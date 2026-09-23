"""The stochastic half of the golden dataset: does the model pick the right terms?

Everything downstream of term selection is already proved deterministically in
`tests/integration/test_eval.py`. What is left — and what cannot be tested
without spending money — is the one judgement the model is actually trusted
with.

These assert on the TERMS the model chose, not on the prose it wrote. Prose
varies run to run and asserting on it produces a suite that fails for reasons
nobody cares about; the term list is the decision, and it is either right or it
is not.

`live_refuses_to_invent_a_threshold` is the important one. Asked for "eGFR
below 45" — a number this hospital does not define — the model must decline
rather than reach for the nearest defined term. That is the single behaviour
the whole definitions layer exists to produce, and no hermetic test can observe
it.
"""

import pytest

from app import tools
from app.config import settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.types import ChatMessage, TextBlock, ToolCall
from app.services import definition_service, seed_service
from app.tools.base import ToolContext
from tests.support.eval_cases import LIVE_CASES, EvalCase
from tests.support.fixture import FIXTURE_SOURCE


@pytest.fixture
async def seeded(session):
    await seed_service.seed_all(session, source=FIXTURE_SOURCE, reset=True)
    return session


async def _terms_the_model_chose(session, question: str) -> tuple[list[str], list[str]]:
    """Run one real turn and report which tools it called, with which terms."""
    context = ToolContext(session=session, user_id="live-eval")
    provider = AnthropicProvider()

    chosen: list[str] = []
    called: list[str] = []

    async def record_and_run(name: str, tool_input: dict) -> object:
        called.append(name)
        chosen.extend(tool_input.get("terms", []))
        return await tools.execute(name, tool_input, context)

    system = await definition_service.with_vocabulary(session, base=settings.system_prompt)
    stream = provider.stream(
        system=system,
        messages=[ChatMessage(role="user", content=[TextBlock(text=question)])],
        tools=tools.definitions(),
        execute_tool=record_and_run,  # type: ignore[arg-type]
    )

    try:
        async for event in stream:
            if isinstance(event, ToolCall):
                continue
    finally:
        await stream.aclose()

    return called, chosen


@pytest.mark.parametrize("case", LIVE_CASES, ids=lambda c: c.id)
async def test_the_model_picks_the_defined_terms(case: EvalCase, seeded):
    called, chosen = await _terms_the_model_chose(seeded, case.question)

    if not case.terms:
        # The case expects the model NOT to query — there is no defined term
        # for what was asked, and inventing one is the failure.
        assert "find_patients" not in called or not chosen, (
            f"{case.id}: the model queried when it should have asked.\n"
            f"  pins: {case.pins}\n  it chose: {chosen}"
        )
        return

    normalised = {term.lower() for term in chosen}
    expected = {term.lower() for term in case.terms}

    assert expected <= normalised, (
        f"{case.id}: the model did not choose the expected terms.\n"
        f"  question: {case.question}\n"
        f"  pins: {case.pins}\n"
        f"  expected at least: {sorted(expected)}\n"
        f"  it chose: {sorted(normalised)}"
    )
