"""Persistence for policies and their immutable versions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.utils import fingerprint, new_id, utcnow
from app.models import Policy, PolicyVersion
from app.services.policy_engine.model import PolicyDocument


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    document: PolicyDocument
    change_note: str = Field(default="Initial version", max_length=500)


class PolicyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: PolicyDocument
    change_note: str = Field(default="", max_length=500)
    base_version: int | None = Field(
        default=None, description="Optimistic concurrency: reject if the latest version is no longer this one."
    )


def create_policy(session: Session, payload: PolicyCreate, *, builtin: bool = False) -> Policy:
    if session.get(Policy, payload.id) is not None:
        raise ConflictError(f"policy '{payload.id}' already exists")
    policy = Policy(id=payload.id, name=payload.name, description=payload.description,
                    latest_version=1, builtin=builtin)
    session.add(policy)
    session.flush()
    _add_version(session, policy, 1, payload.document, payload.change_note)
    return policy


def create_version(session: Session, policy_id: str, payload: PolicyVersionCreate) -> PolicyVersion:
    policy = session.get(Policy, policy_id)
    if policy is None:
        raise NotFoundError(f"policy '{policy_id}' not found")
    if payload.base_version is not None and payload.base_version != policy.latest_version:
        raise ConflictError(
            f"policy was modified: latest version is {policy.latest_version}, not {payload.base_version}",
            code="stale_policy_version",
        )
    latest = get_version(session, policy_id, policy.latest_version)
    if latest.content_hash == _hash(payload.document):
        raise ConflictError("document is identical to the latest version", code="no_changes")
    policy.latest_version += 1
    policy.updated_at = utcnow()
    return _add_version(session, policy, policy.latest_version, payload.document, payload.change_note)


def _hash(document: PolicyDocument) -> str:
    return fingerprint(document.model_dump(mode="json"))


def _add_version(session: Session, policy: Policy, version: int, document: PolicyDocument, note: str) -> PolicyVersion:
    row = PolicyVersion(id=new_id("polv"), policy_id=policy.id, version=version,
                        document=document.model_dump(mode="json"), content_hash=_hash(document), change_note=note)
    session.add(row)
    session.flush()
    return row


def get_version(session: Session, policy_id: str, version: int | None = None) -> PolicyVersion:
    policy = session.get(Policy, policy_id)
    if policy is None:
        raise NotFoundError(f"policy '{policy_id}' not found")
    v = version if version is not None else policy.latest_version
    row = session.scalar(select(PolicyVersion).where(PolicyVersion.policy_id == policy_id, PolicyVersion.version == v))
    if row is None:
        raise NotFoundError(f"policy '{policy_id}' has no version {v}")
    return row


def load_document(row: PolicyVersion) -> PolicyDocument:
    return PolicyDocument.model_validate(row.document)


def seed_policies(session: Session, definitions: list[dict[str, Any]]) -> int:
    created = 0
    for d in definitions:
        if session.get(Policy, d["id"]) is None:
            create_policy(session, PolicyCreate(
                id=d["id"], name=d["name"], description=d["description"],
                document=PolicyDocument.model_validate(d["document"]), change_note="Seeded built-in policy",
            ), builtin=True)
            created += 1
    return created
