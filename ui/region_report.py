"""District / State / Multi-point report panels.

Rendered by the dashboard when the sidebar Analysis Mode is District,
State or Multiple points. Rankings are measured-data driven (SHC lab
samples + bundled census); the satellite crop-cycle summary is an
explicit on-demand button (cost-capped, district mode only).
"""

import pandas as pd
import streamlit as st

from core import region_report
from gis import admin_areas


def _score_table(rows, cols, height=None):
    if not rows:
        st.info("No ranked rows yet - see the coverage note above.")
        return
    df = pd.DataFrame(rows)
    df.insert(0, "rank", range(1, len(df) + 1))
    df = df[["rank"] + cols]
    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=height)


def district_report():
    region = st.session_state.get("region") or {}
    skey, dist = region.get("state"), region.get("district")
    if not (skey and dist):
        st.info("Pick a state and district in the sidebar, then press "
                "**Open district report**.")
        return

    slabel = admin_areas.STATE_LABELS.get(skey, skey.title())
    st.subheader(f"🗺️ District report - {dist.title()} ({slabel})")

    # --- progressive village fetch (budgeted, cached forever) ---
    with st.spinner("Updating village lab data (cached after "
                    "first use)..."):
        try:
            from core import shc_api
            done, total = shc_api.fetch_district_villages(
                slabel, dist, budget_s=20, max_fetch=120)
        except Exception:
            done, total = 0, 0
    if total:
        st.caption(
            f"Soil Health Card lab data loaded for **{done} of "
            f"{total}** portal-listed villages. Re-open the report "
            "to load more; everything fetched stays cached.")

    st.markdown("#### 🏅 Village rankings (soil health score)")
    st.caption(
        "Score = weighted adequacy of N/P/K/OC (double weight), "
        "micronutrients, and pH neutrality from measured lab "
        "samples. Reasons show what drives each score. Small sample "
        "counts - treat as indicative.")
    rows = region_report.village_rankings(slabel, [dist], top=0)
    _score_table(rows, ["village", "district", "score", "reasons",
                        "samples", "cycle"], height=420)

    st.markdown("#### 🧪 District soil summary (measured)")
    try:
        from core import shc_api
        res = shc_api.district_nutrients(slabel, dist)
    except Exception:
        res = None
    if res:
        score, reasons, tot = region_report.soil_score(res)
        c1, c2, c3 = st.columns(3)
        c1.metric("District soil score", f"{score}/100")
        c2.metric("Lab samples", f"{tot:,}")
        c3.metric("Cycle", res.get("_cycle", "-"))
        st.caption("Drivers: " + "; ".join(reasons))
    else:
        st.caption("No district-level SHC data reachable right now.")

    st.markdown("#### 🐄 Economy context (bundled govt data)")
    try:
        from core.allied import load_livestock, _match_row
        df = load_livestock()
        row = _match_row(df, slabel, dist) if not df.empty else None
        if row is not None:
            vals = {c: row[c] for c in df.columns
                    if c not in ("state", "district", "_key", "_state")}
            show = {k.title(): f"{int(float(v)):,}" for k, v in
                    vals.items()
                    if str(v) not in ("nan", "None", "")}
            st.dataframe(pd.DataFrame([show]).T.rename(
                columns={0: "Head (2019 census)"}),
                use_container_width=True)
        else:
            st.caption("No livestock census row matched this district.")
    except Exception:
        st.caption("Livestock data unavailable.")

    st.markdown("#### 🛰️ Satellite crop-cycle summary (on demand)")
    st.caption(
        "Runs the app's cost-capped Earth Engine analysis over a "
        "circle approximating the district extent. Uses the shared "
        "compute budget - run it only when needed.")
    if st.button("Run satellite summary for this district"):
        gdf = admin_areas.district_villages(skey, dist)
        if gdf is None or gdf.empty:
            st.warning("District geometry unavailable.")
        else:
            import math
            b = gdf.total_bounds
            lat = (b[1] + b[3]) / 2
            lon = (b[0] + b[2]) / 2
            radius = min(100, max(10, int(
                max((b[2] - b[0]) * 111 * math.cos(math.radians(lat)),
                    (b[3] - b[1]) * 110) / 2)))
            from gee.analysis import analyze_landcover
            with st.spinner(
                    f"Analyzing ~{radius} km around the district "
                    "centre..."):
                st.session_state.results = analyze_landcover(
                    lat, lon, radius, st.session_state.year)
            st.session_state.lat = lat
            st.session_state.lon = lon
            st.session_state.radius = radius
            st.success(
                "Done - the Analysis Results tabs below now show the "
                "district-extent summary (approximated as a circle).")


def state_report():
    region = st.session_state.get("region") or {}
    skey = region.get("state")
    if not skey:
        st.info("Pick a state in the sidebar, then press "
                "**Open state report**.")
        return

    slabel = admin_areas.STATE_LABELS.get(skey, skey.title())
    st.subheader(f"🏛️ State report - {slabel}")

    with st.spinner("Loading district list..."):
        districts = admin_areas.list_districts(skey)
    if not districts:
        st.warning("No district boundaries available for this state "
                   "yet.")
        return

    st.markdown("#### 🏅 District rankings")
    st.caption(
        "Composite = 60% measured soil health (SHC lab samples, "
        "multi-cycle) + 40% livestock-economy percentile (2019 "
        "census). Reasons are shown per district. Satellite "
        "summaries stay on-demand in each district's report to "
        "protect the shared compute budget.")
    with st.spinner("Scoring districts (first run fetches one portal "
                    "record per district; cached after)..."):
        rows = region_report.district_rankings(slabel, districts)
    _score_table(rows, ["district", "score", "soil_score",
                        "economy_pct", "reasons", "samples", "cycle"],
                 height=560)

    st.markdown("#### 🏘️ Top villages state-wide (from cached lab data)")
    st.caption(
        "Villages appear here once their lab data has been fetched - "
        "coverage grows every time the SHC map layer or a district "
        "report is used. Each village shows its district and the "
        "reasons for its score.")
    vrows = region_report.village_rankings(slabel, districts, top=40)
    _score_table(vrows, ["village", "district", "score", "reasons",
                         "samples", "cycle"], height=420)
    if not vrows:
        st.caption(
            "Tip: open a district report (sidebar → District) to pull "
            "its villages' lab data - they then appear in this "
            "state-wide ranking.")


def multipoint_report():
    st.subheader("📍 Multiple points - comparison")
    pts = st.session_state.get("multi_points") or []
    if not pts:
        st.info("Add points in the sidebar (one 'lat, lon' per line) "
                "and press **Compare points**.")
        return

    rows = []
    with st.spinner(f"Looking up {len(pts)} points (village, district "
                    "& lab soil data)..."):
        for lat, lon in pts[:12]:
            try:
                rows.append(region_report.point_summary(lat, lon))
            except Exception:
                rows.append({"lat": lat, "lon": lon,
                             "village": "lookup failed"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True,
                 hide_index=True)
    st.caption(
        "Soil score/notes come from measured SHC lab samples of each "
        "point's village (multi-cycle). For satellite detail on any "
        "point, switch to Point or Area mode at that location.")
