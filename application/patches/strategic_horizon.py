"""Deterministic strategic-horizon reconciliation (v62.10).

The user's explicit wording is authoritative.  A structured UI field must never
reduce ``plan stratégique à 2 ans`` / ``two-year strategic plan`` to one year.
The reconciled brief also carries a deterministic end date when a run date is
available, so agents cannot call an already-closed fiscal year the first year of
a forward-looking plan.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any


@dataclass
class HorizonReconciliation:
    explicit_months: int | None = None
    previous_value: str = ""
    final_value: str = ""
    changed: bool = False
    reason: str = ""
    language: str = ""
    target_end_date: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_TWO_YEAR_RE = re.compile(
    r"\b(?:"
    r"plan\s+strat[ée]gique[^\n]{0,100}(?:à|sur|horizon)?\s*(?:2|deux)\s+ans?|"
    r"horizon[^\n]{0,40}(?:2|deux)\s+ans?|24\s+mois|"
    r"two[\s-]+year\s+(?:strategic\s+)?plan|(?:strategic\s+)?plan[^\n]{0,100}(?:for|over|across)?\s*(?:2|two)\s+years?|"
    r"(?:2|two)[\s-]+year\s+horizon|24\s+months"
    r")\b",
    re.IGNORECASE,
)
_HORIZON_LINE_RE = re.compile(
    r"(?im)^(?P<prefix>\s*(?:▌\s*)?Horizon\s*:\s*)(?P<value>[^\n]+)$"
)
_END_DATE_LINE_RE = re.compile(
    r"(?im)^\s*(?:▌\s*)?(?:Date\s+de\s+fin\s+cible|Target\s+end\s+date)\s*:\s*"
    r"(?P<date>20\d{2}-\d{2}-\d{2})\s*$"
)
_ENGLISH_HINT_RE = re.compile(
    r"\b(?:two[\s-]+year|24\s+months|strategic\s+plan|board|company|listed|group\s+plc)\b",
    re.I,
)


def _coerce_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


def _add_months(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(idx, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def reconcile_strategic_horizon(
    brief: str,
    *,
    run_date: Any = None,
    lang: str | None = None,
) -> tuple[str, HorizonReconciliation]:
    """Reconcile an explicit two-year request with the structured horizon.

    The function is idempotent.  ``run_date`` may be an ISO string, date or
    datetime.  When provided, a deterministic target end date (run + 24 months)
    is appended once to the canonical brief.
    """
    text = str(brief or "")
    report = HorizonReconciliation()
    if not _TWO_YEAR_RE.search(text):
        return text, report

    is_en = str(lang or "").lower().startswith("en") or bool(_ENGLISH_HINT_RE.search(text))
    report.language = "en" if is_en else "fr"
    report.explicit_months = 24
    final_value = "24 months" if is_en else "24 mois"

    m = _HORIZON_LINE_RE.search(text)
    if m:
        previous = m.group("value").strip()
        report.previous_value = previous
        report.final_value = final_value
        if not re.search(r"\b(?:24\s+(?:mois|months)|2\s+ans?|two\s+years?)\b", previous, re.I):
            text = text[:m.start("value")] + final_value + text[m.end("value"):]
            report.changed = True
            report.reason = (
                "explicit two-year/24-month horizon overrides the shorter structured field"
                if is_en else
                "horizon explicite 2 ans/24 mois prioritaire sur le champ structuré"
            )
    else:
        report.final_value = final_value
        report.reason = (
            "explicit two-year/24-month horizon detected"
            if is_en else "horizon explicite 2 ans/24 mois détecté"
        )

    existing_end = _END_DATE_LINE_RE.search(text)
    if existing_end:
        report.target_end_date = existing_end.group("date")

    rd = _coerce_date(run_date)
    if rd is not None:
        end = _add_months(rd, 24).isoformat()
        # v62.13.9.4.40 — une borne explicite qui contredit « date d'analyse + 24 mois » est
        # SIGNALÉE, pas écrasée en silence : l'utilisateur a pu la vouloir.
        if existing_end and str(existing_end.group("date")) != end:
            try:
                report.conflict = f"explicit end {existing_end.group('date')} ≠ analysis date + 24 months = {end}"
            except Exception:
                pass
        report.target_end_date = end
        if not _END_DATE_LINE_RE.search(text):
            label = "Target end date" if is_en else "Date de fin cible"
            text = text.rstrip() + f"\n▌ {label} : {end}"
            report.changed = True
            if report.reason:
                report.reason += "; "
            report.reason += (
                "forward end date calculated from the actual run date"
                if is_en else "date de fin prospective calculée depuis la date réelle du run"
            )

    return text, report

def enforce_horizon_in_outputs(
    outputs: dict[str, Any] | None,
    *,
    target_end_date: str = "",
    lang: str = "fr",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Make the 12–24 month window explicit in executive narratives.

    This is a framing contract, not a forecast. It prevents an otherwise good
    short-term recovery plan from being presented as the full two-year plan.
    """
    clean = dict(outputs or {})
    report = {
        "applied": False,
        "target_end_date": target_end_date,
        "fields_touched": 0,
    }
    end = _coerce_date(target_end_date)
    if end is None:
        return clean, report

    report["applied"] = True
    en = str(lang or "fr").lower().startswith("en")
    end_iso = end.isoformat()
    end_label = end_iso if en else end.strftime("%d/%m/%Y")
    if en:
        note = (
            "## 12–24 MONTH HORIZON — PLANNING CONTRACT\n"
            f"- Target end date: {end_iso}.\n"
            "- The roadmap must include at least one milestone in the 12–24 "
            "month window; earlier phases are interim recovery steps, not the "
            "full two-year plan."
        )
    else:
        note = (
            "## HORIZON 12–24 MOIS — CONTRAT DE PLANIFICATION\n"
            f"- Date de fin cible : {end_label}.\n"
            "- La feuille de route doit contenir au moins un jalon dans la "
            "fenêtre 12–24 mois ; les phases antérieures sont des étapes de "
            "redressement, pas l'intégralité du plan à deux ans."
        )

    target_year = str(end.year)
    for key in ("synthese_decisions", "direction_generale", "ceo"):
        value = clean.get(key)
        if not isinstance(value, str) or not value:
            continue
        if end_iso in value or target_year in value:
            continue
        clean[key] = value.rstrip() + "\n\n" + note
        report["fields_touched"] += 1
    return clean, report

def ensure_roadmap_reaches_target(
    data: dict[str, Any] | None,
    *,
    target_end_date: str = "",
    lang: str = "fr",
) -> dict[str, Any]:
    """Ensure the Working Deck contains a visible 12–24 month phase."""
    out = dict(data or {})
    end = _coerce_date(target_end_date)
    roadmap = list(out.get("roadmap") or [])
    if end is None or not roadmap:
        return out
    blob = " ".join(str(x) for x in roadmap)
    if end.isoformat() in blob or str(end.year) in blob:
        return out
    en = str(lang or "fr").lower().startswith("en")
    phase = {
        "phase": "T+12–24m" if en else "T+12–24 mois",
        "date": (f"Target by {end.isoformat()}" if en else
                 f"Cible au {end.strftime('%d/%m/%Y')}"),
        "titre": ("Strategic consolidation and next-cycle readiness" if en else
                  "Consolidation stratégique et préparation du cycle suivant"),
        "items": ([
            "Validate sustained revenue, margin and cash recovery from verified reporting",
            "Confirm portfolio, channel and capital-allocation choices",
            "Approve the next strategic cycle from the end-state scorecard",
        ] if en else [
            "Valider la pérennité du redressement CA, marge et cash depuis le reporting vérifié",
            "Confirmer les choix de portefeuille, canaux et allocation du capital",
            "Approuver le cycle stratégique suivant depuis la scorecard cible",
        ]),
        "kpi": ("Board-approved 24-month end-state scorecard" if en else
                "Scorecard cible à 24 mois validée"),
        "budget": ("To be defined from verified baseline" if en else
                   "À définir depuis la baseline vérifiée"),
        "extra": "",
    }
    roadmap = (roadmap[:3] + [phase]) if len(roadmap) >= 4 else (roadmap + [phase])
    out["roadmap"] = roadmap
    return out

