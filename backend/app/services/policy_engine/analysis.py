"""Static analysis of policy documents: conflicts, shadowed rules, diffs and decision matrices."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.services.policy_engine.engine import evaluate, tool_matches_patterns
from app.services.policy_engine.model import EFFECT_SEVERITY, PolicyContext, PolicyDocument, PolicyRule
from app.services.tool_registry.registry import ToolSpec


class PolicyIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    rule_ids: list[str] = []


def _tools_for(rule: PolicyRule, tools: list[ToolSpec]) -> set[str]:
    """Registered tools a rule's tool-level dimensions can match (ignores env/tags/arguments)."""
    m = rule.match
    out = set()
    for t in tools:
        if m.tool_ids is not None and not tool_matches_patterns(t.tool_id, m.tool_ids):
            continue
        if m.categories is not None and t.category not in m.categories:
            continue
        if m.risk_levels is not None and t.risk_level not in m.risk_levels:
            continue
        if m.operations is not None and t.operation not in m.operations:
            continue
        out.add(t.tool_id)
    return out


def _sets_overlap(a: list[str] | None, b: list[str] | None) -> bool:
    return a is None or b is None or bool(set(a) & set(b))


def _covers(broad: list[str] | None, narrow: list[str] | None) -> bool:
    return broad is None or (narrow is not None and set(narrow) <= set(broad))


def validate_policy(document: PolicyDocument, tools: list[ToolSpec]) -> list[PolicyIssue]:
    issues: list[PolicyIssue] = []
    if document.default_effect == "allow":
        issues.append(
            PolicyIssue(
                severity="warning",
                code="default_allow",
                message="The default effect is 'allow': any tool not covered by a rule is permitted "
                "(tools that declare requires_approval still need approval).",
            )
        )
    rules = [r for r in document.rules if r.enabled]
    reach = {r.id: _tools_for(r, tools) for r in rules}
    for rule in rules:
        if not reach[rule.id]:
            issues.append(
                PolicyIssue(
                    severity="warning",
                    code="matches_no_tool",
                    rule_ids=[rule.id],
                    message=f"Rule '{rule.id}' cannot match any registered tool.",
                )
            )
        if rule.match == type(rule.match)():
            issues.append(
                PolicyIssue(
                    severity="info",
                    code="matches_everything",
                    rule_ids=[rule.id],
                    message=f"Rule '{rule.id}' has no conditions and matches every request.",
                )
            )
    for i, a in enumerate(rules):
        for b in rules[i + 1 :]:
            if a.effect == b.effect:
                continue
            shared = reach[a.id] & reach[b.id]
            if not shared:
                continue
            if not (
                _sets_overlap(a.match.environments, b.match.environments)
                and _sets_overlap(a.match.scenario_tags, b.match.scenario_tags)
            ):
                continue
            strict, loose = (a, b) if EFFECT_SEVERITY[a.effect] > EFFECT_SEVERITY[b.effect] else (b, a)
            shadowed = (
                not strict.match.arguments
                and reach[loose.id] <= reach[strict.id]
                and _covers(strict.match.environments, loose.match.environments)
                and _covers(strict.match.scenario_tags, loose.match.scenario_tags)
            )
            if shadowed:
                issues.append(
                    PolicyIssue(
                        severity="warning",
                        code="shadowed_rule",
                        rule_ids=[loose.id, strict.id],
                        message=f"Rule '{loose.id}' ({loose.effect}) never takes effect: '{strict.id}' "
                        f"({strict.effect}) matches every request it matches.",
                    )
                )
            else:
                issues.append(
                    PolicyIssue(
                        severity="info",
                        code="overlapping_rules",
                        rule_ids=[strict.id, loose.id],
                        message=f"Rules '{strict.id}' ({strict.effect}) and '{loose.id}' ({loose.effect}) can both "
                        f"match {', '.join(sorted(shared)[:4])}; '{strict.effect}' wins (deny-overrides).",
                    )
                )
    return issues


def diff_documents(left: PolicyDocument, right: PolicyDocument) -> dict[str, Any]:
    lrules = {r.id: r for r in left.rules}
    rrules = {r.id: r for r in right.rules}
    changed = []
    for rid in sorted(set(lrules) & set(rrules)):
        before, after = lrules[rid].model_dump(), rrules[rid].model_dump()
        if before != after:
            fields = sorted(k for k in before if before[k] != after[k])
            changed.append({"rule_id": rid, "fields": fields, "before": before, "after": after})
    return {
        "default_effect": {
            "before": left.default_effect,
            "after": right.default_effect,
            "changed": left.default_effect != right.default_effect,
        },
        "added": [rrules[r].model_dump() for r in sorted(set(rrules) - set(lrules))],
        "removed": [lrules[r].model_dump() for r in sorted(set(lrules) - set(rrules))],
        "changed": changed,
    }


def decision_matrix(
    policies: list[tuple[str, int, PolicyDocument]], tools: list[ToolSpec], environment: str = "sandbox"
) -> list[dict[str, Any]]:
    """Static per-tool outcome under each policy, evaluated with empty arguments.

    Argument-conditioned rules may decide differently at runtime; the evaluation lab is the
    authoritative comparison.
    """
    ctx = PolicyContext(environment=environment, scenario_id="__matrix__")
    rows = []
    for tool in tools:
        row: dict[str, Any] = {"tool_id": tool.tool_id, "risk_level": tool.risk_level, "outcomes": {}}
        for pid, version, doc in policies:
            decision = evaluate(
                doc,
                policy_id=pid,
                policy_version=version,
                tool_id=tool.tool_id,
                tool=tool,
                arguments={},
                argument_errors=[],
                context=ctx,
            )
            row["outcomes"][f"{pid}@v{version}"] = {"outcome": decision.outcome, "rule": decision.deciding_rule}
        rows.append(row)
    return rows
