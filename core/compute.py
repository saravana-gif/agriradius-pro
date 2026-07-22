"""Global compute-quality lever.

One control trades resolution/accuracy against Earth Engine compute &
memory. 'Light' renders coarse and cheap (use it when EE is throttled
or a radius is large); 'Heavy' renders at full 10 m detail (use it on
the Contributor tier when accuracy matters). It drives:
  * tile_px()    - reproject grid for map overlays (finer = heavier)
  * stat_scale() - scale for area/stat reductions
  * tile_scale() - reduceRegion tileScale (higher = less memory/req)

Functions read these at call time; the sidebar selector clears the
data cache when the profile changes so everything recomputes at the
new quality.
"""

import streamlit as st

PROFILES = {
    "Light": {"tile_px": 40, "stat_scale": 100, "tile_scale": 16,
              "help": "Fast & coarse - lowest compute/memory."},
    "Balanced": {"tile_px": 20, "stat_scale": 50, "tile_scale": 8,
                 "help": "Default - good detail, moderate compute."},
    "Heavy": {"tile_px": 10, "stat_scale": 30, "tile_scale": 4,
              "help": "Full 10 m detail - most compute (Contributor "
                      "tier recommended)."},
}
DEFAULT = "Balanced"


def _p():
    return PROFILES.get(st.session_state.get("compute_quality", DEFAULT),
                        PROFILES[DEFAULT])


def tile_px():
    return _p()["tile_px"]


def stat_scale():
    return _p()["stat_scale"]


def tile_scale():
    return _p()["tile_scale"]


def current():
    return st.session_state.get("compute_quality", DEFAULT)


def selector():
    """Sidebar control. Clears the data cache on change so layers
    recompute at the new quality."""
    prev = current()
    choice = st.select_slider(
        "Compute quality", options=list(PROFILES), value=prev,
        help="Light = fast/coarse (use if Earth Engine is throttled). "
             "Heavy = full detail (Contributor tier).")
    st.caption(PROFILES[choice]["help"])
    if choice != prev:
        st.session_state.compute_quality = choice
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.rerun()
