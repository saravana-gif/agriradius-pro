"""Village Sourcing Score - one ranked number per village.

Combines everything the app knows into a 0-100 score:

  Cropland size      0-30  (percentile within the buffer)
  Cropping intensity 0-25  (pattern + cycles/year)
  Soil quality       0-20  (pH, organic carbon, CEC)
  Rainfall           0-15  (buffer-level reliability verdict)
  Ground truth       0-10  (field-verified prediction bonus)

Missing inputs score their neutral midpoint so villages stay
comparable whichever analyses have been run.
"""

import pandas as pd

PATTERN_POINTS = {
    "Double / Multiple Cropping": 25,
    "Long-Duration Crop": 20,
    "Perennial / Plantation": 20,
    "Single Cropping": 12,
    "Low Cropping Activity": 2,
    "No cropland data": 0,
}

RAIN_POINTS = {
    "Reliable": 15,
    "Moderately Variable": 9,
    "Erratic": 4,
}


def _soil_points(row):
    """0-20 from pH (8), organic carbon (8), CEC (4)."""

    pts = 0.0

    ph = row.get("pH")
    if ph is not None and not pd.isna(ph):
        if 6.0 <= ph <= 7.5:
            pts += 8
        elif 5.5 <= ph <= 8.0:
            pts += 5
        else:
            pts += 2
    else:
        pts += 4  # neutral when unknown

    oc = row.get("OC (g/kg)")
    if oc is not None and not pd.isna(oc):
        if oc >= 9:
            pts += 8
        elif oc >= 5:
            pts += 5
        else:
            pts += 2
    else:
        pts += 4

    cec = row.get("CEC")
    if cec is not None and not pd.isna(cec):
        pts += 4 if cec >= 15 else 2
    else:
        pts += 2

    return pts


def score_villages(insights_df, soil_df=None, rain_verdict=None,
                   gt_df=None):
    """Return ranked DataFrame with Score and component columns."""

    if insights_df is None or insights_df.empty:
        return pd.DataFrame()

    df = insights_df.copy()

    # --- Cropland size: percentile within buffer (0-30) ---
    ranks = df["Cropland (ac)"].rank(pct=True)
    df["Land Pts"] = (ranks * 30).round(1)

    # --- Cropping intensity (0-25) ---
    df["Crop Pts"] = df["Pattern"].map(PATTERN_POINTS).fillna(10)

    # --- Soil (0-20) ---
    if soil_df is not None and not soil_df.empty:
        soil_cols = [c for c in ("Village", "pH", "OC (g/kg)", "CEC")
                     if c in soil_df.columns]
        df = df.merge(soil_df[soil_cols], on="Village", how="left")

    df["Soil Pts"] = df.apply(_soil_points, axis=1)

    # --- Rainfall (0-15, same for whole buffer) ---
    df["Rain Pts"] = RAIN_POINTS.get(rain_verdict, 8)

    # --- Ground truth bonus (0-10) ---
    verified = set()
    if gt_df is not None and not gt_df.empty:
        verified = set(gt_df["Village"].astype(str))

    df["GT Pts"] = df["Village"].astype(str).map(
        lambda v: 10 if v in verified else 5)

    df["Score"] = (
        df["Land Pts"] + df["Crop Pts"] + df["Soil Pts"]
        + df["Rain Pts"] + df["GT Pts"]
    ).round(1)

    df = df.sort_values("Score", ascending=False).reset_index(
        drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))

    keep = ["Rank", "Village", "Taluk", "District", "Score",
            "Cropland (ac)", "Pattern", "Cycles/Year",
            "Land Pts", "Crop Pts", "Soil Pts", "Rain Pts", "GT Pts"]

    return df[[c for c in keep if c in df.columns]]
