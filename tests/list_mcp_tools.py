#!/usr/bin/env python3
"""Enumerate every tool the MCP server exposes.

Prints the tool catalog as a human-readable table — one row per tool with
its name, family, parameters, and one-line description. Also reports
which specialists are allowed to call each tool, per scope.py.

This is the in-process equivalent of `tools/list` over the MCP protocol;
it doesn't spawn the server, just imports the same FastMCP instance that
the server would. Useful for:

  - Showing a hiring manager "this is the tool surface, exactly as the
    server publishes it."
  - Catching catalog regressions (the expected total is 18).
  - Cross-referencing scope.py against the live tool registry.

Run:
    scripts/list_mcp_tools.sh              # bash wrapper (preferred entry point)
    uv run python tests/list_mcp_tools.py  # direct Python invocation

Options:
    --json                Produce the catalog as machine-readable JSON.
    --schema TOOL_NAME    Print the full input/output JSON schema for one tool.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path

# Make src/ importable when run directly.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mcp_server.server import mcp
from src.mcp_server.scope import SPECIALIST_TOOL_ALLOWLIST


# Map each tool name to the family it belongs to (matches src/mcp_server/tools/).
_TOOL_FAMILY: dict[str, str] = {
    # telemetry (6)
    "get_time_series": "telemetry",
    "get_summary_statistics": "telemetry",
    "get_time_pattern": "telemetry",
    "detect_threshold_breaches": "telemetry",
    "get_metric_distribution": "telemetry",
    "get_configuration": "telemetry",
    # context (4)
    "get_business_context": "context",
    "get_sla_target": "context",
    "get_monthly_cost": "context",
    "get_before_after_evidence": "context",
    # specials (3)
    "get_per_instance_breakout": "specials",
    "get_top_queries": "specials",
    "get_top_cache_keys": "specials",
    # scenarios (5)
    "list_scenarios": "scenarios",
    "get_scenario_metadata": "scenarios",
    "get_terraform": "scenarios",
    "get_correlation_evidence": "scenarios",
    "get_handcrafted_recommendation": "scenarios",
}


def _all_tools() -> list:
    """Return the list of FastMCP Tool objects. Handles sync + async APIs."""
    tools = mcp._tool_manager.list_tools()
    if asyncio.iscoroutine(tools):
        tools = asyncio.run(tools)
    return sorted(tools, key=lambda t: (_TOOL_FAMILY.get(t.name, "zzz"), t.name))


def _specialists_for(tool_name: str) -> list[str]:
    """Return the list of specialists allowed to call this tool, per scope.py."""
    return sorted(
        specialist
        for specialist, tools in SPECIALIST_TOOL_ALLOWLIST.items()
        if tool_name in tools
    )


def _signature(tool) -> str:
    """Return the function signature as a string, e.g.
    'get_summary_statistics(app_name: str, tier: str, metric: str) -> dict'.
    """
    if tool.fn is None:
        return f"{tool.name}(...)"
    return f"{tool.name}{inspect.signature(tool.fn)}"


def _short_desc(tool) -> str:
    """First line of the docstring, trimmed."""
    if not tool.description:
        return ""
    return tool.description.strip().split("\n", 1)[0]


# ============================================================
# Renderers
# ============================================================
def render_table(tools: list) -> str:
    """Multi-column table grouped by family."""
    lines: list[str] = []
    lines.append(f"MCP server tool catalog — {len(tools)} tools total")
    lines.append("=" * 72)
    current_family = None
    for tool in tools:
        family = _TOOL_FAMILY.get(tool.name, "?")
        if family != current_family:
            lines.append("")
            lines.append(f"[{family}]")
            current_family = family
        lines.append(f"  {tool.name}")
        lines.append(f"    signature:   {_signature(tool)}")
        lines.append(f"    summary:     {_short_desc(tool)}")
        specialists = _specialists_for(tool.name)
        lines.append(f"    allowed for: {', '.join(specialists) if specialists else '(no specialist; e.g. evaluator-only)'}")
    return "\n".join(lines)


def render_json(tools: list) -> str:
    """Machine-readable JSON."""
    out = []
    for tool in tools:
        out.append({
            "name": tool.name,
            "family": _TOOL_FAMILY.get(tool.name, "unknown"),
            "signature": _signature(tool),
            "description": tool.description or "",
            "allowed_specialists": _specialists_for(tool.name),
        })
    return json.dumps({"tools": out, "count": len(out)}, indent=2)


def render_schema(tool_name: str, tools: list) -> str:
    """Dump the full FastMCP-derived JSON Schema for one tool."""
    for tool in tools:
        if tool.name == tool_name:
            return json.dumps(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,  # FastMCP attaches the auto-derived schema here
                },
                indent=2,
            )
    known = ", ".join(sorted(t.name for t in tools))
    return f"unknown tool: {tool_name!r}. Known tools: {known}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--json", action="store_true", help="produce JSON instead of a table")
    parser.add_argument("--schema", metavar="TOOL_NAME",
                        help="print the JSON schema for one tool and exit")
    args = parser.parse_args()

    tools = _all_tools()

    if args.schema:
        print(render_schema(args.schema, tools))
    elif args.json:
        print(render_json(tools))
    else:
        print(render_table(tools))

    return 0


if __name__ == "__main__":
    sys.exit(main())
