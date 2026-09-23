"""What is in the dataset, described without reading a single patient.

This answers the question the chat cannot: the model can say which *terms*
exist, because they are in its prompt, but it has no way to tell you there are
2,271 patients loaded from a Synthea export dated 2026-09-21, or which
medication-annotation tiers exist. `find_patients` is the only route to the
data and it returns patients matching predicates, not inventory.

**Nothing here selects a patient-identifying column.** Counts, dataset
provenance, the observation catalog, and the distinct annotation values — that
is the whole surface. `app/clinical/` is still the only place a clinical
*query* is assembled, and a structural test asserts this module never touches
`full_name`, `birth_date`, `ssn`, `drivers`, `passport` or `address`.

That distinction is why this is allowed to exist at all. "How many patients
are there, and where did they come from" is metadata about the dataset;
"which patients" is a clinical query and goes through the definitions layer
like everything else.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clinical.columns import IDENTIFYING, MAX_ROWS, SELECTABLE
from app.models import (
    DatasetMeta,
    Medication,
    MedicationAnnotation,
    Observation,
    ObservationCatalog,
    Patient,
    Prescription,
)


@dataclass(frozen=True)
class DatasetProvenance:
    """Which dataset is loaded, and when it thinks "now" is.

    Surfaced in the context panel — SEMANTIC_LAYER.md § 1 — because every age
    and every "currently prescribed" in every answer is relative to
    `as_of_date`, and that is silently wrong to a reader who cannot see it.
    """

    source: str
    as_of_date: date
    patient_count: int
    notes: str | None
    loaded_at: datetime


@dataclass(frozen=True)
class ObservationCatalogEntry:
    """One measured code, and how often it was measured."""

    code: str
    display: str
    category: str | None
    unit: str | None
    units: tuple[str, ...]
    observation_count: int
    patient_count: int
    is_numeric: bool


@dataclass(frozen=True)
class Catalog:
    """The shape of the dataset, for a reader deciding what to ask."""

    dataset: DatasetProvenance | None
    patients: int
    medications: int
    prescriptions: int
    observations: int
    observation_catalog: tuple[ObservationCatalogEntry, ...]
    # attribute (e.g. "nephrotoxic_risk") -> the distinct values it takes,
    # sorted. From medication_annotations — the curated review, not the drug
    # row, which the entity docstring in models.py explains the reason for.
    annotation_values: dict[str, tuple[str, ...]]
    returnable_columns: tuple[str, ...]
    restricted_columns: tuple[str, ...]
    max_rows: int


async def current_dataset(session: AsyncSession) -> DatasetProvenance | None:
    """Which dataset is loaded right now, or `None` before the first seed.

    `seed_service.clear_clinical_data` deletes every `DatasetMeta` row before
    a reload writes a fresh one, so there is never more than one — this is
    not "the most recent of several", it is "the one there is". Reused
    everywhere a clinical answer or a browsed page needs to cite where the
    rows it just showed came from — SEMANTIC_LAYER.md § 1's "answer" level of
    provenance — not just here for the context panel.
    """
    dataset_row = await session.scalar(
        select(DatasetMeta).order_by(DatasetMeta.loaded_at.desc()).limit(1)
    )
    if dataset_row is None:
        return None
    return DatasetProvenance(
        source=dataset_row.source,
        as_of_date=dataset_row.as_of_date,
        patient_count=dataset_row.patient_count,
        notes=dataset_row.notes,
        loaded_at=dataset_row.loaded_at,
    )


async def load_catalog(session: AsyncSession) -> Catalog:
    """Counts, provenance and reference values. Reads no patient-identifying column."""
    dataset = await current_dataset(session)

    patients = await session.scalar(select(func.count()).select_from(Patient)) or 0
    medications = await session.scalar(select(func.count()).select_from(Medication)) or 0
    prescriptions = await session.scalar(select(func.count()).select_from(Prescription)) or 0
    observations = await session.scalar(select(func.count()).select_from(Observation)) or 0

    catalog_rows = await session.execute(
        select(ObservationCatalog).order_by(ObservationCatalog.code)
    )
    observation_catalog = tuple(
        ObservationCatalogEntry(
            code=row.code,
            display=row.display,
            category=row.category,
            unit=row.unit,
            units=tuple(str(u) for u in row.units),
            observation_count=row.observation_count,
            patient_count=row.patient_count,
            is_numeric=row.is_numeric,
        )
        for row in catalog_rows.scalars().all()
    )

    annotation_rows = await session.execute(
        select(MedicationAnnotation.attribute, MedicationAnnotation.value).distinct()
    )
    annotation_values: dict[str, set[str]] = {}
    for attribute, value in annotation_rows.all():
        annotation_values.setdefault(attribute, set()).add(value)

    return Catalog(
        dataset=dataset,
        patients=patients,
        medications=medications,
        prescriptions=prescriptions,
        observations=observations,
        observation_catalog=observation_catalog,
        annotation_values={
            attribute: tuple(sorted(values)) for attribute, values in annotation_values.items()
        },
        returnable_columns=SELECTABLE,
        restricted_columns=IDENTIFYING,
        max_rows=MAX_ROWS,
    )


async def list_patient_states(session: AsyncSession) -> tuple[str, ...]:
    """Distinct patient states, sorted.

    `state` is not identifying — it is on `SELECTABLE`, freely returnable —
    and this exists so a row-level access scope
    (`app/services/authz_service.py`'s `scope_states`) can be set to a real
    value from the loaded dataset rather than a guess at all fifty. Same
    argument this module already makes for drug tiers and observation codes:
    ask the data, not a static list.
    """
    rows = await session.execute(
        select(Patient.state).where(Patient.state.is_not(None)).distinct().order_by(Patient.state)
    )
    return tuple(str(state) for state in rows.scalars().all())
