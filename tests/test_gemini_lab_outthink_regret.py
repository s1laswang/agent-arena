from __future__ import annotations

import ast
import copy
import io
import json
import math
import os
import subprocess
import sys
import tokenize
from dataclasses import asdict
from pathlib import Path

import pytest

from canary.env import Env
from canary.gemini import outthink, outthink_regret
from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy, accuse_value
from canary.types import Step

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "canary" / "gemini" / "outthink_regret.py"
REGRET_JSON_PATH = ROOT / "results" / "gemini" / "outthink_regret.json"
CASES_JSON_PATH = ROOT / "results" / "gemini" / "out_think_gemini.json"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
FORBIDDEN_NET = "fetch" + "("


def test_outthink_regret_cli_check_and_artifact_in_sync(capsys):
    assert REGRET_JSON_PATH.is_file()
    rc = outthink_regret.main(["--check"])
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "OK: 12 cases, 39 ladder runs verified." in captured.out


def test_twelve_cases_frozen_specs_and_entropy_identities():
    cases_doc = json.loads(CASES_JSON_PATH.read_text(encoding="utf-8"))
    regret_doc = json.loads(REGRET_JSON_PATH.read_text(encoding="utf-8"))

    meta = regret_doc["meta"]
    assert meta["tiers_version"] == "v1.4"
    assert meta["case_count"] == 12
    assert meta["level_run_count"] == 39
    assert meta["hold_fire_cases"] == 8
    assert meta["accuse_cases"] == 4
    assert set(meta["thinking_levels"]) == {"minimal", "low", "medium", "high", "xhigh"}

    raw_cases = cases_doc["cases"]
    reg_cases = regret_doc["cases"]
    assert len(reg_cases) == len(raw_cases) == 12
    assert [c["id"] for c in reg_cases] == [spec[0] for spec in outthink.CASE_SPECS]

    pinpoint_zero_entropy_seen = 0
    noisy_full_elim_seen = 0

    for raw_c, reg_c in zip(raw_cases, reg_cases):
        cid = reg_c["id"]
        assert cid == raw_c["id"]
        assert reg_c["tier"] == raw_c["tier"]
        assert reg_c["seed"] == raw_c["seed"]
        assert reg_c["model"] == raw_c["model"]
        assert reg_c["anchor_level"] == raw_c["anchor_level"]
        assert reg_c["decision_day"] == raw_c["decision_day"]
        assert reg_c["decision_step"] == raw_c["decision_step"]
        assert reg_c["true_mole"] == raw_c["true_mole"]
        assert reg_c["value_at_decision"] == pytest.approx(raw_c["value_at_decision"], abs=1e-4)

        expected_n = 40 if reg_c["tier"] == "hard" else 20
        assert reg_c["n_suspects"] == expected_n == len(raw_c["suspects"])

        prior_h = reg_c["prior_entropy_bits"]
        post_h = reg_c["posterior_entropy_bits"]
        mi_h = reg_c["mutual_information_bits"]
        assert prior_h == pytest.approx(math.log2(expected_n), abs=1e-6)
        assert 0.0 <= post_h <= prior_h + 1e-6
        assert not math.copysign(1.0, post_h) < 0.0
        assert mi_h == pytest.approx(prior_h - post_h, abs=2e-6)
        assert reg_c["entropy_reduction_ratio"] == pytest.approx(mi_h / prior_h, abs=2e-6)
        assert reg_c["effective_suspects"] == pytest.approx(2.0 ** post_h, abs=1e-4)

        raw_elim = sum(1 for s in raw_c["suspects"] if s["eliminated"])
        assert reg_c["eliminated_count"] == raw_elim
        assert reg_c["consistent_count"] == expected_n - raw_elim
        assert reg_c["eliminated_fraction"] == pytest.approx(raw_elim / expected_n, abs=1e-6)

        if post_h == 0.0:
            pinpoint_zero_entropy_seen += 1
            assert mi_h == pytest.approx(prior_h, abs=1e-6)
            assert reg_c["effective_suspects"] == pytest.approx(1.0, abs=1e-6)
        if reg_c["eliminated_fraction"] == 1.0:
            noisy_full_elim_seen += 1
            assert reg_c["tier"] == "hard"
            assert post_h > 3.0

    assert pinpoint_zero_entropy_seen >= 2
    assert noisy_full_elim_seen >= 1


def test_independent_env_and_solver_policy_replay_parity():
    regret_doc = json.loads(REGRET_JSON_PATH.read_text(encoding="utf-8"))
    ladder_index = outthink_regret.load_ladder_index()

    for reg_c in regret_doc["cases"]:
        cid = reg_c["id"]
        tier = reg_c["tier"]
        seed = reg_c["seed"]
        d_step = reg_c["decision_step"]
        anchor_ep = ladder_index[(reg_c["model"], reg_c["anchor_level"], tier, seed)]
        steps = [
            Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")})
            for s in anchor_ep["steps"]
        ]

        env = Env(tier, seed)
        params = tier_params_for_episode(tier, steps)
        sp = SolverPolicy(params)
        for st in steps[:d_step]:
            live_res = env.call(st.tool, st.args or {})
            assert live_res.ok is bool((st.result or {}).get("ok"))
            sp._ingest(
                Step(
                    t=st.t,
                    day=st.day,
                    tool=st.tool,
                    args=st.args,
                    result=asdict(live_res),
                )
            )
        sp.seen = d_step
        sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
        live_post = sp.belief()

        live_v = round(float(env.V), 4)
        live_prior_h = math.log2(len(env._ids))
        live_post_h = max(0.0, -sum(p * math.log2(p) for p in live_post.values() if p > 0.0))
        live_mi = max(0.0, live_prior_h - live_post_h)
        live_top = max(live_post, key=live_post.get)
        live_top_p = float(live_post[live_top])
        live_be = 1.0 / (1.0 + live_v)
        live_ev = float(accuse_value(live_top_p, live_v, params))
        live_rec = "accuse" if live_top_p >= live_be else "hold_fire"

        assert reg_c["prior_entropy_bits"] == pytest.approx(live_prior_h, abs=1e-6), cid
        assert reg_c["posterior_entropy_bits"] == pytest.approx(live_post_h, abs=1e-6), cid
        assert reg_c["mutual_information_bits"] == pytest.approx(live_mi, abs=1e-6), cid
        assert reg_c["top_suspect"] == live_top, cid
        assert reg_c["top_prob"] == pytest.approx(live_top_p, abs=1e-6), cid
        assert reg_c["true_mole_prob"] == pytest.approx(float(live_post[env._world.mole]), abs=1e-6), cid
        assert reg_c["break_even_prob"] == pytest.approx(live_be, abs=1e-6), cid
        assert reg_c["ev_accuse_top"] == pytest.approx(live_ev, abs=1e-6), cid
        assert reg_c["recommended_call"] == live_rec, cid


def test_per_thinking_level_decision_regret_and_ladder_monotonicity():
    cases_doc = json.loads(CASES_JSON_PATH.read_text(encoding="utf-8"))
    regret_doc = json.loads(REGRET_JSON_PATH.read_text(encoding="utf-8"))
    summary = regret_doc["summary"]

    total_runs = 0
    matched_runs = 0
    strict_target_regret_seen = 0

    for raw_c, reg_c in zip(cases_doc["cases"], regret_doc["cases"]):
        sol_score = reg_c["solver_final_score"]
        assert sol_score == pytest.approx(raw_c["solver"]["final_score"], abs=1e-6)
        ev_acc = reg_c["ev_accuse_top"]
        rec = reg_c["recommended_call"]

        assert len(reg_c["thinking_levels"]) == len(raw_c["thinking_levels"])
        for raw_lv, reg_lv in zip(raw_c["thinking_levels"], reg_c["thinking_levels"]):
            total_runs += 1
            assert reg_lv["thinking_level"] == raw_lv["thinking_level"]
            assert reg_lv["run_id"] == raw_lv["run_id"]
            assert reg_lv["call_at_t"] == raw_lv["call_at_t"]
            assert reg_lv["recommended_call"] == rec
            expected_match = raw_lv["call_at_t"] == rec
            assert reg_lv["matched_recommended_call"] is expected_match
            if expected_match:
                matched_runs += 1
                assert reg_lv["binary_call_regret_ev"] == 0.0
            else:
                assert reg_lv["binary_call_regret_ev"] == pytest.approx(abs(ev_acc), abs=2e-6)
                assert reg_lv["binary_call_regret_ev"] > 0.0

            assert reg_lv["decision_regret_ev"] >= reg_lv["binary_call_regret_ev"] - 1e-6
            if reg_lv["decision_regret_ev"] > reg_lv["binary_call_regret_ev"] + 1e-3:
                strict_target_regret_seen += 1

            assert reg_lv["score"] == pytest.approx(raw_lv["score"], abs=1e-6)
            assert reg_lv["score_delta_vs_solver"] == pytest.approx(raw_lv["score"] - sol_score, abs=1e-4)
            assert reg_lv["realized_regret_vs_solver"] == pytest.approx(
                max(0.0, sol_score - raw_lv["score"]), abs=1e-4
            )
            assert reg_lv["realized_regret_vs_solver"] == pytest.approx(raw_lv["regret_total"], abs=1e-4)
            assert 0.0 <= reg_lv["episode_final_entropy_bits"] <= reg_c["prior_entropy_bits"] + 1e-6

    assert total_runs == 39
    assert matched_runs == summary["matched_recommended_call_count"] == 14
    assert strict_target_regret_seen >= 1

    by_lv = summary["by_thinking_level"]
    ordered = ["minimal", "low", "medium", "high", "xhigh"]
    assert list(by_lv.keys()) == ordered
    accuracies = [by_lv[k]["accuracy"] for k in ordered]
    scores = [by_lv[k]["mean_score"] for k in ordered]
    realized_regrets = [by_lv[k]["mean_realized_regret_vs_solver"] for k in ordered]
    assert accuracies == sorted(accuracies)
    assert scores == sorted(scores)
    assert realized_regrets == sorted(realized_regrets, reverse=True)


def test_cli_out_roundtrip_and_tamper_detection(tmp_path: Path, capsys):
    out_file = tmp_path / "outthink_regret.json"

    rc_missing = outthink_regret.main(["--check", "--out", str(out_file)])
    err_missing = capsys.readouterr().err
    assert rc_missing != 0
    assert "ERROR:" in err_missing

    out_file.write_text("{not valid json", encoding="utf-8")
    rc_bad_json = outthink_regret.main(["--check", "--out", str(out_file)])
    err_bad_json = capsys.readouterr().err
    assert rc_bad_json != 0
    assert "ERROR:" in err_bad_json

    rc_write = outthink_regret.main(["--out", str(out_file)])
    out_write = capsys.readouterr().out
    assert rc_write == 0
    assert "Wrote" in out_write
    clean_text = out_file.read_text(encoding="utf-8")
    assert clean_text == REGRET_JSON_PATH.read_text(encoding="utf-8")

    rc_clean = outthink_regret.main(["--check", "--out", str(out_file)])
    out_clean = capsys.readouterr().out
    assert rc_clean == 0
    assert "OK:" in out_clean

    out_file.write_text(clean_text + "\n", encoding="utf-8")
    rc_ws_drift = outthink_regret.main(["--check", "--out", str(out_file)])
    err_ws_drift = capsys.readouterr().err
    assert rc_ws_drift != 0
    assert "out of date" in err_ws_drift

    base_payload = json.loads(clean_text)
    assert outthink_regret.validate_payload(base_payload) == []

    tampered_mi = copy.deepcopy(base_payload)
    tampered_mi["cases"][0]["mutual_information_bits"] = 0.123456
    assert any("mutual_information_bits" in e for e in outthink_regret.validate_payload(tampered_mi))
    out_file.write_text(json.dumps(tampered_mi, indent=2) + "\n", encoding="utf-8")
    assert outthink_regret.main(["--check", "--out", str(out_file)]) != 0
    capsys.readouterr()

    tampered_be = copy.deepcopy(base_payload)
    tampered_be["cases"][0]["break_even_prob"] = 0.999
    assert any("break_even_prob" in e for e in outthink_regret.validate_payload(tampered_be))

    tampered_match = copy.deepcopy(base_payload)
    tampered_match["cases"][0]["thinking_levels"][0]["matched_recommended_call"] = True
    assert any("matched_recommended_call" in e for e in outthink_regret.validate_payload(tampered_match))

    tampered_delta = copy.deepcopy(base_payload)
    tampered_delta["cases"][0]["thinking_levels"][0]["score_delta_vs_solver"] = 9.99
    assert any("score_delta_vs_solver" in e for e in outthink_regret.validate_payload(tampered_delta))

    tampered_summary = copy.deepcopy(base_payload)
    tampered_summary["summary"]["matched_recommended_call_count"] = 99
    assert any("summary" in e for e in outthink_regret.validate_payload(tampered_summary))


def test_keyless_subprocess_execution_without_api_keys():
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    clean_env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.outthink_regret", "--check"],
        cwd=ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK: 12 cases, 39 ladder runs verified." in proc.stdout


def test_strict_hygiene_no_comments_dashes_network_keys_or_protected_paths():
    self_path = Path(__file__).resolve()
    py_files = (MODULE_PATH, self_path)
    all_files = (MODULE_PATH, REGRET_JSON_PATH, self_path)

    for pf in py_files:
        src = pf.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"hash comment char in {pf}"
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT
        ]
        assert comments == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "genai" not in alias.name and "google" not in alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "genai" not in node.module and "google" not in node.module

    for fpath in all_files:
        txt = fpath.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash in {fpath}"
        assert EN_DASH not in txt, f"en dash in {fpath}"
        assert FORBIDDEN_NET not in txt, f"forbidden network call in {fpath}"

    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    checked = {f.relative_to(ROOT).as_posix() for f in all_files}
    for rel in checked:
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"protected dir touched: {rel}"
            else:
                assert rel != rule, f"protected file touched: {rel}"
