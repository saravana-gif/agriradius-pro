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


def _sourcing_score_section():

    st.divider()

    st.write("**🏆 Village Sourcing Score**")

    st.caption(
        "One 0-100 score per village combining cropland size, "
        "cropping intensity, soil quality, rainfall reliability and "
        "field verification. Run Village Insights first; soil and "
        "rainfall enrich the score if computed."
    )

    if st.session_state.get("village_insights") is None:
        st.info("Run Village Insights above to enable scoring.")
        return

    if st.button("🏆 Rank Villages", use_container_width=True,
                 type="primary"):

        from core.scoring import score_villages
        from core.ground_truth import load_records
        from core.rain_insight import to_dataframe as _rdf
        from core.rain_insight import analyze_rainfall

        rain_verdict = None

        if st.session_state.get("rainfall_series") is not None:
            try:
                rain_verdict = analyze_rainfall(
                    _rdf(st.session_state.rainfall_series)
                )["verdict"]
            except Exception:
                pass

        try:
            st.session_state.sourcing_scores = score_villages(
                st.session_state.village_insights,
                st.session_state.get("village_soil"),
                rain_verdict,
                load_records(),
            )
        except Exception as e:
            st.error(f"Scoring failed: {e}")
            return

    scores = st.session_state.get("sourcing_scores")

    if scores is None or scores.empty:
        return

    top = scores.iloc[0]

    c1, c2, c3 = st.columns(3)

    c1.metric("Top Village", top["Village"], f"{top['Score']} pts")
    c2.metric("Villages Ranked", len(scores))
    c3.metric("Avg Score", f"{scores['Score'].mean():.1f}")

    st.dataframe(scores, use_container_width=True, hide_index=True,
                 height=400)

    st.download_button(
        "📥 Sourcing Scores (CSV)",
        scores.to_csv(index=False).encode("utf-8"),
        file_name="Village_Sourcing_Scores.csv",
        mime="text/csv",
        use_container_width=True,
    )


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

    if st.button(
        "📄 Build Area Report",
        use_container_width=True,
        type="primary",
    ):
        try:
            pdf = _area_report_bytes(df, villages)
            st.session_state.report_pdf = pdf

            # Also save straight to disk - browser-proof
            from datetime import datetime
            from config import PROJECT_ROOT

            reports_dir = PROJECT_ROOT / "reports"
            reports_dir.mkdir(exist_ok=True)

            stamp = datetime.now().strftime("%Y%m%d_%H%M")
            path = reports_dir / f"AgriRadius_Report_{stamp}.pdf"
            path.write_bytes(pdf)

            st.session_state.report_path = str(path)

        except Exception as e:
            st.session_state.report_pdf = None
            st.error(f"Could not build PDF report: {e}")

    if st.session_state.get("report_pdf"):

        if st.session_state.get("report_path"):
            st.success(
                f"Report saved to: {st.session_state.report_path}"
            )

        st.download_button(
            "📥 Download Area Report (PDF)",
            st.session_state.report_pdf,
            file_name="AgriRadius_Area_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    st.caption(
        "The report includes every analysis you have run in this "
        "session (land cover, confidence, crop cycle, paddy, "
        "rainfall, village insights). Run more analyses, then "
        "rebuild to enrich it."
    )

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


def _plantation_check():

    with st.expander("🥥 Plantation Detection (coconut/arecanut)",
                     expanded=False):

        st.caption(
            "Separates plantations from natural forest inside the "
            "'Trees' class: flat land + still green in the dry "
            "season (irrigated palms) + small patches. Enable the "
            "'Plantations' map layer to see them in orange. "
            "Banana usually appears under cropland, not here."
        )

        run = st.button("Detect Plantations",
                        use_container_width=True)

        # Auto-run when the map layer is switched on
        layer_on = st.session_state.layer_visibility.get("plantation")

        if run or (layer_on
                   and st.session_state.plantation_stats is None):

            from gee.plantation import plantation_stats

            try:
                st.session_state.plantation_stats = plantation_stats(
                    st.session_state.lat,
                    st.session_state.lon,
                    st.session_state.radius,
                    st.session_state.year,
                )
            except Exception as e:
                st.error(f"Plantation detection failed: {e}")
                return

        r = st.session_state.get("plantation_stats")

        if r is None:
            return

        c1, c2, c3 = st.columns(3)

        c1.metric("Plantation Area", f"{r['plantation_ac']:,.0f} ac")
        c2.metric("Total Tree Cover", f"{r['trees_ac']:,.0f} ac")
        c3.metric("Plantation Share", f"{r['plantation_pct']}%")


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


def _forecast_tab():

    st.caption(
        "16-day forecast for the selected point (Open-Meteo). "
        "Use the dry window for harvest and pickup planning."
    )

    from core.weather import get_forecast, analyze_forecast

    try:
        days = get_forecast(
            st.session_state.lat, st.session_state.lon)
    except Exception as e:
        st.warning(f"Could not fetch forecast: {e}")
        return

    r = analyze_forecast(days)

    if not r:
        st.info("No forecast data available.")
        return

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Rain Next 7 Days", f"{r['rain_7d_mm']} mm")
    c2.metric("Rainy Days (7d)", r["rain_days_7d"])
    c3.metric(
        "Longest Dry Window",
        f"{r['dry_window_days']} days",
        help="Best stretch for harvest / transport",
    )
    c4.metric("Temp Range", f"{r['tmin']} - {r['tmax']} °C")

    if r["dry_window_days"] >= 3 and r["dry_window_start"]:
        st.success(
            f"Dry window of {r['dry_window_days']} days starting "
            f"{r['dry_window_start']} - good for harvest, drying "
            f"and transport."
        )
    elif r["rain_7d_mm"] > 50:
        st.warning(
            "Heavy rain expected this week - plan pickups around it."
        )

    fdf = pd.DataFrame(days)

    fig = px.bar(
        fdf,
        x="date",
        y="rain_mm",
        title="Daily Rainfall Forecast (mm)",
        labels={"date": "", "rain_mm": "mm"},
    )
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.line(
        fdf,
        x="date",
        y=["tmax", "tmin"],
        title="Temperature Forecast (°C)",
        labels={"date": "", "value": "°C"},
        markers=True,
    )
    st.plotly_chart(fig2, use_container_width=True)


def _soil_card_section(villages):

    from core.ground_truth import add_soil_card, load_soil_cards

    st.caption(
        "Enter lab-measured values from farmers' Soil Health Cards - "
        "the only real source of P and K. Leave unknown fields at 0."
    )

    with st.form("shc_form", clear_on_submit=True):

        c1, c2 = st.columns(2)

        with c1:
            if villages is not None and not villages.empty:
                village = st.selectbox(
                    "Village", villages["Village"].tolist(),
                    key="shc_village")
            else:
                village = st.text_input("Village", key="shc_village")

        with c2:
            farmer = st.text_input("Farmer name (optional)")

        c3, c4, c5 = st.columns(3)

        with c3:
            ph = st.number_input("pH", 0.0, 14.0, 0.0, step=0.1)
        with c4:
            ec = st.number_input("EC (dS/m)", 0.0, 20.0, 0.0,
                                 step=0.1)
        with c5:
            oc = st.number_input("Organic Carbon (%)", 0.0, 5.0,
                                 0.0, step=0.05)

        c6, c7, c8 = st.columns(3)

        with c6:
            n = st.number_input("N (kg/ha)", 0.0, 1000.0, 0.0,
                                step=5.0)
        with c7:
            p = st.number_input("P (kg/ha)", 0.0, 500.0, 0.0,
                                step=1.0)
        with c8:
            k = st.number_input("K (kg/ha)", 0.0, 1000.0, 0.0,
                                step=5.0)

        water_ft = st.number_input(
            "Borewell water level (ft, 0 if unknown)",
            0.0, 2000.0, 0.0, step=10.0,
            help="Depth at which water stands in nearby borewell - "
                 "our only source for groundwater data")

        micro = st.text_input(
            "Micronutrient notes (e.g. 'Zn low, Fe ok')")

        c9, c10 = st.columns(2)

        with c9:
            notes = st.text_input("Notes", key="shc_notes")
        with c10:
            observer = st.text_input("Observer", key="shc_observer")

        submitted = st.form_submit_button(
            "💾 Save Soil Card", use_container_width=True,
            type="primary")

    if submitted:

        if not village:
            st.error("Village is required.")
        else:
            taluk = district = ""

            if villages is not None and not villages.empty:
                row = villages[villages["Village"] == village]
                if not row.empty:
                    taluk = row.iloc[0].get("Taluk", "")
                    district = row.iloc[0].get("District", "")

            add_soil_card(village, taluk, district, farmer, ph, ec,
                          oc, n, p, k, water_ft, micro, notes,
                          observer)
            st.success(f"Soil card saved for {village}")

    cards = load_soil_cards()

    if cards.empty:
        st.info("No soil cards recorded yet.")
        return

    st.write(f"**{len(cards)} soil cards recorded**")

    st.dataframe(cards, use_container_width=True, hide_index=True,
                 height=250)

    st.download_button(
        "📥 Soil Cards (CSV)",
        cards.to_csv(index=False).encode("utf-8"),
        file_name="Soil_Health_Cards.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _ground_truth_tab():

    from core.ground_truth import (
        CROP_OPTIONS,
        add_record,
        load_records,
        compare_with_predictions,
    )

    st.caption(
        "Record what your field team actually sees in each village. "
        "Every observation scores the satellite predictions and "
        "builds OneRoot's own labeled dataset for calibration."
    )

    villages = _villages_df()

    sub_crop, sub_soil = st.tabs(
        ["🌾 Crop Observation", "🧾 Soil Health Card"])

    with sub_soil:
        _soil_card_section(villages)

    with sub_crop:
        _crop_observation_section(villages)


def _crop_observation_section(villages):

    from core.ground_truth import (
        CROP_OPTIONS,
        add_record,
        load_records,
        compare_with_predictions,
    )

    # --- Entry form ---
    with st.form("gt_form", clear_on_submit=True):

        c1, c2 = st.columns(2)

        with c1:
            if villages is not None and not villages.empty:
                village = st.selectbox(
                    "Village", villages["Village"].tolist())
            else:
                village = st.text_input("Village")

        with c2:
            observer = st.text_input("Observer (your name)")

        crops = st.multiselect("Main crops observed", CROP_OPTIONS)

        c3, c4 = st.columns(2)

        with c3:
            cycles = st.selectbox("Crop cycles per year", [1, 2, 3])

        with c4:
            irrigated = st.toggle("Irrigated")

        notes = st.text_input("Notes (optional)")

        submitted = st.form_submit_button(
            "💾 Save Observation", use_container_width=True,
            type="primary")

    if submitted:

        if not village or not crops:
            st.error("Village and at least one crop are required.")
        else:
            taluk = district = ""

            if villages is not None and not villages.empty:
                row = villages[villages["Village"] == village]
                if not row.empty:
                    taluk = row.iloc[0].get("Taluk", "")
                    district = row.iloc[0].get("District", "")

            add_record(village, taluk, district, crops, cycles,
                       irrigated, notes, observer)
            st.success(f"Saved: {village} - {', '.join(crops)}")

    # --- Records + accuracy ---
    gt = load_records()

    if gt.empty:
        st.info("No observations recorded yet.")
        return

    st.divider()

    st.write(f"**{len(gt)} observations recorded**")

    st.dataframe(gt, use_container_width=True, hide_index=True,
                 height=250)

    st.download_button(
        "📥 Ground Truth (CSV)",
        gt.to_csv(index=False).encode("utf-8"),
        file_name="Ground_Truth.csv",
        mime="text/csv",
        use_container_width=True,
    )

    insights = st.session_state.get("village_insights")

    if insights is None or insights.empty:
        st.caption(
            "Run Village Insights (Villages tab) to score predictions "
            "against these observations."
        )
        return

    cmp, acc = compare_with_predictions(gt, insights)

    if acc is None:
        st.caption(
            "No overlap yet between observed villages and the current "
            "buffer's insights."
        )
        return

    st.divider()

    c1, c2, c3 = st.columns(3)

    c1.metric("Prediction Accuracy", f"{acc}%")
    c2.metric("Villages Scored", len(cmp))
    c3.metric("Matches", int(cmp["Match"].sum()))

    st.dataframe(cmp, use_container_width=True, hide_index=True)

    if acc < 60 and len(cmp) >= 10:
        st.warning(
            "Accuracy below 60% with a decent sample - time to "
            "recalibrate the detection thresholds for this region."
        )


def _soil_tab():

    st.caption(
        "Root-zone (0-30 cm) soil profile from SoilGrids (ISRIC) - "
        "modeled 250m estimates built from lab-tested soil samples "
        "worldwide. Indicative for area planning, not a substitute "
        "for lab tests. Phosphorus and potassium cannot be measured "
        "from satellite - collect Soil Health Cards for those."
    )

    if st.button("🧪 Read Soil Profile", use_container_width=True):

        from gee.soil import soil_profile

        try:
            st.session_state.soil = soil_profile(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
            )
        except Exception as e:
            st.error(f"Soil profile failed: {e}")
            return

    profile = st.session_state.get("soil")

    if profile is None:
        st.info("Read the soil profile to see pH, organic carbon, "
                "nitrogen and texture.")
        return

    from gee.soil import interpret

    verdicts = interpret(profile)

    if not verdicts:
        st.warning("No soil data available for this area.")
        return

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("pH", profile.get("phh2o", "-"))
    c2.metric("Organic Carbon", f"{profile.get('soc', '-')} g/kg")
    c3.metric("Total Nitrogen", f"{profile.get('nitrogen', '-')} g/kg")

    from gee.soil import texture_class
    c4.metric("Texture", texture_class(
        profile.get("sand"), profile.get("clay")))

    st.divider()

    for label, verdict in verdicts.items():
        st.write(f"**{label}:** {verdict}")

    st.divider()

    st.write("**Per-Village Soil Profile**")

    st.caption(
        "Soil values averaged over each village polygon (250m "
        "SoilGrids). Also tick the painted soil layers in the "
        "Layers panel to see pH and organic carbon on the map."
    )

    if st.button("🏘️ Compute Per-Village Soil",
                 use_container_width=True):

        from gee.soil import village_soil

        try:
            st.session_state.village_soil = village_soil(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
            )
        except Exception as e:
            st.error(f"Per-village soil failed: {e}")

    vsoil = st.session_state.get("village_soil")

    if vsoil is not None and not vsoil.empty:

        # Join measured values from soil health cards when available
        from core.ground_truth import village_card_averages

        cards = village_card_averages()

        if not cards.empty:
            vsoil = vsoil.merge(cards, on="Village", how="left")
            st.caption(
                "'Card ...' columns are field-measured values from "
                "Soil Health Cards (averaged per village) - the only "
                "real source of P, K and water level."
            )

        st.dataframe(vsoil, use_container_width=True,
                     hide_index=True, height=350)

        st.download_button(
            "📥 Village Soil (CSV)",
            vsoil.to_csv(index=False).encode("utf-8"),
            file_name="Village_Soil_Profile.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.divider()

    st.write("**🌡️ Soil Temperature & Moisture**")

    st.caption(
        "Monthly soil temperature (0-7 cm) and moisture from "
        "ERA5-Land (~11 km grid - area-level, not per-village). "
        "Groundwater depth has no satellite source: log borewell "
        "levels in the Soil Health Card form instead."
    )

    if st.button("Read Soil Temperature & Moisture",
                 use_container_width=True):

        from gee.climate import soil_climate

        try:
            st.session_state.soil_climate = soil_climate(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year,
            )
        except Exception as e:
            st.error(f"Soil climate failed: {e}")

    sc = st.session_state.get("soil_climate")

    if sc:

        from gee.climate import summarize

        summ = summarize(sc)

        if summ:

            c1, c2, c3, c4 = st.columns(4)

            c1.metric("Mean Soil Temp", f"{summ['mean_temp']} °C")
            c2.metric("Hottest Month", f"{summ['max_temp']} °C")
            c3.metric("Coolest Month", f"{summ['min_temp']} °C")

            if summ["mean_moisture"] is not None:
                c4.metric("Mean Soil Moisture",
                          f"{summ['mean_moisture']}%")

            scdf = pd.DataFrame(sc)

            fig = px.line(
                scdf,
                x="Month",
                y=["Soil Temp (°C)", "Soil Moisture (%)"],
                title="Monthly Soil Temperature & Moisture",
                markers=True,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No soil climate data for this period.")


def _mandi_tab():

    from core.mandi import COMMODITIES, STATES, get_prices

    st.caption(
        "Live daily wholesale prices from APMC mandis (AGMARKNET / "
        "data.gov.in). Prices are Rs per quintal; refreshed every "
        "30 minutes."
    )

    # Default state guessed from the buffer's villages
    default_state = "Karnataka"

    villages = _villages_df()

    if villages is not None and not villages.empty             and "State" in villages.columns:
        top = villages["State"].mode()
        if len(top):
            guess = str(top.iloc[0]).title()
            if guess in STATES:
                default_state = guess

    c1, c2 = st.columns(2)

    with c1:
        commodity_label = st.selectbox(
            "Commodity", list(COMMODITIES.keys()))

    with c2:
        state = st.selectbox(
            "State", STATES, index=STATES.index(default_state))

    try:
        df = get_prices(COMMODITIES[commodity_label], state)
    except Exception as e:
        st.error(f"Could not fetch prices: {e}")
        return

    if df.empty:
        st.info(
            f"No {commodity_label} prices reported "
            f"{'in ' + state if state != 'All India' else 'today'} - "
            "markets may not have traded it today. Try All India."
        )
        return

    modal = df["Modal (Rs/qtl)"].dropna()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Markets Reporting", len(df))
    c2.metric("Best Modal Price", f"₹{modal.max():,.0f}/qtl")
    c3.metric("Average Modal", f"₹{modal.mean():,.0f}/qtl")
    c4.metric("Lowest Modal", f"₹{modal.min():,.0f}/qtl")

    best = df.iloc[0]

    st.success(
        f"Best price: **₹{best['Modal (Rs/qtl)']:,.0f}/qtl** at "
        f"**{best['Market']}** ({best['District']}, {best['State']}) "
        f"on {best['Date']}"
    )

    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=400)

    st.download_button(
        "📥 Mandi Prices (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"Mandi_{commodity_label.replace(' ', '_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )


def results():

    st.subheader("🌾 Analysis Results")

    df = _landcover_df()

    (tab_summary, tab_villages, tab_charts, tab_crop,
     tab_rain, tab_forecast, tab_soil, tab_mandi, tab_gt,
     tab_downloads) = st.tabs(
        ["📊 Summary", "🏘️ Villages", "📈 Charts",
         "🌱 Crop Cycle", "🌧️ Rainfall", "⛅ Forecast",
         "🧪 Soil", "💰 Mandi", "✅ Ground Truth", "📥 Downloads"]
    )

    with tab_summary:
        _summary_tab(df)
        st.divider()
        _confidence_check()
        _stability_check()

    with tab_villages:
        _villages_tab()
        _village_insights_section()
        _sourcing_score_section()

    with tab_charts:
        _charts_tab(df)

    with tab_crop:
        _crop_cycle_tab()
        st.divider()
        _paddy_check()
        _plantation_check()

    with tab_rain:
        _rainfall_tab()

    with tab_forecast:
        _forecast_tab()

    with tab_soil:
        _soil_tab()

    with tab_mandi:
        _mandi_tab()

    with tab_gt:
        _ground_truth_tab()

    with tab_downloads:
        _downloads_tab(df)
