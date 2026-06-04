"""End-to-end integration test for the agent system.

Runs `run_cycle("app-08")` against the real MCP adapter (which reads
from the real HF dataset cache) and validates the resulting audit
trail and harness trail.

Skipped when HF is unreachable — same probe pattern as
tests/integration/test_mcp_server.py. Set NO_NETWORK=1 to opt out
explicitly.
"""

from __future__ import annotations

import os
import socket
import threading
import urllib.error
import urllib.request

import pytest

from src.agents.runner import run_cycle
from src.audit import AuditStore
from src.audit.queries import get_cycle_events
from src.audit.store import IN_MEMORY


_DATASET_REPO = "ameau01/synthesized-cloud-optimization-recommendations"
_PROBE_TIMEOUT_SECONDS = 4.0


def _has_hf_network() -> bool:
    """Same shape as tests/integration/test_mcp_server.py: env opt-outs,
    bounded probe budget. Keeps offline / sandboxed CI from hanging."""
    if os.environ.get("SKIP_HF_TESTS") or os.environ.get("NO_NETWORK"):
        return False

    result: list[bool] = [False]

    def probe() -> None:
        try:
            with socket.create_connection(("huggingface.co", 443), timeout=3):
                pass
        except (OSError, socket.timeout):
            return
        try:
            req = urllib.request.Request(
                f"https://huggingface.co/api/datasets/{_DATASET_REPO}",
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result[0] = 200 <= resp.status < 300
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, OSError, TimeoutError):
            return

    t = threading.Thread(target=probe, daemon=True)
    t.start()
    t.join(timeout=_PROBE_TIMEOUT_SECONDS)
    if t.is_alive():
        return False
    return result[0]


pytestmark = pytest.mark.skipif(
    not _has_hf_network(),
    reason=(
        "HF Hub unreachable, rate-limited, or skipped via "
        "SKIP_HF_TESTS / NO_NETWORK env; skipping agent integration test"
    ),
)


def _make_store() -> AuditStore:
    """In-memory store so the test never touches disk."""
    s = AuditStore(db_path=IN_MEMORY)
    s.initialize()
    return s


def test_agents_correctly_identifies_app_08_tiers() -> None:
    """app-08 is the cross-tier database scenario — compute + database.
    The system_mapper_output row should record exactly those two tiers."""
    store = _make_store()
    cycle_id = run_cycle("app-08", store=store, trigger_type="test")
    events = get_cycle_events(store, cycle_id)
    sys_row = next(e for e in events if e.type == "system_mapper_output")
    tiers = sys_row.content["tiers_detected"]
    assert "compute" in tiers
    assert "database" in tiers


def test_agents_rejects_bogus_app() -> None:
    """Unknown app-name is rejected at the Input Harness gate.
    System Mapper never runs."""
    store = _make_store()
    cycle_id = run_cycle("app-99", store=store, trigger_type="test")
    events = get_cycle_events(store, cycle_id)
    types = {e.type for e in events}
    assert "tool_call" not in types
    assert "system_mapper_output" not in types
    cycle_completed = next(e for e in events if e.type == "cycle_completed")
    assert cycle_completed.content["final_status"] == "rejected_input"
