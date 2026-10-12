"""30-second field report, for an officer's phone.

GPS (one tap) -> nearest watched village -> what happened -> save.
Plus the 7-day check-back: "was the alert right?" Yes / Partly / No.
Saves to the Sheet tab FieldReports (or the server CSV); the morning
job copies it into the store. No Earth Engine.
"""

import datetime

import streamlit as st

from core import field_reports as fr
from core import store

IST = fr.IST
CROPS = ["turmeric", "maize", "banana", "chilli", "tender coconut",
         "coconut", "ragi", "paddy", "sugarcane", "other"]


@st.cache_data(ttl=300, show_spinner=False)
def _villages():
    df = store.query("SELECT village_id, village, district, state, lat, "
                     "lon, crops FROM villages ORDER BY village")
    if df.empty:
        from core import watched_villages
        df, _ = watched_villages.load()
    return df.to_dict("records")


@st.cache_data(ttl=60, show_spinner=False)
def _submitted():
    rows, _ = fr.read_all()
    return rows


def _officer():
    return (st.session_state.get("user") or {}).get("email", "")


def _gps():
    if st.button("📍 Use my location", use_container_width=True,
                 type="primary"):
        st.session_state.fr_gps = True
    if not st.session_state.get("fr_gps"):
        return None
    try:
        from streamlit_js_eval import get_geolocation
        loc = get_geolocation()
    except Exception:
        loc = None
    if loc and loc.get("coords"):
        c = loc["coords"]
        return c.get("latitude"), c.get("longitude"), c.get("accuracy")
    st.caption("Waiting for the phone's location - allow it when asked. "
               "No signal? Pick the village below.")
    return None


def _pick_village(villages, gps):
    by_id = {v["village_id"]: v for v in villages}
    order = [v["village_id"] for v in villages]
    dist = {}
    if gps and gps[0] is not None:
        near = fr.nearest(villages, gps[0], gps[1])
        dist = {v["village_id"]: d for d, v in near}
        order = [v["village_id"] for _, v in near]
        d0, v0 = near[0]
        acc = f" (GPS ±{gps[2]:.0f} m)" if gps[2] else ""
        if d0 <= fr.SNAP_KM:
            st.success(f"Nearest watched village: **{v0['village']}**, "
                       f"{d0} km{acc}")
        else:
            st.warning(f"No watched village within {fr.SNAP_KM:.0f} km "
                       f"(nearest {v0['village']}, {d0} km). Pick the "
                       "village this report is about.")
    vid = st.selectbox(
        "Village", order,
        format_func=lambda i: by_id[i]["village"] + (
            f" - {dist[i]} km" if i in dist else ""))
    return by_id[vid], dist.get(vid)


def _report_form(village, dist, gps):
    crops_here = [c.strip() for c in str(village.get("crops") or "")
                  .replace(",", ";").split(";") if c.strip()]
    crop_opts = crops_here + [c for c in CROPS if c not in crops_here]
    events = [k for k in fr.EVENTS if k != "checkback"]
    ev = st.radio("What happened?", events, horizontal=True,
                  format_func=lambda k: fr.EVENTS[k][0])
    alert_id = verdict = ""
    if ev == "feedback":
        since = datetime.date.today() - datetime.timedelta(days=30)
        al = store.recent_alerts(since, village["village_id"])
        if al.empty:
            st.info("No alerts for this village in the last 30 days.")
            return
        alert_id = st.selectbox(
            "Which alert?", al["alert_id"].tolist(),
            format_func=lambda a: f"{a} - " + al.set_index("alert_id")
            .loc[a, "title"])
        verdict = st.radio("Was it right?", fr.VERDICTS, horizontal=True,
                           format_func=str.capitalize)
    with st.form("field_report", clear_on_submit=True):
        crop = st.selectbox("Crop", [""] + crop_opts,
                            format_func=lambda c: c or "(not about a crop)")
        unit_default = fr.EVENTS[ev][1]
        c1, c2 = st.columns([2, 1])
        qty = c1.number_input("How much (optional)", min_value=0.0,
                              value=None, step=1.0)
        unit = c2.selectbox("Unit", fr.UNITS,
                            index=fr.UNITS.index(unit_default))
        photo = st.file_uploader("Photo (optional)",
                                 type=["jpg", "jpeg", "png"])
        note = st.text_input("Note (optional) - no farmer names or phone "
                             "numbers")
        ok = st.form_submit_button("💾 Save report", type="primary",
                                   use_container_width=True)
    if not ok:
        return
    lat = lon = acc = None
    if gps and gps[0] is not None:
        lat, lon, acc = gps
    try:
        row = fr.make_row(officer=_officer(), village=village, event=ev,
                          lat=lat, lon=lon, accuracy=acc, distance_km=dist,
                          crop=crop, qty=qty, unit=unit if qty else "",
                          alert_id=alert_id, verdict=verdict, note=note)
        if photo is not None:
            row["photo"] = fr.save_photo(row["report_id"], photo.getvalue())
        where = fr.save(row)
    except ValueError as e:
        st.error(str(e))
        return
    except Exception as e:
        st.error(f"Could not save: {type(e).__name__}. Try again; if it "
                 "keeps failing, note it on paper and tell the office.")
        return
    _submitted.clear()
    st.success(f"Saved ({row['report_id']}, {where}). Thank you.")


def _checkbacks():
    """Alerts 7-30 days old with no verdict yet."""
    today = datetime.datetime.now(IST).date()
    al = store.recent_alerts(today - datetime.timedelta(days=30))
    if al.empty:
        return
    al = al[(al["as_of"] <= (today - datetime.timedelta(days=7))
             .isoformat()) & al["verdict"].isna()]
    answered = {r.get("alert_id") for r in _submitted()
                if r.get("event") == "checkback"}
    al = al[~al["alert_id"].isin(answered)]
    st.subheader("✔️ Was it right?")
    if al.empty:
        st.caption("No alerts are waiting for a 7-day check.")
        return
    st.caption("A week after an alert, tell us how it went. This builds "
               "the hit rate shown at FPO meetings; rules right less than "
               "6 times in 10 are retired.")
    names = {v["village_id"]: v for v in _villages()}
    for _, a in al.iterrows():
        v = names.get(a["village_id"], {"village_id": a["village_id"],
                                        "village": a["village_id"]})
        st.markdown(f"**{a['title']}** - {v['village']} · {a['as_of']} · "
                    f"`{a['alert_id']}`")
        cols = st.columns(3)
        for col, verdict in zip(cols, fr.VERDICTS):
            if col.button(verdict.capitalize(),
                          key=f"cb-{a['alert_id']}-{verdict}",
                          use_container_width=True):
                row = fr.make_row(officer=_officer(), village=v,
                                  event="checkback",
                                  alert_id=a["alert_id"], verdict=verdict)
                fr.save(row)
                _submitted.clear()
                st.rerun()


def field_report_page():
    st.title("📝 Field report")
    st.caption("30 seconds: location, what happened, save. Reports feed "
               "the crop-stage clock, the weekly portfolio and the alert "
               "hit rate.")
    villages = _villages()
    if not villages:
        st.error("No watched villages yet - add them to the Villages tab.")
        return
    gps = _gps()
    village, dist = _pick_village(villages, gps)
    _report_form(village, dist, gps)
    st.divider()
    _checkbacks()
