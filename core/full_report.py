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


def gather(progress=None, with_maps=True):
    """Run everything. progress(pct, label) reports steps.

    with_maps=False skips ONLY the map thumbnails. Every number,
    table and chart is still gathered and printed - the maps are the
    slow part (each is computed live over the whole circle), not the
    data. This is what makes a large radius practical: a 38 km report
    without maps builds in a couple of minutes, with maps it may run
    out of the rendering budget.
    """

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

    # 6a. Maize / kharif cereal
    step(54, "Maize / kharif crop detection...")
    try:
        from gee.maize import maize_stats
        bundle["maize"] = maize_stats(lat, lon, radius, year)
        # Also expose it in session state so the Forest tab can compare
        # it against the department's district figure.
        st.session_state.maize_stats = bundle["maize"]
    except Exception:
        bundle["maize"] = None

    # 6a-2. Aquaculture ponds
    step(55, "Aquaculture pond detection...")
    try:
        from gee.aquaculture import aquaculture_stats
        bundle["aquaculture"] = aquaculture_stats(
            lat, lon, radius, year)
    except Exception:
        bundle["aquaculture"] = None

    # 6b. Map thumbnails - visual proof for the PDF. EVERY layer the
    # app can draw is rendered: satellite, land cover, confidence,
    # NDVI, plantation, banana, paddy, maize, WorldCereal,
    # aquaculture and the three painted soil properties, plus the
    # vector layers (measured soil test, coconut crop survey).
    if not with_maps:
        step(56, "Skipping map images (data-only report)...")
        imgs = []
        bundle["notes"].append(
            "This is the DATA-ONLY report: map images were skipped on "
            "purpose, so it builds quickly at any radius. Every "
            "number, table and chart below is the full set - nothing "
            "is abbreviated. Rebuild with 'Include map images' to add "
            "the rendered layers.")
    else:
        step(56, "Rendering every map layer for the report...")
        try:
            from gee.report_maps import map_images
            imgs = map_images(lat, lon, radius, year)
        except Exception as e:
            imgs = []
            bundle["notes"].append(
                f"Satellite map images skipped: {e}")
    try:
        from gee.report_maps import budget_was_spent, missing_layers
        gaps = missing_layers(imgs) if with_maps else []
        if gaps and budget_was_spent():
            # A spent budget and a failed layer need different advice.
            bundle["notes"].append(
                f"Map rendering ran out of time after {len(imgs)} of "
                f"{len(imgs) + len(gaps)} layers, so these were not "
                f"drawn: " + ", ".join(gaps)
                + ". This is the radius, not a fault: each layer is "
                  "computed live over the whole circle, and "
                  f"{radius} km is a large area. Every number in this "
                  "report is unaffected. For the full set of maps, "
                  "rebuild at a smaller radius (20 km renders all of "
                  "them comfortably).")
        elif gaps:
            bundle["notes"].append(
                "Map layers Earth Engine could not render this run: "
                + ", ".join(gaps)
                + ". Everything else in the report is unaffected; "
                  "rebuild the report to retry them.")
    except Exception:
        pass
    if with_maps:
        try:
            from gis.vector_maps import vector_maps
            imgs = list(imgs) + vector_maps(
                lat, lon, radius,
                st.session_state.get("shc_map_metric", "n_low"))
        except Exception as e:
            bundle["notes"].append(
                f"Measured map images skipped: {e}")
    bundle["map_images"] = imgs or None
    if imgs:
        bundle["notes"].append(
            f"{len(imgs)} map layers rendered into this report.")

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
        # A capped table must say so in the report, not just on screen.
        cap = (bundle["insights_df"].attrs or {}).get("cap_note")
        if cap:
            bundle["notes"].append(cap)
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
            # District horticulture where published - finer than state.
            "horticulture_district": agri_data.rows_for_area(
                "horticulture_district", states, dists),
        }
    except Exception as e:
        bundle["allied"] = None
        bundle["notes"].append(f"Allied sectors skipped: {e}")

    # 11c. Measured soil test (Soil Health Card) + fertiliser guidance
    step(98, "Measured soil test & fertiliser guidance...")
    try:
        from core import allied, shc
        dists = allied.districts_touching(lat, lon, radius)
        rows = shc.for_districts(dists) if dists else None
        summary = shc.area_summary(rows) if rows is not None \
            and not rows.empty else None
        bundle["shc_summary"] = summary
        crop = st.session_state.get("fert_crop")
        if summary and not crop:
            crop = (shc.crops() or [None])[0]
        bundle["fertilizer"] = (
            shc.fertilizer_guidance(summary, crop) if summary and crop
            else None)
        bundle["fertilizer_crop"] = crop if bundle["fertilizer"] else None
    except Exception as e:
        bundle["shc_summary"] = None
        bundle["fertilizer"] = None
        bundle["notes"].append(f"Measured soil test skipped: {e}")

    # 11d. Land capability (SLUSI)
    try:
        from core import allied, soil_capability
        dists = allied.districts_touching(lat, lon, radius)
        bundle["capability"] = (
            soil_capability.for_districts(dists) if dists else None)
    except Exception:
        bundle["capability"] = None

    # 11e. Government coconut crop survey (measured ground records)
    try:
        from core import crop_survey
        bundle["coconut_survey"] = crop_survey.radius_summary(
            lat, lon, radius)
        bundle["coconut_villages"] = crop_survey.top_villages(
            lat=lat, lon=lon, radius_km=radius, top=0)
        det = (bundle.get("plantation") or {}).get("plantation_ac")
        bundle["coconut_validation"] = (
            crop_survey.validate_plantation(lat, lon, radius, det)
            if det is not None else None)
    except Exception:
        bundle["coconut_survey"] = None
        bundle["coconut_villages"] = None
        bundle["coconut_validation"] = None

    # 11f. Irrigation - how the land here is watered (district source
    # statistics) plus the satellite measurement of irrigated cropland.
    step(99, "Irrigation (source split + satellite)...")
    try:
        from core import allied, irrigation
        pairs = allied.districts_touching(lat, lon, radius) or []
        names = [d for _s, d in pairs]
        summary = irrigation.area_summary(names) if names else None
        bundle["irrigation"] = summary
        bundle["irrigation_note"] = irrigation.targeting_note(summary)
        bundle["irrigation_rank"] = (irrigation.rankings(names)
                                     if summary else None)
    except Exception as e:
        bundle["irrigation"] = None
        bundle["irrigation_note"] = None
        bundle["irrigation_rank"] = None
        bundle["notes"].append(f"Irrigation statistics skipped: {e}")

    try:
        from gee.irrigation import (irrigation_stats,
                                    source_split_note, verdict)
        st.session_state.irrigation_stats = irrigation_stats(
            lat, lon, radius, year)
        bundle["irrigation_sat"] = st.session_state.irrigation_stats
        bundle["irrigation_verdict"] = verdict(
            bundle["irrigation_sat"])
        bundle["irrigation_source_note"] = source_split_note(
            bundle["irrigation_sat"])
        try:
            from core import irrigation_validate as _iv
            bundle["irrigation_validation"] = _iv.compare(
                lat, lon, radius, bundle["irrigation_sat"])
        except Exception:
            bundle["irrigation_validation"] = None
    except Exception as e:
        bundle["irrigation_sat"] = None
        bundle["irrigation_verdict"] = None
        bundle["notes"].append(f"Satellite irrigation skipped: {e}")

    # Village-level irrigation: every village polygon measured on its
    # own, because the government source split is district-only.
    step(99, "Irrigation village by village...")
    try:
        from gee.village_irrigation import summary as _vsum
        from gee.village_irrigation import village_irrigation
        vdf = village_irrigation(lat, lon, radius, year)
        bundle["irrigation_villages"] = vdf
        bundle["irrigation_villages_summary"] = _vsum(vdf)
    except Exception as e:
        bundle["irrigation_villages"] = None
        bundle["irrigation_villages_summary"] = None
        bundle["notes"].append(f"Village irrigation skipped: {e}")

    # Forest vs farmland: strip natural forest out of the plantation
    # figure, and put the department's own crop numbers beside ours.
    step(99, "Separating forest from plantation...")
    try:
        from gee.forest import forest_stats
        from gee.forest import verdict as _fverdict
        bundle["forest"] = forest_stats(lat, lon, radius, year)
        bundle["forest_verdict"] = _fverdict(bundle["forest"])
    except Exception as e:
        bundle["forest"] = None
        bundle["forest_verdict"] = None
        bundle["notes"].append(f"Forest separation skipped: {e}")

    try:
        from core import crop_stats as _cs
        names = [d for _s, d in
                 (allied.districts_touching(lat, lon, radius) or [])]
        taluks = []
        try:
            from gis.spatial import villages_in_buffer
            _g = villages_in_buffer(lat, lon, radius)
            if _g is not None and not _g.empty and "sdtname" in _g:
                taluks = sorted({str(x) for x in _g["sdtname"]
                                 if str(x) not in ("nan", "None", "")})
        except Exception:
            pass
        det = (bundle.get("maize") or {}).get("maize_ac")
        bundle["dept_maize"] = _cs.compare_maize(names, det)
        bundle["dept_taluks"] = _cs.top_taluks(taluks) if taluks else None
        bundle["dept_crop_hint"] = (_cs.crop_hints(taluks)
                                    if taluks else None)
        bundle["dept_plantation"] = [
            r for r in _cs.plantation_production()
            if any(str(r["place"]).lower() == str(d).lower()
                   for d in names)] or None
    except Exception:
        bundle["dept_maize"] = None
        bundle["dept_taluks"] = None
        bundle["dept_crop_hint"] = None
        bundle["dept_plantation"] = None

    # Counted irrigation structures (Minor Irrigation Census) - neither
    # a district aggregate nor a satellite estimate.
    try:
        from core import mi_census
        if mi_census.available():
            names = [d for _s, d in
                     (allied.districts_touching(lat, lon, radius)
                      or [])]
            bundle["mi_census"] = mi_census.area_table(names)
            bundle["mi_census_level"] = mi_census.granularity()
            bundle["mi_census_note"] = mi_census.source_note()
        else:
            bundle["mi_census"] = None
            bundle["mi_census_note"] = mi_census.source_note()
    except Exception:
        bundle["mi_census"] = None
        bundle["mi_census_note"] = None

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
        map_images=bundle.get("map_images"),
        # everything the screen shows that used to be left out
        ndvi_df=bundle.get("ndvi_df"),
        rain_df=bundle.get("rain_df"),
        forecast_days=bundle.get("forecast_days"),
        soil_profile=bundle.get("soil_profile"),
        maize=bundle.get("maize"),
        aquaculture=bundle.get("aquaculture"),
        shc_summary=bundle.get("shc_summary"),
        fertilizer=bundle.get("fertilizer"),
        fertilizer_crop=bundle.get("fertilizer_crop"),
        capability=bundle.get("capability"),
        coconut_survey=bundle.get("coconut_survey"),
        coconut_villages=bundle.get("coconut_villages"),
        coconut_validation=bundle.get("coconut_validation"),
        gt_df=bundle.get("gt_df"),
        cards_df=bundle.get("cards_df"),
        notes=bundle.get("notes"),
        irrigation=bundle.get("irrigation"),
        irrigation_note=bundle.get("irrigation_note"),
        irrigation_rank=bundle.get("irrigation_rank"),
        irrigation_sat=bundle.get("irrigation_sat"),
        irrigation_verdict=bundle.get("irrigation_verdict"),
        irrigation_source_note=bundle.get("irrigation_source_note"),
        irrigation_validation=bundle.get("irrigation_validation"),
        irrigation_villages=bundle.get("irrigation_villages"),
        irrigation_villages_summary=bundle.get(
            "irrigation_villages_summary"),
        forest=bundle.get("forest"),
        forest_verdict=bundle.get("forest_verdict"),
        dept_maize=bundle.get("dept_maize"),
        dept_taluks=bundle.get("dept_taluks"),
        dept_crop_hint=bundle.get("dept_crop_hint"),
        dept_plantation=bundle.get("dept_plantation"),
        mi_census=bundle.get("mi_census"),
        mi_census_level=bundle.get("mi_census_level"),
        mi_census_note=bundle.get("mi_census_note"),
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

    coconut_villages = bundle.get("coconut_villages")
    if coconut_villages:
        coconut_villages = pd.DataFrame(coconut_villages)

    # --- Irrigation sheets: the source split per district, the same
    # split for the area in view, and the satellite measurement. ---
    irr = bundle.get("irrigation")
    irr_area = None
    if irr:
        rows = [
            ("Districts in view", ", ".join(irr.get("districts", []))),
            ("Net irrigated area (ha)", irr.get("net_ha")),
            ("Net irrigated area (acres)", irr.get("net_ac")),
            ("Gross irrigated area (ha)", irr.get("gross_ha")),
            ("Gross : net (irrigated seasons)", irr.get("intensity")),
            ("Borewell / tubewell share %", irr.get("borewell_pct")),
            ("Canal share %", irr.get("canal_pct")),
            ("Dominant source", irr.get("dominant")),
            ("Data vintage", irr.get("vintage")),
            ("How to target field staff here",
             bundle.get("irrigation_note")),
        ]
        for col, label in (
                [("Borewell/Tubewell", "Borewell / tubewell"),
                 ("Canal (Government)", "Canal (government)"),
                 ("Canal (Private)", "Canal (private)"),
                 ("Open/Dug Well", "Open / dug well"),
                 ("Tank", "Tank"),
                 ("Other Source", "Other (mostly lift)")]):
            rows.append((f"{label} - area (ha)",
                         (irr.get("sources") or {}).get(col)))
            rows.append((f"{label} - share %",
                         (irr.get("shares") or {}).get(col)))
        irr_area = pd.DataFrame(rows, columns=["Measure", "Value"])

    irr_rank = bundle.get("irrigation_rank")
    if irr_rank:
        irr_rank = pd.DataFrame(irr_rank)

    irr_sat = None
    s = bundle.get("irrigation_sat")
    if s:
        labels = [
            ("cropland_ac", "Cropland in area (ac)"),
            ("summer_green_ac",
             "Irrigated - summer green Feb-May (ac)"),
            ("summer_green_pct", "Irrigated share of cropland (%)"),
            ("multicrop_ac", "Multi-crop 2+ crops/yr (ac)"),
            ("lgrip_irrigated_ac", "LGRIP30 irrigated (ac)"),
            ("lgrip_rainfed_ac", "LGRIP30 rain-fed (ac)"),
            ("worldcereal_irrigated_ac",
             "WorldCereal irrigation - lower bound (ac)"),
            ("confirmed_ac",
             "Two methods agree - summer green + LGRIP30 (ac)"),
            ("evidence_2plus_ac", "TWO OR MORE methods agree (ac)"),
            ("evidence_3plus_ac", "THREE OR MORE methods agree (ac)"),
            ("s1_event_ac", "Radar irrigation events, Feb-May (ac)"),
            ("surface_fed_ac", "Canal/tank-fed, inferred (ac)"),
            ("groundwater_fed_ac", "Borewell-fed, inferred (ac)"),
            ("vertisol_ac", "Black cotton soil in cropland (ac)"),
        ]
        rows = [(lab, s.get(k)) for k, lab in labels]
        # An agreement count is only meaningful next to how many
        # methods ran, so the report carries both or neither.
        ok = s.get("methods_ok") or []
        failed = s.get("methods_failed") or {}
        if ok or failed:
            rows.append(("Methods that ran",
                         f"{len(ok)} of 5"))
            if ok:
                rows.append(("  - ran", "; ".join(ok)))
            for name, why in failed.items():
                rows.append((f"  - did NOT run: {name}", str(why)[:200]))
        rows.append(("Verdict", bundle.get("irrigation_verdict")))
        z = (s.get("zone") or {})
        rows.append(("Agro-climatic zone", z.get("label")))
        rows.append(("Expected accuracy in this zone",
                     z.get("accuracy")))
        th = (s.get("thresholds") or {})
        rows.append(("NDVI threshold used", th.get("ndvi")))
        rows.append(("NDMI threshold used", th.get("ndmi")))
        rows.append(("Water-source check",
                     bundle.get("irrigation_source_note")))
        chk = bundle.get("irrigation_validation") or {}
        if chk:
            rows.append(("Crop-survey cross-check - satellite %",
                         chk.get("satellite_pct")))
            rows.append(("Crop-survey cross-check - survey %",
                         chk.get("survey_pct")))
            rows.append(("Cross-check reading", chk.get("reading")))
        irr_sat = pd.DataFrame(rows, columns=["Measure", "Value"])

    # Every Karnataka district, so the workbook is useful on its own.
    irr_all = None
    try:
        from core import irrigation as _ir
        if _ir.available():
            irr_all = pd.DataFrame(_ir.rankings())
    except Exception:
        irr_all = None

    shc_rows = None
    s = bundle.get("shc_summary")
    if s:
        rows = [("Cycle", s.get("cycle")),
                ("Samples", s.get("samples"))]
        for _, m in (s.get("macros") or {}).items():
            rows.append((f"{m['label']} - % Low", m["low"]))
            rows.append((f"{m['label']} - dominant", m["dominant"]))
        for _, m in (s.get("micros") or {}).items():
            rows.append((f"{m['label']} - % deficient",
                         m["deficient_pct"]))
        shc_rows = pd.DataFrame(rows, columns=["Measure", "Value"])

    fert_rows = None
    f = bundle.get("fertilizer")
    if f:
        fert_rows = pd.DataFrame(f.get("rows", []))

    sheets = [
        ("Summary", summary),
        ("Land Cover", bundle.get("landcover_df")),
        ("Coconut Survey", coconut_villages),
        ("Measured Soil (SHC)", shc_rows),
        ("Fertiliser Guidance", fert_rows),
        ("Irrigation - Area", irr_area),
        ("Irrigation - Districts", irr_rank),
        ("Irrigation - Satellite", irr_sat),
        ("Irrigation - All Karnataka", irr_all),
        ("Irrigation - By Village", bundle.get("irrigation_villages")),
        ("Forest vs Plantation",
         (pd.DataFrame(list(bundle["forest"].items()),
                       columns=["Measure", "Value"])
          if bundle.get("forest") else None)),
        ("Dept Crop Figures",
         (pd.DataFrame(bundle["dept_taluks"])
          if bundle.get("dept_taluks") else None)),
        ("Dept Plantation Output",
         (pd.DataFrame(bundle["dept_plantation"])
          if bundle.get("dept_plantation") else None)),
        ("Irrigation - Well Census",
         (pd.DataFrame(bundle["mi_census"])
          if bundle.get("mi_census") else None)),
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
