"""Layer 1: Shape.

Confirms the prediction is parseable JSON with the required top-level
fields. Does not look at values. The next layer (correctness.py) handles
value comparisons.

A reasonable agent passes Shape 18 of 18. A baseline that returns a
Python `None` or an empty string fails.
"""

from __future__ import annotations

from .types import CheckResult, TierResult


def score_shape(prediction: dict, expectations: dict | None = None) -> TierResult:
    """Shape checks: required fields present, non-empty specific_change.

    Does NOT look at values. A wrong-but-well-formed JSON passes Shape;
    Correctness is where it fails.

    The `expectations` parameter is unused (Shape does not consult per-scenario
    rules) but kept for signature parity with the other scoring functions.
    """
    checks: list[CheckResult] = []

    # Required top-level fields
    for required in ("finding_type", "primary_tier", "action_category",
                     "specific_change"):
        checks.append(CheckResult(
            name=f"field_present:{required}",
            passed=required in prediction,
            message=f"{required} present in prediction: {required in prediction}",
        ))

    # specific_change is a string with at least 20 characters
    spec = prediction.get("specific_change") or ""
    if not isinstance(spec, str):
        checks.append(CheckResult(
            name="specific_change_present",
            passed=False,
            message=f"specific_change is {type(spec).__name__}, expected str",
        ))
    else:
        checks.append(CheckResult(
            name="specific_change_present",
            passed=len(spec.strip()) >= 20,
            message=f"specific_change length: {len(spec.strip())} chars",
            detail={"min_chars": 20},
        ))

    overall = all(c.passed for c in checks)
    return TierResult(tier="shape", passed=overall, checks=checks)
