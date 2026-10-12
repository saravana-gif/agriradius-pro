"""The Alerts & share kit page in Streamlit's AppTest."""

import datetime as dt
import json
from pathlib import Path

PAGE = Path(__file__).parents[1] / "pages" / "1_Alerts_and_share.py"


def test_alerts_page_shows_drafts_without_share_buttons(monkeypatch,
                                                       tmp_path):
    from streamlit.testing.v1 import AppTest
    from core import store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "intel.sqlite")
    monkeypatch.setenv("DEV_EMAIL", "officer@oneroot.farm")
    con = store.connect()
    con.execute("INSERT INTO villages VALUES ('byadgi','Byadgi','Haveri',"
                "'Karnataka',14.67,75.49,'chilli','t','now')")
    feats = json.dumps({"village": "Byadgi", "fc_rain_3d_mm": 15.2})
    trace = json.dumps({"all": [["fc_rain_3d_mm", ">=", 10, 15.2, True]],
                        "any": []})
    con.execute("INSERT INTO alert VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,?,?)", ("1012-AAAA", "now", dt.date.today().isoformat(),
                           "byadgi", "chilli", "chilli_drying_rain_red",
                           "chilli_drying", "h", "red", "harvest",
                           "Chilli drying", "Conditions favour x", "src", "",
                           0, feats, trace,
                           json.dumps({"forecast_provider": "ecmwf_open"}),
                           "abc"))
    con.commit()
    con.close()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception
    assert "1012-AAAA" in at.expander[0].label
    assert "draft" in at.expander[0].label
    warn = [w.value for w in at.warning]
    assert len(warn) == 3 and all("Not shareable yet" in w for w in warn)
    assert not [b for b in at.button if "shared" in b.label]
