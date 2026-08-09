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


@st.cache_resource
def _boundary_bootstrap():
    """Kick off the one-shot boundary fetcher in the background (it
    exits immediately when everything is already present). Runs once
    per server process; never blocks the UI."""
    import subprocess
    import sys as _sys
    from config import PROJECT_ROOT
    try:
        subprocess.Popen(
            ["nice", "-n", "10", _sys.executable,
             str(PROJECT_ROOT / "scripts" / "fetch_boundaries.py")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return True


_boundary_bootstrap()

# Shared-password gate (only active if APP_PASSWORD is set in secrets).
if not require_password():
    st.stop()

initialize()
initialize_state()

dashboard()
