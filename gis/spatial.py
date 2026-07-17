"""Spatial queries across all registered states."""

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from data.gis_data import GIS_DATA
from gis.boundary_loader import load_boundaries


def _buffer_geometry(lat, lon, radius_km):
    """Build the buffer polygon in EPSG:4326."""

    point = gpd.GeoSeries(
        [Point(lon, lat)],
        crs="EPSG:4326"
    ).to_crs(3857)

    buffer = point.buffer(radius_km * 1000)

    return gpd.GeoDataFrame(
        geometry=buffer,
        crs="EPSG:3857"
    ).to_crs(4326)


def villages_in_buffer(lat, lon, radius_km):
    """Villages from every registered state that intersect the buffer."""

    buffer = _buffer_geometry(lat, lon, radius_km)
    geom = buffer.geometry.iloc[0]

    parts = []

    for state in GIS_DATA:

        if "villages" not in GIS_DATA[state]:
            continue

        try:
            gdf = load_boundaries(state, "villages")
        except FileNotFoundError:
            continue

        # Spatial index query, then exact intersection test
        idx = list(gdf.sindex.intersection(buffer.total_bounds))

        if not idx:
            continue

        candidates = gdf.iloc[idx]
        hits = candidates[candidates.intersects(geom)]

        if not hits.empty:
            parts.append(hits)

    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        crs="EPSG:4326"
    )