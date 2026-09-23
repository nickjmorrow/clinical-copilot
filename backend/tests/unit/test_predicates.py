"""The validator, which is the gate between a database row and executed SQL.

Mostly rejection cases. The accepting path is exercised by every other test in
the suite; what needs its own coverage is everything this module refuses,
because each refusal is a query that would otherwise have run and returned a
plausible, wrong answer.
"""

from decimal import Decimal

import pytest

from app.clinical.predicates import (
    AgeBand,
    AgeThreshold,
    AllOf,
    InvalidPredicateError,
    MedicationAttribute,
    MedicationGroup,
    Not,
    ObservationAggregate,
    ObservationThreshold,
    PatientColumn,
    PatientCount,
    Resolved,
    TermReference,
    VitalStatus,
    observation_codes,
    parse_dimension,
    parse_measure,
    parse_predicate,
    references,
    substitute,
)

EGFR = {"type": "observation_threshold", "codes": ["33914-3"], "units": ["mL/min"]}


def test_an_observation_threshold_round_trips():
    predicate = parse_predicate({**EGFR, "operator": "<", "value": 60})
    assert predicate == ObservationThreshold(
        codes=("33914-3",), units=("mL/min",), operator="<", value=Decimal(60), most_recent=True
    )


def test_most_recent_defaults_to_true():
    """'Their eGFR is low' and 'their eGFR has ever been low' are different questions.

    The safer default is the current one — a patient whose function recovered
    should not stay on a drug-safety list forever.
    """
    predicate = parse_predicate({**EGFR, "operator": "<", "value": 60})
    assert isinstance(predicate, ObservationThreshold)
    assert predicate.most_recent is True


def test_exposure_defaults_to_active():
    """A finished course is not a patient who is 'on' a drug."""
    predicate = parse_predicate(
        {"type": "medication_attribute", "attribute": "nephrotoxic_risk", "in": ["high"]}
    )
    assert isinstance(predicate, MedicationAttribute)
    assert predicate.exposure == "active"
    assert predicate.within_days is None


def test_recent_exposure_carries_its_window():
    predicate = parse_predicate(
        {
            "type": "medication_attribute",
            "attribute": "nephrotoxic_risk",
            "in": ["high", "moderate"],
            "exposure": "recent",
            "within_days": 730,
        }
    )
    assert isinstance(predicate, MedicationAttribute)
    assert predicate.exposure == "recent"
    assert predicate.within_days == 730


def test_an_age_threshold_round_trips():
    predicate = parse_predicate({"type": "age_threshold", "operator": ">=", "value": 65})
    assert predicate == AgeThreshold(operator=">=", value=65)


def test_a_vital_status_round_trips():
    predicate = parse_predicate({"type": "vital_status", "status": "alive"})
    assert predicate == VitalStatus(status="alive")


def test_a_term_reference_round_trips():
    predicate = parse_predicate({"type": "term", "term": "elderly"})
    assert predicate == TermReference(term="elderly")


def test_composition_round_trips():
    logic = {
        "type": "all_of",
        "of": [
            {"type": "term", "term": "impaired renal function"},
            {"type": "term", "term": "nephrotoxic medication"},
        ],
    }
    predicate = parse_predicate(logic)
    assert isinstance(predicate, AllOf)
    assert predicate.of == (
        TermReference(term="impaired renal function"),
        TermReference(term="nephrotoxic medication"),
    )


def test_negation_round_trips():
    predicate = parse_predicate(
        {"type": "not", "of": {"type": "term", "term": "nephrotoxic medication"}}
    )
    assert predicate == Not(of=TermReference(term="nephrotoxic medication"))


@pytest.mark.parametrize(
    ("logic", "because"),
    [
        ({"type": "drop_table"}, "unknown type"),
        ({}, "no type at all"),
        ("select 1", "not an object"),
        ({**EGFR, "operator": "<", "value": 60, "x": 1}, "unknown key — specs are closed"),
        (
            {
                "type": "observation_threshold",
                "codes": [],
                "units": ["mL/min"],
                "operator": "<",
                "value": 60,
            },
            "empty code list",
        ),
        (
            {
                "type": "observation_threshold",
                "codes": ["33914-3"],
                "units": [],
                "operator": "<",
                "value": 60,
            },
            "empty unit list",
        ),
        ({**EGFR, "operator": "like", "value": 60}, "operator not on the allowlist"),
        ({**EGFR, "operator": "<", "value": "60; drop"}, "value is not a number"),
        ({**EGFR, "operator": "<", "value": True}, "bool is an int in Python, but not a lab value"),
        ({**EGFR, "operator": "<", "value": -5}, "negative lab value"),
        (
            {"type": "medication_attribute", "attribute": "nephrotoxic_risk", "in": []},
            "empty `in` matches nothing and means nothing",
        ),
        (
            {"type": "medication_attribute", "attribute": "nephrotoxic_risk", "in": "high"},
            "`in` must be a list, not a string",
        ),
        (
            {"type": "medication_attribute", "attribute": "nephrotoxic_risk", "in": [""]},
            "empty string in `in`",
        ),
        (
            {
                "type": "medication_attribute",
                "attribute": "nephrotoxic_risk",
                "in": ["high"],
                "exposure": "recent",
            },
            "'recent' needs a within_days",
        ),
        (
            {
                "type": "medication_attribute",
                "attribute": "nephrotoxic_risk",
                "in": ["high"],
                "exposure": "active",
                "within_days": 30,
            },
            "within_days means nothing for 'active'",
        ),
        ({"type": "age_threshold", "operator": ">=", "value": 65.5}, "fractional age"),
        ({"type": "age_threshold", "operator": ">=", "value": 900}, "impossible age"),
        ({"type": "vital_status", "status": "resting"}, "not a real vital status"),
        ({"type": "term", "term": ""}, "blank term name"),
        (
            {"type": "all_of", "of": [{"type": "term", "term": "x"}]},
            "combination needs at least two members",
        ),
    ],
)
def test_rejected(logic, because):
    with pytest.raises(InvalidPredicateError):
        parse_predicate(logic)
    assert because  # the label is the documentation


def test_the_rejection_says_what_was_wrong():
    """These rows are edited by a person, so 'invalid logic' is not good enough."""
    with pytest.raises(InvalidPredicateError, match="codes"):
        parse_predicate(
            {
                "type": "observation_threshold",
                "codes": [],
                "units": ["mL/min"],
                "operator": "<",
                "value": 60,
            }
        )


# ------------------------------------------------------------------ measures


def test_patient_count_round_trips():
    assert parse_measure({"type": "patient_count"}) == PatientCount()


def test_observation_aggregate_round_trips():
    predicate = parse_measure(
        {
            "type": "observation_aggregate",
            "codes": ["33914-3"],
            "units": ["mL/min"],
            "aggregate": "avg",
        }
    )
    assert predicate == ObservationAggregate(codes=("33914-3",), units=("mL/min",), aggregate="avg")


def test_unknown_aggregate_is_rejected():
    with pytest.raises(InvalidPredicateError):
        parse_measure(
            {
                "type": "observation_aggregate",
                "codes": ["33914-3"],
                "units": ["mL/min"],
                "aggregate": "sum",
            }
        )


# ---------------------------------------------------------------- dimensions


def test_patient_column_round_trips():
    assert parse_dimension({"type": "patient_column", "column": "sex"}) == PatientColumn(
        column="sex"
    )


def test_identifying_column_is_not_a_valid_dimension():
    with pytest.raises(InvalidPredicateError):
        parse_dimension({"type": "patient_column", "column": "full_name"})


def test_age_band_round_trips():
    bands = [{"label": "under 65", "upto": 65}, {"label": "65+"}]
    predicate = parse_dimension({"type": "age_band", "bands": bands})
    assert predicate == AgeBand(bands=(("under 65", 65), ("65+", None)))


def test_age_band_boundaries_must_ascend():
    bands = [{"label": "a", "upto": 65}, {"label": "b", "upto": 40}, {"label": "c"}]
    with pytest.raises(InvalidPredicateError):
        parse_dimension({"type": "age_band", "bands": bands})


def test_medication_group_round_trips():
    predicate = parse_dimension(
        {"type": "medication_group", "attribute": "nephrotoxic_risk", "exposure": "active"}
    )
    assert predicate == MedicationGroup(
        attribute="nephrotoxic_risk", exposure="active", within_days=None
    )


# ------------------------------------------------------- references helpers


def test_references_finds_every_term():
    predicate = parse_predicate(
        {
            "type": "all_of",
            "of": [
                {"type": "term", "term": "elderly"},
                {"type": "not", "of": {"type": "term", "term": "nephrotoxic medication"}},
            ],
        }
    )
    assert references(predicate) == ("elderly", "nephrotoxic medication")


def test_substitute_replaces_every_reference():
    predicate = parse_predicate({"type": "term", "term": "elderly"})
    built = AgeThreshold(operator=">=", value=65)
    resolved = substitute(predicate, lambda term: built)
    assert resolved == Resolved(term="elderly", predicate=built)
    # A resolved reference still reports the term it came from, and still
    # carries no unresolved reference of its own.
    assert references(resolved) == ("elderly",)


def test_observation_codes_walks_composition():
    predicate = parse_predicate(
        {
            "type": "any_of",
            "of": [
                {**EGFR, "operator": "<", "value": 60},
                {"type": "age_threshold", "operator": ">=", "value": 65},
            ],
        }
    )
    pairs = observation_codes(predicate)
    assert pairs == ((("33914-3",), ("mL/min",)),)
