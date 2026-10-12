"""30-second field reports: what officers saw, where, and whether an
alert was right.

Storage: the Google Sheet tab "FieldReports" (one row per report) when
Sheets is configured, else data/store/field_reports.csv on the server
(gitignored, survives deploys). jobs/field_reports.py copies the rows
into the SQLite store every morning; feedback and 7-day check-backs
become alert_event rows there.

Never record a farmer's name or phone number here - village, crop and
numbers only. Photos are kept on the server (data/store/photos/), not
in the Sheet and not on any public page.
"""

import csv
import datetime
import io
import math
import secrets

from config import PROJECT_ROOT

SHEET_TAB = "FieldReports"
LOCAL_CSV = PROJECT_ROOT / "data" / "store" / "field_reports.csv"
PHOTO_DIR = PROJECT_ROOT / "data" / "store" / "photos"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

COLUMNS = ["report_id", "submitted_at", "reported_on", "officer",
           "village_id", "village", "lat", "lon", "gps_accuracy_m",
           "distance_km", "event", "crop", "qty", "unit", "alert_id",
           "verdict", "note", "photo"]

# event key -> (label, default unit)
EVENTS = {
    "sown": ("Sown / planted", "acres"),
    "rain": ("Rain fell", "mm"),
    "pest": ("Pest or disease seen", "% plants"),
    "harvest": ("Harvest", "quintals"),
    "price": ("Price heard", "Rs/qtl"),
    "borewell": ("Borewell", "feet"),
    "feedback": ("Feedback on an alert", ""),
    "checkback": ("7-day check: was the alert right?", ""),
}
UNITS = ["acres", "mm", "% plants", "quintals", "nuts", "Rs/qtl",
         "Rs/1000 nuts", "feet", "inches of water", ""]
VERDICTS = ["yes", "partly", "no"]
SNAP_KM = 15.0           # farther than this from every village: ask


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def nearest(villages, lat, lon):
    """[(distance_km, village_row)] sorted, nearest first. `villages`
    is a list of dicts with village_id, village, lat, lon."""
    return sorted(((round(haversine_km(lat, lon, v["lat"], v["lon"]), 1),
                    v) for v in villages), key=lambda x: x[0])


def new_report_id(now=None):
    now = now or datetime.datetime.now(IST)
    return f"R{now:%y%m%d}-{secrets.token_hex(3)}"


def make_row(*, officer, village, event, lat=None, lon=None, accuracy=None,
             distance_km=None, crop="", qty=None, unit="", alert_id="",
             verdict="", note="", photo="", now=None):
    """A validated report row (dict keyed by COLUMNS). Raises ValueError
    with a message an officer can act on."""
    if event not in EVENTS:
        raise ValueError(f"unknown event {event!r}")
    if event in ("feedback", "checkback"):
        if not alert_id:
            raise ValueError("Pick the alert this feedback is about.")
        if verdict not in VERDICTS:
            raise ValueError("Choose Yes, Partly or No.")
    if qty not in (None, "") and float(qty) < 0:
        raise ValueError("Quantity can't be negative.")
    now = now or datetime.datetime.now(IST)
    return {
        "report_id": new_report_id(now),
        "submitted_at": now.isoformat(timespec="seconds"),
        "reported_on": now.date().isoformat(),
        "officer": officer or "",
        "village_id": village["village_id"],
        "village": village.get("village", ""),
        "lat": "" if lat is None else round(float(lat), 5),
        "lon": "" if lon is None else round(float(lon), 5),
        "gps_accuracy_m": "" if accuracy is None else round(float(accuracy)),
        "distance_km": "" if distance_km is None else distance_km,
        "event": event, "crop": (crop or "").strip().lower(),
        "qty": "" if qty in (None, "") else float(qty),
        "unit": unit or "", "alert_id": alert_id or "",
        "verdict": verdict or "", "note": (note or "").strip()[:500],
        "photo": photo or "",
    }


def save_photo(report_id, data, max_px=1280, quality=70):
    """Shrink a phone photo to a small JPEG under data/store/photos/.
    Returns the file name."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    im = im.convert("RGB")
    im.thumbnail((max_px, max_px))
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{report_id}.jpg"
    im.save(PHOTO_DIR / name, "JPEG", quality=quality, optimize=True)
    return name


def save(row):
    """Append one report to the Sheet (or the local CSV). Returns
    where it went."""
    from core import sheets
    if sheets.is_enabled():
        # RAW: dates and ids stay text (USER_ENTERED would reformat
        # "2026-10-09" to the Sheet's locale and break the ingest).
        sheets.append_row(SHEET_TAB, row, COLUMNS,
                          value_input_option="RAW")
        return f"sheet:{SHEET_TAB}"
    LOCAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    new = not LOCAL_CSV.exists()
    with open(LOCAL_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow({c: row.get(c, "") for c in COLUMNS})
    return "csv"


def read_all(create=False):
    """(list of row dicts, source). From the Sheet tab if Sheets is on
    (never creating it unless `create`), else the local CSV."""
    from core import sheets
    if sheets.is_enabled():
        df = (sheets.read_records(SHEET_TAB, COLUMNS) if create
              else sheets.read_existing(SHEET_TAB))
        if df is None or df.empty:
            return [], f"sheet:{SHEET_TAB}"
        return df.astype(str).to_dict("records"), f"sheet:{SHEET_TAB}"
    if not LOCAL_CSV.exists():
        return [], "csv"
    with open(LOCAL_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f)), "csv"
