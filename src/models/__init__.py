"""Pydantic data models for the project.

This package is the single home for every Pydantic schema in the system.
Modules live here rather than scattered next to the code that produces
them, so a reviewer can answer "what are the data shapes?" by reading
one folder.

Current modules:
  - composite : the composite recommendation artifact (gold + scoring
    rubric + optional trace + report content + provenance). Validates
    every file under eval-set/expectations/NN/raw_recommendation.json
    and every live composite produced by the agent pipeline.
  - telemetry : MCP server output schemas (telemetry tools, shared
    context tools, per-tier specials, scenario/dataset tools).

Future modules will land here as harnesses and audit records arrive
(finding schema, audit record types, etc.).
"""
