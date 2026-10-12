"""Shared fixtures. Run with:  python -m pytest tests -q

No network: every test that touches a data source stubs it."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session", autouse=True)
def headless():
    from jobs import headless as h
    h.setup()
    return h


@pytest.fixture
def con(tmp_path):
    from core import store
    c = store.connect(tmp_path / "intel.sqlite")
    yield c
    c.close()


@pytest.fixture
def villages(monkeypatch):
    """Two watched villages, no Sheet."""
    import pandas as pd
    from core import watched_villages as wv
    df = pd.DataFrame([
        {"village_id": "erode", "village": "Erode", "district": "Erode",
         "state": "Tamil Nadu", "lat": 11.341, "lon": 77.717,
         "crops": "turmeric"},
        {"village_id": "byadgi", "village": "Byadgi", "district": "Haveri",
         "state": "Karnataka", "lat": 14.673, "lon": 75.487,
         "crops": "chilli;maize"},
    ], columns=wv.COLUMNS)
    monkeypatch.setattr(wv, "load", lambda: (df.copy(), "test"))
    return df
