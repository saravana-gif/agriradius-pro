"""Red / amber / green status per watched village, for the village card
and the Monday portfolio. Reads the job store only.

Thresholds (roadmap; same as the season-rain rules):
    rain departure   green > -20%   amber -20..-39%   red <= -40%
    dry spell        green < 10 d   amber 10..20 d    red >= 21 d
    crop-stage risk  worst alert of the last 7 days (drafts included -
                     this is an internal view)
    price move       |7-day vs prior 14-day state median| green < 10%,
                     amber 10..19%, red >= 20% (direction shown)
    field report     days since the last one: green <= 7, amber 8..14,
                     red > 14 or never
Missing data is grey ("?"), never green.
"""

import datetime
import json
import sqlite3
from statistics import median

RANK = {"red": 3, "amber": 2, "green": 1, "grey": 0}

# Watched-village crop -> AGMARKNET commodity in mandi_daily.
CROP_COMMODITY = {
    "turmeric": "Turmeric", "maize": "Maize", "chilli": "Dry Chillies",
    "banana": "Banana", "tender coconut": "Tender Coconut",
    "coconut": "Coconut",
}


def rag_rain(dep):
    if dep is None:
        return "grey"
    return "red" if dep <= -40 else "amber" if dep <= -20 else "green"


def rag_dry(days):
    if days is None:
        return "grey"
    return "red" if days >= 21 else "amber" if days >= 10 else "green"


def rag_price(pct):
    if pct is None:
        return "grey"
    a = abs(pct)
    return "red" if a >= 20 else "amber" if a >= 10 else "green"


def rag_report(days):
    if days is None:
        return "red"
    return "red" if days > 14 else "amber" if days > 7 else "green"


def price_move(con, commodity, state, as_of):
    """% change of the state median modal price, last 7 days vs the 14
    days before; None with fewer than 3 prices in either window."""
    a = as_of.isoformat()
    rows = con.execute(
        "SELECT arrival_date, modal_price FROM mandi_daily WHERE "
        "commodity=? AND state=? AND qc='ok' AND arrival_date<=? AND "
        "arrival_date>?", (commodity, state, a,
                           (as_of - datetime.timedelta(days=21)).isoformat()
                           )).fetchall()
    cut = (as_of - datetime.timedelta(days=7)).isoformat()
    recent = [p for d, p in rows if d > cut]
    prior = [p for d, p in rows if d <= cut]
    if len(recent) < 3 or len(prior) < 3:
        return None
    m0 = median(prior)
    return round(100.0 * (median(recent) - m0) / m0, 1) if m0 else None


def last_report_days(con, village_id, as_of):
    """Days since the village's last field report; None if none (or the
    field-report table does not exist yet)."""
    try:
        row = con.execute("SELECT MAX(reported_on) FROM field_report "
                          "WHERE village_id=?", (village_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row[0]:
        return None
    return (as_of - datetime.date.fromisoformat(row[0][:10])).days


def village_rows(con, as_of):
    """One status dict per village in the store, worst first."""
    out = []
    vrows = con.execute("SELECT village_id, village, district, state, crops "
                        "FROM villages ORDER BY village").fetchall()
    since = (as_of - datetime.timedelta(days=6)).isoformat()
    for vid, name, district, state, crops in vrows:
        f = con.execute(
            "SELECT features_json, as_of FROM village_features WHERE "
            "village_id=? AND kind='rain' ORDER BY as_of DESC LIMIT 1",
            (vid,)).fetchone()
        rain = json.loads(f[0]) if f else {}
        alerts = con.execute(
            "SELECT alert_id, severity, title, crop, approved_by, as_of "
            "FROM alert WHERE village_id=? AND as_of>=? ORDER BY as_of "
            "DESC", (vid, since)).fetchall()
        worst = max(alerts, key=lambda a: RANK[a[1]], default=None)
        crop_list = [c.strip().lower() for c in (crops or "").replace(
            ",", ";").split(";") if c.strip()]
        moves = []
        for c in crop_list:
            com = CROP_COMMODITY.get(c)
            pm = price_move(con, com, state, as_of) if com else None
            if pm is not None:
                moves.append((c, pm))
        big = max(moves, key=lambda m: abs(m[1]), default=None)
        rep = last_report_days(con, vid, as_of)
        r = {
            "village_id": vid, "village": name, "district": district,
            "state": state, "crops": crop_list,
            "season": rain.get("season"),
            "season_cum_mm": rain.get("season_cum_mm"),
            "season_normal_mm": rain.get("season_normal_mm"),
            "season_dep_pct": rain.get("season_dep_pct"),
            "season_category": rain.get("season_category"),
            "dry_days": rain.get("dry_days"),
            "dry_days_gap": rain.get("dry_days_gap"),
            "spi3": rain.get("spi3"), "spi3_label": rain.get("spi3_label"),
            "obs_through": rain.get("obs_through"),
            "rain_as_of": f[1] if f else None,
            "alerts": [dict(zip(("alert_id", "severity", "title", "crop",
                                 "approved_by", "as_of"), a))
                       for a in alerts],
            "price_move": big,
            "report_days": rep,
            "rag": {
                "rain": rag_rain(rain.get("season_dep_pct")),
                "dry": rag_dry(rain.get("dry_days")),
                "risk": worst[1] if worst else "green",
                "price": rag_price(big[1] if big else None),
                "report": rag_report(rep),
            },
            "risk_label": (f"{worst[2]}" if worst else "no alerts"),
        }
        out.append(r)
    out.sort(key=lambda r: (
        -sum(v == "red" for v in r["rag"].values()),
        -sum(v == "amber" for v in r["rag"].values()), r["village"]))
    return out
