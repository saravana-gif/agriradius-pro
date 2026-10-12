import streamlit as st

st.set_page_config(page_title="Alerts & share kit", page_icon="📣",
                   layout="centered")

from core.auth_gate import require_password  # noqa: E402

if not require_password():
    st.stop()

from ui.alerts_page import alerts_page  # noqa: E402

alerts_page()
