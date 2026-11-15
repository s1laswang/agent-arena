"""Unit tests for catchability-guaranteed RLMoleV2 policy, gradients, training, and paired eval."""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if sys.path[:1] != [_REPO_ROOT]:
    if _REPO_ROOT in sys.path:
        sys.path.remove(_REPO_ROOT)
    sys.path.insert(0, _REPO_ROOT)
for _m in [k for k in list(sys.modules) if k == "canary" or k.startswith("canary.")]:
    _f = str(getattr(sys.modules[_m], "__file__", "") or "")
    if not _f.startswith(_REPO_ROOT):
        sys.modules.pop(_m, None)

import numpy as np
import pytest

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.forge import rl_mole_v2
from canary.forge.rl_mole_v2 import (
    ALL_AGENTS,
    EPS,
    FEATURE_NAMES,
    NONE_LEAK_IDX,
    RLMoleV2,
    TRAIN_SEEDS,
    VAL_SEEDS,
    _grad_entropy,
    _grad_logp,
    evaluate_paired_set,
    features,
    forward,
    init_params,
    is_wide_unrestricted,
    mi_bonus_and_grad,
    train,
    warm_start_params,
)
from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS, MoleDoc, MoleView
from canary.solver.policy import SolverPolicy


def _make_view(
    day: int = 4,
    rec_counts: tuple[int, ...] = (2, 12, 20),
    restricted: int = 0,
    restricted_peers: tuple[str, ...] = ("e03",),
    decoy: str | None = "e02",
    can_leak: bool = True,
) -> MoleView:
    docs = tuple(
        MoleDoc(f"d{i}", f"Doc {i}", rc, i % 3) for i, rc in enumerate(rec_counts)
    )
    return MoleView(
        day=day,
        docs=docs,
        days_since_last_leak=2,
        i_am_restricted=restricted,
        n_restricted_colleagues=len(restricted_peers),
        recent_low_recipient_docs=sum(1 for rc in rec_counts if rc <= 3),
        peers=("e01", "e02", "e03", "e04"),
        restricted_peers=restricted_peers,
        decoy=decoy,
        can_leak=can_leak,
    )


def test_features_rich_mole_view_and_empty_docs():
    v = _make_view(rec_counts=(2, 10, 22), restricted=0, restricted_peers=("e03",), decoy="e02")
    x = features(v)
    assert x.shape == (len(FEATURE_NAMES) + 1,)
    assert x[-1] == 1.0
    idx_wide = FEATURE_NAMES.index("wide_doc_share")
    idx_spread = FEATURE_NAMES.index("spread_recipients")
    idx_decoy = FEATURE_NAMES.index("has_decoy")
    idx_rpeer = FEATURE_NAMES.index("has_restricted_peer")
    assert math.isclose(float(x[idx_wide]), 2.0 / 3.0, rel_tol=1e-9)
    assert math.isclose(float(x[idx_spread]), (22.0 - 2.0) / 20.0, rel_tol=1e-9)
    assert float(x[idx_decoy]) == 1.0
    assert float(x[idx_rpeer]) == 1.0
    assert is_wide_unrestricted(x) is True

    v_empty = _make_view(rec_counts=(), restricted=0, restricted_peers=(), decoy=None)
    x_empty = features(v_empty)
    assert float(x_empty[idx_wide]) == 0.0
    assert float(x_empty[idx_spread]) == 0.0
    assert float(x_empty[idx_decoy]) == 0.0
    assert float(x_empty[idx_rpeer]) == 0.0
    assert is_wide_unrestricted(x_empty) is False

    v_boundary = _make_view(rec_counts=(4, 8), restricted=0)
    assert is_wide_unrestricted(features(v_boundary)) is False
    v_nine = _make_view(rec_counts=(4, 9), restricted=0)
    assert is_wide_unrestricted(features(v_nine)) is True
    v_rest = _make_view(rec_counts=(4, 20), restricted=1)
    assert is_wide_unrestricted(features(v_rest)) is False


def test_none_logit_cap_and_penalty_enforced():
    p = init_params(hidden=8, seed=7)
    p["bl"] = np.zeros(len(LEAK_SELECTORS), dtype=np.float64)
    p["bl"][NONE_LEAK_IDX] = 40.0

    v_wide = _make_view(rec_counts=(3, 18), restricted=0, can_leak=True)
    x_wide = features(v_wide)
    _, pl_wide, _ = forward(p, x_wide)
    assert float(pl_wide[NONE_LEAK_IDX]) < 0.06

    greedy_pol = RLMoleV2(p, greedy=True)
    dec = greedy_pol.decide(v_wide, random.Random(0))
    assert dec["leak"] in {"d0", "d1"}

    v_restricted = _make_view(rec_counts=(3, 18), restricted=1, can_leak=True)
    _, pl_rest, _ = forward(p, features(v_restricted))
    assert float(pl_rest[NONE_LEAK_IDX]) > 0.99


def test_policy_json_roundtrip_and_env_determinism():
    p = warm_start_params(hidden=10, seed=11)
    pol = RLMoleV2(p, greedy=False, name="v2_unit")
    dumped = json.dumps(pol.to_json())
    loaded = RLMoleV2.from_json(json.loads(dumped))
    for k in p:
        assert np.allclose(loaded.p[k], p[k])

    r1 = run_episode(Env("easy", 15, mole_strategy=pol), SolverPolicy("easy"))
    r2 = run_episode(Env("easy", 15, mole_strategy=loaded), SolverPolicy("easy"))
    assert (r1.score, r1.correct) == (r2.score, r2.correct)

    with pytest.raises(ValueError):
        RLMoleV2.from_json({"kind": "rl_mole", "params": {}})
    with pytest.raises(ValueError):
        RLMoleV2.from_json(
            {
                "kind": "rl_mole_v2",
                "features": ["day"],
                "leak_selectors": list(LEAK_SELECTORS),
                "frame_selectors": list(FRAME_SELECTORS),
                "params": pol.to_json()["params"],
            }
        )


def test_exact_gradients_against_finite_differences():
    p = init_params(hidden=6, seed=42)
    p["bl"][NONE_LEAK_IDX] = 2.5

    views = [
        _make_view(day=2, rec_counts=(2, 16), restricted=0, decoy="e02"),
        _make_view(day=9, rec_counts=(5, 7), restricted=0, restricted_peers=(), decoy=None),
        _make_view(day=12, rec_counts=(12, 24), restricted=1, restricted_peers=("e01", "e03")),
    ]
    xs = [features(v) for v in views]
    delta = 1e-6

    x0 = xs[0]
    li, fi = 2, 1
    g_lp, _ = _grad_logp(p, x0, li, fi)
    g_ent = _grad_entropy(p, x0)
    mi_val, g_mi = mi_bonus_and_grad(p, xs)
    assert mi_val > 0.0

    def logp_fn(q):
        _, pl, pf = forward(q, x0)
        return float(math.log(pl[li]) + math.log(pf[fi]))

    def ent_fn(q):
        _, pl, pf = forward(q, x0)
        return float(-np.sum(pl * np.log(pl + EPS)) - np.sum(pf * np.log(pf + EPS)))

    def mi_fn(q):
        val, _ = mi_bonus_and_grad(q, xs)
        return val

    for key in ("W1", "b1", "Wl", "bl", "Wf", "bf"):
        it = np.nditer(p[key], flags=["multi_index"])
        while not it.finished:
            idx = it.multi_index
            orig = float(p[key][idx])
            p[key][idx] = orig + delta
            lp_hi, ent_hi, mi_hi = logp_fn(p), ent_fn(p), mi_fn(p)
            p[key][idx] = orig - delta
            lp_lo, ent_lo, mi_lo = logp_fn(p), ent_fn(p), mi_fn(p)
            p[key][idx] = orig

            assert math.isclose(float(g_lp[key][idx]), (lp_hi - lp_lo) / (2.0 * delta), abs_tol=1e-5)
            assert math.isclose(float(g_ent[key][idx]), (ent_hi - ent_lo) / (2.0 * delta), abs_tol=1e-5)
            assert math.isclose(float(g_mi[key][idx]), (mi_hi - mi_lo) / (2.0 * delta), abs_tol=1e-5)
            it.iternext()

    p_const = init_params(hidden=6, seed=99)
    p_const["W1"][:] = 0.0
    mi_zero, _ = mi_bonus_and_grad(p_const, [xs[1], xs[2]])
    assert abs(mi_zero) < 1e-12


def test_train_checkpointing_and_judge_guard(tmp_path):
    best_out = tmp_path / "exported_best.json"
    res = train(
        iters=2,
        batch=2,
        workers=1,
        tier="easy",
        hidden=8,
        seed=3,
        val_every=1,
        train_seeds=[160000, 160001],
        val_seeds=[190000, 190001],
        out=tmp_path,
        best_policy_out=best_out,
        log=lambda _: None,
    )
    assert len(res["curve"]) == 2
    assert len(res["val_curve"]) >= 2
    row = json.loads((tmp_path / "curve.jsonl").read_text().splitlines()[0])
    assert {"min_regret", "solver_acc", "lam_catch", "mi_nats", "wide_none_rate"} <= set(row)
    assert (tmp_path / "policy_best.json").is_file()
    assert (tmp_path / "policy_final.json").is_file()
    assert best_out.is_file()
    loaded = RLMoleV2.from_json(json.loads(best_out.read_text()))
    assert loaded.p["W1"].shape[1] == 8

    with pytest.raises(ValueError):
        rl_mole_v2.run_batch(loaded.p, "easy", [900000], workers=1)


def test_paired_heldout_eval_smoke():
    pol = RLMoleV2(warm_start_params(hidden=8, seed=5), greedy=False)
    rep = evaluate_paired_set(
        pol,
        seeds=[200000, 200001],
        tier="easy",
        workers=1,
        v1_policy_path="data/rl_mole/policy_final.json",
        B=100,
    )
    assert rep["n"] == 2
    assert "rl_mole_v2" in rep
    assert "default_mole" in rep
    assert "rl_mole_v1" in rep
    assert "diff_v2_minus_default" in rep
    assert "diff_v2_minus_v1" in rep
    assert "catchable_85" in rep["rl_mole_v2"]
    prof = rep["rl_mole_v2"]["action_profile"]
    assert {"H_leak", "H_frame", "leak", "frame", "wide_unrestricted_none_rate"} <= set(prof)


def test_committed_policy_and_heldout_artifacts():
    root = Path(_REPO_ROOT)
    pol_path = root / "results" / "moletrain" / "rl_mole_v2_policy.json"
    ho_path = root / "results" / "moletrain" / "rl_mole_v2_heldout.json"
    mod_path = root / "canary" / "forge" / "rl_mole_v2.py"
    tst_path = root / "tests" / "test_rl_mole_v2.py"

    hash_ch = chr(35)
    em_dash = chr(0x2014)
    for src_path in (mod_path, tst_path):
        src_text = src_path.read_text(encoding="utf-8")
        assert hash_ch not in src_text
        assert em_dash not in src_text

    assert pol_path.is_file()
    assert ho_path.is_file()
    assert ho_path.stat().st_size < 40 * 1024

    pol_obj = json.loads(pol_path.read_text(encoding="utf-8"))
    pol = RLMoleV2.from_json(pol_obj)
    ep = run_episode(Env("easy", 200000, mole_strategy=pol), SolverPolicy("easy"))
    assert isinstance(ep.score, float)

    ho = json.loads(ho_path.read_text(encoding="utf-8"))
    req_top = {
        "policy",
        "v1_policy",
        "tier",
        "workers",
        "agents",
        "n_per_set",
        "bootstrap_resamples",
        "ci_format",
        "min_solver_acc_threshold",
        "catchable_85_definition",
        "seed_ranges",
        "catchable_85_both_sets",
        "all_heldout_catchable",
        "ws3_heldout",
        "rules_heldout",
    }
    assert req_top <= set(ho)
    assert ho["tier"] == "hard"
    assert ho["workers"] == 1
    assert ho["agents"] == list(ALL_AGENTS)
    assert ho["n_per_set"] == 60
    assert ho["bootstrap_resamples"] == 2000

    sr = ho["seed_ranges"]
    assert sr["train"] == [TRAIN_SEEDS.start, TRAIN_SEEDS.stop - 1]
    assert sr["val"] == [VAL_SEEDS.start, VAL_SEEDS.stop - 1]
    assert sr["ws3_heldout"] == [200000, 200059]
    assert sr["rules_heldout"] == [800000, 800059]
    assert sr["judge"] == [rules.JUDGE_SEEDS.start, rules.JUDGE_SEEDS.stop - 1]

    named_sets = {
        "dev": set(rules.DEV_SEEDS),
        "train": set(range(sr["train"][0], sr["train"][1] + 1)),
        "val": set(range(sr["val"][0], sr["val"][1] + 1)),
        "ws3_heldout": set(range(sr["ws3_heldout"][0], sr["ws3_heldout"][1] + 1)),
        "rules_heldout": set(range(sr["rules_heldout"][0], sr["rules_heldout"][1] + 1)),
        "judge": set(rules.JUDGE_SEEDS),
    }
    assert named_sets["rules_heldout"].issubset(set(rules.HELDOUT_SEEDS))
    keys = list(named_sets)
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1 :]:
            assert named_sets[k1].isdisjoint(named_sets[k2])

    for set_key, exp_range in (("ws3_heldout", [200000, 200059]), ("rules_heldout", [800000, 800059])):
        srep = ho[set_key]
        assert srep["n"] == 60
        assert srep["seed_range"] == exp_range
        assert srep["seeds"] == f"{exp_range[0]}-{exp_range[1]}"
        def_score = srep["default_mole"]["solver"]["score"][0]

        for mkey in ("rl_mole_v2", "default_mole", "rl_mole_v1"):
            mrep = srep[mkey]
            for ag in ALL_AGENTS:
                for metric in ("score", "acc"):
                    ci = mrep[ag][metric]
                    assert len(ci) == 3
                    assert ci[1] <= ci[0] <= ci[2]
            sol_acc = mrep["solver"]["acc"][0]
            sol_score = mrep["solver"]["score"][0]
            assert math.isclose(mrep["default_solver_score_half"], round(0.5 * def_score, 4), abs_tol=1e-4)
            assert mrep["catchable"] is bool(sol_acc >= ho["min_solver_acc_threshold"])
            expected_c85 = bool((sol_acc >= 0.85) and (sol_score >= 0.5 * def_score))
            assert mrep["catchable_85"] is expected_c85

        prof = srep["rl_mole_v2"]["action_profile"]
        assert prof["H_leak"] > 0.5
        assert prof["H_frame"] > 0.2
        assert prof["wide_unrestricted_none_rate"] <= 0.05
        assert math.isclose(sum(prof["leak"].values()), 1.0, abs_tol=1e-3)
        assert math.isclose(sum(prof["frame"].values()), 1.0, abs_tol=1e-3)

    expected_both = bool(
        ho["ws3_heldout"]["rl_mole_v2"]["catchable_85"]
        and ho["rules_heldout"]["rl_mole_v2"]["catchable_85"]
    )
    assert ho["catchable_85_both_sets"] is expected_both
    assert ho["all_heldout_catchable"] is expected_both
    assert ho["catchable_85_both_sets"] is True
