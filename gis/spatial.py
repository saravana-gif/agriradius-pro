import geopandas as gpd
from shapely.geometry import Point

from gis.boundary_loader import load_boundaries


def villages_in_buffer(lat, lon, radius_km):

    gdf = load_boundaries()

    point = gpd.GeoSeries(
        [Point(lon, lat)],
        crs="EPSG:4326"
    ).to_crs(3857)

    buffer = point.buffer(radius_km * 1000)

    buffer = gpd.GeoDataFrame(
        geometry=buffer,
        crs="EPSG:3857"
    ).to_crs(4326)

    # Spatial index query
    candidate_idx = list(gdf.sindex.intersection(buffer.total_bounds))
    candidates = gdf.iloc[candidate_idx]

    # Exact intersection test
    result = candidates[candidates.intersects(buffer.geometry.iloc[0])]

    return result.reset_index(drop=True)