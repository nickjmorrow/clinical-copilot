"""Public mode: an identity per browser, and the ceilings on what it costs.

Everything here runs through the real app over ASGI — the middleware that
mints the cookie, the auth seam that reads it, the role checks, the send
route that enforces the limits. Separate `httpx` clients are separate
browsers, each with its own cookie jar.
"""

import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.bus import bus
from app.config import settings
from app.main import app
from app.models import UsageEvent


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(settings, "visitor_mode", True)
    # httpx, like a browser, will not send a Secure cookie to plain-http
    # `testserver`. The flag itself is asserted on the header below.
    monkeypatch.setattr(settings, "visitor_cookie_secure", False)


@pytest.fixture
async def browsers() -> AsyncIterator[Callable[[], httpx.AsyncClient]]:
    await bus.start()
    transport = httpx.ASGITransport(app=app)
    opened: list[httpx.AsyncClient] = []

    def new_browser() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        opened.append(client)
        return client

    try:
        yield new_browser
    finally:
        for client in opened:
            await client.aclose()
        await bus.stop()


async def _whoami(browser: httpx.AsyncClient) -> dict[str, Any]:
    response = await browser.get("/api/access/me")
    assert response.status_code == 200
    return response.json()["data"]


async def _new_conversation(browser: httpx.AsyncClient) -> str:
    response = await browser.post("/api/conversations")
    assert response.status_code == 201
    return response.json()["data"]["id"]


async def _send(browser: httpx.AsyncClient, conversation_id: str, text: str) -> httpx.Response:
    return await browser.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": text}
    )


# --- identity -----------------------------------------------------------------


async def test_off_by_default_every_request_is_still_the_dev_user(browsers):
    response = await browsers().get("/api/access/me")

    assert "set-cookie" not in response.headers
    assert response.json()["data"]["userId"] == "dev-user"


async def test_a_first_visit_gets_its_own_identity_in_a_locked_down_cookie(
    public, browsers, monkeypatch
):
    monkeypatch.setattr(settings, "visitor_cookie_secure", True)

    response = await browsers().get("/api/access/me")

    cookie = response.headers["set-cookie"]
    assert re.match(r"visitor=[A-Za-z0-9_-]{32};", cookie)
    for flag in ("HttpOnly", "SameSite=Lax", "Secure", "Path=/"):
        assert flag in cookie
    me = response.json()["data"]
    assert me["userId"].startswith("visitor:")
    # A visitor holds no roles: default-deny, the state a user with no row has.
    assert me["roles"] == []


async def test_a_returning_visitor_keeps_its_identity(public, browsers):
    browser = browsers()
    first = await _whoami(browser)

    again = await browser.get("/api/access/me")

    assert "set-cookie" not in again.headers
    assert again.json()["data"]["userId"] == first["userId"]


async def test_visitors_cannot_see_or_touch_each_others_conversations(public, browsers):
    alice, bob = browsers(), browsers()
    await _whoami(alice)
    await _whoami(bob)

    mine = await _new_conversation(alice)

    listed = (await alice.get("/api/conversations")).json()["data"]
    assert [one["id"] for one in listed] == [mine]
    assert (await bob.get("/api/conversations")).json()["data"] == []
    # Indistinguishable from not existing, per AGENTS.md > Authorization.
    assert (await bob.get(f"/api/conversations/{mine}")).status_code == 404
    assert (await bob.delete(f"/api/conversations/{mine}")).status_code == 404


async def test_a_forged_cookie_cannot_choose_its_identity(public, browsers):
    browser = browsers()
    browser.cookies.set("visitor", "dev-user")

    response = await browser.get("/api/access/me")

    assert "set-cookie" in response.headers
    assert response.json()["data"]["userId"].startswith("visitor:")


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/api/clinical/definitions/preview", {"kind": "filter", "logic": {}}),
        ("GET", "/api/audit/unresolved-terms", None),
        ("GET", "/api/clinical/patients", None),
        ("PUT", "/api/access/me", {"scopeStates": ["Massachusetts"]}),
        ("POST", "/api/schedules", {"name": "x", "prompt": "hi", "intervalSeconds": 3600}),
    ],
)
async def test_a_visitor_has_none_of_the_curator_or_auditor_surfaces(
    public, browsers, method, path, body
):
    """Editing the model, other people's questions, the raw table, and the one
    request that keeps spending after its author has gone."""
    response = await browsers().request(method, path, json=body)

    assert response.status_code == 403


async def test_a_visitor_can_read_the_definitions_but_not_change_them(public, browsers):
    """The vocabulary every answer rests on is the thing this demo exists to
    show, so a visitor may read it — logic, history and model check included —
    and may not write a word of it."""
    browser = browsers()

    listed = await browser.get("/api/clinical/definitions")
    created = await browser.post(
        "/api/clinical/definitions",
        json={"term": "x", "kind": "filter", "logic": {}, "changeReason": "x"},
    )

    assert listed.status_code == 200
    assert listed.json()["data"]
    assert created.status_code == 403


# --- cost ceilings ------------------------------------------------------------


async def test_the_hourly_limit_survives_deleting_the_conversation(public, browsers, monkeypatch):
    monkeypatch.setattr(settings, "messages_per_hour", 2)
    alice, bob = browsers(), browsers()
    await _whoami(alice)
    await _whoami(bob)

    first = await _new_conversation(alice)
    for text in ("one", "two"):
        assert (await _send(alice, first, text)).status_code == 202
    assert (await alice.delete(f"/api/conversations/{first}")).status_code == 200

    second = await _new_conversation(alice)
    refused = await _send(alice, second, "three")

    assert refused.status_code == 429
    assert "2 messages in the last hour" in refused.json()["detail"]
    # Refused before anything was written.
    assert (await alice.get(f"/api/conversations/{second}")).json()["data"]["events"] == []
    # Per visitor: somebody else is unaffected.
    assert (await _send(bob, await _new_conversation(bob), "hello")).status_code == 202


async def test_the_daily_budget_counts_everyone_since_midnight_utc(
    public, browsers, session, monkeypatch
):
    monkeypatch.setattr(settings, "daily_token_budget", 1_000)
    browser = browsers()
    await _whoami(browser)
    conversation = await _new_conversation(browser)

    # Yesterday's spending does not count against today.
    session.add(
        UsageEvent(
            user_id="someone-else",
            kind="tokens",
            amount=50_000,
            created_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await session.commit()
    assert (await _send(browser, conversation, "first")).status_code == 202

    # Anyone's spending today does.
    session.add(UsageEvent(user_id="someone-else", kind="tokens", amount=1_000))
    await session.commit()
    refused = await _send(browser, conversation, "second")

    assert refused.status_code == 429
    assert "today's budget" in refused.json()["detail"]
