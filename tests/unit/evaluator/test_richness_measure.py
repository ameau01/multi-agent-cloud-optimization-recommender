"""Unit tests for src/evaluator/richness_measure.py.

Tests score_rich edge cases plus the _extract_fixture_identifiers helper
that score_rich uses internally. No real files.
"""

from __future__ import annotations

from src.evaluator.richness_measure import score_rich, _extract_fixture_identifiers
from src.evaluator.enums import NO_ACTION_FINDINGS


class TestScoreRich:
    def test_short_circuits_on_no_action_findings(self):
        for ft in NO_ACTION_FINDINGS:
            pred = {"finding_type": ft}
            result = score_rich(pred, {}, None)
            assert result.passed
            assert any(c.name == "short_circuit" for c in result.checks), ft

    def test_evidence_structured_passes_with_3_bullets(self):
        pred = {
            "finding_type": "issue_found",
            "evidence": {
                "telemetry_observations": ["a", "b"],
                "infrastructure_context": ["c"],
                "correlation_observations": [],
            },
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        assert score_rich(pred, {}, None).passed

    def test_evidence_structured_fails_with_fewer_than_3(self):
        pred = {
            "finding_type": "issue_found",
            "evidence": {
                "telemetry_observations": ["one"],
                "infrastructure_context": [],
                "correlation_observations": [],
            },
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
        }
        result = score_rich(pred, {}, None)
        assert not result.passed
        assert any(
            c.name == "evidence_structured" and not c.passed for c in result.checks
        )

    def test_cost_impact_quantified_passes_with_non_zero_number(self):
        pred = {
            "finding_type": "issue_found",
            "cost_impact": {"savings_monthly_usd": 1500},
            "projected_state": {"latency_ms": 200},
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
        }
        assert score_rich(pred, {}, None).passed

    def test_cost_impact_quantified_fails_when_all_zero_or_null(self):
        # action_category must be non-null so quantification check applies.
        pred = {
            "finding_type": "issue_found",
            "action_category": "rightsizing",
            "cost_impact": {"savings_monthly_usd": 0, "notes": "tbd"},
            "projected_state": {"latency_ms": 200},
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
        }
        result = score_rich(pred, {}, None)
        assert not result.passed
        assert any(
            c.name == "cost_impact_quantified" and not c.passed for c in result.checks
        )

    def test_fixture_citation_skips_when_metadata_is_none(self):
        pred = {
            "finding_type": "issue_found",
            "specific_change": "do the thing",
            "cost_impact": {"savings_monthly_usd": 100},
            "projected_state": {"latency_ms": 200},
            "evidence": {"telemetry_observations": ["a", "b", "c"]},
        }
        rules = {"must_cite_fixture": "top_queries"}
        # Metadata is None: fixture_citation check should not appear.
        result = score_rich(pred, rules, scenario_metadata=None)
        check_names = {c.name for c in result.checks}
        assert "fixture_citation" not in check_names


class TestExtractFixtureIdentifiers:
    """The _extract_fixture_identifiers helper is module-internal to
    richness_measure.py but accessible for unit testing."""

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
