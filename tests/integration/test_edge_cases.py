"""Integration test: degraded recommendations fail the right layer.

Loads four mock predictions for scenario 08 from
tests/integration/fixtures/mock_predictions/:
  - scenario_08_good.json            (byte-identical to gold; passes all layers)
  - scenario_08_bad_correctness.json (wrong primary_tier; fails Correctness)
  - scenario_08_bad_mid.json         (correct enums, generic prose; fails Mid)
  - scenario_08_bad_rich.json        (correct enums + keywords, no quantification; fails Rich)

The four mocks are crafted to fail exactly one layer each (where possible),
so the test proves the evaluator's discrimination logic catches each class
of mistake. Mocks are version-controlled JSON files rather than in-memory
mutations so they can be inspected and shared with the demo script.

Run:
    pytest tests/integration/test_edge_cases.py -v
"""

from __future__ import annotations

import pytest

from src.evaluator.tiers import (
    score_shape,
    score_correctness,
    score_mid,
    score_rich,
)


# ============================================================
# The good mock passes every layer
# ============================================================
def test_good_mock_passes_all_layers(
    mock_predictions, all_evaluator_expectations, scenario_08_metadata
):
    pred = mock_predictions["good"]
    rules = all_evaluator_expectations["08"]
    assert score_shape(pred, rules).passed
    assert score_correctness(pred, rules).passed
    assert score_mid(pred, rules).passed
    assert score_rich(pred, rules, scenario_08_metadata).passed


# ============================================================
# Bad-correctness mock fails Correctness on the expected fields
# ============================================================
class TestBadCorrectness:
    """The bad_correctness mock has wrong primary_tier (compute instead of
    database) AND wrong action_category. Correctness fails on both fields.
    Mid + Rich are NOT run in production scoring (gate rule), but in unit
    isolation we can still call them; what matters is Correctness fails."""

    def test_correctness_fails(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_correctness"]
        rules = all_evaluator_expectations["08"]
        result = score_correctness(pred, rules)
        assert not result.passed

    def test_correctness_fails_primary_tier(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_correctness"]
        rules = all_evaluator_expectations["08"]
        result = score_correctness(pred, rules)
        assert any(
            c.name == "primary_tier" and not c.passed for c in result.checks
        )

    def test_correctness_fails_action_category(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_correctness"]
        rules = all_evaluator_expectations["08"]
        result = score_correctness(pred, rules)
        assert any(
            c.name == "action_category" and not c.passed for c in result.checks
        )

    def test_shape_still_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        """A wrong-answer recommendation is still well-formed JSON."""
        pred = mock_predictions["bad_correctness"]
        rules = all_evaluator_expectations["08"]
        assert score_shape(pred, rules).passed


# ============================================================
# Bad-mid mock passes Correctness but fails Mid
# ============================================================
class TestBadMid:
    """The bad_mid mock keeps gold's correct enum fields but rewrites
    specific_change + reasoning to use no required keywords and mentions
    only one tier. Correctness passes; Mid fails on action_keywords and
    multi_tier_evidence."""

    def test_correctness_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_mid"]
        rules = all_evaluator_expectations["08"]
        assert score_correctness(pred, rules).passed

    def test_mid_fails(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_mid"]
        rules = all_evaluator_expectations["08"]
        result = score_mid(pred, rules)
        assert not result.passed

    def test_mid_fails_on_action_keywords(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_mid"]
        rules = all_evaluator_expectations["08"]
        result = score_mid(pred, rules)
        assert any(
            c.name == "action_keywords" and not c.passed for c in result.checks
        )


# ============================================================
# Bad-rich mock passes Correctness + Mid but fails Rich
# ============================================================
class TestBadRich:
    """The bad_rich mock keeps gold's correct enums and keyword-rich prose
    but strips cost_impact/projected_state to nulls and leaves only 1
    evidence bullet. Correctness + Mid pass; Rich fails on multiple checks."""

    def test_correctness_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_rich"]
        rules = all_evaluator_expectations["08"]
        assert score_correctness(pred, rules).passed

    def test_mid_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["bad_rich"]
        rules = all_evaluator_expectations["08"]
        assert score_mid(pred, rules).passed

    def test_rich_fails(
        self, mock_predictions, all_evaluator_expectations, scenario_08_metadata
    ):
        pred = mock_predictions["bad_rich"]
        rules = all_evaluator_expectations["08"]
        result = score_rich(pred, rules, scenario_08_metadata)
        assert not result.passed

    def test_rich_fails_on_evidence_structured(
        self, mock_predictions, all_evaluator_expectations, scenario_08_metadata
    ):
        pred = mock_predictions["bad_rich"]
        rules = all_evaluator_expectations["08"]
        result = score_rich(pred, rules, scenario_08_metadata)
        assert any(
            c.name == "evidence_structured" and not c.passed for c in result.checks
        )


# ============================================================
# Known evaluator gap pinned as a test
# ============================================================
def test_rich_fixture_check_skips_on_scenario_08_top_queries(
    mock_predictions, all_evaluator_expectations, scenario_08_metadata
):
    """KNOWN GAP, documented as a test.

    Scenario 08's metadata stores top_queries entries as
    {query_text, count, p95_latency_ms} with no name/shorthand/id keys.
    The evaluator's _extract_fixture_identifiers only recognizes those
    three identifier keys, so on scenario 08 the fixture_citation check
    sees zero extractable identifiers and skips (passes with a skip
    message). The test pins this so future evaluator changes have to
    acknowledge the gap.

    When the evaluator gains query_text-pattern matching, change this
    test to assert that fixture_citation actually verifies.
    """
    pred = mock_predictions["good"]
    rules = all_evaluator_expectations["08"]
    result = score_rich(pred, rules, scenario_08_metadata)
    assert result.passed
    fixture_check = next(
        (c for c in result.checks if c.name == "fixture_citation"), None
    )
    assert fixture_check is not None
    assert fixture_check.passed
    assert "skipped" in fixture_check.message.lower(), (
        f"fixture_citation should skip for scenario 08; "
        f"got: {fixture_check.message}"
    )
