"""Backend settings, read from environment variables. The OpenAI key stays in the investigation layer's own configuration
(uc042/.env); nothing here is secret.

Local POC: one analyst, one backend process, bound to 127.0.0.1. There is no authentication; the reviewer recorded in a
decision is the configured analyst reference (UC042_ANALYST_ID / UC042_ANALYST_NAME)."""
import os
from dataclasses import dataclass, replace
from pathlib import Path

from uc042lib.investigation import config as inv_config
from uc042lib.runtime_paths import default_final_packs_root, inside_project

ENV_STATE_DIR = "UC042_APP_STATE_DIR"            # application state (jobs, reviews, decisions, registry)
ENV_ANALYST_ID = "UC042_ANALYST_ID"              # reviewer reference written into decisions and final packs
ENV_ANALYST_NAME = "UC042_ANALYST_NAME"
ENV_CORS_ORIGINS = "UC042_CORS_ORIGINS"          # comma-separated; default: the local React dev server
ENV_JOB_WORKERS = "UC042_JOB_WORKERS"
ENV_AI_JOB_WORKERS = "UC042_AI_JOB_WORKERS"      # concurrent AI investigations (bounded lane; default 1)
ENV_PACKS_ROOT = "UC042_PACKS_ROOT"
ENV_INVESTIGATIONS_ROOT = "UC042_INVESTIGATIONS_ROOT"
ENV_FINAL_PACKS_ROOT = "UC042_FINAL_PACKS_ROOT"  # primary final packs; must be outside the repository (default: user data dir)
ENV_DATASETS_ROOT = "UC042_DATASETS_ROOT"        # source datasets of the packs in UC042_PACKS_ROOT (default: September)
ENV_DATABASE_URL = "UC042_DATABASE_URL"        # PostgreSQL (postgresql+pg8000://...); unset = file-backed state only
ENV_DOCUMENT_STORE = "UC042_DOCUMENT_STORE"    # uploaded originals (content-addressed) and processing case folders
ENV_ENVIRONMENT_LABEL = "UC042_ENVIRONMENT_LABEL"  # shown in the UI to identify the active data environment (optional)
# Additional storage profiles to serve (comma-separated names from uc042lib.investigation.roots.PROFILES). Profiles recorded
# on periods in the database are always served as well; this is only needed before the database records any.
ENV_STORAGE_PROFILES = "UC042_STORAGE_PROFILES"

DEFAULT_STATE_DIR = inv_config.PROJECT / "app_state"
DEFAULT_DOCUMENT_STORE = inv_config.PROJECT / "document_store"
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


class ConfigurationError(Exception):
    """The backend cannot start safely with the current configuration."""


def _workers():
    raw = os.environ.get(ENV_JOB_WORKERS, "").strip() or "2"
    if not raw.isdigit() or not 1 <= int(raw) <= 8:
        raise ConfigurationError(f"{ENV_JOB_WORKERS} must be an integer from 1 to 8")
    return int(raw)


def _ai_workers():
    raw = os.environ.get(ENV_AI_JOB_WORKERS, "").strip() or "1"
    if not raw.isdigit() or not 1 <= int(raw) <= 4:
        raise ConfigurationError(f"{ENV_AI_JOB_WORKERS} must be an integer from 1 to 4")
    return int(raw)


@dataclass(frozen=True)
class Settings:
    state_dir: Path
    packs_root: Path
    investigations_root: Path
    final_packs_root: Path
    datasets_root: Path
    cors_origins: tuple
    job_workers: int
    analyst_id: str
    analyst_name: str
    database_url: str | None = None
    document_store: Path | None = None
    environment_label: str = ""
    storage_profiles: tuple = ()
    ai_job_workers: int = 1
    # ZIP-only operation (17 Nov 2026): the individual-document upload / confirm / process / reconcile / document-review
    # workflow is retired from active use. This switch is deliberately NOT read from the environment (from_env never sets
    # it): a running application cannot re-enable the retired entry points. Only code (the regression tests that keep
    # covering the retired workflow's shared engine path on historical-style data) can pass legacy_entry_points=True.
    legacy_entry_points: bool = False

    @classmethod
    def from_env(cls, **overrides):
        def path(name, default):
            return Path(os.environ.get(name, "").strip() or default).resolve()
        origins = tuple(o.strip() for o in os.environ.get(ENV_CORS_ORIGINS, "").split(",") if o.strip()) or DEFAULT_CORS_ORIGINS
        values = dict(state_dir=path(ENV_STATE_DIR, DEFAULT_STATE_DIR), packs_root=path(ENV_PACKS_ROOT, inv_config.PACKS_ROOT),
                      investigations_root=path(ENV_INVESTIGATIONS_ROOT, inv_config.INVESTIGATIONS_ROOT),
                      final_packs_root=path(ENV_FINAL_PACKS_ROOT, default_final_packs_root()),
                      datasets_root=path(ENV_DATASETS_ROOT, inv_config.DATASETS_ROOT),
                      cors_origins=origins, job_workers=_workers(), ai_job_workers=_ai_workers(),
                      analyst_id=os.environ.get(ENV_ANALYST_ID, "").strip() or "local-analyst",
                      analyst_name=os.environ.get(ENV_ANALYST_NAME, "").strip() or "Local Analyst",
                      database_url=os.environ.get(ENV_DATABASE_URL, "").strip() or None,
                      document_store=path(ENV_DOCUMENT_STORE, DEFAULT_DOCUMENT_STORE),
                      environment_label=os.environ.get(ENV_ENVIRONMENT_LABEL, "").strip()[:80],
                      storage_profiles=tuple(p.strip() for p in os.environ.get(ENV_STORAGE_PROFILES, "").split(",") if p.strip()))
        values.update(overrides)
        settings = cls(**values)
        settings.check()
        return settings

    def with_(self, **changes):
        return replace(self, **changes)

    @property
    def reviewer(self):
        return {"user_id": self.analyst_id, "display_name": self.analyst_name}

    def check(self):
        """Application state must never live inside the controlled artefact or dataset folders. The packs and datasets
        roots are the AI investigation's input roots: they must exist and stay outside verification and answer material
        (uc042lib.investigation.roots); a bad root stops the backend instead of falling back to September."""
        from uc042lib.investigation.roots import InvestigationRootsError, check_input_root
        for label, root in (("packs", self.packs_root), ("datasets", self.datasets_root)):
            try:
                check_input_root(root, label)
            except InvestigationRootsError as e:
                raise ConfigurationError(str(e)) from None
        for label, own in (("application state", self.state_dir), ("document store", self.document_store)):
            if own is None:
                continue
            own = Path(own).resolve()
            for name, root in (("packs", self.packs_root), ("investigations", self.investigations_root),
                               ("final packs", self.final_packs_root), ("datasets", self.datasets_root)):
                root = Path(root).resolve()
                if own == root or root in own.parents or own in root.parents:
                    raise ConfigurationError(f"the {label} directory must be separate from the {name} folder")
        # Published final packs are runtime output: never inside the source repository (they would mix with the source
        # tree and the historical artefacts it protects). The historical-demo profile keeps its own fixed location.
        if inside_project(self.final_packs_root):
            raise ConfigurationError(f"{ENV_FINAL_PACKS_ROOT} must be outside the source repository ({self.final_packs_root}); "
                                     "set it to an absolute directory for published final packs")
        if "*" in self.cors_origins:
            raise ConfigurationError("a wildcard CORS origin is not allowed; list the frontend origin explicitly")
        if not (self.analyst_id and self.analyst_name):
            raise ConfigurationError("the analyst reference and name must not be empty")
