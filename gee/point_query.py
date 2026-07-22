"""Single-point analysis - details for one exact lat/long.

Unlike the radius mode (which summarises an area), this samples every
dataset at one location: which village it's in, land cover, soil,
soil temperature/moisture, elevation/slope, and - for a full report -
the crop-cycle and rainfall history at that spot.

Internally it uses a tiny (~100 m) buffer so Earth Engine reducers
have a pixel or two to work with, which is effectively point-level.
"""

import ee

POINT_RADIUS_KM = 0.1  # ~100 m sampling footprint

DW_CLASSES = {
    0: "Water", 1: "Trees", 2: "Grass", 3: "Flooded Vegetation",
    4: "Agriculture (crops)", 5: "Shrub/Scrub", 6: "Built-up",
    7: "Bare Ground", 8: "Snow/Ice",
}


def _elevation_slope(lat, lon):
    dem = ee.Image("USGS/SRTMGL1_003")
    slope = ee.Terrain.slope(dem)
    pt = ee.Geometry.Point([lon, lat])
    img = dem.rename("elev").addBands(slope.rename("slope"))
    v = img.reduceRegion(ee.Reducer.first(), pt, 30).getInfo()
    return v.get("elev"), v.get("slope")


def _land_cover_class(lat, lon, year):
    from gee.dynamic_world import dw_class_image
    pt = ee.Geometry.Point([lon, lat])
    buf = pt.buffer(POINT_RADIUS_KM * 1000)
    cls = dw_class_image(buf, f"{year}-01-01", f"{year}-12-31")
    v = cls.reduceRegion(ee.Reducer.mode(), buf, 10).getInfo()
    code = v.get("label")
    return DW_CLASSES.get(int(code), "Unknown") if code is not None \
        else "Unknown"


def point_core(lat, lon, year):
    """Fast point facts: village, land cover, soil, elevation/slope.

    Returns a dict. Used for single points and multi-point tables.
    """
    from gis.spatial import village_at_point
    from gee.soil import interpret, soil_profile, texture_class

    out = {"lat": round(lat, 6), "lon": round(lon, 6)}

    village = village_at_point(lat, lon)
    if village:
        out.update(village)
    else:
        out["Village"] = "(outside mapped boundaries)"

    try:
        out["Land Cover"] = _land_cover_class(lat, lon, year)
    except Exception:
        out["Land Cover"] = None

    try:
        soil = soil_profile(lat, lon, POINT_RADIUS_KM)
        out["Soil pH"] = soil.get("phh2o")
        out["Soil OC (g/kg)"] = soil.get("soc")
        out["Soil N (g/kg)"] = soil.get("nitrogen")
        out["Soil CEC"] = soil.get("cec")
        out["Soil Texture"] = texture_class(
            soil.get("sand"), soil.get("clay"))
        out["_soil_verdicts"] = interpret(soil)
    except Exception:
        pass

    try:
        elev, slope = _elevation_slope(lat, lon)
        out["Elevation (m)"] = round(elev, 1) if elev is not None else None
        out["Slope (deg)"] = round(slope, 1) if slope is not None else None
    except Exception:
        pass

    return out


def point_details(lat, lon, year):
    """Full point report: core facts + crop-cycle & rainfall history +
    soil temperature/moisture + 16-day forecast. Slower (several EE
    calls); button-triggered."""

    out = point_core(lat, lon, year)

    # Crop-cycle history
    try:
        from gee.ndvi import ndvi_monthly_series
        from core.crop_cycle import to_dataframe, analyze_series
        series = ndvi_monthly_series(
            lat, lon, POINT_RADIUS_KM, year - 1, year)
        df = to_dataframe(series)
        if not df["NDVI"].isna().all():
            ins = analyze_series(df)
            out["Cropping Pattern"] = ins["pattern"]
            out["Cycles/Year"] = ins["cycles_per_year"]
            out["_ndvi_series"] = series
    except Exception:
        pass

    # Rainfall history
    try:
        from gee.rainfall import rainfall_monthly
        from core.rain_insight import to_dataframe as rdf, analyze_rainfall
        rain = analyze_rainfall(rdf(
            rainfall_monthly(lat, lon, POINT_RADIUS_KM, year)))
        out["Rainfall Reliability"] = rain["verdict"]
        out["Avg Annual Rain (mm)"] = rain["mean_annual_mm"]
        out["_rain"] = rain
    except Exception:
        pass

    # Soil temperature / moisture
    try:
        from gee.climate import soil_climate, summarize
        sc = soil_climate(lat, lon, POINT_RADIUS_KM, year)
        s = summarize(sc)
        if s:
            out["Mean Soil Temp (C)"] = s["mean_temp"]
            out["Mean Soil Moisture (%)"] = s.get("mean_moisture")
    except Exception:
        pass

    return out
