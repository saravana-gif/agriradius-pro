"""Central configuration for AgriRadius Pro.

All application-wide constants live here. Do not hardcode paths or
credentials elsewhere in the codebase.
"""

from pathlib import Path

# --- Google Earth Engine ---
PROJECT_ID = "agriradius"

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent
BOUNDARIES_DIR = PROJECT_ROOT / "boundaries"
LOGO_PATH = PROJECT_ROOT / "assets" / "logos" / "oneroot_logo.png"

# --- App defaults ---
APP_NAME = "OneRoot AgriRadius Pro"
COMPANY = "OneRoot (ENP Farms Private Limited)"
APP_VERSION = "0.8.1"
DEFAULT_LAT = 11.923456
DEFAULT_LON = 76.940123
DEFAULT_RADIUS_KM = 10
DEFAULT_YEAR = 2025
AVAILABLE_YEARS = [2025, 2024, 2023]
