from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import pytest

_PRELOADED_HEAVY = {m for m in ("torch", "transformers") if m in sys.modules}

import scripts.verify_tiebreak_submission as gate

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = REPO_ROOT / "scripts" / "verify_tiebreak_submission.py"
SELF_PATH = Path(__file__).resolve()

SURFACE_REL_FILES: tuple[str, ...] = (
    ".github/protected-paths.txt",
    "docs/reports/tiebreak_small_model.md",
    "train/compact_render.py",
    "train/eval_compact_hf.py",
    "train/empirical_bayes_policy.py",
    "scripts/tiebreak_scaling_calibration.py",
    "scripts/verify_tiebreak_submission.py",
)


def _link_or_copy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> str:
    dst_p = Path(dst)
    if dst_p.exists():
        dst_p.unlink()
    try:
        os.link(src, dst)
        return str(dst)
    except OSError:
        return str(shutil.copy2(src, dst))


def _write_text_unlinked(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    path.write_text(text, encoding="utf-8")


def _write_bytes_unlinked(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    path.write_bytes(data)


@pytest.fixture(scope="module")
def base_surface(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base_root = tmp_path_factory.mktemp("tiebreak_surface_base")
    for rel in SURFACE_REL_FILES:
        src = REPO_ROOT / rel
        target = base_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    shutil.copytree(REPO_ROOT / "results" / "tiebreak", base_root / "results" / "tiebreak")
    return base_root


@pytest.fixture(scope="module")
def mini_valid_surface(tmp_path_factory: pytest.TempPathFactory) -> Path:
    mini = tmp_path_factory.mktemp("tiebreak_mini_valid")
    prot_dst = mini / ".github" / "protected-paths.txt"
    prot_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / ".github" / "protected-paths.txt", prot_dst)

    stub_policies = {
        "train/compact_render.py": "CompactStubPolicy",
        "train/empirical_bayes_policy.py": "EmpiricalBayesStubPolicy",
        "scripts/tiebreak_scaling_calibration.py": "ScalingStubPolicy",
    }
    for rel_mod, cls_name in stub_policies.items():
        _write_text_unlinked(
            mini / rel_mod,
            f"class {cls_name}:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ready = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n",
        )
    _write_text_unlinked(
        mini / "train" / "eval_compact_hf.py",
        "def run_compact_eval():\n    return {}\n",
    )

    secret_tag = "sha256:0123456789abcdef"
    mini_summary = {
        "run_id": "mini-verified-v14",
        "train_seeds": {"start": 100000, "stop": 100030},
        "eval_seeds": {"start": 800000, "stop": 800030},
        "n": 30,
        "replay_verified": True,
        "invalid_episodes": 0,
        "before": {
            "mean_score": 0.0,
            "valid_call_rate": 1.0,
            "world_secret_tag": secret_tag,
            "invalid_episodes": 0,
        },
        "after": {
            "mean_score": 0.6,
            "valid_call_rate": 1.0,
            "world_secret_tag": secret_tag,
            "invalid_episodes": 0,
        },
        "paired": {
            "mean_delta": 0.6,
            "ci95_low": 0.6,
            "ci95_high": 0.6,
            "deltas": [0.6] * 30,
        },
    }
    _write_text_unlinked(
        mini / "results" / "tiebreak" / "mini_verified" / "summary.json",
        json.dumps(mini_summary, indent=2) + "\n",
    )
    _write_text_unlinked(
        mini / "results" / "tiebreak" / "mini_verified" / "table.md",
        "| Metric | Before | After | Delta | CI95 Low |\n"
        "|---|---:|---:|---:|---:|\n"
        "| score | 0.0000 | 0.6000 | +0.6000 | +0.6000 |\n",
    )

    mini_ledger = {
        "summary_counts": {
            "historical_runs": 0,
            "discovered_runs": 1,
            "verified_improvements": 1,
            "verified_run_ids": ["mini-verified-v14"],
        },
        "calibrated_v14_dataset": {},
        "historical_runs": [],
        "discovered_runs": [
            {
                "run_id": "mini-verified-v14",
                "status": "VERIFIED_IMPROVEMENT",
                "verified_improvement": True,
                "heldout_n": 30,
                "before_mean_score": 0.0,
                "after_mean_score": 0.6,
                "paired_mean_delta": 0.6,
                "paired_ci95_low": 0.6,
                "paired_ci95_high": 0.6,
                "before_valid_call_rate": 1.0,
                "after_valid_call_rate": 1.0,
                "before_world_secret_tag": secret_tag,
                "after_world_secret_tag": secret_tag,
                "replay_verified": True,
                "summary_path": "results/tiebreak/mini_verified/summary.json",
                "gates": {
                    "gate1_seed_hygiene": True,
                    "gate2_paired_world_secret": True,
                    "gate3_sample_and_replay": True,
                    "gate4_paired_ci95_positive": True,
                    "all_passed": True,
                },
            }
        ],
    }
    _write_text_unlinked(
        mini / "results" / "tiebreak" / "experiment_ledger.json",
        json.dumps(mini_ledger, indent=2) + "\n",
    )
    _write_text_unlinked(
        mini / "docs" / "reports" / "tiebreak_small_model.md",
        "Tiebreak Small Model Report\n"
        "===========================\n\n"
        "- Historical runs logged: `0`\n"
        "- Dynamically discovered squad runs: `1`\n"
        "- Verified improvements passing all 4 strict gates: `1`\n\n"
        "| Split | Tier | Nat | Corr | NatAbs | AugAbs | Rej | SFT | DPO | TopAcc | TopAbs |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n\n"
        "| Run ID | Model | Seeds | Held-out n | Score | Valid Call | Secret | Status |\n"
        "|---|---|---|---:|---|---|---|---|\n"
        f"| mini-verified-v14 | stub | 800000..800029 | 30 | 0.000 -> 0.600 (delta +0.600 [+0.600, +0.600]) | 1.00 -> 1.00 | {secret_tag} | VERIFIED_IMPROVEMENT |\n",
    )
    return mini


def _clone_tiebreak_surface(dst_root: Path, src_root: Path) -> Path:
    shutil.copytree(src_root, dst_root, copy_function=_link_or_copy, dirs_exist_ok=True)
    return dst_root


def _clone_provenance_tamper_surface(dst_root: Path, base_root: Path) -> Path:
    ledger_src = base_root / "results" / "tiebreak" / "experiment_ledger.json"
    ledger_dst = dst_root / "results" / "tiebreak" / "experiment_ledger.json"
    ledger_dst.parent.mkdir(parents=True, exist_ok=True)
    _link_or_copy(ledger_src, ledger_dst)

    ledger_data = json.loads(ledger_src.read_text(encoding="utf-8"))
    runs = list(ledger_data.get("historical_runs") or []) + list(ledger_data.get("discovered_runs") or [])
    needed_rels = {"results/tiebreak/empirical_bayes/summary.json"}
    for entry in runs:
        if isinstance(entry, dict) and (
            entry.get("status") == "VERIFIED_IMPROVEMENT" or entry.get("verified_improvement") is True
        ):
            s_rel = entry.get("summary_path")
            if isinstance(s_rel, str) and s_rel.strip():
                needed_rels.add(s_rel.strip())

    for rel in sorted(needed_rels):
        s_src = base_root / rel
        if s_src.is_file():
            s_dst = dst_root / rel
            s_dst.parent.mkdir(parents=True, exist_ok=True)
            _link_or_copy(s_src, s_dst)
    return dst_root


def test_verifier_and_test_source_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    for path in (VERIFIER_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - _PRELOADED_HEAVY) == set()


def test_live_repo_passes_all_checks_and_cli(
    capsys: pytest.CaptureFixture[str],
    mini_valid_surface: Path,
) -> None:
    t0 = time.perf_counter()
    report = gate.run_all_checks(root=REPO_ROOT, strict=True)
    elapsed = time.perf_counter() - t0

    assert report["passed"] is True
    assert report["checks_passed"] == 5
    assert report["checks_total"] == 5
    assert elapsed < 15.0
    for name in gate.CHECK_NAMES:
        assert report["checks"][name]["passed"] is True
        assert report["checks"][name]["errors"] == []
    assert "TIEBREAK SUBMISSION GATE [STRICT]: PASS" in gate.format_human_report(report)

    rc_std = gate.main(["--root", str(mini_valid_surface)])
    assert rc_std == 0
    human_out = capsys.readouterr().out
    assert "TIEBREAK SUBMISSION GATE [STANDARD]: PASS" in human_out

    rc_json = gate.main(["--root", str(mini_valid_surface), "--json", "--strict"])
    assert rc_json == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["passed"] is True
    assert parsed["strict"] is True
    assert set(parsed["checks"].keys()) == set(gate.CHECK_NAMES)


def test_check1_protected_and_frozen_paths_rejections(
    tmp_path: Path,
    mini_valid_surface: Path,
) -> None:
    syn = _clone_tiebreak_surface(tmp_path, mini_valid_surface)

    clean_paths = [
        "docs/reports/tiebreak_small_model.md",
        "results/tiebreak/experiment_ledger.json",
        "scripts/verify_tiebreak_submission.py",
        "tests/test_verify_tiebreak_submission.py",
        "train/empirical_bayes_policy.py",
    ]
    ok_res = gate.check_protected_and_frozen_paths(root=syn, changed_paths=clean_paths, strict=True)
    assert ok_res.passed is True

    bad_protected = [
        "canary/env.py",
        "canary/rules.py",
        "canary/solver/policy.py",
        "harbor/build.py",
        "Makefile",
        "configs/tiers.yaml",
        "data/runs/committed/v1.4/episodes.jsonl",
        "results/judge_table.md",
        ".github/protected-paths.txt",
        ".github/workflows/guard.yml",
    ]
    for bad in bad_protected:
        res = gate.check_protected_and_frozen_paths(root=syn, changed_paths=[*clean_paths, bad])
        assert res.passed is False, f"expected protected rejection for {bad}"
        assert any("protected path touched" in e for e in res.errors)

    bad_frozen = [
        "README.md",
        "docs/SUBMISSION.md",
        "docs/reports/fr8.md",
        "docs/reports/gap.md",
        "docs/gemini/SUBMISSION.md",
    ]
    for bad in bad_frozen:
        res = gate.check_protected_and_frozen_paths(root=syn, changed_paths=[*clean_paths, bad])
        assert res.passed is False, f"expected frozen Silas doc rejection for {bad}"
        assert any("frozen Silas doc touched" in e for e in res.errors)


def test_check1_git_diff_against_base_branch_and_dirty_tree(
    tmp_path: Path,
    mini_valid_surface: Path,
) -> None:
    repo = tmp_path / "mini_repo"
    _clone_tiebreak_surface(repo, mini_valid_surface)
    _write_text_unlinked(repo / "README.md", "Silas baseline\n")
    _write_text_unlinked(repo / "results" / "judge_episodes.jsonl", "{\"seed\": 900000}\n")
    _write_text_unlinked(repo / "canary" / "env.py", "ENV_BASELINE = 1\n")

    git_env = {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["git", "init", "-b", "justSilas"], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, env=git_env, check=True, capture_output=True)

    subprocess.run(["git", "checkout", "-b", "tiebreak-test"], cwd=repo, env=git_env, check=True, capture_output=True)
    _write_text_unlinked(repo / "results" / "tiebreak" / "note.txt", "allowed\n")
    subprocess.run(["git", "add", "."], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "tiebreak ok"], cwd=repo, env=git_env, check=True, capture_output=True)

    ok_res = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas")
    assert ok_res.passed is True

    _write_text_unlinked(repo / "README.md", "unauthorized dirty edit\n")
    dirty_res = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas")
    assert dirty_res.passed is False
    assert any("README.md" in e for e in dirty_res.errors)

    subprocess.run(["git", "checkout", "--", "README.md"], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "fr8/canary/main", "justSilas"],
        cwd=repo,
        env=git_env,
        check=True,
        capture_output=True,
    )
    for rel_doc in ("docs/DEMO.md", "docs/EXPLOITS.md", "docs/SUBMISSION.md"):
        _write_text_unlinked(repo / rel_doc, "craft update\n")
    subprocess.run(["git", "add", "."], cwd=repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "craft docs"], cwd=repo, env=git_env, check=True, capture_output=True)

    unified_ok = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas", strict=True)
    assert unified_ok.passed is True

    _write_text_unlinked(repo / "results" / "judge_episodes.jsonl", "{}\n")
    judge_fail = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas", strict=True)
    assert judge_fail.passed is False
    assert any("results/judge_episodes.jsonl" in e for e in judge_fail.errors)
    subprocess.run(["git", "checkout", "--", "results/judge_episodes.jsonl"], cwd=repo, env=git_env, check=True, capture_output=True)

    _write_text_unlinked(repo / "canary" / "env.py", "tamper\n")
    prot_fail = gate.check_protected_and_frozen_paths(root=repo, base_ref="justSilas", strict=True)
    assert prot_fail.passed is False
    assert any("canary/env.py" in e for e in prot_fail.errors)

    ci_repo = tmp_path / "shallow_ci_repo"
    _clone_tiebreak_surface(ci_repo, mini_valid_surface)
    subprocess.run(["git", "init", "-b", "pr-merge"], cwd=ci_repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=ci_repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "shallow merge commit"], cwd=ci_repo, env=git_env, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "--detach", "HEAD"], cwd=ci_repo, env=git_env, check=True, capture_output=True)
    ci_report = gate.run_all_checks(root=ci_repo, strict=True)
    assert ci_report["passed"] is True
    assert ci_report["checks"]["protected_and_frozen_paths"]["passed"] is True


def test_check2_ast_inference_isolation_optional_pass_and_leak_rejections(
    tmp_path: Path,
    mini_valid_surface: Path,
) -> None:
    syn = _clone_tiebreak_surface(tmp_path, mini_valid_surface)

    clean_optional = syn / "train" / "neural_mlp_tiebreak.py"
    _write_text_unlinked(
        clean_optional,
        "class TinyMLPPolicy:\n"
        "    def reset(self, tools_spec, instruction):\n"
        "        self.ready = True\n"
        "    def belief(self):\n"
        "        return {'e00': 0.5}\n"
        "    def act(self, history):\n"
        "        _ = self.belief()\n"
        "        return ('status', {})\n",
    )
    ok_res = gate.check_ast_inference_isolation(root=syn, strict=True)
    assert ok_res.passed is True
    assert "train/neural_mlp_tiebreak.py:TinyMLPPolicy" in ok_res.metrics["policy_classes_checked"]
    assert "train/compact_dagger_ablation.py" in gate.OPTIONAL_INFERENCE_MODULES
    assert "train/qwen15b_dpo_dagger.py" in gate.OPTIONAL_INFERENCE_MODULES

    clean_ablation = syn / "train" / "compact_dagger_ablation.py"
    _write_text_unlinked(
        clean_ablation,
        "class CompactLinearDAggerPolicy:\n"
        "    def reset(self, tools_spec, instruction):\n"
        "        self.ready = True\n"
        "    def act(self, history):\n"
        "        return ('status', {})\n",
    )
    clean_dpo = syn / "train" / "qwen15b_dpo_dagger.py"
    _write_text_unlinked(
        clean_dpo,
        "from canary.solver.policy import SolverPolicy\n"
        "def relabel_train_step(sp):\n"
        "    return sp.belief()\n"
        "class Qwen15BDpoPolicy:\n"
        "    def reset(self, tools_spec, instruction):\n"
        "        self.ready = True\n"
        "    def act(self, history):\n"
        "        return ('status', {})\n",
    )
    reg_res = gate.check_ast_inference_isolation(root=syn, strict=True)
    assert reg_res.passed is True
    assert "train/compact_dagger_ablation.py:CompactLinearDAggerPolicy" in reg_res.metrics["policy_classes_checked"]
    assert "train/qwen15b_dpo_dagger.py:Qwen15BDpoPolicy" in reg_res.metrics["policy_classes_checked"]
    clean_ablation.unlink()
    clean_dpo.unlink()

    leak_snippets = [
        (
            "world_import_in_act",
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        from canary.world import generate_world\n"
            "        return ('status', {})\n",
        ),
        (
            "solver_act_in_helper",
            "from canary.solver.policy import SolverPolicy\n"
            "def _cheat_step(h):\n"
            "    return SolverPolicy().act(h)\n"
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        return _cheat_step(history)\n",
        ),
        (
            "solver_belief_via_helper_class",
            "class _SneakyHelper:\n"
            "    def probe(self, sp):\n"
            "        return sp.belief()\n"
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.h = _SneakyHelper()\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n",
        ),
        (
            "private_world_attr_snoop",
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        mole = history[0]._world.mole\n"
            "        return ('accuse', {'employee': mole})\n",
        ),
        (
            "dynamic_import_leak",
            "import importlib\n"
            "class BadPolicy:\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        mod = importlib.import_module('canary.world')\n"
            "        return ('status', {})\n",
        ),
        (
            "injected_oracle_act_delegation",
            "class BadPolicy:\n"
            "    def __init__(self, oracle):\n"
            "        self.oracle = oracle\n"
            "    def reset(self, tools_spec, instruction): pass\n"
            "    def act(self, history):\n"
            "        return self.oracle.act(history)\n",
        ),
    ]
    for label, bad_code in leak_snippets:
        _write_text_unlinked(clean_optional, bad_code)
        res = gate.check_ast_inference_isolation(root=syn, strict=True)
        assert res.passed is False, f"expected AST leak rejection for {label}"
        assert len(res.errors) >= 1


def test_check3_seed_and_secret_provenance_tamper_rejections(
    tmp_path: Path,
    base_surface: Path,
) -> None:
    full_syn = _clone_tiebreak_surface(tmp_path / "full", base_surface)
    assert gate.check_seed_and_secret_provenance(root=full_syn, strict=True).passed is True

    syn = _clone_provenance_tamper_surface(tmp_path / "slim", base_surface)
    eb_summary_path = syn / "results" / "tiebreak" / "empirical_bayes" / "summary.json"
    orig_eb = json.loads(eb_summary_path.read_text(encoding="utf-8"))

    bad_train = json.loads(json.dumps(orig_eb))
    bad_train["train_seeds"] = {"start": 500, "stop": 530}
    _write_text_unlinked(eb_summary_path, json.dumps(bad_train))
    res_tr = gate.check_seed_and_secret_provenance(root=syn)
    assert res_tr.passed is False
    assert any("train_seed" in e for e in res_tr.errors)

    bad_eval = json.loads(json.dumps(orig_eb))
    bad_eval["eval_seeds"] = {"start": 800190, "stop": 800210}
    _write_text_unlinked(eb_summary_path, json.dumps(bad_eval))
    res_ev = gate.check_seed_and_secret_provenance(root=syn)
    assert res_ev.passed is False
    assert any("held-out eval_seed" in e for e in res_ev.errors)

    bad_judge = json.loads(json.dumps(orig_eb))
    bad_judge["eval_seeds"] = [900000, 900001]
    _write_text_unlinked(eb_summary_path, json.dumps(bad_judge))
    res_jg = gate.check_seed_and_secret_provenance(root=syn)
    assert res_jg.passed is False
    assert any("JUDGE_SEEDS" in e for e in res_jg.errors)

    _write_text_unlinked(eb_summary_path, json.dumps(orig_eb))
    assert gate.check_seed_and_secret_provenance(root=syn).passed is True

    ledger_path = syn / "results" / "tiebreak" / "experiment_ledger.json"
    orig_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))

    for tamper_fn, expected_substr in (
        (lambda d: d["discovered_runs"][0].update({"heldout_n": 20}), "n >= 30"),
        (
            lambda d: d["discovered_runs"][0].update({"after_world_secret_tag": "sha256:deadbeef00001111"}),
            "world_secret_tag mismatch",
        ),
        (lambda d: d["discovered_runs"][0].update({"before_world_secret_tag": "unset"}), "world_secret_tag"),
        (lambda d: d["discovered_runs"][0].update({"replay_verified": False}), "replay_verified"),
        (lambda d: d["discovered_runs"][0].update({"paired_ci95_low": 0.0}), "paired_ci95_low > 0.0"),
    ):
        mut = json.loads(json.dumps(orig_ledger))
        tamper_fn(mut)
        _write_text_unlinked(ledger_path, json.dumps(mut))
        res_l = gate.check_seed_and_secret_provenance(root=syn)
        assert res_l.passed is False
        assert any(expected_substr in e for e in res_l.errors), res_l.errors

    _write_text_unlinked(ledger_path, json.dumps(orig_ledger))
    spoof_eb = json.loads(json.dumps(orig_eb))
    spoof_eb["paired"]["deltas"] = [-0.2] * 90
    _write_text_unlinked(eb_summary_path, json.dumps(spoof_eb))
    res_spoof = gate.check_seed_and_secret_provenance(root=syn)
    assert res_spoof.passed is False
    assert any("recomputed paired ci95_low" in e for e in res_spoof.errors)


def test_check4_claim_number_audit_tamper_rejections(
    tmp_path: Path,
    base_surface: Path,
) -> None:
    syn = _clone_tiebreak_surface(tmp_path, base_surface)
    assert gate.check_claim_number_audit(root=syn, strict=True).passed is True

    report_path = syn / "docs" / "reports" / "tiebreak_small_model.md"
    orig_report = report_path.read_text(encoding="utf-8")
    _write_text_unlinked(
        report_path,
        re.sub(
            r"Verified improvements passing all 4 strict gates: `\d+`",
            "Verified improvements passing all 4 strict gates: `999`",
            orig_report,
            count=1,
        ),
    )
    res_r = gate.check_claim_number_audit(root=syn)
    assert res_r.passed is False
    assert any("verified_improvements" in e for e in res_r.errors)
    _write_text_unlinked(report_path, orig_report)

    sc_table_path = syn / "results" / "tiebreak" / "scaling" / "table.md"
    orig_sc_table = sc_table_path.read_text(encoding="utf-8")
    _write_text_unlinked(sc_table_path, orig_sc_table.replace("+0.611 +/- 0.069", "+0.755 +/- 0.069"))
    res_sc = gate.check_claim_number_audit(root=syn)
    assert res_sc.passed is False
    assert any("scaling/table.md" in e for e in res_sc.errors)
    _write_text_unlinked(sc_table_path, orig_sc_table)

    eb_table_path = syn / "results" / "tiebreak" / "empirical_bayes" / "table.md"
    orig_eb_table = eb_table_path.read_text(encoding="utf-8")
    _write_text_unlinked(eb_table_path, orig_eb_table.replace("+0.622 [+0.571, +0.671]", "+0.822 [+0.571, +0.671]"))
    res_eb = gate.check_claim_number_audit(root=syn)
    assert res_eb.passed is False
    assert any("empirical_bayes/table.md" in e for e in res_eb.errors)
    _write_text_unlinked(eb_table_path, orig_eb_table)

    orphan_dir = syn / "results" / "tiebreak" / "unbacked_run"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    _write_text_unlinked(orphan_dir / "table.md", "| metric | val |\n|---|---:|\n| score | 0.500 |\n")
    res_orphan = gate.check_claim_number_audit(root=syn)
    assert res_orphan.passed is False
    assert any("missing backing summary.json" in e for e in res_orphan.errors)

    _write_text_unlinked(
        orphan_dir / "summary.json",
        json.dumps({"before": {"mean_score": 0.100}, "after": {"mean_score": 0.900}, "paired": {"mean_delta": 0.800, "ci95_low": 0.600}}),
    )
    res_mismatch = gate.check_claim_number_audit(root=syn)
    assert res_mismatch.passed is False
    assert any("not found in markdown table" in e for e in res_mismatch.errors)


def test_check5_hygiene_and_panel_fix_a_tamper_rejections(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    base_surface: Path,
    mini_valid_surface: Path,
) -> None:
    full_syn = _clone_tiebreak_surface(tmp_path / "full", base_surface)
    assert gate.check_hygiene_and_panel_fix_a(root=full_syn, tracked_paths=[], strict=True).passed is True

    syn = _clone_tiebreak_surface(tmp_path / "mini", mini_valid_surface)
    report_path = syn / "docs" / "reports" / "tiebreak_small_model.md"
    orig_report = report_path.read_text(encoding="utf-8")

    honest_note = "\nDev seeds 0-29 are a post-hoc lock, not a pre-registration.\n"
    _write_text_unlinked(report_path, orig_report + honest_note)
    assert gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=True).passed is True

    _write_text_unlinked(report_path, orig_report + f"\nBad punctuation {chr(0x2014)} here.\n")
    res_em = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[])
    assert res_em.passed is False
    assert any("em dash" in e for e in res_em.errors)

    _write_text_unlinked(report_path, orig_report + f"\nRange 10{chr(0x2013)}20 with en dash.\n")
    res_en_std = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=False)
    assert res_en_std.passed is True
    assert len(res_en_std.warnings) == 1
    res_en_strict = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[], strict=True)
    assert res_en_strict.passed is False

    _write_text_unlinked(report_path, orig_report + "\nEvaluated on our pre-registered seeds 0-29 split.\n")
    res_prereg = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[])
    assert res_prereg.passed is False
    assert any("Panel Fix A" in e for e in res_prereg.errors)
    _write_text_unlinked(report_path, orig_report)

    bad_wt = syn / "train" / "adapter_model.safetensors"
    _write_bytes_unlinked(bad_wt, b"weights")
    res_wt = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=["train/adapter_model.safetensors"])
    assert res_wt.passed is False
    assert any(".safetensors" in e for e in res_wt.errors)
    bad_wt.unlink()

    big_dump = syn / "results" / "tiebreak" / "huge_dump.json"
    if big_dump.exists():
        big_dump.unlink()
    with open(big_dump, "wb") as fh:
        fh.seek(gate.MAX_FILE_BYTES + 64)
        fh.write(b"\0")
    res_big = gate.check_hygiene_and_panel_fix_a(root=syn, tracked_paths=[])
    assert res_big.passed is False
    assert any("oversized file" in e for e in res_big.errors)

    rc_fail = gate.main(["--root", str(syn), "--json"])
    assert rc_fail == 1
    fail_json = json.loads(capsys.readouterr().out)
    assert fail_json["passed"] is False
    assert fail_json["checks"]["hygiene_and_panel_fix_a"]["passed"] is False
