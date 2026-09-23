"""The streaming endpoint's replay half.

Resuming is not a special case here — it is the only case, used identically by
a browser that just sent a message and one that refreshed mid-answer. The
cursor arithmetic is where an off-by-one would live, and an off-by-one shows up
as a duplicated or a silently missing message.

Only the replay path is exercised through HTTP. The live tail deliberately does
not terminate until a terminal status is published, and httpx's ASGITransport
runs the app to completion before returning — so testing the tail this way
hangs rather than fails. It is covered separately against the bus.
"""

import httpx
import pytest

from app.bus import bus
from app.main import app
from app.services import conversation_service, task_service, transcript_service


@pytest.fixture
async def client():
    # The bus is started by hand rather than by running the app's lifespan,
    # which would also try to apply migrations. The streaming endpoint really
    # does need it — it subscribes before replaying — so this is the honest
    # minimum rather than a shortcut.
    await bus.start()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        await bus.stop()


def frames(body: str) -> list[dict]:
    import json

    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


async def test_replay_returns_only_what_comes_after_the_cursor(session, client):
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    await transcript_service.add_user_message(session, conversation=conversation, text="one")
    await transcript_service.add_assistant_message(
        session, conversation_id=conversation.id, text="two"
    )
    await transcript_service.add_tool_call(
        session,
        conversation_id=conversation.id,
        tool_use_id="toolu_1",
        name="find_patients",
        tool_input={"question": "who?", "terms": ["elderly"], "columns": []},
    )

    response = await client.get(f"/api/conversations/{conversation.id}/stream?since=1")
    assert response.status_code == 200

    received = frames(response.text)
    events = [f for f in received if f["type"] == "event"]
    assert [e["event"]["type"] for e in events] == ["assistant_message", "tool_call"]
    assert [e["event"]["seq"] for e in events] == [2, 3]

    # Nothing is running, so the endpoint says so and hangs up rather than
    # holding a connection open forever.
    assert received[-1] == {"type": "status", "taskId": None, "status": "idle"}


async def test_replay_omits_the_empty_assistant_row(session, client):
    """It exists for its token counts; there is no bubble to draw."""
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    await transcript_service.add_assistant_message(
        session, conversation_id=conversation.id, text="", input_tokens=10, output_tokens=2
    )

    response = await client.get(f"/api/conversations/{conversation.id}/stream?since=0")
    assert [f for f in frames(response.text) if f["type"] == "event"] == []


async def test_a_running_task_is_reported_so_a_reloaded_page_reattaches(session, client):
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    task = await task_service.enqueue(session, kind="chat_turn", conversation_id=conversation.id)

    detail = await client.get(f"/api/conversations/{conversation.id}")
    assert detail.json()["data"]["activeTask"]["id"] == str(task.id)


async def test_another_users_conversation_is_indistinguishable_from_a_missing_one(
    session, client, monkeypatch
):
    """Authorization is in the WHERE clause, and 404 rather than 403.

    Checked before the first byte, because once a stream opens the status code
    is already spent. Cheap now; a security bug the day real auth lands.
    """
    conversation = await conversation_service.create_conversation(session, user_id="someone-else")

    for path in (
        f"/api/conversations/{conversation.id}",
        f"/api/conversations/{conversation.id}/stream?since=0",
    ):
        assert (await client.get(path)).status_code == 404

    response = await client.post(
        f"/api/conversations/{conversation.id}/messages", json={"content": "hello"}
    )
    assert response.status_code == 404


async def test_an_over_long_message_is_rejected_before_it_costs_anything(session, client):
    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    response = await client.post(
        f"/api/conversations/{conversation.id}/messages",
        json={"content": "x" * 20_001},
    )
    assert response.status_code == 422


async def test_every_response_carries_a_request_id(client):
    """Bound into structlog contextvars, echoed back, and honoured if supplied.

    The id is what ties an API log line to the worker log line for the same
    turn — two processes that share no memory and no log stream.
    """
    response = await client.get("/api/health")
    assert response.headers["x-request-id"]

    supplied = "abc123fromupstream"
    response = await client.get("/api/health", headers={"x-request-id": supplied})
    assert response.headers["x-request-id"] == supplied


async def test_an_enqueued_turn_records_the_request_that_asked_for_it(session, client):
    from app.services import task_service

    conversation = await conversation_service.create_conversation(session, user_id="dev-user")
    response = await client.post(
        f"/api/conversations/{conversation.id}/messages",
        json={"content": "hello"},
        headers={"x-request-id": "traceme123"},
    )
    assert response.status_code == 202

    task = await task_service.active_task(session, conversation_id=conversation.id)
    assert task is not None
    assert task.request_id == "traceme123"
