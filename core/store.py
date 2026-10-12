"""Local SQLite store for precomputed intel (jobs write, app reads).

WHY
---
The app used to compute everything on click. Early warnings need the
opposite: cron jobs fetch and archive on a schedule, and the app only
reads what is already there. Every day of mandi prices archived is
history that the government feed itself does not keep in a form we
can query.

One file, data/store/intel.sqlite, in WAL mode so the Streamlit app can
read while a job writes. data/store/ is gitignored, so the deploy
`git reset --hard` never touches it.

This module has no Streamlit import: jobs use connect(); the app uses
the read-only helpers at the bottom (wrap them in st.cache_data at the
call site).
"""

import sqlite3
from contextlib import closing

import pandas as pd

from config import PROJECT_ROOT

STORE_DIR = PROJECT_ROOT / "data" / "store"
DB_PATH = STORE_DIR / "intel.sqlite"

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS job_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job           TEXT NOT NULL,
    started_at    TEXT NOT NULL,          -- UTC ISO
    finished_at   TEXT,
    status        TEXT NOT NULL,          -- running | ok | partial | error
    git_sha       TEXT,
    rows_written  INTEGER,
    api_calls     TEXT,                   -- JSON {service: n}
    detail        TEXT
);
CREATE INDEX IF NOT EXISTS job_runs_job ON job_runs (job, started_at);

-- AGMARKNET daily prices. NOTE: the data.gov.in feed has NO arrival
-- quantities, so this is price only.
CREATE TABLE IF NOT EXISTS mandi_daily (
    arrival_date  TEXT NOT NULL,          -- ISO yyyy-mm-dd
    state         TEXT NOT NULL,
    district      TEXT NOT NULL,
    market        TEXT NOT NULL,
    commodity     TEXT NOT NULL,          -- AGMARKNET name
    variety       TEXT NOT NULL DEFAULT '',
    grade         TEXT NOT NULL DEFAULT '',
    min_price     REAL,
    max_price     REAL,
    modal_price   REAL NOT NULL,
    unit          TEXT NOT NULL,          -- Rs/qtl, or Rs/1000 nuts
    qc            TEXT NOT NULL,          -- ok | modal_outside_range
    first_seen    TEXT NOT NULL,          -- UTC ISO, when we first got it
    fetched_at    TEXT NOT NULL,          -- UTC ISO, last refresh
    PRIMARY KEY (arrival_date, state, district, market, commodity,
                 variety, grade)
);
CREATE INDEX IF NOT EXISTS mandi_daily_cs
    ON mandi_daily (commodity, state, arrival_date);

-- Watched villages, as last read from the Sheet / CSV.
CREATE TABLE IF NOT EXISTS villages (
    village_id    TEXT PRIMARY KEY,
    village       TEXT NOT NULL,
    district      TEXT,
    state         TEXT,
    lat           REAL NOT NULL,
    lon           REAL NOT NULL,
    crops         TEXT,
    source        TEXT,
    updated_at    TEXT NOT NULL
);

-- One row per village x forecast issue x day. Kept (not replaced) so
-- forecasts can later be scored against what actually fell.
CREATE TABLE IF NOT EXISTS forecast_daily (
    village_id    TEXT NOT NULL,
    issued_on     TEXT NOT NULL,          -- IST date the job ran
    provider      TEXT NOT NULL,
    date          TEXT NOT NULL,
    rain_mm       REAL,                   -- NULL = not reported, NOT 0
    rain_prob     REAL,
    tmax          REAL,
    tmin          REAL,
    rh_max        REAL,
    rh_min        REAL,
    wind_max      REAL,
    gust_max      REAL,
    et0_mm        REAL,
    weather_code  INTEGER,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (village_id, issued_on, provider, date)
);

-- Hourly detail (disease-weather windows need humidity hours).
-- Pruned to the last few issues; see prune_hourly().
CREATE TABLE IF NOT EXISTS forecast_hourly (
    village_id    TEXT NOT NULL,
    issued_on     TEXT NOT NULL,
    provider      TEXT NOT NULL,
    time          TEXT NOT NULL,          -- local (IST) ISO hour
    temp          REAL,
    rh            REAL,
    dew_point     REAL,
    rain_mm       REAL,
    rain_prob     REAL,
    wind          REAL,
    gust          REAL,
    PRIMARY KEY (village_id, issued_on, provider, time)
);
"""


# ---------------------------------------------------------------- write

def connect(path=None):
    """Read-write connection with the schema in place (jobs only)."""
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    con.commit()
    return con


def upsert(con, table, rows, key, update=None):
    """INSERT ... ON CONFLICT(key) DO UPDATE for a list of dicts.

    `update` lists the columns to refresh on conflict (default: every
    non-key column). Returns the number of rows sent."""
    if not rows:
        return 0
    cols = list(rows[0].keys())
    update = update if update is not None else [
        c for c in cols if c not in key]
    sets = ", ".join(f"{c}=excluded.{c}" for c in update)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)}) "
           f"ON CONFLICT ({', '.join(key)}) "
           + (f"DO UPDATE SET {sets}" if sets else "DO NOTHING"))
    con.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
    return len(rows)


def prune_hourly(con, keep_issues=3):
    """Keep only the newest `keep_issues` issue dates of hourly rows."""
    con.execute(
        "DELETE FROM forecast_hourly WHERE issued_on NOT IN ("
        "SELECT DISTINCT issued_on FROM forecast_hourly "
        "ORDER BY issued_on DESC LIMIT ?)", (keep_issues,))


# ----------------------------------------------------------- read-only

def _ro(path=None):
    """Read-only connection, or None if no job has run yet."""
    path = path or DB_PATH
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True,
                           timeout=10)


def query(sql, params=(), path=None):
    """Run a SELECT and return a DataFrame (empty if no store yet)."""
    con = _ro(path)
    if con is None:
        return pd.DataFrame()
    with closing(con):
        return pd.read_sql_query(sql, con, params=params)


def recent_job_runs(limit=20, path=None):
    return query("SELECT * FROM job_runs ORDER BY id DESC LIMIT ?",
                 (limit,), path)


def last_ok_run(job, path=None):
    """finished_at of the job's last ok/partial run, or None."""
    df = query("SELECT finished_at FROM job_runs WHERE job=? AND "
               "status IN ('ok','partial') ORDER BY id DESC LIMIT 1",
               (job,), path)
    return None if df.empty else df.iloc[0, 0]


def mandi_history(commodity, state=None, since=None, qc_ok=True,
                  path=None):
    """Archived daily prices for one AGMARKNET commodity name."""
    sql = "SELECT * FROM mandi_daily WHERE commodity=?"
    params = [commodity]
    if state:
        sql += " AND state=?"
        params.append(state)
    if since:
        sql += " AND arrival_date>=?"
        params.append(str(since))
    if qc_ok:
        sql += " AND qc='ok'"
    return query(sql + " ORDER BY arrival_date", params, path)


def latest_forecast(village_id, path=None):
    """Daily rows of the newest forecast issue for a village."""
    return query(
        "SELECT * FROM forecast_daily WHERE village_id=? AND issued_on="
        "(SELECT MAX(issued_on) FROM forecast_daily WHERE village_id=?) "
        "ORDER BY date", (village_id, village_id), path)
