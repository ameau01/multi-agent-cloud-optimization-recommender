"""The four harness modules.

  - `input` — schema/completeness/trigger validation at ingest.
  - `action` — per-tool-call policy checks plus the final recommendation gate.
  - `reasoning` — pre-produce structured-output checks (evidence_refs, finding_type,
    confidence-breakdown shape) on specialist findings and the evaluator record.
  - `orchestration` — cycle-level transition checks (completion legitimacy,
    specialists-completed-before-evaluator, should-proceed-to-evaluator).

Each harness is a small class that:
  1. Takes an `AuditStore` (so it can write to `harness_trail`).
  2. Exposes one or more `check_*` methods that return a typed result.
  3. Writes a `harness_trail` row per check (verdict='passed' / 'rejected' /
     'flagged' / 'info').

Callers decide what to do with the result (block, retry, escalate). The
harness's only side effect outside the return value is the audit record
it writes.

See `docs/harnesses.md` for the design.
"""

from __future__ import annotations

from .action import ActionHarness, PolicyResult
from .input import InputHarness, ValidationResult
from .orchestration import OrchestrationCheckResult, OrchestrationHarness
from .reasoning import ReasoningCheckResult, ReasoningHarness

__all__ = [
    "ActionHarness",
    "InputHarness",
    "OrchestrationHarness",
    "ReasoningHarness",
    "PolicyResult",
    "ValidationResult",
    "OrchestrationCheckResult",
    "ReasoningCheckResult",
]
