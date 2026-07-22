"""Real Earth Engine EECU usage meter (via Google Cloud Monitoring).

Reads the actual compute consumed this month from the
'earthengine.googleapis.com/project/cpu/usage_time' metric - the same
source as Google's official EE non-commercial EECU monitor notebook -
so we can show a TRUE quota gauge: EECU-hours used / monthly limit, and
when it resets (the 1st of each month).

Setup on the user's machine (one time):
  * pip install google-cloud-monitoring
  * Grant the app's service account the 'Monitoring Viewer' role
    (roles/monitoring.viewer) on the Earth Engine Cloud project.

Non-commercial monthly EECU-hour limits (as published by Google):
  Community 150 · Contributor 1000 · Partner 100000
"""

import datetime
import json

import streamlit as st

from config import PROJECT_ID

TIER_LIMITS = {"Community": 150, "Contributor": 1000, "Partner": 100000}
METRIC = "earthengine.googleapis.com/project/cpu/usage_time"


def _credentials():
    try:
        raw = (st.secrets.get("EE_SERVICE_ACCOUNT")
               or st.secrets.get("GCP_SERVICE_ACCOUNT"))
    except Exception:
        raw = None
    if not raw:
        return None
    info = json.loads(raw) if isinstance(raw, str) else dict(raw)
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/monitoring.read"])


@st.cache_data(ttl=1800, show_spinner="Reading Earth Engine usage...")
def eecu_usage(tier="Community", _nonce=0):
    """Return this-month EECU usage. Dict:
    {used, limit, remaining, pct, reset, daily} or {error, msg}."""
    try:
        from google.cloud import monitoring_v3
    except ImportError:
        return {"error": "pkg",
                "msg": "Run: pip install google-cloud-monitoring"}

    creds = _credentials()
    if creds is None:
        return {"error": "creds",
                "msg": "No service account found in secrets."}

    try:
        client = monitoring_v3.MetricServiceClient(credentials=creds)
        now = datetime.datetime.now(datetime.timezone.utc)
        start = datetime.datetime(now.year, now.month, 1,
                                  tzinfo=datetime.timezone.utc)
        interval = monitoring_v3.TimeInterval({
            "end_time": {"seconds": int(now.timestamp())},
            "start_time": {"seconds": int(start.timestamp())},
        })
        results = client.list_time_series(request={
            "name": f"projects/{PROJECT_ID}",
            "filter": f'metric.type = "{METRIC}"',
            "interval": interval,
            "view": monitoring_v3.ListTimeSeriesRequest
            .TimeSeriesView.FULL,
            "aggregation": {
                "alignment_period": {"seconds": 86400},
                "per_series_aligner":
                    monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
                "cross_series_reducer":
                    monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
            },
        })

        daily = {}
        for r in results:
            for p in r.points:
                d = p.interval.end_time
                ts = d.timestamp() if hasattr(d, "timestamp") else d
                day = datetime.datetime.fromtimestamp(
                    ts, datetime.timezone.utc).date().isoformat()
                daily[day] = daily.get(day, 0.0) \
                    + p.value.double_value / 3600.0

        used = round(sum(daily.values()), 2)
        limit = TIER_LIMITS.get(tier)
        reset = (datetime.date(now.year + 1, 1, 1) if now.month == 12
                 else datetime.date(now.year, now.month + 1, 1))
        return {
            "used": used,
            "limit": limit,
            "remaining": round(limit - used, 1) if limit else None,
            "pct": round(100 * used / limit, 1) if limit else None,
            "reset": reset.isoformat(),
            "daily": daily,
            "tier": tier,
        }
    except Exception as e:
        name = type(e).__name__
        msg = str(e)
        if "PermissionDenied" in name or "permission" in msg.lower():
            return {"error": "perm",
                    "msg": ("Grant the service account the 'Monitoring "
                            f"Viewer' role on project '{PROJECT_ID}'.")}
        if "NotFound" in name or "not found" in msg.lower():
            return {"error": "notfound",
                    "msg": f"No usage metric for project '{PROJECT_ID}' "
                           "yet (none this month, or wrong project)."}
        return {"error": "other", "msg": msg[:300]}
