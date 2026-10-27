"""X-Request-Id on every response (contract 05).

Each request gets a new ULID. A route may set the header itself (POST /query sets it to
the query_id) and that wins. Pure ASGI, so streaming responses (SSE) pass through untouched.
"""

from __future__ import annotations

import json
import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import error_body
from app.ids import new_ulid
from app.logging_setup import request_id_var

HEADER = "X-Request-Id"
log = logging.getLogger("app.request")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_ulid()
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started, status = True, message["status"]
                headers = list(message.get("headers", []))
                if not any(k.lower() == HEADER.lower().encode() for k, _ in headers):
                    headers.append((HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Starlette re-raises unhandled errors past the app; answer here so the 500 carries the id.
            if not response_started:
                body = json.dumps(error_body("INTERNAL_ERROR", "Something went wrong on our side.")).encode()
                await send_with_id({"type": "http.response.start", "status": 500,
                                    "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
        finally:
            log.info("request", extra={"method": scope.get("method"), "path": scope.get("path"), "status": status,
                                       "latency_ms": round((time.perf_counter() - started) * 1000)})
            request_id_var.reset(token)
