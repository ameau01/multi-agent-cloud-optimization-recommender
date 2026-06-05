"""Headless replay-graph runner — drives the agent_replay graph against
the app-08 cycle fixture and prints the cycle_id that landed in the
audit DB.

This is what the hermetic demo container (`docker compose up demo`)
invokes for Stage 1, before scripts/render_recommendation.sh and
scripts/render_evidence_trace.sh render the artifacts for the user.

The replay reconstructs the recorded reasoning chain from a real prior
cycle, deterministically, without making any LLM or MCP calls. No API
key, no Hugging Face download, no network needed.

Usage:
    python tests/run_replay.py [--fixture PATH] [--app APP-NN] [--cycle-id ID]

Args:
    --fixture     Path to a cycle-export fixture JSON. Default:
                  tests/integration/agents/fixtures/cycle_app08.json
    --app         Application id to invoke the graph with. Default: app-08.
    --cycle-id    Cycle id to stamp on the replayed records. Default:
                  cycle_replay_<UTC ts>_<8hex>.

Env:
    AUDIT_DB_PATH must be set to the SQLite path where the replayed
    audit records should land. The downstream render scripts read from
    the same env var, so passing the same path here lets them find the
    cycle. If unset, falls back to .audit_db/audit.db.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _new_cycle_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"cycle_replay_{ts}_{secrets.token_hex(4)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=PROJECT_ROOT
        / "tests/integration/agents/fixtures/cycle_app08.json",
        help="Cycle-export fixture JSON.",
    )
    parser.add_argument("--app", default="app-08", help="Application id.")
    parser.add_argument(
        "--cycle-id",
        default=None,
        help="Cycle id to stamp on replayed records. Generated if omitted.",
    )
    args = parser.parse_args(argv)

    if not args.fixture.exists():
        print(f"ERROR: fixture not found: {args.fixture}", file=sys.stderr)
        return 2

    # Lazy import so --help works without a heavy dependency tree.
    from src.agents.replay import _load_fixture, build_replay_graph
    from src.audit.store import AuditStore
    from src.common.init import ensure_env_loaded, get_audit_store
    from src.harnesses.action import ActionHarness
    from src.harnesses.input import InputHarness

    ensure_env_loaded()

    # get_audit_store honors AUDIT_DB_PATH from env (or the default).
    # The container Dockerfile sets it to a writable path.
    store: AuditStore = get_audit_store()
    store.initialize()

    fixture = _load_fixture(args.fixture)
    graph = build_replay_graph(
        store=store,
        input_harness=InputHarness(store),
        action_harness=ActionHarness(store),
        fixture=fixture,
    )

    cycle_id = args.cycle_id or _new_cycle_id()
    print(f"Invoking replay graph: app={args.app} cycle_id={cycle_id}",
          file=sys.stderr)
    final_state = graph.invoke({"application_id": args.app, "cycle_id": cycle_id})

    # The replay_init node may mint a fresh cycle_id (when the DB is empty
    # and the passed-in id is treated as "stale"). The rows actually written
    # use the minted id, not the one we passed. Read it back from final_state
    # so the bash wrapper's Stage 2 looks up the right id. Fallback to the
    # passed-in id only if final_state somehow lacks it.
    actual_cycle_id = final_state.get("cycle_id") or cycle_id
    if actual_cycle_id != cycle_id:
        print(f"  (replay_init minted fresh cycle_id={actual_cycle_id})",
              file=sys.stderr)

    # Stdout = cycle_id only, so a bash wrapper can capture it cleanly.
    print(actual_cycle_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
