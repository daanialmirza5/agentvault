"""Runs a mock tool against a copy of the sandbox with a hard wall-clock timeout.

The tool works on a deep copy of the sandbox; the copy is only adopted when the tool
succeeds and its output validates. A timed-out or failed tool therefore cannot leave a
half-applied mutation behind. Timed-out worker threads are abandoned (Python threads
cannot be killed); the built-in mocks bound their own run time to two seconds.
"""

from __future__ import annotations

import copy
import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.tool_registry.implementations import IMPLEMENTATIONS, ToolContext, ToolError
from app.services.tool_registry.registry import ToolSpec, validate_against

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agentvault-tool")


@dataclass
class ToolRunResult:
    status: Literal["succeeded", "failed", "timeout"]
    output: dict[str, Any] | None = None
    error: str = ""
    duration_ms: float = 0.0
    sandbox: dict[str, Any] = field(default_factory=dict)


def tool_rng(seed: int, step: int, tool_id: str) -> random.Random:
    """Deterministic per-call RNG: same seed, step and tool always give the same stream."""
    return random.Random(f"{seed}:{step}:{tool_id}")


def run_tool(
    spec: ToolSpec, arguments: dict[str, Any], sandbox: dict[str, Any], *, seed: int, step: int
) -> ToolRunResult:
    impl = IMPLEMENTATIONS.get(spec.implementation)
    if impl is None:
        return ToolRunResult(status="failed", error=f"no implementation '{spec.implementation}'", sandbox=sandbox)
    working = copy.deepcopy(sandbox)
    ctx = ToolContext(sandbox=working, rng=tool_rng(seed, step, spec.tool_id), step=step, config=dict(spec.mock_config))
    started = time.perf_counter()
    future = _POOL.submit(impl, copy.deepcopy(arguments), ctx)
    try:
        output = future.result(timeout=spec.timeout_seconds)
    except FutureTimeout:
        return ToolRunResult(
            status="timeout",
            error=f"tool exceeded its {spec.timeout_seconds}s timeout",
            duration_ms=_ms(started),
            sandbox=sandbox,
        )
    except ToolError as exc:
        return ToolRunResult(status="failed", error=str(exc)[:500], duration_ms=_ms(started), sandbox=sandbox)
    except Exception as exc:  # a bug in a mock must never crash the engine
        return ToolRunResult(
            status="failed",
            error=f"internal tool error: {type(exc).__name__}",
            duration_ms=_ms(started),
            sandbox=sandbox,
        )
    problems = validate_against(spec.output_schema, output)
    if problems:
        return ToolRunResult(
            status="failed",
            error="output failed schema validation: " + "; ".join(problems),
            duration_ms=_ms(started),
            sandbox=sandbox,
        )
    return ToolRunResult(status="succeeded", output=output, duration_ms=_ms(started), sandbox=working)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
