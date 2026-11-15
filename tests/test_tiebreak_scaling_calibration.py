from __future__ import annotations

import ast
import io
import json
import sys
import time
import tokenize
from pathlib import Path

import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy
import scripts.tiebreak_scaling_calibration as scaling

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_scaling_calibration.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "scaling" / "scaling_summary.json"
LEGACY_SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "scaling" / "summary.json"
TABLE_PATH = REPO_ROOT / "results" / "tiebreak" / "scaling" / "table.md"
SELF_PATH = Path(__file__).resolve()


def test_source_ast_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_flash = "gemini-3.5" + "-flash"
    forbidden_roots = {"torch", "transformers"}

    assert scaling.SUMMARY_JSON_DEFAULT == SUMMARY_PATH
    assert not LEGACY_SUMMARY_PATH.exists()

    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"comment tokens found in {path}"
        assert hash_char not in src, f"hash character found in {path}"
        assert em_dash not in src, f"em dash found in {path}"
        assert en_dash not in src, f"en dash found in {path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    script_tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    for node in script_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "CompactLinearPolicy":
            for inner in ast.walk(node):
                assert not isinstance(inner, (ast.Import, ast.ImportFrom))

    for art_path in (SUMMARY_PATH, TABLE_PATH):
        assert art_path.exists(), f"missing artifact {art_path}"
        art_txt = art_path.read_text(encoding="utf-8")
        assert em_dash not in art_txt, f"em dash found in {art_path}"
        assert en_dash not in art_txt, f"en dash found in {art_path}"
        assert forbidden_flash not in art_txt, f"forbidden flash row found in {art_path}"

    assert _IMPORT_DELTA_HEAVY == frozenset()


def test_seed_hygiene_guards() -> None:
    by_tier = scaling.select_train_seeds(6)
    assert set(by_tier.keys()) == {"easy", "medium", "hard"}
    flat = [s for seeds in by_tier.values() for s in seeds]
    assert len(flat) == 6 and len(set(flat)) == 6
    assert scaling.assert_train_seed_hygiene(flat) == flat

    for bad_train in (0, 500, 106_999, 109_000, 800_000, 900_000):
        with pytest.raises(AssertionError):
            scaling.assert_train_seed_hygiene([bad_train])

    with pytest.raises(ValueError):
        scaling.select_train_seeds(5)

    held = scaling.assert_heldout_seed_hygiene([800_000, 800_001], flat, require_heldout=True)
    assert held == [800_000, 800_001]

    for bad_eval in (107_000, 900_000, 500):
        with pytest.raises(AssertionError):
            scaling.assert_heldout_seed_hygiene([bad_eval], flat, require_heldout=True)


def test_tiny_scaling_experiment_and_rollout_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    t0 = time.perf_counter()
    calls: list[tuple[str, int]] = []
    orig_collect = scaling._collect_one_training_trajectory

    def tracked_collect(
        tier: str,
        seed: int,
        behavior_weights: scaling.LinearPolicyWeights,
        explore_eps: float,
    ) -> scaling.TrainingTrajectory:
        calls.append((tier, seed))
        return orig_collect(tier, seed, behavior_weights, explore_eps)

    monkeypatch.setattr(scaling, "_collect_one_training_trajectory", tracked_collect)

    s3 = scaling.select_train_seeds(3)
    s6 = scaling.select_train_seeds(6)
    for tier in scaling.TIERS:
        assert s6[tier][:1] == s3[tier]

    out = scaling.run_scaling_experiment(
        budgets=(0, 3),
        eval_seeds=[500],
        world_secret="",
        require_heldout=False,
        include_cross_model=False,
    )

    assert len(calls) == 3
    assert len(set(calls)) == 3
    assert out["train_budgets"] == [0, 3]
    assert out["train_seeds_unique_count"] == 3
    assert out["eval_episodes_per_budget"] == 3
    assert out["policy_architecture"]["n_parameters"] == 82

    for row in out["scaling_curve"]:
        assert row["all_replay_verified"] is True
        assert row["replay_verified"] == 3
        assert sum(row["counts"].values()) == 3
    assert time.perf_counter() - t0 < 45.0


def test_classify_episodes_small_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env_abstain = Env("easy", 502)
    while not env_abstain.done:
        env_abstain.call("advance_day", {})
    ep_abstain = scaling._episode_to_shallow_dict(env_abstain.result("abstain_fixture"))

    env_gamble = Env("easy", 502)
    emps_res = env_gamble.call("list_employees", {})
    emps = [e["id"] for e in emps_res.data["employees"]]
    wrong_emp = next(e for e in emps if e != env_gamble._world.mole)
    env_gamble.call("accuse", {"employee": wrong_emp})
    ep_gamble = scaling._episode_to_shallow_dict(env_gamble.result("gamble_fixture"))

    env_solver = Env("easy", 502)
    ep_solver = scaling._episode_to_shallow_dict(run_episode(env_solver, SolverPolicy()))

    fixture_path = tmp_path / "episodes.jsonl"
    fixture_path.write_text(
        "\n".join(json.dumps(ep, sort_keys=True) for ep in (ep_abstain, ep_gamble, ep_solver)) + "\n",
        encoding="utf-8",
    )

    res = scaling.classify_episodes(fixture_path)
    assert res["n"] == 3
    assert res["replay_verified"] == 3
    assert res["all_replay_verified"] is True
    assert sum(res["counts"].values()) == 3
    cats = [r["category"] for r in res["episodes"]]
    assert cats == ["calibrated_abstain", "premature_gamble_loss", "calibrated_win"]

    tampered = dict(ep_solver)
    tampered["score"] = float(ep_solver["score"]) + 0.25
    with pytest.raises(ValueError, match="replay mismatch"):
        scaling.classify_episodes([tampered])

    rc = scaling.main(["--classify", str(fixture_path), "--world-secret", ""])
    assert rc == 0
    cli_out = json.loads(capsys.readouterr().out)
    assert cli_out["n"] == 3
    assert cli_out["replay_verified"] == 3


def test_committed_scaling_summary_and_table() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["schema"] == "canary.tiebreak.scaling_calibration.v1"
    assert summary["tiers_version"] == "v1.4"
    assert summary["train_budgets"] == [0, 15, 60, 240, 900]
    assert summary["train_seed_range"] == [107_000, 108_999]
    assert summary["eval_seeds"] == [800_000, 800_029]
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["eval_episodes_per_budget"] == 90
    assert summary["world_secret_sha256_12"] != "public"

    curve = summary["scaling_curve"]
    assert len(curve) == 5
    for row in curve:
        assert row["all_replay_verified"] is True
        assert row["replay_verified"] == 90
        assert sum(row["counts"].values()) == 90

    n0_metrics = curve[0]["metrics"]
    nmax_metrics = curve[-1]["metrics"]
    assert nmax_metrics["mean_score"] > n0_metrics["mean_score"] + 0.50
    assert nmax_metrics["luck_adjusted_ev"] > n0_metrics["luck_adjusted_ev"] + 0.50
    assert nmax_metrics["accuracy"] > n0_metrics["accuracy"] + 0.80
    assert summary["delta_n0_to_max"]["score_gain"] > 0.50
    assert summary["delta_n0_to_max"]["luck_adjusted_gain"] > 0.50
    assert summary["monotonic_luck_adjusted_ev"] is True

    solver_ref = summary["solver_reference"]
    assert solver_ref["all_replay_verified"] is True
    assert solver_ref["replay_verified"] == 90

    cross_rows = summary["cross_model_v14"]
    assert len(cross_rows) >= 5
    for cr in cross_rows:
        assert cr["replay_verified"] == cr["n"]
        assert sum(cr["counts"].values()) == cr["n"]

    expected_md = scaling.render_markdown_report(summary)
    assert TABLE_PATH.read_text(encoding="utf-8") == expected_md
