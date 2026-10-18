"""Structured logging with request IDs. Log records never include request bodies."""

from __future__ import annotations

import contextvars
import json
import logging
import re
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_BEARER = re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": _BEARER.sub("Bearer [REDACTED]", record.getMessage()),
        }
        for key in ("method", "path", "status", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("agentvault")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


logger = logging.getLogger("agentvault")
