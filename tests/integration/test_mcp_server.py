"""Wire-layer integration test for the MCP server.

Drives the server through the MCP client API (in-process via stdio
transport), so we exercise the real protocol path without needing a
GUI client like Claude Desktop.

Test strategy:
  1. Spawn the server through `mcp` client's StdioServerParameters.
  2. Call tools/list, assert the catalog matches what we expect.
  3. Call tools/call for one representative tool per family against
     scenario 08 (or a similar fixture), assert the response shape.

We intentionally don't exhaustively call all 18 tools end-to-end — the
unit tests for each tool family + the data_loader already cover
correctness. This test guarantees the wire layer works.

These tests need network access to Hugging Face on first run to populate
the .hf_cache. They're skipped in sandboxed CI environments that lack
network access (detected via a connection attempt at the top of the
file).
"""

from __future__ import annotations

import asyncio
import socket

import pytest


def _has_hf_network() -> bool:
    """Quick TCP connect test to huggingface.co:443. Skip the suite when
    the sandbox blocks it (e.g. SOCKS-only envs)."""
    try:
        with socket.create_connection(("huggingface.co", 443), timeout=3):
            return True
    except (OSError, socket.timeout):
        return False


pytestmark = pytest.mark.skipif(
    not _has_hf_network(),
    reason="HF Hub unreachable from this environment; skipping wire test",
)


# Lazy imports — only happen when the suite isn't skipped.
def _client_context():
    """Return an async context manager that yields an MCP ClientSession
    connected to our server over stdio."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command="python",
        args=["-m", "src.mcp_server"],
    )
    return stdio_client(params), ClientSession


# ============================================================
# tools/list
# ============================================================
def test_server_exposes_18_tools():
    async def go():
        stdio_cm, ClientSession = _client_context()
        async with stdio_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_resp = await session.list_tools()
                names = {t.name for t in tools_resp.tools}
        return names

    names = asyncio.run(go())
    expected = {
        # telemetry
        "get_time_series", "get_summary_statistics", "get_time_pattern",
        "detect_threshold_breaches", "get_metric_distribution", "get_configuration",
        # context
        "get_business_context", "get_sla_target", "get_monthly_cost",
        "get_before_after_evidence",
        # specials
        "get_per_instance_breakout", "get_top_queries", "get_top_cache_keys",
        # scenarios
        "list_scenarios", "get_scenario_metadata", "get_terraform",
        "get_correlation_evidence", "get_handcrafted_recommendation",
    }
    missing = expected - names
    extra = names - expected
    assert not missing, f"missing tools: {sorted(missing)}"
    assert not extra, f"unexpected tools: {sorted(extra)}"


# ============================================================
# tools/call — one per family
# ============================================================
def _call_tool(name: str, arguments: dict) -> dict:
    """Helper: spawn server, call one tool, return the parsed result."""
    import json as _json

    async def go():
        stdio_cm, ClientSession = _client_context()
        async with stdio_cm as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                # MCP results come back as a list of content blocks; for
                # JSON-returning tools the first block is a TextContent
                # carrying the JSON string.
                first = result.content[0]
                return _json.loads(first.text)

    return asyncio.run(go())


def test_list_scenarios_returns_18_app_names():
    result = _call_tool("list_scenarios", {})
    assert "app_names" in result
    assert len(result["app_names"]) == 18
    assert all(name.startswith("app-") for name in result["app_names"])


def test_get_summary_statistics_telemetry():
    result = _call_tool("get_summary_statistics",
                        {"app_name": "app-08", "tier": "compute", "metric": "cpu_p95"})
    assert result["app_name"] == "app-08"
    assert result["tier"] == "compute"
    assert {"mean", "p50", "p90", "p95"}.issubset(result.keys())


def test_get_business_context_context():
    result = _call_tool("get_business_context", {"app_name": "app-08"})
    assert result["app_name"] == "app-08"
    assert "business_context" in result


def test_get_top_queries_specials():
    # Scenario 08 has the cross-tier DB cascade — has top_queries evidence.
    result = _call_tool("get_top_queries", {"app_name": "app-08"})
    assert result["app_name"] == "app-08"
    assert isinstance(result["top_queries"], list)
    assert len(result["top_queries"]) > 0


def test_get_terraform_scenarios():
    result = _call_tool("get_terraform", {"app_name": "app-08"})
    assert result["app_name"] == "app-08"
    assert "aws_" in result["terraform"]  # raw HCL text
