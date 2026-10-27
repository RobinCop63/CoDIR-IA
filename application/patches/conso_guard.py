"""
patches/conso_guard.py — v17.4.0-M6B-B1.0 (M6-B · B.1 · E5)

GARDE D'HONNÊTETÉ CONSOLIDATION (D4 — NON NÉGOCIABLE ; note M6-B v3 §4.2,
§7 Partie II).

À graver : UNE SOMME DE COMPTES SOCIAUX N'EST PAS UN COMPTE CONSOLIDÉ
(manquent : éliminations intra-groupe, intérêts minoritaires,
homogénéisation, périmètre). Toute agrégation se fait SOUS RÉSERVE
EXPLICITE, porte transformation=agrégé, ne pose JAMAIS
financial_signal_solid=True et ne devient JAMAIS board_safe.

La consolidation multi-entités n'est pas « standalone = mauvais » : c'est
un cas de PREMIÈRE CLASSE. Le compte social d'une entité déclarée est une
brique LÉGITIME : tagué par entité, agrégeable sous réserve, comptant pour
la COUVERTURE — jamais comme preuve du groupe.

La matrice de couverture complète (présence × homogénéité × normalisation ×
réserve) est SCORÉE en B.3/B.4a ; B.1 en pose la donnée brute
(coverage_map : métrique → entités couvertes / déclarées).

100 % déterministe, sans dépendance pipeline → testable en isolation.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from patches.analysis_context import AnalysisContext, MODE_CONSO

# ── L'étiquette obligatoire (wording EXACT du contrat, §7 Partie II) ──────────
CONSO_RESERVE_LABEL_FR = (
    "Somme brute des comptes sociaux — hors retraitements de consolidation "
    "(intercos, intérêts minoritaires, périmètre). Indicatif, NON board-safe, "
    "≠ comptes consolidés."
)
CONSO_RESERVE_LABEL_EN = (
    "Raw sum of statutory (standalone) accounts — excluding consolidation "
    "adjustments (intercompany eliminations, minority interests, scope). "
    "Indicative, NOT board-safe, ≠ consolidated accounts."
)


def reserve_label(lang: str = "fr") -> str:
    return CONSO_RESERVE_LABEL_EN if (lang or "fr").lower().startswith("en") \
        else CONSO_RESERVE_LABEL_FR


def is_aggregation(fact: Any) -> bool:
    return (getattr(fact, "transformation", "") or "") == "agrégé"


def guard_aggregated_fact(fact: Any, *, lang: str = "fr") -> None:
    """
    Applique la garde D4 à un fait agrégé (in place) :
      · étiquette de réserve OBLIGATOIRE dans les notes ;
      · board_safe_candidate=False + blocker social_aggregation_raw ;
      · le fait ne pourra JAMAIS soutenir financial_signal_solid
        (transformation=agrégé est exclu par gate_financial_signal, E3).
    Ne lève jamais.
    """
    try:
        label = reserve_label(lang)
        notes = list(getattr(fact, "notes", []) or [])
        if label not in notes:
            notes.append(label)
        fact.notes = notes
        fact.transformation = "agrégé"
        fact.board_safe_candidate = False
        blockers = list(getattr(fact, "board_safe_blockers", []) or [])
        if "social_aggregation_raw" not in blockers:
            blockers.append("social_aggregation_raw")
        fact.board_safe_blockers = blockers
    except Exception:
        pass


def aggregate_declared_entities(
    facts: Iterable[Any],
    ctx: AnalysisContext,
    *,
    metric_canonical_id: str,
    lang: str = "fr",
) -> Optional[Dict[str, Any]]:
    """
    Agrégation SOUS RÉSERVE des faits COVERAGE d'une métrique, en mode
    consolidation. Retourne un dict décrivant l'agrégat (le wiring moteur en
    fait un FinancialFact) ou None si < 2 briques sommables homogènes.

    Refuse (None) si : mode ≠ consolidation ; unités hétérogènes ; devises
    hétérogènes — l'honnêteté avant le chiffre.
    """
    if ctx.mode != MODE_CONSO:
        return None
    bricks: List[Any] = []
    for f in facts or []:
        if getattr(f, "metric_canonical_id", "") != metric_canonical_id:
            continue
        if getattr(f, "perimeter_match", "") != "COVERAGE":
            continue
        if getattr(f, "normalized_value", None) is None:
            continue
        if is_aggregation(f):
            continue
        bricks.append(f)
    if len(bricks) < 2:
        return None

    units = {getattr(b, "unit", "") or "" for b in bricks}
    curs = {getattr(b, "currency", "") or "" for b in bricks}
    if len(units) > 1 or len(curs) > 1:
        return None

    total = sum(float(b.normalized_value) for b in bricks)
    periods = {getattr(b, "period", "") or "" for b in bricks}
    nonempty_periods = {p for p in periods if p}
    period_heterogeneous = len(nonempty_periods) > 1
    # B.1.1 — période COMMUNE de l'agrégat : posée seulement si toutes les
    # briques datées portent la même ; sinon "" (l'hétérogénéité est déjà
    # tracée par le blocker period_heterogeneous).
    common_period = nonempty_periods.pop() if len(nonempty_periods) == 1 else ""

    return {
        "metric_canonical_id": metric_canonical_id,
        "normalized_value": total,
        "unit": units.pop() if units else "",
        "currency": curs.pop() if curs else "",
        "n_entities": len(bricks),
        "entities": [getattr(b, "perimeter_entity", "") or "?" for b in bricks],
        "period": common_period,
        "period_heterogeneous": period_heterogeneous,
        # B.1.1 — identité des constituants : permet une fact_instance_id
        # d'agrégat déterministe (même somme des mêmes briques entre deux
        # runs → même instance ; une brique change → instance différente).
        "constituent_keys": sorted(
            (getattr(b, "stable_fact_key", "") or "") for b in bricks),
        "transformation": "agrégé",
        "reserve_label": reserve_label(lang),
        "board_safe_candidate": False,
        "board_safe_blockers": (["social_aggregation_raw"]
                                + (["period_heterogeneous"] if period_heterogeneous else [])),
    }


def coverage_map(facts: Iterable[Any], ctx: AnalysisContext) -> Dict[str, Dict[str, Any]]:
    """
    Donnée brute de la matrice de couverture (§9.1) : par métrique attendue,
    quelles entités déclarées sont couvertes par au moins un fait COVERAGE.
    Le SCORE de couverture arrive en B.3/B.4a — ici, la présence seulement.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if ctx.mode != MODE_CONSO or not ctx.declared_entities:
        return out
    try:
        from patches.perimeter_match import entity_match_status, \
            ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS, ENTITY_SAME_GROUP
        ok_status = (ENTITY_EXACT_ID, ENTITY_EXACT_NAME, ENTITY_ALIAS,
                     ENTITY_SAME_GROUP)
    except Exception:
        ok_status = None

    for metric in ctx.expected_metrics or []:
        covered: List[str] = []
        for decl in ctx.declared_entities:
            hit = False
            for f in facts or []:
                if getattr(f, "metric_canonical_id", "") != metric:
                    continue
                if getattr(f, "perimeter_match", "") != "COVERAGE":
                    continue
                fe = getattr(f, "perimeter_entity", "") or ""
                if ok_status is not None:
                    if entity_match_status(fe, decl) in ok_status:
                        hit = True
                        break
                elif fe.strip().lower() == decl.strip().lower():
                    hit = True
                    break
            if hit:
                covered.append(decl)
        out[metric] = {
            "covered": covered,
            "n_covered": len(covered),
            "n_declared": len(ctx.declared_entities),
        }
    return out
