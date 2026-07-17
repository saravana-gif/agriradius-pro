import streamlit as st

from ui.sidebar import sidebar
from ui.layer_manager import layer_manager
from ui.mapview import mapview
from ui.results import results
from ui.project_panel import project_panel


def dashboard():

    st.title("🌾 AgriRadius Pro")
    st.caption("Agricultural GIS Intelligence Platform")

    left, right = st.columns([1, 3])

    with left:
        sidebar()
        st.divider()
        layer_manager()
        st.divider()
        project_panel()

    with right:
        mapview()

    st.divider()
    results()