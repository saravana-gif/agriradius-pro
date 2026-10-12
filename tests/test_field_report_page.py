"""The field-report page in Streamlit's AppTest (no browser, no GPS)."""

import datetime as dt

import pytest

from core import field_reports as fr

PAGE = "pages/2_Field_report.py"


@pytest.fixture
def app(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from core import sheets, store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "intel.sqlite")
    monkeypatch.setattr(fr, "LOCAL_CSV", tmp_path / "field_reports.csv")
    monkeypatch.setattr(sheets, "is_enabled", lambda: False)
    con = store.connect()
    con.execute("INSERT INTO villages VALUES ('byadgi','Byadgi','Haveri',"
                "'Karnataka',14.67,75.49,'chilli;maize','t','now')")
    old = (dt.date.today() - dt.timedelta(days=8)).isoformat()
    con.execute("INSERT INTO alert VALUES ('0101-OLD1','now',?,'byadgi','',"
                "'r','r','h','red','weather','Season rain red','x','s','',0,"
                "'{}','{}','{}',NULL)", (old,))
    con.commit()
    con.close()
    from pathlib import Path
    at = AppTest.from_file(str(Path(__file__).parents[1] / PAGE),
                           default_timeout=60)
    # conftest runs jobs.headless.setup(), whose secret lookup reads
    # env vars (not st.secrets) - so the dev sign-in goes in the env.
    monkeypatch.setenv("DEV_EMAIL", "officer@oneroot.farm")
    return at


def test_submit_report_and_checkback(app):
    at = app
    at.run()
    assert not at.exception
    at.radio[0].set_value("rain").run()
    at.number_input[0].set_value(18.0)
    at.button[1].click().run()          # [0] = GPS, [1] = Save (form)
    assert not at.exception, at.exception
    assert any("Saved" in s.value for s in at.success)
    rows, _ = fr.read_all()
    assert rows[0]["event"] == "rain" and rows[0]["qty"] == "18.0"
    assert rows[0]["officer"] == "officer@oneroot.farm"
    assert rows[0]["village_id"] == "byadgi" and rows[0]["lat"] == ""

    # 7-day check-back: Yes / Partly / No for the 8-day-old alert
    labels = [b.label for b in at.button]
    assert labels[-3:] == ["Yes", "Partly", "No"]
    at.button[-2].click().run()
    rows, _ = fr.read_all()
    assert rows[-1]["event"] == "checkback"
    assert rows[-1]["alert_id"] == "0101-OLD1"
    assert rows[-1]["verdict"] == "partly"
    assert "Yes" not in [b.label for b in at.button]   # answered, gone
