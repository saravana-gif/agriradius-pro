"""Layer Manager panel.

Builds itself entirely from data/layer_registry.py - do not add
hardcoded layers here.
"""

import streamlit as st

from data.layer_registry import BASEMAPS, LAYERS


def layer_manager():

    st.subheader("Layers")

    # --- Basemap ---
    basemaps = list(BASEMAPS.keys())

    current = st.session_state.basemap
    index = basemaps.index(current) if current in basemaps else 0

    st.session_state.basemap = st.selectbox(
        "Basemap",
        basemaps,
        index=index
    )

    # --- Overlays, grouped by category ---
    for category, layers in LAYERS.items():

        st.caption(category)

        for layer in layers:

            layer_id = layer["id"]

            st.session_state.layer_visibility[layer_id] = st.checkbox(
                layer["label"],
                value=st.session_state.layer_visibility.get(
                    layer_id, layer["default"]
                ),
                key=f"layer_{layer_id}"
            )

    legends()


DW_LEGEND = [
    ("Water", "#419bdf"), ("Trees", "#397d49"), ("Grass", "#88b053"),
    ("Flooded Veg", "#7a87c6"), ("Crops", "#e49635"),
    ("Shrub/Scrub", "#dfc35a"), ("Built-up", "#c4281b"),
    ("Bare", "#a59b8f"), ("Snow/Ice", "#b39fe1"),
]

CONFIDENCE_LEGEND = [
    ("Both datasets agree: cropland", "#1a9850"),
    ("Only one dataset says cropland", "#f4c20d"),
]


def _legend(title, items):

    rows = "".join(
        f'<div style="margin:1px 0">'
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'background:{color};margin-right:6px;border-radius:2px"></span>'
        f'<span style="font-size:0.8em">{label}</span></div>'
        for label, color in items
    )

    st.markdown(
        f'<div style="margin-top:4px"><b style="font-size:0.8em">'
        f'{title}</b>{rows}</div>',
        unsafe_allow_html=True
    )


def legends():
    """Show legends for any active raster overlays."""

    vis = st.session_state.layer_visibility

    if vis.get("dynamic_world"):
        _legend("Dynamic World", DW_LEGEND)

    if vis.get("cropland_confidence"):
        _legend("Cropland Confidence", CONFIDENCE_LEGEND)