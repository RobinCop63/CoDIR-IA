"""
CoDIR-IA — scope_math_validator v1.0  (v17.1 · P0-02)

Garde-fou « Scope before math » : interdit toute opération arithmétique entre
deux faits de PÉRIMÈTRES incompatibles (social standalone vs consolidé, segment,
marché, estimé…), d'entités différentes, de devises différentes ou de périodes
incompatibles.

Origine : banc d'essai Lhyfe (run 2, 2026-06-04). L'agent Finance a calculé
    capitaux_propres_2024 (SOCIAL_STANDALONE, −20 k€)  −  resultat_net_2025 (CONSOLIDATED, −51 M€)
    = capitaux_propres_2025 « −51,02 M€ »
puis en a tiré une (fausse) alerte juridique L.225-248. Le défaut n'est pas le
roll-forward equity = equity_{N-1} + RN_N (légitime À MÊME PÉRIMÈTRE), mais le
mélange standalone × consolidé.

Module PUR : aucun effet de bord, aucun I/O, testable sans mock.
"""

from __future__ import annotations

from typing import Iterable


# =============================================================================
# Référentiel de périmètres (cohérent avec le modèle de fait Couche 1, v17.1 §4)
# =============================================================================

SCOPES = {
    "CONSOLIDATED",
    "SOCIAL_STANDALONE",
    "SEGMENT",
    "PROJECT",
    "MARKET",
    "ESTIMATE",
    "UNKNOWN",
}

# Périmètres « durs » : seuls compatibles entre eux pour un calcul comptable.
# UNKNOWN / ESTIMATE / MARKET ne sont jamais combinables en arithmétique dure.
HARD_SCOPES = {"CONSOLIDATED", "SOCIAL_STANDALONE", "SEGMENT", "PROJECT"}

# Statut de traitement (enum SÉPARÉ de la doctrine Q2 de fiabilité — ne pas mélanger)
STATUS_OK = "OK"
STATUS_INVALID_SCOPE = "INVALIDE_PERIMETRE"


# =============================================================================
# Helpers
# =============================================================================

def _get(fact: dict, key: str, default=None):
    if not isinstance(fact, dict):
        return default
    return fact.get(key, default)


def _norm_period(fact: dict) -> str | None:
    """Clé de période comparable (priorité period_end, sinon as_of_date)."""
    return _get(fact, "period_end") or _get(fact, "as_of_date")


def scopes_compatible(scope_a: str | None, scope_b: str | None) -> bool:
    """Deux périmètres sont compatibles pour un calcul dur s'ils sont identiques
    ET appartiennent aux périmètres durs. Tout UNKNOWN/ESTIMATE/MARKET → incompatible."""
    if scope_a is None or scope_b is None:
        return False
    if scope_a not in HARD_SCOPES or scope_b not in HARD_SCOPES:
        return False
    return scope_a == scope_b


# =============================================================================
# API principale
# =============================================================================

def validate_scope_math(operands: Iterable[dict],
                        operation: str = "subtract") -> dict:
    """Valide une opération arithmétique entre plusieurs faits.

    Args:
        operands : liste de dicts-faits portant au minimum `scope`, et idéalement
                   `entity_id`, `metric_name`, `currency`/`unit`, `period_end`.
        operation : libellé indicatif ('add', 'subtract', 'ratio', …).

    Returns:
        dict {
            'valid': bool,
            'status': 'OK' | 'INVALIDE_PERIMETRE',
            'reason': str,
            'scopes': [...],
            'operation': str,
        }
    """
    ops = [o for o in operands if isinstance(o, dict)]
    if len(ops) < 2:
        # Un seul opérande : rien à combiner, trivialement valide.
        return {
            "valid": True,
            "status": STATUS_OK,
            "reason": "Opérande unique — aucune combinaison inter-périmètres.",
            "scopes": [_get(o, "scope") for o in ops],
            "operation": operation,
        }

    scopes = [_get(o, "scope") for o in ops]
    entities = {_get(o, "entity_id") for o in ops if _get(o, "entity_id") is not None}
    currencies = {(_get(o, "currency") or _get(o, "unit")) for o in ops
                  if (_get(o, "currency") or _get(o, "unit")) is not None}

    # 1) Périmètres incompatibles (le cas Lhyfe)
    ref = scopes[0]
    for s in scopes[1:]:
        if not scopes_compatible(ref, s):
            return {
                "valid": False,
                "status": STATUS_INVALID_SCOPE,
                "reason": (f"Calcul inter-périmètres interdit : "
                           f"{ref} × {s}. Les agrégats de périmètres différents "
                           f"(ex. social standalone vs consolidé) ne sont pas combinables."),
                "scopes": scopes,
                "operation": operation,
            }

    # 2) Entités différentes
    if len(entities) > 1:
        return {
            "valid": False,
            "status": STATUS_INVALID_SCOPE,
            "reason": f"Calcul entre entités différentes : {sorted(entities)}.",
            "scopes": scopes,
            "operation": operation,
        }

    # 3) Devises différentes
    if len(currencies) > 1:
        return {
            "valid": False,
            "status": STATUS_INVALID_SCOPE,
            "reason": f"Calcul entre devises différentes : {sorted(currencies)}.",
            "scopes": scopes,
            "operation": operation,
        }

    return {
        "valid": True,
        "status": STATUS_OK,
        "reason": f"Périmètre homogène ({ref}), même entité/devise — calcul autorisé.",
        "scopes": scopes,
        "operation": operation,
    }


def filter_valid_calculations(calculations: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Sépare une liste de calculs proposés en (valides, rejetés).

    Chaque calcul est un dict {'label': str, 'operands': [faits], 'operation': str}.
    Les rejetés portent leur diagnostic dans la clé 'scope_check'.
    """
    kept, dropped = [], []
    for calc in calculations:
        operands = _get(calc, "operands", []) or []
        res = validate_scope_math(operands, _get(calc, "operation", "subtract"))
        enriched = dict(calc)
        enriched["scope_check"] = res
        if res["valid"]:
            kept.append(enriched)
        else:
            dropped.append(enriched)
    return kept, dropped


__all__ = [
    "SCOPES", "HARD_SCOPES",
    "STATUS_OK", "STATUS_INVALID_SCOPE",
    "scopes_compatible",
    "validate_scope_math",
    "filter_valid_calculations",
]
