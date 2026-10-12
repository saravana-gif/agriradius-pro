import streamlit as st

st.set_page_config(page_title="Field report", page_icon="📝",
                   layout="centered")

from core.auth_gate import require_password  # noqa: E402

if not require_password():
    st.stop()

from ui.field_report_page import field_report_page  # noqa: E402

field_report_page()
