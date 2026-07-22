"""MapEngine - all folium rendering in one place.

The engine only draws; it never loads data or touches session state.
Callers fetch data (villages GeoDataFrame, tile URLs) and pass it in.
"""

import folium

from data.layer_registry import BASEMAPS


class MapEngine:

    def __init__(self, lat, lon, zoom=11, basemap="OpenStreetMap",
                 center=None):

        self.lat = lat
        self.lon = lon

        # Marker/buffer use lat/lon; the map VIEW can be centered
        # elsewhere (e.g. where the user last panned to).
        view = center if center else [lat, lon]

        base = BASEMAPS.get(basemap, BASEMAPS["OpenStreetMap"])

        if base["attr"] is None:
            self.map = folium.Map(
                location=view,
                zoom_start=zoom,
                tiles=base["tiles"],
                max_zoom=22,
            )
        else:
            self.map = folium.Map(
                location=view,
                zoom_start=zoom,
                tiles=None,
                max_zoom=22,
            )
            folium.TileLayer(
                tiles=base["tiles"],
                attr=base["attr"],
                name=basemap,
                max_zoom=22,
                max_native_zoom=20,
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

    def add_villages(self, gdf, name_col=None, popup_fields=None,
                     popup_aliases=None):
        """Draw village polygons with tooltip, popup and hover highlight.

        popup_fields/popup_aliases: parallel lists of attribute columns
        and display labels shown when a village is clicked. Fields not
        present in the GeoDataFrame are dropped automatically.
        """

        if gdf is None or gdf.empty:
            return self

        if name_col is None:
            name_col = next(
                (c for c in ("vilname11", "vilname", "name")
                 if c in gdf.columns),
                None
            )

        popup = None

        if popup_fields:

            pairs = [
                (f, a) for f, a in zip(
                    popup_fields,
                    popup_aliases or popup_fields
                )
                if f in gdf.columns
            ]

            if pairs:
                popup = folium.GeoJsonPopup(
                    fields=[p[0] for p in pairs],
                    aliases=[p[1] for p in pairs],
                )

        keep = {name_col} | set(popup_fields or [])
        cols = ["geometry"] + [c for c in keep if c and c in gdf.columns]

        folium.GeoJson(
            gdf[cols],
            name="Villages",
            style_function=lambda f: {
                "color": "#1f6feb",
                "weight": 1,
                "fillOpacity": 0.05,
            },
            highlight_function=lambda f: {
                "color": "#ff7800",
                "weight": 3,
                "fillOpacity": 0.15,
            },
            tooltip=folium.GeoJsonTooltip(fields=[name_col])
            if name_col else None,
            popup=popup,
        ).add_to(self.map)

        return self

    def add_tile_overlay(self, tile_url, name, attr="Google Earth Engine",
                         opacity=0.6):
        """Add a raster tile overlay (e.g. Dynamic World from EE).

        max_zoom=22 lets the user keep zooming; max_native_zoom=16
        stops Leaflet from requesting fresh deep-zoom tiles from Earth
        Engine (which load slowly/partially and can vanish at 100%
        zoom). Instead it upsamples the zoom-16 tiles it already has,
        so the overlay stays fully visible at every zoom - slightly
        softer at extreme zoom, but the 10 m data isn't sharper than
        that anyway.
        """

        folium.TileLayer(
            tiles=tile_url,
            attr=attr,
            name=name,
            overlay=True,
            opacity=opacity,
            max_zoom=22,
            min_zoom=1,
            max_native_zoom=16,
        ).add_to(self.map)

        return self

    def render(self):
        """Return the finished folium map."""
        return self.map