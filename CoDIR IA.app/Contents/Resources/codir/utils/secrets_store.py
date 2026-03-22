from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config_paths import ensure_config_dir, get_secrets_path

@dataclass
class Secrets:
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    gemini_api_key: str = ""  # alias, optional
    mistral_api_key: str = ""

    def to_env(self) -> Dict[str, str]:
        env: Dict[str, str] = {}
        if self.openai_api_key:
            env["OPENAI_API_KEY"] = self.openai_api_key
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.google_api_key:
            env["GOOGLE_API_KEY"] = self.google_api_key
        if self.gemini_api_key and "GOOGLE_API_KEY" not in env:
            env["GEMINI_API_KEY"] = self.gemini_api_key
        if self.mistral_api_key:
            env["MISTRAL_API_KEY"] = self.mistral_api_key
        return env

def _safe_read_json(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def load_secrets() -> Secrets:
    p = get_secrets_path()
    data = _safe_read_json(p)
    return Secrets(
        openai_api_key=str(data.get("OPENAI_API_KEY") or data.get("openai_api_key") or ""),
        anthropic_api_key=str(data.get("ANTHROPIC_API_KEY") or data.get("anthropic_api_key") or ""),
        google_api_key=str(data.get("GOOGLE_API_KEY") or data.get("google_api_key") or ""),
        gemini_api_key=str(data.get("GEMINI_API_KEY") or data.get("gemini_api_key") or ""),
        mistral_api_key=str(data.get("MISTRAL_API_KEY") or data.get("mistral_api_key") or ""),
    )

def save_secrets(secrets: Secrets) -> Path:
    ensure_config_dir()
    p = get_secrets_path()
    payload = {
        "OPENAI_API_KEY": secrets.openai_api_key.strip(),
        "ANTHROPIC_API_KEY": secrets.anthropic_api_key.strip(),
        "GOOGLE_API_KEY": secrets.google_api_key.strip(),
        "GEMINI_API_KEY": secrets.gemini_api_key.strip(),
        "MISTRAL_API_KEY": secrets.mistral_api_key.strip(),
    }
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p

def apply_secrets_to_env(secrets: Optional[Secrets] = None, override: bool = False) -> Secrets:
    if secrets is None:
        secrets = load_secrets()
    env_map = secrets.to_env()
    import os
    for k, v in env_map.items():
        if override or not os.getenv(k):
            os.environ[k] = v
    return secrets

def has_any_key(secrets: Optional[Secrets] = None) -> bool:
    s = secrets or load_secrets()
    return any([
        bool(s.openai_api_key.strip()),
        bool(s.anthropic_api_key.strip()),
        bool(s.google_api_key.strip() or s.gemini_api_key.strip()),
        bool(s.mistral_api_key.strip()),
    ])
