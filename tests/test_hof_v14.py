from __future__ import annotations

import ast
from dataclasses import asdict
import json
from pathlib import Path
import random

import pytest

from canary import forge_track
from canary.baselines import DoNothing
from canary.env import Env
from canary.eval import run_episode
from canary.mole.dsl import MoleStrategy
from canary.mole.hof_v14 import (
    HOF_KEYS,
    HOF_V14_META_PATH,
    HOF_V14_PATH,
    behavioral_diversity_report,
    decision_vector,
    empirical_archetypes,
    load_hof_v14,
    load_hof_v14_meta,
    main,
    outcome_hash_v14,
    pairwise_view_disagreement,
    select_diverse_survivors,
    strategy_for_v14,
    verify_hof_v14_artifacts,
)
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[1]


def test_hygiene_and_zero_social_imports():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    rels = (
        "canary/mole/hof_v14.py",
        "data/forge/hall_of_fame_v1.4.jsonl",
        "data/forge/hall_of_fame_v1.4.meta.json",
        "tests/test_hof_v14.py",
    )
    for rel in rels:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert hash_ch not in txt, rel
        assert em_dash not in txt, rel
        assert en_dash not in txt, rel
        assert all(ord(ch) < 128 for ch in txt), rel

    tree = ast.parse((ROOT / "canary/mole/hof_v14.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "social" not in node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "social" not in alias.name


def test_committed_v14_hof_artifacts_and_cli(capsys):
    rows, strats = load_hof_v14()
    meta = load_hof_v14_meta()
    assert len(rows) >= 3
    assert len(rows) == len(strats) == meta["n_survivors"]
    for row in rows:
        assert tuple(row.keys()) == HOF_KEYS
        assert row["solver_acc"] >= 0.85
        assert row["fitness"] > 0.0

    rep = verify_hof_v14_artifacts()
    assert rep["ok"] is True
    assert rep["n_strategies"] == len(rows)
    assert rep["min_recorded_solver_acc"] >= 0.85
    assert rep["diversity"]["all_behavior_hashes_unique"] is True
    assert rep["diversity"]["all_outcome_hashes_unique"] is True
    assert rep["diversity"]["min_pairwise_view_disagreement"] >= 0.15

    rc = main(["verify"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["n_strategies"] == len(rows)


def test_empirical_archetypes_diversity_and_dedupe():
    archs = empirical_archetypes("hard")
    assert len(archs) >= 8
    seen_names = set()
    for name, sj in archs:
        seen_names.add(name)
        ms = MoleStrategy.from_json(sj)
        vec = decision_vector(ms, "hard")
        assert len(vec) == 64
    assert "non_decoy_tiebreak_framer" in seen_names
    assert "late_horizon_stall_hybrid" in seen_names

    s0 = archs[0][1]
    s1 = archs[-1][1]
    assert pairwise_view_disagreement(s0, s0, "hard") == 0.0
    assert pairwise_view_disagreement(s0, s1, "hard") > 0.0

    cands = [
        {"strategy_json": s0, "fitness": 0.10, "solver_acc": 0.90, "solver_score": 0.50, "outcome_hash": "oh_a"},
        {"strategy_json": s0, "fitness": 0.22, "solver_acc": 0.95, "solver_score": 0.58, "outcome_hash": "oh_a"},
        {"strategy_json": s1, "fitness": 0.18, "solver_acc": 0.92, "solver_score": 0.55, "outcome_hash": "oh_a"},
        {"strategy_json": s1, "fitness": 0.19, "solver_acc": 0.93, "solver_score": 0.56, "outcome_hash": "oh_b"},
    ]
    picked = select_diverse_survivors(cands, max_survivors=5, tier="hard", min_view_disagreement=0.10)
    assert len(picked) == 2
    assert picked[0]["fitness"] == 0.22
    div = behavioral_diversity_report(picked, tier="hard", outcome_hashes_by_rank={1: "oh_a", 2: "oh_b"})
    assert div["all_behavior_hashes_unique"] is True
    assert div["all_outcome_hashes_unique"] is True


def test_seed_hygiene_and_hard_forge_env_integration(monkeypatch):
    _, strats = load_hof_v14()
    sj0 = strats[0].to_json()
    with pytest.raises(ValueError, match="prohibited seed"):
        outcome_hash_v14(sj0, tier="hard", seeds=[0])

    h1 = outcome_hash_v14(sj0, tier="hard", seeds=[6000], agents=("do_nothing",))
    h2 = outcome_hash_v14(sj0, tier="hard", seeds=[6000], agents=("do_nothing",))
    assert h1 == h2 and len(h1) == 16

    monkeypatch.setenv("CANARY_FORGE_HOF", str(HOF_V14_PATH))
    forge_track._cache.clear()

    picked = [strategy_for_v14(s) for s in range(6000, 6030)]
    assert len({id(x) for x in picked}) >= 3

    a = Env("hard_forge", 6300)
    b = Env("hard_forge", 6300)
    dn_a = run_episode(a, DoNothing(seed=6300))
    dn_b = run_episode(b, DoNothing(seed=6300))
    assert dn_a.score == 0.0 and dn_b.score == 0.0
    assert [asdict(ev) for ev in a.ledger()] == [asdict(ev) for ev in b.ledger()]

    sol_env = Env("hard_forge", 6301)
    sol_res = run_episode(sol_env, SolverPolicy("hard"))
    assert sol_res.correct is True
    assert sol_res.score > 0.25
    for step in sol_env.history:
        blob = json.dumps(step.result)
        assert "strategy_json" not in blob
        assert "most_recipients" not in blob


def test_verify_rejects_corrupt_hof(tmp_path: Path):
    rows, _ = load_hof_v14()
    meta = load_hof_v14_meta()
    bad_hof = tmp_path / "bad.jsonl"
    bad_meta = tmp_path / "bad.meta.json"
    bad_rows = [dict(r) for r in rows]
    bad_rows[0] = dict(bad_rows[0], solver_acc=0.50)
    bad_hof.write_text("".join(json.dumps(r) + "\n" for r in bad_rows), encoding="utf-8")
    bad_meta.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="solver_acc"):
        verify_hof_v14_artifacts(hof_path=bad_hof, meta_path=bad_meta)
