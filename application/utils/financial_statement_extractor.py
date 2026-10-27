"""
CoDIR-IA — utils/financial_statement_extractor.py — Since v16.5.70

Module dédié à l'extraction prioritaire des Financial Statements depuis un
PDF de rapport annuel (Annual Report UK / 10-K US / Liasse FR).

Bug racine identifié sur run terrain dossier anglophone coté v16.5.69.1 :
- 18 PJ uploadées (Annual Reports FY23/24/25 ~200 pages chacun)
- Mais Finance n'a cité aucun chiffre [FAIT — Annual Accounts]
- Cause : `extract_text_from_upload` limite à `pdf.pages[:50]`, or les
  Financial Statements sont en fin de PDF (pages 130-180 typiquement).
- Conséquence : Strategic Report / CEO statement lus, mais Income Statement /
  Balance Sheet / Cash Flow non capturés.

Ce module corrige le problème avec une logique en 2 passes :
  1. Pass 1 — Détection : scan léger des pages pour trouver les sections
     clés (Income Statement, Balance Sheet, Cash Flow, Notes, Auditor's Report)
  2. Pass 2 — Extraction prioritaire : lecture complète des pages détectées
     comme contenant des Financial Statements + leurs notes proches

Le résultat est un objet `FinancialStatementsBundle` qui contient :
  - Détection booléenne (financial_statements_detected)
  - Pages identifiées par section (income / balance / cashflow / notes / auditor)
  - Texte extrait par section (limité par budget tokens)
  - Métadonnées (nb pages totales, langue détectée, devise principale)

Exposé pour intégration dans :
  - codir_engine : enrichir attachments_block avec un bloc dédié
  - confidence_scorer : flag `financial_statements_detected` propre
"""

from __future__ import annotations

import logging as _logging_pdfminer_quiet

# v62.9 — silence ciblé du warning pdfminer FontBBox (non bloquant).
# Indispensable ici aussi : ce module peut être importé par des workers.
_logging_pdfminer_quiet.getLogger("pdfminer.pdffont").setLevel(
    _logging_pdfminer_quiet.ERROR)

import hashlib
import io
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


# ── Constantes de détection ─────────────────────────────────────────────────

# Headers de sections financières — multilingue FR + EN
# Priorité : tableaux comptables auditées (Income Statement, Balance Sheet,
# Cash Flow), puis Notes (souvent contiennent les détails ligne par ligne),
# puis Auditor's Report (signe de validation).
SECTION_PATTERNS = {
    # v62.11.2 — les KPIs ajustés et le free cash flow sont souvent publiés
    # dans le Financial Review, bien avant les états IFRS de fin de rapport.
    "financial_review": [
        r"\bfinancial\s+review\b",
        r"\brevue\s+financi[èe]re\b",
    ],
    "income_statement": [
        # EN
        r"\bconsolidated\s+income\s+statement\b",
        r"\bincome\s+statement\b",
        r"\bstatement\s+of\s+(comprehensive\s+)?income\b",
        r"\bstatement\s+of\s+profit\s+(or\s+loss|and\s+loss)\b",
        r"\bprofit\s+and\s+loss\s+account\b",
        # FR — comptes annuels
        r"\bcompte\s+de\s+r[ée]sultat\b",
        r"\b[ée]tat\s+du\s+r[ée]sultat\b",
        # FR — liasse fiscale 2050-2059 (v16.5.75 — Item #8)
        # Liasses CERFA : 2052 = compte de résultat (en liste), 2053 = compte
        # de résultat (en compte). Ces formulaires utilisent des en-têtes
        # comme "Compte de résultat de l'exercice", "Désignation des postes",
        # "Exercice N / N-1", "Total des produits / charges d'exploitation".
        # Cas dossier réseau de soins : 8 plaquettes CAC FR scannées 0 token, bug observé since v16.5.74.
        r"\bliasse\s+fiscale\b",
        r"\b(formulaire|cerfa)\s+205[0-9]\b",
        r"\bd[ée]signation\s+des\s+postes\b",  # en-tête typique des liasses
        r"\btotal\s+des\s+produits\s+(d['']exploitation|financiers)\b",
        r"\btotal\s+des\s+charges\s+(d['']exploitation|financi[èe]res)\b",
        r"\br[ée]sultat\s+(courant\s+)?(avant\s+imp[ôo]ts|net\s+de\s+l['']exercice)\b",
        # Plaquettes CAC : titres usuels
        r"\bcomptes\s+annuels\b",
        r"\b[ée]tats\s+financiers\s+annuels\b",
    ],
    "balance_sheet": [
        # EN
        r"\bconsolidated\s+balance\s+sheet\b",
        r"\bbalance\s+sheet\b",
        r"\bstatement\s+of\s+financial\s+position\b",
        # FR — comptes annuels
        r"\bbilan(\s+(consolidé|comptable|actif|passif))?\b",
        r"\b[ée]tat\s+de\s+la\s+situation\s+financi[èe]re\b",
        # FR — liasse fiscale 2050-2051 (v16.5.75 — Item #8)
        # Liasses CERFA : 2050 = bilan actif, 2051 = bilan passif.
        # En-têtes typiques : "Bilan - Actif", "Bilan - Passif",
        # "Capitaux propres", "Capital ou individuel", "Total actif",
        # "Total passif".
        r"\bbilan\s*[-–]?\s*(actif|passif)\b",
        r"\btotal\s+(de\s+l['']\s*)?actif\b",
        r"\btotal\s+(des?\s+)?passifs?\b",
        r"\bcapitaux\s+propres\b",
        # Plaquettes CAC : pages bilan
        r"\b[ée]tat\s+du\s+bilan\b",
    ],
    "cash_flow": [
        # EN
        r"\bconsolidated\s+(statement\s+of\s+)?cash\s*flows?\b",
        r"\bcash\s*flow\s+statement\b",
        r"\bstatement\s+of\s+cash\s*flows?\b",
        # FR
        r"\btableau\s+(de\s+)?(flux\s+de\s+)?tr[ée]sorerie\b",
        r"\b[ée]tat\s+des\s+flux\s+de\s+tr[ée]sorerie\b",
        # FR — liasse fiscale 2059-G (v16.5.75 — Item #8)
        r"\b(formulaire|cerfa)\s+2059[-–]?[a-z]?\b",
        r"\btableau\s+de\s+financement\b",
    ],
    "equity_changes": [
        # EN
        r"\bstatement\s+of\s+changes?\s+in\s+equity\b",
        r"\bconsolidated\s+statement\s+of\s+(changes?\s+in\s+)?equity\b",
        # FR
        r"\b[ée]tat\s+des\s+(variations?\s+des?\s+)?capitaux\s+propres\b",
        r"\btableau\s+de\s+variation\s+des?\s+capitaux\s+propres\b",
    ],
    "notes": [
        # EN
        r"\bnotes\s+to\s+the\s+(consolidated\s+)?financial\s+statements\b",
        r"\bnotes\s+to\s+the\s+accounts\b",
        # FR — comptes annuels
        r"\bnotes?\s+aux?\s+(comptes\s+(consolidés?|annuels?)|états?\s+financiers?)\b",
        r"\bannexes?\s+aux?\s+comptes\b",
        # FR — liasse fiscale 2057-2058 (v16.5.75 — Item #8)
        # Annexes liasse : 2057 = ventilation CA, 2058A = détermination
        # résultat fiscal, 2058B = déficits/provisions/amortissements.
        r"\bannexe(s)?\s+(comptable|fiscale|aux?\s+états)\b",
        r"\bventilation\s+du\s+(chiffre\s+d['']affaires|CA)\b",
        r"\bd[ée]termination\s+du\s+r[ée]sultat\s+fiscal\b",
    ],
    "auditor": [
        # EN
        r"\bindependent\s+auditor['s]*\s+report\b",
        r"\bauditor['s]*\s+report\s+(to|on)\b",
        r"\breport\s+of\s+the\s+independent\s+auditor\b",
        # FR
        r"\brapport\s+(des?|du)\s+commissaires?\s+aux?\s+comptes?\b",
        r"\bopinion\s+du\s+commissaire\b",
    ],
    "directors_report": [
        # EN
        r"\bdirectors['s]*\s+report\b",
        r"\bstrategic\s+report\b",
        # FR
        r"\brapport\s+du\s+conseil\s+d[''](administration|surveillance)\b",
        r"\brapport\s+de\s+gestion\b",
    ],
}

# v62.13.9.4.40 — ÉTATS AU FORMAT AMÉRICAIN (formulaires SEC, US GAAP). Les intitulés sont au
# pluriel (« Balance Sheets », « Statements of Operations », « Statements of Cash Flows »,
# « Stockholders' Equity ») ; les motifs historiques, au singulier et au format IFRS/britannique,
# ne les reconnaissaient pas. Ces motifs exigent l'INTITULÉ SEUL SUR SA LIGNE : un rapport
# d'auditeur ou une note qui citent « the consolidated balance sheets » dans une phrase ne
# sont pas des états. Une détection par intitulé seul l'emporte sur les détections faibles
# de la même section (voir la consolidation de detect_sections_in_pdf).
_US_FORM_TAIL = r"\s*(?:\((?:continued|unaudited)\))?\s*$"
_US_FORM_HEADINGS = {
    "balance_sheet": [r"^\s*(?:consolidated\s+|combined\s+)?balance\s+sheets" + _US_FORM_TAIL],
    "income_statement": [r"^\s*(?:consolidated\s+|combined\s+)?statements\s+of\s+(?:operations|income|earnings)"
                         r"(?:\s+and\s+comprehensive\s+(?:income|loss))?" + _US_FORM_TAIL],
    "cash_flow": [r"^\s*(?:consolidated\s+|combined\s+)?statements\s+of\s+cash\s+flows" + _US_FORM_TAIL],
    "equity_changes": [r"^\s*(?:consolidated\s+|combined\s+)?statements\s+of\s+(?:changes\s+in\s+)?"
                       r"(?:stockholders|shareholders)[\u2019']?\s+equity(?:\s*\(deficit\))?" + _US_FORM_TAIL],
    "notes": [r"^\s*notes\s+to\s+(?:the\s+)?consolidated\s+financial\s+statements" + _US_FORM_TAIL],
    "auditor": [r"^\s*report\s+of\s+independent\s+registered\s+public\s+accounting\s+firm" + _US_FORM_TAIL],
}
_US_FORM_COMPILED = {section: [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in pats]
                     for section, pats in _US_FORM_HEADINGS.items()}
_US_FORM_MARK = "US_FORM:"

# Compile une seule fois (perf)
_COMPILED_PATTERNS = {
    section: [re.compile(p, re.IGNORECASE) for p in patterns]
    for section, patterns in SECTION_PATTERNS.items()
}

# Sections prioritaires — l'ordre détermine l'allocation budget tokens
PRIORITY_ORDER = (
    "financial_review",
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "equity_changes",
    "notes",
    "auditor",
    "directors_report",
)

# Budget tokens par défaut quand on extrait le bloc complet
DEFAULT_TOKEN_BUDGET = 12000

# v62.11.2 — contrats du scan financier profond restaurés. Ces constantes
# étaient consommées par app._prepare_documents_for_run mais avaient disparu
# du module lors d'un refactor, ce qui déclenchait un ImportError silencieusement
# absorbé et neutralisait tout le deep scan. Les valeurs sont celles du dernier
# calibrage documenté v16.5.74 pour les corpus riches (dossier anglophone coté 18 PDF).
FS_GLOBAL_BUDGET = 200_000       # enveloppe cumulée de texte financier extrait (9.4.57 : 100 000 → 200 000)
FS_PER_PDF_CAP = 50_000          # plafond par PDF prioritaire (9.4.57 : 20 000 → 50 000)
FS_MAX_DEEP_SCAN_PDFS = 25       # couvre les lots terrain de 18-20 documents

# v62.11.3.1 — version fonctionnelle du pipeline documentaire. Toute évolution
# susceptible de modifier le bloc financier (priorité, extraction, parsing) doit
# incrémenter cette valeur afin d'invalider les caches de session antérieurs.
FS_PIPELINE_CACHE_SCHEMA = "financial_deep_scan_v62.13.9.4.40"   # v62.13.9.4.40 — états au format américain
FS_PRIORITY_POLICY_VERSION = "financial_pdf_priority_v6_reserved_budget"

# Limite max pages à scanner (perf)
MAX_PAGES_TO_SCAN = 400  # bien au-delà des 50 actuels — couvre Annual Reports lourds


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class SectionDetection:
    """Une section détectée dans un PDF."""
    section_name: str          # ex: "income_statement"
    first_page: int            # 1-indexed
    matched_pattern: str       # le regex qui a matché (debug)
    header_line: str           # la ligne où le header a été trouvé


@dataclass
class FinancialStatementsBundle:
    """
    Résultat de l'extraction des Financial Statements depuis un PDF.

    Sert de contrat entre financial_statement_extractor et codir_engine /
    confidence_scorer.
    """
    filename: str
    total_pages: int
    financial_statements_detected: bool
    sections_detected: List[SectionDetection] = field(default_factory=list)
    extracted_text_by_section: Dict[str, str] = field(default_factory=dict)
    total_chars_extracted: int = 0
    tokens_estimate: int = 0
    notes: List[str] = field(default_factory=list)  # diagnostic / warnings

    def has_section(self, section: str) -> bool:
        return any(d.section_name == section for d in self.sections_detected)

    def detected_section_names(self) -> List[str]:
        return sorted({d.section_name for d in self.sections_detected})

    def to_diag_dict(self) -> Dict[str, Any]:
        """Représentation compacte pour diagnostics_ia.csv."""
        return {
            "filename": self.filename,
            "total_pages": self.total_pages,
            "financial_statements_detected": self.financial_statements_detected,
            "sections_detected": self.detected_section_names(),
            "n_sections": len(self.detected_section_names()),
            "tokens_estimate": self.tokens_estimate,
            "total_chars": self.total_chars_extracted,
            "notes": self.notes,
        }


# ── Détection (Pass 1) ───────────────────────────────────────────────────────

def _looks_like_toc_page(text: str) -> bool:
    """
    Patch v16.5.70.1 (audit ChatGPT round 5) — Détection page sommaire.

    Sur un Annual Report UK comme dossier anglophone coté, les titres "Consolidated Income
    Statement / Balance Sheet / Cash Flow" apparaissent dès les premières
    pages dans le sommaire :

        Contents
        Strategic Report ......................... 2
        Consolidated Income Statement ............. 135
        Consolidated Balance Sheet ............... 136
        Cash Flow Statement ...................... 138
        Notes to the Financial Statements ........ 145

    Sans cette détection, Pass 1 capture toutes les sections en page 3 (le
    sommaire), puis Pass 2 extrait les pages 3-10 (chairman statement, pas
    les vrais comptes).

    Patch v16.5.70.1 P0-1 — Heuristique TOC RAFFINÉE :
    On exige soit :
      (1) Header explicite "Contents/Table of contents/Sommaire" en début
          de page (1ᵉʳ 200 chars)
      OU
      (2) Forte densité de patterns "............N" (lignes type entrée TOC)
          ≥ 3 occurrences

    Critère initial "5 lignes courtes avec chiffres en fin" RETIRÉ car il
    matchait aussi les vraies pages d'Income Statement (Revenue 2,968,
    Operating profit 418, etc.). L'ambiguïté entre page TOC et page comptes
    se résout par le pattern "....." (signature unique du TOC).
    """
    if not text:
        return False

    # Pattern 1 : header explicite TOC en DÉBUT de page
    head = text[:200].lower()
    toc_keywords = ["contents", "table of contents",
                    "sommaire", "table des matières"]
    has_toc_header = any(kw in head for kw in toc_keywords)

    # Pattern 2 : densité de "..........N" (lignes type entrée TOC)
    toc_line_pattern = re.compile(r"\.{3,}\s*\d{1,3}\b")
    n_toc_lines = len(toc_line_pattern.findall(text))

    # Décision raffinée v16.5.70.1 :
    # - Header explicite ET au moins 1 ligne TOC pattern (évite faux positif
    #   sur pages narratives qui mentionnent "Contents" en passant)
    # - OU forte densité de patterns "....N" (≥ 3) sans ambiguïté possible
    if has_toc_header and n_toc_lines >= 1:
        return True
    if n_toc_lines >= 3:
        return True
    return False


# Mots-clés qui indiquent du contenu financier RÉEL (pas un titre seul).
# Une page Income Statement valide doit contenir des chiffres / mots-clés
# comme revenue, profit, total assets, cash, equity, etc.
_FINANCIAL_CONTENT_KEYWORDS = re.compile(
    r"\b(revenue|turnover|sales|gross\s+profit|operating\s+profit|profit\s+before\s+tax|"
    r"net\s+income|total\s+assets|total\s+equity|cash\s+and\s+cash\s+equivalents|"
    r"net\s+cash|trade\s+receivables|borrowings|amortisation|depreciation|"
    r"chiffre\s+d['']affaires|résultat\s+net|résultat\s+d['']exploitation|"
    r"capitaux\s+propres|trésorerie|emprunts|dotations)\b",
    re.IGNORECASE
)


def _page_has_financial_content(text: str, header_is_core: bool = False) -> bool:
    """
    Patch v16.5.70.1 — Vérifie qu'une page contient du VRAI contenu financier
    (chiffres + termes comptables typiques), pas juste un titre dans un sommaire.

    Une page valide d'Income Statement doit contenir au moins 2 occurrences
    de mots-clés financiers ET au moins 3 chiffres (typiquement format 1,234
    ou 1.234,56 ou 1234).
    """
    if not text:
        return False

    n_kw = len(_FINANCIAL_CONTENT_KEYWORDS.findall(text))
    # Chiffres : groupes de 3+ digits (montants typiques 100, 1,234, 12,345)
    n_digits_groups = len(re.findall(r"\d{3,}|\d{1,3}[,.\s]\d{3}", text))

    if header_is_core:
        # v62.12.1 (T-FI-5) — un en-tête d'ÉTAT canonique ("Consolidated
        # balance sheet"…) accompagné d'au moins une ligne tabulaire chiffrée
        # EST du contenu financier : les états autonomes courts (Financial
        # Statements séparés, liasses) n'atteignent pas toujours 2 mots-clés
        # génériques. Le garde anti-sommaire reste appliqué en amont, et une
        # ligne de TOC ne porte qu'UN nombre (le folio), jamais deux colonnes.
        tabular_rows = sum(
            1 for line in text.splitlines()
            if len(re.findall(r"\d{3,}|\d{1,3}[,.\s]\d{3}", line)) >= 2
        )
        if n_digits_groups >= 2 and tabular_rows >= 1:
            return True

    # Critère : au moins 2 mots-clés financiers ET 2 chiffres significatifs
    # (relâché de 3 → 2 pour ne pas rater les pages de tableaux courts type
    # "Revenue 100, Operating profit 50, Total assets 800").
    return n_kw >= 2 and n_digits_groups >= 2


def _cover_text_first_page(pdf_bytes: bytes, max_chars: int = 400) -> str:
    """v62.12.1 — texte de couverture (page 1) pour overrides de détection."""
    try:
        import pypdfium2 as pdfium
        import io as _io
        pdf = pdfium.PdfDocument(_io.BytesIO(pdf_bytes))
        try:
            if len(pdf) < 1:
                return ""
            tp = pdf[0].get_textpage()
            try:
                return (tp.get_text_range() or "")[:max_chars]
            finally:
                tp.close()
        finally:
            pdf.close()
    except Exception:
        return ""


def detect_sections_in_pdf(pdf_bytes: bytes, filename: str = "") -> List[SectionDetection]:
    """
    Pass 1 — Scan léger d'un PDF pour détecter les sections financières.

    v62.11.2 : le scan intégral utilise d'abord pypdfium2, déjà fourni par
    pdfplumber, afin de parcourir un Annual Report de plusieurs centaines de
    pages en quelques secondes. L'ancien chemin pdfplumber reste le repli de
    compatibilité. La validation anti-sommaire et les critères financiers sont
    strictement conservés.
    """
    all_detections: Dict[str, List[SectionDetection]] = {
        section: [] for section in _COMPILED_PATTERNS
    }

    def _consume_page(page_idx: int, text: str) -> None:
        if not text:
            return
        if _looks_like_toc_page(text):
            return
        head_text = "\n".join(text.splitlines()[:20])
        for section_name, compiled in _COMPILED_PATTERNS.items():
            # v62.13.9.4.40 — intitulé américain seul sur sa ligne : détection forte, testée d'abord
            compiled = [(_US_FORM_MARK, p) for p in _US_FORM_COMPILED.get(section_name, [])] + \
                       [("", p) for p in compiled]
            for _mark40, pat in compiled:
                if not pat.search(head_text):
                    continue
                requires_financial_content = section_name in (
                    "financial_review", "income_statement", "balance_sheet",
                    "cash_flow", "equity_changes", "notes",
                )
                core_statement = section_name in (
                    "income_statement", "balance_sheet", "cash_flow",
                    "equity_changes", "notes",
                )
                if requires_financial_content and not _page_has_financial_content(
                        text, header_is_core=core_statement):
                    continue
                matched_line = ""
                for line in head_text.splitlines():
                    if pat.search(line):
                        matched_line = line.strip()[:120]
                        break
                all_detections[section_name].append(SectionDetection(
                    section_name=section_name,
                    first_page=page_idx,
                    matched_pattern=_mark40 + pat.pattern,
                    header_line=matched_line,
                ))
                break

    total_pages = 0
    fast_path_ok = False

    # Fast path — PDFium text layer.  This avoids pdfplumber layout analysis on
    # every page; only the few selected pages are later reopened by pdfplumber.
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            total_pages = len(pdf)
            for page_idx in range(min(total_pages, MAX_PAGES_TO_SCAN)):
                page = pdf[page_idx]
                text_page = None
                try:
                    text_page = page.get_textpage()
                    text = text_page.get_text_range() or ""
                    _consume_page(page_idx + 1, text)
                except Exception:
                    continue
                finally:
                    try:
                        if text_page is not None:
                            text_page.close()
                    except Exception:
                        pass
                    try:
                        page.close()
                    except Exception:
                        pass
            fast_path_ok = True
        finally:
            try:
                pdf.close()
            except Exception:
                pass
    except Exception:
        fast_path_ok = False

    # Compatibility fallback — kept for unusual PDFium failures.
    if not fast_path_ok:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                for page_idx, page in enumerate(
                        pdf.pages[:MAX_PAGES_TO_SCAN], start=1):
                    try:
                        _consume_page(page_idx, page.extract_text() or "")
                    except Exception:
                        continue
        except Exception:
            return []

    last_third_start = max(1, int(total_pages * 0.5))
    final_detections: List[SectionDetection] = []
    for section_name, dets in all_detections.items():
        if not dets:
            continue
        # A Financial Review is a continuous early section whose heading is
        # repeated on every page. Taking the last occurrence loses revenue,
        # margin and other opening KPI pages. For audited statements, the
        # historic late-page preference remains appropriate.
        if section_name == "financial_review":
            final_detections.append(dets[0])
            continue
        # v62.13.9.4.40 — un intitulé seul sur sa ligne (format américain) est une preuve plus forte
        # que la préférence historique pour les pages tardives, faite pour les rapports annuels
        # britanniques (états en fin de document) : dans un 10-K, les états sont au milieu.
        _strong40 = [d for d in dets if str(d.matched_pattern).startswith(_US_FORM_MARK)]
        if _strong40:
            final_detections.append(_strong40[0])
            continue
        late_dets = [d for d in dets if d.first_page >= last_third_start]
        if late_dets:
            final_detections.append(late_dets[0])
        else:
            final_detections.append(dets[-1])
    return final_detections


# ── Extraction prioritaire (Pass 2) ──────────────────────────────────────────

def extract_financial_sections(
    pdf_bytes: bytes,
    detections: List[SectionDetection],
    *,
    pages_per_section: int = 8,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> Tuple[Dict[str, str], int]:
    """
    Pass 2 — Lit les pages identifiées par Pass 1 + leurs voisines proches
    (typiquement : 1 page header + 6-8 pages tableaux/notes).

    Retourne un dict {section_name: extracted_text} et le total chars utilisés.

    Stratégie d'allocation :
      - Sections prioritaires (income/balance/cashflow) reçoivent plus de pages
      - Notes peuvent être longues mais utiles → 8 pages max
      - Auditor's Report : 3-4 pages suffisent (court)

    Limité par token_budget global pour éviter explosion contexte.
    """
    if not detections:
        return ({}, 0)

    try:
        import pdfplumber
    except Exception:
        return ({}, 0)

    extracted: Dict[str, str] = {}
    total_chars = 0
    max_chars = token_budget * 4  # heuristique 1 token ≈ 4 chars

    # Allocation pages par section
    pages_alloc = {
        "financial_review": 6,
        "income_statement": 6,
        "balance_sheet": 6,
        "cash_flow": 6,
        "equity_changes": 4,
        "notes": pages_per_section,  # 8
        "auditor": 4,
        "directors_report": 5,
    }

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total_pages_pdf = len(pdf.pages)
            # Trier par priorité pour respecter l'allocation budget
            ordered = sorted(
                detections,
                key=lambda d: PRIORITY_ORDER.index(d.section_name)
                if d.section_name in PRIORITY_ORDER else 999
            )
            for det in ordered:
                if total_chars >= max_chars:
                    break
                n_pages = pages_alloc.get(det.section_name, 4)
                start = det.first_page  # 1-indexed
                end = min(start + n_pages, total_pages_pdf + 1)

                section_chunks = []
                for page_idx in range(start, end):
                    try:
                        page = pdf.pages[page_idx - 1]  # convert 1-idx → 0-idx
                        text = page.extract_text() or ""
                    except Exception:
                        continue
                    if not text.strip():
                        continue
                    section_chunks.append(f"-- p.{page_idx} --\n{text}")
                    # Tables si dispos
                    try:
                        tables = page.extract_tables() or []
                        for t in tables[:2]:
                            for row in t[:25]:
                                row_text = " | ".join(
                                    "" if c is None else str(c).strip()
                                    for c in row
                                )
                                if row_text.strip():
                                    section_chunks.append(row_text)
                    except Exception:
                        pass

                section_text = "\n".join(section_chunks).strip()
                if section_text:
                    # Tronquer si trop volumineux pour respecter budget
                    remaining = max_chars - total_chars
                    if len(section_text) > remaining:
                        section_text = section_text[:remaining] + "\n[... section tronquée par budget tokens ...]"
                    extracted[det.section_name] = section_text
                    total_chars += len(section_text)
    except Exception:
        return (extracted, total_chars)

    return (extracted, total_chars)


# ── Entry point principal ────────────────────────────────────────────────────

def extract_financial_statements_from_pdf(
    pdf_bytes: bytes,
    filename: str = "",
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> FinancialStatementsBundle:
    """
    Pipeline complet :
      1. Détection Pass 1
      2. Extraction Pass 2 sur les sections détectées
      3. Construction du Bundle final avec metadata

    Retourne TOUJOURS un FinancialStatementsBundle (jamais None / exception).
    Si rien n'est détecté ou erreur → bundle.financial_statements_detected = False.
    """
    bundle = FinancialStatementsBundle(
        filename=filename,
        total_pages=0,
        financial_statements_detected=False,
    )

    if not pdf_bytes:
        bundle.notes.append("PDF vide ou bytes manquants")
        return bundle

    # ─── v16.5.75.3 — Sprint #2 : skip rapide si PDF scanné ────────────────
    # Sur PDF scanné sans couche texte, le scan profond (jusqu'à 400 pages)
    # ne retournera rien (CoDIR-IA n'a pas d'OCR intégré). Économie typique :
    # 5-30s par PDF scanné, libérée pour les vrais PDFs natifs du batch.
    try:
        from utils.attachments import pdf_quick_native_check
        if not pdf_quick_native_check(pdf_bytes):
            bundle.notes.append(
                "PDF scanné détecté (peu/pas de texte extractible) — scan profond skippé. "
                "OCR requis pour traiter ce document (non disponible dans CoDIR-IA v16.5.75.3)."
            )
            # On essaie quand même de récupérer total_pages pour traçabilité
            try:
                import pdfplumber as _pdfp
                with _pdfp.open(io.BytesIO(pdf_bytes)) as _pdf:
                    bundle.total_pages = len(_pdf.pages)
            except Exception:
                pass
            return bundle
    except Exception:
        # Fail-open : si le check plante (cas exotique), on continue le scan normal
        pass
    # ────────────────────────────────────────────────────────────────────────

    # Pass 1 — Détection
    try:
        detections = detect_sections_in_pdf(pdf_bytes, filename)
    except Exception as e:
        bundle.notes.append(f"Erreur Pass 1 (détection) : {type(e).__name__}: {str(e)[:100]}")
        return bundle

    bundle.sections_detected = detections

    # Récupérer total pages pour metadata
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            bundle.total_pages = len(pdf.pages)
    except Exception:
        bundle.total_pages = 0

    if not detections:
        bundle.notes.append(
            "Aucune section financière détectée — PDF probablement non structuré "
            "comme rapport annuel, ou en image scannée (OCR requis)."
        )
        return bundle

    # Pass 2 — Extraction prioritaire
    try:
        extracted_dict, total_chars = extract_financial_sections(
            pdf_bytes, detections, token_budget=token_budget
        )
    except Exception as e:
        bundle.notes.append(f"Erreur Pass 2 (extraction) : {type(e).__name__}: {str(e)[:100]}")
        return bundle

    bundle.extracted_text_by_section = extracted_dict
    bundle.total_chars_extracted = total_chars
    bundle.tokens_estimate = max(1, total_chars // 4)

    # Critère : "financial_statements_detected" requis au moins 2 sections
    # parmi income/balance/cashflow OU 1 section + Notes.
    core_sections_found = sum(
        1 for s in ("income_statement", "balance_sheet", "cash_flow")
        if bundle.has_section(s)
    )
    has_notes = bundle.has_section("notes")
    has_financial_review = bundle.has_section("financial_review")

    _cover_txt = _cover_text_first_page(pdf_bytes)
    _title_override = bool(re.search(
        r"financial\s+statements|comptes\s+annuels|liasse\s+fiscale|"
        r"[ée]tats?\s+financiers", _cover_txt, re.IGNORECASE))
    if (core_sections_found >= 2
            or (core_sections_found >= 1 and has_notes)
            or (core_sections_found >= 1 and _title_override)
            # v62.12.2 — un Financial Review courant contenant des KPI
            # critiques est un document complémentaire valide même sans bilan.
            # Il doit pouvoir compléter un jeu d'états primaires incomplet.
            or has_financial_review):
        if _title_override and core_sections_found < 2 and not has_notes:
            bundle.notes.append(
                "Override v62.12.1 : couverture 'Financial Statements/"
                "comptes annuels' + 1 section core → detected")
        bundle.financial_statements_detected = True
        bundle.notes.append(
            f"✓ Financial Statements détectés et extraits "
            f"({core_sections_found} sections core + notes={has_notes} + review={has_financial_review}, "
            f"~{bundle.tokens_estimate} tokens)"
        )
    else:
        bundle.notes.append(
            f"Sections détectées mais pas suffisamment pour confirmer Financial Statements "
            f"(core={core_sections_found}, notes={has_notes})"
        )

    return bundle


# ── Helper : construit un bloc texte dédié pour injection prompt ────────────

def build_financial_statements_block(
    bundles: List[FinancialStatementsBundle],
    lang: str = "fr",
) -> str:
    """
    Concatène plusieurs bundles (un par PDF d'Annual Report) en un bloc texte
    structuré injecté dans le prompt Finance / DG / Synthèse.

    Le bloc identifie clairement :
      - Le nom du fichier source
      - La section (Income Statement, Balance Sheet, etc.)
      - Le numéro de page (pour traçabilité [FAIT — Annual Report p.XX])
    """
    if not bundles:
        return ""

    if lang == "fr":
        header = "📊 ÉTATS FINANCIERS EXTRAITS DES PIÈCES JOINTES (Since v16.5.70) :"
        section_labels = {
            "financial_review": "📌 Revue financière / indicateurs ajustés",
            "income_statement":  "📈 Compte de résultat consolidé",
            "balance_sheet":     "📊 Bilan consolidé",
            "cash_flow":         "💧 Tableau des flux de trésorerie",
            "equity_changes":    "🔄 Variation des capitaux propres",
            "notes":             "📝 Notes annexes aux états financiers",
            "auditor":           "✓ Rapport de l'auditeur indépendant",
            "directors_report":  "📋 Rapport de gestion / Strategic Report",
        }
    else:
        header = "📊 FINANCIAL STATEMENTS EXTRACTED FROM ATTACHMENTS (Since v16.5.70):"
        section_labels = {
            "financial_review": "📌 Financial Review / adjusted KPIs",
            "income_statement":  "📈 Consolidated Income Statement",
            "balance_sheet":     "📊 Consolidated Balance Sheet",
            "cash_flow":         "💧 Cash Flow Statement",
            "equity_changes":    "🔄 Statement of Changes in Equity",
            "notes":             "📝 Notes to the Financial Statements",
            "auditor":           "✓ Independent Auditor's Report",
            "directors_report":  "📋 Directors' / Strategic Report",
        }

    parts = [header, ""]

    for bundle in bundles:
        if not bundle.financial_statements_detected:
            continue
        parts.append(f"--- 📄 {bundle.filename} (total {bundle.total_pages} pages) ---")
        parts.append("")
        for section in PRIORITY_ORDER:
            text = bundle.extracted_text_by_section.get(section, "")
            if not text:
                continue
            label = section_labels.get(section, section)
            parts.append(f"### {label}")
            parts.append(text)
            parts.append("")
        parts.append("")

    return "\n".join(parts).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Patch v16.5.70.2 (audit ChatGPT round 6) — Priorisation PDF avec FY dynamique
# ─────────────────────────────────────────────────────────────────────────────
# Bug détecté audit round 6 : sur 18 PDFs dossier anglophone coté (Annual Reports + Strategic
# Reports + Governance Reports + Preliminary Results + ...), v16.5.70.1 (Since v16.5.70.1) scanne
# tous les PDFs sans priorisation. Conséquence : budget tokens consommé par les
# Strategic Reports avant d'arriver aux Annual Reports.
#
# Apprentissage Robin (audit round 6) : si on hardcode "FY25/FY24/FY23" dans
# la priorisation, en avril 2027 il faudra repatcher pour FY26/FY25/FY24. Anti-
# pattern récurrent (cf. banner ASCII v16.5.67 hardcodée corrigée Session 7).
# Solution : calcul dynamique relatif à la date du run.

def _compute_fy_priority_keywords(today=None) -> List[str]:
    """
    Calcule les keywords FY prioritaires de manière DYNAMIQUE à partir de
    la date du run.

    Sur les UK Annual Reports, FY = année fiscale qui se termine généralement
    en mars/avril. Donc en avril 2026, FY courante = FY26 (clôture mars 2026).
    En janvier 2026 (avant avril), FY courante = FY25 (dernière clôturée).

    Génère les variantes orthographiques courantes :
      - fy25, fy24, fy23 (forme compacte)
      - fy_2025, fy_2024 (forme avec underscore + année 4 chiffres)
      - 2024_25, 2023_24 (forme "annual_report_2024_25.pdf")
      - 2025, 2024, 2023 (année simple dans le nom)

    Apprentissage Robin v16.5.70.2 : aucun hardcode FY25/FY24 → l'heuristique
    se met à jour automatiquement chaque année.
    """
    from datetime import datetime
    today = today or datetime.now()
    year = today.year
    # FY courante : si on est avant avril, FY clôturée = année précédente
    fy_n = year if today.month >= 4 else year - 1
    fy_n_minus_1 = fy_n - 1
    fy_n_minus_2 = fy_n - 2

    keywords = []
    for fy in (fy_n, fy_n_minus_1, fy_n_minus_2):
        keywords.extend([
            f"fy{fy % 100:02d}",       # fy26, fy25, fy24
            f"fy_{fy}",                # fy_2026, fy_2025, fy_2024
            f"fy{fy}",                 # fy2026 (variante sans underscore)
            f"{fy - 1}_{fy % 100:02d}",  # 2025_26, 2024_25 (UK fiscal year span)
            f"{fy}",                   # 2026, 2025, 2024 (année simple)
        ])
    return keywords


# Politique de priorité des documents financiers — v62.11.3.1.
#
# Hiérarchie explicite :
#   1. rapport annuel / comptes audités / 10-K / 20-F ;
#   2. résultats annuels préliminaires ;
#   3. résultats semestriels / intermédiaires ;
#   4. présentation investisseurs ;
#   5. documents secondaires (strategic, governance, sustainability) pénalisés.
#
# Les graphies tiret / underscore / espace sont équivalentes. La fonction
# publique score_pdf_for_fs_extraction fournit en plus une trace auditable
# (classe, bonus FY, pénalité) consommée par diagnostics_ia.
_FILENAME_FINANCIAL_STATEMENTS_KEYWORDS = [
    "audited_accounts", "audited accounts",
    "audited_financial_statements", "audited financial statements",
    "financial_statements", "financialstatements", "financial statements",
    "statutory_accounts", "statutory accounts",
    "comptes_annuels", "comptes annuels", "comptes-annuels",
    "états financiers", "etats financiers",
    "10-k", "10k", "form_10-k", "form 10-k",
    "20-f", "20f", "form_20-f", "form 20-f",
]

_FILENAME_ANNUAL_REPORT_KEYWORDS = [
    "annual_report", "annualreport", "annual report",
    "rapport_annuel", "rapportannuel", "rapport annuel",
]

_FILENAME_PRELIMINARY_KEYWORDS = [
    "preliminary_results", "preliminary results",
    "full_year_results", "full year results",
    "annual_results", "annual results",
    "final_results", "final results",
    "results_announcement", "results announcement",
]

_FILENAME_INTERIM_KEYWORDS = [
    "interim_results", "interim results", "interim",
    "half_year", "half year", "half-year",
    "quarterly_results", "quarterly results",
]

_FILENAME_INVESTOR_PRESENTATION_KEYWORDS = [
    "investor_presentation", "investor presentation",
    "results_presentation", "results presentation",
    "analyst_presentation", "analyst presentation",
]

_FILENAME_DEPRIORITY_KEYWORDS = [
    "strategic_report", "strategic report", "strategicreport",
    "governance_report", "governance report", "governancereport",
    "csr_report", "csr report", "sustainability_report",
    "sustainability report", "sustainability",
    "remuneration_report", "remuneration report",
    "press_release", "press release", "communique",
]


def _normalize_priority_filename(text: str) -> str:
    """Normalise casse et séparateurs pour un matching stable."""
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")



def _first_matching_keyword(name_norm: str, keywords: List[str]) -> str:
    for keyword in keywords:
        if _normalize_priority_filename(keyword) in name_norm:
            return keyword
    return ""


_PRIORITY_PEEK_MAX_PAGES = 5
_PRIORITY_PEEK_MAX_CHARS = 16_000
_SHORT_83_RE = re.compile(r"(?:^|[^A-Za-z0-9])[^./\\]{1,6}~\d(?:\.[A-Za-z0-9]{1,4})?$", re.I)


def _peek_pdf_priority_text(pdf_bytes: bytes,
                            *,
                            max_pages: int = _PRIORITY_PEEK_MAX_PAGES,
                            max_chars: int = _PRIORITY_PEEK_MAX_CHARS
                            ) -> Dict[str, Any]:
    """Read a tiny, non-OCR priority hint from PDF metadata + opening pages.

    Terrain v62.11.3.1 exposed that Windows/browser uploads can reach Streamlit
    with 8.3 aliases such as ``BUC381~1.PDF``.  Filename-only ranking then gives
    every document the same score and can exhaust the global budget before the
    current Annual Report.  This helper never attempts OCR and never builds the
    financial ledger; it only extracts enough native text to classify and date
    the document before the expensive scan.
    """
    out: Dict[str, Any] = {
        "status": "EMPTY",
        "pages_read": 0,
        "chars": 0,
        "metadata_title": "",
        "metadata_subject": "",
        "text": "",
        "error": "",
    }
    if not pdf_bytes:
        return out
    chunks: List[str] = []
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            try:
                meta = pdf.get_metadata_dict() or {}
            except Exception:
                meta = {}
            title = str(meta.get("Title") or meta.get("title") or "").strip()
            subject = str(meta.get("Subject") or meta.get("subject") or "").strip()
            out["metadata_title"] = title[:500]
            out["metadata_subject"] = subject[:500]
            if title:
                chunks.append(title)
            if subject:
                chunks.append(subject)
            for page_idx in range(min(len(pdf), max(1, int(max_pages)))):
                if sum(len(x) for x in chunks) >= max_chars:
                    break
                page = pdf[page_idx]
                text_page = None
                try:
                    text_page = page.get_textpage()
                    txt = (text_page.get_text_range() or "").strip()
                    if txt:
                        chunks.append(txt)
                    out["pages_read"] += 1
                except Exception:
                    continue
                finally:
                    try:
                        if text_page is not None:
                            text_page.close()
                    except Exception:
                        pass
                    try:
                        page.close()
                    except Exception:
                        pass
        finally:
            try:
                pdf.close()
            except Exception:
                pass
        joined = "\n".join(chunks)[:max_chars]
        out.update({
            "status": "OK" if joined else "NO_TEXT",
            "chars": len(joined),
            "text": joined,
        })
        return out
    except Exception as exc:
        out["status"] = "ERROR"
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out


def _priority_period_year(text: str, today=None) -> int | None:
    """Return a plausible fiscal end year, never a CERFA form number.

    The legacy ``max(20xx)`` rule interpreted French form identifiers 2050 to
    2059 as years.  v62.12 gives precedence to explicit fiscal/date patterns,
    excludes CERFA codes and rejects implausible future years.
    """
    from datetime import datetime
    blob = str(text or "")
    now = today or datetime.now()
    max_year = int(now.year) + 2
    split_years: list[int] = []
    for m in re.finditer(r"\b(?:FY\s*)?(20\d{2})\s*[/\-]\s*(\d{2}|20\d{2})\b", blob, re.I):
        second = int(m.group(2))
        y = second if second >= 2000 else 2000 + second
        if 2000 <= y <= max_year and y not in range(2050, 2060):
            split_years.append(y)
    if split_years:
        return max(split_years)
    explicit: list[int] = []
    patterns = (
        r"\b(?:year|exercise|exercice|FY)\s*(?:ended|clos|ending|cl[oô]tur[ée])?[^\n]{0,40}\b(20\d{2})\b",
        r"\b(?:ended|ending|clos\s+le|cl[oô]tur[ée]\s+le)\s+\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+(20\d{2})\b",
        r"\b(?:annual\s+report|rapport\s+annuel|financial\s+statements|comptes\s+annuels)[^\n]{0,30}\b(20\d{2})\b",
    )
    for pat in patterns:
        explicit.extend(int(x) for x in re.findall(pat, blob, re.I))
    explicit = [y for y in explicit if 2000 <= y <= max_year and y not in range(2050, 2060)]
    if explicit:
        return max(explicit)
    years: list[int] = []
    for m in re.finditer(r"\b(20\d{2})\b", blob):
        y = int(m.group(1))
        left = blob[max(0, m.start()-25):m.start()].lower()
        if y in range(2050, 2060) and re.search(r"(?:cerfa|formulaire|liasse|imprim[ée]|n[°o])\s*$", left):
            continue
        if 2000 <= y <= max_year and y not in range(2050, 2060):
            years.append(y)
    return max(years) if years else None


def score_pdf_for_fs_extraction(filename: str, today=None,
                                content_hint: str = "",
                                priority_peek: Optional[Mapping[str, Any]] = None
                                ) -> Dict[str, Any]:
    """Return a serialisable priority score for a PDF.

    v62.11.3.2 keeps filename ranking for normal uploads, but augments it with a
    native-text cover/metadata peek.  This closes the Windows 8.3 alias class:
    ``BUC381~1.PDF`` can still be recognised as the current Annual Report from
    the text printed on its cover.  No OCR and no financial fact extraction are
    performed here.
    """
    name = Path(str(filename or "")).name
    name_norm = _normalize_priority_filename(name)
    hint = str(content_hint or "")
    hint_norm = _normalize_priority_filename(hint)
    score = 100
    document_class = "other"
    class_bonus = 0
    matched_keyword = ""
    matched_keyword_source = ""

    peek = dict(priority_peek or {})
    metadata_title = str(peek.get("metadata_title") or "")
    metadata_subject = str(peek.get("metadata_subject") or "")
    _title_lines = []
    for _line in str(hint or "").splitlines():
        _clean_line = re.sub(r"\s+", " ", _line).strip()
        if not _clean_line or _clean_line.lower() in {"untitled", "unspecified", "none"}:
            continue
        _title_lines.append(_clean_line)
        if len(_title_lines) >= 2:
            break
    cover_head = " ".join(_title_lines)[:320]
    _meta_parts = [x for x in (metadata_title, metadata_subject)
                   if x and x.strip().lower() not in {"untitled", "unspecified", "none"}]
    title_blob = " ".join(_meta_parts + ([cover_head] if cover_head else []))
    title_norm = _normalize_priority_filename(title_blob)
    document_subclass = ""

    # Filename and actual cover/title are authoritative.  Body/TOC mentions
    # are fallback only: an Annual Report often contains the words "Financial
    # Statements" in its contents and must not be misclassified.
    fs_name = _first_matching_keyword(name_norm, _FILENAME_FINANCIAL_STATEMENTS_KEYWORDS)
    ar_name = _first_matching_keyword(name_norm, _FILENAME_ANNUAL_REPORT_KEYWORDS)
    fs_title = _first_matching_keyword(title_norm, _FILENAME_FINANCIAL_STATEMENTS_KEYWORDS)
    ar_title = _first_matching_keyword(title_norm, _FILENAME_ANNUAL_REPORT_KEYWORDS)
    if ar_name or ar_title:
        document_class = "audited_or_annual"
        document_subclass = "annual_report"
        class_bonus = 90
        matched_keyword = ar_name or ar_title
        matched_keyword_source = "filename" if ar_name else "content_peek"
        score += class_bonus
    elif fs_name or fs_title:
        document_class = "audited_or_annual"
        document_subclass = "financial_statements_primary"
        class_bonus = 100
        matched_keyword = fs_name or fs_title
        matched_keyword_source = "filename" if fs_name else "content_peek"
        score += class_bonus
    else:
        classes = (
            ("preliminary_full_year", 60, _FILENAME_PRELIMINARY_KEYWORDS),
            ("interim_or_half_year", 35, _FILENAME_INTERIM_KEYWORDS),
            ("investor_presentation", 15, _FILENAME_INVESTOR_PRESENTATION_KEYWORDS),
        )
        for cls, bonus, keywords in classes:
            matched_name = _first_matching_keyword(name_norm, keywords)
            matched_title = _first_matching_keyword(title_norm, keywords)
            # v62.12.1 (spec §3) — "interim"/"preliminary" dans le CORPS ne
            # classe plus un document (bug Governance→interim) : nom et
            # titre/couverture uniquement.
            matched = matched_name or matched_title
            if matched:
                document_class = cls
                document_subclass = cls
                class_bonus = bonus
                matched_keyword = matched
                matched_keyword_source = ("filename" if matched_name else
                                          "content_peek")
                score += bonus
                break
        if document_class == "other":
            # Last-resort audited/annual detection from the body, weaker than
            # an explicit cover but still useful for 8.3 aliases.
            fs_hint = _first_matching_keyword(hint_norm, _FILENAME_FINANCIAL_STATEMENTS_KEYWORDS)
            ar_hint = _first_matching_keyword(hint_norm, _FILENAME_ANNUAL_REPORT_KEYWORDS)
            if ar_hint:
                document_class = "audited_or_annual"
                document_subclass = "annual_report"
                class_bonus = 80
                matched_keyword = ar_hint
                matched_keyword_source = "content_peek"
                score += class_bonus
            elif fs_hint:
                document_class = "audited_or_annual"
                document_subclass = "financial_statements_primary"
                class_bonus = 90
                matched_keyword = fs_hint
                matched_keyword_source = "content_peek"
                score += class_bonus

    # v62.12.1 (spec §3) — un TITRE explicitement Governance / Strategic /
    # Sustainability impose la classe secondaire, quoi que dise le corps.
    _sec_title = (_first_matching_keyword(title_norm, _FILENAME_DEPRIORITY_KEYWORDS)
                  or _first_matching_keyword(name_norm, _FILENAME_DEPRIORITY_KEYWORDS))
    if _sec_title and document_class != "secondary_report":
        score -= class_bonus
        class_bonus = 0
        document_class = "secondary_report"
        document_subclass = "secondary_report"
        matched_keyword = _sec_title
        matched_keyword_source = "title"

    fy_bonus = 0
    fy_bucket = ""
    matched_fy_keyword = ""
    matched_fy_source = ""
    for index, fy_keyword in enumerate(_compute_fy_priority_keywords(today)):
        norm = _normalize_priority_filename(fy_keyword)
        if norm and norm in name_norm:
            source = "filename"
        elif norm and norm in title_norm:
            # v62.12.1 (spec §3) — le millésime vient du TITRE/couverture,
            # jamais d'une mention incidente du corps (bug BU0988 : "2026"
            # dans le texte d'un rapport FY2024/25 → bucket current à tort).
            source = "content_peek"
        else:
            continue
        fy_index = index // 5
        fy_bonus = max(0, 30 - 10 * fy_index)
        fy_bucket = ("current" if fy_index == 0 else
                     "n_minus_1" if fy_index == 1 else "n_minus_2")
        matched_fy_keyword = fy_keyword
        matched_fy_source = source
        score += fy_bonus
        break

    # v62.12.1 (spec §3) — la période documentaire vient de la COUVERTURE :
    # date de clôture ("52 weeks ended 28 March 2026", "exercice clos le…")
    # ou span FY du titre ("2025/26"). JAMAIS le plus grand millésime du
    # corps ; jamais une année future ("inconnu" vaut mieux que 2027 inventé).
    # Une couverture qui contredit le mot-clé de nom/titre fait AUTORITÉ.
    content_period_year = _cover_period_year(title_blob, hint, today=today)
    if content_period_year:
        from datetime import datetime
        now = today or datetime.now()
        current_fy = now.year if now.month >= 4 else now.year - 1
        delta = current_fy - int(content_period_year)
        if delta >= 0:
            cover_bucket = ("current" if delta == 0 else
                            "n_minus_1" if delta == 1 else
                            "n_minus_2" if delta == 2 else "older")
            if fy_bucket and fy_bucket != cover_bucket:
                score -= fy_bonus
                fy_bonus = 0
                matched_fy_keyword = ""
                matched_fy_source = ""
            fy_bucket = cover_bucket
            if not fy_bonus and delta in (0, 1, 2):
                fy_bonus = max(0, 30 - 10 * delta)
                matched_fy_keyword = str(content_period_year)
                matched_fy_source = "cover_date"
                score += fy_bonus

    secondary_penalty = 0
    matched_secondary_name = _first_matching_keyword(
        name_norm, _FILENAME_DEPRIORITY_KEYWORDS)
    matched_secondary_title = _first_matching_keyword(
        title_norm, _FILENAME_DEPRIORITY_KEYWORDS)
    matched_secondary_hint = _first_matching_keyword(
        hint_norm, _FILENAME_DEPRIORITY_KEYWORDS)
    matched_secondary_keyword = (matched_secondary_name or matched_secondary_title
                                  or matched_secondary_hint)
    primary_classes = {"audited_or_annual"}
    explicit_primary = bool(fs_name or ar_name or fs_title or ar_title)
    explicit_secondary = bool(matched_secondary_name or matched_secondary_title)
    if matched_secondary_keyword and not (document_class in primary_classes and explicit_primary):
        secondary_penalty = -80 if explicit_secondary else -35
        score += secondary_penalty
        if explicit_secondary or document_class == "other":
            document_class = "secondary_report"
            document_subclass = "secondary_report"
    excerpt = re.sub(r"\s+", " ", hint).strip()[:220]
    short_name = bool("~" in name and re.search(r"~\d", name, re.I))
    return {
        "filename": name,
        "score": int(score),
        "document_class": document_class,
        "document_subclass": document_subclass or document_class,
        "class_bonus": int(class_bonus),
        "fy_bonus": int(fy_bonus),
        "fy_bucket": fy_bucket,
        "content_period_year": content_period_year,
        "secondary_penalty": int(secondary_penalty),
        "matched_keyword": matched_keyword,
        "matched_keyword_source": matched_keyword_source,
        "matched_keyword_scope": ("title_or_cover" if matched_keyword_source == "content_peek" and matched_keyword else
                                   "filename" if matched_keyword_source == "filename" else "body"),
        "matched_fy_keyword": matched_fy_keyword,
        "matched_fy_source": matched_fy_source,
        "matched_secondary_keyword": matched_secondary_keyword,
        "short_filename_detected": short_name,
        "priority_peek_status": str(peek.get("status") or
                                    ("OK" if hint else "NOT_RUN")),
        "priority_peek_pages": int(peek.get("pages_read") or 0),
        "priority_peek_chars": int(peek.get("chars") or len(hint)),
        "priority_peek_title": str(peek.get("metadata_title") or "")[:220],
        "priority_peek_excerpt": excerpt,
        "priority_peek_error": str(peek.get("error") or "")[:180],
        "policy_version": FS_PRIORITY_POLICY_VERSION,
    }


_CLASS_RANK = {
    "audited_or_annual": 7,
    "preliminary_full_year": 5,
    "interim_or_half_year": 4,
    "investor_presentation": 3,
    "other": 2,
    "secondary_report": 1,
}


_COVER_CLOSING_RE = re.compile(
    r"(?:52\s+weeks?|year|exercice)\s+(?:ended|ending|clos(?:\s+le)?)\s*"
    r"(?:le\s+)?[^\n]{0,40}?(?P<y>20\d{2})", re.IGNORECASE)
_COVER_SPAN_RE = re.compile(r"\b(20\d{2})\s*[/–—-]\s*(\d{2})\b")


def _cover_period_year(title_blob: str, full_hint: str, today=None):
    """v62.12.1 (spec §3) — année d'exercice par autorité de couverture.

    Ordre : date de clôture explicite ; sinon span FY (2025/26 → 2026) du
    titre ou des 6 premières lignes ; sinon None (inconnu). Le futur est
    interdit : une échéance 2027 rencontrée dans un corps ne date rien.
    """
    from datetime import datetime
    now = today or datetime.now()
    current_fy = now.year if now.month >= 4 else now.year - 1
    head = "\n".join(str(full_hint or "").splitlines()[:6])
    for zone in (str(title_blob or ""), head):
        if not zone:
            continue
        m = _COVER_CLOSING_RE.search(zone)
        if m:
            y = int(m.group("y"))
            if y <= current_fy:
                return y
        m2 = _COVER_SPAN_RE.search(zone)
        if m2:
            y = int(m2.group(1)) + 1
            if y <= current_fy:
                return y
    return None


def rank_pdfs_for_fs_extraction(
    uploads: List[tuple],
    today=None,
) -> List[Tuple[tuple, Dict[str, Any]]]:
    """Rank uploads once, using filename + a cheap native-text content peek."""
    scored: List[Tuple[tuple, Dict[str, Any]]] = []
    for input_index, upload in enumerate(uploads or []):
        filename = upload[0] if upload else ""
        data = upload[2] if upload and len(upload) >= 3 else b""
        peek = _peek_pdf_priority_text(data if isinstance(data, bytes) else bytes(data or b""))
        hint = "\n".join(
            x for x in (
                str(peek.get("metadata_title") or ""),
                str(peek.get("metadata_subject") or ""),
                str(peek.get("text") or ""),
            ) if x
        )
        detail = score_pdf_for_fs_extraction(
            filename, today=today, content_hint=hint, priority_peek=peek)
        detail["input_index"] = int(input_index)
        detail["peek_has_financial_review"] = bool(re.search(
            r"financial\s+review|revue\s+financi[èe]re", hint, re.IGNORECASE))
        _peek_txt = str(peek.get("text") or "")
        # v62.12.2 — une couverture commune ne suffit pas à déclarer deux
        # documents identiques. L'empreinte incorpore taille, pages lues et
        # trois fenêtres du peek (début / milieu / fin). Un PDF sans texte ne
        # peut toujours pas être dédupliqué automatiquement avant OCR.
        if _peek_txt.strip():
            _mid = max(0, len(_peek_txt) // 2 - 750)
            _fp_material = "|".join((
                str(len(data or b"")),
                str(peek.get("pages_read") or 0),
                _peek_txt[:1500],
                _peek_txt[_mid:_mid + 1500],
                _peek_txt[-1500:],
            ))
            detail["peek_fingerprint"] = hashlib.sha256(
                _fp_material.encode("utf-8", "ignore")).hexdigest()
        else:
            detail["peek_fingerprint"] = ""
        scored.append((upload, detail))
    # v62.12.1 — politique v5 (spec §1) : clé composite en rang global.
    # Les documents SECONDAIRES (governance, strategic, RSE) perdent toujours
    # face à un document "other/inconnu" même sans bucket — ils ne doivent pas
    # consommer du budget au détriment de fichiers non classifiés.
    _BUCKET_RANK = {"current": 0, "n_minus_1": 1, "n_minus_2": 2, "older": 3, "": 4}
    _CLS_PRI = {
        "financial_statements_primary": 0,
        "annual_report": 1,
        "preliminary_full_year": 2,
    }

    def _v5_group(d):
        """Clé composite v5 (spec §1) — ordres garantis :
        courant-primaire > n_minus_1-primaire > courant/n1-interim > other >
        courant-secondaire > n_minus_2-et-plus > secondaire-histo.
        "other" devance les secondaires (governance, strategic ne volent pas
        le budget d'un fichier inconnu), mais les secondaires courants passent
        devant les archives n_minus_2+ (ils portent le slot review)."""
        cls = str(d.get("document_class") or "other")
        sub = str(d.get("document_subclass") or "")
        bkt = str(d.get("fy_bucket") or "")
        br = _BUCKET_RANK.get(bkt, 4)
        if cls == "secondary_report":
            # Courant (br=0) → groupe 9 ; histo (br≥2) → groupe 11.
            return (9 if br == 0 else 11, br, 0, 0)
        if cls == "audited_or_annual":
            pri = _CLS_PRI.get(sub, 1)
            if br >= 2:
                g = 10  # n_minus_2+ → groupe 10 (après current secondary, groupe 9)
            else:
                g = br * 3 + pri  # current (0-2) ou n_minus_1 (3-5)
            return (g, 0, -(int(d.get("content_period_year") or 0)), -(int(d.get("score") or 0)))
        if cls == "preliminary_full_year":
            if br >= 2:
                g = 10
            else:
                g = br * 3 + 2
            return (g, 0, -(int(d.get("content_period_year") or 0)), -(int(d.get("score") or 0)))
        if cls == "interim_or_half_year":
            return (6 + min(br, 1), 0, -(int(d.get("content_period_year") or 0)), 0)
        if cls == "investor_presentation":
            return (7, br, 0, 0)
        return (8, br, 0, -(int(d.get("score") or 0)))  # other / inconnu

    scored.sort(
        key=lambda pair: (
            _v5_group(pair[1]),
            int(pair[1].get("input_index") or 0),
        ),
    )
    for rank, (_upload, detail) in enumerate(scored, start=1):
        detail["rank"] = rank
    return scored


def describe_pdf_priorities(uploads: List[tuple], today=None) -> List[Dict[str, Any]]:
    """Trace sorted by the exact policy used by the deep scan."""
    return [dict(detail) for _upload, detail
            in rank_pdfs_for_fs_extraction(uploads, today=today)]


def plan_deep_scan(details):
    """v62.12.2 (spec §1) — réservations de budget + déduplication.

    Mute chaque détail de ``rank_pdfs_for_fs_extraction`` :
      - ``reserved_slot`` ∈ {current_primary_statements,
        current_review_or_report, comparative_n_minus_1, ""} — un document
        réservé n'est JAMAIS écarté pour budget ;
      - ``planned_skip_duplicate`` — copies d'un même (classe, exercice,
        empreinte des premières pages) : un seul exemplaire consomme du
        budget (spec « Déduplication »).
    Retourne la même liste, dans l'ordre reçu (déjà trié v5).
    """
    seen = set()
    slots = {"current_primary_statements": None,
             "current_review_or_report": None,
             "comparative_n_minus_1": None}
    for d in details or []:
        d.setdefault("reserved_slot", "")
        d.setdefault("planned_skip_duplicate", False)
        fp = str(d.get("peek_fingerprint") or "")[:10]
        key = (str(d.get("document_class") or ""),
               str(d.get("document_subclass") or ""),
               int(d.get("content_period_year") or 0), fp)
        if fp and key in seen:
            d["planned_skip_duplicate"] = True
            continue
        seen.add(key)
        bucket = str(d.get("fy_bucket") or "")
        cls = str(d.get("document_class") or "")
        if (slots["current_primary_statements"] is None
                and bucket == "current" and cls == "audited_or_annual"):
            slots["current_primary_statements"] = d
            d["reserved_slot"] = "current_primary_statements"
        elif (slots["current_review_or_report"] is None and bucket == "current"
              and cls in ("audited_or_annual", "preliminary_full_year",
                          "secondary_report")
              and d.get("peek_has_financial_review")):
            # v62.12.1 — le slot review va au document qui PORTE le Financial
            # Review, pas au premier secondaire courant venu (Governance).
            slots["current_review_or_report"] = d
            d["reserved_slot"] = "current_review_or_report"
        elif (slots["comparative_n_minus_1"] is None and bucket == "n_minus_1"
              and cls in ("audited_or_annual", "preliminary_full_year")):
            slots["comparative_n_minus_1"] = d
            d["reserved_slot"] = "comparative_n_minus_1"
    return details


def prioritize_pdfs_for_fs_extraction(
    uploads: List[tuple],
    today=None,
) -> List[tuple]:
    """Sort PDF uploads according to the versioned financial policy."""
    return [upload for upload, _detail
            in rank_pdfs_for_fs_extraction(uploads, today=today)]


_LIASSE_NAME_RE = re.compile(
    r"(?:liasse|cerfa|205[0-9]|comptes?[-_ ]annuels?|plaquette|bilan[-_ ]fiscal)", re.I)
_LIASSE_CONTENT_RE = re.compile(
    r"(?:DIRECTION\s+G[ÉE]N[ÉE]RALE\s+DES\s+FINANCES\s+PUBLIQUES|"
    r"DGFIP\s*(?:N[°O]\s*)?205[0-9]|"
    r"(?:CERFA|FORMULAIRE|IMPRIM[ÉE])\s*(?:N[°O]\s*)?205[0-9]|"
    r"\b2050\s*[-–—:]?\s*BILAN\s+ACTIF\b|\b2051\s*[-–—:]?\s*BILAN\s+PASSIF\b|"
    r"\b2052\s*[-–—:]?\s*COMPTE\s+DE\s+R[ÉE]SULTAT\b|"
    r"R[ÉE]GIME\s+R[ÉE]EL\s+NORMAL|LIASSE\s+FISCALE)", re.I)
_LIASSE_FORM_RE = re.compile(r"\b205[0-9]\b")


def classify_liasse_or_cerfa_pdf(filename: str, pdf_bytes: bytes) -> Dict[str, Any]:
    """Classify a French liasse/CERFA even when the upload has an 8.3 alias.

    No OCR is attempted.  An image-only candidate is explicitly marked
    ``OCR_REQUIRED`` and cannot emit financial facts before v18.
    """
    name_match = bool(_LIASSE_NAME_RE.search(str(filename or "")))
    peek = _peek_pdf_priority_text(pdf_bytes or b"", max_pages=8, max_chars=24_000)
    text = str(peek.get("text") or "")
    forms = sorted(set(_LIASSE_FORM_RE.findall(text)))
    content_match = bool(_LIASSE_CONTENT_RE.search(text) or
                         (forms and re.search(r"\bEXERCICE\b|\bBILAN\b|COMPTE\s+DE\s+R[ÉE]SULTAT", text, re.I)))
    detected = bool(name_match or content_match)
    ocr_required = bool(detected and str(peek.get("status") or "") == "NO_TEXT")
    return {
        "filename": Path(str(filename or "")).name,
        "detected": detected,
        "detected_via": ("filename+content" if name_match and content_match else
                         "filename" if name_match else
                         "content_peek" if content_match else "none"),
        "forms": forms,
        "ocr_required": ocr_required,
        "peek_status": str(peek.get("status") or ""),
        "peek_pages": int(peek.get("pages_read") or 0),
        "peek_chars": int(peek.get("chars") or 0),
        "error": str(peek.get("error") or "")[:180],
    }


__all__ = [
    "SectionDetection",
    "FinancialStatementsBundle",
    "SECTION_PATTERNS",
    "PRIORITY_ORDER",
    "DEFAULT_TOKEN_BUDGET",
    "FS_GLOBAL_BUDGET",
    "FS_PER_PDF_CAP",
    "FS_MAX_DEEP_SCAN_PDFS",
    "FS_PRIORITY_POLICY_VERSION",
    "FS_PIPELINE_CACHE_SCHEMA",
    "classify_liasse_or_cerfa_pdf",
    "MAX_PAGES_TO_SCAN",
    "detect_sections_in_pdf",
    "extract_financial_sections",
    "extract_financial_statements_from_pdf",
    "build_financial_statements_block",
    # Since v16.5.70.2 — priorisation PDF
    "_compute_fy_priority_keywords",
    "prioritize_pdfs_for_fs_extraction",
    "plan_deep_scan",
    "rank_pdfs_for_fs_extraction",
    "describe_pdf_priorities",
    "score_pdf_for_fs_extraction",
]
