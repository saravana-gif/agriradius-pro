"""Dynamic World classification and display tiles.

Uses the mean-of-probabilities method (Google's recommended practice)
instead of mode-of-labels: per-class probabilities are averaged over
the period and each pixel takes its most probable class. This reduces
trees/built-up flicker and recovers seasonal cropland that hard
labels miss.
"""

import ee
import streamlit as st

# Class order matches Dynamic World label encoding (0-8)
PROB_BANDS = [
    "water", "trees", "grass", "flooded_vegetation", "crops",
    "shrub_and_scrub", "built", "bare", "snow_and_ice",
]

CROPS_INDEX = 4

# (crops changed from official orange to magenta - orange was too
# close to built-up red and shrub tan on the map)
PALETTE = [
    "419bdf", "397d49", "88b053", "7a87c6", "ff00ff",
    "dfc35a", "c4281b", "a59b8f", "b39fe1",
]


def dw_class_image(buffer, start_date, end_date):
    """Most-probable-class image (values 0-8) for the period."""

    probs = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(buffer)
        .filterDate(start_date, end_date)
        .select(PROB_BANDS)
        .mean()
    )

    return (
        probs.toArray()
        .arrayArgmax()
        .arrayGet([0])
        .rename("label")
    )


def dw_crops_mask(buffer, start_date, end_date):
    """Binary cropland mask from the probability classification."""
    return dw_class_image(buffer, start_date, end_date).eq(CROPS_INDEX)


@st.cache_data(show_spinner="Loading Dynamic World overlay...")
def get_tile_url(lat, lon, radius_km, year):
    """XYZ tile URL for the probability-based composite."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    img = dw_class_image(
        buffer, f"{year}-01-01", f"{year}-12-31"
    ).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 8, "palette": PALETTE})

    return mapid["tile_fetcher"].url_format