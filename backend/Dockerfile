# uv's official image — ~10x faster dependency resolution than pip, and the
# lockfile it writes (uv.lock) is what makes builds reproducible.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

WORKDIR /srv

# Dependencies are their own layer, so editing app code doesn't reinstall them.
# uv.lock is optional on first build (the glob tolerates its absence) and is
# written by `uv sync`; commit it once it exists.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# PYTHONFAULTHANDLER: a crash inside a compiled extension (exit 139, SIGSEGV)
# otherwise leaves no trace at all — no traceback, no "stopped" log line, just
# a process that is gone. With it, Python writes every thread's stack to
# stderr on the way down, which is the only way to learn which extension did it.
ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

COPY app ./app

# Migrations ship with the image that runs them, so the version of the schema
# and the version of the code that expects it cannot drift apart.
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic


EXPOSE 8000

# Everything above is shared. The two stages below differ only in how the
# process is started and who starts it.
FROM base AS dev

# --reload picks up edits through the source mount in docker-compose.yml.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "/srv/app"]


FROM base AS production

# Unprivileged. The venv and the source are owned by root and only need to be
# read, so nothing has to be chowned — and a container that cannot write to its
# own code is one fewer thing to reason about after a compromise.
RUN useradd --create-home --uid 10001 app
USER app

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]

# No --reload: it costs a filesystem watcher, and it restarts the process on a
# file change, which in production means on nothing at all.
#
# One worker. Add --workers N to use more cores, but note the LISTEN connection
# in app/bus.py is per process, so each one opens its own.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
