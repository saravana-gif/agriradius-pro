"""Shared satellite feature engine.

Builds a rich multi-band feature image for a buffer/year, combining:
  - Sentinel-2 surface reflectance + red-edge vegetation indices
    (NDVI, NDRE, EVI, NDWI, red-edge chlorophyll index)
  - Annual phenology percentiles (p15/p50/p90 NDVI + amplitude)
  - Sentinel-1 radar backscatter (VV, VH) + canopy texture

Both the plantation detector (Lever 1) and the trained classifier
(Lever 3) build on this, so features stay consistent.
"""

import ee

from gee.ndvi import _mask_clouds

S2 = "COPERNICUS/S2_SR_HARMONIZED"
S1 = "COPERNICUS/S1_GRD"


def _s2_collection(buffer, year):
    return (
        ee.ImageCollection(S2)
        .filterBounds(buffer)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        .map(_mask_clouds)
    )


def _indices(img):
    """Add vegetation indices to one Sentinel-2 image.

    Bands: B2 blue, B3 green, B4 red, B5/B6/B7 red-edge, B8 NIR,
    B8A narrow-NIR, B11 SWIR1.
    """
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndre = img.normalizedDifference(["B8", "B5"]).rename("NDRE")
    ndwi = img.normalizedDifference(["B3", "B8"]).rename("NDWI")

    evi = img.expression(
        "2.5*((N-R)/(N+6*R-7.5*B+1))",
        {"N": img.select("B8").divide(10000),
         "R": img.select("B4").divide(10000),
         "B": img.select("B2").divide(10000)},
    ).rename("EVI")

    # Red-edge chlorophyll index: B7/B5 - 1
    cire = img.select("B7").divide(img.select("B5")).subtract(1) \
        .rename("CIre")

    # NDMI - canopy moisture (B8 NIR vs B11 SWIR1). Banana's thick
    # hydrated leaves hold more water than open coconut canopy.
    ndmi = img.normalizedDifference(["B8", "B11"]).rename("NDMI")
    # GNDVI - green chlorophyll.
    gndvi = img.normalizedDifference(["B8", "B3"]).rename("GNDVI")
    # NBR - canopy water/structure (B8 vs B12 SWIR2).
    nbr = img.normalizedDifference(["B8", "B12"]).rename("NBR")

    return ee.Image.cat([ndvi, ndre, ndwi, evi, cire, ndmi, gndvi, nbr])


def _monthly_s2(buffer, year):
    """Reduce ~70 raw scenes to 12 monthly median composites.

    Far fewer images for the downstream reducers, so layers render
    much faster, and monthly medians are less cloud-noisy than raw
    scenes. Empty months (fully cloudy) are dropped.
    """
    col = _s2_collection(buffer, year)
    bands = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A",
             "B11", "B12"]

    def monthly(m):
        m = ee.Number(m)
        start = ee.Date.fromYMD(year, m, 1)
        sub = col.filterDate(start, start.advance(1, "month"))
        return ee.Image(ee.Algorithms.If(
            sub.size().gt(0),
            sub.median().select(bands).set("empty", 0),
            ee.Image().set("empty", 1)))

    months = ee.List.sequence(1, 12).map(monthly)
    return (ee.ImageCollection.fromImages(months)
            .filterMetadata("empty", "equals", 0))


def s2_annual(buffer, year):
    """Median reflectance + median indices + NDVI phenology, computed
    over 12 monthly composites (fast) rather than every raw scene."""

    monthly = _monthly_s2(buffer, year)

    idx = monthly.map(_indices)

    median_idx = idx.median()

    ndvi = idx.select("NDVI")
    pct = ndvi.reduce(ee.Reducer.percentile([15, 50, 90]))
    amplitude = pct.select("NDVI_p90").subtract(
        pct.select("NDVI_p15")).rename("NDVI_amp")

    sr = monthly.median()

    return ee.Image.cat([sr, median_idx, pct, amplitude])


def s1_annual(buffer, year):
    """Sentinel-1 radar: median VV/VH + VH canopy texture.

    Palms and dense tree canopy scatter radar strongly and have high
    local texture; grass, bare soil and water are smooth (low
    texture). This keys on structure, not just greenness.
    """

    col = (
        ee.ImageCollection(S1)
        .filterBounds(buffer)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains(
            "transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains(
            "transmitterReceiverPolarisation", "VH"))
    )

    vv = col.select("VV").median().rename("VV")
    vh = col.select("VH").median().rename("VH")

    # Canopy texture: local standard deviation of VH (~50 m window)
    vh_texture = vh.reduceNeighborhood(
        reducer=ee.Reducer.stdDev(),
        kernel=ee.Kernel.circle(50, "meters"),
    ).rename("VH_texture")

    ratio = vv.subtract(vh).rename("VVVH_diff")

    # Temporal std-dev - harvest/replant cycles (banana) swing more
    # than a permanent palm canopy (coconut).
    vv_std = col.select("VV").reduce(ee.Reducer.stdDev()).rename("VV_std")
    vh_std = col.select("VH").reduce(ee.Reducer.stdDev()).rename("VH_std")

    return ee.Image.cat([vv, vh, vh_texture, ratio, vv_std, vh_std])


def terrain(buffer):
    """Elevation, slope and aspect - static context features."""
    dem = ee.Image("USGS/SRTMGL1_003")
    return ee.Image.cat([
        dem.rename("elevation"),
        ee.Terrain.slope(dem).rename("slope"),
        ee.Terrain.aspect(dem).rename("aspect"),
    ])


def dw_probs(buffer, year):
    """Dynamic World mean class probabilities - auxiliary features
    (woody 'trees' vs herbaceous 'crops' etc.), not the answer."""
    dw = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(buffer)
        .filterDate(f"{year}-01-01", f"{year}-12-31")
        .select(["trees", "crops", "grass", "shrub_and_scrub",
                 "built", "bare"])
        .mean()
    )
    return dw.rename(["DW_trees", "DW_crops", "DW_grass",
                      "DW_shrub", "DW_built", "DW_bare"])


def feature_stack(buffer, year):
    """Full feature image for a year: Sentinel-2 reflectance +
    vegetation/moisture indices + NDVI phenology, Sentinel-1 radar
    (backscatter, ratio, texture, temporal std), Dynamic World class
    probabilities, and terrain. Used by the plantation/banana/maize
    logic and the trained classifier."""
    return (s2_annual(buffer, year)
            .addBands(s1_annual(buffer, year))
            .addBands(dw_probs(buffer, year))
            .addBands(terrain(buffer)))
