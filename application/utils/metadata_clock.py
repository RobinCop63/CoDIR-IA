"""Gate 12 — helpers de MÉTADONNÉES d'édition.

Seul module autorisé à lire l'horloge système pour les besoins d'ÉDITION :
date affichée en en-tête de document, horodatage des noms de fichiers.
Ces valeurs ne participent JAMAIS à la vérité du dossier (statuts,
échéances, retards) — l'autorité temporelle de vérité vit dans le résultat
de session (temporal_authority). Le contrat AST interdit toute horloge
ailleurs sur les chemins de vérité.
"""
from datetime import datetime


def edition_datetime_str(fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Date/heure d'ÉDITION du document (métadonnée d'affichage)."""
    return datetime.now().strftime(fmt)


def file_timestamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Horodatage pour NOMS de fichiers exportés (métadonnée)."""
    return datetime.now().strftime(fmt)


def event_timestamp() -> str:
    """Horodatage REEL d ecriture d un evenement de journal (audit trail).

    Traçabilité d ecriture, jamais une autorité de raisonnement : c est
    précisément la séparation ts (réel) / analysis_date (autorité) qui a
    permis de prouver le P0 du gate 12.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def run_now():
    """Capture UNIQUE de la date/heure REELLE d une session (tz-aware UTC).

    Seul point de capture autorise pour la date reelle du run : le moteur
    l importe ; aucun module de verite ne lit l horloge directement
    (contrat AST v3). La valeur sert la traçabilite (run_date, seed diag),
    JAMAIS un jugement — l autorite de raisonnement vit dans
    temporal_authority.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
