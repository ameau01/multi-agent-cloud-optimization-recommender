"""Supervisor node.

The Supervisor reads the System Mapper's `AnalysisPlan` and decides
what to do next. In Phase 11a the decision is hard-coded: the
Supervisor never fans out to specialists; it always terminates the
cycle with `decision_type="complete"` and `terminal_state="no_specialists"`.
Phase 11a.3-5 rewrites the body to a real state machine that routes
to dispatch_system_mapper, dispatch_specialists, synthesize, gate,
or complete based on what's been gathered.

What lands in the audit trail:
  - One `supervisor_decision` row per Supervisor call. The
    `SupervisorDecisionContent` shape (src/models/audit.py) is
    type-discriminated by `decision_type` (one of SupervisorDecisionType).
  - Every decision carries `evidence_refs` — the audit_records ids the
    decision relied on. In 11a the only upstream evidence is the
    system_mapper_output row, so that's what we cite.

The Supervisor records WHY it chose what it chose. In 11a the reason
is always "skeleton mode — specialists not yet wired"; the framing is
explicit so a reviewer can tell at-a-glance that the cycle was a
skeleton run, not a failed fan-out.
"""

from __future__ import annotations

from typing import Any

from ..audit.store import AuditStore
from ..harnesses.reasoning import ReasoningHarness
from ..models.audit import AuditRecord
from ..models.enums import AgentName, SupervisorDecisionType
from .state import CycleState


class SupervisorError(RuntimeError):
    """Raised when the Supervisor can't proceed (e.g. no analysis_plan
    on the state, or the Reasoning Harness rejected the decision). The
    orchestrator handles this by routing to cycle_complete with
    terminal_state='failed' and failed_at_stage='supervisor'."""


class SupervisorNode:
    """Stateless functor. Constructed once per cycle by the orchestrator."""

    def __init__(
        self,
        store: AuditStore,
        reasoning_harness: ReasoningHarness,
    ) -> None:
        self._store = store
        self._reasoning = reasoning_harness

    # ----------------------------------------------------------------
    # Public entry point
    # ----------------------------------------------------------------
    def run(self, state: CycleState) -> dict[str, Any]:
        """Decide what to do next, route the decision through the
        Reasoning Harness, record it, return partial state.

        Supervisor is the only router. It decides between:
          - dispatch_system_mapper (no system map yet — first call)
          - complete (nothing left to do)
          - dispatch_specialists / synthesize / gate (11b+, not yet wired)

        The Reasoning Harness check is a hard gate — if the harness
        rejects the decision (missing/dangling/foreign evidence_refs),
        the Supervisor raises SupervisorError and the orchestrator
        routes to cycle_complete with failed_at_stage='supervisor'.
        That makes "every routing decision is evidence-backed" a runtime
        invariant rather than a documentation aspiration.

        Unlike Phase 11a, Supervisor no longer requires analysis_plan
        on entry — the first call (no system map yet) is exactly when
        Supervisor routes to System Mapper to produce it.
        """
        decision = self._decide(state)

        # Hard gate: every decision must be evidence-backed. The
        # harness writes a reasoning_check row to harness_trail and
        # tells us pass/reject. Reject = block the decision.
        check = self._reasoning.check_decision_evidence_backed(
            cycle_id=state["cycle_id"],
            decision_payload=decision,
            related_event_id=None,
        )
        if not check.passed:
            raise SupervisorError(
                f"Reasoning Harness rejected the decision "
                f"({check.failure_reason}). The decision was not acted on."
            )

        row_id = self._record_decision(state=state, decision=decision)
        # Backfill the reasoning verdict's related_event_id so a reader
        # of harness_trail can answer "which decision did this verdict
        # check?" without parsing details. Mirrors the dispatch.py
        # backfill for action checks.
        self._store.link_harness_to_event(check.harness_record_id, row_id)

        update: dict[str, Any] = {
            "last_supervisor_decision_id": row_id,
            "next_route": decision["decision_type"],
        }
        # specialists_invoked is the *historical* list of every tier
        # specialist dispatched in this cycle (see state.py field doc).
        # Only update it on dispatch_specialists, and APPEND rather than
        # overwrite — otherwise each supervisor call would clobber the
        # list with just the latest decision's targets, causing the
        # Evaluator's pre-fire `validate_specialists_completed` check to
        # see specialists_invoked=['cross_tier_evaluator'] and reject.
        if decision["decision_type"] == "dispatch_specialists":
            new_targets = [
                t for t in decision["targets"]
                if t not in state["specialists_invoked"]
            ]
            if new_targets:
                update["specialists_invoked"] = (
                    list(state["specialists_invoked"]) + new_targets
                )

        # On synthesize: the supervisor is the assembly point. Take the
        # findings the specialists deposited via the operator.add reducer
        # (which leaves them in non-deterministic completion order) and
        # write a deterministically-ordered version into ordered_findings.
        # Sort key is structural (primary_tier first, specialist name as
        # tiebreaker) — content-preserving, deterministic. The evaluator
        # reads ordered_findings, not specialist_findings, so the
        # canonical order flows through to synthesis + rendering.
        if decision["decision_type"] == "synthesize":
            update["ordered_findings"] = sorted(
                state.get("specialist_findings") or [],
                key=lambda f: (
                    f.get("primary_tier") or "",
                    f.get("specialist") or f.get("agent") or "",
                ),
            )
        return update

    # ----------------------------------------------------------------
    # Decision logic — state machine
    # ----------------------------------------------------------------
    @staticmethod
    def _decide(state: CycleState) -> dict[str, Any]:
        """Return the decision payload for this Supervisor call.

        Routing logic (Phase 11a — only two terminal-shape branches
        because no specialists are wired yet):

          - No system map on state → `dispatch_system_mapper`.
            Cites the input_validation harness row as evidence (the only
            upstream record at that point in the cycle).
          - Has system map, plan named no specialists → `complete`
            with terminal_state="no_specialists".
          - Has system map, plan named specialists → `complete` with
            terminal_state="no_specialists" plus a skeleton-mode reason.
            (Phase 11b will turn this branch into `dispatch_specialists`.)

        Phase 11b+ inserts `dispatch_specialists`, `synthesize`, and
        `gate` between system-map-acquired and complete; the routing
        shape doesn't change, only the branch density.
        """
        # Branch 1: no system map → ask System Mapper to produce one.
        if not state["has_system_map"]:
            # Pre-system-map evidence: the only audit_records row that
            # always exists at this point in the cycle is `cycle_started`.
            # The runner stamps its id on state["cycle_started_id"]; cite it.
            # (Note: last_input_validation_record_id is a harness_trail id,
            # which is a separate table — citing it would be a category
            # error and the harness check rejects with "dangling".)
            evidence: list[int] = []
            if state["cycle_started_id"] is not None:
                evidence.append(state["cycle_started_id"])
            return {
                "decision_type": "dispatch_system_mapper",
                "targets": ["system_mapper"],
                "terminal_state": None,
                "reason": (
                    "No tier_topology yet — System Mapper must run to "
                    "produce one before specialists can be selected."
                ),
                "evidence_refs": evidence,
            }

        # System map present. Walk through the post-mapper state machine.
        plan = state["analysis_plan"]
        evidence = []
        if state["last_system_mapper_output_id"] is not None:
            evidence.append(state["last_system_mapper_output_id"])

        # Edge case: plan named no specialists (no tier has telemetry
        # for any of the three specialist roles). Legitimately complete
        # as no_specialists; the orchestration harness waves this
        # through because the pairing matches its rule.
        if plan is None or not plan.specialists_to_invoke:
            return {
                "decision_type": "complete",
                "targets": [],
                "terminal_state": "no_specialists",
                "reason": "Analysis plan named no specialists.",
                "evidence_refs": evidence,
            }

        # Branch 2: still specialists left to invoke → dispatch ALL at
        # once. Parallel fan-out via Send objects (see _after_supervisor
        # in orchestrator.py). Each specialist runs concurrently against
        # its own tier MCP scope; they share no input or state. Findings
        # gather into specialist_findings via the operator.add reducer.
        # When the supervisor is re-invoked after fan-in (specialists
        # all route back here), branch 3 (synthesize) fires.
        pending = [
            s for s in plan.specialists_to_invoke
            if s not in state["specialists_completed"]
        ]
        if pending:
            return {
                "decision_type": "dispatch_specialists",
                "targets": pending,
                "terminal_state": None,
                "reason": (
                    f"Dispatching {len(pending)} specialist(s) in parallel: "
                    f"{', '.join(pending)}. "
                    f"({len(state['specialists_completed'])} of "
                    f"{len(plan.specialists_to_invoke)} previously completed.)"
                ),
                "evidence_refs": evidence,
            }

        # Branch 3: all specialists complete, no evaluator yet → synthesize.
        # Evidence: every specialist_finding row id.
        if state["last_evaluator_record_id"] is None:
            return {
                "decision_type": "synthesize",
                "targets": ["cross_tier_evaluator"],
                "terminal_state": None,
                "reason": (
                    f"All {len(plan.specialists_to_invoke)} specialists "
                    "completed; routing to Cross-Tier Evaluator for "
                    "drift-check and synthesis."
                ),
                "evidence_refs": list(state["specialist_finding_record_ids"]),
            }

        # Branch 4: evaluator done, gate not fired → gate.
        if state["last_gate_verdict_id"] is None:
            gate_evidence: list[int] = []
            if state["last_recommendation_record_id"] is not None:
                gate_evidence.append(state["last_recommendation_record_id"])
            return {
                "decision_type": "gate",
                "targets": ["action_harness"],
                "terminal_state": None,
                "reason": (
                    "Evaluator produced a recommendation; routing to the "
                    "Action Harness recommendation gate."
                ),
                "evidence_refs": gate_evidence,
            }

        # Branch 5: gate fired → complete.
        return {
            "decision_type": "complete",
            "targets": [],
            "terminal_state": "completed",
            "reason": "Gate passed; cycle complete.",
            "evidence_refs": [state["last_gate_verdict_id"]],
        }

    # ----------------------------------------------------------------
    # Audit row
    # ----------------------------------------------------------------
    def _record_decision(
        self,
        *,
        state: CycleState,
        decision: dict[str, Any],
    ) -> int:
        """Append the supervisor_decision row matching the new
        SupervisorDecisionContent shape. Returns the row id so the caller
        can stamp it on state["last_supervisor_decision_id"]."""
        decision_type: SupervisorDecisionType = decision["decision_type"]
        targets: list[AgentName] = list(decision["targets"])
        plan = state["analysis_plan"]
        decision_details: dict[str, Any] = {}
        if plan is not None:
            decision_details["plan_specialists"] = list(plan.specialists_to_invoke)
        content = {
            "decision_type": decision_type,
            "targets": targets,
            "terminal_state": decision["terminal_state"],
            "reason": decision["reason"],
            "evidence_refs": list(decision["evidence_refs"]),
            "decision_details": decision_details,
        }
        record = AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="supervisor_decision",
            agent="supervisor",
            content=content,
        )
        return self._store.add_event(record)
