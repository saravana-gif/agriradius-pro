"""Forest vs farmland-with-trees - so plantation figures stop counting
natural forest.

THE PROBLEM THIS FIXES
The plantation detector looks for tree canopy that stays green through
the dry season on flat ground. In Karnataka that description also fits
a Western Ghats evergreen patch, so plantation acreage in Malnad,
Kodagu and the coastal belt has been inflated by natural forest.

Worse, the official definition guarantees the confusion: the Forest
Survey of India counts any canopy over 10% across more than 1 ha as
"forest cover" irrespective of ownership or land use - so coffee under
shade trees, arecanut gardens, mango orchards and coastal coconut all
read as forest in ISFR, Hansen and WorldCover alike.

THE FIX
JRC Global Forest Cover 2020 (10 m) is the one free product that
DELIBERATELY EXCLUDES agricultural plantations and land under
agricultural or urban use. Subtracting it from the plantation
detection removes most of the false positives for free:

    plantation_net = plantation_detected AND NOT forest

Three further layers come with it:
  * forest subtypes - naturally regenerating / primary vs PLANTED
    forest (the EUDR reference pair, which matters if OneRoot ever
    ships coffee to the EU);
  * "farmland trees" - canopy that GFC2020 excludes, which in
    Karnataka is overwhelmingly arecanut, coconut, coffee, mango,
    cashew, rubber and eucalyptus woodlots. That layer IS the
    plantation opportunity;
  * canopy-height uniformity - orchards are planted on a grid, natural
    forest is not, so the local standard deviation of canopy height
    separates an areca garden from an evergreen patch even when their
    spectra are nearly identical.

HONEST LIMIT: no satellite product can tell you LEGAL forest status.
Ever. For that you need the Karnataka Forest Department's own records.
"""

import ee
import streamlit as st

from gee.tiles import TILE_TTL

SQM_PER_ACRE = 4046.86

FOREST_COLOR = "1b5e20"
FARM_TREE_COLOR = "ffa000"
PLANTED_FOREST_COLOR = "8d6e63"

# Canopy-height window for a crop tree, and the uniformity cut that
# separates a planted grid from multi-storey natural forest. Tune on
# Shivamogga/Sagara (areca), Kodagu (coffee), Tumakuru (coconut).
CH_MIN_M = 4
CH_MAX_M = 25
CH_STD_MAX = 2.5


def _buffer(lat, lon, radius_km):
    return ee.Geometry.Point([lon, lat]).buffer(radius_km * 1000)


def forest_mask():
    """JRC GFC2020 forest - agricultural plantations already excluded."""
    return ee.Image("JRC/GFC2020/V3").select("Map").eq(1)


def forest_subtypes():
    """(natural_forest, planted_forest) from the GFC2020 subtypes.

    1 = naturally regenerating, 10 = primary, 20 = planted forest.
    """
    sub = ee.Image("JRC/GFC2020_subtypes/V1")
    natural = sub.eq(1).Or(sub.eq(10))
    planted = sub.eq(20)
    return natural, planted


def natural_lands_mask():
    """WRI SBTN Natural Lands (30 m) - independent second opinion."""
    return (ee.Image("WRI/SBTN/naturalLands/v1_1/2020")
            .select("natural").eq(1))


def tree_cover_mask():
    """ESA WorldCover tree cover (class 10)."""
    return ee.Image("ESA/WorldCover/v200").select("Map").eq(10)


def farmland_trees_mask():
    """Canopy present, but NOT forest by GFC2020 - i.e. tree crops.

    This is the layer worth acting on: arecanut, coconut, coffee,
    mango, cashew, rubber, eucalyptus woodlots.
    """
    return tree_cover_mask().And(forest_mask().Not()).rename(
        "farmland_trees")


def canopy_uniformity():
    """(mean height, height std-dev) over a 30 m neighbourhood.

    Community-catalogue assets, so this is wrapped by the caller: a
    missing asset must never break the layer stack.
    """
    from gee.assets import META_CANOPY, asset_ok, missing_note
    if not asset_ok(META_CANOPY):
        raise RuntimeError(missing_note(
            META_CANOPY, "Canopy-height uniformity"))
    ch = ee.Image(META_CANOPY)
    k = ee.Kernel.square(radius=30, units="meters")
    mean = ch.reduceNeighborhood(ee.Reducer.mean(), k)
    std = ch.reduceNeighborhood(ee.Reducer.stdDev(), k)
    return mean, std


def plantation_like_mask():
    """Structurally uniform crop-height canopy - the orchard signature."""
    mean, std = canopy_uniformity()
    return (tree_cover_mask()
            .And(mean.gt(CH_MIN_M)).And(mean.lt(CH_MAX_M))
            .And(std.lt(CH_STD_MAX))
            .rename("plantation_like"))


def plantation_net_mask(buffer, year):
    """The app's plantation detection with natural forest REMOVED."""
    from gee.plantation import plantation_mask
    return (plantation_mask(buffer, year)
            .And(forest_mask().Not())
            .rename("plantation_net"))


# ------------------------------------------------------------------
# Tile layers
# ------------------------------------------------------------------

@st.cache_data(show_spinner="Loading forest cover (GFC2020)...",
               ttl=TILE_TTL)
def forest_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    natural, planted = forest_subtypes()
    combo = (natural.multiply(1).add(planted.multiply(2))
             .updateMask(forest_mask()))
    img = combo.selfMask().clip(buffer)
    mapid = img.getMapId({
        "min": 1, "max": 2,
        "palette": [FOREST_COLOR, PLANTED_FOREST_COLOR]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Finding farmland trees (not forest)...",
               ttl=TILE_TTL)
def farmland_trees_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    img = farmland_trees_mask().selfMask().clip(buffer)
    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", FARM_TREE_COLOR]})
    return mapid["tile_fetcher"].url_format


@st.cache_data(show_spinner="Removing forest from the plantation "
                            "layer...", ttl=TILE_TTL)
def plantation_net_tile_url(lat, lon, radius_km, year):
    buffer = _buffer(lat, lon, radius_km)
    img = plantation_net_mask(buffer, year).selfMask().clip(buffer)
    mapid = img.getMapId({"min": 0, "max": 1,
                          "palette": ["000000", "ffe000"]})
    return mapid["tile_fetcher"].url_format


# ------------------------------------------------------------------
# Statistics
# ------------------------------------------------------------------

def _acres(mask, buffer):
    from core import compute as _cq
    area = (ee.Image.pixelArea().updateMask(mask)
            .reduceRegion(reducer=ee.Reducer.sum(), geometry=buffer,
                          scale=_cq.stat_scale(), maxPixels=1e13,
                          bestEffort=True,
                          tileScale=_cq.tile_scale()).getInfo())
    return round((area.get("area") or 0) / SQM_PER_ACRE, 1)


@st.cache_data(show_spinner="Separating forest from plantations...",
               ttl=3600)
def forest_stats(lat, lon, radius_km, year):
    """Forest vs farmland-trees vs plantation, gross and net."""
    out = {"year": year}
    try:
        buffer = _buffer(lat, lon, radius_km)
    except Exception as e:
        out["error"] = f"Earth Engine unavailable ({e})"
        return out

    try:
        out["forest_ac"] = _acres(forest_mask(), buffer)
    except Exception:
        out["forest_ac"] = None

    try:
        natural, planted = forest_subtypes()
        f = forest_mask()
        out["natural_forest_ac"] = _acres(natural.And(f), buffer)
        out["planted_forest_ac"] = _acres(planted.And(f), buffer)
    except Exception:
        out["natural_forest_ac"] = None
        out["planted_forest_ac"] = None

    try:
        out["farmland_trees_ac"] = _acres(farmland_trees_mask(),
                                          buffer)
    except Exception:
        out["farmland_trees_ac"] = None

    try:
        from gee.plantation import plantation_mask
        gross = plantation_mask(buffer, year)
        out["plantation_gross_ac"] = _acres(gross, buffer)
        out["plantation_net_ac"] = _acres(
            gross.And(forest_mask().Not()), buffer)
        if out["plantation_gross_ac"]:
            removed = (out["plantation_gross_ac"]
                       - out["plantation_net_ac"])
            out["forest_removed_ac"] = round(removed, 1)
            out["forest_removed_pct"] = round(
                100 * removed / out["plantation_gross_ac"], 1)
    except Exception:
        out["plantation_gross_ac"] = None
        out["plantation_net_ac"] = None

    try:
        out["uniform_canopy_ac"] = _acres(plantation_like_mask(),
                                          buffer)
    except Exception:
        out["uniform_canopy_ac"] = None

    try:
        out["natural_lands_ac"] = _acres(natural_lands_mask(), buffer)
    except Exception:
        out["natural_lands_ac"] = None

    return out


def verdict(stats):
    """Plain English: how much of the 'plantation' was really forest."""
    if not stats:
        return None
    gross = stats.get("plantation_gross_ac")
    net = stats.get("plantation_net_ac")
    if gross is None or net is None:
        return None
    pct = stats.get("forest_removed_pct")
    if not gross:
        return ("No plantation canopy detected here, so there is "
                "nothing for the forest mask to correct.")
    if pct is None:
        return None
    if pct >= 40:
        head = ("Most of the raw plantation signal here was natural "
                "forest")
    elif pct >= 15:
        head = "A meaningful slice of it was natural forest"
    elif pct >= 3:
        head = "Only a little natural forest was mixed in"
    else:
        head = "Essentially no natural forest was mixed in"
    return (f"{head}: {gross:,.0f} ac of tree canopy detected, "
            f"{stats.get('forest_removed_ac', 0):,.0f} ac of it "
            f"({pct}%) is forest by JRC GFC2020, leaving "
            f"{net:,.0f} ac of genuine plantation / tree-crop land. "
            f"Legal forest status cannot be read from satellite - "
            f"only the Forest Department's records settle that.")
