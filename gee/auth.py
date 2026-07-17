import ee
import streamlit as st

from config import PROJECT_ID


@st.cache_resource(show_spinner="Connecting to Google Earth Engine...")
def initialize():
    """Initialize Earth Engine once per server session (cached)."""

    try:
        ee.Initialize(project=PROJECT_ID)

    except Exception:

        ee.Authenticate()

        ee.Initialize(project=PROJECT_ID)

    return True
