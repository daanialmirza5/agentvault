"""Semantic comparison of event streams and first-divergence detection.

Two runs are compared on a normalised *fingerprint* per event that keeps what an agent did
and what the platform decided, and drops what is expected to differ between runs: event and
decision IDs, timestamps, latencies, approval IDs, operator names and hash-chain values.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.core.utils import fingerprint


class EventView(Protocol):
    sequence: int
    event_type: str
    tool_id: str | None
    outcome: str
    data: dict[str, Any]


# Events that describe *how* a run was driven rather than what it did. A live approval pauses
# and resumes; a simulated one does not. Binding-mismatch events are out-of-band attack
# attempts against the approval API, not agent behaviour.
IGNORED_IN_COMPARISON = frozenset({"execution.resumed", "approval.binding_mismatch"})


def comparable(events: Sequence[EventView]) -> list[EventView]:
    return [e for e in events if e.event_type not in IGNORED_IN_COMPARISON]


def event_key(e: EventView) -> tuple[Any, ...]:
    d = e.data
    label = d.get("label")
    t = e.event_type
    if t in {"execution.created", "execution.started"}:
        return (t,)
    if t == "approval.requested":
        return (t, label, e.tool_id)
    if t == "agent.action_proposed":
        return (t, label, e.tool_id, fingerprint(d.get("arguments")))
    if t == "tool.requested":
        return (t, label, d.get("action_fingerprint"))
    if t == "policy.evaluated":
        return (t, label, e.outcome, d.get("deciding_rule"))
    if t == "tool.result":
        return (t, label, d.get("output_hash"))
    if t == "guard.triggered":
        return (t, d.get("guard"))
    if t.startswith("execution."):
        return (t, e.outcome)
    return (t, label, e.tool_id, e.outcome)


def summarize(e: EventView | None) -> dict[str, Any] | None:
    if e is None:
        return None
    return {"sequence": e.sequence, "event_type": e.event_type, "tool_id": e.tool_id, "outcome": e.outcome,
            "label": e.data.get("label"), "step": e.data.get("step"), "event_id": getattr(e, "id", None)}


def first_divergence(left_all: Sequence[EventView], right_all: Sequence[EventView]) -> dict[str, Any]:
    """Index is a position in the comparable streams; each side's summary carries its own sequence number."""
    left, right = comparable(left_all), comparable(right_all)
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        ka, kb = event_key(a), event_key(b)
        if ka != kb:
            return {"diverged": True, "index": index, "left": summarize(a), "right": summarize(b),
                    "explanation": _explain(a, b), "left_count": len(left), "right_count": len(right)}
    if len(left) != len(right):
        index = min(len(left), len(right))
        a = left[index] if index < len(left) else None
        b = right[index] if index < len(right) else None
        return {"diverged": True, "index": index, "left": summarize(a), "right": summarize(b),
                "explanation": "One run ended earlier: the streams agree up to this point and then one has "
                               "no further events.", "left_count": len(left), "right_count": len(right)}
    return {"diverged": False, "index": None, "left": None, "right": None,
            "explanation": "The event streams are semantically identical.",
            "left_count": len(left), "right_count": len(right)}


def _explain(a: EventView, b: EventView) -> str:
    if a.event_type != b.event_type:
        return f"Different event types: '{a.event_type}' vs '{b.event_type}'."
    if a.event_type == "policy.evaluated":
        return (f"Policy decided '{a.outcome}' (rule {a.data.get('deciding_rule')}) vs "
                f"'{b.outcome}' (rule {b.data.get('deciding_rule')}) for '{a.data.get('label')}'.")
    if a.event_type == "tool.result":
        return f"Tool '{a.tool_id}' returned different output for '{a.data.get('label')}'."
    if a.event_type in {"agent.action_proposed", "tool.requested"}:
        return f"The agent proposed a different action ({a.tool_id} vs {b.tool_id})."
    return f"Same event type '{a.event_type}' with different outcome: '{a.outcome}' vs '{b.outcome}'."


def tool_call_table(events: Sequence[EventView]) -> list[dict[str, Any]]:
    """One row per proposed tool call: decision, execution status and output hash."""
    rows: dict[int, dict[str, Any]] = {}
    for e in events:
        step = e.data.get("step")
        if not isinstance(step, int):
            continue
        if e.event_type == "tool.requested":
            rows[step] = {"step": step, "label": e.data.get("label"), "tool_id": e.tool_id,
                          "action_fingerprint": e.data.get("action_fingerprint"), "decision": None,
                          "deciding_rule": None, "approval": None, "status": "not_executed", "output_hash": None,
                          "source": None}
        row = rows.get(step)
        if row is None:
            continue
        if e.event_type == "policy.evaluated":
            row["decision"], row["deciding_rule"] = e.outcome, e.data.get("deciding_rule")
        elif e.event_type in {"approval.granted", "approval.rejected", "approval.expired"}:
            row["approval"] = e.outcome
        elif e.event_type == "tool.executed":
            row["status"], row["source"] = e.outcome, e.data.get("source")
        elif e.event_type == "tool.result":
            row["output_hash"] = e.data.get("output_hash")
        elif e.event_type == "tool.blocked":
            row["status"] = f"blocked:{e.outcome}"
    return [rows[k] for k in sorted(rows)]
