"""Unit test: the agent-orchestrator interface contract holds.

The orchestrator is a Phase 7 placeholder. Until the real agents land,
src/agents/orchestrate() must exist and raise NotImplementedError with a
specific message that points users at the evaluator (which IS the stable
interface). This test pins that contract.

Run:
    pytest tests/unit/test_agents_contract.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make src/ importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestOrchestratorInterfaceContract:
    """src/agents/orchestrate() should exist, be callable, and raise
    NotImplementedError with a specific pointer message."""

    def test_orchestrate_is_importable(self):
        from src.agents import orchestrate
        assert callable(orchestrate)

    def test_orchestrate_raises_with_pointer_to_status(self):
        from src.agents import orchestrate
        with pytest.raises(NotImplementedError) as exc_info:
            orchestrate({"scenario_id": "08"})
        msg = str(exc_info.value)
        assert "Phase 7" in msg, "error message should reference Phase 7 status"
        assert "evaluator" in msg.lower(), (
            "error message should reference the stable evaluator interface"
        )
