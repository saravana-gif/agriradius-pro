"""Government crop-survey reference data - MEASURED coconut area.

Source: the Karnataka crop survey / FRUITS parcel export for coconut,
2023-24 Kharif - 547,325 survey-number-level records carrying GPS
coordinates, the farmer's attached extent, irrigation status and a
geo-accuracy flag.

Every record was matched to its census-2011 village polygon by
point-in-polygon (145,746 of 145,748 distinct coordinates matched) and
then AGGREGATED PER VILLAGE, so nothing farmer-identifying ships with
the app - no farmer IDs, no survey numbers, no per-parcel rows.

Districts covered: Hassan, Mandya, Tumakuru, Ramanagara, Chitradurga
and Mysuru, plus a few border villages that fall inside Chikkamagaluru
and Chamarajanagara polygons.

Per-village columns (data/reference/coconut_survey/<district>.csv):

  vilcode11        census-2011 village code - joins the boundary layer
  village, taluk   display names
  parcels          coconut survey-number entries recorded
  farmers          distinct farmers holding those parcels
  extent_ha        coconut land in the village. The survey records a
                   grower's total attached extent once per plot, so
                   each grower's extent is ALLOCATED evenly across
                   their plots before being summed per village - this
                   avoids the double counting you get by summing the
                   raw column, and makes the district totals line up
                   with published coconut area (Hassan 109,713 ha,
                   Tumakuru 89,645 ha, Mandya 82,549 ha, 325,169 ha
                   across all six districts).
  irrigated_pct    share of parcels recorded as irrigated
  village_area_ha  village polygon area, used for density
  lat, lon         median parcel coordinate in that village

Pure data - no streamlit, no folium.
"""

import csv
import math
from functools import lru_cache

from config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data" / "reference" / "coconut_survey"

VINTAGE = "Karnataka crop survey, 2023-24 Kharif"
CROP = "Coconut"

# file slug -> display district name
DISTRICT_LABELS = {
    "hassan": "Hassan",
    "mandya": "Mandya",
    "tumakuru": "Tumakuru",
    "ramanagara": "Ramanagara",
    "chitradurga": "Chitradurga",
    "mysuru": "Mysuru",
    "chikkamagaluru": "Chikkamagaluru",
    "chamarajanagara": "Chamarajanagara",
}

_NUM = ("parcels", "farmers", "extent_ha", "irrigated_pct",
        "village_area_ha", "lat", "lon")

HA_TO_AC = 2.47105


def _slug(name):
    return "".join(c for c in str(name).lower() if c.isalpha())


@lru_cache(maxsize=1)
def _load():
    """Read every district file once. Returns (rows, by_code).

    Each row is a plain dict; numbers are floats. Missing or unreadable
    files are skipped so a partial bundle still works.
    """
    rows, by_code = [], {}
    if not DATA_DIR.exists():
        return rows, by_code

    for path in sorted(DATA_DIR.glob("*.csv")):
        district = DISTRICT_LABELS.get(path.stem, path.stem.title())
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    row = dict(r)
                    row["district"] = district
                    for k in _NUM:
                        try:
                            row[k] = float(row.get(k) or 0)
                        except (TypeError, ValueError):
                            row[k] = 0.0
                    code = str(row.get("vilcode11") or "").strip()
                    row["vilcode11"] = code
                    rows.append(row)
                    if code:
                        by_code[code] = row
        except Exception:
            continue
    return rows, by_code


def available():
    """True when the bundled survey data could be read."""
    return bool(_load()[0])


def districts():
    """Sorted list of district names present in the bundle."""
    return sorted({r["district"] for r in _load()[0]})


def covers_district(name):
    return _slug(name) in {_slug(d) for d in districts()}


def density_pct(row):
    """Coconut land as a % of the village polygon, capped at 100.

    A handful of villages exceed 100% because a grower's holding can
    sit just outside the polygon its plot was matched to - hence the
    cap, and the 'intensity' framing rather than an exact share.
    """
    area = float(row.get("village_area_ha") or 0)
    if area <= 0:
        return None
    return min(100.0, round(100.0 * float(row.get("extent_ha") or 0)
                            / area, 1))


def by_vilcode(code):
    """One village row by census-2011 code, or None."""
    if not code:
        return None
    return _load()[1].get(str(code).strip())


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def in_radius(lat, lon, radius_km):
    """Village rows whose median parcel coordinate is inside the circle.

    A cheap bounding-box prefilter keeps this fast without any GIS
    dependency - the file is small enough to scan.
    """
    rows, _ = _load()
    if not rows:
        return []

    pad_lat = radius_km / 110.6
    coslat = max(0.2, math.cos(math.radians(float(lat))))
    pad_lon = radius_km / (111.3 * coslat)

    out = []
    for r in rows:
        rlat, rlon = r["lat"], r["lon"]
        if not rlat or not rlon:
            continue
        if abs(rlat - lat) > pad_lat or abs(rlon - lon) > pad_lon:
            continue
        if _haversine_km(lat, lon, rlat, rlon) <= radius_km:
            out.append(r)
    return out


def _summarise(rows):
    if not rows:
        return None
    parcels = sum(r["parcels"] for r in rows)
    ha = sum(r["extent_ha"] for r in rows)
    area = sum(r["village_area_ha"] for r in rows)
    irr = sum(r["irrigated_pct"] * r["parcels"] for r in rows)
    return {
        "villages": len(rows),
        "parcels": int(parcels),
        "farmers": int(sum(r["farmers"] for r in rows)),
        "extent_ha": round(ha, 1),
        "extent_ac": round(ha * HA_TO_AC),
        "irrigated_pct": round(irr / parcels) if parcels else None,
        "area_ha": round(area),
        "density_pct": (round(100 * ha / area, 1) if area else None),
        "districts": sorted({r["district"] for r in rows}),
    }


def radius_summary(lat, lon, radius_km):
    """Measured coconut totals inside the analysis circle, or None."""
    return _summarise(in_radius(lat, lon, radius_km))


def district_summary(district):
    """Measured coconut totals for one district, or None."""
    key = _slug(district)
    rows = [r for r in _load()[0] if _slug(r["district"]) == key]
    return _summarise(rows)


def top_villages(district=None, lat=None, lon=None, radius_km=None,
                 top=25, by="extent_ha"):
    """Ranked villages by measured coconut presence.

    Filter by district, or by circle when lat/lon/radius are given.
    """
    if lat is not None and lon is not None and radius_km:
        rows = in_radius(lat, lon, radius_km)
    elif district:
        key = _slug(district)
        rows = [r for r in _load()[0] if _slug(r["district"]) == key]
    else:
        rows = _load()[0]

    out = []
    for r in rows:
        out.append({
            "village": r["village"],
            "taluk": r["taluk"],
            "district": r["district"],
            "coconut_ac": round(r["extent_ha"] * HA_TO_AC),
            "parcels": int(r["parcels"]),
            "farmers": int(r["farmers"]),
            "irrigated_pct": int(r["irrigated_pct"]),
            "intensity_pct": density_pct(r),
        })
    out.sort(key=lambda d: -(d["coconut_ac"] if by == "extent_ha"
                             else d["parcels"]))
    return out[:top] if top else out


def validate_plantation(lat, lon, radius_km, detected_ac):
    """Cross-check the satellite plantation detection against the
    measured survey for the same circle.

    Returns None when the area isn't covered by the survey. Otherwise a
    dict with the two figures, their ratio and a plain-English verdict.
    Satellite detection sits below the survey by design - young palms
    and thin spacing don't register as closed canopy - so a moderate
    shortfall is healthy and only large gaps are flagged.
    """
    s = radius_summary(lat, lon, radius_km)
    if not s or not s["parcels"]:
        return None
    try:
        detected_ac = float(detected_ac or 0)
    except (TypeError, ValueError):
        return None

    survey_ac = s["extent_ac"]
    if survey_ac <= 0:
        return None

    ratio = round(100 * detected_ac / survey_ac)

    if ratio >= 130:
        verdict = ("Satellite finds MORE perennial canopy than the "
                   "coconut survey records - expected where arecanut, "
                   "mango or other orchards grow alongside coconut.")
    elif ratio >= 60:
        verdict = ("Satellite detection lines up with the measured "
                   "coconut survey for this area.")
    elif ratio >= 30:
        verdict = ("Satellite finds noticeably less canopy than the "
                   "survey records. Young or thinly spaced palms are "
                   "the usual reason.")
    else:
        verdict = ("Large gap: the survey records far more coconut "
                   "land here than the satellite flags. Treat the "
                   "detection as a floor, not a total.")

    return {
        "survey_ac": survey_ac,
        "survey_villages": s["villages"],
        "survey_parcels": s["parcels"],
        "detected_ac": round(detected_ac),
        "ratio_pct": ratio,
        "verdict": verdict,
        "vintage": VINTAGE,
    }
