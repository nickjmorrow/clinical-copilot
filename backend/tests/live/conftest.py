"""Fixtures for the tests that call a real model.

This directory exists so that `scripts/check.sh` cannot run these by accident.
It runs `tests/unit tests/structure` and `tests/integration` by name; `tests/live`
is in neither list, and that is the whole gate. No marker, no `--skip-live`
flag, no environment variable that someone sets once and forgets — the
directory is the interface, the same way `integration/` is.

Run them deliberately:

    cd backend && uv run pytest tests/live

They need `ANTHROPIC_API_KEY`, a Postgres on 5433, and they cost money. They
are also non-deterministic by nature: a failure here means "the model chose
differently today", which is worth knowing and is not the same kind of fact as
a red build.
"""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.db import SessionFactory, engine
from app.services import definition_service
from tests.conftest import ADMIN_DSN, TEST_DB

BACKEND_ROOT = Path(__file__).resolve().parents[2]

TABLES = (
    "conversations, event_records, tasks, schedules, "
    "query_audit, observations, observation_catalog, prescriptions, patients, "
    "medication_annotations, medications, clinical_definitions, "
    "clinical_definition_history, dataset_meta, saved_questions, user_roles"
)


def _migrate() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def _requires_a_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set; the live suite needs a real model")


@pytest.fixture(scope="session", autouse=True)
async def _database(_requires_a_key):
    assert TEST_DB.startswith("test_"), "refusing to drop a database not named test_*"

    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f'drop database if exists "{TEST_DB}" with (force)')
    await admin.execute(f'create database "{TEST_DB}"')
    await admin.close()

    await asyncio.to_thread(_migrate)
    yield

    await engine.dispose()
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f'drop database if exists "{TEST_DB}" with (force)')
    await admin.close()


@pytest.fixture(autouse=True)
async def _clean_between_tests():
    yield
    # The definitions cache is module-level state, so it outlives a TRUNCATE.
    # Without this a test that empties the table still sees the previous
    # test's vocabulary, which is the same hazard the truncate exists to
    # prevent — just held in a different place.
    definition_service.invalidate()
    async with SessionFactory() as session:
        await session.execute(text(f"truncate {TABLES} restart identity cascade"))
        await session.commit()


@pytest.fixture
async def session():
    async with SessionFactory() as session:
        yield session
