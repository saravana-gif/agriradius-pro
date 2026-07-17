"""Load village boundary shapefiles (cached in memory)."""

import geopandas as gpd

from data.gis_data import get_layer

_CACHE = {}


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
        raise FileNotFoundError(f"Shapefile not found:\n{shp}")

    gdf = gpd.read_file(shp)

    if gdf.crs is None:
        raise ValueError(f"CRS not found in shapefile: {shp}")

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    gdf = gdf.rename(columns=str.lower)

    # Repair any invalid geometries
    gdf["geometry"] = gdf.geometry.buffer(0)

    _CACHE[key] = gdf

    return gdf
