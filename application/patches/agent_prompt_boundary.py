# -*- coding: utf-8 -*-
"""Temporal Core Refactor — frontière des payloads agents.

Correctif TCR (audit 26/07/2026) : l'état de la frontière est un
``contextvars.ContextVar`` — ISOLÉ PAR SESSION/THREAD/TÂCHE, plus
jamais une variable globale de processus. Une session live ne peut pas
rendre permissive la frontière d'une session bloquée (et
réciproquement) ; l'ordre d'exécution des sessions ne porte aucune
vérité temporelle.

Défense en profondeur derrière l'early-return du moteur : AUCUN
payload agent (system OU user) ne peut être assemblé ni transmis sous
une policy bloquée, même par un chemin de code qui raterait
l'early-return.
"""
from __future__ import annotations

import contextvars

from patches import temporal_policy as _tp

_OPEN_MODES = (_tp.MODE_LIVE, _tp.MODE_RETRO, _tp.MODE_FUTURE)

# Correctif TCR — état PAR CONTEXTE (session Streamlit, thread, tâche),
# jamais partagé entre sessions. default=None = hors contexte moteur.
_POLICY_VAR: contextvars.ContextVar = contextvars.ContextVar(
    "codir_temporal_policy", default=None)


def set_current_policy(policy):
    """Posé par le moteur à CHAQUE résolution (une fois par run) et
    remis à None en ``finally`` par le wrapper du run — aucun résidu
    ne survit au run, même sur exception. Retourne le token
    contextvars (restaurable via reset_policy_token)."""
    return _POLICY_VAR.set(policy)


def reset_policy_token(token) -> None:
    """Restaure l'état antérieur exact (token de set_current_policy)."""
    try:
        _POLICY_VAR.reset(token)
    except Exception:
        _POLICY_VAR.set(None)


def get_current_policy():
    return _POLICY_VAR.get()


class TemporalBoundaryViolation(RuntimeError):
    """Tentative d'assemblage/envoi d'un payload agent sous policy
    bloquée — bug de câblage, jamais un état métier."""


def is_open(policy) -> bool:
    try:
        return getattr(policy, "mode", None) in _OPEN_MODES
    except Exception:
        return False


def ensure_agent_payload_allowed(policy=None, tag: str = "") -> None:
    """À appeler AVANT toute construction/transmission de payload
    agent. policy=None → consulte la policy du CONTEXTE COURANT ; si
    aucune n'est posée, la garde ne s'arme pas (hors contexte moteur —
    le flux run est déjà couvert par l'early-return, ceci est la 2e
    couche). Avec une policy explicite : fail-closed."""
    if policy is None:
        policy = _POLICY_VAR.get()
        if policy is None:
            return
    if not is_open(policy):
        mode = getattr(policy, "mode", "<no-policy>")
        raise TemporalBoundaryViolation(
            f"agent payload forbidden under temporal policy "
            f"{mode!r} (tag={tag or '?'})")
