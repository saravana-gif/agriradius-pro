"""SHC district choropleth - paint MEASURED soil-test status on the map.

Joins the bundled Soil Health Card nutrient table
(data/reference/shc_district_nutrients.csv, real lab samples) onto a
tiny simplified district-boundary file and returns a GeoJSON dict
whose features carry a precomputed fill colour + display text, ready
for folium. The output is CLIPPED to the analysis buffer circle so
the rest of the map stays the normal basemap. Pure data prep - no
folium, no streamlit.

Also provides VILLAGE-resolution rendering: each village polygon in
the buffer coloured by its own live-fetched lab results (see
core/shc_api.py).
"""

import base64
import gzip
import json
from functools import lru_cache

from config import PROJECT_ROOT

_REF = PROJECT_ROOT / "data" / "reference"
DISTRICTS_LOCAL = _REF / "shc_districts_local.geojson.gz.b64"
DISTRICTS_GJ = _REF / "shc_districts.geojson"
DISTRICTS_B64 = _REF / "shc_districts.geojson.gz.b64"


def _read_districts():
    """Load the district GeoJSON.

    Tries, in order: the locally-built compact copy (see
    scripts/build_shc_districts.py), the bundled compact copy, then a
    plain GeoJSON. Each candidate is validated - a corrupt file is
    skipped instead of crashing the map.
    """
    for path in (DISTRICTS_LOCAL, DISTRICTS_B64, DISTRICTS_GJ):
        try:
            if not path.exists():
                continue
            txt = path.read_text()
            if path.name.endswith(".b64"):
                blob = txt.replace("\n", "").replace("\r", "").strip()
                return json.loads(gzip.decompress(base64.b64decode(blob)))
            return json.loads(txt)
        except Exception:
            continue
    return None

# metric key -> (label shown in UI, csv column or "ph", legend kind)
# kind "pct_bad": % of samples where MORE is WORSE (low / deficient)
# kind "ph":      dominant soil-reaction class (categorical)
METRICS = {
    "n_low":     ("Nitrogen - % samples LOW",        "n_low",     "pct_bad"),
    "p_low":     ("Phosphorus - % samples LOW",      "p_low",     "pct_bad"),
    "k_low":     ("Potassium - % samples LOW",       "k_low",     "pct_bad"),
    "oc_low":    ("Organic Carbon - % samples LOW",  "oc_low",    "pct_bad"),
    "ph":        ("Soil reaction (dominant class)",  "ph",        "ph"),
    "ec_saline": ("Salinity - % samples saline",     "ec_saline", "pct_bad"),
    "zn_def":    ("Zinc - % samples deficient",      "zn_def",    "pct_bad"),
    "fe_def":    ("Iron - % samples deficient",      "fe_def",    "pct_bad"),
    "b_def":     ("Boron - % samples deficient",     "b_def",     "pct_bad"),
    "s_def":     ("Sulphur - % samples deficient",   "s_def",     "pct_bad"),
    "mn_def":    ("Manganese - % samples deficient", "mn_def",    "pct_bad"),
    "cu_def":    ("Copper - % samples deficient",    "cu_def",    "pct_bad"),
}

PCT_BINS = [
    (20,  "#1a9850", "under 20% - good"),
    (40,  "#a6d96a", "20-40% - watch"),
    (60,  "#fee08b", "40-60% - concern"),
    (80,  "#f46d43", "60-80% - poor"),
    (101, "#d73027", "over 80% - severe"),
]

PH_COLORS = {
    "Acidic":   "#d7191c",
    "Neutral":  "#91cf60",
    "Alkaline": "#2c7bb6",
}

NO_DATA = "#bdbdbd"


def metric_options():
    """[(key, label), ...] for the UI selector."""
    return [(k, v[0]) for k, v in METRICS.items()]


def legend_items(metric):
    """[(label, color), ...] for the layer legend."""
    kind = METRICS[metric][2]
    if kind == "ph":
        items = [(f"Mostly {k.lower()}", c) for k, c in PH_COLORS.items()]
    else:
        items = [(lab, col) for _, col, lab in PCT_BINS]
    return items + [("No SHC data", NO_DATA)]


def _pct_color(v):
    for hi, col, _ in PCT_BINS:
        if v < hi:
            return col
    return PCT_BINS[-1][1]


@lru_cache(maxsize=1)
def _rows_by_key():
    """{normalised district: csv row dict} with rename tolerance."""
    from core.shc import load
    df = load()
    if df.empty:
        return {}
    return {r["_key"]: r for _, r in df.iterrows()}


def _match(district):
    from core.allied import _norm, DISTRICT_ALIAS
    rows = _rows_by_key()
    k = _norm(district)
    k = DISTRICT_ALIAS.get(k, k)
    if k in rows:
        return rows[k]
    import difflib
    close = difflib.get_close_matches(k, list(rows.keys()), n=1,
                                      cutoff=0.82)
    return rows[close[0]] if close else None


def _circle(lat, lon, radius_km):
    """Approximate geodesic circle as a shapely polygon (degrees)."""
    import math
    from shapely import affinity
    from shapely.geometry import Point

    unit = Point(lon, lat).buffer(1.0, quad_segs=48)
    kx = radius_km / (111.32 * max(0.2, math.cos(math.radians(lat))))
    ky = radius_km / 110.57
    return affinity.scale(unit, kx, ky, origin=(lon, lat))


@lru_cache(maxsize=8)
def geojson_for(metric, lat, lon, radius_km):
    """GeoJSON clipped to the selected buffer circle.

    Only the parts of districts that fall INSIDE the analysis radius
    are painted (rest of the map stays the normal basemap). Where the
    circle crosses a district border the circle is split, so each
    piece carries its own district's measured value. Cached per
    (metric, point, radius).
    """
    if metric not in METRICS:
        return None

    _, col, kind = METRICS[metric]

    gj = _read_districts()
    if gj is None:
        return None

    from shapely.geometry import mapping, shape

    circle = _circle(lat, lon, radius_km)

    feats = []
    for f in gj["features"]:
        try:
            geom = shape(f["geometry"])
            if not geom.intersects(circle):
                continue
            clipped = geom.buffer(0).intersection(circle)
            if clipped.is_empty:
                continue
        except Exception:
            continue

        p = f["properties"]
        row = _match(p.get("district", ""))
        name = str(p.get("district", "?")).title()

        if row is None:
            fill, disp = NO_DATA, "no SHC data"
        elif kind == "ph":
            trio = [("Acidic", int(row["ph_acid"])),
                    ("Neutral", int(row["ph_neut"])),
                    ("Alkaline", int(row["ph_alk"]))]
            dom, pct = max(trio, key=lambda t: t[1])
            fill = PH_COLORS[dom]
            disp = f"{dom} ({pct}% of samples)"
        else:
            v = int(row[col])
            fill = _pct_color(v)
            disp = f"{v}% of samples"

        feats.append({
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {
                "district": name,
                "val": disp,
                "_fill": fill,
            },
        })

    if not feats:
        return None

    return {"type": "FeatureCollection", "features": feats}


# --- Village-level detail (live SHC portal fetch, census-code join) ---

# metric key -> (results key, class name) in the portal's counts dict
_M2V = {
    "n_low":     ("n",  "Low"),
    "p_low":     ("p",  "Low"),
    "k_low":     ("k",  "Low"),
    "oc_low":    ("OC", "Low"),
    "ec_saline": ("EC", "Saline"),
    "zn_def":    ("Zn", "Deficient"),
    "fe_def":    ("Fe", "Deficient"),
    "b_def":     ("B",  "Deficient"),
    "s_def":     ("S",  "Deficient"),
    "mn_def":    ("Mn", "Deficient"),
    "cu_def":    ("Cu", "Deficient"),
}

MAX_VILLAGE_POLYS = 2500


def _village_tol(n):
    """Simplify tolerance by polygon count: finer borders for small
    areas (no visible overlap), coarser for 100 km views (page
    weight)."""
    if n <= 400:
        return 0.00012   # ~13 m - borders stay crisp
    if n <= 900:
        return 0.0003
    if n <= 1800:
        return 0.0005
    return 0.0008


def geojson_villages(metric, lat, lon, radius_km):
    """Village-resolution choropleth covering the WHOLE buffer circle.

    Each village polygon inside the radius is coloured by its OWN
    lab-sample counts, fetched live from the SHC portal (cached on
    disk after the first fetch). Villages without samples, or not yet
    fetched within the time budget, stay grey - re-rendering loads
    more. Returns None when nothing can be drawn.

    Coverage: Karnataka, Tamil Nadu, Kerala, Andhra Pradesh,
    Maharashtra (Telangana pending a boundary file).
    """
    if metric not in METRICS:
        return None

    from gis.spatial import villages_in_buffer

    try:
        gdf = villages_in_buffer(lat, lon, radius_km)
    except Exception:
        return None
    if gdf is None or gdf.empty or "vilname11" not in gdf.columns:
        return None

    gdf = gdf.copy()

    # Some CSV boundary files repeat rows - draw each village once.
    dedupe_cols = [c for c in ("stname", "dtname", "sdtname",
                               "vilname11", "vilcode11")
                   if c in gdf.columns]
    if dedupe_cols:
        gdf = gdf.drop_duplicates(subset=dedupe_cols)

    if len(gdf) > MAX_VILLAGE_POLYS:
        b = gdf.geometry.bounds
        gdf["_d2"] = ((b.minx + b.maxx) / 2 - lon) ** 2 + \
                     ((b.miny + b.maxy) / 2 - lat) ** 2
        gdf = gdf.nsmallest(MAX_VILLAGE_POLYS, "_d2")

    from core import shc_api

    rows = list(gdf.iterrows())
    pairs = [
        (str(i), r.get("stname", ""), r.get("dtname", ""),
         r.get("vilcode11", ""), r.get("vilname11", ""))
        for i, (_, r) in enumerate(rows)
    ]
    try:
        res_map = shc_api.results_for_villages(pairs)
    except Exception:
        res_map = {}

    from shapely.geometry import mapping

    circle = _circle(lat, lon, radius_km)
    tol = _village_tol(len(rows))

    feats = []
    for i, (_, r) in enumerate(rows):
        try:
            geom = r.geometry.simplify(tol, preserve_topology=True)
            clipped = geom.buffer(0).intersection(circle)
            if clipped.is_empty:
                continue
        except Exception:
            continue

        vname = str(r.get("vilname11", "?")).title()
        label = f"{vname} ({str(r.get('dtname', '')).title()})"

        key = str(i)
        if key not in res_map:
            fill, disp = NO_DATA, "not loaded yet - refresh to load more"
        else:
            results = res_map[key]
            fill, disp = _village_style(results, metric)
            extra = _village_summary(results, metric)
            if extra:
                disp = f"{disp}  |  {extra}"

        feats.append({
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {
                "district": label,
                "val": disp,
                "_fill": fill,
            },
        })

    if not feats:
        return None

    return {"type": "FeatureCollection", "features": feats}


def _pct_of(results, key, cls):
    """% of samples in `cls` for one nutrient dict, or None."""
    d = (results or {}).get(key) or {}
    tot = sum(int(v or 0) for v in d.values())
    if not tot:
        return None
    return round(100 * int(d.get(cls, 0) or 0) / tot)


def _village_summary(results, metric):
    """Compact all-nutrient readout for the tooltip (skips the metric
    already shown as the main value)."""
    if not results:
        return ""
    parts = []

    lows = []
    for lab, key in (("N", "n"), ("P", "p"), ("K", "k"), ("OC", "OC")):
        if _M2V.get(metric, ("",))[0] == key:
            continue
        v = _pct_of(results, key, "Low")
        if v is not None:
            lows.append(f"{lab} {v}")
    if lows:
        parts.append("low%: " + " · ".join(lows))

    if metric != "ph":
        d = results.get("pH") or {}
        tot = sum(int(v or 0) for v in d.values())
        if tot:
            dom = max(d, key=lambda k: int(d[k] or 0))
            parts.append(f"pH {dom}")

    defs = []
    for lab, key in (("S", "S"), ("Zn", "Zn"), ("Fe", "Fe"),
                     ("B", "B"), ("Mn", "Mn"), ("Cu", "Cu")):
        if _M2V.get(metric, ("",))[0] == key:
            continue
        v = _pct_of(results, key, "Deficient")
        if v is not None:
            defs.append(f"{lab} {v}")
    if defs:
        parts.append("def%: " + " · ".join(defs))

    return "  ·  ".join(parts)


def _village_style(results, metric):
    """(fill colour, display text) for one village's counts."""
    if not results:
        return NO_DATA, "no lab samples this cycle"

    if metric == "ph":
        d = results.get("pH") or {}
        tot = sum(int(v or 0) for v in d.values())
        if not tot:
            return NO_DATA, "no lab samples this cycle"
        dom = max(d, key=lambda k: int(d[k] or 0))
        return (PH_COLORS.get(dom, NO_DATA),
                f"{dom} ({int(d[dom])}/{tot} samples)")

    key, cls = _M2V[metric]
    d = results.get(key) or {}
    tot = sum(int(v or 0) for v in d.values())
    if not tot:
        return NO_DATA, "no lab samples this cycle"
    v = int(d.get(cls, 0) or 0)
    pct = round(100 * v / tot)
    return _pct_color(pct), f"{pct}% ({v}/{tot} samples)"
