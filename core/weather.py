"""16-day weather forecast for the selected point (Open-Meteo).

Free API, no key required. Powers harvest/procurement timing:
rain outlook and dry-window detection.
"""

import requests
import streamlit as st

API = "https://api.open-meteo.com/v1/forecast"

DRY_DAY_MM = 2.0  # below this counts as a workable dry day


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
