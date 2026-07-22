"""Shared Google Sheets storage for field-collected data.

When deployed, field corrections must persist in one shared place -
local CSV files on a laptop won't do. This module writes ground-truth
observations and soil health cards to a Google Sheet.

Configuration (Streamlit secrets):
    GSHEET_ID           - the Sheet's ID (from its URL)
    GCP_SERVICE_ACCOUNT - the service account JSON (string or table)

The SAME service account can also power Earth Engine. Remember to
share the Sheet with the service account's client_email (Editor).

If not configured, is_enabled() returns False and callers fall back
to local CSV, so the app still runs on a developer machine.
"""

import json

import pandas as pd
import streamlit as st

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _secret(key):
    try:
        return st.secrets.get(key)
    except Exception:
        return None


def is_enabled():
    """True if a Sheet id and service account are configured."""
    return bool(_secret("GSHEET_ID") and _secret("GCP_SERVICE_ACCOUNT"))


@st.cache_resource(show_spinner=False)
def _spreadsheet():
    """Open the configured spreadsheet (cached per server session)."""
    import gspread
    from google.oauth2.service_account import Credentials

    raw = _secret("GCP_SERVICE_ACCOUNT")
    info = json.loads(raw) if isinstance(raw, str) else dict(raw)

    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)

    return client.open_by_key(_secret("GSHEET_ID"))


def _worksheet(name, columns):
    """Get or create a worksheet with a header row."""
    ss = _spreadsheet()

    try:
        ws = ss.worksheet(name)
    except Exception:
        ws = ss.add_worksheet(title=name, rows=1000, cols=max(len(columns), 5))
        ws.append_row(columns)
        return ws

    # Ensure a header exists
    if not ws.get_all_values():
        ws.append_row(columns)

    return ws


def append_row(sheet_name, row_dict, columns):
    """Append one record to a worksheet, in the given column order."""
    ws = _worksheet(sheet_name, columns)
    ws.append_row([str(row_dict.get(c, "")) for c in columns],
                  value_input_option="USER_ENTERED")


def append_rows(sheet_name, rows, columns):
    """Append many records at once (one API call)."""
    ws = _worksheet(sheet_name, columns)
    ws.append_rows(
        [[str(r.get(c, "")) for c in columns] for r in rows],
        value_input_option="USER_ENTERED")


def read_records(sheet_name, columns):
    """Return a worksheet as a DataFrame (empty if missing)."""
    try:
        ws = _worksheet(sheet_name, columns)
        records = ws.get_all_records()
    except Exception:
        return pd.DataFrame(columns=columns)

    if not records:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(records)
