"""Deterministic policy evaluation.

Precedence, applied in this order:

1. ``builtin:unknown_tool``       - a tool that is not in the registry is always denied.
2. ``builtin:invalid_arguments``  - arguments that fail the tool's input schema are denied.
3. Policy rules                   - every enabled rule whose match conditions hold is collected.
   Conflicts resolve as *deny-overrides*: deny > require_approval > allow. ``priority`` only
   orders rules of the same effect to choose the reported deciding rule.
4. ``builtin:default_effect``     - if no rule matches, the policy's default effect applies.
5. ``builtin:tool_requires_approval`` - a tool that declares ``requires_approval`` can never be
   relaxed to a plain allow by policy; an ``allow`` outcome is escalated to ``require_approval``.

The function takes no input from the agent other than the tool ID and arguments. Agent
"claims" (for example that an action is safe or pre-approved) are not parameters, so they
cannot influence the result.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from app.services.policy_engine.model import (
    EFFECT_SEVERITY,
    ArgumentCondition,
    Decision,
    MatchedRule,
    PolicyContext,
    PolicyDocument,
    PolicyRule,
)
from app.services.tool_registry.registry import ToolSpec

_MISSING = object()


def resolve_path(arguments: dict[str, Any], path: str) -> Any:
    current: Any = arguments
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def condition_holds(condition: ArgumentCondition, arguments: dict[str, Any]) -> bool:
    actual = resolve_path(arguments, condition.path)
    op, expected = condition.op, condition.value
    if op == "exists":
        return actual is not _MISSING
    if op == "not_exists":
        return actual is _MISSING
    if actual is _MISSING:
        # Negative operators match when the argument is absent; positive ones do not.
        return op in {"neq", "not_in"}
    if op == "eq":
        return bool(actual == expected)
    if op == "neq":
        return bool(actual != expected)
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected.lower() in actual.lower()
        return isinstance(actual, list) and expected in actual
    if op in {"prefix", "suffix", "glob"}:
        if not isinstance(actual, str):
            return False
        if op == "prefix":
            return actual.startswith(expected)
        if op == "suffix":
            return actual.endswith(expected)
        return fnmatch.fnmatchcase(actual, expected)
    if isinstance(actual, bool) or not isinstance(actual, int | float):
        return False
    return {"gt": actual > expected, "gte": actual >= expected,
            "lt": actual < expected, "lte": actual <= expected}[op]


def tool_matches_patterns(tool_id: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(tool_id, p) for p in patterns)


def rule_matches(rule: PolicyRule, tool: ToolSpec, arguments: dict[str, Any], ctx: PolicyContext) -> bool:
    m = rule.match
    if m.tool_ids is not None and not tool_matches_patterns(tool.tool_id, m.tool_ids):
        return False
    if m.categories is not None and tool.category not in m.categories:
        return False
    if m.risk_levels is not None and tool.risk_level not in m.risk_levels:
        return False
    if m.operations is not None and tool.operation not in m.operations:
        return False
    if m.environments is not None and ctx.environment not in m.environments:
        return False
    if m.scenario_tags is not None and not set(m.scenario_tags) & set(ctx.scenario_tags):
        return False
    return all(condition_holds(c, arguments) for c in m.arguments)


def evaluate(
    document: PolicyDocument,
    *,
    policy_id: str,
    policy_version: int,
    tool_id: str,
    tool: ToolSpec | None,
    arguments: dict[str, Any],
    argument_errors: list[str],
    context: PolicyContext,
) -> Decision:
    def decide(outcome: str, reason: str, deciding: str, matched: list[MatchedRule], trace: list[str]) -> Decision:
        return Decision(outcome=outcome, reason=reason, deciding_rule=deciding,  # type: ignore[arg-type]
                        matched_rules=matched, policy_id=policy_id, policy_version=policy_version, trace=trace)

    trace: list[str] = []
    if tool is None:
        trace.append(f"tool '{tool_id}' is not registered")
        return decide("deny", f"Unknown tool '{tool_id}' is not in the registry allowlist.",
                      "builtin:unknown_tool", [], trace)
    if argument_errors:
        trace.append("arguments failed schema validation")
        return decide("deny", "Arguments failed schema validation: " + "; ".join(argument_errors[:3]),
                      "builtin:invalid_arguments", [], trace)

    matched: list[MatchedRule] = []
    for rule in document.rules:
        if not rule.enabled:
            continue
        if rule_matches(rule, tool, arguments, context):
            matched.append(MatchedRule(rule_id=rule.id, effect=rule.effect, priority=rule.priority,
                                       description=rule.description))
            trace.append(f"rule '{rule.id}' matched -> {rule.effect}")

    if matched:
        matched.sort(key=lambda r: (-EFFECT_SEVERITY[r.effect], r.priority, r.rule_id))
        winner = matched[0]
        outcome, deciding = winner.effect, winner.rule_id
        reason = winner.description or f"Rule '{winner.rule_id}' applies."
        if len({r.effect for r in matched}) > 1:
            trace.append(f"conflict resolved by deny-overrides: '{winner.rule_id}' ({winner.effect}) wins")
    else:
        outcome, deciding = document.default_effect, "builtin:default_effect"
        reason = f"No rule matched; the policy default is '{document.default_effect}'."
        trace.append(reason)

    if outcome == "allow" and tool.requires_approval:
        trace.append(f"tool '{tool.tool_id}' declares requires_approval; escalating allow -> require_approval")
        return decide("require_approval",
                      f"{reason} The tool itself requires human approval, which policy cannot waive.",
                      "builtin:tool_requires_approval", matched, trace)
    return decide(outcome, reason, deciding, matched, trace)
