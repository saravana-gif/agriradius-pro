"""Generic importer for download-only data.gov.in reference datasets.

Works for any registered dataset (fertilizer, horticulture, land_use,
...). Download the CSV once from data.gov.in, then:

    py tools/import_agri.py fertilizer  "C:\\path\\file.csv"  "Karnataka"
    py tools/import_agri.py horticulture "C:\\path\\file.csv"
    py tools/import_agri.py land_use    "C:\\path\\file.csv"  "Tamil Nadu"

It auto-detects the state / district column, keeps every other column
as-is, and writes to the dataset's file (deduped by state or
state+district). The Allied Sectors tab then shows it for the searched
area automatically - no code changes.

List datasets:  py tools/import_agri.py
"""

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.agri_data import DATASETS

STATE_KEYS = ["state", "statename", "stateut", "statesuts", "states"]
DIST_KEYS = ["district", "districtname", "distname", "dtname", "districts"]


def _key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _find(cols, variants):
    for c in cols:
        if _key(c) in variants:
            return c
    for c in cols:
        if any(v in _key(c) for v in variants):
            return c
    return None


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in DATASETS:
        print("Datasets:")
        for k, v in DATASETS.items():
            print(f"  {k:14s} {v['label']} ({v['level']}-level)")
        print("\nUsage: py tools/import_agri.py <dataset> <file> [State]")
        return

    key = sys.argv[1]
    if len(sys.argv) < 3:
        print("Provide the downloaded CSV path.")
        return
    src = Path(sys.argv[2])
    state_arg = sys.argv[3] if len(sys.argv) > 3 else None
    ds = DATASETS[key]

    if not src.exists():
        print(f"File not found: {src}")
        return

    df = pd.read_csv(src)
    cols = list(df.columns)

    scol = _find(cols, STATE_KEYS)
    dcol = _find(cols, DIST_KEYS)

    out = pd.DataFrame()
    if state_arg:
        out["state"] = [state_arg] * len(df)
    elif scol:
        out["state"] = df[scol].astype(str).str.strip()
    else:
        out["state"] = ""

    if ds["level"] == "district":
        if not dcol:
            print("No district column found. Columns:", cols)
            return
        out["district"] = df[dcol].astype(str).str.strip()

    # keep every other column verbatim
    used = {scol, dcol}
    for c in cols:
        if c in used:
            continue
        out[c] = df[c]

    # drop junk / total rows
    idcol = "district" if ds["level"] == "district" else "state"
    if idcol in out:
        out = out[out[idcol].astype(str).str.strip().str.len() > 0]
        out = out[~out[idcol].astype(str).str.lower().isin(
            ["total", "grand total", "all india", "nan", "all"])]

    target = ds["file"]
    keycols = (["state", "district"] if ds["level"] == "district"
               else ["state"])
    if target.exists() and pd.read_csv(target).shape[0] > 0:
        existing = pd.read_csv(target)
        combined = pd.concat([existing, out], ignore_index=True)
        combined["_k"] = combined[keycols].astype(str).agg("|".join, axis=1)\
            .str.lower()
        combined = combined.drop_duplicates("_k", keep="last")\
            .drop(columns="_k")
    else:
        combined = out

    combined.to_csv(target, index=False)
    print(f"Imported {len(out)} rows into {target.name} "
          f"({ds['level']}-level). Total now {len(combined)}.")


if __name__ == "__main__":
    main()
