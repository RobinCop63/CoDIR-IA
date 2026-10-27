"""
CoDIR-IA — orange_alerts v1 (v16.5.76 Phase 5 item 4)

Module de gestion des alertes orange avec mécanisme de levée par DAF.

POURQUOI CE MODULE
==================

Avant Phase 5 :
  - Le scorer pénalise mécaniquement quand `_orange_alerts > 0` via le rule
    `ORANGE_ALERTS_UNRESOLVED` (cf. patches/confidence_scorer.py)
  - Conséquence sur les runs FDE/dossier de conseil : un FLAGGED non critique
    plombait le score sans permettre au DAF de lever l'alerte après revue

Phase 5 item 4 : introduire un mécanisme persistant de levée d'alerte avec
justification écrite. Le DAF peut ainsi :
  - Revoir l'alerte (ex: « FLAGGED scope ambigu sur filiale Lorraine »)
  - Décider si elle est matérielle ou non
  - Écrire la justification (ex: « scope clarifié verbalement avec CFO Groupe »)
  - Marquer l'alerte comme résolue → le scorer ne la compte plus

DOCTRINE Q1-Q5 RESPECTÉE
========================

Q1 (senior copilote) : la résolution est une DÉCISION HUMAINE, pas une
   suggestion automatique. Le DAF garde la main, Claude ne décide pas.
Q3 (propose+flag) : les alertes restent visibles dans le diag CSV avec
   leur statut (raised/resolved/dismissed) — traçabilité totale.
Q5 (AI Act §4bis) : la justification du DAF est consignée et horodatée
   pour l'audit AI Act art. 9 (système de gestion des risques).

STOCKAGE
========

Fichier JSON local : `data/orange_alerts_resolved/<company_slug>.json`

Structure :
    {
      "company": "FDE",
      "resolved_alerts": {
        "<alert_id>": {
          "resolved_at": "2026-05-15T22:34:12Z",
          "daf_initials": "RS",
          "justification": "...",
          "alert_type": "FLAGGED",
          "role": "supply_chain",
          "original_message": "..."
        },
        ...
      },
      "schema_version": 1
    }

Pure fonction côté Python : pas de DB, pas d'API. Le DAF édite directement
le JSON via une UI streamlit (cf. brief_ui.py extension future) ou à la
main pour la première version.

PHILOSOPHIE FAIL-OPEN
=====================

Si le module n'est pas chargé, le storage n'existe pas, le JSON est
corrompu → le code retombe sur le comportement v75.5 (toutes les alertes
sont comptées). Aucune exception ne casse le run.
"""

from __future__ import annotations

import json
import os
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
DEFAULT_STORAGE_DIR = "data/orange_alerts_resolved"

# v16.5.76 Phase 5b (post-audit interne 15 mai 2026) — namespace storage
# Si un intégrateur passe storage_dir= explicitement (ex: UI Streamlit future,
# tests E2E, autre module), les fichiers JSON sont placés dans un sous-répertoire
# de namespace pour éviter la collision avec d'autres modules de la Phase 5
# (run_history utilise un slug identique pour ses fichiers société).
# Quand storage_dir=None, on utilise DEFAULT_STORAGE_DIR directement
# (rétro-compatible avec l'usage en production via codir_engine).
NAMESPACE_SUBDIR = "orange_alerts_resolved"


# ════════════════════════════════════════════════════════════════════════════
# TYPES
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OrangeAlert:
    """
    Alerte orange brute issue du pipeline.

    Champs :
    - alert_id : identifiant déterministe (hash stable role+message), permet
                 de re-matcher une alerte d'un run à l'autre
    - alert_type : "FLAGGED" (par défaut), "ANOMALY", "INCONSISTENCY"
    - role : rôle qui a levé l'alerte (finance, supply_chain, strategie...)
    - message : message court de l'alerte (< 200 chars)
    - raised_at : ISO timestamp
    - severity : "low" / "medium" / "high"
    """
    alert_id: str
    alert_type: str
    role: str
    message: str
    raised_at: str
    severity: str = "medium"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedAlert:
    """Alerte résolue par un DAF avec justification écrite."""
    alert_id: str
    resolved_at: str
    daf_initials: str
    justification: str
    alert_type: str = ""
    role: str = ""
    original_message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNES
# ════════════════════════════════════════════════════════════════════════════

def _slugify_company(name: str) -> str:
    """
    Convertit un nom de société en slug filesystem-safe.

    "La Française de l'Énergie" → "la-francaise-de-l-energie"
    """
    if not name:
        return "unknown"
    s = name.lower().strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "unknown"


def _make_alert_id(role: str, message: str) -> str:
    """
    Crée un alert_id déterministe à partir de role + message.

    Pourquoi déterministe : si la même alerte est levée à 2 runs différents
    sur le même dossier (ex: scope ambigu filiale Lorraine), elle doit avoir
    le MÊME alert_id pour que la levée du DAF s'applique au prochain run.
    """
    import hashlib
    # Normaliser pour stabilité (espaces, casse)
    norm_role = (role or "").strip().lower()
    norm_msg = re.sub(r"\s+", " ", (message or "").strip().lower())[:200]
    payload = f"{norm_role}|{norm_msg}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — STOCKAGE
# ════════════════════════════════════════════════════════════════════════════

def _storage_path(company_name: str, storage_dir: Optional[str] = None) -> Path:
    """
    Chemin du JSON de levées pour une société donnée.

    Si storage_dir est passé explicitement (UI, tests, autre intégrateur),
    on insère un sous-répertoire de namespace (NAMESPACE_SUBDIR) pour éviter
    la collision avec d'autres modules de la Phase 5 (run_history utilise
    une slugification identique pour ses fichiers société).

    Quand storage_dir=None (cas production via codir_engine), on utilise
    DEFAULT_STORAGE_DIR directement, qui contient déjà 'orange_alerts_resolved'
    dans son chemin → rétro-compatible avec les données déjà persistées.
    """
    if storage_dir is None:
        base = Path(DEFAULT_STORAGE_DIR)
    else:
        # Sous-dir de namespace pour éviter collision avec run_history
        base = Path(storage_dir) / NAMESPACE_SUBDIR
    return base / f"{_slugify_company(company_name)}.json"


def load_resolved_alerts(
    company_name: str,
    storage_dir: Optional[str] = None,
) -> dict[str, ResolvedAlert]:
    """
    Charge les alertes résolues pour une société.

    Retourne un dict {alert_id: ResolvedAlert}.
    Si fichier absent ou corrompu → retourne {} silencieusement (fail-open).
    """
    path = _storage_path(company_name, storage_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    resolved_raw = data.get("resolved_alerts", {})
    out: dict[str, ResolvedAlert] = {}
    if isinstance(resolved_raw, dict):
        for aid, info in resolved_raw.items():
            if not isinstance(info, dict):
                continue
            try:
                out[aid] = ResolvedAlert(
                    alert_id=str(aid),
                    resolved_at=str(info.get("resolved_at", "")),
                    daf_initials=str(info.get("daf_initials", "")),
                    justification=str(info.get("justification", ""))[:1000],
                    alert_type=str(info.get("alert_type", "")),
                    role=str(info.get("role", "")),
                    original_message=str(info.get("original_message", ""))[:200],
                )
            except Exception:
                continue
    return out


def save_resolved_alert(
    company_name: str,
    alert: OrangeAlert,
    daf_initials: str,
    justification: str,
    storage_dir: Optional[str] = None,
) -> bool:
    """
    Persiste une levée d'alerte par un DAF.

    Args:
        company_name : nom de la société (slugifié pour le filename)
        alert        : alerte d'origine
        daf_initials : initiales du DAF (ex: "RS")
        justification: justification écrite (< 1000 chars)

    Returns:
        True si écriture OK, False sinon.
    """
    if not company_name or not alert or not alert.alert_id:
        return False
    if not daf_initials or not justification:
        return False
    if len(justification) > 1000:
        justification = justification[:1000]

    # v16.5.76 Phase 5b (post-audit interne) — sanitization stricte des initiales
    # Pour un audit trail AI Act art. 9, on restreint à [A-Z0-9] strict et ≤ 5 chars.
    # Empêche : injection HTML/JS dans rendu futur, caractères invisibles, padding
    # avec espaces, ponctuation. Une initiale valide = "RS", "RS2", "ABCDE", pas plus.
    daf_initials_clean = re.sub(r"[^A-Z0-9]", "", daf_initials.upper())[:5]
    if not daf_initials_clean:
        # Rejet si après sanitization il ne reste rien (ex: "<>!" → "")
        return False

    path = _storage_path(company_name, storage_dir)
    try:
        # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
        try:
            from utils.config_paths import ensure_private_dir as _epd
            _epd(path.parent)
        except Exception:
            path.parent.mkdir(parents=True, exist_ok=True)
        # Charger l'existant
        existing = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (OSError, json.JSONDecodeError):
                existing = {}
        if not isinstance(existing, dict):
            existing = {}

        resolved_alerts = existing.get("resolved_alerts", {})
        if not isinstance(resolved_alerts, dict):
            resolved_alerts = {}

        resolved_alerts[alert.alert_id] = {
            "resolved_at":      _now_iso(),
            "daf_initials":     daf_initials_clean,
            "justification":    justification,
            "alert_type":       alert.alert_type,
            "role":             alert.role,
            "original_message": alert.message[:200],
        }

        new_data = {
            "company":          company_name,
            "schema_version":   SCHEMA_VERSION,
            "resolved_alerts":  resolved_alerts,
            "last_updated_at":  _now_iso(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def is_resolved(
    alert_id: str,
    company_name: str,
    storage_dir: Optional[str] = None,
) -> bool:
    """Vérifie si une alerte spécifique est résolue pour cette société."""
    if not alert_id or not company_name:
        return False
    resolved = load_resolved_alerts(company_name, storage_dir)
    return alert_id in resolved


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — FILTRAGE
# ════════════════════════════════════════════════════════════════════════════

def filter_unresolved_alerts(
    alerts: list[OrangeAlert],
    company_name: str,
    storage_dir: Optional[str] = None,
) -> tuple[list[OrangeAlert], list[OrangeAlert], dict]:
    """
    Filtre une liste d'alertes en séparant résolues / non-résolues.

    Args:
        alerts       : liste d'OrangeAlert produites par le run courant
        company_name : nom de la société (pour load_resolved_alerts)
        storage_dir  : surchargé optionnellement

    Returns:
        (unresolved, resolved, summary_dict) où summary_dict =
        {
          "total": int,
          "unresolved_count": int,
          "resolved_count": int,
          "resolved_details": [{alert_id, daf, justification, role, message}, ...]
        }

    Cette fonction est PURE (lit le storage mais ne le modifie pas).
    """
    if not alerts:
        return [], [], {
            "total": 0,
            "unresolved_count": 0,
            "resolved_count": 0,
            "resolved_details": [],
        }
    if not company_name:
        return list(alerts), [], {
            "total": len(alerts),
            "unresolved_count": len(alerts),
            "resolved_count": 0,
            "resolved_details": [],
        }

    resolved_map = load_resolved_alerts(company_name, storage_dir)
    unresolved: list[OrangeAlert] = []
    resolved: list[OrangeAlert] = []
    resolved_details: list[dict] = []
    for a in alerts:
        if a.alert_id in resolved_map:
            resolved.append(a)
            r = resolved_map[a.alert_id]
            resolved_details.append({
                "alert_id":     a.alert_id,
                "daf_initials": r.daf_initials,
                "justification": r.justification,
                "role":         a.role,
                "message":      a.message[:120],
                "resolved_at":  r.resolved_at,
            })
        else:
            unresolved.append(a)

    return unresolved, resolved, {
        "total":            len(alerts),
        "unresolved_count": len(unresolved),
        "resolved_count":   len(resolved),
        "resolved_details": resolved_details,
    }


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — DÉTECTION (extraction depuis diag_list)
# ════════════════════════════════════════════════════════════════════════════

def extract_alerts_from_diag(diag_list: list[dict]) -> list[OrangeAlert]:
    """
    Parcourt diag_list et extrait les entrées status=FLAGGED en OrangeAlerts.

    Returns une liste, déduplique par alert_id (si même role+message).
    """
    if not diag_list:
        return []
    seen: set[str] = set()
    out: list[OrangeAlert] = []
    now = _now_iso()
    for d in diag_list:
        if not isinstance(d, dict):
            continue
        status = str(d.get("status", "")).upper()
        if status != "FLAGGED":
            continue
        role = str(d.get("role", "") or "")
        # Le message peut venir de plusieurs champs selon les patches
        msg = str(
            d.get("error", "") or d.get("reason", "") or d.get("message", "")
            or d.get("output", "") or ""
        )[:200]
        if not role and not msg:
            continue
        aid = _make_alert_id(role, msg)
        if aid in seen:
            continue
        seen.add(aid)
        out.append(OrangeAlert(
            alert_id=aid,
            alert_type="FLAGGED",
            role=role,
            message=msg,
            raised_at=now,
            severity="medium",
        ))
    return out


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — INTÉGRATION CODIR_ENGINE
# ════════════════════════════════════════════════════════════════════════════

def count_unresolved_in_diag(
    diag_list: list[dict],
    company_name: str,
    storage_dir: Optional[str] = None,
) -> tuple[int, int, dict]:
    """
    Helper haut-niveau pour codir_engine.

    Extrait les alertes du diag_list, charge les résolutions DAF, retourne :
        (unresolved_count, total_count, summary_dict)

    summary_dict contient resolved_details (audit trail pour le DOCX/diag).

    Si company_name vide ou storage indisponible → fallback gracieux :
    retourne (total, total, {}) — toutes les alertes comptent comme non
    résolues, comportement v75.5 préservé.
    """
    alerts = extract_alerts_from_diag(diag_list)
    if not alerts:
        return 0, 0, {
            "total": 0, "unresolved_count": 0,
            "resolved_count": 0, "resolved_details": [],
        }
    if not company_name:
        return len(alerts), len(alerts), {
            "total": len(alerts), "unresolved_count": len(alerts),
            "resolved_count": 0, "resolved_details": [],
        }
    try:
        _unresolved, _resolved, summary = filter_unresolved_alerts(
            alerts, company_name, storage_dir,
        )
        return summary["unresolved_count"], summary["total"], summary
    except Exception:
        # Fail-open : si quelque chose casse, on retombe sur le comportement v75.5
        return len(alerts), len(alerts), {
            "total": len(alerts), "unresolved_count": len(alerts),
            "resolved_count": 0, "resolved_details": [],
        }


__all__ = [
    "OrangeAlert",
    "ResolvedAlert",
    "SCHEMA_VERSION",
    "DEFAULT_STORAGE_DIR",
    "load_resolved_alerts",
    "save_resolved_alert",
    "is_resolved",
    "filter_unresolved_alerts",
    "extract_alerts_from_diag",
    "count_unresolved_in_diag",
]
