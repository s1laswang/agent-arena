from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from canary import rules
from canary.env import Env
from canary.mcp_server import sign_ledger
from canary.redteam import anticheat as ac
from canary.redteam import tamper_guard as tg

ROOT = Path(__file__).resolve().parents[1]


def _pick_episode(rel_file: str, seed: int) -> dict[str, Any]:
    for ln in (ROOT / rel_file).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        ep = json.loads(ln)
        if int(ep["seed"]) == seed:
            return ep
    raise KeyError((rel_file, seed))


def _write_run(
    tmp_path: Path,
    rel_dir: str,
    episodes: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> Path:
    run_dir = tmp_path / "data" / "runs" / "committed" / rel_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(ep) for ep in episodes) + "\n",
        encoding="utf-8",
    )
    if meta is not None:
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return run_dir


def _copy_harbor_trial(tmp_path: Path, job: str, predicate=None) -> Path:
    src_job = ROOT / "results" / "harbor" / job
    dst_job = tmp_path / "results" / "harbor" / job
    dst_job.mkdir(parents=True, exist_ok=True)
    if (src_job / "ledger_key").is_file():
        shutil.copy2(src_job / "ledger_key", dst_job / "ledger_key")
    for res_p in sorted(src_job.glob("*/result.json")):
        if predicate is None or predicate(res_p.parent):
            dst = dst_job / res_p.parent.name
            shutil.copytree(res_p.parent, dst)
            return dst
    raise LookupError(job)


def test_real_opencode_with_companion_transcript_passes_cleanly(tmp_path: Path):
    src_dir = ROOT / "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard"
    ep = _pick_episode("data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl", 2)
    meta = json.loads((src_dir / "meta.json").read_text(encoding="utf-8"))
    run_dir = _write_run(tmp_path, "v1.4/opencode-flash/hard", [ep], meta)
    (run_dir / "transcripts").mkdir()
    shutil.copy2(src_dir / "transcripts" / "2.txt", run_dir / "transcripts" / "2.txt")

    rows = tg.replay_committed(tmp_path)
    assert len(rows) == 1
    assert rows[0]["replay_consistent"] is True, rows[0]
    assert rows[0]["step_mismatches"] == 0
    assert rows[0]["steps_client_only"] == 1
    assert rows[0]["steps_truncated_checked"] == 1


@pytest.mark.parametrize("forged_end_reason", ["horizon", "accused", "tool_cap"])
def test_r15_truncated_accuse_end_reason_mismatch_fails_closed(tmp_path: Path, forged_end_reason: str):
    ep = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 18)
    tampered = copy.deepcopy(ep)
    tampered["steps"] = tampered["steps"][:-1]
    tampered["score"] = 0.0
    tampered["accused"] = None
    tampered["correct"] = False
    tampered["end_reason"] = forged_end_reason
    _write_run(tmp_path, "v1.4/tamper/medium", [tampered], {"tiers_version": "v1.4"})

    row = tg.replay_committed(tmp_path)[0]
    assert row["replay_consistent"] is False, row
    assert row["mismatches"] and any("end_reason" in p for p in row["mismatches"][0].get("tamper", []))


def test_r15_companion_txt_transcript_catches_truncated_accuse_even_if_marked_invalid(tmp_path: Path):
    src_dir = ROOT / "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard"
    ep = _pick_episode("data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl", 0)
    meta = json.loads((src_dir / "meta.json").read_text(encoding="utf-8"))
    tampered = copy.deepcopy(ep)
    tampered["steps"] = tampered["steps"][:-1]
    tampered["score"] = 0.0
    tampered["accused"] = None
    tampered["correct"] = False
    tampered["end_reason"] = "error"
    tampered["meta"] = {
        **(tampered.get("meta") or {}),
        "valid": False,
        "error": "infra:provider_unavailable",
        "ledger_events": [],
        "V_final": None,
    }
    run_dir = _write_run(tmp_path, "v1.4/opencode-flash/hard", [tampered], meta)
    (run_dir / "transcripts").mkdir()
    shutil.copy2(src_dir / "transcripts" / "0.txt", run_dir / "transcripts" / "0.txt")

    row = tg.replay_committed(tmp_path)[0]
    assert row["replay_consistent"] is False, row
    assert any("companion transcript 0.txt" in p for p in row["mismatches"][0].get("tamper", []))


def test_r15_companion_json_transcript_catches_truncated_accuse(tmp_path: Path):
    src_dir = ROOT / "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium"
    ep = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 18)
    meta = json.loads((src_dir / "meta.json").read_text(encoding="utf-8"))
    tampered = copy.deepcopy(ep)
    tampered["steps"] = tampered["steps"][:-1]
    tampered["score"] = 0.0
    tampered["accused"] = None
    tampered["correct"] = False
    tampered["end_reason"] = "error"
    tampered["meta"] = {"valid": False, "error": "infra:provider_unavailable"}
    run_dir = _write_run(tmp_path, "v1.4/inproc/medium", [tampered], meta)
    (run_dir / "transcripts").mkdir()
    shutil.copy2(src_dir / "transcripts" / "18.json", run_dir / "transcripts" / "18.json")

    row = tg.replay_committed(tmp_path)[0]
    assert row["replay_consistent"] is False, row
    assert any("companion transcript 18.json" in p for p in row["mismatches"][0].get("tamper", []))


def test_r08_flipping_valid_false_on_completed_wrong_accusation_fails_closed(tmp_path: Path):
    ep_wrong = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 18)
    tampered = copy.deepcopy(ep_wrong)
    tampered["meta"] = {**(tampered.get("meta") or {}), "valid": False, "error": "infra:provider_quota"}
    _write_run(tmp_path, "v1.4/tamper/medium", [tampered], {"tiers_version": "v1.4"})

    row = tg.replay_committed(tmp_path)[0]
    assert row["replay_consistent"] is False, row
    assert any("invalid episode mismatch" in p for p in row["mismatches"][0].get("tamper", []))


@pytest.mark.parametrize("bad_correct", [True, "yes", 1])
def test_r13_forged_correct_flag_fails_closed(tmp_path: Path, bad_correct: Any):
    ep_wrong = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 18)
    tampered = copy.deepcopy(ep_wrong)
    tampered["correct"] = bad_correct
    _write_run(tmp_path, "v1.4/tamper/medium", [tampered], {"tiers_version": "v1.4"})

    row = tg.replay_committed(tmp_path)[0]
    assert row["replay_consistent"] is False, row
    assert any("correct=" in p for p in row["mismatches"][0].get("tamper", []))


def test_r09_null_step_result_fails_closed(tmp_path: Path):
    ep_win = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 0)
    tampered = copy.deepcopy(ep_win)
    tampered["steps"][0]["result"] = None
    _write_run(tmp_path, "v1.4/tamper/medium", [tampered], {"tiers_version": "v1.4"})

    row = tg.replay_committed(tmp_path)[0]
    assert row["replay_consistent"] is False, row
    assert row["step_mismatches"] >= 1


def test_r07_disguised_final_call_and_non_opencode_spoof_fail_closed(tmp_path: Path):
    ep_horizon = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 3)
    tampered_final = copy.deepcopy(ep_horizon)
    tampered_final["steps"][-1] = {
        "t": len(tampered_final["steps"]) - 1,
        "day": tampered_final["steps"][-1]["day"],
        "tool": "bash",
        "args": {"command": "ls"},
        "result": {
            "ok": False,
            "error": "Model tried to call unavailable tool 'invalid'. Available tools: canary_accuse.",
        },
    }
    _write_run(tmp_path / "case_final", "v1.4/tamper/medium", [tampered_final], {"tiers_version": "v1.4"})
    row_final = tg.replay_committed(tmp_path / "case_final")[0]
    assert row_final["replay_consistent"] is False, row_final
    assert row_final["step_mismatches"] >= 1

    ep_win = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 0)
    spoofed_inproc = copy.deepcopy(ep_win)
    spoofed_inproc["steps"].insert(
        1,
        {
            "t": 1,
            "day": 1,
            "tool": "bash",
            "args": {"command": "whoami"},
            "result": {
                "ok": False,
                "error": "Model tried to call unavailable tool 'invalid'. Available tools: canary_accuse.",
            },
        },
    )
    _write_run(
        tmp_path / "case_inproc",
        "v1.4/tamper/medium",
        [spoofed_inproc],
        {"tiers_version": "v1.4", "provider": "gemini"},
    )
    row_inproc = tg.replay_committed(tmp_path / "case_inproc")[0]
    assert row_inproc["replay_consistent"] is False, row_inproc
    assert row_inproc["step_mismatches"] >= 1


def test_r03_opencode_truncation_tail_edit_and_bracket_suffix_check(tmp_path: Path):
    ep_trunc = _pick_episode("data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl", 2)
    tampered = copy.deepcopy(ep_trunc)
    idx = next(i for i, st in enumerate(tampered["steps"]) if "raw" in (st.get("result") or {}))
    orig = tampered["steps"][idx]["result"]["raw"]
    marker = "Full output saved to: "
    pos = orig.index(marker) + len(marker)
    tail_len = len(orig) - pos
    tampered["steps"][idx]["result"]["raw"] = orig[:pos] + ("/tmp/FORGED_TAIL_" + ("X" * tail_len))[:tail_len]
    _write_run(
        tmp_path / "tail_edit",
        "v1.4/opencode-flash/hard",
        [tampered],
        {"tiers_version": "v1.4", "provider": "opencode"},
    )
    row = tg.replay_committed(tmp_path / "tail_edit")[0]
    assert row["replay_consistent"] is False, row
    assert row["step_mismatches"] >= 1

    ep_win = _pick_episode("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl", 0)
    full_json = json.dumps(ep_win["steps"][0]["result"])
    prefix = full_json[:40]
    rem = len(full_json.encode("utf-8")) - len(prefix.encode("utf-8"))
    assert tg.valid_bracket_truncated_suffix(f"{prefix}[... truncated {rem} bytes ...]", full_json) is True
    assert tg.valid_bracket_truncated_suffix(f"{prefix}[... truncated {rem + 1} bytes ...]", full_json) is False
    assert tg.valid_bracket_truncated_suffix(f"{'X' * 40}[... truncated {rem} bytes ...]", full_json) is False

    bad_bracket_ep = copy.deepcopy(ep_win)
    bad_bracket_ep["steps"][0]["result"] = {"raw": f"{'X' * 40}[... truncated {rem} bytes ...]"}
    _write_run(tmp_path / "bad_bracket", "v1.4/tamper/medium", [bad_bracket_ep], {"tiers_version": "v1.4"})
    row_bracket = tg.replay_committed(tmp_path / "bad_bracket")[0]
    assert row_bracket["replay_consistent"] is False, row_bracket
    assert row_bracket["step_mismatches"] >= 1


@pytest.mark.parametrize("forged_version", ["v9.9", "v2.0", "v0.0", "forged"])
def test_r16_forged_tiers_version_fails_closed_while_historical_v12_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    forged_version: str,
):
    ep = _pick_episode("data/runs/committed/v1.3/codex-gpt-5.5-full/medium/episodes.jsonl", 0)
    forged = copy.deepcopy(ep)
    forged["score"] = 0.99
    _write_run(tmp_path / "forged", f"{forged_version}/tamper/medium", [forged], {"tiers_version": forged_version})
    row_forged = tg.replay_committed(tmp_path / "forged")[0]
    assert row_forged["replay_consistent"] is False, row_forged
    assert row_forged["mismatches"] and "unknown tiers_version" in row_forged["mismatches"][0]["tamper"][0]

    monkeypatch.setattr(rules, "TIERS_HISTORY", {"v1.3": rules.TIERS_V13})
    _write_run(tmp_path / "hist_v12", "legacy/gpt-5.5/medium", [ep], {"tiers_version": "v1.2"})
    row_v12 = tg.replay_committed(tmp_path / "hist_v12")[0]
    assert row_v12["not_replayable"] == 1
    assert row_v12["replay_consistent"] is None


def test_h12_null_harbor_reward_with_ledger_accusation_or_nonzero_score_fails_closed(tmp_path: Path):
    neg_trial = _copy_harbor_trial(
        tmp_path / "tampered",
        "signed-cheat",
        predicate=lambda td: float(
            json.loads((td / "result.json").read_text(encoding="utf-8"))["verifier_result"]["rewards"]["reward"]
        )
        < 0,
    )
    res = json.loads((neg_trial / "result.json").read_text(encoding="utf-8"))
    res["verifier_result"] = {"rewards": {"reward": None}}
    res["exception_info"] = {"exception_type": "AgentTimeoutError", "exception_message": "forged timeout"}
    (neg_trial / "result.json").write_text(json.dumps(res), encoding="utf-8")

    row = tg.check_harbor_trial(neg_trial)
    assert row["consistent"] is False, row
    assert any("verifier reward is None" in p for p in row["problems"]), row

    clean_infra = _copy_harbor_trial(tmp_path / "clean_infra", "g-gemini-try2")
    cres = json.loads((clean_infra / "result.json").read_text(encoding="utf-8"))
    cres["verifier_result"] = None
    cres["exception_info"] = {"exception_type": "AgentTimeoutError", "exception_message": "genuine infra failure"}
    (clean_infra / "result.json").write_text(json.dumps(cres), encoding="utf-8")
    for rel in ("artifacts/ledger.json", "verifier/ledger.json"):
        if (clean_infra / rel).is_file():
            (clean_infra / rel).unlink()
    clean_row = tg.check_harbor_trial(clean_infra)
    assert clean_row["consistent"] is None, clean_row
    assert clean_row["problems"] == []


def test_harbor_dup_keys_symlinks_missing_config_and_missing_isolation_fail_closed(tmp_path: Path):
    t_dup = _copy_harbor_trial(tmp_path / "dup", "cheat-probe")
    raw_led = (t_dup / "artifacts/ledger.json").read_text(encoding="utf-8").strip()
    dup_led = '{"score": 1.0, ' + raw_led[1:]
    for rel in ("artifacts/ledger.json", "verifier/ledger.json"):
        (t_dup / rel).write_text(dup_led, encoding="utf-8")
    r_dup = tg.check_harbor_trial(t_dup)
    assert r_dup["consistent"] is False and any("duplicate JSON keys" in p for p in r_dup["problems"]), r_dup

    t_sym = _copy_harbor_trial(tmp_path / "sym", "signed-stop_early")
    ext = tmp_path / "ext_reward.txt"
    ext.write_text((t_sym / "verifier/reward.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (t_sym / "verifier/reward.txt").unlink()
    (t_sym / "verifier/reward.txt").symlink_to(ext)
    r_sym = tg.check_harbor_trial(t_sym)
    assert r_sym["consistent"] is False and any("symlink" in p for p in r_sym["problems"]), r_sym

    t_iso = _copy_harbor_trial(tmp_path / "iso", "cheat-probe")
    (t_iso / "agent/isolation.txt").unlink()
    r_iso = tg.check_harbor_trial(t_iso)
    assert r_iso["consistent"] is False and any("isolation.txt is missing" in p for p in r_iso["problems"]), r_iso

    t_cfg = _copy_harbor_trial(tmp_path / "cfg", "cheat-probe")
    (t_cfg / "agent/cheat.json").unlink()
    (t_cfg / "config.json").unlink()
    r_cfg = tg.check_harbor_trial(t_cfg)
    assert r_cfg["consistent"] is False and any("config.json is missing" in p for p in r_cfg["problems"]), r_cfg


def test_retired_ledger_key_resign_notice_and_agent_log_crosscheck(tmp_path: Path):
    t_signed = _copy_harbor_trial(tmp_path / "signed_ok", "signed-stop_early")
    row_ok = tg.check_harbor_trial(t_signed)
    assert row_ok["consistent"] is True, row_ok
    assert row_ok["retired_key_published"] is True
    assert row_ok["retired_key_resign_notice"] == tg.RETIRED_KEY_RESIGN_NOTICE

    t_resigned = _copy_harbor_trial(tmp_path / "resigned_swap", "signed-stop_early")
    key_hex = (t_resigned.parent / "ledger_key").read_text(encoding="utf-8").strip()
    for rel in ("artifacts/ledger.json", "verifier/ledger.json"):
        d = json.loads((t_resigned / rel).read_text(encoding="utf-8"))
        ev = next(x for x in d["ledger"] if x["event"] == "accused")
        ev["detail"]["employee"] = "e00"
        d["accused"] = "e00"
        signed = sign_ledger({k: v for k, v in d.items() if k != "sig"}, key_hex)
        (t_resigned / rel).write_text(json.dumps(signed), encoding="utf-8")
    row_swap = tg.check_harbor_trial(t_resigned)
    assert row_swap["consistent"] is False, row_swap
    assert any("agent/solver.txt accused" in p for p in row_swap["problems"]), row_swap


def test_rehearsal_dry_verification_and_rerun_anti_cherrypick(tmp_path: Path):
    real_reh = tg.verify_rehearsal_run(ROOT / "results" / "harbor" / "rehearsal-dry", repo_root=ROOT)
    assert real_reh["passed"] is True, real_reh["problems"]
    assert real_reh["n_jobs"] == 5
    assert real_reh["n_trials"] == 43
    assert real_reh["n_hmac_verified"] == 43
    assert real_reh["n_retired_key_resign_notices"] == 43
    assert real_reh["shared_retired_key_count"] == 1
    assert real_reh["table_md_matches"] is True
    assert real_reh["job_means"] == {
        "do_nothing": 0.0,
        "opencode": 0.398,
        "oracle": 0.467,
        "stop_early": 0.0,
    }

    dst_reh = tmp_path / "results" / "harbor" / "rehearsal-dry"
    for jname in ("oracle", "do_nothing", "stop_early", "opencode", "opencode-infra-rerun"):
        src_j = ROOT / "results" / "harbor" / "rehearsal-dry" / jname
        dst_j = dst_reh / jname
        dst_j.mkdir(parents=True, exist_ok=True)
        for top_f in ("result.json", "ledger_key", "config.json"):
            if (src_j / top_f).is_file():
                shutil.copy2(src_j / top_f, dst_j / top_f)
        for tr_res in sorted(src_j.glob("*/result.json")):
            if "900005" in tr_res.parent.name or "900006" in tr_res.parent.name:
                shutil.copytree(tr_res.parent, dst_j / tr_res.parent.name)

    fake_rerun = dst_reh / "opencode-infra-rerun" / "canary-hard-900005__forged"
    shutil.copytree(
        next((dst_reh / "opencode-infra-rerun").glob("canary-hard-900006*")),
        fake_rerun,
    )
    fr_res = json.loads((fake_rerun / "result.json").read_text(encoding="utf-8"))
    fr_res["task_name"] = "canary/hard-900005"
    fr_res["trial_name"] = "canary-hard-900005__forged"
    (fake_rerun / "result.json").write_text(json.dumps(fr_res), encoding="utf-8")

    hb_rows = tg.harbor_consistency(tmp_path)
    rerun_job_row = next(r for r in hb_rows if r["trial"] == "results/harbor/rehearsal-dry/opencode-infra-rerun/ (job)")
    assert rerun_job_row["consistent"] is False, rerun_job_row
    assert any("replaces non-infra trial" in p for p in rerun_job_row["problems"]), rerun_job_row


def _build_post_1bc3e281_opencode_episode() -> tuple[dict[str, Any], dict[str, Any], int, str]:
    src_dir = ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium"
    ep = copy.deepcopy(_pick_episode("data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl", 0))
    meta = json.loads((src_dir / "meta.json").read_text(encoding="utf-8"))
    with rules.tiers_version("v1.4"):
        env = Env(ep["tier"], int(ep["seed"]))
        target_idx = -1
        target_detail = ""
        for idx, st in enumerate(ep["steps"]):
            r = env.call(st["tool"], st["args"])
            if not r.ok and isinstance(r.data, dict) and set(r.data) == {"detail"}:
                inner = {"ok": False, "data": {"detail": r.data["detail"]}, "error": r.error}
                ep["steps"][idx]["result"] = {"ok": False, "error": json.dumps(inner)}
                if target_idx < 0:
                    target_idx = idx
                    target_detail = str(r.data["detail"])
    assert target_idx >= 0 and target_detail
    return ep, meta, target_idx, target_detail


def test_fix_d_pre_1bc3e281_and_post_1bc3e281_opencode_error_detail_replay(tmp_path: Path):
    src_dir = ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium"
    pre_ep = _pick_episode("data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl", 0)
    meta = json.loads((src_dir / "meta.json").read_text(encoding="utf-8"))

    _write_run(tmp_path / "pre_clean", "v1.4/opencode-carbon/medium", [pre_ep], meta)
    row_pre = tg.replay_committed(tmp_path / "pre_clean")[0]
    assert row_pre["replay_consistent"] is True, row_pre
    assert row_pre["consistent"] == 1
    assert row_pre["step_mismatches"] == 0
    assert row_pre["mismatches"] == []

    pre_bad = copy.deepcopy(pre_ep)
    pre_bad["steps"][3]["result"] = {
        "ok": False,
        "error": json.dumps({"ok": False, "data": {}, "error": "unknown tool"}),
    }
    _write_run(tmp_path / "pre_tampered", "v1.4/opencode-carbon/medium", [pre_bad], meta)
    row_pre_bad = tg.replay_committed(tmp_path / "pre_tampered")[0]
    assert row_pre_bad["replay_consistent"] is False, row_pre_bad
    assert row_pre_bad["step_mismatches"] >= 1

    post_ep, post_meta, err_idx, real_detail = _build_post_1bc3e281_opencode_episode()
    _write_run(tmp_path / "post_clean", "v1.4/opencode-carbon/medium", [post_ep], post_meta)
    upstream_row = ac.replay_committed(tmp_path / "post_clean")[0]
    assert upstream_row["replay_consistent"] is True
    assert upstream_row["step_mismatches"] == 0
    row_post = tg.replay_committed(tmp_path / "post_clean")[0]
    assert row_post["replay_consistent"] is True, row_post
    assert row_post["consistent"] == 1
    assert row_post["step_mismatches"] == 0
    assert row_post["mismatches"] == []

    forged_detail_ep = copy.deepcopy(post_ep)
    forged_detail_ep["steps"][err_idx]["result"] = {
        "ok": False,
        "error": json.dumps({"ok": False, "data": {"detail": real_detail + " forged"}, "error": "invalid arguments"}),
    }
    _write_run(tmp_path / "post_forged_detail", "v1.4/opencode-carbon/medium", [forged_detail_ep], post_meta)
    row_forged_detail = tg.replay_committed(tmp_path / "post_forged_detail")[0]
    assert row_forged_detail["replay_consistent"] is False, row_forged_detail
    assert row_forged_detail["step_mismatches"] >= 1

    forged_outer_ep = copy.deepcopy(post_ep)
    forged_outer_ep["steps"][err_idx]["result"] = {
        "ok": True,
        "error": json.dumps({"ok": False, "data": {"detail": real_detail}, "error": "invalid arguments"}),
    }
    _write_run(tmp_path / "post_forged_outer", "v1.4/opencode-carbon/medium", [forged_outer_ep], post_meta)
    row_forged_outer = tg.replay_committed(tmp_path / "post_forged_outer")[0]
    assert row_forged_outer["replay_consistent"] is False, row_forged_outer
    assert row_forged_outer["step_mismatches"] >= 1

    forged_score_ep = copy.deepcopy(post_ep)
    forged_score_ep["score"] = round(float(forged_score_ep["score"]) + 0.05, 6)
    _write_run(tmp_path / "post_forged_score", "v1.4/opencode-carbon/medium", [forged_score_ep], post_meta)
    row_forged_score = tg.replay_committed(tmp_path / "post_forged_score")[0]
    assert row_forged_score["replay_consistent"] is False, row_forged_score
    assert len(row_forged_score["mismatches"]) == 1

    forged_verdict_ep = copy.deepcopy(post_ep)
    forged_verdict_ep["correct"] = not bool(forged_verdict_ep["correct"])
    _write_run(tmp_path / "post_forged_verdict", "v1.4/opencode-carbon/medium", [forged_verdict_ep], post_meta)
    row_forged_verdict = tg.replay_committed(tmp_path / "post_forged_verdict")[0]
    assert row_forged_verdict["replay_consistent"] is False, row_forged_verdict
    assert any("correct=" in p for p in row_forged_verdict["mismatches"][0].get("tamper", []))

    non_oc_ep = copy.deepcopy(post_ep)
    non_oc_ep["agent"] = "gemini:gemini-4-carbon"
    non_oc_meta = {"tiers_version": "v1.4", "provider": "gemini", "harness": "inproc"}
    _write_run(tmp_path / "post_spoof_inproc", "v1.4/inproc-carbon/medium", [non_oc_ep], non_oc_meta)
    row_spoof_inproc = tg.replay_committed(tmp_path / "post_spoof_inproc")[0]
    assert row_spoof_inproc["replay_consistent"] is False, row_spoof_inproc

    ep_seed1_tampered = copy.deepcopy(
        _pick_episode("data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl", 1)
    )
    ep_seed1_tampered["score"] = 0.99
    _write_run(tmp_path / "post_mixed_two", "v1.4/opencode-carbon/medium", [post_ep, ep_seed1_tampered], post_meta)
    row_mixed = tg.replay_committed(tmp_path / "post_mixed_two")[0]
    assert row_mixed["replay_consistent"] is False, row_mixed
    assert row_mixed["consistent"] == 1
    assert [m["seed"] for m in row_mixed["mismatches"]] == [1]
