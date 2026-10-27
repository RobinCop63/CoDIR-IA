"""
patches/fact_identity.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · E1)

IDENTITÉ DU FAIT PROBANT — les cinq identifiants (note référente M6-B v3,
Partie II §4).

Pourquoi c'est dans B.1 et pas différé : sans identité stable, deux runs
produisent des faits « riches » mais non rapprochables — Christopher ne
saurait pas si c'est le même fait, une version, un doublon, une correction
ou un conflit. L'identité est la condition de la mémoire fiable, donc elle
naît AVEC le fait.

Contrat (Partie II §4) :
    stable_fact_key   = hash(metric_canonical_id + period + perimeter.entity
                             + perimeter.level + normalized_value + unit + scale)
    fact_instance_id  = hash(stable_fact_key + source_ref)
        # source_ref B.1 provisoire : registry_resolution_id |
        # evidence_locator_hash | brief_ref | B1_UNKNOWN (source_id réel → B.2)
    run_id            : identifiant du run (horodaté)
    analysis_context_id : identifiant du contexte d'analyse de ce run
    entity_id         : identifiant registre (SIREN / LEI si connu)
    metric_canonical_id : clé métrique normalisée (REVENUE, NET_INCOME, HEADCOUNT…)

Propriété testée (E1) : fact_id STABLE entre deux runs du même cas —
le run_id ne participe PAS au stable_fact_key ni au fact_instance_id.

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional, Tuple

# ═════════════════════════════════════════════════════════════════════════════
# Métriques canoniques
# ═════════════════════════════════════════════════════════════════════════════
# Clés normalisées (metric_canonical_id). La table mappe les libellés FR/EN
# rencontrés dans la table de faits (financial_facts_table) et les extracteurs
# (Pappers, liasse, consolidated_ledger) vers une clé unique.
#
# Cohérence maison : les libellés canoniques FR existants (« Chiffre
# d'affaires », « Résultat net »…) restent la clé d'AFFICHAGE ; le
# metric_canonical_id est la clé d'IDENTITÉ (hash, rapprochement Christopher).

CANONICAL_METRICS = (
    "REVENUE", "EBITDA", "EBIT", "NET_INCOME", "GROSS_MARGIN",
    "EBITDA_MARGIN", "CASH", "GROSS_DEBT", "NET_DEBT", "FINANCIAL_DEBT",
    "EQUITY", "HEADCOUNT", "FREE_CASH_FLOW", "CAPACITY", "STOCKS",
    "OPERATING_INCOME",
)

# label (minuscule, sans accents) → metric_canonical_id.
# L'ordre importe : les libellés les plus spécifiques d'abord (« marge
# d'ebitda » avant « ebitda », « dette nette » avant « dette »).
_METRIC_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("marge d'ebitda", "EBITDA_MARGIN"),
    ("ebitda margin", "EBITDA_MARGIN"),
    ("marge brute", "GROSS_MARGIN"),
    ("gross margin", "GROSS_MARGIN"),
    ("free cash-flow", "FREE_CASH_FLOW"),
    ("free cash flow", "FREE_CASH_FLOW"),
    ("fcf", "FREE_CASH_FLOW"),
    ("chiffre d'affaires", "REVENUE"),
    ("chiffres d'affaires", "REVENUE"),
    ("revenue", "REVENUE"),
    ("turnover", "REVENUE"),
    ("ventes", "REVENUE"),
    ("ebitda", "EBITDA"),
    ("resultat d'exploitation", "OPERATING_INCOME"),
    ("operating income", "OPERATING_INCOME"),
    ("ebit", "EBIT"),
    ("resultat net", "NET_INCOME"),
    ("perte nette", "NET_INCOME"),
    ("net income", "NET_INCOME"),
    ("net loss", "NET_INCOME"),
    ("tresorerie", "CASH"),
    ("cash", "CASH"),
    ("dette nette", "NET_DEBT"),
    ("net debt", "NET_DEBT"),
    ("dette brute", "GROSS_DEBT"),
    ("gross debt", "GROSS_DEBT"),
    ("dettes financieres", "FINANCIAL_DEBT"),
    ("financial debt", "FINANCIAL_DEBT"),
    ("capitaux propres", "EQUITY"),
    ("equity", "EQUITY"),
    ("effectif", "HEADCOUNT"),
    ("headcount", "HEADCOUNT"),
    ("salaries", "HEADCOUNT"),
    ("employes", "HEADCOUNT"),
    ("employees", "HEADCOUNT"),
    ("capacite installee", "CAPACITY"),
    ("installed capacity", "CAPACITY"),
    ("stocks", "STOCKS"),
)


def _fold(s: str) -> str:
    """minuscule + sans accents + espaces normalisés (clé de matching)."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", s.strip().lower())


def canonical_metric_id(label: Optional[str]) -> str:
    """
    Mappe un libellé de fait (FR/EN, avec suffixe d'entité toléré :
    « Chiffre d'affaires Groupe (consolidé) ») vers son metric_canonical_id.

    Retourne "OTHER" si le libellé ne correspond à aucune métrique connue
    (faits d'identité, statuts, métadonnées…) — jamais d'exception.
    """
    folded = _fold(label or "")
    if not folded:
        return "OTHER"
    for pat, canon in _METRIC_PATTERNS:
        if pat in folded:
            return canon
    return "OTHER"


# ═════════════════════════════════════════════════════════════════════════════
# Normalisation valeur / unité / échelle (pour l'identité, pas pour le rendu)
# ═════════════════════════════════════════════════════════════════════════════

# « 2,4 M€ », « 235 M€ », « 220 124 567 € », « -557 K€ », « 1.5 Md£ »,
# « 2100 personnes », « 0,7% », « 6,7x », « 120 jours »
_NUM_RE = re.compile(r"[+\-]?\d{1,3}(?:[\s\u202F.,]\d{3})+(?:[.,]\d+)?|[+\-]?\d+(?:[.,]\d+)?")

_SCALE_MARKS: Tuple[Tuple[str, float, str], ...] = (
    ("md", 1e9, "Md"), ("bn", 1e9, "Md"), ("billion", 1e9, "Md"),
    ("m", 1e6, "M"), ("million", 1e6, "M"),
    ("k", 1e3, "k"), ("thousand", 1e3, "k"),
)

_CURRENCY_MARKS: Tuple[Tuple[str, str], ...] = (
    ("€", "EUR"), ("eur", "EUR"),
    ("£", "GBP"), ("gbp", "GBP"),
    ("$", "USD"), ("usd", "USD"),
    ("nok", "NOK"), ("chf", "CHF"),
)

_UNIT_MARKS: Tuple[Tuple[str, str], ...] = (
    ("personnes", "PERSONS"), ("personne", "PERSONS"),
    ("salaries", "PERSONS"), ("salarié", "PERSONS"), ("salariés", "PERSONS"),
    ("collaborateurs", "PERSONS"), ("collaborateur", "PERSONS"),
    ("employees", "PERSONS"), ("etp", "PERSONS"), ("fte", "PERSONS"),
    ("jours", "DAYS"), ("days", "DAYS"),
    ("%", "PCT"), ("x", "RATIO"),
)


def parse_value(raw: Optional[str]) -> Tuple[Optional[float], str, str, str]:
    """
    Décompose une valeur affichée en (normalized_value, unit, currency, scale).

      "2,4 M€"        → (2400000.0, "CUR", "EUR", "M")
      "235 M€"        → (235000000.0, "CUR", "EUR", "M")
      "2100 personnes"→ (2100.0, "PERSONS", "", "")
      "0,7%"          → (0.7, "PCT", "", "")
      "6,7x"          → (6.7, "RATIO", "", "")
      "n.d."          → (None, "", "", "")

    normalized_value est TOUJOURS ramené à l'unité de base (euros, personnes…)
    pour que « 235 M€ » et « 235 000 000 € » produisent la même identité —
    et pour que « 235 M€ » vs « 235 k€ » soit un VRAI écart (garde d'unité,
    Partie II §6).
    """
    text = (raw or "").strip()
    if not text:
        return (None, "", "", "")
    # v62.13.9.4.40 — SIGNE MOINS TYPOGRAPHIQUE. « –3 M€ », « −0,1 % » (tiret demi-cadratin,
    # signe moins Unicode) se lisaient POSITIFS : seul le trait d'union ASCII était un signe.
    # Collé au nombre (ou à sa devise), c'est un signe ; suivi d'une espace, c'est un tiret de
    # liste ou de séparation et il reste tel quel.
    text = re.sub(r"[\u2212\u2012\u2013\u2014\ufe63\uff0d](?=[£$€]?\d)", "-", text)
    folded = _fold(text)

    m = _NUM_RE.search(text)
    if not m:
        return (None, "", "", "")
    num_txt = m.group(0)

    # ── B.1.2 (audit gate B.2, P1) — la DEVISE est détectée AVANT le
    # nettoyage numérique : elle ancre la lecture des séparateurs.
    currency = ""
    for mark, code in _CURRENCY_MARKS:
        # B.1.3 — marks textuels (eur/gbp/usd/nok/chf) en WORD-BOUNDARY :
        # « collaborat·eur·s » ne doit jamais donner EUR (bug substring).
        # MAIS les formes POSTFIXÉES d'échelle de B.1.2 restent valides :
        # « NOKm », « CHFbn », « MNOK », « kNOK » — la frontière droite
        # accepte une lettre d'échelle (m/bn/k), la gauche un préfixe
        # d'échelle (M/k) collé au code.
        if mark.isalpha():
            if re.search(rf"(?<![a-z]){mark}(?![a-z])"
                         rf"|(?<![a-z]){mark}(?=(?:m|bn|k)\b)"
                         rf"|(?<![a-z])(?:m|k){mark}(?![a-z])",
                         folded):
                currency = code
                break
        elif mark in folded:
            currency = code
            break

    # ── Nettoyage des séparateurs (règles B.1.2, déterministes) ─────────────
    #   R1  espace / insécable entre groupes de 3 → milliers (« 2 383 »).
    #   R2  virgule ET point présents → le DERNIER séparateur est décimal,
    #       l'autre milliers (« 1,234.56 » et « 1.234,5 »).
    #   R3  un même séparateur ≥ 2 fois → milliers (« 220,124,567 »,
    #       « 220.124.567 »).
    #   R4  séparateur UNIQUE suivi d'exactement 3 chiffres : convention
    #       ancrée devise —
    #         · virgule + £/$ (GBP/USD) → milliers (« 2,383 M£ » = 2 383 M) ;
    #           virgule + € ou sans devise → décimale FR (« 2,383 M€ »).
    #         · point + € (EUR) → milliers EU (« 2.383 M€ » = 2 383 M) ;
    #           point + £/$ ou sans devise → décimal EN (« 2.383 M$ »).
    #   R5  séparateur unique + 1-2 chiffres → décimal, toujours
    #       (« 2,4 M€ », « 3.5 M$ »).
    #   Heuristique assumée et paramétrable — à ratifier au débrief, comme
    #   NA et le seuil devise relatif.
    cleaned = num_txt.replace("\u202F", " ")
    if re.search(r"\d[\s]\d{3}", cleaned):            # R1
        cleaned = cleaned.replace(" ", "")
    if "," in cleaned and "." in cleaned:              # R2
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif cleaned.count(",") >= 2:                      # R3 virgules
        cleaned = cleaned.replace(",", "")
    elif cleaned.count(".") >= 2:                      # R3 points
        cleaned = cleaned.replace(".", "")
    elif re.search(r",\d{3}$", cleaned):               # R4 virgule + 3 chiffres
        # NOK/CHF : rapports scandinaves et suisses publiés en convention EN
        # (« 2,383 NOKm » = 2 383 M NOK) — même lecture que GBP/USD.
        if currency in ("GBP", "USD", "NOK", "CHF"):
            cleaned = cleaned.replace(",", "")         # milliers anglo
        else:
            cleaned = cleaned.replace(",", ".")        # décimale FR
    elif re.search(r"\.\d{3}$", cleaned):              # R4 point + 3 chiffres
        if currency == "EUR":
            cleaned = cleaned.replace(".", "")         # milliers EU
        # sinon : décimal EN, rien à faire
    else:                                              # R5 et cas simples
        cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace(" ", "")
    try:
        value = float(cleaned)
    except Exception:
        return (None, "", "", "")
    # v62.13.9.4.40 — CONVENTION COMPTABLE : UNE VALEUR ENTRE PARENTHÈSES EST NÉGATIVE.
    # « (0.1%) », « £(3)m », « (15) » dans un état financier se lisent –0,1 %, –3 M£, –15.
    # Dossier réel du 21/09/2026 : une marge négative entre parenthèses lue positive, d'où
    # un écart publié faux de deux dixièmes de point — un chiffre faux sur une base confirmée
    # à la page. La règle vaut pour toute valeur dont le NOMBRE est entouré de parenthèses
    # (devise, échelle et % pouvant être dedans ou dehors) ; un signe moins explicite
    # garde la valeur négative, jamais une double négation.
    if value > 0 and re.search(r"\(\s*[£$€]?\s*" + re.escape(num_txt.strip()) + r"\s*(?:%|[kKmM]|bn|Md|M€|m)?\s*\)", text):
        value = -value

    # Unité non monétaire
    unit = ""
    for mark, code in _UNIT_MARKS:
        if mark == "x":
            # ratio : « 6,7x » — le x doit suivre le nombre, pas être une lettre de mot
            if re.search(r"\d\s*x\b", folded):
                unit = code
                break
        elif mark in folded:
            unit = code
            break

    # Échelle (M / k / Md) — cherchée entre le nombre et la devise/fin.
    scale = ""
    tail = _fold(text[m.end():])
    for mark, mult, label in _SCALE_MARKS:
        # « m€ », « m euros », « md£ », « k€ », « m » isolé en fin
        if re.match(rf"\s*{re.escape(mark)}(\b|€|£|\$|eur|gbp|usd|nok)", tail):
            value *= mult
            scale = label
            break
    if not scale:
        # B.1.2 — échelle POSTFIXÉE à la devise, convention des en-têtes de
        # tableaux financiers EN : « £m », « €m », « $m », « NOKm », « £bn ».
        # Le « m/bn/k » n'est lu comme échelle QUE collé à une marque de
        # devise — jamais un « m » nu (mètre, million ambigu).
        pm = re.match(
            r"\s*(?:€|£|\$|eur|gbp|usd|nok|chf)\s?(m|bn|k)\b", tail)
        if pm:
            suf = pm.group(1)
            value *= {"m": 1e6, "bn": 1e9, "k": 1e3}[suf]
            scale = {"m": "M", "bn": "Md", "k": "k"}[suf]

    if currency and not unit:
        unit = "CUR"

    return (value, unit, currency, scale)


# ═════════════════════════════════════════════════════════════════════════════
# Les identifiants
# ═════════════════════════════════════════════════════════════════════════════

def _h(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def stable_fact_key(
    *,
    metric_canonical_id: str,
    period: str = "",
    perimeter_entity: str = "",
    perimeter_level: str = "UNKNOWN",
    normalized_value: Optional[float] = None,
    unit: str = "",
    currency: str = "",
    scale: str = "",
) -> str:
    """
    Identité STABLE du fait — indépendante du run et de la source.
    Deux runs du même cas produisent la MÊME clé (propriété E1 testée).
    """
    val = "NA" if normalized_value is None else f"{normalized_value:.6g}"
    payload = "|".join([
        metric_canonical_id or "OTHER",
        _fold(period),
        _fold(perimeter_entity),
        (perimeter_level or "UNKNOWN").upper(),
        val,
        unit or "",
        # B.1.2 (audit gate B.2, à ratifier) — la DEVISE entre dans la clé :
        # 100 M EUR et 100 M GBP ne sont pas la même unité économique ; sans
        # elle, Christopher rapprocherait comme « même fait » deux valeurs
        # incommensurables. Compat assumée MAINTENANT, avant golden corpus
        # et gel v18.0 (aucune clé historisée à ce jour).
        (currency or "").upper(),
        scale or "",
    ])
    return "F-" + _h(payload)


def fact_instance_id(stable_key: str, source_ref: str = "B1_UNKNOWN") -> str:
    """
    Instance = (fait stable) × (référence de source).
    source_ref B.1 provisoire : registry_resolution_id | evidence_locator_hash
    | brief_ref | B1_UNKNOWN — le source_id réel arrive en B.2.
    """
    return "FI-" + _h(f"{stable_key}|{source_ref or 'B1_UNKNOWN'}")


def evidence_locator_hash(source_doc: Optional[str], source_page: Optional[int],
                          source_section: Optional[str]) -> str:
    """source_ref provisoire quand le fait porte un locator doc/page/section."""
    if not (source_doc or source_page or source_section):
        return ""
    return "EL-" + _h(f"{_fold(source_doc or '')}|{source_page or ''}|{_fold(source_section or '')}")


def make_run_id(now: Optional[datetime] = None) -> str:
    """Identifiant de run horodaté (UTC) — unique par run, absent des fact ids."""
    dt = now or datetime.now(timezone.utc)
    return "RUN-" + dt.strftime("%Y%m%dT%H%M%SZ") + "-" + _h(dt.isoformat())[:6]


def provisional_source_ref(
    *,
    registry_resolution_id: str = "",
    source_doc: Optional[str] = None,
    source_page: Optional[int] = None,
    source_section: Optional[str] = None,
    is_brief: bool = False,
) -> str:
    """
    Résolution B.1 du source_ref (Partie II §4) — dans l'ordre de préférence :
    registre > locator de pièce > brief > B1_UNKNOWN.
    """
    if registry_resolution_id:
        return f"REG-{registry_resolution_id}"
    el = evidence_locator_hash(source_doc, source_page, source_section)
    if el:
        return el
    if is_brief:
        return "brief_ref"
    return "B1_UNKNOWN"


# ═════════════════════════════════════════════════════════════════════════════
# B.1.1 — Extraction de période CENTRALISÉE (règle prudente unique)
# ═════════════════════════════════════════════════════════════════════════════
# Audit ChatGPT (gate B.2, P1) : « une année dans value ou label ne doit être
# acceptée que si elle est explicitement marquée ». Un nombre NU dans une
# valeur (« Effectif : 2050 personnes ») ne doit JAMAIS devenir une période —
# sinon deux effectifs comparables deviennent artificiellement non comparables
# et un conflit disparaît. Cette fonction est LA règle ; proof_layer et
# fact_conflict délèguent ici (zéro duplication de regex).
#
# Marquages acceptés (FR/EN) :
#   · FY2024 / FY 2024 / FY24            → "FY2024" (normalisé 4 chiffres)
#   · exercice 2024 / fiscal year 2024   → "2024"
#   · (2024) / [2024]                    → "2024"
#   · au 31/12/2024 / as of 12/31/2024   → "2024"
# Tout le reste — y compris « 2 050 », « 2024 personnes », « page 2023 » —
# est ignoré.

_MARKED_PERIOD_RE = re.compile(
    r"\bFY\s?((?:19|20)\d{2}|\d{2})\b"                       # FY2024 / FY24
    r"|\b(?:exercice|fiscal\s+year)\s+((?:19|20)\d{2})\b"     # exercice 2024
    r"|[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]"                    # (2024) / [2024]
    r"|\b(?:au|as\s+of)\s+\d{1,2}/\d{1,2}/((?:19|20)\d{2})\b"  # au 31/12/2024
    # B.1.2 (audit §6, préemption terrain) — dates LONGUES marquées, formes
    # réelles des rapports : « exercice clos le 31 décembre 2024 »,
    # « au 31 décembre 2024 », « year ended 31 March 2024 » (dossier anglophone coté),
    # « as at 31 December 2023 ». Toujours des MARQUEURS explicites — une
    # année nue (« CA 2023 ») reste refusée, conformément à l'arbitrage B.1.1.
    r"|\b(?:exercice\s+clos\s+le\s+|au\s+)\d{1,2}(?:er)?\s+"
    r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|"
    r"septembre|octobre|novembre|d[ée]cembre)\s+((?:19|20)\d{2})\b"
    r"|\b(?:year\s+ended|as\s+at|as\s+of)\s+\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def extract_marked_period(text: str) -> str:
    """
    Période depuis un texte libre, UNIQUEMENT si l'année est marquée.
    Retourne "FYxxxx" pour un marquage FY, "xxxx" sinon, "" si rien de marqué.
    Une année nue n'est jamais retenue (verrou anti « 2050 personnes »).
    """
    m = _MARKED_PERIOD_RE.search(text or "")
    if not m:
        return ""
    fy = m.group(1)
    if fy:
        y = fy if len(fy) == 4 else ("20" + fy)  # FY24 → FY2024
        return f"FY{y}"
    return next((g for g in m.groups()[1:] if g), "")
