# Cycle Fixtures — Frozen Audit Data for LangGraph Mock Runs

This folder holds JSON snapshots of completed agent cycles, exported
from the audit DB. Each fixture is the **single source of truth** for
what one historical cycle looked like — every audit_records row and
every harness_trail verdict, in the order they landed.

Sole purpose: drive a **mock LangGraph run** — a future re-invocation
of `build_graph` where the MCP adapter and LLM clients are
monkey-patched to return canned responses pulled from this fixture, so
the same cycle can be replayed without burning real Anthropic / OpenAI
calls.

## How to produce a fixture

The exporter is `tests/export_cycle_fixture.py`. From the project
root with a populated audit DB:

```bash
python tests/export_cycle_fixture.py \
    --cycle cycle_20260604_090632_d4333b8a \
    --out tests/integration/agents/fixtures/cycle_app08.json
```

The script reads `.audit_db/audit.db` (or `AUDIT_DB_PATH` env), selects
every row tagged with the given `cycle_id`, and writes a single JSON
document. Run this **before** `scripts/clean.sh --audit` wipes the DB.

## Fixture shape

```jsonc
{
  "cycle_id": "cycle_20260604_090632_d4333b8a",
  "exported_at": "2026-06-04T15:20:00Z",
  "source_db": "/abs/path/to/.audit_db/audit.db",
  "audit_records": [
    {
      "id": 1, "cycle_id": "...", "parent_id": null,
      "category": "decision", "type": "cycle_started",
      "agent": null, "content": { ... }, "timestamp": "..."
    },
    // ... more rows, ordered by id ASC
  ],
  "harness_trail": [ /* every harness verdict for the cycle */ ],
  "row_counts": { "audit_records": N, "harness_trail": N }
}
```

`content` is the parsed JSON object — not an escaped string. Timestamps
are ISO-formatted. Row ordering matches the original insertion order
(primary key ASC), which is the order the cycle wrote them.

## What a future mock runner consumes from this

A LangGraph mock run wires a patched MCP adapter and a patched LLM
client to the graph, then invokes `build_graph(...).invoke(...)` with
the same initial state the real cycle started from. To make that work,
the runner needs two lookup tables derivable from this fixture:

**1. MCP responses** — derived from `audit_records` rows of type
`observation`. Each `observation.content.result` is the response the
MCP layer returned to the corresponding `tool_call` row (paired by
`parent_id`). Indexing by `(tool_name, args_signature)` reproduces
deterministic MCP behavior.

**2. LLM responses per agent** — derived from `audit_records` rows
where `agent` is one of `system_mapper`, `compute_analyst`,
`data_layer_analyst`, `network_analyst`, `cross_tier_evaluator`.
Specifically:

  - `thought` rows: each is one ReAct-loop LLM completion (carries the
    reasoning text and any tool_uses the LLM chose).
  - `specialist_finding` / `system_mapper_output` /
    `evaluator_record` / `recommendation` rows: the structured output
    of the agent's final LLM call.

For a given agent, the LLM responses to return in order are the rows
written by that agent during the cycle, sorted by `id`. The mock LLM
client returns response\[i\] on the agent's i-th call.

## Replay scope and caveats

The fixture captures **structured outputs**, not raw LLM completions
(prompt text + token-level response). If an agent does post-processing
between the LLM response and the audit-record write, the mock can only
replay the post-processed shape — it can't reproduce the exact raw
completion. For the project's current agents this is sufficient
because every agent uses `with_structured_output(Schema)` (or a tool-
use schema), so the LLM's response IS the structured Pydantic object
the audit row records.

The cycle's MCP responses are already deterministic given the same
inputs (the HF dataset is the source), so a fixture mismatch between
old and new MCP layers would surface immediately as a row-shape
divergence. Run a real cycle and diff against the fixture if you
suspect drift.

## Status of the mock runner itself

The runner (the code that loads a fixture and replays the graph) is
**not in this repo yet**. The fixture is the input; the consumer is a
follow-up. See:

  - `src/agents/mock_llm.py` for the existing static mock-LLM client
    that returns hard-coded responses by call type.
  - `tests/unit/agents/conftest.py::_MockMcp` for the MCP-side mock
    pattern that the fixture-driven version will mirror.

The follow-up is a small piece of glue: a context manager that loads
the fixture, builds the (tool, args) and (agent, index) lookup
tables, and monkey-patches `mcp_adapter.call_tool` and the relevant
LLM client class. Pair it with `build_graph` and `make_initial_state`
and the cycle replays. The fixture this folder holds is the
load-bearing artifact for that work.
