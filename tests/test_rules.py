import datetime as dt
import json
import sqlite3

import pytest

from core import features, rules

D = dt.date


def test_starter_rules_load_and_pass_lint():
    rs, errors = rules.load()
    assert errors == []
    ids = {r.id for r in rs}
    assert {"season_rain_red", "season_rain_amber", "chilli_black_thrips",
            "chilli_drying_rain_red", "chilli_drying_rain_amber",
            "turmeric_leaf_blotch", "maize_drying_risk",
            "maize_drying_window"} <= ids
    assert not any(r.approved for r in rs)        # all drafts until signed


@pytest.mark.parametrize("text,kind,bad", [
    ("Conditions favour thrips. Scout before spraying.", "pest", None),
    ("Conditions favour thrips.", "pest", "scout before spraying"),
    ("Thrips are coming.", "weather", "conditions favour"),
    ("Conditions favour rain; it will rain.", "weather", "certainty"),
    ("Conditions favour mould. Use Confidor.", "harvest", "brand"),
    ("Conditions favour mould. Sell at Rs 9000.", "harvest", "price"),
    ("Conditions favour mould. OneRoot pays ₹50.", "harvest", "brand"),
])
def test_lint(text, kind, bad):
    probs = rules.lint_text(text, kind)
    if bad is None:
        assert probs == []
    else:
        assert any(bad in p for p in probs), probs


def _rule(**kw):
    raw = {"id": "t", "title": "t", "kind": "weather", "severity": "amber",
           "source": "s", "draft_en": "Conditions favour x in {village}.",
           "all": [["a", ">=", 1]]}
    raw.update(kw)
    return rules._parse(raw)


def test_rule_validation_rejects_code_and_bad_shapes():
    with pytest.raises(rules.RuleError):
        _rule(all=[["a", "__import__('os')", 1]])
    with pytest.raises(rules.RuleError):
        _rule(all=[["a", ">="]])
    with pytest.raises(rules.RuleError):
        _rule(draft_en="Conditions favour {village.__class__}")
    with pytest.raises(rules.RuleError):
        _rule(draft_en="Conditions favour {fc:>10}")
    with pytest.raises(rules.RuleError):
        _rule(surprise=1)
    with pytest.raises(rules.RuleError):
        _rule(source=" ")


def test_evaluate_missing_feature_is_false():
    r = _rule(all=[["a", ">=", 1]], any=[["b", "<", 0], ["c", "in", [1]]])
    assert rules.evaluate(r, {"a": 2, "c": 1})[0]
    assert not rules.evaluate(r, {"a": None, "c": 1})[0]
    assert not rules.evaluate(r, {"a": 2})[0]          # any: none known
    fired, trace = rules.evaluate(r, {"a": 2, "b": -1})
    assert fired and trace["any"][0] == ["b", "<", 0, -1, True]
    assert not rules.evaluate(r, {"a": "x"})[0]        # type mismatch


def test_active_on_windows():
    assert _rule(dates=["11-20", "03-31"]).active_on(D(2027, 1, 5))
    assert _rule(dates=["11-20", "03-31"]).active_on(D(2026, 11, 20))
    assert not _rule(dates=["11-20", "03-31"]).active_on(D(2026, 11, 19))
    assert not _rule(dates=["11-20", "03-31"]).active_on(D(2027, 4, 1))
    assert _rule(std_weeks=[44]).active_on(D(2026, 10, 29))
    assert not _rule(std_weeks=[44]).active_on(D(2026, 11, 5))
    assert _rule(months=[10]).active_on(D(2026, 10, 1))


def test_std_week():
    assert features.std_week(D(2026, 1, 1)) == 1
    assert features.std_week(D(2026, 3, 4)) == 9
    assert features.std_week(D(2024, 2, 29)) == 9
    assert features.std_week(D(2024, 3, 4)) == 9      # 8-day week 9
    assert features.std_week(D(2024, 3, 5)) == 10
    assert features.std_week(D(2026, 12, 31)) == 52
    assert features.std_week(D(2026, 11, 19)) == 47     # 19-25 Nov
    assert features.std_week(D(2026, 11, 18)) == 46


def test_render_formats_and_never_crashes():
    t = "{village}: {season_dep_pct} {fc_rain_3d_mm} mm {dry_days} {nope}"
    out = rules.render(t, {"village": "Erode", "season_dep_pct": -43.4,
                           "fc_rain_3d_mm": 7.25, "dry_days": 12})
    assert out == "Erode: -43% 7.2 mm 12 n/a"


def test_forecast_features_gaps_and_blotch():
    as_of = D(2026, 10, 20)
    daily = [{"date": (as_of + dt.timedelta(days=k)).isoformat(),
              "rain_mm": [0.0, 0.0, 12.0, 0.0, 0.0, 3.0, 0.0][k],
              "tmax": 31.0, "tmin": 21.0, "rh_max": 90.0, "rh_min": 60.0}
             for k in range(7)]
    hourly = []
    for k in range(7 * 8):                       # 3-hourly, ECMWF style
        t = dt.datetime(2026, 10, 20, 2, 30) + dt.timedelta(hours=3 * k)
        night = t.hour < 9
        hourly.append({"time": t.strftime("%Y-%m-%dT%H:%M"),
                       "temp": 22.0 if night else 29.0,
                       "rh": 90.0 if night else 60.0})
    f = features.forecast_features(daily, hourly, as_of)
    assert f["fc_rain_3d_mm"] == 12.0 and f["fc_max_rain_3d_mm"] == 12.0
    assert f["fc_rainy_days_7d"] == 2 and f["fc_dry_run_days"] == 2
    assert f["fc_rh_mean_7d"] == 75.0 and f["fc_tmax_mean_7d"] == 31.0
    # 02:30, 05:30 and 08:30 rows -> 9 h a day at 22 C / 90%
    assert f["fc_blotch_days_7d"] >= 6
    daily[1]["rain_mm"] = None                   # a gap is not 0 mm
    f = features.forecast_features(daily, hourly, as_of)
    assert f["fc_rain_3d_mm"] is None and f["fc_rain_7d_mm"] is None
    assert f["fc_dry_run_days"] == 1
