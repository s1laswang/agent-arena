import os

os.environ["GEMINI_API_KEY"] = ""

import pytest

from agents import ladder


@pytest.fixture(scope="module")
def t():
    return {r["team"]: r for r in ladder.table(days=10, start=1000, seat=None, jobs=4)}


def test_monotone(t):
    means = [t["ladder%d" % i]["mean"] for i in range(len(ladder.RULES))]
    assert means == sorted(means) and means[0] < means[-1]


def test_top_matches_reference_and_beats_lower(t):
    top, ref = t["ladder%d" % ladder.TOP], t["reference"]
    assert top["mean"] >= ref["mean"] - ref["ci"]
    for i in range(ladder.TOP):
        assert t["ladder%d" % i]["mean"] < top["mean"] or i == 0 and top["mean"] > 0


def test_context_order(t):
    assert t["do_nothing"]["mean"] <= t["trust_all"]["mean"] + 1e-9 < t["reference"]["mean"] <= t["oracle"]["mean"]
