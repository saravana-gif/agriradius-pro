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


# Published Sentinel-1 rule for irrigation EVENTS: the change in
# plot-mean VV backscatter between consecutive passes.
#   <= -0.5 dB  -> no irrigation
#   >= +1.0 dB  -> probable irrigation event
# Tested on plots of 0.1-65 ha at ~86% overall discrimination. Radar
# sees through cloud, which is why this carries the coastal/Malnad
# districts where the optical signal is useless.
S1_EVENT_DB = 1.0

# JRC Global Surface Water: occurrence >= this % means permanent water.
PERMANENT_WATER_PCT = 50
# Land within this distance of permanent water is plausibly served by
# canal/tank (surface) irrigation rather than a borewell.
SURFACE_WATER_M = 1500


def _buffer(lat, lon, radius_km):
    return ee.Geometry.Point([lon, lat]).buffer(radius_km * 1000)


def thresholds(districts=None):
    """Zone-aware NDVI/NDMI thresholds (see core.irrigation)."""
    try:
        from core import irrigation as _ir
        prof = _ir.zone_profile(districts or [])
        return float(prof["ndvi"]), float(prof["ndmi"]), prof
    except Exception:
        return NDVI_MIN, NDMI_MIN, None


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
    """Cropland mask - irrigation is only meaningful on cropland.

    Dynamic World crops, widened by ESA WorldCover's cropland class.
    Both are OFFICIAL Earth Engine catalogue datasets. The GFSAD
    community mirror was used here before and silently poisoned every
    layer built on it: Earth Engine is lazy, so an unreadable asset
    only errors when the tile is requested, long after the try/except
    around its construction has passed.
    """
    from gee.assets import (GCEP30, WORLDCOVER, WORLDCOVER_CROPLAND,
                            asset_ok)
    from gee.dynamic_world import dw_crops_mask

    dw = dw_crops_mask(buffer, f"{year}-01-01", f"{year}-12-31")
    try:
        wc = (ee.Image(WORLDCOVER).select("Map")
              .eq(WORLDCOVER_CROPLAND))
        mask = dw.Or(wc)
    except Exception:
        mask = dw

    # Only add the community GFSAD layer when it is genuinely readable.
    if asset_ok(GCEP30):
        try:
            mask = mask.Or(ee.Image(GCEP30).eq(2))
        except Exception:
            pass
    return mask


def summer_green_mask(buffer, year, ndvi_min=None, ndmi_min=None):
    """Cropland still green AND moist through the dry season.

    Thresholds default to the semi-arid interior; pass zone-aware
    values (see thresholds()) for coastal/Malnad or the vertisol belt.
    """
    ndvi_min = NDVI_MIN if ndvi_min is None else ndvi_min
    ndmi_min = NDMI_MIN if ndmi_min is None else ndmi_min
    s, e = _summer_window(year)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
           .filterBounds(buffer)
           .filterDate(s, e)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
           .map(_mask_s2))
    med = col.median()
    ndvi = med.normalizedDifference(["B8", "B4"])
    ndmi = med.normalizedDifference(["B8", "B11"])
    wet = ndvi.gte(ndvi_min).And(ndmi.gte(ndmi_min))
    return wet.And(_cropland(buffer, year)).rename("irrigated")


def s1_event_mask(buffer, year):
    """Probable irrigation EVENTS from Sentinel-1 VV backscatter.

    Wetting the soil raises VV. Over the dry season, cropland whose
    VV jumps by >= +1.0 dB between consecutive passes has almost
    certainly had water applied - rain being rare in that window. This
    is the only method here that works under cloud, so it carries the
    coastal and Malnad districts.

    Sentinel-1 is back to a 6-day exact repeat (S1C operational May
    2025, S1D from April 2026), which is what makes event-level
    detection viable again rather than season-level only.
    """
    s, e = _summer_window(year)
    col = (ee.ImageCollection("COPERNICUS/S1_GRD")
           .filterBounds(buffer)
           .filterDate(s, e)
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains(
               "transmitterReceiverPolarisation", "VV"))
           .select("VV")
           .sort("system:time_start"))

    # Rise of the maximum over the minimum, in dB, across the window:
    # a cheap, robust proxy for "at least one wetting event".
    rise = col.max().subtract(col.min())
    return (rise.gte(S1_EVENT_DB)
            .And(_cropland(buffer, year))
            .rename("s1_events"))


def surface_vs_ground(buffer, year):
    """Split irrigated land by plausible SOURCE.

    Land near permanent surface water is plausibly canal- or tank-fed;
    irrigated land far from any surface water is almost certainly
    groundwater (borewell). This mirrors the district statistics -
    56.6% of Karnataka's irrigated area is borewell - and gives field
    staff the distinction on the map.

    Returns (surface_fed, groundwater_fed) masks over irrigated land.
    """
    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")
    permanent = gsw.gte(PERMANENT_WATER_PCT).selfMask()
    dist = (permanent.fastDistanceTransform(256).sqrt()
            .multiply(ee.Image.pixelArea().sqrt()))
    near = dist.lte(SURFACE_WATER_M)
    irr = summer_green_mask(buffer, year)
    return (irr.And(near).rename("surface_fed"),
            irr.And(near.Not()).rename("groundwater_fed"))


def vertisol_mask(buffer):
    """Black cotton soil proxy: clay-rich topsoil (SoilGrids).

    Where this is extensive, rain-fed rabi is normal and any
    rabi-based irrigation rule would over-count badly.
    """
    from gee.soil import _rootzone
    clay = _rootzone("clay").divide(10)      # g/kg -> %
    return clay.gte(35).rename("vertisol")


def evidence_score(buffer, year, ndvi_min=None, ndmi_min=None):
    """0-5 agreement score - the honest headline product.

    One point each for: summer greenness, a radar irrigation event,
    multi-cropping, LGRIP30 irrigated, WorldCereal irrigation. No
    single product here is trustworthy alone; agreement between
    independent methods is. Pixels scoring 3+ are the ones worth
    sending someone to look at.
    """
    layers = []
    try:
        layers.append(summer_green_mask(buffer, year, ndvi_min,
                                        ndmi_min).unmask(0))
    except Exception:
        pass
    try:
        layers.append(s1_event_mask(buffer, year).unmask(0))
    except Exception:
        pass
    try:
        layers.append(multicrop_mask(buffer).unmask(0))
    except Exception:
        pass
    try:
        irr, _ = lgrip_masks()
        layers.append(irr.unmask(0))
    except Exception:
        pass
    try:
        layers.append(worldcereal_irrigation_mask().unmask(0))
    except Exception:
        pass

    if not layers:
        return None
    total = layers[0]
    for extra in layers[1:]:
        total = total.add(extra)
    return total.rename("evidence").updateMask(
        _cropland(buffer, year))


def multicrop_available():
    from gee.assets import GCI30, asset_ok
    return asset_ok(GCI30)


def multicrop_mask(buffer):
    """Two or more crops a year (GCI30). 127 is the fill value.

    Raises when the community asset is unreadable, so callers report
    it instead of drawing an empty layer.
    """
    from gee.assets import GCI30, asset_ok, missing_note
    if not asset_ok(GCI30):
        raise RuntimeError(missing_note(GCI30, "The multi-crop layer"))
    gci = ee.Image(GCI30)
    return gci.gte(2).And(gci.neq(127)).rename("multicrop")


def lgrip_available():
    from gee.assets import LGRIP30, asset_ok
    return asset_ok(LGRIP30)


def lgrip_masks():
    """(irrigated, rainfed) from LGRIP30. 2=irrigated, 3=rain-fed."""
    from gee.assets import LGRIP30, asset_ok, missing_note
    if not asset_ok(LGRIP30):
        raise RuntimeError(missing_note(
            LGRIP30, "The LGRIP30 irrigated/rain-fed layer"))
    lg = ee.Image(LGRIP30)
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


@st.cache_data(show_spinner="Detecting irrigation events (radar)...",
               ttl=TILE_TTL)
def s1_event_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    img = s1_event_mask(buffer, year).selfMask().clip(buffer)
    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", "ff4081"]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Scoring irrigation evidence...",
               ttl=TILE_TTL)
def evidence_tile_url(lat, lon, radius_km, year):
    """0-5 agreement between independent methods."""
    buffer = _buffer(lat, lon, radius_km)
    ndvi_min, ndmi_min, _ = thresholds(_districts(lat, lon, radius_km))
    img = evidence_score(buffer, year, ndvi_min, ndmi_min)
    if img is None:
        return None
    img = img.updateMask(img.gte(1)).clip(buffer)
    mapid = img.getMapId({
        "min": 1, "max": 5,
        "palette": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26",
                    "#a50f15"]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Separating canal/tank from borewell...",
               ttl=TILE_TTL)
def water_source_tile_url(lat, lon, radius_km, year):
    """Irrigated land split by plausible water source."""
    buffer = _buffer(lat, lon, radius_km)
    surf, ground = surface_vs_ground(buffer, year)
    combo = surf.multiply(1).add(ground.multiply(2)).selfMask()
    img = combo.clip(buffer)
    mapid = img.getMapId({"min": 1, "max": 2,
                          "palette": ["1f78b4", "e6550d"]})
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

def _districts(lat, lon, radius_km):
    """District names touching the circle - for zone-aware thresholds."""
    try:
        from core import allied
        return [d for _s, d in
                (allied.districts_touching(lat, lon, radius_km) or [])]
    except Exception:
        return []


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

    dists = _districts(lat, lon, radius_km)
    ndvi_min, ndmi_min, zone = thresholds(dists)
    out["zone"] = zone
    out["thresholds"] = {"ndvi": ndvi_min, "ndmi": ndmi_min}

    crop = _cropland(buffer, year)
    try:
        out["cropland_ac"] = _acres(crop, buffer)
    except Exception:
        out["cropland_ac"] = None

    summer = None
    try:
        summer = summer_green_mask(buffer, year, ndvi_min, ndmi_min)
        out["summer_green_ac"] = _acres(summer, buffer)
    except Exception:
        out["summer_green_ac"] = None

    events = None
    try:
        events = s1_event_mask(buffer, year)
        out["s1_event_ac"] = _acres(events, buffer)
    except Exception:
        out["s1_event_ac"] = None

    try:
        surf, ground = surface_vs_ground(buffer, year)
        out["surface_fed_ac"] = _acres(surf, buffer)
        out["groundwater_fed_ac"] = _acres(ground, buffer)
    except Exception:
        out["surface_fed_ac"] = None
        out["groundwater_fed_ac"] = None

    try:
        out["vertisol_ac"] = _acres(
            vertisol_mask(buffer).And(crop), buffer)
    except Exception:
        out["vertisol_ac"] = None

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

    # Ensemble: how much land two or more / three or more independent
    # methods call irrigated. This is the defensible headline.
    try:
        ev = evidence_score(buffer, year, ndvi_min, ndmi_min)
        if ev is not None:
            out["evidence_2plus_ac"] = _acres(ev.gte(2), buffer)
            out["evidence_3plus_ac"] = _acres(ev.gte(3), buffer)
    except Exception:
        out["evidence_2plus_ac"] = None
        out["evidence_3plus_ac"] = None

    if out.get("cropland_ac") and out.get("summer_green_ac") is not None:
        out["summer_green_pct"] = round(
            100 * out["summer_green_ac"] / out["cropland_ac"], 1)

    return out


def verdict(stats):
    """One plain-English line about how irrigated this area is.

    Quotes the two-method agreement figure rather than any single
    product, and carries the zone's honest accuracy band.
    """
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

    line = (f"{head} - {pct}% of the cropland here holds green, moist "
            f"canopy through the February-May dry season, which needs "
            f"applied water.")

    agree = stats.get("evidence_2plus_ac")
    if agree:
        line += (f" Two or more independent methods agree on "
                 f"{agree:,.0f} ac.")

    zone = stats.get("zone") or {}
    if zone.get("label"):
        line += (f" Zone: {zone['label']} - expect "
                 f"{zone.get('accuracy', 'variable accuracy')}.")
    return line


def source_split_note(stats):
    """Surface-fed vs groundwater-fed, in plain words."""
    if not stats:
        return None
    surf = stats.get("surface_fed_ac")
    ground = stats.get("groundwater_fed_ac")
    if surf is None or ground is None:
        return None
    total = surf + ground
    if total <= 0:
        return None
    gpct = round(100 * ground / total)
    return (f"Of the irrigated land found here, about {gpct}% sits "
            f"more than {SURFACE_WATER_M / 1000:.1f} km from any "
            f"permanent surface water, so it is almost certainly "
            f"groundwater (borewell) fed - {ground:,.0f} ac, against "
            f"{surf:,.0f} ac plausibly canal- or tank-fed. Borewell "
            f"land will not appear on any canal command-area map.")
