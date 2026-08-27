"""Shared pytest fixtures for all tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from financial_sim.config import SimConfig
from financial_sim.utils.logging import setup_logging
from financial_sim.utils.paths import project_root, scenarios_dir


@pytest.fixture(scope="session", autouse=True)
def _setup_logging() -> None:
    """Configure logging once per test session."""
    setup_logging(level="WARNING")  # Quiet by default


@pytest.fixture
def default_config() -> SimConfig:
    """Default simulation config for tests."""
    return SimConfig.default()


@pytest.fixture
def small_config() -> SimConfig:
    """Small fast-running config for unit tests."""
    return SimConfig(
        n_households=10,
        n_firms_per_sector=2,
        sectors=["consumer_goods"],
        n_banks=1,
        n_ticks=12,
    )


@pytest.fixture
def project_root_path() -> Path:
    """Path to the project root."""
    return project_root()


@pytest.fixture
def scenarios_path() -> Path:
    """Path to the scenarios directory."""
    return scenarios_dir()
