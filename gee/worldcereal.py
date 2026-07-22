"""ESA WorldCereal cropland - an independent seasonal-crop map.

WorldCereal (10 m, 2021) is built by ESA from a different pipeline
than Dynamic World, so it's a useful third opinion on where seasonal
cropland is. Note: it maps *temporary* crops, so it will NOT flag
perennial plantations (coconut/arecanut) - use it alongside, not
instead of, the plantation layer.
"""

import ee
import streamlit as st

CROPLAND_COLOR = "e6550d"  # orange-brown


def _temporary_crops():
    """Mosaic of the WorldCereal annual temporary-crops product."""
    return (
        ee.ImageCollection("ESA/WorldCereal/2021/MODELS/v100")
        .filter(ee.Filter.eq("product", "temporarycrops"))
        .select("classification")
        .mosaic()
    )


@st.cache_data(show_spinner="Loading WorldCereal cropland...")
def worldcereal_tile_url(lat, lon, radius_km):
    """Tile URL showing WorldCereal cropland (value 100)."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    crops = _temporary_crops().eq(100)
    img = crops.updateMask(crops).clip(buffer)

    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", CROPLAND_COLOR]})

    return mapid["tile_fetcher"].url_format
