"""Tier specialists — Compute, Data Layer, Network.

Each specialist is a bounded ReAct agent: it pulls telemetry through
its tier-scoped MCP surface, reasons in iterative thought/action/
observation turns, and produces one structured `specialist_finding` audit
record per cycle. The Action Harness's per-agent tool allow-list
(`src/mcp_server/scope.py`) is what makes the scope structural — a
compute analyst cannot reach database telemetry even if its prompt
asked for it.

The shared loop, harness wiring, and audit writes live in
`base.TierSpecialistNode`. Each concrete subclass provides only the
agent name, the human-readable tier label for prompt substitution,
and the prompt file to load. Three subclasses, one base class.
"""

from .base import SpecialistError, TierSpecialistNode
from .compute import ComputeAnalystNode
from .data_layer import DataLayerAnalystNode
from .network import NetworkAnalystNode

__all__ = [
    "SpecialistError",
    "TierSpecialistNode",
    "ComputeAnalystNode",
    "DataLayerAnalystNode",
    "NetworkAnalystNode",
]
