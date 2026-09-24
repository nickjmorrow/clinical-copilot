"""Which columns an answer may contain.

Column-level access control, plus the semantic binding that makes a
hallucinated column name a refusal rather than a database error. Both live here
because they are the same check: a column is either on the allowlist or the
query does not run.

**The allowlist is code, not a table.** A restriction that can be lifted by a
database write is not a restriction — and the row that lifts it is exactly the
kind of thing a seeding script or a careless migration does by accident. The
only way to widen this is a commit.

**Denied, not redacted.** A request for `full_name` is refused with a reason,
not silently answered without it. Quietly dropping a requested column answers a
different question from the one asked, and the caller cannot tell — which is
the same failure mode as dropping a filter.

Age is the point of the design. It is derived from `birth_date` at query
time and is freely available, while `birth_date` itself is withheld. That is
what lets "now just the ones over 65" be answered without the answer carrying a
date of birth, and it is the concrete thing to show when someone asks what
column-level control buys.
"""

from collections.abc import Collection, Sequence
from datetime import date
from typing import Any, Final

from sqlalchemy import ColumnElement, func

from app.models import Patient

# Everything that may ever appear in an answer, mapped from the name a caller
# uses to the column it means. A name not in here does not resolve, which is
# the semantic-binding check: the model cannot invent `ssn` and reach the
# database with it.
#
# An explicit map rather than `getattr(Patient, name)`. The exposed names are
# no longer the column names — `patient_id` is `source_id`, `age` is derived
# from `birth_date` and is not a column at all — and spelling the mapping out
# removes the last place a caller-supplied string chose an attribute.
SELECTABLE: Final = ("patient_id", "age", "sex", "race", "state")

# On the allowlist, but withheld unless the asker's role is explicitly
# permitted — see `ROLE_IDENTIFYING_COLUMNS` below.
#
# Longer than it used to be, because Synthea issues more identifiers than the
# hand-rolled data did: a social security number, a driving licence and a
# passport alongside the name, birth date and street address. Every one of
# them is loaded and none is returnable — a rule that only holds because the
# sensitive column was never imported is not a rule.
IDENTIFYING: Final = ("full_name", "birth_date", "ssn", "drivers", "passport", "address")

# Which identifying columns each role may additionally see, beyond the
# baseline every role already gets from `SELECTABLE`. Empty for every role
# today — deliberately: this codebase's whole argument for column-level
# control is that identifying data stays withheld by default (see this
# module's own docstring), and that argument does not change just because the
# check is now per-role instead of a single global switch. What changes is
# that granting a real role a specific column later is a one-line edit here,
# not a new mechanism — plain role-name strings rather than an import from
# `authz_service`, because `clinical/` sits below `services/` in the import
# order (AGENTS.md's "Which direction imports run") and may not reach up for
# `authz_service.ROLES`.
ROLE_IDENTIFYING_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "analyst": (),
    "curator": (),
    "auditor": (),
}

# What an answer returns when nothing specific was asked for. `patient_id` is
# included because an answer a clinician cannot act on is not an answer: they
# need to know *which* patients. It identifies a person, which is why every row
# returned is recorded in query_audit.
DEFAULT_COLUMNS: Final = ("patient_id", "age", "sex")

MAX_ROWS: Final = 200


class ColumnAccessError(Exception):
    """A column was requested that does not exist, or may not be returned."""

    def __init__(self, denied: Sequence[str], reason: str) -> None:
        self.denied = tuple(denied)
        self.reason = reason
        super().__init__(reason)


def age_expression(today: date) -> ColumnElement[Any]:
    """Age in whole years, derived at query time.

    The single definition of what age means here. The assembler filters on this
    and the column list displays it, and if those two ever disagreed the demo
    would return a patient whose shown age contradicts the filter that found
    them.

    `today` is the dataset's as-of date, not the wall clock. A generated cohort
    is frozen at whenever the generator stopped, so ageing it against real time
    would make "over 65" mean something different every month while the data
    never changed.

    A deceased patient's age is their age at death. Ageing the dead against
    the as-of date would put a patient who died at 70 in 1998 into `elderly`
    at 98, which is a row in an answer that a clinician would rightly stop
    trusting the whole answer over.
    """
    return func.date_part(
        "year", func.age(func.coalesce(Patient.death_date, today), Patient.birth_date)
    )


def resolve_columns(
    requested: Sequence[str] | None,
    *,
    today: date,
    roles: Collection[str] = (),
) -> tuple[list[ColumnElement[Any]], tuple[str, ...]]:
    """Map requested column names to expressions. Raises `ColumnAccessError`.

    Returns the expressions and the names they correspond to, in the order
    asked for, so the caller can label rows without a second lookup.

    `roles` is the asker's roles (`Asker.roles`), not a permission the caller
    asserts — the same discipline `scope_states` already follows. A caller
    with no roles, or none of the identifying tier's, sees exactly what a
    caller with `roles=()` always saw here: denied.
    """
    names = tuple(requested) if requested else DEFAULT_COLUMNS

    unknown = [name for name in names if name not in SELECTABLE and name not in IDENTIFYING]
    if unknown:
        message = (
            f"no such column(s): {unknown}. Available: {list(SELECTABLE)}. "
            "Age is derived from the date of birth and can be used instead of it."
        )
        raise ColumnAccessError(unknown, message)

    permitted = permitted_identifying_columns(roles)
    denied = [name for name in names if name in IDENTIFYING and name not in permitted]
    if denied:
        message = (
            f"column(s) {denied} contain direct patient identifiers and are not returned "
            "by this tool. Ask for `age` rather than `birth_date`; `patient_id` identifies "
            "a patient for follow-up without returning their name."
        )
        raise ColumnAccessError(denied, message)

    return [_expression(name, today=today) for name in names], names


def permitted_identifying_columns(roles: Collection[str]) -> frozenset[str]:
    """Every identifying column any of `roles` is permitted to see.

    A caller with two roles gets the union, the same way `resolve_columns`'s
    own semantic-binding check treats a requested name as permitted if any
    role on the asker grants it — a curator who is also an auditor is not
    made more restricted by holding a second role.
    """
    permitted: set[str] = set()
    for role in roles:
        permitted.update(ROLE_IDENTIFYING_COLUMNS.get(role, ()))
    return frozenset(permitted)


# Exposed name -> the column behind it. `age` is absent because it is derived
# rather than stored, which is the whole point of it being available while
# `birth_date` is not.
_COLUMNS: Final[dict[str, Any]] = {
    "patient_id": Patient.source_id,
    "sex": Patient.sex,
    "race": Patient.race,
    "state": Patient.state,
    "full_name": Patient.full_name,
    "birth_date": Patient.birth_date,
    "ssn": Patient.ssn,
    "drivers": Patient.drivers,
    "passport": Patient.passport,
    "address": Patient.address,
}


def _expression(name: str, *, today: date) -> ColumnElement[Any]:
    if name == "age":
        return age_expression(today).label("age")
    column: ColumnElement[Any] = _COLUMNS[name]
    return column.label(name)
