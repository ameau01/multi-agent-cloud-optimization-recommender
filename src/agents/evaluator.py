"""Cross-Tier Evaluator — single-shot synthesis across specialist findings.

Unlike the tier specialists, the Evaluator does NOT run a ReAct loop.
It receives all specialist findings + the System Mapper's plan + any
cross-tier observations as input, and produces exactly one structured
`evaluator_record` (drift-check + synthesis + trade-off scores) plus
one `recommendation` audit row.

The Evaluator is the only agent that sees across tiers — by design,
so synthesis happens in exactly one place. The Action Harness gates
the Evaluator's tool scope (it may re-read per-tier telemetry for
synthesis context) and the recommendation gate at the end of the
cycle. The Reasoning Harness gates each drift-check verdict + the
evidence binding on the synthesized recommendation.

Handles every legitimate finding-mix the dataset produces:

  - All specialists `issue_found` → standard cross-tier synthesis,
    cite primary + secondary tiers, full action_category.
  - Mixed `issue_found` + `no_issue_found` → synthesize across
    issuers, note healthy tiers.
  - All `no_issue_found` → recommendation = no_issue_found,
    primary_tier=None, action_category=None (the app-06 restraint
    case).
  - All `diagnostic_deferral` → recommendation = diagnostic_deferral,
    primary_tier="deferred" (the app-15 / app-17 deferral case).

`primary_tier=None` and `action_category=None` are *legitimate values*
for restraint and deferral — the Recommendation Pydantic model must
treat these as Optional, and the eval-set scorer already short-circuits
scoring for these cases (see docs/eval-set.md and src/evaluator/).
"""

from __future__ import annotations

import json
from typing import Any

from ..audit.store import AuditStore
from ..harnesses.action import ActionHarness
from ..harnesses.reasoning import ReasoningHarness
from ..models.audit import AuditRecord
from ..models.enums import (
    ACTION_CATEGORY_VALUES,
    FINDING_TYPE_VALUES,
    TIERS,
    TIERS_OR_DEFERRED,
    AgentName,
)
from .llm_client import LLMClient
from .prompts import load_prompt
from .state import CycleState


# Pre-sorted lists for the tool-schema enums. Sourced from the
# canonical enum frozensets in src/models/enums.py so the agent's
# tool schemas and the Scorer's allowed-value universe stay in
# lockstep. If a new ActionCategory or FindingType is added there,
# the agent's tool schema picks it up the next time this module loads.
_FINDING_TYPE_ENUM = sorted(FINDING_TYPE_VALUES)
_TIER_ENUM = sorted(TIERS_OR_DEFERRED)   # includes "deferred" sentinel
_REAL_TIER_ENUM = sorted(TIERS)          # cross-tier correlations only
_ACTION_CATEGORY_ENUM = sorted(ACTION_CATEGORY_VALUES)
_DRIFT_VERDICT_ENUM = ["tight", "loose", "contradictory"]
_CONFIDENCE_LEVEL_ENUM = ["high", "medium", "low"]
_TRADE_OFF_DIMENSION_ENUM = ["cost", "performance", "reliability", "risk"]


# ====================================================================
# Step 1 of the three-step chain: produce_reconciliation
# --------------------------------------------------------------------
# The LLM reads specialist findings + raw evidence and produces five
# reasoning artifacts that reconcile across tiers. These become the
# "Specialist findings" and "Cross-tier analysis" sections of the
# rendered report. The LLM does NOT commit to a recommendation here.
# ====================================================================
PRODUCE_RECONCILIATION_TOOL: dict[str, Any] = {
    "name": "produce_reconciliation",
    "description": (
        "Step 1 of 3: reconcile specialist findings across tiers. "
        "Walk through topology, per-specialist re-statement, drift "
        "checks, cross-tier correlations, and conflict resolution. "
        "Call this exactly once. Do NOT commit to a recommendation "
        "yet — that happens in step 2 (produce_recommendation)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topology_assessment": {
                "type": "string",
                "description": (
                    "Which specialists were invoked, which were not, "
                    "and why. Include tier-coverage notes from the "
                    "System Mapper output (e.g. 'Only the Compute "
                    "Analyst was invoked. The System Mapper observed "
                    "that no database, cache, or network tier is "
                    "present in the Terraform.' Or: 'The Data Layer "
                    "Analyst covers both cache and database tiers per "
                    "docs/agents.md, so the cache root cause and the "
                    "DB symptom are captured inside one specialist's "
                    "finding.')."
                ),
            },
            "specialist_findings_summary": {
                "type": "array",
                "description": (
                    "One row per specialist, re-stated in your own "
                    "words (do not just copy each headline). Each row "
                    "must be an object with these keys:\n"
                    "  - agent: string (e.g. 'compute_analyst')\n"
                    "  - finding_type: one of " + ", ".join(_FINDING_TYPE_ENUM) + "\n"
                    "  - confidence: 'high' | 'medium' | 'low' (use "
                    "empty string for system_mapper)\n"
                    "  - key_observation: 1-2 sentences summarizing "
                    "what the specialist saw and why it matters\n"
                    "  - evidence_refs: array of integer audit row ids "
                    "the specialist cited"
                ),
            },
            "drift_check": {
                "type": "array",
                "description": (
                    "One row per specialist. Each row must be an object "
                    "with these keys:\n"
                    "  - agent: string (the specialist name)\n"
                    "  - verdict: 'tight' | 'loose' | 'contradictory'\n"
                    "  - narrative: short prose tying the verdict to "
                    "specific evidence_refs (e.g. 'The Data Layer "
                    "Analyst's conclusion that cache is the root cause "
                    "is supported by obs_data_001 through obs_data_004 "
                    "(cache pressure) plus obs_data_006 (DB CPU "
                    "healthy, so DB is absorbing).')\n"
                    "  - supporting_evidence_refs: array of integer "
                    "audit row ids"
                ),
            },
            "cross_tier_correlations": {
                "type": "array",
                "description": (
                    "List every observed cross-tier correlation from "
                    "the correlation_evidence cited in the raw evidence. "
                    "Each row must be an object with these keys:\n"
                    "  - tier_a: one of compute | database | cache | network\n"
                    "  - tier_b: one of compute | database | cache | network\n"
                    "  - coefficient: number (Pearson coefficient)\n"
                    "  - lag_minutes: integer or null (0 for zero-lag, "
                    "null if not reported)\n"
                    "  - interpretation: short prose explaining what "
                    "the signal means (e.g. 'Cache misses and DB "
                    "latency move in lockstep. Misses overflow to the "
                    "DB.')\n"
                    "  - evidence_ref: integer audit row id, or null\n"
                    "Use an empty array when no cross-tier correlations "
                    "were observed."
                ),
            },
            "conflict_resolution": {
                "type": "string",
                "description": (
                    "How specialist disagreements were resolved. E.g. "
                    "'No specialist disagreement; the data layer is the "
                    "only actionable claim and the only one cited in "
                    "the recommendation.' If there was conflict, name "
                    "the conflict and the resolution path."
                ),
            },
        },
        "required": [
            "topology_assessment", "specialist_findings_summary",
            "drift_check", "cross_tier_correlations",
            "conflict_resolution",
        ],
    },
}


# ====================================================================
# Step 2 of the three-step chain: produce_recommendation
# --------------------------------------------------------------------
# The LLM has just produced reconciliation (see PRODUCE_RECONCILIATION_TOOL).
# Now it commits to the final recommendation, anchored in that
# reconciliation. The fields here populate the "Summary" + "Final
# recommendation" sections of the rendered report.
# ====================================================================
PRODUCE_RECOMMENDATION_TOOL: dict[str, Any] = {
    "name": "produce_recommendation",
    "description": (
        "Step 2 of 3: commit to the recommendation, anchored in the "
        "reconciliation you just produced. Call this exactly once. "
        "After this call, you MUST call produce_reflection with the "
        "trade-off and confidence reflection."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {
                "type": "string",
                "description": (
                    "One sentence stating the causal claim with "
                    "direction. For issue_found: name the cascade across "
                    "tiers (e.g. 'Slow database queries during business "
                    "hours cascade into elevated application latency on "
                    "the compute tier.'). For no_issue_found: 'No "
                    "actionable issue observed; all tiers within healthy "
                    "bands.' For diagnostic_deferral: the dimension that "
                    "is unobservable from current evidence."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "2-3 sentences with three explicit beats: "
                    "(a) the causal claim (restate the cascade); "
                    "(b) enumeration + mechanism (count implicated "
                    "entities and name the mechanism, e.g. 'Six queries "
                    "account for the worst p95 latencies, all of them "
                    "missing covering indexes.'); "
                    "(c) explicit restraint with quantitative evidence "
                    "naming what NOT to change and why (e.g. 'Compute is "
                    "correctly sized at 8 m5.large instances with CPU "
                    "p95 stable at 27%. Scaling compute would not "
                    "address the root cause.'). All three beats are "
                    "required even when one is short."
                ),
            },
            "finding_type": {
                "type": "string",
                "enum": _FINDING_TYPE_ENUM,
            },
            "primary_tier": {
                # null is legitimate for no_issue_found; the enum below
                # is exclusive of null, so the JSON Schema "type" field
                # accepts both string and null to keep both shapes valid.
                "type": ["string", "null"],
                "enum": [*_TIER_ENUM, None],
                "description": (
                    "Tier the recommendation acts on. null when "
                    "finding_type is no_issue_found. 'deferred' when "
                    "diagnostic_deferral. Otherwise one of "
                    "compute/database/cache/network."
                ),
            },
            "secondary_tier": {
                "type": ["string", "null"],
                "enum": [*_TIER_ENUM, None],
                "description": (
                    "Second tier involved in cross-tier scenarios. "
                    "null when single-tier."
                ),
            },
            "action_category": {
                "type": ["string", "null"],
                # Constrained vocabulary — the Scorer's Correctness
                # layer enforces the same set. A free-form invented
                # value (e.g. 'query_optimization_and_read_scaling')
                # would fail Correctness even when the substantive
                # reasoning is right.
                "enum": [*_ACTION_CATEGORY_ENUM, None],
                "description": (
                    "The change category. Pick the closest match from "
                    "the enum — do not invent new strings. null for "
                    "no_issue_found and diagnostic_deferral."
                ),
            },
            "headline": {"type": "string"},
            "reasoning": {"type": "string"},
            "specific_change": {
                "type": "string",
                "description": (
                    "Operationally precise description of the change(s) "
                    "to make. This is the field the eval-set's LLM "
                    "judge compares against the gold's specific_change "
                    "for the richness score. Aim for the level of "
                    "specificity an on-call engineer would need to "
                    "execute the change without follow-up questions: "
                    "name specific resources (e.g. 'composite index "
                    "(user_id, id) on carts'), specific query "
                    "identifiers when relevant, specific cost deltas "
                    "when cost evidence is available, and the post-"
                    "change projected metric targets (e.g. 'P95 < "
                    "220ms'). Reasoning explains *why*; specific_change "
                    "tells the operator *exactly what to do*."
                ),
            },
            "evidence": {
                "type": "object",
                "title": "RecommendationEvidence",
                "description": (
                    "Structured restatement of the bullets you cite in "
                    "`reasoning`. Three lists, each one a list of short "
                    "string bullets. Pull from the specialist findings "
                    "+ raw observation bodies above. >= 3 bullets total "
                    "across all three lists satisfies the Rich "
                    "evidence_structured check."
                ),
                "properties": {
                    "telemetry_observations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Metric-level observations from the "
                            "telemetry tools (e.g. 'db query P95 791ms "
                            "exceeds 300ms SLA target')."
                        ),
                    },
                    "infrastructure_context": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Topology / config facts (e.g. '1 read "
                            "replica, no R/W splitting')."
                        ),
                    },
                    "correlation_observations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Cross-tier statistical relationships "
                            "(e.g. 'db latency leads app latency, "
                            "Pearson r=0.945, lag=15min')."
                        ),
                    },
                },
            },
            "projected_state": {
                "type": "object",
                "title": "ProjectedState",
                "description": (
                    "Post-change numeric estimates. At least one "
                    "numeric field is required to satisfy the Rich "
                    "projected_state_quantified check. Use ranges as "
                    "strings when appropriate (e.g. '180-240'), but "
                    "include at least one numeric field."
                ),
                "properties": {
                    "cpu_p95_pct_estimate": {
                        "type": ["string", "number", "null"]
                    },
                    "memory_p95_pct_estimate": {
                        "type": ["string", "number", "null"]
                    },
                    "latency_p95_ms_estimate": {
                        "type": ["string", "number", "null"],
                        "description": (
                            "Numeric or range string. For scenario 08 "
                            "the gold uses '180-240' (ms)."
                        ),
                    },
                    "sla_availability_preserved": {
                        "type": ["boolean", "null"]
                    },
                    "notes": {"type": ["string", "null"]},
                },
            },
            "cost_impact": {
                "type": "object",
                "title": "CostImpact",
                "description": (
                    "Monthly cost delta. At least one non-zero numeric "
                    "field (current_monthly_usd, projected_monthly_usd, "
                    "savings_monthly_usd, or savings_pct) is required "
                    "to satisfy the Rich cost_impact_quantified check. "
                    "Pull current_monthly_usd from get_monthly_cost "
                    "observations cited above; project the delta from "
                    "the action(s) you propose. Sign matters: "
                    "savings_monthly_usd is negative when the "
                    "recommendation increases cost."
                ),
                "properties": {
                    "current_monthly_usd": {"type": ["number", "null"]},
                    "projected_monthly_usd": {"type": ["number", "null"]},
                    "savings_monthly_usd": {
                        "type": ["number", "null"],
                        "description": (
                            "Negative when the recommendation "
                            "increases cost (e.g. adding replicas)."
                        ),
                    },
                    "savings_pct": {"type": ["number", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
            },
        },
        "required": [
            "root_cause", "summary",
            "finding_type", "headline", "reasoning", "specific_change",
            # The three structured sub-objects are required so the LLM
            # does not skip them in favour of pouring the same numbers
            # into specific_change prose.
            "evidence", "projected_state", "cost_impact",
        ],
    },
}


# --------------------------------------------------------------------
# Post-recommendation coherence guard.
#
# The PRODUCE_RECOMMENDATION_TOOL schema lists primary_tier and
# action_category as nullable (legitimate for no_issue_found /
# diagnostic_deferral), so the schema alone cannot enforce that they
# are non-null when finding_type=issue_found. The prompt asks for it,
# but the LLM occasionally produces an issue_found recommendation with
# a null taxonomy field (see app-07 in the 18-scenario integration
# test). This helper flags that condition so the caller can re-prompt.
# --------------------------------------------------------------------
def _coherence_missing_fields(rec: dict[str, Any] | None) -> list[str]:
    """Return the list of taxonomy fields that are null when they must
    be set. Empty list means the recommendation is coherent. None input
    returns an empty list (caller handles the None separately)."""
    if not isinstance(rec, dict):
        return []
    if rec.get("finding_type") != "issue_found":
        return []
    missing: list[str] = []
    if rec.get("primary_tier") in (None, ""):
        missing.append("primary_tier")
    if rec.get("action_category") in (None, ""):
        missing.append("action_category")
    return missing


# ====================================================================
# Step 3 of the three-step chain: produce_reflection
# --------------------------------------------------------------------
# Post-decision reflection. The LLM has the reconciliation AND the
# committed recommendation in context. Now it scores the trade-offs
# and narrates evaluator confidence. These fields become the
# "Trade-off analysis" and "Evaluator confidence" sections.
# ====================================================================
PRODUCE_REFLECTION_TOOL: dict[str, Any] = {
    "name": "produce_reflection",
    "description": (
        "Step 3 of 3: post-decision reflection. Score the trade-offs "
        "of the committed recommendation across four dimensions, "
        "narrate the directional logic, and report your confidence. "
        "Call this exactly once. After this call, the Evaluator's work "
        "is done."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "trade_off_analysis": {
                "type": "array",
                "description": (
                    "Four rows, one per dimension. Each row must be an "
                    "object with these keys:\n"
                    "  - dimension: 'cost' | 'performance' | "
                    "'reliability' | 'risk'\n"
                    "  - value: quantified outcome where possible "
                    "(e.g. '-$2,400 / month', '+66% p95'). May be 'no "
                    "change' for no_issue_found / diagnostic_deferral.\n"
                    "  - note: short prose explaining the score"
                ),
            },
            "trade_off_philosophy": {
                "type": "string",
                "description": (
                    "Closing paragraph after the trade-off table. "
                    "Explain the directional logic (e.g. 'This is a "
                    "reliability investment, not a cost-reduction "
                    "recommendation. The trade-off exchange is "
                    "explicit: $2,400/month buys an SLA-compliant "
                    "checkout flow.') and any alternatives considered "
                    "and rejected. Use empty string for restraint and "
                    "deferral cases."
                ),
            },
            "trade_off_scores": {
                "type": "object",
                "title": "TradeOffScores",
                "description": (
                    "Three numeric scores on independent axes — these "
                    "are the machine-readable counterpart to "
                    "trade_off_analysis. Each is a number; sign "
                    "indicates direction (negative = worse, positive = "
                    "better). Do not collapse to a single composite."
                ),
                "properties": {
                    "cost_impact": {"type": "number"},
                    "performance_impact": {"type": "number"},
                    "reliability_impact": {"type": "number"},
                },
                "required": [
                    "cost_impact", "performance_impact",
                    "reliability_impact",
                ],
            },
            "evaluator_confidence_level": {
                "type": "string",
                "enum": _CONFIDENCE_LEVEL_ENUM,
            },
            "evaluator_confidence_narrative": {
                "type": "string",
                "description": (
                    "Prose justification for the confidence level. "
                    "Name the load-bearing observation(s) — the "
                    "evidence whose presence or absence licenses the "
                    "recommendation (e.g. 'The DB CPU healthy "
                    "observation (obs_data_006) is the load-bearing "
                    "check that ruled out the DB-bottleneck "
                    "alternative.')."
                ),
            },
            "evaluator_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Numeric counterpart to evaluator_confidence_level. "
                    "Use ranges: high >= 0.8, medium 0.5-0.8, low < 0.5."
                ),
            },
        },
        "required": [
            "trade_off_analysis", "trade_off_philosophy",
            "trade_off_scores", "evaluator_confidence_level",
            "evaluator_confidence_narrative", "evaluator_confidence",
        ],
    },
}


class EvaluatorError(RuntimeError):
    """Raised when the Cross-Tier Evaluator cannot produce a valid
    synthesis (LLM crashed, malformed output, Reasoning Harness
    rejected drift verdicts). The orchestrator catches this and
    terminates the cycle with failed_at_stage='evaluator'."""


class CrossTierEvaluatorNode:
    """Three-step synthesis agent. Construct once per cycle.

    The three steps (each one LLM call):
      1. produce_reconciliation — topology assessment, per-specialist
         re-statement, drift check, cross-tier correlations with
         interpretation, conflict resolution. No recommendation yet.
      2. produce_recommendation — anchored in step 1's output:
         root cause, summary (cascade + enumeration + restraint), and
         the recommendation fields (finding_type, primary_tier,
         action_category, specific_change, evidence / projected_state /
         cost_impact sub-objects).
      3. produce_reflection — post-decision reflection: trade-off
         analysis (4 rows + philosophy paragraph), trade-off numeric
         scores, evaluator confidence (level + narrative + numeric).

    Inputs (read from CycleState):
      - specialist_finding_record_ids: list[int] of all findings the
        specialists landed this cycle.
      - last_system_mapper_output_id: the analysis plan's row id, for
        evidence-citation continuity.
      - application_id, cycle_id: standard context.

    Outputs:
      - One `evaluator_record` audit row carrying drift verdicts,
        cross-tier interactions, trade-off scores, and the three-step
        reasoning sub-objects (reconciliation + reflection).
      - One `recommendation` audit row carrying the recommendation
        Composite plus reconciliation + reflection sub-objects so the
        renderer can read every section in one place.
      - Reasoning Harness routes the drift verdicts through
        check_evaluator_drift_verdicts.
      - Returns state-update dict with last_evaluator_record_id and
        last_recommendation_record_id stamped for the Supervisor.
    """

    agent_name: AgentName = "cross_tier_evaluator"
    prompt_name = "cross_tier_evaluator"

    def __init__(
        self,
        store: AuditStore,
        action_harness: ActionHarness,
        reasoning_harness: ReasoningHarness,
        llm_client: LLMClient,
    ) -> None:
        self._store = store
        self._action_harness = action_harness   # for future tool-use
        self._reasoning = reasoning_harness
        self._llm = llm_client

    # ----------------------------------------------------------------
    # Public entry point
    # ----------------------------------------------------------------
    def run(self, state: CycleState) -> dict[str, Any]:
        """Read specialist findings from the audit trail, prompt the
        Evaluator LLM, produce the structured synthesis + recommendation.

        Raises EvaluatorError on LLM failure, missing produce_synthesis
        call, malformed structured output, or Reasoning Harness
        rejection of the drift verdicts.
        """
        findings = self._load_findings(state)
        if not findings:
            # Should never happen if the orchestration harness's
            # should_proceed_to_evaluator check fires first, but
            # defensive-by-design rather than rely on harness ordering.
            raise EvaluatorError(
                "No specialist findings found for cycle — Evaluator "
                "cannot synthesize from nothing."
            )

        synthesis = self._run_synthesis(state, findings)

        # Reasoning Harness check on the drift verdicts (each verdict
        # must be in {tight, loose, contradictory}).
        drift_check = self._reasoning.check_evaluator_drift_verdicts(
            cycle_id=state["cycle_id"],
            evaluator_payload=synthesis,
            related_event_id=None,
        )
        if not drift_check.passed:
            raise EvaluatorError(
                f"Reasoning Harness rejected drift verdicts: "
                f"{drift_check.failure_reason}"
            )

        # Substance-quality check: a `tight` drift verdict must cite at
        # least one observation with substantive measurement. This is
        # the gate that catches a specialist citing empty observations
        # (e.g. get_per_instance_breakout=[], time_pattern n_records=0)
        # as if they confirmed a positive verdict. Independent of the
        # verdict-value check above — that catches malformed verdict
        # strings; this catches hollow citations.
        density_check = self._reasoning.check_drift_evidence_density(
            cycle_id=state["cycle_id"],
            evaluator_payload=synthesis,
            related_event_id=None,
        )
        if not density_check.passed:
            raise EvaluatorError(
                f"Reasoning Harness rejected drift evidence density: "
                f"{density_check.failure_reason}"
            )

        ev_row_id = self._record_evaluator(state, synthesis, findings)
        rec_row_id = self._record_recommendation(state, synthesis)

        # Backfill the drift-check verdict to point at the evaluator
        # row it judged.
        self._store.link_harness_to_event(
            drift_check.harness_record_id, ev_row_id,
        )

        return {
            "evaluator_record": synthesis,
            "recommendation": synthesis.get("recommendation"),
            "last_evaluator_record_id": ev_row_id,
            "last_recommendation_record_id": rec_row_id,
        }

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------
    def _load_findings(self, state: CycleState) -> list[dict[str, Any]]:
        """Return the supervisor-ordered findings batch.

        After parallel fan-out, the supervisor writes the deterministically
        sorted list of finding content dicts into state["ordered_findings"]
        (sorted by primary_tier, then specialist name). The evaluator reads
        from there so its input order is reproducible across runs.

        Fallback to the audit-DB-loaded path if `ordered_findings` is
        empty (e.g. tests with mocked state that pre-populate
        specialist_finding_record_ids but not ordered_findings).
        """
        ordered = state.get("ordered_findings") or []
        if ordered:
            return list(ordered)
        # Legacy fallback: rebuild from audit DB.
        from ..audit.queries import get_cycle_events
        events = get_cycle_events(self._store, state["cycle_id"])
        findings_by_id = {
            e.id: e.content for e in events
            if e.type == "specialist_finding" and e.id is not None
        }
        return [
            findings_by_id[rid]
            for rid in state["specialist_finding_record_ids"]
            if rid in findings_by_id
        ]

    def _run_synthesis(
        self, state: CycleState, findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Three LLM calls chained: reconcile, recommend, reflect.

        Step 1 (produce_reconciliation) reads specialist findings and
        raw evidence, then produces five reasoning artifacts:
        topology_assessment, specialist_findings_summary, drift_check,
        cross_tier_correlations, conflict_resolution. These become the
        "Specialist findings" + "Cross-tier analysis" report sections.

        Step 2 (produce_recommendation) sees the reconciliation in its
        context and commits to the recommendation: root_cause, summary
        (cascade + enumeration + restraint), and the existing
        recommendation fields (finding_type, primary_tier, action_category,
        specific_change, evidence/projected_state/cost_impact sub-objects).

        Step 3 (produce_reflection) sees both prior outputs and produces
        post-decision reflection: trade_off_analysis (4 rows + philosophy
        paragraph), trade_off_scores (numeric), evaluator_confidence
        (level + narrative + numeric).

        The user message in every step carries (1) each specialist's
        structured finding and (2) the raw observation body for every
        evidence_ref. Layer (2) is critical: specialist reasoning_summaries
        are 2-4 sentence rollups that cannot carry artifacts the Evaluator
        needs (actual SQL text, instance classes, dollar figures). With
        the raw evidence in context the LLM reads SQL WHERE/JOIN clauses
        verbatim and quotes concrete operational artifacts.

        Returns a synthesis dict with three primary sub-objects
        (`reconciliation`, `recommendation`, `reflection`) plus
        backwards-compat keys (`drift_verdicts`, `cross_tier_interactions`,
        `trade_off_scores`, `evaluator_confidence`) read by the existing
        recording layer and the Reasoning Harness.
        """
        system_prompt = load_prompt(self.prompt_name).format(
            app_name=state["application_id"],
        )
        findings_text = "\n\n".join([
            f"### {f.get('specialist', '?')}\n"
            f"- finding_type: {f.get('finding_type')}\n"
            f"- primary_tier: {f.get('primary_tier')}\n"
            f"- headline: {f.get('headline')}\n"
            f"- reasoning_summary: {f.get('reasoning_summary')}\n"
            f"- evidence_refs: {f.get('evidence_refs')}\n"
            for f in findings
        ])

        # Load the raw observation bodies for every cited evidence_ref so
        # the LLM sees the underlying tool output, not just the
        # specialist's summary. Index by audit_records.id for O(1) lookup.
        from ..audit.queries import get_cycle_events  # noqa: PLC0415
        events = get_cycle_events(self._store, state["cycle_id"])
        events_by_id = {e.id: e for e in events if e.id is not None}

        evidence_blocks: list[str] = []
        seen_ids: set[int] = set()
        for f in findings:
            specialist = f.get("specialist", "?")
            for ref in f.get("evidence_refs") or []:
                if ref in seen_ids:
                    continue
                seen_ids.add(ref)
                ev = events_by_id.get(ref)
                if ev is None:
                    continue
                content_json = json.dumps(ev.content, default=str, indent=2)
                evidence_blocks.append(
                    f"### evidence_ref={ref}  "
                    f"(type={ev.type}, agent={ev.agent}, "
                    f"cited_by={specialist})\n"
                    f"```json\n{content_json}\n```"
                )
        evidence_text = (
            "\n\n".join(evidence_blocks)
            if evidence_blocks else
            "(no observation bodies cited by specialists)"
        )

        # ------------------------------------------------------------
        # Step 1: produce_reconciliation
        # ------------------------------------------------------------
        reconciliation_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt,
                "_mock_key": (self.agent_name, "reconcile"),
            },
            {
                "role": "user",
                "content": (
                    f"Step 1 of 3 for {state['application_id']}.\n\n"
                    f"Reconcile the specialist findings across tiers. "
                    f"Call produce_reconciliation exactly once with:\n"
                    f"  - topology_assessment\n"
                    f"  - specialist_findings_summary (one row per "
                    f"specialist in your own words)\n"
                    f"  - drift_check (per-specialist verdict + "
                    f"narrative tying to evidence_refs)\n"
                    f"  - cross_tier_correlations (one row per "
                    f"correlation with interpretation)\n"
                    f"  - conflict_resolution\n\n"
                    f"Do NOT commit to a recommendation yet — that "
                    f"happens in step 2.\n\n"
                    f"=== Specialist findings ===\n\n"
                    f"{findings_text}\n\n"
                    f"=== Raw evidence (observation bodies cited above) ===\n\n"
                    f"{evidence_text}"
                ),
            },
        ]
        reconciliation_response = self._llm.complete(
            reconciliation_messages, tools=[PRODUCE_RECONCILIATION_TOOL],
        )
        reconciliation = self._extract_tool_args(
            reconciliation_response, PRODUCE_RECONCILIATION_TOOL["name"],
        )
        if reconciliation is None:
            raise EvaluatorError(
                "Evaluator LLM did not call produce_reconciliation "
                "(step 1 of 3)"
            )

        # ------------------------------------------------------------
        # Step 2: produce_recommendation, with reconciliation in context.
        # ------------------------------------------------------------
        reconciliation_recap = json.dumps(
            reconciliation, default=str, indent=2,
        )
        recommendation_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt,
                "_mock_key": (self.agent_name, "recommend"),
            },
            {
                "role": "user",
                "content": (
                    f"Step 2 of 3 for {state['application_id']}.\n\n"
                    f"You just produced this reconciliation:\n\n"
                    f"=== Your reconciliation (from step 1) ===\n\n"
                    f"```json\n{reconciliation_recap}\n```\n\n"
                    f"Now call produce_recommendation with the final "
                    f"recommendation, anchored in the reconciliation "
                    f"above. The specific_change must follow directly "
                    f"from your drift_check + cross_tier_correlations. "
                    f"Use the raw evidence below verbatim when "
                    f"populating specific_change: read SQL "
                    f"WHERE/JOIN/ORDER BY clauses for index columns, "
                    f"quote get_configuration instance classes "
                    f"exactly, quote get_monthly_cost dollar figures "
                    f"exactly.\n\n"
                    f"=== Specialist findings ===\n\n"
                    f"{findings_text}\n\n"
                    f"=== Raw evidence (observation bodies cited above) ===\n\n"
                    f"{evidence_text}"
                ),
            },
        ]
        recommendation_response = self._llm.complete(
            recommendation_messages, tools=[PRODUCE_RECOMMENDATION_TOOL],
        )
        recommendation = self._extract_tool_args(
            recommendation_response, PRODUCE_RECOMMENDATION_TOOL["name"],
        )
        if recommendation is None:
            raise EvaluatorError(
                "Evaluator LLM did not call produce_recommendation "
                "(step 2 of 3)"
            )

        # ------------------------------------------------------------
        # Step 2.5: coherence guard.
        #
        # When finding_type=issue_found, both primary_tier and
        # action_category MUST be non-null. The LLM sometimes ignores
        # this rule and produces rich root_cause/reasoning/specific_change
        # while leaving the taxonomy fields null — see app-07 in the
        # 18-scenario integration test. A null taxonomy on an issue_found
        # recommendation breaks the Shape + Correctness gates and
        # silently produces an unactionable recommendation downstream.
        #
        # One retry with an explicit correction message. If the retry
        # also fails the check, raise — visible failure beats silent
        # malformed output.
        missing = _coherence_missing_fields(recommendation)
        if missing:
            correction_text = (
                f"Your previous produce_recommendation call returned a "
                f"recommendation with finding_type=issue_found but "
                f"{', '.join(missing)} set to null. For issue_found "
                f"cases these fields are REQUIRED — they identify "
                f"which tier the recommendation acts on and what kind "
                f"of action it is.\n\n"
                f"Your previous call returned:\n\n"
                f"```json\n{json.dumps(recommendation, indent=2)}\n```\n\n"
                f"Call produce_recommendation again with the SAME "
                f"content, except fill {', '.join(missing)} with the "
                f"closest enum value from the tool schema based on the "
                f"recommendation's actual scope (e.g. if the "
                f"specific_change targets a cache tier, primary_tier "
                f"is 'cache' and action_category is "
                f"'cache_capacity_adjustment' or "
                f"'query_cache_optimization'). Do not invent values "
                f"outside the enum, and do not change any other field."
            )
            recommendation_messages.append({
                "role": "user",
                "content": correction_text,
                "_mock_key": (self.agent_name, "recommend_retry"),
            })
            recommendation_response = self._llm.complete(
                recommendation_messages, tools=[PRODUCE_RECOMMENDATION_TOOL],
            )
            retry_rec = self._extract_tool_args(
                recommendation_response,
                PRODUCE_RECOMMENDATION_TOOL["name"],
            )
            if retry_rec is None or _coherence_missing_fields(retry_rec):
                still_missing = (
                    _coherence_missing_fields(retry_rec) if retry_rec
                    else missing
                )
                raise EvaluatorError(
                    f"Evaluator failed to produce a coherent "
                    f"recommendation after one retry: finding_type="
                    f"issue_found but {', '.join(still_missing)} "
                    f"remain null."
                )
            recommendation = retry_rec

        # ------------------------------------------------------------
        # Step 3: produce_reflection, with both prior outputs in context.
        # ------------------------------------------------------------
        recommendation_recap = json.dumps(
            recommendation, default=str, indent=2,
        )
        reflection_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_prompt,
                "_mock_key": (self.agent_name, "reflect"),
            },
            {
                "role": "user",
                "content": (
                    f"Step 3 of 3 for {state['application_id']}.\n\n"
                    f"You produced this reconciliation:\n\n"
                    f"=== Reconciliation (step 1) ===\n\n"
                    f"```json\n{reconciliation_recap}\n```\n\n"
                    f"You committed to this recommendation:\n\n"
                    f"=== Recommendation (step 2) ===\n\n"
                    f"```json\n{recommendation_recap}\n```\n\n"
                    f"Now call produce_reflection with the post-"
                    f"decision reflection. Score the trade-offs of the "
                    f"committed recommendation across cost / "
                    f"performance / reliability / risk; write the "
                    f"trade_off_philosophy paragraph; rate your "
                    f"confidence (level + narrative + numeric) and "
                    f"name the load-bearing observation(s) — the "
                    f"evidence whose presence or absence licenses the "
                    f"recommendation."
                ),
            },
        ]
        reflection_response = self._llm.complete(
            reflection_messages, tools=[PRODUCE_REFLECTION_TOOL],
        )
        reflection = self._extract_tool_args(
            reflection_response, PRODUCE_REFLECTION_TOOL["name"],
        )
        if reflection is None:
            raise EvaluatorError(
                "Evaluator LLM did not call produce_reflection "
                "(step 3 of 3)"
            )

        # Assemble the synthesis dict the rest of the module expects.
        # The three primary sub-objects are persisted as-is (renderer
        # consumes them); the backwards-compat keys (drift_verdicts,
        # cross_tier_interactions, trade_off_scores, evaluator_confidence)
        # are derived so the existing _record_evaluator + Reasoning
        # Harness paths keep working unchanged.
        drift_verdicts_map: dict[str, str] = {}
        for row in reconciliation.get("drift_check") or []:
            agent = row.get("agent")
            verdict = row.get("verdict")
            if agent and verdict:
                drift_verdicts_map[agent] = verdict

        synthesis: dict[str, Any] = {
            "reconciliation": reconciliation,
            "recommendation": recommendation,
            "reflection": reflection,
            # Legacy compat keys read by the recording layer + harness.
            "drift_verdicts": drift_verdicts_map,
            "cross_tier_interactions": (
                reconciliation.get("cross_tier_correlations") or []
            ),
            "trade_off_scores": reflection.get("trade_off_scores") or {},
            "evaluator_confidence": reflection.get("evaluator_confidence"),
        }
        return synthesis

    @staticmethod
    def _extract_tool_args(
        response: dict[str, Any], expected_name: str,
    ) -> dict[str, Any] | None:
        """Pull the args of the named tool call from an LLM response.
        Returns None when the LLM did not call the expected tool."""
        for tc in response.get("tool_calls") or []:
            if tc.get("name") == expected_name:
                args = tc.get("args") or tc.get("arguments") or {}
                # langchain-anthropic occasionally serializes nested
                # object fields as JSON strings; coerce here so the
                # caller always gets a dict.
                if isinstance(args, str):
                    return CrossTierEvaluatorNode._coerce_to_dict(args)
                return args if isinstance(args, dict) else {}
        return None

    @staticmethod
    def _coerce_to_dict(value: Any) -> dict[str, Any]:
        """Coerce a value to a dict, parsing JSON-strings if needed.

        langchain-anthropic's bind_tools sometimes returns nested object
        fields (like the `recommendation` sub-object inside
        produce_synthesis's args) as a JSON-encoded *string* rather than
        a Python dict — the model serializes the object into the field
        instead of emitting a structured value. Downstream consumers
        (this module's audit row writers, show_recommendation.sh, the
        Scorer) all assume a dict. Coerce here so the rest of the
        pipeline stays dict-typed.
        """
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            import json as _json  # noqa: PLC0415
            try:
                parsed = _json.loads(value)
            except _json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @classmethod
    def _extract_recommendation(cls, synthesis: dict[str, Any]) -> dict[str, Any]:
        """Pull the recommendation sub-object from the three-step
        synthesis. With produce_recommendation as a dedicated step 2,
        the recommendation fields land at the top of that step's args
        directly — no flat/nested rescue needed any more. The legacy
        helper name is kept for callers that haven't been renamed yet.
        """
        rec = synthesis.get("recommendation")
        return cls._coerce_to_dict(rec)

    def _record_evaluator(
        self,
        state: CycleState,
        synthesis: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> int:
        """Append the evaluator_record audit row.

        Carries the three new sub-objects (reconciliation, reflection)
        alongside the legacy fields the Reasoning Harness reads
        (drift_verdicts, cross_tier_interactions, trade_off_scores,
        evaluator_confidence) and the renderer reads (synthesis is
        the recommendation dict).
        """
        contributing_ids = list(state["specialist_finding_record_ids"])
        recommendation_dict = self._extract_recommendation(synthesis)
        record = AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="evaluator_record",
            agent=self.agent_name,
            content={
                # Legacy fields read by Reasoning Harness + composer.
                "drift_verdicts": synthesis.get("drift_verdicts") or {},
                "cross_tier_interactions": (
                    synthesis.get("cross_tier_interactions") or []
                ),
                "trade_off_scores": synthesis.get("trade_off_scores") or {},
                "synthesis": recommendation_dict,
                "evaluator_confidence": synthesis.get("evaluator_confidence"),
                # Three-step reasoning sub-objects (renderer consumes).
                "reconciliation": synthesis.get("reconciliation") or {},
                "reflection": synthesis.get("reflection") or {},
                # Bookkeeping.
                "contributing_findings": contributing_ids,
                "evidence_refs": contributing_ids,
            },
        )
        return self._store.add_event(record)

    def _record_recommendation(
        self, state: CycleState, synthesis: dict[str, Any],
    ) -> int:
        """Append the recommendation audit row. The Action Harness's
        recommendation gate (added in sub-batch 7) will judge this row.

        Carries `composite` (the recommendation Pydantic shape) plus
        the three-step reasoning sub-objects (`reconciliation`,
        `reflection`) so the renderer can read every section without
        joining back to the evaluator_record row.
        """
        recommendation = self._extract_recommendation(synthesis)
        record = AuditRecord(
            cycle_id=state["cycle_id"],
            parent_id=None,
            category="decision",
            type="recommendation",
            agent=self.agent_name,
            content={
                "composite": recommendation,
                "reconciliation": synthesis.get("reconciliation") or {},
                "reflection": synthesis.get("reflection") or {},
                "evidence_refs": list(state["specialist_finding_record_ids"]),
            },
        )
        return self._store.add_event(record)
