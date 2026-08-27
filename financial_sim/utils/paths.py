"""Path utilities for project structure."""
from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the project root directory."""
    # Walk up from this file's location until we find pyproject.toml
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    msg = "Could not find project root (no pyproject.toml found)"
    raise FileNotFoundError(msg)


def data_dir() -> Path:
    """Return the data directory, creating if needed."""
    path = project_root() / "data"
    path.mkdir(exist_ok=True)
    return path


def snapshots_dir() -> Path:
    """Return the snapshots directory, creating if needed."""
    path = project_root() / "snapshots"
    path.mkdir(exist_ok=True)
    return path


def reports_dir() -> Path:
    """Return the reports directory, creating if needed."""
    path = project_root() / "reports"
    path.mkdir(exist_ok=True)
    return path


def scenarios_dir() -> Path:
    """Return the scenarios directory."""
    return project_root() / "scenarios"
