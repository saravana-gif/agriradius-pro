"""Job runner CLI.

    python -m jobs.run daily            # every daily job, in order
    python -m jobs.run mandi_archive    # one job
    python -m jobs.run list

Each job is a module in jobs/ with run(con) -> dict(rows=, detail=,
status=). Every run is logged to the job_runs table with the git SHA
it ran from and the API calls it made. Exit status is non-zero if any
job failed, so cron mail / log watchers can see it.
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
    "mandi_archive": "jobs.mandi_archive",
    "rain_baseline": "jobs.rain_baseline",
}

GROUPS = {
    # 05:15 IST: fresh forecast and observed rain for the morning, then
    # sweep up mandi rows uploaded late the previous evening. The
    # baseline goes last: it is time-boxed and a no-op once complete.
    "daily": ["forecast", "rain", "mandi_archive", "rain_baseline"],
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

    names = GROUPS.get(args.target) or (
        [args.target] if args.target in JOBS else None)
    if not names:
        ap.error(f"unknown job {args.target!r} (try 'list')")

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
