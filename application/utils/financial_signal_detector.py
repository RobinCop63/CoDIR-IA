"""
CoDIR-IA — utils/financial_signal_detector.py — Since v16.5.71

Module de détection de signaux financiers SOLIDES dans n'importe quelle
source textuelle (attachments_block agrégé, brief utilisateur, etc.) —
pas seulement les PDFs Annual Reports.

Bug racine identifié sur audit ChatGPT round 8 v16.5.70.3 :
- Sur dossier réseau de soins, l'utilisateur uploadait 8 PJ : 5 Excel comptables auditées
  (exemple synthétique : chiffre d’affaires consolidé et marge d’une filiale), 2 PDF non-FS, 1 Word annexe légale
- Le module financial_statement_extractor scanne UNIQUEMENT les PDFs
- Donc financial_statements_detected = False sur dossier réseau de soins
- Cascade Source Quality : "PJ uploadées mais FS non détectés" → score 35
  → règle prudence ACTIVE → Finance bridé en diagnostic qualitatif
- Régression : dossier réseau de soins v16.5.70.2 = Grade B/70 → dossier réseau de soins v16.5.70.3 = Grade D/35
  alors que les chiffres sont parfaitement extractibles

Solution v16.5.71 :
- Détection rigoureuse multi-format dans `attachments_block` (qui agrège
  texte de tous les uploads PDF + DOCX + XLSX + CSV + TXT après
  extract_text_from_upload)
- 4 indicateurs combinés : keywords financiers, montants/devises,
  sigles comptables, structures tabulaires
- Score de confiance 0-100 + verdict booléen "financial_signal_solid"
- Multilingue FR + EN

Apprentissage Robin (audit round 8) : "le plus rigoureux et précis possible
pour en rater le moins possible". Donc on combine 4 indicateurs avec seuils
et on documente chaque heuristique pour audit futur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constantes — patterns multilingues
# ─────────────────────────────────────────────────────────────────────────────

# Indicateur 1 — Keywords financiers (>50 termes typiques rapports financiers)
# Multilingue FR + EN. Couvre : compte de résultat, bilan, cash flow, ratios.
_FINANCIAL_KEYWORDS_PATTERN = re.compile(
    r"\b("
    # === Compte de résultat / Income Statement ===
    r"revenue|turnover|sales|net\s+sales|gross\s+sales|"
    r"chiffre\s+d['']affaires|ca\b|ventes|produits\s+d['']exploitation|"
    r"cost\s+of\s+sales|cogs|cost\s+of\s+goods\s+sold|"
    r"co[ûu]t\s+des?\s+ventes?|achats\s+et\s+charges\s+externes?|"
    r"gross\s+profit|gross\s+margin|"
    r"marge\s+brute|"
    r"operating\s+profit|operating\s+income|operating\s+loss|operating\s+expenses|"
    r"r[ée]sultat\s+d['']exploitation|r[ée]sultat\s+op[ée]rationnel|"
    r"charges\s+d['']exploitation|"
    r"ebit\b|ebitda\b|"
    r"profit\s+before\s+tax|pretax|"
    r"r[ée]sultat\s+avant\s+imp[ôo]ts?|r[ée]sultat\s+net|"
    r"net\s+income|net\s+earnings|net\s+profit|net\s+loss|"
    r"earnings\s+per\s+share|eps\b|b[ée]n[ée]fice\s+par\s+action|"
    # === Bilan / Balance Sheet ===
    r"total\s+assets|fixed\s+assets|current\s+assets|"
    r"actif\s+total|actif\s+immobilis[ée]|actif\s+circulant|immobilisations?|"
    r"trade\s+receivables|accounts\s+receivable|"
    r"cr[ée]ances\s+clients|"
    r"inventories|stock\s+(?:and\s+)?work|"
    r"stocks?|en[\s\-]cours|"
    r"cash\s+and\s+cash\s+equivalents|cash\s+at\s+bank|"
    r"tr[ée]sorerie|disponibilit[ée]s|"
    r"total\s+equity|shareholders[''']?\s+equity|"
    r"capitaux\s+propres|fonds\s+propres|"
    r"trade\s+payables|accounts\s+payable|"
    r"dettes\s+fournisseurs|dettes\s+commerciales|"
    r"borrowings|long[\s\-]term\s+debt|short[\s\-]term\s+debt|"
    r"emprunts?|dettes\s+financi[èe]res?|"
    # === Cash Flow / Tableau de flux ===
    r"net\s+cash\s+(?:from|used)|operating\s+cash\s+flow|"
    r"flux\s+(?:net\s+)?(?:de\s+)?tr[ée]sorerie|"
    r"capital\s+expenditure|capex|"
    r"investissements?|d[ée]penses?\s+d['']investissement|"
    r"free\s+cash\s+flow|fcf\b|"
    # === Ratios ===
    r"return\s+on\s+(?:equity|assets|capital)|roe\b|roa\b|roce\b|"
    r"rentabilit[ée]\s+(?:des?\s+(?:capitaux|fonds)|nette|brute)|"
    r"working\s+capital|wcr\b|"
    r"bfr\b|besoin\s+en\s+fonds\s+de\s+roulement|"
    # === Reporting / audit ===
    r"audited\s+financial|consolidated|preliminary\s+results|"
    r"audit[ée]e?s?|consolid[ée]e?s?|comptes\s+annuels|"
    r"liasse\s+fiscale|annexe\s+(?:l[ée]gale|fiscale)|"
    r"commissaires?\s+aux?\s+comptes?"
    r")\b",
    re.IGNORECASE | re.UNICODE
)

# Indicateur 2 — Montants financiers significatifs
# Couvre : 1,234 / 1.234 / 1234.56 / 1 234 567 / £2,968M / €220M / 14,5%
# 5 patterns distincts car les formats varient FR/EN/US.
_AMOUNT_PATTERNS = [
    # Pattern 1 : Montant avec milliers (1,234 ou 1.234 ou 1 234) suivi
    # éventuellement de décimales et d'unité M/k/Md/B/€/$/£/%
    re.compile(
        r"\b\d{1,3}(?:[,.\s]\d{3})+(?:[,.]\d{1,3})?"
        r"\s*(?:M€|MEUR|k€|KEUR|Md€|G€|M\$|k\$|MGBP|MUSD|M£|"
        r"\$|€|£|GBP|EUR|USD|CHF|"
        r"M\b|k\b|Md\b|B\b|millions?|milliards?|"
        r"billion|million|thousand)?",
        re.IGNORECASE
    ),
    # Pattern 2 : Montant simple ≥ 4 chiffres (1234, 12345, 1234567)
    re.compile(r"\b\d{4,}(?:[.,]\d{1,2})?\b"),
    # Pattern 3 : Pourcentages (12,5% / 12.5% / -9.6% / -9,6 pts)
    re.compile(r"[+\-]?\d{1,3}(?:[.,]\d{1,2})?\s*(?:%|pts?|bps|points?\s+de\s+base)\b", re.IGNORECASE),
    # Pattern 4 : Devise + montant collé (€2,968 / £220 / $1500)
    re.compile(r"[€$£¥]\s*\d{1,3}(?:[,.\s]?\d{3})*(?:[.,]\d{1,3})?(?:\s*[MkBmgKb]?)\b"),
    # Pattern 5 (Since v16.5.71) — Montant FR court avec unité financière obligatoire
    # Capte : "220 M€", "16,5 M€", "33 M€", "4,5 M€", "557 k€", "2,968 £M"
    # Le critère "unité obligatoire" évite de matcher "11 ans" ou "2026 France"
    re.compile(
        r"[+\-]?\d{1,4}(?:[,.]\d{1,3})?"        # nombre 1-4 digits + décimales optionnelles
        r"\s*"                                    # espace optionnel
        r"(?:M€|MEUR|MEur|k€|KEUR|kEur|Md€|G€|"  # unités FR explicites
        r"M\$|k\$|MUSD|"                          # USD compact
        r"M£|MGBP|"                               # GBP compact
        r"€M|£M|\$M|"                             # ordre alternatif (post-EN)
        r"EUR\s*M|GBP\s*M|USD\s*M|"              # avec espace
        r"millions?\s+(?:d'|de\s+|of\s+)?(?:€|euros?|EUR|dollars?|USD|\$|£|GBP|livres?)|"
        r"milliards?\s+(?:d'|de\s+|of\s+)?(?:€|euros?|EUR|dollars?|USD|\$|£|GBP|livres?))",
        re.IGNORECASE
    ),
]

# Indicateur 3 — Sigles / abréviations comptables typiques
_ACCOUNTING_SIGLES_PATTERN = re.compile(
    r"\b("
    r"FY\d{2,4}|"           # FY24, FY2024, FY26
    r"Q[1-4]\b|H[12]\b|"    # trimestres / semestres
    r"YoY|QoQ|YTD|MTD|"     # year-on-year, quarter-on-quarter
    r"P&L|P&L\b|EBIT|EBITDA|EBT|"
    r"DSO|DPO|DIO|"         # days sales/payable/inventory outstanding
    r"NRV|FIFO|LIFO|"       # méthodes valorisation stocks
    r"GAAP|IFRS|US\s*GAAP|"
    r"K€|M€|Md€|G€|"        # unités françaises
    r"SIREN|SIRET|APE|NAF|" # identifiants FR
    r"ROE|ROA|ROCE|ROIC|"
    r"WACC|WCR|BFR|"
    r"CAPEX|OPEX|FCF|"
    r"COGS|SG&A|R&D"
    r")\b",
    re.IGNORECASE
)

# Indicateur 4 — Structures tabulaires (lignes de tableaux extraits)
# Détecte les patterns "Label .... Number" typiques de l'extraction PDF/Excel
# Ex: "Revenue                              2,968"
#     "Cost of sales                       (1,200)"
#     "Total assets | 4 200 | 3 800 | 3 500"
_TABLE_LINE_PATTERN = re.compile(
    r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-'']{4,40}"  # label : 5-45 chars commençant par lettre
    r"[\s\t|]{2,}"                              # séparateur visible
    r"\(?[+\-]?\d{1,3}(?:[,.\s]\d{3})+(?:[.,]\d{1,3})?\)?"  # 1ᵉʳ montant
    r"(?:[\s\t|]+\(?[+\-]?\d{1,3}(?:[,.\s]\d{3})+(?:[.,]\d{1,3})?\)?){0,4}",  # 0-4 colonnes
    re.MULTILINE
)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass de résultat
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FinancialSignalReport:
    """
    Rapport de détection de signaux financiers dans une source texte.

    Attributs :
        source_chars            : taille analysée
        n_keywords              : nombre de keywords financiers matchés
        n_amounts               : nombre de montants détectés (tous patterns)
        n_sigles                : nombre de sigles comptables (EBITDA, FY24, etc.)
        n_table_lines           : nombre de lignes de tableau "label nombre"
        confidence_score        : 0-100, score composite
        financial_signal_solid  : verdict booléen (score >= seuil)
        sample_keywords         : 5 premiers keywords matchés (debug)
        sample_amounts          : 5 premiers montants matchés (debug)
        notes                   : observations / warnings
    """
    source_chars: int
    n_keywords: int
    n_amounts: int
    n_sigles: int
    n_table_lines: int
    confidence_score: int = 0
    financial_signal_solid: bool = False
    sample_keywords: List[str] = field(default_factory=list)
    sample_amounts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_diag_dict(self) -> Dict[str, Any]:
        return {
            "source_chars": self.source_chars,
            "n_keywords": self.n_keywords,
            "n_amounts": self.n_amounts,
            "n_sigles": self.n_sigles,
            "n_table_lines": self.n_table_lines,
            "confidence_score": self.confidence_score,
            "financial_signal_solid": self.financial_signal_solid,
            "sample_keywords": self.sample_keywords,
            "sample_amounts": self.sample_amounts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Fonction principale
# ─────────────────────────────────────────────────────────────────────────────

# Seuils de confiance (calibrés sur cas réels dossier réseau de soins + dossier anglophone coté)
THRESHOLD_KEYWORDS_MIN = 5      # ≥ 5 keywords financiers distincts
THRESHOLD_AMOUNTS_MIN = 10      # ≥ 10 montants détectés
THRESHOLD_SIGLES_MIN = 1        # ≥ 1 sigle comptable
THRESHOLD_CONFIDENCE_SOLID = 60  # score >= 60 → financial_signal_solid


def detect_financial_signal(
    source_text: str,
    *,
    threshold_solid: int = THRESHOLD_CONFIDENCE_SOLID,
) -> FinancialSignalReport:
    """
    Analyse une source texte pour déterminer si elle contient des signaux
    financiers SOLIDES (chiffres comptables réels, pas juste mentions vagues).

    Tolère un texte vide ou None — retourne un rapport "rien détecté".

    Le score de confiance combine 4 indicateurs avec pondérations :
      - 30 pts si keywords ≥ 5 (échelle dégressive 0-30)
      - 30 pts si amounts ≥ 10 (échelle dégressive 0-30)
      - 20 pts si sigles ≥ 1 (échelle dégressive 0-20)
      - 20 pts si table_lines ≥ 3 (échelle dégressive 0-20)
    Score max théorique : 100.

    Verdict `financial_signal_solid` = True si score >= threshold_solid (60 par défaut).
    """
    if not source_text or not isinstance(source_text, str):
        return FinancialSignalReport(
            source_chars=0, n_keywords=0, n_amounts=0,
            n_sigles=0, n_table_lines=0,
            notes=["Source vide ou non-string"],
        )

    text = source_text
    n_chars = len(text)

    # Indicateur 1 — Keywords financiers (set distinct pour ne pas surcompter)
    keyword_matches = _FINANCIAL_KEYWORDS_PATTERN.findall(text)
    distinct_keywords = list({m.lower() for m in keyword_matches})
    n_keywords = len(distinct_keywords)

    # Indicateur 2 — Montants (somme des 4 patterns, dédupliqué par valeur)
    all_amounts = []
    for pat in _AMOUNT_PATTERNS:
        all_amounts.extend(pat.findall(text))
    n_amounts = len(set(all_amounts))

    # Indicateur 3 — Sigles comptables (set distinct)
    sigle_matches = _ACCOUNTING_SIGLES_PATTERN.findall(text)
    n_sigles = len({m.upper() for m in sigle_matches})

    # Indicateur 4 — Lignes de tableau structurées
    table_matches = _TABLE_LINE_PATTERN.findall(text)
    n_table_lines = len(table_matches)

    # Score composite — chaque indicateur contribue jusqu'à son max
    score = 0.0
    if n_keywords >= THRESHOLD_KEYWORDS_MIN:
        # 30 pts pleins à 5+ keywords, +1pt par keyword au-delà jusqu'à 30 max
        score += min(30, 30 + 0)  # base 30 dès le seuil
    else:
        # 0-30 pts proportionnel : 6 pts par keyword
        score += n_keywords * 6

    if n_amounts >= THRESHOLD_AMOUNTS_MIN:
        score += 30
    else:
        score += n_amounts * 3

    if n_sigles >= THRESHOLD_SIGLES_MIN:
        score += min(20, 10 + n_sigles * 5)
    # else 0 pts

    if n_table_lines >= 3:
        score += 20
    elif n_table_lines >= 1:
        score += n_table_lines * 5

    score = int(min(100, score))

    report = FinancialSignalReport(
        source_chars=n_chars,
        n_keywords=n_keywords,
        n_amounts=n_amounts,
        n_sigles=n_sigles,
        n_table_lines=n_table_lines,
        confidence_score=score,
        financial_signal_solid=(score >= threshold_solid),
        sample_keywords=distinct_keywords[:5],
        sample_amounts=list(set(all_amounts))[:5],
    )

    # Notes diagnostic
    if score >= threshold_solid:
        report.notes.append(
            f"✓ Signal financier SOLIDE (score {score}/100, "
            f"{n_keywords} keywords + {n_amounts} montants + "
            f"{n_sigles} sigles + {n_table_lines} lignes table)"
        )
    elif score >= 30:
        report.notes.append(
            f"⚠ Signal financier FAIBLE (score {score}/100 < {threshold_solid}) "
            f"— quelques indicateurs présents mais insuffisant"
        )
    else:
        report.notes.append(
            f"✗ Aucun signal financier détectable (score {score}/100)"
        )

    return report


__all__ = [
    "FinancialSignalReport",
    "detect_financial_signal",
    "THRESHOLD_KEYWORDS_MIN",
    "THRESHOLD_AMOUNTS_MIN",
    "THRESHOLD_SIGLES_MIN",
    "THRESHOLD_CONFIDENCE_SOLID",
]
