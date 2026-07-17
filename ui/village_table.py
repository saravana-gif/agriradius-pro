"""Village table panel - lists all villages inside the buffer."""

import streamlit as st

from gis.village_search import get_villages


def village_table():

    with st.expander("🏘️ Villages in Buffer", expanded=False):

        try:
            df = get_villages(
                st.session_state.lat,
                st.session_state.lon,
                st.session_state.radius
            )
        except Exception as e:
            st.warning(f"Could not load villages: {e}")
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

        csv = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "📥 Download Village List",
            csv,
            file_name="Villages_In_Buffer.csv",
            mime="text/csv",
            use_container_width=True
        )