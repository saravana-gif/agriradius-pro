"""Import a state's Livestock Census CSV into the app.

Why this exists: Tamil Nadu (and most states') 20th Livestock Census
district files are public but sit behind data.gov.in's login / JS
portal, so they can't be auto-fetched. Download the CSV once, drop it
anywhere, and run this - it maps the columns to the app's schema and
appends the rows to data/allied/livestock_district.csv (deduping by
state+district). No other code changes needed; the Allied Sectors tab
picks the new state up automatically.

Usage:
    py tools/import_livestock.py "C:\\path\\to\\tamilnadu_livestock.csv" "Tamil Nadu"

The second argument (state name) is optional if the CSV already has a
state column. Column names are auto-detected from common variants
(data.gov.in, DAHD, ARTPARK, indiastat exports).
"""

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "data" / "allied" / "livestock_district.csv"

SPECIES = ["cattle", "buffalo", "goat", "sheep", "pig", "poultry"]

# Header variants -> our canonical column. Matching is done on a
# lowercased, alphanumeric-only version of each incoming header.
ALIASES = {
    "district": ["district", "districtname", "distname", "dtname",
                 "districts"],
    "state": ["state", "statename", "statut", "stateut"],
    "cattle": ["cattle", "totalcattle", "cattletotal",
               "populationcattle"],
    "buffalo": ["buffalo", "buffaloes", "totalbuffalo",
                "populationbuffalo"],
    "goat": ["goat", "goats", "totalgoat", "populationgoat"],
    "sheep": ["sheep", "sheeps", "totalsheep", "populationsheep"],
    "pig": ["pig", "pigs", "totalpig", "populationpig"],
    "poultry": ["poultry", "totalpoultry", "poultrytotal",
                "populationpoultry", "fowls", "totalfowls"],
}


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _resolve_columns(df):
    """Map incoming columns to canonical names."""
    lookup = {}
    for col in df.columns:
        k = _key(col)
        for canon, variants in ALIASES.items():
            if k in variants:
                lookup[canon] = col
                break
    return lookup


def _to_int(series):
    return (pd.to_numeric(
        series.astype(str).str.replace(r"[^0-9.]", "", regex=True),
        errors="coerce").fillna(0).round().astype(int))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    src = Path(sys.argv[1])
    state_arg = sys.argv[2] if len(sys.argv) > 2 else None

    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)

    df = pd.read_csv(src)
    cols = _resolve_columns(df)

    if "district" not in cols:
        print("Could not find a district column. Columns seen:")
        print(list(df.columns))
        sys.exit(1)

    have = [s for s in SPECIES if s in cols]
    if not have:
        print("No livestock species columns detected. Columns seen:")
        print(list(df.columns))
        sys.exit(1)

    out = pd.DataFrame()
    out["district"] = df[cols["district"]].astype(str).str.strip()
    if state_arg:
        out["state"] = state_arg
    elif "state" in cols:
        out["state"] = df[cols["state"]].astype(str).str.strip()
    else:
        print("No state given and no state column found. Pass the "
              "state name as the 2nd argument.")
        sys.exit(1)

    for s in SPECIES:
        out[s] = _to_int(df[cols[s]]) if s in cols else 0

    # Drop blank/total rows
    out = out[out["district"].str.len() > 0]
    out = out[~out["district"].str.lower().isin(
        ["total", "grand total", "state total", "all", "nan"])]

    out = out[["state", "district"] + SPECIES]

    # Merge with existing, dedupe on (state, district)
    if TARGET.exists():
        existing = pd.read_csv(TARGET)
        combined = pd.concat([existing, out], ignore_index=True)
        combined["_k"] = (combined["state"].str.lower().str.strip()
                          + "|" + combined["district"].str.lower()
                          .str.strip())
        combined = combined.drop_duplicates("_k", keep="last") \
            .drop(columns="_k")
    else:
        combined = out

    combined.to_csv(TARGET, index=False)
    print(f"Imported {len(out)} rows for "
          f"{out['state'].iloc[0] if len(out) else state_arg}.")
    print(f"{TARGET} now has {len(combined)} district rows across "
          f"{combined['state'].nunique()} state(s).")


if __name__ == "__main__":
    main()
