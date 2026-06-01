# Judge prompt: score the richness of a cloud-optimization recommendation

You are evaluating a single field of a cloud-optimization recommendation:
the `specific_change` prose. The decision underneath the prose (which tier,
which action category, issue or no issue) has already been graded
deterministically by a separate Correctness check. Your job is to grade
the **richness** of the prose itself: how well does the prediction's
`specific_change` engage with the same evidence and produce the same
depth of recommendation as the gold answer?

You will see two pieces of text:

- GOLD: the hand-crafted `specific_change` from the dataset's gold answer.
- PREDICTION: the `specific_change` from the agent's recommendation.

Both should be addressing the same underlying problem (otherwise Correctness
would have already failed). Your scoring is independent of correctness; you
are only assessing whether the prediction's prose matches the gold's level
of substance and specificity.

## Scoring scale

Score the prediction's `specific_change` on a 0 to 100 scale:

| Range | Label | Means |
| :--- | :--- | :--- |
| 0 to 29 | low richness | Prediction's prose is generic, off-target, evasive, or uses vague synonyms that dodge the specifics. May name the right general direction but offers no concrete plan. Reads like mimicry without substance. |
| 30 to 59 | mid richness | Prediction's prose engages with the right tiers and the right kind of intervention in the right direction. But it lacks the depth of the gold: no specific entities named (tables, queries, instance classes, time windows), no quantified projections in the prose, generic phrasing where the gold is concrete. |
| 60 to 100 | high richness | Prediction's prose demonstrates the kind of specific, evidence-bound reasoning the gold demonstrates. Names concrete entities (specific queries, tables, indexes, instance classes, time windows), specifies magnitudes, and avoids generic phrasing. Reads as substantively equivalent to the gold even if the wording differs. |

A score of 100 means the prediction's prose is substantively equivalent to
the gold (same specifics, same direction, same magnitudes). It does not
require literal text matching; paraphrasing is fine if the substance is
present.

## How to weight semantic failure modes

When you judge, watch for these failure modes that drop the score:

- **Semantic inversion.** Prediction recommends the opposite action even
  if it uses related vocabulary ("we should NOT add a read replica").
  Score < 20.
- **Wrong magnitude.** Prediction picks the right action but specifies
  the wrong number ("add 10 read replicas" when the gold says 2).
  Score 30 to 50 depending on how off-base the magnitude is.
- **Mimicry without substance.** Prediction uses the right vocabulary
  but provides no specifics ("optimize the slow queries" with no
  query, no index, no plan). Score 10 to 25.
- **Direction-right, detail-thin.** Prediction names the right tiers and
  the right kind of action but skips the concrete entities the gold cites.
  Score 30 to 55.
- **Substantively equivalent.** Prediction names the same entities, same
  magnitudes, same direction as the gold, with reasonable paraphrasing.
  Score 75 to 95.

## Output format

Use the `score_richness` tool to return your verdict. The tool takes:

- `score`: integer 0 to 100
- `rationale`: one paragraph explaining the score. Cite specific phrases
  from the prediction and gold to ground the rationale. Note what the
  prediction got right and what it missed.

Do not output prose outside the tool call. Do not return null or skip.
Every prediction gets a score.

## What you are NOT scoring

You are not scoring correctness (whether the enum decisions are right).
You are not scoring the evidence, projected_state, or cost_impact fields
(those are checked structurally by separate rules). You are only scoring
the richness of the `specific_change` prose.

---

## Inputs

GOLD:

{gold_specific_change}

PREDICTION:

{prediction_specific_change}
