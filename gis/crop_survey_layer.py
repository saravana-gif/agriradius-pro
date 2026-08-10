"""Coconut crop-survey choropleth - paint MEASURED coconut on the map.

Joins the bundled per-village coconut survey aggregates
(core/crop_survey.py, from the Karnataka 2023-24 crop survey) onto the
village boundary polygons inside the analysis circle and returns a
GeoJSON dict whose features carry a precomputed fill colour plus the
tooltip text, ready for folium. Output is clipped to the buffer.

This is ground-recorded data, not a satellite guess - it is the
strongest cross-check the app has for its plantation detection.

Pure data prep - no folium, no streamlit.
"""

from core import crop_survey

# metric key -> (label shown in the UI, tooltip unit)
METRICS = {
    "intensity": ("Coconut intensity (% of village area)", "%"),
    "extent_ac": ("Coconut land recorded (acres)", "ac"),
    "parcels": ("Coconut plots recorded (count)", "plots"),
    "farmers": ("Coconut growers (count)", "growers"),
}

NO_DATA = "#e3e3e3"

# (threshold, colour) - first bin whose threshold is met wins.
_BINS = {
    "intensity": [(40, "#004b23"), (25, "#087f23"), (15, "#38b000"),
                  (7, "#9ef01a"), (0.1, "#eaf7c6")],
    "extent_ac": [(1500, "#004b23"), (700, "#087f23"), (300, "#38b000"),
                  (80, "#9ef01a"), (0.1, "#eaf7c6")],
    "parcels": [(600, "#004b23"), (250, "#087f23"), (100, "#38b000"),
                (25, "#9ef01a"), (0.1, "#eaf7c6")],
    "farmers": [(300, "#004b23"), (150, "#087f23"), (60, "#38b000"),
                (15, "#9ef01a"), (0.1, "#eaf7c6")],
}


def metric_options():
    """[(key, label)] for the sidebar selectbox."""
    return [(k, v[0]) for k, v in METRICS.items()]


def _value(row, metric):
    if metric == "intensity":
        return crop_survey.density_pct(row)
    if metric == "extent_ac":
        return round(row["extent_ha"] * crop_survey.HA_TO_AC)
    if metric == "parcels":
        return int(row["parcels"])
    if metric == "farmers":
        return int(row["farmers"])
    return None


def _colour(value, metric):
    if value is None:
        return NO_DATA
    for threshold, colour in _BINS.get(metric, _BINS["intensity"]):
        if value >= threshold:
            return colour
    return NO_DATA


def legend_items(metric):
    """[(label, colour)] for the map legend caption."""
    bins = _BINS.get(metric, _BINS["intensity"])
    unit = METRICS.get(metric, METRICS["intensity"])[1]
    items = [(f"{int(bins[0][0])}+ {unit}", bins[0][1])]
    for i in range(1, len(bins)):
        low = bins[i][0]
        high = bins[i - 1][0]
        low_txt = "under 1" if low < 1 else str(int(low))
        items.append((f"{low_txt}-{int(high)} {unit}", bins[i][1]))
    items.append(("not in the survey", NO_DATA))
    return items


def _tooltip(row):
    ac = round(row["extent_ha"] * crop_survey.HA_TO_AC)
    dens = crop_survey.density_pct(row)
    bits = [
        f"{ac:,} ac of coconut recorded",
        f"{int(row['parcels']):,} plots · {int(row['farmers']):,} growers",
    ]
    if dens is not None:
        bits.append(f"intensity {dens}% of village area")
    bits.append(f"{int(row['irrigated_pct'])}% of plots irrigated")
    bits.append(crop_survey.VINTAGE)
    return "  ·  ".join(bits)


def geojson_villages(metric, lat, lon, radius_km):
    """Village polygons in the circle, coloured by measured coconut.

    Villages the survey does not list stay pale grey. Returns None when
    there is nothing to draw (outside the covered districts, or no
    village boundaries available here).
    """
    if metric not in METRICS:
        metric = "intensity"

    if not crop_survey.available():
        return None

    # Nothing to paint outside the covered districts - skip the (much
    # heavier) boundary read entirely.
    if not crop_survey.in_radius(lat, lon, radius_km):
        return None

    from gis.spatial import villages_in_buffer
    from gis.shc_layer import MAX_VILLAGE_POLYS, _circle, _village_tol

    try:
        gdf = villages_in_buffer(lat, lon, radius_km)
    except Exception:
        return None
    if gdf is None or gdf.empty or "vilcode11" not in gdf.columns:
        return None

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

        row = crop_survey.by_vilcode(r.get("vilcode11", ""))
        if row:
            value = _value(row, metric)
            fill = _colour(value, metric)
            disp = _tooltip(row)
            painted += 1
        else:
            fill = NO_DATA
            disp = ("no coconut recorded in the 2023-24 crop survey "
                    "(survey covers Hassan, Mandya, Tumakuru, "
                    "Ramanagara, Chitradurga, Mysuru)")

        name = str(r.get("vilname11", "?")).title()
        label = f"{name} ({str(r.get('dtname', '')).title()})"

        feats.append({
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {"district": label, "val": disp,
                           "_fill": fill},
        })

    if not feats or not painted:
        return None

    return {"type": "FeatureCollection", "features": feats}
