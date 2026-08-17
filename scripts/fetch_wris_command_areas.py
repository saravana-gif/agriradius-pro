"""Harvest India-WRIS canal command areas -> a map layer the app paints.

WHY THIS RUNS ON THE SERVER, NOT IN A BROWSER
India-WRIS publishes command areas through an ArcGIS REST service.
A browser can only show you one map image of it; the REST endpoint
returns the actual polygons, page by page, and needs to be paged and
filtered server-side. The app's Lightsail box has open internet, so it
does the harvest once and caches the result.

WHAT A COMMAND AREA IS WORTH
It is the area a canal actually serves - "ayakat". Inside a command
area, irrigated farmland is found for free: no satellite, no land
records. That only helps in canal-led districts (Raichur 77% canal,
Yadgir 52%, Mandya 47%); in Tumakuru or Chitradurga, where 99% of
irrigation is borewell, command areas are close to irrelevant. The
irrigation panel says which case you are in.

Run:
    python scripts/fetch_wris_command_areas.py            # Karnataka
    python scripts/fetch_wris_command_areas.py --discover # list layers

Safe to run repeatedly: it skips work when a good cache already exists,
and it never raises into the app - a failure just leaves the layer
unavailable with an explanation.
"""

import argparse
import json
import sys
from pathlib import Path

BASE = ("https://arc.indiawris.gov.in/server/rest/services/"
        "SubInfoSysLCC")

# Candidate services/layers, best first. WRIS renames things, so we try
# a few and keep whatever returns polygons.
CANDIDATES = [
    ("CommandArea", 0),
    ("CommandArea", 1),
    ("Command_Area", 0),
    ("Irrigation", 0),
]

# Karnataka bounding box (minx, miny, maxx, maxy).
KA_BBOX = "74.0,11.5,78.6,18.5"

OUT = (Path(__file__).resolve().parents[1] / "data" / "reference"
       / "wris_command_areas.geojson")

PAGE = 500
MIN_FEATURES = 1
TIMEOUT = 90


def _get(url, params):
    import requests
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def discover():
    """Print the layer tree so a human can pick the right one."""
    for service, _ in CANDIDATES:
        try:
            j = _get(f"{BASE}/{service}/MapServer/layers",
                     {"f": "pjson"})
        except Exception as e:
            print(f"{service}: unreachable ({e})", file=sys.stderr)
            continue
        print(f"\n{service}:")
        for lyr in j.get("layers", []):
            print(f"  [{lyr.get('id')}] {lyr.get('name')} "
                  f"geom={lyr.get('geometryType')}")


def fetch_layer(service, layer, bbox=KA_BBOX):
    """Page through one ArcGIS layer. Returns a list of GeoJSON feats."""
    url = f"{BASE}/{service}/MapServer/{layer}/query"
    feats, offset = [], 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true",
            "outSR": 4326,
            "resultOffset": offset,
            "resultRecordCount": PAGE,
            "geometry": bbox,
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        }
        j = _get(url, params)
        page = j.get("features") or []
        feats.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
        if offset > 20000:          # hard stop; never loop forever
            break
    return feats


def _simplify(feats, tol=0.001):
    """Shrink the polygons so the cache and the map stay light."""
    try:
        from shapely.geometry import mapping, shape
    except Exception:
        return feats
    out = []
    for f in feats:
        try:
            g = shape(f["geometry"]).buffer(0).simplify(
                tol, preserve_topology=True)
            if g.is_empty:
                continue
            f = dict(f)
            f["geometry"] = mapping(g)
            out.append(f)
        except Exception:
            continue
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--bbox", default=KA_BBOX)
    a = ap.parse_args(argv)

    if a.discover:
        discover()
        return 0

    if OUT.exists() and not a.force:
        try:
            existing = json.loads(OUT.read_text())
            if len(existing.get("features", [])) >= MIN_FEATURES:
                print(f"cache ok: {len(existing['features'])} "
                      f"command areas at {OUT}")
                return 0
        except Exception:
            pass

    for service, layer in CANDIDATES:
        try:
            print(f"trying {service}/{layer} ...", file=sys.stderr)
            feats = fetch_layer(service, layer, a.bbox)
        except Exception as e:
            print(f"  failed: {e}", file=sys.stderr)
            continue
        if len(feats) < MIN_FEATURES:
            print("  no features", file=sys.stderr)
            continue

        feats = _simplify(feats)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({
            "type": "FeatureCollection",
            "_source": f"India-WRIS {service}/{layer}",
            "features": feats,
        }))
        print(f"wrote {len(feats)} command areas -> {OUT}")
        return 0

    print("No India-WRIS command-area layer could be read. The service "
          "renames layers periodically - run with --discover from a "
          "machine with open internet to list what exists today.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
