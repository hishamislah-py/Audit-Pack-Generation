"""Alembic environment for the UC-042 application-state schema. The URL comes from the Config built by
uc042app.db.alembic_config (or UC042_DATABASE_URL when alembic is run directly)."""
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from uc042app.db.models import Base

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", os.environ["UC042_DATABASE_URL"].replace("%", "%%"))
target_metadata = Base.metadata


def run_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
