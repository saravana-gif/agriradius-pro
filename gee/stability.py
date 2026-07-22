"""Multi-year cropland stability check.

Real cropland shows consistent acreage year over year; large swings
mean the classification is unreliable in this area. Consistency
across years is evidence of correctness - no ground data needed.
"""

import ee
import streamlit as st

from gee.dynamic_world import dw_crops_mask

SQM_PER_ACRE = 4046.8564224

N_YEARS = 3


@st.cache_data(show_spinner="Checking 3-year cropland stability...")
def cropland_stability(lat, lon, radius_km, end_year):
    """Cropland acres for the last 3 years + stability verdict."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    years = list(range(end_year - N_YEARS + 1, end_year + 1))

    # Each year is reduced in its OWN request (not stacked into one
    # image) with tileScale to spread memory, and at a coarser 60 m
    # scale - a year-over-year *ratio* doesn't need 30 m precision.
    # This avoids the "User memory limit exceeded" error that stacking
    # three full-year Dynamic World reductions caused. Coarser/scaled
    # fallbacks keep it working even on large radii.
    def _acres(y, scale, tile_scale):
        mask = dw_crops_mask(buffer, f"{y}-01-01", f"{y}-12-31")
        area = (ee.Image.pixelArea().updateMask(mask)
                .reduceRegion(reducer=ee.Reducer.sum(), geometry=buffer,
                              scale=scale, maxPixels=1e13,
                              bestEffort=True, tileScale=tile_scale)
                .get("area"))
        return round((area.getInfo() or 0) / SQM_PER_ACRE, 1)

    by_year = {}
    for y in years:
        try:
            by_year[y] = _acres(y, 60, 8)
        except Exception:
            # last-resort: even coarser + max tiling
            by_year[y] = _acres(y, 120, 16)

    values = list(by_year.values())
    mean = sum(values) / len(values) if values else 0

    if mean:
        spread = (max(values) - min(values)) / mean * 100
    else:
        spread = 0.0

    if spread < 10:
        verdict = "Stable"
        detail = (
            "Cropland acreage is consistent across years - the "
            "classification is dependable here."
        )
    elif spread < 25:
        verdict = "Mostly Stable"
        detail = (
            "Some year-to-year movement - fine for planning, but "
            "treat exact acreage as approximate."
        )
    else:
        verdict = "Unstable"
        detail = (
            "Large swings between years - the classifier struggles "
            "with this landscape; rely on the confirmed (green) "
            "cropland zones and visual checks."
        )

    return {
        "by_year": by_year,
        "spread_pct": round(spread, 1),
        "verdict": verdict,
        "detail": detail,
    }
