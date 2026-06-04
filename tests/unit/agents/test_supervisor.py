"""Tests for the Supervisor node.

Covers:
  - Decision: skeleton run invokes zero specialists, regardless of plan.
  - Audit row written with the right decision_type and details.
  - Raises SupervisorError when state has no analysis_plan.
  - Reasoning Harness rejects decisions with missing/dangling evidence.
"""

from __future__ import annotations

import pytest

from src.agents.analysis_plan import AnalysisPlan
from src.agents.state import CycleState, make_initial_state
from src.agents.supervisor import SupervisorError, SupervisorNode
from src.audit import AuditStore
from src.audit.queries import get_cycle_events
from src.harnesses.reasoning import ReasoningHarness
from src.models.audit import AuditRecord


def _state_with_plan(
    cycle_id: str,
    specialists: list[str],
    *,
    store: AuditStore | None = None,
) -> CycleState:
    """Build a CycleState whose Supervisor decision will satisfy the
    Reasoning Harness's evidence-backed gate.

    The Supervisor in 11a cites `last_system_mapper_output_id` as
    evidence on every decision. The fixture writes a fake
    system_mapper_output row and stamps its id on the state so the
    harness check resolves to a real row.
    """
    plan = AnalysisPlan(
        application_id="app-08",
        tiers_detected=["compute", "database"],
        specialists_to_invoke=specialists,  # type: ignore[arg-type]
    )
    last_sm_id: int | None = None
    if store is not None:
        last_sm_id = store.add_event(AuditRecord(
            cycle_id=cycle_id,
            parent_id=None,
            category="decision",
            type="system_mapper_output",
            agent="system_mapper",
            content={
                "application_id": "app-08",
                "tiers_detected": ["compute", "database"],
                "specialists_to_invoke": specialists,
            },
        ))
    # has_system_map=True because the fixture is set up post-mapper —
    # the tests are exercising the "Supervisor decides after the map
    # exists" branch (the `complete` decision). The pre-map case (where
    # Supervisor decides `dispatch_system_mapper`) is exercised by the
    # orchestrator integration test.
    state = make_initial_state(application_id="app-08", cycle_id=cycle_id)
    state["analysis_plan"] = plan
    state["has_system_map"] = last_sm_id is not None
    state["last_system_mapper_output_id"] = last_sm_id
    return state


def test_supervisor_dispatches_specialists_when_plan_has_them(
    store: AuditStore, cycle_id: str,
) -> None:
    """Phase 11b: with a plan naming specialists and a system map on
    state, the Supervisor decides `dispatch_specialists` in a single
    decision row — every pending specialist appears in `targets`, ready
    for the conditional edge to fan out via `Send` objects.

    `specialists_invoked` is the historical list of every specialist
    dispatched at least once. On a first-time dispatch, it grows to
    contain the full pending set (append semantics, not overwrite —
    see SupervisorNode.run()).
    """
    node = SupervisorNode(store, ReasoningHarness(store))
    state = _state_with_plan(
        cycle_id,
        ["compute_analyst", "data_layer_analyst"],
        store=store,
    )

    update = node.run(state)
    assert update["next_route"] == "dispatch_specialists"
    assert sorted(update["specialists_invoked"]) == [
        "compute_analyst",
        "data_layer_analyst",
    ]


def test_supervisor_audit_row_records_dispatch_specialists(
    store: AuditStore, cycle_id: str,
) -> None:
    """The supervisor_decision row records the dispatch:
      - decision_type = "dispatch_specialists"
      - targets       = the pending specialists list
      - terminal_state = None (we're not terminating)
      - reason         = describes the parallel dispatch
      - evidence_refs  = the system_mapper_output row id (already on state)
      - decision_details.plan_specialists = the plan's full list
    """
    node = SupervisorNode(store, ReasoningHarness(store))
    state = _state_with_plan(cycle_id, ["compute_analyst"], store=store)
    node.run(state)

    events = get_cycle_events(store, cycle_id)
    sup = [e for e in events if e.type == "supervisor_decision"]
    assert len(sup) == 1
    content = sup[0].content
    assert content["decision_type"] == "dispatch_specialists"
    assert content["targets"] == ["compute_analyst"]
    assert content["terminal_state"] is None
    assert "parallel" in content["reason"]
    assert content["decision_details"]["plan_specialists"] == ["compute_analyst"]


def test_supervisor_synthesize_writes_sorted_ordered_findings(
    store: AuditStore, cycle_id: str,
) -> None:
    """When all specialists have completed, the Supervisor's `synthesize`
    decision branch sorts `specialist_findings` (which arrived in non-
    deterministic order via the operator.add reducer) by
    `(primary_tier, specialist)` and writes the result into the single-
    writer `ordered_findings` field. The Cross-Tier Evaluator reads
    `ordered_findings` — not `specialist_findings` — so this sort is the
    canonical-order guarantee.

    The fixture seeds findings in deliberately-wrong order
    (network → compute → database) to confirm the sort actually fires.
    """
    plan_specialists = ["compute_analyst", "data_layer_analyst", "network_analyst"]
    state = _state_with_plan(cycle_id, plan_specialists, store=store)
    # Mark all specialists as completed so branch 3 (synthesize) fires.
    state["specialists_completed"] = list(plan_specialists)
    # Seed findings in WRONG order so we can prove the sort runs.
    state["specialist_findings"] = [
        {"specialist": "network_analyst",      "primary_tier": "network"},
        {"specialist": "compute_analyst",      "primary_tier": "compute"},
        {"specialist": "data_layer_analyst",   "primary_tier": "database"},
    ]
    # Real audit row ids so the synthesize branch's evidence_refs check
    # (citing specialist_finding_record_ids) resolves cleanly.
    fids: list[int] = []
    for spec in plan_specialists:
        fid = store.add_event(AuditRecord(
            cycle_id=cycle_id,
            parent_id=None,
            category="decision",
            type="specialist_finding",
            agent=spec,  # type: ignore[arg-type]
            content={"specialist": spec, "primary_tier": "compute"},
        ))
        fids.append(fid)
    state["specialist_finding_record_ids"] = fids

    node = SupervisorNode(store, ReasoningHarness(store))
    update = node.run(state)

    assert update["next_route"] == "synthesize"
    # ordered_findings is sorted by (primary_tier, specialist).
    # Alphabetical on primary_tier: compute < database < network.
    ordered = update["ordered_findings"]
    assert [f["primary_tier"] for f in ordered] == ["compute", "database", "network"]
    assert [f["specialist"] for f in ordered] == [
        "compute_analyst",
        "data_layer_analyst",
        "network_analyst",
    ]


def test_supervisor_with_empty_plan_still_records(
    store: AuditStore, cycle_id: str,
) -> None:
    """If the plan named no specialists, the Supervisor still writes a
    decision row (the absence-of-fan-out is itself the decision)."""
    node = SupervisorNode(store, ReasoningHarness(store))
    state = _state_with_plan(cycle_id, [], store=store)
    node.run(state)

    events = get_cycle_events(store, cycle_id)
    sup = [e for e in events if e.type == "supervisor_decision"]
    assert len(sup) == 1
    content = sup[0].content
    assert content["decision_type"] == "complete"
    assert content["terminal_state"] == "no_specialists"
    assert "named no specialists" in content["reason"]


def test_supervisor_without_evidence_raises(
    store: AuditStore, cycle_id: str,
) -> None:
    """A bare CycleState (no map, no input_validation row) means the
    Supervisor's first-call decision (dispatch_system_mapper) has no
    evidence_refs to cite, and the Reasoning Harness rejects it.

    Under the supervisor-as-router pattern, Supervisor no longer
    requires analysis_plan on entry — the first call is exactly when
    it routes to System Mapper *to* produce one. What it does require
    is at least one evidence_ref to cite, which the orchestrator
    provides via state["last_input_validation_record_id"] on the pass-
    through from the Input Harness.
    """
    node = SupervisorNode(store, ReasoningHarness(store))
    # No cycle_started_id and no last_input_validation_record_id —
    # branch 1 of _decide produces an empty evidence list, which the
    # Reasoning Harness rejects.
    state = make_initial_state(application_id="app-08", cycle_id=cycle_id)
    with pytest.raises(SupervisorError, match="no evidence_refs"):
        node.run(state)


def test_supervisor_routes_to_system_mapper_on_first_call(
    store: AuditStore, cycle_id: str,
) -> None:
    """The supervisor-as-router pattern: the first Supervisor call
    (no system map yet) decides dispatch_system_mapper, cites the
    cycle_started audit_records row as evidence, and records a passing
    reasoning_check verdict.
    """
    state = make_initial_state(
        application_id="app-08",
        cycle_id=cycle_id,
        cycle_started_id=store.get_cycle_started_id(cycle_id),
    )
    state["input_validation_passed"] = True

    node = SupervisorNode(store, ReasoningHarness(store))
    update = node.run(state)
    assert update["next_route"] == "dispatch_system_mapper"
    # specialists_invoked is the historical list of *tier specialists*
    # dispatched in this cycle. system_mapper is not a specialist, so a
    # dispatch_system_mapper decision must NOT touch the field. (The
    # state.py docstring spells out that ownership.) Confirm by absence:
    assert "specialists_invoked" not in update

    events = get_cycle_events(store, cycle_id)
    sup = [e for e in events if e.type == "supervisor_decision"]
    assert len(sup) == 1
    assert sup[0].content["decision_type"] == "dispatch_system_mapper"
    assert sup[0].content["targets"] == ["system_mapper"]
