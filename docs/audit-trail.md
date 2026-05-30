# Audit Trail

The audit trail is the system's primary observability mechanism. It is treated as its own architectural component, not logging bolted onto each agent, because it is fundamentally different code from the agents themselves. Structured persistent storage with strong schema discipline, not agentic orchestration.

This doc covers what the audit trail captures, how it supports replay, why the storage choice is relational rather than vector, and what the schema looks like.

## What the audit trail captures

Every significant event in a review cycle is a record. The trail is rich enough that a reviewer reading it should be able to reconstruct exactly what the system did and why.

**Trigger and ingest records** When a review was requested, by what trigger, against which application, with what scenario hash.

**System Mapper records** The architecture model produced for this review (tiers, dependencies, analysis plan). Any parsing diagnostics from Terraform.

**Supervisor decision records** Which specialists were invoked and why. Low-confidence handling decisions. Retry decisions. Escalations.

**Specialist ReAct step records** For each specialist, every cycle of the ReAct loop: the thought, the action (tool call with parameters), the observation (tool result). Each step is its own record, ordered.

**Specialist finding records** The structured output from each specialist: `finding_type`, recommendation (if any), `evidence_refs`, `reasoning_trace` summary, specialist confidence with breakdown.

**Evaluator records** Drift-check verdicts per specialist. Cross-tier interactions identified. Trade-off scores across cost / performance / reliability. Final synthesized recommendation. Evaluator confidence with breakdown.

**Action Harness records** The recommendation gate verdict. The severity classification. The duplication check result.

**Review packet records** The full review packet as surfaced to the human reviewer. Stored as the canonical artifact, not just a pointer to it.

**HITL records** The human's decision (approve / reject / defer), timestamp, and any notes the reviewer attached.

Every record carries:

- A stable unique identifier.
- A timestamp.
- The agent or harness that emitted it.
- The review-cycle identifier (so all records from one cycle can be retrieved together).
- Foreign-key references to upstream records in the causal chain.

The foreign keys are what make the trail navigable: from a final HITL approval, the reader can walk backward through Action Harness gate → review packet → Evaluator synthesis → drift-check verdicts → specialist findings → specialist ReAct steps → tool calls → ingest records.

## Append-only by design

Records are never updated or deleted. This is the property that makes "replayable" real rather than aspirational.

If a recommendation needs to be corrected, for example, the human reviewer rejects it and provides feedback, the correction is a **new record** that references the original. The historical state at any past point in time is exactly the records that existed up to that point. Nothing is rewritten retroactively.

This discipline matters because the alternative (mutable records) makes the audit trail unreliable for governance purposes. A governance reviewer asking "what did the system recommend three months ago?"


In storage terms, append-only is enforced both by schema discipline (no `UPDATE` paths in the data access layer) and by application discipline (corrections produce new records). For the portfolio in SQLite, this is straightforward; for a production deployment in Postgres, the same pattern applies.

## Replayability

A review is **replayable** if, given the review-cycle identifier, the full reasoning chain can be reconstructed from the audit trail by following foreign-key references in either direction.

What this means in practice:

- Every recommendation has explicit citations to the Evaluator records that produced it.
- Every Evaluator record has explicit citations to the specialist findings that informed it (via `contributing_findings`).
- Every drift-check verdict names the specific finding it judged (via `target_finding_id`).
- Every specialist finding has explicit citations to the ReAct observations it relied on (via `evidence_refs`).
- Every ReAct step has an `observation_id` so the finding's citations resolve to lookable records.
- Every tool call records the scenario hash and exact parameters used.

A developer or reviewer can walk the chain forward or backward. The system's reasoning is not a black box; it is a navigable graph.

**What replayability does NOT mean** Replay reconstructs what happened from the stored records. It does not re-run the LLM. LLM outputs are non-deterministic, so the audit trail captures the actual outputs that occurred.

### What's verifiable today

The full agent system is not yet implemented (Phase 7 in `CHANGELOG.md`). Until it is, the auditability contract is verified by:

- **`examples/verify_trace.py`** A standalone script that walks the sample trace backward and confirms every parent reference resolves. Runs in under a second; exits non-zero if any pointer is dangling.
- **`examples/traces/scenario_08_trace.json`** The sample trace with all the required IDs and foreign keys in place.

When the agents are implemented, the Action Harness's `evidence_completeness` check runs the same verification at gate time on every live review. The `verified_refs` field on that check is what carries the result.

## Why relational, not vector

A vector database was considered for the audit trail and rejected. The reasoning matters for the design-decisions narrative, see `decisions.md` for the long-form version. Briefly:

**The audit trail's access patterns are relational**

- Append-only writes of structured records.
- Foreign-key traversal to reconstruct causal chains.
- Structured queries ("show all recommendations rejected by HITL in the last 30 days," "show all reviews where drift-check flagged a specialist").
- Deterministic replay from a known starting point.

None of these are similarity-search patterns. A vector database would turn deterministic replay into approximate similarity, drop the foreign-key guarantees, and provide nothing the audit trail needs that relational storage does not already give.

A vector database **would** be appropriate for a different concern, semantic retrieval over past reasoning traces, where an agent wants to find scenarios similar to the current one. That is a separate concern (agent memory), not currently in scope, and it would be a parallel storage system, not a replacement for the relational audit trail.

**Storage engine** SQLite for the portfolio. Single file, zero infrastructure, ships with Python. The audit trail demo runs anywhere. The senior signal is the schema design, not the engine, the same schema upgrades cleanly to Postgres for production.

## Conceptual schema

The conceptual schema below describes the record categories and their relationships. Concrete column types are deferred to implementation.

```text
reviews
 - review_id (primary key)
 - application_id
 - trigger_type
 - scenario_hash
 - started_at
 - completed_at
 - final_status   (approved | rejected | deferred | error)

ingest_validations
 - validation_id
 - review_id (FK → reviews)
 - check_name
 - verdict
 - details
 - emitted_at

architecture_models
 - model_id
 - review_id (FK → reviews)
 - tiers      (structured: list of tier descriptors)
 - dependencies   (structured: list of inter-tier edges)
 - analysis_plan  (structured: specialists required, cross-tier pairs)
 - emitted_at

supervisor_decisions
 - decision_id
 - review_id (FK → reviews)
 - decision_type  (invoke_specialist | retry | escalate | aggregate)
 - decision_details (structured)
 - emitted_at

specialist_steps
 - step_id
 - review_id (FK → reviews)
 - specialist    (compute | data_layer | network)
 - step_index    (ordinal within the specialist's ReAct loop)
 - thought
 - action_name
 - action_params  (structured)
 - observation   (structured)
 - emitted_at

specialist_findings
 - finding_id
 - review_id (FK → reviews)
 - specialist
 - finding_type   (issue_found | no_issue_found | insufficient_data)
 - recommendation  (nullable)
 - evidence_refs  (structured: list of step_id references)
 - reasoning_trace_summary
 - specialist_confidence
 - confidence_breakdown (structured)
 - emitted_at

evaluator_drift_checks
 - drift_check_id
 - review_id (FK → reviews)
 - target_finding_id (FK → specialist_findings)
 - verdict     (tight | loose | contradictory)
 - reasoning
 - emitted_at

evaluator_records
 - evaluator_id
 - review_id (FK → reviews)
 - cross_tier_interactions (structured)
 - trade_off_scores    (structured: cost, performance, reliability)
 - synthesis        (structured: balanced recommendation)
 - evaluator_confidence
 - confidence_breakdown  (structured)
 - contributing_findings  (structured: list of finding_id references)
 - emitted_at

action_harness_gate_records
 - gate_id
 - review_id (FK → reviews)
 - evaluator_id (FK → evaluator_records)
 - well_formedness_verdict
 - evidence_completeness_verdict
 - severity_classification
 - duplication_check_result
 - overall_verdict  (pass | flagged | rejected)
 - emitted_at

review_packets
 - packet_id
 - review_id (FK → reviews)
 - gate_id (FK → action_harness_gate_records)
 - packet_contents    (canonical JSON of what the human sees)
 - emitted_at

hitl_decisions
 - decision_id
 - review_id (FK → reviews)
 - packet_id (FK → review_packets)
 - decision       (approve | reject | defer)
 - reviewer_notes
 - decided_at
```

The schema is normalized enough to support structured queries but flat enough to be readable in a SQLite shell. The `(structured)` annotations are fields stored as JSON within a column, pragmatic for SQLite, easy to query with `json_extract`, and clean to migrate to Postgres `jsonb` or to fully-typed columns later.

## What the audit trail does not do

**It is not an event bus** Agents do not communicate by writing to the audit trail and reading each other's writes. Agent-to-agent communication is the Supervisor's responsibility. The audit trail is a parallel write-only stream.

**It is not a knowledge base** Agents do not query the audit trail as part of their reasoning. They reason against the scenario data they pull via MCP. The audit trail exists for human-facing observability and replay, not for agent memory.

**It is not a metrics store** Operational metrics (latency, error rates, LLM token counts) may flow into a separate observability stack. The audit trail is for governance-facing reasoning traceability, which is a different artifact

Conflating any of these with the audit trail's purpose would dilute it. Keeping its scope clean is part of the architectural signal.

## The audit trail as the README's visual hero

The strongest single section of the README is the **audit-trail walkthrough**: pick one scenario, run it through the system, and show every record that was written, in causal order, with the recommendation at the end traceable back through the entire chain. A hiring manager who reads only that section should understand what the project does and why it is worth the engineering depth.

This is what "the audit trail is the artifact a governance reviewer engages with" means. The walkthrough is not a debugging tool. It is the system's primary deliverable to anyone who needs to **understand** a recommendation rather than just consume it.
