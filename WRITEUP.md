# Clinical Copilot: why the model does not write the SQL

A chat app answering clinical questions over a 2,271-patient synthetic dataset
(Synthea, real LOINC labs and RxNorm prescriptions) — *"what patients are on a
nephrotoxic medication and have impaired kidney function?"* The interesting
decision is what the model is **not** allowed to do.

**A definitions layer, not text-to-SQL.** Letting a model generate SQL for
domain logic makes it the author of clinical thresholds; ask twice and
"impaired kidney function" may be eGFR < 60 once and < 45 the next time. So
`clinical_definitions` holds one row per term — a filter, a measure, or a
dimension — with a structured predicate and a `notes` field carrying the
justification: KDIGO G3a, the boundary below which renal dose adjustment is
generally required. The model only chooses *which defined term* a question
means, filter versus thing-to-aggregate versus thing-to-group-by; a
deterministic assembler turns resolved terms into parameterised SQL and is the
only code here that writes any. There is no `sql` property in the tool's
schema to pass.
*"Average eGFR by age band, for patients on a nephrotoxic medication"* runs
the same assembler down a `GROUP BY` path — a named measure and dimension, not
a formula the model wrote.

`logic` is structured JSON, never a SQL fragment — a config table of snippets
that get interpolated is an injection vector wearing a config table's clothes,
and nothing can validate it.

**The tier that earns the table.** Nephrotoxicity is tiered, not boolean, and
ACE inhibitors sit in `contextual` rather than beside gentamicin: they lower
measured eGFR through efferent arteriolar dilation — haemodynamics, not
injury — and are prescribed *for* their renoprotective effect in proteinuric
CKD. A flat label would return lisinopril alongside an aminoglycoside: a
clinically misleading answer that still looks like a correct query result.
`nephrotoxic medication` matches 355 of 2,271 patients; `renin-angiotensin
blocker` reaches a different 423, on purpose.

**The zero that stayed zero.** The clinically correct follow-up —
*"which patients on an ACE inhibitor or ARB have high potassium?"* — comes
back empty: nobody in this sampled population clears 5.5 mmol/L potassium
while on a RAAS blocker. Found, not designed, while rebuilding the eval suite
against real data, and the project's own rule is explicit: never tune a
threshold to make a demo look better. It stayed at 5.5; the eval case now
asserts the real zero, and a second case proves the *term* still reaches real
patients on its own — the zero is about potassium, not an unreachable class.

**What the eval caught that the unit tests could not.** Asked *"now just the
ones over 65"*, the model didn't re-query. It filtered rows already in its
context and admitted *"> 65 is my own filter, not a hospital-defined term"* —
the hospital defines `elderly` as `>= 65`. It had never been told `elderly`
existed: the vocabulary was only shown after a resolution *failed*, so every
first attempt was a guess at the term names. That guess usually resolves,
which is worse than it sounds — it works until it quietly doesn't. The term
list now goes into the prompt every turn, and that exchange is a regression
case: 76 patients narrows to 35 when `elderly` is added correctly.

**Answering a PHI audit.** `query_audit` is append-only and written on
refusals too; a log of successes cannot answer "did anyone try to read that
column". `columns_touched` records `patients.birth_date` for age-filtered
queries even though no date of birth is ever returned — age is derived from
it, so it was read. The conversation key is `ON DELETE SET NULL`, because an
audit trail a user can erase by tidying their chat list is not an audit trail.
Definitions are cached; answers never are — the patient whose eGFR just fell
is precisely the one the query exists to surface.

---

*Synthetic data throughout. Not validated for clinical use.*
