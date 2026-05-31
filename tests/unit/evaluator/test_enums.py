"""Unit tests for src/evaluator/enums.py.

The enum universes are the single source of truth. Tests confirm:
  - Each frozenset contains the expected core values.
  - NO_ACTION_FINDINGS includes the three short-circuit values.
  - universe_for() resolves known fields and rejects unknown ones.
  - is_valid_value() correctly classifies members and non-members.
"""

from __future__ import annotations

import pytest

from src.evaluator.enums import (
    FINDING_TYPES,
    PRIMARY_TIERS,
    SECONDARY_TIERS,
    ACTION_CATEGORIES,
    NO_ACTION_FINDINGS,
    universe_for,
    is_valid_value,
)


class TestEnumUniverses:
    def test_finding_types_contains_core_values(self):
        assert "issue_found" in FINDING_TYPES
        assert "no_issue_found" in FINDING_TYPES
        assert "diagnostic_deferral" in FINDING_TYPES
        assert "insufficient_data" in FINDING_TYPES  # forward-compatible

    def test_primary_tiers_contains_cloud_tiers_plus_sentinels(self):
        for tier in ("compute", "database", "cache", "network"):
            assert tier in PRIMARY_TIERS, f"missing core tier: {tier}"
        assert "deferred" in PRIMARY_TIERS  # diagnostic_deferral sentinel
        assert None in PRIMARY_TIERS  # null is valid (no_issue_found case)

    def test_secondary_tiers_mirrors_primary_tiers(self):
        # Today they're the same set. If they ever diverge, this test
        # forces the divergence to be intentional.
        assert SECONDARY_TIERS == PRIMARY_TIERS

    def test_action_categories_contains_cache_specific(self):
        assert "cache_capacity_adjustment" in ACTION_CATEGORIES
        # And the common ones:
        for cat in ("rightsizing", "query_cache_optimization", None):
            assert cat in ACTION_CATEGORIES, f"missing action_category: {cat}"

    def test_no_action_findings_is_the_short_circuit_set(self):
        assert NO_ACTION_FINDINGS == frozenset({
            "no_issue_found",
            "diagnostic_deferral",
            "insufficient_data",
        })

    def test_no_action_findings_is_subset_of_finding_types(self):
        assert NO_ACTION_FINDINGS <= FINDING_TYPES


class TestUniverseFor:
    def test_returns_correct_frozenset_for_each_field(self):
        assert universe_for("finding_type") is FINDING_TYPES
        assert universe_for("primary_tier") is PRIMARY_TIERS
        assert universe_for("secondary_tier") is SECONDARY_TIERS
        assert universe_for("action_category") is ACTION_CATEGORIES

    def test_raises_on_unknown_field(self):
        with pytest.raises(ValueError) as exc_info:
            universe_for("not_a_real_field")
        assert "not_a_real_field" in str(exc_info.value)


class TestIsValidValue:
    def test_returns_true_for_valid_values(self):
        assert is_valid_value("finding_type", "issue_found")
        assert is_valid_value("primary_tier", "compute")
        assert is_valid_value("primary_tier", None)  # null is valid
        assert is_valid_value("action_category", "cache_capacity_adjustment")

    def test_returns_false_for_invalid_values(self):
        assert not is_valid_value("finding_type", "not_a_finding")
        assert not is_valid_value("primary_tier", "elephant")
        assert not is_valid_value("action_category", "magic_fix")

    def test_raises_on_unknown_field_name(self):
        with pytest.raises(ValueError):
            is_valid_value("not_a_field", "anything")
