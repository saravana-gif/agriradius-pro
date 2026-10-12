import datetime as dt
import json
import sqlite3

import pytest

D = dt.date


def _seed(con, as_of, rain=None, fc_rain=None, crops="chilli;maize"):
    con.execute("INSERT OR REPLACE INTO villages VALUES "
                "('byadgi','Byadgi','Haveri','Karnataka',14.67,75.49,?,"
                "'test','now')", (crops,))
    rain = rain or {}
    feats = {"obs_through": (as_of - dt.timedelta(days=1)).isoformat(),
             "obs_lag_days": 1, "season": "ne", "ne_start": "2026-10-01",
             "season_cum_mm": 40.0, "season_normal_mm": 120.0,
             "season_dep_pct": -66.7, "season_category": "large_deficient",
             "dry_days": 12, "spi3": -0.4, "rain_8_28d_mm": 35.0}
    feats.update(rain)
    con.execute("INSERT OR REPLACE INTO village_features VALUES "
                "('byadgi', ?, 'rain', ?, ?, 'now')",
                (as_of.isoformat(), json.dumps(feats),
                 json.dumps({"rain_sources": ["imd"]})))
    fc_rain = fc_rain or [0.0] * 10
    for k, mm in enumerate(fc_rain):
        con.execute("INSERT OR REPLACE INTO forecast_daily (village_id, "
                    "issued_on, provider, date, rain_mm, tmax, tmin, "
                    "rh_max, rh_min, fetched_at) VALUES ('byadgi', ?, "
                    "'ecmwf_open', ?, ?, 32, 21, 80, 40, 'now')",
                    (as_of.isoformat(),
                     (as_of + dt.timedelta(days=k)).isoformat(), mm))
    con.commit()


@pytest.fixture
def job(monkeypatch):
    import jobs.alerts as ja
    monkeypatch.setattr("jobs.run.git_sha", lambda: "abc1234")

    def at(day):
        class _DT(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt.datetime(day.year, day.month, day.day, 5, 30,
                                   tzinfo=tz)
        monkeypatch.setattr(ja.datetime, "datetime", _DT)
    ja.at = at
    return ja


def _alerts(con):
    return con.execute("SELECT as_of, crop, rule_id, severity, shareable, "
                       "git_sha FROM alert ORDER BY as_of, rule_id"
                       ).fetchall()


def test_alerts_max_two_per_day_worst_first(con, job):
    day = D(2026, 11, 26)            # std week 48, chilli drying window
    _seed(con, day, fc_rain=[6.0, 5.0, 4.0] + [0.0] * 7)
    job.at(day)
    res = job.run(con)
    assert res["status"] == "ok", res
    got = _alerts(con)
    # Fired: season red, chilli drying red (15 mm/3d), maize drying
    # risk (15 mm). Cap 2 -> the two reds; thrips needs a dry forecast.
    assert [(c, r, s) for _, c, r, s, _, _ in got] == [
        ("chilli", "chilli_drying_rain_red", "red"),
        ("", "season_rain_red", "red")]
    assert all(sh == 0 and sha == "abc1234" for *_, sh, sha in got)
    row = con.execute("SELECT text_en, features_json, trace_json, "
                      "vintage_json FROM alert WHERE rule_id="
                      "'season_rain_red'").fetchone()
    assert "Byadgi: NE monsoon rain since 1 Oct is 40 mm against a " \
           "usual 120 mm (-67%" in row[0]
    assert json.loads(row[1])["dry_days"] == 12
    assert json.loads(row[3])["forecast_provider"] == "ecmwf_open"
    assert con.execute("SELECT COUNT(*) FROM alert_event WHERE "
                       "event='created'").fetchone()[0] == 2
    # same day again: nothing new (cooldown + cap), no duplicates
    assert job.run(con)["rows"] == 0


def test_cooldown_and_escalation(con, job):
    day = D(2026, 10, 20)
    _seed(con, day, rain={"season_dep_pct": -25.0, "dry_days": 3},
          crops="turmeric")
    job.at(day)
    job.run(con)
    assert [r[2] for r in _alerts(con)] == ["season_rain_amber"]
    day2 = day + dt.timedelta(days=3)          # still amber: cooldown
    _seed(con, day2, rain={"season_dep_pct": -28.0, "dry_days": 6},
          crops="turmeric")
    job.at(day2)
    assert job.run(con)["rows"] == 0
    day3 = day + dt.timedelta(days=4)          # turns red: escalates
    _seed(con, day3, rain={"season_dep_pct": -45.0, "dry_days": 6},
          crops="turmeric")
    job.at(day3)
    assert job.run(con)["rows"] == 1
    assert _alerts(con)[-1][2:4] == ("season_rain_red", "red")
    day4 = day3 + dt.timedelta(days=7)         # red's cooldown over
    _seed(con, day4, rain={"season_dep_pct": -25.0, "dry_days": 3},
          crops="turmeric")
    job.at(day4)
    assert job.run(con)["rows"] == 1


def test_missing_data_fires_nothing(con, job):
    day = D(2026, 11, 26)
    _seed(con, day, rain={"season_dep_pct": None, "dry_days": None,
                          "spi3": None},
          fc_rain=[None] * 10)
    job.at(day)
    assert job.run(con)["rows"] == 0


def test_stale_forecast_is_ignored(con, job):
    day = D(2026, 11, 26)
    _seed(con, day - dt.timedelta(days=3), fc_rain=[20.0] * 10,
          rain={"season_dep_pct": 5.0, "dry_days": 0})
    job.at(day)
    res = job.run(con)
    assert res["rows"] == 0 and "without a fresh forecast" in res["detail"]


def test_alert_log_is_append_only(con, job):
    day = D(2026, 11, 26)
    _seed(con, day)
    job.at(day)
    job.run(con)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE alert SET severity='green'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM alert")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM alert_event")


def test_bad_rule_is_skipped_and_reported(con, job, tmp_path,
                                          monkeypatch):
    from core import rules
    p = tmp_path / "rules.toml"
    p.write_text(rules.RULES_PATH.read_text() + '''
[[rule]]
id = "broken"
title = "x"
kind = "pest"
severity = "red"
source = "x"
all = [["dry_days", ">=", 1]]
draft_en = "Spray now, it will work."
''')
    monkeypatch.setattr(rules, "RULES_PATH", p)
    _seed(con, D(2026, 11, 26))
    job.at(D(2026, 11, 26))
    res = job.run(con)
    assert res["status"] == "partial" and "broken" in res["detail"]
    assert "broken" not in [r[2] for r in _alerts(con)]
