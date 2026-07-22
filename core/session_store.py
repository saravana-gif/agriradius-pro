"""Remember the last-used location across app restarts.

Stores lat/lon/radius/year/place in data/last_session.json so the
app reopens where the user left off instead of the hardcoded
default.
"""

import json

from config import PROJECT_ROOT

STORE_PATH = PROJECT_ROOT / "data" / "last_session.json"

FIELDS = ["lat", "lon", "radius", "year", "search_location", "basemap"]


def save_last(state):
    """Persist the current location fields from a session-state map."""

    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)

        data = {f: state[f] for f in FIELDS if f in state}

        STORE_PATH.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        # Persistence is best-effort; never break the app over it.
        pass


def load_last():
    """Return the saved location dict, or {} if none/unreadable."""

    if not STORE_PATH.exists():
        return {}

    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
