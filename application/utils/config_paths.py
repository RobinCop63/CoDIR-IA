import os
import sys
from pathlib import Path

# CoDIR IA — config_paths.py — v16.5.67
APP_NAME = "CoDIR-IA"


def _legacy_config_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def get_config_dir() -> Path:
    """Return the primary OS-appropriate config directory.

    Priority:
      1) CODIR_CONFIG_DIR override
      2) Windows   -> %APPDATA%\\CoDIR-IA
      3) macOS     -> ~/Library/Application Support/CoDIR-IA
      4) Linux/XDG -> $XDG_CONFIG_HOME/CoDIR-IA or ~/.config/CoDIR-IA
    """
    override = (os.getenv("CODIR_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser()

    if sys.platform == 'win32':
        appdata = os.getenv('APPDATA')
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / 'AppData' / 'Roaming' / APP_NAME

    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP_NAME

    xdg = os.getenv('XDG_CONFIG_HOME')
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / '.config' / APP_NAME


def candidate_config_dirs() -> list[Path]:
    """Directories to try when loading secrets/settings.

    The first item is the canonical location. Legacy paths are still read so
    older installs continue to work after migration.
    """
    primary = get_config_dir()
    dirs = [primary]
    legacy = _legacy_config_dir()
    if legacy != primary:
        dirs.append(legacy)
    return dirs




def get_cache_dir() -> Path:
    """Return the canonical OS-appropriate cache directory.

    Priority:
      1) CODIR_CACHE_DIR override
      2) Windows -> %LOCALAPPDATA%\\CoDIR-IA\\cache
      3) macOS   -> ~/Library/Application Support/CoDIR-IA/cache
      4) Linux   -> $XDG_CACHE_HOME/CoDIR-IA or ~/.cache/CoDIR-IA
    """
    override = (os.getenv("CODIR_CACHE_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME / "cache"
        return Path.home() / "AppData" / "Local" / APP_NAME / "cache"
    if sys.platform == "darwin":
        return get_config_dir() / "cache"
    xdg = os.getenv("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".cache" / APP_NAME


def get_data_dir() -> Path:
    """Return the canonical local data/history directory."""
    override = (os.getenv("CODIR_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    return get_config_dir() / "data"


def ensure_cache_dir() -> Path:
    return ensure_private_dir(get_cache_dir())


def ensure_data_dir() -> Path:
    return ensure_private_dir(get_data_dir())


def get_secrets_path() -> Path:
    return get_config_dir() / 'secrets.json'


def get_settings_path() -> Path:
    return get_config_dir() / 'settings.json'


def ensure_config_dir() -> Path:
    p = get_config_dir()
    p.mkdir(parents=True, exist_ok=True)
    # v16.5.76 Phase 7a (audit sécurité 25 mai 2026, VULN-5 validée ChatGPT) :
    # Restreindre les permissions du dossier de config CoDIR-IA à 0o700
    # (owner-only) sur POSIX. Sans ce chmod, le dossier hérite de l'umask
    # par défaut (souvent 0o755 = world-readable), ce qui permettrait à un
    # user local de LISTER (et donc cibler) les fichiers secrets.json,
    # settings.json, pappers_cache.json. Sur Windows : chmod no-op, mitigation
    # via ACL/Credential Manager tracée v17.
    if os.name == 'posix':
        try:
            current_mode = p.stat().st_mode & 0o777
            if current_mode & 0o077 != 0:
                os.chmod(p, 0o700)
        except OSError:
            # Fail-open : si le chmod échoue, on continue (FS exotique).
            pass
    return p


def ensure_private_dir(path: Path) -> Path:
    """v16.5.76 Phase 7a — Helper public pour créer un dossier privé (0o700 POSIX).

    À utiliser partout où CoDIR-IA crée un sous-dossier susceptible de contenir
    des données sensibles : caches Pappers/Companies House, run_history,
    orange_alerts, etc. Idempotent. Fail-open si chmod échoue.

    Args:
        path: chemin du dossier à créer

    Returns:
        path tel quel pour chaînage
    """
    path.mkdir(parents=True, exist_ok=True)
    if os.name == 'posix':
        try:
            current_mode = path.stat().st_mode & 0o777
            if current_mode & 0o077 != 0:
                os.chmod(path, 0o700)
        except OSError:
            pass
    return path
