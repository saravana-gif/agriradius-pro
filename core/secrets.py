"""Tolerant secret lookup.

Reads a key from the TOP LEVEL of st.secrets, and also from inside the
[auth] table as a fallback.

Why: in TOML, every key written after a [section] header belongs to
that section. If someone pastes plain keys (service account, sheet id,
owner email...) below the [auth] block, those keys silently become
st.secrets["auth"][key] instead of st.secrets[key] - and Earth Engine /
Sheets can't find them. This helper checks both places so that
ordering mistake can't take the app down.
"""

import streamlit as st


def get(key, default=None):
    # Top level first.
    try:
        val = st.secrets.get(key)
        if val is not None:
            return val
    except Exception:
        pass
    # Fallback: nested under the [auth] table.
    try:
        auth = st.secrets.get("auth")
        if auth is not None and hasattr(auth, "get"):
            val = auth.get(key)
            if val is not None:
                return val
    except Exception:
        pass
    return default
