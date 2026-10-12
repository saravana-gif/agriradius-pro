"""Run app modules outside `streamlit run` (cron jobs).

The core/ modules were written for Streamlit: they read st.secrets and
count API calls in st.session_state. Call setup() once before importing
anything that fetches, and they work headless:

- secrets come from .streamlit/secrets.toml via tomllib (override the
  path with AGRI_SECRETS_PATH). Values are never logged or printed -
  only whether a key is present.
- core.secrets.get reads that dict (top level, then [auth], then an
  environment variable of the same name).
- core.usage.bump / note_error count calls into CALLS instead of
  st.session_state, so job_runs can record API usage per run.
- Earth Engine: init_ee() uses the service account ONLY. It never falls
  back to ee.Authenticate() - a browser login would hang a cron job.
"""

import logging
import os
import tomllib
from pathlib import Path

from config import PROJECT_ID, PROJECT_ROOT

log = logging.getLogger("jobs")

CALLS = {}

_SECRETS = None
_READY = False


def secrets_path():
    return Path(os.environ.get("AGRI_SECRETS_PATH")
                or PROJECT_ROOT / ".streamlit" / "secrets.toml")


def load_secrets():
    """Parse secrets.toml once. Missing file = empty dict (jobs that
    need a key then fail with a clear 'not configured' message)."""
    global _SECRETS
    if _SECRETS is None:
        p = secrets_path()
        try:
            with open(p, "rb") as f:
                _SECRETS = tomllib.load(f)
        except FileNotFoundError:
            log.warning("no secrets file at %s - env vars only", p)
            _SECRETS = {}
    return _SECRETS


def secret(key, default=None):
    """Same lookup order as core.secrets.get, plus env vars."""
    s = load_secrets()
    val = s.get(key)
    if val is None and isinstance(s.get("auth"), dict):
        val = s["auth"].get(key)
    if val is None:
        val = os.environ.get(key)
    return default if val is None else val


def _bump(service, n=1):
    CALLS[service] = CALLS.get(service, 0) + n


def _note_error(service, exc):
    from core import usage
    return usage.classify(exc)


def setup(level=logging.INFO):
    """Idempotent. Quiet Streamlit and patch secrets/usage."""
    global _READY
    if _READY:
        return
    # Streamlit warns "No runtime found" on every cache call outside
    # `streamlit run`; that noise would bury the job log.
    os.environ.setdefault("STREAMLIT_LOGGER_LEVEL", "error")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import streamlit  # noqa: F401  (load before silencing its loggers)
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("streamlit"):
            logging.getLogger(name).setLevel(logging.ERROR)

    import core.secrets
    import core.usage
    core.secrets.get = secret
    core.usage.bump = _bump
    core.usage.note_error = _note_error

    load_secrets()
    _READY = True


def init_ee():
    """Initialise Earth Engine from the service account, or raise.

    Phase 0 jobs do not need Earth Engine; this exists so later jobs
    use the one safe path. Keep EE use minimal - the free tier is
    non-commercial."""
    setup()
    import ee
    from gee.auth import _service_account_creds
    creds = _service_account_creds()
    if creds is None:
        raise RuntimeError(
            "Earth Engine needs EE_SERVICE_ACCOUNT (or "
            "GCP_SERVICE_ACCOUNT) in secrets for headless jobs.")
    ee.Initialize(creds, project=PROJECT_ID)
