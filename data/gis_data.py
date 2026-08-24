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


# Known holes in the bundled boundary data.
#
# Tamil Nadu's village shapefile was committed TRUNCATED: the header
# declared 36,736,480 bytes, only 18,804,736 were ever stored, and
# the geometry for 8,644 of 18,159 villages went with the missing
# half. The attribute table survived, so the loss could be measured
# exactly rather than guessed - these 11 districts have NO village
# geometry at all.
#
# They are not a random slice. They are western Tamil Nadu, the belt
# that borders Karnataka, and they include Coimbatore and Tiruppur -
# the Pollachi coconut belt this app ships as its own sample area.
# So this hole sits directly under OneRoot's Tamil Nadu sourcing.
#
# Fix properly with:  python scripts/fetch_boundaries.py tamilnadu
# (needs internet, so it runs on the server, not in the sandbox.)
COVERAGE_GAPS = {
    "tamilnadu": {
        "missing_districts": [
            "Coimbatore", "Dharmapuri", "Dindigul", "Erode", "Karur",
            "Krishnagiri", "Namakkal", "The Nilgiris", "Tirupathur",
            "Tiruppur", "Vellore",
        ],
        "villages_missing": 8644,
        "villages_present": 9515,
        "why": ("the bundled shapefile was truncated in an earlier "
                "commit; the salvageable half is shipped as "
                "tamilnadu.csv.xz"),
        "fix": "python scripts/fetch_boundaries.py tamilnadu",
        # How the gap proves itself CLOSED. Once the fetcher writes
        # the full 18,159 villages the file lands near 7 MB, well
        # past the 3.6 MB salvaged half.
        "file": "tamilnadu_villages/tamilnadu.csv.xz",
        "fixed_above_bytes": 5_000_000,
    },
}


def coverage_gap(state):
    """The known hole in a state's boundary data, or None.

    Returns None once the data has actually been repaired. A warning
    that outlives the problem trains people to ignore warnings, so
    this retires itself on evidence rather than waiting for someone
    to remember to delete the entry.
    """
    gap = COVERAGE_GAPS.get(str(state).lower())
    if not gap:
        return None
    rel, floor = gap.get("file"), gap.get("fixed_above_bytes")
    if rel and floor:
        try:
            if (BOUNDARIES_DIR / rel).stat().st_size >= floor:
                return None          # repaired - stop warning
        except OSError:
            pass                     # missing file: keep warning
    return gap


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


def refresh():
    """Re-scan boundaries/ so files downloaded AFTER startup (see
    scripts/fetch_boundaries.py) register without a restart. Cheap -
    just a small directory scan."""
    GIS_DATA.update(_discover())


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
