"""Ad-hoc cohort queries, over real HTTP — SEMANTIC_LAYER.md § 3's cohort
drilldown.

What these cover that `test_saved_question_routes.py` does not: nothing is
persisted (no `saved_questions` row appears), `columns` is honoured (the
whole reason to reach for this over a saved question's run), and a run still
goes through the real column allowlist and row-level scope.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DEV_USER_ID
from app.main import app
from app.services import authz_service


@pytest.fixture(autouse=True)
async def _restore_default_access(session):
    yield
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def test_no_terms_is_refused(client):
    response = await client.post("/api/clinical/query", json={"terms": []})
    assert response.status_code == 422


async def test_default_columns_when_none_are_given(client):
    response = await client.post("/api/clinical/query", json={"terms": ["impaired renal function"]})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["outcome"] == "answered"
    assert body["rowCount"] == 22
    assert body["columns"] == ["patient_id", "age", "sex"]


async def test_every_returnable_column_when_asked_for(client):
    """The whole point of this route over a saved question's run: columns a
    saved question does not carry."""
    response = await client.post(
        "/api/clinical/query",
        json={
            "columns": ["patient_id", "age", "sex", "race", "state"],
            "terms": ["impaired renal function"],
        },
    )
    body = response.json()["data"]
    assert body["columns"] == ["patient_id", "age", "sex", "race", "state"]
    assert body["rows"]
    assert set(body["rows"][0]) == {"patient_id", "age", "sex", "race", "state"}


async def test_the_answer_cites_which_dataset_it_ran_against(client):
    body = (
        await client.post("/api/clinical/query", json={"terms": ["impaired renal function"]})
    ).json()["data"]
    assert body["dataset"] is not None
    assert "Synthea" in body["dataset"]["source"]


async def test_a_restricted_column_is_refused(client):
    response = await client.post(
        "/api/clinical/query",
        json={"columns": ["patient_id", "full_name"], "terms": ["impaired renal function"]},
    )
    body = response.json()["data"]
    assert body["outcome"] == "rejected"
    assert "full_name" in (body["reason"] or "")


async def test_nothing_is_persisted(client):
    """Not a saved question — running this twice must not create a row."""
    await client.post("/api/clinical/query", json={"terms": ["elderly"]})
    await client.post("/api/clinical/query", json={"terms": ["elderly"]})

    listed = (await client.get("/api/saved-questions")).json()["data"]
    assert listed == []


async def test_honours_the_callers_row_level_scope(client, session):
    unconfined = await client.post("/api/clinical/query", json={"terms": ["elderly"]})
    assert unconfined.json()["data"]["rowCount"] > 0

    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=list(authz_service.ROLES), scope_states=["Nowhere"]
    )

    confined = await client.post("/api/clinical/query", json={"terms": ["elderly"]})
    assert confined.json()["data"]["rowCount"] == 0
