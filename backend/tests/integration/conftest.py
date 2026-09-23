"""The database, for the tests that need one.

Isolation is one disposable database per test session, with a TRUNCATE between
tests. Not a transaction rolled back per test, which is faster but would defeat
the four things most worth testing here:

* the worker and the streaming endpoint open their own sessions from the global
  `SessionFactory`, on a different connection, and would never see uncommitted
  rows;
* `claim_next` is `for update skip locked`, which needs two concurrent
  transactions to mean anything, and inside one outer transaction there is only
  ever one;
* `pg_notify` delivers at COMMIT, so in a transaction that always rolls back no
  notification is ever delivered and every bus test silently sees nothing.

TRUNCATE on empty tables costs a millisecond or two. That is the whole saving
being passed up, and it buys back the tests that matter.

**The clinical dataset is the one thing NOT in that TRUNCATE, and that is new.**
It used to be — "252 patients reloading per test is still cheap" — and that was
true of the old hand-rolled seed. It stopped being true the moment the fixture
became a real Synthea export: 111 patients and ~79,500 observations, reseeded
through `seed_service.seed_all` (real `COPY`s, not a fixture-in-memory trick),
cost about 2.4 seconds. Paid once per test across the ~100 tests that need
clinical data, that was most of a 37-minute suite for a fixed cost that never
actually varied between them.

So `CLINICAL_TABLES` is loaded **once, for the whole session**, by
`_seed_clinical_data` below, and is deliberately absent from `APP_STATE_TABLES`
— the per-test TRUNCATE list. A test that seeds cannot leak its cohort into the
next one only holds if nothing mutates the shared cohort; the handful of tests
that must intentionally corrupt a definition or insert a stray observation
clean up after themselves instead of leaning on a blanket reset — see
`test_clinical_query.py`'s cache-freshness and unusable-definition tests, and
`test_access_routes.py` / `test_saved_question_routes.py`'s scope tests. Grep
for `CLINICAL_TABLES` before adding a test that writes to one of these tables:
if it does not restore what it changed, it is a bug the next test file will
report as its own.

`test_seed.py` is unaffected — it calls `seed_service.seed_all(..., reset=True)`
itself, explicitly, which still clears and reloads everything regardless of
what this file does between tests. That is the one place a full reseed is the
actual thing under test, not overhead to avoid.

These fixtures live here rather than in `tests/conftest.py` because autouse
reaches downward only. `tests/unit` and `tests/structure` sit beside this
directory, not below it, so they run with no Postgres anywhere in sight.
"""

import asyncio
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.db import SessionFactory, engine
from app.services import definition_service, seed_service
from tests.conftest import ADMIN_DSN, TEST_DB
from tests.support.fixture import FIXTURE_SOURCE

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Reference data: real rows from the fixture, expensive to reload, and — with
# the exception of the handful of self-cleaning tests named in the module
# docstring — nothing in this suite is supposed to mutate them. Seeded once by
# `_seed_clinical_data`, never truncated by `_clean_between_tests`.
CLINICAL_TABLES = (
    "observations, observation_catalog, prescriptions, patients, "
    "medication_annotations, medications, clinical_definitions, "
    "clinical_definition_history, dataset_meta, user_roles"
)

# Per-test state: cheap, small, and genuinely different for every test.
# Truncated between every test, same as always.
APP_STATE_TABLES = (
    "conversations, event_records, tasks, schedules, query_audit, saved_questions, usage_events"
)


def _migrate() -> None:
    """Build the schema the same way production does.

    `alembic upgrade head`, not `Base.metadata.create_all()`. They are supposed
    to agree, and testing against the one that is not deployed is how you find
    out they stopped agreeing only after a release.
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
async def _database():
    assert TEST_DB.startswith("test_"), "refusing to drop a database not named test_*"

    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f'drop database if exists "{TEST_DB}" with (force)')
    await admin.execute(f'create database "{TEST_DB}"')
    await admin.close()

    # In a thread, because alembic/env.py ends in `asyncio.run(...)` — Alembic's
    # entry point is synchronous by design, and this fixture is already inside a
    # running loop. A fresh thread has no loop for it to collide with.
    await asyncio.to_thread(_migrate)
    yield

    await engine.dispose()
    admin = await asyncpg.connect(ADMIN_DSN)
    await admin.execute(f'drop database if exists "{TEST_DB}" with (force)')
    await admin.close()


@pytest.fixture(scope="session", autouse=True)
async def _seed_clinical_data(_database: None) -> None:
    """The fixture, loaded once for the whole session — not once per test.

    Depends on `_database` explicitly (the parameter, unused otherwise) so
    pytest orders this after the schema exists, rather than relying on
    fixture-registration order, which is not a dependency.
    """
    async with SessionFactory() as session:
        await seed_service.seed_all(session, source=FIXTURE_SOURCE)


@pytest.fixture(autouse=True)
async def _clean_between_tests():
    yield
    # The definitions cache is module-level state, so it outlives a TRUNCATE.
    # Without this a test that empties the table still sees the previous
    # test's vocabulary, which is the same hazard the truncate exists to
    # prevent — just held in a different place.
    definition_service.invalidate()
    # RESTART IDENTITY resets event_records.seq, which is what lets a test assert
    # on `seq == 1` instead of on whatever the previous tests left behind.
    # CLINICAL_TABLES is deliberately not here — see the module docstring.
    async with SessionFactory() as session:
        await session.execute(text(f"truncate {APP_STATE_TABLES} restart identity cascade"))
        await session.commit()


@pytest.fixture
async def session():
    """A session for the test body.

    Committing in a test is fine and expected: the code under test commits, and
    the worker and streaming paths open their own sessions that must be able to
    see the result.
    """
    async with SessionFactory() as session:
        yield session
