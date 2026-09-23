"""The column allowlist, and the per-role policy over its identifying
tier — SEMANTIC_LAYER.md § 19.

`ROLE_IDENTIFYING_COLUMNS` grants nothing to any role today, on purpose (see
its own comment in `app/clinical/columns.py`), so most of what is worth
testing is the *mechanism* — that a role granted a column gets it, that a
caller with no roles is denied exactly like the old `allow_identifying=False`
default always denied everyone, and that the semantic-binding check (an
unknown name) does not care about roles at all. `monkeypatch` stands in for a
real grant the same way it does for `MAX_ROWS` in the integration suite.
"""

from datetime import date

import pytest

from app.clinical import columns
from app.clinical.columns import ColumnAccessError, permitted_identifying_columns, resolve_columns

TODAY = date(2026, 1, 1)


def test_no_roles_denies_every_identifying_column():
    with pytest.raises(ColumnAccessError) as excinfo:
        resolve_columns(["patient_id", "full_name"], today=TODAY)
    assert excinfo.value.denied == ("full_name",)


def test_a_role_with_no_grant_still_denies():
    with pytest.raises(ColumnAccessError):
        resolve_columns(["full_name"], today=TODAY, roles=["analyst"])


def test_a_granted_role_is_permitted_its_column(monkeypatch):
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "auditor", ("full_name",))

    _selected, names = resolve_columns(["patient_id", "full_name"], today=TODAY, roles=["auditor"])
    assert names == ("patient_id", "full_name")


def test_a_grant_on_one_role_does_not_leak_to_another(monkeypatch):
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "auditor", ("full_name",))

    with pytest.raises(ColumnAccessError):
        resolve_columns(["full_name"], today=TODAY, roles=["analyst"])


def test_holding_two_roles_is_the_union_not_the_intersection(monkeypatch):
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "auditor", ("full_name",))
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "curator", ("birth_date",))

    _selected, names = resolve_columns(
        ["full_name", "birth_date"], today=TODAY, roles=["auditor", "curator"]
    )
    assert names == ("full_name", "birth_date")


def test_an_unknown_column_is_refused_regardless_of_role(monkeypatch):
    """The semantic-binding check runs first and does not consult roles at
    all — a role cannot grant access to a column that was never on the
    allowlist to begin with."""
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "auditor", ("full_name",))

    with pytest.raises(ColumnAccessError, match="no such column"):
        resolve_columns(["diagnosis"], today=TODAY, roles=["auditor"])


def test_permitted_identifying_columns_is_the_union_across_roles(monkeypatch):
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "auditor", ("full_name", "ssn"))
    monkeypatch.setitem(columns.ROLE_IDENTIFYING_COLUMNS, "curator", ("birth_date",))

    assert permitted_identifying_columns(["auditor", "curator"]) == {
        "full_name",
        "ssn",
        "birth_date",
    }


def test_permitted_identifying_columns_is_empty_for_no_roles():
    assert permitted_identifying_columns([]) == frozenset()
