"""Measured coconut panel - government crop survey, no satellite.

Renders under the map whenever the searched area falls inside the
districts covered by the bundled Karnataka coconut crop survey
(see core/crop_survey.py). Two jobs:

  1. show what the survey actually recorded on the ground here, and
  2. score the app's satellite plantation detection against it - the
     strongest accuracy check available anywhere in the app.
"""

import pandas as pd
import streamlit as st

from core import crop_survey


def _cross_check():
    """Satellite plantation detection vs the measured survey."""
    stats = st.session_state.get("plantation_stats") or {}
    detected = stats.get("plantation_ac")
    if detected is None:
        st.caption(
            "Run **Plantation Detection** in the Summary tab (or tick "
            "the Plantations map layer) to score the satellite "
            "detection against these measured records.")
        return

    try:
        v = crop_survey.validate_plantation(
            st.session_state.lat, st.session_state.lon,
            st.session_state.radius, detected)
    except Exception:
        return
    if not v:
        return

    st.markdown("**Satellite detection vs the measured survey**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Survey coconut land", f"{v['survey_ac']:,} ac")
    c2.metric("Satellite detected", f"{v['detected_ac']:,} ac")
    c3.metric("Detection vs survey", f"{v['ratio_pct']}%")
    st.caption(v["verdict"])


def coconut_survey_panel():
    """Expander with measured coconut records for the current area.

    Silent (renders nothing) when the area has no survey coverage, so
    it never adds noise outside the covered districts.
    """
    if not crop_survey.available():
        return

    try:
        lat = float(st.session_state.lat)
        lon = float(st.session_state.lon)
        radius = float(st.session_state.get("radius", 10) or 10)
    except (TypeError, ValueError, AttributeError):
        return

    try:
        summary = crop_survey.radius_summary(lat, lon, radius)
    except Exception:
        return
    if not summary:
        # Explain the gap rather than disappearing - the survey covers
        # six districts, and "no coverage" is not the same as "no
        # coconut here".
        st.caption(
            "🥥 **Measured coconut (crop survey)** - no recorded "
            "coconut plots inside this circle. The 2023-24 crop-survey "
            "extract loaded here covers Hassan, Mandya, Tumakuru, "
            "Ramanagara, Chitradurga and Mysuru; elsewhere use the "
            "satellite plantation layer instead.")
        return

    with st.expander(
            "🥥 Measured coconut - government crop survey "
            f"({summary['extent_ac']:,} ac recorded here)",
            expanded=False):

        st.caption(
            "Every coconut plot logged against its survey number in "
            "the Karnataka crop survey (2023-24 Kharif), matched to "
            "its village polygon and aggregated. Ground-recorded - "
            "this is what the satellite layers get measured against. "
            "Coverage: Hassan, Mandya, Tumakuru, Ramanagara, "
            "Chitradurga and Mysuru.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Coconut land recorded", f"{summary['extent_ac']:,} ac")
        c2.metric("Coconut plots", f"{summary['parcels']:,}")
        c3.metric("Growers", f"{summary['farmers']:,}")
        c4.metric("Villages", f"{summary['villages']:,}")

        if summary["irrigated_pct"] is not None:
            st.caption(
                f"{summary['irrigated_pct']}% of the recorded plots "
                f"are irrigated · districts in view: "
                f"{', '.join(summary['districts'])} · "
                f"{crop_survey.VINTAGE}.")

        _cross_check()

        rows = crop_survey.top_villages(
            lat=lat, lon=lon, radius_km=radius, top=40)
        if rows:
            st.markdown("**Villages ranked by recorded coconut land**")
            df = pd.DataFrame(rows)
            df.insert(0, "rank", range(1, len(df) + 1))
            st.dataframe(df, use_container_width=True,
                         hide_index=True, height=360)

        st.caption(
            "`coconut_ac` is each grower's recorded extent allocated "
            "across their plots, then summed per village - district "
            "totals line up with published coconut area. "
            "`intensity_pct` is that land as a share of the village "
            "area (capped at 100%). Tick the **Coconut - govt crop "
            "survey** map layer to see it painted village by village.")
