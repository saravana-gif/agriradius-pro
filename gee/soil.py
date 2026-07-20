"""Soil profile from SoilGrids (ISRIC) - modeled 250m estimates.

Available: pH, organic carbon, total nitrogen, texture (sand/silt/
clay). NOT available from satellite: phosphorus and potassium -
those need lab tests (Soil Health Cards).

Values are root-zone (0-30cm) averages over cropland in the buffer.
"""

import ee
import streamlit as st

# SoilGrids assets: per-property images with per-depth bands.
# Units: phh2o = pH*10, soc = dg/kg, nitrogen = cg/kg,
# sand/silt/clay = g/kg
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]

PROPS = {
    "phh2o": 10.0,      # -> pH
    "soc": 10.0,        # -> g/kg
    "nitrogen": 100.0,  # -> g/kg
    "sand": 10.0,       # -> %
    "silt": 10.0,       # -> %
    "clay": 10.0,       # -> %
}


def _rootzone(prop):
    """Mean of the 0-30cm depth bands for a property."""

    img = ee.Image(f"projects/soilgrids-isric/{prop}_mean")

    bands = [f"{prop}_{d}_mean" for d in DEPTHS]

    return img.select(bands).reduce(ee.Reducer.mean()).rename(prop)


@st.cache_data(show_spinner="Reading soil profile (SoilGrids)...")
def soil_profile(lat, lon, radius_km):
    """Return dict of root-zone soil properties for the buffer."""

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    stack = ee.Image.cat([_rootzone(p) for p in PROPS])

    stats = stack.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=buffer,
        scale=250,
        maxPixels=1e13,
        bestEffort=True,
    ).getInfo()

    out = {}

    for prop, divisor in PROPS.items():
        v = stats.get(prop)
        out[prop] = round(v / divisor, 2) if v is not None else None

    return out


def texture_class(sand, clay):
    """Simplified USDA texture class from sand/clay percentages."""

    if sand is None or clay is None:
        return "Unknown"

    silt = 100 - sand - clay

    if clay >= 40:
        return "Clay"
    if clay >= 27:
        return "Clay Loam"
    if sand >= 70 and clay < 15:
        return "Sandy"
    if sand >= 52:
        return "Sandy Loam"
    if silt >= 50:
        return "Silty Loam"
    return "Loam"


def interpret(profile):
    """Human verdicts for pH, organic carbon, nitrogen, texture."""

    if not profile:
        return None

    ph = profile.get("phh2o")
    soc = profile.get("soc")
    n = profile.get("nitrogen")
    sand = profile.get("sand")
    clay = profile.get("clay")

    verdicts = {}

    if ph is not None:
        if ph < 5.5:
            verdicts["pH"] = (f"{ph} - Acidic; may limit nutrient "
                              "uptake, liming can help")
        elif ph <= 7.5:
            verdicts["pH"] = f"{ph} - Ideal range for most crops"
        elif ph <= 8.5:
            verdicts["pH"] = (f"{ph} - Slightly alkaline; fine for "
                              "most crops, watch micronutrients")
        else:
            verdicts["pH"] = (f"{ph} - Strongly alkaline; can lock "
                              "up iron/zinc")

    if soc is not None:
        if soc < 5:
            verdicts["Organic Carbon"] = (
                f"{soc} g/kg - Low; organic matter addition "
                "(FYM/compost) would pay off")
        elif soc < 10:
            verdicts["Organic Carbon"] = (
                f"{soc} g/kg - Moderate (typical for South Indian "
                "farmland)")
        else:
            verdicts["Organic Carbon"] = f"{soc} g/kg - Good"

    if n is not None:
        if n < 0.8:
            verdicts["Total Nitrogen"] = (
                f"{n} g/kg - Low; nitrogen management matters here")
        elif n < 1.5:
            verdicts["Total Nitrogen"] = f"{n} g/kg - Moderate"
        else:
            verdicts["Total Nitrogen"] = f"{n} g/kg - Good"

    tex = texture_class(sand, clay)

    verdicts["Texture"] = (
        f"{tex} (sand {sand}%, clay {clay}%)"
        if sand is not None else tex
    )

    return verdicts
