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

    # SHC measured-data choropleth: pick which soil-test metric to
    # paint (district-level lab data, cycle-based - see Soil tab).
    if st.session_state.layer_visibility.get("shc"):
        from gis import shc_layer
        opts = shc_layer.metric_options()
        keys = [k for k, _ in opts]
        labels = {k: l for k, l in opts}
        st.selectbox(
            "SHC metric to paint",
            keys,
            format_func=lambda k: labels[k],
            key="shc_map_metric",
            help="Lab-tested farmer samples from the Soil Health "
                 "Card scheme - real measurements.",
        )
        st.radio(
            "SHC resolution",
            ["District average", "Village detail (live)"],
            key="shc_map_res",
            help="Village detail fetches each village's own lab "
                 "results live from the SHC portal for the selected "
                 "area. Covers Karnataka, Tamil Nadu, Kerala, Andhra "
                 "Pradesh & Maharashtra. Large areas load in batches "
                 "- click 'Refresh map' to fill in more villages "
                 "(everything fetched is cached). Grey villages have "
                 "no samples yet or no boundary match. Sample counts "
                 "per village are small - treat as indicative.",
        )

    # Irrigation source: village or district resolution, and which
    # metric to paint.
    if st.session_state.layer_visibility.get("irrigation_source"):
        from gis import irrigation_layer

        res = st.radio(
            "Irrigation resolution",
            ["Village detail (measured, live)", "District statistics"],
            key="irrigation_res",
            help="Village detail measures each village polygon's OWN "
                 "irrigated area from satellite - like the SHC "
                 "village layer. District statistics show the "
                 "government source split (canal / borewell / tank), "
                 "which is only published per district.",
        )

        if str(res).startswith("Village"):
            opts = irrigation_layer.village_metric_options()
            keys = [k for k, _ in opts]
            labels = {k: l for k, l in opts}
            st.selectbox(
                "Village irrigation metric",
                keys,
                format_func=lambda k: labels[k],
                key="irrigation_village_metric",
                help="Measured per village for the analysis circle: "
                     "irrigated share, irrigated acres, likely "
                     "borewell-fed acres, acres two or more methods "
                     "agree on, and radar wetting events. First run "
                     "takes 1-3 minutes, then it is cached.",
            )
        else:
            opts = irrigation_layer.metric_options()
            keys = [k for k, _ in opts]
            labels = {k: l for k, l in opts}
            st.selectbox(
                "District irrigation metric",
                keys, index=keys.index("borewell_pct"),
                format_func=lambda k: labels[k],
                key="irrigation_metric",
                help="District irrigation by SOURCE (Land Use "
                     "Statistics 2022-23, Karnataka). The "
                     "borewell/canal split is the operational one: "
                     "canal-led districts can be targeted from "
                     "command-area maps, borewell-led districts "
                     "cannot - those wells are invisible to "
                     "infrastructure data.",
            )

    # Coconut crop survey: measured, village-level government records.
    if st.session_state.layer_visibility.get("coconut_survey"):
        from gis import crop_survey_layer
        opts = crop_survey_layer.metric_options()
        keys = [k for k, _ in opts]
        labels = {k: l for k, l in opts}
        st.selectbox(
            "Coconut survey metric",
            keys,
            format_func=lambda k: labels[k],
            key="coconut_survey_metric",
            help="Village-level coconut records from the Karnataka "
                 "crop survey (2023-24 Kharif): plot counts, growers "
                 "and the land attached to them. Ground-recorded, not "
                 "a satellite estimate. Covers Hassan, Mandya, "
                 "Tumakuru, Ramanagara, Chitradurga and Mysuru.",
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

    if vis.get("shc"):
        from gis import shc_layer
        metric = st.session_state.get("shc_map_metric", "n_low")
        if metric in shc_layer.METRICS:
            _legend(
                f"SHC: {shc_layer.METRICS[metric][0]}",
                [(lab, col)
                 for lab, col in shc_layer.legend_items(metric)])

    if vis.get("irrigation_source"):
        from gis import irrigation_layer
        res = st.session_state.get("irrigation_res", "")
        if str(res).startswith("Village"):
            vm = st.session_state.get("irrigation_village_metric",
                                      "irrigated_pct")
            if vm in irrigation_layer.VILLAGE_METRICS:
                _legend(
                    f"Village irrigation: "
                    f"{irrigation_layer.VILLAGE_METRICS[vm][0]}",
                    irrigation_layer.village_legend_items(vm))
        else:
            metric = st.session_state.get("irrigation_metric",
                                          "borewell_pct")
            if metric in irrigation_layer.METRICS:
                _legend(
                    f"Irrigation: "
                    f"{irrigation_layer.METRICS[metric][0]}",
                    irrigation_layer.legend_items(metric))

    if vis.get("irrigation_lgrip"):
        _legend("LGRIP30 irrigated vs rain-fed",
                [("Irrigated cropland", "#00c2ff"),
                 ("Rain-fed cropland", "#d9a441")])

    if vis.get("irrigation_summer"):
        _legend("Irrigated (green through Feb-May dry season)",
                [("Irrigated cropland", "#00c2ff")])

    if vis.get("forest_cover"):
        _legend("Forest cover (JRC GFC2020 - excludes tree crops)",
                [("Natural / primary forest", "#1b5e20"),
                 ("Planted forest (EUDR subtype)", "#8d6e63")])

    if vis.get("farmland_trees"):
        _legend("Farmland trees - canopy that is NOT forest",
                [("Arecanut, coconut, coffee, mango, cashew, rubber, "
                  "woodlots", "#ffa000")])

    if vis.get("plantation_net"):
        _legend("Plantation with natural forest removed",
                [("Genuine plantation / tree crop", "#ffe000")])

    if vis.get("irrigation_evidence"):
        _legend("Irrigation confidence - independent methods agreeing",
                [("1 of 5 methods", "#fee5d9"),
                 ("2 of 5", "#fcae91"),
                 ("3 of 5 - worth a field visit", "#fb6a4a"),
                 ("4 of 5", "#de2d26"),
                 ("5 of 5 - as certain as remote sensing gets",
                  "#a50f15")])

    if vis.get("irrigation_events"):
        _legend("Irrigation events detected by radar (Feb-May)",
                [("VV backscatter rise >= 1 dB", "#ff4081")])

    if vis.get("irrigation_water_source"):
        _legend("Inferred water source of irrigated land",
                [("Near permanent water - canal/tank plausible",
                  "#1f78b4"),
                 ("Far from surface water - borewell almost certain",
                  "#e6550d")])

    if vis.get("irrigation_command"):
        _legend("Canal command areas (ayakat)",
                [("Land a canal actually serves", "#1f78b4")])

    if vis.get("irrigation_multicrop"):
        _legend("Multi-crop land (2+ crops a year)",
                [("Two or more crops", "#7b1fa2")])

    if vis.get("coconut_survey"):
        from gis import crop_survey_layer
        metric = st.session_state.get("coconut_survey_metric",
                                      "intensity")
        if metric in crop_survey_layer.METRICS:
            _legend(
                f"Coconut survey: "
                f"{crop_survey_layer.METRICS[metric][0]}",
                crop_survey_layer.legend_items(metric))
