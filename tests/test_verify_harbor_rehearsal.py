"""Offline unit and hygiene tests for scripts/verify_harbor_rehearsal.py."""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import io
import json
import re
import shutil
import sys
import time
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts/verify_harbor_rehearsal.py"
JSON_PATH = ROOT / "results/eval_v14/verify_harbor_rehearsal.json"
MD_PATH = ROOT / "docs/reports/harbor_rehearsal_verification_v14.md"
THIS_TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
SYNTH_KEY = "cd" * 32

SECRET_AND_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("provider_token", re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
)


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_harbor_rehearsal", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vhr = _load_module()


def _sign_ledger(body: dict[str, Any], key_hex: str = SYNTH_KEY) -> dict[str, Any]:
    payload = {k: v for k, v in body.items() if k != "sig"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    mac = hmac.new(key_hex.encode(), canonical, hashlib.sha256).hexdigest()
    out = dict(payload)
    out["sig"] = {"alg": "HMAC-SHA256", "mac": mac}
    return out


def _make_ledger(
    tier: str,
    score: float,
    end_reason: str | None,
    accused: str | None = None,
    correct: bool = False,
    final_day: int = 10,
    done: bool = True,
    key_hex: str = SYNTH_KEY,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    v_val = score if (accused is not None and correct) else 0.65
    if accused is not None:
        events.append({
            "t": 12,
            "day": final_day,
            "event": "accused",
            "detail": {"employee": accused, "correct": correct, "V": v_val},
        })
        events.append({
            "t": 12,
            "day": final_day,
            "event": "episode_end",
            "detail": {"reason": "accused", "score": score, "V": v_val},
        })
    body = {
        "done": done,
        "end_reason": end_reason,
        "accused": accused,
        "correct": correct,
        "accused_correct": correct,
        "final_day": final_day,
        "V": v_val,
        "score": score,
        "tier": tier,
        "episode": "deadbeef12345678",
        "ledger": events,
    }
    return _sign_ledger(body, key_hex=key_hex)


def _write_trajectory(path: Path, accused: str | None) -> None:
    steps: list[dict[str, Any]] = []
    if accused is not None:
        steps.append({
            "tool_calls": [
                {
                    "tool_call_id": "call_1",
                    "function_name": "canary_accuse",
                    "arguments": {"employee": accused},
                }
            ],
            "observation": {
                "results": [
                    {
                        "source_call_id": "call_1",
                        "content": json.dumps({"ok": True, "data": {"episode_over": True}, "error": None}),
                    }
                ]
            },
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"steps": steps}), encoding="utf-8")


def _write_trial(
    job_dir: Path,
    seed: int,
    policy: str,
    score: float | None,
    end_reason: str | None,
    accused: str | None = None,
    correct: bool = False,
    final_day: int = 10,
    done: bool = True,
    exc_info: dict[str, Any] | None = None,
    is_opencode: bool = False,
    key_hex: str = SYNTH_KEY,
    opencode_log_line: str | None = None,
) -> Path:
    tname = f"canary-hard-{seed}__syn{seed % 100}"
    tdir = job_dir / tname
    (tdir / "artifacts").mkdir(parents=True, exist_ok=True)
    (tdir / "verifier").mkdir(parents=True, exist_ok=True)
    (tdir / "agent").mkdir(parents=True, exist_ok=True)

    agent_cfg: dict[str, Any] = {"name": "opencode" if is_opencode else "oracle"}
    if not is_opencode and policy != "oracle":
        agent_cfg["env"] = {"ORACLE_POLICY": policy}
    if is_opencode:
        agent_cfg["model_name"] = "google/gemini-4-carbon"

    (tdir / "config.json").write_text(json.dumps({"agent": agent_cfg}), encoding="utf-8")

    res_obj: dict[str, Any] = {
        "task_name": f"canary/hard-{seed}",
        "trial_name": tname,
        "config": {"agent": agent_cfg},
        "verifier_result": None if score is None else {"rewards": {"reward": score}},
        "exception_info": exc_info,
    }
    (tdir / "result.json").write_text(json.dumps(res_obj), encoding="utf-8")

    if score is not None:
        led = _make_ledger(
            tier="hard",
            score=score,
            end_reason=end_reason,
            accused=accused,
            correct=correct,
            final_day=final_day,
            done=done,
            key_hex=key_hex,
        )
        led_txt = json.dumps(led)
        (tdir / "artifacts/ledger.json").write_text(led_txt, encoding="utf-8")
        (tdir / "verifier/ledger.json").write_text(led_txt, encoding="utf-8")
        (tdir / "verifier/reward.txt").write_text(repr(float(score)), encoding="utf-8")
        (tdir / "verifier/reward.json").write_text(json.dumps({"reward": float(score)}), encoding="utf-8")
        (tdir / "verifier/test-stdout.txt").write_text(
            f"reward={float(score)!r} source=sidecar signature=ok done={done} end_reason={end_reason}\n",
            encoding="utf-8",
        )

    if is_opencode:
        if score is not None:
            _write_trajectory(tdir / "agent/trajectory.json", accused)
        if opencode_log_line is not None:
            (tdir / "agent/opencode.txt").write_text(opencode_log_line + "\n", encoding="utf-8")
    else:
        (tdir / "agent/isolation.txt").write_text("ISOLATION OK: 11 checks passed, 0 findings\n", encoding="utf-8")
        if policy == "cheat_probe":
            (tdir / "agent/cheat.json").write_text(
                json.dumps({
                    "agent": "cheat_probe",
                    "holes": [],
                    "incomplete": None,
                    "controls_failed": 0,
                    "n_attempts": 149,
                }),
                encoding="utf-8",
            )
    return tdir


def _write_job_summary(job_dir: Path) -> None:
    trials = sorted(job_dir.glob("*/result.json"))
    rewards: list[float] = []
    buckets: dict[str, list[str]] = {}
    exc_stats: dict[str, list[str]] = {}
    n_errors = 0
    n_scored = 0
    for rf in trials:
        r = json.loads(rf.read_text(encoding="utf-8"))
        exc = r.get("exception_info")
        exc_type = exc.get("exception_type") if isinstance(exc, dict) else None
        if exc:
            n_errors += 1
            if exc_type:
                exc_stats.setdefault(exc_type, []).append(rf.parent.name)
        if exc_type in {"ApiRateLimitError", "AgentSetupTimeoutError"}:
            continue
        n_scored += 1
        rew = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if rew is not None:
            fval = float(rew)
            rewards.append(fval)
            buckets.setdefault(str(fval), []).append(rf.parent.name)
    mean_val = sum(rewards) / len(rewards) if rewards else None
    job_res = {
        "n_total_trials": len(trials),
        "stats": {
            "evals": {
                f"{job_dir.name}__synth": {
                    "n_trials": n_scored,
                    "n_errors": n_errors,
                    "exception_stats": exc_stats,
                    "metrics": [{"mean": mean_val}],
                    "reward_stats": {"reward": buckets},
                }
            }
        },
    }
    (job_dir / "result.json").write_text(json.dumps(job_res), encoding="utf-8")


def _build_synthetic_3x10(rehearsal_dir: Path, job_level_keys: bool = True) -> Path:
    rehearsal_dir.mkdir(parents=True, exist_ok=True)
    (rehearsal_dir / "README.md").write_text(
        "Judge rehearsal protocol on afterquery-final: opencode-1, opencode-2, opencode-3, "
        "-infra-rerun and ApiRateLimitError rules.\n",
        encoding="utf-8",
    )
    if not job_level_keys:
        (rehearsal_dir / "ledger_key").write_text(SYNTH_KEY + "\n", encoding="utf-8")

    seeds = list(range(900000, 900010))
    oracle_scores = [0.62, 0.58, 0.65, 0.54, 0.60, 0.55, 0.61, 0.52, 0.57, 0.56]

    run_outcomes = {
        "opencode-1": [
            (0.50, "accused", "e03", True),
            (0.48, "accused", "e03", True),
            (0.52, "accused", "e03", True),
            (0.44, "accused", "e03", True),
            (0.46, "accused", "e03", True),
            (0.40, "accused", "e03", True),
            (0.00, "horizon", None, False),
            (-1.0, "accused", "e09", False),
            (0.42, "accused", "e03", True),
            (0.00, "horizon", None, False),
        ],
        "opencode-2": [
            (0.49, "accused", "e03", True),
            (0.47, "accused", "e03", True),
            (0.51, "accused", "e03", True),
            (0.45, "accused", "e03", True),
            (0.43, "accused", "e03", True),
            (0.00, "horizon", None, False),
            (0.41, "accused", "e03", True),
            (0.00, "horizon", None, False),
            (-1.0, "accused", "e09", False),
            (0.38, "accused", "e03", True),
        ],
        "opencode-3": [
            (0.51, "accused", "e03", True),
            (0.46, "accused", "e03", True),
            (0.50, "accused", "e03", True),
            (0.42, "accused", "e03", True),
            (0.44, "accused", "e03", True),
            (0.39, "accused", "e03", True),
            (0.00, "tool_cap", None, False),
            (0.37, "accused", "e03", True),
            (0.40, "accused", "e03", True),
            (-1.0, "accused", "e09", False),
        ],
    }

    for jn in ("oracle", "do_nothing", "stop_early", "cheat-probe", "cheat", "opencode-1", "opencode-2", "opencode-3"):
        jdir = rehearsal_dir / jn
        jdir.mkdir(parents=True, exist_ok=True)
        if job_level_keys:
            (jdir / "ledger_key").write_text(SYNTH_KEY + "\n", encoding="utf-8")

        for idx, s in enumerate(seeds):
            if jn == "oracle":
                _write_trial(jdir, s, "oracle", oracle_scores[idx], "accused", "e03", True, final_day=9)
            elif jn == "do_nothing":
                _write_trial(jdir, s, "do_nothing", 0.0, "horizon", None, False, final_day=21)
            elif jn == "stop_early":
                _write_trial(jdir, s, "stop_early", 0.0, None, None, False, final_day=1, done=False)
            elif jn == "cheat-probe":
                _write_trial(jdir, s, "cheat_probe", 0.0, None, None, False, final_day=4, done=False)
            elif jn == "cheat":
                _write_trial(jdir, s, "cheat", -1.0, "accused", "e01", False, final_day=1)
            else:
                sc, er, acc, corr = run_outcomes[jn][idx]
                _write_trial(jdir, s, "opencode", sc, er, acc, corr, final_day=12, is_opencode=True)

        _write_job_summary(jdir)

    return rehearsal_dir


@pytest.fixture(scope="module")
def synth_template(tmp_path_factory) -> Path:
    return _build_synthetic_3x10(tmp_path_factory.mktemp("synth_3x10_base"))


def _clone_rehearsal(src: Path, dst: Path, editable_jobs: tuple[str, ...] = ()) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in editable_jobs:
            shutil.copytree(child, dst / child.name)
        else:
            (dst / child.name).symlink_to(child, target_is_directory=child.is_dir())
    return dst


def test_committed_artifacts_and_check_mode_fast():
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    raw_bytes = JSON_PATH.read_bytes()
    assert len(raw_bytes) <= vhr.MAX_JSON_BYTES

    t0 = time.perf_counter()
    rc = vhr.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 5.0

    summary = json.loads(raw_bytes.decode("utf-8"))
    assert summary["schema_version"] == "verify_harbor_rehearsal_v14.v1"
    assert summary["overall_ok"] is True
    assert all(summary["checks"].values())

    tot = summary["totals"]
    assert tot["n_jobs"] == 18
    assert tot["n_top_level_jobs"] == 13
    assert tot["n_rehearsal_dry_jobs"] == 5
    assert tot["n_trials"] == 80
    assert tot["n_top_level_trials"] == 37
    assert tot["n_rehearsal_dry_trials"] == 43
    assert tot["trials_consistent"] == 80
    assert tot["jobs_consistent"] == 18
    assert tot["signed_trials"] == 60
    assert tot["hmac_verified_trials"] == 57
    assert tot["isolation_harbor_11of11"] == 61
    assert tot["isolation_including_negative_11of11"] == 62
    assert tot["isolation_checks_per_trial"] == 11
    assert tot["trajectory_checked_trials"] == 19

    rd = summary["rehearsal_dry"]
    assert rd["overall_ok"] is True
    assert rd["classification"] == "1_run_harness_check_not_gap_claim"
    assert rd["oracle_10task_mean"] == pytest.approx(0.467, abs=1e-6)
    assert rd["opencode_10task_mean"] == pytest.approx(0.398, abs=1e-6)
    assert rd["opencode_ratio_vs_oracle"] == pytest.approx(0.852248, abs=1e-5)
    assert rd["opencode_ratio_ci95"][0] == pytest.approx(0.107884, abs=1e-5)
    assert rd["opencode_ratio_ci95"][1] == pytest.approx(3.55, abs=1e-5)
    assert rd["opencode_disclosed_infra_reruns_n"] == 3
    assert rd["opencode_unresolved_infra_n"] == 0
    assert rd["do_nothing_10task_mean"] == 0.0
    assert rd["stop_early_10task_mean"] == 0.0
    assert rd["table_md_matches"] is True

    cp = summary["cheat_probe"]
    assert cp["n_trials"] == 6
    assert cp["all_zero_reward"] is True
    assert cp["probes_per_trial"] == 149
    assert cp["total_probe_attempts"] == 894
    assert cp["holes_found"] == 0

    neg = summary["negative_control"]
    assert neg["failed_closed_ok"] is True
    assert neg["tampered_ledger_score"] == 1.0
    assert neg["harbor_result_reward"] == 0.0
    assert neg["verifier_reward_txt"] == 0.0

    ora = summary["oracle_range_v14"]["hard_k10"]
    assert ora["builds"] == 200
    assert ora["band_90pct"] == [0.39, 0.68]
    assert ora["mean"] == pytest.approx(0.56938, abs=1e-6)
    assert ora["sd"] == pytest.approx(0.094469, abs=1e-6)

    lr = summary["live_rehearsal"]
    assert lr["status"] == "protocol_only"
    assert lr["n_jobs"] == 0
    assert lr["n_trials"] == 0
    assert lr["automatic_verifier_ready"] is True

    pkg = summary["current_package_verification"]
    assert pkg["verified"] is True
    assert pkg["n_tasks"] == 10
    assert pkg["stop_early_inproc_mean"] == 0.0
    assert pkg["do_nothing_inproc_mean"] == 0.0
    assert pkg["scratch_dir_deleted"] is True


def test_check_mode_detects_json_or_md_drift(tmp_path):
    j_copy = tmp_path / "verify_harbor_rehearsal.json"
    m_copy = tmp_path / "harbor_rehearsal_verification_v14.md"
    shutil.copyfile(JSON_PATH, j_copy)
    shutil.copyfile(MD_PATH, m_copy)

    tiny = json.loads(j_copy.read_text(encoding="utf-8"))
    tiny["rehearsal_dry"]["oracle_10task_mean"] += 1e-12
    j_copy.write_text(json.dumps(tiny, indent=2) + "\n", encoding="utf-8")
    assert vhr.main(["--check", "--out-json", str(j_copy), "--out-md", str(m_copy)]) == 0

    bad = json.loads(j_copy.read_text(encoding="utf-8"))
    bad["rehearsal_dry"]["oracle_10task_mean"] = 0.999
    j_copy.write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
    assert vhr.main(["--check", "--out-json", str(j_copy), "--out-md", str(m_copy)]) == 1

    shutil.copyfile(JSON_PATH, j_copy)
    m_copy.write_text(m_copy.read_text(encoding="utf-8").replace("85% [11%, 355%]", "99% [98%, 100%]"), encoding="utf-8")
    assert vhr.main(["--check", "--out-json", str(j_copy), "--out-md", str(m_copy)]) == 1


def test_valid_synthetic_3x10_rehearsal_and_live_rehearsal_promotion(synth_template, tmp_path):
    out_json = tmp_path / "out/verify.json"
    out_md = tmp_path / "out/VERIFY.md"

    rc = vhr.main([str(synth_template), "--strict", "--out-json", str(out_json), "--out-md", str(out_md)])
    assert rc == 0
    assert out_json.is_file() and out_md.is_file()

    rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert rep["overall_ok"] is True
    assert all(rep["checks"].values())
    assert rep["oracle"]["mean"] == pytest.approx(0.58)
    assert rep["oracle"]["in_90pct_band"] is True
    assert rep["oracle"]["band_reference"]["band_90pct"] == [0.39, 0.68]

    sp = rep["agent_spread"]
    assert sp["n_runs"] == 3
    assert sp["tasks_with_3plus_runs"] == 10
    assert sp["pass_hat_3"] == pytest.approx(0.5)
    assert sp["sd_across_runs"] > 0.0
    assert sp["range_across_runs"] > 0.0

    for pr in rep["paired_runs"]:
        if pr["job"].startswith("opencode"):
            lo, hi = pr["ratio_ci95"]
            assert lo is not None and hi is not None
            assert lo <= pr["ratio_vs_oracle"] <= hi

    promoted = vhr.inspect_live_rehearsal(synth_template)
    assert promoted["status"] == "verified_3x10_complete"
    assert promoted["status_consistent"] is True
    assert promoted["n_jobs"] == 8
    assert promoted["n_trials"] == 80

    empty_live = tmp_path / "protocol_only_rehearsal"
    empty_live.mkdir(parents=True, exist_ok=True)
    (empty_live / "README.md").write_text(
        "Pre-registered protocol on afterquery-final: opencode-1, opencode-2, opencode-3, "
        "-infra-rerun, ApiRateLimitError.\n",
        encoding="utf-8",
    )
    proto = vhr.inspect_live_rehearsal(empty_live)
    assert proto["status"] == "protocol_only"
    assert proto["status_consistent"] is True
    assert proto["n_jobs"] == 0


def test_infra_rerun_protocol_valid_merge_and_invalid_replacement_rejected(synth_template, tmp_path):
    rdir = _clone_rehearsal(synth_template, tmp_path / "rehearsal_rerun_ok", editable_jobs=("opencode-1",))
    op1 = rdir / "opencode-1"
    victim = next(op1.glob("canary-hard-900006*"))
    shutil.rmtree(victim)
    _write_trial(
        op1,
        900006,
        "opencode",
        0.0,
        None,
        done=False,
        exc_info={"exception_type": "ApiRateLimitError", "exception_message": "429 quota"},
        is_opencode=True,
        opencode_log_line='{"type":"error","error":{"message":"You exceeded your current quota 429"}}',
    )
    _write_job_summary(op1)

    rerun_dir = rdir / "opencode-1-infra-rerun"
    rerun_dir.mkdir(parents=True, exist_ok=True)
    (rerun_dir / "ledger_key").write_text(SYNTH_KEY + "\n", encoding="utf-8")
    _write_trial(rerun_dir, 900006, "opencode", 0.44, "accused", "e03", True, final_day=12, is_opencode=True)
    _write_job_summary(rerun_dir)

    rep_ok = vhr.verify_rehearsal(rdir, strict=True, n_boot=250)
    assert rep_ok["overall_ok"] is True
    assert rep_ok["checks"]["rerun_protocol_clean"] is True
    assert rep_ok["checks"]["chief_data_rule_clean"] is True
    assert len(rep_ok["disclosed_infra_reruns"]) == 1
    assert rep_ok["disclosed_infra_reruns"][0]["first_infra_reason"] == "provider rate limit"

    _write_trial(rerun_dir, 900000, "opencode", 0.95, "accused", "e03", True, final_day=5, is_opencode=True)
    _write_job_summary(rerun_dir)
    rep_bad = vhr.verify_rehearsal(rdir, strict=True, n_boot=250)
    assert rep_bad["overall_ok"] is False
    assert rep_bad["checks"]["rerun_protocol_clean"] is False


def test_missing_required_jobs_or_incomplete_tasks_fail(synth_template, tmp_path):
    rdir = _clone_rehearsal(synth_template, tmp_path / "rehearsal")
    (rdir / "opencode-3").unlink()
    rep_missing = vhr.verify_rehearsal(rdir, expected_tasks=10, min_agent_runs=3, n_boot=250)
    assert rep_missing["overall_ok"] is False
    assert rep_missing["checks"]["required_jobs_present"] is False

    rdir2 = _clone_rehearsal(synth_template, tmp_path / "rehearsal2", editable_jobs=("opencode-1",))
    victim = next((rdir2 / "opencode-1").glob("canary-hard-900009*"))
    shutil.rmtree(victim)
    _write_job_summary(rdir2 / "opencode-1")
    rep_short = vhr.verify_rehearsal(rdir2, expected_tasks=10, min_agent_runs=3, n_boot=250)
    assert rep_short["overall_ok"] is False
    assert rep_short["checks"]["expected_tasks_complete"] is False


@pytest.mark.parametrize("job_level_keys", [True, False])
def test_tampered_hmac_rejected_under_job_or_shared_key(synth_template, tmp_path, job_level_keys):
    rdir = _clone_rehearsal(synth_template, tmp_path / "rehearsal", editable_jobs=("opencode-1",))
    jdir = rdir / "opencode-1"
    if not job_level_keys:
        for nm in ("oracle", "do_nothing", "stop_early", "cheat-probe", "cheat", "opencode-1", "opencode-2", "opencode-3"):
            kf = rdir / nm / "ledger_key"
            if kf.is_symlink() or kf.exists():
                if nm == "opencode-1":
                    kf.unlink()
        (rdir / "ledger_key").write_text(SYNTH_KEY + "\n", encoding="utf-8")
    tdir = next(jdir.glob("canary-hard-900000*"))

    for rel in ("artifacts/ledger.json", "verifier/ledger.json"):
        led = json.loads((tdir / rel).read_text(encoding="utf-8"))
        for ev in led["ledger"]:
            if ev["event"] == "accused":
                ev["detail"]["V"] = 0.99
            elif ev["event"] == "episode_end":
                ev["detail"]["score"] = 0.99
                ev["detail"]["V"] = 0.99
        led["V"] = 0.99
        led["score"] = 0.99
        (tdir / rel).write_text(json.dumps(led), encoding="utf-8")

    (tdir / "verifier/reward.txt").write_text("0.99", encoding="utf-8")
    (tdir / "verifier/reward.json").write_text(json.dumps({"reward": 0.99}), encoding="utf-8")
    (tdir / "verifier/test-stdout.txt").write_text("reward=0.99 source=sidecar signature=ok\n", encoding="utf-8")
    res = json.loads((tdir / "result.json").read_text(encoding="utf-8"))
    res["verifier_result"]["rewards"]["reward"] = 0.99
    (tdir / "result.json").write_text(json.dumps(res), encoding="utf-8")
    _write_job_summary(jdir)

    rc = vhr.main([str(rdir)])
    assert rc == 1
    rep = vhr.verify_rehearsal(rdir, n_boot=250)
    assert rep["overall_ok"] is False
    assert rep["checks"]["anticheat_trials_consistent"] is False
    assert any("HMAC" in msg for msg in rep["errors"]["trial_consistency_failures"])


@pytest.mark.parametrize(
    "failure_kind",
    [
        "setup_timeout_none_reward",
        "agent_timeout_zero_reward",
        "api_key_error_zero_reward",
        "ledger_error_end_reason",
        "nonzero_exit_incomplete_ledger",
        "thought_signature_cli_error",
    ],
)
def test_chief_data_rule_flags_infra_failures_never_silently_zero(synth_template, tmp_path, failure_kind):
    rdir = _clone_rehearsal(synth_template, tmp_path / f"rehearsal_{failure_kind}", editable_jobs=("opencode-2",))
    jdir = rdir / "opencode-2"
    victim = next(jdir.glob("canary-hard-900000*"))
    shutil.rmtree(victim)

    if failure_kind == "setup_timeout_none_reward":
        tdir = _write_trial(
            jdir,
            900000,
            "opencode",
            None,
            None,
            exc_info={"exception_type": "AgentSetupTimeoutError", "exception_message": "setup exceeded 360s"},
            is_opencode=True,
        )
    elif failure_kind == "agent_timeout_zero_reward":
        tdir = _write_trial(
            jdir,
            900000,
            "opencode",
            0.0,
            None,
            done=False,
            exc_info={"exception_type": "AgentTimeoutError", "exception_message": "agent timed out"},
            is_opencode=True,
        )
    elif failure_kind == "api_key_error_zero_reward":
        tdir = _write_trial(
            jdir,
            900000,
            "opencode",
            0.0,
            None,
            done=False,
            exc_info={
                "exception_type": "NonZeroAgentExitCodeError",
                "exception_message": "Command failed (exit 1): AI_LoadAPIKeyError: Google Generative AI API key is missing",
            },
            is_opencode=True,
        )
    elif failure_kind == "ledger_error_end_reason":
        tdir = _write_trial(
            jdir,
            900000,
            "opencode",
            0.0,
            "error",
            done=True,
            exc_info=None,
            is_opencode=True,
        )
    elif failure_kind == "thought_signature_cli_error":
        tdir = _write_trial(
            jdir,
            900000,
            "opencode",
            0.0,
            None,
            done=False,
            exc_info={"exception_type": "NonZeroAgentExitCodeError", "exception_message": "exit 1"},
            is_opencode=True,
            opencode_log_line='{"type":"error","error":{"message":"Function call is missing a thought_signature"}}',
        )
    else:
        tdir = _write_trial(
            jdir,
            900000,
            "opencode",
            0.0,
            None,
            done=False,
            exc_info={"exception_type": "NonZeroAgentExitCodeError", "exception_message": "segfault on day 1"},
            is_opencode=True,
        )

    _write_job_summary(jdir)

    inspected = vhr.inspect_trial(tdir, shared_key_file=jdir / "ledger_key")
    assert inspected["infra_invalid"] is True
    assert inspected["valid_reward"] is None

    rep = vhr.verify_rehearsal(rdir, n_boot=250)
    assert rep["overall_ok"] is False
    assert rep["checks"]["chief_data_rule_clean"] is False
    op2 = next(r for r in rep["paired_runs"] if r["job"] == "opencode-2")
    assert op2["n_infra_invalid"] == 1
    assert op2["n_paired_valid"] == 9


def test_harmless_post_game_nonzero_agent_exit_permitted_in_strict_mode(synth_template, tmp_path):
    rdir = _clone_rehearsal(synth_template, tmp_path / "rehearsal", editable_jobs=("opencode-3",))
    jdir = rdir / "opencode-3"
    epipe_exc = {
        "exception_type": "NonZeroAgentExitCodeError",
        "exception_message": "Command failed (exit 1): error: EPIPE: broken pipe, write",
    }

    for seed_target in (900000, 900006):
        tdir = next(jdir.glob(f"canary-hard-{seed_target}*"))
        res = json.loads((tdir / "result.json").read_text(encoding="utf-8"))
        res["exception_info"] = epipe_exc
        (tdir / "result.json").write_text(json.dumps(res), encoding="utf-8")
    _write_job_summary(jdir)

    rc = vhr.main([str(rdir), "--strict"])
    assert rc == 0
    rep = vhr.verify_rehearsal(rdir, strict=True, n_boot=250)
    assert rep["overall_ok"] is True
    assert rep["checks"]["chief_data_rule_clean"] is True
    op3 = next(r for r in rep["paired_runs"] if r["job"] == "opencode-3")
    assert op3["n_infra_invalid"] == 0
    assert op3["n_post_game_nonzero_exit"] == 2
    assert op3["n_paired_valid"] == 10


def test_baseline_nonzero_cheat_probe_hole_and_oracle_out_of_band_rejected(synth_template, tmp_path):
    rdir = _clone_rehearsal(synth_template, tmp_path / "rehearsal_bad_se", editable_jobs=("stop_early",))
    se_dir = rdir / "stop_early"
    victim = next(se_dir.glob("canary-hard-900000*"))
    shutil.rmtree(victim)
    _write_trial(se_dir, 900000, "stop_early", -1.0, "accused", "e09", False, final_day=1)
    _write_job_summary(se_dir)

    rep_se = vhr.verify_rehearsal(rdir, n_boot=250)
    assert rep_se["overall_ok"] is False
    assert rep_se["checks"]["baselines_exact_zero"] is False

    rdir_cp = _clone_rehearsal(synth_template, tmp_path / "rehearsal_bad_cp", editable_jobs=("cheat-probe",))
    cp_trial = next((rdir_cp / "cheat-probe").glob("canary-hard-900000*"))
    (cp_trial / "agent/cheat.json").write_text(
        json.dumps({"agent": "cheat_probe", "holes": ["secrets.file[/run/canary/ledger_token]"], "incomplete": None}),
        encoding="utf-8",
    )
    rep_cp = vhr.verify_rehearsal(rdir_cp, n_boot=250)
    assert rep_cp["overall_ok"] is False
    assert rep_cp["checks"]["anticheat_trials_consistent"] is False
    assert rep_cp["checks"]["baselines_exact_zero"] is False

    rdir_or = _clone_rehearsal(synth_template, tmp_path / "rehearsal_low_oracle", editable_jobs=("oracle",))
    odir = rdir_or / "oracle"
    for s in range(900000, 900010):
        old = next(odir.glob(f"canary-hard-{s}*"))
        shutil.rmtree(old)
        _write_trial(odir, s, "oracle", 0.25, "accused", "e03", True, final_day=18)
    _write_job_summary(odir)

    rep_or = vhr.verify_rehearsal(rdir_or, n_boot=250)
    assert rep_or["overall_ok"] is False
    assert rep_or["checks"]["oracle_in_90pct_band"] is False


def test_hygiene_zero_comments_zero_unicode_dashes_zero_secrets_zero_leaks():
    for py_path in (SCRIPT_PATH, THIS_TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"unexpected hash character in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"tokenize.COMMENT found in {py_path}: {comment_tokens}"

    co_authored_tag = "Co-Authored" + "-By"
    for fpath in (SCRIPT_PATH, JSON_PATH, MD_PATH, THIS_TEST_PATH):
        txt = fpath.read_text(encoding="utf-8")
        txt.encode("ascii")
        assert EN_DASH not in txt and EM_DASH not in txt, f"unicode dash found in {fpath}"
        assert co_authored_tag not in txt
        for pat_name, pat in SECRET_AND_LEAK_PATTERNS:
            assert pat.search(txt) is None, f"{pat_name} matched in {fpath}"

    raw_json_str = JSON_PATH.read_text(encoding="utf-8")
    for volatile_key in ('"elapsed_s"', '"duration_s"', '"wall_clock"', '"generated_at"', '"head_sha"'):
        assert volatile_key not in raw_json_str
