from pathlib import Path
import geopandas as gpd

_BOUNDARIES = None


def load_boundaries():

    global _BOUNDARIES

    if _BOUNDARIES is not None:
        return _BOUNDARIES

    from data.gis_data import get_layer

shp = get_layer(
    "karnataka",
    "villages"
)

    if not shp.exists():
        raise FileNotFoundError(
            f"Village shapefile not found:\n{shp}"
        )

    gdf = gpd.read_file(shp)

    if gdf.crs is None:
        raise Exception("CRS not found in shapefile.")

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    gdf = gdf.rename(columns=str.lower)

    gdf["geometry"] = gdf.geometry.buffer(0)

    _BOUNDARIES = gdf

    return _BOUNDARIES