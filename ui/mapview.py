import streamlit as st
from streamlit_folium import st_folium

from ui.map_engine import MapEngine


def mapview():

    vis = st.session_state.layer_visibility

    engine = MapEngine(
        st.session_state.lat,
        st.session_state.lon,
        zoom=11,
        basemap=st.session_state.basemap
    )

    if vis.get("marker"):
        engine.add_marker()

    if vis.get("buffer"):
        engine.add_buffer(st.session_state.radius)

    if vis.get("villages"):

        from gis.spatial import villages_in_buffer

        try:
            gdf = villages_in_buffer(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius
            )
            engine.add_villages(
                gdf,
                popup_fields=["vilname11", "sdtname", "dtname", "stname"],
                popup_aliases=["Village", "Taluk", "District", "State"],
            )
        except Exception as e:
            st.warning(f"Could not load villages: {e}")

    if vis.get("dynamic_world"):

        from gee.dynamic_world import get_tile_url

        try:
            url = get_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Dynamic World")
        except Exception as e:
            st.warning(f"Could not load Dynamic World overlay: {e}")

    if vis.get("cropland_confidence"):

        from gee.worldcover import confidence_tile_url

        try:
            url = confidence_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Cropland Confidence",
                                    opacity=0.7)
        except Exception as e:
            st.warning(f"Could not load confidence layer: {e}")

    if vis.get("paddy"):

        from gee.paddy import paddy_tile_url

        try:
            url = paddy_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Paddy Fields", opacity=0.8)
        except Exception as e:
            st.warning(f"Could not load paddy layer: {e}")

    map_data = st_folium(
        engine.render(),
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
