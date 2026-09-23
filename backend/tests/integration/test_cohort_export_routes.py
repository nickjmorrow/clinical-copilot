"""Cohort export, over real HTTP — SEMANTIC_LAYER.md § 18.

What this covers that `test_cohort_query_routes.py` does not: the response is
a CSV file, not JSON, so a rejection has nowhere to put an `outcome` field
and has to be a status code instead, and every audited query in this file
gets `via="export"` rather than `via="cohort"`.
"""

import csv
import io

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


def _rows(response) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(response.text)))


async def test_no_terms_is_refused(client):
    response = await client.post("/api/clinical/export", json={"terms": []})
    assert response.status_code == 422


async def test_a_restricted_column_is_refused_with_no_csv_body(client):
    response = await client.post(
        "/api/clinical/export",
        json={"columns": ["patient_id", "full_name"], "terms": ["impaired renal function"]},
    )
    assert response.status_code == 422
    assert "full_name" in response.json()["detail"]


async def test_downloads_a_csv_with_a_header_row_and_attachment_headers(client):
    response = await client.post(
        "/api/clinical/export", json={"terms": ["impaired renal function"]}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="cohort.csv"'

    rows = _rows(response)
    assert len(rows) == 22
    assert set(rows[0]) == {"patient_id", "age", "sex"}


async def test_every_returnable_column_when_asked_for(client):
    response = await client.post(
        "/api/clinical/export",
        json={
            "columns": ["patient_id", "age", "sex", "race", "state"],
            "terms": ["impaired renal function"],
        },
    )
    rows = _rows(response)
    assert set(rows[0]) == {"patient_id", "age", "sex", "race", "state"}


async def test_nothing_is_persisted(client):
    """Not a saved question — exporting must not create a row."""
    await client.post("/api/clinical/export", json={"terms": ["elderly"]})

    listed = (await client.get("/api/saved-questions")).json()["data"]
    assert listed == []


async def test_honours_the_callers_row_level_scope(client, session):
    unconfined = await client.post("/api/clinical/export", json={"terms": ["elderly"]})
    assert len(_rows(unconfined)) > 0

    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=list(authz_service.ROLES), scope_states=["Nowhere"]
    )

    confined = await client.post("/api/clinical/export", json={"terms": ["elderly"]})
    assert confined.status_code == 200
    assert _rows(confined) == []
