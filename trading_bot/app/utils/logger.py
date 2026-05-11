"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import logging
import re
import sys
from typing import Any

try:
    # python-json-logger >= 3.x
    from pythonjsonlogger.json import JsonFormatter as _BaseFormatter
except ImportError:  # pragma: no cover - fallback for older versions
    from pythonjsonlogger.jsonlogger import JsonFormatter as _BaseFormatter  # type: ignore


SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|api[_-]?secret|token|secret|password)=([^\s,&]+)", re.IGNORECASE),
    re.compile(r"\"(api[_-]?key|api[_-]?secret|token|secret|password)\"\s*:\s*\"([^\"]+)\"", re.IGNORECASE),
]


def _redact(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text = pat.sub(lambda m: f"{m.group(1)}=***REDACTED***", text)
    return text


class RedactingFormatter(_BaseFormatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        return _redact(super().format(record))


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: str, event: str, **fields: Any) -> None:
    getattr(logger, level.lower())(event, extra={"event": event, **fields})
