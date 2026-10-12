"""One-time CHIRPS 1981-2025 monthly baseline per watched village
-> rain_monthly_baseline. Feeds the rain normals and SPI in jobs/rain.

540 months x one small HTTP read each. The job is time-boxed
(RAIN_BASELINE_BUDGET_S, default 6 min) and resumable: every month is
committed as it lands, so it finishes over a few runs and is then a
cheap no-op - until a new village is added, which it fills in.

No Earth Engine. A month that fails is not stored and is retried on
the next run; a pixel with no data is stored as NULL.
"""

import datetime
import logging
import os
import time

from core import store, watched_villages
from core.sources.rain import ChirpsMonthly

log = logging.getLogger("jobs.rain_baseline")

FIRST_YEAR, LAST_YEAR = 1981, 2025
GIVE_UP_AFTER = 3     # straight failures with no success = source down


def budget_s():
    try:
        return int(os.environ.get("RAIN_BASELINE_BUDGET_S", "360"))
    except ValueError:
        return 360


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def months():
    return [(y, m) for y in range(FIRST_YEAR, LAST_YEAR + 1)
            for m in range(1, 13)]


def todo(con, ids):
    """[(year, month, [village_ids missing it])], newest first, so a
    partial baseline covers the most recent years first."""
    have = {}
    for vid, y, m in con.execute(
            "SELECT village_id, year, month FROM rain_monthly_baseline "
            "WHERE source='chirps'"):
        have.setdefault((y, m), set()).add(vid)
    out = []
    for y, m in reversed(months()):
        miss = [v for v in ids if v not in have.get((y, m), ())]
        if miss:
            out.append((y, m, miss))
    return out


def run(con, source=None, budget=None):
    now = _utc_now()
    villages, vsource = watched_villages.load_and_sync(con, now)
    if villages.empty:
        return {"rows": 0, "status": "ok", "detail": "no watched villages"}
    loc = {r.village_id: (r.lat, r.lon) for r in villages.itertuples()}
    work = todo(con, list(loc))
    if not work:
        return {"rows": 0, "status": "ok",
                "detail": f"baseline complete for {len(loc)} villages"}

    source = source or ChirpsMonthly()
    budget = budget_s() if budget is None else budget
    t0 = time.monotonic()
    done = rows = 0
    failed = []
    for y, m, ids in work:
        if time.monotonic() - t0 > budget:
            break
        try:
            vals = source.read_month(y, m, [loc[v] for v in ids])
        except Exception as e:
            log.warning("%s", e)
            failed.append(f"{y}-{m:02d}")
            if not done and len(failed) >= GIVE_UP_AFTER:
                raise RuntimeError(f"CHIRPS unreachable - first "
                                   f"{len(failed)} months failed ({e})")
            continue
        rows += store.upsert(con, "rain_monthly_baseline", [
            {"village_id": v, "year": y, "month": m, "source": "chirps",
             "rain_mm": mm, "fetched_at": now}
            for v, mm in zip(ids, vals)],
            ["village_id", "year", "month", "source"])
        con.commit()
        done += 1

    left = len(todo(con, list(loc)))
    detail = (f"{done} months read for {len(loc)} villages ({vsource}) "
              f"in {time.monotonic() - t0:.0f}s; {left} months still to "
              f"do")
    if failed:
        detail += f"; failed: {', '.join(failed[:10])}"
    return {"rows": rows, "detail": detail,
            "status": "ok" if not left else "partial"}
