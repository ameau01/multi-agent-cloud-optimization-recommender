"""Shared result types used by every scoring layer.

CheckResult and TierResult are the data structures returned by score_shape,
score_correctness, score_mid, and score_rich. Kept in one module so the
four scoring modules (shape, correctness, richness) can import without
circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class TierResult:
    tier: str               # "shape", "correctness", "floor", "mid", or "rich"
    passed: bool            # all checks in this tier passed
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message,
                 "detail": c.detail}
                for c in self.checks
            ],
        }
