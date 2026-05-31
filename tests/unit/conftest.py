"""Pytest fixtures for unit tests.

Unit tests use crafted inputs (not real gold answers or scenario data) to
exercise individual src/ functions in isolation. This conftest sets up the
import path so `from src.evaluator.tiers import ...` works.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
