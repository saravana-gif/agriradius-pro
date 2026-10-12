"""The list of villages scheduled jobs watch (forecasts, later alerts).

Source, first that has rows wins:
1. Google Sheet tab "Villages" (when GSHEET_ID + GCP_SERVICE_ACCOUNT
   are configured) - field staff edit this.
2. data/watch_villages.csv on the server (gitignored).
3. data/reference/watch_villages.example.csv - town-centre examples
   so a fresh install produces something; replace them.

Columns (header row, case-insensitive):
    village_id  optional; stable key. Default: village-district slug.
                Keep it fixed once set - stored forecasts hang off it.
    village     required
    district, state, crops   optional (crops: "turmeric;banana")
    lat, lon    required, decimal degrees
    active      optional; no/false/0 skips the row
"""

import logging
import re

import pandas as pd

from config import PROJECT_ROOT

log = logging.getLogger(__name__)

SHEET_TAB = "Villages"
LOCAL_CSV = PROJECT_ROOT / "data" / "watch_villages.csv"
EXAMPLE_CSV = PROJECT_ROOT / "data" / "reference" / \
    "watch_villages.example.csv"

COLUMNS = ["village_id", "village", "district", "state", "lat", "lon",
           "crops"]

# Loose box around Karnataka + Tamil Nadu: catches swapped lat/lon and
# typos without having to load boundary files.
LAT_RANGE = (7.5, 19.0)
LON_RANGE = (73.5, 81.0)


def _slug(*parts):
    s = "-".join(str(p) for p in parts if p and str(p).strip())
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _s(v):
    """Cell -> stripped string; blank/NaN -> ''."""
    return "" if v is None or pd.isna(v) else str(v).strip()


def normalise(df):
    """Raw table -> clean DataFrame[COLUMNS]. Bad rows are logged and
    skipped, never guessed at."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.rename(columns=lambda c: str(c).strip().lower())
    out, seen = [], set()
    for i, r in df.iterrows():
        name = _s(r.get("village"))
        if _s(r.get("active")).lower() in ("no", "false",
                                                         "0", "n"):
            continue
        try:
            lat, lon = float(r.get("lat")), float(r.get("lon"))
        except (TypeError, ValueError):
            lat = lon = None
        if not name or lat is None or lon is None:
            log.warning("villages row %d skipped: needs village, lat, "
                        "lon", i + 2)
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]
                and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            log.warning("villages row %d (%s) skipped: %.4f,%.4f is "
                        "outside KA/TN - lat/lon swapped?", i + 2, name,
                        lat, lon)
            continue
        district = _s(r.get("district"))
        vid = _s(r.get("village_id")) or _slug(name, district)
        if vid in seen:
            log.warning("villages row %d skipped: duplicate id %s",
                        i + 2, vid)
            continue
        seen.add(vid)
        out.append({
            "village_id": vid, "village": name, "district": district,
            "state": _s(r.get("state")),
            "lat": round(lat, 5), "lon": round(lon, 5),
            "crops": _s(r.get("crops")),
        })
    return pd.DataFrame(out, columns=COLUMNS)


def load():
    """(DataFrame[COLUMNS], source_label)."""
    from core import sheets
    if sheets.is_enabled():
        try:
            raw = sheets.read_existing(SHEET_TAB)
            if raw is None:
                log.info("no '%s' tab in the Sheet - using local list",
                         SHEET_TAB)
            else:
                df = normalise(raw)
                if not df.empty:
                    return df, f"sheet:{SHEET_TAB}"
                log.warning("'%s' tab has no usable rows", SHEET_TAB)
        except Exception as e:
            log.warning("could not read '%s' tab (%s) - using local "
                        "list", SHEET_TAB, type(e).__name__)
    for path, label in ((LOCAL_CSV, "csv"), (EXAMPLE_CSV, "example")):
        if path.exists():
            df = normalise(pd.read_csv(path, dtype=str,
                                         keep_default_na=False))
            if not df.empty:
                if label == "example":
                    log.warning("using EXAMPLE villages - add a "
                                "'%s' Sheet tab or %s", SHEET_TAB,
                                LOCAL_CSV.name)
                return df, label
    return pd.DataFrame(columns=COLUMNS), "none"
