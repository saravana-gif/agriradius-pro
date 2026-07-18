import streamlit as st

from config import APP_NAME

# Must be the first Streamlit command
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

from gee.auth import initialize
from utils.state import initialize_state
from ui.dashboard import dashboard

initialize()
initialize_state()

dashboard()
