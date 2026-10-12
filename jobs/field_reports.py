"""Copy field reports (Sheet tab FieldReports, or the local CSV) into
the store, and turn feedback / 7-day check-backs into alert_event rows.

Runs first in the daily group, so the morning's alerts and pages see
yesterday's reports (sowing dates, days since the last visit, verdicts).
Idempotent: report_id is the key, and an alert_event is added once per
report (matched on detail_json.report_id).
"""

import datetime
import json
import logging

from core import field_reports, store

log = logging.getLogger("jobs.field_reports")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _f(v):
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _row(r, source, now):
    return {
        "report_id": r["report_id"], "submitted_at": r.get("submitted_at"),
        "reported_on": (r.get("reported_on") or "")[:10],
        "officer": r.get("officer"), "village_id": r["village_id"],
        "lat": _f(r.get("lat")), "lon": _f(r.get("lon")),
        "gps_accuracy_m": _f(r.get("gps_accuracy_m")),
        "distance_km": _f(r.get("distance_km")),
        "event": r["event"], "crop": (r.get("crop") or "").lower(),
        "qty": _f(r.get("qty")), "unit": r.get("unit"),
        "alert_id": r.get("alert_id") or None,
        "verdict": (r.get("verdict") or "").lower() or None,
        "note": r.get("note"), "photo": r.get("photo"),
        "source": source, "ingested_at": now,
    }


def run(con):
    now = _utc_now()
    rows, source = field_reports.read_all()
    good, bad = [], 0
    for r in rows:
        if not r.get("report_id") or not r.get("village_id") \
                or r.get("event") not in field_reports.EVENTS \
                or len(r.get("reported_on") or "") < 10:
            bad += 1
            continue
        good.append(_row(r, source, now))
    n = store.upsert(con, "field_report", good, ["report_id"],
                     update=[c for c in good[0] if c not in
                             ("report_id", "ingested_at")] if good else None)

    events = unknown = 0
    for r in good:
        if r["event"] not in ("feedback", "checkback") or not r["alert_id"]:
            continue
        if r["verdict"] not in field_reports.VERDICTS:
            bad += 1
            continue
        if not con.execute("SELECT 1 FROM alert WHERE alert_id=?",
                           (r["alert_id"],)).fetchone():
            unknown += 1
            continue
        seen = con.execute(
            "SELECT 1 FROM alert_event WHERE alert_id=? AND "
            "json_extract(detail_json, '$.report_id')=?",
            (r["alert_id"], r["report_id"])).fetchone()
        if seen:
            continue
        con.execute(
            "INSERT INTO alert_event (alert_id, at, event, actor, "
            "detail_json) VALUES (?, ?, ?, ?, ?)",
            (r["alert_id"], r["submitted_at"] or now, r["event"],
             r["officer"], json.dumps({"report_id": r["report_id"],
                                       "verdict": r["verdict"],
                                       "note": r["note"] or ""})))
        events += 1
    con.commit()
    detail = (f"{n} reports from {source} ({len(rows)} rows read); "
              f"{events} new feedback/check-back events")
    status = "ok"
    if bad:
        detail += (f"; {bad} rows skipped (missing id, village, event "
                   "or date, or a bad verdict)")
    if unknown:
        detail += f"; {unknown} refer to an unknown alert id"
    return {"rows": n + events, "detail": detail, "status": status}
