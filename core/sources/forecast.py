"""Weather-forecast providers behind one interface.

    from core.sources.forecast import get_provider
    prov = get_provider()                    # FORECAST_PROVIDER secret
    for loc, fc in prov.fetch_many([(lat, lon), ...]):
        fc["daily"], fc["hourly"]            # lists of dicts

Every provider returns the same normalised rows (field names below).
A value the provider did not send is None - never 0 - so "no data"
can never read as "no rain".

LICENSING: ECMWF open data is CC-BY-4.0 - commercial use allowed with
attribution ("Contains ECMWF data"; see ATTRIBUTION). Open-Meteo's free
API is non-commercial, so it is only the fallback: set
OPEN_METEO_API_KEY (a paid plan) to use its customer endpoint.

FORECAST_PROVIDER (secret) picks the order, comma-separated; default
"ecmwf_open,open_meteo": ECMWF first, Open-Meteo if that fails.
"""

import contextlib
import datetime
import io
import logging
import os
import tempfile
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


IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def rh_from_dewpoint(t_c, td_c):
    """Relative humidity (%) from temperature and dew point (deg C),
    Magnus formula (Alduchov & Eskridge 1996)."""
    import math
    a, b = 17.625, 243.04
    rh = 100 * math.exp(a * td_c / (b + td_c) - a * t_c / (b + t_c))
    return round(min(100.0, max(0.0, rh)), 1)


class EcmwfOpenDataProvider(ForecastProvider):
    """ECMWF IFS 0.25 deg open data (CC-BY-4.0), latest 00/12 UTC run
    out to 15 days, read straight from the GRIB2 files.

    Only the fields we use are downloaded (HTTP range reads via the
    files' .index), in blocks of a few steps to a temp file that is
    deleted after reading; each field is decoded one at a time
    (~8 MB) and only the village grid points are kept, so memory stays
    small on the 1 GB box. About 350 fields, ~250 MB a day; ~4 min.

    Days are IST calendar days. Each forecast interval is assigned to
    the IST day holding its midpoint; a day is kept only when its
    intervals cover all 24 h. Hourly rows are 3-hourly (the model's
    output step) for the first 7 days, at IST times (hh:30).
    Not provided: rain_prob (needs the ensemble), wind, gusts, et0_mm,
    weather_code -> None (no rule uses them; each costs ~70 MB a day).
    """

    name = "ecmwf_open"
    # Mirrors, tried in order. AWS throttles index reads (503 Slow Down).
    SOURCES = ("ecmwf", "google", "aws")
    BLOCK = 12                              # steps per download

    def __init__(self, sources=None, workdir=None):
        self.sources = sources or self.SOURCES
        self.workdir = workdir
        self.base_time = None

    @staticmethod
    def plan(hourly_hours=168, last_step=360):
        """[(steps, params)] download blocks."""
        s3 = list(range(3, 145, 3))
        s6 = list(range(150, last_step + 1, 6))
        hourly = ["tp", "2t", "2d"]
        out = [(s3, hourly + ["mx2t3", "mn2t3"]),
               ([s for s in s6 if s <= hourly_hours],
                hourly + ["mx2t6", "mn2t6"]),
               ([s for s in s6 if s > hourly_hours],
                ["tp", "mx2t6", "mn2t6"])]
        return [(st, p) for st, p in out if st]

    def _client(self, source):
        from ecmwf.opendata import Client
        return Client(source=source, model="ifs", resol="0p25",
                      maximum_retries=3, retry_after=10)

    def _download(self, locations, days):
        """{(param, step): [value per location]} and the base time."""
        from core import usage
        last_step = min(360, days * 24)
        errors = []
        for src in self.sources:
            try:
                client = self._client(src)
                base = client.latest(type="fc", stream="oper",
                                     step=last_step, param="tp")
                fields = {}
                fd, path = tempfile.mkstemp(suffix=".grib2",
                                            dir=self.workdir)
                os.close(fd)
                try:
                    for steps, params in self.plan(last_step=last_step):
                        for i in range(0, len(steps), self.BLOCK):
                            usage.bump("ecmwf_open")
                            # multiurl draws tqdm progress bars on
                            # stderr (disable=False is hard-coded) -
                            # noise in the cron log. Log handlers keep
                            # their own stream, so warnings still show.
                            with contextlib.redirect_stderr(io.StringIO()):
                                client.retrieve(
                                    date=base.strftime("%Y%m%d"),
                                    time=base.hour, type="fc",
                                    stream="oper",
                                    step=steps[i:i + self.BLOCK],
                                    param=params, target=path)
                            fields.update(read_points(path, locations))
                finally:
                    os.remove(path)
                return base, fields
            except Exception as e:
                errors.append(f"{src}: {type(e).__name__}: {str(e)[:150]}")
                log.warning("ecmwf open data via %s failed: %s", src, e)
        raise RuntimeError("ECMWF open data unavailable - "
                           + " | ".join(errors))

    def fetch_many(self, locations, days=16, hourly_hours=168):
        locations = list(locations)
        base, fields = self._download(locations, days)
        self.base_time = base
        for k, loc in enumerate(locations):
            pts = {key: vals[k] for key, vals in fields.items()}
            yield loc, to_rows(base, pts, hourly_hours)


def read_points(path, locations):
    """{(shortName, endStep): [value at each (lat, lon)]} from a GRIB
    file on a regular lat/lon grid (nearest grid point)."""
    import eccodes
    out, idx_cache = {}, {}
    with open(path, "rb") as f:
        while True:
            h = eccodes.codes_grib_new_from_file(f)
            if h is None:
                break
            try:
                if eccodes.codes_get(h, "gridType") != "regular_ll":
                    raise ValueError("unexpected GRIB grid type")
                geo = tuple(eccodes.codes_get(h, k) for k in (
                    "latitudeOfFirstGridPointInDegrees",
                    "longitudeOfFirstGridPointInDegrees",
                    "iDirectionIncrementInDegrees",
                    "jDirectionIncrementInDegrees", "Ni", "Nj",
                    "jScansPositively"))
                if geo not in idx_cache:
                    idx_cache[geo] = _grid_index(geo, locations)
                vals = eccodes.codes_get_values(h)
                miss = eccodes.codes_get(h, "missingValue")
                key = (eccodes.codes_get(h, "shortName"),
                       int(eccodes.codes_get(h, "endStep")))
                out[key] = [None if vals[i] == miss else float(vals[i])
                            for i in idx_cache[geo]]
            finally:
                eccodes.codes_release(h)
    return out


def _grid_index(geo, locations):
    lat0, lon0, di, dj, ni, nj, jpos = geo
    idx = []
    for lat, lon in locations:
        j = round((lat - lat0) / dj) if jpos else round((lat0 - lat) / dj)
        i = round(((lon - lon0) % 360) / di) % ni
        if not 0 <= j < nj:
            raise ValueError(f"latitude {lat} outside the GRIB grid")
        idx.append(int(j * ni + i))
    return idx


def _k_to_c(v):
    return None if v is None else round(v - 273.15, 1)


def to_rows(base, pts, hourly_hours=168):
    """One location's {(param, step): value} -> {"daily", "hourly"}."""
    steps = sorted({s for (p, s) in pts if p == "tp"})
    days, prev = {}, 0
    hourly = []
    for s in steps:
        tp0 = 0.0 if prev == 0 else pts.get(("tp", prev))
        tp1 = pts.get(("tp", s))
        rain = (None if tp0 is None or tp1 is None
                else round(max(0.0, (tp1 - tp0) * 1000), 2))
        hrs = s - prev
        mid = base + datetime.timedelta(hours=prev + hrs / 2)
        day = mid.astimezone(IST).date().isoformat()
        d = days.setdefault(day, {"hours": 0, "rain": [], "tmax": [],
                                  "tmin": [], "rh": []})
        d["hours"] += hrs
        d["rain"].append(rain)
        d["tmax"].append(_k_to_c(pts.get((f"mx2t{hrs}", s))))
        d["tmin"].append(_k_to_c(pts.get((f"mn2t{hrs}", s))))
        t, td = _k_to_c(pts.get(("2t", s))), _k_to_c(pts.get(("2d", s)))
        rh = None if t is None or td is None else rh_from_dewpoint(t, td)
        if t is not None:
            vt = (base + datetime.timedelta(hours=s)).astimezone(IST)
            vday = vt.date().isoformat()
            days.setdefault(vday, {"hours": 0, "rain": [], "tmax": [],
                                   "tmin": [], "rh": []})["rh"].append(rh)
            if s <= hourly_hours:
                hourly.append({
                    "time": vt.strftime("%Y-%m-%dT%H:%M"), "temp": t,
                    "rh": rh, "dew_point": td, "rain_mm": rain,
                    "rain_prob": None, "wind": None, "gust": None})
        prev = s

    def _agg(vals, fn):
        vals = [v for v in vals if v is not None]
        return round(fn(vals), 1) if vals else None

    daily = []
    for day in sorted(days):
        d = days[day]
        if d["hours"] != 24:
            continue          # partial first / last day
        daily.append({
            "date": day,
            "rain_mm": (None if any(r is None for r in d["rain"])
                        else round(sum(d["rain"]), 1)),
            "rain_prob": None,
            "tmax": _agg(d["tmax"], max), "tmin": _agg(d["tmin"], min),
            "rh_max": _agg(d["rh"], max), "rh_min": _agg(d["rh"], min),
            "wind_max": None, "gust_max": None,
            "et0_mm": None, "weather_code": None})
    return {"daily": daily, "hourly": hourly}


class FallbackProvider(ForecastProvider):
    """Try providers in order; the first that delivers every location
    wins and its name is stored with the rows."""

    def __init__(self, providers):
        self.providers = providers
        self.name = providers[0].name
        self.base_time = None
        self.errors = []

    def fetch_many(self, locations, days=16, hourly_hours=168):
        locations = list(locations)
        for p in self.providers:
            try:
                got = list(p.fetch_many(locations, days, hourly_hours))
            except Exception as e:
                self.errors.append(f"{p.name}: {type(e).__name__}: "
                                   f"{str(e)[:300]}")
                log.warning("forecast provider %s failed: %s", p.name, e)
                continue
            self.name = p.name
            self.base_time = getattr(p, "base_time", None)
            yield from got
            return
        raise RuntimeError("all forecast providers failed: "
                           + " | ".join(self.errors))


PROVIDERS = {
    "ecmwf_open": EcmwfOpenDataProvider,
    "open_meteo": OpenMeteoProvider,
}

ATTRIBUTION = {
    "ecmwf_open": "ECMWF open data (CC BY 4.0)",
    "open_meteo": "Open-Meteo",
}

DEFAULT_ORDER = "ecmwf_open,open_meteo"


def _make(name):
    from core.secrets import get as _sec
    if name not in PROVIDERS:
        raise ValueError(f"unknown forecast provider {name!r}; "
                         f"have {sorted(PROVIDERS)}")
    if name == "open_meteo":
        return OpenMeteoProvider(api_key=_sec("OPEN_METEO_API_KEY"))
    return PROVIDERS[name]()


def get_provider(name=None):
    """Provider(s) by name ("a" or "a,b"), else the FORECAST_PROVIDER
    secret, else ECMWF open data with Open-Meteo as fallback."""
    from core.secrets import get as _sec
    names = [n.strip() for n in str(
        name or _sec("FORECAST_PROVIDER") or DEFAULT_ORDER).split(",")
        if n.strip()]
    provs = [_make(n) for n in names]
    return provs[0] if len(provs) == 1 else FallbackProvider(provs)
