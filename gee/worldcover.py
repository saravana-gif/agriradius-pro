"""ESA WorldCover cross-check - independent validation of cropland.

Dynamic World (Google) and WorldCover (ESA) are built by different
teams from different methods. Where both agree a pixel is cropland,
confidence is high; where only one says cropland, be suspicious.
"""

import ee
import streamlit as st

from gee.dynamic_world import dw_crops_mask

SQM_PER_ACRE = 4046.8564224

# Agreement palette: 1 = only one dataset says cropland (yellow),
#                    2 = both agree cropland (green)
PALETTE = ["f4c20d", "1a9850"]


def _layers(lat, lon, radius_km, year):

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    dw_crops = dw_crops_mask(
        buffer, f"{year}-01-01", f"{year}-12-31"
    )

    # WorldCover v200 (2021 baseline), class 40 = cropland
    wc_crops = (
        ee.ImageCollection("ESA/WorldCover/v200")
        .first()
        .select("Map")
        .eq(40)
    )

    return buffer, dw_crops, wc_crops


@st.cache_data(show_spinner="Building cropland confidence layer...")
def confidence_tile_url(lat, lon, radius_km, year):
    """Tile URL: green = both agree cropland, yellow = only one."""

    from core import compute as _cq
    buffer, dw, wc = _layers(lat, lon, radius_km, year)

    agreement = dw.add(wc).reproject(  # 0 / 1 / 2
        crs="EPSG:3857", scale=_cq.tile_px())

    img = agreement.updateMask(agreement.gt(0)).clip(buffer)

    mapid = img.getMapId({"min": 1, "max": 2, "palette": PALETTE})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Cross-checking cropland (two datasets)...")
def cropland_crosscheck(lat, lon, radius_km, year):
    """Compare cropland area between the two datasets. Returns dict."""

    buffer, dw, wc = _layers(lat, lon, radius_km, year)

    both = dw.And(wc)
    dw_only = dw.And(wc.Not())
    wc_only = wc.And(dw.Not())

    img = ee.Image.cat([
        ee.Image.pixelArea().updateMask(both).rename("both"),
        ee.Image.pixelArea().updateMask(dw_only).rename("dw_only"),
        ee.Image.pixelArea().updateMask(wc_only).rename("wc_only"),
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

    both_ac = acres("both")
    dw_only_ac = acres("dw_only")
    wc_only_ac = acres("wc_only")

    union = both_ac + dw_only_ac + wc_only_ac

    return {
        "confirmed_ac": both_ac,
        "dw_only_ac": dw_only_ac,
        "wc_only_ac": wc_only_ac,
        "agreement_pct": round(100 * both_ac / union, 1) if union else 0.0,
    }