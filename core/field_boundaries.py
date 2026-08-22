"""Field parcels from Fields of The World (FTW) global boundaries.

WHAT THIS IS
------------
FTW is the first global, wall-to-wall agricultural field-boundary
dataset at 10 m: ~1.6 billion polygons per year for 2024 and 2025,
195 countries, produced by running the PRUE segmentation model over
cloud-free Sentinel-2 mosaics. Published CC-BY-4.0 by Taylor
Geospatial with Microsoft AI for Good, ASU, WashU, Oregon State and
Clark. Paper: Robinson et al. 2026, arXiv:2605.11055.

WHAT IT IS NOT - read this before quoting anything
--------------------------------------------------
The FTW authors are explicit: "A field here is a remote-sensing field
unit (a connected component of predicted field-interior pixels), NOT
a cadastral/legal parcel. This is not a land-tenure product." One
legal parcel may map to many polygons, or to none. It carries no
survey number and says nothing about ownership.

They also warn that the confidence layer "is conservative outside the
FTW training distribution (e.g. smallholder systems)" - which is
exactly Karnataka. Real fields here may score low. So the default
confidence floor is deliberately permissive, and the panel reports
the confidence distribution rather than hiding behind a threshold.

For survey numbers you need the Karnataka cadastral record
(Dishaank / Bhoomi RTC), which has no open API and is about 58%
georeferenced. FTW gives you the shape; only the revenue record gives
you the number.

HOW IT IS FETCHED
-----------------
The data is anonymous-read GeoParquet over plain HTTPS, so DuckDB
reads only the byte ranges it needs - the whole India partition is
never downloaded. Runs on the server, like the WRIS and MI-census
fetchers, because a sandbox cannot reach source.coop.
"""

import json
import time
from pathlib import Path

# Public HTTPS base. Deliberately NOT the s3:// form - the FTW docs
# give two different S3 bases (".../ftw/global-data/..." in the code
# sample, ".../tge-labs/ftw-global-data/..." in the storage note) and
# the HTTPS base is the one they document as canonical.
HTTPS_BASE = "https://data.source.coop/ftw/global-data"
VECTORS = f"{HTTPS_BASE}/predictions/vectors"

# Where the discovered partition layout is remembered, so the probe
# runs once rather than on every analysis.
CACHE_NAME = "ftw_partitions.json"

# A 38 km circle can contain tens of thousands of parcels. Cap what
# we pull into memory - the server is small and an unbounded read is
# how the report build already died once.
MAX_PARCELS = 20000

# Permissive on purpose: see the smallholder caveat above.
DEFAULT_MIN_CONFIDENCE = 0


def _cache_path():
    from config import PROJECT_ROOT
    return PROJECT_ROOT / "data" / CACHE_NAME


def _connect(memory_limit="256MB", remote=True):
    """A DuckDB connection set up for remote GeoParquet.

    httpfs is loaded only when the target is remote, and its proxy
    settings are neutralised first. DuckDB parses http_proxy eagerly
    and a malformed value raises on EVERY query - including reads of
    a plain local file - so an unrelated proxy variable in the
    server's environment would take field parcels down with an error
    that points nowhere near the real cause.
    """
    import os

    import duckdb

    # Neutralise proxy variables for the duration of the connection.
    # DuckDB parses http_proxy when httpfs loads, and httpfs is
    # AUTO-loaded by read_parquet - so a malformed value breaks even
    # a local file read, with an error naming a proxy the query never
    # needed. Clearing the setting after connecting is too late.
    saved = {k: os.environ.pop(k, None)
             for k in ("http_proxy", "https_proxy",
                       "HTTP_PROXY", "HTTPS_PROXY")}
    try:
        con = duckdb.connect()
        # No spatial extension: the query filters on bbox columns and
        # geometry comes back as raw WKB, decoded by shapely. One
        # less download to fail on a locked-down server.
        if remote:
            try:
                con.execute("INSTALL httpfs; LOAD httpfs;")
            except Exception:
                pass      # local/cached reads still work without it
        for stmt in ("SET http_proxy='';",
                     "SET http_proxy_username='';",
                     "SET http_proxy_password='';"):
            try:
                con.execute(stmt)
            except Exception:
                pass
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    # The box has 1 GB. Let DuckDB spill rather than be OOM-killed.
    con.execute(f"SET memory_limit='{memory_limit}';")
    try:
        con.execute("SET enable_progress_bar=false;")
    except Exception:
        pass
    return con


def _is_remote(glob):
    return str(glob).startswith(("http://", "https://", "s3://"))


# ------------------------------------------------------------------
# Discovery
# ------------------------------------------------------------------
# India is one of the nine countries FTW splits by admin subdivision,
# and the docs show only the single-file case (France). Rather than
# guess the Indian layout and fail silently at query time, probe a
# short list of candidates once and record what actually answered.

CANDIDATE_ROOTS = [
    f"{VECTORS}/alpha/results-by-admin-conf",
    f"{VECTORS}/results-by-admin-conf",
    f"{VECTORS}/alpha/results-by-country-conf",
]

CANDIDATE_PATTERNS = [
    "admin:country_code=IN/*.parquet",
    "admin:country_code=IN/**/*.parquet",
    "admin:country_code=IN/India.parquet",
    "country_code=IN/*.parquet",
]


def discover(timeout_s=120):
    """Find the India partition. Returns a dict describing the probe.

    Always returns - never raises - and always says what it tried,
    because a silent failure here would surface later as an empty map
    layer with no explanation.
    """
    out = {"ok": False, "glob": None, "columns": [], "tried": [],
           "error": None, "checked_at": int(time.time())}
    try:
        con = _connect()
    except Exception as e:
        out["error"] = (f"DuckDB is not available on the server "
                        f"({e.__class__.__name__}: {e}). Add 'duckdb' "
                        f"to requirements.txt and restart.")
        return out

    started = time.time()
    for root in CANDIDATE_ROOTS:
        for pat in CANDIDATE_PATTERNS:
            if time.time() - started > timeout_s:
                out["error"] = "Probe timed out."
                return out
            glob = f"{root}/{pat}"
            try:
                cols = con.execute(
                    f"SELECT * FROM read_parquet('{glob}') LIMIT 0"
                ).description
                out["glob"] = glob
                out["columns"] = [c[0] for c in (cols or [])]
                out["ok"] = True
                out["tried"].append({"glob": glob, "result": "OK"})
                _save_cache(out)
                return out
            except Exception as e:
                out["tried"].append(
                    {"glob": glob,
                     "result": f"{e.__class__.__name__}: "
                               f"{str(e)[:160]}"})
    out["error"] = ("None of the candidate FTW paths answered. The "
                    "dataset layout may have changed; the probe log "
                    "below shows exactly what was attempted.")
    return out


def _save_cache(info):
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(info, indent=2), encoding="utf-8")
    except Exception:
        pass


def cached_layout():
    try:
        p = _cache_path()
        if p.exists():
            info = json.loads(p.read_text(encoding="utf-8"))
            return info if info.get("ok") else None
    except Exception:
        pass
    return None


def available():
    return cached_layout() is not None


# ------------------------------------------------------------------
# Query
# ------------------------------------------------------------------
def _bbox(lat, lon, radius_km, margin=1.05):
    """Degree bbox around the point. Latitude-corrected in longitude.

    The margin matters: a bbox exactly the circle's diameter clips
    parcels that straddle the edge, and those are then lost before
    the circle intersection runs. 5% costs nothing on a ranged read
    and keeps edge parcels available for the proper clip.
    """
    import math
    r = radius_km * margin
    dlat = r / 111.32
    dlon = r / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _bbox_predicate(cols, minx, miny, maxx, maxy):
    """SQL that keeps rows whose bbox overlaps ours, if we can.

    GeoParquet 1.1 usually stores a struct column `bbox` with
    xmin/ymin/xmax/ymax; some writers emit flat columns instead.
    Returns None when neither is present, in which case we fall back
    to reading and clipping in GeoPandas rather than failing.
    """
    if "bbox" in cols:
        return (f"bbox.xmin <= {maxx} AND bbox.xmax >= {minx} AND "
                f"bbox.ymin <= {maxy} AND bbox.ymax >= {miny}")
    flat = {"xmin", "ymin", "xmax", "ymax"}
    if flat <= set(cols):
        return (f"xmin <= {maxx} AND xmax >= {minx} AND "
                f"ymin <= {maxy} AND ymax >= {miny}")
    return None


def parcels(lat, lon, radius_km, year=None,
            min_confidence=DEFAULT_MIN_CONFIDENCE,
            max_parcels=MAX_PARCELS):
    """Field parcels intersecting the analysis circle.

    Returns (GeoDataFrame, info). info always explains what happened,
    including when nothing came back, so an empty layer can never be
    mistaken for "there are no fields here".
    """
    import geopandas as gpd
    import pandas as pd
    from shapely import wkb

    info = {"source": "Fields of The World (FTW) global, CC-BY-4.0",
            "note": None, "count": 0, "capped": False,
            "min_confidence": min_confidence, "year": year}

    layout = cached_layout()
    if not layout:
        info["note"] = ("Field parcels are not set up yet - the FTW "
                        "dataset layout has not been discovered on "
                        "this server. Press 'Find field parcel data' "
                        "once to probe it.")
        return gpd.GeoDataFrame(), info

    minx, miny, maxx, maxy = _bbox(lat, lon, radius_km)
    glob = layout["glob"]
    cols = set(layout.get("columns") or [])

    # Spatial filter WITHOUT the spatial extension.
    #
    # GeoParquet stores geometry as WKB, and fiboa/GeoParquet 1.1
    # files carry bbox columns for exactly this. Filtering on those
    # is plain SQL: it needs no extension download (a small server
    # with restricted egress cannot always fetch spatial.duckdb_
    # extension), and it prunes whole row groups, so it is faster
    # than ST_Intersects as well. The exact circle clip happens in
    # GeoPandas below, where it belongs.
    bbox_expr = _bbox_predicate(cols, minx, miny, maxx, maxy)
    where = []
    if bbox_expr:
        where.append(bbox_expr)
    if "confidence" in cols and min_confidence:
        where.append(f"confidence >= {float(min_confidence)}")
    if year and "determination:datetime" in cols:
        where.append(f'EXTRACT(year FROM "determination:datetime") '
                     f'= {int(year)}')
    if not where:
        where.append("TRUE")

    select = ["geometry AS wkb"]
    for c, alias in (("confidence", "confidence"),
                     ("metrics:area", "area_m2"),
                     ("id", "ftw_id")):
        if c in cols:
            select.append(f'"{c}" AS {alias}')

    sql = (f"SELECT {', '.join(select)} "
           f"FROM read_parquet('{glob}') "
           f"WHERE {' AND '.join(where)} "
           f"LIMIT {int(max_parcels) + 1}")

    try:
        con = _connect(remote=_is_remote(glob))
        df = con.execute(sql).df()
    except Exception as e:
        info["note"] = (f"Field parcels could not be read: "
                        f"{e.__class__.__name__}: {str(e)[:200]}. "
                        f"Every other layer is unaffected.")
        return gpd.GeoDataFrame(), info

    if df.empty:
        info["note"] = ("FTW returned no parcels for this circle. "
                        "That can mean genuinely unfielded land "
                        "(forest, scrub, water) - or that the model "
                        "did not resolve smallholder plots here. It "
                        "does NOT mean there is no farming.")
        return gpd.GeoDataFrame(), info

    if len(df) > max_parcels:
        df = df.iloc[:max_parcels]
        info["capped"] = True
        # Deliberately does not promise a final count: the cap is
        # applied to the query, then the circle clip removes more, so
        # "showing the first N" would be wrong by the time you read it.
        info["note"] = (f"This circle holds more than {max_parcels:,} "
                        f"parcels. The read was capped at that point "
                        f"and then clipped to the circle, so every "
                        f"parcel figure below is a FLOOR - the real "
                        f"count and area are higher. Reduce the "
                        f"radius for a complete count.")

    try:
        geom = [wkb.loads(bytes(b)) for b in df["wkb"]]
    except Exception as e:
        info["note"] = f"Parcel geometry could not be decoded: {e}"
        return gpd.GeoDataFrame(), info

    gdf = gpd.GeoDataFrame(
        df.drop(columns=["wkb"]), geometry=geom, crs="EPSG:4326")

    # The bbox is a square; the analysis area is a circle. Clip so the
    # count matches what the rest of the app measured.
    try:
        from shapely.geometry import Point
        import math
        centre = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
        utm = centre.estimate_utm_crs()
        circle = centre.to_crs(utm).buffer(radius_km * 1000)
        keep = gdf.to_crs(utm).intersects(circle.iloc[0])
        gdf = gdf[keep.values].reset_index(drop=True)
    except Exception:
        pass                     # bbox result is still usable

    info["count"] = len(gdf)
    return gdf, info


def summary(gdf, info):
    """Headline numbers for the panel and the report."""
    out = {"parcels": 0, "total_ac": None, "median_ac": None,
           "p90_ac": None, "confidence_median": None,
           "note": info.get("note"), "capped": info.get("capped"),
           "source": info.get("source")}
    if gdf is None or len(gdf) == 0:
        return out

    SQM_PER_ACRE = 4046.8564224
    out["parcels"] = len(gdf)
    try:
        if "area_m2" in gdf.columns and gdf["area_m2"].notna().any():
            ac = gdf["area_m2"] / SQM_PER_ACRE
        else:
            ac = gdf.to_crs(gdf.estimate_utm_crs()).area / SQM_PER_ACRE
        out["total_ac"] = round(float(ac.sum()), 1)
        out["median_ac"] = round(float(ac.median()), 2)
        out["p90_ac"] = round(float(ac.quantile(0.9)), 2)
    except Exception:
        pass
    try:
        if "confidence" in gdf.columns:
            out["confidence_median"] = round(
                float(gdf["confidence"].median()), 1)
    except Exception:
        pass
    return out


def caveat():
    """The sentence that must travel with every parcel figure."""
    return (
        "FTW parcels are remote-sensing field units, not legal "
        "parcels - one survey number may cover several of these, or "
        "none. They carry no survey number and say nothing about "
        "ownership; only the Karnataka revenue record (Dishaank / "
        "Bhoomi RTC) does that. The model was trained mostly outside "
        "smallholder systems, so small Karnataka plots may be merged "
        "or missed and tend to score low confidence.")
