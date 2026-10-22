import datetime as dt
import json

import pytest

from core import verification as V

D = dt.date


def test_wilson_known_values():
    lo, hi = V.wilson(0, 10)
    assert lo == 0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = V.wilson(8, 10)
    assert (lo, hi) == (pytest.approx(0.490, abs=1e-3),
                        pytest.approx(0.943, abs=1e-3))
    assert V.wilson(0, 0) == (None, None)


def test_finley_tornado_table():
    """Finley (1884), the textbook example (Jolliffe & Stephenson):
    a=28, b=72, c=23, d=2680."""
    s = V.categorical_scores({"a": 28, "b": 72, "c": 23, "d": 2680})
    assert s["pod"]["value"] == pytest.approx(0.549, abs=1e-3)
    assert s["far"]["value"] == pytest.approx(0.720, abs=1e-3)
    assert s["csi"] == pytest.approx(0.228, abs=1e-3)
    assert s["bias"] == pytest.approx(1.961, abs=1e-3)
    assert s["hss"] == pytest.approx(0.355, abs=1e-3)
    assert s["accuracy"]["value"] == pytest.approx(0.966, abs=1e-3)


def test_contingency_and_mae():
    t = V.contingency([(True, True), (True, False), (False, True),
                       (False, False), (False, False)])
    assert t == {"a": 1, "b": 1, "c": 1, "d": 2}
    m = V.mae([(5, 2), (0, 4), (None, 3)])
    assert m == {"n": 2, "mae": 3.5, "me": -0.5}


def test_class_metrics():
    y = ["A"] * 10 + ["B"] * 10
    p = ["A"] * 8 + ["B"] * 2 + ["B"] * 9 + ["A"]
    classes, m = V.confusion_matrix(y, p)
    assert m == [[8, 2], [1, 9]]
    r = V.class_metrics(classes, m)
    assert r["overall"]["value"] == 0.85
    # kappa = (0.85 - 0.5) / (1 - 0.5)
    assert r["kappa"] == pytest.approx(0.70)
    assert r["per_class"]["A"]["producers"]["value"] == 0.8
    assert r["per_class"]["A"]["users"]["value"] == pytest.approx(8 / 9)
    assert r["balanced_accuracy"] == pytest.approx(0.85)
    assert r["per_class"]["A"]["enough"]


def test_spatial_folds_keep_blocks_together_and_spread_classes():
    pts, labels = [], []
    for v in range(20):                  # 20 villages, 10 km apart
        lat, lon = 12.0 + 0.09 * (v // 5), 76.0 + 0.09 * (v % 5)
        for k in range(5):               # 5 fields within ~300 m
            pts.append((lat + 0.001 * k, lon))
            labels.append("Coconut" if v % 2 else "Maize")
    blocks = V.spatial_blocks(pts, block_km=5)
    folds = V.assign_folds(blocks, labels, k=5)
    for b in set(blocks):                # a village never split
        assert len({f for f, bb in zip(folds, blocks) if bb == b}) == 1
    for f in range(5):                   # every fold tests both crops
        assert {lab for lab, ff in zip(labels, folds) if ff == f} == {
            "Coconut", "Maize"}


@pytest.mark.parametrize("k,n,want", [(3, 4, "too_few"), (2, 20, "retire"),
                                      (11, 20, "watch"), (15, 20, "ok")])
def test_verdict_for_rate(k, n, want):
    assert V.verdict_for_rate(V.proportion(k, n)) == want


# --------------------------------------------------------- the job

@pytest.fixture
def today(monkeypatch):
    import jobs.verify as jv

    class _DT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 12, 20, 5, 30, tzinfo=tz)
    monkeypatch.setattr(jv.datetime, "datetime", _DT)
    return jv


def _alert(con, aid, as_of, rule_id, vid="byadgi"):
    con.execute("INSERT INTO alert VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?)", (aid, "now", as_of, vid, "chilli", rule_id,
                             rule_id, "h", "red", "harvest", "t", "x", "s",
                             "", 0, "{}", "{}", "{}", None))


def _obs(con, day, mm, vid="byadgi", source="imd"):
    con.execute("INSERT INTO rain_daily VALUES (?,?,?,?,'now')",
                (vid, day.isoformat(), source, mm))


def test_verify_job(con, today):
    # IMD rain: dry, then 14 mm on 1-3 Dec, dry again
    for k in range(49):                 # 1 Nov .. 19 Dec (yesterday)
        day = D(2026, 11, 1) + dt.timedelta(days=k)
        _obs(con, day, 5.0 if D(2026, 12, 1) <= day <= D(2026, 12, 3)
             else 0.0)
    _obs(con, D(2026, 12, 2), 30.0, source="open_meteo")   # ignored
    _alert(con, "A-HIT", "2026-12-01", "chilli_drying_rain_red")
    _alert(con, "A-MISS", "2026-11-10", "chilli_drying_rain_red")
    _alert(con, "A-WAIT", "2026-12-19", "chilli_drying_rain_red")
    _alert(con, "A-THRIPS", "2026-11-20", "chilli_black_thrips")
    # forecasts issued 30 Nov: rain on 1-3 Dec at lead 1-3
    for k in range(8):
        day = D(2026, 11, 30) + dt.timedelta(days=k)
        con.execute("INSERT INTO forecast_daily (village_id, issued_on, "
                    "provider, date, rain_mm, fetched_at) VALUES "
                    "('byadgi','2026-11-30','ecmwf_open',?,?,'now')",
                    (day.isoformat(), 6.0 if 1 <= k <= 2 else 0.0))
    # officer check-backs: thrips rule 2 yes / 10 no -> retire
    for i in range(12):
        aid = f"T{i}"
        _alert(con, aid, "2026-11-21", "chilli_black_thrips",
               vid=f"v{i}")
        con.execute("INSERT INTO alert_event (alert_id, at, event, "
                    "detail_json) VALUES (?, 'now', 'checkback', ?)",
                    (aid, json.dumps({"verdict": "yes" if i < 2 else "no"})))
    con.commit()

    res = today.run(con)
    assert res["status"] == "ok", res
    ev = dict(con.execute(
        "SELECT alert_id, json_extract(detail_json, '$.outcome') FROM "
        "alert_event WHERE event='verified'").fetchall())
    assert ev == {"A-HIT": "hit", "A-MISS": "false_alarm"}
    assert "chilli_black_thrips" in res["detail"]       # retire flagged
    today.run(con)                                      # no duplicates
    assert con.execute("SELECT COUNT(*) FROM alert_event WHERE "
                       "event='verified'").fetchone()[0] == 2

    card = json.loads(con.execute(
        "SELECT json FROM accuracy_snapshot WHERE kind='alerts'"
    ).fetchone()[0])
    by = {r["rule_id"]: r for r in card["rules"]}
    th = by["chilli_black_thrips"]
    assert th["checkbacks"] == 12 and th["status"] == "retire"
    dr = by["chilli_drying_rain_red"]
    assert dr["observed"]["k"] == 1 and dr["observed"]["n"] == 2
    assert dr["observed_status"] == "too_few"

    fc = json.loads(con.execute(
        "SELECT json FROM accuracy_snapshot WHERE kind='forecast'"
    ).fetchone()[0])
    p = fc["providers"]["ecmwf_open"]
    # lead 1 (1 Dec): forecast 6 mm, IMD 5 mm -> hit at 2.5 mm
    assert p["leads"]["1"]["rain_2_5"]["pod"]["value"] == 1.0
    # lead 3 (3 Dec): forecast 0, IMD 5 mm -> miss
    assert p["leads"]["3"]["rain_2_5"]["pod"]["value"] == 0.0
    # 3-day total from the 30 Nov issue: fc 12 mm, IMD 10 mm -> hit
    assert p["three_day_10mm"]["pod"]["value"] == 1.0
    assert fc["n_pairs"] == 8                  # fallback rain not used


def test_obs_features_wait_for_complete_window():
    from jobs.verify import obs_features
    obs = {D(2026, 12, 1): 0.0, D(2026, 12, 2): 3.0}
    f = obs_features(obs, D(2026, 12, 1))
    assert "obs_rain_3d_mm" not in f and f["obs_dry_run_days"] == 1
    obs[D(2026, 12, 3)] = 9.0
    f = obs_features(obs, D(2026, 12, 1))
    assert f["obs_rain_3d_mm"] == 12.0 and f["obs_max_rain_3d_mm"] == 9.0


def test_rule_verify_must_use_observed_features():
    from core import rules
    with pytest.raises(rules.RuleError, match="obs_"):
        rules._parse({"id": "x", "title": "t", "kind": "harvest",
                      "severity": "red", "source": "s",
                      "draft_en": "Conditions favour x.",
                      "all": [["fc_rain_3d_mm", ">=", 10]],
                      "verify": [["fc_rain_3d_mm", ">=", 10]]})


def test_accuracy_page(con, today, monkeypatch, tmp_path):
    import jobs.publish as jp
    monkeypatch.setattr(jp, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(jp, "SECRET_FILE", tmp_path / "secret")
    monkeypatch.setattr(jp, "INDEX_FILE", tmp_path / "index.json")
    for i in range(12):
        _alert(con, f"T{i}", "2026-11-21", "chilli_black_thrips",
               vid=f"v{i}")
        con.execute("INSERT INTO alert_event (alert_id, at, event, "
                    "detail_json) VALUES (?, 'now', 'checkback', ?)",
                    (f"T{i}", json.dumps({"verdict": "yes"})))
    con.execute("INSERT INTO villages VALUES ('v0','V0','D','Karnataka',"
                "12,77,'chilli','t','now')")
    con.commit()
    today.run(con)
    jp.run(con)
    page = (tmp_path / "public" / "p" /
            f"{jp.token('accuracy', 'all')}.html").read_text()
    assert "How often are we right?" in page and "noindex" in page
    assert "100% <span class=m>(76-100%)</span>" in page   # 12/12, Wilson
    assert "Not measured yet" in page                       # crop map
    assert len(page.encode()) < 50_000
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["accuracy"].endswith(jp.token("accuracy", "all"))
