# Conventions

This file is the contract for the codebase, and the first thing a human should
read. When a rule here conflicts with what a file does, the file is wrong.

Some of these rules are checked by machine rather than by review, and that is
covered in [Checks](#checks): `scripts/check.sh` runs everything, a pre-commit
hook runs the fast half, and `backend/tests/structure/` plus
`frontend/src/structure.test.ts` assert on the conventions that no linter can
express.

## What this is

**Clinical Copilot**: a streaming LLM app that answers questions about a
hospital's patients — synthetic ones — without the model ever writing SQL or
choosing a clinical threshold. The model picks which of the hospital's defined
terms a question refers to; everything after that is deterministic, cited and
audited. Postgres + FastAPI + React + a worker, four containers, one command.

It started from a reference-architecture template for streaming LLM apps with
tools and scheduled agents. The conventions below began as that template's and
grew with what this project needed, and one of its rules still governs how the
code grows: **delete what you don't need, and design no abstraction before its
second use.** You cannot design a good reusable foundation from zero examples,
and a layer introduced to serve one call site is a cost with no benefit yet.

## Running it

```bash
cp .env.example .env     # add your ANTHROPIC_API_KEY
docker compose up        # http://localhost:3000
```

The schema is Alembic migrations, applied by a one-shot `migrate` container that
the backend and worker wait on. `docker compose up` is still one command, and
your data survives it.

Changing the schema is two steps: edit `backend/app/models.py`, then

```bash
docker compose run --rm migrate alembic revision --autogenerate -m "what changed"
```

**Read what it generated before applying it.** Autogenerate is a good first
draft and a bad last word: it cannot see a rename, so it emits a drop and an add
— which is a data-loss bug wearing a migration's clothes. `docker compose up`
applies whatever is committed.

It has a quieter blind spot too, and this one emits *nothing* rather than
something wrong. **Alembic compares an index by name and columns and never looks
at its `WHERE` clause.** Change a plain index to a partial one in `models.py`
and autogenerate sees the same name over the same columns, concludes nothing
changed, and writes an empty migration — leaving a partial index that exists
only in Python. `conversations_user_updated_idx` is the one in the tree that
went that way; its migration drops and recreates it by hand, because Postgres
has no `ALTER INDEX` for a predicate. The check is `\d tablename` in psql: if
the `WHERE` is not printed there, it is not real.

## Layout

```
backend/alembic/       Migrations. `versions/` is the schema's history.
backend/tests/         pytest. unit/, integration/, structure/, support/.
frontend/nginx.conf    Serves the built bundle and proxies /api in production.
backend/app/
  main.py              App wiring only. No logic.
  config.py            All environment reads. The only place os.getenv belongs.
  logging.py           structlog setup + the logging rules.
  db.py                Async engine and session factory.
  models.py            SQLAlchemy models. THE SCHEMA'S SOURCE OF TRUTH.
  wire.py              The event shapes BOTH transports send. camelCase lives here.
  api/
    deps.py            Shared dependencies, including the identity seam.
    middleware.py      Request ids and access logging. Pure ASGI, not BaseHTTP.
    schemas.py         The {data, meta} envelope + the HTTP-only shapes.
    routes/            Thin: validate -> authorize -> call a service -> respond.
  bus.py               LISTEN/NOTIFY fan-out. Live tokens, worker -> browser.
  worker/
    __main__.py        `python -m app.worker`.
    loop.py            Claim, run, settle, wait for NOTIFY, repeat.
    handlers.py        What each task kind means; settling the row afterwards.
    turn.py            One turn: the event stream -> rows + frames. The engine.
    shutdown.py        The stop flag and the signal handlers that set it.
    dev.py             Dev only: restart the worker on a code change or a death.
  services/
    conversation_service.py  The conversation row: CRUD, controls, naming.
    transcript_service.py    The append-only event log and its two readings.
    task_service.py          The queue: claim, settle, sweep, supersede.
    schedule_service.py      Schedules as rows. Expanded by the worker.
    definition_service.py    Validates, versions and caches clinical_definitions.
    clinical_query_service.py  Resolve -> guard -> assemble -> execute -> audit.
    catalog_service.py       Dataset counts and reference values for the vocabulary panel.
    audit_service.py         Writes query_audit rows. Never rolls back with the query.
    saved_question_service.py  Saved questions: CRUD, scoped by user_id.
    usage_service.py         Cost ceilings: messages per hour, tokens per day.
    authz_service.py         Roles and row-level (state) scope for a user.
    seed_service.py          Loads the Synthea dataset + curated annotations.
  clinical/
    predicates.py      What a definitions row may say. Closed specs, validated.
    columns.py          The column allowlist: what a query may select or filter on.
    assembler.py       Validated predicates -> parameterised SQL. Writes ALL of it.
  seed/
    synthea.py          Parses the raw Synthea export into rows seed_service inserts.
    reference_data.py   Static reference tables (units, categories) seeded once.
    annotations.py      Curated clinical judgement (e.g. nephrotoxic tiers), reviewable.
  llm/
    types.py           Provider-neutral events and blocks. THE SEAM.
    base.py            The LLMProvider Protocol.
    anthropic_provider.py  The only file importing `anthropic`.
  tools/
    base.py            What a tool is: a closed schema, a handler, a context.
    find_patients.py   The clinical tool. The only one that reaches the data.
    __init__.py        The registry, and the only place tools are listed.
frontend/src/
  main.tsx             Mounts App inside its providers. No markup of its own.
  App.tsx              The route table: the sidebar, and the page the URL names.
  index.css            Tailwind + the @theme block. The only stylesheet there is.
  api/                 The HTTP boundary: client, resources, SSE parsing.
  turns.ts             The event log folded into what gets drawn. No React.
  format.ts            Durations, timestamps, tool-input summaries. No React.
  markdown.ts          Splitting half-written markdown mid-stream. No React.
  paths.ts             Every URL: router patterns and link builders. No React.
  cohortCall.ts        A find_patients call read back: question, outcome. No React.
  chart.ts             A result's rows folded into something to plot. No React.
  predicates.ts        The definitions editor's typed `logic` shapes. No React.
  styles.ts            Shared class strings for form controls. No React.
  hooks/               Stateful logic that isn't layout. One hook per file.
  components/          UI. One per file, default export, named after the file.
```

Two compose files: `docker-compose.yml` is development, `docker-compose.prod.yml`
is not. Both Dockerfiles are multi-stage; the dev stack asks for the `dev` target
explicitly, and a bare `docker build` gives you the production one.

**The rule for where code goes:** if a second caller would need it — a CLI, a
worker, a test — it belongs in `services/`. Routes exist to translate HTTP into
a service call and back.

That one sentence decides most cases. The rest of this section is the cases it
does not, written down because every one of them has already been got wrong
once.

### The `.ts` files at the top level are the view model

`turns.ts`, `format.ts`, `markdown.ts`, `chart.ts`, `cohortCall.ts`,
`paths.ts`, `predicates.ts` and `styles.ts` are pure functions and data with
no React in them, which is why they are not in `components/`. Each is the same shape: it
takes data and returns data, a `.test.ts` sits beside it, and nothing has to be
rendered to find out whether it works.

That is the bar for putting a new file there — **not** "it did not fit
anywhere else." A helper that needs a hook is a hook; a helper used by one
component belongs in that component's file until a second component wants it.
The moment a top-level `.ts` imports React the suite that tests it needs a
renderer, which is how that suite stops existing.

`src/api/` is held to the same rule for the same reason, and both halves are
checked by `frontend/src/structure.test.ts`.

### `app/wire.py` is the vocabulary both transports speak

The browser receives an event over **two transports**: the REST and SSE
responses `api/routes/conversations.py` writes, and the NOTIFY frames
`worker/turn.py` publishes while the turn is still running. One definition of
what an event looks like is what lets a client fold a replayed event and a live
one with the same function. Two definitions is a bug that only shows up after a
refresh.

So those shapes live at the top level, in `app/wire.py`, and not under `api/`.
A process that serves no HTTP should not have to import the HTTP layer to say
what an event is.

`api/schemas.py` is what is left once that is taken out: the `{data, meta}`
envelope, the request bodies, and the resource shapes that genuinely only
travel over HTTP. It imports from `wire.py`; nothing imports back.

This was briefly the other way round — everything lived in `api/schemas.py` and
the worker reached up for `event_frame`, plus `DEV_USER_ID` from `api/deps.py`.
Both of those moved down rather than being blessed as exceptions, which is what
lets the import rule below be absolute instead of a list of allowances. **A rule
with two exceptions is a rule nobody can apply without looking it up.**

### Which direction imports run

Backend, top to bottom — each layer may import the ones below it and never the
ones above:

```
main.py, worker/, seed/   the three processes: wiring and the run loop
api/routes/               HTTP. Imported by main.py alone.
tools/                    leaves the model can call. May call into services/.
services/                 business logic. Imports models, llm, clinical, bus, config.
llm/, clinical/, bus.py   the seams and the fan-out
wire.py, models.py, db.py, config.py, logging.py
```

`seed/` is a peer of `main.py` and `worker/`, not a layer beneath `services/`:
`python -m app.seed` calls into `services/seed_service.py` the same way the API
and the worker call into their services, and importing the package must never
write anything — see its own `__main__.py`.

The two rules with teeth: **`services/` never imports `api/` or `worker`**, and
**nothing outside `app/api/` imports `app.api` at all, except `main.py`.** A
service that reaches up into the HTTP layer is one a worker can no longer call,
which is the entire reason `services/` exists.

Inside `worker/` the same shape holds one level down —
`shutdown <- turn <- handlers <- loop` — which is why the stop flag is its own
module rather than a global in whichever file happened to need it first.

Frontend, the same shape:

```
App.tsx, components/      React. May import hooks/, api/, the view model.
hooks/                    React, no markup. May import api/ and the view model.
turns.ts, format.ts, markdown.ts, api/     no React, and no imports upward.
```

**Imports are absolute** (`src/api/client`), never relative. Relative paths
stop being readable three directories in, and `../../` tells you nothing about
which layer you landed in.

### One thing per file, named after the file

A component file exports its component and nothing else. A hook file exports
its hook, plus the interface of whatever that hook returns — `useScrollAnchor`
exporting `ScrollAnchor` is the pattern, because a caller needs to name the
thing it was handed.

If a second file wants a type or a helper that lives beside a component, that
is the signal to move it to a `.ts` module, **not** to add an export. Two
exports from a component file is how `components/` turns into the place
everything ends up.

On the backend, every `__init__.py` is empty except `tools/__init__.py`, which
is the registry and says so. Services are imported as modules — `from
app.services import conversation_service`, then `conversation_service.create` —
rather than as loose symbols, so the call site says which layer it is calling
into.

### Where tests go

The two halves disagree, and both are right for their toolchain.

Backend tests live in a tree under `backend/tests/`, split by what they need:
`unit/` and `structure/` need nothing, `integration/` needs a Postgres,
`live/` needs a real model and an API key, and `support/` is fixtures rather
than tests. That split is not organisational tidiness — `scripts/check.sh` runs
the first two on every commit and the third only when a database is reachable,
so the directory *is* the interface.

`live/` is the newest and the rule is the strictest: `check.sh` names the
directories it runs and `live/` is not among them. No marker, no `--skip-live`
flag, no environment variable someone sets once and forgets. Those tests call a
real model, cost money, and are non-deterministic by nature — a failure there
means "the model chose differently today", which is worth knowing and is not
the same kind of fact as a red build. Run them deliberately with
`uv run pytest tests/live`.

The golden dataset in `support/eval_cases.py` is walked by both
`integration/test_eval.py` and `live/test_eval_live.py`, which is the point of
it being data rather than test functions: one document, two questions. The
integration runner asks "given the right terms, is the answer right"; the live
runner asks "does a model pick the right terms". A suite that mixed them would
fail for two unrelated reasons and tell you neither.

Frontend tests sit beside what they test: `turns.test.ts` next to `turns.ts`.
Vitest finds them anywhere, the file it covers is one line away in the
listing, and a module with no neighbouring test is visible at a glance. There
is no `frontend/src/components/*.test.tsx` today, which is a gap rather than a
rule — the view model is tested because it is pure, and that is the easy half.

### Size is a smell, not a limit

There is no line ceiling, and adding one would be worse than the problem. But
when a file is the biggest in its half by a wide margin, that is usually not one
idea that happens to be long. Two were, and both have been split:

- `worker.py` was ~580 lines doing four things. It is now `worker/`, one module
  per thing, in the dependency order named above. `python -m app.worker` is
  unchanged because `__main__.py` is the entry point.
- `conversation_service.py` was ~520 lines holding conversation CRUD *and* the
  transcript machinery. [The transcript](#the-transcript) is its own section in
  this document; it is now its own module too.

The definitions layer has since outgrown that line, and the sizes say so:
`services/definition_service.py` (~1,000 lines) and
`services/clinical_query_service.py` (~900) are now the largest files in
`app/`. `models.py` (~880) is the schema and `clinical/assembler.py` (~760)
is one idea whose SQL is genuinely that long; those are fine. The two services
are the next splits: the first holds validation, versioning and the model check,
the second the resolve → guard → assemble → execute → audit path plus browsing
and explanation — each more than one concern. That is the distinction to apply:
**length is only a problem when it is concealing a second concern.** A long
file that does one thing is fine; a 200-line file doing three is not.

When you do split one, split it along a line this document already draws. Both
of the splits above were named in prose here long before the code matched —
which is the useful signal, and cheaper to notice than to rediscover.

## Backend

### Async

`async def` everywhere, native uvicorn, asyncpg. This is correct **because**
nothing here runs under a WSGI shim or gevent workers. If you ever deploy behind
one, async handlers block the event loop on every database call and this rule
inverts. Know which world you are in.

### Logging

structlog. The first argument is a **static string** — no f-strings, no
interpolation. It is the event name you grep and aggregate on; interpolating
makes every occurrence unique and destroys that. Everything else is a keyword
argument, and every value is a primitive.

```python
# Good
logger.info("conversation created", conversation_id=str(c.id), user_id=user_id)

# Bad: interpolated message, ORM object in kwargs
logger.info(f"created {c.id}", conversation=c)
```

Never pass an ORM model as a kwarg, even one with a nice `__repr__`. Never log
user content or secrets — ids, counts, durations, and model names are fine.

Log at both ends of anything that can fail or take time.

**Every log line carries a request id**, and none of them pass it explicitly.
`RequestContextMiddleware` binds it into `structlog.contextvars` and
`merge_contextvars` — which was in the processor chain from the start — puts it
on everything for the rest of the request. The id is stored on the `tasks` row
when a turn is enqueued and re-bound by the worker when it claims it, so one
`grep` returns both halves of a turn across two processes that share no memory
and no log stream. That is the only thread tying them together; without it, "why
was this slow" is two investigations.

That middleware is pure ASGI rather than `BaseHTTPMiddleware` on purpose. The
convenient base class buffers the response body, which turns an SSE endpoint
into one that delivers everything at the end — the same failure the
`X-Accel-Buffering` header exists to prevent.

### Configuration

Everything environment-dependent is a field on `Settings` in `config.py`.
`os.getenv` anywhere else is a bug: a typo in an env var name should fail at
startup with a clear error, not at 2am with a `None`.

### Responses

Every response is `{"data": ..., "meta": {...}}`. A bare array or scalar leaves
nowhere to add pagination or a warning without breaking clients.

The wire is **camelCase**; Python is **snake_case**. The alias generator in
`app/wire.py` converts at the boundary, so no TypeScript file contains
`created_at` and no Python file contains `createdAt`.

### Errors

Catch a chain, most specific first. A single broad `except` collapses "wait and
retry" into "your key is wrong", and the caller can no longer tell them apart.
See `llm/anthropic_provider.py` for the shape.

### Identity

There is no sign-in. `get_current_user()` in `api/deps.py` is the one place
that decides who a request is, and it has two modes.

Outside public mode it returns a constant, `dev-user`, and the app runs with
no accounts at all — which is what keeps `docker compose up` a single command.

**Public mode** (`VISITOR_MODE`, on in `docker-compose.prod.yml`) is for a
deployment anyone can open. `api/middleware.VisitorMiddleware` gives each
browser a random id in an HttpOnly cookie, and that — prefixed `visitor:`, so
it can never equal any other id — is the user. Because every query is already
scoped by user id, visitors are isolated from each other with no other change,
and because a visitor holds no roles, every curator and auditor surface stays
closed.

Adding real sign-in is a change to that one function, because nothing below it
wants anything but a user id. It was built once — OIDC, verified against the
provider's JWKS — and removed unused; see
[What is deliberately missing](#what-is-deliberately-missing).

### Authorization

Scope by `user_id` **in the WHERE clause**, never as an assertion afterwards. A
row belonging to someone else must be indistinguishable from one that does not
exist. Every query goes through `get_current_user()` in `api/deps.py`, which
is why each of its modes was a one-function change.

**Anything that keeps spending after its author has gone is curator-only.** A
schedule is the model running on a timer on the deployment's API key, so
`/api/schedules` is gated like a definition edit. What a visitor may spend is
bounded by `services/usage_service.py`: messages per user per hour and tokens
per UTC day, counted from `usage_events` — a ledger with no foreign key to
anything a user can delete. Counted from the transcript, deleting the
conversation would reset the count.

### Enforcement

`ruff check`, `ruff format --check` and `basedpyright`, all three in CI.

Ruff selects nearly every rule group and then turns individual rules off with a
note, rather than selecting a short list. The difference matters: an `ignore`
with a reason is a decision someone can argue with later, and a short `select`
is a decision nobody wrote down. The list is explicit rather than `ALL` so that
upgrading ruff adds rules on a day we choose.

Two of those `ignore`s are worth reading before you change them. **`TRY400`**
wants `logger.exception` everywhere inside an `except`, which is wrong here: the
error chain in `llm/anthropic_provider.py` catches *expected* provider failures
and turns each into a `StreamError`, so a traceback per rate limit is exactly
the noise the chain exists to avoid — and in the `AuthenticationError` branch it
would echo the key prefix into the logs, which a comment there tells you not to
do. `G201` still holds you to `.exception()` where a traceback *is* wanted.
**`D`** is off because the docstrings here are prose on purpose; pydocstyle
would demand one on every function and then argue about the mood of its first
verb.

basedpyright runs at **strict** on `app/`. The three suppressions left are all
about other people's libraries — asyncpg ships no stubs, SQLAlchemy's `desc()`
is partially generic — not about this code. `tests/` relaxes the annotation and
private-access rules through an `executionEnvironments` block, because a test
signature is fixtures in and `None` out, and a test reaching into a private
helper is doing its job.

The complexity limits in `[tool.ruff.lint.pylint]` are set just above the worst
function that exists rather than switched off. The adapter's tool loop, the
worker's `_generate` and the SSE encoder are complex because this file argues
they should be; the ceiling stops the next one being worse.

## The LLM seam

`llm/types.py` defines provider-neutral events. `llm/anthropic_provider.py` is
the **only** file allowed to import `anthropic`. If the SDK appears anywhere
else, the seam has leaked and the next model swap becomes a refactor.

Adapters **never raise** for a provider failure — they yield a terminal
`StreamError`. Once a stream has started the HTTP status is already sent, so an
exception cannot become a status code; the error has to travel in-band.

The Protocol has a second method, and the split is worth keeping. `stream()` is
a turn somebody is watching: tools, thinking, cancellation checkpoints, events.
`complete()` is one short answer on the cheap model — no tools, no streaming, no
thinking — and it returns `str | None`, where `None` is every failure there is.
That is only safe because **every caller of `complete()` is doing something
optional**. Naming a conversation is the one today; it has a serviceable
fallback title already written down, so a failure is a value to ignore rather
than something to retry or report. Do not reach for it from a path that has to
succeed — that path wants a turn, and turns go through `stream()`.

Adding an event type is a four-file change, and all four must stay in step:

1. `backend/app/llm/types.py` — the union
2. the adapter that emits it
3. `backend/app/api/routes/conversations.py` — the SSE encoder
4. `frontend/src/api/stream.ts` — the TypeScript union

Not every event reaches the browser. `AssistantMessage` exists so the route can
write a row and is deliberately not forwarded — the client already has that text
delta by delta. When you add an event, decide which of those two things it is.

### The adapter owns the tool loop

A turn is not one call to the model. It is: ask, run whatever tools it asked
for, ask again with the results, until it answers without calling one. That loop
lives inside the adapter, for two reasons.

The first is thinking. Continuing a turn after a tool result requires handing the
model its own reasoning back, verbatim, in the provider's own block format. The
adapter is the only layer allowed to touch those raw blocks — so it keeps them
in a local list that never escapes the function, and nothing above the seam
learns that provider-shaped data exists. Reasoning still never crosses a turn
boundary and is still never persisted.

The second is that the caller's job stays the same whether a turn took one model
call or five: consume events until a terminal one. A loop in the route would put
provider mechanics in the place that is supposed to be thin.

`max_tool_iterations` caps it. The failure it exists for is a tool that can never
succeed: it errors, the model adapts, tries again, forever. Without a cap that is
an unbounded bill.

It is the blunt backstop, not the whole story. Hitting it means a turn ran out
of loop, which no one can explain to a user. The per-tool failure budget in
[§ Tools](#tools) is what normally ends a retry cycle, and it ends it with a
reason.

### Choosing a model

`settings.anthropic_model` defaults to `claude-opus-5`. Don't downgrade for cost
without measuring — a cheaper model that needs more turns is not cheaper. Model
ids are exact strings; never append a date suffix.

There is a second, deliberate exception: `settings.anthropic_fast_model`
(`claude-haiku-4-5`) serves `complete()`. It needs no measuring because it is
not the same work — a six-word summary is not a turn, and the rule above is
about downgrading the model that does the thinking. Anything that grows into
this setting should be that shape too. If you find yourself wanting the fast
model for an *answer*, you want a measurement, not this field.

Thinking is `{"type": "adaptive"}` with `display: "summarized"`. The display
setting is opt-in: the default returns thinking blocks with empty text, which in
a streaming UI looks like a long silent pause.

## Tools

A tool is a JSON Schema the model reads and a function the server runs, paired in
one object so the two cannot drift. `tools/find_patients.py` is the worked
example and the only one: it is the sole route to the clinical dataset, so the
set of things this application can do to patient data is the set of things that
one function does. A second tool is a second thing to audit.

The template's `current_time` and `send_email` examples were deleted once this
one existed, which is what the template says to do with them.

Adding a tool is a module next to it plus one entry in `tools/__init__.py`.

**Schemas are closed.** Every property declared, `required` listed,
`additionalProperties: false`. The adapter sends tools as strict, so the provider
guarantees the arguments validate before a handler ever sees them — which is what
lets `run` read its input directly instead of re-checking every field. A schema
that isn't closed silently gives that guarantee up.

**Handlers take a `ToolContext`** — the turn's session, the asking user, the
conversation. Passed explicitly rather than read from a contextvar: the
identity a clinical query is audited against should be visible in the signature
of the thing doing the auditing. The worker builds one per turn and binds it
with `tools.executor(context)`, so the provider's `(name, input) -> output`
contract is untouched.

**Handlers never raise.** A failure is `ToolOutput(..., is_error=True)`, which
goes back to the model as an ordinary result. The model reads it, usually fixes
itself, and the user never knows. An exception ends the turn instead — a dead
stream because an argument had a typo in it. The registry enforces this for
handlers that break the rule anyway, and logs the traceback for you while telling
the model only that the tool failed: an exception message can carry paths and
queries into the conversation.

**The description is prompt, not documentation.** Say *when* to call it, not just
what it does. That is the difference between the model knowing a tool exists and
reaching for it.

**A tool gets two failures per turn.** After that the registry stops running it
and returns a plain result — *not* `is_error` — telling the model to stop
retrying and explain itself to the user. `AttemptLedger` on the `ToolContext`
holds the count, and its lifetime is the turn.

Two, because one correction is usually the right number: the model asks for a
column it may not have, is refused, and asks again for one it may. That retry
should succeed. A third attempt is the model guessing, and a guess against a
clinical dataset is worse than an admission.

Only `is_error` results count. A clarification is not a failure — asking the
user which term they meant, getting an answer and asking again is the loop
working, and charging it a retry would end a conversation that was going fine.

This is **not** `max_tool_iterations`, and both are wanted. That one bounds
model calls per turn so a tool that can never succeed cannot run up an
unbounded bill; it is a backstop and says nothing to anyone. This one ends a
specific tool's retries with a sentence the model can relay.

**Keep the registry order stable.** The tool list renders at the very front of
the prompt, ahead of the system prompt and the messages, so reordering it
invalidates the cached prefix for every conversation.

A tool is a leaf. If one needs a database or business logic, it calls into
`services/`; it does not grow its own.

## The definitions layer

The clinical counterpart to the LLM seam, and the same kind of rule.

`clinical_definitions` rows say what a term means — "impaired renal function"
is eGFR < 60 — and `app/clinical/assembler.py` is **the only thing in this
codebase that writes SQL for a clinical question.** The model's job stops at
choosing which defined terms a question refers to. It never sees a threshold
and never emits SQL.

That split is what the whole project is arguing for, so the two properties
holding it up are worth stating plainly:

**`logic` is structured data, never a SQL fragment.** A config table of
snippets that get interpolated into a query is an injection vector wearing a
config table's clothes, and nothing can validate it. `predicates.py` checks
every spec against a closed allowlist of shapes — unknown `type`, unknown key,
unknown column, unknown operator are all refusals — before the assembler is
allowed to see it.

**Failing to resolve is not failing open.** A term that does not match is not
dropped: `Resolution.is_complete` goes false and the caller must stop. Dropping
one leg of a two-leg question returns more patients than were asked about and
looks entirely correct doing it. Assembling from *no* predicates is refused
outright by the assembler, because that query is every patient in the hospital.

The tests in `tests/integration/test_query_assembly.py` pin each target
question to SQL a person wrote. **Keep that half hand-written.** A baseline
generated by the thing it is meant to check proves only self-consistency.

**The catalog is the one deliberate exception.**
`services/catalog_service.py` counts rows and lists reference values —
`GET /api/clinical/context` serves the vocabulary panel from it — so it
appears on the clinical-table allowlist alongside the assembler. The
distinction it rests on: "how many patients are there" is metadata about the
dataset, while "which patients" is a clinical query and goes through the
definitions layer like everything else.

That distinction is kept honest by a second structural test asserting the
catalog never references `full_name`, `date_of_birth` or `mrn`. Widening the
allowlist without it would turn "only the assembler reads patient data" into
"only the assembler, and whatever else got added later". If the catalog ever
needs an identifier, it is not a catalog any more.

## The transcript

**The `event_records` table is append-only. Nothing updates a row.** One row per
user message, assistant response, tool call, and tool result, ordered by `seq` —
and everything anyone reads is *derived* by replaying them.

The obvious alternative, one row per turn holding the final text, is right for
plain chat and wrong the moment a tool is involved, because a turn stops being
one string. It becomes some text, a call, a result, and then more text. There is
no honest way to put that in a `content` column.

Two views come out of the log, and they are allowed to differ:

- `load_history()` in `services/transcript_service.py` builds what the **model**
  sees. It folds consecutive events by the same speaker into one turn, because
  the provider requires that, and it drops events the provider would reject.
- `to_event_out()` in `app/wire.py` builds what the **user** sees. It hides
  the empty assistant rows that a pure tool call produces, and is where you would
  add a token count or summarize a noisy tool result.

Do not let those two collapse back into one function because they happen to agree
today. Showing the human something different from what you send the model is the
point, not an accident.

**Replay repairs, it does not trust.** A run that dies between calling a tool and
recording the result leaves a call with no answer, and history in that state is
rejected outright — which would wedge that conversation permanently. Every orphan
gets a synthetic error result instead. This is not a hypothetical: it is what
happens every time someone closes the tab mid-answer.

## Conversation controls

Pinning, archiving, renaming and deleting are four columns and one `PATCH`. The
decisions worth knowing are the ones that are not obvious from the endpoint.

**`pinned_at` and `archived_at` are timestamps, not booleans.** The pin is also
the sort key — pinned conversations order by when they were pinned — so a
boolean would need a second column to say the same thing. `archived_at` earns
its type by answering "when did this leave the list", which a boolean throws
away for no saving.

**The list is ordered in SQL, and `nulls_last` is load-bearing.** Postgres sorts
NULLs *first* under `DESC`, so `order by pinned_at desc` alone puts every
unpinned conversation above every pinned one. The bug appears only once
something is pinned, which is exactly late enough to ship. The client re-sorts
nothing; it splits the list it was handed.

**`updated_at` is bumped by a new user message and by nothing else.** There is
deliberately no `onupdate=now()` on the column: that fires for a pin and a
rename too, and reordering the sidebar because somebody fixed a typo in a title
is not what "newest" is for.

**Archiving unpins.** A pin is a statement about the working set, and leaving
the working set ends it — otherwise unarchiving a year later drops something at
the top of the sidebar for reasons nobody remembers. **Sending a message
unarchives**, for the symmetric reason: a message that succeeds into a
conversation the sidebar does not list reads as the app having lost it.

**The archive is a second list, not a filter on the first.** `?archived=true`
selects between them. `App` only ever sees the live one — it is what the sidebar
lists and what names the conversation on screen, and neither should change
because somebody opened the archive — so the archive is a query belonging to
`ConversationList`, and it does not run until it is opened.

**A patch distinguishes absent from null.** The route reads
`body.model_fields_set`, not `body.pinned is None`: `{}` and `{"pinned": null}`
arrive identically through Pydantic and mean opposite things. Getting this wrong
makes renaming silently unpin.

### Starting one

**A conversation is created by its first message, not by the button.** `/` is a
state rather than a missing id: an empty transcript and a composer, with
nothing written down until you send. The URL becomes `/c/<id>` at that moment,
and it `replace`s rather than pushes — the draft *became* this conversation, so
leaving a `/` entry behind would make Back look like the message was lost. A
new saved question and a new definition do the same (`/saved/new` →
`/saved/<id>`), for the same reason; every other navigation pushes.

This replaced three pieces of machinery that all existed to hide the same
mistake, creating the row too early: an effect that created a conversation on
landing, a search of the list for a blank one to reuse so the button could not
leave five behind, and a delete handler that made a new conversation when it
removed the last one. A row nobody has spoken in is not a conversation; it is a
button press that leaked.

The create and the send are two requests, and the draft **keeps what the first
one returned**. If the create lands and the send does not, a retry goes into
the conversation that now exists rather than making a second one — otherwise
the failure path leaves behind exactly the blank row this design removes.

Sending is also a **remount**: `Chat` is keyed by the conversation, and that key
changes from `new` to the id. So the handover goes through the query cache
rather than state, which is about to be thrown away — `setQueryData` writes the
conversation and its task where the remounted hook will look for them. `events`
is deliberately left empty: the stream resumes from 0 and replays the message
from the server, so nothing here has to guess the shape of a row the database
already has. Seeding the *task* is the part that matters, and without it the
composer flickers out of "Stop" for a round trip.

### Deleting one that is still answering

Delete is a cascade, and it can land while a worker is inside that turn. The
worker has to survive it, because the alternative is not a failed turn — it is a
**stopped queue**. This wedged the worker twice, for two unrelated reasons, and
both are worth knowing before touching `_execute`:

- **Roll back before the error path touches anything.** A failed flush leaves
  the session refusing every further statement *and* expires every instance it
  holds. The handler's own `logger.exception(..., task_id=str(task.id))` then
  lazy-loads an expired attribute — a statement — and raises from inside the
  logging call, escaping the `except` that exists to contain it. `_execute`
  captures `task_id` as a local before the turn for exactly this reason.
- **Ask the database whether the row is still there.** `session.get()` answers
  from the identity map, and by the time a worker settles a task it ran, that
  row is always in the identity map — so it reports a deleted row as present
  and the settle UPDATEs zero rows, which SQLAlchemy raises `StaleDataError`
  for. `task_service.task_exists()` selects a scalar so there is nothing to
  serve from cache.

Both are covered by
`tests/integration/test_conversation_controls.py`, parametrized over deleting
before and after the assistant message is written — the second case is the
subtle one, because nothing fails during the turn at all.

The route also supersedes the active task before deleting. That is politeness,
not the fix: it narrows the window, and the worker is what closes it.

### Naming a conversation

The first user message names the conversation *provisionally*, by truncation,
so the sidebar has something to show immediately. The worker replaces it with a
real title from `provider.complete()` on the cheap model.

Three things about when it runs, and each is a choice the other options make
worse:

- **From the opening message, not the answer.** That is what a name is for. The
  answer adds length and cost and almost no information, and waiting for it
  would leave a truncated sentence in the sidebar for the whole first turn.
- **Once, on the first turn only.** A title that rewrites itself while you are
  talking is worse than a slightly general one — and a title per turn is a
  provider call per turn for a value that is thrown away.
- **Beside generation, not before or after it.** A cheap model still takes the
  better part of a second, and every serial placement of that second is visible:
  before, it delays the first token; after, it holds the task `running`, which
  the browser reads as "still answering" and leaves the composer disabled with
  the answer already on screen. It runs as a task awaited in a `finally`, on a
  session of its own — one `AsyncSession` driven from two places at once is a
  corrupted connection, not a race you can reason about.

**A rename beats the namer, always.** That is what `title_custom` is for: the
namer checks it before starting and again after the round trip, because a
rename can land inside one. Without the second check, a name typed during the
first turn is silently overwritten seconds later — a bug nobody can reproduce on
demand.

**Failing to name is not an error.** The provisional title is already written
down and is serviceable, so `complete()` returning `None` is a value to ignore.
Nothing retries and nobody is told, which is the property that makes a blocking
provider call acceptable in the middle of a turn at all.

## The worker

**Generation does not happen in the HTTP request.** `POST /messages` writes the
user's message, enqueues a `chat_turn` task, and returns a receipt. A separate
process — `app/worker/`, its own container — claims the task and does the
work. `GET /conversations/{id}/stream?since=N` watches.

That split is the whole reason closing a tab no longer costs you a turn. It also
makes three things explicit that were previously impossible to express:
cancellation has to travel through the database, a dead worker has to be noticed
by somebody else, and a second message arriving mid-turn has to resolve to a
decision. Putting generation back in the request handler would make all three
disappear, along with the guarantee.

**Keep the worker in its own process.** Not a thread, not a `create_task` in the
API. The moment the thing doing the work can see the thing serving the request,
every problem above turns back into a shortcut.

### Postgres is the queue

No Redis, no broker, no new infrastructure. Three pieces, all in
`services/task_service.py`:

- **Claiming** is `select … for update skip locked`. Two workers running that
  query take different rows instead of queueing behind each other.
- **Waking** is `NOTIFY` on one global channel. Without it the worker polls, and
  every chat turn waits half a poll interval for nothing.
- **Sweeping** is what makes the claim safe. A worker killed mid-task leaves a
  row marked `running` forever, because nothing in Postgres knows the worker
  existed. The sweeper is that knowledge. It is not optional.

That is what Oban, River, and Solid Queue are underneath. Outgrow it and you
will know — the symptom is queue depth you can measure, not an opinion.

### Two channels, and why

Durable state goes in `event_records` and can be replayed from any point.
**Tokens go through `LISTEN`/`NOTIFY` and are gone if nobody was listening.**

A token is not worth a row, and a row is not fast enough for a token. Because
every durable event is published on both paths, a dropped token costs nothing
permanent: the authoritative text arrives moments later as an
`assistant_message` and replaces the preview. Build the live path so that losing
a frame is a flicker, never a corruption.

### Resuming is the only path

`seq` is the cursor. A client says "I have seen up to N" and gets everything
after it, then the live tail. A browser that just sent a message and a browser
that refreshed halfway through an answer run identical code with different
numbers — so the interesting case is exercised constantly instead of only when
something goes wrong.

Subscribe **before** replaying. The other order loses anything published between
the query and the subscribe, and that race is invisible in testing.

### Cancellation is a request, not a command

The worker is another process; it cannot be interrupted. `cancel_requested` is a
flag it checks at every durable event and roughly once a second while tokens
stream — a turn with no tool calls has no other boundary until it is finished,
and a Stop that only lands after the answer is complete is not a stop.

**A cancelled turn is a shorter turn, not a discarded one.** Whatever had been
generated is written down on the way out. If you change this code, keep that
true — the alternative is text vanishing from the user's screen on next refresh.
There is exactly one exception, and it is a turn that was *superseded* rather
than cancelled; see [Sending while one is running](#sending-while-one-is-running)
for why that one has to go the other way.

### Sending while one is running

**The composer is not locked during a turn.** Sending a new message while one is
running **supersedes** the old task rather than racing it: `POST /messages`
retires the active task, *then* writes the new message, *then* enqueues a turn
for it. Two workers appending to one conversation interleave into nonsense; the
newest message wins.

Supersession is not just a cancellation with another name, and the difference is
the one thing here that is easy to get wrong:

- **A superseded turn discards what it had written.** This is the deliberate
  exception to the rule above, and the reason is ordering. The new user message
  is already in the log by the time the retired worker notices, so flushing a
  half-sentence there files the answer to the old question *below* the question
  that replaced it — and leaves the turn about to run replaying a history that
  ends on an assistant turn. `task_service.stop_reason()` returns which kind of
  stop this is precisely so `_generate` can flush for one and not the other. A
  bool cannot say this, which is why it is not one.
- **The row goes terminal immediately, even while a worker still holds it.**
  Not an attempt to interrupt the worker — it cannot be. It is so `active_task`
  stops naming an obsolete turn, and a browser reattaching in that window is
  pointed at the turn that will answer it.
- **The stream endpoint filters status frames by task id.** The retired worker
  settles a second or two later and publishes its own terminal status to the
  same channel; without the filter that frame hangs up the stream watching the
  turn that replaced it. Event frames are *not* filtered — rows the old turn
  already wrote belong to the conversation whoever produced them.

On the client, `useConversationStream` aborts the open stream **before** it
clears the preview and sets the new cursor. The effect's own cleanup would abort
a render later, and the read loop can deliver another chunk in between — tokens
carry no task id to filter on, so they would land in `liveText` as text the
server has already thrown away.

The composer shows one button, not two: with a turn running and the box empty it
is Stop, and once there is something to send, sending *is* stopping.

### Scheduled agents

A `schedules` row is a prompt plus a cadence. The worker expands due rows into
`agent_run` tasks and gets out of the way, so a slow agent cannot delay the next
thing that is due. Missed runs are skipped rather than backfilled — coming back
from a day offline should be one run, not a day of them.

An agent run **creates a real conversation**, which is why there is no separate
viewer for it: what the agent did at 3am reads in the same UI as everything
else, tool calls and all. It runs with `agent_system_prompt`, which exists
because a model with nobody watching should never stop to ask a question — that
produces a run that accomplished nothing.

**An agent cannot reach outside this system, and that is deliberate.** The
template shipped a `send_email` tool for exactly this purpose and it was
deleted here. A scheduled run acting on its own judgement at 3am, against a
patient dataset, with a tool that sends mail to an address it chose, is a
combination worth not having — and the alternative costs nothing, because an
agent run already writes into a real conversation. "Every Monday, list patients
newly meeting the nephrotoxic criteria" lands in the UI where a clinician reads
it, with the query and its definitions attached, and nothing leaves the
building.

## Frontend

- **Server state is TanStack Query. Local UI state is `useState`.** The line
  moved when the worker arrived: an in-flight turn is now *server* state — it
  has a task row and its events are already durable — and the only genuinely
  local thing left is the live token buffer, which exists nowhere else and is
  replaced by the durable `assistant_message` moments later.
- **Overlap and deduplicate; do not try to hand off precisely.** The fetched
  transcript and the streamed events cover the same range on purpose, and
  `mergeEvents` keys them by `seq`. Every scheme that tries to make the two
  halves meet exactly has a race in it.
- **The persisted transcript and the in-flight turn render through one shape.**
  Both fold down to `TurnItem[]` in `src/turns.ts`. Two render paths is how a
  tool card mid-stream ends up looking different from the same tool card after a
  refresh. That fold is a pure function of the event log with no React in it —
  the frontend's counterpart to `to_event_out()` — so it lives outside
  `components/`.
- **Never render streamed text straight from the stream.** Tokens arrive in
  uneven bursts and React batches whatever lands in one tick, so painting on
  arrival looks jittery rather than fast. `useRevealedText` separates the reveal
  rate from the arrival rate, and the two surfaces that use it — `StreamingText`
  for the reasoning, `StreamingMarkdown` for the answer — stay leaf components
  so the per-frame renders happen there rather than redrawing the transcript
  sixty times a second.
- **Where a file goes, what it may import, and what it may export** are in
  [Layout](#layout) — one file, one default export named after it; absolute
  imports; no React above the view model. They are there rather than here
  because the same rules govern both halves of the repo.
- **If it would survive being rendered by a different component, it is a hook.**
  The same test `services/` gets on the backend. `useConversationStream` owns
  cursors, reattaching and supersession, which is why `Chat.tsx` is arrangement
  and nothing else.
- **Which screen is showing lives in the URL, and only there.** react-router,
  declarative mode: `App` holds the route table for the page and `Sidebar` a
  second `<Routes>` for the list beside it, both matching the patterns in
  `src/paths.ts`, so the two read one address and cannot disagree. This
  replaced a conversation id in the URL plus a "view" in component state — two
  sources that did disagree: clicking a conversation from the dashboard
  highlighted it and changed the address while the dashboard stayed on
  screen, and a refresh threw you back into chat. **Every URL is spelled in
  `paths.ts`** — a pattern for the router and a builder for links — and
  `paths.test.ts` runs each builder through the router's own `matchPath`, so
  a new screen is a pattern, a builder and a test case, and none of them can
  drift. Selections are links (`<Link>`), not click handlers, so cmd-click
  opens one in a new tab.
- **Reset state with a `key`, not an effect.** `ChatPage` mounts `Chat` with
  `key={id}`, so switching conversations remounts instead of clearing five
  pieces of state by hand and having to keep that list current.
- **The pane scrolls, not the reading column.** The scroll container spans the
  whole area beside the sidebar and `Column` re-centres the text inside it, so
  the scrollbar rides the edge of the window instead of sitting against the last
  word of every line. It is also what stops the transcript clipping whatever
  bleeds into the margin — an icon button's hover background, a negative margin
  — because `overflow` clips at the padding box and the bleed now lands inside
  it. Three subtrees have to agree on that width, which is why it is a component
  and not a class string in each of them.
- **Tailwind utilities only.** No CSS files beyond `index.css`; theme tokens go
  in its `@theme` block. shadcn/ui drops in cleanly when you want real
  components: `pnpm dlx shadcn@latest init`.
- `noUncheckedIndexedAccess` is on. `array[0]` is `T | undefined`. Handle it.
- **SSE uses `fetch` + `ReadableStream`, never `EventSource`** — `EventSource`
  cannot POST and cannot set headers, so it is unusable for sending a message or
  for any authenticated stream.

### Enforcement

`eslint`, `prettier --check`, `tsc` and `vite build`, all four in CI. `pnpm
lint:fix` and `pnpm format` before you push.

`eslint.config.js` is built the same way as the backend's ruff config: take the
broad recommended sets — typescript-eslint **strict + stylistic type-checked**,
react-hooks, unicorn, jsx-a11y — then turn individual rules off with a note
saying why. Each CONVENTIONS.md rule it enforces cites the line it comes from.

The `off`s are the interesting part, because most of them are a general-purpose
rule meeting a decision this codebase already made:

- **`unicorn/no-null`** — `null` *is* the wire format. The backend sends it for
  an absent task and an unanswered tool call, and `undefined` does not survive
  JSON.
- **`unicorn/name-replacements`** — would rename `props` to `properties` and
  `ref` to `reference`. That is React's vocabulary, not an abbreviation we chose.
- **`unicorn/no-break-in-nested-loop`** — fires on `break` inside a `switch`
  that sits inside a `for`, which is the exact shape of the fold in `turns.ts`.
- **`jsx-a11y/aria-role`** is configured with `ignoreNonDOM`, because
  `<Bubble role={'assistant'}>` is the chat domain's role — the same one the
  backend puts on a message — and not an ARIA role.

Two rules are worth knowing about because they caught real defects rather than
style. `@typescript-eslint/no-misused-spread` found that `apiFetch` spread
`init.headers` into an object literal: `HeadersInit` is also allowed to be a
`Headers` or an array of pairs, and spreading either of those silently produces
no headers at all. `react-hooks/set-state-in-effect` found an effect resetting
five pieces of state on a prop change, which is what `key={id}` is for.

This was all added late, and the gap it left is instructive: the rules above
were written down from the start and *nothing read them*, so `MessageList.tsx`
quietly grew to three components while the doc said one. Note also that
`react-refresh/only-export-components` does not catch that — it inspects
exports, not definitions. `react/no-multi-comp` is the rule that does.

The other half — server state vs local state, the single render path, the
overlap-and-dedupe rule — is judgement no linter can express, and it is written
down in [Frontend](#frontend) above. Neither replaces the other.

## Checks

```bash
scripts/setup.sh           once per clone: deps, .env, and the git hook
scripts/check.sh           lint, format, types and tests, both halves
scripts/check.sh --fast    the subset the pre-commit hook runs
scripts/check.sh backend   one half only
```

**One script, three callers.** You run it by hand, `.githooks/pre-commit` runs
it on the halves you touched, and `.github/workflows/ci.yml` runs it after
installing dependencies. A hook that checks something different from CI is worse
than no hook: it teaches you to trust a green that does not mean anything.

`--fast` drops exactly two things, and both for the same reason — they are not a
pure function of the source. The pytest integration suite needs a Postgres, and
`vite build` is slow and re-proves what `tsc` just proved. Everything else runs
on every commit.

The hook is **opt-in per clone** (`git config core.hooksPath .githooks`, which
`scripts/setup.sh` does for you), because git refuses to version `.git/hooks`.
It checks your working tree rather than the index — stashing unstaged work in
the middle of a commit is a good way to lose it, and CI checks the real commit
anyway. `git commit --no-verify` skips it, which is a legitimate thing to do on
a work-in-progress commit.

### Structural tests

`backend/tests/structure/` and `frontend/src/structure.test.ts` assert on the
**shape of the codebase** rather than on what it computes: which module may
import what, which functions take which arguments, whether two files that must
change together did. A structural test is a linter rule that was too
repo-specific to be a linter rule.

They exist because the alternative does not work. Most of this document is
prose, and prose is enforced by nothing — which is not a hypothetical worry:

- `MessageList.tsx` quietly grew to three components while this file said one,
  until `react/no-multi-comp` was switched on;
- `routes/schedules.py` built its own queries for months while this file said
  routes call services.

Both rules were written down from the start. Neither was checked. What is
checked now:

| Rule | Where |
| --- | --- |
| Only the adapter imports `anthropic` | backend |
| Only `config.py` reads the environment | backend |
| Routes do not build queries | backend |
| Every service function takes an explicit `session` | backend |
| Tool schemas are closed and every property is described | backend |
| No registered tool raises on bad input | backend |
| Every `LLMStreamEvent` is handled by the worker | backend |
| The TypeScript frame union matches what the backend sends | backend |
| `services/` imports neither `api/` nor `worker` | backend |
| Only `main.py` imports `app.api` at all | backend |
| Every `__init__.py` is empty but the tool registry | backend |
| No literal Tailwind colour anywhere in `src/` | frontend |
| The view model and `api/` import no React | frontend |
| A component or hook file is named after what it exports | frontend |
| Every top-level `.ts` module has a test beside it | frontend |

**What belongs here:** a rule where the cost of the drift is high and the cost
of the check is a regex or an AST walk. **What does not:** anything `ruff`,
`basedpyright` or `eslint` already catches — a rule in two places is a rule that
will disagree with itself — and anything stylistic. A test that fails because a
file was sensibly renamed teaches people to delete tests.

Write the failure message as an argument, not an assertion. Every one of these
names the section above that it enforces, because the person who hits it at
11pm is deciding whether the rule or their code is wrong, and needs the reason
to decide.

**Prove a new one fails.** Break the convention on purpose, watch the test go
red, put it back. A structural test that cannot fail is worse than none: it is a
line in the table above that is not true.

## What is deliberately missing

Each of these is *additive* — cheap to add later, expensive to build before you
need it. The seam each one needs already exists.

| Missing | Add it when | Seam that's ready |
| --- | --- | --- |
| Pagination | A conversation list or a transcript gets long enough to notice | The `{data, meta}` envelope already has the room |
| Schedules UI | You tire of `curl` | `/api/schedules` exists and is unreachable from the browser |
| Sign-in | A curator needs to edit on a public deployment | `get_current_user()` is the only thing that decides who a request is. Verify a token there — name the algorithms, and give every failure the same 401 — and nothing below it changes |
| Multi-user sharing | Two people need the same conversation | Every query is scoped by `user_id`, so a link 404s for anyone else — sharing is a row, not a URL change |
| Error tracking | You have users who will not tell you when it breaks | `ErrorBoundary.componentDidCatch`, and the exception handler in the API |
| Prompt caching | The tools and system prompt together exceed ~1000 tokens | They already render as one stable prefix; below that size it will not cache at all |

### Already done: the event log, the worker, migrations, tests, routing, markdown

Six entries used to live in the table above: replacing the one-row-per-turn
`messages` table, moving generation out of the request, migrations, tests,
routing with a conversation list, and markdown rendering. All six are done — see
[The transcript](#the-transcript) and [The worker](#the-worker) — and the note
survives as a warning about ordering.

**Delete a row the day it stops being true.** The two most recent ones sat in
this table claiming "the id never reaches the URL today" and "assistant text is
plain text today" while `useConversationRoute.ts` and `Markdown.tsx` were both
already in the tree. A stale "deliberately missing" row is worse than no table:
it is the document telling you not to look.

Do the event log **before** adding tools, and the worker **after** it. In that
order each step is additive. In any other order they are rewrites: retrofitting
an event log into code that assumed one row per turn touches every layer at
once, and a worker with nowhere durable to write its progress cannot give you
the thing you wanted a worker for.

The migration switch carried its own lesson. `models.py` had been maintained as
a hand-written mirror of `schema.sql`, and it had quietly drifted: five CHECK
constraints, two partial indexes and four column defaults existed only in the
SQL. Autogenerating against the models as they stood would have produced a
schema missing all of it, silently. **If you keep two descriptions of one
schema, diff them before you trust either** — `pg_dump --schema-only` on a
database built each way is the check, and it is worth the ten minutes.

Tests taught the same lesson about a different claim. The table above used to
say `LLMProvider` was "a Protocol a fake satisfies", and that was true of the
type and false of the wiring: the worker built its provider at module scope, so
a fake could only be monkeypatched over a global and importing the worker at all
required an API key. **A seam nothing has ever used is a hypothesis, not a
seam.** Writing the first test is how you find out which one you have.
