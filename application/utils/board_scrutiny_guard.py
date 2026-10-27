"""Board-scrutiny truth contract (v62.13.9.4.4).

In BOARD_SCRUTINY mode, unsupported numeric targets must not become executive
anchors in the Word report or the Working Deck.  Verified facts remain allowed;
model estimates are rewritten into qualitative actions that explicitly require a
baseline and provenance.  The proof-layer parser itself is deliberately outside
this micro-cycle (v62.11).
"""
from __future__ import annotations

from utils import editorial_quantity as _EQ
from utils import quantity_ledger as _QL
import re
from copy import deepcopy
from typing import Any, Mapping, Optional, Sequence

_UNSUPPORTED = re.compile(
    r"(?:\[\s*(?:AI\s*)?ESTIM|\[UNSOURCED\]|\[NON\s+SOURC[ÉE]\]|"
    r"estimate(?:d)?(?:,?\s*to\s*verify)?|estim\.?\s*[àa]\s*v[ée]rifier|"
    r"working\s+assumption|hypoth[èe]se|≈|(?<![A-Za-z0-9])~\s*\d)",
    re.I,
)
_NUMERIC = re.compile(
    r"(?:[£€$]\s*\(?\s*[-+]?\d[\d\s,.'’]*(?:[-–—]\s*\d[\d\s,.'’]*)?\s*(?:m|bn|million|billion)?|"
    r"[-+]?\d(?:[\d\s,.'’]*\d)?\s*(?:Md|Mrd|bn|G|M|k)?\s*[£€$]|"
    r"[-+]?\d(?:[\d\s,.'’]*\d)?(?:[-–—]\s*[-+]?\d(?:[\d\s,.'’]*\d)?)?\s*"
    r"(?:%|pp\b|percentage\s+points?|points?\s+de\s+pourcentage|bps|x\b|m\b|bn\b|million|billion)|"
    r"\b\d+(?:[.,]\d+)?\s*/\s*10\b(?!\s*/\s*\d{2,4})|"
    r"\b\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+(?:[.,]\d+)?)?\s+(?:clients?|customers?|collaborateurs?|salari[ée]s?|employees?|filiales?|subsidiaries?|partenariats?|partenaires?|partners?|pilotes?)\b|"
    r"\d[\d\s,.'’]*(?:[-–—]\s*\d[\d\s,.'’]*)?(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ]+){0,4}\s+"
    r"(?:days?|jours?|months?|mois|stores?|magasins?|skus?|bags?|sacs?|closures?|fermetures?|markets?|march[ée]s?|leads?|flagships?|icons?|sites?|points?\s+of\s+sale|"
    r"clients?|customers?|distributeurs?|distributors?|collaborateurs?|salari[ée]s?|employees?|filiales?|subsidiaries?|partenariats?|partenaires?|partners?|pilotes?)|"
    r"[-+]?\d+(?:[.,]\d+)?\s*(?:pts?|points?)\s*(?:de\s+)?(?:PDM|part\s+de\s+march[ée]|market\s+share)\b)",
    re.I,
)

# Prospective language catches targets even if a structuring model has dropped
# the original [ESTIM] marker. Historical statements such as "Revenue down 20%
# FY25" do not match this expression and remain visible.
_TARGET_LANGUAGE = re.compile(
    r"\b(?:target(?:s|ed|ing)?|achiev(?:e|es|ed|ing)?|aim(?:s|ed|ing)?|goal|objective|by\s+(?:FY\s*\d{2}|Q[1-4](?:\s*FY?\d{2})?|20\d{2})|"
    r"release|save|reduce|cut|lift|raise|increase|grow|improve|restore|recover|rebuild|regain|return\s+to|stabilis(?:e|es|ed|ing|er|é|ée|és|ées)|"
    r"below|above|minimum|maximum|at\s+least|more\s+than|less\s+than|close|downsize|"
    r"suspend|reallocate|budget|spend|facility|headroom|availability|OTIF|investissement|investment|financement|funding|co[ûu]t|cost|homologation|d[ée]lai|delay|duration|"
    r"pipeline|pilot|test|launch|lancer|lancement|former|formation|train|training|deploy|d[ée]ployer|d[ée]ploiement|implement|mettre\s+en\s+place|identify|protect|ring[- ]?fence|segment|flagships?|focus|constrain|assortment|depth|ouvrir|ouverture|signer|signature|recruter|recrutement|rationalis(?:e|es|ed|ing|ation)|"
    r"kpi|seuil|threshold|pdm|part\s+de\s+march[ée]|market\s+share|objectif|cible|atteindre|viser|d['’]ici|avant\s+(?:FY|T[1-4]|20\d{2})|"
    r"lib[ée]rer|[ée]conomiser|r[ée]duire|augmenter|am[ée]liorer|stabiliser|"
    r"inf[ée]rieur|sup[ée]rieur|fermer|r[ée]allouer|enveloppe)\b",
    re.I,
)
_FACT_ONLY = re.compile(r"(?:\[(?:FACT|FAIT)\]|\b(?:FACT|FAIT)\b|DERIVED\s+FROM\s+FACTS|D[ÉE]RIV[ÉE]\s+DES\s+FAITS)", re.I)
_SOURCE_REFERENCE_ONLY = re.compile(
    r"(?:\bsource\b|\b(?:annual|audited|financial)\s+report\b|\bfinancial\s+statements?\b|"
    r"\brapport\s+annuel\b|\bcomptes?\s+(?:annuels?|sociaux|consolid[ée]s?)\b|"
    r"\b(?:p(?:age)?\.?\s*)\d+\b)",
    re.I,
)
_EXPLICIT_PROSPECTIVE = re.compile(
    r"\b(?:target|targets|targeted|aim|goal|objective|forecast|projection|scenario|"
    r"pilot|lancer|lancement|d[ée]ployer|d[ée]ploiement|ouvrir|ouverture|signer|signature|recruter|recrutement|budget|capex|investissement|investment|financement|funding|homologation|d[ée]lai|delay|duration|to\s+achieve|cible|objectif|kpi|seuil|threshold|pr[ée]vision|sc[ée]nario|"
    r"hypoth[èe]se|d['’]ici)\b|\bby\s+(?:FY\s*\d{2}|20\d{2})\b",
    re.I,
)
_HISTORICAL_LANGUAGE = re.compile(
    r"\b(?:FY\s*\d{2}(?:/\d{2})?|20\d{2}|year\s+ended|as\s+at|reported|"
    r"declined|fell|decreased|increased|rose|recovered|improved|reduced|changed|grew|was|were|from\s+[^\n]{0,30}\s+to|"
    r"clos\s+le|exercice\s+clos|a\s+baiss[ée]|a\s+augment[ée])\b",
    re.I,
)

_TARGET_TABLE_HEADER = re.compile(
    r"(?:\bmetric\b|\bindicator\b|\bindicateur\b).*(?:\btarget\b|\bcible\b)|"
    r"(?:FY\s*\d{2}|20\d{2}).*(?:\btarget\b|\bcible\b)",
    re.I,
)
_TABLE_ROW = re.compile(r"^[^|\n]*\|[^|\n]*\|", re.I)
_TRANSPOSED_SCENARIO_HEADER = re.compile(
    r"(?:\b(?:FY\s*(?:20)?\d{2}|20\d{2})\b[^|]{0,60}"
    r"\b(?:base|bear|bull|severe|target|scenario|forecast|projection|cible|objectif|central|prudent|stress|pessimiste|optimiste)\b|"
    r"\b(?:base|bear|bull|severe|target|scenario|forecast|projection|cible|objectif|central|prudent|stress|pessimiste|optimiste)\b"
    r"[^|]{0,60}\b(?:FY\s*(?:20)?\d{2}|20\d{2})\b)",
    re.I,
)
_FACT_TABLE_HEADER = re.compile(
    r"\bstatus\b.*\bfact\b.*\bvalue\b.*\bsource\b|"
    r"\bstatut\b.*\bfait\b.*\bvaleur\b.*\bsource\b",
    re.I,
)
_TABLE_NUMERIC_CELL = re.compile(
    r"^\s*\(?[-+]?\d[\d\s,.'’]*(?:\)|%|x|pp|bps)?\s*$", re.I)


_NON_QUANTITY_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]{1,6}\d+[A-Za-z]+|[A-Za-z]{1,4}\d+(?:\.\d+)+|"
    r"§\s*\d+(?:\.\d+)*|FY\s*20\d{2}|[TQ][1-4](?:\s*20\d{2})?|H[12](?:\s*20\d{2})?)(?![A-Za-z0-9])",
    re.I,
)

def _mask_non_quantity_codes(text: str) -> str:
    return _NON_QUANTITY_CODE_RE.sub(" CODE ", str(text or ""))


def _is_transposed_scenario_table(rows: Sequence[Sequence[str]], context: str = "") -> bool:
    """Detect forecast tables whose scenarios are carried by columns."""
    if not rows:
        return False
    header_cells = [re.sub(r"\s+", " ", str(x or "")).strip() for x in rows[0]]
    header = " | ".join(header_cells)
    if _FACT_TABLE_HEADER.search(header):
        return False
    hits = sum(1 for cell in header_cells if _TRANSPOSED_SCENARIO_HEADER.search(cell))
    context_scenario = bool(re.search(
        r"\b(?:financial\s+projections?|scenario|forecast|projection|"
        r"base\s+case|bear\s+case|bull\s+case|success\s+metrics|"
        r"projections?\s+financi[èe]res?|sc[ée]nario)\b", context, re.I))
    numeric_rows = sum(1 for row in rows[1:] if any(
        _NUMERIC.search(str(c or "")) or _TABLE_NUMERIC_CELL.match(str(c or ""))
        for c in row))
    return hits >= 2 and numeric_rows >= 1 and (context_scenario or len(header_cells) >= 4)


_PREFIX = re.compile(r"^(?P<prefix>\s*(?:[-*•]|\d+[.)]|\[n\d+\])?\s*)")


_SCENARIO_BLOCK_START = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:(?:\d+(?:\.\d+){0,3}|[IVXLCDM]+)[.)]?\s+)?(?:"
    r"REVISED\s+(?:PROJECTION|FORECAST)(?:\s*[—–-]\s*[^\n]*)?|"
    r"(?:24[- ]MONTH\s+)?FINANCIAL\s+PROJECTIONS?(?:\s*(?:&|AND)\s+RISK\s+ASSESSMENT)?(?:\s*[—–-]\s*[^\n]*)?|"
    r"(?:CORRECTED\s+)?(?:THREE|TWO|FOUR)?\s*SCENARIOS?(?:\s+NARRATIVES?)?|"
    r"SUCCESS\s+METRICS?(?:\s*\([^\n)]*\))?|TARGET\s+OUTCOMES?(?:\s*\([^\n)]*\))?|"
    r"CORRECTED\s+BASELINE\s+ASSUMPTION|EXPLICIT\s+ASSUMPTIONS?(?:\s*\([^\n)]*\))?|"
    r"(?:BASELINE|SEVERE\s+BEAR\s+CASE|BEAR\s+CASE|BULL\s+CASE|DOWNSIDE\s+CASE|UPSIDE\s+CASE)"
    r"(?:\s*\([^\n)]*(?:PROBABILITY|PROBABILIT[ÉE])?[^\n)]*\))?|"
    r"PROJECTIONS?\s+FINANCI[ÈE]RES?(?:\s*[—–-]\s*[^\n]*)?|"
    r"M[ÉE]TRIQUES?\s+DE\s+SUCC[ÈE]S|OBJECTIFS?\s+CHIFFR[ÉE]S?|"
    r"(?:REVENUE|MARGIN|GROSS\s+MARGIN|OPERATING\s+EXPENSE|OPEX|CAPEX|CASH\s+FLOW|WORKING\s+CAPITAL)"
    r"\s+(?:BRIDGE|PROJECTION|WATERFALL|FORECAST)|"
    r"ASSUMPTION\s+\d+|HYPOTHESIS\s+\d+|SCENARIO\s+[A-Z0-9]|"
    r"PROJECTION\s+R[ÉE]VIS[ÉE]E|PONT\s+DE\s+MARGE|PR[ÉE]VISIONNEL\s+CHIFFR[ÉE]"
    r")\s*:?[—–-]?\s*$",
    re.I,
)
_MAJOR_SECTION = re.compile(
    r"^\s*(?:#{1,6}\s*)?\d+(?:\.\d+){0,3}[.)]?\s+[A-ZÀ-Ö]", re.I)

# v62.12.4 — confinement de classe : aucune limite de longueur ne doit
# réinjecter la fin d'un scénario dans la surface exécutive. 250 lignes est
# seulement la taille maximale d'un FRAGMENT D'ANNEXE, jamais une frontière de
# quarantaine. Les blocs plus longs sont découpés en SCN-x-A/B/... tout en
# restant intégralement retirés du corps principal.
_MD_HEADING = re.compile(r"^\s*#{1,6}\s+\S")
_SCENARIO_ARCHIVE_CHUNK_LINES = 250
# Alias historique conservé pour les plugins/tests externes ; sa sémantique est
# désormais "taille de fragment d'annexe", pas "fin du bloc scénario".
_SCENARIO_BLOCK_MAX_LINES = _SCENARIO_ARCHIVE_CHUNK_LINES
_SCENARIO_CONTINUATION = re.compile(
    r"→|➔|->|\btargets?\b|\bcibles?\b|\bbase\s+case\b|\bstress\s+case\b|"
    r"\btarget\s+case\b|\bassumptions?\b|\bhypoth[èe]ses?\b|"
    r"\bsc[ée]narios?\b|\bbridge\b|\bwaterfall\b|\bprojections?\b|"
    r"\bforecasts?\b|\bpr[ée]visionnel\b|\bsavings?\b",
    re.I,
)

# Marqueurs de vérité : ils ferment toujours la quarantaine, même collés au
# scénario sans ligne vide ni syntaxe Markdown.
_FACT_BOUNDARY = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\[(?:FACT|FAIT)\]|"
    r"(?:DERIVED\s+FROM\s+FACTS|D[ÉE]RIV[ÉE]\s+DES\s+FAITS)\b)",
    re.I,
)

# Sous-titres qui appartiennent au scénario et ne doivent PAS fermer le bloc.
_SCENARIO_INTERNAL_HEADING = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:"
    r"(?:revised\s+)?(?:projection|forecast|scenario|assumption|hypothesis)|"
    r"(?:revenue|gross\s+margin|margin|operating\s+expense|opex|capex|"
    r"cash[- ]?flow|working\s+capital|debt|liquidity)\s+"
    r"(?:bridge|breakdown|projection|waterfall|forecast|sensitivity)|"
    r"base\s+case|stress\s+case|target\s+case|downside\s+case|upside\s+case|"
    r"driver\s+detail|margin\s+component|cash[- ]?flow\s+component|"
    r"total\s+(?:gross\s+margin|opex|capex|revenue|cash[- ]?flow|ebitda)|"
    r"sensitivity\s+analysis|assumption\s+detail|scenario\s+summary"
    r")\s*:?[—–-]?\s*$",
    re.I,
)

# Titres métier ordinaires fréquemment produits sans Markdown. Ils constituent
# des frontières sûres car ils ouvrent une nouvelle surface factuelle / rôle.
_BUSINESS_SECTION_HEADING = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:"
    r"factual\s+baseline|verified\s+facts?|financial\s+facts?|current\s+situation|"
    r"current\s+financial\s+position|key\s+findings?|major\s+risks?|watch\s+points?|"
    r"priority\s+actions?|action\s+plan|actions?\s+(?:retained|agreed)\s+by\s+the\s+committee|"
    r"decisions?\s+(?:retained|agreed|to\s+make)|open\s+decisions?|governance|"
    r"executive\s+summary|board\s+brief|strategic\s+plan|current\s+state|"
    r"supply\s+chain(?:\s*&\s*operational\s+performance)?|"
    r"sales\s*&\s*commercial|commercial|marketing\s*&\s*communications?|marketing|"
    r"finance(?:\s*&\s*(?:tax|fiscality))?|chief\s+financial\s+officer|"
    r"chief\s+strategy\s+officer|chief\s+executive\s+officer|"
    r"(?:cfo|ceo|cmo|coo)(?:\s+critical\s+verdict)?|"
    r"direction\s+g[ée]n[ée]rale|strat[ée]gie|faits\s+v[ée]rifi[ée]s|faits\s+financiers|"
    r"situation\s+actuelle|constats\s+cl[ée]s|risques\s+majeurs|actions\s+prioritaires|"
    r"d[ée]cisions\s+retenues|arbitrages\s+ouverts|plan\s+d['’]action"
    r")\s*:?[—–-]?\s*$",
    re.I,
)


def _is_all_caps_business_heading(line: str) -> bool:
    """Détecte un titre métier court en capitales sans sur-classer les
    sous-titres de scénario (MARGIN BRIDGE, BASE CASE, etc.)."""
    stripped = re.sub(r"\s+", " ", str(line or "")).strip().strip(":—–-")
    if not stripped or len(stripped) > 120 or "|" in stripped:
        return False
    if _SCENARIO_INTERNAL_HEADING.match(stripped):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not (len(letters) >= 4 and stripped.upper() == stripped and not re.search(r"\d", stripped)):
        return False
    # Un titre ALL CAPS n'est frontière que s'il porte un vocabulaire métier ;
    # TOTAL GROSS MARGIN / CAGR restent des éléments de scénario.
    return bool(re.search(
        r"\b(?:FACT|BASELINE|SITUATION|ACTION|DECISION|GOVERNANCE|SUMMARY|"
        r"SUPPLY\s+CHAIN|COMMERCIAL|MARKETING|FINANCE|CFO|CEO|CMO|COO|"
        r"STRATEGY|STRAT[ÉE]GIE|RISKS?|RISQUES?|FINDINGS?|CONSTATS?)\b",
        stripped, re.I))


def _is_scenario_boundary(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    if _SCENARIO_BLOCK_START.search(stripped) or _SCENARIO_INTERNAL_HEADING.match(stripped):
        return False
    if _FACT_BOUNDARY.match(stripped):
        return True
    if _MD_HEADING.match(stripped):
        return True
    if _MAJOR_SECTION.search(stripped):
        return True
    if re.match(r"^\s*(?:PILLAR|PART|SECTION|CHAPTER|AXE)\s+[A-Z0-9IVX]+\b", stripped, re.I):
        return True
    if _BUSINESS_SECTION_HEADING.match(stripped):
        return True
    return _is_all_caps_business_heading(stripped)


def _scenario_continuation(line: str) -> bool:
    """Une ligne prolonge-t-elle un bloc scénario après une ligne vide ?"""
    stripped = line.strip()
    if not stripped:
        return False
    if _is_scenario_boundary(stripped):
        return False
    if _SCENARIO_BLOCK_START.search(stripped) or _SCENARIO_INTERNAL_HEADING.match(stripped):
        return True
    if _TABLE_ROW.match(line) or _TARGET_TABLE_HEADER.search(stripped):
        return True
    return bool(_SCENARIO_CONTINUATION.search(stripped))


def _chunk_scenario_lines(lines: list[str], max_lines: int = _SCENARIO_ARCHIVE_CHUNK_LINES) -> list[list[str]]:
    """Découpe uniquement l'ARCHIVE. La quarantaine, elle, reste continue."""
    size = max(1, int(max_lines or 1))
    return [lines[i:i + size] for i in range(0, len(lines), size)] or [[]]


def _sanitize_explicit_scenario_blocks(lines: list[str], lang: str):
    """Retire intégralement les projections jusqu'à une vraie frontière.

    Contrairement aux versions précédentes, aucune limite 40/100/250 lignes ne
    remet la queue du scénario dans le corps. Les blocs longs sont seulement
    fragmentés pour l'annexe Word.
    """
    out: list[str] = []
    scenarios: list[dict[str, str]] = []
    samples: list[dict[str, str]] = []
    rewritten = 0
    i = 0
    block_seq = 0
    while i < len(lines):
        line = lines[i]
        if not _SCENARIO_BLOCK_START.search(line):
            out.append(line)
            i += 1
            continue
        block_seq += 1
        block = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if _is_scenario_boundary(nxt):
                break
            if not nxt.strip():
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines) or _is_scenario_boundary(lines[j]) or not _scenario_continuation(lines[j]):
                    break
            if nxt.strip() == "---":
                # Le séparateur appartient au document, pas au scénario.
                break
            block.append(nxt)
            i += 1
        original = "\n".join(block).strip()
        replacement = _qualitative_or_msg(block, original, lang)
        out.append(replacement)
        rewritten += 1
        chunks = _chunk_scenario_lines(block)
        for chunk_index, chunk in enumerate(chunks, start=1):
            chunk_original = "\n".join(chunk).strip()
            scenarios.append({
                "original": chunk_original,
                "replacement": replacement,
                "status": "UNVALIDATED_SCENARIO",
                "source_type": "narrative_scenario_block",
                "scenario_block_id": f"SB-{block_seq:03d}",
                "chunk_index": chunk_index,
                "chunk_count": len(chunks),
            })
        if len(samples) < 8:
            samples.append({"before": original[:220], "after": replacement})
    return out, rewritten, samples, scenarios



def _qualitative_or_msg(block, original: str, lang: str) -> str:
    """v62.13.9.4.39 — DOCTRINE DES SCÉNARIOS : le scénario chiffré écarté part ENTIER au
    registre, mais la DÉCISION qui le portait reste dans le corps, réécrite sans son
    chiffre ; le message thématique ne vient qu'à défaut de noyau qualitatif. Run réel
    anglais du 20/09/2026 : cinq décisions prioritaires remplacées par « Unsupported
    quantified target (…) » — zéro décision livrée."""
    replacement = _msg(_classify(original), lang)
    # (9.4.56 — sous _FLAG_IN_PLACE49, la sortie de ce composant n'est jamais livrée : l'appelant conserve les lignes
    # d'origine et les signale en place ; le composant garde son comportement pour ses contrats unitaires)
    try:
        lines = block if isinstance(block, (list, tuple)) else str(block or "").split("\n")
        head = next((l for l in lines if str(l).strip()), "").strip()
        head = head.split("|", 1)[0].strip()
        head = re.sub(r"^\s*(?:[-*•→]\s*)?\[?n?\d{1,2}\]?[.)]?\s*", "", head)
        head = re.sub(r"\s*\[[^\]]{2,40}\]", "", head).strip()
        # un TITRE de bloc (« FINANCIAL PROJECTIONS — CORRECTED THREE SCENARIOS », en-tête
        # markdown, ligne en capitales) n'est pas une décision : le message reste
        _letters = [c for c in head if c.isalpha()]
        if head.startswith("#") or (_letters and sum(1 for c in _letters if c.isupper()) / len(_letters) >= 0.6):
            return replacement
        # PORTÉE BORNÉE (doctrines v62.11 / v62.13.1 / v62.13.3 conservées) : un ENGAGEMENT,
        # une APPROBATION, une RATIFICATION ou une CIBLE dont le chiffre est l'objet même de
        # la phrase gardent le message générique ; seule une décision dont le chiffrage est
        # SUBORDONNÉ (parenthèse, cellule après une barre, proposition annexe) conserve son
        # noyau qualitatif.
        if re.search(r"(?i)\b(?:approv|approuv|approb|ratif|aval\b|autoris|authori[sz]|commit|engag[ée]?|s'engag|valid(?:er|ate|ation)\b|"
                     r"sign[- ]?off|green[- ]?light|d[ée]bloqu|allou|allocat|vote)", head):
            return replacement
        _figure_in_main_clause = bool(re.search(r"\d", re.split(r"\s*[(|]", head, 1)[0])) and "(" not in head and "|" not in str(lines[0] if lines else "")
        if _figure_in_main_clause and re.search(r"(?i)\b(?:target|cible|objectif|goal|reach|atteindre|attain|deliver|d[ée]livrer|"
                                                   r"achieve|r[ée]aliser|generate|g[ée]n[ée]rer|save|[ée]conomiser|grow|cro[iî]tre|increase|augmenter|"
                                                   r"reduce|r[ée]duire|cut|baisser|improve|am[ée]liorer|lift|raise|hit)\b", head):
            return replacement
        q = _replacement_for(head, lang)
        # un millésime ou une date dans la phrase réécrite ne sont pas des cardinaux
        # résiduels (« d'ici fin 2027 ») : on s'en remet au juge de _replacement_for
        if q and q not in (_EQ.NEUTRAL_STATUS_EN, _EQ.NEUTRAL_STATUS_FR) and len(q.split()) >= 4 \
           and not _EQ.residual_cardinals(q) and not _EQ.unsupported_quantity(q):
            replacement = q
    except Exception:
        pass
    return replacement

def _msg(kind: str, lang: str) -> str:
    en = str(lang or "fr").lower().startswith("en")
    messages = {
        "dividend": (
            "Unsupported quantified target (dividend) — baseline and provenance required — TO ARBITRATE",
            "Cible chiffrée non étayée (dividende) — baseline et provenance requises — À ARBITRER",
        ),
        "inventory": (
            "Unsupported quantified target (inventory) — baseline and provenance required — TO VALIDATE",
            "Cible chiffrée non étayée (stocks) — baseline et provenance requises — À VALIDER",
        ),
        "marketing": (
            "Unsupported quantified target (marketing) — baseline and provenance required",
            "Cible chiffrée non étayée (marketing) — baseline et provenance requises",
        ),
        "margin": (
            "Unsupported quantified target (revenue/margin) — baseline and provenance required",
            "Cible chiffrée non étayée (CA/marge) — baseline et provenance requises",
        ),
        "stores": (
            "Unsupported quantified target (network) — baseline and provenance required",
            "Cible chiffrée non étayée (réseau) — baseline et provenance requises",
        ),
        "liquidity": (
            "Unsupported quantified target (debt/liquidity) — baseline and provenance required",
            "Cible chiffrée non étayée (dette/liquidité) — baseline et provenance requises",
        ),
        "service": (
            "Unsupported quantified target (service) — baseline and provenance required",
            "Cible chiffrée non étayée (service) — baseline et provenance requises",
        ),
        "growth": (
            "Unsupported quantified target (growth) — baseline and provenance required",
            "Cible chiffrée non étayée (croissance) — baseline et provenance requises",
        ),
        "generic": (
            "Quantified target withheld — establish baseline and provenance",
            "Cible chiffrée écartée — établir baseline et provenance",
        ),
    }
    return messages[kind][0 if en else 1]


def _amount_supported_by_claims(line: str, claims: Any) -> bool:
    """v62.13.9.4.5 — délègue à la liaison stricte par composants : un match
    numérique isolé ne valide jamais une phrase (métrique/unité/devise exigées),
    et un claim factuel ne prouve jamais une cible prospective."""
    from utils.claim_binding import supports
    return supports(line, claims)


def _replacement_for(original: str, lang: str) -> str:
    """v62.13.9.4.4 — remplacement d'une ligne non étayée : réécriture générique partagée
    (quantités neutralisées, sujet conservé) ; à défaut, statut neutre. Jamais une
    recommandation métier : la table _msg n'est plus émise, elle ne sert qu'à reconnaître
    les fallbacks d'anciens artefacts."""
    text = str(original or "").strip()
    en = str(lang or "fr").lower().startswith("en")
    if not text:
        return _EQ.NEUTRAL_STATUS_EN if en else _EQ.NEUTRAL_STATUS_FR
    # v62.13.9.4.39 — LA DÉCISION DE L'AGENT EST RÉÉCRITE, PAS EFFACÉE. Run réel anglais
    # du 20/09/2026 : les cinq décisions prioritaires (« REFOCUS product mix on heritage
    # outerwear and scarves (reduce seasonal SKU breadth by 15–20%) … ») ont TOUTES été
    # remplacées par « Unsupported quantified target — baseline and provenance
    # required » parce qu'elles portaient un verbe de décision : le produit livrait zéro
    # décision. La règle 9.4.4 (« jamais une recommandation métier ») visait les phrases
    # de repli que le PRODUIT fabriquait ; la phrase d'un agent, réécrite sans son
    # chiffre, n'est pas une recommandation du produit. On réécrit d'abord ; le statut
    # neutre ne vient qu'à défaut.
    rewritten = _EQ.rewrite_quantities(text, "en" if en else "fr")
    # v62.13.9.4.39 — une phrase réécrite n'est admise que si AUCUN chiffre libre ne
    # subsiste (les millésimes, exercices, trimestres et repères de phase ne comptent
    # pas) : « +25% comparable sales » survivait à la réécriture (contrats v62.11 /
    # v62.13.3), le statut neutre l'écartait avant, le noyau qualitatif le fait maintenant.
    _free = re.sub(r"(?:FY|AF|Q|T|S|H)\s?\d{2,4}(?:/\d{2,4})?|\b(?:19|20)\d{2}(?:[-/.]\d{2}(?:[-/.]\d{2,4})?)?\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|(?<![A-Za-z0-9])(?:T|J|M)\s*[+\-]?\s*\d{1,3}(?![A-Za-z0-9%])",
                   " ", rewritten or "")
    if rewritten and rewritten != text and not re.search(r"\d", _free) and not _EQ.residual_cardinals(rewritten) and not _EQ.unsupported_quantity(rewritten):
        return rewritten
    # à défaut : conserver le noyau qualitatif (avant la première parenthèse ou barre)
    # s'il ne porte plus aucun chiffre — la décision survit, son chiffrage part au registre
    _core = re.split(r"\s*[(|]", text, 1)[0].strip(" ;:—–-")
    if _core and len(_core.split()) >= 4 and not re.search(r"\d", _core) and not _EQ.unsupported_quantity(_core):
        return _core
    return _EQ.NEUTRAL_STATUS_EN if en else _EQ.NEUTRAL_STATUS_FR


# v62.13.9.4.4 — anciennes phrases de remplacement (≤ 9.4.3) : RECONNUES dans les artefacts
# hérités pour être agrégées/nettoyées, jamais émises.
_LEGACY_FALLBACK_STRINGS = (
    "Review dividend policy after a verified cash and covenant forecast — TO ARBITRATE",
    "Revoir le dividende après prévisionnel cash et covenants vérifiés — À ARBITRER",
    "Reduce inventory only after an SKU baseline and cash bridge — TO VALIDATE",
    "Réduire les stocks après baseline SKU et bridge de trésorerie — À VALIDER",
    "Set marketing budget after channel baseline and funding review",
    "Fixer le budget marketing après baseline canal et revue du financement",
    "Set revenue and margin targets after a verified baseline",
    "Fixer les objectifs CA et marge après baseline vérifiée",
    "Review stores after site economics, leases and brand-impact analysis",
    "Revoir les magasins après économie par site, baux et impact marque",
    "Assess debt and liquidity from a verified cash forecast",
    "Évaluer dette et liquidité depuis un prévisionnel cash vérifié",
    "Set service targets after establishing the current OTIF baseline",
    "Fixer les objectifs de service après établissement de la baseline OTIF",
    "Set growth targets after a baseline and conversion analysis",
    "Fixer les objectifs de croissance après baseline et analyse de conversion",
)


def _classify(line: str) -> str:
    low = line.lower()
    if any(k in low for k in ("dividend", "dividende")):
        return "dividend"
    if any(k in low for k in ("inventory", "stock", "sku", "sell-through", "markdown")):
        return "inventory"
    if any(k in low for k in ("marketing", "campaign", "roi", "media spend", "budget")):
        return "marketing"
    if any(k in low for k in ("margin", "revenue target", "sales target", "operating profit", "ebit")):
        return "margin"
    if any(k in low for k in ("store closure", "stores", "store network", "magasins")):
        return "stores"
    if any(k in low for k in ("credit facility", "net debt", "liquidity", "covenant", "cash buffer", "trésorerie")):
        return "liquidity"
    if any(k in low for k in ("otif", "availability", "service rate", "taux de service")):
        return "service"
    if any(k in low for k in ("growth", "comp sales", "comparable sales", "panier", "pipeline")):
        return "growth"
    return "generic"


# ── v62.13.1 — canonical claims and strong working-scenario labels ──────────
_WORKING_SCENARIO_TAG_RE = re.compile(
    r"\[(?:WORKING\s+SCENARIO\s*[—–-]\s*UNVALIDATED|"
    r"SC[ÉE]NARIO\s+DE\s+TRAVAIL\s*[—–-]\s*NON\s+VALID[ÉE])\]",
    re.I,
)
# v62.13.2 — Executive commitment morphology is explicit and bounded.
# It covers conjugated/nominal approval and commitment forms without matching
# unrelated words such as "committee" or marketing "customer engagement".
_EXECUTIVE_COMMITMENT_RE = re.compile(
    r"(?:"
    r"\bapprov(?:e|es|ed|ing|al|als)\b|"
    r"\bauthori[sz](?:e|es|ed|ing|ation|ations)?\b|"
    r"\bcommit(?:s|ted|ting|ment|ments)?\b|"
    r"\bsign[- ]?off\b|"
    r"\bexpected\s+decisions?\b|\bdecision\s*#?\d*\b|"
    r"\bboard\s+approval\b|\bbudget\s+approved\b|\bkpi\s*:|"
    r"\bapprouv(?:er|e|é|ée|és|ées|ant|ons|ez|ent|ation|ations)?\b|"
    r"\bapprobations?\b|\bratifications?\b|"
    r"\baval\s+(?:du\s+conseil|du\s+board|de\s+la\s+direction|budg[ée]taire|financier)\b|"
    r"\bautoris(?:er|e|é|ée|és|ées|ant|ons|ez|ent|ation|ations)?\b|"
    r"\bengag(?:er|e|é|ée|és|ées|ant|ons|ez|ent)\b|"
    r"\bengagements?\s+(?:financiers?|budg[ée]taires?|de\s+(?:[£€$]|\d))|"
    r"\bd[ée]cisions?\s+attendues?\b|"
    r"\bvalid(?:ation|é|ée|és|ées)\s+(?:par\s+le\s+)?conseil\b"
    r")",
    re.I,
)
_CLAIM_MONEY_RE = re.compile(
    r"(?P<cur>[£€$])\s*(?P<open>\()?\s*(?P<sign>[-+])?\s*"
    r"(?P<num>\d+(?:[\s,.'’]\d{3})*(?:[.,]\d+)?)\s*"
    r"(?P<scale>bn|billion|m|million|k|thousand)?\s*(?P<close>\))?",
    re.I,
)
# French / suffix-currency forms used by native FR outputs: 2 420 M€,
# 2,4 Md€, 150 k€, 2 420 M£. Parsed in addition to the prefix-currency form.
_CLAIM_MONEY_ACCOUNTING_PREFIX_RE = re.compile(
    r"(?P<cur>[£€$])\s*\(\s*(?P<num>\d+(?:[\s\u00a0\u202f,.'’]\d{3})*(?:[.,]\d+)?)\s*\)\s*"
    r"(?P<scale>bn|billion|m|million|k|thousand)?",
    re.I,
)
_CLAIM_MONEY_SUFFIX_RE = re.compile(
    r"(?<![\w£€$])(?P<open>\()?\s*(?P<sign>[-+])?\s*"
    r"(?P<num>\d+(?:[\s\u00a0\u202f.'’]\d{3})*(?:[.,]\d+)?)\s*"
    r"(?P<scale>Md|Mrd|bn|G|M|k)?\s*(?P<cur>[£€$])\s*(?P<close>\))?",
    re.I,
)
_CLAIM_PCT_RE = re.compile(r"(?<!\w)(?P<sign>[-+])?\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<kind>%|pp|bps)", re.I)

_METRIC_ALIASES = {
    # Bare "sales" is intentionally excluded: comparable/LFL/same-store sales
    # are distinct metrics and must never be laundered into consolidated revenue.
    "REVENUE": ("revenue", "turnover", "total sales", "group sales", "net sales", "chiffre d'affaires", "chiffre d’affaires", "ca"),
    "STOCKS": ("inventory", "inventories", "stock", "stocks", "sku"),
    "ADJUSTED_OPERATING_MARGIN": ("adjusted operating margin", "operating margin", "marge opérationnelle ajustée", "marge operationnelle ajustee"),
    "OPERATING_MARGIN": ("operating margin", "marge opérationnelle", "marge operationnelle"),
    "ADJUSTED_OPERATING_PROFIT": ("adjusted operating profit", "adjusted op profit", "résultat opérationnel ajusté", "resultat operationnel ajuste"),
    "OPERATING_PROFIT": ("operating profit", "operating loss", "résultat opérationnel", "resultat operationnel"),
    "FREE_CASH_FLOW": ("free cash flow", "fcf", "free cash-flow"),
    "NET_DEBT": ("net debt", "dette nette"),
    "CASH_NET_OF_OVERDRAFTS": ("cash net of overdrafts", "cash", "trésorerie nette", "tresorerie nette"),
    "CASH": ("cash and cash equivalents", "cash", "trésorerie", "tresorerie"),
}


def _norm_number(text: str) -> float:
    raw = str(text or "").replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    # Commas between three-digit groups are thousands separators; a single
    # comma followed by 1-2 digits is a decimal separator.
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", raw):
        raw = raw.replace(",", "")
    elif "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    raw = raw.replace("'", "").replace("’", "")
    return float(raw)


def _extract_numeric_components(line: str) -> list[dict[str, float]]:
    text = str(line or "")
    out: list[dict[str, float]] = []
    occupied: list[tuple[int, int]] = []
    for m in _CLAIM_MONEY_ACCOUNTING_PREFIX_RE.finditer(text):
        try:
            value = _norm_number(m.group("num"))
        except Exception:
            continue
        scale = str(m.group("scale") or "").lower()
        if scale in {"bn", "billion"}:
            value *= 1e9
        elif scale in {"m", "million"}:
            value *= 1e6
        elif scale in {"k", "thousand"}:
            value *= 1e3
        out.append({"kind": "money", "value": -value})
        occupied.append(m.span())
    for m in _CLAIM_MONEY_RE.finditer(text):
        if any(a < m.end() and m.start() < b for a, b in occupied):
            continue
        try:
            value = _norm_number(m.group("num"))
        except Exception:
            continue
        scale = str(m.group("scale") or "").lower()
        if scale in {"bn", "billion"}:
            value *= 1e9
        elif scale in {"m", "million"}:
            value *= 1e6
        elif scale in {"k", "thousand"}:
            value *= 1e3
        if m.group("sign") == "-" or (m.group("open") and m.group("close")):
            value = -value
        out.append({"kind": "money", "value": value})
        occupied.append(m.span())
    for m in _CLAIM_MONEY_SUFFIX_RE.finditer(text):
        if any(a < m.end() and m.start() < b for a, b in occupied):
            continue
        try:
            value = _norm_number(m.group("num"))
        except Exception:
            continue
        scale = str(m.group("scale") or "").lower()
        if scale in {"md", "mrd", "bn", "g"}:
            value *= 1e9
        elif scale == "m":
            value *= 1e6
        elif scale == "k":
            value *= 1e3
        if m.group("sign") == "-" or (m.group("open") and m.group("close")):
            value = -value
        out.append({"kind": "money", "value": value})
        occupied.append(m.span())
    for m in _CLAIM_PCT_RE.finditer(text):
        if any(a <= m.start() < b for a, b in occupied):
            continue
        try:
            value = _norm_number(m.group("num"))
        except Exception:
            continue
        if m.group("sign") == "-":
            value = -value
        kind = str(m.group("kind") or "%").lower()
        raw_num = str(m.group("num") or "")
        decimals = len(re.split(r"[.,]", raw_num, maxsplit=1)[1]) if re.search(r"[.,]", raw_num) else 0
        out.append({"kind": "pct" if kind == "%" else kind,
                    "value": value, "decimals": decimals})
    return out


def _claim_is_authoritative(claim: Mapping[str, Any]) -> bool:
    """Only page-confirmed facts or deterministic derivatives may authorise numbers.

    A textual ``[FACT]``/``[FAIT]`` marker, a filename or a page token is never
    evidence by itself. Canonical claims emitted by the Financial Proof Layer
    carry an explicit proof status; everything else remains fail-closed.
    """
    proof = str(claim.get("proof_status") or "").upper().strip()
    claim_type = str(claim.get("claim_type") or "").upper().strip()
    components = list(claim.get("numeric_components") or [])
    if not components:
        return False
    # v62.13.9.4.37 — NIVEAU 2 : un fait confirmé AU REGISTRE (Pappers, GLEIF, SEC)
    # fait autorité comme un fait confirmé à la page ; sa « pièce » est le registre
    # et sa date de consultation, portés par source_doc. Décision de Robin, 18/09/2026.
    if proof in ("CONFIRMED_ON_PAGE", "CONFIRMED_AT_REGISTRY"):
        source_doc = str(claim.get("source_doc") or "").strip()
        source_page = claim.get("source_page")
        refs = list(claim.get("source_refs") or [])
        return bool(source_doc and source_page not in (None, "")) or any(
            isinstance(ref, Mapping)
            and str(ref.get("source_doc") or "").strip()
            and ref.get("source_page") not in (None, "")
            for ref in refs
        )
    if proof == "DERIVED_FROM_CONFIRMED_ON_PAGE" and claim_type == "DERIVED":
        refs = [
            ref for ref in (claim.get("source_refs") or [])
            if isinstance(ref, Mapping)
            and str(ref.get("source_doc") or "").strip()
            and ref.get("source_page") not in (None, "")
        ]
        lineage = bool(claim.get("fact_instance_ids") or claim.get("stable_fact_keys"))
        return bool(refs and lineage)
    return False


def _claim_period_matches_line(line: str, claim: Mapping[str, Any]) -> bool:
    """Reject a numeric coincidence assigned to an incompatible explicit period."""
    text = str(line or "")
    line_years: set[str] = set()
    for token in re.findall(r"\bFY\s*(20\d{2}|\d{2})(?:/\d{2})?\b", text, re.I):
        line_years.add(token if len(token) == 4 else "20" + token)
    # ISO / standalone years are relevant only when the line explicitly frames
    # a financial period; page numbers such as p.29 are not considered years.
    if re.search(r"\b(?:FY|financial year|exercice|period|p[ée]riode|vs\.?|versus)\b", text, re.I):
        line_years.update(re.findall(r"\b20\d{2}\b", text))
    if not line_years:
        return True
    claim_years: set[str] = set()
    for key in ("period", "comparison_period", "period_end_date", "comparison_period_end_date"):
        value = str(claim.get(key) or "")
        for y in re.findall(r"20\d{2}", value):
            claim_years.add(y)
        for y in re.findall(r"\bFY\s*(\d{2})\b", value, re.I):
            claim_years.add("20" + y)
    return bool(claim_years and line_years.issubset(claim_years))


def _claim_period_overlaps_line(line: str, claim: Mapping[str, Any]) -> bool:
    """A partial/hybrid line may contain a wrong extra period, but must share
    at least one explicit financial year with the canonical claim.

    Exact canonical matching remains stricter via ``_claim_period_matches_line``.
    This overlap rule exists only to rebuild the *whole* contaminated sentence
    from a deterministic claim rather than laundering one matching number.
    """
    text = str(line or "")
    line_years: set[str] = set()
    for token in re.findall(r"\bFY\s*(20\d{2}|\d{2})(?:/\d{2})?\b", text, re.I):
        line_years.add(token if len(token) == 4 else "20" + token)
    if re.search(r"\b(?:FY|financial year|exercice|period|p[ée]riode|vs\.?|versus)\b", text, re.I):
        line_years.update(re.findall(r"\b20\d{2}\b", text))
    if not line_years:
        return True
    claim_years: set[str] = set()
    for key in ("period", "comparison_period", "period_end_date", "comparison_period_end_date"):
        value = str(claim.get(key) or "")
        claim_years.update(re.findall(r"20\d{2}", value))
        claim_years.update("20" + y for y in re.findall(r"\bFY\s*(\d{2})\b", value, re.I))
    return bool(claim_years and line_years.intersection(claim_years))


def _claim_metric_aliases(claim: Mapping[str, Any]) -> tuple[str, ...]:
    metric = str(claim.get("base_metric_id") or claim.get("metric_id") or "")
    for suffix in ("_CHANGE_REPORTED", "_CHANGE_PP", "_GROWTH_REPORTED"):
        if metric.endswith(suffix):
            metric = metric[:-len(suffix)]
    aliases = list(_METRIC_ALIASES.get(metric, ()))
    label = str(claim.get("label") or "").strip().lower()
    if label:
        aliases.append(label)
        # v62.13.9.4.49 — un libellé canonique bilingue (« Net income / Résultat net ») donne DEUX alias. Audit du
        # 29/09/2026 : pris comme un seul alias, il ne se retrouvait dans aucune ligne ; un fait sourcé du
        # rapport annuel, étiqueté [FACT] avec sa page, n'était rattaché à aucun claim et sortait signalé « sans pièce ».
        for part in re.split(r"\s+/\s+", label):
            if part.strip():
                aliases.append(part.strip())
    return tuple(dict.fromkeys(a for a in aliases if a))


def _component_matches(line_component: Mapping[str, Any], claim_component: Mapping[str, Any]) -> bool:
    lk = str(line_component.get("kind") or "")
    ck = str(claim_component.get("kind") or "")
    try:
        lv = float(line_component.get("value"))
        cv = float(claim_component.get("value"))
    except Exception:
        return False
    if lk == "money" and ck in {"money", "money_abs"}:
        if ck == "money_abs":
            lv, cv = abs(lv), abs(cv)
        # Relative tolerance only. A universal £/€/$ million allowance would
        # silently match materially different SME figures (for example 2m vs
        # 3m). 0.5% covers display rounding without weakening provenance.
        return abs(lv - cv) <= max(1.0, abs(cv) * 0.005)
    if lk == "pct" and ck in {"pct", "pp"}:
        decimals = int(line_component.get("decimals", 1) or 0)
        rounding = 0.55 if decimals == 0 else 0.06 if decimals == 1 else 0.006
        return abs(lv - cv) <= max(rounding, abs(cv) * 0.001)
    if lk == ck:
        decimals = int(line_component.get("decimals", 1) or 0)
        rounding = 0.55 if decimals == 0 else 0.06 if decimals == 1 else 0.006
        return abs(lv - cv) <= max(rounding, abs(cv) * 0.001)
    return False


_COMPARABLE_SALES_RE = re.compile(
    r"\b(?:comparable|like[- ]for[- ]like|lfl|same[- ]store|comp(?:\.|arable)?\s+sales|"
    r"ventes?\s+comparables?|[àa]\s+p[ée]rim[èe]tre\s+(?:constant|comparable))\b",
    re.I,
)


def _normalise_alias_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("’", "'").replace("`", "'").lower()).strip()


def _alias_matches_line(line: str, alias: str) -> bool:
    normal_line = _normalise_alias_text(line)
    normal_alias = _normalise_alias_text(alias)
    if not normal_alias:
        return False
    # Word boundaries are not sufficient around apostrophes; explicit lexical
    # boundaries protect short aliases such as FR "CA" from cash/capital/campaign.
    pattern = r"(?<![\w'’])" + re.escape(normal_alias) + r"(?![\w'’])"
    return bool(re.search(pattern, normal_line, re.I))


def match_canonical_claim(line: str, canonical_claims: Optional[Sequence[Mapping[str, Any]]]) -> Optional[Mapping[str, Any]]:
    """Return the page-confirmed/derived claim covering every numeric token.

    A numeric coincidence is not enough: approval, target and commitment
    wording must never be rewritten into a historical fact merely because the
    proposed amount equals an evidenced metric.  Canonical matching is limited
    to explicit fact/derived markers or recognisably historical observations.
    """
    claims = list(canonical_claims or [])
    if not claims:
        return None
    raw_line = str(line or "")
    low = _normalise_alias_text(raw_line)
    historical_or_fact = bool(_FACT_ONLY.search(raw_line) or _HISTORICAL_LANGUAGE.search(raw_line))
    if _EXECUTIVE_COMMITMENT_RE.search(raw_line):
        return None
    if _EXPLICIT_PROSPECTIVE.search(raw_line) and not historical_or_fact:
        return None
    components = _extract_numeric_components(raw_line)
    if not components:
        return None
    for claim in claims:
        if not _claim_is_authoritative(claim) or not _claim_period_matches_line(raw_line, claim):
            continue
        aliases = _claim_metric_aliases(claim)
        if aliases and not any(_alias_matches_line(low, alias) for alias in aliases):
            continue
        base_metric = str(claim.get("base_metric_id") or claim.get("metric_id") or "").upper()
        if base_metric.startswith("REVENUE") and _COMPARABLE_SALES_RE.search(low):
            continue
        allowed = list(claim.get("numeric_components") or [])
        if not allowed:
            try:
                val = claim.get("normalized_value")
                unit = str(claim.get("unit") or "")
                if val is not None:
                    allowed = [{"kind": "pct" if unit == "PCT" else "money" if unit == "CUR" else "number", "value": val}]
            except Exception:
                allowed = []
        if allowed and all(any(_component_matches(comp, candidate) for candidate in allowed)
                           for comp in components):
            return claim
    return None


def _claim_primary_period_matches_line(line: str, claim: Mapping[str, Any]) -> bool:
    """Allow atomic reconstruction when the current claim period is explicit.

    A hybrid sentence may contain a correct current-period amount together with
    a wrong comparison year/percentage.  In that case the whole sentence must
    be rebuilt from the derived canonical claim, not left untouched.  The
    primary claim period must nevertheless be present when the line names an
    explicit FY/year, preventing a FY2024 observation from being rewritten as a
    FY2026 fact merely because one amount happens to coincide.
    """
    text = str(line or "")
    line_years: set[str] = set()
    for token in re.findall(r"\bFY\s*(20\d{2}|\d{2})(?:/\d{2})?\b", text, re.I):
        line_years.add(token if len(token) == 4 else "20" + token)
    if re.search(r"\b(?:FY|financial year|exercice|period|p[ée]riode|vs\.?|versus)\b", text, re.I):
        line_years.update(re.findall(r"\b20\d{2}\b", text))
    if not line_years:
        return True
    primary_years: set[str] = set()
    for key in ("period", "period_end_date"):
        value = str(claim.get(key) or "")
        primary_years.update(re.findall(r"20\d{2}", value))
        primary_years.update("20" + y for y in re.findall(r"\bFY\s*(\d{2})\b", value, re.I))
    return bool(primary_years and line_years.intersection(primary_years))


def _claim_component_match_count(line: str, claim: Mapping[str, Any]) -> tuple[int, int]:
    components = _extract_numeric_components(line)
    allowed = list(claim.get("numeric_components") or [])
    if not components or not allowed:
        return 0, len(components)
    matched = sum(1 for comp in components
                  if any(_component_matches(comp, candidate) for candidate in allowed))
    return matched, len(components)


def _partial_canonical_claim(line: str, canonical_claims: Optional[Sequence[Mapping[str, Any]]]) -> Optional[Mapping[str, Any]]:
    """Reconstruct a hybrid line instead of partially laundering its numbers."""
    claims = list(canonical_claims or [])
    components = _extract_numeric_components(line)
    if len(components) < 2 or match_canonical_claim(line, claims):
        return None
    candidates: list[tuple[int, str, int, Mapping[str, Any]]] = []
    for claim in claims:
        if not _claim_is_authoritative(claim) or not _claim_period_overlaps_line(line, claim):
            continue
        aliases = _claim_metric_aliases(claim)
        if aliases and not any(_alias_matches_line(line, alias) for alias in aliases):
            continue
        base_metric = str(claim.get("base_metric_id") or claim.get("metric_id") or "").upper()
        if base_metric.startswith("REVENUE") and _COMPARABLE_SALES_RE.search(line):
            continue
        matched, total = _claim_component_match_count(line, claim)
        if matched <= 0 or matched >= total:
            continue
        is_derived = 1 if str(claim.get("claim_type") or "").upper() == "DERIVED" else 0
        candidates.append((is_derived, str(claim.get("period_end_date") or ""), matched, claim))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    if re.search(r"\b(?:declined|fell|changed|grew|increased|decreased|from|vs\.?|versus)\b", line, re.I):
        for is_derived, _, _, claim in candidates:
            if is_derived:
                return claim
    return candidates[0][3]


def _canonical_claim_line(line: str, canonical_claims: Optional[Sequence[Mapping[str, Any]]]) -> tuple[Optional[str], Optional[str]]:
    claim = match_canonical_claim(line, canonical_claims) or _partial_canonical_claim(line, canonical_claims)
    if not claim:
        return None, None
    prefix = (_PREFIX.match(line).group("prefix") if _PREFIX.match(line) else "")
    rendered = str(claim.get("compact_executive_line") or
                   claim.get("executive_line") or claim.get("display_line") or "").strip()
    rendered = re.sub(r"^\[(?:FACT|FAIT|DERIVED FROM FACTS|D[ÉE]RIV[ÉE] DE FAITS)\]\s*", "", rendered, flags=re.I)
    return prefix + rendered, str(claim.get("claim_id") or "")

def canonical_claim_line_for_text(
    line: str,
    canonical_claims: Optional[Sequence[Mapping[str, Any]]],
) -> tuple[Optional[str], Optional[str]]:
    """Public boundary: only canonical/page-confirmed claims authorise numbers.

    A ``[FACT]``/``[FAIT]`` tag, a source name or a page reference is metadata,
    never proof by itself.  Callers use this helper to rewrite a supported line
    into the clean canonical wording or to fail closed when no claim matches.
    """
    return _canonical_claim_line(line, canonical_claims)


def _brief_targets_only48(line: str, lang: str, authority) -> bool:
    items = [it for it in (authority or []) if isinstance(it, Mapping) and it.get("unit") == "BRIEF_TARGET"]
    if not items:
        return False
    try:
        from utils.editorial_quantity import mask_exempt as _mx48
        from utils.declared_quantities import brief_target_hit as _bth48
        if _QL._has_factual_past(line, lang):
            return False
        toks = [m.group(0) for m in _NUMERIC.finditer(_mx48(line))]
        toks = [x for x in toks if re.search(r"\d", x)]
        return bool(toks) and all(_bth48(line, x, items) for x in toks)
    except Exception:
        return False


# v62.13.9.4.49 — signaler en place (doctrine du 28/09/2026) ; False rétablit l'ancien remplacement.
_FLAG_IN_PLACE49 = True


def sanitize_board_scrutiny_text(
    text: str,
    lang: str = "fr",
    *,
    force_numeric_targets: bool = False,
    allow_labelled_estimates: bool = False,
    canonical_claims: Optional[Sequence[Mapping[str, Any]]] = None,
    numeric_support_claims: Optional[Sequence[Mapping[str, Any]]] = None,

    authoritative_horizon_values: Any = None,
    local_rewrite: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Govern unsupported numbers while preserving canonical facts.

    Option B is enforced in all delivery modes: unvalidated quantified scenarios
    are confined to the Word appendix and never pass the executive surfaces.
    Canonical FACT and DERIVED claims are rewritten deterministically.
    """
    if canonical_claims is None and numeric_support_claims is not None:
        canonical_claims = numeric_support_claims
    if not isinstance(text, str) or not text:
        return text or "", {"lines_rewritten": 0, "claims_rewritten": 0,
                            "samples": [], "withheld_scenarios": []}
    if _FLAG_IN_PLACE49:                               # v62.13.9.4.49 — les blocs de scénario restent en place
        _pl, _rw, _sm, _ws = _sanitize_explicit_scenario_blocks(text.splitlines(), lang)
        pre_lines, rewritten, samples = text.splitlines(), 0, []
        withheld_scenarios = [dict(w, replacement=w.get("original", ""), policy="FLAG_IN_PLACE")
                              for w in (_ws or []) if isinstance(w, dict)]
    else:
        pre_lines, rewritten, samples, withheld_scenarios = (
            _sanitize_explicit_scenario_blocks(text.splitlines(), lang)
        )
    out: list[str] = []
    seen_replacements: set[str] = set()
    in_target_table = False
    claims_rewritten = 0
    for line in pre_lines:
        # Target-table state has priority over every exemption. A target row may
        # not survive merely because one cell starts with ≈ or carries a label.
        if _FLAG_IN_PLACE49 and (_TARGET_TABLE_HEADER.search(line) or in_target_table):
            # v62.13.9.4.49 — un tableau de cibles reste entier : ses lignes chiffrées sont consignées
            # (le mainteneur les étiquette) et le rendu les signale en place.
            in_target_table = bool(line.strip()) and (in_target_table or bool(_TARGET_TABLE_HEADER.search(line)))
            if line.strip() and (_TARGET_TABLE_HEADER.search(line) or _TABLE_ROW.search(line)
                                 or (_NUMERIC.search(line) and "|" in line)):
                withheld_scenarios.append({"original": line.strip(), "replacement": line.strip(), "kind": "margin",
                                           "status": "UNVALIDATED_SCENARIO", "source_type": "narrative_table_row",
                                           "policy": "FLAG_IN_PLACE"})
            out.append(line)
            continue
        if _TARGET_TABLE_HEADER.search(line):
            in_target_table = True
            replacement = _msg("margin", lang)
            if replacement.lower() not in seen_replacements:
                out.append(replacement)
                seen_replacements.add(replacement.lower())
                rewritten += 1
                if len(samples) < 8:
                    samples.append({"before": line[:220], "after": replacement[:220]})
                withheld_scenarios.append({
                    "original": line[:1200], "replacement": replacement,
                    "status": "UNVALIDATED_SCENARIO", "source_type": "narrative_table",
                })
            continue
        if in_target_table:
            if not line.strip():
                in_target_table = False
                out.append(line)
                continue
            if _TABLE_ROW.search(line) or (_NUMERIC.search(line) and "|" in line):
                withheld_scenarios.append({
                    "original": line[:1200], "replacement": _msg("margin", lang),
                    "status": "UNVALIDATED_SCENARIO", "source_type": "narrative_table_row",
                })
                rewritten += 1
                continue
            in_target_table = False

        canonical_line, claim_id = _canonical_claim_line(line, canonical_claims)
        if canonical_line and _FLAG_IN_PLACE49:
            # v62.13.9.4.49 — la ligne de l'agent n'est plus remplacée par la formulation canonique
            # (contre-recette du 28/09 : une ligne de marge prospective devenait le rappel historique
            # « Gross margin: 55.1% (FY2025) »). Si elle ne diffère que par la forme, elle reste telle
            # quelle ; si elle porte un montant ou un taux que le fait confirmé ne porte pas (« declined
            # N % … vs £X m » contre « -n % … £Y m » dans la pièce), elle est CONSIGNÉE avec la formulation de la
            # pièce, que le rendu affiche à côté : le faux chiffre n'est plus corrigé en silence, il est
            # montré avec la valeur sourcée.
            def _vals49(s):
                return [(c.get("kind"), abs(float(c.get("value") or 0.0))) for c in _extract_numeric_components(s)]

            def _supported49(kind, v, ref) -> bool:
                # l'arrondi (« -16% » pour -16,4 %) et l'écart entre deux montants de la pièce
                # (« reduced £83m » pour £507m → £424m) ne sont pas des contradictions
                same = [c for k, c in ref if k == kind]
                if any(abs(v - c) <= max(0.01 * abs(c), 0.5 if kind == "pct" else 0.0) for c in same):
                    return True
                if kind == "money":
                    return any(abs(abs(a - b) - v) <= 0.01 * max(v, 1.0) for a in same for b in same if a != b)
                return False

            _ref49 = _vals49(canonical_line)
            if any(not _supported49(k, v, _ref49) for k, v in _vals49(line)):
                withheld_scenarios.append({"original": line.strip(), "replacement": line.strip(),
                                           "kind": "contradicted_fact", "source_line": canonical_line.strip(),
                                           "policy": "FLAG_IN_PLACE"})
            # la ligne est rattachée à un fait confirmé : elle reste telle quelle ; seule une valeur
            # contredite est consignée (ci-dessus). Elle n'est pas rejugée comme cible.
            out.append(line)
            continue
        if canonical_line:
            out.append(canonical_line)
            if canonical_line.strip() != line.strip():
                claims_rewritten += 1
                if len(samples) < 8:
                    samples.append({"before": line[:220], "after": canonical_line[:220],
                                    "claim_id": claim_id})
            continue

        # v62.13.2 — Option B ratified: no quantified unvalidated scenario is
        # allowed in the Word/PPTX executive surfaces, even when strongly tagged.
        # The tag remains recognised for migration and annex classification only.
        _ = allow_labelled_estimates  # backward-compatible API; intentionally inert

        # v62.13.9.4.29 — audit du dossier industriel v28 : « Organiser un séminaire
        # pour arbitrer entre options 1, 2 et 3 ; 30/11/2026 » devenait « Cible
        # chiffrée écartée » : un numéro d'option, une date, un label d'ordre ne
        # sont pas des nombres.
        try:
            from utils.editorial_quantity import mask_exempt as _mx
            has_numeric = bool(_NUMERIC.search(_mx(line)))
        except Exception:
            has_numeric = bool(_NUMERIC.search(line))
        has_unsupported = bool(_UNSUPPORTED.search(line) or _WORKING_SCENARIO_TAG_RE.search(line))
        has_target = bool(_TARGET_LANGUAGE.search(line) or _EXECUTIVE_COMMITMENT_RE.search(line))
        looks_historical = bool(_HISTORICAL_LANGUAGE.search(line))
        fact_marker = bool(_FACT_ONLY.search(line))
        source_marker = bool(_SOURCE_REFERENCE_ONLY.search(line))
        # v62.13.9.2 — a FACT/FAIT label, a source name or a page token is
        # metadata, never evidence. Supported facts have already been rewritten
        # above through the canonical claim matcher.
        force_rewrite = bool(
            (force_numeric_targets and has_numeric and not looks_historical)
            or ((fact_marker or source_marker) and has_numeric)
        )
        if not (has_numeric and (has_unsupported or has_target or force_rewrite)):
            out.append(line)
            continue
        # v62.13.9.4.48 — point 4 : une ligne dont TOUS les nombres sont des cibles du brief, citées
        # comme cibles, garde sa phrase : la déclaration du dirigeant est signalée une fois (section du
        # brief, registre). Présentée comme atteinte, ou mêlée d'un autre chiffre, la règle s'applique.
        if has_target and not force_rewrite and _brief_targets_only48(line, lang, authoritative_horizon_values):
            out.append(line)
            continue
        kind = _classify(line)
        # v62.13.9.4.49 — DOCTRINE « TOUT LIVRER, TOUT SIGNALER EN PLACE » (28/09/2026) : la garde ne
        # remplace plus la phrase. Elle la laisse telle quelle et consigne le constat ; le mainteneur
        # étiquette le passage et le rendu le signale. Contre-recette du 28/09 : le remplacement
        # « Quantified target withheld… » coupait un tableau de réalisé en deux, et le retrait d'une
        # phrase d'interdiction laissait l'action qu'elle interdisait.
        if _FLAG_IN_PLACE49:
            out.append(line)
            withheld_scenarios.append({"original": line.strip(), "replacement": line.strip(),
                                       "kind": kind, "policy": "FLAG_IN_PLACE"})
            continue
        replacement = _msg(kind, lang)
        prefix = (_PREFIX.match(line).group("prefix") if _PREFIX.match(line) else "")
        # v62.13.9.4.29 — contre-audit v27/v28 (§3) : une phrase d'avantages
        # qualitatifs portant une part de marché non étayée était remplacée par un
        # message générique, puis SUPPRIMÉE parce qu'une ligne précédente avait
        # produit le même message. Le chiffre sort, pas la phrase : la réécriture
        # locale de la quantité est tentée d'abord ; le message générique ne sert
        # que si un cardinal résiste.
        _local = None
        # Portée : une affirmation ou une estimation non étayée (fait de marché,
        # ordre de grandeur) ; un engagement ou une cible (approbation, budget à
        # valider, objectif) garde le message générique des contrats v62.13.2/3,
        # et les valeurs de deck restent dédoublonnées comme avant.
        try:
            if has_target or not local_rewrite:
                raise RuntimeError("generic")
            from utils.editorial_quantity import rewrite_quantities as _rq, residual_cardinals as _rc
            _body = line[len(prefix):] if prefix and line.startswith(prefix) else line
            _cand = _rq(_body, lang)
            if _cand and _cand.strip() != _body.strip() and not _rc(_cand) and not _NUMERIC.search(_cand):
                _local = prefix + _cand
        except Exception:
            _local = None
        if _local:
            out.append(_local)
            rewritten += 1
            if len(samples) < 8:
                samples.append({"before": line[:220], "after": _local[:220]})
            withheld_scenarios.append({
                "original": line.strip(), "replacement": _local.strip(),
                "kind": kind, "status": "QUANTITY_NEUTRALISED_V62429",
            })
            continue
        # v62.13.9.4.39 — DOCTRINE DES SCÉNARIOS sur une CIBLE : la ligne complète (avec sa
        # cible) part au registre, mais la décision qui la porte reste dans le corps,
        # réduite à son noyau qualitatif ; le message thématique ne vient qu'à défaut.
        # Run réel anglais du 20/09/2026 : cinq décisions prioritaires remplacées par
        # « Unsupported quantified target (…) » — zéro décision livrée.
        try:
            _body39 = line[len(prefix):] if prefix and line.startswith(prefix) else line
            _is_bare_target39 = bool(re.match(r"(?i)^\s*(?:[-*•]\s*)?(?:cibles?|objectifs?|targets?|goals?|kpi)\s*:", _body39))
            if not _is_bare_target39:      # une cible nue garde le message (9.4.29) ; toute autre ligne garde sa phrase
                _q39 = _qualitative_or_msg([_body39], _body39, lang)
                if _q39 and _q39 != replacement:
                    replacement = _q39
        except Exception:
            pass
        rendered = prefix + replacement
        key = rendered.strip().lower()
        if key in seen_replacements:
            continue
        seen_replacements.add(key)
        out.append(rendered)
        rewritten += 1
        if len(samples) < 8:
            samples.append({"before": line[:220], "after": rendered[:220]})
        withheld_scenarios.append({
            "original": line[:1200], "replacement": rendered,
            "status": "UNVALIDATED_SCENARIO", "source_type": "narrative_line",
        })
    return "\n".join(out), {
        "lines_rewritten": rewritten,
        "claims_rewritten": claims_rewritten,
        "samples": samples,
        "withheld_scenarios": withheld_scenarios,
    }

def sanitize_board_scrutiny_outputs(
    outputs: Mapping[str, Any] | None,
    *,
    finance_tone: str = "",
    lang: str = "fr",

    allow_labelled_estimates: bool = False,
    numeric_support_claims: Any = None,

    authoritative_horizon_values: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    clean = dict(outputs or {})
    report: dict[str, Any] = {
        "applied": False,
        "finance_tone": finance_tone,
        "fields_touched": 0,
        "lines_rewritten": 0,
        "claims_rewritten": 0,
        "samples": [],
        "withheld_scenarios": [],
    }
    if str(finance_tone or "").upper() != "BOARD_SCRUTINY":
        return clean, report
    report["applied"] = True
    for key, value in list(clean.items()):
        if not isinstance(value, str) or not value:
            continue
        new, rep = sanitize_board_scrutiny_text(value, lang=lang, allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
        if new != value:
            clean[key] = new
            report["fields_touched"] += 1
            report["lines_rewritten"] += int(rep.get("lines_rewritten", 0) or 0)
            report["claims_rewritten"] += int(rep.get("claims_rewritten", 0) or 0)
            for sample in rep.get("samples", []) or []:
                if len(report["samples"]) < 10:
                    report["samples"].append({"section": key, **sample})
        # v62.13.9.4.49 — les constats sont agrégés même quand rien n'est réécrit (signalement en place)
        for scenario in rep.get("withheld_scenarios", []) or []:
            report["withheld_scenarios"].append({"section": key, **scenario})
    return clean, report


def collect_numeric_scenarios_from_mapping(
    value: Any,
    *,
    section: str = "structured",
    lang: str = "en",
    _path: tuple[str, ...] = (),
    canonical_claims: Optional[Sequence[Mapping[str, Any]]] = None,
    numeric_support_claims: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, str]]:
    """Collect unsupported quantified scenarios before structured sanitisation.

    The returned objects are designed for a Word-only appendix.  They are never
    fed back into the Working Deck or the decision synthesis.
    """
    if canonical_claims is None and numeric_support_claims is not None:
        canonical_claims = numeric_support_claims
    out: list[dict[str, str]] = []
    prospective_keys = {
        "target", "targets", "goal", "goals", "objective", "objectives",
        "kpi", "kpis", "budget", "budgets", "action", "actions",
        "opportunity", "opportunities", "recommendation", "recommendations",
        "decision", "decisions", "roadmap", "milestone", "milestones",
        "risks", "risques", "dg_decisions", "codir_tradeoffs",
    }
    lower_path = tuple(str(k).lower() for k in _path)
    path_is_exec = any(k in prospective_keys for k in lower_path)
    if isinstance(value, str):
        if (_NUMERIC.search(value) and not match_canonical_claim(value, canonical_claims) and
                (_UNSUPPORTED.search(value) or _TARGET_LANGUAGE.search(value) or
                 path_is_exec or _FACT_ONLY.search(value) or
                 _SOURCE_REFERENCE_ONLY.search(value))):
            out.append({
                "section": section,
                "path": ".".join(_path),
                "original": value[:1200],
                "replacement": _msg(_classify(value), lang),
                "status": "UNVALIDATED_SCENARIO",
                "source_type": "structured_payload",
            })
        return out
    if isinstance(value, Mapping):
        for k, v in value.items():
            out.extend(collect_numeric_scenarios_from_mapping(
                v, section=section, lang=lang, _path=_path + (str(k),),
                canonical_claims=canonical_claims))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            out.extend(collect_numeric_scenarios_from_mapping(
                v, section=section, lang=lang, _path=_path + (str(i),),
                canonical_claims=canonical_claims))
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and path_is_exec:
        out.append({
            "section": section,
            "path": ".".join(_path),
            "original": str(value),
            "replacement": "TO QUALIFY",
            "status": "UNVALIDATED_SCENARIO",
            "source_type": "structured_payload",
        })
    return out


def deduplicate_scenario_appendix(items: list[Mapping[str, Any]] | None,
                                  lang: str = "en") -> list[dict[str, Any]]:
    """Deduplicate and enrich the explicit, non-executive scenario register."""
    seen: set[str] = set(); out: list[dict[str, Any]] = []
    en = str(lang or "en").lower().startswith("en")
    for item in items or []:
        original = re.sub(r"\s+", " ", str(item.get("original") or "")).strip()
        if not original:
            continue
        key = re.sub(r"[^a-z0-9]+", " ", original.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "scenario_id": f"SCN-{len(out)+1:03d}",
            "section": str(item.get("section") or "unknown"),
            "path": str(item.get("path") or ""),
            "original_hypothesis": original,
            "qualitative_replacement": str(item.get("replacement") or ""),
            "status": "UNVALIDATED_SCENARIO",
            "required_validation": (
                "Verified baseline, transparent formula, provenance, sensitivity and decision owner"
                if en else
                "Baseline vérifiée, formule transparente, provenance, sensibilité et porteur de validation"
            ),
            "allowed_surface": "WORD_APPENDIX_ONLY",
        })
    return out


def strip_numeric_targets_from_mapping(
    value: Any,
    lang: str = "fr",
    *,
    _path: tuple[str, ...] = (),
    canonical_claims: Optional[Sequence[Mapping[str, Any]]] = None,
    numeric_support_claims: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Any:
    """Defensive sanitizer for structured executive payloads.

    Structured payloads are executive surfaces: a model can drop ``[ESTIM]``
    while preserving an unsupported number.  In v62.11.3.2 numeric targets in
    action/KPI/opportunity paths are therefore governed even without an
    estimate marker.  Historical facts carrying an explicit period remain
    available.  Supply-chain maturity scores are marked estimated so the deck
    renders ``TO QUALIFY`` instead of arbitrary ``6/10`` badges.
    """
    if canonical_claims is None and numeric_support_claims is not None:
        canonical_claims = numeric_support_claims
    prospective_keys = {
        "target", "targets", "goal", "goals", "objective", "objectives",
        "kpi", "kpis", "budget", "budgets", "action", "actions",
        "plan_actions", "opportunity", "opportunities", "opportunite",
        "opportunites", "recommendation", "recommendations", "decision",
        "decisions", "points", "items", "challenges_marketing",
        "challenges_finance", "risks", "risques", "milestone", "milestones",
        "roadmap", "tradeoffs", "codir_tradeoffs", "dg_decisions",
    }
    lower_path = tuple(str(k).lower() for k in _path)
    path_is_exec = any(k in prospective_keys for k in lower_path)

    if isinstance(value, str):
        text = value
        if _FLAG_IN_PLACE49:
            # v62.13.9.4.49 — doctrine du 28/09/2026 : la charge structurée garde le texte de l'agent
            # (ni reformulation canonique, ni remplacement) ; les constats sont relevés par
            # ``collect_numeric_scenarios_from_mapping`` et signalés par le rendu.
            return text
        canonical_line, _claim_id = _canonical_claim_line(text, canonical_claims)
        if canonical_line:
            return canonical_line
        fact_marker = bool(_FACT_ONLY.search(text))
        source_marker = bool(_SOURCE_REFERENCE_ONLY.search(text))
        if _NUMERIC.search(text) and (
                _UNSUPPORTED.search(text) or path_is_exec or
                _TARGET_LANGUAGE.search(text) or fact_marker or source_marker):
            return sanitize_board_scrutiny_text(
                text, lang=lang,
                force_numeric_targets=(path_is_exec or fact_marker or source_marker),
                canonical_claims=canonical_claims, local_rewrite=False)[0]
        return text

    if isinstance(value, list):
        # v62.13.3 F3 — sanitize every item but preserve multiplicity here.
        # The PPTX common boundary has the complete semantic section and is the
        # only safe place to replace repeated fallbacks by one summary without
        # producing one summary per nested leaf list.
        return [strip_numeric_targets_from_mapping(
                    v, lang=lang, _path=_path, canonical_claims=canonical_claims)
                for v in value]
    if isinstance(value, tuple):
        return tuple(strip_numeric_targets_from_mapping(
            v, lang=lang, _path=_path, canonical_claims=canonical_claims)
                     for v in value)
    if isinstance(value, Mapping):
        out = {
            k: strip_numeric_targets_from_mapping(
                v, lang=lang, _path=_path + (str(k),),
                canonical_claims=canonical_claims)
            for k, v in value.items()
        }
        # Supply-chain scores are model assessments unless a dedicated evidence
        # object explicitly says otherwise.  The renderer already knows how to
        # show estimated scores as TO QUALIFY; enforce that semantic here.
        if lower_path and lower_path[-1] == "scores":
            if not bool(out.get("page_confirmed") or out.get("evidence_confirmed")):
                out["scores_estimated"] = True
        return out

    # Bare numeric values inside action/KPI paths are unsupported anchors.  A
    # common case is the supply-chain 1–10 score, which must not look measured.
    if isinstance(value, (int, float)) and not isinstance(value, bool) and path_is_exec:
        return ("TO QUALIFY" if str(lang).lower().startswith("en") else "À QUALIFIER")
    return deepcopy(value)


def _numeric_table_cells(line: str) -> list[str]:
    if "|" not in str(line or ""):
        return []
    cells = [re.sub(r"\s+", " ", c).strip() for c in str(line).split("|")]
    return [c for c in cells if c and _NUMERIC.search(c)]


def _looks_like_orphan_numeric_table_row(line: str) -> bool:
    """Filet post-sérialisation pour une queue de table prospective.

    Une ligne de type ``Metric 39 | 39% | 40%`` doit être bloquée même si le
    titre TARGET a été confiné plus haut. Les lignes factuelles identifiées ou
    clairement historiques (FY/période + source/page) restent autorisées.
    """
    rendered = re.sub(r"\s+", " ", str(line or "")).strip()
    if "|" not in rendered:
        return False
    numeric_cells = _numeric_table_cells(rendered)
    if len(numeric_cells) < 2:
        return False
    # Period/source metadata alone is not proof. A page-confirmed canonical
    # claim is checked by the caller before this orphan-row fail-closed test.
    # Les tableaux de scénarios contiennent typiquement plusieurs valeurs,
    # pourcentages, devises ou bps sans claim/provenance canonique.
    return True


# ── v62.13.2 — legacy scenario label recognition (Option B is active) ─────
# Bare approximation signs or the phrase "estimate, to verify" are useful
# epistemic warnings, but they are not a universal pass through the executive
# numeric gate.  Canonical facts/derived claims are handled separately.
_LABELLED_ESTIMATE_RE = _WORKING_SCENARIO_TAG_RE


def is_labelled_estimate_line(line: str) -> bool:
    """Does the line carry the strong working-scenario label?"""
    return bool(_LABELLED_ESTIMATE_RE.search(str(line or "")))


# v62.13.9.4.2 — micro-dégel borné au pendule de non-régression.
_V6213942_GUARD_DATE_RE = re.compile(
    r"^\s*(?:date\s+de\s+fin\s+cible|date\s+cible|échéance|deadline|target\s+end\s+date)\s*[:\-–]\s*"
    r"(?:\d{4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})\s*[.!]?\s*$", re.I,
)
_V6213942_GUARD_COMPLETED_RE = re.compile(
    r"(?<![\w/.,:\-–])\d+(?:[.,]\d+)?\s+[^.\n;]{0,60}?\b(?:tenu|réalisé|realisé|signé|livré|achevé|clos|"
    r"effectué|terminé|finalisé|accompli|atteint|conclu|obtenu|held|completed|delivered|signed|"
    r"achieved|closed)(?:e|es|s)?\b", re.I,
)
_V6213943_GUARD_FUTURE_TARGET_RE = re.compile(
    r"\b(?:d['’]ici|avant|by|objectifs?|cibles?|targets?|ambition|à\s+r[ée]aliser|à\s+livrer|à\s+atteindre|"
    r"to\s+deliver|to\s+achieve|to\s+reach|pr[ée]vu(?:e|s|es)?|planned|expected)\b", re.I,
)
_V6213942_GUARD_ATTRIBUTE_RE = re.compile(
    r"\b100\s*%\s*(?:électrique|electric|recyclé|recyclable|biosourcé|digital|numérique)\b", re.I,
)
# v62.13.9.4.3 — quantité d'action générique (verbe/nominalisation + cardinal + nom, tout nom).
_V6213943_GUARD_ACTION_RE = re.compile(
    r"\b(?:former|formez|ouvrir|ouvrez|lancer|lancez|recruter|recrutez|embaucher|signer|signez|"
    r"prospecter|contacter|d[ée]ployer|[ée]quiper|fermer|convertir|cr[ée]er|acqu[ée]rir|r[ée]aliser|"
    r"installer|implanter|d[ée]velopper|cibler|atteindre|livrer|vendre|produire|doubler|tripler|"
    r"conqu[ée]rir|fid[ée]liser|g[ée]n[ée]rer|gagner|obtenir|ajouter|train|open|launch|recruit|hire|"
    r"sign|deploy|equip|close|convert|create|acquire|deliver|sell|produce|reach|win|add|"
    r"formation|ouverture|lancement|recrutement|embauche|signature|prospection|d[ée]ploiement|"
    r"[ée]quipement|fermeture|conversion|cr[ée]ation|acquisition|r[ée]alisation|installation|"
    r"implantation|d[ée]veloppement|ciblage|livraison|production|conqu[êe]te|opening|launching|"
    r"recruitment|hiring|deployment|closure|creation|delivery)s?\b[^.\n;]{0,70}?"
    r"(?<![\w/.,:\-–])(?!(?:19|20)\d\d(?![\d/.,]))\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s+"
    r"(?!(?:%|pts?|points?(?!\s+(?:de\s+vente|of\s+sale))|pp|bps|M€|k€|Md€|€|£|\$|mois|semaines?|jours?|ans?|"
    r"ann[ée]es?|h\b|heures?|km|kwh|kg|t\b|tonnes?|x\b|fois|days?|weeks?|months?|years?|hours?)(?![\w]))"
    r"(?:points?\s+de\s+vente|points?\s+of\s+sale|[a-zà-öø-ÿA-ZÀ-Ö][\w'’-]{2,})",
    re.I,
)
# v62.13.9.4.3 — descripteur de tranche d'effectif (nomenclature fermée type Sirene/INSEE).
_V6213943_GUARD_BAND_RE = re.compile(
    r"\btranches?\s+\d{1,6}\s*[-–]\s*\d{1,6}\b|"
    r"\b\d{1,6}\s*[-–]\s*\d{1,6}\s+(?:salari[ée]s?|employees?|employ[ée]s?|personnes?|collaborateurs?|staff)\b",
    re.I,
)
# v62.13.9.4.3 — mot de cible + cardinal + nom (tout nom) : cible non validée.
_V6213943_GUARD_TARGET_COUNT_RE = re.compile(
    r"\b(?:objectifs?|cibles?|targets?|ambitions?|kpis?|indicateurs?|goals?)\b[^.\n;]{0,60}?"
    r"(?<![\w/.,:\-–])(?!(?:19|20)\d\d(?![\d/.,]))\d+(?:[.,]\d+)?(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?\s+"
    r"(?!(?:%|pts?|points?(?!\s+(?:de\s+vente|of\s+sale))|pp|bps|M€|k€|Md€|€|£|\$|mois|semaines?|jours?|ans?|"
    r"ann[ée]es?|h\b|heures?|km|kwh|kg|t\b|tonnes?|x\b|fois|days?|weeks?|months?|years?|hours?)(?![\w]))"
    r"(?:points?\s+de\s+vente|points?\s+of\s+sale|[a-zà-öø-ÿA-ZÀ-Ö][\w'’-]{2,})",
    re.I,
)
_V6213942_GUARD_NEW_TARGET_RE = re.compile(
    r"\b(?:convertir|conversion|réaliser|realiser|acquérir|acquerir|acquisition(?:s)?)\b.{0,90}\b\d+(?:[.,]\d+)?\b|"
    r"\b\d+(?:[.,]\d+)?\b.{0,60}\b(?:clients?\s+prioritaires?|acquisitions?\s+ciblées?)\b", re.I,
)

def find_unsupported_executive_numeric_lines(
    text: str,
    lang: str = "en",
    *,
    allow_labelled_estimates: bool = False,
    canonical_claims: Optional[Sequence[Mapping[str, Any]]] = None,
    numeric_support_claims: Optional[Sequence[Mapping[str, Any]]] = None,
    authoritative_horizon_values: Any = None,
) -> list[str]:
    """Return residual unsupported prospective numeric anchors.

    Canonical page-confirmed/derived claims are allowed by exact numeric and
    metric matching. Target tables are always governed before scenario
    exemptions. In Working mode, only the explicit structured scenario tag is
    accepted, and not for approval/commitment lines.
    """
    if canonical_claims is None and numeric_support_claims is not None:
        canonical_claims = numeric_support_claims
    if not isinstance(text, str) or not text:
        return []
    hits: list[str] = []
    in_appendix = False
    in_target_table = False
    try:                                   # v62.13.9.4.17 — registre embarqué tagué ; 9.4.18 — benchmark étiqueté
        from utils.quantity_ledger import (is_tagged_register_line as _itrl62417a,
                                           is_labelled_benchmark_line as _ilbl62418,
                                           is_epistemic_caveat_line as _iecl62419)
        _itrl62417 = lambda _l: _itrl62417a(_l) or _ilbl62418(_l) or _iecl62419(_l)   # noqa: E731
    except Exception:
        _itrl62417 = lambda _l: False      # noqa: E731
    appendix_re = re.compile(
        r"Unvalidated quantified working scenarios|"
        r"Sc[ée]narios chiffr[ée]s de travail non valid[ée]s", re.I)
    validated_target = re.compile(
        r"\[(?:VALIDATED\s+TARGET|CIBLE\s+VALID[ÉE]E|BOARD[- ]APPROVED\s+TARGET)\]", re.I)
    maturity_score = re.compile(r"\b\d+(?:[.,]\d+)?\s*/\s*10\b")
    # v62.13.9.4.5 — reconnaissance de *format* produit : une ligne du registre
    # de preuve (statut FACT/FAIT, ≥3 séparateurs de cellules, une cellule
    # source à extension documentaire, cellule terminale de page numérique) EST
    # la couche de preuve — elle n'est pas une assertion exécutive à re-prouver
    # par claims. Aucun contenu de dossier : structure seule.
    evidence_row = re.compile(
        r"^[✅✔️\s]*(?:FACT|FAIT)\b[^|]*\|(?:[^|]*\|){2,}[^|]*"
        r"\b[\w~-]+\.(?:pdf|docx?|xlsx?|pptx?|xhtml|html)\b[^|]*\|\s*\d{1,4}\s*$",
        re.I,
    )
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", str(raw or "")).strip()
        if evidence_row.match(line):
            continue
        if _itrl62417(line) or "\u2063" in raw or "⟨statut" in raw.lower() or "⟨status" in raw.lower():   # v62.13.9.4.17 — registre tagué ; 9.4.21 — marqueur d'outil
            continue
        # 9.4.65 — huitième vérification : la mention de l'outil (« Généré par CoDIR IA — v17.0 (build 9.4.65) »,
        # « Generated by CoDIR IA — … ») n'est jamais un chiffre de pilotage, même si le marqueur d'outil a été perdu.
        if re.match(r"(?i)^\W*(?:g[ée]n[ée]r[ée]\s+par|generated\s+by)\s+CoDIR\s+IA\b", line):
            continue
        # v62.13.9.4.38 — UN TITRE DE SECTION N'EST PAS UNE LIGNE EXÉCUTIVE : « §5 — Plan
        # d'actions (porteur · échéance) », « §2 — Décisions proposées ». Deux synthèses
        # réelles du 19/09/2026 ont été RETENUES sur le numéro de leur section, devenu par
        # ailleurs une valeur déclarée d'un agent. Même exclusion pour une ligne qui ne
        # porte que des repères de phase ou des dates (« T0 -> T+90 jours (2026-09-18 …) »).
        if re.match(r"^\s*§\s*\d{1,2}\s*(?:[—–\-:.]|\s+[A-ZÀ-Ÿ])", line):
            continue
        # seuls les REPÈRES DE PHASE sont court-circuités (« T0 », « T+90 », « S1 ») ; un
        # millésime ou une date restent au régime du garde — « Déployer 2026 capteurs »
        # est un compte, « Ouvrir vingt centres d'ici 2027 » une cible en lettres.
        _phase_free38 = re.sub(r"(?<![A-Za-z0-9])(?:T|J|M|W|D|H)\s*[+\-]?\s*\d{1,3}(?![A-Za-z0-9%])"
                               r"|(?<![A-Za-z0-9])(?:S|Q|H)[1-4](?![A-Za-z0-9])", " ", line)
        # ne court-circuiter QUE les lignes dont les seuls chiffres étaient des repères
        # de phase ou des dates ; une ligne sans chiffre arabe (« Recruter II ingénieurs »,
        # 9.4.32) suit le régime normal du garde, qui connaît les nombres romains.
        if re.search(r"\d", line) and not re.search(r"\d", _phase_free38):
            continue
        if not line:
            in_target_table = False
            continue
        if appendix_re.search(line):
            in_appendix = True
            continue
        if in_appendix:
            continue
        if _TARGET_TABLE_HEADER.search(line):
            in_target_table = True
            continue
        if in_target_table:
            if _TABLE_ROW.search(line) or (_NUMERIC.search(line) and "|" in line):
                hits.append(line[:500])
                continue
            in_target_table = False
        if validated_target.search(line):
            continue
        if match_canonical_claim(line, canonical_claims):
            continue
        if _partial_canonical_claim(line, canonical_claims):
            hits.append(line[:500])
            continue
        # v62.13.9.4.6 — socle deny-by-default typé (contre-audit 29/08,
        # correctif n°1) : toute quantité sans type descriptif certain retient
        # la ligne ; un fait accompli intégralement typé n'est jamais retenu.
        if _QL.line_is_protected_fact(line, lang):
            continue
        _ledger_verdict = _QL.classify_line(
            line, lang, claims=numeric_support_claims or canonical_claims,
            authority_values=authoritative_horizon_values
            if isinstance(authoritative_horizon_values, (set, list, tuple)) else None)
        if _ledger_verdict.withhold:
            hits.append(line[:500])
            continue
        if any(r in ("evidence_row", "scenario_register_row", "financial_model_row")
               for r in _ledger_verdict.reasons):
            continue  # v62.13.9.4.7 — sortie/registre du produit : symétrie trois surfaces
        if _ledger_verdict.typed and not _ledger_verdict.untyped:
            continue  # v62.13.9.4.6 — ligne intégralement typée : le legacy ne re-juge pas
        if _EQ.is_stative_present_fact(line) and not _EQ.TARGET_WORDS_RE.search(line) and not _EQ.DECISION_VERB_RE.search(line):
            pass  # v62.13.9.4.5 — fait statif au présent : jamais une cible
        elif _EQ.unsupported_quantity(line, authoritative_values=authoritative_horizon_values) and not _amount_supported_by_claims(line, canonical_claims):
            hits.append(line[:500])  # v62.13.9.4.4 — quantité prospective générique, hors claims
            continue
        # v62.13.2 — Option B: labelled unvalidated scenarios remain blocked
        # in all executive surfaces. ``allow_labelled_estimates`` is retained
        # only for API compatibility with older plugins/settings.
        _ = allow_labelled_estimates
        analysed = re.sub(r"^\s*(?:[-*•✓▌]\s*)?(?:\d+[.)]\s+)", "", line)
        if _V6213942_GUARD_DATE_RE.match(analysed):
            continue
        if _V6213943_GUARD_BAND_RE.search(analysed) and not _V6213943_GUARD_TARGET_COUNT_RE.search(analysed):
            continue  # v62.13.9.4.3 — une tranche d'effectif (nomenclature fermée) est une catégorie, jamais une cible
        if _V6213942_GUARD_COMPLETED_RE.search(analysed) and not _V6213943_GUARD_FUTURE_TARGET_RE.search(analysed):
            continue
        if _V6213942_GUARD_ATTRIBUTE_RE.search(analysed):
            residual_attribute = _V6213942_GUARD_ATTRIBUTE_RE.sub("", analysed)
            if not re.search(r"\b\d+(?:[.,]\d+)?\b", _mask_non_quantity_codes(residual_attribute)):
                continue
        if _V6213942_GUARD_NEW_TARGET_RE.search(analysed):
            hits.append(line[:500])
            continue
        if _V6213943_GUARD_ACTION_RE.search(analysed):
            hits.append(line[:500])
            continue
        if _V6213943_GUARD_TARGET_COUNT_RE.search(analysed):
            hits.append(line[:500])
            continue
        analysed = _mask_non_quantity_codes(analysed)
        analysed = _EQ.PLANNING_CONTRACT_RE.sub(" PLAN ", analysed)  # v62.13.9.4.4 — contrat de planification produit
        if not _NUMERIC.search(analysed):
            continue
        unverified_evidence = bool(
            _FACT_ONLY.search(analysed) or _SOURCE_REFERENCE_ONLY.search(analysed))
        unsupported = bool(_UNSUPPORTED.search(analysed) or _WORKING_SCENARIO_TAG_RE.search(analysed))
        # v62.13.9.2 — tags, filenames and page tokens are not proof. The
        # canonical matcher above is the sole numeric fact authority.
        if unverified_evidence:
            hits.append(line[:500])
            continue
        if _looks_like_orphan_numeric_table_row(analysed):
            hits.append(line[:500])
            continue
        prospective = bool(_TARGET_LANGUAGE.search(analysed) or _EXECUTIVE_COMMITMENT_RE.search(analysed))
        scenario = bool(_SCENARIO_BLOCK_START.search(analysed))
        arbitrary_score = bool(maturity_score.search(analysed))
        historical = bool(_HISTORICAL_LANGUAGE.search(analysed))
        if historical and _V6213943_GUARD_FUTURE_TARGET_RE.search(analysed):
            historical = False  # v62.13.9.4.3 — un participe passé n'efface pas une cible future explicite
        explicit_forward = bool(_EXPLICIT_PROSPECTIVE.search(analysed))
        timeline_only = bool(
            re.search(r"\b(?:roadmap|milestone|window|horizon|phase|planning|jalon|fen[êe]tre)\b", analysed, re.I)
            and re.search(r"\b(?:days?|months?|years?|jours?|mois|ans?)\b", analysed, re.I)
            and not re.search(r"[£€$]|%|\bpp\b|\bbps\b|\b\d+(?:[.,]\d+)?x\b", analysed, re.I)
        )
        if timeline_only and not prospective and not unsupported and not scenario:
            continue
        if arbitrary_score or unsupported or scenario or prospective or unverified_evidence:
            if historical and not (unsupported or scenario or arbitrary_score or explicit_forward or unverified_evidence):
                continue
            hits.append(line[:500])
    return list(dict.fromkeys(hits))

def deduplicate_guard_fallbacks(value: Any, lang: str = "en") -> tuple[Any, dict[str, Any]]:
    """Collapse repeated guard fallbacks inside one rendered section.

    The renderer often stores one slide as a nested mapping (decisions, actions,
    KPI and challenges in separate lists).  De-duplicating each leaf list in
    isolation leaves the same fallback visible five times on one slide.  This
    function therefore treats the supplied object as one semantic scope: it
    counts exact guard fallbacks recursively, replaces the first occurrence of
    each repeated fallback by one compact summary, and blanks/removes later
    duplicates without changing any layout object.
    """
    guard_lines = {s.strip().lower() for s in _LEGACY_FALLBACK_STRINGS} | {_msg(k, lang).strip().lower() for k in (
        "dividend", "inventory", "marketing", "margin", "stores",
        "liquidity", "service", "growth", "generic")}
    counts: dict[str, int] = {}

    def count(obj: Any) -> None:
        if isinstance(obj, str):
            key = re.sub(r"\s+", " ", obj).strip().lower()
            if key in guard_lines:
                counts[key] = counts.get(key, 0) + 1
        elif isinstance(obj, Mapping):
            for item in obj.values():
                count(item)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                count(item)

    count(value)
    repeated = {k: n for k, n in counts.items() if n > 1}
    if not repeated:
        return deepcopy(value), {"duplicates_removed": 0, "scopes_touched": 0,
                                 "summaries_inserted": 0, "fallback_counts": counts}

    seen: set[str] = set()
    removed = 0
    inserted = 0

    def summary(n: int) -> str:
        # v62.13.9.4.39 — pas d'annexe (doctrine des scénarios : registre du dossier complet)
        # et un libellé sans compte en tête, que la réécriture des comptes ne peut pas
        # mutiler (« des quantified proposals withheld — volume à valider », trame réelle
        # du 20/09/2026). Le nombre reste dans le registre.
        if str(lang or "en").lower().startswith("en"):
            return "Quantified proposals withheld — kept in the register of the complete file"
        return "Propositions chiffrées écartées — conservées au registre du dossier complet"

    def walk(obj: Any) -> Any:
        nonlocal removed, inserted
        if isinstance(obj, str):
            key = re.sub(r"\s+", " ", obj).strip().lower()
            if key not in repeated:
                return obj
            if key not in seen:
                seen.add(key); inserted += 1
                return summary(repeated[key])
            removed += 1
            return ""
        if isinstance(obj, Mapping):
            return {k: walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            out = [walk(v) for v in obj]
            return [v for v in out if not (isinstance(v, str) and not v.strip())]
        if isinstance(obj, tuple):
            out = [walk(v) for v in obj]
            return tuple(v for v in out if not (isinstance(v, str) and not v.strip()))
        return deepcopy(obj)

    return walk(value), {"duplicates_removed": removed,
                         "scopes_touched": 1,
                         "summaries_inserted": inserted,
                         "fallback_counts": repeated}


def _docx_visible_units(payload: bytes) -> list[str]:
    """Extract paragraphs and table rows in document order."""
    import io
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(io.BytesIO(payload))
    units: list[str] = []
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            txt = "".join(node.text or "" for node in child.iter()
                          if node.tag == qn("w:t"))
            if txt.strip():
                units.append(txt.strip())
        elif child.tag == qn("w:tbl"):
            for row in child.findall(".//" + qn("w:tr")):
                cells: list[str] = []
                for cell in row.findall("./" + qn("w:tc")):
                    txt = "".join(node.text or "" for node in cell.iter()
                                  if node.tag == qn("w:t"))
                    cells.append(re.sub(r"\s+", " ", txt).strip())
                rendered = " | ".join(cells).strip(" |")
                if rendered:
                    units.append(rendered)
    return units


def _iter_pptx_shapes(shapes):
    for shape in shapes:
        yield shape
        nested = getattr(shape, "shapes", None)
        if nested is not None:
            yield from _iter_pptx_shapes(nested)


def _pptx_visible_units(payload: bytes) -> list[str]:
    """Extract one audit unit per paragraph or table row from every slide."""
    import io
    from pptx import Presentation
    prs = Presentation(io.BytesIO(payload))
    units: list[str] = []
    for slide in prs.slides:
        for shape in _iter_pptx_shapes(slide.shapes):
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    rendered = " | ".join(
                        re.sub(r"\s+", " ", cell.text or "").strip()
                        for cell in row.cells).strip(" |")
                    if rendered:
                        units.append(rendered)
            if getattr(shape, "has_text_frame", False):
                for para in shape.text_frame.paragraphs:
                    txt = re.sub(r"\s+", " ", para.text or "").strip()
                    if txt:
                        units.append(txt)
    return units


def _looks_historical_table_context(header: str, context: str) -> bool:
    joined = f"{context} | {header}"
    scenario = bool(re.search(
        r"\b(?:target|forecast|projection|scenario|assumption|budget|base\s+case|"
        r"stress\s+case|upside|downside|cible|pr[ée]vision|sc[ée]nario|hypoth[èe]se)\b",
        joined, re.I))
    if scenario:
        return False
    periods = re.findall(r"\b(?:FY\s*\d{2}(?:/\d{2})?|20\d{2}(?:/\d{2})?)\b", joined, re.I)
    factual_context = bool(re.search(
        r"\b(?:financial\s+facts?|factual\s+baseline|verified\s+facts?|source\s+traceability|"
        r"historical|actuals?|reported|financial\s+statements?|faits\s+financiers|"
        r"faits\s+v[ée]rifi[ée]s|baseline\s+factuelle|tra[çc]abilit[ée])\b",
        joined, re.I))
    return factual_context or len(periods) >= 2


def _docx_scenario_paragraph_ranges(doc: Any) -> list[dict[str, Any]]:
    paragraphs = list(doc.paragraphs)
    # v62.13.9.4.31 — les paragraphes écrits par le produit (sommaire, bandeaux)
    # portent la marque d'outil : un renvoi vers l'annexe n'ouvre pas l'annexe.
    texts = ["" if "\u2063" in (p.text or "") else re.sub(r"\s+", " ", p.text or "").strip()
             for p in paragraphs]
    appendix_re = re.compile(
        r"Unvalidated quantified working scenarios|Sc[ée]narios chiffr[ée]s de travail non valid[ée]s", re.I)
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(texts):
        line = texts[i]
        if appendix_re.search(line):
            break
        if not _SCENARIO_BLOCK_START.search(line):
            i += 1
            continue
        start = i; block = [line]; i += 1
        while i < len(texts):
            nxt = texts[i]
            if appendix_re.search(nxt) or nxt.strip() == "---" or _is_scenario_boundary(nxt):
                break
            block.append(nxt); i += 1
        original = "\n".join(x for x in block if x).strip()
        if original:
            out.append({"start": start, "end": i - 1, "original": original})
    return out


def _render_docx_table(rows: Sequence[Sequence[str]]) -> str:
    return "\n".join(" | ".join(str(c or "").strip() for c in row).strip(" |") for row in rows).strip()


def audit_docx_executive_numbers_detailed(payload: bytes, lang: str = "en", *, allow_labelled_estimates: bool = False, numeric_support_claims: Any = None, authoritative_horizon_values: Any = None) -> list[dict[str, Any]]:
    """Context-aware DOCX post-control.

    Table rows are evaluated with their heading/header. This prevents a factual
    FY2025/FY2024 comparison table from being mistaken for an unsupported
    target merely because the period/source is carried by the header instead of
    repeated in every row. True forecast/target tables remain fail-closed.
    """
    import io
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(io.BytesIO(payload))
    hits: list[dict[str, Any]] = []
    recent_paragraphs: list[str] = []
    in_appendix = False
    appendix_re = re.compile(
        r"(?<!\u2063)(?:Unvalidated quantified working scenarios|"      # v62.13.9.4.31 — jamais depuis le sommaire
        r"Sc[ée]narios chiffr[ée]s de travail non valid[ée]s)", re.I)
    p_index = -1
    t_index = -1
    scenario_ranges = _docx_scenario_paragraph_ranges(doc)
    for block in scenario_ranges:
        hits.append({"kind": "scenario_block", "paragraph_index": int(block["start"]),
                     "paragraph_end_index": int(block["end"]),
                     "text": str(block["original"]),
                     "reason": "unvalidated_numeric_scenario_block"})
    scenario_para_indexes = {idx for block in scenario_ranges
                             for idx in range(int(block["start"]), int(block["end"]) + 1)}
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p_index += 1
            text = "".join(node.text or "" for node in child.iter() if node.tag == qn("w:t"))
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            if appendix_re.search(text):
                in_appendix = True
                recent_paragraphs.append(text)
                continue
            recent_paragraphs = (recent_paragraphs + [text])[-4:]
            if in_appendix:
                continue
            if p_index in scenario_para_indexes:
                continue
            unit_hits = find_unsupported_executive_numeric_lines(text, lang=lang, allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
            for hit in unit_hits:
                hits.append({"kind": "paragraph", "paragraph_index": p_index,
                             "text": hit, "reason": "unsupported_numeric_paragraph"})
        elif child.tag == qn("w:tbl"):
            t_index += 1
            rows = []
            for row in child.findall(".//" + qn("w:tr")):
                cells = []
                for cell in row.findall("./" + qn("w:tc")):
                    text = "".join(node.text or "" for node in cell.iter() if node.tag == qn("w:t"))
                    cells.append(re.sub(r"\s+", " ", text).strip())
                rows.append(cells)
            if not rows or in_appendix:
                continue
            header = " | ".join(rows[0]).strip(" |")
            context = " | ".join(recent_paragraphs[-3:])
            if _is_transposed_scenario_table(rows, context):
                hits.append({"kind": "scenario_table", "table_index": t_index,
                             "text": _render_docx_table(rows), "header": header[:500],
                             "context": context[:500],
                             "reason": "unsupported_transposed_scenario_table"})
                continue
            historical = _looks_historical_table_context(header, context)
            scenario_table = bool(re.search(
                r"\b(?:target|forecast|projection|scenario|assumption|budget|base\s+case|"
                r"stress\s+case|cible|pr[ée]vision|sc[ée]nario|hypoth[èe]se)\b",
                f"{context} | {header}", re.I))
            for r_index, cells in enumerate(rows):
                rendered = " | ".join(cells).strip(" |")
                if not rendered:
                    continue
                unit_hits = find_unsupported_executive_numeric_lines(rendered, lang=lang, allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
                if not unit_hits:
                    continue
                # Row-level explicit estimate/target markers override historical context.
                explicit_forward = bool(_UNSUPPORTED.search(rendered) or _EXPLICIT_PROSPECTIVE.search(rendered))
                if historical and not scenario_table and not explicit_forward:
                    continue
                for hit in unit_hits:
                    hits.append({"kind": "table_row", "table_index": t_index,
                                 "row_index": r_index, "text": hit,
                                 "header": header[:500], "context": context[:500],
                                 "reason": "unsupported_numeric_table_row"})
    # Stable de-duplication.
    unique: list[dict[str, Any]] = []
    seen = set()
    for item in hits:
        key = (item.get("kind"), item.get("paragraph_index"), item.get("paragraph_end_index"),
               item.get("table_index"), item.get("row_index"), item.get("text"))
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique


def _append_docx_scenario_archive(doc: Any, original: str, replacement: str, *, source_type: str, lang: str) -> None:
    heading = ("Annex — Unvalidated quantified working scenarios"
               if str(lang or "en").lower().startswith("en")
               else "Annexe — Scénarios chiffrés de travail non validés")
    # The normal CoDIR report already owns the named scenario register. The
    # last-mile repair enriches it, but does not create a new visible appendix
    # in small utility documents or third-party DOCX files.
    if not any(heading.lower() in (p.text or "").lower() for p in doc.paragraphs):
        return
    p = doc.add_paragraph()
    p.add_run(f"[SERIALIZED QUARANTINE · {source_type}] ").bold = True
    p.add_run(str(original or "")[:12000])
    doc.add_paragraph(("Executive replacement: " if str(lang or "en").lower().startswith("en") else "Remplacement exécutif : ") + replacement)


def repair_docx_executive_numbers(payload: bytes, lang: str = "en", *, allow_labelled_estimates: bool = False, numeric_support_claims: Any = None,
    authoritative_horizon_values: Any = None,
) -> tuple[bytes, dict[str, Any]]:
    """Deterministically quarantine residual executive targets in the real DOCX.

    The upstream guard should normally remove them. This last-mile repair is a
    safety net for serialization-specific structures (notably tables). It never
    rewrites factual historical tables and never touches the named scenario
    appendix.
    """
    import io
    from docx import Document
    hits = audit_docx_executive_numbers_detailed(payload, lang=lang, allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
    if not hits:
        return payload, {"before": 0, "repaired": 0, "after": 0, "samples": []}
    doc = Document(io.BytesIO(payload))
    paragraphs = list(doc.paragraphs)
    tables = list(doc.tables)
    if _FLAG_IN_PLACE49:
        # v62.13.9.4.49 — doctrine du 28/09/2026 : la réparation exécutive ne réécrit plus ; chaque constat reçoit
        # une étiquette À SA PLACE (paragraphe, lignes chiffrées d'un bloc, rangées chiffrées d'un tableau), que le
        # rendu signale. Audit du 29/09/2026 (campagne réelle de référence) : appelée seule, elle laissait la valeur
        # « +30 » dans le corps sans retrait ni signalement.
        _tag49 = " ⟨status : unsourced figure⟩" if str(lang).lower().startswith("en") else " ⟨statut : chiffre sans pièce⟩"

        def _has_value49(txt: str) -> bool:
            # un libellé de période (« FY2027 target », « 2026 », « Q3 2027 ») n'est pas une valeur à signaler
            rest = re.sub(r"(?i)\b(?:FY|CY|Q[1-4]|H[12]|S[12]|T[1-4])?\s?'?(?:19|20)\d{2}\b(?:\s?[/–-]\s?(?:19|20)?\d{2})?", " ", txt or "")
            return bool(re.search(r"\d", rest))

        def _flag_par49(par) -> int:
            if not _has_value49(par.text or "") or "⟨" in (par.text or ""):
                return 0
            # 9.4.61 — contre-recette du 12/10 (A60-02) : scores internes, durées et références ne reçoivent pas l'étiquette
            # générique « chiffre sans pièce » (à la source : le rendu reste idempotent d'une passe à l'autre)
            try:
                from utils.flag_render49 import _TECH_LINE61 as _tl61
                if _tl61.search(par.text or ""):
                    return 0
            except Exception:
                pass
            par.add_run(_tag49)
            return 1

        flagged49 = 0
        _cc49 = list(numeric_support_claims or [])       # la garde rattache directement aux claims de soutien
        _en49 = str(lang).lower().startswith("en")
        for item in hits:
            kind = item.get("kind")
            if kind == "paragraph":
                idx = int(item.get("paragraph_index", -1))
                if 0 <= idx < len(paragraphs):
                    _par49 = paragraphs[idx]
                    # une ligne hybride (vrai libellé, faux montants) porte la formulation de la pièce, comme dans le
                    # texte : « contredit par la pièce : … » au lieu d'être reconstruite en silence
                    _canon49 = None
                    if _cc49 and "⟨" not in (_par49.text or ""):
                        try:
                            _canon49, _ = _canonical_claim_line(_par49.text or "", _cc49)
                        except Exception:
                            _canon49 = None
                    # 9.4.57 — contre-recette du 10/10 (§5.3) : la garde étiquetait « contredit par la pièce : Trésorerie
                    # 58,1 M$ » un paragraphe qui citait 58,13 M$ et dont le chiffre non étayé était… un ROIC. La
                    # contradiction n'est affirmée que si les montants de la ligne contredisent VRAIMENT le fait.
                    _contra57 = False
                    if _canon49:
                        try:
                            from utils.v62136_fr_path_maintenance import _amounts_contradict49 as _ac57
                            _contra57 = bool(_ac57(_par49.text or "", _canon49))
                        except Exception:
                            _contra57 = False
                    if _canon49 and _contra57:
                        _par49.add_run((" ⟨status : contradicted by the source: " if _en49 else " ⟨statut : contredit par la pièce : ")
                                       + re.sub(r"\s+", " ", _canon49).strip()[:110] + "⟩")
                        flagged49 += 1
                    else:
                        flagged49 += _flag_par49(_par49)
            elif kind == "scenario_block":
                start = int(item.get("paragraph_index", -1)); end = int(item.get("paragraph_end_index", start))
                for j in range(max(0, start), min(end + 1, len(paragraphs))):
                    flagged49 += _flag_par49(paragraphs[j])
            else:
                ti = int(item.get("table_index", -1)); ri = item.get("row_index")
                if 0 <= ti < len(tables):
                    rows = list(tables[ti].rows)
                    # la rangée d'en-tête est un libellé, jamais une valeur (« Metric | FY2027 target | … »)
                    targets = [rows[int(ri)]] if ri is not None and 0 <= int(ri) < len(rows) else rows[1:]
                    # colonnes de RÉALISÉ (« FY2026 Actual ») : elles relèvent du rapprochement avec la pièce (réalisé
                    # unique), pas d'un signalement « sans pièce » — un réalisé conforme n'est pas un chiffre douteux
                    _hdr_cells49 = list(rows[0].cells) if rows else []
                    _actual_cols49 = {i for i, c in enumerate(_hdr_cells49)
                                      if re.search(r"(?i)\b(?:actuals?|réalisé|réel|historical|reported|publié)\b", c.text or "")}
                    for row in targets:
                        # chaque cellule chiffrée est étiquetée (atomicité de rangée, comme le mainteneur) ;
                        # la première cellule (libellé) ne l'est pas si d'autres cellules portent les chiffres
                        cells = [c for i, c in enumerate(row.cells)
                                 if re.search(r"\d", c.text or "") and i not in _actual_cols49]
                        if len(cells) > 1 and cells[0]._tc is row.cells[0]._tc:
                            cells = cells[1:]
                        for c in cells:
                            flagged49 += _flag_par49(c.paragraphs[-1])
        out = io.BytesIO(); doc.save(out)
        return out.getvalue(), {"before": len(hits), "repaired": 0, "flagged": flagged49, "after": 0,
                                "samples": [], "policy": "FLAG_IN_PLACE"}
    # Stable OOXML object lookup: removing rows/paragraphs must not shift the
    # indexes carried by the pre-repair audit findings.
    table_rows = {(ti, ri): row for ti, table in enumerate(tables)
                  for ri, row in enumerate(list(table.rows))}
    repaired = 0
    samples = []
    seen_table_replacement: set[tuple[int, str]] = set()
    removed_paragraph_ids: set[int] = set()
    for item in hits:
        original = str(item.get("text") or "")
        replacement = _qualitative_or_msg([original], original, lang)
        # v62.13.9.4.12 — LOCALITÉ PAR MONTANT. Une phrase mixte —
        # « le CA était de 15 M€ en 2025 ; le plan vise 15 recrutements en
        # 2027 » — perdait son fait daté avec sa cible, d'autant plus
        # facilement que les deux grandeurs valent le même nombre. On isole
        # la proposition fautive ; à défaut de découpage utile, on retombe
        # sur le remplacement de ligne.
        if item.get("kind") != "scenario_block":
            try:
                from utils.v62136_fr_path_maintenance import _clause_local_rewrite
                _sup62412 = list(numeric_support_claims or [])
                _local = _clause_local_rewrite(
                    original, lang,
                    {"lang": lang, "numeric_support_claims": _sup62412},
                    verdict=lambda c: bool(find_unsupported_executive_numeric_lines(
                        c, lang=lang,
                        allow_labelled_estimates=allow_labelled_estimates,
                        numeric_support_claims=_sup62412)))
                if _local:
                    replacement = _local
            except Exception:
                pass
        if item.get("kind") == "scenario_block":
            start = int(item.get("paragraph_index", -1)); end = int(item.get("paragraph_end_index", start))
            if 0 <= start < len(paragraphs):
                original_block = "\n".join(paragraphs[j].text for j in range(start, min(end + 1, len(paragraphs))))
                paragraphs[start].text = replacement
                for j in range(start + 1, min(end + 1, len(paragraphs))):
                    paragraph = paragraphs[j]
                    element = paragraph._element
                    parent = element.getparent()
                    if parent is not None and id(element) not in removed_paragraph_ids:
                        parent.remove(element)
                        removed_paragraph_ids.add(id(element))
                _append_docx_scenario_archive(doc, original_block, replacement,
                                              source_type="narrative_scenario_block", lang=lang)
                repaired += 1
        elif item.get("kind") == "paragraph":
            idx = int(item.get("paragraph_index", -1))
            if 0 <= idx < len(paragraphs):
                canonical, _claim_id = _canonical_claim_line(original, numeric_support_claims)
                paragraphs[idx].text = canonical or replacement
                repaired += 1
        elif item.get("kind") == "scenario_table":
            ti = int(item.get("table_index", -1))
            if 0 <= ti < len(tables):
                original_table = item.get("text") or ""
                table = tables[ti]
                fallback_p = doc.add_paragraph(replacement)
                table._tbl.addprevious(fallback_p._p)
                parent = table._tbl.getparent()
                if parent is not None:
                    parent.remove(table._tbl)
                _append_docx_scenario_archive(doc, str(original_table), replacement,
                                              source_type="transposed_scenario_table", lang=lang)
                repaired += 1
        elif item.get("kind") == "table_row":
            ti = int(item.get("table_index", -1)); ri = int(item.get("row_index", -1))
            row = table_rows.get((ti, ri))
            if row is not None:
                key = (ti, replacement.lower())
                if key not in seen_table_replacement:
                    for ci, cell in enumerate(row.cells):
                        cell.text = replacement if ci == 0 else ""
                    seen_table_replacement.add(key)
                else:
                    row_el = row._tr
                    parent = row_el.getparent()
                    if parent is not None:
                        parent.remove(row_el)
                repaired += 1
        if len(samples) < 10:
            samples.append({"before": original[:300], "after": replacement,
                            "kind": item.get("kind"), "reason": item.get("reason")})
    # v62.13.3 F3 — upstream row-level retention can leave visually empty
    # scenario rows behind.  Remove only fully empty rows from tables that
    # already contain a guard fallback; factual/traceability tables are untouched.
    _fallback_tokens = tuple(s.strip().lower() for s in _LEGACY_FALLBACK_STRINGS) + tuple(_msg(k, lang).strip().lower() for k in (
        "dividend", "inventory", "marketing", "margin", "stores",
        "liquidity", "service", "growth", "generic"))
    for table in list(doc.tables):
        rows_now = list(table.rows)
        table_text = " ".join(cell.text for row in rows_now for cell in row.cells).lower()
        if not any(token and token in table_text for token in _fallback_tokens):
            continue
        for row in rows_now[1:]:
            if all(not re.sub(r"\s+", " ", cell.text or "").strip() for cell in row.cells):
                row_el = row._tr
                parent = row_el.getparent()
                if parent is not None:
                    parent.remove(row_el)

    out = io.BytesIO(); doc.save(out)
    final = out.getvalue()
    after_hits = audit_docx_executive_numbers_detailed(final, lang=lang, allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
    return final, {"before": len(hits), "repaired": repaired,
                   "after": len(after_hits), "samples": samples,
                   "remaining": after_hits[:10]}


def audit_docx_executive_numbers(payload: bytes, lang: str = "en", *, allow_labelled_estimates: bool = False, numeric_support_claims: Any = None,
    authoritative_horizon_values: Any = None,
) -> list[str]:
    return [str(x.get("text") or "") for x in
            audit_docx_executive_numbers_detailed(payload, lang=lang, allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)]


def pptx_flag_units(payload: bytes, lang: str = "en", *, numeric_support_claims: Any = None,
                    authoritative_horizon_values: Any = None) -> list[str]:
    """v62.13.9.4.49 — constats du deck pour le signalement en place : la détection de la garde
    (celle qui réécrivait jusqu'ici : marqueurs d'estimation, langage de cible, engagements, tableaux de
    cibles) ET celle du contrôle final, réunies. Sans la première, une cible marquée « [ESTIM] »
    échappait au contrôle final du deck, qui ne l'avait jamais vu puisque la garde le retirait avant."""
    text = "\n".join(_pptx_visible_units(payload))
    _clean, rep = sanitize_board_scrutiny_text(text, lang=lang, numeric_support_claims=numeric_support_claims,
                                                authoritative_horizon_values=authoritative_horizon_values)
    units = [str(w.get("original") or "") for w in (rep.get("withheld_scenarios") or [])
             if isinstance(w, dict) and w.get("policy") == "FLAG_IN_PLACE"]
    units += [str(x) for x in find_unsupported_executive_numeric_lines(
        text, lang=lang, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)]
    return [u for u in dict.fromkeys(units) if u.strip()]


def audit_pptx_executive_numbers(payload: bytes, lang: str = "en", *, allow_labelled_estimates: bool = False, numeric_support_claims: Any = None, authoritative_horizon_values: Any = None) -> list[str]:
    return find_unsupported_executive_numeric_lines(
        "\n".join(_pptx_visible_units(payload)), lang=lang,
        allow_labelled_estimates=allow_labelled_estimates, numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)


def _set_paragraph_text_preserving_first_run(paragraph: Any, text: str) -> None:
    runs = list(getattr(paragraph, "runs", []) or [])
    if runs:
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""
    else:
        paragraph.text = text


def repair_pptx_executive_numbers(
    payload: bytes,
    lang: str = "en",
    *,
    allow_labelled_estimates: bool = False,
    numeric_support_claims: Any = None,

    authoritative_horizon_values: Any = None,
) -> tuple[bytes, dict[str, Any]]:
    """Repair the serialized Working Deck without changing geometry.

    Page-confirmed and deterministic derived lines are replaced by their
    canonical claim wording. Residual unsupported quantified anchors are
    replaced by the same qualitative fail-safe used upstream.
    """
    import io
    from pptx import Presentation

    before = audit_pptx_executive_numbers(
        payload, lang=lang, allow_labelled_estimates=allow_labelled_estimates,
        numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
    prs = Presentation(io.BytesIO(payload))
    repaired = 0
    claims_rewritten = 0
    samples: list[dict[str, Any]] = []

    for slide_no, slide in enumerate(prs.slides, start=1):
        for shape in _iter_pptx_shapes(slide.shapes):
            if getattr(shape, "has_text_frame", False):
                for paragraph in shape.text_frame.paragraphs:
                    original = re.sub(r"\s+", " ", paragraph.text or "").strip()
                    if not original:
                        continue
                    canonical, claim_id = _canonical_claim_line(
                        original, numeric_support_claims)
                    if canonical and canonical.strip() != original:
                        _set_paragraph_text_preserving_first_run(paragraph, canonical)
                        repaired += 1
                        claims_rewritten += 1
                        if len(samples) < 12:
                            samples.append({"slide": slide_no, "before": original[:400],
                                            "after": canonical[:400],
                                            "claim_id": claim_id, "kind": "canonical"})
                        continue
                    hits = find_unsupported_executive_numeric_lines(
                        original, lang=lang,
                        allow_labelled_estimates=allow_labelled_estimates,
                        numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
                    if hits:
                        replacement = _qualitative_or_msg([original], original, lang)
                        _set_paragraph_text_preserving_first_run(paragraph, replacement)
                        repaired += 1
                        if len(samples) < 12:
                            samples.append({"slide": slide_no, "before": original[:400],
                                            "after": replacement, "kind": "withheld"})
            if getattr(shape, "has_table", False):
                for row_no, row in enumerate(shape.table.rows):
                    rendered = " | ".join(
                        re.sub(r"\s+", " ", cell.text or "").strip()
                        for cell in row.cells).strip(" |")
                    if not rendered:
                        continue
                    canonical, claim_id = _canonical_claim_line(
                        rendered, numeric_support_claims)
                    if canonical:
                        row.cells[0].text = canonical
                        for cell in row.cells[1:]:
                            cell.text = ""
                        repaired += 1
                        claims_rewritten += 1
                        continue
                    hits = find_unsupported_executive_numeric_lines(
                        rendered, lang=lang,
                        allow_labelled_estimates=allow_labelled_estimates,
                        numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
                    if hits:
                        if _FLAG_IN_PLACE49:
                            # 9.4.56 — doctrine « tout livrer, signaler » (décision du dirigeant, 08/10/2026) : la rangée
                            # reste entière ; sa première cellule porte le signalement au lieu d'être remplacée
                            _f56 = (" ⚠ to verify — unsupported quantified target" if str(lang).lower().startswith("en")
                                    else " ⚠ à vérifier — cible chiffrée non étayée")
                            if _f56.strip() not in row.cells[0].text:
                                row.cells[0].text = row.cells[0].text.rstrip() + _f56
                        else:
                            row.cells[0].text = _msg(_classify(rendered), lang)
                            for cell in row.cells[1:]:
                                cell.text = ""
                        repaired += 1

    out = io.BytesIO()
    prs.save(out)
    final = out.getvalue()
    after = audit_pptx_executive_numbers(
        final, lang=lang, allow_labelled_estimates=allow_labelled_estimates,
        numeric_support_claims=numeric_support_claims,
        authoritative_horizon_values=authoritative_horizon_values)
    return final, {"before": len(before), "repaired": repaired,
                   "claims_rewritten": claims_rewritten, "after": len(after),
                   "remaining": after[:20], "samples": samples}


__all__ = [
    "sanitize_board_scrutiny_text",
    "sanitize_board_scrutiny_outputs",
    "collect_numeric_scenarios_from_mapping",
    "deduplicate_scenario_appendix",
    "strip_numeric_targets_from_mapping",
    "find_unsupported_executive_numeric_lines",
    "audit_docx_executive_numbers",
    "audit_docx_executive_numbers_detailed",
    "repair_docx_executive_numbers",
    "audit_pptx_executive_numbers",
    "repair_pptx_executive_numbers",
    "match_canonical_claim",
    "canonical_claim_line_for_text",
    "deduplicate_guard_fallbacks",
]
