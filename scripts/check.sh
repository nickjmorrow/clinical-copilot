#!/usr/bin/env bash
#
# Every check this repo knows how to run, in one place.
#
# Three callers, one script, on purpose: you run it by hand, `.githooks/pre-commit`
# runs it on the halves you touched, and `.github/workflows/ci.yml` runs it in
# CI. A pre-commit hook that checks something different from CI is worse than no
# hook — it teaches you to trust a green that does not mean anything.
#
#   scripts/check.sh                 everything
#   scripts/check.sh backend         backend only
#   scripts/check.sh frontend        frontend only
#   scripts/check.sh --fast          skip anything slow or stateful (see below)
#
# --fast drops the two checks that are not a pure function of the source:
# the pytest integration suite, which needs a Postgres, and `vite build`, which
# is slow and re-proves what `tsc` just proved. The hook uses it. CI does not.
#
# Failures are collected rather than fatal: one run tells you everything that is
# wrong, not the first thing.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAST=0
TARGET=all
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    backend | frontend | all) TARGET="$arg" ;;
    *)
      echo "usage: scripts/check.sh [backend|frontend|all] [--fast]" >&2
      exit 2
      ;;
  esac
done

FAILED=()
STEP_INDEX=0

# Run one check, remember whether it passed, keep going either way.
step() {
  local name="$1"
  shift
  STEP_INDEX=$((STEP_INDEX + 1))
  printf '\n\033[1m── %s\033[0m\n' "$name"
  if "$@"; then
    return 0
  fi
  FAILED+=("$name")
  return 1
}

note() { printf '\033[2m   %s\033[0m\n' "$1"; }

# --------------------------------------------------------------- toolchains

# pnpm, however this machine has it. `corepack pnpm` reads the `packageManager`
# field in frontend/package.json, so it is the SAME pnpm the Dockerfile and CI
# use rather than whatever happens to be on PATH.
pnpm_cmd() {
  if command -v pnpm >/dev/null 2>&1; then
    pnpm "$@"
  elif command -v corepack >/dev/null 2>&1; then
    corepack pnpm "$@"
  else
    echo "pnpm not found. Install Node 22+ (corepack ships with it) or pnpm itself." >&2
    return 127
  fi
}

# Is there a Postgres to run the integration suite against? Checked rather than
# assumed, because `docker compose up db` is a thing you forget.
database_is_up() {
  local dsn="${TEST_DATABASE_ADMIN_DSN:-postgresql://app:app@localhost:5433/postgres}"
  local host port
  host="$(printf '%s' "$dsn" | sed -E 's|.*@([^:/]+).*|\1|')"
  port="$(printf '%s' "$dsn" | sed -E 's|.*:([0-9]+)/.*|\1|')"
  (echo >"/dev/tcp/${host}/${port}") >/dev/null 2>&1
}

# ----------------------------------------------------------------- backend

check_backend() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found. See https://docs.astral.sh/uv/ or run scripts/setup.sh." >&2
    FAILED+=("backend (uv missing)")
    return
  fi

  cd "$ROOT/backend" || return

  step "backend · lint" uv run ruff check app tests
  step "backend · format" uv run ruff format --check app tests
  step "backend · types" uv run basedpyright

  # Unit and structural tests need no database and no network, which is what
  # makes them safe to run on every commit. Keep it that way.
  step "backend · tests (no db)" uv run pytest tests/unit tests/structure

  if [ "$FAST" = "1" ]; then
    note "skipping the integration suite (--fast)"
  elif database_is_up; then
    # -n auto: one Postgres database per xdist worker (see tests/conftest.py),
    # not one shared by all of them. The clinical fixture is seeded once per
    # worker rather than once per test (tests/integration/conftest.py) and the
    # big tables load through `COPY`, not batched `INSERT` (app/services/
    # seed_service.py) — together that took this suite from ~37 minutes to
    # under 30 seconds. Read those two files before making a test reseed the
    # dataset again; that regression is easy to reintroduce one fixture at a
    # time and hard to notice until the suite is slow again.
    step "backend · tests (integration)" uv run pytest tests/integration -n auto
  elif [ "${CHECK_REQUIRE_DB:-0}" = "1" ]; then
    # CI sets this. Without it, a Postgres service that failed to come up would
    # make the integration suite quietly skip and the build go green — the
    # worst possible outcome for the tests that cover the queue and the bus.
    echo "CHECK_REQUIRE_DB=1 but no database is reachable." >&2
    FAILED+=("backend · tests (integration) — no database")
  else
    note "no database reachable — skipping the integration suite."
    note "start one with: docker compose up db -d"
  fi

  cd "$ROOT" || return
}

# ---------------------------------------------------------------- frontend

check_frontend() {
  cd "$ROOT/frontend" || return

  if [ ! -d node_modules ]; then
    note "node_modules missing — installing"
    pnpm_cmd install --frozen-lockfile || {
      FAILED+=("frontend (install)")
      cd "$ROOT" || return
      return
    }
  fi

  step "frontend · lint" pnpm_cmd lint
  step "frontend · format" pnpm_cmd format:check
  step "frontend · types" pnpm_cmd typecheck
  step "frontend · tests" pnpm_cmd test

  if [ "$FAST" = "1" ]; then
    note "skipping the production build (--fast)"
  else
    # Not redundant with typecheck: `build` is `tsc -b && vite build`, which
    # re-checks under project-reference rules AND proves the bundle resolves.
    step "frontend · build" pnpm_cmd build
  fi

  cd "$ROOT" || return
}

# --------------------------------------------------------------------- run

if [ "$TARGET" = "all" ] || [ "$TARGET" = "backend" ]; then check_backend; fi
if [ "$TARGET" = "all" ] || [ "$TARGET" = "frontend" ]; then check_frontend; fi

echo
if [ ${#FAILED[@]} -eq 0 ]; then
  printf '\033[32m✔ all checks passed\033[0m (%s steps)\n' "$STEP_INDEX"
  exit 0
fi

printf '\033[31m✘ %s of %s checks failed:\033[0m\n' "${#FAILED[@]}" "$STEP_INDEX"
printf '   %s\n' "${FAILED[@]}"
exit 1
