#!/usr/bin/env bash
# Run the MCP server wire-layer integration test.
#
# What this proves:
#   - The server spawns cleanly as a subprocess via `python -m src.mcp_server`.
#   - The MCP protocol handshake (initialize, tools/list, tools/call) works
#     over stdio against a real client.
#   - All 18 registered tools are reachable.
#   - One representative tool per family returns the expected response shape.
#
# Auto-skips when Hugging Face is unreachable from this network (sandboxes,
# offline laptops). On a normal dev machine with HF access, all 6 tests run.
#
# Usage:
#   scripts/run_mcp_server_test.sh           # default verbose run
#   scripts/run_mcp_server_test.sh -x        # stop at first failure
#   scripts/run_mcp_server_test.sh -k list   # run only test_list_scenarios*

set -e
cd "$(dirname "$0")/.."

uv run python -m pytest tests/integration/test_mcp_server.py -v "$@"
