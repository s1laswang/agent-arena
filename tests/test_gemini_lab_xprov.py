"""Cross-provider control (canary.gemini.xprov): pure-function tests on synthetic episodes, no API, no env."""
from canary.gemini import xprov


def _ep(label, provider, tier, seed, score, correct=True, cost=1.0, harness=xprov.SAME_HARNESS, roster=("a", "b")):
    return {"label": label, "provider": provider, "model": "m", "level": "medium", "harness": harness, "tier": tier,
            "seed": seed, "score": score, "correct": correct, "accused": True, "final_day": 5, "cost_usd": cost,
            "roster": roster}


def _world(gem_scores, gpt_scores, gem_cost=0.25, gpt_cost=1.0):
    eps = [_ep("gem", "google", "hard", i, s, s > 0, gem_cost) for i, s in enumerate(gem_scores)]
    eps += [_ep(xprov.GPT_SAME, "openai", "hard", i, s, s > 0, gpt_cost) for i, s in enumerate(gpt_scores)]
    solver = {("hard", i): 0.5 for i in range(max(len(gem_scores), len(gpt_scores)))}
    return eps, solver


def test_summarize_pairs_with_the_solver_and_prices_per_episode():
    eps, solver = _world([0.5] * 8, [0.25] * 8)
    rows = {r["label"]: r for r in xprov.summarize(eps, solver, B=500)}
    assert abs(rows["gem"]["pct_solver"] - 1.0) < 1e-9 and abs(rows[xprov.GPT_SAME]["pct_solver"] - 0.5) < 1e-9
    assert rows["gem"]["pct_lo"] == rows["gem"]["pct_hi"] == 1.0          # no variance -> degenerate CI
    assert rows["gem"]["cost_per_ep"] == 0.25 and rows["gem"]["n"] == 8 and rows["gem"]["correct"] == 8


def test_versus_uses_only_shared_seeds_and_gates_the_verdict():
    eps, _ = _world([0.6, 0.7, 0.6, 0.7, 0.6, 0.7, 0.9, 0.9], [0.1, 0.2, 0.1, 0.2, 0.1, 0.2])   # gem has 2 extra seeds
    v = xprov.versus(eps, xprov.GPT_SAME, B=2000)[0]
    assert v["shared_seeds"] == [0, 1, 2, 3, 4, 5] and v["n"] == 6
    assert v["verdict"] == "higher" and v["diff_lo"] > 0 and abs(v["base_cost_ratio"] - 4.0) < 1e-9
    noisy, _ = _world([0.9, -1.0, 0.8, -1.0, 0.7, 0.6], [0.5, 0.5, -1.0, 0.6, 0.4, 0.5])
    assert xprov.versus(noisy, xprov.GPT_SAME, B=2000)[0]["verdict"] == "not distinguishable"
    worse, _ = _world([0.1] * 6, [0.6, 0.7, 0.6, 0.7, 0.6, 0.7])
    assert xprov.versus(worse, xprov.GPT_SAME, B=2000)[0]["verdict"] == "lower"


def test_headline_is_prespecified_matched_effort_and_ci_gated():
    eps, _ = _world([0.6, 0.7, 0.6, 0.7, 0.6, 0.7], [0.1, 0.2, 0.1, 0.2, 0.1, 0.2])
    h = xprov.headline(xprov.versus(eps, xprov.GPT_SAME, B=2000))
    assert "gem scores higher" in h and "(4.0x cheaper)" in h and "n=6 shared seeds" in h and "matched medium effort" in h
    noisy, _ = _world([0.9, -1.0, 0.8, -1.0, 0.7, 0.6], [0.5, 0.5, -1.0, 0.6, 0.4, 0.5])
    h2 = xprov.headline(xprov.versus(noisy, xprov.GPT_SAME, B=2000))
    assert "gem is not distinguishable" in h2 and "higher" not in h2
    assert xprov.headline([]) == ""


def test_headline_ignores_small_cells_and_unmatched_levels():
    few, _ = _world([0.9, 0.9, 0.9], [0.1, 0.1, 0.1])                      # n=3 < MIN_SHARED: no headline, however good
    assert xprov.headline(xprov.versus(few, xprov.GPT_SAME, B=500)) == ""
    eps, _ = _world([0.6, 0.7, 0.6, 0.7, 0.6, 0.7], [0.1, 0.2, 0.1, 0.2, 0.1, 0.2])
    for e in eps:
        if e["provider"] == "google":
            e["level"] = "high"                                           # not the matched setting
    assert xprov.headline(xprov.versus(eps, xprov.GPT_SAME, B=500)) == ""


def test_same_world_check_flags_a_different_roster():
    eps, _ = _world([0.5, 0.5], [0.5, 0.5])
    assert xprov.check_same_world(eps) == {"same_roster": 2, "different_roster": [], "not_comparable": 0}
    eps[0]["roster"] = ("x", "y")
    chk = xprov.check_same_world(eps)
    assert chk["same_roster"] == 1 and chk["different_roster"] == [["gem", "hard", 0]]


def test_openai_cost_prefers_the_recorded_estimate_and_else_prices_cached_input():
    assert xprov.openai_cost("gpt-5.5", {"in": 10, "out": 1, "cost_usd_est": 0.42}) == 0.42
    c = xprov.openai_cost("gpt-5.5", {"in": 1_000_000, "cached_in": 800_000, "out": 10_000})
    assert abs(c - (200_000 * 5 + 800_000 * 0.5 + 10_000 * 30) / 1e6) < 1e-9


def test_committed_gpt_runs_load_with_costs_and_rosters():
    gpt = xprov.load_committed("gpt-5.5-full", xprov.GPT_SAME, xprov.SAME_HARNESS)
    assert {e["tier"] for e in gpt} == {"hard", "medium"} and len(gpt) >= 15
    assert all(e["cost_usd"] > 0 and e["roster"] for e in gpt)
    solver = xprov.committed_solver()
    assert all((e["tier"], e["seed"]) in solver for e in gpt)
