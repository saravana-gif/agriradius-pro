"""Fail the build when an Earth Engine asset is wrapped in the wrong type.

Why this exists
---------------
Earth Engine is lazy. `ee.Image("ESA/WorldCover/v200")` constructs
without complaint even though WorldCover is published as an
ImageCollection, and the mistake only surfaces much later as a failed
tile - which the UI shows as a bare "(unavailable)" layer. That is
exactly how six irrigation layers went dark: the cropland mask they all
share was built on a wrongly-wrapped WorldCover, and the try/except
around it caught nothing because nothing had been evaluated yet.

This check is static: it greps the source for literal asset ids and
compares the wrapper used against the type published in the Earth
Engine catalogue (verified against the catalogue pages, not guessed).
It needs no network and no Earth Engine credentials, so it can run
anywhere - locally, in CI, or before a push.

Run:  python scripts/check_ee_assets.py
Exit: 0 = every wrapper matches, 1 = at least one mismatch.
"""

import ast
import os
import pathlib
import sys

# Verified against the Earth Engine / community catalogue pages.
# "I" = ee.Image, "C" = ee.ImageCollection.
EXPECTED = {
    # Official Earth Engine catalogue
    "COPERNICUS/S1_GRD": "C",
    "COPERNICUS/S2_SR_HARMONIZED": "C",
    "ESA/WorldCereal/2021/MODELS/v100": "C",
    "ESA/WorldCover/v200": "C",       # one image per year - NOT an Image
    "GOOGLE/DYNAMICWORLD/V1": "C",
    "UCSB-CHG/CHIRPS/PENTAD": "C",
    "JRC/GFC2020/V3": "I",
    "JRC/GFC2020_subtypes/V1": "I",
    "JRC/GSW1_4/GlobalSurfaceWater": "I",
    "USGS/SRTMGL1_003": "I",
    "WRI/SBTN/naturalLands/v1_1/2020": "I",
    # Community catalogue (awesome-gee-community-catalog). All four are
    # tiled ImageCollections, so they must be mosaicked, never wrapped
    # in ee.Image - use gee.assets.community_image().
    "projects/sat-io/open-datasets/GCI30": "C",
    "projects/sat-io/open-datasets/GFSAD/LGRIP30": "C",
    "projects/sat-io/open-datasets/GFSAD/GCEP30": "C",
    "projects/sat-io/open-datasets/facebook/meta-canopy-height": "C",
}

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {"scripts", "__pycache__", "venv", ".venv", "node_modules"}


def sources():
    """Every .py file in the app, skipping hidden and vendor trees.

    os.walk with onerror ignored: a single unreadable directory (a
    stale mount, a broken symlink) must not stop the check.
    """
    for base, dirs, files in os.walk(ROOT, onerror=lambda e: None):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in SKIP]
        for f in sorted(files):
            if f.endswith(".py"):
                yield pathlib.Path(base) / f


def calls(tree):
    """Yield (line, "Image"|"ImageCollection", asset_id) for ee.X("id").

    Parsed from the AST rather than grepped, so prose in a docstring
    that quotes the wrong call - the comments in gee/assets.py exist
    precisely to explain this bug - is not mistaken for real code.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute)
                and fn.attr in ("Image", "ImageCollection")
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "ee"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            yield node.lineno, fn.attr, arg.value


def problems():
    """Yield (file, line, asset, used, expected) for every mismatch."""
    for path in sources():
        rel = path.relative_to(ROOT)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for n, wrapper, asset in calls(tree):
            want = EXPECTED.get(asset)
            if want is None:
                continue              # not a tracked asset
            used = "I" if wrapper == "Image" else "C"
            if used != want:
                yield rel, n, asset, used, want


def main():
    name = {"I": "ee.Image", "C": "ee.ImageCollection"}
    bad = list(problems())
    for rel, n, asset, used, want in bad:
        print(f"{rel}:{n}: {asset} is a {name[want]}, "
              f"but is wrapped in {name[used]}")
    if bad:
        print(f"\n{len(bad)} wrong wrapper(s). ee.Image on a collection "
              f"builds fine and fails later at tile time - the layer "
              f"just shows as (unavailable).")
        return 1
    print(f"Earth Engine asset wrappers OK "
          f"({len(EXPECTED)} assets checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
