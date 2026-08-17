"""5th Minor Irrigation Census - counted irrigation structures.

Loads whatever scripts/fetch_mi_census.py harvested from data.gov.in
(using the same key the app already uses for mandi prices) and serves
it per village, per block or per district - whichever granularity the
census actually publishes for that resource. The harvester records
which it found, and this module never claims finer than the truth.

This is the only irrigation evidence in the app that is neither a
district aggregate nor a satellite estimate: enumerators counted the
dug wells, tubewells and lift schemes.
"""

import csv
import json
import re
from functools import lru_cache

from config import PROJECT_ROOT

CSV_PATH = PROJECT_ROOT / "data" / "reference" / "mi_census_villages.csv"
META_PATH = PROJECT_ROOT / "data" / "reference" / "mi_census_meta.json"

VINTAGE = "5th Minor Irrigation Census (data.gov.in)"


def _key(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


@lru_cache(maxsize=1)
def _load():
    """(rows, meta). Empty when the harvest has not run yet."""
    if not CSV_PATH.exists():
        return [], {}
    rows = []
    try:
        with CSV_PATH.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows.append(r)
    except Exception:
        return [], {}
    meta = {}
    try:
        if META_PATH.exists():
            meta = json.loads(META_PATH.read_text())
    except Exception:
        meta = {}
    return rows, meta


def available():
    return bool(_load()[0])


def granularity():
    """'village', 'block', 'district' or None - what the data really is."""
    _rows, meta = _load()
    levels = {m.get("granularity")
              for m in (meta.get("resources") or {}).values()}
    for want in ("village", "block", "district"):
        if want in levels:
            return want
    return "village" if _rows and _rows[0].get("village") else None


def source_note():
    rows, meta = _load()
    if not rows:
        return ("Minor Irrigation Census not harvested yet. The server "
                "pulls it from data.gov.in with the same API key the "
                "mandi prices use - it runs on restart, or press the "
                "button in the irrigation panel.")
    g = granularity() or "unknown"
    return (f"{len(rows):,} {g}-level records from the "
            f"{VINTAGE}, state: {meta.get('state', 'Karnataka')}.")


_COUNT_HINTS = ("dugwell", "dug_well", "shallow", "deep", "tubewell",
                "tube_well", "well", "lift", "scheme", "structure",
                "pump", "number", "no_of", "count", "total")


def _count_fields(row):
    return [k for k in row
            if k not in ("village", "block", "district", "state",
                         "_source")
            and any(h in k for h in _COUNT_HINTS)]


def for_village(village, district=None, block=None):
    """Census rows matching a village (and district/block if given)."""
    rows, _ = _load()
    if not rows:
        return []
    vk = _key(village)
    dk = _key(district) if district else None
    bk = _key(block) if block else None
    out = []
    for r in rows:
        if vk and _key(r.get("village")) != vk:
            continue
        if dk and r.get("district") and _key(r["district"]) != dk:
            continue
        if bk and r.get("block") and _key(r["block"]) != bk:
            continue
        out.append(r)
    return out


def for_district(district):
    rows, _ = _load()
    dk = _key(district)
    return [r for r in rows if _key(r.get("district")) == dk]


def structures(rows):
    """Sum the counted structures across rows -> {field: total}."""
    if not rows:
        return {}
    totals = {}
    for r in rows:
        for f in _count_fields(r):
            try:
                totals[f] = totals.get(f, 0.0) + float(r.get(f) or 0)
            except (TypeError, ValueError):
                continue
    return {k: round(v) for k, v in totals.items() if v}


def area_table(names_by_district):
    """Census table for the districts in view, as list-of-dicts.

    `names_by_district` is a list of district names.
    """
    rows = []
    for d in names_by_district or []:
        hit = for_district(d)
        if not hit:
            continue
        tot = structures(hit)
        row = {"district": str(d).title(),
               "records": len(hit),
               "level": granularity()}
        row.update(tot)
        rows.append(row)
    return rows


def village_lookup():
    """{(village_key, district_key): counted structures} for joining."""
    rows, _ = _load()
    out = {}
    for r in rows:
        v = _key(r.get("village"))
        if not v:
            continue
        d = _key(r.get("district"))
        cur = out.setdefault((v, d), {})
        for f in _count_fields(r):
            try:
                cur[f] = cur.get(f, 0.0) + float(r.get(f) or 0)
            except (TypeError, ValueError):
                continue
    return {k: {f: round(x) for f, x in v.items() if x}
            for k, v in out.items()}
