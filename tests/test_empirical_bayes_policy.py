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

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary import world as canary_world
from canary.env import Env
from canary.eval import run_episode
import train.empirical_bayes_policy as eb_mod
from train.empirical_bayes_policy import (
    ABLATION_VARIANTS,
    DEFAULT_CHECKPOINT_DIR,
    HELDOUT_SECRET_TAG,
    EmpiricalBayesParams,
    EmpiricalBayesPolicy,
    assert_strict_train_seed,
    bootstrap_ci,
    build_ablation_variant_params,
    format_markdown_report,
    luck_adjusted_ev,
    main,
    make_ev_stop_only_params,
    make_naive_prior_params,
    make_no_canary_planting_params,
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

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)


def test_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    banned_flash = "gemini-" + "3.5" + "-flash"
    banned_prereg_hyphen = "pre-" + "regist"
    banned_prereg_compact = "prere" + "gist"
    forbidden_imports = {"torch", "transformers", "peft", "mlx", "mlx_lm", "google", "genai"}

    assert DEFAULT_CHECKPOINT_DIR == "/tmp/fleet-silas/shared/tiebreak/empirical_bayes"

    for py_path in (MODULE_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        low = src.lower()
        tree = ast.parse(src, filename=str(py_path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"comment token found in {py_path}"
        assert hash_char not in src, f"hash char found in {py_path}"
        assert em_dash not in src, f"em dash found in {py_path}"
        assert en_dash not in src, f"en dash found in {py_path}"
        assert banned_flash not in low, f"forbidden flash reference in {py_path}"
        assert banned_prereg_hyphen not in low, f"forbidden wording in {py_path}"
        assert banned_prereg_compact not in low, f"forbidden wording in {py_path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    for art_path in (SUMMARY_PATH, TABLE_PATH):
        assert art_path.is_file(), f"missing artifact: {art_path}"
        txt = art_path.read_text(encoding="utf-8")
        low = txt.lower()
        assert hash_char not in txt, f"hash char found in {art_path}"
        assert em_dash not in txt, f"em dash found in {art_path}"
        assert en_dash not in txt, f"en dash found in {art_path}"
        assert banned_flash not in low, f"forbidden flash row in {art_path}"
        assert banned_prereg_hyphen not in low, f"forbidden wording in {art_path}"
        assert banned_prereg_compact not in low, f"forbidden wording in {art_path}"

    assert _IMPORT_DELTA_HEAVY == frozenset()


def test_committed_summary_n180_n90_ablations_and_panel_fix_a() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    table_md = TABLE_PATH.read_text(encoding="utf-8")

    expected_sha_tag = "sha256:" + hashlib.sha256(HELDOUT_SECRET_TAG.encode("utf-8")).hexdigest()[:16]

    assert summary["run_id"] == "empirical-bayes-v14"
    assert summary["model"] == "EmpiricalBayesPolicy (likelihood + optimal stopping learned on TRAIN_SEEDS)"
    assert summary["tiers_version"] == "v1.4"
    assert summary["tiers"] == ["easy", "medium", "hard"]
    assert summary["n"] == 180
    assert summary["train_seeds"] == {"start": 102000, "stop": 102780}
    assert summary["eval_seeds"] == {"start": 800000, "stop": 800060}
    assert summary["eval_seed_range"] == "800000..800059"
    assert summary["eval_n90_seed_range"] == "800000..800029"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["total_episodes_replayed"] == 1530

    for side_key in ("before", "after"):
        side = summary[side_key]
        assert side["n"] == 180
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
    assert isinstance(paired["deltas"], list) and len(paired["deltas"]) == 180
    assert paired["mean_delta"] == pytest.approx(sum(paired["deltas"]) / 180.0, abs=1e-5)
    assert paired["mean_delta"] > 0.9
    assert paired["ci95_low"] > 0.8
    assert paired["ci95_high"] > paired["mean_delta"]

    ho = summary["heldout"]
    assert ho["n_per_tier"] == 60
    assert ho["n_total_per_agent"] == 180
    assert ho["eval_seed_range"] == "800000..800059"
    assert ho["episodes_replayed"] == 1260

    ho90 = summary["heldout_n90"]
    assert ho90["n_per_tier"] == 30
    assert ho90["n_total_per_agent"] == 90
    assert ho90["eval_seed_range"] == "800000..800029"
    assert len(ho90["before_after_gate"]["paired_episode_deltas"]) == 90
    assert ho90["before_after_gate"]["paired_mean_delta"] > 0.8
    assert ho90["before_after_gate"]["paired_ci95_low"] > 0.7

    ab = summary["component_ablation_matrix"]
    assert ab["eval_seed_range"] == "800000..800059"
    assert ab["n_per_tier"] == 60
    assert ab["n_total_per_variant"] == 180
    assert ab["world_secret_tag"] == HELDOUT_SECRET_TAG
    assert ab["replay_verified"] is True
    assert ab["episodes_replayed"] == 900
    assert tuple(v["variant"] for v in ab["variants"]) == ABLATION_VARIANTS

    ab_by_name = {v["variant"]: v for v in ab["variants"]}
    assert ab_by_name["eb_ev_stop_only"]["negative_ablation"] is True
    assert ab_by_name["eb_ev_stop_only"]["n180_overall"]["score"]["mean"] < 0.0
    assert ab_by_name["eb_no_canary_planting"]["negative_ablation"] is True
    assert ab_by_name["eb_no_canary_planting"]["n180_overall"]["total_canaries_planted"] == 0
    assert ab_by_name["eb_no_canary_planting"]["n180_overall"]["mean_canaries_planted"] == 0.0
    assert ab_by_name["eb_no_canary_planting"]["n180_overall"]["abstain_rate"] > 0.80

    pd_ov = ho["paired_deltas"]["overall"]
    assert pd_ov["eb_likelihood_only_minus_eb_naive_prior"]["score_delta"]["ci95_low"] > 0.5
    assert pd_ov["eb_experience_opt_minus_eb_no_canary_planting"]["score_delta"]["ci95_low"] > 0.45
    assert pd_ov["eb_experience_opt_minus_eb_likelihood_only"]["score_delta"]["ci95_low"] > 0.10
    assert pd_ov["eb_experience_opt_minus_heuristic"]["score_delta"]["ci95_low"] > 0.20

    validated = ledger_mod.validate_experiment_summary(
        summary,
        summary_path="results/tiebreak/empirical_bayes/summary.json",
    )
    assert validated["verified_improvement"] is True
    assert validated["status"] == "VERIFIED_IMPROVEMENT"
    assert validated["heldout_n"] == 180
    assert validated["gates"]["gate1_seed_hygiene"] is True
    assert validated["gates"]["gate2_paired_world_secret"] is True
    assert validated["gates"]["gate3_sample_and_replay"] is True
    assert validated["gates"]["gate4_paired_ci95_positive"] is True
    assert validated["gates"]["all_passed"] is True
    assert validated["gates"]["reasons"] == []

    assert summary["dev_protocol_label"] == "post-hoc locked dev hard 0..29"
    assert summary["dev_hard"]["protocol_label"] == "post-hoc locked dev hard 0..29"
    assert "post-hoc locked dev hard 0..29" in table_md
    assert "5. Keyless Reference Comparison on Post-Hoc Locked Dev Hard 0..29" in table_md

    assert format_markdown_report(summary) == table_md
    dev_agents = set(summary["dev_hard"]["agents"].keys())
    assert set(ABLATION_VARIANTS).issubset(dev_agents)
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
    like_params = EmpiricalBayesParams.from_dict(summary["parameters"]["eb_likelihood_only"])
    ev_only_params = make_ev_stop_only_params()
    no_can_params = make_no_canary_planting_params(like_params, opt_params)
    built = build_ablation_variant_params(naive_params, like_params, opt_params)
    assert tuple(built.keys()) == ABLATION_VARIANTS

    assert naive_params.use_ev_stopping is False
    assert like_params.use_ev_stopping is False
    assert ev_only_params.use_ev_stopping is True
    assert ev_only_params.w_angry_msg > 0.0
    assert no_can_params.canary_coverage == 0.0
    assert opt_params.use_ev_stopping is True
    assert opt_params.w_angry_msg < 0.0

    no_can_ep = run_episode(Env("medium", 102_001), EmpiricalBayesPolicy(no_can_params, seed=102_001))
    assert replay_verify_episode(no_can_ep) is True
    assert all(st.tool != "plant_canary" for st in no_can_ep.steps)

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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    with pytest.raises(ValueError, match="workers 1"):
        run_full_pipeline(
            stage2_count=1,
            stage3_count=1,
            heldout_count=1,
            dev_count=1,
            checkpoint_dir=str(tmp_path / "c"),
            results_dir=str(tmp_path / "r"),
            workers=2,
        )

    def _fast_opt_stopping(stage2_params: EmpiricalBayesParams, seeds: list[int]):
        for s in seeds:
            assert_strict_train_seed(s, eb_mod.STAGE3_TRAIN_RANGE[0], eb_mod.STAGE3_TRAIN_RANGE[1])
        opt = EmpiricalBayesParams(
            w_canary_hit=stage2_params.w_canary_hit,
            w_canary_miss=stage2_params.w_canary_miss,
            w_doc_hit=stage2_params.w_doc_hit,
            w_after_hours=stage2_params.w_after_hours,
            w_evasive=stage2_params.w_evasive,
            w_angry_msg=stage2_params.w_angry_msg,
            tau_margin=0.65,
            unsurfaced_v_discount=1.0,
            canary_coverage=0.55,
            tiny_pool_size=4,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="eb_experience_opt",
        )
        ev = eb_mod._eval_params_on_train_slice(opt, seeds)
        row = {
            "phase": "fast_smoke_selected",
            "canary_coverage": opt.canary_coverage,
            "tiny_pool_size": opt.tiny_pool_size,
            "tau_margin": opt.tau_margin,
            "unsurfaced_v_discount": opt.unsurfaced_v_discount,
            "use_ev_stopping": True,
            **ev,
        }
        return opt, {
            "seed_range": f"{seeds[0]}..{seeds[-1]}",
            "n_episodes": len(seeds),
            "selected": opt.to_dict(),
            "search_ledger": [row],
        }

    monkeypatch.setattr(eb_mod, "optimize_stopping_and_splits", _fast_opt_stopping)

    prior_env_secret = os.environ.get("CANARY_WORLD_SECRET")
    prior_set_secret = b"test-prior-secret-value-16bytes"
    os.environ["CANARY_WORLD_SECRET"] = "caller-env-secret-preserved"
    canary_world.set_world_secret(prior_set_secret)
    try:
        ckpt_dir = tmp_path / "ckpt"
        res_dir = tmp_path / "res"
        rc = main([
            "--stage2-n",
            "1",
            "--stage3-n",
            "1",
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
        assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()

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
