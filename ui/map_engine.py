"""MapEngine - all folium rendering in one place.

The engine only draws; it never loads data or touches session state.
Callers fetch data (villages GeoDataFrame, tile URLs) and pass it in.
"""

import folium

from data.layer_registry import BASEMAPS


class MapEngine:

    def __init__(self, lat, lon, zoom=11, basemap="OpenStreetMap"):

        self.lat = lat
        self.lon = lon

        base = BASEMAPS.get(basemap, BASEMAPS["OpenStreetMap"])

        if base["attr"] is None:
            self.map = folium.Map(
                location=[lat, lon],
                zoom_start=zoom,
                tiles=base["tiles"]
            )
        else:
            self.map = folium.Map(
                location=[lat, lon],
                zoom_start=zoom,
                tiles=None
            )
            folium.TileLayer(
                tiles=base["tiles"],
                attr=base["attr"],
                name=basemap
            ).add_to(self.map)

    def add_marker(self, tooltip="Selected Location"):

        folium.Marker(
            [self.lat, self.lon],
            tooltip=tooltip
        ).add_to(self.map)

        return self

    def add_buffer(self, radius_km, color="green", fill_opacity=0.2):

        folium.Circle(
            location=[self.lat, self.lon],
            radius=radius_km * 1000,
            color=color,
            fill=True,
            fill_opacity=fill_opacity
        ).add_to(self.map)

        return self

    def add_villages(self, gdf, name_col=None):
        """Draw village polygons from a GeoDataFrame (EPSG:4326)."""

        if gdf is None or gdf.empty:
            return self

        if name_col is None:
            name_col = next(
                (c for c in ("vilname11", "vilname", "name")
                 if c in gdf.columns),
                None
            )

        cols = ["geometry"] + ([name_col] if name_col else [])

        folium.GeoJson(
            gdf[cols],
            name="Villages",
            style_function=lambda f: {
                "color": "#1f6feb",
                "weight": 1,
                "fillOpacity": 0.05,
            },
            tooltip=folium.GeoJsonTooltip(fields=[name_col])
            if name_col else None,
        ).add_to(self.map)

        return self

    def add_tile_overlay(self, tile_url, name, attr="Google Earth Engine",
                         opacity=0.6):
        """Add a raster tile overlay (e.g. Dynamic World from EE)."""

        folium.TileLayer(
            tiles=tile_url,
            attr=attr,
            name=name,
            overlay=True,
            opacity=opacity
        ).add_to(self.map)

        return self

    def render(self):
        """Return the finished folium map."""
        return self.map