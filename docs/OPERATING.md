# Operating it

The operator's half of the [README](../README.md): what you need once the app
is running, rather than what it is for. It covers the checks and the commands
you reach for while working on the code, what to do when the dev frontend is
slow, how to schedule an agent, and how to deploy the whole thing to a server
and keep it there. The reasoning behind most of it lives in
[AGENTS.md](../AGENTS.md); this file is the how.

## Working on it

```bash
scripts/setup.sh           # once per clone: deps, .env, and the pre-commit hook
scripts/check.sh           # lint, format, types and tests, both halves
scripts/check.sh --fast    # the subset the hook runs — no database, no bundle
```

One script, three callers: you, the pre-commit hook, and CI. A hook that checks
something different from CI is worse than no hook.

The hook is opt-in per clone (`git config core.hooksPath .githooks`, which
`setup.sh` does) because git will not version `.git/hooks`. `git commit
--no-verify` skips it.

Some of the conventions in [AGENTS.md](../AGENTS.md) are checked by
**structural tests** — `backend/tests/structure/` and
`frontend/src/structure.test.ts` — which assert on the shape of the codebase
rather than on what it computes: only the adapter may import `anthropic`, only
`config.py` may read the environment, no literal colour may appear in a
component. [AGENTS.md § Checks](../AGENTS.md#checks) lists all of
them and says what belongs in one.

## Common tasks

```bash
# Change the schema: edit backend/app/models.py, then generate a revision.
# Read it before you commit it — autogenerate cannot see a rename.
docker compose run --rm migrate alembic revision --autogenerate -m "what changed"

# Start over from an empty database (destroys data), then reseed
docker compose down -v && docker compose up -d
cd backend && uv run python -m app.seed --from ./data/synthea/csv

# Backend logs
docker compose logs -f backend

# Worker logs — tool calls and agent runs land here
docker compose logs -f worker

# All checks, both halves (integration tests need the db running)
scripts/check.sh

# What is queued right now
docker compose exec db psql -U app -d app \
  -c "select kind, status, attempts, created_at from tasks order by created_at desc limit 10;"

# Rebuild after changing dependencies
docker compose build backend && docker compose up -d

# A psql shell
docker compose exec db psql -U app -d app
```

Source is mounted into the app containers, so editing `backend/app/**` or
`frontend/src/**` reloads without a rebuild. Only dependency changes need one.

Schema changes go through Alembic: a one-shot `migrate` container runs
`alembic upgrade head` before the backend and worker start, so `docker compose
up` stays one command and your data survives it.

## If the frontend feels slow

Vite runs with filesystem polling because Docker on macOS does not deliver file
events across bind mounts. If it bothers you, run the frontend on the host
instead — everything still works:

```bash
docker compose up db backend worker
cd frontend && pnpm install && pnpm dev
```

## Scheduled agents

An agent that wakes up on its own, queries the dataset, and writes what it
found into a conversation you can read later:

```bash
curl -X POST http://localhost:8000/api/schedules \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "Daily briefing",
        "prompt": "List any patients on a high-risk nephrotoxic medication whose most recent eGFR is below 30.",
        "intervalSeconds": 86400
      }'
```

It runs immediately, then every 24 hours. Each run gets its own conversation, so
you can read exactly what it did in the same UI as everything else.

**An agent has no way to send anything outside this system.** The template's
`send_email` tool was deleted rather than kept: a scheduled run acting on its
own judgement at 3am, against patient data, with a tool that mails an address
it chose, is a combination worth not having. The run's conversation is the
output, and it reads in the same UI as everything else.

## Deploying it

**The one-command way**, to a fresh Ubuntu server your SSH key can reach as root:

```bash
scripts/deploy.sh root@<server-ip>                 # https://<ip-with-dashes>.sslip.io
scripts/deploy.sh root@<server-ip> your.domain     # once the domain's A record points there
```

It installs Docker and Caddy, locks the firewall to SSH/HTTP/HTTPS, writes
`.env.prod` on the server (generated database password, your API key from
`.env`), copies the code and dataset, builds, seeds, and serves it over HTTPS.
Re-run it to redeploy: every step checks before it acts. Several projects can
share one server — see the header of the script. What it does, by hand:

On any host with Docker Compose — a VPS is the shape the production compose
file assumes:

```bash
cp .env.prod.example .env.prod          # fill in every value; none default
docker compose -f docker-compose.prod.yml --env-file .env.prod up --build -d

# Once, on a fresh database: load the Synthea export and the curated
# definitions. Takes about a minute. backend/data/ must be on the server —
# it is about 380 MB and not in git; scripts/generate-synthea.sh rebuilds it.
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm worker python -m app.seed
```

**It deploys public.** Anyone who can reach it can use it, each browser as an
anonymous visitor of its own: their own conversations and saved questions,
nobody else's, and no roles — so they can read every definition but not change
one, and the unresolved-term report and the raw patient table are closed to
them. Two ceilings bound what
that costs, both in `.env.prod`: `MESSAGES_PER_HOUR` per visitor and
`DAILY_TOKEN_BUDGET` across everyone. **Also set a monthly spend limit in the
Anthropic console** — the app checks its ceilings between turns, so a turn in
flight can overshoot them; the console limit cannot be overshot.

**Put TLS in front of it.** nginx listens on `PUBLIC_PORT` over plain HTTP.
The simplest front is Caddy on the same host, which fetches and renews a
certificate by itself:

```
# /etc/caddy/Caddyfile — with PUBLIC_PORT=8080 in .env.prod
copilot.example.com {
    reverse_proxy localhost:8080
    header Strict-Transport-Security "max-age=31536000"
}
```

Set `PUBLIC_ORIGIN` to the `https://` address people will use.

**Back up the database.** Everything in it but the dataset is irreplaceable —
conversations, saved questions, and every definition edit with its history.
A nightly dump is enough to start with:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "backup-$(date +%F).sql.gz"
```

**Redeploying** is the same `up --build -d`. Migrations run first and stop the
deploy if they fail. The worker hands back a turn it was running when it is
stopped, and a worker that *crashes* has its turn picked up by its replacement
on startup rather than after the sweeper's fifteen minutes. `POSTGRES_PASSWORD`
is read only when the volume is first created — see `.env.prod.example`
before changing it.

The production stack differs from the development one in ways worth knowing
before you need them:

| | Development | Production |
| --- | --- | --- |
| Frontend | Vite dev server | Built bundle on nginx, which also proxies `/api` |
| Reload | Hot, with source mounts | None; the image is the artifact |
| Identity | One dev user with every role | An anonymous visitor per browser, no roles |
| Cost ceilings | None | Per-visitor hourly, all-visitor daily |
| Backend user | root | Unprivileged `app` (uid 10001) |
| Restart | Worker supervised; rest manual | `unless-stopped` |
| Healthchecks | db only | All four, worker included |
| Postgres port | Published on 5433 | Not published at all |
| Logs | Human-readable | JSON |
| Headers | — | Strict CSP, nosniff, frame-deny, gzip |

**The nginx proxy is not decoration.** The client calls `/api` on its own
origin, and in development Vite's dev server proxies that to the backend — a
`server:` block that does not exist in a built bundle. Without something
reproducing it, a production build has no route to the API at all. `nginx.conf`
is that something, and it carries the three directives SSE needs
(`proxy_buffering off`, HTTP/1.1, a long read timeout) without which streaming
appears broken in a way that looks like an application bug. It also re-resolves
`backend` through Docker's DNS, so redeploying the backend alone does not leave
nginx sending to an address that no longer exists.

Still not included, because they depend on where you deploy: secrets
management beyond `.env.prod`, log shipping, and uptime alerting.
