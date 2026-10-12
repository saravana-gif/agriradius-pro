"""Nightly mandi archive: AGMARKNET daily prices -> mandi_daily.

The data.gov.in "current daily price" resource only holds the latest
snapshot - yesterday's rows are gone once today's arrive. So every day
we do not archive is history lost for good. This pages through the
feed for Karnataka + Tamil Nadu x the priority commodities and upserts
into the store.

Cleaning is deliberately light, so the archive stays close to source:
- rows without a usable modal price or date are dropped (counted);
- min > max is swapped (an entry slip, not a price signal);
- modal outside [min, max] is KEPT with qc='modal_outside_range' so
  alert rules can skip it (store.mandi_history filters qc='ok');
- duplicates within a run collapse on the primary key.

The feed has NO arrival quantities - price only. Do not build supply
alerts on this table.
"""

import datetime
import logging
import time

import requests

from core import mandi, store, usage

log = logging.getLogger("jobs.mandi_archive")

STATES = ["Karnataka", "Tamil Nadu"]

# AGMARKNET commodity names (not app display labels).
COMMODITIES = [
    "Turmeric",
    "Maize",
    "Banana",
    "Banana - Green",
    "Dry Chillies",
    "Green Chilli",
    "Tender Coconut",
    "Coconut",
    "Copra",
]

PAGE = 500          # rows per request
MAX_PAGES = 40      # safety stop per state x commodity
TIMEOUT = 40        # the government server is slow; this is a cron job
PAUSE_S = 1.0       # be polite between requests
RETRIES = 2

_UNIT_BY_NAME = {v: mandi.price_unit(k) for k, v in mandi.COMMODITIES.items()}


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _get_page(key, state, commodity, offset):
    params = {
        "api-key": key,
        "format": "json",
        "limit": PAGE,
        "offset": offset,
        "filters[state]": state,
        "filters[commodity]": commodity,
    }
    last = None
    for attempt in range(RETRIES + 1):
        try:
            usage.bump("data_gov")
            r = requests.get(mandi.API, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(5 * (attempt + 1))
    # Never let the API key leak into logs / job_runs via the URL.
    raise RuntimeError(f"{type(last).__name__}: "
                       f"{str(last).replace(key, '***')[:300]}")


def fetch_all(key, state, commodity):
    """All feed records for one state x commodity (paged)."""
    out = []
    for page in range(MAX_PAGES):
        j = _get_page(key, state, commodity, page * PAGE)
        recs = j.get("records") or []
        out.extend(recs)
        total = j.get("total")
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = None
        if len(recs) < PAGE or (total is not None and len(out) >= total):
            break
        time.sleep(PAUSE_S)
    else:
        log.warning("%s/%s: hit MAX_PAGES, archive may be partial",
                    state, commodity)
    return out


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _iso_date(v):
    try:
        return datetime.datetime.strptime(str(v).strip(),
                                          "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def clean(records, now):
    """Feed records -> store rows. Returns (rows, dropped_count)."""
    rows = {}
    dropped = 0
    for r in records:
        date = _iso_date(r.get("arrival_date"))
        modal = _num(r.get("modal_price"))
        if not date or modal is None:
            dropped += 1
            continue
        lo, hi = _num(r.get("min_price")), _num(r.get("max_price"))
        if lo is not None and hi is not None and lo > hi:
            lo, hi = hi, lo
        ok = ((lo is None or lo <= modal) and (hi is None or modal <= hi))
        commodity = str(r.get("commodity") or "").strip()
        row = {
            "arrival_date": date,
            "state": str(r.get("state") or "").strip(),
            "district": str(r.get("district") or "").strip(),
            "market": str(r.get("market") or "").strip(),
            "commodity": commodity,
            "variety": str(r.get("variety") or "").strip(),
            "grade": str(r.get("grade") or "").strip(),
            "min_price": lo,
            "max_price": hi,
            "modal_price": modal,
            "unit": _UNIT_BY_NAME.get(commodity, "Rs/qtl"),
            "qc": "ok" if ok else "modal_outside_range",
            "first_seen": now,
            "fetched_at": now,
        }
        k = tuple(row[c] for c in ("arrival_date", "state", "district",
                                   "market", "commodity", "variety",
                                   "grade"))
        rows[k] = row          # later duplicate wins
    return list(rows.values()), dropped


KEY = ["arrival_date", "state", "district", "market", "commodity",
       "variety", "grade"]
# first_seen is set on insert only, so it records when a row first
# appeared (late uploads show up as first_seen >> arrival_date).
UPDATE = ["min_price", "max_price", "modal_price", "unit", "qc",
          "fetched_at"]


def run(con):
    key = mandi._api_key()
    if not key:
        raise RuntimeError("DATA_GOV_API_KEY not configured")

    now = _utc_now()
    written = dropped = flagged = 0
    failed, empty = [], []
    for state in STATES:
        for commodity in COMMODITIES:
            try:
                recs = fetch_all(key, state, commodity)
            except Exception as e:
                log.warning("%s/%s failed: %s", state, commodity, e)
                failed.append(f"{state}/{commodity}")
                continue
            rows, d = clean(recs, now)
            dropped += d
            flagged += sum(r["qc"] != "ok" for r in rows)
            if not rows:
                empty.append(f"{state}/{commodity}")
            written += store.upsert(con, "mandi_daily", rows, KEY, UPDATE)
            con.commit()
            log.info("%s/%s: %d feed rows -> %d stored", state, commodity,
                     len(recs), len(rows))
            time.sleep(PAUSE_S)

    total = len(STATES) * len(COMMODITIES)
    if len(failed) == total:
        raise RuntimeError(f"every request failed ({failed[0]} ...)")
    detail = (f"{written} rows upserted, {dropped} dropped (no date/"
              f"price), {flagged} flagged modal_outside_range; "
              f"{len(empty)} empty, {len(failed)} failed")
    if failed:
        detail += ": " + ", ".join(failed)
    return {"rows": written, "detail": detail,
            "status": "partial" if failed else "ok"}
