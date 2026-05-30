# Evaluation

The system is evaluated against the 18-scenario dataset published at [`ameau01/synthesized-cloud-optimization-recommendations`](https://huggingface.co/datasets/ameau01/synthesized-cloud-optimization-recommendations). This doc defines what "the system passes" means. It also defines how agent output is scored against the hand-crafted recommendation each scenario carries.

Without an evaluation methodology, the demo has no objective success criterion. Specifying one is part of what makes this a portfolio project.

## Two evaluation layers

There are two evaluation systems. They operate in different layers and should stay independent.

| Layer            | What it evaluates                                                               | Where it lives                         |
| ---------------- | ------------------------------------------------------------------------------- | -------------------------------------- |
| Dataset QA       | Whether the synthetic dataset itself is well-formed                             | Dataset generation pipeline (separate) |
| Agent evaluation | Whether the agent's recommendation matches the hand-crafted target in substance | This project, under `src/evaluator/`   |

Dataset QA validated the inputs once. That work is done. Agent evaluation validates the outputs. This doc covers the agent side.

## The three-tier evaluator

For each scenario, the agent produces a review packet with a recommendation. The evaluator scores that recommendation across three tiers. Each tier groups related checks.

### Floor: structure and category

Floor confirms the prediction is shaped like an optimization recommendation. It does not score quality.

Checks:

- `finding_type` is one of the values the scenario allows.
- `primary_tier` is one of the allowed tier names.
- `action_category` is one of the allowed values.
- `specific_change` is a non-empty string of at least 20 characters.

A reasonable agent passes Floor 18 out of 18.

### Mid: depth

Mid confirms the recommendation engages with the right evidence.

Checks:

- `secondary_tier` is one of the values the scenario allows (when the scenario flags multi-tier reasoning).
- `action_keyword_groups`: the prediction text contains keywords from at least N of the scenario's required OR-groups. Match is case-insensitive substring.
- `multi_tier_evidence`: for scenarios that demand multi-tier reasoning, the prediction text mentions each required tier by name.

A careful single-shot agent that reads the telemetry passes most of Mid.

### Rich: orchestrated synthesis

Rich confirms the recommendation shows the kind of cross-fixture synthesis that orchestration produces.

Checks:

- `fixture_citation`: when the scenario flags a named fixture (such as `top_queries`, `top_cache_keys`, `per_instance_breakdown`), the prediction cites at least one identifier from that fixture.
- `cost_impact_quantified`: the `cost_impact` section includes a non-zero numeric field. Skips for no-action, deferral, and SLA-review scenarios.
- `projected_state_quantified`: the `projected_state` section includes at least one numeric field. Skips under the same rules.
- `evidence_structured`: the `evidence` section totals at least three bullets across telemetry, infrastructure, and correlation categories.

Single-shot agents typically fail Rich. Orchestrated agents pass.

## Why three tiers, not five

The dataset originally carried a five-dimension rubric (R1 through R5). That rubric collapsed two distinct concerns: was the agent shaped right at all, and did the agent really engage with the data. Floor, Mid, and Rich separate these into independently meaningful tiers. Each tier has a clear discrimination story.

- Floor passes for any agent that emits a shape-valid recommendation.
- Mid separates careful from careless single-shot agents.
- Rich separates orchestrated from single-shot.

## Determinism, not LLM-as-judge

The evaluator uses pure-Python checks against per-scenario expectations. Same prediction file plus same expectations file equals the same score every time. No LLM call, no network, no flakiness.

An earlier version used LLM-as-judge with Sonnet. It was replaced for two reasons. First, judge runs were not reproducible across sessions. Second, the rubric was hard to audit when expressed as prose. The deterministic version reads as Python that a reviewer can step through.

## Per-scenario and aggregate reporting

**Per-scenario** Floor, Mid, Rich each pass or fail. The output is a vector of three booleans per scenario, not a single composite score.

**Aggregate across 18** The report shows per-tier totals. Example: "Floor 18/18, Mid 17/18, Rich 12/18." This surfaces patterns. The orchestrated-vs-single-shot story shows up here.

A single composite "X percent passed" number is intentionally not produced. It hides which tier failed.

## Expected discrimination across baselines

The eval-set is calibrated so the three tiers separate different kinds of agents. The expected scores per baseline are below. These numbers are projections, not measurements. Real baseline runs will be published in `baselines.md` once they execute.

| Baseline                                | Floor (18) | Mid (18) | Rich (18) |
| --------------------------------------- | ---------- | -------- | --------- |
| Trivial (returns one canned answer)     | 1 to 2     | 0        | 0         |
| Random (picks allowed values randomly)  | 4 to 6     | 0        | 0         |
| Single-shot frontier LLM, no tools      | 18         | 12 to 15 | 8 to 12   |
| Orchestrated multi-agent (this project) | 18         | 18       | 18        |

The table tells the discrimination story.

**Floor is meant to be easy** Any agent that emits well-formed JSON with allowed category values passes Floor. Floor is a shape check, not a quality check.

**Mid separates careless from careful** A strong single-shot model that actually reads the telemetry can pass most of Mid. A random or trivial agent cannot. Mid says "did the agent engage with the data."

**Rich is meant to be hard** Rich requires fixture citations and quantified projections. A single-shot agent reasoning over four tiers in one prompt rarely produces both. It runs out of attention before it cites the named query from `top_queries` or quantifies the projected cost. An orchestrated agent passes Rich because each specialist has narrow scope, so each one can chase fixtures and quantification deeply inside its tier.

This is what makes the multi-agent architecture earn its complexity. If a single-shot frontier model could pass Rich 18/18, the orchestration
would not be defensible. The expected gap between rows three and four is the architectural justification.

## Calibration discipline

If a single-shot baseline ever scores 17 or 18 on Rich, the tier is too lenient and the checks get tightened. We do not lower the bar by loosening the hand-crafted recommendations. The gold answers are the ground truth; the tier checks are the dial.

## The three subset modes

Running the full 18 scenarios is the truth signal but takes time. Three subset modes serve different purposes.

**Smoke test (3 scenarios).** Scenarios 01, 06, 07. One single-tier negative, one healthy, one cross-tier. Confirms the pipeline runs end to end. Useful for rapid iteration.

**Coverage subset (6 scenarios).** Scenarios 01, 04, 07, 09, 12, 17. One of each major scenario type. Useful for catching regressions across architectural patterns without running the full eval.

**Full eval (18 scenarios).** All scenarios. Run before any release or after any change that could plausibly affect multiple scenarios.

The smoke test should complete in minutes. The full eval takes longer depending on LLM latency and ReAct loop depth.

## What the evaluation does not do

**Does not measure latency or throughput** Operational performance is a separate concern. It belongs in observability metrics outside the audit trail.

**Does not re-validate the audit trail** The audit trail's correctness is structurally enforced by the Reasoning Harness's evidence-binding. The evaluator checks recommendation content, not chain integrity.

**Does not score the agent against itself across runs** LLM non-determinism makes cross-run comparisons noisy. The methodology compares agent output to the hand-crafted target, not to prior agent runs.

**Does not gate releases** This is a portfolio project. There is no release gate. In a production deployment, the methodology would inform a gate, but that is out of scope.

## How to run the evaluator

The evaluator is a CLI under `src/evaluator/`. It has no third-party runtime dependencies. It reads scenarios from the Hugging Face cache managed by `src/data_loader.py`, so no separate dataset download or `--dataset` flag is needed for normal use.

```bash
# Full three-tier scoring (default)
python -m src.evaluator.eval --predictions your_predictions.json

# One tier only
python -m src.evaluator.eval --predictions your_predictions.json --tier floor
python -m src.evaluator.eval --predictions your_predictions.json --tier mid
python -m src.evaluator.eval --predictions your_predictions.json --tier rich

# Machine-readable JSON (for CI dashboards, regression tracking)
python -m src.evaluator.eval --predictions your_predictions.json --json > scores.json

# Use a local dataset copy instead of the HF cache (for offline runs)
python -m src.evaluator.eval --predictions your_predictions.json --dataset path/to/local/dataset
```

### What the output looks like

```
=========================================================================
  sid   floor    mid    rich  notes
  ------------------------------------------------------------------------
  01     PASS   PASS   PASS
  02     PASS   PASS   FAIL  rich:fixture_citation
  ...
  Totals: floor 18/18  mid 17/18  rich 12/18
==========================================================================
```

A failure note lists the failing check names. Use `--json` for full
per-check detail.

### Exit codes

- `0`: every submitted prediction passed every requested tier.
- `1`: at least one tier failed for at least one scenario.
- `2`: usage error (missing file, malformed JSON, dataset not reachable).

## The evaluator as a build artifact

The evaluator is bundled inside this orchestration project. The pieces:

- `src/evaluator/tiers.py`: Floor + Mid + Rich check logic. Pure Python,
  no LLM, no network.
- `src/evaluator/expectations/NN/evaluation_expectations.json`: the
  per-scenario allowed values, keyword groups, and fixture names. Same
  shape across all 18 scenarios; only values change.
- `src/evaluator/eval.py`: the CLI scorer.

The dataset published on Hugging Face does not ship a quality scorer. It ships gold answers plus a Floor sanity check. The full Floor + Mid + Rich evaluator is owned by this project. See [decisions.md](decisions.md) section 12 for the ownership rationale..

A `make eval` entry point runs the evaluator over a predictions file and writes a structured report. The report is itself an artifact that can be inspected, archived, and compared across versions of the agent.

This closes the loop on "what does it mean for this system to work?" There is a concrete answer. It is reproducible. Same prediction file plus same expectations equals the same score, every time.
