"""Parse a Google Maps link or pasted coordinates into lat/lon.

Handles:
  - plain "lat, lon" (what Google Maps copies for a coordinate)
  - full maps URLs: .../@lat,lon,zoom / ?q=lat,lon / &ll=lat,lon
  - place URLs with the pin encoded as !3dLAT!4dLON
  - shortened links (maps.app.goo.gl / goo.gl/maps) - resolved by
    following the redirect
"""

import re

# The place pin is the true location; @ is the map centre; q/ll are
# query points; plain "lat, lon" is a pasted coordinate.
_PATTERNS = [
    r"[?&]q=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
    r"[?&]ll=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
    r"@(-?\d+\.\d+),(-?\d+\.\d+)",
    r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$",
]


def _valid(lat, lon):
    return -90 <= lat <= 90 and -180 <= lon <= 180


def _extract(text):
    # Place pin: !3d is latitude, !4d is longitude, in any order.
    lat_m = re.search(r"!3d(-?\d+\.\d+)", text)
    lon_m = re.search(r"!4d(-?\d+\.\d+)", text)
    if lat_m and lon_m:
        lat, lon = float(lat_m.group(1)), float(lon_m.group(1))
        if _valid(lat, lon):
            return lat, lon

    for pat in _PATTERNS:
        m = re.search(pat, text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if _valid(lat, lon):
                return lat, lon
    return None


def _resolve_short(url):
    """Follow a shortened Google link to its full URL."""
    import requests
    try:
        r = requests.get(url, allow_redirects=True, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        return r.url
    except Exception:
        return url


def parse_location(text):
    """Return (lat, lon) from a pasted link/coords, or None."""

    if not text or not text.strip():
        return None

    text = text.strip()

    # Direct match first (plain coords or full URL)
    hit = _extract(text)
    if hit:
        return hit

    # Shortened link - resolve the redirect, then re-parse
    if "goo.gl" in text or "maps.app" in text:
        resolved = _resolve_short(text)
        hit = _extract(resolved)
        if hit:
            return hit

    return None
