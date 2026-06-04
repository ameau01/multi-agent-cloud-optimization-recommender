"""LangGraph orchestrator: wires the cycle as a state machine.

The graph in Phase 11a:

    START
      ↓
    input_validation_gate
      ↓ (passed)                 ↓ (rejected)
    system_mapper                cycle_complete(rejected_input)
      ↓
    supervisor
      ↓
    cycle_complete(completed | no_specialists)
      ↓
    END

Phases 11b–11d add specialist nodes and the cross-tier evaluator
between supervisor and cycle_complete; the graph builder grows but
the agent wiring above remains intact.

Public API:
  - `build_graph(...)` returns a compiled LangGraph application.
  - `orchestrate(scenario)` retains the original stub signature for
    callers built before the runner landed; it now delegates to the
    public runner.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..audit.store import AuditStore
from ..harnesses.action import ActionHarness
from ..harnesses.input import InputHarness
from ..harnesses.orchestration import OrchestrationHarness
from ..harnesses.reasoning import ReasoningHarness
from ..models.audit import AuditRecord
from .evaluator import CrossTierEvaluatorNode, EvaluatorError
from .llm_client import (
    LLMClient,
    make_evaluator_client,
    make_specialist_client,
)
from .specialists import (
    ComputeAnalystNode,
    DataLayerAnalystNode,
    NetworkAnalystNode,
    SpecialistError,
    TierSpecialistNode,
)
from .state import CycleState, make_initial_state
from .supervisor import SupervisorError, SupervisorNode
from .system_mapper import SystemMapperError, SystemMapperNode


# ============================================================
# Node functions (closures over store + harnesses)
# ============================================================
def _make_runner_init_node(store: AuditStore):
    """Idempotent first node that fills in `cycle_id`,
    `cycle_started_id`, and any TypedDict defaults missing from the
    initial state.

    Production callers go through `runner.run_cycle`, which calls
    `store.start_cycle(...)` before invoking the graph and uses
    `make_initial_state()` to stamp every defaulted field onto state.
    For those callers this node is a no-op — every key is already
    present.

    LangGraph dev / Studio bypasses the runner: a user pastes a
    partial input (often just `application_id`) and clicks Submit, so
    the graph sees state with `cycle_id` and `has_system_map` missing.
    Downstream nodes subscript-access those keys (`state["cycle_id"]`,
    `state["has_system_map"]`), which would KeyError. This shim:

      1. If `cycle_id` is missing, calls `store.start_cycle(...)` to
         create one and stamps cycle_id + cycle_started_id.
      2. For every key in `make_initial_state(...)` that's missing
         from state, fills it with the default value.

    Studio users can therefore submit `{"application_id": "app-08"}`
    and the graph picks up the rest. The runner path doesn't change —
    its state arrives fully populated, so step 2's `if key not in
    state` always falls through.
    """
    def node(state: CycleState) -> dict[str, Any]:
        update: dict[str, Any] = {}
        app_id = state.get("application_id", "unknown")

        # Resolve cycle_id / cycle_started_id, with the DB as the
        # source of truth (not the state). This matters because Studio
        # caches thread state across runs — and across dev-server
        # reloads. After a reload, the new in-memory store is empty
        # but the thread still has the old run's cycle_id +
        # cycle_started_id. If we trusted state blindly, the
        # Supervisor would cite a row that no longer exists, and the
        # Reasoning Harness would reject for dangling evidence.
        #
        # Three outcomes, in priority order:
        #
        #   A. state has cycle_id AND the DB has a cycle_started row
        #      for it — use the DB's id (authoritative), correcting
        #      state if it disagrees.
        #   B. state has cycle_id but the DB has no matching row
        #      (Studio after reload, or Studio user typed a freeform
        #      cycle_id) — treat as bare submit, start fresh.
        #   C. state has no cycle_id (true bare submit) — start fresh.
        cycle_id = state.get("cycle_id")
        cycle_started_id = state.get("cycle_started_id")
        if cycle_id:
            db_started_id = store.get_cycle_started_id(cycle_id)
            if db_started_id is not None:
                # Outcome A: DB has the row. Use its id.
                if db_started_id != cycle_started_id:
                    update["cycle_started_id"] = db_started_id
                cycle_started_id = db_started_id
            else:
                # Outcome B: cycle_id is stale. Fall through to mint
                # a fresh one.
                cycle_id = None
                cycle_started_id = None
        if not cycle_id:
            cycle_id = store.start_cycle(
                application_id=app_id,
                trigger_type="manual",
                notes="LangGraph dev / Studio run (no runner)",
            )
            cycle_started_id = store.get_cycle_started_id(cycle_id)
            update["cycle_id"] = cycle_id
            update["cycle_started_id"] = cycle_started_id

        # Fill missing defaults from make_initial_state.
        defaults = make_initial_state(
            application_id=app_id,
            cycle_id=cycle_id,
            cycle_started_id=cycle_started_id,
        )
        for key, default_value in defaults.items():
            if key not in state and key not in update:
                update[key] = default_value
        return update
    return node


def _make_input_validation_node(
    input_harness: InputHarness,
):
    """Validates the trigger via the Input Harness. Sets
    state["input_validation_passed"]; on rejection, sets terminal_state
    so the conditional edge routes to cycle_complete early.

    The audit store is not a parameter here because the Input Harness
    owns the trail writes via `add_harness_event` internally.
    """
    def node(state: CycleState) -> dict[str, Any]:
        trigger = input_harness.validate_trigger(
            cycle_id=state["cycle_id"],
            application_id=state["application_id"],
        )
        known = input_harness.validate_application_known(
            cycle_id=state["cycle_id"],
            application_id=state["application_id"],
        )
        passed = trigger.passed and known.passed
        # The Supervisor cites this row as evidence on its first
        # decision (dispatch_system_mapper). Use the application_known
        # row id (the second check, more specific).
        last_input_id = known.harness_record_id
        if passed:
            return {
                "input_validation_passed": True,
                "last_input_validation_record_id": last_input_id,
            }
        reason = trigger.failure_reason or known.failure_reason
        return {
            "input_validation_passed": False,
            "input_validation_reason": reason,
            "last_input_validation_record_id": last_input_id,
            "terminal_state": "rejected_input",
            "failure_reason": reason,
            "failed_at_stage": "input_harness",
        }
    return node


def _make_system_mapper_node(
    store: AuditStore,
    action_harness: ActionHarness,
    reasoning_harness: ReasoningHarness,
):
    """Wraps SystemMapperNode so System Mapper errors land as
    terminal_state='failed' rather than crashing the graph."""
    mapper = SystemMapperNode(store, action_harness, reasoning_harness)
    def node(state: CycleState) -> dict[str, Any]:
        try:
            return mapper.run(state)
        except SystemMapperError as exc:
            return {
                "terminal_state": "failed",
                "failure_reason": f"system_mapper: {exc}",
                "failed_at_stage": "system_mapper",
            }
    return node


def _make_supervisor_node(
    store: AuditStore,
    reasoning_harness: ReasoningHarness,
):
    """Wraps SupervisorNode with the same error-to-state mapping."""
    supervisor = SupervisorNode(store, reasoning_harness)
    def node(state: CycleState) -> dict[str, Any]:
        try:
            return supervisor.run(state)
        except SupervisorError as exc:
            return {
                "terminal_state": "failed",
                "failure_reason": f"supervisor: {exc}",
                "failed_at_stage": "supervisor",
            }
    return node


def _make_specialist_node(
    specialist_cls: type[TierSpecialistNode],
    store: AuditStore,
    action_harness: ActionHarness,
    reasoning_harness: ReasoningHarness,
    llm_client: LLMClient,
):
    """Wraps a TierSpecialistNode so SpecialistError lands as terminal."""
    specialist = specialist_cls(store, action_harness, reasoning_harness, llm_client)
    name = specialist.agent_name

    def node(state: CycleState) -> dict[str, Any]:
        try:
            return specialist.run(state)
        except SpecialistError as exc:
            return {
                "terminal_state": "failed",
                "failure_reason": f"{name}: {exc}",
                "failed_at_stage": "specialist",
            }
    return node


def _make_evaluator_node(
    store: AuditStore,
    action_harness: ActionHarness,
    reasoning_harness: ReasoningHarness,
    orchestration_harness: OrchestrationHarness,
    llm_client: LLMClient,
):
    """Wraps the Cross-Tier Evaluator. Fires the two new orchestration
    checks first; on rejection, the Evaluator never runs and the cycle
    terminates failed_at_stage='orchestration'."""
    evaluator = CrossTierEvaluatorNode(
        store, action_harness, reasoning_harness, llm_client,
    )

    def node(state: CycleState) -> dict[str, Any]:
        # Two pre-evaluator orchestration checks.
        v_check = orchestration_harness.check_validate_specialists_completed(
            cycle_id=state["cycle_id"],
            specialists_invoked=list(state["specialists_invoked"]),
            specialists_completed=list(state["specialists_completed"]),
            related_event_id=None,
        )
        if not v_check.passed:
            return {
                "terminal_state": "failed",
                "failure_reason": (
                    f"orchestration: {v_check.failure_reason}"
                ),
                "failed_at_stage": "orchestration",
            }
        p_check = orchestration_harness.check_should_proceed_to_evaluator(
            cycle_id=state["cycle_id"],
            specialist_finding_record_ids=list(
                state["specialist_finding_record_ids"]
            ),
            related_event_id=None,
        )
        if not p_check.passed:
            return {
                "terminal_state": "failed",
                "failure_reason": (
                    f"orchestration: {p_check.failure_reason}"
                ),
                "failed_at_stage": "orchestration",
            }
        try:
            return evaluator.run(state)
        except EvaluatorError as exc:
            return {
                "terminal_state": "failed",
                "failure_reason": f"evaluator: {exc}",
                "failed_at_stage": "evaluator",
            }
    return node


def _make_gate_node(
    action_harness: ActionHarness,
):
    """Action Harness recommendation gate node. Stamps
    last_gate_verdict_id onto state."""
    def node(state: CycleState) -> dict[str, Any]:
        if state["last_recommendation_record_id"] is None:
            return {
                "terminal_state": "failed",
                "failure_reason": "gate: no recommendation to gate",
                "failed_at_stage": "gate",
            }
        result = action_harness.check_recommendation_gate(
            cycle_id=state["cycle_id"],
            recommendation_record_id=state["last_recommendation_record_id"],
        )
        update: dict[str, Any] = {
            "last_gate_verdict_id": result.harness_record_id,
        }
        if not result.passed:
            update["terminal_state"] = "failed"
            update["failure_reason"] = f"gate: {result.rejection_reason}"
            update["failed_at_stage"] = "gate"
        return update
    return node


def _make_cycle_complete_node(orchestration_harness: OrchestrationHarness):
    """Decide the final terminal_state and route it through the
    Orchestration Harness's `cycle_completion_legitimate` check before
    the runner writes `cycle_completed`.

    Note: this node does NOT call AuditStore.complete_cycle. The
    runner owns the start/complete pair so the call brackets the
    graph execution; this means cycle_completed lands even if a
    node raises an uncaught exception inside the graph.

    On orchestration-check rejection: the harness has already written
    the rejected verdict to harness_trail, and we coerce the
    terminal_state to 'failed' with stage='orchestration' so the
    `cycle_completed` row the runner writes reflects the harness's
    refusal. This makes the rejection visible in both the audit trail
    (substance: the failed completion) and the harness trail (the
    enforcement: which rule was violated).
    """
    def node(state: CycleState) -> dict[str, Any]:
        if state["terminal_state"] in ("rejected_input", "failed"):
            final = state["terminal_state"]
            reason = state["failure_reason"]
            # If a node already set failed_at_stage (e.g. system_mapper on
            # a parse failure), respect it. Otherwise default based on the
            # terminal state: rejected_input -> input_harness; failed
            # without an explicit stage is left None for the runner's
            # outer try/except to fill in.
            stage = state["failed_at_stage"]
            if stage is None and final == "rejected_input":
                stage = "input_harness"
        elif not state["specialists_invoked"]:
            # Phase 11a: skeleton run, no specialists invoked. Not a
            # failure — supervisor decided there was nothing to dispatch.
            final = "no_specialists"
            reason = "Phase 11a: no specialists wired yet."
            stage = None
        else:
            final = "completed"
            reason = None
            stage = None

        # Cycle-level legitimacy check via the Orchestration Harness.
        check = orchestration_harness.check_cycle_completion_legitimate(
            cycle_id=state["cycle_id"],
            final_status=final,
            failed_at_stage=stage,
            specialists_invoked=list(state["specialists_invoked"]),
            related_event_id=None,
        )
        if not check.passed:
            final = "failed"
            reason = f"orchestration_harness: {check.failure_reason}"
            stage = "orchestration"

        return {
            "terminal_state": final,
            "failure_reason": reason,
            "failed_at_stage": stage,
            # Stamped so the runner can backfill related_event_id after
            # writing cycle_completed. Mirrors the link pattern used
            # for action checks (in dispatch.py) and reasoning checks
            # (in supervisor.py + system_mapper.py).
            "last_orchestration_check_id": check.harness_record_id,
        }
    return node


# ============================================================
# Conditional edges — Supervisor is the only real router
# ============================================================
def _after_input_validation(state: CycleState) -> str:
    """On pass, hand off to Supervisor (the only router); on rejection,
    short-circuit to cycle_complete (the Input Harness has already set
    terminal_state='rejected_input' and failed_at_stage='input_harness').
    """
    return "supervisor" if state["input_validation_passed"] else "cycle_complete"


def _after_system_mapper(state: CycleState) -> str:
    """System Mapper always returns to Supervisor — workers never decide
    termination themselves. On failure the system_mapper node sets
    terminal_state='failed' (caught in the wrapper); the edge still
    points to Supervisor, but Supervisor's _decide handles the terminated
    case (analysis_plan is None) by raising SupervisorError, which the
    wrapper converts to cycle_complete with failed_at_stage='supervisor'
    — except when the mapper itself failed, we want failed_at_stage to
    stay 'system_mapper'. Short-circuit there to preserve the stage.
    """
    if state["terminal_state"] == "failed":
        return "cycle_complete"
    return "supervisor"


def _after_supervisor(state: CycleState):
    """Supervisor is the only router. Maps decision_type (cached on
    state["next_route"] by SupervisorNode.run) to the next destination.

    Returns either a single node-name string OR a list of `Send` objects
    for parallel fan-out. The `dispatch_specialists` branch is the only
    one that fans out — the supervisor decides which specialists to fire
    (one decision row listing N targets), and the conditional edge here
    realizes that decision as N concurrent `Send` invocations.

    LangGraph waits for all parallel branches to complete before routing
    to the next node (the specialists' return edge points back to
    supervisor; the supervisor's NEXT _decide call sees the merged state
    with all findings present and routes onward to `cross_tier_evaluator`
    via the `synthesize` branch).
    """
    if state.get("terminal_state") == "failed":
        return "cycle_complete"
    route = state.get("next_route")
    if route == "dispatch_system_mapper":
        return "system_mapper"
    if route == "dispatch_specialists":
        # Parallel fan-out via Send objects. The supervisor's most-
        # recent dispatch_specialists decision named the targets; they
        # were appended to specialists_invoked. To find THIS turn's
        # dispatch set, take the suffix not yet present in
        # specialists_completed.
        targets = [
            s for s in state.get("specialists_invoked") or []
            if s not in (state.get("specialists_completed") or [])
            and s in ("compute_analyst", "data_layer_analyst",
                      "network_analyst")
        ]
        if not targets:
            return "cycle_complete"
        return [Send(t, state) for t in targets]
    if route == "synthesize":
        return "cross_tier_evaluator"
    if route == "gate":
        return "gate"
    return "cycle_complete"


def _after_worker(state: CycleState) -> str:
    """Specialists, the Evaluator, and the gate all return to the
    Supervisor unless they set terminal_state='failed' (the wrapper
    catches their errors and stamps that)."""
    if state["terminal_state"] == "failed":
        return "cycle_complete"
    return "supervisor"


# ============================================================
# Public builder
# ============================================================
# --------------------------------------------------------------------
# LangGraph Studio metadata helper
#
# Wraps each node callable in a RunnableLambda with tags + a one-line
# description. The tags surface in LangSmith filters (e.g. "show only
# specialists") and in the Studio panel; the description shows on the
# node detail panel for a human reading the graph. None of this is
# visible at runtime — fn still receives the CycleState dict and
# returns its delta as before.
# --------------------------------------------------------------------
def _tagged_node(fn, *, tags: list[str], description: str):
    return RunnableLambda(fn).with_config({
        "tags": tags,
        "metadata": {"description": description},
    })


def build_graph(
    store: AuditStore,
    input_harness: InputHarness,
    action_harness: ActionHarness,
    reasoning_harness: ReasoningHarness | None = None,
    orchestration_harness: OrchestrationHarness | None = None,
    specialist_llm_client: LLMClient | None = None,
    evaluator_llm_client: LLMClient | None = None,
    llm_client: LLMClient | None = None,
):
    """Build and compile the LangGraph application for one cycle.

    Specialists and the Cross-Tier Evaluator each take their own
    LLM client so the two tiers can be configured independently via
    `.env` (SPECIALIST_PROVIDER / SPECIALIST_MODEL for the workers,
    EVALUATOR_PROVIDER / EVALUATOR_MODEL for synthesis).

    Three knobs, in order of precedence:
      - `specialist_llm_client` / `evaluator_llm_client` — pass these
        explicitly (e.g. a MockLLMClient in unit tests, or two
        already-constructed real clients).
      - `llm_client` — back-compat single client used for BOTH tiers.
        Tests that wired a single mock before the split still work.
      - Defaults — when nothing is passed, `make_specialist_client()`
        and `make_evaluator_client()` build the right provider+model
        from environment for each tier independently.
    """
    if reasoning_harness is None:
        reasoning_harness = ReasoningHarness(store)
    if orchestration_harness is None:
        orchestration_harness = OrchestrationHarness(store)
    if specialist_llm_client is None:
        specialist_llm_client = llm_client or make_specialist_client()
    if evaluator_llm_client is None:
        evaluator_llm_client = llm_client or make_evaluator_client()

    graph: StateGraph = StateGraph(CycleState)

    # Runner-init shim. Fills cycle_id + TypedDict defaults when the
    # graph is invoked outside the runner (LangGraph dev / Studio).
    # No-op on the production path because make_initial_state in the
    # runner already populates every key.
    graph.add_node(
        "runner_init",
        _tagged_node(
            _make_runner_init_node(store),
            tags=["init"],
            description=(
                "Idempotent init shim. If cycle_id is missing (Studio "
                "submission, no runner), calls store.start_cycle and "
                "fills TypedDict defaults. No-op when the runner has "
                "already populated the state."
            ),
        ),
    )

    graph.add_node(
        "input_validation",
        _tagged_node(
            _make_input_validation_node(input_harness),
            tags=["harness", "input-validation"],
            description=(
                "Input Harness — validates the incoming app_name, "
                "Terraform fixture, and SLA spec before any agent fires. "
                "On rejection, the cycle short-circuits to cycle_complete."
            ),
        ),
    )
    graph.add_node(
        "system_mapper",
        _tagged_node(
            _make_system_mapper_node(store, action_harness, reasoning_harness),
            tags=["analysis", "system-mapper"],
            description=(
                "Parses the application's Terraform + telemetry envelope "
                "into a tier topology (compute / data layer / network) "
                "and an analysis plan the Supervisor uses to route work."
            ),
        ),
    )
    graph.add_node(
        "supervisor",
        _tagged_node(
            _make_supervisor_node(store, reasoning_harness),
            tags=["routing", "supervisor"],
            description=(
                "State-machine router. Picks the next node based on what "
                "has been completed, what tier evidence is still needed, "
                "and whether the Cross-Tier Evaluator is ready to fire. "
                "Every routing decision is evidence-checked by the "
                "Reasoning Harness before being recorded."
            ),
        ),
    )
    # Three tier specialists.
    graph.add_node(
        "compute_analyst",
        _tagged_node(
            _make_specialist_node(
                ComputeAnalystNode, store, action_harness,
                reasoning_harness, specialist_llm_client,
            ),
            tags=["specialist", "tier:compute"],
            description=(
                "Compute tier specialist. ReAct loop over CPU, memory, "
                "scaling, and configuration MCP tools. Produces one "
                "structured finding (issue_found / no_issue_found / "
                "diagnostic_deferral) with cited evidence_refs."
            ),
        ),
    )
    graph.add_node(
        "data_layer_analyst",
        _tagged_node(
            _make_specialist_node(
                DataLayerAnalystNode, store, action_harness,
                reasoning_harness, specialist_llm_client,
            ),
            tags=["specialist", "tier:data"],
            description=(
                "Database + cache tier specialist. ReAct loop over query "
                "latency, connection pool, cache hit ratio, and top-N "
                "queries / hot keys. Produces one structured finding."
            ),
        ),
    )
    graph.add_node(
        "network_analyst",
        _tagged_node(
            _make_specialist_node(
                NetworkAnalystNode, store, action_harness,
                reasoning_harness, specialist_llm_client,
            ),
            tags=["specialist", "tier:network"],
            description=(
                "Network tier specialist. ReAct loop over throughput, "
                "load-balancer behaviour, and tier-edge latency. "
                "Produces one structured finding."
            ),
        ),
    )
    # Cross-Tier Evaluator (with pre-fire orchestration checks).
    graph.add_node(
        "cross_tier_evaluator",
        _tagged_node(
            _make_evaluator_node(
                store, action_harness, reasoning_harness,
                orchestration_harness, evaluator_llm_client,
            ),
            tags=["evaluator", "synthesis"],
            description=(
                "Three-step synthesis: (1) reconcile drift-check + cross-"
                "tier correlations across specialist findings, (2) commit "
                "a recommendation with finding_type / tier / action_category "
                "/ specific_change, (3) reflect on trade-offs and report "
                "evaluator confidence."
            ),
        ),
    )
    # Action Harness recommendation gate.
    graph.add_node(
        "gate",
        _tagged_node(
            _make_gate_node(action_harness),
            tags=["harness", "action-gate"],
            description=(
                "Action Harness — runs structural and safety checks on "
                "the committed recommendation before it leaves the cycle. "
                "Failures route to cycle_complete with terminal_state="
                "failed."
            ),
        ),
    )
    graph.add_node(
        "cycle_complete",
        _tagged_node(
            _make_cycle_complete_node(orchestration_harness),
            tags=["terminal", "cycle-complete"],
            description=(
                "Terminal node. Records the cycle outcome and final "
                "state, runs the Orchestration Harness post-cycle checks, "
                "and closes out the audit trail."
            ),
        ),
    )

    graph.add_edge(START, "runner_init")
    graph.add_edge("runner_init", "input_validation")
    # Input validation routes to Supervisor on pass; cycle_complete on
    # rejection. Supervisor is the only node that fans out to workers.
    graph.add_conditional_edges(
        "input_validation",
        _after_input_validation,
        {"supervisor": "supervisor", "cycle_complete": "cycle_complete"},
    )
    # Supervisor → {system_mapper, cycle_complete} (Phase 11a). Phase 11b
    # adds specialist_* targets here.
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
    # System Mapper returns to Supervisor.
    graph.add_conditional_edges(
        "system_mapper",
        _after_system_mapper,
        {"supervisor": "supervisor", "cycle_complete": "cycle_complete"},
    )
    # Specialists / Evaluator / Gate all return to Supervisor unless
    # they set terminal_state='failed' (then cycle_complete).
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
# LangGraph Studio entry point
# ============================================================
def graph_factory():
    """Zero-arg factory that the LangGraph dev server / Studio can call.

    Uses an in-memory audit store on purpose:

      - Studio loads the factory from inside an ASGI loop, and blockbuster
        rejects sync filesystem I/O there (the on-disk store calls mkdir
        for `.audit_db/` during construction). In-memory has no FS I/O.
      - Studio runs are exploratory; persisting them to the real DB would
        pollute the trail the inspect CLI surfaces.

    For persistent cycles, use `scripts/run_agents.sh app-NN` — that uses
    the on-disk store. Studio is for graph visualization + ad-hoc runs.

    Referenced from `langgraph.json` at the repo root:
        {"graphs": {"agent": "src.agents.orchestrator:graph_factory"}}
    """
    from ..common.init import get_audit_store
    store = get_audit_store(db_path=":memory:")
    return build_graph(store, InputHarness(store), ActionHarness(store))


# ============================================================
# Backwards-compat stub (kept so any import of `orchestrate` doesn't
# break; the new entry point is `runner.run_cycle`)
# ============================================================
def orchestrate(scenario: dict[str, Any]) -> dict[str, Any]:
    """Legacy entry point retained for backward compatibility.

    The real entry point for Phase 11+ is `src.agents.runner.run_cycle`,
    which takes an application_id and returns a cycle_id. This function
    is preserved so older callers continue to import without an
    ImportError; it raises with a pointer to the new entry point.
    """
    raise NotImplementedError(
        "orchestrate(scenario) is the legacy stub. Use "
        "`from src.agents.runner import run_cycle; run_cycle(app_id)` "
        "instead. See CHANGELOG Phase 11a."
    )


# Suppress unused-import warning for AuditRecord (re-exported below for
# downstream notebooks that build CycleState manually).
__all__ = ["build_graph", "orchestrate", "AuditRecord"]
