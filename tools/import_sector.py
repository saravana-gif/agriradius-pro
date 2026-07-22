"""Import a district-level sericulture or fisheries CSV into the app.

Same idea as import_livestock.py: district-level sericulture (cocoon /
mulberry) and fisheries (inland fish) files on data.gov.in sit behind
a login, so download once, drop the file anywhere, and run this. It
maps the columns and writes data/allied/<sector>_district.csv. The
Allied Sectors tab then shows district rows (which take priority over
the state-level figure) automatically.

Usage:
    py tools/import_sector.py sericulture "C:\\path\\ka_cocoon.csv" "Karnataka"
    py tools/import_sector.py fisheries   "C:\\path\\tn_fish.csv"   "Tamil Nadu"

The state name (last arg) is optional if the CSV already has a state
column. Column names are auto-detected from common variants.
"""

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ALLIED = ROOT / "data" / "allied"

# sector -> (target file, {canonical: [header variants]})
SECTORS = {
    "sericulture": (
        ALLIED / "sericulture_district.csv",
        {
            "mulberry_ha": ["mulberryarea", "mulberryha", "areaundermulberry",
                            "mulberryareaha", "areamulberry", "mulberry"],
            "cocoon_mt": ["cocoonproduction", "cocoon", "cocoonmt",
                          "cocoonproductionmt", "cocoonproductioninmts",
                          "productionofcocoon", "cocoonproductionintonnes"],
            "reeling_units": ["reelingunits", "reeling", "noofreelingunits"],
        },
    ),
    "fisheries": (
        ALLIED / "fisheries_district.csv",
        {
            "inland_water_ha": ["inlandwaterarea", "waterarea", "areaha",
                                "waterspreadarea", "inlandwaterha", "area"],
            "fish_production_tonnes": ["fishproduction", "inlandfishproduction",
                                       "production", "fishproductiontonnes",
                                       "productiontonnes", "fishproductionmt",
                                       "inlandfishproductiontonnes"],
        },
    ),
}

DISTRICT_KEYS = ["district", "districtname", "distname", "dtname", "districts"]
STATE_KEYS = ["state", "statename", "stateut"]


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _find(df, variants):
    # Exact match first, then substring (handles unit suffixes like
    # "Area under Mulberry (Ha)" -> areaundermulberryha).
    for col in df.columns:
        if _key(col) in variants:
            return col
    for variant in variants:
        for col in df.columns:
            if variant in _key(col):
                return col
    return None


def _to_num(series):
    return pd.to_numeric(
        series.astype(str).str.replace(r"[^0-9.]", "", regex=True),
        errors="coerce")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    sector = sys.argv[1].lower()
    src = Path(sys.argv[2])
    state_arg = sys.argv[3] if len(sys.argv) > 3 else None

    if sector not in SECTORS:
        print(f"Unknown sector '{sector}'. Use: {list(SECTORS)}")
        sys.exit(1)
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)

    target, metric_aliases = SECTORS[sector]
    df = pd.read_csv(src)

    dcol = _find(df, DISTRICT_KEYS)
    if dcol is None:
        print("No district column found. Columns seen:", list(df.columns))
        sys.exit(1)

    out = pd.DataFrame()
    out["district"] = df[dcol].astype(str).str.strip()
    scol = _find(df, STATE_KEYS)
    if state_arg:
        out["state"] = state_arg
    elif scol:
        out["state"] = df[scol].astype(str).str.strip()
    else:
        print("No state given and no state column found. Pass the state "
              "name as the last argument.")
        sys.exit(1)

    found = []
    for canon, variants in metric_aliases.items():
        col = _find(df, variants)
        if col is not None:
            out[canon] = _to_num(df[col]).round(1)
            found.append(canon)

    if not found:
        print(f"No {sector} metric columns detected. Columns seen:")
        print(list(df.columns))
        sys.exit(1)

    out = out[out["district"].str.len() > 0]
    out = out[~out["district"].str.lower().isin(
        ["total", "grand total", "state total", "all", "nan"])]

    cols = ["state", "district"] + found
    out = out[cols]

    if target.exists():
        existing = pd.read_csv(target)
        combined = pd.concat([existing, out], ignore_index=True)
        # keep only rows that actually have a district
        combined = combined[combined["district"].notna()]
        combined["_k"] = (combined["state"].astype(str).str.lower().str.strip()
                          + "|"
                          + combined["district"].astype(str).str.lower()
                          .str.strip())
        combined = combined.drop_duplicates("_k", keep="last") \
            .drop(columns="_k")
    else:
        combined = out

    combined.to_csv(target, index=False)
    print(f"Imported {len(out)} {sector} rows "
          f"({', '.join(found)}) for "
          f"{out['state'].iloc[0] if len(out) else state_arg}.")
    print(f"{target.name} now has {len(combined)} district rows.")


if __name__ == "__main__":
    main()
