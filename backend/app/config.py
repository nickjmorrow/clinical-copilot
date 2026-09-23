"""Typed configuration, read once from the environment.

Everything that varies by environment comes from here. Importing `settings`
anywhere is fine; calling `os.getenv` anywhere else is not — a typo in an env
var name should fail at startup with a clear error, not at 2am with a None.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The identity every request gets outside public mode.
#
# Not a Settings field, because it is not environment-dependent: it is the one
# user that exists when there are no visitors. It lives here rather than beside
# the identity seam in `api/deps.py` because the worker needs it too — an agent run
# has to belong to somebody, and a process that serves no HTTP should not import
# the HTTP layer to find out who.
DEV_USER_ID = "dev-user"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5433/app"

    # Checked where it is used, in AnthropicProvider, rather than by a validator
    # here. Only the worker talks to the provider — the API, the migration step,
    # and every test do not — and a setting that refuses to load without a key
    # forces one on all of them. An unset env var arrives as an empty string, so
    # a plain `str` would otherwise fail much later as an opaque 401.
    anthropic_api_key: str = ""

    # See CONVENTIONS.md § Choosing a model before changing this.
    anthropic_model: str = "claude-opus-5"

    # A ceiling, not a target — the model stops when it is done. Set high
    # because truncating mid-sentence costs a full retry, and streaming means
    # there is no HTTP timeout to worry about.
    anthropic_max_tokens: int = 64_000

    # The cheap model, for the small utility calls that are not the
    # conversation itself. Today that is exactly one thing: naming a
    # conversation from its first message. This is the one place a downgrade
    # needs no measurement — the task is a six-word summary, and Opus would
    # spend a turn's worth of reasoning on it.
    anthropic_fast_model: str = "claude-haiku-4-5"

    # Small on purpose: a title that needs more than this is not a title, and
    # the cap is cheaper than trusting the prompt.
    anthropic_fast_max_tokens: int = 64

    # How many times the model may call tools before the turn is abandoned. The
    # failure this guards against is a tool that can never succeed: it returns
    # an error, the model reads it, adjusts, tries again, forever. Without a cap
    # that is an unbounded bill. Raise it when an agent legitimately needs many
    # steps; do not remove it.
    max_tool_iterations: int = 8

    # How long the worker waits on a LISTEN before looking around anyway. It is
    # woken by NOTIFY the instant a task is enqueued, so this is not the latency
    # of a chat turn — it is how often due schedules and dead workers get
    # noticed when nothing else is happening.
    worker_idle_seconds: float = 5.0

    # A task claimed and then not finished within this long is assumed to belong
    # to a worker that died, and goes back on the queue. Must comfortably exceed
    # your longest real turn, or the sweeper will steal live work.
    task_stale_seconds: int = 900

    # Touched once per loop pass, so a container healthcheck can tell a worker
    # that is running from one that is wedged. The worker has no HTTP port, and
    # "the process exists" is not liveness — Docker already restarts a process
    # that exits.
    # S108: a fixed path inside the worker's own container, not a shared
    # tmpdir on a multi-user host. Override it if that stops being true.
    worker_heartbeat_path: Path = Path("/tmp/worker-alive")  # noqa: S108

    # Backoff for a task that failed for a reason worth trying again — a rate
    # limit, a provider outage. Doubles per attempt from the base, capped at the
    # max. See RETRYABLE_ERROR_CODES in llm/types.py for which failures qualify;
    # a wrong API key is not one of them.
    task_retry_base_seconds: float = 5.0
    task_retry_max_seconds: float = 120.0

    # A ceiling on one user message. Unbounded input is unbounded tokens is an
    # unbounded bill, and the number that matters is the one you picked on
    # purpose rather than the one the model happened to accept.
    max_message_length: int = 20_000

    # Where `python -m app.seed` finds a Synthea CSV export when `--from` is
    # not given. Not checked in: about 380 MB, and regenerable by
    # scripts/generate-synthea.sh.
    synthea_csv_dir: Path | None = None

    # The clinical rules the model is held to. Most of this is about what NOT
    # to do, because the failure mode is the model being helpful: supplying a
    # threshold it knows, or narrowing a question it could not resolve.
    system_prompt: str = (
        "You are a clinical data assistant for a hospital. You answer questions about "
        "patients in this hospital's records by calling the `find_patients` tool.\n\n"
        "The hospital defines what clinical terms mean — 'impaired renal function', "
        "'nephrotoxic medication' and the rest — and those definitions are the authority. "
        "Never state a threshold from your own knowledge, never invent one, and never "
        "describe a patient as meeting a criterion you did not get from the tool.\n\n"
        "When the tool reports a term it could not resolve, ask the user which defined term "
        "they meant, in one short question. Do not guess, and do not retry with a different "
        "guess.\n\n"
        "Patient names and dates of birth are not available to you. Refer to patients by "
        "patient id.\n\n"
        "The tool also answers aggregate questions — how many, what is the average, broken "
        "down by what — through defined MEASURES and DIMENSIONS, the same way it answers a "
        "plain list through defined filter terms. Use `measures` and `group_by` for those "
        "rather than counting or averaging rows yourself.\n\n"
        "To narrow, widen or otherwise change a previous answer, CALL THE TOOL AGAIN with "
        "the terms that express the new question. Never filter the rows of an earlier "
        "result yourself: your idea of where a boundary falls is not the hospital's, and a "
        "follow-up answered from memory is neither audited nor reproducible.\n\n"
        "Always show the definitions an answer relied on, including the threshold and its "
        "rationale, so the reader can check why those patients and not others. If a result "
        "was capped, say so rather than implying the list is complete. Be concise.\n\n"
        "This is synthetic data in a demonstration system. It is not a clinical decision "
        "support tool, and nothing here should inform a real care decision."
    )

    # Agent runs have nobody watching, which changes how the model should
    # behave: there is no one to ask, and stopping to request clarification
    # means the run produced nothing at all.
    agent_system_prompt: str = (
        "You are an agent running on a schedule. No human is watching this run "
        "and nobody will answer a question, so never ask one — make a reasonable "
        "assumption, state it, and finish the task. Use your tools to gather "
        "what you need, and write what you found into this conversation — that "
        "transcript is how anyone will read the result."
    )

    # Naming a conversation. Terse and negative, because every failure mode
    # here is the model being helpful: quoting the request back, adding
    # "Conversation about", wrapping the answer in a sentence. The length is
    # enforced again in the service — a prompt is guidance, not a constraint.
    title_system_prompt: str = (
        "Write a title of at most six words for the conversation below. "
        "Reply with the title alone: no quotes, no punctuation at the end, "
        "no preamble, and never the words 'conversation' or 'chat'. "
        "Use the language the user wrote in."
    )

    # ----------------------------------------------------------- public mode
    #
    # For a deployment anyone can open. With this on, each browser gets an
    # identity of its own — a random id in an HttpOnly cookie,
    # see `api/middleware.VisitorMiddleware` — instead of every request being
    # the one dev user. That is the difference between strangers sharing one
    # conversation list (and deleting each other's) and each having their own.
    # A visitor holds no roles, so everything gated to curators and auditors
    # stays closed.
    visitor_mode: bool = False

    # Send the cookie only over HTTPS. Leave this on anywhere real; browsers
    # treat http://localhost as secure already, so local testing needs no
    # change either.
    visitor_cookie_secure: bool = True

    # Cost ceilings, both off by default. A public URL is otherwise an open tap
    # on the API key: every message is a turn on the most capable model. Both
    # are counted from `usage_events`, which no delete can reset.
    #
    #   messages_per_hour   per user (per visitor, in public mode) — fairness
    #   daily_token_budget  input + output tokens across everyone since midnight
    #                       UTC — the ceiling on the bill. Set a spend limit in
    #                       the Anthropic console as well; this one is enforced
    #                       between turns, so a turn in flight can overshoot it.
    messages_per_hour: int | None = None
    daily_token_budget: int | None = None

    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["console", "json"] = "console"

    # Comma-separated, not a list.
    #
    # pydantic-settings parses a `list[str]` field from the environment as
    # JSON, so `CORS_ORIGINS=http://localhost:3000` is a startup crash and
    # `CORS_ORIGINS=["http://localhost:3000"]` is what it actually wants. That
    # is a miserable thing to write in a compose file, so the field is a plain
    # string and the split happens here. Same trap applies to any list- or
    # dict-typed setting you add.
    cors_origins: str = "http://localhost:3000"

    @property
    def database_dsn(self) -> str:
        """The URL without SQLAlchemy's `+driver` suffix.

        asyncpg is reached two ways here: through SQLAlchemy for everything
        normal, and directly for LISTEN/NOTIFY, which SQLAlchemy has no API for.
        The direct path wants a plain libpq URL.
        """
        return self.database_url.replace("+asyncpg", "", 1)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
