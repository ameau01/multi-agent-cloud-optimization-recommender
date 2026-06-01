"""Render a full Composite into report.md and trace.json.

Usage:
    python -m src.renderer \\
        --composite sample_runs/scenario_08/raw_recommendation.json \\
        --out-report sample_runs/reports/scenario_08_report.md \\
        --out-trace  sample_runs/traces/scenario_08_trace.json

Either output flag is optional; pass only the one you want regenerated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..models.composite import Composite
from . import render_report, render_trace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--composite", required=True, type=Path,
        help="Path to a full composite JSON file."
    )
    parser.add_argument(
        "--out-report", type=Path, default=None,
        help="Write the rendered report.md here.",
    )
    parser.add_argument(
        "--out-trace", type=Path, default=None,
        help="Write the rendered trace.json here.",
    )
    args = parser.parse_args()

    if not args.composite.exists():
        print(f"ERROR: composite not found: {args.composite}", file=sys.stderr)
        return 2
    if args.out_report is None and args.out_trace is None:
        print("ERROR: pass at least one of --out-report or --out-trace",
              file=sys.stderr)
        return 2

    composite = Composite.model_validate_json(args.composite.read_text())

    if args.out_report is not None:
        args.out_report.parent.mkdir(parents=True, exist_ok=True)
        args.out_report.write_text(render_report(composite))
        print(f"wrote {args.out_report}")

    if args.out_trace is not None:
        args.out_trace.parent.mkdir(parents=True, exist_ok=True)
        args.out_trace.write_text(render_trace(composite))
        print(f"wrote {args.out_trace}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
