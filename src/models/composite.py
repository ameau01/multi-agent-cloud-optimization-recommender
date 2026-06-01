"""Pydantic schemas for the recommendation + composite artifacts.

Two related models live here, with `Composite` inheriting from
`Recommendation`:

  Recommendation     — what the agent orchestration produces. Lenient
                       (extra='allow', most fields Optional). Only two
                       fields are mandatory: `scenario_id` (to identify
                       the scenario) and `specific_change` (the rich-text
                       answer the LLM judge compares against gold). The
                       agent has structural freedom inside every other
                       field; sub-objects are typed but each internal
                       field is Optional.

  Composite          — the strict gold-quality artifact. IS-A Recommendation
                       with three additions:
                         (a) tightens finding_type, evidence, reasoning
                             to required (gold MUST populate them)
                         (b) carries the scoring rubric (ScoringMetadata)
                         (c) carries optional trace + report_content +
                             provenance sections for full-composite runs.

This split lets one set of consumers (the evaluator and the renderer)
operate on either shape: the agent's lenient output flows through the
same code paths as a strict gold. Composite IS a Recommendation via
Liskov substitution.

Audit-trail sub-shapes inside TraceSection stay as `dict[str, Any]`;
their typing is deferred until each harness/agent emitter exists.

Schema version is 1.0. Bump explicitly on breaking changes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0"


# ============================================================
# Inner sub-objects (typed but each internal field Optional)
# ============================================================
class Conclusion(BaseModel):
    """The conclusion block. All fields Optional so a partial agent
    output validates; gold answers populate them."""
    finding_type: str | None = None
    primary_tier: str | None = None
    secondary_tier: str | None = None
    action_category: str | None = None
    headline: str | None = None

    model_config = ConfigDict(extra="allow")


class Evidence(BaseModel):
    """Evidence bullets. All three lists Optional and default None so an
    agent can emit any subset; gold answers populate all three."""
    telemetry_observations: list[str] | None = None
    infrastructure_context: list[str] | None = None
    correlation_observations: list[str] | None = None

    model_config = ConfigDict(extra="allow")


class ProjectedState(BaseModel):
    cpu_p95_pct_estimate: str | None = None
    memory_p95_pct_estimate: str | None = None
    latency_p95_ms_estimate: str | None = None
    sla_availability_preserved: bool | None = None
    notes: str | None = None
    model_config = ConfigDict(extra="allow")


class CostImpact(BaseModel):
    current_monthly_usd: float | None = None
    projected_monthly_usd: float | None = None
    savings_monthly_usd: float | None = None
    savings_pct: float | None = None
    notes: str | None = None
    model_config = ConfigDict(extra="allow")


class RiskAssessment(BaseModel):
    primary_risk: str | None = None
    mitigation: str | None = None
    rollback: str | None = None
    notes: str | None = None
    model_config = ConfigDict(extra="allow")


# ============================================================
# Scoring metadata (gold-only; rubric for the evaluator)
# ============================================================
class ShortCircuit(BaseModel):
    """When present and `applies=true`, Mid and Rich are bypassed."""
    applies: bool
    reason: str | None = None


class ScoringMetadata(BaseModel):
    """Per-scenario rules consumed by the evaluator. Strict shape — the
    rubric is hand-authored and never partial."""
    description: str
    finding_type_allowed: list[str | None]
    primary_tier_allowed: list[str | None]
    secondary_tier_allowed: list[str | None]
    action_category_allowed: list[str | None]

    finding_type_rationale: str | None = None
    primary_tier_rationale: str | None = None
    secondary_tier_rationale: str | None = None
    action_category_rationale: str | None = None

    must_cite_fixture: str | None = None
    short_circuit: ShortCircuit | None = None

    model_config = ConfigDict(extra="forbid")


# ============================================================
# Optional: audit trail (populated for full composites)
# ============================================================
class TraceSection(BaseModel):
    """Audit trail. Sub-fields stay as dict[str, Any] until each emitter
    exists — typing them now would be premature commitment to shapes the
    harnesses and agents have not yet produced. Next phase tightens
    these per-emitter."""
    review: dict[str, Any] | None = None
    input_harness_validation: dict[str, Any] | None = None
    system_mapper: dict[str, Any] | None = None
    supervisor_decision: dict[str, Any] | None = None
    specialist_findings: list[dict[str, Any]] | None = None
    evaluator_records: dict[str, Any] | None = None
    action_harness_gate: dict[str, Any] | None = None
    review_packet: dict[str, Any] | None = None
    hitl_decision: dict[str, Any] | None = None

    model_config = ConfigDict(extra="allow")


# ============================================================
# Optional: structured report content (populated for full composites)
# ============================================================
class ReportContent(BaseModel):
    """Structured content the renderer uses to produce report.md."""
    scenario_name: str | None = None
    analysis_date: str | None = None
    status_line: str | None = None
    report_banner: dict[str, str] | None = None
    final_recommendation_rows: list[dict[str, str]] | None = None
    headline: str | None = None
    summary: str | None = None
    cross_tier_analysis: str | None = None
    evaluator_confidence: str | None = None
    how_to_verify: str | None = None
    replayability: str | None = None
    specialist_findings_summary: list[dict[str, Any]] | None = None
    trade_off_scores: dict[str, Any] | None = None
    trade_off_scores_table: list[dict[str, str]] | None = None
    evidence_anchors: list[dict[str, Any]] | None = None
    handoff: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


# ============================================================
# Optional: provenance (honest framing for hand-crafted composites)
# ============================================================
class Provenance(BaseModel):
    """Honest framing: what is real vs illustrative."""
    authored_at: str | None = None
    dataset_version: str | None = None
    author: str | None = None
    note: str | None = None
    what_is_real: list[str] | None = None
    what_is_illustrative: list[str] | None = None
    what_is_verifiable_today: list[str] | None = None
    model_config = ConfigDict(extra="allow")


# ============================================================
# Recommendation — the agent's output contract
# ============================================================
class Recommendation(BaseModel):
    """Lenient agent output. The shared contract between agent
    orchestration (producer) and the evaluator + renderer (consumers).

    Only scenario_id and specific_change are mandatory. specific_change
    is required because the LLM judge compares it against the gold's
    specific_change for the richness layer; no other field is required
    for the evaluator's deterministic layers to run.

    All other top-level fields and every sub-object are Optional. The
    agent may emit any subset; the evaluator scores what is present and
    marks unscored layers as 'skipped' or 'failed'.

    extra='allow' lets the agent attach debugging or trace fields
    without breaking validation. The renderer ignores unknown keys.
    """
    scenario_id: str                    # MANDATORY
    specific_change: str                # MANDATORY (richness judge input)

    # Optional structural fields:
    finding_type: str | None = None
    primary_tier: str | None = None
    secondary_tier: str | None = None
    action_category: str | None = None

    # Optional sub-objects (typed; each internal field Optional):
    conclusion: Conclusion | None = None
    evidence: Evidence | None = None
    reasoning: str | None = None
    projected_state: ProjectedState | None = None
    cost_impact: CostImpact | None = None
    risk_assessment: RiskAssessment | None = None

    model_config = ConfigDict(extra="allow")


# ============================================================
# Composite — the strict gold-quality artifact
# ============================================================
class Composite(Recommendation):
    """Composite recommendation artifact. IS-A Recommendation with
    three additions: tighter required-field set (gold semantics), the
    scoring rubric, and optional trace + report_content + provenance
    sections.

    The 18 gold answers are Composites. Sample_runs runs that record
    their own audit + report content are also Composites. A live
    agent's output is a Recommendation; it becomes a Composite only
    when paired with its scoring rubric and run metadata.
    """
    schema_version: str = SCHEMA_VERSION

    # Tighten Recommendation's lenient declarations. Pydantic v2 lets
    # subclasses shadow field declarations to make them stricter.
    # Note: `conclusion` stays Optional (scenario 06's gold has
    # conclusion=null because no_issue_found has nothing to summarize).
    finding_type: str                   # required (gold must have one)
    evidence: Evidence                  # required (gold has bullets)
    reasoning: str                      # required (gold has narrative)

    # Gold-only sections:
    scoring_metadata: ScoringMetadata
    trace: TraceSection | None = None
    report_content: ReportContent | None = None

    # Provenance carried as _provenance on disk (leading underscore signals
    # metadata-not-payload). On the model it's named provenance_.
    provenance_: Provenance | None = Field(default=None, alias="_provenance")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # --------------------------------------------------------
    # Convenience accessors used by evaluator code paths
    # --------------------------------------------------------
    def to_rules_dict(self) -> dict[str, Any]:
        """Return the scoring_metadata as a flat dict matching the legacy
        rules.json shape."""
        sm = self.scoring_metadata
        out: dict[str, Any] = {
            "description": sm.description,
            "finding_type_allowed": sm.finding_type_allowed,
            "primary_tier_allowed": sm.primary_tier_allowed,
            "secondary_tier_allowed": sm.secondary_tier_allowed,
            "action_category_allowed": sm.action_category_allowed,
        }
        if sm.finding_type_rationale is not None:
            out["finding_type_rationale"] = sm.finding_type_rationale
        if sm.primary_tier_rationale is not None:
            out["primary_tier_rationale"] = sm.primary_tier_rationale
        if sm.secondary_tier_rationale is not None:
            out["secondary_tier_rationale"] = sm.secondary_tier_rationale
        if sm.action_category_rationale is not None:
            out["action_category_rationale"] = sm.action_category_rationale
        if sm.must_cite_fixture is not None:
            out["must_cite_fixture"] = sm.must_cite_fixture
        if sm.short_circuit is not None:
            out["short_circuit"] = sm.short_circuit.model_dump(exclude_none=True)
        return out

    def to_gold_dict(self) -> dict[str, Any]:
        """Return the top-level prediction fields as a flat dict matching
        the legacy expectations/NN.json shape.

        Uses `exclude_unset=True` on sub-models so explicit nulls in the
        source round-trip exactly without inventing absent fields.
        """
        out: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "finding_type": self.finding_type,
            "specific_change": self.specific_change,
            "primary_tier": self.primary_tier,
            "secondary_tier": self.secondary_tier,
            "action_category": self.action_category,
            "conclusion": (
                self.conclusion.model_dump(exclude_unset=True)
                if self.conclusion is not None
                else None
            ),
            "evidence": self.evidence.model_dump(exclude_unset=True),
            "reasoning": self.reasoning,
        }
        set_fields = self.model_fields_set
        for key in ("projected_state", "cost_impact", "risk_assessment"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value.model_dump(exclude_unset=True)
            elif key in set_fields:
                out[key] = None
        return out
