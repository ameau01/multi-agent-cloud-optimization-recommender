"""Pytest fixtures for live-judge tests.

These tests actually call an LLM provider (OpenAI or Anthropic). They
are gated on at least one of OPENAI_API_KEY or ANTHROPIC_API_KEY being
present in the environment (loaded from .env via JudgeClient). When
both keys are set, OpenAI is preferred; override with
LLM_JUDGE_PROVIDER=anthropic in .env if you want to test the
Anthropic path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluator.judge_client import JudgeClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_SET_DIR = PROJECT_ROOT / "eval-set"


@pytest.fixture(scope="session")
def live_judge_or_skip():
    """Return a real JudgeClient. Skip the test if no API key."""
    if not JudgeClient.is_available():
        pytest.skip("No LLM API key set (OPENAI_API_KEY or ANTHROPIC_API_KEY); "
                    "live-judge tests skipped")
    return JudgeClient()


@pytest.fixture(scope="session")
def all_golds() -> dict[str, dict]:
    """Load every gold answer from eval-set/expectations/."""
    out = {}
    for path in sorted((EVAL_SET_DIR / "expectations").glob("*.json")):
        sid = path.stem
        out[sid] = json.loads(path.read_text())
    return out
