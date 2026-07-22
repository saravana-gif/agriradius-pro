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

    # --- Overlay transparency (see imagery underneath) ---
    # Bind purely by key (no value= + reassignment) so the slider
    # doesn't jump while dragging.
    if "overlay_opacity" not in st.session_state:
        st.session_state["overlay_opacity"] = 0.5

    st.slider(
        "Overlay opacity",
        min_value=0.1, max_value=1.0,
        step=0.05,
        key="overlay_opacity",
        help="Lower = more see-through, so crops/imagery below show.",
    )

    # --- Compute quality lever (resolution vs EE compute/memory) ---
    from core import compute as _cq
    _cq.selector()

    st.caption(
        "Satellite layers are computed live and can take 10-30s the "
        "first time you enable one for an area; they load fast after "
        "(cached). Plantation is the heaviest. Use **Compute quality** "
        "above: Light if Earth Engine is throttled, Heavy for full "
        "10 m detail.")

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
    ("Water", "#419bdf"),
    ("Trees / Forest", "#397d49"),
    ("Grass", "#88b053"),
    ("Flooded Vegetation", "#7a87c6"),
    ("Crops (farmland)", "#ff00ff"),
    ("Shrub / Scrub", "#dfc35a"),
    ("Built-up", "#c4281b"),
    ("Bare Ground", "#a59b8f"),
    ("Snow / Ice", "#b39fe1"),
]

CONFIDENCE_LEGEND = [
    ("High confidence - both datasets agree: cropland", "#1a9850"),
    ("Uncertain - only one dataset says cropland", "#f4c20d"),
]

PADDY_LEGEND = [
    ("Detected paddy (flooded, then strong growth)", "#00e5ff"),
]

PLANTATION_LEGEND = [
    ("Likely coconut/arecanut (flat + evergreen in dry season)",
     "#ffff00"),
]

SOIL_PH_LEGEND = [
    ("pH ~5.0 - strongly acidic", "#d7191c"),
    ("pH ~6.0 - mildly acidic", "#fdae61"),
    ("pH ~6.5-7.0 - neutral (ideal)", "#ffffbf"),
    ("pH ~7.5 - mildly alkaline", "#a6d96a"),
    ("pH ~8.5 - strongly alkaline", "#2c7bb6"),
]

SOIL_OC_LEGEND = [
    ("~3 g/kg - low (needs organic matter)", "#fff7bc"),
    ("~6 g/kg - below average", "#d9f0a3"),
    ("~9 g/kg - moderate", "#78c679"),
    ("~12 g/kg - good", "#238443"),
    ("~15 g/kg - very good", "#004529"),
]

SOIL_N_LEGEND = [
    ("~0.5 g/kg - low nitrogen", "#fee8c8"),
    ("~1.0 g/kg - below average", "#fdbb84"),
    ("~1.5 g/kg - moderate", "#e34a33"),
    ("~2.0 g/kg - good", "#b30000"),
    ("~2.5 g/kg - high", "#7f0000"),
]


def _legend(title, items):

    rows = "".join(
        f'<div style="margin:1px 0">'
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'background:{color};margin-right:6px;border-radius:2px;'
        f'border:1px solid #8884"></span>'
        f'<span style="font-size:0.8em">{label}</span></div>'
        for label, color in items
    )

    st.markdown(
        f'<div style="margin-top:4px"><b style="font-size:0.85em">'
        f'{title}</b>{rows}</div>',
        unsafe_allow_html=True
    )


# Which legend belongs to which layer id
LEGENDS = {
    "dynamic_world": ("Dynamic World Land Cover", DW_LEGEND),
    "cropland_confidence": ("Cropland Confidence", CONFIDENCE_LEGEND),
    "paddy": ("Paddy (radar)", PADDY_LEGEND),
    "plantation": ("Plantations", PLANTATION_LEGEND),
    "banana": ("Banana (likely)",
               [("Dense closed canopy - likely banana", "#ff1493")]),
    "maize": ("Maize / kharif crop (likely)",
              [("Dense kharif crop, bare off-season", "#ff8c00")]),
    "worldcereal": ("WorldCereal Cropland (ESA, seasonal)",
                    [("Cropland (temporary crops)", "#e6550d")]),
    "aquaculture": ("Aquaculture ponds",
                    [("Persistent pond-sized water (fish/prawn/farm pond)",
                      "#1565c0")]),
    "soil_ph": ("Soil pH (0-30cm)", SOIL_PH_LEGEND),
    "soil_oc": ("Soil Organic Carbon (0-30cm)", SOIL_OC_LEGEND),
    "soil_n": ("Soil Total Nitrogen (0-30cm)", SOIL_N_LEGEND),
}


def legends():
    """Show a clear legend for every active overlay layer."""

    vis = st.session_state.layer_visibility

    for layer_id, (title, items) in LEGENDS.items():
        if vis.get(layer_id):
            _legend(title, items)
