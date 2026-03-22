from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from .config_paths import ensure_config_dir, get_settings_path

@dataclass
class Settings:
    mode_default: str = "equilibre"  # equilibre | qualite | eco
    temperature: float = 0.4
    max_output_tokens: int = 4000

    openai_model_id: str = "gpt-4.1-mini"  # default; configurable
    google_model_id: str = "gemini-2.5-flash"
    anthropic_model_id: str = "claude-sonnet-4-5"
    mistral_model_id: str = "mistral-medium-latest"

    fallback_enabled: bool = True
    fallback_max_attempts: int = 2

    attachments_max_files: int = 5
    attachments_max_total_mb: int = 25
    attachments_doc_token_budget: int = 8000

def _safe_read_json(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

# Modèles obsolètes → remplacés automatiquement à la lecture
_MODEL_MIGRATIONS: Dict[str, str] = {
    "gpt-5-mini":                  "gpt-4.1-mini",
    "gpt-5":                       "gpt-4.1",
    "gpt-4o-mini":                 "gpt-4.1-mini",
    "mistral-large-latest":        "mistral-medium-latest",
    "gemini-2.0-flash":            "gemini-2.5-flash",
    "claude-3-5-sonnet-20241022":  "claude-sonnet-4-5",
}

def load_settings() -> Settings:
    p = get_settings_path()
    d = _safe_read_json(p)
    s = Settings()
    _migrated = False
    for k in s.__dataclass_fields__.keys():
        if k in d:
            val = d[k]
            # Migration automatique des model_id obsolètes
            if k.endswith("_model_id") and val in _MODEL_MIGRATIONS:
                val = _MODEL_MIGRATIONS[val]
                _migrated = True
            setattr(s, k, val)
    # Réécrire le settings.json si migration (met à jour le fichier local)
    if _migrated:
        save_settings(s)
    return s

def save_settings(settings: Settings) -> Path:
    ensure_config_dir()
    p = get_settings_path()
    p.write_text(json.dumps(settings.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")
    return p
