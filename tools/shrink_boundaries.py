"""Optional: shrink village boundary files for faster deploys.

Not required - the current files are all under GitHub's limits. Run
this only if you add very large boundaries (e.g. full-resolution
Maharashtra) or want a lighter repo / quicker Streamlit Cloud deploys.

For each boundaries/<state>_villages/ folder it:
  1. reads the boundary layer,
  2. simplifies geometry slightly (~55 m; negligible for buffer
     intersection),
  3. keeps only the columns the app needs,
  4. writes a compact <state>_villages.gpkg alongside the original.

The app prefers the .gpkg automatically. After checking the result,
you can delete the original .shp/.dbf/.shx/.prj (or .csv.xz) to save
space.

Usage:
    python tools/shrink_boundaries.py
"""

import sys
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = ROOT / "boundaries"

# Simplify tolerance in degrees (~0.0005 deg is roughly 55 m)
TOLERANCE = 0.0005

# Columns the app uses (after normalization). Extra columns dropped.
KEEP = ["vilname11", "vilnam_soi", "village_name", "sdtname",
        "block_name", "dtname", "district_name", "stname",
        "state_name", "geometry"]


def main():
    if not BOUNDARIES.exists():
        print("No boundaries/ folder found.")
        return

    sys.path.insert(0, str(ROOT))
    from gis.boundary_loader import _read_csv_wkt  # noqa: E402

    for folder in sorted(BOUNDARIES.iterdir()):
        if not folder.is_dir() or not folder.name.endswith("_villages"):
            continue

        src = None
        for ext in ("*.shp", "*.geojson", "*.json", "*.csv.xz",
                    "*.csv"):
            hits = sorted(folder.glob(ext))
            if hits:
                src = hits[0]
                break

        if src is None:
            continue

        print(f"\n{folder.name}: reading {src.name} ...")

        if src.suffix in (".csv",) or src.name.endswith(".csv.xz"):
            gdf = _read_csv_wkt(src)
        else:
            gdf = gpd.read_file(src)

        if gdf.crs is None:
            gdf = gdf.set_crs(4326)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)

        before = len(gdf)
        gdf["geometry"] = gdf.geometry.simplify(
            TOLERANCE, preserve_topology=True)
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]

        keep = [c for c in gdf.columns
                if c.lower() in KEEP or c == "geometry"]
        gdf = gdf[keep]

        out = folder / f"{folder.name}.gpkg"
        gdf.to_file(out, driver="GPKG")

        mb = out.stat().st_size / 1e6
        print(f"  {before} villages -> {out.name}  ({mb:.1f} MB)")

    print("\nDone. The app now prefers the .gpkg files. Verify in the "
          "app, then optionally delete the original .shp/.csv files.")


if __name__ == "__main__":
    main()
