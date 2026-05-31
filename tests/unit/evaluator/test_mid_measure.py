"""Unit tests for src/evaluator/mid_measure.py.

Tests score_mid edge cases plus the shared prediction_text helper that
score_mid (and score_rich) consume. No real files.
"""

from __future__ import annotations

from src.evaluator.mid_measure import score_mid
from src.evaluator.scoring_helpers import prediction_text
from src.evaluator.enums import NO_ACTION_FINDINGS


class TestScoreMid:
    def test_short_circuits_on_no_issue_found(self):
        pred = {"finding_type": "no_issue_found",
                "specific_change": "everything healthy"}
        result = score_mid(pred, {})
        assert result.passed
        assert any(c.name == "short_circuit" for c in result.checks)

    def test_short_circuits_on_diagnostic_deferral(self):
        pred = {"finding_type": "diagnostic_deferral",
                "specific_change": "need more data"}
        result = score_mid(pred, {})
        assert result.passed
        assert any(c.name == "short_circuit" for c in result.checks)

    def test_short_circuits_on_insufficient_data(self):
        """Forward-compatible: insufficient_data is in NO_ACTION_FINDINGS
        even though no current gold uses it."""
        pred = {"finding_type": "insufficient_data",
                "specific_change": "specialist had no signal"}
        result = score_mid(pred, {})
        assert result.passed
        assert any(c.name == "short_circuit" for c in result.checks)

    def test_keyword_group_passes_when_min_match_met(self):
        pred = {
            "finding_type": "issue_found",
            "specific_change": "downsize the compute instances",
            "reasoning": "compute is over-provisioned",
        }
        rules = {
            "action_keyword_groups": [
                ["downsize", "rightsize"],
                ["compute", "ec2"],
            ],
            "action_keyword_min_match": 2,
        }
        assert score_mid(pred, rules).passed

    def test_keyword_group_fails_when_under_threshold(self):
        pred = {
            "finding_type": "issue_found",
            "specific_change": "do something",
            "reasoning": "the system needs improvement",
        }
        rules = {
            "action_keyword_groups": [
                ["downsize", "rightsize"],
                ["compute", "ec2"],
            ],
            "action_keyword_min_match": 2,
        }
        result = score_mid(pred, rules)
        assert not result.passed
        assert any(c.name == "action_keywords" and not c.passed for c in result.checks)

    def test_multi_tier_evidence_passes_when_all_tiers_named(self):
        pred = {
            "finding_type": "issue_found",
            "specific_change": "optimize the database, address compute saturation",
        }
        rules = {
            "multi_tier_evidence": {
                "must_cite_tiers": ["database", "compute"],
                "min_tiers": 2,
            },
        }
        assert score_mid(pred, rules).passed

    def test_multi_tier_evidence_fails_when_only_one_named(self):
        pred = {
            "finding_type": "issue_found",
            "specific_change": "optimize the database",
        }
        rules = {
            "multi_tier_evidence": {
                "must_cite_tiers": ["database", "compute"],
                "min_tiers": 2,
            },
        }
        result = score_mid(pred, rules)
        assert not result.passed


class TestPredictionText:
    """The shared prose helper used by score_mid and score_rich.
    Lives in scoring_helpers.py; tested here because score_mid is its
    main caller."""

    def test_concatenates_specific_change_and_reasoning(self):
        pred = {"specific_change": "Hello", "reasoning": "World"}
        text = prediction_text(pred)
        assert "hello" in text and "world" in text  # lowercased

    def test_includes_evidence_bullets(self):
        pred = {
            "evidence": {
                "telemetry_observations": ["alpha"],
                "infrastructure_context": ["beta"],
                "correlation_observations": ["gamma"],
            },
        }
        text = prediction_text(pred)
        assert "alpha" in text
        assert "beta" in text
        assert "gamma" in text

    def test_handles_missing_evidence_gracefully(self):
        pred = {"specific_change": "ok"}
        text = prediction_text(pred)
        assert "ok" in text
