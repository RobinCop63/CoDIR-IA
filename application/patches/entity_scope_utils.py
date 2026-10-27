"""patches/entity_scope_utils.py — v17.4.3.6-M6B-B1.3.6 (module PUR).

Run dossier anglophone coté B.1.3.5 : la note « entité LIÉE » existait au CR mais ni les
LIGNES de métadonnées ni le DECK ne portaient la réserve — le CR disait
« attention, lié », le PPT disait « fait ». Ce helper centralise le test
registre≠analyse pour les DEUX writers (docx + deck), même vocabulaire.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple


def _toks(s: str) -> set:
    return {t for t in re.split(r"[^A-Za-z0-9]+", (s or "").upper()) if len(t) >= 3}


def registry_related(entity_scope: dict | None) -> Optional[Tuple[str, str]]:
    """(registry, analysis) si l'entité registre est une entité LIÉE
    (ensembles de tokens différents), None sinon. « dossier anglophone coté LIMITED » vs
    « dossier anglophone coté Group plc » → liée ; « dossier industriel (composants) » vs « dossier industriel (composants) » → None."""
    es = entity_scope or {}
    an = str(es.get("analysis_entity") or "").strip()
    rg = str(es.get("registry_entity") or "").strip()
    if not (an and rg):
        return None
    if rg.upper() == an.upper() or _toks(rg) == _toks(an):
        return None
    return (rg, an)
