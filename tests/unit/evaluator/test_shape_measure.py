"""Unit tests for src/evaluator/shape_measure.py.

Tests score_shape with crafted inputs. No real files, no subprocess.
"""

from __future__ import annotations

from src.evaluator.shape_measure import score_shape


class TestScoreShape:
    def test_passes_on_minimal_valid_prediction(self):
        pred = {
            "finding_type": "issue_found",
            "primary_tier": "compute",
            "action_category": "rightsizing",
            "specific_change": "x" * 20,  # exactly the length floor
        }
        assert score_shape(pred).passed

    def test_fails_when_finding_type_missing(self):
        pred = {
            "primary_tier": "compute",
            "action_category": "rightsizing",
            "specific_change": "x" * 30,
        }
        result = score_shape(pred)
        assert not result.passed
        assert any(
            c.name == "field_present:finding_type" and not c.passed
            for c in result.checks
        )

    def test_fails_when_specific_change_too_short(self):
        pred = {
            "finding_type": "issue_found",
            "primary_tier": "compute",
            "action_category": "rightsizing",
            "specific_change": "fix it",  # 6 chars
        }
        result = score_shape(pred)
        assert not result.passed
        assert any(
            c.name == "specific_change_present" and not c.passed
            for c in result.checks
        )

    def test_fails_when_specific_change_is_not_string(self):
        pred = {
            "finding_type": "issue_found",
            "primary_tier": "compute",
            "action_category": "rightsizing",
            "specific_change": ["not", "a", "string"],
        }
        result = score_shape(pred)
        assert not result.passed
        assert any(
            c.name == "specific_change_present" and not c.passed
            for c in result.checks
        )

    def test_fails_when_specific_change_is_none(self):
        pred = {
            "finding_type": "issue_found",
            "primary_tier": "compute",
            "action_category": "rightsizing",
            "specific_change": None,
        }
        result = score_shape(pred)
        assert not result.passed

    def test_specific_change_with_leading_trailing_whitespace_uses_strip(self):
        pred = {
            "finding_type": "issue_found",
            "primary_tier": "compute",
            "action_category": "rightsizing",
            "specific_change": "   " + "x" * 30 + "   ",
        }
        assert score_shape(pred).passed
