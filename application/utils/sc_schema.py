# -*- coding: utf-8 -*-
"""M6-A2.2.3 — Garde de schéma Supply Chain, SOURCE DE VÉRITÉ UNIQUE (moteur + deck).

Historique de durcissement :
  - A2.2.2 : la garde n'existait que côté deck ; factorisée ici. Mais elle acceptait
    tout dict portant une clé « forte » (key_findings, recommendations, ...). Or
    key_findings / recommendations / codir_tradeoffs / dg_decisions sont des clés
    GÉNÉRIQUES (un JSON Strategy/Marketing/Finance/Board peut les porter).
  - A2.2.3 : on prouve « Supply Chain » par la STRUCTURE MÉTIER, pas par la présence
    d'une clé générique. Référence = le schéma réellement demandé à l'agent SC :
      global_status ∈ {healthy|under_pressure|degraded|critical}
      scores = {service_level, stock_management, supply_resilience, cash_impact}
      recommendations = {0_30_days, 1_3_months, 3_12_months}

Un JSON est Supply Chain s'il porte AU MOINS UNE signature structurelle SC. Un JSON
commercial (opportunites/plan_actions/challenges_*) ou générique (recommendations en
liste, key_findings seul, recommendations:{marketing:[...]}) est rejeté.
"""
from __future__ import annotations
import unicodedata

# Clés SC fortes (rétro-compat A2.2.2) — exposées mais NON suffisantes seules.
SC_STRONG_KEYS = {"key_findings", "major_risks", "codir_tradeoffs",
                  "recommendations", "dg_decisions"}
COMMERCIAL_JSON_KEYS = {"opportunites", "plan_actions",
                        "challenges_marketing", "challenges_finance"}

# Signatures structurelles RÉELLEMENT spécifiques à la Supply Chain.
SC_SCORE_KEYS = {"service_level", "stock_management", "supply_resilience", "cash_impact"}
SC_HORIZON_KEYS = {"0_30_days", "1_3_months", "3_12_months"}
SC_STATUS_VALUES = {
    "healthy", "under_pressure", "degraded", "critical",          # EN (enum agent)
    "sain", "sous_tension", "tendu", "degrade", "critique",       # FR variantes
}


def _norm(value) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower().replace(" ", "_").replace("-", "_")


def _has_sc_signature(obj: dict) -> bool:
    """True si le dict porte au moins une preuve STRUCTURELLE Supply Chain."""
    # 1) scores SC (service_level / stock_management / supply_resilience / cash_impact)
    scores = obj.get("scores")
    if isinstance(scores, dict) and (SC_SCORE_KEYS & {str(k) for k in scores.keys()}):
        return True
    # 2) recommandations par HORIZON (dict 0_30_days / 1_3_months / 3_12_months)
    rec = obj.get("recommendations")
    if isinstance(rec, dict) and (SC_HORIZON_KEYS & {str(k) for k in rec.keys()}):
        return True
    # 3) global_status portant un statut SC reconnu (enum)
    if "global_status" in obj and _norm(obj.get("global_status")) in SC_STATUS_VALUES:
        return True
    # 4) major_risks structuré « à la SC » : liste de dicts portant risk + probability
    risks = obj.get("major_risks")
    if isinstance(risks, list) and any(
        isinstance(r, dict) and "risk" in r and "probability" in r for r in risks):
        return True
    return False


def is_supply_chain_json(obj) -> bool:
    """True UNIQUEMENT si `obj` porte une signature structurelle Supply Chain.
    Une simple clé générique (recommendations/key_findings seule) ne suffit pas.
    Un JSON commercial explicite est rejeté."""
    if not isinstance(obj, dict):
        return False
    keys = set(obj.keys())
    if (COMMERCIAL_JSON_KEYS & keys) and not _has_sc_signature(obj):
        return False
    return _has_sc_signature(obj)


# ── M6-A2.2.5 — helpers type-safe PARTAGÉS (moteur + deck) ───────────────────
# Un champ JSON SC mal typé (sortie LLM) ne doit JAMAIS crasher un consommateur,
# ni côté codir_engine (should_generate_sc_slide) ni côté deck.
def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def as_str_list(value):
    if isinstance(value, list):
        return [x for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []
