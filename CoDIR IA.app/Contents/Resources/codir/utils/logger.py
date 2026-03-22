from __future__ import annotations
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone

def get_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("codir")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = TimedRotatingFileHandler(
        filename=str(log_dir / "codir.log.jsonl"),
        when="D",
        interval=1,
        backupCount=7,
        encoding="utf-8",
        utc=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger

def log_event(logger: logging.Logger, level: str, module: str, message: str, **kwargs):
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level.upper(),
        "module": module,
        "message": message,
        **kwargs,
    }
    line = json.dumps(rec, ensure_ascii=False)
    fn = getattr(logger, level.lower(), None)
    if callable(fn):
        fn(line)
    else:
        logger.info(line)
