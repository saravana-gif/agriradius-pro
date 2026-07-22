"""GIS dataset registry.

Auto-discovers every state's village boundaries under boundaries/.
Drop a folder named "<state>_villages" containing a .shp (with its
.dbf/.shx/.prj siblings) or a .geojson, and it is registered
automatically - no code changes needed.

Example layout:
    boundaries/
        karnataka_villages/karnataka_villages.shp
        kerala_villages/kerala_villages.shp
        goa_villages/goa_villages.geojson
"""

from config import BOUNDARIES_DIR


def _find_layer_file(folder):
    """Return the first supported boundary file in a folder, else None.

    Supported: shapefile (.shp), GeoJSON (.geojson/.json), GeoPackage
    (.gpkg), and CSV-with-WKT (.csv / .csv.xz - e.g. the gggodhwani
    village dataset).
    """
    # Prefer compact formats (.gpkg) over raw shapefiles when both
    # exist, so a slimmed file (see tools/shrink_boundaries.py) wins.
    for ext in ("*.gpkg", "*.shp", "*.geojson", "*.json",
                "*.csv.xz", "*.csv"):
        hits = sorted(folder.glob(ext))
        if hits:
            return hits[0]
    return None


def _discover():
    """Scan boundaries/ for '<state>_villages' folders."""
    registry = {}

    if not BOUNDARIES_DIR.exists():
        return registry

    for folder in sorted(BOUNDARIES_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if not folder.name.endswith("_villages"):
            continue

        state = folder.name[: -len("_villages")].lower()
        path = _find_layer_file(folder)

        if path is not None:
            registry.setdefault(state, {})["villages"] = path

    return registry


GIS_DATA = _discover()


def get_layer(state, layer):
    """Return the Path for a registered layer.

    Raises KeyError with a helpful message if the state or layer
    is not registered.
    """
    try:
        return GIS_DATA[state][layer]
    except KeyError:
        raise KeyError(
            f"Layer not registered: state='{state}', layer='{layer}'. "
            f"Available: { {s: list(l) for s, l in GIS_DATA.items()} }"
        )
