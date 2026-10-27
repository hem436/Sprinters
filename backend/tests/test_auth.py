"""Admin login (contract 01 section 7): HTTP basic auth on admin routes when ADMIN_PASSWORD is set."""

from __future__ import annotations

import base64

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app
from app.observability import store

# Routes anyone may call: chat, feedback, health, the user library and the API docs.
OPEN = {
    ("GET", "/health"),
    ("POST", "/query"),
    ("POST", "/query/stream"),
    ("POST", "/feedback"),
    ("GET", "/library"),
    ("GET", "/library/{document_id}/pages/{page}"),
}


def _basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture(autouse=True)
def event_store(config: Config) -> None:
    store.init_db(config.paths.resolve(config.paths.observability_db))


@pytest.fixture
def locked(config: Config) -> TestClient:
    config.secrets.admin_username = "admin"
    config.secrets.admin_password = "s3cret"
    return TestClient(create_app(config), raise_server_exceptions=False)


def test_no_password_keeps_admin_routes_open(client: TestClient) -> None:
    assert client.get("/metrics/summary").status_code == 200
    assert client.get("/auth/me").json() == {"username": None, "login_required": False}


def test_missing_or_wrong_login_is_401_without_browser_prompt(locked: TestClient) -> None:
    for headers in ({}, _basic("admin", "wrong"), _basic("someone", "s3cret"), {"Authorization": "Basic not-base64"}):
        r = locked.get("/metrics/summary", headers=headers)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"
        assert "www-authenticate" not in r.headers
        assert r.headers.get("X-Request-Id")


def test_right_login_opens_admin_routes(locked: TestClient) -> None:
    ok = _basic("admin", "s3cret")
    assert locked.get("/metrics/summary", headers=ok).status_code == 200
    assert locked.get("/tools", headers=ok).status_code == 200
    assert locked.get("/auth/me", headers=ok).json() == {"username": "admin", "login_required": True}


def test_open_routes_need_no_login(locked: TestClient) -> None:
    assert locked.get("/health").status_code == 200
    # Feedback on an unknown query is 404, not 401: the route is open.
    assert locked.post("/feedback", json={"query_id": "nope", "helpful": True}).status_code == 404


def test_every_other_route_needs_the_login(locked: TestClient) -> None:
    """A new admin route that forgets require_admin fails here."""
    checked = 0
    for route in locked.app.routes:
        if not isinstance(route, APIRoute) or route.path.startswith(("/docs", "/openapi", "/redoc")):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (method, route.path) in OPEN:
                continue
            path = route.path.replace("{page}", "1")
            for name in ("document_id", "query_id", "run_id", "table_id", "name"):
                path = path.replace("{" + name + "}", "x")
            r = locked.request(method, path)
            assert r.status_code == 401, (method, route.path, r.status_code)
            checked += 1
    assert checked >= 20
