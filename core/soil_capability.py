"""SLUSI Detailed Soil Survey — Land Capability Classification (LCC).

The Soil & Land Use Survey of India (SLUSI) has run fine-scale
(1:10,000) detailed soil surveys of selected watersheds and published,
per report, the Land Capability Classification breakdown (Classes I-VIII)
of the surveyed area. This is authoritative, field-measured Indian
soil-suitability data — the thing global SoilGrids cannot give.

Two bundled tables (data/reference/):
  * slusi_dss_district_lcc.csv  - LCC areas aggregated per district
  * slusi_dss_reports.csv       - one row per survey report + PDF link

IMPORTANT vintage / scope caveats (surfaced in the UI):
  * Surveys span 1960-2018; each district's coverage is only the
    watersheds that were surveyed, NOT the whole district.
  * Land capability is a stable soil property, so old surveys remain
    useful as reference — but this is NOT a current land-use map.

LCC classes (standard USDA-derived system used by SLUSI):
  I-IV  = arable / cultivable land (I best, IV marginal)
  V-VIII= non-arable (pasture / forestry / wildlife); VIII unusable
"""

import re
import unicodedata
from functools import lru_cache

import pandas as pd

from config import PROJECT_ROOT

DIST_CSV = PROJECT_ROOT / "data" / "reference" / "slusi_dss_district_lcc.csv"
REPORT_CSV = PROJECT_ROOT / "data" / "reference" / "slusi_dss_reports.csv"

LCC_COLS = ["lcc1", "lcc2", "lcc3", "lcc4", "lcc5", "lcc6", "lcc7", "lcc8"]

CLASS_LABEL = {
    1: "Class I — prime arable (very few limitations)",
    2: "Class II — good arable (minor limitations)",
    3: "Class III — moderate arable (needs conservation)",
    4: "Class IV — marginal arable (severe limitations)",
    5: "Class V — non-arable (pasture / forestry)",
    6: "Class VI — non-arable (restricted grazing / forestry)",
    7: "Class VII — non-arable (steep / erosion-prone)",
    8: "Class VIII — unusable (wildlife / recreation only)",
}

# Old (SLUSI) district name -> modern name, so we match the district
# the app resolves from village polygons. Mirrors core.allied aliases.
ALIAS = {
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
    "CHIKMAGALURU": "CHIKKAMAGALURU",
    "RAMANAGARAM": "RAMANAGARA",
    "THE NILGIRIS": "NILGIRIS",
    "NILGIRIS": "NILGIRIS",
}


def _norm(name):
    """Uppercase, strip accents / non-letters, drop a leading 'THE'."""
    if name is None:
        return ""
    s = unicodedata.normalize("NFKD", str(name))
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z ]", "", s).upper().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^THE ", "", s)
    return s


def _key(name):
    n = _norm(name)
    return ALIAS.get(n, n)


@lru_cache(maxsize=1)
def _districts():
    if not DIST_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(DIST_CSV)
    df["_key"] = df["district"].map(_key)
    return df


@lru_cache(maxsize=1)
def _reports():
    if not REPORT_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(REPORT_CSV)
    return df


def has_data():
    return not _districts().empty


def _summarise(row):
    """Turn one aggregated district row into a friendly summary dict."""
    lcc = [int(row[c]) for c in LCC_COLS]
    classified = sum(lcc)
    arable = sum(lcc[:4])          # I-IV
    marginal = sum(lcc[4:])        # V-VIII
    prime = sum(lcc[:2])           # I-II
    pc = lambda x: round(100 * x / classified, 1) if classified else 0.0

    # dominant class (1-based)
    dom = (lcc.index(max(lcc)) + 1) if classified else None

    return {
        "district": row["district"],
        "state": row["state"],
        "reports": int(row["n_reports"]),
        "surveyed_ha": int(row["area_ha"]),
        "classified_ha": classified,
        "class_ha": {i + 1: lcc[i] for i in range(8)},
        "arable_ha": arable,
        "marginal_ha": marginal,
        "arable_pct": pc(arable),
        "marginal_pct": pc(marginal),
        "prime_pct": pc(prime),
        "dominant_class": dom,
        "dominant_label": CLASS_LABEL.get(dom, "-"),
        "year_min": int(row["year_min"]),
        "year_max": int(row["year_max"]),
    }


def for_district(state, district):
    """Return the LCC summary for one (state, district) or None."""
    df = _districts()
    if df.empty:
        return None
    k = _key(district)
    hit = df[df["_key"] == k]
    if hit.empty:
        return None
    return _summarise(hit.iloc[0])


def for_districts(pairs):
    """Summaries for a list of (state, district) tuples. De-duplicated,
    only those with survey data, ordered by surveyed area desc."""
    out, seen = [], set()
    for state, district in pairs:
        k = _key(district)
        if k in seen:
            continue
        seen.add(k)
        s = for_district(state, district)
        if s:
            out.append(s)
    out.sort(key=lambda s: s["surveyed_ha"], reverse=True)
    return out


def reports_for_district(district, limit=None):
    """Survey reports (report_no, year, pdf_url) touching a district,
    newest first. Matches on the modern district key."""
    df = _reports()
    if df.empty:
        return []
    k = _key(district)
    rows = []
    for _, r in df.iterrows():
        dl = [_key(d) for d in str(r["districts"]).split(",")]
        if k in dl:
            rows.append({
                "report_no": r["report_no"],
                "year": int(r["year"]),
                "districts": r["districts"],
                "pdf_url": r["pdf_url"],
            })
    rows.sort(key=lambda x: x["year"], reverse=True)
    return rows[:limit] if limit else rows


def year_span(summaries):
    """(min_year, max_year) across a list of summaries, or None."""
    if not summaries:
        return None
    return (min(s["year_min"] for s in summaries),
            max(s["year_max"] for s in summaries))
