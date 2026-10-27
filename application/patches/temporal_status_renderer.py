# -*- coding: utf-8 -*-
"""Temporal Core Refactor — rendu UNIQUE du statut temporel.

Toutes les surfaces (UI Streamlit, Pilot, DOCX, PPTX) consomment CE
module : une seule source de vérité pour le badge, le message et les
capacités affichées. Aucune surface ne re-décide un libellé temporel.
"""
from __future__ import annotations

from patches import temporal_policy as _tp

_BADGE = {
    _tp.MODE_LIVE: "",
    _tp.MODE_RETRO: "🔒",
    _tp.MODE_FUTURE: "🔒",
    _tp.MODE_BLOCKED_INVALID: "⛔",
    _tp.MODE_BLOCKED_CONFLICT: "⛔",
    _tp.MODE_BLOCKED_ERROR: "⛔",
    _tp.MODE_BLOCKED_AMBIGUOUS: "⛔",
}


def temporal_status(obj, lang: str = "fr") -> dict:
    """obj = TemporalExecutionPolicy OU result dict (route alors par
    policy_for_view, donc hérite du cross-check fail-closed v5)."""
    pol = (obj if isinstance(obj, _tp.TemporalExecutionPolicy)
           else _tp.policy_for_view(obj))
    msg = pol.user_message_fr if lang == "fr" else pol.user_message_en
    blocked = pol.mode not in (_tp.MODE_LIVE, _tp.MODE_RETRO,
                               _tp.MODE_FUTURE)
    return {
        "mode": pol.mode,
        "badge": _BADGE.get(pol.mode, "⛔"),
        "message": msg,
        "is_blocked": blocked,
        "is_read_only": not pol.can_mutate_from_pilot,
        "analysis_date": pol.analysis_date or None,
        "run_date": pol.run_date or None,
    }
