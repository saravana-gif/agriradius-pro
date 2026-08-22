"""Watchlist panel - save an area, come back, see what moved."""

import streamlit as st


def watchlist_body():
    from core import watchlist as W

    st.markdown("#### 👁 Watchlist")
    st.caption(
        "Save this area's headline figures, then compare on a later "
        "visit. Built for the fifteen areas a sourcing team returns "
        "to, rather than a one-off search.")

    c1, c2 = st.columns([3, 2])
    with c1:
        name = st.text_input(
            "Name for this area",
            value=st.session_state.get("search_location") or "",
            key="wl_name",
            placeholder="e.g. Chamarajanagar 38 km")
    with c2:
        st.write("")
        if st.button("📌 Save snapshot", use_container_width=True,
                     key="wl_save"):
            key, msg = W.save_snapshot(dict(st.session_state),
                                       name=name or None)
            (st.success if key else st.warning)(msg)

    saved = W.areas()
    if not saved:
        st.info(
            "No areas saved yet. Run an analysis, then press Save "
            "snapshot - the comparison needs at least two visits, "
            "ideally a season apart.")
        return

    labels = {
        f"{a['name']}  ({a['snapshots']} visit"
        f"{'s' if a['snapshots'] != 1 else ''})": a["key"]
        for a in saved
    }
    pick = st.selectbox("Compare a saved area", list(labels),
                        key="wl_pick")
    d = W.diff(labels[pick])
    if not d:
        return
    if d.get("note"):
        st.info(d["note"])
        return

    st.caption(
        f"{d['since'][:10]} → {d['until'][:10]}"
        + (f" · {d['days']} day{'s' if d['days'] != 1 else ''} apart"
           if d.get("days") is not None else ""))

    try:
        import pandas as pd
        rows = []
        for r in d["rows"]:
            rows.append({
                "Measure": r["label"],
                "Before": (f"{r['old']:,.0f}" if r["old"] is not None
                           else "not measured"),
                "Now": (f"{r['new']:,.0f}" if r["new"] is not None
                        else "not measured"),
                "Change": ("-" if r["delta"] is None
                           else f"{r['delta']:+,.0f} {r['unit']}"),
                "Reading": r["verdict"],
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
    except Exception as e:
        st.caption(f"Comparison table unavailable: {e}")

    moved = [r for r in d["rows"]
             if r["verdict"] not in ("no meaningful change",
                                     "not measured on both visits")]
    if moved:
        st.warning(
            "Moved since last visit: "
            + "; ".join(f"{r['label']} {r['verdict']}"
                        for r in moved))
    else:
        st.success("Nothing moved beyond measurement noise.")

    note = W.interpretation(d)
    if note:
        st.caption("⚠ " + note)
