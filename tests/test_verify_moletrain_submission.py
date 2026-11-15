from __future__ import annotations

import ast
import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from canary.forge import rl_mole_v2
from canary.forge.rl_mole_v2 import RLMoleV2, warm_start_params
from train import eval_mole, qwen_diverse_mole

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_moletrain_submission.py"
TEST_PATH = Path(__file__).resolve()


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_moletrain_submission", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load_verifier()


def _init_git_repo(repo: Path, files: dict[str, str], branch: str = "justSilas") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    for rel, content in files.items():
        fp = repo / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)


def _populate_clean_tree(root: Path) -> None:
    prot = root / ".github" / "protected-paths.txt"
    prot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / ".github" / "protected-paths.txt", prot)

    for rel in V.MOLETRAIN_PY_FILES:
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("x = 1\n", encoding="utf-8")

    for rel in V.PREEXISTING_SILAS_FILES:
        fp = root / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(chr(35) + " pre-existing Silas comment\ny = 2\n", encoding="utf-8")

    mdir = root / "results" / "moletrain"
    mdir.mkdir(parents=True, exist_ok=True)
    pol = RLMoleV2(warm_start_params(hidden=6, seed=3), greedy=False)
    (mdir / "rl_mole_v2_policy.json").write_text(json.dumps(pol.to_json()), encoding="utf-8")
    shutil.copyfile(
        ROOT / "results" / "moletrain" / "rl_mole_v2_heldout.json",
        mdir / "rl_mole_v2_heldout.json",
    )


def test_source_files_have_zero_hash_emdash_coauthor_and_no_torch_import():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    co_author = "co-authored" + "-by"
    forbidden_imports = {"torch", "transformers", "peft", "trl"}

    for path in (SCRIPT_PATH, TEST_PATH):
        text = path.read_text(encoding="utf-8")
        assert hash_ch not in text
        assert em_dash not in text
        assert co_author not in text.lower()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports


def test_real_repo_passes_all_four_gates_and_reproducible_output(tmp_path):
    out1 = tmp_path / "gate1.json"
    out2 = tmp_path / "gate2.json"

    rc1 = V.main(["--root", str(ROOT), "--out", str(out1), "--check"])
    rc2 = V.main(["--root", str(ROOT), "--out", str(out2), "--check"])
    assert rc1 == 0
    assert rc2 == 0
    assert out1.read_bytes() == out2.read_bytes()
    assert out1.stat().st_size < 25 * 1024

    payload = json.loads(out1.read_text(encoding="utf-8"))
    assert payload["all_passed"] is True
    assert payload["gates_passed"] == 4
    assert payload["gates_total"] == 4

    g4 = payload["gates"]["gate_4_catchability_and_provenance"]
    assert g4["bootstrap_cis_checked"] >= 98
    assert len(g4["rl_mole_v2_replay"]) == 2
    assert all(r["reproducible"] is True for r in g4["rl_mole_v2_replay"])

    committed_gate = ROOT / "results" / "moletrain" / "submission_gate.json"
    if committed_gate.is_file():
        assert committed_gate.stat().st_size < 25 * 1024
        committed_payload = json.loads(committed_gate.read_text(encoding="utf-8"))
        assert committed_payload["all_passed"] is True


def test_gate1_protected_paths_git_diff_and_shallow_fallbacks(tmp_path):
    prot_txt = (ROOT / ".github" / "protected-paths.txt").read_text(encoding="utf-8")
    repo = tmp_path / "git_repo"
    _init_git_repo(
        repo,
        {
            ".github/protected-paths.txt": prot_txt,
            "canary/rules.py": "TIERS_VERSION = 'v1.4'\n",
            "canary/solver/core.py": "SOLVER = True\n",
            "scripts/ok.py": "OK = 1\n",
        },
        branch="justSilas",
    )
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    (repo / "scripts" / "verify_moletrain_submission.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "canary" / "forge").mkdir(parents=True, exist_ok=True)
    (repo / "canary" / "forge" / "rl_mole_v2.py").write_text("z = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "allowed changes"], cwd=repo, check=True)

    res_clean = V.check_gate1_protected_paths(repo, base_ref="origin/justSilas")
    assert res_clean["passed"] is True
    assert res_clean["mode"] == "git_diff:justSilas...HEAD"
    assert res_clean["protected_hits"] == []

    (repo / "canary" / "rules.py").write_text("TIERS_VERSION = 'v9.9'\n", encoding="utf-8")
    (repo / "canary" / "solver" / "core.py").write_text("SOLVER = False\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "touch protected"], cwd=repo, check=True)

    res_bad = V.check_gate1_protected_paths(repo, base_ref="justSilas")
    assert res_bad["passed"] is False
    assert "canary/rules.py" in res_bad["protected_hits"]
    assert "canary/solver/core.py" in res_bad["protected_hits"]

    shallow = tmp_path / "shallow_repo"
    _init_git_repo(
        shallow,
        {
            ".github/protected-paths.txt": prot_txt,
            "harbor/build.py": "H = 1\n",
        },
        branch="detached_ci",
    )
    res_shallow = V.check_gate1_protected_paths(shallow, base_ref="origin/nonexistent")
    assert res_shallow["passed"] is True
    assert res_shallow["mode"] == "fallback_working_tree"

    (shallow / "harbor" / "untracked_extra.py").write_text("U = 1\n", encoding="utf-8")
    res_shallow_untracked = V.check_gate1_protected_paths(shallow, base_ref="origin/nonexistent")
    assert res_shallow_untracked["passed"] is False
    assert "harbor/untracked_extra.py" in res_shallow_untracked["protected_hits"]
    (shallow / "harbor" / "untracked_extra.py").unlink()

    (shallow / "harbor" / "build.py").write_text("H = 2\n", encoding="utf-8")
    res_shallow_dirty = V.check_gate1_protected_paths(shallow, base_ref="origin/nonexistent")
    assert res_shallow_dirty["passed"] is False
    assert "harbor/build.py" in res_shallow_dirty["protected_hits"]

    archive_dir = tmp_path / "archive_no_git"
    (archive_dir / ".github").mkdir(parents=True)
    (archive_dir / ".github" / "protected-paths.txt").write_text(prot_txt, encoding="utf-8")
    res_archive = V.check_gate1_protected_paths(archive_dir)
    assert res_archive["passed"] is True
    assert res_archive["mode"] == "fallback_no_git"

    empty_dir = tmp_path / "missing_prot"
    empty_dir.mkdir()
    assert V.check_gate1_protected_paths(empty_dir)["passed"] is False


def test_gate2_hygiene_checks_and_silas_exemption(tmp_path):
    tree = tmp_path / "clean_hygiene"
    _populate_clean_tree(tree)
    rep_dir = tree / "docs" / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    md_heading = chr(35) + " Qwen Mole Report\n\nClean prose without forbidden punctuation.\n"
    (rep_dir / "qwen_mole_training.md").write_text(md_heading, encoding="utf-8")

    g2_ok = V.check_gate2_hygiene(tree)
    assert g2_ok["passed"] is True
    assert g2_ok["violations"] == []

    (tree / "train" / "qwen_diverse_mole.py").write_text(
        "x = 1  " + chr(35) + " inline comment\n",
        encoding="utf-8",
    )
    g2_hash = V.check_gate2_hygiene(tree)
    assert g2_hash["passed"] is False
    assert any("qwen_diverse_mole.py" in v for v in g2_hash["violations"])
    (tree / "train" / "qwen_diverse_mole.py").write_text("x = 1\n", encoding="utf-8")

    (rep_dir / "qwen_mole_training.md").write_text("Bad dash " + chr(0x2014) + " here.\n", encoding="utf-8")
    g2_em = V.check_gate2_hygiene(tree)
    assert g2_em["passed"] is False
    assert any("U+2014" in v for v in g2_em["violations"])
    (rep_dir / "qwen_mole_training.md").write_text(md_heading, encoding="utf-8")

    escaped_em = '{"note": "escaped \\u2014 dash"}\n'
    (tree / "results" / "moletrain" / "extra.json").write_text(escaped_em, encoding="utf-8")
    g2_json_em = V.check_gate2_hygiene(tree)
    assert g2_json_em["passed"] is False
    assert any("extra.json" in v for v in g2_json_em["violations"])

    co_tag = "Co-Authored" + "-By: Someone <s@example.com>"
    fake_gkey = "AI" + "za" + "SySyntheticLeakTokenValue123456"
    fake_skey = "s" + "k-proj-" + ("Z" * 24)
    (tree / "results" / "moletrain" / "extra.json").write_text(
        json.dumps({"trailer": co_tag, "k1": fake_gkey, "k2": fake_skey}),
        encoding="utf-8",
    )
    g2_sec = V.check_gate2_hygiene(tree)
    assert g2_sec["passed"] is False
    joined = "\n".join(g2_sec["violations"])
    assert "google_api_key" in joined
    assert "sk_api_key" in joined
    assert fake_gkey not in joined
    assert fake_skey not in joined

    (tree / "results" / "moletrain" / "extra.json").write_text(
        json.dumps({"blob": "a" * (105 * 1024)}),
        encoding="utf-8",
    )
    g2_big = V.check_gate2_hygiene(tree)
    assert g2_big["passed"] is False
    assert any("100 KB" in v for v in g2_big["violations"])


def test_gate3_seed_disjointness_and_drift_detection(monkeypatch, tmp_path):
    g3_ok = V.check_gate3_seed_disjointness(ROOT)
    assert g3_ok["passed"] is True
    assert g3_ok["pairwise_partition_checks"] == 21

    monkeypatch.setattr(rl_mole_v2, "TRAIN_SEEDS", range(185_000, 195_000))
    g3_v2_leak = V.check_gate3_seed_disjointness(ROOT)
    assert g3_v2_leak["passed"] is False
    assert any("rl_mole_v2.TRAIN_SEEDS" in v for v in g3_v2_leak["violations"])
    monkeypatch.undo()

    monkeypatch.setattr(eval_mole, "HELDOUT_SEED_BASE", 350_000)
    g3_em_leak = V.check_gate3_seed_disjointness(ROOT)
    assert g3_em_leak["passed"] is False
    assert any("eval_mole.HELDOUT_SEED_BASE" in v for v in g3_em_leak["violations"])
    monkeypatch.undo()

    monkeypatch.setattr(qwen_diverse_mole, "guard_train_seed", lambda s: int(s))
    g3_guard = V.check_gate3_seed_disjointness(ROOT)
    assert g3_guard["passed"] is False
    assert any("guard_train_seed" in v for v in g3_guard["violations"])
    monkeypatch.undo()

    bad_root = tmp_path / "seed_art"
    _populate_clean_tree(bad_root)
    ho_p = bad_root / "results" / "moletrain" / "rl_mole_v2_heldout.json"
    ho_obj = json.loads(ho_p.read_text(encoding="utf-8"))
    ho_obj["seed_ranges"]["ws3_heldout"] = [189_990, 200_059]
    ho_p.write_text(json.dumps(ho_obj), encoding="utf-8")
    g3_art = V.check_gate3_seed_disjointness(bad_root)
    assert g3_art["passed"] is False
    assert any("seed_ranges" in v for v in g3_art["violations"])


def test_gate4_ci_bounds_catchability_schemas_and_replay(tmp_path):
    tree = tmp_path / "gate4_ok"
    _populate_clean_tree(tree)
    mdir = tree / "results" / "moletrain"

    qwen_eval = {
        "tier": "hard",
        "seeds": "800000-800049",
        "n": 50,
        "min_solver_acc": 0.85,
        "grpo_mole": {
            "solver": {
                "score": 0.56,
                "acc": 0.92,
                "score_ci95": [0.56, 0.49, 0.63],
                "acc_ci95": [0.92, 0.84, 0.98],
            },
            "regret": {"grok_tactics": [0.24, 0.14, 0.34]},
            "min_regret": 0.24,
            "catchable": True,
            "catchable_85": True,
        },
        "rl_mole": {
            "solver": {
                "score": 0.34,
                "acc": 0.75,
                "score_ci95": [0.34, 0.23, 0.45],
                "acc_ci95": [0.75, 0.62, 0.86],
            },
            "catchable": False,
        },
        "adapter_result": {
            "reward": {"mean": 0.21, "ci95": [0.12, 0.30], "n": 50},
            "solver_catch": {"mean": 0.90, "ci95": [0.82, 0.98], "n": 50},
        },
    }
    (mdir / "qwen_grpo_eval.json").write_text(json.dumps(qwen_eval), encoding="utf-8")

    g4_ok = V.check_gate4_catchability_and_provenance(tree)
    assert g4_ok["passed"] is True
    assert g4_ok["bootstrap_cis_checked"] > 100
    assert len(g4_ok["rl_mole_v2_replay"]) == 2

    bad_ci = copy.deepcopy(qwen_eval)
    bad_ci["grpo_mole"]["solver"]["score_ci95"] = [0.20, 0.49, 0.63]
    (mdir / "qwen_grpo_eval.json").write_text(json.dumps(bad_ci), encoding="utf-8")
    g4_bad_ci = V.check_gate4_catchability_and_provenance(tree)
    assert g4_bad_ci["passed"] is False
    assert any("lo <= mean <= hi" in v for v in g4_bad_ci["violations"])

    bad_ci2 = copy.deepcopy(qwen_eval)
    bad_ci2["adapter_result"]["reward"] = {"mean": 0.50, "ci95": [0.12, 0.30], "n": 50}
    (mdir / "qwen_grpo_eval.json").write_text(json.dumps(bad_ci2), encoding="utf-8")
    g4_bad_ci2 = V.check_gate4_catchability_and_provenance(tree)
    assert g4_bad_ci2["passed"] is False
    assert any("reward.ci95" in v for v in g4_bad_ci2["violations"])

    uncatch = copy.deepcopy(qwen_eval)
    uncatch["grpo_mole"]["solver"]["acc"] = 0.78
    uncatch["grpo_mole"]["solver"]["acc_ci95"] = [0.78, 0.66, 0.88]
    uncatch["grpo_mole"]["catchable_85"] = False
    (mdir / "qwen_grpo_eval.json").write_text(json.dumps(uncatch), encoding="utf-8")
    g4_uncatch = V.check_gate4_catchability_and_provenance(tree)
    assert g4_uncatch["passed"] is False
    assert any("grpo_mole" in v for v in g4_uncatch["violations"])

    untruth = copy.deepcopy(qwen_eval)
    untruth["rl_mole"]["catchable_85"] = True
    (mdir / "qwen_grpo_eval.json").write_text(json.dumps(untruth), encoding="utf-8")
    g4_untruth = V.check_gate4_catchability_and_provenance(tree)
    assert g4_untruth["passed"] is False
    assert any("rl_mole" in v for v in g4_untruth["violations"])

    (mdir / "qwen_grpo_eval.json").write_text(json.dumps(qwen_eval), encoding="utf-8")
    (mdir / "rl_mole_v2_policy.json").write_text('{"kind": "broken"}\n', encoding="utf-8")
    g4_bad_pol = V.check_gate4_catchability_and_provenance(tree)
    assert g4_bad_pol["passed"] is False
    assert any("RLMoleV2.from_json" in v for v in g4_bad_pol["violations"])


def test_cli_check_exit_codes(tmp_path):
    bad_tree = tmp_path / "cli_bad"
    _populate_clean_tree(bad_tree)
    (bad_tree / "canary" / "forge" / "rl_mole_v2.py").write_text(
        chr(35) + " forbidden comment\n",
        encoding="utf-8",
    )
    out_gate = bad_tree / "results" / "moletrain" / "submission_gate.json"

    rc_no_check = V.main(["--root", str(bad_tree), "--out", str(out_gate)])
    assert rc_no_check == 0
    saved = json.loads(out_gate.read_text(encoding="utf-8"))
    assert saved["all_passed"] is False

    rc_check = V.main(["--root", str(bad_tree), "--out", str(out_gate), "--check"])
    assert rc_check == 1
