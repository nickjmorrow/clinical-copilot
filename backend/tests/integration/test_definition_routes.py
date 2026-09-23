"""The definitions routes, over real HTTP: who may read and write them, and the
impact preview a curator runs before saving.

Reading is open to everyone and writing is curator-only — see the module
docstring of `app/api/routes/definitions.py` for why that line sits where it
does.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import DEV_USER_ID
from app.main import app
from app.services import authz_service

OVER_65 = {"type": "age_threshold", "operator": ">=", "value": 65}


@pytest.fixture(autouse=True)
async def _restore_default_access(session):
    yield
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def _as_analyst_only(session) -> None:
    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=[authz_service.ANALYST], scope_states=None
    )


async def test_anyone_may_read_the_definitions_and_the_model_check(client, session):
    await _as_analyst_only(session)

    listed = await client.get("/api/clinical/definitions")
    assert listed.status_code == 200
    first = listed.json()["data"][0]
    # The read side shows `logic` — the point of opening it up.
    assert "logic" in first

    history = await client.get(f"/api/clinical/definitions/{first['id']}/history")
    assert history.status_code == 200

    check = await client.get("/api/clinical/model/check")
    assert check.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/clinical/definitions"),
        ("POST", "/api/clinical/definitions/preview"),
    ],
)
async def test_writing_and_previewing_need_the_curator_role(client, session, method, path):
    await _as_analyst_only(session)

    response = await client.request(method, path, json={"kind": "filter", "logic": OVER_65})

    assert response.status_code == 403


async def test_a_filter_preview_counts_patients(client):
    response = await client.post(
        "/api/clinical/definitions/preview", json={"kind": "filter", "logic": OVER_65}
    )

    assert response.status_code == 200
    assert response.json()["data"]["patientCount"] > 0


async def test_a_preview_counts_only_within_the_curators_scope(client, session):
    """It used to build its query context from the user id alone, which drops
    scope — so a curator confined to one state saw a count across all of them."""
    await authz_service.set_roles(
        session, user_id=DEV_USER_ID, roles=list(authz_service.ROLES), scope_states=["Nowhere"]
    )

    response = await client.post(
        "/api/clinical/definitions/preview", json={"kind": "filter", "logic": OVER_65}
    )

    assert response.json()["data"]["patientCount"] == 0


async def test_a_measure_preview_checks_the_shape_and_counts_nothing(client):
    good = await client.post(
        "/api/clinical/definitions/preview",
        json={"kind": "measure", "logic": {"type": "patient_count"}},
    )
    bad = await client.post(
        "/api/clinical/definitions/preview",
        json={"kind": "measure", "logic": {"type": "no_such_measure"}},
    )

    assert good.status_code == 200
    assert good.json()["data"]["patientCount"] is None
    assert bad.status_code == 422


async def test_logic_that_does_not_parse_is_a_422_with_the_reason(client):
    response = await client.post(
        "/api/clinical/definitions/preview",
        json={"kind": "filter", "logic": {"type": "sql", "text": "1=1"}},
    )

    assert response.status_code == 422
    assert response.json()["detail"]
