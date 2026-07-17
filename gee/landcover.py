import ee

classes = {
    0: "Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded Vegetation",
    4: "Agriculture",
    5: "Shrub/Scrub",
    6: "Built-up",
    7: "Bare Ground"
}

def get_landcover(buffer, start_date, end_date):

    dw = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(buffer)
        .filterDate(start_date, end_date)
        .select("label")
        .mode()
    )

    results = []

    for value, name in classes.items():

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

        hectares = ee.Number(area.get("area")).divide(10000).getInfo()

        results.append({
            "Land Cover": name,
            "Area (ha)": hectares
        })

    return results