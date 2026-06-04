#!/usr/bin/env python3
"""Walk every audit trail and confirm every cited evidence reference resolves.

Run:
    scripts/verify_trace.sh                               # default: sample_runs/traces/
    scripts/verify_trace.sh <dir>                         # custom directory
    uv run python tests/verify_trace.py                   # direct invocation
    uv run python tests/verify_trace.py <dir>             # custom directory

Schema this script targets (the live trace shape produced by
`src/renderer/`):

    {
      "cycle_id": "cycle_<...>",
      "application_id": "app-NN",
      "recommendation_row_id": <int>,
      "recommendation": {composite, reconciliation, reflection},
      "specialist_findings": [
        {
          "id": <int>,
          "agent": "<specialist_name>",
          "content": {"evidence_refs": [<int>, ...], ...},
          "evidence_refs_chain": [{"ref": <int>, "resolved": <bool>, ...}, ...],
        },
        ...
      ],
      "evidence_chain": {
        "<id>": {"id": <int>, "type": "observation"|"specialist_finding", ...},
        ...
      },
      "summary": {
        "unique_refs_cited": <int>,
        "resolved": <int>,
        "dangling": <int>,
        ...
      },
    }

What this script verifies (independently of `summary`):

  1. Every `id` listed in any specialist_finding's `content.evidence_refs`
     resolves to an `evidence_chain` entry. This is the dangling-ref
     contract: a specialist may not cite an observation that doesn't exist.
  2. Every `ref` listed in any specialist_finding's `evidence_refs_chain`
     resolves, and its `resolved` flag is true.
  3. Every entry in `evidence_chain` has a non-empty `cited_by` list —
     evidence_chain is reverse-indexed by the renderer, so an unciteable
     entry would be a renderer bug.
  4. The independently-computed counts (unique_refs_cited, observation_refs,
     specialist_finding_refs, dangling, resolved) match the trace's
     self-reported `summary` block. A mismatch means either the renderer's
     summary is wrong or this verifier is wrong; either way it's a
     contract violation worth surfacing.

  Renderer's counting convention (matched by this verifier):

      unique_refs_cited       == len(evidence_chain)
      observation_refs        == count of entries with type == "observation"
      specialist_finding_refs == count of entries with type == "specialist_finding"
      dangling                == count of specialist-cited refs not in evidence_chain
      resolved                == unique_refs_cited - dangling

What this script does NOT do. It does not re-run the agents. LLM output
is non-deterministic at non-zero temperature, so replay cannot re-derive
the same answer by running the model again. Replay reconstructs what
happened, not what would happen.

Discovery. By default, every file matching `sample_runs/traces/*_trace.json`
is verified. Pass a directory as the first argument to scan a different
tree (used to verify each `integration-test-*/step4_reports/app-*/
trace.json` after a live run).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_TRACES_DIR = (
    Path(__file__).resolve().parent.parent / "sample_runs" / "traces"
)


def verify_trace(trace: dict) -> tuple[bool, list[str], dict[str, int]]:
    """Verify one trace.

    Returns (ok, log_lines, counts) where counts is the independently
    computed {unique_refs_cited, resolved, dangling}.
    """
    log: list[str] = []
    ok = True

    def step(msg: str, success: bool = True) -> None:
        nonlocal ok
        prefix = "  ✓" if success else "  ✗"
        log.append(f"{prefix} {msg}")
        if not success:
            ok = False

    # Build the universe of resolvable ids from evidence_chain.
    # Keys are stringified ints; normalize to int for comparison.
    universe: set[int] = set()
    observation_count = 0
    specialist_finding_count = 0
    evidence_chain = trace.get("evidence_chain", {})

    for key, entry in evidence_chain.items():
        try:
            universe.add(int(key))
        except (TypeError, ValueError):
            step(f"evidence_chain key {key!r} is not an int", success=False)
            continue
        # Cross-check: entry['id'] should agree with the key.
        if isinstance(entry, dict) and "id" in entry:
            if str(entry["id"]) != str(key):
                step(
                    f"evidence_chain[{key!r}].id={entry['id']} disagrees "
                    f"with key",
                    success=False,
                )
        # Tally by type for summary cross-check.
        etype = entry.get("type") if isinstance(entry, dict) else None
        if etype == "observation":
            observation_count += 1
        elif etype == "specialist_finding":
            specialist_finding_count += 1
        # cited_by must be non-empty: evidence_chain is reverse-indexed,
        # so an entry with no citer should never appear here.
        if isinstance(entry, dict) and not entry.get("cited_by"):
            step(
                f"evidence_chain[{key!r}] has empty cited_by — "
                f"renderer reverse-index would not have surfaced it",
                success=False,
            )

    log.append(
        f"  evidence_chain universe: {len(universe)} ids "
        f"(observations={observation_count}, "
        f"specialist_findings={specialist_finding_count})"
    )

    # Walk every specialist ref and check it resolves.
    dangling: set[int] = set()

    specialist_refs: set[int] = set()
    specialist_findings = trace.get("specialist_findings", [])
    for sf in specialist_findings:
        agent = sf.get("agent", "<unknown>")
        finding_id = sf.get("id", "<no-id>")

        # content.evidence_refs (the substantive citation list)
        content_refs = sf.get("content", {}).get("evidence_refs", []) or []
        for ref in content_refs:
            specialist_refs.add(ref)
            if ref not in universe:
                dangling.add(ref)
                step(
                    f"finding[id={finding_id}, agent={agent}]."
                    f"content.evidence_refs[{ref!r}] is dangling",
                    success=False,
                )

        # evidence_refs_chain (renderer-side enrichment with resolved flags)
        for entry in sf.get("evidence_refs_chain", []) or []:
            ref = entry.get("ref")
            if ref is None:
                continue
            specialist_refs.add(ref)
            if ref not in universe:
                dangling.add(ref)
                step(
                    f"finding[id={finding_id}, agent={agent}]."
                    f"evidence_refs_chain entry ref={ref!r} is dangling",
                    success=False,
                )
            elif entry.get("resolved") is False:
                step(
                    f"finding[id={finding_id}, agent={agent}]."
                    f"evidence_refs_chain ref={ref!r} present in universe "
                    f"but flagged resolved=false",
                    success=False,
                )

    if not dangling:
        step(
            f"all {len(specialist_refs)} unique refs cited by specialists "
            f"resolve in evidence_chain"
        )

    # Match the renderer's counting convention (see module docstring).
    counts = {
        "unique_refs_cited": len(universe),
        "observation_refs": observation_count,
        "specialist_finding_refs": specialist_finding_count,
        "resolved": len(universe) - len(dangling),
        "dangling": len(dangling),
    }

    # Cross-check against trace's self-reported summary.
    summary = trace.get("summary", {})
    for key in (
        "unique_refs_cited",
        "observation_refs",
        "specialist_finding_refs",
        "resolved",
        "dangling",
    ):
        reported = summary.get(key)
        computed = counts[key]
        if reported is None:
            step(f"summary.{key} missing from trace", success=False)
        elif reported != computed:
            step(
                f"summary.{key}={reported} disagrees with independently "
                f"computed {computed}",
                success=False,
            )
        else:
            log.append(f"  ✓ summary.{key}={reported} agrees with verifier")

    return ok, log, counts


def discover_traces(traces_dir: Path) -> list[Path]:
    """Return every *_trace.json or trace.json under traces_dir, sorted.

    Supports both layouts:
      - sample_runs/traces/scenario_NN_trace.json
      - integration-test-*/step4_reports/app-NN/trace.json
    """
    by_pattern: set[Path] = set()
    by_pattern.update(traces_dir.glob("*_trace.json"))
    by_pattern.update(traces_dir.glob("**/trace.json"))
    return sorted(by_pattern)


def main() -> int:
    if len(sys.argv) > 1:
        traces_dir = Path(sys.argv[1]).resolve()
    else:
        traces_dir = DEFAULT_TRACES_DIR

    if not traces_dir.exists():
        print(f"Directory not found: {traces_dir}", file=sys.stderr)
        return 2

    trace_paths = discover_traces(traces_dir)
    if not trace_paths:
        print(f"No trace files found under {traces_dir}", file=sys.stderr)
        return 2

    overall_ok = True
    per_trace_results: list[tuple[Path, bool, dict[str, int]]] = []

    for path in trace_paths:
        try:
            trace = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"\n{'=' * 70}\n  {path}\n{'=' * 70}")
            print(f"  ✗ invalid JSON: {exc}")
            overall_ok = False
            per_trace_results.append((path, False, {}))
            continue

        print()
        print("=" * 70)
        rel = (
            path.relative_to(traces_dir.parent)
            if path.is_relative_to(traces_dir.parent)
            else path
        )
        print(f"  Auditing {rel}")
        print("=" * 70)
        ok, log, counts = verify_trace(trace)
        for line in log:
            print(line)
        per_trace_results.append((path, ok, counts))
        if not ok:
            overall_ok = False

    print()
    print("=" * 70)
    print(f"  Summary  ({traces_dir})")
    print("=" * 70)
    for path, ok, counts in per_trace_results:
        marker = "✓" if ok else "✗"
        cited = counts.get("unique_refs_cited", "?")
        dangling = counts.get("dangling", "?")
        print(f"  {marker} {path.name}  unique={cited} dangling={dangling}")
    print()

    if overall_ok:
        print("  ✓ PASS. Every cited evidence ref resolves in every trace,")
        print("        and every trace's self-reported summary agrees with")
        print("        an independent walk.")
        print()
        print("  Note: replay reconstructs the recorded reasoning. It does")
        print("        not re-derive answers by re-running the model. LLM")
        print("        output is non-deterministic at non-zero temperature.")
        return 0
    else:
        print("  ✗ FAIL. At least one reference is dangling or one summary")
        print("        block disagrees with the independent walk. The")
        print("        trace(s) above marked with ✗ do not satisfy the")
        print("        auditability contract.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
