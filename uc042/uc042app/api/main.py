"""FastAPI application factory for the local single-analyst POC.

    python -m uc042app                      # 127.0.0.1:8000, one process (see __main__.py)

There is no authentication: the API must only be reachable from the local machine. It is started bound to 127.0.0.1,
and requests from any non-loopback client are refused (403 LOCAL_ONLY) as a second guard. One backend process per
application-state directory: the locks are in-process, and a second process is refused by the instance lock.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Settings
from ..services import Services
from . import problems
from .routers import cases, final_packs, investigations, monthly, packs, reviews, system

log = logging.getLogger("uc042app")
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}  # "testclient": FastAPI's in-process test client


def create_app(settings=None, investigator_factory=None):
    """Build the app. Settings come from the environment unless given; the investigator factory defaults to the
    existing investigator_from_env (tests inject a mocked provider)."""
    settings = settings or Settings.from_env()
    svc = Services(settings, investigator_factory)

    @asynccontextmanager
    async def lifespan(app):
        svc.start()
        try:
            yield
        finally:
            svc.stop()

    app = FastAPI(title="UC-042 Audit Pack Backend (local POC)", version=system.VERSION, lifespan=lifespan,
                  description="Local, single-analyst API around the UC-042 deterministic engine, AI investigation V2 and final "
                              "audit-pack library. Bound to 127.0.0.1; no authentication. Synthetic data only; not a "
                              "compliance opinion.")
    app.state.services = svc
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type"],
                       expose_headers=["ETag", "X-Snapshot-SHA256"])

    @app.middleware("http")
    async def local_only_and_headers(request, call_next):
        if (request.client.host if request.client else "") not in LOOPBACK:
            return problems.problem(403, "LOCAL_ONLY", "this local POC API only accepts requests from the local machine")
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    problems.install(app)
    for router in (system.health, packs.router, investigations.router, reviews.router, final_packs.router, monthly.router,
                   cases.router):
        app.include_router(router)
    return app
