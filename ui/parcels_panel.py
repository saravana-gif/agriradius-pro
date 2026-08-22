"""Field parcels panel - individual fields inside the analysis circle.

This is the answer to "why don't we have field boundary data": the
app now draws the actual parcels, not just a circle. What it cannot
do is attach a survey number to them - see the caveat, which travels
with every figure here rather than sitting in a footnote.
"""

import contextlib

import streamlit as st


def _L(text):
    """Bilingual label - Kannada/Tamil with the English kept alongside."""
    try:
        from core.lang import bilingual
        return bilingual(text)
    except Exception:
        return text



def parcels_body(as_tab=False):
    """Render the panel. as_tab=True skips the expander wrapper."""
    from core import field_boundaries as fb

    box = (contextlib.nullcontext() if as_tab
           else st.expander("🔲 Field parcels (individual fields)"))
    with box:
        if as_tab:
            st.markdown("### 🔲 Field parcels in this circle")
        st.caption(
            "Individual agricultural fields from Fields of The World "
            "(FTW) - a global 10 m field-boundary map built by running "
            "a segmentation model over Sentinel-2. Open data, "
            "CC-BY-4.0.")

        if not fb.available():
            _setup_block(fb)
            return

        lat, lon, radius, year = _inputs()
        if lat is None:
            st.info("Search or mark an area first.")
            return

        # Never automatic: a 38 km read is heavy and the tab body
        # runs on every Streamlit rerun.
        key = f"parcels_{lat:.4f}_{lon:.4f}_{radius}"
        run = st.button("Load field parcels for this area",
                        key="parcels_run")
        if not run and key not in st.session_state:
            st.info(
                "Press the button to fetch the individual field "
                "boundaries inside this circle. It reads only the "
                "bytes it needs, so it is quick, but it is on demand "
                "rather than automatic.")
            _show_caveat(fb)
            return

        if run or key not in st.session_state:
            conf = st.session_state.get("parcels_min_conf", 0)
            with st.spinner("Reading field parcels..."):
                gdf, info = fb.parcels(lat, lon, radius, year=None,
                                       min_confidence=conf)
            st.session_state[key] = (gdf, info)

        gdf, info = st.session_state[key]
        s = fb.summary(gdf, info)

        if s["parcels"] == 0:
            st.warning(info.get("note") or "No parcels returned.")
            _show_caveat(fb)
            return

        if info.get("capped"):
            st.warning(info["note"])
        elif info.get("note"):
            st.info(info["note"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(_L("Field parcels"), f"{s['parcels']:,}")
        c2.metric(_L("Total parcel area"),
                  f"{(s['total_ac'] or 0):,.0f} ac",
                  help="Sum of the parcels found. Compare this with "
                       "the cropland figure in Summary - they measure "
                       "different things and rarely match exactly.")
        c3.metric(_L("Median parcel size"),
                  f"{s['median_ac']} ac" if s['median_ac'] else "n/a",
                  help="Half the fields are smaller than this. The "
                       "number that tells you whether you are dealing "
                       "with smallholders or estates.")
        c4.metric("Model confidence (median)",
                  f"{s['confidence_median']}"
                  if s['confidence_median'] is not None else "n/a",
                  help="0-100. FTW's own confidence layer is "
                       "conservative for smallholder systems, so a "
                       "low score here does NOT mean the fields are "
                       "not real.")

        if s.get("p90_ac"):
            st.caption(
                f"90% of parcels are under {s['p90_ac']} ac. "
                f"{_holding_read(s)}")

        _show_caveat(fb)
        _kgis_block(gdf)

        with st.expander("Parcel size distribution"):
            try:
                import pandas as pd
                ac = _acres(gdf)
                bins = [0, 0.5, 1, 2, 5, 10, 25, 1e9]
                labels = ["<0.5 ac", "0.5-1", "1-2", "2-5", "5-10",
                          "10-25", "25+ ac"]
                cut = pd.cut(ac, bins=bins, labels=labels,
                             right=False)
                tab = (cut.value_counts().reindex(labels)
                       .rename_axis("Parcel size")
                       .reset_index(name="Parcels"))
                st.dataframe(tab, use_container_width=True,
                             hide_index=True)
            except Exception as e:
                st.caption(f"Distribution unavailable: {e}")


def _kgis_block(ftw_gdf):
    """Attach survey numbers, if K-GIS access has been configured."""
    from core import kgis

    st.divider()
    st.markdown("#### 🧾 Survey numbers (Karnataka K-GIS)")

    if not kgis.available():
        st.info(
            "FTW gives you the SHAPE of each field. Only the Karnataka "
            "revenue record gives it a SURVEY NUMBER - and that is the "
            "key your crop-survey data already uses. K-GIS (KSRSAC) "
            "holds exactly that: survey number with village, taluk and "
            "district codes. It has no public endpoint, so OneRoot "
            "needs to request one.")
        with st.expander("Request access - ready-to-send email"):
            st.caption(
                f"Addressed to **{kgis.KSRSAC_SUPPORT}**, replies to "
                f"**{kgis.CONTACT_EMAIL}**. Copy it as it stands, or "
                f"edit first - it asks for the endpoint, the field "
                f"names and the access terms in one go, so KSRSAC can "
                f"answer everything in a single reply.")
            st.code(kgis.request_draft(), language="text")
            st.caption(
                "Two things worth knowing before you send: only about "
                "**58% of Karnataka's hissa maps are georeferenced** "
                "so far, and the cadastral layer is not open data - "
                "expect terms, and possibly an MoU, attached.")
        with st.form("kgis_cfg"):
            st.caption("Paste the endpoint here once you have it.")
            url = st.text_input(
                "K-GIS service URL",
                placeholder="https://.../FeatureServer/0  or  "
                            "https://.../wfs")
            layer = st.text_input("Layer / typeName (WFS only)",
                                  placeholder="cadastral:survey")
            token = st.text_input("Token, if required", type="password")
            if st.form_submit_button("Save K-GIS endpoint") and url:
                kgis.configure(url, token=token or None,
                               layer=layer or None)
                st.success("Saved. Reload and load parcels again.")
        return

    if not st.button("Attach survey numbers", key="kgis_join"):
        st.caption(
            "K-GIS is configured. Press to fetch survey-number "
            "parcels for this circle and match them to the fields "
            "above.")
        return

    lat, lon, radius, _ = _inputs()
    with st.spinner("Querying K-GIS cadastral..."):
        kg, info = kgis.parcels(lat, lon, radius)
    if info.get("note"):
        st.warning(info["note"])
    if len(kg) == 0:
        return

    st.success(f"{len(kg):,} survey-number parcels returned.")
    joined, msg = kgis.join_to_ftw(ftw_gdf, kg)
    st.caption(msg)
    try:
        cols = [c for c in ("survey_no", "village", "taluk",
                            "survey_overlap", "area_m2")
                if c in joined.columns]
        st.dataframe(joined[cols].head(200),
                     use_container_width=True, hide_index=True)
        st.session_state.parcels_with_survey = joined
    except Exception as e:
        st.caption(f"Table unavailable: {e}")


def _acres(gdf):
    SQM = 4046.8564224
    if "area_m2" in gdf.columns and gdf["area_m2"].notna().any():
        return gdf["area_m2"] / SQM
    return gdf.to_crs(gdf.estimate_utm_crs()).area / SQM


def _holding_read(s):
    """One plain sentence on what the size profile means."""
    m = s.get("median_ac") or 0
    if m and m < 1:
        return ("That is smallholder country - expect many owners "
                "per village and aggregation to be the hard part.")
    if m and m < 2.5:
        return ("Typical South Indian smallholding. Sourcing means "
                "many small conversations, not a few big ones.")
    if m:
        return ("Larger holdings than the South Indian norm - fewer "
                "owners for the same volume.")
    return ""


def _inputs():
    try:
        return (float(st.session_state.lat),
                float(st.session_state.lon),
                float(st.session_state.get("radius", 10) or 10),
                int(st.session_state.get("year", 2025)))
    except Exception:
        return None, None, None, None


def _show_caveat(fb):
    st.caption("⚠ " + fb.caveat())


def _setup_block(fb):
    """First run on a server: probe for the dataset, show the log."""
    st.info(
        "Field parcels are not set up on this server yet. The FTW "
        "dataset is public and needs no key - press below and the "
        "server will locate the India partition once and remember it.")
    if not st.button("Find field parcel data", key="ftw_discover"):
        return
    with st.spinner("Probing the FTW catalogue..."):
        info = fb.discover()
    if info.get("ok"):
        files = info.get("files") or []
        st.success(
            f"Found it - {len(files)} India file"
            f"{'s' if len(files) != 1 else ''}, "
            f"{len(info.get('columns') or [])} columns. Field parcels "
            f"are now available; press 'Load field parcels' above.")
        with st.expander(f"The {len(files)} file(s) it will read"):
            for u in files[:40]:
                st.caption(u.rsplit("/", 1)[-1])
            if len(files) > 40:
                st.caption(f"... and {len(files) - 40} more")
    else:
        st.error(info.get("error") or "Probe failed.")
    with st.expander("What the probe tried"):
        for row in info.get("tried") or []:
            st.markdown(f"- `{row['glob']}` → {row['result']}")
        st.caption(
            "If every path failed, the dataset layout has changed. "
            "The paths above are what to check against "
            "https://source.coop/ftw/global-data")
