"""Pure-Python tests for train.eval_compact_hf (zero torch, zero Gemini calls)."""
from __future__ import annotations

import ast
import dataclasses
import io
import json
from pathlib import Path
import sys
import tokenize

import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy
from canary import world as canary_world
from train.eval_compact_hf import (
    DEFAULT_HELD_OUT_WORLD_SECRET,
    audit_seed_hygiene,
    compare_runs,
    compute_world_secret_tag,
    format_comparison_markdown,
    load_compact_render_module,
    luck_adjusted_episode_ev,
    main,
    run_compact_eval,
    verify_episode_file,
)

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "eval_compact_hf.py"
SELF_PATH = Path(__file__).resolve()


def _make_abstain_episode(tier: str, seed: int, secret: str | None = None) -> dict:
    prev = getattr(canary_world, "_SET_SECRET", None)
    if secret is not None:
        canary_world.set_world_secret(secret.encode("utf-8"))
    try:
        env = Env(tier=tier, seed=seed)
        while not env.done:
            env.call("advance_day", {})
        ep = dataclasses.asdict(env.result("abstain_agent"))
        if secret is not None:
            ep["meta"]["world_secret_tag"] = compute_world_secret_tag(secret)
        return ep
    finally:
        canary_world.set_world_secret(prev)


def _make_solver_episode(tier: str, seed: int, secret: str | None = None) -> dict:
    prev = getattr(canary_world, "_SET_SECRET", None)
    if secret is not None:
        canary_world.set_world_secret(secret.encode("utf-8"))
    try:
        env = Env(tier=tier, seed=seed)
        pol = SolverPolicy()
        ep = dataclasses.asdict(run_episode(env, pol))
        if secret is not None:
            ep["meta"]["world_secret_tag"] = compute_world_secret_tag(secret)
        return ep
    finally:
        canary_world.set_world_secret(prev)


def test_source_and_ast_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    banned_roots = {"torch", "transformers", "peft"}

    for path in (MODULE_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"comment token in {path}"
        assert hash_char not in src, f"hash char in {path}"
        assert em_dash not in src, f"em dash in {path}"
        assert en_dash not in src, f"en dash in {path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in banned_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned_roots

    assert _IMPORT_DELTA_HEAVY == frozenset()


def test_seed_hygiene_catches_all_leaks_and_unpaired_secrets() -> None:
    tag = compute_world_secret_tag(DEFAULT_HELD_OUT_WORLD_SECRET)
    clean = audit_seed_hygiene(
        train_seeds=[100_000, 150_000, 189_999],
        eval_seeds=[800_000, 800_001, 800_199],
        world_secret_tags={"before": tag, "after": tag},
    )
    assert clean["ok"] is True
    assert clean["violations"] == []
    assert clean["heldout_eval"] is True
    assert clean["world_secret_paired"] is True

    clean_dev = audit_seed_hygiene(
        train_seeds=[100_000, 100_001],
        eval_seeds=[0, 1, 29],
    )
    assert clean_dev["ok"] is True
    assert clean_dev["heldout_eval"] is False
    assert clean_dev["world_secret_paired"] is True

    dev_leak = audit_seed_hygiene([100_000, 0, 9_999], [800_000])
    assert dev_leak["ok"] is False
    assert dev_leak["dev_leaks"] == [0, 9_999]
    assert "train_dev_seed_leak" in dev_leak["violations"]

    pre_leak = audit_seed_hygiene([100_000, 10_000, 99_999], [800_000])
    assert pre_leak["ok"] is False
    assert pre_leak["pre_train_leaks"] == [10_000, 99_999]
    assert "train_pre_train_range_leak" in pre_leak["violations"]

    post_leak = audit_seed_hygiene([100_000, 200_000, 500_000], [800_000])
    assert post_leak["ok"] is False
    assert post_leak["post_train_leaks"] == [200_000, 500_000]
    assert "train_post_train_range_leak" in post_leak["violations"]

    heldout_leak = audit_seed_hygiene([100_000, 800_000, 800_199], [0, 1])
    assert heldout_leak["ok"] is False
    assert heldout_leak["heldout_leaks"] == [800_000, 800_199]
    assert "train_heldout_seed_leak" in heldout_leak["violations"]

    judge_leak = audit_seed_hygiene([100_000, 900_000, 900_039], [800_000])
    assert judge_leak["ok"] is False
    assert judge_leak["judge_leaks"] == [900_000, 900_039]
    assert "train_judge_seed_leak" in judge_leak["violations"]

    neg_leak = audit_seed_hygiene([-5, 100_000], [800_000])
    assert neg_leak["ok"] is False
    assert neg_leak["negative_leaks"] == [-5]
    assert "train_negative_seed" in neg_leak["violations"]

    overlap = audit_seed_hygiene([100_000, 190_005], [190_005, 190_006])
    assert overlap["ok"] is False
    assert overlap["train_eval_overlap"] == [190_005]
    assert "train_eval_seed_overlap" in overlap["violations"]

    unset_sec = audit_seed_hygiene(
        [100_000],
        [800_000],
        world_secret_tags={"before": None, "after": tag},
    )
    assert unset_sec["ok"] is False
    assert unset_sec["world_secret_paired"] is False
    assert unset_sec["unset_secret_runs"] == ["before"]
    assert "heldout_unset_world_secret" in unset_sec["violations"]

    proc_sec = audit_seed_hygiene(
        [100_000],
        [800_000],
        world_secret_tags={"before": "per_process_random", "after": "per_process_random"},
    )
    assert proc_sec["ok"] is False
    assert proc_sec["world_secret_paired"] is False
    assert "heldout_unset_world_secret" in proc_sec["violations"]

    mismatch_sec = audit_seed_hygiene(
        [100_000],
        [800_000],
        world_secret_tags={"before": "sha256:1111111111111111", "after": "sha256:2222222222222222"},
    )
    assert mismatch_sec["ok"] is False
    assert mismatch_sec["world_secret_paired"] is False
    assert "heldout_mismatched_world_secret_tags" in mismatch_sec["violations"]


def test_verify_episode_file_data_rule_and_secret_restoration(tmp_path: Path) -> None:
    prior_secret = b"prior-secret-value-at-least-16b"
    canary_world.set_world_secret(prior_secret)
    try:
        ep1 = _make_solver_episode("easy", 800_000, secret=DEFAULT_HELD_OUT_WORLD_SECRET)
        ep2 = _make_abstain_episode("easy", 800_001, secret=DEFAULT_HELD_OUT_WORLD_SECRET)
        assert getattr(canary_world, "_SET_SECRET", None) == prior_secret

        invalid_false = dict(ep2, seed=800_002, score=0.0, meta={"valid": False, "error": "infra:provider_quota"})
        timeout_meta = dict(ep2, seed=800_003, score=0.0, meta={"rc": "timeout", "valid": True})
        error_end = dict(ep2, seed=800_004, score=0.0, end_reason="error", meta={"error": "policy crashed"})

        jsonl_path = tmp_path / "episodes.jsonl"
        rows = [ep1, ep2, invalid_false, timeout_meta, error_end]
        jsonl_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        ver = verify_episode_file(jsonl_path, world_secret=DEFAULT_HELD_OUT_WORLD_SECRET)
        assert getattr(canary_world, "_SET_SECRET", None) == prior_secret
        assert ver["ok"] is True
        assert ver["replay_ok"] is True
        assert ver["data_rule_clean"] is False
        assert ver["total_count"] == 5
        assert ver["valid_count"] == 2
        assert ver["excluded_count"] == 3
        assert ver["replay_verified_count"] == 2
        expected_mean = (ep1["score"] + ep2["score"]) / 2.0
        assert ver["mean_score"] == pytest.approx(expected_mean)

        reason_sets = [set(x["reasons"]) for x in ver["excluded_episodes"]]
        assert {"valid_false", "infra_error"} in reason_sets
        assert {"rc_timeout"} in reason_sets
        assert {"end_reason_error"} in reason_sets

        tampered = dict(ep1, score=ep1["score"] + 0.123)
        bad_path = tmp_path / "tampered.jsonl"
        bad_path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
        bad_ver = verify_episode_file(bad_path, world_secret=DEFAULT_HELD_OUT_WORLD_SECRET)
        assert bad_ver["ok"] is False
        assert bad_ver["replay_ok"] is False
        assert bad_ver["mismatch_count"] == 1

        wrong_sec_path = tmp_path / "heldout_solver.jsonl"
        wrong_sec_path.write_text(json.dumps(ep1) + "\n", encoding="utf-8")
        wrong_sec_ver = verify_episode_file(
            wrong_sec_path,
            world_secret="completely-different-heldout-secret-99",
        )
        assert wrong_sec_ver["replay_ok"] is False
        assert wrong_sec_ver["mismatch_count"] == 1
        assert getattr(canary_world, "_SET_SECRET", None) == prior_secret
    finally:
        canary_world.set_world_secret(None)


def test_luck_adjusted_episode_ev_blind_abstain_and_solver() -> None:
    env_blind = Env(tier="easy", seed=5)
    env_blind.call("accuse", {"employee": "e00"})
    blind_ep = dataclasses.asdict(env_blind.result("blind_guesser"))

    blind_ev = luck_adjusted_episode_ev(blind_ep)
    assert blind_ev["replay_match"] is True
    assert blind_ev["accused"] == "e00"
    assert blind_ev["true_v"] == pytest.approx(1.0)
    assert blind_ev["p_emp"] == pytest.approx(1.0 / 12.0)
    assert blind_ev["luck_adjusted_ev"] == pytest.approx((1.0 / 12.0) * 1.0 - (11.0 / 12.0))

    abstain_ep = _make_abstain_episode("easy", 6)
    abs_ev = luck_adjusted_episode_ev(abstain_ep)
    assert abs_ev["replay_match"] is True
    assert abs_ev["accused"] is None
    assert abs_ev["p_emp"] is None
    assert abs_ev["raw_score"] == 0.0
    assert abs_ev["luck_adjusted_ev"] == 0.0

    solver_ep = _make_solver_episode("easy", 800_005, secret=DEFAULT_HELD_OUT_WORLD_SECRET)
    sol_ev = luck_adjusted_episode_ev(solver_ep, world_secret=DEFAULT_HELD_OUT_WORLD_SECRET)
    assert getattr(canary_world, "_SET_SECRET", None) is None
    assert sol_ev["replay_match"] is True
    assert sol_ev["p_emp"] is not None and sol_ev["p_emp"] > sol_ev["breakeven_p"]
    assert sol_ev["luck_adjusted_ev"] > 0.4


def test_compact_eval_paired_comparison_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    compact_mod = load_compact_render_module()
    assert hasattr(compact_mod, "CompactHFPolicy")

    call_counter = {"n": 0}

    def weak_generator(_turn: dict) -> str:
        call_counter["n"] += 1
        if call_counter["n"] % 4 == 1:
            return "unparseable text without json"
        return '{"name": "advance_day", "arguments": {}}'

    runs_root = tmp_path / "runs"
    before_summary = run_compact_eval(
        model_spec="weak_base",
        out_root=runs_root,
        tiers=("easy", "medium"),
        seeds_spec="heldout",
        n=2,
        run_id="before",
        generator=weak_generator,
        bootstrap_n=300,
    )
    after_summary = main([
        "--eval-model",
        "solver",
        "--tiers",
        "easy,medium",
        "--seeds",
        "heldout",
        "--n",
        "2",
        "--out",
        str(runs_root),
        "--run-id",
        "after",
        "--bootstrap-n",
        "300",
    ])
    capsys.readouterr()

    assert before_summary["n_valid"] == 4
    assert after_summary["n_valid"] == 4
    assert before_summary["world_secret_tag"] == after_summary["world_secret_tag"]
    assert before_summary["by_tier"]["all"]["abstain_rate"] == pytest.approx(1.0)
    assert before_summary["by_tier"]["all"]["valid_tool_call_rate"] < 1.0
    assert after_summary["by_tier"]["all"]["valid_tool_call_rate"] == pytest.approx(1.0)

    after_eps_path = runs_root / "after" / "episodes.jsonl"
    timeout_line = {
        "tier": "easy",
        "seed": 800_099,
        "agent": "solver",
        "steps": [],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 1,
        "end_reason": "horizon",
        "meta": {"rc": "timeout", "valid": False},
    }
    with open(after_eps_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(timeout_line) + "\n")

    out_json = tmp_path / "comp.json"
    out_md = tmp_path / "comp.md"
    comp = main([
        "--compare",
        f"before={runs_root / 'before'}",
        f"after={runs_root / 'after'}",
        "--bootstrap-n",
        "400",
        "--rng-seed",
        "7",
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ])
    printed_md = capsys.readouterr().out

    assert out_json.is_file()
    assert out_md.is_file()
    assert comp["hygiene"]["ok"] is True
    assert comp["hygiene"]["world_secret_paired"] is True
    assert comp["runs"]["after"]["n_valid"] == 4
    assert comp["runs"]["after"]["n_excluded"] == 1

    all_delta = comp["paired_delta"]["all"]
    assert all_delta["n_paired"] == 4
    assert all_delta["mean_score_delta"] > 0.4
    assert all_delta["score_delta_ci_lo"] > 0.0
    assert all_delta["mean_luck_adjusted_ev_delta"] > 0.4
    assert all_delta["luck_adjusted_ev_delta_ci_lo"] > 0.0
    assert all_delta["valid_tool_call_rate_delta"] > 0.0

    md_text = format_comparison_markdown(comp)
    assert md_text.strip() == printed_md.strip()
    assert chr(35) not in md_text
    assert chr(0x2014) not in md_text
    assert chr(0x2013) not in md_text
    assert "after - before" in md_text

    direct_comp = compare_runs(
        {"before": runs_root / "before", "after": runs_root / "after"},
        world_secret=DEFAULT_HELD_OUT_WORLD_SECRET,
        bootstrap_n=300,
        rng_seed=7,
        train_seeds=[100_000, 100_001],
    )
    assert direct_comp["hygiene"]["ok"] is True
    assert direct_comp["paired_delta"]["easy"]["n_paired"] == 2
    assert direct_comp["paired_delta"]["medium"]["n_paired"] == 2
    assert direct_comp["paired_delta"]["hard"]["n_paired"] == 0

    with pytest.raises(ValueError, match="workers"):
        main(["--verify", str(after_eps_path), "--workers", "2"])

    ver_cli = main(["--verify", str(after_eps_path)])
    capsys.readouterr()
    assert ver_cli["replay_ok"] is True
    assert ver_cli["valid_count"] == 4
    assert ver_cli["excluded_count"] == 1

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()


def test_wrong_accusations_hard_tier_and_tamper_rejection(tmp_path: Path) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    def blind_accuser(_turn: dict) -> str:
        return '{"name": "accuse", "arguments": {"employee": "e00"}}'

    def calibrated_abstainer(_turn: dict) -> str:
        return '{"name": "advance_day", "arguments": {}}'

    runs_root = tmp_path / "all_tiers"
    before_sum = run_compact_eval(
        model_spec="blind_base",
        out_root=runs_root,
        tiers=("easy", "medium", "hard"),
        seeds_spec="heldout",
        n=2,
        run_id="before",
        generator=blind_accuser,
        bootstrap_n=300,
    )
    after_sum = run_compact_eval(
        model_spec="calibrated_after",
        out_root=runs_root,
        tiers=("easy", "medium", "hard"),
        seeds_spec="heldout",
        n=2,
        run_id="after",
        generator=calibrated_abstainer,
        bootstrap_n=300,
    )
    assert before_sum["n_valid"] == 6
    assert after_sum["n_valid"] == 6

    b_all = before_sum["by_tier"]["all"]
    assert b_all["accuse_rate"] == pytest.approx(1.0)
    assert b_all["abstain_rate"] == pytest.approx(0.0)
    assert b_all["wrong_accuse_rate"] > 0.5
    assert b_all["accuracy"] + b_all["wrong_accuse_rate"] == pytest.approx(b_all["accuse_rate"])

    comp = compare_runs(
        {"before": runs_root / "before", "after": runs_root / "after"},
        world_secret=DEFAULT_HELD_OUT_WORLD_SECRET,
        bootstrap_n=400,
        rng_seed=11,
        train_seeds=[100_000, 100_001],
    )
    for tier_name in ("easy", "medium", "hard"):
        assert comp["paired_delta"][tier_name]["n_paired"] == 2
    assert comp["paired_delta"]["all"]["n_paired"] == 6
    assert comp["paired_delta"]["all"]["mean_score_delta"] > 0.5
    assert comp["paired_delta"]["all"]["mean_luck_adjusted_ev_delta"] > 0.7
    assert comp["paired_delta"]["all"]["wrong_accuse_rate_delta"] < -0.5

    bad_hygiene_comp = compare_runs(
        {"before": runs_root / "before", "after": runs_root / "after"},
        world_secret=DEFAULT_HELD_OUT_WORLD_SECRET,
        bootstrap_n=200,
        rng_seed=11,
        train_seeds=[100_000, 800_000],
    )
    assert bad_hygiene_comp["hygiene"]["ok"] is False
    assert "train_heldout_seed_leak" in bad_hygiene_comp["hygiene"]["violations"]

    tampered_dir = tmp_path / "tampered_run"
    tampered_dir.mkdir(parents=True, exist_ok=True)
    orig_lines = (runs_root / "after" / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
    first_ep = json.loads(orig_lines[0])
    first_ep["score"] = first_ep["score"] + 0.25
    (tampered_dir / "episodes.jsonl").write_text(json.dumps(first_ep) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="replay mismatch"):
        compare_runs(
            {"before": runs_root / "before", "after": tampered_dir},
            world_secret=DEFAULT_HELD_OUT_WORLD_SECRET,
            bootstrap_n=100,
        )

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
