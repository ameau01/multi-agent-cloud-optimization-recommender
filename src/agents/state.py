"""LangGraph state schema — a coordination protocol between agent nodes.

`CycleState` is a `TypedDict`, not a single Pydantic model. Each key is
an independently-merged channel: most are scalar fields with a single
writer (the node that owns them); `specialist_findings` and
`specialist_finding_record_ids` carry an `operator.add` reducer so
parallel specialists can deposit concurrently without conflict.

Field ownership (each field has exactly one writer except where noted):

  - `application_id`        : runner; immutable for the life of the cycle
  - `cycle_id`              : runner
  - `cycle_started_id`      : runner
  - `input_validation_*`    : input-harness gate node
  - `analysis_plan`,
    `has_system_map`,
    `last_system_mapper_output_id` : system mapper
  - `specialists_invoked`,
    `specialists_to_invoke`,
    `last_supervisor_decision_id`,
    `next_route`,
    `ordered_findings`      : supervisor (assembles deterministically-
                              ordered findings batch for the evaluator)
  - `specialist_findings`,
    `specialist_finding_record_ids` : tier specialists (multi-writer,
                              merged via operator.add reducer)
  - `evaluator_record`,
    `recommendation`,
    `last_evaluator_record_id`,
    `last_recommendation_record_id`,
    `last_gate_verdict_id`  : Cross-Tier Evaluator + Action Harness gate
  - `terminal_state`,
    `failure_reason`,
    `failed_at_stage`,
    `last_orchestration_check_id` : cycle_complete node

The "no node writes a field another node owns" rule is enforced by
single-writer convention (not by the framework). The two multi-writer
fields are the deposit mailbox for parallel specialists; their reducer
is `operator.add` (concat), and the supervisor's deterministic ordering
step writes the sorted batch into the single-writer `ordered_findings`
field that the evaluator reads.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from .analysis_plan import AnalysisPlan


class CycleState(TypedDict, total=False):
    """The LangGraph state. One instance per cycle.

    `total=False`: every field is optional at the TypedDict-validation
    level. The runner fills required fields (`application_id`,
    `cycle_id`) in `make_initial_state()`; nodes fill the rest as the
    cycle progresses.
    """

    # ----- Runner-set; immutable for the life of the cycle. -----
    application_id: str
    cycle_id: str
    # audit_records.id of the cycle_started row. The Supervisor cites
    # this as evidence on its very first decision (before any other
    # audit_records substance exists). Always set by the runner via
    # AuditStore.get_cycle_started_id after start_cycle inserts the row.
    cycle_started_id: int | None

    # ----- Input-harness gate node. -----
    input_validation_passed: bool
    input_validation_reason: str | None
    # audit_records.id of the input_harness summary the Supervisor can
    # cite as evidence on its first decision.
    last_input_validation_record_id: int | None

    # ----- System Mapper. -----
    analysis_plan: AnalysisPlan | None
    # True once the System Mapper has produced a tier_topology that the
    # Supervisor can route on. Mirrors the truthiness of analysis_plan
    # but is named for the Supervisor's state-machine condition.
    has_system_map: bool
    # audit_records.id of the most recent system_mapper_output row.
    last_system_mapper_output_id: int | None

    # ----- Supervisor. -----
    # `specialists_invoked` is the historical list of every specialist
    # that has been dispatched at least once. `specialists_to_invoke`
    # is the still-pending set the Supervisor decided to fan out to but
    # whose findings haven't landed yet. The fan-in completeness check
    # uses `len(specialist_findings) == len(specialists_to_invoke)`.
    specialists_invoked: list[str]
    specialists_to_invoke: list[str]
    # audit_records.id of the Supervisor's most recent supervisor_decision
    # row. Lets the verifier walk every decision in the cycle by following
    # parent_id back from the latest one.
    last_supervisor_decision_id: int | None

    # ----- Tier specialists (multi-writer, reducer-merged). -----
    # Parallel specialists deposit concurrently; `operator.add` (list
    # concat) merges the three deltas. Order in this list is non-
    # deterministic (it follows whichever branch finished first);
    # downstream consumers must NOT rely on this list's order — they
    # read `ordered_findings` instead, which the supervisor writes
    # after deterministically sorting this concat'd list by tier name.
    specialist_findings: Annotated[list[dict[str, Any]], add]
    # Same merge semantics — record-id list grows as each specialist's
    # finding row lands in the audit DB. The Cross-Tier Evaluator and
    # the Supervisor cite these ids as evidence_refs.
    specialist_finding_record_ids: Annotated[list[int], add]
    # Same merge semantics — each specialist appends its own name.
    # Order is non-deterministic; the supervisor's fan-in check uses
    # `len(specialists_completed) == len(specialists_to_invoke)` (a
    # length comparison, order-insensitive).
    specialists_completed: Annotated[list[str], add]

    # ----- Supervisor's deterministic re-projection (single writer). -----
    # After fan-in, the supervisor sorts `specialist_findings` by
    # `(primary_tier, specialist)` and writes the sorted list here.
    # The Cross-Tier Evaluator reads ONLY this field — never the raw
    # `specialist_findings`. This separation lets the dumb reducer
    # gather concurrent deposits while the supervisor owns the
    # canonical-order presentation to the next stage. Single-writer ⇒
    # no reducer needed.
    ordered_findings: list[dict[str, Any]]

    # ----- Cross-Tier Evaluator + Action Harness gate. -----
    evaluator_record: dict[str, Any] | None
    recommendation: dict[str, Any] | None
    last_evaluator_record_id: int | None
    last_recommendation_record_id: int | None
    # harness_trail.id of the Action Harness's recommendation gate
    # verdict. The Supervisor's `complete` decision is only legitimate
    # after this has fired; the Orchestration Harness's
    # `cycle_completion_legitimate` check verifies the linkage.
    last_gate_verdict_id: int | None

    # ----- Supervisor's most recent routing decision (label). -----
    # The conditional edge after the supervisor node reads this to know
    # which worker (or cycle_complete) to route to next. Mirrors the
    # SupervisorDecisionType Literal in src/models/enums.py.
    next_route: str | None

    # ----- Cycle-complete node. -----
    terminal_state: str | None
    failure_reason: str | None
    # Machine-readable counterpart to failure_reason — names the stage
    # the cycle stopped at. One of FailureStage values (see
    # src/models/enums.py).
    failed_at_stage: str | None
    # harness_trail.id of the orchestration_check verdict written by
    # the cycle_complete node.
    last_orchestration_check_id: int | None


def make_initial_state(
    application_id: str,
    cycle_id: str,
    cycle_started_id: int | None = None,
) -> CycleState:
    """Factory for the per-cycle initial state.

    Sets the runner-owned fields and zero/empty defaults for every
    other field. Nodes mutate from here. Defaults match the prior
    Pydantic `Field(default_factory=...)` semantics field-for-field.
    """
    return CycleState(
        application_id=application_id,
        cycle_id=cycle_id,
        cycle_started_id=cycle_started_id,
        input_validation_passed=False,
        input_validation_reason=None,
        last_input_validation_record_id=None,
        analysis_plan=None,
        has_system_map=False,
        last_system_mapper_output_id=None,
        specialists_invoked=[],
        specialists_to_invoke=[],
        last_supervisor_decision_id=None,
        specialist_findings=[],
        specialist_finding_record_ids=[],
        specialists_completed=[],
        ordered_findings=[],
        evaluator_record=None,
        recommendation=None,
        last_evaluator_record_id=None,
        last_recommendation_record_id=None,
        last_gate_verdict_id=None,
        next_route=None,
        terminal_state=None,
        failure_reason=None,
        failed_at_stage=None,
        last_orchestration_check_id=None,
    )
