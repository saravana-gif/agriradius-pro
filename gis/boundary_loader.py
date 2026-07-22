"""Load village boundary shapefiles (cached in memory)."""

import geopandas as gpd

from data.gis_data import get_layer

_CACHE = {}

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


def load_boundaries(state="karnataka", layer="villages"):
    """Load a boundary layer as a GeoDataFrame in EPSG:4326.

    Results are cached per (state, layer) so shapefiles are only
    read from disk once per session.
    """
    key = (state, layer)

    if key in _CACHE:
        return _CACHE[key]

    shp = get_layer(state, layer)

    if not shp.exists():
        raise FileNotFoundError(f"Boundary file not found:\n{shp}")

    name = shp.name.lower()

    if name.endswith(".csv") or name.endswith(".csv.xz"):
        gdf = _read_csv_wkt(shp)
    else:
        gdf = gpd.read_file(shp)

    if gdf.crs is None:
        # CSV-WKT village data from gggodhwani is WGS84 lat/lon
        gdf = gdf.set_crs(4326)

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    gdf = gdf.rename(columns=str.lower)

    gdf = _normalize_columns(gdf)

    # Repair only invalid geometries (much faster on large files)
    invalid = ~gdf.geometry.is_valid
    if invalid.any():
        gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

    _CACHE[key] = gdf

    return gdf