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
    # NO TAMIL NADU ENTRY - and that is a checked fact, not an
    # oversight.
    #
    # I added one pointing at datameet/indian_village_boundaries on
    # the assumption that Tamil Nadu was there because Maharashtra
    # is. It is not. That repository contains exactly:
    #     br, ga, gj, ka, kl, mh, or, rj, sk
    # Bihar, Goa, Gujarat, Karnataka, Kerala, Maharashtra, Odisha,
    # Rajasthan, Sikkim. There is no tn directory, so no filename
    # variant could ever have worked, and the candidate-layout probe
    # I wrote to "let the network settle it" was solving the wrong
    # problem - the directory, not the filename, was the guess.
    #
    # Tamil Nadu's village boundaries therefore have NO identified
    # open source yet. The bundled tamilnadu.csv.xz holds the 9,515
    # villages salvageable from the truncated shapefile - 52% of the
    # state, missing the entire western belt. COVERAGE_GAPS reports
    # that hole and must keep reporting it until a real source
    # exists. It must NOT point anyone at a command that cannot help.
    #
    # Lead worth following: the original shapefile's columns
    # (vilnam_soi, vil_lgd, dist_lgd, gp_code, block_lgd) say it came
    # from a Survey of India / LGD-linked government dataset, and
    # Karnataka's intact file shares that exact schema. Whatever
    # supplied Karnataka can probably supply Tamil Nadu.
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


def _resolve_parts(state, cfg):
    """Pick whichever candidate file layout actually exists.

    I could not verify Tamil Nadu's filenames from here - both
    api.github.com and raw.githubusercontent.com are unreachable from
    the sandbox - so the path is a reasoned guess, not a checked
    fact. Maharashtra is split as mh1/mh2 and Tamil Nadu is a big
    state, so it may well be tn1/tn2 rather than tn.

    Rather than guess once and 404 on the server, list the plausible
    layouts and let the network settle it. Same approach that fixed
    the FTW bucket: stop reading docs, ask the server.
    """
    import requests

    cands = cfg.get("part_candidates")
    if not cands:
        return cfg["parts"]

    for layout in cands:
        ok = True
        for url, _kind in layout:
            try:
                r = requests.head(url, timeout=30, allow_redirects=True)
                if r.status_code != 200:
                    ok = False
                    break
            except Exception:
                ok = False
                break
        if ok:
            names = ", ".join(u.rsplit("/", 1)[-1] for u, _ in layout)
            print(f"{state}: using {names}")
            return layout

    tried = "; ".join(
        ", ".join(u.rsplit("/", 1)[-1] for u, _ in layout)
        for layout in cands)
    raise RuntimeError(
        f"none of the candidate file layouts exist ({tried}). "
        f"Check https://github.com/datameet/indian_village_boundaries "
        f"for the current {state} filenames and update "
        f"part_candidates.")


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


def _convert(state, cfg, force=False):
    import csv

    from shapely import wkt as _wkt
    from shapely.geometry import shape

    out = cfg["out"]

    # A state with a RECORDED coverage gap is never "already
    # complete", whatever its file size. Tamil Nadu's salvaged half
    # is 3.6 MB and my first min_bytes was 3 MB, taken from that
    # salvaged file rather than from the full dataset - so the script
    # looked at the very file it was meant to replace and declared
    # the job done. A size threshold cannot detect a known hole;
    # the hole is recorded, so ask it directly.
    try:
        from data.gis_data import coverage_gap
        known_gap = coverage_gap(state) is not None
    except Exception:
        known_gap = False

    if (out.exists() and out.stat().st_size >= cfg["min_bytes"]
            and not known_gap and not force):
        print(f"{state}: already complete, skipping")
        return
    if known_gap and out.exists():
        print(f"{state}: replacing a known-incomplete file "
              f"({out.stat().st_size:,} bytes)")

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.xz")

    # Resolve BEFORE opening the temp file, so a layout that cannot
    # be found leaves no half-written litter next to the real data.
    parts = _resolve_parts(state, cfg)

    n = 0
    with lzma.open(tmp, "wt", encoding="utf-8", newline="",
                   preset=3) as fh:
        w = csv.writer(fh)
        w.writerow(["village_name", "district_name", "state_name",
                    "village_census_code", "WKT"])
        for url, kind in parts:
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
    """Fetch every source, or only the states named on the command line.

    The filter is not a nicety. Without it, asking for Tamil Nadu also
    re-ran Maharashtra, which failed on a missing dependency and made
    the output look like Tamil Nadu had failed too.
    """
    wanted = [a.strip().lower() for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv

    if wanted:
        unknown = [w for w in wanted if w not in SOURCES]
        if unknown:
            print(f"Unknown state(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"Available: {', '.join(SOURCES)}", file=sys.stderr)
            return 2
        todo = {k: v for k, v in SOURCES.items() if k in wanted}
    else:
        todo = SOURCES

    failed = 0
    for state, cfg in todo.items():
        try:
            _convert(state, cfg, force=force)
        except Exception as e:
            failed += 1
            print(f"{state}: FAILED - {e}", file=sys.stderr)
            if isinstance(e, ImportError) or "No module named" in str(e):
                print(f"    fix: pip install ijson requests",
                      file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    # Propagate the status. main() returning 2 meant nothing while
    # the exit code stayed 0, so a typo'd state name looked like a
    # clean run to anything checking.
    sys.exit(main() or 0)
