"""The endpoint behind the "what can I ask" panel.

It exists so a reader can see the vocabulary without spending a model call,
and so the panel and the prompt cannot disagree — both read the same rows.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.support.fixture import RUNNING_EXAMPLE_CORE


@pytest.fixture
async def client(session):
    transport = ASGITransport(app=app)
    async with AsyncClient(base_url="http://test", transport=transport) as client:
        yield client


async def test_every_defined_term_is_listed(client, session):
    response = await client.get("/api/clinical/context")
    assert response.status_code == 200

    terms = response.json()["data"]["terms"]
    assert {t["term"] for t in terms} >= {
        "elderly",
        "impaired renal function",
        "nephrotoxic medication",
        "renin-angiotensin blocker",
    }


async def test_each_term_carries_its_justification(client):
    """A threshold a reader cannot interrogate is one they must take on trust."""
    terms = (await client.get("/api/clinical/context")).json()["data"]["terms"]
    for term in terms:
        assert term["why"].strip(), term["term"]
        assert term["means"].strip(), term["term"]


async def test_the_predicate_is_never_sent_to_the_client(client):
    """`logic` is the assembler's business.

    Rendering a predicate invites a reader — or a model reading over their
    shoulder — to reason about the number instead of the name, which is the
    failure the definitions layer exists to prevent.
    """
    body = (await client.get("/api/clinical/context")).text
    assert "lab_threshold" not in body
    assert "most_recent" not in body
    assert "logic" not in body


async def test_the_dataset_shape_is_reported(client):
    dataset = (await client.get("/api/clinical/context")).json()["data"]["dataset"]

    assert dataset["patients"] == 111
    assert dataset["medications"] == 149
    assert dataset["prescriptions"] == 5835
    assert dataset["observations"] == 79508
    codes = {entry["code"] for entry in dataset["observationCatalog"]}
    assert "33914-3" in codes  # eGFR
    assert sorted(dataset["annotationValues"]["nephrotoxic_risk"]) == [
        "contextual",
        "high",
        "moderate",
    ]


async def test_the_panel_reports_where_and_when_the_data_is_from(client):
    """SEMANTIC_LAYER.md § 1: every age is relative to `as_of_date`, and that
    is silently wrong to a reader who cannot see it."""
    dataset = (await client.get("/api/clinical/context")).json()["data"]["dataset"]

    assert dataset["dataset"]["asOfDate"] == "2026-09-20"
    assert dataset["dataset"]["patientCount"] == 111


async def test_the_panel_says_which_columns_are_withheld(client):
    """The restriction is worth showing, not hiding.

    A reader who knows names are unavailable asks a different question; one who
    does not assumes the tool is broken.
    """
    dataset = (await client.get("/api/clinical/context")).json()["data"]["dataset"]

    assert dataset["returnableColumns"] == ["patient_id", "age", "sex", "race", "state"]
    assert set(dataset["restrictedColumns"]) == {
        "full_name",
        "birth_date",
        "ssn",
        "drivers",
        "passport",
        "address",
    }


async def test_no_patient_row_is_reachable_through_this_endpoint(client):
    """The catalog counts; it does not enumerate."""
    body = (await client.get("/api/clinical/context")).text
    assert RUNNING_EXAMPLE_CORE not in body
