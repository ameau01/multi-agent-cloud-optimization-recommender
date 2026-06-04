"""Mock-replay graph factory — drives the cycle from a recorded fixture.

Reads a cycle-export fixture produced by `tests/export_cycle_fixture.py`
and builds a LangGraph application that re-executes the same graph
topology with the LLM-invoking nodes replaced by "replay nodes" that
write the recorded outputs directly to the audit DB. The result is a
deterministic, network-free replay of one historical cycle suitable
for LangGraph dev visualization and offline debugging.

What's replayed vs run-for-real:

  ┌──────────────────────┬─────────────────────────────────────────┐
  │ Node                 │ Replay strategy                          │
  ├──────────────────────┼─────────────────────────────────────────┤
  │ input_validation     │ Run for real (no LLM, no MCP)            │
  │ system_mapper        │ Replay — write recorded                  │
  │                      │   system_mapper_output row, populate     │
  │                      │   analysis_plan on state                 │
  │ supervisor           │ Run for real (no LLM, deterministic)     │
  │ compute_analyst      │ Replay — write recorded                  │
  │ data_layer_analyst   │   specialist_finding row, return         │
  │ network_analyst      │   matching state delta                   │
  │ cross_tier_evaluator │ Replay — write recorded recommendation   │
  │                      │   row, populate evaluator state          │
  │ gate                 │ Run for real (no LLM)                    │
  │ cycle_complete       │ Run for real (no LLM)                    │
  └──────────────────────┴─────────────────────────────────────────┘

Harness checks inside replay nodes are bypassed — the original cycle
already passed them; re-running them on replayed data adds no signal.

Entry point:

  - `graph_factory_replay()` — zero-arg factory wired into
    `langgraph.json` under the `agent_replay` graph name. Reads the
    fixture path from `REPLAY_FIXTURE` env (or a default path) and
    returns the compiled graph.

Use from LangGraph dev:

  1. Run `tests/export_cycle_fixture.py` to produce a fixture.
  2. `REPLAY_FIXTURE=tests/integration/agents/fixtures/cycle_app08.json langgraph dev`
  3. In the LangGraph dev UI, select graph `agent_replay`.
  4. Invoke with `{"application_id": "app-08", "cycle_id": "replay-test"}` —
     the cycle_id can be any string; the audit DB is in-memory.

The replay reproduces the cycle's STRUCTURED OUTPUTS (findings,
recommendation, plan) but not the raw LLM completions — those are not
stored in the audit DB by design. For the project's agents, structured
output is the load-bearing artifact, so replay fidelity for downstream
consumers (gate, scorer, renderer) is full.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..audit.store import AuditStore
from ..harnesses.action import ActionHarness
from ..harnesses.input import InputHarness
from ..harnesses.orchestration import OrchestrationHarness
from ..harnesses.reasoning import ReasoningHarness
from ..models.audit import AuditRecord
from .analysis_plan import AnalysisPlan
from .orchestrator import (
    _after_input_validation,
    _after_supervisor,
    _after_system_mapper,
    _after_worker,
    _make_cycle_complete_node,
    _make_gate_node,
    _make_input_validation_node,
    _make_supervisor_node,
    _tagged_node,
)
from .state import make_initial_state as _make_initial_state
from .state import CycleState


# ============================================================
# Fixture loading
# ============================================================
def _load_fixture(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Replay fixture not found: {p}. Generate one with "
            f"`python tests/export_cycle_fixture.py --cycle <id> --out <path>`."
        )
    return json.loads(p.read_text())


def _find_rows(
    fixture: dict[str, Any],
    *,
    type_: str | None = None,
    agent: str | None = None,
) -> list[dict[str, Any]]:
    """Filter audit_records by type and/or agent. Order is preserved
    (fixture rows are stored id-ascending)."""
    rows = fixture.get("audit_records", [])
    if type_ is not None:
        rows = [r for r in rows if r.get("type") == type_]
    if agent is not None:
        rows = [r for r in rows if r.get("agent") == agent]
    return rows


# ============================================================
# Replay nodes
# ============================================================
def _fixture_application_id(fixture: dict[str, Any]) -> str | None:
    """Pull the original cycle's application_id off the fixture.

    Checks the system_mapper_output row first (richest source), then
    falls back to the cycle_started row's content. Returns None if
    neither is recoverable — the caller decides what to do then.
    """
    sm = _find_rows(fixture, type_="system_mapper_output")
    if sm and isinstance(sm[0].get("content"), dict):
        v = sm[0]["content"].get("application_id")
        if v:
            return str(v)
    cs = _find_rows(fixture, type_="cycle_started")
    if cs and isinstance(cs[0].get("content"), dict):
        v = cs[0]["content"].get("application_id")
        if v:
            return str(v)
    return None


def _make_replay_init_node(store: AuditStore, fixture: dict[str, Any]):
    """Studio-friendly first node — fills in `application_id`,
    `cycle_id`, and `cycle_started_id` when they're missing from the
    initial state.

    Production callers go through `runner.run_cycle`, which calls
    `store.start_cycle(...)` before invoking the graph and stamps the
    resulting ids onto state. Studio bypasses the runner: a user clicks
    Submit on an empty form and the graph sees state with no
    `cycle_id` or `application_id`. The downstream nodes use
    `state["cycle_id"]` (subscript, not `.get`), so the very first
    node would KeyError.

    Replay's twist: this shim also fills in `application_id` from the
    fixture when missing, because a replay always knows the right
    answer — the cycle we're replaying was for a specific app. The
    fixture's system_mapper_output row carries it. Falls back to
    "unknown" only if the fixture is malformed (no system_mapper_output
    at all), in which case the Input Harness will reject and the cycle
    terminates cleanly with `terminal_state="rejected_input"`.

    Idempotent: if cycle_id is already set (i.e. the caller IS the
    runner), the node is a no-op.
    """
    fixture_app_id = _fixture_application_id(fixture)

    def node(state: CycleState) -> dict[str, Any]:
        update: dict[str, Any] = {}
        # Resolve application_id: caller's input > fixture's app > "unknown".
        app_id = (
            state.get("application_id") or fixture_app_id or "unknown"
        )
        if "application_id" not in state:
            update["application_id"] = app_id

        # cycle_id / cycle_started_id resolution. DB is the source of
        # truth — Studio caches thread state across runs, and after a
        # dev-server reload the new store is empty but the thread still
        # references the old store's ids. Same logic as
        # orchestrator._make_runner_init_node:
        #
        #   A. state has cycle_id, DB has matching row → use DB's id
        #   B. state has cycle_id, DB has nothing → stale, mint fresh
        #   C. no cycle_id → mint fresh
        cycle_id = state.get("cycle_id")
        cycle_started_id = state.get("cycle_started_id")
        if cycle_id:
            db_started_id = store.get_cycle_started_id(cycle_id)
            if db_started_id is not None:
                if db_started_id != cycle_started_id:
                    update["cycle_started_id"] = db_started_id
                cycle_started_id = db_started_id
            else:
                cycle_id = None
                cycle_started_id = None
        if not cycle_id:
            cycle_id = store.start_cycle(
                application_id=app_id,
                trigger_type="replay",
                notes="LangGraph dev replay run (no runner)",
            )
            cycle_started_id = store.get_cycle_started_id(cycle_id)
            update["cycle_id"] = cycle_id
            update["cycle_started_id"] = cycle_started_id

        # ALWAYS fill missing defaults — even when the caller provided
        # cycle_id but omitted the booleans / lists / Nones that
        # downstream nodes subscript-access. Without this, a Studio
        # input like `{"application_id": "app-08", "cycle_id": "x"}`
        # would KeyError on the first `state["has_system_map"]`
        # access in supervisor._decide. Mirrors make_initial_state's
        # default set.
        defaults = _make_initial_state(
            application_id=app_id,
            cycle_id=cycle_id,
            cycle_started_id=cycle_started_id,
        )
        for key, default_value in defaults.items():
            if key not in state and key not in update:
                update[key] = default_value
        return update
    return node


def _make_replay_system_mapper(
    store: AuditStore,
    fixture: dict[str, Any],
):
    """Write the fixture's system_mapper_output to the new DB and stamp
    the AnalysisPlan onto state. Skips MCP calls and the Reasoning
    Harness check the production node performs.

    Failure mode: if the fixture has no system_mapper_output row (e.g.
    the original cycle short-circuited at input_validation), set
    terminal_state='failed' with stage='system_mapper' so the
    conditional edge routes to cycle_complete.
    """
    sm_rows = _find_rows(fixture, type_="system_mapper_output")

    def node(state: CycleState) -> dict[str, Any]:
        if not sm_rows:
            return {
                "terminal_state": "failed",
                "failure_reason": "replay: fixture has no system_mapper_output",
                "failed_at_stage": "system_mapper",
            }
        content = sm_rows[0]["content"]
        # The recorded content shape matches SystemMapperOutputContent —
        # which the AnalysisPlan model expects. Some legacy fields may be
        # present; AnalysisPlan has extra='forbid', so we filter to the
        # known field set.
        plan = AnalysisPlan(
            application_id=content.get(
                "application_id", state["application_id"],
            ),
            tiers_detected=list(content.get("tiers_detected", [])),
            specialists_to_invoke=list(content.get("specialists_to_invoke", [])),
            terraform_resources_summary=content.get(
                "terraform_resources_summary",
            ),
            metadata_summary=dict(content.get("metadata_summary", {})),
            notes=content.get("notes"),
        )
        row_id = store.add_event(AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="system_mapper_output",
            agent="system_mapper",
            content={
                **content,
                # Re-cite as evidence the parent cycle_started row id, so
                # any downstream evidence walker that needs at least one
                # ref finds something local.
                "evidence_refs": (
                    [state["cycle_started_id"]]
                    if state.get("cycle_started_id") is not None
                    else []
                ),
            },
        ))
        return {
            "analysis_plan": plan,
            "has_system_map": True,
            "last_system_mapper_output_id": row_id,
        }
    return node


def _make_replay_specialist(
    agent_name: str,
    store: AuditStore,
    fixture: dict[str, Any],
):
    """Write the fixture's specialist_finding row for this agent and
    return the operator.add-shaped delta the production node returns.

    Three deltas are returned (matching specialists/base.py):
      - specialist_findings: [<finding dict>]
      - specialist_finding_record_ids: [<row id>]
      - specialists_completed: [<agent_name>]

    The finding dict mirrors the supervisor's sort expectation: it
    carries primary_tier + specialist so `(primary_tier, specialist)`
    sorting produces deterministic ordered_findings.
    """
    # Pre-resolve the recorded finding so node() can run cheaply.
    matches = _find_rows(fixture, type_="specialist_finding", agent=agent_name)

    def node(state: CycleState) -> dict[str, Any]:
        if not matches:
            # Fixture has no finding from this specialist — return an
            # empty delta so the supervisor's fan-in completeness check
            # sees the specialist as "completed with no finding". The
            # supervisor will route to synthesize anyway; the evaluator
            # then has fewer findings to reconcile.
            return {
                "specialists_completed": [agent_name],
            }
        content = matches[0]["content"]
        row_id = store.add_event(AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="specialist_finding",
            agent=agent_name,  # type: ignore[arg-type]
            content={
                **content,
                # Drop the original cycle's evidence_refs — they point at
                # row ids that don't exist in this fresh in-memory DB.
                # The replay sacrifices evidence-chain fidelity for
                # simplicity; the gate + scorer don't follow these refs
                # on the replay path. See module docstring.
                "evidence_refs": [],
            },
        ))
        finding_with_meta = {
            **content,
            "specialist": agent_name,
            "evidence_refs": [],
            "audit_record_id": row_id,
        }
        return {
            "specialist_findings": [finding_with_meta],
            "specialist_finding_record_ids": [row_id],
            "specialists_completed": [agent_name],
        }
    return node


def _make_replay_evaluator(
    store: AuditStore,
    fixture: dict[str, Any],
):
    """Write the fixture's evaluator_record + recommendation rows and
    stamp the corresponding state fields. Production evaluator does a
    three-step LLM call (reconcile/recommend/reflect) which is collapsed
    to a single deterministic write here."""
    eval_rows = _find_rows(fixture, type_="evaluator_record")
    rec_rows = _find_rows(fixture, type_="recommendation")

    def node(state: CycleState) -> dict[str, Any]:
        update: dict[str, Any] = {}

        # evaluator_record (the reconcile + reflect outputs in the
        # project's 3-step synthesis). Always write SOMETHING, even if
        # the fixture lacks an evaluator_record row — otherwise
        # supervisor's branch 3 (synthesize) keeps firing because
        # `last_evaluator_record_id` stays None and the cycle loops
        # supervisor → cross_tier_evaluator → supervisor forever.
        er_content: dict[str, Any]
        if eval_rows:
            er_content = dict(eval_rows[0]["content"])
        else:
            # Synthesize a minimal placeholder. Matches
            # EvaluatorRecordContent's required fields.
            er_content = {
                "cross_tier_interactions": [],
                "trade_off_scores": {},
                "synthesis": {"note": "replay placeholder — no eval_record in fixture"},
                "contributing_findings": list(
                    state.get("specialist_finding_record_ids") or []
                ),
                "evaluator_confidence": None,
            }
        er_content["evidence_refs"] = list(
            state.get("specialist_finding_record_ids") or []
        )
        er_id = store.add_event(AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="evaluator_record",
            agent="cross_tier_evaluator",
            content=er_content,
        ))
        update["evaluator_record"] = er_content
        update["last_evaluator_record_id"] = er_id

        # recommendation (the recommend step). Same defense — supervisor
        # branch 4 (gate) needs last_recommendation_record_id non-null,
        # so write a placeholder if the fixture has no recommendation
        # (which would be unusual but possible for partial fixtures).
        rc_content: dict[str, Any]
        if rec_rows:
            rc_content = dict(rec_rows[0]["content"])
        else:
            rc_content = {
                "composite": {
                    "finding_type": "diagnostic_deferral",
                    "primary_tier": None,
                    "action_category": None,
                },
            }
        rc_content["evidence_refs"] = list(
            state.get("specialist_finding_record_ids") or []
        )
        rc_id = store.add_event(AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="recommendation",
            agent="cross_tier_evaluator",
            content=rc_content,
        ))
        update["recommendation"] = rc_content
        update["last_recommendation_record_id"] = rc_id
        return update
    return node


# ============================================================
# Graph builder
# ============================================================
def build_replay_graph(
    store: AuditStore,
    input_harness: InputHarness,
    action_harness: ActionHarness,
    fixture: dict[str, Any],
    reasoning_harness: ReasoningHarness | None = None,
    orchestration_harness: OrchestrationHarness | None = None,
):
    """Build the replay variant of the graph. Same topology as
    `orchestrator.build_graph` — the only difference is the four LLM-
    invoking nodes are replaced by replay nodes that read from `fixture`.
    """
    if reasoning_harness is None:
        reasoning_harness = ReasoningHarness(store)
    if orchestration_harness is None:
        orchestration_harness = OrchestrationHarness(store)

    graph: StateGraph = StateGraph(CycleState)

    # Replay init — fills cycle_id / cycle_started_id when the graph is
    # invoked from LangGraph dev / Studio (no runner to call start_cycle).
    # No-op when the runner already populated the state (production path).
    graph.add_node(
        "replay_init",
        _tagged_node(
            _make_replay_init_node(store, fixture),
            tags=["replay", "init"],
            description=(
                "Studio-friendly init shim. If cycle_id is missing, calls "
                "store.start_cycle and stamps the result. No-op when the "
                "runner has already initialized state."
            ),
        ),
    )

    # Real nodes (no LLM)
    graph.add_node(
        "input_validation",
        _tagged_node(
            _make_input_validation_node(input_harness),
            tags=["harness", "input-validation", "replay"],
            description="Input Harness — replay (real, no LLM).",
        ),
    )
    graph.add_node(
        "system_mapper",
        _tagged_node(
            _make_replay_system_mapper(store, fixture),
            tags=["analysis", "system-mapper", "replay"],
            description=(
                "Replay node — writes the fixture's system_mapper_output "
                "row and populates analysis_plan on state. Skips MCP."
            ),
        ),
    )
    graph.add_node(
        "supervisor",
        _tagged_node(
            _make_supervisor_node(store, reasoning_harness),
            tags=["routing", "supervisor", "replay"],
            description=(
                "State-machine router (real). Same routing decisions "
                "as production; no LLM involved."
            ),
        ),
    )
    # Replay specialists
    for agent in ("compute_analyst", "data_layer_analyst", "network_analyst"):
        graph.add_node(
            agent,
            _tagged_node(
                _make_replay_specialist(agent, store, fixture),
                tags=["specialist", "replay", agent],
                description=(
                    f"Replay {agent} — writes the fixture's "
                    f"specialist_finding row and returns the operator.add "
                    f"delta. Bypasses ReAct loop + Reasoning Harness."
                ),
            ),
        )
    # Replay evaluator
    graph.add_node(
        "cross_tier_evaluator",
        _tagged_node(
            _make_replay_evaluator(store, fixture),
            tags=["evaluator", "synthesis", "replay"],
            description=(
                "Replay evaluator — writes the fixture's evaluator_record "
                "+ recommendation rows. Collapses the 3-step LLM synthesis "
                "into a single deterministic write."
            ),
        ),
    )
    # Real gate + cycle_complete
    graph.add_node(
        "gate",
        _tagged_node(
            _make_gate_node(action_harness),
            tags=["harness", "action-gate", "replay"],
            description="Action Harness gate (real, no LLM).",
        ),
    )
    graph.add_node(
        "cycle_complete",
        _tagged_node(
            _make_cycle_complete_node(orchestration_harness),
            tags=["terminal", "cycle-complete", "replay"],
            description="Terminal node (real). Records the cycle outcome.",
        ),
    )

    # Edges — identical to production except for the replay_init prepend.
    # Supervisor remains the only router.
    graph.add_edge(START, "replay_init")
    graph.add_edge("replay_init", "input_validation")
    graph.add_conditional_edges(
        "input_validation",
        _after_input_validation,
        {"supervisor": "supervisor", "cycle_complete": "cycle_complete"},
    )
    graph.add_conditional_edges(
        "supervisor",
        _after_supervisor,
        {
            "system_mapper": "system_mapper",
            "compute_analyst": "compute_analyst",
            "data_layer_analyst": "data_layer_analyst",
            "network_analyst": "network_analyst",
            "cross_tier_evaluator": "cross_tier_evaluator",
            "gate": "gate",
            "cycle_complete": "cycle_complete",
        },
    )
    graph.add_conditional_edges(
        "system_mapper",
        _after_system_mapper,
        {"supervisor": "supervisor", "cycle_complete": "cycle_complete"},
    )
    for worker in (
        "compute_analyst",
        "data_layer_analyst",
        "network_analyst",
        "cross_tier_evaluator",
        "gate",
    ):
        graph.add_conditional_edges(
            worker,
            _after_worker,
            {"supervisor": "supervisor", "cycle_complete": "cycle_complete"},
        )
    graph.add_edge("cycle_complete", END)

    return graph.compile()


# ============================================================
# LangGraph dev entry point
# ============================================================
DEFAULT_FIXTURE_PATH = "tests/integration/agents/fixtures/cycle_app08.json"


def graph_factory_replay():
    """Zero-arg factory for LangGraph dev's `agent_replay` graph.

    Reads the fixture path from `REPLAY_FIXTURE` env, falling back to
    `tests/integration/agents/fixtures/cycle_app08.json`.

    Uses a **tempfile-backed** SQLite store (not in-memory) because the
    parallel specialist fan-out (compute_analyst + data_layer_analyst
    + network_analyst running concurrently via langgraph.types.Send)
    issues concurrent writes that SQLite's :memory: mode can't handle
    cleanly — you get `sqlite3.OperationalError: cannot commit - no
    transaction is active`. The on-disk SQLite the production runner
    uses (`.audit_db/audit.db`) handles concurrency via WAL mode; the
    replay needs the same. Tempfile is the lightweight alternative to
    polluting the project's persistent DB.

    The tempfile path is unique per process and gets cleaned up by the
    OS; nothing the user has to manage.

    Referenced from `langgraph.json`:
        {"graphs": {"agent_replay": "src.agents.replay:graph_factory_replay"}}
    """
    import tempfile

    from ..audit.store import AuditStore

    fixture_path = os.environ.get("REPLAY_FIXTURE", DEFAULT_FIXTURE_PATH)
    fixture = _load_fixture(fixture_path)

    # NamedTemporaryFile(delete=False) so SQLite can re-open the path;
    # the OS reaps /tmp on reboot, and a single replay session's DB is
    # bounded to a few hundred KB.
    tmp = tempfile.NamedTemporaryFile(
        prefix="agent_replay_", suffix=".db", delete=False,
    )
    tmp.close()
    store = AuditStore(db_path=tmp.name)
    store.initialize()
    return build_replay_graph(
        store,
        InputHarness(store),
        ActionHarness(store),
        fixture,
    )


# Send is re-exported so the orchestrator's _after_supervisor (which
# this module reuses) sees the same symbol when it's called against the
# replay graph. Avoids a stale-import edge case if a downstream caller
# imports Send from this module instead of langgraph.types.
__all__ = [
    "build_replay_graph",
    "graph_factory_replay",
    "Send",
]
