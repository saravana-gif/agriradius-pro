import streamlit as st

from config import APP_NAME

# Must be the first Streamlit command
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

from core.auth_gate import require_password
from gee.auth import initialize
from utils.state import initialize_state
from ui.dashboard import dashboard

# Shared-password gate (only active if APP_PASSWORD is set in secrets).
if not require_password():
    st.stop()

initialize()
initialize_state()

dashboard()
