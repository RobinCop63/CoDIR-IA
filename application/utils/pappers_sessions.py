"""
utils/pappers_sessions.py — Persistance des logs de résolution Pappers — v16.5.67
Journalise chaque session dans outputs/pappers_sessions.jsonl (append).
Format : une ligne JSON par session, exploitable pour audit et métriques de coût.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Chemin du journal — dans outputs/ pour être à côté des exports DOCX/PPTX
_DEFAULT_JOURNAL = Path("outputs") / "pappers_sessions.jsonl"


def _journal_path() -> Path:
    override = os.environ.get("PAPPERS_SESSIONS_PATH", "")
    return Path(override) if override else _DEFAULT_JOURNAL


def append_session_log(
    resolution_log,            # PappersResolutionLog ou None
    session_ts: str = "",      # timestamp ISO de la session (si disponible)
    pappers_credits_est: float = 0.0,
) -> Optional[Path]:
    """
    Appende une ligne JSON dans le journal des sessions Pappers.
    Non bloquant — toute exception est silencieusement absorbée.

    Retourne le chemin du journal, ou None si log vide / échec.
    """
    if resolution_log is None:
        return None
    try:
        path = _journal_path()
        # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
        try:
            from utils.config_paths import ensure_private_dir as _epd
            _epd(path.parent)
        except Exception:
            path.parent.mkdir(parents=True, exist_ok=True)

        # Estimation heuristique des crédits Pappers consommés.
        # NOTE : estimation, pas un comptage réel.
        # Utile pour piloter vos marges (vous payez les APIs, le client paie un forfait).
        # Heuristique : fiche=1.1 cr, +2.0 cr si contexte financier (comptes appelés).
        # Pour un comptage exact : instrumenter _fetch_fiche/_fetch_comptes (v17).
        # Estimation heuristique des crédits Pappers consommés.
        # NOTE : estimation, pas un comptage réel appel par appel.
        # Utile pour surveiller vos marges fournisseur (vous payez les APIs,
        # le client paie un forfait). Heuristique : fiche=1.1 cr, +2.0 cr
        # si contexte financier (comptes annuels appelés).
        # Pour un comptage exact : instrumenter _fetch_fiche/_fetch_comptes (v17).
        if pappers_credits_est == 0.0:
            base = 1.1 if resolution_log.siren_used else 0.1
            base += 2.0 if resolution_log.contexte_fin else 0.0
            pappers_credits_est = round(base, 2)

        # Mettre à jour le champ dans l'objet lui-même
        try:
            resolution_log.pappers_credits_est = pappers_credits_est
        except Exception:
            pass

        entry = resolution_log.to_dict()
        entry["session_timestamp"] = session_ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry["pappers_credits_est"] = round(pappers_credits_est, 3)

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path
    except Exception:
        return None


def load_recent_sessions(n: int = 10) -> list[dict]:
    """
    Charge les n dernières entrées du journal (ordre chronologique inverse).
    Retourne [] si le journal est absent ou vide.
    """
    path = _journal_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in reversed(lines[-100:]):   # lire les 100 dernières max
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries[:n]
    except Exception:
        return []


def session_cost_summary(n: int = 10) -> dict:
    """
    Résumé des coûts sur les n dernières sessions.
    Retourne {sessions, total_credits_est, avg_credits, total_tokens_full,
              avg_tokens_full, total_tokens_summary, cache_hit_rate}.
    """
    entries = load_recent_sessions(n)
    if not entries:
        return {"sessions": 0}

    total_cr    = sum(e.get("pappers_credits_est", 0) for e in entries)
    total_tf    = sum(e.get("tokens_est_full", 0)     for e in entries)
    total_ts    = sum(e.get("tokens_est_summary", 0)  for e in entries)
    cache_hits  = sum(1 for e in entries if e.get("cache_hit"))

    return {
        "sessions":         len(entries),
        "total_credits_est": round(total_cr, 2),
        "avg_credits":       round(total_cr / len(entries), 2),
        "total_tokens_full": total_tf,
        "avg_tokens_full":   round(total_tf / len(entries)),
        "total_tokens_summary": total_ts,
        "cache_hit_rate":    round(cache_hits / len(entries) * 100, 1),
    }
