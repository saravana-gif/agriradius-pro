"""Alerts & share kit page: read the morning's alerts, get the card,
WhatsApp text and voice script for signed-off ones.

Reads the job store only - no Earth Engine, nothing computed here
except drawing the card image.
"""

import datetime
import json

import pandas as pd
import streamlit as st

from core import share, store

SEV_ICON = {"red": "🔴", "amber": "🟠", "green": "🟢"}
STATE_LANG = {"Karnataka": "kn", "Tamil Nadu": "ta"}


@st.cache_data(ttl=300, show_spinner=False)
def _alerts(days):
    since = datetime.date.today() - datetime.timedelta(days=days)
    df = store.recent_alerts(since)
    v = store.query("SELECT village_id, village, state FROM villages")
    if df.empty:
        return df
    return df.merge(v, on="village_id", how="left")


@st.cache_data(ttl=300, show_spinner=False)
def _templates(mtime):
    return share.load_templates()


@st.cache_data(max_entries=200, show_spinner=False)
def _card(alert_json, lang, mtime):
    a = json.loads(alert_json)
    t, labels, _ = _templates(mtime)
    k = share.kit(a, lang, t, labels)
    return k, share.card_png(k)


def _actor():
    return (st.session_state.get("user") or {}).get("email", "unknown")


def _kit_tab(a, lang, mtime):
    try:
        k, png = _card(json.dumps(a, default=str), lang, mtime)
    except share.ShareError as e:
        st.error(str(e))
        return
    st.image(png, use_container_width=True)
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Card (PNG)", png, file_name=f"{a['alert_id']}"
                       f"-{k.lang}.png", mime="image/png",
                       key=f"dl-{a['alert_id']}-{lang}",
                       use_container_width=True)
    if k.shareable:
        c2.link_button("📲 Share on WhatsApp", k.wa_url,
                       use_container_width=True)
        if st.button("✅ I shared this", key=f"sh-{a['alert_id']}-{lang}"):
            store.add_alert_event(a["alert_id"], "shared", _actor(),
                                  {"lang": k.lang})
            st.success("Logged. Thank you - the 7-day check-back will "
                       "ask how it went.")
    else:
        c2.warning("Not shareable yet: " + k.why_not)
    st.markdown(f"**Voice-note script** (≈{k.voice_seconds} s - record "
                "it in your own voice):")
    st.text_area("voice", k.voice, height=180, label_visibility="collapsed",
                 key=f"v-{a['alert_id']}-{lang}")
    with st.expander("WhatsApp text"):
        st.code(k.message, language=None)


def _links():
    """Links to the static pages written by jobs/publish.py."""
    from jobs.publish import INDEX_FILE
    try:
        idx = json.loads(INDEX_FILE.read_text())
    except (OSError, ValueError):
        return
    with st.expander("🔗 Village pages and the weekly portfolio"):
        st.markdown(
            f"**[Weekly portfolio]({idx['portfolio']})** - internal: "
            "includes drafts and mandi prices, don't forward.")
        st.caption("Village pages open on 2G without signing in and show "
                   "only signed-off advice. Anyone with a link can read "
                   "it - share a village's link with that village only.")
        for vid, v in sorted(idx["villages"].items(),
                             key=lambda kv: kv[1]["village"]):
            st.markdown(f"- [{v['village']}]({v['url']})")


def alerts_page():
    st.title("📣 Alerts & share kit")
    st.caption(
        "Made every morning at 05:15 from IMD observed rain and the "
        "ECMWF forecast. A share button appears only after an "
        "agronomist has signed off the rule and the language. Until "
        "then the card says DRAFT - read it, don't forward it.")
    _links()
    c1, c2 = st.columns([1, 2])
    days = c1.selectbox("Period", [7, 14, 30, 90], index=1,
                        format_func=lambda d: f"last {d} days")
    df = _alerts(days)
    if df.empty:
        st.info("No alerts in this period. Jobs may not have run yet - "
                "check the sidebar's job status on the main page.")
        return
    names = sorted(df["village"].fillna(df["village_id"]).unique())
    pick = c2.multiselect("Villages", names)
    if pick:
        df = df[df["village"].fillna(df["village_id"]).isin(pick)]
    mtime = share.TEMPLATES_PATH.stat().st_mtime

    for _, r in df.iterrows():
        a = {k: (None if pd.isna(v) else v) for k, v in r.items()}
        status = ("✅ signed off" if a["approved_by"] else "📝 draft")
        crop = f" · {a['crop']}" if a["crop"] else ""
        head = (f"{SEV_ICON.get(a['severity'], '')} **{a['title']}** — "
                f"{a.get('village') or a['village_id']}{crop} · "
                f"{a['as_of']} · `{a['alert_id']}` · {status}")
        if a.get("verdict"):
            head += f" · checked: {a['verdict']}"
        with st.expander(head):
            first = STATE_LANG.get(a.get("state"), "en")
            order = [first] + [x for x in share.LANGS if x != first]
            tabs = st.tabs([share.LANG_NAME[x] for x in order])
            for tab, lang in zip(tabs, order):
                with tab:
                    _kit_tab(a, lang, mtime)
            with st.expander("Why did this fire? (data and conditions)"):
                tr = json.loads(a["trace_json"])
                rows = [{"part": part, "feature": c[0], "test":
                         f"{c[1]} {c[2]}", "value": c[3],
                         "met": "yes" if c[4] else "no"}
                        for part in ("all", "any") for c in tr[part]]
                st.dataframe(pd.DataFrame(rows), hide_index=True,
                             use_container_width=True)
                st.caption("Data: " + json.dumps(json.loads(
                    a["vintage_json"])) + f" · rule {a['rule_id']} "
                    f"({a['rule_hash']}) · code {a['git_sha']}")
                st.markdown("**English draft as logged:**")
                st.write(a["text_en"])
