"""Rainfall reliability analysis (pure python)."""

import pandas as pd


def to_dataframe(series):
    """[('YYYY-MM', mm), ...] -> DataFrame with Year column."""

    df = pd.DataFrame(series, columns=["Month", "Rainfall (mm)"])
    df["Rainfall (mm)"] = pd.to_numeric(
        df["Rainfall (mm)"], errors="coerce"
    ).fillna(0)
    df["Year"] = df["Month"].str[:4].astype(int)

    return df


def analyze_rainfall(df):
    """Annual totals + reliability verdict. Returns dict."""

    annual = df.groupby("Year")["Rainfall (mm)"].sum()

    # Drop incomplete years (no rainfall recorded at all)
    annual = annual[annual > 0]

    mean_annual = float(annual.mean())
    cv = float(annual.std() / mean_annual * 100) if mean_annual else 0.0

    if cv < 15:
        verdict = "Reliable"
        detail = (
            "Year-to-year rainfall is stable - production risk from "
            "rainfall variability is low."
        )
    elif cv < 25:
        verdict = "Moderately Variable"
        detail = (
            "Noticeable good-year/bad-year swings - expect occasional "
            "weak seasons."
        )
    else:
        verdict = "Erratic"
        detail = (
            "Large rainfall swings between years - rain-fed production "
            "here is high-risk; irrigated areas are safer bets."
        )

    monsoon = df[df["Month"].str[5:7].isin(["06", "07", "08", "09"])]
    monsoon_share = float(
        monsoon["Rainfall (mm)"].sum() / df["Rainfall (mm)"].sum() * 100
    ) if df["Rainfall (mm)"].sum() else 0.0

    return {
        "mean_annual_mm": round(mean_annual),
        "cv_pct": round(cv, 1),
        "verdict": verdict,
        "detail": detail,
        "wettest_year": int(annual.idxmax()) if len(annual) else 0,
        "wettest_mm": round(float(annual.max())) if len(annual) else 0,
        "driest_year": int(annual.idxmin()) if len(annual) else 0,
        "driest_mm": round(float(annual.min())) if len(annual) else 0,
        "monsoon_share_pct": round(monsoon_share, 1),
        "annual": annual,
    }
