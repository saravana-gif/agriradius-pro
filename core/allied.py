"""Allied / livestock sector intelligence.

Turns the 20th Livestock Census (2019) district counts into an
area-aware profile for any searched point or radius, plus derived
dairy (milk pool) and feed-demand estimates.

Data: district-level cattle / buffalo / goat / sheep / pig / poultry
counts from the 20th Livestock Census 2019, bundled in
data/allied/livestock_district.csv (sourced from the ARTPARK / DAHD
open release). Drop in more states by appending rows - no code change.

Method notes (be honest about what is measured vs estimated):
  * Counts are REAL census figures at DISTRICT level.
  * "Within your radius" numbers are an AREA-ALLOCATION estimate: a
    district's total is split by the share of that district's area
    that falls inside the buffer (computed from the village polygons
    already loaded). Assumes livestock is spread evenly across the
    district - a reasonable first-order estimate, not a headcount.
  * Milk and feed are DERIVED estimates from transparent coefficients
    below, not measured. They are for relative comparison / sizing.
"""

import re
import unicodedata
from functools import lru_cache

import pandas as pd

from config import PROJECT_ROOT

ALLIED_DIR = PROJECT_ROOT / "data" / "allied"
LIVESTOCK_CSV = ALLIED_DIR / "livestock_district.csv"
SERICULTURE_CSV = ALLIED_DIR / "sericulture_district.csv"
FISHERIES_CSV = ALLIED_DIR / "fisheries_district.csv"
SERICULTURE_STATE_CSV = ALLIED_DIR / "sericulture_state.csv"
FISHERIES_STATE_CSV = ALLIED_DIR / "fisheries_state.csv"

# National context where reliable open data is only national.
APICULTURE_NOTE = (
    "Honey output is published at national level (~1.33 lakh MT, "
    "2021-22, National Bee Board); reliable district/state open data "
    "is not available. Karnataka and Tamil Nadu are both active "
    "National Beekeeping & Honey Mission (NBHM) states.")

SPECIES = ["cattle", "buffalo", "goat", "sheep", "pig", "poultry"]

# ---- Derived-estimate coefficients (documented, tunable) ----
# Share of the herd that is an adult female in milk at any time.
MILCH_FRACTION = {"cattle": 0.28, "buffalo": 0.32}
# Average daily milk yield per in-milk animal (litres), Karnataka-
# blend of indigenous + crossbred / graded.
MILK_YIELD_LPD = {"cattle": 4.5, "buffalo": 5.5}
# Concentrate (bought) feed per in-milk bovine, kg/day.
BOVINE_CONCENTRATE_KG = 2.5
# Share of census poultry that is commercial (fed manufactured feed);
# the rest is backyard/foraging. National 20th-census commercial share.
POULTRY_COMMERCIAL_FRAC = 0.65
# Manufactured feed per commercial bird, kg/day (layer/broiler blend).
POULTRY_FEED_KG = 0.10

# District renames between Census-2011 boundaries (old names) and the
# 2019 livestock release (new names).
DISTRICT_ALIAS = {
    "BANGALORE": "BENGALURU URBAN",
    "BANGALORE URBAN": "BENGALURU URBAN",
    "BANGALORE RURAL": "BENGALURU RURAL",
    "BELGAUM": "BELAGAVI",
    "BELLARY": "BALLARI",
    "BIJAPUR": "VIJAYAPURA",
    "GULBARGA": "KALABURAGI",
    "SHIMOGA": "SHIVAMOGGA",
    "TUMKUR": "TUMAKURU",
    "BAGALKOT": "BAGALKOTE",
    "DAVANAGERE": "DAVANGERE",
    "CHIKMAGALUR": "CHIKKAMAGALURU",
    "CHICKMAGALUR": "CHIKKAMAGALURU",
    "CHAMARAJANAGAR": "CHAMARAJANAGARA",
    "CHIKBALLAPUR": "CHIKKABALLAPURA",
    "CHICKBALLAPUR": "CHIKKABALLAPURA",
    "RAMANAGARAM": "RAMANAGARA",
}


def _norm(name):
    """Uppercase, strip accents and non-letters for name matching."""
    if name is None:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z ]", "", s).upper().strip()
    s = re.sub(r"\s+", " ", s)
    return s


@lru_cache(maxsize=1)
def load_livestock():
    """District livestock census as a DataFrame (empty if missing)."""
    if not LIVESTOCK_CSV.exists():
        return pd.DataFrame(
            columns=["state", "district"] + SPECIES)
    df = pd.read_csv(LIVESTOCK_CSV)
    df["_key"] = df["district"].map(_norm)
    df["_state"] = df["state"].map(_norm)
    return df


def _match_row(df, state, district):
    """Find the census row for a (state, district), tolerant of
    renames and old/new spellings. Returns a Series or None."""
    dn = _norm(district)
    dn = DISTRICT_ALIAS.get(dn, dn)
    sub = df[df["_state"] == _norm(state)] if state else df
    if sub.empty:
        sub = df
    hit = sub[sub["_key"] == dn]
    if not hit.empty:
        return hit.iloc[0]
    # Fallback: prefix / close match
    import difflib
    keys = sub["_key"].tolist()
    close = difflib.get_close_matches(dn, keys, n=1, cutoff=0.82)
    if close:
        return sub[sub["_key"] == close[0]].iloc[0]
    return None


def derive_dairy_feed(counts):
    """Given a dict of species counts, return derived milk + feed
    estimates. All values rounded; clearly ESTIMATES."""
    cattle = counts.get("cattle", 0) or 0
    buffalo = counts.get("buffalo", 0) or 0
    poultry = counts.get("poultry", 0) or 0

    milch_cattle = cattle * MILCH_FRACTION["cattle"]
    milch_buffalo = buffalo * MILCH_FRACTION["buffalo"]

    milk_lpd = (milch_cattle * MILK_YIELD_LPD["cattle"]
                + milch_buffalo * MILK_YIELD_LPD["buffalo"])

    bovine_feed_tpd = (milch_cattle + milch_buffalo) \
        * BOVINE_CONCENTRATE_KG / 1000.0
    poultry_feed_tpd = (poultry * POULTRY_COMMERCIAL_FRAC
                        * POULTRY_FEED_KG) / 1000.0

    return {
        "milch_bovines": round(milch_cattle + milch_buffalo),
        "milk_litres_per_day": round(milk_lpd),
        "milk_litres_per_year": round(milk_lpd * 365),
        "bovine_feed_tpd": round(bovine_feed_tpd, 1),
        "poultry_feed_tpd": round(poultry_feed_tpd, 1),
        "total_feed_tpd": round(bovine_feed_tpd + poultry_feed_tpd, 1),
    }


def _district_area_shares(lat, lon, radius_km):
    """For each (state, district) touching the buffer, return
    (area_in_buffer, area_total) in the same projected units, using
    the village polygons already bundled.

    Returns dict {(state_norm, district_norm): (a_in, a_tot)}.
    """
    from data.gis_data import GIS_DATA
    from gis.boundary_loader import load_boundaries
    from gis.spatial import _buffer_geometry

    buf = _buffer_geometry(lat, lon, radius_km).to_crs(3857)
    buf_geom = buf.geometry.iloc[0]

    out = {}
    for state in GIS_DATA:
        if "villages" not in GIS_DATA[state]:
            continue
        try:
            gdf = load_boundaries(state, "villages")
        except Exception:
            continue
        if "dtname" not in gdf.columns:
            continue
        gdf = gdf.to_crs(3857)
        dist = gdf["dtname"].map(_norm)

        # candidate villages intersecting the buffer bounds
        try:
            cand_idx = list(gdf.sindex.intersection(buf.total_bounds))
        except Exception:
            cand_idx = list(range(len(gdf)))
        cand = gdf.iloc[cand_idx]
        cand_dist = dist.iloc[cand_idx]
        inside = cand[cand.intersects(buf_geom)]
        if inside.empty:
            continue
        inside_dist = cand_dist.loc[inside.index]

        clip_area = inside.geometry.intersection(buf_geom).area
        state_norm = _norm(state)

        for d in inside_dist.unique():
            a_in = float(clip_area[inside_dist == d].sum())
            a_tot = float(gdf.geometry.area[dist == d].sum())
            out[(state_norm, d)] = (a_in, a_tot)

    return out


def area_profile(lat, lon, radius_km, state_hint=None):
    """Livestock profile for a searched radius.

    Returns dict with per-district rows (real district totals) and an
    area-allocated 'within radius' aggregate + derived dairy/feed.
    """
    df = load_livestock()
    if df.empty:
        return {"available": False, "reason": "no livestock data bundled"}

    shares = _district_area_shares(lat, lon, radius_km)

    rows = []
    agg = {s: 0.0 for s in SPECIES}
    matched_any = False

    # Group share keys by district-name (state may be normed folder).
    for (state_norm, dist_norm), (a_in, a_tot) in shares.items():
        row = _match_row(df, state_norm, dist_norm)
        if row is None:
            continue
        matched_any = True
        frac = (a_in / a_tot) if a_tot > 0 else 0.0
        frac = min(frac, 1.0)
        rec = {"District": row["district"].title(),
               "State": row["state"],
               "AreaShare": round(frac, 3)}
        for s in SPECIES:
            total = float(row.get(s, 0) or 0)
            rec[s] = int(total)
            agg[s] += total * frac
        rows.append(rec)

    if not matched_any:
        return {"available": False,
                "reason": "no census match for districts in view"}

    agg = {s: round(v) for s, v in agg.items()}
    derived = derive_dairy_feed(agg)

    rows.sort(key=lambda r: r.get("cattle", 0), reverse=True)

    return {
        "available": True,
        "within_radius": agg,
        "derived": derived,
        "districts": rows,
    }


@lru_cache(maxsize=2)
def _load_generic(path_str):
    """Load a district CSV keyed for matching. Empty if missing/blank."""
    from pathlib import Path
    path = Path(path_str)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    if df.empty or "district" not in df.columns:
        return pd.DataFrame()
    df["_key"] = df["district"].map(_norm)
    df["_state"] = df.get("state", "").map(_norm) \
        if "state" in df.columns else ""
    return df


def sector_for_districts(path, districts):
    """Return the rows of a district CSV for the given district names.

    districts: iterable of (state, district) strings. Returns a
    DataFrame of matched rows (real values), or empty if none / no
    data bundled yet.
    """
    df = _load_generic(str(path))
    if df.empty:
        return pd.DataFrame()
    rows = []
    seen = set()
    for state, district in districts:
        row = _match_row_generic(df, state, district)
        if row is not None and row["_key"] not in seen:
            seen.add(row["_key"])
            rows.append(row.drop(labels=["_key", "_state"]))
    return pd.DataFrame(rows).reset_index(drop=True) if rows \
        else pd.DataFrame()


def _match_row_generic(df, state, district):
    dn = _norm(district)
    dn = DISTRICT_ALIAS.get(dn, dn)
    sub = df[df["_state"] == _norm(state)] if state and "_state" in df \
        else df
    if sub.empty:
        sub = df
    hit = sub[sub["_key"] == dn]
    if not hit.empty:
        return hit.iloc[0]
    import difflib
    close = difflib.get_close_matches(dn, sub["_key"].tolist(),
                                      n=1, cutoff=0.82)
    if close:
        return sub[sub["_key"] == close[0]].iloc[0]
    return None


def districts_touching(lat, lon, radius_km):
    """Unique (state, district) names whose villages fall in the buffer."""
    shares = _district_area_shares(lat, lon, radius_km)
    return [(s, d) for (s, d) in shares.keys()]


def _norm_state(name):
    """State-name key: uppercase letters only (drops spaces so
    'Tamil Nadu' == folder 'tamilnadu')."""
    return re.sub(r"[^A-Z]", "", _norm(name))


def states_touching(lat, lon, radius_km):
    """Normalised state keys whose villages fall in the buffer."""
    shares = _district_area_shares(lat, lon, radius_km)
    return sorted({_norm_state(s) for (s, d) in shares.keys()})


def state_sector_rows(path, state_keys):
    """Return rows of a state-level CSV for the given normalised state
    keys. Empty DataFrame if the file is missing or nothing matches."""
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    if df.empty or "state" not in df.columns:
        return pd.DataFrame()
    keys = set(state_keys)
    mask = df["state"].map(lambda s: _norm_state(s) in keys)
    return df[mask].reset_index(drop=True)


def point_profile(lat, lon, state=None, district=None):
    """Livestock profile for the district containing a point."""
    df = load_livestock()
    if df.empty:
        return {"available": False, "reason": "no livestock data bundled"}

    if district is None:
        from gis.spatial import village_at_point
        v = village_at_point(lat, lon) or {}
        district = v.get("District")
        state = state or v.get("State")

    if not district:
        return {"available": False,
                "reason": "point is outside loaded boundaries"}

    row = _match_row(df, state or "", district)
    if row is None:
        return {"available": False,
                "reason": f"no census row for {district}"}

    counts = {s: int(row.get(s, 0) or 0) for s in SPECIES}
    return {
        "available": True,
        "district": row["district"].title(),
        "state": row["state"],
        "counts": counts,
        "derived": derive_dairy_feed(counts),
    }
