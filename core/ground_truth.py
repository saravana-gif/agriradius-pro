"""Ground truth collection and accuracy scoring.

Field observations are stored in data/ground_truth/ground_truth.csv -
this file is the company's proprietary labeled dataset and SHOULD be
committed to git. Every record makes the satellite analysis more
trustworthy: predictions are scored against observations and the
thresholds can be recalibrated as the dataset grows.
"""

from datetime import date
from pathlib import Path

import pandas as pd

from config import PROJECT_ROOT

GT_DIR = PROJECT_ROOT / "data" / "ground_truth"
GT_PATH = GT_DIR / "ground_truth.csv"

COLUMNS = [
    "Date", "Village", "Taluk", "District",
    "Crops", "Cycles", "Irrigated", "Notes", "Observer",
]

CROP_OPTIONS = [
    "Turmeric", "Chilli", "Maize", "Coconut", "Banana", "Paddy",
    "Sugarcane", "Vegetables", "Fruits/Orchard", "Ginger",
    "Groundnut", "Cotton", "Ragi/Millets", "Fallow", "Other",
]

# Crops whose canopy stays green year-round -> plantation signature
PERENNIAL = {"coconut", "banana", "fruits/orchard", "arecanut",
             "mango", "coffee"}

# Long-duration annuals (9-18 month cycles)
LONG_DURATION = {"sugarcane", "turmeric", "ginger"}


def load_records():
    """Return the ground truth DataFrame (empty if none yet)."""

    if not GT_PATH.exists():
        return pd.DataFrame(columns=COLUMNS)

    return pd.read_csv(GT_PATH)


def add_record(village, taluk, district, crops, cycles,
               irrigated, notes, observer):
    """Append one observation to the CSV."""

    GT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_records()

    row = {
        "Date": date.today().isoformat(),
        "Village": village,
        "Taluk": taluk,
        "District": district,
        "Crops": ", ".join(crops) if isinstance(crops, list) else crops,
        "Cycles": cycles,
        "Irrigated": "Yes" if irrigated else "No",
        "Notes": notes or "",
        "Observer": observer or "",
    }

    new_row = pd.DataFrame([row])
    df = new_row if df.empty else pd.concat(
        [df, new_row], ignore_index=True)
    df.to_csv(GT_PATH, index=False)

    return row


def expected_pattern(crops, cycles):
    """Map an observation to the pattern the satellite should see."""

    crop_set = {
        c.strip().lower() for c in str(crops).split(",") if c.strip()
    }

    if crop_set & PERENNIAL:
        return "Perennial / Plantation"

    if crop_set & LONG_DURATION:
        return "Long-Duration Crop"

    if "fallow" in crop_set:
        return "Low Cropping Activity"

    try:
        n = float(cycles)
    except (TypeError, ValueError):
        n = 1

    if n >= 2:
        return "Double / Multiple Cropping"

    return "Single Cropping"


def compare_with_predictions(gt_df, insights_df):
    """Join observations with predictions. Returns (df, accuracy_pct).

    accuracy is None when there are no matched rows.
    """

    if gt_df.empty or insights_df is None or insights_df.empty:
        return pd.DataFrame(), None

    gt = gt_df.copy()
    gt["Expected"] = [
        expected_pattern(c, n)
        for c, n in zip(gt["Crops"], gt["Cycles"])
    ]

    pred = insights_df[["Village", "Pattern", "Cycles/Year"]].rename(
        columns={"Pattern": "Predicted"})

    merged = gt.merge(pred, on="Village", how="inner")

    if merged.empty:
        return merged, None

    merged["Match"] = merged["Expected"] == merged["Predicted"]

    accuracy = round(100 * merged["Match"].mean(), 1)

    cols = ["Date", "Village", "Crops", "Cycles", "Expected",
            "Predicted", "Cycles/Year", "Match"]

    return merged[[c for c in cols if c in merged.columns]], accuracy


# ---------------------------------------------------------------
# Soil Health Cards - lab-measured values from farmers' cards.
# This is the only source of real P and K data (not measurable
# from satellite). Stored beside crop observations.
# ---------------------------------------------------------------

SOIL_CARD_PATH = GT_DIR / "soil_cards.csv"

SOIL_CARD_COLUMNS = [
    "Date", "Village", "Taluk", "District", "Farmer",
    "pH", "EC (dS/m)", "OC (%)",
    "N (kg/ha)", "P (kg/ha)", "K (kg/ha)",
    "Micronutrients", "Notes", "Observer",
]


def load_soil_cards():
    """Return the soil card DataFrame (empty if none yet)."""

    if not SOIL_CARD_PATH.exists():
        return pd.DataFrame(columns=SOIL_CARD_COLUMNS)

    return pd.read_csv(SOIL_CARD_PATH)


def add_soil_card(village, taluk, district, farmer, ph, ec, oc,
                  n, p, k, micro, notes, observer):
    """Append one soil health card record. Zero/blank = not recorded."""

    GT_DIR.mkdir(parents=True, exist_ok=True)

    def clean(v):
        try:
            v = float(v)
            return v if v > 0 else ""
        except (TypeError, ValueError):
            return ""

    df = load_soil_cards()

    row = {
        "Date": date.today().isoformat(),
        "Village": village,
        "Taluk": taluk,
        "District": district,
        "Farmer": farmer or "",
        "pH": clean(ph),
        "EC (dS/m)": clean(ec),
        "OC (%)": clean(oc),
        "N (kg/ha)": clean(n),
        "P (kg/ha)": clean(p),
        "K (kg/ha)": clean(k),
        "Micronutrients": micro or "",
        "Notes": notes or "",
        "Observer": observer or "",
    }

    new_row = pd.DataFrame([row])
    df = new_row if df.empty else pd.concat(
        [df, new_row], ignore_index=True)
    df.to_csv(SOIL_CARD_PATH, index=False)

    return row
