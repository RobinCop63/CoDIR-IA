"""
CoDIR-IA — run_history v1 (v16.5.76 Phase 5 item 10)

Module d'historique des runs et calcul des deltas entre runs successifs
sur le même dossier (même société).

POURQUOI CE MODULE
==================

Avant Phase 5 : aucune mémoire entre runs. Un DAF qui relance le pipeline
après avoir levé une alerte orange (Phase 5 item 4) ou ajouté des PJ ne
voit aucune indication explicite de progrès. Le score sort en valeur
absolue, sans contexte d'évolution.

Phase 5 item 10 : à la fin de chaque run, persister un snapshot des
métriques clés. Au run suivant sur le même dossier, charger le snapshot
précédent et calculer un delta (score, metrics_count, alerts résolues...).
Le delta est exposé dans le diag CSV et peut être affiché dans le DOCX/PPTX.

DOCTRINE Q1-Q5 RESPECTÉE
========================

Q1 (senior copilote) : le delta est FACTUEL, pas évaluatif. On présente
   "+5 points vs run précédent" sans dire "c'est bien" ou "c'est mal".
Q3 (propose+flag) : si le delta est négatif (score baisse), on flag mais
   on n'alerte pas hystériquement — le DAF a sans doute une raison.

STOCKAGE
========

Fichier JSON par société : `data/run_history/<company_slug>.json`

Structure :
    {
      "company": "FDE",
      "schema_version": 1,
      "runs": [
        {
          "run_id": "abc123def456",
          "timestamp": "2026-05-15T22:34:12Z",
          "score": 78,
          "raw_score": 82,
          "cap_applied": true,
          "metrics_count": 42,
          "agent_claims_count": {
              "finance": 8, "strategie": 7, "marketing": 6,
              "brief_codir": 4, "synthese_decisions": 9, "dg": 8
          },
          "orange_alerts_total": 3,
          "orange_alerts_unresolved": 1,
          "duration_s": 187.5
        },
        ...
      ]
    }

Limite : on garde les 20 derniers runs par société (rotation FIFO).

PHILOSOPHIE FAIL-OPEN
=====================

Si écriture impossible (disque plein, permissions, etc.) → run continue
normalement, juste pas d'historique. Si lecture impossible → pas de delta,
pas d'erreur.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ════════════════════════════════════════════════════════════════════════════

SCHEMA_VERSION = 1
DEFAULT_STORAGE_DIR = "data/run_history"
MAX_RUNS_KEPT_PER_COMPANY = 20

# v16.5.76 Phase 5b (post-audit interne 15 mai 2026) — namespace storage
# Si un intégrateur passe storage_dir= explicitement (ex: UI Streamlit future,
# tests E2E), les fichiers JSON sont placés dans un sous-répertoire de
# namespace pour éviter la collision avec orange_alerts (slugification
# identique pour les fichiers société).
# Quand storage_dir=None, on utilise DEFAULT_STORAGE_DIR directement
# (rétro-compatible avec l'usage en production via codir_engine).
NAMESPACE_SUBDIR = "run_history"


# ════════════════════════════════════════════════════════════════════════════
# TYPES
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RunSnapshot:
    """Snapshot d'un run pour comparaison ultérieure."""
    run_id: str
    timestamp: str
    score: Optional[int] = None
    raw_score: Optional[int] = None
    cap_applied: bool = False
    metrics_count: int = 0
    agent_claims_count: dict = field(default_factory=dict)
    orange_alerts_total: int = 0
    orange_alerts_unresolved: int = 0
    duration_s: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RunDelta:
    """Delta entre deux RunSnapshots (current - previous)."""
    has_previous: bool
    score_delta: Optional[int] = None
    raw_score_delta: Optional[int] = None
    metrics_count_delta: Optional[int] = None
    orange_alerts_total_delta: Optional[int] = None
    orange_alerts_unresolved_delta: Optional[int] = None
    previous_run_id: str = ""
    previous_timestamp: str = ""
    direction: str = "unknown"  # "up" / "down" / "flat" / "unknown"
    human_summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNES
# ════════════════════════════════════════════════════════════════════════════

def _slugify_company(name: str) -> str:
    """Slugifie un nom de société (identique à orange_alerts pour cohérence)."""
    if not name:
        return "unknown"
    s = name.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unknown"


def _make_run_id(company_name: str, timestamp: str) -> str:
    """Run ID déterministe basé sur company + timestamp."""
    payload = f"{company_name}|{timestamp}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_path(company_name: str, storage_dir: Optional[str] = None) -> Path:
    """
    Chemin du JSON d'historique pour une société donnée.

    Si storage_dir est passé explicitement (UI, tests, autre intégrateur),
    on insère un sous-répertoire de namespace (NAMESPACE_SUBDIR) pour éviter
    la collision avec orange_alerts (slugification identique).

    Quand storage_dir=None (cas production via codir_engine), on utilise
    DEFAULT_STORAGE_DIR directement, qui contient déjà 'run_history' dans
    son chemin → rétro-compatible avec les données déjà persistées.
    """
    if storage_dir is None:
        base = Path(DEFAULT_STORAGE_DIR)
    else:
        base = Path(storage_dir) / NAMESPACE_SUBDIR
    return base / f"{_slugify_company(company_name)}.json"


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — STOCKAGE
# ════════════════════════════════════════════════════════════════════════════

def load_run_history(
    company_name: str,
    storage_dir: Optional[str] = None,
) -> list[RunSnapshot]:
    """
    Charge l'historique des runs pour une société (ordre chronologique).

    Returns la liste des RunSnapshots, du plus ancien au plus récent.
    Si fichier absent ou corrompu → retourne [] (fail-open).
    """
    path = _storage_path(company_name, storage_dir)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    runs_raw = data.get("runs", [])
    if not isinstance(runs_raw, list):
        return []
    out: list[RunSnapshot] = []
    for r in runs_raw:
        if not isinstance(r, dict):
            continue
        try:
            out.append(RunSnapshot(
                run_id=str(r.get("run_id", "")),
                timestamp=str(r.get("timestamp", "")),
                score=r.get("score"),
                raw_score=r.get("raw_score"),
                cap_applied=bool(r.get("cap_applied", False)),
                metrics_count=int(r.get("metrics_count", 0)),
                agent_claims_count=r.get("agent_claims_count", {}) or {},
                orange_alerts_total=int(r.get("orange_alerts_total", 0)),
                orange_alerts_unresolved=int(r.get("orange_alerts_unresolved", 0)),
                duration_s=r.get("duration_s"),
            ))
        except Exception:
            continue
    return out


def save_run_snapshot(
    company_name: str,
    snapshot: RunSnapshot,
    storage_dir: Optional[str] = None,
    max_kept: int = MAX_RUNS_KEPT_PER_COMPANY,
) -> bool:
    """
    Persiste un snapshot de run en fin de pipeline.

    Fait une rotation FIFO : on garde les `max_kept` runs les plus récents.

    Returns True si OK, False sinon (fail-open).
    """
    if not company_name or not snapshot:
        return False
    try:
        path = _storage_path(company_name, storage_dir)
        # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
        try:
            from utils.config_paths import ensure_private_dir as _epd
            _epd(path.parent)
        except Exception:
            path.parent.mkdir(parents=True, exist_ok=True)

        # Charger l'existant
        existing_runs = load_run_history(company_name, storage_dir)
        # Append puis rotation
        existing_runs.append(snapshot)
        # Tri par timestamp ascendant pour rotation propre
        try:
            existing_runs.sort(key=lambda r: r.timestamp)
        except Exception:
            pass
        if len(existing_runs) > max_kept:
            existing_runs = existing_runs[-max_kept:]

        new_data = {
            "company":        company_name,
            "schema_version": SCHEMA_VERSION,
            "runs":           [r.to_dict() for r in existing_runs],
            "last_updated_at": _now_iso(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_previous_run(
    company_name: str,
    storage_dir: Optional[str] = None,
) -> Optional[RunSnapshot]:
    """
    Retourne le dernier RunSnapshot du dossier (le plus récent), ou None.

    Utilisé pour calculer le delta du run EN COURS vs le run précédent.
    Le run en cours n'est PAS encore persisté quand on appelle cette fonction.
    """
    history = load_run_history(company_name, storage_dir)
    if not history:
        return None
    # Trier par timestamp décroissant pour prendre le plus récent
    try:
        history.sort(key=lambda r: r.timestamp, reverse=True)
    except Exception:
        pass
    return history[0]


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — CALCUL DELTA
# ════════════════════════════════════════════════════════════════════════════

def compute_delta(
    current: RunSnapshot,
    previous: Optional[RunSnapshot],
) -> RunDelta:
    """
    Calcule le delta entre 2 RunSnapshots (current - previous).

    Si previous est None → RunDelta(has_previous=False), tous les delta=None.
    Si current et previous présents → deltas calculés + summary lisible.

    Le delta n'est PAS un jugement de valeur — c'est un fait. À la couche
    de présentation de décider comment l'afficher.
    """
    if previous is None or current is None:
        return RunDelta(
            has_previous=False,
            direction="unknown",
            human_summary="Premier run sur ce dossier — aucun delta disponible.",
        )

    def _sub(a, b):
        if a is None or b is None:
            return None
        try:
            return int(a) - int(b)
        except (TypeError, ValueError):
            return None

    score_d   = _sub(current.score, previous.score)
    raw_d     = _sub(current.raw_score, previous.raw_score)
    metrics_d = _sub(current.metrics_count, previous.metrics_count)
    total_d   = _sub(current.orange_alerts_total, previous.orange_alerts_total)
    unres_d   = _sub(current.orange_alerts_unresolved, previous.orange_alerts_unresolved)

    direction = "unknown"
    if score_d is not None:
        if score_d > 0:
            direction = "up"
        elif score_d < 0:
            direction = "down"
        else:
            direction = "flat"

    # Synthèse lisible
    parts = []
    if score_d is not None:
        sign = "+" if score_d > 0 else ""
        parts.append(f"score {sign}{score_d} pts")
    if metrics_d is not None:
        sign = "+" if metrics_d > 0 else ""
        parts.append(f"metrics {sign}{metrics_d}")
    if unres_d is not None and unres_d != 0:
        sign = "+" if unres_d > 0 else ""
        parts.append(f"alertes orange non résolues {sign}{unres_d}")
    if parts:
        summary = "Δ vs run précédent : " + " | ".join(parts)
    else:
        summary = "Δ vs run précédent : pas de variation significative."

    return RunDelta(
        has_previous=True,
        score_delta=score_d,
        raw_score_delta=raw_d,
        metrics_count_delta=metrics_d,
        orange_alerts_total_delta=total_d,
        orange_alerts_unresolved_delta=unres_d,
        previous_run_id=previous.run_id,
        previous_timestamp=previous.timestamp,
        direction=direction,
        human_summary=summary,
    )


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — INTÉGRATION CODIR_ENGINE
# ════════════════════════════════════════════════════════════════════════════

def build_current_snapshot(
    company_name: str,
    confidence_score: Optional[dict],
    metrics_count: int,
    agent_claims_count: dict,
    orange_alerts_total: int,
    orange_alerts_unresolved: int,
    duration_s: Optional[float] = None,
) -> RunSnapshot:
    """
    Helper pour construire un RunSnapshot à partir des données du run courant.

    Args:
        confidence_score : dict retourné par compute_confidence (peut être None).
                            On y cherche les clés "score", "raw_score", "cap_applied".
        agent_claims_count : dict {role: claims_count} (vient de _agent_json_stats).

    Returns:
        RunSnapshot pré-rempli, prêt à être persisté.
    """
    now = _now_iso()
    score = None
    raw_score = None
    cap_applied = False
    if isinstance(confidence_score, dict):
        score = confidence_score.get("score")
        raw_score = confidence_score.get("raw_score")
        cap_applied = bool(confidence_score.get("cap_applied", False))

    # Normaliser agent_claims_count (peut contenir des structures complexes)
    safe_claims_count: dict = {}
    if isinstance(agent_claims_count, dict):
        for k, v in agent_claims_count.items():
            try:
                if isinstance(v, dict):
                    safe_claims_count[str(k)] = int(v.get("claims_count", 0))
                else:
                    safe_claims_count[str(k)] = int(v)
            except (TypeError, ValueError):
                continue

    return RunSnapshot(
        run_id=_make_run_id(company_name or "unknown", now),
        timestamp=now,
        score=score,
        raw_score=raw_score,
        cap_applied=cap_applied,
        metrics_count=int(metrics_count or 0),
        agent_claims_count=safe_claims_count,
        orange_alerts_total=int(orange_alerts_total or 0),
        orange_alerts_unresolved=int(orange_alerts_unresolved or 0),
        duration_s=duration_s,
    )


def compute_and_persist_delta(
    company_name: str,
    confidence_score: Optional[dict],
    metrics_count: int,
    agent_claims_count: dict,
    orange_alerts_total: int,
    orange_alerts_unresolved: int,
    duration_s: Optional[float] = None,
    storage_dir: Optional[str] = None,
) -> tuple[RunDelta, bool]:
    """
    Helper haut-niveau pour codir_engine.

    1. Construit le snapshot courant
    2. Charge le snapshot précédent (s'il existe)
    3. Calcule le delta
    4. Persiste le snapshot courant (rotation FIFO 20 runs)

    Returns:
        (RunDelta, persist_ok: bool)
    """
    if not company_name:
        return RunDelta(has_previous=False,
                        human_summary="Nom de société absent — historique non chargé."), False
    try:
        previous = get_previous_run(company_name, storage_dir)
        current = build_current_snapshot(
            company_name=company_name,
            confidence_score=confidence_score,
            metrics_count=metrics_count,
            agent_claims_count=agent_claims_count,
            orange_alerts_total=orange_alerts_total,
            orange_alerts_unresolved=orange_alerts_unresolved,
            duration_s=duration_s,
        )
        delta = compute_delta(current, previous)
        persist_ok = save_run_snapshot(company_name, current, storage_dir)
        return delta, persist_ok
    except Exception:
        # Fail-open : si quelque chose casse, run continue
        return RunDelta(has_previous=False,
                        human_summary="Erreur interne run_history — pas de delta."), False


__all__ = [
    "RunSnapshot",
    "RunDelta",
    "SCHEMA_VERSION",
    "DEFAULT_STORAGE_DIR",
    "MAX_RUNS_KEPT_PER_COMPANY",
    "load_run_history",
    "save_run_snapshot",
    "get_previous_run",
    "compute_delta",
    "build_current_snapshot",
    "compute_and_persist_delta",
]
