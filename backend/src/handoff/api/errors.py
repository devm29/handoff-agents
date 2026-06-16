from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from handoff.errors import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)

log = structlog.get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


def _respond(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return _respond(404, "not_found", str(exc))

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
        return _respond(409, "conflict", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            f"{'.'.join(str(p) for p in error['loc'] if p != 'body')}: {error['msg']}"
            for error in exc.errors()
        ]
        return _respond(422, "validation_error", "; ".join(problems) or "The request is invalid.")

    @app.exception_handler(ValidationError)
    async def _invalid(_: Request, exc: ValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else None
        where = ".".join(str(p) for p in first["loc"]) if first else ""
        detail = f"{where}: {first['msg']}" if first else str(exc)
        return _respond(422, "invalid_state", detail)

    @app.exception_handler(BadRequestError)
    async def _bad_request(_: Request, exc: BadRequestError) -> JSONResponse:
        return _respond(400, "bad_request", str(exc))

    @app.exception_handler(AuthenticationError)
    async def _unauthenticated(_: Request, exc: AuthenticationError) -> JSONResponse:
        response = _respond(401, "unauthenticated", str(exc) or "Sign in to continue.")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(PermissionDeniedError)
    async def _forbidden(_: Request, exc: PermissionDeniedError) -> JSONResponse:
        return _respond(403, "forbidden", str(exc))

    @app.exception_handler(UnprocessableError)
    async def _refused(_: Request, exc: UnprocessableError) -> JSONResponse:
        return _respond(422, "refused", str(exc))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled_error", path=request.url.path)
        return _respond(500, "internal_error", "Something went wrong on our side. The error has been logged.")
