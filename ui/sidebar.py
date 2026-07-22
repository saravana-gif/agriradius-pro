import streamlit as st
from core.geocoder import search_place
from gee.analysis import analyze_landcover


def sidebar():

    st.subheader("Search")

    place = st.text_input(
        "Place Name",
        value=st.session_state.search_location
    )

    if st.button("Search Place", use_container_width=True):

        result = search_place(place)

        if result:
            st.session_state.lat = result[0]
            st.session_state.lon = result[1]
            st.session_state.search_location = place
            st.rerun()
        else:
            st.error("Location not found")

    # --- Google Maps link / coordinates ---
    gmap = st.text_input(
        "Google Maps link or coordinates",
        placeholder="paste link or  12.9716, 77.5946",
        help="Paste a Google Maps share link or 'lat, lon'. Works "
             "for both Area and Point modes.",
    )

    if st.button("📍 Set from Google Location",
                 use_container_width=True):
        from core.location import parse_location
        loc = parse_location(gmap)
        if loc:
            st.session_state.lat, st.session_state.lon = loc
            st.session_state.search_location = "Google location"
            st.success(f"Set to {loc[0]:.6f}, {loc[1]:.6f}")
            st.rerun()
        else:
            st.error(
                "Couldn't read a location from that. Paste a Google "
                "Maps link or coordinates like '12.9716, 77.5946'.")

    st.divider()

    st.subheader("Input")

    # --- Analysis mode: area vs single point (mutually exclusive) ---
    st.session_state.mode = st.radio(
        "Analysis Mode",
        ["Area (radius)", "Point location"],
        index=0 if st.session_state.get("mode") != "Point location"
        else 1,
        help="Area summarises everything inside a radius. Point "
             "gives details for one exact coordinate (no radius).",
    )

    st.session_state.input_method = st.radio(
        "Input Method",
        [
            "Manual Coordinates",
            "Map Click"
        ],
        index=0 if st.session_state.input_method == "Manual Coordinates" else 1
    )

    st.session_state.lat = st.number_input(
        "Latitude",
        value=float(st.session_state.lat),
        format="%.6f"
    )

    st.session_state.lon = st.number_input(
        "Longitude",
        value=float(st.session_state.lon),
        format="%.6f"
    )

    # Radius controls appear ONLY in Area mode.
    if st.session_state.mode == "Area (radius)":

        if "radius_slider" not in st.session_state:
            st.session_state["radius_slider"] = int(st.session_state.radius)
        if "radius_num" not in st.session_state:
            st.session_state["radius_num"] = int(st.session_state.radius)

        _r = int(st.session_state.radius)
        if (st.session_state["radius_slider"] != _r
                and st.session_state["radius_num"] != _r):
            st.session_state["radius_slider"] = _r
            st.session_state["radius_num"] = _r

        def _radius_from_slider():
            v = st.session_state["radius_slider"]
            st.session_state.radius = v
            st.session_state["radius_num"] = v

        def _radius_from_num():
            v = st.session_state["radius_num"]
            st.session_state.radius = v
            st.session_state["radius_slider"] = v

        st.slider(
            "Radius (km)",
            1, 100,
            key="radius_slider",
            on_change=_radius_from_slider,
        )

        st.number_input(
            "Exact radius (km)",
            min_value=1, max_value=100, step=1,
            key="radius_num",
            on_change=_radius_from_num,
            help="Type an exact value; the slider stays in sync.",
        )

    st.session_state.year = st.selectbox(
        "Year",
        [2025, 2024, 2023],
        index=[2025, 2024, 2023].index(st.session_state.year)
    )

    st.divider()

    st.write("### Current Location")
    st.write(f"Latitude : {st.session_state.lat:.6f}")
    st.write(f"Longitude : {st.session_state.lon:.6f}")

    st.divider()

    if st.session_state.mode == "Area (radius)":

        if st.button("🔍 Analyze This Area", use_container_width=True,
                     type="primary",
                     help="Compute land cover for the buffer around "
                          "the selected point"):

            with st.spinner("Analyzing..."):

                st.session_state.results = analyze_landcover(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    st.session_state.year
                )

            from core.session_store import save_last
            save_last(st.session_state)

            st.success("Analysis Complete")

    else:
        st.caption(
            "Point mode: open the '📍 Point Details' section below "
            "the map to get everything for this exact coordinate."
        )
        from core.session_store import save_last
        save_last(st.session_state)