"""Pydantic schema for the composite recommendation artifact.

A composite contains:
  - Top-level prediction fields (read by the evaluator).
  - `scoring_metadata`: the rubric for scoring this scenario (formerly
    eval-set/scoring_rules/NN/rules.json).
  - Optional `trace`: audit trail mirroring sample_runs/traces/*.json.
  - Optional `report_content`: structured content the renderer uses to
    produce a markdown report.
  - Optional `_provenance`: honest framing (what is real vs illustrative)
    plus authorship metadata.

For eval-set composites ("thin"), the optional sections are usually
absent. For live-agent or sample_runs composites ("full"), all sections
populate.

Schema version is 1.0. Bump explicitly on breaking changes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0"


# ============================================================
# Inner blocks shared with eval-set/expectations/NN.json today
# ============================================================
class Conclusion(BaseModel):
    """The conclusion block mirrors top-level enum fields plus a headline.

    Validated for consistency in the migration script: top-level
    finding_type/primary_tier/etc. must equal conclusion's fields.
    """
    finding_type: str
    primary_tier: str | None = None
    secondary_tier: str | None = None
    action_category: str | None = None
    headline: str | None = None

    model_config = ConfigDict(extra="allow")


class Evidence(BaseModel):
    telemetry_observations: list[str] = Field(default_factory=list)
    infrastructure_context: list[str] = Field(default_factory=list)
    correlation_observations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class ProjectedState(BaseModel):
    cpu_p95_pct_estimate: str | None = None
    memory_p95_pct_estimate: str | None = None
    latency_p95_ms_estimate: str | None = None
    sla_availability_preserved: bool | None = None
    notes: str | None = None

    # Some scenarios use additional fields beyond the canonical four.
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
# Scoring metadata (formerly eval-set/scoring_rules/NN/rules.json)
# ============================================================
class ShortCircuit(BaseModel):
    """When present and `applies=true`, Mid and Rich are bypassed."""
    applies: bool
    reason: str | None = None


class ScoringMetadata(BaseModel):
    """Per-scenario rules consumed by the evaluator.

    Replaces eval-set/scoring_rules/NN/rules.json. Lives inside the
    composite so the gold answer and its scoring rubric are one artifact.
    """
    description: str
    finding_type_allowed: list[str | None]
    primary_tier_allowed: list[str | None]
    secondary_tier_allowed: list[str | None]
    action_category_allowed: list[str | None]

    # Rationales (documentation only; not consumed by the scorer)
    finding_type_rationale: str | None = None
    primary_tier_rationale: str | None = None
    secondary_tier_rationale: str | None = None
    action_category_rationale: str | None = None

    # Rich-layer config
    must_cite_fixture: str | None = None

    # Short-circuit marker for no-action scenarios
    short_circuit: ShortCircuit | None = None

    model_config = ConfigDict(extra="forbid")


# ============================================================
# Optional: audit trail (populated for full composites)
# ============================================================
class TraceSection(BaseModel):
    """Audit trail. Mirrors sample_runs/traces/scenario_NN_trace.json.

    All fields optional so that thin composites can omit this section.
    When present, fields are populated as a complete audit trail of how
    a recommendation was produced.
    """
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
    """Structured content the renderer uses to produce report.md.

    All fields optional so renderers can use a thin composite to produce
    a basic report (built from top-level prediction fields), or use a
    full composite for richer narrative.

    Field groups:
      - title block: scenario_name, analysis_date, status_line
      - banner blockquote: report_banner (three named paragraphs)
      - final-recommendation table: final_recommendation_rows
      - narrative sections: summary, cross_tier_analysis,
        evaluator_confidence, how_to_verify, replayability
      - structured tables: specialist_findings_summary,
        trade_off_scores_table, evidence_anchors, handoff
    """
    # Title block
    scenario_name: str | None = None
    analysis_date: str | None = None
    status_line: str | None = None

    # Banner blockquote — three paragraphs of prose explaining what is
    # real, illustrative, and verifiable in this specific report. These
    # are scenario-specific and verbatim; structural cousins of the
    # composite-level _provenance lists, but written for a report reader
    # rather than a JSON consumer.
    report_banner: dict[str, str] | None = None

    # Final-recommendation table rows. Each entry is {field, value}.
    final_recommendation_rows: list[dict[str, str]] | None = None

    # Narrative sections (free prose; markdown paragraphs).
    headline: str | None = None
    summary: str | None = None
    cross_tier_analysis: str | None = None
    evaluator_confidence: str | None = None
    how_to_verify: str | None = None
    replayability: str | None = None

    # Structured tables — the renderer turns these into markdown tables.
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
    """Honest framing: what is real, what is illustrative.

    Hand-crafted golds and sample_runs use this to document that
    timestamps, IDs, and durations are placeholders. Live-agent
    composites use this to document the run that produced them.
    """
    authored_at: str | None = None
    dataset_version: str | None = None
    author: str | None = None
    note: str | None = None
    what_is_real: list[str] | None = None
    what_is_illustrative: list[str] | None = None
    what_is_verifiable_today: list[str] | None = None

    model_config = ConfigDict(extra="allow")


# ============================================================
# Top-level composite
# ============================================================
class Composite(BaseModel):
    """Composite recommendation artifact.

    Top-level prediction fields are what the evaluator reads. The
    scoring_metadata block is the rubric. The optional trace +
    report_content sections support rendering and audit replay.
    """
    schema_version: str = SCHEMA_VERSION
    scenario_id: str

    # Prediction fields (the evaluator reads these directly)
    finding_type: str
    primary_tier: str | None = None
    secondary_tier: str | None = None
    action_category: str | None = None
    specific_change: str
    # conclusion is None for no_issue_found scenarios where there is no
    # action to summarize (e.g. scenario 06). For all other scenarios it
    # mirrors the four top-level enum fields plus a headline.
    conclusion: Conclusion | None = None
    evidence: Evidence
    reasoning: str
    projected_state: ProjectedState | None = None
    cost_impact: CostImpact | None = None
    risk_assessment: RiskAssessment | None = None

    # Scoring rubric
    scoring_metadata: ScoringMetadata

    # Optional sections for the renderer / replay tools
    trace: TraceSection | None = None
    report_content: ReportContent | None = None

    # Provenance carried as _provenance on disk (leading underscore
    # signals metadata-not-payload). On the model it's named provenance_.
    provenance_: Provenance | None = Field(default=None, alias="_provenance")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # --------------------------------------------------------
    # Convenience accessors used by evaluator code paths
    # --------------------------------------------------------
    def to_rules_dict(self) -> dict[str, Any]:
        """Return the scoring_metadata as a flat dict matching the legacy
        rules.json shape. Lets evaluator code that consumed rules.json
        keep its existing key access patterns.
        """
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
        the legacy expectations/NN.json shape. Lets evaluator code that
        consumed expectations keep its existing access patterns.

        Uses `exclude_unset=True` on sub-models so explicit nulls in the
        source (e.g. conclusion.secondary_tier = null on scenario 18)
        round-trip exactly without inventing absent fields.
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
        # Emit optional sections when present, OR as explicit null when
        # the legacy file set them to null (e.g. scenarios 06/15/17).
        set_fields = self.model_fields_set
        for key in ("projected_state", "cost_impact", "risk_assessment"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value.model_dump(exclude_unset=True)
            elif key in set_fields:
                out[key] = None
        return out
