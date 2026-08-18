"""Check an Earth Engine asset exists BEFORE building a layer on it.

Earth Engine is lazy: `ee.Image("projects/sat-io/...")` succeeds even
when the asset is missing or not readable by this service account, and
the error only appears when a tile or a statistic is finally requested.
A try/except around the construction therefore catches nothing, and the
layer surfaces as a bare "(unavailable)" with no explanation - which is
exactly what happened to the irrigation layers built on the community
(`sat-io`) catalogue.

`asset_ok()` asks Earth Engine for the asset's metadata once per
process, which is cheap and eager, so a layer can decide up front
whether to draw, degrade, or explain itself.
"""

from functools import lru_cache

# Community-catalogue assets the app would like to use. Not part of the
# official Earth Engine catalogue, so availability depends on the
# awesome-gee-community-catalogue project and on this account's access.
GCI30 = "projects/sat-io/open-datasets/GCI30"
LGRIP30 = "projects/sat-io/open-datasets/GFSAD/LGRIP30"
GCEP30 = "projects/sat-io/open-datasets/GFSAD/GCEP30"
META_CANOPY = ("projects/sat-io/open-datasets/facebook/"
               "meta-canopy-height")

# Official-catalogue equivalents that are always available.
# NOTE WorldCover is published as an ImageCollection (one image per
# year), NOT as an Image - see worldcover() below.
WORLDCOVER = "ESA/WorldCover/v200"
WORLDCOVER_CROPLAND = 40


def worldcover():
    """ESA WorldCover as a single image.

    `ee.Image("ESA/WorldCover/v200")` looks correct and is not: the
    official snippet is
    `ee.ImageCollection("ESA/WorldCover/v200").first()`. Earth Engine
    accepts the wrong wrapper silently and only fails when a tile or a
    statistic is requested, which took down every irrigation layer
    built on the cropland mask.
    """
    import ee
    return ee.ImageCollection(WORLDCOVER).first()


@lru_cache(maxsize=64)
def asset_type(asset_id):
    """"IMAGE", "IMAGE_COLLECTION", ... or "" when unreadable.

    One eager metadata call per asset per process.
    """
    try:
        import ee
        return ee.data.getAsset(asset_id).get("type", "") or ""
    except Exception:
        return ""


def asset_ok(asset_id):
    """True if this project can actually read the asset."""
    return asset_type(asset_id) != ""


def community_image(asset_id):
    """A single ee.Image for a community asset, whatever its type.

    These datasets are almost all published as tiled ImageCollections
    covering the globe, not as one Image - LGRIP30, GCI30, GCEP30 and
    the Meta canopy-height maps all are. Wrapping a collection id in
    `ee.Image(...)` builds an object that looks fine and only fails at
    tile time, which is exactly how six irrigation layers came to
    report "(unavailable)" with no explanation. Mosaic collections;
    pass images straight through.
    """
    import ee
    kind = asset_type(asset_id)
    if kind == "IMAGE_COLLECTION":
        return ee.ImageCollection(asset_id).mosaic()
    if kind == "IMAGE":
        return ee.Image(asset_id)
    raise RuntimeError(missing_note(asset_id, "This layer"))


def missing_note(asset_id, what):
    """One line explaining a skipped layer, for the UI to show."""
    return (f"{what} needs the Earth Engine asset `{asset_id}`, which "
            f"this project cannot read right now. It is a "
            f"community-catalogue dataset, not part of the official "
            f"Earth Engine catalogue - the other layers do not depend "
            f"on it.")
