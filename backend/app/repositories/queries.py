"""Read-side queries: filtering, pagination and dashboard aggregates."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import Approval, AuditEvent, Evaluation, Execution, PolicyDecisionRecord, Replay, Report, Scenario

T = TypeVar("T")


def paginate(session: Session, query: Select[T], limit: int, offset: int) -> tuple[list[T], int]:
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    return list(session.scalars(query.limit(limit).offset(offset)).all()), total


def executions_query(
    *,
    status: str | None = None,
    scenario_id: str | None = None,
    policy_id: str | None = None,
    origin: str | None = None,
    evaluation_id: str | None = None,
    q: str | None = None,
) -> Select[Execution]:
    query = select(Execution)
    if status:
        query = query.where(Execution.status == status)
    if scenario_id:
        query = query.where(Execution.scenario_id == scenario_id)
    if policy_id:
        query = query.where(Execution.policy_id == policy_id)
    if origin:
        query = query.where(Execution.origin == origin)
    if evaluation_id:
        query = query.where(Execution.evaluation_id == evaluation_id)
    if q:
        like = f"%{q[:80]}%"
        query = query.where(or_(Execution.id.like(like), Execution.task.like(like), Execution.scenario_id.like(like)))
    return query.order_by(Execution.created_at.desc(), Execution.id)


def events_query(
    *,
    execution_id: str | None = None,
    event_type: str | None = None,
    tool_id: str | None = None,
    outcome: str | None = None,
) -> Select[AuditEvent]:
    query = select(AuditEvent)
    if execution_id:
        query = query.where(AuditEvent.execution_id == execution_id)
    if event_type:
        query = (
            query.where(AuditEvent.event_type.like(f"{event_type[:40]}%"))
            if event_type.endswith(".")
            else query.where(AuditEvent.event_type == event_type)
        )
    if tool_id:
        query = query.where(AuditEvent.tool_id == tool_id)
    if outcome:
        query = query.where(AuditEvent.outcome == outcome)
    if execution_id:
        return query.order_by(AuditEvent.sequence)
    return query.order_by(AuditEvent.timestamp.desc(), AuditEvent.sequence.desc())


def decisions_query(
    *, execution_id: str | None = None, outcome: str | None = None, tool_id: str | None = None
) -> Select[PolicyDecisionRecord]:
    query = select(PolicyDecisionRecord)
    if execution_id:
        query = query.where(PolicyDecisionRecord.execution_id == execution_id)
    if outcome:
        query = query.where(PolicyDecisionRecord.outcome == outcome)
    if tool_id:
        query = query.where(PolicyDecisionRecord.tool_id == tool_id)
    return query.order_by(PolicyDecisionRecord.created_at.desc())


def dashboard_stats(session: Session) -> dict[str, Any]:
    def count(model: Any, *where: Any) -> int:
        return session.scalar(select(func.count()).select_from(model).where(*where)) or 0

    status_rows = session.execute(select(Execution.status, func.count()).group_by(Execution.status)).all()
    decision_rows = session.execute(
        select(PolicyDecisionRecord.outcome, func.count()).group_by(PolicyDecisionRecord.outcome)
    ).all()
    rule_rows = session.execute(
        select(PolicyDecisionRecord.deciding_rule, PolicyDecisionRecord.outcome, func.count())
        .group_by(PolicyDecisionRecord.deciding_rule, PolicyDecisionRecord.outcome)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    by_policy = session.execute(
        select(PolicyDecisionRecord.policy_id, PolicyDecisionRecord.outcome, func.count()).group_by(
            PolicyDecisionRecord.policy_id, PolicyDecisionRecord.outcome
        )
    ).all()
    recent = session.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(8)).all()
    evaluations = session.scalars(select(Evaluation).order_by(Evaluation.created_at.desc()).limit(5)).all()
    policy_summary: dict[str, dict[str, int]] = {}
    for pid, outcome, n in by_policy:
        policy_summary.setdefault(pid, {"allow": 0, "deny": 0, "require_approval": 0})[outcome] = n
    return {
        "executions": {
            "total": count(Execution),
            "by_status": {s: n for s, n in status_rows},
            "manual": count(Execution, Execution.origin == "manual"),
            "evaluation": count(Execution, Execution.origin == "evaluation"),
        },
        "decisions": {o: n for o, n in decision_rows},
        "blocked_actions": count(AuditEvent, AuditEvent.event_type == "tool.blocked"),
        "tool_failures": count(AuditEvent, AuditEvent.event_type == "tool.failed"),
        "pending_approvals": count(Approval, Approval.status == "pending"),
        "approvals_by_status": {
            s: n for s, n in session.execute(select(Approval.status, func.count()).group_by(Approval.status)).all()
        },
        "top_rules": [{"rule": r, "outcome": o, "count": n} for r, o, n in rule_rows],
        "policy_summary": policy_summary,
        "recent_executions": [
            {
                "id": e.id,
                "scenario_id": e.scenario_id,
                "policy": f"{e.policy_id}@v{e.policy_version}",
                "status": e.status,
                "origin": e.origin,
                "created_at": e.created_at.isoformat(),
                "tool_calls": e.tool_call_count,
            }
            for e in recent
        ],
        "recent_evaluations": [
            {
                "id": ev.id,
                "name": ev.name,
                "status": ev.status,
                "created_at": ev.created_at.isoformat(),
                "pass_rates": {
                    label: m["scenario_pass_rate"]["value"] for label, m in (ev.results.get("metrics") or {}).items()
                },
            }
            for ev in evaluations
        ],
        "counts": {"scenarios": count(Scenario), "replays": count(Replay), "reports": count(Report)},
    }
