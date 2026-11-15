from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import forge_track, rules
from canary.baselines import BASELINES, CALIBRATION_POLICIES
from canary.env import TOPICS, Env
from canary.eval import run_episode
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical
from canary.forge.rl_mole import FEATURE_NAMES as RL_FEATURE_NAMES
from canary.forge.rl_mole import RLMole
from canary.forge.rl_mole import features as rl_features
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FEATURES as DSL_FEATURES,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MoleDoc,
    MoleStrategy,
    MoleView,
    _select_frame,
    _select_leak,
)
from canary.redteam import fuzz
from canary.redteam.swarm_probes import SWARM_POLICIES
from canary.solver.policy import SolverPolicy
from canary.world import generate_world

DEFAULT_OUT_DIR = "/tmp/opencode/w6"
MIN_ACC = forge_track.MIN_ACC

NON_CANARY_BASELINES: tuple[str, ...] = (
    "do_nothing",
    "stop_early",
    "guess_day1",
    "restrict_all",
    "accuse_decoy",
    "logs_only",
    "accuse_most_logs",
)

CANARY_BASELINES: tuple[str, ...] = (
    "heuristic",
    "hinted_heuristic",
    "grok_tactics",
    "swarm_w2b008",
)

ALL_BASELINES: tuple[str, ...] = NON_CANARY_BASELINES + CANARY_BASELINES
ALL_POLICIES: tuple[str, ...] = ALL_BASELINES + ("solver",)

PART_A_FULL_SEEDS: list[int] = (
    list(range(0, 120)) + list(range(50000, 50100)) + list(range(200000, 200100))
)
PART_A_QUICK_SEEDS: list[int] = list(range(0, 11))

PART_B_FULL_SEEDS: list[int] = list(range(6000, 6200))
PART_B_QUICK_SEEDS: list[int] = [6000]

PART_C_FULL_SEEDS: list[int] = list(range(6000, 6040))
PART_C_QUICK_SEEDS: list[int] = [6000]
PART_C_FULL_BUDGET = 1200
PART_C_QUICK_BUDGET = 1

MOLE_ROW_ORDER: tuple[str, ...] = (
    "default_hard_5dept",
    "hof_v12_hard_5dept",
    "hof_v13_hard_5dept",
    "rl_final_hard_5dept",
    "rl_final_hard_rl_4dept",
    "rl_it80_hard_5dept",
)

FUZZ_MOLE_ORDER: tuple[str, ...] = (
    "hof_v12_hard_5dept",
    "hof_v13_hard_5dept",
    "rl_final_hard_5dept",
    "rl_final_hard_rl_4dept",
    "rl_it80_hard_5dept",
)


def ci95(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))


def exact_binom_upper_tail(k: int, n: int) -> float:
    if n <= 0:
        return 1.0
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    terms = [math.comb(n, j) for j in range(k, n + 1)]
    total = sum(terms)
    return float(total / (1 << n))


def exact_binom_two_sided(k: int, n: int, p: float) -> float:
    if n <= 0:
        return 1.0
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    lg_n = math.lgamma(n + 1)
    lp_p = math.log(p)
    lp_q = math.log(1.0 - p)

    def log_pmf(j: int) -> float:
        return lg_n - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * lp_p + (n - j) * lp_q

    lp_obs = log_pmf(k)
    thresh = lp_obs + 1e-12
    acc = 0.0
    for j in range(n + 1):
        lp_j = log_pmf(j)
        if lp_j <= thresh:
            acc += math.exp(lp_j)
    return min(1.0, acc)


class CheatingCanaryPeekMole:
    name = "cheating_canary_peek_mole"

    def __init__(
        self,
        canary_lookup: Callable[[str], bool] | None = None,
        use_doc_id_prefix: bool = False,
        suppress_when_all_canary: bool = True,
    ):
        self.canary_lookup = canary_lookup
        self.use_doc_id_prefix = use_doc_id_prefix
        self.suppress_when_all_canary = suppress_when_all_canary

    def _is_canary(self, doc: MoleDoc) -> bool:
        if self.canary_lookup is not None:
            return bool(self.canary_lookup(doc.doc_id))
        if self.use_doc_id_prefix:
            return doc.doc_id.startswith("c")
        return False

    def decide(self, view: MoleView, rng: random.Random | None = None) -> dict[str, str | None]:
        r = rng if rng is not None else random.Random(0)
        frame = _select_frame("decoy", view, r)
        if not view.docs or not view.can_leak:
            return {"leak": None, "frame": frame}
        safe_docs = [d for d in view.docs if not self._is_canary(d)]
        if safe_docs:
            chosen = safe_docs[0].doc_id
            return {"leak": chosen, "frame": frame}
        if self.suppress_when_all_canary:
            return {"leak": None, "frame": frame}
        return {"leak": view.docs[0].doc_id, "frame": frame}


_COMMITTED_MOLES_CACHE: dict[Path, dict[str, Any]] = {}


def load_committed_moles(repo_root: Path = ROOT) -> dict[str, Any]:
    resolved = repo_root.resolve()
    cached = _COMMITTED_MOLES_CACHE.get(resolved)
    if cached is not None:
        return cached
    v12_path = resolved / "data" / "forge" / "hall_of_fame_v1.2.jsonl"
    v13_path = resolved / "data" / "forge" / "hall_of_fame_v1.3.jsonl"
    v14_path = resolved / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
    rl_hof_path = resolved / "data" / "rl_mole" / "hall_of_fame.jsonl"
    rl_final_path = resolved / "data" / "rl_mole" / "policy_final.json"
    rl_it80_path = resolved / "data" / "rl_mole" / "policy_it080.json"

    v12_rows, v12_strats = forge_track.load(v12_path)
    v13_rows, v13_strats = forge_track.load(v13_path)
    rl_rows, rl_strats = forge_track.load(rl_hof_path)

    rl_final_json = json.loads(rl_final_path.read_text(encoding="utf-8"))
    rl_it80_json = json.loads(rl_it80_path.read_text(encoding="utf-8"))
    rl_final = RLMole.from_json(rl_final_json)
    rl_it80 = RLMole.from_json(rl_it80_json)

    loaded = {
        "default_v0": DEFAULT_STRATEGY,
        "hof_v12": v12_strats[0],
        "hof_v12_row": v12_rows[0],
        "hof_v13": v13_strats[0],
        "hof_v13_row": v13_rows[0],
        "hof_v14_exists": v14_path.exists(),
        "rl_hof": rl_strats[0],
        "rl_hof_row": rl_rows[0],
        "rl_final": rl_final,
        "rl_final_json": rl_final_json,
        "rl_it80": rl_it80,
        "rl_it80_json": rl_it80_json,
    }
    _COMMITTED_MOLES_CACHE[resolved] = loaded
    return loaded


def make_mole_env_factories(moles: dict[str, Any]) -> dict[str, tuple[str, Any, Callable[[int], Env]]]:
    return {
        "default_hard_5dept": (
            "hard",
            moles["default_v0"],
            lambda s: Env("hard", s, mole_strategy=moles["default_v0"]),
        ),
        "hof_v12_hard_5dept": (
            "hard",
            moles["hof_v12"],
            lambda s: Env("hard", s, mole_strategy=moles["hof_v12"]),
        ),
        "hof_v13_hard_5dept": (
            "hard",
            moles["hof_v13"],
            lambda s: Env("hard", s, mole_strategy=moles["hof_v13"]),
        ),
        "rl_final_hard_5dept": (
            "hard",
            moles["rl_final"],
            lambda s: Env("hard", s, mole_strategy=moles["rl_final"]),
        ),
        "rl_final_hard_rl_4dept": (
            "hard_rl",
            moles["rl_hof"],
            lambda s: Env("hard_rl", s),
        ),
        "rl_it80_hard_5dept": (
            "hard",
            moles["rl_it80"],
            lambda s: Env("hard", s, mole_strategy=moles["rl_it80"]),
        ),
    }


def make_investigator(name: str, seed: int, quick: bool = False):
    if name in BASELINES:
        return BASELINES[name](seed=seed)
    if name in CALIBRATION_POLICIES:
        return CALIBRATION_POLICIES[name](seed=seed)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if name in SWARM_POLICIES:
        return SWARM_POLICIES[name](seed=seed)
    if name == "solver":
        if quick:
            return SolverPolicy(
                act_budget=6.0,
                threshold=0.05,
                multi="off",
                max_candidates=2,
                coverages=(0.5,),
                tiny=False,
                max_pending=1,
                use_v_drops=False,
                read_logs=False,
                find_decoy=False,
            )
        return SolverPolicy(act_budget=10.0)
    raise ValueError(f"unknown investigator: {name}")


def _build_canary_peek_fixtures(seeds: list[int], quick: bool = False) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    fixture_tier = "easy" if quick else "hard"
    for idx, s in enumerate(seeds):
        env = Env(fixture_tier, s)
        mole = env._world.mole
        reg_raw = None
        for d_raw in env.docs:
            if mole in d_raw["recipients"]:
                reg_raw = d_raw
                break
        if reg_raw is None:
            peers = [e for e in env._ids if e != mole]
            recips = sorted([mole] + peers[:15])
            reg_id, reg_title, k = "d1-1", "Q1 Engineering budget forecast", len(recips)
        else:
            recips = list(reg_raw["recipients"])
            reg_id, reg_title, k = reg_raw["doc_id"], reg_raw["title"], len(recips)

        labels = ("A", "B", "C")
        asg = {e: labels[i % 3] for i, e in enumerate(recips)}
        env.call("plant_canary", {"doc_title": f"Board deck draft Q{(s % 4) + 1}", "assignment": asg})
        can_id = env._canary_ids[-1]
        can_raw = env._doc_by_id[can_id]

        reg_doc = MoleDoc(reg_id, reg_title, k, 0)
        can_doc = MoleDoc(can_id, can_raw["title"], k, 0)
        peers_t = tuple(e for e in env._ids if e != mole)
        low_cnt = 2 if k <= env.p.low_recipient_threshold else 0
        single_low_cnt = int(k <= env.p.low_recipient_threshold)

        v_ab = MoleView(
            day=1,
            docs=(reg_doc, can_doc),
            days_since_last_leak=1,
            i_am_restricted=0,
            n_restricted_colleagues=0,
            recent_low_recipient_docs=low_cnt,
            peers=peers_t,
            restricted_peers=(),
            decoy=env._world.decoy,
            can_leak=True,
            select_weights=(1.0, 1.0),
        )
        v_ba = MoleView(
            day=1,
            docs=(can_doc, reg_doc),
            days_since_last_leak=1,
            i_am_restricted=0,
            n_restricted_colleagues=0,
            recent_low_recipient_docs=low_cnt,
            peers=peers_t,
            restricted_peers=(),
            decoy=env._world.decoy,
            can_leak=True,
            select_weights=(1.0, 1.0),
        )
        v_only_reg = dataclasses.replace(
            v_ab,
            docs=(reg_doc,),
            select_weights=(1.0,),
            recent_low_recipient_docs=single_low_cnt,
        )
        v_only_can = dataclasses.replace(
            v_ab,
            docs=(can_doc,),
            select_weights=(1.0,),
            recent_low_recipient_docs=single_low_cnt,
        )
        fixtures.append(
            {
                "idx": idx,
                "seed": s,
                "reg_id": reg_id,
                "can_id": can_id,
                "doc_by_id": env._doc_by_id,
                "v_ab": v_ab,
                "v_ba": v_ba,
                "v_only_reg": v_only_reg,
                "v_only_can": v_only_can,
            }
        )
    return fixtures


def detect_canary_peeking(
    mole_strategy: Any,
    seeds: list[int],
    bind_env_lookup: bool = False,
    prebuilt_fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    n_pairs = 0
    n_leak_decisions = 0
    n_regular_chosen = 0
    n_canary_chosen = 0
    n_order_asymmetric_pairs = 0
    n_singleton_canary_suppressed = 0
    n_singleton_regular_leaked = 0

    fixtures = prebuilt_fixtures if prebuilt_fixtures is not None else _build_canary_peek_fixtures(seeds)

    for fx in fixtures:
        idx = fx["idx"]
        s = fx["seed"]
        reg_id = fx["reg_id"]
        can_id = fx["can_id"]
        v_ab = fx["v_ab"]
        v_ba = fx["v_ba"]
        v_only_reg = fx["v_only_reg"]
        v_only_can = fx["v_only_can"]

        strat = mole_strategy
        if bind_env_lookup and isinstance(mole_strategy, CheatingCanaryPeekMole):
            strat = CheatingCanaryPeekMole(
                canary_lookup=lambda did, db=fx["doc_by_id"]: bool(db.get(did, {}).get("is_canary")),
                use_doc_id_prefix=mole_strategy.use_doc_id_prefix,
                suppress_when_all_canary=mole_strategy.suppress_when_all_canary,
            )

        rng_seed = 900_000 + idx * 17 + s
        r1 = random.Random(rng_seed)
        r2 = random.Random(rng_seed)
        d_ab = strat.decide(v_ab, r1).get("leak")
        d_ba = strat.decide(v_ba, r2).get("leak")
        n_pairs += 1

        for choice in (d_ab, d_ba):
            if choice in (reg_id, can_id):
                n_leak_decisions += 1
                if choice == reg_id:
                    n_regular_chosen += 1
                else:
                    n_canary_chosen += 1
        if d_ab == reg_id and d_ba == reg_id:
            n_order_asymmetric_pairs += 1

        o_reg = strat.decide(v_only_reg, random.Random(rng_seed + 1)).get("leak")
        o_can = strat.decide(v_only_can, random.Random(rng_seed + 1)).get("leak")
        if o_reg == reg_id:
            n_singleton_regular_leaked += 1
        if o_reg == reg_id and o_can is None:
            n_singleton_canary_suppressed += 1

    p_pair = exact_binom_upper_tail(n_regular_chosen, n_leak_decisions)
    p_supp = exact_binom_upper_tail(n_singleton_canary_suppressed, n_singleton_regular_leaked) if n_singleton_canary_suppressed > 0 else 1.0
    p_combined = min(p_pair, p_supp)
    reg_share = n_regular_chosen / n_leak_decisions if n_leak_decisions else 0.5
    return {
        "n_seed_pairs": n_pairs,
        "n_leak_decisions": n_leak_decisions,
        "n_regular_chosen": n_regular_chosen,
        "n_canary_chosen": n_canary_chosen,
        "regular_share": round(reg_share, 6),
        "n_both_orders_picked_regular": n_order_asymmetric_pairs,
        "n_singleton_regular_leaked": n_singleton_regular_leaked,
        "n_singleton_canary_suppressed": n_singleton_canary_suppressed,
        "p_value_paired_choice": p_pair,
        "p_value_singleton_suppression": p_supp,
        "p_value": p_combined,
        "canary_peeking_detected": p_combined < 1e-6,
    }


def run_part_a_isolation_audit(
    seeds: list[int],
    quick: bool = False,
    moles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    if moles is None:
        moles = load_committed_moles()
    targets = ("easy", "medium", "hard", "hard_forge", "hard_rl")

    mole_doc_fields = tuple(f.name for f in dataclasses.fields(MoleDoc))
    mole_view_fields = tuple(f.name for f in dataclasses.fields(MoleView))
    forbidden_attr_names = {
        "is_canary",
        "variants",
        "world_seed",
        "mole",
        "_world",
        "interview_lr",
        "signal",
        "posterior",
        "belief",
        "_logs",
        "_history",
    }
    schema_forbidden_hits = sorted(
        (set(mole_doc_fields) | set(mole_view_fields)) & forbidden_attr_names
    )

    views_inspected = 0
    is_canary_exposures = 0
    variant_map_exposures = 0
    world_seed_exposures = 0
    interview_signal_exposures = 0
    investigator_belief_exposures = 0
    rl_feature_bounds_violations = 0

    view_seeds = seeds[:5] if quick else seeds
    for idx, s in enumerate(view_seeds):
        target = targets[idx % len(targets)]
        env = Env(target, s)
        captured_views: list[MoleView] = []
        orig_mv = env._mole_view

        def hooked_mv(d: int, _orig=orig_mv, _cap=captured_views) -> MoleView:
            v = _orig(d)
            _cap.append(v)
            return v

        env._mole_view = hooked_mv
        emps = [e["id"] for e in env.call("list_employees", {}).data["employees"]]
        mole = env._world.mole
        ws_str = str(env._world.world_seed)
        sentinel_variants = ("VTAG_ALPHA", "VTAG_BETA", "VTAG_GAMMA")[: env.p.max_variants]
        asg = {e: sentinel_variants[i % len(sentinel_variants)] for i, e in enumerate(emps[: min(12, len(emps))])}
        asg[mole] = sentinel_variants[0]
        env.call("plant_canary", {"doc_title": "Budget review Q2", "assignment": asg})
        iv_res = env.call("interview", {"employee": mole, "topic": TOPICS[idx % len(TOPICS)]})
        iv_ans = str((iv_res.data or {}).get("answer", ""))
        peer0 = next(e for e in emps if e != mole)
        env.call("restrict_access", {"employee": peer0})
        fake_solver_post = {e: round(0.731912 if e == mole else 0.268088 / (len(emps) - 1), 8) for e in emps}
        env.call("advance_day", {})
        if not quick:
            env.call("read_access_logs", {"day_from": 1, "day_to": 1})
            env.call("advance_day", {})

        for v in captured_views:
            views_inspected += 1
            raw_dict = dataclasses.asdict(v)
            serialized = json.dumps(raw_dict, sort_keys=True)
            if "is_canary" in raw_dict or any("is_canary" in d for d in raw_dict["docs"]):
                is_canary_exposures += 1
            if "variants" in serialized or any(tag in serialized for tag in sentinel_variants):
                variant_map_exposures += 1
            if len(ws_str) >= 6 and ws_str in serialized:
                world_seed_exposures += 1
            if "evasive" in serialized.lower() or "cooperative" in serialized.lower() or (iv_ans and iv_ans in serialized):
                interview_signal_exposures += 1
            if "0.731912" in serialized or "posterior" in serialized:
                investigator_belief_exposures += 1
            x = rl_features(v)
            if x.shape != (len(RL_FEATURE_NAMES) + 1,) or not np.all(np.isfinite(x)):
                rl_feature_bounds_violations += 1
            elif np.any(x[:-1] < 0.0) or np.any(x[:-1] > 2.0) or float(x[-1]) != 1.0:
                rl_feature_bounds_violations += 1
            for fname in DSL_FEATURES:
                fv = v.feature(fname)
                if not math.isfinite(float(fv)):
                    rl_feature_bounds_violations += 1
            _ = fake_solver_post

    variant_perm_diffs = 0
    canary_flag_dsl_diffs = 0
    canary_flag_rl_diffs = 0
    canary_flag_det_selector_diffs = 0
    careful_weight_formula_mismatches = 0

    mut_seeds = seeds[:1] if quick else seeds
    for s in mut_seeds:
        env_a = Env("hard", s)
        env_b = Env("hard", s)
        mole = env_a._world.mole
        peers = [e for e in env_a._ids if e != mole]
        recips = sorted([mole] + peers[:15])
        asg_a = {e: ("A", "B", "C")[i % 3] for i, e in enumerate(recips)}
        asg_b = {e: ("Z", "X", "Y")[(i + 1) % 3] for i, e in enumerate(recips)}
        env_a.call("plant_canary", {"doc_title": "Roadmap Q3", "assignment": asg_a})
        env_b.call("plant_canary", {"doc_title": "Roadmap Q3", "assignment": asg_b})

        rng_snap = env_a._dyn.getstate()
        env_b._dyn.setstate(rng_snap)
        va = env_a._mole_view(1)
        vb = env_b._mole_view(1)
        if va != vb or not np.array_equal(rl_features(va), rl_features(vb)):
            variant_perm_diffs += 1

        cid = env_a._canary_ids[-1]
        env_a._doc_by_id[cid]["is_canary"] = False
        env_a._doc_by_id[cid]["doc_id"] = "d1-99"
        env_a._doc_by_id[cid]["title"] = "Q3 Finance vendor contracts Q3"
        env_a._doc_by_id["d1-99"] = env_a._doc_by_id.pop(cid)
        env_a._held[mole] = ["d1-99" if x == cid else x for x in env_a._held[mole]]
        env_a._dyn.setstate(rng_snap)
        vc = env_a._mole_view(1)

        dsl_b = [vb.feature(f) for f in DSL_FEATURES]
        dsl_c = [vc.feature(f) for f in DSL_FEATURES]
        if dsl_b != dsl_c:
            canary_flag_dsl_diffs += 1
        if float(np.max(np.abs(rl_features(vb) - rl_features(vc)))) != 0.0:
            canary_flag_rl_diffs += 1

        vb_leak = dataclasses.replace(vb, can_leak=True)
        vc_leak = dataclasses.replace(vc, can_leak=True)
        for sel in ("newest", "oldest", "most_recipients", "fewest_recipients", "none"):
            pick_b = _select_leak(sel, vb_leak, random.Random(0))
            pick_c = _select_leak(sel, vc_leak, random.Random(0))
            idx_b = [d.doc_id for d in vb_leak.docs].index(pick_b) if pick_b is not None else -1
            idx_c = [d.doc_id for d in vc_leak.docs].index(pick_c) if pick_c is not None else -1
            if idx_b != idx_c:
                canary_flag_det_selector_diffs += 1

        expected_w = 1.0 - (len(recips) / env_b.p.n_employees)
        if vb.select_weights is None or abs(vb.select_weights[-1] - expected_w) > 1e-12:
            careful_weight_formula_mismatches += 1
        if vc.select_weights is None or abs(vc.select_weights[-1] - 1.0) > 1e-12:
            careful_weight_formula_mismatches += 1

    non_interference_steps = 0
    non_interference_diffs = 0
    ni_seeds = seeds[:1] if quick else seeds
    for s in ni_seeds:
        e1 = Env("hard", s, mole_strategy=moles["rl_final"])
        e2 = Env("hard", s, mole_strategy=moles["rl_final"])
        rec_1: list[tuple[Any, ...]] = []
        rec_2: list[tuple[Any, ...]] = []

        def wrap_env(ev: Env, sink: list[tuple[Any, ...]]) -> None:
            orig_mv = ev._mole_view
            orig_md = ev._mole_decide

            def mv(d: int, _o=orig_mv):
                v = _o(d)
                sink.append(("view", dataclasses.asdict(v), rl_features(v).tolist()))
                return v

            def md(v: MoleView, _o=orig_md, _ev=ev):
                dec = _o(v)
                sink.append(("dec", dec, _ev._dyn.getstate()[1][:4]))
                return dec

            ev._mole_view = mv
            ev._mole_decide = md

        wrap_env(e1, rec_1)
        wrap_env(e2, rec_2)
        emps = [x["id"] for x in e1.call("list_employees", {}).data["employees"]]
        e2.call("list_employees", {})

        ni_days = 3 if quick else 5
        for day_i in range(1, ni_days):
            asg = {e: ("A" if j % 2 == 0 else "B") for j, e in enumerate(emps[:10])}
            e1.call("plant_canary", {"doc_title": f"Memo {day_i}", "assignment": asg})
            e2.call("plant_canary", {"doc_title": f"Memo {day_i}", "assignment": asg})
            if day_i == 1:
                e1.call("restrict_access", {"employee": emps[0]})
                e2.call("restrict_access", {"employee": emps[0]})
            e2.call("status", {})
            e2.call("list_documents", {"day_from": 1, "day_to": day_i})
            e2.call("check_leak_feed", {})
            for t_idx in range(3):
                e2.call("interview", {"employee": emps[(day_i + t_idx) % len(emps)], "topic": TOPICS[t_idx]})
            e2.call("search_messages", {"query": "project"})
            e2.call("read_access_logs", {"day_from": 1, "day_to": day_i})
            e1.call("advance_day", {})
            e2.call("advance_day", {})
            non_interference_steps += 1
        if rec_1 != rec_2:
            non_interference_diffs += 1

    always_leak_dsl = MoleStrategy.from_json(
        {"name": "always_leak_frame", "rules": [], "default": {"leak": "newest", "frame": "decoy"}}
    )
    extreme_params = {
        "W1": np.zeros((len(RL_FEATURE_NAMES) + 1, 4), dtype=np.float64),
        "b1": np.zeros(4, dtype=np.float64),
        "Wl": np.zeros((4, len(LEAK_SELECTORS)), dtype=np.float64),
        "bl": np.array([100.0, 0.0, 0.0, 0.0, 0.0, -100.0], dtype=np.float64),
        "Wf": np.zeros((4, len(FRAME_SELECTORS)), dtype=np.float64),
        "bf": np.array([100.0, 0.0, 0.0, -100.0], dtype=np.float64),
    }
    extreme_rl = RLMole(extreme_params, greedy=False, name="extreme_rl_stress")

    p_leak_bypass_count = 0
    unheld_or_window_or_repeat_violations = 0
    framing_cap_violations = 0
    restricted_mole_post_window_leaks = 0
    eligible_days_total = 0
    can_leak_true_total = 0
    actual_leaks_under_always = 0
    clearance_never_binds_ok = True

    stress_strats = (
        ("default_v0", moles["default_v0"]),
        ("hof_v12", moles["hof_v12"]),
        ("hof_v13", moles["hof_v13"]),
        ("rl_final", moles["rl_final"]),
        ("always_dsl", always_leak_dsl),
        ("extreme_rl", extreme_rl),
    )

    stress_seeds = seeds[:6] if quick else seeds
    for idx, s in enumerate(stress_seeds):
        st_name, st_obj = stress_strats[idx % len(stress_strats)]
        env = Env("hard", s, mole_strategy=st_obj)
        mole = env._world.mole
        emps = env.call("list_employees", {}).data["employees"]
        if any(e.get("clearance") not in (1, 2, 3) for e in emps):
            clearance_never_binds_ok = False
        all_asg = {e["id"]: ("A", "B", "C")[i % 3] for i, e in enumerate(emps)}
        c_res = env.call("plant_canary", {"doc_title": "Full staff canary", "assignment": all_asg})
        if not c_res.ok:
            clearance_never_binds_ok = False

        restrict_mole_mode = (idx % 4 == 0)
        if restrict_mole_mode:
            env.call("restrict_access", {"employee": mole})

        step_records: list[tuple[int, MoleView, dict[str, Any], set[str], set[str]]] = []
        orig_mv = env._mole_view
        orig_md = env._mole_decide
        last_view_box: list[MoleView] = []

        def mv_hook(d: int, _o=orig_mv, _box=last_view_box):
            v = _o(d)
            _box.clear()
            _box.append(v)
            return v

        def md_hook(v: MoleView, _o=orig_md, _env=env, _recs=step_records):
            held_snap = set(_env._held[_env._world.mole])
            leaked_snap = set(_env._leaked)
            dec = _o(v)
            _recs.append((_env.day, v, dec, held_snap, leaked_snap))
            return dec

        env._mole_view = mv_hook
        env._mole_decide = md_hook

        n_sim_days = 4 if quick else 10
        for _ in range(n_sim_days):
            if env.done:
                break
            env.call("advance_day", {})

        framed_by_day: dict[int, int] = {}
        for e in env.ledger():
            if e.event == "framed":
                framed_by_day[e.day] = framed_by_day.get(e.day, 0) + 1
                tgt = e.detail.get("employee")
                if tgt == mole or tgt not in env._idset or not env._held[tgt]:
                    framing_cap_violations += 1
        if any(cnt > 1 for cnt in framed_by_day.values()):
            framing_cap_violations += 1

        for d_num, v, dec, held_snap, leaked_snap in step_records:
            lk = dec.get("leak")
            if v.docs:
                eligible_days_total += 1
                if v.can_leak:
                    can_leak_true_total += 1
            if not v.can_leak and lk is not None:
                p_leak_bypass_count += 1
            if lk is not None:
                lo = d_num - env.p.leak_window_days + 1
                doc_meta = env._doc_by_id.get(lk)
                if (
                    lk not in held_snap
                    or lk in leaked_snap
                    or doc_meta is None
                    or not (lo <= doc_meta["day"] <= d_num)
                ):
                    unheld_or_window_or_repeat_violations += 1
            if restrict_mole_mode and d_num >= 1 + env.p.leak_window_days:
                if len(v.docs) > 0 or lk is not None:
                    restricted_mole_post_window_leaks += 1
            if st_name in ("always_dsl", "extreme_rl") and v.docs and lk is not None:
                actual_leaks_under_always += 1

    emp_p_leak = can_leak_true_total / eligible_days_total if eligible_days_total else 0.0
    p_leak_binom_pval = exact_binom_two_sided(can_leak_true_total, eligible_days_total, rules.TIERS["hard"].p_leak)

    peek_fixtures = _build_canary_peek_fixtures(seeds, quick=quick)
    detector_results = {
        "default_v0": detect_canary_peeking(moles["default_v0"], seeds, prebuilt_fixtures=peek_fixtures),
        "hof_v12": detect_canary_peeking(moles["hof_v12"], seeds, prebuilt_fixtures=peek_fixtures),
        "hof_v13": detect_canary_peeking(moles["hof_v13"], seeds, prebuilt_fixtures=peek_fixtures),
        "rl_final": detect_canary_peeking(moles["rl_final"], seeds, prebuilt_fixtures=peek_fixtures),
        "rl_it80": detect_canary_peeking(moles["rl_it80"], seeds, prebuilt_fixtures=peek_fixtures),
        "cheating_whitebox_is_canary": detect_canary_peeking(
            CheatingCanaryPeekMole(), seeds, bind_env_lookup=True, prebuilt_fixtures=peek_fixtures
        ),
        "cheating_doc_id_prefix": detect_canary_peeking(
            CheatingCanaryPeekMole(use_doc_id_prefix=True),
            seeds,
            bind_env_lookup=False,
            prebuilt_fixtures=peek_fixtures,
        ),
    }

    live_impact_seeds = seeds[:1] if quick else list(range(6000, 6050))
    def_canary_leaks = 0
    def_reg_leaks = 0
    cheat_canary_leaks = 0
    cheat_reg_leaks = 0
    for s in live_impact_seeds:
        e_def = Env("hard", s, mole_strategy=moles["default_v0"])
        run_episode(e_def, CALIBRATION_POLICIES["heuristic"](seed=s))
        for le in e_def.ledger():
            if le.event == "leak":
                if e_def._doc_by_id[le.detail["doc_id"]]["is_canary"]:
                    def_canary_leaks += 1
                else:
                    def_reg_leaks += 1

        e_ch = Env("hard", s)
        e_ch._world.mole_strategy = CheatingCanaryPeekMole(
            canary_lookup=lambda did, db=e_ch._doc_by_id: bool(db.get(did, {}).get("is_canary"))
        )
        run_episode(e_ch, CALIBRATION_POLICIES["heuristic"](seed=s))
        for le in e_ch.ledger():
            if le.event == "leak":
                if e_ch._doc_by_id[le.detail["doc_id"]]["is_canary"]:
                    cheat_canary_leaks += 1
                else:
                    cheat_reg_leaks += 1

    lawful_clean = all(
        not detector_results[k]["canary_peeking_detected"] and detector_results[k]["p_value"] > 0.01
        for k in ("default_v0", "hof_v12", "hof_v13", "rl_final", "rl_it80")
    )
    positive_controls_caught = (
        detector_results["cheating_whitebox_is_canary"]["canary_peeking_detected"]
        and detector_results["cheating_whitebox_is_canary"]["p_value"] < 1e-6
        and detector_results["cheating_doc_id_prefix"]["canary_peeking_detected"]
        and detector_results["cheating_doc_id_prefix"]["p_value"] < 1e-6
    )

    all_ok = (
        len(schema_forbidden_hits) == 0
        and is_canary_exposures == 0
        and variant_map_exposures == 0
        and world_seed_exposures == 0
        and interview_signal_exposures == 0
        and investigator_belief_exposures == 0
        and rl_feature_bounds_violations == 0
        and variant_perm_diffs == 0
        and canary_flag_dsl_diffs == 0
        and canary_flag_rl_diffs == 0
        and canary_flag_det_selector_diffs == 0
        and careful_weight_formula_mismatches == 0
        and non_interference_diffs == 0
        and p_leak_bypass_count == 0
        and unheld_or_window_or_repeat_violations == 0
        and framing_cap_violations == 0
        and restricted_mole_post_window_leaks == 0
        and clearance_never_binds_ok
        and lawful_clean
        and positive_controls_caught
    )

    return {
        "n_seeds": len(seeds),
        "mole_doc_fields": list(mole_doc_fields),
        "mole_view_fields": list(mole_view_fields),
        "dsl_features": list(DSL_FEATURES),
        "rl_feature_names": list(RL_FEATURE_NAMES),
        "schema_forbidden_hits": schema_forbidden_hits,
        "views_inspected": views_inspected,
        "secret_exposures": {
            "is_canary": is_canary_exposures,
            "variant_maps": variant_map_exposures,
            "world_seed": world_seed_exposures,
            "interview_signals": interview_signal_exposures,
            "investigator_beliefs": investigator_belief_exposures,
            "rl_feature_bounds_violations": rl_feature_bounds_violations,
        },
        "canary_mutation_probes": {
            "n_seeds_probed": len(mut_seeds),
            "variant_permutation_diffs": variant_perm_diffs,
            "is_canary_dsl_feature_diffs": canary_flag_dsl_diffs,
            "is_canary_rl_feature_diffs": canary_flag_rl_diffs,
            "is_canary_deterministic_selector_diffs": canary_flag_det_selector_diffs,
            "careful_weight_formula_mismatches": careful_weight_formula_mismatches,
        },
        "interview_and_belief_non_interference": {
            "n_seeds_probed": len(ni_seeds),
            "mole_steps_compared": non_interference_steps,
            "divergences": non_interference_diffs,
        },
        "action_boundary_enforcement": {
            "n_seeds_probed": len(stress_seeds),
            "p_leak_bypass_count": p_leak_bypass_count,
            "eligible_days_total": eligible_days_total,
            "can_leak_true_total": can_leak_true_total,
            "empirical_can_leak_rate": round(emp_p_leak, 6),
            "documented_hard_p_leak": rules.TIERS["hard"].p_leak,
            "p_leak_binomial_two_sided_p": round(p_leak_binom_pval, 6),
            "actual_leaks_under_always_policies": actual_leaks_under_always,
            "unheld_or_window_or_repeat_violations": unheld_or_window_or_repeat_violations,
            "framing_cap_violations": framing_cap_violations,
            "restricted_mole_post_window_leaks": restricted_mole_post_window_leaks,
            "panel_fix_a_clearance_never_binds": clearance_never_binds_ok,
        },
        "canary_peeking_detector": detector_results,
        "live_cheating_episode_impact": {
            "n_seeds": len(live_impact_seeds),
            "default_mole_canary_leaks": def_canary_leaks,
            "default_mole_regular_leaks": def_reg_leaks,
            "cheating_mole_canary_leaks": cheat_canary_leaks,
            "cheating_mole_regular_leaks": cheat_reg_leaks,
        },
        "lawful_moles_all_clean": lawful_clean,
        "positive_controls_caught_below_1e6": positive_controls_caught,
        "all_ok": all_ok,
        "seconds": round(time.time() - t0, 2),
    }


def _run_with_mole_capture(tier: str, seed: int, strat: Any, policy: Any) -> tuple[list[Any], list[Any]]:
    env = Env(tier, seed, mole_strategy=strat)
    captured: list[Any] = []
    orig_md = env._mole_decide

    def wrapped_md(view: MoleView):
        st_before = env._dyn.getstate()
        dec = orig_md(view)
        st_after = env._dyn.getstate()
        captured.append((view, st_before, dec, st_after))
        return dec

    env._mole_decide = wrapped_md
    run_episode(env, policy)
    ev = [
        (seed, e.day, e.event, e.detail.get("doc_id") or e.detail.get("employee"))
        for e in env.ledger()
        if e.event in ("leak", "framed")
    ]
    return ev, captured


def exact_trace_dedupe(
    strats: list[Any],
    seeds: list[int],
    agent_name: str = "do_nothing",
    tier: str = "hard",
    quick: bool = False,
) -> dict[str, Any]:
    groups_cache: list[dict[int, tuple[list[Any], list[Any]]]] = []
    out_sigs: dict[str, list[int]] = {}
    per_strat_seed_hashes: list[list[str]] = []
    n_env_runs = 0

    for idx, st in enumerate(strats):
        all_ev: list[Any] = []
        seed_hashes: list[str] = []
        for s in seeds:
            matched_ev = None
            for rep_traces in groups_cache:
                if s in rep_traces:
                    rep_ev, cap = rep_traces[s]
                    ok = True
                    r = random.Random()
                    for view, rng_before, rep_dec, rng_after in cap:
                        r.setstate(rng_before)
                        d2 = st.decide(view, r)
                        if d2 != rep_dec or r.getstate() != rng_after:
                            ok = False
                            break
                    if ok:
                        matched_ev = rep_ev
                        break
            if matched_ev is None:
                n_env_runs += 1
                pol = make_investigator(agent_name, s, quick=quick)
                ev, cap = _run_with_mole_capture(tier, s, st, pol)
                matched_ev = ev
                placed = False
                for rep_traces in groups_cache:
                    if s not in rep_traces:
                        rep_traces[s] = (ev, cap)
                        placed = True
                        break
                if not placed:
                    groups_cache.append({s: (ev, cap)})
            all_ev.extend(matched_ev)
            seed_hashes.append(hashlib.sha256(json.dumps(matched_ev).encode()).hexdigest()[:12])
        per_strat_seed_hashes.append(seed_hashes)
        h = hashlib.sha256(json.dumps(all_ev).encode()).hexdigest()[:16]
        out_sigs.setdefault(h, []).append(idx + 1)

    total_pairs = len(strats) * len(seeds)
    majority_hash = max(out_sigs.items(), key=lambda kv: len(kv[1]))[0]
    maj_idx = out_sigs[majority_hash][0] - 1
    matching_seed_cells = sum(
        1
        for sh_list in per_strat_seed_hashes
        for k, sh in enumerate(sh_list)
        if sh == per_strat_seed_hashes[maj_idx][k]
    )

    return {
        "n_strategies": len(strats),
        "n_seeds": len(seeds),
        "n_outcome_groups": len(out_sigs),
        "outcome_groups": out_sigs,
        "env_episodes_needed": n_env_runs,
        "total_strategy_seed_cells": total_pairs,
        "majority_group_seed_cell_agreement": round(matching_seed_cells / max(1, total_pairs), 6),
    }


def run_part_b_dedupe(
    seeds: list[int],
    quick: bool = False,
    moles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    if moles is None:
        moles = load_committed_moles()

    src12_path = ROOT / "fr8" / "analysis" / "out" / "forge_v12_hof_source_gen500.jsonl"
    src13_path = ROOT / "fr8" / "analysis" / "out" / "forge_v13_hof_source_gen300.jsonl"
    src12_rows = [json.loads(x) for x in src12_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    src13_rows = [json.loads(x) for x in src13_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    dedupe_rows_12 = src12_rows[:1] if quick else src12_rows
    dedupe_rows_13 = src13_rows[:1] if quick else src13_rows
    src12_strats = [MoleStrategy.from_json(r["strategy_json"]) for r in dedupe_rows_12]
    src13_strats = [MoleStrategy.from_json(r["strategy_json"]) for r in dedupe_rows_13]

    v12_canon = canonical(moles["hof_v12_row"]["strategy_json"])
    v13_canon = canonical(moles["hof_v13_row"]["strategy_json"])
    v12_source_match_ranks = [
        r["rank"] for r in src12_rows if canonical(r["strategy_json"]) == v12_canon
    ]
    v13_source_match_ranks = [
        r["rank"] for r in src13_rows if canonical(r["strategy_json"]) == v13_canon
    ]

    rl_hof_params = moles["rl_hof_row"]["strategy_json"]["params"]
    rl_final_params = moles["rl_final_json"]["params"]
    rl_it80_params = moles["rl_it80_json"]["params"]
    max_diff_hof_vs_final = max(
        float(np.max(np.abs(np.asarray(rl_hof_params[k]) - np.asarray(rl_final_params[k]))))
        for k in rl_hof_params
    )
    max_diff_final_vs_it80 = max(
        float(np.max(np.abs(np.asarray(rl_final_params[k]) - np.asarray(rl_it80_params[k]))))
        for k in rl_final_params
    )

    v13_check_seeds = [6000] if quick else list(range(6000, 6020))
    with rules.tiers_version("v1.3"):
        v12_on_v13_dn = exact_trace_dedupe(src12_strats, v13_check_seeds, "do_nothing", "hard", quick=quick)
        v12_on_v13_sol = exact_trace_dedupe(src12_strats, v13_check_seeds, "solver", "hard", quick=quick)
        v13_on_v13_dn = exact_trace_dedupe(src13_strats, v13_check_seeds, "do_nothing", "hard", quick=quick)
        v13_on_v13_sol = exact_trace_dedupe(src13_strats, v13_check_seeds, "solver", "hard", quick=quick)

    v12_on_v14_dn = exact_trace_dedupe(src12_strats, seeds, "do_nothing", "hard", quick=quick)
    v13_on_v14_dn = exact_trace_dedupe(src13_strats, seeds, "do_nothing", "hard", quick=quick)

    primary_list = [
        ("default_v0", moles["default_v0"]),
        ("hof_v12", moles["hof_v12"]),
        ("hof_v13", moles["hof_v13"]),
        ("rl_final", moles["rl_final"]),
        ("rl_it80", moles["rl_it80"]),
    ]
    primary_hashes: dict[str, str] = {}
    for label, st in primary_list:
        ev_all = []
        for s in seeds:
            env = Env("hard", s, mole_strategy=st)
            run_episode(env, BASELINES["do_nothing"](seed=s))
            for e in env.ledger():
                if e.event in ("leak", "framed"):
                    ev_all.append((s, e.day, e.event, e.detail.get("doc_id") or e.detail.get("employee")))
        primary_hashes[label] = hashlib.sha256(json.dumps(ev_all).encode()).hexdigest()[:16]

    track_equiv_seeds = seeds[:1] if quick else seeds[:20]
    hard_forge_matches_v12 = True
    prev_env = os.environ.pop("CANARY_FORGE_HOF", None)
    try:
        for s in track_equiv_seeds:
            e_track = Env("hard_forge", s)
            e_direct = Env("hard_forge", s, mole_strategy=moles["hof_v12"])
            run_episode(e_track, BASELINES["do_nothing"](seed=s))
            run_episode(e_direct, BASELINES["do_nothing"](seed=s))
            if e_track.ledger() != e_direct.ledger():
                hard_forge_matches_v12 = False
                break
    finally:
        if prev_env is not None:
            os.environ["CANARY_FORGE_HOF"] = prev_env

    configs_audit = {
        "default_forge_hof_file": forge_track.DEFAULT_HOF.name,
        "default_rl_hof_file": str(forge_track.DEFAULT_RL_HOF.relative_to(ROOT)),
        "hof_v12_entries": 1,
        "hof_v13_entries": 1,
        "hof_v14_exists": moles["hof_v14_exists"],
        "rl_hof_entries": 1,
        "forge_yaml_exists": (ROOT / "configs" / "agents" / "forge.yaml").is_file(),
        "forge_gemini_yaml_exists": (ROOT / "configs" / "agents" / "forge_gemini.yaml").is_file(),
        "mole_arena_yaml_exists": (ROOT / "configs" / "agents" / "mole_arena.yaml").is_file(),
        "hard_forge_unset_env_matches_hof_v12": hard_forge_matches_v12,
    }

    return {
        "configs_and_files": configs_audit,
        "v12_survivor_source_ranks": v12_source_match_ranks,
        "v13_survivor_source_ranks": v13_source_match_ranks,
        "src12_unique_canonical_json": len({canonical(r["strategy_json"]) for r in src12_rows}),
        "src13_unique_canonical_json": len({canonical(r["strategy_json"]) for r in src13_rows}),
        "rl_hof_vs_policy_final_max_abs_diff": max_diff_hof_vs_final,
        "rl_final_vs_policy_it80_max_abs_diff": round(max_diff_final_vs_it80, 6),
        "v13_rules_dedupe": {
            "seeds": [v13_check_seeds[0], v13_check_seeds[-1]],
            "v12_source_do_nothing": v12_on_v13_dn,
            "v12_source_solver": v12_on_v13_sol,
            "v13_source_do_nothing": v13_on_v13_dn,
            "v13_source_solver": v13_on_v13_sol,
        },
        "v14_rules_dedupe": {
            "seeds": [seeds[0], seeds[-1]],
            "v12_source_do_nothing": v12_on_v14_dn,
            "v13_source_do_nothing": v13_on_v14_dn,
        },
        "primary_committed_moles_outcome_hashes": primary_hashes,
        "primary_committed_moles_distinct_count": len(set(primary_hashes.values())),
        "seconds": round(time.time() - t0, 2),
    }


def evaluate_mole_against_policies(
    mole_key: str,
    tier: str,
    env_factory: Callable[[int], Env],
    seeds: list[int],
    quick: bool = False,
) -> dict[str, Any]:
    t0 = time.time()
    p = rules.tier_params(tier)
    w0 = generate_world(tier, seeds[0], p)
    per_policy: dict[str, Any] = {}

    for pol_name in ALL_POLICIES:
        pt0 = time.time()
        scores: list[float] = []
        corrects: list[bool] = []
        accused_flags: list[bool] = []
        accuse_days: list[int] = []
        luck_evs: list[float] = []
        canary_calls = 0
        non_solver_exploits = 0

        for s in seeds:
            env = env_factory(s)
            pol = make_investigator(pol_name, s, quick=quick)
            res = run_episode(env, pol)
            sc = float(res.score)
            corr = bool(res.correct)
            did_acc = res.accused is not None
            scores.append(sc)
            corrects.append(corr)
            accused_flags.append(did_acc)
            if did_acc:
                accuse_days.append(int(res.final_day))

            c_calls = sum(1 for st in res.steps if st.tool == "plant_canary" and st.result.get("ok"))
            canary_calls += c_calls

            acc_events = [e for e in env.ledger() if e.event == "accused"]
            single_true = len(acc_events) == 1 and acc_events[0].detail.get("employee") == env._world.mole
            if sc > 0.0 and not single_true:
                non_solver_exploits += 1

            if pol_name == "solver":
                if did_acc and hasattr(pol, "post") and isinstance(pol.post, dict) and res.accused in pol.post:
                    p_acc = float(pol.post[res.accused])
                    luck_evs.append(p_acc * float(env.V) - (1.0 - p_acc))
                else:
                    luck_evs.append(0.0)

        n = len(scores)
        n_acc = sum(accused_flags)
        mean_sc = sum(scores) / n
        acc_rate = sum(corrects) / n
        entry: dict[str, Any] = {
            "n": n,
            "mean_score": round(mean_sc, 4),
            "ci95": round(ci95(scores), 4),
            "min_score": round(min(scores), 4),
            "max_score": round(max(scores), 4),
            "accuracy": round(acc_rate, 4),
            "correct_count": sum(corrects),
            "accused_rate": round(n_acc / n, 4),
            "acc_among_accused": round(sum(corrects) / n_acc, 4) if n_acc else None,
            "mean_accuse_day": round(sum(accuse_days) / len(accuse_days), 2) if accuse_days else None,
            "positive_episodes": sum(1 for x in scores if x > 0.0),
            "canary_calls_total": canary_calls,
            "non_solver_positive_exploits": non_solver_exploits,
            "seconds": round(time.time() - pt0, 2),
        }
        if pol_name == "solver":
            entry["luck_adjusted_ev_mean"] = round(sum(luck_evs) / len(luck_evs), 4)
            entry["luck_adjusted_ev_ci95"] = round(ci95(luck_evs), 4)
            entry["passes_min_acc_075"] = acc_rate >= MIN_ACC
        per_policy[pol_name] = entry

    solver_mean = per_policy["solver"]["mean_score"]
    strongest_baseline = max(ALL_BASELINES, key=lambda b: per_policy[b]["mean_score"])
    strongest_baseline_score = per_policy[strongest_baseline]["mean_score"]
    min_regret = round(solver_mean - strongest_baseline_score, 4)

    non_canary_zero_canary_calls = all(
        per_policy[b]["canary_calls_total"] == 0 for b in NON_CANARY_BASELINES
    )
    do_nothing_zero = (
        per_policy["do_nothing"]["min_score"] == 0.0 and per_policy["do_nothing"]["max_score"] == 0.0
    )
    stop_early_zero = (
        per_policy["stop_early"]["min_score"] == 0.0 and per_policy["stop_early"]["max_score"] == 0.0
    )
    accusing_non_canary_negative = all(
        per_policy[b]["mean_score"] < 0.0
        for b in ("guess_day1", "restrict_all", "accuse_decoy", "logs_only", "accuse_most_logs")
    )
    zero_non_solver_exploits = all(
        per_policy[p_name]["non_solver_positive_exploits"] == 0 for p_name in ALL_POLICIES
    )
    all_baselines_below_solver = all(
        per_policy[b]["mean_score"] < solver_mean for b in ALL_BASELINES
    )

    return {
        "mole_key": mole_key,
        "tier": tier,
        "dept_count": len(w0.depts),
        "depts": sorted(w0.depts),
        "seeds": [seeds[0], seeds[-1]],
        "n_seeds": len(seeds),
        "per_policy": per_policy,
        "solver_mean_score": solver_mean,
        "solver_accuracy": per_policy["solver"]["accuracy"],
        "solver_luck_adjusted_ev": per_policy["solver"]["luck_adjusted_ev_mean"],
        "passes_min_acc_075": per_policy["solver"]["passes_min_acc_075"],
        "strongest_baseline": strongest_baseline,
        "strongest_baseline_score": strongest_baseline_score,
        "min_regret_vs_baselines": min_regret,
        "checks": {
            "do_nothing_exact_zero": do_nothing_zero,
            "stop_early_exact_zero": stop_early_zero,
            "non_canary_zero_canary_calls": non_canary_zero_canary_calls,
            "accusing_non_canary_all_negative": accusing_non_canary_negative,
            "zero_non_solver_positive_exploits": zero_non_solver_exploits,
            "all_baselines_strictly_below_solver": all_baselines_below_solver,
        },
        "seconds": round(time.time() - t0, 2),
    }


def _eval_solver_slice(
    env_factory: Callable[[int], Env],
    seeds: list[int],
    quick: bool = False,
) -> dict[str, Any]:
    scores: list[float] = []
    corrects: list[bool] = []
    luck_evs: list[float] = []
    days: list[int] = []
    for s in seeds:
        env = env_factory(s)
        pol = make_investigator("solver", s, quick=quick)
        res = run_episode(env, pol)
        scores.append(float(res.score))
        corrects.append(bool(res.correct))
        days.append(int(res.final_day))
        if res.accused is not None and res.accused in pol.post:
            p_acc = float(pol.post[res.accused])
            luck_evs.append(p_acc * float(env.V) - (1.0 - p_acc))
        else:
            luck_evs.append(0.0)
    n = len(scores)
    acc = sum(corrects) / n
    return {
        "n": n,
        "seeds": [seeds[0], seeds[-1]],
        "mean_score": round(sum(scores) / n, 4),
        "ci95": round(ci95(scores), 4),
        "accuracy": round(acc, 4),
        "correct_count": sum(corrects),
        "luck_adjusted_ev_mean": round(sum(luck_evs) / n, 4),
        "mean_final_day": round(sum(days) / n, 2),
        "passes_min_acc_075": acc >= MIN_ACC,
    }


def run_part_b_crosscheck(quick: bool = False, moles: dict[str, Any] | None = None) -> dict[str, Any]:
    t0 = time.time()
    if moles is None:
        moles = load_committed_moles()
    dev30_seeds = [0] if quick else list(range(0, 30))
    rl_heldout_seeds = [200000] if quick else list(range(200000, 200100))
    v13_seeds = [6000] if quick else list(range(6000, 6040))

    dev30_5dept = _eval_solver_slice(
        lambda s: Env("hard", s, mole_strategy=moles["rl_final"]), dev30_seeds, quick=quick
    )
    dev30_4dept = _eval_solver_slice(lambda s: Env("hard_rl", s), dev30_seeds, quick=quick)

    held100_5dept = _eval_solver_slice(
        lambda s: Env("hard", s, mole_strategy=moles["rl_final"]), rl_heldout_seeds, quick=quick
    )
    held100_4dept = _eval_solver_slice(lambda s: Env("hard_rl", s), rl_heldout_seeds, quick=quick)

    with rules.tiers_version("v1.3"):
        v13_hof12 = _eval_solver_slice(
            lambda s: Env("hard", s, mole_strategy=moles["hof_v12"]), v13_seeds, quick=quick
        )
        v13_hof13 = _eval_solver_slice(
            lambda s: Env("hard", s, mole_strategy=moles["hof_v13"]), v13_seeds, quick=quick
        )

    sample_seeds = [0, 1] if quick else list(range(6000, 6200))
    rec_hard: list[int] = []
    rec_hard_rl: list[int] = []
    for s in sample_seeds:
        wh = generate_world("hard", s, rules.tier_params("hard"))
        wr = generate_world("hard_rl", s, rules.tier_params("hard_rl"))
        for docs in wh.planned_docs.values():
            for d in docs:
                rec_hard.append(len(d["recipients"]))
        for docs in wr.planned_docs.values():
            for d in docs:
                rec_hard_rl.append(len(d["recipients"]))

    return {
        "issue_w1_hard_rl_depts": {
            "hard_depts": 5,
            "hard_rl_depts": 4,
            "missing_dept": "Research",
            "hard_mean_recipients": round(sum(rec_hard) / len(rec_hard), 4),
            "hard_rl_mean_recipients": round(sum(rec_hard_rl) / len(rec_hard_rl), 4),
            "dev_0_29_posthoc_lock_slice": {
                "hard_5dept": dev30_5dept,
                "hard_rl_4dept": dev30_4dept,
                "acc_delta_4dept_minus_5dept": round(dev30_4dept["accuracy"] - dev30_5dept["accuracy"], 4),
                "score_delta_4dept_minus_5dept": round(dev30_4dept["mean_score"] - dev30_5dept["mean_score"], 4),
            },
            "rl_heldout_200000_200099_slice": {
                "hard_5dept": held100_5dept,
                "hard_rl_4dept": held100_4dept,
                "acc_delta_4dept_minus_5dept": round(held100_4dept["accuracy"] - held100_5dept["accuracy"], 4),
                "score_delta_4dept_minus_5dept": round(held100_4dept["mean_score"] - held100_5dept["mean_score"], 4),
            },
        },
        "v13_solver_reference": {
            "hof_v12_on_v13": v13_hof12,
            "hof_v13_on_v13": v13_hof13,
        },
        "seconds": round(time.time() - t0, 2),
    }


def _counting_factory(base_factory: Callable[[str, int], Any]):
    ep_counter = itertools.count(0)
    call_counter = itertools.count(0)

    def factory(tier: str, seed: int):
        env = base_factory(tier, seed)
        next(ep_counter)
        orig_call = env.call

        def wrapped_call(tool: str, args: Any):
            next(call_counter)
            return orig_call(tool, args)

        env.call = wrapped_call
        return env

    def read_counts() -> tuple[int, int]:
        return next(ep_counter), next(call_counter)

    return factory, read_counts


def run_part_c_fuzz_target(
    mole_key: str,
    tier: str,
    base_env_factory: Callable[[int], Any],
    seeds: list[int],
    budget: int,
    rng_seed: int = 0,
    quick: bool = False,
) -> dict[str, Any]:
    t0 = time.time()
    cfac, read_counts = _counting_factory(lambda _t, s: base_env_factory(s))
    fuzz_mode = "evolve" if quick else "all"
    res = fuzz.hunt(
        tier=tier,
        seeds=seeds,
        budget=budget,
        seed=rng_seed,
        mode=fuzz_mode,
        workers=1,
        factory=cfac,
    )
    eps, calls = read_counts()
    return {
        "mole_key": mole_key,
        "tier": tier,
        "seeds": [seeds[0], seeds[-1]],
        "n_seeds": len(seeds),
        "budget": budget,
        "rng_seed": rng_seed,
        "episode_evaluations": eps,
        "tool_call_evaluations": calls,
        "best_non_solver_score": float(res["best_non_solver_score"]),
        "best_score_per_call": round(float(res["best_score_per_call"]), 6),
        "n_violations": len(res["invariant_violations"]),
        "violation_kinds": list(res["violation_kinds"]),
        "per_mode": res.get("per_mode"),
        "seconds": round(time.time() - t0, 2),
    }


def check_report_text(report_path: Path, summary: dict[str, Any] | None = None) -> dict[str, Any]:
    text = report_path.read_text(encoding="utf-8")
    forbidden_dashes = [d for d in (chr(0x2014), chr(0x2013), chr(0x2212)) if d in text]
    forbidden_prereg = [p for p in ("pre-reg", "prereg") if p in text.lower()]
    required_phrases = [
        "MoleView",
        "RLMole",
        "CheatingCanaryPeekMole",
        "ISSUE-W1-HARD-RL-DEPTS",
        "ISSUE-W6-DEFAULT-HOF-V12-AND-NO-V14",
        "ISSUE-W6-ARENA-LLM-MOLE-SURFACE",
        "MIN_ACC = 0.75",
        "hall_of_fame_v1.2.jsonl",
        "hall_of_fame_v1.3.jsonl",
        "hall_of_fame_v1.4.jsonl",
        "data/rl_mole/hall_of_fame.jsonl",
        "swarm_w2b008",
        "grok_tactics",
        "post-hoc lock",
        "clearance",
    ]
    missing_phrases = [p for p in required_phrases if p not in text]
    mismatch_numbers: list[str] = []
    if summary is not None and not summary.get("quick"):
        if summary.get("part_a") is not None:
            vi_str = str(summary["part_a"]["views_inspected"])
            if vi_str not in text:
                mismatch_numbers.append(f"part_a:views_inspected={vi_str}")
        for mk in MOLE_ROW_ORDER:
            row = summary["part_b"]["matrix"].get(mk)
            if row is not None:
                for field in ("solver_mean_score", "solver_accuracy", "solver_luck_adjusted_ev", "min_regret_vs_baselines"):
                    val_str = f"{row[field]:.4f}"
                    if val_str not in text:
                        mismatch_numbers.append(f"{mk}:{field}={val_str}")
        if summary["part_b"].get("crosscheck") is not None:
            w1 = summary["part_b"]["crosscheck"]["issue_w1_hard_rl_depts"]
            for slice_key in ("dev_0_29_posthoc_lock_slice", "rl_heldout_200000_200099_slice"):
                sl = w1[slice_key]
                for sub_key in ("hard_5dept", "hard_rl_4dept"):
                    for field in ("mean_score", "accuracy"):
                        val_str = f"{sl[sub_key][field]:.4f}"
                        if val_str not in text:
                            mismatch_numbers.append(f"{slice_key}:{sub_key}:{field}={val_str}")
        if summary["part_c"].get("fuzz_complete"):
            for field in ("total_genomes", "total_episodes", "total_tool_calls"):
                val_str = str(summary["part_c"][field])
                if val_str not in text:
                    mismatch_numbers.append(f"part_c:{field}={val_str}")
    ok = not forbidden_dashes and not forbidden_prereg and not missing_phrases and not mismatch_numbers
    return {
        "ok": ok,
        "forbidden_dashes": forbidden_dashes,
        "forbidden_prereg": forbidden_prereg,
        "missing_phrases": missing_phrases,
        "mismatch_numbers": mismatch_numbers,
    }


def run_audit(
    quick: bool = False,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    workers: int = 1,
    resume: bool = False,
    only_part: str = "all",
    only_mole: str | None = None,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("workers must be 1")
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    moles = load_committed_moles()
    factories = make_mole_env_factories(moles)

    seeds_a = PART_A_QUICK_SEEDS if quick else PART_A_FULL_SEEDS
    seeds_b = PART_B_QUICK_SEEDS if quick else PART_B_FULL_SEEDS
    seeds_c = PART_C_QUICK_SEEDS if quick else PART_C_FULL_SEEDS
    budget_c = PART_C_QUICK_BUDGET if quick else PART_C_FULL_BUDGET

    part_a_file = out_root / ("part_a_quick.json" if quick else "part_a_full.json")
    part_b_dedupe_file = out_root / ("part_b_dedupe_quick.json" if quick else "part_b_dedupe_full.json")
    part_b_cross_file = out_root / ("part_b_cross_quick.json" if quick else "part_b_cross_full.json")

    part_a: dict[str, Any] | None = None
    if only_part in ("all", "a"):
        if resume and part_a_file.exists():
            part_a = json.loads(part_a_file.read_text(encoding="utf-8"))
        else:
            part_a = run_part_a_isolation_audit(seeds_a, quick=quick, moles=moles)
            part_a_file.write_text(json.dumps(part_a, indent=2) + "\n", encoding="utf-8")
    elif part_a_file.exists():
        part_a = json.loads(part_a_file.read_text(encoding="utf-8"))

    part_b_dedupe: dict[str, Any] | None = None
    if only_part in ("all", "b_dedupe"):
        if resume and part_b_dedupe_file.exists():
            part_b_dedupe = json.loads(part_b_dedupe_file.read_text(encoding="utf-8"))
        else:
            part_b_dedupe = run_part_b_dedupe(seeds_b, quick=quick, moles=moles)
            part_b_dedupe_file.write_text(json.dumps(part_b_dedupe, indent=2) + "\n", encoding="utf-8")
    elif part_b_dedupe_file.exists():
        part_b_dedupe = json.loads(part_b_dedupe_file.read_text(encoding="utf-8"))

    part_b_cross: dict[str, Any] | None = None
    if only_part in ("all", "b_crosscheck"):
        if resume and part_b_cross_file.exists():
            part_b_cross = json.loads(part_b_cross_file.read_text(encoding="utf-8"))
        else:
            part_b_cross = run_part_b_crosscheck(quick=quick, moles=moles)
            part_b_cross_file.write_text(json.dumps(part_b_cross, indent=2) + "\n", encoding="utf-8")
    elif part_b_cross_file.exists():
        part_b_cross = json.loads(part_b_cross_file.read_text(encoding="utf-8"))

    matrix_rows: dict[str, Any] = {}
    for mk in MOLE_ROW_ORDER:
        m_file = out_root / f"part_b_matrix_{mk}_{'quick' if quick else 'full'}.json"
        if only_part in ("all", "b_matrix") and (only_mole is None or only_mole == mk):
            if resume and m_file.exists():
                matrix_rows[mk] = json.loads(m_file.read_text(encoding="utf-8"))
            else:
                tier_name, _, fac = factories[mk]
                row = evaluate_mole_against_policies(mk, tier_name, fac, seeds_b, quick=quick)
                m_file.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
                matrix_rows[mk] = row
        elif m_file.exists():
            matrix_rows[mk] = json.loads(m_file.read_text(encoding="utf-8"))

    fuzz_rows: dict[str, Any] = {}
    for idx_f, mk in enumerate(FUZZ_MOLE_ORDER):
        f_file = out_root / f"part_c_fuzz_{mk}_{'quick' if quick else 'full'}.json"
        if only_part in ("all", "c") and (only_mole is None or only_mole == mk):
            if resume and f_file.exists():
                fuzz_rows[mk] = json.loads(f_file.read_text(encoding="utf-8"))
            else:
                tier_name, _, fac = factories[mk]
                frow = run_part_c_fuzz_target(
                    mk, tier_name, fac, seeds_c, budget_c, rng_seed=idx_f * 100, quick=quick
                )
                f_file.write_text(json.dumps(frow, indent=2) + "\n", encoding="utf-8")
                fuzz_rows[mk] = frow
        elif f_file.exists():
            fuzz_rows[mk] = json.loads(f_file.read_text(encoding="utf-8"))

    matrix_complete = set(matrix_rows) == set(MOLE_ROW_ORDER)
    fuzz_complete = set(fuzz_rows) == set(FUZZ_MOLE_ORDER)

    report_only_issues = [
        {
            "id": "ISSUE-W1-HARD-RL-DEPTS",
            "severity": "medium",
            "locations": ["canary/world.py:121", "canary/env.py:215", "canary/forge_track.py:89"],
            "summary": (
                "generate_world gives hard_rl 4 departments (missing Research, ~20.0 regular doc recipients) "
                "instead of 5 departments like hard and hard_forge (~16.0 recipients), lowering SolverPolicy "
                "accuracy below MIN_ACC=0.75 on 4-dept hard_rl while the identical RL mole policy passes on 5-dept hard."
            ),
        },
        {
            "id": "ISSUE-W6-DEFAULT-HOF-V12-AND-NO-V14",
            "severity": "low",
            "locations": ["canary/forge_track.py:23", "data/forge/hall_of_fame_v1.2.jsonl", "data/forge/hall_of_fame_v1.3.jsonl"],
            "summary": (
                "DEFAULT_HOF in canary/forge_track.py still points to hall_of_fame_v1.2.jsonl when CANARY_FORGE_HOF "
                "is unset (and upstream justSilas@58716742 ships no hall_of_fame_v1.4.jsonl); "
                "both v1.2 and v1.3 HoF survivors remain catchable above MIN_ACC=0.75 on v1.4."
            ),
        },
        {
            "id": "ISSUE-W6-ARENA-LLM-MOLE-SURFACE",
            "severity": "low",
            "locations": ["canary/agents/mole_arena.py:35-83", "canary/env.py:559-562"],
            "summary": (
                "Non-judge arena helper LLMMole serializes doc_id (c-prefix for canaries vs d-prefix for regular docs) "
                "and title in view_to_dict and omits checking view.can_leak in decide; judge tracks hard, hard_forge, "
                "and hard_rl strictly use MoleStrategy and RLMole via _select_leak, which never read doc_id/title and "
                "always enforce view.can_leak."
            ),
        },
    ]

    det_check_keys = (
        "do_nothing_exact_zero",
        "stop_early_exact_zero",
        "non_canary_zero_canary_calls",
        "zero_non_solver_positive_exploits",
    )
    matrix_all_integrity_pass = matrix_complete and all(
        all(matrix_rows[mk]["checks"][ck] for ck in det_check_keys)
        and (quick or all(matrix_rows[mk]["checks"].values()))
        for mk in MOLE_ROW_ORDER
    )
    five_dept_moles_pass_min_acc = matrix_complete and all(
        matrix_rows[mk]["passes_min_acc_075"]
        for mk in ("default_hard_5dept", "hof_v12_hard_5dept", "hof_v13_hard_5dept", "rl_final_hard_5dept", "rl_it80_hard_5dept")
    )
    fuzz_clean = fuzz_complete and all(
        fuzz_rows[mk]["n_violations"] == 0 and fuzz_rows[mk]["best_non_solver_score"] == 0.0
        for mk in FUZZ_MOLE_ORDER
    )

    summary = {
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": rules.KNOWN_V_MODE,
        "quick": quick,
        "workers": workers,
        "only_part": only_part,
        "only_mole": only_mole,
        "part_a": part_a,
        "part_b": {
            "deduplication": part_b_dedupe,
            "matrix": matrix_rows,
            "crosscheck": part_b_cross,
            "matrix_complete": matrix_complete,
            "all_integrity_checks_pass": matrix_all_integrity_pass,
            "five_dept_moles_pass_min_acc_075": five_dept_moles_pass_min_acc if not quick else None,
        },
        "part_c": {
            "per_mole": fuzz_rows,
            "fuzz_complete": fuzz_complete,
            "total_genomes": sum(r["budget"] for r in fuzz_rows.values()),
            "total_episodes": sum(r["episode_evaluations"] for r in fuzz_rows.values()),
            "total_tool_calls": sum(r["tool_call_evaluations"] for r in fuzz_rows.values()),
            "total_invariant_violations": sum(r["n_violations"] for r in fuzz_rows.values()),
            "best_non_solver_score": max((r["best_non_solver_score"] for r in fuzz_rows.values()), default=0.0),
            "all_clean": fuzz_clean,
        },
        "report_only_issues": report_only_issues,
        "elapsed_seconds": round(time.time() - t_start, 2),
    }

    summary_file = out_root / ("audit_summary_quick.json" if quick else "audit_summary.json")
    summary_file.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_mole_hof_and_rl_audit")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--only-part",
        choices=["all", "a", "b_dedupe", "b_matrix", "b_crosscheck", "c"],
        default="all",
    )
    ap.add_argument("--only-mole", default=None)
    ap.add_argument("--check-report", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise SystemExit("error: --workers must be 1")

    summary = run_audit(
        quick=args.quick,
        out_dir=args.out_dir,
        workers=args.workers,
        resume=args.resume,
        only_part=args.only_part,
        only_mole=args.only_mole,
    )

    if args.check_report:
        rep_check = check_report_text(Path(args.check_report), summary)
        summary["report_check"] = rep_check
        if not rep_check["ok"]:
            print(json.dumps(rep_check, indent=2))
            return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        pa_ok = summary["part_a"]["all_ok"] if summary["part_a"] else None
        pb_ok = summary["part_b"]["all_integrity_checks_pass"]
        pc_ok = summary["part_c"]["all_clean"]
        print(
            f"mole_hof_rl_audit quick={args.quick} part_a_ok={pa_ok} "
            f"part_b_ok={pb_ok} part_c_ok={pc_ok} elapsed={summary['elapsed_seconds']}s"
        )

    if summary["part_a"] is not None and not summary["part_a"]["all_ok"]:
        return 1
    if summary["part_b"]["matrix_complete"] and not summary["part_b"]["all_integrity_checks_pass"]:
        return 1
    if summary["part_c"]["fuzz_complete"] and not summary["part_c"]["all_clean"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
