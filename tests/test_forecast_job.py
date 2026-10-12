import pytest


class FakeProvider:
    name = "fake"

    def fetch_many(self, locations, days=16, hourly_hours=168):
        for loc in locations:
            yield loc, {
                "daily": [{"date": "2026-10-12", "rain_mm": None,
                           "tmax": 31.0}],
                "hourly": [{"time": "2026-10-12T00:00", "temp": 22.0,
                            "rh": 90.0}]}


def test_forecast_job_stores_rows_and_villages(con, villages, monkeypatch):
    import jobs.forecast as jf
    monkeypatch.setattr(jf, "get_provider", lambda: FakeProvider())
    res = jf.run(con)
    assert res["status"] == "ok" and "1 daily rain values" not in res
    assert con.execute("SELECT COUNT(*) FROM villages").fetchone()[0] == 2
    row = con.execute("SELECT provider, rain_mm, tmax FROM forecast_daily "
                      "WHERE village_id='erode'").fetchone()
    assert row == ("fake", None, 31.0)       # missing stays NULL
