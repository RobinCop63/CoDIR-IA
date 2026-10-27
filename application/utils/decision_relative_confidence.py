"""Decision-relative confidence for CoDIR-IA work products (v62.3).

The historical ``confidence_score`` measures *evidence sufficiency*.  It is
kept intact because it is useful, auditable and deliberately conservative.

Terrain dossier de conseil showed that this score must not be confused with a second
question: does the output help a consultant, transition manager or SME leader
structure the issue, surface blind spots and prepare arbitrations?

This module therefore adds a **second, independent indicator**:
``decision_usefulness``.  It never adds points to, re-grades or bypasses the
proof score.  It is classified primarily from the structured agenda genre and
only falls back to the existing deterministic router when needed.

Product doctrine is explicit: CoDIR-IA produces a supervised working document,
never a final client/board deliverable.  External distribution remains ``NO``
whatever the usefulness band.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping

PROFILE_MARKET_REFLECTION = "MARKET_REFLECTION"
PROFILE_GENERAL_REFLECTION = "GENERAL_REFLECTION"
PROFILE_EVIDENCE_CRITICAL = "EVIDENCE_CRITICAL"


@dataclass(frozen=True)
class ProfileResult:
    profile: str
    agenda_genre: str
    decision_mode: str
    finance_tone: str
    source: str
    agenda_fit: int


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def classify_decision_profile(run_ctx: Mapping[str, Any] | None = None,
                              brief_text: str = "") -> ProfileResult:
    """Classify from structured agenda routing first, deterministic fallback.

    This intentionally avoids broad lexical triggers such as ``investissement``
    or ``clôture`` that previously misclassified ordinary commercial sentences.
    """
    ctx = run_ctx if isinstance(run_ctx, Mapping) else {}
    genre = _upper(ctx.get("agenda_genre"))
    mode = _upper(ctx.get("decision_mode"))
    tone = _upper(ctx.get("finance_tone"))
    source = "structured"

    if not genre:
        source = "agenda_router_fallback"
        try:
            from patches.agenda_genre import detect_agenda_genre
            routed = detect_agenda_genre(str(brief_text or ""))
            genre = _upper(getattr(routed, "genre", ""))
            mode = mode or _upper(getattr(routed, "decision_mode", ""))
            tone = tone or _upper(getattr(routed, "finance_tone", ""))
        except Exception:
            genre = "GENERIC_CODIR"
            mode = mode or "ARBITRATION"
            tone = tone or "ADVISORY"
            source = "safe_default"

    if genre in {"MARKET_STUDY", "BIZDEV_PLAN"}:
        profile = PROFILE_MARKET_REFLECTION
        fit = 90 if source == "structured" else 82
    elif genre == "GENERIC_CODIR" and mode in {"OPTIONS_PLAN", "ARBITRATION", ""} \
            and tone != "BOARD_SCRUTINY":
        profile = PROFILE_GENERAL_REFLECTION
        fit = 68 if source == "structured" else 60
    elif mode == "OPTIONS_PLAN" and tone == "ADVISORY":
        profile = PROFILE_GENERAL_REFLECTION
        fit = 75
    else:
        # M&A, closing/audit, turnaround, legal/tax and finance reviews demand
        # evidence before the output can be considered decision-useful.
        profile = PROFILE_EVIDENCE_CRITICAL
        fit = 90 if genre and genre != "GENERIC_CODIR" else 65

    return ProfileResult(
        profile=profile,
        agenda_genre=genre or "GENERIC_CODIR",
        decision_mode=mode or "ARBITRATION",
        finance_tone=tone or "ADVISORY",
        source=source,
        agenda_fit=max(0, min(100, int(fit))),
    )


def _score_band(score: int, lang: str) -> tuple[str, str]:
    en = str(lang or "fr").lower().startswith("en")
    table = [
        (85, "A", "Highly useful for supervised internal framing" if en
         else "Très utile pour le cadrage interne supervisé"),
        (70, "B", "Useful for supervised internal framing" if en
         else "Utile pour le cadrage interne supervisé"),
        (60, "C", "Usable reflection base, to be completed" if en
         else "Base de réflexion exploitable à compléter"),
        (45, "D", "Limited internal exploration" if en
         else "Exploration interne limitée"),
        (0, "E", "Insufficient even for internal framing" if en
         else "Insuffisant même pour le cadrage interne"),
    ]
    for threshold, band, label in table:
        if score >= threshold:
            return band, label
    return "E", table[-1][2]


def _usage_for_score(score: int, lang: str) -> dict[str, Any]:
    en = str(lang or "fr").lower().startswith("en")
    if score >= 70:
        consultant = leader = ("Usable under professional supervision" if en
                               else "Exploitable sous supervision professionnelle")
        code = "OK_SUPERVISED"
    elif score >= 60:
        consultant = leader = ("Limited use; complete before arbitration" if en
                               else "Usage limité ; compléter avant arbitrage")
        code = "LIMITED_SUPERVISED"
    elif score >= 45:
        consultant = leader = ("Exploratory use only" if en
                               else "Usage exploratoire uniquement")
        code = "EXPLORATORY_ONLY"
    else:
        consultant = leader = ("Not usable" if en else "Non exploitable")
        code = "NO"
    return {
        "consultant_working_document": code,
        "consultant_working_document_label": consultant,
        "sme_leader_reflection": code,
        "sme_leader_reflection_label": leader,
        "final_client_delivery": "NO_BY_DOCTRINE",
        "final_client_delivery_label": (
            "Not intended as a final client deliverable" if en
            else "Non destiné à être remis tel quel au client final"),
        "external_distribution": "NO_BY_DOCTRINE",
        "external_distribution_label": (
            "No external distribution as-is" if en
            else "Aucune diffusion externe telle quelle"),
        "human_review_required": True,
    }


def _component(cs: Mapping[str, Any], key: str, default: int = 0) -> int:
    components = cs.get("component_scores") or {}
    try:
        return max(0, min(100, int(components.get(key, default))))
    except Exception:
        return max(0, min(100, int(default)))


def _weighted_score(values: Mapping[str, int], weights: Mapping[str, float]) -> tuple[int, list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = []
    total = 0.0
    for key, weight in weights.items():
        value = max(0, min(100, int(values.get(key, 0))))
        contribution = round(value * float(weight), 2)
        total += contribution
        trace.append({
            "step": key,
            "value": value,
            "weight": float(weight),
            "contribution": contribution,
        })
    rounded = max(0, min(100, int(round(total))))
    trace.append({"step": "aggregate", "sum_weighted": round(total, 2), "rounded": rounded})
    return rounded, trace


def _profile_actions(profile: str, values: Mapping[str, int], lang: str,
                     legacy_actions: list[str] | None = None) -> list[str]:
    en = str(lang or "fr").lower().startswith("en")
    if profile == PROFILE_MARKET_REFLECTION:
        actions: list[str] = []
        if values.get("evidence_sufficiency", 0) < 60:
            actions.append("Reconcile market sources by year and perimeter." if en
                           else "Réconcilier les sources marché par année et périmètre.")
        if values.get("actionability", 0) < 80:
            actions.append("Document the company's actual positioning, references and commercial metrics." if en
                           else "Documenter le positionnement réel, les références et les métriques commerciales de l’entreprise.")
        actions.append("Validate quantified commercial and pricing assumptions before execution." if en
                       else "Valider les hypothèses commerciales et tarifaires chiffrées avant exécution.")
        return actions[:3]
    if profile == PROFILE_GENERAL_REFLECTION:
        actions = []
        if values.get("agenda_fit", 0) < 75:
            actions.append("Clarify the agenda question and expected arbitration." if en
                           else "Clarifier la question d’agenda et l’arbitrage attendu.")
        if values.get("actionability", 0) < 80:
            actions.append("Complete owners, deadlines and success indicators." if en
                           else "Compléter les porteurs, échéances et indicateurs de succès.")
        if values.get("coherence", 0) < 80:
            actions.append("Reconcile cross-functional contradictions before the next CoDIR." if en
                           else "Réconcilier les contradictions inter-directions avant le prochain CoDIR.")
        if not actions:
            actions.append("Confirm the key assumptions with the accountable manager." if en
                           else "Confirmer les hypothèses clés avec le responsable concerné.")
        return actions[:3]
    # High-stakes profile: retain the proof scorer's corrective actions.
    return [str(x) for x in (legacy_actions or [])[:3]]


def compute_decision_usefulness(confidence_score: Mapping[str, Any],
                                run_ctx: Mapping[str, Any] | None = None,
                                brief_text: str = "",
                                lang: str = "fr") -> dict[str, Any]:
    """Compute an independent usefulness indicator without changing proof score."""
    cs = confidence_score if isinstance(confidence_score, Mapping) else {}
    profile = classify_decision_profile(run_ctx, brief_text)
    evidence_score = max(0, min(100, int(cs.get("score") or 0)))
    values = {
        "agenda_fit": profile.agenda_fit,
        "actionability": _component(cs, "completeness", 0),
        "coherence": _component(cs, "consistency", 0),
        "sector_relevance": _component(cs, "sector_confidence", 0),
        "run_stability": _component(cs, "run_stability", 0),
        "content_balance": _component(cs, "content_mix", 0),
        "evidence_sufficiency": _component(cs, "source_quality", evidence_score),
    }

    if profile.profile == PROFILE_MARKET_REFLECTION:
        weights = {
            "agenda_fit": 0.15,
            "actionability": 0.25,
            "coherence": 0.20,
            "sector_relevance": 0.15,
            "run_stability": 0.10,
            "content_balance": 0.10,
            "evidence_sufficiency": 0.05,
        }
    elif profile.profile == PROFILE_GENERAL_REFLECTION:
        weights = {
            "agenda_fit": 0.15,
            "actionability": 0.25,
            "coherence": 0.25,
            "sector_relevance": 0.10,
            "run_stability": 0.10,
            "content_balance": 0.10,
            "evidence_sufficiency": 0.05,
        }
    else:
        weights = {
            "agenda_fit": 0.10,
            "actionability": 0.15,
            "coherence": 0.20,
            "sector_relevance": 0.05,
            "run_stability": 0.10,
            "content_balance": 0.10,
            "evidence_sufficiency": 0.30,
        }

    score, trace = _weighted_score(values, weights)
    caps: list[dict[str, Any]] = []
    if profile.profile == PROFILE_EVIDENCE_CRITICAL:
        cap = min(100, evidence_score + 15)
        if score > cap:
            caps.append({"code": "EVIDENCE_CRITICAL_CAP", "before": score, "after": cap})
            score = cap
    # A current-financial-truth blocker can cap usefulness without invalidating
    # the whole exploratory work product.  v62.10.2 uses this while the full
    # page-confirmed proof layer is being built in v62.11.
    try:
        _truth_cap = int(cs.get("decision_usefulness_cap"))
    except (TypeError, ValueError):
        _truth_cap = None
    if _truth_cap is not None and score > _truth_cap:
        caps.append({"code": "CURRENT_FINANCIAL_TRUTH_CAP",
                     "before": score, "after": _truth_cap})
        score = _truth_cap

    # A non-validatable run cannot be promoted by the utility indicator.
    if bool(cs.get("run_not_validatable")) or _upper(cs.get("mission_status")).startswith("NON MISSION"):
        if score > 44:
            caps.append({"code": "RUN_NOT_VALIDATABLE_CAP", "before": score, "after": 44})
            score = 44

    band, label = _score_band(score, lang)
    usage = _usage_for_score(score, lang)
    en = str(lang or "fr").lower().startswith("en")
    rationale = [
        ((f"Evidence sufficiency remains {evidence_score}/100 (Grade {cs.get('grade', '?')}); "
          "it limits assertions, not the exploratory value of the work product.") if en else
         (f"La solidité probatoire reste à {evidence_score}/100 (Grade {cs.get('grade', '?')}) ; "
          "elle limite les affirmations, pas la valeur exploratoire du document de travail.")),
        ((f"Profile {profile.agenda_genre}/{profile.decision_mode}: usefulness is calculated "
          "from framing, coherence, actionability and relevant evidence.") if en else
         (f"Profil {profile.agenda_genre}/{profile.decision_mode} : l’utilité est calculée "
          "à partir du cadrage, de la cohérence, de l’actionnabilité et des preuves pertinentes.")),
        ("This indicator never authorises external distribution as-is." if en
         else "Cet indicateur n’autorise jamais une diffusion externe telle quelle."),
    ]

    return {
        "score": score,
        "band": band,
        "label": label,
        "profile": profile.profile,
        "agenda_genre": profile.agenda_genre,
        "decision_mode": profile.decision_mode,
        "finance_tone": profile.finance_tone,
        "classification_source": profile.source,
        "component_scores": values,
        "weights": dict(weights),
        "calculation_trace": trace,
        "caps": caps,
        "rationale": rationale,
        "usage": usage,
        "next_best_actions": _profile_actions(
            profile.profile, values, lang,
            legacy_actions=list(cs.get("next_best_actions") or [])),
        "evidence_score": evidence_score,
        "evidence_grade": str(cs.get("grade") or "?"),
        "proof_score_unchanged": True,
    }


def attach_decision_usefulness(confidence_score: MutableMapping[str, Any] | None,
                               run_ctx: Mapping[str, Any] | None = None,
                               brief_text: str = "",
                               lang: str = "fr") -> MutableMapping[str, Any] | None:
    """Attach the second indicator in place; the historical score is untouched."""
    if not isinstance(confidence_score, MutableMapping):
        return confidence_score
    try:
        # Snapshot of the proof score for explicit dual-read semantics.
        confidence_score["evidence_confidence"] = {
            "score": confidence_score.get("score"),
            "grade": confidence_score.get("grade"),
            "label": confidence_score.get("label"),
            "usage_recommendation": dict(confidence_score.get("usage_recommendation") or {}),
        }
        usefulness = compute_decision_usefulness(
            confidence_score, run_ctx=run_ctx, brief_text=brief_text, lang=lang)
        confidence_score["decision_usefulness"] = usefulness
        confidence_score["decision_profile"] = usefulness.get("profile")
        confidence_score["doctrine_usage"] = usefulness.get("usage")
        confidence_score["doctrine_label"] = usefulness.get("label")
    except Exception as exc:  # fail-open: never break a run for a secondary score
        confidence_score["decision_usefulness_error"] = f"{type(exc).__name__}:{exc}"
    return confidence_score


__all__ = [
    "PROFILE_MARKET_REFLECTION",
    "PROFILE_GENERAL_REFLECTION",
    "PROFILE_EVIDENCE_CRITICAL",
    "ProfileResult",
    "classify_decision_profile",
    "compute_decision_usefulness",
    "attach_decision_usefulness",
]
