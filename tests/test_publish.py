import datetime as dt
import json
import re

import pytest

D = dt.date


@pytest.fixture
def pub(monkeypatch, tmp_path):
    import jobs.publish as jp
    monkeypatch.setattr(jp, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(jp, "SECRET_FILE", tmp_path / "store" / "secret")
    monkeypatch.setattr(jp, "INDEX_FILE", tmp_path / "store" / "index.json")

    class _DT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 11, 26, 5, 40, tzinfo=tz)
    monkeypatch.setattr(jp.datetime, "datetime", _DT)
    return jp


def _seed(con, n=40):
    today = D(2026, 11, 26)
    for i in range(n):
        vid = f"v{i:02d}"
        state = "Karnataka" if i % 2 else "Tamil Nadu"
        con.execute("INSERT INTO villages VALUES (?,?,?,?,?,?,?,?,?)",
                    (vid, f"Village <{i}>", "Dist", state, 12.0, 77.0,
                     "chilli;maize", "test", "now"))
        f = {"season": "ne", "season_cum_mm": 50.0 + i,
             "season_normal_mm": 200.0, "season_dep_pct": -75.0 + 2 * i,
             "season_category": "large_deficient", "dry_days": i,
             "dry_days_gap": False, "spi3": -1.2, "spi3_label":
             "moderately dry", "obs_through": "2026-11-25"}
        con.execute("INSERT INTO village_features VALUES (?,?,?,?,?,?)",
                    (vid, today.isoformat(), "rain", json.dumps(f), "{}",
                     "now"))
        for k in range(7):
            con.execute(
                "INSERT INTO forecast_daily (village_id, issued_on, "
                "provider, date, rain_mm, tmax, tmin, fetched_at) VALUES "
                "(?,?,?,?,?,?,?,?)", (vid, today.isoformat(), "ecmwf_open",
                                      (today + dt.timedelta(days=k))
                                      .isoformat(), [0, 0.4, 3.2, None,
                                                     12, 0, 0][k], 31.2,
                                      20.1, "now"))
    # Karnataka chilli: price up ~25 %
    for k in range(21):
        d = (today - dt.timedelta(days=k)).isoformat()
        con.execute("INSERT INTO mandi_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,"
                    "?,?,?)", (d, "Karnataka", "Haveri", "Byadgi",
                               "Dry Chillies", "", "", None, None,
                               25000.0 if k < 7 else 20000.0, "Rs/qtl",
                               "ok", "now", "now"))
    tr = json.dumps({"all": [["fc_rain_3d_mm", ">=", 10, 15.0, True]],
                     "any": []})
    fe = json.dumps({"village": "Village <1>", "fc_rain_3d_mm": 15.0})
    for aid, appr in (("1126-SIGN", "Dr A"), ("1126-DRFT", "")):
        con.execute("INSERT INTO alert VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,"
                    "?,?,?,?,?,?)",
                    (aid, "now", today.isoformat(), "v01", "chilli",
                     "chilli_drying_rain_red", "chilli_drying", "h", "red",
                     "harvest", "Chilli drying: heavy rain possible",
                     "SECRET DRAFT TEXT " + aid, "src", appr, int(bool(appr)),
                     fe, tr, json.dumps({"forecast_provider": "ecmwf_open"}),
                     "abc"))
    con.commit()


def test_publish_pages(con, pub):
    _seed(con)
    res = pub.run(con)
    assert res["status"] == "ok", res
    cdir = pub.PUBLIC_DIR / "c"
    pages = list(cdir.glob("*.html"))
    assert len(pages) == 40
    tok = pub.token("village", "v01")
    assert re.fullmatch(r"[a-z2-7]{26}", tok)
    assert tok == pub.token("village", "v01")           # stable
    assert tok != pub.token("village", "v02")
    html = (cdir / f"{tok}.html").read_text()
    assert len(html.encode()) < 50_000
    assert "noindex" in html and "<script" not in html
    assert "Village &lt;1&gt;" in html                  # escaped
    assert "-73% (Large deficient)" in html
    assert "ECMWF open data (CC BY 4.0)" in html
    assert "SECRET DRAFT TEXT" not in html               # never on a card
    assert "1 draft alert(s) waiting" in html
    assert "Chilli drying: heavy rain possible" in html  # signed title
    assert (cdir / f"{tok}.html").stat().st_mode & 0o777 == 0o644

    port = pub.PUBLIC_DIR / "p" / f"{pub.token('portfolio', 'all')}.html"
    p = port.read_text()
    assert len(p.encode()) < 50_000 and p.count("<tr>") == 41
    assert f"../c/{tok}" in p
    assert "chilli +25%" in p                            # Karnataka rows
    # worst first: v01 has red rain, red crop risk, red price, no report
    rows = re.findall(r"Village &lt;(\d+)&gt;</a>", p)
    assert rows[0] == "1"
    assert "never" in p                                  # no field reports

    idx = json.loads(pub.INDEX_FILE.read_text())
    assert idx["villages"]["v01"]["url"].endswith(f"/c/{tok}")
    assert pub.INDEX_FILE.stat().st_mode & 0o777 == 0o600
    assert pub.SECRET_FILE.stat().st_mode & 0o777 == 0o600


def test_signed_alert_gets_card_png_only_when_template_signed(
        con, pub, monkeypatch):
    from core import share
    _seed(con, 2)
    real = share.load_templates

    def signed(path=None):
        t, labels, err = real(path)
        return ({k: {l: dict(b, approved_by="Dr T") for l, b in v.items()}
                 for k, v in t.items()}, labels, err)
    monkeypatch.setattr(share, "load_templates", signed)
    pub.run(con)
    tok = pub.token("village", "v01")
    files = sorted(p.name for p in (pub.PUBLIC_DIR / "c" / tok).iterdir())
    want = ["1126-SIGN-en.png"] + (["1126-SIGN-kn.png"]
                                   if share.raqm_ok() else [])
    assert files == sorted(want)
    html = (pub.PUBLIC_DIR / "c" / f"{tok}.html").read_text()
    assert f"{tok}/1126-SIGN-en.png" in html


def test_dropped_village_page_is_replaced_not_deleted(con, pub):
    _seed(con, 3)
    pub.run(con)
    con.execute("DELETE FROM villages WHERE village_id='v02'")
    con.commit()
    res = pub.run(con)
    gone = pub.PUBLIC_DIR / "c" / f"{pub.token('village', 'v02')}.html"
    assert gone.exists() and "No longer watched" in gone.read_text()
    assert "1 old pages" in res["detail"]


def test_rag_thresholds():
    from core import village_status as vs
    assert [vs.rag_rain(x) for x in (None, -45, -40, -39, -20, -19)] == [
        "grey", "red", "red", "amber", "amber", "green"]
    assert [vs.rag_dry(x) for x in (None, 21, 20, 10, 9)] == [
        "grey", "red", "amber", "amber", "green"]
    assert [vs.rag_price(x) for x in (None, -20, 19.9, 10, 9)] == [
        "grey", "red", "amber", "amber", "green"]
    assert [vs.rag_report(x) for x in (None, 15, 14, 8, 7)] == [
        "red", "red", "amber", "amber", "green"]
