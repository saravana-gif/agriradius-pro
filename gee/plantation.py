"""Plantation detection - separate coconut/arecanut from forest.

At 10m resolution the planting-row pattern is invisible, but
plantations differ from natural (dry-deciduous) forest in three
computable ways:

1. Dry-season greenness: irrigated palms stay green Feb-Apr while
   deciduous forest browns down.
2. Terrain: plantations are on flat land, forest mostly on slopes.
3. Patch size: forests form large contiguous blocks; plantations
   are small patches inside the farmland mosaic.

Tree pixels satisfying all three -> 'Plantation'. Banana mostly
classifies as crops (it is a herb, not a tree) and is covered by
the cropland analysis.
"""

import ee
import streamlit as st

from gee.dynamic_world import dw_class_image
from gee.ndvi import _mask_clouds

SQM_PER_ACRE = 4046.8564224

# --- Tuning constants ---
MAX_SLOPE_DEG = 15        # plantations sit on flat-ish land
DRY_GREEN_NDVI = 0.35     # still green in dry season (Feb-Apr);
                          # 10m palm pixels mix canopy with soil so
                          # the effective NDVI is lower than canopy
FOREST_PATCH_PX = 1000    # ~10 ha at 10m; bigger patches = forest

PLANTATION_COLOR = "ff9800"  # orange


def _dry_season_ndvi(buffer, year):
    """Median NDVI for Feb-Apr (peak dry season)."""

    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(buffer)
        .filterDate(f"{year}-02-01", f"{year}-04-30")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        .map(_mask_clouds)
    )

    return col.map(
        lambda i: i.normalizedDifference(["B8", "B4"])
    ).median()


def plantation_mask(buffer, year):
    """Binary mask: tree pixels that behave like plantations."""

    trees = dw_class_image(
        buffer, f"{year}-01-01", f"{year}-12-31"
    ).eq(1)

    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
    flat = slope.lte(MAX_SLOPE_DEG)

    dry_green = _dry_season_ndvi(buffer, year).gte(DRY_GREEN_NDVI)

    patch_px = trees.selfMask().connectedPixelCount(
        FOREST_PATCH_PX, True)
    small_patch = patch_px.lt(FOREST_PATCH_PX)

    return (
        trees.And(flat).And(dry_green).And(small_patch)
        .rename("plantation")
    )


@st.cache_data(show_spinner="Detecting plantations (coconut/arecanut)...")
def plantation_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL showing likely plantations in orange."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = plantation_mask(buffer, year)

    img = mask.updateMask(mask).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", PLANTATION_COLOR]})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Measuring plantation area...")
def plantation_stats(lat, lon, radius_km, year):
    """Plantation acres and share of the tree class."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = plantation_mask(buffer, year)

    trees = dw_class_image(
        buffer, f"{year}-01-01", f"{year}-12-31"
    ).eq(1)

    img = ee.Image.cat([
        ee.Image.pixelArea().updateMask(mask).rename("plantation"),
        ee.Image.pixelArea().updateMask(trees).rename("trees"),
    ])

    stats = img.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=buffer,
        scale=30,
        maxPixels=1e13,
        bestEffort=True,
    ).getInfo()

    plant_ac = round((stats.get("plantation") or 0) / SQM_PER_ACRE, 2)
    trees_ac = round((stats.get("trees") or 0) / SQM_PER_ACRE, 2)

    return {
        "plantation_ac": plant_ac,
        "trees_ac": trees_ac,
        "plantation_pct": round(100 * plant_ac / trees_ac, 1)
        if trees_ac else 0.0,
    }
