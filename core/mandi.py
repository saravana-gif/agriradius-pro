"""Live mandi (APMC) prices from AGMARKNET via data.gov.in.

Daily wholesale prices per market. Prices are Rs per quintal.
API key lives in .streamlit/secrets.toml (never committed to git).
"""

import pandas as pd
import requests
import streamlit as st

RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"
API = f"https://api.data.gov.in/resource/{RESOURCE}"

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
          "Andhra Pradesh", "Telangana", "Maharashtra"]


def _api_key():
    try:
        return st.secrets["DATA_GOV_API_KEY"]
    except Exception:
        return ""


@st.cache_data(ttl=1800, show_spinner="Fetching mandi prices...")
def get_prices(commodity, state=None, limit=200):
    """Latest prices for a commodity. Returns a DataFrame."""

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

    resp = requests.get(API, params=params, timeout=20)
    resp.raise_for_status()

    records = resp.json().get("records", [])

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    df = df.rename(columns={
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
        "Modal (Rs/qtl)", ascending=False
    ).reset_index(drop=True)
