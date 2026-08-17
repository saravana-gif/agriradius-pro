"""Satellite irrigation layers - is this cropland irrigated or rain-fed?

Four independent views, deliberately kept separate so you can see where
they agree:

1. SUMMER GREEN (our own, the primary signal)
   Cropland that is still green and moist between mid-February and
   mid-May. Nothing survives a Karnataka summer on stored soil
   moisture, so summer greenness is the cleanest evidence of applied
   water. This avoids the trap that ruins naive classifiers: rabi
   jowar, chickpea and safflower on black cotton soil (vertisols) in
   Vijayapura, Bagalkote, Kalaburagi, Bidar and Vijayanagara are
   RAIN-FED, grown entirely on stored vertisol moisture. A
   "green in rabi = irrigated" rule mislabels much of north Karnataka;
   a summer window does not.

2. MULTI-CROP PRIOR (GCI30)
   Two or more crops a year. In the semi-arid interior - Chitradurga,
   Tumakuru, Kolar, Vijayapura, Kalaburagi, Raichur, Ballari -
   rainfall cannot support double cropping, so this is near-conclusive
   evidence of irrigation, and often a better indicator than the
   dedicated irrigation products.

3. LGRIP30 (USGS/NASA, 30 m)
   The Landsat-derived global irrigated/rain-fed map. Note honestly:
   its headline 91% accuracy is for the CONTINENTAL US only (V002); the
   version covering India is V001 (2015) and no Indian accuracy figure
   has ever been published. Class 0 is ocean AND inland water, so
   Karnataka's tanks and reservoirs fall in it.

4. WORLDCEREAL IRRIGATION (ESA, 10 m)
   Treat as a LOWER BOUND only. ESA's own paper states they had
   "little means to run a quantitative validation of irrigation
   products as such" - there are no published accuracy metrics, the
   training data is biased toward centre-pivot systems, and it
   under-maps Asia.

Every function is independent and guarded by the caller, so one
unavailable asset never breaks the map or the report.
"""

import ee
import streamlit as st

from gee.tiles import TILE_TTL

SQM_PER_ACRE = 4046.86

# Mid-February to mid-May: the discriminating window for Karnataka.
SUMMER_START_MD = (2, 15)
SUMMER_END_MD = (5, 15)

IRRIGATED_COLOR = "00c2ff"
RAINFED_COLOR = "d9a441"
MULTICROP_COLOR = "7b1fa2"

# Summer thresholds. NDVI keeps bare/senescent land out; NDMI is the
# moisture term that proved decisive in the published Berambadi work.
NDVI_MIN = 0.35
NDMI_MIN = 0.0


def _buffer(lat, lon, radius_km):
    return ee.Geometry.Point([lon, lat]).buffer(radius_km * 1000)


def _summer_window(year):
    s = ee.Date.fromYMD(year, SUMMER_START_MD[0], SUMMER_START_MD[1])
    e = ee.Date.fromYMD(year, SUMMER_END_MD[0], SUMMER_END_MD[1])
    return s, e


def _mask_s2(img):
    scl = img.select("SCL")
    ok = (scl.neq(3).And(scl.neq(8)).And(scl.neq(9))
          .And(scl.neq(10)).And(scl.neq(11)))
    return img.updateMask(ok).divide(10000)


def _cropland(buffer, year):
    """Cropland mask: Dynamic World crops, widened by GFSAD where
    available. Irrigation is only meaningful on cropland."""
    from gee.dynamic_world import dw_crops_mask
    dw = dw_crops_mask(buffer, f"{year}-01-01", f"{year}-12-31")
    try:
        gcep = ee.Image(
            "projects/sat-io/open-datasets/GFSAD/GCEP30").eq(2)
        return dw.Or(gcep)
    except Exception:
        return dw


def summer_green_mask(buffer, year):
    """Cropland still green AND moist through the dry season."""
    s, e = _summer_window(year)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(buffer)
           .filterDate(s, e)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
           .map(_mask_s2))
    med = col.median()
    ndvi = med.normalizedDifference(["B8", "B4"])
    ndmi = med.normalizedDifference(["B8", "B11"])
    wet = ndvi.gte(NDVI_MIN).And(ndmi.gte(NDMI_MIN))
    return wet.And(_cropland(buffer, year)).rename("irrigated")


def multicrop_mask(buffer):
    """Two or more crops a year (GCI30). 127 is the fill value."""
    gci = ee.Image("projects/sat-io/open-datasets/GCI30")
    return gci.gte(2).And(gci.neq(127)).rename("multicrop")


def lgrip_masks():
    """(irrigated, rainfed) from LGRIP30. 2=irrigated, 3=rain-fed."""
    lg = ee.Image("projects/sat-io/open-datasets/GFSAD/LGRIP30")
    return lg.eq(2).rename("lgrip_irrigated"), \
        lg.eq(3).rename("lgrip_rainfed")


def worldcereal_irrigation_mask():
    """ESA WorldCereal irrigation - lower bound only."""
    return (ee.ImageCollection("ESA/WorldCereal/2021/MODELS/v100")
            .filter(ee.Filter.eq("product", "irrigation"))
            .select("classification")
            .mosaic()
            .eq(100)
            .rename("wc_irrigated"))


# ------------------------------------------------------------------
# Tile layers
# ------------------------------------------------------------------

@st.cache_data(show_spinner="Detecting irrigated cropland (summer)...",
               ttl=TILE_TTL)
def summer_green_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    img = summer_green_mask(buffer, year).selfMask().clip(buffer)
    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", IRRIGATED_COLOR]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Loading multi-crop prior...", ttl=TILE_TTL)
def multicrop_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    img = multicrop_mask(buffer).selfMask().clip(buffer)
    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", MULTICROP_COLOR]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Loading LGRIP30 irrigated/rain-fed...",
               ttl=TILE_TTL)
def lgrip_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    irr, rain = lgrip_masks()
    # 1 = irrigated, 2 = rain-fed, everything else transparent
    combo = irr.multiply(1).add(rain.multiply(2))
    img = combo.selfMask().clip(buffer)
    mapid = img.getMapId({
        "min": 1, "max": 2,
        "palette": [IRRIGATED_COLOR, RAINFED_COLOR]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Loading WorldCereal irrigation...",
               ttl=TILE_TTL)
def worldcereal_irrigation_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    img = worldcereal_irrigation_mask().selfMask().clip(buffer)
    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", "0b6fa4"]})
    return mapid["tile_fetcher"].url_format


# ------------------------------------------------------------------
# Acreage statistics
# ------------------------------------------------------------------

def _acres(mask, buffer):
    from core import compute as _cq
    area = (ee.Image.pixelArea().updateMask(mask)
            .reduceRegion(reducer=ee.Reducer.sum(), geometry=buffer,
                          scale=_cq.stat_scale(), maxPixels=1e13,
                          bestEffort=True,
                          tileScale=_cq.tile_scale()).getInfo())
    return round((area.get("area") or 0) / SQM_PER_ACRE, 1)


@st.cache_data(show_spinner="Measuring irrigated area...", ttl=3600)
def irrigation_stats(lat, lon, radius_km, year):
    """Acres by each independent method, plus where they agree.

    Agreement between two independent methods is the number worth
    quoting; a single method on its own is an estimate.
    """
    buffer = _buffer(lat, lon, radius_km)
    out = {"year": year}

    crop = _cropland(buffer, year)
    try:
        out["cropland_ac"] = _acres(crop, buffer)
    except Exception:
        out["cropland_ac"] = None

    summer = None
    try:
        summer = summer_green_mask(buffer, year)
        out["summer_green_ac"] = _acres(summer, buffer)
    except Exception:
        out["summer_green_ac"] = None

    try:
        mc = multicrop_mask(buffer).And(crop)
        out["multicrop_ac"] = _acres(mc, buffer)
    except Exception:
        out["multicrop_ac"] = None

    try:
        irr, rain = lgrip_masks()
        out["lgrip_irrigated_ac"] = _acres(irr, buffer)
        out["lgrip_rainfed_ac"] = _acres(rain, buffer)
    except Exception:
        out["lgrip_irrigated_ac"] = None
        out["lgrip_rainfed_ac"] = None

    try:
        out["worldcereal_irrigated_ac"] = _acres(
            worldcereal_irrigation_mask(), buffer)
    except Exception:
        out["worldcereal_irrigated_ac"] = None

    # Confidence: summer greenness AND an independent product agree.
    try:
        if summer is not None:
            irr, _ = lgrip_masks()
            out["confirmed_ac"] = _acres(summer.And(irr), buffer)
    except Exception:
        out["confirmed_ac"] = None

    if out.get("cropland_ac") and out.get("summer_green_ac") is not None:
        out["summer_green_pct"] = round(
            100 * out["summer_green_ac"] / out["cropland_ac"], 1)

    return out


def verdict(stats):
    """One plain-English line about how irrigated this area is."""
    if not stats:
        return None
    pct = stats.get("summer_green_pct")
    if pct is None:
        return None
    if pct >= 50:
        head = "Heavily irrigated"
    elif pct >= 25:
        head = "Substantially irrigated"
    elif pct >= 10:
        head = "Partly irrigated"
    else:
        head = "Largely rain-fed"
    return (f"{head} - {pct}% of the cropland here holds green, moist "
            f"canopy through the February-May dry season, which needs "
            f"applied water.")
