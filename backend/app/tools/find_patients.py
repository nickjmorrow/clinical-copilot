"""The one tool that reaches the clinical dataset.

The model's entire job is `terms`, `measures` and `group_by`: deciding which
*defined* terms a question refers to, which of them are filters, and which
are things to aggregate or group by. It does not write SQL, does not see a
threshold, and cannot name a column or a code that is not on an allowlist.
Everything after this handler is deterministic.

That is the architecture in one file, and the schema is where it is enforced
— there is no `sql` property to pass, and no way to express "eGFR below 45"
except by referring to a term that already means that.

The handler is thin, per CONVENTIONS.md > Tools: it translates between the model's
arguments and `clinical_query_service`, which is the only path to the data.
"""

from decimal import Decimal
from typing import Any

from app.llm.types import ToolDefinition, ToolOutput
from app.logging import get_logger
from app.services import clinical_query_service
from app.services.clinical_query_service import ClinicalAnswer
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)

DEFINITION = ToolDefinition(
    name="find_patients",
    # Prompt, not documentation: it says when to reach for this and — just as
    # important — what to do when a term does not resolve, because the failure
    # mode being designed against is the model guessing a threshold.
    description=(
        "Find patients matching clinical criteria in this hospital's records, or ask a "
        "question about a cohort: how many, what is the average, broken down by what. "
        "Pass the hospital's DEFINED CLINICAL TERMS in `terms` — never SQL, never a "
        "numeric threshold of your own. This hospital defines what terms like 'impaired "
        "renal function' mean, and those definitions are the authority, not your training. "
        "Leave `measures` and `group_by` empty for a plain list of matching patients. Fill "
        "`measures` (e.g. ['average eGFR']) to aggregate over the matching patients instead "
        "of listing them, and `group_by` (e.g. ['age band']) to break that aggregate down. "
        "If you are unsure which term fits, call this anyway with your best guess: any term "
        "that does not resolve comes back with the full list of defined terms, and you should "
        "then ASK THE USER which they meant rather than guessing again."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "The user's question, in their own words. Recorded in the audit log, "
                    "so copy it rather than paraphrasing."
                ),
            },
            "terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The defined FILTER terms this question refers to, e.g. "
                    "['impaired renal function', 'nephrotoxic medication']. Terms are "
                    "combined with AND. At least one is required — this tool always "
                    "narrows to a population before it lists or aggregates. Use the "
                    "hospital's wording where you know it; common synonyms are accepted."
                ),
            },
            "measures": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Defined MEASURE terms to aggregate over the matching patients, e.g. "
                    "['average eGFR']. Leave empty to get a plain list of patients instead."
                ),
            },
            "group_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Defined DIMENSION terms to group the measures by, e.g. ['age band']. "
                    "Only meaningful together with `measures`; ignored otherwise. A question "
                    "about drugs rather than patients — 'which nephrotoxins are most "
                    "prescribed' — is a `group_by` on a medication-entity dimension like "
                    "'nephrotoxic medication name', with `patient count` as the measure; "
                    "`terms` still narrows which patients' prescriptions count. Dimensions "
                    "cannot be mixed across entities in one call."
                ),
            },
            "columns": {
                "type": "array",
                "items": {"type": "string", "enum": ["patient_id", "age", "sex", "race", "state"]},
                "description": (
                    "Which columns to return for a plain patient list. Pass an empty array "
                    "for the default (patient_id, age, sex). Ignored when `measures` is set. "
                    "Patient names and dates of birth are never available — ask for `age` "
                    "instead of a date of birth."
                ),
            },
        },
        "required": ["question", "terms", "measures", "group_by", "columns"],
        "additionalProperties": False,
    },
)


async def run(tool_input: dict[str, Any], context: ToolContext) -> ToolOutput:
    asker = await clinical_query_service.build_asker(
        context.session, user_id=context.user_id, conversation_id=context.conversation_id
    )
    answer = await clinical_query_service.answer_question(
        context.session,
        asker,
        question=tool_input["question"],
        terms=tool_input["terms"],
        columns=tool_input["columns"] or None,
        measures=tool_input["measures"],
        group_by=tool_input["group_by"],
    )

    logger.info(
        "clinical query answered",
        outcome=answer.outcome,
        aggregate=answer.aggregate,
        row_count=answer.row_count,
        truncated=answer.truncated,
    )

    match answer.outcome:
        case "answered":
            return ToolOutput(content=_render_answer(answer), data=_answer_data(answer))
        case "clarification_requested":
            # NOT is_error. An error tells the model to fix itself and retry,
            # which here means guessing again. This is a result: the question
            # was genuinely ambiguous and a person has to resolve it.
            return ToolOutput(content=_render_clarification(answer))
        case "rejected":
            # is_error, because this one the model *can* fix — usually by
            # asking for `age` rather than a date of birth.
            return ToolOutput(content=f"Query refused. {answer.reason}", is_error=True)
        case _:
            return ToolOutput(
                content="The query could not be run against the clinical database.",
                is_error=True,
            )


def _render_answer(answer: ClinicalAnswer) -> str:
    """Rows, plus the definitions they were selected by.

    The definitions are not decoration. A clinician reading this needs to know
    that "impaired renal function" meant eGFR < 60 and why, or the list of
    patients is a number they have to take on trust.
    """
    lines: list[str] = []

    lines.append("Definitions applied:")
    for resolved in answer.resolved:
        lines.append(f"  - {resolved.term}: {resolved.description}")
        lines.append(f"    rationale: {resolved.notes}")
    lines.extend(f"  - measure {m.term}: {m.description}" for m in answer.resolved_measures)
    lines.extend(f"  - group by {d.term}: {d.description}" for d in answer.resolved_dimensions)

    lines.append("")
    if answer.aggregate:
        lines.append(f"{answer.row_count} group(s).")
    else:
        lines.append(f"{answer.row_count} matching patient(s).")
    if answer.truncated:
        lines.append(
            "This is a capped page, not the whole result — more patients match. "
            "Tell the user the list is truncated rather than implying it is complete."
        )
    lines.extend(
        f"{u.count} patient(s) could not be evaluated for {u.term!r} — no measurement on "
        "record. They are excluded from the count above, not counted as not meeting it; "
        "say so if it changes how the answer should be read."
        for u in answer.unmeasured
    )

    if answer.rows:
        lines.append("")
        lines.append(" | ".join(answer.columns))
        lines.extend(
            " | ".join(_cell(row.get(column)) for column in answer.columns) for row in answer.rows
        )

    lines.append("")
    lines.append("SQL executed:")
    lines.append(answer.executed_sql or "(none)")

    if answer.dataset is not None:
        lines.append("")
        lines.append(
            f"Dataset: {answer.dataset.source}, as of {answer.dataset.as_of_date.isoformat()}, "
            f"loaded {answer.dataset.loaded_at.isoformat()}."
        )
    return "\n".join(lines)


def _answer_data(answer: ClinicalAnswer) -> dict[str, Any]:
    """The structured half of an answered question, for the interface to render from.

    Every answer gets one, because the count and whether it was capped are what
    the result under a chat answer leads with — and without this, a patient
    list could not be told from a clarification without parsing the prose
    above. Only a clarification or a refusal has no data: no query ran.

    An aggregate also carries its rows, for a chart; a chart is derived from
    aggregate rows only, never authored by the model (SEMANTIC_LAYER.md § 4).
    A patient list does not: its rows are already in the text, and "show
    patients" re-asks for them with every returnable column.
    """
    data: dict[str, Any] = {
        "aggregate": answer.aggregate,
        "rowCount": answer.row_count,
        "truncated": answer.truncated,
    }
    if answer.aggregate:
        data |= {
            "columns": list(answer.columns),
            "rows": [{key: _json_safe(value) for key, value in row.items()} for row in answer.rows],
            "measures": [m.term for m in answer.resolved_measures],
            "groupBy": [d.term for d in answer.resolved_dimensions],
        }
    return data


def _json_safe(value: object) -> object:
    """`average eGFR`/`median creatinine` come back `Decimal` — Postgres NUMERIC
    via asyncpg — and this dict is about to go into a JSONB column and onto the
    wire as JSON, neither of which has a Decimal type. `json.dumps` raises on
    one buried in a nested dict, which is exactly where this one was: every row
    of a chartable aggregate answer, so any measure of this kind crashed the
    turn that produced it. Everything else here (str, int, bool, None) already
    round-trips through JSON unchanged.
    """
    return float(value) if isinstance(value, Decimal) else value


def _render_clarification(answer: ClinicalAnswer) -> str:
    lines = [
        "This question could not be resolved to defined clinical terms, so no query was run.",
        f"Unrecognised: {list(answer.unresolved)}",
        "",
        (
            "Do NOT guess a threshold or re-run with an invented term. Ask the user which "
            "of these defined terms they meant, in one short question:"
        ),
    ]
    lines.extend(
        f"  - {entry['term']} ({entry['kind']}): {entry['means']}" for entry in answer.vocabulary
    )
    return "\n".join(lines)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


FIND_PATIENTS = Tool(definition=DEFINITION, run=run)
