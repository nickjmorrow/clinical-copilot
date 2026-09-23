"""How a provider refusal becomes a `StreamError` — the part a person reads.

No network: the SDK client is swapped for one whose `stream` raises the real
exception type, so what is under test is the adapter's `except` chain and
nothing else.
"""

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.config import settings
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.types import StreamError


def bad_request(message: str) -> anthropic.BadRequestError:
    # httpx2, not httpx: it is what the SDK is built on, and its exceptions
    # insist on its own Response type.
    response = httpx2.Response(
        400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    return anthropic.BadRequestError(message, response=response, body=None)


async def terminal_error(monkeypatch: pytest.MonkeyPatch, exc: anthropic.APIError) -> StreamError:
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    provider = AnthropicProvider()

    def stream(**_: Any) -> None:
        raise exc

    provider._client = SimpleNamespace(messages=SimpleNamespace(stream=stream))  # type: ignore[assignment]

    async def no_tools(_name: str, _input: dict[str, Any]) -> Any:
        raise AssertionError("no tool should run")

    events = [
        event
        async for event in provider.stream(system="", messages=[], tools=[], execute_tool=no_tools)
    ]
    assert len(events) == 1
    [event] = events
    assert isinstance(event, StreamError)
    return event


@pytest.mark.parametrize(
    "provider_message",
    [
        (
            "Your credit balance is too low to access the Anthropic API. "
            "Please go to Plans & Billing to upgrade or purchase credits."
        ),
        (
            "You have reached your specified API usage limits. "
            "You will regain access on 2026-10-01 at 00:00 UTC."
        ),
    ],
)
async def test_running_out_of_credit_says_so_in_plain_words(
    monkeypatch: pytest.MonkeyPatch, provider_message: str
):
    error = await terminal_error(monkeypatch, bad_request(provider_message))

    assert error.code == "out_of_credit"
    assert "run out of model credit" in error.message
    # The console's own wording is for whoever holds the key, not a visitor.
    assert "Plans & Billing" not in error.message


async def test_any_other_rejection_does_not_echo_the_provider(monkeypatch: pytest.MonkeyPatch):
    error = await terminal_error(
        monkeypatch, bad_request("messages.0.content: unexpected field `cache_hint`")
    )

    assert error.code == "bad_request"
    assert "cache_hint" not in error.message
