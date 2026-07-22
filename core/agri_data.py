"""Importable reference-data registry.

data.gov.in has many useful agri datasets that are DOWNLOAD-ONLY (no
live API): fertiliser consumption, horticulture area/production, land
use, animal-husbandry stats, MSP, etc. This module is a single, generic
home for all of them - register a dataset here, drop a CSV in via
tools/import_agri.py, and it shows up in the Allied Sectors tab for the
searched area. No per-dataset code.

Levels:
  'state'    - one row per state (joined to the state(s) in view)
  'district' - one row per district (joined to district(s) in view)
"""

from functools import lru_cache

import pandas as pd

from config import PROJECT_ROOT
from core.allied import _norm, _norm_state, DISTRICT_ALIAS

REF_DIR = PROJECT_ROOT / "data" / "reference"

DATASETS = {
    "fertilizer": {
        "label": "Fertiliser consumption (NPK)",
        "level": "state",
        "file": REF_DIR / "fertilizer_state.csv",
        "source": "DES Fertiliser Statistics / data.gov.in",
        "note": "N+P+K nutrient use - proxy for input-market size.",
    },
    "horticulture": {
        "label": "Horticulture area & production",
        "level": "state",
        "file": REF_DIR / "horticulture_state.csv",
        "source": ("National Horticulture Board (nhb.gov.in) or "
                   "'Horticulture Statistics at a Glance'"),
        "note": "Fruit/veg/plantation area & output.",
    },
    "land_use": {
        "label": "Land use (net sown / irrigated)",
        "level": "state",
        "file": REF_DIR / "land_use_state.csv",
        "source": ("DES 'Land Use Statistics at a Glance' "
                   "(desagri.gov.in)"),
        "note": "Net sown, irrigated area and cropping intensity.",
    },
}


@lru_cache(maxsize=8)
def _load(path_str):
    from pathlib import Path
    p = Path(path_str)
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(p)
    except Exception:
        return pd.DataFrame()
    return df if not df.empty else pd.DataFrame()


def rows_for_area(key, states, districts):
    """Return the dataset rows relevant to the searched area.

    states:    iterable of normalised state keys (from allied.states_touching)
    districts: iterable of (state, district) name strings
    """
    ds = DATASETS.get(key)
    if ds is None:
        return pd.DataFrame()
    df = _load(str(ds["file"]))
    if df.empty:
        return df

    if ds["level"] == "state":
        if "state" not in df.columns:
            return pd.DataFrame()
        keys = set(states)
        return df[df["state"].map(lambda s: _norm_state(s) in keys)] \
            .reset_index(drop=True)

    # district level
    if "district" not in df.columns:
        return pd.DataFrame()
    want = set()
    for _, d in districts:
        dn = _norm(d)
        want.add(DISTRICT_ALIAS.get(dn, dn))
    return df[df["district"].map(
        lambda x: DISTRICT_ALIAS.get(_norm(x), _norm(x)) in want)] \
        .reset_index(drop=True)
