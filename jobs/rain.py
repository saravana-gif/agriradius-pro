"""Daily rain tracker: observed rain per watched village -> rain_daily,
then season / dry-spell / SPI features -> village_features (kind
'rain'). No Earth Engine.

1. IMD real-time 0.25 deg gridded rain (imdlib's URLs) for every day
   since the start of the oldest season we report (1 Jun for SW, 1 Oct
   for NE) that is not stored yet, plus the last REFETCH_DAYS again
   (IMD revises recent days).
2. Days IMD has not published after FALLBACK_AFTER_DAYS, or every day
   if IMD cannot be reached, are filled from Open-Meteo past_days under
   source 'open_meteo'. IMD always wins where both exist.
3. Features against the CHIRPS 1981-2025 monthly baseline
   (jobs/rain_baseline.py). Until that has run, departures and SPI are
   None - never a guess.
"""

import datetime
import json
import logging

from core import rain_stats, store, watched_villages
from core.sources.rain import ImdRealtimeRain, OpenMeteoPastRain

log = logging.getLogger("jobs.rain")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
REFETCH_DAYS = 3          # IMD revises the newest days
FALLBACK_AFTER_DAYS = 2   # give IMD this long before using the fallback
MAX_IMD_DAYS = 240        # per run; the first run back-fills a season
SOURCE_RANK = {"imd": 0, "open_meteo": 1}


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def first_needed(as_of):
    """Oldest date the features need: the start of every reported
    season, and three full months back for SPI-3."""
    starts = [w["start"] for w in rain_stats.season_windows(as_of).values()]
    y, m = rain_stats.shift_month(as_of.year, as_of.month, -4)
    starts.append(datetime.date(y, m, 1))
    return min(starts)


def _dates(start, end):
    d = start
    while d <= end:
        yield d
        d += datetime.timedelta(days=1)


def _stored(con, source, since, with_value=False):
    """{village_id: set(iso dates)} with a row from `source` (only rows
    holding a value if `with_value`)."""
    out = {}
    sql = ("SELECT village_id, date FROM rain_daily WHERE source=? AND "
           "date>=?" + (" AND rain_mm IS NOT NULL" if with_value else ""))
    for vid, d in con.execute(sql, (source, since.isoformat())):
        out.setdefault(vid, set()).add(d)
    return out


def merged_daily(con, village_id, since):
    """{date: mm|None}: one value per day, best source first."""
    rows = con.execute(
        "SELECT date, source, rain_mm FROM rain_daily WHERE village_id=? "
        "AND date>=?", (village_id, since.isoformat())).fetchall()
    best = {}
    for d, src, mm in rows:
        if mm is None:
            continue
        r = SOURCE_RANK.get(src, 9)
        if d not in best or r < best[d][0]:
            best[d] = (r, mm, src)
    daily = {datetime.date.fromisoformat(d): v[1] for d, v in best.items()}
    sources = sorted({v[2] for v in best.values()})
    return daily, sources


def baseline_for(con, village_id):
    return {(y, m): mm for y, m, mm in con.execute(
        "SELECT year, month, rain_mm FROM rain_monthly_baseline WHERE "
        "village_id=? AND source='chirps'", (village_id,))}


def fetch_imd(con, villages, start, end, now):
    """Fetch missing / recent IMD days. Returns (rows, published_days,
    unpublished_days, error or None)."""
    imd = ImdRealtimeRain()
    ids = villages["village_id"].tolist()
    locs = list(zip(villages["lat"], villages["lon"]))
    have = _stored(con, "imd", start)
    recent = end - datetime.timedelta(days=REFETCH_DAYS - 1)
    todo = [d for d in _dates(start, end)
            if d >= recent or any(d.isoformat() not in have.get(v, ())
                                  for v in ids)]
    todo = todo[-MAX_IMD_DAYS:]
    rows = published = unpublished = 0
    for i, day in enumerate(todo):
        try:
            grid = imd.fetch_day(day)
        except Exception as e:
            if not published:
                return rows, published, unpublished, str(e)
            log.warning("IMD %s failed: %s", day, e)
            continue
        if grid is None:
            unpublished += 1
            continue
        published += 1
        vals = imd.values_at(grid, locs)
        rows += store.upsert(con, "rain_daily", [
            {"village_id": v, "date": day.isoformat(), "source": "imd",
             "rain_mm": mm, "fetched_at": now}
            for v, mm in zip(ids, vals)],
            ["village_id", "date", "source"])
        if i % 20 == 19:
            con.commit()
    con.commit()
    return rows, published, unpublished, None


def fill_fallback(con, villages, start, end, imd_down, now):
    """Open-Meteo for days IMD has not covered. Returns rows written."""
    cutoff = end if imd_down else (
        end - datetime.timedelta(days=FALLBACK_AFTER_DAYS - 1))
    oldest = max(start, end - datetime.timedelta(days=91))
    have = _stored(con, "imd", oldest, with_value=True)
    ids = villages["village_id"].tolist()
    need = {v: [d.isoformat() for d in _dates(oldest, cutoff)
                if d.isoformat() not in have.get(v, ())] for v in ids}
    if not any(need.values()):
        return 0
    locs = list(zip(villages["lat"], villages["lon"]))
    got = OpenMeteoPastRain().fetch(locs, days=(end - oldest).days + 2)
    rows = []
    for v, loc in zip(ids, locs):
        series = got.get(loc, {})
        rows += [{"village_id": v, "date": d, "source": "open_meteo",
                  "rain_mm": series.get(d), "fetched_at": now}
                 for d in need[v] if d in series]
    n = store.upsert(con, "rain_daily", rows,
                     ["village_id", "date", "source"])
    con.commit()
    return n


def compute_features(con, villages, as_of, since, now):
    n = 0
    for v in villages["village_id"]:
        daily, sources = merged_daily(con, v, since)
        base = baseline_for(con, v)
        f = rain_stats.rain_features(daily, base, as_of)
        vintage = {"rain_sources": sources,
                   "rain_obs_through": f["obs_through"],
                   "baseline": (f"chirps v2.0 monthly, {f['baseline_years']}"
                                " years (1981-2025)")
                   if f["baseline_years"] else None}
        store.upsert(con, "village_features", [{
            "village_id": v, "as_of": as_of.isoformat(), "kind": "rain",
            "features_json": json.dumps(f), "vintage_json":
            json.dumps(vintage), "computed_at": now}],
            ["village_id", "as_of", "kind"])
        n += 1
    con.commit()
    return n


def run(con):
    now = _utc_now()
    villages, source = watched_villages.load_and_sync(con, now)
    if villages.empty:
        return {"rows": 0, "status": "ok", "detail": "no watched villages"}
    as_of = datetime.datetime.now(IST).date()
    end = as_of - datetime.timedelta(days=1)
    start = first_needed(as_of)

    imd_rows, pub, unpub, imd_err = fetch_imd(con, villages, start, end, now)
    fb_rows, fb_err = 0, None
    try:
        fb_rows = fill_fallback(con, villages, start, end,
                                imd_err is not None, now)
    except Exception as e:
        fb_err = f"{type(e).__name__}: {str(e)[:200]}"
        log.warning("fallback failed: %s", fb_err)
    nf = compute_features(con, villages, as_of, start, now)

    detail = (f"{len(villages)} villages ({source}), {start}..{end}: "
              f"IMD {pub} days stored, {unpub} not yet published; "
              f"fallback {fb_rows} rows; {nf} feature rows")
    status = "ok"
    if imd_err:
        detail += f"; IMD unreachable: {imd_err[:200]}"
        status = "partial"
    if fb_err:
        detail += f"; fallback failed: {fb_err}"
        status = "partial"
    if imd_err and fb_err:
        status = "error"
    no_base = con.execute(
        "SELECT COUNT(*) FROM rain_monthly_baseline").fetchone()[0] == 0
    if no_base:
        detail += "; no CHIRPS baseline yet (run rain_baseline)"
    return {"rows": imd_rows + fb_rows, "detail": detail, "status": status}
