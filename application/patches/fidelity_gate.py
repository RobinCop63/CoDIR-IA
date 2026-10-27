"""patches/fidelity_gate.py — v17.4.3.6-M6B-B1.3.6 : pont SQ ↔ fidélité-page.

Audit terrain dossier anglophone coté B.1.3.5 : 18 pièces jointes, sonde amont
source_quality=60 / signal 80, score 62 Grade C — pendant que la couche 1
aval affichait DEGRADED, 0/8 fait confirmé à la page citée. Deux mesures
jamais réconciliées : le score montait sur du « signal détecté », pas sur
du « fait exploitable ».

Ce module PUR applique un CAP post-scorer (même mécanique que le language
gate) : des pièces jointes SANS AUCUN fait confirmé à la page citée ne
peuvent pas porter un run au-dessus de Grade D. Le cap est visible,
motivé, traçable — jamais silencieux.
"""
from __future__ import annotations

from typing import Any, Dict

_GRADE_ORDER = ["A", "B", "C", "D", "E"]
CAP_GRADE = "D"
CAP_SCORE = 55


def evaluate(n_attachments: int, n_pj_facts: int,
             n_confirmed_on_page: int, lang: str = "fr") -> Dict[str, Any]:
    """True si des PJ existent, des faits en sont extraits, et AUCUN n'est
    confirmé à la page citée."""
    triggered = bool(n_attachments and n_pj_facts and not n_confirmed_on_page)
    if not triggered:
        return {"triggered": False, "target_lang": lang}
    reason = ((f"{n_pj_facts} fait(s) extrait(s) des pièces, 0 confirmé à la "
               f"page citée — signal détecté ≠ fait exploitable : la qualité "
               f"de source ne peut pas porter le score.")
              if lang == "fr" else
              (f"{n_pj_facts} fact(s) extracted from attachments, 0 confirmed "
               f"on cited page — detected signal ≠ exploitable fact: source "
               f"quality cannot carry the score."))
    return {"triggered": True, "reason": reason, "target_lang": lang,
            "n_attachments": int(n_attachments), "n_pj_facts": int(n_pj_facts),
            "n_confirmed_on_page": int(n_confirmed_on_page)}


def apply_fidelity_gate(score_result: dict, *, n_attachments: int,
                        n_pj_facts: int, n_confirmed_on_page: int,
                        lang: str = "fr") -> Dict[str, Any]:
    """Cappe score/grade dans score_result (muté) et pose
    score_result['fidelity_gate'] = info. Retourne info.

    B.1.3.6-HYBRID : idempotent. Le gate peut tourner tôt (avant DOCX/PPTX)
    puis être rappelé plus tard par l'ancien câblage UI ; le second appel ne
    doit pas réécrire raw_score/raw_grade ni dupliquer les diagnostics.
    """
    if isinstance(score_result, dict):
        existing = score_result.get("fidelity_gate")
        if isinstance(existing, dict) and existing.get("triggered"):
            # B.1.3.8 — marqueur pour que le câblage tardif SKIPPE son diag
            # (le run 3.7 loggait DEUX rows fidelity_gate pour un seul cap).
            out = dict(existing)
            out["already_applied"] = True  # B.1.3.10 — le câblage tardif
            # journalise SKIPPED_IDEMPOTENT au lieu d'une 2e row CAPPED.
            out["idempotent_skip"] = True
            return out
    info = evaluate(n_attachments, n_pj_facts, n_confirmed_on_page, lang=lang)
    if not info.get("triggered") or not isinstance(score_result, dict):
        return info
    raw_score = score_result.get("score")
    raw_grade = str(score_result.get("grade") or "")
    info["raw_score"] = raw_score
    info["raw_grade"] = raw_grade
    info["pre_fidelity_score"] = raw_score
    info["fidelity_cap_score"] = CAP_SCORE
    score_result["pre_fidelity_score"] = raw_score
    try:
        if raw_score is not None and float(raw_score) > CAP_SCORE:
            score_result["score"] = CAP_SCORE
    except Exception:
        pass
    if raw_grade in _GRADE_ORDER and _GRADE_ORDER.index(raw_grade) < _GRADE_ORDER.index(CAP_GRADE):
        score_result["grade"] = CAP_GRADE
    info["capped_grade"] = score_result.get("grade")
    info["capped_score"] = score_result.get("score")
    score_result["final_evidence_score"] = score_result.get("score")
    score_result["fidelity_cap_score"] = CAP_SCORE
    score_result["fidelity_gate"] = info
    return info


def sync_confidence_diagnostics(diagnostics: list | None, score_result: dict | None) -> int:
    """Aligne les lignes CSV/diagnostic sur le score FINAL exposé.

    Le score brut reste disponible séparément ; aucune surface ne doit appeler
    le score pré-cap « score » après application du fidelity gate.
    """
    if not isinstance(diagnostics, list) or not isinstance(score_result, dict):
        return 0
    final_score = score_result.get("score")
    final_grade = score_result.get("grade")
    fg = score_result.get("fidelity_gate") or {}
    raw_score = fg.get("raw_score", score_result.get("raw_score"))
    raw_grade = fg.get("raw_grade")
    n = 0
    for row in diagnostics:
        if not isinstance(row, dict):
            continue
        if row.get("role") == "confidence_score":
            row["raw_score"] = raw_score
            row["raw_grade"] = raw_grade
            row["pre_cap_weighted_score"] = score_result.get("pre_cap_weighted_score")
            row["post_brief_mode_cap_score"] = score_result.get("post_brief_mode_cap_score")
            row["post_structured_evidence_cap_score"] = score_result.get("post_structured_evidence_cap_score")
            row["pre_fidelity_score"] = score_result.get("pre_fidelity_score", raw_score)
            row["fidelity_cap_score"] = score_result.get("fidelity_cap_score")
            row["final_evidence_score"] = final_score
            row["score"] = final_score
            row["final_score"] = final_score
            row["final_grade"] = final_grade
            row["cap_reason"] = "fidelity_gate" if fg.get("triggered") else ""
            n += 1
        elif row.get("role") == "decision_usefulness":
            row["evidence_score"] = final_score
            n += 1
    return n
