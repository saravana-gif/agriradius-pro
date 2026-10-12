"""Show previously analysed areas instantly; refresh them on request.

core/result_cache keeps finished results on disk. This module is the
UI side:
- prefill_sections(): after Analyze, put every section result that
  was saved for this area/year straight into the session, so tabs
  that used to need a button click (village insights, NDVI, rainfall,
  soil...) appear at once. Sections with nothing saved are cleared, so
  a result from the PREVIOUS area is never shown against this one.
- banner(): "Showing saved results from <date>" + a Refresh button.
- run_pending_refresh(): Refresh recomputes land cover and every
  section currently on screen, replacing the saved copies.
"""

import datetime
import importlib

import streamlit as st

from core import result_cache as rc

# session key -> (module, function, extra args after lat, lon, radius)
#   "y"  = (year,)      "y2" = (year - 1, year)      "" = ()
SECTIONS = {
    "crosscheck": ("gee.worldcover", "cropland_crosscheck", "y"),
    "village_insights": ("gee.village_stats", "village_insights", "y"),
    "stability": ("gee.stability", "cropland_stability", "y"),
    "paddy_stats": ("gee.paddy", "paddy_stats", "y"),
    "plantation_stats": ("gee.plantation", "plantation_stats", "y"),
    "ndvi_series": ("gee.ndvi", "ndvi_monthly_series", "y2"),
    "rainfall_series": ("gee.rainfall", "rainfall_monthly", "y"),
    "soil": ("gee.soil", "soil_profile", ""),
    "village_soil": ("gee.soil", "village_soil", ""),
    "soil_climate": ("gee.climate", "soil_climate", "y"),
}


def _area():
    ss = st.session_state
    return ss.lat, ss.lon, ss.radius, ss.year


def _args(kind, lat, lon, radius, year):
    extra = {"y": (year,), "y2": (year - 1, year), "": ()}[kind]
    return (lat, lon, radius) + extra


def _fn(module, name):
    return getattr(importlib.import_module(module), name)


def prefill_sections():
    """Fill section results from saved copies for the current area."""
    lat, lon, radius, year = _area()
    for key, (mod, name, kind) in SECTIONS.items():
        try:
            fn = _fn(mod, name)
            val = fn.peek(*_args(kind, lat, lon, radius, year)) \
                if hasattr(fn, "peek") else None
        except Exception:
            val = None
        st.session_state[key] = val


def _request_refresh():
    lat, lon, radius, _ = _area()
    rc.start_refresh(lat, lon, radius)
    st.session_state["_refresh_pending"] = [
        k for k in SECTIONS if st.session_state.get(k) is not None]


def run_pending_refresh():
    """Called at the top of the results page, before anything renders."""
    pending = st.session_state.pop("_refresh_pending", None)
    if pending is None:
        return
    lat, lon, radius, year = _area()
    failed = []
    with st.spinner("Refreshing with the latest satellite data..."):
        try:
            from gee.analysis import analyze_landcover
            st.session_state.results = analyze_landcover(
                lat, lon, radius, year)
        except Exception:
            failed.append("land cover")
        for key in pending:
            mod, name, kind = SECTIONS[key]
            try:
                st.session_state[key] = _fn(mod, name)(
                    *_args(kind, lat, lon, radius, year))
            except Exception:
                failed.append(key.replace("_", " "))   # keep old value
    if failed:
        st.warning("Could not refresh: " + ", ".join(failed) +
                   " - showing the earlier results for those. Earth "
                   "Engine may be busy; try again in a while.")
    else:
        st.success("Refreshed with the latest data.")


def _ago(iso):
    try:
        then = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    local = then.astimezone(datetime.timezone(
        datetime.timedelta(hours=5, minutes=30)))
    days = (datetime.datetime.now(datetime.timezone.utc) - then).days
    when = local.strftime("%d %b %Y, %I:%M %p IST")
    if days == 0:
        return f"{when} (today)"
    return f"{when} ({days} day{'s' if days != 1 else ''} ago)"


def banner(placeholder):
    """Fill `placeholder` (created at the top of the page) once the
    tabs have run and we know which results came from disk."""
    lat, lon, radius, year = _area()
    rc.end_refresh_if_moved(lat, lon, radius)
    as_of = rc.saved_as_of(lat, lon, radius)
    if not as_of:
        return
    with placeholder.container():
        c1, c2 = st.columns([3, 1])
        with c1:
            msg = (f"⚡ Showing saved results for this area from "
                   f"**{_ago(as_of)}** - loaded instantly instead of "
                   "recomputing.")
            if rc.is_stale(as_of, year):
                st.warning(msg + " New satellite images may have "
                           "arrived since; refresh for the latest.")
            else:
                st.info(msg)
        with c2:
            st.button("🔄 Refresh with latest data",
                      use_container_width=True,
                      on_click=_request_refresh,
                      help="Recompute land cover and every section "
                           "shown for this area (can take a few "
                           "minutes), and save the new results.")
