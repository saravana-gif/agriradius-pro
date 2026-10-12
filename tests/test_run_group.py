import subprocess


def test_group_runs_each_job_in_own_process_and_survives_a_crash(
        monkeypatch, tmp_path):
    from core import store
    import jobs.run as jr
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "intel.sqlite")
    con = store.connect()
    con.execute("INSERT INTO job_runs (job, started_at, status) VALUES "
                "('rain', 'now', 'running')")
    con.commit()
    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd[-1])
        rc = {"rain": -11, "mandi_archive": 1}.get(cmd[-1], 0)
        return subprocess.CompletedProcess(cmd, rc)
    monkeypatch.setattr(jr.subprocess, "run", fake_run)
    assert jr.main(["daily"]) == 1
    assert calls == jr.GROUPS["daily"]           # all ran despite crash
    row = con.execute("SELECT status, detail FROM job_runs WHERE "
                      "job='rain'").fetchone()
    assert row == ("killed", "crashed (signal 11)")
    con.close()


def test_single_job_still_runs_in_process(monkeypatch):
    import jobs.run as jr
    seen = []
    monkeypatch.setattr(jr, "run_group", lambda g: seen.append(g) or 0)
    monkeypatch.setattr(jr, "run_job", lambda n, c, s: seen.append(n)
                        or True)
    import sqlite3
    real = sqlite3.connect(":memory:")
    real.execute("CREATE TABLE job_runs (status, finished_at)")
    monkeypatch.setattr("core.store.connect", lambda *a: real)
    assert jr.main(["publish"]) == 0 and seen == ["publish"]
