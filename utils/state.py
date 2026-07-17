import streamlit as st

DEFAULTS = {
    "lat": 11.923456,
    "lon": 76.940123,
    "radius": 38,
    "year": 2025,
    "input_method": "Manual Coordinates",
    "search_location": "",
    "basemap": "OpenStreetMap",
    "analyze": False,
    "results": None,
}

def initialize_state():
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value