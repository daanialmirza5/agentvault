"""Environment-based configuration. Every setting is prefixed with ``AGENTVAULT_``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTVAULT_",
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'agentvault.db').as_posix()}"
    environment: Literal["local", "test", "production"] = "local"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_token: SecretStr | None = None
    operator_name: str = Field(default="local-operator", max_length=64)

    max_request_bytes: int = Field(default=256 * 1024, ge=1024, le=10 * 1024 * 1024)
    max_steps: int = Field(default=40, ge=1, le=500)
    max_tool_calls: int = Field(default=20, ge=1, le=200)
    max_identical_calls: int = Field(default=3, ge=1, le=50)
    approval_ttl_seconds: int = Field(default=900, ge=1, le=7 * 24 * 3600)
    execution_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    retention_days: int = Field(default=30, ge=0)
    seed_on_startup: bool = True
    scenarios_dir: Path = REPO_DIR / "scenarios"

    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        # Wildcards are rejected on purpose: the API exposes approval decisions.
        return [o for o in origins if o != "*"]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def auth_required(self) -> bool:
        return self.api_token is not None and bool(self.api_token.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
