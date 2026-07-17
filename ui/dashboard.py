import streamlit as st

from ui.sidebar import sidebar
from ui.mapview import mapview
from ui.results import results


def dashboard():

    st.set_page_config(
        page_title="AgriRadius Pro",
        page_icon="🌾",
        layout="wide"
    )

    st.title("🌾 AgriRadius Pro")
    st.caption("Agricultural GIS Intelligence Platform")

    left, right = st.columns([1, 3])

    with left:
        sidebar()

    with right:
        mapview()

    st.divider()

    results()