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
import re
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
                     "SET http_proxy_password='';",
                     # Harmless if unused; needed the moment any path
                     # does contain a wildcard.
                     "SET allow_asterisks_in_http_paths=true;"):
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

# The bucket behind data.source.coop. Listing it is the only honest
# way to find India's files: plain HTTP has no directory listing, so
# DuckDB cannot glob over it ("Globs for generic HTTP file are not
# supported"), and guessing filenames produced a 404 - India is one
# of the nine countries FTW splits by admin subdivision, so there is
# no single India.parquet to guess at.
# PATH-STYLE, not virtual-hosted style. The bucket is called
# "us-west-2.opendata.source.coop" and that name CONTAINS DOTS, so
# the virtual-hosted host
# "us-west-2.opendata.source.coop.s3.amazonaws.com" is not covered by
# AWS's wildcard certificate - "*.s3.amazonaws.com" matches exactly
# one label. TLS then fails before a single request is sent, which is
# precisely the SSLError the first live probe hit. Path style keeps
# the host as plain s3.us-west-2.amazonaws.com, which the cert covers.
S3_ENDPOINT = "https://s3.us-west-2.amazonaws.com"
S3_BUCKET = "us-west-2.opendata.source.coop"
S3_BUCKET_URL = f"{S3_ENDPOINT}/{S3_BUCKET}"

# Prefixes to list under, in order. The FTW docs give two different
# storage bases, so both are tried rather than assumed.
CANDIDATE_PREFIXES = [
    "ftw/global-data/predictions/vectors/alpha/results-by-admin-conf/",
    "ftw/global-data/predictions/vectors/results-by-admin-conf/",
    "tge-labs/ftw-global-data/predictions/vectors/alpha/"
    "results-by-admin-conf/",
    "tge-labs/ftw-global-data/predictions/vectors/"
    "results-by-admin-conf/",
]

# How India's partition might be spelled in the key.
INDIA_MARKERS = ("country_code=IN/", "country_code=IND/", "/India")


def _list_bucket(prefix, max_keys=4000, timeout=60):
    """Anonymous S3 ListObjectsV2 over HTTPS. Returns object keys."""
    import xml.etree.ElementTree as ET

    import requests

    keys, token = [], None
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    while True:
        params = {"list-type": "2", "prefix": prefix,
                  "max-keys": str(min(1000, max_keys))}
        if token:
            params["continuation-token"] = token
        r = requests.get(S3_BUCKET_URL, params=params, timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for c in root.findall(f"{ns}Contents"):
            k = c.findtext(f"{ns}Key")
            if k:
                keys.append(k)
        if len(keys) >= max_keys:
            break
        if root.findtext(f"{ns}IsTruncated") != "true":
            break
        token = root.findtext(f"{ns}NextContinuationToken")
        if not token:
            break
    return keys


def discover(timeout_s=180):
    """Find India's FTW files by LISTING the bucket, not guessing.

    Always returns - never raises - and always records what it tried,
    because a silent failure here surfaces later as an empty map
    layer with no explanation.
    """
    out = {"ok": False, "glob": None, "files": [], "columns": [],
           "tried": [], "error": None, "checked_at": int(time.time())}

    started = time.time()
    for prefix in CANDIDATE_PREFIXES:
        if time.time() - started > timeout_s:
            out["error"] = "Probe timed out while listing the bucket."
            return out
        try:
            keys = _list_bucket(prefix)
        except Exception as e:
            out["tried"].append(
                {"glob": f"list {prefix}",
                 "result": f"{e.__class__.__name__}: {str(e)[:150]}"})
            continue

        if not keys:
            out["tried"].append({"glob": f"list {prefix}",
                                 "result": "no objects under prefix"})
            continue

        india = [k for k in keys
                 if k.endswith(".parquet")
                 and any(m in k for m in INDIA_MARKERS)]
        if not india:
            sample = ", ".join(k.rsplit("/", 1)[-1]
                               for k in keys[:3]) or "-"
            out["tried"].append(
                {"glob": f"list {prefix}",
                 "result": f"{len(keys)} objects, none matched India "
                           f"(e.g. {sample})"})
            continue

        out["tried"].append(
            {"glob": f"list {prefix}",
             "result": f"listed OK - {len(india)} India file(s)"})

        # Two ways to address the same object. Try each on the first
        # file and keep whichever actually reads, rather than
        # assuming - the docs disagree about the storage base, and
        # the CDN and the bucket can behave differently.
        for form, build in (
                ("path-style S3", lambda k: f"{S3_BUCKET_URL}/{k}"),
                ("data.source.coop",
                 lambda k: f"https://data.source.coop/{k}")):
            urls = [build(k) for k in india]
            try:
                con = _connect(remote=True)
                cols = con.execute(
                    f"SELECT * FROM read_parquet({urls[:1]!r}) LIMIT 0"
                ).description
            except Exception as e:
                out["tried"].append(
                    {"glob": urls[0],
                     "result": f"{form}: unreadable - "
                               f"{e.__class__.__name__}: "
                               f"{str(e)[:130]}"})
                continue

            out["files"] = urls
            out["glob"] = urls[0] if len(urls) == 1 else None
            out["columns"] = [c[0] for c in (cols or [])]
            out["url_form"] = form
            out["ok"] = True
            out["tried"].append(
                {"glob": urls[0],
                 "result": f"{form}: OK - readable"})
            _save_cache(out)
            return out

    out["error"] = (
        "Could not locate India's FTW files. Plain HTTP has no "
        "directory listing, so the bucket is listed directly instead "
        "- the log below shows each prefix tried and what came back. "
        "Check them against https://source.coop/ftw/global-data")
    return out


def _save_cache(info):
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(info, indent=2), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------------
# Per-file extent index
# ------------------------------------------------------------------
# India's FTW partition is 55 separate files, one per admin unit
# (IN_KA is Karnataka, IN_TN Tamil Nadu, and so on). Without this
# index every query opens all 55 over the network. The first live
# run did exactly that and froze the browser tab - a 38 km circle in
# Chamarajanagar has no business opening Ladakh's parquet.
#
# The index is built from the PARQUET FOOTER, not the data: DuckDB's
# parquet_metadata() reads only the trailing metadata block and
# hands back per-row-group min/max statistics for each column. So
# indexing 55 files costs 55 small ranged reads, once, and is then
# cached to disk beside the layout.
#
# Filenames are deliberately NOT parsed to guess a state. The FTW
# admin codes include entries like IN_01, IN_B, IN_P5 and IN_GB whose
# meaning is not documented anywhere I can verify, and a wrong guess
# would silently drop real parcels. Measured extents cannot be wrong
# in that way.

def _footer_extent(con, url):
    """(minx, miny, maxx, maxy) from the parquet footer, or None.

    None means "could not determine" and is treated as "might
    overlap" by the caller. Failing safe here matters: excluding a
    file we could not index would drop parcels invisibly, which is
    the exact class of silent failure this app keeps having to undo.
    """
    try:
        rows = con.execute(
            "SELECT path_in_schema, stats_min, stats_max "
            "FROM parquet_metadata(?) "
            "WHERE lower(path_in_schema) LIKE '%min' "
            "   OR lower(path_in_schema) LIKE '%max'",
            [url]).fetchall()
    except Exception:
        return None

    acc = {}
    for path, smin, smax in rows:
        # DuckDB writes a struct field's path as "bbox, xmin" - comma
        # and space, NOT a dot. Splitting on "." (the obvious guess,
        # and my first one) matches nothing and quietly yields an
        # unindexed file. Take the trailing token whatever separates
        # it, so a flat "xmin" column works identically.
        m = re.search(r"([xy](?:min|max))\s*$", str(path).lower())
        if not m:
            continue
        leaf = m.group(1)
        for val in (smin, smax):
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            lo, hi = acc.get(leaf, (v, v))
            acc[leaf] = (min(lo, v), max(hi, v))

    if not {"xmin", "xmax", "ymin", "ymax"} <= set(acc):
        return None
    # Widest reading of each side - the union across row groups.
    return (acc["xmin"][0], acc["ymin"][0],
            acc["xmax"][1], acc["ymax"][1])


# How many files to measure in one go, and for how long. Both are
# needed. The count keeps a fast link from doing too much work; the
# clock keeps a slow link from hanging regardless of count. The live
# server froze twice before these existed.
INDEX_BATCH = 8
INDEX_BUDGET_S = 25


def _failed_list(layout):
    """extents_failed as a list of URLs, whatever shape it is on disk.

    An earlier build of this module wrote extents_failed as a COUNT.
    A cache file left behind by that build would make len() raise and
    take the whole Field Parcels tab down with a TypeError that names
    nothing useful. Migrating in place is two lines; debugging that
    crash from a screenshot is not.
    """
    v = layout.get("extents_failed")
    if isinstance(v, list):
        return list(v)
    return []                    # int, None or anything else -> start over


def index_progress(layout=None):
    """(measured, unmeasurable, total) for the extent index."""
    layout = layout or cached_layout() or {}
    files = layout.get("files") or []
    ext = layout.get("extents") or {}
    return len(ext), len(_failed_list(layout)), len(files)


def build_extent_index(layout=None, batch=INDEX_BATCH,
                       budget_s=INDEX_BUDGET_S, progress=None):
    """Measure the next tranche of file extents and cache them.

    INCREMENTAL BY DESIGN. Measuring all 55 India files in one
    foreground call froze the live server twice - each measurement is
    a round trip from Mumbai to Oregon, and 55 of them do not fit
    inside a web request no matter how small each read is.

    So this measures at most `batch` files or `budget_s` seconds,
    whichever comes first, and SAVES AFTER EVERY FILE. A call that is
    killed mid-way still leaves its work behind, and the next call
    picks up where it stopped. Repeated calls converge on a complete
    index without any single call being slow.

    Returns the layout. `progress(done, total)` is called between
    files if supplied, so the UI can show a bar instead of a spinner.
    """
    layout = layout or cached_layout()
    if not layout:
        return None
    files = layout.get("files") or []
    if not files:
        return layout

    extents = layout.get("extents") or {}
    failed = _failed_list(layout)
    todo = [u for u in files
            if u not in extents and u not in failed]
    if not todo:
        return layout

    try:
        con = _connect(remote=True)
    except Exception:
        return layout

    started = time.time()
    for n, u in enumerate(todo[:max(1, int(batch))]):
        if n and time.time() - started > budget_s:
            break
        ext = _footer_extent(con, u)
        if ext is None:
            # Remembered as unmeasurable so it is not retried on
            # every call forever - but see _files_for_bbox: it is
            # still READ, so this costs speed, never data.
            failed.append(u)
        else:
            extents[u] = [round(v, 4) for v in ext]
        layout["extents"] = extents
        layout["extents_failed"] = failed
        _save_cache(layout)          # after every file, deliberately
        if progress:
            try:
                progress(len(extents) + len(failed), len(files))
            except Exception:
                pass
    return layout


def _files_for_bbox(layout, minx, miny, maxx, maxy):
    """Files whose extent overlaps this bbox, plus what was skipped.

    Returns (files, span, pending) where `pending` counts files whose
    extent is not yet measured. Those are INCLUDED in the read - an
    incomplete index costs speed, never data - and `pending` is
    reported to the user so a slow first run explains itself instead
    of looking like a hang.
    """
    files = layout.get("files") or []
    extents = layout.get("extents") or {}
    if not extents:
        return files, None, len(files)

    hit, pending = [], 0
    for u in files:
        e = extents.get(u)
        if not e:
            hit.append(u)          # unknown extent - keep it
            pending += 1
            continue
        fx0, fy0, fx1, fy1 = e
        if fx0 <= maxx and fx1 >= minx and fy0 <= maxy and fy1 >= miny:
            hit.append(u)
    if not hit:
        # Nothing overlaps. That is a real answer, not an error, but
        # returning an empty file list to read_parquet would raise -
        # so say so explicitly instead.
        return [], "no-overlap", 0
    return hit, f"{len(hit)} of {len(files)}", pending


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
    # A concrete list of file URLs, never a glob: plain HTTP has no
    # directory listing, so DuckDB cannot expand a wildcard against
    # it. discover() resolves the real filenames once.
    files = layout.get("files") or (
        [layout["glob"]] if layout.get("glob") else [])
    if not files:
        info["note"] = ("The saved FTW layout has no files in it. "
                        "Press 'Find field parcel data' again.")
        return gpd.GeoDataFrame(), info
    glob = files[0]
    cols = set(layout.get("columns") or [])

    # Narrow the 55 admin files to the handful this circle can touch.
    #
    # The index is NOT built here. Doing that made a query silently
    # responsible for up to 55 remote round trips and froze the
    # server; indexing is now an explicit, bounded, resumable step in
    # the panel. A query uses whatever index exists and reads the
    # rest, so it is always correct and gets faster as the index
    # fills in.
    files, span, pending = _files_for_bbox(
        layout, minx, miny, maxx, maxy)
    info["files_scanned"] = span
    info["files_pending"] = pending
    if span == "no-overlap":
        info["note"] = (
            "No FTW admin file covers this circle. That means the "
            "point is outside the area FTW published for India - not "
            "that the land is unfarmed.")
        return gpd.GeoDataFrame(), info
    glob = files[0]

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

    # read_parquet accepts a list, so all of India's admin partitions
    # are scanned in one query - bbox pruning means only the byte
    # ranges covering this circle are actually fetched.
    sql = (f"SELECT {', '.join(select)} "
           f"FROM read_parquet({files!r}) "
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


def _num(value, places):
    """A rounded float, or None if it is not a real number.

    pandas returns NaN from median() on an all-empty column, and
    float(nan) succeeds, so a NaN sails through any `is not None`
    guard and reaches the screen as the word "nan". That reads like a
    measurement and is not one. Anything non-finite becomes None here
    so the UI shows an honest gap instead.
    """
    import math
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, places) if math.isfinite(v) else None


def summary(gdf, info):
    """Headline numbers for the panel and the report."""
    out = {"parcels": 0, "total_ac": None, "median_ac": None,
           "p90_ac": None, "confidence_median": None,
           "confidence_published": False,
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
        out["total_ac"] = _num(ac.sum(), 1)
        out["median_ac"] = _num(ac.median(), 2)
        out["p90_ac"] = _num(ac.quantile(0.9), 2)
    except Exception:
        pass
    try:
        if "confidence" in gdf.columns:
            # Distinguish "FTW published no confidence for this
            # partition" from "we failed to compute it". The first is
            # a fact about the data worth telling the user; the
            # second would be a bug. Both used to print "nan".
            out["confidence_published"] = bool(
                gdf["confidence"].notna().any())
            out["confidence_median"] = _num(
                gdf["confidence"].median(), 1)
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
