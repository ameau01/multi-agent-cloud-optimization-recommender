"""Live-judge self-validation: each gold answer scores high against itself.

The judge prompt promises that a prediction substantively equivalent to
the gold scores 75 to 95. The trivial case is comparing the gold's own
`specific_change` to itself: a well-calibrated prompt should land at or
near 100.

This test makes one real API call per non-short-circuit scenario (15
calls). At small-model pricing (Haiku or gpt-4o-mini), one full run is
roughly $0.02. The provider is whatever JudgeClient auto-detects
(OpenAI is preferred when both keys are set; LLM_JUDGE_PROVIDER
overrides).

Run only when iterating on the judge prompt:
    pytest tests/judge_live/ -v

Skipped automatically when neither OPENAI_API_KEY nor
ANTHROPIC_API_KEY is in the environment.
"""

from __future__ import annotations

import pytest

from src.evaluator.enums import NO_ACTION_FINDINGS


SHORT_CIRCUIT_SIDS = ("06", "15", "17")


def _action_scenarios(all_golds: dict) -> list[str]:
    """Return scenario ids whose gold is an action recommendation (not
    a no-action / short-circuit case)."""
    return [
        sid for sid, gold in sorted(all_golds.items())
        if gold.get("finding_type") not in NO_ACTION_FINDINGS
    ]


@pytest.mark.parametrize("sid", [
    "01", "02", "03", "04", "05", "07", "08", "09",
    "10", "11", "12", "13", "14", "16", "18",
])
def test_gold_scores_high_against_itself(sid, live_judge_or_skip, all_golds):
    """Calling judge(gold, gold) for the same scenario must return a
    score in the high-richness band (>= 75). If this fails, either the
    prompt is too strict or the gold's prose is too thin to be the
    standard."""
    gold = all_golds[sid]
    result = live_judge_or_skip.score(gold=gold, prediction=gold)
    assert result["score"] >= 75, (
        f"scenario {sid}: gold scored {result['score']} against itself "
        f"(expected >= 75). Rationale: {result['rationale']!r}"
    )


def test_scenario_08_gold_scores_at_least_60(live_judge_or_skip, all_golds):
    """Tighter assertion on the canonical demo scenario: scenario 08's
    gold must clear the Rich gate (>= 60) against itself. This is the
    gate-passing case the design depends on."""
    gold = all_golds["08"]
    result = live_judge_or_skip.score(gold=gold, prediction=gold)
    assert result["score"] >= 60, (
        f"scenario 08 gold-vs-gold score {result['score']} < 60. "
        f"Rationale: {result['rationale']!r}"
    )
    assert "rationale" in result
    assert len(result["rationale"]) > 20, "rationale should be a real paragraph"
