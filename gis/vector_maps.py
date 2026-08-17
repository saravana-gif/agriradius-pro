"""Render the app's VECTOR map layers to PNGs for the PDF report.

The SHC soil-test layer and the coconut crop-survey layer are drawn
from GeoJSON with precomputed fill colours, not from Earth Engine, so
they need their own renderer. Matplotlib draws each polygon with the
same colour the live map uses, giving the report a faithful picture of
the measured layers.

Returns the same {kind, title, caption, legend, png} shape as
gee/report_maps.py so the PDF builder treats them identically.
"""

from io import BytesIO


def _polygons(geom):
    """Yield exterior rings as [(x, y), ...] from a GeoJSON geometry."""
    if not geom:
        return
    t = geom.get("type")
    c = geom.get("coordinates")
    if t == "Polygon":
        if c:
            yield c[0]
    elif t == "MultiPolygon":
        for poly in c or []:
            if poly:
                yield poly[0]


def _render(geojson, title, subtitle):
    """Draw a GeoJSON FeatureCollection to a PNG. None if nothing."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MplPolygon

    feats = (geojson or {}).get("features") or []
    if not feats:
        return None

    fig, ax = plt.subplots(figsize=(6, 6))
    drawn = 0
    for f in feats:
        fill = (f.get("properties") or {}).get("_fill") or "#bdbdbd"
        for ring in _polygons(f.get("geometry")):
            try:
                ax.add_patch(MplPolygon(
                    ring, closed=True, facecolor=fill,
                    edgecolor="#666666", linewidth=0.25))
                drawn += 1
            except Exception:
                continue
    if not drawn:
        plt.close(fig)
        return None

    ax.autoscale_view()
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(subtitle, fontsize=9, color="#444444")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def shc_map(lat, lon, radius_km, metric="n_low"):
    """Village-level measured soil-test layer as a report image."""
    try:
        from gis import shc_layer
        gj = shc_layer.geojson_villages(metric, round(float(lat), 4),
                                        round(float(lon), 4),
                                        float(radius_km))
        if gj is None:
            gj = shc_layer.geojson_for(metric, round(float(lat), 4),
                                       round(float(lon), 4),
                                       float(radius_km))
        if gj is None:
            return None
        label = shc_layer.METRICS.get(
            metric, shc_layer.METRICS["n_low"])[0]
        png = _render(gj, label, label)
        if not png:
            return None
        return {
            "kind": "shc",
            "title": f"Measured soil test - {label}",
            "caption": "Soil Health Card lab results, village by "
                       "village. These are real farmer samples tested "
                       "in government labs - the only measured (not "
                       "modelled) soil layer in this report. Grey = no "
                       "samples on record.",
            "legend": [(c.lstrip("#"), lab)
                       for lab, c in shc_layer.legend_items(metric)],
            "png": png,
        }
    except Exception:
        return None


def coconut_survey_map(lat, lon, radius_km, metric="intensity"):
    """Government coconut crop-survey layer as a report image."""
    try:
        from gis import crop_survey_layer
        gj = crop_survey_layer.geojson_villages(
            metric, round(float(lat), 4), round(float(lon), 4),
            float(radius_km))
        if gj is None:
            return None
        label = crop_survey_layer.METRICS.get(
            metric, crop_survey_layer.METRICS["intensity"])[0]
        png = _render(gj, label, label)
        if not png:
            return None
        return {
            "kind": "coconut_survey",
            "title": f"Government coconut crop survey - {label}",
            "caption": "Every coconut plot logged against its survey "
                       "number in the Karnataka crop survey (2023-24 "
                       "Kharif), aggregated per village. Ground "
                       "records, not satellite.",
            "legend": [(c.lstrip("#"), lab)
                       for lab, c in
                       crop_survey_layer.legend_items(metric)],
            "png": png,
        }
    except Exception:
        return None


def irrigation_map(lat, lon, radius_km, metric="borewell_pct"):
    """District irrigation-source layer as a report image."""
    try:
        from gis import irrigation_layer
        gj = irrigation_layer.geojson_for(
            metric, round(float(lat), 4), round(float(lon), 4),
            float(radius_km))
        if gj is None:
            return None
        label = irrigation_layer.METRICS.get(
            metric, irrigation_layer.METRICS["borewell_pct"])[0]
        png = _render(gj, label, label)
        if not png:
            return None
        return {
            "kind": "irrigation_source",
            "title": f"Irrigation source by district - {label}",
            "caption": "Land Use Statistics (DES-Agri) 2022-23. The "
                       "borewell/canal split is the operational one: "
                       "canal-led districts can be targeted straight "
                       "from command-area maps, borewell-led "
                       "districts cannot - those wells are invisible "
                       "to infrastructure data and are drilled faster "
                       "than land records update.",
            "legend": [(c.lstrip("#"), lab) for lab, c in
                       irrigation_layer.legend_items(metric)],
            "png": png,
        }
    except Exception:
        return None


def vector_maps(lat, lon, radius_km, shc_metric="n_low"):
    """All available vector-layer report images."""
    out = []
    for fn in (lambda: shc_map(lat, lon, radius_km, shc_metric),
               lambda: coconut_survey_map(lat, lon, radius_km),
               lambda: irrigation_map(lat, lon, radius_km,
                                      "borewell_pct"),
               lambda: irrigation_map(lat, lon, radius_km,
                                      "dominant")):
        try:
            item = fn()
        except Exception:
            item = None
        if item:
            out.append(item)
    return out
