"""Survey-number parcels from Karnataka K-GIS (KSRSAC).

WHY THIS IS AN ADAPTER AND NOT A HARD-CODED FETCHER
---------------------------------------------------
K-GIS is the state's own GIS platform, run by KSRSAC - the same
agency behind Dishaank. Its cadastral database is documented as
holding exactly what we need: grid number, SURVEY NUMBER, census
district code, taluk code and village code. That is the join key
FTW parcels lack and the Karnataka Crop Survey already uses.

What it does not have is a published, anonymous endpoint. The portal
is a JavaScript application, the service URLs are not discoverable
from outside, and the cadastral layer is not open data. Guessing a
URL and scraping the portal would be both unreliable and wrong.

So this module is an ADAPTER: give it the service URL your K-GIS
account is entitled to use and it queries survey-number parcels by
bounding box. It speaks the two protocols K-GIS publishes -
ArcGIS REST FeatureServer/MapServer and OGC WFS - and works out
which one it is given.

HOW TO GET THE URL
------------------
Write to kgissupport@ksrsac.in asking for programmatic access to the
cadastral layer for OneRoot's sourcing work, specifically:
  * a FeatureServer/MapServer query endpoint, or a WFS GetFeature
    endpoint, for the cadastral/survey-number layer;
  * the field names carrying survey number, village, taluk and
    district code;
  * whether a token or IP allow-listing is needed.
Paste what they give you into the Field Parcels tab.
"""

import json
from urllib.parse import urlencode

TIMEOUT = 60

# Field names K-GIS is documented to carry. Matched case-insensitively
# and by substring, because the exact spelling varies between layers.
SURVEY_KEYS = ["survey", "surveyno", "survey_no", "sy_no", "syno",
               "kgis_survey"]
VILLAGE_KEYS = ["village", "vill", "kgis_village"]
TALUK_KEYS = ["taluk", "taluka", "tehsil"]
DISTRICT_KEYS = ["district", "dist"]


# Who KSRSAC should reply to. Kept here so the request draft and any
# saved config carry the same contact rather than drifting apart.
CONTACT_EMAIL = "saravana@oneroot.farm"
CONTACT_ORG = "OneRoot (ENP Farms Private Limited)"
KSRSAC_SUPPORT = "kgissupport@ksrsac.in"


def request_draft(contact_email=CONTACT_EMAIL, org=CONTACT_ORG):
    """A ready-to-send access request for the K-GIS cadastral layer.

    Written to be answerable: it names the two protocols K-GIS
    already publishes, asks for the field names rather than guessing
    them, and states where the requests will originate so IP
    allow-listing can be arranged in the same reply instead of a
    second round trip.
    """
    return f"""To: {KSRSAC_SUPPORT}
Subject: Request for programmatic access to K-GIS cadastral \
(survey-number) layer

Dear K-GIS Support Team,

I am writing from {org} regarding agricultural sourcing work in
Karnataka. We operate an internal satellite analysis tool that
measures cropland, irrigation and plantation extent for a selected
area, and we would like to reference parcels by their official
survey number rather than by geometry alone.

Could you advise on programmatic access to the K-GIS cadastral
layer? Specifically:

1. A FeatureServer / MapServer query endpoint, or an OGC WFS
   GetFeature endpoint, for the cadastral / survey-number layer.

2. The field names carrying survey number, village, taluk and
   district code, so we map them correctly rather than by guesswork.

3. Whether a token or IP allow-listing is required. Our server is
   hosted in Mumbai (AWS ap-south-1) and we can supply a fixed IP.

4. The terms of use that apply, and whether a formal data-sharing
   agreement or MoU is needed for a private company.

We understand the hissa map georeferencing is still in progress and
that partial coverage is expected - that is not a problem for our
use case.

Please reply to {contact_email}.

Thank you for your time.

Regards,
Saravana
{org}
{contact_email}"""


def _cfg_path():
    from config import PROJECT_ROOT
    return PROJECT_ROOT / "data" / "kgis_service.json"


def configure(url, token=None, layer=None, note=None):
    """Remember the endpoint. Returns the saved config."""
    cfg = {"url": (url or "").strip(), "token": (token or "").strip(),
           "layer": layer, "note": note}
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def config():
    try:
        p = _cfg_path()
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            return cfg if cfg.get("url") else None
    except Exception:
        pass
    return None


def available():
    return config() is not None


def _kind(url):
    u = (url or "").lower()
    if "featureserver" in u or "mapserver" in u:
        return "arcgis"
    if "wfs" in u or "service=wfs" in u:
        return "wfs"
    return "unknown"


def _pick(props, keys):
    """First property whose name matches any of `keys`."""
    for k, v in (props or {}).items():
        kl = str(k).lower()
        if any(want in kl for want in keys):
            if v not in (None, "", " "):
                return v
    return None


def parcels(lat, lon, radius_km, max_features=4000):
    """Survey-number parcels intersecting the circle.

    Returns (GeoDataFrame, info). Never raises; info always explains.
    """
    import geopandas as gpd

    info = {"source": "Karnataka K-GIS (KSRSAC) cadastral",
            "note": None, "count": 0, "kind": None}

    cfg = config()
    if not cfg:
        info["note"] = (
            "K-GIS is not configured. It is the only source that can "
            "attach a SURVEY NUMBER to a parcel, but it has no public "
            "endpoint - request one from kgissupport@ksrsac.in and "
            "paste it into the Field Parcels tab.")
        return gpd.GeoDataFrame(), info

    kind = _kind(cfg["url"])
    info["kind"] = kind
    if kind == "unknown":
        info["note"] = (
            f"The saved URL does not look like an ArcGIS "
            f"FeatureServer/MapServer or an OGC WFS endpoint: "
            f"{cfg['url'][:120]}. Those are the two K-GIS publishes.")
        return gpd.GeoDataFrame(), info

    from core.field_boundaries import _bbox
    minx, miny, maxx, maxy = _bbox(lat, lon, radius_km)

    try:
        if kind == "arcgis":
            gj = _query_arcgis(cfg, minx, miny, maxx, maxy,
                               max_features)
        else:
            gj = _query_wfs(cfg, minx, miny, maxx, maxy, max_features)
    except Exception as e:
        info["note"] = (f"K-GIS query failed: {e.__class__.__name__}: "
                        f"{str(e)[:200]}")
        return gpd.GeoDataFrame(), info

    feats = (gj or {}).get("features") or []
    if not feats:
        info["note"] = ("K-GIS returned no parcels for this circle. "
                        "Note that only about 58% of Karnataka's "
                        "hissa maps are georeferenced, so gaps are "
                        "expected rather than surprising.")
        return gpd.GeoDataFrame(), info

    try:
        gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    except Exception as e:
        info["note"] = f"K-GIS response could not be parsed: {e}"
        return gpd.GeoDataFrame(), info

    # Normalise the identifying columns so the rest of the app does
    # not have to know K-GIS's field naming.
    props = feats[0].get("properties") or {}
    gdf["survey_no"] = [
        _pick(f.get("properties"), SURVEY_KEYS) for f in feats]
    gdf["village"] = [
        _pick(f.get("properties"), VILLAGE_KEYS) for f in feats]
    gdf["taluk"] = [
        _pick(f.get("properties"), TALUK_KEYS) for f in feats]
    gdf["district"] = [
        _pick(f.get("properties"), DISTRICT_KEYS) for f in feats]

    if gdf["survey_no"].isna().all():
        info["note"] = (
            f"Parcels came back but none carried a recognisable "
            f"survey-number field. Fields present: "
            f"{', '.join(list(props)[:12])}. Tell me which one holds "
            f"the survey number and I will map it.")

    info["count"] = len(gdf)
    return gdf, info


def _query_arcgis(cfg, minx, miny, maxx, maxy, limit):
    import requests
    url = cfg["url"].rstrip("/")
    if not url.endswith("/query"):
        url = f"{url}/query"
    params = {
        "f": "geojson",
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "resultRecordCount": int(limit),
    }
    if cfg.get("token"):
        params["token"] = cfg["token"]
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _query_wfs(cfg, minx, miny, maxx, maxy, limit):
    import requests
    params = {
        "service": "WFS", "version": "2.0.0",
        "request": "GetFeature",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": int(limit),
        # WFS 2.0 with EPSG:4326 expects lat,lon ordering.
        "bbox": f"{miny},{minx},{maxy},{maxx},EPSG:4326",
    }
    if cfg.get("layer"):
        params["typeNames"] = cfg["layer"]
    if cfg.get("token"):
        params["token"] = cfg["token"]
    sep = "&" if "?" in cfg["url"] else "?"
    r = requests.get(f"{cfg['url']}{sep}{urlencode(params)}",
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def join_to_ftw(ftw_gdf, kgis_gdf):
    """Attach survey numbers to FTW parcels by largest overlap.

    FTW gives the shape a machine saw; K-GIS gives the number a
    revenue office recognises. Neither alone is enough for sourcing:
    you cannot visit "polygon 4471", and you cannot measure a survey
    number from orbit. Matching is by greatest area of intersection,
    and the result carries the overlap fraction so a poor match can
    be spotted rather than trusted.
    """
    import geopandas as gpd

    if ftw_gdf is None or len(ftw_gdf) == 0:
        return ftw_gdf, "No FTW parcels to join."
    if kgis_gdf is None or len(kgis_gdf) == 0:
        return ftw_gdf, "No K-GIS parcels to join."

    try:
        utm = ftw_gdf.estimate_utm_crs()
        a = ftw_gdf.to_crs(utm).copy()
        b = kgis_gdf.to_crs(utm).copy()
        a["_ftw_i"] = range(len(a))
        a["_ftw_area"] = a.geometry.area

        inter = gpd.overlay(
            a[["_ftw_i", "_ftw_area", "geometry"]],
            b[["survey_no", "village", "taluk", "district",
               "geometry"]],
            how="intersection", keep_geom_type=False)
        if inter.empty:
            return ftw_gdf, ("FTW and K-GIS parcels do not overlap "
                             "here - check they cover the same area.")
        inter["_ov"] = inter.geometry.area
        inter["_frac"] = inter["_ov"] / inter["_ftw_area"]
        best = (inter.sort_values("_ov", ascending=False)
                .drop_duplicates("_ftw_i")
                .set_index("_ftw_i"))

        out = ftw_gdf.copy()
        for col in ("survey_no", "village", "taluk", "district"):
            out[col] = out.index.map(
                lambda i: best[col].get(i) if i in best.index else None)
        out["survey_overlap"] = out.index.map(
            lambda i: round(float(best["_frac"].get(i, 0)), 2)
            if i in best.index else None)

        matched = int(out["survey_no"].notna().sum())
        return out, (
            f"{matched} of {len(out)} field parcels matched to a "
            f"survey number by largest overlap. The overlap fraction "
            f"is kept per parcel - anything well below 1.0 means the "
            f"machine-seen field and the revenue parcel disagree, "
            f"which is common where one survey number holds several "
            f"cultivated plots.")
    except Exception as e:
        return ftw_gdf, f"Join failed: {e.__class__.__name__}: {e}"
