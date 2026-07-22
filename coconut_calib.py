"""Calibrate the coconut / plantation detector against real ground truth.

Uses the Srirangapatna FRUITS coconut survey (87 geolocated villages,
~4,300 acres of confirmed coconut) to measure the ACTUAL satellite
signature of coconut here and check how well the current plantation
detector catches it - the coconut analog of maize_diag.py.

Run on your machine (where Earth Engine is authenticated):

    py coconut_calib.py

It prints, for the 87 known-coconut points:
  1. The real coconut feature signature (NDVI p15/p90/amplitude, VH,
     Dynamic World trees/crops, slope) as percentiles.
  2. The % passing each gate of the current detector and the final
     recall (how many known-coconut points it flags as coconut), so
     we can see which threshold is throwing coconut away.
"""

import pandas as pd

from maize_diag import init_ee  # reuses the service-account loader
from config import PROJECT_ROOT

import ee
from gee.features import feature_stack

# Expanded ground truth: 2,677 coconut villages across 6 districts.
# Filter to one belt and cap the sample so a single Earth Engine run
# stays cheap (quota-friendly):
#   py coconut_calib.py                 -> Srirangapatna (default)
#   py coconut_calib.py Tiptur          -> Tiptur belt
#   py coconut_calib.py Gubbi 150       -> Gubbi, 150-point sample
#   py coconut_calib.py all 300         -> random 300 across all belts*
# (*'all' spans a huge area; keep the sample small.)
import sys as _sys

GT = PROJECT_ROOT / "data" / "ground_truth" / "coconut_gt_expanded.csv"
TALUK = _sys.argv[1] if len(_sys.argv) > 1 else "Srirangapatna"
SAMPLE = int(_sys.argv[2]) if len(_sys.argv) > 2 else 400
YEAR = 2024

# current detector thresholds (mirror gee/plantation.py)
MAX_SLOPE_DEG = 12
EVERGREEN_MIN = 0.22         # base: dry-season greenness (p15)
PLANTATION_PEAK_MIN = 0.45   # base: greens up at peak
PLANTATION_TREES_MIN = 0.12  # base: persistent tree canopy
DW_BUILT_MAX = 0.30          # base: not built-up
PEAK_MAX = 0.82              # coconut vote
AMP_MAX = 0.45              # coconut vote
VH_MIN = -18.0             # coconut vote

BANDS = ["NDVI_p15", "NDVI_p90", "NDVI_amp", "VH",
         "DW_trees", "DW_crops", "DW_built", "DW_bare", "slope"]


def main():
    init_ee()
    df = pd.read_csv(GT)
    if TALUK.lower() != "all":
        df = df[df["taluk"].str.lower().str.contains(
            TALUK.lower(), na=False)]
    if len(df) > SAMPLE:
        df = df.sample(SAMPLE, random_state=1)
    df = df.reset_index(drop=True)
    print(f"Belt='{TALUK}': {len(df)} confirmed-coconut points loaded")

    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([r.lon, r.lat]), {"i": int(i)})
        for i, r in df.iterrows()
    ])

    # One feature stack over the taluk bounds, sampled at all points.
    region = fc.geometry().bounds().buffer(2000)
    feats = feature_stack(region, YEAR).select(BANDS)
    sampled = feats.sampleRegions(
        collection=fc, properties=["i"], scale=10, tileScale=4).getInfo()

    rows = [f["properties"] for f in sampled["features"]]
    s = pd.DataFrame(rows)
    print(f"{len(s)} points returned satellite features\n")

    print("=== Real coconut signature (percentiles) ===")
    for b in BANDS:
        if b in s:
            q = s[b].quantile([0.1, 0.5, 0.9]).round(3).tolist()
            print(f"  {b:10s} p10={q[0]:<8} p50={q[1]:<8} p90={q[2]}")

    n = len(s)
    def pct(x):
        return f"{100*x.mean():5.1f}%"

    # New logic (mirror gee/plantation.py)
    base = ((s["slope"] <= MAX_SLOPE_DEG)
            & (s["NDVI_p15"] >= EVERGREEN_MIN)
            & (s["NDVI_p90"] >= PLANTATION_PEAK_MIN)
            & (s["DW_trees"] >= PLANTATION_TREES_MIN)
            & (s["DW_trees"] > s["DW_bare"])
            & (s["DW_built"] < DW_BUILT_MAX))
    v_tree = s["DW_trees"] > s["DW_crops"]
    v_peak = s["NDVI_p90"] < PEAK_MAX
    v_stable = s["NDVI_amp"] <= AMP_MAX
    v_vh = s["VH"] > VH_MIN
    votes = (v_tree.astype(int) + v_peak.astype(int)
             + v_stable.astype(int) + v_vh.astype(int))
    coconut = base & (votes >= 2)

    print("\n=== Gate pass-rates over known coconut (higher = better) ===")
    print(f"  base: slope<={MAX_SLOPE_DEG}              : {pct(s['slope']<=MAX_SLOPE_DEG)}")
    print(f"  base: p15>={EVERGREEN_MIN} (dry-green)    : {pct(s['NDVI_p15']>=EVERGREEN_MIN)}")
    print(f"  base: p90>={PLANTATION_PEAK_MIN} (greens up)   : {pct(s['NDVI_p90']>=PLANTATION_PEAK_MIN)}")
    print(f"  base: DW_trees>={PLANTATION_TREES_MIN} (canopy) : {pct(s['DW_trees']>=PLANTATION_TREES_MIN)}")
    print(f"  base (all)                     : {pct(base)}")
    print(f"  vote tree (trees>crops)        : {pct(v_tree)}")
    print(f"  vote peak (p90<{PEAK_MAX})         : {pct(v_peak)}")
    print(f"  vote stable (amp<={AMP_MAX})        : {pct(v_stable)}")
    print(f"  vote VH (>{VH_MIN})            : {pct(v_vh)}")
    print(f"  votes>=2 (within base)         : {pct((votes>=2))}")
    print(f"\n  >>> FINAL coconut RECALL       : {pct(coconut)}  "
          f"({int(coconut.sum())}/{n})")

    # Sweep the two base thresholds so we can fine-tune WITHOUT another
    # Earth Engine run (quota-friendly). Recall for each combination:
    print("\n=== Recall sweep over base thresholds (rows=DW_trees, cols=p90) ===")
    tree_grid = [0.03, 0.05, 0.08, 0.12]
    peak_grid = [0.35, 0.40, 0.45, 0.50]
    hdr = "  trees\\p90 " + "".join(f"{p:>7}" for p in peak_grid)
    print(hdr)
    for t in tree_grid:
        cells = []
        for p in peak_grid:
            b = ((s["slope"] <= MAX_SLOPE_DEG)
                 & (s["NDVI_p90"] >= p) & (s["DW_trees"] >= t))
            cells.append(f"{100*(b & (votes>=2)).mean():6.0f}%")
        print(f"  {t:<9}" + "".join(cells))

    miss = s[~coconut]
    if len(miss):
        print(f"\n  Missed {len(miss)} points. Their medians:")
        for b in BANDS:
            if b in miss:
                print(f"     {b:10s} {miss[b].median():.3f}")


if __name__ == "__main__":
    main()
