"""Audit completeness: structural invariants every execution's event stream must satisfy."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.models.execution import TERMINAL_STATUSES
from app.services.audit.events import TERMINAL_EVENT_FOR_STATUS, EventType


class EventLike(Protocol):
    sequence: int
    event_type: str
    outcome: str
    data: dict[str, Any]


def check_completeness(events: Sequence[EventLike], status: str) -> dict[str, Any]:
    """Return {"complete": bool, "problems": [...]} for one execution.

    Invariants:
      1. The stream starts with ``execution.created``.
      2. Every ``tool.requested`` step has a ``policy.evaluated`` event for the same step.
      3. Every ``tool.executed`` step was authorised: an ``allow`` policy decision, or a
         ``require_approval`` decision followed by ``approval.granted`` for that step.
      4. No step is executed after a deny, rejection or expiry.
      5. Every ``approval.requested`` is resolved unless the execution is still waiting
         (or was cancelled while waiting).
      6. A terminal execution ends with exactly one matching terminal event.
    """
    problems: list[str] = []
    types = [e.event_type for e in events]
    if not events or types[0] != EventType.EXECUTION_CREATED:
        problems.append("stream does not start with execution.created")

    by_step: dict[int, dict[str, Any]] = {}
    for e in events:
        step = e.data.get("step")
        if not isinstance(step, int):
            continue
        s = by_step.setdefault(step, {"types": [], "decision": None})
        s["types"].append(e.event_type)
        if e.event_type == EventType.POLICY_EVALUATED:
            s["decision"] = e.outcome

    for step, s in sorted(by_step.items()):
        t = s["types"]
        if EventType.TOOL_REQUESTED in t and EventType.POLICY_EVALUATED not in t:
            problems.append(f"step {step}: tool requested without a policy decision")
        if EventType.TOOL_EXECUTED in t:
            if s["decision"] == "allow":
                pass
            elif s["decision"] == "require_approval":
                if EventType.APPROVAL_GRANTED not in t or t.index(EventType.APPROVAL_GRANTED) > t.index(EventType.TOOL_EXECUTED):
                    problems.append(f"step {step}: executed without a prior approval.granted")
            else:
                problems.append(f"step {step}: executed although the policy decision was '{s['decision']}'")
            for bad in (EventType.APPROVAL_REJECTED, EventType.APPROVAL_EXPIRED):
                if bad in t:
                    problems.append(f"step {step}: executed despite {bad}")
        if EventType.APPROVAL_REQUESTED in t:
            resolved = any(x in t for x in (EventType.APPROVAL_GRANTED, EventType.APPROVAL_REJECTED,
                                            EventType.APPROVAL_EXPIRED))
            if not resolved and status not in {"waiting_for_approval", "cancelled"}:
                problems.append(f"step {step}: approval requested but never resolved")

    if status in TERMINAL_STATUSES:
        expected = TERMINAL_EVENT_FOR_STATUS[status]
        terminal = [x for x in types if x in TERMINAL_EVENT_FOR_STATUS.values()]
        if terminal != [expected]:
            problems.append(f"expected exactly one terminal event '{expected}', found {terminal}")
        elif types[-1] != expected:
            problems.append("terminal event is not the last event")
    return {"complete": not problems, "problems": problems}
