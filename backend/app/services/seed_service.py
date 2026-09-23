"""Loading the clinical dataset from a Synthea export.

The data comes from three places and this module is the only thing that
writes any of it:

- `app/seed/synthea.py` reads the generated population — patients,
  prescriptions, observations — and has no opinion about it.
- `app/seed/annotations.py` is the curated review of which drugs carry kidney
  risk; matching runs here, once per load, and what persists is a row per
  code with its rationale.
- `app/seed/reference_data.py` is the clinical definitions, written through
  `definition_service` so they get the same validation and the same history
  row as a definition somebody types into the editor.

It is a service rather than a script because two callers already want it:
`python -m app.seed`, and the integration tests, which load the fixture under
`tests/support/synthea/` through exactly this code.

Every function takes an explicit `session`, like every other service.

**`query_audit` is never touched here.** Not on seed, not on reset. An audit
log that a maintenance command can empty is not an audit log, and the one
command most likely to be run carelessly is the one that reloads demo data.
The definitions' history is left alone for the same reason: a reload writes
new `created` rows, and the old ones stay.
"""

import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEV_USER_ID
from app.logging import get_logger
from app.models import (
    DatasetMeta,
    Medication,
    MedicationAnnotation,
    Observation,
    ObservationCatalog,
    Patient,
    Prescription,
)
from app.seed import annotations, reference_data, synthea
from app.seed.synthea import SourceObservation
from app.services import authz_service, definition_service

logger = get_logger(__name__)

# Rows per INSERT. Large enough that a million observations is a few hundred
# statements, small enough that one statement is not a memory spike.
CHUNK = 5_000

SEED_ACTOR = "seed"


@dataclass(frozen=True)
class SeedSummary:
    """What a seed run did. Counts, so it can be logged and asserted on."""

    patients: int
    medications: int
    annotations: int
    prescriptions: int
    observations: int
    catalog_codes: int
    definitions: int
    as_of_date: date | None
    skipped: bool


async def is_seeded(session: AsyncSession) -> bool:
    """True when a dataset is already loaded."""
    count = await session.scalar(select(func.count()).select_from(DatasetMeta))
    return bool(count)


async def clear_clinical_data(session: AsyncSession) -> None:
    """Delete the loaded dataset. Leaves `query_audit` alone — see the module docstring.

    Order matters: `prescriptions.medication_id` is ON DELETE RESTRICT, so the
    join rows go before the drugs they point at. Definitions are deleted
    through the service so each one gets a `deleted` history row rather than
    vanishing.
    """
    for model in (
        Prescription,
        Observation,
        Patient,
        Medication,
        MedicationAnnotation,
        ObservationCatalog,
        DatasetMeta,
    ):
        await session.execute(delete(model))
    await session.commit()

    for row in await definition_service.list_definitions(session, include_unpublished=True):
        await definition_service.delete_definition(
            session,
            definition=row,
            changed_by=SEED_ACTOR,
            change_reason="dataset reset; reloading from reference_data.py",
        )

    # The definitions cache would otherwise serve terms whose rows no longer
    # exist, which is the one way a TTL cache of reference data goes wrong.
    definition_service.invalidate()
    logger.info("clinical data cleared")


async def seed_all(session: AsyncSession, *, source: Path, reset: bool = False) -> SeedSummary:
    """Load a Synthea export. A no-op if a dataset is already there, unless `reset`.

    Not an upsert. Loading the same export twice would produce identical rows
    under new ids, which breaks nothing except any id in a saved answer.
    Reloading is an explicit choice.
    """
    if await is_seeded(session):
        if not reset:
            logger.info("seed skipped", reason="already seeded")
            return SeedSummary(0, 0, 0, 0, 0, 0, 0, None, skipped=True)
        await clear_clinical_data(session)

    logger.info("seed started", source=str(source))

    patients = synthea.read_patients(source)
    patient_ids = await _insert_patients(session, patients)

    prescriptions = synthea.read_prescriptions(source)
    medication_ids = await _insert_medications(session, prescriptions)
    annotated = await _insert_annotations(session, medication_ids)
    prescription_count = await _insert_prescriptions(
        session, prescriptions, patient_ids, medication_ids
    )

    observation_count, catalog, latest = await _insert_observations(
        session, synthea.iter_observations(source), patient_ids
    )
    await _insert_catalog(session, catalog)

    as_of = synthea.as_of_date(prescriptions, latest)
    session.add(
        DatasetMeta(
            source=f"Synthea CSV export ({source.name})",
            as_of_date=as_of,
            patient_count=len(patients),
            notes=(
                f"Loaded from {source}. Observations restricted to nothing: every row the "
                "export carries is here, and the catalog says which codes were measured."
            ),
        )
    )
    await session.commit()

    definitions = await _insert_definitions(session)
    await authz_service.ensure_dev_user(session, user_id=DEV_USER_ID)

    summary = SeedSummary(
        patients=len(patients),
        medications=len(medication_ids),
        annotations=annotated,
        prescriptions=prescription_count,
        observations=observation_count,
        catalog_codes=len(catalog),
        definitions=definitions,
        as_of_date=as_of,
        skipped=False,
    )
    logger.info(
        "seed complete",
        patients=summary.patients,
        medications=summary.medications,
        annotations=summary.annotations,
        prescriptions=summary.prescriptions,
        observations=summary.observations,
        catalog_codes=summary.catalog_codes,
        definitions=summary.definitions,
        as_of_date=str(as_of),
    )
    return summary


# ------------------------------------------------------------------ writers


async def _insert_patients(
    session: AsyncSession, patients: list[synthea.SourcePatient]
) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for chunk in _chunks(patients):
        # Assigned up front, typed, rather than read back out of the mixed-type
        # row dicts below — a dict of str | date | UUID | None values loses the
        # per-column type the moment it is built.
        chunk_ids: dict[str, uuid.UUID] = {p.source_id: uuid.uuid4() for p in chunk}
        rows = [
            {
                "id": chunk_ids[p.source_id],
                "source_id": p.source_id,
                "full_name": p.full_name,
                "birth_date": p.birth_date,
                "death_date": p.death_date,
                "sex": p.sex,
                "race": p.race,
                "ethnicity": p.ethnicity,
                "state": p.state,
                "city": p.city,
                "ssn": p.ssn,
                "drivers": p.drivers,
                "passport": p.passport,
                "address": p.address,
            }
            for p in chunk
        ]
        await session.execute(insert(Patient), rows)
        ids.update(chunk_ids)
    await session.commit()
    return ids


async def _insert_medications(
    session: AsyncSession, prescriptions: list[synthea.SourcePrescription]
) -> dict[str, uuid.UUID]:
    """One row per distinct code. The commonest display wins a tie."""
    displays: dict[str, Counter[str]] = defaultdict(Counter)
    for p in prescriptions:
        displays[p.code][p.display] += 1

    code_ids: dict[str, uuid.UUID] = {code: uuid.uuid4() for code in displays}
    rows = [
        {
            "id": code_ids[code],
            "code": code,
            "system": synthea.MEDICATION_SYSTEM,
            "display": names.most_common(1)[0][0],
        }
        for code, names in sorted(displays.items())
    ]
    for chunk in _chunks(rows):
        await session.execute(insert(Medication), chunk)
    await session.commit()
    return code_ids


async def _insert_annotations(session: AsyncSession, medication_ids: dict[str, uuid.UUID]) -> int:
    """Run the curated review over every distinct drug and persist its verdicts."""
    result = await session.execute(select(Medication.code, Medication.display))
    patterns = [
        (re.compile(p, re.IGNORECASE), tier, why)
        for p, tier, why in annotations.NEPHROTOXIC_PATTERNS
    ]

    rows: list[dict[str, Any]] = []
    for code, display in result.all():
        if code not in medication_ids:
            continue
        for pattern, tier, rationale in patterns:
            if pattern.search(display):
                rows.append(
                    {
                        "code": code,
                        "system": synthea.MEDICATION_SYSTEM,
                        "attribute": annotations.NEPHROTOXIC_RISK,
                        "value": tier,
                        "rationale": rationale,
                    }
                )
                break  # first match wins; the list runs highest risk first
    if rows:
        await session.execute(insert(MedicationAnnotation), rows)
    await session.commit()
    return len(rows)


async def _driver_connection(session: AsyncSession) -> Any:
    """This session's live asyncpg connection, for driver features (`COPY`)
    SQLAlchemy's `Connection` does not wrap. Still the same connection and
    the same open transaction as everything else `session` has done —
    `get_raw_connection` does not open a second one."""
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    return raw.driver_connection


PRESCRIPTION_COPY_COLUMNS: Final = (
    "patient_id",
    "medication_id",
    "start_date",
    "end_date",
    "reason_display",
)


async def _insert_prescriptions(
    session: AsyncSession,
    prescriptions: list[synthea.SourcePrescription],
    patient_ids: dict[str, uuid.UUID],
    medication_ids: dict[str, uuid.UUID],
) -> int:
    """`COPY`, not batched `INSERT` — see `_insert_observations`. Six figures
    of rows in the full export, same fix, same reason."""
    rows = [
        (
            patient_ids[p.patient_source_id],
            medication_ids[p.code],
            p.start_date,
            p.end_date,
            p.reason_display,
        )
        for p in prescriptions
        if p.patient_source_id in patient_ids
    ]
    if not rows:
        return 0
    asyncpg_connection = await _driver_connection(session)
    await asyncpg_connection.copy_records_to_table(
        "prescriptions", records=rows, columns=PRESCRIPTION_COPY_COLUMNS
    )
    await session.commit()
    return len(rows)


@dataclass
class _CatalogEntry:
    display: Counter[str]
    units: Counter[str]
    category: Counter[str]
    observations: int = 0
    patients: set[str] | None = None
    numeric: int = 0


OBSERVATION_COPY_COLUMNS: Final = (
    "patient_id",
    "category",
    "code",
    "system",
    "display",
    "value_numeric",
    "value_text",
    "unit",
    "taken_at",
)


async def _insert_observations(
    session: AsyncSession,
    observations: Iterable[SourceObservation],
    patient_ids: dict[str, uuid.UUID],
) -> tuple[int, dict[str, _CatalogEntry], date | None]:
    """Stream observations straight into Postgres with `COPY`, building the
    catalog as they pass.

    **Not `INSERT`, even batched.** A batched `execute(insert(...), rows)` is
    still one parsed, planned statement per batch — correct, and what made a
    1.77M-row load take minutes even at `CHUNK=5_000`, which is what every
    integration test's reseed was paying, every test, all session. `COPY` is
    the wire protocol built for exactly this: no per-row statement, no
    per-batch round trip, just a stream. `asyncpg` exposes it as
    `copy_records_to_table`, which is not something SQLAlchemy's `Connection`
    wraps — it needs the driver's own connection object, reached through
    `get_raw_connection().driver_connection`, a documented SQLAlchemy asyncio
    escape hatch for exactly this class of driver-specific feature.

    Still one transaction: `driver_connection` is *this session's* live
    DBAPI connection, not a second one, so `COPY` runs inside whatever
    transaction the session already has open and `session.commit()` below
    still closes it.

    The catalog is a by-product of the load rather than a second pass over
    the file: a second pass over a million rows is a minute for nothing.
    `copy_records_to_table` accepts any iterable of row tuples, so the
    catalog bookkeeping and the row-building both happen inside the one
    generator it streams from — a second, materialised list here would give
    back the memory `COPY` is supposed to save.
    """
    catalog: dict[str, _CatalogEntry] = {}
    latest: date | None = None
    count = 0

    def rows() -> Iterable[tuple[Any, ...]]:
        nonlocal latest, count
        for o in observations:
            patient_id = patient_ids.get(o.patient_source_id)
            if patient_id is None:
                continue
            entry = catalog.get(o.code)
            if entry is None:
                entry = catalog[o.code] = _CatalogEntry(
                    Counter(), Counter(), Counter(), patients=set()
                )
            entry.display[o.display] += 1
            if o.unit:
                entry.units[o.unit] += 1
            if o.category:
                entry.category[o.category] += 1
            entry.observations += 1
            if entry.patients is not None:
                entry.patients.add(o.patient_source_id)
            if o.value_numeric is not None:
                entry.numeric += 1

            taken = o.taken_at.date()
            latest = taken if latest is None or taken > latest else latest

            count += 1
            if count % 200_000 == 0:
                logger.info("observations loading", loaded=count)

            yield (
                patient_id,
                o.category,
                o.code,
                synthea.OBSERVATION_SYSTEM,
                o.display,
                o.value_numeric,
                o.value_text,
                o.unit,
                o.taken_at,
            )

    asyncpg_connection = await _driver_connection(session)
    await asyncpg_connection.copy_records_to_table(
        "observations", records=rows(), columns=OBSERVATION_COPY_COLUMNS
    )
    await session.commit()
    return count, catalog, latest


async def _insert_catalog(session: AsyncSession, catalog: dict[str, _CatalogEntry]) -> None:
    rows = [
        {
            "code": code,
            "system": synthea.OBSERVATION_SYSTEM,
            "display": entry.display.most_common(1)[0][0],
            "category": entry.category.most_common(1)[0][0] if entry.category else None,
            "unit": entry.units.most_common(1)[0][0] if entry.units else None,
            "units": [unit for unit, _ in entry.units.most_common()],
            "observation_count": entry.observations,
            "patient_count": len(entry.patients or ()),
            # Numeric if any row was: a code that is usually a number and
            # occasionally text is still one a threshold can read.
            "is_numeric": entry.numeric > 0,
        }
        for code, entry in sorted(catalog.items())
    ]
    for chunk in _chunks(rows):
        await session.execute(insert(ObservationCatalog), chunk)
    await session.commit()


async def _insert_definitions(session: AsyncSession) -> int:
    """Write the reference definitions through the same path an editor uses.

    So they are validated the same way, get a `created` history row, and a
    reference row that no longer parses fails the seed loudly rather than
    landing as a term nothing can resolve.
    """
    for row in reference_data.CLINICAL_DEFINITIONS:
        await definition_service.create_definition(
            session,
            term=row["term"],
            kind=row["kind"],
            entity=row["entity"],
            description=row["description"],
            logic=row["logic"],
            notes=row["notes"],
            synonyms=list(row["synonyms"]),
            invariants=list(row.get("invariants", [])),
            changed_by=SEED_ACTOR,
            change_reason="seeded from app/seed/reference_data.py",
            owner=SEED_ACTOR,
        )
    return len(reference_data.CLINICAL_DEFINITIONS)


def _chunks[T](items: list[T]) -> Iterable[list[T]]:
    for start in range(0, len(items), CHUNK):
        yield items[start : start + CHUNK]
