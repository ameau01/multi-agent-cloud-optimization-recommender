# Optimization Recommendation Report

**Scenario.** 08, Database Bottleneck Impact
**Analysis date.** 2026-05-29 (illustrative)
**Status.** Sample output (agent system v0.1, runtime not yet implemented)

> **What's real in this report.** The diagnostic content, the
> finding type, tier assignment, action category, telemetry observation
> values, cross-tier correlation numbers, fixture citations, and
> trade-off scores come from real data in the published dataset for
> scenario 08. When the agents run, they will produce equivalent
> content from the same sources.
>
> **What's illustrative.** Timestamps, durations, the `review_id`, the
> bundle hash, drift-check verdicts, and the Action Harness gate
> verdict are placeholders. Those values come from a real review only
> after the agent system runs (see CHANGELOG.md).
>
> **What's verifiable today.** Trace structure and the traceability
> contract. Run `scripts/verify_trace.sh` to confirm every
> reference in the companion trace JSON resolves.

---

## Final recommendation

| Field           | Value                                              |
|-----------------|----------------------------------------------------|
| Finding type    | `issue_found`                                      |
| Primary tier    | `database`                                         |
| Secondary tier  | `compute` (downstream symptom)                     |
| Action category | `query_cache_optimization`                         |
| Cost impact     | +$2,400 / month (reliability spend, not a savings) |
| Performance     | Application p95 latency: 660 ms -> 220 ms          |
| SLA impact      | 99.9% target preserved                             |

Add composite indexes on the top six slowest queries. Provision two
read replicas (db.r6g.xlarge) with read/write splitting on the
database tier. Do not scale compute. The bottleneck is downstream.

---

## Summary

Slow database queries during business hours cascade into elevated
application latency on the compute tier. Six queries account for the
worst p95 latencies, all of them missing covering indexes. Compute is
correctly sized at 8 m5.large instances with CPU p95 stable at 27%.

The right action is to fix the database. Scaling compute would not
address the root cause.

---

## Specialist findings

| Agent              | Finding type     | Confidence | Key observation                                                       | Evidence refs                                  |
|--------------------|------------------|------------|-----------------------------------------------------------------------|------------------------------------------------|
| System Mapper      | plan_complete    | -          | Tier graph: compute, database, network. Cross-tier pair: db-compute.  | `sm_001`                                       |
| Data Layer Analyst | `issue_found`    | High       | Six slow queries with p95 of 380 to 820 ms, holding on 11 of 14 days. | `obs_data_001`, `obs_data_002`, `obs_data_003` |
| Compute Analyst    | `no_issue_found` | High       | CPU p95 stable at 27%. Latency tracks DB, not compute load.           | `obs_comp_001`, `obs_comp_002`                 |
| Network Analyst    | `no_issue_found` | High       | Bandwidth and packet loss within healthy bands.                       | `obs_net_001`, `obs_net_002`                   |

Every ID in the Evidence refs column resolves to a logged observation
in `sample_runs/traces/scenario_08_trace.json`. A reviewer can walk from
any claim to the tool call that produced it.

---

## Cross-tier analysis (Evaluator's synthesis step)

**Drift-check.** All three specialist findings are tight. Each
conclusion resolves to specific logged tool-call observations. No
internal contradictions.

**Cross-tier correlation (`xt_001`).** `correlation_evidence.json`
shows db_query_p95_latency_ms leads application_p95_latency_ms by 15
minutes with a Pearson coefficient of 0.945 and an alignment score of
0.979. This is the signature of a downstream cascade, not coincidence.

**Conflict resolution.** No specialist disagreement. Compute and
Network both produced `no_issue_found` with high confidence. The
database finding is the only actionable claim and the only one cited
in the recommendation.

---

## Trade-off analysis

| Dimension   | Score           | Note                                                   |
|-------------|-----------------|--------------------------------------------------------|
| Cost        | -$2,400 / month | Two read replicas at db.r6g.xlarge add about $2,400/mo |
| Performance | +66% p95        | Application p95 latency 660 ms -> 220 ms during peak   |
| Reliability | Improved        | Closes SLA breach on tier-1 checkout service           |
| Risk        | Low             | Standard composite-index and read-replica patterns     |

The cost line is intentionally negative. This is a reliability
investment, not a cost-reduction recommendation. The trade-off
exchange is explicit: $2,400/month buys an SLA-compliant checkout
flow.

---

## Evidence anchors

| Source                                            | Observations captured          | What it supports                                  |
|---------------------------------------------------|--------------------------------|---------------------------------------------------|
| `metadata.scenario_specific_evidence.top_queries` | `obs_data_002`                 | Six query patterns with counts and p95 latencies  |
| `correlation_evidence.json`                       | `xt_001`                       | 15-minute database-to-compute cascade signature   |
| `database_telemetry.json`                         | `obs_data_001`, `obs_data_003` | Query latency distribution, connection pool usage |
| `compute_telemetry.json`                          | `obs_comp_001`, `obs_comp_002` | Compute health (CPU p95 stable, latency rising)   |
| `network_telemetry.json`                          | `obs_net_001`, `obs_net_002`   | No network contribution to the latency rise       |

Every claim in this report resolves to one of the source-plus-observation
pairs above. The observation IDs are logged in
`sample_runs/traces/scenario_08_trace.json`.

---

## Evaluator confidence

**High.** Drift-check tight on all three specialists. Strong cross-tier
correlation signal (`xt_001`). No contradictory observations. The
proposed action follows standard patterns (composite indexes plus read
replicas) with well-understood trade-offs.

---

## How to verify this report

This report is the human-readable summary of the review. The full
audit trail is `sample_runs/traces/scenario_08_trace.json`.

The traceability contract:

- **Each claim in the report carries an evidence_ref ID** (visible
  in the Specialist findings and Evidence anchors tables).
- **Every ID resolves to a specific logged observation** in the trace
  JSON. The resolution is a lookup, not an inference.
- **The trace records each ReAct step**: thought, action, observation,
  observation_id. A reviewer can walk from any cited ID back to the
  tool call that produced it.

**Today:** `scripts/verify_trace.sh` runs the
verification externally. It enumerates every evidence_ref the report
cites and confirms each resolves to a logged observation. Exits
non-zero if any pointer is dangling.

**When the agent system lands:** the Action Harness's
`evidence_completeness` check runs the same logic at gate time on every
live review. The `action_harness_gate.checks[1].verified_refs` field in
the trace is what carries the result. A dangling reference would fail
the gate and the report would not be surfaced for review.

Same contract, two enforcement points. `scripts/verify_trace.sh` is the
today-substitute; the gate is the runtime check that follows when the
agents land.

## Replayability

The trace is structured so a reviewer can walk forward or backward
through the chain without inference:

- **Backward walk** from `review_packet` -> `gate` -> `synthesis` ->
  `drift_checks` and `cross_tier_interactions` -> `specialist_findings`
  -> `react_steps` -> `observations`. Every parent reference resolves
  to a logged node.
- **Forward walk** is the chronological order in the trace JSON.
- **Verification:** run `scripts/verify_trace.sh` to confirm
  every reference resolves cleanly. The script walks the chain
  backward and exits non-zero if any pointer is dangling.

The honest scope of "replayability." The recorded reasoning chain is
complete and traversable in both directions. Replay reconstructs
**what happened**. It does not re-derive answers by re-running the
model. LLM output at non-zero temperature is non-deterministic; the
audit trail captures the reasoning that occurred, not a reproducible
recipe for re-deriving it. This is true of every LLM-based system and
is acknowledged here explicitly.

---

## Handoff

| Field             | Value                                       |
|-------------------|---------------------------------------------|
| State             | Ready for human review                      |
| Review packet     | `traces/scenario_08_review_packet.json`     |
| Audit trail       | review_id `rev_a3f9b21c`                    |
| Trace walkthrough | `sample_runs/traces/scenario_08_trace.json` |

A human reviewer can walk the audit trail by `review_id` to see every
thought, tool call, and observation logged during this analysis.
