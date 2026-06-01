#!/usr/bin/env bash
# Print the catalog of tools the MCP server exposes.
#
# What this proves:
#   - The server registers exactly the 18 tools documented in mcp-server.md.
#   - Every tool's signature and one-line description matches the catalog.
#   - The scope.py allow-list maps each tool to the specialists allowed
#     to call it.
#
# Usage:
#   scripts/list_mcp_tools.sh                       # human-readable table
#   scripts/list_mcp_tools.sh --json                # machine-readable JSON
#   scripts/list_mcp_tools.sh --schema get_summary_statistics
#                                                   # full input schema for one tool

set -e
cd "$(dirname "$0")/.."

uv run python tests/list_mcp_tools.py "$@"
