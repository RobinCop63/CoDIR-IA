"""Current-financial-truth fail-closed guard (v62.10.2).

The dossier anglophone coté v62.10.1 terrain run exposed a dangerous state: the engine knew
that the latest registry filing had not been parsed, detected a hard
metric/scope conflict and had zero page-confirmed critical facts, yet the Word
and PPTX still promoted a quantified "current situation".

This hotfix does not attempt to parse financial statements.  It enforces a
small safety invariant before the full v62.11 proof layer:

* when current critical financial evidence is not established, quantified
  current-state claims are removed from executive surfaces;
* the limitation is stated once, visibly and locally;
* decision usefulness is capped at exploratory use;
* historical/identity metadata and non-financial analysis remain available.

The full page-confirmed ledger is implemented separately in v62.11.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import re
from typing import Any, Mapping, MutableMapping

_CONFIRMED = {"verbatim_on_page", "normalized_on_page", "CONFIRMED_ON_PAGE"}
_CRITICAL_IDS = {
    "REVENUE", "OPERATING_PROFIT", "ADJUSTED_OPERATING_PROFIT",
    "OPERATING_MARGIN", "NET_INCOME", "FREE_CASH_FLOW", "CASH",
    "NET_DEBT", "GROSS_DEBT", "EBIT", "EBITDA",
}
_CRITICAL_LABEL = re.compile(
    r"\b(?:revenue|turnover|net\s+sales|sales|chiffre\s+d['’]affaires|\bCA\b|"
    r"adjusted\s+operating\s+profit|operating\s+(?:profit|loss|margin)|"
    r"résultat\s+(?:opérationnel|d['’]exploitation|net)|marge\s+opérationnelle|"
    r"net\s+(?:income|profit|loss|debt)|free\s+cash\s+flow|\bFCF\b|"
    r"cash(?:\s+and\s+cash\s+equivalents)?|trésorerie|gross\s+debt|"
    r"dette\s+(?:brute|nette)|\bEBITDA\b|\bEBIT\b)\b",
    re.I,
)
_NUMERIC = re.compile(
    r"(?:[£€$]\s*\(?\s*[-+]?\d|\(?\s*[-+]?\d[\d\s,.]*\s*(?:%|bps|x\b|m\b|bn\b|million|billion|M€|M£|M\$))",
    re.I,
)
_SAFE_WORDING = re.compile(
    r"not\s+(?:available|established|specified)|to\s+collect|to\s+verify|"
    r"undetermined|withheld|baseline|provenance|non\s+(?:communiqu|disponible)|"
    r"à\s+(?:collecter|vérifier|établir)|indéterminé|écarté",
    re.I,
)
_FACT_TAG = re.compile(r"\[(?:FACT|FAIT)\]", re.I)


def _year(value: Any) -> int | None:
    text = str(value or "")
    # Accept canonical periods emitted across the engine: ``2026-03-28``,
    # ``FY2026``, ``FY26`` and split fiscal labels such as ``FY25/26``.
    # For split labels, the end year is the relevant comparison point.
    split = re.search(r"\bFY\s*(?:20)?(\d{2})\s*/\s*(?:20)?(\d{2})\b", text, re.I)
    if split:
        return 2000 + int(split.group(2))
    fy = re.search(r"\bFY\s*(20\d{2}|\d{2})\b", text, re.I)
    if fy:
        raw = fy.group(1)
        return int(raw) if len(raw) == 4 else 2000 + int(raw)
    years = [int(x) for x in re.findall(r"\b(20\d{2})\b", text)]
    if years:
        return max(years)
    return None


def _fact_metric_id(fact: Any) -> str:
    if isinstance(fact, Mapping):
        return str(fact.get("metric_canonical_id") or fact.get("metric") or "").upper()
    return str(getattr(fact, "metric_canonical_id", "") or "").upper()


def _fact_fidelity(fact: Any) -> str:
    if isinstance(fact, Mapping):
        return str(fact.get("proof_status") or fact.get("fidelity_page") or "")
    return str(getattr(fact, "proof_status", "") or getattr(fact, "fidelity_page", "") or "")


def _fact_period(fact: Any) -> str:
    if isinstance(fact, Mapping):
        return str(fact.get("period") or fact.get("document_date") or "")
    return str(getattr(fact, "period", "") or getattr(fact, "document_date", "") or "")


def _iter_facts(table: Any):
    if table is None:
        return []
    for attr in ("facts", "rows", "items", "entries"):
        value = getattr(table, attr, None)
        if value is not None:
            return list(value or [])
    if isinstance(table, (list, tuple)):
        return list(table)
    if isinstance(table, Mapping):
        for key in ("facts", "rows", "items", "entries"):
            if key in table:
                return list(table.get(key) or [])
    return []


def _risk_flags(mission_report: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(mission_report, Mapping):
        return set()
    return {str(x).upper() for x in (mission_report.get("risk_flags") or [])}


@dataclass
class CurrentFinancialTruthReport:
    applied: bool = False
    current_financial_state_established: bool = False
    blockers: list[str] | None = None
    latest_registry_year: int | None = None
    latest_parsed_year: int | None = None
    latest_confirmed_critical_year: int | None = None
    page_confirmed_critical_facts: int = 0
    fields_touched: int = 0
    lines_removed: int = 0
    usefulness_cap: int | None = None
    evidence_cap: int | None = None
    pre_truth_evidence_score: int | None = None
    message: str = ""
    policy: str = ""                     # v62.13.9.4.50 — « FLAG_IN_PLACE » : rien retiré, limite dite en tête

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["blockers"] = list(self.blockers or [])
        return out


def _period_key(value: Any) -> tuple[int, int, int] | None:
    """Comparable financial date key; year-only labels map to year end."""
    text = str(value or "")
    iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if iso:
        return tuple(int(iso.group(i)) for i in (1, 2, 3))
    y = _year(text)
    return (y, 12, 31) if y else None


def compute_final_current_financial_truth(
    *,
    facts_table: Any = None,
    temporal_frame: Any = None,
    mission_report: Mapping[str, Any] | None = None,
    financial_signal_solid: bool = False,
) -> dict[str, Any]:
    """Single final truth consumed by mission gate, Word, PPTX and scores.

    A ledger-only baseline is not "current" when the registry points to a
    newer filing.  Conversely, a generic narrative conflict does not block a
    page-confirmed current ledger with no current critical conflict.
    """
    facts = _iter_facts(facts_table)
    confirmed = [f for f in facts
                 if _fact_metric_id(f) in _CRITICAL_IDS
                 and _fact_fidelity(f) in _CONFIRMED]
    confirmed_periods = [
        str((f.get("period_end_date") if isinstance(f, Mapping)
             else getattr(f, "period_end_date", "")) or _fact_period(f) or "")
        for f in confirmed
    ]
    latest_confirmed_text = max(
        confirmed_periods,
        key=lambda x: _period_key(x) or (0, 0, 0),
        default="",
    )
    latest_confirmed = _year(latest_confirmed_text)
    registry_text = str(getattr(temporal_frame, "latest_accounts_date", "") or "")
    latest_registry = _year(registry_text)
    document_text = str(
        getattr(temporal_frame, "latest_document_year_detected", "")
        or getattr(temporal_frame, "latest_parsed_financial_period", "")
        or ""
    )
    latest_document = _year(document_text)
    try:
        summary = (facts_table.proof_summary()
                   if hasattr(facts_table, "proof_summary") else {})
    except Exception:
        summary = {}
    current_conflicts = int(summary.get("current_critical_conflicts") or 0)
    ledger_established = bool(
        summary.get("current_financial_state_established")
        and current_conflicts == 0
    )
    # Backward-compatible fallback for legacy callers passing a bare fact list
    # rather than the FinancialFactsTable object. Production calls always carry
    # the structured summary; tests and imported historical sessions may not.
    if not summary and confirmed and current_conflicts == 0:
        ledger_established = True
    blockers: list[str] = []
    if current_conflicts:
        blockers.append("CURRENT_CRITICAL_FACT_CONFLICT")
    if financial_signal_solid and not confirmed:
        blockers.append("NO_PAGE_CONFIRMED_CRITICAL_METRICS")
    # Compatibility + observability: distinguish a newer registry filing that
    # was not even reached by the document scan from one scanned but lacking
    # critical page-confirmed facts.
    if latest_registry and (not latest_document or latest_document < latest_registry):
        blockers.append("NEWER_REGISTRY_PERIOD_UNPARSED")
    reg_key = _period_key(registry_text)
    conf_key = _period_key(latest_confirmed_text)
    if reg_key and (not conf_key or conf_key < reg_key):
        blockers.append("LATEST_CRITICAL_FACT_OLDER_THAN_REGISTRY")
    flags = _risk_flags(mission_report)
    if "HARD_METRIC_SCOPE_CONFLICT" in flags and (not ledger_established or not summary):
        blockers.append("HARD_METRIC_SCOPE_CONFLICT")
    # Deduplicate while preserving order for deterministic diagnostics.
    blockers = list(dict.fromkeys(blockers))
    established = bool(ledger_established and not blockers)
    return {
        "current_financial_state_established": established,
        "blockers": blockers,
        "latest_registry_year": latest_registry,
        "latest_registry_date": registry_text,
        "latest_document_year_detected": latest_document,
        "latest_document_period_detected": document_text,
        "latest_confirmed_critical_year": latest_confirmed,
        "latest_confirmed_critical_period": latest_confirmed_text,
        "page_confirmed_critical_facts": len(confirmed),
        "current_critical_conflicts": current_conflicts,
        "proof_summary_current_established": ledger_established,
    }


def apply_final_truth_to_temporal_frame(temporal_frame: Any,
                                        report: Mapping[str, Any] | None,
                                        *, lang: str = "fr") -> Any:
    if temporal_frame is None or not isinstance(report, Mapping):
        return temporal_frame
    established = bool(report.get("current_financial_state_established"))
    temporal_frame.current_established = established
    latest = str(report.get("latest_confirmed_critical_period") or "")
    if latest:
        temporal_frame.latest_confirmed_critical_period = latest
    if not getattr(temporal_frame, "latest_document_year_detected", ""):
        doc_period = str(report.get("latest_document_period_detected") or "")
        if doc_period:
            temporal_frame.latest_document_year_detected = doc_period
    blockers = list(report.get("blockers") or [])
    en = str(lang or "fr").lower().startswith("en")
    if established:
        temporal_frame.established_reason = ""
        temporal_frame.parsed_period_note = ""
    else:
        reason_map = {
            "CURRENT_CRITICAL_FACT_CONFLICT": (
                "unresolved critical conflict on the current period",
                "conflit critique non résolu sur la période courante"),
            "NEWER_REGISTRY_PERIOD_UNPARSED": (
                "newer registry filing not reached by the document scan",
                "dépôt registre plus récent non atteint par le scan documentaire"),
            "LATEST_CRITICAL_FACT_OLDER_THAN_REGISTRY": (
                "latest critical page-confirmed fact is older than the registry filing",
                "le dernier fait critique confirmé est antérieur au dépôt registre"),
            "NO_PAGE_CONFIRMED_CRITICAL_METRICS": (
                "no page-confirmed critical financial metric",
                "aucune métrique financière critique confirmée à la page"),
            "HARD_METRIC_SCOPE_CONFLICT": (
                "hard metric/scope conflict remains unresolved",
                "conflit dur de métrique/périmètre non résolu"),
        }
        reasons = [reason_map.get(b, (b, b))[0 if en else 1] for b in blockers]
        # v62.13.9.4.46 — un « non » sans raison n'est pas un verdict : quand aucun bloqueur
        # n'est nommé, la raison est celle du registre de preuve lui-même — pas de période
        # critique confirmée à la page.
        if not reasons:
            reasons = ["no page-confirmed critical period" if en else "aucune période critique confirmée à la page"]
        temporal_frame.established_reason = "; ".join(reasons)
        temporal_frame.parsed_period_note = (
            "Registry metadata is newer than the latest critical page-confirmed period; the current financial position remains unestablished."
            if en else
            "La métadonnée registre est plus récente que la dernière période critique confirmée ; la position financière courante reste non établie."
        ) if "LATEST_CRITICAL_FACT_OLDER_THAN_REGISTRY" in blockers else ""
    return temporal_frame


def _message(lang: str, blockers: list[str]) -> str:
    en = str(lang or "fr").lower().startswith("en")
    if en:
        return (
            "CURRENT FINANCIAL POSITION NOT ESTABLISHED — the latest usable "
            "page-confirmed financial evidence is incomplete or older than the "
            "latest registry filing. Verify and parse the latest filing before "
            "using a quantified current-state diagnosis."
        )
    return (
        "SITUATION FINANCIÈRE ACTUELLE NON ÉTABLIE — la dernière preuve "
        "financière exploitable et confirmée à la page est incomplète ou plus "
        "ancienne que le dernier dépôt registre. Vérifier et parser le dernier "
        "dépôt avant tout diagnostic chiffré de situation actuelle."
    )


# Une proposition datée et attribuée : « [1] Mettre en œuvre … | DAF | avant 2026-10-31 | … »
_PROPOSAL_LINE = re.compile(
    r"^\s*(?:[-*•]|\[\s*\d{1,2}\s*\]|\d{1,2}[.)])\s*[^|]{10,}\|.*\|"
    r"|^\s*(?:[-*•]|\[\s*\d{1,2}\s*\]|\d{1,2}[.)])\s*(?:mettre|lancer|engager|structurer|d[ée]ployer|"
    r"organiser|formaliser|conduire|r[ée]aliser|auditer|arbitrer|n[ée]gocier|recruter|construire)\b", re.I)


def _sanitize_text(text: str, message: str) -> tuple[str, int]:
    if not isinstance(text, str) or not text:
        return text or "", 0
    out: list[str] = []
    removed = 0
    inserted = False
    for line in text.splitlines():
        if (_CRITICAL_LABEL.search(line) and _NUMERIC.search(line)
                and not _SAFE_WORDING.search(line)):
            # v62.13.9.4.31 — contre-audit v30 (§3) : une PROPOSITION (décision,
            # action, arbitrage) portant un porteur et une échéance n'est pas une
            # affirmation de situation financière : elle est conservée, seule sa
            # partie chiffrée est réécrite. Sans cela, les cinq priorités du
            # dossier disparaissaient derrière le message de limitation.
            _prop = _PROPOSAL_LINE.search(line)
            if _prop:
                try:
                    from utils.editorial_quantity import rewrite_quantities as _rq, residual_cardinals as _rc
                    _cand = _rq(line, "fr")
                    # les fragments d'une date ISO (« 2026-10-31 ») ne sont pas des
                    # grandeurs résiduelles : ils sont masqués avant le contrôle
                    _probe = re.sub(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b", " ", _cand or "")
                    if _cand and not _rc(_probe):
                        if not inserted:
                            out.append(message)
                            inserted = True
                        out.append(_cand)
                        continue
                except Exception:
                    pass
            removed += 1
            if not inserted:
                out.append(message)
                inserted = True
            continue
        # A stale quantified FACT tag is particularly dangerous.  The line is
        # withheld even if it escaped the generic numeric pattern.
        if _FACT_TAG.search(line) and _CRITICAL_LABEL.search(line) and not _SAFE_WORDING.search(line):
            removed += 1
            if not inserted:
                out.append(message)
                inserted = True
            continue
        out.append(line)
    if not inserted:
        # The limitation must remain visible even when no line happened to be
        # numeric in this particular agent output.
        out.insert(0, message)
    return "\n".join(out), removed


_FLAG_IN_PLACE50 = True


def govern_current_financial_truth(
    outputs: Mapping[str, Any] | None,
    *,
    facts_table: Any = None,
    extraction_fidelity: Mapping[str, Any] | None = None,
    mission_report: Mapping[str, Any] | None = None,
    temporal_frame: Any = None,
    finance_tone: str = "",
    financial_signal_solid: bool = False,
    lang: str = "fr",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail closed on quantified current-state claims when proof is absent.

    The guard is intentionally limited to ``BOARD_SCRUTINY``.  It does not
    parse or correct figures; it only prevents unsafe promotion until v62.11.
    """
    clean = dict(outputs or {})
    rep = CurrentFinancialTruthReport(blockers=[])
    if str(finance_tone or "").upper() != "BOARD_SCRUTINY":
        return clean, rep.to_dict()

    final_truth = compute_final_current_financial_truth(
        facts_table=facts_table,
        temporal_frame=temporal_frame,
        mission_report=mission_report,
        financial_signal_solid=financial_signal_solid,
    )
    rep.latest_registry_year = final_truth.get("latest_registry_year")
    rep.latest_parsed_year = final_truth.get("latest_document_year_detected")
    rep.latest_confirmed_critical_year = final_truth.get("latest_confirmed_critical_year")
    rep.page_confirmed_critical_facts = int(
        final_truth.get("page_confirmed_critical_facts") or 0)
    rep.blockers = list(final_truth.get("blockers") or [])
    rep.current_financial_state_established = bool(
        final_truth.get("current_financial_state_established")
    )
    apply_final_truth_to_temporal_frame(temporal_frame, final_truth, lang=lang)
    blockers = list(rep.blockers or [])
    if rep.current_financial_state_established:
        return clean, rep.to_dict()

    rep.applied = True
    rep.usefulness_cap = 44
    # A report cannot simultaneously state that the current financial truth is
    # unavailable and advertise Grade B / "Client OK" evidence.  Keep the
    # historical ledger visible, but cap the overall evidence label at Grade D.
    rep.evidence_cap = 55
    rep.message = _message(lang, blockers)
    if _FLAG_IN_PLACE50:
        # v62.13.9.4.50 — doctrine « tout livrer, tout signaler en place » (28/09/2026) : les lignes de situation
        # chiffrée ne sont plus retirées ni réécrites (contre-recette du 30/09 : chiffres des cartes clés perdus,
        # propositions réécrites). La limite est dite UNE fois, en tête des documents (signalement de document), et
        # les chiffres affichés portent leur exercice (règle du dernier réalisé daté).
        rep.policy = "FLAG_IN_PLACE"
        return clean, rep.to_dict()
    for key, value in list(clean.items()):
        if not isinstance(value, str) or not value:
            continue
        new, removed = _sanitize_text(value, rep.message)
        if new != value:
            clean[key] = new
            rep.fields_touched += 1
            rep.lines_removed += removed
    return clean, rep.to_dict()


def apply_truth_caps(confidence: MutableMapping[str, Any] | None,
                     report: Mapping[str, Any] | None,
                     *,
                     lang: str = "fr") -> None:
    """Apply coherent evidence and usefulness caps from the truth guard.

    v62.11.3.1 exposed a contradictory surface: evidence 70/Grade B/Client OK
    next to usefulness 44/Band E/Not usable.  When current financial truth is
    withheld, both indicators now tell the same safety story while preserving
    their distinct meanings.
    """
    if not isinstance(confidence, MutableMapping) or not isinstance(report, Mapping):
        return

    ucap = report.get("usefulness_cap")
    if ucap is not None:
        confidence["decision_usefulness_cap"] = int(ucap)

    ecap = report.get("evidence_cap")
    if ecap is not None and bool(report.get("applied")):
        try:
            current = int(confidence.get("score") or 0)
            cap = int(ecap)
        except Exception:
            current, cap = 0, int(ecap or 55)
        if current > cap:
            confidence["pre_current_financial_truth_score"] = current
            if isinstance(report, MutableMapping):
                report["pre_truth_evidence_score"] = current
            confidence["score"] = cap
            confidence["final_score"] = cap
            confidence["final_evidence_score"] = cap
            confidence["post_current_financial_truth_cap_score"] = cap
            try:
                from patches.confidence_scorer import grade_and_usage
                grade, label, usage = grade_and_usage(cap, lang)
            except Exception:
                grade = "D"
                label = ("Internal scoping only" if str(lang).lower().startswith("en")
                         else "Cadrage interne uniquement")
                usage = {
                    "internal_codir": "LIMITED",
                    "client_presentation": "NO",
                    "board": "NO",
                    "public_external_use": "NO",
                }
            confidence["grade"] = grade
            confidence["label"] = label
            confidence["usage_recommendation"] = usage
            confidence["current_financial_truth_evidence_cap"] = cap
            penalties = confidence.setdefault("penalties", [])
            if not any(isinstance(x, Mapping) and
                       x.get("code") == "CURRENT_FINANCIAL_TRUTH_EVIDENCE_CAP"
                       for x in penalties):
                penalties.append({
                    "code": "CURRENT_FINANCIAL_TRUTH_EVIDENCE_CAP",
                    "impact": cap - current,
                    "component": "source_quality",
                    "reason": (
                        "Current financial position not established; evidence "
                        "grade capped at D until the latest filing is parsed and "
                        "page-confirmed."
                        if str(lang).lower().startswith("en") else
                        "Situation financière actuelle non établie ; solidité "
                        "probatoire plafonnée à D tant que le dernier dépôt "
                        "n'est pas parsé et confirmé à la page."
                    ),
                })
            explanation = confidence.setdefault("confidence_explanation", [])
            reason = ("Current financial position not established — evidence capped at Grade D."
                      if str(lang).lower().startswith("en") else
                      "Situation financière actuelle non établie — preuve plafonnée au Grade D.")
            if reason not in explanation:
                explanation.insert(0, reason)

    confidence["current_financial_truth"] = dict(report)


def apply_usefulness_cap(confidence: MutableMapping[str, Any] | None,
                         report: Mapping[str, Any] | None) -> None:
    """Backward-compatible wrapper; new code should call ``apply_truth_caps``."""
    apply_truth_caps(confidence, report)


__all__ = [
    "CurrentFinancialTruthReport",
    "compute_final_current_financial_truth",
    "apply_final_truth_to_temporal_frame",
    "govern_current_financial_truth",
    "apply_usefulness_cap",
    "apply_truth_caps",
]
