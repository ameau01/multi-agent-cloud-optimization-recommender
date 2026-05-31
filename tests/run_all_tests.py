#!/usr/bin/env python3
"""Default test runner.

By default this runs only the unit tests (fast: under 1 second). Pass
--integration or --all to also run the integration tests (slightly
slower; still well under 1 second on this project but the cost grows
with dataset size).

Usage:
    python tests/run_all_tests.py            # unit only (default, fast)
    python tests/run_all_tests.py --integration   # unit + integration
    python tests/run_all_tests.py --all      # alias for --integration
    python tests/run_all_tests.py --integration-only  # integration only
    python tests/run_all_tests.py -v --all   # verbose, both

Any extra args are passed to pytest.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    args = sys.argv[1:]

    run_integration = (
        "--integration" in args or "--all" in args
        or "--integration-only" in args
    )
    integration_only = "--integration-only" in args

    # Strip our custom flags before forwarding to pytest
    pytest_args = [
        a for a in args
        if a not in ("--integration", "--all", "--integration-only")
    ]

    if integration_only:
        targets = ["tests/integration/"]
    elif run_integration:
        targets = ["tests/unit/", "tests/integration/"]
    else:
        targets = ["tests/unit/"]

    label = "+".join(t.split("/")[-2] for t in targets)
    print(f"Running tests: {label}")

    cmd = [sys.executable, "-m", "pytest", *targets, *pytest_args]
    sys.exit(subprocess.call(cmd, cwd=PROJECT_ROOT))


if __name__ == "__main__":
    main()
