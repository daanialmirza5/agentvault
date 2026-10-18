"""Command-line utilities.

python -m app.cli seed
python -m app.cli verify-audit [--execution exe_...]
python -m app.cli purge [--days 30] [--dry-run]
python -m app.cli evaluate [--policies baseline strict-lockdown permissive-dev] [--output ../benchmarks/results]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core import db
from app.core.config import get_settings
from app.core.migrations import upgrade_to_head
from app.models import Execution
from app.services.audit.integrity import check_completeness
from app.services.audit.log import list_events, verify_chain
from app.services.evaluation.evaluator import EvaluationCreate, PolicyRef, run_evaluation
from app.services.reporting.reports import ReportCreate, create_report
from app.services.retention import purge_older_than
from app.services.seed import seed_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="apply migrations and seed tools, policies and scenarios")
    verify = sub.add_parser("verify-audit", help="verify hash chains and audit completeness")
    verify.add_argument("--execution")
    purge = sub.add_parser("purge", help="delete finished executions older than the retention window")
    purge.add_argument("--days", type=int, default=None)
    purge.add_argument("--dry-run", action="store_true")
    evaluate = sub.add_parser("evaluate", help="run the scenario suite and write JSON + Markdown results")
    evaluate.add_argument("--policies", nargs="+", default=["baseline", "strict-lockdown", "permissive-dev"])
    evaluate.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = db.init_engine(settings.database_url)
    upgrade_to_head(engine)
    session = db.session_factory()()
    try:
        if args.command == "seed":
            print(json.dumps(seed_all(session, settings.scenarios_dir)))
            return 0
        if args.command == "verify-audit":
            query = select(Execution)
            if args.execution:
                query = query.where(Execution.id == args.execution)
            failures = 0
            executions = session.scalars(query).all()
            for ex in executions:
                events = list_events(session, ex.id)
                chain = verify_chain(events, ex.last_event_hash)
                complete = check_completeness(events, ex.status)
                if not (chain["valid"] and complete["complete"]):
                    failures += 1
                    print(f"FAIL {ex.id}: {chain['problems'] + complete['problems']}")
            print(f"verified {len(executions)} execution(s), {failures} failure(s)")
            return 1 if failures else 0
        if args.command == "purge":
            days = settings.retention_days if args.days is None else args.days
            print(json.dumps(purge_older_than(session, days, dry_run=args.dry_run)))
            return 0
        if args.command == "evaluate":
            seed_all(session, settings.scenarios_dir)
            ev = run_evaluation(
                session,
                settings,
                EvaluationCreate(name="CLI benchmark", policies=[PolicyRef(policy_id=p) for p in args.policies]),
            )
            report = create_report(session, ReportCreate(kind="evaluation", subject_id=ev.id))
            if args.output:
                args.output.mkdir(parents=True, exist_ok=True)
                (args.output / "latest.json").write_text(
                    json.dumps(report.content, indent=2, default=str), encoding="utf-8"
                )
                (args.output / "latest.md").write_text(report.markdown, encoding="utf-8")
            for label, metrics in ev.results["metrics"].items():
                summary = {k: v["value"] for k, v in metrics.items() if isinstance(v, dict) and "numerator" in v}
                print(label, json.dumps(summary))
            return 0
    finally:
        session.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
