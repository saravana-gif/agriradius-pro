"""Crop cycle detection from a monthly NDVI series (pure python)."""

import pandas as pd

PEAK_THRESHOLD = 0.4     # NDVI above this can count as a crop peak
HIGH_NDVI = 0.5          # "actively growing" level
MIN_PEAK_GAP = 3         # months between distinct peaks


def to_dataframe(series):
    """[(month, ndvi|None), ...] -> DataFrame with smoothed column."""

    df = pd.DataFrame(series, columns=["Month", "NDVI"])
    df["NDVI"] = pd.to_numeric(df["NDVI"], errors="coerce")
    df["NDVI"] = df["NDVI"].interpolate(limit_direction="both")
    df["Smoothed"] = df["NDVI"].rolling(3, center=True, min_periods=1).mean()

    return df


def _find_peaks(smooth):

    peaks = []

    for i in range(1, len(smooth) - 1):
        if (
            smooth.iloc[i] >= PEAK_THRESHOLD
            and smooth.iloc[i] >= smooth.iloc[i - 1]
            and smooth.iloc[i] > smooth.iloc[i + 1]
        ):
            peaks.append(i)

    # Merge peaks closer than MIN_PEAK_GAP months (keep the higher one)
    merged = []
    for p in peaks:
        if merged and p - merged[-1] < MIN_PEAK_GAP:
            if smooth.iloc[p] > smooth.iloc[merged[-1]]:
                merged[-1] = p
        else:
            merged.append(p)

    return merged


def analyze_series(df):
    """Classify the cropping pattern. Returns a dict of insights."""

    smooth = df["Smoothed"]
    years = max(len(smooth) / 12.0, 1e-9)

    peaks = _find_peaks(smooth)

    mean_ndvi = float(smooth.mean())
    amplitude = float(smooth.max() - smooth.min())
    cycles_per_year = len(peaks) / years
    high_months_per_year = float((smooth >= HIGH_NDVI).sum() / years)

    if mean_ndvi >= 0.55 and amplitude < 0.15:
        pattern = "Perennial / Plantation"
        detail = (
            "Consistently high NDVI with little seasonal variation - "
            "typical of coconut, banana, orchards or other plantation "
            "crops that stay green year-round."
        )
    elif cycles_per_year >= 1.8:
        pattern = "Double / Multiple Cropping"
        detail = (
            "Two or more growth peaks per year - farmland here supports "
            "multiple crop cycles (good irrigation access likely)."
        )
    elif high_months_per_year >= 8 and amplitude >= 0.15:
        pattern = "Long-Duration Crop"
        detail = (
            "One extended growth period covering most of the year - "
            "candidate crops include sugarcane and turmeric "
            "(9-18 month cycles)."
        )
    elif cycles_per_year >= 0.8:
        pattern = "Single Cropping"
        detail = (
            "One growth peak per year - likely rain-fed farming with "
            "a single monsoon crop (kharif)."
        )
    else:
        pattern = "Low Cropping Activity"
        detail = (
            "Weak or no clear growth peaks - land may be fallow, "
            "sparsely cropped, or the buffer contains little cropland."
        )

    return {
        "pattern": pattern,
        "detail": detail,
        "cycles_per_year": round(cycles_per_year, 1),
        "mean_ndvi": round(mean_ndvi, 3),
        "amplitude": round(amplitude, 3),
        "peak_months": [df["Month"].iloc[p] for p in peaks],
    }