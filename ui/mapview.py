import streamlit as st
import folium
from streamlit_folium import st_folium

from data.layer_registry import BASEMAPS


def _add_basemap(m):
    """Add the selected basemap from the registry."""

    base = BASEMAPS.get(
        st.session_state.basemap,
        BASEMAPS["OpenStreetMap"]
    )

    if base["attr"]:
        folium.TileLayer(
            tiles=base["tiles"],
            attr=base["attr"],
            name=st.session_state.basemap
        ).add_to(m)


def _add_villages(m):
    """Draw village boundaries inside the buffer (basic outline)."""

    from gis.spatial import villages_in_buffer

    try:
        gdf = villages_in_buffer(
            st.session_state.lat,
            st.session_state.lon,
            st.session_state.radius
        )
    except Exception as e:
        st.warning(f"Could not load villages: {e}")
        return

    if gdf.empty:
        return

    name_col = next(
        (c for c in ("vilname11", "vilname", "name") if c in gdf.columns),
        None
    )

    cols = ["geometry"] + ([name_col] if name_col else [])

    folium.GeoJson(
        gdf[cols],
        name="Villages",
        style_function=lambda f: {
            "color": "#1f6feb",
            "weight": 1,
            "fillOpacity": 0.05,
        },
        tooltip=folium.GeoJsonTooltip(fields=[name_col])
        if name_col else None,
    ).add_to(m)


def mapview():

    vis = st.session_state.layer_visibility

    base = BASEMAPS.get(
        st.session_state.basemap,
        BASEMAPS["OpenStreetMap"]
    )

    if base["attr"] is None:
        m = folium.Map(
            location=[st.session_state.lat, st.session_state.lon],
            zoom_start=11,
            tiles=base["tiles"]
        )
    else:
        m = folium.Map(
            location=[st.session_state.lat, st.session_state.lon],
            zoom_start=11,
            tiles=None
        )
        _add_basemap(m)

    if vis.get("marker"):
        folium.Marker(
            [st.session_state.lat, st.session_state.lon],
            tooltip="Selected Location"
        ).add_to(m)

    if vis.get("buffer"):
        folium.Circle(
            location=[st.session_state.lat, st.session_state.lon],
            radius=st.session_state.radius * 1000,
            color="green",
            fill=True,
            fill_opacity=0.2
        ).add_to(m)

    if vis.get("villages"):
        _add_villages(m)

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