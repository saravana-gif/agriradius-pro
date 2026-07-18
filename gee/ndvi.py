"""Sentinel-2 monthly NDVI time series over cropland only.

NDVI is masked to Dynamic World's crops class so the signal reflects
farmland, not forests or built-up areas.
"""

import ee
import streamlit as st

from gee.dynamic_world import dw_crops_mask


def _mask_clouds(img):
    """Mask clouds/shadows/snow using the SCL band."""
    scl = img.select("SCL")
    bad = (
        scl.eq(3)      # cloud shadow
        .Or(scl.eq(8))   # cloud medium prob
        .Or(scl.eq(9))   # cloud high prob
        .Or(scl.eq(10))  # cirrus
        .Or(scl.eq(11))  # snow
    )
    return img.updateMask(bad.Not())


def ndvi_monthly_stack(buffer, start_year, end_year):
    """Build a multi-band image: one cropland-masked NDVI band per
    month. Returns (stack, months) where months is a list of
    (band_name, 'YYYY-MM') pairs."""

    # Cropland mask (probability-based Dynamic World classification)
    crops = dw_crops_mask(
        buffer, f"{start_year}-01-01", f"{end_year}-12-31"
    )

    months = []
    images = []

    for y in range(start_year, end_year + 1):
        for m in range(1, 13):

            start = ee.Date.fromYMD(y, m, 1)
            end = start.advance(1, "month")

            col = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(buffer)
                .filterDate(start, end)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
                .map(_mask_clouds)
            )

            band = f"m{y}_{m:02d}"

            # Months with no usable images produce an empty (0-band)
            # image; substitute a fully-masked band so the stack stays
            # consistent and the month simply reads as a gap.
            ndvi = ee.Image(
                ee.Algorithms.If(
                    col.size().gt(0),
                    col.map(
                        lambda i: i.normalizedDifference(["B8", "B4"])
                    )
                    .median()
                    .updateMask(crops)
                    .rename(band),
                    ee.Image.constant(0)
                    .updateMask(ee.Image.constant(0))
                    .rename(band),
                )
            )

            months.append((band, f"{y}-{m:02d}"))
            images.append(ndvi)

    return ee.Image.cat(images), months


@st.cache_data(show_spinner="Computing NDVI time series (30-60s)...")
def ndvi_monthly_series(lat, lon, radius_km, start_year, end_year):
    """Return [(month 'YYYY-MM', mean NDVI over cropland), ...]."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    stack, months = ndvi_monthly_stack(buffer, start_year, end_year)

    stats = stack.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=buffer,
        scale=30,
        maxPixels=1e13,
        bestEffort=True,
    ).getInfo()

    series = []
    for band, label in months:
        value = stats.get(band)
        series.append((label, round(value, 4) if value is not None else None))

    return series
