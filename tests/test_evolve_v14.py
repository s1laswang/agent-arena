from __future__ import annotations

import json
import math

import pytest

from canary import forge_track
from canary.forge.fitness import SOLVER_NAME, fake_factory
from canary.forge.mutate import FRAME_SELECTORS, LEAK_SELECTORS, canonical, validate_strategy
from canary.mole.dsl import MoleStrategy, MoleView
from canary.mole.evolve_v14 import (
    DEFAULT_HOLDOUT_SEEDS,
    DEFAULT_MIN_SOLVER_ACC,
    DEFAULT_TRAIN_SEEDS,
    V14Mutator,
    behavior_hash,
    dedupe_by_behavior,
    evaluate_v14,
    generation_seed_batch,
    is_valid_rule_conds,
    main,
    rank_holdout_hof,
    representative_views,
    run_j5c,
    tier_feature_ranges,
    v14_fake_investigators,
    v14_fake_runner,
    v14_investigators,
    validate_seed_hygiene,
)
from canary.rules import tiers_version


def test_v14_feature_ranges_and_tier_param_scaling():
    hard_ranges = tier_feature_ranges("hard")
    assert hard_ranges["day"] == (1, 21)
    assert hard_ranges["days_since_last_leak"] == (1, 21)
    assert hard_ranges["max_recipient_count"] == (1, 40)

    med_ranges = tier_feature_ranges("medium")
    assert med_ranges["day"] == (1, 14)
    assert med_ranges["max_recipient_count"] == (1, 20)

    with tiers_version("v1.3"):
        v13_ranges = tier_feature_ranges("hard")
        assert v13_ranges["day"] == (1, 14)
        assert v13_ranges["max_recipient_count"] == (1, 30)


def test_v14_mutator_explores_v14_ranges_without_dead_or_contradictory_conds():
    assert not is_valid_rule_conds([["n_restricted_colleagues", "<", 0]], "hard")
    assert not is_valid_rule_conds([["day", "<", 1]], "hard")
    assert not is_valid_rule_conds([["day", ">", 21]], "hard")
    assert not is_valid_rule_conds([["day", ">=", 1]], "hard")
    assert not is_valid_rule_conds([["max_recipient_count", "<=", 40]], "hard")
    assert not is_valid_rule_conds(
        [["days_since_last_leak", "<=", 1], ["days_since_last_leak", "!=", 10]],
        "hard",
    )
    assert not is_valid_rule_conds([["day", ">", 15], ["day", "<", 10]], "hard")
    assert not is_valid_rule_conds([["day", "<", 5], ["days_since_last_leak", ">", 8]], "hard")
    assert not is_valid_rule_conds(
        [["min_recipient_count", ">", 20], ["max_recipient_count", "<", 10]],
        "hard",
    )
    assert not is_valid_rule_conds([["n_leakable", "<", 2], ["n_docs_held", ">", 5]], "hard")
    assert is_valid_rule_conds([["day", ">=", 16], ["max_recipient_count", "<=", 38]], "hard")

    seen_late_days = False
    seen_wide_recipients = False
    for seed in range(25):
        mut = V14Mutator(seed=seed, tier="hard")
        parents = [{"strategy_json": {"rules": [], "default": {"leak": "random_seeded", "frame": "none"}}}]
        for _ in range(6):
            kids = mut.propose(parents, 6)
            assert len(kids) == 6
            for k in kids:
                assert validate_strategy(k) == k
                MoleStrategy.from_json(k)
                branches = [r["then"] for r in k["rules"]] + [k["default"]]
                assert any(b.get("leak") not in (None, "none") for b in branches)
                for r in k["rules"]:
                    assert is_valid_rule_conds(r["if"], "hard")
                    for f, _, val in r["if"]:
                        if f == "day" and val >= 15:
                            seen_late_days = True
                        if f == "max_recipient_count" and val >= 31:
                            seen_wide_recipients = True
            parents = [{"strategy_json": k, "fitness": 0.2, "beaten_tags": []} for k in kids]

    assert seen_late_days
    assert seen_wide_recipients

    dirty = {
        "rules": [
            {
                "if": [["n_restricted_colleagues", "<", 0], ["max_recipient_count", "<=", 14]],
                "then": {"leak": "none", "frame": "none"},
            },
            {
                "if": [["days_since_last_leak", "<=", 1], ["days_since_last_leak", "!=", 10]],
                "then": {"leak": "none", "frame": "none"},
            },
        ],
        "default": {"leak": "none", "frame": "none"},
    }
    cleaned = V14Mutator(seed=1, tier="hard").mutate(dirty)
    for r in cleaned["rules"]:
        assert is_valid_rule_conds(r["if"], "hard")
    all_branches = [r["then"] for r in cleaned["rules"]] + [cleaned["default"]]
    assert any(b.get("leak") not in (None, "none") for b in all_branches)


def test_behavior_hash_64_views_collapses_clones_and_separates_distinct():
    views = representative_views("hard")
    assert len(views) == 64
    assert all(isinstance(v, MoleView) for v in views)

    base = {"rules": [], "default": {"leak": "newest", "frame": "decoy"}}
    dead_cond = {
        "rules": [{"if": [["day", "<", 0]], "then": {"leak": "oldest", "frame": "none"}}],
        "default": {"leak": "newest", "frame": "decoy"},
    }
    tautology = {
        "rules": [{"if": [["day", ">=", 1]], "then": {"leak": "newest", "frame": "decoy"}}],
        "default": {"leak": "oldest", "frame": "none"},
    }
    noop_rule = {
        "rules": [{"if": [["day", "<=", 10]], "then": {"leak": "newest", "frame": "decoy"}}],
        "default": {"leak": "newest", "frame": "decoy"},
    }
    bh_base = behavior_hash(base, "hard")
    assert behavior_hash(base, "hard") == bh_base
    assert behavior_hash(dead_cond, "hard") == bh_base
    assert behavior_hash(tautology, "hard") == bh_base
    assert behavior_hash(noop_rule, "hard") == bh_base

    lt8 = {
        "rules": [{"if": [["day", "<", 8]], "then": {"leak": "oldest", "frame": "decoy"}}],
        "default": {"leak": "newest", "frame": "none"},
    }
    le7 = {
        "rules": [{"if": [["day", "<=", 7]], "then": {"leak": "oldest", "frame": "decoy"}}],
        "default": {"leak": "newest", "frame": "none"},
    }
    shadowed = {
        "rules": [
            {"if": [["day", "<", 8]], "then": {"leak": "oldest", "frame": "decoy"}},
            {"if": [["day", "<", 4]], "then": {"leak": "fewest_recipients", "frame": "random_peer"}},
        ],
        "default": {"leak": "newest", "frame": "none"},
    }
    assert behavior_hash(lt8, "hard") == behavior_hash(le7, "hard") == behavior_hash(shadowed, "hard")

    default_hashes = {
        behavior_hash({"rules": [], "default": {"leak": lk, "frame": fr}}, "hard")
        for lk in LEAK_SELECTORS
        for fr in FRAME_SELECTORS
    }
    assert len(default_hashes) == len(LEAK_SELECTORS) * len(FRAME_SELECTORS)

    day_split_hashes = {
        behavior_hash(
            {
                "rules": [{"if": [["day", "<=", d]], "then": {"leak": "oldest", "frame": "decoy"}}],
                "default": {"leak": "newest", "frame": "none"},
            },
            "hard",
        )
        for d in range(1, 21)
    }
    assert len(day_split_hashes) == 20


def test_rotating_seed_schedule_and_seed_hygiene():
    assert list(DEFAULT_TRAIN_SEEDS) == list(range(200, 600))
    assert list(DEFAULT_HOLDOUT_SEEDS) == list(range(6200, 6240))

    batches = [generation_seed_batch(DEFAULT_TRAIN_SEEDS, 24, seed=11, gen=g) for g in range(16)]
    assert all(len(b) == 24 for b in batches)
    union_16 = set().union(*batches)
    assert len(union_16) == 16 * 24

    more_batches = [generation_seed_batch(DEFAULT_TRAIN_SEEDS, 24, seed=11, gen=g) for g in range(40)]
    for g in range(1, 40):
        assert set(more_batches[g]) != set(more_batches[g - 1])
    assert generation_seed_batch(DEFAULT_TRAIN_SEEDS, 24, seed=11, gen=9) == more_batches[9]

    for bad_train, bad_holdout in [
        ([0, 1, 2], [6200, 6201]),
        ([29, 200], [6200, 6201]),
        ([-1, 200], [6200, 6201]),
        ([200, 201], [900000, 900001]),
        ([200, 201], [800000, 800001]),
        ([200, 201, 202], [202, 6200]),
    ]:
        with pytest.raises(ValueError):
            validate_seed_hygiene(bad_train, bad_holdout)


class _CosmeticCloneMutator:
    name = "clone_test"

    def reseed(self, gen: int) -> None:
        self.gen = gen

    def propose(self, parents: list[dict], n: int) -> list[dict]:
        out = []
        for idx in range(n):
            d = 100 + idx
            out.append(
                validate_strategy(
                    {
                        "rules": [{"if": [["day", ">", d]], "then": {"leak": "oldest", "frame": "decoy"}}],
                        "default": {"leak": "random_seeded", "frame": "none"},
                    }
                )
            )
        return out


def test_behavioral_deduplication_in_elites_and_hof(tmp_path):
    res = run_j5c(
        mutator_spec=_CosmeticCloneMutator(),
        tier="hard",
        pop_size=6,
        gens=3,
        train_seeds=range(200, 212),
        batch_size=4,
        holdout_seeds=range(6200, 6206),
        fake=True,
        seed=4,
        hof_k=10,
        out=tmp_path / "clones",
        log=lambda *_: None,
    )
    assert len(res["hof"]) == 1
    hof_lines = [json.loads(ln) for ln in (tmp_path / "clones/hall_of_fame.jsonl").read_text().splitlines()]
    assert len(hof_lines) == 1

    s_simple = validate_strategy({"rules": [], "default": {"leak": "newest", "frame": "decoy"}})
    s_bloated = validate_strategy(
        {
            "rules": [{"if": [["day", ">", 500]], "then": {"leak": "oldest", "frame": "none"}}],
            "default": {"leak": "newest", "frame": "decoy"},
        }
    )
    deduped = dedupe_by_behavior(
        [
            {"strategy_json": s_bloated, "fitness": 0.4},
            {"strategy_json": s_simple, "fitness": 0.4},
        ],
        "hard",
    )
    assert len(deduped) == 1
    assert deduped[0]["strategy_json"] == s_simple


def test_holdout_validation_ranks_strictly_by_out_of_sample_min_regret(tmp_path):
    s_overfit = validate_strategy(
        {
            "rules": [{"if": [["day", "<=", 10]], "then": {"leak": "oldest", "frame": "decoy"}}],
            "default": {"leak": "newest", "frame": "none"},
        }
    )
    s_general = validate_strategy(
        {
            "rules": [{"if": [["day", "<=", 14]], "then": {"leak": "most_recipients", "frame": "most_restricted_peer"}}],
            "default": {"leak": "fewest_recipients", "frame": "decoy"},
        }
    )
    bh_overfit = behavior_hash(s_overfit, "hard")
    bh_general = behavior_hash(s_general, "hard")
    assert bh_overfit != bh_general

    class _TwoCandidateMutator:
        name = "two_cand"

        def reseed(self, gen: int) -> None:
            pass

        def propose(self, parents: list[dict], n: int) -> list[dict]:
            pool = [s_overfit, s_general]
            return [pool[i % 2] for i in range(n)]

    def controlled_runner(tier: str, seed: int, strategy_json: dict, agent: str, factory=None):
        if agent == SOLVER_NAME:
            return 0.80, True
        bh = behavior_hash(strategy_json, tier)
        is_holdout = seed >= 6200
        if bh == bh_overfit:
            inv_score = 0.75 if is_holdout else 0.05
        elif bh == bh_general:
            inv_score = 0.35 if is_holdout else 0.50
        else:
            inv_score = 0.70
        return inv_score, True

    res = run_j5c(
        mutator_spec=_TwoCandidateMutator(),
        tier="hard",
        pop_size=4,
        gens=2,
        train_seeds=range(200, 208),
        batch_size=4,
        holdout_seeds=range(6200, 6206),
        runner=controlled_runner,
        investigators=v14_fake_investigators(),
        solver_factory=fake_factory,
        out=tmp_path / "holdout_rank",
        hof_k=5,
        log=lambda *_: None,
    )
    hof = res["hof"]
    assert len(hof) == 3
    by_bh = {h["behavior_hash"]: h for h in hof}
    assert hof[0]["behavior_hash"] == bh_general
    assert abs(hof[0]["min_regret"] - 0.45) < 1e-9
    assert by_bh[bh_general]["train_fitness"] < by_bh[bh_overfit]["train_fitness"]
    assert by_bh[bh_general]["min_regret"] > by_bh[bh_overfit]["min_regret"]
    assert [h["min_regret"] for h in hof] == sorted([h["min_regret"] for h in hof], reverse=True)


def test_solver_catchability_constraint_rejects_low_acc_and_low_score():
    assert set(v14_investigators()) == {"heuristic", "hinted_heuristic", "grok_tactics"}
    assert DEFAULT_MIN_SOLVER_ACC == 0.80

    never_leak = validate_strategy({"rules": [], "default": {"leak": "none", "frame": "decoy"}})
    dead_rule_leak = validate_strategy(
        {
            "rules": [{"if": [["day", "<", 0]], "then": {"leak": "newest", "frame": "none"}}],
            "default": {"leak": "none", "frame": "decoy"},
        }
    )
    for bad in (never_leak, dead_rule_leak):
        ev = evaluate_v14(
            bad,
            v14_fake_investigators(),
            fake_factory,
            range(200, 210),
            tier="hard",
            runner=v14_fake_runner,
        )
        assert not ev["feasible"] and ev["fitness"] == -math.inf

    s_acc75 = validate_strategy(
        {
            "rules": [{"if": [["day", "<=", 5]], "then": {"leak": "oldest", "frame": "decoy"}}],
            "default": {"leak": "newest", "frame": "none"},
        }
    )
    s_low_score = validate_strategy(
        {
            "rules": [{"if": [["day", "<=", 9]], "then": {"leak": "most_recipients", "frame": "decoy"}}],
            "default": {"leak": "newest", "frame": "none"},
        }
    )
    s_good = validate_strategy(
        {
            "rules": [{"if": [["day", "<=", 12]], "then": {"leak": "fewest_recipients", "frame": "decoy"}}],
            "default": {"leak": "random_seeded", "frame": "none"},
        }
    )
    bh_acc75 = behavior_hash(s_acc75, "hard")
    bh_low_score = behavior_hash(s_low_score, "hard")
    bh_good = behavior_hash(s_good, "hard")

    seeds = [6200, 6201, 6202, 6203]

    def catchability_runner(tier: str, seed: int, strategy_json: dict, agent: str, factory=None):
        bh = behavior_hash(strategy_json, tier)
        if agent == SOLVER_NAME:
            if bh == bh_acc75:
                return (0.80, True) if seed != 6203 else (-1.0, False)
            if bh == bh_low_score:
                return 0.30, True
            return 0.80, True
        return 0.20, True

    hof, base = rank_holdout_hof(
        [
            {"strategy_json": s_acc75, "train_fitness": 0.9},
            {"strategy_json": s_low_score, "train_fitness": 0.9},
            {"strategy_json": s_good, "train_fitness": 0.4},
        ],
        investigators=v14_fake_investigators(),
        solver_factory=fake_factory,
        holdout_seeds=seeds,
        tier="hard",
        runner=catchability_runner,
        hof_k=5,
    )
    assert abs(base["score"] - 0.80) < 1e-9
    assert [h["behavior_hash"] for h in hof] == [bh_good]


def test_fake_determinism_resume_and_cli(tmp_path):
    common = dict(
        mutator_spec="v14",
        tier="hard",
        pop_size=6,
        train_seeds=range(200, 224),
        batch_size=6,
        holdout_seeds=range(6200, 6208),
        fake=True,
        seed=17,
        elite=2,
        hof_k=5,
        log=lambda *_: None,
    )
    ra = run_j5c(gens=3, out=tmp_path / "a", **common)
    rb = run_j5c(gens=3, out=tmp_path / "b", **common)

    strip = lambda p: [
        {k: v for k, v in json.loads(ln).items() if k != "seconds"}
        for ln in p.read_text().splitlines()
    ]
    logs_a = strip(tmp_path / "a/log.jsonl")
    logs_b = strip(tmp_path / "b/log.jsonl")
    assert logs_a == logs_b
    assert len(logs_a) == 3
    assert logs_a[0]["seeds"] != logs_a[1]["seeds"] != logs_a[2]["seeds"]
    assert ra["hof"] == rb["hof"]
    assert len({h["behavior_hash"] for h in ra["hof"]}) == len(ra["hof"])

    run_j5c(gens=2, out=tmp_path / "resumed", **common)
    res_resumed = run_j5c(gens=3, out=tmp_path / "resumed", **common)
    assert strip(tmp_path / "resumed/log.jsonl") == logs_a
    assert res_resumed["hof"] == ra["hof"]

    cli_out = tmp_path / "cli"
    rc = main(
        [
            "--fake",
            "--gens",
            "2",
            "--pop",
            "5",
            "--train-seeds",
            "200-215",
            "--batch-size",
            "4",
            "--holdout-seeds",
            "6200-6205",
            "--workers",
            "1",
            "--out",
            str(cli_out),
        ]
    )
    assert rc == 0
    rows, strats = forge_track.load(cli_out / "hall_of_fame.jsonl")
    assert rows and len(rows) == len(strats)
    for row in rows:
        assert set(row["per_investigator"]) == {"grok_tactics", "heuristic", "hinted_heuristic"}
        assert row["solver_acc"] >= 0.80
        assert validate_strategy(MoleStrategy.from_json(row["strategy_json"]).to_json()) == row["strategy_json"]


def test_real_env_two_seed_smoke_with_workers(tmp_path):
    out_dir = tmp_path / "real_smoke"
    res = run_j5c(
        mutator_spec="v14",
        tier="hard",
        pop_size=2,
        gens=1,
        train_seeds=[200, 201],
        batch_size=2,
        holdout_seeds=[6200, 6202],
        workers=2,
        out=out_dir,
        fake=False,
        seed=3,
        hof_k=2,
        log=lambda *_: None,
    )
    assert (out_dir / "log.jsonl").exists()
    assert (out_dir / "hall_of_fame.jsonl").exists()
    hof = res["hof"]
    assert hof
    assert len({h["behavior_hash"] for h in hof}) == len(hof)
    for h in hof:
        assert set(h["per_investigator"]) == {"grok_tactics", "heuristic", "hinted_heuristic"}
        assert h["solver_acc"] >= 0.80
        assert h["solver_score"] >= 0.5 * h["baseline_solver_score"]
        expected_min = min(v["regret"] for v in h["per_investigator"].values())
        assert math.isfinite(h["fitness"]) and abs(h["fitness"] - expected_min) < 1e-9
