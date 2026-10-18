from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.services.policy_engine.analysis import decision_matrix, diff_documents, validate_policy
from app.services.policy_engine.defaults import BASELINE, DEFAULT_POLICIES, PERMISSIVE, STRICT
from app.services.policy_engine.engine import evaluate
from app.services.policy_engine.model import PolicyContext, PolicyDocument
from app.services.policy_engine.store import (
    PolicyVersionCreate,
    create_version,
    get_version,
    load_document,
    seed_policies,
)
from app.services.tool_registry.builtin_tools import BUILTIN_TOOLS
from app.services.tool_registry.registry import ToolRegistry, ToolSpec

REGISTRY = ToolRegistry(ToolSpec(**{**t, "builtin": True}) for t in BUILTIN_TOOLS)
SANDBOX = PolicyContext(environment="sandbox", scenario_id="test")


def _decide(policy: dict[str, Any], tool_id: str, args: dict[str, Any], ctx: PolicyContext = SANDBOX) -> Any:
    doc = PolicyDocument.model_validate(policy["document"])
    tool = REGISTRY.get(tool_id)
    errors = REGISTRY.validate_arguments(tool, args) if tool else []
    return evaluate(doc, policy_id=policy["id"], policy_version=1, tool_id=tool_id, tool=tool,
                    arguments=args, argument_errors=errors, context=ctx)


def test_low_risk_read_is_allowed() -> None:
    d = _decide(BASELINE, "docs.read", {"doc_id": "refund-policy"})
    assert d.outcome == "allow" and d.deciding_rule == "allow-low-risk-reads"


def test_drafting_allowed_sending_requires_approval() -> None:
    assert _decide(BASELINE, "email.draft", {"to": "a@example.com", "subject": "s", "body": "b"}).outcome == "allow"
    assert _decide(BASELINE, "email.send", {"to": "a@example.com", "subject": "s", "body": "b"}).outcome == "require_approval"


def test_unknown_tool_denied_even_under_default_allow() -> None:
    d = _decide(PERMISSIVE, "shell.exec", {"cmd": "rm -rf /"})
    assert d.outcome == "deny" and d.deciding_rule == "builtin:unknown_tool"


def test_malformed_arguments_denied_before_rules() -> None:
    d = _decide(PERMISSIVE, "email.draft", {"to": "x"})
    assert d.outcome == "deny" and d.deciding_rule == "builtin:invalid_arguments"


def test_protected_resource_denied_by_argument_rule() -> None:
    d = _decide(BASELINE, "crm.update_record", {"customer_id": "CUST-1002", "field": "credit_limit", "value": "1"})
    assert d.outcome == "deny" and d.deciding_rule == "deny-protected-crm-fields"
    ok = _decide(BASELINE, "crm.update_record", {"customer_id": "CUST-1002", "field": "phone", "value": "1"})
    assert ok.outcome == "require_approval"


def test_conflicting_rules_resolve_deny_overrides() -> None:
    d = _decide(BASELINE, "ticket.create", {"title": "Outage", "priority": "p0"})
    assert d.outcome == "deny"
    assert {r.rule_id for r in d.matched_rules} == {"allow-support-tickets", "deny-agent-p0-tickets"}
    assert any("deny-overrides" in line for line in d.trace)


def test_priority_only_orders_rules_with_the_same_effect() -> None:
    doc = PolicyDocument.model_validate({"default_effect": "deny", "rules": [
        {"id": "allow-first", "effect": "allow", "priority": 0, "match": {}},
        {"id": "deny-late", "effect": "deny", "priority": 9999, "match": {"tool_ids": ["kb.*"]}},
    ]})
    tool = REGISTRY.get("kb.search")
    d = evaluate(doc, policy_id="p", policy_version=1, tool_id="kb.search", tool=tool,
                 arguments={"query": "x"}, argument_errors=[], context=SANDBOX)
    assert d.outcome == "deny" and d.deciding_rule == "deny-late"


def test_tool_level_approval_cannot_be_waived_by_policy() -> None:
    d = _decide(PERMISSIVE, "email.send", {"to": "a@example.com", "subject": "s", "body": "b"})
    assert d.outcome == "require_approval" and d.deciding_rule == "builtin:tool_requires_approval"


def test_no_match_falls_back_to_default_effect() -> None:
    d = _decide(STRICT, "kb.search", {"query": "refund"})
    assert d.outcome == "deny" and d.deciding_rule == "builtin:default_effect"


def test_environment_condition() -> None:
    args = {"title": "Customer call", "priority": "p2"}
    assert _decide(BASELINE, "ticket.create", args).outcome == "allow"
    prod = PolicyContext(environment="production", scenario_id="t")
    assert _decide(BASELINE, "ticket.create", args, prod).outcome == "require_approval"


def test_scenario_tag_condition() -> None:
    doc = PolicyDocument.model_validate({"default_effect": "allow", "rules": [
        {"id": "deny-untrusted", "effect": "deny", "match": {"scenario_tags": ["untrusted-input"]}},
    ]})
    tool = REGISTRY.get("kb.search")
    kwargs: dict[str, Any] = {"policy_id": "p", "policy_version": 1, "tool_id": "kb.search", "tool": tool,
                              "arguments": {"query": "x"}, "argument_errors": []}
    assert evaluate(doc, context=SANDBOX, **kwargs).outcome == "allow"
    tagged = PolicyContext(environment="sandbox", scenario_id="t", scenario_tags=("untrusted-input",))
    assert evaluate(doc, context=tagged, **kwargs).outcome == "deny"


@pytest.mark.parametrize("op,value,actual,expected", [
    ("eq", "a", "a", True), ("neq", "a", "b", True), ("in", ["a", "b"], "b", True),
    ("not_in", ["a"], "a", False), ("contains", "LIMIT", "credit_limit", True), ("prefix", "CUST-0", "CUST-0001", True),
    ("suffix", ".com", "a@example.com", True), ("glob", "*@example.com", "a@example.com", True),
    ("gt", 10, 11, True), ("lte", 10, 11, False), ("gt", 1, "11", False),
])
def test_condition_operators(op: str, value: Any, actual: Any, expected: bool) -> None:
    from app.services.policy_engine.engine import condition_holds
    from app.services.policy_engine.model import ArgumentCondition
    assert condition_holds(ArgumentCondition(path="x", op=op, value=value), {"x": actual}) is expected  # type: ignore[arg-type]


def test_missing_argument_semantics() -> None:
    from app.services.policy_engine.engine import condition_holds
    from app.services.policy_engine.model import ArgumentCondition
    assert condition_holds(ArgumentCondition(path="x", op="eq", value=1), {}) is False
    assert condition_holds(ArgumentCondition(path="x", op="neq", value=1), {}) is True
    assert condition_holds(ArgumentCondition(path="x", op="not_exists"), {}) is True


@pytest.mark.parametrize("document", [
    {"rules": [{"id": "dup", "effect": "allow"}, {"id": "dup", "effect": "deny"}]},
    {"rules": [{"id": "x", "effect": "maybe"}]},
    {"rules": [{"id": "x", "effect": "deny", "match": {"arguments": [{"path": "a", "op": "in", "value": "str"}]}}]},
    {"rules": [{"id": "x", "effect": "deny", "match": {"tool_ids": []}}]},
    {"rules": [{"id": "x", "effect": "deny", "match": {"unknown_dimension": 1}}]},
    {"default_effect": "allow", "extra": True},
])
def test_invalid_documents_rejected(document: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PolicyDocument.model_validate(document)


def test_validator_reports_conflicts_and_shadowing() -> None:
    tools = REGISTRY.all()
    codes = {i.code for i in validate_policy(PolicyDocument.model_validate(BASELINE["document"]), tools)}
    assert "overlapping_rules" in codes
    shadow = PolicyDocument.model_validate({"default_effect": "allow", "rules": [
        {"id": "allow-email", "effect": "allow", "match": {"tool_ids": ["email.draft"]}},
        {"id": "deny-comms", "effect": "deny", "match": {"categories": ["communication"]}},
        {"id": "nothing", "effect": "deny", "match": {"tool_ids": ["nope.*"]}},
    ]})
    found = {i.code for i in validate_policy(shadow, tools)}
    assert {"shadowed_rule", "matches_no_tool", "default_allow"} <= found


def test_all_default_policies_are_valid_documents() -> None:
    for p in DEFAULT_POLICIES:
        issues = validate_policy(PolicyDocument.model_validate(p["document"]), REGISTRY.all())
        assert not [i for i in issues if i.severity == "error"]


def test_diff_and_matrix() -> None:
    a = PolicyDocument.model_validate(BASELINE["document"])
    b = PolicyDocument.model_validate(STRICT["document"])
    diff = diff_documents(a, b)
    assert diff["added"] and diff["removed"]
    assert diff["default_effect"]["changed"] is False
    # Both shared rule IDs exist in each policy with different descriptions.
    assert {c["rule_id"] for c in diff["changed"]} == {"deny-restricted-documents", "deny-admin-tools"}
    assert all(c["fields"] == ["description"] for c in diff["changed"])
    rows = decision_matrix([("baseline", 1, a), ("strict-lockdown", 1, b)], REGISTRY.all())
    kb = next(r for r in rows if r["tool_id"] == "kb.search")
    assert kb["outcomes"]["baseline@v1"]["outcome"] == "allow"
    assert kb["outcomes"]["strict-lockdown@v1"]["outcome"] == "deny"


def test_versions_are_immutable_and_sequential(session: Session) -> None:
    seed_policies(session, DEFAULT_POLICIES)
    v1 = get_version(session, "baseline")
    doc = load_document(v1)
    doc.rules = doc.rules[:-1]
    v2 = create_version(session, "baseline", PolicyVersionCreate(document=doc, change_note="drop prod rule"))
    assert v2.version == 2 and get_version(session, "baseline").version == 2
    assert load_document(get_version(session, "baseline", 1)).rules != doc.rules
    with pytest.raises(ConflictError):
        create_version(session, "baseline", PolicyVersionCreate(document=doc))
    with pytest.raises(ConflictError):
        create_version(session, "baseline", PolicyVersionCreate(document=load_document(v1), base_version=1))
