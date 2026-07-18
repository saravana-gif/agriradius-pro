"""CHIRPS rainfall history for the buffer.

Monthly rainfall totals for the last 10 years in one Earth Engine
call (CHIRPS pentad data, ~5.5 km resolution - plenty for area-level
rainfall). Powers annual reliability metrics and monthly charts.
"""

import ee
import streamlit as st

YEARS_BACK = 10


@st.cache_data(show_spinner="Fetching 10 years of rainfall (CHIRPS)...")
def rainfall_monthly(lat, lon, radius_km, end_year):
    """Return [('YYYY-MM', rainfall_mm), ...] for the last 10 years."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    col = ee.ImageCollection("UCSB-CHG/CHIRPS/PENTAD")

    start_year = end_year - YEARS_BACK + 1

    months = []
    images = []

    for y in range(start_year, end_year + 1):
        for m in range(1, 13):

            start = ee.Date.fromYMD(y, m, 1)
            end = start.advance(1, "month")

            band = f"r{y}_{m:02d}"

            monthly = (
                col.filterDate(start, end)
                .select("precipitation")
                .sum()
                .rename(band)
            )

            months.append((band, f"{y}-{m:02d}"))
            images.append(monthly)

    stack = ee.Image.cat(images)

    stats = stack.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=buffer,
        scale=5566,
        maxPixels=1e13,
        bestEffort=True,
    ).getInfo()

    series = []
    for band, label in months:
        v = stats.get(band)
        series.append((label, round(v, 1) if v is not None else None))

    return series
