import datetime as dt
import json
import random

import pytest

from core import verification as V


def _nn_factory(feature):
    """1-nearest-neighbour on one feature: memorises perfectly."""
    def factory(bands):
        def fp(train, test):
            return [min(train, key=lambda r: abs(r[feature] - t[feature])
                        )["label"] for t in test]
        return fp
    factory.train_fit = lambda rows, bands: sum(
        p == r["label"] for p, r in zip(factory(bands)(rows, rows), rows)
    ) / len(rows)
    return factory


def _villages(n_vill=30, per=8, separable=False, seed=0):
    """Fields in villages ~11 km apart. Crop is random per village; the
    feature is either the village's own 'look' (location signal only)
    or the crop's look (real signal)."""
    rnd = random.Random(seed)
    rows = []
    for v in range(n_vill):
        crop = rnd.choice(["Maize", "Turmeric"])
        look = rnd.random()
        for k in range(per):
            f = ({"Maize": 0.2, "Turmeric": 0.8}[crop] + rnd.gauss(0, 0.05)
                 if separable else look + rnd.gauss(0, 0.001))
            rows.append({"label": crop, "lat": 12 + 0.1 * (v // 6),
                         "lon": 76 + 0.1 * (v % 6) + 0.001 * k, "f": f})
    return rows


def test_blocked_cv_exposes_memorising_training_fit():
    """The scientific point: a model that memorises villages scores
    ~100% on its own training points but near chance on new villages."""
    rows = _villages()
    fac = _nn_factory("f")
    from jobs.crop_accuracy import evaluate
    res = evaluate(rows, fac([]))
    assert fac.train_fit(rows, []) == 1.0
    assert res["metrics"]["overall"]["value"] < 0.75
    assert res["folds"] == 5 and res["blocks"] >= 30   # some villages
    #                                                     straddle a block edge


def test_blocked_cv_rewards_real_signal():
    from jobs.crop_accuracy import evaluate
    res = evaluate(_villages(separable=True), _nn_factory("f")([]))
    assert res["metrics"]["overall"]["value"] > 0.95


def test_one_block_is_refused():
    from jobs.crop_accuracy import evaluate
    rows = [{"label": "Maize", "lat": 14.5, "lon": 75.5, "f": 0.1},
            {"label": "Chilli", "lat": 14.5001, "lon": 75.5, "f": 0.9}]
    assert "one 5 km block" in evaluate(rows, None)["skipped"]


def test_cross_validate_keeps_folds_apart():
    rows = [{"label": i % 2, "x": i} for i in range(6)]
    seen = []

    def fp(train, test):
        seen.append(({r["x"] for r in train}, {r["x"] for r in test}))
        return [0] * len(test)
    y, p = V.cross_validate(rows, [0, 0, 1, 1, 2, 2], fp)
    assert len(y) == 6
    assert all(not (tr & te) for tr, te in seen)


# --------------------------------------------------------------- job

@pytest.fixture
def fakes(monkeypatch):
    from core import sheets
    monkeypatch.setattr(sheets, "is_enabled", lambda: False)
    rnd = random.Random(1)
    signal = {"Maize": 0.2, "LongDuration": 0.5, "Seasonal": 0.8,
              "Coconut": 0.9}

    def sampler(points, year):
        return [{"pid": p["pid"], "NDVI_p50": signal.get(p["label"], 0.3)
                 + rnd.gauss(0, 0.03), "VH": -14.0} for p in points]

    def neg_sampler(centres, year, per_class):
        out = []
        for c, n in per_class.items():
            for i in range(min(n, 10)):
                la, lo = centres[i % len(centres)]
                out.append({"cls": c, "lat": la + 0.01, "lon": lo,
                            "NDVI_p50": 0.1 * c / 6 + rnd.gauss(0, .01),
                            "VH": -14.0})
        return out
    return _nn_factory("NDVI_p50"), sampler, neg_sampler


def test_job_end_to_end_and_monthly_skip(con, fakes, monkeypatch):
    import jobs.crop_accuracy as jc
    fac, sampler, neg = fakes
    res = jc.run(con, fac, sampler, neg)
    assert res["status"] == "ok", res
    snap = json.loads(con.execute("SELECT json FROM accuracy_snapshot "
                                  "WHERE kind='crop_map'").fetchone()[0])
    field, coco = snap["models"]
    assert set(field["metrics"]["classes"]) == {"Maize", "LongDuration",
                                                "Seasonal"}
    # the one Fallow point shares its GPS with a chilli plot (same
    # field, earlier visit) and is de-duplicated away
    assert "Coconut" not in field["metrics"]["classes"]
    assert field["year"] == 2026 and field["n_points"] == 41
    assert coco["metrics"]["per_class"]["Coconut"]["n"] == 150
    assert "Dynamic World" in coco["note"]
    assert field["train_fit"] == 1.0
    again = jc.run(con, fac, sampler, neg)           # within 28 days
    assert again["rows"] == 0 and "next after" in again["detail"]


def test_job_does_not_save_when_everything_fails(con, fakes):
    import jobs.crop_accuracy as jc
    fac, _, neg = fakes

    def broken(points, year):
        raise RuntimeError("Earth Engine quota")
    res = jc.run(con, fac, broken, neg)
    assert res["status"] == "error" and "quota" in res["detail"]
    assert con.execute("SELECT COUNT(*) FROM accuracy_snapshot"
                       ).fetchone()[0] == 0          # retried tomorrow


def test_page_shows_crop_section(con, fakes):
    import jobs.crop_accuracy as jc
    from core import accuracy_page
    jc.run(con, *fakes)
    on, snap = con.execute("SELECT computed_on, json FROM "
                           "accuracy_snapshot").fetchone()
    html = accuracy_page.crop_section(json.loads(snap), on)
    assert "Annual field crops" in html and "Coconut map" in html
    assert "spatial folds" in html and "Training-fit figure" in html
