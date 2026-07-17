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

# --- App defaults ---
APP_NAME = "AgriRadius Pro"
APP_VERSION = "0.5.1"
DEFAULT_LAT = 11.923456
DEFAULT_LON = 76.940123
DEFAULT_RADIUS_KM = 38
DEFAULT_YEAR = 2025
AVAILABLE_YEARS = [2025, 2024, 2023]
