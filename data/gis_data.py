"""GIS dataset registry.

Single source of truth for every boundary dataset on disk.
Add new states/layers here only - never hardcode shapefile paths
anywhere else in the application.
"""

from config import BOUNDARIES_DIR

GIS_DATA = {
    "karnataka": {
        "villages": BOUNDARIES_DIR / "karnataka_villages" / "karnataka_villages.shp",
    },
    "tamilnadu": {
        "villages": BOUNDARIES_DIR / "tamilnadu_villages" / "tamilnadu_villages.shp",
    },
}


def get_layer(state, layer):
    """Return the Path for a registered layer.

    Raises KeyError with a helpful message if the state or layer
    is not registered.
    """
    try:
        return GIS_DATA[state][layer]
    except KeyError:
        raise KeyError(
            f"Layer not registered: state='{state}', layer='{layer}'. "
            f"Available: { {s: list(l) for s, l in GIS_DATA.items()} }"
        )
