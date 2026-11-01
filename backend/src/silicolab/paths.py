"""Writable macOS application paths, separate from bundle resources."""

import json
import os
from pathlib import Path
import sys

from silicolab.branding import APP_NAME, DATABASE_FILENAME


def project_directory() -> Path:
    """Source checkout root; package installation can override writable paths."""
    return Path(__file__).resolve().parents[3]


def browser_database() -> Path:
    override = os.environ.get("SILICOLAB_DB")
    if override:
        return Path(override).expanduser()
    root = project_directory()
    if (root / "backend" / "pyproject.toml").exists():
        return root / "data" / DATABASE_FILENAME
    return application_directory() / DATABASE_FILENAME


def frontend_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "frontend" / "dist"
    override = os.environ.get("SILICOLAB_FRONTEND_DIST")
    if override:
        return Path(override).expanduser().resolve()
    return project_directory() / "frontend" / "dist"


def application_directory() -> Path:
    override = os.environ.get("SILICOLAB_APP_DATA")
    directory = Path(override).expanduser() if override else Path.home() / "Library" / "Application Support" / APP_NAME
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def read_preferences(directory: Path) -> dict:
    path = directory / "desktop.json"
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_preferences(directory: Path, preferences: dict):
    path = directory / "desktop.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(preferences, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
