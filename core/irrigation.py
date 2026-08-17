"""Karnataka irrigation by SOURCE - measured government statistics.

Why this matters more than it looks: Karnataka's net irrigated area is
5.04 M ha and 56.6% of it is borewell/tubewell. Borewells are invisible
to canal command-area maps and are drilled far faster than land records
are updated. So the way you find irrigated land flips completely by
district:

  * canal-led districts (Raichur 77%, Yadgir, Mandya) - command-area
    maps find the farms for you, no satellite work needed;
  * borewell-led districts (Tumakuru 99.5%, Chitradurga 99.3%,
    Vijayapura 91.4%) - command-area maps are useless, only satellite
    or current land records will do.

Source: Land Use Statistics, DES-Agri (Ministry of Agriculture &
Farmers Welfare), 2022-23, all 31 districts. Bundled at
data/Karnataka_Irrigation_Toolkit/data/.

Pure data - no streamlit, no folium.
"""

import csv
import re
from functools import lru_cache

from config import PROJECT_ROOT

DIR = PROJECT_ROOT / "data" / "Karnataka_Irrigation_Toolkit" / "data"
WIDE = DIR / "ka_net_irrigated_area_by_source_2022_23_wide.csv"
LONG = DIR / "ka_net_gross_irrigated_area_by_source_2022_23_long.csv"

VINTAGE = "Land Use Statistics (DES-Agri), 2022-23"
STATE = "Karnataka"

SOURCES = [
    ("Borewell/Tubewell", "Borewell / tubewell"),
    ("Canal (Government)", "Canal (government)"),
    ("Canal (Private)", "Canal (private)"),
    ("Open/Dug Well", "Open / dug well"),
    ("Tank", "Tank"),
    ("Other Source", "Other (mostly lift)"),
]

HA_TO_AC = 2.47105

# The statistics and the boundary file spell some districts differently,
# and Ramanagara was renamed Bengaluru South in 2024.
_ALIAS = {
    "chamarajanagar": "chamarajanagara",
    "davanagere": "davangere",
    "vijayanagara": "vijayanagar",
    "bengalurusouth": "ramanagara",
    "ramanagaram": "ramanagara",
    "bangalorerural": "bengalururural",
    "bangaloreurban": "bengaluruurban",
    "bellary": "ballari",
    "bijapur": "vijayapura",
    "gulbarga": "kalaburagi",
    "mysore": "mysuru",
    "tumkur": "tumakuru",
    "shimoga": "shivamogga",
    "chikmagalur": "chikkamagaluru",
    "chickballapur": "chikkaballapura",
    "bagalkot": "bagalkote",
    "belgaum": "belagavi",
    "hubli": "dharwad",
}


def key(name):
    """Normalised district key, alias-folded."""
    k = re.sub(r"[^a-z]", "", str(name or "").lower())
    return _ALIAS.get(k, k)


def _num(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return 0.0


@lru_cache(maxsize=1)
def _load():
    """{district_key: row} with sources, totals, shares and gross area."""
    rows = {}
    if not WIDE.exists():
        return rows

    try:
        with WIDE.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                name = (r.get("district") or "").strip()
                if not name:
                    continue
                srcs = {c: _num(r.get(c)) for c, _ in SOURCES}
                net = _num(r.get("Total Net Irrigated (ha)")) or \
                    sum(srcs.values())
                rows[key(name)] = {
                    "district": name,
                    "sources": srcs,
                    "net_ha": net,
                    "gross_ha": 0.0,
                }
    except Exception:
        return {}

    # Gross irrigated area (same land counted once per season) tells you
    # how hard the irrigated land is worked.
    try:
        if LONG.exists():
            with LONG.open(newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if "gross" not in str(r.get("measure", "")).lower():
                        continue
                    k = key(r.get("district"))
                    if k in rows:
                        rows[k]["gross_ha"] += _num(r.get("area_ha"))
    except Exception:
        pass

    for row in rows.values():
        net = row["net_ha"]
        row["shares"] = {
            c: (round(100 * row["sources"][c] / net, 1) if net else None)
            for c, _ in SOURCES
        }
        canal = (row["sources"]["Canal (Government)"]
                 + row["sources"]["Canal (Private)"])
        row["canal_ha"] = canal
        row["canal_pct"] = round(100 * canal / net, 1) if net else None
        row["borewell_pct"] = row["shares"]["Borewell/Tubewell"]
        row["well_pct"] = row["shares"]["Open/Dug Well"]
        row["tank_pct"] = row["shares"]["Tank"]
        row["other_pct"] = row["shares"]["Other Source"]
        dom = max(row["sources"].items(), key=lambda kv: kv[1])
        row["dominant"] = dom[0] if dom[1] > 0 else None
        row["intensity"] = (round(row["gross_ha"] / net, 2)
                            if net and row["gross_ha"] else None)
        row["net_ac"] = round(net * HA_TO_AC)
    return rows


def available():
    return bool(_load())


def districts():
    return sorted(r["district"] for r in _load().values())


def for_district(name):
    """One district's irrigation profile, or None."""
    return _load().get(key(name))


def for_districts(names):
    """Profiles for a list of district names (missing ones dropped)."""
    out, seen = [], set()
    for n in names or []:
        k = key(n)
        if k in seen:
            continue
        row = _load().get(k)
        if row:
            seen.add(k)
            out.append(row)
    return out


def state_totals():
    """Karnataka-wide net irrigated area by source."""
    rows = _load()
    if not rows:
        return None
    net = sum(r["net_ha"] for r in rows.values())
    srcs = {c: sum(r["sources"][c] for r in rows.values())
            for c, _ in SOURCES}
    return {
        "net_ha": round(net),
        "net_ac": round(net * HA_TO_AC),
        "districts": len(rows),
        "sources": srcs,
        "shares": {c: (round(100 * v / net, 1) if net else None)
                   for c, v in srcs.items()},
        "vintage": VINTAGE,
    }


def area_summary(names):
    """Irrigation profile aggregated over the districts in view."""
    rows = for_districts(names)
    if not rows:
        return None
    net = sum(r["net_ha"] for r in rows)
    gross = sum(r["gross_ha"] for r in rows)
    srcs = {c: sum(r["sources"][c] for r in rows) for c, _ in SOURCES}
    canal = srcs["Canal (Government)"] + srcs["Canal (Private)"]
    shares = {c: (round(100 * v / net, 1) if net else None)
              for c, v in srcs.items()}
    dom = max(srcs.items(), key=lambda kv: kv[1])
    return {
        "districts": [r["district"] for r in rows],
        "net_ha": round(net),
        "net_ac": round(net * HA_TO_AC),
        "gross_ha": round(gross),
        "intensity": round(gross / net, 2) if net and gross else None,
        "sources": srcs,
        "shares": shares,
        "borewell_pct": shares["Borewell/Tubewell"],
        "canal_pct": round(100 * canal / net, 1) if net else None,
        "dominant": dom[0] if dom[1] > 0 else None,
        "vintage": VINTAGE,
    }


def targeting_note(summary):
    """How to find irrigated farms here, given the source mix.

    This is the practical payoff of the dataset: it tells field staff
    whether a canal map is enough or whether they need satellite work.
    """
    if not summary:
        return None
    bore = summary.get("borewell_pct") or 0
    canal = summary.get("canal_pct") or 0

    if canal >= 40:
        return ("Canal-led ({:.0f}% of irrigated land). Command-area "
                "boundaries locate irrigated farms directly - work "
                "outward from the canal network before spending any "
                "satellite budget.".format(canal))
    if bore >= 80:
        return ("Borewell-dominated ({:.0f}% of irrigated land). Canal "
                "and command-area maps are useless here: these wells "
                "are invisible to infrastructure data and are drilled "
                "faster than land records update. Use the satellite "
                "irrigation layers and current land records."
                .format(bore))
    if bore >= 50:
        return ("Borewell-led ({:.0f}% borewell vs {:.0f}% canal). "
                "Expect scattered, individually-owned irrigation - "
                "satellite screening first, then ground checks."
                .format(bore, canal))
    return ("Mixed sources ({:.0f}% borewell, {:.0f}% canal). Use the "
            "canal command areas where they exist and satellite "
            "screening for the rest.".format(bore, canal))


def rankings(names=None, by="net_ha"):
    """Districts ranked for the report tables."""
    rows = for_districts(names) if names else list(_load().values())
    out = []
    for r in rows:
        out.append({
            "district": r["district"],
            "net_irrigated_ac": r["net_ac"],
            "borewell_pct": r["borewell_pct"],
            "canal_pct": r["canal_pct"],
            "tank_pct": r["tank_pct"],
            "well_pct": r["well_pct"],
            "dominant_source": r["dominant"],
            "gross_to_net": r["intensity"],
        })
    keymap = {"net_ha": "net_irrigated_ac", "borewell": "borewell_pct",
              "canal": "canal_pct"}
    col = keymap.get(by, "net_irrigated_ac")
    out.sort(key=lambda d: -(d.get(col) or 0))
    return out


# Kannada land-class terms that appear in the land records - useful in
# the report because field staff meet them constantly.
GLOSSARY = [
    ("Khushki / Jirayat", "Dry, rain-fed land"),
    ("Tari", "Wet land - canal or tank irrigated, usually paddy"),
    ("Bagayat", "Garden land - well/borewell irrigated, "
                "horticulture or plantation"),
    ("Neeravari", "Irrigation / irrigated"),
    ("Ayakat", "Area commanded under a given irrigation source"),
    ("Bele Sameekshe", "The seasonal Crop Survey"),
]

CAVEATS = [
    "These are district AGGREGATES. No government or commercial "
    "product gives a reliable, current, plot-level irrigated/rain-fed "
    "flag for all of Karnataka - only the RTC/Pahani (authoritative "
    "for land class, stale for new borewells) and the seasonal Crop "
    "Survey come close, and neither has an open bulk API.",
    "Rabi jowar, chickpea and safflower on black cotton soil in "
    "Vijayapura, Bagalkote, Kalaburagi, Bidar and Vijayanagara are "
    "largely RAIN-FED, grown on stored vertisol moisture. A "
    "'green in rabi = irrigated' rule mislabels much of north "
    "Karnataka - which is why the satellite layer here uses the "
    "February-May summer window instead.",
    "Expect 80-90% parcel-level accuracy in the semi-arid interior "
    "and north, but only 60-75% in coastal Karnataka, Malnad and the "
    "Western Ghats, where year-round rain hides the irrigation "
    "signal.",
]
