"""
CoDIR-IA — mission_risk_gate v1.0  (v17.1 · P0-05)

Overlay de plafonnement du grade en fonction du RISQUE MISSION. Ne refond PAS le
confidence_scorer (doctrine Q5 inchangée) : il vient COIFFER son résultat, sur le
modèle exact du `BRIEF_MODE_SCORE_CAP` déjà en place.

Origine : banc d'essai Lhyfe. Un run contenant une fausse alerte juridique et un
comparatif abandonné conservait Grade B/70 — score trompeur au regard du risque
de décision. Ce gate force la dégradation.

Caps (convention identique au scorer : cap = seuil bas du grade cible) :
    Grade C max → 60   |   Grade D max → 45
"""

from __future__ import annotations

from typing import Iterable

from patches.confidence_scorer import grade_and_usage


# Drapeaux de risque mission et plafond de score associé.
MISSION_RISK_CAPS: dict[str, int] = {
    "CRITICAL_FALSE_LEGAL_ALERT":   60,   # Grade C max
    "REQUESTED_DELIVERABLE_MISSING": 60,  # Grade C max
    "REQUESTED_DELIVERABLE_UNSOURCED": 75,  # v62.13.9.4.36 — réserve de sourçage, pas livrable absent
    "HARD_METRIC_SCOPE_CONFLICT":   60,   # Grade C max
    "INTERNAL_CONTRADICTION":       60,   # F.6.7 — Grade C max (valeurs incompatibles)
}

# Si ≥ 2 drapeaux critiques distincts sont levés → Grade D max.
COMBINED_CAP = 45
COMBINED_THRESHOLD = 2

_RISK_LABELS = {
    "CRITICAL_FALSE_LEGAL_ALERT": "Fausse alerte juridique potentielle non étayée",
    "REQUESTED_DELIVERABLE_MISSING": "Demande explicite du brief non exécutée",
    "REQUESTED_DELIVERABLE_UNSOURCED": "Demande du brief exécutée mais non sourcée à l'entité",
    "HARD_METRIC_SCOPE_CONFLICT": "Conflit dur de métrique/périmètre",
    "INTERNAL_CONTRADICTION": "Contradiction interne (même entité/métrique, valeurs incompatibles)",
}


def compute_mission_cap(risk_flags: Iterable[str]) -> tuple[int | None, list[str]]:
    """Retourne (cap, flags_reconnus) le plafond le plus sévère applicable."""
    flags = [f for f in dict.fromkeys(risk_flags) if f in MISSION_RISK_CAPS]
    if not flags:
        return None, []
    if len(flags) >= COMBINED_THRESHOLD:
        return COMBINED_CAP, flags
    return min(MISSION_RISK_CAPS[f] for f in flags), flags


def apply_mission_risk_gate(scorer_result: dict, risk_flags: Iterable[str]) -> dict:
    """Coiffe le résultat du confidence_scorer en fonction des risques mission.

    Args:
        scorer_result : dict renvoyé par compute_delivery_confidence_score.
        risk_flags     : itérable de drapeaux (clés de MISSION_RISK_CAPS).

    Returns:
        Une COPIE enrichie du résultat, avec score/grade plafonnés si nécessaire
        et une entrée de trace dans 'mission_risk_gate'. Non destructif.
    """
    result = dict(scorer_result)
    cap, flags = compute_mission_cap(risk_flags)

    # Clé canonique du scorer = "score" (alias historiques tolérés).
    current = int(result.get("score",
                             result.get("delivery_confidence_score",
                                        result.get("raw_score", 0))) or 0)

    if cap is None or current <= cap:
        result["mission_risk_gate"] = {
            "applied": False,
            "flags": flags,
            "cap": cap,
            "score_before": current,
            "reason": ("Aucun risque mission critique détecté." if cap is None
                       else f"Score {current} déjà ≤ plafond mission {cap}."),
        }
        return result

    grade, label, usage = grade_and_usage(cap)
    result["score"] = cap
    if "delivery_confidence_score" in result:
        result["delivery_confidence_score"] = cap
    result["grade"] = grade
    result["usage_recommendation"] = usage
    result["mission_risk_gate"] = {
        "applied": True,
        "flags": flags,
        "flag_labels": [_RISK_LABELS.get(f, f) for f in flags],
        "cap": cap,
        "score_before": current,
        "score_after": cap,
        "delta": cap - current,
        "combined": len(flags) >= COMBINED_THRESHOLD,
        "reason": (f"Risque mission ({', '.join(flags)}) → score plafonné à "
                   f"{cap}/100 (Grade {grade}), était {current}."),
    }
    # Trace lisible dans les pénalités si la structure existe.
    pen = result.get("penalties")
    if isinstance(pen, list):
        pen = list(pen)
        pen.append({
            "code": "MISSION_RISK_CAP",
            "impact": cap - current,
            "reason": result["mission_risk_gate"]["reason"],
        })
        result["penalties"] = pen
    return result


__all__ = [
    "MISSION_RISK_CAPS", "COMBINED_CAP", "COMBINED_THRESHOLD",
    "compute_mission_cap", "apply_mission_risk_gate",
]
