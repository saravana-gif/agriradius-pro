"""Ground-truth-trained crop classifier (the calibration flywheel).

Trains a Random Forest in Earth Engine on the field observations your
team logs (Ground Truth tab), using the shared satellite feature
stack (red-edge indices, phenology, radar). As more labels accrue,
the model gets better and more region-specific than any global
product.

Needs a minimum number of labelled villages spread across at least
two crop classes. Until then, use the heuristic layers.
"""

import math

import ee
import pandas as pd
import streamlit as st

from config import PROJECT_ROOT
from gee.features import feature_stack

MIN_POINTS = 20          # minimum labelled points to train
MIN_CLASSES = 2          # need at least two crop groups
N_TREES = 60

# Bundled coconut ground truth (FRUITS/Bhoomi crop survey): thousands
# of geolocated confirmed-coconut villages across the Karnataka belt.
COCONUT_GT_CSV = (PROJECT_ROOT / "data" / "ground_truth"
                  / "coconut_gt_expanded.csv")

# Map observed crops to classes the model learns. Coconut, banana
# and maize are kept SEPARATE (that is the whole point), with a few
# spectrally-similar crops grouped where 10 m can't split them.
CROP_GROUPS = {
    "Coconut": "Coconut",
    "Arecanut": "Arecanut",
    "Banana": "Banana",
    "Maize": "Maize",
    "Paddy": "Paddy",
    "Sugarcane": "Sugarcane",
    "Turmeric": "LongDuration", "Ginger": "LongDuration",
    "Fruits/Orchard": "Orchard", "Mango": "Orchard",
    "Chilli": "Seasonal", "Vegetables": "Seasonal",
    "Groundnut": "Seasonal", "Cotton": "Seasonal",
    "Ragi/Millets": "Seasonal",
    # Non-coconut tree cover - the key "negative" class that teaches
    # the model NOT to call every evergreen tree a coconut grove.
    "Other Tree": "OtherTree", "Casuarina": "OtherTree",
    "Mixed Trees": "OtherTree", "Forest": "OtherTree",
    "Fallow": "Fallow",
}

GROUP_PALETTE = {
    "Coconut": "ffff00",     # yellow
    "Arecanut": "d4a017",    # goldenrod
    "Banana": "ff1493",      # pink
    "Maize": "ff8c00",       # orange
    "Paddy": "00e5ff",       # cyan
    "Sugarcane": "9acd32",   # yellow-green
    "LongDuration": "e34a33",
    "Orchard": "8b4513",
    "Seasonal": "ff00ff",    # magenta
    "OtherTree": "2e7d32",   # dark green
    "Fallow": "a59b8f",
}


def _group_for(crops):
    """First recognised group from a comma-separated crop string."""
    for c in str(crops).split(","):
        c = c.strip()
        if c in CROP_GROUPS:
            return CROP_GROUPS[c]
    return None


def labelled_points(gt_df, village_centroids):
    """Join ground-truth rows to village centroids -> training points.

    village_centroids: dict {village_name: (lat, lon)}.
    Returns (list_of_dicts, group_names) where each dict has
    lat/lon/group.
    """
    points = []
    groups = set()

    if gt_df is None or gt_df.empty:
        return points, groups

    for _, row in gt_df.iterrows():
        village = str(row.get("Village", "")).strip()
        grp = _group_for(row.get("Crops", ""))
        if not grp or village not in village_centroids:
            continue
        lat, lon = village_centroids[village]
        points.append({"lat": lat, "lon": lon, "group": grp})
        groups.add(grp)

    return points, groups


def can_train(points, groups):
    return len(points) >= MIN_POINTS and len(groups) >= MIN_CLASSES


def parse_labeled_points(text):
    """Parse 'lat, lon, crop' lines into training points.

    Returns (points, groups). Unknown crops are skipped.
    """
    points, groups = [], set()
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line.lower().startswith("lat"):
            continue
        parts = [p.strip() for p in line.replace(";", ",").split(",")]
        if len(parts) < 3:
            continue
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        grp = _group_for(parts[2])
        if not grp:
            continue
        points.append({"lat": lat, "lon": lon, "group": grp})
        groups.add(grp)
    return points, groups


# Feature bands that best separate coconut / banana / maize - used by
# the probe to read real values at labeled coordinates for tuning.
PROBE_BANDS = [
    "NDVI_p15", "NDVI_p50", "NDVI_p90", "NDVI_amp",
    "NDMI", "GNDVI", "NDRE", "CIre",
    "VV", "VH", "VVVH_diff", "VH_std",
    "DW_trees", "DW_crops", "elevation", "slope",
]


@st.cache_data(show_spinner="Reading satellite features at point...")
def probe(lat, lon, year):
    """Return the discriminating feature values at a coordinate, for
    calibrating coconut/banana/maize thresholds."""
    pt = ee.Geometry.Point([lon, lat])
    buf = pt.buffer(150)
    feats = feature_stack(buf, year).select(PROBE_BANDS)
    vals = feats.reduceRegion(
        reducer=ee.Reducer.mean(), geometry=buf, scale=20,
        bestEffort=True).getInfo()
    return {k: (round(vals[k], 3) if vals.get(k) is not None else None)
            for k in PROBE_BANDS}


@st.cache_data(show_spinner="Training crop classifier...")
def train_and_classify(lat, lon, radius_km, year, points):
    """Train an RF on the points and classify the current buffer.

    points: list of {lat, lon, group} - may lie anywhere (training
    features are sampled around the points; the map is classified
    over the current view buffer). Returns dict with tile_url,
    legend, train_accuracy, class list.
    """

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    # Encode groups as integers
    group_names = sorted({p["group"] for p in points})
    code = {g: i for i, g in enumerate(group_names)}

    fc = ee.FeatureCollection([
        ee.Feature(
            ee.Geometry.Point([p["lon"], p["lat"]]),
            {"cls": code[p["group"]]},
        )
        for p in points
    ])

    # Feature image over the TRAINING region (covers all points, even
    # outside the current view), sampled only at the points.
    train_region = fc.geometry().bounds().buffer(2000)
    feats_train = feature_stack(train_region, year)

    training = feats_train.sampleRegions(
        collection=fc,
        properties=["cls"],
        scale=10,
        tileScale=4,
    )

    classifier = ee.Classifier.smileRandomForest(N_TREES).train(
        features=training,
        classProperty="cls",
        inputProperties=feats_train.bandNames(),
    )

    # Classify the current view buffer with the same features.
    feats = feature_stack(buffer, year)
    classified = feats.classify(classifier).clip(buffer)

    # Resubstitution (training) accuracy - optimistic but indicative
    try:
        acc = (training.classify(classifier)
               .errorMatrix("cls", "classification")
               .accuracy().getInfo())
    except Exception:
        acc = None

    palette = [GROUP_PALETTE.get(g, "888888") for g in group_names]

    mapid = classified.getMapId({
        "min": 0, "max": len(group_names) - 1, "palette": palette})

    return {
        "tile_url": mapid["tile_fetcher"].url_format,
        "legend": {g: GROUP_PALETTE.get(g, "888888")
                   for g in group_names},
        "train_accuracy": round(acc * 100, 1) if acc else None,
        "classes": group_names,
        "n_points": len(points),
    }


# ---------------------------------------------------------------
# Coconut model: trains on the bundled coconut ground truth (real
# FRUITS labels) vs auto-sampled non-coconut land cover, so the RF is
# usable now without waiting for hand-logged negative labels.
# ---------------------------------------------------------------

SQM_PER_ACRE = 4046.8564224


@st.cache_data(show_spinner=False)
def _coconut_gt():
    """The bundled coconut ground-truth points (empty if missing)."""
    if COCONUT_GT_CSV.exists():
        return pd.read_csv(COCONUT_GT_CSV)
    return pd.DataFrame()


def coconut_points_in_view(lat, lon, radius_km, margin_km=6, cap=250):
    """Bundled coconut points inside (buffer + margin). Capped for a
    quota-friendly training run."""
    df = _coconut_gt()
    if df.empty:
        return []
    dlat = (radius_km + margin_km) / 111.0
    dlon = (radius_km + margin_km) / (111.0 * max(
        math.cos(math.radians(lat)), 0.2))
    sub = df[df["lat"].between(lat - dlat, lat + dlat)
             & df["lon"].between(lon - dlon, lon + dlon)]
    if len(sub) > cap:
        sub = sub.sample(cap, random_state=1)
    return list(zip(sub["lat"].tolist(), sub["lon"].tolist()))


@st.cache_data(show_spinner="Training coconut model on ground truth...")
def train_coconut_classifier(lat, lon, radius_km, year):
    """Train an RF: bundled coconut labels vs auto-sampled non-coconut
    land cover, then map coconut across the current view.

    Returns a dict compatible with the classifier display, plus a
    measured coconut area.
    """
    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)
    region = buffer.bounds().buffer(1500)

    coco = coconut_points_in_view(lat, lon, radius_km)
    if len(coco) < 30:
        raise ValueError(
            "Only %d bundled coconut points near this view - pan to a "
            "coconut belt (Tiptur, Gubbi, Arsikere, Nagamangala, "
            "Channapatna, Hiriyur...) and retry." % len(coco))

    feats = feature_stack(region, year)

    # Coconut positives (class 1) from real ground truth.
    fc_coco = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([lo, la]), {"cls": 1})
        for la, lo in coco
    ])
    train_coco = feats.sampleRegions(
        collection=fc_coco, properties=["cls"], scale=10, tileScale=4)

    # Non-coconut negatives (classes 2-6) from confident Dynamic World
    # land cover - sampled, never hand-labelled. Forest is taken on
    # steep ground and cropland where tree-prob is low, so real
    # (flat, woody) coconut is not sampled as a negative.
    dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
          .filterBounds(region)
          .filterDate(f"{year}-01-01", f"{year}-12-31")
          .select(["water", "trees", "crops", "grass", "built", "bare"])
          .mean())
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))

    negband = (ee.Image(0)
               .where(dw.select("crops").gt(0.5)
                      .And(dw.select("trees").lt(0.12)), 2)   # Cropland
               .where(dw.select("trees").gt(0.6)
                      .And(slope.gt(15)), 3)                  # Forest
               .where(dw.select("water").gt(0.6), 4)          # Water
               .where(dw.select("built").gt(0.5), 5)          # Built-up
               .where(dw.select("grass").gt(0.5)
                      .Or(dw.select("bare").gt(0.5)), 6)       # OpenLand
               .rename("cls").toInt())

    neg = feats.addBands(negband).stratifiedSample(
        numPoints=50, classBand="cls", region=buffer, scale=30,
        classValues=[2, 3, 4, 5, 6],
        classPoints=[70, 50, 25, 20, 45],
        seed=1, tileScale=4, geometries=False, dropNulls=True)

    training = train_coco.merge(neg)

    classifier = ee.Classifier.smileRandomForest(80).train(
        features=training, classProperty="cls",
        inputProperties=feats.bandNames())

    classified = feats.classify(classifier).clip(buffer)
    coconut = classified.eq(1)

    # Map tile - coconut in bright yellow (reprojected -> cached grid)
    tile_img = coconut.selfMask().reproject(crs="EPSG:3857", scale=20)
    mapid = tile_img.getMapId({"min": 0, "max": 1,
                               "palette": ["000000", "ffff00"]})

    # Measured coconut area + resubstitution accuracy
    try:
        area = (ee.Image.pixelArea().updateMask(coconut)
                .reduceRegion(reducer=ee.Reducer.sum(), geometry=buffer,
                              scale=30, maxPixels=1e13, bestEffort=True)
                .get("area").getInfo())
        coconut_ac = round((area or 0) / SQM_PER_ACRE, 1)
    except Exception:
        coconut_ac = None
    try:
        acc = (training.classify(classifier)
               .errorMatrix("cls", "classification").accuracy().getInfo())
    except Exception:
        acc = None

    return {
        "tile_url": mapid["tile_fetcher"].url_format,
        "legend": {"Coconut (RF-trained)": "ffff00"},
        "classes": ["Coconut", "Cropland", "Forest", "Water",
                    "Built-up", "OpenLand"],
        "train_accuracy": round(acc * 100, 1) if acc else None,
        "n_points": len(coco),
        "coconut_ac": coconut_ac,
    }
