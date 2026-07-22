import streamlit as st
from streamlit_folium import st_folium

from ui.map_engine import MapEngine


def mapview():

    vis = st.session_state.layer_visibility
    _op = float(st.session_state.get("overlay_opacity", 0.5))

    lat = st.session_state.lat
    lon = st.session_state.lon

    # --- Preserve the user's pan/zoom across reruns ---
    # If the selected point changed (search / manual / map click),
    # recenter on it; otherwise keep the view the user navigated to.
    anchor = (round(lat, 6), round(lon, 6))

    if st.session_state.get("map_anchor") != anchor:
        st.session_state.map_anchor = anchor
        st.session_state.map_center = [lat, lon]

    center = st.session_state.get("map_center", [lat, lon])
    zoom = int(st.session_state.get("map_zoom", 11))

    engine = MapEngine(
        lat,
        lon,
        zoom=zoom,
        basemap=st.session_state.basemap,
        center=center,
    )

    if vis.get("marker"):
        engine.add_marker()

    # The buffer circle only makes sense in Area mode.
    if vis.get("buffer") and \
            st.session_state.get("mode") == "Area (radius)":
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
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load villages: {e}")

    if vis.get("dynamic_world"):

        from gee.dynamic_world import get_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = get_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Dynamic World",
                                    opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load Dynamic World overlay: {e}")

    if vis.get("cropland_confidence"):

        from gee.worldcover import confidence_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = confidence_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Cropland Confidence",
                                    opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load confidence layer: {e}")

    if vis.get("paddy"):

        from gee.paddy import paddy_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = paddy_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Paddy Fields", opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load paddy layer: {e}")

    if vis.get("plantation"):

        from gee.plantation import plantation_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = plantation_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Plantations", opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load plantation layer: {e}")

    if vis.get("banana"):

        from gee.plantation import banana_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = banana_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Banana", opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load banana layer: {e}")

    if vis.get("worldcereal"):

        from gee.worldcereal import worldcereal_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = worldcereal_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
            )
            engine.add_tile_overlay(url, "WorldCereal Cropland",
                                    opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load WorldCereal layer: {e}")

    if vis.get("maize"):

        from gee.maize import maize_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = maize_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Maize", opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load maize layer: {e}")

    if vis.get("aquaculture"):

        from gee.aquaculture import aquaculture_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = aquaculture_tile_url(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            engine.add_tile_overlay(url, "Aquaculture ponds", opacity=_op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load aquaculture layer: {e}")

    for soil_layer in ("soil_ph", "soil_oc", "soil_n"):

        if vis.get(soil_layer):

            from gee.soil import soil_tile_url

            try:
                from core import usage as _u
                _u.bump("earth_engine")
                url = soil_tile_url(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    soil_layer
                )
                engine.add_tile_overlay(
                    url, soil_layer, opacity=_op)
            except Exception as e:
                from core import usage as _u
                _u.note_error("earth_engine", e)
                st.warning(_u.friendly(e) or f"Could not load {soil_layer}: {e}")

    # --- Refresh button: remounts the map so any tiles that failed
    # to load (Earth Engine timeouts at high zoom) are re-requested,
    # without having to nudge the opacity slider. ---
    rc1, rc2 = st.columns([1, 4])
    with rc1:
        if st.button("🔄 Refresh map", use_container_width=True,
                     help="Reload any missing overlay tiles at the "
                          "current view"):
            st.session_state.map_refresh = \
                st.session_state.get("map_refresh", 0) + 1
    with rc2:
        st.caption(
            "If overlay tiles are missing after zooming, click "
            "Refresh map to reload them.")

    map_data = st_folium(
        engine.render(),
        width=None,
        height=650,
        returned_objects=["last_clicked", "center", "zoom"],
        key=f"map_{st.session_state.get('map_refresh', 0)}",
    )

    # Capture the current view so changing a setting (opacity, layers)
    # keeps the same place instead of snapping back to the point.
    if map_data:
        c = map_data.get("center")
        if c and "lat" in c and "lng" in c:
            st.session_state.map_center = [c["lat"], c["lng"]]
        if map_data.get("zoom") is not None:
            st.session_state.map_zoom = map_data["zoom"]

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
