"""Redaction of sensitive values before they are persisted in audit records or logs.

Redaction is key-based: any mapping key that looks like a credential, plus any key a tool
declares in ``sensitive_arguments``, is replaced with a marker. Values are never inspected
heuristically, so free text containing secrets is *not* detected (documented limitation).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|credential|ssn|card[_-]?number|cvv)",
    re.IGNORECASE,
)
_MAX_DEPTH = 12


def redact(value: Any, extra_keys: Iterable[str] = (), _depth: int = 0) -> Any:
    extra = {k.lower() for k in extra_keys}
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            k = str(key)
            if k.lower() in extra or _SENSITIVE_KEY.search(k):
                out[k] = REDACTED
            else:
                out[k] = redact(item, extra, _depth + 1)
        return out
    if isinstance(value, list | tuple):
        return [redact(v, extra, _depth + 1) for v in value]
    return value
