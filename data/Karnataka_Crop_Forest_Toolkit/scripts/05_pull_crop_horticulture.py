#!/usr/bin/env python3
"""
Karnataka crop-wise data pullers — taluk horticulture, crop-wise irrigated area,
gram-panchayat crop records, and daily APMC prices.

    pip install requests pandas
    python 05_pull_crop_horticulture.py --all --api-key YOUR_DATA_GOV_IN_KEY

IMPORTANT — the demo key trap:
The widely-circulated public demo key works but CAPS EVERY RESPONSE AT 10 RECORDS,
whatever limit you pass. A 228-row taluk file then takes 23 calls. Register your
own free key at https://www.data.gov.in/ and this disappears. The script pages
correctly either way; it is just slower on the demo key.

All endpoints verified live on 17 August 2026.
"""
import argparse, json, sys, time
import requests
import pandas as pd

DEMO_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
OGD = "https://api.data.gov.in/resource/{uuid}"
CKAN = "https://ckandev.indiadataportal.com/api/3/action/datastore_search"

# ---------------------------------------------------------------------------
# Karnataka DES taluk-level horticulture series (228 taluks, 2018-19).
# Publisher: Planning & Statistics Dept / Directorate of Economics & Statistics.
# File "b" carries dist_code + taluk_code, which are KGIS codes — join key to
# KGIS taluk polygons. The other files key on kgistalukname only, so join them
# to "b" on name first to inherit the codes.
# Row 1 of each file is a STATE TOTAL (kgistalukname 'NA' or 'State total') — drop it.
# ---------------------------------------------------------------------------
HORTI_TALUK = {
    "fruits_b":     ("bfc85e6a-7165-4758-9143-080db4fddfd1", "banana, mango, lemon, pineapple, guava, grapes"),
    "fruits_c":     ("489411a3-b1d8-45b5-b2a8-91df86f1a23e", "sapota, pomegranate, papaya, orange, watermelon"),
    "veg_d":        ("4543cdc5-6939-46cc-8c6c-142143ebad1e", "tomato, brinjal, cucumber, beans, cluster beans, cabbage, ridge gourd"),
    "veg_e":        ("02ad6bf0-218a-401b-9e37-a3f5b699dbac", "radish, onion, beetroot, carrot, knol khol, okra, green chillies, snake gourd"),
    "veg_f":        ("851b03af-a68e-4a72-b3de-efdec43ad49b", "potato, pumpkin, cauliflower"),
    "plantation_prod": ("11654dc5-4d33-4c7d-96ba-ecfd013ec2e0", "PRODUCTION: coconut, arecanut, cardamom, pepper, cashewnut, cocoa"),
    "fruits_prod":  ("f4e1c769-949e-4b65-8fc7-fc3aa645c31e", "PRODUCTION: banana, mango, lemon, pineapple, guava, grapes, sapota, pomegranate, papaya"),
}

# PMFBY crop-cutting experiments — GRAM PANCHAYAT level crop + irrigation_type.
# Fields: district_name, taluk_name, gram_panchayat_or_hobli, hobli_name,
#         gram_panchayat, crop_name, irrigation_type, no_cce_conducted, averageyieldperha
# Covers insured CCE crops only (maize yes; no horticulture). 2016-17 to 2018-19.
CCE_KA = {
    "bengaluru_urban_kharif_2018_19": "26fa23d5-a3c7-46c2-8510-463bd1a87c59",
    "davangere_kharif_2018_19":       "47c80296-eb6f-4da6-b4c0-9fd39c9a6a69",
    "belagavi_kharif_2018_19":        "0e7e3d7f-765c-42ed-947f-7828299a9100",
    "chitradurga_kharif_2018_19":     "d9d2aacc-3c2f-4707-8600-7d761f07b1b7",
    "haveri_summer_2018_19":          "9ac8847c-739b-49bf-989c-a33385877a2f",
    "kolar_kharif_2018_19":           "5d7111c6-f06b-4307-b006-c995007d243e",
    "shivamogga_rabi_2018_19":        "316b1c4a-3ebd-4071-b7ce-08f80316ab6f",
    "mysuru_rabi_2018_19":            "6b6ab848-48ac-4b39-b8cf-d14c12138a8a",
    "chamarajanagar_kharif_2018_19":  "d3db2fab-e999-4782-afde-c5d2c9ed5458",
    "chikkamagaluru_kharif_2018_19":  "d8d089eb-c47a-4a6c-867e-e47760badcbf",
}

APMC_DAILY = "9ef84268-d588-465a-a308-a864a43d0070"
CROP_IRRIGATED_CKAN = "0fb99c18-a1f7-46f0-b40d-ddffca021319"


def pull_ogd(uuid, api_key, page=100, sleep=0.3, max_pages=400, **filters):
    """Page an api.data.gov.in resource. Handles the demo key's 10-record cap."""
    rows, offset, pages = [], 0, 0
    while pages < max_pages:
        params = {"api-key": api_key, "format": "json", "limit": page, "offset": offset}
        for k, v in filters.items():
            params[f"filters[{k}]"] = v
        r = requests.get(OGD.format(uuid=uuid), params=params, timeout=120)
        r.raise_for_status()
        j = r.json()
        batch = j.get("records", [])
        total = j.get("total", 0)
        rows += batch
        if not batch:
            break
        offset += len(batch)          # advance by what we actually got, not by `page`
        pages += 1
        print(f"    {len(rows)}/{total}", file=sys.stderr)
        if offset >= total:
            break
        time.sleep(sleep)
    return pd.DataFrame(rows)


def pull_ckan(resource_id, page=100, **filters):
    """Page a CKAN datastore resource. limit=100 genuinely works here, no key needed."""
    rows, offset = [], 0
    while True:
        r = requests.get(CKAN, params={"resource_id": resource_id,
                                       "filters": json.dumps(filters),
                                       "limit": page, "offset": offset}, timeout=120)
        r.raise_for_status()
        res = r.json()["result"]
        batch = res["records"]
        rows += batch
        total = res.get("total", 0)
        offset += page
        print(f"    {min(offset, total)}/{total}", file=sys.stderr)
        if offset >= total or not batch:
            break
    return pd.DataFrame(rows)


def build_taluk_crop_matrix(api_key):
    """Join all the horticulture area files into one taluk x crop matrix.

    Output: one row per taluk, one column per crop, area in hectares, with the
    KGIS dist_code / taluk_code attached so it joins straight to KGIS polygons.
    """
    frames = {}
    for name, (uuid, crops) in HORTI_TALUK.items():
        print(f"  {name}: {crops}", file=sys.stderr)
        df = pull_ogd(uuid, api_key)
        if df.empty:
            print(f"    !! {name} returned nothing", file=sys.stderr)
            continue
        df.to_csv(f"ka_horti_{name}.csv", index=False)
        frames[name] = df

    if "fruits_b" not in frames:
        print("!! cannot build matrix without file 'b' (it carries the KGIS codes)", file=sys.stderr)
        return None

    base = frames["fruits_b"].copy()
    base["kgistalukname"] = base["kgistalukname"].astype(str).str.strip()
    # drop the state-total row
    base = base[~base["kgistalukname"].str.upper().isin(["NA", "STATE TOTAL", "NAN", ""])]
    out = base

    for name in ["fruits_c", "veg_d", "veg_e", "veg_f"]:
        if name not in frames:
            continue
        f = frames[name].copy()
        f["kgistalukname"] = f["kgistalukname"].astype(str).str.strip()
        f = f[~f["kgistalukname"].str.upper().isin(["NA", "STATE TOTAL", "NAN", ""])]
        drop = [c for c in ["dist_code", "taluk_code", "entry_year", "sl_no"] if c in f.columns]
        f = f.drop(columns=drop)
        out = out.merge(f, on="kgistalukname", how="outer", suffixes=("", f"_{name}"))

    for c in out.columns:
        if c not in ("kgistalukname", "dist_code", "taluk_code", "entry_year"):
            out[c] = pd.to_numeric(out[c], errors="coerce")

    out.to_csv("ka_taluk_crop_area_matrix.csv", index=False)
    print(f"wrote ka_taluk_crop_area_matrix.csv  ({len(out)} taluks, {len(out.columns)} columns)")
    return out


def pull_apmc(api_key, commodities=("Maize", "Turmeric", "Banana", "Tomato", "Onion", "Potato")):
    """Daily APMC prices. NOTE: this is a SNAPSHOT — no history is retained
    server-side, so run it on a cron and append if you want a time series.
    Filter key is 'state', not 'state_name', and values are case-sensitive."""
    out = []
    for c in commodities:
        try:
            df = pull_ogd(APMC_DAILY, api_key, state="Karnataka", commodity=c)
            if not df.empty:
                out.append(df)
                print(f"  {c}: {len(df)} market rows", file=sys.stderr)
            else:
                print(f"  {c}: no arrivals reported today", file=sys.stderr)
        except Exception as e:
            print(f"  {c}: FAILED {e}", file=sys.stderr)
    if out:
        d = pd.concat(out, ignore_index=True)
        d.to_csv("ka_apmc_prices_snapshot.csv", index=False)
        print(f"wrote ka_apmc_prices_snapshot.csv ({len(d)} rows)")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=DEMO_KEY,
                    help="data.gov.in key. The default demo key is capped at 10 records/call.")
    ap.add_argument("--year", default="2022-2023")
    ap.add_argument("--horticulture", action="store_true", help="taluk-level horticulture area + production")
    ap.add_argument("--crops", action="store_true", help="district crop-wise IRRIGATED area (CKAN, no key)")
    ap.add_argument("--cce", action="store_true", help="gram-panchayat crop + irrigation_type records")
    ap.add_argument("--apmc", action="store_true", help="today's APMC price snapshot")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.api_key == DEMO_KEY and (a.horticulture or a.cce or a.apmc or a.all):
        print("NOTE: using the public demo key — responses are capped at 10 records each, "
              "so this will be slow. Get a free key at data.gov.in.\n", file=sys.stderr)

    if a.horticulture or a.all:
        print("== Karnataka taluk-level horticulture ==", file=sys.stderr)
        build_taluk_crop_matrix(a.api_key)

    if a.crops or a.all:
        print("== Crop-wise IRRIGATED area, district level ==", file=sys.stderr)
        df = pull_ckan(CROP_IRRIGATED_CKAN, state_name="Karnataka", year=a.year)
        df.to_csv(f"ka_crop_irrigated_area_{a.year}.csv", index=False)
        print(f"wrote {len(df)} rows")
        if not df.empty:
            df["area"] = pd.to_numeric(df["area"], errors="coerce")
            top = df.groupby("crop_name")["area"].sum().sort_values(ascending=False).head(15)
            print("\nTop crops by irrigated area (ha):")
            print(top.to_string())

    if a.cce or a.all:
        print("== Gram-panchayat crop records (PMFBY CCE) ==", file=sys.stderr)
        for name, uuid in CCE_KA.items():
            try:
                d = pull_ogd(uuid, a.api_key)
                d.to_csv(f"ka_cce_{name}.csv", index=False)
                print(f"  {name}: {len(d)} rows")
            except Exception as e:
                print(f"  {name}: FAILED {e}", file=sys.stderr)

    if a.apmc or a.all:
        print("== APMC daily price snapshot ==", file=sys.stderr)
        pull_apmc(a.api_key)
