"""Static pages from the store: one village card per watched village and
the Monday portfolio. Served by Caddy, read without Streamlit or Earth
Engine, small enough for 2G (each page < 50 KB, no scripts, no web
fonts, no images inline).

    /c/<token>          village card   (data/public/c/<token>.html)
    /c/<token>/<file>   share-card PNGs of SIGNED-OFF alerts only
    /p/<token>          portfolio      (data/public/p/<token>.html)

Tokens are HMAC-SHA256 of the page name with a server-side secret
(PUBLISH_SECRET, else data/store/publish_secret, made on first run), so
links cannot be guessed and stay stable across runs. Pages carry
noindex; Caddy adds X-Robots-Tag too. Anyone holding a link can read
it: the village card shows only signed-off advice (drafts are counted,
not shown); the portfolio is internal (prices, drafts) - share it with
staff only.

On the server data/public is a symlink to /var/www/groundintel
(scripts/setup_lightsail.sh), because Caddy cannot read inside
/home/agri.
"""

import base64
import datetime
import hashlib
import hmac
import html
import json
import logging
import os
import secrets
import tempfile

from config import PROJECT_ROOT
from core import share, village_status
from core.rain_stats import CATEGORY_LABEL, SEASONS
from core.sources.forecast import ATTRIBUTION

log = logging.getLogger("jobs.publish")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
PUBLIC_DIR = PROJECT_ROOT / "data" / "public"
SECRET_FILE = PROJECT_ROOT / "data" / "store" / "publish_secret"
INDEX_FILE = PROJECT_ROOT / "data" / "store" / "publish_index.json"
DEFAULT_BASE_URL = "https://groundintel.oneroot.farm"
MAX_PAGE_BYTES = 50_000
STATE_LANG = {"Karnataka": "kn", "Tamil Nadu": "ta"}


# --------------------------------------------------------------- tokens

def _secret():
    from core.secrets import get
    s = get("PUBLISH_SECRET")
    if s:
        return str(s).encode()
    if not SECRET_FILE.exists():
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return SECRET_FILE.read_text().strip().encode()


def token(kind, ident):
    """26 lowercase base32 chars (130 bits) - unguessable, stable."""
    mac = hmac.new(_secret(), f"{kind}:{ident}".encode(), hashlib.sha256)
    return base64.b32encode(mac.digest()).decode().lower()[:26]


def base_url():
    from core.secrets import get
    return str(get("PUBLIC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def village_url(village_id):
    return f"{base_url()}/c/{token('village', village_id)}"


def portfolio_url():
    return f"{base_url()}/p/{token('portfolio', 'all')}"


# ---------------------------------------------------------------- files

def _write(path, data, public=True):
    """Atomic write. Public files are world-readable (Caddy runs as
    another user); private ones (the index) are owner-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if public:
        os.chmod(path.parent, 0o755)
    binary = isinstance(data, bytes)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb" if binary else "w",
                   **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(data)
    os.chmod(tmp, 0o644 if public else 0o600)
    os.replace(tmp, path)


# ----------------------------------------------------------------- html

E = html.escape
CSS = """body{font:15px/1.45 system-ui,-apple-system,"Noto Sans",sans-serif;
margin:0;color:#0f172a;background:#f8fafc}main{max-width:760px;margin:auto;
padding:14px}h1{font-size:21px;margin:4px 0}h2{font-size:16px;margin:18px 0
6px}.m{color:#475569;font-size:13px}.box{background:#fff;border:1px solid
#e2e8f0;border-radius:8px;padding:10px 12px;margin:8px 0}.red{color:#b91c1c}
.amber{color:#b45309}.green{color:#15803d}.grey{color:#64748b}table{
border-collapse:collapse;width:100%;font-size:13px}td,th{padding:5px 4px;
border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}
.d{display:inline-block;width:11px;height:11px;border-radius:6px;
margin-right:4px;vertical-align:-1px}.d.red{background:#dc2626}
.d.amber{background:#f59e0b}.d.green{background:#16a34a}.d.grey{
background:#cbd5e1}a{color:#0e7490}"""


def _page(title, body, updated):
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,"
            f"initial-scale=1'><meta name=robots content='noindex,"
            f"nofollow'><meta name=referrer content=no-referrer>"
            f"<title>{E(title)}</title><style>{CSS}</style></head><body>"
            f"<main>{body}<p class=m>Updated {E(updated)} IST · OneRoot "
            f"Ground Intel · Odds, not certainty: check the field before "
            f"acting.</p></main></body></html>")


def _num(v, unit="", signed=False):
    if v is None:
        return "?"
    s = f"{v:+.0f}" if signed else f"{v:.0f}"
    return s + unit


def _rain(mm):
    if mm is None:
        return "?"
    if mm == 0:
        return "0"
    return "&lt;1 mm" if mm < 1 else f"{mm:.0f} mm"


def _dot(c):
    return f"<span class='d {c}'></span>"


def _forecast_rows(con, vid, as_of):
    row = con.execute(
        "SELECT issued_on, provider FROM forecast_daily WHERE village_id=? "
        "AND issued_on<=? ORDER BY issued_on DESC LIMIT 1",
        (vid, as_of.isoformat())).fetchone()
    if not row:
        return None, []
    days = con.execute(
        "SELECT date, rain_mm, tmax, tmin FROM forecast_daily WHERE "
        "village_id=? AND issued_on=? AND provider=? AND date>=? ORDER BY "
        "date LIMIT 7", (vid, row[0], row[1], as_of.isoformat())).fetchall()
    return row, days


def village_card(con, r, as_of, updated, cards):
    """HTML for one village. `cards` = {alert_id: [(lang, file)]}."""
    vid = r["village_id"]
    title = f"{r['village']} - village card"
    sea = r["season"]
    b = [f"<h1>{E(r['village'])}</h1><p class=m>{E(r['district'] or '')}"
         f"{', ' + E(r['state']) if r['state'] else ''} · crops: "
         f"{E(', '.join(r['crops']) or '-')}</p>"]

    b.append("<h2>Rain this season</h2><div class=box>")
    if sea:
        cat = CATEGORY_LABEL.get(r["season_category"], "?")
        b.append(
            f"<p>{_dot(r['rag']['rain'])}<b>{E(SEASONS[sea][0])}</b>: "
            f"{_num(r['season_cum_mm'], ' mm')} against a usual "
            f"{_num(r['season_normal_mm'], ' mm')} - "
            f"<b class={r['rag']['rain']}>"
            f"{_num(r['season_dep_pct'], '%', True)} ({E(cat)})</b></p>")
    else:
        b.append("<p>No monsoon season running.</p>")
    gap = " (at least - a day is missing)" if r["dry_days_gap"] else ""
    b.append(f"<p>{_dot(r['rag']['dry'])}Days in a row without useful "
             f"rain (&lt;2.5 mm): <b>{_num(r['dry_days'])}</b>{gap}</p>")
    if r["spi3_label"]:
        b.append(f"<p>Last 3 months: {E(r['spi3_label'])} (SPI-3 "
                 f"{r['spi3']:+.1f})</p>")
    b.append(f"<p class=m>Observed rain to {E(r['obs_through'] or '?')}"
             f" (IMD gridded rainfall); normal: CHIRPS 1981-2025.</p>"
             "</div>")

    fc, days = _forecast_rows(con, vid, as_of)
    b.append("<h2>Next 7 days</h2><div class=box>")
    if days:
        b.append("<table><tr><th>Day</th><th>Rain</th><th>Max</th>"
                 "<th>Min</th></tr>")
        for d, rain, tmax, tmin in days:
            dd = datetime.date.fromisoformat(d)
            b.append(f"<tr><td>{dd:%a %d %b}</td><td>{_rain(rain)}</td>"
                     f"<td>{_num(tmax, '°')}</td><td>{_num(tmin, '°')}"
                     "</td></tr>")
        b.append(f"</table><p class=m>Forecast: "
                 f"{E(ATTRIBUTION.get(fc[1], fc[1]))}, issued {E(fc[0])}. "
                 "Forecasts can be wrong, more so after 3 days.</p>")
    else:
        b.append("<p>No forecast yet.</p>")
    b.append("</div>")

    signed = [a for a in r["alerts"] if a["approved_by"]]
    drafts = len(r["alerts"]) - len(signed)
    b.append("<h2>Advice this week</h2><div class=box>")
    if not signed:
        b.append("<p>No signed-off advice this week.</p>")
    for a in signed:
        b.append(f"<p>{_dot(a['severity'])}<b>{E(a['title'])}</b> "
                 f"<span class=m>{E(a['as_of'])} · {E(a['alert_id'])}"
                 "</span></p>")
        files = cards.get(a["alert_id"], [])
        if files:
            links = " · ".join(
                f"<a href='{token('village', vid)}/{E(fn)}'>"
                f"{E(share.LANG_NAME[lang])}</a>" for lang, fn in files)
            b.append(f"<p class=m>Card: {links}</p>")
    if drafts:
        b.append(f"<p class=m>{drafts} draft alert(s) waiting for "
                 "agronomist sign-off - not shown here.</p>")
    b.append("</div>")
    return title, _page(title, "".join(b), updated)


def portfolio(rows, as_of, updated):
    monday = as_of - datetime.timedelta(days=as_of.weekday())
    n_red = sum(any(v == "red" for k, v in r["rag"].items()
                    if k != "report") for r in rows)
    week = monday.strftime("%a %d %b %Y")
    b = [f"<h1>Weekly portfolio</h1><p class=m>Week of {week}"
         f" · {len(rows)} villages · {n_red} with a red flag (rain, "
         "dry spell, crop risk or price) · worst first. INTERNAL - "
         "includes drafts and mandi prices; do not forward.</p>",
         "<div class=box style='overflow-x:auto'><table><tr>"
         "<th>Village</th><th>Rain vs normal</th><th>Dry days</th>"
         "<th>Crop-stage risk (7 d)</th><th>Price 7 d vs prior 14 d</th>"
         "<th>Last field report</th></tr>"]
    for r in rows:
        g = r["rag"]
        pm = r["price_move"]
        price = (f"{E(pm[0])} {pm[1]:+.0f}%" if pm else "?")
        rep = ("never" if r["report_days"] is None
               else f"{r['report_days']} d ago")
        risk = E(r["risk_label"])
        if r["alerts"] and not any(a["approved_by"] for a in r["alerts"]):
            risk += " <span class=m>(draft)</span>"
        b.append(
            f"<tr><td><a href='../c/{token('village', r['village_id'])}'>"
            f"{E(r['village'])}</a><br><span class=m>"
            f"{E(r['district'] or '')} · {E(', '.join(r['crops']))}</span>"
            f"</td><td>{_dot(g['rain'])}"
            f"{_num(r['season_dep_pct'], '%', True)}</td>"
            f"<td>{_dot(g['dry'])}{_num(r['dry_days'])}</td>"
            f"<td>{_dot(g['risk'])}{risk}</td>"
            f"<td>{_dot(g['price'])}{price}</td>"
            f"<td>{_dot(g['report'])}{rep}</td></tr>")
    b.append("</table></div><p class=m>Thresholds: rain red ≤ -40%, "
             "amber ≤ -20%; dry spell red ≥ 21 d, amber ≥ 10 d; price "
             "move (state median, Agmarknet) red ≥ 20%, amber ≥ 10%; "
             "field report red > 14 d or never, amber > 7 d. Grey = no "
             "data.</p>")
    return _page("Weekly portfolio", "".join(b), updated)


# ------------------------------------------------------------------ run

def _cards_for(con, r, out_dir):
    """PNG share cards for signed-off alerts that have a signed
    template. {alert_id: [(lang, filename)]}."""
    cards = {}
    signed = [a for a in r["alerts"] if a["approved_by"]]
    if not signed:
        return cards
    t, labels, _ = share.load_templates()
    first = STATE_LANG.get(r["state"], "en")
    for a in signed:
        cur = con.execute("SELECT * FROM alert WHERE alert_id=?",
                          (a["alert_id"],))
        alert = dict(zip([c[0] for c in cur.description], cur.fetchone()))
        for lang in dict.fromkeys([first, "en"]):
            k = share.kit(alert, lang, t, labels)
            if not k.shareable:
                continue
            fn = f"{a['alert_id']}-{k.lang}.png"
            try:
                _write(out_dir / fn, share.card_png(k))
            except share.ShareError as e:
                log.warning("%s: %s", fn, e)
                continue
            cards.setdefault(a["alert_id"], []).append((k.lang, fn))
    return cards


def run(con):
    now = datetime.datetime.now(IST)
    as_of = now.date()
    updated = now.strftime("%d %b %Y %H:%M")
    rows = village_status.village_rows(con, as_of)
    if not rows:
        return {"rows": 0, "status": "ok", "detail": "no villages yet"}
    index, too_big = {}, []
    for r in rows:
        tok = token("village", r["village_id"])
        cards = _cards_for(con, r, PUBLIC_DIR / "c" / tok)
        _, page = village_card(con, r, as_of, updated, cards)
        if len(page.encode()) > MAX_PAGE_BYTES:
            too_big.append(r["village_id"])
        _write(PUBLIC_DIR / "c" / f"{tok}.html", page)
        index[r["village_id"]] = {"village": r["village"],
                                  "url": village_url(r["village_id"])}
    page = portfolio(rows, as_of, updated)
    if len(page.encode()) > MAX_PAGE_BYTES:
        too_big.append("portfolio")
    _write(PUBLIC_DIR / "p" / f"{token('portfolio', 'all')}.html", page)

    # Pages of villages no longer watched: replace, never delete.
    keep = {f"{token('village', r['village_id'])}.html" for r in rows}
    gone = 0
    cdir = PUBLIC_DIR / "c"
    for p in cdir.glob("*.html"):
        if p.name not in keep and "no longer watched" not in p.read_text(
                encoding="utf-8")[:2000]:
            _write(p, _page("Not watched", "<h1>No longer watched</h1>"
                            "<p>This village is no longer watched - "
                            "this page is not updated.</p>", updated))
            gone += 1

    _write(INDEX_FILE, json.dumps({"portfolio": portfolio_url(),
                                   "villages": index}, indent=1),
           public=False)
    detail = f"{len(rows)} village cards + portfolio written"
    if gone:
        detail += f"; {gone} old pages marked no longer watched"
    status = "ok"
    if too_big:
        detail += f"; OVER 50 KB: {', '.join(too_big)}"
        status = "partial"
    return {"rows": len(rows) + 1, "detail": detail, "status": status}
