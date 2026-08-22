"""Harvest window from the observed NDVI curve.

WHY THIS IS BUILT ON SENESCENCE, NOT A CALENDAR
-----------------------------------------------
A crop calendar tells you when a crop is *usually* harvested in a
district. That is an average over many seasons and does not know
whether this particular area sowed late, or lost a month to a dry
spell. The NDVI curve does know: canopy peaks, then declines as the
crop matures and dries down, and harvest sits inside that decline.

So the window here is measured from the actual curve for the actual
area - the peak month, then the month the canopy falls back through
a senescence threshold. The only assumed number is how far into that
decline harvest typically falls, and that assumption is stated on
screen rather than buried.

WHAT IT CANNOT DO
-----------------
Perennials break the premise. Coconut has no senescence peak - it is
picked in rounds every 45-60 days all year - so a "harvest window"
for coconut would be fiction. This module refuses to produce one and
says why, rather than printing a confident month range.
"""

import datetime as _dt

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Fraction of the peak-to-trough decline at which a standing crop is
# typically ready. 0.5 = halfway down the curve. This is the ONE
# assumed parameter and it is surfaced in the output so a reader can
# disagree with it.
SENESCENCE_FRACTION = 0.5

# Patterns for which a discrete harvest window is meaningful at all.
WINDOWED_PATTERNS = {
    "Single Cropping",
    "Double / Multiple Cropping",
    "Long-Duration Crop",
}


def _month_index(label):
    """'Sep' / 'Sep 2025' / '2025-09' -> 0-11, or None."""
    if label is None:
        return None
    s = str(label).strip()
    for i, m in enumerate(MONTHS):
        if s[:3].lower() == m.lower():
            return i
    for sep in ("-", "/"):
        if sep in s:
            parts = s.split(sep)
            for p in parts:
                if p.isdigit() and 1 <= int(p) <= 12:
                    return int(p) - 1
    return None


def windows(df, insight, today=None):
    """Estimate harvest windows from a monthly NDVI frame.

    df      - from core.crop_cycle.to_dataframe (Month, Smoothed)
    insight - from core.crop_cycle.analyze_series
    Returns a dict; never raises.
    """
    out = {"supported": False, "reason": None, "windows": [],
           "next": None, "basis": None, "pattern": None}
    if not insight:
        out["reason"] = "No cropping pattern was computed for this area."
        return out

    pattern = insight.get("pattern")
    out["pattern"] = pattern

    if pattern == "Perennial / Plantation":
        out["reason"] = (
            "This area reads as perennial/plantation - coconut, "
            "arecanut, banana or orchard. The canopy never senesces, "
            "so there is no harvest peak to measure. Coconut is "
            "picked in rounds roughly every 45-60 days year-round and "
            "arecanut mainly August-December; neither is a window "
            "this curve can date. Use the crop-survey extent and "
            "local knowledge for arrival timing here.")
        return out

    if pattern not in WINDOWED_PATTERNS:
        out["reason"] = (
            f"Pattern is '{pattern}' - too little cropping signal to "
            f"place a harvest window. A window here would be invented, "
            f"not measured.")
        return out

    try:
        smooth = df["Smoothed"].tolist()
        months = df["Month"].tolist()
    except Exception as e:
        out["reason"] = f"NDVI series unusable: {e}"
        return out

    if len(smooth) < 6:
        out["reason"] = ("Fewer than 6 months of NDVI - not enough "
                         "curve to find a decline.")
        return out

    peak_labels = insight.get("peak_months") or []
    peak_idx = [i for i, m in enumerate(months) if m in peak_labels]
    if not peak_idx:
        out["reason"] = ("No NDVI peak was detected, so there is no "
                         "decline to measure from.")
        return out

    found = []
    for p in peak_idx:
        peak_val = smooth[p]
        # Walk forward to the trough that follows this peak.
        tail = smooth[p + 1:]
        if not tail:
            continue
        trough_val = min(tail)
        target = peak_val - SENESCENCE_FRACTION * (peak_val - trough_val)
        hit = None
        for j in range(p + 1, len(smooth)):
            if smooth[j] <= target:
                hit = j
                break
        if hit is None:
            continue
        found.append({
            "peak_month": months[p],
            "peak_ndvi": round(float(peak_val), 3),
            "harvest_month": months[hit],
            "months_after_peak": hit - p,
            # A one-month band either side: monthly compositing cannot
            # resolve finer than that, and pretending otherwise would
            # be false precision.
            "window": _band(months, hit),
        })

    if not found:
        out["reason"] = ("Peaks were found but the canopy never "
                         "declined far enough within the series to "
                         "date a harvest - the season may still be "
                         "standing, or the series ends too early.")
        return out

    out["supported"] = True
    out["windows"] = found
    out["basis"] = (
        f"Measured from this area's own NDVI curve: harvest is placed "
        f"where the canopy has fallen {int(SENESCENCE_FRACTION * 100)}% "
        f"of the way from its peak to the following trough. Monthly "
        f"compositing means the window cannot be finer than about a "
        f"month either side.")
    out["next"] = _next_window(found, today)
    return out


def _band(months, i):
    """A +/- one month band around index i, using the real labels."""
    lo = months[i - 1] if i - 1 >= 0 else months[i]
    hi = months[i + 1] if i + 1 < len(months) else months[i]
    return f"{lo} to {hi}"


def _next_window(found, today=None):
    """Which measured window comes round next in the calendar.

    Answers in MONTH NAMES ONLY, deliberately. The series spans two
    years, so the same harvest appears twice with different year
    labels; picking one by index returned a window that had already
    passed. These windows recur annually - the useful answer is
    "October to December", not "Oct 25 to Dec 25".
    """
    today = today or _dt.date.today()
    now = today.month - 1

    # Collapse repeated cycles onto the calendar month they occur in.
    by_month = {}
    for w in found:
        mi = _month_index(w["harvest_month"])
        if mi is None:
            continue
        by_month.setdefault(mi, w)

    if not by_month:
        return None

    mi = min(by_month, key=lambda m: (m - now) % 12)
    ahead = (mi - now) % 12
    lo = MONTHS[(mi - 1) % 12]
    hi = MONTHS[(mi + 1) % 12]
    return {
        "harvest_month": MONTHS[mi],
        "window": f"{lo} to {hi}",
        "months_away": ahead,
        "cycles_per_year": len(by_month),
        "note": ("this month" if ahead == 0
                 else f"about {ahead} month{'s' if ahead > 1 else ''} away"),
    }


def verdict(res):
    """One line for the panel and the report."""
    if not res or not res.get("supported"):
        return None
    n = res.get("next") or {}
    if not n:
        return None
    per_year = n.get("cycles_per_year", 1)
    return (f"Next harvest window here: {n['window']} "
            f"({n['note']}). {per_year} harvest"
            f"{'s' if per_year > 1 else ''} per year, measured from "
            f"this area's own NDVI curve.")
