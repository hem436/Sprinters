"""One error format for every endpoint (contract 05):

{"error": {"code": "UPPER_SNAKE", "message": "...", "fields": [{"field": "...", "problem": "..."}]}}
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_STATUS_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


class ApiError(Exception):
    """Raise from any route or service to return a contract error.

    raise ApiError(409, "DUPLICATE_DOCUMENT", "This file was already uploaded.")
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or []
        self.headers = headers


def error_body(code: str, message: str, fields: list[dict[str, str]] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "fields": fields or []}}


def _field_name(loc: tuple) -> str:
    # Drop the "body" / "query" / "path" prefix so the field reads like the request.
    if loc and loc[0] in ("body", "query", "path", "header"):
        loc = loc[1:]
    return ".".join(str(p) for p in loc) or "request"


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        error_body(exc.code, exc.message, exc.fields), status_code=exc.status_code, headers=exc.headers
    )


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [{"field": _field_name(tuple(e.get("loc", ()))), "problem": e.get("msg", "invalid")} for e in exc.errors()]
    return JSONResponse(error_body("INVALID_REQUEST", "The request has invalid fields.", fields), status_code=422)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None))


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    # Never leak internals; the request id in the header links the user to the log line.
    log.exception("unhandled error", extra={"error_type": type(exc).__name__})
    return JSONResponse(error_body("INTERNAL_ERROR", "Something went wrong on our side."), status_code=500)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled_error)
