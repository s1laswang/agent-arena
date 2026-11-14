import json

from canary.analysis.gap import gap_alert, load_runs, mean_ci, pass_hat_k, summarize, gap_table_md, tag_counts


def ep(agent, seed, score, correct, tier="medium", day=5):
    return dict(tier=tier, seed=seed, agent=agent, steps=[], score=score, accused="e01" if correct else None,
                correct=correct, final_day=day, end_reason="accused", meta={})


def test_mean_ci():
    assert mean_ci([1.0]) == (1.0, 0.0)
    m, h = mean_ci([0.0, 1.0, 0.0, 1.0])
    assert m == 0.5 and h > 0


def test_pass_hat_k():
    assert pass_hat_k({1: [True, True, True], 2: [True, False, True]}, 3) == 0.5


def test_summarize_and_alert(tmp_path):
    eps = [ep("solver", s, 0.8, True) for s in range(3)] + [ep("openai:x", s, 0.4 * (s % 2), s % 2 == 1) for s in range(3)]
    d = tmp_path / "r1"; d.mkdir()
    (d / "episodes.jsonl").write_text("\n".join(json.dumps(e) for e in eps))
    rows = summarize(load_runs(tmp_path))
    agent = next(r for r in rows if r["agent"] == "openai:x")
    assert abs(agent["norm"] - (0.5 / 3)) < 1e-9 and abs(agent["accuracy"] - 1 / 3) < 1e-9
    assert "openai:x" in gap_table_md(rows)
    assert gap_alert(rows) == []
    strong = summarize([ep("solver", 0, 0.8, True), ep("a", 0, 0.7, True)])
    assert gap_alert(strong) and "a:" in gap_alert(strong)[0]


def test_tag_counts():
    c = tag_counts([ep("a", 0, 0, False)], attribute=lambda e: [{"regret": 0.1, "tags": ["decoy_chase"]}])
    assert c["a"]["decoy_chase"] == 1 and abs(c["a#regret"]["decoy_chase"] - 0.1) < 1e-9
