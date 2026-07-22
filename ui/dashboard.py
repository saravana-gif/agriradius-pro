import streamlit as st

from config import APP_NAME, LOGO_PATH
from ui.sidebar import sidebar
from ui.layer_manager import layer_manager
from ui.mapview import mapview
from ui.results import results
from ui.project_panel import project_panel

_CSS = """
<style>
/* --- OneRoot AgriRadius Pro - professional polish --- */
.block-container {padding-top: 3rem; padding-bottom: 2rem; max-width: 1400px;}
header[data-testid="stHeader"] {background: transparent;}
h1, h2, h3 {color: #0E3D20; font-weight: 700; letter-spacing: -0.01em;}
/* Metric cards */
div[data-testid="stMetric"] {
    background: #F1F7F2; border: 1px solid #E1EDE4;
    border-radius: 12px; padding: 12px 14px;
}
div[data-testid="stMetricLabel"] p {color: #5B6770; font-weight: 600;}
div[data-testid="stMetricValue"] {color: #0E3D20;}
/* Tabs */
button[data-baseweb="tab"] {font-weight: 600;}
div[data-baseweb="tab-list"] {gap: 2px;}
/* Primary buttons */
div.stButton > button[kind="primary"] {
    background: #1B7A3D; border: 0; border-radius: 8px; font-weight: 600;
}
div.stButton > button[kind="primary"]:hover {background: #14602F;}
div.stButton > button {border-radius: 8px;}
/* Sidebar */
section[data-testid="stSidebar"] {background: #FBFDFB;}
section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {
    color: #1B7A3D;
}
/* Dataframes */
div[data-testid="stDataFrame"] {border-radius: 8px;}
/* Header band */
.or-header {
    display:flex; align-items:center; gap:14px;
    border-bottom: 3px solid #1B7A3D; padding-bottom: 10px; margin-bottom: 14px;
}
.or-header .t {font-size: 1.9rem; font-weight: 800; color:#0E3D20; line-height:1;}
.or-header .s {font-size: 0.9rem; color:#5B6770;}
</style>
"""


def dashboard():

    st.markdown(_CSS, unsafe_allow_html=True)

    if LOGO_PATH.exists():

        c_logo, c_title = st.columns([1, 9])

        with c_logo:
            st.image(str(LOGO_PATH), width=84)

        with c_title:
            st.markdown(
                f"<div style='padding-top:6px'>"
                f"<div style='font-size:1.9rem;font-weight:800;"
                f"color:#0E3D20;line-height:1.1'>{APP_NAME}</div>"
                f"<div style='color:#5B6770;font-size:0.9rem'>"
                f"Agricultural GIS Intelligence Platform &nbsp;·&nbsp; "
                f"OneRoot (ENP Farms)</div></div>",
                unsafe_allow_html=True)
        st.markdown(
            "<hr style='margin:8px 0 4px;border:none;"
            "border-top:3px solid #1B7A3D'>", unsafe_allow_html=True)

    else:
        st.title(f"🌾 {APP_NAME}")
        st.caption("Agricultural GIS Intelligence Platform")

    st.caption(
        "ℹ️ Free open-source build (Google Earth Engine) with a limited "
        "shared monthly compute budget - please test mindfully: one "
        "heavy layer at a time, avoid very large radii and rapid repeat "
        "clicks. Live usage is in the sidebar's *Service health* panel.")

    # All controls live in the collapsible sidebar - on mobile it
    # folds into a hamburger menu and the map/results get the full
    # screen width.
    with st.sidebar:
        sidebar()
        st.divider()
        layer_manager()
        st.divider()
        project_panel()
        st.divider()
        from core.usage import health_panel
        health_panel()

    mapview()

    st.divider()

    results()