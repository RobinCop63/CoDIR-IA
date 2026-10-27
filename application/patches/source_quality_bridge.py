"""patches/source_quality_bridge.py — v17.4.3.6-M6B-B1.3.6 (module PUR).

Run dossier anglophone coté 3.5 (18 PJ) : la sonde a1 amont posait source_quality=60
(signal 80) pendant que la Couche 1 aval disait DEGRADED, 0/8 fait confirmé
à la page citée — deux mesures jamais réconciliées, score C « trop facile ».
Doctrine : « signal DÉTECTÉ ≠ fait EXPLOITABLE ». Ce pont plafonne SQ quand
la fidélité-page est nulle sur une table dégradée.
"""
from __future__ import annotations

from typing import Optional, Tuple

SQ_CAP_NO_PAGE_FIDELITY = 40


def cap_source_quality(sq: Optional[float],
                       n_page_confirmed: Optional[int],
                       n_facts_checked: Optional[int],
                       table_status: str = "") -> Tuple[Optional[float], Optional[str]]:
    """(sq_plafonné, raison|None). Plafonne à 40 si : SQ>40, ≥1 fait vérifié,
    0 confirmé à la page, et statut Couche 1 dégradé/échec. Fail-open : toute
    donnée manquante ⇒ pas de cap (on ne pénalise pas sans preuve)."""
    try:
        if sq is None or float(sq) <= SQ_CAP_NO_PAGE_FIDELITY:
            return sq, None
        if not n_facts_checked or (n_page_confirmed or 0) > 0:
            return sq, None
        if str(table_status or "").upper() not in ("DEGRADED", "FAILED", "WEAK"):
            return sq, None
        return float(SQ_CAP_NO_PAGE_FIDELITY), (
            f"PAGE_FIDELITY_ZERO: sq {sq}→{SQ_CAP_NO_PAGE_FIDELITY} "
            f"(0/{n_facts_checked} fait(s) confirmé(s) à la page citée, "
            f"couche 1 {table_status})")
    except Exception:
        return sq, None
