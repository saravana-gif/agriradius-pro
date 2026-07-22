"""Simple shared-password gate for the deployed app.

If `APP_PASSWORD` is set in secrets, visitors must enter it before the
app loads (keeps random visitors from burning your Earth Engine quota).
If it is NOT set (e.g. local dev), the app is open. One shared password
for everyone - deliberately simple to hand out.
"""

import streamlit as st


def _expected():
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None


def require_password():
    """Return True if allowed in, else render the login and return
    False (caller should st.stop())."""
    expected = _expected()
    if not expected:
        return True  # no password configured -> open
    if st.session_state.get("auth_ok"):
        return True

    st.markdown(
        "<div style='max-width:420px;margin:10vh auto 0;text-align:center'>"
        "<div style='font-size:1.6rem;font-weight:800;color:#0E3D20'>"
        "🌾 OneRoot AgriRadius Pro</div>"
        "<div style='color:#5B6770;margin:6px 0 18px'>"
        "Enter the access password to continue.</div></div>",
        unsafe_allow_html=True)

    c = st.columns([1, 2, 1])[1]
    with c:
        with st.form("login", clear_on_submit=False):
            pw = st.text_input("Password", type="password",
                               label_visibility="collapsed",
                               placeholder="Access password")
            ok = st.form_submit_button("Enter", use_container_width=True,
                                       type="primary")
        if ok:
            if pw == expected:
                st.session_state.auth_ok = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.caption(
            "ℹ️ This runs on a free, open-source setup (Google Earth "
            "Engine) with a **limited shared monthly compute budget**. "
            "Please test mindfully - avoid rapid repeated clicks and "
            "very large search radii, and enable one heavy layer at a "
            "time.")
    return False
