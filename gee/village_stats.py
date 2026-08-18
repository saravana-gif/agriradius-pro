"""Per-village crop insights.

For every village in the buffer: cropland acres, cropping pattern,
cycles/year and mean NDVI - computed in two Earth Engine calls
(area + 24-month NDVI stack, both reduced per village polygon).
"""

import ee
import pandas as pd
import streamlit as st

from core.crop_cycle import to_dataframe, analyze_series
from gee.dynamic_world import dw_crops_mask
from gee.ndvi import ndvi_monthly_stack
from gis.spatial import villages_in_buffer

SQM_PER_ACRE = 4046.8564224

# Above this many villages the per-village reduction gets very slow.
# Rather than refuse (which made a 38 km report simply lose its
# village table), rank the villages and analyse the largest
# MAX_VILLAGES of them.
MAX_VILLAGES = 300


def _rank_and_cap(gdf, max_villages):
    """Keep the largest `max_villages` polygons; report what was cut.

    Ranked by POLYGON AREA, not by distance from the centre. Taking
    the nearest N would quietly shrink a 38 km request back to ~27 km
    and hide the fact; taking the largest keeps the full footprint and
    drops only the smallest villages, which carry the least farmland.
    Cropland area would be the ideal ranking, but that is the very
    thing the expensive Earth Engine call computes - polygon area is
    the best proxy available before paying for it.
    """
    total = len(gdf)
    if total <= max_villages:
        return gdf, None

    ranked = gdf.copy()
    try:
        # Project before measuring: degrees are not an area.
        ranked["_area"] = ranked.to_crs(
            ranked.estimate_utm_crs()).geometry.area
    except Exception:
        ranked["_area"] = ranked.geometry.area   # last resort
    ranked = ranked.sort_values("_area", ascending=False)
    kept = ranked.head(max_villages).drop(columns=["_area"])

    note = (
        f"{total} villages fall inside this radius, above the "
        f"{max_villages} the per-village analysis can handle. The "
        f"{max_villages} LARGEST by area are analysed here and "
        f"{total - max_villages} smaller ones are not - ranked by "
        f"village area, so the full radius is still covered rather "
        f"than quietly cropped to a smaller circle. The village "
        f"table below is therefore the largest {max_villages}, not "
        f"every village in the circle.")
    return kept.reset_index(drop=True), note


def _to_feature_collection(gdf):
    """Simplified village polygons -> ee.FeatureCollection."""

    slim = gdf[["geometry"]].copy()
    slim["idx"] = range(len(gdf))

    # Simplify to keep the upload small (~50m tolerance)
    slim["geometry"] = slim.geometry.simplify(0.0005)

    return ee.FeatureCollection(slim.__geo_interface__)


@st.cache_data(show_spinner="Computing village insights (1-3 min)...")
def village_insights(lat, lon, radius_km, year):
    """Return a DataFrame: one row per village with crop insights."""

    gdf = villages_in_buffer(lat, lon, radius_km)

    if gdf.empty:
        return pd.DataFrame()

    gdf, cap_note = _rank_and_cap(gdf, MAX_VILLAGES)

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    start, end = f"{year - 1}-01-01", f"{year}-12-31"

    fc = _to_feature_collection(gdf)

    # --- Call 1: cropland area per village ---
    crops = dw_crops_mask(buffer, start, end)

    area_fc = (
        ee.Image.pixelArea()
        .updateMask(crops)
        .reduceRegions(
            collection=fc,
            reducer=ee.Reducer.sum(),
            scale=30,
            tileScale=4,
        )
        .getInfo()
    )

    # --- Call 2: monthly NDVI means per village ---
    stack, months = ndvi_monthly_stack(buffer, year - 1, year)

    ndvi_fc = (
        stack.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=60,
            tileScale=4,
        )
        .getInfo()
    )

    crop_area = {
        f["properties"]["idx"]: f["properties"].get("sum", 0)
        for f in area_fc["features"]
    }

    ndvi_props = {
        f["properties"]["idx"]: f["properties"]
        for f in ndvi_fc["features"]
    }

    rows = []

    for i in range(len(gdf)):

        rec = gdf.iloc[i]

        acres = round((crop_area.get(i) or 0) / SQM_PER_ACRE, 1)

        props = ndvi_props.get(i, {})
        series = [
            (label, props.get(band)) for band, label in months
        ]

        has_data = any(v is not None for _, v in series)

        if has_data and acres > 0:
            insight = analyze_series(to_dataframe(series))
            pattern = insight["pattern"]
            cycles = insight["cycles_per_year"]
            mean_ndvi = insight["mean_ndvi"]
        else:
            pattern = "No cropland data"
            cycles = 0.0
            mean_ndvi = 0.0

        rows.append({
            "Village": rec.get("vilname11", f"Village {i}"),
            "Taluk": rec.get("sdtname", ""),
            "District": rec.get("dtname", ""),
            "Cropland (ac)": acres,
            "Pattern": pattern,
            "Cycles/Year": cycles,
            "Mean NDVI": mean_ndvi,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(
        "Cropland (ac)", ascending=False).reset_index(drop=True)

    # Carried on the frame so the UI and the PDF can both say the
    # table is a capped subset. A truncated table that does not admit
    # it is worse than no table.
    df.attrs["cap_note"] = cap_note
    df.attrs["villages_analysed"] = len(df)
    return df
