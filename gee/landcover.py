"""Dynamic World land-cover statistics (probability-based).

Two things went wrong here at large radius and are fixed below.

1. ONE reduction, not eight. The old code ran a separate
   reduceRegion per class - eight round trips over the same pixels.
   At a 38 km radius that is ~4.5 billion m2 measured eight times,
   and Earth Engine gave up. A grouped reducer answers all eight
   classes in a single pass.

2. A failure must never be reported as zero. The old code wrapped
   each call in `except Exception: acres = 0`, so when Earth Engine
   failed the app printed "Total Area 0.00 ac" - which reads as a
   real measurement of empty land rather than "this did not run".
   Failures now raise, and the caller reports them.
"""

import ee

from gee.dynamic_world import dw_class_image

# 1 acre = 4046.8564224 square metres
SQM_PER_ACRE = 4046.8564224

CLASSES = {
    0: "Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded Vegetation",
    4: "Agriculture",
    5: "Shrub/Scrub",
    6: "Built-up",
    7: "Bare Ground",
}


def _scale_for(radius_km):
    """Reduction scale, coarsened for big circles.

    Derived from the radius the caller already knows - deliberately
    NOT from an extra buffer.area().getInfo() round trip. That call
    can itself fail, and its except-branch would have fallen back to
    the FINEST scale, which is precisely the wrong direction for the
    large circle that made it fail.
    """
    from core import compute as _cq
    base = _cq.stat_scale()
    try:
        r = float(radius_km or 0)
    except (TypeError, ValueError):
        r = 0
    if r <= 0 or r > 30:       # unknown radius is treated as large
        return max(base, 60)
    if r > 18:
        return max(base, 30)
    return max(base, 10)


def get_landcover(buffer, start_date, end_date, radius_km=None):
    """Area (acres) per Dynamic World class inside the buffer.

    Raises on Earth Engine failure - never returns zeros for it.
    """
    from core import compute as _cq

    dw = dw_class_image(buffer, start_date, end_date)
    scale = _scale_for(radius_km)

    # pixelArea grouped BY class: one pass, eight answers.
    grouped = (
        ee.Image.pixelArea().addBands(dw.rename("class"))
        .reduceRegion(
            reducer=ee.Reducer.sum().group(groupField=1,
                                           groupName="class"),
            geometry=buffer,
            scale=scale,
            maxPixels=1e13,
            bestEffort=True,
            tileScale=_cq.tile_scale(),
        )
    )

    groups = ee.List(grouped.get("groups")).getInfo() or []
    by_class = {}
    for g in groups:
        try:
            by_class[int(g["class"])] = float(g["sum"]) / SQM_PER_ACRE
        except (KeyError, TypeError, ValueError):
            continue

    return [{"Land Cover": name,
             "Area (acres)": round(by_class.get(value, 0.0), 2)}
            for value, name in CLASSES.items()]
