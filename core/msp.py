"""Minimum Support Price (MSP) reference.

MSP is the government's floor price. It is published annually (not a
live API on data.gov.in - that resource is download-only), so it is
bundled as a small static table in data/reference/msp.csv. Used in the
Mandi tab to show whether the market modal price is above or below the
floor - a direct procurement signal.

Only a handful of crops are MSP-mandated; most horticulture / spice /
plantation commodities have NO MSP, which is itself worth stating.
"""

from functools import lru_cache

import pandas as pd

from config import PROJECT_ROOT

MSP_CSV = PROJECT_ROOT / "data" / "reference" / "msp.csv"

# Map the app's mandi commodity labels to an MSP row. Coconut is not
# directly MSP-covered, but copra (dried kernel) is - so we surface
# the copra floor as a reference (different unit, so not a direct
# price comparison).
APP_TO_MSP = {
    "Maize": ("Maize", True),
    "Paddy (Common)": ("Paddy (Common)", True),
    "Coconut": ("Copra (Ball)", False),
}


@lru_cache(maxsize=1)
def load_msp():
    if not MSP_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(MSP_CSV)


def msp_for_commodity(app_label):
    """Return MSP info for an app mandi commodity, or None if the crop
    has no MSP. Dict: msp, commodity, season, year, comparable."""
    df = load_msp()
    if df.empty or app_label not in APP_TO_MSP:
        return None
    msp_name, comparable = APP_TO_MSP[app_label]
    row = df[df["commodity"] == msp_name]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "commodity": msp_name,
        "msp": float(r["msp_rs_qtl"]),
        "season": str(r["season"]),
        "year": str(r["year"]),
        "comparable": comparable,
    }
