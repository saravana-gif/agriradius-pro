import streamlit as st

from config import (
    DEFAULT_LAT,
    DEFAULT_LON,
    DEFAULT_RADIUS_KM,
    DEFAULT_YEAR,
)
from data.layer_registry import default_visibility

DEFAULTS = {
    "lat": DEFAULT_LAT,
    "lon": DEFAULT_LON,
    "radius": DEFAULT_RADIUS_KM,
    "year": DEFAULT_YEAR,
    "input_method": "Manual Coordinates",
    "search_location": "",
    "basemap": "OpenStreetMap",
    "analyze": False,
    "results": None,
    "ndvi_series": None,
    "crosscheck": None,
    "paddy_stats": None,
}


def initialize_state():

    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "layer_visibility" not in st.session_state:
        st.session_state.layer_visibility = default_visibility()
