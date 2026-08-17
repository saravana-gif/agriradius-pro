"""Irrigation report - is the land here irrigated, and how?

Reads as a briefing, not a data dump. Four parts:

  1. What the government statistics say for the districts in view -
     total irrigated area and the SOURCE split (borewell / canal /
     tank / well), because the source decides how you find farms.
  2. How to target field staff here, spelled out.
  3. What the satellite says, cross-checked against the statistics -
     four independent methods, with agreement called out.
  4. The caveats and land-record terminology, so nobody over-reads it.
"""

import pandas as pd
import streamlit as st

from core import irrigation


def _source_chart(shares):
    """Horizontal bar of the source split - instantly readable."""
    rows = [(label, shares.get(col) or 0)
            for col, label in irrigation.SOURCES
            if (shares.get(col) or 0) > 0]
    if not rows:
        return
    df = pd.DataFrame(rows, columns=["Source", "Share %"]) \
        .set_index("Source")
    st.bar_chart(df, horizontal=True, height=210)


def _districts_in_view(lat, lon, radius):
    try:
        from core import allied
        pairs = allied.districts_touching(lat, lon, radius) or []
        return [d for _s, d in pairs]
    except Exception:
        return []


MAX_AUTO_RADIUS_KM = 30


def _village_block(lat, lon, radius, year):
    """Village-by-village irrigation - the finest level open data allows.

    Runs AUTOMATICALLY for the searched area (cached per area, so a
    re-render costs nothing). Very large circles still ask first,
    because hundreds of village polygons is the heaviest call in the
    app and the Earth Engine budget is shared.
    """
    st.markdown("#### 🏘️ Irrigation village by village")
    st.caption(
        "The government source split exists only per district. So each "
        "village's irrigated AREA is measured here from its own "
        "polygon - the same resolution as the SHC village layer. "
        "Village level is as fine as public data goes: survey-number "
        "irrigation lives only in the Bhoomi RTC/Pahani and the "
        "seasonal Crop Survey, neither of which has an open bulk API.")

    key = f"irr_villages_{round(lat, 3)}_{round(lon, 3)}_{radius}"

    auto = radius <= MAX_AUTO_RADIUS_KM
    run = st.button("Re-measure now" if key in st.session_state
                    else "Measure irrigation for every village here",
                    key="irr_vill_btn")

    if run or (auto and key not in st.session_state):
        try:
            from gee.village_irrigation import village_irrigation
            with st.spinner("Measuring each village polygon "
                            "(1-3 min the first time, then cached)..."):
                st.session_state[key] = village_irrigation(
                    lat, lon, radius, year)
        except Exception as e:
            st.session_state[key] = None
            st.warning(f"Village irrigation run failed: {e}")
            return
    elif not auto and key not in st.session_state:
        st.info(
            f"This circle is {radius:.0f} km - larger than the "
            f"{MAX_AUTO_RADIUS_KM} km auto-run limit, because village "
            f"measurement is the heaviest analysis here. Press the "
            f"button to run it anyway, or reduce the radius and it "
            f"runs by itself.")
        return

    df = st.session_state.get(key)
    if df is None or (hasattr(df, "empty") and df.empty):
        return

    _census_block(df)

    from gee.village_irrigation import summary as _vsum
    s = _vsum(df)
    if s:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Villages measured", f"{s['villages']:,}")
        c2.metric("Irrigated",
                  f"{s['irrigated_ac']:,} ac"
                  + (f" · {s['irrigated_pct']}%"
                     if s.get("irrigated_pct") is not None else ""))
        c3.metric("Likely borewell-fed",
                  f"{s['borewell_fed_ac']:,} ac")
        c4.metric("2+ methods agree", f"{s['agree_2plus_ac']:,} ac")
        st.caption(
            f"{s['heavily_irrigated_villages']} villages are 40%+ "
            f"irrigated; {s['rainfed_villages']} are effectively "
            f"rain-fed. Tick **Irrigation source by district** in the "
            f"sidebar and set *Irrigation resolution* to **Village "
            f"detail** to see this painted on the map."
            + (" Only the villages nearest the centre were measured "
               "(payload cap) - reduce the radius for full coverage."
               if s.get("truncated") else ""))

    st.dataframe(df, use_container_width=True, hide_index=True,
                 height=420)
    st.download_button(
        "📥 Village irrigation (CSV)",
        df.to_csv(index=False).encode(),
        file_name="irrigation_by_village.csv", mime="text/csv",
        key="irr_vill_dl")


def _census_block(vdf):
    """Counted irrigation structures (Minor Irrigation Census).

    The only irrigation evidence here that is neither a district
    aggregate nor a satellite estimate - enumerators counted the wells.
    Joined onto the villages just measured, where the census reaches
    village level.
    """
    from core import mi_census

    st.markdown("**Counted irrigation structures (Minor Irrigation "
                "Census)**")

    if not mi_census.available():
        st.caption(
            "Not harvested yet. " + mi_census.source_note()
            + " It reuses the data.gov.in key the mandi prices already "
              "use, so nothing new is needed.")
        if st.button("Harvest the Minor Irrigation Census now",
                     key="mi_fetch"):
            import subprocess
            import sys as _sys

            from config import PROJECT_ROOT
            from core.secrets import get as _secret

            import os
            env = dict(os.environ)
            k = _secret("DATA_GOV_API_KEY")
            if k:
                env["DATA_GOV_API_KEY"] = str(k)
            script = (PROJECT_ROOT / "scripts"
                      / "fetch_mi_census.py")
            with st.spinner("Paging data.gov.in - this resource has "
                            "~190k rows, so give it a few minutes..."):
                try:
                    proc = subprocess.run(
                        [_sys.executable, str(script)],
                        capture_output=True, text=True, timeout=900,
                        env=env)
                except Exception as e:
                    st.warning(f"Harvest failed: {e}")
                    return
            mi_census._load.cache_clear()
            if mi_census.available():
                st.success(mi_census.source_note())
            else:
                st.warning(
                    "data.gov.in returned nothing usable. "
                    + ((proc.stderr or "")[-400:] if proc else ""))
        return

    st.caption(mi_census.source_note()
               + f" · {mi_census.VINTAGE}")

    level = mi_census.granularity()
    if level == "village":
        lookup = mi_census.village_lookup()
        import re as _re

        def _k(s):
            return _re.sub(r"[^a-z0-9]", "", str(s or "").lower())

        rows = []
        for _, r in vdf.iterrows():
            hit = lookup.get((_k(r.get("village")),
                              _k(r.get("district")))) or \
                lookup.get((_k(r.get("village")), ""))
            if not hit:
                continue
            row = {"village": r.get("village"),
                   "district": r.get("district"),
                   "irrigated_ac": r.get("irrigated_ac")}
            row.update(hit)
            rows.append(row)
        if rows:
            st.dataframe(pd.DataFrame(rows),
                         use_container_width=True, hide_index=True,
                         height=300)
            st.caption(
                "Counted structures beside the measured irrigated "
                "area for the same village - two independent kinds of "
                "evidence. Many wells and little irrigated area can "
                "mean failed or disused borewells; the reverse "
                "suggests canal or tank water.")
        else:
            st.caption(
                "None of the villages measured here appear in the "
                "census extract - village names in the census often "
                "differ from the census-2011 boundary names.")
    else:
        dists = sorted({str(d) for d in vdf.get("district", [])
                        if str(d) not in ("nan", "None", "")})
        table = mi_census.area_table(dists)
        if table:
            st.dataframe(pd.DataFrame(table),
                         use_container_width=True, hide_index=True)
            st.caption(
                f"This census resource publishes at **{level}** level, "
                f"so it is shown at that level rather than pretending "
                f"to be per village.")


def _command_area_block():
    """Canal command areas - harvest them from here, no shell needed.

    India-WRIS publishes command areas through an ArcGIS service that
    only the server can page through. The server also tries this on
    every restart; this button is here so it can be forced and, more
    importantly, so the outcome is visible instead of silent.
    """
    from gis import command_area_layer as cal

    st.markdown("#### 🚰 Canal command areas (ayakat)")

    if cal.available():
        st.success(cal.source_note())
        st.caption(
            "Tick **Canal command areas (India-WRIS)** in the sidebar "
            "to draw them. Inside a command area, canal-irrigated "
            "farmland is located for free - no satellite, no land "
            "records. Worth using in Raichur, Yadgir, Mandya and "
            "Koppal; close to useless in Tumakuru or Chitradurga, "
            "where nearly all irrigation is borewell.")
        return

    st.caption(
        "Not harvested yet. The server fetches these itself on "
        "restart - it needs open internet and an Indian IP, which is "
        "why it cannot be done from a browser. Press below to run it "
        "now and see the result.")

    if not st.button("Harvest canal command areas now",
                     key="wris_fetch"):
        return

    import subprocess
    import sys

    from config import PROJECT_ROOT
    script = PROJECT_ROOT / "scripts" / "fetch_wris_command_areas.py"

    with st.spinner("Paging the India-WRIS service (up to 2 min)..."):
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            st.warning(
                "India-WRIS did not finish in time. The service is "
                "often slow - try again later; nothing else is "
                "affected.")
            return
        except Exception as e:
            st.warning(f"Could not run the harvester: {e}")
            return

    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    cal._load.cache_clear()

    if cal.available():
        st.success(f"Done. {cal.source_note()} Tick the layer in the "
                   f"sidebar to see it.")
    else:
        st.warning(
            "India-WRIS did not return any command-area polygons. It "
            "renames its layers periodically, so this needs a look at "
            "what the service currently publishes.")
    if out:
        with st.expander("Harvester output", expanded=False):
            st.code(out[-3000:])


def _satellite_block(lat, lon, radius, year, summary):
    st.markdown("#### 🛰️ What the satellite sees")
    st.caption(
        "Four independent methods. The one that matters most for "
        "Karnataka is the **February-May summer window**: nothing "
        "holds a green, moist canopy through a Karnataka summer "
        "without applied water. Rabi greenness is deliberately NOT "
        "used - rabi jowar and chickpea on black cotton soil in the "
        "north are rain-fed on stored vertisol moisture, and a rabi "
        "rule mislabels them as irrigated.")

    if not st.button("Measure irrigated area here (satellite)",
                     key="irr_sat_run"):
        stats = st.session_state.get("irrigation_stats")
        if not stats:
            st.info(
                "Press the button to run the four irrigation methods "
                "over this area. It uses the shared Earth Engine "
                "budget, so it is on demand rather than automatic.")
            return
    else:
        try:
            from gee.irrigation import irrigation_stats
            with st.spinner("Measuring irrigated cropland "
                            "(February-May window)..."):
                st.session_state.irrigation_stats = irrigation_stats(
                    lat, lon, radius, year)
        except Exception as e:
            st.warning(f"Satellite irrigation run failed: {e}")
            return

    stats = st.session_state.get("irrigation_stats")
    if not stats:
        return

    from gee.irrigation import source_split_note, verdict
    v = verdict(stats)
    if v:
        st.success(v)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cropland in area",
              f"{(stats.get('cropland_ac') or 0):,.0f} ac")
    c2.metric("Irrigated - summer green",
              f"{(stats.get('summer_green_ac') or 0):,.0f} ac",
              help="Green AND moist through Feb-May. Our primary "
                   "signal.")
    c3.metric("2+ methods agree",
              f"{(stats.get('evidence_2plus_ac') or 0):,.0f} ac",
              help="At least two of five independent methods call it "
                   "irrigated. This is the figure to quote.")
    c4.metric("3+ methods agree",
              f"{(stats.get('evidence_3plus_ac') or 0):,.0f} ac",
              help="Three or more agree - send someone here first.")

    # Water source and radar, the two additions that carry the hard
    # cases (borewell land, and cloudy coastal/Malnad districts).
    note = source_split_note(stats)
    if note:
        st.info(f"**Where the water comes from:** {note}")

    if stats.get("s1_event_ac") is not None:
        st.caption(
            f"Radar detected wetting events on "
            f"**{stats['s1_event_ac']:,.0f} ac** during Feb-May. "
            f"Sentinel-1 sees through cloud, so this is the method to "
            f"lean on in coastal Karnataka and Malnad where greenness "
            f"tells you nothing. Rule used: VV backscatter rise of "
            f"1 dB or more (~86% discrimination on 0.1-65 ha plots).")

    if stats.get("vertisol_ac"):
        st.caption(
            f"⚠ About {stats['vertisol_ac']:,.0f} ac of the cropland "
            f"here is clay-rich black cotton soil. Rabi crops on that "
            f"soil are commonly RAIN-FED on stored moisture - which is "
            f"exactly why this layer ignores rabi and uses the "
            f"February-May window.")

    rows = [
        ["Radar irrigation events (Sentinel-1)",
         stats.get("s1_event_ac"),
         "The only method here that works under cloud. ~86% "
         "discrimination in published work; carries the coastal and "
         "Malnad districts."],
        ["Summer green (ours, Feb-May)",
         stats.get("summer_green_ac"),
         "Primary signal. Best in the semi-arid interior; weakest on "
         "the coast and in Malnad where rain keeps everything green."],
        ["Multi-crop prior (GCI30)", stats.get("multicrop_ac"),
         "Two or more crops a year. Near-conclusive in the dry "
         "interior."],
        ["LGRIP30 irrigated (30 m)", stats.get("lgrip_irrigated_ac"),
         "USGS/NASA. Its 91% accuracy headline is CONTINENTAL US "
         "only; the India version is V001 (2015) with no published "
         "Indian accuracy. Class 0 includes inland water, so tanks "
         "and reservoirs are excluded, not rain-fed."],
        ["LGRIP30 rain-fed (30 m)", stats.get("lgrip_rainfed_ac"),
         "Published South Asia work reports rain-fed user's accuracy "
         "of only 63% - over a third of 'rain-fed' pixels are in fact "
         "irrigated, so treat this as a soft exclusion."],
        ["WorldCereal irrigation (10 m)",
         stats.get("worldcereal_irrigated_ac"),
         "LOWER BOUND only. ESA published no accuracy metrics, the "
         "training data is biased to centre-pivot systems, and it "
         "under-maps Asia."],
    ]
    df = pd.DataFrame(
        [[r[0], (f"{r[1]:,.0f} ac" if r[1] is not None else "n/a"),
          r[2]] for r in rows],
        columns=["Method", "Irrigated area", "How much to trust it"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # --- Accuracy: what to expect, and how it did against records ---
    st.markdown("#### 🎯 How accurate is this here?")
    try:
        from core import irrigation_validate as iv
        exp = iv.zone_expectation(summary.get("districts")
                                  if summary else [])
        st.caption(
            f"**Zone:** {exp['zone']} — expect **{exp['accuracy']}**. "
            f"{exp['note']}"
            + (" This circle straddles more than one zone ("
               + ", ".join(exp.get("zones_present") or [])
               + "), so the most conservative one is applied."
               if exp.get("mixed") else "")
            + f" Thresholds in use: NDVI ≥ {exp['ndvi_threshold']}, "
              f"NDMI ≥ {exp['ndmi_threshold']}.")

        chk = iv.compare(lat, lon, radius, stats)
        if chk:
            a, b, c = st.columns(3)
            a.metric("Satellite irrigated share",
                     f"{chk['satellite_pct']}%")
            b.metric("Crop-survey irrigated share",
                     f"{chk['survey_pct']}%")
            c.metric("Gap", f"{chk['gap_pct']:+.1f} pts")
            st.caption(
                f"{chk['reading']} Checked against "
                f"{chk['parcels']:,} surveyed coconut plots across "
                f"{chk['villages']} villages. {chk['caveat']}")
    except Exception:
        pass

    # Cross-check against the government statistics.
    if summary and summary.get("net_ac"):
        st.markdown("**Satellite vs government statistics**")
        sat = stats.get("summer_green_ac") or 0
        st.caption(
            f"Satellite finds **{sat:,.0f} ac** of irrigated cropland "
            f"inside this {radius:.0f} km circle. The Land Use "
            f"Statistics record **{summary['net_ac']:,} ac** net "
            f"irrigated across the whole of "
            f"{', '.join(summary['districts'])} - a much larger area, "
            f"so treat the district figure as context for the mix of "
            f"sources, not as a total for this circle.")


def irrigation_panel():
    """Rendered under the map. Silent outside Karnataka."""
    if not irrigation.available():
        return

    try:
        lat = float(st.session_state.lat)
        lon = float(st.session_state.lon)
        radius = float(st.session_state.get("radius", 10) or 10)
        year = int(st.session_state.get("year", 2025))
    except (TypeError, ValueError, AttributeError):
        return

    names = _districts_in_view(lat, lon, radius)
    summary = irrigation.area_summary(names) if names else None
    if not summary:
        return

    head = (f"({summary['net_ac']:,} ac net irrigated · "
            f"{summary['borewell_pct']:.0f}% borewell)"
            if summary.get("borewell_pct") is not None else "")

    with st.expander(f"💧 Irrigation - how this land is watered {head}",
                     expanded=False):

        st.caption(
            "District irrigation by SOURCE, from the Land Use "
            "Statistics (DES-Agri) 2022-23. Karnataka's net irrigated "
            "area is 5.04 million ha and 56.6% of it is "
            "borewell/tubewell - which is why the source split, not "
            "just the total, decides how you find irrigated farms.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Net irrigated", f"{summary['net_ac']:,} ac")
        c2.metric("Borewell share",
                  f"{summary['borewell_pct']:.0f}%"
                  if summary.get("borewell_pct") is not None else "-")
        c3.metric("Canal share",
                  f"{summary['canal_pct']:.0f}%"
                  if summary.get("canal_pct") is not None else "-")
        c4.metric("Gross : net",
                  f"{summary['intensity']}x"
                  if summary.get("intensity") else "-",
                  help="Gross irrigated area divided by net - how "
                       "many irrigated seasons the same land carries.")

        note = irrigation.targeting_note(summary)
        if note:
            st.info(f"**How to target field staff here:** {note}")

        st.markdown("#### 💠 Where the water comes from")
        _source_chart(summary.get("shares") or {})

        st.markdown("#### 🏛️ District detail")
        rank = irrigation.rankings(names)
        if rank:
            st.dataframe(pd.DataFrame(rank), use_container_width=True,
                         hide_index=True)
        st.caption(
            f"Districts in view: {', '.join(summary['districts'])} · "
            f"{irrigation.VINTAGE}.")

        st.divider()
        _village_block(lat, lon, radius, year)

        st.divider()
        _command_area_block()

        st.divider()
        _satellite_block(lat, lon, radius, year, summary)

        st.divider()
        with st.expander("How far to trust this, and the land-record "
                         "words you will meet", expanded=False):
            for c in irrigation.CAVEATS:
                st.markdown(f"- {c}")
            st.markdown("**Land-record terminology**")
            st.dataframe(
                pd.DataFrame(irrigation.GLOSSARY,
                             columns=["Term", "Meaning"]),
                use_container_width=True, hide_index=True)
