"""Observed-rain sources for the rain tracker (no Earth Engine).

    ImdRealtimeRain     IMD 0.25 deg gridded daily rain (gauge based),
                        fetched with imdlib's URLs and grid. Primary.
    OpenMeteoPastRain   Open-Meteo `past_days` - model analysis, not
                        gauges, and its free API is non-commercial.
                        Fallback only, and every row says so.
    ChirpsMonthly       CHIRPS v2.0 monthly 0.05 deg, 1981-2025, read
                        point-by-point over HTTP for normals and SPI.

Every value the source did not give is None - never 0 - so a gap can
never read as "no rain".
"""

import datetime
import logging
import time

import requests

log = logging.getLogger(__name__)


def _nearest_valid(grid, lats, lons, lat, lon, missing):
    """Value of the cell containing (lat, lon) from a (lat, lon) grid;
    if that cell is missing (coast, no gauge), the mean of the valid
    cells around it; None if there are none."""
    import numpy as np
    i = int(round((lat - lats[0]) / (lats[1] - lats[0])))
    j = int(round((lon - lons[0]) / (lons[1] - lons[0])))
    if not (0 <= i < grid.shape[0] and 0 <= j < grid.shape[1]):
        return None
    v = float(grid[i, j])
    if missing(v):
        win = grid[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2].ravel()
        ok = [float(x) for x in win if not missing(float(x))]
        return round(float(np.mean(ok)), 2) if ok else None
    return round(v, 2)


class ImdRealtimeRain:
    """IMD real-time gridded daily rainfall (0.25 deg, 135 x 129 grid).

    Day D covers 08:30 IST on D to 08:30 IST on D+1 and is usually
    published the next day. A day IMD has not published yet comes back
    as an empty file -> fetch_day returns None (not an error)."""

    name = "imd"
    TIMEOUT = 60
    RETRIES = 2

    def __init__(self):
        # imdlib owns the URL, grid and file checks, so an IMD URL change
        # is fixed by upgrading imdlib, not by editing this file.
        from imdlib import util
        self._u = util
        self.url = util.REALTIME_URLS["rain"][0]
        self.grid = util.GRIDS[util.REALTIME_GRID["rain"]]
        self.lats, self.lons = self.grid.lat, self.grid.lon

    def fetch_day(self, day):
        """(lat, lon) float32 grid for one date, or None if IMD has not
        published it. Raises when IMD cannot be reached."""
        from core import usage
        u = self._u
        last = None
        for attempt in range(self.RETRIES + 1):
            try:
                usage.bump("imd")
                r = u.post(self.url, {"rain": day.strftime("%d%m%Y")},
                           f"IMD rain {day}", timeout=self.TIMEOUT)
                r.raise_for_status()
                u.check_download_size(len(r.content),
                                      self.grid.file_size(),
                                      f"IMD rain {day}")
                break
            except u.DataNotAvailableError:
                return None
            except (requests.RequestException, u.DownloadError) as e:
                last = e
                time.sleep(3 * (attempt + 1))
        else:
            raise RuntimeError(f"IMD rain {day}: {type(last).__name__}: "
                               f"{str(last)[:200]}")
        import numpy as np
        nlat, nlon = self.grid.shape
        return np.frombuffer(r.content, dtype="<f4").reshape(nlat, nlon)

    def values_at(self, grid, locations):
        """Rain (mm) at each (lat, lon); None where IMD has no value."""
        # -999 marks no data; any negative value is treated the same.
        miss = lambda v: v != v or v < 0  # noqa: E731
        return [_nearest_valid(grid, self.lats, self.lons, lat, lon, miss)
                for lat, lon in locations]


class OpenMeteoPastRain:
    """Fallback: daily precipitation_sum for the last `days` days.

    Calendar days in IST (midnight to midnight), not IMD's 08:30 day,
    and model analysis rather than gauges - so it is stored under its
    own source name and features say when they used it."""

    name = "open_meteo"
    API = "https://api.open-meteo.com/v1/forecast"
    BATCH = 50

    def fetch(self, locations, days=92):
        """{(lat, lon): {iso_date: mm or None}} for past `days` days
        (today excluded: it is not over)."""
        from core import usage
        out = {}
        today = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ).date().isoformat()
        locations = list(locations)
        for s in range(0, len(locations), self.BATCH):
            chunk = locations[s:s + self.BATCH]
            usage.bump("open_meteo", len(chunk))
            r = requests.get(self.API, params={
                "latitude": ",".join(f"{a:.4f}" for a, _ in chunk),
                "longitude": ",".join(f"{b:.4f}" for _, b in chunk),
                "daily": "precipitation_sum", "past_days": min(days, 92),
                "forecast_days": 1, "timezone": "Asia/Kolkata"},
                timeout=60)
            r.raise_for_status()
            j = r.json()
            res = j if isinstance(j, list) else [j]
            if len(res) != len(chunk):
                raise RuntimeError("open-meteo: result count mismatch")
            for loc, one in zip(chunk, res):
                d = one.get("daily") or {}
                times = d.get("time") or []
                vals = d.get("precipitation_sum") or []
                out[loc] = {t: (vals[i] if i < len(vals) else None)
                            for i, t in enumerate(times) if t < today}
        return out


class ChirpsMonthly:
    """CHIRPS v2.0 global monthly totals (mm), 0.05 deg, read per point.

    Tries the cloud-optimised GeoTIFF first (a few small HTTP range
    reads per month) and falls back to the gzipped GeoTIFF. Rasterio is
    already a dependency; nothing is written to disk."""

    name = "chirps"
    BASE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly"
    URLS = (
        "/vsicurl/" + BASE + "/cogs/chirps-v2.0.{y}.{m:02d}.cog",
        "/vsigzip//vsicurl/" + BASE + "/tifs/chirps-v2.0.{y}.{m:02d}.tif.gz",
    )
    GDAL_ENV = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".cog,.tif,.gz",
        "GDAL_HTTP_TIMEOUT": "60",
        "GDAL_HTTP_MAX_RETRY": "2",
        "GDAL_HTTP_RETRY_DELAY": "3",
        "GDAL_CACHEMAX": 64,               # MB
    }

    def __init__(self, urls=None):
        self.urls = urls or self.URLS

    def read_month(self, year, month, locations):
        """[mm or None] per (lat, lon). Raises if no URL could be read."""
        import rasterio
        from core import usage
        last = None
        for tmpl in self.urls:
            path = tmpl.format(y=year, m=month)
            try:
                usage.bump("chirps")
                with rasterio.Env(**self.GDAL_ENV), \
                        rasterio.open(path) as ds:
                    nodata = ds.nodata
                    out = []
                    for (v,) in ds.sample([(lon, lat)
                                           for lat, lon in locations]):
                        v = float(v)
                        bad = (v != v or v < 0
                               or (nodata is not None and v == nodata))
                        out.append(None if bad else round(v, 1))
                    return out
            except Exception as e:      # rasterio raises its own types
                last = e
        raise RuntimeError(f"CHIRPS {year}-{month:02d}: "
                           f"{type(last).__name__}: {str(last)[:200]}")
