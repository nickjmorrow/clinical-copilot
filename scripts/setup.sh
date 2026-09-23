#!/usr/bin/env bash
#
# One-time setup for a fresh clone.
#
# You do NOT need this to run the app — `cp .env.example .env && docker compose up`
# is still the whole story, and the containers carry their own dependencies.
# This is for running the checks on your machine and for the pre-commit hook,
# both of which run outside Docker because a check you have to wait on a
# container for is a check you stop running.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

say "git hooks"
# Git will not version .git/hooks, so the hook lives in .githooks/ and this
# points git at it. One line, per clone, and reviewable like any other file.
git config core.hooksPath .githooks
echo "   core.hooksPath -> .githooks (pre-commit runs scripts/check.sh --fast)"

say "environment"
if [ -f .env ]; then
  echo "   .env exists — leaving it alone"
else
  cp .env.example .env
  echo "   .env created from .env.example — add your ANTHROPIC_API_KEY"
fi

say "backend"
if command -v uv >/dev/null 2>&1; then
  (cd backend && uv sync --locked --group dev)
  echo "   backend/.venv ready"
else
  echo "   uv not found — install it from https://docs.astral.sh/uv/ and re-run."
  echo "   (Only needed for running checks locally; the containers do not use it.)"
fi

say "frontend"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm install --frozen-lockfile)
elif command -v corepack >/dev/null 2>&1; then
  # corepack reads `packageManager` in frontend/package.json, so this is the
  # same pnpm the Dockerfile and CI use rather than whatever is on PATH.
  (cd frontend && corepack pnpm install --frozen-lockfile)
else
  echo "   pnpm not found — install Node 22+ (corepack ships with it) and re-run."
fi

say "done"
cat <<'MSG'
   docker compose up          run the app on http://localhost:3000
   scripts/check.sh           lint, types and tests, both halves
   scripts/check.sh --fast    what the pre-commit hook runs
MSG
