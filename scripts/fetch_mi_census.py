"""Harvest the 5th Minor Irrigation Census - real village-level wells.

WHY THIS MATTERS
Everything else in the irrigation stack is either a district aggregate
or a satellite estimate. This census counts actual irrigation
structures - dug wells, shallow and deep tubewells, surface lift
schemes - as recorded by government enumerators, at the finest
administrative level the data goes to. Where it reaches village level,
it is the only non-satellite, non-district irrigation evidence
available.

WHY IT MUST RUN ON THE SERVER
data.gov.in ignores its own server-side filters on these resources
(`filters[state]=Karnataka` silently returns nothing), so the whole
resource has to be paged and filtered locally - roughly 190k rows.
That is a one-off harvest, cached to disk, not something to do on a
user's click.

Uses the SAME data.gov.in key the app already uses for mandi prices
(DATA_GOV_API_KEY), so nothing new is needed. Order of preference:
--api-key, then $DATA_GOV_API_KEY, then .streamlit/secrets.toml.

Run:
    python scripts/fetch_mi_census.py
    python scripts/fetch_mi_census.py --state Karnataka --max-pages 250

Safe to re-run: it skips work when a good cache exists and never raises
into the app.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "mi_census_villages.csv"
META = ROOT / "data" / "reference" / "mi_census_meta.json"

OGD = "https://api.data.gov.in/resource/{uuid}"

# The two resources that carry structure COUNTS (the rest are costs,
# reasons and social breakdowns - useful later, not for targeting).
RESOURCES = {
    "dugwells_by_type": "89baee64-e9c8-4e8e-9576-dd8b4bac3372",
    "surface_lift_ownership": "9936122b-7699-4fa9-bf7a-d6752a1cc0eb",
}

PAGE = 1000
SLEEP = 0.25
TIMEOUT = 180

# Column names data.gov.in uses for place fields, best first.
_VILLAGE_KEYS = ("village", "village_name", "villagename", "vill_name")
_DISTRICT_KEYS = ("district", "district_name", "districtname", "dist")
_BLOCK_KEYS = ("block", "block_name", "taluk", "tehsil", "sub_district")
_STATE_KEYS = ("state", "state_name", "statename")


def _api_key(cli=None):
    if cli:
        return cli
    env = os.environ.get("DATA_GOV_API_KEY")
    if env:
        return env
    for name in (".streamlit/secrets.toml", "secrets.toml"):
        p = ROOT / name
        if not p.exists():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'DATA_GOV_API_KEY\s*=\s*"([^"]+)"', txt)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None


def _first(row, names):
    for n in names:
        for k in row:
            if str(k).strip().lower() == n:
                return k
    # loose contains match
    for n in names:
        for k in row:
            if n in str(k).strip().lower():
                return k
    return None


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def pull(uuid, key, state, max_pages):
    import requests

    rows, offset, total, pages = [], 0, None, 0
    while True:
        r = requests.get(OGD.format(uuid=uuid), params={
            "api-key": key, "format": "json",
            "limit": PAGE, "offset": offset,
        }, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        batch = j.get("records") or []
        total = j.get("total", total)
        if not batch:
            break

        skey = _first(batch[0], _STATE_KEYS)
        if state and skey:
            want = state.lower().replace(" ", "")
            batch = [b for b in batch
                     if want in str(b.get(skey, "")).lower()
                     .replace(" ", "")]
        rows += batch
        offset += PAGE
        pages += 1
        print(f"  {uuid[:8]} {offset}/{total} kept={len(rows)}",
              file=sys.stderr)
        if total and offset >= int(total):
            break
        if max_pages and pages >= max_pages:
            print("  stopping at page cap", file=sys.stderr)
            break
        time.sleep(SLEEP)
    return rows


def _aggregate(rows):
    """Collapse to one row per place, summing every numeric column."""
    if not rows:
        return [], {}

    sample = rows[0]
    vkey = _first(sample, _VILLAGE_KEYS)
    dkey = _first(sample, _DISTRICT_KEYS)
    bkey = _first(sample, _BLOCK_KEYS)
    skey = _first(sample, _STATE_KEYS)

    place_keys = [k for k in (vkey, bkey, dkey, skey) if k]
    numeric = [k for k in sample
               if k not in place_keys and _num(sample.get(k)) or
               (k not in place_keys
                and str(sample.get(k)).replace(".", "").isdigit())]

    agg = {}
    for r in rows:
        key = tuple(str(r.get(k, "")).strip() for k in place_keys)
        cur = agg.setdefault(key, {})
        for n in numeric:
            cur[n] = cur.get(n, 0.0) + _num(r.get(n))

    out = []
    for key, sums in agg.items():
        row = {}
        for i, k in enumerate(place_keys):
            label = ("village" if k == vkey else
                     "block" if k == bkey else
                     "district" if k == dkey else "state")
            row[label] = key[i]
        for n, v in sums.items():
            row[re.sub(r"[^a-z0-9_]", "_", str(n).lower())] = round(v, 2)
        out.append(row)

    meta = {
        "granularity": ("village" if vkey else
                        "block" if bkey else
                        "district" if dkey else "unknown"),
        "village_field": vkey, "block_field": bkey,
        "district_field": dkey,
        "numeric_fields": numeric,
        "rows": len(out),
    }
    return out, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key")
    ap.add_argument("--state", default="Karnataka")
    ap.add_argument("--max-pages", type=int, default=260)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    if OUT.exists() and not a.force:
        print(f"cache ok: {OUT}")
        return 0

    key = _api_key(a.api_key)
    if not key:
        print("No data.gov.in key found. The app already uses one for "
              "mandi prices (DATA_GOV_API_KEY in .streamlit/"
              "secrets.toml) - this reuses it.", file=sys.stderr)
        return 2

    all_rows, metas = [], {}
    for name, uuid in RESOURCES.items():
        try:
            print(f"== {name} ==", file=sys.stderr)
            raw = pull(uuid, key, a.state, a.max_pages)
        except Exception as e:
            print(f"  failed: {e}", file=sys.stderr)
            continue
        rows, meta = _aggregate(raw)
        meta["resource"] = name
        metas[name] = meta
        for r in rows:
            r["_source"] = name
        all_rows += rows
        print(f"  -> {len(rows)} aggregated rows "
              f"({meta['granularity']} level)", file=sys.stderr)

    if not all_rows:
        print("Nothing harvested.", file=sys.stderr)
        return 1

    cols = []
    for r in all_rows:
        for k in r:
            if k not in cols:
                cols.append(k)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    META.write_text(json.dumps(
        {"state": a.state, "resources": metas}, indent=1))

    print(f"wrote {len(all_rows)} rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
