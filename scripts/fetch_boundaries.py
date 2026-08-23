"""Fetch missing / partial village-boundary files from public sources.

Runs as a one-shot background subprocess (kicked off by app.py at
startup). Memory-safe by design for the 1 GB server: sources are
STREAMED feature-by-feature with ijson - the whole GeoJSON is never
held in RAM - and written out as the compact csv.xz format the
boundary loader already reads.

Sources (all open data):
  * Telangana  - gggodhwani/telangana_boundaries (Govt. of Telangana
                 Tank Information System), 11,154 villages.
  * Maharashtra- datameet/indian_village_boundaries (community/census),
                 48,926 villages - replaces the partial 12k bundle.

A state is skipped when its existing csv.xz is already at least
MIN_BYTES (i.e. the full dataset is present). Safe to run repeatedly.
"""

import io
import lzma
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BOUND = ROOT / "boundaries"

RAW = "https://raw.githubusercontent.com"

SOURCES = {
    "telangana": {
        "out": BOUND / "telangana_villages" / "telangana.csv.xz",
        "min_bytes": 1_500_000,
        "parts": [
            (f"{RAW}/gggodhwani/telangana_boundaries/master/"
             "village_boundaries.json.xz", "xz"),
        ],
        "fields": lambda p: (str(p.get("DMV_N", "")),
                             str(p.get("D_N", "")).title(),
                             "Telangana",
                             str(p.get("DMV_C", ""))),
    },
    # Tamil Nadu. The shapefile that used to live here was committed
    # TRUNCATED - its header declared 36,736,480 bytes but only
    # 18,804,736 were ever stored, so 8,644 of 18,159 villages were
    # unreadable and any read that reached them died with an opaque
    # fread() error. Worse, that error propagated and took
    # Karnataka's villages down with it on any circle spanning the
    # border. The salvageable 9,515 are shipped as tamilnadu.csv.xz;
    # run this to replace them with the full set.
    "tamilnadu": {
        "out": BOUND / "tamilnadu_villages" / "tamilnadu.csv.xz",
        "min_bytes": 3_000_000,
        "parts": [
            (f"{RAW}/datameet/indian_village_boundaries/master/"
             "tn/tn.geojson", "plain"),
        ],
        "fields": lambda p: (str(p.get("NAME", "")),
                             str(p.get("DISTRICT", "")),
                             "Tamil Nadu",
                             str(p.get("CEN_2001", ""))),
    },
    "maharashtra": {
        "out": BOUND / "maharashtra_villages" / "maharashtra.csv.xz",
        "min_bytes": 7_000_000,
        "parts": [
            (f"{RAW}/datameet/indian_village_boundaries/master/"
             "mh/mh1.geojson", "plain"),
            (f"{RAW}/datameet/indian_village_boundaries/master/"
             "mh/mh2.geojson", "plain"),
        ],
        "fields": lambda p: (str(p.get("NAME", "")),
                             str(p.get("DISTRICT", "")),
                             "Maharashtra",
                             str(p.get("CEN_2001", ""))),
    },
}


def _stream(url, kind):
    """Yield GeoJSON features one by one without holding the whole
    file in RAM: download to a temp file on disk first (disk is
    cheap, RAM is not), then stream-parse it with ijson."""
    import os
    import shutil
    import tempfile

    import ijson
    import requests

    fd, tmp_path = tempfile.mkstemp(suffix=".part")
    try:
        with os.fdopen(fd, "wb") as t:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, t, 1 << 16)
        fh = (lzma.open(tmp_path) if kind == "xz"
              else open(tmp_path, "rb"))
        with fh:
            yield from ijson.items(fh, "features.item")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _convert(state, cfg):
    import csv

    from shapely import wkt as _wkt
    from shapely.geometry import shape

    out = cfg["out"]
    if out.exists() and out.stat().st_size >= cfg["min_bytes"]:
        print(f"{state}: already complete, skipping")
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.xz")

    n = 0
    with lzma.open(tmp, "wt", encoding="utf-8", newline="",
                   preset=3) as fh:
        w = csv.writer(fh)
        w.writerow(["village_name", "district_name", "state_name",
                    "village_census_code", "WKT"])
        for url, kind in cfg["parts"]:
            for feat in _stream(url, kind):
                try:
                    g = shape(feat["geometry"])
                    if not g.is_valid:
                        g = g.buffer(0)
                    g = g.simplify(0.00008, preserve_topology=True)
                    row = cfg["fields"](feat.get("properties") or {})
                    w.writerow(list(row) +
                               [_wkt.dumps(g, rounding_precision=5)])
                    n += 1
                except Exception:
                    continue

    if n < 1000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{state}: only {n} rows - aborting")
    tmp.replace(out)
    print(f"{state}: wrote {n} villages -> {out.name}")


def main():
    for state, cfg in SOURCES.items():
        try:
            _convert(state, cfg)
        except Exception as e:
            print(f"{state}: FAILED - {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
