"""Utility functions."""

from pathlib import Path

def ensure_dir(path: Path) -> Path:
    """Ensure dir exists, if not create it."""
    path.mkdir(parents=True, exist_ok=True)
    return path

