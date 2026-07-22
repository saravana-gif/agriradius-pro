"""Paddy (rice) detection from Sentinel-1 radar.

Signature: transplanted paddy fields are flooded (very low VH
backscatter - water looks 'black' to radar), then backscatter rises
sharply as the rice canopy grows. Flood-then-growth over cropland
= paddy. Radar sees through clouds, so monsoon seasons are covered.
"""

import ee
import streamlit as st

from gee.dynamic_world import dw_crops_mask

SQM_PER_ACRE = 4046.8564224

# Tuning constants (dB)
FLOOD_DB = -20      # VH below this at some point = flooded field
GROWTH_DB = 8       # min->max rise above this = strong canopy growth

PADDY_COLOR = "00e5ff"  # cyan


def _s1_collection(buffer, start_date, end_date):

    return (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(buffer)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.listContains(
            "transmitterReceiverPolarisation", "VH"))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .select("VH")
    )


def paddy_mask(buffer, start_date, end_date):
    """Binary paddy mask (1 = paddy) over cropland."""

    col = _s1_collection(buffer, start_date, end_date)

    # Speckle-smoothed seasonal extremes
    vh_min = col.min().focal_median(30, "circle", "meters")
    vh_max = col.max().focal_median(30, "circle", "meters")

    flooded = vh_min.lt(FLOOD_DB)
    growth = vh_max.subtract(vh_min).gt(GROWTH_DB)

    crops = dw_crops_mask(buffer, start_date, end_date)

    return flooded.And(growth).And(crops).rename("paddy")


@st.cache_data(show_spinner="Detecting paddy fields (radar)...")
def paddy_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL showing detected paddy in cyan."""

    from core import compute as _cq
    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = paddy_mask(
        buffer, f"{year}-01-01", f"{year}-12-31"
    ).reproject(crs="EPSG:3857", scale=_cq.tile_px())

    img = mask.updateMask(mask).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", PADDY_COLOR]})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Measuring paddy area (radar)...")
def paddy_stats(lat, lon, radius_km, year):
    """Paddy acres and share of cropland inside the buffer."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    start, end = f"{year}-01-01", f"{year}-12-31"

    mask = paddy_mask(buffer, start, end)
    crops = dw_crops_mask(buffer, start, end)

    img = ee.Image.cat([
        ee.Image.pixelArea().updateMask(mask).rename("paddy"),
        ee.Image.pixelArea().updateMask(crops).rename("cropland"),
    ])

    from core import compute as _cq
    stats = img.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=buffer,
        scale=_cq.stat_scale(),
        maxPixels=1e13,
        bestEffort=True,
        tileScale=_cq.tile_scale(),
    ).getInfo()

    paddy_ac = round((stats.get("paddy") or 0) / SQM_PER_ACRE, 2)
    crop_ac = round((stats.get("cropland") or 0) / SQM_PER_ACRE, 2)

    return {
        "paddy_ac": paddy_ac,
        "cropland_ac": crop_ac,
        "paddy_pct": round(100 * paddy_ac / crop_ac, 1) if crop_ac else 0.0,
    }
