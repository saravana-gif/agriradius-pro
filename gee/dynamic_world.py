"""Dynamic World display tiles for the map."""

import ee
import streamlit as st

# Official Dynamic World palette, classes 0-8:
# water, trees, grass, flooded_vegetation, crops,
# shrub_and_scrub, built, bare, snow_and_ice
PALETTE = [
    "419bdf", "397d49", "88b053", "7a87c6", "e49635",
    "dfc35a", "c4281b", "a59b8f", "b39fe1",
]


@st.cache_data(show_spinner="Loading Dynamic World overlay...")
def get_tile_url(lat, lon, radius_km, year):
    """Return an XYZ tile URL for the Dynamic World mode composite."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    dw = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(buffer)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .select("label")
        .mode()
        .clip(buffer)
    )

    mapid = dw.getMapId({"min": 0, "max": 8, "palette": PALETTE})

    return mapid["tile_fetcher"].url_format