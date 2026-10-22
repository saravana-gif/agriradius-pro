"""Monthly held-out accuracy of the crop maps -> accuracy_snapshot
('crop_map'), shown on the "How often are we right?" page.

Replaces the app's "Training accuracy" (trained and scored on the same
points - always flattering) with a spatially blocked cross-validation:
points are grouped into ~5 km blocks, blocks are split into folds, and
each fold is predicted by a model trained only on the OTHER folds. So
a village's fields never help score themselves, which is how the map is
used: on villages it has not seen.

Two models, reported separately because their labels differ in kind:

1. Annual field crops - GPS field points logged by staff
   (LabeledPoints Sheet tab or data/ground_truth/labeled_points.csv,
   plus data/ground_truth/maize_gt.csv): maize vs turmeric/ginger vs
   chilli etc., in the app's crop groups. Coconut rows there are
   village centres from the FRUITS survey, not fields, so they are
   left out of this model.
2. Coconut - FRUITS/Bhoomi coconut villages (village centres) vs
   Dynamic World "clearly not coconut" samples, as the app trains it.
   Only RECALL is real here (share of known coconut villages found):
   the negatives are Dynamic World's opinion, not ground truth, so
   precision is reported as agreement with Dynamic World and labelled
   so.

Runs inside the daily group but only does work when the last result
is MIN_AGE_DAYS old (one small Earth Engine batch a month).
"""

import datetime
import json
import logging
import random

import pandas as pd

from config import PROJECT_ROOT
from core import verification as V

log = logging.getLogger("jobs.crop_accuracy")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
MIN_AGE_DAYS = 28
K_FOLDS = 5
BLOCK_KM = 5.0
MIN_PER_CLASS = 3        # fewer labelled points: class left out
COCONUT_POINTS = 150
NEG_CENTRES = 50
NEG_PER_CLASS = {2: 140, 3: 100, 4: 50, 5: 40, 6: 90}
GT_DIR = PROJECT_ROOT / "data" / "ground_truth"
META = {"pid", "label", "lat", "lon", "cls", "system:index"}


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


# --------------------------------------------------------------- labels

def field_points():
    """[(lat, lon, group, year)] GPS field points, deduplicated to
    ~10 m, coconut village centres excluded."""
    from core import sheets
    from core.ground_truth import LABELED_CSV, LABELED_SHEET
    from gee.classifier import CROP_GROUPS
    df = None
    if sheets.is_enabled():
        try:
            df = sheets.read_existing(LABELED_SHEET)
        except Exception as e:
            log.warning("LabeledPoints tab unreadable (%s) - using CSV",
                        type(e).__name__)
    if df is None or df.empty:
        df = pd.read_csv(LABELED_CSV)
    df = df[df["Crop"].astype(str).str.strip() != "Coconut"]
    rows = [(float(r.Latitude), float(r.Longitude),
             CROP_GROUPS.get(str(r.Crop).strip()), str(r.Date or ""))
            for r in df.itertuples()]
    mz = pd.read_csv(GT_DIR / "maize_gt.csv")
    rows += [(float(r.lat), float(r.lon), "Maize", str(r.date))
             for r in mz.itertuples()]
    seen, out = set(), []
    for lat, lon, grp, date in rows:
        key = (round(lat, 4), round(lon, 4))
        if not grp or key in seen or lat != lat:
            continue
        seen.add(key)
        year = int(date[:4]) if date[:4].isdigit() else None
        out.append((lat, lon, grp, year))
    return out


def coconut_points(n=COCONUT_POINTS, seed=1):
    df = pd.read_csv(GT_DIR / "coconut_gt_expanded.csv")
    df = df.sample(min(n, len(df)), random_state=seed)
    return list(zip(df["lat"], df["lon"]))


# ------------------------------------------------------------ evaluation

def evaluate(rows, fit_predict, k=K_FOLDS, block_km=BLOCK_KM):
    """Spatially blocked CV on rows ({label, lat, lon, bands...}).
    Returns the snapshot fields for one model."""
    blocks = V.spatial_blocks([(r["lat"], r["lon"]) for r in rows],
                              block_km)
    k = min(k, len(set(blocks)))
    if k < 2:
        return {"skipped": "all labelled points sit in one "
                           f"{block_km:g} km block - collect points in "
                           "more villages"}
    folds = V.assign_folds(blocks, [r["label"] for r in rows], k)
    y, p = V.cross_validate(rows, folds, fit_predict)
    classes, m = V.confusion_matrix(y, p)
    return {"metrics": V.class_metrics(classes, m), "folds": k,
            "blocks": len(set(blocks)), "block_km": block_km}


def _bands(rows):
    keys = None
    for r in rows:
        ks = {k for k, v in r.items() if k not in META and v is not None}
        keys = ks if keys is None else keys & ks
    return sorted(keys or [])


def field_model(fit_factory, sampler, today):
    pts = field_points()
    counts = pd.Series([g for *_, g, _ in pts]).value_counts()
    keep = set(counts[counts >= MIN_PER_CLASS].index)
    dropped = {g: int(n) for g, n in counts.items() if g not in keep}
    pts = [p for p in pts if p[2] in keep]
    model = {"name": "Annual field crops (trained crop map)",
             "note": f"{len(pts)} GPS field points; groups with fewer "
                     f"than {MIN_PER_CLASS} points left out: "
                     f"{dropped or 'none'}"}
    if len(keep) < 2:
        model["skipped"] = "needs at least two crop groups with points"
        return model
    years = [p[3] for p in pts if p[3]]
    year = max(set(years), key=years.count) if years else today.year
    labelled = [{"pid": i, "lat": la, "lon": lo, "label": g}
                for i, (la, lo, g, _) in enumerate(pts)]
    feats = {r["pid"]: r for r in sampler(labelled, year)}
    rows = [{**feats[p["pid"]], **p} for p in labelled if p["pid"] in feats]
    model.update(year=year, n_points=len(rows),
                 no_imagery=len(labelled) - len(rows))
    bands = _bands(rows)
    model.update(evaluate(rows, fit_factory(bands)))
    if "metrics" in model:
        model["train_fit"] = fit_factory.train_fit(rows, bands)
    return model


def coconut_model(fit_factory, sampler, neg_sampler, today):
    year = today.year - 1                 # perennial: last full year
    coco = coconut_points()
    labelled = [{"pid": i, "lat": la, "lon": lo, "label": "Coconut"}
                for i, (la, lo) in enumerate(coco)]
    feats = {r["pid"]: r for r in sampler(labelled, year)}
    rows = [{**feats[p["pid"]], **p} for p in labelled if p["pid"] in feats]
    centres = random.Random(2).sample(coco, min(NEG_CENTRES, len(coco)))
    from gee.classifier import NEGATIVE_CLASSES
    for r in neg_sampler(centres, year, NEG_PER_CLASS):
        r["label"] = f"{NEGATIVE_CLASSES[int(r['cls'])]} (Dynamic World)"
        rows.append(r)
    model = {"name": "Coconut map",
             "note": "Coconut = FRUITS survey village centres (real); "
                     "other classes = Dynamic World land cover, not "
                     "ground truth. Trust the coconut 'Found' figure; "
                     "'Right (of mapped)' only measures agreement with "
                     "Dynamic World.",
             "year": year, "n_points": len(rows)}
    bands = _bands(rows)
    model.update(evaluate(rows, fit_factory(bands)))
    if "metrics" in model:
        model["train_fit"] = fit_factory.train_fit(rows, bands)
    return model


class _EEFactory:
    """fit_predict factory backed by Earth Engine (the app's RF)."""

    def __call__(self, bands):
        from gee.accuracy import ee_fit_predict
        return ee_fit_predict(bands)

    @staticmethod
    def train_fit(rows, bands):
        from gee.accuracy import train_fit
        return train_fit(rows, bands)


def run(con, factory=None, sampler=None, neg_sampler=None, force=False):
    today = datetime.datetime.now(IST).date()
    last = con.execute("SELECT MAX(computed_on) FROM accuracy_snapshot "
                       "WHERE kind='crop_map'").fetchone()[0]
    if (last and not force and (today - datetime.date.fromisoformat(
            last)).days < MIN_AGE_DAYS):
        return {"rows": 0, "status": "ok",
                "detail": f"last measured {last}; next after "
                          f"{MIN_AGE_DAYS} days"}
    if factory is None:
        from jobs import headless
        headless.init_ee()
        from gee import accuracy
        factory, sampler = _EEFactory(), accuracy.sample_features
        neg_sampler = accuracy.sample_negatives
    models, problems = [], []
    for name, fn, args in (
            ("field", field_model, (factory, sampler, today)),
            ("coconut", coconut_model,
             (factory, sampler, neg_sampler, today))):
        try:
            models.append(fn(*args))
        except Exception as e:
            log.exception("%s model failed", name)
            problems.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
    if not models:              # nothing ran (e.g. Earth Engine down):
        return {"rows": 0, "status": "error",   # retry tomorrow
                "detail": "; ".join(problems)}
    snap = {"models": models, "method":
            f"spatially blocked {K_FOLDS}-fold cross-validation, "
            f"{BLOCK_KM:g} km blocks"}
    con.execute("INSERT INTO accuracy_snapshot VALUES (?, 'crop_map', ?, ?) "
                "ON CONFLICT (computed_on, kind) DO UPDATE SET json="
                "excluded.json, computed_at=excluded.computed_at",
                (today.isoformat(), json.dumps(snap), _utc_now()))
    con.commit()
    parts = []
    for m in models:
        if "metrics" in m:
            ov = m["metrics"]["overall"]
            parts.append(f"{m['name']}: held-out {ov['value']:.0%} "
                         f"(n={ov['n']}, training fit "
                         f"{(m.get('train_fit') or 0):.0%})")
        else:
            parts.append(f"{m['name']}: {m.get('skipped')}")
    detail = "; ".join(parts + problems)
    return {"rows": len(models), "detail": detail,
            "status": "partial" if problems else "ok"}
