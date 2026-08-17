import streamlit as st
from streamlit_folium import st_folium

from gee.tiles import fresh_tile_url
from ui.map_engine import MapEngine


@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def _district_gdf(state_key, district):
    from gis import admin_areas
    return admin_areas.district_villages(state_key, district)


def _overlay(engine, url, name, opacity):
    """Add a tile overlay, and SAY SO when a layer cannot be drawn.

    Silence was the old failure mode: an expired Earth Engine token
    made every layer render as plain satellite with no hint that
    anything was wrong. Now a missing layer always announces itself.
    """
    if not url:
        st.warning(
            f"**{name}** could not be drawn just now - Earth Engine "
            "did not return a usable tile layer. Click **Refresh "
            "map**; if it persists, the shared compute budget may be "
            "throttled.")
        return False
    engine.add_tile_overlay(url, name, opacity=opacity)
    return True


def _region_geometry(engine, mode):
    """Draw district villages / state extent / compare points."""
    region = st.session_state.get("region") or {}

    if mode == "Multiple points":
        pts = st.session_state.get("multi_points") or []
        if pts:
            engine.add_points(pts)
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            engine.fit_bounds(min(lons) - 0.1, min(lats) - 0.1,
                              max(lons) + 0.1, max(lats) + 0.1)
        else:
            st.caption("Add points in the sidebar to see them here.")
        return

    if mode == "District" and region.get("kind") == "district":
        from gis import shc_layer
        gj = None
        with st.spinner("Painting villages by measured soil health "
                        "(cached lab data)..."):
            try:
                gj = shc_layer.geojson_district(
                    region["state"], region["district"])
            except Exception:
                gj = None
        if gj:
            engine.add_choropleth(gj, "Soil health score",
                                  fill_opacity=0.65)
            legend = "  ·  ".join(
                f"{lab}" for _, _, lab in shc_layer.SCORE_BINS)
            st.caption(
                f"**{region['district'].title()}** - "
                f"{len(gj['features']):,} villages coloured by "
                f"measured soil-health score (green = better): "
                f"{legend}; grey = no lab samples. Hover any village "
                "for its score, reasons and sample count. Full "
                "report below the map.")
            b = None
            with st.spinner(""):
                gdf = _district_gdf(region["state"],
                                    region["district"])
                if gdf is not None and not gdf.empty:
                    b = gdf.total_bounds
            if b is not None:
                engine.fit_bounds(b[0], b[1], b[2], b[3])
            return
        # Fallback: plain borders if the colour join failed
        with st.spinner("Loading district boundaries..."):
            gdf = _district_gdf(region["state"], region["district"])
        if gdf is None or gdf.empty:
            st.warning("Could not load this district's villages.")
            return
        show = gdf.copy()
        show["geometry"] = show.geometry.simplify(
            0.0002, preserve_topology=True)
        engine.add_villages(
            show,
            popup_fields=["vilname11", "sdtname", "dtname", "stname"],
            popup_aliases=["Village", "Taluk", "District", "State"],
        )
        b = gdf.total_bounds
        engine.fit_bounds(b[0], b[1], b[2], b[3])
        st.caption(
            f"**{region['district'].title()}** - {len(gdf):,} village "
            "boundaries (soil colours unavailable right now).")
        return

    if mode == "State" and region.get("kind") == "state":
        from gis.boundary_loader import STATE_BBOXES
        bb = STATE_BBOXES.get(region["state"])
        if bb:
            engine.fit_bounds(bb[0], bb[1], bb[2], bb[3])
        st.caption(
            "State view - district rankings and state-wide village "
            "rankings are in the report below the map. Open a "
            "district (sidebar → District) for its exact village "
            "borders.")
        return

    st.caption("Choose a region in the sidebar and open its report.")


def _render_map(engine):
    map_data = st_folium(
        engine.render(),
        width=None,
        height=650,
        returned_objects=["center", "zoom"],
        key=f"map_{st.session_state.get('map_refresh', 0)}",
    )
    if map_data:
        c = map_data.get("center")
        if c and "lat" in c and "lng" in c:
            st.session_state.map_center = [c["lat"], c["lng"]]
        if map_data.get("zoom") is not None:
            st.session_state.map_zoom = map_data["zoom"]


def mapview():

    vis = st.session_state.layer_visibility
    _op = float(st.session_state.get("overlay_opacity", 0.5))

    # --- View mode: single map vs multi-layer comparison grid ---
    view_mode = st.radio(
        "🗺️ Map view",
        ["Single map", "Compare layers (grid)"],
        horizontal=True,
        key="map_view_mode",
        help="Compare shows every ticked overlay layer in its own panel "
             "with synced or independent zoom and a full-screen option.",
    )
    if view_mode == "Compare layers (grid)":
        from ui.multimap import multimap_view
        multimap_view()
        return

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

    mode = st.session_state.get("mode", "Area (radius)")

    # --- Region modes draw their own geometry and skip the
    #     radius-based overlay machinery entirely. ---
    if mode in ("District", "State", "Multiple points"):
        _region_geometry(engine, mode)
        _render_map(engine)
        return

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
            # Keep the map light: simplify outlines (~30 m tolerance)
            # and cap how many polygons go into the page. A 100 km
            # radius can hit thousands of villages, which used to
            # build an enormous map and stall the free server.
            MAX_VILLAGES = 1200
            if len(gdf):
                gdf = gdf.copy()
                gdf["geometry"] = gdf.geometry.simplify(
                    0.0003, preserve_topology=True)
            if len(gdf) > MAX_VILLAGES:
                st.caption(
                    f"Showing {MAX_VILLAGES} of {len(gdf)} villages "
                    "on the map (all are counted in the Villages tab). "
                    "Reduce the radius to see every outline.")
                gdf = gdf.head(MAX_VILLAGES)
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
            url = fresh_tile_url(
                get_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Dynamic World", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load Dynamic World overlay: {e}")

    if vis.get("cropland_confidence"):

        from gee.worldcover import confidence_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                confidence_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Cropland Confidence", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load confidence layer: {e}")

    if vis.get("paddy"):

        from gee.paddy import paddy_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                paddy_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Paddy Fields", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load paddy layer: {e}")

    if vis.get("plantation"):

        from gee.plantation import plantation_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                plantation_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Plantations", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load plantation layer: {e}")

    if vis.get("banana"):

        from gee.plantation import banana_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                banana_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Banana", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load banana layer: {e}")

    if vis.get("worldcereal"):

        from gee.worldcereal import worldcereal_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                worldcereal_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
            )
            _overlay(engine, url, "WorldCereal Cropland", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load WorldCereal layer: {e}")

    if vis.get("maize"):

        from gee.maize import maize_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                maize_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Maize", _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load maize layer: {e}")

    if vis.get("aquaculture"):

        from gee.aquaculture import aquaculture_tile_url

        try:
            from core import usage as _u
            _u.bump("earth_engine")
            url = fresh_tile_url(
                aquaculture_tile_url,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year
            )
            _overlay(engine, url, "Aquaculture ponds", _op)
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
                url = fresh_tile_url(
                    soil_tile_url,
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    soil_layer
                )
                _overlay(engine, url, soil_layer, _op)
            except Exception as e:
                from core import usage as _u
                _u.note_error("earth_engine", e)
                st.warning(_u.friendly(e) or f"Could not load {soil_layer}: {e}")

    if vis.get("shc"):

        from gis import shc_layer

        try:
            metric = st.session_state.get("shc_map_metric", "n_low")
            label = shc_layer.METRICS.get(
                metric, shc_layer.METRICS["n_low"])[0]
            _shc_args = (
                metric,
                round(float(st.session_state.lat), 4),
                round(float(st.session_state.lon), 4),
                float(st.session_state.get("radius", 10)),
            )
            res_mode = st.session_state.get(
                "shc_map_res", "District average")

            gj = None
            if str(res_mode).startswith("Village"):
                with st.spinner(
                        "Fetching village-level SHC lab results..."):
                    gj = shc_layer.geojson_villages(*_shc_args)
                if gj is None:
                    st.caption(
                        "No village-level SHC data here - showing "
                        "the district average instead.")
            if gj is None:
                gj = shc_layer.geojson_for(*_shc_args)

            if gj:
                engine.add_choropleth(
                    gj, label,
                    fill_opacity=min(0.8, _op + 0.1))
            else:
                st.caption(
                    "No SHC district data inside the selected area "
                    "(coverage: Karnataka & Tamil Nadu).")
        except Exception as e:
            st.warning(f"Could not load SHC district layer: {e}")

    # --- Irrigation: four satellite views + the measured district
    #     source split. Kept as separate layers so you can see where
    #     independent methods agree. ---
    _IRR_TILES = (
        ("irrigation_summer", "gee.irrigation",
         "summer_green_tile_url",
         "Irrigated cropland (summer green)"),
        ("irrigation_multicrop", "gee.irrigation",
         "multicrop_tile_url", "Multi-crop land (2+ crops/yr)"),
        ("irrigation_lgrip", "gee.irrigation", "lgrip_tile_url",
         "LGRIP30 irrigated vs rain-fed"),
        ("irrigation_worldcereal", "gee.irrigation",
         "worldcereal_irrigation_tile_url",
         "WorldCereal irrigation (lower bound)"),
    )
    for _lid, _mod, _fn, _label in _IRR_TILES:
        if not vis.get(_lid):
            continue
        try:
            import importlib
            from core import usage as _u
            _u.bump("earth_engine")
            _f = getattr(importlib.import_module(_mod), _fn)
            url = fresh_tile_url(
                _f,
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year,
            )
            _overlay(engine, url, _label, _op)
        except Exception as e:
            from core import usage as _u
            _u.note_error("earth_engine", e)
            st.warning(_u.friendly(e) or f"Could not load {_label}: {e}")

    if vis.get("irrigation_source"):

        from gis import irrigation_layer

        try:
            metric = st.session_state.get(
                "irrigation_metric", "borewell_pct")
            label = irrigation_layer.METRICS.get(
                metric, irrigation_layer.METRICS["borewell_pct"])[0]
            gj = irrigation_layer.geojson_for(
                metric,
                round(float(st.session_state.lat), 4),
                round(float(st.session_state.lon), 4),
                float(st.session_state.get("radius", 10)),
            )
            if gj:
                engine.add_choropleth(
                    gj, f"Irrigation source - {label}",
                    fill_opacity=min(0.8, _op + 0.1))
            else:
                st.caption(
                    "No irrigation-source statistics for this area - "
                    "the district table covers Karnataka only.")
        except Exception as e:
            st.warning(f"Could not load the irrigation layer: {e}")

    if vis.get("coconut_survey"):

        from gis import crop_survey_layer

        try:
            metric = st.session_state.get(
                "coconut_survey_metric", "intensity")
            label = crop_survey_layer.METRICS.get(
                metric, crop_survey_layer.METRICS["intensity"])[0]
            gj = crop_survey_layer.geojson_villages(
                metric,
                round(float(st.session_state.lat), 4),
                round(float(st.session_state.lon), 4),
                float(st.session_state.get("radius", 10)),
            )
            if gj:
                engine.add_choropleth(
                    gj, f"Coconut survey - {label}",
                    fill_opacity=min(0.8, _op + 0.1))
            else:
                st.caption(
                    "No coconut crop-survey records inside this area "
                    "(survey covers Hassan, Mandya, Tumakuru, "
                    "Ramanagara, Chitradurga and Mysuru).")
        except Exception as e:
            st.warning(f"Could not load the coconut survey layer: {e}")

    # --- Refresh button: remounts the map so any tiles that failed
    # to load (Earth Engine timeouts at high zoom) are re-requested,
    # without having to nudge the opacity slider. ---
    rc1, rc2 = st.columns([1, 4])
    with rc1:
        if st.button("🔄 Refresh map", use_container_width=True,
                     help="Rebuild every overlay with a fresh Earth "
                          "Engine token and reload the tiles"):
            # Force brand-new tile URLs, not just a map remount: a
            # stale token is exactly what makes layers look absent.
            for _mod, _fns in (
                    ("gee.dynamic_world", ["get_tile_url"]),
                    ("gee.worldcover", ["confidence_tile_url"]),
                    ("gee.paddy", ["paddy_tile_url"]),
                    ("gee.plantation", ["plantation_tile_url",
                                        "banana_tile_url"]),
                    ("gee.maize", ["maize_tile_url"]),
                    ("gee.worldcereal", ["worldcereal_tile_url"]),
                    ("gee.aquaculture", ["aquaculture_tile_url"]),
                    ("gee.soil", ["soil_tile_url"])):
                try:
                    import importlib
                    m = importlib.import_module(_mod)
                    for _fn in _fns:
                        getattr(m, _fn).clear()
                except Exception:
                    continue
            st.session_state.tile_health = {
                "checked": 0, "renewed": 0, "failed": 0}
            st.session_state.map_refresh = \
                st.session_state.get("map_refresh", 0) + 1
    with rc2:
        st.caption(
            "If an overlay looks missing, click Refresh map - it "
            "rebuilds each layer with a fresh Earth Engine token. "
            "Layer health is shown in the sidebar's Service health "
            "panel.")

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

    # Measured coconut records for this area (government crop survey)
    # - renders only where the survey has coverage.
    try:
        from ui.crop_survey_panel import coconut_survey_panel
        coconut_survey_panel()
    except Exception:
        pass

    # Irrigation briefing - district source split, targeting advice and
    # the satellite cross-check. Renders only where the statistics
    # cover the area (Karnataka).
    try:
        from ui.irrigation_panel import irrigation_panel
        irrigation_panel()
    except Exception:
        pass
