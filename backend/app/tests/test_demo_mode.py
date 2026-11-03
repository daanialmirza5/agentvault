"""Public demo mode and single-container frontend serving."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.tests.factories import make_settings


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = make_settings(
        database_url=f"sqlite:///{(tmp_path / 'demo.db').as_posix()}", seed_on_startup=True, **overrides
    )
    return TestClient(create_app(settings))


def test_demo_mode_refuses_an_api_token() -> None:
    with pytest.raises(ValidationError, match="DEMO_MODE cannot be combined with AGENTVAULT_API_TOKEN"):
        make_settings(demo_mode=True, api_token="secret")


def test_demo_mode_refuses_an_llm_endpoint() -> None:
    with pytest.raises(ValidationError, match="LLM endpoint"):
        make_settings(demo_mode=True, llm_base_url="https://llm.invalid/v1", llm_api_key="k", llm_model="m")


def test_ready_reports_demo_mode(tmp_path: Path) -> None:
    with _client(tmp_path, demo_mode=True) as client:
        body = client.get("/api/v1/ready").json()
    assert body["status"] == "ready"
    assert body["demo_mode"] is True
    assert body["auth_mode"] == "single_user_local"


def test_demo_mode_serves_data_without_a_token(tmp_path: Path) -> None:
    with _client(tmp_path, demo_mode=True) as client:
        response = client.get("/api/v1/tools")
    assert response.status_code == 200


def test_ready_reports_demo_mode_off_by_default(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/v1/ready").json()["demo_mode"] is False


@pytest.fixture()
def static_dir(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>AgentVault</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the static root", encoding="utf-8")
    return dist


def test_static_files_and_spa_fallback(tmp_path: Path, static_dir: Path) -> None:
    with _client(tmp_path, static_dir=static_dir) as client:
        assert "AgentVault" in client.get("/").text
        assert client.get("/assets/app.js").text == "console.log('ok')"
        # Client-side routes fall back to the app shell.
        assert "AgentVault" in client.get("/approvals").text


def test_static_serving_never_shadows_the_api(tmp_path: Path, static_dir: Path) -> None:
    with _client(tmp_path, static_dir=static_dir) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        assert client.get("/api/v1/does-not-exist").status_code == 404
        assert client.get("/api/unknown").status_code == 404


def test_static_serving_does_not_escape_its_directory(tmp_path: Path, static_dir: Path) -> None:
    with _client(tmp_path, static_dir=static_dir) as client:
        response = client.get("/..%2Fsecret.txt")
    assert "outside the static root" not in response.text


def test_static_dir_without_index_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match=r"index\.html"):
        create_app(make_settings(static_dir=empty))
