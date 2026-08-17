"""Forest vs farmland panel - stops plantation figures counting forest.

Answers one question directly: of the tree canopy this app detected,
how much is actually natural forest, and how much is genuine tree-crop
land you could source from?

Also puts the Karnataka department's own crop numbers beside ours -
irrigated maize hectares per district, plantation-crop output, and the
leading taluks for banana, grapes, mango, onion and tomato - so the
satellite figures can be judged rather than trusted.
"""

import pandas as pd
import streamlit as st


def _districts_taluks(lat, lon, radius):
    dists, taluks = [], []
    try:
        from core import allied
        dists = [d for _s, d in
                 (allied.districts_touching(lat, lon, radius) or [])]
    except Exception:
        pass
    try:
        from gis.spatial import villages_in_buffer
        gdf = villages_in_buffer(lat, lon, radius)
        if gdf is not None and not gdf.empty and "sdtname" in gdf:
            taluks = sorted({str(t) for t in gdf["sdtname"]
                             if str(t) not in ("nan", "None", "")})
    except Exception:
        pass
    return dists, taluks


def _forest_block(lat, lon, radius, year):
    st.markdown("#### 🌳 How much of the 'plantation' is really forest?")
    st.caption(
        "The plantation detector looks for tree canopy that stays "
        "green through the dry season - which also describes a Western "
        "Ghats evergreen patch. The Forest Survey of India makes it "
        "worse by counting any canopy over 10% across 1 ha as forest "
        "*irrespective of land use*, so shade-grown coffee, arecanut "
        "gardens and coastal coconut all read as forest in the usual "
        "products. JRC Global Forest Cover 2020 is the one free layer "
        "that deliberately EXCLUDES agricultural plantations, so "
        "subtracting it leaves genuine tree-crop land.")

    key = f"forest_{round(lat, 3)}_{round(lon, 3)}_{radius}_{year}"
    if st.button("Separate forest from plantation here",
                 key="forest_run"):
        try:
            from gee.forest import forest_stats
            with st.spinner("Measuring forest, farmland trees and "
                            "plantation net of forest..."):
                st.session_state[key] = forest_stats(
                    lat, lon, radius, year)
        except Exception as e:
            st.warning(f"Forest separation failed: {e}")
            return

    s = st.session_state.get(key)
    if not s:
        st.info(
            "Press the button to run it. This is the correction that "
            "matters most in Malnad, Kodagu, Shivamogga, Chikkamagaluru "
            "and the coastal belt, where natural forest and tree crops "
            "sit side by side.")
        return

    from gee.forest import verdict
    v = verdict(s)
    if v:
        st.success(v)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Plantation detected (gross)",
              f"{(s.get('plantation_gross_ac') or 0):,.0f} ac")
    c2.metric("Forest removed",
              f"{(s.get('forest_removed_ac') or 0):,.0f} ac",
              delta=(f"-{s['forest_removed_pct']}%"
                     if s.get("forest_removed_pct") else None),
              delta_color="inverse")
    c3.metric("Plantation NET of forest",
              f"{(s.get('plantation_net_ac') or 0):,.0f} ac",
              help="Use this figure for sourcing, not the gross one.")
    c4.metric("Farmland trees (tree crops)",
              f"{(s.get('farmland_trees_ac') or 0):,.0f} ac",
              help="Canopy that GFC2020 excludes from forest - in "
                   "Karnataka overwhelmingly arecanut, coconut, "
                   "coffee, mango, cashew, rubber and woodlots.")

    rows = [
        ["Forest cover (GFC2020, tree crops excluded)",
         s.get("forest_ac"),
         "The mask being subtracted. 10 m, 2020."],
        ["- naturally regenerating / primary",
         s.get("natural_forest_ac"),
         "GFC2020 subtypes 1 and 10 - the EUDR reference class."],
        ["- planted forest",
         s.get("planted_forest_ac"),
         "Subtype 20. Timber/pulp plantations, not tree crops."],
        ["WRI SBTN natural lands", s.get("natural_lands_ac"),
         "Independent second opinion at 30 m."],
        ["Structurally uniform canopy", s.get("uniform_canopy_ac"),
         "Crop-height canopy planted on a regular grid - orchards are "
         "uniform, natural forest is not."],
    ]
    st.dataframe(
        pd.DataFrame(
            [[r[0], (f"{r[1]:,.0f} ac" if r[1] is not None else "n/a"),
              r[2]] for r in rows],
            columns=["Layer", "Area", "What it is"]),
        use_container_width=True, hide_index=True)

    st.caption(
        "⚠ No satellite product can tell you LEGAL forest status - "
        "ever. Only the Karnataka Forest Department's records settle "
        "whether a parcel is legally forest land.")


def _dept_block(lat, lon, radius):
    from core import crop_stats as cs

    if not cs.available():
        return

    st.markdown("#### 🏛️ The department's own crop numbers")
    dists, taluks = _districts_taluks(lat, lon, radius)

    maize_detected = (st.session_state.get("maize_stats") or {}).get(
        "maize_ac")
    cmp_ = cs.compare_maize(dists, maize_detected) if dists else None
    if cmp_:
        a, b, c = st.columns(3)
        a.metric("Maize detected here",
                 f"{cmp_['detected_ac']:,} ac")
        b.metric("Dept irrigated maize (district-wide)",
                 f"{cmp_['department_ac']:,} ac")
        c.metric("Detected vs department",
                 f"{cmp_['ratio_pct']}%")
        st.caption(f"{cmp_['reading']} {cmp_['caveat']} "
                   f"Districts: {', '.join(cmp_['districts'])} · "
                   f"{cmp_['vintage']}.")
    elif dists:
        m = cs.maize_area(dists)
        if m:
            st.caption(
                f"Department irrigated maize for "
                f"{', '.join(m['districts'])}: "
                f"**{m['area_ha']:,} ha** ({m['area_ac']:,} ac), "
                f"{m['year']}. Run the maize layer or detection to "
                f"compare it with ours.")

    hint = cs.crop_hints(taluks) if taluks else None
    if hint:
        st.info(f"**Which crop is it likely to be?** {hint}")

    tt = cs.top_taluks(taluks) if taluks else []
    if tt:
        st.markdown("**Leading crops in these taluks**")
        st.dataframe(pd.DataFrame(tt), use_container_width=True,
                     hide_index=True)

    plant = [r for r in cs.plantation_production()
             if any(str(r["place"]).lower() == str(d).lower()
                    for d in dists)]
    if plant:
        st.markdown("**Plantation-crop output for these districts**")
        st.dataframe(pd.DataFrame(plant), use_container_width=True,
                     hide_index=True)
        st.caption(
            "Output, not area - useful for sizing a procurement "
            "opportunity against the acreage the satellite finds.")


def forest_panel():
    """Rendered under the map. Quiet until there is something to say."""
    try:
        lat = float(st.session_state.lat)
        lon = float(st.session_state.lon)
        radius = float(st.session_state.get("radius", 10) or 10)
        year = int(st.session_state.get("year", 2025))
    except (TypeError, ValueError, AttributeError):
        return

    with st.expander("🌳 Forest vs farmland - and the department's crop "
                     "figures", expanded=False):
        _forest_block(lat, lon, radius, year)
        st.divider()
        _dept_block(lat, lon, radius)
