"""One-click full report: run every analysis, bundle every dataset.

gather() executes all analyses (using their caches when already
run), stores results into session state so the tabs fill in too,
and returns a bundle dict used by the PDF and Excel builders.
"""

import pandas as pd
import streamlit as st

from core.crop_cycle import analyze_series, to_dataframe
from core.rain_insight import analyze_rainfall
from core.rain_insight import to_dataframe as rain_to_df


def gather(progress=None):
    """Run everything. progress(pct, label) reports steps."""

    def step(pct, label):
        if progress:
            progress(pct, label)

    lat = st.session_state.lat
    lon = st.session_state.lon
    radius = st.session_state.radius
    year = st.session_state.year

    bundle = {
        "meta": {
            "lat": lat, "lon": lon, "radius": radius, "year": year,
            "place": st.session_state.search_location or "",
        },
        "notes": [],
    }

    # 1. Land cover
    step(5, "Land cover analysis...")
    try:
        if st.session_state.results is None:
            from gee.analysis import analyze_landcover
            st.session_state.results = analyze_landcover(
                lat, lon, radius, year)
        bundle["landcover_df"] = pd.DataFrame(st.session_state.results)
    except Exception as e:
        bundle["landcover_df"] = None
        bundle["notes"].append(f"Land cover failed: {e}")

    # 2. Cropland confidence
    step(15, "Cropland confidence cross-check...")
    try:
        from gee.worldcover import cropland_crosscheck
        st.session_state.crosscheck = cropland_crosscheck(
            lat, lon, radius, year)
        bundle["crosscheck"] = st.session_state.crosscheck
    except Exception as e:
        bundle["crosscheck"] = None
        bundle["notes"].append(f"Confidence check failed: {e}")

    # 3. Stability
    step(22, "3-year stability check...")
    try:
        from gee.stability import cropland_stability
        st.session_state.stability = cropland_stability(
            lat, lon, radius, year)
        bundle["stability"] = st.session_state.stability
    except Exception:
        bundle["stability"] = None

    # 4. NDVI crop cycle
    step(30, "NDVI crop cycle (30-60s)...")
    try:
        from gee.ndvi import ndvi_monthly_series
        st.session_state.ndvi_series = ndvi_monthly_series(
            lat, lon, radius, year - 1, year)
        ndvi_df = to_dataframe(st.session_state.ndvi_series)
        bundle["ndvi_df"] = ndvi_df
        bundle["crop_insight"] = (
            analyze_series(ndvi_df)
            if not ndvi_df["NDVI"].isna().all() else None)
    except Exception as e:
        bundle["ndvi_df"] = None
        bundle["crop_insight"] = None
        bundle["notes"].append(f"Crop cycle failed: {e}")

    # 5. Paddy
    step(45, "Paddy detection (radar)...")
    try:
        from gee.paddy import paddy_stats
        st.session_state.paddy_stats = paddy_stats(
            lat, lon, radius, year)
        bundle["paddy"] = st.session_state.paddy_stats
    except Exception:
        bundle["paddy"] = None

    # 6. Plantation
    step(52, "Plantation detection...")
    try:
        from gee.plantation import plantation_stats
        st.session_state.plantation_stats = plantation_stats(
            lat, lon, radius, year)
        bundle["plantation"] = st.session_state.plantation_stats
    except Exception:
        bundle["plantation"] = None

    # 7. Rainfall
    step(58, "10-year rainfall history...")
    try:
        from gee.rainfall import rainfall_monthly
        st.session_state.rainfall_series = rainfall_monthly(
            lat, lon, radius, year)
        rdf = rain_to_df(st.session_state.rainfall_series)
        bundle["rain_df"] = rdf
        bundle["rain"] = analyze_rainfall(rdf)
    except Exception as e:
        bundle["rain_df"] = None
        bundle["rain"] = None
        bundle["notes"].append(f"Rainfall failed: {e}")

    # 8. Forecast
    step(64, "16-day weather forecast...")
    try:
        from core.weather import analyze_forecast, get_forecast
        days = get_forecast(lat, lon)
        bundle["forecast_days"] = pd.DataFrame(days)
        bundle["forecast"] = analyze_forecast(days)
    except Exception:
        bundle["forecast_days"] = None
        bundle["forecast"] = None

    # 9. Soil profile + climate + per-village
    step(70, "Soil profile...")
    try:
        from gee.soil import interpret, soil_profile
        st.session_state.soil = soil_profile(lat, lon, radius)
        bundle["soil_profile"] = st.session_state.soil
        bundle["soil_verdicts"] = interpret(st.session_state.soil)
    except Exception as e:
        bundle["soil_profile"] = None
        bundle["soil_verdicts"] = None
        bundle["notes"].append(f"Soil profile failed: {e}")

    step(74, "Soil temperature & moisture...")
    try:
        from gee.climate import soil_climate
        st.session_state.soil_climate = soil_climate(
            lat, lon, radius, year)
        bundle["soil_climate_df"] = pd.DataFrame(
            st.session_state.soil_climate)
    except Exception as e:
        bundle["soil_climate_df"] = None
        bundle["notes"].append(f"Soil temp/moisture failed: {e}")

    step(78, "Per-village soil...")
    try:
        from gee.soil import village_soil
        st.session_state.village_soil = village_soil(
            lat, lon, radius)
        bundle["village_soil_df"] = st.session_state.village_soil
    except Exception as e:
        bundle["village_soil_df"] = None
        bundle["notes"].append(f"Per-village soil failed: {e}")

    # 10. Villages + insights + scores
    step(82, "Village list...")
    try:
        from gis.village_search import get_villages
        bundle["villages_df"] = get_villages(lat, lon, radius)
    except Exception:
        bundle["villages_df"] = None

    step(86, "Village insights (may take 1-3 min)...")
    try:
        from gee.village_stats import village_insights
        st.session_state.village_insights = village_insights(
            lat, lon, radius, year)
        bundle["insights_df"] = st.session_state.village_insights
    except Exception as e:
        bundle["insights_df"] = None
        bundle["notes"].append(f"Village insights skipped: {e}")

    step(94, "Sourcing scores...")
    try:
        from core.ground_truth import load_records
        from core.scoring import score_villages
        verdict = bundle["rain"]["verdict"] if bundle.get("rain") \
            else None
        scores = score_villages(
            bundle.get("insights_df"),
            bundle.get("village_soil_df"),
            verdict,
            load_records())
        st.session_state.sourcing_scores = scores
        bundle["scores_df"] = scores
    except Exception:
        bundle["scores_df"] = None

    # 11. Mandi prices - only if already fetched in the Mandi tab.
    # We do NOT call the slow data.gov.in API here, or the whole
    # report would hang on it. Fetch prices in the Mandi tab first
    # (click Get Prices) and they are included automatically.
    step(97, "Mandi prices (if fetched)...")
    try:
        md = st.session_state.get("mandi_df")
        if md is not None and not md.empty:
            md = md.copy()
            label = st.session_state.get("mandi_label")
            if label and "Commodity" not in md.columns:
                md.insert(0, "Commodity", label)
            bundle["mandi_df"] = md
        else:
            bundle["mandi_df"] = None
            bundle["notes"].append(
                "Mandi prices not included - fetch them in the Mandi "
                "tab (Get Prices) before building the report.")
    except Exception:
        bundle["mandi_df"] = None

    # 11b. Allied sectors & agri-economy (fast - local data + polygons)
    step(98, "Allied sectors (livestock, dairy, feed, agri-economy)...")
    try:
        from core import agri_data, allied
        prof = allied.area_profile(lat, lon, radius)
        states = allied.states_touching(lat, lon, radius)
        dists = allied.districts_touching(lat, lon, radius)
        bundle["allied"] = {
            "profile": prof,
            "sericulture": allied.state_sector_rows(
                allied.SERICULTURE_STATE_CSV, states),
            "fisheries": allied.state_sector_rows(
                allied.FISHERIES_STATE_CSV, states),
            "fertilizer": agri_data.rows_for_area(
                "fertilizer", states, dists),
            "horticulture": agri_data.rows_for_area(
                "horticulture", states, dists),
        }
    except Exception as e:
        bundle["allied"] = None
        bundle["notes"].append(f"Allied sectors skipped: {e}")

    # Mandi price trend / variety - only if fetched in the Mandi tab.
    bundle["mandi_hist"] = st.session_state.get("mandi_hist")
    bundle["mandi_var"] = st.session_state.get("mandi_var")

    # 12. Field data
    try:
        from core.ground_truth import load_records, load_soil_cards
        gt = load_records()
        cards = load_soil_cards()
        bundle["gt_df"] = gt if not gt.empty else None
        bundle["cards_df"] = cards if not cards.empty else None
    except Exception:
        bundle["gt_df"] = None
        bundle["cards_df"] = None

    step(100, "Building report...")

    return bundle


def pdf_bytes(bundle):
    """Full PDF report from the bundle. Returns bytes."""

    from core.report import build_area_report

    return build_area_report(
        bundle["meta"],
        landcover_df=bundle.get("landcover_df"),
        crosscheck=bundle.get("crosscheck"),
        crop_insight=bundle.get("crop_insight"),
        paddy=bundle.get("paddy"),
        rain=bundle.get("rain"),
        villages_df=bundle.get("villages_df"),
        insights_df=bundle.get("insights_df"),
        stability=bundle.get("stability"),
        plantation=bundle.get("plantation"),
        forecast=bundle.get("forecast"),
        soil_verdicts=bundle.get("soil_verdicts"),
        scores_df=bundle.get("scores_df"),
        mandi_df=bundle.get("mandi_df"),
        soil_climate_df=bundle.get("soil_climate_df"),
        village_soil_df=bundle.get("village_soil_df"),
        allied=bundle.get("allied"),
        mandi_hist=bundle.get("mandi_hist"),
        mandi_var=bundle.get("mandi_var"),
    )


def excel_bytes(bundle):
    """Multi-sheet Excel workbook from the bundle. Returns bytes."""

    from io import BytesIO

    meta = bundle["meta"]

    summary_rows = [
        ("Location", f"{meta['lat']:.6f}, {meta['lon']:.6f}"),
        ("Place", meta.get("place") or "-"),
        ("Radius (km)", meta["radius"]),
        ("Analysis Year", meta["year"]),
    ]

    if bundle.get("crosscheck"):
        r = bundle["crosscheck"]
        summary_rows += [
            ("Confirmed Cropland (ac)", r["confirmed_ac"]),
            ("Cropland Agreement (%)", r["agreement_pct"]),
        ]

    if bundle.get("stability"):
        summary_rows.append(
            ("Cropland Stability", bundle["stability"]["verdict"]))

    if bundle.get("crop_insight"):
        ci = bundle["crop_insight"]
        summary_rows += [
            ("Cropping Pattern", ci["pattern"]),
            ("Cycles per Year", ci["cycles_per_year"]),
        ]

    if bundle.get("paddy"):
        summary_rows.append(
            ("Paddy (ac)", bundle["paddy"]["paddy_ac"]))

    if bundle.get("plantation"):
        summary_rows.append(
            ("Plantation (ac)", bundle["plantation"]["plantation_ac"]))

    if bundle.get("rain"):
        r = bundle["rain"]
        summary_rows += [
            ("Rainfall Reliability", r["verdict"]),
            ("Avg Annual Rainfall (mm)", r["mean_annual_mm"]),
        ]

    if bundle.get("forecast"):
        f = bundle["forecast"]
        summary_rows += [
            ("Rain Next 7 Days (mm)", f["rain_7d_mm"]),
            ("Longest Dry Window (days)", f["dry_window_days"]),
        ]

    if bundle.get("soil_profile"):
        p = bundle["soil_profile"]
        summary_rows += [
            ("Soil pH", p.get("phh2o")),
            ("Soil OC (g/kg)", p.get("soc")),
            ("Soil N (g/kg)", p.get("nitrogen")),
        ]

    for n in bundle.get("notes", []):
        summary_rows.append(("Note", n))

    summary = pd.DataFrame(summary_rows,
                           columns=["Parameter", "Value"])

    sheets = [
        ("Summary", summary),
        ("Land Cover", bundle.get("landcover_df")),
        ("Sourcing Scores", bundle.get("scores_df")),
        ("Village Insights", bundle.get("insights_df")),
        ("Village Soil", bundle.get("village_soil_df")),
        ("Villages", bundle.get("villages_df")),
        ("NDVI Monthly", bundle.get("ndvi_df")),
        ("Rainfall Monthly", bundle.get("rain_df")),
        ("Forecast 16d", bundle.get("forecast_days")),
        ("Soil Climate", bundle.get("soil_climate_df")),
        ("Mandi Prices", bundle.get("mandi_df")),
        ("Ground Truth", bundle.get("gt_df")),
        ("Soil Cards", bundle.get("cards_df")),
    ]

    buf = BytesIO()

    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets:
            if df is not None and not df.empty:
                df.to_excel(xw, sheet_name=name[:31], index=False)

    return buf.getvalue()
