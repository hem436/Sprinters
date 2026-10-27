"""Admin login (contract 01 section 7): HTTP basic auth on the admin and reviewer routes.

ADMIN_USERNAME and ADMIN_PASSWORD come from .env. With no ADMIN_PASSWORD the admin routes stay open, as the
team decided for the demo (issue 48). Chat, feedback, health and the library never need a login.

A 401 carries no WWW-Authenticate header: the web app shows its own login page, and that header would make
the browser open its built-in password dialog instead.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from fastapi import APIRouter, Depends, Request

from app.api.errors import ApiError
from app.config import Config, get_config

router = APIRouter(tags=["auth"])

DEFAULT_USERNAME = "admin"


def login_required(config: Config) -> bool:
    return bool(config.secrets.admin_password)


def _basic_credentials(header: str) -> tuple[str, str] | None:
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        return None
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, sep, password = decoded.partition(":")
    return (username, password) if sep else None


def _same(given: str, wanted: str) -> bool:
    return secrets.compare_digest(given.encode("utf-8"), wanted.encode("utf-8"))


def require_admin(request: Request, config: Config = Depends(get_config)) -> str | None:
    """Route dependency. Returns the admin's user name, or None when no password is set."""
    if not login_required(config):
        return None
    credentials = _basic_credentials(request.headers.get("Authorization", ""))
    wanted_user = config.secrets.admin_username or DEFAULT_USERNAME
    if credentials is None:
        raise ApiError(401, "UNAUTHORIZED", "Log in as an admin to use this page.")
    # Compare both parts every time, so a wrong user name takes as long as a wrong password.
    if not (_same(credentials[0], wanted_user) & _same(credentials[1], config.secrets.admin_password)):
        raise ApiError(401, "UNAUTHORIZED", "Log in as an admin to use this page.")
    return credentials[0]


@router.get("/auth/me")
def me(username: str | None = Depends(require_admin), config: Config = Depends(get_config)) -> dict:
    """The web app's login page calls this to check a user name and password before it saves them."""
    return {"username": username, "login_required": login_required(config)}
