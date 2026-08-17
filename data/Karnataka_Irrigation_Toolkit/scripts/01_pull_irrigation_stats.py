#!/usr/bin/env python3
"""
Karnataka irrigation data — bulk pullers for the two APIs that actually work.

Run from India, or from anywhere with unrestricted egress. Both endpoints were
verified live on 17 Aug 2026.

    pip install requests pandas
    python 01_pull_irrigation_stats.py --all --api-key YOUR_DATA_GOV_IN_KEY

Get a free data.gov.in key at https://www.data.gov.in/ (My Account -> Generate API key).
The CKAN puller needs no key at all.
"""
import argparse, json, time, sys
import requests
import pandas as pd

OUT = "."

# --------------------------------------------------------------------------
# 1. District x year x source  —  India Data Portal CKAN mirror of DES-Agri LUS
#    No API key. Server-side filters WORK here.  181,500 rows total.
# --------------------------------------------------------------------------
CKAN = "https://ckandev.indiadataportal.com/api/3/action/datastore_search"
LUS_RESOURCE = "ef174105-0886-45f2-bd0d-679c45e05845"


def pull_lus(state="Karnataka", year=None, page=1000):
    """District-level net & gross irrigated area by source. Karnataka = 9,024 rows."""
    filters = {"state_name": state}
    if year:
        filters["year"] = year          # e.g. "2022-2023"
    rows, offset = [], 0
    while True:
        r = requests.get(CKAN, params={
            "resource_id": LUS_RESOURCE,
            "filters": json.dumps(filters),
            "limit": page, "offset": offset,
        }, timeout=120)
        r.raise_for_status()
        res = r.json()["result"]
        batch = res["records"]
        rows += batch
        total = res.get("total", 0)
        print(f"  LUS {offset + len(batch)}/{total}", file=sys.stderr)
        offset += page
        if offset >= total or not batch:
            break
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # tidy source labels
    df["source_label"] = df.apply(_label, axis=1)
    return df


def _label(r):
    sub = str(r.get("area_sub_classification", ""))
    cls = str(r.get("area_classification", ""))
    if sub == "Tubewell":
        return "Borewell/Tubewell"
    if sub == "Other Well":
        return "Open/Dug Well"
    if cls == "Canal":
        return f"Canal ({sub})"
    return cls


def lus_wide(df, measure="Net Irrigated Area", year=None):
    d = df[df.irrigated_area_type == measure]
    if year:
        d = d[d.year == year]
    d = d.copy()
    d["irrigated_area"] = pd.to_numeric(d["irrigated_area"], errors="coerce")
    w = d.pivot_table(index=["year", "district_name"], columns="source_label",
                      values="irrigated_area", aggfunc="sum")
    w["TOTAL"] = w.sum(axis=1, min_count=1)
    for c in ["Borewell/Tubewell", "Canal (Government)"]:
        if c in w.columns:
            w[c + " share %"] = (w[c] / w["TOTAL"] * 100).round(1)
    return w.reset_index()


# --------------------------------------------------------------------------
# 2. VILLAGE-level minor irrigation infrastructure  —  data.gov.in
#    Needs a free API key. Server-side filters are BROKEN on these resources:
#    filters[state]=Karnataka silently returns 0 rows. So we page everything
#    and filter locally. ~193k rows = ~193 calls at limit=1000.
# --------------------------------------------------------------------------
OGD = "https://api.data.gov.in/resource/{uuid}"

MI_CENSUS_5 = {
    "dugwells_by_type":                 "89baee64-e9c8-4e8e-9576-dd8b4bac3372",
    "dugwells_perm_not_in_use_reasons": "31e12b93-5a9a-4d48-9cfa-d3dd3a3d834a",
    "dugwells_by_owner_holding_size":   "ec58e04e-a054-4a9e-b027-fead3e00df95",
    "dugwells_cost_of_construction":    "07b451ee-964a-4f6f-9043-f40f9e05b361",
    "dugwells_cost_of_maintenance":     "c3fe8960-298f-4547-99b8-4d6bcb39d19d",
    "dugwells_cca_potential_temp":      "7e1303cd-ef6a-4c0b-b05d-1bd3e56d63d0",
    "dugwells_cca_potential_perm":      "d149dea5-632a-46d0-8a53-374d727f66d7",
    "surface_lift_ownership":           "9936122b-7699-4fa9-bf7a-d6752a1cc0eb",
    "surface_lift_utilisation":         "edb308f2-6a1f-4610-abc3-6ffac265acfc",
    "surface_lift_construction_cost":   "2fdbacd7-33d9-4152-a241-6e0e07eed8a8",
    "surface_lift_maintenance_cost":    "a88e11b9-ac8d-4cda-960f-b4993ed1459e",
    "surface_lift_owner_social_status": "7f30854d-53c6-4dbb-bc6b-2c1727dad19e",
    "surface_lift_water_distribution":  "7194ce53-fe08-4914-b3dd-e8c582c3cae2",
    "surface_lift_pumping_hours":       "6c55a118-9ea1-4d47-92bb-0892840df992",
}

# Ministry of Agriculture, district x year x source (same data as CKAN above,
# different encoding: irrigationsource = e.g. "Net_Wells_Tubewell")
LUS_OGD = "512a034f-6924-42d8-9a76-d40bfb56424a"


def pull_ogd(uuid, api_key, state="Karnataka", state_field="state", page=1000, sleep=0.3):
    rows, offset = [], 0
    while True:
        r = requests.get(OGD.format(uuid=uuid), params={
            "api-key": api_key, "format": "json",
            "limit": page, "offset": offset,
        }, timeout=180)
        r.raise_for_status()
        j = r.json()
        batch = j.get("records", [])
        total = j.get("total", 0)
        if state and state_field in (batch[0] if batch else {}):
            batch = [b for b in batch
                     if state.lower().replace(" ", "") in str(b.get(state_field, "")).lower().replace(" ", "")]
        rows += batch
        offset += page
        print(f"  {uuid[:8]} {offset}/{total} kept={len(rows)}", file=sys.stderr)
        if offset >= total:
            break
        time.sleep(sleep)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", help="data.gov.in API key (needed for --mi-census)")
    ap.add_argument("--state", default="Karnataka")
    ap.add_argument("--year", default=None, help='e.g. "2022-2023"; omit for all years 1998-2024')
    ap.add_argument("--lus", action="store_true", help="district-level source-wise irrigated area (no key needed)")
    ap.add_argument("--mi-census", action="store_true", help="VILLAGE-level minor irrigation infrastructure (needs key)")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.lus or a.all:
        print("== Land Use Statistics: district x year x irrigation source ==", file=sys.stderr)
        df = pull_lus(a.state, a.year)
        df.to_csv(f"{OUT}/lus_sources_of_irrigation_{a.state.lower()}.csv", index=False)
        print(f"wrote {len(df)} rows")
        if not df.empty:
            w = lus_wide(df, "Net Irrigated Area", a.year)
            w.to_csv(f"{OUT}/lus_net_irrigated_wide_{a.state.lower()}.csv", index=False)
            print(w.tail(10).to_string())

    if a.mi_census or a.all:
        if not a.api_key:
            print("!! --mi-census needs --api-key (free from data.gov.in)", file=sys.stderr)
        else:
            print("== 5th Minor Irrigation Census: VILLAGE level ==", file=sys.stderr)
            for name, uuid in MI_CENSUS_5.items():
                try:
                    d = pull_ogd(uuid, a.api_key, a.state, state_field="state")
                    d.to_csv(f"{OUT}/mi5_{name}_{a.state.lower()}.csv", index=False)
                    print(f"  {name}: {len(d)} Karnataka rows")
                except Exception as e:
                    print(f"  {name}: FAILED {e}", file=sys.stderr)
