"""Village lookup for the current buffer, as a display-ready table."""

import pandas as pd
import streamlit as st

from gis.spatial import villages_in_buffer

DISPLAY_COLS = {
    "vilname11": "Village",
    "sdtname": "Taluk",
    "dtname": "District",
    "stname": "State",
}


@st.cache_data(show_spinner="Finding villages in buffer...")
def get_villages(lat, lon, radius):
    """Return villages intersecting the buffer as a plain DataFrame."""

    gdf = villages_in_buffer(lat, lon, radius)

    cols = [c for c in DISPLAY_COLS if c in gdf.columns]

    df = pd.DataFrame(gdf[cols]).rename(columns=DISPLAY_COLS)

    sort_cols = [c for c in ("District", "Taluk", "Village") if c in df.columns]

    if sort_cols:
        df = df.sort_values(sort_cols)

    return df.reset_index(drop=True)