"""Weather-forecast providers behind one interface.

    from core.sources.forecast import get_provider
    prov = get_provider()                    # FORECAST_PROVIDER secret
    for loc, fc in prov.fetch_many([(lat, lon), ...]):
        fc["daily"], fc["hourly"]            # lists of dicts

Every provider returns the same normalised rows (field names below).
A value the provider did not send is None - never 0 - so "no data"
can never read as "no rain".

LICENSING: Open-Meteo's free API is for non-commercial use. OneRoot's
use is internal advisory, but before alerts feed sales decisions at
scale either buy an Open-Meteo API plan (set OPEN_METEO_API_KEY; the
adapter switches to the customer endpoint) or move to an open-data
provider.
TODO(phase 1+): EcmwfOpenDataProvider - ECMWF open data (IFS 0.25deg,
CC-BY-4.0, commercial use allowed) via the `ecmwf-opendata` package.
It ships GRIB, so it needs eccodes/cfgrib and a point-extraction step;
check memory on the 1 GB box before enabling it.
"""

import logging
import time

import requests

log = logging.getLogger(__name__)

DAILY_FIELDS = ["rain_mm", "rain_prob", "tmax", "tmin", "rh_max",
                "rh_min", "wind_max", "gust_max", "et0_mm",
                "weather_code"]
HOURLY_FIELDS = ["temp", "rh", "dew_point", "rain_mm", "rain_prob",
                 "wind", "gust"]


class ForecastProvider:
    """Interface. `name` is stored with every row."""

    name = "base"

    def fetch_many(self, locations, days=16, hourly_hours=168):
        """Yield ((lat, lon), {"daily": [...], "hourly": [...]}) for
        each location, in order. Raise on a whole-request failure."""
        raise NotImplementedError


class OpenMeteoProvider(ForecastProvider):
    name = "open_meteo"

    FREE_API = "https://api.open-meteo.com/v1/forecast"
    PAID_API = "https://customer-api.open-meteo.com/v1/forecast"
    BATCH = 50            # locations per request
    # Free tier: 600 calls/min, 5,000/h, 10,000/day, where one location
    # with >10 variables or >14 days counts as more than one call (ours
    # ~2). 50 locations every 15 s ~ 400 weighted calls/min; 1,000
    # villages take ~5 min.
    PAUSE_S = 15
    TZ = "Asia/Kolkata"   # dates are IST calendar days

    DAILY = {             # our field -> Open-Meteo daily variable
        "rain_mm": "precipitation_sum",
        "rain_prob": "precipitation_probability_max",
        "tmax": "temperature_2m_max",
        "tmin": "temperature_2m_min",
        "rh_max": "relative_humidity_2m_max",
        "rh_min": "relative_humidity_2m_min",
        "wind_max": "wind_speed_10m_max",
        "gust_max": "wind_gusts_10m_max",
        "et0_mm": "et0_fao_evapotranspiration",
        "weather_code": "weather_code",
    }
    HOURLY = {
        "temp": "temperature_2m",
        "rh": "relative_humidity_2m",
        "dew_point": "dew_point_2m",
        "rain_mm": "precipitation",
        "rain_prob": "precipitation_probability",
        "wind": "wind_speed_10m",
        "gust": "wind_gusts_10m",
    }

    def __init__(self, api_key=None, timeout=60):
        self.api_key = api_key
        self.timeout = timeout

    @staticmethod
    def _rows(block, mapping, time_key):
        times = block.get("time") or []
        out = []
        for i, t in enumerate(times):
            row = {time_key: t}
            for ours, theirs in mapping.items():
                arr = block.get(theirs) or []
                row[ours] = arr[i] if i < len(arr) else None
            out.append(row)
        return out

    def fetch_many(self, locations, days=16, hourly_hours=168):
        from core import usage
        locations = list(locations)
        for start in range(0, len(locations), self.BATCH):
            if start:
                time.sleep(self.PAUSE_S)
            chunk = locations[start:start + self.BATCH]
            params = {
                "latitude": ",".join(f"{lat:.4f}" for lat, _ in chunk),
                "longitude": ",".join(f"{lon:.4f}" for _, lon in chunk),
                "daily": ",".join(self.DAILY.values()),
                "hourly": ",".join(self.HOURLY.values()),
                "forecast_days": days,
                "forecast_hours": hourly_hours,
                "timezone": self.TZ,
            }
            url = self.FREE_API
            if self.api_key:
                url, params["apikey"] = self.PAID_API, self.api_key
            usage.bump("open_meteo", len(chunk))
            r = requests.get(url, params=params, timeout=self.timeout)
            if r.status_code == 429:      # minutely limit: wait it out once
                log.warning("open-meteo 429, retrying in 65 s")
                time.sleep(65)
                r = requests.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            j = r.json()
            # One location -> a dict; several -> a list, same order.
            results = j if isinstance(j, list) else [j]
            if len(results) != len(chunk):
                raise RuntimeError(
                    f"open-meteo returned {len(results)} results for "
                    f"{len(chunk)} locations")
            for loc, res in zip(chunk, results):
                yield loc, {
                    "daily": self._rows(res.get("daily") or {},
                                        self.DAILY, "date"),
                    "hourly": self._rows(res.get("hourly") or {},
                                         self.HOURLY, "time"),
                }


PROVIDERS = {
    "open_meteo": OpenMeteoProvider,
    # "ecmwf_open": EcmwfOpenDataProvider,   # TODO, see module doc
}


def get_provider(name=None):
    """Provider by name, else the FORECAST_PROVIDER secret, else
    Open-Meteo."""
    from core.secrets import get as _sec
    name = name or _sec("FORECAST_PROVIDER") or "open_meteo"
    if name not in PROVIDERS:
        raise ValueError(f"unknown forecast provider {name!r}; "
                         f"have {sorted(PROVIDERS)}")
    if name == "open_meteo":
        return OpenMeteoProvider(api_key=_sec("OPEN_METEO_API_KEY"))
    return PROVIDERS[name]()
