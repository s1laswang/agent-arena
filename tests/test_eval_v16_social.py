from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_v16_social as h


def test_default_cli_args_and_aliases():
    ap = h.build_parser()
    a = ap.parse_args([])
    assert a.tier == "hard"
    assert a.seeds == "0-9"
    assert a.model == "gemini-4-carbon"
    assert a.timeout == 3600
    assert a.v14_provider == "template"
    assert a.v16_provider == "social-v2"
    assert a.v14_source == "run"

    b = ap.parse_args(["--provider", "v16:sycophancy", "--concurrency", "1", "--seeds", "0-4", "--env", "FOO=bar"])
    assert b.v16_provider == "v16:sycophancy"
    assert b.jobs == 1
    assert b.seeds == "0-4"
    assert h.parse_env_overrides(b.env_vars) == {"FOO": "bar"}


def test_timeouts_and_empty_replies_are_strictly_invalid(tmp_path: Path):
    ep_timeout = {
        "tier": "hard",
        "seed": 0,
        "agent": "opencode:google/gemini-4-carbon",
        "score": 0.0,
        "correct": False,
        "accused": None,
        "final_day": 7,
        "end_reason": "error",
        "steps": [],
        "meta": {"rc": "timeout", "wall_s": 3600.2, "valid": True},
    }
    reason = h.invalid_attempt_reason(tmp_path, ep_timeout)
    assert reason is not None and "invalid:timeout" in reason

    tr_dir = tmp_path / "transcripts"
    tr_dir.mkdir()
    (tr_dir / "1.txt").write_text(
        json.dumps({"part": {"type": "step-start"}})
        + "\n"
        + json.dumps({"part": {"type": "step-finish", "reason": "stop", "tokens": {"output": 0, "reasoning": 0}}})
        + "\n"
    )
    ep_empty = {
        "tier": "hard",
        "seed": 1,
        "agent": "opencode:google/gemini-4-carbon",
        "score": 0.0,
        "correct": False,
        "accused": None,
        "final_day": 4,
        "end_reason": "error",
        "steps": [],
        "meta": {"rc": 0, "wall_s": 50.0, "valid": True},
    }
    r_empty = h.invalid_attempt_reason(tmp_path, ep_empty)
    assert r_empty is not None and "empty_model_response" in r_empty

    ep_valid = {
        "tier": "hard",
        "seed": 2,
        "agent": "opencode:google/gemini-4-carbon",
        "score": 0.55,
        "correct": True,
        "accused": "e04",
        "final_day": 11,
        "end_reason": "accused",
        "steps": [],
        "meta": {"rc": 0, "wall_s": 900.0, "valid": True},
    }
    assert h.invalid_attempt_reason(tmp_path, ep_valid) is None


def test_eval_job_command_uses_timeout_3600_and_provider_isolation(tmp_path: Path):
    job = h.EvalJob(
        arm="v1.6",
        provider="v16:authority",
        tier="hard",
        seed=3,
        model="gemini-4-carbon",
        timeout_s=3600,
        staging=tmp_path / "stg",
        cache_dir=tmp_path / "cache",
        env_overrides={"CANARY_CUSTOM": "1"},
    )
    cmd = job.cmd()
    assert "--timeout" in cmd
    assert cmd[cmd.index("--timeout") + 1] == "3600"
    assert cmd[0] == sys.executable
    env16 = job.build_env({"PATH": "/usr/bin"})
    assert env16["CANARY_PROVIDER"] == "v16:authority"
    assert env16["CANARY_SOCIAL_CACHE_DIR"] == str(tmp_path / "cache")
    assert env16["CANARY_GEMINI_CACHE_DIR"] == str(tmp_path / "cache")
    assert env16["CANARY_CUSTOM"] == "1"

    job14 = h.EvalJob(
        arm="v1.4",
        provider="template",
        tier="hard",
        seed=3,
        model="gemini-4-carbon",
        timeout_s=3600,
        staging=tmp_path / "stg",
        cache_dir=tmp_path / "cache",
        env_overrides={"CANARY_CUSTOM": "1"},
    )
    env14 = job14.build_env({"PATH": "/usr/bin"})
    assert env14["CANARY_PROVIDER"] == "template"
    assert "CANARY_CUSTOM" not in env14
    assert job14.dir != job.dir


def test_paired_ratio_and_ship_gate_logic(tmp_path: Path):
    ref = h.verify_reference_and_baselines("hard", [0, 1, 2], "v16-template:all", tmp_path / "cache")
    assert ref["solver_exact_match"] is True
    assert ref["do_nothing_mean"] == 0.0
    assert ref["stop_early_mean"] == 0.0

    v14_eps = {}
    v16_eps = {}
    for s in (0, 1, 2):
        sol_score = ref["solver_v14"][s]["score"]
        v14_eps[s] = {
            "tier": "hard",
            "seed": s,
            "agent": "opencode:google/gemini-4-carbon",
            "score": round(sol_score * 0.7, 4),
            "correct": True,
            "accused": ref["solver_v14"][s]["accused"],
            "final_day": 12,
            "end_reason": "accused",
            "steps": [],
            "meta": {"rc": 0, "wall_s": 500.0, "valid": True},
        }
        v16_eps[s] = {
            "tier": "hard",
            "seed": s,
            "agent": "opencode:google/gemini-4-carbon",
            "score": round(sol_score * 0.4, 4),
            "correct": False,
            "accused": "e00",
            "final_day": 10,
            "end_reason": "accused",
            "steps": [],
            "meta": {"rc": 0, "wall_s": 520.0, "valid": True},
        }
    s14 = h.summarize_arm("v1.4", "template", "hard", [0, 1, 2], v14_eps, ref["solver_v14"], {})
    s16 = h.summarize_arm("v1.6", "v16-template:all", "hard", [0, 1, 2], v16_eps, ref["solver_v16"], {})
    comp = h.compute_paired_comparison([0, 1, 2], s14, s16, ref)
    assert comp["below_v14"] is True
    assert comp["ship_gate_pass"] is True
    assert comp["v16_ratio_shared"] < comp["v14_ratio_shared"]


def test_committed_v14_hard_seeds_0_to_9_load_and_dry_run(tmp_path: Path, capsys):
    eps14 = h.load_committed_v14("hard", list(range(10)), "gemini-4-carbon")
    assert len(eps14) == 10
    rc = h.main([
        "--seeds",
        "0-2",
        "--v16-provider",
        "v16-template:all",
        "--staging",
        str(tmp_path / "stg"),
        "--social-cache-dir",
        str(tmp_path / "cache"),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "exact_match=True" in out
    assert "do_nothing=0.000" in out
    assert "stop_early=0.000" in out
