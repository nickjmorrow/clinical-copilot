#!/usr/bin/env python3
"""Filter the full Synthea export down to a small, committed test fixture.

`backend/data/synthea/csv/` (390MB, gitignored, reproduced by
`scripts/generate-synthea.sh`) is too big to commit and too slow to seed on
every test run. This script filters `patients.csv`, `medications.csv` and
`observations.csv` down to a fixed, small set of patients and gzips the
result into `backend/tests/support/synthea/`, read by the same
`app/seed/synthea.py` loader — a subset in the same format rather than a
fixture format of its own.

The patient set is two things concatenated, not one:

**The anchors** — found by querying the live-seeded dev database for
patients who actually sit on a specific edge (running example, contextual
tier, unmeasured eGFR, high-tier-but-not-active, ...), the way
SEMANTIC_LAYER.md asks for: found, not designed. Each one is documented below
with the real evidence that earned it a place, because a future reader
re-picking anchors needs to know what each one was *for*, not just that it
matched a query once.

**~100 random patients** — so aggregate counts (`elderly`, `living`, and any
future measure/dimension) have a real background population rather than
being entirely anchor-shaped. Picked with a fixed seed so the fixture is
reproducible from `patients.csv` alone, without needing the database again.

Run from the repo root:

    cd backend && uv run python ../scripts/build-test-fixture.py

Then `python -m app.seed --from tests/support/synthea --reset` (against a
test database) gets you real counts for the fixture specifically — the
numbers the integration tests assert against.
"""

import csv
import gzip
import random
from pathlib import Path

# source_id -> why this patient earned a place, with the evidence that was
# actually queried for it (today = the dataset's as-of date, 2026-09-21).
ANCHORS: dict[str, str] = {
    "00477fd7-f01f-8e60-3f2d-f295431de5dc": (
        "Running example core. eGFR 6.7 mL/min (severe), on naproxen (moderate, "
        "active) and lisinopril+valsartan (contextual, active) — matches "
        "`impaired renal function`, `severely impaired renal function`, "
        "`nephrotoxic medication`, `renin-angiotensin blocker` all at once. "
        "Deceased 2018-12-29, so also the `living` filter's exclusion case."
    ),
    "074b4461-241b-cd2f-9f7b-b9e7bdcc4cc7": (
        "Running example. eGFR 11.3 (severe), tacrolimus (moderate) active. "
        "Deceased 2012-04-12."
    ),
    "07582daa-18ad-0191-6328-83612743e81c": (
        "Running example, impaired but NOT severe. eGFR 42.3 (<60 but >=30), "
        "naproxen (moderate) active. Deceased 2007-05-17. Proves the two renal "
        "terms nest rather than cross."
    ),
    "00c85a50-8585-bea5-0c70-b15725c2ccef": (
        "Excluded from the running example on purpose. eGFR 9.1 (severe), but "
        "the one nephrotoxic-tier prescription (ibuprofen, moderate) ended in "
        "1996 — neither `active` nor `recent` (730d). Matches `not on a "
        "nephrotoxin` despite once having taken one. Deceased 2006-10-18."
    ),
    "02325e00-0da1-5030-07c3-d6a2fe2c5c46": (
        "Same exclusion shape as the row above (eGFR 7.6, ibuprofen ended "
        "2020-05-21 — outside the 730-day recent window as of 2026-09-21) but "
        "ALIVE, so `living` ∩ `severely impaired renal function` ∩ "
        "`not on a nephrotoxin` has a real match."
    ),
    "0409a669-1df2-c48b-3ec6-4c410e8b5152": (
        "eGFR 7.4 (severe), losartan (contextual) active, alive, age 62 (not "
        "elderly). `renin-angiotensin blocker` ∩ severe impairment, "
        "without the elderly/deceased confound."
    ),
    "0fcb02a6-4a68-49da-7a30-f16fb4c53e15": (
        "No eGFR ever recorded — excluded entirely from `impaired renal "
        "function`, and the anchor for `_unmeasured_counts`. Vancomycin (high "
        "tier) ended 2020: matches `high-risk nephrotoxic medication` "
        "(exposure=ever ignores end_date) but not the active-exposure terms. "
        "Alive, age 51."
    ),
    "11184316-f78c-e3d9-4168-1b9d59091946": (
        "eGFR 12.6 (severe), potassium 5.0 (near but under the 5.5 "
        "hyperkalemia line), losartan+lisinopril (contextual) active, "
        "ibuprofen (moderate) ended 2026-05-08 — inside the 730-day "
        "window, so `past nephrotoxic exposure` matches but `nephrotoxic "
        "medication` (active) does not. Alive, age 63."
    ),
    "4eabfa47-5f30-b37b-8983-1eb95f44d700": (
        "eGFR 80.2 mL/min/1.73m² (NOT impaired — also the other "
        "eGFR unit, for coverage) with cisplatin (high tier) ever prescribed "
        "(closed 2005). Clean `elderly` ∩ `high-risk nephrotoxic "
        "medication` anchor with no renal-impairment confound. Deceased "
        "2005-04-18, age 96 at death."
    ),
    "0052e4b1-8e5b-f4f0-69ab-05f87db22664": (
        "Control: alive, no eGFR ever below 60, never prescribed anything on "
        "the nephrotoxic-tier list. Matches none of the running example's "
        "terms — the negative-space case."
    ),
    "00d0b8ca-e6cf-5147-92b5-64a8618f8eba": (
        "A second control, same shape as above, for tests that want two "
        "distinct non-matching patients rather than one repeated."
    ),
}

RANDOM_SEED = 20260922
RANDOM_COUNT = 100


def main() -> None:
    source = Path("data/synthea/csv")
    out = Path("tests/support/synthea")
    out.mkdir(parents=True, exist_ok=True)

    with (source / "patients.csv").open(newline="", encoding="utf-8") as handle:
        all_ids = [row["Id"] for row in csv.DictReader(handle)]

    missing_anchors = set(ANCHORS) - set(all_ids)
    if missing_anchors:
        message = f"anchor(s) not found in patients.csv: {sorted(missing_anchors)}"
        raise SystemExit(message)

    rng = random.Random(RANDOM_SEED)
    random_sample = set(rng.sample(all_ids, RANDOM_COUNT))
    keep = set(ANCHORS) | random_sample
    print(f"{len(ANCHORS)} anchors + {len(random_sample)} random "
          f"({len(random_sample & set(ANCHORS))} overlap) = {len(keep)} patients")

    for name, id_field in (
        ("patients", "Id"),
        ("medications", "PATIENT"),
        ("observations", "PATIENT"),
    ):
        in_path = source / f"{name}.csv"
        out_path = out / f"{name}.csv.gz"
        with (
            in_path.open(newline="", encoding="utf-8") as fin,
            gzip.open(out_path, "wt", newline="", encoding="utf-8") as fout,
        ):
            reader = csv.DictReader(fin)
            writer = csv.DictWriter(fout, fieldnames=reader.fieldnames or [])
            writer.writeheader()
            count = 0
            for row in reader:
                if row[id_field] in keep:
                    writer.writerow(row)
                    count += 1
        print(f"{name}: {count} rows -> {out_path}")


if __name__ == "__main__":
    main()
