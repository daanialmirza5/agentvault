"""The execution event schema shared by live executions, replays and evaluations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    EXECUTION_CREATED = "execution.created"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_RESUMED = "execution.resumed"
    AGENT_ACTION_PROPOSED = "agent.action_proposed"
    TOOL_REQUESTED = "tool.requested"
    ARGUMENTS_VALIDATED = "tool.arguments_validated"
    ARGUMENTS_REJECTED = "tool.arguments_rejected"
    POLICY_EVALUATED = "policy.evaluated"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_EXPIRED = "approval.expired"
    APPROVAL_BINDING_MISMATCH = "approval.binding_mismatch"
    TOOL_EXECUTED = "tool.executed"
    TOOL_RESULT = "tool.result"
    TOOL_FAILED = "tool.failed"
    TOOL_BLOCKED = "tool.blocked"
    GUARD_TRIGGERED = "guard.triggered"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_BLOCKED = "execution.blocked"
    EXECUTION_CANCELLED = "execution.cancelled"


TERMINAL_EVENT_FOR_STATUS = {
    "completed": EventType.EXECUTION_COMPLETED,
    "failed": EventType.EXECUTION_FAILED,
    "blocked": EventType.EXECUTION_BLOCKED,
    "cancelled": EventType.EXECUTION_CANCELLED,
}


@dataclass
class EventRecord:
    """A backend-neutral event produced by the runner before it is persisted."""

    event_type: EventType
    outcome: str
    data: dict[str, Any] = field(default_factory=dict)
    tool_id: str | None = None
    policy_version: str | None = None
