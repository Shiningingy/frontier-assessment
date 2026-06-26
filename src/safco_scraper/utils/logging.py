"""Structured logging. Emits JSON lines (one event per line) to stdout and a
per-run log file, so logs are greppable and machine-parseable in production.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach any structured extras passed via logger.info(..., extra={"extra": {...}})
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", as_json: bool = True, log_dir: str | None = "logs") -> logging.Logger:
    logger = logging.getLogger("safco")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    stream = logging.StreamHandler(sys.stdout)
    if as_json:
        stream.setFormatter(JsonFormatter())
    else:
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(stream)

    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fh = logging.FileHandler(Path(log_dir) / f"run-{run_id}.log", encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        logger.addHandler(fh)

    return logger


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields: Any) -> None:
    """Helper to log a message with arbitrary structured fields."""
    logger.log(level, msg, extra={"extra": fields})
