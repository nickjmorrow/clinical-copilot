"""Reading a Synthea CSV export.

Synthea (MITRE) is an open-source patient simulator. Pointed at a directory
its CSV exporter wrote, this module reads three of the files it produces —
`patients.csv`, `medications.csv`, `observations.csv` — into plain dataclasses
that `services/seed_service.py` writes to the canonical tables.

**Pure.** Nothing here touches a database, and nothing here has an opinion
about the data. A drug is a code and a name; whether it is nephrotoxic is
decided elsewhere (`annotations.py`), and which measurements matter is decided
by the definitions rows. This module's only judgement is how to spell Synthea's
columns in ours.

Two properties worth keeping:

**Observations stream.** A 2,000-patient population produces close to a
million observation rows, and a list of them is a memory spike for nothing —
the writer inserts in chunks anyway. `iter_observations` yields.

**The fixture is the same format.** `tests/support/synthea/` is a subset of a
real export, gzipped, and it is read by exactly this code. A test fixture in a
format of its own would be a second loader that only exists to be tested.

Every identifier Synthea issues — SSN, driving licence, passport, name,
address — is read and kept. The column-level access rule in
`app/clinical/columns.py` is what keeps them out of an answer, and it can
only be demonstrated against a schema that has something to withhold.
"""

import csv
import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO

# The coding systems Synthea uses for these files. Recorded on every row so a
# dataset that mixes systems — or a loader for a source that codes drugs in
# something other than RxNorm — has somewhere honest to say so.
OBSERVATION_SYSTEM = "http://loinc.org"
MEDICATION_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"

_SEX = {"M": "male", "F": "female"}


@dataclass(frozen=True)
class SourcePatient:
    source_id: str
    full_name: str
    birth_date: date
    death_date: date | None
    sex: str
    race: str | None
    ethnicity: str | None
    state: str | None
    city: str | None
    ssn: str | None
    drivers: str | None
    passport: str | None
    address: str | None


@dataclass(frozen=True)
class SourcePrescription:
    patient_source_id: str
    code: str
    display: str
    start_date: date
    end_date: date | None
    reason_display: str | None


@dataclass(frozen=True)
class SourceObservation:
    patient_source_id: str
    category: str | None
    code: str
    display: str
    value_numeric: Decimal | None
    value_text: str | None
    unit: str | None
    taken_at: datetime


class SyntheaExportError(ValueError):
    """The directory is not a Synthea CSV export, or a file in it is malformed."""


def open_csv(directory: Path, name: str) -> IO[str]:
    """`name.csv` or `name.csv.gz`, whichever is there. Raises if neither."""
    plain = directory / f"{name}.csv"
    if plain.exists():
        return plain.open(newline="", encoding="utf-8")
    zipped = directory / f"{name}.csv.gz"
    if zipped.exists():
        return gzip.open(zipped, mode="rt", newline="", encoding="utf-8")
    message = f"no {name}.csv or {name}.csv.gz in {directory}; is this a Synthea CSV export?"
    raise SyntheaExportError(message)


def read_patients(directory: Path) -> list[SourcePatient]:
    with open_csv(directory, "patients") as handle:
        rows = csv.DictReader(handle)
        return [_patient(row) for row in rows]


def read_prescriptions(directory: Path) -> list[SourcePrescription]:
    with open_csv(directory, "medications") as handle:
        prescriptions = [_prescription(row) for row in csv.DictReader(handle)]
    return [p for p in prescriptions if p is not None]


def iter_observations(directory: Path) -> Iterator[SourceObservation]:
    with open_csv(directory, "observations") as handle:
        for row in csv.DictReader(handle):
            observation = _observation(row)
            if observation is not None:
                yield observation


def as_of_date(prescriptions: list[SourcePrescription], latest_observation: date | None) -> date:
    """The dataset's own "today": the newest date anything in it records.

    A generated cohort is frozen at whenever the generator stopped. Ages and
    recency computed against the wall clock instead would drift away from the
    data as months pass, so every age in every answer is relative to this.
    """
    candidates = [latest_observation] if latest_observation else []
    candidates.extend(p.end_date or p.start_date for p in prescriptions)
    if not candidates:
        message = "the export has no dated records, so no as-of date can be derived"
        raise SyntheaExportError(message)
    return max(candidates)


# ------------------------------------------------------------- row parsing


def _patient(row: dict[str, str]) -> SourcePatient:
    sex = _SEX.get(row.get("GENDER", ""), "unknown")
    name = " ".join(part for part in (row.get("FIRST", ""), row.get("LAST", "")) if part)
    return SourcePatient(
        source_id=_required(row, "Id"),
        full_name=name or "unnamed",
        birth_date=_date(_required(row, "BIRTHDATE")),
        death_date=_date(row["DEATHDATE"]) if row.get("DEATHDATE") else None,
        sex=sex,
        race=_blank(row.get("RACE")),
        ethnicity=_blank(row.get("ETHNICITY")),
        state=_blank(row.get("STATE")),
        city=_blank(row.get("CITY")),
        ssn=_blank(row.get("SSN")),
        drivers=_blank(row.get("DRIVERS")),
        passport=_blank(row.get("PASSPORT")),
        address=_blank(row.get("ADDRESS")),
    )


def _prescription(row: dict[str, str]) -> SourcePrescription | None:
    start = _date(_required(row, "START"))
    end = _date(row["STOP"]) if row.get("STOP") else None
    if end is not None and end < start:
        # A known Synthea quirk, not a mapping bug on this side: about one row
        # in 2,500 in a generated export has STOP before START, almost always
        # from an end-of-life or transplant encounter where several drugs on
        # the same encounter share one (reversed) pair of timestamps. The
        # schema's `prescriptions_date_order_check` would refuse the row
        # outright, so it is skipped here instead — the same choice
        # `_observation` makes for a row with no value, and for the same
        # reason: one malformed row in an export is not worth failing the
        # whole load over.
        return None
    return SourcePrescription(
        patient_source_id=_required(row, "PATIENT"),
        code=_required(row, "CODE"),
        display=_required(row, "DESCRIPTION"),
        start_date=start,
        end_date=end,
        reason_display=_blank(row.get("REASONDESCRIPTION")),
    )


def _observation(row: dict[str, str]) -> SourceObservation | None:
    raw = row.get("VALUE", "")
    numeric = _decimal(raw) if row.get("TYPE") == "numeric" else None
    text = None if numeric is not None else _blank(raw)
    if numeric is None and text is None:
        # A row with no value is a row that measured nothing. The schema
        # refuses it (observations_has_a_value_check), so it is skipped here
        # rather than failing the whole load on the one row Synthea left blank.
        return None
    return SourceObservation(
        patient_source_id=_required(row, "PATIENT"),
        category=_blank(row.get("CATEGORY")),
        code=_required(row, "CODE"),
        display=_required(row, "DESCRIPTION"),
        value_numeric=numeric,
        value_text=text,
        unit=_blank(row.get("UNITS")),
        taken_at=_timestamp(_required(row, "DATE")),
    )


def _required(row: dict[str, str], column: str) -> str:
    value = row.get(column, "").strip()
    if not value:
        message = f"a row is missing {column!r}; the export is malformed"
        raise SyntheaExportError(message)
    return value


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _timestamp(value: str) -> datetime:
    # Synthea writes `2016-10-07T23:08:12Z`; `fromisoformat` accepts the Z from
    # 3.11 on. A date-only value is midnight UTC, stated rather than naive.
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
