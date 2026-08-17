"""Irrigation-source choropleth - measured government statistics.

Paints Karnataka's district boundaries by how the land is irrigated:
total irrigated area, and the share coming from borewells, canals,
tanks and dug wells. The borewell/canal split is the operationally
useful one - it tells field staff whether a canal command-area map
will find farms for them or whether they need satellite screening.

Joins core/irrigation.py onto the same simplified district boundary
file the SHC layer uses, and clips to the analysis circle. Pure data
prep - no folium, no streamlit.
"""

from core import irrigation

NO_DATA = "#d9d9d9"

# metric key -> (label, unit, kind)
METRICS = {
    "net_ac": ("Irrigated area (acres)", "ac", "area"),
    "borewell_pct": ("Borewell / tubewell share (%)", "%", "pct"),
    "canal_pct": ("Canal share (%)", "%", "pct"),
    "tank_pct": ("Tank share (%)", "%", "pct"),
    "well_pct": ("Open / dug well share (%)", "%", "pct"),
    "dominant": ("Dominant irrigation source", "", "cat"),
    "intensity": ("Gross : net irrigated (cropping intensity)", "x",
                  "ratio"),
}

_BINS = {
    "net_ac": [(400000, "#08519c"), (200000, "#3182bd"),
               (100000, "#6baed6"), (40000, "#bdd7e7"),
               (1, "#eff3ff")],
    "borewell_pct": [(85, "#7f2704"), (60, "#d94801"),
                     (35, "#fd8d3c"), (10, "#fdd0a2"),
                     (0.1, "#feedde")],
    "canal_pct": [(50, "#08306b"), (30, "#2171b5"), (15, "#6baed6"),
                  (5, "#c6dbef"), (0.1, "#f7fbff")],
    "tank_pct": [(10, "#00441b"), (5, "#238b45"), (2, "#74c476"),
                 (0.5, "#c7e9c0"), (0.1, "#f7fcf5")],
    "well_pct": [(30, "#3f007d"), (15, "#6a51a3"), (7, "#9e9ac8"),
                 (2, "#dadaeb"), (0.1, "#fcfbfd")],
    "intensity": [(1.6, "#004529"), (1.35, "#238443"),
                  (1.15, "#78c679"), (1.02, "#d9f0a3"),
                  (0.01, "#ffffe5")],
}

# Categorical palette for the dominant-source view.
_SOURCE_COLOUR = {
    "Borewell/Tubewell": "#d94801",
    "Canal (Government)": "#2171b5",
    "Canal (Private)": "#6baed6",
    "Tank": "#238b45",
    "Open/Dug Well": "#6a51a3",
    "Other Source": "#969696",
}


def metric_options():
    return [(k, v[0]) for k, v in METRICS.items()]


def _value(row, metric):
    if metric == "dominant":
        return row.get("dominant")
    return row.get(metric)


def _colour(value, metric):
    if value in (None, ""):
        return NO_DATA
    if metric == "dominant":
        return _SOURCE_COLOUR.get(value, NO_DATA)
    for threshold, colour in _BINS.get(metric, _BINS["borewell_pct"]):
        try:
            if float(value) >= threshold:
                return colour
        except (TypeError, ValueError):
            return NO_DATA
    return NO_DATA


def legend_items(metric):
    """[(label, colour)] for the map legend."""
    if metric == "dominant":
        return [(name.replace("/", " / "), col)
                for name, col in _SOURCE_COLOUR.items()] + \
               [("no data", NO_DATA)]
    bins = _BINS.get(metric, _BINS["borewell_pct"])
    unit = METRICS.get(metric, METRICS["borewell_pct"])[1]

    def fmt(v):
        return f"{int(v):,}" if v >= 1 else "under 1"

    items = [(f"{fmt(bins[0][0])}+ {unit}".strip(), bins[0][1])]
    for i in range(1, len(bins)):
        items.append((f"{fmt(bins[i][0])}-{fmt(bins[i-1][0])} "
                      f"{unit}".strip(), bins[i][1]))
    items.append(("no data", NO_DATA))
    return items


def _tooltip(row):
    bits = [f"{row['net_ac']:,} ac net irrigated"]
    sh = row.get("shares") or {}
    parts = []
    for col, label in irrigation.SOURCES:
        v = sh.get(col)
        if v:
            parts.append(f"{label} {v}%")
    if parts:
        bits.append(" · ".join(parts))
    if row.get("intensity"):
        bits.append(f"gross:net {row['intensity']}x")
    bits.append(irrigation.VINTAGE)
    return "  |  ".join(bits)


def geojson_for(metric, lat, lon, radius_km):
    """District polygons in the circle, coloured by irrigation source.

    Returns None outside Karnataka or when the statistics are missing.
    """
    if metric not in METRICS:
        metric = "borewell_pct"
    if not irrigation.available():
        return None

    from gis.shc_layer import _circle, _read_districts

    gj = _read_districts()
    if not gj or not gj.get("features"):
        return None

    from shapely.geometry import mapping, shape

    circle = _circle(lat, lon, radius_km)

    feats, painted = [], 0
    for f in gj["features"]:
        props = f.get("properties") or {}
        if not str(props.get("state", "")).lower().startswith("karn"):
            continue
        row = irrigation.for_district(props.get("district"))
        if not row:
            continue
        try:
            geom = shape(f["geometry"]).buffer(0)
            clipped = geom.intersection(circle)
            if clipped.is_empty:
                continue
        except Exception:
            continue

        fill = _colour(_value(row, metric), metric)
        painted += 1
        feats.append({
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {
                "district": f"{row['district']} (Karnataka)",
                "val": _tooltip(row),
                "_fill": fill,
            },
        })

    if not painted:
        return None
    return {"type": "FeatureCollection", "features": feats}
