# -*- coding: utf-8 -*-
"""B.1.3.28 — Executive Evidence Guard, hardened candidate.

Contract:
- no executive number may be more affirmative than its evidence;
- the guard consumes the governed facts table when available, then falls back
  to the rendered CR;
- it applies to the real corporate deck surfaces, not only the legacy ``marche``
  payload;
- accounting actions based on unconfirmed amounts are rewritten as
  verify -> arbitrate -> act if confirmed;
- the helper remains deterministic and network-free.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

try:
    from patches.fact_identity import canonical_metric_id as _canonical_metric_id
except Exception:  # pragma: no cover - fail-open import for isolated tooling
    def _canonical_metric_id(label: Optional[str]) -> str:
        return "OTHER"

# Strong badges only.  A bare "estimé/estimated" is intentionally not enough.
_ALREADY = re.compile(
    r"^\s*≈|\bESTIM\.|\[ESTIM[- .]|\[AI EST|OBJECTIF PROPOS|PROPOSED TARGET|"
    r"Non disponible|Not available|à vérifier|to verify|Instable entre runs|"
    r"Unstable across runs|si confirmé|if confirmed",
    re.I,
)
_FACT_MARKER = re.compile(r"✅\s*(?:FAIT|FACT)|\|\s*(?:FAIT|FACT)\s*\|", re.I)
_WEAK_MARKER = re.compile(
    r"À\s*VÉRIFIER|TO\s*VERIFY|ESTIM|HYPOTH|NON\s*SOURC|UNSOURC|"
    r"HORS\s*PÉRIMÈTRE|OUT\s*OF\s*PERIMETER|non[- ]board[- ]safe",
    re.I,
)

_MINUS_CHARS = "-−‒–—﹣－"
_NUM = r"[+\-−‒–—﹣－]?\d+(?:[ \u00a0.,'’]\d+)*"
_RANGE = rf"(?:\s*[-–]\s*{_NUM})?"
# Major ISO-4217 currencies encountered by global corporate decks.  This is
# reference data, not company-specific logic.  Unsupported currencies used to
# bypass the guard entirely because no amount token was extracted.
_CURRENCY_CODES = (
    "GBP", "EUR", "USD", "CHF", "NOK", "SEK", "DKK", "CNY", "RMB",
    "JPY", "CAD", "AUD", "NZD", "HKD", "SGD", "INR", "KRW", "BRL",
    "MXN", "ZAR", "PLN", "CZK", "HUF", "TRY", "AED", "SAR", "CNH",
)
_CURRENCY_RX = "|".join(_CURRENCY_CODES) + r"|HK\$|NZ\$|R\$|A\$|C\$|S\$|£|€|₹|₩|¥|\$"
_PREFIX_RE = re.compile(
    rf"(?P<cur>{_CURRENCY_RX})\s*"
    rf"(?P<num>{_NUM})(?P<rng>{_RANGE})\s*"
    rf"(?P<scale>k|m|bn|b|mds?|million(?:s)?|billion(?:s)?|milliard(?:s)?)?",
    re.I,
)
_SUFFIX_CURRENCY_RE = re.compile(
    rf"(?P<num>{_NUM})(?P<rng>{_RANGE})\s*"
    rf"(?P<scale>k|m|bn|b|mds?|million(?:s)?|billion(?:s)?|milliard(?:s)?)?\s*"
    rf"(?P<cur>{_CURRENCY_RX})",
    re.I,
)
_SUFFIX_UNIT_RE = re.compile(
    rf"(?P<num>{_NUM})(?P<rng>{_RANGE})\s*"
    r"(?P<unit>k€|K€|M€|m€|Md\s*€|Mds\s*€|k£|K£|M£|m£|%|bps?|ETP|FTE|"
    r"salari(?:é|e)s?|collaborateurs?|employees?|people|x)",
    re.I,
)

# Explicit accounting-parentheses formats that the generic patterns cannot
# consume (e.g. ``GBP (47)m``).  They are always negative by convention.
_PAREN_PREFIX_RE = re.compile(
    rf"(?P<cur>{_CURRENCY_RX})\s*\(\s*(?P<num>{_NUM})\s*\)\s*"
    rf"(?P<scale>k|m|bn|b|mds?|million(?:s)?|billion(?:s)?|milliard(?:s)?)?",
    re.I,
)
_PAREN_SUFFIX_CURRENCY_RE = re.compile(
    rf"\(\s*(?P<num>{_NUM})\s*\)\s*"
    rf"(?P<scale>k|m|bn|b|mds?|million(?:s)?|billion(?:s)?|milliard(?:s)?)?\s*"
    rf"(?P<cur>{_CURRENCY_RX})",
    re.I,
)
_SCALE_ONLY_RE = re.compile(
    rf"(?P<num>{_NUM})(?P<rng>{_RANGE})\s*"
    rf"(?P<scale>k|m|bn|b|mds?|million(?:s)?|billion(?:s)?|milliard(?:s)?)(?![A-Za-zÀ-ÿ²³])",
    re.I,
)

# Period tokens are masked with same-length spaces before amount extraction.
# This prevents ``FY2026 H1 100 M€`` and ``FY2025/26 100 M€`` from becoming
# respectively ``1 100 M€`` and ``26 100 M€`` while preserving source spans.
_ESTIMATE_PERIOD_RE = re.compile(
    r"\b(?P<fy>FY\s*)?[\'’]?(?P<year>[0-9]{2}|[12][0-9]{3})\s*(?P<flag>[EFP])\b", re.I)
_HALF_PREFIX_RE = re.compile(
    r"\b([12])H\s*(?:FY\s*)?[\'’]?([0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I)
_QUARTER_PREFIX_RE = re.compile(
    r"\b([1-4])Q\s*(?:FY\s*)?[\'’]?([0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I)


_AMOUNT_PERIOD_MASK_PATTERNS = (
    _ESTIMATE_PERIOD_RE,
    _HALF_PREFIX_RE,
    _QUARTER_PREFIX_RE,
    re.compile(r"\b(?:H[12]|Q[1-4])\s*(?:FY\s*)?['’]?(?:[0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I),
    re.compile(r"\b(?:FY\s*)?(?:[0-9]{2}|[12][0-9]{3})\s*(?:H[12]|Q[1-4])\b", re.I),
    re.compile(r"\b(?:LTM|YTD|TTM|NTM)\s*(?:FY\s*)?['’]?(?:[0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I),
    re.compile(r"\b(?:FY\s*)?(?:[0-9]{2}|[12][0-9]{3})\s*(?:LTM|YTD|TTM|NTM)\b", re.I),
    re.compile(r"\bFY\s*(?:[0-9]{2}|[12][0-9]{3})\s*[/\-]\s*(?:[0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I),
    re.compile(r"\bFY\s*(?:[0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I),
    re.compile(r"\b(?:H[12]|Q[1-4])\b", re.I),
)

_CURRENCY = {
    "£": "GBP", "$": "USD", "€": "EUR", "RMB": "CNY", "CNH": "CNY",
    "R$": "BRL", "A$": "AUD", "C$": "CAD", "HK$": "HKD",
    "S$": "SGD", "NZ$": "NZD", "₹": "INR", "₩": "KRW",
    # The yen/yuan symbol is jurisdiction-ambiguous; keep it isolated rather
    # than letting it borrow an explicit JPY or CNY fact.
    "¥": "JPY_OR_CNY",
}
_SCALE = {
    "": "", "k": "K", "m": "M", "b": "BN", "bn": "BN",
    "million": "M", "millions": "M", "billion": "BN", "billions": "BN",
    "milliard": "BN", "milliards": "BN", "md": "BN", "mds": "BN",
}

# B.1.3.29 audit candidate — amount equality is not evidence equality.
# These generic metric families are used only to prevent a fact about one
# metric (e.g. GBP 100m savings) from certifying another executive claim
# carrying the same amount (e.g. GBP 100m marketing investment).
_METRIC_FAMILY_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:announced\s+)?savings?\b|\b(?:cost|co[ûu]t)s?\s+reduction\b|\b[ée]conomies?\b", re.I), "SAVINGS"),
    (re.compile(r"\bbudget\s+marketing\b|\bmarketing\s+(?:budget|spend|investment|envelope)\b|\b(?:invest(?:ment|ir|issement|issements)?|spend)\b[^.;|]{0,40}\bmarketing\b", re.I), "MARKETING_SPEND"),
    (re.compile(r"\bcapex\b|\bcapital expenditure\b|\binvest(?:ment|ir|issement|issements)?\b", re.I), "CAPEX"),
    (re.compile(r"\bdividend(?:e|s)?\b", re.I), "DIVIDEND"),
    (re.compile(r"\bengagements?\s+retraite\b|\bpension\b|\bretirement\b|\bprovision(?:ner|ing)?\b", re.I), "PENSION_PROVISION"),
    (re.compile(r"\bbfr\b|\bworking capital\b", re.I), "WORKING_CAPITAL"),
    (re.compile(r"\bstocks?\b|\binventory\b", re.I), "STOCKS"),
    (re.compile(r"\bpart(?:s)? de march[ée]\b|\bmarket share\b|\bpdm\b", re.I), "MARKET_SHARE"),
    (re.compile(r"\bca\b|\bchiffre(?:s)? d['’]affaires?\b|\brevenue\b|\bturnover\b|\bsales\b|\bventes?\b", re.I), "REVENUE"),
    (re.compile(r"\brn\b|\br[ée]sultat net\b|\bnet (?:income|loss)\b", re.I), "NET_INCOME"),
    (re.compile(r"\b(?:budget|spend|d[ée]penses?|investissements?)\s+(?:de\s+)?r\s*&\s*d\b|\br\s*&\s*d\s+(?:budget|spend|investment)\b|\brecherche\s+et\s+d[ée]veloppement\b", re.I), "RND_SPEND"),
    (re.compile(r"\b(?:restructuring|restructuration)\s+(?:costs?|charges?|co[ûu]ts?)\b|\b(?:costs?|charges?|co[ûu]ts?)\s+(?:de\s+)?restructur(?:ing|ation)\b", re.I), "RESTRUCTURING_COSTS"),
    (re.compile(r"\bsg\s*&\s*a\b|\boperating expenses?\b|\bopex\b|\bcharges? d['’]exploitation\b|\bfrais d['’]exploitation\b", re.I), "OPERATING_EXPENSES"),
    (re.compile(r"\bliquidit[ée]s?\b|\bliquidity\b", re.I), "CASH"),
    (re.compile(r"\bdebt\b|\bdette\b", re.I), "FINANCIAL_DEBT"),
    (re.compile(r"\btaille (?:du |de )?march[ée]\b|\bmarket size\b", re.I), "MARKET_SIZE"),
    (re.compile(
        r"\bcroissance\b|\bgrowth\b|\bdecline\b|\bbaisse\b|\bhausse\b|"
        r"\b(?:increase(?:d)?|decrease(?:d)?|reduce(?:d)?|rise|rose|fall|fell|grow|grew|decline(?:d)?)\s+(?:by|of)\b|"
        r"\b(?:increase|decrease|reduction|rise|fall|decline|variation|progression|recul|r[ée]duction)\s+(?:of|de)\b|"
        r"\b(?:augment[ée]?|diminu[ée]?|r[ée]duit(?:e)?)\s+de\b",
        re.I), "GROWTH"),
    (re.compile(r"\bmarge (?:op[ée]rationnelle|d['’]exploitation)\b|\boperating (?:profit )?margin\b", re.I), "OPERATING_MARGIN"),
    (re.compile(r"\br[ée]sultat op[ée]rationnel\b|\boperating (?:profit|loss|income)\b", re.I), "OPERATING_INCOME"),
)

_FIELD_METRIC_HINTS = {
    "ca": "REVENUE",
    "croissance": "REVENUE GROWTH",
    "effectif": "HEADCOUNT",
    "taille": "MARKET_SIZE",
    "missions": "MISSIONS",
}

# B.1.3.30 audit — only known semantic families may constrain evidence.
# Arbitrary renderer keys such as ``impact`` or ``points`` must not become
# synthetic metric families.
_KNOWN_METRIC_FAMILIES = {
    "REVENUE", "GROWTH", "HEADCOUNT", "EBITDA", "EBIT", "NET_INCOME",
    "GROSS_MARGIN", "EBITDA_MARGIN", "OPERATING_MARGIN",
    "OPERATING_INCOME", "CASH", "GROSS_DEBT", "NET_DEBT",
    "FINANCIAL_DEBT", "EQUITY", "FREE_CASH_FLOW", "CAPACITY", "STOCKS",
    "SAVINGS", "CAPEX", "MARKETING_SPEND", "DIVIDEND",
    "PENSION_PROVISION", "WORKING_CAPITAL", "MARKET_SHARE", "MARKET_SIZE",
    "MISSIONS", "RND_SPEND", "RESTRUCTURING_COSTS", "OPERATING_EXPENSES",
}
_BASE_METRIC_FAMILIES = _KNOWN_METRIC_FAMILIES - {"GROWTH"}
_UNTYPED_VALUE_METRIC = "__UNTYPED_VALUE__"

# A badge located in one sub-clause must not exempt every other amount in the
# same sentence.  Only genuinely sentence-level badges are treated as global.
_GLOBAL_ALREADY = re.compile(
    r"^\s*≈|^\s*\[(?:ESTIM|AI EST)[^\]]*\]|"
    r"\[(?:ESTIM|AI EST)[^\]]*\]\s*$|"
    r"(?:—|-)\s*(?:estim(?:ation)?\.?|estimate|à vérifier|to verify)\s*$|"
    r"^\s*(?:Faire confirmer par le DAF / expert-comptable|Have the CFO/auditor confirm)\b|"
    r"\b(?:si confirmé|if confirmed)\b\s*[.:]?\s*$",
    re.I,
)
_CLAUSE_BREAK_RE = re.compile(
    r"(?:\n+|[;|•]+|\s+[—]\s+|,\s+(?=[A-Za-zÀ-ÿ])|\s+/\s+|"
    r"\s+\b(?:and|et|but|mais|while|whereas|puis|then)\b\s+)",
    re.I,
)

# Period/intent guards.  Evidence equality is not only amount+metric: a
# historical FY25 revenue does not certify an FY27 target carrying the same
# amount, and a historical margin does not certify an instruction to maintain
# that margin in the future.
_FY_RE = re.compile(r"\bFY\s*([0-9]{2}|[12][0-9]{3})\b", re.I)
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
_FORWARD_RE = re.compile(
    r"\b(?:target|targeting|objective|goal|aim|guidance|forecast|expected|ntm|"
    r"run[- ]?rate|annuali[sz](?:ed|ation)|annualis[ée]e?|"
    r"announced|proposed|plan(?:ned)?|maintain|sustain|preserve|protect|deliver|achieve|complete|finali[sz]e|reali[sz]e|"
    r"reach|grow\s+to|increase\s+to|reduce\s+to|by\s+(?:FY\s*)?\d{2,4}|"
    r"objectif|cible|viser|vis[ée]|annonc[ée]|prévision|pr[ée]vu|attendu|propos[ée]|"
    r"maintenir|soutenir|pr[ée]server|prot[ée]ger|livrer|atteindre|achever|finaliser|r[ée]aliser|porter\s+[àa]|"
    r"d['’]ici|[àa]\s+horizon|(?:FY\s*)?(?:[0-9]{2}|[12][0-9]{3})[EFP])\b",
    re.I,
)
_FORECAST_PERIOD_TOKEN_RE = re.compile(
    r"\b(?:FY\s*)?(?:[0-9]{2}|[12][0-9]{3})\s*[EFP]\b|"
    r"\b(?:[12]H|[1-4]Q|H[12]|Q[1-4])\s*(?:FY\s*)?['’]?(?:[0-9]{2}|[12][0-9]{3})\s*[EFP]\b|"
    r"\bFY\s*(?:[0-9]{2}|[12][0-9]{3})\s*[/\-]\s*(?:[0-9]{2}|[12][0-9]{3})\s*[EFP]\b",
    re.I,
)
_ROW_FORWARD_RE = re.compile(
    r"\b(?:announc(?:ed|ement)?|target|objective|goal|guidance|forecast|ntm|"
    r"run[- ]?rate|annuali[sz](?:ed|ation)|annualis[ée]e?|(?:FY\s*)?(?:[0-9]{2}|[12][0-9]{3})[EFP]|"
    r"expected|planned|plan|objectif|cible|annonc[ée]|pr[ée]vision|pr[ée]vu)\b|"
    r"\bFY\s*\d{2,4}E\b",
    re.I,
)

# Sub-periods are material evidence dimensions.  H1 FY26, Q1 FY26 and FY26
# are not interchangeable even though they share the same calendar year.
_HALF_RE = re.compile(r"\b(H[12])\s*(?:FY\s*)?['’]?([0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I)
_QUARTER_RE = re.compile(r"\b(Q[1-4])\s*(?:FY\s*)?['’]?([0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I)
_ROLLING_RE = re.compile(r"\b(LTM|YTD|TTM|NTM)\s*(?:FY\s*)?['’]?([0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I)
_HALF_AFTER_RE = re.compile(r"\b(?:FY\s*)?([0-9]{2}|[12][0-9]{3})\s*(H[12])(?:\s*[EFP])?\b", re.I)
_QUARTER_AFTER_RE = re.compile(r"\b(?:FY\s*)?([0-9]{2}|[12][0-9]{3})\s*(Q[1-4])(?:\s*[EFP])?\b", re.I)
_ROLLING_AFTER_RE = re.compile(r"\b(?:FY\s*)?([0-9]{2}|[12][0-9]{3})\s*(LTM|YTD|TTM|NTM)(?:\s*[EFP])?\b", re.I)
_FY_RANGE_RE = re.compile(r"\bFY\s*([0-9]{2}|[12][0-9]{3})\s*[/\-]\s*([0-9]{2}|[12][0-9]{3})(?:\s*[EFP])?\b", re.I)
_YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2})\s*/\s*([0-9]{2}|[12][0-9]{3})\b")
_HALF_ONLY_RE = re.compile(r"\b(H[12])\b", re.I)
_QUARTER_ONLY_RE = re.compile(r"\b(Q[1-4])\b", re.I)
_ROLLING_ONLY_RE = re.compile(r"\b(LTM|TTM|NTM|YTD|QTD|MTD)\b", re.I)

# Lexical polarity closes the remaining same-metric collision: a loss is not
# a profit, and a decline is not growth, even when the displayed magnitude is
# identical and the minus sign is expressed only in words.
_LOSS_RE = re.compile(r"\b(?:loss|losses|perte|pertes|déficit|deficit|negative|négatif|négative|DR)\b", re.I)
_PROFIT_RE = re.compile(r"\b(?:profit|profits|income|bénéfice|benefice|positive|positif|positive|CR)\b", re.I)
_DOWN_RE = re.compile(r"\b(?:decline|declined|decrease|decreased|reduce|reduced|down|drop|dropped|fall|fell|baisse|recul|diminution|contraction)\b", re.I)
_UP_RE = re.compile(r"\b(?:growth|grow|grew|increase|increased|up|rise|rose|hausse|progression|amélioration|amelioration)\b", re.I)


# B.1.3.35 adversarial candidate — semantic qualifiers are evidence dimensions.
# Amount + canonical metric is still insufficient when a claim changes the
# reporting basis (adjusted vs reported), temporal basis (run-rate/TTM), unit
# basis (per employee/store/share) or business segment/category.
_BASIS_QUALIFIER_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\badjusted\b|\bajust[ée]\b", re.I), "BASIS:ADJUSTED"),
    (re.compile(r"\breported\b|\bstatutory\b|\bpubli[ée]\b", re.I), "BASIS:REPORTED"),
    (re.compile(r"\bunderlying\b|\bsous[- ]jacent\b", re.I), "BASIS:UNDERLYING"),
    (re.compile(r"\borganic\b|\borganique\b", re.I), "BASIS:ORGANIC"),
    (re.compile(r"\bcomparable\b|\blike[- ]for[- ]like\b|\bLFL\b", re.I), "BASIS:COMPARABLE"),
    (re.compile(r"\bconstant (?:exchange )?rates?\b|\bconstant currency\b|\bCER\b|\bdevises? constantes?\b", re.I), "BASIS:CONSTANT_CURRENCY"),
    (re.compile(r"\bnon[- ]GAAP\b", re.I), "BASIS:NON_GAAP"),
)
_TIME_BASIS_QUALIFIER_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brun[- ]?rate\b|\brythme annualis[ée]\b", re.I), "TIME:RUN_RATE"),
    (re.compile(r"\bannuali[sz](?:ed|ation)\b|\bannualis[ée]e?\b", re.I), "TIME:ANNUALIZED"),
    (re.compile(r"\bTTM\b", re.I), "TIME:TTM"),
    (re.compile(r"\bLTM\b", re.I), "TIME:LTM"),
    (re.compile(r"\bNTM\b", re.I), "TIME:NTM"),
    (re.compile(r"\bYTD\b", re.I), "TIME:YTD"),
    (re.compile(r"\bQTD\b", re.I), "TIME:QTD"),
    (re.compile(r"\bMTD\b", re.I), "TIME:MTD"),
)
_PER_UNIT_RE = re.compile(
    r"\b(?:per|par)\s+(?P<unit>employee|fte|head|store|shop|share|customer|client|"
    r"unit|site|machine|user|subscriber|sqm|m2|m²|salari[ée]|collaborateur|magasin|action|unit[ée])s?\b",
    re.I,
)
_SEGMENT_METRIC = (
    r"(?:revenue|sales|turnover|chiffre(?:s)? d['’]affaires?|headcount|effectif|"
    r"operating profit|operating income|r[ée]sultat op[ée]rationnel|net income|"
    r"r[ée]sultat net|ebitda|gross margin|marge brute)"
)
_SEGMENT_BEFORE_RE = re.compile(
    rf"\b(?P<seg>[A-Za-zÀ-ÿ][\wÀ-ÿ'’.-]*(?:\s+[A-Za-zÀ-ÿ][\wÀ-ÿ'’.-]*){{0,2}})\s+{_SEGMENT_METRIC}\b",
    re.I,
)
_SEGMENT_AFTER_RE = re.compile(
    rf"\b{_SEGMENT_METRIC}\s+(?:in|from|for|de|du|des|en)\s+"
    r"(?P<seg>[A-Za-zÀ-ÿ][\wÀ-ÿ'’.-]*(?:\s+[A-Za-zÀ-ÿ][\wÀ-ÿ'’.-]*){0,2})\b",
    re.I,
)
# B.1.3.37 — ordre suffixé français SANS préposition (« Revenue France »,
# « CA Île-de-France », « Chiffre d'affaires Allemagne », « Sales Outerwear »).
# Racine (sonde Claude 3.35→3.36, contresignée ChatGPT) : _SEGMENT_AFTER_RE
# exigeait une préposition ; le qualificateur en position post-métrique nue
# n'était pas extrait → fait groupe et claim France partageaient un ensemble
# vide de qualificateurs → fausse certification directe. Garde-fous : le
# premier caractère du qualificateur doit être une MAJUSCULE (les verbes
# « increased/expected » restent hors capture), chaque token exclut les
# marqueurs de période (FY…, années, H1/Q1…), la capture est bornée par une
# période, un montant, une ponctuation ou la fin de proposition, et les codes
# devise sont filtrés post-capture (liste ISO, pas de liste d'entreprises).
# ChatGPT audit candidate after B.1.3.37 — same root, boundary completion.
# The first implementation required initial capitals and accepted only a narrow
# punctuation set.  Consequently common rendered forms such as
# ``Revenue France — FY2024 100 M€``, ``CA france FY2024 100 M€`` or
# ``CA Île de France FY2024 100 M€`` still lost their analytical qualifier and
# could borrow a group fact.  The suffix phrase is now parsed conservatively,
# case-insensitively, with lowercase connectors and common deck separators.
# False positives only demote a claim to an estimate; false certification is
# the forbidden failure mode.
_SEG_SUFFIX_TOKEN = r"[A-Za-zÀ-ÿ][\wÀ-ÿ'’.-]*"
_SEGMENT_SUFFIX_RE = re.compile(
    rf"\b(?:(?:{_SEGMENT_METRIC})|CA|RN)\s+"
    rf"(?P<seg>{_SEG_SUFFIX_TOKEN}(?:\s+{_SEG_SUFFIX_TOKEN}){{0,5}}?)"
    r"(?=\s*(?:"
    r"(?:FY\s*)?['’]?(?:[0-9]{2}|[12][0-9]{3})(?:\s*[/\-]\s*(?:[0-9]{2}|[12][0-9]{3}))?(?:\s*[EFP])?\b|"
    r"(?:H[12]|Q[1-4]|LTM|YTD|TTM|NTM)\b|(?:[12]H|[1-4]Q)[0-9]{2,4}[EFP]?\b|"
    r"[+\-−‒–—﹣－]?(?:\s*(?:GBP|EUR|USD|CHF|NOK|SEK|DKK|CNY|CNH|RMB|JPY|CAD|AUD|NZD|HKD|SGD|INR|KRW|BRL|MXN|ZAR|PLN|CZK|HUF|TRY|AED|SAR|HK\$|NZ\$|R\$|A\$|C\$|S\$|£|€|₹|₩|¥|\$))?\s*[\d(]|"
    r"[-–—|/]|[.,;:!?)]|$))",
    re.I,
)
_SEG_SUFFIX_CCY = {
    "USD", "EUR", "GBP", "JPY", "CNY", "CNH", "RMB", "CHF", "NOK", "SEK",
    "DKK", "CAD", "AUD", "NZD", "HKD", "SGD", "INR", "KRW", "BRL", "MXN",
    "ZAR", "PLN", "CZK", "HUF", "TRY", "AED", "SAR", "MD", "MDS", "M", "K", "BN",
}

_SEGMENT_STOP = {
    "adjusted", "reported", "statutory", "underlying", "organic", "comparable",
    "total", "group", "groupe", "consolidated", "consolide", "consolidé",
    "social", "standalone", "annual", "annualized", "annualised", "current",
    "latest", "historical", "actual", "estimated", "estimate", "target", "forecast",
    "full", "year", "fy", "h1", "h2", "q1", "q2", "q3", "q4", "ltm", "ttm",
    "ntm", "ytd", "run", "rate", "constant", "currency", "cer", "non", "gaap",
    "the", "a", "an", "le", "la", "les", "du", "de", "des",
    # B.1.3.37 — mots de DIMENSION métrique et de STRUCTURE : jamais des
    # segments analytiques (les hints MAJUSCULES « REVENUE GROWTH » et les
    # labels « CA Holding (mère) » gagnaient un faux SEG: qui cassait la
    # compatibilité — deux régressions de suite attrapées par les tests).
    "growth", "croissance", "margin", "marge", "income", "profit", "loss",
    "perte", "ebitda", "capex", "opex", "revenue", "sales", "headcount",
    "effectif", "holding", "parent", "mère", "mere",
    # Connectors, action/forecast words and per-unit nouns may follow a metric
    # but are not analytical segments.  Keeping them out preserves the
    # existing GROWTH / forward-looking / per-unit dimensions.
    "by", "of", "to", "at", "from", "for", "in", "en", "au", "aux",
    "et", "and", "versus", "vs", "per", "par", "store", "stores",
    "employee", "employees", "salarié", "salarie", "salariés", "salaries",
    "increased", "increase", "decreased", "decrease", "reduced", "reduce",
    "reduction", "grew", "rose", "rise", "fell", "fall", "up", "down",
    "expected", "expect", "projected", "projection", "planned", "plan",
    "maintain", "sustain", "reach", "achieve", "aimed", "aiming", "budget",
    "budgeted",
}


def _fold_qualifier(value: str) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.lower().replace("’", "'")
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_")


def _clean_segment(value: str) -> str:
    words = []
    for word in re.findall(r"[A-Za-zÀ-ÿ0-9][\wÀ-ÿ'’.-]*", str(value or "")):
        folded = _fold_qualifier(word)
        if not folded or folded in _SEGMENT_STOP:
            continue
        if re.fullmatch(r"(?:fy)?\d{2,4}[efp]?|[hq][1-4]|\d+h\d{2}[efp]?|\d+q\d{2}[efp]?", folded):
            continue
        if folded.upper() in _CURRENCY_CODES or folded in {"gbp", "eur", "usd"}:
            continue
        words.append(folded)
    return "_".join(words[:3])


def _semantic_qualifiers(text: str, metrics: Optional[set[str]] = None) -> frozenset[str]:
    src = str(text or "")
    out: set[str] = set()
    for rx, tag in _BASIS_QUALIFIER_PATTERNS + _TIME_BASIS_QUALIFIER_PATTERNS:
        if rx.search(src):
            out.add(tag)
    for m in _PER_UNIT_RE.finditer(src):
        unit = _fold_qualifier(m.group("unit"))
        if unit:
            out.add("PER:" + unit)
    # Segment/category/geography qualifiers are retained exactly.  This makes
    # ``Americas revenue`` distinct from group revenue and ``outerwear sales``
    # distinct from total sales, without company-specific lists.
    for rx in (_SEGMENT_BEFORE_RE, _SEGMENT_AFTER_RE):
        for m in rx.finditer(src):
            seg = _clean_segment(m.group("seg"))
            if seg:
                out.add("SEG:" + seg)
    # B.1.3.37 — ordre suffixé sans préposition ; les codes devise/échelle
    # capturés par erreur (« Revenue GBP 100m ») sont filtrés ici.
    for m in _SEGMENT_SUFFIX_RE.finditer(src):
        raw = m.group("seg")
        if raw.split()[0].upper().strip(".,") in _SEG_SUFFIX_CCY:
            continue
        seg = _clean_segment(raw)
        if seg:
            out.add("SEG:" + seg)
    return frozenset(out)


def _qualifiers_compatible(target: frozenset[str], row: frozenset[str]) -> bool:
    # Conservative equality: an explicit basis/segment/per-unit modifier cannot
    # be silently added or omitted.  False negatives degrade to estimates; false
    # certifications are forbidden.
    return target == row

_KPI_HISTORY_LOCK = threading.Lock()


def _norm_number(raw: str) -> str:
    """Normalize a display number without interpreting the currency scale."""
    s = (raw or "").replace("\u00a0", "").replace(" ", "").replace("'", "").replace("’", "")
    for _minus in _MINUS_CHARS[1:]:
        s = s.replace(_minus, "-")
    s = s.lstrip("+")
    if not s:
        return ""
    if "," in s and "." in s:
        # Last separator is assumed decimal; the other one is grouping.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        left, right = s.rsplit(",", 1)
        s = left + "." + right if len(right) <= 2 else left + right
    elif "." in s:
        left, right = s.rsplit(".", 1)
        if len(right) == 3 and left.replace("-", "").isdigit():
            s = left + right
    try:
        value = float(s)
        if value.is_integer():
            return str(int(value))
        return (f"{value:.8f}").rstrip("0").rstrip(".")
    except Exception:
        return s


def _canonical_currency(cur: str, scale: str = "") -> str:
    c = _CURRENCY.get(cur, (cur or "").upper())
    sc = _SCALE.get((scale or "").lower(), (scale or "").upper())
    return f"{c}_{sc}" if sc else c


def _canonical_suffix_unit(unit: str) -> str:
    u = (unit or "").strip()
    compact = re.sub(r"\s+", "", u)
    low = compact.lower()
    if low in ("%",):
        return "PCT"
    if low.startswith("bp"):
        return "BPS"
    if low in ("etp", "fte") or low.startswith("salari") or low.startswith("collabor") or low in ("employees", "people"):
        return "HEADCOUNT"
    if low == "x":
        return "RATIO"
    if compact.endswith("€"):
        return _canonical_currency("EUR", compact[:-1])
    if compact.endswith("£"):
        return _canonical_currency("GBP", compact[:-1])
    return compact.upper()


_DIRECT_RANGE_CONNECTOR_RE = re.compile(
    r"(?<=\d)(?P<pre>\s+)(?P<conn>to|through|à|au)(?P<post>\s+)(?=[+\-−‒–—﹣－]?\d)",
    re.I,
)
_BETWEEN_RANGE_CONNECTOR_RE = re.compile(
    rf"\b(?:between|entre)\s+{_NUM}\s+(?P<conn>and|et)\s+(?=[+\-−‒–—﹣－]?\d)",
    re.I,
)

def _normalize_scan_source(src: str) -> str:
    """Normalize typography/range connectors without changing string length."""
    chars = list(str(src or ""))
    # Unicode minus variants are semantically minus and remain one code point.
    for i, ch in enumerate(chars):
        if ch in _MINUS_CHARS[1:]:
            chars[i] = "-"
    base = "".join(chars)
    for rx in (_DIRECT_RANGE_CONNECTOR_RE, _BETWEEN_RANGE_CONNECTOR_RE):
        for m in rx.finditer(base):
            st, en = m.span("conn")
            chars[st] = "-"
            for i in range(st + 1, en):
                chars[i] = " "
    return "".join(chars)

def _mask_period_tokens(src: str) -> str:
    chars = list(str(src or ""))
    for rx in _AMOUNT_PERIOD_MASK_PATTERNS:
        for m in rx.finditer(src or ""):
            for i in range(m.start(), m.end()):
                chars[i] = " "
    return "".join(chars)


def _apply_display_sign(raw_num: str, match: re.Match[str], src: str, kind: str) -> str:
    """Preserve signs that sit before a currency token or in accounting parens."""
    raw = str(raw_num or "")
    negative = raw.lstrip().startswith("-")
    # ``-£47m``, ``- £47m`` and typographic Unicode-minus variants.
    left_context = str(src or "")[:match.start()].rstrip()
    if left_context and left_context[-1] in _MINUS_CHARS:
        negative = True
    # Explicit inner accounting form: ``GBP (47)m`` / ``(47)m GBP``.
    if kind.startswith("paren_"):
        negative = True
    # Accounting parentheses may wrap the monetary token inside a narrative
    # cell (``Net income (£47m)``), not only the whole cell.  Treat this
    # conservatively as negative rather than letting a positive fact certify it.
    left_nonspace = str(src or "")[:match.start()].rstrip()
    right_nonspace = str(src or "")[match.end():].lstrip()
    if left_nonspace.endswith("(") and right_nonspace.startswith(")"):
        negative = True
    # Ledger exports may use a trailing minus (``47m-`` / ``47m −``).
    if right_nonspace and right_nonspace[0] in _MINUS_CHARS:
        negative = True
    # A value-only accounting cell ``(£47m)`` is also negative.  Do not infer
    # negativity from arbitrary narrative parentheticals such as
    # ``Revenue (GBP 47m)``.
    stripped = str(src or "").strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        inner = stripped[1:-1].strip()
        if match.start() <= str(src or "").find(inner) + 1 and not re.search(r"[A-Za-zÀ-ÿ]{3,}", inner.replace(str(match.groupdict().get("cur") or ""), "")):
            negative = True
    if negative and not raw.lstrip().startswith("-"):
        raw = "-" + raw.lstrip("+")
    return raw


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _comparison_amount_key(amount: str, unit: str, polarity: str = "") -> Tuple[str, str]:
    """Canonicalize currency scales for evidence comparison only.

    Extraction remains display-faithful, but ``1000 k€`` and ``1 M€`` (or
    ``1030m GBP`` and ``1.03bn GBP``) represent the same evidence amount.
    """
    m = re.fullmatch(r"([A-Z]{3})_(K|M|BN)", str(unit or ""))
    unspecified = re.fullmatch(r"UNSPEC_(K|M|BN)", str(unit or ""))
    bare = re.fullmatch(r"([A-Z]{3})", str(unit or ""))
    try:
        value = Decimal(str(amount or ""))
    except (InvalidOperation, ValueError):
        return str(amount or ""), str(unit or "")
    if polarity in ("NEG", "DOWN"):
        value = -abs(value)
    elif polarity in ("POS", "UP"):
        value = abs(value)
    if m:
        factor = {"K": Decimal("0.001"), "M": Decimal("1"), "BN": Decimal("1000")}[m.group(2)]
        return _decimal_text(value * factor), f"{m.group(1)}_MBASE"
    if unspecified:
        factor = {"K": Decimal("0.001"), "M": Decimal("1"), "BN": Decimal("1000")}[unspecified.group(1)]
        return _decimal_text(value * factor), "UNSPEC_MBASE"
    if bare:
        return _decimal_text(value / Decimal("1000000")), f"{bare.group(1)}_MBASE"
    return _decimal_text(value), str(unit or "")


def _strip_leading_period_number(raw_num: str, src: str, start: int) -> Tuple[str, int]:
    """Remove a leading four-digit period accidentally swallowed by `_NUM`.

    The permissive thousands grammar historically read ``FY2026 100 M€`` as
    ``2,026,100 M€`` and ``FY2026 67.9%`` as ``202667.9%``.  A leading year is
    removed only when another numeric token follows and the local context is a
    marked period or a recognised financial metric.
    """
    raw = str(raw_num or "")
    m = re.match(r"^\s*((?:19|20)\d{2})[ \u00a0]+(.+?)\s*$", raw)
    if not m:
        return raw, 0
    before = str(src or "")[max(0, start - 60):start]
    marked = bool(re.search(
        r"(?:FY|H[12]\s*FY?|Q[1-4]\s*FY?|LTM|YTD)\s*$", before, re.I))
    metric_context = bool(_metric_families(before))
    return (m.group(2), m.start(2)) if (marked or metric_context) else (raw, 0)


def _extract_amount_refs(text: str) -> List[Tuple[int, int, str, str]]:
    """Return ordered ``(start, end, number, unit)`` references.

    Multiple endpoints emitted by one range deliberately share the same text
    span but preserve their textual order.  Competing regexes are de-duplicated
    by selecting the longest non-overlapping span.
    """
    src = text or ""
    scan_src = _normalize_scan_source(_mask_period_tokens(src))
    found: List[Tuple[int, int, int, str, str]] = []
    patterns = (
        (_PREFIX_RE, "prefix"), (_SUFFIX_CURRENCY_RE, "suffix"),
        (_SUFFIX_UNIT_RE, "unit"), (_PAREN_PREFIX_RE, "paren_prefix"),
        (_PAREN_SUFFIX_CURRENCY_RE, "paren_suffix"),
        (_SCALE_ONLY_RE, "scale_only"),
    )
    for rx, kind in patterns:
        for m in rx.finditer(scan_src):
            raw_num, num_offset = _strip_leading_period_number(
                m.group("num"), src, m.start("num"))
            raw_num = _apply_display_sign(raw_num, m, src, kind)
            num = _norm_number(raw_num)
            if not num:
                continue
            if kind == "scale_only":
                window = src[max(0, m.start() - 60):min(len(src), m.end() + 30)]
                if not _metric_families(window):
                    continue
            # ``Revenue FY2025 GBP 2.46bn`` used to be read as the amount
            # ``2025 GBP``; because that span overlaps the real prefixed
            # amount, the actual 2.46bn disappeared.  Reject a suffix-currency
            # candidate when it is visibly a marked period, or when a 4-digit
            # year is immediately followed by the real numeric amount.
            if kind == "suffix":
                before = src[max(0, m.start() - 12):m.start()]
                after = src[m.end():m.end() + 24]
                marked_fy = bool(re.search(r"(?:FY|H[12]\s*FY?)\s*$", before, re.I))
                looks_year = bool(re.fullmatch(r"(?:19|20)\d{2}", num))
                followed_by_amount = bool(re.match(r"\s*[+\-]?\d", after))
                if marked_fy or (looks_year and followed_by_amount):
                    continue
            if kind == "unit":
                unit = _canonical_suffix_unit(m.group("unit"))
            elif kind == "scale_only":
                unit = "UNSPEC_" + _SCALE.get((m.group("scale") or "").lower(), (m.group("scale") or "").upper())
            else:
                unit = _canonical_currency(m.group("cur"), m.group("scale") or "")
            span_start = (m.start("num") + num_offset) if kind in ("suffix", "unit", "scale_only") else m.start()
            found.append((span_start, m.end(), 0, num, unit))
            rng = (m.groupdict().get("rng") or "").strip()
            if rng:
                rhs = re.sub(r"^\s*(?:[-–]|to|through|à|au|and|et)\s*", "", rng, flags=re.I)
                if num.startswith("-") and not rhs.lstrip().startswith("-"):
                    rhs = "-" + rhs.lstrip("+")
                rhs_num = _norm_number(rhs)
                if rhs_num:
                    found.append((span_start, m.end(), 1, rhs_num, unit))

    by_span: Dict[Tuple[int, int], List[Tuple[int, str, str]]] = {}
    for st, en, order, num, unit in found:
        vals = by_span.setdefault((st, en), [])
        item = (order, num, unit)
        if item not in vals:
            vals.append(item)

    selected: List[Tuple[int, int]] = []
    for span in sorted(by_span, key=lambda x: (x[0], -(x[1] - x[0]))):
        if any(not (span[1] <= old[0] or span[0] >= old[1]) for old in selected):
            continue
        selected.append(span)

    refs: List[Tuple[int, int, str, str]] = []
    for st, en in sorted(selected):
        seen_values = set()
        for order, num, unit in sorted(by_span[(st, en)], key=lambda x: x[0]):
            sig = (num, unit)
            if sig in seen_values:
                continue
            seen_values.add(sig)
            refs.append((st, en, num, unit))
    return refs


def extract_amounts(text: str) -> List[Tuple[str, str]]:
    """Return canonical amount/unit pairs in textual order.

    Naked years/integers are ignored.  Both endpoints of a displayed range are
    returned: ``15-20 M€`` becomes ``15 EUR_M`` AND ``20 EUR_M``.
    """
    return [(num, unit) for _, _, num, unit in _extract_amount_refs(text or "")]


def _amount_keys(text: str) -> set[Tuple[str, str]]:
    return set(extract_amounts(text or ""))


def _explicit_metric_families(explicit: str = "") -> set[str]:
    exp = re.sub(r"[\s,/|+]+", " ", (explicit or "").strip().upper())
    if not exp or exp == "OTHER":
        return set()
    if exp in _KNOWN_METRIC_FAMILIES:
        return {exp}
    return {token for token in exp.split() if token in _KNOWN_METRIC_FAMILIES}


def _year4(raw: str) -> str:
    """Normalize FY25/FY2025-like year tokens to a four-digit year."""
    s = str(raw or "").strip()
    if len(s) == 2 and s.isdigit():
        return str(2000 + int(s))
    return s if len(s) == 4 and s.isdigit() else ""


def _period_years(text: str = "", *, explicit_period: bool = False) -> set[str]:
    """Extract normalized period tokens, preserving fiscal granularity/order."""
    src = str(text or "")
    out: set[str] = set()
    occupied: List[Tuple[int, int]] = []
    amount_spans = [(st, en) for st, en, _num, _unit in _extract_amount_refs(src)]

    def free(span: Tuple[int, int]) -> bool:
        return not any(not (span[1] <= st or span[0] >= en) for st, en in occupied)

    def is_amount(span: Tuple[int, int]) -> bool:
        return any(not (span[1] <= st or span[0] >= en) for st, en in amount_spans)

    # Most specific forms first.  Otherwise FY26E inside H1 FY26E would occupy
    # the span and erase the material half-year granularity.
    for rx, prefix in ((_HALF_PREFIX_RE, "H"), (_QUARTER_PREFIX_RE, "Q")):
        for m in rx.finditer(src):
            if not free(m.span()):
                continue
            year = _year4(m.group(2))
            if year:
                out.add(f"{prefix}{m.group(1)}FY{year}")
                occupied.append(m.span())

    for rx, prefix in ((_FY_RANGE_RE, "FYR"), (_YEAR_RANGE_RE, "YR")):
        for m in rx.finditer(src):
            if not free(m.span()):
                continue
            y1, y2 = _year4(m.group(1)), _year4(m.group(2))
            if y1 and y2:
                out.add(f"{prefix}{y1}-{y2}")
                occupied.append(m.span())

    for rx in (_HALF_RE, _QUARTER_RE, _ROLLING_RE):
        for m in rx.finditer(src):
            if not free(m.span()):
                continue
            year = _year4(m.group(2))
            if not year:
                continue
            tag = m.group(1).upper()
            out.add(f"{tag}FY{year}" if tag.startswith(("H", "Q")) else f"{tag}{year}")
            occupied.append(m.span())

    for rx in (_HALF_AFTER_RE, _QUARTER_AFTER_RE, _ROLLING_AFTER_RE):
        for m in rx.finditer(src):
            if not free(m.span()):
                continue
            year = _year4(m.group(1))
            if not year:
                continue
            tag = m.group(2).upper()
            out.add(f"{tag}FY{year}" if tag.startswith(("H", "Q")) else f"{tag}{year}")
            occupied.append(m.span())

    # Plain forecast/plan suffixes (2026E/F/P, FY26E/F/P) after sub-periods.
    for m in _ESTIMATE_PERIOD_RE.finditer(src):
        if not free(m.span()):
            continue
        year = _year4(m.group("year"))
        if year:
            out.add(("FY" if m.group("fy") else "Y") + year)
            occupied.append(m.span())

    for m in _FY_RE.finditer(src):
        if not free(m.span()):
            continue
        year = _year4(m.group(1))
        if year:
            out.add(f"FY{year}")
            occupied.append(m.span())

    for rx in (_HALF_ONLY_RE, _QUARTER_ONLY_RE, _ROLLING_ONLY_RE):
        for m in rx.finditer(src):
            if free(m.span()):
                out.add(m.group(1).upper())
                occupied.append(m.span())

    for m in _YEAR_RE.finditer(src):
        if not free(m.span()) or is_amount(m.span()):
            continue
        year = m.group(1)
        if explicit_period:
            out.add(f"Y{year}")
            continue
        window = src[max(0, m.start() - 40):min(len(src), m.end() + 40)]
        if _metric_families(window) or _FORWARD_RE.search(window):
            out.add(f"Y{year}")
    return out


def _period_token_year(token: str) -> str:
    m = re.search(r"((?:19|20)\d{2})$", str(token or ""))
    return m.group(1) if m else ""


def _specific_period(token: str) -> bool:
    return str(token or "").startswith(("H1", "H2", "Q1", "Q2", "Q3", "Q4", "LTM", "TTM", "NTM", "YTD", "QTD", "MTD", "FYR", "YR"))


def _is_forward_claim(text: str = "") -> bool:
    src = str(text or "")
    return bool(_FORWARD_RE.search(src) or _FORECAST_PERIOD_TOKEN_RE.search(src))


def _row_temporal_semantics(row: Mapping[str, Any]) -> tuple[set[str], bool]:
    primary = " ".join(str(row.get(k) or "") for k in (
        "label", "fact", "name", "metric"))
    periods = _period_years(str(row.get("period") or ""), explicit_period=True)
    if not periods:
        periods = _period_years(primary)
    temporal_text = primary + " " + str(row.get("period") or "")
    return periods, bool(_ROW_FORWARD_RE.search(temporal_text)
                         or _FORECAST_PERIOD_TOKEN_RE.search(temporal_text))


def _metric_families(text: str = "", explicit: str = "") -> set[str]:
    """Infer generic metric families from governed rows or executive text."""
    out: set[str] = set(_explicit_metric_families(explicit))
    canon = str(_canonical_metric_id(text or "") or "OTHER").upper()
    if canon in _KNOWN_METRIC_FAMILIES:
        out.add(canon)
    for rx, family in _METRIC_FAMILY_PATTERNS:
        if rx.search(text or ""):
            out.add(family)
    # A marketing investment is a marketing-spend claim, not generic CAPEX.
    if "MARKETING_SPEND" in out:
        out.discard("CAPEX")
    if "SAVINGS" in out:
        out.add("GROWTH")
    # "Operating profit margin" is a margin, not an amount of operating income.
    if "OPERATING_MARGIN" in out:
        out.discard("OPERATING_INCOME")
    # Specific debt families dominate the generic fallback.
    if "NET_DEBT" in out or "GROSS_DEBT" in out:
        out.discard("FINANCIAL_DEBT")
    return out


def _semantic_polarity(text: str, metrics: set[str], amount: str = "", unit: str = "") -> str:
    """Return a conservative lexical/numeric direction for one metric claim.

    Numeric sign already distinguishes many facts, but corporate documents
    often write ``GBP 47m loss`` or ``5% decline`` with a positive magnitude.
    Without this dimension, a loss could certify a profit carrying the same
    amount.  Empty means genuinely neutral/unknown.
    """
    src = str(text or "")
    try:
        numeric_negative = float(str(amount or "")) < 0
    except Exception:
        numeric_negative = False

    directional_unit = str(unit or "") in {"PCT", "BPS"}
    if directional_unit or "GROWTH" in metrics:
        down = bool(_DOWN_RE.search(src)) or numeric_negative
        up = bool(_UP_RE.search(src)) and not numeric_negative
        if down != up:
            return "DOWN" if down else "UP"

    if metrics & {"NET_INCOME", "OPERATING_INCOME", "EBIT", "EBITDA"}:
        neg = bool(_LOSS_RE.search(src)) or numeric_negative
        pos = bool(_PROFIT_RE.search(src)) and not numeric_negative
        if neg != pos:
            return "NEG" if neg else "POS"
    return ""


def _polarity_compatible(target: str, row: str) -> bool:
    if not target and not row:
        return True
    return bool(target and row and target == row)


def _row_metric_families(row: Mapping[str, Any]) -> set[str]:
    """Return structured row semantics without contamination from source prose.

    ``source_line`` can legitimately mention several metrics.  It is used only
    as a last-resort fallback when neither the canonical id nor the row label
    provides a metric.  Conflicting structured base metrics make the row
    ineligible for executive certification rather than silently broadening it.
    """
    explicit = _explicit_metric_families(str(row.get("metric_canonical_id") or ""))
    primary_text = " ".join(str(row.get(k) or "") for k in (
        "label", "fact", "name", "metric"))
    inferred = _metric_families(primary_text)
    exp_base = explicit & _BASE_METRIC_FAMILIES
    inf_base = inferred & _BASE_METRIC_FAMILIES
    if exp_base:
        if inf_base and exp_base.isdisjoint(inf_base):
            return set()
        # A structured canonical id is authoritative for the base metric.
        # Label inference may add modifiers such as GROWTH, never a second
        # unrelated base metric.
        return explicit | (inferred - _BASE_METRIC_FAMILIES)
    families = inferred
    if families:
        return families
    fallback_text = " ".join(str(row.get(k) or "") for k in (
        "source_line", "raw_line", "notes"))
    return _metric_families(fallback_text)


def _metric_compatible(target: set[str], row_metric: set[str]) -> bool:
    # Amount-only equality is never sufficient evidence.  Unknown semantics
    # degrade to an estimate instead of allowing an unrelated same-amount fact
    # to certify the claim.
    if target == {_UNTYPED_VALUE_METRIC}:
        # Legacy numeric-only values may match only another untyped row.  They
        # never permit a semantic claim (profit, debt, sales...) to borrow an
        # unlabelled amount.
        return not row_metric
    if not target:
        return False
    if not row_metric:
        return False
    # Composite semantics such as REVENUE+GROWTH require both components.
    return target.issubset(row_metric)


def _temporal_compatible(target_periods: set[str], row_periods: set[str],
                         target_forward: bool, row_forward: bool) -> bool:
    # A forward-looking objective must be backed by a forward-looking governed
    # fact, and an actual must not borrow a target.
    if target_forward != row_forward:
        return False

    def pair(a: str, b: str) -> bool:
        if a == b:
            return True
        return (_period_token_year(a) == _period_token_year(b)
                and not _specific_period(a) and not _specific_period(b))

    if target_periods and row_periods:
        # Both sides must describe the same complete period set.  One half/year
        # or one endpoint of a range can never certify a broader claim.
        return (all(any(pair(t, r) for r in row_periods) for t in target_periods)
                and all(any(pair(t, r) for t in target_periods) for r in row_periods))
    if target_periods and not row_periods:
        # A period-less announced programme may support a dated delivery target.
        return bool(target_forward and row_forward)
    if not target_periods and row_periods:
        # A headline may omit a full-year label already shown elsewhere in the
        # slide, but must never erase a material sub-period (H1/Q1/LTM/YTD or
        # fiscal-year range).
        return all(not _specific_period(r) for r in row_periods)
    return True


def _clause_for_span(text: str, start: int, end: int) -> str:
    left, right = 0, len(text or "")
    for m in _CLAUSE_BREAK_RE.finditer(text or ""):
        if m.end() <= start:
            left = m.end()
        elif m.start() >= end:
            right = m.start()
            break
    return (text or "")[left:right].strip()


def _evidence_context_for_span(text: str, start: int, end: int,
                               metric_hint: str = "") -> str:
    """Return the local claim context, carrying a descriptor across a visual separator.

    Corporate decks commonly render ``Revenue France — FY2024 100 M€`` or a
    two-cell equivalent ``Revenue France | FY2024 100 M€``.  ``_CLAUSE_BREAK_RE``
    intentionally splits those separators to prevent evidence leaking between
    independent claims, but the right-hand numeric cell then loses its metric
    and analytical qualifier.  When (and only when) the current clause is
    numeric/period-only and the immediately preceding clause contains a known
    metric, the two are rejoined for evidence classification.
    """
    src = str(text or "")
    current = _clause_for_span(src, start, end)
    # A structured field hint already carries the descriptor; no textual
    # backtracking is needed in that case.
    if metric_hint or not _numeric_only_clause(current):
        return current

    breaks = list(_CLAUSE_BREAK_RE.finditer(src))
    current_left = 0
    previous_left = 0
    previous_right = 0
    for m in breaks:
        if m.end() <= start:
            previous_left = current_left
            previous_right = m.start()
            current_left = m.end()
        elif m.start() >= end:
            break
    if previous_right <= previous_left:
        return current
    previous = src[previous_left:previous_right].strip()
    if not previous:
        return current
    previous_metrics = _metric_families(previous)
    if not previous_metrics:
        return current
    return (previous + " " + current).strip()


def _numeric_only_clause(clause: str) -> bool:
    """Whether a clause is only a displayed number plus harmless qualifiers."""
    src = str(clause or "")
    for start, end, _num, _unit in reversed(_extract_amount_refs(src)):
        src = src[:start] + " " + src[end:]
    for rx in (_FY_RANGE_RE, _YEAR_RANGE_RE, _HALF_RE, _QUARTER_RE, _ROLLING_RE,
               _HALF_AFTER_RE, _QUARTER_AFTER_RE, _ROLLING_AFTER_RE,
               _HALF_ONLY_RE, _QUARTER_ONLY_RE, _FY_RE, _YEAR_RE):
        src = rx.sub(" ", src)
    src = re.sub(
        r"\b(?:estimated|estimate|estim[ée]|indicatif|indicative|approx|approximately|"
        r"environ|about|circa|ca\.?|as of|au|at|FY|H[12])\b",
        " ", src, flags=re.I,
    )
    return not bool(re.search(r"[A-Za-zÀ-ÿ]", src))


def _infer_unique_metric_for_amount(amount: str, unit: str, cr_text: str,
                                    financial_facts_table: Optional[Mapping[str, Any]]) -> set[str]:
    """Infer semantics for a value-only KPI only when evidence is unambiguous."""
    idx = build_evidence_index(financial_facts_table)
    entries = idx.get(_comparison_amount_key(amount, unit), [])
    families = {tuple(sorted(fam)) for _level, fam, _periods, _forward, _polarity, _quals in entries if fam}
    if len(families) == 1:
        return set(next(iter(families)))
    cr_families = set()
    for line in str(cr_text or "").splitlines():
        if (amount, unit) not in _amount_keys(line):
            continue
        if not (_FACT_MARKER.search(line) or _WEAK_MARKER.search(line)):
            continue
        fam = _metric_families(line)
        if fam:
            cr_families.add(tuple(sorted(fam)))
    return set(next(iter(cr_families))) if len(cr_families) == 1 else set()


def _row_evidence_level(row: Mapping[str, Any]) -> str:
    status = str(row.get("status") or row.get("kind") or "").upper()
    perimeter_match = str(row.get("perimeter_match") or "").upper()
    blockers = str(row.get("board_safe_blockers") or "").lower()
    source_doc = str(row.get("source_doc") or row.get("source") or "").lower()
    hard_blockers = (
        "unresolved_conflict", "unit_uncertain", "period_heterogeneous",
        "social_aggregation_raw", "transformation_undocumented",
        "perimeter_mismatch", "pairing_suspect",
    )
    if perimeter_match != "FULL" or "hors périmètre" in status or "out of perimeter" in status:
        return "ESTIM"
    if any(token in blockers for token in hard_blockers):
        return "ESTIM"
    if any(tok in status for tok in ("A_VERIFIER", "À VÉRIFIER", "TO VERIFY", "ESTIM", "HYPOTH")):
        return "ESTIM"
    if any(tok in source_doc for tok in ("narratif", "narrative", "agent")):
        return "ESTIM"
    if "source_non_board_safe" in blockers or "narrative_only" in blockers:
        return "ESTIM"
    if status in ("FAIT", "FACT") or status.startswith("FAIT") or status.startswith("FACT"):
        return "FAIT"
    return "ESTIM"


def build_evidence_index(financial_facts_table: Optional[Mapping[str, Any]]) -> Dict[Tuple[str, str], List[Tuple[str, set[str], set[str], bool, str, frozenset[str]]]]:
    """Build amount -> evidence entries with metric, period, polarity and qualifiers."""
    out: Dict[Tuple[str, str], List[Tuple[str, set[str], set[str], bool, str, frozenset[str]]]] = {}
    rows = ((financial_facts_table or {}).get("facts") or []) if isinstance(financial_facts_table, Mapping) else []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        periods, forward = _row_temporal_semantics(row)
        families = _row_metric_families(row)
        row_text = " ".join(str(row.get(k) or "") for k in (
            "label", "fact", "name", "metric", "value"))
        qualifiers = _semantic_qualifiers(row_text, families)
        for raw_key in _amount_keys(str(row.get("value") or "")):
            polarity = _semantic_polarity(row_text, families, raw_key[0], raw_key[1])
            key = _comparison_amount_key(*raw_key, polarity)
            entry = (_row_evidence_level(row), families, periods, forward, polarity, qualifiers)
            if entry not in out.setdefault(key, []):
                out[key].append(entry)
    return out


def _reduce_entries(entries: Iterable[Tuple[str, set[str], set[str], bool, str, frozenset[str]]],
                    target_metrics: set[str], target_periods: set[str],
                    target_forward: bool, target_polarity: str = "",
                    target_qualifiers: Optional[frozenset[str]] = None) -> str:
    entries = list(entries or [])
    if not entries:
        return "ABSENT"
    tq = frozenset(target_qualifiers or ())
    compatible = [
        level for level, fam, periods, forward, polarity, qualifiers in entries
        if _metric_compatible(target_metrics, fam)
        and _temporal_compatible(target_periods, periods, target_forward, forward)
        and _polarity_compatible(target_polarity, polarity)
        and _qualifiers_compatible(tq, qualifiers)
    ]
    if not compatible:
        return "ABSENT"
    return "FAIT" if "FAIT" in compatible else "ESTIM"


def classify_amount_in_cr(amount_norm: str, unit: str, cr_text: str,
                          target_metrics: Optional[set[str]] = None,
                          target_periods: Optional[set[str]] = None,
                          target_forward: bool = False,
                          target_polarity: str = "",
                          target_qualifiers: Optional[frozenset[str]] = None) -> str:
    """Fallback classification from rendered CR, with local semantic context."""
    if not cr_text:
        return "ABSENT"
    lines = (cr_text or "").splitlines()
    target = _comparison_amount_key(amount_norm, unit, target_polarity)
    hits = []
    tq = frozenset(target_qualifiers or ())
    for idx, line in enumerate(lines):
        context = line
        ctx_metrics = _metric_families(context)
        ctx_keys = {
            _comparison_amount_key(k[0], k[1], _semantic_polarity(context, ctx_metrics, k[0], k[1]))
            for k in _amount_keys(line)
        }
        if target not in ctx_keys:
            continue
        if target_metrics and not ctx_metrics:
            context = " ".join(lines[max(0, idx - 1): min(len(lines), idx + 2)])
            ctx_metrics = _metric_families(context)
        if not _metric_compatible(set(target_metrics or ()), ctx_metrics):
            continue
        if not _qualifiers_compatible(tq, _semantic_qualifiers(context, ctx_metrics)):
            continue
        ctx_periods = _period_years(context)
        ctx_forward = _is_forward_claim(context)
        if not _temporal_compatible(
            set(target_periods or ()), ctx_periods, bool(target_forward), ctx_forward
        ):
            continue
        if not _polarity_compatible(
            str(target_polarity or ""),
            _semantic_polarity(context, ctx_metrics, amount_norm, unit),
        ):
            continue
        marker_context = context
        if not (_FACT_MARKER.search(marker_context) or _WEAK_MARKER.search(marker_context)):
            marker_context = " ".join(lines[max(0, idx - 1): min(len(lines), idx + 2)])
        level = "FAIT" if (_FACT_MARKER.search(marker_context) and not _WEAK_MARKER.search(marker_context)) else "ESTIM"
        hits.append(level)
    if not hits:
        return "ABSENT"
    return "FAIT" if "FAIT" in hits else "ESTIM"


def classify_amount(amount_norm: str, unit: str, cr_text: str,
                    financial_facts_table: Optional[Mapping[str, Any]] = None,
                    target_metrics: Optional[set[str]] = None,
                    target_periods: Optional[set[str]] = None,
                    target_forward: bool = False,
                    target_polarity: str = "",
                    target_qualifiers: Optional[frozenset[str]] = None) -> str:
    idx = build_evidence_index(financial_facts_table)
    key = _comparison_amount_key(amount_norm, unit, target_polarity)
    if key in idx:
        return _reduce_entries(
            idx[key], set(target_metrics or ()), set(target_periods or ()),
            bool(target_forward), str(target_polarity or ""),
            frozenset(target_qualifiers or ()))
    return classify_amount_in_cr(
        amount_norm, unit, cr_text, set(target_metrics or ()),
        set(target_periods or ()), bool(target_forward), str(target_polarity or ""),
        frozenset(target_qualifiers or ()))


def _classify_text(value: str, cr_text: str,
                   financial_facts_table: Optional[Mapping[str, Any]],
                   metric_hint: str = "") -> set[str]:
    verdicts: List[str] = []
    for start, end, amount, unit in _extract_amount_refs(value or ""):
        clause = _evidence_context_for_span(value or "", start, end, metric_hint)
        target_metrics = _metric_families(clause, metric_hint)
        if not target_metrics and _numeric_only_clause(clause):
            target_metrics = _infer_unique_metric_for_amount(
                amount, unit, cr_text, financial_facts_table)
            if not target_metrics:
                target_metrics = {_UNTYPED_VALUE_METRIC}
        # Corporate value cells can contain a year but no metric word
        # (e.g. ``118,4 M€ (2025)``). Include the structured field hint so
        # the year is treated as a period and cannot borrow a FY2024 fact.
        # Values already explicitly labelled as estimates/hypotheses retain
        # their historical cautious rendering instead of becoming "absent".
        _period_hint = "" if re.search(
            r"(?:estim|hypoth|à vérifier|to verify)", value or "", re.I
        ) else metric_hint
        target_periods = _period_years(
            " ".join(part for part in (clause, _period_hint) if part))
        target_forward = _is_forward_claim(clause)
        target_polarity = _semantic_polarity(clause, target_metrics, amount, unit)
        target_qualifiers = _semantic_qualifiers(
            " ".join(part for part in (clause, metric_hint) if part), target_metrics)
        # 9.4.51 — un TAUX DÉRIVÉ de deux faits confirmés de la même période (marge brute / CA, résultat d'exploitation
        # / CA, résultat net / CA) est un fait, à la précision affichée près (recette du 02/10/2026 : « Marge brute à
        # 55,06 % » — 341,343 / 619,985 — sortait « ≈ … estim. à vérifier » ET « chiffre sans pièce »)
        if str(unit or "").strip().upper() in ("%", "PCT") and not target_forward and _derived_rate_supported51(
                value or "", start, end, amount, financial_facts_table, target_periods):
            verdicts.append("FAIT")
            continue
        verdicts.append(classify_amount(
            amount, unit, cr_text, financial_facts_table, target_metrics,
            target_periods, target_forward, target_polarity, target_qualifiers))
    return set(verdicts)


def _derived_rate_supported51(value: str, start: int, end: int, amount, facts_table, periods) -> bool:
    try:
        facts = list((facts_table or {}).get("facts") or [])
        num = {}
        for f in facts:
            if str(f.get("proof_status") or "").upper().startswith("CONFIRMED") or f.get("proof_status") in (None, ""):
                v = f.get("normalized_value")
                if isinstance(v, (int, float)) and v:
                    num[(str(f.get("metric_canonical_id") or ""), str(f.get("period") or ""))] = float(v)
        raw = str(value or "")[start:end]
        m = re.search(r"(\d+)(?:[.,](\d+))?", raw)
        if not m:
            return False
        decimals = len(m.group(2) or "")
        shown = float(amount) if not isinstance(amount, str) else float(m.group(0).replace(",", "."))
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        wanted = {str(p) for p in (periods or [])}
        for (metric, period), den in num.items():
            if metric != "REVENUE" or (wanted and not any(w in period for w in wanted)):
                continue
            for numer_metric in ("GROSS_MARGIN", "GROSS_PROFIT", "OPERATING_PROFIT", "EBITDA", "NET_INCOME", "EBIT"):
                n = num.get((numer_metric, period))
                if n and abs(n / den * 100 - shown) <= tol:
                    return True
        return False
    except Exception:
        return False


def _headline_is_hypothesis(value: str, cr_text: str,
                            financial_facts_table: Optional[Mapping[str, Any]],
                            metric_hint: str = "") -> bool:
    v = (value or "").strip()
    if not v or v == "—":
        return False
    if re.search(r"Non disponible|Not available|ESTIM|HYPOTH|à vérifier|to verify|Instable entre runs|Unstable across runs|^\s*≈", v, re.I):
        return True
    amts = extract_amounts(v)
    if not amts:
        return False
    verdicts = _classify_text(v, cr_text, financial_facts_table, metric_hint)
    return not (verdicts and verdicts <= {"FAIT"})


# v62.13.9.4.50 — doctrine « tout livrer, tout signaler en place » (décision du 28/09/2026) : ces deux gardes ne
# réécrivent plus la valeur (« ≈ … — estim. à vérifier ») ni ne la remplacent (« Non disponible — à collecter ») ;
# elles posent l'étiquette de statut, rendue en marqueur « ⚠ à vérifier — chiffre sans pièce ». Témoin : contrat
# d'un dossier coté britannique (une ligne de fait sortait « ≈ … — estimate, to verify »).
# Décision de cycle (30/09/2026) : la forme « ≈ valeur — estim. à vérifier » est déjà un signalement VISIBLE en place
# (rien n'est retiré) ; l'unifier avec le marqueur « ⚠ à vérifier — motif » toucherait ~45 contrats B1.3 : reporté au
# prochain cycle, interrupteur prêt. « Non disponible — à collecter » ne vise qu'une carte sans aucune pièce.
_FLAG_IN_PLACE50 = False


def _flag50(v: str, lang: str) -> str:
    if "⟨statu" in v:
        return v
    return f"{v} ⟨statut : non étayé — à documenter⟩" if lang == "fr" else f"{v} ⟨status : unsourced figure⟩"


def govern_kpi_value(value: str, cr_text: str, lang: str = "fr",
                     financial_facts_table: Optional[Mapping[str, Any]] = None,
                     metric_hint: str = "") -> str:
    """Govern a headline KPI: fact, visibly estimated, or unavailable."""
    v = (value or "").strip()
    if not v or v == "—" or _GLOBAL_ALREADY.search(v):
        return v
    amts = extract_amounts(v)
    if not amts:
        return v
    verdicts = _classify_text(v, cr_text, financial_facts_table, metric_hint)
    if verdicts and verdicts <= {"FAIT"}:
        return v
    if _FLAG_IN_PLACE50:
        return _flag50(v, lang)
    if verdicts == {"ABSENT"} and not _is_forward_claim(v):
        return "Non disponible — à collecter" if lang == "fr" else "Not available — to collect"
    suffix = " — estim. à vérifier" if lang == "fr" else " — estimate, to verify"
    return ("≈ " + v + suffix) if not v.startswith("≈") else v + suffix


def govern_executive_text(value: str, cr_text: str, lang: str = "fr",
                          financial_facts_table: Optional[Mapping[str, Any]] = None,
                          metric_hint: str = "") -> str:
    """Govern a numeric sentence without deleting the sentence when evidence is absent."""
    v = (value or "").strip()
    if not v or not extract_amounts(v):
        return v
    verdicts = _classify_text(v, cr_text, financial_facts_table, metric_hint)
    if verdicts and verdicts <= {"FAIT"}:
        return v
    if _GLOBAL_ALREADY.search(v):
        return v
    if _FLAG_IN_PLACE50:
        return _flag50(v, lang)
    suffix = " — estim. à vérifier" if lang == "fr" else " — estimate, to verify"
    return ("≈ " + v + suffix) if not v.startswith("≈") else v + suffix


_FIRM_ACTION_FR = re.compile(
    r"^(Provisionner|Constater|Comptabiliser|Passer)\s+(.*(?:€|k€|M€|Md€).*)$",
    re.I,
)
_FIRM_ACTION_EN = re.compile(
    r"^(Provision|Accrue|Recognize|Recognise|Book|Record)\s+(.*(?:GBP|EUR|USD|£|€|\$).*)$",
    re.I,
)


def rewrite_firm_financial_actions(text: str, lang: str = "fr", cr_text: str = "",
                                   financial_facts_table: Optional[Mapping[str, Any]] = None) -> str:
    """Rewrite a firm accounting action only when its amount is not fact-backed."""
    t = (text or "").strip()
    if not t or "si confirmé" in t.lower() or "if confirmed" in t.lower():
        return t
    rx = _FIRM_ACTION_EN if lang == "en" else _FIRM_ACTION_FR
    m = rx.match(t)
    if not m:
        return t
    verdicts = _classify_text(t, cr_text, financial_facts_table)
    if verdicts and verdicts <= {"FAIT"}:
        return t
    verb = m.group(1).lower()
    rest = m.group(2).rstrip(". ")
    if lang == "en":
        return f"Have the CFO/auditor confirm, then {verb} if confirmed: {rest}."
    return f"Faire confirmer par le DAF / expert-comptable, puis {verb} si confirmé : {rest}."


def _dict_metric_hint(item: Mapping[str, Any], key: str) -> str:
    """Derive a semantic hint for a numeric value stored in a generic dict.

    Real deck payloads frequently separate ``label`` and ``value``.  Once
    amount-only matching is forbidden, the value cell must inherit the metric
    from its sibling label rather than becoming an untyped claim.
    """
    direct = _FIELD_METRIC_HINTS.get(str(key or "").lower(), "")
    context = " ".join(str(item.get(k) or "") for k in (
        "metric_canonical_id", "metric", "label", "fact", "name", "title",
        "kpi", "indicateur", "type", "action", "decision",
    ))
    families = _metric_families(context, direct)
    return context.strip() or " ".join(sorted(families))


def _govern_list(values: Any, cr_text: str, lang: str,
                 fft: Optional[Mapping[str, Any]], *, actions: bool = False) -> tuple[Any, int]:
    changed = 0
    # Deck renderers expect list-valued optional fields.  Never replace a
    # missing list by ``None`` while applying the guard.
    if values is None:
        return [], changed
    if not isinstance(values, list):
        return values, changed
    out = []
    for value in values:
        if isinstance(value, str):
            new = rewrite_firm_financial_actions(value, lang, cr_text, fft) if actions else value
            new = govern_executive_text(new, cr_text, lang, fft)
            changed += int(new != value)
            out.append(new)
        elif isinstance(value, dict):
            item = dict(value)
            for key in list(item):
                if isinstance(item[key], str):
                    old = item[key]
                    new = rewrite_firm_financial_actions(old, lang, cr_text, fft) if (actions or key in ("action", "decision")) else old
                    new = govern_executive_text(
                        new, cr_text, lang, fft,
                        metric_hint=_dict_metric_hint(item, str(key)),
                    )
                    item[key] = new
                    changed += int(new != old)
                elif isinstance(item[key], list):
                    item[key], n = _govern_list(item[key], cr_text, lang, fft, actions=actions)
                    changed += n
            out.append(item)
        else:
            out.append(value)
    return out, changed


def govern_executive_payload(data: MutableMapping[str, Any], cr_text: str,
                             lang: str = "fr",
                             financial_facts_table: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Apply the guard to the actual corporate and solo deck surfaces in-place."""
    stats = {"changed": 0, "hypothesis_kpis": False, "headline_values": []}

    # Corporate headline KPIs — the real path for dossier industriel / dossier agroalimentaire.
    cc = data.get("contexte_corporate")
    if isinstance(cc, dict):
        for key in ("ca", "croissance", "effectif"):
            if cc.get(key):
                old = str(cc[key])
                hint = _FIELD_METRIC_HINTS.get(key, key)
                was_hypothesis = _headline_is_hypothesis(
                    old, cr_text, financial_facts_table, hint)
                new = govern_kpi_value(
                    old, cr_text, lang, financial_facts_table, hint)
                cc[key] = new
                stats["headline_values"].append(new)
                stats["hypothesis_kpis"] = bool(
                    stats["hypothesis_kpis"] or was_hypothesis)
                if new != old:
                    stats["changed"] += 1
        if cc.get("situation"):
            old = str(cc["situation"])
            new = govern_executive_text(old, cr_text, lang, financial_facts_table)
            cc["situation"] = new
            stats["changed"] += int(new != old)
        for key in ("risques_top", "arbitrages"):
            cc[key], n = _govern_list(cc.get(key), cr_text, lang, financial_facts_table)
            stats["changed"] += n

    # Solo/market headline KPIs.
    market = data.get("marche")
    if isinstance(market, dict):
        for key in ("taille", "croissance", "missions"):
            if market.get(key):
                old = str(market[key])
                hint = _FIELD_METRIC_HINTS.get(key, key)
                was_hypothesis = _headline_is_hypothesis(
                    old, cr_text, financial_facts_table, hint)
                new = govern_kpi_value(
                    old, cr_text, lang, financial_facts_table, hint)
                market[key] = new
                stats["headline_values"].append(new)
                stats["hypothesis_kpis"] = bool(
                    stats["hypothesis_kpis"] or was_hypothesis)
                if new != old:
                    stats["changed"] += 1

    # Executive narrative surfaces.
    swot = data.get("swot")
    if isinstance(swot, dict):
        for key in ("forces", "faiblesses", "opportunites", "risques"):
            swot[key], n = _govern_list(swot.get(key), cr_text, lang, financial_facts_table)
            stats["changed"] += n

    data["axes"], n = _govern_list(data.get("axes"), cr_text, lang, financial_facts_table, actions=True)
    stats["changed"] += n
    data["roadmap"], n = _govern_list(data.get("roadmap"), cr_text, lang, financial_facts_table, actions=True)
    stats["changed"] += n
    data["next_steps"], n = _govern_list(data.get("next_steps"), cr_text, lang, financial_facts_table, actions=True)
    stats["changed"] += n
    data["decisions_codir"], n = _govern_list(data.get("decisions_codir"), cr_text, lang, financial_facts_table, actions=True)
    stats["changed"] += n

    commercial = data.get("commercial")
    if isinstance(commercial, dict):
        for key in ("opportunites", "challenges_marketing", "challenges_finance"):
            commercial[key], n = _govern_list(commercial.get(key), cr_text, lang, financial_facts_table)
            stats["changed"] += n
        commercial["plan_actions"], n = _govern_list(
            commercial.get("plan_actions"), cr_text, lang, financial_facts_table, actions=True)
        stats["changed"] += n

    conclusion = data.get("conclusion")
    if isinstance(conclusion, dict):
        conclusion["points"], n = _govern_list(conclusion.get("points"), cr_text, lang, financial_facts_table)
        stats["changed"] += n

    # Supply payload can contain findings, decisions and action-plan dictionaries.
    supply = data.get("supply_chain")
    if isinstance(supply, dict):
        for key in ("findings", "key_findings", "risks", "dg_decisions", "decisions",
                    "action_plan", "kpis", "codir_tradeoffs"):
            supply[key], n = _govern_list(supply.get(key), cr_text, lang, financial_facts_table, actions=("decision" in key or "action" in key))
            stats["changed"] += n

    return stats


def _representative_million_values(kpis: Iterable[str]) -> Dict[str, float]:
    """Collapse each currency KPI/range to a million-base representative."""
    grouped: Dict[str, List[float]] = {}
    for text in kpis or []:
        per_text: Dict[str, List[float]] = {}
        for amount, unit in extract_amounts(str(text)):
            m = re.fullmatch(r"([A-Z]{3})_(K|M|BN)", unit or "")
            if not m:
                continue
            try:
                value = float(amount)
                scale = m.group(2)
                if scale == "BN":
                    value *= 1000.0
                elif scale == "K":
                    value /= 1000.0
                per_text.setdefault(f"{m.group(1)}_M", []).append(value)
            except Exception:
                pass
        for unit, values in per_text.items():
            if values:
                # A range is represented by its midpoint.  Identical wide ranges
                # therefore never compare one endpoint against the other.
                grouped.setdefault(unit, []).append((min(values) + max(values)) / 2.0)
    return {unit: sum(vals) / len(vals) for unit, vals in grouped.items() if vals}


def _history_values(raw: Any) -> Dict[str, float]:
    if isinstance(raw, Mapping) and isinstance(raw.get("values"), Mapping):
        out = {}
        for unit, value in raw.get("values", {}).items():
            try:
                out[str(unit)] = float(value)
            except Exception:
                pass
        return out
    # Migration from B.1.3.29 list format.  Collapse range endpoints by unit.
    grouped: Dict[str, List[float]] = {}
    for item in raw or []:
        if isinstance(item, list) and len(item) == 2:
            try:
                grouped.setdefault(str(item[1]), []).append(float(item[0]))
            except Exception:
                pass
    return {unit: sum(vals) / len(vals) for unit, vals in grouped.items() if vals}


def kpi_stability_check(state_dir: Optional[str], att_hash: Optional[str],
                        kpis: Iterable[str], lang: str = "fr") -> Optional[str]:
    """Detect a >=2x material KPI change for identical inputs.

    Range endpoints are compared via one midpoint representative, avoiding a
    false alert when the exact same wide range is generated twice.
    """
    if not state_dir or not att_hash:
        return None
    with _KPI_HISTORY_LOCK:
        os.makedirs(state_dir, exist_ok=True)
        path = Path(state_dir) / "kpi_history.json"
        hist: Dict[str, Any] = {}
        try:
            if path.exists():
                hist = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            hist = {}
        current = _representative_million_values(kpis)
        previous = _history_values(hist.get(att_hash))
        note = None
        for unit, pa in previous.items():
            ca = current.get(unit)
            if ca is None or pa <= 0 or ca <= 0:
                continue
            ratio = max(pa, ca) / max(min(pa, ca), 0.001)
            if ratio >= 2.0:
                note = (
                    f"RUN_NUMERIC_INSTABILITY — KPI {unit}: {pa:g} vs {ca:g} à entrées constantes "
                    f"(ratio {ratio:.1f}x) — ne pas utiliser en bandeau exécutif."
                    if lang == "fr" else
                    f"RUN_NUMERIC_INSTABILITY — {unit} KPI: {pa:g} vs {ca:g} on identical inputs ({ratio:.1f}x)."
                )
        # Do not erase a valid prior observation when the current headline was
        # intentionally hidden as unavailable by the evidence guard.
        if current:
            hist[att_hash] = {"version": 2, "values": current}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix="kpi_history_", suffix=".tmp", dir=str(path.parent))
            os.close(fd)
            Path(tmp).write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            try:
                if 'tmp' in locals() and Path(tmp).exists():
                    Path(tmp).unlink()
            except Exception:
                pass
        return note


def has_primary_financial_fact(financial_facts_table: Optional[Mapping[str, Any]]) -> bool:
    rows = ((financial_facts_table or {}).get("facts") or []) if isinstance(financial_facts_table, Mapping) else []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not extract_amounts(str(row.get("value") or "")):
            continue
        if _row_evidence_level(row) == "FAIT":
            return True
    return False


def client_usage_not_recommended(confirmed_on_page: int,
                                 has_primary_financial_fait: bool,
                                 kpis_hypothesis_driven: bool) -> bool:
    return (int(confirmed_on_page or 0) == 0
            and not has_primary_financial_fait
            and bool(kpis_hypothesis_driven))


def apply_client_usage_gate(confidence_score: MutableMapping[str, Any],
                            confirmed_on_page: int,
                            financial_facts_table: Optional[Mapping[str, Any]],
                            kpis_hypothesis_driven: bool,
                            lang: str = "fr") -> bool:
    """Mutate the real confidence-score usage schema when the gate triggers."""
    if not isinstance(confidence_score, MutableMapping):
        return False
    if not client_usage_not_recommended(
        confirmed_on_page,
        has_primary_financial_fact(financial_facts_table),
        kpis_hypothesis_driven,
    ):
        return False
    usage = confidence_score.setdefault("usage_recommendation", {})
    if not isinstance(usage, MutableMapping):
        return False
    usage["client_presentation"] = "Not recommended" if lang == "en" else "Non recommandé"
    confidence_score["executive_evidence_gate"] = {
        "triggered": True,
        "reason": "NO_PAGE_CONFIRMED_NO_PRIMARY_FACT_HYPOTHESIS_KPI",
    }
    return True
