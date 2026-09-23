"""What a `clinical_definitions.logic` value is allowed to say.

This module is the gate between a row in a database table and SQL that gets
executed. Everything downstream — the assembler, the tool, the answer — trusts
that a `Predicate` came through here, so this is the only place that decides
what a definition may express.

**Specs are closed**, the same way tool schemas are (CONVENTIONS.md > Tools). Every
key declared, unknown keys rejected, unknown `type` rejected. A spec that is
merely *parsed* rather than *validated* gives up the one guarantee the
assembler relies on, and it does so silently — the failure arrives later, as a
query that ran and returned the wrong patients.

Rejection is a raised `InvalidPredicateError` carrying a reason meant to be read by
a person: these come from a table a human edits, and "invalid logic" is not a
message anyone can act on.

Adding a shape means a dataclass, a branch in the parser, and a branch in the
assembler. Three places on purpose — a shape the assembler cannot build is
worse than one that does not exist, so the compiler-adjacent pain of touching
all three is the point.

**Three kinds of definition, three parsers.** A *filter* is a predicate over
patients — `parse_predicate`. A *measure* is something aggregated over the
patients a filter selects — `parse_measure`. A *dimension* is something they
are grouped by — `parse_dimension`. The three are kept as separate unions
rather than one, so the assembler's signatures say which they take and a
measure can never be handed somewhere a filter was expected.

**Validation happens at two levels, and this file is only the first.** Here a
spec is checked for *shape*: the right keys, a known operator, a number where a
number belongs. Whether the codes it names exist in the loaded dataset, and in
the unit it declares, is a question about data, needs a database, and belongs
to `definition_service`, which checks them against `observation_catalog` when
it builds the vocabulary.

Keeping those apart is what lets this module stay pure and stay honest: it
knows what a well-formed predicate looks like and deliberately knows nothing
about which cohort is loaded.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, cast

# There is deliberately no list of observation codes here. Which measurements
# a question may ask about is a property of the dataset that happens to be
# loaded, and it is answered by `observation_catalog` at resolution time. A
# tuple in this file is exactly the coupling that made swapping datasets a code
# change rather than a load.

# How a medication predicate may read exposure over time.
#
#   active  the prescription is open (`end_date is null`)
#   recent  open, or ended within `within_days`
#   ever    prescribed at any point on record
#
# Stated by the definition rather than defaulted silently, because the right
# answer is a property of the export. Synthea's 2020 sample closes nearly every
# prescription and its 2026 sample leaves them open; reading `active` against
# the first finds almost nobody, and reading `ever` against the second calls a
# course from a decade ago current.
EXPOSURES: Final = ("active", "recent", "ever")

COMPARISONS: Final = ("<", "<=", ">", ">=", "=")

VITAL_STATUSES: Final = ("alive", "deceased")

# What a measure may do to a per-patient value. No `sum`: summing a lab value
# across patients is not a clinical quantity, and its absence here is the only
# thing stopping a definition from asking for one.
AGGREGATES: Final = ("avg", "min", "max", "median")

# Patient columns a dimension may group by. Single-valued per patient, which
# is what makes grouping by them safe — see `assembler.aggregate_query` for
# the fan-out this list is protecting against. Never an identifying column.
PATIENT_DIMENSION_COLUMNS: Final = ("sex", "race", "state")

# Ages outside this are a typo, not a clinical question.
MAX_AGE: Final = 120

# How deep a composed predicate may nest. Real definitions are one or two
# levels; twenty is a definition that has become a program.
MAX_DEPTH: Final = 8


class InvalidPredicateError(ValueError):
    """A definitions row the assembler must not be asked to build SQL from."""


# ------------------------------------------------------------------ filters


@dataclass(frozen=True)
class ObservationThreshold:
    """A comparison against a coded measurement.

    `codes` is a set, not one code, because an analyte has several in real
    data: creatinine is LOINC 2160-0 in serum and 38483-4 in blood, and a
    patient's latest result may be under either. Matching a single code would
    miss them silently, which is the worst way to be wrong.

    `units` is required and is compared, never converted. The same code arrives
    in more than one unit in real data — Synthea reports eGFR as both
    `mL/min/{1.73_m2}` and `mL/min` under one LOINC — and a threshold of 60
    means something different against each. A row in a unit not listed here is
    invisible to this predicate, which is the same choice as a restricted
    column being denied rather than redacted: a silent adjustment answers a
    question nobody asked. Listing two units is the definition's author
    asserting they are comparable for this threshold, with the reason in
    `notes`; that is a reviewable judgement where a conversion table would be
    a hidden one.

    `most_recent` is the difference between "their kidney function is reduced"
    and "their kidney function has ever been reduced". Both are legitimate
    questions with different answers, so the definition says which it means.
    With several codes, "most recent" is the latest across all of them —
    whichever assay ran last is the current picture.
    """

    codes: tuple[str, ...]
    units: tuple[str, ...]
    operator: str
    value: Decimal
    most_recent: bool


@dataclass(frozen=True)
class MedicationAttribute:
    """Membership test against a curated annotation, not against the drug row.

    `attribute` names a row in `medication_annotations` — `nephrotoxic_risk` is
    the one this project curates. The source data has RxNorm codes and no
    opinion about kidney risk, and that separation is deliberate: the judgement
    is reviewable because it is a row with a rationale.

    `exposure` says how to read time. See EXPOSURES; `within_days` is required
    for `recent` and meaningless otherwise.
    """

    attribute: str
    values: tuple[str, ...]
    exposure: str
    within_days: int | None


@dataclass(frozen=True)
class AgeThreshold:
    """A comparison against age derived from `birth_date`.

    Derived rather than stored, which is what lets age be filtered on while
    birth_date itself stays redacted by the column rules.
    """

    operator: str
    value: int


@dataclass(frozen=True)
class VitalStatus:
    """Alive or deceased, as the source records it.

    The source keeps deceased patients, as a hospital does. A question about
    drug safety usually means the living and a question about outcomes does
    not, so this is a term a definition applies rather than a filter the
    assembler adds on its own.
    """

    status: str


@dataclass(frozen=True)
class TermReference:
    """Another definition, by name. How a term is built from terms.

    `frail elderly` may say `{"type": "term", "term": "elderly"}` rather than
    restating 65, so a vocabulary with reuse cannot drift into two rows that
    each encode the same number and eventually disagree. Resolved by
    `definition_service` when the vocabulary loads — this module does not know
    which terms exist — and the resolved form is `Resolved`, below.
    """

    term: str


@dataclass(frozen=True)
class AnyOf:
    """OR. Non-empty, and every member is a full predicate in its own right."""

    of: tuple["Predicate", ...]


@dataclass(frozen=True)
class AllOf:
    """AND, written down. The assembler ANDs top-level terms anyway; this is
    for composing inside a definition."""

    of: tuple["Predicate", ...]


@dataclass(frozen=True)
class Not:
    """Negation of one predicate.

    The trap worth naming: "not on a nephrotoxic drug" and "no prescription
    record at all" are different claims, and NOT EXISTS answers the first. A
    patient with no prescriptions on file satisfies this predicate, which is
    correct and is worth saying in the definition's `notes`.
    """

    of: "Predicate"


@dataclass(frozen=True)
class Resolved:
    """A `TermReference` after the vocabulary looked it up.

    Keeps the term's name so an answer can still say which definition a
    composed term leaned on, and so the audit's version map covers it.
    """

    term: str
    predicate: "Predicate"


Predicate = (
    ObservationThreshold
    | MedicationAttribute
    | AgeThreshold
    | VitalStatus
    | TermReference
    | AnyOf
    | AllOf
    | Not
    | Resolved
)


# ----------------------------------------------------------------- measures


@dataclass(frozen=True)
class PatientCount:
    """How many patients. The one measure every question already implies."""


@dataclass(frozen=True)
class ObservationAggregate:
    """An aggregate over each patient's *latest* value for a code set.

    One value per patient, then the aggregate over patients — never an
    aggregate over raw observation rows. The distinction is the difference
    between "average eGFR across the cohort" and "average of every eGFR ever
    drawn, weighted by however often each patient was tested", and only the
    first is a clinical quantity.

    `units` is required for the reason it is on `ObservationThreshold`.
    """

    codes: tuple[str, ...]
    units: tuple[str, ...]
    aggregate: str


Measure = PatientCount | ObservationAggregate


# --------------------------------------------------------------- dimensions


@dataclass(frozen=True)
class PatientColumn:
    """Group by a patient column. Single-valued, so every patient lands in
    exactly one group and the counts add up to the cohort."""

    column: str


@dataclass(frozen=True)
class AgeBand:
    """Group by age, in bands a definition declares.

    The boundaries are a clinical judgement — 65 is the geriatric line for a
    reason, 18 is not a clinical fact about kidneys — so they belong in a row
    with a rationale, exactly like a threshold does. Bands are contiguous and
    ordered: each `upto` is exclusive and the last band is open-ended.
    """

    bands: tuple[tuple[str, int | None], ...]


@dataclass(frozen=True)
class MedicationGroup:
    """Group by a curated annotation value — patients per nephrotoxic tier.

    **Multi-valued per patient.** A patient on a high-tier drug and a
    moderate-tier drug belongs to both groups, so this dimension fans out, and
    the assembler refuses to combine it with any measure other than a patient
    count. Averaging a lab value across this grouping would weight each
    patient by how many tiers they touch, which is a number that means
    nothing and looks like one that does.
    """

    attribute: str
    exposure: str
    within_days: int | None


@dataclass(frozen=True)
class MedicationName:
    """Group by the medication itself — which specific drug, not which
    patient or which tier. `entity` on the definition row this builds from is
    `"medication"`: the query this feeds is FROM prescriptions/medications,
    never FROM patients, which is what tells `clinical_query_service` to
    reach for `assembler.medication_aggregate_query` instead of
    `aggregate_query`.

    Restricted to medications carrying a given curated annotation, the same
    `attribute`/`values`/`exposure`/`within_days` shape `MedicationAttribute`
    already uses to answer "is this patient on one of these" — here it
    answers "which of these, and how many patients is each one on". Unlike
    `MedicationGroup`, this does not fan out patients across groups: each row
    already *is* one medication, counted once.
    """

    attribute: str
    values: tuple[str, ...]
    exposure: str
    within_days: int | None


Dimension = PatientColumn | AgeBand | MedicationGroup | MedicationName


# ---------------------------------------------------------------- invariants


@dataclass(frozen=True)
class Invariant:
    """A filter's claimed relationship to another filter.

    Not enforced at save time — the data under a threshold can shift, and a
    relationship that held when it was written is a fact worth re-checking on
    every load, not a rule the editor should block a save over.
    `definition_service.check_model()` is where it is actually checked, against
    the loaded dataset, and surfaces a violation the same way a definition
    matching nobody already does: a warning, not a rejection.
    """

    type: str
    term: str


INVARIANT_TYPES: Final = ("subset_of", "disjoint_from")


def parse_invariants(value: object) -> tuple[Invariant, ...]:
    """Validate a `clinical_definitions.invariants` value. Raises
    `InvalidPredicateError`. `None` and `[]` both mean "none claimed"."""
    if value is None:
        return ()
    if not isinstance(value, list):
        message = f"invariants must be a list, got {type(value).__name__}"
        raise InvalidPredicateError(message)

    invariants: list[Invariant] = []
    for entry in cast("list[Any]", value):
        spec = _as_spec(entry)
        _reject_unknown_keys(spec, frozenset({"type", "term"}))
        kind = _require_one_of("type", spec.get("type"), INVARIANT_TYPES)
        term = spec.get("term")
        if not isinstance(term, str) or not term.strip():
            message = f"an invariant's `term` must name a definition, got {term!r}"
            raise InvalidPredicateError(message)
        invariants.append(Invariant(type=kind, term=term))
    return tuple(invariants)


# ------------------------------------------------------------------ parsing


def parse_predicate(logic: object) -> Predicate:
    """Validate one filter `logic` value. Raises `InvalidPredicateError`.

    Takes `object`, not a mapping: this value came out of a JSONB column, so
    claiming a shape in the signature and then checking it anyway would be the
    signature lying about where the data came from.
    """
    return _parse_predicate(logic, depth=0)


def parse_measure(logic: object) -> Measure:
    """Validate one measure `logic` value. Raises `InvalidPredicateError`."""
    spec = _as_spec(logic)
    kind = spec.get("type")
    if kind == "patient_count":
        _reject_unknown_keys(spec, frozenset({"type"}))
        return PatientCount()
    if kind == "observation_aggregate":
        _reject_unknown_keys(spec, frozenset({"type", "codes", "units", "aggregate"}))
        return ObservationAggregate(
            codes=_require_code_list("codes", spec.get("codes")),
            units=_require_units(spec.get("units")),
            aggregate=_require_one_of("aggregate", spec.get("aggregate"), AGGREGATES),
        )
    message = (
        f"unknown measure type {kind!r}; expected one of: patient_count, observation_aggregate"
    )
    raise InvalidPredicateError(message)


def parse_dimension(logic: object) -> Dimension:
    """Validate one dimension `logic` value. Raises `InvalidPredicateError`."""
    spec = _as_spec(logic)
    kind = spec.get("type")
    if kind == "patient_column":
        _reject_unknown_keys(spec, frozenset({"type", "column"}))
        column = _require_one_of("column", spec.get("column"), PATIENT_DIMENSION_COLUMNS)
        return PatientColumn(column=column)
    if kind == "age_band":
        _reject_unknown_keys(spec, frozenset({"type", "bands"}))
        return AgeBand(bands=_require_bands(spec.get("bands")))
    if kind == "medication_group":
        _reject_unknown_keys(spec, frozenset({"type", "attribute", "exposure", "within_days"}))
        exposure, within_days = _require_exposure(spec)
        return MedicationGroup(
            attribute=_require_attribute(spec.get("attribute")),
            exposure=exposure,
            within_days=within_days,
        )
    if kind == "medication_name":
        _reject_unknown_keys(
            spec, frozenset({"type", "attribute", "in", "exposure", "within_days"})
        )
        exposure, within_days = _require_exposure(spec)
        return MedicationName(
            attribute=_require_attribute(spec.get("attribute")),
            values=_require_code_list("in", spec.get("in")),
            exposure=exposure,
            within_days=within_days,
        )
    known = "patient_column, age_band, medication_group, medication_name"
    message = f"unknown dimension type {kind!r}; expected one of: {known}"
    raise InvalidPredicateError(message)


def substitute(predicate: Predicate, lookup: Callable[[str], Predicate]) -> Predicate:
    """Replace every `TermReference` with what `lookup` returns for it.

    The loader passes a function that raises `InvalidPredicateError` for an
    unknown or cyclic term, so an unresolvable reference fails at load rather
    than at question time.
    """
    match predicate:
        case TermReference():
            return Resolved(term=predicate.term, predicate=lookup(predicate.term))
        case AnyOf():
            return AnyOf(of=tuple(substitute(member, lookup) for member in predicate.of))
        case AllOf():
            return AllOf(of=tuple(substitute(member, lookup) for member in predicate.of))
        case Not():
            return Not(of=substitute(predicate.of, lookup))
        case _:
            return predicate


def observation_codes(
    predicate: Predicate,
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Every (code set, unit set) pair a predicate compares against.

    What the data-level validation checks against `observation_catalog`.
    """
    match predicate:
        case ObservationThreshold():
            return ((predicate.codes, predicate.units),)
        case AnyOf() | AllOf():
            return tuple(pair for member in predicate.of for pair in observation_codes(member))
        case Not():
            return observation_codes(predicate.of)
        case Resolved():
            return observation_codes(predicate.predicate)
        case _:
            return ()


# --------------------------------------------------------------- the checks


def _parse_predicate(logic: object, *, depth: int) -> Predicate:
    if depth > MAX_DEPTH:
        message = f"logic nests deeper than {MAX_DEPTH} levels; a definition that deep is a program"
        raise InvalidPredicateError(message)

    spec = _as_spec(logic)
    kind = spec.get("type")
    if kind == "observation_threshold":
        return _observation_threshold(spec)
    if kind == "medication_attribute":
        return _medication_attribute(spec)
    if kind == "age_threshold":
        return _age_threshold(spec)
    if kind == "vital_status":
        _reject_unknown_keys(spec, frozenset({"type", "status"}))
        return VitalStatus(status=_require_one_of("status", spec.get("status"), VITAL_STATUSES))
    if kind == "term":
        _reject_unknown_keys(spec, frozenset({"type", "term"}))
        term = spec.get("term")
        if not isinstance(term, str) or not term.strip():
            message = f"`term` must name a definition, got {term!r}"
            raise InvalidPredicateError(message)
        return TermReference(term=term)
    if kind in {"any_of", "all_of"}:
        _reject_unknown_keys(spec, frozenset({"type", "of"}))
        members = _require_members(spec.get("of"), depth=depth)
        return AnyOf(of=members) if kind == "any_of" else AllOf(of=members)
    if kind == "not":
        _reject_unknown_keys(spec, frozenset({"type", "of"}))
        return Not(of=_parse_predicate(spec.get("of"), depth=depth + 1))

    known = (
        "observation_threshold, medication_attribute, age_threshold, vital_status, term, "
        "any_of, all_of, not"
    )
    message = f"unknown logic type {kind!r}; expected one of: {known}"
    raise InvalidPredicateError(message)


def _as_spec(logic: object) -> Mapping[str, Any]:
    if not isinstance(logic, Mapping):
        message = f"logic must be an object, got {type(logic).__name__}"
        raise InvalidPredicateError(message)
    # The isinstance above is the actual check; the cast only tells the type
    # checker what the runtime now guarantees. Every value inside is still
    # treated as untrusted by the branches below.
    return cast("Mapping[str, Any]", logic)


def _reject_unknown_keys(logic: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(set(logic) - allowed)
    if unknown:
        message = (
            f"unexpected key(s) {unknown} for logic type {logic.get('type')!r}; "
            f"allowed: {sorted(allowed)}"
        )
        raise InvalidPredicateError(message)


def _require_one_of(field: str, value: Any, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        message = f"{field} must be one of {list(allowed)}, got {value!r}"
        raise InvalidPredicateError(message)
    return value


def _require_bool(field: str, value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        message = f"{field} must be true or false, got {value!r}"
        raise InvalidPredicateError(message)
    return value


def _require_units(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        message = (
            f"`units` must be a non-empty list, got {value!r}. A threshold without a unit "
            "is compared against whatever unit each row happens to be in."
        )
        raise InvalidPredicateError(message)
    return _require_code_list("units", value)


def _require_attribute(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        message = f"attribute must be a non-empty string, got {value!r}"
        raise InvalidPredicateError(message)
    return value


def _require_number(field: str, raw: Any) -> Decimal:
    # bool is a subclass of int, and `egfr < true` should not parse.
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        message = f"{field} must be a number, got {raw!r}"
        raise InvalidPredicateError(message)
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        message = f"{field} must be a number, got {raw!r}"
        raise InvalidPredicateError(message) from None
    if value < 0:
        message = f"{field} must not be negative, got {value}"
        raise InvalidPredicateError(message)
    return value


def _observation_threshold(logic: Mapping[str, Any]) -> ObservationThreshold:
    _reject_unknown_keys(
        logic, frozenset({"type", "codes", "units", "operator", "value", "most_recent"})
    )
    return ObservationThreshold(
        codes=_require_code_list("codes", logic.get("codes")),
        units=_require_units(logic.get("units")),
        operator=_require_one_of("operator", logic.get("operator"), COMPARISONS),
        value=_require_number("value", logic.get("value")),
        most_recent=_require_bool("most_recent", logic.get("most_recent"), default=True),
    )


def _require_exposure(logic: Mapping[str, Any]) -> tuple[str, int | None]:
    exposure = _require_one_of("exposure", logic.get("exposure", "active"), EXPOSURES)
    within_days = logic.get("within_days")
    if exposure == "recent":
        if isinstance(within_days, bool) or not isinstance(within_days, int) or within_days <= 0:
            message = (
                f"exposure 'recent' needs a positive `within_days`, got {within_days!r}. "
                "How recent is a clinical judgement and has to be stated."
            )
            raise InvalidPredicateError(message)
        return exposure, within_days
    if within_days is not None:
        message = f"`within_days` means nothing for exposure {exposure!r}; remove it"
        raise InvalidPredicateError(message)
    return exposure, None


def _medication_attribute(logic: Mapping[str, Any]) -> MedicationAttribute:
    _reject_unknown_keys(logic, frozenset({"type", "attribute", "in", "exposure", "within_days"}))
    exposure, within_days = _require_exposure(logic)
    return MedicationAttribute(
        attribute=_require_attribute(logic.get("attribute")),
        values=_require_code_list("in", logic.get("in")),
        exposure=exposure,
        within_days=within_days,
    )


def _require_code_list(field: str, value: Any) -> tuple[str, ...]:
    """A non-empty list of non-empty strings, preserved in order."""
    if not isinstance(value, list) or not value:
        message = f"`{field}` must be a non-empty list, got {value!r}"
        raise InvalidPredicateError(message)
    items = cast("list[Any]", value)
    if not all(isinstance(item, str) and item.strip() for item in items):
        message = f"`{field}` must contain only non-empty strings, got {items!r}"
        raise InvalidPredicateError(message)
    return tuple(str(item) for item in items)


def _require_members(value: Any, *, depth: int) -> tuple[Predicate, ...]:
    # PLR2004: two is the definition of a combination, not a tunable limit.
    if not isinstance(value, list) or len(cast("list[Any]", value)) < 2:  # noqa: PLR2004
        message = "`of` must be a list of at least two predicates; one is not a combination"
        raise InvalidPredicateError(message)
    members = cast("list[Any]", value)
    return tuple(_parse_predicate(member, depth=depth + 1) for member in members)


def _require_bands(value: Any) -> tuple[tuple[str, int | None], ...]:
    # PLR2004: one band is no breakdown at all, so two is the floor by definition.
    if not isinstance(value, list) or len(cast("list[Any]", value)) < 2:  # noqa: PLR2004
        message = "`bands` must list at least two bands, each {label, upto}; the last has no upto"
        raise InvalidPredicateError(message)
    raw_bands = cast("list[Any]", value)
    bands: list[tuple[str, int | None]] = []
    previous: int | None = None
    for index, raw in enumerate(raw_bands):
        band = _as_spec(raw)
        _reject_unknown_keys(band, frozenset({"label", "upto"}))
        label = band.get("label")
        if not isinstance(label, str) or not label.strip():
            message = f"band {index} needs a non-empty `label`, got {label!r}"
            raise InvalidPredicateError(message)
        upto = band.get("upto")
        last = index == len(raw_bands) - 1
        if last:
            if upto is not None:
                message = "the last band is open-ended and must not have `upto`"
                raise InvalidPredicateError(message)
        elif isinstance(upto, bool) or not isinstance(upto, int) or not 0 < upto <= MAX_AGE:
            message = f"band {index} needs an `upto` between 1 and {MAX_AGE}, got {upto!r}"
            raise InvalidPredicateError(message)
        elif previous is not None and upto <= previous:
            message = f"bands must ascend; band {index} ends at {upto} after {previous}"
            raise InvalidPredicateError(message)
        else:
            previous = upto
        bands.append((label, None if last else upto))
    return tuple(bands)


def _age_threshold(logic: Mapping[str, Any]) -> AgeThreshold:
    _reject_unknown_keys(logic, frozenset({"type", "operator", "value"}))
    operator = _require_one_of("operator", logic.get("operator"), COMPARISONS)

    value = logic.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        message = f"age value must be a whole number, got {value!r}"
        raise InvalidPredicateError(message)
    if not 0 <= value <= MAX_AGE:
        message = f"age value must be between 0 and {MAX_AGE}, got {value}"
        raise InvalidPredicateError(message)

    return AgeThreshold(operator=operator, value=value)
