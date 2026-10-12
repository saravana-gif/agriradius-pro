import datetime as dt

import numpy as np
import pytest

from core.sources import forecast as F

UTC = dt.timezone.utc


def _write_grib(path, fields):
    """fields: [(shortName, step, value_fn(lat, lon))] on a 1-deg global
    grid, written with eccodes like ECMWF open data (lat 90 -> -90)."""
    eccodes = pytest.importorskip("eccodes")
    lats = np.arange(90, -91, -1.0)
    lons = np.arange(-180, 180, 1.0)
    with open(path, "wb") as f:
        for short, step, fn in fields:
            h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
            for k, v in [("Ni", 360), ("Nj", 181),
                         ("latitudeOfFirstGridPointInDegrees", 90.0),
                         ("longitudeOfFirstGridPointInDegrees", -180.0),
                         ("latitudeOfLastGridPointInDegrees", -90.0),
                         ("longitudeOfLastGridPointInDegrees", 179.0),
                         ("iDirectionIncrementInDegrees", 1.0),
                         ("jDirectionIncrementInDegrees", 1.0),
                         ("jScansPositively", 0)]:
                eccodes.codes_set(h, k, v)
            eccodes.codes_set(h, "shortName", short)
            eccodes.codes_set(h, "endStep", step)
            vals = np.array([[fn(la, lo) for lo in lons] for la in lats])
            eccodes.codes_set_values(h, vals.ravel())
            eccodes.codes_write(h, f)
            eccodes.codes_release(h)


def test_read_points_nearest_cell_and_shortnames(tmp_path):
    p = tmp_path / "x.grib2"
    _write_grib(p, [("2t", 6, lambda la, lo: 273.15 + la + lo / 1000),
                    ("tp", 6, lambda la, lo: 0.004)])
    got = F.read_points(str(p), [(11.34, 77.72), (14.67, 75.49)])
    assert got[("2t", 6)] == pytest.approx(
        [273.15 + 11 + 0.078, 273.15 + 15 + 0.075])
    assert got[("tp", 6)] == pytest.approx([0.004, 0.004])


def _pts(base_steps3=range(3, 145, 3), steps6=range(150, 361, 6)):
    """Synthetic point series: 1 mm/h of rain on IST 13 Oct only,
    T = 30 C, Td = 20 C, max/min 31/24 C."""
    base = dt.datetime(2026, 10, 11, 12, tzinfo=UTC)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    pts, tp, prev = {}, 0.0, 0
    for s in list(base_steps3) + list(steps6):
        hrs = s - prev
        mid = base + dt.timedelta(hours=prev + hrs / 2)
        if mid.astimezone(ist).date() == dt.date(2026, 10, 13):
            tp += hrs * 0.001
        pts[("tp", s)] = tp
        pts[(f"mx2t{hrs}", s)] = 273.15 + 31
        pts[(f"mn2t{hrs}", s)] = 273.15 + 24
        if s <= 168:
            pts[("2t", s)] = 273.15 + 30
            pts[("2d", s)] = 273.15 + 20
        prev = s
    return base, pts


def test_to_rows_ist_days_complete_only():
    base, pts = _pts()
    out = F.to_rows(base, pts)
    days = {d["date"]: d for d in out["daily"]}
    # run 12Z 11 Oct = 17:30 IST: 11 Oct is partial and dropped; 15 days
    # of steps end 12Z 26 Oct -> last complete IST day is 25 Oct.
    assert min(days) == "2026-10-12" and max(days) == "2026-10-25"
    assert len(days) == 14
    assert days["2026-10-13"]["rain_mm"] == 24.0
    assert days["2026-10-12"]["rain_mm"] == 0.0
    assert days["2026-10-14"]["tmax"] == 31.0
    assert days["2026-10-14"]["tmin"] == 24.0
    assert days["2026-10-14"]["rh_max"] == pytest.approx(55.1, abs=0.1)
    assert days["2026-10-20"]["rh_max"] is None      # beyond 7-day RH
    assert days["2026-10-14"]["rain_prob"] is None   # never invented
    assert out["hourly"][0]["time"] == "2026-10-11T20:30"
    assert all(h["time"].endswith(":30") for h in out["hourly"])


def test_to_rows_missing_field_is_none_not_zero():
    base, pts = _pts()
    pts[("tp", 45)] = None       # GRIB missing value on 13 Oct
    days = {d["date"]: d for d in F.to_rows(base, pts)["daily"]}
    assert days["2026-10-13"]["rain_mm"] is None


class _Boom(F.ForecastProvider):
    name = "boom"

    def fetch_many(self, locations, days=16, hourly_hours=168):
        raise RuntimeError("503 slow down")
        yield  # pragma: no cover


class _Ok(F.ForecastProvider):
    name = "ok"

    def fetch_many(self, locations, days=16, hourly_hours=168):
        for loc in locations:
            yield loc, {"daily": [], "hourly": []}


def test_fallback_provider_uses_next_and_records_error():
    p = F.FallbackProvider([_Boom(), _Ok()])
    got = list(p.fetch_many([(1, 2), (3, 4)]))
    assert [g[0] for g in got] == [(1, 2), (3, 4)]
    assert p.name == "ok" and "503" in p.errors[0]
    with pytest.raises(RuntimeError):
        list(F.FallbackProvider([_Boom()]).fetch_many([(1, 2)]))


def test_get_provider_default_is_ecmwf_then_open_meteo():
    p = F.get_provider()
    assert isinstance(p, F.FallbackProvider)
    assert [q.name for q in p.providers] == ["ecmwf_open", "open_meteo"]
    assert F.get_provider("open_meteo").name == "open_meteo"
    with pytest.raises(ValueError):
        F.get_provider("nope")


def test_ecmwf_download_falls_through_mirrors(monkeypatch, tmp_path):
    prov = F.EcmwfOpenDataProvider(sources=("ecmwf", "aws"),
                                   workdir=str(tmp_path))
    seen = []

    class _C:
        def __init__(self, src):
            self.src = src

        def latest(self, **kw):
            seen.append(self.src)
            if self.src == "ecmwf":
                raise ConnectionError("blocked")
            return dt.datetime(2026, 10, 11, 12)

        def retrieve(self, target=None, **kw):
            _write_grib(target, [("tp", s, lambda la, lo: 0.0)
                                 for s in kw["step"]])
    monkeypatch.setattr(prov, "_client", _C)
    base, fields = prov._download([(11.34, 77.72)], days=16)
    assert seen == ["ecmwf", "aws"] and ("tp", 360) in fields
    assert list(tmp_path.iterdir()) == []      # temp GRIB deleted
