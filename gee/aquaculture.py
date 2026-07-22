"""Aquaculture pond detection from satellite.

Fish / prawn ponds are small-to-medium, fairly PERMANENT inland water
bodies with regular shapes - distinct from rivers (long, connected)
and reservoirs/large tanks (very large connected water). We key on
persistent surface water (JRC Global Surface Water occurrence) and
keep only pond-sized connected clusters on flat ground.

Honest scope: this finds "persistent small water bodies", which in
coastal deltas and tank-fed belts are predominantly aquaculture, but
can include farm ponds and small irrigation tanks. It is the one
allied sector visible from space, so unlike livestock it IS a map.
"""

import ee
import streamlit as st

SQM_PER_ACRE = 4046.8564224

# Tuning constants
OCC_MIN = 35        # % of time water is present (JRC occurrence)
MIN_POND_PX = 4     # ~0.36 ha at 30 m - drop speckle/tiny ponds
MAX_POND_PX = 500   # ~45 ha - above this it's a reservoir/river/lake
MAX_SLOPE_DEG = 8   # ponds sit on flat ground

AQUA_COLOR = "1565c0"   # deep blue (distinct from paddy cyan)


def aquaculture_mask(buffer):
    """Binary mask (1 = likely aquaculture/farm pond)."""

    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater")
    occ = gsw.select("occurrence")          # 0-100

    water = occ.gte(OCC_MIN)

    # Connected-cluster size (pixels). Rivers/reservoirs saturate the
    # cap; small ponds stay small.
    size = water.selfMask().connectedPixelCount(MAX_POND_PX + 20, True)

    ponds = (water
             .And(size.gte(MIN_POND_PX))
             .And(size.lte(MAX_POND_PX)))

    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))
    flat = slope.lte(MAX_SLOPE_DEG)

    return ponds.And(flat).rename("aquaculture")


@st.cache_data(show_spinner="Detecting aquaculture ponds...")
def aquaculture_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL showing likely ponds in blue. (year unused - JRC
    water is a multi-year climatology - kept for a uniform signature.)"""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    from core import compute as _cq
    mask = aquaculture_mask(buffer).reproject(
        crs="EPSG:3857", scale=_cq.tile_px())

    img = mask.updateMask(mask).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", AQUA_COLOR]})

    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Measuring aquaculture area...")
def aquaculture_stats(lat, lon, radius_km, year):
    """Pond acres inside the buffer."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    mask = aquaculture_mask(buffer)

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

    return {"pond_ac": round((area.get("area") or 0) / SQM_PER_ACRE, 1)}
