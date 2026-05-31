"""Unit tests for src/evaluator/correctness_measure.py.

Tests score_correctness and score_floor (back-compat alias) with crafted
inputs. No real files.
"""

from __future__ import annotations

from src.evaluator.correctness_measure import score_correctness, score_floor


class TestScoreCorrectness:
    def test_passes_when_all_three_match_allowed(self):
        pred = {"finding_type": "issue_found", "primary_tier": "compute",
                "action_category": "rightsizing"}
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        assert score_correctness(pred, rules).passed

    def test_fails_when_finding_type_wrong(self):
        pred = {"finding_type": "no_issue_found", "primary_tier": "compute",
                "action_category": "rightsizing"}
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        result = score_correctness(pred, rules)
        assert not result.passed
        assert any(c.name == "finding_type" and not c.passed for c in result.checks)

    def test_fails_when_primary_tier_wrong(self):
        pred = {"finding_type": "issue_found", "primary_tier": "database",
                "action_category": "rightsizing"}
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        result = score_correctness(pred, rules)
        assert not result.passed

    def test_passes_when_value_in_multi_value_allowed_list(self):
        # Used by deferral scenarios' secondary_tier_allowed.
        pred = {"finding_type": "issue_found", "primary_tier": "compute",
                "action_category": "rightsizing"}
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute", "database"],  # broad
            "action_category_allowed": ["rightsizing"],
        }
        assert score_correctness(pred, rules).passed

    def test_no_checks_when_rules_omit_allowed_lists(self):
        pred = {"finding_type": "anything"}
        result = score_correctness(pred, {})
        assert result.passed
        assert result.checks == []


class TestScoreFloor:
    """score_floor is the back-compat alias = Shape + Correctness merged."""

    def test_floor_passes_when_both_shape_and_correctness_pass(self):
        pred = {
            "finding_type": "issue_found", "primary_tier": "compute",
            "action_category": "rightsizing", "specific_change": "x" * 30,
        }
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        result = score_floor(pred, rules)
        assert result.passed
        assert result.tier == "floor"

    def test_floor_fails_when_shape_fails(self):
        pred = {  # missing specific_change
            "finding_type": "issue_found", "primary_tier": "compute",
            "action_category": "rightsizing",
        }
        rules = {
            "finding_type_allowed": ["issue_found"],
            "primary_tier_allowed": ["compute"],
            "action_category_allowed": ["rightsizing"],
        }
        assert not score_floor(pred, rules).passed

    def test_floor_fails_when_correctness_fails(self):
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
        assert not score_floor(pred, rules).passed
