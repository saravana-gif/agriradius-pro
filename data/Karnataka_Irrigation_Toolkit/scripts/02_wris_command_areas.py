#!/usr/bin/env python3
"""
Harvest India-WRIS canal command areas + canal networks for Karnataka as GeoJSON.

Why this matters for field targeting: land INSIDE a canal command area is
canal-irrigable. Irrigated land OUTSIDE a command area is, in Karnataka,
almost always groundwater (borewell). That single distinction covers most of
Raichur (77% canal), Yadgir (52%), Mandya (47%), Koppal (29%) and Davanagere (28%)
with no satellite work at all.

Endpoint verified live 17 Aug 2026: ArcGIS Server 10.81, no authentication.

    pip install requests
    python 02_wris_command_areas.py --discover
    python 02_wris_command_areas.py --service CommandArea --layer 0 --state Karnataka
"""
import argparse, json, sys, time
import requests

BASE = "https://arc.indiawris.gov.in/server/rest/services/SubInfoSysLCC"

# Services enumerated live from .../SubInfoSysLCC?f=pjson on 17 Aug 2026
SERVICES = [
    "Agro_Regions", "AquiferLitholog", "AquiferSystems", "Coastal_Data",
    "CommandArea",            # <- canal command area polygons
    "District_Infosys", "Glacial_Support",
    "GWP",                    # <- groundwater prospects
    "InlandNavigation", "InterBasinTransferLink", "LandDegradation",
    "Litholog_Analysis_Depth_Thickness_Material",
    "MinorIrrigation",        # <- dugwell / tubewell / surface scheme metrics
    "Reservoir_Survey2021", "River_StreamOrder", "Socioeconomic", "Soil",
    "Wasteland",
    "WaterBodies",            # <- tanks
    "WaterResourceProject", "Wetlands",
]

# Karnataka bounding box (WGS84) — used when no attribute state field exists
KA_BBOX = "74.0,11.5,78.6,18.5"


def discover(service=None):
    """Print the layer tree and field names so you can pick the right WHERE clause."""
    targets = [service] if service else SERVICES
    for s in targets:
        try:
            r = requests.get(f"{BASE}/{s}/MapServer/layers", params={"f": "pjson"}, timeout=90)
            j = r.json()
        except Exception as e:
            print(f"{s}: unreachable ({e})", file=sys.stderr); continue
        print(f"\n=== {s} ===")
        for lyr in j.get("layers", []):
            fields = [f["name"] for f in lyr.get("fields", [])]
            print(f"  [{lyr['id']}] {lyr['name']}  geom={lyr.get('geometryType')}")
            print(f"      fields: {', '.join(fields[:30])}")
        time.sleep(0.5)


def fetch(service, layer, where="1=1", bbox=None, out="out.geojson", page=500):
    """Page through an ArcGIS layer and write a single GeoJSON FeatureCollection."""
    url = f"{BASE}/{service}/MapServer/{layer}/query"
    feats, offset = [], 0
    while True:
        params = {
            "where": where, "outFields": "*", "f": "geojson",
            "returnGeometry": "true", "outSR": 4326,
            "resultOffset": offset, "resultRecordCount": page,
        }
        if bbox:
            params.update({"geometry": bbox, "geometryType": "esriGeometryEnvelope",
                           "inSR": 4326, "spatialRel": "esriSpatialRelIntersects"})
        r = requests.get(url, params=params, timeout=180)
        r.raise_for_status()
        j = r.json()
        batch = j.get("features", [])
        feats += batch
        print(f"  {service}/{layer}: {len(feats)} features", file=sys.stderr)
        if len(batch) < page:
            break
        offset += page
        time.sleep(0.3)
    with open(out, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f)
    print(f"wrote {out} ({len(feats)} features)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--service", default="CommandArea")
    ap.add_argument("--layer", type=int, default=0)
    ap.add_argument("--state", default=None, help="tries WHERE STATE='<name>'; falls back to bbox")
    ap.add_argument("--bbox", default=KA_BBOX)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.discover:
        discover(None if a.service == "ALL" else a.service)
        sys.exit(0)

    where = f"UPPER(STATE)='{a.state.upper()}'" if a.state else "1=1"
    out = a.out or f"wris_{a.service}_{a.layer}.geojson"
    try:
        fetch(a.service, a.layer, where=where, out=out)
    except Exception as e:
        print(f"attribute filter failed ({e}); retrying with bbox", file=sys.stderr)
        fetch(a.service, a.layer, where="1=1", bbox=a.bbox, out=out)

# ---------------------------------------------------------------------------
# QGIS alternative (often easier):
#   Browser panel -> ArcGIS REST Servers -> New Connection
#   URL: https://arc.indiawris.gov.in/server/rest/services
#   Prefer MapServer entries. Then right-click layer -> Export -> Save as GeoJSON.
#
# CLI alternative:
#   pip install esri2geojson
#   esri2geojson https://arc.indiawris.gov.in/server/rest/services/SubInfoSysLCC/CommandArea/MapServer/0 command.geojson
#
# OGC WMS (for a basemap rather than data):
#   https://arc.indiawris.gov.in/server/rest/services/SubInfoSysLCC/CommandArea/MapServer/WMSServer?request=GetCapabilities
# ---------------------------------------------------------------------------
