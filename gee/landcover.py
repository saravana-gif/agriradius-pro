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

# A pixel counts as cropland if its crops probability reaches this
# level during the season (90th percentile across the period), even
# if another class wins on average. Raise to be stricter, lower to
# catch more seasonal farmland.
CROPS_PROB_THRESHOLD = 0.5

# Official Dynamic World palette
PALETTE = [
    "419bdf", "397d49", "88b053", "7a87c6", "e49635",
    "dfc35a", "c4281b", "a59b8f", "b39fe1",
]


def dw_class_image(buffer, start_date, end_date):
    """Classification image (values 0-8) for the period.

    Base: mean of per-class probabilities, argmax per pixel.
    Cropland boost: pixels whose crops probability is sustained high
    at some point in the season (90th percentile >= threshold) are
    classified as crops even if another class wins on average -
    seasonal farmland spends much of the year not looking like crops.
    """

    col = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(buffer)
        .filterDate(start_date, end_date)
    )

    probs = col.select(PROB_BANDS).mean()

    base = (
        probs.toArray()
        .arrayArgmax()
        .arrayGet([0])
        .rename("label")
    )

    seasonal_crops = (
        col.select("crops")
        .reduce(ee.Reducer.percentile([90]))
        .gte(CROPS_PROB_THRESHOLD)
    )

    return base.where(seasonal_crops, CROPS_INDEX)


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