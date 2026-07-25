"""Static satellite map thumbnails for the PDF report.

Visual proof for the report: each detection layer is rendered to a PNG
via Earth Engine's getThumbURL, clipped to the analysis buffer, so the
report can *show* what its numbers describe (plantation pixels, paddy,
land cover, greenness) laid over the real satellite image.

Every render is wrapped by the caller in try/except - a single failed
layer is simply omitted and never breaks the report.
"""

import ee
import requests

from gee.features import _s2_collection, _season, s2_annual


def _buffer(lat, lon, radius_km):
    return ee.Geometry.Point([lon, lat]).buffer(radius_km * 1000)


def _thumb(image, region, dimensions=560):
    """Fetch a PNG render of a visualised image over a region."""
    url = image.getThumbURL({
        "region": region,
        "dimensions": dimensions,
        "format": "png",
    })
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return r.content


def _s2_rgb(buffer, year):
    """Sentinel-2 true-colour composite, already visualised (RGB)."""
    med = _s2_collection(buffer, year).median()
    return med.visualize(bands=["B4", "B3", "B2"], min=0, max=3000)


def map_images(lat, lon, radius_km, year):
    """Return a list of {title, caption, png} for the report. Each
    layer is guarded independently so one failure omits just that map."""

    out = []
    buffer = _buffer(lat, lon, radius_km)

    # 1. Satellite context (true colour) -------------------------------
    try:
        rgb = _s2_rgb(buffer, year)
        out.append({
            "title": "Satellite view (true colour)",
            "caption": "Sentinel-2 cloud-free composite over the analysis "
                       "area - the ground every layer below is measured "
                       "from.",
            "png": _thumb(rgb.clip(buffer), buffer),
        })
    except Exception:
        pass

    # 2. Land cover (Dynamic World) ------------------------------------
    try:
        from gee.dynamic_world import PALETTE, dw_class_image
        s, e = _season(year)
        dw = dw_class_image(buffer, s, e)
        dwvis = dw.visualize(min=0, max=8, palette=PALETTE)
        out.append({
            "title": "Land cover classification (Dynamic World)",
            "caption": "Google Dynamic World near-real-time classes - "
                       "water, trees, crops, grass, built-up, bare soil.",
            "png": _thumb(dwvis.clip(buffer), buffer),
        })
    except Exception:
        pass

    # 3. NDVI greenness -------------------------------------------------
    try:
        ndvi = s2_annual(buffer, year).select("NDVI")
        nvis = ndvi.visualize(
            min=0.1, max=0.8,
            palette=["#d7191c", "#fdae61", "#ffffbf",
                     "#a6d96a", "#1a9641"])
        out.append({
            "title": "Vegetation vigour (NDVI)",
            "caption": "Median greenness. Red = bare / low vigour, "
                       "green = dense healthy vegetation.",
            "png": _thumb(nvis.clip(buffer), buffer),
        })
    except Exception:
        pass

    # 4. Plantation detection over satellite ---------------------------
    try:
        from gee.plantation import plantation_mask
        rgb = _s2_rgb(buffer, year)
        mask = plantation_mask(buffer, year).selfMask()
        mvis = mask.visualize(palette=["#ffe000"])
        out.append({
            "title": "Plantation detection (coconut / arecanut)",
            "caption": "Yellow = pixels the detector flags as perennial "
                       "plantation, drawn over the satellite image so you "
                       "can see the fit.",
            "png": _thumb(rgb.blend(mvis).clip(buffer), buffer),
        })
    except Exception:
        pass

    # 5. Paddy detection over satellite --------------------------------
    try:
        from gee.paddy import paddy_mask
        rgb = _s2_rgb(buffer, year)
        mask = paddy_mask(
            buffer, f"{year}-01-01", f"{year}-12-31").selfMask()
        mvis = mask.visualize(palette=["#00e5ff"])
        out.append({
            "title": "Paddy detection (radar)",
            "caption": "Cyan = pixels flagged as paddy from Sentinel-1 "
                       "radar structure, over the satellite image.",
            "png": _thumb(rgb.blend(mvis).clip(buffer), buffer),
        })
    except Exception:
        pass

    return out
