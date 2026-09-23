"""Curated clinical judgement about drugs, and how it gets attached to codes.

Synthea supplies an RxNorm code and a display name. It does not say a drug is
nephrotoxic, because that is not a fact about the drug in the dataset — it is a
review decision, of the kind a hospital's own formulary committee makes and
writes down.

**The patterns below are the review; the `medication_annotations` rows are its
result.** Matching runs once at load, against each distinct drug in the
dataset, and what persists is a row per code carrying the tier and the reason.
That is the reviewable artefact: a clinician can read the table and disagree
with a row, which they could not do with a regular expression buried in a
loader.

First match wins, so order matters where patterns could overlap. The list runs
highest risk first for that reason.

**Coverage is deliberately narrow.** These are agents whose renal risk is well
established enough to state plainly. A drug not matched here is not annotated,
and a question about nephrotoxicity will simply not return it — an omission,
which is recoverable, rather than a guess, which is not.
"""

from typing import Final

# (pattern, tier, rationale). Matched case-insensitively against the drug's
# display name as the source spells it.
NEPHROTOXIC_PATTERNS: Final[list[tuple[str, str, str]]] = [
    # --- high: directly tubulotoxic, or a well-established cause of AKI
    (
        r"\b(gentamicin|tobramycin|amikacin|streptomycin|neomycin)\b",
        "high",
        (
            "Aminoglycoside. Accumulates in proximal tubular cells and causes non-oliguric acute "
            "tubular necrosis; risk rises with duration of therapy and trough level."
        ),
    ),
    (
        r"\bvancomycin\b",
        "high",
        (
            "Dose- and trough-dependent tubular injury. Risk compounds sharply in combination "
            "with piperacillin-tazobactam or an aminoglycoside."
        ),
    ),
    (
        r"\bamphotericin\b",
        "high",
        (
            "Direct tubular toxicity with afferent arteriolar vasoconstriction; classically also "
            "causes potassium and magnesium wasting."
        ),
    ),
    (
        r"\b(cisplatin|carboplatin)\b",
        "high",
        (
            "Platinum chemotherapy. Cumulative, dose-dependent proximal tubular injury that is "
            "often only partly reversible."
        ),
    ),
    (
        r"\b(tenofovir disoproxil|cidofovir|foscarnet)\b",
        "high",
        ("Antiviral with established proximal tubular toxicity."),
    ),
    # --- moderate: real risk, usually dose- or duration-dependent
    (
        r"\b(ibuprofen|naproxen|ketorolac|diclofenac|indomethacin|meloxicam|celecoxib|piroxicam|etodolac|nabumetone|sulindac|ketoprofen)\b",
        "moderate",
        (
            "NSAID. Prostaglandin inhibition removes the afferent arteriolar vasodilation the "
            "kidney depends on when volume-depleted; also causes interstitial nephritis."
        ),
    ),
    (
        r"\b(iohexol|iodixanol|iopamidol|ioversol)\b",
        "moderate",
        (
            "Iodinated contrast. Medullary vasoconstriction plus direct tubular toxicity; risk "
            "concentrates in patients who already have reduced eGFR."
        ),
    ),
    (
        r"\b(tacrolimus|cyclosporine|ciclosporin)\b",
        "moderate",
        (
            "Calcineurin inhibitor. Dose-dependent afferent arteriolar vasoconstriction acutely, "
            "and chronic interstitial fibrosis with long exposure."
        ),
    ),
    (
        r"\b(methotrexate)\b",
        "moderate",
        (
            "Crystal nephropathy at high dose, particularly with inadequate hydration or urinary "
            "alkalinisation."
        ),
    ),
    # --- contextual: lowers measured eGFR by design, and protects the kidney
    #
    # This tier is the one that earns the table. Flattening it into the
    # same bucket as gentamicin produces an answer that is wrong in a
    # way a clinician notices immediately and a demo does not.
    (
        r"\b(lisinopril|enalapril|ramipril|captopril|benazepril|quinapril|perindopril|fosinopril|moexipril|trandolapril)\b",
        "contextual",
        (
            "ACE inhibitor. Lowers measured eGFR through efferent arteriolar dilation, not "
            "injury; a creatinine rise of up to ~30% on starting is expected and is not a reason "
            "to stop. Renoprotective in proteinuric CKD — listing it as nephrotoxic inverts the "
            "advice."
        ),
    ),
    (
        r"\b(losartan|valsartan|irbesartan|candesartan|olmesartan|telmisartan|eprosartan)\b",
        "contextual",
        (
            "Angiotensin receptor blocker. Same efferent haemodynamics and the same "
            "renoprotective indication as an ACE inhibitor."
        ),
    ),
]

# The attribute these rows are filed under. Definitions reference it by name.
NEPHROTOXIC_RISK: Final = "nephrotoxic_risk"
