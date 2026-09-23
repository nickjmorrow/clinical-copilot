"""Test-wide environment setup.

**The environment block below runs at import time and must stay above every
`app` import.** Three module-level globals are built from settings when
`app.config` and `app.db` are first imported — `settings`, `engine`, and
`SessionFactory` — and there is no later hook that can redirect them at a
database. Move an `app` import above this and the suite quietly runs against
your development database.

Only the environment lives here. The fixtures that *build* a database are in
`tests/integration/conftest.py`, one directory down, and that placement is
load-bearing rather than tidy: an autouse session fixture applies to every test
below the conftest that defines it, so keeping it here would mean `tests/unit`
and `tests/structure` could not run without Postgres. They have no business
needing it, and the pre-commit hook runs exactly those two.
"""

import os

# Where to create the test database. Points at docker-compose's db by default,
# so `docker compose up db -d && uv run pytest` works with no setup.
ADMIN_DSN = os.environ.get(
    "TEST_DATABASE_ADMIN_DSN", "postgresql://app:app@localhost:5433/postgres"
)
# One database per xdist worker, not one shared by all of them. `pytest-xdist`
# sets `PYTEST_XDIST_WORKER` to `gw0`, `gw1`, ... in each worker process and
# leaves it unset outside `-n`; a shared name would mean two workers racing
# `drop database ... with (force)` against a database the other is mid-test on.
_worker = os.environ.get("PYTEST_XDIST_WORKER")
TEST_DB = "test_clinical_copilot" if _worker is None else f"test_clinical_copilot_{_worker}"
_base = ADMIN_DSN.rsplit("/", 1)[0]

os.environ["DATABASE_URL"] = f"{_base.replace('postgresql://', 'postgresql+asyncpg://')}/{TEST_DB}"
os.environ.setdefault("LOG_LEVEL", "warning")
