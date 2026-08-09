"""District / State report engine - rankings with reasons.

Rankings combine, transparently:
  * SOIL      - measured SHC lab data (village- and district-level),
  * ECONOMY   - bundled government data (livestock density, dairy,
                land capability where available) as district context,
  * CROP CYCLE- the app's satellite summary, run on demand with the
                existing cost-capped Earth Engine pipeline (district
                mode only; never fired automatically state-wide).

Pure computation - no streamlit.
"""

import re

from core import shc_api

# nutrient key -> (label, adequacy class meaning "good")
_MACROS = [("n", "N"), ("p", "P"), ("k", "K"), ("OC", "OC")]
_MICROS = [("S", "S"), ("Zn", "Zn"), ("Fe", "Fe"),
           ("B", "B"), ("Mn", "Mn"), ("Cu", "Cu")]


def _n(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def _pct(d, cls):
    d = d or {}
    tot = sum(int(v or 0) for v in d.values())
    if not tot:
        return None, 0
    return round(100 * int(d.get(cls, 0) or 0) / tot), tot


def soil_score(results):
    """(score 0-100, [reason strings], total samples).

    Score = mean adequacy: macros count double (N/P/K/OC drive yield),
    micros single, pH neutrality small bonus. Reasons list the worst
    offenders so every ranking is explainable.
    """
    if not results:
        return None, ["no lab samples"], 0

    parts, weights, reasons = [], [], []
    max_tot = 0

    for key, lab in _MACROS:
        low, tot = _pct(results.get(key), "Low")
        if low is None:
            continue
        max_tot = max(max_tot, tot)
        parts.append(100 - low)
        weights.append(2.0)
        if low >= 60:
            reasons.append(f"{lab} {low}% low")

    for key, lab in _MICROS:
        def_, tot = _pct(results.get(key), "Deficient")
        if def_ is None:
            continue
        max_tot = max(max_tot, tot)
        parts.append(100 - def_)
        weights.append(1.0)
        if def_ >= 60:
            reasons.append(f"{lab} {def_}% deficient")

    ph = results.get("pH") or {}
    neut, tot = _pct(ph, "Neutral")
    if neut is not None:
        max_tot = max(max_tot, tot)
        parts.append(neut)
        weights.append(0.5)
        if neut <= 25:
            dom = max(ph, key=lambda k: int(ph[k] or 0))
            reasons.append(f"soil mostly {dom.lower()}")

    if not parts:
        return None, ["no lab samples"], 0

    score = round(sum(p * w for p, w in zip(parts, weights))
                  / sum(weights))

    # Lead with what's GOOD when the score is decent, so a top-ranked
    # village never reads as a list of pure negatives.
    if score >= 60:
        good = [lab for key, lab in _MACROS
                if (_pct(results.get(key), "Low")[0] or 0) <= 20
                and _pct(results.get(key), "Low")[0] is not None]
        if good:
            reasons.insert(0, "/".join(good) + " adequate")

    if not reasons:
        reasons.append("balanced nutrient profile")
    return score, reasons[:3], max_tot


def _clean_village(name):
    """Portal village name -> display name (strip code/markers)."""
    s = re.sub(r"[-\s]*\d{4,}\s*$", "", str(name or ""))
    return re.sub(r"\s+", " ", s).strip().title()


def village_rankings(state_label, districts, top=25, min_samples=1):
    """Ranked villages across one or many districts, from the SHC
    cache (no network). Returns list of dicts sorted best-first:
    {village, district, score, reasons, samples, cycle}.

    min_samples filters out statistically weak entries (a village
    with one sample shouldn't outrank one with fifty)."""
    rows = []
    for dist in districts:
        cached = shc_api.village_results_cached(state_label, dist)
        for vname, res in cached.items():
            score, reasons, tot = soil_score(res)
            if score is None or tot < min_samples:
                continue
            rows.append({
                "village": _clean_village(vname),
                "district": str(dist).title(),
                "score": score,
                "reasons": "; ".join(reasons),
                "samples": tot,
                "cycle": (res or {}).get("_cycle", ""),
            })
    rows.sort(key=lambda r: (-r["score"], -r["samples"]))
    return rows[:top] if top else rows


def _livestock_totals(state_label, districts):
    """{district: total livestock head} from the bundled 2019 census
    (economy proxy). Missing districts are absent."""
    out = {}
    try:
        from core.allied import load_livestock, _match_row
        df = load_livestock()
        if df.empty:
            return out
        for dist in districts:
            row = _match_row(df, state_label, dist)
            if row is None:
                continue
            tot = 0
            for c in df.columns:
                if c in ("state", "district", "_key", "_state"):
                    continue
                try:
                    tot += int(float(row[c]))
                except (TypeError, ValueError):
                    continue
            if tot > 0:
                out[dist] = tot
    except Exception:
        pass
    return out


def district_rankings(state_label, districts):
    """Ranked districts by a transparent composite:

      60% SOIL    - measured SHC adequacy (one cached portal query
                    per district, multi-cycle),
      40% ECONOMY - livestock economy percentile from the bundled
                    2019 census (dairy/meat capacity proxy).

    Crop-cycle satellite summaries stay on-demand per district (cost
    capped) and are shown in the district report rather than fired
    for a whole state. Every row carries its reasons."""
    live = _livestock_totals(state_label, districts)
    vals = sorted(live.values())

    def econ_pct(dist):
        v = live.get(dist)
        if v is None or not vals:
            return None
        below = sum(1 for x in vals if x <= v)
        return round(100 * below / len(vals))

    rows = []
    for dist in districts:
        res = shc_api.district_nutrients(state_label, dist)
        score, reasons, tot = soil_score(res)
        ep = econ_pct(dist)

        if score is not None and ep is not None:
            comp = round(0.6 * score + 0.4 * ep)
            reasons = list(reasons) + [
                f"livestock economy P{ep} ({live[dist]:,} head)"]
        elif score is not None:
            comp = score
        elif ep is not None:
            comp = ep
            reasons = [f"livestock economy P{ep} "
                       f"({live[dist]:,} head); no soil samples"]
        else:
            comp = None

        rows.append({
            "district": str(dist).title(),
            "score": comp,
            "soil_score": score,
            "economy_pct": ep,
            "reasons": "; ".join(reasons),
            "samples": tot,
            "cycle": (res or {}).get("_cycle", "") if res else "",
        })
    with_score = [r for r in rows if r["score"] is not None]
    without = [r for r in rows if r["score"] is None]
    with_score.sort(key=lambda r: -r["score"])
    return with_score + without


def point_summary(lat, lon):
    """Compare-table row for one point: village, district, state,
    village soil (from cache or one live fetch), reasons."""
    from gis.spatial import village_at_point
    info = village_at_point(lat, lon) or {}
    village = info.get("Village", "?")
    district = info.get("District", "?")
    state = info.get("State", "?")

    res_map = {}
    try:
        res_map = shc_api.results_for_villages(
            [("p0", state, district, "", village)])
    except Exception:
        pass
    res = res_map.get("p0")
    score, reasons, tot = soil_score(res)

    return {
        "lat": round(float(lat), 5),
        "lon": round(float(lon), 5),
        "village": str(village).title(),
        "district": str(district).title(),
        "state": str(state).title(),
        "soil_score": score,
        "soil_notes": "; ".join(reasons),
        "samples": tot,
        "cycle": (res or {}).get("_cycle", "") if res else "",
    }
