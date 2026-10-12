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

SCHEMA_VERSION = 3

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

-- Observed daily rain per village (jobs/rain.py). One row per source,
-- so a fallback value never hides behind an IMD one; readers prefer
-- imd. IMD's rain day D is 08:30 IST on D to 08:30 IST on D+1.
CREATE TABLE IF NOT EXISTS rain_daily (
    village_id    TEXT NOT NULL,
    date          TEXT NOT NULL,
    source        TEXT NOT NULL,          -- imd | open_meteo
    rain_mm       REAL,                   -- NULL = missing, NOT 0
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (village_id, date, source)
);

-- Monthly rain 1981-2025 per village for normals and SPI
-- (jobs/rain_baseline.py, one-time fill). A month that could not be
-- read has no row (retried next run); NULL = no data at that pixel.
CREATE TABLE IF NOT EXISTS rain_monthly_baseline (
    village_id    TEXT NOT NULL,
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    source        TEXT NOT NULL,          -- chirps
    rain_mm       REAL,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (village_id, year, month, source)
);

-- Per-village feature snapshots written by jobs, one row per day and
-- kind ('rain', ...). vintage_json says which data they rest on.
CREATE TABLE IF NOT EXISTS village_features (
    village_id    TEXT NOT NULL,
    as_of         TEXT NOT NULL,          -- IST date of the run
    kind          TEXT NOT NULL,
    features_json TEXT NOT NULL,
    vintage_json  TEXT NOT NULL,
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (village_id, as_of, kind)
);

-- Alert log (jobs/alerts.py). APPEND-ONLY: a row is never updated or
-- deleted (the triggers below refuse it); what happens to an alert
-- afterwards (shared, feedback, check-back, withdrawn) goes into
-- alert_event. Each row keeps the features, data vintage, rule hash
-- and git SHA it was made from, so it can be audited and scored.
CREATE TABLE IF NOT EXISTS alert (
    alert_id      TEXT PRIMARY KEY,       -- e.g. 1012-K7QF
    created_at    TEXT NOT NULL,          -- UTC ISO
    as_of         TEXT NOT NULL,          -- IST date
    village_id    TEXT NOT NULL,
    crop          TEXT NOT NULL,          -- '' = whole village
    rule_id       TEXT NOT NULL,
    rule_group    TEXT NOT NULL,
    rule_hash     TEXT NOT NULL,
    severity      TEXT NOT NULL,          -- red | amber | green
    kind          TEXT NOT NULL,          -- weather | pest | disease | harvest
    title         TEXT NOT NULL,
    text_en       TEXT NOT NULL,          -- rendered English draft
    source        TEXT NOT NULL,
    approved_by   TEXT NOT NULL,          -- '' = draft, cannot be shared
    shareable     INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    trace_json    TEXT NOT NULL,          -- each condition and its value
    vintage_json  TEXT NOT NULL,
    git_sha       TEXT
);
CREATE INDEX IF NOT EXISTS alert_village ON alert (village_id, as_of);
CREATE TRIGGER IF NOT EXISTS alert_no_update BEFORE UPDATE ON alert
BEGIN SELECT RAISE(ABORT, 'alert is append-only: add an alert_event'); END;
CREATE TRIGGER IF NOT EXISTS alert_no_delete BEFORE DELETE ON alert
BEGIN SELECT RAISE(ABORT, 'alert is append-only'); END;

CREATE TABLE IF NOT EXISTS alert_event (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id      TEXT NOT NULL REFERENCES alert (alert_id),
    at            TEXT NOT NULL,          -- UTC ISO
    event         TEXT NOT NULL,          -- created | shared | feedback | checkback | withdrawn
    actor         TEXT,
    detail_json   TEXT
);
CREATE INDEX IF NOT EXISTS alert_event_alert ON alert_event (alert_id);
CREATE TRIGGER IF NOT EXISTS alert_event_no_update BEFORE UPDATE ON
alert_event BEGIN SELECT RAISE(ABORT, 'alert_event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS alert_event_no_delete BEFORE DELETE ON
alert_event BEGIN SELECT RAISE(ABORT, 'alert_event is append-only'); END;
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


def prune_daily(con, keep_days=180):
    """Drop daily forecast issues older than `keep_days` - enough to
    score forecasts against a season of observed rain."""
    con.execute("DELETE FROM forecast_daily WHERE issued_on < "
                "date('now', ?)", (f"-{int(keep_days)} days",))


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


def latest_features(kind, village_id=None, path=None):
    """Newest feature snapshot of `kind` per village: DataFrame with
    village_id, as_of, features (dict), vintage (dict)."""
    import json
    sql = ("SELECT f.village_id, f.as_of, f.features_json, f.vintage_json "
           "FROM village_features f JOIN (SELECT village_id, "
           "MAX(as_of) AS as_of FROM village_features WHERE kind=? "
           "GROUP BY village_id) m ON f.village_id=m.village_id AND "
           "f.as_of=m.as_of WHERE f.kind=?")
    params = [kind, kind]
    if village_id:
        sql += " AND f.village_id=?"
        params.append(village_id)
    df = query(sql, params, path)
    if df.empty:
        return df
    df["features"] = df.pop("features_json").map(json.loads)
    df["vintage"] = df.pop("vintage_json").map(json.loads)
    return df


def recent_alerts(since, village_id=None, path=None):
    """Alerts with as_of >= since (newest first), plus their latest
    check-back verdict if any."""
    sql = ("SELECT a.*, (SELECT json_extract(e.detail_json, '$.verdict') "
           "FROM alert_event e WHERE e.alert_id=a.alert_id AND "
           "e.event='checkback' ORDER BY e.id DESC LIMIT 1) AS verdict "
           "FROM alert a WHERE a.as_of>=?")
    params = [str(since)]
    if village_id:
        sql += " AND a.village_id=?"
        params.append(village_id)
    return query(sql + " ORDER BY a.as_of DESC, CASE a.severity WHEN "
                 "'red' THEN 0 WHEN 'amber' THEN 1 ELSE 2 END", params,
                 path)


def add_alert_event(alert_id, event, actor=None, detail=None, path=None):
    """Append one alert_event (shared / feedback / checkback / withdrawn)
    from the app. The only write the app makes to the store: a single
    append, never an update."""
    import datetime
    import json
    con = connect(path)
    try:
        if not con.execute("SELECT 1 FROM alert WHERE alert_id=?",
                           (alert_id,)).fetchone():
            raise ValueError(f"no alert {alert_id}")
        con.execute(
            "INSERT INTO alert_event (alert_id, at, event, actor, "
            "detail_json) VALUES (?, ?, ?, ?, ?)",
            (alert_id, datetime.datetime.now(datetime.timezone.utc)
             .isoformat(timespec="seconds"), event, actor,
             json.dumps(detail or {})))
        con.commit()
    finally:
        con.close()
