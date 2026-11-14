"""Mole Forge J5c v1.4 evolution runner with rotating training seeds, behavioral deduplication, and fresh holdout ranking.

python -m canary.mole.evolve_v14 --mutator v14 --tier hard --pop 16 --gens 20 \
    --train-seeds 200-599 --batch-size 24 --holdout-seeds 6200-6239 --workers 1 --out data/forge/j5c
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from canary.forge.evolve import parse_seeds
from canary.forge.fitness import (
    SOLVER_NAME,
    ClassFactory,
    default_solver_factory,
    evaluate,
    fake_factory,
    real_runner,
    solver_baseline,
)
from canary.forge.mutate import (
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    LLMMutator,
    MAX_CONDS,
    MAX_RULES,
    OPS,
    canonical,
    default_strategy_json,
    validate_strategy,
)
from canary.mole.dsl import FEATURES, OPS as DSL_OPS, MoleDoc, MoleStrategy, MoleView
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, tier_params

DEFAULT_TRAIN_SEEDS = range(200, 600)
DEFAULT_HOLDOUT_SEEDS = range(6200, 6240)
RESERVED_HELDOUT_EVAL_SEEDS = range(30_000, 30_200)
DEFAULT_BATCH_SIZE = 24
DEFAULT_MIN_SOLVER_ACC = 0.80
DEFAULT_MIN_SOLVER_RATIO = 0.5
FORBIDDEN_LOW_SEED_MAX = 29
REPRESENTATIVE_VIEW_COUNT = 64

_ACTIVE_LEAK_SELECTORS = [s for s in LEAK_SELECTORS if s != "none"]
_FEATURE_ALIAS = {"n_docs_held": "n_leakable"}
_VIEWS_CACHE: dict[tuple[Any, ...], tuple[MoleView, ...]] = {}
_PROFILE_CACHE: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}


def _tier_cache_key(tier: str) -> tuple[Any, ...]:
    p = tier_params(tier)
    return (
        tier,
        p.n_employees,
        p.n_days,
        p.leak_window_days,
        p.low_recipient_threshold,
        p.careful_mole,
        p.decoy,
        p.canaries_per_day,
        p.docs_per_day,
    )


def tier_feature_ranges(tier: str = "hard") -> dict[str, tuple[int, int]]:
    p = tier_params(tier)
    max_docs = max(4, p.leak_window_days * (max(p.docs_per_day) + p.canaries_per_day))
    min_rc_hi = max(2, (2 * p.n_employees) // 3)
    max_restricted = max(1, p.n_employees // 3)
    max_low_rc = max(2, p.leak_window_days * p.canaries_per_day + 2)
    return {
        "day": (1, p.n_days),
        "days_since_last_leak": (1, p.n_days),
        "i_am_restricted": (0, 1),
        "n_restricted_colleagues": (0, max_restricted),
        "recent_low_recipient_docs": (0, max_low_rc),
        "n_leakable": (0, max_docs),
        "n_docs_held": (0, max_docs),
        "min_recipient_count": (1, min_rc_hi),
        "max_recipient_count": (1, p.n_employees),
        "newest_doc_age_days": (0, max(1, p.leak_window_days)),
    }


def is_valid_cond(cond: Sequence[Any], ranges: dict[str, tuple[int, int]]) -> bool:
    if len(cond) != 3:
        return False
    f, op, val = cond[0], cond[1], cond[2]
    if f not in ranges or op not in DSL_OPS or isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    lo, hi = ranges[f]
    if val < lo or val > hi:
        return False
    fn = DSL_OPS[op]
    sat = sum(1 for x in range(lo, hi + 1) if fn(x, val))
    return 0 < sat < (hi - lo + 1)


def is_valid_rule_conds(conds: Sequence[Sequence[Any]], tier: str = "hard") -> bool:
    if not (1 <= len(conds) <= MAX_CONDS):
        return False
    ranges = tier_feature_ranges(tier)
    p = tier_params(tier)
    grouped: dict[str, list[set[int]]] = defaultdict(list)
    bounds: dict[str, tuple[int, int]] = {}
    for c in conds:
        if not is_valid_cond(c, ranges):
            return False
        f, op, val = c[0], c[1], c[2]
        cf = _FEATURE_ALIAS.get(f, f)
        lo, hi = ranges[cf]
        bounds[cf] = (lo, hi)
        fn = DSL_OPS[op]
        grouped[cf].append({x for x in range(lo, hi + 1) if fn(x, val)})

    allowed: dict[str, set[int]] = {}
    for cf, sets in grouped.items():
        lo, hi = bounds[cf]
        full_len = hi - lo + 1
        inter = set.intersection(*sets)
        if not (0 < len(inter) < full_len):
            return False
        if len(sets) > 1:
            for idx in range(len(sets)):
                others = set.intersection(*(sets[j] for j in range(len(sets)) if j != idx))
                if others == inter:
                    return False
        allowed[cf] = inter

    if "day" in allowed and "days_since_last_leak" in allowed:
        if not any(ds <= d for d in allowed["day"] for ds in allowed["days_since_last_leak"]):
            return False
    if "min_recipient_count" in allowed and "max_recipient_count" in allowed:
        if not any(mn <= mx for mn in allowed["min_recipient_count"] for mx in allowed["max_recipient_count"]):
            return False
    if "n_leakable" in allowed and "recent_low_recipient_docs" in allowed:
        if not any(rl <= nl for nl in allowed["n_leakable"] for rl in allowed["recent_low_recipient_docs"]):
            return False
    if "n_leakable" in allowed and allowed["n_leakable"] == {0}:
        if "min_recipient_count" in allowed or "max_recipient_count" in allowed:
            return False
        if "newest_doc_age_days" in allowed:
            for c in conds:
                if c[0] == "newest_doc_age_days" and not DSL_OPS[c[1]](99, c[2]):
                    return False
    if "min_recipient_count" in allowed and "recent_low_recipient_docs" in allowed:
        if min(allowed["min_recipient_count"]) > p.low_recipient_threshold and 0 not in allowed["recent_low_recipient_docs"]:
            return False
    return True


def representative_views(tier: str = "hard") -> tuple[MoleView, ...]:
    ck = _tier_cache_key(tier)
    if ck in _VIEWS_CACHE:
        return _VIEWS_CACHE[ck]
    p = tier_params(tier)
    n_emp = p.n_employees
    peers = tuple(f"e{k:02d}" for k in range(1, n_emp))
    decoy = "e01" if p.decoy and peers else None
    rpeer_pool = peers[1:] if len(peers) > 1 else peers
    max_restr = max(1, n_emp // 3)
    restr_cycle = (0, 1, 2, 3, 5, min(max_restr, 8), max_restr)
    doc_len_cycle = (4, 5, 6, 8, 11, 15)
    min_rc_cycle = (1, 2, 3, 4, 6, 9, 13, 18, max(2, (2 * n_emp) // 3 - 4))
    max_rc_fracs = (0.15, 0.25, 0.35, 0.50, 0.65, 0.78, 0.88, 0.95, 1.0)

    views: list[MoleView] = []
    for idx in range(60):
        day = (idx % p.n_days) + 1
        ds_choices = (1, 2, 3, max(1, day // 2), day)
        dsll = min(day, ds_choices[idx % len(ds_choices)])
        i_restr = 1 if idx % 4 == 3 else 0
        n_restr = min(len(rpeer_pool), restr_cycle[idx % len(restr_cycle)])
        rpeers = rpeer_pool[:n_restr]

        raw_min = min(n_emp - 3, min_rc_cycle[idx % len(min_rc_cycle)])
        min_rc = max(1, raw_min)
        scaled_max = max(min_rc + 3, int(round(n_emp * max_rc_fracs[idx % len(max_rc_fracs)])))
        max_rc = min(n_emp, scaled_max)
        if max_rc <= min_rc + 2:
            min_rc = max(1, max_rc - 3)
        mid1 = min_rc + max(1, (max_rc - min_rc) // 3)
        mid2 = min(max_rc - 1, mid1 + max(1, (max_rc - min_rc) // 3))

        max_age = max(1, p.leak_window_days - 1)
        if idx % 15 == 14:
            ages = (max_age, max_age, max_age, max_age)
        elif idx % 5 == 4 and max_age >= 2:
            ages = (1, max_age, 1, 1)
        else:
            mid_age = min(1, max_age)
            ages = (0, max_age, mid_age, mid_age)

        core_rcs = [mid1, mid2, max_rc, min_rc]
        target_len = doc_len_cycle[idx % len(doc_len_cycle)]
        docs_list = [
            MoleDoc(f"v{idx:02d}_d{j}", f"Doc {idx}-{j}", core_rcs[j], ages[j])
            for j in range(4)
        ]
        for extra_j in range(4, target_len):
            want_low = (idx + extra_j) % 3 == 0 and min_rc <= p.low_recipient_threshold
            rc = min(max_rc - 1, max(min_rc + 1, p.low_recipient_threshold if want_low else mid1))
            age = min(max_age, max(ages[0], 1))
            docs_list.append(MoleDoc(f"v{idx:02d}_d{extra_j}", f"Doc {idx}-{extra_j}", rc, age))

        docs = tuple(docs_list)
        low_rc = sum(1 for d in docs if d.recipient_count <= p.low_recipient_threshold)
        weights = (
            tuple(max(0.05, 1.0 - d.recipient_count / n_emp) for d in docs)
            if p.careful_mole
            else None
        )
        views.append(
            MoleView(
                day=day,
                docs=docs,
                days_since_last_leak=dsll,
                i_am_restricted=i_restr,
                n_restricted_colleagues=len(rpeers),
                recent_low_recipient_docs=low_rc,
                peers=peers,
                restricted_peers=rpeers,
                decoy=decoy,
                can_leak=True,
                select_weights=weights,
            )
        )

    special_specs = [
        (min(5, p.n_days), min(3, p.n_days), 1, min(len(rpeer_pool), 2), (), False),
        (1, 1, 0, 0, (), False),
        (
            max(1, p.n_days // 2),
            2,
            0,
            min(len(rpeer_pool), 1),
            (MoleDoc("v62_d0", "Canary 62", min(2, n_emp), 0),),
            True,
        ),
        (
            p.n_days,
            p.n_days,
            0,
            min(len(rpeer_pool), 4),
            (
                MoleDoc("v63_d0", "Memo 63a", 2, 0),
                MoleDoc("v63_d1", "Memo 63b", n_emp, max(1, p.leak_window_days - 1)),
            ),
            True,
        ),
    ]
    for offset, (day, dsll, i_restr, n_restr, docs, can_leak) in enumerate(special_specs):
        rpeers = rpeer_pool[:n_restr]
        low_rc = sum(1 for d in docs if d.recipient_count <= p.low_recipient_threshold)
        weights = (
            tuple(max(0.05, 1.0 - d.recipient_count / n_emp) for d in docs)
            if (p.careful_mole and docs)
            else None
        )
        views.append(
            MoleView(
                day=day,
                docs=docs,
                days_since_last_leak=min(day, dsll),
                i_am_restricted=i_restr,
                n_restricted_colleagues=len(rpeers),
                recent_low_recipient_docs=low_rc,
                peers=peers,
                restricted_peers=rpeers,
                decoy=decoy,
                can_leak=can_leak,
                select_weights=weights,
            )
        )

    out = tuple(views)
    assert len(out) == REPRESENTATIVE_VIEW_COUNT
    _VIEWS_CACHE[ck] = out
    return out


def _strategy_profile(strategy_json: dict | MoleStrategy, tier: str = "hard") -> dict[str, Any]:
    strat = strategy_json if isinstance(strategy_json, MoleStrategy) else MoleStrategy.from_json(strategy_json)
    ck = _tier_cache_key(tier)
    key = (canonical(strat.to_json()), ck)
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]

    views = representative_views(tier)
    p = tier_params(tier)
    decisions: list[tuple[str | None, str | None]] = []
    leak_opportunities = 0
    leaks_taken = 0
    high_rc_leaks = 0
    frames_taken = 0

    for idx, view in enumerate(views):
        rng = random.Random(f"v14-bhash:{tier}:{idx}")
        dec = strat.decide(view, rng)
        lk, fr = dec.get("leak"), dec.get("frame")
        decisions.append((lk, fr))
        if fr is not None:
            frames_taken += 1
        if view.can_leak and view.docs:
            leak_opportunities += 1
            if lk is not None:
                leaks_taken += 1
                doc_map = {d.doc_id: d for d in view.docs}
                chosen = doc_map.get(lk)
                if chosen is not None and chosen.recipient_count > p.low_recipient_threshold:
                    high_rc_leaks += 1

    raw = json.dumps(decisions, separators=(",", ":")).encode("utf-8")
    bhash = hashlib.sha256(raw).hexdigest()[:32]
    prof = {
        "behavior_hash": bhash,
        "leak_rate": leaks_taken / max(1, leak_opportunities),
        "high_rc_share": high_rc_leaks / max(1, leaks_taken) if leaks_taken else 0.0,
        "frame_rate": frames_taken / len(views),
    }
    _PROFILE_CACHE[key] = prof
    return prof


def behavior_hash(strategy_json: dict, tier: str = "hard") -> str:
    return _strategy_profile(strategy_json, tier)["behavior_hash"]


class V14Mutator:
    name = "v14"

    def __init__(self, seed: int | str = 0, tier: str | int = "hard"):
        if isinstance(seed, str):
            actual_tier = seed
            actual_seed = int(tier) if isinstance(tier, int) else 0
        else:
            actual_seed = int(seed)
            actual_tier = str(tier)
        self.seed = actual_seed
        self.tier = actual_tier
        self.params = tier_params(self.tier)
        self.feature_ranges = tier_feature_ranges(self.tier)
        self.rng = random.Random(f"forge-v14:{self.tier}:{self.seed}")

    def reseed(self, gen: int) -> None:
        self.params = tier_params(self.tier)
        self.feature_ranges = tier_feature_ranges(self.tier)
        self.rng = random.Random(f"forge-v14:{self.tier}:{self.seed}:{gen}")

    def _valid_ops_and_vals(self, feature: str) -> list[tuple[str, int]]:
        lo, hi = self.feature_ranges[feature]
        if lo == 0 and hi == 1:
            return [("==", 0), ("==", 1)]
        pairs: list[tuple[str, int]] = []
        for op in OPS:
            for v in range(lo, hi + 1):
                if is_valid_cond((feature, op, v), self.feature_ranges):
                    pairs.append((op, v))
        return pairs

    def _cond(self, existing: Sequence[Sequence[Any]] = ()) -> list[Any]:
        r = self.rng
        used_canonical = {_FEATURE_ALIAS.get(c[0], c[0]) for c in existing}
        preferred = [f for f in FEATURES if _FEATURE_ALIAS.get(f, f) not in used_canonical]
        pool = preferred or list(FEATURES)
        for _ in range(32):
            f = r.choice(pool)
            choices = self._valid_ops_and_vals(f)
            if not choices:
                continue
            op, val = r.choice(choices)
            cand = [f, op, val]
            if is_valid_rule_conds([*existing, cand], self.tier):
                return cand
        for f in FEATURES:
            for op, val in self._valid_ops_and_vals(f):
                cand = [f, op, val]
                if is_valid_rule_conds([*existing, cand], self.tier):
                    return cand
        return ["day", "<=", max(1, self.params.n_days // 2)]

    def _action(self, require_leak: bool = False) -> dict[str, str | None]:
        r = self.rng
        leak_pool = _ACTIVE_LEAK_SELECTORS if require_leak else LEAK_SELECTORS
        return {"leak": r.choice(leak_pool), "frame": r.choice(FRAME_SELECTORS)}

    def _rule(self) -> dict[str, Any]:
        n_conds = self.rng.randint(1, 3)
        conds: list[list[Any]] = []
        for _ in range(n_conds):
            nxt = self._cond(conds)
            if is_valid_rule_conds([*conds, nxt], self.tier):
                conds.append(nxt)
        if not conds:
            conds = [self._cond(())]
        return {"if": conds, "then": self._action()}

    def _repair_strategy(self, s: dict[str, Any]) -> dict[str, Any]:
        cleaned_rules: list[dict[str, Any]] = []
        seen_ifs: set[str] = set()
        for r in s.get("rules", [])[:MAX_RULES]:
            raw_if = r.get("if", [])
            kept: list[list[Any]] = []
            for c in raw_if[:MAX_CONDS]:
                if is_valid_cond(c, self.feature_ranges) and is_valid_rule_conds([*kept, c], self.tier):
                    kept.append([c[0], c[1], int(c[2]) if float(c[2]).is_integer() else c[2]])
            if not kept:
                kept = [self._cond(())]
            sig = canonical({"if": kept})
            if sig in seen_ifs:
                continue
            seen_ifs.add(sig)
            cleaned_rules.append({"if": kept, "then": copy.deepcopy(r.get("then", self._action()))})

        default_act = copy.deepcopy(s.get("default") or DEFAULT_STRATEGY_JSON_V14["default"])
        while cleaned_rules and cleaned_rules[-1]["then"] == default_act:
            cleaned_rules.pop()

        out = validate_strategy({"rules": cleaned_rules, "default": default_act})
        branches = [rl["then"] for rl in out["rules"]] + [out["default"]]
        if all(b.get("leak") in (None, "none") for b in branches):
            if out["rules"] and self.rng.random() < 0.5:
                self.rng.choice(out["rules"])["then"]["leak"] = self.rng.choice(_ACTIVE_LEAK_SELECTORS)
            else:
                out["default"]["leak"] = self.rng.choice(_ACTIVE_LEAK_SELECTORS)
            out = validate_strategy(out)
        return out

    def mutate(self, s: dict[str, Any]) -> dict[str, Any]:
        self.params = tier_params(self.tier)
        self.feature_ranges = tier_feature_ranges(self.tier)
        s = copy.deepcopy(s)
        r = self.rng
        rules = s.setdefault("rules", [])
        op = r.choice(["add", "remove", "cond", "threshold", "op", "leak", "frame", "default", "swap"])

        if op == "add" or not rules:
            if len(rules) < MAX_RULES:
                rules.insert(r.randint(0, len(rules)), self._rule())
            else:
                rules[r.randrange(len(rules))] = self._rule()
        elif op == "remove":
            rules.pop(r.randrange(len(rules)))
        elif op == "swap" and len(rules) >= 2:
            i, j = r.sample(range(len(rules)), 2)
            rules[i], rules[j] = rules[j], rules[i]
        elif op in ("cond", "threshold", "op"):
            rule = r.choice(rules)
            idx = r.randrange(len(rule["if"]))
            others = [rule["if"][j] for j in range(len(rule["if"])) if j != idx]
            if op == "cond":
                if len(rule["if"]) < MAX_CONDS and r.random() < 0.5:
                    cand = self._cond(rule["if"])
                    if is_valid_rule_conds([*rule["if"], cand], self.tier):
                        rule["if"].append(cand)
                elif len(rule["if"]) > 1 and is_valid_rule_conds(others, self.tier):
                    rule["if"].pop(idx)
                else:
                    rule["if"][idx] = self._cond(others)
            elif op == "threshold":
                f, cur_op, cur_val = rule["if"][idx]
                lo, hi = self.feature_ranges.get(f, (0, 14))
                span = max(1, (hi - lo) // 5)
                deltas = [d for d in range(-span, span + 1) if d != 0]
                r.shuffle(deltas)
                replaced = False
                for delta in deltas:
                    nv = max(lo, min(hi, int(cur_val) + delta))
                    trial = copy.deepcopy(rule["if"])
                    trial[idx] = [f, cur_op, nv]
                    if nv != cur_val and is_valid_rule_conds(trial, self.tier):
                        rule["if"][idx][2] = nv
                        replaced = True
                        break
                if not replaced:
                    rule["if"][idx] = self._cond(others)
            else:
                f, _, cur_val = rule["if"][idx]
                alt_ops = [o for o in OPS if o != rule["if"][idx][1]]
                r.shuffle(alt_ops)
                replaced = False
                for new_op in alt_ops:
                    trial = copy.deepcopy(rule["if"])
                    trial[idx] = [f, new_op, cur_val]
                    if is_valid_rule_conds(trial, self.tier):
                        rule["if"][idx][1] = new_op
                        replaced = True
                        break
                if not replaced:
                    rule["if"][idx] = self._cond(others)
        elif op == "leak":
            tgt = r.choice(rules)["then"] if rules and r.random() < 0.8 else s["default"]
            tgt["leak"] = r.choice(LEAK_SELECTORS)
        elif op == "frame":
            tgt = r.choice(rules)["then"] if rules and r.random() < 0.8 else s["default"]
            tgt["frame"] = r.choice(FRAME_SELECTORS)
        else:
            s["default"] = self._action()

        return self._repair_strategy(s)

    def crossover(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        r = self.rng
        ra, rb = a.get("rules", []), b.get("rules", [])
        ia, ib = r.randint(0, len(ra)), r.randint(0, len(rb))
        merged = copy.deepcopy(ra[:ia] + rb[ib:])[:MAX_RULES]
        default_act = copy.deepcopy(r.choice([a, b]).get("default", DEFAULT_STRATEGY_JSON_V14["default"]))
        return self._repair_strategy({"rules": merged, "default": default_act})

    def propose(self, parents: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
        strategies = [validate_strategy(p["strategy_json"]) for p in parents] or [
            validate_strategy(default_strategy_json())
        ]
        out: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        attempts = 0
        max_attempts = max(n, n * 6)
        while len(out) < n and attempts < max_attempts:
            attempts += 1
            if len(strategies) >= 2 and self.rng.random() < 0.35:
                pa, pb = self.rng.sample(strategies, 2)
                child = self.crossover(pa, pb)
                if self.rng.random() < 0.6:
                    child = self.mutate(child)
            else:
                child = self.mutate(self.rng.choice(strategies))
            bh = behavior_hash(child, self.tier)
            if bh not in seen_hashes or attempts > n * 4:
                seen_hashes.add(bh)
                out.append(child)
        while len(out) < n:
            out.append(self.mutate(self.rng.choice(strategies)))
        return out


DEFAULT_STRATEGY_JSON_V14 = {"rules": [], "default": {"leak": "random_seeded", "frame": "none"}}


def get_v14_mutator(spec: Any = "v14", tier: str = "hard", seed: int = 0):
    if not isinstance(spec, str) and hasattr(spec, "propose"):
        return spec
    if spec in ("v14", "stub"):
        return V14Mutator(seed=seed, tier=tier)
    from canary.llm import get_client

    m = LLMMutator(get_client(spec), seed=seed)
    m.fallback = V14Mutator(seed=seed, tier=tier)
    return m


def v14_investigators() -> dict[str, Callable]:
    return {
        "heuristic": ClassFactory("canary.baselines", "Heuristic"),
        "hinted_heuristic": ClassFactory("canary.forge.investigators", "HintedHeuristic"),
        "grok_tactics": ClassFactory("canary.baselines", "GrokTactics"),
    }


def v14_fake_investigators() -> dict[str, Callable]:
    return {
        "heuristic": fake_factory,
        "hinted_heuristic": fake_factory,
        "grok_tactics": fake_factory,
    }


def _u(*parts: Any) -> float:
    digest = hashlib.sha256(":".join(map(str, parts)).encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) / 0xFFFFFFFF


def v14_fake_runner(
    tier: str,
    seed: int,
    strategy_json: dict,
    agent: str,
    factory: Callable | None = None,
) -> tuple[float, bool]:
    prof = _strategy_profile(strategy_json, tier)
    bhash = prof["behavior_hash"]
    leak_rate = prof["leak_rate"]
    frame_rate = prof["frame_rate"]
    high_rc_share = prof["high_rc_share"]
    noise = _u(bhash, tier, seed, agent) - 0.5

    if agent == SOLVER_NAME:
        if leak_rate <= 0.05:
            return 0.0, False
        acc_prob = min(0.98, 0.55 + 0.55 * leak_rate)
        correct = _u(bhash, tier, seed, "solver_acc") < acc_prob
        if not correct:
            return -1.0, False
        score = max(0.15, min(0.95, 0.72 + 0.06 * leak_rate - 0.04 * frame_rate + 0.10 * noise))
        return score, True

    if leak_rate <= 0.05:
        return 0.0, False

    base = {"heuristic": 0.48, "hinted_heuristic": 0.58, "grok_tactics": 0.62}.get(agent, 0.52)
    frame_weight = 0.06 if agent == "hinted_heuristic" else 0.14
    selective_bonus = 0.16 * max(0.0, 1.0 - abs(leak_rate - 0.60)) if leak_rate < 0.98 else 0.0
    penalty = frame_weight * frame_rate + selective_bonus + 0.18 * high_rc_share
    raw = base - penalty + 0.18 * noise
    if raw < 0.12:
        return -1.0, False
    return min(0.95, raw), True


def validate_seed_hygiene(train_seeds: Sequence[int], holdout_seeds: Sequence[int]) -> None:
    if not train_seeds:
        raise ValueError("train_seeds must not be empty")
    if not holdout_seeds:
        raise ValueError("holdout_seeds must not be empty")
    for label, seq in (("train_seeds", train_seeds), ("holdout_seeds", holdout_seeds)):
        for s in seq:
            if isinstance(s, bool) or not isinstance(s, int):
                raise ValueError(f"{label} contains non-integer seed: {s!r}")
            if s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(
                    f"{label} contains forbidden seed {s} (seeds 0..29 and negative seeds are prohibited)"
                )
            if s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
                raise ValueError(
                    f"{label} contains forbidden judge/heldout seed {s} (800000+ and 900000+ prohibited)"
                )
            if label == "train_seeds" and s in RESERVED_HELDOUT_EVAL_SEEDS:
                raise ValueError(
                    f"train_seeds contains reserved held-out seed {s} (30000..30199 reserved for held-out eval)"
                )
    overlap = sorted(set(train_seeds) & set(holdout_seeds))
    if overlap:
        raise ValueError(f"train_seeds and holdout_seeds must be disjoint; overlap={overlap[:10]}")


def generation_seed_batch(
    train_seeds: Sequence[int],
    batch_size: int,
    seed: int = 0,
    gen: int = 0,
) -> list[int]:
    if gen < 0:
        raise ValueError(f"gen must be >= 0, got {gen}")
    pool = list(dict.fromkeys(int(s) for s in train_seeds))
    if not pool:
        raise ValueError("train_seeds pool must not be empty")
    n_pool = len(pool)
    b = max(1, min(int(batch_size), n_pool))
    if b == n_pool:
        out = list(pool)
        random.Random(f"j5c-full:{seed}:{gen}").shuffle(out)
        return out

    def _epoch_perm(epoch_idx: int) -> list[int]:
        perm = list(pool)
        random.Random(f"j5c-epoch:{seed}:{epoch_idx}").shuffle(perm)
        return perm

    start = gen * b
    end = start + b
    ep_lo = start // n_pool
    ep_hi = (end - 1) // n_pool
    stream: list[int] = []
    for ep in range(ep_lo, ep_hi + 1):
        stream.extend(_epoch_perm(ep))
    offset = start - ep_lo * n_pool
    batch = list(dict.fromkeys(stream[offset : offset + b]))
    if len(batch) < b:
        extra_rng = random.Random(f"j5c-fill:{seed}:{gen}")
        rem = [x for x in pool if x not in set(batch)]
        extra_rng.shuffle(rem)
        batch.extend(rem[: b - len(batch)])

    if gen > 0:
        prev = generation_seed_batch(pool, b, seed=seed, gen=gen - 1)
        if set(batch) == set(prev):
            alt_rng = random.Random(f"j5c-alt:{seed}:{gen}")
            non_prev = [x for x in pool if x not in set(prev)]
            alt_rng.shuffle(non_prev)
            keep_prev = list(prev)
            alt_rng.shuffle(keep_prev)
            batch = (non_prev + keep_prev)[:b]
    return batch


def evaluate_v14(
    strategy_json: dict,
    investigators: dict[str, Callable],
    solver_factory: Callable,
    seeds: Iterable[int],
    tier: str = "hard",
    runner: Callable = real_runner,
    workers: int = 1,
    baseline: dict | None = None,
    fitness_mode: str = "min",
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
) -> dict[str, Any]:
    res = evaluate(
        strategy_json,
        investigators,
        solver_factory,
        seeds,
        tier,
        runner=runner,
        workers=workers,
        baseline=baseline,
        fitness_mode=fitness_mode,
        min_solver_acc=min_solver_acc,
    )
    feasible = (
        res["solver_score"] >= min_solver_ratio * res["baseline_solver_score"]
        and res["solver_acc"] >= min_solver_acc
    )
    raw_fit = res["min_regret"] if fitness_mode == "min" else res["regret"]
    res["min_solver_ratio"] = min_solver_ratio
    res["feasible"] = feasible
    res["fitness"] = raw_fit if feasible else -math.inf
    return res


def _fin(x: float | None) -> float | None:
    return x if x is not None and math.isfinite(x) else None


def _member_sort_key(m: dict[str, Any]) -> tuple[float, int, str]:
    fit = m["fitness"] if m["fitness"] is not None and math.isfinite(m["fitness"]) else -math.inf
    s = m["strategy_json"]
    return (fit, -len(s.get("rules", [])), canonical(s))


def dedupe_by_behavior(members: Iterable[dict[str, Any]], tier: str = "hard") -> list[dict[str, Any]]:
    best_by_hash: dict[str, dict[str, Any]] = {}
    for m in members:
        bh = m.get("behavior_hash") or behavior_hash(m["strategy_json"], tier)
        cand = {**m, "behavior_hash": bh}
        prev = best_by_hash.get(bh)
        if prev is None or _member_sort_key(cand) > _member_sort_key(prev):
            best_by_hash[bh] = cand
    return sorted(best_by_hash.values(), key=_member_sort_key, reverse=True)


def _tournament(rng: random.Random, pop: list[dict[str, Any]], k: int = 3) -> dict[str, Any]:
    cand = rng.sample(pop, min(k, len(pop)))
    return max(cand, key=_member_sort_key)


def _update_archive(
    archive: dict[str, dict[str, Any]],
    member: dict[str, Any],
    n_batch_seeds: int,
    tier: str,
) -> None:
    bh = member.get("behavior_hash") or behavior_hash(member["strategy_json"], tier)
    ev = member["eval"]
    feasible = bool(ev.get("feasible")) and math.isfinite(member["fitness"])
    cur = archive.get(bh)
    if cur is None:
        cur = {
            "behavior_hash": bh,
            "strategy_json": member["strategy_json"],
            "total_seeds": 0,
            "feasible_seeds": 0,
            "feasible_batches": 0,
            "weighted_min_regret": 0.0,
            "best_batch_fitness": -math.inf,
        }
        archive[bh] = cur

    cur["total_seeds"] += n_batch_seeds
    if feasible:
        prev_fs = cur["feasible_seeds"]
        new_fs = prev_fs + n_batch_seeds
        cur["weighted_min_regret"] = (
            cur["weighted_min_regret"] * prev_fs + float(ev["min_regret"]) * n_batch_seeds
        ) / new_fs
        cur["feasible_seeds"] = new_fs
        cur["feasible_batches"] += 1
        cand_key = (float(member["fitness"]), -len(member["strategy_json"].get("rules", [])))
        best_key = (cur["best_batch_fitness"], -len(cur["strategy_json"].get("rules", [])))
        if cand_key > best_key:
            cur["best_batch_fitness"] = float(member["fitness"])
            cur["strategy_json"] = member["strategy_json"]


def _write_gen_log(
    path: Path,
    gen: int,
    gen_seeds: list[int],
    pop: list[dict[str, Any]],
    baseline: dict[str, float],
    mutator: Any,
    t0: float,
) -> None:
    fits = [p["fitness"] for p in pop]
    feas = [f for f in fits if math.isfinite(f)]
    best = max(pop, key=_member_sort_key)
    unique_bh = len({p["behavior_hash"] for p in pop})
    line = {
        "gen": gen,
        "seeds": gen_seeds,
        "unique_behaviors": unique_bh,
        "best_fitness": _fin(best["fitness"]),
        "mean_fitness": sum(feas) / len(feas) if feas else None,
        "feasible_share": len(feas) / len(pop) if pop else 0.0,
        "best_behavior_hash": best["behavior_hash"],
        "best_strategy": best["strategy_json"],
        "best_eval": {k: v for k, v in best["eval"].items() if k != "fitness"},
        "baseline_solver_score": baseline["score"],
        "mutator": getattr(mutator, "name", "?"),
        "seconds": round(time.time() - t0, 3),
        "population": [
            {
                "strategy_json": p["strategy_json"],
                "behavior_hash": p["behavior_hash"],
                "fitness": _fin(p["fitness"]),
                "eval": {k: v for k, v in p["eval"].items() if k != "fitness"},
            }
            for p in pop
        ],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


def rank_holdout_hof(
    candidates: Sequence[dict[str, Any]],
    investigators: dict[str, Callable],
    solver_factory: Callable,
    holdout_seeds: Sequence[int],
    tier: str = "hard",
    runner: Callable = real_runner,
    workers: int = 1,
    hof_k: int = 10,
    fitness_mode: str = "min",
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    holdout_list = list(holdout_seeds)
    holdout_baseline = solver_baseline(solver_factory, holdout_list, tier, runner, workers)
    unique_cands: dict[str, dict[str, Any]] = {}
    for c in candidates:
        sj = validate_strategy(c["strategy_json"])
        bh = behavior_hash(sj, tier)
        tf = c.get("train_fitness")
        tf_val = float(tf) if tf is not None and math.isfinite(float(tf)) else -math.inf
        prev = unique_cands.get(bh)
        if prev is None or (tf_val, -len(sj.get("rules", []))) > (
            prev["train_sort"],
            -len(prev["strategy_json"].get("rules", [])),
        ):
            unique_cands[bh] = {
                "behavior_hash": bh,
                "strategy_json": sj,
                "train_fitness": _fin(tf_val),
                "train_sort": tf_val,
            }

    scored: list[tuple[tuple[float, float, int, str], dict[str, Any]]] = []
    for bh, item in unique_cands.items():
        sj = item["strategy_json"]
        ev = evaluate_v14(
            sj,
            investigators,
            solver_factory,
            holdout_list,
            tier=tier,
            runner=runner,
            workers=workers,
            baseline=holdout_baseline,
            fitness_mode=fitness_mode,
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
        )
        if not ev["feasible"] or not math.isfinite(ev["min_regret"]):
            continue
        sort_key = (
            float(ev["min_regret"]),
            float(ev["solver_score"]),
            -len(sj.get("rules", [])),
            canonical(sj),
        )
        scored.append(
            (
                sort_key,
                {
                    "fitness": float(ev["min_regret"]),
                    "min_regret": float(ev["min_regret"]),
                    "regret": float(ev["regret"]),
                    "train_fitness": item["train_fitness"],
                    "behavior_hash": bh,
                    "solver_score": float(ev["solver_score"]),
                    "solver_acc": float(ev["solver_acc"]),
                    "baseline_solver_score": float(ev["baseline_solver_score"]),
                    "per_investigator": ev["per_investigator"],
                    "n_holdout_seeds": len(holdout_list),
                    "strategy_json": sj,
                },
            )
        )

    scored.sort(key=lambda pair: pair[0], reverse=True)
    hof: list[dict[str, Any]] = []
    for idx, (_, row) in enumerate(scored[:hof_k]):
        hof.append({"rank": idx + 1, **row})
    return hof, holdout_baseline


def run_j5c(
    mutator_spec: str = "v14",
    tier: str = "hard",
    pop_size: int = 16,
    gens: int = 20,
    train_seeds: Iterable[int] = DEFAULT_TRAIN_SEEDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    holdout_seeds: Iterable[int] = DEFAULT_HOLDOUT_SEEDS,
    workers: int = 1,
    out: str | Path = "data/forge/j5c",
    fake: bool = False,
    seed: int = 0,
    elite: int = 3,
    hof_k: int = 10,
    holdout_candidates: int | None = None,
    investigators: dict[str, Callable] | None = None,
    solver_factory: Callable | None = None,
    runner: Callable | None = None,
    log: Callable = print,
    fitness_mode: str = "min",
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
) -> dict[str, Any]:
    train_pool = list(train_seeds)
    holdout_list = list(holdout_seeds)
    validate_seed_hygiene(train_pool, holdout_list)

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fake:
        runner = runner or v14_fake_runner
        investigators = investigators or v14_fake_investigators()
        solver_factory = solver_factory or fake_factory
    else:
        runner = runner or real_runner
        investigators = investigators or v14_investigators()
        solver_factory = solver_factory or default_solver_factory()

    mutator = get_v14_mutator(mutator_spec, tier=tier, seed=seed)
    archive: dict[str, dict[str, Any]] = {}
    seed_schedule: list[list[int]] = []

    log_path = out_dir / "log.jsonl"
    start_gen = 0
    pop: list[dict[str, Any]] | None = None
    last_train_baseline: dict[str, float] | None = None

    if log_path.exists():
        lines = [json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for ln in lines:
            batch_s = ln.get("seeds", [])
            seed_schedule.append(batch_s)
            for p in ln["population"]:
                p["fitness"] = -math.inf if p["fitness"] is None else float(p["fitness"])
                p["behavior_hash"] = p.get("behavior_hash") or behavior_hash(p["strategy_json"], tier)
                p["eval"] = {**p["eval"], "fitness": p["fitness"]}
                _update_archive(archive, p, max(1, len(batch_s)), tier)
        if lines:
            start_gen = int(lines[-1]["gen"]) + 1
            pop = lines[-1]["population"]
            last_train_baseline = {"score": float(lines[-1]["baseline_solver_score"]), "acc": 1.0}
            log(f"resuming {out_dir} at gen {start_gen}")

    for gen in range(start_gen, gens):
        t0 = time.time()
        gen_seeds = generation_seed_batch(train_pool, batch_size, seed=seed, gen=gen)
        seed_schedule.append(gen_seeds)
        gen_baseline = solver_baseline(solver_factory, gen_seeds, tier, runner, workers)
        last_train_baseline = gen_baseline
        batch_cache: dict[str, dict[str, Any]] = {}

        def eval_member(sj: dict[str, Any]) -> dict[str, Any]:
            norm = validate_strategy(sj)
            ck = canonical(norm)
            if ck not in batch_cache:
                batch_cache[ck] = evaluate_v14(
                    norm,
                    investigators,
                    solver_factory,
                    gen_seeds,
                    tier=tier,
                    runner=runner,
                    workers=workers,
                    baseline=gen_baseline,
                    fitness_mode=fitness_mode,
                    min_solver_acc=min_solver_acc,
                    min_solver_ratio=min_solver_ratio,
                )
            ev = batch_cache[ck]
            return {
                "strategy_json": norm,
                "behavior_hash": behavior_hash(norm, tier),
                "fitness": ev["fitness"],
                "eval": ev,
            }

        rng = random.Random(f"j5c-evolve:{seed}:{gen}")
        if hasattr(mutator, "reseed"):
            mutator.reseed(gen)

        if pop is None:
            base = validate_strategy(default_strategy_json())
            proposals = mutator.propose(
                [{"strategy_json": base, "fitness": None, "beaten_tags": []}],
                max(0, pop_size - 1),
            )
            cand_jsons = [base] + proposals
        else:
            unique_ranked = dedupe_by_behavior(pop, tier)
            elite_jsons = [m["strategy_json"] for m in unique_ranked[: max(1, min(elite, pop_size))]]
            seen_bh = {behavior_hash(s, tier) for s in elite_jsons}
            n_parents = max(2, min(4, max(2, pop_size // 4)))
            parents = []
            for _ in range(n_parents):
                chosen = _tournament(rng, unique_ranked)
                parents.append(
                    {
                        "strategy_json": chosen["strategy_json"],
                        "fitness": _fin(chosen["fitness"]),
                        "beaten_tags": chosen["eval"].get("beaten", []),
                    }
                )
            needed = max(0, pop_size - len(elite_jsons))
            children: list[dict[str, Any]] = []
            fallback_children: list[dict[str, Any]] = []
            for _ in range(4):
                if len(children) >= needed:
                    break
                raw_kids = mutator.propose(parents, needed - len(children))
                for kid in raw_kids:
                    kbh = behavior_hash(kid, tier)
                    if kbh not in seen_bh:
                        seen_bh.add(kbh)
                        children.append(kid)
                        if len(children) >= needed:
                            break
                    else:
                        fallback_children.append(kid)
            while len(children) < needed and fallback_children:
                children.append(fallback_children.pop(0))
            while len(children) < needed:
                children.extend(mutator.propose(parents, needed - len(children)))
            cand_jsons = elite_jsons + children[:needed]

        pop = [eval_member(sj) for sj in cand_jsons[:pop_size]]
        for m in pop:
            _update_archive(archive, m, len(gen_seeds), tier)

        _write_gen_log(log_path, gen, gen_seeds, pop, gen_baseline, mutator, t0)
        best = max(pop, key=_member_sort_key)
        n_feas = sum(1 for m in pop if math.isfinite(m["fitness"]))
        n_uniq = len({m["behavior_hash"] for m in pop})
        log(
            f"gen {gen}: seeds={gen_seeds[0]}..{gen_seeds[-1]} (n={len(gen_seeds)}) "
            f"best={best['fitness']:.4f} feasible={n_feas}/{len(pop)} unique={n_uniq}"
        )

    feasible_archive = [
        {
            "behavior_hash": bh,
            "strategy_json": item["strategy_json"],
            "train_fitness": item["weighted_min_regret"],
            "feasible_seeds": item["feasible_seeds"],
        }
        for bh, item in archive.items()
        if item["feasible_batches"] > 0
    ]
    feasible_archive.sort(
        key=lambda x: (
            float(x["train_fitness"]),
            int(x["feasible_seeds"]),
            -len(x["strategy_json"].get("rules", [])),
        ),
        reverse=True,
    )
    max_holdout_cands = holdout_candidates if holdout_candidates is not None else max(hof_k * 2, pop_size)
    shortlist = feasible_archive[: max(1, max_holdout_cands)]
    if not shortlist and gens == 0:
        shortlist = [{"strategy_json": validate_strategy(default_strategy_json()), "train_fitness": None}]

    hof, holdout_baseline = rank_holdout_hof(
        shortlist,
        investigators=investigators,
        solver_factory=solver_factory,
        holdout_seeds=holdout_list,
        tier=tier,
        runner=runner,
        workers=workers,
        hof_k=hof_k,
        fitness_mode=fitness_mode,
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
    )
    hof_path = out_dir / "hall_of_fame.jsonl"
    hof_path.write_text("".join(json.dumps(row) + "\n" for row in hof), encoding="utf-8")

    return {
        "out": str(out_dir),
        "tier": tier,
        "baseline": holdout_baseline,
        "train_baseline": last_train_baseline,
        "holdout_baseline": holdout_baseline,
        "seed_schedule": seed_schedule,
        "hof": hof,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--mutator", default="v14")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--gens", type=int, default=20)
    ap.add_argument("--train-seeds", "--seeds", dest="train_seeds", default="200-599")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--holdout-seeds", default="6200-6239")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--elite", type=int, default=3)
    ap.add_argument("--hof", type=int, default=10)
    ap.add_argument("--holdout-candidates", type=int, default=None)
    ap.add_argument("--fitness", choices=["min", "mean"], default="min")
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args(argv)

    res = run_j5c(
        mutator_spec=a.mutator,
        tier=a.tier,
        pop_size=a.pop,
        gens=a.gens,
        train_seeds=parse_seeds(a.train_seeds),
        batch_size=a.batch_size,
        holdout_seeds=parse_seeds(a.holdout_seeds),
        workers=a.workers,
        out=a.out,
        fake=a.fake,
        seed=a.seed,
        elite=a.elite,
        hof_k=a.hof,
        holdout_candidates=a.holdout_candidates,
        fitness_mode=a.fitness,
        min_solver_acc=a.min_solver_acc,
        min_solver_ratio=a.min_solver_ratio,
    )
    print(
        json.dumps(
            {
                "out": res["out"],
                "tier": res["tier"],
                "holdout_baseline": res["holdout_baseline"],
                "hof_size": len(res["hof"]),
                "best_holdout_min_regret": res["hof"][0]["min_regret"] if res["hof"] else None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
