"""Per-village crop insights.

For every village in the buffer: cropland acres, cropping pattern,
cycles/year and mean NDVI - computed in two Earth Engine calls
(area + 24-month NDVI stack, both reduced per village polygon).
"""

import ee
import pandas as pd
import streamlit as st

from core.crop_cycle import to_dataframe, analyze_series
from gee.dynamic_world import dw_crops_mask
from gee.ndvi import ndvi_monthly_stack
from gis.spatial import villages_in_buffer

SQM_PER_ACRE = 4046.8564224

# Above this many villages the per-village reduction gets very slow.
# Rather than refuse (which made a 38 km report simply lose its
# village table), rank the villages and analyse the largest
# MAX_VILLAGES of them.
MAX_VILLAGES = 300


# How the shortlist is scored. Irrigated LAND dominates because that
# is what the field team can act on; the share terms stop a big
# village with a thin irrigated fraction outranking a small intensely
# irrigated one; cropland size is the tie-breaker.
RANK_WEIGHTS = {
    "irrigated_ac": 0.45,     # measured Feb-May green+moist cropland
    "irrigated_share": 0.20,  # how much of its cropland is irrigated
    "intensity_share": 0.15,  # multi-crop share - cropping intensity
    "cropland_ac": 0.20,      # total farmland
}


def _screen_villages(gdf, buffer, year, lat, lon, radius_km):
    """One cheap Earth Engine pass over EVERY village.

    Returns a DataFrame with measured cropland, irrigated and
    multi-crop area per village, or None if the pass fails.

    This exists so the shortlist can be ranked on IRRIGATION and
    CROPPING INTENSITY rather than on polygon size. The full analysis
    (24-month NDVI phenology, cycles/year) is far too heavy for 600+
    villages, but these three areas come from a single reduceRegions
    over one multi-band image, which is affordable for all of them.
    Rank on what matters, then spend the expensive call on the
    shortlist.
    """
    from core import compute as _cq
    from gee.irrigation import (_cropland, multicrop_mask,
                                summer_green_mask, thresholds)

    area = ee.Image.pixelArea()
    crop = _cropland(buffer, year)
    bands = [area.updateMask(crop).rename("crop_m2")]

    try:
        ndvi_min, ndmi_min, _ = thresholds(
            _districts_safe(lat, lon, radius_km))
        irr = summer_green_mask(buffer, year, ndvi_min, ndmi_min)
        bands.append(area.updateMask(irr).rename("irr_m2"))
    except Exception:
        pass
    try:
        bands.append(
            area.updateMask(multicrop_mask(buffer)).rename("mc_m2"))
    except Exception:
        pass

    # Screening only, so it runs coarse on purpose - the numbers
    # decide an ordering, not a published figure.
    scale = max(_cq.stat_scale(), 60)
    feats = (ee.Image.cat(bands)
             .reduceRegions(collection=_to_feature_collection(gdf),
                            reducer=ee.Reducer.sum(),
                            scale=scale,
                            tileScale=_cq.tile_scale())
             .getInfo())

    rows = []
    for f in feats["features"]:
        p = f["properties"]
        crop_ac = (p.get("crop_m2") or 0) / SQM_PER_ACRE
        irr_ac = (p.get("irr_m2") or 0) / SQM_PER_ACRE
        mc_ac = (p.get("mc_m2") or 0) / SQM_PER_ACRE
        rows.append({
            "idx": p.get("idx"),
            "cropland_ac": crop_ac,
            "irrigated_ac": irr_ac,
            "irrigated_share": (irr_ac / crop_ac) if crop_ac else 0.0,
            "intensity_share": (mc_ac / crop_ac) if crop_ac else 0.0,
        })
    return pd.DataFrame(rows)


def _districts_safe(lat, lon, radius_km):
    try:
        from gee.irrigation import _districts
        return _districts(lat, lon, radius_km)
    except Exception:
        return None


def _score(screen):
    """Blend the measured columns into one 0-1 score per village."""
    s = pd.Series(0.0, index=screen.index)
    for col, weight in RANK_WEIGHTS.items():
        if col not in screen:
            continue
        v = screen[col].astype(float)
        hi = v.max()
        if hi and hi > 0:
            s = s + weight * (v / hi)      # normalise, then weight
    return s


def _rank_and_cap(gdf, max_villages, buffer=None, year=None,
                  lat=None, lon=None, radius_km=None):
    """Shortlist the `max_villages` most agriculturally significant.

    Ranked on MEASURED irrigation and cropping intensity, not on
    polygon size and not on distance from the centre. Distance would
    quietly shrink a 38 km request to a smaller circle while still
    calling itself 38 km; size would favour big empty villages over
    small intensively irrigated ones.

    Falls back to polygon area only if the screening pass fails, and
    says so, because an unexplained ordering is worse than a crude
    one.
    """
    total = len(gdf)
    if total <= max_villages:
        return gdf, None

    screen = None
    if buffer is not None:
        try:
            screen = _screen_villages(gdf, buffer, year, lat, lon,
                                      radius_km)
        except Exception:
            screen = None

    if screen is not None and len(screen) == total:
        screen = screen.set_index("idx").reindex(range(total))
        screen = screen.fillna(0.0)
        order = _score(screen).sort_values(ascending=False)
        keep_idx = list(order.head(max_villages).index)
        kept = gdf.iloc[keep_idx].reset_index(drop=True)
        sel = screen.loc[keep_idx]
        note = (
            f"{total} villages fall inside this radius - above the "
            f"{max_villages} the full per-village analysis can "
            f"handle. Rather than drop the table, every one of the "
            f"{total} was first screened by satellite for cropland, "
            f"irrigated area (Feb-May green and moist) and "
            f"multi-cropping, and the {max_villages} ranking highest "
            f"on those were analysed in full. Weights: irrigated "
            f"acres {RANK_WEIGHTS['irrigated_ac']:.0%}, irrigated "
            f"share {RANK_WEIGHTS['irrigated_share']:.0%}, cropping "
            f"intensity {RANK_WEIGHTS['intensity_share']:.0%}, "
            f"cropland acres {RANK_WEIGHTS['cropland_ac']:.0%}. The "
            f"shortlist holds {sel['irrigated_ac'].sum():,.0f} ac of "
            f"the {screen['irrigated_ac'].sum():,.0f} ac of irrigated "
            f"cropland found across all {total} villages "
            f"({100 * sel['irrigated_ac'].sum() / max(screen['irrigated_ac'].sum(), 1e-9):.0f}%). "
            f"The {total - max_villages} villages not listed are the "
            f"least irrigated and least intensively cropped, spread "
            f"across the whole radius - the footprint is not cropped "
            f"to a smaller circle.")
        return kept, note

    # Fallback: polygon area, clearly labelled as the weaker rule.
    ranked = gdf.copy()
    try:
        ranked["_area"] = ranked.to_crs(
            ranked.estimate_utm_crs()).geometry.area
    except Exception:
        ranked["_area"] = ranked.geometry.area
    ranked = ranked.sort_values("_area", ascending=False)
    kept = ranked.head(max_villages).drop(
        columns=["_area"]).reset_index(drop=True)
    note = (
        f"{total} villages fall inside this radius, above the "
        f"{max_villages} the per-village analysis can handle. The "
        f"satellite screening pass that normally ranks them by "
        f"irrigation and cropping intensity could not run, so this "
        f"shortlist is the {max_villages} LARGEST BY AREA - a "
        f"cruder rule: a big village with little irrigated land can "
        f"outrank a small intensively irrigated one. Rebuild to "
        f"retry the proper ranking.")
    return kept, note


def _to_feature_collection(gdf):
    """Simplified village polygons -> ee.FeatureCollection."""

    slim = gdf[["geometry"]].copy()
    slim["idx"] = range(len(gdf))

    # Simplify to keep the upload small (~50m tolerance)
    slim["geometry"] = slim.geometry.simplify(0.0005)

    return ee.FeatureCollection(slim.__geo_interface__)


@st.cache_data(show_spinner="Computing village insights (1-3 min)...")
def village_insights(lat, lon, radius_km, year):
    """Return a DataFrame: one row per village with crop insights."""

    gdf = villages_in_buffer(lat, lon, radius_km)

    if gdf.empty:
        return pd.DataFrame()

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(radius_km * 1000)

    # Screen and shortlist BEFORE the expensive phenology call.
    gdf, cap_note = _rank_and_cap(
        gdf, MAX_VILLAGES, buffer=buffer, year=year,
        lat=lat, lon=lon, radius_km=radius_km)

    start, end = f"{year - 1}-01-01", f"{year}-12-31"

    fc = _to_feature_collection(gdf)

    # --- Call 1: cropland area per village ---
    crops = dw_crops_mask(buffer, start, end)

    area_fc = (
        ee.Image.pixelArea()
        .updateMask(crops)
        .reduceRegions(
            collection=fc,
            reducer=ee.Reducer.sum(),
            scale=30,
            tileScale=4,
        )
        .getInfo()
    )

    # --- Call 2: monthly NDVI means per village ---
    stack, months = ndvi_monthly_stack(buffer, year - 1, year)

    ndvi_fc = (
        stack.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=60,
            tileScale=4,
        )
        .getInfo()
    )

    crop_area = {
        f["properties"]["idx"]: f["properties"].get("sum", 0)
        for f in area_fc["features"]
    }

    ndvi_props = {
        f["properties"]["idx"]: f["properties"]
        for f in ndvi_fc["features"]
    }

    rows = []

    for i in range(len(gdf)):

        rec = gdf.iloc[i]

        acres = round((crop_area.get(i) or 0) / SQM_PER_ACRE, 1)

        props = ndvi_props.get(i, {})
        series = [
            (label, props.get(band)) for band, label in months
        ]

        has_data = any(v is not None for _, v in series)

        if has_data and acres > 0:
            insight = analyze_series(to_dataframe(series))
            pattern = insight["pattern"]
            cycles = insight["cycles_per_year"]
            mean_ndvi = insight["mean_ndvi"]
        else:
            pattern = "No cropland data"
            cycles = 0.0
            mean_ndvi = 0.0

        rows.append({
            "Village": rec.get("vilname11", f"Village {i}"),
            "Taluk": rec.get("sdtname", ""),
            "District": rec.get("dtname", ""),
            "Cropland (ac)": acres,
            "Pattern": pattern,
            "Cycles/Year": cycles,
            "Mean NDVI": mean_ndvi,
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(
        "Cropland (ac)", ascending=False).reset_index(drop=True)

    # Carried on the frame so the UI and the PDF can both say the
    # table is a capped subset. A truncated table that does not admit
    # it is worse than no table.
    df.attrs["cap_note"] = cap_note
    df.attrs["villages_analysed"] = len(df)
    return df
