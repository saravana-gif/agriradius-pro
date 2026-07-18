"""Layer registry - single source of truth for all map layers.

The Layer Manager UI and the map renderer both build themselves from
this configuration. To add a new layer, register it here; never
hardcode layer lists in the UI.
"""

# --- Basemaps ---
# "attr" of None means folium's built-in tile set.
BASEMAPS = {
    "OpenStreetMap": {
        "tiles": "OpenStreetMap",
        "attr": None,
    },
    "Satellite": {
        "tiles": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "attr": "Google Satellite",
    },
    "Terrain": {
        "tiles": "https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
        "attr": "Google Terrain",
    },
}

# --- Overlay layers, grouped by category ---
# id      : unique key used in session state and by the renderer
# label   : text shown in the Layer Manager
# default : visible on first load?
LAYERS = {
    "Analysis": [
        {"id": "marker", "label": "Location Marker", "default": True},
        {"id": "buffer", "label": "Buffer Zone", "default": True},
        {"id": "dynamic_world", "label": "Dynamic World Land Cover", "default": False},
        {"id": "cropland_confidence", "label": "Cropland Confidence","default": False},
    ],
    "Administrative": [
        {"id": "villages", "label": "Villages (in buffer)", "default": False},
    ],
}


def default_visibility():
    """Return {layer_id: default_visible} for every registered layer."""
    return {
        layer["id"]: layer["default"]
        for layers in LAYERS.values()
        for layer in layers
    }


def all_layer_ids():
    """Return every registered layer id."""
    return list(default_visibility().keys())