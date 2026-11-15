"""Unit and reproducibility tests for scripts/harbor_luck_adjusted_v14.py."""
from __future__ import annotations

import copy
import hashlib
import hmac
import importlib.util
import io
import json
import math
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT_PATH = ROOT / "scripts/harbor_luck_adjusted_v14.py"
TEST_PATH = Path(__file__).resolve()
JSON_PATH = ROOT / "results/eval_v14/harbor_rehearsal_dry_posteriors.json"
MD_PATH = ROOT / "docs/reports/harbor_rehearsal_dry_luck_adjusted.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


HLA = _load_module("harbor_luck_adjusted_v14", SCRIPT_PATH)


def _sign_ledger(body: dict[str, Any], key_bytes: bytes) -> dict[str, Any]:
    clean = {k: v for k, v in body.items() if k != "sig"}
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    mac = hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()
    return {**clean, "sig": {"alg": "hmac-sha256", "mac": mac}}


def _write_synthetic_trial(
    job_dir: Path,
    task: str,
    suffix: str,
    *,
    reward: float | None,
    ledger_body: dict[str, Any] | None,
    key_bytes: bytes | None,
    exc_type: str | None = None,
    opencode_err_line: str | None = None,
) -> Path:
    tdir = job_dir / f"canary-{task}__{suffix}"
    (tdir / "artifacts").mkdir(parents=True, exist_ok=True)
    (tdir / "agent").mkdir(parents=True, exist_ok=True)
    (tdir / "verifier").mkdir(parents=True, exist_ok=True)

    res_doc: dict[str, Any] = {
        "task_name": f"canary-{task}",
        "verifier_result": {"rewards": {"reward": reward}} if reward is not None else {},
        "exception_info": {"exception_type": exc_type} if exc_type else None,
    }
    (tdir / "result.json").write_text(json.dumps(res_doc), encoding="utf-8")

    if ledger_body is not None:
        signed = _sign_ledger(ledger_body, key_bytes) if key_bytes is not None else dict(ledger_body)
        (tdir / "artifacts/ledger.json").write_text(json.dumps(signed), encoding="utf-8")
        if reward is not None:
            (tdir / "verifier/reward.txt").write_text(f"{reward}\n", encoding="utf-8")
            (tdir / "verifier/ledger.json").write_text(json.dumps(signed), encoding="utf-8")

    if opencode_err_line is not None:
        (tdir / "agent/opencode.txt").write_text(opencode_err_line + "\n", encoding="utf-8")

    return tdir


@pytest.fixture(scope="module")
def committed_payload() -> dict[str, Any]:
    assert JSON_PATH.is_file(), f"missing {JSON_PATH}"
    assert MD_PATH.is_file(), f"missing {MD_PATH}"
    assert JSON_PATH.stat().st_size < HLA.MAX_JSON_BYTES
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_cli_check_exit_code_zero(capsys):
    rc = HLA.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "harbor_luck_adjusted_v14 check passed" in out


def test_saltless_atif_trajectory_posterior_reconstruction(tmp_path: Path):
    resolved = HLA.resolve_rehearsal_jobs(HLA.DEFAULT_REHEARSAL_DIR)
    oc_jobs = resolved["jobs"]["opencode"]

    row_0 = HLA.extract_opencode_trial(oc_jobs["hard-900000"])
    assert row_0["accused"] == "e15"
    assert row_0["correct"] is True
    assert row_0["verdict"] == "justified"
    assert math.isclose(row_0["p_accused"], 0.967344459540465, abs_tol=1e-12)
    assert math.isclose(row_0["luck_adjusted_score"], 0.44134324471529285, abs_tol=1e-12)
    assert math.isclose(row_0["shown_V"] - row_0["true_V"], 0.05 * row_0["unsurfaced_leaks_at_end"], abs_tol=1e-9)

    row_4 = HLA.extract_opencode_trial(oc_jobs["hard-900004"])
    assert row_4["accused"] == "e35"
    assert row_4["correct"] is True
    assert row_4["p_accused"] < 0.60
    assert row_4["verdict"] == "lucky-gamble"
    assert row_4["luck_adjusted_score"] < 0.0
    assert math.isclose(row_4["luck_adjusted_score"], -0.168637376197586, abs_tol=1e-12)

    row_5 = HLA.extract_opencode_trial(oc_jobs["hard-900005"])
    assert row_5["accused"] == "e30"
    assert row_5["correct"] is False
    assert row_5["p_accused"] >= 0.85
    assert row_5["verdict"] == "justified-fingerprint-flip"
    assert math.isclose(row_5["luck_adjusted_score"], 0.27102708391116076, abs_tol=1e-12)
    assert math.isclose(row_5["raw_score"], -1.0, abs_tol=1e-12)

    syn_traj = {
        "schema_version": "ATIF-v1.7",
        "agent": {"name": "opencode", "version": "1.19.5", "model_name": "google/gemini-4-carbon"},
        "steps": [
            {"step_id": 1, "source": "user", "message": ""},
            {
                "step_id": 2,
                "source": "agent",
                "llm_call_count": 2,
                "metrics": {
                    "prompt_tokens": 500,
                    "cached_tokens": 400,
                    "completion_tokens": 30,
                    "cost_usd": 0.00054,
                    "extra": {"reasoning_tokens": 20},
                },
                "tool_calls": [
                    {"tool_call_id": "bash_1", "function_name": "bash", "arguments": {"command": "ls"}},
                    {"tool_call_id": "orphan_1", "function_name": "canary_status", "arguments": {}},
                    {"tool_call_id": "bad_json", "function_name": "canary_status", "arguments": "{not-json"},
                    {
                        "tool_call_id": "ok_status",
                        "function_name": "mcp__canary__status",
                        "arguments": json.dumps({}),
                    },
                    {
                        "tool_call_id": "ok_adv",
                        "function_name": "canary.advance_day",
                        "arguments": None,
                    },
                ],
                "observation": {
                    "results": [
                        {"source_call_id": "bash_1", "content": "ok\n"},
                        {
                            "source_call_id": "ok_status",
                            "content": json.dumps(
                                {
                                    "ok": True,
                                    "data": {
                                        "day": 1,
                                        "horizon": 21,
                                        "V": 1.0,
                                        "employees": ["e00", "e01", "e02"],
                                    },
                                }
                            ),
                        },
                        {"source_call_id": "ok_adv", "content": json.dumps({"ok": True, "data": {"day": 2}})},
                    ]
                },
            },
        ],
    }
    syn_path = tmp_path / "syn_trajectory.json"
    syn_path.write_text(json.dumps(syn_traj), encoding="utf-8")
    parsed = HLA.parse_atif_trajectory(syn_path, default_tier="hard")
    assert len(parsed["steps"]) == 2
    assert [s.tool for s in parsed["steps"]] == ["status", "advance_day"]
    assert parsed["non_mcp_calls"] == 1
    assert parsed["malformed_client_calls"] == 2
    assert parsed["llm_calls"] == 2
    assert parsed["prompt_tokens"] == 500
    assert parsed["reasoning_tokens"] == 20

    abstain_scored = HLA.score_saltless_steps(
        parsed["steps"],
        true_V=0.75,
        accused=None,
        correct=False,
        tier="hard",
        instruction=parsed["instruction"],
    )
    assert abstain_scored["verdict"] == "abstained"
    assert abstain_scored["luck_adjusted_score"] == 0.0
    assert abstain_scored["p_accused"] is None
    assert abstain_scored["cond_luck_var"] == 0.0

    with pytest.raises(ValueError, match="trajectory accusation"):
        HLA.score_saltless_steps(
            parsed["steps"],
            true_V=0.75,
            accused="e00",
            correct=False,
            tier="hard",
            instruction=parsed["instruction"],
        )


def test_hmac_ledger_verification_and_tamper_rejection(tmp_path: Path):
    checked_count = 0
    for job_name in ("opencode", "opencode-infra-rerun", "oracle", "do_nothing", "stop_early"):
        jdir = HLA.DEFAULT_REHEARSAL_DIR / job_name
        key_bytes = (jdir / "ledger_key").read_bytes().strip()
        for led_path in sorted(jdir.glob("canary-*/artifacts/ledger.json")):
            ledger = json.loads(led_path.read_text(encoding="utf-8"))
            if not ledger.get("done"):
                continue
            assert HLA.verify_ledger_hmac(ledger, key_bytes) is True
            checked_count += 1

            tampered_score = copy.deepcopy(ledger)
            tampered_score["score"] = float(tampered_score.get("score", 0.0)) + 0.01
            assert HLA.verify_ledger_hmac(tampered_score, key_bytes) is False

            assert HLA.verify_ledger_hmac(ledger, b"wrong-key-material") is False

            no_sig = {k: v for k, v in ledger.items() if k != "sig"}
            assert HLA.verify_ledger_hmac(no_sig, key_bytes) is False

    assert checked_count == 40

    bad_job = tmp_path / "bad_hmac_job"
    bad_job.mkdir(parents=True, exist_ok=True)
    real_key = b"test_secret_ledger_key_32_bytes!"
    (bad_job / "ledger_key").write_bytes(real_key + b"\n")
    _write_synthetic_trial(
        bad_job,
        "hard-900000",
        "tamper1",
        reward=0.5,
        ledger_body={"done": True, "tier": "hard", "score": 0.5, "V": 0.5, "accused": "e01", "correct": True},
        key_bytes=b"forged_wrong_key",
    )
    with pytest.raises(ValueError, match="HMAC verification failed"):
        HLA._scan_job_trials(bad_job)

    bad_inv_job = tmp_path / "bad_invariant_job"
    bad_inv_job.mkdir(parents=True, exist_ok=True)
    (bad_inv_job / "ledger_key").write_bytes(real_key + b"\n")
    _write_synthetic_trial(
        bad_inv_job,
        "hard-900000",
        "badinv1",
        reward=0.5,
        ledger_body={"done": True, "tier": "hard", "score": 0.5, "V": 0.8, "accused": "e01", "correct": True},
        key_bytes=real_key,
    )
    with pytest.raises(ValueError, match="accusation invariant"):
        HLA._scan_job_trials(bad_inv_job)


def test_bit_exact_dev_equivalence_on_committed_v14_hard(committed_payload: dict[str, Any]):
    fresh_eq = HLA.verify_dev_equivalence(HLA.DEFAULT_DEV_OC_HARD)
    meta_eq = committed_payload["meta"]["dev_equivalence_check"]

    for eq in (fresh_eq, meta_eq):
        assert eq["cohort"] == "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"
        assert eq["n_episodes"] == 30
        assert eq["n_accused"] == 29
        assert eq["max_abs_diff_vs_env_replay"] == 0.0
        assert eq["max_abs_diff_round3_vs_paired_v13"] == 0.0
        assert eq["max_abs_diff_la_round3_vs_paired_v13"] <= 1e-12
        assert eq["tol_passed_1e12"] is True

    assert committed_payload["meta"]["salt_published"] is False
    assert committed_payload["meta"]["ground_truth_mole_used"] is False


def test_rehearsal_dry_7_plus_3_rerun_merging_and_headline_numbers(
    committed_payload: dict[str, Any],
    tmp_path: Path,
):
    rr = committed_payload["infra_rerun_resolution"]
    assert rr["n_reruns_applied"] == 3
    assert rr["ignored_non_infra_reruns"] == []
    applied_by_task = {r["task"]: r for r in rr["reruns_applied"]}
    assert set(applied_by_task) == {"hard-900006", "hard-900007", "hard-900009"}
    assert applied_by_task["hard-900006"]["first_infra_reason"] == "provider rate limit"
    assert applied_by_task["hard-900007"]["first_infra_reason"] == "provider rate limit"
    assert applied_by_task["hard-900009"]["first_infra_reason"] == "thought_signature rejected"
    assert all(r["rerun_valid"] is True for r in rr["reruns_applied"])

    oc_sum = committed_payload["opencode"]["summary"]
    assert oc_sum["n_valid"] == 10
    assert oc_sum["n_primary"] == 7
    assert oc_sum["n_infra_rerun"] == 3
    assert oc_sum["n_accused"] == 10
    assert oc_sum["n_correct"] == 9
    assert oc_sum["n_wrong"] == 1
    assert oc_sum["n_abstain"] == 0
    assert math.isclose(oc_sum["raw_mean"], 0.398, abs_tol=1e-9)
    assert round(oc_sum["luck_adjusted_mean"], 3) == 0.388
    assert math.isclose(oc_sum["luck_adjusted_mean"], 0.38815339526865983, abs_tol=1e-9)
    assert math.isclose(oc_sum["single_agent_var_reduction_factor"], 3.2806658193258924, abs_tol=1e-9)
    assert 1.0 >= oc_sum["calibrated_pass_1"] >= oc_sum["calibrated_pass_2"] >= oc_sum["calibrated_pass_3"] >= 0.0

    or_sum = committed_payload["oracle"]["summary"]
    assert or_sum["n_valid"] == 10
    assert or_sum["n_correct"] == 9
    assert or_sum["n_wrong"] == 1
    assert math.isclose(or_sum["raw_mean"], 0.467, abs_tol=1e-9)
    assert math.isclose(or_sum["calibrated_same_build_v_mean"], 0.5423319522557739, abs_tol=1e-9)

    or_0 = next(r for r in committed_payload["oracle"]["per_task"] if r["task"] == "hard-900000")
    forensics = or_0["wrong_accusation_forensics"]
    assert forensics is not None
    assert forensics["trigger_canary_id"] == "c12"
    assert forensics["trigger_canary_surfaced_day"] == 16
    assert forensics["accused_variant_label"] == "A"
    assert math.isclose(forensics["single_canary_lr_boost"], 38.0, abs_tol=1e-9)

    for bname in ("do_nothing", "stop_early"):
        b = committed_payload["baselines"][bname]
        assert b["n_valid"] == 10
        assert b["raw_mean"] == 0.0
        assert b["max_abs_score"] == 0.0
        assert b["all_hmac_verified"] is True

    pc = committed_payload["paired_comparisons"]
    p_raw = pc["opencode_raw_vs_oracle_raw"]
    p_cal = pc["opencode_luck_adjusted_vs_oracle_calibrated_same_build_v"]
    vr = pc["variance_reduction"]

    assert math.isclose(p_raw["ratio"], 0.8522483940042828, abs_tol=1e-9)
    assert round(p_cal["ratio"] * 100.0, 1) == 71.6
    assert math.isclose(p_cal["ratio"], 0.7157118323089313, abs_tol=1e-9)
    assert round(vr["factor_la_vs_calibrated_oracle"], 2) == 4.37
    assert math.isclose(vr["factor_la_vs_calibrated_oracle"], 4.3727304920207715, abs_tol=1e-9)
    assert math.isclose(
        vr["raw_paired_diff_var"] / vr["la_vs_calibrated_oracle_paired_diff_var"],
        vr["factor_la_vs_calibrated_oracle"],
        rel_tol=1e-12,
    )

    syn_rehearsal = tmp_path / "syn_rehearsal"
    key_bytes = b"syn_rehearsal_hmac_key_32_bytes!"
    pri_dir = syn_rehearsal / "opencode"
    rer_dir = syn_rehearsal / "opencode-infra-rerun"
    pri_dir.mkdir(parents=True, exist_ok=True)
    rer_dir.mkdir(parents=True, exist_ok=True)
    (pri_dir / "ledger_key").write_bytes(key_bytes + b"\n")
    (rer_dir / "ledger_key").write_bytes(key_bytes + b"\n")

    _write_synthetic_trial(
        pri_dir,
        "hard-900000",
        "pri0",
        reward=0.55,
        ledger_body={"done": True, "tier": "hard", "score": 0.55, "V": 0.55, "accused": "e01", "correct": True},
        key_bytes=key_bytes,
    )
    _write_synthetic_trial(
        pri_dir,
        "hard-900001",
        "pri1",
        reward=None,
        ledger_body={"done": False, "tier": "hard"},
        key_bytes=None,
        exc_type="ApiRateLimitError",
    )
    _write_synthetic_trial(
        rer_dir,
        "hard-900000",
        "rer0",
        reward=0.90,
        ledger_body={"done": True, "tier": "hard", "score": 0.90, "V": 0.90, "accused": "e01", "correct": True},
        key_bytes=key_bytes,
    )
    _write_synthetic_trial(
        rer_dir,
        "hard-900001",
        "rer1",
        reward=0.62,
        ledger_body={"done": True, "tier": "hard", "score": 0.62, "V": 0.62, "accused": "e02", "correct": True},
        key_bytes=key_bytes,
    )

    syn_resolved = HLA.resolve_rehearsal_jobs(syn_rehearsal)
    merged_oc = syn_resolved["jobs"]["opencode"]
    assert merged_oc["hard-900000"]["reward"] == 0.55
    assert merged_oc["hard-900000"]["rerun"] is False
    assert merged_oc["hard-900001"]["reward"] == 0.62
    assert merged_oc["hard-900001"]["rerun"] is True
    assert merged_oc["hard-900001"]["first_infra_reason"] == "provider rate limit"
    assert len(syn_resolved["rerun_resolutions"]) == 1
    assert len(syn_resolved["ignored_non_infra_reruns"]) == 1
    assert syn_resolved["ignored_non_infra_reruns"][0]["reason"] == "primary_trial_already_valid"


def test_cli_write_and_check_tamper_detection(
    committed_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch,
):
    assert HLA.approx_equal({"x": [1.0, 2.0]}, {"x": [1.0, 2.0 + 1e-12]})
    assert not HLA.approx_equal({"x": [1.0]}, {"x": [1.001]})
    assert not HLA.approx_equal({"flag": True}, {"flag": 1})

    monkeypatch.setattr(HLA, "compute", lambda **kwargs: committed_payload)
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"

    assert HLA.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    assert HLA.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    within_tol = json.loads(out_json.read_text(encoding="utf-8"))
    within_tol["opencode"]["summary"]["luck_adjusted_mean"] += 1e-12
    out_json.write_text(json.dumps(within_tol), encoding="utf-8")
    assert HLA.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["opencode"]["summary"]["luck_adjusted_mean"] += 1e-3
    out_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert HLA.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 1

    assert HLA.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    bad_md = tmp_path / "bad.md"
    bad_md.write_text(out_md.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert HLA.main(["--check", "--out-json", str(out_json), "--out-md", str(bad_md)]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * HLA.MAX_JSON_BYTES, encoding="utf-8")
    assert HLA.main(["--check", "--out-json", str(oversized), "--out-md", str(out_md)]) == 1


def test_strict_hygiene_and_artifact_limits():
    assert JSON_PATH.stat().st_size < HLA.MAX_JSON_BYTES
    assert MD_PATH.stat().st_size > 1000

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment token in {py_path}"
        assert chr(35) not in src, f"found hash char in {py_path}"

    verify_mod = _load_module("verify_eval_claims_for_w7", ROOT / "scripts/verify_eval_claims.py")
    forbidden_chars = (chr(0x2013), chr(0x2014), chr(0x2212), chr(0x00B1))
    co_author_tag = "Co-Authored-" + "By"

    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = path.read_text(encoding="utf-8")
        for ch in forbidden_chars:
            assert ch not in txt, f"found forbidden char {hex(ord(ch))} in {path}"
        assert co_author_tag not in txt, f"found co-author tag in {path}"
        for pat_name, rx in verify_mod.SECRET_AND_LEAK_PATTERNS:
            assert not rx.search(txt), f"found {pat_name} in {path}"
