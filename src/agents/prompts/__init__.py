"""Agent prompts.

Each agent's system prompt lives as a plain text file in this folder.
Files are read once at process start (cached after that) — they're
content, not code, so editing a prompt is a git-diff-friendly change
that doesn't require touching the agent class.

Usage:

    from src.agents.prompts import load_prompt
    text = load_prompt("compute_analyst")  # reads compute_analyst.txt
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Read a prompt file by name (without .txt extension). Cached after
    first read so re-loads are free in a long-lived process.

    Raises FileNotFoundError if no such prompt exists — the caller is
    expected to know its agent's prompt name at construction time, so
    a missing file is a config error, not a runtime concern.
    """
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")
