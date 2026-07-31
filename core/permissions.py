"""Email -> role permissions, stored in the shared Google Sheet.

Identity (who you are) comes from Google sign-in; this module only holds
authorisation (what you may do), keyed by email address. There are no
passwords here or anywhere in the app - Google holds the only password.

Storage: a "Users" worksheet in the same Google Sheet used for field
data, so the allowlist PERSISTS on Streamlit Cloud (the local filesystem
is wiped on every restart). Falls back to a local CSV for development.

Roles:
    owner   - full access + the People & Access admin panel
    analyst - full app access, no user admin
    viewer  - read-only use of the app
"""

import time
from datetime import date

import pandas as pd

from config import PROJECT_ROOT

ROLES = ("owner", "analyst", "viewer")

USERS_SHEET = "Users"
USERS_COLUMNS = ["email", "name", "role", "active", "added_at"]
CSV_PATH = PROJECT_ROOT / "data" / "permissions.csv"

# Light cache so we don't hit the Sheet on every Streamlit rerun.
_CACHE = {"rows": None, "ts": 0.0}
_TTL = 20.0


def _clean(email):
    return (email or "").strip().lower()


def _truthy(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return True
    return str(v).strip().lower() in ("1", "true", "yes", "y", "")


def _s(v):
    """Coerce a cell to a clean string ('' for NaN/None)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _read():
    from core import sheets
    if sheets.is_enabled():
        df = sheets.read_records(USERS_SHEET, USERS_COLUMNS)
    elif CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH)
    else:
        df = pd.DataFrame(columns=USERS_COLUMNS)

    rows = []
    for _, r in df.iterrows():
        email = _clean(_s(r.get("email")))
        if not email or "@" not in email:
            continue
        role = (_s(r.get("role")) or "viewer").lower()
        rows.append({
            "email": email,
            "name": _s(r.get("name")),
            "role": role if role in ROLES else "viewer",
            "active": _truthy(r.get("active", 1)),
            "added_at": _s(r.get("added_at")),
        })
    return rows


def _load(force=False):
    now = time.time()
    if not force and _CACHE["rows"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["rows"]
    _CACHE["rows"] = _read()
    _CACHE["ts"] = now
    return _CACHE["rows"]


def _save(rows):
    from core import sheets
    out = [{**r, "active": 1 if r["active"] else 0} for r in rows]
    if sheets.is_enabled():
        sheets.overwrite(USERS_SHEET, USERS_COLUMNS, out)
    else:
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(out, columns=USERS_COLUMNS).to_csv(CSV_PATH, index=False)
    _CACHE["rows"] = rows
    _CACHE["ts"] = time.time()


def ensure_owner(email, name=""):
    """Guarantee an address always exists as an active owner, so the
    admin can never lock themselves out. Called at startup."""
    email = _clean(email)
    if not email:
        return
    rows = _load(force=True)
    for r in rows:
        if r["email"] == email:
            if r["role"] != "owner" or not r["active"]:
                r["role"] = "owner"
                r["active"] = True
                _save(rows)
            return
    rows.append({"email": email, "name": name, "role": "owner",
                 "active": True, "added_at": date.today().isoformat()})
    _save(rows)


def get(email):
    """Return the active user's record dict, or None if no access."""
    email = _clean(email)
    if not email:
        return None
    for r in _load():
        if r["email"] == email and r["active"]:
            return dict(r)
    return None


def list_all():
    return [dict(r) for r in sorted(_load(),
                                    key=lambda x: x["email"])]


def upsert(email, role="viewer", active=True, name=""):
    email = _clean(email)
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if role not in ROLES:
        raise ValueError("Role must be one of " + ", ".join(ROLES) + ".")
    rows = _load(force=True)
    for r in rows:
        if r["email"] == email:
            r["role"] = role
            r["active"] = bool(active)
            if name:
                r["name"] = name
            _save(rows)
            return
    rows.append({"email": email, "name": name, "role": role,
                 "active": bool(active), "added_at": date.today().isoformat()})
    _save(rows)


def remove(email):
    email = _clean(email)
    rows = [r for r in _load(force=True) if r["email"] != email]
    _save(rows)
