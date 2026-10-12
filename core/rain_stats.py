"""Rain-tracker arithmetic: seasons, normals, departures, dry spells,
SPI. Pure functions on plain dicts - no I/O - so they are easy to test.

Conventions
- daily: {datetime.date: mm or None}. A missing day stays None; it is
  never counted as 0 mm, and never as a dry day.
- monthly normals: {month: mm} averaged over the baseline years.
- IMD categories (departure from normal, %): large excess >= +60,
  excess +20..+59, normal -19..+19, deficient -20..-59, large
  deficient -60..-99, no rain -100.
"""

import calendar
import datetime
import math
from statistics import NormalDist

DRY_DAY_MM = 2.5          # IMD rainy-day threshold
MIN_NORMAL_YEARS = 30     # fewer baseline years -> no normal, no SPI
MAX_MISSING_SHARE = 0.2   # more missing days in a window -> no departure

SEASONS = {
    # key: (label, start (month, day), end (month, day))
    "sw": ("SW monsoon", (6, 1), (9, 30)),
    "ne": ("NE monsoon", (10, 1), (12, 31)),
}


def imd_category(dep_pct):
    if dep_pct is None:
        return None
    d = round(dep_pct)
    if d <= -100:
        return "no_rain"
    if d <= -60:
        return "large_deficient"
    if d <= -20:
        return "deficient"
    if d < 20:
        return "normal"
    if d < 60:
        return "excess"
    return "large_excess"


CATEGORY_LABEL = {
    "no_rain": "No rain", "large_deficient": "Large deficient",
    "deficient": "Deficient", "normal": "Normal", "excess": "Excess",
    "large_excess": "Large excess",
}


def season_windows(as_of):
    """Seasons worth reporting on `as_of` (an IST date; observations
    run to the day before). SW is reported Jun-Dec (final after Sep),
    NE Oct-Mar (final after Dec). Returns {key: dict(start, end,
    active)} where end = min(season end, as_of - 1)."""
    last_obs = as_of - datetime.timedelta(days=1)
    out = {}
    for key, (_, (sm, sd), (em, ed)) in SEASONS.items():
        if key == "sw":
            if as_of.month < 6:
                continue
            year = as_of.year
        else:
            if 4 <= as_of.month <= 9:
                continue
            year = as_of.year if as_of.month >= 10 else as_of.year - 1
        start = datetime.date(year, sm, sd)
        end = min(datetime.date(year, em, ed), last_obs)
        if end < start:
            continue
        out[key] = {"start": start, "end": end,
                    "active": end == last_obs
                    and last_obs <= datetime.date(year, em, ed)}
    return out


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += datetime.timedelta(days=1)


def period_normal(normals, days):
    """Normal rain (mm) over a set of days, each day taking its month's
    normal / days in that month. None if a month has no normal."""
    tot = 0.0
    for d in days:
        n = normals.get(d.month)
        if n is None:
            return None
        tot += n / calendar.monthrange(d.year, d.month)[1]
    return tot


def cumulative(daily, normals, start, end):
    """Cumulative rain against normal over [start, end].

    Missing days are left out of BOTH the total and the normal, and
    counted; with more than MAX_MISSING_SHARE missing there is no
    departure."""
    days = list(_days(start, end))
    have = [d for d in days if daily.get(d) is not None]
    missing = len(days) - len(have)
    cum = round(sum(daily[d] for d in have), 1) if have else None
    normal = period_normal(normals, have) if have else None
    dep = None
    if (cum is not None and normal and normal > 0
            and missing <= MAX_MISSING_SHARE * len(days)):
        dep = round(100.0 * (cum - normal) / normal, 1)
    return {"cum_mm": cum,
            "normal_mm": None if normal is None else round(normal, 1),
            "dep_pct": dep, "category": imd_category(dep),
            "days": len(days), "missing_days": missing}


def dry_spell(daily, end):
    """(n, gap): consecutive days < 2.5 mm ending at `end`, walking
    back. A missing day stops the count: then gap=True and n is only a
    lower bound."""
    n, d = 0, end
    while True:
        v = daily.get(d)
        if v is None:
            return n, True
        if v >= DRY_DAY_MM:
            return n, False
        n += 1
        d -= datetime.timedelta(days=1)


def window_sum(daily, end, first_back, last_back):
    """Sum over days end-last_back .. end-first_back (inclusive);
    None if any day in it is missing."""
    tot = 0.0
    for k in range(first_back, last_back + 1):
        v = daily.get(end - datetime.timedelta(days=k))
        if v is None:
            return None
        tot += v
    return round(tot, 1)


def month_total(daily, year, month):
    """Total for a calendar month, or None unless every day is there."""
    n = calendar.monthrange(year, month)[1]
    vals = [daily.get(datetime.date(year, month, d)) for d in range(1, n + 1)]
    if any(v is None for v in vals):
        return None
    return round(sum(vals), 1)


def shift_month(year, month, k):
    i = year * 12 + (month - 1) + k
    return i // 12, i % 12 + 1


# ------------------------------------------------------------------ SPI

def _gammainc_lower(a, x):
    """Regularised lower incomplete gamma P(a, x) (Numerical Recipes:
    series for x < a+1, continued fraction otherwise)."""
    if x <= 0:
        return 0.0
    lg = math.lgamma(a)
    if x < a + 1:
        ap, s, delta = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1
            delta *= x / ap
            s += delta
            if abs(delta) < abs(s) * 1e-12:
                break
        return s * math.exp(-x + a * math.log(x) - lg)
    b = x + 1 - a
    c, d = 1e300, 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-12:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - lg) * h


def spi(history, value):
    """Standardised Precipitation Index of `value` against `history`
    (totals for the same calendar window in the baseline years).

    Gamma distribution fitted by Thom's maximum-likelihood estimate,
    with zeros handled as a mixed distribution (McKee et al. 1993).
    None if fewer than MIN_NORMAL_YEARS values or `value` is None.
    Result clipped to +-3."""
    hist = [h for h in history if h is not None]
    if value is None or len(hist) < MIN_NORMAL_YEARS:
        return None
    pos = [h for h in hist if h > 0]
    q = (len(hist) - len(pos)) / len(hist)
    if len(pos) < 10:
        return None
    mean = sum(pos) / len(pos)
    a_ = math.log(mean) - sum(math.log(h) for h in pos) / len(pos)
    if a_ <= 0:
        return None
    alpha = (1 + math.sqrt(1 + 4 * a_ / 3)) / (4 * a_)
    beta = mean / alpha
    g = _gammainc_lower(alpha, value / beta) if value > 0 else 0.0
    p = q + (1 - q) * g
    p = min(max(p, 1e-6), 1 - 1e-6)
    return round(max(-3.0, min(3.0, NormalDist().inv_cdf(p))), 2)


SPI_LABEL = [(-2.0, "extremely dry"), (-1.5, "severely dry"),
             (-1.0, "moderately dry"), (1.0, "near normal"),
             (1.5, "moderately wet"), (2.0, "very wet")]


def spi_label(v):
    if v is None:
        return None
    for cut, lab in SPI_LABEL:
        if v <= cut:
            return lab
    return "extremely wet"


# ------------------------------------------------------------- features

def normals_from_baseline(baseline):
    """{(year, month): mm or None} -> ({month: normal}, n_years).
    A month with fewer than MIN_NORMAL_YEARS values has no normal."""
    by_m = {}
    for (y, m), v in baseline.items():
        if v is not None:
            by_m.setdefault(m, []).append(v)
    normals = {m: round(sum(v) / len(v), 1) for m, v in by_m.items()
               if len(v) >= MIN_NORMAL_YEARS}
    years = len({y for (y, _), v in baseline.items() if v is not None})
    return normals, years


def _window_history(baseline, end_year, end_month, k):
    """Baseline totals for the k-month window ending at end_month, one
    per baseline year that has all k months."""
    out = []
    years = sorted({y for (y, _) in baseline})
    for y in years:
        vals = [baseline.get(shift_month(y, end_month, -i))
                for i in range(k)]
        if all(v is not None for v in vals):
            out.append(sum(vals))
    return out


def rain_features(daily, baseline, as_of):
    """Everything the cards and rules need about observed rain.

    daily: {date: mm|None} observed (merged sources).
    baseline: {(year, month): mm|None} monthly baseline.
    as_of: IST run date; observations are used up to as_of - 1.
    """
    normals, n_years = normals_from_baseline(baseline)
    obs_dates = [d for d, v in daily.items() if v is not None]
    last_obs = max(obs_dates) if obs_dates else None
    f = {"as_of": as_of.isoformat(),
         "obs_through": last_obs.isoformat() if last_obs else None,
         "obs_lag_days": (as_of - last_obs).days if last_obs else None,
         "baseline_years": n_years}

    active = None
    for key, w in season_windows(as_of).items():
        c = cumulative(daily, normals, w["start"], w["end"])
        f.update({f"{key}_{k}": v for k, v in c.items()})
        f[f"{key}_start"] = w["start"].isoformat()
        f[f"{key}_end"] = w["end"].isoformat()
        f[f"{key}_active"] = w["active"]
        if w["active"]:
            active = key
    f["season"] = active
    for k in ("cum_mm", "normal_mm", "dep_pct", "category",
              "missing_days"):
        f[f"season_{k}"] = f.get(f"{active}_{k}") if active else None

    if last_obs:
        n, gap = dry_spell(daily, last_obs)
        f["dry_days"], f["dry_days_gap"] = n, gap
        f["rain_7d_mm"] = window_sum(daily, last_obs, 0, 6)
        f["rain_14d_mm"] = window_sum(daily, last_obs, 0, 13)
        # rain 8-28 days back: "after rain" in pest rules
        f["rain_8_28d_mm"] = window_sum(daily, last_obs, 7, 27)
    else:
        f.update(dry_days=None, dry_days_gap=None, rain_7d_mm=None,
                 rain_14d_mm=None, rain_8_28d_mm=None)

    # SPI on the last complete calendar month(s). Observed months come
    # from the daily record; history from the baseline.
    ly, lm = shift_month(as_of.year, as_of.month, -1)
    if last_obs and last_obs < datetime.date(
            *shift_month(ly, lm, 1), 1) - datetime.timedelta(days=1):
        ly, lm = shift_month(ly, lm, -1)      # last month not complete
    for k in (1, 3):
        months = [shift_month(ly, lm, -i) for i in range(k)]
        tots = [month_total(daily, y, m) for y, m in months]
        val = None if any(t is None for t in tots) else sum(tots)
        s = spi(_window_history(baseline, ly, lm, k), val)
        f[f"spi{k}"] = s
        f[f"spi{k}_label"] = spi_label(s)
        f[f"spi{k}_to"] = f"{ly}-{lm:02d}"
    return f
