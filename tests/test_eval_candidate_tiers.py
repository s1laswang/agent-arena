"""Offline unit, mutation, and hygiene tests for scripts/eval_candidate_tiers.py."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import math
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

SCRIPT_PATH = ROOT / "scripts/eval_candidate_tiers.py"
JSON_PATH = ROOT / "results/eval_v14/candidate_tiers_v14.json"
MD_PATH = ROOT / "docs/reports/candidate_tiers_v14.md"
THIS_TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
CO_AUTHORED_TAG = "Co-" + "Authored-" + "By"

SECRET_AND_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("provider_token", re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
)


def _load_module():
    spec = importlib.util.spec_from_file_location("eval_candidate_tiers", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ect = _load_module()


@pytest.fixture(scope="module")
def computed_data() -> dict[str, Any]:
    assert JSON_PATH.is_file(), f"missing {JSON_PATH}"
    assert MD_PATH.is_file(), f"missing {MD_PATH}"
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_hygiene_zero_hash_comments_and_dashes() -> None:
    for py_path in (SCRIPT_PATH, THIS_TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"found literal hash character in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"found comment tokens in {py_path}: {comment_tokens}"

    for owned_path in (SCRIPT_PATH, JSON_PATH, MD_PATH, THIS_TEST_PATH):
        assert owned_path.is_file(), f"missing owned file: {owned_path}"
        txt = owned_path.read_text(encoding="utf-8")
        assert all(ord(ch) < 128 for ch in txt), f"non-ASCII char in {owned_path}"
        assert EN_DASH not in txt, f"found en-dash in {owned_path}"
        assert EM_DASH not in txt, f"found em-dash in {owned_path}"
        assert CO_AUTHORED_TAG not in txt, f"found trailer tag in {owned_path}"
        for pat_name, rx in SECRET_AND_LEAK_PATTERNS:
            if owned_path == THIS_TEST_PATH and pat_name == "world_mole_dump":
                continue
            assert not rx.search(txt), f"matched {pat_name} in {owned_path}"


def test_json_artifact_size_schema_and_live_fast_gates(computed_data: dict[str, Any]) -> None:
    raw = JSON_PATH.read_bytes()
    assert 0 < len(raw) < 60 * 1024
    on_disk = json.loads(raw.decode("utf-8"))
    assert on_disk["schema_version"] == "candidate_tiers_v14.v1"
    assert on_disk["tiers_version"] == "v1.4"
    assert on_disk["overall_passed"] is True
    assert len(on_disk["gates"]) == 3
    assert all(g["passed"] and g["violation_count"] == 0 for g in on_disk["gates"])
    assert ect.render_md(on_disk) + "\n" == MD_PATH.read_text(encoding="utf-8")

    live_harbor = ect.verify_harbor_rehearsal_gate(ROOT)
    assert live_harbor["passed"] is True and live_harbor["violations"] == []
    live_harbor_clean = ect.clean_json_value(
        {k: v for k, v in live_harbor.items() if k not in {"passed", "violations"}}
    )
    assert ect.approx_equal(on_disk["harbor_rehearsal"], live_harbor_clean, tol=1e-9)

    live_tracks = ect.verify_dropped_candidates_and_negative_gates(ROOT)
    assert live_tracks["passed"] is True and live_tracks["violations"] == []
    live_tracks_clean = ect.clean_json_value(
        {k: v for k, v in live_tracks.items() if k not in {"passed", "violations"}}
    )
    assert ect.approx_equal(on_disk["dropped_candidates_and_gates"], live_tracks_clean, tol=1e-9)

    v14_dir = ROOT / "data/runs/committed/v1.4"
    gpt_dir = v14_dir / "opencode-gpt-5.5/hard"
    gem_dir = v14_dir / "opencode-gemini-4-carbon/hard"
    sol_path = v14_dir / "reference/solver-hard-20261114-121126/episodes.jsonl"
    assert ect._check_gpt55_transcript_text_accuse(gpt_dir / "transcripts/0.txt") is True
    assert ect._check_gpt55_transcript_text_accuse(gpt_dir / "transcripts/1.txt") is False

    gpt_eps = ect._load_valid_episodes([gpt_dir / "episodes.jsonl"], "opencode:openai/gpt-5.5")
    gem_eps = ect._load_valid_episodes([gem_dir / "episodes.jsonl"], "opencode:google/gemini-4-carbon")
    sol_eps = ect._load_valid_episodes([sol_path], "solver")
    sol_slice = [ect._replay_and_audit_episode(sol_eps[s]) for s in (0, 1)]
    gpt_slice = [ect._replay_and_audit_episode(gpt_eps[s]) for s in (0, 1)]
    gem_slice = [ect._replay_and_audit_episode(gem_eps[s]) for s in (0, 1)]
    gpt_sum = ect._summarize_cohort("gpt-5.5 slice", "opencode:openai/gpt-5.5", gpt_slice, sol_slice)
    gem_sum = ect._summarize_cohort("carbon slice", "opencode:google/gemini-4-carbon", gem_slice, sol_slice)
    assert gpt_sum["outcomes"]["no_accusation_seeds"] == [0]
    assert gpt_sum["outcomes"]["wrong"] == 0
    assert gem_sum["outcomes"]["wrong_seeds"] == [1]


def test_cli_check_passes_fast(
    computed_data: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ect, "compute", lambda _root=ROOT: copy.deepcopy(computed_data))
    t0 = time.perf_counter()
    rc = ect.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 3.0


def test_cli_check_detects_json_and_markdown_drift(
    computed_data: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ect, "compute", lambda _root=ROOT: copy.deepcopy(computed_data))
    tmp_json = tmp_path / "out.json"
    tmp_md = tmp_path / "out.md"
    shutil.copyfile(JSON_PATH, tmp_json)
    shutil.copyfile(MD_PATH, tmp_md)

    assert ect.main(["--check", "--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 0

    tiny_obj = json.loads(tmp_json.read_text(encoding="utf-8"))
    tiny_obj["harbor_rehearsal"]["oracle_10task_mean"] += 1e-12
    tmp_json.write_text(json.dumps(tiny_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert ect.main(["--check", "--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 0

    bad_obj = json.loads(tmp_json.read_text(encoding="utf-8"))
    bad_obj["harbor_rehearsal"]["oracle_10task_mean"] += 1e-5
    tmp_json.write_text(json.dumps(bad_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert ect.main(["--check", "--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 1

    shutil.copyfile(JSON_PATH, tmp_json)
    tmp_md.write_text(tmp_md.read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8")
    assert ect.main(["--check", "--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 1


def test_harbor_rehearsal_build_and_10task_table_arithmetic(computed_data: dict[str, Any]) -> None:
    hr = computed_data["harbor_rehearsal"]
    build = hr["build"]
    assert build["sha_short"] == "1bc3e281"
    assert build["describe"] == "afterquery-final"
    assert build["harbor_version"] == "0.26.0"
    assert build["logged_verifier_timeout_sec"] == 120.0
    assert build["effective_agent_timeout_sec"] == 10800.0
    assert hr["task_count"] == 10
    assert math.isclose(hr["oracle_10task_mean"], 0.506, abs_tol=1e-9)
    assert hr["oracle_correct_count"] == 9

    by_run = {r["run"]: r for r in hr["summary_rows"]}
    assert by_run["opencode-1"]["n_valid"] == 10
    assert math.isclose(by_run["opencode-1"]["mean"], 0.472, abs_tol=1e-9)
    assert by_run["opencode-1"]["ratio_formatted"] == "93% [20%, 371%]"

    assert by_run["opencode-2"]["n_valid"] == 10
    assert math.isclose(by_run["opencode-2"]["mean"], 0.585, abs_tol=1e-9)
    assert by_run["opencode-2"]["ratio_formatted"] == "116% [78%, 363%]"

    assert by_run["opencode-3"]["n_valid"] == 7
    assert by_run["opencode-3"]["n_infra_excluded"] == 1
    assert by_run["opencode-3"]["n_not_run"] == 2
    assert math.isclose(by_run["opencode-3"]["mean"], 4.59 / 7.0, abs_tol=1e-9)
    assert math.isclose(by_run["opencode-3"]["oracle_same_tasks"], 3.00 / 7.0, abs_tol=1e-9)
    assert by_run["opencode-3"]["ratio_formatted"] == "153% [89%, 411%]"
    assert math.isclose(by_run["opencode-3"]["mean_infra_as_0"], 4.59 / 8.0, abs_tol=1e-9)

    for zero_run in ("do_nothing", "stop_early"):
        assert by_run[zero_run]["n_valid"] == 10
        assert by_run[zero_run]["mean"] == 0.0
        assert by_run[zero_run]["ratio_formatted"] == "0% [0%, 0%]"

    sp = hr["opencode_spread"]
    assert sp["n_opencode_runs"] == 3
    assert sp["pooled_valid_correct"] == 26
    assert sp["pooled_valid_accused"] == 27
    assert f"{sp['mean_of_means']:+.3f}" == "+0.571"
    assert f"{sp['sample_sd']:.3f}" == "0.093"
    assert f"{sp['range']:.3f}" == "0.184"

    r3f = hr["opencode_3_final"]
    assert r3f["correction_commit"] == "aa1c679e"
    assert r3f["trial_archive_branch"] == "s1-rehearsal-final"
    assert r3f["trial_archive_commit"] == "d0ead011"
    assert r3f["n_valid"] == 9
    assert r3f["n_after_0830_cutoff"] == 5
    assert r3f["n_infra_excluded"] == 1
    assert math.isclose(r3f["mean"], 0.626, abs_tol=1e-9)
    assert r3f["ratio_formatted"] == "131% [86%, 590%]"

    spf = hr["opencode_final_spread"]
    assert spf["n_opencode_runs"] == 3
    assert spf["pooled_valid_correct"] == 28
    assert spf["pooled_valid_accused"] == 29
    assert f"{spf['mean_of_means']:+.3f}" == "+0.561"
    assert f"{spf['sample_sd']:.3f}" == "0.080"
    assert f"{spf['range']:.3f}" == "0.154"
    assert all(hr["honest_non_reproduction_disclosed"].values())


def test_harbor_rehearsal_tamper_detection(tmp_path: Path) -> None:
    (tmp_path / "results/harbor/rehearsal").mkdir(parents=True)
    (tmp_path / "docs/reports").mkdir(parents=True)
    shutil.copyfile(ROOT / "results/harbor/rehearsal/BUILD.txt", tmp_path / "results/harbor/rehearsal/BUILD.txt")
    tampered_table = (ROOT / "results/harbor/rehearsal/TABLE.md").read_text(encoding="utf-8").replace(
        "93% [20%, 371%]", "65% [20%, 98%]"
    )
    (tmp_path / "results/harbor/rehearsal/TABLE.md").write_text(tampered_table, encoding="utf-8")
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    shutil.copyfile(ROOT / "docs/SUBMISSION.md", tmp_path / "docs/SUBMISSION.md")
    shutil.copyfile(ROOT / "docs/reports/gap.md", tmp_path / "docs/reports/gap.md")
    shutil.copyfile(ROOT / "docs/reports/CEO.md", tmp_path / "docs/reports/CEO.md")

    res = ect.verify_harbor_rehearsal_gate(tmp_path)
    assert res["passed"] is False
    assert any("opencode-1: ratio_ci" in v for v in res["violations"])


def test_gpt55_parity_and_behaviour_cross_check(computed_data: dict[str, Any]) -> None:
    gp = computed_data["gpt55_parity_and_behaviour"]
    assert gp["episodes_replayed"] == 90
    assert gp["behaviour_compare_table_exact_match"] is True

    pre = gp["gpt_5_5_preregistration"]
    assert pre["commit_prefix"] == "cf394894"
    assert pre["opencode_version"] == "1.19.5"
    assert math.isclose(pre["cost_usd_est"], 38.908, abs_tol=1e-6)
    assert pre["transcript_files_verified"] == 30
    assert pre["text_only_accusation_seeds"] == [0, 17]
    assert pre["text_only_accusation_verified"] is True

    c_sol = gp["cohorts"]["solver"]
    c_gpt = gp["cohorts"]["gpt_5_5"]
    c_gem = gp["cohorts"]["gemini_4_carbon"]

    assert f"{c_gpt['mean']:+.3f}" == "+0.504"
    assert f"{c_gpt['ci95']:.3f}" == "0.064"
    assert f"{c_sol['mean']:+.3f}" == "+0.499"
    assert f"{c_gpt['raw_ratio']:.0%}" == "101%"
    assert f"{c_gpt['luck_adj_ratio']:.0%}" == "84%"
    assert f"{c_gpt['canaries_mean']:.1f}" == "17.2"
    assert f"{c_gpt['interviews_mean']:.1f}" == "4.2"
    assert f"{c_gpt['interview_share']:.0%}" == "6%"
    assert c_gpt["outcomes"]["formatted"] == "28 / 0 / 2"

    assert f"{c_gem['mean']:+.3f}" == "+0.322"
    assert f"{c_gem['canaries_mean']:.1f}" == "8.5"
    assert f"{c_gem['interviews_mean']:.1f}" == "68.0"
    assert f"{c_gem['interview_share']:.0%}" == "53%"
    assert c_gem["outcomes"]["formatted"] == "25 / 4 / 1"
    assert c_gem["detail_stripped_calls"] == 28
    assert c_gem["tool_calls_total"] == 3841


def test_dropped_candidate_tracks_and_ws4_negative_gates(computed_data: dict[str, Any]) -> None:
    dc = computed_data["dropped_candidates_and_gates"]
    fenv = dc["frozen_judged_env"]
    assert fenv["tiers_version"] == "v1.4"
    assert fenv["tier_hash"] == "a8f99c2537c91d72"
    assert fenv["shipped_tiers"] == ["easy", "hard", "medium"]

    tracks = dc["tracks"]
    v15 = tracks["v1_5_candidate_social_layer"]
    assert v15["status"] == "dropped_at_gate_b"
    assert v15["v14_raw_ratio"] == 0.61
    assert v15["v15_raw_ratio"] == 1.08
    assert v15["ship_criterion_met"] is False

    exp = tracks["expert_070_fingerprint_tier"]
    assert exp["status"] == "dropped_at_ceo_gap_gate"
    assert exp["fingerprint_accuracy"] == 0.70
    assert exp["carbon_opencode_n"] == 13
    assert exp["carbon_luck_adj_ratio"] == 0.84
    assert exp["carbon_luck_adj_ci95"] == [0.52, 1.28]
    assert exp["ship_criterion_met"] is False

    sv2 = tracks["solver_v2_reference_candidate"]
    assert sv2["fresh_eval_seeds"] == "9000-9399"
    assert sv2["n_per_tier"] == 400
    assert sv2["hard_paired_delta"] == 0.012
    assert sv2["hard_paired_delta"] < sv2["ship_bar_hard_delta"]
    assert sv2["medium_paired_delta"] == 0.019
    assert sv2["gpt55_habit_reparam_fresh_9000_9399"] == 0.496
    assert sv2["ship_criterion_met"] is False

    ws4 = tracks["ws4_small_model_tiebreaker"]
    assert ws4["status"] == "bar_not_met_honestly_disclosed"
    assert ws4["trained_runs_count"] == 7
    assert ws4["all_trained_below_base"] is True
    assert ws4["best_trained_mean"] == -0.050
    assert ws4["dagger_round1"]["mean"] == -0.542
    assert ws4["dagger_round1"]["n"] == 50
    assert ws4["verda_measured_spend_eur"] == 104.46
    assert ws4["verda_instances_deleted"] == 9
    assert ws4["ship_criterion_met"] is False


def test_negative_gate_doc_tamper_detection(tmp_path: Path) -> None:
    (tmp_path / "docs/reports").mkdir(parents=True)
    for rel in (
        "README.md",
        "VERDA.md",
        "docs/SUBMISSION.md",
        "docs/DIFFICULTY.md",
        "docs/reports/gap.md",
        "docs/reports/reference_optimality.md",
        "docs/reports/CEO.md",
    ):
        shutil.copyfile(ROOT / rel, tmp_path / rel)

    bad_readme = (tmp_path / "README.md").read_text(encoding="utf-8").replace(
        "seven trained runs, none above the base", "trained model beat base"
    )
    (tmp_path / "README.md").write_text(bad_readme, encoding="utf-8")
    res = ect.verify_dropped_candidates_and_negative_gates(tmp_path)
    assert res["passed"] is False
    assert any("seven trained runs" in v for v in res["violations"])


def test_auto_discovered_by_run_all_eval_checks() -> None:
    from scripts import run_all_eval_checks as raec

    _, optional_items = raec.discover_verifiers(ROOT)
    by_name = {item["name"]: item for item in optional_items}
    assert "eval_candidate_tiers" in by_name
    assert by_name["eval_candidate_tiers"]["present"] is True
    assert by_name["eval_candidate_tiers"]["script"] == "scripts/eval_candidate_tiers.py"
