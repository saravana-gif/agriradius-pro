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
WORLDCOVER = "ESA/WorldCover/v200"
WORLDCOVER_CROPLAND = 40


@lru_cache(maxsize=64)
def asset_ok(asset_id):
    """True if this project can actually read the asset."""
    try:
        import ee
        ee.data.getAsset(asset_id)
        return True
    except Exception:
        return False


def missing_note(asset_id, what):
    """One line explaining a skipped layer, for the UI to show."""
    return (f"{what} needs the Earth Engine asset `{asset_id}`, which "
            f"this project cannot read. It is a community-catalogue "
            f"dataset, not part of the official Earth Engine "
            f"catalogue - the other irrigation layers do not depend on "
            f"it.")
