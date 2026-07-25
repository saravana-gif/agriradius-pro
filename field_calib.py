"""Train + validate the crop classifier on the uploaded FIELD points.

The annual-crop analog of coconut_calib.py. Where coconut_calib measures
the satellite signature of known coconut groves, this does the same for
the hand-collected field points in data/ground_truth/labeled_points.csv
(Turmeric / Ginger / Chilli / Maize, collected THIS season) and then
trains the app's own Random Forest on them to check the crops are
separable from satellite.

All points are treated as CURRENT-SEASON observations, so it samples the
2026 feature stack by default (override with a year argument).

Run on your machine (where Earth Engine is authenticated):

    py field_calib.py            # 2026 season (this week's data)
    py field_calib.py 2025       # compare against last year's imagery

It prints, for the labelled points:
  1. How many points per crop and the classifier groups they map to.
  2. Each crop's real satellite signature (NDVI phenology, red-edge,
     radar, Dynamic World probabilities, terrain) as medians - so you
     can see how turmeric vs ginger vs chilli vs maize actually differ.
  3. The trained Random Forest's accuracy + confusion matrix, so we
     know whether the app can tell these crops apart here.
"""

import sys

import pandas as pd

from maize_diag import init_ee          # service-account EE loader
from config import PROJECT_ROOT
from gee.classifier import CROP_GROUPS, PROBE_BANDS, N_TREES

import ee
from gee.features import feature_stack

GT = PROJECT_ROOT / "data" / "ground_truth" / "labeled_points.csv"
YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2026

# Signature bands to report per crop (superset of the probe bands).
SIG_BANDS = [
    "NDVI_p15", "NDVI_p50", "NDVI_p90", "NDVI_amp",
    "NDRE", "CIre", "GNDVI", "NDMI",
    "VV", "VH", "VVVH_diff", "VH_std",
    "DW_crops", "DW_trees", "DW_grass", "DW_bare",
    "elevation", "slope",
]


def _group(crop):
    return CROP_GROUPS.get(str(crop).strip())


def main():
    init_ee()

    df = pd.read_csv(GT)
    df = df.dropna(subset=["Latitude", "Longitude", "Crop"]).copy()
    df["group"] = df["Crop"].map(_group)
    unknown = df[df["group"].isna()]
    if len(unknown):
        print("Skipping crops with no classifier group:",
              sorted(unknown["Crop"].unique()))
    df = df.dropna(subset=["group"]).reset_index(drop=True)

    print(f"\nYear sampled: {YEAR}  |  {len(df)} labelled field points")
    print("Points per crop:")
    for crop, n in df["Crop"].value_counts().items():
        print(f"   {crop:10s} {n:3d}  -> group '{_group(crop)}'")
    print("Classifier groups present:",
          sorted(df["group"].unique()))

    # --- one feature stack over all points, sampled at each ---
    feats = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([r.Longitude, r.Latitude]),
                   {"i": int(i)})
        for i, r in df.iterrows()
    ])
    region = feats.geometry().bounds().buffer(3000)
    stack = feature_stack(region, YEAR)

    sampled = stack.select(SIG_BANDS).sampleRegions(
        collection=feats, properties=["i"], scale=10,
        tileScale=4).getInfo()
    s = pd.DataFrame([f["properties"] for f in sampled["features"]])
    s = s.merge(df[["Crop", "group"]].reset_index().rename(
        columns={"index": "i"}), on="i", how="left")
    print(f"\n{len(s)} of {len(df)} points returned satellite features")

    # --- per-crop signature (medians) ---
    print("\n=== Real satellite signature per crop (median) ===")
    hdr = "  crop        " + "".join(f"{b[:8]:>9}" for b in SIG_BANDS)
    print(hdr)
    for crop, g in s.groupby("Crop"):
        cells = "".join(
            f"{g[b].median():9.3f}" if b in g and g[b].notna().any()
            else f"{'-':>9}" for b in SIG_BANDS)
        print(f"  {crop:10s}{cells}")

    # --- train the app's RF and score it ---
    groups = sorted(s["group"].dropna().unique())
    if len(groups) < 2:
        print("\nNeed >=2 groups to train. Add more crops.")
        return

    code = {g: i for i, g in enumerate(groups)}
    train_fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([r.Longitude, r.Latitude]),
                   {"cls": code[r.group]})
        for r in df.itertuples()
    ])
    train_region = train_fc.geometry().bounds().buffer(3000)
    fstack = feature_stack(train_region, YEAR)
    training = fstack.sampleRegions(
        collection=train_fc, properties=["cls"], scale=10, tileScale=4)

    clf = ee.Classifier.smileRandomForest(N_TREES).train(
        features=training, classProperty="cls",
        inputProperties=fstack.bandNames())

    matrix = training.classify(clf).errorMatrix("cls", "classification")
    acc = matrix.accuracy().getInfo()
    cm = matrix.array().getInfo()

    print(f"\n=== Random Forest ({N_TREES} trees), {YEAR} features ===")
    print("Groups (row/col order):", groups)
    print("Confusion matrix (resubstitution - optimistic):")
    for g, row in zip(groups, cm):
        print(f"  {g:12s} {row}")
    print(f"\n  >>> Training accuracy: {round(acc * 100, 1)}%   "
          f"({len(df)} points, {len(groups)} groups)")
    print("\nNote: resubstitution accuracy is optimistic (trained and "
          "scored on the same points). With only a few points per crop "
          "it mainly confirms the crops are separable from satellite; "
          "log more field points to make it robust. In the app, the "
          "'Trained Crop Map' tab already uses these points live.")


if __name__ == "__main__":
    main()
