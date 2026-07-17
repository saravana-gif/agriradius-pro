"""Results dashboard - tabbed: Summary / Villages / Charts / Downloads."""

import streamlit as st
import pandas as pd
import plotly.express as px

from gis.village_search import get_villages
from core.export import excel_report


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


def _downloads_tab(df):

    villages = _villages_df()

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


def results():

    st.subheader("🌾 Analysis Results")

    df = _landcover_df()

    tab_summary, tab_villages, tab_charts, tab_downloads = st.tabs(
        ["📊 Summary", "🏘️ Villages", "📈 Charts", "📥 Downloads"]
    )

    with tab_summary:
        _summary_tab(df)

    with tab_villages:
        _villages_tab()

    with tab_charts:
        _charts_tab(df)

    with tab_downloads:
        _downloads_tab(df)