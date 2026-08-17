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
    """Kick off the one-shot data fetchers in the background (each
    exits immediately when its data is already present). Runs once per
    server process; never blocks the UI.

    The server is the only place these can run: it has open internet
    and an Indian IP, which several of these government services
    require. Nothing here needs a shell session - a deploy is enough.
    """
    import subprocess
    import sys as _sys
    from config import PROJECT_ROOT

    for script in ("fetch_boundaries.py",
                   "fetch_wris_command_areas.py"):
        try:
            subprocess.Popen(
                ["nice", "-n", "10", _sys.executable,
                 str(PROJECT_ROOT / "scripts" / script)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            continue
    return True


_boundary_bootstrap()

# Shared-password gate (only active if APP_PASSWORD is set in secrets).
if not require_password():
    st.stop()

initialize()
initialize_state()

dashboard()
