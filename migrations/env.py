"""Run the project's versioned PostgreSQL/PostGIS migrations."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

database_url = os.getenv("FLOODCAT_DATABASE_URL")
if not database_url or not database_url.startswith("postgresql+"):
    raise RuntimeError("Set FLOODCAT_DATABASE_URL to a PostgreSQL URL")


def run_migrations_offline():
    context.configure(
        url=database_url, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
