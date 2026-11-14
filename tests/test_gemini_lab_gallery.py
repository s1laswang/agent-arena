"""Failure gallery: keyless. The decomposition of every episode's gap (solver score - agent score) onto steps and
explicit categories must sum to the gap exactly, using a faithful replay of the recorded actions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from canary.gemini.atlas_data import load_run
from canary.gemini.gallery import CATEGORIES, decompose, replay_accounting, solver_episodes

ROOT = Path(__file__).resolve().parents[1]
RUNS = [(ROOT / "data/runs/committed/v1.3/codex-gpt-5.5-full/hard", "v1.3"),
        (ROOT / "data/runs/committed/v1.3/codex-gpt-5.5-full/medium", "v1.3"),
        (ROOT / "data/runs/committed/codex-gpt-5.5/medium", "v1.2")]


@pytest.fixture(scope="module")
def cases():
    refs = solver_episodes([ROOT / "data/runs/committed"])
    out = []
    for d, v in RUNS:
        raw = [json.loads(x) for x in (d / "episodes.jsonl").read_text().splitlines() if x.strip()]
        for ep in load_run(d):
            e = next(x for x in raw if x["seed"] == ep.seed and x["tier"] == ep.tier)
            se = refs[(v, ep.tier, ep.seed)]
            out.append((ep, e, se, v))
    return out


def test_replay_is_faithful(cases):
    for ep, e, se, v in cases:
        a = replay_accounting(e, v)
        assert a["faithful"], (ep.seed, a["mismatched_results"])
        assert a["score"] == pytest.approx(e["score"])
        assert replay_accounting(se, v)["faithful"]


def test_categories_sum_to_the_gap_for_every_episode(cases):
    kinds = set()
    for ep, e, se, v in cases:
        a, s = replay_accounting(e, v), replay_accounting(se, v)
        d = decompose(ep, a, s, se)
        assert d["gap"] == pytest.approx(float(se["score"]) - float(e["score"]), abs=1e-9)
        assert abs(sum(i["value"] for i in d["items"]) - d["gap"]) < 1e-6, (ep.seed, d)
        for i in d["items"]:
            assert i["category"] in CATEGORIES
            kinds.add(i["category"])
    # the sample covers a wrong accusation and canary spend at least
    assert any(k.startswith("wrong_accusation") for k in kinds)
    assert "excess_canary_spend" in kinds or "fewer_canaries_credit" in kinds


def test_wrong_accusation_is_attributed_to_the_accuse_step(cases):
    for ep, e, se, v in cases:
        if e.get("accused") and not e.get("correct"):
            d = decompose(ep, replay_accounting(e, v), replay_accounting(se, v), se)
            acc_t = [s.t for s in ep.steps if s.tool == "accuse"][-1]
            wrong = [i for i in d["items"] if i["category"].startswith("wrong_accusation")]
            assert wrong and wrong[0]["t"] == acc_t
            return
    pytest.skip("no wrong accusation in the sample")


def test_mcp_wrapped_error_counts_as_the_same_result():
    from canary.gemini.gallery import same_result
    rep = {"ok": False, "data": {}, "error": "invalid arguments"}
    rec = {"ok": False, "error": json.dumps(rep)}
    assert same_result(rec, rep)
    assert not same_result({"ok": False, "error": json.dumps({"ok": False, "error": "unknown employee"})}, rep)
    assert not same_result({"ok": True, "data": {}}, rep)


def test_harness_artifacts_are_recognised():
    from canary.gemini.gallery import harness_artifact
    assert harness_artifact({"raw": "...62295 bytes truncated..."})
    assert harness_artifact({"ok": False, "error": "Model tried to call unavailable tool 'invalid'."})
    assert not harness_artifact({"ok": False, "data": {}, "error": "invalid arguments"})
