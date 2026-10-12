"""Per-village features for the rules engine, built from the store.

    feats, vintage = build(con, village_id, as_of)

Everything a rule can test is a flat {name: value} dict:
- calendar: month, std_week (IMD standard meteorological week), date
- observed rain (jobs/rain): season_dep_pct, dry_days, spi3, ...
- forecast (jobs/forecast, latest issue no older than a day):
  fc_rain_3d_mm, fc_rain_7d_mm, fc_max_rain_3d_mm, fc_rainy_days_7d,
  fc_dry_run_days, fc_tmax_mean_7d, fc_rh_mean_7d, fc_blotch_days_7d
- labels for message text: village, season_label, ...

A value that cannot be computed honestly is None, and a rule condition
on None is never true - missing data cannot fire an alert.
"""

import datetime
import json

from core import rain_stats

FORECAST_MAX_AGE_DAYS = 1      # older issue -> no forecast features
RAIN_MAX_AGE_DAYS = 2          # older rain snapshot -> no rain features
RAINY_MM = rain_stats.DRY_DAY_MM

# Turmeric leaf blotch (Taphrina maculans): favoured by 21-23 C with
# RH >= 80% (TNAU Agritech). A "favourable day" has at least this many
# such hours in the forecast.
BLOTCH_T = (21.0, 23.0)
BLOTCH_RH = 80.0
BLOTCH_MIN_HOURS = 6


def std_week(d):
    """IMD standard meteorological week (1-52): 7-day weeks from 1 Jan;
    week 9 takes 29 Feb in leap years and week 52 has 8 days."""
    doy = d.timetuple().tm_yday
    leap = (d.year % 4 == 0 and d.year % 100 != 0) or d.year % 400 == 0
    if leap and doy >= 60:
        doy -= 1                              # 29 Feb joins week 9
    return min(52, (doy - 1) // 7 + 1)


def _fmt_day(iso):
    if not iso:
        return None
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d:%b}"


def calendar_features(as_of):
    return {"date": as_of.isoformat(), "month": as_of.month,
            "std_week": std_week(as_of), "mmdd": as_of.strftime("%m-%d")}


def _latest_rain(con, village_id, as_of):
    row = con.execute(
        "SELECT as_of, features_json, vintage_json FROM village_features "
        "WHERE village_id=? AND kind='rain' AND as_of<=? ORDER BY as_of "
        "DESC LIMIT 1", (village_id, as_of.isoformat())).fetchone()
    if not row:
        return {}, {}
    if (as_of - datetime.date.fromisoformat(row[0])).days \
            > RAIN_MAX_AGE_DAYS:
        return {}, {"rain_stale_since": row[0]}
    f = json.loads(row[1])
    f.pop("as_of", None)
    v = json.loads(row[2])
    season = f.get("season")
    f["season_label"] = rain_stats.SEASONS[season][0] if season else None
    f["season_start_label"] = _fmt_day(f.get(f"{season}_start")) \
        if season else None
    f["season_category_label"] = rain_stats.CATEGORY_LABEL.get(
        f.get("season_category"))
    return f, v


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _sum_all(vals):
    """Sum only if every value is present - a gap is not 0 mm."""
    if not vals or any(v is None for v in vals):
        return None
    return round(sum(vals), 1)


def forecast_features(daily, hourly, as_of):
    """daily: [{date, rain_mm, tmax, tmin, rh_max, rh_min}] from the
    latest issue; hourly: [{time, temp, rh}] (any spacing)."""
    days = [d for d in daily if d["date"] >= as_of.isoformat()]
    d3, d7 = days[:3], days[:7]
    f = {}
    if len(d3) == 3:
        r3 = [d["rain_mm"] for d in d3]
        f["fc_rain_3d_mm"] = _sum_all(r3)
        f["fc_max_rain_3d_mm"] = (None if any(r is None for r in r3)
                                  else max(r3))
        f["fc_rainy_days_3d"] = (None if any(r is None for r in r3)
                                 else sum(r >= RAINY_MM for r in r3))
    if len(d7) == 7:
        r7 = [d["rain_mm"] for d in d7]
        f["fc_rain_7d_mm"] = _sum_all(r7)
        f["fc_rainy_days_7d"] = (None if any(r is None for r in r7)
                                 else sum(r >= RAINY_MM for r in r7))
        f["fc_tmax_mean_7d"] = _mean([d["tmax"] for d in d7])
        f["fc_tmax_max_7d"] = max((d["tmax"] for d in d7
                                   if d["tmax"] is not None), default=None)
        f["fc_tmin_min_7d"] = min((d["tmin"] for d in d7
                                   if d["tmin"] is not None), default=None)
        f["fc_rh_mean_7d"] = _mean([
            (d["rh_max"] + d["rh_min"]) / 2 for d in d7
            if d["rh_max"] is not None and d["rh_min"] is not None])
    run = 0
    for d in days:          # dry days in a row from today
        if d["rain_mm"] is None or d["rain_mm"] >= RAINY_MM:
            break
        run += 1
    f["fc_dry_run_days"] = run if days else None
    f.update(_blotch(hourly, as_of))
    return f


def _blotch(hourly, as_of):
    """Days in the next 7 with >= BLOTCH_MIN_HOURS hours at 21-23 C and
    RH >= 80%. Each row stands for the hours up to the next row (3 h
    for ECMWF, 1 h for Open-Meteo)."""
    rows = sorted((h for h in hourly if h.get("time")),
                  key=lambda h: h["time"])
    if len(rows) < 2:
        return {"fc_blotch_days_7d": None}
    t = [datetime.datetime.fromisoformat(h["time"]) for h in rows]
    hours = {}
    covered = {}
    for i, h in enumerate(rows):
        span = ((t[i + 1] - t[i]).total_seconds() / 3600
                if i + 1 < len(rows) else (t[i] - t[i - 1]).total_seconds()
                / 3600)
        day = t[i].date()
        covered[day] = covered.get(day, 0) + span
        temp, rh = h.get("temp"), h.get("rh")
        if (temp is not None and rh is not None
                and BLOTCH_T[0] <= temp <= BLOTCH_T[1] and rh >= BLOTCH_RH):
            hours[day] = hours.get(day, 0) + span
    window = [as_of + datetime.timedelta(days=k) for k in range(7)]
    full = [d for d in window if covered.get(d, 0) >= 20]
    if len(full) < 5:            # too little hourly data to say
        return {"fc_blotch_days_7d": None}
    return {"fc_blotch_days_7d": sum(hours.get(d, 0) >= BLOTCH_MIN_HOURS
                                     for d in full)}


def _latest_forecast(con, village_id, as_of):
    row = con.execute(
        "SELECT issued_on, provider FROM forecast_daily WHERE "
        "village_id=? AND issued_on<=? ORDER BY issued_on DESC LIMIT 1",
        (village_id, as_of.isoformat())).fetchone()
    if not row or (as_of - datetime.date.fromisoformat(row[0])).days \
            > FORECAST_MAX_AGE_DAYS:
        return None
    issued, prov = row
    cols = ["date", "rain_mm", "tmax", "tmin", "rh_max", "rh_min"]
    daily = [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM forecast_daily WHERE "
        "village_id=? AND issued_on=? AND provider=? ORDER BY date",
        (village_id, issued, prov))]
    hourly = [dict(zip(("time", "temp", "rh"), r)) for r in con.execute(
        "SELECT time, temp, rh FROM forecast_hourly WHERE village_id=? "
        "AND issued_on=? AND provider=? ORDER BY time",
        (village_id, issued, prov))]
    return issued, prov, daily, hourly


def build(con, village_id, as_of):
    """(features, vintage) for one village on `as_of` (IST date)."""
    v = con.execute("SELECT village, district, state, crops FROM villages "
                    "WHERE village_id=?", (village_id,)).fetchone()
    feats = {"village_id": village_id}
    if v:
        feats.update(village=v[0], district=v[1], state=v[2])
    feats.update(calendar_features(as_of))
    rain, rain_v = _latest_rain(con, village_id, as_of)
    feats.update(rain)
    vintage = dict(rain_v)
    fc = _latest_forecast(con, village_id, as_of)
    if fc:
        issued, prov, daily, hourly = fc
        feats.update(forecast_features(daily, hourly, as_of))
        vintage.update(forecast_issued_on=issued, forecast_provider=prov)
    return feats, vintage


def village_crops(con, village_id):
    """Normalised crop names for a village ('tender coconut' stays)."""
    row = con.execute("SELECT crops FROM villages WHERE village_id=?",
                      (village_id,)).fetchone()
    raw = (row[0] if row else "") or ""
    return sorted({c.strip().lower() for c in raw.replace(",", ";")
                   .split(";") if c.strip()})
