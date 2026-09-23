"""The unresolved-term report, over real HTTP — SEMANTIC_LAYER.md § 14.

What this covers that `test_audit_service.py` does not: the wire is
camelCase, and the route is gated to curator/auditor the same way the
definitions editor's read side is — an ordinary chat session has no reason to
see what other users' questions failed to resolve.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DEV_USER_ID
from app.main import app
from app.services import audit_service, authz_service
from app.services.audit_service import QueryAttempt


@pytest.fixture(autouse=True)
async def _restore_default_access(session):
    yield
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def test_the_seeded_dev_user_can_read_the_report(client):
    """dev-user is seeded with every role — this is the route working, not a
    permission bypass; the 403 case is its own test below."""
    response = await client.get("/api/audit/unresolved-terms")
    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_a_clarification_shows_up_camel_cased(client, session):
    await audit_service.record_query(
        session,
        QueryAttempt(
            asked_by="dr-who", raw_question="who has bad kidneys", outcome="clarification_requested"
        ),
    )

    body = (await client.get("/api/audit/unresolved-terms")).json()["data"]
    (entry,) = body
    assert entry["rawQuestion"] == "who has bad kidneys"
    assert entry["count"] == 1
    assert entry["askedBy"] == ["dr-who"]
    assert "lastAsked" in entry
    assert "raw_question" not in entry


async def test_an_answered_question_does_not_appear(client, session):
    await audit_service.record_query(
        session,
        QueryAttempt(asked_by="dr-who", raw_question="how many elderly?", outcome="answered"),
    )

    body = (await client.get("/api/audit/unresolved-terms")).json()["data"]
    assert body == []


async def test_a_user_with_neither_role_is_refused(client, session):
    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=[authz_service.ANALYST], scope_states=None
    )

    response = await client.get("/api/audit/unresolved-terms")
    assert response.status_code == 403
