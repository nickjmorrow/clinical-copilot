"""Saved questions, over real HTTP — SEMANTIC_LAYER.md § 17.

What these cover that a service-level test would not: the wire is camelCase,
running a saved question goes through the real definitions layer rather than
replaying stored rows, and a run honors row-level scope exactly like a chat
turn would.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DEV_USER_ID
from app.main import app
from app.services import authz_service, saved_question_service


# `user_roles` is part of the clinical dataset loaded once per session (see
# tests/integration/conftest.py) rather than truncated between tests, so the
# one test here that changes `dev-user`'s scope restores it afterward.
@pytest.fixture(autouse=True)
async def _restore_default_access(session):
    yield
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def _create(client, **overrides) -> str:
    body = {"groupBy": [], "measures": [], "name": "impaired renal function", "terms": []}
    body.update(overrides)
    response = await client.post("/api/saved-questions", json=body)
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def test_creating_with_no_terms_is_refused(client):
    response = await client.post(
        "/api/saved-questions", json={"groupBy": [], "measures": [], "name": "x", "terms": []}
    )
    assert response.status_code == 422


async def test_a_created_question_is_listed_camel_cased(client):
    question_id = await _create(client, terms=["impaired renal function"])

    listed = (await client.get("/api/saved-questions")).json()["data"]
    (entry,) = [q for q in listed if q["id"] == question_id]
    assert entry["terms"] == ["impaired renal function"]
    assert entry["groupBy"] == []
    assert "created_at" not in entry
    assert "createdAt" in entry


async def test_deleting_removes_it_from_the_list(client):
    question_id = await _create(client, terms=["elderly"])

    response = await client.delete(f"/api/saved-questions/{question_id}")
    assert response.status_code == 200

    listed = (await client.get("/api/saved-questions")).json()["data"]
    assert question_id not in {q["id"] for q in listed}


async def test_running_a_missing_question_is_404(client):
    response = await client.post("/api/saved-questions/00000000-0000-0000-0000-000000000000/run")
    assert response.status_code == 404


async def test_running_resolves_fresh_against_the_real_data(client):
    """Not a replay of a stored answer — a saved question re-asks the
    definitions layer every time, so an edited threshold is picked up. The
    real fixture count for `impaired renal function` alone is 22 — see
    tests/support/eval_cases.py — asserted here rather than trusted, because a
    stale cached count would pass a test that only checked the outcome."""
    question_id = await _create(client, terms=["impaired renal function"])

    response = await client.post(f"/api/saved-questions/{question_id}/run")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["outcome"] == "answered"
    assert body["aggregate"] is False
    assert body["rowCount"] == 22
    assert body["resolvedTerms"][0]["term"] == "impaired renal function"


async def test_running_an_aggregate_question_returns_json_numbers_not_strings(client):
    """Regression case for the Decimal-as-string bug found while wiring this
    route up — see `_json_safe` in `app/api/schemas.py`."""
    question_id = await _create(
        client, group_by=["age band"], measures=["average eGFR"], terms=["impaired renal function"]
    )

    response = await client.post(f"/api/saved-questions/{question_id}/run")
    body = response.json()["data"]
    assert body["aggregate"] is True
    assert body["rows"]
    for row in body["rows"]:
        assert isinstance(row["average eGFR"], float)


async def test_running_honours_the_callers_row_level_scope(client, session):
    """The same guardrail a chat turn gets. Confining to a state nobody in the
    fixture has must return nobody — not an error, not the unconfined count."""
    question_id = await _create(client, terms=["elderly"])

    unconfined = (await client.post(f"/api/saved-questions/{question_id}/run")).json()["data"]
    assert unconfined["rowCount"] > 0

    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=list(authz_service.ROLES), scope_states=["Nowhere"]
    )

    confined = (await client.post(f"/api/saved-questions/{question_id}/run")).json()["data"]
    assert confined["rowCount"] == 0


async def test_someone_elses_saved_question_is_not_there(client, session):
    """The same discipline `test_conversation_routes.py` pins for conversations:
    a row belonging to another user is a 404, not a 403 — indistinguishable
    from one that does not exist, so the error can't be used to enumerate
    other users' saved questions."""
    theirs = await saved_question_service.create_saved_question(
        session, user_id="someone-else", name="theirs", terms=["elderly"]
    )

    assert (await client.post(f"/api/saved-questions/{theirs.id}/run")).status_code == 404
    assert (await client.delete(f"/api/saved-questions/{theirs.id}")).status_code == 200

    # The delete above is a no-op against another user's row, not a real
    # delete: it still exists afterward.
    assert (
        await saved_question_service.get_saved_question(
            session, user_id="someone-else", question_id=theirs.id
        )
        is not None
    )

    # And it never showed up in the caller's own list either.
    listed = (await client.get("/api/saved-questions")).json()["data"]
    assert theirs.id not in {uuid.UUID(q["id"]) for q in listed}
