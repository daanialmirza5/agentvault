from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Operator, PageParams
from app.core.db import get_read_session, get_session
from app.core.errors import NotFoundError, ValidationFailedError
from app.models import Policy
from app.repositories.queries import paginate
from app.schemas.common import Page
from app.schemas.resources import PolicyDetailOut, PolicySummaryOut, PolicyVersionOut
from app.services.policy_engine.analysis import decision_matrix, diff_documents, validate_policy
from app.services.policy_engine.engine import evaluate
from app.services.policy_engine.model import PolicyContext, PolicyDocument
from app.services.policy_engine.store import (
    PolicyCreate,
    PolicyVersionCreate,
    create_policy,
    create_version,
    get_version,
    load_document,
)
from app.services.tool_registry.registry import ToolRegistry

router = APIRouter(prefix="/policies", tags=["policies"])
ReadSession = Annotated[Session, Depends(get_read_session)]
WriteSession = Annotated[Session, Depends(get_session)]


class PolicyRefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str = Field(max_length=64)
    version: int | None = Field(default=None, ge=1)


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: PolicyDocument


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: PolicyRefIn
    right: PolicyRefIn
    environment: Literal["sandbox", "staging", "production"] = "sandbox"


class SimulateRequest(BaseModel):
    """Evaluate one hypothetical tool call (policy playground). Nothing is executed or stored."""

    model_config = ConfigDict(extra="forbid")
    document: PolicyDocument | None = None
    policy: PolicyRefIn | None = None
    tool_id: str = Field(max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    environment: Literal["sandbox", "staging", "production"] = "sandbox"
    scenario_tags: list[str] = Field(default_factory=list, max_length=20)


def _detail(session: Session, policy: Policy) -> PolicyDetailOut:
    out = PolicyDetailOut.model_validate(policy)
    out.versions = sorted(out.versions, key=lambda v: v.version, reverse=True)
    return out


@router.get("", response_model=Page[PolicySummaryOut], summary="List policies")
def list_policies(session: ReadSession, page: PageParams) -> Page[PolicySummaryOut]:
    rows, total = paginate(session, select(Policy).order_by(Policy.builtin.desc(), Policy.id), page.limit, page.offset)
    return Page(
        items=[PolicySummaryOut.model_validate(r) for r in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("", response_model=PolicyDetailOut, status_code=201, summary="Create a policy (version 1)")
def create(payload: PolicyCreate, session: WriteSession, _: Operator) -> PolicyDetailOut:
    policy = create_policy(session, payload)
    session.commit()
    session.refresh(policy)
    return _detail(session, policy)


@router.post("/validate", summary="Static checks: conflicts, shadowed rules, unmatched rules")
def validate(payload: ValidateRequest, session: ReadSession) -> dict[str, Any]:
    issues = validate_policy(payload.document, ToolRegistry.from_session(session).all())
    return {"valid": not any(i.severity == "error" for i in issues), "issues": [i.model_dump() for i in issues]}


@router.post("/compare", summary="Diff two policy versions and show a static decision matrix")
def compare(payload: CompareRequest, session: ReadSession) -> dict[str, Any]:
    left = get_version(session, payload.left.policy_id, payload.left.version)
    right = get_version(session, payload.right.policy_id, payload.right.version)
    ld, rd = load_document(left), load_document(right)
    tools = ToolRegistry.from_session(session).all()
    return {
        "left": f"{left.policy_id}@v{left.version}",
        "right": f"{right.policy_id}@v{right.version}",
        "diff": diff_documents(ld, rd),
        "matrix": decision_matrix(
            [(left.policy_id, left.version, ld), (right.policy_id, right.version, rd)], tools, payload.environment
        ),
        "note": "The matrix evaluates each tool with empty arguments; argument-conditioned rules may differ at "
        "runtime. Run an evaluation for scenario-level evidence.",
    }


@router.post("/simulate", summary="Evaluate a hypothetical tool call against a policy (nothing executes)")
def simulate_decision(payload: SimulateRequest, session: ReadSession) -> dict[str, Any]:
    if (payload.document is None) == (payload.policy is None):
        raise ValidationFailedError("provide exactly one of 'document' or 'policy'")
    if payload.policy is not None:
        row = get_version(session, payload.policy.policy_id, payload.policy.version)
        document, pid, version = load_document(row), row.policy_id, row.version
    else:
        assert payload.document is not None
        document, pid, version = payload.document, "draft", 0
    registry = ToolRegistry.from_session(session)
    tool = registry.get(payload.tool_id)
    errors = registry.validate_arguments(tool, payload.arguments) if tool else []
    decision = evaluate(
        document,
        policy_id=pid,
        policy_version=version,
        tool_id=payload.tool_id,
        tool=tool,
        arguments=payload.arguments,
        argument_errors=errors,
        context=PolicyContext(
            environment=payload.environment, scenario_id="playground", scenario_tags=tuple(payload.scenario_tags)
        ),
    )
    return {"decision": decision.model_dump(), "argument_errors": errors, "tool_registered": tool is not None}


@router.get("/{policy_id}", response_model=PolicyDetailOut, summary="Policy with full version history")
def get_policy(policy_id: str, session: ReadSession) -> PolicyDetailOut:
    policy = session.get(Policy, policy_id)
    if policy is None:
        raise NotFoundError(f"policy '{policy_id}' not found")
    return _detail(session, policy)


@router.get("/{policy_id}/versions/{version}", response_model=PolicyVersionOut)
def get_policy_version(policy_id: str, version: int, session: ReadSession) -> PolicyVersionOut:
    return PolicyVersionOut.model_validate(get_version(session, policy_id, version))


@router.post(
    "/{policy_id}/versions",
    response_model=PolicyVersionOut,
    status_code=201,
    summary="Save an edited document as a new immutable version",
)
def new_version(policy_id: str, payload: PolicyVersionCreate, session: WriteSession, _: Operator) -> PolicyVersionOut:
    row = create_version(session, policy_id, payload)
    session.commit()
    return PolicyVersionOut.model_validate(row)
