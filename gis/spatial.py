"""Spatial queries across all registered states - memory-safe.

Every query passes a bounding box to the loader, so only the villages
near the query area are ever read into memory (see boundary_loader).
"""

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from data.gis_data import GIS_DATA
from gis.boundary_loader import load_boundaries, state_may_intersect


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
    """Villages from every registered state that intersect the buffer.

    Only reads features inside the buffer's bounding box, and skips
    states whose extent cannot overlap it at all.
    """

    from data import gis_data as _gd
    _gd.refresh()   # pick up boundary files fetched after startup

    buffer = _buffer_geometry(lat, lon, radius_km)
    geom = buffer.geometry.iloc[0]
    bounds = tuple(buffer.total_bounds)  # (minx, miny, maxx, maxy)

    parts = []

    for state in GIS_DATA:

        if "villages" not in GIS_DATA[state]:
            continue

        if not state_may_intersect(state, bounds):
            continue

        try:
            gdf = load_boundaries(state, "villages", bbox=bounds)
        except FileNotFoundError:
            continue

        if gdf.empty:
            continue

        hits = gdf[gdf.intersects(geom)]

        if not hits.empty:
            parts.append(hits)

    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    return gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        crs="EPSG:4326"
    )


def village_at_point(lat, lon):
    """Return the village whose polygon contains the point.

    Returns a dict of Village/Taluk/District/State (values that exist)
    or None if the point falls outside all registered boundaries.
    """

    pt = Point(lon, lat)

    # A tiny window around the point is all we need to read.
    pad = 0.02  # ~2 km
    bounds = (lon - pad, lat - pad, lon + pad, lat + pad)

    for state in GIS_DATA:

        if "villages" not in GIS_DATA[state]:
            continue

        if not state_may_intersect(state, bounds):
            continue

        try:
            gdf = load_boundaries(state, "villages", bbox=bounds)
        except FileNotFoundError:
            continue

        if gdf.empty:
            continue

        hit = gdf[gdf.contains(pt)]

        if not hit.empty:
            row = hit.iloc[0]
            fields = {
                "Village": "vilname11",
                "Taluk": "sdtname",
                "District": "dtname",
                "State": "stname",
            }
            return {
                label: str(row[col])
                for label, col in fields.items()
                if col in hit.columns and row[col] is not None
            }

    return None
