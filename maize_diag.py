"""Maize phenology + detection diagnostic.

Run this ON YOUR MACHINE (where Earth Engine is authenticated), from
the project root:

    py maize_diag.py

It authenticates EE with the same service account the app uses
(.streamlit/secrets.toml), then for the target belt prints:

  1. The month-by-month NDVI curve over cropland for 3 seasons - so we
     can SEE the real sowing / peak / harvest timing.
  2. The % of cropland pixels passing each maize gate at several
     threshold settings - so we can see which gate is the bottleneck.

Change LAT / LON / RADIUS_M / YEARS below to test any other region.
"""

import json
import re
import sys
from pathlib import Path

import ee

PROJECT_ID = "agriradius"
SECRETS = Path(__file__).parent / ".streamlit" / "secrets.toml"

# ---- target: change these to test another belt ----
LAT, LON = 11.871990, 77.241518      # Kollegal maize belt
RADIUS_M = 7000
YEARS = [2022, 2023, 2024]
# ----------------------------------------------------


def init_ee():
    """Service account from secrets.toml, else local credentials."""
    try:
        txt = SECRETS.read_text(encoding="utf-8")
        m = (re.search(r"GCP_SERVICE_ACCOUNT\s*=\s*'''(.*?)'''", txt, re.S)
             or re.search(r'GCP_SERVICE_ACCOUNT\s*=\s*"""(.*?)"""', txt, re.S))
        if m:
            info = json.loads(m.group(1))
            creds = ee.ServiceAccountCredentials(
                info["client_email"], key_data=json.dumps(info))
            ee.Initialize(creds, project=PROJECT_ID)
            print("EE ready (service account)")
            return
    except Exception as e:
        print("service-account init failed:", e)
    ee.Initialize(project=PROJECT_ID)
    print("EE ready (local credentials)")


def _mask_clouds(img):
    qa = img.select("QA60")
    m = (qa.bitwiseAnd(1 << 10).eq(0)
         .And(qa.bitwiseAnd(1 << 11).eq(0)))
    return img.updateMask(m)


def _s2(buffer, y):
    return (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(buffer)
            .filterDate(f"{y}-01-01", f"{y}-12-31")
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
            .map(_mask_clouds))


def _ndvi(col):
    return col.map(lambda i: i.normalizedDifference(["B8", "B4"]).rename("NDVI"))


def _cropland(buffer, y):
    dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
          .filterBounds(buffer).filterDate(f"{y}-01-01", f"{y}-12-31"))
    return dw.select("crops").max().gt(0.4)


def monthly_curve(buffer, y, crop_only=True):
    col = _s2(buffer, y)
    mask = _cropland(buffer, y) if crop_only else None
    d = {}
    for mth in range(1, 13):
        start = ee.Date.fromYMD(y, mth, 1)
        sub = _ndvi(col.filterDate(start, start.advance(1, "month")))
        img = ee.Image(ee.Algorithms.If(sub.size().gt(0), sub.median(),
                                        ee.Image(0).rename("NDVI")))
        if mask is not None:
            img = img.updateMask(mask)
        d[mth] = img.reduceRegion(ee.Reducer.mean(), buffer, 40,
                                  bestEffort=True).get("NDVI")
    vals = ee.Dictionary(d).getInfo()
    return {int(k): (round(v, 3) if v is not None else None)
            for k, v in vals.items()}


def _peak(buffer, y, pct=90):
    """p90 NDVI over Jun-Dec - matches the app's new peak measure."""
    col = (_s2(buffer, y)
           .filterDate(f"{y}-06-01", f"{y}-12-31"))
    return _ndvi(col).reduce(ee.Reducer.percentile([pct])).rename("peak")


def _trough(buffer, y, pct=15):
    ndvi = _ndvi(_s2(buffer, y))
    return ndvi.reduce(ee.Reducer.percentile([pct])).rename("trough")


def gate_diag(buffer, y):
    crop = _cropland(buffer, y).selfMask()
    peak = _peak(buffer, y)
    trough = _trough(buffer, y)
    amp = peak.subtract(trough)
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003"))

    total = crop.rename("x").reduceRegion(
        ee.Reducer.count(), buffer, 30, maxPixels=1e12,
        bestEffort=True).get("x")

    # Final combined mask = the app's actual maize rule.
    final = (peak.gte(0.50)
             .And(trough.lt(0.35))
             .And(amp.gte(0.25))
             .And(slope.lte(15)))

    gates = {
        "peak>=0.50": peak.gte(0.50),
        "peak>=0.55": peak.gte(0.55),
        "peak>=0.60": peak.gte(0.60),
        "trough<0.30": trough.lt(0.30),
        "trough<0.35": trough.lt(0.35),
        "amp>=0.25": amp.gte(0.25),
        "amp>=0.28": amp.gte(0.28),
        "slope<=15": slope.lte(15),
        "== FINAL maize ==": final,
    }
    out = {"_cropland_px": total}
    for name, g in gates.items():
        out[name] = (g.rename("x").updateMask(crop).selfMask()
                     .reduceRegion(ee.Reducer.count(), buffer, 30,
                                   maxPixels=1e12, bestEffort=True).get("x"))
    return ee.Dictionary(out).getInfo()


def main():
    init_ee()
    buffer = ee.Geometry.Point([LON, LAT]).buffer(RADIUS_M)

    print("\n" + "=" * 60)
    print("MONTHLY NDVI over cropland (Jan..Dec) - watch for the pulse")
    print("=" * 60)
    for y in YEARS:
        c = monthly_curve(buffer, y, crop_only=True)
        line = "  ".join(f"{m:02d}:{(c[m] if c[m] is not None else 0):.2f}"
                         for m in range(1, 13))
        print(f"{y}  {line}")

    print("\n" + "=" * 60)
    print("GATE PASS RATE over cropland (which gate is the bottleneck?)")
    print("=" * 60)
    for y in YEARS:
        d = gate_diag(buffer, y)
        tot = d.get("_cropland_px") or 1
        print(f"\n-- {y} --  cropland pixels: {tot}")
        for k, v in d.items():
            if k == "_cropland_px":
                continue
            print(f"   {k:14s}: {100*(v or 0)/tot:5.1f}%")


if __name__ == "__main__":
    main()
