"""Plantation detection - separate coconut/arecanut from forest.

At 10m resolution the planting-row pattern is invisible, but in
dry-deciduous belts plantations differ from natural forest in two
computable ways:

1. Dry-season greenness: irrigated palms stay green Feb-Apr while
   deciduous forest browns down.
2. Terrain: plantations are on flat-ish land, forest on slopes.

Candidates are pixels with meaningful Dynamic World 'trees'
probability (palms often split between trees and crops classes).
Banana classifies as cropland and is covered by the crop analyses.
"""

import ee
import streamlit as st

from gee.dynamic_world import dw_class_image
from gee.features import feature_stack

SQM_PER_ACRE = 4046.8564224

# --- Tuning constants ---
# CALIBRATED to ground truth: 87 confirmed-coconut villages in
# Srirangapatna (Mandya) from the FRUITS/Bhoomi crop survey. That data
# showed the earlier "dense evergreen palm" assumptions were wrong for
# interior open/rain-fed coconut, which at 10 m mixes palm with bare
# ground + seasonal intercrop. Measured coconut medians there:
#   NDVI_p15 0.29 (NOT evergreen), NDVI_p90 0.73, amplitude 0.34,
#   VH -16.7 dB, DW_trees 0.16. So we no longer gate on a high
#   dry-season NDVI; instead the plantation base keys on persistent
#   partial TREE canopy (Dynamic World trees prob) - the signal that
#   separates open coconut from seasonal cropland (~0 trees) - plus a
#   peak-greenness floor to drop bare land, on flat ground.
MAX_SLOPE_DEG = 10           # tightened 12->10: drops hill forest/scrub
# Base gate: pixel greens up at peak (rejects permanently bare land).
PLANTATION_PEAK_MIN = 0.45
# Base gate: DRY-SEASON greenness (15th-pct NDVI). This is the key
# "evergreen palm vs bare/built land" signal - bare land and built-up
# brown down in the dry season (p15 ~0.1), irrigated/rain-fed coconut
# stays greener. Tightened 0.22->0.26: at 0.22 the layer still spilled
# onto empty/fallow ground (which greens a little in monsoon). 0.26
# sits just under the ground-truth coconut median (~0.29) so it keeps
# most true coconut while cutting the empty-land leak.
EVERGREEN_MIN = 0.26
# Base gate: persistent tree canopy fraction (Dynamic World). Raised
# 0.12->0.14 for precision - thin-tree scrub/fallow leaked below this.
PLANTATION_TREES_MIN = 0.14
# Base gate: UPPER tree bound. Dense closed-canopy NATURAL forest sits
# well above plantations (ground-truth coconut DW_trees ~0.16), so an
# upper cap drops solid forest that was being painted as plantation
# without hurting real open coconut.
DW_TREES_MAX = 0.82
# Base gate: reject empty/bare ground explicitly (belt-and-braces with
# the tree>bare test) and grassland.
DW_BARE_MAX = 0.30
# Base gate: reject built-up outright (never plantation). (Water is
# already excluded by the greenness gates - it has near-zero NDVI.)
DW_BUILT_MAX = 0.30

# --- Coconut vs banana voting thresholds ---
# Within the plantation base, a pixel is coconut if it wins >=2 of 4
# votes, else banana. Thresholds sit where REAL coconut lives (from
# the ground truth) so the votes stop rejecting true coconut; banana
# sits on the far side (denser peak, bigger swings).
COCONUT_PEAK_NDVI_MAX = 0.82   # coconut peak <=~0.8; banana > 0.82
COCONUT_AMP_MAX = 0.45         # coconut amp ~0.34; banana swings more
COCONUT_VH_MIN_DB = -18.0      # coconut ~ -17 dB; banana lower/variable

PLANTATION_COLOR = "ffff00"    # bright yellow - coconut/arecanut
BANANA_COLOR = "ff1493"        # deep pink - banana


def crop_class_image(buffer, year):
    """3-class image: 0 = other, 1 = coconut/arecanut, 2 = banana.

    Within the plantation base (flat + persistent tree canopy + greens
    up), each pixel gets a coconut-vs-banana score from four signals:
      1. Dynamic World: coconut is woody -> trees prob > crops prob;
         banana is herbaceous -> crops prob > trees prob.
      2. Peak NDVI: coconut moderate (canopy gaps); banana very high
         (dense closed leaf canopy).
      3. Temporal stability: coconut static year-round; banana swings
         with harvest / ratoon cycles.
      4. Sentinel-1 VH: coconut strong volume scattering (rigid
         fronds/trunk); banana lower, more variable.
    Coconut if it wins >= 2 of 4 votes, else banana.
    """

    feats = feature_stack(buffer, year)
    p15 = feats.select("NDVI_p15")
    p90 = feats.select("NDVI_p90")
    amp = feats.select("NDVI_amp")
    vh = feats.select("VH")
    dw_trees = feats.select("DW_trees")
    dw_crops = feats.select("DW_crops")
    dw_built = feats.select("DW_built")
    dw_bare = feats.select("DW_bare")
    dw_grass = feats.select("DW_grass")

    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))

    # Plantation base: flat, GREEN THROUGH THE DRY SEASON (evergreen
    # palm - excludes bare/built that brown down), greens to a real
    # canopy at peak, has persistent tree canopy, and is not built-up
    # or water. The dry-season gate (p15) is what stops the layer
    # spilling into empty land and towns.
    base = (slope.lte(MAX_SLOPE_DEG)
            .And(p15.gte(EVERGREEN_MIN))
            .And(p90.gte(PLANTATION_PEAK_MIN))
            .And(dw_trees.gte(PLANTATION_TREES_MIN))
            .And(dw_trees.lte(DW_TREES_MAX))   # not dense natural forest
            .And(dw_trees.gt(dw_bare))         # tree-dominant, not bare
            .And(dw_trees.gt(dw_grass))        # not grassland
            .And(dw_bare.lt(DW_BARE_MAX))      # not empty/bare ground
            .And(dw_built.lt(DW_BUILT_MAX)))

    # Woody dominance is now a HARD gate for coconut (was a soft vote):
    # coconut is a tree crop, so its Dynamic World 'trees' probability
    # must beat 'crops'. This is what stops the layer swallowing the
    # green cropland matrix (paddy, maize, sugarcane) - those are
    # crop-dominant and get excluded here rather than painted yellow.
    tree_dom = dw_trees.gt(dw_crops)

    v_peak = p90.lt(COCONUT_PEAK_NDVI_MAX)
    v_stable = amp.lte(COCONUT_AMP_MAX)
    v_vh = vh.gt(COCONUT_VH_MIN_DB)
    # Support from the 3 remaining signatures (peak / stability / radar).
    support = v_peak.add(v_stable).add(v_vh)

    coconut = base.And(tree_dom).And(support.gte(2))
    banana = base.And(tree_dom.Not()).And(support.lt(2))

    return (ee.Image(0)
            .where(coconut, 1)
            .where(banana, 2)
            .rename("cropclass")
            .updateMask(base))


def _not_paddy(buffer, year):
    """1 where the independent radar paddy detector says NOT paddy.

    Paddy and coconut are mutually exclusive land uses, and paddy is
    found from a different signal (Sentinel-1 radar), so subtracting it
    is a clean cross-check that stops irrigated paddy / wet cropland
    leaking into the plantation layer.
    """
    try:
        from gee.paddy import paddy_mask
        pad = paddy_mask(buffer, f"{year}-01-01", f"{year}-12-31")
        return pad.unmask(0).eq(0)
    except Exception:
        return ee.Image(1)


def plantation_mask(buffer, year):
    """Coconut/arecanut mask (class 1), with paddy carved out."""
    coco = crop_class_image(buffer, year).eq(1)
    return coco.And(_not_paddy(buffer, year)).rename("plantation")


def banana_mask(buffer, year):
    """Banana mask (class 2), with paddy carved out."""
    ban = crop_class_image(buffer, year).eq(2)
    return ban.And(_not_paddy(buffer, year)).rename("banana")


@st.cache_data(show_spinner="Detecting plantations (coconut/arecanut)...")
def plantation_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL showing likely plantations in bright yellow.

    The mask is reprojected to a fixed 20 m grid before display, so
    Earth Engine computes the heavy year-long analysis ONCE and
    serves a cached tile pyramid - instead of recomputing per tile at
    every zoom (which timed out and left blank/partial tiles).
    """

    from core import compute as _cq
    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = plantation_mask(buffer, year).reproject(
        crs="EPSG:3857", scale=_cq.tile_px())

    img = mask.updateMask(mask).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", PLANTATION_COLOR]})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Detecting banana plantations...")
def banana_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL showing likely banana in deep pink."""

    from core import compute as _cq
    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = banana_mask(buffer, year).reproject(
        crs="EPSG:3857", scale=_cq.tile_px())

    img = mask.updateMask(mask).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", BANANA_COLOR]})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Measuring plantation area...")
def plantation_stats(lat, lon, radius_km, year):
    """Plantation acres and share of tree cover in the buffer."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = plantation_mask(buffer, year)

    trees_class = dw_class_image(
        buffer, f"{year}-01-01", f"{year}-12-31"
    ).eq(1)

    img = ee.Image.cat([
        ee.Image.pixelArea().updateMask(mask).rename("plantation"),
        ee.Image.pixelArea().updateMask(trees_class).rename("trees"),
        ee.Image.pixelArea().rename("total"),
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

    def acres(key):
        return round((stats.get(key) or 0) / SQM_PER_ACRE, 2)

    plant_ac = acres("plantation")
    trees_ac = acres("trees")
    total_ac = acres("total")

    # Share is of the SEARCHED AREA, not of Dynamic World "tree cover":
    # open coconut is often labelled crops/grass by DW, so plantation
    # can (correctly) exceed DW tree cover - making tree cover a wrong
    # denominator (it produced >100% shares).
    return {
        "plantation_ac": plant_ac,
        "trees_ac": trees_ac,
        "area_ac": total_ac,
        "plantation_pct": round(100 * plant_ac / total_ac, 1)
        if total_ac else 0.0,
    }
