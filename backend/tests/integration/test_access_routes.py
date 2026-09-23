"""Row-level access, over real HTTP — SEMANTIC_LAYER.md § 19.

`GET`/`PUT /access/me` are self-service only: there is no user id anywhere in
either request, so "edit someone else's scope" is not expressible through
this surface at all, and that is the property worth testing rather than
assuming from reading the route.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DEV_USER_ID
from app.main import app
from app.services import authz_service


# `user_roles` is part of the clinical dataset loaded once per session (see
# tests/integration/conftest.py) rather than truncated between tests, so
# every test here that changes `dev-user`'s scope restores it afterward
# instead of relying on a per-test reset that no longer happens.
@pytest.fixture(autouse=True)
async def _restore_default_access(session):
    yield
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def test_the_seeded_dev_user_is_unconfined_with_every_role(client):
    response = await client.get("/api/access/me")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["userId"] == DEV_USER_ID
    assert sorted(body["roles"]) == sorted(authz_service.ROLES)
    assert body["scopeStates"] is None


async def test_available_states_come_from_the_loaded_data(client):
    """Not a hardcoded list of fifty — whatever the fixture actually has."""
    body = (await client.get("/api/access/me")).json()["data"]
    assert body["availableStates"] == sorted(set(body["availableStates"]))
    assert all(isinstance(state, str) and state for state in body["availableStates"])


async def test_setting_a_scope_persists_and_is_read_back(client, session):
    """That a scope set here actually *confines* a query is the claim
    `test_saved_question_routes.py::test_running_honours_the_callers_row_level_scope`
    makes end to end, through a real endpoint. This test is the narrower one:
    the write landed, in the same row `authz_service.get_scope_states` reads
    for every other query path."""
    put = await client.put("/api/access/me", json={"scopeStates": ["Nowhere"]})
    assert put.status_code == 200
    assert put.json()["data"]["scopeStates"] == ["Nowhere"]

    scope_states = await authz_service.get_scope_states(session, user_id=DEV_USER_ID)
    assert scope_states == ["Nowhere"]


async def test_clearing_the_scope_sets_it_back_to_unconfined(client):
    await client.put("/api/access/me", json={"scopeStates": ["Nowhere"]})

    cleared = await client.put("/api/access/me", json={"scopeStates": None})
    assert cleared.json()["data"]["scopeStates"] is None


async def test_roles_are_untouched_by_updating_the_scope(client):
    before = (await client.get("/api/access/me")).json()["data"]["roles"]

    await client.put("/api/access/me", json={"scopeStates": ["Nowhere"]})

    after = (await client.get("/api/access/me")).json()["data"]["roles"]
    assert sorted(after) == sorted(before)
