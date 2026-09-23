# What a semantic-model product has that this does not

A gap list, written by comparing this app to something like Zenlytic: a
product whose whole surface is a semantic model you author, review and edit
over time, with a chat interface sitting on top of it.

**This is a wish list with rules.** Every entry says what is missing, *why it
is worth having here specifically*, and what already exists to hang it on. An
entry with no argument for it is a feature someone thought of, and those are
free to think of — so the bar for being in this file is that the reasoning
survives being read back in three months.

Two rules, borrowed from [CONVENTIONS.md § What is deliberately
missing](./CONVENTIONS.md#what-is-deliberately-missing), which this file is the long
form of:

- **Delete an entry the day it ships.** A gap list that still claims something
  is missing after it was built is worse than no list: it is the document
  telling you not to look.
- **Say what it depends on.** Several of these are cheap in the right order and
  a rewrite in the wrong one — charts before aggregation is a bar chart with
  one bar. [Ordering](#ordering) is the short version.

**A third rule: numbering stays put.** Every `§N` anchor here is cited from
shipped code — routes, services, schemas, frontend components — not just from
this file's own cross-references. Deleting a shipped entry would renumber
everything after it and quietly break those citations, with no compiler to
catch it. So a shipped entry is marked **Shipped** and says where to look,
rather than being removed — no stale claim is left standing either way.

## Where this app actually is

Worth stating first, because the gaps below only make sense against it.

The semantic layer is no longer *"a set of boolean filters over one entity."*
`clinical_definitions` holds three kinds of row now — filters, measures,
dimensions — nineteen of them; a filter's predicate can be composed with
`all_of`/`any_of`/`not` and can reference another filter by name, not just AND
a flat list; the assembler has a real `GROUP BY` path, over a second entity
(medications, not just patients) as of the multi-entity work in § 11; and
there is a working editor with validation, preview, versioned history and
synonym-conflict detection sitting in front of all of it. Five of the six
things a Zenlytic/LookML/Cube-shaped semantic layer has that a boolean-filter
list does not — **measures, dimensions, an editor, a change history, and now
joins** — are built. What "joins" turned out to mean here, concretely: not a
runtime-bound schema profile (see "Deliberately not on this list" — that is
still, correctly, out) but `assembler._join_medication_annotations`, the one
relationship this schema's queries actually share, extracted from four places
that repeated it identically and documented once with the cardinality that
matters — `medication_annotations` joins on `code` rather than a foreign key,
and fans out one row per curated attribute, which is exactly why every caller
already filtered `attribute` in its own `WHERE`. That is the whole join graph
this app has; declaring it did not require inventing a bigger one. The one
piece still open is **lineage back to the source data**, and even that is
narrower than first framed — see § 1, now mostly shipped.

The bet this project makes — the model chooses terms and never writes SQL — is
not in tension with any of it. A measure is as definable as a filter, and the
model picking `average eGFR` from a list is the same act as picking `impaired
renal function`. What must not happen is the model inventing either one.

## The four that matter most

### 1. Where the data came from

Provenance, at three levels, and they were always separate pieces of work.

**The dataset. Shipped.** `dataset_meta` (source, as-of date, patient count,
notes) renders in `ClinicalContextPanel`'s "In this dataset" section — source,
as-of date, and the counts, right next to the vocabulary. This was the cheap,
unblocked first step [Ordering](#ordering) named, and it went first.

**The row — mostly shipped, on reflection narrower than first framed.**
`clear_clinical_data` deletes every `DatasetMeta` row before a reload writes
a fresh one — this codebase has never had more than one load coexisting, so
"which load run wrote this row" was never actually ambiguous; every row in
the tables right now came from the one `dataset_meta` row. What was genuinely
missing was surfacing that fact rather than leaving it implicit, which
`catalog_service.current_dataset()` (extracted from `load_catalog`, reused
everywhere below) now makes cheap to do anywhere. The `system` column on
`observations`/`medications`/`medication_annotations` remains real and
still unsurfaced past the raw code — attributing an *individual value* to its
code system is the same shape of question as "why is this patient not in the
cohort" (§15), which
was explicitly declined this round, so it stayed out rather than reopening
that boundary through a different door.

**The answer — shipped.** Every `ClinicalAnswer` and `BrowseResult` now
carries `dataset: DatasetProvenance | None`, populated at the same place the
SQL and the row count already were. `find_patients.py` renders it as a
"Dataset: ..." line right after "SQL executed:", so the model can relay it if
asked, and `SavedQuestionResult`/`PatientBrowser` render the same fact as a
one-line caption for a human reading the UI directly. Not a *new* clickable
path to the tables — [drilldown, export and the table
browser](#3-querying-the-database-directly-to-see-the-raw-data) already are
that, and shipped before this did — but the missing half of "SQL → tables →
**the loader**": which load those tables came from, cited next to every
answer rather than only in the context panel.

**Seam:** `dataset_meta`, `catalog_service.current_dataset`, the `system`
columns, `query_audit.executed_sql`.

### 2. Seeing the semantic model in the frontend

**Shipped.** `DefinitionsEditor` (`src/components/DefinitionsEditor.tsx`,
`DefinitionForm.tsx`, `DefinitionList.tsx`) is the model view this entry asked
for: every definition, any status, with `logic` shown as structured, editable
form controls per predicate/measure/dimension shape — not a raw JSON box, and
not the chat panel's deliberately-withheld view. `PredicateEditor` recurses for
`all_of`/`any_of`/`not`; version and `updatedBy` show on every definition;
history (who, when, why) lists at the bottom. Reached via "Definitions" in the
sidebar (`/definitions`), gated `RequireReviewer`/`RequireCurator`.

Not fully built: rendering a predicate as an *English sentence* alongside the
form. The structured editor arguably does more for a curator than prose would,
so this was not missed so much as superseded — flagged here rather than
silently dropped, in case a future reader wants the sentence anyway.

### 3. Querying the database directly, to see the raw data

**Shipped.** All three things that ever wore this name are resolved now —
two built, one correctly still refused.

**Cohort drilldown — shipped.** `POST /api/clinical/query`
(`app/api/routes/cohort.py`) is exactly "show me these 76 patients, one per
row, with the values that made them match": the same terms a chat answer
already resolved, re-asked for every returnable column instead of the three
the model happened to request. The "Show patients" button under a chat
answer (`AnswerActions`, inside `ToolCard`'s result) is the frontend end of it. It is the filtered raw view this entry
asked for, not a new query path — same column allowlist, same row-level
scope, its own `query_audit` row (`via="cohort"`). `SavedQuestionsPanel`
(§17) still shows the roster for a *saved* question's run the same way it
always did; this is the general case, reachable from any chat answer.

**A governed table browser for a human — shipped.** `GET /clinical/patients`
(`app/api/routes/cohort.py`, `clinical_query_service.browse_patients`) and
`PatientBrowser` in the frontend, behind a "Browse patients" header button.
The one genuinely new piece, next to the drilldown: no terms, no question,
no definitions resolved at all — `assembler.browse_patients_query` is a
deliberate, explicitly-named exception to `patient_condition`'s refusal of an
empty predicate list, reachable only from this one human-only path. Same
column allowlist and per-role policy (§19) as everywhere else, same row-level
scope, paginated (50 a page, 200-row hard cap), its own audited `via="browse"`
— a value the `query_audit` CHECK constraint needed a migration to admit,
since autogenerate doesn't see a widened `in (...)` list any more than it sees
a partial index's `WHERE` clause. Gated `RequireReviewer`: this is a curator
or auditor paging through the dataset itself, not a chat surface.

**A SQL box the model can reach.** Still, correctly, out. Not because a human
should not see rows, but because the moment arbitrary SQL is reachable *by the
model*, the definitions layer is decoration — there is a faster path to an
answer that skips it, and everything downstream still looks correct.

The distinction to hold: **the browser is a UI affordance, not a tool.** It is
not registered in `tools/__init__.py`, it does not appear in the model's
schema, and the structural test asserting one tool reaches the data stays
green. The drilldown and the table browser are both reached directly by the
frontend the same way — neither is registered as a tool the model can call.

**Seam:** `clinical/columns.py`, `query_audit`, `catalog_service` (already the
one blessed reader of clinical tables that is not the assembler).

### 4. Visualisation artifacts

**Shipped.** A tool result's aggregate rows fold through a new pure module,
`frontend/src/chart.ts` (`toChartData`), into a horizontal bar chart
(`Chart.tsx`) — one section per measure, rendered in `ToolCard`'s result — open
by default, above the collapsed arguments and SQL — and reused as-is in `SavedQuestionResult` for a saved question's
run. Both decisions this entry asked for going in are exactly what shipped:
the chart is derived from `data` and never authored by the model (there is
still no property on the tool for a chart spec), and it renders through the
one fold `turns.ts` already owned — `chart.ts` is called from the same place
`ToolCard` already was, not a second render path.

A trap worth knowing: `average eGFR`/`median creatinine` are Postgres
`NUMERIC`, which arrives as Python `Decimal` — no JSON representation, and
`json.dumps`-based paths (the JSONB write, a route response typed
`dict[str, Any]`) either raised or silently stringified it. `_json_safe` in
`app/tools/find_patients.py` and `app/api/schemas.py` converts it at the two
points data crosses into JSON. Worth knowing before adding a second numeric
measure by copy-pasting one of the existing ones — the conversion is not
automatic anywhere else.

### 5. Measures and dimensions

**Shipped.** Four measures (`patient count`, `average eGFR`, `lowest eGFR`,
`median creatinine`), four dimensions (`sex`, `age band`, `nephrotoxic tier`,
`state`), a real `GROUP BY` path in the assembler with fan-out protection —
`ObservationAggregate` reads one value per patient (their latest), never a
join fan-out across prescriptions. `find_patients`'s `measures`/`group_by`
arrays are how the model reaches any of it; leaving both empty is still a
plain cohort listing. This was the entry everything else waited on, and it is
why so much of the rest of this list closed in the same phase.

### 6. Editing the model without a migration

**Shipped.** Full CRUD through `app/api/routes/definitions.py` and
`DefinitionsEditor`: create, update, publish (a dedicated step, not a status
dropdown), delete, and `POST /clinical/definitions/preview` — a dry run
against real data returning a patient count before anything saves, exactly
the "this change moves the cohort from 76 to 112" impact preview this entry
asked for. Two-level validation (shape in `predicates.py`, codes against
`observation_catalog` in `definition_service`) surfaces as a form error, not a
500. Cache invalidation happens on every write; `check_model()` — exposed as
`GET /clinical/model/check` — flags a definition that matches nobody or
cannot be built at all, and renders as a ⚠ in the definition list.

### 7. Definition history, and answers pinned to it

**Shipped.** `clinical_definitions.version` bumps on every edit;
`clinical_definition_history` is append-only, one row per change, with
`changed_by` and a required `change_reason`; `query_audit.definition_versions`
records which version of each term an answer resolved through. An old answer
is reproducible and a changed one is explainable — "the cohort grew because
the threshold moved on the 12th" is answerable by reading two tables, not by
memory.

### 8. Predicate composition: OR, NOT, and terms built from terms

**Shipped.** `predicates.py` has `AnyOf`, `AllOf`, `Not`, and `TermReference`
(a predicate that names another filter and gets substituted in) alongside the
leaf shapes — `renal risk on a nephrotoxin` in the seed data is `all_of` two
other terms, and `not on a nephrotoxin` is a `TermReference` wrapped in `Not`,
both exercised by `test_query_assembly.py`. Composition has a cycle check
(`definition_service.load_vocabulary`'s inner `resolve()`) and feeds directly
into conflict detection (§12).

### 9. Units, and refusing to compare across them

**Shipped.** `ObservationThreshold.units` is a declared field on every
observation-threshold predicate, checked at load time against
`observation_catalog` — a definition naming a unit nothing in the dataset was
ever measured in fails to load, loudly, rather than comparing across units
silently. `impaired renal function`'s `codes`/`units` pair (LOINC 33914-3,
`mL/min/1.73m²` or `mL/min`) is the worked example in `reference_data.py`'s
own comments.

### 10. What happens to patients with no measurement

**Shipped.** `UnmeasuredCount`/`_unmeasured_counts` in
`clinical_query_service.py` reports, alongside every cohort and aggregate
answer, how many patients matched everything else asked and were never
measured for the one threshold that would have decided them — excluded from
the count, not counted as not meeting it, and said so in the rendered answer.
The denominator this entry asked for.

### 11. More than one entity, and refinable cohorts

**Partly shipped.** Two different problems always wore this one number, and
only the first is built.

**Questions about medications, not just patients — shipped.**
`clinical_definitions.entity` (`patient`/`medication`/`observation`) existed
from the start but was pure decoration — stored, never read by anything that
built a query. It is load-bearing now: a new `MedicationName` dimension and
`assembler.medication_aggregate_query()` (FROM prescriptions/medications,
never FROM patients) let a question be about drugs directly, and
`clinical_query_service` routes on the resolved dimension's `entity` to
decide which assembler function to call. "Which nephrotoxins are most
prescribed" — this section's own named example of what was inexpressible —
now resolves through the unmodified `find_patients` tool schema: `group_by`
already took a term name, and the term now names a medication-entity
dimension. The existing `patient count` measure is reused as-is; no new
measure vocabulary was needed. Mixing a patient-entity and a medication-entity
dimension in one `group_by` is a rejection with a reason, not a query that
happens to compile — one question, one entity.

Fixing this surfaced a real, previously-invisible data error: the seeded
`nephrotoxic tier` dimension carried `entity: "medication"`, true of what it
is *about* and false of which query it needs (it groups *patients* by their
drug's tier, and stays on the ordinary patient-scoped `aggregate_query`).
That was silently wrong for as long as `entity` was decorative and would have
broken it the moment routing went live. Routing is what caught it.

**A cohort as a refinable object — still open, and deliberately not
attempted.** "Now just the elderly ones" still re-queries from scratch rather
than refining a saved result. This section used to call that "still the right
behaviour for a chat follow-up (it proves the definition is cited the second
time too)" and that argument was not resolved by shipping the paragraph
above — if anything it sharpens the choice: a stateful, model-held cohort
that narrows across turns without re-resolving would cut against the exact
citation guarantee this project's whole argument rests on. So the question to
answer before any code is written: is this (a) a UI convenience — narrow a
result by adding a defined term, still re-resolved and re-cited on every
step — or (b) state the model holds and narrows across turns? Only (a) keeps
the guarantee, and neither is built. Saved questions (§17) gave a cohort a *name* you
can return to; that has not changed, and it is not the same thing as a
refinement history within one conversation.

### 12. Conflicts and ambiguity in the vocabulary

**Shipped.** `definition_service._check_no_conflict` refuses to save a
definition whose term or synonym is already claimed by another one —
`DefinitionConflictError`, surfaced as a 409 by the create/update routes and
shown as a form error in the editor. Exact matching with no fuzzy fallback was
already the design and stays; what shipped is the check that two rows cannot
silently claim the same synonym.

### 13. Tests for the model, not just the code

**Partly shipped.** `check_model()` (§6) catches the two failure modes that
matter most in practice — a definition that cannot be built at all, and one
that matches nobody in the loaded dataset (the `hyperkalemia` case, which
stayed a real, documented zero rather than being tuned away) — and now a
third: **`invariants`**, a `subset_of`/
`disjoint_from` relationship between two filter terms, declared on
`clinical_definitions` and checked live against real patient ids by
`_check_invariants`, not just against the predicate shapes. "Severely
impaired renal function" declaring `subset_of` "impaired renal function" is
the seeded, real example — an editor could otherwise define the "severe"
threshold on the wrong side of the "any" one and nothing would say so until a
clinician noticed the numbers didn't nest. Still missing: the bound on how
much a term's cohort may change on a dataset reload before it is worth a
second look. That is still exactly the guardrail that makes handing the
editor to a non-engineer safe rather than merely possible — invariants catch
a *relationship* going wrong, not a single term drifting on its own.

## Trust, and the feedback loop

### 14. The unresolved-term report

**Shipped.** `GET /api/audit/unresolved-terms` (`app/api/routes/audit.py`) and
`UnresolvedTermsPanel` in the frontend, reached from a header button beside
"Saved questions". The service-level read (`audit_service.unresolved_term_report`
— grouped by raw question, ranked by frequency, exactly as this entry always
described) predated this update and had no caller; the work here was the
route, the schema, the page, and the tests neither had. Gated `RequireReviewer`
(curator or auditor), the same read-side guard the definitions editor uses —
a curator deciding what to define next, not something an ordinary chat
session needs to see.

### 15. Why a patient is *not* in the cohort

Still open, and deprioritised rather than forgotten — raised and explicitly
set aside as lower value than the rest of this list. A backend half was
built — `explain_patient` in `clinical_query_service.py`, per-predicate
attribution for one patient — and later deleted, because nothing ever called
it. It is in the repository's first commit if priorities change.

### 16. Freshness, ownership and certification on a term

**Partly shipped.** The versioned history this entry said was a
precondition — §7 — is real now, so "last reviewed" would no longer be a date
with nothing behind it. `owner` and `reviewed_at` are columns on
`clinical_definitions` and travel over the API (`DefinitionOut.owner`/
`.reviewedAt`), but `DefinitionForm` does not surface or edit either one, and
nothing anywhere ever sets `reviewed_at` — there is no "mark reviewed"
action. Nineteen rows written in one phase still do not need this; it is
worth building before a second curator shows up, not after.

## Delivery

### 17. Saved questions, dashboards and a schedules UI

**Partly shipped.** Saved questions are real: `saved_questions` (a name plus
terms/measures/group-by, never rows or SQL), full CRUD through
`app/api/routes/saved_questions.py`, and `SavedQuestionsPanel` in the
frontend — create from the real vocabulary via checkboxes (no way to save a
term name that will not resolve), run on demand, which re-asks the
definitions layer fresh every time rather than replaying a stored answer, and
renders through the same `chart.ts`/`Chart.tsx` an aggregate chat answer does.

**Dashboard — shipped.** `Dashboard.tsx`/`DashboardCard.tsx`, reached from a
"Dashboard" button beside "Saved questions": every saved question, run fresh
on load and shown together — exactly the phrase this entry used, "a set of
saved questions on one page", with no new backend route (the existing list
and per-question run endpoints were already the whole API it needed). This
entry previously said a dashboard mostly wants
[cohorts as objects](#11-more-than-one-entity-and-refinable-cohorts) — that
turned out to overstate the dependency: a page of current answers to saved
questions needs saved questions, not a refinable cohort, and building it
surfaced that rather than requiring §11's harder half first.

Still missing: a digest (the same page, delivered rather than opened) and a
schedules UI. `/api/schedules` is unchanged: it exists, works, and is
unreachable from the browser, deliberately — see
[CONVENTIONS.md](./CONVENTIONS.md#what-is-deliberately-missing).

### 18. Export, and treating it as a governed act

**Shipped.** The whole model as JSON, every status, is
`GET /clinical/definitions` — the list the editor (§6) reads — and that is the
backup-and-diff story for choosing database rows over git-tracked files. A
separate `/definitions/export` endpoint once returned exactly the same thing
and was removed as a duplicate nothing called. The
other kind of export this entry meant, a CSV of a *cohort's* rows, is now
`POST /api/clinical/export` (`app/api/routes/cohort.py`), reached from
the "Download CSV" button under a chat answer, next to the drilldown (§3), for
a patient list and an aggregate alike. It was, as
predicted, the same policy decision rather than a new one: the same column
allowlist, the same row-level scope, its own `query_audit` outcome
(`via="export"` — a value the schema named
before anything used it). A rejection has no rows for a file, so it is a
422 rather than a 200 with an empty download — the one place this differs
from the JSON drilldown, because a binary response has no `outcome` field to
carry the distinction in.

### 19. Row-level access, and roles

**Partly shipped.** Row scoping is real: `user_roles.scope_states` (a list of
US states a user's queries are confined to; `None` is unconfined), applied by
`app/clinical/assembler.scope_condition` and threaded through every query path
— the chat tool, saved-question runs, previews — via `Asker.scope_states`.
`AccessPanel` in the frontend lets the dev user set their own scope and watch
subsequent questions confine to it, which is the seam proven end to end rather
than a permission model: there is no sign-in, so the user is the dev user
locally and an anonymous visitor on the public demo, and scope-editing is gated `RequireCurator` on the theory that changing what your
own queries can see is a deliberate act, not a default.

**Per-role column policy — shipped, granting nothing.** `resolve_columns`
took a single `allow_identifying: bool` that no caller ever set to `True` —
one global switch nobody flipped. It now takes `roles: Collection[str]`, and
`clinical/columns.py`'s new `ROLE_IDENTIFYING_COLUMNS` maps each role to the
identifying columns it may additionally see beyond the baseline every role
already gets. Every role maps to `()` today — deliberately: this project's
whole argument for column-level control is that identifying data stays
withheld by default, and swapping the mechanism does not change that
argument. What changes is that granting a real role a real column, if that is
ever wanted, is a one-line edit to a dict rather than a new system to design.
`Asker.roles`, threaded from `authz_service.get_roles` at every call site the
same way `scope_states` already is, is what makes the check real rather than
decorative — verified with a test that grants `auditor` a column via
`monkeypatch`, confirms it reads through the real `find_patients`-shaped path,
and confirms an ungranted role still can't. The identity seam itself is
still the easy half whenever a second real user shows up — one function, see
[CONVENTIONS.md § Identity](./CONVENTIONS.md#identity).

## Deliberately not on this list

Stated so they do not get re-proposed as oversights.

- **A runtime-bound schema profile — the assembler made table-agnostic.** That
  is LookML, and building it against one schema is speculative design from zero
  examples. The line this project draws instead: clinical *semantics* become
  data, the canonical schema stays. Every warehouse normalises sources
  into a canonical model and that is not a smell.
- **A SQL tool for the model.** See
  [§3](#3-querying-the-database-directly-to-see-the-raw-data). The human
  browser is fine; the tool is the thesis being abandoned.
- **Model-authored chart specs.** See [§4](#4-visualisation-artifacts) — now
  shipped in the non-model-authored form this always meant. The tool still has
  no property a chart spec could travel in.
- **Caching answers.** No TTL makes a stale clinical answer acceptable; it only
  sets how long the system may be confidently wrong. Definitions are cached,
  answers are not, and that asymmetry is deliberate.
- **Fuzzy term matching.** An unmatched term becomes a clarification, and that
  is better than a confident resolution to the wrong row.

## Ordering

Not a schedule — a dependency order, so nothing here is built twice. Left in
place with its original numbering so it stays readable as a record of what
was decided and why; what actually shipped is marked inline.

1. **The cheap, unblocked reads.** ~~Dataset provenance in the panel~~
   **shipped**, and the row and answer levels followed
   ([§1](#1-where-the-data-came-from) — all three). ~~The
   [unresolved-term report](#14-the-unresolved-term-report)~~ **shipped**.
   ~~The model view~~ **shipped**
   ([§2](#2-seeing-the-semantic-model-in-the-frontend)).
2. **Correctness the current design already implies.** ~~Units~~ and
   ~~unmeasured patients~~ — **both shipped**
   ([§9](#9-units-and-refusing-to-compare-across-them),
   [§10](#10-what-happens-to-patients-with-no-measurement)).
3. **Measures and dimensions** ([§5](#5-measures-and-dimensions)) — **shipped**,
   with fan-out protection. Everything below this line that shipped, shipped
   because this did first.
4. **The editor**, with impact preview, history and model tests — **shipped**
   ([§6](#6-editing-the-model-without-a-migration),
   [§7](#7-definition-history-and-answers-pinned-to-it)); model tests
   ([§13](#13-tests-for-the-model-not-just-the-code)) shipped the
   disjointness/subset piece as declared `invariants`, checked live. The
   reload-drift bound is the one piece of this step still open.
5. **Charts, drilldown, saved views, export.** All four **shipped**
   ([§4](#4-visualisation-artifacts),
   [§17](#17-saved-questions-dashboards-and-a-schedules-ui),
   [§3](#3-querying-the-database-directly-to-see-the-raw-data),
   [§18](#18-export-and-treating-it-as-a-governed-act)) — drilldown and CSV
   export as `POST /clinical/query` and `POST /clinical/export`, both reached
   from the actions under a chat answer, beside "Save question", which saves
   the answer's terms, measures and dimensions without rebuilding them.
6. **Roles and row-level access.** Row scoping **shipped**
   ([§19](#19-row-level-access-and-roles)) ahead of "a second user" showing
   up — built deliberately early rather than discovered as a prerequisite.
   Per-role column policy **shipped**
   too — granting nothing by default (deliberately), with the mechanism real
   and tested — without waiting for a second real user, the same way row
   scoping didn't.

**What is actually left, in the order this file would now put it:** cohorts as
refinable objects (§11's second half — the one substantial remaining piece of
design, deliberately not attempted: a product decision to make on purpose
rather than guess at); the reload-drift bound (§13); why a patient is not
in the cohort (§15), explicitly out of scope.
