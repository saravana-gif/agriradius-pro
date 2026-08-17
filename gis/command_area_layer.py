"""India-WRIS canal command areas - free irrigated-land targeting.

A command area ("ayakat") is the land a canal actually serves. Inside
one, irrigated farmland is located for nothing: no satellite compute,
no land records. That is only decisive in canal-led districts - Raichur
(77% canal), Yadgir (52%), Mandya (47%) - and close to useless in
Tumakuru or Chitradurga where ~99% of irrigation is borewell.

The polygons are harvested once by scripts/fetch_wris_command_areas.py
(the server has open internet; a browser can only ever show you a
picture of this service). Until that cache exists the layer reports
itself as unavailable rather than failing.
"""

import json
from functools import lru_cache

from config import PROJECT_ROOT

CACHE = PROJECT_ROOT / "data" / "reference" / "wris_command_areas.geojson"

FILL = "#1f78b4"

# Fields WRIS uses for the command-area name / project, best first.
_NAME_FIELDS = ("COMMAND_AREA", "CommandArea", "NAME", "Name",
                "PROJECT", "Project", "PROJECT_NAME", "SCHEME",
                "canal_name", "CANAL_NAME")
_AREA_FIELDS = ("AREA_HA", "Area_ha", "CCA", "CCA_HA", "GCA",
                "SHAPE_Area")


@lru_cache(maxsize=1)
def _load():
    if not CACHE.exists():
        return None
    try:
        gj = json.loads(CACHE.read_text())
        return gj if gj.get("features") else None
    except Exception:
        return None


def available():
    return _load() is not None


def source_note():
    gj = _load()
    if not gj:
        return ("Canal command areas have not been harvested yet. The "
                "server fetches them from the India-WRIS ArcGIS "
                "service - run scripts/fetch_wris_command_areas.py "
                "(one-off).")
    return (f"{len(gj['features']):,} command-area polygons from "
            f"{gj.get('_source', 'India-WRIS')}.")


def _label(props):
    for f in _NAME_FIELDS:
        v = props.get(f)
        if v:
            return str(v).title()
    return "Canal command area"


def _detail(props):
    bits = []
    for f in _AREA_FIELDS:
        v = props.get(f)
        if v:
            try:
                bits.append(f"{float(v):,.0f} ha commanded")
            except (TypeError, ValueError):
                pass
            break
    for f in ("STATE", "State", "DISTRICT", "District", "BASIN",
              "Basin"):
        v = props.get(f)
        if v:
            bits.append(str(v).title())
    bits.append("Inside a command area, canal-irrigated farmland can "
                "be targeted directly - no satellite work needed.")
    return "  |  ".join(bits)


def geojson_for(lat, lon, radius_km):
    """Command-area polygons clipped to the analysis circle."""
    gj = _load()
    if not gj:
        return None

    from shapely.geometry import mapping, shape

    from gis.shc_layer import _circle

    circle = _circle(lat, lon, radius_km)
    feats = []
    for f in gj["features"]:
        try:
            geom = shape(f["geometry"]).buffer(0)
            clipped = geom.intersection(circle)
            if clipped.is_empty:
                continue
        except Exception:
            continue
        props = f.get("properties") or {}
        feats.append({
            "type": "Feature",
            "geometry": mapping(clipped),
            "properties": {
                "district": _label(props),
                "val": _detail(props),
                "_fill": FILL,
            },
        })

    if not feats:
        return None
    return {"type": "FeatureCollection", "features": feats}
