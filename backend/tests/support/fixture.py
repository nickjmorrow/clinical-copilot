"""The committed test fixture — a small, deterministic subset of a real
Synthea export.

Built by `scripts/build-test-fixture.py`, which documents each anchor patient
and why it earned a place (found by querying the live-seeded dev database,
not designed). Read here rather than recomputed per test file, so every
suite that seeds from the fixture pins the same `today`.
"""

from datetime import date
from pathlib import Path

FIXTURE_SOURCE = Path(__file__).resolve().parent / "synthea"

# The fixture's own as-of date: the latest observation/prescription date
# among its 111 patients. One day earlier than the full export's
# (2026-09-21), because the subset does not happen to include whichever
# patient contributed that final day — the same reason `dataset_meta.
# as_of_date` is derived per load rather than assumed. Pinned here rather
# than read back from the database by every test, for the same reason the
# old `SEED_TODAY` existed: an age-dependent expected answer must not drift
# with the wall clock.
FIXTURE_TODAY = date(2026, 9, 20)

# Anchors from scripts/build-test-fixture.py's ANCHORS dict, named here so a
# test reads `RUNNING_EXAMPLE_CORE` rather than a bare UUID with a comment
# repeating what the script already documented in full.
RUNNING_EXAMPLE_CORE = "00477fd7-f01f-8e60-3f2d-f295431de5dc"
RUNNING_EXAMPLE_MODERATE = "074b4461-241b-cd2f-9f7b-b9e7bdcc4cc7"
RUNNING_EXAMPLE_NOT_SEVERE = "07582daa-18ad-0191-6328-83612743e81c"
EXCLUDED_COURSE_ENDED_DECEASED = "00c85a50-8585-bea5-0c70-b15725c2ccef"
EXCLUDED_COURSE_ENDED_ALIVE = "02325e00-0da1-5030-07c3-d6a2fe2c5c46"
CONTEXTUAL_SEVERE_ALIVE = "0409a669-1df2-c48b-3ec6-4c410e8b5152"
UNMEASURED_EGFR_HIGH_TIER_EVER = "0fcb02a6-4a68-49da-7a30-f16fb4c53e15"
RECENT_EXPOSURE_NOT_ACTIVE = "11184316-f78c-e3d9-4168-1b9d59091946"
ELDERLY_HIGH_RISK_NO_RENAL = "4eabfa47-5f30-b37b-8983-1eb95f44d700"
CONTROL_ONE = "0052e4b1-8e5b-f4f0-69ab-05f87db22664"
CONTROL_TWO = "00d0b8ca-e6cf-5147-92b5-64a8618f8eba"
