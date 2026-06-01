"""Multi-agent orchestration layer.

The six agents (Supervisor, System Mapper, three Tier Specialists,
Cross-Tier Evaluator) and the orchestrator that runs them. The agent
implementation is in progress; see CHANGELOG.md for current status.

The stable interface is the orchestrator's return value: a
recommendation dict that conforms to the eval-set gold-answer schema.
src/evaluator/ scores that output without knowing how it was produced.
"""

from src.agents.orchestrator import orchestrate

__all__ = ["orchestrate"]
