"""Check the satellite irrigation layer against ground records.

There is no published plot-level irrigation truth set for Karnataka, so
the app validates against the closest thing it holds: the government
crop survey records whether each coconut plot is irrigated. Aggregated
per village that gives a measured irrigated SHARE for ~3,300 villages
across six districts - an independent yardstick the satellite never
saw.

Read the result honestly. This is a correlation against one crop's
plots, not a kappa against a labelled sample:

  * coconut is a perennial garden crop, so its irrigated share runs
    higher than the village as a whole;
  * the survey's irrigation flag is recorded per plot by a surveyor,
    not measured;
  * agreement in DIRECTION (villages the survey calls heavily
    irrigated should score high on the satellite layer) is the useful
    signal - not agreement in absolute percentage.

Used by the irrigation panel and the report to state, in numbers, how
much the satellite layer can be trusted in the districts you are
looking at.
"""

from core import crop_survey, irrigation


def survey_irrigation_reference(lat, lon, radius_km):
    """Measured irrigated share from the crop survey for this circle.

    Returns None outside the survey's districts.
    """
    rows = crop_survey.in_radius(lat, lon, radius_km)
    if not rows:
        return None

    parcels = sum(r["parcels"] for r in rows)
    if not parcels:
        return None

    irr_parcels = sum(r["parcels"] * (r["irrigated_pct"] / 100.0)
                      for r in rows)
    shares = [r["irrigated_pct"] for r in rows if r["parcels"] >= 5]

    return {
        "villages": len(rows),
        "villages_scored": len(shares),
        "parcels": int(parcels),
        "irrigated_pct": round(100 * irr_parcels / parcels, 1),
        "high_irrigation_villages": sum(1 for s in shares if s >= 50),
        "low_irrigation_villages": sum(1 for s in shares if s <= 10),
        "vintage": crop_survey.VINTAGE,
    }


def compare(lat, lon, radius_km, sat_stats):
    """Satellite irrigated share vs the survey's measured share.

    Returns a dict with both figures, the gap, and a plain-English
    reading of what the gap means. None when either side is missing.
    """
    ref = survey_irrigation_reference(lat, lon, radius_km)
    if not ref or not sat_stats:
        return None

    sat_pct = sat_stats.get("summer_green_pct")
    if sat_pct is None:
        return None

    gap = round(sat_pct - ref["irrigated_pct"], 1)

    if abs(gap) <= 15:
        reading = (
            "The satellite layer and the surveyor's irrigation flags "
            "agree closely here, which is the best evidence available "
            "that the layer is behaving.")
    elif gap < -15:
        reading = (
            "The satellite finds LESS irrigation than the survey "
            "records. Expected where coconut dominates: mature palms "
            "on drip or basin irrigation hold moderate canopy and "
            "little bare-soil contrast, so summer greenness "
            "under-detects them. Treat the satellite figure as a "
            "floor for plantation districts.")
    else:
        reading = (
            "The satellite finds MORE irrigation than the coconut "
            "survey records. That is expected: the survey's flag "
            "covers coconut plots only, while the satellite sees every "
            "irrigated crop in the circle, including seasonal ones.")

    return {
        "satellite_pct": sat_pct,
        "survey_pct": ref["irrigated_pct"],
        "gap_pct": gap,
        "villages": ref["villages"],
        "parcels": ref["parcels"],
        "reading": reading,
        "vintage": ref["vintage"],
        "caveat": (
            "Coconut plots only, surveyor-recorded, aggregated per "
            "village - a directional check, not a formal accuracy "
            "score."),
    }


def zone_expectation(districts):
    """What accuracy to expect here, before any measurement."""
    prof = irrigation.zone_profile(districts)
    return {
        "zone": prof.get("label"),
        "accuracy": prof.get("accuracy"),
        "note": prof.get("note"),
        "mixed": prof.get("mixed"),
        "zones_present": prof.get("zones_present"),
        "ndvi_threshold": prof.get("ndvi"),
        "ndmi_threshold": prof.get("ndmi"),
    }
