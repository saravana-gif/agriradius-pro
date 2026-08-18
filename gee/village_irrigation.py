"""Irrigation measured PER VILLAGE - the answer to "can I have this at
village level?".

The government irrigation statistics only exist per district, so this
computes the village-level numbers from satellite instead: for every
village polygon in the analysis circle, one Earth Engine pass returns

  * cropland area,
  * irrigated area (green AND moist through the Feb-May dry season),
  * radar irrigation events (works under cloud),
  * how much of it is far from surface water, i.e. borewell-fed,
  * how much two or more independent methods agree on.

Everything is a REAL measurement of that village's own polygon - not a
district figure spread across villages. The district source mix
(canal / borewell / tank) is carried alongside as context, clearly
labelled, because no open dataset publishes that split per village.

Village level is as fine as public data goes. Survey-number level
exists only in the Bhoomi RTC/Pahani and the seasonal Crop Survey, and
neither has an open bulk API.
"""

import ee
import streamlit as st

SQM_PER_ACRE = 4046.86

# Villages per run. Each village is a polygon in one reduceRegions
# call, so this is about payload size, not per-village cost.
MAX_VILLAGES = 400


def _fc(gdf):
    """Village polygons -> ee.FeatureCollection with a stable index."""
    slim = gdf[["geometry"]].copy()
    slim["idx"] = range(len(gdf))
    slim["geometry"] = slim.geometry.simplify(0.0005)
    return ee.FeatureCollection(slim.__geo_interface__)


def _sum_ac(image, fc, scale=30):
    """Area (acres) of a mask per feature, keyed by idx."""
    out = (ee.Image.pixelArea().updateMask(image)
           .reduceRegions(collection=fc, reducer=ee.Reducer.sum(),
                          scale=scale, tileScale=4)
           .getInfo())
    vals = {}
    for f in out.get("features", []):
        p = f.get("properties") or {}
        idx = p.get("idx")
        if idx is None:
            continue
        vals[int(idx)] = round((p.get("sum") or 0) / SQM_PER_ACRE, 1)
    return vals


@st.cache_data(show_spinner="Measuring irrigation village by village "
                            "(1-3 min)...", ttl=3600)
def village_irrigation(lat, lon, radius_km, year):
    """Per-village irrigation table for the circle.

    Returns a DataFrame, one row per village, or None. Cached, because
    it is the heaviest thing in the irrigation stack.
    """
    import pandas as pd

    from gis.spatial import villages_in_buffer

    gdf = villages_in_buffer(lat, lon, radius_km)
    if gdf is None or gdf.empty:
        return None

    gdf = gdf.copy()
    dedupe = [c for c in ("stname", "dtname", "vilname11", "vilcode11")
              if c in gdf.columns]
    if dedupe:
        gdf = gdf.drop_duplicates(subset=dedupe)

    truncated = False
    if len(gdf) > MAX_VILLAGES:
        b = gdf.geometry.bounds
        gdf["_d2"] = ((b.minx + b.maxx) / 2 - lon) ** 2 + \
                     ((b.miny + b.maxy) / 2 - lat) ** 2
        gdf = gdf.nsmallest(MAX_VILLAGES, "_d2")
        truncated = True

    gdf = gdf.reset_index(drop=True)
    fc = _fc(gdf)

    from gee import irrigation as ir

    buffer = ir._buffer(lat, lon, radius_km)
    districts = sorted({str(d) for d in gdf.get("dtname", [])
                        if str(d) not in ("nan", "None", "")})
    ndvi_min, ndmi_min, zone = ir.thresholds(districts)

    crop = ir._cropland(buffer, year)
    crop_ac = _sum_ac(crop, fc)

    try:
        irr_mask = ir.summer_green_mask(buffer, year, ndvi_min,
                                        ndmi_min)
        irr_ac = _sum_ac(irr_mask, fc)
    except Exception:
        irr_mask, irr_ac = None, {}

    try:
        ev_ac = _sum_ac(ir.s1_event_mask(buffer, year), fc)
    except Exception:
        ev_ac = {}

    try:
        _surf, ground = ir.surface_vs_ground(buffer, year)
        bore_ac = _sum_ac(ground, fc)
    except Exception:
        bore_ac = {}

    try:
        # evidence_score returns (image, per-method report); the report
        # is summarised in the area-level panel, not per village.
        ev, _report = ir.evidence_score(buffer, year, ndvi_min, ndmi_min)
        agree_ac = _sum_ac(ev.gte(2), fc) if ev is not None else {}
    except Exception:
        agree_ac = {}

    # District source mix as context - labelled, never presented as a
    # village-level measurement.
    from core import irrigation as istats

    rows = []
    for i, r in gdf.iterrows():
        dist = str(r.get("dtname", "") or "")
        prof = istats.for_district(dist) if dist else None
        c = crop_ac.get(i, 0.0)
        a = irr_ac.get(i, 0.0)
        rows.append({
            "village": str(r.get("vilname11", "?")).title(),
            "taluk": str(r.get("sdtname", "") or "").title(),
            "district": dist.title(),
            "cropland_ac": c,
            "irrigated_ac": a,
            "irrigated_pct": (round(100 * a / c, 1) if c else None),
            "radar_event_ac": ev_ac.get(i),
            "borewell_fed_ac": bore_ac.get(i),
            "agree_2plus_ac": agree_ac.get(i),
            "district_borewell_pct": (prof or {}).get("borewell_pct"),
            "district_canal_pct": (prof or {}).get("canal_pct"),
            "district_dominant_source": (prof or {}).get("dominant"),
            "vilcode11": str(r.get("vilcode11", "") or ""),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("irrigated_ac", ascending=False,
                        na_position="last").reset_index(drop=True)
    df.attrs["truncated"] = truncated
    df.attrs["zone"] = zone
    df.attrs["year"] = year
    return df


def summary(df):
    """Totals + the honest headline for a village irrigation table."""
    if df is None or df.empty:
        return None
    crop = float(df["cropland_ac"].fillna(0).sum())
    irr = float(df["irrigated_ac"].fillna(0).sum())
    bore = float(df["borewell_fed_ac"].fillna(0).sum())
    agree = float(df["agree_2plus_ac"].fillna(0).sum())
    scored = df["irrigated_pct"].notna().sum()
    return {
        "villages": int(len(df)),
        "villages_scored": int(scored),
        "cropland_ac": round(crop),
        "irrigated_ac": round(irr),
        "irrigated_pct": round(100 * irr / crop, 1) if crop else None,
        "borewell_fed_ac": round(bore),
        "agree_2plus_ac": round(agree),
        "heavily_irrigated_villages": int(
            (df["irrigated_pct"] >= 40).sum()),
        "rainfed_villages": int((df["irrigated_pct"] <= 5).sum()),
        "zone": df.attrs.get("zone"),
        "truncated": bool(df.attrs.get("truncated")),
    }
