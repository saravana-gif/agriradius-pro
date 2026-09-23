"""Field parcels as a map layer - the individual fields, drawn.

The Field Parcels tab already counts them and reports the size
distribution. This draws them, which is a different job: a median of
0.29 ac is a number you have to trust, whereas a screen full of tiny
polygons against the satellite image is something you can check
against what you can see.

Coloured BY SIZE, because size is the sourcing question. How many
owners stand between you and a tonne of produce is decided by the
parcel size distribution, not by the total area.

Everything here reads from core.field_boundaries, so the FTW caveat
travels with it: these are remote-sensing field units, not legal
parcels, and they carry no survey number.
"""

# Acres -> fill colour. Breaks chosen for South Indian smallholdings,
# where almost everything falls under 5 ac and a single "small vs
# large" split would paint the whole map one colour.
SIZE_BREAKS = [
    (0.5, "#08519c", "under 0.5 ac"),
    (1.0, "#3182bd", "0.5 - 1 ac"),
    (2.0, "#6baed6", "1 - 2 ac"),
    (5.0, "#bdd7e7", "2 - 5 ac"),
    (10.0, "#fdae6b", "5 - 10 ac"),
    (25.0, "#e6550d", "10 - 25 ac"),
    (float("inf"), "#a63603", "25 ac and over"),
]

# A browser will not draw 20,000 polygons without the page becoming
# unusable, and the parcel read is already capped at that. Draw the
# densest subset that stays responsive and SAY when some are hidden -
# a thinned layer that looks complete would misrepresent the ground.
MAX_DRAWN = 4000


def _colour(acres):
    for limit, colour, _label in SIZE_BREAKS:
        if acres < limit:
            return colour
    return SIZE_BREAKS[-1][1]


def _band(acres):
    for limit, _colour, label in SIZE_BREAKS:
        if acres < limit:
            return label
    return SIZE_BREAKS[-1][2]


def legend():
    """[(label, colour)] for the map legend, largest last."""
    return [(label, colour) for _lim, colour, label in SIZE_BREAKS]


def geojson_parcels(gdf, max_drawn=MAX_DRAWN):
    """(geojson, info) for a parcel GeoDataFrame from field_boundaries.

    Returns (None, info) when there is nothing to draw. `info` always
    explains what happened, including how many parcels were left out,
    so the caller can say so rather than showing a partial layer as
    though it were the whole set.
    """
    info = {"drawn": 0, "total": 0, "hidden": 0, "note": None}

    if gdf is None or len(gdf) == 0:
        info["note"] = "No field parcels to draw."
        return None, info

    SQM_PER_ACRE = 4046.8564224
    info["total"] = len(gdf)

    try:
        if "area_m2" in gdf.columns and gdf["area_m2"].notna().any():
            acres = gdf["area_m2"] / SQM_PER_ACRE
        else:
            acres = (gdf.to_crs(gdf.estimate_utm_crs()).area
                     / SQM_PER_ACRE)
    except Exception as e:
        info["note"] = f"Parcel areas could not be computed: {e}"
        return None, info

    g = gdf.copy()
    g["_acres"] = acres.values

    # Keep the LARGEST when thinning. A random sample would scatter
    # holes through the layer and read as missing fields; keeping the
    # biggest keeps the picture honest about what is there, and the
    # note says how many small ones were dropped.
    if len(g) > max_drawn:
        g = g.nlargest(max_drawn, "_acres")
        info["hidden"] = info["total"] - len(g)
        info["note"] = (
            f"Showing the {len(g):,} largest of {info['total']:,} "
            f"parcels - {info['hidden']:,} smaller ones are not drawn, "
            f"so the map looks emptier than the ground is. The counts "
            f"in the Field Parcels tab cover all of them.")

    feats = []
    for geom, ac in zip(g.geometry, g["_acres"]):
        if geom is None or geom.is_empty:
            continue
        try:
            feats.append({
                "type": "Feature",
                "geometry": geom.__geo_interface__,
                "properties": {
                    "_fill": _colour(float(ac)),
                    "district": f"{float(ac):,.2f} ac",   # tooltip key
                    "val": _band(float(ac)),
                },
            })
        except Exception:
            continue

    if not feats:
        info["note"] = "Parcel geometry could not be converted."
        return None, info

    info["drawn"] = len(feats)
    return {"type": "FeatureCollection", "features": feats}, info


def caption(info):
    """One line describing what the layer is showing."""
    if not info or not info.get("drawn"):
        return info.get("note") if info else None
    base = (f"{info['drawn']:,} field parcels drawn, coloured by "
            f"size. Blue = smallholdings, orange = larger holdings.")
    return f"{base} {info['note']}" if info.get("note") else base
