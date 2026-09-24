"""Structural tests: the conventions, checked by a machine.

Most of AGENTS.md is prose, and prose is not enforced by anything. That is not
a hypothetical worry — it already happened twice in this repo. `MessageList.tsx`
grew to three components while the doc said one, and `routes/schedules.py` built
its own queries while the doc said routes call services. Both were written down
from the start. Neither was checked.

A structural test asserts on the *shape of the codebase* rather than on what it
computes: which module may import what, which functions take which arguments,
whether two files that must change together did. It is a linter rule that was
too repo-specific to be a linter rule.

**What belongs here.** A rule where the cost of the drift is high and the cost
of the check is a regex or an AST walk: the LLM seam, the config boundary, the
tool contract, the four-file event change. Every test below names the section of
AGENTS.md it enforces.

**What does not.** Anything `ruff`, `basedpyright` or `eslint` already catches —
duplicating them is a second place to update. Anything stylistic; a test that
fails because a file was renamed sensibly teaches people to delete tests.
Anything behavioural, which is what the rest of the suite is for.

**Frontend-only rules live in `frontend/src/structure.test.ts`,** not here: a
frontend developer running `pnpm test` should see them fail. The one exception
is the cross-language event contract at the bottom of this file, because the
backend is the side that defines it.

These tests need no database and no network, so the pre-commit hook can run them
on every commit. Keep it that way.
"""

import ast
import re
import typing
from pathlib import Path

import pytest

from app import tools
from app.db import SessionFactory
from app.llm.types import LLMStreamEvent, ToolOutput
from app.tools.base import ToolContext

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
APP = BACKEND / "app"
FRONTEND_SRC = REPO / "frontend" / "src"

APP_MODULES = sorted(APP.rglob("*.py"))


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO))


def _imported_roots(path: Path) -> set[str]:
    """Top-level package names this module imports, via AST rather than grep.

    A regex counts the word `anthropic` in a docstring explaining why nothing
    may import it, which is how a well-meaning check ends up being deleted.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


# --------------------------------------------------------------- the seam
#
# AGENTS.md > The LLM seam: "`llm/anthropic_provider.py` is the ONLY file
# allowed to import `anthropic`. If the SDK appears anywhere else, the seam has
# leaked and the next model swap becomes a refactor."


def test_only_the_adapter_imports_the_provider_sdk():
    allowed = APP / "llm" / "anthropic_provider.py"
    leaked = [
        _relative(path)
        for path in APP_MODULES
        if path != allowed and "anthropic" in _imported_roots(path)
    ]
    assert leaked == [], (
        f"The `anthropic` SDK leaked out of the seam into {leaked}. "
        "Only app/llm/anthropic_provider.py may import it — see AGENTS.md > The LLM seam."
    )


# -------------------------------------------------------- the config boundary
#
# AGENTS.md > Configuration: "`os.getenv` anywhere else is a bug: a typo in an
# env var name should fail at startup with a clear error, not at 2am with a
# `None`."


def _reads_the_environment(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        # Matches a getenv call or any use of the environ mapping.
        if isinstance(node, ast.Attribute) and node.attr in {"getenv", "environ"}:
            value = node.value
            if isinstance(value, ast.Name) and value.id == "os":
                return True
    return False


def test_the_environment_is_read_in_exactly_one_place():
    allowed = APP / "config.py"
    leaked = [
        _relative(path) for path in APP_MODULES if path != allowed and _reads_the_environment(path)
    ]
    assert leaked == [], (
        f"{leaked} read the environment directly. Every environment-dependent value is a field "
        "on Settings in app/config.py — see AGENTS.md > Configuration."
    )


# ------------------------------------------------------------ routes are thin
#
# AGENTS.md > Layout: "Routes exist to translate HTTP into a service call and
# back." The check is narrow on purpose: a route may name a model in a type
# annotation, but the moment it builds a query it has grown a second home for
# business logic that a CLI or the worker cannot reach.


def test_routes_do_not_build_their_own_queries():
    offenders: list[str] = []
    for path in sorted((APP / "api" / "routes").glob("*.py")):
        roots = _imported_roots(path)
        if "sqlalchemy" not in roots:
            continue
        # health.py's `select 1` is a liveness probe, not business logic: it
        # exists precisely to touch the database without going through anything.
        if path.name == "health.py":
            continue
        offenders.append(_relative(path))

    assert offenders == [], (
        f"{offenders} import sqlalchemy. A route validates, authorizes, calls a service and shapes "
        "a response; the query belongs in app/services/ where a second caller can reach it. "
        "See AGENTS.md > Layout."
    )


# ------------------------------------------------------- services take a session
#
# AGENTS.md > Layout: "services/ — Business logic. Every function takes an
# explicit session." Reaching for an ambient request-scoped session is what
# makes service code unusable from the worker.


def _public_async_functions(path: Path) -> list[ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and not node.name.startswith("_")
    ]


def test_every_service_function_takes_an_explicit_session():
    offenders: list[str] = []
    for path in sorted((APP / "services").glob("*.py")):
        for function in _public_async_functions(path):
            first = function.args.args[0] if function.args.args else None
            if first is None or first.arg != "session":
                offenders.append(f"{_relative(path)}::{function.name}")

    assert offenders == [], (
        f"{offenders} do not take `session` as their first argument. Every service function takes "
        "an explicit session — see AGENTS.md > Layout."
    )


# --------------------------------------------------------- the tool contract
#
# AGENTS.md > Tools: "Schemas are closed. Every property declared, `required`
# listed, `additionalProperties: false`. The adapter sends tools as strict, so
# the provider guarantees the arguments validate before a handler ever sees
# them — which is what lets `run` read its input directly instead of
# re-checking every field. A schema that isn't closed silently gives that
# guarantee up."


@pytest.mark.parametrize("definition", tools.definitions(), ids=lambda d: d.name)
def test_tool_schemas_are_closed(definition):
    schema = definition.input_schema
    properties = schema.get("properties", {})

    assert schema.get("type") == "object", f"{definition.name}: input_schema must be an object"
    assert schema.get("additionalProperties") is False, (
        f"{definition.name}: additionalProperties must be false. Without it the provider stops "
        "guaranteeing the input validates, and the handler's direct indexing becomes a KeyError."
    )
    assert sorted(schema.get("required", [])) == sorted(properties), (
        f"{definition.name}: `required` must list every property. A strict schema with an optional "
        "property is a handler reading a key that may not be there."
    )
    undescribed = [name for name, spec in properties.items() if not spec.get("description")]
    assert undescribed == [], (
        f"{definition.name}: {undescribed} have no description. The schema is prompt, not "
        "documentation — the model reads it to decide what to pass."
    )


def test_tool_descriptions_say_when_to_call_the_tool():
    # AGENTS.md > Tools: "The description is prompt, not documentation. Say
    # *when* to call it, not just what it does." A length floor is a crude proxy
    # and deliberately crude: it catches "Gets the time." and nothing else.
    too_short = [d.name for d in tools.definitions() if len(d.description) < 80]
    assert too_short == [], (
        f"{too_short} have a one-line description. Say when the model should reach for the tool, "
        "not just what it does — see AGENTS.md > Tools."
    )


def _structure_context() -> ToolContext:
    """A context for tests that never reach the database.

    `SessionFactory()` does not connect until something is executed, so this
    needs no Postgres. If a handler ever did reach the database from here the
    connection error is caught by the registry and returned as an error result,
    which is the property under test anyway.
    """
    return ToolContext(session=SessionFactory(), user_id="structure-test")


async def test_no_registered_tool_raises_on_bad_input():
    """AGENTS.md > Tools: "Handlers never raise."

    The registry catches an exception anyway and turns it into an error result,
    so this passes even for a handler that breaks the rule. That is the point:
    what is being pinned here is that a bad argument can never end a turn, no
    matter which of the two layers upholds it.
    """
    for definition in tools.definitions():
        output = await tools.execute(definition.name, {}, _structure_context())
        assert isinstance(output, ToolOutput)


async def test_an_unknown_tool_is_an_error_result_not_an_exception():
    output = await tools.execute("no_such_tool", {}, _structure_context())
    assert output.is_error


# ------------------------------------------------ the four-file event change
#
# AGENTS.md > The LLM seam: "Adding an event type is a four-file change, and all
# four must stay in step: llm/types.py, the adapter that emits it, the SSE
# encoder, and frontend/src/api/stream.ts."
#
# The first two are checked here by walking the union. The last is a string
# comparison across languages, which is as good as it gets without a shared
# schema — and still better than finding out in the browser.

STREAM_EVENTS = typing.get_args(LLMStreamEvent)


def test_every_stream_event_is_handled_by_the_worker():
    # The whole package, not one module: `inspect.getsource` on a package hands
    # back its (empty) __init__ and every event would look unhandled.
    source = "".join(path.read_text() for path in sorted((APP / "worker").glob("*.py")))
    unhandled = [event.__name__ for event in STREAM_EVENTS if event.__name__ not in source]
    assert unhandled == [], (
        f"{unhandled} are in LLMStreamEvent but never named in app/worker/. The match statement "
        "in worker/turn.py is the consumer of that union — an unhandled case falls through "
        "silently. See AGENTS.md > The LLM seam."
    )


# The frames that cross the wire. Changing this set is the four-file change:
# update llm/types.py, the emitter, the SSE encoder, and the TypeScript union in
# frontend/src/api/stream.ts — then update this line.
WIRE_FRAMES = {"event", "status", "text", "thinking"}


def test_the_typescript_union_matches_the_frames_the_backend_sends():
    stream_ts = (FRONTEND_SRC / "api" / "stream.ts").read_text()
    # Up to the blank line that ends the declaration. Not up to the first `;`:
    # the members are object type literals and are full of them.
    union = stream_ts.split("export type StreamFrame =", 1)[1].split("\n\n", 1)[0]
    declared = set(re.findall(r"type: '([a-z_]+)'", union))

    assert declared == WIRE_FRAMES, (
        f"frontend/src/api/stream.ts declares {sorted(declared)} but the backend sends "
        f"{sorted(WIRE_FRAMES)}. Adding an event type is a four-file change and this is the "
        "fourth file — see AGENTS.md > The LLM seam."
    )


def test_every_wire_frame_is_actually_emitted_by_the_backend():
    emitters = "".join(
        path.read_text()
        for path in (
            *sorted((APP / "worker").glob("*.py")),
            APP / "wire.py",
            APP / "api" / "routes" / "conversations.py",
        )
    )
    missing = [frame for frame in sorted(WIRE_FRAMES) if f'"{frame}"' not in emitters]
    assert missing == [], (
        f"{missing} are declared on the wire but no backend module emits them. Either the frame "
        "was removed and the TypeScript union was not, or WIRE_FRAMES above is stale."
    )


# --------------------------------------------------- clinical SQL has one author
#
# AGENTS.md > The definitions layer: "`app/clinical/assembler.py` is the only
# thing in this codebase that writes SQL for a clinical question."
#
# This is what statement gating looks like when the door has no handle. There is
# no runtime filter checking that a statement starts with SELECT, because
# nothing anywhere constructs a statement that could start with anything else —
# and a regex pretending to guard that would be worse than nothing, since it
# would imply the danger exists and had been handled.

CLINICAL_TABLES = ("Patient", "Medication", "Prescription", "Observation", "MedicationAnnotation")


def _touches_table(name: str, source: str) -> bool:
    """Whether `source` uses `name` as a model — `Name.column` or `(Name` as
    the first argument of a call — rather than merely containing it as a
    substring of a longer identifier.

    A naive substring check would flag `ObservationCatalog` for `Observation`,
    which is exactly the kind of table this module is allowed to read — it is
    metadata about the dataset, not a clinical table. `\\b` at the end of
    `name` is what tells the two apart: there is no word boundary between
    "Observation" and "Catalog", so `Observation\\b` does not match inside it.
    """
    return bool(re.search(rf"\b{name}\.", source)) or bool(re.search(rf"\({name}\b", source))


def test_only_the_assembler_queries_the_clinical_tables():
    allowed = {
        APP / "clinical" / "assembler.py",
        APP / "clinical" / "columns.py",
        APP / "services" / "seed_service.py",
        # Counts, provenance and reference values for the "what is in here"
        # panel. Allowed because it answers a question about the DATASET
        # rather than about patients, and the test below is what keeps that
        # distinction real rather than a claim in a docstring.
        APP / "services" / "catalog_service.py",
    }

    offenders: list[str] = []
    for path in APP_MODULES:
        if path in allowed:
            continue
        imported = _imported_modules(path)
        if "app.models" not in imported:
            continue
        source = path.read_text()
        touched = [name for name in CLINICAL_TABLES if _touches_table(name, source)]
        if touched:
            offenders.append(f"{_relative(path)} -> {touched}")

    assert offenders == [], (
        f"{offenders} reference the clinical tables directly. Every clinical query is assembled "
        "from validated predicates in app/clinical/assembler.py — that is the only reason the "
        "definitions layer can claim the model never writes SQL. The exceptions are columns.py "
        "(which owns the column allowlist), seed_service.py (which writes the data) and "
        "catalog_service.py (which only counts rows). See AGENTS.md > The definitions layer."
    )


# AGENTS.md > The definitions layer: the catalog is allowed to count rows, and
# nothing else. Widening the allowlist above without this would turn "only the
# assembler reads patient data" into "only the assembler, and whatever else we
# added later".

IDENTIFYING_COLUMNS = ("full_name", "birth_date", "ssn", "drivers", "passport", "address")


def test_the_catalog_never_reads_an_identifying_column():
    source = (APP / "services" / "catalog_service.py").read_text()
    body = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    # The module docstring names these columns to say it does not read them,
    # so the docstring is removed before looking.
    body = re.sub(r'"""(?:.|\n)*?"""', "", body, count=1)

    found = [column for column in IDENTIFYING_COLUMNS if column in body]
    assert found == [], (
        f"catalog_service.py references {found}. It exists to count rows and list reference "
        "values, and it is on the clinical-table allowlist only because it does not read "
        "patient identifiers. If it needs one, it is no longer a catalog and belongs behind "
        "the definitions layer like every other question about patients."
    )


# ------------------------------------------------------------ import direction
#
# AGENTS.md > Layout > Which direction imports run: "`services/` never imports
# `api/` or `worker`, and nothing outside `app/api/` imports `api/routes` or
# `api/middleware`. A service that reaches up into the HTTP layer is one a
# worker can no longer call, which is the entire reason `services/` exists."


def _imported_modules(path: Path) -> set[str]:
    """Fully-qualified module names this file imports, `from` and `import` alike."""
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
            # `from app.services import task_service` names a module too.
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_services_never_import_the_layers_above_them():
    offenders: list[str] = []
    for path in sorted((APP / "services").glob("*.py")):
        upward = {m for m in _imported_modules(path) if m.startswith(("app.api", "app.worker"))}
        if upward:
            offenders.append(f"{_relative(path)} -> {sorted(upward)}")

    assert offenders == [], (
        f"{offenders} import the HTTP layer or the worker. Business logic may only import the "
        "layers below it — models, llm, tools, bus, config. A service that reaches up into "
        "app/api/ is one the worker can no longer call, which is the entire reason services/ "
        "exists. See AGENTS.md > Layout > Which direction imports run."
    )


def test_only_main_imports_the_http_layer():
    """Nothing outside `app/api/` imports `app.api`, except the file that wires it.

    This was briefly a two-symbol allowance: the worker imported `event_frame`
    from `api/schemas.py` and `DEV_USER_ID` from `api/deps.py`, because it needs
    both and they happened to live there. Those moved to `app/wire.py` and
    `app/config.py`, and the rule got to become absolute — which is the whole
    reason the move was worth doing. Do not reintroduce the allowance; move the
    shared thing down instead.
    """
    allowed = APP / "main.py"
    offenders: list[str] = []

    for path in APP_MODULES:
        if path == allowed or path.is_relative_to(APP / "api"):
            continue
        leaked = {m for m in _imported_modules(path) if m.startswith("app.api")}
        if leaked:
            offenders.append(f"{_relative(path)} -> {sorted(leaked)}")

    assert offenders == [], (
        f"{offenders} import app/api/. That package is HTTP, and only main.py wires it. "
        "Whatever is wanted from it belongs lower down: business logic in services/, the event "
        "shapes both transports send in app/wire.py, a default in app/config.py. A worker that "
        "imports the HTTP layer is one you cannot run without it. See AGENTS.md > Layout."
    )


# ------------------------------------------------------------- empty packages
#
# AGENTS.md > Layout > One thing per file: "every `__init__.py` is empty except
# `tools/__init__.py`, which is the registry and says so. Services are imported
# as modules rather than as loose symbols, so the call site says which layer it
# is calling into."


def test_package_inits_are_empty_except_the_tool_registry():
    registry = APP / "tools" / "__init__.py"
    populated = [
        _relative(path)
        for path in sorted(APP.rglob("__init__.py"))
        if path != registry and path.read_text().strip()
    ]
    assert populated == [], (
        f"{populated} are not empty. A package __init__ that re-exports its modules gives every "
        "symbol two import paths and hides which layer a call goes to; import the module instead "
        "(`from app.services import conversation_service`). tools/__init__.py is the one "
        "exception because it IS the registry. See AGENTS.md > Layout."
    )
