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

# Above this many villages the per-village reduction gets very slow;
# ask the user to shrink the radius instead.
MAX_VILLAGES = 300


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

    if len(gdf) > MAX_VILLAGES:
        raise ValueError(
            f"{len(gdf)} villages in buffer - too many for per-village "
            f"analysis (max {MAX_VILLAGES}). Reduce the radius."
        )

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

    return df.sort_values(
        "Cropland (ac)", ascending=False
    ).reset_index(drop=True)
