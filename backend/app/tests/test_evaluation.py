from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import REPO_DIR, Settings
from app.models import Scenario
from app.services.evaluation.evaluator import EvaluationCreate, PolicyRef, run_evaluation
from app.services.evaluation.metrics import aggregate, percentile, rate
from app.services.evaluation.scenario_loader import load_scenario_files
from app.services.seed import seed_all
from app.tests.factories import make_settings

SCENARIOS = REPO_DIR / "scenarios"
REQUIRED_CATEGORIES = {
    "normal_read_only",
    "legitimate_approval",
    "unauthorized_tool",
    "protected_resource",
    "malformed_arguments",
    "execution_loop",
    "tool_failure",
    "policy_conflict",
    "stale_approval",
    "approval_replay",
    "untrusted_content",
    "over_restriction_probe",
}


@pytest.fixture()
def settings() -> Settings:
    return make_settings()


@pytest.fixture()
def seeded(session: Session) -> Session:
    seed_all(session, SCENARIOS)
    return session


def evaluate(session: Session, settings: Settings, *policies: str, **kw: Any) -> dict[str, Any]:
    request = EvaluationCreate(policies=[PolicyRef(policy_id=p) for p in policies], **kw)
    evaluation = run_evaluation(session, settings, request)
    assert evaluation.status == "completed", evaluation.error
    return evaluation.results


def test_fixtures_cover_every_required_category() -> None:
    files = load_scenario_files(SCENARIOS)
    assert {s.category for _, s in files} >= REQUIRED_CATEGORIES
    assert {src for src, _ in files} == {"demo", "adversarial"}


def test_baseline_policy_passes_every_fixture(seeded: Session, settings: Settings) -> None:
    results = evaluate(seeded, settings, "baseline")
    runs = results["runs"]["baseline@v1"]
    failing = {r["scenario_id"]: r["failures"] for r in runs if not r["passed"]}
    assert not failing, failing
    m = results["metrics"]["baseline@v1"]
    assert m["unsafe_action_block_rate"]["value"] == 1.0
    assert m["legitimate_false_block_rate"]["value"] == 0.0
    assert m["approval_enforcement_rate"]["value"] == 1.0
    assert m["audit_completeness_rate"]["value"] == 1.0
    assert m["replay_consistency_rate"]["value"] == 1.0


def test_strict_policy_measurably_disrupts_legitimate_work(seeded: Session, settings: Settings) -> None:
    results = evaluate(seeded, settings, "baseline", "strict-lockdown")
    base, strict = results["metrics"]["baseline@v1"], results["metrics"]["strict-lockdown@v1"]
    assert strict["legitimate_false_block_rate"]["value"] > base["legitimate_false_block_rate"]["value"]
    assert strict["task_completion_rate"]["value"] < base["task_completion_rate"]["value"]
    # The difference report cites real decision events for both policies.
    probe = next(d for d in results["differences"] if d["scenario_id"] == "customer-status-lookup")
    change = probe["changed_actions"][0]
    assert change["baseline@v1"]["event_id"] and change["strict-lockdown@v1"]["event_id"]


def test_permissive_policy_lets_unsafe_actions_through(seeded: Session, settings: Settings) -> None:
    results = evaluate(seeded, settings, "permissive-dev")
    m = results["metrics"]["permissive-dev@v1"]
    assert m["unsafe_action_block_rate"]["value"] < 1.0
    failed = {r["scenario_id"] for r in results["runs"]["permissive-dev@v1"] if not r["passed"]}
    assert {"protected-resource-modification", "conflicting-policy-rules"} <= failed


def test_approval_attacks_are_refused(seeded: Session, settings: Settings) -> None:
    results = evaluate(seeded, settings, "baseline", scenario_ids=["stale-approval", "approval-replay-attack"])
    attacks = [a for r in results["runs"]["baseline@v1"] for a in r["approval_attacks"]]
    assert {a["attack"] for a in attacks} == {"stale_approval", "approve_wrong_execution", "approve_tampered_action"}
    assert all(a["refused"] for a in attacks)
    codes = {a["error_code"] for a in attacks}
    assert codes == {"approval_expired", "approval_binding_mismatch"}


def test_evaluations_are_reproducible(seeded: Session, settings: Settings) -> None:
    def fingerprint(results: dict[str, Any]) -> list[Any]:
        return [
            (
                r["scenario_id"],
                r["status"],
                r["passed"],
                [(a["label"], a["decision"], a["executed"]) for a in r["actions"]],
            )
            for r in results["runs"]["baseline@v1"]
        ]

    assert fingerprint(evaluate(seeded, settings, "baseline")) == fingerprint(evaluate(seeded, settings, "baseline"))


def test_expectations_never_influence_decisions(seeded: Session, settings: Settings) -> None:
    """Flip every expectation label; the platform's decisions and outcomes must not change."""
    before = evaluate(seeded, settings, "baseline", include_replay_check=False)
    for row in seeded.scalars(select(Scenario)).all():
        flipped = dict(row.expectations)
        flipped["actions"] = {
            k: {**v, "safety": "legitimate" if v["safety"] == "unsafe" else "unsafe"}
            for k, v in row.expectations.get("actions", {}).items()
        }
        row.expectations = flipped
    seeded.commit()
    after = evaluate(seeded, settings, "baseline", include_replay_check=False)

    def decisions(res):
        return [[(a["label"], a["decision"], a["executed"]) for a in r["actions"]] for r in res["runs"]["baseline@v1"]]

    assert decisions(before) == decisions(after)
    assert (
        before["metrics"]["baseline@v1"]["scenario_pass_rate"] != after["metrics"]["baseline@v1"]["scenario_pass_rate"]
    )


def test_metric_helpers() -> None:
    assert rate(0, 0)["value"] is None
    assert rate(1, 4)["value"] == 0.25
    assert percentile([1, 2, 3, 4, 100], 50) == 3
    assert aggregate([])["runs"] == 0


def test_duplicate_policy_rejected(seeded: Session, settings: Settings) -> None:
    from app.core.errors import ValidationFailedError

    with pytest.raises(ValidationFailedError):
        run_evaluation(
            seeded,
            settings,
            EvaluationCreate(policies=[PolicyRef(policy_id="baseline"), PolicyRef(policy_id="baseline", version=1)]),
        )
