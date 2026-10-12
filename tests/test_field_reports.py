import datetime as dt
import io
import json

import pytest

from core import field_reports as fr

IST = fr.IST
V = {"village_id": "byadgi", "village": "Byadgi", "lat": 14.673,
     "lon": 75.487}


@pytest.fixture
def local(monkeypatch, tmp_path):
    monkeypatch.setattr(fr, "LOCAL_CSV", tmp_path / "field_reports.csv")
    monkeypatch.setattr(fr, "PHOTO_DIR", tmp_path / "photos")
    from core import sheets
    monkeypatch.setattr(sheets, "is_enabled", lambda: False)
    return tmp_path


def test_nearest_and_haversine():
    vs = [V, {"village_id": "erode", "village": "Erode", "lat": 11.341,
              "lon": 77.717}]
    near = fr.nearest(vs, 14.70, 75.50)
    assert near[0][1]["village_id"] == "byadgi" and near[0][0] < 4
    assert 430 < fr.haversine_km(14.673, 75.487, 11.341, 77.717) < 450


def test_make_row_validation():
    r = fr.make_row(officer="a@oneroot.farm", village=V, event="sown",
                    crop=" Maize ", qty=2, unit="acres", lat=14.6731234,
                    lon=75.4871234, accuracy=12.4, distance_km=0.3)
    assert r["crop"] == "maize" and r["lat"] == 14.67312
    assert r["report_id"].startswith("R") and r["event"] == "sown"
    with pytest.raises(ValueError, match="alert"):
        fr.make_row(officer="", village=V, event="feedback", verdict="yes")
    with pytest.raises(ValueError, match="Yes, Partly or No"):
        fr.make_row(officer="", village=V, event="checkback",
                    alert_id="1012-AAAA", verdict="maybe")
    with pytest.raises(ValueError):
        fr.make_row(officer="", village=V, event="party")
    with pytest.raises(ValueError):
        fr.make_row(officer="", village=V, event="rain", qty=-3)


def test_save_and_read_local_csv(local):
    for ev in ("rain", "sown"):
        assert fr.save(fr.make_row(officer="o", village=V, event=ev,
                                   qty=12, unit="mm")) == "csv"
    rows, src = fr.read_all()
    assert src == "csv" and [r["event"] for r in rows] == ["rain", "sown"]
    assert set(rows[0]) == set(fr.COLUMNS)


def test_save_photo_shrinks(local):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), (120, 160, 80)).save(buf, "JPEG")
    name = fr.save_photo("R1", buf.getvalue())
    im = Image.open(local / "photos" / name)
    assert max(im.size) == 1280 and name == "R1.jpg"


def _alert(con, aid, as_of):
    con.execute("INSERT INTO alert VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?,?)", (aid, "now", as_of, "byadgi", "", "r", "r", "h",
                             "amber", "weather", "Title", "x", "s", "", 0,
                             "{}", "{}", "{}", None))
    con.commit()


def test_ingest_job(con, local):
    import jobs.field_reports as jf
    _alert(con, "1001-AAAA", "2026-10-01")
    now = dt.datetime(2026, 10, 9, 9, 0, tzinfo=IST)
    rows = [fr.make_row(officer="o", village=V, event="sown", crop="maize",
                        now=now),
            fr.make_row(officer="o", village=V, event="checkback",
                        alert_id="1001-AAAA", verdict="partly", now=now),
            fr.make_row(officer="o", village=V, event="feedback",
                        alert_id="9999-NONE", verdict="no", now=now)]
    for r in rows:
        fr.save(r)
    res = jf.run(con)
    assert res["status"] == "ok" and "1 refer to an unknown alert" in \
        res["detail"]
    assert con.execute("SELECT COUNT(*) FROM field_report").fetchone()[0] \
        == 3
    ev = con.execute("SELECT event, actor, detail_json FROM alert_event"
                     ).fetchall()
    assert len(ev) == 1 and ev[0][0] == "checkback"
    assert json.loads(ev[0][2])["verdict"] == "partly"
    jf.run(con)                                   # idempotent
    assert con.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0] \
        == 1
    from core import features, village_status
    assert features.sown_days(con, "byadgi", dt.date(2026, 10, 20)) == {
        "maize": 11}
    assert village_status.last_report_days(con, "byadgi",
                                           dt.date(2026, 10, 20)) == 11


def test_ingest_skips_bad_rows(con, local):
    import jobs.field_reports as jf
    fr.LOCAL_CSV.write_text(",".join(fr.COLUMNS) + "\n" +
                            "R1,,,,byadgi,,,,,,rain,,,,,,,\n")  # no date
    res = jf.run(con)
    assert res["rows"] == 0 and "1 rows skipped" in res["detail"]


def test_days_since_sown_reaches_rules(con, local):
    """The crop-stage clock is a rule feature for the crop tested."""
    import jobs.alerts as ja
    from core import rules
    con.execute("INSERT INTO villages VALUES ('byadgi','Byadgi','Haveri',"
                "'Karnataka',14.67,75.49,'maize','t','now')")
    con.execute("INSERT INTO field_report (report_id, reported_on, "
                "village_id, event, crop, ingested_at) VALUES ('R1', "
                "'2026-10-01', 'byadgi', 'sown', 'maize', 'now')")
    r = rules._parse({"id": "faw", "title": "t", "kind": "pest",
                      "severity": "amber", "source": "s", "crops": ["maize"],
                      "draft_en": "Conditions favour x. Scout before "
                                  "spraying.",
                      "all": [["days_since_sown", ">=", 10],
                              ["days_since_sown", "<=", 40]]})
    from core import features
    feats, _ = features.build(con, "byadgi", dt.date(2026, 10, 20))
    c = ja.candidates([r], feats, ["maize"], dt.date(2026, 10, 20))
    assert [(x[0].id, x[1]) for x in c] == [("faw", "maize")]


def test_sheet_path_writes_raw_and_reads_back(monkeypatch):
    """With Sheets on: rows go in RAW (no date reformatting) and come
    back as strings the ingest can parse, whatever types gspread gives."""
    import pandas as pd
    from core import sheets
    sent = {}
    monkeypatch.setattr(sheets, "is_enabled", lambda: True)
    monkeypatch.setattr(sheets, "append_row",
                        lambda tab, row, cols, value_input_option: sent.update(
                            tab=tab, mode=value_input_option, row=row))
    r = fr.make_row(officer="o", village=V, event="rain", qty=7)
    assert fr.save(r) == "sheet:FieldReports"
    assert sent["mode"] == "RAW" and sent["tab"] == "FieldReports"
    back = pd.DataFrame([{**r, "qty": 7, "lat": ""}])   # gspread numerics
    monkeypatch.setattr(sheets, "read_existing", lambda tab: back)
    rows, src = fr.read_all()
    assert rows[0]["qty"] == "7" and rows[0]["reported_on"] == \
        r["reported_on"]
