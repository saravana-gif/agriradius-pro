"""16-day weather forecast for the selected point (Open-Meteo).

Free API, no key required. Powers harvest/procurement timing:
rain outlook and dry-window detection.
"""

import requests
import streamlit as st

API = "https://api.open-meteo.com/v1/forecast"
AQ_API = "https://air-quality-api.open-meteo.com/v1/air-quality"

DRY_DAY_MM = 2.0  # below this counts as a workable dry day

# WMO weather codes -> (text, is_rain)
WMO = {
    0: ("Clear sky", False), 1: ("Mainly clear", False),
    2: ("Partly cloudy", False), 3: ("Overcast", False),
    45: ("Fog", False), 48: ("Rime fog", False),
    51: ("Light drizzle", True), 53: ("Drizzle", True),
    55: ("Dense drizzle", True), 56: ("Freezing drizzle", True),
    57: ("Freezing drizzle", True),
    61: ("Light rain", True), 63: ("Rain", True),
    65: ("Heavy rain", True), 66: ("Freezing rain", True),
    67: ("Freezing rain", True),
    71: ("Light snow", True), 73: ("Snow", True), 75: ("Heavy snow", True),
    77: ("Snow grains", True),
    80: ("Light showers", True), 81: ("Showers", True),
    82: ("Violent showers", True),
    85: ("Snow showers", True), 86: ("Snow showers", True),
    95: ("Thunderstorm", True), 96: ("Thunderstorm + hail", True),
    99: ("Thunderstorm + hail", True),
}


@st.cache_data(ttl=300, show_spinner="Reading live conditions...")
def get_current(lat, lon, _nonce=0):
    """Live current weather at the point. `_nonce` lets a Refresh
    button force a fresh pull past the cache. Returns a dict."""
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m",
            "apparent_temperature", "is_day", "precipitation", "rain",
            "showers", "weather_code", "cloud_cover", "surface_pressure",
            "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
            "shortwave_radiation", "uv_index",
            "soil_temperature_0cm", "soil_moisture_0_to_1cm",
            "evapotranspiration",
        ]),
        "timezone": "auto",
    }
    from core import usage
    usage.bump("open_meteo")
    resp = requests.get(API, params=params, timeout=12)
    resp.raise_for_status()
    c = resp.json().get("current", {})

    code = int(c.get("weather_code", 0) or 0)
    text, is_rain = WMO.get(code, ("-", False))
    precip = float(c.get("precipitation", 0) or 0)

    return {
        "time": c.get("time", ""),
        "temp": c.get("temperature_2m"),
        "feels_like": c.get("apparent_temperature"),
        "humidity": c.get("relative_humidity_2m"),
        "wind_speed": c.get("wind_speed_10m"),
        "wind_gust": c.get("wind_gusts_10m"),
        "wind_dir": c.get("wind_direction_10m"),
        "cloud_cover": c.get("cloud_cover"),
        "pressure": c.get("surface_pressure"),
        "solar": c.get("shortwave_radiation"),   # W/m^2
        "uv": c.get("uv_index"),
        "soil_temp": c.get("soil_temperature_0cm"),
        "soil_moisture": c.get("soil_moisture_0_to_1cm"),  # m3/m3
        "et": c.get("evapotranspiration"),        # mm (hourly)
        "precip": precip,
        "rain": float(c.get("rain", 0) or 0),
        "showers": float(c.get("showers", 0) or 0),
        "is_day": bool(c.get("is_day", 1)),
        "code": code,
        "condition": text,
        "is_raining": is_rain or precip > 0,
    }


@st.cache_data(ttl=1800, show_spinner=False)
def get_air_quality(lat, lon, _nonce=0):
    """Live particulates (PM2.5 / PM10) and US AQI. Returns dict or
    None if unavailable."""
    try:
        params = {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "current": "pm2_5,pm10,us_aqi",
            "timezone": "auto",
        }
        resp = requests.get(AQ_API, params=params, timeout=12)
        resp.raise_for_status()
        c = resp.json().get("current", {})
        return {"pm2_5": c.get("pm2_5"), "pm10": c.get("pm10"),
                "us_aqi": c.get("us_aqi")}
    except Exception:
        return None


def drying_assessment(cur):
    """Rate sun-drying suitability (copra/grain/produce) from live
    conditions. Returns (label, score_0_100, reasons list)."""
    if cur is None:
        return ("Unknown", 0, [])

    if cur.get("is_raining") or (cur.get("precip") or 0) > 0:
        return ("Not suitable - wet", 0,
                ["Rain/precipitation right now"])
    if not cur.get("is_day"):
        return ("Night - no sun drying", 10,
                ["Sun not up; use covered/forced drying"])

    temp = cur.get("temp") or 0
    hum = cur.get("humidity") or 100
    solar = cur.get("solar") or 0
    wind = cur.get("wind_speed") or 0
    cloud = cur.get("cloud_cover") or 100

    score = 0
    reasons = []
    # Solar radiation is the biggest driver
    score += min(40, solar / 20)            # 800 W/m2 -> 40
    score += max(0, min(25, (temp - 24) * 3))   # warmer better
    score += max(0, min(20, (70 - hum) * 0.6))  # drier better
    score += min(10, wind * 1.2)                # breeze helps
    score += max(0, min(5, (100 - cloud) * 0.05))
    score = int(min(100, score))

    if solar < 250:
        reasons.append("Low sunlight (cloud/haze)")
    if hum > 70:
        reasons.append("High humidity slows drying")
    if temp < 26:
        reasons.append("Cooler than ideal")
    if wind < 3:
        reasons.append("Little breeze")
    if not reasons:
        reasons.append("Warm, sunny, dry, breezy - good drying")

    label = ("Excellent" if score >= 75 else "Good" if score >= 55
             else "Fair" if score >= 35 else "Poor")
    return (label, score, reasons)


@st.cache_data(ttl=3600, show_spinner="Fetching weather forecast...")
def get_forecast(lat, lon):
    """Return list of daily dicts: date, rain_mm, rain_prob,
    tmax, tmin. Raises on network failure."""

    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "daily": ",".join([
            "precipitation_sum",
            "precipitation_probability_max",
            "temperature_2m_max",
            "temperature_2m_min",
        ]),
        "forecast_days": 16,
        "timezone": "auto",
    }

    from core import usage
    usage.bump("open_meteo")
    resp = requests.get(API, params=params, timeout=15)
    resp.raise_for_status()

    daily = resp.json().get("daily", {})

    days = []
    times = daily.get("time", [])

    for i, date in enumerate(times):

        def val(key):
            arr = daily.get(key, [])
            return arr[i] if i < len(arr) and arr[i] is not None else 0

        days.append({
            "date": date,
            "rain_mm": round(float(val("precipitation_sum")), 1),
            "rain_prob": int(val("precipitation_probability_max")),
            "tmax": round(float(val("temperature_2m_max")), 1),
            "tmin": round(float(val("temperature_2m_min")), 1),
        })

    return days


def analyze_forecast(days):
    """Summary metrics + longest dry window. Returns dict."""

    if not days:
        return None

    week = days[:7]

    rain_7d = round(sum(d["rain_mm"] for d in week), 1)
    rain_16d = round(sum(d["rain_mm"] for d in days), 1)
    rain_days_7d = sum(1 for d in week if d["rain_mm"] >= DRY_DAY_MM)

    # Longest run of dry days in the 16-day window
    best_start, best_len = None, 0
    cur_start, cur_len = None, 0

    for d in days:
        if d["rain_mm"] < DRY_DAY_MM:
            if cur_start is None:
                cur_start = d["date"]
            cur_len += 1
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
        else:
            cur_start, cur_len = None, 0

    tmax = max(d["tmax"] for d in days)
    tmin = min(d["tmin"] for d in days)

    return {
        "rain_7d_mm": rain_7d,
        "rain_16d_mm": rain_16d,
        "rain_days_7d": rain_days_7d,
        "dry_window_start": best_start,
        "dry_window_days": best_len,
        "tmax": tmax,
        "tmin": tmin,
    }
