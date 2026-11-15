from __future__ import annotations

import ast
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time
import tokenize

import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary.env import Env
from canary.eval import run_episode
import scripts.run_tiebreak_policy as cli
import scripts.tiebreak_scaling_calibration as scaling_mod
import scripts.verify_tiebreak_submission as gate
import train.neural_mlp_tiebreak as mlp_mod

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_tiebreak_policy.py"
SELF_PATH = Path(__file__).resolve()


def _build_scoped_ast_root(dst: Path) -> Path:
    stubs = {
        "train/compact_render.py": "CompactStubPolicy",
        "train/empirical_bayes_policy.py": "EmpiricalBayesStubPolicy",
        "scripts/tiebreak_scaling_calibration.py": "ScalingStubPolicy",
    }
    for rel_mod, cls_name in stubs.items():
        p = dst / rel_mod
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"class {cls_name}:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ready = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n",
            encoding="utf-8",
        )
    hf_stub = dst / "train" / "eval_compact_hf.py"
    hf_stub.parent.mkdir(parents=True, exist_ok=True)
    hf_stub.write_text("def run_compact_eval():\n    return {}\n", encoding="utf-8")

    script_dst = dst / "scripts" / "run_tiebreak_policy.py"
    script_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_PATH, script_dst)
    return dst


def test_source_hygiene_and_strict_ast_inference_isolation(tmp_path: Path) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    if py_path == SCRIPT_PATH:
                        assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots
                if py_path == SCRIPT_PATH:
                    assert not node.module.startswith(("canary.solver", "canary.world"))
                    if node.module == "canary":
                        imported_names = {a.name for a in node.names}
                        assert "solver" not in imported_names
                        assert "world" not in imported_names

    assert _IMPORT_DELTA_HEAVY == frozenset()
    scoped_root = _build_scoped_ast_root(tmp_path / "ast_scope")
    rel_outcome = gate.check_ast_inference_isolation(
        root=scoped_root,
        extra_paths=[scoped_root / Path("scripts/run_tiebreak_policy.py")],
        strict=True,
    )
    assert rel_outcome.passed is True, rel_outcome.errors
    assert rel_outcome.errors == []
    assert "scripts/run_tiebreak_policy.py" in rel_outcome.metrics["modules_checked"]
    assert "scripts/run_tiebreak_policy.py:AbstainPolicy" in rel_outcome.metrics["policy_classes_checked"]
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()

    script_tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    full_leaks = gate._scan_ast_block_for_leaks(
        script_tree.body,
        {},
        "scripts/run_tiebreak_policy.py",
        own_class_methods={"reset", "act"},
    )
    assert full_leaks == []


def test_check_mode_fast_smoke_cli_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    rc = cli.main(["--check", "--json"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 10.0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == cli.SCHEMA_ID
    assert payload["passed"] is True
    assert payload["mode"] == "check"
    assert payload["policy"] == "empirical_bayes"
    assert payload["paired_before_policy"] == "naive_prior"
    assert payload["seed_split"] == "heldout"
    assert payload["tiers"] == ["easy", "medium", "hard"]
    assert payload["seeds"] == [800_000, 800_001, 800_002]
    assert payload["n"] == 3
    assert payload["replay_verified"] is True
    assert payload["episodes_replayed"] == 6
    assert payload["episodes_expected"] == 6
    assert payload["invalid_episodes"] == 0
    assert payload["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert payload["before"]["world_secret_tag"] == payload["after"]["world_secret_tag"]
    assert payload["paired"]["mean_delta"] > 0.0

    rc_human = cli.main(["--check"])
    assert rc_human == 0
    human_txt = capsys.readouterr().out
    assert "TIEBREAK POLICY EVAL [CHECK]: PASS" in human_txt
    assert "replayed=6/6" in human_txt

    for base_pol in ("abstain", "naive_prior"):
        rc_bad = cli.main(["--policy", base_pol, "--check", "--json"])
        assert rc_bad == 2
        err_obj = json.loads(capsys.readouterr().out)
        assert err_obj["passed"] is False

    rc_dev_check = cli.main(["--seeds", "0-2", "--check", "--json"])
    assert rc_dev_check == 2
    _ = capsys.readouterr()


def test_trained_policies_baselines_and_committed_summary_parity(capsys: pytest.CaptureFixture[str]) -> None:
    eb_sum = json.loads((REPO_ROOT / "results/tiebreak/empirical_bayes/summary.json").read_text(encoding="utf-8"))
    cl_sum = json.loads((REPO_ROOT / "results/tiebreak/dagger_ablation/summary.json").read_text(encoding="utf-8"))
    sc_sum = json.loads((REPO_ROOT / "results/tiebreak/scaling/scaling_summary.json").read_text(encoding="utf-8"))

    rep_eb = cli.evaluate_policy(
        policy_name="empirical_bayes",
        tiers=("easy",),
        seeds=(800_000,),
        paired_before="auto",
        root=REPO_ROOT,
    )
    assert rep_eb["passed"] is True
    assert rep_eb["paired_before_policy"] == "naive_prior"
    assert rep_eb["episodes_replayed"] == 2
    assert rep_eb["paired"]["deltas"] == eb_sum["paired"]["deltas"][:1]

    rep_cl = cli.evaluate_policy(
        policy_name="compact_linear_dagger",
        tiers=("easy",),
        seeds=(800_000,),
        paired_before="auto",
        root=REPO_ROOT,
    )
    assert rep_cl["passed"] is True
    assert rep_cl["provenance"]["param_count"] == 785
    assert rep_cl["episodes_replayed"] == 2
    assert rep_cl["paired"]["deltas"] == cl_sum["paired"]["deltas"][:1]

    sc_row_900 = next(r for r in sc_sum["scaling_curve"] if int(r["n_train"]) == 900)
    sc_fac, _ = cli.load_policy_bundle("scaling_logistic", root=REPO_ROOT)
    with cli._scoped_world_secret(cli.HELDOUT_WORLD_SECRET):
        sc_direct_scores = [
            float(run_episode(Env("easy", sd), sc_fac(sd)).score)
            for sd in (800_000, 800_001)
        ]
    sc_easy_ref = sum(sc_direct_scores) / len(sc_direct_scores)
    assert sc_row_900["by_tier"]["easy"]["metrics"]["n"] == 30
    assert scaling_mod.D_SUSPECT > 0

    rep_sc = cli.evaluate_policy(
        policy_name="scaling_logistic",
        tiers=("easy",),
        seeds=(800_000, 800_001),
        paired_before="abstain",
        root=REPO_ROOT,
    )
    assert rep_sc["passed"] is True
    assert rep_sc["provenance"]["param_count"] == 82
    assert rep_sc["episodes_replayed"] == 4
    assert rep_sc["metrics"]["overall"]["mean_score"] == pytest.approx(sc_easy_ref, abs=1e-6)
    assert rep_sc["before"]["mean_score"] == pytest.approx(0.0, abs=1e-9)
    assert rep_sc["paired"]["mean_delta"] == pytest.approx(sc_easy_ref, abs=1e-6)

    rc_dev = cli.main(
        [
            "--policy",
            "compact_linear_dagger",
            "--tier",
            "easy,hard",
            "--seeds",
            "0",
            "--paired-before",
            "naive_prior",
            "--json",
        ]
    )
    assert rc_dev == 0
    dev_out = json.loads(capsys.readouterr().out)
    assert dev_out["seed_split"] == "dev"
    assert dev_out["world_secret_tag"] == "public"
    assert dev_out["n"] == 2
    assert dev_out["episodes_replayed"] == 4
    assert "post-hoc locked, not pre-registered" in dev_out["protocol_note"].lower()

    rep_abs = cli.evaluate_policy(policy_name="abstain", tiers=("easy", "medium"), seeds=(800_199,))
    assert rep_abs["passed"] is True
    assert rep_abs["metrics"]["overall"]["mean_score"] == 0.0
    assert rep_abs["metrics"]["overall"]["abstain_rate"] == 1.0
    assert rep_abs["metrics"]["overall"]["valid_call_rate"] == 1.0


def test_tiny_mlp_checkpoint_and_shallow_ci_deterministic_retrain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_default_mlp_cache_dir", lambda: tmp_path / "mlp_cache")
    mlp_sum_path = REPO_ROOT / "results/tiebreak/neural_mlp_dagger/mlp_summary.json"
    mlp_sum = json.loads(mlp_sum_path.read_text(encoding="utf-8"))
    exp_thr = float(mlp_sum["selected_commit_threshold"])

    shared_ckpt = Path(mlp_mod.DEFAULT_CKPT_PATH)
    if shared_ckpt.is_file():
        rep_live = cli.evaluate_policy(
            policy_name="tiny_mlp",
            tiers=("easy",),
            seeds=(800_000,),
            paired_before="auto",
            root=REPO_ROOT,
        )
        assert rep_live["passed"] is True
        assert rep_live["paired"]["deltas"] == mlp_sum["paired"]["deltas"][:1]
        wt_stage3 = mlp_mod.load_checkpoint_npz(shared_ckpt, "stage3_onpolicy_dagger_r2")
    else:
        wt_base = mlp_mod.init_untrained_weights(107_000)
        wt_stage3 = mlp_mod.MLPWeights(
            wt_base.w1,
            wt_base.b1,
            wt_base.w2,
            wt_base.b2,
            wt_base.w3,
            wt_base.b3,
            exp_thr,
            "stage3_onpolicy_dagger_r2",
        )

    tmp_ckpt = tmp_path / "tiny_mlp_test.npz"
    mlp_mod.save_checkpoint_npz(
        tmp_ckpt,
        {
            "stage0_untrained": mlp_mod.init_untrained_weights(107_000),
            "stage3_onpolicy_dagger_r2": wt_stage3,
        },
    )
    rc_ckpt = cli.main(
        [
            "--policy",
            "tiny_mlp",
            "--tier",
            "easy",
            "--seeds",
            "800000",
            "--paired-before",
            "untrained",
            "--mlp-ckpt",
            str(tmp_ckpt),
            "--json",
        ]
    )
    assert rc_ckpt == 0
    ckpt_out = json.loads(capsys.readouterr().out)
    assert ckpt_out["passed"] is True
    assert ckpt_out["provenance"]["weight_source"] == "explicit_ckpt_npz"
    assert ckpt_out["provenance"]["param_count"] == int(mlp_sum["param_count"])
    assert ckpt_out["episodes_replayed"] == 2

    orig_adam = mlp_mod._train_mlp_adam

    def _fast_adam(samples, init_w, epochs=40, **kwargs):
        return orig_adam(samples, init_w, epochs=min(int(epochs), 4), **kwargs)

    monkeypatch.setattr(mlp_mod, "_train_mlp_adam", _fast_adam)

    mini_root = tmp_path / "mini_repo"
    mini_mlp_dir = mini_root / "results" / "tiebreak" / "neural_mlp_dagger"
    mini_mlp_dir.mkdir(parents=True, exist_ok=True)
    mini_sum = dict(mlp_sum)
    mini_sum["train_seeds"] = {"start": 107_000, "stop": 107_002}
    (mini_mlp_dir / "mlp_summary.json").write_text(json.dumps(mini_sum), encoding="utf-8")

    cli._MLP_WEIGHT_MEMO.clear()
    rep_retrain = cli.evaluate_policy(
        policy_name="tiny_mlp",
        tiers=("easy",),
        seeds=(800_000,),
        root=mini_root,
    )
    assert rep_retrain["passed"] is True
    assert rep_retrain["provenance"]["weight_source"] in (
        "deterministic_retrain_from_summary",
        "cached_reconstructed_npz",
    )
    assert rep_retrain["episodes_replayed"] == 1


def test_seed_guards_judge_blocking_and_secret_scoping(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CANARY_WORLD_SECRET", raising=False)

    for bad_spec in (
        "900000",
        "900000-900002",
        "judge",
        "950000",
        "100000",
        "102500",
        "199999",
        "-1",
        "10000",
        "500000",
        "800200",
        "899999",
        "0,800000",
        "800000,800000",
        "800005-800001",
    ):
        rc = cli.main(["--policy", "abstain", "--tier", "easy", "--seeds", bad_spec, "--json"])
        assert rc == 2, f"expected rejection for seeds={bad_spec!r}"
        err = json.loads(capsys.readouterr().out)
        assert err["passed"] is False

    rc_no_sec = cli.main(
        ["--policy", "abstain", "--tier", "easy", "--seeds", "900000", "--allow-judge-smoke", "--json"]
    )
    assert rc_no_sec == 2
    _ = capsys.readouterr()

    for bad_sec in ("", "public", "none", "unset", "random", "abc"):
        rc_bad_sec = cli.main(
            [
                "--policy",
                "abstain",
                "--tier",
                "easy",
                "--seeds",
                "900000",
                "--allow-judge-smoke",
                "--world-secret",
                bad_sec,
                "--json",
            ]
        )
        assert rc_bad_sec == 2
        _ = capsys.readouterr()

    monkeypatch.setenv("CANARY_WORLD_SECRET", "judge-smoke-explicit-secret-2026")
    rc_still_blocked = cli.main(["--policy", "abstain", "--tier", "easy", "--seeds", "900000", "--json"])
    assert rc_still_blocked == 2
    _ = capsys.readouterr()

    rc_out_of_judge = cli.main(
        ["--policy", "abstain", "--tier", "easy", "--seeds", "900045", "--allow-judge-smoke", "--json"]
    )
    assert rc_out_of_judge == 2
    _ = capsys.readouterr()

    rc_judge_ok = cli.main(
        [
            "--policy",
            "empirical_bayes",
            "--tier",
            "easy",
            "--seeds",
            "900000",
            "--paired-before",
            "abstain",
            "--allow-judge-smoke",
            "--json",
        ]
    )
    assert rc_judge_ok == 0
    judge_rep = json.loads(capsys.readouterr().out)
    assert judge_rep["passed"] is True
    assert judge_rep["seed_split"] == "judge_smoke"
    assert judge_rep["episodes_replayed"] == 2
    assert os.environ.get("CANARY_WORLD_SECRET") == "judge-smoke-explicit-secret-2026"

    monkeypatch.setenv("CANARY_WORLD_SECRET", "ambient-secret-preserved-01")
    custom_rep = cli.evaluate_policy(
        policy_name="empirical_bayes",
        tiers=("easy",),
        seeds=(800_150, 800_151),
        paired_before="naive_prior",
        world_secret="custom-heldout-secret-xyz987",
        root=REPO_ROOT,
    )
    assert custom_rep["passed"] is True
    assert custom_rep["world_secret_tag"] == cli.compute_secret_tag("custom-heldout-secret-xyz987")
    assert custom_rep["before"]["world_secret_tag"] == custom_rep["after"]["world_secret_tag"]
    assert os.environ.get("CANARY_WORLD_SECRET") == "ambient-secret-preserved-01"


def test_replay_verifier_rejects_tampered_episodes() -> None:
    factory, _ = cli.load_policy_bundle("empirical_bayes", root=REPO_ROOT)
    with cli._scoped_world_secret(cli.HELDOUT_WORLD_SECRET):
        ep = run_episode(Env("easy", 800_000), factory(800_000))
        assert cli.verify_episode_replay(ep) is True

        bad_score = copy.deepcopy(ep)
        bad_score.score = float(ep.score) - 0.15
        with pytest.raises(AssertionError, match="replay terminal mismatch"):
            cli.verify_episode_replay(bad_score)

        bad_accused = copy.deepcopy(ep)
        bad_accused.accused = "e99"
        with pytest.raises(AssertionError, match="replay terminal mismatch"):
            cli.verify_episode_replay(bad_accused)

        bad_step_data = copy.deepcopy(ep)
        bad_step_data.steps[0].result["data"] = {"tampered": True}
        with pytest.raises(AssertionError, match="replay data mismatch"):
            cli.verify_episode_replay(bad_step_data)

        bad_step_ok = copy.deepcopy(ep)
        bad_step_ok.steps[0].result["ok"] = False
        with pytest.raises(AssertionError, match="replay ok mismatch"):
            cli.verify_episode_replay(bad_step_ok)

        bad_invalid = copy.deepcopy(ep)
        bad_invalid.end_reason = "error"
        with pytest.raises(AssertionError, match="episode invalid"):
            cli.verify_episode_replay(bad_invalid)
