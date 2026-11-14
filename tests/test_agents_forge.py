import json
import math

import pytest

from canary.forge import evolve as E
from canary.forge.fitness import evaluate, fake_factory, fake_runner, solver_baseline
from canary.forge.mutate import (DEFAULT_STRATEGY_JSON, LLMMutator, StubMutator, _local_validate, canonical,
                                 validate_strategy)
from canary.llm.stub import StubClient

INV = {"heuristic": fake_factory, "hinted_heuristic": fake_factory}


def test_stub_mutator_always_valid():
    for seed in range(40):
        m = StubMutator(seed)
        parents = [{"strategy_json": DEFAULT_STRATEGY_JSON, "fitness": None, "beaten_tags": []}]
        for _ in range(8):
            kids = m.propose(parents, 6)
            assert len(kids) == 6
            for k in kids:
                assert _local_validate(k) == k and len(k["rules"]) <= 12
            parents = [{"strategy_json": k, "fitness": 0.1, "beaten_tags": []} for k in kids]


def test_stub_mutator_deterministic():
    p = [{"strategy_json": DEFAULT_STRATEGY_JSON, "fitness": None, "beaten_tags": []}]
    assert StubMutator(3).propose(p, 10) == StubMutator(3).propose(p, 10)
    assert StubMutator(3).propose(p, 10) != StubMutator(4).propose(p, 10)


@pytest.mark.parametrize("bad", [
    {"rules": [{"if": [["nope", "<", 1]], "then": {"leak": "newest", "frame": None}}], "default": {"leak": None, "frame": None}},
    {"rules": [{"if": [["day", "~", 1]], "then": {"leak": "newest", "frame": None}}], "default": {"leak": None, "frame": None}},
    {"rules": [], "default": {"leak": "exec('x')", "frame": None}},
    {"rules": [{"if": [["day", "<", 1]], "then": {"leak": "newest", "frame": None}}] * 13, "default": {"leak": None, "frame": None}},
])
def test_validator_rejects(bad):
    with pytest.raises(ValueError):
        validate_strategy(bad)


def test_llm_mutator_drops_invalid_and_backfills():
    good = {"rules": [{"if": [["day", ">", "3"]], "then": {"leak": "oldest", "frame": "decoy"}}],
            "default": {"leak": "newest", "frame": "none"}}
    bad = {"rules": [{"if": [["evil", ">", "3"]], "then": {"leak": "oldest", "frame": "decoy"}}],
           "default": {"leak": "newest", "frame": "none"}}
    client = StubClient(script=[{"json": {"children": [good, bad]}}])
    m = LLMMutator(client, seed=1)
    kids = m.propose([{"strategy_json": DEFAULT_STRATEGY_JSON, "fitness": 0.2, "beaten_tags": ["late_accuse"]}], 3)
    assert len(kids) == 3 and kids[0]["rules"][0]["if"][0] == ["day", ">", 3]
    assert m.n_valid == 1 and m.n_invalid == 1
    prompt = client.calls[0]["messages"][1]["content"]
    assert "late_accuse" in prompt and client.calls[0]["response_schema"] is not None
    # schema_example output (no script) must not crash
    assert len(LLMMutator(StubClient(), seed=1).propose([], 2)) == 2


def test_feasibility_rejects_unsolvable():
    never_leak = {"rules": [], "default": {"leak": None, "frame": "decoy"}}
    r = evaluate(never_leak, INV, fake_factory, range(10), "hard", runner=fake_runner)
    assert not r["feasible"] and r["fitness"] == -math.inf
    framed = {"rules": [], "default": {"leak": "fewest_recipients", "frame": "decoy"}}
    r = evaluate(framed, INV, fake_factory, range(10), "hard", runner=fake_runner, workers=2)
    assert r["feasible"] and math.isfinite(r["fitness"]) and r["fitness"] > 0
    base = solver_baseline(fake_factory, range(10), "hard", fake_runner)
    assert r["baseline_solver_score"] == base["score"]


def test_negative_scores_counted():
    # heuristics that accuse wrongly score -1, which must raise regret above solver score
    s = {"rules": [{"if": [["day", ">", 0]], "then": {"leak": "oldest", "frame": "decoy"}}] * 6,
         "default": {"leak": "fewest_recipients", "frame": "random_peer"}}
    r = evaluate(validate_strategy(s), INV, fake_factory, range(20), "hard", runner=fake_runner)
    assert min(v["score"] for v in r["per_investigator"].values()) < 0
    assert r["regret"] > r["solver_score"]


def _run(tmp, gens=3, **kw):
    return E.run("stub", "hard", pop_size=6, gens=gens, seeds=range(5), workers=1, out=tmp, fake=True,
                 seed=7, log=lambda *_: None, **kw)


def test_evolve_fake_writes_files_and_is_deterministic(tmp_path):
    _run(tmp_path / "a")
    _run(tmp_path / "b")
    la = (tmp_path / "a/log.jsonl").read_text().splitlines()
    lb = (tmp_path / "b/log.jsonl").read_text().splitlines()
    assert len(la) == 3
    strip = lambda ls: [{k: v for k, v in json.loads(l).items() if k != "seconds"} for l in ls]
    assert strip(la) == strip(lb)
    line = json.loads(la[-1])
    assert {"best_fitness", "mean_fitness", "feasible_share", "best_strategy"} <= set(line)
    hof = [json.loads(l) for l in (tmp_path / "a/hall_of_fame.jsonl").read_text().splitlines()]
    assert hof and len({canonical(h["strategy_json"]) for h in hof}) == len(hof)
    assert all(h["fitness"] >= hof[-1]["fitness"] for h in hof)
    assert json.loads(la[-1])["best_fitness"] >= json.loads(la[0])["best_fitness"]  # elitism


def test_evolve_resume_matches_uninterrupted(tmp_path):
    _run(tmp_path / "full", gens=4)
    _run(tmp_path / "part", gens=2)
    _run(tmp_path / "part", gens=4)
    strip = lambda p: [{k: v for k, v in json.loads(l).items() if k != "seconds"}
                       for l in p.read_text().splitlines()]
    assert strip(tmp_path / "full/log.jsonl") == strip(tmp_path / "part/log.jsonl")


def test_cli_fake(tmp_path, capsys):
    assert E.main(["--fake", "--gens", "2", "--pop", "4", "--seeds", "0-3", "--workers", "1",
                   "--out", str(tmp_path)]) == 0
    assert (tmp_path / "log.jsonl").exists() and (tmp_path / "hall_of_fame.jsonl").exists()
