import json
import urllib.parse

import pytest

from core import rules, share


@pytest.fixture(scope="module")
def tpl():
    t, labels, errors = share.load_templates()
    assert errors == []
    return t, labels


def _alert(rule_id="chilli_drying_rain_red", approved_by="", **feats):
    f = {"village": "Byadgi", "season": "ne", "ne_start": "2026-10-01",
         "season_cum_mm": 40.0, "season_normal_mm": 120.0,
         "season_dep_pct": -66.7, "season_category": "large_deficient",
         "dry_days": 12, "fc_rain_3d_mm": 15.2, "fc_max_rain_3d_mm": 6.0,
         "fc_rain_7d_mm": 2.0, "fc_tmax_mean_7d": 31.4,
         "fc_blotch_days_7d": 3, "fc_rainy_days_7d": 3,
         "fc_dry_run_days": 5}
    f.update(feats)
    return {"alert_id": "1126-K7QF", "as_of": "2026-11-26",
            "village_id": "byadgi", "rule_id": rule_id, "severity": "red",
            "title": "t", "text_en": "Conditions favour x.",
            "source": "TNAU guidance", "approved_by": approved_by,
            "features_json": json.dumps(f),
            "vintage_json": json.dumps({"forecast_provider": "ecmwf_open",
                                        "forecast_issued_on": "2026-11-26"}),
            "trace_json": json.dumps({"all": [["fc_rain_3d_mm", ">=", 10,
                                               15.2, True]], "any": []})}


def _signed(t):
    return {k: {l: dict(b, approved_by="Dr T") for l, b in v.items()}
            for k, v in t.items()}


def test_every_rule_has_three_signed_off_able_languages(tpl):
    t, _ = tpl
    for r in rules.load()[0]:
        assert set(t[r.id]) == {"kn", "ta", "en"}, r.id
        for lang, b in t[r.id].items():
            assert b["approved_by"] == ""            # nobody signed yet
            secs = share.voice_seconds(b["voice"], lang)
            assert 20 <= secs <= share.VOICE_MAX_S, (r.id, lang, secs)


def test_slots_are_known_features(tpl):
    t, _ = tpl
    known = {"village", "season_label", "season_start_label",
             "season_cum_mm", "season_normal_mm", "season_dep_pct",
             "season_category_label", "dry_days", "fc_rain_3d_mm",
             "fc_max_rain_3d_mm", "fc_rain_7d_mm", "fc_rainy_days_7d",
             "fc_dry_run_days", "fc_tmax_mean_7d", "fc_blotch_days_7d"}
    for rid, langs in t.items():
        for lang, b in langs.items():
            for k in ("headline", "text", "voice"):
                assert set(rules.slots(b[k])) <= known, (rid, lang, k)


def test_draft_is_not_shareable(tpl):
    t, labels = tpl
    k = share.kit(_alert(), "kn", t, labels)
    assert not k.shareable and k.wa_url is None
    assert "rule not signed off" in k.why_not
    k = share.kit(_alert(approved_by="Dr A"), "kn", t, labels)
    assert not k.shareable and "ಕನ್ನಡ text not signed off" in k.why_not


def test_signed_kit_text_and_whatsapp_link(tpl):
    t, labels = tpl
    k = share.kit(_alert(approved_by="Dr A"), "ta", _signed(t), labels)
    assert k.shareable and k.lang == "ta"
    assert "15 மி.மீ." in k.text
    assert "ECMWF open data (CC BY 4.0)" in k.footer      # attribution
    assert "TNAU guidance" in k.footer and "1126-K7QF" in k.footer
    assert k.wa_url.startswith("https://wa.me/?text=")
    assert urllib.parse.unquote(k.wa_url.split("=", 1)[1]) == k.message


def test_kannada_labels_localised(tpl):
    t, labels = tpl
    k = share.kit(_alert("season_rain_red", "Dr A"), "kn", _signed(t),
                  labels)
    assert "ಅಕ್ಟೋಬರ್ 1ರಿಂದ ಹಿಂಗಾರು ಮಳೆ 40 ಮಿ.ಮೀ." in k.text
    assert "(-67%)" in k.text
    assert "Forecast" not in k.footer        # rain rule: no fc_ conditions
    k = share.kit(_alert("season_rain_red", "Dr A"), "en", _signed(t),
                  labels)
    assert "NE monsoon rain since 1 Oct is 40 mm" in k.text


def test_missing_template_falls_back_to_english_draft(tpl):
    t, labels = tpl
    k = share.kit(_alert("no_such_rule", "Dr A"), "kn", t, labels)
    assert k.lang == "en" and not k.shareable
    assert k.text == "Conditions favour x."


def test_template_lint_catches_kannada_problems(tmp_path):
    p = tmp_path / "advice.toml"
    p.write_text('''
[chilli_black_thrips.kn]
approved_by = ""
headline = "x"
text = "ಥ್ರಿಪ್ಸ್ ಖಂಡಿತ ಬರುತ್ತದೆ. ಅನುಕೂಲ."
voice = "ಅನುಕೂಲ. ಸಿಂಪಡಿಸುವ ಮೊದಲು ನೋಡಿ. Use Coragen."
''', encoding="utf-8")
    t, _, errors = share.load_templates(p)
    assert t == {}
    assert "ಸಿಂಪಡಿಸುವ ಮೊದಲು" in errors[0] and "certainty" in errors[0]
    assert "coragen" in errors[0].lower()


def test_runs_split_latin_from_indic():
    assert share._runs("Byadgi: ಮಳೆ 40 ಮಿ.ಮೀ. · x", "kn") == [
        ("latin", "Byadgi: "), ("kn", "ಮಳೆ "), ("latin", "40 "),
        ("kn", "ಮಿ"), ("latin", "."), ("kn", "ಮೀ"), ("latin", ". · x")]


@pytest.mark.parametrize("lang", ["kn", "ta", "en"])
def test_card_png(tpl, lang):
    if lang != "en" and not share.raqm_ok():
        pytest.skip("libraqm not available")
    from PIL import Image
    import io
    t, labels = tpl
    for signed in (False, True):
        tt = _signed(t) if signed else t
        k = share.kit(_alert(approved_by="Dr A" if signed else ""), lang,
                      tt, labels)
        png = share.card_png(k)
        im = Image.open(io.BytesIO(png))
        assert im.size == (1080, 1350) and len(png) < 400_000


def test_card_refuses_indic_without_raqm(tpl, monkeypatch):
    t, labels = tpl
    monkeypatch.setattr(share, "raqm_ok", lambda: False)
    with pytest.raises(share.ShareError):
        share.card_png(share.kit(_alert(), "kn", t, labels))


def test_add_alert_event_appends(con, tmp_path):
    from core import store
    path = tmp_path / "intel.sqlite"
    c = store.connect(path)
    c.execute("INSERT INTO alert VALUES ('A1','now','2026-11-26','v','',"
              "'r','r','h','red','harvest','t','x','s','',0,'{}','{}','{}',"
              "NULL)")
    c.commit()
    store.add_alert_event("A1", "shared", "a@oneroot.farm", {"lang": "kn"},
                          path=path)
    assert c.execute("SELECT event, actor FROM alert_event").fetchall() == [
        ("shared", "a@oneroot.farm")]
    with pytest.raises(ValueError):
        store.add_alert_event("nope", "shared", path=path)
