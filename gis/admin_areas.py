"""District / State admin-area access - memory-safe.

Provides, for every state with village boundaries:
  * the list of its districts,
  * the villages of one district (with geometry),
  * a per-district bounding box index so a district's villages can be
    windowed out of the big state file without loading the state.

The index is built ONCE per state by scanning the boundary file in
small chunks (never holding the whole state in RAM - the server has
1 GB) and cached to disk. First build of a state takes a minute or
two; every later call is instant.
"""

import json
import re

from config import PROJECT_ROOT

CACHE = PROJECT_ROOT / "data" / "cache" / "admin"

STATE_LABELS = {
    "karnataka": "Karnataka",
    "tamilnadu": "Tamil Nadu",
    "kerala": "Kerala",
    "andhra_pradesh": "Andhra Pradesh",
    "maharashtra": "Maharashtra",
    "telangana": "Telangana",
}


def _n(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _load(name):
    try:
        return json.loads((CACHE / name).read_text())
    except Exception:
        return None


def _save(name, obj):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / (name + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(CACHE / name)


def available_states():
    """[(key, label)] for states that actually have village files."""
    from data.gis_data import GIS_DATA, refresh
    refresh()
    out = []
    for key in sorted(GIS_DATA):
        if "villages" in GIS_DATA[key]:
            out.append((key, STATE_LABELS.get(
                key, key.replace("_", " ").title())))
    return out


def _index_shapefile(path):
    """Chunked district-bbox scan of a shapefile/gpkg."""
    import geopandas as gpd
    idx = {}
    start, step = 0, 6000
    while True:
        try:
            g = gpd.read_file(path, rows=slice(start, start + step))
        except Exception:
            break
        if g is None or len(g) == 0:
            break
        g = g.rename(columns=str.lower)
        dcol = next((c for c in ("dtname", "district_name", "district",
                                 "dist_name", "dtname11")
                     if c in g.columns), None)
        if dcol is None:
            break
        b = g.geometry.bounds
        for dist, sub in b.groupby(g[dcol].astype(str)):
            box = [float(sub.minx.min()), float(sub.miny.min()),
                   float(sub.maxx.max()), float(sub.maxy.max())]
            if dist in idx:
                o = idx[dist]
                idx[dist] = [min(o[0], box[0]), min(o[1], box[1]),
                             max(o[2], box[2]), max(o[3], box[3])]
            else:
                idx[dist] = box
        if len(g) < step:
            break
        start += step
        del g
    return idx


def _index_csv(path):
    """Chunked district-bbox scan of a CSV-WKT file."""
    import pandas as pd
    from shapely import wkt as _wkt

    idx = {}
    for chunk in pd.read_csv(path, chunksize=3000):
        chunk = chunk.rename(columns=str.lower)
        dcol = next((c for c in ("district_name", "dtname", "district")
                     if c in chunk.columns), None)
        wcol = next((c for c in ("wkt", "geometery_in_wkt",
                                 "geometry_in_wkt", "geometry")
                     if c in chunk.columns), None)
        if dcol is None or wcol is None:
            break
        for dist, sub in chunk.groupby(chunk[dcol].astype(str)):
            box = None
            for s in sub[wcol]:
                try:
                    b = _wkt.loads(str(s)).bounds
                except Exception:
                    continue
                if box is None:
                    box = list(b)
                else:
                    box = [min(box[0], b[0]), min(box[1], b[1]),
                           max(box[2], b[2]), max(box[3], b[3])]
            if box is None:
                continue
            if dist in idx:
                o = idx[dist]
                idx[dist] = [min(o[0], box[0]), min(o[1], box[1]),
                             max(o[2], box[2]), max(o[3], box[3])]
            else:
                idx[dist] = box
    return idx


def district_index(state_key):
    """{district name: [minx,miny,maxx,maxy]} for a state, cached."""
    fname = f"district_index_{state_key}.json"
    cached = _load(fname)
    if cached:
        return cached

    from data.gis_data import get_layer
    try:
        path = get_layer(state_key, "villages")
    except Exception:
        return {}

    name = path.name.lower()
    if name.endswith(".csv") or name.endswith(".csv.xz"):
        idx = _index_csv(path)
    else:
        idx = _index_shapefile(path)

    # Drop junk district names (pure numbers etc.)
    idx = {d: b for d, b in idx.items()
           if d and not d.strip().isdigit() and d.lower() != "nan"}
    if idx:
        _save(fname, idx)
    return idx


def list_districts(state_key):
    """Sorted display list of the state's districts."""
    return sorted(district_index(state_key).keys(),
                  key=lambda s: s.title())


def find_district(state_key, typed):
    """Resolve a typed district name (fuzzy) to the exact file name."""
    idx = district_index(state_key)
    if not idx:
        return None
    t = _n(typed)
    if not t:
        return None
    for d in idx:
        if _n(d) == t:
            return d
    for d in idx:
        if t in _n(d) or _n(d) in t:
            return d
    import difflib
    close = difflib.get_close_matches(
        t, {_n(d): d for d in idx}.keys(), n=1, cutoff=0.75)
    if close:
        return {_n(d): d for d in idx}[close[0]]
    return None


def district_villages(state_key, district):
    """GeoDataFrame of ONE district's villages (windowed read)."""
    idx = district_index(state_key)
    box = idx.get(district)
    if not box:
        return None
    from gis.boundary_loader import load_boundaries
    pad = 0.02
    gdf = load_boundaries(state_key, "villages",
                          bbox=(box[0] - pad, box[1] - pad,
                                box[2] + pad, box[3] + pad))
    if gdf is None or gdf.empty or "dtname" not in gdf.columns:
        return None
    gdf = gdf[gdf["dtname"].astype(str).map(_n) == _n(district)]
    if gdf.empty:
        return None
    dedupe = [c for c in ("vilname11", "sdtname", "vilcode11")
              if c in gdf.columns]
    if dedupe:
        gdf = gdf.drop_duplicates(subset=dedupe)
    return gdf.reset_index(drop=True)
