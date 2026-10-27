"""v62.13.9.4.50 — DATE DE CLÔTURE de l'exercice, lue dans les pièces (recette du 01/10/2026).

Sans registre interrogé (pas de contact SEC, société hors Pappers), les faits n'avaient que l'étiquette « FY2025 » :
la règle du dernier réalisé daté retombait sur le 31 décembre et ne pouvait pas dire « dernier publié » d'un exercice
clos le 31 août 2025. La date est lue sur les formules de couverture des comptes (« fiscal year ended August 31, 2025 »,
« for the year ended 31 March 2025 », « 52 weeks ended 28 March 2026 », « exercice clos le 31 décembre 2025 »).
Aucune date n'est inventée : sans formule reconnue, rien n'est renvoyé.
"""
from __future__ import annotations

import re
from datetime import date

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], start=1)}
_MONTHS.update({m: i for i, m in enumerate(
    ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
     "décembre"], start=1)})
_MONTHS.update({"fevrier": 2, "aout": 8, "decembre": 12})
_MN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_CUE_EN = r"(?:fiscal\s+)?(?:year|years|period|\d{2}\s+weeks)\s+ended"
_CUE_FR = r"exercice\s+(?:clos|clôturé|cloturé|arrêté)\s+(?:le|au)"
_PATTERNS = (
    re.compile(rf"(?i)\b{_CUE_EN}\s+({_MN})\s+(\d{{1,2}}),?\s+((?:19|20)\d{{2}})"),          # August 31, 2025
    re.compile(rf"(?i)\b{_CUE_EN}\s+(\d{{1,2}})\s+({_MN})\s+((?:19|20)\d{{2}})"),            # 31 March 2025
    re.compile(rf"(?i)\b{_CUE_FR}\s+(\d{{1,2}})(?:er)?\s+({_MN})\s+((?:19|20)\d{{2}})"),     # 31 décembre 2025
    re.compile(rf"(?i)\b{_CUE_FR}\s+(\d{{1,2}})/(\d{{1,2}})/((?:19|20)\d{{2}})"),             # 31/12/2025
)


def _mk(y: int, m: int, d: int):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def detect_fiscal_year_end(text: str, analysis_date: str = "") -> str:
    """Date ISO de la clôture la plus récente citée par une formule de couverture (jamais après la date d'analyse)."""
    s = str(text or "")
    if not s:
        return ""
    try:
        limit = date.fromisoformat(str(analysis_date)[:10]) if analysis_date else date.today()
    except ValueError:
        limit = date.today()
    found = []
    for i, rx in enumerate(_PATTERNS):
        for m in rx.finditer(s[:400000]):
            g = m.groups()
            if i == 0:
                d0 = _mk(int(g[2]), _MONTHS[g[0].lower()], int(g[1]))
            elif i in (1, 2):
                d0 = _mk(int(g[2]), _MONTHS[g[1].lower()], int(g[0]))
            else:
                d0 = _mk(int(g[2]), int(g[1]), int(g[0]))
            if d0 and d0 <= limit:
                found.append(d0)
    return max(found).isoformat() if found else ""


# ── 9.4.51 — EFFECTIF lu dans les pièces (contre-recette du 03/10/2026 : les trois decks portaient « Non communiqué »
# alors que le 10-K fourni donne 714 salariés). Formules de rapport annuel uniquement ; aucune estimation.
_HC_PATTERNS = (
    re.compile(r"(?i)\b(?:employed|had|have|has)\s+(?:approximately|about|around|some)?\s*(\d{1,3}(?:[,\s]\d{3})*|\d+)\s+"
               r"(?:full[- ]time\s+)?(?:people|employees|persons|staff)\b"),
    re.compile(r"(?i)\b(\d{1,3}(?:[,\s]\d{3})*|\d+)\s+(?:full[- ]time\s+)?employees\s+(?:worldwide|globally|in\s+total)\b"),
    re.compile(r"(?i)\beffectifs?\s+(?:total\s+)?(?:de|:)\s*(\d{1,3}(?:[\s\u202f]\d{3})*|\d+)\s+(?:salari[ée]s|collaborateurs|personnes)\b"),
    # 9.4.52 — recette du 05/10 : l'effectif du 10-K n'était pas lu. Formules plus larges, toujours ancrées sur un
    # vocabulaire d'effectif (jamais un nombre isolé)
    re.compile(r"(?i)\b(?:employed|employs|employing|workforce\s+of|headcount\s+of)\s+(?:approximately\s+|about\s+)?"
               r"(\d{1,3}(?:[,\s]\d{3})*|\d+)\b(?:\s+\S+){0,3}?\s+(?:people|employees|individuals|persons|staff)\b"),
    re.compile(r"(?i)\b(\d{1,3}(?:[,\s]\d{3})*|\d+)\s+(?:full[- ]time\s+|total\s+|active\s+)?(?:employees|associates)\b"
               r"(?=[^.]{0,80}\b(?:worldwide|globally|of\s+whom|located|based|as\s+of))"),
    re.compile(r"(?i)\b(?:number\s+of\s+employees|employees|headcount|effectifs?(?:\s+total)?)\s*[:=]\s*(\d{1,3}(?:[,\s\u202f]\d{3})*|\d+)\b"),
    # 9.4.53 — forme possessive d'un rapport annuel (« our N employees spread across… »), recette du 05/10/2026
    re.compile(r"(?i)\b(?:our|its|their|nos|ses|leurs)\s+(\d{1,3}(?:[,\s\u202f]\d{3})*|\d+)\s+(?:full[- ]time\s+)?"
               r"(?:employees|associates|salari[ée]s|collaborateurs)\b"),
    # 9.4.55 — mise en page en colonnes : « our » et « 714 employees » ne sont pas toujours contigus dans le texte extrait ;
    # l'ancrage se fait sur ce qui SUIT le nombre (« spread across », « located », « based », « worldwide »)
    re.compile(r"(?i)\b(\d{1,3}(?:[,\s\u202f]\d{3})*|\d{2,6})\s+(?:full[- ]time\s+)?(?:employees|associates)\s+"
               r"(?:spread|across|located|based|worldwide|globally|around\s+the\s+world|in\s+\d+\s+countries)\b"),
)


def detect_headcount(text: str) -> str:
    """Effectif cité par une formule de rapport annuel (« the Company employed 714 people ») ; "" si aucune. Le plus
    fréquent l'emporte ; à égalité, le premier cité."""
    from collections import Counter
    s = str(text or "")[:600000]
    found = []
    for rx in _HC_PATTERNS:
        for m in rx.finditer(s):
            n = re.sub(r"[,\s\u202f]", "", m.group(1))
            if n.isdigit() and 1 <= int(n) <= 5_000_000:
                found.append(n)
    if not found:
        return ""
    c = Counter(found)
    best = max(c.values())
    return next(n for n in found if c[n] == best)
