"""Load village boundary files - memory-safe.

The old version read ENTIRE state shapefiles into a permanent
in-process cache. Karnataka + Tamil Nadu alone are ~120 MB on disk and
several hundred MB as GeoDataFrames, which blew straight through the
512 MB limit of the free hosting tier (Render kills the instance ->
users see "service unavailable").

This version:
  * reads only the features inside a bounding box (bbox) when one is
    given - a village search now loads a few MB, not a whole state;
  * pre-filters states by a static bounding box, so a search near
    Mysore never even opens the Maharashtra file;
  * keeps NO permanent whole-state cache. Callers that need repeat
    answers already sit behind st.cache_data.
"""

import geopandas as gpd

from data.gis_data import get_layer

# Approximate state extents (EPSG:4326, generous margins). Used to skip
# states whose file could not possibly contain the query area. States
# not listed are always checked (safe default for future additions).
STATE_BBOXES = {
    "karnataka": (73.9, 11.3, 78.7, 18.6),
    "tamilnadu": (76.0, 7.9, 80.5, 13.7),
    "kerala": (74.6, 8.0, 77.6, 12.9),
    "andhra_pradesh": (76.6, 12.4, 85.0, 19.3),
    "maharashtra": (72.4, 15.4, 81.1, 22.3),
}


def state_may_intersect(state, bounds):
    """Cheap prefilter: can this state's extent overlap the query
    bounds (minx, miny, maxx, maxy)? Unknown states -> True."""
    bb = STATE_BBOXES.get(state)
    if bb is None or bounds is None:
        return True
    minx, miny, maxx, maxy = bounds
    return not (maxx < bb[0] or minx > bb[2]
                or maxy < bb[1] or miny > bb[3])


# Map common column-name variants (across data sources) to the four
# fields the app uses. Keys are checked in order; first match wins.
COLUMN_ALIASES = {
    "vilname11": ["vilname11", "vilnam_soi", "village_name", "village",
                  "vil_name", "name", "vname", "villname", "nam"],
    "sdtname": ["sdtname", "block_name", "subdist", "sub_dist",
                "tehsil", "taluk", "taluka", "block", "mandal",
                "sdtname11"],
    "dtname": ["dtname", "district_name", "district", "dist_name",
               "distname", "dtname11", "dist"],
    "stname": ["stname", "state_name", "state", "st_nm",
               "stname11", "st_name"],
}

# Column names that hold WKT geometry in CSV datasets
WKT_COLUMNS = ["geometery_in_wkt", "geometry_in_wkt", "wkt",
               "geometry", "geom", "the_geom"]


def _read_csv_wkt(path):
    """Read a CSV (optionally .xz) whose geometry is a WKT column
    into a GeoDataFrame (e.g. the gggodhwani village dataset)."""

    import pandas as pd
    from shapely import wkt

    df = pd.read_csv(path)  # pandas infers .xz compression

    lower = {c.lower(): c for c in df.columns}

    # 1. Prefer a column by known name
    wkt_col = next((lower[c] for c in WKT_COLUMNS if c in lower), None)

    # 2. Otherwise detect by content: a column whose first value looks
    #    like WKT (starts with a geometry keyword).
    if wkt_col is None:
        keywords = ("POLYGON", "MULTIPOLYGON", "POINT",
                    "MULTIPOINT", "LINESTRING", "GEOMETRYCOLLECTION")
        for col in df.columns:
            sample = df[col].dropna().astype(str).head(1)
            if len(sample) and sample.iloc[0].lstrip().upper().startswith(
                    keywords):
                wkt_col = col
                break

    if wkt_col is None:
        raise ValueError(
            f"No WKT geometry column found in {path.name}. "
            f"Columns: {list(df.columns)}")

    def _parse(s):
        if not isinstance(s, str) or not s.strip():
            return None
        s = s.strip()
        # Strip an "SRID=4326;" prefix some exports add
        if s.upper().startswith("SRID="):
            s = s.split(";", 1)[-1]
        try:
            return wkt.loads(s)
        except Exception:
            return None  # skip malformed rows instead of aborting

    geom = df[wkt_col].apply(_parse)

    df = df.drop(columns=[wkt_col])

    gdf = gpd.GeoDataFrame(df, geometry=geom, crs=4326)

    good = gdf[~gdf.geometry.isna()].reset_index(drop=True)

    if good.empty:
        raise ValueError(
            f"Could not parse any geometry from {path.name} "
            f"(column '{wkt_col}'). The file's geometry format may "
            f"not be WKT.")

    return good


def _normalize_columns(gdf):
    """Ensure the app's standard columns exist by copying from the
    first matching source column. Non-destructive."""

    lower = {c.lower(): c for c in gdf.columns}

    for target, aliases in COLUMN_ALIASES.items():
        if target in gdf.columns:
            continue
        for alias in aliases:
            if alias in lower and lower[alias] != target:
                gdf[target] = gdf[lower[alias]]
                break

    return gdf


def _prune_columns(gdf):
    """Keep only the columns the app uses (plus geometry). The raw
    .dbf attribute tables carry dozens of unused columns that would
    otherwise sit in RAM."""
    keep = set()
    lower = {c.lower(): c for c in gdf.columns}
    for aliases in COLUMN_ALIASES.values():
        for a in aliases:
            if a in lower:
                keep.add(lower[a])
    keep.add(gdf.geometry.name)
    cols = [c for c in gdf.columns if c in keep]
    return gdf[cols]


def load_boundaries(state="karnataka", layer="villages", bbox=None):
    """Load a boundary layer as a GeoDataFrame in EPSG:4326.

    bbox: optional (minx, miny, maxx, maxy) in lon/lat. When given,
    only features intersecting the box are read - this is the
    memory-safe path and should be used for all query-sized work.
    A full-state read (bbox=None) is allowed but discouraged.
    """
    shp = get_layer(state, layer)

    if not shp.exists():
        raise FileNotFoundError(f"Boundary file not found:\n{shp}")

    name = shp.name.lower()

    if name.endswith(".csv") or name.endswith(".csv.xz"):
        # CSV-WKT cannot be windowed at read time; read then filter.
        gdf = _read_csv_wkt(shp)
        if bbox is not None:
            gdf = gdf.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
            gdf = gdf.reset_index(drop=True)
    else:
        # Shapefile / GeoPackage / GeoJSON: the reader itself windows
        # the file, so only matching features ever enter memory.
        if bbox is not None:
            gdf = gpd.read_file(shp, bbox=bbox)
        else:
            gdf = gpd.read_file(shp)

    if gdf.crs is None:
        # CSV-WKT village data from gggodhwani is WGS84 lat/lon
        gdf = gdf.set_crs(4326)

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    gdf = gdf.rename(columns=str.lower)

    gdf = _normalize_columns(gdf)

    gdf = _prune_columns(gdf)

    # Repair only invalid geometries (fast on the small windowed set)
    if len(gdf):
        invalid = ~gdf.geometry.is_valid
        if invalid.any():
            gdf.loc[invalid, "geometry"] = \
                gdf.loc[invalid, "geometry"].buffer(0)

    return gdf
