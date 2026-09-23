# Demo script

Everything below has been run against the actual seeded dataset. Commands are
verbatim, the numbers are the ones the real 2,271-patient Synthea export
actually produces, and where the live behaviour is less dramatic than the
design, this says so rather than promising a better show.

Total time from a fresh clone: a few minutes, nearly all of it generating the
Synthea export. Loading 1.77 million observations into Postgres — 293
medications, 2,271 patients, 110,870 prescriptions, all of it — takes under a
minute, via `COPY` rather than batched `INSERT`.

## Setup

```bash
cp .env.example .env          # then put your ANTHROPIC_API_KEY in it
docker compose up -d
scripts/generate-synthea.sh
cd backend && uv run python -m app.seed --from ./data/synthea/csv
```

The seed is a separate step, and it runs on the host rather than in a
container: an app that writes 2,271 patients into whatever database it finds
at startup is a bad default, even for synthetic data, and the 380 MB export is
gitignored and regenerated locally rather than shipped.

It loads 293 medications, 49 curated nephrotoxic-risk annotations, 20 clinical
definitions (11 filters, 4 measures, 5 dimensions), 2,271 patients, 110,870
prescriptions and 1,773,806 observations. **All of it is fabricated.** No real
patient data has ever been in this project.

Open <http://localhost:3000>.

**Click "What can I ask?" in the header before you start.** The panel groups
the vocabulary into filters, measures and group-bys, and — behind a
disclosure on each — carries the justification for the threshold. It is
served from the same `clinical_definitions` rows the query layer resolves
against, so it cannot drift from what the system actually understands. Click
any term in it and it drops into the message box. It
also reports the dataset's own shape at the bottom: patient/medication/
observation counts, which LOINC codes are actually tracked, which
nephrotoxic-risk tiers exist, and which columns are returnable versus
restricted.

That panel is worth thirty seconds of the demo on its own. The definitions
layer is the architecture, and without it on screen you are asking someone to
take your word for it. Expand "why this threshold" on **hyperkalemia** — the
rationale explains that raised potassium is the complication that actually
limits ACE inhibitors in CKD, which is the setup for the clinical point at the
end of this script.

**"Definitions" in the sidebar opens the definitions editor** — the same
`clinical_definitions` rows, editable: create, preview against the real data,
publish, and a version history per term. It is real and working end to end
(create → preview → publish → appears in the model's own vocabulary →
versioned → delete, all exercised against the live API), but it is new this
phase and still awaiting review, so treat it as "here if you want to show it"
rather than a scripted step.

## The four questions

Ask them in this order. Each one is doing a different job.

### 1. The architecture, in one answer

> What patients are on a nephrotoxic medication and have impaired kidney
> function?

**76 patients.** Watch what comes back with them: the answer states that
"impaired renal function" means a most-recent eGFR below 60, that this is the
KDIGO G3a boundary, and that "nephrotoxic medication" covers the high and
moderate risk tiers while deliberately excluding a third.

That is the whole argument. The model did not choose the threshold — it chose
which *defined term* the question meant, and the threshold came from a row in
`clinical_definitions` that a clinician could review. Under the answer, the
result shows the count, the chart for an aggregate, and **Show patients**,
**Download CSV** and **Save question**; open **How this was answered** to see
the terms it passed and the SQL that was assembled from them.

**The point to make out loud:** there is no `sql` property in the tool's
schema. The model has no way to express "eGFR below 45" except by naming a term
that already means that.

### 2. The follow-up

> now just the ones over 65

**35 patients**, and — this is the part worth pausing on — the answer says
something like *"this is 65 and over, not strictly over 65"*.

The hospital defines `elderly` as `>= 65`. The question said "over 65". The
system answered the hospital's question and told the user it had done so.

It gets there by calling the tool again with `elderly` added, not by filtering
the seventy-six rows it already had. That matters for two reasons: the
boundary is the hospital's rather than the model's, and the follow-up appears
in the audit log as a query in its own right.

**This exact case is a regression test** (`over_65_followup` in
`backend/tests/support/eval_cases.py`) because the first live run got it wrong:
the model filtered its own context and invented `> 65`. It had never been told
`elderly` existed.

### 3. The one that aggregates, not lists

> What's the average eGFR for patients with impaired kidney function, broken
> down by age band?

This is the newest capability, and it is a different query *shape*, not a
filtered list: naming a measure (`average eGFR`) and a dimension (`age band`)
turns the same resolved cohort into a `GROUP BY`. The real numbers this
returns:

| age band | average eGFR |
| --- | --- |
| under 18 | 12.6 |
| 18–44 | 11.8 |
| 45–64 | 19.1 |
| 65–79 | 19.8 |
| 80+ | 22.6 |

**The point to make out loud:** the model did not compute a single one of
these averages. It named a measure and a dimension, both rows in
`clinical_definitions`, and the assembler wrote the aggregate SQL — the same
guarantee as question 1, extended to arithmetic the model would otherwise be
tempted to do itself.

### 4. The one that refuses

> List the full names and dates of birth of every patient with impaired kidney
> function.

The model replies **"Names and dates of birth aren't available to me — I can
identify patients only by their patient id and report age"**, then answers the
answerable part: up to 200 patients (of 244 — the answer says it is capped),
by `patient_id` and age.

**Be honest about what this shows.** The model complied on its own; it asked
for `patient_id, age, sex` and never tried for the restricted columns. That is
good behaviour, but it is *the model being obedient*, not the guardrail being
exercised. If you want to show the guardrail itself, show one of these
instead:

- `backend/tests/support/eval_cases.py`, cases `asks_for_names`,
  `asks_for_date_of_birth` and `adversarial_pii_probe` — the last one is a
  prompt-injection attempt demanding names in "administrator mode". It is
  refused because the allowlist is code and the tool's schema has no property
  that could carry the instruction.
- `backend/app/clinical/columns.py` — the allowlist itself, in source rather
  than in a table, because a restriction liftable by a database write is not a
  restriction. It is longer than it looks like it needs to be, on purpose:
  Synthea issues an SSN, a driving licence and a passport alongside the name
  and birth date, and every one of them is loaded and none of them returnable.

## The audit log

```bash
docker compose exec db psql -U app -d app -c \
  "select outcome, row_count, resolved_terms, columns_touched from query_audit order by created_at desc limit 5;"
```

Two things to point at.

**`columns_touched` on the second question includes `patients.birth_date`,**
even though no date of birth was returned to anyone. Age is derived from it at
query time, so the column was *read*. An audit that only recorded what was
displayed would miss that, and it is exactly what a PHI audit asks about.

**Rejections are logged too.** Run the fourth question's restricted-column
variant through the tests and the row is there with `outcome = 'rejected'` and
a reason. "Did anyone try to read that column" is the question this table
exists to answer, and a log of successes cannot answer it.

Deleting a conversation does not delete its audit rows — the foreign key is
`ON DELETE SET NULL`. An audit trail a user can erase by tidying their chat
list is not an audit trail.

## The eval

```bash
cd backend && uv run pytest tests/integration/test_eval.py -v
```

Nineteen cases, each carrying a `pins` line saying what breaks if it fails, so
a failure reads "the contextual tier stopped being excluded" rather than
"expected 76, got 75". They run against a small, committed, real fixture —
`backend/tests/support/synthea/` — rather than the full export, so the suite
does not need a 1.77-million-row load to gate a commit. See
[CONVENTIONS.md § Where tests go](./CONVENTIONS.md#where-tests-go) for why the fixture
is a subset in the same format rather than a format of its own.

The four `live_only` cases in the same file need a real model and run
separately:

```bash
cd backend && uv run pytest tests/live        # costs money, needs the API key
```

That split is deliberate. The hermetic suite answers "given the right terms, is
the answer right"; the live suite answers "does a model pick the right terms".
A suite that mixed them would fail for two unrelated reasons and tell you
neither.

## The clinical point worth making

If someone asks why `nephrotoxic medication` excludes ACE inhibitors:

> They lower measured eGFR through efferent arteriolar dilation, not injury,
> and they are prescribed *for* their kidney benefit in proteinuric CKD.
> Returning a patient on lisinopril next to one on gentamicin, under one flat
> label, is a clinically misleading answer that still looks like a correct
> query result.

Then show that the right question is still askable:

> Which patients on an ACE inhibitor or ARB have high potassium?

**Zero patients — and that is the honest answer, not a bug.** Nobody in this
sampled population clears 5.5 mmol/L potassium while on a RAAS blocker. It
would have been easy to quietly loosen the threshold until someone matched;
the project's standing rule is the opposite — never tune a clinical threshold
to make a demo look better, say so out loud instead. Follow it with the term
alone to show it is not an unreachable label:

> Which patients are on an ACE inhibitor or ARB?

**423 patients**, including the ones `nephrotoxic medication` deliberately
leaves out. Raised potassium is the complication that actually limits those
drugs in CKD; this dataset's patients simply do not happen to have it
recorded that high, and the system says exactly that rather than manufacturing
a match.

## Production

```bash
cp .env.prod.example .env.prod      # fill in every value; none default
docker compose -f docker-compose.prod.yml --env-file .env.prod up --build -d
```

Built bundle on nginx, JSON logs, Postgres unpublished, healthchecks on all
four services. Streaming was verified through nginx by attaching to a live turn
and counting frames — 99 text frames and 65 thinking frames arriving separately
as the response body grew. A buffered SSE response is indistinguishable from an
application bug from the outside, which is why reading `nginx.conf` and
believing it does not count.

Stop the dev stack first; both bind the same host ports.

**Seeding production.** `docker-compose.prod.yml` bind-mounts
`./backend/data:/srv/data:ro` into the `worker` service and sets
`SYNTHEA_CSV_DIR` to match, the same way the dev stack points the loader at a
local export (`scripts/deploy.sh` does all of this for you):

```bash
scripts/generate-synthea.sh                                          # once, on the host
docker compose -f docker-compose.prod.yml --env-file .env.prod \
  run --rm --entrypoint python worker -m app.seed
```

This is the answer for a deploy where the containers and the CSV export share a
filesystem — a single VPS, most self-hosted setups. It is not the answer for a
platform where they do not (most managed container platforms): that still wants
an object-storage fetch in the seed entrypoint, which is not built, because the
deployment this project actually uses — one server, via `scripts/deploy.sh` —
does not need it.
