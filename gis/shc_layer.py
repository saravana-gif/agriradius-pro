"""SHC district choropleth - paint MEASURED soil-test status on the map.

Joins the bundled Soil Health Card nutrient table
(data/reference/shc_district_nutrients.csv, real lab samples) onto a
tiny simplified district-boundary file
(data/reference/shc_districts.geojson, ~135 KB) and returns a GeoJSON
dict whose features carry a precomputed fill colour + display text,
ready for folium. Pure data prep - no folium, no streamlit.
"""

import base64
import gzip
import json
from functools import lru_cache

from config import PROJECT_ROOT

_REF = PROJECT_ROOT / "data" / "reference"
DISTRICTS_GJ = _REF / "shc_districts.geojson"
DISTRICTS_B64 = _REF / "shc_districts.geojson.gz.b64"


def _read_districts():
    """Load the district GeoJSON (prefers the compact gz+base64 copy)."""
    if DISTRICTS_B64.exists():
        blob = DISTRICTS_B64.read_text().replace("\n", "").strip()
        return json.loads(gzip.decompress(base64.b64decode(blob)))
    if DISTRICTS_GJ.exists():
        return json.loads(DISTRICTS_GJ.read_text())
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


@lru_cache(maxsize=4)
def geojson_for(metric):
    """GeoJSON dict for `metric`; features carry _fill, district, val.

    Cached per metric (the source file is ~135 KB, so at most a few
    hundred KB resident - safe on the small server).
    """
    if metric not in METRICS:
        return None

    _, col, kind = METRICS[metric]

    gj = _read_districts()
    if gj is None:
        return None

    for f in gj["features"]:
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

        f["properties"] = {
            "district": name,
            "val": disp,
            "_fill": fill,
        }

    return gj
