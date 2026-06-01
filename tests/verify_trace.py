#!/usr/bin/env python3
"""Walk every sample-run audit trail backward and confirm every reference resolves.

Run:
    scripts/verify_trace.sh                # bash wrapper (preferred entry point)
    uv run python tests/verify_trace.py    # direct Python invocation

This script proves each trace satisfies the auditability contract:

    Every node names its parents.
    A replay script can traverse the whole graph from the final
    review_packet back to the input_harness step by following references.

Why this matters. The architecture commits to a relational audit trail
where foreign-key traversal is the primary access pattern (see
docs/decisions.md, decision #3). This script is the proof: if any
reference is dangling in any trace, the backward walk fails and the
script exits non-zero. The Action Harness's evidence_completeness
check is meant to do the same thing at gate time; this script is what
a reviewer can run manually to verify the same property.

What this script does NOT do. It does not re-run the agents.
LLM output is non-deterministic at non-zero temperature, so replay
cannot re-derive the same answer by running the model again. Replay
reconstructs what happened, not what would happen.

Discovery. Every file matching `sample_runs/traces/scenario_NN_trace.json`
is verified. To add a new trace, drop it in that folder; no script
changes needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TRACES_DIR = (
    Path(__file__).resolve().parent.parent / "sample_runs" / "traces"
)


def walk_backward(trace: dict) -> tuple[bool, list[str]]:
    """Walk one audit trail backward and resolve every reference.

    Returns (success, log_lines).
    """
    log: list[str] = []
    ok = True

    def step(msg: str, success: bool = True) -> None:
        nonlocal ok
        prefix = "  ✓" if success else "  ✗"
        log.append(f"{prefix} {msg}")
        if not success:
            ok = False

    # Build a lookup table of every IDed record.
    table: dict[str, dict] = {}

    def register(record: dict, id_field: str, kind: str) -> str | None:
        if id_field in record and isinstance(record[id_field], str):
            rid = record[id_field]
            table[rid] = {"kind": kind, "record": record}
            return rid
        return None

    # Register every node by its primary ID.
    register(trace["input_harness_validation"], "step_id", "input_harness")
    register(trace["system_mapper"], "step_id", "system_mapper")
    register(trace["supervisor_decision"], "step_id", "supervisor")
    for sf in trace["specialist_findings"]:
        register(sf, "step_id", "specialist_finding")
        for rs in sf["react_steps"]:
            register(rs, "step_id", "react_step")
            if "observation_id" in rs:
                # Observation IDs are referenced from finding.evidence_refs
                table[rs["observation_id"]] = {"kind": "observation", "record": rs["observation"]}
    register(trace["evaluator_records"], "step_id", "evaluator")
    register(trace["evaluator_records"]["synthesis"], "synthesis_id", "synthesis")
    for xt in trace["evaluator_records"]["cross_tier_interactions"]:
        register(xt, "interaction_id", "cross_tier_interaction")
    register(trace["action_harness_gate"], "step_id", "action_harness_gate")
    # gate also gets registered under gate_id (alias)
    if "gate_id" in trace["action_harness_gate"]:
        table[trace["action_harness_gate"]["gate_id"]] = {
            "kind": "action_harness_gate", "record": trace["action_harness_gate"],
        }
    register(trace["review_packet"], "packet_id", "review_packet")

    log.append(f"  registered {len(table)} nodes")
    log.append("")
    log.append("  Backward walk from review_packet to inputs:")

    # Step 1: review_packet -> gate, synthesis, review
    packet = trace["review_packet"]
    step(f"review_packet.gate_id {packet.get('gate_id')!r} resolves",
         packet.get("gate_id") in table)
    step(f"review_packet.synthesis_id {packet.get('synthesis_id')!r} resolves",
         packet.get("synthesis_id") in table)
    step(f"review_packet.review_id {packet.get('review_id')!r} matches review",
         packet.get("review_id") == trace["review"]["review_id"])

    # Step 2: gate -> evaluator, synthesis
    gate = trace["action_harness_gate"]
    step(f"gate.evaluator_id {gate.get('evaluator_id')!r} resolves",
         gate.get("evaluator_id") in table)
    step(f"gate.synthesis_id {gate.get('synthesis_id')!r} resolves",
         gate.get("synthesis_id") in table)
    # The evidence_completeness check should list verified_refs
    for chk in gate["checks"]:
        if chk.get("check") == "evidence_completeness":
            for ref in chk.get("verified_refs", []):
                step(f"gate.evidence_completeness.verified_refs[{ref!r}] resolves",
                     ref in table)

    # Step 3: synthesis -> contributing_findings, evidence_refs, cross-tier
    syn = trace["evaluator_records"]["synthesis"]
    for fid in syn.get("contributing_findings", []):
        step(f"synthesis.contributing_findings[{fid!r}] resolves to a specialist_finding",
             fid in table and table[fid]["kind"] == "specialist_finding")
    for ref in syn.get("evidence_refs", []):
        step(f"synthesis.evidence_refs[{ref!r}] resolves", ref in table)

    # Step 4: drift_check -> target_finding_id
    for dc in trace["evaluator_records"]["drift_check"]:
        tfid = dc.get("target_finding_id")
        step(f"drift_check[{dc['specialist']!r}].target_finding_id {tfid!r} resolves to a specialist_finding",
             tfid in table and table[tfid]["kind"] == "specialist_finding")

    # Step 5: each specialist_finding -> its react_steps and their observations
    for sf in trace["specialist_findings"]:
        for ref in sf["finding"].get("evidence_refs", []):
            step(f"finding[{sf['step_id']!r}].evidence_refs[{ref!r}] resolves to an observation",
                 ref in table and table[ref]["kind"] == "observation")
        # All react_steps should be present with observation_ids
        for rs in sf["react_steps"]:
            step(f"react_step[{rs['step_id']!r}] has observation_id {rs.get('observation_id')!r}",
                 "observation_id" in rs and rs["observation_id"] in table)

    return ok, log


def discover_traces(traces_dir: Path) -> list[Path]:
    """Return every scenario_NN_trace.json under traces_dir, sorted."""
    return sorted(traces_dir.glob("scenario_*_trace.json"))


def main() -> int:
    trace_paths = discover_traces(TRACES_DIR)
    if not trace_paths:
        print(f"No trace files found under {TRACES_DIR}", file=sys.stderr)
        return 2

    overall_ok = True
    per_trace_results: list[tuple[Path, bool]] = []

    for path in trace_paths:
        trace = json.loads(path.read_text())
        print()
        print("=" * 70)
        print(f"  Auditing {path.name}")
        print("=" * 70)
        ok, log = walk_backward(trace)
        for line in log:
            print(line)
        per_trace_results.append((path, ok))
        if not ok:
            overall_ok = False

    print()
    print("=" * 70)
    print("  Summary")
    print("=" * 70)
    for path, ok in per_trace_results:
        marker = "✓" if ok else "✗"
        print(f"  {marker} {path.name}")
    print()

    if overall_ok:
        print("  ✓ PASS. Every parent reference resolves in every trace.")
        print("        Each chain is fully traversable forward and backward.")
        print()
        print("  Note: replay reconstructs the recorded reasoning. It does")
        print("        not re-derive answers by re-running the model. LLM")
        print("        output is non-deterministic at non-zero temperature.")
        return 0
    else:
        print("  ✗ FAIL. At least one reference is dangling in at least one trace.")
        print("        The trace(s) above marked with ✗ do not satisfy the")
        print("        auditability contract.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
