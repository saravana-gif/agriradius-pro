import streamlit as st

from config import AVAILABLE_YEARS
from core.geocoder import search_place
from gee.analysis import analyze_landcover

MODES = ["Area (radius)", "Point location", "Multiple points",
         "District", "State"]


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

    if st.button("✨ Try a sample area (Pollachi)",
                 use_container_width=True,
                 help="Loads a demo coconut belt so you can explore "
                      "the app instantly — then hit a layer or Run."):
        st.session_state.lat = 10.6588
        st.session_state.lon = 77.0089
        st.session_state.search_location = "Pollachi (sample)"
        st.rerun()

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

    # --- Analysis mode ---
    cur = st.session_state.get("mode", MODES[0])
    st.session_state.mode = st.radio(
        "Analysis Mode",
        MODES,
        index=MODES.index(cur) if cur in MODES else 0,
        help="Area = circle around a point. Point = one exact "
             "coordinate. Multiple points = side-by-side comparison. "
             "District / State = whole-region reports with rankings.",
    )
    mode = st.session_state.mode

    if mode in ("Area (radius)", "Point location"):
        _point_inputs(mode)
    elif mode == "Multiple points":
        _multi_point_inputs()
    elif mode == "District":
        _district_inputs()
    elif mode == "State":
        _state_inputs()

    st.session_state.year = st.selectbox(
        "Year",
        AVAILABLE_YEARS,
        index=(AVAILABLE_YEARS.index(st.session_state.year)
               if st.session_state.year in AVAILABLE_YEARS else 0),
    )

    import datetime as _dt
    if st.session_state.year >= _dt.date.today().year:
        st.caption(
            "🛰️ Current year uses a **rolling 12-month** satellite "
            "window so the crop detectors still work mid-season. If a "
            "layer ever looks unusually sparse, a completed past year "
            "is the safest reference.")

    if mode in ("Area (radius)", "Point location"):
        st.divider()
        st.write("### Current Location")
        st.write(f"Latitude : {st.session_state.lat:.6f}")
        st.write(f"Longitude : {st.session_state.lon:.6f}")

    st.divider()

    if mode == "Area (radius)":

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

    elif mode == "Point location":
        st.caption(
            "Point mode: open the '📍 Point Details' section below "
            "the map to get everything for this exact coordinate."
        )
        from core.session_store import save_last
        save_last(st.session_state)


def _point_inputs(mode):
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
    if mode == "Area (radius)":

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


def _multi_point_inputs():
    st.caption(
        "One point per line as 'lat, lon'. Up to 12 points are "
        "compared side by side (village, district & measured soil).")
    txt = st.text_area(
        "Points",
        value=st.session_state.get("multi_points_text", ""),
        placeholder="16.1693, 74.8224\n10.6588, 77.0089",
        height=120,
        key="multi_points_text",
    )
    if st.button("⚖️ Compare points", use_container_width=True,
                 type="primary"):
        pts = []
        for line in str(txt).replace(";", "\n").splitlines():
            bits = line.replace("\t", ",").split(",")
            if len(bits) < 2:
                continue
            try:
                lat, lon = float(bits[0]), float(bits[1])
            except ValueError:
                continue
            if 5 <= lat <= 25 and 68 <= lon <= 90:
                pts.append((lat, lon))
        if pts:
            st.session_state.multi_points = pts[:12]
            st.success(f"{len(pts[:12])} points ready - see the "
                       "comparison below the map.")
        else:
            st.error("No valid 'lat, lon' lines found.")


def _district_inputs():
    from gis import admin_areas
    states = admin_areas.available_states()
    if not states:
        st.warning("No village boundary files found.")
        return
    keys = [k for k, _ in states]
    labels = {k: l for k, l in states}
    cur = st.session_state.get("region_state", keys[0])
    skey = st.selectbox(
        "State", keys,
        index=keys.index(cur) if cur in keys else 0,
        format_func=lambda k: labels[k],
        key="region_state",
    )

    with st.spinner("Loading district list (first time per state "
                    "builds an index - can take a minute)..."):
        districts = admin_areas.list_districts(skey)
    if not districts:
        st.warning("Could not read districts for this state.")
        return

    dist = st.selectbox(
        "District (type to search)", districts,
        key=f"region_district_{skey}",
    )

    if st.button("📊 Open district report", use_container_width=True,
                 type="primary"):
        st.session_state.region = {
            "kind": "district", "state": skey, "district": dist}
        idx = admin_areas.district_index(skey).get(dist)
        if idx:
            st.session_state.lat = (idx[1] + idx[3]) / 2
            st.session_state.lon = (idx[0] + idx[2]) / 2
        st.rerun()


def _state_inputs():
    from gis import admin_areas
    states = admin_areas.available_states()
    if not states:
        st.warning("No village boundary files found.")
        return
    keys = [k for k, _ in states]
    labels = {k: l for k, l in states}
    cur = st.session_state.get("region_state", keys[0])
    skey = st.selectbox(
        "State", keys,
        index=keys.index(cur) if cur in keys else 0,
        format_func=lambda k: labels[k],
        key="region_state",
    )
    if st.button("🏛️ Open state report", use_container_width=True,
                 type="primary"):
        st.session_state.region = {"kind": "state", "state": skey}
        st.rerun()
