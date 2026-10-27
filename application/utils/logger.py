from __future__ import annotations
import json
import logging
import os
import re
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"),
)


def redact_log_text(value: object) -> str:
    """Remove common secrets from crash/log messages before disk persistence."""
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: (m.group(1) or "") + "[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text




class RedactingFormatter(logging.Formatter):
    """Redact secrets from the entire rendered record, including traceback text."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


def _private_file(path: Path) -> None:
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _has_handler_for(logger: logging.Logger, path: Path) -> bool:
    wanted = str(path.resolve())
    for handler in logger.handlers:
        base = getattr(handler, "baseFilename", "")
        if base:
            try:
                if str(Path(base).resolve()) == wanted:
                    return True
            except Exception:
                if str(base) == str(path):
                    return True
    return False


def _ensure_rotating_handler(logger: logging.Logger, path: Path, *, level: int) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _has_handler_for(logger, path):
        handler = TimedRotatingFileHandler(
            filename=str(path), when="D", interval=1, backupCount=14,
            encoding="utf-8", utc=True,
        )
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    _private_file(path)
    return logger


def get_logger(log_dir: Path) -> logging.Logger:
    """Structured application-event logger (JSONL, 7-day rotation)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("codir")
    path = log_dir / "codir.log.jsonl"
    if not _has_handler_for(logger, path):
        handler = TimedRotatingFileHandler(
            filename=str(path), when="D", interval=1, backupCount=7,
            encoding="utf-8", utc=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    _private_file(path)
    return logger


def get_crash_log_path(log_dir: Path | None = None) -> Path:
    if log_dir is None:
        from .config_paths import ensure_config_dir
        log_dir = ensure_config_dir() / "logs"
    return Path(log_dir) / "codir-ia.log"


def get_crash_logger(log_dir: Path | None = None) -> logging.Logger:
    """Return the real production crash logger, regardless of other handlers.

    The previous implementation only added a FileHandler when ``logger.handlers``
    was empty. A StreamHandler/NullHandler could therefore silently prevent the
    promised log file from ever being created. This helper verifies the target
    file handler itself and uses rotation + local owner-only permissions.
    """
    path = get_crash_log_path(log_dir)
    return _ensure_rotating_handler(logging.getLogger("codir_ia"), path, level=logging.ERROR)


def log_crash(logger: logging.Logger, message: str, *, exc_info=True, **context) -> None:
    safe_context = {k: redact_log_text(v) for k, v in context.items()}
    suffix = " " + json.dumps(safe_context, ensure_ascii=False, default=str) if safe_context else ""
    logger.error(redact_log_text(message) + suffix, exc_info=exc_info)


def flush_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        try:
            handler.flush()
        except Exception:
            pass

def log_event(logger: logging.Logger, level: str, module: str, message: str = "", *extra, **kwargs):
    """
    Patch v16.5.72.8 (audit ChatGPT round 23) — Sécurisation du logger.

    Le logger ne doit JAMAIS être un single point of failure pour le pipeline.
    Modifications :
      1. `message` devient optionnel (default "") — un appel avec kwargs seuls
         (ex: log_event(logger, "info", "mod", summary="x")) ne crashe plus,
         même si c'est un appel buggé legacy. Le bug est masqué dans le log
         mais le pipeline métier continue.
      2. Try/except interne global — si la sérialisation JSON, le file IO,
         ou le format du level échoue, on swallow plutôt que crasher.

    Cette double protection était nécessaire après le bug v16.5.72.7 où
    une exception métier dans build_facts_table_from_sources() était masquée
    par le crash du log_event() lui-même (TypeError missing 'message').
    """
    try:
        rec = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": (level or "INFO").upper(),
            "module": module or "unknown",
            "message": message or "",
            **kwargs,
        }
        # Patch v17.1-B2.1.2 — un appel legacy/buggé passant des positionnels en
        # trop (ex: log_event(l, "info", "mod", "evt", "detail")) ne doit pas
        # lever un TypeError au CALL (hors de portée du try/except interne) et
        # casser le pipeline. On absorbe les extras au lieu de crasher.
        if extra:
            rec["extra_positional"] = [str(a) for a in extra]
        line = json.dumps(rec, ensure_ascii=False, default=str)
        fn = getattr(logger, (level or "info").lower(), None)
        if callable(fn):
            fn(line)
        else:
            logger.info(line)
    except Exception:
        # Patch v16.5.72.8 — defensive : un crash dans le logging ne doit
        # jamais bubble jusqu'au pipeline métier. On accepte de perdre la
        # trace de log plutôt que de casser une session CoDIR.
        try:
            # Tentative ultime : log brut
            logger.warning(f"[log_event_self_error] level={level} module={module}")
        except Exception:
            pass
