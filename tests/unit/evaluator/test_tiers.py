"""Unit tests for src/evaluator/tiers.py (the back-compat facade).

The facade re-exports score_shape, score_correctness, score_floor,
score_mid, score_rich, NO_ACTION_FINDINGS, plus a stateless
score_all_tiers convenience wrapper.
"""

from __future__ import annotations

from src.evaluator.tiers import score_all_tiers


class TestScoreAllTiers:
    def test_all_pass_returns_true_when_every_layer_passes(self):
        pred = {
            "finding_type": "issue_found", "primary_tier": "compute",
            "action_category": "rightsizing", "specific_change": "x" * 30,
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        result = score_all_tiers(pred, rules)
        assert "shape" in result
        assert "correctness" in result
        assert "floor" in result  # back-compat
        assert "mid" in result
        assert "rich" in result
        assert result["all_pass"] is True

    def test_all_pass_false_when_correctness_fails(self):
        pred = {
            "finding_type": "no_issue_found",  # wrong
            "primary_tier": "compute",
            "action_category": "rightsizing", "specific_change": "x" * 30,
        }
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        result = score_all_tiers(pred, rules)
        assert result["all_pass"] is False
