from canary.analysis.gallery import build, check, md


def ep(seed, score, agent="a"):
    return {"tier": "hard", "seed": seed, "agent": agent, "score": score, "steps": [{"t": 0, "day": 1, "tool": "accuse", "args": {"employee": "e01"}, "result": {}}]}


def attr(res):
    return [{"t": 0, "day": 1, "action": "accuse", "regret": 0.5 + res.seed, "p_best": 0.3, "tags": ["premature_accusation"] if res.seed < 2 else []}]


def test_gallery_and_check():
    g = build([ep(0, 0.0), ep(1, 0.0), ep(2, 1.0), ep(3, 0.0)], attr)
    assert g["losses"] == 3 and len(g["unlabelled_losses"]) == 1
    x = g["labels"][0]
    assert x["label"] == "premature_accusation" and x["count"] == 2 and x["example"]["seed"] == 1
    assert any("loss without a label" in p for p in check(g))
    assert "premature_accusation" in md(g)


def test_clean():
    g = build([ep(0, 0.0), ep(2, 1.0)], attr)
    assert check(g) == []
