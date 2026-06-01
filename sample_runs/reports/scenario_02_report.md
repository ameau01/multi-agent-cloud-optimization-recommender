# Optimization Recommendation Report

**Scenario.** 02, Spiky Compute Load
**Analysis date.** 2026-05-29 (illustrative)
**Status.** Sample output (agent system v0.1, runtime not yet implemented)

> **What's real in this report.** The diagnostic content, the
> finding type, tier assignment, action category, telemetry observation
> values, time-pattern detection, infrastructure context, and trade-off
> scores come from real data in the published dataset for scenario 02.
> When the agents run, they will produce equivalent content from the
> same sources.
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

| Field           | Value                                                        |
|-----------------|--------------------------------------------------------------|
| Finding type    | `issue_found`                                                |
| Primary tier    | `compute`                                                    |
| Secondary tier  | none (single-tier topology)                                  |
| Action category | `scaling_policy_change`                                      |
| Cost impact     | -$2,496 / month (48% savings)                                |
| Performance     | Application p95 latency: 572 ms peak -> 200-280 ms estimated |
| SLA impact      | 99.9% target preserved during spike windows                  |

Replace the fixed 6 x m5.large fleet with a scheduled auto-scaling
group: 3 instances off-peak (weekday nights and weekends), 6 instances
during weekday daytime, 9 instances during the two predictable spike
windows (weekdays 09:45-11:15 and 14:45-16:15 UTC). Layer a
target-tracking policy (CPU target 50%) on top as a reactive safety net.

---

## Summary

A compute-only deployment is comfortable at baseline (CPU p50 around
34%) but catastrophically under-provisioned during two predictable
daily spike windows on weekdays. The spikes hold on 11 of 14 observed
days, with peak CPU at 96% and application p95 latency at 572 ms,
breaching the 300 ms SLA target.

The pattern is periodic and well-aligned with checkout-traffic
timing, which makes it addressable by scheduled scaling. Reactive
auto-scaling alone would lag the spike onset by 5 to 10 minutes and
miss the early burst.

---

## Specialist findings

Only the Compute Analyst was invoked. The System Mapper observed that
no database, cache, or network tier is present in the Terraform, so no
other specialists had any tier to read.

| Agent           | Finding type  | Confidence | Key observation                                                                                                               | Evidence refs                                                  |
|-----------------|---------------|------------|-------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------|
| System Mapper   | plan_complete | -          | Single tier present: compute. No cross-tier pairs to analyze.                                                                 | `sm_001`                                                       |
| Compute Analyst | `issue_found` | High       | Fixed 6-instance fleet, no ASG. CPU spikes to 96% in two predictable daily weekday windows; p95 latency 572 ms vs 300 ms SLA. | `obs_comp_001`, `obs_comp_002`, `obs_comp_003`, `obs_comp_004` |

Every ID in the Evidence refs column resolves to a logged observation
in `sample_runs/traces/scenario_02_trace.json`. A reviewer can walk
from any claim to the tool call that produced it.

---

## Cross-tier analysis (Evaluator's synthesis step)

**Drift-check.** The single specialist finding is tight. The
time-pattern observation (`obs_comp_002`) directly supports the
recommendation for scheduled scaling rather than reactive scaling.

**Cross-tier interactions.** None. `correlation_evidence.json` is
empty for scenario 02 because no other tier is present to correlate
against. The Evaluator records this as an empty
`cross_tier_interactions` array rather than skipping the step, so
downstream consumers can distinguish "no interactions found" from "no
interactions checked."

**Conflict resolution.** Not applicable; only one specialist produced
a finding.

---

## Trade-off analysis

| Dimension   | Score           | Note                                                                                |
|-------------|-----------------|-------------------------------------------------------------------------------------|
| Cost        | +$2,496 / month | 48% reduction. Blended average of 3.7 instances vs current fixed 6.                 |
| Performance | +51% p95        | Application p95 from 572 ms peak to 200-280 ms; CPU peak from 96% to 65%.           |
| Reliability | SLA restored    | p95 < 300 ms target met during spike windows with 9-instance headroom.              |
| Risk        | Low to moderate | Spike timing may shift seasonally; target-tracking policy mitigates within 5-7 min. |

This is the unusual case where cost savings and reliability move in
the same direction. The fixed fleet over-provisions off-peak (paying
for capacity that idles) and under-provisions during spikes (failing
SLA). Scheduled scaling fixes both at once.

---

## Evidence anchors

| Source                                             | Observations captured | What it supports                                                 |
|----------------------------------------------------|-----------------------|------------------------------------------------------------------|
| `compute_telemetry.json` (cpu_p95)                 | `obs_comp_001`        | CPU distribution: p95 91.2%, peak 95.9%, stddev 14.1%.           |
| `compute_telemetry.json` (cpu_p95 time pattern)    | `obs_comp_002`        | Two daily weekday spike windows; 11 of 14 days hold the pattern. |
| `compute_telemetry.json` (application_p95_latency) | `obs_comp_003`        | p95 487.5 ms, peak 572.4 ms vs 300 ms SLA threshold.             |
| `main.tf`                                          | `obs_comp_004`        | 6 x m5.large fixed fleet, no ASG, no scaling policy.             |

Every claim in this report resolves to one of the source-plus-observation
pairs above. The observation IDs are logged in
`sample_runs/traces/scenario_02_trace.json`.

---

## Evaluator confidence

**High.** Drift-check tight on the single specialist. The time-pattern
signal (`obs_comp_002`) is the load-bearing observation: it converts a
"CPU is sometimes high" claim into a "CPU spikes are scheduled and
predictable" claim, which is what licenses scheduled scaling as the
right tool. The recommendation follows standard ASG patterns with
well-understood trade-offs.

---

## How to verify this report

This report is the human-readable summary of the review. The full
audit trail is `sample_runs/traces/scenario_02_trace.json`.

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
  `drift_checks` -> `specialist_findings` -> `react_steps` ->
  `observations`. Every parent reference resolves to a logged node.
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
| Review packet     | `traces/scenario_02_review_packet.json`     |
| Audit trail       | review_id `rev_b7c3d4e1`                    |
| Trace walkthrough | `sample_runs/traces/scenario_02_trace.json` |

A human reviewer can walk the audit trail by `review_id` to see every
thought, tool call, and observation logged during this analysis.
