# Optimization Recommendation Report

**Scenario.** 07, Cache Miss Cascade
**Analysis date.** 2026-05-29 (illustrative)
**Status.** Sample output (agent system v0.1, runtime not yet implemented)

> **What's real in this report.** The diagnostic content, the
> finding type, tier assignment, action category, telemetry observation
> values, cross-tier correlation numbers, top cache-key counts, and
> trade-off scores come from real data in the published dataset for
> scenario 07. When the agents run, they will produce equivalent
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

| Field           | Value                                                   |
|-----------------|---------------------------------------------------------|
| Finding type    | `issue_found`                                           |
| Primary tier    | `cache`                                                 |
| Secondary tier  | `database` (downstream symptom)                         |
| Action category | `cache_capacity_adjustment`                             |
| Cost impact     | +$700 / month (reliability spend, not a savings)        |
| Performance     | Application p95 latency: 458 ms -> 200-260 ms estimated |
| SLA impact      | 99.9% target restored                                   |

Scale the Redis cluster from 3 to 6 cache.r6g.large nodes to relieve
memory pressure (currently 88 to 95% used) and reduce evictions.
Implement cache warming on the three hottest key patterns
(`rec:user:*`, `rec:trending:*`, `rec:similar:*`) and redesign these
keys with sharded prefixes (`rec:u:{shard}:{user_id}`) to distribute
load evenly across the expanded cluster. Do not scale the database or
compute tier. They are downstream symptoms, not causes.

---

## Summary

Cache memory pressure is the root cause. The cache cluster sits at
94.6% memory with evictions reaching 180 per second, which drives hit
ratio to 0.669 against the healthy band of >=0.89. Three key patterns
account for the bulk of misses: `rec:user:*` (3.1M miss), `rec:trending:*`
(1.9M miss), and `rec:similar:*` (1.7M miss), or 6.7M of about 22.1M
total accesses.

Misses overflow to the database, pushing query p95 to 316 ms and
application p95 to 458 ms (300 ms SLA target). Database CPU stays
healthy at 58% p95, confirming the DB is absorbing rather than
bottlenecking. Compute is healthy at 70% p95. The fix is contained to
the cache layer.

---

## Specialist findings

The Data Layer Analyst covers both cache and database tiers (per
`docs/agents.md`), so the cache root cause and the DB symptom are
captured inside one specialist's finding.

| Agent              | Finding type     | Confidence | Key observation                                                                                                              | Evidence refs                                                                                  |
|--------------------|------------------|------------|------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| System Mapper      | plan_complete    | -          | Tiers present: compute, database, cache. Cross-tier pairs: cache-db, cache-compute.                                          | `sm_001`                                                                                       |
| Data Layer Analyst | `issue_found`    | High       | Cache 94.6% memory, 180 evictions/sec, hit ratio 0.669 vs 0.89 band. DB query p95 elevated to 316 ms; DB CPU healthy at 58%. | `obs_data_001`, `obs_data_002`, `obs_data_003`, `obs_data_004`, `obs_data_005`, `obs_data_006` |
| Compute Analyst    | `no_issue_found` | High       | CPU stable at 70% p95. Application latency tracks cache-miss / DB-latency pattern, not compute load.                         | `obs_comp_001`, `obs_comp_002`                                                                 |

The Network Analyst was not invoked. No network tier is present in
the Terraform.

Every ID in the Evidence refs column resolves to a logged observation
in `sample_runs/traces/scenario_07_trace.json`. A reviewer can walk
from any claim to the tool call that produced it.

---

## Cross-tier analysis (Evaluator's synthesis step)

**Drift-check.** Both specialist findings are tight. The Data Layer
Analyst's conclusion that cache is the root cause is supported by
`obs_data_001` through `obs_data_004` (cache pressure) plus
`obs_data_006` (DB CPU healthy, so DB is absorbing, not bottlenecking).
The Compute Analyst's no-issue conclusion is justified by stable CPU
within the healthy band.

**Cross-tier correlations.** Three near-perfect zero-lag signals from
`correlation_evidence.json`:

| Interaction | Tiers              | Coefficient | Lag    | What it means                                                                       |
|-------------|--------------------|-------------|--------|-------------------------------------------------------------------------------------|
| `xt_001`    | cache -> database  | -0.961      | 0 min  | Cache misses and DB latency move in lockstep. Misses overflow to the DB.            |
| `xt_002`    | cache -> compute   | -0.963      | 0 min  | Cache misses and application latency move in lockstep. The cascade reaches the user. |
| `xt_003`    | cache -> database  | +0.924      | 0 min  | Cache hit ratio tracks DB cache hit ratio. Misses pressure the DB buffer pool too.   |

Zero-lag inverse correlations this strong are the signature of an
upstream cause, not coincidence. Together with the cache memory
pressure observed directly, they license the cache-first
recommendation and rule out scaling DB or compute as masking-only
fixes.

**Conflict resolution.** No specialist disagreement. The Compute
Analyst's `no_issue_found` is consistent with the Data Layer Analyst's
finding. Both point at cache as the lever.

---

## Trade-off analysis

| Dimension   | Score         | Note                                                                                                                    |
|-------------|---------------|-------------------------------------------------------------------------------------------------------------------------|
| Cost        | -$700 / month | Cache tier doubles from $700 to $1,400. Compute and database tiers unchanged.                                           |
| Performance | +56% p95      | Application p95 from 458 ms to 200-260 ms; cache hit ratio from 0.65 to 0.91.                                           |
| Reliability | SLA restored  | p95 < 300 ms target met. DB query p95 expected to drop about 38%.                                                       |
| Risk        | Moderate      | Hot-shard imbalance if `rec:user:*` cardinality is skewed; mitigated by deploying key redesign with the node expansion. |

The cost line is intentionally negative. This is a reliability
investment, not a cost-reduction recommendation. The trade-off
exchange is explicit: $700/month at the cache tier buys SLA compliance
for a tier-1 recommender service.

A note on alternatives. Scaling the database or compute tier would
move metrics in the right direction by absorbing more of the overflow,
but neither addresses the upstream miss rate. The three zero-lag
cross-tier correlations are why the recommendation is specifically
"fix the cache" and not "scale whatever looks busy."

---

## Evidence anchors

| Source                                               | Observations captured                          | What it supports                                                   |
|------------------------------------------------------|------------------------------------------------|--------------------------------------------------------------------|
| `cache_telemetry.json`                               | `obs_data_001`, `obs_data_002`, `obs_data_003` | Hit ratio 0.669; memory 94.6% p95; evictions 180/sec p95.          |
| `metadata.scenario_specific_evidence.top_cache_keys` | `obs_data_004`                                 | Top 3 key patterns and their hit/miss counts.                      |
| `database_telemetry.json`                            | `obs_data_005`, `obs_data_006`                 | DB query p95 316 ms (elevated); DB CPU 58% p95 (healthy).          |
| `compute_telemetry.json`                             | `obs_comp_001`, `obs_comp_002`                 | CPU stable at 70% p95; app latency 458 ms p95 vs 300 ms SLA.       |
| `correlation_evidence.json`                          | `xt_001`, `xt_002`, `xt_003`                   | Three zero-lag near-perfect correlations establishing the cascade. |

Every claim in this report resolves to one of the source-plus-observation
pairs above. The observation IDs are logged in
`sample_runs/traces/scenario_07_trace.json`.

---

## Evaluator confidence

**High.** Drift-check tight on both specialists. Three independent
zero-lag cross-tier correlations all point to cache as the upstream
cause. The "DB CPU healthy" observation (`obs_data_006`) is the
load-bearing check that ruled out the DB-bottleneck alternative. The
recommended action (cache scaling plus warming plus key redesign)
follows standard patterns with well-understood trade-offs.

---

## How to verify this report

This report is the human-readable summary of the review. The full
audit trail is `sample_runs/traces/scenario_07_trace.json`.

The traceability contract:

- **Each claim in the report carries an evidence_ref ID** (visible
  in the Specialist findings and Evidence anchors tables).
- **Every ID resolves to a specific logged observation** in the trace
  JSON. The resolution is a lookup, not an inference.
- **The trace records each ReAct step**: thought, action, observation,
  observation_id. A reviewer can walk from any cited ID back to the
  tool call that produced it.

**Today:** `scripts/verify_trace.sh` runs the
verification externally. It walks every trace under `sample_runs/traces/`
and confirms each parent reference resolves. Exits non-zero if any
pointer is dangling.

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
| Review packet     | `traces/scenario_07_review_packet.json`     |
| Audit trail       | review_id `rev_c8d4e5f2`                    |
| Trace walkthrough | `sample_runs/traces/scenario_07_trace.json` |

A human reviewer can walk the audit trail by `review_id` to see every
thought, tool call, and observation logged during this analysis.
