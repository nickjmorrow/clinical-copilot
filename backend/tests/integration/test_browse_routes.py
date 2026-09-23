"""The governed table browser, over real HTTP — SEMANTIC_LAYER.md § 3.

What this covers that `test_cohort_query_routes.py` does not: no `terms` are
required at all (the whole point — a curator paging through the raw dataset
has no question to resolve), pagination behaves, and the route is gated to
curator/auditor the same way the definitions editor's read side is.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DEV_USER_ID
from app.main import app
from app.services import authz_service

# The committed test fixture's own patient count — see
# tests/integration/conftest.py's module docstring.
FIXTURE_PATIENT_COUNT = 111


@pytest.fixture(autouse=True)
async def _restore_default_access(session):
    yield
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def test_no_filter_is_required_at_all(client):
    """The whole point of a browser over a drilldown: there is no question."""
    response = await client.get("/api/clinical/patients")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["outcome"] == "answered"
    assert body["total"] == FIXTURE_PATIENT_COUNT


async def test_a_page_cites_which_dataset_it_came_from(client):
    body = (await client.get("/api/clinical/patients")).json()["data"]
    assert body["dataset"] is not None
    assert "Synthea" in body["dataset"]["source"]


async def test_default_page_is_capped_at_fifty(client):
    body = (await client.get("/api/clinical/patients")).json()["data"]
    assert len(body["rows"]) == 50
    assert body["limit"] == 50
    assert body["offset"] == 0


async def test_paging_through_reaches_every_patient_exactly_once(client):
    seen: set[str] = set()
    offset = 0
    while True:
        body = (
            await client.get("/api/clinical/patients", params={"offset": offset, "limit": 50})
        ).json()["data"]
        if not body["rows"]:
            break
        for row in body["rows"]:
            assert row["patient_id"] not in seen, "the same patient appeared on two pages"
            seen.add(row["patient_id"])
        offset += 50

    assert len(seen) == FIXTURE_PATIENT_COUNT


async def test_a_limit_over_the_hard_cap_is_silently_capped(client):
    body = (await client.get("/api/clinical/patients", params={"limit": 10_000})).json()["data"]
    assert body["limit"] == 200
    assert len(body["rows"]) == FIXTURE_PATIENT_COUNT


async def test_specific_columns_can_be_requested(client):
    body = (
        await client.get(
            "/api/clinical/patients", params={"columns": ["patient_id", "state"], "limit": 1}
        )
    ).json()["data"]
    assert body["columns"] == ["patient_id", "state"]
    assert set(body["rows"][0]) == {"patient_id", "state"}


async def test_an_identifying_column_is_refused_with_no_rows(client):
    response = await client.get(
        "/api/clinical/patients", params={"columns": ["patient_id", "full_name"]}
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["outcome"] == "rejected"
    assert "full_name" in (body["reason"] or "")
    assert body["rows"] == []


async def test_nothing_is_persisted_by_browsing(client):
    await client.get("/api/clinical/patients")

    listed = (await client.get("/api/saved-questions")).json()["data"]
    assert listed == []


async def test_honours_the_callers_row_level_scope(client, session):
    unconfined = (await client.get("/api/clinical/patients")).json()["data"]
    assert unconfined["total"] == FIXTURE_PATIENT_COUNT

    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=list(authz_service.ROLES), scope_states=["Nowhere"]
    )

    confined = (await client.get("/api/clinical/patients")).json()["data"]
    assert confined["total"] == 0
    assert confined["rows"] == []


async def test_a_user_with_neither_curator_nor_auditor_is_refused(client, session):
    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=[authz_service.ANALYST], scope_states=None
    )

    response = await client.get("/api/clinical/patients")
    assert response.status_code == 403
