"""Unit tests for src/evaluator/richness_measure.py.

Tests score_rich edge cases under the judge-gate + structural-check design
plus the _extract_fixture_identifiers helper.

Rich behavior (per docs/eval-set.md):
  - short_circuit: when finding_type is in NO_ACTION_FINDINGS, Rich
    passes with a short_circuit marker (no judge needed).
  - graceful skip: when judge_result is None, Rich returns a 'skipped'
    marker.
  - judge gate: when judge_result is provided, the gate first checks
    score >= RICH_THRESHOLD (60). If the gate fails, return early.
  - structural checks: when the gate passes, the four existing
    deterministic checks run (fixture_citation, cost_impact_quantified,
    projected_state_quantified, evidence_structured).
"""

from __future__ import annotations

from src.evaluator.richness_measure import (
    score_rich, _extract_fixture_identifiers, RICH_THRESHOLD,
)
from src.evaluator.enums import NO_ACTION_FINDINGS


# Shared helper: a judge_result that clears the gate
def _passing_judge(score: int = 85) -> dict:
    return {"score": score, "rationale": "rich enough"}


# ============================================================
# Short-circuit behavior
# ============================================================
class TestShortCircuit:
    def test_short_circuits_on_no_action_findings(self):
        for ft in NO_ACTION_FINDINGS:
            pred = {"finding_type": ft}
            result = score_rich(pred, {}, None)
            assert result.passed
            assert any(c.name == "short_circuit" for c in result.checks), ft


# ============================================================
# Graceful skip (no judge available)
# ============================================================
class TestGracefulSkip:
    def test_returns_skipped_when_no_judge_result(self):
        pred = {"finding_type": "issue_found",
                "specific_change": "do x"}
        result = score_rich(pred, {}, None, judge_result=None)
        assert result.passed  # marker, not a real pass
        assert len(result.checks) == 1
        assert result.checks[0].name == "skipped"


# ============================================================
# Judge gate (score < 60 short-circuits the structural checks)
# ============================================================
class TestJudgeGate:
    def test_fails_immediately_when_score_below_threshold(self):
        """When the gate fails, the structural checks should NOT run.
        Result has exactly one check (the judge_richness gate)."""
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "specific_change": "do x",
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        result = score_rich(pred, {}, None,
                            judge_result={"score": RICH_THRESHOLD - 1,
                                          "rationale": "thin"})
        assert not result.passed
        assert len(result.checks) == 1
        assert result.checks[0].name == "judge_richness"
        assert not result.checks[0].passed

    def test_gate_passes_at_threshold(self):
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "specific_change": "do x",
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        result = score_rich(pred, {}, None,
                            judge_result={"score": RICH_THRESHOLD,
                                          "rationale": "at boundary"})
        assert result.passed
        # Multiple checks ran (gate + 3 structural)
        assert len(result.checks) > 1


# ============================================================
# Structural checks (judge gate passing)
# ============================================================
class TestStructuralChecks:
    def test_passes_when_judge_passes_and_structure_ok(self):
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "evidence": {
                "telemetry_observations": ["a", "b"],
                "infrastructure_context": ["c"],
                "correlation_observations": [],
            },
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        assert score_rich(pred, {}, None, judge_result=_passing_judge()).passed

    def test_evidence_structured_fails_with_fewer_than_3_bullets(self):
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "evidence": {
                "telemetry_observations": ["one"],
                "infrastructure_context": [],
                "correlation_observations": [],
            },
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        result = score_rich(pred, {}, None, judge_result=_passing_judge())
        assert not result.passed
        assert any(
            c.name == "evidence_structured" and not c.passed
            for c in result.checks
        )

    def test_cost_impact_quantified_passes_with_non_zero_number(self):
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "cost_impact": {"savings_monthly_usd": 1500},
            "projected_state": {"latency_ms": 200},
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
        }
        assert score_rich(pred, {}, None, judge_result=_passing_judge()).passed

    def test_cost_impact_quantified_fails_when_all_zero(self):
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "cost_impact": {"savings_monthly_usd": 0, "notes": "tbd"},
            "projected_state": {"latency_ms": 200},
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
        }
        result = score_rich(pred, {}, None, judge_result=_passing_judge())
        assert not result.passed
        assert any(
            c.name == "cost_impact_quantified" and not c.passed
            for c in result.checks
        )

    def test_fixture_citation_skips_when_metadata_is_none(self):
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "specific_change": "do the thing",
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
        }
        rules = {"must_cite_fixture": "top_queries"}
        result = score_rich(pred, rules,
                            scenario_metadata=None,
                            judge_result=_passing_judge())
        check_names = {c.name for c in result.checks}
        assert "fixture_citation" not in check_names


# ============================================================
# Fixture-identifier extraction (helper)
# ============================================================
class TestExtractFixtureIdentifiers:
    def test_top_queries_with_name_key(self):
        items = [{"name": "q1", "p95": 100}, {"name": "q2", "p95": 200}]
        assert _extract_fixture_identifiers("top_queries", items) == ["q1", "q2"]

    def test_top_queries_with_query_text_returns_empty(self):
        """Documented gap: query_text shape is not recognized."""
        items = [{"query_text": "SELECT * FROM users", "count": 10}]
        assert _extract_fixture_identifiers("top_queries", items) == []

    def test_top_cache_keys_with_pattern_key(self):
        items = [{"pattern": "user:*", "hits": 100}]
        assert _extract_fixture_identifiers("top_cache_keys", items) == ["user:*"]

    def test_per_instance_breakdown_with_instance_id(self):
        items = [{"instance_id": "i-abc", "cpu": 50}]
        assert _extract_fixture_identifiers("per_instance_breakdown", items) == ["i-abc"]
