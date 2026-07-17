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

    st.divider()

    st.subheader("Input")

    st.session_state.input_method = st.radio(
        "Input Method",
        [
            "Manual Coordinates",
            "Map Click"
        ],
        index=0 if st.session_state.input_method == "Manual Coordinates" else 1
    )

    st.session_state.basemap = st.selectbox(
        "Basemap",
        [
            "OpenStreetMap",
            "Satellite"
        ]
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

    st.session_state.radius = st.slider(
        "Radius (km)",
        1,
        100,
        int(st.session_state.radius)
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

    if st.button("Analyze", use_container_width=True):

        with st.spinner("Analyzing..."):

            st.session_state.results = analyze_landcover(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )

        st.success("Analysis Complete")