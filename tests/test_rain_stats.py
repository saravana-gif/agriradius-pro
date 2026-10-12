import datetime as dt
import random

import pytest

from core import rain_stats as rs

D = dt.date


@pytest.mark.parametrize("dep,cat", [
    (-100, "no_rain"), (-60, "large_deficient"), (-59.6, "large_deficient"),
    (-59.4, "deficient"), (-20, "deficient"), (-19, "normal"),
    (19, "normal"), (20, "excess"), (59, "excess"), (60, "large_excess"),
    (None, None)])
def test_imd_category(dep, cat):
    assert rs.imd_category(dep) == cat


def test_season_windows():
    w = rs.season_windows(D(2026, 10, 12))
    assert w["sw"] == {"start": D(2026, 6, 1), "end": D(2026, 9, 30),
                       "active": False}
    assert w["ne"] == {"start": D(2026, 10, 1), "end": D(2026, 10, 11),
                       "active": True}
    w = rs.season_windows(D(2027, 2, 1))
    assert set(w) == {"ne"} and w["ne"]["start"] == D(2026, 10, 1)
    assert w["ne"]["end"] == D(2026, 12, 31) and not w["ne"]["active"]
    assert rs.season_windows(D(2027, 5, 1)) == {}
    w = rs.season_windows(D(2027, 6, 1))   # nothing observed yet
    assert w == {}
    assert rs.season_windows(D(2027, 6, 2))["sw"]["active"]


def test_cumulative_skips_missing_days_in_total_and_normal():
    normals = {10: 310.0}                       # 10 mm/day in October
    daily = {D(2026, 10, d): 5.0 for d in range(1, 11)}
    daily[D(2026, 10, 3)] = None                # missing, NOT zero
    c = rs.cumulative(daily, normals, D(2026, 10, 1), D(2026, 10, 10))
    assert c["cum_mm"] == 45.0 and c["normal_mm"] == 90.0
    assert c["dep_pct"] == -50.0 and c["category"] == "deficient"
    assert c["missing_days"] == 1
    for d in range(2, 6):                       # 4/10 missing: no verdict
        daily[D(2026, 10, d)] = None
    c = rs.cumulative(daily, normals, D(2026, 10, 1), D(2026, 10, 10))
    assert c["dep_pct"] is None and c["category"] is None


def test_dry_spell_stops_at_gap():
    end = D(2026, 10, 11)
    daily = {end - dt.timedelta(days=k): 0.0 for k in range(5)}
    daily[end - dt.timedelta(days=5)] = 12.0
    assert rs.dry_spell(daily, end) == (5, False)
    daily[end - dt.timedelta(days=5)] = None
    assert rs.dry_spell(daily, end) == (5, True)
    daily[end] = 2.5                             # 2.5 mm is a rainy day
    assert rs.dry_spell(daily, end) == (0, False)


def test_spi_matches_scipy_fit():
    scipy = pytest.importorskip("scipy.stats")
    rnd = random.Random(1)
    hist = [rnd.gammavariate(2.0, 60.0) for _ in range(45)]
    for v in (20.0, 100.0, 300.0):
        a, _, scale = scipy.gamma.fit(hist, floc=0)
        ref = scipy.norm.ppf(scipy.gamma.cdf(v, a, scale=scale))
        assert rs.spi(hist, v) == pytest.approx(ref, abs=0.06)
    assert rs.spi(hist[:20], 50.0) is None       # too few years
    assert rs.spi(hist, None) is None


def test_spi_zero_heavy_month():
    hist = [0.0] * 30 + [5.0, 10.0, 20.0, 1.0, 2.0, 3.0, 8.0, 12.0, 4.0,
                         6.0, 7.0, 9.0, 11.0, 15.0, 30.0]
    assert rs.spi(hist, 0.0) == pytest.approx(
        __import__("statistics").NormalDist().inv_cdf(30 / 45), abs=0.01)


def _season(as_of, mm_per_day, start):
    d, out = start, {}
    while d < as_of:
        out[d] = mm_per_day
        d += dt.timedelta(days=1)
    return out


def test_rain_features_end_to_end():
    base = {(y, m): (100.0 + (y % 7) * 10 if m != 10 else 150.0 + (y % 9) * 15)
            for y in range(1981, 2026) for m in range(1, 13)}
    as_of = D(2026, 10, 12)
    daily = _season(as_of, 1.0, D(2026, 6, 1))
    daily[D(2026, 9, 28)] = 20.0
    f = rs.rain_features(daily, base, as_of)
    assert f["obs_through"] == "2026-10-11" and f["obs_lag_days"] == 1
    assert f["season"] == "ne" and f["ne_active"] and not f["sw_active"]
    assert f["ne_cum_mm"] == 11.0
    assert f["season_dep_pct"] == f["ne_dep_pct"] < -60
    assert f["season_category"] == "large_deficient"
    assert f["dry_days"] == 13 and f["dry_days_gap"] is False
    assert f["rain_7d_mm"] == 7.0 and f["rain_8_28d_mm"] == 40.0
    assert f["spi1_to"] == "2026-09" and f["spi1"] < -2
    assert f["spi3"] is not None and f["spi3_label"]
    assert f["baseline_years"] == 45


def test_rain_features_without_baseline_or_obs():
    f = rs.rain_features({}, {}, D(2026, 10, 12))
    assert f["obs_through"] is None and f["dry_days"] is None
    assert f["season_dep_pct"] is None and f["spi1"] is None
