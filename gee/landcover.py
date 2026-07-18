"""Dynamic World land-cover statistics (probability-based)."""

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


def get_landcover(buffer, start_date, end_date):
    """Compute area (acres) per Dynamic World class inside the buffer."""

    dw = dw_class_image(buffer, start_date, end_date)

    results = []

    for value, name in CLASSES.items():

        area = (
            ee.Image.pixelArea()
            .updateMask(dw.eq(value))
            .reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=buffer,
                scale=10,
                maxPixels=1e13,
            )
        )

        try:
            acres = ee.Number(area.get("area")).divide(SQM_PER_ACRE).getInfo()
        except Exception:
            acres = 0

        results.append({
            "Land Cover": name,
            "Area (acres)": round(acres or 0, 2),
        })

    return results