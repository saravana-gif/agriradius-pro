"""Earth Engine side of the crop-map accuracy check (jobs/crop_accuracy).

Two calls, kept small for the quota:
- sample_features: read the app's feature stack once at every labelled
  point (client-side rows of band values);
- ee_fit_predict: train the SAME Random Forest the app uses
  (smileRandomForest, gee.classifier.N_TREES) on some rows and predict
  others. Rows go up as plain property tables, so cross-validation
  folds are decided in Python and never re-sample imagery.
"""

import ee

from gee.classifier import N_TREES, negative_classes
from gee.features import feature_stack

CHUNK = 150          # points per sampleRegions call


def sample_features(points, year, scale=10):
    """points: [{"pid", "lat", "lon", ...}] -> rows {"pid", band: value}
    for every point the imagery covered (cloud-masked points drop out)."""
    rows = []
    for s in range(0, len(points), CHUNK):
        chunk = points[s:s + CHUNK]
        fc = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([p["lon"], p["lat"]]),
                       {"pid": p["pid"]}) for p in chunk])
        region = fc.geometry().bounds().buffer(2000)
        got = feature_stack(region, year).sampleRegions(
            collection=fc, properties=["pid"], scale=scale,
            tileScale=4, geometries=False).getInfo()
        rows += [f["properties"] for f in got["features"]]
    return rows


def sample_negatives(centres, year, per_class, radius_m=3000, seed=1):
    """Dynamic-World 'clearly not coconut' samples within radius_m of
    the given (lat, lon) centres: rows with band values, lat/lon and a
    NEGATIVE_CLASSES label code in 'cls'."""
    fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([lo, la]))
                               for la, lo in centres])
    region = fc.geometry().buffer(radius_m)
    stack = feature_stack(region.bounds(), year)
    neg = stack.addBands(negative_classes(region.bounds(), year))
    classes = sorted(per_class)
    got = neg.stratifiedSample(
        numPoints=0, classBand="cls", region=region, scale=30,
        classValues=classes, classPoints=[per_class[c] for c in classes],
        seed=seed, tileScale=4, geometries=True,
        dropNulls=True).getInfo()
    rows = []
    for f in got["features"]:
        lon, lat = f["geometry"]["coordinates"]
        rows.append({**f["properties"], "lat": lat, "lon": lon})
    return rows


def ee_fit_predict(bands, n_trees=N_TREES):
    """fit_predict(train_rows, test_rows) for core.verification.
    cross_validate. Labels are mapped to integers for Earth Engine and
    back; seed fixed so a re-run gives the same numbers."""
    def fit_predict(train, test):
        labels = sorted({r["label"] for r in train})
        code = {c: i for i, c in enumerate(labels)}

        def table(rows, with_cls):
            return ee.FeatureCollection([
                ee.Feature(None, {**{b: r[b] for b in bands},
                                  "i": i,
                                  **({"cls": code[r["label"]]}
                                     if with_cls else {})})
                for i, r in enumerate(rows)])
        clf = ee.Classifier.smileRandomForest(n_trees, seed=7).train(
            features=table(train, True), classProperty="cls",
            inputProperties=bands)
        res = (table(test, False).classify(clf)
               .reduceColumns(ee.Reducer.toList(2),
                              ["i", "classification"])
               .get("list").getInfo())
        out = [None] * len(test)
        for i, c in res:
            out[int(i)] = labels[int(c)]
        return out
    return fit_predict


def train_fit(rows, bands, n_trees=N_TREES):
    """The old 'Training accuracy': train and score on the same rows.
    Kept only to show how much it overstates the held-out figure."""
    fp = ee_fit_predict(bands, n_trees)
    pred = fp(rows, rows)
    ok = sum(p == r["label"] for p, r in zip(pred, rows))
    return ok / len(rows) if rows else None
