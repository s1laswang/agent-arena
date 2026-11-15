from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
import sys
import tokenize
from pathlib import Path

import pytest

from canary import world as canary_world
from canary.env import Env
from canary.eval import run_episode
from train.empirical_bayes_policy import (
    DEFAULT_CHECKPOINT_DIR,
    HELDOUT_SECRET_TAG,
    EmpiricalBayesParams,
    EmpiricalBayesPolicy,
    assert_strict_train_seed,
    bootstrap_ci,
    format_markdown_report,
    luck_adjusted_ev,
    main,
    make_naive_prior_params,
    paired_bootstrap_delta,
    replay_verify_episode,
    run_full_pipeline,
    validate_seed_partition,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "empirical_bayes_policy.py"
LEDGER_SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_experiment_ledger.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "empirical_bayes" / "summary.json"
TABLE_PATH = REPO_ROOT / "results" / "tiebreak" / "empirical_bayes" / "table.md"
SELF_PATH = Path(__file__).resolve()

_SPEC = importlib.util.spec_from_file_location("tiebreak_experiment_ledger", LEDGER_SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
ledger_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ledger_mod)


def test_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    banned_flash = "gemini-" + "3.5" + "-flash"
    forbidden_imports = {"torch", "transformers", "peft", "mlx", "mlx_lm", "google", "genai"}

    assert DEFAULT_CHECKPOINT_DIR == "/localscratch/fleet-silas/tiebreak-shared/empirical_bayes"

    for py_path in (MODULE_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"comment token found in {py_path}"
        assert hash_char not in src, f"hash char found in {py_path}"
        assert em_dash not in src, f"em dash found in {py_path}"
        assert en_dash not in src, f"en dash found in {py_path}"
        assert banned_flash not in src.lower(), f"forbidden flash reference in {py_path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    for art_path in (SUMMARY_PATH, TABLE_PATH):
        assert art_path.is_file(), f"missing artifact: {art_path}"
        txt = art_path.read_text(encoding="utf-8")
        assert hash_char not in txt, f"hash char found in {art_path}"
        assert em_dash not in txt, f"em dash found in {art_path}"
        assert en_dash not in txt, f"en dash found in {art_path}"
        assert banned_flash not in txt.lower(), f"forbidden flash row in {art_path}"

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_committed_summary_passes_all_four_ledger_gates() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    table_md = TABLE_PATH.read_text(encoding="utf-8")

    expected_sha_tag = "sha256:" + hashlib.sha256(HELDOUT_SECRET_TAG.encode("utf-8")).hexdigest()[:16]

    assert summary["run_id"] == "empirical-bayes-v14"
    assert summary["model"] == "EmpiricalBayesPolicy (likelihood + optimal stopping learned on TRAIN_SEEDS)"
    assert summary["tiers_version"] == "v1.4"
    assert summary["tiers"] == ["easy", "medium", "hard"]
    assert summary["n"] == 90
    assert summary["train_seeds"] == {"start": 102000, "stop": 102780}
    assert summary["eval_seeds"] == {"start": 800000, "stop": 800030}
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    for side_key in ("before", "after"):
        side = summary[side_key]
        assert side["n"] == 90
        assert side["valid_call_rate"] == 1.0
        assert side["world_secret_tag"] == expected_sha_tag
        assert side["replay_verified"] is True
        assert side["invalid_episodes"] == 0

    assert summary["before"]["mean_score"] == pytest.approx(
        summary["heldout"]["overall"]["eb_naive_prior"]["score"]["mean"]
    )
    assert summary["after"]["mean_score"] == pytest.approx(
        summary["heldout"]["overall"]["eb_experience_opt"]["score"]["mean"]
    )

    paired = summary["paired"]
    assert isinstance(paired["deltas"], list) and len(paired["deltas"]) == 90
    assert paired["mean_delta"] == pytest.approx(sum(paired["deltas"]) / 90.0, abs=1e-5)
    assert paired["mean_delta"] > 0.5
    assert paired["ci95_low"] > 0.5
    assert paired["ci95_high"] > paired["mean_delta"]

    validated = ledger_mod.validate_experiment_summary(
        summary,
        summary_path="results/tiebreak/empirical_bayes/summary.json",
    )
    assert validated["verified_improvement"] is True
    assert validated["status"] == "VERIFIED_IMPROVEMENT"
    assert validated["gates"]["gate1_seed_hygiene"] is True
    assert validated["gates"]["gate2_paired_world_secret"] is True
    assert validated["gates"]["gate3_sample_and_replay"] is True
    assert validated["gates"]["gate4_paired_ci95_positive"] is True
    assert validated["gates"]["all_passed"] is True
    assert validated["gates"]["reasons"] == []

    assert format_markdown_report(summary) == table_md
    dev_agents = set(summary["dev_hard"]["agents"].keys())
    assert "opencode:google/gemini-4-carbon" in dev_agents
    assert "gemini:gemini-4-carbon" in dev_agents
    assert "solver" in dev_agents


def test_seed_partition_and_strict_train_seed_guards() -> None:
    assert assert_strict_train_seed(102_000, 102_000, 102_600) == 102_000
    assert assert_strict_train_seed(102_779, 102_600, 103_200) == 102_779

    validate_seed_partition(
        stage2_seeds=list(range(102_000, 102_010)),
        stage3_seeds=list(range(102_600, 102_610)),
        heldout_seeds=list(range(800_000, 800_005)),
        dev_seeds=list(range(0, 5)),
    )

    for bad_seed in (0, 9_999, 10_000, 99_999, 102_600, 200_000, 800_000, 900_000, -1, True):
        with pytest.raises(ValueError):
            assert_strict_train_seed(bad_seed, 102_000, 102_600)

    with pytest.raises(ValueError, match="outside allowed stage slice"):
        validate_seed_partition([102_000], [102_000], [800_000], [0])

    with pytest.raises(ValueError, match="HELDOUT_SEEDS"):
        validate_seed_partition([102_000], [102_600], [0], [0])

    with pytest.raises(ValueError, match="DEV_SEEDS"):
        validate_seed_partition([102_000], [102_600], [800_000], [800_000])


def test_posterior_stopping_and_replay_verification() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    opt_params = EmpiricalBayesParams.from_dict(summary["parameters"]["eb_experience_opt"])
    assert opt_params.to_dict() == summary["parameters"]["eb_experience_opt"]
    assert set(opt_params.theta_dict().keys()) == {
        "w_canary_hit",
        "w_canary_miss",
        "w_doc_hit",
        "w_after_hours",
        "w_evasive",
        "w_angry_msg",
    }

    naive_params = make_naive_prior_params()
    assert naive_params.use_ev_stopping is False
    assert opt_params.use_ev_stopping is True
    assert opt_params.w_angry_msg < 0.0

    for tier, seed in (("easy", 102_000), ("medium", 102_001), ("hard", 102_002)):
        pol = EmpiricalBayesPolicy(opt_params, seed=seed)
        ep = run_episode(Env(tier, seed), pol)
        assert replay_verify_episode(ep) is True
        assert ep.end_reason in ("accused", "horizon")
        assert all(bool(st.result.get("ok")) for st in ep.steps)
        ev = luck_adjusted_ev(ep)
        assert math.isfinite(ev)
        post = pol.posterior()
        assert math.isclose(sum(post.values()), 1.0, rel_tol=1e-6)

    tampered = copy.deepcopy(ep)
    tampered.score = float(tampered.score) + 0.25
    with pytest.raises(AssertionError, match="replay score mismatch"):
        replay_verify_episode(tampered)

    ci = bootstrap_ci([0.2, 0.4, 0.6, 0.8], n_boot=500, rng_seed=42)
    assert ci["ci95_low"] <= ci["mean"] <= ci["ci95_high"]
    with pytest.raises(ValueError, match="identical length"):
        paired_bootstrap_delta([1.0, 2.0], [1.0])


def test_mini_pipeline_cli_and_secret_restoration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValueError, match="workers 1"):
        run_full_pipeline(
            stage2_count=3,
            stage3_count=3,
            heldout_count=1,
            dev_count=1,
            checkpoint_dir=str(tmp_path / "c"),
            results_dir=str(tmp_path / "r"),
            workers=2,
        )

    prior_env_secret = os.environ.get("CANARY_WORLD_SECRET")
    prior_set_secret = b"test-prior-secret-value-16bytes"
    os.environ["CANARY_WORLD_SECRET"] = "caller-env-secret-preserved"
    canary_world.set_world_secret(prior_set_secret)
    try:
        ckpt_dir = tmp_path / "ckpt"
        res_dir = tmp_path / "res"
        rc = main([
            "--stage2-n",
            "3",
            "--stage3-n",
            "3",
            "--heldout-n",
            "1",
            "--dev-n",
            "1",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--results-dir",
            str(res_dir),
        ])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["replay_verified"] is True
        assert os.environ.get("CANARY_WORLD_SECRET") == "caller-env-secret-preserved"
        assert getattr(canary_world, "_SET_SECRET", None) == prior_set_secret

        assert (ckpt_dir / "checkpoints.json").is_file()
        mini_sum = json.loads((res_dir / "summary.json").read_text(encoding="utf-8"))
        assert (res_dir / "table.md").is_file()
        assert mini_sum["n"] == 3
        assert len(mini_sum["paired"]["deltas"]) == 3
        assert mini_sum["before"]["world_secret_tag"] == mini_sum["after"]["world_secret_tag"]
    finally:
        canary_world.set_world_secret(None)
        if prior_env_secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prior_env_secret
