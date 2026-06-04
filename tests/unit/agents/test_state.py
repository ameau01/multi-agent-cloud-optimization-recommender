"""Tests for the LangGraph state schema (TypedDict + reducers).

Covers:
  - `make_initial_state` fills every key with the right zero/empty default.
  - Required runner fields (application_id, cycle_id) round-trip onto the dict.
  - Multi-writer fields carry the `operator.add` reducer so parallel
    deposits concat without conflict.
  - The supervisor-owned `ordered_findings` field is a single-writer
    field (no reducer) — overlaying a new value replaces, not concats.

The TypedDict has `total=False`, so at runtime it's a plain `dict`. We
don't pin runtime ValidationError behavior here — TypedDict has none.
The schema's value is in the reducer wiring, which we check end-to-end
via a small `StateGraph` instead of trying to inspect `Annotated` at
runtime (LangGraph reads the annotation; the test goes through the same
path the orchestrator does).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from src.agents.state import CycleState, make_initial_state


# ============================================================
# make_initial_state
# ============================================================
def test_make_initial_state_sets_required_fields() -> None:
    s = make_initial_state(application_id="app-08", cycle_id="cycle_x")
    assert s["application_id"] == "app-08"
    assert s["cycle_id"] == "cycle_x"


def test_make_initial_state_defaults() -> None:
    """Every field the factory writes lands as a zero/empty default."""
    s = make_initial_state(application_id="app-08", cycle_id="cycle_x")
    # Booleans / None for scalar fields.
    assert s["input_validation_passed"] is False
    assert s["input_validation_reason"] is None
    assert s["last_input_validation_record_id"] is None
    assert s["analysis_plan"] is None
    assert s["has_system_map"] is False
    assert s["last_system_mapper_output_id"] is None
    assert s["last_supervisor_decision_id"] is None
    assert s["evaluator_record"] is None
    assert s["recommendation"] is None
    assert s["last_evaluator_record_id"] is None
    assert s["last_recommendation_record_id"] is None
    assert s["last_gate_verdict_id"] is None
    assert s["next_route"] is None
    assert s["terminal_state"] is None
    assert s["failure_reason"] is None
    assert s["failed_at_stage"] is None
    assert s["last_orchestration_check_id"] is None
    # Lists for multi-writer + single-writer collection fields.
    assert s["specialists_invoked"] == []
    assert s["specialists_to_invoke"] == []
    assert s["specialist_findings"] == []
    assert s["specialist_finding_record_ids"] == []
    assert s["specialists_completed"] == []
    assert s["ordered_findings"] == []


def test_make_initial_state_accepts_cycle_started_id() -> None:
    """The runner passes cycle_started_id so Supervisor can cite it as
    evidence on its first decision. None is the default; an int when set."""
    s = make_initial_state(
        application_id="app-08",
        cycle_id="cycle_x",
        cycle_started_id=42,
    )
    assert s["cycle_started_id"] == 42


# ============================================================
# Reducer wiring — operator.add concatenates parallel deposits
# ============================================================
def test_specialist_findings_reducer_merges_concurrent_deposits() -> None:
    """Three sibling nodes deposit one finding each into
    `specialist_findings`. The `operator.add` reducer on the field's
    `Annotated[list[...], add]` annotation merges them via list concat,
    yielding all three after fan-in.

    This is the load-bearing wiring for parallel specialists. If the
    annotation is ever dropped, this test fails with a "last writer
    wins" result (len == 1) instead of the concat result (len == 3).
    """
    g: StateGraph = StateGraph(CycleState)
    g.add_node(
        "a",
        lambda s: {"specialist_findings": [{"specialist": "compute_analyst"}]},
    )
    g.add_node(
        "b",
        lambda s: {"specialist_findings": [{"specialist": "data_layer_analyst"}]},
    )
    g.add_node(
        "c",
        lambda s: {"specialist_findings": [{"specialist": "network_analyst"}]},
    )
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge(START, "c")
    g.add_edge("a", END)
    g.add_edge("b", END)
    g.add_edge("c", END)
    app = g.compile()
    out = app.invoke(make_initial_state(application_id="app-08", cycle_id="cycle_x"))

    findings = out["specialist_findings"]
    assert len(findings) == 3
    specialists = sorted(f["specialist"] for f in findings)
    assert specialists == [
        "compute_analyst",
        "data_layer_analyst",
        "network_analyst",
    ]


def test_specialists_completed_reducer_merges() -> None:
    """`specialists_completed` carries the same reducer — each specialist
    appends its own name; the merger concatenates."""
    g: StateGraph = StateGraph(CycleState)
    g.add_node("a", lambda s: {"specialists_completed": ["compute_analyst"]})
    g.add_node("b", lambda s: {"specialists_completed": ["data_layer_analyst"]})
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", END)
    g.add_edge("b", END)
    app = g.compile()
    out = app.invoke(make_initial_state(application_id="app-08", cycle_id="cycle_x"))

    assert sorted(out["specialists_completed"]) == [
        "compute_analyst",
        "data_layer_analyst",
    ]


def test_specialist_finding_record_ids_reducer_merges() -> None:
    """Same shape, but for the audit_records.id list."""
    g: StateGraph = StateGraph(CycleState)
    g.add_node("a", lambda s: {"specialist_finding_record_ids": [101]})
    g.add_node("b", lambda s: {"specialist_finding_record_ids": [202]})
    g.add_node("c", lambda s: {"specialist_finding_record_ids": [303]})
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge(START, "c")
    g.add_edge("a", END)
    g.add_edge("b", END)
    g.add_edge("c", END)
    app = g.compile()
    out = app.invoke(make_initial_state(application_id="app-08", cycle_id="cycle_x"))

    assert sorted(out["specialist_finding_record_ids"]) == [101, 202, 303]


# ============================================================
# Single-writer fields replace, not concat
# ============================================================
def test_ordered_findings_single_writer_replaces() -> None:
    """`ordered_findings` is the supervisor's single-writer canonical
    re-projection of `specialist_findings`. It carries NO reducer —
    a node that writes to it must own it. The test verifies that two
    sequential writes replace each other (last writer wins), in contrast
    to the multi-writer fields' concat semantics. If a reducer ever gets
    attached, this test breaks immediately (the second write would
    concat the lists instead of replacing)."""
    g: StateGraph = StateGraph(CycleState)
    g.add_node(
        "first",
        lambda s: {"ordered_findings": [{"specialist": "compute_analyst"}]},
    )
    g.add_node(
        "second",
        lambda s: {
            "ordered_findings": [
                {"specialist": "data_layer_analyst"},
                {"specialist": "network_analyst"},
            ]
        },
    )
    g.add_edge(START, "first")
    g.add_edge("first", "second")
    g.add_edge("second", END)
    app = g.compile()
    out = app.invoke(make_initial_state(application_id="app-08", cycle_id="cycle_x"))

    assert out["ordered_findings"] == [
        {"specialist": "data_layer_analyst"},
        {"specialist": "network_analyst"},
    ]
