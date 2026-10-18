"""Built-in mock tool implementations.

Every implementation operates only on the per-execution ``sandbox`` dictionary and a
seeded RNG. None of them touch the filesystem, network, subprocesses or real accounts.
New tools registered through the API must bind to one of these implementations; there is
no way to register executable code.
"""

from __future__ import annotations

import ast
import operator
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    """A tool ran but reported a failure (it is recorded as ``tool.failed``)."""


@dataclass
class ToolContext:
    sandbox: dict[str, Any]
    rng: random.Random
    step: int
    config: dict[str, Any] = field(default_factory=dict)


Implementation = Callable[[dict[str, Any], ToolContext], dict[str, Any]]


def _docs_read(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    doc = ctx.sandbox["documents"].get(args["doc_id"])
    if doc is None:
        raise ToolError(f"document '{args['doc_id']}' does not exist")
    return {"doc_id": args["doc_id"], **doc}


def _kb_search(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    terms = [t for t in args["query"].lower().split() if t]
    scored = []
    for article in ctx.sandbox["kb_articles"]:
        text = f"{article['title']} {article['body']}".lower()
        score = sum(text.count(t) for t in terms)
        if score:
            scored.append((score, article))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["article_id"]))
    limit = args.get("limit", 3)
    return {
        "results": [
            {"article_id": a["article_id"], "title": a["title"], "snippet": a["body"][:80], "score": s}
            for s, a in scored[:limit]
        ]
    }


def _crm_get_customer(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    customer = ctx.sandbox["customers"].get(args["customer_id"])
    if customer is None:
        raise ToolError(f"customer '{args['customer_id']}' not found")
    return {"customer_id": args["customer_id"], **{k: v for k, v in customer.items() if k != "notes"}}


def _email_draft(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = f"DRAFT-{len(ctx.sandbox['drafts']) + 1:04d}"
    ctx.sandbox["drafts"].append({"draft_id": draft_id, **args})
    return {"draft_id": draft_id, "status": "draft_saved"}


def _email_send(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    message_id = f"MSG-{len(ctx.sandbox['outbox']) + 1:04d}"
    ctx.sandbox["outbox"].append({"message_id": message_id, **args})
    return {"message_id": message_id, "status": "delivered_to_simulated_outbox"}


def _ticket_create(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    ticket_id = f"TCK-{len(ctx.sandbox['tickets']) + 1:04d}"
    ctx.sandbox["tickets"].append({"ticket_id": ticket_id, "status": "open", **args})
    return {"ticket_id": ticket_id, "status": "open"}


def _crm_update_record(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    customer = ctx.sandbox["customers"].get(args["customer_id"])
    if customer is None:
        raise ToolError(f"customer '{args['customer_id']}' not found")
    if customer.get("protected"):
        # Defence in depth: the mock backend refuses even if a policy wrongly allowed it.
        raise ToolError("record is protected and cannot be modified")
    old = customer.get(args["field"])
    customer[args["field"]] = args["value"]
    ctx.sandbox["record_changes"].append({**args, "old_value": old})
    return {"customer_id": args["customer_id"], "field": args["field"], "old_value": str(old), "new_value": args["value"]}


_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod,
}


def _safe_arith(node: ast.AST, depth: int = 0) -> float:
    """Evaluate +,-,*,/,% and ** (small exponents) over numeric literals only. No names, calls or attributes."""
    if depth > 30:
        raise ToolError("expression too deeply nested")
    if isinstance(node, ast.Expression):
        return _safe_arith(node.body, depth + 1)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        value = _safe_arith(node.operand, depth + 1)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left, right = _safe_arith(node.left, depth + 1), _safe_arith(node.right, depth + 1)
        if isinstance(node.op, ast.Pow):
            if abs(right) > 10 or abs(left) > 1e6:
                raise ToolError("exponent out of the allowed range")
            return float(left**right)
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ToolError("operator not allowed")
        try:
            return op(left, right)
        except ZeroDivisionError as exc:
            raise ToolError("division by zero") from exc
    raise ToolError("only numeric arithmetic is allowed")


def _calc_evaluate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    try:
        tree = ast.parse(args["expression"], mode="eval")
    except SyntaxError as exc:
        raise ToolError("expression is not valid arithmetic") from exc
    return {"result": round(_safe_arith(tree), 10)}


def _admin_export(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # Records the attempt only; nothing leaves the sandbox.
    ctx.sandbox["export_attempts"].append(args)
    return {"exported_records": len(ctx.sandbox["customers"]), "destination": args["destination"]}


def _ops_generate_report(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    time.sleep(min(int(args.get("delay_ms", 0)), 2000) / 1000)
    return {"report": args["report"], "rows": 3 + ctx.step % 5}


def _ops_check_inventory(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    failure_rate = float(ctx.config.get("failure_rate", 0.5))
    if ctx.rng.random() < failure_rate:
        raise ToolError("inventory service unavailable (simulated transient failure)")
    stock = ctx.sandbox["inventory"].get(args["sku"])
    if stock is None:
        raise ToolError(f"unknown SKU '{args['sku']}'")
    return {"sku": args["sku"], "in_stock": stock}


def _ops_fetch_exchange_rate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # Deliberately NOT seeded: models an external source whose answer changes over time.
    jitter = random.SystemRandom().uniform(-0.02, 0.02)
    return {"pair": args["pair"], "rate": round(1.08 + jitter, 5)}


def _static_response(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    response = ctx.config.get("response", {})
    return dict(response) if isinstance(response, dict) else {}


def _echo(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return {"echo": args}


IMPLEMENTATIONS: dict[str, Implementation] = {
    "mock.docs.read": _docs_read,
    "mock.kb.search": _kb_search,
    "mock.crm.get_customer": _crm_get_customer,
    "mock.email.draft": _email_draft,
    "mock.email.send": _email_send,
    "mock.ticket.create": _ticket_create,
    "mock.crm.update_record": _crm_update_record,
    "mock.calc.evaluate": _calc_evaluate,
    "mock.admin.export_all": _admin_export,
    "mock.ops.generate_report": _ops_generate_report,
    "mock.ops.check_inventory": _ops_check_inventory,
    "mock.ops.fetch_exchange_rate": _ops_fetch_exchange_rate,
    "mock.static_response": _static_response,
    "mock.echo": _echo,
}

# Implementations that custom (API-registered) tools may bind to.
GENERIC_IMPLEMENTATIONS = ("mock.static_response", "mock.echo")

IMPLEMENTATION_NOTES: dict[str, str] = {
    "mock.docs.read": "Returns a document from the sandbox fixture. Read-only.",
    "mock.kb.search": "Deterministic keyword scoring over fixture KB articles.",
    "mock.crm.get_customer": "Returns a fictional customer record from the sandbox.",
    "mock.email.draft": "Appends a draft to the sandbox `drafts` list.",
    "mock.email.send": "Appends to the sandbox `outbox`. No email is ever sent.",
    "mock.ticket.create": "Appends a ticket to the sandbox `tickets` list.",
    "mock.crm.update_record": "Mutates a sandbox customer; refuses protected records.",
    "mock.calc.evaluate": "AST-whitelisted arithmetic. No eval(), names or calls.",
    "mock.admin.export_all": "Records the export attempt in the sandbox; exports nothing.",
    "mock.ops.generate_report": "Sleeps for `delay_ms` (max 2 s) to exercise tool timeouts.",
    "mock.ops.check_inventory": "Fails with seeded probability `failure_rate` to exercise failures.",
    "mock.ops.fetch_exchange_rate": "Unseeded jitter: intentionally non-deterministic for replay tests.",
    "mock.static_response": "Returns `mock_config.response` verbatim (custom tools).",
    "mock.echo": "Returns the validated arguments (custom tools).",
}
