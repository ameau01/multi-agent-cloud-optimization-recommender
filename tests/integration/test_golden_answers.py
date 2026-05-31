"""Integration test: every gold answer passes every layer of its own evaluator.

This is the headline benchmark-integrity test. If the gold answers and the
scoring rules are aligned, all 18 must pass:
  - Shape (well-formed JSON, required fields)
  - Correctness (enum equality with the per-scenario rules)
  - Mid (keyword groups + multi-tier evidence, or short-circuit on no-action)
  - Rich (fixture citation + quantification, or short-circuit on no-action)

A failure here means rules and golds have drifted apart. Fix one or the
other before publishing the eval set.

Run:
    pytest tests/integration/test_golden_answers.py -v
"""

from __future__ import annotations

import pytest

from src.evaluator.tiers import (
    score_shape,
    score_correctness,
    score_floor,
    score_mid,
    score_rich,
    NO_ACTION_FINDINGS,
)


SCENARIO_IDS = [f"{i:02d}" for i in range(1, 19)]
# Scenarios that have metadata vendored locally (for Rich fixture_citation)
LOCAL_METADATA_SCENARIOS = {"08"}


# ============================================================
# Shape: every gold answer is well-formed
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_shape_passes_on_gold(sid, all_gold_answers, all_evaluator_expectations):
    gold = all_gold_answers[sid]
    expectations = all_evaluator_expectations[sid]
    result = score_shape(gold, expectations)
    assert result.passed, (
        f"scenario {sid}: Shape failed on gold answer. "
        f"Failing: {[c.name for c in result.checks if not c.passed]}"
    )


# ============================================================
# Correctness: every gold matches its own per-scenario rules
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_correctness_passes_on_gold(sid, all_gold_answers, all_evaluator_expectations):
    gold = all_gold_answers[sid]
    expectations = all_evaluator_expectations[sid]
    result = score_correctness(gold, expectations)
    assert result.passed, (
        f"scenario {sid}: Correctness failed on gold answer. "
        f"Failing: {[c.name for c in result.checks if not c.passed]}"
    )


# ============================================================
# Floor (back-compat alias = Shape + Correctness combined)
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_floor_passes_on_gold(sid, all_gold_answers, all_evaluator_expectations):
    gold = all_gold_answers[sid]
    expectations = all_evaluator_expectations[sid]
    result = score_floor(gold, expectations)
    assert result.passed, (
        f"scenario {sid}: Floor failed on gold answer. "
        f"Failing: {[c.name for c in result.checks if not c.passed]}"
    )


# ============================================================
# Mid: every gold answer passes (active layer or short-circuit)
# ============================================================
@pytest.mark.parametrize("sid", SCENARIO_IDS)
def test_mid_passes_on_gold(sid, all_gold_answers, all_evaluator_expectations):
    gold = all_gold_answers[sid]
    expectations = all_evaluator_expectations[sid]
    result = score_mid(gold, expectations)
    assert result.passed, (
        f"scenario {sid}: Mid failed on gold answer. "
        f"Failing: {[c.name for c in result.checks if not c.passed]}"
    )


# ============================================================
# Rich: scenario 08 with metadata; others with metadata=None
# ============================================================
def test_rich_passes_on_scenario_08_with_metadata(
    all_gold_answers, all_evaluator_expectations, scenario_08_metadata
):
    """Scenario 08 has its metadata vendored locally, so the
    fixture_citation check can fully resolve (even though it currently
    skips due to the documented top_queries identifier-key gap)."""
    gold = all_gold_answers["08"]
    expectations = all_evaluator_expectations["08"]
    result = score_rich(gold, expectations, scenario_08_metadata)
    assert result.passed, (
        f"Rich failed on scenario 08 gold. "
        f"Failing: {[c.name for c in result.checks if not c.passed]}"
    )


@pytest.mark.parametrize(
    "sid",
    [s for s in SCENARIO_IDS if s not in LOCAL_METADATA_SCENARIOS],
)
def test_rich_passes_on_gold_without_metadata(
    sid, all_gold_answers, all_evaluator_expectations
):
    """Without metadata, fixture_citation skips cleanly; the other Rich
    checks still run and must pass on the gold."""
    gold = all_gold_answers[sid]
    expectations = all_evaluator_expectations[sid]
    result = score_rich(gold, expectations, scenario_metadata=None)
    assert result.passed, (
        f"scenario {sid}: Rich failed (metadata=None). "
        f"Failing: {[c.name for c in result.checks if not c.passed]}"
    )


# ============================================================
# Short-circuit semantics: no-action scenarios bypass Mid + Rich
# ============================================================
@pytest.mark.parametrize("sid", ["06", "15", "17"])
def test_short_circuit_marker_present_for_no_action_scenarios(
    sid, all_gold_answers, all_evaluator_expectations
):
    """Scenarios 06, 15, 17 (no_issue_found + diagnostic_deferral) should
    show the short_circuit marker on both Mid and Rich."""
    gold = all_gold_answers[sid]
    expectations = all_evaluator_expectations[sid]
    assert gold["finding_type"] in NO_ACTION_FINDINGS

    mid = score_mid(gold, expectations)
    assert mid.passed
    assert any(c.name == "short_circuit" for c in mid.checks), (
        f"scenario {sid}: Mid should have short_circuit marker; "
        f"got checks: {[c.name for c in mid.checks]}"
    )

    rich = score_rich(gold, expectations, scenario_metadata=None)
    assert rich.passed
    assert any(c.name == "short_circuit" for c in rich.checks), (
        f"scenario {sid}: Rich should have short_circuit marker; "
        f"got checks: {[c.name for c in rich.checks]}"
    )


# ============================================================
# Aggregate: all 18 gold answers pass all 4 layers
# ============================================================
def test_all_18_gold_answers_pass_all_layers(
    all_gold_answers, all_evaluator_expectations
):
    """End-to-end sanity: every scenario, every layer, all pass.
    The headline guarantee in docs/eval-set.md."""
    shape_passes = correctness_passes = mid_passes = rich_passes = 0
    for sid in SCENARIO_IDS:
        gold = all_gold_answers[sid]
        expectations = all_evaluator_expectations[sid]
        if score_shape(gold, expectations).passed:
            shape_passes += 1
        if score_correctness(gold, expectations).passed:
            correctness_passes += 1
        if score_mid(gold, expectations).passed:
            mid_passes += 1
        if score_rich(gold, expectations, scenario_metadata=None).passed:
            rich_passes += 1
    assert shape_passes == 18, f"Shape passes only {shape_passes}/18"
    assert correctness_passes == 18, f"Correctness passes only {correctness_passes}/18"
    assert mid_passes == 18, f"Mid passes only {mid_passes}/18 (includes short-circuit)"
    assert rich_passes == 18, f"Rich passes only {rich_passes}/18 (includes short-circuit)"
