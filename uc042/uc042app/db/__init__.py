"""Database access: engine and session factory for UC042_DATABASE_URL, and the Alembic schema check.

PostgreSQL is the operational database. The schema is managed ONLY by Alembic migrations (uc042app/db/migrations);
the application refuses to start against a database whose schema is not at the latest migration. For offline tests a
SQLite URL may be used, in which case the tables are created directly from the models (create_all)."""
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from .models import SCHEMAS, Base

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


class DatabaseNotReady(Exception):
    """The database schema is missing or not at the latest migration."""


def make_engine(url):
    kwargs = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # SQLite has no schemas: the audit and operations tables share its single namespace (names do not collide).
        kwargs["execution_options"] = {"schema_translate_map": {s: None for s in SCHEMAS}}
    return create_engine(url, **kwargs)


def make_sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)


def alembic_config(url):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url, revision="head"):
    """Apply migrations (python -m uc042app.admin db-upgrade)."""
    from alembic import command
    command.upgrade(alembic_config(url), revision)


def check_schema(engine):
    """Refuse to run against an unmigrated database (PostgreSQL) instead of creating tables implicitly."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    head = ScriptDirectory.from_config(alembic_config(str(engine.url))).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current != head:
        raise DatabaseNotReady(f"database schema is at {current or 'no revision'}, expected {head}: run "
                               "`python -m uc042app.admin db-upgrade`")


def create_all_for_tests(engine):
    """SQLite / test databases only: create the tables directly from the models."""
    Base.metadata.create_all(engine)
    return sorted(inspect(engine).get_table_names())
