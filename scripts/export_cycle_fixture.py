#!/usr/bin/env python3
"""Export every row of a single audit cycle to a JSON fixture.

Reads the audit DB at .audit_db/audit.db (or AUDIT_DB_PATH env if set),
selects every row tagged with the given cycle_id across the three
tables (audit_records, harness_trail, operations), and writes them
as one JSON document to the path passed via --out.

The fixture is the ground-truth shape a future replay test will
assert against. It captures the cycle's structured outputs — the
analyses, decisions, findings, harness verdicts — but not the raw
LLM call signatures (those are not stored in the audit DB by design).
A subsequent replay-test runner can use this fixture as the
expected state after a re-run that mocks LLM calls to return the
same structured outputs the agents produced here.

Usage:
    python scripts/export_cycle_fixture.py \\
        --cycle cycle_20260604_090632_d4333b8a \\
        --out tests/integration/agents/fixtures/cycle_app08.json

Schema of the output document:
    {
      "cycle_id": "cycle_...",
      "exported_at": "ISO timestamp",
      "audit_records": [ {row dict}, ... ],   # ordered by id ASC
      "harness_trail": [ {row dict}, ... ],   # ordered by id ASC
      "operations":    [ {row dict}, ... ],   # ordered by id ASC
      "row_counts":    {
          "audit_records": N,
          "harness_trail": N,
          "operations":    N
      }
    }

Each row dict mirrors the SQL columns 1:1. `content` is the parsed JSON
object (not the raw string). `timestamp` is ISO-formatted.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_dicts(
    rows: list[sqlite3.Row],
    *,
    json_columns: tuple[str, ...] = ("content",),
    datetime_columns: tuple[str, ...] = ("timestamp",),
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        # Parse the JSON `content` column so the fixture is a single
        # well-formed JSON document, not a JSON containing escaped JSON.
        for col in json_columns:
            if col in d and isinstance(d[col], str):
                try:
                    d[col] = json.loads(d[col])
                except json.JSONDecodeError:
                    # Leave it as a string if it's not parseable — better
                    # to round-trip than to lose data on a malformed row.
                    pass
        # Normalize datetimes to ISO strings.
        for col in datetime_columns:
            if col in d and d[col] is not None:
                # sqlite returns timestamps as strings already; normalize
                # if it's a datetime object.
                if isinstance(d[col], datetime):
                    d[col] = d[col].isoformat()
        out.append(d)
    return out


def export_cycle(
    cycle_id: str,
    out_path: Path,
    db_path: str,
) -> dict[str, int]:
    """Export one cycle to `out_path`. Returns row counts per table."""
    if not Path(db_path).exists():
        sys.exit(f"audit DB not found at {db_path}")

    conn = _connect(db_path)
    try:
        ar = conn.execute(
            "SELECT * FROM audit_records WHERE cycle_id = ? ORDER BY id ASC",
            (cycle_id,),
        ).fetchall()
        ht = conn.execute(
            "SELECT * FROM harness_trail WHERE cycle_id = ? ORDER BY id ASC",
            (cycle_id,),
        ).fetchall()
        # operations keys on target_cycle_id rather than cycle_id (post-hoc
        # ops over a completed cycle).
        ops = conn.execute(
            "SELECT * FROM operations WHERE target_cycle_id = ? ORDER BY id ASC",
            (cycle_id,),
        ).fetchall()
    finally:
        conn.close()

    if not ar and not ht and not ops:
        sys.exit(f"no rows found for cycle_id={cycle_id!r}; nothing to export")

    payload = {
        "cycle_id": cycle_id,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "source_db": str(Path(db_path).resolve()),
        "audit_records": _rows_to_dicts(ar),
        "harness_trail": _rows_to_dicts(ht),
        "operations":    _rows_to_dicts(ops),
        "row_counts": {
            "audit_records": len(ar),
            "harness_trail": len(ht),
            "operations":    len(ops),
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return payload["row_counts"]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export an audit cycle to a JSON fixture file.",
    )
    p.add_argument(
        "--cycle",
        required=True,
        help="cycle_id to export (e.g. cycle_20260604_090632_d4333b8a)",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output JSON file path",
    )
    p.add_argument(
        "--db",
        default=os.environ.get("AUDIT_DB_PATH", ".audit_db/audit.db"),
        help="path to the audit SQLite DB "
             "(default: $AUDIT_DB_PATH or .audit_db/audit.db)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    counts = export_cycle(args.cycle, args.out, args.db)
    print(f"Exported cycle {args.cycle!r} to {args.out}")
    print(f"  audit_records: {counts['audit_records']} rows")
    print(f"  harness_trail: {counts['harness_trail']} rows")
    print(f"  operations:    {counts['operations']} rows")


if __name__ == "__main__":
    main()
