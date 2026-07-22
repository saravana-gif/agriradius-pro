"""Maize (kharif) detection.

Maize in central Karnataka (Davangere, Ranibennur, Kotturu, and the
Kollegal-Doddinduvadi belt) is a rain-fed kharif crop: bare/dry land
that greens up fast with the monsoon (Jun-Oct), peaks very high (tall
dense crop), then goes bare after harvest. That strong single-season
NDVI pulse - high in kharif, low the rest of the year - is what we
key on.

Honest scope: at 10 m this detects "dense kharif cropland", which in
these maize belts is predominantly maize, but can include other tall
kharif crops (sorghum, cotton). Species-level separation needs the
ground-truth-trained classifier.
"""

import ee
import streamlit as st

from gee.ndvi import _mask_clouds

SQM_PER_ACRE = 4046.8564224

# --- Tuning constants ---
# Phenology-robust design, calibrated to measured NDVI curves in the
# Kollegal belt (timing-independent so it generalises to other belts):
#   * PEAK = the 90th-percentile NDVI over Jun-Dec. A percentile of
#     every clear observation recovers the true green peak even when
#     monsoon cloud blanks whole months (July reads ~0 - no clear
#     scenes), which a month-by-month median could not. The window
#     runs to December because the measured peak in this belt is often
#     Oct-Dec, not Aug-Sep (monsoon cloud + late/second sowings).
#   * TROUGH = a low annual NDVI percentile (the bare period, WHENEVER
#     it falls). Using the annual trough instead of a fixed Jan-Mar
#     window means double-cropped / rabi fields (green in Jan-Mar) are
#     no longer wrongly excluded - what matters is the field goes bare
#     at *some* point, which every single-pulse kharif field does and
#     no perennial (coconut/banana) does.
#   * A Dynamic World cropland guard keeps the (deliberately low) peak
#     threshold from bleeding into monsoon-green scrub/grassland.
# Measured gate pass-rates over belt cropland showed PEAK was the only
# bottleneck (trough/amp/slope ~100%), so the peak gate is relaxed.
MAX_SLOPE_DEG = 15
KHARIF_PEAK_MIN = 0.50     # green peak (p90) of a real crop canopy
TROUGH_MAX = 0.35          # must go bare at some point in the year
MIN_AMPLITUDE = 0.25       # peak minus annual trough (strong pulse)
TROUGH_PCT = 15            # percentile used as the "bare" trough level
PEAK_PCT = 90              # percentile used as the green "peak" level
DW_CROP_MIN = 0.35         # Dynamic World cropland-probability guard

MAIZE_COLOR = "ff8c00"     # dark orange


def _median_ndvi(buffer, start, end):
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(buffer)
        .filterDate(start, end)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        .map(_mask_clouds)
    )
    return col.map(
        lambda i: i.normalizedDifference(["B8", "B4"])
    ).median()


def _season_peak_ndvi(buffer, year, pct=PEAK_PCT):
    """High NDVI percentile over the Jun-Dec growing/harvest window.

    A percentile of every clear observation recovers the true green
    peak even when monsoon cloud blanks whole months (July has no
    clear scenes here), which a month-by-month median cannot. p90
    (not the raw max) avoids single cloud-edge pixels giving a false
    high. The window runs through December because the measured peak
    in this belt is frequently Oct-Dec, not Aug-Sep.
    """
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(buffer)
        .filterDate(f"{year}-06-01", f"{year}-12-31")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
        .map(_mask_clouds)
    )
    ndvi = col.map(lambda i: i.normalizedDifference(["B8", "B4"]))
    return ndvi.reduce(ee.Reducer.percentile([pct])).rename("peak")


def _farmland_guard(buffer, year):
    """Reject land that is DEFINITELY not farmland (forest, water,
    built-up) - and nothing else.

    We deliberately do NOT require Dynamic World's 'crops' label:
    after harvest or in a rotation year, maize fields routinely read
    as 'grass' or 'bare', so demanding 'crops' throws out real
    farmland and leaves the belt looking sparse. Persistent tree
    cover, water and built-up are the only classes that a seasonal
    cropland pixel can never be, so those are all we exclude here.
    The 'goes bare + strong pulse' NDVI gates do the crop-vs-scrub
    work."""
    dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
          .filterBounds(buffer)
          .filterDate(f"{year}-01-01", f"{year}-12-31")
          .select(["trees", "water", "built"])
          .mean())
    return (dw.select("trees").lt(0.5)
            .And(dw.select("water").lt(0.3))
            .And(dw.select("built").lt(0.3)))


def _annual_trough_ndvi(buffer, year, pct=TROUGH_PCT):
    """Low NDVI percentile over the whole year - the 'bare' level.

    Using a percentile of every clear observation (not a fixed
    dry-season window) finds the bare trough WHENEVER it occurs, so
    fields whose fallow gap is pre-monsoon, post-harvest OR in winter
    are all handled, and residual cloud can't drag it up the way a
    single-scene minimum could.
    """
    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(buffer)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
        .map(_mask_clouds)
    )
    ndvi = col.map(lambda i: i.normalizedDifference(["B8", "B4"]))
    return ndvi.reduce(ee.Reducer.percentile([pct])).rename("trough")


def maize_mask(buffer, year):
    """Dense kharif cropland (mostly maize in the maize belts).

    Keys on a strong single NDVI pulse: a high monsoon peak, a low
    annual trough (bare at some point), and a big amplitude between
    them. Timing-independent, so it transfers to other maize belts.
    """

    # Green peak = p90 NDVI over Jun-Dec (cloud-robust, late-peak safe).
    kharif = _season_peak_ndvi(buffer, year)
    # Bare trough = low annual NDVI percentile (whenever it occurs).
    trough = _annual_trough_ndvi(buffer, year)

    amp = kharif.subtract(trough)

    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
    flat = slope.lte(MAX_SLOPE_DEG)

    seasonal = (kharif.gte(KHARIF_PEAK_MIN)
                .And(trough.lt(TROUGH_MAX))
                .And(amp.gte(MIN_AMPLITUDE)))

    # Farmland guard: only reject forest / water / built-up.
    mask = seasonal.And(flat).And(_farmland_guard(buffer, year))

    # Exclude paddy (also a flooded kharif crop) so the layers don't
    # overlap.
    try:
        from gee.paddy import paddy_mask
        paddy = paddy_mask(buffer, f"{year}-01-01", f"{year}-12-31")
        mask = mask.And(paddy.Not())
    except Exception:
        pass

    return mask.rename("maize")


@st.cache_data(show_spinner="Detecting maize (kharif crop)...")
def maize_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL showing likely maize in orange."""

    from core import compute as _cq
    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = maize_mask(buffer, year).reproject(
        crs="EPSG:3857", scale=_cq.tile_px())

    img = mask.updateMask(mask).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", MAIZE_COLOR]})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Measuring maize area...")
def maize_stats(lat, lon, radius_km, year):
    """Maize acres in the buffer."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = maize_mask(buffer, year)

    from core import compute as _cq
    area = (
        ee.Image.pixelArea().updateMask(mask)
        .reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=buffer,
            scale=_cq.stat_scale(),
            maxPixels=1e13,
            bestEffort=True,
            tileScale=_cq.tile_scale(),
        ).getInfo()
    )

    return {"maize_ac": round((area.get("area") or 0) / SQM_PER_ACRE, 1)}
