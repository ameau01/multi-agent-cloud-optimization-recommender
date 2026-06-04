"""Network Analyst — tier specialist for network telemetry.

Sees egress, ingress, latency, packet-loss, and load-balancer metrics
for the network tier only. The narrowest scope of the three
specialists in terms of metric variety, but the trickiest in terms
of cross-tier signal — network problems often present as compute or
database symptoms first.
"""

from __future__ import annotations

from .base import TierSpecialistNode


class NetworkAnalystNode(TierSpecialistNode):
    """ReAct loop over network-tier MCP tools. One finding per cycle."""

    agent_name = "network_analyst"
    tier_label = "network"
    prompt_name = "network_analyst"

    def _primary_tier_for_finding(self, finding_type: str | None) -> str | None:
        if finding_type == "issue_found":
            return "network"
        return None
