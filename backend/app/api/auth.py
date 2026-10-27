"""require_admin: HTTP Basic for admin and reviewer routes (contract 01 section 7).

In the demo KNOWLEDGE_ADMIN and REVIEWER share one password (case 4.2 puts identity
out of scope). If ADMIN_PASSWORD is not set, every admin route refuses.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.api.errors import ApiError
from app.config import Config, get_config

log = logging.getLogger(__name__)
_basic = HTTPBasic(auto_error=False)
_CHALLENGE = {"WWW-Authenticate": 'Basic realm="admin"'}


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    config: Config = Depends(get_config),
) -> str:
    expected_password = config.secrets.admin_password
    if not expected_password:
        log.warning("admin route called but ADMIN_PASSWORD is not set")
        raise ApiError(401, "UNAUTHORIZED", "Admin access is not configured on this server.", headers=_CHALLENGE)
    if credentials is None:
        raise ApiError(401, "UNAUTHORIZED", "Admin credentials are required.", headers=_CHALLENGE)

    # Compare both parts in constant time, and always both, so timing does not reveal which was wrong.
    user_ok = secrets.compare_digest(credentials.username.encode(), config.secrets.admin_user.encode())
    password_ok = secrets.compare_digest(credentials.password.encode(), expected_password.encode())
    if not (user_ok and password_ok):
        raise ApiError(401, "UNAUTHORIZED", "The admin user name or password is wrong.", headers=_CHALLENGE)
    return credentials.username
