import streamlit as st

from config import APP_NAME, LOGO_PATH
from ui.sidebar import sidebar
from ui.layer_manager import layer_manager
from ui.mapview import mapview
from ui.results import results
from ui.project_panel import project_panel


def dashboard():

    if LOGO_PATH.exists():

        c_logo, c_title = st.columns([1, 8])

        with c_logo:
            st.image(str(LOGO_PATH), width=90)

        with c_title:
            st.title(APP_NAME)
            st.caption("Agricultural GIS Intelligence Platform")

    else:
        st.title(f"🌾 {APP_NAME}")
        st.caption("Agricultural GIS Intelligence Platform")

    # All controls live in the collapsible sidebar - on mobile it
    # folds into a hamburger menu and the map/results get the full
    # screen width.
    with st.sidebar:
        sidebar()
        st.divider()
        layer_manager()
        st.divider()
        project_panel()

    mapview()

    st.divider()

    results()