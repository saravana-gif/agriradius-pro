import json

import ee
import streamlit as st

from config import PROJECT_ID


def _service_account_creds():
    """Build EE credentials from a service account, if configured.

    Looks for a service-account JSON in Streamlit secrets under
    EE_SERVICE_ACCOUNT (the full JSON, as a string or table). This is
    how the app authenticates when deployed to a server where no
    interactive browser login is possible.
    Returns ee credentials or None.
    """
    try:
        raw = (st.secrets.get("EE_SERVICE_ACCOUNT")
               or st.secrets.get("GCP_SERVICE_ACCOUNT"))
    except Exception:
        raw = None

    if not raw:
        return None

    info = json.loads(raw) if isinstance(raw, str) else dict(raw)

    return ee.ServiceAccountCredentials(
        info["client_email"],
        key_data=json.dumps(info),
    )


@st.cache_resource(show_spinner="Connecting to Google Earth Engine...")
def initialize():
    """Initialize Earth Engine once per server session (cached).

    Order of preference:
    1. Service account from secrets (works headless / on a server).
    2. Existing local credentials (developer machine).
    3. Interactive browser login (first run on a dev machine only).
    """

    # 1. Service account (deployment)
    creds = _service_account_creds()
    if creds is not None:
        ee.Initialize(creds, project=PROJECT_ID)
        return True

    # 2. Existing local credentials
    try:
        ee.Initialize(project=PROJECT_ID)
        return True
    except Exception:
        pass

    # 3. Interactive login (local dev only; will fail on a server)
    ee.Authenticate()
    ee.Initialize(project=PROJECT_ID)
    return True
