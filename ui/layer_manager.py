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