"""Score ourselves: how often were the alerts and the forecast right?

Runs every morning after rain (so yesterday's IMD observations are in)
and writes accuracy_snapshot rows that the accuracy page publishes.
No Earth Engine. Three measurements:

1. Forecast vs IMD gauge rain, last 90 days, per provider and lead
   day: rain yes/no at 2.5 mm (IMD's rainy day) and 10 mm, scored
   with POD / false alarm ratio / Heidke skill, plus mean absolute
   error; and 3-day totals >= 10 mm (the chilli-drying threshold).
   Only IMD (gauge-based) rain is used as truth - scoring a model
   against the Open-Meteo fallback (another model) would be circular.
   Timing: IMD's day D runs 08:30 IST on D to 08:30 on D+1, the
   forecast day is midnight to midnight, so daily pairs overlap by
   15.5 of 24 hours; the 3-day totals soften that mismatch.

2. Forecast-based alerts checked against what fell: each rule with a
   `verify` condition (rules/rules.toml) gets an alert_event
   'verified' (hit / false_alarm) once its window is observed. This
   measures the success ratio (share of warnings that came true); it
   cannot count missed events, which part 1 covers (POD).

3. Officers' 7-day check-backs (Yes / Partly / No) per rule, with a
   Wilson 95% interval. A rule is a retire candidate only when even
   the upper bound of its "right or partly right" share is below 60%
   - noise in a few answers never retires a rule.
"""

import datetime
import json
import logging

from core import rules, verification as V

log = logging.getLogger("jobs.verify")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
WINDOW_DAYS = 90
LEADS = range(0, 8)          # 0 = the issue day itself
GIVE_UP_DAYS = 21            # still no observations -> 'no_data'
RAINY_MM = 2.5


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _d(s):
    return datetime.date.fromisoformat(s)


# ------------------------------------------------- observed rain (IMD)

def observed(con, village_id, since, source="imd"):
    """{date: mm} from one source only, values present only."""
    return {_d(d): mm for d, mm in con.execute(
        "SELECT date, rain_mm FROM rain_daily WHERE village_id=? AND "
        "source=? AND date>=? AND rain_mm IS NOT NULL",
        (village_id, source, since.isoformat()))}


def obs_features(obs, start):
    """Observed outcome features for a window starting `start`. A
    feature is None until every day it needs is observed."""
    def days(n):
        vals = [obs.get(start + datetime.timedelta(days=k))
                for k in range(n)]
        return None if any(v is None for v in vals) else vals
    f = {}
    d3, d7 = days(3), days(7)
    if d3:
        f["obs_rain_3d_mm"] = round(sum(d3), 1)
        f["obs_max_rain_3d_mm"] = max(d3)
        f["obs_rainy_days_3d"] = sum(v >= RAINY_MM for v in d3)
    if d7:
        f["obs_rain_7d_mm"] = round(sum(d7), 1)
        f["obs_rainy_days_7d"] = sum(v >= RAINY_MM for v in d7)
    run = 0
    for k in range(7):                 # dry days in a row from start
        v = obs.get(start + datetime.timedelta(days=k))
        if v is None:
            run = None
            break
        if v >= RAINY_MM:
            break
        run += 1
    f["obs_dry_run_days"] = run
    return f


# ------------------------------------------------ 2. verify the alerts

def verify_alerts(con, rule_by_id, today, now):
    """Append a 'verified' event to forecast-based alerts whose window
    is now observed. Returns counts."""
    since = today - datetime.timedelta(days=60)
    rows = con.execute(
        "SELECT a.alert_id, a.village_id, a.as_of, a.rule_id FROM alert a "
        "WHERE a.as_of>=? AND NOT EXISTS (SELECT 1 FROM alert_event e "
        "WHERE e.alert_id=a.alert_id AND e.event='verified')",
        (since.isoformat(),)).fetchall()
    n = {"hit": 0, "false_alarm": 0, "no_data": 0, "waiting": 0}
    cache = {}
    for aid, vid, as_of, rid in rows:
        r = rule_by_id.get(rid)
        if not r or not (r.verify or r.verify_any):
            continue
        start = _d(as_of)
        if vid not in cache:
            cache[vid] = observed(con, vid, since)
        obs = obs_features(cache[vid], start)
        outcome, trace = rules.check_outcome(r, obs)
        if outcome is None:
            if (today - start).days < GIVE_UP_DAYS:
                n["waiting"] += 1
                continue
            outcome = "no_data"
        con.execute(
            "INSERT INTO alert_event (alert_id, at, event, actor, "
            "detail_json) VALUES (?, ?, 'verified', 'jobs.verify', ?)",
            (aid, now, json.dumps({"outcome": outcome, "observed": obs,
                                   "trace": trace, "truth": "IMD"})))
        n[outcome] += 1
    return n


# ------------------------------------------------ 1. forecast skill

def forecast_pairs(con, since):
    """[(provider, lead, village, date, fc_mm, obs_mm)] for every daily
    forecast whose date has an IMD observation."""
    return con.execute(
        "SELECT f.provider, CAST(julianday(f.date) - julianday(f.issued_on)"
        " AS INTEGER), f.village_id, f.date, f.rain_mm, r.rain_mm FROM "
        "forecast_daily f JOIN rain_daily r ON r.village_id=f.village_id "
        "AND r.date=f.date AND r.source='imd' WHERE f.date>=? AND "
        "f.rain_mm IS NOT NULL AND r.rain_mm IS NOT NULL",
        (since.isoformat(),)).fetchall()


def forecast_skill(con, today):
    since = today - datetime.timedelta(days=WINDOW_DAYS)
    pairs = forecast_pairs(con, since)
    out = {"window_days": WINDOW_DAYS, "since": since.isoformat(),
           "truth": "IMD gridded rain (gauge-based)", "providers": {}}
    by_prov = {}
    for prov, lead, vid, date, f, o in pairs:
        by_prov.setdefault(prov, []).append((lead, vid, date, f, o))
    for prov, rows in by_prov.items():
        leads = {}
        for lead in LEADS:
            sel = [(f, o) for ld, _, _, f, o in rows if ld == lead]
            if not sel:
                continue
            leads[str(lead)] = {
                "rain_2_5": V.categorical_scores(V.contingency(
                    (f >= RAINY_MM, o >= RAINY_MM) for f, o in sel)),
                "rain_10": V.categorical_scores(V.contingency(
                    (f >= 10, o >= 10) for f, o in sel)),
                "amount": V.mae(sel),
            }
        # 3-day totals from each issue: forecast days 0-2 vs observed
        fc3, ob3 = {}, {}
        for ld, vid, date, f, o in rows:
            if 0 <= ld <= 2:
                issued = (_d(date) - datetime.timedelta(days=ld))
                k = (vid, issued)
                fc3.setdefault(k, {})[ld] = f
                ob3.setdefault(k, {})[ld] = o
        tri = [(sum(fc3[k].values()), sum(ob3[k].values()))
               for k in fc3 if len(fc3[k]) == 3]
        out["providers"][prov] = {
            "leads": leads,
            "three_day_10mm": V.categorical_scores(V.contingency(
                (f >= 10, o >= 10) for f, o in tri)),
        }
    out["n_pairs"] = len(pairs)
    return out


# ------------------------------------------------ 3. rule scorecard

def rule_scorecard(con, rule_list, today):
    """Per rule: officers' verdicts and observed outcomes."""
    since = today - datetime.timedelta(days=365)
    alerts = con.execute(
        "SELECT a.alert_id, a.rule_id, (SELECT json_extract(e.detail_json,"
        " '$.verdict') FROM alert_event e WHERE e.alert_id=a.alert_id AND "
        "e.event='checkback' ORDER BY e.id DESC LIMIT 1), (SELECT "
        "json_extract(e.detail_json, '$.outcome') FROM alert_event e WHERE"
        " e.alert_id=a.alert_id AND e.event='verified' ORDER BY e.id DESC "
        "LIMIT 1) FROM alert a WHERE a.as_of>=?",
        (since.isoformat(),)).fetchall()
    per = {}
    for _, rid, verdict, outcome in alerts:
        p = per.setdefault(rid, {"alerts": 0, "yes": 0, "partly": 0,
                                 "no": 0, "hit": 0, "false_alarm": 0})
        p["alerts"] += 1
        if verdict in ("yes", "partly", "no"):
            p[verdict] += 1
        if outcome in ("hit", "false_alarm"):
            p[outcome] += 1
    titles = {r.id: r.title for r in rule_list}
    out = []
    for rid, p in sorted(per.items()):
        n_cb = p["yes"] + p["partly"] + p["no"]
        right = V.proportion(p["yes"], n_cb)
        right_or_partly = V.proportion(p["yes"] + p["partly"], n_cb)
        n_obs = p["hit"] + p["false_alarm"]
        out.append({
            "rule_id": rid, "title": titles.get(rid, rid), **p,
            "checkbacks": n_cb, "right": right,
            "right_or_partly": right_or_partly,
            "status": V.verdict_for_rate(right_or_partly),
            "observed": V.proportion(p["hit"], n_obs),
            "observed_status": V.verdict_for_rate(
                V.proportion(p["hit"], n_obs)),
        })
    return {"since": since.isoformat(), "rules": out}


def _save(con, today, kind, data, now):
    con.execute("INSERT INTO accuracy_snapshot VALUES (?, ?, ?, ?) ON "
                "CONFLICT (computed_on, kind) DO UPDATE SET json="
                "excluded.json, computed_at=excluded.computed_at",
                (today.isoformat(), kind, json.dumps(data), now))


def run(con):
    now = _utc_now()
    today = datetime.datetime.now(IST).date()
    rule_list, errors = rules.load()
    by_id = {r.id: r for r in rule_list}
    counts = verify_alerts(con, by_id, today, now)
    fc = forecast_skill(con, today)
    card = rule_scorecard(con, rule_list, today)
    _save(con, today, "forecast", fc, now)
    _save(con, today, "alerts", card, now)
    con.commit()
    retire = [r["rule_id"] for r in card["rules"]
              if "retire" in (r["status"], r["observed_status"])]
    detail = (f"alerts verified: {counts['hit']} hit, "
              f"{counts['false_alarm']} false alarm, {counts['no_data']} "
              f"no data, {counts['waiting']} waiting; forecast pairs "
              f"{fc['n_pairs']}; {len(card['rules'])} rules scored")
    if retire:
        detail += f"; RETIRE CANDIDATES: {', '.join(retire)}"
    return {"rows": sum(counts.values()) - counts["waiting"] + 2,
            "detail": detail, "status": "partial" if errors else "ok"}
