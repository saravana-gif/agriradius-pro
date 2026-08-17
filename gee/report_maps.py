"""Static satellite map thumbnails for the PDF report.

Visual proof for the report: EVERY map layer the app can show on
screen is rendered to a PNG via Earth Engine's getThumbURL, clipped to
the analysis buffer, so the report can *show* what its numbers
describe (land cover, greenness, plantation, banana, paddy, maize,
WorldCereal cropland, aquaculture ponds, and the three painted soil
properties) laid over the real satellite image.

Every render is wrapped so a single failed layer is simply omitted and
never breaks the report.
"""

import ee
import requests

from gee.features import _s2_collection, _season, s2_annual


# Legends (hex, label) so the PDF can show what each colour means.
DW_LEGEND = [
    ("419bdf", "Water"), ("397d49", "Trees"), ("88b053", "Grass"),
    ("ff00ff", "Cropland"), ("dfc35a", "Shrub / scrub"),
    ("c4281b", "Built-up"), ("a59b8f", "Bare soil"),
]
NDVI_LEGEND = [
    ("d7191c", "Bare / very low"), ("fdae61", "Low"),
    ("ffffbf", "Moderate"), ("a6d96a", "High"),
    ("1a9641", "Dense / very high"),
]
CONFIDENCE_LEGEND = [
    ("1a9850", "Both datasets agree: cropland"),
    ("f4c20d", "Only one dataset says cropland"),
]


# Every layer this module tries to render. The report compares this
# against what actually came back and lists anything missing, so a
# silently dropped layer can't go unnoticed.
EXPECTED = [
    ("satellite", "Satellite view"),
    ("landcover", "Land cover (Dynamic World)"),
    ("confidence", "Cropland confidence"),
    ("ndvi", "Vegetation vigour (NDVI)"),
    ("plantation", "Plantation detection"),
    ("banana", "Banana detection"),
    ("paddy", "Paddy detection"),
    ("maize", "Maize / kharif detection"),
    ("worldcereal", "WorldCereal cropland"),
    ("aquaculture", "Aquaculture ponds"),
    ("soil_ph", "Soil pH"),
    ("soil_oc", "Soil organic carbon"),
    ("soil_n", "Soil nitrogen"),
]


def missing_layers(images):
    """Titles of the layers that failed to render, for the notes."""
    got = {i.get("kind") for i in (images or [])}
    return [label for kind, label in EXPECTED if kind not in got]


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


def _overlay(out, buffer, year, kind, title, caption, mask_fn, colour,
             what):
    """Render a detection mask over the satellite image."""
    try:
        rgb = _s2_rgb(buffer, year)
        mask = mask_fn().selfMask()
        mvis = mask.visualize(palette=[colour])
        out.append({
            "kind": kind,
            "title": title,
            "caption": caption,
            "legend": [(colour.lstrip("#"), what),
                       ("_base", "Satellite (everything else)")],
            "png": _thumb(rgb.blend(mvis).clip(buffer), buffer),
        })
    except Exception:
        pass


def map_images(lat, lon, radius_km, year):
    """Return a list of {kind, title, caption, legend, png} covering
    every map layer. Each layer is guarded independently so one
    failure omits just that map."""

    out = []
    buffer = _buffer(lat, lon, radius_km)

    # 1. Satellite context (true colour) -------------------------------
    try:
        rgb = _s2_rgb(buffer, year)
        out.append({
            "kind": "satellite",
            "title": "Satellite view (true colour)",
            "caption": "Sentinel-2 cloud-free composite over the analysis "
                       "area - the ground every layer below is measured "
                       "from. Natural colour: vegetation green, water "
                       "dark, soil/built pale.",
            "legend": None,
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
            "kind": "landcover",
            "title": "Land cover classification (Dynamic World)",
            "caption": "Google Dynamic World near-real-time classes. Each "
                       "pixel is coloured by its most likely land cover "
                       "(see legend).",
            "legend": DW_LEGEND,
            "png": _thumb(dwvis.clip(buffer), buffer),
        })
    except Exception:
        pass

    # 3. Cropland confidence (two datasets cross-checked) --------------
    try:
        from gee.worldcover import PALETTE as CONF_PALETTE, _layers
        buf2, dw_c, wc_c = _layers(lat, lon, radius_km, year)
        agreement = dw_c.add(wc_c)
        img = agreement.updateMask(agreement.gt(0)).clip(buffer)
        cvis = img.visualize(min=1, max=2, palette=CONF_PALETTE)
        out.append({
            "kind": "confidence",
            "title": "Cropland confidence (two datasets)",
            "caption": "Green where Dynamic World and ESA WorldCover "
                       "both call the pixel cropland; yellow where only "
                       "one does. Green is the land you can rely on.",
            "legend": CONFIDENCE_LEGEND,
            "png": _thumb(cvis, buffer),
        })
    except Exception:
        pass

    # 4. NDVI greenness -------------------------------------------------
    try:
        ndvi = s2_annual(buffer, year).select("NDVI")
        nvis = ndvi.visualize(
            min=0.1, max=0.8,
            palette=["#d7191c", "#fdae61", "#ffffbf",
                     "#a6d96a", "#1a9641"])
        out.append({
            "kind": "ndvi",
            "title": "Vegetation vigour (NDVI)",
            "caption": "Median growing-season greenness (NDVI). Higher = "
                       "denser, healthier canopy.",
            "legend": NDVI_LEGEND,
            "png": _thumb(nvis.clip(buffer), buffer),
        })
    except Exception:
        pass

    # 5-9. Detection layers over the satellite image -------------------
    try:
        from gee.plantation import banana_mask, plantation_mask
        _overlay(out, buffer, year, "plantation",
                 "Plantation detection (coconut / arecanut)",
                 "Detector output drawn over the satellite image so you "
                 "can judge the fit against real groves.",
                 lambda: plantation_mask(buffer, year),
                 "#ffe000", "Detected plantation")
        _overlay(out, buffer, year, "banana",
                 "Banana detection (likely)",
                 "Banana signature: dense year-round canopy on flat, "
                 "irrigated ground, in small blocks.",
                 lambda: banana_mask(buffer, year),
                 "#ff8f00", "Likely banana")
    except Exception:
        pass

    try:
        from gee.paddy import paddy_mask
        _overlay(out, buffer, year, "paddy",
                 "Paddy detection (radar)",
                 "Flagged from Sentinel-1 radar structure - flooded, "
                 "smooth fields - drawn over the satellite image.",
                 lambda: paddy_mask(buffer, f"{year}-01-01",
                                    f"{year}-12-31"),
                 "#00e5ff", "Detected paddy")
    except Exception:
        pass

    try:
        from gee.maize import maize_mask
        _overlay(out, buffer, year, "maize",
                 "Maize / kharif crop detection (likely)",
                 "Tall seasonal cereal signature: a sharp monsoon NDVI "
                 "peak followed by a hard senescence trough.",
                 lambda: maize_mask(buffer, year),
                 "#ffa000", "Likely maize / kharif crop")
    except Exception:
        pass

    try:
        from gee.worldcereal import CROPLAND_COLOR, _temporary_crops
        crops = _temporary_crops().eq(100)
        _overlay(out, buffer, year, "worldcereal",
                 "WorldCereal cropland (ESA, independent)",
                 "ESA's independent seasonal-crop map (2021). It maps "
                 "TEMPORARY crops only, so perennial plantations are "
                 "deliberately absent - use it as a third opinion on "
                 "seasonal cropland.",
                 lambda: crops,
                 "#" + CROPLAND_COLOR, "WorldCereal cropland")
    except Exception:
        pass

    try:
        from gee.aquaculture import aquaculture_mask
        _overlay(out, buffer, year, "aquaculture",
                 "Aquaculture ponds (satellite)",
                 "Permanent water bodies with regular, rectangular "
                 "shapes - the fish/shrimp pond signature.",
                 lambda: aquaculture_mask(buffer),
                 "#00bcd4", "Detected ponds")
    except Exception:
        pass

    # 10-12. Painted soil properties (SoilGrids) -----------------------
    try:
        from gee.soil import SOIL_LAYERS, _rootzone
        for layer_id in ("soil_ph", "soil_oc", "soil_n"):
            try:
                cfg = SOIL_LAYERS[layer_id]
                img = _rootzone(cfg["prop"]).clip(buffer)
                svis = img.visualize(min=cfg["min"], max=cfg["max"],
                                     palette=cfg["palette"])
                legend = [(c, "") for c in cfg["palette"]]
                legend[0] = (cfg["palette"][0], "low")
                legend[-1] = (cfg["palette"][-1], "high")
                out.append({
                    "kind": layer_id,
                    "title": cfg["label"],
                    "caption": "SoilGrids (ISRIC) modelled root-zone "
                               "0-30 cm estimate at 250 m. Modelled, "
                               "not lab-measured - see the Soil Health "
                               "Card section for measured values.",
                    "legend": legend,
                    "png": _thumb(svis, buffer),
                })
            except Exception:
                continue
    except Exception:
        pass

    return out
