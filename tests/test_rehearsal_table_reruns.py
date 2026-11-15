from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_rehearsal_table():
    script = ROOT / "scripts" / "rehearsal_table.py"
    spec = importlib.util.spec_from_file_location("rehearsal_table", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_trial(
    job_dir: Path,
    dir_name: str,
    task_name: str,
    started_at: str,
    *,
    reward: float | None,
    done: bool,
    accused: str | None = None,
    correct: bool | None = None,
    day: int | None = None,
    exc_type: str | None = None,
    source_trial: str | None = None,
) -> Path:
    tdir = job_dir / dir_name
    (tdir / "artifacts").mkdir(parents=True, exist_ok=True)
    res = {
        "task_name": task_name,
        "trial_name": dir_name,
        "started_at": started_at,
        "config": {"source_trial": source_trial},
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": {"exception_type": exc_type} if exc_type else None,
    }
    (tdir / "result.json").write_text(json.dumps(res), encoding="utf-8")
    ledger = {
        "done": done,
        "accused": accused,
        "correct": correct,
        "final_day": day,
        "score": reward,
    }
    (tdir / "artifacts" / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    return tdir


def test_rehearsal_dry_matches_committed_table_byte_for_byte(tmp_path: Path):
    rt = _load_rehearsal_table()
    rehearsal_dry = ROOT / "results" / "harbor" / "rehearsal-dry"
    out_md = tmp_path / "TABLE.md"
    rt.main([str(rehearsal_dry), "--out", str(out_md)])
    assert out_md.read_bytes() == (rehearsal_dry / "TABLE.md").read_bytes()


def test_chronological_inline_multi_attempt_retry_and_no_valid_overwrite(tmp_path: Path):
    rt = _load_rehearsal_table()
    rehearsal = tmp_path / "rehearsal"
    oracle = rehearsal / "oracle"
    opencode = rehearsal / "opencode-1"

    _write_trial(
        oracle,
        "canary-hard-900005__ora5",
        "canary/hard-900005",
        "2026-11-15T01:00:00Z",
        reward=0.70,
        done=True,
        accused="e05",
        correct=True,
        day=9,
    )
    _write_trial(
        oracle,
        "canary-hard-900006__ora6",
        "canary/hard-900006",
        "2026-11-15T01:00:00Z",
        reward=0.60,
        done=True,
        accused="e06",
        correct=True,
        day=11,
    )

    _write_trial(
        opencode,
        "canary-hard-900006__zzFirst",
        "canary/hard-900006",
        "2026-11-15T01:00:00Z",
        reward=None,
        done=False,
        exc_type="ApiRateLimitError",
    )
    _write_trial(
        opencode,
        "canary-hard-900006__aaRetry",
        "canary/hard-900006",
        "2026-11-15T01:20:00Z",
        reward=0.55,
        done=True,
        accused="e06",
        correct=True,
        day=12,
        exc_type="NonZeroAgentExitCodeError",
    )

    _write_trial(
        opencode,
        "canary-hard-900005__zzValidFirst",
        "canary/hard-900005",
        "2026-11-15T01:05:00Z",
        reward=-1.0,
        done=True,
        accused="e01",
        correct=False,
        day=14,
        exc_type="NonZeroAgentExitCodeError",
    )
    _write_trial(
        opencode,
        "canary-hard-900005__aaLaterAttempt",
        "canary/hard-900005",
        "2026-11-15T01:25:00Z",
        reward=0.85,
        done=True,
        accused="e05",
        correct=True,
        day=6,
        exc_type="NonZeroAgentExitCodeError",
    )

    assert "canary-hard-900006__aaRetry" < "canary-hard-900006__zzFirst"
    out_md = tmp_path / "TABLE.md"
    rt.main([str(rehearsal), "--out", str(out_md)])
    txt = out_md.read_text(encoding="utf-8")

    loaded = rt.load(rehearsal)
    t6 = loaded["opencode-1"]["hard-900006"]
    assert t6["reward"] == 0.55
    assert t6["rerun"] is True
    assert t6["inline"] is True
    assert t6["first"] == "provider rate limit"

    t5 = loaded["opencode-1"]["hard-900005"]
    assert t5["reward"] == -1.0
    assert t5["rerun"] is False

    assert "| hard-900006 | +0.60 \u2713 d11 | +0.55 \u2713 d12 \u2020 |" in txt
    assert "| hard-900005 | +0.70 \u2713 d9 | -1.00 \u2717 d14 |" in txt
    assert "\u2020 inline retry within `<job>` because the first attempt was an infrastructure failure: opencode-1 hard-900006 (provider rate limit)." in txt


def test_harbor_in_place_job_n_retries_disclosure(tmp_path: Path):
    rt = _load_rehearsal_table()
    rehearsal = tmp_path / "rehearsal"
    oracle = rehearsal / "oracle"
    opencode = rehearsal / "opencode-1"
    rerun = rehearsal / "opencode-1-infra-rerun"

    _write_trial(
        oracle,
        "canary-hard-900000__ora0",
        "canary/hard-900000",
        "2026-11-15T01:00:00Z",
        reward=0.65,
        done=True,
        accused="e02",
        correct=True,
        day=10,
    )
    (oracle / "result.json").write_text(json.dumps({"stats": {"n_retries": 0}}), encoding="utf-8")

    _write_trial(
        opencode,
        "canary-hard-900000__oc0",
        "canary/hard-900000",
        "2026-11-15T01:15:00Z",
        reward=0.48,
        done=True,
        accused="e02",
        correct=True,
        day=13,
        exc_type="NonZeroAgentExitCodeError",
    )
    (opencode / "result.json").write_text(json.dumps({"stats": {"n_retries": 2}}), encoding="utf-8")

    rerun.mkdir(parents=True, exist_ok=True)
    (rerun / "result.json").write_text(json.dumps({"stats": {"n_retries": 4}}), encoding="utf-8")

    out_md = tmp_path / "TABLE.md"
    rt.main([str(rehearsal), "--out", str(out_md)])
    txt = out_md.read_text(encoding="utf-8")

    assert "Note: Harbor inline --retry-include infra retries recorded in job result.json: opencode-1 (n_retries=2)." in txt
    assert "opencode-1-infra-rerun" not in txt


def test_source_trial_and_mixed_inline_plus_infra_rerun_footnotes(tmp_path: Path):
    rt = _load_rehearsal_table()
    rehearsal = tmp_path / "rehearsal"
    oracle = rehearsal / "oracle"
    opencode = rehearsal / "opencode-1"
    rerun = rehearsal / "opencode-1-infra-rerun"

    for tid in ("hard-900000", "hard-900001"):
        _write_trial(
            oracle,
            f"canary-{tid}__ora",
            f"canary/{tid}",
            "2026-11-15T01:00:00Z",
            reward=0.60,
            done=True,
            accused="e01",
            correct=True,
            day=10,
        )

    _write_trial(
        opencode,
        "canary-hard-900000__retried",
        "canary/hard-900000",
        "2026-11-15T01:10:00Z",
        reward=0.50,
        done=True,
        accused="e01",
        correct=True,
        day=12,
        source_trial="canary-hard-900000__orig",
    )
    _write_trial(
        opencode,
        "canary-hard-900001__infra",
        "canary/hard-900001",
        "2026-11-15T01:11:00Z",
        reward=None,
        done=False,
        exc_type="AgentSetupTimeoutError",
    )
    _write_trial(
        rerun,
        "canary-hard-900001__rerun",
        "canary/hard-900001",
        "2026-11-15T01:30:00Z",
        reward=0.45,
        done=True,
        accused="e01",
        correct=True,
        day=13,
    )

    out_md = tmp_path / "TABLE.md"
    rt.main([str(rehearsal), "--out", str(out_md)])
    txt = out_md.read_text(encoding="utf-8")

    assert "hard-900000 (source_trial=canary-hard-900000__orig, inline)" in txt
    assert "hard-900001 (agent setup timeout, infra-rerun)" in txt
