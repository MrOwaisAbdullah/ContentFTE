"""Alembic environment: the engine's own database, the engine's own models."""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from lib.db import Base, database_url

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return database_url()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connect_args = {"check_same_thread": False} if _url().startswith("sqlite") else {}
    engine = create_engine(_url(), poolclass=pool.NullPool, connect_args=connect_args)
    with engine.connect() as connection:
        # render_as_batch: SQLite cannot ALTER most things in place; batch mode recreates the table.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
