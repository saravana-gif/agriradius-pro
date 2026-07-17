import ee

CLASSES = {
    0: "Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded Vegetation",
    4: "Agriculture",
    5: "Shrub/Scrub",
    6: "Built-up",
    7: "Bare Ground"
}


def analyze_landcover(latitude, longitude, radius_km, year=2025):

    point = ee.Geometry.Point([longitude, latitude])
    buffer = point.buffer(radius_km * 1000)

    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    dw = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(buffer)
        .filterDate(start_date, end_date)
        .select("label")
        .mode()
    )

    results = []

    for value, name in CLASSES.items():

        area = (
            ee.Image.pixelArea()
            .updateMask(dw.eq(value))
            .reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=buffer,
                scale=10,
                maxPixels=1e13
            )
        )

        hectares = ee.Number(area.get("area")).divide(10000)

        try:
            hectares = hectares.getInfo()
        except Exception:
            hectares = 0

        results.append({
            "Land Cover": name,
            "Area (ha)": round(hectares, 2)
        })

    return results