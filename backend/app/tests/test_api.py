from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import REPO_DIR
from app.main import create_app
from app.tests.factories import make_settings


def _client(tmp_path: Path, **overrides: Any) -> TestClient:
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
        seed_on_startup=True,
        scenarios_dir=REPO_DIR / "scenarios",
        approval_sweep_interval_seconds=0,
        **overrides,
    )
    return TestClient(create_app(settings))


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path) as c:
        yield c


def launch(client: TestClient, scenario: str, policy: str = "baseline") -> dict[str, Any]:
    r = client.post("/api/v1/executions", json={"scenario_id": scenario, "policy_id": policy})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.e2e
def test_end_to_end_approval_replay_compare_and_export(client: TestClient) -> None:
    # 1-4. Launch a deterministic scenario; it requests tools, is evaluated and pauses for approval.
    execution = launch(client, "enterprise-follow-up")
    assert execution["status"] == "waiting_for_approval"
    events = client.get(f"/api/v1/executions/{execution['id']}/events").json()["items"]
    types = [e["event_type"] for e in events]
    assert {"tool.requested", "policy.evaluated", "approval.requested"} <= set(types)
    queue = client.get("/api/v1/approvals", params={"status": "pending"}).json()["items"]
    approval = next(a for a in queue if a["execution_id"] == execution["id"])
    assert approval["tool_id"] == "email.send" and approval["risk_level"] == "high"
    assert approval["context"]["agent_claims"] == {"safe": True}

    # 5-6. Approve the exact action; the execution resumes and completes.
    r = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"execution_id": execution["id"], "action_hash": approval["action_hash"], "note": "ok"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["execution"]["status"] == "completed"
    detail = client.get(f"/api/v1/executions/{execution['id']}").json()
    assert len(detail["sandbox_effects"]["outbox"]) == 1

    # 7. Inspect the audit trail.
    verify = client.get(f"/api/v1/executions/{execution['id']}/audit/verify").json()
    assert verify["chain"]["valid"] and verify["completeness"]["complete"]
    decisions = client.get(f"/api/v1/executions/{execution['id']}/decisions").json()
    assert [d["outcome"] for d in decisions] == ["allow", "allow", "require_approval"]

    # 8. Replay the recorded execution.
    replay = client.post("/api/v1/replays", json={"execution_id": execution["id"], "mode": "simulate"}).json()
    assert replay["result"]["divergence"]["diverged"] is False

    # 9. Compare policy versions on the same scenarios.
    evaluation = client.post(
        "/api/v1/evaluations",
        json={
            "scenario_ids": ["customer-status-lookup", "protected-resource-modification"],
            "policies": [{"policy_id": "baseline"}, {"policy_id": "strict-lockdown"}],
        },
    ).json()
    assert evaluation["status"] == "completed"
    assert evaluation["results"]["differences"]

    # 10. Export reports.
    for kind, subject in (
        ("execution", execution["id"]),
        ("evaluation", evaluation["id"]),
        ("replay", replay["id"]),
        ("policy_comparison", "baseline@v1..strict-lockdown@v1"),
    ):
        rep = client.post("/api/v1/reports", json={"kind": kind, "subject_id": subject})
        assert rep.status_code == 201, rep.text
        md = client.get(f"/api/v1/reports/{rep.json()['id']}", params={"format": "markdown", "download": True})
        assert md.status_code == 200 and md.text.startswith("# ")
        assert "attachment" in md.headers["content-disposition"]
        js = client.get(f"/api/v1/reports/{rep.json()['id']}").json()
        assert js["kind"] == kind


def test_reject_via_api_never_executes(client: TestClient) -> None:
    execution = launch(client, "stale-approval")
    approval = client.get("/api/v1/approvals", params={"execution_id": execution["id"]}).json()["items"][0]
    r = client.post(
        f"/api/v1/approvals/{approval['id']}/reject",
        json={"execution_id": execution["id"], "action_hash": approval["action_hash"]},
    )
    assert r.json()["execution"]["status"] == "blocked"
    assert client.get(f"/api/v1/executions/{execution['id']}").json()["sandbox_effects"]["outbox"] == []
    again = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"execution_id": execution["id"], "action_hash": approval["action_hash"]},
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "approval_rejected"


def test_wrong_binding_is_409_with_error_envelope(client: TestClient) -> None:
    a = launch(client, "stale-approval")
    b = launch(client, "stale-approval")
    approval = client.get("/api/v1/approvals", params={"execution_id": a["id"]}).json()["items"][0]
    r = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"execution_id": b["id"], "action_hash": approval["action_hash"]},
    )
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "approval_binding_mismatch" and err["request_id"] == r.headers["x-request-id"]


def test_cancel_execution(client: TestClient) -> None:
    execution = launch(client, "stale-approval")
    r = client.post(f"/api/v1/executions/{execution['id']}/cancel", json={"reason": "not needed"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/executions/{execution['id']}/cancel").status_code == 409


def test_unauthorized_tool_is_denied_over_api(client: TestClient) -> None:
    execution = launch(client, "unauthorized-tool-call")
    events = client.get(f"/api/v1/executions/{execution['id']}/events", params={"event_type": "tool.blocked"}).json()
    assert {e["outcome"] for e in events["items"]} == {"denied", "unknown_tool"}


def test_tools_policies_scenarios_listing_and_registration(client: TestClient) -> None:
    tools = client.get("/api/v1/tools", params={"limit": 100}).json()
    assert tools["total"] >= 12 and all("input_schema" in t for t in tools["items"])
    assert (
        client.get("/api/v1/tools", params={"risk_level": "critical"}).json()["items"][0]["tool_id"]
        == "admin.export_all_customers"
    )
    new_tool = {
        "tool_id": "weather.lookup",
        "name": "Weather",
        "category": "info",
        "risk_level": "low",
        "mutating": False,
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
        "mock_config": {"response": {"forecast": "sunny"}},
    }
    assert client.post("/api/v1/tools", json=new_tool).status_code == 201
    assert client.post("/api/v1/tools", json=new_tool).status_code == 409
    assert client.get("/api/v1/tools/weather.lookup").json()[0]["version"] == "1.0.0"
    policies = client.get("/api/v1/policies").json()
    assert {p["id"] for p in policies["items"]} >= {"baseline", "strict-lockdown", "permissive-dev"}
    scenarios = client.get("/api/v1/scenarios", params={"limit": 100}).json()
    assert scenarios["total"] == 12


def test_policy_create_version_validate_compare_simulate(client: TestClient) -> None:
    doc = {
        "default_effect": "deny",
        "rules": [{"id": "allow-reads", "effect": "allow", "match": {"operations": ["read"]}}],
    }
    r = client.post("/api/v1/policies", json={"id": "team-policy", "name": "Team", "document": doc})
    assert r.status_code == 201 and r.json()["latest_version"] == 1
    doc["rules"].append({"id": "deny-crm", "effect": "deny", "match": {"categories": ["crm"]}})
    v2 = client.post("/api/v1/policies/team-policy/versions", json={"document": doc, "base_version": 1})
    assert v2.status_code == 201 and v2.json()["version"] == 2
    stale = client.post("/api/v1/policies/team-policy/versions", json={"document": doc, "base_version": 1})
    assert stale.status_code == 409
    detail = client.get("/api/v1/policies/team-policy").json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    issues = client.post("/api/v1/policies/validate", json={"document": doc}).json()
    assert any(i["code"] == "overlapping_rules" for i in issues["issues"])
    cmp_ = client.post(
        "/api/v1/policies/compare",
        json={"left": {"policy_id": "team-policy", "version": 1}, "right": {"policy_id": "team-policy", "version": 2}},
    ).json()
    assert [rule["id"] for rule in cmp_["diff"]["added"]] == ["deny-crm"]
    sim = client.post(
        "/api/v1/policies/simulate",
        json={
            "policy": {"policy_id": "team-policy"},
            "tool_id": "crm.get_customer",
            "arguments": {"customer_id": "CUST-1001"},
        },
    ).json()
    assert sim["decision"]["outcome"] == "deny"
    bad = client.post("/api/v1/policies/validate", json={"document": {"rules": [{"id": "x", "effect": "maybe"}]}})
    assert bad.status_code == 422


def test_pagination_and_filters(client: TestClient) -> None:
    for _ in range(3):
        launch(client, "support-faq-lookup")
    page = client.get("/api/v1/executions", params={"limit": 2, "offset": 0, "status": "completed"}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["limit"] == 2
    page2 = client.get("/api/v1/executions", params={"limit": 2, "offset": 2, "status": "completed"}).json()
    assert len(page2["items"]) == 1
    assert client.get("/api/v1/executions", params={"limit": 500}).status_code == 422
    events = client.get("/api/v1/audit/events", params={"event_type": "tool.", "limit": 5}).json()
    assert events["total"] > 5 and all(e["event_type"].startswith("tool.") for e in events["items"])


def test_error_envelope_and_no_input_echo(client: TestClient) -> None:
    missing = client.get("/api/v1/executions/exe_missing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    secret = "sk-very-secret-value"
    r = client.post("/api/v1/executions", json={"scenario_id": "x", "api_key": secret})
    assert r.status_code == 422 and secret not in r.text
    assert client.post("/api/v1/executions", json={"scenario_id": "nope"}).status_code == 404


def test_request_size_limit(tmp_path: Path) -> None:
    with _client(tmp_path, max_request_bytes=2048) as c:
        r = c.post(
            "/api/v1/policies/validate", content=b"{" + b" " * 5000 + b"}", headers={"content-type": "application/json"}
        )
        assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


def test_request_ids(client: TestClient) -> None:
    assert len(client.get("/api/v1/health").headers["x-request-id"]) >= 8
    assert (
        client.get("/api/v1/health", headers={"x-request-id": "trace-12345678"}).headers["x-request-id"]
        == "trace-12345678"
    )
    assert client.get("/api/v1/health", headers={"x-request-id": "bad id!"}).headers["x-request-id"] != "bad id!"


def test_readiness_and_stats(client: TestClient) -> None:
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200 and ready.json()["checks"]["migrations_current"]
    launch(client, "unauthorized-tool-call")
    stats = client.get("/api/v1/stats").json()
    assert stats["executions"]["total"] == 1 and stats["blocked_actions"] == 2


def test_readiness_fails_without_seed_data(tmp_path: Path) -> None:
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
        seed_on_startup=False,
        approval_sweep_interval_seconds=0,
    )
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/v1/ready")
        assert r.status_code == 503 and r.json()["status"] == "not_ready"


def test_bearer_token_required_for_mutations_when_configured(tmp_path: Path) -> None:
    with _client(tmp_path, api_token="s3cret-token") as c:
        assert c.get("/api/v1/health").status_code == 200  # liveness/readiness stay public
        assert c.get("/api/v1/ready").status_code == 200
        assert c.get("/api/v1/tools").status_code == 401  # audit data is protected when a token is set
        assert c.get("/api/v1/stats").status_code == 401
        assert c.get("/api/v1/tools", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
        body = {"scenario_id": "support-faq-lookup"}
        assert c.post("/api/v1/executions", json=body).status_code == 401
        assert c.post("/api/v1/executions", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = c.post("/api/v1/executions", json=body, headers={"Authorization": "Bearer s3cret-token"})
        assert ok.status_code == 201


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    good = client.options(
        "/api/v1/tools", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert good.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.options(
        "/api/v1/tools", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )
    assert "access-control-allow-origin" not in evil.headers


def test_interrupted_executions_are_recovered_on_startup(tmp_path: Path) -> None:
    from sqlalchemy import update

    from app.core import db
    from app.models import Execution

    with _client(tmp_path) as c:
        execution = launch(c, "support-faq-lookup")
        with db.session_factory()() as s:
            s.execute(update(Execution).where(Execution.id == execution["id"]).values(status="running"))
            s.commit()
    with _client(tmp_path) as c:
        detail = c.get(f"/api/v1/executions/{execution['id']}").json()
        assert detail["status"] == "failed" and "interrupted" in detail["status_reason"]
