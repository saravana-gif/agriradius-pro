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
    "overlay_opacity": 0.5,
    "analyze": False,
    "results": None,
    "ndvi_series": None,
    "crosscheck": None,
    "paddy_stats": None,
    "village_insights": None,
    "rainfall_series": None,
    "stability": None,
    "report_pdf": None,
    "soil": None,
    "plantation_stats": None,
    "village_soil": None,
    "soil_climate": None,
    "sourcing_scores": None,
    "report_path": None,
    "full_pdf_bytes": None,
    "full_pdf_path": None,
    "full_excel_bytes": None,
    "full_excel_path": None,
    "full_notes": None,
    "mandi_df": None,
    "mandi_label": None,
    "mandi_state": None,
    "classifier_result": None,
    "forecast_days": None,
    "mode": "Area (radius)",
    "point_result": None,
    "multi_points_df": None,
}


def initialize_state():

    # Start from defaults, then overlay the last-used location so the
    # app reopens where the user left off.
    from core.session_store import load_last

    last = load_last()

    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = last.get(key, value) \
                if key in ("lat", "lon", "radius", "year",
                           "search_location", "basemap") else value

    if "layer_visibility" not in st.session_state:
        st.session_state.layer_visibility = default_visibility()
