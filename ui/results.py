"""Results dashboard - tabbed: Summary / Villages / Charts / Downloads."""

import streamlit as st
import pandas as pd
import plotly.express as px

from gis.village_search import get_villages
from core.export import excel_report
from core.crop_cycle import to_dataframe, analyze_series
from gee.worldcover import cropland_crosscheck


def _landcover_df():
    if st.session_state.results is None:
        return None
    return pd.DataFrame(st.session_state.results)


def _villages_df():
    try:
        return get_villages(
            st.session_state.lat,
            st.session_state.lon,
            st.session_state.radius
        )
    except Exception as e:
        st.warning(f"Could not load villages: {e}")
        return None


def _summary_tab(df):

    if df is None:
        st.info("Run an analysis to view the summary.")
        return

    total_area = df["Area (acres)"].sum()
    agriculture = df.loc[df["Land Cover"] == "Agriculture", "Area (acres)"].sum()
    trees = df.loc[df["Land Cover"] == "Trees", "Area (acres)"].sum()
    built = df.loc[df["Land Cover"] == "Built-up", "Area (acres)"].sum()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Total Area", f"{total_area:,.2f} ac")
    c2.metric("Agriculture", f"{agriculture:,.2f} ac")
    c3.metric("Trees", f"{trees:,.2f} ac")
    c4.metric("Built-up", f"{built:,.2f} ac")

    st.divider()

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )


def _confidence_check():

    with st.expander("🔍 Cropland Confidence Check", expanded=False):

        st.caption(
            "Compares cropland between two independent datasets: "
            "Google Dynamic World (your selected year) and ESA "
            "WorldCover (2021 baseline). High agreement means the "
            "cropland estimate is trustworthy. Also enable the "
            "'Cropland Confidence' map layer to see where they "
            "agree (green) and disagree (yellow)."
        )

        if st.button("Run Cross-Check", use_container_width=True):

            try:
                st.session_state.crosscheck = cropland_crosscheck(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    st.session_state.year,
                )
            except Exception as e:
                st.error(f"Cross-check failed: {e}")
                return

        r = st.session_state.get("crosscheck")

        if r is None:
            return

        c1, c2, c3, c4 = st.columns(4)

        c1.metric("Agreement", f"{r['agreement_pct']}%")
        c2.metric("Confirmed Cropland", f"{r['confirmed_ac']:,.0f} ac")
        c3.metric("Only Dynamic World", f"{r['dw_only_ac']:,.0f} ac")
        c4.metric("Only WorldCover", f"{r['wc_only_ac']:,.0f} ac")

        low = r["confirmed_ac"]
        high = r["confirmed_ac"] + r["dw_only_ac"] + r["wc_only_ac"]

        st.markdown(
            f"**Realistic cropland range: "
            f"{low:,.0f} - {high:,.0f} acres.** "
            f"The true figure is almost certainly inside this band: "
            f"the low end is confirmed by both datasets, the high end "
            f"counts everything either dataset calls cropland."
        )

        pct = r["agreement_pct"]

        if pct >= 70:
            st.success(
                "High agreement - the cropland estimate for this area "
                "is reliable."
            )
        elif pct >= 45:
            st.warning(
                "Moderate agreement - treat exact acreage with caution; "
                "check the yellow zones on the map against the "
                "satellite basemap."
            )
        else:
            st.error(
                "Low agreement - the datasets disagree here (common in "
                "plantation/orchard belts and mixed scrub). Verify "
                "visually and with ground knowledge before trusting "
                "the numbers."
            )


def _village_insights_section():

    st.divider()

    st.caption(
        "Per-village crop intelligence: cropland acres, cropping "
        "pattern and cycles/year for every village in the buffer. "
        "Slow (1-3 min) - best with radius <= 25 km."
    )

    if st.button("🧠 Compute Village Insights", use_container_width=True):

        from gee.village_stats import village_insights

        try:
            st.session_state.village_insights = village_insights(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year,
            )
        except Exception as e:
            st.error(f"Village insights failed: {e}")
            return

    vi = st.session_state.get("village_insights")

    if vi is None:
        return

    if vi.empty:
        st.info("No villages found.")
        return

    c1, c2, c3 = st.columns(3)

    double = (vi["Pattern"] == "Double / Multiple Cropping").sum()
    plantation = (vi["Pattern"] == "Perennial / Plantation").sum()

    c1.metric("Villages Analyzed", len(vi))
    c2.metric("Double-Crop Villages", int(double))
    c3.metric("Plantation Villages", int(plantation))

    st.dataframe(
        vi,
        use_container_width=True,
        hide_index=True,
        height=400
    )

    st.download_button(
        "📥 Village Insights (CSV)",
        vi.to_csv(index=False).encode("utf-8"),
        file_name="Village_Crop_Insights.csv",
        mime="text/csv",
        use_container_width=True
    )


def _stability_check():

    with st.expander("📅 3-Year Stability Check", expanded=False):

        st.caption(
            "Real cropland stays consistent year over year. If the "
            "acreage swings wildly between years, the classification "
            "is unreliable in this landscape - consistency is "
            "evidence of correctness, no ground data needed."
        )

        if st.button("Check Stability", use_container_width=True):

            from gee.stability import cropland_stability

            try:
                st.session_state.stability = cropland_stability(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    st.session_state.year,
                )
            except Exception as e:
                st.error(f"Stability check failed: {e}")
                return

        r = st.session_state.get("stability")

        if r is None:
            return

        cols = st.columns(len(r["by_year"]) + 1)

        cols[0].metric("Verdict", r["verdict"])

        for i, (y, ac) in enumerate(sorted(r["by_year"].items())):
            cols[i + 1].metric(str(y), f"{ac:,.0f} ac")

        st.write(f"Year-to-year spread: **{r['spread_pct']}%**")

        st.info(r["detail"])


def _villages_tab():

    df = _villages_df()

    if df is None:
        return

    if df.empty:
        st.info("No villages found in the current buffer.")
        return

    c1, c2, c3 = st.columns(3)

    c1.metric("Villages", len(df))

    if "Taluk" in df.columns:
        c2.metric("Taluks", df["Taluk"].nunique())

    if "District" in df.columns:
        c3.metric("Districts", df["District"].nunique())

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=350
    )


def _charts_tab(df):

    if df is None:
        st.info("Run an analysis to view charts.")
        return

    left, right = st.columns(2)

    with left:
        fig = px.pie(
            df,
            values="Area (acres)",
            names="Land Cover",
            title="Land Cover Distribution"
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        fig2 = px.bar(
            df,
            x="Land Cover",
            y="Area (acres)",
            title="Area by Land Cover"
        )
        st.plotly_chart(fig2, use_container_width=True)


def _area_report_bytes(df, villages):
    """Assemble the PDF from whatever analyses have been run."""

    from core.report import build_area_report

    meta = {
        "lat": st.session_state.lat,
        "lon": st.session_state.lon,
        "radius": st.session_state.radius,
        "year": st.session_state.year,
        "place": st.session_state.search_location or "",
    }

    crop_insight = None
    if st.session_state.get("ndvi_series") is not None:
        ndvi_df = to_dataframe(st.session_state.ndvi_series)
        if not ndvi_df["NDVI"].isna().all():
            crop_insight = analyze_series(ndvi_df)

    rain = None
    if st.session_state.get("rainfall_series") is not None:
        from core.rain_insight import to_dataframe as rain_df
        from core.rain_insight import analyze_rainfall
        rain = analyze_rainfall(
            rain_df(st.session_state.rainfall_series))

    return build_area_report(
        meta,
        landcover_df=df,
        crosscheck=st.session_state.get("crosscheck"),
        crop_insight=crop_insight,
        paddy=st.session_state.get("paddy_stats"),
        rain=rain,
        villages_df=villages,
        insights_df=st.session_state.get("village_insights"),
    )


def _downloads_tab(df):

    villages = _villages_df()

    try:
        st.download_button(
            "📄 Area Report (PDF)",
            _area_report_bytes(df, villages),
            file_name="AgriRadius_Area_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )
        st.caption(
            "The report includes every analysis you have run in this "
            "session (land cover, confidence, crop cycle, paddy, "
            "rainfall, village insights). Run more analyses to enrich it."
        )
    except Exception as e:
        st.warning(f"Could not build PDF report: {e}")

    st.divider()

    if df is not None:
        st.download_button(
            "📥 Land Cover (CSV)",
            df.to_csv(index=False).encode("utf-8"),
            file_name="LandCover_Report.csv",
            mime="text/csv",
            use_container_width=True
        )

    if villages is not None and not villages.empty:
        st.download_button(
            "📥 Village List (CSV)",
            villages.to_csv(index=False).encode("utf-8"),
            file_name="Villages_In_Buffer.csv",
            mime="text/csv",
            use_container_width=True
        )

    if df is not None or (villages is not None and not villages.empty):
        st.download_button(
            "📥 Full Report (Excel)",
            excel_report(df, villages),
            file_name="AgriRadius_Report.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
            use_container_width=True
        )
    else:
        st.info("Run an analysis to enable downloads.")


def _paddy_check():

    with st.expander("🌾 Paddy Detection (radar)", expanded=False):

        st.caption(
            "Sentinel-1 radar sees flooded fields through clouds. "
            "Fields that flood then show strong canopy growth are "
            "classified as paddy. Also enable the 'Paddy Fields "
            "(radar)' map layer to see them in cyan."
        )

        if st.button("Detect Paddy", use_container_width=True):

            from gee.paddy import paddy_stats

            try:
                st.session_state.paddy_stats = paddy_stats(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    st.session_state.year,
                )
            except Exception as e:
                st.error(f"Paddy detection failed: {e}")
                return

        r = st.session_state.get("paddy_stats")

        if r is None:
            return

        c1, c2, c3 = st.columns(3)

        c1.metric("Paddy Area", f"{r['paddy_ac']:,.0f} ac")
        c2.metric("Total Cropland", f"{r['cropland_ac']:,.0f} ac")
        c3.metric("Paddy Share", f"{r['paddy_pct']}%")


def _crop_cycle_tab():

    st.caption(
        "Monthly NDVI over cropland only (Dynamic World crop mask), "
        "last 2 years ending with the selected year. Detects how many "
        "crop cycles farmland in this buffer supports."
    )

    if st.button("🌱 Run Crop Cycle Analysis", use_container_width=True):

        from gee.ndvi import ndvi_monthly_series

        try:
            series = ndvi_monthly_series(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year - 1,
                st.session_state.year,
            )
            st.session_state.ndvi_series = series
        except Exception as e:
            st.error(f"NDVI analysis failed: {e}")
            return

    if st.session_state.get("ndvi_series") is None:
        st.info("Run the analysis to see cropping cycles.")
        return

    df = to_dataframe(st.session_state.ndvi_series)

    if df["NDVI"].isna().all():
        st.warning("No usable NDVI data for this buffer/period.")
        return

    insight = analyze_series(df)

    c1, c2, c3 = st.columns(3)
    c1.metric("Cropping Pattern", insight["pattern"])
    c2.metric("Cycles / Year", insight["cycles_per_year"])
    c3.metric("Mean NDVI (cropland)", insight["mean_ndvi"])

    st.info(insight["detail"])

    if insight["peak_months"]:
        st.write(
            "**Growth peaks:** " + ", ".join(insight["peak_months"])
        )

    fig = px.line(
        df,
        x="Month",
        y=["NDVI", "Smoothed"],
        title="NDVI Time Series - Cropland in Buffer",
        markers=True,
    )
    fig.add_hline(y=0.4, line_dash="dot",
                  annotation_text="crop peak threshold")
    st.plotly_chart(fig, use_container_width=True)


def _rainfall_tab():

    st.caption(
        "10 years of monthly rainfall for this buffer (CHIRPS "
        "satellite-gauge dataset). Tells you whether this belt gets "
        "dependable rain or swings between good and bad years."
    )

    if st.button("🌧️ Analyze Rainfall", use_container_width=True):

        from gee.rainfall import rainfall_monthly

        try:
            st.session_state.rainfall_series = rainfall_monthly(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year,
            )
        except Exception as e:
            st.error(f"Rainfall analysis failed: {e}")
            return

    if st.session_state.get("rainfall_series") is None:
        st.info("Run the analysis to see rainfall history.")
        return

    from core.rain_insight import to_dataframe as rain_df
    from core.rain_insight import analyze_rainfall

    df = rain_df(st.session_state.rainfall_series)
    r = analyze_rainfall(df)

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Reliability", r["verdict"])
    c2.metric("Avg Annual", f"{r['mean_annual_mm']:,} mm")
    c3.metric("Variability (CV)", f"{r['cv_pct']}%")
    c4.metric("Monsoon Share", f"{r['monsoon_share_pct']}%")

    st.info(r["detail"])

    st.write(
        f"**Wettest year:** {r['wettest_year']} "
        f"({r['wettest_mm']:,} mm) | "
        f"**Driest year:** {r['driest_year']} "
        f"({r['driest_mm']:,} mm)"
    )

    annual_df = r["annual"].reset_index()
    annual_df.columns = ["Year", "Rainfall (mm)"]

    left, right = st.columns(2)

    with left:
        fig = px.bar(
            annual_df,
            x="Year",
            y="Rainfall (mm)",
            title="Annual Rainfall (10 years)",
        )
        fig.add_hline(y=r["mean_annual_mm"], line_dash="dot",
                      annotation_text="average")
        st.plotly_chart(fig, use_container_width=True)

    with right:
        recent = df.tail(36)
        fig2 = px.bar(
            recent,
            x="Month",
            y="Rainfall (mm)",
            title="Monthly Rainfall (last 3 years)",
        )
        st.plotly_chart(fig2, use_container_width=True)


def results():

    st.subheader("🌾 Analysis Results")

    df = _landcover_df()

    (tab_summary, tab_villages, tab_charts,
     tab_crop, tab_rain, tab_downloads) = st.tabs(
        ["📊 Summary", "🏘️ Villages", "📈 Charts",
         "🌱 Crop Cycle", "🌧️ Rainfall", "📥 Downloads"]
    )

    with tab_summary:
        _summary_tab(df)
        st.divider()
        _confidence_check()
        _stability_check()

    with tab_villages:
        _villages_tab()
        _village_insights_section()

    with tab_charts:
        _charts_tab(df)

    with tab_crop:
        _crop_cycle_tab()
        st.divider()
        _paddy_check()

    with tab_rain:
        _rainfall_tab()

    with tab_downloads:
        _downloads_tab(df)
