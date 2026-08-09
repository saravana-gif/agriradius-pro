"""MapEngine - all folium rendering in one place.

The engine only draws; it never loads data or touches session state.
Callers fetch data (villages GeoDataFrame, tile URLs) and pass it in.
"""

import folium
from branca.element import MacroElement
from jinja2 import Template

from data.layer_registry import BASEMAPS


class _ZoomAdaptiveStroke(MacroElement):
    """Scale the buffer-circle stroke with zoom so it never looks
    clumsy: thin when zoomed out, bolder as you zoom in."""
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function(){
            var map = {{ this._parent.get_name() }};
            function upd(){
                var z = map.getZoom();
                var w = Math.max(0.8, Math.min(4.5,
                                 0.6 + (z - 8) * 0.35));
                map.eachLayer(function(l){
                    if (l instanceof L.Circle){
                        l.setStyle({weight: w});
                    }
                });
            }
            map.on('zoomend', upd);
            map.whenReady(upd);
        })();
        {% endmacro %}""")


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

        self.map.add_child(_ZoomAdaptiveStroke())

    def fit_bounds(self, minx, miny, maxx, maxy):
        """Zoom the view to a bounding box (lon/lat)."""
        self.map.fit_bounds([[miny, minx], [maxy, maxx]])
        return self

    def add_points(self, points):
        """Numbered markers for a list of (lat, lon)."""
        for i, (lat, lon) in enumerate(points, 1):
            folium.Marker(
                [lat, lon],
                tooltip=f"Point {i}: {lat:.4f}, {lon:.4f}",
                icon=folium.Icon(color="green" if i == 1 else "blue"),
            ).add_to(self.map)
        return self

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

    def add_choropleth(self, geojson, name, fill_opacity=0.55):
        """District choropleth from a GeoJSON dict whose feature
        properties carry a precomputed `_fill` colour plus `district`
        and `val` for the tooltip."""

        if not geojson:
            return self

        folium.GeoJson(
            geojson,
            name=name,
            style_function=lambda f: {
                "fillColor": f["properties"].get("_fill", "#bdbdbd"),
                "color": "#666",
                "weight": 1,
                "fillOpacity": fill_opacity,
            },
            highlight_function=lambda f: {
                "color": "#222",
                "weight": 2.5,
                "fillOpacity": min(0.85, fill_opacity + 0.2),
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["district", "val"],
                aliases=["Village / District", name],
                sticky=True,
                # Fixed-width wrapping box: leaflet tooltips default
                # to a single nowrap line that runs off the screen,
                # and max-width alone collapses near the map edge.
                # min() keeps it inside small phone screens.
                style=("width: min(300px, 72vw); white-space: normal; "
                       "font-size: 12px; "
                       "line-height: 1.45; padding: 6px 9px;"),
            ),
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
