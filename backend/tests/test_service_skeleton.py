"""WP-BE1: error format, request ids, config loader, /health."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api import health
from app.api.errors import ApiError
from app.config import DEFAULT_CONFIG_PATH, Config, load_config
from app.main import create_app


class Body(BaseModel):
    question: str
    top_k: int


def _app_with_probe_routes(config: Config) -> TestClient:
    app = create_app(config)

    @app.get("/_probe/conflict")
    def conflict():
        raise ApiError(409, "DUPLICATE_DOCUMENT", "Already uploaded.")

    @app.post("/_probe/body")
    def body(payload: Body):
        return payload

    @app.get("/_probe/boom")
    def boom():
        raise RuntimeError("secret internal detail")


    return TestClient(app, raise_server_exceptions=False)


# Error format

def test_api_error_uses_contract_shape(config):
    resp = _app_with_probe_routes(config).get("/_probe/conflict")
    assert resp.status_code == 409
    assert resp.json() == {"error": {"code": "DUPLICATE_DOCUMENT", "message": "Already uploaded.", "fields": []}}


def test_validation_error_lists_fields(config):
    resp = _app_with_probe_routes(config).post("/_probe/body", json={"top_k": "many"})
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert {f["field"] for f in error["fields"]} == {"question", "top_k"}


def test_unknown_route_is_not_found_in_contract_shape(client):
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_unhandled_error_hides_details(config):
    resp = _app_with_probe_routes(config).get("/_probe/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in resp.text
    assert resp.headers["X-Request-Id"]


# Request ids

def test_every_response_has_a_request_id(client):
    first = client.get("/health").headers["X-Request-Id"]
    second = client.get("/no-such-route").headers["X-Request-Id"]
    assert len(first) == 26 and len(second) == 26
    assert first != second


# Config loader

def test_config_reads_contract_keys():
    cfg = load_config(DEFAULT_CONFIG_PATH, environ={})
    assert cfg.get("obs.grounding_min") == 0.8
    assert cfg.get("tools.timeout_ms") == 2000
    assert cfg.get("no.such.key", "default") == "default"


def test_env_overrides_typed_and_untyped_sections():
    cfg = load_config(
        DEFAULT_CONFIG_PATH,
        environ={"APP__QDRANT__URL": "http://qdrant:6333", "APP__OBS__GROUNDING_MIN": "0.9"},
    )
    assert cfg.qdrant.url == "http://qdrant:6333"
    assert cfg.get("obs.grounding_min") == 0.9


def test_secrets_never_serialised():
    cfg = load_config(DEFAULT_CONFIG_PATH, environ={})
    assert "secrets" not in cfg.model_dump()


# /health (true or false values, as the web app's Health type reads them)

def test_health_is_down_without_business_db(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "qdrant", "llm", "ocr_available", "reranker", "db"}
    assert all(isinstance(body[k], bool) for k in ("qdrant", "llm", "ocr_available", "reranker", "db"))
    assert (body["status"], body["db"], body["qdrant"]) == ("down", False, False)


def test_health_degraded_then_ok(client, config, monkeypatch):
    import sqlite3

    sqlite3.connect(config.paths.resolve(config.paths.business_db)).close()
    body = client.get("/health").json()
    assert (body["status"], body["db"], body["llm"]) == ("degraded", True, True)

    async def qdrant_up(_config):
        return True

    monkeypatch.setattr(health, "check_qdrant", qdrant_up)
    assert client.get("/health").json()["status"] == "ok"
