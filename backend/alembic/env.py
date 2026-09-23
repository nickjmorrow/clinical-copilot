"""Alembic environment.

Two things worth knowing before editing this:

* **`app/models.py` is the source of truth.** `--autogenerate` diffs those
  classes against the live database. Anything not declared there does not exist
  as far as Alembic is concerned, so a CHECK constraint or a partial index left
  off a model is one Alembic will happily drop.
* **The engine is async**, because the app's is. Alembic's own API is
  synchronous, so the connection is handed across with `run_sync`.

Always read the generated revision before applying it. Autogenerate is a good
first draft and a bad last word — it cannot see a rename (it emits a drop and an
add, which is a data-loss bug wearing a migration's clothes), and it does not
detect CHECK constraint changes at all unless you name them, which is why the
constraints in models.py all carry explicit names.
"""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without these, autogenerate silently ignores a column whose type or
        # default changed — the diff comes back empty and you conclude the
        # schema is in sync when it is not.
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it — `alembic upgrade head --sql`.

    Useful when someone else applies migrations, or for reading exactly what a
    revision will do before it does it.
    """
    context.configure(
        url=settings.database_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: this process runs migrations and exits. A pool would only
        # hold connections open past the point anything needs them.
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
