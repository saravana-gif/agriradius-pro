"""Live mandi (APMC) prices from AGMARKNET via data.gov.in.

Daily wholesale prices per market. Prices are Rs per quintal.
API key lives in .streamlit/secrets.toml (never committed to git).
"""

import pandas as pd
import requests
import streamlit as st

RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"
API = f"https://api.data.gov.in/resource/{RESOURCE}"

# Variety-wise DAILY prices archive (agmarknet_new) - 80M+ rows back
# to 2014, so it powers the historical price-trend chart (the current
# resource above only holds today's snapshot).
HIST_RESOURCE = "35985678-0d79-46b4-9ed6-6f13308a1d24"
HIST_API = f"https://api.data.gov.in/resource/{HIST_RESOURCE}"

# Display name -> AGMARKNET commodity name
COMMODITIES = {
    "Turmeric": "Turmeric",
    "Coconut": "Coconut",
    "Banana": "Banana",
    "Maize": "Maize",
    "Dry Chillies": "Dry Chillies",
    "Green Chilli": "Green Chilli",
    "Paddy (Common)": "Paddy(Dhan)(Common)",
    "Sugarcane": "Sugarcane",
    "Arecanut": "Arecanut(Betelnut/Supari)",
    "Ginger (Green)": "Ginger(Green)",
    "Tomato": "Tomato",
    "Onion": "Onion",
}

STATES = ["All India", "Karnataka", "Tamil Nadu", "Kerala",
          "Andhra Pradesh", "Telangana", "Goa", "Maharashtra"]


def _api_key():
    try:
        return st.secrets["DATA_GOV_API_KEY"]
    except Exception:
        return ""


def _cache_dir():
    from config import PROJECT_ROOT
    d = PROJECT_ROOT / "data" / "mandi_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(commodity, state):
    import re
    tag = re.sub(r"[^\w]+", "_", f"{commodity}_{state or 'all'}")
    return _cache_dir() / f"{tag}.csv"


def _fetch(commodity, state, limit, timeout):
    """One raw API call. Returns cleaned DataFrame or raises."""

    key = _api_key()

    if not key:
        raise RuntimeError(
            "No API key. Add DATA_GOV_API_KEY to "
            ".streamlit/secrets.toml")

    params = {
        "api-key": key,
        "format": "json",
        "limit": limit,
        "filters[commodity]": commodity,
    }

    if state and state != "All India":
        params["filters[state]"] = state

    from core import usage
    usage.bump("data_gov")
    resp = requests.get(API, params=params, timeout=timeout)
    resp.raise_for_status()

    records = resp.json().get("records", [])

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).rename(columns={
        "state": "State",
        "district": "District",
        "market": "Market",
        "variety": "Variety",
        "grade": "Grade",
        "arrival_date": "Date",
        "min_price": "Min (Rs/qtl)",
        "max_price": "Max (Rs/qtl)",
        "modal_price": "Modal (Rs/qtl)",
    })

    for c in ["Min (Rs/qtl)", "Max (Rs/qtl)", "Modal (Rs/qtl)"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    cols = ["Market", "District", "State", "Variety", "Grade",
            "Date", "Min (Rs/qtl)", "Max (Rs/qtl)",
            "Modal (Rs/qtl)"]

    df = df[[c for c in cols if c in df.columns]]

    return df.sort_values(
        "Modal (Rs/qtl)", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner="Fetching mandi prices...")
def get_prices(commodity, state=None, limit=100):
    """Latest prices for a commodity. Returns a DataFrame.

    On success, caches to disk. If the government server is slow/down,
    falls back to the last cached prices (df.attrs['note'] explains).
    A smaller limit is used because the AGMARKNET API is much faster
    with fewer rows.
    """

    cache = _cache_path(commodity, state)

    # Fail fast: one short attempt. data.gov.in either answers quickly
    # or is effectively down - a long wait just freezes the button.
    last_err = None
    try:
        df = _fetch(commodity, state, limit, timeout=12)
        try:
            df.to_csv(cache, index=False)
        except Exception:
            pass
        df.attrs["note"] = ""
        return df
    except requests.exceptions.RequestException as e:
        last_err = e

    # Live fetch failed - fall back to cached prices if we have them.
    if cache.exists():
        try:
            import datetime
            df = pd.read_csv(cache)
            when = datetime.datetime.fromtimestamp(
                cache.stat().st_mtime).strftime("%d %b %H:%M")
            df.attrs["note"] = (
                f"Live server unavailable - showing cached prices "
                f"from {when}.")
            return df
        except Exception:
            pass

    raise RuntimeError(
        "data.gov.in did not respond and no cached prices exist yet. "
        "The government server is slow or down - try again shortly. "
        f"({last_err})")


@st.cache_data(ttl=21600, show_spinner="Fetching price history...")
def get_price_history(commodity, state, limit=6000, months=48):
    """Monthly modal-price trend for a commodity in a state.

    Pulls the daily variety-wise archive (2014+) filtered to the
    commodity & state, then aggregates to a monthly median (robust to
    per-market spread). Returns a DataFrame: Month, Modal, Low, High,
    Records. Empty if nothing found. Note: the feed returns markets in
    name order, so this is a representative SAMPLE of the state's
    markets, not every mandi - good for direction & seasonality.
    """
    key = _api_key()
    if not key:
        raise RuntimeError("No API key. Add DATA_GOV_API_KEY to secrets.")

    params = {
        "api-key": key,
        "format": "json",
        "limit": limit,
        "filters[Commodity]": commodity,
    }
    if state and state != "All India":
        params["filters[State]"] = state

    from core import usage
    usage.bump("data_gov")
    resp = requests.get(HIST_API, params=params, timeout=20)
    resp.raise_for_status()
    records = resp.json().get("records", [])
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df.get("Arrival_Date"),
                                format="%d/%m/%Y", errors="coerce")
    df["modal"] = pd.to_numeric(df.get("Modal_Price"), errors="coerce")
    df = df.dropna(subset=["date", "modal"])
    df = df[df["modal"] > 0]
    if df.empty:
        return pd.DataFrame()

    df["Month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    g = (df.groupby("Month")
         .agg(Modal=("modal", "median"),
              Low=("modal", "min"),
              High=("modal", "max"),
              Records=("modal", "size"))
         .reset_index()
         .sort_values("Month"))
    g["Modal"] = g["Modal"].round(0)
    return g.tail(months).reset_index(drop=True)


@st.cache_data(ttl=21600, show_spinner="Fetching variety prices...")
def get_variety_prices(commodity, state, limit=6000):
    """Per-variety price summary for a commodity in a state, from the
    variety-wise archive. Returns a DataFrame: Variety, Latest, Latest
    Date, Median, Low, High, Markets, Records - sorted by latest modal
    (highest-value grade first). Empty if nothing found."""
    key = _api_key()
    if not key:
        raise RuntimeError("No API key. Add DATA_GOV_API_KEY to secrets.")

    params = {
        "api-key": key,
        "format": "json",
        "limit": limit,
        "filters[Commodity]": commodity,
    }
    if state and state != "All India":
        params["filters[State]"] = state

    from core import usage
    usage.bump("data_gov")
    resp = requests.get(HIST_API, params=params, timeout=20)
    resp.raise_for_status()
    records = resp.json().get("records", [])
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df.get("Arrival_Date"),
                                format="%d/%m/%Y", errors="coerce")
    df["modal"] = pd.to_numeric(df.get("Modal_Price"), errors="coerce")
    df["Variety"] = df.get("Variety", "Other").fillna("Other")
    df["Market"] = df.get("Market", "")
    df = df.dropna(subset=["date", "modal"])
    df = df[df["modal"] > 0]
    if df.empty:
        return pd.DataFrame()

    df = df.sort_values("date")
    latest = (df.groupby("Variety").tail(1)
              .set_index("Variety")[["date", "modal"]]
              .rename(columns={"date": "Latest Date", "modal": "Latest"}))
    agg = df.groupby("Variety").agg(
        Median=("modal", "median"),
        Low=("modal", "min"),
        High=("modal", "max"),
        Markets=("Market", "nunique"),
        Records=("modal", "size"),
    )
    out = latest.join(agg).reset_index()
    out["Latest Date"] = out["Latest Date"].dt.strftime("%d %b %Y")
    for c in ("Latest", "Median", "Low", "High"):
        out[c] = out[c].round(0).astype(int)
    return out.sort_values("Latest", ascending=False).reset_index(
        drop=True)
