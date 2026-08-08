"""Build the SHC district-choropleth geometry locally.

Dissolves the bundled village boundaries (Karnataka + Tamil Nadu) into
district polygons, simplifies them heavily (choropleth display only),
and writes a compact gzip+base64 GeoJSON to

    data/reference/shc_districts_local.geojson.gz.b64   (gitignored)

gis/shc_layer.py prefers this locally-built file over any bundled
copy. Run once per machine (needs geopandas, ~1 min):

    python scripts/build_shc_districts.py
"""

import base64
import gzip
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reference" / "shc_districts_local.geojson.gz.b64"

SOURCES = [
    (ROOT / "boundaries" / "karnataka_villages" / "karnataka_villages.shp",
     "KARNATAKA"),
    (ROOT / "boundaries" / "tamilnadu_villages" / "tamilnadu_villages.shp",
     "TAMIL NADU"),
]


def main():
    import geopandas as gpd
    import pandas as pd

    parts = []
    for shp, state in SOURCES:
        print(f"reading + dissolving {state} ...", flush=True)
        g = gpd.read_file(shp, columns=["dtname", "geometry"])
        g = g[g.geometry.notna()]
        g["geometry"] = g.geometry.buffer(0)
        d = g.dissolve(by="dtname", as_index=False)
        del g
        d["state"] = state
        parts.append(d[["state", "dtname", "geometry"]])
        print(f"  {len(d)} districts", flush=True)

    dd = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True),
                          crs=parts[0].crs)
    dd["geometry"] = dd.geometry.simplify(
        0.025, preserve_topology=True).buffer(0)

    gj = json.loads(dd.to_json())

    def rnd(c):
        if isinstance(c, (int, float)):
            return round(c, 3)
        return [rnd(x) for x in c]

    for f in gj["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
        p = f["properties"]
        f["properties"] = {"state": p["state"],
                           "district": p.get("district") or p.get("dtname")}

    raw = json.dumps(gj, separators=(",", ":")).encode()
    b64 = base64.b64encode(gzip.compress(raw, 9)).decode()
    OUT.write_text("\n".join(textwrap.wrap(b64, 120)) + "\n")

    # self-verify
    txt = OUT.read_text().replace("\n", "").strip()
    check = json.loads(gzip.decompress(base64.b64decode(txt)))
    print(f"OK: {OUT.name} written, {len(check['features'])} districts, "
          f"{OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
