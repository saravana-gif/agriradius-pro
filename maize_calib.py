"""Calibrate / validate the maize detector against field ground truth.

Uses the GPS-precise confirmed-maize fields (Haveri belt) to read the
real maize NDVI signal and check the detector's gates.

    py maize_calib.py            # default: 2025 (a COMPLETE season)
    py maize_calib.py 2026       # current season (in progress - peak
                                 # Aug-Sep not reached, expect low)

Robust to monsoon cloud / restricted EE mode: it samples a small
buffer around each field (not a single 10 m pixel) and reports clearly
if Earth Engine returned no data (usually quota-restricted mode - wait
and retry).

Maize peaks Aug-Sep, so for the CURRENT year the peak/amplitude read
low now - that's the crop still growing, not a miss. Re-run after
harvest for true validation; run a complete prior year for the full
curve shape.
"""

import sys

import ee
import pandas as pd

from maize_diag import init_ee
from config import PROJECT_ROOT
from gee.ndvi import _mask_clouds
from gee.maize import (_season_peak_ndvi, _annual_trough_ndvi,
                       KHARIF_PEAK_MIN, TROUGH_MAX, MIN_AMPLITUDE,
                       MAX_SLOPE_DEG)

GT = PROJECT_ROOT / "data" / "ground_truth" / "maize_gt.csv"
YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
S2 = "COPERNICUS/S2_SR_HARMONIZED"


def main():
    init_ee()
    df = pd.read_csv(GT)
    print(f"{len(df)} confirmed-maize fields | year {YEAR}\n")

    feats = [ee.Feature(ee.Geometry.Point([r.lon, r.lat]).buffer(40),
                        {"i": int(i)}) for i, r in df.iterrows()]
    fc = ee.FeatureCollection(feats)
    region = fc.geometry().bounds().buffer(3000)

    col = (ee.ImageCollection(S2).filterBounds(region)
           .filterDate(f"{YEAR}-01-01", f"{YEAR}-12-31")
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 85))
           .map(_mask_clouds)
           .map(lambda i: i.normalizedDifference(["B8", "B4"])
                .rename("NDVI")))

    # --- Gate values: sample peak/trough/slope at each field ---
    peak = _season_peak_ndvi(region, YEAR).rename("peak")
    trough = _annual_trough_ndvi(region, YEAR).rename("trough")
    slope = ee.Terrain.slope(
        ee.Image("USGS/SRTMGL1_003")).rename("slope")

    gate_img = ee.Image.cat([peak, trough, slope])
    rows = gate_img.reduceRegions(
        collection=fc, reducer=ee.Reducer.mean(),
        scale=10, tileScale=4).getInfo()["features"]
    s = pd.DataFrame([r["properties"] for r in rows])
    for c in ("peak", "trough", "slope"):
        if c not in s:
            s[c] = float("nan")

    if s[["peak", "trough"]].isna().all().all():
        print("Earth Engine returned no usable data for these fields.\n"
              "Most likely restricted mode (quota) - wait and retry, or "
              "try a complete year. Heavy monsoon cloud in the current "
              "season can also leave no clear pixels.")
        return

    # --- Monthly NDVI: belt-average via a per-month reduceRegion.
    # One getInfo over a server-side dict - robust (no multiband cat /
    # dynamic band-name issues that were returning blanks). ---
    m_out = {}
    for m in range(1, 13):
        start = ee.Date.fromYMD(YEAR, m, 1)
        sub = col.filterDate(start, start.advance(1, "month"))
        m_out[f"m{m:02d}"] = ee.Algorithms.If(
            sub.size().gt(0),
            sub.median().reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region, scale=100,
                maxPixels=1e12, bestEffort=True).get("NDVI"),
            None)
    mvals = ee.Dictionary(m_out).getInfo()

    print("=== Monthly NDVI (belt average) - sowing->peak->harvest ===")
    parts = []
    for m in range(1, 13):
        v = mvals.get(f"m{m:02d}")
        parts.append(f"{m:02d}:{('%.2f' % v) if v is not None else ' -- '}")
    print("  " + "  ".join(parts))

    s["amp"] = s["peak"] - s["trough"]
    print("\n=== Maize gate values per field ===")
    for _, r in s.iterrows():
        def f(x):
            return f"{x:.2f}" if pd.notna(x) else " -- "
        print(f"  field {int(r['i'])}: peak={f(r['peak'])} "
              f"trough={f(r['trough'])} amp={f(r['amp'])} "
              f"slope={f(r['slope'])}")

    ok = ((s["peak"] >= KHARIF_PEAK_MIN) & (s["trough"] < TROUGH_MAX)
          & (s["amp"] >= MIN_AMPLITUDE) & (s["slope"] <= MAX_SLOPE_DEG))
    print(f"\nGates: peak>={KHARIF_PEAK_MIN}, trough<{TROUGH_MAX}, "
          f"amp>={MIN_AMPLITUDE}, slope<={MAX_SLOPE_DEG}")
    print(f">>> Fields passing maize detector: {int(ok.sum())}/{len(s)}")
    print(f"    peak    median: {s['peak'].median():.2f}")
    print(f"    trough  median: {s['trough'].median():.2f}")
    print(f"    amp     median: {s['amp'].median():.2f}")
    if YEAR >= 2026:
        print("\n(Season in progress - peak Aug-Sep not yet reached, so "
              "low pass-rate now is expected.)")


if __name__ == "__main__":
    main()
