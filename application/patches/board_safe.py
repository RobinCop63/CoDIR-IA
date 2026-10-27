"""
patches/board_safe.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · §8.3)

BOARD-SAFE HARD GATE — défini ICI (le contrat), ENFORCÉ en B.4a.

board_safe n'est JAMAIS un label narratif : c'est une porte dure, calculée
à partir des blockers. Sémantique B.1 (verrou ChatGPT) : B.1 POSE les
verrous — il remplit la liste ; B.4a la transforme en HARD GATE.

    board_safe_candidate = False (défaut)
    board_safe_blockers = [ perimeter_mismatch, social_aggregation_raw,
                            brief_only, period_heterogeneous, unit_uncertain,
                            transformation_undocumented, unresolved_conflict ]

Lecture B.1 des blockers (provisoire là où B.2/B.3 affineront) :
    perimeter_mismatch         : perimeter_match == MISMATCH
    social_aggregation_raw     : transformation == agrégé (somme de sociaux)
    brief_only                 : fait déclaratif sans pièce ni registre
                                 (source_type réel → B.2 ; heuristique B.1 :
                                 status HYPOTHÈSE/À VÉRIFIER sans source_doc)
    period_heterogeneous       : posé au niveau table/agrégat quand les
                                 périodes du périmètre déclaré divergent
    unit_uncertain             : valeur chiffrée dont l'unité n'a pas pu être
                                 normalisée
    transformation_undocumented: transformation renseignée hors vocabulaire
                                 (brut | recalculé | agrégé | normalisé |
                                 converti)
    unresolved_conflict        : appartient à un conflit hard/apparent
                                 non résolu (E4)

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional

BLOCKER_PERIMETER = "perimeter_mismatch"
BLOCKER_AGGREGATION = "social_aggregation_raw"
BLOCKER_BRIEF_ONLY = "brief_only"
BLOCKER_PERIOD = "period_heterogeneous"
BLOCKER_UNIT = "unit_uncertain"
BLOCKER_TRANSFO = "transformation_undocumented"
BLOCKER_CONFLICT = "unresolved_conflict"

ALL_BLOCKERS = (BLOCKER_PERIMETER, BLOCKER_AGGREGATION, BLOCKER_BRIEF_ONLY,
                BLOCKER_PERIOD, BLOCKER_UNIT, BLOCKER_TRANSFO, BLOCKER_CONFLICT)

_KNOWN_TRANSFOS = ("", "brut", "recalculé", "recalcule", "agrégé", "agrege",
                   "normalisé", "normalise", "converti")


def _status_text(f: Any) -> str:
    s = getattr(f, "status", "")
    return str(getattr(s, "value", s) or "").upper()


def _is_brief_only(f: Any) -> bool:
    # B.1.3.1 (bloquant 2 audit, REPRODUIT) — source_doc="Brief" est le cas
    # CANONIQUE du blocker brief_only : les faits extraits du brief (B.1.3)
    # portent précisément cette source. L'ancien code retournait False dès
    # qu'un source_doc existait → le blocker posé à l'extraction était
    # ensuite écrasé par annotate_board_safe, et « GBP 2.46bn | Brief »
    # ressortait FAIT sans blocker (Traçabilité 100/100).
    src = str(getattr(f, "source_doc", "") or "").strip().lower()
    if src == "brief":
        return True
    blockers = [str(b).lower()
                for b in (getattr(f, "board_safe_blockers", None) or [])]
    if "brief_only" in blockers:
        return True
    if src:
        return False
    st = _status_text(f)
    return ("HYPOTH" in st) or ("VÉRIF" in st) or ("VERIF" in st) \
        or ("NON SOURC" in st)


def _is_unit_uncertain(f: Any) -> bool:
    if getattr(f, "normalized_value", None) is None:
        # valeur non parseable mais chiffrée à l'affichage → unité incertaine
        return bool(re.search(r"\d", str(getattr(f, "value", "") or ""))) and \
            (getattr(f, "metric_canonical_id", "") not in ("", "OTHER"))
    return False


def compute_board_safe_blockers(
    fact: Any,
    *,
    unresolved_conflict: bool = False,
    period_heterogeneous: bool = False,
) -> List[str]:
    """Remplit la liste des blockers pour UN fait (B.1 pose ; B.4a enforce)."""
    blockers: List[str] = []
    if getattr(fact, "perimeter_match", "") == "MISMATCH":
        blockers.append(BLOCKER_PERIMETER)
    transfo = (getattr(fact, "transformation", "") or "").strip().lower()
    if transfo in ("agrégé", "agrege"):
        blockers.append(BLOCKER_AGGREGATION)
    elif transfo not in _KNOWN_TRANSFOS:
        blockers.append(BLOCKER_TRANSFO)
    if _is_brief_only(fact):
        blockers.append(BLOCKER_BRIEF_ONLY)
    if period_heterogeneous:
        blockers.append(BLOCKER_PERIOD)
    if _is_unit_uncertain(fact):
        blockers.append(BLOCKER_UNIT)
    if unresolved_conflict:
        blockers.append(BLOCKER_CONFLICT)
    return blockers


def annotate_board_safe(facts: Iterable[Any], conflicts=None,
                        *, period_heterogeneous: bool = False) -> None:
    """
    Pose board_safe_candidate (toujours False en B.1) + board_safe_blockers
    sur chaque fait (in place). Jamais narratif, jamais silencieux.
    """
    try:
        from patches.fact_conflict import has_unresolved_blocking_conflict
    except Exception:
        has_unresolved_blocking_conflict = lambda _c, _f: False  # noqa: E731

    for f in facts or []:
        try:
            f.board_safe_candidate = False
            # B.1.3.1 (bloquant 2 audit) — UNION, jamais remplacement : un
            # blocker posé à l'extraction (brief_only sur les faits du brief)
            # SURVIT au recalcul. « Une fois bloqué, toujours bloqué » est le
            # sens même d'une porte dure.
            _existing = set(getattr(f, "board_safe_blockers", None) or [])
            _computed = set(compute_board_safe_blockers(
                f,
                unresolved_conflict=has_unresolved_blocking_conflict(
                    conflicts or [], f),
                period_heterogeneous=period_heterogeneous,
            ))
            f.board_safe_blockers = sorted(_existing | _computed)
        except Exception:
            continue
