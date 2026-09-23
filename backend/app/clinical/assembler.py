"""Turning validated predicates into SQL.

The deterministic half of the architecture. The model's job ends at choosing
which defined terms a question means; this module decides what SQL that is, and
it is the only thing that writes any.

Three properties it has to keep:

**Nothing is interpolated.** Every value arrives as a bound parameter, and
every column and operator is chosen from a tuple declared in `predicates.py`.
There is no code path here that puts a caller's string into SQL text — which is
the reason `clinical_definitions.logic` is structured data and not a snippet.

**An empty predicate list is refused.** A query assembled from no filters is
`select * from patients`, and the way that bug reaches production is a term
that silently failed to resolve. Failing closed here means the worst case is a
refusal instead of the entire cohort.

**Each leaf predicate is an independent EXISTS or scalar subquery.** They
compose with AND, OR and NOT and never multiply rows, so "on a nephrotoxic drug
AND has reduced eGFR" cannot return a patient twice because they are on two
nephrotoxic drugs. A join-based version of this needs a DISTINCT that is easy
to forget and invisible when forgotten.

The same property is what makes `aggregate_query` safe: every measure is
computed from one value per patient, so an average is an average over
patients. The one dimension that does fan out — grouping by a medication
annotation, where a patient can be in two groups — is allowed only with a
patient count, and that refusal is written here rather than left to a caller
to remember.

Row-level scope is the last thing in every WHERE clause. A user confined to
some states gets `patients.state in (...)` on every query this module builds,
which is the discipline `conversations.user_id` already follows: a row outside
the scope is indistinguishable from one that does not exist.
"""

import operator
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from typing import Any, Final, NoReturn

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    exists,
    func,
    not_,
    or_,
    select,
    true,
)

from app.clinical.columns import age_expression
from app.clinical.predicates import (
    AgeBand,
    AgeThreshold,
    AllOf,
    AnyOf,
    Dimension,
    InvalidPredicateError,
    Measure,
    MedicationAttribute,
    MedicationGroup,
    MedicationName,
    Not,
    ObservationAggregate,
    ObservationThreshold,
    PatientColumn,
    PatientCount,
    Predicate,
    Resolved,
    TermReference,
    VitalStatus,
)
from app.models import Medication, MedicationAnnotation, Observation, Patient, Prescription

_COMPARE: Final[dict[str, Callable[[Any, Any], ColumnElement[bool]]]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "=": operator.eq,
}

# A named predicate, for the explain path: which leg admitted or excluded a
# patient is only answerable if each leg carries the term it came from.
NamedPredicate = tuple[str, Predicate]


def patient_condition(
    predicates: Sequence[Predicate],
    *,
    today: date,
    scope_states: Sequence[str] | None = None,
) -> ColumnElement[bool]:
    """Combine predicates into one WHERE clause correlated to `patients`.

    `today` is explicit rather than `date.today()` so that an age-dependent
    answer is reproducible: the eval harness pins it, and a test written in
    September still passes in March.
    """
    if not predicates:
        message = (
            "refusing to assemble a query with no predicates — that is every patient. "
            "A question that resolved to nothing should be a clarification, not a query."
        )
        raise InvalidPredicateError(message)

    conditions = [condition_for(predicate, today=today) for predicate in predicates]
    return and_(*conditions, scope_condition(scope_states))


def scope_condition(scope_states: Sequence[str] | None) -> ColumnElement[bool]:
    """Row-level access as a predicate. `None` is unconfined; `[]` sees nobody."""
    if scope_states is None:
        return true()
    return Patient.state.in_(list(scope_states))


def patient_query(
    predicates: Sequence[Predicate],
    *,
    today: date,
    columns: Sequence[Any] | None = None,
    scope_states: Sequence[str] | None = None,
) -> Select[Any]:
    """A SELECT over matching patients.

    `columns` defaults to the two that are never restricted. Choosing which
    columns a caller may actually have is the column-access-control layer's
    job, not this one's — the assembler builds what it is asked for and the
    guardrails decide what may be asked.
    """
    chosen = list(columns) if columns else [Patient.id, Patient.source_id]
    return (
        select(*chosen)
        .where(patient_condition(predicates, today=today, scope_states=scope_states))
        .order_by(Patient.source_id)
    )


def browse_patients_query(
    *,
    columns: Sequence[Any] | None = None,
    scope_states: Sequence[str] | None = None,
    offset: int = 0,
    limit: int,
) -> Select[Any]:
    """A page of every patient in scope. No predicates — the deliberate
    exception to `patient_condition`'s refusal of an empty one.

    That refusal exists because an unresolved term silently becoming "every
    patient" is a bug wearing a query's clothes. A curator or auditor asking
    to page through the raw dataset is not that bug; it is the governed table
    browser SEMANTIC_LAYER.md § 3 asks for, and "the fastest way to lose
    faith in an answer is to be unable to look at the rows behind it" is the
    argument for building it at all. Row-level scope still applies —
    browsing is a way around requiring a filter first, never around who a
    user's queries may see.

    No `today` parameter, unlike `patient_query`: `columns` already carries a
    baked-in `age` expression if one was requested, resolved by
    `clinical/columns.py` before this is ever called.
    """
    chosen = list(columns) if columns else [Patient.id, Patient.source_id]
    return (
        select(*chosen)
        .where(scope_condition(scope_states))
        .order_by(Patient.source_id)
        .offset(offset)
        .limit(limit)
    )


def browse_patients_count(*, scope_states: Sequence[str] | None = None) -> Select[Any]:
    """How many patients `browse_patients_query` has to page through, in
    scope — the denominator a pager needs and a single page cannot show."""
    return select(func.count()).select_from(Patient).where(scope_condition(scope_states))


def aggregate_query(
    predicates: Sequence[Predicate],
    *,
    measures: Sequence[tuple[str, Measure]],
    dimensions: Sequence[tuple[str, Dimension]],
    today: date,
    scope_states: Sequence[str] | None = None,
) -> Select[Any]:
    """Measures over the cohort a predicate list selects, grouped by dimensions.

    Every measure is a per-patient value aggregated over patients, and every
    dimension except `MedicationGroup` is single-valued per patient, so the
    result's counts add up to the cohort and its averages are averages over
    people. `MedicationGroup` fans out and is admitted only with
    `PatientCount`, which counts distinct patients and so survives the fan-out
    honestly. That check is the fan-out protection; do not move it.

    Labels are the definition's own term, so the row a caller gets back reads
    `{"nephrotoxic tier": "high", "patient count": 12}` and needs no second
    lookup to be a sentence.
    """
    if not measures:
        message = "an aggregate query needs at least one measure"
        raise InvalidPredicateError(message)

    fans_out = any(isinstance(dimension, MedicationGroup) for _, dimension in dimensions)
    if fans_out and any(not isinstance(measure, PatientCount) for _, measure in measures):
        message = (
            "grouping by a medication annotation puts a patient in more than one group, so "
            "only a patient count can be reported against it. An average across that "
            "grouping would weight each patient by how many groups they fall in."
        )
        raise InvalidPredicateError(message)

    condition = patient_condition(predicates, today=today, scope_states=scope_states)

    # A fan-out dimension is a joined subquery of (patient, value) pairs, and
    # the same subquery object has to appear in the join and in the select
    # list, so it is built once here and handed to the expression builder.
    groups = {
        label: _medication_group_rows(dimension, today=today)
        for label, dimension in dimensions
        if isinstance(dimension, MedicationGroup)
    }
    dimension_columns = [
        _dimension_expression(dimension, today=today, group=groups.get(label)).label(label)
        for label, dimension in dimensions
    ]
    measure_columns = [_measure_expression(measure).label(label) for label, measure in measures]

    query = select(*dimension_columns, *measure_columns).select_from(Patient).where(condition)
    for group in groups.values():
        query = query.join(group, group.c.patient_id == Patient.id)
    if dimension_columns:
        query = query.group_by(*dimension_columns).order_by(
            *(
                _dimension_order(dimension, column, today=today)
                for (_, dimension), column in zip(dimensions, dimension_columns, strict=True)
            )
        )
    return query


def _dimension_order(
    dimension: Dimension, column: ColumnElement[Any], *, today: date
) -> ColumnElement[Any]:
    """What a dimension's groups sort by: its label, except where the label is
    a name for a position on a scale.

    An age band is: "under 18" sorts after "80+" as text, because letters sort
    after digits, and that is how the bands used to come back — in the table,
    the chart and the CSV alike. Ordering by the youngest age in each group
    puts them where the definition lists them, youngest first, whatever the
    labels say. An aggregate is what a grouped query may order by; the band's
    own position, computed per row, is not.
    """
    if isinstance(dimension, AgeBand):
        return func.min(age_expression(today))
    return column


def _join_medication_annotations(query: Select[Any]) -> Select[Any]:
    """The two-hop join every curated-annotation read needs, declared once
    rather than written out by hand at each of the four places that used to
    repeat it identically: `medication_aggregate_query`,
    `_medication_condition`, `matching_prescriptions_query` and
    `_medication_group_rows`.

    **The relationship, and its cardinality.** `prescriptions.medication_id`
    is a real foreign key to `medications.id` — many prescriptions to one
    medication. `medications` to `medication_annotations` is not a foreign
    key at all: it joins on `code` (unique on `medications`, RxNorm) because
    `medication_annotations` is curated review data meant to survive a
    reload that reassigns every `medications.id` — see the model's own
    docstring. `medication_annotations`'s real constraint is `(code,
    attribute)`, not `code` alone, so this join **fans out** one row per
    curated attribute a drug happens to have. Every caller filters
    `attribute` in its own `WHERE` for exactly that reason; this function
    only builds the join; it is still each caller's job to constrain which
    row of the fan-out it means, the same way `aggregate_query`'s own
    `MedicationGroup` fan-out guard is a caller's job to remember, not
    something a join can enforce for you.
    """
    return query.join(Medication, Medication.id == Prescription.medication_id).join(
        MedicationAnnotation, MedicationAnnotation.code == Medication.code
    )


def medication_aggregate_query(
    predicates: Sequence[Predicate],
    *,
    measures: Sequence[tuple[str, Measure]],
    dimensions: Sequence[tuple[str, Dimension]],
    today: date,
    scope_states: Sequence[str] | None = None,
) -> Select[Any]:
    """Measures over prescriptions, grouped by the medication itself — the
    medication-entity counterpart to `aggregate_query`.

    FROM prescriptions joined to medications, never FROM patients: "which
    nephrotoxins are most prescribed" is a question about drugs, and routing
    it through `aggregate_query`'s patient-scoped shape would answer a
    different question (patients grouped by their tier, not drugs counted by
    name). `predicates` still mean what they mean everywhere else — `terms`
    like "elderly" become a semi-join against the exact same
    `patient_condition` every other query path uses, so scoping this to a
    sub-cohort does not need a second predicate language.

    Only a patient count is admitted, for the same reason `aggregate_query`
    restricts `MedicationGroup` to one: there is no per-medication scalar
    value to average here, only patients to count. Only `MedicationName` is
    admitted as a dimension, since it is the one dimension shape that
    supplies the attribute/values filter this query's FROM clause needs to
    decide which medications are even in scope.
    """
    if not measures:
        message = "an aggregate query needs at least one measure"
        raise InvalidPredicateError(message)
    if not dimensions:
        message = "a medication aggregate needs a medication_name dimension to group by"
        raise InvalidPredicateError(message)
    if any(not isinstance(measure, PatientCount) for _, measure in measures):
        message = (
            "only a patient count can be reported grouped by medication — there is no "
            "per-medication value to average"
        )
        raise InvalidPredicateError(message)
    if any(not isinstance(dimension, MedicationName) for _, dimension in dimensions):
        message = "a medication aggregate can only group by a medication_name dimension"
        raise InvalidPredicateError(message)

    patient_ids = select(Patient.id).where(
        patient_condition(predicates, today=today, scope_states=scope_states)
    )
    dimension_columns = [Medication.display.label(label) for label, _ in dimensions]
    measure_columns = [
        func.count(func.distinct(Prescription.patient_id)).label(label) for label, _ in measures
    ]
    medication_filters = [
        and_(
            MedicationAnnotation.attribute == dimension.attribute,
            MedicationAnnotation.value.in_(dimension.values),
            _exposure_condition(dimension.exposure, dimension.within_days, today=today),
        )
        for _, dimension in dimensions
        if isinstance(dimension, MedicationName)
    ]

    return (
        _join_medication_annotations(
            select(*dimension_columns, *measure_columns).select_from(Prescription)
        )
        .where(Prescription.patient_id.in_(patient_ids), *medication_filters)
        .group_by(*dimension_columns)
        .order_by(measure_columns[0].desc())
    )


def unmeasured_query(
    threshold: ObservationThreshold,
    *,
    other: Sequence[Predicate],
    today: date,
    scope_states: Sequence[str] | None = None,
) -> Select[Any]:
    """How many patients match `other` but have no value for `threshold`.

    The denominator SEMANTIC_LAYER.md § 10 asks for: not "how many patients
    have impaired renal function" but "how many could not be evaluated for
    it". `other` may be empty — a question naming only this one term — in
    which case the count is simply everyone unmeasured, still inside scope.
    """
    unmeasured = unmeasured_condition(threshold)
    condition = (
        and_(patient_condition(other, today=today, scope_states=scope_states), unmeasured)
        if other
        else and_(scope_condition(scope_states), unmeasured)
    )
    return select(func.count(func.distinct(Patient.id))).select_from(Patient).where(condition)


def unmeasured_condition(threshold: ObservationThreshold) -> ColumnElement[bool]:
    """Patients with no numeric result at all for this threshold's codes and unit.

    The denominator a threshold silently drops. "Patients with impaired renal
    function" excludes everyone never tested, which is defensible only if the
    answer says how many that is.
    """
    return not_(
        exists(
            select(1)
            .where(
                Observation.patient_id == Patient.id,
                Observation.code.in_(threshold.codes),
                Observation.unit.in_(threshold.units),
                Observation.value_numeric.is_not(None),
            )
            .correlate(Patient)
        )
    )


def leg_report_query(
    named: Sequence[NamedPredicate], *, source_id: str, today: date
) -> Select[Any]:
    """For one patient, whether each named predicate admits them.

    One row, one boolean column per term. The explain path — "why is this
    patient not in the cohort" — is this query plus the evidence queries below.
    Scope is deliberately not applied: a curator asking why a patient is
    absent should be told "out of your scope" by the caller, not shown a row
    that does not exist.
    """
    columns = [
        case((condition_for(predicate, today=today), True), else_=False).label(term)
        for term, predicate in named
    ]
    return select(Patient.source_id, *columns).where(Patient.source_id == source_id)


def latest_observation_query(threshold: ObservationThreshold, *, source_id: str) -> Select[Any]:
    """The value a threshold actually compared for one patient, and when.

    Evidence for a cohort row: the number behind "impaired renal function"
    rather than the word. Reads the observation, never a patient column.
    """
    return (
        select(
            Observation.code,
            Observation.display,
            Observation.value_numeric,
            Observation.unit,
            Observation.taken_at,
        )
        .join(Patient, Patient.id == Observation.patient_id)
        .where(
            Patient.source_id == source_id,
            Observation.code.in_(threshold.codes),
            Observation.unit.in_(threshold.units),
            Observation.value_numeric.is_not(None),
        )
        .order_by(Observation.taken_at.desc())
        .limit(1)
    )


def matching_prescriptions_query(
    predicate: MedicationAttribute, *, source_id: str, today: date
) -> Select[Any]:
    """The prescriptions that put one patient inside a medication predicate."""
    return (
        _join_medication_annotations(
            select(
                Medication.display,
                Medication.code,
                MedicationAnnotation.value,
                Prescription.start_date,
                Prescription.end_date,
            )
            .select_from(Prescription)
            .join(Patient, Patient.id == Prescription.patient_id)
        )
        .where(
            Patient.source_id == source_id,
            MedicationAnnotation.attribute == predicate.attribute,
            MedicationAnnotation.value.in_(predicate.values),
            _exposure_condition(predicate.exposure, predicate.within_days, today=today),
        )
        .order_by(Prescription.start_date.desc())
    )


def touched_columns(
    predicates: Sequence[Predicate],
    *,
    measures: Sequence[Measure] = (),
    dimensions: Sequence[Dimension] = (),
) -> tuple[str, ...]:
    """Every column these predicates read, qualified, for the audit log.

    "Which columns did that question touch" is the question a PHI audit asks,
    and answering it by re-parsing the emitted SQL would be inventing a parser
    to recover something already known here.
    """
    touched: set[str] = set()
    for predicate in predicates:
        touched.update(_touched_by(predicate))
    for measure in measures:
        if isinstance(measure, ObservationAggregate):
            touched.update(_OBSERVATION_COLUMNS)
    for dimension in dimensions:
        match dimension:
            case PatientColumn():
                touched.add(f"patients.{dimension.column}")
            case AgeBand():
                touched.add("patients.birth_date")
            case MedicationGroup():
                touched.update(_MEDICATION_COLUMNS)
                if dimension.exposure != "ever":
                    touched.add("prescriptions.end_date")
            case MedicationName():
                touched.update(_MEDICATION_COLUMNS)
                touched.add("medications.display")
                if dimension.exposure != "ever":
                    touched.add("prescriptions.end_date")
    return tuple(sorted(touched))


_OBSERVATION_COLUMNS: Final = frozenset(
    {
        "observations.code",
        "observations.unit",
        "observations.value_numeric",
        "observations.taken_at",
    }
)
_MEDICATION_COLUMNS: Final = frozenset(
    {
        "medications.code",
        "medication_annotations.attribute",
        "medication_annotations.value",
        "prescriptions.patient_id",
    }
)


def _touched_by(predicate: Predicate) -> set[str]:
    match predicate:
        case ObservationThreshold():
            return set(_OBSERVATION_COLUMNS)
        case MedicationAttribute():
            touched = set(_MEDICATION_COLUMNS)
            if predicate.exposure != "ever":
                touched.add("prescriptions.end_date")
            return touched
        case AgeThreshold():
            return {"patients.birth_date", "patients.death_date"}
        case VitalStatus():
            return {"patients.death_date"}
        case AnyOf() | AllOf():
            return {column for member in predicate.of for column in _touched_by(member)}
        case Not():
            return _touched_by(predicate.of)
        case Resolved():
            return _touched_by(predicate.predicate)
        case TermReference():
            return _unresolved(predicate)


def condition_for(predicate: Predicate, *, today: date) -> ColumnElement[bool]:
    """One predicate as a boolean expression correlated to `patients`."""
    match predicate:
        case ObservationThreshold():
            return _observation_condition(predicate)
        case MedicationAttribute():
            return _medication_condition(predicate, today=today)
        case AgeThreshold():
            return _age_condition(predicate, today=today)
        case VitalStatus():
            if predicate.status == "alive":
                return Patient.death_date.is_(None)
            return Patient.death_date.is_not(None)
        case AnyOf():
            return or_(*(condition_for(member, today=today) for member in predicate.of))
        case AllOf():
            return and_(*(condition_for(member, today=today) for member in predicate.of))
        case Not():
            return not_(condition_for(predicate.of, today=today))
        case Resolved():
            return condition_for(predicate.predicate, today=today)
        case TermReference():
            return _unresolved(predicate)


def _unresolved(predicate: TermReference) -> NoReturn:
    # A reference that reached the assembler is a loader bug, not a data
    # error: `definition_service` substitutes every one before a predicate is
    # handed out. Refusing here keeps the guarantee visible.
    message = (
        f"term reference {predicate.term!r} was never resolved; the vocabulary loader "
        "substitutes references before a predicate reaches the assembler"
    )
    raise InvalidPredicateError(message)


def _latest_value(codes: Sequence[str], units: Sequence[str]) -> Any:
    """Each patient's most recent numeric result for a code set, in listed units.

    A correlated scalar subquery rather than a window function: it reads as
    "their latest eGFR", and `observations_patient_code_taken_idx` serves the
    ORDER BY ... LIMIT 1 directly.

    `in_` across the code set, so the latest result wins whichever assay
    produced it — which is the current clinical picture, and the reason a
    single-code match would be wrong rather than merely narrow. Units are
    matched, never converted: a result in a unit the definition did not list
    is not this measurement.
    """
    return (
        select(Observation.value_numeric)
        .where(
            Observation.patient_id == Patient.id,
            Observation.code.in_(list(codes)),
            Observation.unit.in_(list(units)),
            Observation.value_numeric.is_not(None),
        )
        .order_by(Observation.taken_at.desc())
        .limit(1)
        .correlate(Patient)
        .scalar_subquery()
    )


def _observation_condition(predicate: ObservationThreshold) -> ColumnElement[bool]:
    compare = _COMPARE[predicate.operator]

    if predicate.most_recent:
        return compare(_latest_value(predicate.codes, predicate.units), predicate.value)

    # Only numeric results can be compared. A qualitative value sits in
    # `value_text` and is invisible here rather than being coerced into a
    # number, which is the quiet way a threshold query goes wrong.
    return exists(
        select(1)
        .where(
            Observation.patient_id == Patient.id,
            Observation.code.in_(predicate.codes),
            Observation.unit.in_(predicate.units),
            Observation.value_numeric.is_not(None),
            compare(Observation.value_numeric, predicate.value),
        )
        .correlate(Patient)
    )


def _exposure_condition(
    exposure: str, within_days: int | None, *, today: date
) -> ColumnElement[bool]:
    match exposure:
        case "active":
            return Prescription.end_date.is_(None)
        case "recent":
            # `within_days` is guaranteed present for this exposure by the
            # validator, so the cutoff cannot be None here.
            cutoff = today - timedelta(days=within_days or 0)
            return or_(Prescription.end_date.is_(None), Prescription.end_date >= cutoff)
        case _:
            return true()  # "ever" places no constraint on time


def _medication_condition(predicate: MedicationAttribute, *, today: date) -> ColumnElement[bool]:
    """Exposure to a drug carrying a curated annotation.

    The join runs prescription -> medication -> annotation — see
    `_join_medication_annotations` for why it goes through `code` rather
    than a foreign key, and what that costs.

    No `getattr` on a model here. `attribute` is a value compared inside the
    query, so there is no way for a definition to name a column at all.
    """
    return exists(
        _join_medication_annotations(select(1).select_from(Prescription))
        .where(
            Prescription.patient_id == Patient.id,
            MedicationAnnotation.attribute == predicate.attribute,
            MedicationAnnotation.value.in_(predicate.values),
            _exposure_condition(predicate.exposure, predicate.within_days, today=today),
        )
        .correlate(Patient)
    )


def _age_condition(predicate: AgeThreshold, *, today: date) -> ColumnElement[bool]:
    """Age derived at query time, never stored.

    Shares `age_expression` with the column list rather than recomputing it. If
    the filter and the displayed value ever diverged, the demo would return a
    patient whose shown age contradicts the filter that found them.

    Computed as `date_part('year', age(today, birth_date))` rather than
    inverted into a birth-date range. The inversion is faster — it can use an
    index on birth_date — but getting the direction backwards is a silent,
    plausible-looking bug, and at this cohort size the readable form costs
    nothing. Revisit if the table ever gets large.
    """
    return _COMPARE[predicate.operator](age_expression(today), predicate.value)


# ------------------------------------------------------- measures, dimensions


def _measure_expression(measure: Measure) -> ColumnElement[Any]:
    match measure:
        case PatientCount():
            # Distinct, so the one fan-out dimension counts people not rows.
            return func.count(func.distinct(Patient.id))
        case ObservationAggregate():
            latest = _latest_value(measure.codes, measure.units)
            match measure.aggregate:
                case "avg":
                    return func.round(func.avg(latest), 1)
                case "min":
                    return func.min(latest)
                case "max":
                    return func.max(latest)
                case _:
                    return func.percentile_cont(0.5).within_group(latest)


def _dimension_expression(
    dimension: Dimension, *, today: date, group: Any = None
) -> ColumnElement[Any]:
    match dimension:
        case PatientColumn():
            # From the same closed list the validator checked against, and
            # spelled out rather than `getattr`, for the reason columns.py gives.
            column = {
                "sex": Patient.sex,
                "race": Patient.race,
                "state": Patient.state,
            }[dimension.column]
            return func.coalesce(column, "unknown")
        case AgeBand():
            age = age_expression(today)
            whens = [(age < upto, label) for label, upto in dimension.bands if upto is not None]
            last_label = dimension.bands[-1][0]
            return case(*whens, else_=last_label)
        case MedicationGroup():
            if group is None:
                message = "a medication_group dimension needs its joined subquery"
                raise InvalidPredicateError(message)
            return group.c.value
        case MedicationName():
            message = (
                "a medication_name dimension groups medications, not patients — it needs "
                "medication_aggregate_query, not aggregate_query"
            )
            raise InvalidPredicateError(message)


def _medication_group_rows(dimension: MedicationGroup, *, today: date) -> Any:
    """Each (patient, annotation value) pair the dimension puts a patient in.

    Uncorrelated on purpose: it is joined to `patients` in the FROM clause, so
    a patient on drugs in two tiers appears twice — which is the fan-out
    `aggregate_query` guards against by admitting only a distinct count.
    """
    return (
        _join_medication_annotations(
            select(
                Prescription.patient_id.label("patient_id"),
                MedicationAnnotation.value.label("value"),
            ).select_from(Prescription)
        )
        .where(
            MedicationAnnotation.attribute == dimension.attribute,
            _exposure_condition(dimension.exposure, dimension.within_days, today=today),
        )
        .distinct()
        .subquery("medication_groups")
    )
