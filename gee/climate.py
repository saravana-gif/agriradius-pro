"""Soil temperature and moisture from ERA5-Land (~11 km).

Monthly soil temperature (0-7 cm) and volumetric soil moisture for
the selected year. Note: groundwater DEPTH (water table) cannot be
measured from satellite or any public API - collect borewell water
levels through the field team (soil card form).
"""

import ee
import streamlit as st

DATASET = "ECMWF/ERA5_LAND/MONTHLY_AGGR"

BANDS = {
    "soil_temperature_level_1": "temp_k",
    "volumetric_soil_water_layer_1": "moisture",
}


@st.cache_data(show_spinner="Fetching soil temperature & moisture...")
def soil_climate(lat, lon, radius_km, year):
    """Return [{month, soil_temp_c, moisture_pct}, ...] for the year."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    col = (
        ee.ImageCollection(DATASET)
        .filterDate(f"{year}-01-01", f"{year + 1}-01-01")
        .select(list(BANDS.keys()))
    )

    images = []
    months = []

    for m in range(1, 13):

        start = ee.Date.fromYMD(year, m, 1)

        img = col.filterDate(start, start.advance(1, "month")).first()

        band_t = f"t{m:02d}"
        band_w = f"w{m:02d}"

        img = ee.Image(ee.Algorithms.If(
            img,
            ee.Image(img).rename([band_t, band_w]),
            ee.Image.constant([0, 0])
            .updateMask(ee.Image.constant(0))
            .rename([band_t, band_w]),
        ))

        months.append((band_t, band_w, f"{year}-{m:02d}"))
        images.append(img)

    stats = ee.Image.cat(images).reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=buffer,
        scale=11132,
        maxPixels=1e13,
        bestEffort=True,
    ).getInfo()

    series = []

    for band_t, band_w, label in months:

        t = stats.get(band_t)
        w = stats.get(band_w)

        series.append({
            "Month": label,
            "Soil Temp (°C)": round(t - 273.15, 1)
            if t is not None else None,
            "Soil Moisture (%)": round(w * 100, 1)
            if w is not None else None,
        })

    return series


def summarize(series):
    """Mean/extremes over available months. Returns dict or None."""

    temps = [d["Soil Temp (°C)"] for d in series
             if d["Soil Temp (°C)"] is not None]
    moist = [d["Soil Moisture (%)"] for d in series
             if d["Soil Moisture (%)"] is not None]

    if not temps:
        return None

    return {
        "mean_temp": round(sum(temps) / len(temps), 1),
        "max_temp": max(temps),
        "min_temp": min(temps),
        "mean_moisture": round(sum(moist) / len(moist), 1)
        if moist else None,
    }
