"""Saved areas, and what changed between visits.

WHY
---
Everything else in this app is one-shot: search, compute, read,
leave. A sourcing team does not work that way - they care about the
same fifteen areas every week, and what they actually want to know
is what MOVED since last time.

So this stores a snapshot of the headline figures per saved area and
diffs the next run against it.

WHAT A DIFF HERE IS AND IS NOT
------------------------------
A change between two runs can mean the ground changed. It can also
mean the satellite saw it differently - a cloudier composite, a
different Sentinel-2 pass, a season boundary, or a change to the
app's own thresholds between versions. This module therefore reports
CHANGE, never CAUSE, and flags anything under a noise floor as "no
meaningful change" rather than dressing up jitter as a trend. Two
snapshots taken days apart cannot show real cropland change; two
taken seasons apart might.
"""

import json
import time
from datetime import datetime

# Below these, a difference is treated as measurement noise rather
# than a real move. Satellite composites vary run to run; calling a
# 1% wobble "growth" would be worse than saying nothing.
NOISE_FLOOR_PCT = 5.0
NOISE_FLOOR_AC = 25.0

# The figures worth watching, and how to label them.
TRACKED = [
    ("cropland_ac", "Cropland", "ac"),
    ("agriculture_ac", "Agriculture (land cover)", "ac"),
    ("plantation_ac", "Plantation detected", "ac"),
    ("plantation_net_ac", "Plantation net of forest", "ac"),
    ("farmland_trees_ac", "Farmland trees", "ac"),
    ("summer_green_ac", "Irrigated - summer green", "ac"),
    ("s1_event_ac", "Radar irrigation events", "ac"),
    ("forest_ac", "Forest cover", "ac"),
    ("parcels", "Field parcels", ""),
    ("coconut_survey_ac", "Coconut (crop survey)", "ac"),
]


def _path():
    from config import PROJECT_ROOT
    return PROJECT_ROOT / "data" / "watchlist.json"


def _load():
    try:
        p = _path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"areas": {}}


def _save(db):
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(db, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def area_key(lat, lon, radius_km):
    """Stable id for a circle. 4 dp is ~11 m - the same spot twice."""
    return f"{float(lat):.4f}_{float(lon):.4f}_{float(radius_km):g}"


def areas():
    """Saved areas, most recently seen first."""
    db = _load()
    out = []
    for key, a in (db.get("areas") or {}).items():
        snaps = a.get("snapshots") or []
        out.append({
            "key": key,
            "name": a.get("name") or key,
            "lat": a.get("lat"), "lon": a.get("lon"),
            "radius_km": a.get("radius_km"),
            "snapshots": len(snaps),
            "last_seen": snaps[-1]["when"] if snaps else None,
        })
    out.sort(key=lambda x: x["last_seen"] or "", reverse=True)
    return out


def snapshot_from_state(state):
    """Pull the tracked figures out of whatever the app has computed.

    Missing figures are simply absent - a snapshot records what was
    measured on that visit, and an absent number must never later
    read as a drop to zero.
    """
    snap = {}

    def put(key, value):
        try:
            if value is None:
                return
            v = float(value)
            if v != v:                      # NaN
                return
            snap[key] = v
        except (TypeError, ValueError):
            pass

    irr = state.get("irrigation_stats") or {}
    put("cropland_ac", irr.get("cropland_ac"))
    put("summer_green_ac", irr.get("summer_green_ac"))
    put("s1_event_ac", irr.get("s1_event_ac"))

    fo = state.get("forest_stats") or {}
    put("plantation_ac", fo.get("plantation_gross_ac"))
    put("plantation_net_ac", fo.get("plantation_net_ac"))
    put("farmland_trees_ac", fo.get("farmland_trees_ac"))
    put("forest_ac", fo.get("forest_ac"))

    pl = state.get("plantation_stats") or {}
    if "plantation_ac" not in snap:
        put("plantation_ac", pl.get("plantation_ac"))

    cs = state.get("coconut_survey") or {}
    put("coconut_survey_ac", cs.get("extent_ac"))

    # Land-cover agriculture row, if the analysis has run.
    try:
        for row in (state.get("results") or []):
            if str(row.get("Land Cover", "")).lower() == "agriculture":
                put("agriculture_ac", row.get("Area (acres)"))
    except Exception:
        pass

    return snap


def save_snapshot(state, name=None):
    """Record the current figures for the current area."""
    try:
        lat = float(state["lat"])
        lon = float(state["lon"])
        radius = float(state.get("radius", 10) or 10)
    except Exception:
        return None, "No area is selected."

    snap = snapshot_from_state(state)
    if not snap:
        return None, ("Nothing has been measured for this area yet - "
                      "run the analysis first, otherwise the snapshot "
                      "would record an empty visit.")

    db = _load()
    key = area_key(lat, lon, radius)
    area = db["areas"].get(key) or {
        "name": name or state.get("search_location") or key,
        "lat": lat, "lon": lon, "radius_km": radius,
        "snapshots": [],
    }
    if name:
        area["name"] = name
    area["snapshots"].append({
        "when": datetime.now().isoformat(timespec="seconds"),
        "year": state.get("year"),
        "values": snap,
    })
    # Keep the history bounded; a small server does not need years of
    # JSON, and the useful comparison is against the last visit.
    area["snapshots"] = area["snapshots"][-24:]
    db["areas"][key] = area
    ok = _save(db)
    return key, (f"Snapshot saved - {len(snap)} figures recorded."
                 if ok else "Could not write the watchlist file.")


def diff(key, against=-2):
    """Compare the latest snapshot with an earlier one."""
    db = _load()
    area = (db.get("areas") or {}).get(key)
    if not area:
        return None
    snaps = area.get("snapshots") or []
    if len(snaps) < 2:
        return {"area": area, "rows": [], "since": None,
                "note": ("Only one visit recorded so far. Save "
                         "another snapshot on a later date and this "
                         "will show what moved.")}

    new = snaps[-1]
    old = snaps[against] if abs(against) <= len(snaps) else snaps[0]

    rows = []
    for field, label, unit in TRACKED:
        a = old["values"].get(field)
        b = new["values"].get(field)
        if a is None or b is None:
            # Never present a missing measurement as a change.
            if a is not None or b is not None:
                rows.append({
                    "label": label, "old": a, "new": b, "unit": unit,
                    "delta": None, "pct": None,
                    "verdict": "not measured on both visits",
                })
            continue
        delta = b - a
        pct = (100.0 * delta / a) if a else None
        rows.append({
            "label": label, "old": a, "new": b, "unit": unit,
            "delta": delta, "pct": pct,
            "verdict": _verdict(delta, pct, unit),
        })

    return {"area": area, "rows": rows,
            "since": old["when"], "until": new["when"],
            "days": _days_between(old["when"], new["when"]),
            "note": None}


def _days_between(a, b):
    try:
        return (datetime.fromisoformat(b)
                - datetime.fromisoformat(a)).days
    except Exception:
        return None


def _verdict(delta, pct, unit):
    """Change or noise - said plainly."""
    if unit == "ac" and abs(delta) < NOISE_FLOOR_AC:
        return "no meaningful change"
    if pct is not None and abs(pct) < NOISE_FLOOR_PCT:
        return "no meaningful change"
    direction = "up" if delta > 0 else "down"
    if pct is None:
        return direction
    return f"{direction} {abs(pct):.0f}%"


def interpretation(d):
    """The sentence that keeps a diff honest."""
    if not d or not d.get("rows"):
        return None
    days = d.get("days")
    if days is not None and days < 30:
        return (
            f"These snapshots are {days} day"
            f"{'s' if days != 1 else ''} apart. Cropland and "
            f"plantation do not change measurably in that time - "
            f"anything moving here is almost certainly the satellite "
            f"seeing differently (cloud, a different pass, a season "
            f"boundary), not the ground changing. Compare across "
            f"seasons for a real signal.")
    return (
        "A change here means the two measurements differ. It does "
        "not say why: real change on the ground, a cloudier "
        "composite, a different Sentinel-2 pass and a change to the "
        "app's own thresholds between versions all look identical "
        "from here. Treat a move as a prompt to look, not a finding.")
