import datetime as dt
import json

import numpy as np
import pytest

from core.sources import rain as R


class _Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        pass


def _imd_grid(fill=0.0):
    from imdlib.util import GRIDS
    g = GRIDS["r025"]
    return np.full(g.shape, fill, dtype="<f4"), g


def test_imd_fetch_day_parses_grid_and_missing_cells(monkeypatch):
    from imdlib import util
    arr, g = _imd_grid(-999.0)
    i = int(round((11.341 - g.lat0) / g.step))
    j = int(round((77.717 - g.lon0) / g.step))
    arr[i, j] = 12.5                       # Erode cell
    k = int(round((14.673 - g.lat0) / g.step))
    m = int(round((75.487 - g.lon0) / g.step))
    arr[k, m + 1], arr[k - 1, m] = 4.0, 6.0   # Byadgi cell missing
    calls = []

    def fake_post(url, data, what, **kw):
        calls.append(data)
        return _Resp(arr.tobytes() if data["rain"] != "01012030" else b"")
    monkeypatch.setattr(util, "post", fake_post)

    imd = R.ImdRealtimeRain()
    grid = imd.fetch_day(dt.date(2026, 10, 10))
    assert calls[0] == {"rain": "10102026"}
    vals = imd.values_at(grid, [(11.341, 77.717), (14.673, 75.487),
                                (30.0, 95.0)])
    assert vals == [12.5, 5.0, None]       # neighbour mean; all-missing
    assert imd.fetch_day(dt.date(2030, 1, 1)) is None   # not published


def test_chirps_reads_points_from_geotiff(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    data = np.full((200, 160), 55.0, dtype="float32")
    data[10, 20] = -9999.0
    path = tmp_path / "chirps-v2.0.1990.07.tif"
    with rasterio.open(path, "w", driver="GTiff", height=200, width=160,
                       count=1, dtype="float32", crs="EPSG:4326",
                       nodata=-9999.0,
                       transform=from_origin(73.0, 19.0, 0.05, 0.05)) as ds:
        ds.write(data, 1)
    src = R.ChirpsMonthly(urls=(str(tmp_path / "missing-{y}.tif"),
                                str(tmp_path / "chirps-v2.0.{y}.{m:02d}.tif")))
    lat_bad = 19.0 - 10.5 * 0.05
    lon_bad = 73.0 + 20.5 * 0.05
    assert src.read_month(1990, 7, [(11.34, 77.72), (lat_bad, lon_bad)]) \
        == [55.0, None]
    with pytest.raises(RuntimeError):
        src.read_month(1991, 1, [(11.34, 77.72)])


class FakeImd:
    name = "imd"
    published_until = dt.date(2026, 10, 10)    # 11 Oct not out yet
    down = False

    def __init__(self):
        pass

    def fetch_day(self, day):
        if self.down:
            raise RuntimeError("connection refused")
        if day > self.published_until:
            return None
        return day

    def values_at(self, day, locs):
        mm = 1.0 if day >= dt.date(2026, 10, 1) else 4.0
        return [mm, None]          # 2nd village: IMD cell missing


class FakeFallback:
    def fetch(self, locs, days=92):
        out = {}
        for loc in locs:
            d = dt.date(2026, 10, 11)
            out[loc] = {(d - dt.timedelta(days=k)).isoformat(): 9.0
                        for k in range(days)}
        return out


class FakeChirps:
    def read_month(self, y, m, locs):
        if (y, m) == (1985, 2):
            raise RuntimeError("timeout")
        return [100.0 + y % 5 for _ in locs]


@pytest.fixture
def today(monkeypatch):
    import jobs.rain as jr

    class _DT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 10, 12, 5, 15, tzinfo=tz)
    monkeypatch.setattr(jr.datetime, "datetime", _DT)
    monkeypatch.setattr(jr, "ImdRealtimeRain", FakeImd)
    monkeypatch.setattr(jr, "OpenMeteoPastRain", FakeFallback)
    return jr


def test_rain_job_imd_then_fallback_then_features(con, villages, today):
    from jobs import rain_baseline as rb
    res = rb.run(con, source=FakeChirps(), budget=60)
    assert res["status"] == "partial" and "1985-02" in res["detail"]
    res = rb.run(con, source=FakeChirps(), budget=60)   # still failing
    assert con.execute("SELECT COUNT(DISTINCT year*100+month) FROM "
                       "rain_monthly_baseline").fetchone()[0] == 539

    res = today.run(con)
    assert res["status"] == "ok", res
    rows = con.execute("SELECT village_id, date, source, rain_mm FROM "
                       "rain_daily ORDER BY 1,2,3").fetchall()
    erode = [r for r in rows if r[0] == "erode"]
    # IMD from 1 Jun to 10 Oct, fallback only for 11 Oct (IMD late)...
    assert erode[0][1] == "2026-06-01"
    assert [r for r in erode if r[2] == "open_meteo"] == []
    # ...but the fallback is used once IMD is 2 days late:
    by = {(r[1], r[2]): r[3] for r in rows if r[0] == "byadgi"}
    assert by[("2026-10-01", "imd")] is None     # stored as NULL, not 0
    assert by[("2026-10-01", "open_meteo")] == 9.0
    assert ("2026-10-11", "open_meteo") not in by   # too fresh for fallback

    f = json.loads(con.execute(
        "SELECT features_json FROM village_features WHERE "
        "village_id='erode' AND kind='rain'").fetchone()[0])
    assert f["obs_through"] == "2026-10-10" and f["season"] == "ne"
    assert f["ne_cum_mm"] == 10.0 and f["ne_dep_pct"] < -60
    assert f["baseline_years"] == 45
    v = json.loads(con.execute(
        "SELECT vintage_json FROM village_features WHERE "
        "village_id='byadgi'").fetchone()[0])
    assert v["rain_sources"] == ["open_meteo"]


def test_rain_job_imd_down_uses_fallback_for_all_days(con, villages,
                                                      today):
    FakeImd.down = True
    try:
        res = today.run(con)
    finally:
        FakeImd.down = False
    assert res["status"] == "partial" and "IMD unreachable" in res["detail"]
    n = con.execute("SELECT COUNT(*) FROM rain_daily WHERE "
                    "source='open_meteo' AND village_id='erode' AND "
                    "date='2026-10-11'").fetchone()[0]
    assert n == 1
