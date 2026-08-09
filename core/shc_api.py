"""Live VILLAGE-level Soil Health Card nutrient fetcher.

Talks to the same public GraphQL endpoint the soilhealth.dac.gov.in
dashboard uses, but drilled down to village resolution. Responses are
raw lab-sample counts per class for each village, e.g.

    {"n": {"High": 1, "Low": 12, "Medium": 24}, "pH": {...}, ...}

Everything is cached on disk (data/cache/shc_villages/), so each
village is fetched from the government portal at most once per cycle.
Village identity is joined via the CENSUS village code, which the
portal embeds in its village names ("AMARAHOSAHALLI - 619459") and
which equals `vilcode11` in the bundled census village boundaries -
an exact join, no fuzzy name matching.

Pure python + requests. No streamlit, no folium.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from config import PROJECT_ROOT

API = "https://soilhealth4.dac.gov.in/"
CYCLE = "2025-26"
TIMEOUT = 8
WORKERS = 6
MAX_FETCH = 150        # new villages fetched per render
BUDGET_S = 25          # stop scheduling new fetches after this

CACHE = PROJECT_ROOT / "data" / "cache" / "shc_villages"

STATE_IDS = {
    "karnataka": "63f99fbd519359b7438a84ca",
    "tamilnadu": "63f9be9f519359b7438d08bb",
}

Q_DISTRICTS = """
query GetdistrictAndSubdistrictBystate($state: ID) {
  getdistrictAndSubdistrictBystate(state: $state)
}
"""

Q_VILLAGES = """
query GetVillageBydistrict($district: ID) {
  getVillageBydistrict(district: $district)
}
"""

Q_NUTRI = """
query GetNutrientDashboardForPortal($state: ID, $district: ID, $block: ID, $village: ID, $cycle: String, $count: Boolean, $scheme: String) {
  getNutrientDashboardForPortal(state: $state, district: $district, block: $block, village: $village, cycle: $cycle, count: $count, scheme: $scheme)
}
"""


def _n(s):
    """Normalise a name for matching (lowercase letters only)."""
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _gql(query, variables):
    import requests
    r = requests.post(API, json={"query": query, "variables": variables},
                      timeout=TIMEOUT)
    r.raise_for_status()
    out = r.json()
    if out.get("errors"):
        raise RuntimeError(str(out["errors"])[:200])
    data = out.get("data") or {}
    return data[next(iter(data))] if data else None


def _load(name, default):
    try:
        return json.loads((CACHE / name).read_text())
    except Exception:
        return default


def _save(name, obj):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / (name + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(CACHE / name)


def _district_ids(state_key):
    """{normalised district name: portal id} for a state, disk-cached."""
    sid = STATE_IDS.get(state_key)
    if not sid:
        return {}
    fname = f"districts_{sid}.json"
    cached = _load(fname, None)
    if cached:
        return cached
    rows = _gql(Q_DISTRICTS, {"state": sid}) or []
    out = {}
    for r in rows:
        if isinstance(r, dict) and r.get("name") and r.get("_id"):
            out[_n(r["name"])] = r["_id"]
    if out:
        _save(fname, out)
    return out


def district_id_for(state_name, district_name):
    """Portal district id from our shapefile names (alias-tolerant)."""
    key = _n(state_name)
    if key not in STATE_IDS:
        return None
    dmap = _district_ids(key)
    dn = _n(district_name)
    try:
        from core.allied import DISTRICT_ALIAS, _norm
        dn_alias = _n(DISTRICT_ALIAS.get(_norm(district_name), ""))
    except Exception:
        dn_alias = ""
    if dn in dmap:
        return dmap[dn]
    if dn_alias and dn_alias in dmap:
        return dmap[dn_alias]
    import difflib
    close = difflib.get_close_matches(dn, list(dmap.keys()), n=1,
                                      cutoff=0.8)
    return dmap[close[0]] if close else None


def _village_ids(district_id):
    """{census code: portal village id} for a district, disk-cached."""
    fname = f"villages_{district_id}.json"
    cached = _load(fname, None)
    if cached:
        return cached
    rows = _gql(Q_VILLAGES, {"district": district_id}) or []
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "")
        vid = r.get("_id")
        m = re.search(r"(\d{4,})\s*$", name)
        if m and vid:
            out[str(int(m.group(1)))] = vid
    if out:
        _save(fname, out)
    return out


def _nutri(village_id):
    """Results counts for one village, or None if no samples."""
    rows = _gql(Q_NUTRI, {"village": village_id, "cycle": CYCLE,
                          "count": True}) or []
    if not rows:
        return None
    return (rows[0] or {}).get("results") or None


def results_for_villages(pairs):
    """Fetch/lookup village nutrient counts.

    pairs: iterable of (state_name, district_name, census_code).
    Returns {census_code: results dict | None}. Codes absent from the
    result were NOT fetched yet (time budget) - rerendering continues
    where it left off, everything already fetched comes from disk.
    """
    t0 = time.time()
    out = {}

    by_dist = {}
    for st, dt, code in pairs:
        try:
            c = str(int(str(code).strip()))
        except Exception:
            continue
        by_dist.setdefault((str(st), str(dt)), []).append(c)

    fetched = 0
    for (st, dt), codes in by_dist.items():
        try:
            did = district_id_for(st, dt)
        except Exception:
            did = None
        if not did:
            for c in codes:
                out[c] = None
            continue

        try:
            vmap = _village_ids(did)
        except Exception:
            vmap = {}

        fname = f"nutri_{did}_{CYCLE}.json"
        ncache = _load(fname, {})
        todo = []
        for c in codes:
            vid = vmap.get(c)
            if vid is None:
                out[c] = None
            elif vid in ncache:
                out[c] = ncache[vid]
            else:
                todo.append((c, vid))

        # fetch what the time budget allows, in small parallel chunks
        n_new = 0
        for i in range(0, len(todo), WORKERS):
            if time.time() - t0 > BUDGET_S or fetched >= MAX_FETCH:
                break
            chunk = todo[i:i + WORKERS]

            def safe(vid):
                try:
                    return _nutri(vid)
                except Exception:
                    return "ERR"

            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                results = list(ex.map(safe, [v for _, v in chunk]))
            for (c, vid), res in zip(chunk, results):
                if res == "ERR":
                    continue
                ncache[vid] = res
                out[c] = res
                fetched += 1
                n_new += 1
        if n_new:
            _save(fname, ncache)

    return out
