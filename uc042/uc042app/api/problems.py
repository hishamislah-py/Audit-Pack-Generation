"""RFC 7807 problem-details responses for every error. Unexpected exceptions are logged server-side with their trace
and answered with a generic 500 that carries no internal detail."""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..errors import AppError

log = logging.getLogger("uc042app.api")
MEDIA = "application/problem+json"
TITLES = {400: "Bad request", 403: "Not permitted", 404: "Not found", 405: "Method not allowed",
          409: "Conflict", 422: "Invalid request", 500: "Internal error", 503: "Service unavailable"}


def problem(status, code, detail, title=None, **extra):
    body = {"type": "about:blank", "title": title or TITLES.get(status, "Error"), "status": status, "detail": detail, "code": code}
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=MEDIA)


async def app_error(request: Request, exc: AppError):
    if exc.status >= 500:
        log.error("%s %s -> %s %s", request.method, request.url.path, exc.code, exc.detail)
    return problem(exc.status, exc.code, exc.detail, exc.title, **exc.extra)


async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"location": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "")} for e in exc.errors()][:20]
    return problem(422, "VALIDATION_ERROR", "the request is not valid", errors=errors)


async def http_error(request: Request, exc: StarletteHTTPException):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return problem(exc.status_code, code, str(exc.detail) if exc.status_code != 404 else "not found")


async def unexpected_error(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return problem(500, "INTERNAL_ERROR", "an unexpected error occurred; it has been logged")


def install(app):
    app.add_exception_handler(AppError, app_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(Exception, unexpected_error)
