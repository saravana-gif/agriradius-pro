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


def _build_full_report(kind):
    """Run every analysis, then build a PDF or Excel and save to disk.

    kind is 'pdf' or 'excel'. Stores bytes + path in session state.
    """

    from datetime import datetime

    from config import APP_NAME, PROJECT_ROOT
    from core.full_report import excel_bytes, gather, pdf_bytes

    bar = st.progress(0, text="Starting full analysis...")

    def report_progress(pct, label):
        bar.progress(int(pct), text=label)

    bundle = gather(progress=report_progress)

    place = (bundle["meta"].get("place") or "area").replace(" ", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    if kind == "pdf":
        data = pdf_bytes(bundle)
        fname = f"AgriRadius_{place}_{stamp}.pdf"
    else:
        data = excel_bytes(bundle)
        fname = f"AgriRadius_{place}_{stamp}.xlsx"

    bar.progress(100, text="Done.")

    # Best-effort local save (skipped silently on read-only hosts
    # like Streamlit Cloud; the download button always works).
    saved_path = None
    try:
        reports_dir = PROJECT_ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        p = reports_dir / fname
        p.write_bytes(data)
        saved_path = str(p)
    except Exception:
        saved_path = None

    st.session_state[f"full_{kind}_bytes"] = data
    st.session_state[f"full_{kind}_path"] = saved_path
    st.session_state["full_notes"] = bundle.get("notes", [])


def _downloads_tab(df):

    st.caption(
        "One click runs every analysis for the current location and "
        "radius, then builds a complete report. The full suite can "
        "take 1-3 minutes (village insights is the slow part). Each "
        "report is also saved to your project's 'reports' folder."
    )

    c1, c2 = st.columns(2)

    with c1:
        if st.button("📄 Build Full PDF Report",
                     use_container_width=True, type="primary"):
            try:
                _build_full_report("pdf")
            except Exception as e:
                st.error(f"PDF build failed: {e}")

    with c2:
        if st.button("📊 Build Full Excel Report",
                     use_container_width=True, type="primary"):
            try:
                _build_full_report("excel")
            except Exception as e:
                st.error(f"Excel build failed: {e}")

    XLSX_MIME = ("application/vnd.openxmlformats-officedocument"
                 ".spreadsheetml.sheet")

    if st.session_state.get("full_pdf_bytes"):
        if st.session_state.get("full_pdf_path"):
            st.success(
                f"PDF saved to: {st.session_state['full_pdf_path']}")
        else:
            st.success("PDF report ready.")
        st.download_button(
            "📥 Download PDF Report",
            st.session_state["full_pdf_bytes"],
            file_name="AgriRadius_Full_Report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    if st.session_state.get("full_excel_bytes"):
        if st.session_state.get("full_excel_path"):
            st.success(
                f"Excel saved to: {st.session_state['full_excel_path']}")
        else:
            st.success("Excel report ready.")
        st.download_button(
            "📥 Download Excel Report",
            st.session_state["full_excel_bytes"],
            file_name="AgriRadius_Full_Report.xlsx",
            mime=XLSX_MIME,
            use_container_width=True,
        )

    notes = st.session_state.get("full_notes")
    if notes:
        with st.expander("Report notes / skipped sections"):
            for n in notes:
                st.write(f"- {n}")


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


def _live_conditions():
    """Header + controls, then an auto-refreshing metrics fragment."""
    st.markdown("##### 🔴 Live conditions (now)")
    lc1, lc2, lc3 = st.columns([2, 1, 1])
    lc1.caption(
        "Real-time readings at this point (Open-Meteo). Toggle Auto to "
        "refresh every 5 min, or pull on demand.")
    lc2.toggle("Auto 5m", key="live_auto",
               help="Auto-refresh live metrics every 5 minutes.")
    if lc3.button("🔄 Refresh", use_container_width=True):
        st.session_state.live_nonce = \
            st.session_state.get("live_nonce", 0) + 1

    interval = 300 if st.session_state.get("live_auto") else None

    @st.fragment(run_every=interval)
    def _live_metrics():
        _render_live()

    _live_metrics()
    st.divider()


def _render_live():
    """Fetch + render the live metrics (runs inside the fragment)."""
    from core.weather import (get_current, get_air_quality,
                              drying_assessment)
    import datetime as _dt

    nonce = st.session_state.get("live_nonce", 0)
    try:
        cur = get_current(st.session_state.lat, st.session_state.lon,
                          nonce)
    except Exception as e:
        st.warning(f"Could not read live conditions: {e}")
        cur = None

    if cur:
        # Rain / sun headline
        if cur["is_raining"]:
            amt = cur["precip"] or cur["rain"] or cur["showers"]
            st.error(f"🌧️ Raining now - {cur['condition']} "
                     f"({amt:.1f} mm/h)")
        elif cur["is_day"]:
            st.success(f"☀️ {cur['condition']} - dry")
        else:
            st.info(f"🌙 {cur['condition']} - night, dry")

        c = st.columns(4)
        c[0].metric("Temperature", f"{cur['temp']}°C",
                    f"feels {cur['feels_like']}°C")
        c[1].metric("Humidity", f"{cur['humidity']}%")
        c[2].metric("Wind", f"{cur['wind_speed']} km/h",
                    f"gust {cur['wind_gust']}")
        c[3].metric("Rain now", f"{cur['precip']:.1f} mm/h")
        c = st.columns(4)
        c[0].metric("Cloud cover", f"{cur['cloud_cover']}%")
        c[1].metric("Sun (solar)", f"{cur['solar']:.0f} W/m²")
        c[2].metric("UV index", f"{cur.get('uv') or 0:.1f}")
        c[3].metric("Pressure", f"{cur['pressure']:.0f} hPa")

        # Real-time soil + water balance (irrigation / drying signal)
        c = st.columns(4)
        sm = cur.get("soil_moisture")
        c[0].metric("Soil moisture", f"{sm*100:.0f}%" if sm is not None
                    else "-", help="Volumetric, surface 0-1 cm.")
        c[1].metric("Soil temp", f"{cur.get('soil_temp') or 0:.0f}°C")
        c[2].metric("Evapotranspiration",
                    f"{cur.get('et') or 0:.2f} mm/h",
                    help="Current water loss rate (ET).")
        aq = get_air_quality(st.session_state.lat,
                             st.session_state.lon, nonce)
        if aq and aq.get("pm2_5") is not None:
            c[3].metric("Air PM2.5", f"{aq['pm2_5']:.0f} µg/m³",
                        f"AQI {aq.get('us_aqi', '-')}")

        label, score, reasons = drying_assessment(cur)
        st.markdown(
            f"**🌾 Drying suitability: {label} ({score}/100)** - "
            + "; ".join(reasons))
        auto = " · auto-refresh on" if st.session_state.get(
            "live_auto") else ""
        st.caption(
            f"Reading time: {cur.get('time', '-')} · updated "
            f"{_dt.datetime.now().strftime('%H:%M:%S')}{auto}")


def _forecast_tab():

    _live_conditions()

    st.caption(
        "16-day forecast for the selected point (Open-Meteo). "
        "Use the dry window for harvest and pickup planning."
    )

    from core.weather import get_forecast, analyze_forecast

    # Fetch only on click, so a slow weather server can't block the
    # rest of the page.
    if st.button("⛅ Get Forecast", use_container_width=True,
                 type="primary"):
        try:
            st.session_state.forecast_days = get_forecast(
                st.session_state.lat, st.session_state.lon)
        except Exception as e:
            st.session_state.forecast_days = None
            st.warning(f"Could not fetch forecast: {e}")
            return

    days = st.session_state.get("forecast_days")

    if days is None:
        st.info("Click Get Forecast for the 16-day outlook.")
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

    sub_crop, sub_soil, sub_ai = st.tabs(
        ["🌾 Crop Observation", "🧾 Soil Health Card",
         "🧠 Trained Crop Map"])

    with sub_soil:
        _soil_card_section(villages)

    with sub_crop:
        _crop_observation_section(villages)

    with sub_ai:
        _classifier_section()


def _classifier_section():

    import pandas as pd

    import folium
    from streamlit_folium import st_folium

    from core.ground_truth import load_records
    from gee.classifier import (
        can_train, labelled_points, train_and_classify, MIN_POINTS,
        parse_labeled_points, probe)
    from gis.village_search import village_centroids

    st.caption(
        "Trains a Random Forest on labelled points using ~35 features "
        "(reflectance, red-edge & moisture indices, phenology, radar, "
        "Dynamic World probabilities, terrain) - a crop map tuned to "
        "your region, not a global guess."
    )

    # --- Coconut model (bundled ground truth, one click) ---
    from gee.classifier import (
        train_coconut_classifier, coconut_points_in_view)

    n_coco = len(coconut_points_in_view(
        st.session_state.lat, st.session_state.lon,
        st.session_state.radius))

    st.markdown("##### 🥥 Coconut model (trained on field ground truth)")
    st.caption(
        f"{n_coco} confirmed-coconut villages from the FRUITS/Bhoomi "
        "survey lie in this view. Trains a Random Forest on them vs "
        "auto-sampled non-coconut land cover - real labels, not "
        "thresholds. Pan to a coconut belt (Tiptur, Gubbi, Arsikere, "
        "Nagamangala, Channapatna, Hiriyur) if the count is low.")

    if st.button("🥥 Train coconut model from ground truth",
                 use_container_width=True, type="primary",
                 disabled=n_coco < 30):
        try:
            st.session_state.classifier_result = \
                train_coconut_classifier(
                    st.session_state.lat, st.session_state.lon,
                    st.session_state.radius, st.session_state.year)
            r = st.session_state.classifier_result
            msg = f"Trained on {r['n_points']} coconut ground-truth points"
            if r.get("coconut_ac") is not None:
                msg += f" · mapped {r['coconut_ac']:,} ac coconut in view"
            st.success(msg)
        except Exception as e:
            st.error(f"Training failed: {e}")

    st.divider()

    # --- Direct labelled-points training (paste lat, lon, crop) ---
    with st.expander("📌 Train from pasted coordinates "
                     "(lat, lon, crop)", expanded=False):
        st.caption(
            "One point per line: lat, lon, crop. Crops: Coconut, "
            "Arecanut, Banana, Maize, Paddy, Sugarcane, Turmeric, "
            "Chilli, Vegetables, Groundnut, Fallow. Needs "
            f"{MIN_POINTS}+ points across 2+ crops.")
        ptext = st.text_area(
            "Labelled points",
            placeholder="10.6588, 77.0089, Coconut\n"
                        "11.9270, 76.9424, Banana\n"
                        "14.4667, 75.9167, Maize",
            height=140, key="clf_points_text")

        if st.button("🧠 Train from these points",
                     use_container_width=True, type="primary"):
            pts, grps = parse_labeled_points(ptext)
            if not can_train(pts, grps):
                st.error(
                    f"Need {MIN_POINTS}+ valid points across 2+ crops "
                    f"- got {len(pts)} across {len(grps)}.")
            else:
                try:
                    st.session_state.classifier_result = \
                        train_and_classify(
                            st.session_state.lat,
                            st.session_state.lon,
                            st.session_state.radius,
                            st.session_state.year, pts)
                    st.success(
                        f"Trained on {len(pts)} points, "
                        f"{len(grps)} crops.")
                except Exception as e:
                    st.error(f"Training failed: {e}")

    # --- Feature probe (calibration) ---
    with st.expander("🔬 Probe satellite features at a coordinate",
                     expanded=False):
        st.caption(
            "Reads the raw discriminating features (peak NDVI, "
            "moisture, radar VH, Dynamic World probabilities...) at a "
            "point - useful for checking why a plot classifies the "
            "way it does, or for tuning thresholds.")
        prow = st.text_input("lat, lon", key="probe_pt",
                             placeholder="10.6588, 77.0089")
        if st.button("Read features", use_container_width=True):
            try:
                a, b = prow.replace(";", ",").split(",")[:2]
                vals = probe(float(a), float(b),
                             st.session_state.year)
                st.dataframe(
                    pd.DataFrame(vals.items(),
                                 columns=["Feature", "Value"]),
                    use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Probe failed: {e}")

    st.divider()
    st.caption("Or train from village ground-truth observations:")

    gt = load_records()

    try:
        centroids = village_centroids(
            st.session_state.lat,
            st.session_state.lon,
            st.session_state.radius,
        )
    except Exception as e:
        st.warning(f"Could not locate villages: {e}")
        return

    points, groups = labelled_points(gt, centroids)

    c1, c2 = st.columns(2)
    c1.metric("Usable labelled villages", len(points))
    c2.metric("Crop groups", len(groups))

    if not can_train(points, groups):
        st.info(
            "Not enough labelled data in this buffer yet. Keep "
            "logging crop observations in the villages here - once "
            f"there are {MIN_POINTS}+ across 2+ groups, the trained "
            "map unlocks."
        )
        return

    if st.button("🧠 Train & Map", use_container_width=True,
                 type="primary"):
        try:
            st.session_state.classifier_result = train_and_classify(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius,
                st.session_state.year,
                points,
            )
        except Exception as e:
            st.session_state.classifier_result = None
            st.error(f"Training failed: {e}")
            return

    res = st.session_state.get("classifier_result")

    if not res:
        return

    a, b = st.columns(2)
    a.metric("Training Points", res["n_points"])
    if res.get("train_accuracy") is not None:
        b.metric("Training Accuracy", f"{res['train_accuracy']}%")

    st.caption("Legend: " + "  ".join(
        f"{g}" for g in res["classes"]))

    m = folium.Map(
        location=[st.session_state.lat, st.session_state.lon],
        zoom_start=12, tiles=None)
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google", name="Satellite").add_to(m)
    folium.TileLayer(
        tiles=res["tile_url"], attr="AgriRadius", name="Crop Map",
        opacity=0.6).add_to(m)
    for g, color in res["legend"].items():
        folium.Circle(
            location=[st.session_state.lat, st.session_state.lon],
            radius=1, color=f"#{color}", tooltip=g).add_to(m)
    st_folium(m, width=None, height=500,
              returned_objects=[])


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

    st.caption(
        "Prices come from the government AGMARKNET feed (data.gov.in) "
        "- the only open source, used by every price aggregator. It "
        "can be slow; the fetch gives up after ~12s and falls back to "
        "the last cached prices if the server is down. Just click "
        "again if it fails.")

    # Fetch ONLY on button click, and fail fast (12s) so it can't
    # freeze the page. A synchronous fetch can't be cancelled
    # mid-flight, so 'stop' = a short timeout + retry.
    bcol1, bcol2 = st.columns([3, 1])
    with bcol1:
        fetch = st.button("Get Prices", use_container_width=True,
                          type="primary")
    with bcol2:
        if st.button("Clear", use_container_width=True):
            st.session_state.mandi_df = None
            st.rerun()

    if fetch:
        try:
            st.session_state.mandi_df = get_prices(
                COMMODITIES[commodity_label], state)
            st.session_state.mandi_label = commodity_label
            st.session_state.mandi_state = state
        except Exception as e:
            st.session_state.mandi_df = None
            st.error(f"Could not fetch prices: {e}")
            return

    df = st.session_state.get("mandi_df")

    if df is None:
        st.info("Choose a commodity and state, then click Get Prices.")
        return

    commodity_label = st.session_state.get("mandi_label", commodity_label)
    state = st.session_state.get("mandi_state", state)

    if df.empty:
        st.info(
            f"No {commodity_label} prices reported "
            f"{'in ' + state if state != 'All India' else 'today'} - "
            "markets may not have traded it today. Try All India."
        )
        return

    note = df.attrs.get("note")
    if note:
        st.warning(note)

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

    # --- MSP floor comparison (procurement signal) ---
    from core.msp import msp_for_commodity
    m = msp_for_commodity(commodity_label)
    if m is None:
        st.caption(
            f"ℹ️ {commodity_label} is not an MSP-mandated crop - there "
            "is no government floor price for it.")
    elif m["comparable"]:
        avg = float(modal.mean())
        floor = m["msp"]
        gap = avg - floor
        pct = 100 * gap / floor if floor else 0
        mc1, mc2 = st.columns(2)
        mc1.metric(f"MSP floor ({m['season']} {m['year']})",
                   f"₹{floor:,.0f}/qtl")
        mc2.metric("Avg modal vs MSP", f"₹{avg:,.0f}/qtl",
                   f"{pct:+.0f}% vs floor")
        if avg < floor:
            st.warning(
                f"Market average is **below the MSP floor** - farmers "
                f"may hold produce or sell to procurement. Sourcing "
                f"leverage is higher.")
        else:
            st.info(
                f"Market average is **{pct:.0f}% above MSP** - open "
                f"market is the better sell for farmers.")
    else:
        st.info(
            f"ℹ️ Coconut has no direct MSP, but the **copra floor is "
            f"₹{m['msp']:,.0f}/qtl** ({m['year']}) - the effective "
            "price support for coconut farmers who make copra.")

    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=400)

    st.download_button(
        "📥 Mandi Prices (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"Mandi_{commodity_label.replace(' ', '_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # --- Historical price trend (variety-wise archive, 2014+) ---
    st.divider()
    st.markdown("##### 📈 Price trend (history)")
    st.caption(
        "Monthly modal price (median across the state's reporting "
        "markets) from the daily archive - shows seasonality and the "
        "multi-year direction, to time procurement.")
    if st.button("Show price trend", use_container_width=True):
        try:
            from core.mandi import get_price_history, COMMODITIES
            hist = get_price_history(
                COMMODITIES[commodity_label], state)
            if hist is None or hist.empty:
                st.info("No historical prices found for this "
                        "commodity/state.")
            else:
                st.session_state.mandi_hist = hist
                st.session_state.mandi_hist_key = (commodity_label, state)
        except Exception as e:
            st.warning(f"Could not load history: {e}")

    hist = st.session_state.get("mandi_hist")
    if hist is not None and not hist.empty:
        hk = st.session_state.get("mandi_hist_key", ("", ""))
        st.caption(f"{hk[0]} · {hk[1]} · {len(hist)} months "
                   f"(₹/qtl, monthly median)")
        st.line_chart(hist.set_index("Month")["Modal"],
                      height=260)
        recent = hist.iloc[-1]
        first = hist.iloc[0]
        chg = (recent["Modal"] - first["Modal"])
        pctv = 100 * chg / first["Modal"] if first["Modal"] else 0
        h1, h2, h3 = st.columns(3)
        h1.metric("Latest month",
                  f"₹{recent['Modal']:,.0f}/qtl")
        h2.metric("Range (period)",
                  f"₹{hist['Low'].min():,.0f}-{hist['High'].max():,.0f}")
        h3.metric("Since start", f"{pctv:+.0f}%")

    # --- Variety / grade breakdown (variety-wise archive) ---
    st.divider()
    st.markdown("##### 🏷️ Variety / grade breakdown")
    st.caption(
        "Price by variety & grade (e.g. Grade-I vs Grade-II) - the "
        "premium a better grade fetches, for sourcing & pricing.")
    if st.button("Show variety breakdown", use_container_width=True):
        try:
            from core.mandi import get_variety_prices, COMMODITIES
            vdf = get_variety_prices(COMMODITIES[commodity_label], state)
            if vdf is None or vdf.empty:
                st.info("No variety data found for this "
                        "commodity/state.")
                st.session_state.mandi_var = None
            else:
                st.session_state.mandi_var = vdf
                st.session_state.mandi_var_key = (commodity_label, state)
        except Exception as e:
            st.warning(f"Could not load variety breakdown: {e}")

    vdf = st.session_state.get("mandi_var")
    if vdf is not None and not vdf.empty:
        vk = st.session_state.get("mandi_var_key", ("", ""))
        st.caption(f"{vk[0]} · {vk[1]} · ₹/qtl "
                   "(Latest = most recent reported day per variety)")
        st.dataframe(vdf, use_container_width=True, hide_index=True)
        top = vdf.iloc[0]
        st.success(
            f"Top grade: **{top['Variety']}** at "
            f"**₹{top['Latest']:,}/qtl** (latest {top['Latest Date']})")


@st.cache_data(show_spinner="Reading livestock census for this area...")
def _allied_area_profile(lat, lon, radius_km):
    from core.allied import area_profile
    return area_profile(lat, lon, radius_km)


@st.cache_data(show_spinner=False)
def _allied_sector_rows(lat, lon, radius_km, which):
    from core import allied
    dists = allied.districts_touching(lat, lon, radius_km)
    path = (allied.SERICULTURE_CSV if which == "sericulture"
            else allied.FISHERIES_CSV)
    return allied.sector_for_districts(path, dists)


def _allied_tab():
    """Allied / livestock sectors: animal husbandry, poultry, dairy,
    feed demand, aquaculture, sericulture, fisheries."""

    lat = st.session_state.lat
    lon = st.session_state.lon
    radius = st.session_state.radius

    st.caption(
        "District figures are the **20th Livestock Census 2019** "
        "(real counts). 'Within your radius' numbers are area-"
        "allocated from those district totals; milk and feed are "
        "**derived estimates** (see method note at the bottom).")

    prof = _allied_area_profile(lat, lon, radius)

    if not prof.get("available"):
        st.info(
            "No livestock census match for this area yet. Bundled data "
            "currently covers Karnataka; other states drop in as a CSV "
            "under data/allied/. (" + str(prof.get("reason", "")) + ")")
    else:
        wr = prof["within_radius"]
        d = prof["derived"]

        st.markdown("#### 🐄 Livestock & poultry (within radius, est.)")
        c = st.columns(3)
        c[0].metric("Cattle", f"{wr['cattle']:,}")
        c[1].metric("Buffalo", f"{wr['buffalo']:,}")
        c[2].metric("Poultry", f"{wr['poultry']:,}")
        c = st.columns(3)
        c[0].metric("Goat", f"{wr['goat']:,}")
        c[1].metric("Sheep", f"{wr['sheep']:,}")
        c[2].metric("Pig", f"{wr['pig']:,}")

        st.markdown("#### 🥛 Dairy pool & feed demand (estimated)")
        c = st.columns(3)
        c[0].metric("Milk / day (L)",
                    f"{d['milk_litres_per_day']:,}")
        c[1].metric("Milk / year (L)",
                    f"{d['milk_litres_per_year']:,}")
        c[2].metric("In-milk bovines", f"{d['milch_bovines']:,}")
        c = st.columns(3)
        c[0].metric("Bovine feed (t/day)", f"{d['bovine_feed_tpd']:,}")
        c[1].metric("Poultry feed (t/day)", f"{d['poultry_feed_tpd']:,}")
        c[2].metric("Total feed (t/day)", f"{d['total_feed_tpd']:,}")
        st.caption(
            "Feed = concentrate/manufactured feed only (the feed-"
            "company-relevant portion), not green/dry fodder.")

        rows = prof.get("districts", [])
        if rows:
            import pandas as _pd
            tdf = _pd.DataFrame(rows)
            ren = {"AreaShare": "Share in radius", "cattle": "Cattle",
                   "buffalo": "Buffalo", "goat": "Goat", "sheep": "Sheep",
                   "pig": "Pig", "poultry": "Poultry"}
            tdf = tdf.rename(columns=ren)
            with st.expander(
                    "District census totals (real) & share falling in "
                    "your radius"):
                st.dataframe(tdf, use_container_width=True,
                             hide_index=True)

    st.divider()

    # --- Aquaculture (satellite, opt-in compute) ---
    st.markdown("#### 🐟 Aquaculture ponds (satellite)")
    st.caption(
        "Persistent pond-sized water bodies (fish/prawn/farm ponds). "
        "Toggle the *Aquaculture ponds* map layer to see them; measure "
        "the area here.")
    if st.button("Measure pond area in radius"):
        try:
            from gee.aquaculture import aquaculture_stats
            s = aquaculture_stats(lat, lon, radius, st.session_state.year)
            st.metric("Detected pond area (acres)", f"{s['pond_ac']:,}")
        except Exception as e:
            st.warning(f"Could not measure ponds: {e}")

    st.divider()

    # --- Sericulture & Fisheries: district data if bundled, else the
    #     authoritative state-level figure for the state(s) in view. ---
    from core import allied as _allied
    try:
        state_keys = _allied.states_touching(lat, lon, radius)
    except Exception:
        state_keys = []

    for which, title, note, state_csv in (
        ("sericulture", "🐛 Sericulture",
         "Mulberry silk - raw silk production.",
         _allied.SERICULTURE_STATE_CSV),
        ("fisheries", "🎣 Fisheries",
         "Inland fish production.",
         _allied.FISHERIES_STATE_CSV),
    ):
        st.markdown(f"#### {title}")
        st.caption(note)

        # 1) district-level (only if a district CSV has been filled)
        try:
            ddf = _allied_sector_rows(lat, lon, radius, which)
        except Exception:
            ddf = None
        if ddf is not None and not ddf.empty:
            st.dataframe(ddf, use_container_width=True, hide_index=True)
            continue

        # 2) state-level fallback (real, latest)
        try:
            sdf = _allied.state_sector_rows(state_csv, state_keys)
        except Exception:
            sdf = None
        if sdf is not None and not sdf.empty:
            st.dataframe(sdf, use_container_width=True, hide_index=True)
            st.caption("State-level figure (latest available). "
                       "District split not yet in open data.")
        else:
            st.info(
                "No figure bundled for this state yet - add a row to "
                f"data/allied/{which}_state.csv (or district rows to "
                f"{which}_district.csv) and it appears here.")

    # --- Apiculture (national-only data) ---
    st.markdown("#### 🐝 Apiculture (beekeeping)")
    st.info(_allied.APICULTURE_NOTE)

    st.divider()

    # --- Importable reference datasets (fertiliser, horticulture,
    #     land use, ...) - download-only from data.gov.in, drop-in. ---
    st.markdown("#### 📚 Agri economy data (importable)")
    from core import agri_data
    try:
        d_states = _allied.states_touching(lat, lon, radius)
    except Exception:
        d_states = []
    try:
        d_dists = _allied.districts_touching(lat, lon, radius)
    except Exception:
        d_dists = []

    for key, ds in agri_data.DATASETS.items():
        st.markdown(f"**{ds['label']}**")
        try:
            rows = agri_data.rows_for_area(key, d_states, d_dists)
        except Exception:
            rows = None
        if rows is not None and not rows.empty:
            st.caption(ds["note"])
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption(
                ds["note"] + "  \n_Not bundled for this area yet._ "
                f"Source: {ds['source']}. After downloading, run: "
                f"`py tools/import_agri.py {key} <file>"
                f"{' <State>' if ds['level']=='state' else ''}` "
                "(or drop the file in the folder and send it to me).")

    with st.expander("ℹ️ Method & sources"):
        st.markdown(
            "**Real:** cattle / buffalo / goat / sheep / pig / poultry "
            "counts are 20th Livestock Census 2019 district figures "
            "(DAHD, via the ARTPARK open release).\n\n"
            "**Area-allocated:** a district's count is split by the "
            "share of its area inside your radius (from village "
            "polygons) - assumes even spread, so treat as an estimate, "
            "not a headcount.\n\n"
            "**Derived (estimates):** milk = in-milk cattle (28%) x "
            "4.5 L + in-milk buffalo (32%) x 5.5 L per day; feed = "
            "2.5 kg/day concentrate per in-milk bovine + 0.10 kg/day "
            "per commercial bird (65% of poultry). Coefficients are "
            "tunable in core/allied.py.\n\n"
            "**Aquaculture:** JRC Global Surface Water occurrence, "
            "pond-sized clusters on flat land - visible from space, "
            "so it is a true map layer.")


def _safe(render, *args):
    """Render a tab's content; if it errors, show the error inside
    that tab instead of aborting the whole results section (which
    would blank out every tab after it)."""
    try:
        render(*args)
    except Exception as e:
        import traceback
        st.error(f"This section hit an error: {e}")
        with st.expander("Technical details"):
            st.code(traceback.format_exc())


def _data_confidence_panel():
    """Honest, always-visible statement of what to trust and how."""

    with st.expander("ℹ️ Data & Confidence - how much to trust this",
                     expanded=False):
        st.markdown(
            "**High confidence (direct measurements):**\n"
            "- NDVI / crop-cycle vigour - measured from Sentinel-2, "
            "not modelled\n"
            "- Rainfall history (CHIRPS, 40+ yrs) and 16-day forecast\n"
            "- Paddy & plantation detection - Sentinel-1 radar "
            "structure\n"
            "- Mandi prices - reported by markets, not estimated\n\n"
            "**Use as ranges, not exact (modelled / classified):**\n"
            "- Land-cover classes (Dynamic World ~75-85% accuracy)\n"
            "- Soil pH / OC / N / texture - SoilGrids modelled at "
            "250 m; belt-level, not field-level\n"
            "- Cropping-pattern & sourcing-score thresholds\n\n"
            "**Built-in cross-checks:** two independent datasets "
            "(Dynamic World + ESA WorldCover/WorldCereal) are "
            "compared, a 3-year stability test flags unreliable "
            "areas, and every prediction can be scored against your "
            "team's ground-truth.\n\n"
            "**Rule of thumb:** trust the direction and the ranges; "
            "verify the edges on the ground. Accuracy improves for a "
            "region as your team logs observations there.\n\n"
            "*Sources: Sentinel-1/2 (ESA), Dynamic World (Google), "
            "WorldCover/WorldCereal (ESA), SoilGrids (ISRIC), CHIRPS "
            "(UCSB), ERA5-Land (ECMWF), Open-Meteo, AGMARKNET "
            "(data.gov.in).*"
        )


def _point_details_view():
    """Point mode: details for one exact coordinate + optional
    multi-point table."""

    import pandas as pd

    lat = st.session_state.lat
    lon = st.session_state.lon

    st.subheader("📍 Point Details")
    st.caption(
        f"Everything the satellites know about the exact point "
        f"{lat:.6f}, {lon:.6f} - no radius. First run takes ~1 min.")

    if st.button("🔎 Get Point Details", use_container_width=True,
                 type="primary"):
        from gee.point_query import point_details
        try:
            st.session_state.point_result = point_details(
                lat, lon, st.session_state.year)
        except Exception as e:
            st.session_state.point_result = None
            st.error(f"Point analysis failed: {e}")

    r = st.session_state.get("point_result")

    if r:
        c1, c2, c3 = st.columns(3)
        c1.metric("Village", r.get("Village", "-"))
        c2.metric("Taluk", r.get("Taluk", "-"))
        c3.metric("District", r.get("District", "-"))

        c1, c2, c3 = st.columns(3)
        c1.metric("Land Cover", str(r.get("Land Cover", "-")))
        c2.metric("Elevation", f"{r.get('Elevation (m)', '-')} m")
        c3.metric("Slope", f"{r.get('Slope (deg)', '-')}°")

        st.markdown("**Soil**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("pH", r.get("Soil pH", "-"))
        c2.metric("Organic C", f"{r.get('Soil OC (g/kg)', '-')} g/kg")
        c3.metric("Nitrogen", f"{r.get('Soil N (g/kg)', '-')} g/kg")
        c4.metric("Texture", str(r.get("Soil Texture", "-")))

        if r.get("Cropping Pattern"):
            st.markdown("**History**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Cropping Pattern", r["Cropping Pattern"])
            c2.metric("Cycles/Year", r.get("Cycles/Year", "-"))
            if r.get("Mean Soil Temp (C)") is not None:
                c3.metric("Mean Soil Temp",
                          f"{r['Mean Soil Temp (C)']} °C")

        if r.get("Rainfall Reliability"):
            c1, c2 = st.columns(2)
            c1.metric("Rainfall Reliability",
                      r["Rainfall Reliability"])
            c2.metric("Avg Annual Rain",
                      f"{r.get('Avg Annual Rain (mm)', '-')} mm")

        # Download this point's full record
        flat = {k: v for k, v in r.items() if not k.startswith("_")}
        st.download_button(
            "📥 Point Details (CSV)",
            pd.DataFrame([flat]).to_csv(index=False).encode("utf-8"),
            file_name="Point_Details.csv", mime="text/csv",
            use_container_width=True)

    # --- Multiple coordinates ---
    st.divider()
    with st.expander("📋 Multiple points (paste coordinates)"):
        st.caption(
            "One point per line as 'lat, lon'. Returns village, land "
            "cover, soil and elevation for each (no history, to keep "
            "it fast).")
        txt = st.text_area(
            "Coordinates", placeholder="12.9716, 77.5946\n"
            "13.3400, 77.1006", height=120)

        if st.button("Analyze Points", use_container_width=True):
            from gee.point_query import point_core
            rows = []
            for line in txt.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    a, b = line.replace(";", ",").split(",")[:2]
                    plat, plon = float(a), float(b)
                except Exception:
                    continue
                try:
                    core = point_core(plat, plon, st.session_state.year)
                    rows.append({k: v for k, v in core.items()
                                 if not k.startswith("_")})
                except Exception:
                    rows.append({"lat": plat, "lon": plon,
                                 "Village": "error"})
            st.session_state.multi_points_df = (
                pd.DataFrame(rows) if rows else None)

        mp = st.session_state.get("multi_points_df")
        if mp is not None and not mp.empty:
            st.dataframe(mp, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Points Table (CSV)",
                mp.to_csv(index=False).encode("utf-8"),
                file_name="Points_Details.csv", mime="text/csv",
                use_container_width=True)


def results():

    if st.session_state.get("mode") == "Point location":
        _safe(_point_details_view)
        return

    st.subheader("🌾 Analysis Results")

    df = _landcover_df()

    _data_confidence_panel()

    (tab_summary, tab_villages, tab_charts, tab_crop,
     tab_rain, tab_forecast, tab_soil, tab_allied, tab_mandi, tab_gt,
     tab_downloads) = st.tabs(
        ["📊 Summary", "🏘️ Villages", "📈 Charts",
         "🌱 Crop Cycle", "🌧️ Rainfall", "⛅ Forecast",
         "🧪 Soil", "🐄 Allied Sectors", "💰 Mandi",
         "✅ Ground Truth", "📥 Downloads"]
    )

    with tab_summary:
        _safe(_summary_tab, df)
        st.divider()
        _safe(_confidence_check)
        _safe(_stability_check)

    with tab_villages:
        _safe(_villages_tab)
        _safe(_village_insights_section)
        _safe(_sourcing_score_section)

    with tab_charts:
        _safe(_charts_tab, df)

    with tab_crop:
        _safe(_crop_cycle_tab)
        st.divider()
        _safe(_paddy_check)
        _safe(_plantation_check)

    with tab_rain:
        _safe(_rainfall_tab)

    with tab_forecast:
        _safe(_forecast_tab)

    with tab_soil:
        _safe(_soil_tab)

    with tab_allied:
        _safe(_allied_tab)

    with tab_mandi:
        _safe(_mandi_tab)

    with tab_gt:
        _safe(_ground_truth_tab)

    with tab_downloads:
        _safe(_downloads_tab, df)
