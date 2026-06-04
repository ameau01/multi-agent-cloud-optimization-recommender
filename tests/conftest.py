"""Root pytest conftest.

Runs once at test-session start, BEFORE any test module imports
langchain / langgraph / langsmith. The job here is small and load-bearing:

  - Force LangSmith tracing OFF for the test run.

    Tests that invoke `run_cycle()` or build the graph would otherwise
    cause every graph step to fire a `Run.post()` HTTPS call to
    `api.smith.langchain.com`. With no real network (sandbox / offline /
    intermittent CI / locked-down workstation), those calls don't error
    fast — they wait on the OS-level connect timeout, which can stall
    the suite for tens of seconds per test. Cumulatively the suite
    appears to hang.

    We force-override instead of `setdefault` because `uv run` (and
    other dev launchers) auto-load `.env` into the environment before
    pytest starts. With `LANGCHAIN_TRACING_V2=true` in .env (the dev
    default for `langgraph dev`), `setdefault` would honor it and the
    hang would persist. Tests should never depend on LangSmith — debug
    a graph interactively, not under pytest. If you really need a
    traced test run, edit this line locally for that session.

Anything that must happen before `src/` imports (path setup, env mocks,
debug-noise suppression) belongs here, not in per-package conftests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force LangSmith tracing off. See module docstring for the why.
os.environ["LANGCHAIN_TRACING_V2"] = "false"
# Belt-and-suspenders: even with tracing disabled, langchain still
# reads LANGSMITH_API_KEY in places. Clear it so any stray phone-home
# path returns a "no auth" no-op instead of hanging on a connect.
os.environ.pop("LANGSMITH_API_KEY", None)

# Clear LLM provider keys so unit/integration tests that invoke
# `run_cycle()` with mocked MCP don't fall through to a real
# Anthropic / OpenAI call from a specialist or the cross-tier evaluator.
#
# Without this, on a developer machine with API keys in `.env`, the
# graph would dispatch specialists, each specialist would build a real
# LLM client and POST to api.anthropic.com / api.openai.com — those
# calls run for 30-90 s each, multiplied across every test that
# invokes the runner. Total wall time grows from ~12 s to ~10+ min,
# and some tests appear to hang on the TLS handshake.
#
# Specialists raise a clean "ANTHROPIC_API_KEY is not set" error when
# the key is missing. The orchestrator's try/finally catches that and
# the cycle terminates with `final_status="failed"`. Tests that assert
# on terminal state should be tolerant of "failed" or be specifically
# skipped — the runner tests already are.
#
# Tests that genuinely need a live LLM key live under tests/judge_live/
# and are excluded from the default sweep. They build their own
# JudgeClient and check `JudgeClient.is_available()` to opt-in.
for _key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_key, None)

# CRITICAL: stop `ensure_env_loaded()` from reloading .env and restoring
# the keys we just cleared. The function is idempotent — it loads .env
# exactly once per process, gated by its module-level `_env_loaded` flag.
# By flipping the flag to True here, every subsequent call (from
# `run_cycle`, `get_audit_store`, etc.) becomes a no-op. `dotenv` with
# its default `override=False` would otherwise see that
# `ANTHROPIC_API_KEY` is unset (because we popped it) and helpfully
# restore it from .env — re-introducing the hang we just defended
# against.
#
# Done as an import-then-mutate pair rather than a monkeypatch fixture
# because pytest's monkeypatch operates at function/test scope; this
# needs session scope and to run before any test-module import.
from src.common import init as _init  # noqa: E402
_init._env_loaded = True
