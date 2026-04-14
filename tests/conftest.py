"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def executor_session() -> Path:
    return FIXTURES_DIR / "executor_session"


@pytest.fixture
def planner_session() -> Path:
    return FIXTURES_DIR / "planner_session"
