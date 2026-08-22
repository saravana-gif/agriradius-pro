"""Indicative harvest volume from detected area.

WHY THIS IS A RANGE AND NOT A NUMBER
------------------------------------
Volume = area x yield. The area comes from satellite and is measured.
The yield does not: it varies with palm age, spacing, irrigation,
management and season, and published district productivity differs by
a factor of two within Karnataka. Reporting a single tonnage would
imply a precision that does not exist.

So every figure here is a band, built from published Karnataka
productivity, with the source and year attached. Where the low and
high come from different years, that is stated too - arecanut
productivity fell 37% between 2021-22 and 2025-26, and pretending
otherwise would flatter the estimate.

CALIBRATION
-----------
These are district-average productivities applied to detected area.
They know nothing about the specific palms in the circle. The moment
OneRoot's own arrival data is available it should replace the table
below - measured yield from real procurement beats any published
average, and no competitor can copy it. `override()` exists for that.
"""

HA_PER_ACRE = 0.404686

# Published Karnataka productivity. low/high are a genuine documented
# spread, NOT a confidence interval.
YIELDS = {
    "coconut": {
        "low": 4900, "high": 10600, "central": 7300,
        "unit": "nuts/ha",
        "basis": (
            "Low end is the productivity implied by Hassan district "
            "(97,999 ha for 4,759.81 lakh nuts); high end is the "
            "Karnataka state average of 10,581 nuts/ha; central is "
            "Tumakuru-implied (1,78,748 ha for 13,123.68 lakh nuts), "
            "the largest coconut district. National average for "
            "comparison: 9,123 nuts/ha."),
        "source": "Karnataka horticulture / Coconut Development Board",
        "year": "2018-19 to recent",
    },
    "arecanut": {
        "low": 1.42, "high": 2.24, "central": 1.8,
        "unit": "tonnes/ha",
        "basis": (
            "Karnataka arecanut productivity fell from 2.24 t/ha in "
            "2021-22 to 1.42 t/ha in 2025-26 - a 37% decline - while "
            "area grew from 6.03 to 7.99 lakh ha. The band spans that "
            "documented fall, so the low end is the recent reality "
            "and the high end the pre-decline level."),
        "source": "Karnataka horticulture department estimates",
        "year": "2021-22 to 2025-26",
    },
}

_OVERRIDES = {}


def override(crop, low, high, unit, basis, source, year="OneRoot"):
    """Replace a published band with OneRoot's own measured yield.

    Intended for the day procurement data exists: real arrivals per
    acre beat any district average, and the panel will say the figure
    came from OneRoot rather than a department table.
    """
    _OVERRIDES[str(crop).lower()] = {
        "low": float(low), "high": float(high),
        "central": (float(low) + float(high)) / 2,
        "unit": unit, "basis": basis, "source": source, "year": year,
        "measured": True,
    }


def yield_for(crop):
    key = str(crop or "").lower()
    if key in _OVERRIDES:
        return _OVERRIDES[key]
    for name, y in YIELDS.items():
        if name in key:
            return dict(y, measured=False)
    return None


def estimate(crop, acres, area_label=None, area_is_crop_specific=True):
    """Indicative volume band for `acres` of `crop`.

    `area_label` says WHAT the acreage is ("coconut recorded in the
    crop survey", "plantation net of forest"). It is not decoration:
    applying a coconut yield to every tree-crop acre - arecanut,
    mango, coffee and all - inflates the answer enormously. On a
    38 km circle that mistake produced a figure equal to a tenth of
    Karnataka's entire coconut crop. Set
    `area_is_crop_specific=False` for a mixed area and the output is
    labelled as a ceiling, not an estimate.

    Returns None when there is no defensible yield to apply - an
    unknown crop gets no number rather than a guessed one.
    """
    y = yield_for(crop)
    if not y or not acres or acres <= 0:
        return None
    ha = float(acres) * HA_PER_ACRE
    out = {
        "crop": crop,
        "acres": round(float(acres), 1),
        "hectares": round(ha, 1),
        "low": ha * y["low"],
        "high": ha * y["high"],
        "central": ha * y["central"],
        "unit": y["unit"].split("/")[0],
        "yield_low": y["low"],
        "yield_high": y["high"],
        "yield_unit": y["unit"],
        "basis": y["basis"],
        "source": y["source"],
        "year": y["year"],
        "measured": y.get("measured", False),
        "area_label": area_label or "detected area",
        "crop_specific": bool(area_is_crop_specific),
    }
    out["label"] = _label(out)
    return out


def _fmt(v, unit):
    if unit == "nuts":
        if v >= 1e7:
            return f"{v / 1e7:,.1f} crore nuts"
        if v >= 1e5:
            return f"{v / 1e5:,.1f} lakh nuts"
        return f"{v:,.0f} nuts"
    return f"{v:,.0f} t"


def _label(e):
    return (f"{_fmt(e['low'], e['unit'])} to "
            f"{_fmt(e['high'], e['unit'])}")


def caveat(e):
    """The sentence that must sit under any volume figure."""
    if not e:
        return None

    if not e.get("crop_specific", True):
        return (
            f"CEILING, NOT AN ESTIMATE. This applies {e['crop']} yield "
            f"to '{e['area_label']}' - an area that also contains "
            f"other tree crops. The true {e['crop']} volume is a "
            f"fraction of this. Use it only as an upper bound, and "
            f"prefer the crop-survey extent where one exists.")

    if e.get("measured"):
        return (f"Applied to {e['area_label']}. Yield band is "
                f"OneRoot's own measured figure, not a published "
                f"average.")
    return (
        f"Applied to {e['area_label']}. " +
        f"This is detected area multiplied by a published district "
        f"productivity band ({e['yield_low']}-{e['yield_high']} "
        f"{e['yield_unit']}, {e['source']}, {e['year']}). It knows "
        f"nothing about the age, spacing, irrigation or management of "
        f"the specific palms in this circle, and the band is a real "
        f"spread between districts and years - not a margin of error. "
        f"Treat it as an order of magnitude for planning, never as a "
        f"procurement commitment.")
