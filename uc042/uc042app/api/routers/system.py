"""Health (no secrets)."""
from pathlib import Path

from fastapi import APIRouter, Depends

from uc042lib.investigation import config as inv_config

from ..deps import services
from ..schemas import Health

VERSION = "uc042-backend/0.3-local"


def environment(settings, layout=None):
    """The data environment (database name, primary packs root and the storage profiles served; never credentials). One
    database holds every period; the storage profiles say which artefact folders the backend reads them from."""
    database = None
    if settings.database_url:
        from sqlalchemy.engine import make_url
        database = make_url(settings.database_url).database
    root = Path(settings.packs_root).resolve()
    shown = root.relative_to(inv_config.PROJECT).as_posix() if inv_config.PROJECT in root.parents else root.name
    label = settings.environment_label or (f"Database {database}" if database else "File-backed state (no database)")
    return {"label": label, "database": database, "packs_root": shown, "storage_profiles": layout.names if layout else ["primary"]}
health = APIRouter(tags=["health"])


@health.get("/health", response_model=Health, summary="Liveness and dependency status (no secrets)")
def get_health(svc=Depends(services)):
    storage, registry = svc.storage_ok(), not svc.registry.problems()
    database = svc.database_ok() if svc.database else None
    return {"status": "ok" if storage and registry and database is not False else "degraded", "storage": storage,
            "registry": registry, "provider_configured": inv_config.api_key_configured(), "analyst_id": svc.settings.analyst_id,
            "version": VERSION, "database": database, "environment": environment(svc.settings, svc.layout)}
