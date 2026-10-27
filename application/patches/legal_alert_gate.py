"""
CoDIR-IA — legal_alert_gate v1.0  (v17.1 · P0-03)

Garde-fou « Legal claims are gated » : aucune alerte juridique forte ne peut être
émise sans un socle de preuves minimal, à la bonne métrique et au bon périmètre.

Cas cible (Lhyfe run 2) : émission d'une alerte « CAPITAUX PROPRES NÉGATIFS —
RISQUE JURIDIQUE IMMÉDIAT / art. L.225-248 » + « augmentation de capital urgente »,
construite sur une perte CONSOLIDÉE et un chiffre Pappers standalone mal typé.

Rappel L.225-248 (SA) : l'obligation (AGE sous 4 mois, reconstitution sous 2 ans)
se déclenche lorsque, du fait de pertes constatées dans les DOCUMENTS COMPTABLES
de la société, les CAPITAUX PROPRES (sociaux, pas consolidés) deviennent
inférieurs à la MOITIÉ DU CAPITAL SOCIAL. Donc : il faut les capitaux propres
sociaux ET le capital social, sourcés — pas un calcul libre.

Module PUR : aucun effet de bord, aucun I/O.
"""

from __future__ import annotations

import re
from typing import Iterable


# Tag de fiabilité minimal exigé pour un input d'alerte juridique forte.
_TRUSTED_TAGS = {"FAIT"}

# Exigences de preuve par type d'alerte juridique forte.
LEGAL_ALERT_REQUIREMENTS: dict[str, dict] = {
    "L225-248": {
        "label": "Perte de la moitié du capital social (art. L.225-248 C. com., SA)",
        "required_facts": [
            "capitaux_propres_sociaux",   # scope SOCIAL_STANDALONE, tag FAIT
            "capital_social",             # tag FAIT
        ],
        "required_context": [
            "comptes_approuves_status",   # comptes approuvés / date d'approbation
            "legal_form",                 # forme juridique (SA/SAS…)
        ],
        # Périmètre EXIGÉ pour les capitaux propres : société, jamais consolidé.
        "equity_scope_required": "SOCIAL_STANDALONE",
    },
}

# Vocabulaire d'alerte forte banni hors gate validé (insensible à la casse).
_BANNED_PATTERNS = [
    r"risque\s+juridique\s+imm[ée]diat",
    r"augmentation\s+de\s+capital\s+urgente",
    r"dissolution\s+(?:potentielle|imm[ée]diate|de\s+la\s+soci[ée]t[ée])",
    r"cessation\s+de\s+paiements?",
    r"capitaux\s+propres\s+n[ée]gatifs",   # affirmation brute interdite hors gate
    r"d[ée]p[ôo]t\s+de\s+bilan",
]

NEUTRAL_REPLACEMENT = (
    "[POINT JURIDIQUE À VÉRIFIER : nécessite capitaux propres sociaux et capital "
    "social sourcés avant toute conclusion]"
)


def _fact_ok(fact: dict | None, *, scope_required: str | None = None) -> bool:
    """Un fait est exploitable pour une alerte forte s'il est tagué FAIT et,
    si un périmètre est exigé, au bon périmètre."""
    if not isinstance(fact, dict):
        return False
    if fact.get("tag") not in _TRUSTED_TAGS:
        return False
    if scope_required is not None and fact.get("scope") != scope_required:
        return False
    return fact.get("value") is not None


def evaluate_legal_alert(alert_type: str, evidence: dict) -> dict:
    """Décide si une alerte juridique forte peut être émise.

    Args:
        alert_type : clé de LEGAL_ALERT_REQUIREMENTS (ex. 'L225-248').
        evidence   : dict pouvant contenir des faits-dicts sous les clés
                     'capitaux_propres_sociaux', 'capital_social', et des
                     contextes 'comptes_approuves_status', 'legal_form',
                     'primary_source'.

    Returns:
        dict {
            'emit': bool,              # True ⇒ alerte forte autorisée
            'downgraded': bool,        # True ⇒ remplacée par « à vérifier »
            'alert_type': str,
            'missing': [str, ...],
            'message': str,            # message à utiliser dans le livrable
        }
    """
    spec = LEGAL_ALERT_REQUIREMENTS.get(alert_type)
    if spec is None:
        return {
            "emit": False, "downgraded": True, "alert_type": alert_type,
            "missing": ["alert_type_inconnu"],
            "message": NEUTRAL_REPLACEMENT,
        }

    missing: list[str] = []

    # Faits requis (avec contrôle de périmètre pour les capitaux propres)
    for fname in spec["required_facts"]:
        scope_req = spec.get("equity_scope_required") if fname == "capitaux_propres_sociaux" else None
        if not _fact_ok(evidence.get(fname), scope_required=scope_req):
            missing.append(fname)

    # Contexte requis
    for cname in spec["required_context"]:
        if not evidence.get(cname):
            missing.append(cname)

    # Source primaire exigée
    if not evidence.get("primary_source"):
        missing.append("primary_source")

    if missing:
        return {
            "emit": False, "downgraded": True, "alert_type": alert_type,
            "missing": missing,
            "message": (f"{NEUTRAL_REPLACEMENT} — éléments manquants : "
                        f"{', '.join(missing)}."),
        }

    return {
        "emit": True, "downgraded": False, "alert_type": alert_type,
        "missing": [],
        "message": (f"Alerte {spec['label']} : conditions de preuve réunies "
                    f"(capitaux propres sociaux + capital social sourcés)."),
    }


def scrub_unauthorized_legal_language(text: str, gate_passed: bool) -> tuple[str, list[str]]:
    """Neutralise le vocabulaire d'alerte forte dans un texte agent si le gate
    n'est pas validé. Retourne (texte_nettoyé, expressions_retirées)."""
    if gate_passed or not text:
        return text, []
    removed: list[str] = []
    cleaned = text
    for pat in _BANNED_PATTERNS:
        rx = re.compile(pat, flags=re.IGNORECASE)
        found = rx.findall(cleaned)
        if found:
            removed.extend(m if isinstance(m, str) else " ".join(m) for m in found)
            cleaned = rx.sub(NEUTRAL_REPLACEMENT, cleaned)
    return cleaned, removed


__all__ = [
    "LEGAL_ALERT_REQUIREMENTS",
    "NEUTRAL_REPLACEMENT",
    "evaluate_legal_alert",
    "scrub_unauthorized_legal_language",
]
