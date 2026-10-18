from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Approval, AuditEvent, Execution
from app.services.agent_runtime.engine import ExecutionCreate, start_execution
from app.services.approval_engine.service import ApprovalDecisionRequest, decide
from app.services.replay.divergence import event_key, first_divergence
from app.services.replay.service import CompareRequest, ReplayCreate, compare_executions, create_replay
from app.services.seed import seed_all
from app.tests.factories import make_scenario, make_settings

READS = [
    {"label": "search", "tool_id": "kb.search", "arguments": {"query": "refund"}},
    {"label": "read", "tool_id": "docs.read", "arguments": {"doc_id": "refund-policy"}},
]
SEND = [
    {"label": "draft", "tool_id": "email.draft", "arguments": {"to": "ada@example.com", "subject": "Hi", "body": "x"}},
    {"label": "send", "tool_id": "email.send", "arguments": {"to": "ada@example.com", "subject": "Hi", "body": "x"}},
]


@pytest.fixture()
def settings() -> Settings:
    return make_settings()


@pytest.fixture()
def seeded(session: Session) -> Session:
    seed_all(session)
    make_scenario(session, "reads", READS)
    make_scenario(session, "send", SEND)
    make_scenario(
        session, "fx", [{"label": "fx", "tool_id": "ops.fetch_exchange_rate", "arguments": {"pair": "EUR/USD"}}]
    )
    make_scenario(
        session,
        "ticket",
        [{"label": "t", "tool_id": "ticket.create", "arguments": {"title": "Customer call", "priority": "p2"}}],
    )
    return session


def run(session: Session, settings: Settings, scenario: str, policy: str = "baseline") -> Execution:
    return start_execution(session, settings, ExecutionCreate(scenario_id=scenario, policy_id=policy))


def approve(session: Session, settings: Settings, execution: Execution) -> Execution:
    approval = session.scalars(select(Approval).where(Approval.execution_id == execution.id)).one()
    _, execution, _ = decide(
        session,
        settings,
        approval.id,
        "approve",
        ApprovalDecisionRequest(execution_id=execution.id, action_hash=approval.action_hash),
        operator="alice",
    )
    return execution


def counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(Execution)) or 0,
        session.scalar(select(func.count()).select_from(Approval)) or 0,
        session.scalar(select(func.count()).select_from(AuditEvent)) or 0,
    )


def test_recorded_mode_reconstructs_timeline(seeded: Session, settings: Settings) -> None:
    execution = run(seeded, settings, "reads")
    replay = create_replay(seeded, settings, ReplayCreate(execution_id=execution.id, mode="recorded"))
    frames = replay.result["frames"]
    assert len(frames) == execution.event_count
    assert all(f["source"] in {"recorded", "live"} for f in frames)
    assert frames[-1]["state"]["status"] == "completed"
    assert frames[-1]["state"]["executed"] == ["search", "read"]


def test_simulation_with_same_policy_does_not_diverge(seeded: Session, settings: Settings) -> None:
    execution = run(seeded, settings, "reads")
    replay = create_replay(seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate"))
    assert replay.result["divergence"]["diverged"] is False
    sources = {f["source"] for f in replay.result["frames"] if f["event_type"] == "tool.result"}
    assert sources == {"reconstructed"}
    assert replay.result["final_status"] == "completed"


def test_simulation_is_deterministic(seeded: Session, settings: Settings) -> None:
    execution = run(seeded, settings, "send")
    approve(seeded, settings, execution)
    a = create_replay(seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate"))
    b = create_replay(seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate"))

    def key(r):
        return [
            event_key(SimpleNamespace(**{k: f[k] for k in ("event_type", "tool_id", "outcome", "data")}))
            for f in r.result["frames"]
        ]

    assert key(a) == key(b)


def test_replay_reuses_recorded_approval_and_never_repeats_side_effects(seeded: Session, settings: Settings) -> None:
    execution = approve(seeded, settings, run(seeded, settings, "send"))
    assert execution.status == "completed"
    before = counts(seeded)
    outbox_before = list(execution.sandbox_state["outbox"])
    replay = create_replay(seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate"))
    assert replay.result["divergence"]["diverged"] is False, replay.result["divergence"]
    granted = [f for f in replay.result["frames"] if f["event_type"] == "approval.granted"]
    assert granted and granted[0]["data"]["source"] == "recorded"
    assert counts(seeded) == before  # no new executions, approvals or audit rows
    seeded.refresh(execution)
    assert execution.sandbox_state["outbox"] == outbox_before
    assert replay.result["sandbox_effects"]["outbox"] == 1  # only inside the isolated replay sandbox


def test_policy_comparison_finds_first_divergence(seeded: Session, settings: Settings) -> None:
    execution = run(seeded, settings, "reads")
    replay = create_replay(
        seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate", policy_id="strict-lockdown")
    )
    div = replay.result["divergence"]
    assert div["diverged"] is True
    assert div["left"]["event_type"] == "policy.evaluated" and div["left"]["label"] == "search"
    assert "builtin:default_effect" in div["explanation"]
    assert replay.result["final_status"] == "blocked"
    assert replay.policy_id == "strict-lockdown"


def test_missing_recorded_approval_is_unavailable_unless_what_if(seeded: Session, settings: Settings) -> None:
    execution = run(seeded, settings, "ticket")  # allowed under baseline, no approval recorded
    strict = create_replay(
        seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate", policy_id="strict-lockdown")
    )
    assert strict.result["final_status"] == "blocked"
    assert "replay_unresolvable" in strict.result["status_reason"]
    assert strict.result["unavailable_frames"]
    what_if = create_replay(
        seeded,
        settings,
        ReplayCreate(
            execution_id=execution.id, mode="simulate", policy_id="strict-lockdown", approval_strategy="approve_all"
        ),
    )
    assert what_if.result["final_status"] == "completed"


def test_nondeterministic_tool_uses_recorded_output(seeded: Session, settings: Settings) -> None:
    execution = run(seeded, settings, "fx")
    replay = create_replay(seeded, settings, ReplayCreate(execution_id=execution.id, mode="simulate"))
    result = next(f for f in replay.result["frames"] if f["event_type"] == "tool.result")
    assert result["source"] == "recorded"
    assert replay.result["divergence"]["diverged"] is False


def test_two_live_runs_of_nondeterministic_tool_can_diverge(seeded: Session, settings: Settings) -> None:
    runs = [run(seeded, settings, "fx") for _ in range(5)]
    comparisons = [
        compare_executions(seeded, CompareRequest(left_execution_id=runs[0].id, right_execution_id=r.id))
        for r in runs[1:]
    ]
    diverged = [c for c in comparisons if c["divergence"]["diverged"]]
    assert diverged, "unseeded jitter should produce at least one differing output in 5 runs"
    assert diverged[0]["divergence"]["left"]["event_type"] == "tool.result"


def test_compare_executions_under_two_policies(seeded: Session, settings: Settings) -> None:
    a, b = run(seeded, settings, "reads"), run(seeded, settings, "reads", policy="strict-lockdown")
    result = compare_executions(seeded, CompareRequest(left_execution_id=a.id, right_execution_id=b.id))
    assert result["same_scenario"]
    assert result["divergence"]["diverged"]
    assert result["divergence"]["left"]["event_id"] and result["divergence"]["right"]["event_id"]
    assert [r["decision"] for r in result["tool_calls"]["left"]] == ["allow", "allow"]
    assert result["tool_calls"]["right"][0]["decision"] == "deny"


def test_first_divergence_prefix_and_identical() -> None:
    def ev(seq: int, t: str, outcome: str = "ok") -> SimpleNamespace:
        return SimpleNamespace(sequence=seq, event_type=t, tool_id=None, outcome=outcome, data={})

    a = [ev(1, "execution.created"), ev(2, "execution.started"), ev(3, "execution.completed", "completed")]
    assert first_divergence(a, list(a))["diverged"] is False
    short = first_divergence(a, a[:2])
    assert short["diverged"] and short["index"] == 2 and short["right"] is None
    # resume events are ignored, so a paused run and an unpaused simulation still compare equal
    paused = [a[0], a[1], ev(3, "execution.resumed"), ev(4, "execution.completed", "completed")]
    assert first_divergence(a, paused)["diverged"] is False
