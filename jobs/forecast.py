"""Daily forecast for every watched village -> forecast_daily/_hourly.

Runs at 05:15 IST so the morning's alerts (Phase 1) read a fresh
issue. Daily rows are kept per issue date so forecasts can later be
scored against observed rain; hourly rows are pruned to the last few
issues to keep the store small on the 1 GB box.

The provider sits behind core.sources.forecast (Open-Meteo by default;
its free API is non-commercial - see that module).
"""

import datetime
import logging

from core import store, watched_villages
from core.sources.forecast import (DAILY_FIELDS, HOURLY_FIELDS,
                                   get_provider)

log = logging.getLogger("jobs.forecast")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
HOURLY_KEEP_ISSUES = 3


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def run(con):
    villages, source = watched_villages.load()
    if villages.empty:
        return {"rows": 0, "status": "ok",
                "detail": "no watched villages (add a 'Villages' Sheet "
                          "tab or data/watch_villages.csv)"}

    now = _utc_now()
    issued_on = datetime.datetime.now(IST).date().isoformat()

    store.upsert(con, "villages", [
        {**v, "source": source, "updated_at": now}
        for v in villages.to_dict("records")], ["village_id"])

    prov = get_provider()
    ids = villages["village_id"].tolist()
    locs = list(zip(villages["lat"], villages["lon"]))

    n_daily = n_hourly = missing = 0
    for vid, (_, fc) in zip(ids, prov.fetch_many(locs)):
        base = {"village_id": vid, "issued_on": issued_on,
                "provider": prov.name}
        daily = [{**base, "date": d["date"],
                  **{f: d.get(f) for f in DAILY_FIELDS},
                  "fetched_at": now} for d in fc["daily"]]
        hourly = [{**base, "time": h["time"],
                   **{f: h.get(f) for f in HOURLY_FIELDS}}
                  for h in fc["hourly"]]
        missing += sum(d["rain_mm"] is None for d in daily)
        n_daily += store.upsert(con, "forecast_daily", daily,
                                ["village_id", "issued_on", "provider",
                                 "date"])
        n_hourly += store.upsert(con, "forecast_hourly", hourly,
                                 ["village_id", "issued_on", "provider",
                                  "time"])
    store.prune_hourly(con, HOURLY_KEEP_ISSUES)
    con.commit()

    detail = (f"{len(ids)} villages from {source} via {prov.name}: "
              f"{n_daily} daily, {n_hourly} hourly rows (issue "
              f"{issued_on})")
    if missing:
        detail += f"; {missing} daily rain values missing (stored NULL)"
    return {"rows": n_daily + n_hourly, "detail": detail, "status": "ok"}
