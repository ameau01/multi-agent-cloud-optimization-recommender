"""Integration tests for src/evaluator/eval.py (the simplified CLI).

The CLI accepts two flags: --app-name app-NN and --prediction FILE.
It maps app-NN to the matching scenario rules from eval-set/, scores
the prediction, prints the four-layer verdict, and exits 0/1/2.

These are integration tests (spawn subprocess + read real eval-set/)
per the unit-vs-integration distinction documented in tests/README.md.

Run:
    pytest tests/integration/test_eval_cli.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_CMD = [sys.executable, "-m", "src.evaluator.eval"]


def _run_eval(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        EVAL_CMD + args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


# ============================================================
# Basic CLI shape + error paths
# ============================================================
class TestCliInvocation:
    def test_help_returns_exit_0(self):
        result = _run_eval(["--help"])
        assert result.returncode == 0
        assert "--app-name" in result.stdout
        assert "--prediction" in result.stdout
        assert "app-NN" in result.stdout  # documents the expected format

    def test_missing_required_args_exits_nonzero(self):
        result = _run_eval([])
        assert result.returncode != 0

    def test_missing_prediction_file_exits_2(self, tmp_path):
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(tmp_path / "nonexistent.json"),
        ])
        assert result.returncode == 2
        assert "not found" in result.stderr.lower()

    def test_malformed_prediction_file_exits_2(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not valid json {{{")
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(bad),
        ])
        assert result.returncode == 2
        assert "json" in result.stderr.lower()

    def test_prediction_not_object_exits_2(self, tmp_path):
        not_object = tmp_path / "list.json"
        not_object.write_text("[1, 2, 3]")
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(not_object),
        ])
        assert result.returncode == 2

    def test_invalid_app_name_format_exits_2(self):
        # bare scenario id (no app- prefix) should fail
        result = _run_eval([
            "--app-name", "08",
            "--prediction", str(PROJECT_ROOT / "eval-set/expectations/08.json"),
        ])
        assert result.returncode == 2
        assert "app-NN" in result.stderr

    def test_unknown_app_exits_2(self):
        result = _run_eval([
            "--app-name", "app-99",
            "--prediction", str(PROJECT_ROOT / "eval-set/expectations/08.json"),
        ])
        assert result.returncode == 2
        assert "unknown app" in result.stderr.lower()


# ============================================================
# All-pass case: feed the gold answer as the prediction
# ============================================================
class TestGoldAnswerAllPass:
    def test_app_08_gold_passes_all_layers(self):
        gold_path = PROJECT_ROOT / "eval-set/expectations/08.json"
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(gold_path),
        ])
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "All layers passed." in result.stdout
        assert "app-08" in result.stdout

    def test_app_06_gold_passes_with_short_circuit(self):
        """app-06 is no_issue_found; Mid + Rich short-circuit but Shape
        and Correctness should still pass."""
        gold_path = PROJECT_ROOT / "eval-set/expectations/06.json"
        result = _run_eval([
            "--app-name", "app-06",
            "--prediction", str(gold_path),
        ])
        assert result.returncode == 0
        assert "All layers passed." in result.stdout


# ============================================================
# Discrimination: degraded mocks fail the expected layer
# ============================================================
class TestDiscrimination:
    @pytest.fixture
    def mocks_dir(self):
        return PROJECT_ROOT / "tests/integration/fixtures/mock_predictions"

    def test_bad_correctness_mock_fails_at_correctness(self, mocks_dir):
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(mocks_dir / "scenario_08_bad_correctness.json"),
        ])
        assert result.returncode == 1
        assert "Correctness gate failed" in result.stdout

    def test_bad_mid_mock_fails_at_mid_layer(self, mocks_dir):
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(mocks_dir / "scenario_08_bad_mid.json"),
        ])
        assert result.returncode == 1
        assert "Correctness gate failed" not in result.stdout
        assert "correct but thin" in result.stdout

    def test_bad_rich_mock_fails_at_rich_layer(self, mocks_dir):
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(mocks_dir / "scenario_08_bad_rich.json"),
        ])
        assert result.returncode == 1
        assert "correct but thin" in result.stdout


# ============================================================
# Cross-app mismatch: scoring app-06's gold against app-08's rules
# ============================================================
class TestCrossAppMismatch:
    def test_gold_06_scored_against_app_08_rules_fails(self):
        """Feed app-06's gold (no_issue_found) against app-08's rules
        (issue_found / database). Correctness should fail because the
        finding_type mismatches."""
        gold06 = PROJECT_ROOT / "eval-set/expectations/06.json"
        result = _run_eval([
            "--app-name", "app-08",
            "--prediction", str(gold06),
        ])
        assert result.returncode == 1
        assert "Correctness gate failed" in result.stdout
