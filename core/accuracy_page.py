"""Body HTML of the public "How often are we right?" page, from the
accuracy snapshots (jobs/verify.py, jobs/crop_accuracy.py). Wrapped
and written by jobs/publish.py. Meant to be shown at FPO meetings, so
it carries no prices and no draft advice text - only rule titles and
counts.
"""

import html

from core.verification import MIN_N

E = html.escape

STATUS = {
    "too_few": ("grey", f"too few answers yet (needs {MIN_N})"),
    "ok": ("green", "keep"),
    "watch": ("amber", "watch - below 6 in 10"),
    "retire": ("red", "retire or change - clearly below 6 in 10"),
}
PROVIDER = {"ecmwf_open": "ECMWF", "open_meteo": "Open-Meteo"}


def pct(p, enough=MIN_N):
    """'72% (61-81%)' or 'too few (n=4)'."""
    if not p or p.get("n", 0) == 0 or p.get("value") is None:
        return "-"
    if p["n"] < enough:
        return f"too few (n={p['n']})"
    return (f"{p['value'] * 100:.0f}% <span class=m>"
            f"({p['low'] * 100:.0f}-{p['high'] * 100:.0f}%)</span>")


def _num(v, fmt="{:.2f}"):
    return "-" if v is None else fmt.format(v)


def _status(s):
    c, label = STATUS.get(s, ("grey", s))
    return f"<span class='d {c}'></span>{E(label)}"


def alerts_section(snap):
    rules = (snap or {}).get("rules", [])
    b = ["<h2>Alerts: did the officers find them right?</h2>"
         "<div class=box style='overflow-x:auto'>"]
    if not rules:
        b.append("<p>No alerts scored yet. A week after each alert the "
                 "officer answers Yes / Partly / No.</p></div>")
        return "".join(b)
    b.append("<table><tr><th>Rule</th><th>Alerts</th><th>Answered</th>"
             "<th>Right</th><th>Right or partly</th><th>Verdict</th></tr>")
    for r in rules:
        b.append(f"<tr><td>{E(r['title'])}</td><td>{r['alerts']}</td>"
                 f"<td>{r['checkbacks']}</td><td>{pct(r['right'])}</td>"
                 f"<td>{pct(r['right_or_partly'])}</td>"
                 f"<td>{_status(r['status'])}</td></tr>")
    b.append("</table></div>")

    obs = [r for r in rules if r["observed"]["n"]]
    b.append("<h2>Forecast warnings: did the rain come?</h2>"
             "<div class=box style='overflow-x:auto'>")
    if not obs:
        b.append("<p>No forecast-based warning has been checked against "
                 "IMD rain yet (each needs its 3-7 days observed).</p>")
    else:
        b.append("<table><tr><th>Rule</th><th>Checked</th><th>Came true"
                 "</th><th>Verdict</th></tr>")
        for r in obs:
            b.append(f"<tr><td>{E(r['title'])}</td><td>"
                     f"{r['observed']['n']}</td><td>{pct(r['observed'])}"
                     f"</td><td>{_status(r['observed_status'])}</td></tr>")
        b.append("</table>")
    b.append("<p class=m>Checked against IMD gridded rain. This shows how "
             "often a warning came true; how many rain events we failed "
             "to warn about is in the forecast table below.</p></div>")
    return "".join(b)


def forecast_section(snap):
    b = ["<h2>Rain forecast against IMD rain</h2>"
         "<div class=box style='overflow-x:auto'>"]
    provs = (snap or {}).get("providers") or {}
    if not provs:
        b.append("<p>Not enough days with both a forecast and IMD "
                 "rain yet.</p></div>")
        return "".join(b)
    for prov, p in provs.items():
        b.append(f"<p><b>{E(PROVIDER.get(prov, prov))}</b>, last "
                 f"{snap['window_days']} days, all watched villages</p>"
                 "<table><tr><th>Day ahead</th><th>Rain days caught</th>"
                 "<th>False alarms</th><th>Skill</th><th>Error</th>"
                 "<th>Pairs</th></tr>")
        for lead, s in sorted(p["leads"].items(), key=lambda x: int(x[0])):
            r = s["rain_2_5"]
            label = "today" if lead == "0" else f"+{lead}"
            b.append(f"<tr><td>{label}</td><td>{pct(r['pod'])}</td>"
                     f"<td>{pct(r['far'])}</td><td>"
                     f"{_num(r['hss'])}</td><td>"
                     f"{_num(s['amount']['mae'], '{:.1f} mm')}</td>"
                     f"<td>{r['n']}</td></tr>")
        t = p["three_day_10mm"]
        b.append(f"<tr><td>next 3 days, &ge;10 mm</td><td>{pct(t['pod'])}"
                 f"</td><td>{pct(t['far'])}</td><td>{_num(t['hss'])}</td>"
                 f"<td></td><td>{t['n']}</td></tr></table>")
    b.append("<p class=m>Rain day = 2.5 mm or more (IMD). Caught = share "
             "of rain days the forecast said yes to. False alarms = share "
             "of forecast rain days that stayed dry. Skill (Heidke): 0 = "
             "no better than chance, 1 = perfect. Error = average miss "
             "in mm. IMD's day runs 08:30-08:30, the forecast day "
             "midnight-midnight, so daily scores are a little "
             "pessimistic; the 3-day row is fairer.</p></div>")
    return "".join(b)


def crop_section(snap, computed_on):
    b = ["<h2>Crop map: how often is a mapped crop right?</h2>"
         "<div class=box style='overflow-x:auto'>"]
    if not snap:
        b.append("<p>Not measured yet. The monthly check trains on some "
                 "villages and tests on others it has never seen.</p>"
                 "</div>")
        return "".join(b)
    for model in snap.get("models", []):
        m = model.get("metrics")
        b.append(f"<p><b>{E(model['name'])}</b> - {E(model['note'])}</p>")
        if not m:
            b.append(f"<p>{E(model.get('skipped', 'not run'))}</p>")
            continue
        b.append(f"<p>Overall right: {pct(m['overall'])} · kappa "
                 f"{_num(m['kappa'])} · {m['n']} held-out points in "
                 f"{model['folds']} spatial folds ({model['block_km']} km "
                 f"blocks). Training-fit figure the app used to show: "
                 f"{_num(model.get('train_fit'), '{:.0%}')}.</p>"
                 "<table><tr><th>Crop</th><th>Test points</th><th>Found "
                 "(of real)</th><th>Right (of mapped)</th></tr>")
        for c, s in m["per_class"].items():
            b.append(f"<tr><td>{E(c)}</td><td>{s['n']}</td><td>"
                     f"{pct(s['producers'])}</td><td>{pct(s['users'])}"
                     "</td></tr>")
        b.append("</table>")
    b.append(f"<p class=m>Measured {E(computed_on or '')}. Each fold "
             "trains on the other areas only, so nearby fields never "
             "help score themselves. Found = of the real crop, how much "
             "the map caught; Right = of what the map called that crop, "
             "how much really was.</p></div>")
    return "".join(b)


def body(alerts_snap, forecast_snap, crop_snap, crop_on, updated_on):
    return ("<h1>How often are we right?</h1><p class=m>Every alert and "
            "forecast is logged and checked afterwards. Ranges in "
            "brackets are 95% confidence intervals - with few answers "
            f"they are wide. Scores as of {E(updated_on)}.</p>"
            + alerts_section(alerts_snap)
            + forecast_section(forecast_snap)
            + crop_section(crop_snap, crop_on))
