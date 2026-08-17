#!/usr/bin/env python3
"""
KGIS Web API — the lat/long <-> survey number bridge.

This is the single most operationally useful API for field-staff targeting in
Karnataka. It turns a GPS ping into District/Taluk/Hobli/Village/Survey Number,
and a survey number into a polygon (WKT) you can run satellite statistics over.

Docs (verified live 17 Aug 2026): https://kgis.ksrsac.in/kgis/webapi.aspx

IMPORTANT: KSRSAC documents the twelve services, their parameters and their
response fields, but does NOT publish the base URLs or the auth mechanism.
The `deptcode` / `applncode` parameters imply per-department provisioning.
Email kgissupport@ksrsac.in to request base URLs + keys, then fill in
KGIS_BASE and KGIS_AUTH below. Everything else in this file is ready.

Services documented (name -> what it gives you):
  1  Admin Hierarchy          type=kgis|lgd|bhoomi + code -> district/taluk/hobli/village names+codes
                              (this is your KGIS <-> Bhoomi code cross-walk)
  2  Nearby Admin Hierarchy    coords + distance + aoi=d|t|h -> district/taluk/hobli + survey numbers
  3  Survey Number             KGIS village code + coords + distance -> survey numbers + village name
  4  District Code             districtname -> districtName, districtCode
  5  Taluk Code                talukname -> district+taluk codes
  6  Hobli Code                hobliname -> district+taluk+hobli codes
  7  Geometric Polygon Area    KGIS VillageId + Survey Number -> geom (polygon, WKT)   <-- KEY
  8  Nearby Assets             coords + layer code + N -> assetName, x, y, distance, type
  9  Distance Between PIN Codes
 10  Election Jurisdiction Hierarchy
 11  Nearby Location Details   coords -> rural: survey number, village, hobli, taluk, district   <-- KEY
 12  Zonation Data (POST)      Gps_Lat/Gps_Lon (single or batch) -> full admin + electoral zonation
"""
import os, sys, json, time, csv
import requests

KGIS_BASE = os.environ.get("KGIS_BASE", "https://<REQUEST-FROM-KSRSAC>/kgisapi")
KGIS_AUTH = {
    "deptcode":  os.environ.get("KGIS_DEPTCODE", ""),
    "applncode": os.environ.get("KGIS_APPLNCODE", ""),
}


def _get(path, **params):
    p = dict(KGIS_AUTH); p.update(params)
    r = requests.get(f"{KGIS_BASE}/{path}", params=p, timeout=60)
    r.raise_for_status()
    return r.json()


def locate(lat, lon):
    """Service 11 — a field-staff GPS ping -> full rural hierarchy + survey number."""
    return _get("NearbyLocationDetails", coordinates=f"{lat},{lon}", type="DD", aoi="w")


def survey_polygon(village_id, survey_no):
    """Service 7 — survey number -> polygon geometry as WKT (use with shapely/GEE)."""
    return _get("GeometricPolygonArea", villageid=village_id, surveyno=survey_no, type="DD")


def survey_numbers_near(village_code, lat, lon, distance_m=250):
    """Service 3 — every survey number within N metres of a point."""
    return _get("SurveyNumber", code=village_code, coordinates=f"{lat},{lon}",
                distance=distance_m, type="DD")


def admin_hierarchy(code, code_type="bhoomi"):
    """Service 1 — cross-walk KGIS <-> LGD <-> Bhoomi village codes.
    Use this to join KGIS geometry to Bhoomi RTC attributes."""
    return _get("AdminHierarchy", type=code_type, code=code)


def zonation_batch(points):
    """Service 12 (POST) — batch a list of (lat, lon) tuples in one call."""
    payload = {"Gps_Lat": [p[0] for p in points], "Gps_Lon": [p[1] for p in points]}
    r = requests.post(f"{KGIS_BASE}/Zonation", json={**KGIS_AUTH, **payload}, timeout=120)
    r.raise_for_status()
    return r.json()


def enrich_csv(in_csv, out_csv, lat_col="lat", lon_col="lon", sleep=0.2):
    """Take a CSV of field-staff GPS points and append survey number + hierarchy.

    This is the workflow: field staff drop pins -> you resolve them to survey
    numbers -> you look those up in Bhoomi RTC (Khushki/Tari/Bagayat + Column 8)
    or score them with the satellite model.
    """
    rows = list(csv.DictReader(open(in_csv)))
    out = []
    for i, row in enumerate(rows, 1):
        try:
            j = locate(row[lat_col], row[lon_col])
            row.update({
                "kgis_district": j.get("KGISDistrictName") or j.get("districtName"),
                "kgis_taluk":    j.get("KGISTalukName")    or j.get("talukName"),
                "kgis_hobli":    j.get("KGISHobliName")    or j.get("hobliName"),
                "kgis_village":  j.get("villageName"),
                "survey_number": j.get("surveyNumber") or j.get("SurveyNumber"),
                "kgis_raw": json.dumps(j, ensure_ascii=False),
            })
        except Exception as e:
            row["kgis_raw"] = f"ERROR {e}"
        out.append(row)
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}", file=sys.stderr)
        time.sleep(sleep)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)
    print(f"wrote {out_csv}")


if __name__ == "__main__":
    if "<REQUEST-FROM-KSRSAC>" in KGIS_BASE:
        print(__doc__)
        print("\nSet KGIS_BASE, KGIS_DEPTCODE and KGIS_APPLNCODE once KSRSAC provisions you.")
        print("Request: kgissupport@ksrsac.in  |  Docs: https://kgis.ksrsac.in/kgis/webapi.aspx")
        sys.exit(0)
    if len(sys.argv) == 3:
        print(json.dumps(locate(sys.argv[1], sys.argv[2]), indent=2, ensure_ascii=False))
    elif len(sys.argv) == 4 and sys.argv[1] == "csv":
        enrich_csv(sys.argv[2], sys.argv[3])
    else:
        print("usage: 03_kgis_latlong_to_survey.py <lat> <lon>")
        print("       03_kgis_latlong_to_survey.py csv in.csv out.csv")
