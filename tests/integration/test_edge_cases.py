"""Integration test: degraded recommendations fail the right layer.

Loads five mock predictions for scenario 08 from
tests/integration/fixtures/mock_predictions/:

  - scenario_08_good.json            (byte-identical to gold; passes all layers)
  - scenario_08_bad_correctness.json (wrong primary_tier; fails Correctness)
  - scenario_08_low_richness.json    (correct enums, generic prose;
                                      LLM judge would score ~15)
  - scenario_08_mid_richness.json    (correct enums, on-target shallow prose;
                                      LLM judge would score ~45)
  - scenario_08_thin_structure.json  (correct enums, rich prose, but evidence
                                      field too sparse; judge ~75, fails
                                      Rich's structural check)

Each mock is crafted to exercise exactly one path through the four-layer
evaluator under the threshold-gating design documented in
`docs/eval-set.md`:

  Shape       deterministic   well-formed JSON
  Correctness deterministic   strict enum equality on 4 fields
  Mid         LLM judge       score >= 30 on `specific_change`
  Rich        LLM judge gate  score >= 60 AND deterministic existence checks

Each non-good mock carries a leading-underscore annotation:
  _expected_judge_score      what the judge is expected to return
  _judge_score_rationale     why the prose earns that score

The mock_judge fixture in conftest.py reads these annotations to simulate
the judge without an API call, letting these tests exercise the
threshold logic without touching the live LLM client.

Tests that depend on judge-aware code paths still under development are
marked with `@pytest.mark.skip(...)` so they document the contract
without breaking CI today.

Run:
    pytest tests/integration/test_edge_cases.py -v
"""

from __future__ import annotations

from src.evaluator.tiers import (
    score_shape,
    score_correctness,
    score_mid,
    score_rich,
)


# ============================================================
# Good mock: every layer passes
# ============================================================
class TestGoodMock:
    """The good mock is byte-identical to the gold answer. Every layer
    should pass: Shape, Correctness deterministically; Mid + Rich via
    the judge (or its placeholder)."""

    def test_shape_passes(self, mock_predictions, all_evaluator_expectations):
        pred = mock_predictions["good"]
        rules = all_evaluator_expectations["08"]
        assert score_shape(pred, rules).passed

    def test_correctness_passes(self, mock_predictions, all_evaluator_expectations):
        pred = mock_predictions["good"]
        rules = all_evaluator_expectations["08"]
        assert score_correctness(pred, rules).passed

    def test_mid_passes_via_judge(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        mock_judge,
    ):
        pred = mock_predictions["good"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)  # good has no annotation, defaults to 100
        assert score_mid(pred, rules, judge_result=judge_result).passed

    def test_rich_passes_via_judge(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        scenario_08_metadata, mock_judge,
    ):
        pred = mock_predictions["good"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)
        assert score_rich(pred, rules, scenario_08_metadata,
                          judge_result=judge_result).passed


# ============================================================
# Bad-correctness mock: fails Correctness deterministically
# ============================================================
class TestBadCorrectness:
    """The bad_correctness mock has wrong primary_tier (compute instead of
    database) AND wrong action_category. Correctness fails on both fields.
    Mid + Rich are gated off in production scoring; in unit isolation we
    only assert Correctness here."""

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
# Low-richness mock: judge score < 30; Mid + Rich both fail
# ============================================================
class TestLowRichness:
    """The low_richness mock keeps correct enums but the prose is generic,
    uses vague synonyms, and lacks any specifics. Expected judge score
    is ~15. Mid and Rich both fail under the threshold-gating design."""

    def test_correctness_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["low_richness"]
        rules = all_evaluator_expectations["08"]
        assert score_correctness(pred, rules).passed

    def test_annotation_consistent_with_design(self, mock_predictions):
        """Sanity-check the fixture's annotation matches the layer this
        mock is supposed to exercise."""
        pred = mock_predictions["low_richness"]
        assert pred["_expected_judge_score"] < 30, (
            "low_richness mock must annotate a score < 30 (Mid + Rich fail)"
        )

    def test_mid_fails_via_judge_threshold(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        mock_judge,
    ):
        """mock_judge reads _expected_judge_score=15 from the fixture;
        15 < 30 (MID_THRESHOLD) so Mid fails."""
        pred = mock_predictions["low_richness"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)
        assert judge_result["score"] == 15  # confirms fixture annotation read
        assert not score_mid(pred, rules, judge_result=judge_result).passed

    def test_rich_fails_via_judge_threshold(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        scenario_08_metadata, mock_judge,
    ):
        """Score 15 < 60 (RICH_THRESHOLD); Rich's judge gate fails,
        structural checks not reached."""
        pred = mock_predictions["low_richness"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)
        result = score_rich(pred, rules, scenario_08_metadata,
                            judge_result=judge_result)
        assert not result.passed
        assert result.checks[0].name == "judge_richness"
        # Structural checks were short-circuited by the failing gate
        assert len(result.checks) == 1


# ============================================================
# Mid-richness mock: judge score 30-59; Mid passes, Rich fails
# ============================================================
class TestMidRichness:
    """The mid_richness mock keeps correct enums and the prose engages
    with the right direction (mentions DB, compute, queries, replicas)
    but lacks specificity (no table names, no replica counts, no
    quantified projections). Expected judge score is ~45.

    Mid passes (45 >= 30); Rich fails because the judge gate is 60.
    Even though the structural checks would pass (full evidence, full
    cost, full projected_state), Rich is short-circuited by the score
    threshold."""

    def test_correctness_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["mid_richness"]
        rules = all_evaluator_expectations["08"]
        assert score_correctness(pred, rules).passed

    def test_annotation_consistent_with_design(self, mock_predictions):
        pred = mock_predictions["mid_richness"]
        score = pred["_expected_judge_score"]
        assert 30 <= score < 60, (
            "mid_richness mock must annotate a score in [30, 60) "
            "(Mid pass, Rich fail on judge gate)"
        )

    def test_mid_passes_via_judge_threshold(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        mock_judge,
    ):
        """Score ~45 >= 30; Mid passes."""
        pred = mock_predictions["mid_richness"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)
        assert 30 <= judge_result["score"] < 60
        assert score_mid(pred, rules, judge_result=judge_result).passed

    def test_rich_fails_on_judge_gate(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        scenario_08_metadata, mock_judge,
    ):
        """Score 30-59 passes Mid but fails Rich's 60 gate. The
        structural checks below the gate are not run."""
        pred = mock_predictions["mid_richness"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)
        result = score_rich(pred, rules, scenario_08_metadata,
                            judge_result=judge_result)
        assert not result.passed
        # Only the gate check ran; structural checks gated off
        assert len(result.checks) == 1
        assert result.checks[0].name == "judge_richness"


# ============================================================
# Thin-structure mock: judge score >= 60 but evidence too sparse
# ============================================================
class TestThinStructure:
    """The thin_structure mock has rich, specific prose (names six
    queries, specifies indexes, replica count, instance class) that
    earns a high judge score (~75), but the supporting `evidence`
    field carries only 1 bullet total when Rich requires >= 3.

    Mid passes (75 >= 30); the judge gate for Rich also passes
    (75 >= 60); but the deterministic evidence_structured check fails
    because the supporting evidence is too thin to back up the prose."""

    def test_correctness_passes(
        self, mock_predictions, all_evaluator_expectations
    ):
        pred = mock_predictions["thin_structure"]
        rules = all_evaluator_expectations["08"]
        assert score_correctness(pred, rules).passed

    def test_annotation_consistent_with_design(self, mock_predictions):
        pred = mock_predictions["thin_structure"]
        score = pred["_expected_judge_score"]
        assert score >= 60, (
            "thin_structure mock must annotate score >= 60 "
            "(judge gate passes; Rich fails on existence check)"
        )

    def test_evidence_is_actually_thin(self, mock_predictions):
        """Sanity-check that the mock's evidence field really has fewer
        than 3 bullets total. If a future edit pads the evidence, this
        test will fail and the fixture intent should be re-examined."""
        pred = mock_predictions["thin_structure"]
        evidence = pred.get("evidence") or {}
        bullets = 0
        for cat in ("telemetry_observations", "infrastructure_context",
                    "correlation_observations"):
            bullets += len(evidence.get(cat) or [])
        assert bullets < 3, (
            f"thin_structure mock must have < 3 evidence bullets total "
            f"(found {bullets}); the structural check needs something "
            f"to fail on"
        )

    def test_rich_fails_on_evidence_structured_despite_judge_passing(
        self, mock_predictions, all_gold_answers, all_evaluator_expectations,
        scenario_08_metadata, mock_judge,
    ):
        """Score 75 clears the 60 gate, but evidence has < 3 bullets
        so the structural check fails."""
        pred = mock_predictions["thin_structure"]
        rules = all_evaluator_expectations["08"]
        gold = all_gold_answers["08"]
        judge_result = mock_judge(gold, pred)
        assert judge_result["score"] >= 60  # gate passes
        result = score_rich(pred, rules, scenario_08_metadata,
                            judge_result=judge_result)
        assert not result.passed
        assert any(
            c.name == "judge_richness" and c.passed for c in result.checks
        ), "gate should pass at score >= 60"
        assert any(
            c.name == "evidence_structured" and not c.passed
            for c in result.checks
        ), "evidence_structured should fail with < 3 bullets"
