"""The conversation control endpoints, over real HTTP.

What these cover that the service tests do not is the boundary: that a patch
distinguishes "not sent" from "sent as null", that the wire is camelCase, and
that a conversation belonging to someone else is a 404 rather than a 403.
"""

import httpx
import pytest

from app.bus import bus
from app.main import app
from app.services import conversation_service


@pytest.fixture
async def client():
    await bus.start()
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        await bus.stop()


async def _create(client) -> str:
    response = await client.post("/api/conversations")
    assert response.status_code == 201
    return response.json()["data"]["id"]


async def test_a_new_conversation_is_neither_pinned_nor_archived(client):
    response = await client.post("/api/conversations")
    data = response.json()["data"]
    # camelCase on the wire, snake_case in Python — asserted rather than assumed,
    # because the alias generator is the only thing making it true.
    assert data["pinnedAt"] is None
    assert data["archivedAt"] is None


async def test_patch_renames_pins_and_archives(client):
    conversation_id = await _create(client)

    renamed = await client.patch(
        f"/api/conversations/{conversation_id}", json={"title": "  Taxes  "}
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["title"] == "Taxes"

    pinned = await client.patch(f"/api/conversations/{conversation_id}", json={"pinned": True})
    assert pinned.json()["data"]["pinnedAt"] is not None

    # Archiving unpins, and the response says so rather than making the client
    # refetch to find out.
    archived = await client.patch(f"/api/conversations/{conversation_id}", json={"archived": True})
    assert archived.json()["data"]["archivedAt"] is not None
    assert archived.json()["data"]["pinnedAt"] is None


async def test_a_field_left_out_of_the_patch_is_untouched(client):
    conversation_id = await _create(client)
    await client.patch(f"/api/conversations/{conversation_id}", json={"pinned": True})

    # The bug this guards: reading `body.pinned is None` instead of
    # `model_fields_set` makes this unpin, because an absent field and an
    # explicit null arrive identically.
    await client.patch(f"/api/conversations/{conversation_id}", json={"title": "Still Pinned"})

    response = await client.get("/api/conversations")
    listed = response.json()["data"][0]
    assert listed["title"] == "Still Pinned"
    assert listed["pinnedAt"] is not None


async def test_an_empty_title_is_rejected(client):
    conversation_id = await _create(client)
    response = await client.patch(f"/api/conversations/{conversation_id}", json={"title": "   "})
    assert response.status_code == 422


async def test_the_list_and_the_archive_are_two_lists(client):
    kept = await _create(client)
    filed = await _create(client)
    await client.patch(f"/api/conversations/{filed}", json={"archived": True})

    live = await client.get("/api/conversations")
    assert [c["id"] for c in live.json()["data"]] == [kept]

    archive = await client.get("/api/conversations", params={"archived": "true"})
    assert [c["id"] for c in archive.json()["data"]] == [filed]


async def test_sending_a_message_brings_an_archived_conversation_back(client):
    conversation_id = await _create(client)
    await client.patch(f"/api/conversations/{conversation_id}", json={"archived": True})

    sent = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": "hi"}
    )
    assert sent.status_code == 202

    live = await client.get("/api/conversations")
    assert [c["id"] for c in live.json()["data"]] == [conversation_id]


async def test_delete_removes_it_and_is_then_a_404(client):
    conversation_id = await _create(client)

    assert (await client.delete(f"/api/conversations/{conversation_id}")).status_code == 200
    assert (await client.get(f"/api/conversations/{conversation_id}")).status_code == 404
    assert (await client.delete(f"/api/conversations/{conversation_id}")).status_code == 404


async def test_someone_elses_conversation_is_not_there(client, session):
    theirs = await conversation_service.create_conversation(session, user_id="someone-else")

    # 404, not 403. A row you may not touch has to be indistinguishable from one
    # that does not exist, or the error message is an enumeration oracle.
    assert (
        await client.patch(f"/api/conversations/{theirs.id}", json={"pinned": True})
    ).status_code == 404
    assert (await client.delete(f"/api/conversations/{theirs.id}")).status_code == 404

    # And it is still there afterwards.
    assert await conversation_service.list_conversations(session, user_id="someone-else") != []
