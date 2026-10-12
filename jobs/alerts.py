"""Evaluate rules/rules.toml for every watched village -> alert log.

Runs after forecast and rain in the daily group. For each village and
each crop it grows (plus '' for whole-village rules):

1. build features (core.features) - observed rain, latest forecast,
   calendar;
2. evaluate every rule that is in season and applies to the crop;
3. keep the highest severity per rule group;
4. drop a group still in its cooldown, unless the severity went up;
5. keep at most MAX_PER_VILLAGE_DAY per village per day, worst first;
6. append `alert` + an `alert_event` 'created'. Rows are never edited.

An alert from a rule with empty approved_by is an English-only draft
(shareable = 0): staff can read it, the share kit will not offer it.
"""

import base64
import datetime
import hashlib
import json
import logging

from core import features, rules, store

log = logging.getLogger("jobs.alerts")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
MAX_PER_VILLAGE_DAY = 2


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def alert_id(as_of, village_id, crop, rule_id):
    """Short, stable id an officer can read out: MMDD-XXXX."""
    h = hashlib.sha1(f"{as_of}|{village_id}|{crop}|{rule_id}".encode())
    return f"{as_of:%m%d}-" + base64.b32encode(h.digest()).decode()[:4]


def _recent(con, village_id, since):
    """{(group, crop): highest severity rank} of alerts since `since`,
    and the number of alerts already made today."""
    out = {}
    for grp, crop, sev in con.execute(
            "SELECT rule_group, crop, severity FROM alert WHERE "
            "village_id=? AND as_of>=?", (village_id, since.isoformat())):
        k = (grp, crop)
        out[k] = max(out.get(k, 0), rules.SEVERITY_RANK[sev])
    return out


def candidates(rule_list, feats, crops, as_of):
    """Fired (rule, crop, trace), highest severity per (group, crop)."""
    best = {}
    for crop in [""] + crops:
        f = dict(feats, crop=crop)
        for r in rule_list:
            if not r.applies_to(crop) or not r.active_on(as_of):
                continue
            fired, trace = rules.evaluate(r, f)
            if not fired:
                continue
            k = (r.key, crop)
            cur = best.get(k)
            if cur is None or (rules.SEVERITY_RANK[r.severity],
                               r.priority) > (
                    rules.SEVERITY_RANK[cur[0].severity], cur[0].priority):
                best[k] = (r, crop, trace)
    return list(best.values())


def run_village(con, vid, rule_list, as_of, now, sha):
    feats, vintage = features.build(con, vid, as_of)
    crops = features.village_crops(con, vid)
    cands = candidates(rule_list, feats, crops, as_of)
    made_today = con.execute(
        "SELECT COUNT(*) FROM alert WHERE village_id=? AND as_of=?",
        (vid, as_of.isoformat())).fetchone()[0]
    kept = []
    for r, crop, trace in cands:
        since = as_of - datetime.timedelta(days=max(r.cooldown_days, 1) - 1)
        prev = _recent(con, vid, since).get((r.key, crop), 0)
        if prev >= rules.SEVERITY_RANK[r.severity]:
            continue                      # in cooldown, no escalation
        kept.append((r, crop, trace))
    kept.sort(key=lambda x: (rules.SEVERITY_RANK[x[0].severity],
                             x[0].priority), reverse=True)
    kept = kept[:max(0, MAX_PER_VILLAGE_DAY - made_today)]
    n = 0
    for r, crop, trace in kept:
        f = dict(feats, crop=crop)
        aid = alert_id(as_of, vid, crop, r.id)
        cur = con.execute(
            "INSERT OR IGNORE INTO alert (alert_id, created_at, as_of, "
            "village_id, crop, rule_id, rule_group, rule_hash, severity, "
            "kind, title, text_en, source, approved_by, shareable, "
            "features_json, trace_json, vintage_json, git_sha) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, now, as_of.isoformat(), vid, crop, r.id, r.key, r.hash,
             r.severity, r.kind, r.title, rules.render(r.draft_en, f),
             r.source, r.approved_by.strip(), int(r.approved),
             json.dumps(f), json.dumps(trace), json.dumps(vintage), sha))
        if cur.rowcount:
            con.execute(
                "INSERT INTO alert_event (alert_id, at, event, actor, "
                "detail_json) VALUES (?, ?, 'created', 'jobs.alerts', ?)",
                (aid, now, json.dumps({"rule_hash": r.hash})))
            n += 1
    return n, feats


def run(con):
    from jobs.run import git_sha
    rule_list, errors = rules.load()
    now = _utc_now()
    as_of = datetime.datetime.now(IST).date()
    sha = git_sha()
    vids = [r[0] for r in con.execute(
        "SELECT village_id FROM villages ORDER BY village_id")]
    if not vids:
        return {"rows": 0, "status": "ok",
                "detail": "no villages in the store yet (forecast/rain "
                          "jobs fill it)"}
    made = no_rain = no_fc = 0
    for vid in vids:
        n, feats = run_village(con, vid, rule_list, as_of, now, sha)
        made += n
        no_rain += feats.get("obs_through") is None
        no_fc += feats.get("fc_rain_3d_mm") is None
    con.commit()
    detail = (f"{len(rule_list)} rules x {len(vids)} villages: {made} new "
              f"alerts")
    if no_rain:
        detail += f"; {no_rain} villages without fresh observed rain"
    if no_fc:
        detail += f"; {no_fc} without a fresh forecast"
    status = "ok"
    if errors:
        detail += "; RULES SKIPPED: " + " | ".join(errors)
        status = "partial"
    return {"rows": made, "detail": detail, "status": status}
