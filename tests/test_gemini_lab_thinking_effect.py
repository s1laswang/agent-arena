"""thinking_effect: the pooled OLS + clustered bootstrap recovers a known synthetic slope; eligibility rules hold."""
import numpy as np

from canary.gemini import thinking_effect as te


def _synthetic(slope, n_seeds=30, noise=8.0, seed=1):
    rng = np.random.default_rng(seed)
    rows, model_fx, tier_fx = [], {"gemini-a": 0.0, "gemini-b": -40.0, "gemini-c": 15.0}, {"hard": -10.0, "medium": 0.0}
    for tier in tier_fx:
        for s in range(n_seeds):
            world = rng.normal(0, 10)  # shared (tier, seed) shock: what the clustered bootstrap must absorb
            for m, mfx in model_fx.items():
                for lv in ("low", "medium", "high"):
                    st = te.STEP[lv]
                    y = mfx + tier_fx[tier] + slope * st + world + rng.normal(0, noise)
                    rows.append({"model": m, "level": lv, "step": st, "tier": tier, "seed": s,
                                 "thinking_10k": st * 0.5, "score_pp_of_solver": y, "accuracy_pp": 50 + 5 * st,
                                 "premature_regret_per_ep": 0.3 - 0.05 * st})
    return rows


def test_recovers_known_slope_with_ci():
    rows = _synthetic(slope=12.0)
    r = te.clustered_bootstrap(rows, "step", "score_pp_of_solver", B=400, rng=np.random.default_rng(0))
    assert abs(r["slope"] - 12.0) < 1.5 and r["ci95"][0] < 12.0 < r["ci95"][1] and r["excludes_zero"]
    assert r["n_clusters"] == 60 and r["n_episodes"] == 60 * 9


def test_null_slope_is_reported_as_not_distinguishable():
    a = te.analyse(_synthetic(slope=0.0), B=300)
    s = a["pooled_step"]["score_pp_of_solver"]
    assert s["ci95"][0] < 0 < s["ci95"][1] and "not distinguishable from zero" in a["headline"]
    assert abs(a["pooled_step"]["accuracy_pp"]["slope"] - 5.0) < 1e-6
    assert abs(a["pooled_dose_per_10k_thinking_tokens"]["accuracy_pp"]["slope"] - 10.0) < 1e-6
    assert set(a["per_model_step"]) == {"gemini-a", "gemini-b", "gemini-c"}


def test_positive_headline_wording():
    a = te.analyse(_synthetic(slope=10.0), B=300)
    assert a["headline"].startswith("Each step up in thinking_level adds +")


def test_eligibility_excludes_single_level_default_and_non_gemini():
    def ep(model, level, tier="hard", seed=0, score=0.5):
        return {"_cell": {"model": model, "level": level, "tier": tier, "seed": seed, "thinking": 1000},
                "score": score, "correct": True, "_premature": 0.0}
    eps = [ep("gemini-x", "low"), ep("gemini-x", "high"), ep("gemini-y", "high"), ep("gemini-x", "default"),
           ep("gemma-4-31b-it", "low"), ep("gemma-4-31b-it", "high")]
    rows = te.episode_table(eps, {("hard", 0): 0.5})
    assert {(r["model"], r["level"]) for r in rows} == {("gemini-x", "low"), ("gemini-x", "high")}
    assert all(r["score_pp_of_solver"] == 0.0 for r in rows)
