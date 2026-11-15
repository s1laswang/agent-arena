"""Tests for v1.4 Mole strategy benchmark, hall_of_fame_v1.4.jsonl, and fairness_audit gates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import forge_track
from canary.env import Env
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.fairness_audit import CHECK_NAMES, audit_hof
from scripts.benchmark_mole_strategies import (
    BUILTIN_V14_CANDIDATES,
    HOF_KEYS,
    discover_library_candidates,
    evaluate_suite,
    parse_seed_spec,
    select_hof_survivors,
    validate_benchmark_seeds,
    write_hof_v14,
)

HOF_V14 = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
META_V14 = ROOT / "data" / "forge" / "hall_of_fame_v1.4.meta.json"


def _load_hof_rows() -> list[dict]:
    assert HOF_V14.is_file()
    lines = [ln for ln in HOF_V14.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 3
    return [json.loads(ln) for ln in lines]


def test_hof_v14_schema_and_meta(monkeypatch):
    rows = _load_hof_rows()
    assert META_V14.is_file()
    meta = json.loads(META_V14.read_text(encoding="utf-8"))

    assert meta["tiers_version"] == "v1.4"
    assert meta["tier"] == "hard"
    assert meta["n_survivors"] == len(rows)

    dev_seeds = parse_seed_spec(meta["dev_seeds"]) if meta.get("dev_seeds") else None
    heldout_seeds = parse_seed_spec(meta["heldout_seeds"])
    validate_benchmark_seeds(dev_seeds, heldout_seeds)

    dev_by_name = {c["name"]: c for c in (meta.get("dev_candidates") or [])}
    heldout_by_name = {c["name"]: c for c in meta["heldout_candidates"]}
    for sname in meta["survivor_names"]:
        assert heldout_by_name[sname]["all_gates_passed"] is True
        if dev_by_name:
            assert dev_by_name[sname]["all_gates_passed"] is True

    for idx, row in enumerate(rows, start=1):
        assert list(row.keys()) == HOF_KEYS
        assert row["rank"] == idx
        assert float(row["fitness"]) > 0.0
        assert float(row["solver_acc"]) >= 0.85
        assert float(row["solver_score"]) >= 0.25

        per_inv = row["per_investigator"]
        for req_inv in ("grok_tactics", "heuristic", "hinted_heuristic"):
            assert req_inv in per_inv
            assert {"score", "acc", "regret"} <= set(per_inv[req_inv].keys())

        sj = row["strategy_json"]
        norm = validate_strategy(sj)
        parsed = MoleStrategy.from_json(norm)
        assert 1 <= len(parsed.rules) <= MAX_RULES
        c1 = canonical(parsed.to_json())
        assert MoleStrategy.from_json(json.loads(c1)) == parsed
        for rule in sj["rules"]:
            assert is_valid_rule_conds(rule["if"], "hard")

    loaded_rows, loaded_strats = forge_track.load(HOF_V14)
    assert len(loaded_rows) == len(rows)
    assert len(loaded_strats) == len(rows)

    monkeypatch.setenv("CANARY_FORGE_HOF", str(HOF_V14))
    env = Env("hard_forge", 105)
    assert env.p.name == "hard"
    assert env._world.mole_strategy in loaded_strats


def test_hof_v14_distinct_behavior_and_outcome_hashes():
    rows = _load_hof_rows()
    meta = json.loads(META_V14.read_text(encoding="utf-8"))

    default_bh = behavior_hash(DEFAULT_STRATEGY.to_json(), "hard")
    hof_bhashes = [behavior_hash(r["strategy_json"], "hard") for r in rows]
    assert len(set(hof_bhashes)) == len(rows)
    assert default_bh not in hof_bhashes

    meta_bhashes = list(meta["survivor_behavior_hashes"].values())
    assert meta_bhashes == hof_bhashes

    default_oh = meta["default_heldout"]["outcome_hash"]
    meta_ohashes = list(meta["survivor_outcome_hashes"].values())
    assert len(set(meta_ohashes)) == len(rows)
    assert default_oh not in meta_ohashes


@pytest.mark.parametrize(
    "bad_dev,bad_heldout",
    [
        ([0, 10000], [6200, 6201]),
        ([29, 10000], [6200, 6201]),
        ([30, 10000], [6200, 6201]),
        ([49, 10000], [6200, 6201]),
        ([59, 10000], [6200, 6201]),
        ([-1, 10000], [6200, 6201]),
        ([30000, 10000], [6200, 6201]),
        ([10000, 10001], [30199, 6200]),
        ([10000, 10001], [800000, 6200]),
        ([900000, 10000], [6200, 6201]),
        ([6200, 10000], [6200, 6201]),
    ],
)
def test_seed_hygiene_rejects_forbidden_ranges(bad_dev, bad_heldout):
    with pytest.raises(ValueError):
        validate_benchmark_seeds(bad_dev, bad_heldout)


def test_seed_spec_parsing_and_valid_ranges():
    assert parse_seed_spec("10000-10002") == [10000, 10001, 10002]
    assert parse_seed_spec("6200:6203") == [6200, 6201, 6202]
    assert parse_seed_spec("60,61,62") == [60, 61, 62]
    validate_benchmark_seeds(parse_seed_spec("10000-10019"), parse_seed_spec("6200-6219"))

    lib_cands = discover_library_candidates()
    assert len(lib_cands) >= 6
    assert "surgical_trap_shield" in {c["name"] for c in lib_cands}


def test_hof_v14_passes_fairness_audit():
    rep = audit_hof(
        HOF_V14,
        tier="hard",
        seeds=range(6200, 6208),
        min_solver_acc=0.85,
        max_logs_acc=0.10,
    )
    assert rep["n_strategies"] >= 3
    assert rep["n_passed"] == rep["n_strategies"]
    assert rep["n_fairness_passed"] == rep["n_strategies"]
    assert rep["fairness_passed"] is True
    assert rep["all_passed"] is True

    for strat_rep in rep["strategies"]:
        for cname in CHECK_NAMES:
            assert strat_rep["checks"][cname]["passed"] is True, (strat_rep["rank"], cname, strat_rep["checks"][cname])
        assert strat_rep["checks"]["solver_beatable"]["solver_acc"] >= 0.85
        assert strat_rep["checks"]["logs_only_bounded"]["logs_only_acc"] <= 0.10
        assert strat_rep["checks"]["logs_only_bounded"]["accuse_most_logs_acc"] <= 0.10
        assert strat_rep["checks"]["regret_gain"]["regret_gain"] > 0.0


def test_benchmark_dedupe_and_writer_smoke(tmp_path):
    c1 = dict(BUILTIN_V14_CANDIDATES[0])
    c1_dup = {
        "name": "two_wave_blackout_clone",
        "description": "Exact duplicate strategy JSON for deduplication test.",
        "strategy_json": c1["strategy_json"],
    }
    c2 = dict(BUILTIN_V14_CANDIDATES[5])
    ev = evaluate_suite(
        [c1, c1_dup, c2],
        seeds=[6250, 6251],
        tier="hard",
        investigators=("grok_tactics", "heuristic", "hinted_heuristic"),
        workers=1,
        min_solver_acc=0.50,
        min_solver_ratio=0.30,
        max_logs_acc=0.50,
    )
    hof_rows, ranked = select_hof_survivors(ev, top_k=4)
    assert 1 <= len(hof_rows) <= 2
    assert len({r["outcome_hash"] for r in ranked}) == len(ranked)
    assert len({r["behavior_hash"] for r in ranked}) == len(ranked)

    out_hof = tmp_path / "hof_test.jsonl"
    meta_out = write_hof_v14(hof_rows, out_hof, {"tier": "hard", "tiers_version": "v1.4"})
    assert out_hof.is_file()
    assert meta_out.is_file()
    written = [json.loads(ln) for ln in out_hof.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(written) == len(hof_rows)
    assert all(list(w.keys()) == HOF_KEYS for w in written)
