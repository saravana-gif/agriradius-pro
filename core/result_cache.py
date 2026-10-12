"""Saved analysis results: re-open an area instantly, refresh on demand.

WHY
---
Every Earth Engine result was cached only in Streamlit's memory, which
is wiped whenever the app restarts - each deploy, and whenever the
1 GB box runs short of memory. So an area analysed yesterday was
recomputed from scratch today (village insights alone: 1-3 min).

This keeps a copy of each finished STATS result on disk
(data/store/analysis_cache.sqlite - gitignored, survives deploys).
Asking for the same area again returns the saved copy at once. The
user can "Refresh with latest data" to recompute everything for the
area; that refresh then replaces the saved copies.

WHAT IS AND IS NOT SAVED
------------------------
- Saved: numbers, tables, dicts (area stats, insights, time series).
- Never saved: map tile URLs (Earth Engine tokens expire within hours),
  Earth Engine objects, None, and empty results - an empty answer is
  more often a throttled/failed call than a real "nothing here", and
  saving it would pin the failure.
- The key includes rounded location (4 dp = ~11 m), every argument,
  the compute-quality profile (it changes the numbers) and the app
  version (detector changes invalidate old answers).

Usage - put it ABOVE st.cache_data so the memory cache still serves
repeat reruns and the disk only fills the gap after a restart:

    @saved_result()
    @st.cache_data(show_spinner="Measuring maize area...")
    def maize_stats(lat, lon, radius_km, year): ...
"""

import datetime
import functools
import hashlib
import json
import logging
import pickle
import random
import sqlite3
import zlib
from contextlib import closing, contextmanager

import pandas as pd
import streamlit as st

from config import APP_VERSION, PROJECT_ROOT

log = logging.getLogger(__name__)

DB_PATH = PROJECT_ROOT / "data" / "store" / "analysis_cache.sqlite"
KEEP_DAYS = 180              # unused entries older than this are pruned
MAX_PAYLOAD = 20 * 1024 ** 2  # don't save anything bigger than 20 MB

# Current-year analyses use a rolling 12-month satellite window, so
# new imagery keeps arriving; flag those as stale after this many days.
# Completed past years do not change.
STALE_DAYS_CURRENT_YEAR = 7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    key         TEXT PRIMARY KEY,
    fn          TEXT NOT NULL,
    area        TEXT NOT NULL,   -- "lat,lon,radius" rounded
    args        TEXT NOT NULL,
    created_at  TEXT NOT NULL,   -- UTC ISO
    used_at     TEXT NOT NULL,
    payload     BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS results_area ON results (area);
"""


@contextmanager
def _connect():
    """Short-lived connection: commit on success, always close."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(DB_PATH), timeout=10)) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(_SCHEMA)
        with con:
            yield con


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _norm(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return repr(v)


def area_key(lat, lon, radius):
    return f"{round(float(lat), 4)},{round(float(lon), 4)},{float(radius)}"


def _quality():
    try:
        from core.compute import current
        return current()
    except Exception:
        return "Balanced"


def _key(name, args, kwargs):
    raw = json.dumps([name, _norm(list(args)),
                      {k: _norm(v) for k, v in sorted(kwargs.items())},
                      _quality(), APP_VERSION], default=repr)
    return hashlib.sha1(raw.encode()).hexdigest(), raw


def _has_ee(obj, depth=0):
    """True if obj holds an Earth Engine object anywhere we can see."""
    if depth > 4:
        return False
    mod = type(obj).__module__ or ""
    if mod == "ee" or mod.startswith("ee."):
        return True
    if isinstance(obj, dict):
        return any(_has_ee(v, depth + 1) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_has_ee(v, depth + 1) for v in obj[:50])
    return False


def _worth_saving(val):
    if val is None or _has_ee(val):
        return False
    if isinstance(val, (pd.DataFrame, pd.Series)):
        return not val.empty
    if isinstance(val, (dict, list, tuple)):
        return len(val) > 0
    return True


# ------------------------------------------------- session bookkeeping

def _ss():
    try:
        return st.session_state
    except Exception:
        return {}


def _note_hit(area, name, created_at, key):
    """Record that a result on screen came from an earlier visit -
    unless this session computed it itself a moment ago."""
    try:
        if key in _ss().get("_fresh_keys", set()):
            return
        hits = _ss().setdefault("_saved_hits", {})
        hits.setdefault(area, {})[name] = created_at
    except Exception:
        pass


def _refreshing(area, key):
    """True if the user asked to refresh this area and this exact
    result has not been recomputed yet in that refresh."""
    try:
        ss = _ss()
        if ss.get("_refresh_area") != area:
            return False
        return key not in ss.setdefault("_refreshed", set())
    except Exception:
        return False


def _mark_fresh(key):
    try:
        _ss().setdefault("_fresh_keys", set()).add(key)
    except Exception:
        pass


def _mark_refreshed(key):
    try:
        _ss().setdefault("_refreshed", set()).add(key)
    except Exception:
        pass


# ----------------------------------------------------------- storage

def _load(key):
    try:
        with _connect() as con:
            row = con.execute(
                "SELECT payload, created_at, used_at FROM results "
                "WHERE key=?", (key,)).fetchone()
            if row is None:
                return None
            # Every page rerun reads these; only write when the "last
            # used" mark (for pruning) is a day old.
            if row[2] < (datetime.datetime.now(datetime.timezone.utc)
                         - datetime.timedelta(days=1)).isoformat():
                con.execute("UPDATE results SET used_at=? WHERE key=?",
                            (_now(), key))
        return pickle.loads(zlib.decompress(row[0])), row[1]
    except Exception as e:           # a bad cache must never break a page
        log.warning("saved result unreadable (%s) - recomputing", e)
        return None


def _save(key, name, area, raw, val):
    try:
        blob = zlib.compress(pickle.dumps(val, protocol=4))
        if len(blob) > MAX_PAYLOAD:
            return None
        now = _now()
        with _connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO results (key, fn, area, args, "
                "created_at, used_at, payload) VALUES (?,?,?,?,?,?,?)",
                (key, name, area, raw, now, now, blob))
            if random.random() < 0.02:
                con.execute(
                    "DELETE FROM results WHERE used_at < ?",
                    ((datetime.datetime.now(datetime.timezone.utc)
                      - datetime.timedelta(days=KEEP_DAYS)).isoformat(),))
        return now
    except Exception as e:
        log.warning("could not save result for %s: %s", name, e)
        return None


# --------------------------------------------------------- decorator

def saved_result(name=None):
    """Decorator for functions whose first three args are
    (lat, lon, radius_km). Wraps a plain function or an st.cache_data
    one (in which case its memory entry is cleared on refresh)."""

    def deco(fn):
        base = getattr(fn, "__wrapped__", fn)   # see through st.cache_data
        fname = name or f"{base.__module__}.{base.__name__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                area = area_key(*args[:3])
            except Exception:
                return fn(*args, **kwargs)     # unexpected call shape
            key, raw = _key(fname, args, kwargs)

            refresh = _refreshing(area, key)
            if not refresh:
                got = _load(key)
                if got is not None:
                    val, created = got
                    _note_hit(area, fname, created, key)
                    return val

            if refresh and hasattr(fn, "clear"):
                try:
                    fn.clear(*args, **kwargs)  # drop the memory copy too
                except Exception:
                    pass
            val = fn(*args, **kwargs)
            _mark_fresh(key)
            if refresh:
                _mark_refreshed(key)
            if _worth_saving(val):
                _save(key, fname, area, raw, val)
            return val

        wrapper.peek = lambda *a, **k: _peek(fname, a, k)
        return wrapper

    return deco


def _peek(fname, args, kwargs):
    """Saved value for exactly these args, or None. Never computes."""
    key, _ = _key(fname, args, kwargs)
    got = _load(key)
    if got is None:
        return None
    val, created = got
    try:
        _note_hit(area_key(*args[:3]), fname, created, key)
    except Exception:
        pass
    return val


# --------------------------------------------------------- UI helpers

def start_refresh(lat, lon, radius):
    """Recompute every result for this area as it is next requested."""
    ss = _ss()
    area = area_key(lat, lon, radius)
    ss["_refresh_area"] = area
    ss["_refreshed"] = set()
    ss.setdefault("_saved_hits", {}).pop(area, None)


def end_refresh_if_moved(lat, lon, radius):
    """Leaving the area ends its refresh, so revisiting it is instant."""
    ss = _ss()
    if ss.get("_refresh_area") not in (None, area_key(lat, lon, radius)):
        ss["_refresh_area"] = None
        ss["_refreshed"] = set()


def saved_as_of(lat, lon, radius):
    """Oldest saved-result timestamp shown for this area this session
    (UTC ISO), or None if everything on screen was computed fresh."""
    hits = _ss().get("_saved_hits", {}).get(area_key(lat, lon, radius))
    return min(hits.values()) if hits else None


def is_stale(created_iso, year):
    if int(year) < datetime.date.today().year:
        return False
    try:
        age = datetime.datetime.now(datetime.timezone.utc) - \
            datetime.datetime.fromisoformat(created_iso)
    except ValueError:
        return False
    return age.days >= STALE_DAYS_CURRENT_YEAR
