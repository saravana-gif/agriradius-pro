import streamlit as st
import folium
from streamlit_folium import st_folium


def mapview():

    # Create map based on selected basemap
    if st.session_state.basemap == "OpenStreetMap":

        m = folium.Map(
            location=[st.session_state.lat, st.session_state.lon],
            zoom_start=11,
            tiles="OpenStreetMap"
        )

    else:

        m = folium.Map(
            location=[st.session_state.lat, st.session_state.lon],
            zoom_start=11,
            tiles=None
        )

        folium.TileLayer(
            tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
            attr="Google Satellite",
            name="Satellite"
        ).add_to(m)

    # Marker
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        tooltip="Selected Location"
    ).add_to(m)

    # Buffer circle
    folium.Circle(
        location=[st.session_state.lat, st.session_state.lon],
        radius=st.session_state.radius * 1000,
        color="green",
        fill=True,
        fill_opacity=0.2
    ).add_to(m)

    # Display map
    map_data = st_folium(
        m,
        width=None,
        height=650
    )

    # Map click
    if (
        st.session_state.input_method == "Map Click"
        and map_data
        and map_data.get("last_clicked")
    ):
        clicked = map_data["last_clicked"]

        st.session_state.lat = clicked["lat"]
        st.session_state.lon = clicked["lng"]

        st.rerun()