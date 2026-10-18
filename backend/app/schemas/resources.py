"""Response models. Internal fields (full pending arguments, sandbox internals, agent state)
are deliberately not exposed."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ToolOut(_Out):
    tool_id: str
    version: str
    name: str
    description: str
    category: str
    risk_level: str
    mutating: bool
    requires_approval: bool
    timeout_seconds: float
    implementation: str
    implementation_notes: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    mock_config: dict[str, Any]
    deterministic: bool
    sensitive_arguments: list[str]
    builtin: bool
    enabled: bool
    created_at: datetime


class PolicyVersionOut(_Out):
    policy_id: str
    version: int
    document: dict[str, Any]
    content_hash: str
    change_note: str
    created_at: datetime


class PolicySummaryOut(_Out):
    id: str
    name: str
    description: str
    latest_version: int
    builtin: bool
    created_at: datetime
    updated_at: datetime


class PolicyDetailOut(PolicySummaryOut):
    versions: list[PolicyVersionOut]


class ScenarioOut(_Out):
    scenario_id: str
    version: int
    name: str
    category: str
    description: str
    source: str
    spec: dict[str, Any]
    human_script: dict[str, Any]
    expectations: dict[str, Any]
    content_hash: str
    created_at: datetime


class ExecutionOut(_Out):
    id: str
    scenario_id: str
    scenario_version: int
    policy_id: str
    policy_version: int
    agent_type: str
    environment: str
    seed: int
    origin: str
    evaluation_id: str | None
    status: str
    status_reason: str
    task: str
    step_count: int
    tool_call_count: int
    event_count: int
    last_event_hash: str
    final_output: str
    active_ms: float
    pending_approval_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ExecutionDetailOut(ExecutionOut):
    spec: dict[str, Any]
    sandbox_effects: dict[str, Any]


class EventOut(_Out):
    id: str
    execution_id: str
    sequence: int
    event_type: str
    tool_id: str | None
    policy_version: str | None
    outcome: str
    data: dict[str, Any]
    timestamp: datetime
    prev_hash: str
    hash: str


class DecisionOut(_Out):
    id: str
    execution_id: str
    event_id: str
    policy_id: str
    policy_version: int
    tool_id: str
    tool_version: str | None
    arguments_redacted: dict[str, Any]
    action_hash: str
    outcome: str
    reason: str
    matched_rules: list[Any]
    deciding_rule: str
    latency_us: float
    created_at: datetime


class ApprovalOut(_Out):
    id: str
    execution_id: str
    decision_id: str
    step: int
    action_label: str
    action_hash: str
    tool_id: str
    tool_version: str
    arguments_redacted: dict[str, Any]
    risk_level: str
    reason: str
    context: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_note: str
    consumed_at: datetime | None


class ApprovalDecisionOut(BaseModel):
    approval: ApprovalOut
    execution: ExecutionOut
    idempotent_repeat: bool


class ReplayOut(_Out):
    id: str
    execution_id: str
    mode: str
    policy_id: str
    policy_version: int
    result: dict[str, Any]
    created_at: datetime


class EvaluationSummaryOut(_Out):
    id: str
    name: str
    status: str
    error: str
    created_at: datetime
    finished_at: datetime | None
    request: dict[str, Any]


class EvaluationOut(EvaluationSummaryOut):
    results: dict[str, Any]


class ReportOut(_Out):
    id: str
    kind: str
    subject_id: str
    title: str
    created_at: datetime
