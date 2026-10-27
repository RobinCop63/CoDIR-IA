"""v62.13.9.4.4 — alias d'entités du dossier, fournis par configuration ou par le run.

Aucun nom de dossier n'est codé dans le produit : la liste vit dans
``config/entity_aliases.json`` (vide par défaut) et peut être surchargée par le
run (brief) ou par les tests via :func:`set_entity_aliases`.
"""
from __future__ import annotations

import json
import os
import re
import threading

_LOCK = threading.Lock()
_OVERRIDE: list[str] | None = None


def _config_path() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "entity_aliases.json")


def get_entity_aliases() -> list[str]:
    with _LOCK:
        if _OVERRIDE is not None:
            return list(_OVERRIDE)
    try:
        with open(_config_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        aliases = data.get("entity_aliases") or []
        return [str(a).strip() for a in aliases if str(a).strip()]
    except Exception:
        return []


def set_entity_aliases(aliases: list[str] | None) -> None:
    """Surcharge (run/brief/tests). ``None`` restaure la configuration fichier."""
    global _OVERRIDE
    with _LOCK:
        _OVERRIDE = None if aliases is None else [str(a).strip() for a in aliases if str(a).strip()]


def entity_alias_regex() -> re.Pattern[str] | None:
    aliases = get_entity_aliases()
    if not aliases:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(a) for a in aliases) + r")\b", re.I)
