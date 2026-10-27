# -*- coding: utf-8 -*-
"""Temporal legacy-intent boundary — pure, mention-local and compositional.

This module implements the rank-3 contract of the Temporal Core:

* it NEVER grants temporal authority;
* it converts a plausible natural-language analysis frame into a visible
  candidate that must be confirmed (A5);
* it leaves deadlines, document dates, measurements, historical events and
  comparisons in the live business brief;
* it fails closed when an analysis intention is explicit but its temporal
  expression is incomplete, invalid or contradictory;
* it is pure and session-safe: no request-specific state is stored on the
  detector singleton.

The public API and the historical data classes/constants are intentionally
kept stable because audit scripts and permanent contracts exercise them.
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

# ── Public signal states ────────────────────────────────────────────────
NONE = "NONE"
CANDIDATE = "CANDIDATE"
AMBIGUOUS = "AMBIGUOUS"
ERROR = "ERROR"

# ── Public semantic roles ──────────────────────────────────────────────
ANALYSIS_FRAME = "ANALYSIS_FRAME"
DEADLINE_OR_MILESTONE = "DEADLINE_OR_MILESTONE"
DOCUMENT_DATE = "DOCUMENT_DATE"
BUSINESS_MEASUREMENT = "BUSINESS_MEASUREMENT"
HISTORICAL_EVENT = "HISTORICAL_EVENT"
COMPARISON_OR_PERIOD = "COMPARISON_OR_PERIOD"
UNKNOWN = "UNKNOWN"

# ── Directive-act categories (internal, explicit and auditable) ───────
ACT_IMPERATIVE = "IMPERATIVE"
ACT_MODAL = "MODAL_OBLIGATION"
ACT_PURPOSE = "PURPOSE_OR_TASK"
ACT_PASSIVE = "PASSIVE_REQUEST"
ACT_QUESTION = "QUESTION_REQUEST"
ACT_HYPOTHESIS = "HYPOTHETICAL_REQUEST"
ACT_OPERATIONAL = "OPERATIONAL_ACTION"
ACT_DECLARATIVE = "DECLARATIVE_STATEMENT"
ACT_NOMINAL = "NOMINAL"

# ── Temporal expression categories ────────────────────────────────────
EXACT_DATE = "EXACT_DATE"
ABBREVIATED_DATE = "ABBREVIATED_DATE"
ORDINAL_DATE = "ORDINAL_DATE"
TWO_DIGIT_YEAR = "TWO_DIGIT_YEAR"
YEAR_ONLY = "YEAR_ONLY"
MONTH_YEAR = "MONTH_YEAR"
QUARTER_HALF_FY = "QUARTER_HALF_FY"
RELATIVE_DATE = "RELATIVE_DATE"
PLACEHOLDER = "PLACEHOLDER"
INVALID_DATE = "INVALID_DATE"

_MONTH_MAP = {
    # FR full / common abbreviations
    "janvier": 1, "janv": 1, "janv.": 1,
    "février": 2, "fevrier": 2, "févr": 2, "fevr": 2,
    "févr.": 2, "fevr.": 2,
    "mars": 3,
    "avril": 4, "avr": 4, "avr.": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7, "juil": 7, "juil.": 7,
    "août": 8, "aout": 8,
    "septembre": 9, "sept": 9, "sept.": 9,
    "octobre": 10, "oct": 10, "oct.": 10,
    "novembre": 11, "nov": 11, "nov.": 11,
    "décembre": 12, "decembre": 12, "déc": 12, "dec": 12,
    "déc.": 12, "dec.": 12,
    # EN full / abbreviations
    "january": 1, "jan": 1, "jan.": 1,
    "february": 2, "feb": 2, "feb.": 2,
    "march": 3, "mar": 3, "mar.": 3,
    "april": 4, "apr": 4, "apr.": 4,
    "may": 5,
    "june": 6, "jun": 6, "jun.": 6,
    "july": 7, "jul": 7, "jul.": 7,
    "august": 8, "aug": 8, "aug.": 8,
    "september": 9, "sep": 9, "sep.": 9, "sept": 9,
    "october": 10, "oct": 10, "oct.": 10,
    "november": 11, "nov": 11, "nov.": 11,
    "december": 12, "dec": 12, "dec.": 12,
}
_MONTH_ALT = "|".join(sorted((re.escape(k) for k in _MONTH_MAP),
                              key=len, reverse=True))

# Exact / partial expression regexes. They are evaluated together and the
# longest, highest-priority non-overlapping spans are retained.
_NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,4})\s*([./-])\s*(\d{1,2})\s*[./-]\s*(\d{1,4})(?!\d)")
_DAY_MONTH_YEAR_RE = re.compile(
    rf"(?<!\w)(\d{{1,2}})(?:st|nd|rd|th|er)?\s+({_MONTH_ALT})"
    r"(?:\s*,\s*|\s+)(\d{2,4})(?!\d)", re.IGNORECASE)
_MONTH_DAY_YEAR_RE = re.compile(
    rf"(?<!\w)({_MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?"
    r"(?:\s*,\s*|\s+)(\d{2,4})(?!\d)", re.IGNORECASE)
_QUARTER_RE = re.compile(r"\b([QT])\s*([1-4])\s*['’]?(\d{2,4})\b",
                         re.IGNORECASE)
_HALF_RE = re.compile(r"\b([HS])\s*([12])\s*['’]?(\d{2,4})\b",
                      re.IGNORECASE)
_FY_RE = re.compile(r"\bFY\s*['’]?(\d{2,4})\b", re.IGNORECASE)
_YEAR_END_RE = re.compile(
    r"\b(?:year[-\s]?end|end\s+of|at\s+the\s+end\s+of|"
    r"fin(?:\s+de\s+l['’]ann[ée]e)?|[àa]\s+fin|cl[ôo]ture(?:\s+de\s+l['’]exercice)?)"
    r"\s+(\d{4})\b", re.IGNORECASE)
_ANALYSIS_YEAR_AFTER_RE = re.compile(
    r"\b(?:analysis\s+year|ann[ée]e\s+d['’]analyse)\s*[:=]?\s*(\d{4})\b",
    re.IGNORECASE)
_ANALYSIS_YEAR_BEFORE_RE = re.compile(
    r"\b(\d{4})\s+(?:as\s+the\s+analysis\s+year|comme\s+ann[ée]e\s+d['’]analyse)\b",
    re.IGNORECASE)
_DAY_MONTH_NO_YEAR_RE = re.compile(
    rf"(?<!\w)(\d{{1,2}})(?:st|nd|rd|th|er)?\s+({_MONTH_ALT})(?!\s*\d)",
    re.IGNORECASE)
_MONTH_YEAR_RE = re.compile(
    rf"(?<!\w)({_MONTH_ALT})\s+(\d{{4}})(?!\d)", re.IGNORECASE)
_RELATIVE_RE = re.compile(
    r"\b(?:yesterday|hier|last\s+quarter|previous\s+quarter|"
    r"trimestre\s+dernier|next\s+year|ann[ée]e\s+prochaine|"
    r"latest\s+available\s+date|most\s+recent\s+date|"
    r"derni[èe]re\s+date\s+disponible|year[-\s]?end|fin\s+d['’]ann[ée]e|"
    r"il\s+y\s+a\s+(?:\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)\s+mois|"
    r"(?:\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix)\s+months?\s+ago)\b",
    re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(
    r"\b(?:TBD|TBC|unknown|pending|N/?A|someday|some\s+day|"
    r"to\s+be\s+(?:confirmed|defined|determined)|"
    r"a\s+date\s+to\s+be\s+(?:confirmed|defined|determined)|"
    r"[àa]\s+(?:d[ée]finir|confirmer|pr[ée]ciser|compl[ée]ter)|"
    r"date\s+(?:inconnue|[àa]\s+d[ée]finir))\b|\?{2,}",
    re.IGNORECASE)

_SENTENCE_DELIMS = ".;!?\n"
_CONNECTOR_RE = re.compile(
    r"\b(?:and\s+then|et\s+puis|compared\s+(?:with|to)|"
    r"par\s+rapport\s+[àa]|versus|vs\.?|then|puis|and|et|or|ou|but|mais)\b",
    re.IGNORECASE)
_COMPARISON_CONNECTOR_RE = re.compile(
    r"\b(?:compared\s+(?:with|to)|par\s+rapport\s+[àa]|versus|vs\.?)\b",
    re.IGNORECASE)

# Analysis and operational predicate lexicons are intentionally small and
# domain-oriented. The decision does not rely on a single verb: act type,
# target, attachment and composition are evaluated together.
_ANALYSIS_VERB_RE = re.compile(
    r"\b(?:analy[sz](?:e|es|ed|ing)?|assess(?:es|ed|ing)?|"
    r"evaluat(?:e|es|ed|ing)|review(?:s|ed|ing)?|examin(?:e|es|ed|ing)|"
    r"stud(?:y|ies|ied|ying)|simulat(?:e|es|ed|ing)|"
    r"reconstruct(?:s|ed|ing)?|backtest(?:s|ed|ing)?|"
    r"apprais(?:e|es|ed|ing)|diagnos(?:e|es|ed|ing)|model(?:s|ed|ing)?|"
    r"compare(?:s|d|ing)?|"
    r"analys(?:er|ez|e|ons|ent|ait|ée|ées)?|[ée]valu(?:er|ez|e|ons|ent|ait|ée)?|"
    r"examin(?:er|ez|e|ons|ent|ait|é)?|[ée]tudi(?:er|ez|e|ons|ent|ait|é)?|"
    r"simul(?:er|ez|e|ons|ent|ait|é)?|reconstitu(?:er|ez|e|ons|ent|ait|é)?|"
    r"compar(?:er|ez|e|ons|ent|ait|é)?|"
    r"diagnostiqu(?:er|ez|e|ons|ent|ait|é)?|mod[ée]lis(?:er|ez|e|ons|ent|ait|é)?)\b",
    re.IGNORECASE)
_OPERATIONAL_VERB_RE = re.compile(
    r"\b(?:submit|present|approve|complete|finalize|finalise|schedule|hold|"
    r"launch|report\s+to|deliver|file|send|publish|close|implement|release|"
    r"remettre|remettez|pr[ée]senter|pr[ée]sentez|approuver|approuvez|"
    r"finaliser|finalisez|cl[ôo]turer|cl[ôo]turez|lancer|lancez|tenir|tenez|"
    r"planifier|planifiez|programmer|programmez|soumettre|soumettez|"
    r"d[ée]poser|d[ée]posez|publier|publiez|envoyer|envoyez|achever|achevez)\b",
    re.IGNORECASE)
_ANALYSIS_TARGET_RE = re.compile(
    r"\b(?:company|business|organisation|organization|group|entity|enterprise|"
    r"soci[ée]t[ée]|entreprise|organisation|groupe|entit[ée]|activité|activity)\b",
    re.IGNORECASE)
_ANALYSIS_NOUN_RE = re.compile(
    r"\b(?:analysis|review|assessment|evaluation|diagnosis|study|"
    r"analyse|revue|[ée]valuation|diagnostic|[ée]tude)\b", re.IGNORECASE)
_ANALYSIS_NOMINAL_FOLLOW_RE = re.compile(
    r"^\s+(?:financial|finance|strategic|strategy|commercial|operational|"
    r"complete|full|detailed|historical|historic|preliminary|"
    r"financi[èe]re?|strat[ée]gique|commerciale?|op[ée]rationnelle?|"
    r"compl[èe]te?|d[ée]taill[ée]e?|historique|pr[ée]liminaire)\b",
    re.IGNORECASE)
_FRAME_NOUN_RE = re.compile(
    r"\b(?:reference\s+(?:date|point)|analysis\s+(?:date|year)|scenario\s+date|"
    r"point\s+de\s+r[ée]f[ée]rence|date\s+de\s+r[ée]f[ée]rence|"
    r"ann[ée]e\s+d['’]analyse|perspective|starting\s+point|point\s+de\s+d[ée]part|"
    r"cut[-\s]?off|snapshot|photograph(?:y|ie)|photographie|"
    r"today|current\s+date|aujourd['’]hui|date\s+du\s+jour|"
    r"situation\s+future|position\s+at|position\s+on|"
    r"situation\s+au|situation\s+[àa]\s+la\s+date)\b", re.IGNORECASE)

_FRAME_CONTROL_VERB_RE = re.compile(
    r"\b(?:base|use|set|take|retain|choose|adopt|place|freeze|treat|consider|"
    r"run|perform|conduct|"
    r"baser|basez|utiliser|utilisez|retenir|retenez|prendre|prenez|"
    r"adopter|adoptez|placer|placez|figer|figez|consid[ée]rer|consid[ée]rez|"
    r"faire|faites|r[ée]aliser|r[ée]alisez|conduire|conduisez)\b", re.IGNORECASE)

# High-frequency analytical constructions whose directive force is carried by
# a light verb or a fixed professional phrase rather than by the analysis
# noun itself.  The pattern is deliberately anchored to a request position
# (sentence/field head, optionally after a polite or exercise preamble).  It
# therefore covers genuine user instructions without reviving the historical
# unsafe fallback “first non-function word = imperative”.
_ANALYTIC_CONSTRUCTION_RE = re.compile(
    r"(?:^|[.!?;\n]\s*)"
    r"(?:for\s+(?:this|the)\s+(?:exercise|review)[,:]?\s*|"
    r"pour\s+(?:cet|cette)\s+(?:exercice|revue)[,:]?\s*)?"
    r"(?:please\s+|kindly\s+|merci\s+de\s+|veuillez\s+)?"
    r"(?:"
    # English light-verb constructions.
    r"(?:carry\s+out|undertake|prepare)\s+(?:an?|the)?\s*"
    r"(?:analysis|review|assessment|evaluation|diagnosis|study)\s+"
    r"(?:of|on)\s+(?:the\s+)?(?:company|business|organisation|organization|group|entity|enterprise)"
    r"|(?:provide|give(?:\s+me)?|form)\s+(?:an?|the)?\s*"
    r"(?:analysis|review|assessment|evaluation|diagnosis|view)\s+"
    r"(?:of|on)\s+(?:the\s+)?(?:company|business|organisation|organization|group|entity|enterprise)"
    r"|look\s+at\s+(?:the\s+)?(?:company|business|organisation|organization|group|entity|enterprise)"
    r"|take\s+stock\s+of\s+(?:the\s+)?(?:company|business|organisation|organization|group|entity|enterprise)"
    r"|(?:recreate|reconstruct)\s+(?:the\s+)?(?:company(?:['’]s)?|business(?:['’]s)?|group(?:['’]s)?)\s+"
    r"(?:position|situation|state)"
    r"|determine\s+how\s+(?:the\s+)?(?:company|business|organisation|organization|group|entity|enterprise)\s+"
    r"(?:stood|looked|performed|was|operated)"
    # French professional constructions.
    r"|proc[ée]d(?:er|ez)\s+[àa]\s+(?:l['’])?(?:analyse|revue|[ée]valuation|[ée]tude|diagnostic)\s+"
    r"(?:de|sur)\s+(?:la\s+|l['’]|le\s+)?(?:soci[ée]t[ée]|entreprise|organisation|groupe|entit[ée]|activit[ée])"
    r")", re.IGNORECASE)

# Compact French professional constructions are kept in a second expression
# to make alternation precedence explicit and auditable.
_ANALYTIC_CONSTRUCTION_FR_RE = re.compile(
    r"(?:^|[.!?;\n]\s*)"
    r"(?:pour\s+(?:cet|cette)\s+(?:exercice|revue)[,:]?\s*)?"
    r"(?:merci\s+de\s+|veuillez\s+)?"
    r"(?:"
    r"(?:faire|faites)\s+le\s+point\s+sur\s+(?:la\s+|l['’]|le\s+)?"
    r"(?:soci[ée]t[ée]|entreprise|organisation|groupe|entit[ée]|activit[ée])"
    r"|(?:dresser|dressez|[ée]tablir|[ée]tablissez)\s+(?:un|une|l['’])?\s*"
    r"(?:diagnostic|[ée]tat\s+des\s+lieux|analyse|vue)\s+(?:de|sur)\s+"
    r"(?:la\s+|l['’]|le\s+)?(?:soci[ée]t[ée]|entreprise|organisation|groupe|entit[ée]|activit[ée])"
    r"|(?:donner|donnez|fournir|fournissez|produire|produisez)\s*(?:-?moi\s+)?"
    r"(?:un|une|l['’])?\s*(?:analyse|revue|[ée]valuation|vue|diagnostic)\s+(?:de|sur)\s+"
    r"(?:la\s+|l['’]|le\s+)?(?:soci[ée]t[ée]|entreprise|organisation|groupe|entit[ée]|activit[ée])"
    r"|d[ée]termin(?:er|ez)\s+comment\s+(?:se\s+)?(?:pr[ée]sentait|situait|portait|comportait|[ée]tait)\s+"
    r"(?:la\s+|l['’]|le\s+)?(?:soci[ée]t[ée]|entreprise|organisation|groupe|entit[ée]|activit[ée])"
    r")", re.IGNORECASE)

_METRIC_RE = re.compile(
    r"\b(?:revenue|turnover|sales|ebitda|ebit|margin|cash(?:\s+flow)?|"
    r"profit|loss|net\s+debt|debt|inventory|stock|order\s+book|backlog|"
    r"pipeline|headcount|workforce|balance\s+sheet|income\s+statement|"
    r"financial\s+statements?|accounts?|assets?|liabilit(?:y|ies)|"
    r"chiffre\s+d['’]affaires|r[ée]sultat|marge|tr[ée]sorerie|flux\s+de\s+tr[ée]sorerie|"
    r"dette(?:\s+nette)?|inventaire|stocks?|carnet\s+de\s+commandes|"
    r"effectif|bilan|comptes?|[ée]tats?\s+financiers?|actifs?|passifs?)\b",
    re.IGNORECASE)
_DOCUMENT_RE = re.compile(
    r"\b(?:dated|attached|enclosed|appendix|document|report|manual|documentation|"
    r"board\s+pack|roadmap|strategic\s+plan|forecast|"
    r"dat(?:é|ée|és|ées)|ci[-\s]joint|pi[èe]ce\s+jointe|annexe|document|rapport|manuel|"
    r"documentation|feuille\s+de\s+route|plan\s+strat[ée]gique|pr[ée]vision)\b",
    re.IGNORECASE)
_EVENT_RE = re.compile(
    r"\b(?:meeting|workshop|session|committee|board\s+meeting|quarterly\s+review|"
    r"rendez[-\s]vous|atelier|session|comit[ée]|conseil|revue\s+trimestrielle)\b",
    re.IGNORECASE)
_AMOUNT_RE = re.compile(
    r"(?:[€$£¥]|\b(?:EUR|USD|GBP|CHF)\b|\b\d[\d\s.,]*\s*(?:%|k€|M€|m|bn|million|billion|millions?|milliards?)\b)",
    re.IGNORECASE)

_MODAL_REQUEST_RE = re.compile(
    r"\b(?:we|you|i|they)\s+(?:should|must|need\s+to|have\s+to|could|would|can)\b"
    r"|\b(?:il\s+faut|nous\s+devons|vous\s+devez|on\s+doit|devrions|faudrait)\b",
    re.IGNORECASE)
_PURPOSE_REQUEST_RE = re.compile(
    r"\b(?:the\s+task|our\s+task|the\s+objective|our\s+objective|the\s+purpose|"
    r"the\s+goal)\s+(?:is|would\s+be)\s+to\b"
    r"|\b(?:la\s+t[âa]che|notre\s+t[âa]che|l['’]objectif|notre\s+objectif|le\s+but)\s+"
    r"(?:est|consiste)\s+(?:[àa]|de)\b", re.IGNORECASE)
_PASSIVE_REQUEST_RE = re.compile(
    r"\b(?:analysis|review|assessment|evaluation)\s+(?:should|must|needs?\s+to|is\s+to)\s+be\s+"
    r"(?:performed|conducted|carried\s+out|completed|made)\b"
    r"|\b(?:company|business|organisation|organization|group|entity|enterprise)\s+"
    r"(?:is|are)\s+to\s+be\s+(?:analy[sz]ed|assessed|evaluated|reviewed|examined|studied)\b"
    r"|\b(?:an\s+)?(?:analysis|review|assessment|evaluation)\s+of\s+(?:the\s+)?"
    r"(?:company|business|organisation|organization|group|entity|enterprise)\s+"
    r"(?:is|are)\s+(?:required|requested|expected)\b"
    r"|\b(?:l['’]analyse|la\s+revue|l['’][ée]valuation)\s+(?:doit|devrait|est\s+[àa])\s+[êe]tre?\s*"
    r"(?:r[ée]alis[ée]e|conduite|effectu[ée]e)?\b"
    r"|\b(?:la\s+soci[ée]t[ée]|l['’]entreprise|le\s+groupe|l['’]entit[ée])\s+"
    r"(?:doit|devrait|est\s+[àa])\s+[êe]tre\s+(?:analys[ée]e|[ée]valu[ée]e|examin[ée]e|[ée]tudi[ée]e)\b",
    re.IGNORECASE)
_QUESTION_REQUEST_RE = re.compile(
    r"\b(?:would\s+it\s+be\s+possible\s+to|could\s+you|would\s+you|can\s+you)\b"
    r"|\b(?:what|how)\s+would\b|\bserait[-\s]il\s+possible\s+de\b"
    r"|\b(?:pourriez[-\s]vous|pouvez[-\s]vous)\b|\bque\s+se\s+passerait[-\s]il\b",
    re.IGNORECASE)
_HYPOTHESIS_RE = re.compile(
    r"\b(?:assume|suppose|imagine|treat|consider)\b|\bif\b[^.!?;\n]{0,90}\b(?:were|was)\b"
    r"|\b(?:supposons|imaginons|admettons|consid[ée]rons|consid[ée]rez)\b"
    r"|\bsi\b[^.!?;\n]{0,90}\b[ée]tait\b",
    re.IGNORECASE)
_PAST_RE = re.compile(
    r"\b(?:was|were|had|has\s+been|have\s+been|had\s+been|did|approved|completed|"
    r"finalized|finalised|closed|ended|published|filed|"
    r"[ée]tait|[ée]taient|avait|avaient|a\s+[ée]t[ée]|ont\s+[ée]t[ée]|finalis[ée]e?s?|"
    r"cl[ôo]tur[ée]e?s?|termin[ée]e?s?|approuv[ée]e?s?|publi[ée]e?s?|d[ée]pos[ée]e?s?)\b",
    re.IGNORECASE)
_FRAME_RELATION_RE = re.compile(
    r"\b(?:as\s+of|as\s+at|at|on|with|from|using|based\s+on|in\s+date|"
    r"au|[àa]\s+la\s+date|en\s+date|[àa]\s+partir\s+de|sur\s+la\s+situation)\b",
    re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r"\b(?:by|before|no\s+later\s+than|due\s+(?:on|by)?|deadline|on|at|"
    r"d['’]ici|avant|au\s+plus\s+tard|pour\s+le|pour\s+la|le|au)\b",
    re.IGNORECASE)
_RANGE_RE = re.compile(
    r"\b(?:from|between|du|de|entre)\b[\s\S]{0,80}?\b(?:to|through|until|and|au|[àa]|et)\b",
    re.IGNORECASE)
_COMPARISON_RE = re.compile(
    r"\b(?:compare|compared\s+(?:with|to)|comparison|versus|vs\.?|"
    r"comparer|compar[ée]\s+[àa]|par\s+rapport\s+[àa])\b", re.IGNORECASE)

_CONTROL_FIELD_RE = re.compile(
    r"^\s*(?:analysis[_ ]as[_ ]of[_ ]date\s*=|date\s+d['’]analyse\s*:|"
    r"scenario\s+date\s*:|[àa]\s+la\s+date\s+du\s+[^:\n]+\s*:|"
    r"reference\s+date\s*:|analysis\s+date\s+to\s+use\s*:|"
    r"analysis\s+year\s*:|date\s+de\s+r[ée]f[ée]rence\s*:|"
    r"ann[ée]e\s+d['’]analyse\s*:)",
    re.IGNORECASE)
_NEGATED_FIELD_RE = re.compile(
    r"\b(?:do\s+not\s+use|not\s+to\s+be\s+used|ignore|previous|former|old|obsolete|"
    r"ne\s+pas\s+utiliser|ne\s+plus\s+utiliser|ignorer|ancien(?:ne)?|pr[ée]c[ée]dent(?:e)?)\b",
    re.IGNORECASE)

_NUMBER_WORDS_FR = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}


def _ascii_word(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(ch))


def _year4(raw: str) -> int:
    y = int(raw)
    if len(raw) == 2:
        return 2000 + y if y <= 69 else 1900 + y
    return y


def _safe_date(y: int, m: int, d: int) -> Optional[str]:
    try:
        return date(y, m, d).isoformat()
    except Exception:
        return None


def _month_number(raw: str) -> Optional[int]:
    return _MONTH_MAP.get(raw.casefold()) or _MONTH_MAP.get(_ascii_word(raw))


def _contains_temporal_expression(text: str) -> bool:
    """Cheap syntax probe used only for speech-act classification.

    Semantic parsing remains the responsibility of
    :class:`TemporalExpressionNormalizer`; this helper merely recognises that
    an inverted adjunct contains a date/period token before an imperative.
    """
    return any(regex.search(text or "") for regex in (
        _NUMERIC_DATE_RE, _DAY_MONTH_YEAR_RE, _MONTH_DAY_YEAR_RE,
        _QUARTER_RE, _HALF_RE, _FY_RE, _YEAR_END_RE,
        _DAY_MONTH_NO_YEAR_RE, _MONTH_YEAR_RE, _RELATIVE_RE,
        _PLACEHOLDER_RE,
    ))


@dataclass(frozen=True)
class DateMention:
    """A temporal expression located before any semantic classification."""

    raw: str = ""
    parsed_value: Optional[str] = None
    parse_status: str = "NONE"  # VALID | INVALID | PLACEHOLDER | NONE
    span: Tuple[int, int] = (0, 0)
    local_clause: str = ""
    clause_span: Tuple[int, int] = (0, 0)
    opening_coordinator: str = ""
    source_text: str = ""
    expression_kind: str = ""
    sentence_span: Tuple[int, int] = (0, 0)

    @property
    def is_usable(self) -> bool:
        return self.parse_status == "VALID" and bool(self.parsed_value)


@dataclass(frozen=True)
class LegacyIntent:
    """Rank-3 signal. It is never an authority."""

    kind: str = NONE
    value: Optional[str] = None
    raw: str = ""
    span: Tuple[int, int] = (0, 0)
    reason: str = ""
    relation: str = UNKNOWN
    mentions: Tuple[DateMention, ...] = field(default_factory=tuple)

    def is_signal(self) -> bool:
        return self.kind in (CANDIDATE, AMBIGUOUS, ERROR)


@dataclass(frozen=True)
class _RawExpression:
    raw: str
    span: Tuple[int, int]
    parsed_value: Optional[str]
    parse_status: str
    kind: str
    priority: int


class TemporalExpressionNormalizer:
    """Extract and normalize business temporal expressions.

    Extraction is deliberately independent from semantic role. A date is
    first represented faithfully, then attached to the sentence constituent
    that it qualifies.
    """

    def extract(self, text: str, run_date: Optional[str] = None) -> List[_RawExpression]:
        candidates: List[_RawExpression] = []

        def add(match: re.Match, value: Optional[str], status: str,
                kind: str, priority: int, span_group: Optional[int] = None) -> None:
            if span_group is None:
                a, b = match.span(0)
                raw = match.group(0)
            else:
                a, b = match.span(span_group)
                raw = match.group(span_group)
            candidates.append(_RawExpression(raw, (a, b), value, status,
                                             kind, priority))

        # Full numeric dates.
        for m in _NUMERIC_DATE_RE.finditer(text):
            a, _sep, b, c = m.groups()
            value = None
            kind = EXACT_DATE
            status = "INVALID"
            try:
                if len(a) == 4:
                    y, mo, d = int(a), int(b), int(c)
                else:
                    y = _year4(c)
                    x1, x2 = int(a), int(b)
                    kind = TWO_DIGIT_YEAR if len(c) == 2 else EXACT_DATE
                    if x1 > 12 >= x2:
                        d, mo = x1, x2
                    elif x2 > 12 >= x1:
                        mo, d = x1, x2
                    elif x1 == x2:
                        d, mo = x1, x2
                    else:
                        raise ValueError("ambiguous numeric date")
                value = _safe_date(y, mo, d)
                status = "VALID" if value else "INVALID"
            except Exception:
                status, value = "INVALID", None
            add(m, value, status, kind, 10)

        # Literal dates.
        for m in _DAY_MONTH_YEAR_RE.finditer(text):
            d, mon, yraw = m.groups()
            y = _year4(yraw)
            mo = _month_number(mon)
            value = _safe_date(y, mo or 0, int(d)) if mo else None
            kind = ORDINAL_DATE if re.search(r"(?:st|nd|rd|th|er)", m.group(0), re.I) else ABBREVIATED_DATE
            add(m, value, "VALID" if value else "INVALID", kind, 10)
        for m in _MONTH_DAY_YEAR_RE.finditer(text):
            mon, d, yraw = m.groups()
            y = _year4(yraw)
            mo = _month_number(mon)
            value = _safe_date(y, mo or 0, int(d)) if mo else None
            kind = ORDINAL_DATE if re.search(r"(?:st|nd|rd|th)", m.group(0), re.I) else ABBREVIATED_DATE
            add(m, value, "VALID" if value else "INVALID", kind, 10)

        # Coarse periods with a known end.
        for m in _QUARTER_RE.finditer(text):
            _qt, q, yraw = m.groups()
            y = _year4(yraw)
            month = int(q) * 3
            value = date(y, month, calendar.monthrange(y, month)[1]).isoformat()
            add(m, value, "VALID", QUARTER_HALF_FY, 20)
        for m in _HALF_RE.finditer(text):
            _hs, h, yraw = m.groups()
            y = _year4(yraw)
            month = 6 if h == "1" else 12
            value = date(y, month, calendar.monthrange(y, month)[1]).isoformat()
            add(m, value, "VALID", QUARTER_HALF_FY, 20)
        for m in _YEAR_END_RE.finditer(text):
            y = int(m.group(1))
            add(m, date(y, 12, 31).isoformat(), "VALID", YEAR_ONLY, 20)
        for m in _FY_RE.finditer(text):
            # Fiscal year end is jurisdiction-dependent. Keep visible but do
            # not manufacture a calendar date.
            add(m, None, "PLACEHOLDER", QUARTER_HALF_FY, 20)

        # Explicit analysis-year forms are visible but not silently reduced
        # to an arbitrary day.
        for regex in (_ANALYSIS_YEAR_AFTER_RE, _ANALYSIS_YEAR_BEFORE_RE):
            for m in regex.finditer(text):
                group = 1
                add(m, None, "PLACEHOLDER", YEAR_ONLY, 25,
                    span_group=group)

        # Incomplete literal dates / month-year expressions.
        for m in _DAY_MONTH_NO_YEAR_RE.finditer(text):
            add(m, None, "PLACEHOLDER", PLACEHOLDER, 30)
        for m in _MONTH_YEAR_RE.finditer(text):
            # Ignore if already part of a full literal date; overlap resolver
            # keeps the full expression because it has stronger priority.
            add(m, None, "PLACEHOLDER", MONTH_YEAR, 30)

        # Relative and placeholder expressions.
        for m in _RELATIVE_RE.finditer(text):
            value = None
            raw = m.group(0).casefold()
            # Deterministic relative values are safe candidates; other
            # expressions remain explicit ambiguities.
            if run_date:
                try:
                    rd = date.fromisoformat(str(run_date)[:10])
                    if raw in ("yesterday", "hier"):
                        value = (rd - timedelta(days=1)).isoformat()
                    elif raw in ("last quarter", "previous quarter", "trimestre dernier"):
                        q = (rd.month - 1) // 3
                        if q == 0:
                            y, month = rd.year - 1, 12
                        else:
                            y, month = rd.year, q * 3
                        value = date(y, month, calendar.monthrange(y, month)[1]).isoformat()
                except Exception:
                    value = None
            add(m, value, "VALID" if value else "PLACEHOLDER",
                RELATIVE_DATE, 35)
        for m in _PLACEHOLDER_RE.finditer(text):
            add(m, None, "PLACEHOLDER", PLACEHOLDER, 35)

        # Retain non-overlapping expressions: stronger priority, then longer
        # span. This prevents « February 2023 » from shadowing
        # « 15 February 2023 ».
        candidates.sort(key=lambda x: (x.priority, -(x.span[1] - x.span[0]),
                                       x.span[0]))
        chosen: List[_RawExpression] = []
        for cand in candidates:
            if any(not (cand.span[1] <= x.span[0] or cand.span[0] >= x.span[1])
                   for x in chosen):
                continue
            chosen.append(cand)
        return sorted(chosen, key=lambda x: x.span)


@dataclass(frozen=True)
class DirectiveAct:
    kind: str
    analysis_spans: Tuple[Tuple[int, int], ...] = ()
    operational_spans: Tuple[Tuple[int, int], ...] = ()

    @property
    def requests_analysis(self) -> bool:
        return self.kind in {
            ACT_IMPERATIVE, ACT_MODAL, ACT_PURPOSE, ACT_PASSIVE,
            ACT_QUESTION, ACT_HYPOTHESIS,
        }


class DirectiveActClassifier:
    """Classify the speech act independently from the temporal role."""

    @staticmethod
    def _spans(regex: re.Pattern, text: str) -> Tuple[Tuple[int, int], ...]:
        return tuple(m.span() for m in regex.finditer(text))

    def classify(self, text: str) -> DirectiveAct:
        construction_spans = tuple(
            m.span()
            for regex in (_ANALYTIC_CONSTRUCTION_RE, _ANALYTIC_CONSTRUCTION_FR_RE)
            for m in regex.finditer(text)
        )
        analysis_spans = tuple(sorted(set(
            self._spans(_ANALYSIS_VERB_RE, text) + construction_spans
        )))
        operational_spans = self._spans(_OPERATIONAL_VERB_RE, text)
        if _QUESTION_REQUEST_RE.search(text) and (analysis_spans or _FRAME_NOUN_RE.search(text)):
            kind = ACT_QUESTION
        elif _HYPOTHESIS_RE.search(text):
            kind = ACT_HYPOTHESIS
        elif _PASSIVE_REQUEST_RE.search(text):
            kind = ACT_PASSIVE
        elif _PURPOSE_REQUEST_RE.search(text) and analysis_spans:
            kind = ACT_PURPOSE
        elif _MODAL_REQUEST_RE.search(text) and analysis_spans:
            kind = ACT_MODAL
        elif construction_spans:
            kind = ACT_IMPERATIVE
        elif _PAST_RE.search(text) and not (_MODAL_REQUEST_RE.search(text)
                                              or _QUESTION_REQUEST_RE.search(text)
                                              or _HYPOTHESIS_RE.search(text)):
            kind = ACT_DECLARATIVE
        elif operational_spans and not self._analysis_command_precedes_operation(
                analysis_spans, operational_spans):
            kind = ACT_OPERATIONAL
        elif self._is_imperative_analysis(text, analysis_spans):
            kind = ACT_IMPERATIVE
        elif operational_spans:
            kind = ACT_OPERATIONAL
        else:
            kind = ACT_NOMINAL
        return DirectiveAct(kind, analysis_spans, operational_spans)

    @staticmethod
    def _analysis_command_precedes_operation(analysis_spans, operational_spans) -> bool:
        if not analysis_spans or not operational_spans:
            return False
        return min(a for a, _ in analysis_spans) < min(a for a, _ in operational_spans)

    @staticmethod
    def _is_imperative_analysis(text: str, spans: Sequence[Tuple[int, int]]) -> bool:
        if not spans:
            return False
        # Base/imperative form at sentence head or after a source-setting
        # preamble (« Using the report, analyze… »).
        for a, _b in spans:
            token = text[a:_b].casefold()
            # Ambiguous surface forms such as French « analyse » and English
            # « review » are nouns when followed by a domain/adjectival
            # qualifier.  « As of <date>, analyse financière complète » is a
            # nominal heading, not an imperative request.
            if token in {"analyse", "review", "evaluation", "évaluation", "etude", "étude"}                     and _ANALYSIS_NOMINAL_FOLLOW_RE.match(text[_b:]):
                continue
            prefix = text[:a].strip(" \t\n,;:-")
            if not prefix:
                return True
            if re.search(r"\b(?:please|kindly|using|based\s+on|from|with|"
                         r"veuillez|merci\s+de|[àa]\s+partir\s+de|sur\s+la\s+base\s+de)\b[^.!?;]*$",
                         prefix, re.IGNORECASE):
                return True
            # Inverted frame: « as of <date>, analyze … ».  The text before
            # the predicate is only the temporal adjunct, not a declarative
            # subject. Literal and numeric forms are both accepted.
            if (re.search(r"\b(?:as\s+of|as\s+at|au|[àa]\s+la\s+date\s+du)\b",
                          prefix, re.IGNORECASE)
                    and _contains_temporal_expression(prefix)):
                return True
            # French infinitive headings/bullets are valid requests.
            if token.endswith("er") or token.endswith("ez"):
                return True
        return False


class TemporalAttachmentClassifier:
    """Attach each temporal mention to its local semantic governor."""

    def __init__(self) -> None:
        self._acts = DirectiveActClassifier()

    def classify(self, mention: DateMention,
                 mentions: Sequence[DateMention]) -> str:
        source = mention.source_text
        sentence = source[mention.sentence_span[0]:mention.sentence_span[1]]
        local = mention.local_clause
        before = source[mention.clause_span[0]:mention.span[0]]
        after = source[mention.span[1]:mention.clause_span[1]]
        act = self._acts.classify(local)

        # 1. Explicit control field at top level.
        if self._is_leading_control_field(mention):
            return ANALYSIS_FRAME
        # A reference-field-looking line outside the top-level control zone
        # is documentation, never a rank-3 request.
        if _CONTROL_FIELD_RE.match(mention.local_clause.strip()):
            return DOCUMENT_DATE

        # 2. Composition relations: ranges and comparisons are business
        # scope unless the range is explicitly the requested company frame.
        range_kind = self._range_role(mention, mentions)
        if range_kind:
            return range_kind
        if self._is_comparison_mention(mention, mentions):
            return COMPARISON_OR_PERIOD

        # 3. Direct attachment beats words elsewhere in the local window.
        if self._direct_document_attachment(before):
            return DOCUMENT_DATE
        if self._direct_event_or_operational_attachment(before, local, act):
            return DEADLINE_OR_MILESTONE
        if self._direct_metric_attachment(before, local, mention):
            return BUSINESS_MEASUREMENT

        # 4. Explicit analysis frame. This is evaluated after direct object
        # attachment, so « review headcount as of <date> » stays a metric,
        # while « using revenue data, analyze the company as of <date> »
        # remains a frame.
        if self._analysis_frame(mention, local, before, after, act):
            return ANALYSIS_FRAME

        # 5. Remaining documentary / historical / nominal content.
        if _DOCUMENT_RE.search(local):
            return DOCUMENT_DATE
        if _METRIC_RE.search(local) or _AMOUNT_RE.search(local):
            return BUSINESS_MEASUREMENT
        if act.kind == ACT_DECLARATIVE or _PAST_RE.search(local):
            return HISTORICAL_EVENT
        if act.kind == ACT_OPERATIONAL:
            return DEADLINE_OR_MILESTONE
        return UNKNOWN

    @staticmethod
    def _direct_document_attachment(before: str) -> bool:
        tail = before[-120:]
        return bool(re.search(
            r"\b(?:dated|dat(?:é|ée|és|ées)|document\s+du|report\s+dated|"
            r"accounts?\s+dated|comptes?\s+(?:dat(?:é|ée|és|ées)|clos|"
            r"arr[êe]t[ée]s?)\s*(?:au|le)?|year\s+ended|period\s+ended|"
            r"situation\s+financi[èe]re\s+arr[êe]t(?:é|ée|és|ées)\s*(?:au|le)?)"
            r"\s*$", tail, re.IGNORECASE))

    @staticmethod
    def _direct_event_or_operational_attachment(before: str, local: str,
                                                 act: DirectiveAct) -> bool:
        tail = before[-140:]
        if _DEADLINE_RE.search(tail) and not re.search(
                r"(?:data|information|donn[ée]es|informations)\s+available\s*$|"
                r"(?:donn[ée]es|informations)\s+disponibles?\s*$",
                tail, re.IGNORECASE):
            if act.kind == ACT_OPERATIONAL or _OPERATIONAL_VERB_RE.search(local):
                return True
        events = list(_EVENT_RE.finditer(tail))
        if events:
            targets = list(_ANALYSIS_TARGET_RE.finditer(tail))
            if not targets or events[-1].start() > targets[-1].start():
                return True
        if act.kind == ACT_OPERATIONAL and _OPERATIONAL_VERB_RE.search(before):
            return True
        return False

    @staticmethod
    def _direct_metric_attachment(before: str, local: str,
                                  mention: DateMention) -> bool:
        # ``take stock of the company`` is an analytical idiom, not an
        # inventory metric.  More generally, explicit professional analytical
        # constructions outrank incidental metric tokens inside that phrase.
        if (_ANALYTIC_CONSTRUCTION_RE.search(local)
                or _ANALYTIC_CONSTRUCTION_FR_RE.search(local)):
            return False
        tail = before[-120:]
        metrics = list(_METRIC_RE.finditer(tail))
        if not metrics:
            return False
        last_metric = metrics[-1]
        # If an analysis predicate occurs after the metric, the metric is a
        # source/object and the date may still frame the company analysis.
        analysis_after_metric = any(m.start() > last_metric.start()
                                    for m in _ANALYSIS_VERB_RE.finditer(tail))
        if analysis_after_metric and _ANALYSIS_TARGET_RE.search(tail[last_metric.end():]):
            return False
        # Direct metric phrase immediately before the temporal relation.
        return len(tail) - last_metric.end() <= 55

    def _analysis_frame(self, mention: DateMention, local: str, before: str,
                        after: str, act: DirectiveAct) -> bool:
        if (_ANALYTIC_CONSTRUCTION_RE.search(local)
                or _ANALYTIC_CONSTRUCTION_FR_RE.search(local)):
            return True
        # A declarative or purely nominal statement never becomes a
        # request merely because it contains the noun “analysis/position”.
        if act.kind == ACT_DECLARATIVE:
            return False
        if _QUESTION_REQUEST_RE.search(local):
            if (_ANALYSIS_VERB_RE.search(local) or _ANALYSIS_TARGET_RE.search(local)
                    or _FRAME_NOUN_RE.search(local)):
                return True
        if _HYPOTHESIS_RE.search(local):
            if _FRAME_RELATION_RE.search(local):
                return True
            # Hypothetical date can be stated copularly before a coordinated
            # analysis request: « Let us assume that it is <date> and
            # analyze the company ». Connector-local windows deliberately
            # separate the two acts, so consult the containing sentence only
            # for this explicit hypothesis pattern.
            sentence = mention.source_text[mention.sentence_span[0]:mention.sentence_span[1]]
            if (re.search(r"\b(?:assume|suppose|imagine|treat|consider|"
                          r"supposons|imaginons|admettons|consid[ée]rons|consid[ée]rez)\b"
                          r"[^.!?;]{0,120}\b(?:it\s+is|we\s+are|nous\s+sommes|on\s+est|"
                          r"il\s+est|ce\s+serait|were|was|[ée]tait)\b",
                          sentence, re.IGNORECASE)
                    and _ANALYSIS_VERB_RE.search(sentence)
                    and _ANALYSIS_TARGET_RE.search(sentence)):
                return True
        if _PASSIVE_REQUEST_RE.search(local) or _PURPOSE_REQUEST_RE.search(local):
            return True
        if _MODAL_REQUEST_RE.search(local) and _ANALYSIS_VERB_RE.search(local):
            return True
        if _FRAME_CONTROL_VERB_RE.search(local) and _FRAME_NOUN_RE.search(local):
            return True
        if (_FRAME_CONTROL_VERB_RE.search(local) and _ANALYSIS_NOUN_RE.search(local)
                and _FRAME_RELATION_RE.search(local)):
            return True
        # Predicate may be before or after the date (« as of <d>, analyze »),
        # but it must be part of a classified request act, not a nominal.
        if act.requests_analysis:
            if _ANALYSIS_TARGET_RE.search(local) or _FRAME_RELATION_RE.search(local):
                return True
        if (_FRAME_NOUN_RE.search(local) and not _NEGATED_FIELD_RE.search(local)
                and act.kind in (ACT_IMPERATIVE, ACT_MODAL, ACT_PURPOSE,
                                 ACT_PASSIVE, ACT_QUESTION, ACT_HYPOTHESIS)):
            return True
        # « Use data available as of <date> » and equivalents.
        if re.search(
            r"\b(?:use|using|base|based|utilis(?:e|ez|er)|base[sz]?|"
            r"prenez|retenez)\b[^.!?;]{0,120}\b(?:data|information|donn[ée]es|"
            r"informations|position|situation)\b",
            local, re.IGNORECASE):
            return True
        # Future state questions/requests.
        if re.search(r"\b(?:will|would)\s+(?:look|stand|become|perform)|"
                     r"\b(?:deviendra|situation\s+future|simul)",
                     local, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def _is_leading_control_field(mention: DateMention) -> bool:
        source = mention.source_text
        line_start = source.rfind("\n", 0, mention.span[0]) + 1
        line_end = source.find("\n", mention.span[1])
        if line_end < 0:
            line_end = len(source)
        line = source[line_start:line_end]
        stripped = line.lstrip()
        if len(line) - len(stripped) >= 4 or stripped.startswith((">", "<", "|", "```", "~~~", "-----")):
            return False
        if not _CONTROL_FIELD_RE.match(stripped) or _NEGATED_FIELD_RE.search(stripped):
            return False
        for prev in source[:line_start].splitlines():
            if not prev.strip():
                continue
            # Only other temporal-control fields may precede it.
            if not _CONTROL_FIELD_RE.match(prev.strip()):
                return False
        return True

    @staticmethod
    def _sentence_mentions(mention: DateMention,
                           mentions: Sequence[DateMention]) -> List[DateMention]:
        return [m for m in mentions if m.sentence_span == mention.sentence_span]

    def _range_role(self, mention: DateMention,
                    mentions: Sequence[DateMention]) -> Optional[str]:
        peers = sorted(self._sentence_mentions(mention, mentions),
                       key=lambda m: m.span)
        if len(peers) < 2:
            return None
        sentence = mention.source_text[mention.sentence_span[0]:mention.sentence_span[1]]
        if not _RANGE_RE.search(sentence):
            return None

        # A mention participates in a range only when it is one of the two
        # endpoints connected by the local from/between…to/and structure.
        # A later independent analysis date in the same sentence must not be
        # swallowed by an earlier performance range.
        idx = next((i for i, m in enumerate(peers) if m.span == mention.span), -1)
        if idx < 0:
            return None
        participates = False
        sentence_start = mention.sentence_span[0]
        source = mention.source_text
        start_re = re.compile(r"\b(from|between|du|de|entre)\b", re.IGNORECASE)
        for left_i in range(len(peers) - 1):
            left, right = peers[left_i], peers[left_i + 1]
            prefix_full = source[sentence_start:left.span[0]]
            starts = list(start_re.finditer(prefix_full))
            if not starts:
                continue
            start_match = starts[-1]
            start_abs_end = sentence_start + start_match.end()
            # The range starter must govern this left endpoint. If another
            # temporal mention occurs after the starter and before ``left``,
            # then ``left`` is already the right endpoint of a previous range.
            if any(m.span[0] >= start_abs_end and m.span[1] <= left.span[0]
                   for m in peers if m is not left):
                continue
            between = source[left.span[1]:right.span[0]]
            starter = start_match.group(1).casefold()
            if starter in ("between", "entre"):
                end_ok = bool(re.search(r"\b(?:and|et)\b", between, re.IGNORECASE))
            else:
                end_ok = bool(re.search(r"\b(?:to|through|until|au|[àa])\b",
                                        between, re.IGNORECASE))
            if end_ok and idx in (left_i, left_i + 1):
                participates = True
                break
        if not participates:
            return None

        # Performance/period ranges are business scope. A requested company
        # range is not a single snapshot and must fail closed (both endpoints
        # remain ANALYSIS_FRAME; the aggregator returns AMBIGUOUS).
        range_text = mention.source_text[peers[max(0, idx - 1)].clause_span[0]:
                                         peers[min(len(peers) - 1, idx + 1)].clause_span[1]]
        if re.search(r"\b(?:performance|period|p[ée]riode|FY|Q[1-4]|T[1-4]|"
                     r"revenue|sales|chiffre\s+d['’]affaires)\b",
                     range_text, re.IGNORECASE):
            return COMPARISON_OR_PERIOD
        if (_ANALYSIS_VERB_RE.search(sentence)
                and _ANALYSIS_TARGET_RE.search(sentence)):
            return ANALYSIS_FRAME
        return COMPARISON_OR_PERIOD

    def _is_comparison_mention(self, mention: DateMention,
                               mentions: Sequence[DateMention]) -> bool:
        peers = self._sentence_mentions(mention, mentions)
        sentence = mention.source_text[mention.sentence_span[0]:mention.sentence_span[1]]
        if len(peers) >= 2 and re.match(r"\s*(?:compare|comparer|comparison)",
                                        sentence, re.IGNORECASE):
            return True
        before = mention.source_text[mention.sentence_span[0]:mention.span[0]]
        if re.search(r"\b(?:compared\s+(?:with|to)|versus|vs\.?|par\s+rapport\s+[àa])\s*$",
                     before, re.IGNORECASE):
            return True
        return False


class CompositionAggregator:
    """Aggregate mention-local roles into one rank-3 intent."""

    @staticmethod
    def aggregate(text: str, mentions: Sequence[DateMention],
                  relations: Sequence[str]) -> LegacyIntent:
        frames = [m for m, r in zip(mentions, relations) if r == ANALYSIS_FRAME]
        if not frames:
            return LegacyIntent(mentions=tuple(mentions))

        # A frame alternative followed by an invalid/placeholder date remains
        # ambiguous even when the second fragment has no repeated predicate.
        ordered_all = sorted(mentions, key=lambda m: m.span)
        for left, right in zip(ordered_all, ordered_all[1:]):
            between = text[left.span[1]:right.span[0]]
            if left in frames and re.search(r"\b(?:or|ou)\b", between, re.I):
                # Once an explicit frame is followed by an alternative date,
                # the request no longer designates one snapshot—even if the
                # second branch omits the repeated analysis predicate.
                reason = ("alternative de cadre contenant une date indéterminée"
                          if not right.is_usable
                          else "alternative de cadre contenant plusieurs dates")
                return LegacyIntent(
                    AMBIGUOUS, None, left.raw, left.span, reason,
                    ANALYSIS_FRAME, tuple(mentions))

        # Alternative or range between frame mentions makes the request
        # ambiguous as a single snapshot.
        if CompositionAggregator._frame_composition_is_ambiguous(text, frames):
            first = frames[0]
            return LegacyIntent(
                AMBIGUOUS, None, first.raw, first.span,
                "cadre d'analyse composé (alternative ou plage)",
                ANALYSIS_FRAME, tuple(mentions))

        usable = [m for m in frames if m.is_usable]
        unresolved = [m for m in frames if not m.is_usable]
        distinct = {m.parsed_value for m in usable}
        if len(distinct) > 1:
            first = frames[0]
            return LegacyIntent(
                AMBIGUOUS, None, first.raw, first.span,
                "plusieurs dates de cadre incompatibles : "
                + ", ".join(sorted(x for x in distinct if x)),
                ANALYSIS_FRAME, tuple(mentions))
        if unresolved and usable:
            first = frames[0]
            return LegacyIntent(
                AMBIGUOUS, None, first.raw, first.span,
                "cadre d'analyse mêlant date valide et valeur indéterminée",
                ANALYSIS_FRAME, tuple(mentions))
        if usable:
            m = usable[0]
            return LegacyIntent(CANDIDATE, m.parsed_value, m.raw, m.span,
                                "date de cadre d'analyse", ANALYSIS_FRAME,
                                tuple(mentions))
        m = frames[0]
        why = ("date de cadre d'analyse indéterminée"
               if m.parse_status == "PLACEHOLDER"
               else "date de cadre d'analyse illisible")
        return LegacyIntent(AMBIGUOUS, None, m.raw, m.span, why,
                            ANALYSIS_FRAME, tuple(mentions))

    @staticmethod
    def _frame_composition_is_ambiguous(text: str,
                                        frames: Sequence[DateMention]) -> bool:
        if len(frames) < 2:
            return False
        ordered = sorted(frames, key=lambda m: m.span)
        for left, right in zip(ordered, ordered[1:]):
            between = text[left.span[1]:right.span[0]]
            if re.search(r"\b(?:or|ou)\b", between, re.IGNORECASE):
                return True
            if re.search(r"\b(?:to|through|until|au|[àa])\b", between,
                         re.IGNORECASE) and re.search(
                             r"\b(?:from|between|du|de|entre)\b",
                             text[max(0, left.span[0] - 40):left.span[0]],
                             re.IGNORECASE):
                return True
        return False


class LegacyTemporalIntentDetector:
    """Pure detector: no request-specific state lives on the instance."""

    def __init__(self) -> None:
        self._normalizer = TemporalExpressionNormalizer()
        self._attachments = TemporalAttachmentClassifier()
        self._aggregator = CompositionAggregator()

    def _mentions(self, text: str,
                  run_date: Optional[str] = None) -> List[DateMention]:
        raw = self._normalizer.extract(text, run_date)
        if not raw:
            return []
        spans = [x.span for x in raw]
        sentence_bounds = self._sentence_bounds(text, spans)
        out: List[DateMention] = []
        for expression in raw:
            sa, sb = next((a, b) for a, b in sentence_bounds
                          if a <= expression.span[0] < b)
            sentence_exprs = [x.span for x in raw if sa <= x.span[0] < sb]
            wa, wb, coord = self._window_for(text, sa, sb,
                                             expression.span, sentence_exprs)
            out.append(DateMention(
                raw=expression.raw, parsed_value=expression.parsed_value,
                parse_status=expression.parse_status, span=expression.span,
                local_clause=text[wa:wb], clause_span=(wa, wb),
                opening_coordinator=coord, source_text=text,
                expression_kind=expression.kind, sentence_span=(sa, sb)))
        return out

    @staticmethod
    def _sentence_bounds(text: str,
                         protected: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
        bounds: List[Tuple[int, int]] = []
        start = 0
        for i, ch in enumerate(text):
            if ch not in _SENTENCE_DELIMS:
                continue
            if any(a <= i < b for a, b in protected):
                continue
            if text[start:i].strip():
                bounds.append((start, i))
            start = i + 1
        if text[start:].strip():
            bounds.append((start, len(text)))
        return bounds or [(0, len(text))]

    @staticmethod
    def _window_for(text: str, sa: int, sb: int,
                    span: Tuple[int, int],
                    sentence_exprs: Sequence[Tuple[int, int]]) -> Tuple[int, int, str]:
        # Absolute connector positions — never accumulated relative offsets.
        connectors = [(sa + m.start(), sa + m.end(), m.group(0))
                      for m in _CONNECTOR_RE.finditer(text[sa:sb])]
        s, e = span
        lo, hi, opening = sa, sb, ""
        for a, b, raw in connectors:
            if b <= s:
                lo, opening = b, raw.strip().casefold()
            elif a >= e:
                hi = a
                break
        return lo, hi, opening

    # Kept for historical tests/audit probes.
    @staticmethod
    def _local_windows(text, a, b, inner):
        return [LegacyTemporalIntentDetector._window_for(text, a, b, span, inner)
                for span in inner]

    def classify(self, mention: DateMention,
                 run_date: Optional[str] = None,
                 mentions: Optional[Sequence[DateMention]] = None) -> str:
        all_mentions = mentions or self._mentions(mention.source_text or
                                                  mention.local_clause)
        # When a historical test passes a mention object obtained from this
        # detector, locate it by span in the freshly supplied list.
        target = next((m for m in all_mentions if m.span == mention.span), mention)
        return self._attachments.classify(target, all_mentions)

    def detect(self, text: str,
               run_date: Optional[str] = None) -> LegacyIntent:
        if not text or not text.strip():
            return LegacyIntent()
        mentions = self._mentions(text)
        if not mentions:
            return LegacyIntent()
        relations = [self._attachments.classify(m, mentions) for m in mentions]
        return self._aggregator.aggregate(text, mentions, relations)


# Kept for audit monkeypatch compatibility. The instance is stateless.
_DETECTOR = LegacyTemporalIntentDetector()


def detect_legacy_temporal_intent(text: str,
                                  run_date: Optional[str] = None) -> LegacyIntent:
    """Public rank-3 detector. Exceptions deliberately propagate so the
    TemporalContext boundary can convert them to BLOCKED_ERROR."""
    return _DETECTOR.detect(text, run_date)


__all__ = [
    "NONE", "CANDIDATE", "AMBIGUOUS", "ERROR",
    "ANALYSIS_FRAME", "DEADLINE_OR_MILESTONE", "DOCUMENT_DATE",
    "BUSINESS_MEASUREMENT", "HISTORICAL_EVENT", "COMPARISON_OR_PERIOD",
    "UNKNOWN", "DateMention", "LegacyIntent", "LegacyTemporalIntentDetector",
    "TemporalExpressionNormalizer", "DirectiveActClassifier",
    "TemporalAttachmentClassifier", "CompositionAggregator",
    "detect_legacy_temporal_intent", "_DETECTOR",
]
