"""WP-BE1: error format, request ids, require_admin, config loader, /health."""

from __future__ import annotations

from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api import health
from app.api.auth import require_admin
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

    @app.get("/_probe/admin")
    def admin(user: str = Depends(require_admin)):
        return {"user": user}

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


def test_valid_incoming_request_id_is_kept(client):
    resp = client.get("/health", headers={"X-Request-Id": "trace-abc_123"})
    assert resp.headers["X-Request-Id"] == "trace-abc_123"


def test_unsafe_incoming_request_id_is_replaced(client):
    resp = client.get("/health", headers={"X-Request-Id": "bad id\r\nx"})
    assert resp.headers["X-Request-Id"] != "bad id\r\nx"
    assert len(resp.headers["X-Request-Id"]) == 26


# require_admin

def test_admin_route_needs_credentials(config):
    resp = _app_with_probe_routes(config).get("/_probe/admin")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


def test_admin_route_rejects_wrong_password(config):
    resp = _app_with_probe_routes(config).get("/_probe/admin", auth=("admin", "wrong"))
    assert resp.status_code == 401


def test_admin_route_accepts_right_password(config):
    resp = _app_with_probe_routes(config).get("/_probe/admin", auth=("admin", "s3cret"))
    assert resp.status_code == 200
    assert resp.json() == {"user": "admin"}


def test_admin_route_refuses_when_no_password_configured(config):
    config.secrets.admin_password = None
    resp = _app_with_probe_routes(config).get("/_probe/admin", auth=("admin", ""))
    assert resp.status_code == 401


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


# /health

def test_health_shape_and_degraded_without_qdrant(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "qdrant", "llm", "ocr_available", "reranker", "db"}
    assert body["qdrant"] == "down"
    assert body["status"] == "degraded"
    assert body["db"] == {"observability": "ok", "knowledge": "missing", "business": "missing"}


def test_health_ok_when_dependencies_are_up(client, monkeypatch):
    async def qdrant_up(_config):
        return "ok"

    monkeypatch.setattr(health, "check_qdrant", qdrant_up)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["llm"] == "configured"
