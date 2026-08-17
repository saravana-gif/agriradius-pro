"""Earth Engine tile URLs that never go stale.

Earth Engine hands out map tiles behind a short-lived token:

    https://earthengine.googleapis.com/v1/projects/<p>/maps/<id>-<token>/tiles/{z}/{x}/{y}

That token EXPIRES. The app caches each layer's tile URL so repeat
views are free, but the cache had no expiry - so some hours after a
restart every overlay quietly started returning

    401 {"error": {"message": "Invalid token: ...", "status": "UNAUTHENTICATED"}}

The browser can't show a 401 tile, so the map looked like the layer
simply wasn't there: no error, no warning, just satellite. Numbers and
reports kept working, because those are computed server-side and never
touch a token.

Two guards live here:

  * `TILE_TTL` - the per-layer caches expire well inside the token's
    lifetime, so URLs are refreshed on their own.
  * `fresh_tile_url()` - before a URL is handed to the browser, one
    real tile is fetched. If the token is dead the cached value is
    dropped and the URL regenerated once. A layer can therefore never
    render blank because of an expired token.

The probe is a single 256x256 request against Google's CDN, so it adds
a few milliseconds and no Earth Engine compute.
"""

import math

import requests

# Refresh cached tile URLs this often (seconds). Comfortably shorter
# than the token lifetime, long enough that panning/zooming and
# re-running analyses stay free.
TILE_TTL = 1200


def _xyz(lat, lon, zoom=10):
    """Slippy-map tile indices for a coordinate."""
    lat = max(min(float(lat), 85.05), -85.05)
    n = 2 ** zoom
    x = int((float(lon) + 180.0) / 360.0 * n)
    rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(rad) + 1 / math.cos(rad))
             / math.pi) / 2.0 * n)
    return zoom, min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_alive(url_format, lat, lon, timeout=6):
    """True if one real tile comes back OK.

    Unknown failures (a network blip, a slow CDN) count as alive - we
    only want to catch the definite 401/403 'token is dead' case, never
    to hide a working layer because a probe timed out.
    """
    if not url_format:
        return False
    try:
        z, x, y = _xyz(lat, lon)
        url = (str(url_format)
               .replace("{z}", str(z))
               .replace("{x}", str(x))
               .replace("{y}", str(y)))
        r = requests.get(url, timeout=timeout)
        if r.status_code in (401, 403, 404):
            return False
        return True
    except Exception:
        return True


def _health(event):
    """Record tile health so the Service health panel can show it."""
    try:
        import streamlit as st
        h = st.session_state.setdefault(
            "tile_health", {"checked": 0, "renewed": 0, "failed": 0})
        h["checked"] += 1
        if event in h:
            h[event] += 1
    except Exception:
        pass


def fresh_tile_url(fn, *args, probe=None, **kwargs):
    """Call a cached tile-URL function and guarantee a live token.

    `fn` is one of the @st.cache_data tile-URL builders. `probe` is the
    (lat, lon) used for the liveness check - defaults to the first two
    positional arguments, which is how every tile function is called.

    Returns None only when the layer genuinely cannot be produced, so
    callers can say so on screen instead of drawing nothing.
    """
    url = fn(*args, **kwargs)
    if not url:
        _health("failed")
        return url

    lat, lon = (probe if probe else (args[0], args[1]))

    if tile_alive(url, lat, lon):
        _health("ok")
        return url

    # Token expired: drop the memoised value and rebuild once.
    try:
        fn.clear()
    except Exception:
        pass
    try:
        url = fn(*args, **kwargs)
    except Exception:
        _health("failed")
        return None

    if url and tile_alive(url, lat, lon):
        _health("renewed")
        return url

    _health("failed")
    return None
