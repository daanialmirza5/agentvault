"""Shared FastAPI dependencies."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Header, Query

from app.core.config import Settings, get_settings
from app.core.errors import AuthError

SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_write_access(settings: SettingsDep, authorization: Annotated[str | None, Header()] = None) -> str:
    """Authorise mutating requests and return the operator identity.

    Single-user local mode (no ``AGENTVAULT_API_TOKEN``): every caller is the configured
    operator. With a token configured, a matching ``Authorization: Bearer`` header is required.
    This is a shared-secret gate, not multi-user authentication.
    """
    if settings.auth_required:
        assert settings.api_token is not None
        expected = settings.api_token.get_secret_value()
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise AuthError("a valid bearer token is required for this operation")
    return settings.operator_name


Operator = Annotated[str, Depends(require_write_access)]


class Pagination:
    def __init__(
        self, limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0
    ) -> None:
        self.limit = limit
        self.offset = offset


PageParams = Annotated[Pagination, Depends()]
