import os
from pathlib import Path

APP_NAME = "CoDIR-IA"

def get_config_dir() -> Path:
    """Return an OS-appropriate config directory."""
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / ".config" / APP_NAME

def get_secrets_path() -> Path:
    return get_config_dir() / "secrets.json"

def get_settings_path() -> Path:
    return get_config_dir() / "settings.json"

def ensure_config_dir() -> Path:
    p = get_config_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p
