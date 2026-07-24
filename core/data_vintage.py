"""Central registry of data-source vintages ("as of" dates).

Every dataset the app shows has a time-stamp: some are live (weather,
mandi), some are periodic government releases (census, MSP), some are
modelled baselines (SoilGrids), and some are historical reference
surveys (SLUSI soil survey, CGWB groundwater). Surfacing the vintage
everywhere stops anyone mistaking older reference data for today's
ground reality.

This is the single source of truth. UI tabs pull their captions from
here via `caption()` / `st_caption()`, and the methodology / help view
renders the whole table via `as_table()`.
"""

from datetime import date

# kind: how "fresh" the number is
#   live      - refreshed continuously / on demand
#   periodic  - a dated official release; newer ones appear over time
#   modelled  - a modelled baseline tied to a training epoch
#   reference - a one-off historical survey; does not update
VINTAGES = {
    "satellite": {
        "label": "Sentinel-2 optical + Dynamic World land cover",
        "as_of": "selected analysis year (season composite)",
        "kind": "periodic",
        "note": "Crop / land-cover layers are composited from imagery "
                "of the year you pick in the sidebar.",
    },
    "soil": {
        "label": "SoilGrids v2.0 (ISRIC)",
        "as_of": "2020 release · modelled, 250 m",
        "kind": "modelled",
        "note": "Global modelled soil estimate, not a current lab test.",
    },
    "soil_era5": {
        "label": "ERA5-Land soil temperature & moisture",
        "as_of": "monthly, ~1-2 month lag",
        "kind": "periodic",
        "note": "~11 km grid; area-level, updated monthly.",
    },
    "rainfall": {
        "label": "CHIRPS rainfall history",
        "as_of": "1981 → ~1 month ago",
        "kind": "periodic",
        "note": "Satellite-gauge rainfall; latest pentad lags ~1 month.",
    },
    "weather": {
        "label": "Open-Meteo current & forecast",
        "as_of": "live (updated hourly)",
        "kind": "live",
        "note": "Real-time conditions and 16-day outlook.",
    },
    "livestock": {
        "label": "20th Livestock Census",
        "as_of": "2019",
        "kind": "periodic",
        "note": "Latest all-India livestock census; district totals.",
    },
    "mandi": {
        "label": "AGMARKNET APMC mandi prices",
        "as_of": "daily (latest reported arrivals)",
        "kind": "live",
        "note": "Government daily price feed via data.gov.in.",
    },
    "msp": {
        "label": "Minimum Support Price (CACP / GoI)",
        "as_of": "2025-26 season",
        "kind": "periodic",
        "note": "Announced per crop season.",
    },
    "horticulture": {
        "label": "Horticulture area & production (State Hort. Dept)",
        "as_of": "~2022-23",
        "kind": "periodic",
        "note": "Latest published state/district horticulture figures.",
    },
    "fertilizer": {
        "label": "Fertiliser consumption (DES)",
        "as_of": "2022-23",
        "kind": "periodic",
        "note": "State NPK use per hectare.",
    },
    "land_use": {
        "label": "Land-use statistics (DES)",
        "as_of": "~2020-22",
        "kind": "periodic",
        "note": "Net sown / irrigated area, cropping intensity.",
    },
    "worldcereal": {
        "label": "ESA WorldCereal cropland",
        "as_of": "2021",
        "kind": "periodic",
        "note": "Independent 10 m cropland cross-check, 2021 season.",
    },
    "worldcover": {
        "label": "ESA WorldCover v200",
        "as_of": "2021",
        "kind": "periodic",
        "note": "Independent 10 m land-cover cross-check.",
    },
    "slusi": {
        "label": "SLUSI Detailed Soil Survey — land capability",
        "as_of": "field surveys 1960-2018 (varies by district)",
        "kind": "reference",
        "note": "One-off detailed surveys of selected watersheds. "
                "Land capability is a stable soil property, but this "
                "is NOT current land use.",
    },
}

# small icon per freshness kind
_ICON = {
    "live": "🟢",
    "periodic": "🟡",
    "modelled": "🟠",
    "reference": "⚪",
}

_KIND_WORD = {
    "live": "live",
    "periodic": "periodic release",
    "modelled": "modelled baseline",
    "reference": "historical reference",
}


def as_of(key, override=None):
    """Just the 'as of' string for a source (or override text)."""
    if override:
        return override
    v = VINTAGES.get(key)
    return v["as_of"] if v else ""


def caption(key, as_of_override=None):
    """A one-line grey caption, e.g.
    '🟡 SoilGrids v2.0 (ISRIC) · data as of 2020 release · modelled baseline'."""
    v = VINTAGES.get(key)
    if not v:
        return ""
    icon = _ICON.get(v["kind"], "•")
    stamp = as_of_override or v["as_of"]
    kind = _KIND_WORD.get(v["kind"], v["kind"])
    return f"{icon} {v['label']} · data as of {stamp} · {kind}"


def st_caption(key, as_of_override=None, extra=None):
    """Render the vintage caption in Streamlit (lazy import)."""
    import streamlit as st
    text = caption(key, as_of_override)
    if extra:
        text = f"{text} · {extra}"
    st.caption(text)


def as_table():
    """All sources as a DataFrame for the methodology / help view."""
    import pandas as pd
    rows = [
        {
            "Data": v["label"],
            "As of": v["as_of"],
            "Type": _KIND_WORD.get(v["kind"], v["kind"]),
            "Notes": v["note"],
        }
        for v in VINTAGES.values()
    ]
    return pd.DataFrame(rows)


def legend():
    """Short legend explaining the freshness icons."""
    return ("🟢 live · 🟡 periodic government release · "
            "🟠 modelled baseline · ⚪ historical reference "
            f"(read on {date.today().isoformat()})")
