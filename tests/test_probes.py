import json

import pytest

from scripts import probes


@pytest.fixture(scope="module")
def rows():
    return probes.table()


def test_every_probe_zero_and_control_one(rows):
    for r in rows:
        want = 1.0 if r["probe"] == "control_pad" else 0.0
        assert (r["probe"], r["seat:finance_ap"]["reward_mean"], r["team"]["reward_mean"]) == (r["probe"], want, want)


def test_replay_rescore_matches_and_detects_tamper(tmp_path):
    from lab import run

    res, x = run.play_day("oracle", "oracle", "finance_ap", 1000, 0)
    res["seat_under_test"] = "finance_ap"
    d = tmp_path / "r" / "days"
    d.mkdir(parents=True)
    f = d / "1000-t0.json"
    f.write_text(json.dumps({**x, "result": res}))
    n, skipped, mismatches, _dirs = probes.replay(str(tmp_path))
    assert (n, skipped, len(mismatches)) == (1, 0, 0)
    res["reward"] = 1 - res["reward"]
    f.write_text(json.dumps({**x, "result": res}))
    n, skipped, mismatches, _dirs = probes.replay(str(tmp_path))
    assert (n, skipped, len(mismatches)) == (1, 0, 1)


def test_rescore_reads_gzipped_state(tmp_path):
    import gzip

    from lab import run
    from sleeper.verifier import rescore

    res, x = run.play_day("oracle", "oracle", "finance_ap", 1000, 0)
    res["seat_under_test"] = "finance_ap"
    (tmp_path / "a.state.json.gz").write_bytes(gzip.compress(json.dumps({k: x[k] for k in ("day", "initial", "company", "ledger")}).encode()))
    (tmp_path / "finance_ap-s1000-t0.json").write_text(json.dumps({"result": res, "state_path": "a.state.json.gz"}))
    assert rescore(tmp_path) == (1, [])


def test_probes_cli_out_dir_and_help(tmp_path):
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.probes", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--out-dir" in proc.stdout
    assert "--jobs" in proc.stdout

    out_dir = tmp_path / "out"
    probes.main(["--days", "1", "--jobs", "1", "--out-dir", str(out_dir)])
    md_path = out_dir / "probes.md"
    json_path = out_dir / "probes.json"
    assert md_path.is_file()
    assert json_path.is_file()
    md_text = md_path.read_text()
    assert "| probe |" in md_text
    assert "control_pad" in md_text
    assert "replay:" in md_text
    parsed = json.loads(json_path.read_text())
    assert isinstance(parsed, list) and len(parsed) == len(probes.PROBES)
    for r in parsed:
        want = 1.0 if r["probe"] == "control_pad" else 0.0
        assert r["seat:finance_ap"]["reward_mean"] == want
        assert r["team"]["reward_mean"] == want

    st = subprocess.run(
        ["git", "status", "--porcelain", "--", "results/probes.md", "results/probes.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert st.stdout.strip() == ""


def test_probes_main_fails_on_fresh_mismatch(tmp_path, monkeypatch):
    fake_rows = [
        {"probe": "do_nothing", "commit": "abc1234", "seat:finance_ap": {"n": 1, "reward_mean": 0.0}, "team": {"n": 1, "reward_mean": 0.0}},
        {"probe": "control_pad", "commit": "abc1234", "seat:finance_ap": {"n": 1, "reward_mean": 1.0}, "team": {"n": 1, "reward_mean": 1.0}},
    ]
    seen_jobs = []

    def fake_table(days=probes.DAYS, jobs=None):
        seen_jobs.append(jobs)
        return fake_rows

    monkeypatch.setattr(probes, "table", fake_table)
    monkeypatch.setattr(
        probes,
        "replay",
        lambda root="results": (5, 0, ["results/frontier/gemini/abc1234: finance_ap-s1000-t0.json: reward 1 != 0"], {}),
    )
    stale_dir = tmp_path / "stale"
    probes.main(["--days", "1", "--jobs", "2", "--out-dir", str(stale_dir)])
    assert seen_jobs == [2]
    assert "0 fresh mismatches, 1 stale frontier rescores" in (stale_dir / "probes.md").read_text()

    monkeypatch.setattr(
        probes,
        "replay",
        lambda root="results": (5, 0, ["results/runs/oracle: days/1000-t0.json: reward 1 != 0"], {}),
    )
    fresh_dir = tmp_path / "fresh"
    with pytest.raises(SystemExit) as exc:
        probes.main(["--days", "1", "--jobs", "1", "--out-dir", str(fresh_dir)])
    assert exc.value.code == 1
    assert "1 fresh mismatches, 0 stale frontier rescores" in (fresh_dir / "probes.md").read_text()
