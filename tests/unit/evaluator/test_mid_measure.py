"""Unit tests for src/evaluator/mid_measure.py.

Tests score_mid edge cases under the threshold-gating design plus the
shared prediction_text helper that mid (and rich) consume. No real files,
no API calls.

Mid behavior (per docs/eval-set.md):
  - short_circuit: when finding_type is in NO_ACTION_FINDINGS, Mid
    passes with a short_circuit marker (no judge needed).
  - graceful skip: when judge_result is None, Mid returns a 'skipped'
    marker (passed=True for report-format compatibility).
  - judge gate: when judge_result is provided, Mid passes iff
    score >= MID_THRESHOLD (30).
"""

from __future__ import annotations

from src.evaluator.mid_measure import score_mid, MID_THRESHOLD
from src.evaluator.scoring_helpers import prediction_text


# ============================================================
# Short-circuit behavior (no-action findings)
# ============================================================
class TestShortCircuit:
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

    def test_short_circuit_takes_precedence_over_judge_result(self):
        """Even if a (stale) judge_result is passed in, a short-circuit
        finding_type wins."""
        pred = {"finding_type": "no_issue_found",
                "specific_change": "all healthy"}
        result = score_mid(pred, {}, judge_result={"score": 10, "rationale": "x"})
        assert result.passed
        assert any(c.name == "short_circuit" for c in result.checks)


# ============================================================
# Graceful skip (no judge available)
# ============================================================
class TestGracefulSkip:
    def test_returns_skipped_when_no_judge_result_provided(self):
        """When the judge is unavailable (no API key), Mid returns a
        'skipped' marker. passed=True keeps the report shape intact."""
        pred = {"finding_type": "issue_found",
                "specific_change": "do something concrete"}
        result = score_mid(pred, {}, judge_result=None)
        assert result.passed  # marker, not a real pass
        assert len(result.checks) == 1
        assert result.checks[0].name == "skipped"
        assert "unavailable" in result.checks[0].message.lower()


# ============================================================
# Threshold gating (judge_result provided)
# ============================================================
class TestThresholdGating:
    def test_passes_when_score_at_threshold(self):
        pred = {"finding_type": "issue_found",
                "specific_change": "do x"}
        result = score_mid(pred, {},
                           judge_result={"score": MID_THRESHOLD,
                                         "rationale": "at boundary"})
        assert result.passed
        assert result.checks[0].name == "judge_richness"

    def test_passes_when_score_above_threshold(self):
        pred = {"finding_type": "issue_found",
                "specific_change": "do x"}
        result = score_mid(pred, {},
                           judge_result={"score": 75, "rationale": "rich"})
        assert result.passed
        check = result.checks[0]
        assert check.detail["score"] == 75
        assert check.detail["threshold"] == MID_THRESHOLD

    def test_fails_when_score_below_threshold(self):
        pred = {"finding_type": "issue_found",
                "specific_change": "do x"}
        result = score_mid(pred, {},
                           judge_result={"score": MID_THRESHOLD - 1,
                                         "rationale": "thin"})
        assert not result.passed
        check = result.checks[0]
        assert check.name == "judge_richness"
        assert not check.passed

    def test_fails_when_score_is_zero(self):
        pred = {"finding_type": "issue_found",
                "specific_change": "do x"}
        result = score_mid(pred, {},
                           judge_result={"score": 0, "rationale": "trivial"})
        assert not result.passed

    def test_rationale_carried_through_to_detail(self):
        pred = {"finding_type": "issue_found",
                "specific_change": "do x"}
        result = score_mid(pred, {},
                           judge_result={"score": 50,
                                         "rationale": "decent prose"})
        assert result.checks[0].detail["rationale"] == "decent prose"


# ============================================================
# prediction_text helper (lives in scoring_helpers; tested here
# because mid/rich are its main callers)
# ============================================================
class TestPredictionText:
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
