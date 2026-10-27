"""
patches/temporal_gate.py — v17.1-B2 / B2.1 (ticket B-06)

Empêche qu'un événement FUTUR (postérieur à la date du run) soit présenté comme
acquis. Bug observé sur le run Lhyfe : « coté Euronext Growth depuis juillet 2026 »
dans un run daté du 5 juin 2026.

B2.1-03 — couverture élargie : « depuis [le] [JJ] mois AAAA », « depuis MM/AAAA »,
et variantes anglaises « since / listed since / effective from / as of <date> ».
"""
from __future__ import annotations

import re
import calendar
from datetime import date
from typing import List, Tuple

_MONTHS = {
    # FR
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # EN
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    # abréviations usuelles FR / EN (avec ou sans point)
    "janv": 1, "janv.": 1, "jan": 1, "jan.": 1,
    "févr": 2, "févr.": 2, "fevr": 2, "fevr.": 2, "feb": 2, "feb.": 2,
    "mar": 3, "mar.": 3,
    "avr": 4, "avr.": 4, "apr": 4, "apr.": 4,
    "jun": 6, "jun.": 6,
    "juil": 7, "juil.": 7, "jul": 7, "jul.": 7,
    "aoû": 8, "aoû.": 8, "aug": 8, "aug.": 8,
    "sept": 9, "sept.": 9, "sep": 9, "sep.": 9,
    "oct.": 10, "nov.": 11, "déc": 12, "déc.": 12,
    "dec": 12, "dec.": 12,
}
_MONTHS_RE = "|".join(re.escape(k) for k in sorted(_MONTHS.keys(), key=len, reverse=True))

# Déclencheur « état acquis depuis une date » — FR + EN.
_TRIGGER = r"(?:depuis(?:\s+le)?|listed\s+since|since|effective\s+from|as\s+of)"

_FUTURE_RE = re.compile(
    r"(?P<trig>" + _TRIGGER + r")\s+"
    r"(?:(?P<day>\d{1,2})\s+)?"
    r"(?:(?P<month>" + _MONTHS_RE + r")\s+|(?P<mm>\d{1,2})\s*/\s*)?"
    r"(?P<year>20\d\d)\b",
    re.IGNORECASE,
)


def _parse_run_date(run_date):
    """Gate 12 - une autorite MALFORMEE rend None (aucun jugement),
    plus jamais l horloge systeme (chemin de verite zero-horloge)."""
    if isinstance(run_date, date):
        return run_date
    try:
        return date.fromisoformat(str(run_date)[:10])
    except Exception:
        return None


def neutralize_future_as_past(text: str, run_date) -> Tuple[str, int, List[str]]:
    """Réécrit les « <depuis/since…> <date future> » en formulation prudente.
    Retourne (texte_corrigé, n_corrections, échantillons)."""
    if not text:
        return text, 0, []
    rd = _parse_run_date(run_date)
    if rd is None:
        # Gate 12 - sans autorite lisible, aucun jugement.
        return text, 0, []
    samples: List[str] = []

    def _repl(m: re.Match) -> str:
        year = int(m.group("year"))
        month_name = (m.group("month") or "").lower()
        mm = m.group("mm")
        if month_name:
            month = _MONTHS.get(month_name, 1)
            when = f"{m.group('month')} {year}"
        elif mm:
            month = max(1, min(12, int(mm)))
            when = f"{int(mm):02d}/{year}"
        else:
            month = 1            # année seule → début d'année (prudent pour le futur)
            when = str(year)
        try:
            ref = date(year, month, 1)
        except Exception:
            return m.group(0)
        if ref <= rd:
            return m.group(0)    # passé / présent → inchangé
        samples.append(m.group(0))
        return (f"à compter de {when} (prévu, sous réserve — postérieur à la date "
                f"d'analyse {rd.isoformat()})")

    new_text, _ = _FUTURE_RE.subn(_repl, text)
    return new_text, len(samples), samples


# ── M6-A0 (A3) — actions à échéance PASSÉE ────────────────────────────────────
# Bug dossier anglophone coté : run du 22/06/2026, mais des ACTIONS à lancer datées « T1 2025 »,
# « Jan-Mars 2025 », « 2025-04 ». Le gate existant ne couvrait que l'inverse
# (date future présentée comme acquise). Ici on cible les CHAMPS D'ACTION
# structurés (échéance/délai), JAMAIS les constats historiques (FY25, « clos le
# 29 mars 2025 » restent légitimes). Distinction analyste : un constat décrit le
# passé ; une action à lancer doit être ≥ date du run.

_SEASON_RE = re.compile(
    r"\b(printemps|été|ete|automne|hiver|spring|summer|autumn|fall|winter)\s+(20\d\d)\b",
    re.IGNORECASE)
_Q_SUFFIX_RE = re.compile(
    r"\b[TQ]([1-4])\s*[-/ \'’]?\s*(?:FY\s*)?(\d{2}|20\d\d)\b", re.IGNORECASE)
_Q_PREFIX_RE = re.compile(
    r"\bFY\s*(\d{2}|20\d\d)\s*[-/ ]?\s*[TQ]([1-4])\b", re.IGNORECASE)
_H_SUFFIX_RE = re.compile(
    r"\b[SH]([12])\s*[-/ \'’]?\s*(?:FY\s*)?(\d{2}|20\d\d)\b", re.IGNORECASE)
_H_PREFIX_RE = re.compile(
    r"\bFY\s*(\d{2}|20\d\d)\s*[-/ ]?\s*[SH]([12])\b", re.IGNORECASE)
# gate 5, intégration Claude — en position année-première, une année à deux
# chiffres n'est plausible que dans la décennie courante (« page 12 T2 »
# fabriquait l'échéance passée 30/06/2012 sur du bruit documentaire).
_Q_YEAR_FIRST_RE = re.compile(
    r"(?<![\d\-–—])\b(2[0-9]|20\d\d)\s*[-/ ]?\s*[TQ]([1-4])\b", re.IGNORECASE)
_H_YEAR_FIRST_RE = re.compile(
    r"(?<![\d\-–—])\b(2[0-9]|20\d\d)\s*[-/ ]?\s*[SH]([12])\b", re.IGNORECASE)
_Q_COMPACT_RE = re.compile(
    r"\b([1-4])Q(?:FY)?['’]?([0-9]{2}|20\d\d)\b", re.IGNORECASE)
_H_COMPACT_RE = re.compile(
    r"\b([12])H(?:FY)?['’]?([0-9]{2}|20\d\d)\b", re.IGNORECASE)
_HALF_TEXT_RE = re.compile(
    r"\b(?:first\s+half(?:\s+of)?|first\s+semester(?:\s+of)?|premier\s+semestre|1er\s+semestre)\s+(20\d\d)\b|"
    r"\b(?:second\s+half(?:\s+of)?|second\s+semester(?:\s+of)?|deuxi[èe]me\s+semestre|second\s+semestre)\s+(20\d\d)\b",
    re.IGNORECASE)
_QUARTER_TEXT_RE = re.compile(
    r"\b(first|1st|second|2nd|third|3rd|fourth|4th|premier|1er|deuxi[èe]me|2e|troisi[èe]me|3e|quatri[èe]me|4e)"
    r"\s+(?:quarter|trimestre)(?:\s+of|\s+de)?\s+(20\d\d)\b", re.IGNORECASE)
_QTR_TEXT_RE = re.compile(
    r"\b(?:qtr|quarter|trimestre)\s*([1-4])(?:\s+of|\s+de)?\s+(20\d\d)\b|"
    r"\b([1-4])(?:st|nd|rd|th)?\s+qtr(?:\s+of)?\s+(20\d\d)\b",
    re.IGNORECASE)
_Q_OF_YEAR_RE = re.compile(
    r"\b([TQ])([1-4])\s+(?:of|de)\s+(20\d\d)\b", re.IGNORECASE)
_H_OF_YEAR_RE = re.compile(
    r"\b([SH])([12])\s+(?:of|de)\s+(20\d\d)\b", re.IGNORECASE)
_YEAR_PHASE_RE = re.compile(
    r"\b(early|mid|late|d[ée]but|mi|fin)[-\s]+(?:de\s+)?(20\d\d)\b", re.IGNORECASE)
_MONTH_PHASE_RE = re.compile(
    r"\b(early|mid|late|d[ée]but|mi|fin)[-\s]+(?:de\s+)?(" + _MONTHS_RE + r")\s+(20\d\d)\b",
    re.IGNORECASE)
_MON_YEAR_RE = re.compile(r"\b(" + _MONTHS_RE + r")\s+(20\d\d)\b", re.IGNORECASE)
_DAY_MON_YEAR_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTHS_RE + r")\s*,?\s*(20\d\d)\b",
    re.IGNORECASE)
_MON_DAY_YEAR_RE = re.compile(
    r"\b(" + _MONTHS_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(20\d\d)\b",
    re.IGNORECASE)
_YEAR_MON_DAY_RE = re.compile(
    r"\b(20\d\d)\s+(" + _MONTHS_RE + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE)
_ISO_RE = re.compile(r"(?<!\d)(20\d\d)-(\d{2})-(\d{2})(?!\d)")
# Dates exactes usuelles complémentaires. Elles sont séparées des dates
# ambiguës D/M/Y pour préserver le jour lorsqu'il est explicitement fourni.
_YMD_SLASH_DOT_RE = re.compile(
    r"\b(20\d\d)\s*[/\.]\s*(\d{1,2})\s*[/\.]\s*(\d{1,2})\b")
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(20\d\d)\b")
_NUMERIC_DATE_2Y_RE = re.compile(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{2})\b")
_DMY_DOT_RE = re.compile(
    r"(?<![\w.])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d\d)\b")
_DMY_DOT_2Y_RE = re.compile(
    r"(?<![\w.])(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{2})\b")
_YEAR_MONTH_RE = re.compile(
    r"(?<![\w.])(20\d\d)\s*[-/\.]\s*(\d{1,2})\b")
_MONTH_YEAR_RE = re.compile(
    r"(?<![\w.])(\d{1,2})\s*[-/\.]\s*(20\d\d)\b")
_MONTH_YEAR_2Y_RE = re.compile(
    r"(?<![\w.])(\d{1,2})\s*[-/\.]\s*(\d{2})\b")
_WEEK_LIKE_RE = re.compile(r"\b(?:week|semaine|W)\s*[- ]?\d{1,2}(?:\s+20\d\d)?\b", re.IGNORECASE)
_VERSION_LIKE_RE = re.compile(r"\b(?:v(?:ersion)?|release|build)\s*[:#-]?\s*\d{1,4}(?:[./-]\d{1,4}){1,3}\b", re.IGNORECASE)
# Gate 6 — références normatives et pagination ne sont jamais des échéances.
_STANDARD_LIKE_RE = re.compile(
    r"\b(?:ISO(?:\s*/\s*IEC)?|IEC|NF(?:\s+EN)?|EN|DIN|BS|ASTM|IFRS|IAS|"
    r"RFC|IEEE|NIST|CIS|COBIT|CMMI|SOC(?:\s+2(?:\s+TYPE\s+II)?)?)"
    r"\s*[-/]?\s*[A-Z]?\s*\d{1,5}"
    r"(?:\s*[-:]\s*\d{1,5})?"
    r"(?:\s*[:\-]\s*(?:19|20)\d{2}|"
    r"\s*\(\s*(?:19|20)\d{2}\s*\)|"
    r"\s*,?\s*(?:19|20)\d{2}\s*(?:edition|ed\.?)?)?\b",
    re.IGNORECASE)
_DOC_REF_MARKER_RE = re.compile(
    r"(?:\b(?:pages?|annexes?|annex|appendices?|appendix|sections?|"
    r"chapters?|chapitres?|tables?|tableaux?|figures?|exhibits?|slides?|"
    r"diapositives?|paragraphs?|paragraphes?|articles?|schedules?|"
    r"clauses?)\b|\bart\.?|\bpp?\.?|\bparas?\.?|§)",
    re.IGNORECASE)
_PAGE_PERIOD_RE = re.compile(
    r"(?:\b(?:pages?|annexes?|annex|appendices?|appendix|sections?|"
    r"chapters?|chapitres?|tables?|tableaux?|figures?|exhibits?|slides?|"
    r"diapositives?|paragraphs?|paragraphes?|articles?|schedules?|"
    r"clauses?)\b|\bart\.?|\bpp?\.?|\bparas?\.?|§)\s*"
    r"\d{1,3}(?:\s*(?:[-–—]|to|à|and|et|,|/)\s*\d{1,3})*"
    r"(?:\s*(?:for|covering|sur|pour)\s*)?\s*[,;:.)\-–—]?\s*"
    r"(?:[TQSH][1-4]|[12][QH])"
    r"(?:\s*(?:FY\s*)?(?:\d{2}|20\d{2}))?\b", re.IGNORECASE)
_DOC_REF_LOCAL_RE = re.compile(
    r"(?:\b(?:pages?|annexes?|annex|appendices?|appendix|sections?|"
    r"chapters?|chapitres?|tables?|tableaux?|figures?|exhibits?|slides?|"
    r"diapositives?|paragraphs?|paragraphes?|articles?|schedules?|"
    r"clauses?)\b|\bart\.?|\bpp?\.?|\bparas?\.?|§)\s*"
    r"\d{1,3}(?:\s*(?:[-–—]|to|à|and|et|,|/)\s*\d{1,3})*"
    r"(?:\s*(?:for|covering|sur|pour))?\s*[,;:.)\-–—]?\s*$",
    re.IGNORECASE)
_DEADLINE_LOCAL_RE = re.compile(
    r"\b(?:deadline|due|échéance|echeance|target|objective|objectif|milestone|"
    r"jalon|planned\s+for|scheduled\s+for|cibl[ée]e?|before|by|avant|"
    r"d['’]ici|au\s+plus\s+tard|end\s+of|fin\s+de)\b",
    re.IGNORECASE)
_YEAR_RANGE_PERIOD_RE = re.compile(
    r"\b(?:[TQSH][1-4]\s*(?:20)?\d{2}\s*/\s*(?:\d{2}|20\d{2})|"
    r"(?:20)?\d{2}\s*/\s*(?:\d{2}|20\d{2})\s*[TQSH][1-4])\b",
    re.IGNORECASE)
_FY_RANGE_PREFIX_Q_RE = re.compile(
    r"\bFY\s*(\d{2}|20\d{2})\s*/\s*(\d{2}|20\d{2})\s*[TQ]([1-4])\b", re.IGNORECASE)
_Q_FY_RANGE_RE = re.compile(
    r"\b[TQ]([1-4])\s*FY\s*(\d{2}|20\d{2})\s*/\s*(\d{2}|20\d{2})\b", re.IGNORECASE)
_FY_RANGE_PREFIX_H_RE = re.compile(
    r"\bFY\s*(\d{2}|20\d{2})\s*/\s*(\d{2}|20\d{2})\s*[SH]([12])\b", re.IGNORECASE)
_H_FY_RANGE_RE = re.compile(
    r"\b[SH]([12])\s*FY\s*(\d{2}|20\d{2})\s*/\s*(\d{2}|20\d{2})\b", re.IGNORECASE)
_FY_RANGE_LIKE_RE = re.compile(
    r"\b(?:FY\s*(?:\d{2}|20\d{2})\s*/\s*(?:\d{2}|20\d{2})\s*[TQSH][1-4]|"
    r"[TQSH][1-4]\s*FY\s*(?:\d{2}|20\d{2})\s*/\s*(?:\d{2}|20\d{2}))\b",
    re.IGNORECASE)
_MON_HYPHEN_YEAR_RE = re.compile(
    r"\b(" + _MONTHS_RE + r")\s*[-/]\s*(20\d\d)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(20\d\d)\b")


def parse_deadline(text: str):
    """Extrait une échéance sans inventer ni déplacer une date.

    Les dates exactes gardent leur jour ; une date structurée mais invalide
    rend ``None`` et ne retombe jamais sur la fin de son mois/année. Les formes
    FY, année→trimestre, compactes (1Q26/1H26), années à deux chiffres et
    périodes early/mid/late usuelles sont reconnues.
    """
    if not text:
        return None
    t = str(text)
    best = None
    exact_spans = []
    invalid_spans = []
    blocked_spans = []
    phase_spans = []

    # Les références normatives et les mentions de pagination ressemblant à
    # des périodes sont protégées avant toute extraction.
    blocked_spans.extend(m.span() for m in _STANDARD_LIKE_RE.finditer(t))
    blocked_spans.extend(m.span() for m in _PAGE_PERIOD_RE.finditer(t))
    # Un FY chevauchant (26/27) exige le calendrier fiscal de l'entité ; sans
    # cette métadonnée, None est plus honnête qu'une date calendaire inventée.
    blocked_spans.extend(m.span() for m in _FY_RANGE_LIKE_RE.finditer(t))
    blocked_spans.extend(m.span() for m in _YEAR_RANGE_PERIOD_RE.finditer(t))

    def _inside(spans, m):
        return any(a <= m.start() and m.end() <= b for a, b in spans)

    def _keep(d):
        nonlocal best
        if d and (best is None or d > best):
            best = d

    def _year(raw):
        y = int(raw)
        return 2000 + y if y < 100 else y

    def _version_context(start):
        prefix = t[max(0, start - 20):start]
        return bool(re.search(r"(?:\bv(?:ersion)?|\brelease|\bbuild)\s*[:#-]?\s*$", prefix, re.I))

    def _doc_ref_context(start):
        """True si la période/date est localement portée par une citation.

        La référence documentaire la plus proche gagne, sauf si un marqueur
        explicite d'échéance apparaît après elle (« page 27 ; deadline Q1
        2026 »). Cette défense complète le blocage par span et couvre les
        variantes plurielles/ranges sans transformer une pagination en jalon.
        """
        prefix = t[max(0, start - 110):start]
        doc_matches = list(_DOC_REF_LOCAL_RE.finditer(prefix))
        if not doc_matches:
            return False
        doc_end = max(m.end() for m in doc_matches)
        deadline_end = max((m.end() for m in _DEADLINE_LOCAL_RE.finditer(prefix)), default=-1)
        return doc_end > deadline_end

    def _exact(m, year, month, day, *, version_sensitive=False):
        if _inside(blocked_spans, m):
            return
        if _doc_ref_context(m.start()):
            blocked_spans.append(m.span()); return
        if version_sensitive and _version_context(m.start()):
            blocked_spans.append(m.span()); return
        try:
            _keep(date(int(year), int(month), int(day)))
            exact_spans.append(m.span())
        except Exception:
            invalid_spans.append(m.span())

    for m in _ISO_RE.finditer(t):
        _exact(m, m.group(1), m.group(2), m.group(3), version_sensitive=True)
    for m in _YMD_SLASH_DOT_RE.finditer(t):
        _exact(m, m.group(1), m.group(2), m.group(3), version_sensitive=True)
    for m in _DMY_DOT_RE.finditer(t):
        _exact(m, m.group(3), m.group(2), m.group(1), version_sensitive=True)
    for m in _DMY_DOT_2Y_RE.finditer(t):
        _exact(m, _year(m.group(3)), m.group(2), m.group(1), version_sensitive=True)
    for rex, y2 in ((_NUMERIC_DATE_RE, False), (_NUMERIC_DATE_2Y_RE, True)):
        for m in rex.finditer(t):
            a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
            if a > 12 and b <= 12:
                day, month = a, b
            elif b > 12 and a <= 12:
                month, day = a, b
            else:
                day, month = a, b  # convention D/M/Y
            _exact(m, y, month, day)
    for m in _DAY_MON_YEAR_RE.finditer(t):
        _exact(m, m.group(3), _MONTHS[m.group(2).lower()], m.group(1))
    for m in _MON_DAY_YEAR_RE.finditer(t):
        _exact(m, m.group(3), _MONTHS[m.group(1).lower()], m.group(2))
    for m in _YEAR_MON_DAY_RE.finditer(t):
        _exact(m, m.group(1), _MONTHS[m.group(2).lower()], m.group(3))

    # Les exercices fiscaux chevauchants sont placés dans blocked_spans
    # ci-dessus : sans calendrier fiscal explicite, aucune date n'est inventée.

    # Périodes lexicales à granularité connue.
    for m in _MONTH_PHASE_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        phase_spans.append(m.span())
        phase, mon, year = m.group(1).lower(), _MONTHS[m.group(2).lower()], int(m.group(3))
        last = calendar.monthrange(year, mon)[1]
        day = 10 if phase in ("early", "début") else 15 if phase in ("mid", "mi") else last
        _keep(date(year, mon, day))
    for m in _YEAR_PHASE_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        phase_spans.append(m.span())
        phase, year = m.group(1).lower(), int(m.group(2))
        if phase in ("early", "début"):
            _keep(date(year, 3, 31))
        elif phase in ("mid", "mi"):
            _keep(date(year, 6, 30))
        else:
            _keep(date(year, 12, 31))
    for m in _HALF_TEXT_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        if m.group(1):
            _keep(date(int(m.group(1)), 6, 30))
        elif m.group(2):
            _keep(date(int(m.group(2)), 12, 31))
    _qmap = {
        "first": 1, "1st": 1, "premier": 1, "1er": 1,
        "second": 2, "2nd": 2, "deuxième": 2, "deuxieme": 2, "2e": 2,
        "third": 3, "3rd": 3, "troisième": 3, "troisieme": 3, "3e": 3,
        "fourth": 4, "4th": 4, "quatrième": 4, "quatrieme": 4, "4e": 4,
    }
    for m in _QUARTER_TEXT_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        q = _qmap.get(m.group(1).lower())
        if q:
            month = q * 3
            year = int(m.group(2))
            _keep(date(year, month, calendar.monthrange(year, month)[1]))
    for m in _QTR_TEXT_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        q = int(m.group(1) or m.group(3))
        year = int(m.group(2) or m.group(4))
        month = q * 3
        _keep(date(year, month, calendar.monthrange(year, month)[1]))
    for m in _Q_OF_YEAR_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        q, year = int(m.group(2)), int(m.group(3))
        month = q * 3
        _keep(date(year, month, calendar.monthrange(year, month)[1]))
    for m in _H_OF_YEAR_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        half, year = int(m.group(2)), int(m.group(3))
        month = 6 if half == 1 else 12
        _keep(date(year, month, calendar.monthrange(year, month)[1]))

    for m in _SEASON_RE.finditer(t):
        if _doc_ref_context(m.start()):
            continue
        season = m.group(1).lower(); year = int(m.group(2))
        start_map = {"printemps": (3, 20), "spring": (3, 20),
                     "été": (6, 21), "ete": (6, 21), "summer": (6, 21),
                     "automne": (9, 22), "autumn": (9, 22), "fall": (9, 22),
                     "hiver": (12, 21), "winter": (12, 21)}
        end_map = {"printemps": (6, 20), "spring": (6, 20),
                   "été": (9, 21), "ete": (9, 21), "summer": (9, 21),
                   "automne": (12, 20), "autumn": (12, 20), "fall": (12, 20),
                   "hiver": (3, 20), "winter": (3, 20)}
        prefix = t[max(0, m.start() - 24):m.start()].lower()
        before = bool(re.search(
            r"(?:\bavant\b|\bbefore\b|\bby\b|\bd['’]ici\b)\s*"
            r"(?:le\s+|la\s+|l['’]\s*|the\s+)?$", prefix))
        mo, dd = (start_map if before else end_map).get(season, (12, 31))
        yy = year + 1 if (not before and mo == 3) else year
        _keep(date(yy, mo, dd))

    protected_pre = blocked_spans + phase_spans
    quarters = []
    for m in _Q_SUFFIX_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            quarters.append((int(m.group(1)), _year(m.group(2))))
    for m in _Q_PREFIX_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            quarters.append((int(m.group(2)), _year(m.group(1))))
    for m in _Q_YEAR_FIRST_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            quarters.append((int(m.group(2)), _year(m.group(1))))
    for m in _Q_COMPACT_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            quarters.append((int(m.group(1)), _year(m.group(2))))
    for q, year in quarters:
        month = q * 3
        _keep(date(year, month, calendar.monthrange(year, month)[1]))

    halves = []
    for m in _H_SUFFIX_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            halves.append((int(m.group(1)), _year(m.group(2))))
    for m in _H_PREFIX_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            halves.append((int(m.group(2)), _year(m.group(1))))
    for m in _H_YEAR_FIRST_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            halves.append((int(m.group(2)), _year(m.group(1))))
    for m in _H_COMPACT_RE.finditer(t):
        if not _inside(protected_pre, m) and not _doc_ref_context(m.start()):
            halves.append((int(m.group(1)), _year(m.group(2))))
    for half, year in halves:
        month = 6 if half == 1 else 12
        _keep(date(year, month, calendar.monthrange(year, month)[1]))

    protected = exact_spans + invalid_spans + blocked_spans + phase_spans

    for m in _YEAR_MONTH_RE.finditer(t):
        if _inside(protected, m) or _doc_ref_context(m.start()): continue
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            _keep(date(year, month, calendar.monthrange(year, month)[1]))
    for rex, y2 in ((_MONTH_YEAR_RE, False), (_MONTH_YEAR_2Y_RE, True)):
        for m in rex.finditer(t):
            if _inside(protected, m) or _doc_ref_context(m.start()): continue
            month, year = int(m.group(1)), _year(m.group(2))
            if 1 <= month <= 12:
                _keep(date(year, month, calendar.monthrange(year, month)[1]))
    for m in _MON_HYPHEN_YEAR_RE.finditer(t):
        if _inside(protected, m) or _doc_ref_context(m.start()): continue
        month = _MONTHS.get(m.group(1).lower(), 0); year = int(m.group(2))
        if month:
            _keep(date(year, month, calendar.monthrange(year, month)[1]))
    for m in _MON_YEAR_RE.finditer(t):
        if _inside(protected, m) or _doc_ref_context(m.start()): continue
        month = _MONTHS.get(m.group(1).lower(), 1); year = int(m.group(2))
        _keep(date(year, month, calendar.monthrange(year, month)[1]))

    if best is None:
        # Invalides, versions et granularités reconnues mais non supportées :
        # aucune approximation au 31/12 n'est permise.
        if invalid_spans or blocked_spans or _VERSION_LIKE_RE.search(t) or _WEEK_LIKE_RE.search(t):
            return None
        if (re.search(r"\d{1,4}\s*[-/\.]\s*\d{1,2}", t)
                or re.search(r"\b(?:FY|[TQSH]\d|\d[QH])\b", t, re.IGNORECASE)):
            return None
        _bare_year_allowed = bool(
            re.fullmatch(r"\s*20\d{2}\s*", t)
            or re.search(
                r"\b(?:deadline|due|échéance|echeance|target|objective|objectif|"
                r"milestone|jalon|planned\s+for|scheduled\s+for|cibl[ée]e?|"
                r"before|by|avant|d['’]ici|au\s+plus\s+tard|end\s+of|fin\s+de)\b",
                t, re.IGNORECASE))
        if _bare_year_allowed:
            for m in _YEAR_RE.finditer(t):
                if not _inside(protected, m):
                    _keep(date(int(m.group(1)), 12, 31))
    return best


def _overdue_tag(lang: str) -> str:
    return ("[overdue deadline — to requalify]" if str(lang or "fr").lower().startswith("en")
            else "[échéance dépassée — à requalifier]")


def flag_past_action_deadline(deadline_text: str, run_date, lang: str = "fr"):
    """Renvoie (texte_éventuellement_flaggé, is_past). Une action dont l'échéance
    est < date du run est marquée comme dépassée (jamais présentée comme future)."""
    rd = _parse_run_date(run_date)
    if rd is None:
        # Gate 12 - sans autorite lisible, aucun jugement.
        return deadline_text, False
    d = parse_deadline(deadline_text)
    if d is not None and d < rd:
        tag = _overdue_tag(lang)
        txt = str(deadline_text or "").strip()
        if tag not in txt:
            txt = f"{txt} {tag}".strip()
        return txt, True
    return deadline_text, False


def flag_past_dated_actions(items, run_date, lang: str = "fr",
                            date_keys=("echeance", "delai", "date", "deadline", "échéance")):
    """Parcourt une liste d'actions (dicts) et flague les échéances passées
    in-place. Cible UNIQUEMENT les champs d'échéance d'actions — pas les constats.
    Renvoie le nombre d'actions flaggées."""
    if not isinstance(items, list):
        return 0
    n = 0
    _closed = ("fait", "faite", "terminé", "terminée", "clôturé", "clôturée",
               "cloturé", "réalisé", "réalisée", "abandonné", "abandonnée",
               "annulé", "annulée", "done", "completed", "closed", "cancelled")
    for it in items:
        if not isinstance(it, dict):
            continue
        # Scope D (B.1.3.56) — une action CLÔTURÉE dont l'échéance est passée
        # n'est pas « dépassée » : elle a été réalisée. Aucun tag.
        _cur = ""
        for sk in ("statut", "status"):
            if it.get(sk):
                _cur = str(it[sk]).strip().lower(); break
        if _cur in _closed:
            continue
        for k in date_keys:
            if k in it and isinstance(it[k], str):
                new, past = flag_past_action_deadline(it[k], run_date, lang)
                if past:
                    it[k] = new; n += 1
                    # Scope D (B.1.3.56) — une action OUVERTE à échéance
                    # dépassée ne peut pas rester « À lancer » : son statut
                    # devient « En retard » (les statuts d'arbitrage et de
                    # clôture sont conservés, l'échéance porte déjà le tag).
                    for sk in ("statut", "status"):
                        cur = str(it.get(sk, "") or "").strip().lower()
                        if cur in ("à lancer", "a lancer", "en cours",
                                   "to launch", "in progress", "open"):
                            it[sk] = ("Overdue" if (lang or "fr").lower().startswith("en")
                                      else "En retard")
                            break
                    break
    return n


# ── M6-A0.2 (A3) — gate NARRATIF conservateur (CR Word) ───────────────────────
# Couvre les dates passées dans la PROSE du CR (« S&OP à lancer au 30/04/2025 »,
# « plan média verrouillé avant 31/05/2025 ») SANS toucher aux constats
# (« FY25 clos le 29 mars 2025 », « publié le 15/05/2026 »). Règle : on ne flague
# une date passée que si un marqueur d'ACTION À VENIR / d'ÉCHÉANCE la précède dans
# une fenêtre courte. Un constat (clos / publié / réalisé / enregistré…) n'a pas
# ce marqueur → épargné.
_FWD_ACTION_RE = re.compile(
    r"(?:à\s+(?:lancer|r[ée]aliser|verrouiller|finaliser|livrer|engager|d[ée]ployer|"
    r"mettre|conduire|pr[ée]senter|valider|arbitrer|boucler|publier|pr[ée]parer|"
    r"cadrer|piloter|d[ée]marrer|initier|signer|d[ée]cider)|"
    r"deadline|[ée]ch[ée]ance|pr[ée]vu(?:e|s)?|planifi[ée](?:e|s)?|cibl[ée]|objectif|"
    r"jalon|avant|d[''’]ici|au\s+plus\s+tard|"
    r"activer|lancer|d[ée]ployer|[ée]tendre|acc[ée]l[ée]rer|restructurer|"
    r"d[ée]marrer|initier|mettre\s+en\s+place|"
    r"to\s+(?:launch|complete|deliver|finalize|present|validate|prepare|run|start|sign)|"
    r"due\b|target\b|by\s+|milestone|next\s+step|deliver\s+by)",
    re.IGNORECASE,
)
# B.1.3.56 (scope D) — un fait ACCOMPLI adjacent à la date exclut le flag :
# « absorption finalisée le 30/05/2025 », « ERP déployée en mars 2025 »,
# « verrouillé en T1 2025 » sont des constats historiques, jamais des échéances.
_DONE_RE = re.compile(
    r"\b(?:finalis[ée]e?s?|r[ée]alis[ée]e?s?|achev[ée]e?s?|sign[ée]e?s?|"
    r"cl[oô]tur[ée]e?s?|absorb[ée]e?s?|act[ée]e?s?|approuv[ée]e?s?|"
    r"effectu[ée]e?s?|livr[ée]e?s?|publi[ée]e?s?|d[ée]ploy[ée]e?s?|"
    r"verrouill[ée]e?s?|enregistr[ée]e?s?|c[ée]d[ée]e?s?|"
    r"absorption|fusion\s+(?:finalis[ée]e|r[ée]alis[ée]e|act[ée]e)|"
    r"completed|finali[sz]ed|signed|closed|delivered|deployed|recorded)\b",
    re.IGNORECASE,
)
_DATE_SPAN_RE = re.compile(
    r"(?P<d>\b20\d\d-\d{2}-\d{2}\b|"
    r"\b\d{1,2}\s*/\s*\d{1,2}\s*/\s*20\d\d\b|"
    r"\b[TQ][1-4]\s*[-/ ]?\s*20\d\d\b|"
    r"\b(?:printemps|été|ete|automne|hiver|spring|summer|autumn|fall|winter)\s+20\d\d\b|"
    r"\b(?:" + _MONTHS_RE + r")\s+20\d\d\b)",
    re.IGNORECASE,
)


import re as _re_reg
_REGISTRY_CTX_RE = _re_reg.compile(
    r"\b(accounts?|comptes|filed|d[ée]pos[ée]|filing|incorporat|registry|registre|"
    r"companies\s+house|latest\s+accounts|exercice\s+clos|year[-\s]?end|"
    r"cl[oô]ture\s+comptable|date\s+des\s+comptes)\b", _re_reg.I)


def flag_past_action_dates_in_text(text: str, run_date, lang: str = "fr") -> str:
    """Insère le tag « échéance dépassée » après une date PASSÉE uniquement si elle
    est introduite par un marqueur d'action/échéance. Constats laissés intacts."""
    if not text:
        return text
    rd = _parse_run_date(run_date)
    if rd is None:
        # Gate 12 - sans autorite lisible, aucun jugement.
        return text
    tag = _overdue_tag(lang)
    out = []
    last = 0
    for m in _DATE_SPAN_RE.finditer(text):
        d = parse_deadline(m.group("d"))
        win = text[max(0, m.start() - 55):m.start()]
        after = text[m.end():m.end() + 45]
        # M6-A2.x — ne JAMAIS flaguer une date en contexte registre/comptes (la
        # latest_accounts_date n'est pas une échéance d'action).
        ctx = text[max(0, m.start() - 60):m.end() + 45]
        if _REGISTRY_CTX_RE.search(ctx):
            continue
        # Scope D (B.1.3.56, durci gate ChatGPT) — dans la fenêtre, le
        # marqueur le plus PROCHE de la date gagne : « Absorption finalisée,
        # reporting à lancer au 30/04/2025 » doit taguer (l'action prospective
        # est plus proche), « Fusion finalisée le 30/05/2025 » ne tague jamais
        # (le fait accompli est le dernier marqueur avant la date).
        _done_last = max((mm.end() for mm in _DONE_RE.finditer(win)), default=-1)
        _fwd_last = max((mm.end() for mm in _FWD_ACTION_RE.finditer(win)), default=-1)
        if _done_last > _fwd_last:
            continue
        if d is not None and d < rd and _fwd_last >= 0 and tag not in after:
            out.append(text[last:m.end()])
            out.append(f" {tag}")
            last = m.end()
    out.append(text[last:])
    return "".join(out)
