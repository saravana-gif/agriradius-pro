"""Project save/open - .agr.json files under data/projects/.

A project captures everything needed to reproduce an analysis:
location, radius, year, basemap, layer visibility and results.
"""

import json
import re
from datetime import datetime

from config import PROJECT_ROOT, APP_VERSION

PROJECTS_DIR = PROJECT_ROOT / "data" / "projects"

EXTENSION = ".agr.json"

# Session keys captured in a project file
SESSION_KEYS = [
    "lat",
    "lon",
    "radius",
    "year",
    "basemap",
    "input_method",
    "search_location",
    "layer_visibility",
    "results",
]


def _safe_name(name):
    """Make a filesystem-safe project name."""
    name = re.sub(r"[^\w\- ]", "", name).strip()
    return re.sub(r"\s+", "_", name)


def save_project(name, state):
    """Write a project file from a session-state mapping. Returns Path."""

    safe = _safe_name(name)

    if not safe:
        raise ValueError("Project name is empty or invalid.")

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "project_name": name,
        "app_version": APP_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
    }

    for key in SESSION_KEYS:
        if key in state:
            data[key] = state[key]

    path = PROJECTS_DIR / f"{safe}{EXTENSION}"

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return path


def list_projects():
    """Return saved project names (newest first)."""

    if not PROJECTS_DIR.exists():
        return []

    files = sorted(
        PROJECTS_DIR.glob(f"*{EXTENSION}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return [f.name[: -len(EXTENSION)] for f in files]


def load_project(name):
    """Read a project file and return its dict."""

    path = PROJECTS_DIR / f"{_safe_name(name)}{EXTENSION}"

    if not path.exists():
        raise FileNotFoundError(f"Project not found: {name}")

    return json.loads(path.read_text(encoding="utf-8"))


def apply_project(data, state):
    """Copy project values into a session-state mapping."""

    for key in SESSION_KEYS:
        if key in data:
            state[key] = data[key]