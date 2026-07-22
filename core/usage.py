"""Service health / usage tracker.

IMPORTANT (honesty): Google Earth Engine, Open-Meteo and data.gov.in
do NOT publish an API to read your remaining daily quota or an exact
reset time. So this is NOT a live read of Google's fuel gauge - it
cannot be. Instead it tracks THIS app's activity (calls made this
session) and, crucially, captures the exact moment a service returns a
limit / memory / rate error, so you get a clear red/amber/green signal
and a timestamp. Reset behaviour is explained, not guessed.
"""

import datetime

import streamlit as st

SERVICES = {
    "earth_engine": "Google Earth Engine",
    "open_meteo": "Open-Meteo weather",
    "data_gov": "data.gov.in (mandi/MSP)",
}

# Error-message signatures -> limit kind.
_PATTERNS = {
    "quota": ["compute quota", "quota exceeded", "restricted mode",
              "user quota", "exceeded the compute"],
    "memory": ["memory limit", "out of memory", "user memory"],
    "timeout": ["timed out", "timeout", "deadline exceeded"],
    "rate": ["too many", "concurrent", "rate limit", "429",
             "quota metric", "resource exhausted"],
}


def _today():
    return datetime.date.today().isoformat()


def _state():
    u = st.session_state.get("usage")
    if not u or u.get("date") != _today():
        u = {"date": _today(),
             "calls": {k: 0 for k in SERVICES},
             "events": []}
        st.session_state["usage"] = u
    return u


def bump(service, n=1):
    """Count a call to a service."""
    s = _state()
    s["calls"][service] = s["calls"].get(service, 0) + n


def classify(msg):
    m = str(msg).lower()
    for kind, pats in _PATTERNS.items():
        if any(p in m for p in pats):
            return kind
    return None


def note_error(service, exc):
    """Record a limit/error event if the message looks like a limit.
    Returns the kind or None."""
    kind = classify(exc)
    if not kind:
        return None
    s = _state()
    s["events"].append({
        "service": service, "kind": kind,
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "msg": str(exc)[:200],
    })
    s["events"] = s["events"][-25:]
    return kind


def snapshot():
    s = _state()
    return {"date": s["date"], "calls": dict(s["calls"]),
            "events": list(s["events"])}


def friendly(exc):
    """A clear, actionable message if the error is a service limit,
    else None (so the caller shows the raw error)."""
    kind = classify(exc)
    if kind == "quota":
        return ("🛰️ Earth Engine is at its compute limit right now. "
                "Wait a few minutes and click Refresh, or reduce the "
                "radius / turn off other layers. (See Service health "
                "in the sidebar.)")
    if kind == "memory":
        return ("🛰️ This computation exceeded Earth Engine's memory "
                "limit. Reduce the radius and try again.")
    if kind in ("timeout", "rate"):
        return ("🛰️ Earth Engine was busy or slow. Click Refresh to "
                "retry; if it persists, reduce the radius.")
    return None


def health(service):
    """green / amber / red for a service, based on recent events."""
    s = _state()
    evs = [e for e in s["events"] if e["service"] == service]
    if not evs:
        return "green", None
    last = evs[-1]
    try:
        t = datetime.datetime.strptime(last["time"], "%H:%M:%S").time()
        mins = (datetime.datetime.now()
                - datetime.datetime.combine(datetime.date.today(), t)
                ).total_seconds() / 60
    except Exception:
        mins = 999
    return ("red" if mins <= 20 else "amber"), last


_DOT = {"green": "🟢", "amber": "🟡", "red": "🔴"}


def health_panel():
    """Sidebar service-health / usage meter."""
    with st.expander("🛰️ Service health & limits", expanded=False):

        # --- Real EECU quota gauge (Cloud Monitoring) ---
        from core.ee_quota import eecu_usage, TIER_LIMITS
        tier = st.selectbox(
            "Earth Engine tier", list(TIER_LIMITS), index=0,
            key="ee_tier",
            help="Non-commercial monthly EECU-hour limit.")
        q = eecu_usage(tier, st.session_state.get("ee_quota_nonce", 0))
        if q.get("error"):
            st.caption(f"EECU meter: {q['msg']}")
        else:
            used, lim, rem = q["used"], q["limit"], q["remaining"]
            st.progress(min(used / lim, 1.0) if lim else 0.0,
                        text=f"EECU compute: {used:.1f} / {lim} hrs "
                             f"this month")
            colr = ("🔴" if q["pct"] >= 90 else
                    "🟡" if q["pct"] >= 70 else "🟢")
            st.caption(f"{colr} {rem:.1f} EECU-hrs remaining · "
                       f"resets {q['reset']}")
            if q.get("daily"):
                import pandas as _pd
                dd = _pd.Series(q["daily"]).sort_index()
                dd.index = _pd.to_datetime(dd.index)
                st.bar_chart(dd, height=120)
        if st.button("↻ Refresh usage", use_container_width=True):
            st.session_state.ee_quota_nonce = \
                st.session_state.get("ee_quota_nonce", 0) + 1
            st.rerun()

        st.divider()
        st.caption(
            "Below: this session's call activity and any limit/memory "
            "errors a service returned (complements the EECU gauge "
            "above).")

        for key, label in SERVICES.items():
            calls = _state()["calls"].get(key, 0)
            state, last = health(key)
            line = f"{_DOT[state]} **{label}** - {calls} calls today"
            if last:
                line += (f"  \n  ⚠ last {last['kind']} at "
                         f"{last['time']}")
            st.markdown(line)

        if st.button("Check Earth Engine now",
                     use_container_width=True):
            try:
                import ee
                from gee.auth import initialize
                initialize()
                # small real computation (not just a constant) so it
                # reflects compute availability, kept tiny for quota.
                pt = ee.Geometry.Point([76.6, 12.4]).buffer(300)
                _ = (ee.Image("USGS/SRTMGL1_003")
                     .reduceRegion(ee.Reducer.mean(), pt, 90,
                                   bestEffort=True).getInfo())
                bump("earth_engine")
                st.success("Earth Engine responded normally.")
            except Exception as e:
                kind = note_error("earth_engine", e)
                st.error(f"Earth Engine issue"
                         f"{' (' + kind + ')' if kind else ''}: {e}")

        st.caption(
            "**Resets:** the EECU-hours gauge above is the real monthly "
            "compute budget and resets on the 1st of each month. "
            "Short-term 'restricted mode' throttling also clears within "
            "minutes-to-a-day. Open-Meteo free tier ~10k calls/day; "
            "data.gov.in has soft rate limits. If Earth Engine shows "
            "red, wait and retry, or use lighter layers / smaller "
            "radius meanwhile.")
