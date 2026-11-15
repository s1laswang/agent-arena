from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path

from canary.redteam.anticheat import harbor_consistency

ROOT = Path(__file__).resolve().parents[1]
REHEARSAL_DIR = ROOT / "results" / "harbor" / "rehearsal-fr8"
REPORT_PATH = ROOT / "docs" / "reports" / "harbor_rehearsal_fr8.md"
EXPECTED_JOBS = (
    "oracle",
    "do_nothing",
    "stop_early",
    "cheat_probe",
    "opencode-1",
    "opencode-2",
    "opencode-3",
)


def _load_script(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_harbor_rehearsal_fr8_layout_and_build_provenance():
    assert REHEARSAL_DIR.is_dir()
    job_dirs = {p.name for p in REHEARSAL_DIR.iterdir() if p.is_dir() and (p / "result.json").is_file()}
    assert job_dirs == set(EXPECTED_JOBS)
    trial_results = sorted(REHEARSAL_DIR.glob("*/*/result.json"))
    assert len(trial_results) == 70
    expected_tasks = [f"canary-hard-{seed}" for seed in range(900000, 900010)]
    for job in EXPECTED_JOBS:
        trials = sorted((REHEARSAL_DIR / job).glob("canary-hard-*/result.json"))
        assert len(trials) == 10
        prefixes = sorted(p.parent.name.split("__", 1)[0] for p in trials)
        assert prefixes == expected_tasks

    build_txt = REHEARSAL_DIR / "BUILD.txt"
    assert build_txt.is_file()
    build_content = build_txt.read_text(encoding="utf-8")
    assert "8cd20d9e" in build_content
    assert "harbor: 0.26.0" in build_content

    assert REPORT_PATH.is_file()
    report_content = REPORT_PATH.read_text(encoding="utf-8")
    assert "8cd20d9e" in report_content
    assert "results/harbor/rehearsal-fr8" in report_content


def test_harbor_rehearsal_fr8_panel_fix_d_and_trajectory_counts():
    report_content = REPORT_PATH.read_text(encoding="utf-8")
    assert "Panel Fix D" in report_content
    assert "1bc3e281" in report_content
    assert "58716742" in report_content
    assert "data.detail" in report_content
    assert "30/30 OpenCode trials have `agent/opencode.txt` logs" in report_content
    assert "29/30 have `agent/trajectory.json`" in report_content

    opencode_logs = sorted(REHEARSAL_DIR.glob("opencode-*/canary-hard-*/agent/opencode.txt"))
    opencode_trajs = sorted(REHEARSAL_DIR.glob("opencode-*/canary-hard-*/agent/trajectory.json"))
    assert len(opencode_logs) == 30
    assert len(opencode_trajs) == 29


def test_harbor_rehearsal_fr8_consistency_and_table():
    prefix = "results/harbor/rehearsal-fr8/"
    rows = [r for r in harbor_consistency(ROOT) if str(r.get("trial") or "").startswith(prefix)]
    trial_rows = [r for r in rows if r.get("kind", "trial") == "trial"]
    job_rows = [r for r in rows if r.get("kind") == "job"]
    assert len(trial_rows) == 70
    assert len(job_rows) == 7
    inconsistent = [r for r in rows if r.get("consistent") is not True or r.get("problems")]
    assert inconsistent == []
    assert all(r.get("signed") is True for r in trial_rows)

    rt = _load_script("rehearsal_table", "scripts/rehearsal_table.py")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rt.main([str(REHEARSAL_DIR)])
    table_path = REHEARSAL_DIR / "TABLE.md"
    assert table_path.is_file()
    assert buf.getvalue().rstrip("\n") == table_path.read_text(encoding="utf-8").rstrip("\n")
