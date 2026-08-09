"""Live VILLAGE-level Soil Health Card nutrient fetcher.

Talks to the same public GraphQL endpoint the soilhealth.dac.gov.in
dashboard uses, but drilled down to village resolution. Responses are
raw lab-sample counts per class for each village, e.g.

    {"n": {"High": 1, "Low": 12, "Medium": 24}, "pH": {...}, ...}

Everything is cached on disk (data/cache/shc_villages/), so each
village is fetched from the government portal at most once per cycle.

Village identity join, per boundary dataset:

  * Karnataka & Tamil Nadu boundary files carry the census-2011
    village code (`vilcode11`), which the portal embeds in its own
    village names ("AMARAHOSAHALLI - 619459") - an exact code join.

  * The Andhra Pradesh / Kerala / Maharashtra / Telangana boundary
    files carry different code systems, so those villages are joined
    by normalised NAME within the matched district (the portal's
    "(CT)" / "(Part)" markers and trailing code are stripped first),
    with a state-wide unique-name fallback for villages whose census
    district was since renamed or split (all of Telangana).

Pure python + requests. No streamlit, no folium.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from config import PROJECT_ROOT

API = "https://soilhealth4.dac.gov.in/"
CYCLE = "2025-26"
# Newest first. A village with no samples in the current cycle very
# often has them in an earlier one - fall back so fewer villages are
# grey. The cycle used is echoed in the tooltip.
CYCLES = ["2025-26", "2024-25", "2023-24"]
TIMEOUT = 8
WORKERS = 8
MAX_FETCH = 400        # new villages fetched per render
BUDGET_S = 30          # stop scheduling new fetches after this

CACHE = PROJECT_ROOT / "data" / "cache" / "shc_villages"

# Portal state ids (from the portal's own GetState query).
STATE_IDS = {
    "karnataka":     "63f99fbd519359b7438a84ca",
    "tamilnadu":     "63f9be9f519359b7438d08bb",
    "andhrapradesh": "63f957b089d86ca9e2c00e14",
    "kerala":        "63f9bd39519359b7438ce777",
    "maharashtra":   "63f9322a89d86ca9e2bca5df",
    "telangana":     "63f871f5c660ddb223457dca",
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


def _vn(s):
    """Normalise a VILLAGE name: drop the trailing census code and
    any parenthetical markers like (CT) / (Part), then _n()."""
    s = str(s or "")
    s = re.sub(r"[-\s]*\d{4,}\s*$", "", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    return _n(s)


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
    """Portal district id from our boundary-file names (alias-tolerant)."""
    key = _n(state_name)
    if key not in STATE_IDS:
        return None
    dmap = _district_ids(key)
    dn = _n(district_name)
    if not dn:
        return None
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


def _village_list(district_id):
    """Raw portal village rows [{name, _id}] for a district, cached."""
    fname = f"villagelist_{district_id}.json"
    cached = _load(fname, None)
    if cached is not None:
        return cached
    rows = _gql(Q_VILLAGES, {"district": district_id}) or []
    out = [{"name": str(r.get("name") or ""), "_id": r["_id"]}
           for r in rows if isinstance(r, dict) and r.get("_id")]
    if out:
        _save(fname, out)
    return out


def _maps_for_district(district_id):
    """(by_census_code, by_normalised_name) village-id lookup maps."""
    bycode, byname = {}, {}
    for r in _village_list(district_id):
        name, vid = r.get("name", ""), r.get("_id")
        if not vid:
            continue
        m = re.search(r"(\d{4,})\s*$", name)
        if m:
            bycode[str(int(m.group(1)))] = vid
        nn = _vn(name)
        if nn:
            byname.setdefault(nn, vid)
    return bycode, byname


def _state_maps(state_key, max_new=10):
    """State-wide (by_code, by_unique_name) maps across every portal
    district of a state.

    Used when the boundary file's district can't be matched to a
    portal district (districts got renamed / split - e.g. Telangana
    went from 10 census districts to 33) or the village isn't listed
    under the matched district. Name matches are only kept when the
    name is UNIQUE state-wide, so a wrong-district collision can't
    mislabel a village. District village lists are fetched at most
    `max_new` per call (cached on disk forever after).
    """
    try:
        dmap = _district_ids(state_key)
    except Exception:
        return {}, {}
    bycode, byname, seen = {}, {}, {}
    new = 0
    for did in dmap.values():
        rows = _load(f"villagelist_{did}.json", None)
        if rows is None:
            if new >= max_new:
                continue
            try:
                rows = _village_list(did)
                new += 1
            except Exception:
                continue
        for r in rows:
            name, vid = r.get("name", ""), r.get("_id")
            if not vid:
                continue
            m = re.search(r"(\d{4,})\s*$", name)
            if m:
                bycode.setdefault(str(int(m.group(1))), vid)
            nn = _vn(name)
            if nn:
                seen[nn] = seen.get(nn, 0) + 1
                byname.setdefault(nn, vid)
    return bycode, {n: v for n, v in byname.items() if seen.get(n) == 1}


def has_counts(res):
    """True when a results dict holds at least one non-zero sample
    count. The portal sometimes returns a results record whose class
    counts are all zero/empty - that must NOT stop the older-cycle
    fallback."""
    if not isinstance(res, dict):
        return False
    for k, v in res.items():
        if k == "_cycle" or not isinstance(v, dict):
            continue
        for c in v.values():
            try:
                if int(c or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _nutri(village_id):
    """Results counts for one village, or None if no samples.

    Tries the current cycle first, then falls back through older
    cycles until one actually holds samples. The cycle that produced
    the data is recorded under the "_cycle" key of the returned
    dict."""
    for cyc in CYCLES:
        rows = _gql(Q_NUTRI, {"village": village_id, "cycle": cyc,
                              "count": True}) or []
        res = (rows[0] or {}).get("results") if rows else None
        if has_counts(res):
            res["_cycle"] = cyc
            return res
    return None


def district_nutrients(state_name, district_name):
    """District-level nutrient counts straight from the portal (one
    query per district, multi-cycle fallback, disk-cached). Works for
    ALL six states - unlike the bundled KA/TN csv."""
    did = district_id_for(state_name, district_name)
    if not did:
        return None
    fname = f"nutri_district_{did}_multi.json"
    cached = _load(fname, "MISS")
    if cached != "MISS" and (cached is None or has_counts(cached)):
        return cached
    res = None
    for cyc in CYCLES:
        try:
            rows = _gql(Q_NUTRI, {"district": did, "cycle": cyc,
                                  "count": True}) or []
        except Exception:
            return None   # network trouble - don't cache
        r = (rows[0] or {}).get("results") if rows else None
        if has_counts(r):
            r["_cycle"] = cyc
            res = r
            break
    _save(fname, res)
    return res


def village_results_cached(state_name, district_name):
    """{portal village name: results} from the on-disk cache ONLY (no
    network). Used by rankings so they get faster as the map / report
    is used more."""
    did = district_id_for(state_name, district_name)
    if not did:
        return {}
    ncache = _load(f"nutri_{did}_multi.json", {})
    out = {}
    for r in _village_list_cached(did):
        vid = r.get("_id")
        if vid in ncache and has_counts(ncache.get(vid)):
            out[r.get("name", "")] = ncache[vid]
    return out


def _village_list_cached(district_id):
    return _load(f"villagelist_{district_id}.json", None) or []


def fetch_district_villages(state_name, district_name, budget_s=25,
                            max_fetch=150):
    """Progressively fetch nutrient data for a district's villages
    (cached). Returns how many are now cached vs total listed."""
    did = district_id_for(state_name, district_name)
    if not did:
        return 0, 0
    try:
        rows = _village_list(did)
    except Exception:
        rows = _village_list_cached(did)
    fname = f"nutri_{did}_multi.json"
    ncache = _load(fname, {})
    todo = [r["_id"] for r in rows
            if r.get("_id") and not (
                r["_id"] in ncache and (ncache[r["_id"]] is None
                                        or has_counts(ncache[r["_id"]])))]
    t0 = time.time()
    fetched = 0
    for i in range(0, len(todo), WORKERS):
        if time.time() - t0 > budget_s or fetched >= max_fetch:
            break
        chunk = todo[i:i + WORKERS]

        def safe(vid):
            try:
                return _nutri(vid)
            except Exception:
                return "ERR"

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(safe, chunk))
        for vid, res in zip(chunk, results):
            if res == "ERR":
                continue
            ncache[vid] = res
            fetched += 1
    if fetched:
        _save(fname, ncache)
    done = sum(1 for r in rows if r.get("_id") in ncache)
    return done, len(rows)


def results_for_villages(pairs):
    """Fetch/lookup village nutrient counts.

    pairs: iterable of (key, state_name, district_name, census_code,
    village_name). Returns {key: results dict | None}. None means the
    village has no match / no samples; keys ABSENT from the result
    were not fetched yet (time budget) - re-rendering continues where
    it left off, everything already fetched comes from disk.
    """
    t0 = time.time()
    out = {}

    by_dist = {}
    for key, st, dt, code, name in pairs:
        by_dist.setdefault((str(st), str(dt)), []).append(
            (str(key), code, name))

    fetched = 0
    state_pending = {}   # state name -> [(key, code, name)] unresolved

    def _fetch_batch(todo, ncache, fname):
        """Fetch nutrient counts for (key, vid) pairs within budget."""
        nonlocal fetched
        got = 0
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
            for (key, vid), res in zip(chunk, results):
                if res == "ERR":
                    continue
                ncache[vid] = res
                out[key] = res
                fetched += 1
                got += 1
        if got:
            _save(fname, ncache)

    for (st, dt), items in by_dist.items():
        if time.time() - t0 > BUDGET_S:
            break  # leave the rest absent -> grey "refresh to load"

        try:
            did = district_id_for(st, dt)
        except Exception:
            did = None
        if not did:
            state_pending.setdefault(st, []).extend(items)
            continue

        try:
            bycode, byname = _maps_for_district(did)
        except Exception:
            bycode, byname = {}, {}

        fname = f"nutri_{did}_multi.json"
        ncache = _load(fname, {})
        todo = []
        for key, code, name in items:
            vid = None
            try:
                vid = bycode.get(str(int(str(code).strip())))
            except Exception:
                vid = None
            if vid is None:
                vid = byname.get(_vn(name))
            if vid is None:
                state_pending.setdefault(st, []).append(
                    (key, code, name))
            elif vid in ncache and (ncache[vid] is None
                                    or has_counts(ncache[vid])):
                # cached zero-count records (from before the
                # older-cycle fallback existed) are refetched
                out[key] = ncache[vid]
            else:
                todo.append((key, vid))

        _fetch_batch(todo, ncache, fname)

    # Second pass: villages whose district didn't resolve (renamed /
    # split districts) - match state-wide by code or unique name.
    for st, items in state_pending.items():
        if time.time() - t0 > BUDGET_S:
            break
        skey = _n(st)
        sid = STATE_IDS.get(skey)
        if not sid:
            for key, _, _ in items:
                out[key] = None
            continue
        bycode, byname = _state_maps(skey)
        fname = f"nutri_state_{sid}_multi.json"
        ncache = _load(fname, {})
        todo = []
        for key, code, name in items:
            vid = None
            try:
                vid = bycode.get(str(int(str(code).strip())))
            except Exception:
                vid = None
            if vid is None:
                vid = byname.get(_vn(name))
            if vid is None:
                out[key] = None
            elif vid in ncache and (ncache[vid] is None
                                    or has_counts(ncache[vid])):
                out[key] = ncache[vid]
            else:
                todo.append((key, vid))
        _fetch_batch(todo, ncache, fname)

    return out
