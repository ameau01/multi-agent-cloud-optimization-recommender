# Sample runs

Real-looking outputs the system produces for three scenarios. Open
these to see what a finished recommendation looks like for each major
shape of rich recommendation in the dataset.

For the four-layer evaluator that scores these outputs, see
[`docs/eval-set.md`](../docs/eval-set.md). For the architecture, see
[`README.md`](../README.md) and [`ARCHITECTURE.md`](../ARCHITECTURE.md).

## What's here

```
sample_runs/
├── reports/                              3 markdown reports
│   ├── scenario_02_report.md             single-tier (compute / scaling_policy_change)
│   ├── scenario_07_report.md             cross-tier (cache -> database / cache_capacity_adjustment)
│   └── scenario_08_report.md             cross-tier (database -> compute / query_cache_optimization)
├── traces/                               3 audit trails (JSON + human-readable markdown)
│   ├── scenario_02_trace.json
│   ├── scenario_02_trace.md
│   ├── scenario_07_trace.json
│   ├── scenario_07_trace.md
│   ├── scenario_08_trace.json
│   └── scenario_08_trace.md
└── README.md                             (this file)
```

These files are **vendored read-only output** from a live Opus end-to-end
run on 2026-06-04 (cycle IDs below). Their source composites live in the
audit DB from that run, not on disk — there is no `raw_recommendation.json`
in this folder to re-render. To produce a fresh report from a live cycle,
run the agents against an app and use the wrapper scripts:

```bash
bash scripts/run_agents.sh app-08
bash scripts/render_recommendation.sh app-08 --out /tmp/report.md
bash scripts/render_evidence_trace.sh app-08 --format json --out /tmp/trace.json
```

The three picks match the three scenarios vendored in
[`dataset-examples/`](../dataset-examples/), so a reviewer can read
the input telemetry for each scenario, then the report the system
produces for it, then the trace that produced the report.

## The three reports

| File                                                                  | Scenario | Tier pairing            | Action category             | What it demonstrates                                                                  |
|-----------------------------------------------------------------------|----------|-------------------------|-----------------------------|---------------------------------------------------------------------------------------|
| [`reports/scenario_02_report.md`](reports/scenario_02_report.md)      | 02       | compute (single-tier)   | `scaling_policy_change`     | Time-pattern recognition. Spiky load fixed by scheduled scaling, not a bigger box.    |
| [`reports/scenario_07_report.md`](reports/scenario_07_report.md)      | 07       | cache -> database       | `cache_capacity_adjustment` | Upstream-cause identification. Cache pressure cascades into DB load and app latency.  |
| [`reports/scenario_08_report.md`](reports/scenario_08_report.md)      | 08       | database -> compute     | `query_cache_optimization`  | Cross-tier reasoning. DB query latency cascades into compute waste; fix at the DB.    |

Three different primary tiers. Three different action categories. One
single-tier scenario and two cross-tier scenarios. A reviewer scanning
the trio sees the breadth of recommendation shapes the system
produces.

The short-circuit cases (`no_issue_found`, `diagnostic_deferral`) are
deliberately excluded here. Their gold answers are intentionally thin
because the right answer is "no action" or "defer until more data."
For the full short-circuit story, see
[`docs/eval-set.md`](../docs/eval-set.md).

## What's NOT here

- **Mock predictions for testing** moved to
  [`tests/integration/fixtures/mock_predictions/`](../tests/integration/fixtures/mock_predictions/).
  These are deliberately-degraded JSON predictions used by
  `test_edge_cases.py` to prove the evaluator's discrimination logic.
- **Trace-verification utility** lives at
  [`scripts/verify_trace.sh`](../scripts/verify_trace.sh) (a bash wrapper
  around [`tests/verify_trace.py`](../tests/verify_trace.py)).

This folder now holds only the human-readable artifacts. The machinery
that exercises and verifies the evaluator lives in `tests/` and
`scripts/`.

## Status of the example outputs

These are **real outputs from a live run** of the agent system on
2026-06-04 (Opus end-to-end, both specialist and evaluator tiers). All
18 scenarios passed Shape + Correctness + Mid + Rich; the three shown
here are the canonical demos.

- `cycle_20260604_143726_ddaeaf53` — app-02
- `cycle_20260604_150000_a952f749` — app-07
- `cycle_20260604_150610_37995130` — app-08

Every evidence reference in every report resolves to a real
observation row in the corresponding trace JSON. The trace JSONs are
machine-readable; the trace markdown files are the same data rendered
for human review.

## Traceability model

The reports and the trace JSONs together implement a strict
traceability contract.

- **The trace JSON is the source of truth.** Every ReAct step has an
  explicit `observation_id`. Every finding's `evidence_refs` list
  cites those IDs literally.
- **The report references IDs in two places.** The Specialist findings
  table shows the evidence_refs each finding produced. The Evidence
  anchors table shows which source files each observation came from.
- **Resolution is a lookup, not an inference.** A reviewer copies an
  ID from the report and finds it in the trace JSON with one search.

The Action Harness enforces this contract at gate time. A report with
dangling references would fail the gate and not surface.

Run `scripts/verify_trace.sh` to confirm every parent reference
in every trace resolves. The script discovers every
`scenario_NN_trace.json` under `sample_runs/traces/`, walks each one
backward, and exits non-zero if any pointer in any trace is dangling.

## Format

Reports are markdown. Convert to PDF or HTML with:

```bash
pandoc sample_runs/reports/scenario_08_report.md -o report.pdf
pandoc sample_runs/reports/scenario_08_report.md -o report.html
```

Trace files are JSON with the structure described in `docs/audit-trail.md`.
