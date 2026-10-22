"""Job runner CLI.

    python -m jobs.run daily            # every daily job, in order
    python -m jobs.run mandi_archive    # one job
    python -m jobs.run list

Each job is a module in jobs/ with run(con) -> dict(rows=, detail=,
status=). Every run is logged to the job_runs table with the git SHA
it ran from and the API calls it made. Exit status is non-zero if any
job failed, so cron mail / log watchers can see it.

A group runs each job in its own Python process. Wheels bundle their
own native libraries, and they clash in one process: after eccodes
(forecast) loads its libcurl, GDAL's HTTP reader (rain_baseline)
segfaults. Separate processes also hand memory back between jobs on
the 1 GB box, and a crash stops one job, not the rest of the morning.
"""

import argparse
import datetime
import importlib
import json
import logging
import subprocess
import sys
import time

from config import PROJECT_ROOT
from jobs import headless

JOBS = {
    "forecast": "jobs.forecast",
    "rain": "jobs.rain",
    "field_reports": "jobs.field_reports",
    "verify": "jobs.verify",
    "alerts": "jobs.alerts",
    "publish": "jobs.publish",
    "mandi_archive": "jobs.mandi_archive",
    "rain_baseline": "jobs.rain_baseline",
    "crop_accuracy": "jobs.crop_accuracy",
}

GROUPS = {
    # 05:15 IST: fresh forecast and observed rain, yesterday's field
    # reports, score past alerts and forecasts, the morning's alerts,
    # the pages, then sweep up mandi rows uploaded late the previous
    # evening. The baseline is time-boxed and a no-op once complete;
    # the crop-map accuracy check uses Earth Engine once a month and is
    # a no-op on other days.
    "daily": ["forecast", "rain", "field_reports", "verify", "alerts",
              "publish", "mandi_archive", "rain_baseline",
              "crop_accuracy"],
}

log = logging.getLogger("jobs.run")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def git_sha():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def run_job(name, con, sha):
    """Run one job, logging a job_runs row. Returns True on success."""
    headless.CALLS.clear()
    cur = con.execute(
        "INSERT INTO job_runs (job, started_at, status, git_sha) "
        "VALUES (?, ?, 'running', ?)", (name, _utc_now(), sha))
    run_id = cur.lastrowid
    con.commit()

    t0 = time.monotonic()
    status, rows, detail = "error", 0, ""
    try:
        mod = importlib.import_module(JOBS[name])
        res = mod.run(con) or {}
        status = res.get("status", "ok")
        rows = res.get("rows", 0)
        detail = res.get("detail", "")
    except Exception as e:
        con.rollback()
        log.exception("%s failed", name)
        detail = f"{type(e).__name__}: {e}"[:2000]

    con.execute(
        "UPDATE job_runs SET finished_at=?, status=?, rows_written=?, "
        "api_calls=?, detail=? WHERE id=?",
        (_utc_now(), status, rows, json.dumps(headless.CALLS),
         detail, run_id))
    con.commit()
    log.info("%s: %s, %s rows, %.0fs, calls=%s - %s", name, status, rows,
             time.monotonic() - t0, headless.CALLS, detail)
    return status in ("ok", "partial")


def run_group(group):
    """Run a group's jobs one after another, each in a fresh process.
    Returns 0 only if every job succeeded."""
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ok = True
    for name in GROUPS[group]:
        rc = subprocess.run([sys.executable, "-m", "jobs.run", name],
                            cwd=PROJECT_ROOT).returncode
        if rc not in (0, 1):
            how = f"signal {-rc}" if rc < 0 else f"exit code {rc}"
            log.error("%s crashed (%s)", name, how)
            _mark_crashed(name, how)
        ok = ok and rc == 0
    return 0 if ok else 1


def _mark_crashed(name, how):
    """A child that died without finishing leaves its job_runs row
    'running' - close it with the reason now."""
    from core import store
    con = store.connect()
    try:
        con.execute("UPDATE job_runs SET status='killed', finished_at=?, "
                    "detail=? WHERE job=? AND status='running'",
                    (_utc_now(), f"crashed ({how})", name))
        con.commit()
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m jobs.run")
    ap.add_argument("target",
                    help="job name, group (daily) or 'list'")
    args = ap.parse_args(argv)

    if args.target == "list":
        print("jobs:  ", ", ".join(JOBS))
        print("groups:", ", ".join(f"{g}={'+'.join(j)}"
                                    for g, j in GROUPS.items()))
        return 0

    if args.target in GROUPS:
        return run_group(args.target)
    if args.target not in JOBS:
        ap.error(f"unknown job {args.target!r} (try 'list')")
    names = [args.target]

    headless.setup()
    from core import store
    con = store.connect()
    # Cron wraps runs in flock, so a row still 'running' now is from a
    # run that was killed (timeout, OOM, reboot) - say so.
    con.execute("UPDATE job_runs SET status='killed', finished_at=? "
                "WHERE status='running'", (_utc_now(),))
    con.commit()
    sha = git_sha()
    ok = True
    try:
        for name in names:
            ok = run_job(name, con, sha) and ok
    finally:
        con.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
