"""The curated half of the seed: the clinical definitions.

Hand-authored, not generated. These are the rows the whole architecture rests
on — if `nephrotoxic medication` resolves to the wrong set of drugs, every
answer downstream is confidently wrong — so each one carries its reasoning in
the row rather than in a commit message nobody will find later.

The patients are the other half and come from Synthea (`synthea.py`). The drug
annotations are the third (`annotations.py`).

**Codes, not names.** A definition names LOINC codes and a unit, because that
is what the data carries. The `notes` say which codes and why, so a reader can
check the row against the catalog rather than take the mapping on trust.

**`logic` is a structured predicate, never a SQL fragment** — see the
`ClinicalDefinition` docstring for why, and `app/clinical/predicates.py` for
the validator that checks these shapes before anything is assembled.

**`notes` is NOT NULL on purpose:** a threshold with no defence is the thing
this table exists to prevent.
"""

from typing import Any, Final

from app.seed.annotations import NEPHROTOXIC_RISK

# eGFR. Synthea reports it under one LOINC in two units: the metabolic panel
# normalises to body surface area (`mL/min/{1.73_m2}`) and its kidney-disease
# module does not (`mL/min`). Both are the same estimate for the same purpose;
# for an adult of average build they differ by well under the noise between
# two draws, and both are used for KDIGO staging in practice. A definition
# that accepted only one would silently miss the patients the other module
# wrote — which is most of the CKD cohort — so both are listed, and this
# comment is the record of that being a decision rather than a default.
EGFR_CODES: Final = ["33914-3"]
EGFR_UNITS: Final = ["mL/min/{1.73_m2}", "mL/min"]

# Potassium and creatinine each carry two LOINCs in real data — serum and
# whole blood — and a patient's latest result may be under either.
POTASSIUM_CODES: Final = ["2823-3", "6298-4"]
POTASSIUM_UNITS: Final = ["mmol/L"]
CREATININE_CODES: Final = ["2160-0", "38483-4"]
CREATININE_UNITS: Final = ["mg/dL"]

# The tier ACE inhibitors and ARBs sit in. Named here because two definitions
# below and one dimension all refer to it, and the reason is in annotations.py.
CONTEXTUAL: Final = "contextual"

CLINICAL_DEFINITIONS: list[dict[str, Any]] = [
    # ------------------------------------------------------------- filters
    {
        "term": "impaired renal function",
        "kind": "filter",
        "entity": "observation",
        "description": "Most recent eGFR below 60 mL/min/1.73m².",
        "logic": {
            "type": "observation_threshold",
            "codes": EGFR_CODES,
            "units": EGFR_UNITS,
            "operator": "<",
            "value": 60,
            "most_recent": True,
        },
        "notes": (
            "eGFR < 60 is the KDIGO G3a boundary and the conventional threshold for CKD "
            "stage 3, below which renal dose adjustment is generally required. Uses the most "
            "recent value rather than any value: a patient whose function recovered should "
            "not stay on the list forever. A single reading is a snapshot — KDIGO requires "
            "≥3 months for a true CKD diagnosis — so this term means 'currently reduced', "
            "which is the right question for drug safety and is what the description says. "
            "LOINC 33914-3, accepted in both mL/min/1.73m² and mL/min: the source reports "
            "both under one code and the difference is below the noise between draws."
        ),
        "synonyms": [
            "reduced kidney function",
            "impaired kidney function",
            "renal impairment",
            "low egfr",
            "poor kidney function",
            "chronic kidney disease",
            "ckd",
        ],
    },
    {
        "term": "severely impaired renal function",
        "kind": "filter",
        "entity": "observation",
        "description": "Most recent eGFR below 30 mL/min/1.73m².",
        "logic": {
            "type": "observation_threshold",
            "codes": EGFR_CODES,
            "units": EGFR_UNITS,
            "operator": "<",
            "value": 30,
            "most_recent": True,
        },
        "notes": (
            "KDIGO G4. The threshold at which many drugs are contraindicated outright rather "
            "than dose-reduced. Kept separate from the G3a term so a question about severe "
            "impairment does not silently widen to everyone below 60."
        ),
        "synonyms": ["severe renal impairment", "stage 4 ckd", "severe kidney disease"],
        # eGFR < 30 implies eGFR < 60 by construction — the two thresholds
        # cannot disagree about a patient without one of them being wrong.
        # SEMANTIC_LAYER.md § 13's worked example: checked against the loaded
        # dataset on every `check_model()` call, not just asserted once in a
        # test file (see test_severe_is_a_subset_of_impaired, which pins the
        # same claim the other, code-only way).
        "invariants": [{"type": "subset_of", "term": "impaired renal function"}],
    },
    {
        "term": "nephrotoxic medication",
        "kind": "filter",
        "entity": "medication",
        "description": "Currently prescribed a drug tiered high or moderate for kidney risk.",
        "logic": {
            "type": "medication_attribute",
            "attribute": NEPHROTOXIC_RISK,
            "in": ["high", "moderate"],
            "exposure": "active",
        },
        "notes": (
            "Deliberately EXCLUDES the `contextual` tier. ACE inhibitors and ARBs lower "
            "measured eGFR through efferent arteriolar dilation rather than injury, and are "
            "prescribed for their renoprotective effect in proteinuric CKD. Returning a "
            "patient on lisinopril beside one on gentamicin, under one flat label, is a "
            "clinically misleading answer that still looks like a correct query result. A "
            "question that genuinely wants those drugs should ask for them by class. "
            "Exposure is `active` — an open prescription — because the question is about "
            "current risk; a finished course is `past nephrotoxic exposure`."
        ),
        "synonyms": [
            "nephrotoxic drug",
            "nephrotoxin",
            "kidney-damaging medication",
            "drug that harms the kidneys",
        ],
    },
    {
        "term": "past nephrotoxic exposure",
        "kind": "filter",
        "entity": "medication",
        "description": "Prescribed a high- or moderate-tier nephrotoxin in the last two years.",
        "logic": {
            "type": "medication_attribute",
            "attribute": NEPHROTOXIC_RISK,
            "in": ["high", "moderate"],
            "exposure": "recent",
            "within_days": 730,
        },
        "notes": (
            "The recency question. Two years because contrast- and platinum-associated "
            "injury can declare itself well after the course, and because this source "
            "closes almost every prescription — `active` alone would call a chronic NSAID "
            "user with a dispense last month unexposed. The window is a judgement and is "
            "written here so it can be argued with."
        ),
        "synonyms": ["recently on a nephrotoxin", "recent nephrotoxic medication"],
    },
    {
        "term": "high-risk nephrotoxic medication",
        "kind": "filter",
        "entity": "medication",
        "description": "Prescribed a drug tiered high for kidney risk, at any time on record.",
        "logic": {
            "type": "medication_attribute",
            "attribute": NEPHROTOXIC_RISK,
            "in": ["high"],
            "exposure": "ever",
        },
        "notes": (
            "The narrow reading: directly tubulotoxic agents only — aminoglycosides, "
            "vancomycin, amphotericin B, platinum chemotherapy. Exists so that 'nephrotoxic' "
            "and 'seriously nephrotoxic' are two answerable questions rather than one "
            "ambiguous one. Exposure is `ever` because these are short courses that are "
            "always closed by the time anyone asks, and cumulative platinum injury is "
            "permanent — the history is the risk."
        ),
        "synonyms": ["highly nephrotoxic medication", "seriously nephrotoxic drug"],
    },
    {
        "term": "elderly",
        "kind": "filter",
        "entity": "patient",
        "description": "Aged 65 or over.",
        "logic": {"type": "age_threshold", "operator": ">=", "value": 65},
        "notes": (
            "The conventional geriatric cutoff used by CMS and most guideline documents. "
            "Relevant here beyond convention: eGFR declines with age, so age and renal "
            "impairment are correlated and a question combining them is asking about a real "
            "population. Derived from birth_date at the dataset's as-of date, which is what "
            "lets age be filtered on while birth_date itself stays redacted. A deceased "
            "patient's age is their age at death."
        ),
        "synonyms": ["older patients", "geriatric", "over 65", "seniors"],
    },
    {
        "term": "living",
        "kind": "filter",
        "entity": "patient",
        "description": "Not recorded as deceased.",
        "logic": {"type": "vital_status", "status": "alive"},
        "notes": (
            "The source keeps deceased patients, as a hospital's records do. Most drug-safety "
            "questions are about people who can still be harmed, and this term is how a "
            "question says so — it is not applied silently, because 'how many patients on "
            "cisplatin died' is also a legitimate question."
        ),
        "synonyms": ["alive", "living patients", "not deceased"],
    },
    {
        "term": "renin-angiotensin blocker",
        "kind": "filter",
        "entity": "medication",
        "description": "Currently prescribed an ACE inhibitor or an angiotensin receptor blocker.",
        "logic": {
            "type": "medication_attribute",
            "attribute": NEPHROTOXIC_RISK,
            "in": [CONTEXTUAL],
            "exposure": "active",
        },
        "notes": (
            "Asks for these drugs by their tier, which is the honest way to reach them. The "
            "`nephrotoxic medication` term deliberately excludes them, and the answer to that "
            "exclusion is a term that names what it actually wants rather than widening "
            "`nephrotoxic` until it does. Paired with `hyperkalemia` this is a real monitoring "
            "question: raised potassium is the complication that actually limits RAAS blockade "
            "in CKD."
        ),
        "synonyms": [
            "ace inhibitor or arb",
            "raas blocker",
            "renin angiotensin aldosterone blocker",
            "acei/arb",
        ],
    },
    {
        "term": "hyperkalemia",
        "kind": "filter",
        "entity": "observation",
        "description": "Most recent potassium above 5.5 mmol/L.",
        "logic": {
            "type": "observation_threshold",
            "codes": POTASSIUM_CODES,
            "units": POTASSIUM_UNITS,
            "operator": ">",
            "value": 5.5,
            "most_recent": True,
        },
        "notes": (
            "5.5 mmol/L is the usual threshold for moderate hyperkalemia and for acting on it. "
            "Included because it is the complication that actually limits ACE inhibitor and ARB "
            "use in CKD — which makes it the clinically correct second question to ask about "
            "the `contextual` tier, rather than mislabelling those drugs as nephrotoxic. "
            "LOINC 2823-3 (serum) and 6298-4 (blood). The generated population may contain "
            "nobody above this line; that is a fact about the data, not a reason to lower it."
        ),
        "synonyms": ["high potassium", "raised potassium", "elevated k"],
    },
    {
        "term": "renal risk on a nephrotoxin",
        "kind": "filter",
        "entity": "patient",
        "description": "Impaired renal function together with a current nephrotoxic medication.",
        "logic": {
            "type": "all_of",
            "of": [
                {"type": "term", "term": "impaired renal function"},
                {"type": "term", "term": "nephrotoxic medication"},
            ],
        },
        "notes": (
            "The patients most exposed to drug-induced kidney injury: function already reduced, "
            "and an active prescription for something that can reduce it further. Composed from "
            "the two terms rather than restating either threshold, so the eGFR cutoff and the "
            "tier list are each written in one place and a change to either flows through. A "
            "question that names both terms gets the same query."
        ),
        "synonyms": ["at renal risk", "nephrotoxic exposure with reduced kidney function"],
    },
    {
        "term": "not on a nephrotoxin",
        "kind": "filter",
        "entity": "medication",
        "description": "No current prescription for a high- or moderate-tier nephrotoxin.",
        "logic": {"type": "not", "of": {"type": "term", "term": "nephrotoxic medication"}},
        "notes": (
            "The negation of `nephrotoxic medication`. A patient with no prescriptions on file "
            "at all satisfies this "
            "— 'not on a nephrotoxin' and 'no medication record' are different claims and "
            "this term is the first one. Useful with `impaired renal function` for the safety "
            "review question: who has reduced kidney function and is NOT on anything risky."
        ),
        "synonyms": ["no nephrotoxic medication", "off nephrotoxins"],
    },
    # ------------------------------------------------------------ measures
    {
        "term": "patient count",
        "kind": "measure",
        "entity": "patient",
        "description": "How many distinct patients.",
        "logic": {"type": "patient_count"},
        "notes": (
            "Counts people, not rows. Distinct, so a grouping that puts a patient in two "
            "groups still counts them once per group and never twice within one."
        ),
        "synonyms": ["number of patients", "count", "how many patients"],
    },
    {
        "term": "average eGFR",
        "kind": "measure",
        "entity": "observation",
        "description": "Mean of each patient's most recent eGFR.",
        "logic": {
            "type": "observation_aggregate",
            "codes": EGFR_CODES,
            "units": EGFR_UNITS,
            "aggregate": "avg",
        },
        "notes": (
            "One value per patient — their latest — then the mean across patients. Never the "
            "mean of every eGFR ever drawn, which would weight a patient by how often they "
            "were tested. Patients with no eGFR on record contribute nothing and are "
            "reported as unmeasured rather than as zero."
        ),
        "synonyms": ["mean egfr", "average kidney function"],
    },
    {
        "term": "lowest eGFR",
        "kind": "measure",
        "entity": "observation",
        "description": "The lowest of the patients' most recent eGFR values.",
        "logic": {
            "type": "observation_aggregate",
            "codes": EGFR_CODES,
            "units": EGFR_UNITS,
            "aggregate": "min",
        },
        "notes": (
            "The worst current kidney function in the group. Same per-patient rule as the mean."
        ),
        "synonyms": ["minimum egfr", "worst egfr"],
    },
    {
        "term": "median creatinine",
        "kind": "measure",
        "entity": "observation",
        "description": "Median of each patient's most recent creatinine, in mg/dL.",
        "logic": {
            "type": "observation_aggregate",
            "codes": CREATININE_CODES,
            "units": CREATININE_UNITS,
            "aggregate": "median",
        },
        "notes": (
            "Median rather than mean because creatinine is right-skewed — a handful of "
            "dialysis patients drag a mean somewhere no individual is. LOINC 2160-0 (serum) "
            "and 38483-4 (blood), mg/dL only; a µmol/L result is 88.4 times larger and is "
            "not silently mixed in."
        ),
        "synonyms": ["typical creatinine"],
    },
    # ---------------------------------------------------------- dimensions
    {
        "term": "sex",
        "kind": "dimension",
        "entity": "patient",
        "description": "Patient sex as recorded.",
        "logic": {"type": "patient_column", "column": "sex"},
        "notes": "As the source records it. Single-valued, so groups add up to the cohort.",
        "synonyms": ["by sex", "gender"],
    },
    {
        "term": "age band",
        "kind": "dimension",
        "entity": "patient",
        "description": "Under 18, 18-44, 45-64, 65-79, 80 and over.",
        "logic": {
            "type": "age_band",
            "bands": [
                {"label": "under 18", "upto": 18},
                {"label": "18-44", "upto": 45},
                {"label": "45-64", "upto": 65},
                {"label": "65-79", "upto": 80},
                {"label": "80+"},
            ],
        },
        "notes": (
            "65 is the geriatric line the `elderly` term uses, and the bands are chosen so "
            "that line is a band boundary: a breakdown by age band and a filter on elderly "
            "should never disagree about who is old. 80 splits the geriatric population "
            "where frailty and polypharmacy change sharply."
        ),
        "synonyms": ["by age", "age group"],
    },
    {
        "term": "nephrotoxic tier",
        "kind": "dimension",
        # `entity` decides which assembler query shape this needs — `patient`
        # because each row is still a group of *patients* (grouped by the
        # tier of drug they're on), even though the tier itself is a fact
        # about a medication. `nephrotoxic medication name` below is the
        # dimension that needs the medication-entity query.
        "entity": "patient",
        "description": "The kidney-risk tier of a patient's current medications.",
        "logic": {
            "type": "medication_group",
            "attribute": NEPHROTOXIC_RISK,
            "exposure": "active",
        },
        "notes": (
            "A patient on drugs in two tiers is counted in both — this dimension fans out. "
            "So only a patient count is allowed against it; an average eGFR "
            "by tier would weight each patient by how many tiers they touch. Patients on "
            "nothing annotated do not appear at all, which is why a count by tier does not "
            "sum to the cohort."
        ),
        "synonyms": ["by nephrotoxic tier", "by kidney risk tier"],
    },
    {
        "term": "nephrotoxic medication name",
        "kind": "dimension",
        "entity": "medication",
        "description": "Which specific nephrotoxic drug, by name.",
        "logic": {
            "type": "medication_name",
            "attribute": NEPHROTOXIC_RISK,
            "in": ["high", "moderate"],
            "exposure": "active",
        },
        "notes": (
            "Unlike `nephrotoxic tier`, this does not fan out patients — each row already is "
            "one medication, so `patient count` works against it as it does anywhere else. "
            "Restricted to the high/moderate tier the "
            "same way `nephrotoxic medication` the filter term is; a drug annotated `low` or "
            "not annotated at all does not get a row, so counts here do not sum to the cohort "
            "either — the denominator is 'patients on any of these drugs', not 'all patients'."
        ),
        "synonyms": ["by nephrotoxic medication", "which nephrotoxin", "drug name"],
    },
    {
        "term": "state",
        "kind": "dimension",
        "entity": "patient",
        "description": "State of residence.",
        "logic": {"type": "patient_column", "column": "state"},
        "notes": (
            "Where the patient lives. A user whose access is confined to certain states sees "
            "only those states here. Synthea generates a population one state at a time, so "
            "this is usually a single group."
        ),
        "synonyms": ["by state"],
    },
]
