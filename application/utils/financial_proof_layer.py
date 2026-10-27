"""Page-confirmed financial proof ledger — CoDIR IA v62.11.

This module closes the gap exposed by the dossier anglophone coté terrain run:
financial documents were readable by the agents, but their figures did not
become structured, page-confirmed facts consumed by KPI cards, the evidence
score and the final Word/PPTX outputs.

The implementation is deliberately deterministic and independent from LLM
narrative.  It parses only text that is explicitly tied to a document and a
page, normalises metric/value/period/scope, detects material conflicts and
emits ``FinancialFact`` objects carrying a proof status.

OCR is intentionally out of scope.  Image-only scans remain ``OCR_REQUIRED``
until v18.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import math
import hashlib
import re
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

PROOF_LAYER_VERSION = "v62.13.1"

CONFIRMED_ON_PAGE = "CONFIRMED_ON_PAGE"
PAGE_UNAVAILABLE = "PAGE_UNAVAILABLE"
CONFLICT = "CONFLICT"
QUARANTINED = "QUARANTINED"
OCR_REQUIRED = "OCR_REQUIRED"

# Metric identifiers are intentionally more precise than the historic E1 list.
# Reported and adjusted measures must never be collapsed together.
CRITICAL_METRIC_IDS = {
    "REVENUE",
    "OPERATING_PROFIT",
    "ADJUSTED_OPERATING_PROFIT",
    "OPERATING_MARGIN",
    "ADJUSTED_OPERATING_MARGIN",
    "NET_INCOME",
    "FREE_CASH_FLOW",
    "CASH",
    "CASH_NET_OF_OVERDRAFTS",
    "GROSS_DEBT",
    "NET_DEBT",
    "EBITDA",
    "ADJUSTED_EBITDA",
}


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    label_en: str
    label_fr: str
    patterns: tuple[str, ...]
    kind: str = "money"  # money | pct | ratio | persons
    # Lower rank is stronger.
    source_rank: int = 50


_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "ADJUSTED_OPERATING_MARGIN", "Adjusted operating margin",
        "Marge opérationnelle ajustée",
        (r"adjusted\s+operating\s+margin", r"marge\s+op[ée]rationnelle\s+ajust[ée]e"),
        "pct", 10,
    ),
    MetricSpec(
        "OPERATING_MARGIN", "Operating margin", "Marge opérationnelle",
        (r"(?<!adjusted\s)operating\s+margin", r"marge\s+op[ée]rationnelle(?!\s+ajust)"),
        "pct", 10,
    ),
    MetricSpec(
        "ADJUSTED_OPERATING_PROFIT", "Adjusted operating profit",
        "Résultat opérationnel ajusté",
        (r"adjusted\s+operating\s+profit", r"r[ée]sultat\s+op[ée]rationnel\s+ajust[ée]"),
        "money", 10,
    ),
    MetricSpec(
        "OPERATING_PROFIT", "Operating profit / (loss)",
        "Résultat opérationnel / (perte)",
        (
            r"(?<!adjusted\s)operating\s+profit\s*/?\s*\(?loss\)?",
            r"(?<!adjusted\s)(?:reported\s+)?operating\s+(?:profit|loss)",
            # v62.13.9.4.46 — vocabulaire des comptes américains : « Income from operations »,
            # « Operating income ». Run réel de référence du 26/09/2026 : la ligne de résultat
            # d'exploitation du 10-K n'était pas reconnue, et la situation courante ne pouvait
            # pas s'établir faute de résultat d'exploitation confirmé.
            r"(?<!adjusted\s)(?<!non-)income\s+from\s+operations",
            r"(?<!adjusted\s)(?<!non-)operating\s+income(?!\s+tax)",
            r"r[ée]sultat\s+op[ée]rationnel\s*/?\s*\(?perte\)?",
            r"r[ée]sultat\s+d['’]exploitation",
        ),
        "money", 10,
    ),
    MetricSpec(
        "REVENUE", "Revenue", "Chiffre d'affaires",
        (r"^\s*revenue\b", r"^\s*turnover\b", r"^\s*chiffre\s+d['’]affaires\b"),
        "money", 10,
    ),
    MetricSpec(
        "ATTRIBUTABLE_NET_INCOME", "Attributable profit / (loss)",
        "Résultat net attribuable",
        (r"attributable\s+profit\s*/?\s*\(?loss\)?",
         r"profit\s*/?\s*\(?loss\)?\s+attributable"),
        "money", 15,
    ),
    MetricSpec(
        "NET_INCOME", "Profit / (loss) for the year", "Résultat net",
        (r"profit\s*/?\s*\(?loss\)?\s+for\s+the\s+(?:year|period)",
         r"^\s*net\s+(?:income|profit|loss)", r"^\s*r[ée]sultat\s+net"),
        "money", 10,
    ),
    MetricSpec(
        "FREE_CASH_FLOW", "Free cash flow", "Free cash-flow",
        (r"^\s*free\s+cash\s+flow(?!\s+before\s+tax)\b", r"^\s*FCF\b"), "money", 20,
    ),
    MetricSpec(
        "CASH_NET_OF_OVERDRAFTS", "Cash net of overdrafts",
        "Trésorerie nette des découverts",
        (r"^\s*cash\s+net\s+of\s+overdrafts\b", r"^\s*tr[ée]sorerie\s+nette\s+des\s+d[ée]couverts"),
        "money", 20,
    ),
    MetricSpec(
        "CASH", "Cash and cash equivalents", "Trésorerie et équivalents",
        (r"cash\s+and\s+cash\s+equivalents", r"tr[ée]sorerie\s+et\s+[ée]quivalents"),
        "money", 10,
    ),
    MetricSpec(
        "ADJUSTED_EBITDA", "Adjusted EBITDA", "EBITDA ajusté",
        (r"^\s*adjusted\s+EBITDA\b", r"^\s*EBITDA\s+ajust[ée]\b"), "money", 20,
    ),
    MetricSpec(
        "EBITDA", "EBITDA", "EBITDA",
        (r"^\s*(?<!adjusted\s)EBITDA\b",), "money", 30,
    ),
    MetricSpec(
        "NET_DEBT", "Net debt", "Dette nette",
        (r"^\s*net\s+debt\b", r"^\s*dette\s+nette\b"), "money", 20,
    ),
    MetricSpec(
        "GROSS_DEBT", "Borrowings", "Dette brute",
        (r"^\s*(?:total\s+)?borrowings\b", r"^\s*dette\s+brute\b"), "money", 20,
    ),
    MetricSpec(
        "STOCKS", "Inventories", "Stocks",
        (r"^\s*inventories\b", r"^\s*stocks?\b"), "money", 10,
    ),
    MetricSpec(
        "HEADCOUNT", "Headcount", "Effectif",
        (r"number\s+of\s+employees", r"\bheadcount\b", r"\beffectif\b"),
        "persons", 20,
    ),
)


@dataclass
class PageRecord:
    source_doc: str
    source_page: int
    section: str
    text: str
    origin: str = "financial_statements_block"


@dataclass
class ParsedValue:
    raw: str
    numeric: float
    normalized: float
    unit: str
    currency: str
    scale: str
    formatted: str


@dataclass
class ProofCandidate:
    metric_id: str
    label: str
    value: str
    source_value_text: str
    normalized_value: float
    unit: str
    currency: str
    scale: str
    period: str
    period_end_date: str
    scope: str
    source_doc: str
    source_page: int
    source_section: str
    source_excerpt: str
    proof_status: str = CONFIRMED_ON_PAGE
    # v62.13.1 — deux dimensions distinctes : la preuve reste confirmée,
    # tandis que le rôle indique si le fait est courant, historique,
    # post-clôture ou supplanté par une source plus forte.
    canonical_role: str = "CURRENT"
    definition_axis: str = ""
    source_rank: int = 50
    board_safe_blockers: list[str] = field(default_factory=list)
    conflict_group_id: str = ""
    conflict_detail: dict[str, Any] = field(default_factory=dict)


_DOC_FS = re.compile(r"---\s*📄?\s*(.+?\.pdf)(?:\s*\([^)]*\))?\s*---", re.I)
_DOC_ATTACHMENT = re.compile(r"^###\s+(?:Fichier|File)\s*:\s*(.+?)\s*$", re.I)
_SECTION = re.compile(r"^###\s+(.+?)\s*$")
_PAGE_FS = re.compile(r"^--\s*p\.?\s*(\d{1,4})\s*--\s*$", re.I)
_PAGE_ATTACHMENT = re.compile(r"^##\s+Page\s+(\d{1,4})\s*$", re.I)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    "decembre": 12,
}
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December|janvier|février|fevrier|mars|avril|"
    r"mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\s+"
    r"(20\d{2})\b", re.I,
)
_FY_RE = re.compile(r"\bFY\s*(?:20)?(\d{2})(?:\s*/\s*(?:20)?(\d{2}))?\b", re.I)

_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
    r"September|October|November|December|janvier|février|fevrier|mars|avril|"
    r"mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)\b", re.I)

# Numeric tokens occurring in financial rows.  Dates and pure years are
# removed later; percentages, bps and x ratios keep their dimensions.
_VALUE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<open>\()?\s*(?P<sign>[-−])?\s*"
    r"(?P<num>\d{1,3}(?:[,\u00a0\u202f]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<close>\))?\s*(?P<suffix>%|bps|x)?(?![A-Za-z0-9])",
    re.I,
)


def _normalise_section(title: str) -> str:
    low = re.sub(r"\s+", " ", str(title or "").strip().lower())
    if "financial review" in low or "financial measures" in low:
        return "financial_review"
    if "consolidated financial statements" in low or "group financial statements" in low:
        return "financial_statements"
    if "income statement" in low or "profit and loss" in low or "compte de résultat" in low:
        return "income_statement"
    if "balance sheet" in low or "financial position" in low or "bilan" in low:
        return "balance_sheet"
    if "cash flow" in low or "flux de trésorerie" in low:
        return "cash_flow"
    if "notes" in low:
        return "notes"
    return low[:80] or "unknown"


def parse_paged_corpus(financial_statements_block: str = "",
                       attachments_block: str = "") -> list[PageRecord]:
    """Parse the two paginated corpus formats emitted by CoDIR IA."""
    pages: list[PageRecord] = []

    def consume(text: str, origin: str) -> None:
        if not isinstance(text, str) or not text.strip():
            return
        doc = ""
        section = "unknown"
        page_no: Optional[int] = None
        buf: list[str] = []

        def flush() -> None:
            nonlocal buf
            if doc and page_no is not None and buf:
                body = "\n".join(buf).strip()
                if body:
                    pages.append(PageRecord(doc, int(page_no), section, body, origin))
            buf = []

        for raw in text.splitlines():
            line = raw.rstrip("\r")
            mdoc = _DOC_FS.match(line.strip()) or _DOC_ATTACHMENT.match(line.strip())
            if mdoc:
                flush()
                doc = mdoc.group(1).strip()
                page_no = None
                section = "unknown"
                continue
            msec = _SECTION.match(line.strip())
            if msec and not _DOC_ATTACHMENT.match(line.strip()):
                # Attachment format uses ### File: as document marker (handled above).
                flush()
                section = _normalise_section(msec.group(1))
                page_no = None
                continue
            mp = _PAGE_FS.match(line.strip()) or _PAGE_ATTACHMENT.match(line.strip())
            if mp:
                flush()
                page_no = int(mp.group(1))
                continue
            if page_no is not None:
                buf.append(line)
        flush()

    consume(financial_statements_block or "", "financial_statements_block")
    consume(attachments_block or "", "attachments_block")

    # Deduplicate the same document/page when it appears in both corpora.
    dedup: dict[tuple[str, int], PageRecord] = {}
    for p in pages:
        key = (_norm_doc(p.source_doc), p.source_page)
        cur = dedup.get(key)
        if cur is None or len(p.text) > len(cur.text):
            dedup[key] = p
    return list(dedup.values())


def _norm_doc(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _iso_date(day: str, month: str, year: str) -> str:
    m = _MONTHS.get(month.lower())
    if not m:
        return ""
    try:
        return datetime(int(year), int(m), int(day)).date().isoformat()
    except ValueError:
        return ""


def _header_periods(page_text: str) -> list[tuple[str, str]]:
    """Return ordered (period_label, end_date) columns for a page.

    Handles both compact text (``28 March 2026 29 March 2025``) and layout
    extraction where dates and years are on consecutive rows:
    ``28 March   29 March`` then ``2026   2025``.
    """
    lines = [re.sub(r"\s+", " ", x).strip() for x in page_text.splitlines() if x.strip()]

    # Layout-table form: day/month columns followed by the year columns.
    for i, line in enumerate(lines[:24]):
        dm = list(_DAY_MONTH_RE.finditer(line))
        if len(dm) < 2:
            continue
        for next_line in lines[i + 1:min(len(lines), i + 5)]:
            years = re.findall(r"\b(20\d{2})\b", next_line)
            if len(years) >= len(dm):
                out = []
                for m, year in zip(dm, years):
                    iso = _iso_date(m.group(1), m.group(2), year)
                    if iso:
                        out.append((f"FY{year}", iso))
                if len(out) >= 2:
                    return out

    windows: list[str] = lines[:18]
    windows += [" ".join(lines[i:i + 2]) for i in range(min(14, max(0, len(lines) - 1)))]
    for win in windows:
        dates = []
        for m in _DATE_RE.finditer(win):
            iso = _iso_date(m.group(1), m.group(2), m.group(3))
            if iso:
                dates.append((f"FY{m.group(3)}", iso, m.start()))
        if len(dates) >= 2:
            dates.sort(key=lambda x: x[2])
            out: list[tuple[str, str]] = []
            for label, iso, _ in dates:
                if (label, iso) not in out:
                    out.append((label, iso))
            return out
        fys = []
        for m in _FY_RE.finditer(win):
            yy1, yy2 = int(m.group(1)), m.group(2)
            end_year = 2000 + (int(yy2) if yy2 else yy1)
            fys.append((f"FY{end_year}", f"{end_year}-12-31", m.start()))
        if len(fys) >= 2:
            fys.sort(key=lambda x: x[2])
            return [(a, b) for a, b, _ in fys]
    return []

def _page_currency_scale(text: str, spec: MetricSpec) -> tuple[str, str]:
    if spec.kind in {"pct", "ratio", "persons"}:
        return "", ""
    head = "\n".join(text.splitlines()[:30])
    if re.search(r"£\s*(?:million|m)\b|\b£m\b", head, re.I):
        return "GBP", "M"
    if re.search(r"€\s*(?:million|m)\b|\b€m\b|\bM€\b", head, re.I):
        return "EUR", "M"
    if re.search(r"\$\s*(?:million|m)\b|\b\$m\b|\bM\$\b", head, re.I):
        return "USD", "M"
    if "£" in text:
        return "GBP", "M" if re.search(r"£\s*million", text, re.I) else ""
    if "€" in text:
        return "EUR", "M" if re.search(r"€\s*million", text, re.I) else ""
    if "$" in text:
        return "USD", "M" if re.search(r"\$\s*million", text, re.I) else ""
    return "", ""


def _token_values(text: str) -> list[ParsedValue]:
    out: list[ParsedValue] = []
    for m in _VALUE_TOKEN_RE.finditer(text):
        raw = m.group(0).strip()
        num_s = re.sub(r"[ ,\u00a0\u202f]", "", m.group("num"))
        try:
            val = float(num_s)
        except ValueError:
            continue
        if m.group("open") and m.group("close") or m.group("sign"):
            val = -abs(val)
        suffix = (m.group("suffix") or "").lower()
        if suffix == "%":
            out.append(ParsedValue(raw, val, val, "PCT", "", "", f"{val:g}%"))
        elif suffix == "bps":
            out.append(ParsedValue(raw, val, val, "BPS", "", "", f"{val:g}bps"))
        elif suffix == "x":
            out.append(ParsedValue(raw, val, val, "RATIO", "", "", f"{val:g}x"))
        else:
            out.append(ParsedValue(raw, val, val, "", "", "", _format_plain_number(val)))
    return out


def _format_plain_number(v: float) -> str:
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:g}"


def _money_value(p: ParsedValue, currency: str, scale: str) -> ParsedValue:
    mult = {"k": 1e3, "M": 1e6, "Md": 1e9}.get(scale, 1.0)
    normalized = p.numeric * mult
    sym = {"GBP": "£", "EUR": "€", "USD": "$"}.get(currency, "")
    abs_v = abs(p.numeric)
    core = f"{abs_v:,.0f}" if abs_v.is_integer() else f"{abs_v:,.1f}".rstrip("0").rstrip(".")
    formatted = f"{sym}({core}){scale.lower()}" if p.numeric < 0 else f"{sym}{core}{scale.lower()}"
    if not sym and scale:
        formatted = f"{core} {scale}" if p.numeric >= 0 else f"({core}) {scale}"
    return ParsedValue(p.raw, p.numeric, normalized, "CUR", currency, scale, formatted)


def _persons_value(p: ParsedValue) -> ParsedValue:
    return ParsedValue(p.raw, p.numeric, p.numeric, "PERSONS", "", "",
                       f"{int(p.numeric):,} employees")


def _scope_for_page(page: PageRecord) -> str:
    head = " ".join(page.text.splitlines()[:8]).lower()
    if re.search(r"\bcompany\s+(?:income\s+statement|balance\s+sheet|statement)", head):
        return "SOCIAL_STANDALONE"
    if (re.search(r"\b(group|consolidated)\b", head)
            or page.section in {"financial_review", "financial_statements"}
            or "financial review" in head):
        return "CONSOLIDATED"
    return "UNKNOWN"


def _source_rank(page: PageRecord, spec: MetricSpec) -> int:
    head = " ".join(page.text.splitlines()[:8]).lower()
    if re.search(r"group\s+(?:income\s+statement|balance\s+sheet|statement\s+of\s+cash\s+flows)", head):
        return min(spec.source_rank, 5)
    if page.section == "financial_review" or "financial review" in head:
        return min(spec.source_rank, 15)
    return spec.source_rank


def _match_metric(line: str) -> tuple[MetricSpec, re.Match[str]] | None:
    compact = re.sub(r"\s+", " ", line).strip()
    for spec in _METRICS:
        for pat in spec.patterns:
            m = re.search(pat, compact, re.I)
            if m:
                # For anchored rows, avoid a narrative sentence that merely
                # mentions the metric unless the page is a financial review.
                return spec, m
    return None


def _drop_note_token(values: list[ParsedValue], periods: Sequence[tuple[str, str]],
                     *, explicit_note: bool = False) -> list[ParsedValue]:
    if not explicit_note or len(values) <= len(periods):
        return values
    first = values[0]
    first_raw = re.sub(r"\D", "", first.raw)
    if first_raw and first.numeric >= 0 and first.numeric <= 40 and len(values[1:]) >= len(periods):
        return values[1:]
    return values

def _line_candidates(page: PageRecord) -> list[ProofCandidate]:
    periods = _header_periods(page.text)
    if not periods:
        return []
    out: list[ProofCandidate] = []
    page_head = " ".join(page.text.splitlines()[:10]).lower()
    audited_page = bool(page.section == "financial_statements" or re.search(
        r"group\s+(?:income\s+statement|balance\s+sheet|statement\s+of\s+cash\s+flows)",
        page_head))
    for raw_line in page.text.splitlines():
        if not raw_line.strip():
            continue
        compact = re.sub(r"\s+", " ", raw_line).strip()
        mm = _match_metric(compact)
        if not mm:
            continue
        spec, match = mm
        # The metric label must be followed directly by numeric columns (and
        # an optional note marker). Lines such as "cash net of overdrafts at
        # beginning of year" describe movements, not the closing metric.
        semantic_tail = compact[match.end():]
        semantic_before_number = re.split(r"[£€$()\-−+]?\d", semantic_tail, maxsplit=1)[0]
        semantic_words = re.findall(r"[A-Za-zÀ-ÿ]+", semantic_before_number)
        # Metric units are frequently glued to the label by PDF extraction
        # (e.g. ``Adjusted operating profit* £m 160 26``).  They do not
        # turn a tabular row into narrative prose and must therefore be
        # accepted before the first numeric cell.
        allowed_pre_number = {
            "note", "m", "mn", "bn", "million", "millions",
            "billion", "eur", "gbp", "usd", "percent", "pct",
        }
        if [w for w in semantic_words if w.lower() not in allowed_pre_number]:
            continue
        # A statutory balance sheet usually lists current and non-current
        # borrowings separately. Bare "Borrowings" rows are not a gross-debt
        # total; the Financial Review total row remains eligible.
        if (spec.metric_id == "GROSS_DEBT"
                and (page.section == "balance_sheet" or "group balance sheet" in page_head)
                and not re.search(r"^\s*total\s+borrowings", compact, re.I)):
            continue

        if "|" in raw_line:
            cells = [c.strip() for c in raw_line.split("|") if c.strip()]
        else:
            cells = [c.strip() for c in re.split(r"\s{2,}", raw_line.strip()) if c.strip()]

        explicit_note = False
        vals: list[ParsedValue] = []
        if len(cells) >= 2:
            label_idx = None
            for idx, cell in enumerate(cells):
                if _match_metric(re.sub(r"\s+", " ", cell).strip()):
                    label_idx = idx
                    break
            if label_idx is None:
                continue
            label_cell = cells[label_idx]
            label_match = _match_metric(re.sub(r"\s+", " ", label_cell).strip())
            assert label_match is not None
            _spec2, lm = label_match
            remainder = label_cell[lm.end():].strip(" *")
            value_cells = ([remainder] if remainder else []) + cells[label_idx + 1:]
            explicit_note = bool(re.search(r"\bnote\s*\d", label_cell, re.I))
            # Audited tables often have a dedicated note-number cell.
            if audited_page and value_cells and re.fullmatch(r"\d{1,2}", value_cells[0]):
                explicit_note = True
            for cell in value_cells:
                toks = _token_values(cell)
                if toks:
                    vals.append(toks[0])
        else:
            # pdfplumber sometimes collapses a row into single-space text.
            # Accept only a compact row: after the metric label, no narrative
            # sentence and enough numeric cells for all periods.
            remainder = compact[match.end():].strip(" *")
            alpha = [w.lower() for w in re.findall(r"[A-Za-z]+", remainder)]
            allowed = {"flat", "reported", "fx", "cer", "n", "a", "nil",
                       "m", "mn", "bn", "million", "millions", "billion",
                       "eur", "gbp", "usd"}
            if len([w for w in alpha if w not in allowed]) > 2:
                continue
            vals = _token_values(remainder)
            explicit_note = audited_page and bool(
                vals and len(vals) >= len(periods) + 1 and
                vals[0].numeric >= 0 and vals[0].numeric <= 40)

        vals = [v for v in vals
                if not (1900 <= abs(v.numeric) <= 2100 and v.numeric.is_integer())]
        if not vals:
            continue
        vals = _drop_note_token(vals, periods, explicit_note=explicit_note)
        if len(vals) < len(periods):
            continue

        currency, scale = _page_currency_scale(page.text, spec)
        if spec.kind == "money" and not (currency and scale):
            continue

        for idx, (period, end_date) in enumerate(periods):
            pv = vals[idx]
            if spec.kind == "money":
                if spec.metric_id in {"CASH", "CASH_NET_OF_OVERDRAFTS", "GROSS_DEBT", "NET_DEBT"}:
                    pv = ParsedValue(pv.raw, abs(pv.numeric), abs(pv.numeric),
                                     pv.unit, pv.currency, pv.scale, pv.formatted)
                pv = _money_value(pv, currency, scale)
            elif spec.kind == "persons":
                if re.search(r"stores?|shops?|doors?|boutiques?|points?\s+of\s+sale", raw_line, re.I):
                    continue
                pv = _persons_value(pv)
            elif spec.kind == "pct" and pv.unit != "PCT":
                pv = ParsedValue(pv.raw, pv.numeric, pv.numeric, "PCT", "", "", f"{pv.numeric:g}%")
            elif spec.kind == "ratio" and pv.unit != "RATIO":
                pv = ParsedValue(pv.raw, pv.numeric, pv.numeric, "RATIO", "", "", f"{pv.numeric:g}x")
            out.append(ProofCandidate(
                metric_id=spec.metric_id,
                label=spec.label_en,
                value=pv.formatted,
                source_value_text=pv.raw,
                normalized_value=pv.normalized,
                unit=pv.unit or ("CUR" if spec.kind == "money" else ""),
                currency=pv.currency,
                scale=pv.scale,
                period=period,
                period_end_date=end_date,
                scope=_scope_for_page(page),
                source_doc=page.source_doc,
                source_page=page.source_page,
                source_section=page.section,
                source_excerpt=compact[:500],
                source_rank=_source_rank(page, spec),
            ))
    return out

def _narrative_candidates(page: PageRecord,
                          fallback_periods: Sequence[tuple[str, str]] | None = None) -> list[ProofCandidate]:
    """Extract metrics expressed in financial-review prose.

    A narrative page can omit the fiscal dates because they are stated on the
    first page of the same financial-review section; document-level periods are
    therefore accepted as deterministic fallback.
    """
    periods = _header_periods(page.text) or list(fallback_periods or [])
    by_year = {int(d[:4]): (p, d) for p, d in periods if d}
    out: list[ProofCandidate] = []
    text = re.sub(r"\s+", " ", page.text)
    patterns: tuple[tuple[str, str, str], ...] = (
        ("FREE_CASH_FLOW", "Free cash flow", r"Free cash flow was £([\d,]+) million in the year \(FY\s*2024/25:\s*£([\d,]+) million\)"),
        ("CASH_NET_OF_OVERDRAFTS", "Cash net of overdrafts", r"Cash net of overdrafts on 28 March 2026 was £([\d,]+) million \(29 March 2025:\s*£([\d,]+) million\)"),
        ("NET_DEBT", "Net debt", r"net debt in the period was £([\d,]+) million \(29 March 2025:\s*£([\d,]+) million\)"),
    )
    for metric_id, label, pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        for raw, year in zip(m.groups(), (2026, 2025)):
            numeric = float(raw.replace(",", ""))
            period, end_date = by_year.get(year, (f"FY{year}", f"{year}-12-31"))
            out.append(ProofCandidate(
                metric_id=metric_id, label=label,
                value=f"£{numeric:,.0f}m", source_value_text=raw,
                normalized_value=numeric * 1e6, unit="CUR", currency="GBP", scale="M",
                period=period, period_end_date=end_date, scope="CONSOLIDATED",
                source_doc=page.source_doc, source_page=page.source_page,
                source_section=page.section, source_excerpt=m.group(0)[:500],
                source_rank=15,
            ))
    return out


def _candidate_key(c: ProofCandidate) -> tuple[str, str, str, str, str]:
    """Legacy identity, including the display period.

    Retained only for the no-authority compatibility path.  The v62.13.1
    authority path groups by economic identity first, then partitions by a
    normalised period end and definition axis.
    """
    return (c.metric_id, c.period, c.scope, c.currency, c.unit)


def _economic_candidate_key(c: ProofCandidate) -> tuple[str, str, str, str]:
    return (c.metric_id, c.scope, c.currency, c.unit)


def _materially_different(a: float, b: float, unit: str) -> bool:
    if unit in {"PCT", "BPS", "RATIO"}:
        return abs(a - b) > 0.15
    # v62.12.2 — aucune tolérance monétaire absolue universelle : 1 M€ est
    # immatériel pour un groupe coté mais peut être déterminant pour une PME.
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom > 0.01


# ── v62.13.1 — preuve et rôle canonique sont orthogonaux ───────────────────
CANONICAL_CURRENT = "CURRENT"
# Compatibility/readability alias used by acceptance tests and downstream code.
CURRENT_CANONICAL = CANONICAL_CURRENT
CONTRIBUTING_HISTORY = "CONTRIBUTING_HISTORY"
POST_CLOSE_INDICATION = "POST_CLOSE_INDICATION"
SUPERSEDED = "SUPERSEDED"

_STOCK_METRICS = {
    "CASH", "CASH_AND_EQUIVALENTS", "CASH_NET_OF_OVERDRAFTS", "NET_DEBT",
    "GROSS_DEBT", "FINANCIAL_DEBT", "EQUITY", "STOCKS",
}

_DEFINITION_AXES = (
    ("pre_ifrs16", re.compile(r"pre[- ]?ifrs\s*16|hors\s+ifrs\s*16|excluding\s+ifrs\s*16", re.I)),
    ("post_ifrs16", re.compile(r"post[- ]?ifrs\s*16|including\s+ifrs\s*16|ifrs\s*16\s+incluse?", re.I)),
    ("adjusted_apm", re.compile(r"\badjust(?:ed|é)e?s?\b|\bunderlying\b|\bapm\b|hors\s+(?:él[ée]ments|items)", re.I)),
    ("statutory", re.compile(r"\bstatutory\b|\breported\b|\bcomptable\b|\bpubli[ée]e?\b", re.I)),
)

_RESTATED_RE = re.compile(r"\brestated\b|\bre[- ]?presented\b|\bretrait[ée]e?s?\b", re.I)


def _definition_axis(c: "ProofCandidate") -> str:
    hay = " ".join([
        str(getattr(c, "label", "") or ""),
        str(getattr(c, "source_value_text", "") or ""),
        str(getattr(c, "source_excerpt", "") or "")[:600],
    ])
    for axis, rx in _DEFINITION_AXES:
        if rx.search(hay):
            return axis
    return ""


def _is_restated(c: "ProofCandidate") -> bool:
    hay = " ".join([
        str(getattr(c, "label", "") or ""),
        str(getattr(c, "source_excerpt", "") or "")[:600],
    ])
    return bool(_RESTATED_RE.search(hay))


def _parse_period_end(value: Any) -> Optional[date]:
    """Parse the period end into a real date; never compare raw strings."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    # ISO / year-first, with or without zero padding.
    m = re.fullmatch(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # Common FR/UK day-first representation.
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](20\d{2})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    # Day + month name + year.
    m = _DATE_RE.search(text)
    if m:
        iso = _iso_date(m.group(1), m.group(2), m.group(3))
        if iso:
            return date.fromisoformat(iso)
    return None


def normalize_period_end(value: Any) -> str:
    parsed = _parse_period_end(value)
    return parsed.isoformat() if parsed else ""


def _effective_period_end(c: "ProofCandidate") -> str:
    return normalize_period_end(getattr(c, "period_end_date", ""))


def _role_for_period(c: ProofCandidate, auth_date: Optional[date]) -> str:
    pe = _parse_period_end(getattr(c, "period_end_date", ""))
    if auth_date is None or pe is None:
        return CANONICAL_CURRENT
    if pe == auth_date:
        return CANONICAL_CURRENT
    if pe < auth_date:
        return CONTRIBUTING_HISTORY
    # A later interim/current observation is visible but never replaces the
    # latest closed annual authority.  The R3 contract named stock metrics;
    # the same non-canonical posture is safer for any post-close period.
    return POST_CLOSE_INDICATION


def compute_dossier_authoritative_period_end(
        candidates: Iterable["ProofCandidate"]) -> str:
    """Latest annual page-confirmed close, emitted in ISO format.

    This helper is consumed both by the v62.13 Financial Proof Layer and by
    the older B1 structured-fact layer.  Legacy ``FinancialFact`` rows often
    carry ``status=FAIT`` while leaving ``proof_status`` empty, so an empty
    proof_status is accepted only for an explicit factual status.  Interim
    labels (H1/Q1/LTM) are never promoted to annual authority.
    """
    dates: list[date] = []
    annual_label = re.compile(r"^(?:FY\s*)?(?:19|20)\d{2}(?:\s*/\s*\d{2,4})?$", re.I)
    for c in candidates or []:
        proof = str(getattr(c, "proof_status", "") or "").strip()
        if proof and proof != CONFIRMED_ON_PAGE:
            continue
        if not proof:
            status_obj = getattr(c, "status", None)
            status = str(getattr(status_obj, "value", status_obj) or "").upper()
            if status and status not in {"FAIT", "FACT"}:
                continue
        period = str(getattr(c, "period", "") or "").strip()
        if not annual_label.fullmatch(period):
            continue
        parsed = (_parse_period_end(getattr(c, "period_end_date", ""))
                  or _parse_period_end(getattr(c, "document_date", "")))
        if parsed:
            dates.append(parsed)
    return max(dates).isoformat() if dates else ""


def _legacy_reconcile_candidates(candidates: Iterable[ProofCandidate]) -> list[ProofCandidate]:
    """Exact strict compatibility path used when no authority is available."""
    groups: dict[tuple[str, str, str, str, str], list[ProofCandidate]] = {}
    for c in candidates:
        groups.setdefault(_candidate_key(c), []).append(c)
    out: list[ProofCandidate] = []
    for key, rows in groups.items():
        rows.sort(key=lambda c: (c.source_rank, -len(c.source_excerpt)))
        reference = rows[0]
        conflicts = [r for r in rows[1:]
                     if _materially_different(reference.normalized_value,
                                              r.normalized_value, reference.unit)]
        if conflicts:
            gid = "FPL-CONFLICT-" + "-".join(
                re.sub(r"[^A-Z0-9]+", "", x.upper())[:18] for x in key[:3])
            detail = {
                "metric_id": key[0], "period": key[1], "scope": key[2],
                "currency": key[3], "unit": key[4],
                "values": [{
                    "value": r.normalized_value,
                    "value_text": getattr(r, "source_value_text", ""),
                    "source_doc": r.source_doc,
                    "source_page": r.source_page,
                    "source_rank": getattr(r, "source_rank", None),
                } for r in rows],
                "reason": "value_divergence_same_identity",
            }
            for r in rows:
                r.proof_status = CONFLICT
                r.canonical_role = CANONICAL_CURRENT
                r.conflict_group_id = gid
                r.conflict_detail = dict(detail)
                if "hard_metric_scope_conflict" not in r.board_safe_blockers:
                    r.board_safe_blockers.append("hard_metric_scope_conflict")
                out.append(r)
            continue
        reference.canonical_role = CANONICAL_CURRENT
        out.append(reference)
    return out


def _mark_superseded(row: ProofCandidate, *, reason: str,
                     winner: Optional[ProofCandidate] = None) -> None:
    row.proof_status = CONFIRMED_ON_PAGE
    row.canonical_role = SUPERSEDED
    row.board_safe_blockers = [b for b in row.board_safe_blockers
                               if b != "hard_metric_scope_conflict"]
    row.conflict_detail = {
        "resolution": reason,
        "winner_source_doc": getattr(winner, "source_doc", "") if winner else "",
        "winner_source_page": getattr(winner, "source_page", None) if winner else None,
    }


def _resolve_same_period_group(rows: list[ProofCandidate],
                               economic_key: tuple[str, str, str, str],
                               period_key: str,
                               role: str) -> list[ProofCandidate]:
    """Resolve one metric/scope/definition/period partition."""
    if not rows:
        return []
    for r in rows:
        r.canonical_role = role
        r.proof_status = CONFIRMED_ON_PAGE
        r.board_safe_blockers = [b for b in r.board_safe_blockers
                                 if b != "hard_metric_scope_conflict"]
    # Restated/re-presented outranks the original within the same period, but
    # two restated values of equal authority may still be a genuine conflict.
    restated = [r for r in rows if _is_restated(r)]
    originals = [r for r in rows if r not in restated]
    if restated and originals:
        resolved_restated = _resolve_same_period_group(
            restated, economic_key, period_key, role)
        winner = next((r for r in resolved_restated
                       if r.proof_status == CONFIRMED_ON_PAGE
                       and r.canonical_role != SUPERSEDED), None)
        for r in originals:
            _mark_superseded(r, reason="superseded_by_restated", winner=winner)
        return resolved_restated + originals

    rows = sorted(rows, key=lambda c: (c.source_rank, -len(c.source_excerpt)))
    best_rank = rows[0].source_rank
    top = [r for r in rows if r.source_rank == best_rank]
    weaker = [r for r in rows if r.source_rank != best_rank]
    top_ref = top[0]
    top_conflicts = [r for r in top[1:]
                     if _materially_different(top_ref.normalized_value,
                                              r.normalized_value, top_ref.unit)]
    if not top_conflicts:
        for r in weaker:
            _mark_superseded(r, reason="superseded_by_document_hierarchy",
                             winner=top_ref)
        # Concordant duplicate top sources are also retained only as provenance,
        # not as additional canonical rows.
        for r in top[1:]:
            _mark_superseded(r, reason="duplicate_concordant_source", winner=top_ref)
        return [top_ref] + [r for r in rows if r is not top_ref]

    # Same period, same definition and equal document authority: genuine hard conflict.
    gid_material = "|".join([*economic_key, period_key,
                              str(getattr(top_ref, "definition_axis", "") or "")])
    gid = "FPL-CONFLICT-" + hashlib.sha256(gid_material.encode("utf-8")).hexdigest()[:18]
    detail = {
        "conflict_group_id": gid,
        "metric_id": economic_key[0],
        "period_end": period_key,
        "period": period_key,
        "scope": economic_key[1],
        "currency": economic_key[2],
        "unit": economic_key[3],
        "definition_axis": str(getattr(top_ref, "definition_axis", "") or ""),
        "definition": str(getattr(top_ref, "definition_axis", "") or ""),
        "values": [{
            "value": r.normalized_value,
            "value_text": getattr(r, "source_value_text", ""),
            "source_doc": r.source_doc,
            "source_page": r.source_page,
            "source_rank": r.source_rank,
            "source_section": getattr(r, "source_section", ""),
        } for r in top],
        "reason": "value_divergence_same_period_definition_and_rank",
    }
    result: list[ProofCandidate] = []
    for r in top:
        r.proof_status = CONFLICT
        r.canonical_role = role
        r.conflict_group_id = gid
        r.conflict_detail = dict(detail)
        if "hard_metric_scope_conflict" not in r.board_safe_blockers:
            r.board_safe_blockers.append("hard_metric_scope_conflict")
        result.append(r)
    for r in weaker:
        _mark_superseded(r, reason="superseded_by_document_hierarchy",
                         winner=top_ref)
        result.append(r)
    return result


def reconcile_candidates(candidates: Iterable[ProofCandidate], *,
                         authoritative_period_end: str | None = None
                         ) -> list[ProofCandidate]:
    """Reconcile proof candidates without conflating evidence and chronology.

    With an authority, grouping is performed in two stages: economic identity
    excluding period, then definition axis and normalised period end.  Earlier
    and post-close facts remain page-confirmed and usable for comparisons; only
    unresolved same-period/same-definition/equal-rank divergences become hard
    conflicts.  Without an authority the legacy strict behaviour is preserved.
    """
    rows_all = list(candidates or [])
    auth_date = _parse_period_end(authoritative_period_end)
    if auth_date is None:
        return _legacy_reconcile_candidates(rows_all)

    groups: dict[tuple[str, str, str, str], list[ProofCandidate]] = {}
    for c in rows_all:
        norm = normalize_period_end(getattr(c, "period_end_date", ""))
        if norm:
            c.period_end_date = norm
        c.definition_axis = _definition_axis(c)
        groups.setdefault(_economic_candidate_key(c), []).append(c)

    out: list[ProofCandidate] = []
    for economic_key, econ_rows in groups.items():
        # Explicit definition axes are independent facts.  Unlabelled rows form
        # their own default axis and may still conflict with one another.
        by_axis: dict[str, list[ProofCandidate]] = {}
        for r in econ_rows:
            by_axis.setdefault(r.definition_axis or "__default__", []).append(r)
        for axis_key, axis_rows in by_axis.items():
            by_period: dict[str, list[ProofCandidate]] = {}
            for r in axis_rows:
                pe = normalize_period_end(getattr(r, "period_end_date", ""))
                period_key = pe or str(getattr(r, "period", "") or "UNKNOWN")
                by_period.setdefault(period_key, []).append(r)
            for period_key, period_rows in by_period.items():
                role = _role_for_period(period_rows[0], auth_date)
                resolved = _resolve_same_period_group(
                    period_rows, economic_key, period_key, role)
                # Make the authority and role auditable on every non-conflict row.
                for r in resolved:
                    if r.proof_status == CONFIRMED_ON_PAGE and not r.conflict_detail:
                        r.conflict_detail = {
                            "resolution": (
                                "authoritative_current" if r.canonical_role == CANONICAL_CURRENT
                                else "contributing_history" if r.canonical_role == CONTRIBUTING_HISTORY
                                else "post_close_indication" if r.canonical_role == POST_CLOSE_INDICATION
                                else "superseded"
                            ),
                            "authoritative_period_end": auth_date.isoformat(),
                            "period_end": normalize_period_end(getattr(r, "period_end_date", "")),
                            "definition_axis": r.definition_axis or "",
                        }
                out.extend(resolved)
    return out

def _candidate_to_fact(c: ProofCandidate, lang: str = "en"):
    from utils.financial_facts_table import FinancialFact, FactStatus
    label = c.label
    if str(lang or "en").lower().startswith("fr"):
        for s in _METRICS:
            if s.metric_id == c.metric_id:
                label = s.label_fr
                break
    _stable_material = "|".join((c.metric_id, c.period, c.scope, c.currency, c.unit, c.definition_axis or ""))
    _stable_key = hashlib.sha256(_stable_material.encode("utf-8")).hexdigest()[:24]
    _instance_material = f"{_stable_key}|{c.source_doc}|{c.source_page}|{c.source_value_text}"
    _instance_id = hashlib.sha256(_instance_material.encode("utf-8")).hexdigest()[:24]
    fact = FinancialFact(
        label=label,
        value=c.value,
        source_doc=c.source_doc,
        source_page=c.source_page,
        source_section=c.source_section,
        status=FactStatus.FAIT if c.proof_status == CONFIRMED_ON_PAGE else FactStatus.A_VERIFIER,
        confidence=1.0 if c.proof_status == CONFIRMED_ON_PAGE else 0.3,
        notes=(["Contributing history — page-confirmed, non-current "
                f"({PROOF_LAYER_VERSION})"] if c.canonical_role == CONTRIBUTING_HISTORY
               else ["Post-close indication — page-confirmed, never canonical "
                     f"({PROOF_LAYER_VERSION})"] if c.canonical_role == POST_CLOSE_INDICATION
               else ["Superseded page-confirmed source — diagnostics only "
                     f"({PROOF_LAYER_VERSION})"] if c.canonical_role == SUPERSEDED
               else [f"Page-confirmed financial proof ({PROOF_LAYER_VERSION})"]),
        scope=c.scope,
        allowed_uses=(["comparison", "diagnostics", "trend"]
                      if c.canonical_role == CONTRIBUTING_HISTORY
                      else ["comparison", "diagnostics", "post_close"]
                      if c.canonical_role == POST_CLOSE_INDICATION
                      else ["diagnostics"] if c.canonical_role == SUPERSEDED
                      else ["narrative", "finance_model", "comparison"]
                      if c.proof_status == CONFIRMED_ON_PAGE else ["diagnostics"]),
        metric_canonical_id=c.metric_id,
        period=c.period,
        unit=c.unit,
        currency=c.currency,
        scale=c.scale,
        normalized_value=c.normalized_value,
        source_type="registry_filing" if "annual" in c.source_doc.lower() else "attachment",
        source_id=f"{c.source_doc}#p{c.source_page}",
        document_date=c.period_end_date,
        stable_fact_key=_stable_key,
        fact_instance_id=_instance_id,
        conflict_group_id=c.conflict_group_id,
        board_safe_candidate=(c.proof_status == CONFIRMED_ON_PAGE and c.canonical_role == CANONICAL_CURRENT and not c.board_safe_blockers),
        board_safe_blockers=list(c.board_safe_blockers),
    )
    fact.proof_status = c.proof_status
    fact.canonical_role = c.canonical_role
    fact.definition_axis = c.definition_axis
    fact.source_excerpt = c.source_excerpt
    fact.source_value_text = c.source_value_text
    fact.period_end_date = c.period_end_date
    fact.source_document_date = c.period_end_date
    fact.proof_layer_version = PROOF_LAYER_VERSION
    fact.source_priority = c.source_rank
    # v62.12.1 (spec §4) — le détail auditable du conflit voyage jusqu'au
    # FinancialFact, sinon current_conflict_records reste vide au summary.
    try:
        fact.conflict_detail = getattr(c, "conflict_detail", None)
    except Exception:
        pass
    return fact


def build_page_confirmed_financial_facts(
    financial_statements_block: str = "",
    attachments_block: str = "",
    *,
    lang: str = "en",
) -> list[Any]:
    """Build the authoritative page-confirmed ledger from paginated text."""
    pages = parse_paged_corpus(financial_statements_block, attachments_block)
    # Document-level fiscal columns are deterministic and allow later review
    # pages (FCF/debt prose) to inherit dates stated on page 1 of the section.
    _doc_periods: dict[str, list[tuple[str, str]]] = {}
    for _p in pages:
        _periods = _header_periods(_p.text)
        if _periods and len(_periods) > len(_doc_periods.get(_norm_doc(_p.source_doc), [])):
            _doc_periods[_norm_doc(_p.source_doc)] = _periods
    candidates: list[ProofCandidate] = []
    for page in pages:
        # Only financial statement/review pages can emit core financial facts.
        head = " ".join(page.text.splitlines()[:12]).lower()
        relevant = (
            page.section in {"financial_review", "financial_statements", "income_statement", "balance_sheet", "cash_flow"}
            or re.search(r"financial review|group income statement|group balance sheet|"
                         r"group statement of cash flows|summary income statement|"
                         r"compte de résultat|bilan consolidé|flux de trésorerie", head, re.I)
        )
        if not relevant:
            continue
        candidates.extend(_line_candidates(page))
        if page.section == "financial_review" or "financial review" in head:
            candidates.extend(_narrative_candidates(
                page, _doc_periods.get(_norm_doc(page.source_doc), [])))
    _auth_end_62130 = compute_dossier_authoritative_period_end(candidates)
    reconciled = reconcile_candidates(candidates,
        authoritative_period_end=_auth_end_62130)
    return [_candidate_to_fact(c, lang=lang) for c in reconciled]


def confirmed_fact_rows(facts: Iterable[Any]) -> list[Any]:
    """All page-confirmed facts, including history and post-close indications."""
    return [f for f in (facts or [])
            if str(getattr(f, "proof_status", "")) == CONFIRMED_ON_PAGE]


def current_confirmed_fact_rows(facts: Iterable[Any]) -> list[Any]:
    return [f for f in confirmed_fact_rows(facts)
            if str(getattr(f, "canonical_role", "") or CANONICAL_CURRENT)
            == CANONICAL_CURRENT]


_EXECUTIVE_FINANCIAL_SCOPES = {"CONSOLIDATED", "SOCIAL_STANDALONE"}


def _is_executive_financial_scope(fact: Any) -> bool:
    """Return True only for scopes that may feed executive current-state KPIs.

    HOLDING facts remain page-confirmed and visible in the ledger, but they are
    statutory parent-company facts.  They must not silently become group or
    operating-company facts in a consolidated strategic review.
    """
    return str(getattr(fact, "scope", "UNKNOWN") or "UNKNOWN").upper() in _EXECUTIVE_FINANCIAL_SCOPES


def latest_confirmed_facts(facts: Iterable[Any], *, executive_only: bool = True) -> dict[str, Any]:
    """One authoritative current fact per metric.

    Page-confirmed history and post-close indications remain in the ledger but
    never displace the latest closed annual authority in executive KPIs.
    """
    out: dict[str, Any] = {}
    for f in confirmed_fact_rows(facts):
        if executive_only and not _is_executive_financial_scope(f):
            continue
        role = str(getattr(f, "canonical_role", "") or CANONICAL_CURRENT)
        if role != CANONICAL_CURRENT:
            continue
        metric = str(getattr(f, "metric_canonical_id", "") or "")
        if not metric:
            continue
        cur = out.get(metric)
        parsed = _parse_period_end(getattr(f, "period_end_date", ""))
        key = (parsed or date.min,
               -int(getattr(f, "source_priority", 999) or 999),
               -len(str(getattr(f, "source_excerpt", "") or "")))
        if cur is None:
            out[metric] = f
            continue
        cur_parsed = _parse_period_end(getattr(cur, "period_end_date", ""))
        cur_key = (cur_parsed or date.min,
                   -int(getattr(cur, "source_priority", 999) or 999),
                   -len(str(getattr(cur, "source_excerpt", "") or "")))
        if key > cur_key:
            out[metric] = f
    return out

def financial_proof_summary(facts: Iterable[Any]) -> dict[str, Any]:
    rows = list(facts or [])
    confirmed = confirmed_fact_rows(rows)
    executive_confirmed = [f for f in confirmed if _is_executive_financial_scope(f)]
    current_confirmed = [f for f in executive_confirmed
                         if str(getattr(f, "canonical_role", "") or CANONICAL_CURRENT)
                         == CANONICAL_CURRENT]
    history_confirmed = [f for f in executive_confirmed
                         if str(getattr(f, "canonical_role", "") or "")
                         == CONTRIBUTING_HISTORY]
    post_close_confirmed = [f for f in executive_confirmed
                            if str(getattr(f, "canonical_role", "") or "")
                            == POST_CLOSE_INDICATION]
    holding_confirmed = [f for f in confirmed
                         if str(getattr(f, "scope", "UNKNOWN") or "UNKNOWN").upper() == "HOLDING"]
    conflicts = [f for f in rows if str(getattr(f, "proof_status", "")) == CONFLICT]
    latest = latest_confirmed_facts(rows, executive_only=True)
    critical_current = [f for f in current_confirmed
                        if str(getattr(f, "metric_canonical_id", "")) in CRITICAL_METRIC_IDS]
    parsed_dates = [_parse_period_end(getattr(f, "period_end_date", ""))
                    for f in critical_current]
    parsed_dates = [d for d in parsed_dates if d]
    latest_period = max(parsed_dates).isoformat() if parsed_dates else ""
    # v62.13.9.4.46 — UN EXERCICE EST UNE PÉRIODE. Run réel du 26/09/2026 : trois
    # métriques critiques confirmées à la page pour FY2025, aucun conflit, et pourtant
    # « situation financière établie : non », parce que les faits d'un 10-K portent
    # « FY2025 » sans date de clôture au jour près. À défaut de date, le dernier
    # exercice confirmé fait foi ; le tableau de bord ne se déclare pas non établi pour
    # une date de clôture que la page n'écrit pas.
    if not latest_period and critical_current:
        _fy = []
        for f in critical_current:
            m = re.search(r"(?:FY|20)(\d{2,4})", str(getattr(f, "period", "") or ""))
            if m:
                y = m.group(1)
                y = ("20" + y) if len(y) == 2 else y
                if len(y) == 4:
                    _fy.append(y)
        if _fy:
            latest_period = f"FY{max(_fy)}"
    crit_conflicts = [f for f in conflicts
                      if str(getattr(f, "metric_canonical_id", "") or "") in CRITICAL_METRIC_IDS]
    current_critical_conflicts = []
    historical_critical_conflicts = []
    for f in crit_conflicts:
        pe = normalize_period_end(getattr(f, "period_end_date", ""))
        if not latest_period or pe == latest_period:
            current_critical_conflicts.append(f)
        else:
            historical_critical_conflicts.append(f)
    def _unique_conflict_records(items):
        return list({
            str((rec or {}).get("conflict_group_id")
                or (rec or {}).get("metric_id")
                or repr(rec)): rec
            for rec in (getattr(f, "conflict_detail", None) for f in items) if rec
        }.values())
    return {
        "proof_layer_version": PROOF_LAYER_VERSION,
        "facts_total": len(rows),
        "confirmed_on_page": len(confirmed),
        "executive_confirmed_on_page": len(executive_confirmed),
        "current_confirmed_on_page": len(current_confirmed),
        "history_confirmed_on_page": len(history_confirmed),
        "post_close_confirmed_on_page": len(post_close_confirmed),
        "holding_confirmed_on_page": len(holding_confirmed),
        "critical_confirmed_on_page": len(critical_current),
        "conflicts": len(conflicts),
        "current_critical_conflicts": len(current_critical_conflicts),
        "current_conflict_records": _unique_conflict_records(current_critical_conflicts),
        "historical_conflict_records": _unique_conflict_records(historical_critical_conflicts),
        "latest_confirmed_period_end": latest_period,
        "latest_metrics": sorted(latest),
        "current_financial_state_established": bool(
            latest_period and not current_critical_conflicts
            and "REVENUE" in latest
            and ("OPERATING_PROFIT" in latest or "ADJUSTED_OPERATING_PROFIT" in latest)
        ),
    }

def _claim_hash(*parts: Any) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return "CC-" + hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _sorted_confirmed_metric_facts(facts: Iterable[Any], metric_id: str) -> list[Any]:
    rows = [
        f for f in confirmed_fact_rows(facts)
        if _is_executive_financial_scope(f)
        and str(_attr(f, "metric_canonical_id", "") or "") == metric_id
        and str(_attr(f, "canonical_role", "") or CANONICAL_CURRENT)
        in {CANONICAL_CURRENT, CONTRIBUTING_HISTORY}
    ]
    rows.sort(
        key=lambda f: (
            _parse_period_end(_attr(f, "period_end_date", "")) or date.min,
            -int(_attr(f, "source_priority", 999) or 999),
        ),
        reverse=True,
    )
    return rows


def _format_money_delta(delta: float, currency: str) -> str:
    symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(str(currency or "").upper(), "")
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    val = abs(delta)
    if val >= 1e9:
        return f"{sign}{symbol}{val / 1e9:,.1f}bn"
    if val >= 1e6:
        decimals = 0 if abs(val / 1e6 - round(val / 1e6)) < 0.05 else 1
        return f"{sign}{symbol}{val / 1e6:,.{decimals}f}m"
    if val >= 1e3:
        return f"{sign}{symbol}{val / 1e3:,.0f}k"
    return f"{sign}{symbol}{val:,.0f}"


def _metric_display_label(metric: str, lang: str = "en") -> str:
    en = str(lang or "en").lower().startswith("en")
    labels_en = {
        "REVENUE": "Revenue", "STOCKS": "Inventories",
        "ADJUSTED_OPERATING_MARGIN": "Adjusted operating margin",
        "OPERATING_MARGIN": "Operating margin",
        "ADJUSTED_OPERATING_PROFIT": "Adjusted operating profit",
        "OPERATING_PROFIT": "Operating profit",
        "FREE_CASH_FLOW": "Free cash flow", "NET_DEBT": "Net debt",
        "CASH_NET_OF_OVERDRAFTS": "Cash net of overdrafts",
        "CASH": "Cash and cash equivalents", "HEADCOUNT": "Headcount",
    }
    labels_fr = {
        "REVENUE": "Chiffre d'affaires", "STOCKS": "Stocks",
        "ADJUSTED_OPERATING_MARGIN": "Marge opérationnelle ajustée",
        "OPERATING_MARGIN": "Marge opérationnelle",
        "ADJUSTED_OPERATING_PROFIT": "Résultat opérationnel ajusté",
        "OPERATING_PROFIT": "Résultat opérationnel",
        "FREE_CASH_FLOW": "Free cash flow", "NET_DEBT": "Dette nette",
        "CASH_NET_OF_OVERDRAFTS": "Trésorerie nette des découverts",
        "CASH": "Trésorerie et équivalents", "HEADCOUNT": "Effectif",
    }
    return (labels_en if en else labels_fr).get(metric, metric.replace("_", " ").title())


def _format_local_number(value: float, decimals: int, *, lang: str) -> str:
    rendered = f"{value:,.{decimals}f}"
    if str(lang or "en").lower().startswith("fr"):
        rendered = rendered.replace(",", " ").replace(".", ",")
    return rendered


def _format_fact_value(fact: Any, *, lang: str = "en") -> str:
    raw = str(_attr(fact, "value", "") or "").strip()
    unit = str(_attr(fact, "unit", "") or "").upper()
    currency = str(_attr(fact, "currency", "") or "").upper()
    fr = str(lang or "en").lower().startswith("fr")
    try:
        normalized = float(_attr(fact, "normalized_value", None))
    except Exception:
        normalized = None
    # English preserves a reliable source rendering. French is rebuilt from the
    # normalized value so canonical lines use native forms (2 420 M€, 6,6 %).
    if not fr and raw and (re.search(r"[£€$%]", raw) or re.search(r"\b(?:bn|m|k|million|billion)\b", raw, re.I)):
        return raw
    if normalized is None:
        return raw
    if unit == "PCT":
        decimals = 0 if abs(normalized - round(normalized)) < 0.005 else 1
        rendered = _format_local_number(normalized, decimals, lang=lang)
        return f"{rendered} %" if fr else f"{rendered}%"
    if unit == "PERSONS":
        return _format_local_number(normalized, 0, lang=lang)
    if unit == "CUR":
        symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(currency, "")
        sign = "-" if normalized < 0 else ""
        val = abs(normalized)
        if val >= 1e6:
            m = val / 1e6
            decimals = 0 if abs(m - round(m)) < 0.05 else 1
            number = _format_local_number(m, decimals, lang=lang)
            return f"{sign}{number} M{symbol}" if fr else f"{sign}{symbol}{number}m"
        if val >= 1e3:
            number = _format_local_number(val / 1e3, 0, lang=lang)
            return f"{sign}{number} k{symbol}" if fr else f"{sign}{symbol}{number}k"
        number = _format_local_number(val, 0, lang=lang)
        return f"{sign}{number} {symbol}".rstrip() if fr else f"{sign}{symbol}{number}"
    rendered = _format_local_number(normalized, 0 if normalized.is_integer() else 1, lang=lang)
    return raw or rendered


def _build_change_claim(metric: str, current: Any, previous: Any, *, lang: str) -> Optional[dict[str, Any]]:
    try:
        cur_val = float(_attr(current, "normalized_value", 0.0) or 0.0)
        prev_val = float(_attr(previous, "normalized_value", 0.0) or 0.0)
    except Exception:
        return None
    if prev_val == 0:
        return None
    unit = str(_attr(current, "unit", "") or "")
    currency = str(_attr(current, "currency", "") or "")
    pct = (cur_val - prev_val) / abs(prev_val) * 100.0
    cur_display = _format_fact_value(current, lang=lang)
    prev_display = _format_fact_value(previous, lang=lang)
    cur_period = str(_attr(current, "period", "") or "")
    prev_period = str(_attr(previous, "period", "") or "")
    raw_label = str(_attr(current, "label", "") or "")
    label = (_metric_display_label(metric, lang)
             if not raw_label or raw_label.upper() == metric else raw_label)
    if not str(lang or "en").lower().startswith("en"):
        label = label.replace("'", "’")
    cur_id = str(_attr(current, "fact_instance_id", "") or "")
    prev_id = str(_attr(previous, "fact_instance_id", "") or "")
    cur_key = str(_attr(current, "stable_fact_key", "") or "")
    prev_key = str(_attr(previous, "stable_fact_key", "") or "")
    en = str(lang or "en").lower().startswith("en")
    numeric_components: list[dict[str, Any]] = []
    if unit == "PCT":
        pp = cur_val - prev_val
        display = (f"{pp:+.1f}pp" if en else f"{pp:+.1f}".replace(".", ",") + " pp")
        executive = (
            f"{label} increased to {cur_display} from {prev_display} ({display}; {cur_period} vs {prev_period})"
            if pp >= 0 else
            f"{label} decreased to {cur_display} from {prev_display} ({display}; {cur_period} vs {prev_period})"
        ) if en else (
            f"{label} portée à {cur_display} contre {prev_display} ({display} ; {cur_period} vs {prev_period})"
            if pp >= 0 else
            f"{label} ramenée à {cur_display} contre {prev_display} ({display} ; {cur_period} vs {prev_period})"
        )
        numeric_components = [
            {"kind": "pct", "value": cur_val},
            {"kind": "pct", "value": prev_val},
            {"kind": "pp", "value": pp},
        ]
        metric_id = metric + "_CHANGE_PP"
    else:
        delta = cur_val - prev_val
        delta_display = _format_money_delta(delta, currency)
        pct_display = (f"{pct:+.1f}%" if en else f"{pct:+.1f}".replace(".", ",") + " %")
        if metric == "STOCKS":
            executive = (
                f"Inventories changed by {delta_display} ({pct_display}) to {cur_display} ({cur_period} vs {prev_period})"
                if en else
                f"Stocks : variation de {delta_display} ({pct_display}) à {cur_display} ({cur_period} vs {prev_period})"
            )
        else:
            executive = (
                f"{label} changed to {cur_display} from {prev_display} ({pct_display}; {cur_period} vs {prev_period})"
                if en else
                f"{label} : {cur_display} contre {prev_display} ({pct_display} ; {cur_period} vs {prev_period})"
            )
        numeric_components = [
            {"kind": "money", "value": cur_val},
            {"kind": "money", "value": prev_val},
            {"kind": "money_abs", "value": abs(delta)},
            {"kind": "pct", "value": pct},
        ]
        metric_id = metric + "_CHANGE_REPORTED"
    if unit == "PCT":
        compact = (
            f"{label} {prev_display}→{cur_display} ({display}; {cur_period} vs {prev_period})"
            if en else
            f"{label} {prev_display}→{cur_display} ({display} ; {cur_period} vs {prev_period})"
        )
    else:
        compact_label = ("Inventories" if metric == "STOCKS" and en else
                         "Stocks" if metric == "STOCKS" else label)
        compact = (
            f"{compact_label} {prev_display}→{cur_display} ({pct:+.1f}%; {cur_period} vs {prev_period})"
            if en else
            f"{compact_label} {prev_display}→{cur_display} ({f'{pct:+.1f}'.replace('.', ',')} % ; {cur_period} vs {prev_period})"
        )
    return {
        "claim_id": _claim_hash(metric_id, cur_id or cur_key, prev_id or prev_key),
        "claim_type": "DERIVED",
        "metric_id": metric_id,
        "base_metric_id": metric,
        "label": label,
        "value": executive,
        "display_value": executive,
        "executive_line": executive,
        "compact_executive_line": compact,
        "normalized_value": pct,
        "unit": "PCT",
        "currency": currency,
        "period": cur_period,
        "period_end_date": str(_attr(current, "period_end_date", "") or ""),
        "comparison_period": prev_period,
        "scope": str(_attr(current, "scope", "UNKNOWN") or "UNKNOWN"),
        "source_refs": [
            {"source_doc": str(_attr(current, "source_doc", "") or ""),
             "source_page": _attr(current, "source_page", None)},
            {"source_doc": str(_attr(previous, "source_doc", "") or ""),
             "source_page": _attr(previous, "source_page", None)},
        ],
        "fact_instance_ids": [x for x in (cur_id, prev_id) if x],
        "stable_fact_keys": [x for x in (cur_key, prev_key) if x],
        "proof_status": "DERIVED_FROM_CONFIRMED_ON_PAGE",
        "formula": "(current - prior) / abs(prior)",
        "numeric_components": numeric_components,
        "current_display": cur_display,
        "previous_display": prev_display,
        "display_line": (
            f"[DERIVED FROM FACTS] {executive}"
            if en else f"[DÉRIVÉ DE FAITS] {executive}"
        ),
    }

def build_canonical_financial_claims(table_or_facts: Any, lang: str = "en") -> list[dict[str, Any]]:
    """Single claim set consumed by Word, PPTX and numeric post-controls.

    Current facts come only from ``CONFIRMED_ON_PAGE`` rows whose
    ``canonical_role`` is CURRENT. Historical page-confirmed rows remain
    available for deterministic comparisons and derived claims.
    """
    facts = _iter_fact_objects(table_or_facts)
    latest = latest_confirmed_facts(facts, executive_only=True)
    en = str(lang or "en").lower().startswith("en")
    order = (
        "REVENUE", "ADJUSTED_OPERATING_PROFIT", "ADJUSTED_OPERATING_MARGIN",
        "OPERATING_PROFIT", "OPERATING_MARGIN", "NET_INCOME",
        "FREE_CASH_FLOW", "NET_DEBT", "CASH_NET_OF_OVERDRAFTS", "CASH",
        "STOCKS", "HEADCOUNT",
    )
    claims: list[dict[str, Any]] = []
    for metric in order:
        f = latest.get(metric)
        if f is None or str(_attr(f, "proof_status", "") or "") != CONFIRMED_ON_PAGE:
            continue
        fact_id = str(_attr(f, "fact_instance_id", "") or "")
        stable_key = str(_attr(f, "stable_fact_key", "") or "")
        claim_id = _claim_hash(metric, fact_id or stable_key)
        raw_label = str(_attr(f, "label", "") or "")
        label = (_metric_display_label(metric, lang)
                 if not raw_label or raw_label.upper() == metric else raw_label)
        if not en:
            label = label.replace("'", "’")
        value = _format_fact_value(f, lang=lang)
        period = str(_attr(f, "period", "") or "")
        source_doc = str(_attr(f, "source_doc", "") or "")
        source_page = _attr(f, "source_page", None)
        normalized = _attr(f, "normalized_value", None)
        unit = str(_attr(f, "unit", "") or "")
        kind = "pct" if unit == "PCT" else "money" if unit == "CUR" else "number"
        # v62.13.9.4.36 — pas de parenthèse vide quand la période est inconnue. Run réel
        # du 17/09/2026 : « Chiffre d'affaires IAV : 2,4 M€ () — dossier réseau de soins~1.PDF p.13 »,
        # seize occurrences dans un même dossier. Sans période, la ligne s'arrête à la
        # valeur ; la source à la page reste, elle, toujours affichée.
        _per36 = str(period or "").strip()
        # v62.13.9.4.49 — l'affichage ne garde que la langue du run (« Revenue: $620m », pas « Revenue / Chiffre
        # d'affaires: $620m ») ; le libellé bilingue reste dans « label » pour le rattachement (deux alias)
        try:
            from utils.financial_facts_table import monolingual_metric_label as _mono49
            _dlabel49 = _mono49(label, lang) or label
        except Exception:
            _dlabel49 = label
        executive = ((f"{_dlabel49}: {value} ({_per36})" if en else f"{_dlabel49} : {value} ({_per36})")
                     if _per36 else (f"{_dlabel49}: {value}" if en else f"{_dlabel49} : {value}"))
        # 9.4.65 (LM01) — un fait d'un AUTRE périmètre que la cible (comptes sociaux d'une filiale en mode groupe) garde son
        # entité et sa nature jusque sur les cartes : « <Filiale> — Effectif : <n> (<année>, comptes sociaux) ».
        if str(_attr(f, "perimeter_match", "") or "").upper() == "MISMATCH":
            _ent65 = str(_attr(f, "perimeter_entity", "") or "").strip()
            _ent65 = _ent65.title() if _ent65.isupper() else _ent65
            _scope65 = ("standalone accounts" if en else "comptes sociaux") if str(_attr(f, "scope", "") or "").upper() == \
                "SOCIAL_STANDALONE" else ("other scope" if en else "autre périmètre")
            _core65 = (f"{_dlabel49}: {value}" if en else f"{_dlabel49} : {value}")
            executive = (f"{_ent65} — " if _ent65 else "") + _core65 + (f" ({_per36}, {_scope65})" if _per36 else f" ({_scope65})")
        claims.append({
            "claim_id": claim_id,
            "claim_type": "FACT",
            "metric_id": metric,
            "label": label,
            "value": value,
            "normalized_value": normalized,
            "unit": unit,
            "currency": str(_attr(f, "currency", "") or ""),
            "period": period,
            "period_end_date": str(_attr(f, "period_end_date", "") or ""),
            "scope": str(_attr(f, "scope", "UNKNOWN") or "UNKNOWN"),
            "source_doc": source_doc,
            "source_page": source_page,
            "source_refs": [{"source_doc": source_doc, "source_page": source_page}],
            "fact_instance_ids": [fact_id] if fact_id else [],
            "stable_fact_keys": [stable_key] if stable_key else [],
            "proof_status": CONFIRMED_ON_PAGE,
            "display_value": value,
            "executive_line": executive,
            "numeric_components": ([{"kind": kind, "value": normalized}]
                                   if normalized is not None else []),
            "display_line": (
                f"[FACT] {executive} — {source_doc} p.{source_page}"
                if en else
                f"[FAIT] {executive} — {source_doc} p.{source_page}"
            ),
        })

    # Deterministic changes. These are facts-derived, not model estimates.
    change_metrics = (
        "REVENUE", "STOCKS", "ADJUSTED_OPERATING_MARGIN",
        "OPERATING_MARGIN", "ADJUSTED_OPERATING_PROFIT", "OPERATING_PROFIT",
        "FREE_CASH_FLOW", "NET_DEBT", "CASH_NET_OF_OVERDRAFTS",
    )
    for metric in change_metrics:
        rows = _sorted_confirmed_metric_facts(facts, metric)
        if len(rows) < 2:
            continue
        current = rows[0]
        previous = next((r for r in rows[1:]
                         if normalize_period_end(_attr(r, "period_end_date", ""))
                         != normalize_period_end(_attr(current, "period_end_date", ""))
                         and str(_attr(r, "scope", "UNKNOWN") or "UNKNOWN")
                         == str(_attr(current, "scope", "UNKNOWN") or "UNKNOWN")
                         and str(_attr(r, "currency", "") or "")
                         == str(_attr(current, "currency", "") or "")), None)
        if previous is None:
            continue
        claim = _build_change_claim(metric, current, previous, lang=lang)
        if claim:
            claims.append(claim)

    # Backwards-compatible alias used by KPI mapping.
    revenue_change = next((c for c in claims
                           if c.get("metric_id") == "REVENUE_CHANGE_REPORTED"), None)
    if revenue_change:
        alias = dict(revenue_change)
        alias["claim_id"] = _claim_hash(
            "REVENUE_GROWTH_REPORTED", *alias.get("fact_instance_ids", []))
        alias["metric_id"] = "REVENUE_GROWTH_REPORTED"
        alias["label"] = "Revenue growth" if en else "Croissance du chiffre d'affaires"
        pct = next((x.get("value") for x in alias.get("numeric_components", [])
                    if x.get("kind") == "pct"), alias.get("normalized_value"))
        try:
            display = f"{float(pct):+.1f}% reported" if en else f"{float(pct):+.1f} % publié"
        except Exception:
            display = str(alias.get("display_value") or "")
        alias["value"] = display
        alias["display_value"] = display
        alias["executive_line"] = (
            f"Revenue growth {display} ({alias.get('period')} vs {alias.get('comparison_period')})"
            if en else
            f"Croissance du chiffre d'affaires {display} ({alias.get('period')} vs {alias.get('comparison_period')})"
        )
        alias["display_line"] = (
            f"[DERIVED FROM FACTS] {alias['executive_line']}"
            if en else f"[DÉRIVÉ DE FAITS] {alias['executive_line']}"
        )
        claims.append(alias)
    return claims



def canonical_current_financial_lines(facts: Iterable[Any], lang: str = "en") -> list[str]:
    """Human-readable canonical current claims for final narrative surfaces."""
    return [str(c.get("display_line") or "") for c in build_canonical_financial_claims(facts, lang=lang)
            if c.get("metric_id") != "REVENUE_GROWTH_REPORTED"]


def build_board_numeric_support_claims(table_or_facts: Any, lang: str = "en") -> list[dict[str, Any]]:
    """Claims authorised on executive surfaces.

    The set is deliberately identical to the canonical financial claim set:
    page-confirmed current facts plus deterministic changes built from two
    page-confirmed periods.  The Board Scrutiny guard consumes the numeric
    components and claim ids; it does not trust a model's ``≈`` marker.
    """
    claims = build_canonical_financial_claims(table_or_facts, lang=lang)
    # v62.13.9.4.50 — TOUT fait confirmé à la page soutient une ligne (contre-recette du 30/09, A02 ; échantillon du
    # vrai CR : « Marge brute : 341,3 M$ », « créances clients 120,589 M$ » sortaient « sans pièce » alors que la base
    # les confirmait). Les claims canoniques restent l'ensemble AFFICHÉ (cartes, base courante) ; les faits confirmés
    # des autres métriques s'y ajoutent ici comme SOUTIEN seulement.
    try:
        seen = {str(c.get("metric_id") or "") for c in claims}
        seen_vals = {(str(c.get("metric_id") or ""), float((c.get("numeric_components") or [{}])[0].get("value") or 0))
                     for c in claims if c.get("numeric_components")}
        for f in _iter_fact_objects(table_or_facts):
            if str(_attr(f, "proof_status", "") or "") != CONFIRMED_ON_PAGE:
                continue
            if str(_attr(f, "canonical_role", "") or "CURRENT") not in ("CURRENT", "", str(globals().get("CANONICAL_CURRENT", "CURRENT"))):
                continue
            metric = str(_attr(f, "metric_canonical_id", "") or "")
            label0 = str(_attr(f, "label", "") or "")
            if not metric or metric == "OTHER":
                # deux faits « OTHER » (créances, total actif) ne doivent pas se masquer l'un l'autre
                metric = re.sub(r"[^A-Z0-9]+", "_", label0.split("/")[0].strip().upper()).strip("_") or "OTHER"
            if (metric, float(_attr(f, "normalized_value", 0) or 0)) in seen_vals or metric in seen:
                continue
            normalized = _attr(f, "normalized_value", None)
            if normalized is None:
                continue
            unit = str(_attr(f, "unit", "") or "")
            kind = "pct" if unit == "PCT" else "money" if unit == "CUR" else "number"
            label = str(_attr(f, "label", "") or metric.replace("_", " ").title())
            period = str(_attr(f, "period", "") or "")
            claims.append({
                "claim_id": _claim_hash(metric, str(_attr(f, "fact_instance_id", "") or _attr(f, "stable_fact_key", "") or "")),
                "claim_type": "FACT", "metric_id": metric, "label": label, "period": period,
                "proof_status": CONFIRMED_ON_PAGE, "support_only": True,
                "numeric_components": [{"kind": kind, "value": float(normalized)}],
                "source_doc": str(_attr(f, "source_doc", "") or _attr(f, "source", "") or ""),
                # la provenance (pièce + page) est exigée par la liaison pour un fait CONFIRMED_ON_PAGE
                "source_page": _attr(f, "source_page", None) or _attr(f, "page", None),
                "currency": str(_attr(f, "currency", "") or ""),
                # la devise doit figurer dans le texte du claim : la liaison exige « devise affirmée ⇒ devise certifiée »
                "compact_executive_line": (f"{label} : {float(normalized):,.0f} {str(_attr(f, 'currency', '') or '').upper()} ({period})"
                                           if kind == "money" else f"{label} : {float(normalized):g} ({period})").strip(),
            })
            seen.add(metric)
    except Exception:
        pass
    return claims

def detect_ocr_required_documents(financial_statements_block: str = "",
                                  attachments_block: str = "") -> list[str]:
    """List image-only/scan documents explicitly marked as non-extractable.

    No OCR is attempted in v62.11. This is observability, not interpretation.
    """
    pages = parse_paged_corpus(financial_statements_block, attachments_block)
    docs: set[str] = set()
    # Do not match the ordinary verb ``scan`` (for example "we also scan
    # for emerging risks" in an annual report).  OCR_REQUIRED is reserved for
    # an explicit document/extraction condition.
    marker = re.compile(
        r"(?:scanned|scan(?:né|ne))\s+(?:pdf|document|page|image)|"
        r"(?:pdf|document|page)\s+(?:scanned|scan(?:né|ne))|"
        r"image[- ]only|OCR\s+(?:required|unavailable|non\s+disponible)|"
        r"sans\s+OCR|no\s+text\s+layer|texte\s+non\s+extractible", re.I)
    for page in pages:
        if marker.search(page.text):
            docs.add(page.source_doc)
    # Some bundle summaries contain a scan marker before any page body.
    blob = "\n".join((financial_statements_block or "", attachments_block or ""))
    current = ""
    for line in blob.splitlines():
        m = _DOC_FS.match(line.strip()) or _DOC_ATTACHMENT.match(line.strip())
        if m:
            current = m.group(1).strip()
        elif current and marker.search(line):
            docs.add(current)
    return sorted(docs)


# ─────────────────────────────────────────────────────────────────────────────
# Ledger governance and shared output consumers
# ─────────────────────────────────────────────────────────────────────────────

def _iter_fact_objects(table_or_facts: Any) -> list[Any]:
    if table_or_facts is None:
        return []
    if isinstance(table_or_facts, Mapping):
        for key in ("facts", "rows", "items", "entries"):
            value = table_or_facts.get(key)
            if isinstance(value, (list, tuple)):
                return list(value)
    for attr in ("facts", "rows", "items", "entries"):
        value = getattr(table_or_facts, attr, None)
        if isinstance(value, (list, tuple)):
            return list(value)
    if isinstance(table_or_facts, (list, tuple)):
        return list(table_or_facts)
    return []


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, Mapping) else getattr(obj, name, default)


def _set(obj: Any, name: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)


def quarantine_conflicting_ledger_facts(table_or_facts: Any) -> dict[str, Any]:
    """Make the page-confirmed ledger authoritative over narrative/legacy facts.

    A narrative agent value can remain in diagnostics, but it can never compete
    with a page-confirmed value for the same metric, period and perimeter.
    """
    facts = _iter_fact_objects(table_or_facts)
    confirmed = confirmed_fact_rows(facts)
    authoritative: dict[tuple[str, str, str], list[Any]] = {}
    for f in confirmed:
        key = (
            str(_attr(f, "metric_canonical_id", "") or ""),
            str(_attr(f, "period", "") or ""),
            str(_attr(f, "scope", "UNKNOWN") or "UNKNOWN"),
        )
        authoritative.setdefault(key, []).append(f)
    quarantined = 0
    for f in facts:
        if str(_attr(f, "proof_status", "") or "") == CONFIRMED_ON_PAGE:
            continue
        metric = str(_attr(f, "metric_canonical_id", "") or "")
        period = str(_attr(f, "period", "") or "")
        scope = str(_attr(f, "scope", "UNKNOWN") or "UNKNOWN")
        if not metric or not period:
            continue
        refs = authoritative.get((metric, period, scope)) or authoritative.get((metric, period, "CONSOLIDATED")) or []
        if not refs:
            continue
        val = _attr(f, "normalized_value", None)
        if val is None:
            continue
        if any(not _materially_different(float(val), float(_attr(r, "normalized_value", 0.0)),
                                         str(_attr(r, "unit", "") or "")) for r in refs):
            # Duplicate non-authoritative claim: keep diagnostics only.
            _set(f, "proof_status", QUARANTINED)
            _set(f, "allowed_uses", ["diagnostics"])
            blockers = list(_attr(f, "board_safe_blockers", []) or [])
            if "superseded_by_page_confirmed_fact" not in blockers:
                blockers.append("superseded_by_page_confirmed_fact")
            _set(f, "board_safe_blockers", blockers)
            quarantined += 1
            continue
        _set(f, "proof_status", QUARANTINED)
        _set(f, "allowed_uses", ["diagnostics"])
        blockers = list(_attr(f, "board_safe_blockers", []) or [])
        if "conflicts_with_page_confirmed_fact" not in blockers:
            blockers.append("conflicts_with_page_confirmed_fact")
        _set(f, "board_safe_blockers", blockers)
        _set(f, "conflict_group_id", str(_attr(refs[0], "stable_fact_key", "") or "FPL-CONFLICT"))
        quarantined += 1
    return {
        "status": "OK", "facts_total": len(facts),
        "page_confirmed": len(confirmed), "quarantined": quarantined,
    }


def update_temporal_frame_from_ledger(temporal_frame: Any, table_or_facts: Any,
                                      lang: str = "en") -> Any:
    """Bind the *parsed* period to the latest page-confirmed critical fact."""
    if temporal_frame is None:
        return temporal_frame
    summary = financial_proof_summary(_iter_fact_objects(table_or_facts))
    latest = str(summary.get("latest_confirmed_period_end") or "")
    # v62.12.1 (spec §6) — trois notions, trois champs : l'année documentaire
    # détectée/scannée (posée en amont, plus jamais écrasée ici), la dernière
    # période CRITIQUE page-confirmée, et la position établie oui/non + raison.
    try:
        temporal_frame.latest_confirmed_critical_period = latest
        _est = summary.get("current_financial_state_established")
        temporal_frame.current_established = (None if _est is None else bool(_est))
        _en = str(lang or "en").lower().startswith("en")
        if _est is False:
            _ncc = int(summary.get("current_critical_conflicts") or 0)
            _reg = str(getattr(temporal_frame, "latest_accounts_date", "") or "")
            if _ncc:
                temporal_frame.established_reason = (
                    f"{_ncc} unresolved critical conflict(s) on the current period"
                    if _en else
                    f"{_ncc} conflit(s) critique(s) non résolus sur la période courante")
            elif _reg and latest and _reg > latest:
                temporal_frame.established_reason = (
                    "latest critical page-confirmed fact is older than the registry filing"
                    if _en else
                    "le dernier fait critique confirmé est antérieur au dépôt registre")
            else:
                temporal_frame.established_reason = (
                    "insufficient page-confirmed critical facts"
                    if _en else "faits critiques page-confirmés insuffisants")
        else:
            temporal_frame.established_reason = ""
    except Exception:
        pass
    if not latest:
        return temporal_frame
    # v62.12.2 — ne jamais écraser l'année documentaire détectée/scannée
    # par la dernière période critique confirmée. Les deux notions restent
    # distinctes. Pour compatibilité avec les anciens appels qui n'ont jamais
    # renseigné le champ documentaire, on initialise seulement s'il est vide.
    if not str(getattr(temporal_frame, "latest_parsed_financial_period", "") or ""):
        temporal_frame.latest_parsed_financial_period = latest
        temporal_frame.parsed_period_source = (
            "fallback from page-confirmed ledger (no document-year signal)"
            if str(lang or "en").lower().startswith("en") else
            "repli depuis le ledger page-confirmé (année documentaire absente)"
        )
    registry = str(getattr(temporal_frame, "latest_accounts_date", "") or "")
    if registry and registry > latest:
        temporal_frame.parsed_period_note = (
            "Registry metadata is newer than the latest page-confirmed financial period; the newer filing remains unparsed."
            if str(lang or "en").lower().startswith("en") else
            "La métadonnée registre est plus récente que la dernière période financière confirmée à la page ; le dépôt plus récent reste non parsé."
        )
    else:
        temporal_frame.parsed_period_note = ""
    return temporal_frame


def _money_tokens(text: str) -> list[float]:
    """Normalise currency tokens to base units for claim/ledger comparison."""
    out: list[float] = []
    rx = re.compile(
        r"(?P<open>\()?\s*(?P<cur>[£€$])\s*(?P<num>\d[\d,\s]*(?:\.\d+)?)\s*"
        r"(?P<scale>bn|billion|m|million|k|thousand)?\s*(?P<close>\))?", re.I)
    for m in rx.finditer(str(text or "")):
        raw = m.group("num").replace(" ", "").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        scale = str(m.group("scale") or "").lower()
        if scale in {"bn", "billion"}: value *= 1e9
        elif scale in {"m", "million"}: value *= 1e6
        elif scale in {"k", "thousand"}: value *= 1e3
        if m.group("open") and m.group("close"): value = -abs(value)
        out.append(value)
    return out


_LINE_METRICS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (spec.metric_id, re.compile("|".join(f"(?:{p})" for p in spec.patterns), re.I))
    for spec in _METRICS if spec.metric_id in CRITICAL_METRIC_IDS
)


def _numeric_tokens_for_metrics(text: str) -> list[float]:
    out = _money_tokens(text)
    for m in re.finditer(r"(?<![\d.])([-+−]?\d+(?:[.,]\d+)?)\s*%", str(text or "")):
        try:
            out.append(float(m.group(1).replace("−", "-").replace(",", ".")))
        except Exception:
            pass
    return out


def _metrics_in_line(line: str) -> list[str]:
    cleaned = re.sub(r"^\s*(?:[-*•]+\s*)?(?:\[(?:FACT|FAIT)\]\s*)?", "", str(line or ""), flags=re.I)
    return [metric for metric, rx in _LINE_METRICS if rx.search(cleaned)]


def _value_matches(metric: str, token: float, facts: Sequence[Any]) -> bool:
    for f in facts:
        if not _is_executive_financial_scope(f):
            continue
        if str(_attr(f, "metric_canonical_id", "") or "") != metric:
            continue
        if str(_attr(f, "proof_status", "") or "") != CONFIRMED_ON_PAGE:
            continue
        value = _attr(f, "normalized_value", None)
        if value is None:
            continue
        if not _materially_different(float(token), float(value), str(_attr(f, "unit", "") or "CUR")):
            return True
    return False


_ESTIMATE_MARKER = re.compile(
    r"(?:\[(?:AI\s*)?ESTIM|\[UNSOURCED\]|\[NON\s+SOURC[ÉE]\]|"
    r"estimate(?:d)?|working\s+assumption|hypoth[èe]se|projection|forecast|"
    r"current\s+year\s+estimate|baseline\s+estimate|≈|~\s*\d)", re.I)
_CURRENT_BASELINE_LANGUAGE = re.compile(
    r"(?:\bcurrent(?:\s+(?:year|situation|position))?\b|\blatest\b|\bbaseline\b|\bactual\b|"
    r"\bsituation\s+actuelle\b|^\s*situation\s*:|\bexercice\s+courant\b|"
    r"\bannée\s+courante\b|\bcorrected\s+FY\b)", re.I)
_FINANCIAL_LANGUAGE = re.compile(
    r"\b(?:revenue|turnover|sales|operating\s+profit|operating\s+margin|"
    r"net\s+income|free\s+cash\s+flow|cash|net\s+debt|borrowings|EBITDA|"
    r"chiffre\s+d['’]affaires|résultat\s+opérationnel|marge|résultat\s+net|"
    r"trésorerie|dette\s+nette|stocks?)\b", re.I)
_CANONICAL_BLOCK_TITLE = re.compile(
    r"^(?:PAGE-CONFIRMED CURRENT FINANCIAL BASELINE|BASE FINANCIÈRE ACTUELLE CONFIRMÉE À LA PAGE)\s*$",
    re.I)


def _period_years_from_line(line: str) -> list[int]:
    out: list[int] = []
    for m in re.finditer(r"\bFY\s*(?:20)?(\d{2})(?:\s*/\s*(?:20)?(\d{2}))?\b", str(line or ""), re.I):
        y = 2000 + int(m.group(2) or m.group(1))
        out.append(y)
    for m in re.finditer(r"\b(20\d{2})\s*[/\-]\s*(\d{2}|20\d{2})\b", str(line or "")):
        second = int(m.group(2))
        out.append(second if second >= 2000 else 2000 + second)
    out.extend(int(x) for x in re.findall(r"\b(20\d{2})\b", str(line or "")))
    return sorted(set(out))


def _strip_existing_canonical_block(text: str) -> str:
    lines = str(text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if _CANONICAL_BLOCK_TITLE.match(lines[i].strip()):
            i += 1
            while i < len(lines) and (lines[i].lstrip().startswith(("•", "[FACT]", "[FAIT]", "[DERIVED", "[DÉRIVÉ")) or not lines[i].strip()):
                i += 1
            continue
        out.append(lines[i]); i += 1
    return "\n".join(out).strip()


def _confirmed_period_map(facts: Sequence[Any]) -> dict[tuple[str, int], list[Any]]:
    out: dict[tuple[str, int], list[Any]] = {}
    for f in confirmed_fact_rows(facts):
        if not _is_executive_financial_scope(f):
            continue
        metric = str(_attr(f, "metric_canonical_id", "") or "")
        date = str(_attr(f, "period_end_date", "") or "")
        year = int(date[:4]) if re.match(r"^20\d{2}", date) else 0
        if metric and year:
            out.setdefault((metric, year), []).append(f)
    return out


def _format_historical_conflict_note(records: Sequence[Mapping[str, Any]] | None,
                                     lang: str = "en") -> str:
    rows = list(records or [])
    if not rows:
        return ""
    en = str(lang or "en").lower().startswith("en")
    title = ("HISTORICAL CONFLICTS — NOT ESTABLISHED" if en
             else "HISTORIQUE CONTESTÉ — NON ÉTABLI")
    lines = [title]
    for rec in rows:
        metric = str(rec.get("metric_id") or "metric").replace("_", " ").title()
        period = str(rec.get("period_end") or rec.get("period") or "")
        values = []
        for item in rec.get("values") or []:
            txt = str(item.get("value_text") or item.get("value") or "").strip()
            if txt and txt not in values:
                values.append(txt)
        joined = " / ".join(values[:4]) or "divergent values"
        sources = len({(str(x.get("source_doc") or ""), str(x.get("source_page") or ""))
                       for x in (rec.get("values") or [])})
        if en:
            lines.append(f"• {metric} {period}: {joined} ({sources} source(s)); does not affect the current confirmed period.")
        else:
            lines.append(f"• {metric} {period} : {joined} ({sources} source(s)) ; sans effet sur la période courante confirmée.")
    return "\n".join(lines)


def reconcile_financial_narrative(outputs: Mapping[str, Any] | None,
                                  table_or_facts: Any,
                                  lang: str = "en") -> tuple[dict[str, Any], dict[str, Any]]:
    """Enforce the page-confirmed current period across every narrative.

    - page-confirmed current facts are authoritative;
    - estimates for an already closed and confirmed period are removed;
    - conflicting current-period claims are withheld even if the model omitted
      an epistemic tag;
    - one canonical claim set feeds both Word and PPTX.
    """
    clean = dict(outputs or {})
    facts = _iter_fact_objects(table_or_facts)
    confirmed = confirmed_fact_rows(facts)
    summary = financial_proof_summary(facts)
    claims = build_canonical_financial_claims(facts, lang=lang)
    if not confirmed:
        return clean, {"applied": False, **summary, "lines_withheld": 0,
                       "stale_closed_period_estimates_removed": 0,
                       "canonical_claims": []}
    current_period = str(summary.get("latest_confirmed_period_end") or "")
    current_year = int(current_period[:4]) if re.match(r"^20\d{2}", current_period) else 0
    confirmed_by_period = _confirmed_period_map(confirmed)
    canonical_lines = [str(c.get("display_line") or "") for c in claims]
    title = ("PAGE-CONFIRMED CURRENT FINANCIAL BASELINE" if str(lang or "en").lower().startswith("en")
             else "BASE FINANCIÈRE ACTUELLE CONFIRMÉE À LA PAGE")
    block = title + "\n" + "\n".join(f"• {x}" for x in canonical_lines)
    historical_conflict_note = _format_historical_conflict_note(
        summary.get("historical_conflict_records") or [], lang=lang)
    touched = 0
    withheld = 0
    stale_removed = 0
    injected_keys = {"finance", "strategie", "synthese_decisions", "direction_generale", "ceo", "brief_codir"}
    skip_keys = {"entity_validation_annex", "diagnostics", "raw", "report_raw"}
    for key, text in list(clean.items()):
        if key in skip_keys or not isinstance(text, str) or not text.strip():
            continue
        original = text
        text = _strip_existing_canonical_block(text)
        lines: list[str] = []
        in_stale_table = False
        for line in text.splitlines():
            years = _period_years_from_line(line)
            metrics = _metrics_in_line(line)
            tokens = _numeric_tokens_for_metrics(line)
            estimate = bool(_ESTIMATE_MARKER.search(line))
            current_language = bool(_CURRENT_BASELINE_LANGUAGE.search(line))
            financial_language = bool(metrics or _FINANCIAL_LANGUAGE.search(line))
            # A table headed as an estimate/baseline for an exercise already
            # closed and page-confirmed is obsolete as a whole.
            if "|" in line and estimate and years and current_year and max(years) <= current_year:
                in_stale_table = True
                stale_removed += 1; withheld += 1
                continue
            if in_stale_table:
                if not line.strip():
                    in_stale_table = False
                    lines.append(line)
                elif "|" in line:
                    stale_removed += 1; withheld += 1
                else:
                    in_stale_table = False
                    lines.append(line)
                continue
            # A heading/current-situation claim anchored to a prior closed
            # year cannot remain the active situation once a newer period is
            # page-confirmed. Historical sections without current-language are
            # retained.
            if (current_language and years and current_year
                    and max(years) < current_year):
                # A heading that still calls an older period the "current"
                # situation is stale even when it does not repeat a metric on
                # the same line.  Keeping it would let an obsolete narrative
                # frame survive above the page-confirmed baseline.
                stale_removed += 1; withheld += 1
                continue
            if (estimate and current_language and years and current_year
                    and max(years) <= current_year and not metrics):
                # Closed-period estimate headings (e.g. "Corrected FY2026
                # Baseline — Current Year Estimate") are obsolete once the
                # same exercise is page-confirmed.
                stale_removed += 1; withheld += 1
                continue
            stale_estimate = False
            if estimate and financial_language and current_year:
                line_years = years or ([current_year] if current_language else [])
                for year in line_years:
                    if year > current_year:
                        continue
                    if metrics:
                        if any((metric, year) in confirmed_by_period for metric in metrics):
                            stale_estimate = True; break
                    elif year == current_year:
                        stale_estimate = True; break
            if stale_estimate:
                stale_removed += 1; withheld += 1
                continue
            # Current-period factual-looking numbers must agree with the ledger.
            current_claim = bool(current_language or (current_year and current_year in years))
            fact_like = bool(re.search(r"\[(?:FACT|FAIT)\]|annual\s+reports?|source\s*:|actual", line, re.I))
            conflict = False
            if metrics and tokens and (fact_like or current_claim):
                conflict = not any(_value_matches(metric, token, confirmed)
                                   for metric in metrics for token in tokens)
            if conflict:
                withheld += 1
                continue
            lines.append(line)
        rendered = "\n".join(lines).strip()
        if key in injected_keys:
            prefix_block = block
            if key == "finance" and historical_conflict_note:
                prefix_block += "\n\n" + historical_conflict_note
            rendered = prefix_block + ("\n\n" + rendered if rendered else "")
        if rendered != original:
            clean[key] = rendered
            touched += 1
    return clean, {
        "applied": bool(touched), **summary,
        "fields_touched": touched,
        "lines_withheld": withheld,
        "stale_closed_period_estimates_removed": stale_removed,
        "authoritative_period_end": current_period,
        "canonical_claims": claims,
        "canonical_claim_count": len(claims),
    }


_EXT_LABELS50 = {"REVENUE": ("Revenue", "Chiffre d'affaires"), "OPERATING_PROFIT": ("Operating profit", "Résultat d'exploitation"),
                 "CASH": ("Cash and cash equivalents", "Trésorerie"), "HEADCOUNT": ("Headcount", "Effectif"),
                 "NET_INCOME": ("Net income", "Résultat net")}


def _latest_external50(external_facts, metric: str):
    best = None
    for f in external_facts or ():
        if isinstance(f, Mapping) and f.get("metric") == metric and (best is None or str(f.get("period_end")) > str(best.get("period_end"))):
            best = f
    return best


def _format_external_value50(f: Mapping[str, Any], lang: str) -> str:
    v = float(f.get("value") or 0)
    cur = {"USD": "$", "EUR": "€", "GBP": "£"}.get(str(f.get("currency") or ""), str(f.get("currency") or ""))
    if not cur:
        return f"{v:,.0f}".replace(",", " ")
    m = v / 1e6
    txt = f"{m:,.1f}" if abs(m) < 1000 else f"{m:,.0f}"
    if not str(lang).lower().startswith("en"):
        return txt.replace(",", " ").replace(".", ",") + f" M{cur}"
    return f"{cur}{txt}m"


def _period_end50(period: Any, external_facts, metric: str) -> str:
    for f in external_facts or ():
        if isinstance(f, Mapping) and f.get("metric") == metric and f.get("period") == period:
            return str(f.get("period_end") or "")
    m = re.fullmatch(r"FY((?:19|20)\d{2})", str(period or ""))
    return f"{m.group(1)}-12-31" if m else ""


def _days_between50(a: str, b: str) -> int:
    try:
        from datetime import date as _d
        ya, ma, da = (int(x) for x in str(a)[:10].split("-"))
        yb, mb, db = (int(x) for x in str(b)[:10].split("-"))
        return (_d(yb, mb, db) - _d(ya, ma, da)).days
    except Exception:
        return 0


def inject_confirmed_financial_kpis(data: MutableMapping[str, Any],
                                    table_or_facts: Any,
                                    lang: str = "en",
                                    canonical_claims: Optional[Sequence[Mapping[str, Any]]] = None,
                                    external_facts: Optional[Sequence[Mapping[str, Any]]] = None,
                                    analysis_date: str = "",
                                    fiscal_year_end: str = "") -> dict[str, Any]:
    """Populate executive KPI cards from the exact canonical claim set.

    v62.13.9.4.50 — RÈGLE DU DERNIER RÉALISÉ DATÉ (décision Robin du 30/09/2026) : chaque carte porte l'exercice de sa
    valeur ; quand les pièces fournies ne portent pas la métrique, le dernier réalisé d'un DÉPÔT (SEC, comptes
    déposés, registre) la renseigne, avec sa source courte ; une valeur dont l'exercice est clos depuis plus d'un an à
    la date d'analyse porte « dernier publié ». Les pièces passent toujours avant un dépôt."""
    facts = _iter_fact_objects(table_or_facts)
    claims = list(canonical_claims or build_canonical_financial_claims(facts, lang=lang))
    by_metric = {str(c.get("metric_id") or ""): c for c in claims}
    cc = data.setdefault("contexte_corporate", {})
    if not isinstance(cc, dict):
        cc = {}; data["contexte_corporate"] = cc
    changed: list[str] = []
    claim_ids: dict[str, str] = {}
    kpi_metadata: dict[str, dict[str, Any]] = {}
    def put(key: str, metric: str) -> None:
        claim = by_metric.get(metric)
        if claim:
            cc[key] = str(claim.get("display_value") or claim.get("value") or "")
            claim_ids[key] = str(claim.get("claim_id") or "")
            # v62.13.9.4.50 — libellé dans la langue du run (« Revenue / Chiffre d'affaires » s'affichait sur les
            # cartes du deck) et exercice de la valeur (règle du dernier réalisé daté)
            try:
                from utils.financial_facts_table import monolingual_metric_label as _mono50
                _lab50 = _mono50(str(claim.get("label") or ""), lang) or str(claim.get("label") or "")
            except Exception:
                _lab50 = str(claim.get("label") or "")
            kpi_metadata[key] = {
                "claim_id": str(claim.get("claim_id") or ""),
                "metric_id": str(claim.get("metric_id") or metric),
                "label": _lab50 or metric.replace("_", " ").title(),
                "sub": str(claim.get("period") or "")[:20],
                "proof_status": str(claim.get("proof_status") or ""),
                "period": str(claim.get("period") or ""),
                "value": str(claim.get("display_value") or claim.get("value") or ""),
                "period_end": str(claim.get("period_end") or claim.get("period_end_date") or ""),
            }
            changed.append(key)
        else:
            _ext = _latest_external50(external_facts, metric)
            if _ext:
                cc[key] = _format_external_value50(_ext, lang)
                claim_ids[key] = f"EXT-{metric}-{_ext.get('period_end')}"
                _src = re.sub(r"\s+—.*$", "", str(_ext.get("source") or "")).strip()   # « SEC EDGAR », « Pappers »…
                kpi_metadata[key] = {
                    "claim_id": claim_ids[key], "metric_id": metric,
                    "label": _EXT_LABELS50.get(metric, (metric, metric))[0 if str(lang).lower().startswith("en") else 1],
                    "sub": f"{_ext.get('period')} · {_src}"[:40], "proof_status": str(_ext.get("status") or ""),
                    "period": str(_ext.get("period") or ""), "value": cc[key], "external": True,
                    "period_end": str(_ext.get("period_end") or ""),
                }
                changed.append(key)
        # dernier réalisé : une valeur d'un exercice clos depuis plus d'un an porte « dernier publié »
        if key in kpi_metadata and analysis_date:
            _pe = kpi_metadata[key].get("period_end") or ""
            if not _pe and fiscal_year_end and str(kpi_metadata[key].get("period") or "").endswith(str(fiscal_year_end)[:4]):
                _pe = str(fiscal_year_end)          # clôture lue dans les pièces, pour l'exercice de la carte
            _pe = _pe or _period_end50(kpi_metadata[key].get("period"), external_facts, metric)
            if _pe and _days_between50(_pe, analysis_date) > 366:
                kpi_metadata[key]["sub"] = (kpi_metadata[key]["sub"] + (" · last published" if str(lang).lower().startswith("en")
                                                                         else " · dernier publié"))[:48]
    put("ca", "REVENUE")
    put("croissance", "REVENUE_GROWTH_REPORTED")
    if "ADJUSTED_OPERATING_MARGIN" in by_metric:
        put("marge", "ADJUSTED_OPERATING_MARGIN")
    elif "OPERATING_MARGIN" in by_metric:
        put("marge", "OPERATING_MARGIN")
    elif "ADJUSTED_OPERATING_PROFIT" in by_metric:
        put("resultat_operationnel", "ADJUSTED_OPERATING_PROFIT")
    else:
        put("resultat_operationnel", "OPERATING_PROFIT")     # v62.13.9.4.50 — pièce, sinon dernier dépôt
    if "CASH_NET_OF_OVERDRAFTS" in by_metric:
        put("cash", "CASH_NET_OF_OVERDRAFTS")
    else:
        put("cash", "CASH")                                   # v62.13.9.4.50 — pièce, sinon dernier dépôt
    if "HEADCOUNT" in by_metric:
        put("effectif", "HEADCOUNT")
    else:
        for key in ("effectif", "headcount"):
            value = str(cc.get(key) or "")
            if re.search(r"\b(?:stores?|shops?|boutiques?|magasins?|doors?|points?\s+of\s+sale)\b", value, re.I):
                cc.pop(key, None); changed.append(key + "_removed")
    cc["financial_kpi_source"] = "v62.13.3 canonical financial claims"
    cc["financial_kpi_claim_ids"] = claim_ids
    cc["financial_kpi_metadata"] = kpi_metadata
    data["canonical_financial_claims"] = claims
    return {"changed": changed, "claim_ids": claim_ids, **financial_proof_summary(facts)}


__all__ = [
    "PROOF_LAYER_VERSION", "CONFIRMED_ON_PAGE", "PAGE_UNAVAILABLE",
    "CONFLICT", "QUARANTINED", "OCR_REQUIRED", "CRITICAL_METRIC_IDS",
    "PageRecord", "ProofCandidate", "parse_paged_corpus",
    "build_page_confirmed_financial_facts", "confirmed_fact_rows",
    "latest_confirmed_facts", "financial_proof_summary",
    "canonical_current_financial_lines", "build_canonical_financial_claims",
    "build_board_numeric_support_claims", "reconcile_candidates",
    "normalize_period_end", "compute_dossier_authoritative_period_end",
    "CANONICAL_CURRENT", "CURRENT_CANONICAL", "CONTRIBUTING_HISTORY",
    "POST_CLOSE_INDICATION", "SUPERSEDED",
    "detect_ocr_required_documents",
    "quarantine_conflicting_ledger_facts", "update_temporal_frame_from_ledger",
    "reconcile_financial_narrative", "inject_confirmed_financial_kpis",
]

# ── v62.13.9.4.37 — CONFIRMATION À LA PAGE DE TOUT FAIT DÉCLARÉ, DANS TOUTE PIÈCE ──
#
# Run réel du 18/09/2026 (biscuiterie) : le compte rendu a été RETENU par le garde
# des nombres exécutifs sur « 123 456 € | 98 765 € » — engagements de retraite au
# 31/12/2024 et relevé IFC, tous deux écrits en clair dans le TRAITÉ DE FUSION fourni,
# et déclarés FAIT / CONSTATÉ / PASSÉ par l'agent. La preuve à la page ne couvrait que
# seize métriques fermées lues dans les états financiers : un acte juridique, un
# rapport de gestion, un procès-verbal n'y étaient jamais candidats. Décision de Robin
# (18/09) : un montant déclaré est confirmé s'il se retrouve TEXTUELLEMENT, avec sa
# page et le sujet de sa métrique à proximité, dans N'IMPORTE QUELLE pièce jointe —
# la nature du document n'est pas le critère, la vérification l'est. Les bornes : le
# montant ET un mot de la métrique sur la même page, à moins de 400 caractères ; un
# nom de fichier n'est pas une page (le « 18 » de « Actes du 18-01-2019 » ne confirme
# pas un BFR à 18 %) ; la période reste celle de la déclaration ou de la page, jamais
# promue en fait courant. Le registre externe (Pappers, GLEIF, SEC) est un niveau
# distinct, CONFIRMED_AT_REGISTRY, inactif en mode rétrospectif.

CONFIRMED_AT_REGISTRY = "CONFIRMED_AT_REGISTRY"

_DECL_STOP37 = frozenset(("de", "du", "des", "la", "le", "les", "un", "une", "et", "en", "au", "aux",
                          "of", "the", "a", "an", "and", "in", "on", "to", "for", "par", "sur", "pour"))


def _value_variants37(value: str) -> list[str]:
    """Écritures d'un même montant : 123456 → « 123 456 », « 123.456 », « 123456 »."""
    v = str(value or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    digits = re.sub(r"[^\d]", "", v.split(",")[0].split(".")[0]) if v else ""
    out = {v} if v else set()
    if digits and len(digits) >= 4:
        groups = []
        d = digits
        while len(d) > 3:
            groups.insert(0, d[-3:]); d = d[:-3]
        groups.insert(0, d)
        out.add(" ".join(groups)); out.add(".".join(groups)); out.add("\u202f".join(groups)); out.add(digits)
    return [x for x in out if x]


def _column_matches_period40(body: str, line_start: int, line_end: int, pos: int, year: str) -> bool:
    """v62.13.9.4.40 — vrai si la valeur trouvée en ``pos`` est dans la colonne de ``year``, ou si
    la colonne ne peut pas être établie sans ambiguïté (la règle précédente s'applique alors)."""
    try:
        from patches.financial_extractor import _TABLE_CELL_RE, _HEADER_PERIOD_LINE_RE
    except Exception:
        return True
    line = body[line_start:line_end]
    cells = [(line_start + c.start(), line_start + c.end()) for c in _TABLE_CELL_RE.finditer(line)
             if re.search(r"\d|[—–]", c.group(0))]
    if len(cells) < 2:
        return True
    idx = next((i for i, (a, b) in enumerate(cells) if a <= pos < b), -1)
    if idx < 0:
        return True
    above = body[:line_start].split("\n")[-40:]
    years: list[str] = []
    block_started = False
    for ln in reversed(above):
        if _HEADER_PERIOD_LINE_RE.match(ln) and ln.strip():
            block_started = True
            years = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", ln) + years
        elif block_started:
            break
    if len(years) != len(cells) or year not in years or len(set(years)) != len(years):
        return True
    return years.index(year) == idx


def confirm_declared_facts_in_corpus(declared_entries: Iterable[Any], pages: Sequence["PageRecord"],
                                     lang: str = "fr") -> list[dict[str, Any]]:
    """Faits déclarés FAIT/CONSTATÉ retrouvés à la page dans une pièce jointe.

    Rend des faits canoniques de la même forme que ceux du tableau financier, avec
    ``proof_status = CONFIRMED_ON_PAGE``, pièce, page et période. Un montant sans mot
    de sa métrique à proximité, ou trouvé dans un nom de fichier, n'est PAS confirmé.
    """
    en = str(lang or "fr").lower().startswith("en")
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for e in declared_entries or ():
        try:
            nature = str(_attr(e, "nature", "") or "").upper()
            modality = str(_attr(e, "modality", "") or "").upper()
            if nature != "FAIT" or modality not in ("CONSTATE", "CONSTATÉ", ""):
                continue
            value = str(_attr(e, "value", "") or "").strip()
            metric = str(_attr(e, "metric", "") or "").strip().lower()
            if not value or not metric or (value, metric) in seen:
                continue
            words = [w for w in re.findall(r"[a-zà-ÿ]{3,}", metric) if w not in _DECL_STOP37]
            if not words:
                continue
            # radical de 4 lettres pour les mots longs (« couverture » ↔ « couvrir »,
            # « engagements » ↔ « engagement ») ; les mots courts restent exacts. Le
            # radical seul ne suffit jamais : il faut AUSSI le montant sur la même page.
            stems = [w[:4] if len(w) >= 6 else w for w in words]
            variants = _value_variants37(value)
            found = None
            for page in pages:
                body = str(getattr(page, "text", "") or "")
                if not body:
                    continue
                for var in variants:
                    for m in re.finditer(re.escape(var), body):
                        # frontières : pas au milieu d'un nombre plus long
                        if (m.start() > 0 and body[m.start() - 1].isdigit()) or \
                           (m.end() < len(body) and body[m.end()].isdigit()):
                            continue
                        # v62.13.9.4.40 — UNE CONFIRMATION PORTE SUR LE FAIT COMPLET, PAS SUR UN NOMBRE.
                        # Dossier réel du 21/09/2026 : des « faits confirmés à la page » dont une dette
                        # nette en unité de compte, périmètre inconnu, pièce d'un autre exercice — le
                        # libellé était cherché à ±400 caractères, n'importe où sur la page. Le libellé
                        # doit être sur la MÊME LIGNE (ou la ligne d'en-tête qui la précède) ; une valeur
                        # présentée sur la page comme cible ou hypothèse n'est pas un fait constaté ; une
                        # période déclarée doit apparaître sur la page.
                        _ls40 = body.rfind("\n", 0, m.start()) + 1
                        _le40 = body.find("\n", m.end()); _le40 = len(body) if _le40 < 0 else _le40
                        _prevl40 = body.rfind("\n", 0, max(0, _ls40 - 1)) + 1
                        ctx = body[_prevl40:_le40].lower()
                        if not any(st in ctx for st in stems):
                            continue
                        if re.search(r"(?i)\b(?:target|objectif|cible|goal|ambition|guidance|assumption|hypoth[èe]se|"
                                     r"scenario|sc[ée]nario|forecast|pr[ée]vision|by\s+fy|d.ici\s+fy|outlook)\b", body[_ls40:_le40]):
                            continue
                        _per40 = str(_attr(e, "period", "") or "")
                        _yr40 = re.search(r"(?:19|20)\d{2}", _per40)
                        if _yr40 and _yr40.group(0) not in body and _yr40.group(0)[2:] not in re.findall(r"FY\s?(\d{2})\b", body):
                            continue
                        # v62.13.9.4.40 — LA COLONNE DE LA PÉRIODE. Un tableau d'états porte deux ou trois
                        # exercices côte à côte : « la période figure sur la page » ne suffit pas, la valeur
                        # de l'exercice précédent confirmerait une affirmation sur l'exercice courant. Quand
                        # l'en-tête du tableau compte autant d'exercices que la ligne a de valeurs, la valeur
                        # doit être dans la colonne de sa période ; sinon (colonnes brut / amortissements /
                        # net d'une liasse, note en première colonne) la règle précédente s'applique.
                        if _yr40 and not _column_matches_period40(body, _ls40, _le40, m.start(), _yr40.group(0)):
                            continue
                        found = (page, m.start()); break
                    if found: break
                if found: break
            if not found:
                continue
            page, pos = found
            unit = str(_attr(e, "unit", "") or "")
            if re.search(r"(?i)\b(?:debt|dette|revenue|chiffre|sales|ventes|profit|r[ée]sultat|ebitda|cash|tr[ée]sorerie|"
                         r"capex|borrowings|emprunts|equity|capitaux|stocks?|inventor)", metric) and \
               str(unit).strip().upper() in ("COUNT", "NB", "NOMBRE", "UNITS", "PERSONS"):
                continue      # v62.13.9.4.40 — un montant ne se confirme pas en unité de compte
            period = str(_attr(e, "period", "") or "")
            label = metric[:1].upper() + metric[1:]
            display = f"{value} {unit}".strip()
            # forme canonique attendue par le garde des nombres exécutifs : unité de
            # famille (CUR / PCT / COUNT), valeur numérique normalisée, composantes
            # typées — sinon « 123 456 € » (money) ne s'apparie pas à une composante
            # « number ». Devise et échelle lues sur la page à l'endroit du montant.
            _num = None
            try:
                _num = float(re.sub(r"[^\d.,-]", "", value).replace(" ", "").replace(",", "."))
            except Exception:
                _num = None
            _tail = str(getattr(page, "text", "") or "")[pos: pos + 40].lower()
            _u = unit.lower()
            if _u in ("€", "eur", "euro", "euros", "k€", "m€", "md€", "$", "usd", "£", "gbp") or \
               re.match(r"\s*(?:€|eur|euros?|k€|m€|md€|\$|£)", _tail):
                _fam, _cur = "CUR", ("EUR" if ("€" in _u or "eur" in _u or "€" in _tail or "eur" in _tail) else
                                     "USD" if ("$" in _u or "usd" in _u or "$" in _tail) else
                                     "GBP" if ("£" in _u or "gbp" in _u or "£" in _tail) else "EUR")
                _scale = 1_000 if "k€" in _u else 1_000_000 if "m€" in _u else 1_000_000_000 if "md€" in _u else 1
                _kind = "money"
            elif "%" in _u or "pct" in _u or "pourcent" in _u:
                _fam, _cur, _scale, _kind = "PCT", "", 1, "pct"
            else:
                _fam, _cur, _scale, _kind = "COUNT", "", 1, "number"
            _norm = (_num * _scale) if _num is not None else None
            executive = (f"{label}: {display} ({period})" if en else f"{label} : {display} ({period})") \
                if period else (f"{label}: {display}" if en else f"{label} : {display}")
            claims.append({
                "claim_id": f"decl-page-{len(claims) + 1}",
                "claim_type": "FACT",
                "metric_id": re.sub(r"[^a-z0-9]+", "_", metric).strip("_"),
                "label": label,
                "value": display,
                "normalized_value": _norm,
                "unit": _fam,
                "currency": _cur,
                "numeric_components": ([{"kind": _kind, "value": _norm}] if _norm is not None else []),
                "period": period,
                "period_end_date": "",
                "scope": "UNKNOWN",
                "source_doc": str(getattr(page, "source_doc", "") or ""),
                "source_page": getattr(page, "source_page", None),
                "source_refs": [{"source_doc": str(getattr(page, "source_doc", "") or ""), "source_page": getattr(page, "source_page", None)}],
                "fact_instance_ids": [],
                "stable_fact_keys": [],
                "proof_status": CONFIRMED_ON_PAGE,
                "display_value": display,
                "executive_line": executive,
                "provenance": "declared_fact_found_on_page",
            })
            seen.add((value, metric))
        except Exception:
            continue
    return claims
