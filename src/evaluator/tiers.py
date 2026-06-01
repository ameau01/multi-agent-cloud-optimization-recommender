"""Back-compat facade for the four-layer scorer.

The scoring functions live in separate modules per layer:
  - shape_measure.py        score_shape
  - correctness_measure.py  score_correctness, score_floor
  - mid_measure.py          score_mid
  - richness_measure.py     score_rich, _extract_fixture_identifiers
  - scoring_helpers.py      prediction_text (shared by mid + richness)
  - types.py                CheckResult, TierResult
  - enums.py                NO_ACTION_FINDINGS, FINDING_TYPES, etc.

This module re-exports everything from those locations so older imports
keep working:

    from src.evaluator.tiers import score_correctness, NO_ACTION_FINDINGS

Continues to work exactly as before. New code can import directly from the
focused modules; existing CLI and tests don't need to change.
"""

from __future__ import annotations

# Result types
from .types import CheckResult, TierResult

# Enum sentinel sets
from .enums import NO_ACTION_FINDINGS

# Layer scorers
from .shape_measure import score_shape
from .correctness_measure import score_correctness, score_floor
from .mid_measure import score_mid
from .richness_measure import score_rich, _extract_fixture_identifiers
from .scoring_helpers import prediction_text


__all__ = [
    # Types
    "CheckResult", "TierResult",
    # Enums
    "NO_ACTION_FINDINGS",
    # Scorers
    "score_shape", "score_correctness", "score_floor",
    "score_mid", "score_rich",
    # Combined
    "score_all_tiers",
    # Helpers (used by some tests)
    "prediction_text", "_extract_fixture_identifiers",
]


# ============================================================
# Combined scorer (preserved here for back-compat)
# ============================================================
def score_all_tiers(prediction: dict, expectations: dict,
                    scenario_metadata: dict | None = None) -> dict:
    """Run Shape, Correctness, Mid, and Rich and return a single dict.

    Mid and Rich are run even when Correctness fails (callers can apply
    the gate by checking correctness.passed). The legacy 'floor' key is
    kept for back-compat: it's Shape + Correctness merged.
    """
    shape = score_shape(prediction, expectations)
    correctness = score_correctness(prediction, expectations)
    mid = score_mid(prediction, expectations)
    rich = score_rich(prediction, expectations, scenario_metadata)
    floor = TierResult(
        tier="floor",
        passed=shape.passed and correctness.passed,
        checks=shape.checks + correctness.checks,
    )
    return {
        "shape": shape,
        "correctness": correctness,
        "floor": floor,           # deprecated, kept for back-compat
        "mid": mid,
        "rich": rich,
        "all_pass": (shape.passed and correctness.passed
                     and mid.passed and rich.passed),
    }
