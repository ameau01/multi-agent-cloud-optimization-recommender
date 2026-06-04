"""Compute Analyst — tier specialist for compute telemetry.

Bounded to the compute tier by the Action Harness's per-agent
allow-list. Sees CPU, memory, request-rate, instance-count, and
related compute metrics; cannot reach database, cache, or network
telemetry. The structural scope is what gives the cross-tier
evaluator's drift-check its integrity — each specialist's view is
genuinely independent.
"""

from __future__ import annotations

from .base import TierSpecialistNode


class ComputeAnalystNode(TierSpecialistNode):
    """ReAct loop over compute-tier MCP tools. One finding per cycle."""

    agent_name = "compute_analyst"
    tier_label = "compute"
    prompt_name = "compute_analyst"

    def _primary_tier_for_finding(self, finding_type: str | None) -> str | None:
        if finding_type == "issue_found":
            return "compute"
        return None
