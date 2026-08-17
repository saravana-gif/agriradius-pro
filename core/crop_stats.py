"""Karnataka department crop statistics - the yardstick for our acreage.

What the bundled file holds (data/Karnataka_Crop_Forest_Toolkit/data/
ka_crop_data_2022_23.csv, pulled from data.gov.in resources):

  * maize_irrigated_area   - irrigated maize hectares per DISTRICT,
                             2022-23. Directly comparable to the app's
                             maize detection.
  * plantation_production  - plantation-crop output (coconut in
                             thousand nuts, arecanut/cashew etc. in
                             tonnes).
  * horticulture_state_total - state horticulture area/output.
  * top_taluk_<crop>       - the leading TALUKS for banana, grapes,
                             mango, onion and tomato. This is the piece
                             that makes a satellite class actionable:
                             the app can detect "short-cycle irrigated
                             vegetable" but never "tomato"; the taluk
                             ranking says which vegetable it most
                             likely is.

Used two ways:
  1. as a cross-check - department hectares beside detected acres, so
     the app's numbers can be judged rather than trusted;
  2. as a crop-naming prior - what actually grows in this taluk.

Pure data - no streamlit, no folium.
"""

import csv
import re
from functools import lru_cache

from config import PROJECT_ROOT

CSV_PATH = (PROJECT_ROOT / "data" / "Karnataka_Crop_Forest_Toolkit"
            / "data" / "ka_crop_data_2022_23.csv")

VINTAGE = "Karnataka DES / horticulture department, 2022-23"
HA_TO_AC = 2.47105


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


@lru_cache(maxsize=1)
def _load():
    if not CSV_PATH.exists():
        return []
    rows = []
    try:
        with CSV_PATH.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    r["value_num"] = float(
                        str(r.get("value", "")).replace(",", ""))
                except (TypeError, ValueError):
                    r["value_num"] = None
                r["_place"] = _key(r.get("area_or_district_or_taluk"))
                rows.append(r)
    except Exception:
        return []
    return rows


def available():
    return bool(_load())


def datasets():
    return sorted({r["dataset"] for r in _load()})


def maize_area(districts):
    """Department irrigated-maize area for the districts in view."""
    want = {_key(d) for d in (districts or [])}
    hits = [r for r in _load()
            if r["dataset"] == "maize_irrigated_area"
            and r["_place"] in want and r["value_num"]]
    if not hits:
        return None
    ha = sum(r["value_num"] for r in hits)
    return {
        "districts": [r["area_or_district_or_taluk"] for r in hits],
        "area_ha": round(ha),
        "area_ac": round(ha * HA_TO_AC),
        "year": hits[0].get("year"),
        "vintage": VINTAGE,
    }


def plantation_production(crop=None):
    """Plantation-crop output rows, optionally for one crop."""
    out = []
    for r in _load():
        if r["dataset"] != "plantation_production":
            continue
        if crop and _key(crop) not in _key(r.get("crop")):
            continue
        out.append({
            "crop": r.get("crop"),
            "place": r.get("area_or_district_or_taluk"),
            "value": r.get("value_num"),
            "unit": r.get("unit"),
            "year": r.get("year"),
        })
    return out


def top_taluks(taluks=None):
    """Which crops these taluks are ranked leaders for.

    The practical use: the satellite can say "short-cycle irrigated
    vegetable"; this says whether that taluk leads the state in tomato,
    onion, banana, grapes or mango.
    """
    want = {_key(t) for t in (taluks or [])}
    out = []
    for r in _load():
        if not r["dataset"].startswith("top_taluk_"):
            continue
        if want and r["_place"] not in want:
            continue
        out.append({
            "taluk": r.get("area_or_district_or_taluk"),
            "crop": r.get("crop") or r["dataset"]
            .replace("top_taluk_", "").title(),
            "value": r.get("value_num"),
            "unit": r.get("unit"),
            "year": r.get("year"),
        })
    out.sort(key=lambda d: -(d.get("value") or 0))
    return out


def crop_hints(taluks):
    """One line naming the crops these taluks lead the state in."""
    rows = top_taluks(taluks)
    if not rows:
        return None
    names = []
    for r in rows:
        c = str(r["crop"]).title()
        if c not in names:
            names.append(c)
    return ("Department data ranks "
            + ", ".join(sorted({str(r['taluk']).title()
                                for r in rows}))
            + " among Karnataka's leading taluks for "
            + ", ".join(names)
            + " - so an unidentified irrigated short-cycle crop here "
              "is most likely one of those.")


def compare_maize(districts, detected_ac):
    """Detected maize acreage against the department's figure."""
    dept = maize_area(districts)
    if not dept or detected_ac is None:
        return None
    ratio = (round(100 * detected_ac / dept["area_ac"])
             if dept["area_ac"] else None)
    if ratio is None:
        return None
    if ratio <= 130 and ratio >= 40:
        reading = ("The detection is the right order of magnitude "
                   "against the department's district figure.")
    elif ratio > 130:
        reading = ("The detection exceeds the department figure. "
                   "Expected when the circle covers only part of the "
                   "district (the department number is district-wide) "
                   "or when other tall kharif cereals are picked up.")
    else:
        reading = ("The detection is well below the department figure - "
                   "expected when the circle is a small slice of a "
                   "large district.")
    return {
        "detected_ac": round(detected_ac),
        "department_ac": dept["area_ac"],
        "department_ha": dept["area_ha"],
        "districts": dept["districts"],
        "ratio_pct": ratio,
        "reading": reading,
        "caveat": ("The department figure is for the WHOLE district, "
                   "the detection only for your circle, so treat this "
                   "as a sanity check on scale, not an accuracy "
                   "score."),
        "vintage": VINTAGE,
    }
