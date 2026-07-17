import streamlit as st
import pandas as pd
import plotly.express as px


def results():

    st.subheader("🌾 Analysis Results")

    if st.session_state.results is None:
        st.info("Run an analysis to view results.")
        return

    df = pd.DataFrame(st.session_state.results)

    # ---------- KPI ----------
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

    # ---------- Table ----------
    st.subheader("Land Cover Statistics")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    left, right = st.columns(2)

    # ---------- Pie Chart ----------
    with left:

        fig = px.pie(
            df,
            values="Area (acres)",
            names="Land Cover",
            title="Land Cover Distribution"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

    # ---------- Bar Chart ----------
    with right:

        fig2 = px.bar(
            df,
            x="Land Cover",
            y="Area (acres)",
            title="Area by Land Cover"
        )

        st.plotly_chart(
            fig2,
            use_container_width=True
        )

    st.divider()

    # ---------- Download ----------
    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "📥 Download CSV",
        csv,
        file_name="LandCover_Report.csv",
        mime="text/csv",
        use_container_width=True
    )