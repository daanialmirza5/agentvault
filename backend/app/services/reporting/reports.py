"""Exportable reports (JSON + Markdown) built only from persisted records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.utils import new_id, utcnow
from app.models import Approval, Evaluation, Execution, PolicyDecisionRecord, Replay, Report
from app.services.audit.integrity import check_completeness
from app.services.audit.log import list_events, verify_chain
from app.services.policy_engine.analysis import decision_matrix, diff_documents
from app.services.policy_engine.store import get_version, load_document
from app.services.tool_registry.registry import ToolRegistry

ReportKind = Literal["execution", "replay", "evaluation", "policy_comparison"]


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ReportKind
    subject_id: str = Field(
        max_length=80,
        description="Execution, replay or evaluation ID; for policy_comparison use 'policyA@vN..policyB@vM'.",
    )


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(v: Any) -> str:
        return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def _fmt_rate(r: dict[str, Any]) -> str:
    if r["value"] is None:
        return "n/a (0/0)"
    return f"{r['value'] * 100:.1f}% ({r['numerator']}/{r['denominator']})"


def _execution_report(session: Session, execution_id: str) -> tuple[str, dict[str, Any], str]:
    ex = session.get(Execution, execution_id)
    if ex is None:
        raise NotFoundError(f"execution '{execution_id}' not found")
    events = list_events(session, ex.id)
    decisions = session.scalars(
        select(PolicyDecisionRecord)
        .where(PolicyDecisionRecord.execution_id == ex.id)
        .order_by(PolicyDecisionRecord.created_at)
    ).all()
    approvals = session.scalars(select(Approval).where(Approval.execution_id == ex.id)).all()
    chain = verify_chain(events, ex.last_event_hash)
    complete = check_completeness(events, ex.status)
    completeness_text = "complete" if complete["complete"] else "INCOMPLETE: " + "; ".join(complete["problems"])
    content: dict[str, Any] = {
        "execution": {
            "id": ex.id,
            "scenario": f"{ex.scenario_id}@v{ex.scenario_version}",
            "policy": f"{ex.policy_id}@v{ex.policy_version}",
            "status": ex.status,
            "status_reason": ex.status_reason,
            "seed": ex.seed,
            "environment": ex.environment,
            "agent_type": ex.agent_type,
            "task": ex.task,
            "steps": ex.step_count,
            "tool_calls": ex.tool_call_count,
            "final_output": ex.final_output,
            "created_at": ex.created_at.isoformat(),
            "head_hash": ex.last_event_hash,
        },
        "integrity": {"chain": chain, "completeness": complete},
        "events": [
            {
                "sequence": e.sequence,
                "id": e.id,
                "type": e.event_type,
                "tool_id": e.tool_id,
                "outcome": e.outcome,
                "timestamp": e.timestamp.isoformat(),
                "data": e.data,
                "hash": e.hash,
            }
            for e in events
        ],
        "decisions": [
            {
                "id": d.id,
                "tool_id": d.tool_id,
                "outcome": d.outcome,
                "deciding_rule": d.deciding_rule,
                "reason": d.reason,
                "arguments": d.arguments_redacted,
                "event_id": d.event_id,
            }
            for d in decisions
        ],
        "approvals": [
            {
                "id": a.id,
                "tool_id": a.tool_id,
                "status": a.status,
                "decided_by": a.decided_by,
                "created_at": a.created_at.isoformat(),
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            }
            for a in approvals
        ],
    }
    md = [
        f"# Execution report `{ex.id}`",
        "",
        f"- **Scenario:** {content['execution']['scenario']}",
        f"- **Policy:** {content['execution']['policy']}",
        f"- **Status:** {ex.status} — {ex.status_reason}",
        f"- **Seed / environment:** {ex.seed} / {ex.environment}",
        f"- **Task:** {ex.task}",
        f"- **Hash chain:** {'valid' if chain['valid'] else 'INVALID'} (head `{ex.last_event_hash[:16]}…`)",
        f"- **Audit completeness:** {completeness_text}",
        "",
        "## Policy decisions",
        "",
        _md_table(
            ["Decision", "Tool", "Outcome", "Rule", "Reason"],
            [[d.id, d.tool_id, d.outcome, d.deciding_rule, d.reason] for d in decisions],
        ),
        "",
        "## Approvals",
        "",
        _md_table(
            ["Approval", "Tool", "Status", "Decided by"], [[a.id, a.tool_id, a.status, a.decided_by] for a in approvals]
        )
        if approvals
        else "_None._",
        "",
        "## Timeline",
        "",
        _md_table(
            ["#", "Event", "Tool", "Outcome", "Label"],
            [[e.sequence, e.event_type, e.tool_id, e.outcome, e.data.get("label")] for e in events],
        ),
    ]
    return f"Execution {ex.id}", content, "\n".join(md)


def _replay_report(session: Session, replay_id: str) -> tuple[str, dict[str, Any], str]:
    rp = session.get(Replay, replay_id)
    if rp is None:
        raise NotFoundError(f"replay '{replay_id}' not found")
    r = rp.result
    div = r.get("divergence")
    content = {
        "replay": {
            "id": rp.id,
            "mode": rp.mode,
            "execution_id": rp.execution_id,
            "policy": f"{rp.policy_id}@v{rp.policy_version}",
            "approval_strategy": r.get("approval_strategy"),
        },
        **r,
    }
    md = [
        f"# Replay report `{rp.id}`",
        "",
        f"- **Original execution:** `{rp.execution_id}` ({r['original']['policy']}, status {r['original']['status']})",
        f"- **Mode:** {rp.mode} under {rp.policy_id}@v{rp.policy_version} (approvals: {r.get('approval_strategy')})",
        f"- **Replay final status:** {r['final_status']} — {r.get('status_reason', '')}",
    ]
    if r.get("warnings"):
        md += ["", "**Warnings:**", *[f"- {w}" for w in r["warnings"]]]
    if div is not None:
        md += [
            "",
            "## First divergence",
            "",
            "No divergence: the replay is semantically identical to the recording."
            if not div["diverged"]
            else f"At comparable position {div['index']}: {div['explanation']}\n\n"
            f"- Original: `{div['left']}`\n- Replay: `{div['right']}`",
        ]
    md += [
        "",
        "## Frames",
        "",
        _md_table(
            ["#", "Event", "Tool", "Outcome", "Source"],
            [[f["index"], f["event_type"], f["tool_id"], f["outcome"], f["source"]] for f in r["frames"]],
        ),
    ]
    md += [
        "",
        "_Source legend: `recorded` = copied from the original run; `reconstructed` = re-executed against "
        "an isolated mock sandbox; `re-evaluated` = policy decision recomputed; `unavailable` = could not be "
        "reproduced._",
    ]
    return f"Replay {rp.id}", content, "\n".join(md)


def _evaluation_report(session: Session, evaluation_id: str) -> tuple[str, dict[str, Any], str]:
    ev = session.get(Evaluation, evaluation_id)
    if ev is None:
        raise NotFoundError(f"evaluation '{evaluation_id}' not found")
    if ev.status != "completed":
        raise ValidationFailedError(f"evaluation is {ev.status}")
    res = ev.results
    content = {
        "evaluation": {"id": ev.id, "name": ev.name, "request": ev.request, "created_at": ev.created_at.isoformat()},
        **res,
    }
    metric_names = [
        "scenario_pass_rate",
        "unsafe_action_block_rate",
        "legitimate_false_block_rate",
        "legitimate_action_completion_rate",
        "approval_enforcement_rate",
        "task_completion_rate",
        "replay_consistency_rate",
        "audit_completeness_rate",
        "tool_failure_rate",
    ]
    labels = list(res["metrics"])
    rows = [[m, *[_fmt_rate(res["metrics"][label][m]) for label in labels]] for m in metric_names]
    rows.append(
        [
            "policy_eval_latency_p50_us",
            *[res["metrics"][label]["policy_evaluation_latency_us"]["p50"] for label in labels],
        ]
    )
    rows.append(
        ["execution_latency_mean_ms", *[res["metrics"][label]["execution_latency_ms"]["mean"] for label in labels]]
    )
    md = [
        f"# Evaluation report: {ev.name}",
        "",
        f"- **Evaluation:** `{ev.id}`",
        f"- **Generated by:** AgentVault {__version__}",
        f"- **Created:** {ev.created_at.isoformat()}",
        "",
        f"> {res['methodology']}",
        "",
        "## Metrics",
        "",
        _md_table(["Metric", *labels], rows),
        "",
        "## Per-scenario results",
        "",
    ]
    for label in labels:
        md += [
            f"### {label}",
            "",
            _md_table(
                ["Scenario", "Category", "Status", "Passed", "Execution", "Failures"],
                [
                    [
                        r["scenario_id"],
                        r["category"],
                        r["status"],
                        "yes" if r["passed"] else "NO",
                        r["execution_id"],
                        "; ".join(r["failures"]),
                    ]
                    for r in res["runs"][label]
                ],
            ),
            "",
        ]
    if res.get("differences"):
        md += ["## Policy differences (with evidence)", ""]
        for d in res["differences"]:
            md.append(f"- **{d['scenario_id']}**: status {d['status']}; executions {d['execution_ids']}")
            for c in d["changed_actions"]:
                md.append(
                    f"  - `{c['label']}` ({c['tool_id']}): "
                    + "; ".join(
                        f"{k}: {v['decision']} / executed={v['executed']} (event `{v['event_id']}`)"
                        for k, v in c.items()
                        if isinstance(v, dict)
                    )
                )
    return f"Evaluation {ev.name}", content, "\n".join(md)


def _comparison_report(session: Session, subject: str) -> tuple[str, dict[str, Any], str]:
    try:
        left_ref, right_ref = subject.split("..")
        lp, lv = left_ref.split("@v")
        rp, rv = right_ref.split("@v")
        left, right = get_version(session, lp, int(lv)), get_version(session, rp, int(rv))
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError("subject must look like 'baseline@v1..strict-lockdown@v1'") from exc
    ld, rd = load_document(left), load_document(right)
    diff = diff_documents(ld, rd)
    matrix = decision_matrix(
        [(lp, left.version, ld), (rp, right.version, rd)], ToolRegistry.from_session(session).all()
    )
    content: dict[str, Any] = {
        "left": f"{lp}@v{left.version}",
        "right": f"{rp}@v{right.version}",
        "diff": diff,
        "matrix": matrix,
    }
    md = [
        f"# Policy comparison: {content['left']} vs {content['right']}",
        "",
        f"- Default effect: {diff['default_effect']['before']} → {diff['default_effect']['after']}",
        f"- Rules added: {len(diff['added'])}, removed: {len(diff['removed'])}, changed: {len(diff['changed'])}",
        "",
        "## Static decision matrix (empty arguments)",
        "",
        _md_table(
            ["Tool", "Risk", content["left"], content["right"]],
            [[r["tool_id"], r["risk_level"], *[v["outcome"] for v in r["outcomes"].values()]] for r in matrix],
        ),
        "",
        "_Argument-conditioned rules can decide differently at runtime; use an evaluation for evidence._",
    ]
    return f"Policy comparison {content['left']} vs {content['right']}", content, "\n".join(md)


_BUILDERS = {
    "execution": _execution_report,
    "replay": _replay_report,
    "evaluation": _evaluation_report,
    "policy_comparison": _comparison_report,
}


def create_report(session: Session, request: ReportCreate) -> Report:
    title, content, markdown = _BUILDERS[request.kind](session, request.subject_id)
    content = {
        "report_kind": request.kind,
        "generated_at": utcnow().isoformat(),
        "generator": f"AgentVault {__version__}",
        **content,
    }
    report = Report(
        id=new_id("rep"),
        kind=request.kind,
        subject_id=request.subject_id,
        title=title,
        content=content,
        markdown=markdown + "\n",
    )
    session.add(report)
    session.commit()
    return report


def get_report(session: Session, report_id: str) -> Report:
    report = session.get(Report, report_id)
    if report is None:
        raise NotFoundError(f"report '{report_id}' not found")
    return report
