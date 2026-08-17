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


# ------------------------------------------------------------------
# VILLAGE resolution - measured per village, like the SHC layer.
# ------------------------------------------------------------------

VILLAGE_METRICS = {
    "irrigated_pct": ("Irrigated share of cropland (%)", "%"),
    "irrigated_ac": ("Irrigated area (acres)", "ac"),
    "borewell_fed_ac": ("Borewell-fed area (acres)", "ac"),
    "agree_2plus_ac": ("Confirmed by 2+ methods (acres)", "ac"),
    "radar_event_ac": ("Radar irrigation events (acres)", "ac"),
}

_V_BINS = {
    "irrigated_pct": [(50, "#08519c"), (30, "#3182bd"),
                      (15, "#6baed6"), (5, "#bdd7e7"),
                      (0.1, "#eff3ff")],
    "irrigated_ac": [(800, "#08519c"), (400, "#3182bd"),
                     (150, "#6baed6"), (40, "#bdd7e7"),
                     (0.1, "#eff3ff")],
    "borewell_fed_ac": [(600, "#7f2704"), (300, "#d94801"),
                        (120, "#fd8d3c"), (30, "#fdd0a2"),
                        (0.1, "#feedde")],
    "agree_2plus_ac": [(500, "#00441b"), (250, "#238b45"),
                       (100, "#74c476"), (25, "#c7e9c0"),
                       (0.1, "#f7fcf5")],
    "radar_event_ac": [(800, "#7a0177"), (400, "#c51b8a"),
                       (150, "#f768a1"), (40, "#fbb4b9"),
                       (0.1, "#feebe2")],
}


def village_metric_options():
    return [(k, v[0]) for k, v in VILLAGE_METRICS.items()]


def _v_colour(value, metric):
    if value in (None, ""):
        return NO_DATA
    try:
        v = float(value)
    except (TypeError, ValueError):
        return NO_DATA
    for threshold, colour in _V_BINS.get(metric,
                                         _V_BINS["irrigated_pct"]):
        if v >= threshold:
            return colour
    return NO_DATA


def village_legend_items(metric):
    bins = _V_BINS.get(metric, _V_BINS["irrigated_pct"])
    unit = VILLAGE_METRICS.get(metric,
                               VILLAGE_METRICS["irrigated_pct"])[1]

    def fmt(v):
        return f"{int(v):,}" if v >= 1 else "under 1"

    items = [(f"{fmt(bins[0][0])}+ {unit}", bins[0][1])]
    for i in range(1, len(bins)):
        items.append((f"{fmt(bins[i][0])}-{fmt(bins[i-1][0])} {unit}",
                      bins[i][1]))
    items.append(("no cropland / not measured", NO_DATA))
    return items


def _village_tooltip(row):
    bits = []
    if row.get("irrigated_pct") is not None:
        bits.append(f"{row['irrigated_pct']}% of cropland irrigated")
    if row.get("irrigated_ac") is not None:
        bits.append(f"{row['irrigated_ac']:,.0f} ac irrigated of "
                    f"{(row.get('cropland_ac') or 0):,.0f} ac cropland")
    if row.get("agree_2plus_ac") is not None:
        bits.append(f"{row['agree_2plus_ac']:,.0f} ac confirmed by 2+ "
                    f"methods")
    if row.get("radar_event_ac") is not None:
        bits.append(f"{row['radar_event_ac']:,.0f} ac with radar "
                    f"wetting events")
    if row.get("borewell_fed_ac") is not None:
        bits.append(f"{row['borewell_fed_ac']:,.0f} ac likely "
                    f"borewell-fed")
    if row.get("district_dominant_source"):
        bits.append(f"district mix: "
                    f"{row.get('district_borewell_pct')}% borewell / "
                    f"{row.get('district_canal_pct')}% canal "
                    f"(district figure, not this village)")
    bits.append("measured from satellite for THIS village polygon")
    return "  |  ".join(bits)


def _reason(text):
    """Record WHY the village layer could not draw, for the UI to show.

    Silent fallbacks are indistinguishable from missing data, which
    wasted real debugging time once. Every early return says why.
    """
    try:
        import streamlit as st
        st.session_state["irrigation_village_reason"] = text
    except Exception:
        pass
    return None


def geojson_villages(metric, lat, lon, radius_km, year):
    """Village polygons coloured by their OWN measured irrigation.

    Mirrors the SHC village layer: real per-village numbers, not a
    district value spread across villages. Returns None when nothing
    could be measured - and records the reason.
    """
    if metric not in VILLAGE_METRICS:
        metric = "irrigated_pct"

    try:
        import streamlit as st
        st.session_state.pop("irrigation_village_reason", None)
    except Exception:
        pass

    try:
        from gee.village_irrigation import village_irrigation
        df = village_irrigation(lat, lon, radius_km, year)
    except Exception as e:
        return _reason(
            f"the per-village Earth Engine pass failed "
            f"({type(e).__name__}: {e})")
    if df is None or df.empty:
        return _reason(
            "the per-village Earth Engine pass returned no rows - "
            "usually no village boundaries or no cropland inside the "
            "circle")

    by_code = {}
    by_name = {}
    for _, r in df.iterrows():
        d = r.to_dict()
        if d.get("vilcode11"):
            by_code[str(d["vilcode11"])] = d
        by_name[(str(d.get("village", "")).lower(),
                 str(d.get("district", "")).lower())] = d

    from gis.spatial import villages_in_buffer
    from gis.shc_layer import MAX_VILLAGE_POLYS, _circle, _village_tol

    try:
        gdf = villages_in_buffer(lat, lon, radius_km)
    except Exception as e:
        return _reason(f"village boundaries could not be read ({e})")
    if gdf is None or gdf.empty:
        return _reason(
            "no village boundaries are available for this area")

    gdf = gdf.copy()
    dedupe = [c for c in ("stname", "dtname", "vilname11", "vilcode11")
              if c in gdf.columns]
    if dedupe:
        gdf = gdf.drop_duplicates(subset=dedupe)
    if len(gdf) > MAX_VILLAGE_POLYS:
        b = gdf.geometry.bounds
        gdf["_d2"] = ((b.minx + b.maxx) / 2 - lon) ** 2 + \
                     ((b.miny + b.maxy) / 2 - lat) ** 2
        gdf = gdf.nsmallest(MAX_VILLAGE_POLYS, "_d2")

    from shapely.geometry import mapping

    circle = _circle(lat, lon, radius_km)
    tol = _village_tol(len(gdf))

    feats, painted = [], 0
    for _, r in gdf.iterrows():
        try:
            geom = r.geometry.simplify(tol, preserve_topology=True)
            clipped = geom.buffer(0).intersection(circle)
            if clipped.is_empty:
                continue
        except Exception:
            continue

        row = by_code.get(str(r.get("vilcode11", ""))) or by_name.get(
            (str(r.get("vilname11", "")).lower(),
             str(r.get("dtname", "")).lower()))

        if row:
            fill = _v_colour(row.get(metric), metric)
            disp = _village_tooltip(row)
            painted += 1
        else:
            fill = NO_DATA
            disp = "not measured in this run"

        name = str(r.get("vilname11", "?")).title()
        feats.append({
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {
                "district": f"{name} "
                            f"({str(r.get('dtname', '')).title()})",
                "val": disp,
                "_fill": fill,
            },
        })

    if not painted:
        return _reason(
            f"{len(feats)} village polygons were drawn but none could "
            f"be matched to a measured row (village name/code mismatch "
            f"between the boundary file and the measurement)")
    return {"type": "FeatureCollection", "features": feats}


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
