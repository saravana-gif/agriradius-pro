"""Land-cover analysis orchestration."""

from gee.buffer import create_buffer
from gee.landcover import get_landcover


def analyze_landcover(latitude, longitude, radius_km, year=2025):
    """Run Dynamic World land-cover analysis around a point.

    Returns a list of dicts: [{"Land Cover": name, "Area (ha)": value}, ...]
    """
    buffer = create_buffer(latitude, longitude, radius_km)

    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    return get_landcover(buffer, start_date, end_date)
