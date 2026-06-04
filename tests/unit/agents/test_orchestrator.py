"""Tests for the LangGraph orchestrator.

Covers:
  - Graph builds without raising.
  - Input Harness rejection short-circuits to cycle_complete with
    terminal_state='rejected_input'.
  - The legacy `orchestrate()` stub still raises with a pointer to the
    new runner entry point (back-compat contract).
"""

from __future__ import annotations

import pytest

from src.agents.orchestrator import build_graph, orchestrate
from src.agents.state import make_initial_state
from src.audit import AuditStore
from src.audit.queries import get_cycle_events, get_harness_events_for_cycle
from src.harnesses.action import ActionHarness
from src.harnesses.input import InputHarness


# ============================================================
# Build
# ============================================================
def test_build_graph_returns_compiled_app(
    store: AuditStore,
    input_harness: InputHarness,
    action_harness: ActionHarness,
) -> None:
    app = build_graph(store, input_harness, action_harness)
    # Compiled LangGraph has an invoke method.
    assert hasattr(app, "invoke")


# ============================================================
# Input rejection short-circuit
# ============================================================
def test_input_rejection_short_circuits(
    store: AuditStore,
    input_harness: InputHarness,
    action_harness: ActionHarness,
) -> None:
    """Bogus app-name → Input Harness rejects → graph routes straight
    to cycle_complete. System Mapper never runs; no tool_call rows."""
    cycle_id = store.start_cycle(application_id="bogus_app", trigger_type="test")
    app = build_graph(store, input_harness, action_harness)
    initial = make_initial_state(application_id="bogus_app", cycle_id=cycle_id)
    final = app.invoke(initial)

    terminal = (
        final.get("terminal_state") if isinstance(final, dict)
        else final.terminal_state
    )
    assert terminal == "rejected_input"

    events = get_cycle_events(store, cycle_id)
    types = {e.type for e in events}
    # cycle_started only — no system_mapper rows, no tool_calls
    assert types == {"cycle_started"}

    h_events = get_harness_events_for_cycle(store, cycle_id)
    rejected = [h for h in h_events if h.verdict == "rejected"]
    assert len(rejected) >= 1


# ============================================================
# Legacy stub contract (back-compat)
# ============================================================
def test_legacy_orchestrate_stub_still_raises_with_pointer() -> None:
    """The old `orchestrate(scenario)` entry remains importable and
    raises with a pointer to `run_cycle`. Keeps any pre-agent-cycle caller
    from silently breaking; the error tells them where to go."""
    with pytest.raises(NotImplementedError) as exc:
        orchestrate({"scenario_id": "08"})
    msg = str(exc.value)
    assert "run_cycle" in msg
    assert "CHANGELOG" in msg
