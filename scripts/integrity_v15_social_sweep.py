"""Audit origin/justSilas-v15 social mechanics, anti-inversion leaks, fuzz summaries, and invariants."""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable


SOCIAL_PARAMS_V15 = {
    "rumour_rate": 2.0,
    "rumour_frame_share": 0.4,
    "grudge_pairs": 2,
    "grudge_rate": 0.5,
    "authority_day": 3,
    "p_misforward": 0.15,
}

AUTHORITY_ROLES = ("manager", "lead", "controller", "counsel")
SOCIAL_SUBJECT_RE = re.compile(r"^(rumour|unverified accusation|grudge): (e\d+)$")

SYNTH_RUMOUR_TPLS = (
    "Not saying it is {tn} for sure, but they have been acting odd lately. Could be them passing things out.",
    "Overheard something in the kitchen. People think {tn} is the one passing documents out.",
    "Is it just me or does {tn} always know things before the rest of us? My money is on them for the leaks.",
    "Gut feeling: {tn}. Always closing their laptop when I walk by.",
    "Someone told me {tn} was on the phone in the stairwell again. Make of that what you will.",
)

SYNTH_AUTHORITY_TPLS = (
    "I will say it plainly: I am confident {tn} is behind the document problem. I have not verified this yet, "
    "but I have seen enough. Treat this as my personal view until security confirms.",
    "Team, I am fairly certain the source is {tn}. No hard proof, I want to be clear this is unverified, "
    "but my instinct has rarely been wrong.",
)

SYNTH_GRUDGE_TPLS = (
    "Of course it is {tn} behind the leaks. Has anyone actually checked what they do all day?",
    "Again {tn} takes credit for my work. Would not surprise me if they were the leaker too.",
    "If anyone here is selling us out it is {tn}, I have said it before.",
)

FORBIDDEN_SUBSTRINGS = (
    "world_seed",
    "canary_world_secret",
    "seed_rumour",
    "true_mole",
    "is_mole",
    "true_culprit",
)


def parse_seed_spec(spec: str) -> list[int]:
    if ":" in spec:
        a, b = spec.split(":", 1)
        return list(range(int(a), int(b)))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def activate_repo_root(root: Path) -> None:
    resolved = str(root.resolve())
    for k in list(sys.modules):
        if k == "canary" or k.startswith("canary."):
            sys.modules.pop(k, None)
    if resolved in sys.path:
        sys.path.remove(resolved)
    sys.path.insert(0, resolved)


def git_head_sha(root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=str(root), text=True)
        return out.strip()
    except Exception:
        return "unknown"


def ci95(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))


def rate_summary(hits: int, total: int) -> dict[str, Any]:
    if total <= 0:
        return {"hits": 0, "total": 0, "rate": 0.0, "ci95": 0.0}
    p = hits / total
    se = math.sqrt(max(0.0, p * (1.0 - p)) / total)
    return {"hits": hits, "total": total, "rate": round(p, 6), "ci95": round(1.96 * se, 6)}


def mole_named_leak(text: str, mole: str) -> bool:
    m = re.escape(mole)
    pats = (
        rf"mole\W{{0,6}}{m}\b",
        rf"{m}\W{{0,12}}(is|was)\W+(the\W+)?mole",
        r"\"(is_)?mole\"\s*:",
        r"\"correct\"\s*:",
        r"\"(true_)?culprit\"\s*:",
    )
    return any(re.search(p, text, re.I) for p in pats)


def deterministic_fuzz_calls(
    tier: str,
    seeds: list[int],
    per_mode_budget: dict[str, int],
    parallel_races: int,
    threads_per_race: int,
    rng_seed: int = 0,
) -> dict[str, int]:
    from canary.redteam.fuzz import random_genome

    tier_emp_counts = {"easy": 12, "medium": 20, "hard": 40, "hard_forge": 40}
    n_emp = tier_emp_counts.get(tier, 20)
    emps = [f"e{i:02d}" for i in range(n_emp)]

    rand_budget = int(per_mode_budget.get("random", 0))
    rng = random.Random(rng_seed)
    random_calls = 0
    for _ in range(rand_budget):
        if seeds:
            rng.choice(seeds)
        g = random_genome(rng, emps)
        random_calls += len(g)

    malformed_calls = 30 * int(per_mode_budget.get("malformed", 0))
    evolve_min_calls = int(per_mode_budget.get("evolve", 0))
    active_search_modes = sum(1 for m in ("random", "malformed", "evolve") if m in per_mode_budget)
    setup_calls = active_search_modes * len(seeds)
    parity_calls = active_search_modes * min(len(seeds), 5) * 17
    parallel_calls = parallel_races * (threads_per_race + 1) if parallel_races > 0 else 0
    non_evolve_calls = random_calls + malformed_calls + setup_calls + parity_calls + parallel_calls
    return {
        "random_calls": random_calls,
        "malformed_calls": malformed_calls,
        "evolve_min_calls": evolve_min_calls,
        "parallel_accuse_calls": parallel_calls,
        "parity_calls": parity_calls,
        "setup_calls": setup_calls,
        "deterministic_non_evolve_calls": non_evolve_calls,
        "min_total_calls": non_evolve_calls + evolve_min_calls,
    }


def summarize_fuzz_dir(fuzz_dir: Path) -> dict[str, Any]:
    tier_order = {"easy": 0, "medium": 1, "hard": 2, "hard_forge": 3}
    entries: list[dict[str, Any]] = []
    if not fuzz_dir.exists():
        return {"present": False, "tiers": [], "totals": {}}
    for sub in sorted(fuzz_dir.iterdir()):
        if not sub.is_dir():
            continue
        sj = sub / "summary.json"
        fj = sub / "findings.jsonl"
        if not sj.exists():
            continue
        data = json.loads(sj.read_text())
        findings_lines = [ln for ln in fj.read_text().splitlines() if ln.strip()] if fj.exists() else []
        seeds_pair = data.get("seeds", [0, -1])
        seed_list = list(range(int(seeds_pair[0]), int(seeds_pair[1]) + 1)) if len(seeds_pair) == 2 and seeds_pair[1] >= seeds_pair[0] else []
        n_seeds = len(seed_list)
        per_mode = data.get("per_mode", {})
        search_modes = [m for m in ("random", "malformed", "evolve") if m in per_mode]
        per_mode_budget = {m: int(per_mode[m].get("budget", 0)) for m in per_mode}
        search_episodes = sum(per_mode_budget[m] for m in search_modes)
        parity_seeds = min(n_seeds, 5)
        parity_episodes = len(search_modes) * parity_seeds * 3 * 2
        par_mode = per_mode.get("parallel_accuse", {})
        parallel_races = int(par_mode.get("races", 0))
        threads_per_race = int(par_mode.get("threads_per_race", 0))
        total_episodes = search_episodes + parallel_races + parity_episodes
        tier_name = str(data.get("tier", "unknown"))
        call_stats = deterministic_fuzz_calls(
            tier=tier_name,
            seeds=seed_list,
            per_mode_budget=per_mode_budget,
            parallel_races=parallel_races,
            threads_per_race=threads_per_race,
            rng_seed=0,
        )
        entries.append({
            "dir": sub.name,
            "tier": tier_name,
            "seeds": seeds_pair,
            "n_seeds": n_seeds,
            "budget": int(data.get("budget", 0)),
            "search_episodes": search_episodes,
            "parallel_races": parallel_races,
            "threads_per_race": threads_per_race,
            "parity_episodes": parity_episodes,
            "total_episodes": total_episodes,
            "calls": call_stats,
            "best_non_solver_score": float(data.get("best_non_solver_score", 0.0)),
            "best_score_per_call": float(data.get("best_score_per_call", 0.0)),
            "per_mode_score_per_call": {m: float(per_mode[m].get("best_score_per_call", 0.0)) for m in per_mode},
            "per_mode_budget": per_mode_budget,
            "per_mode_violations": {m: int(per_mode[m].get("n_violations", 0)) for m in per_mode},
            "n_findings": int(data.get("n_findings", 0)),
            "findings_jsonl_count": len(findings_lines),
            "violation_kinds": list(data.get("violation_kinds", [])),
            "seconds": float(data.get("seconds", 0.0)),
        })
    entries.sort(key=lambda r: (tier_order.get(r["tier"], 99), r["dir"]))
    totals = {
        "n_tiers": len(entries),
        "total_budget": sum(e["budget"] for e in entries),
        "total_search_episodes": sum(e["search_episodes"] for e in entries),
        "total_parallel_races": sum(e["parallel_races"] for e in entries),
        "total_parallel_threads": sum(e["parallel_races"] * e["threads_per_race"] for e in entries),
        "total_parity_episodes": sum(e["parity_episodes"] for e in entries),
        "total_episodes": sum(e["total_episodes"] for e in entries),
        "total_random_calls": sum(e["calls"]["random_calls"] for e in entries),
        "total_malformed_calls": sum(e["calls"]["malformed_calls"] for e in entries),
        "total_evolve_min_calls": sum(e["calls"]["evolve_min_calls"] for e in entries),
        "total_parallel_accuse_calls": sum(e["calls"]["parallel_accuse_calls"] for e in entries),
        "total_parity_calls": sum(e["calls"]["parity_calls"] for e in entries),
        "total_setup_calls": sum(e["calls"]["setup_calls"] for e in entries),
        "total_deterministic_non_evolve_calls": sum(e["calls"]["deterministic_non_evolve_calls"] for e in entries),
        "min_total_calls": sum(e["calls"]["min_total_calls"] for e in entries),
        "max_best_non_solver_score": max((e["best_non_solver_score"] for e in entries), default=0.0),
        "total_invariant_violations": sum(e["n_findings"] for e in entries),
        "total_findings_jsonl_lines": sum(e["findings_jsonl_count"] for e in entries),
        "total_seconds": round(sum(e["seconds"] for e in entries), 1),
    }
    return {"present": bool(entries), "tiers": entries, "totals": totals}


def _poisson_draw(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k = 0
    prod = 1.0
    while prod > limit:
        k += 1
        prod *= rng.random()
    return k - 1


def make_synthetic_v15_factory(social_params: dict[str, Any] | None = None, plant_leak: bool = False) -> Callable[..., Any]:
    from canary.env import Env

    cfg = dict(SOCIAL_PARAMS_V15)
    if social_params:
        cfg.update(social_params)
    chan_prefix = chr(35)

    class SyntheticV15Env(Env):
        def __init__(self, tier: str = "easy", seed: int = 0, **kw: Any):
            self._seed_rumour_mode = str(kw.pop("seed_rumour_mode", "default"))
            self._social_cfg = dict(cfg)
            self._plant_leak = plant_leak
            super().__init__(tier=tier, seed=seed, **kw)

        def instruction(self) -> str:
            base = super().instruction().rstrip("\n")
            lines = [base]
            for k, v in self._social_cfg.items():
                lines.append(f"- {k}: {v}")
            return "\n".join(lines) + "\n"

        def _publish_day(self, d: int) -> None:
            for raw in self._world.planned_docs.get(d, []):
                doc = {
                    "doc_id": raw["doc_id"],
                    "title": raw["title"],
                    "day": d,
                    "recipients": [r for r in raw["recipients"] if r not in self._restricted],
                    "is_canary": False,
                }
                pm = float(self._social_cfg.get("p_misforward", 0.0))
                if pm > 0:
                    r = random.Random(f"{self._world.world_seed}:fwd:{doc['doc_id']}")
                    if r.random() < pm:
                        pool = [e for e in self._ids if e not in doc["recipients"] and e not in self._restricted]
                        if pool:
                            x = r.choice(pool)
                            doc["recipients"] = sorted(doc["recipients"] + [x])
                            doc["forwarded_to"] = x
                self._add_doc(doc)

        def _grudges(self) -> list[tuple[str, str]]:
            if not hasattr(self, "_grudge_cache"):
                r = random.Random(f"{self._world.world_seed}:grudge")
                pool = [e for e in self._ids if e != self._world.decoy]
                r.shuffle(pool)
                k = min(int(self._social_cfg.get("grudge_pairs", 0)), len(pool) // 2)
                self._grudge_cache = [tuple(sorted(pool[2 * i : 2 * i + 2])) for i in range(k)]
            return self._grudge_cache

        def _pick_seed_target(self, rng: random.Random) -> str | None:
            w = self._world
            peers = [e for e in self._ids if e != w.mole]
            sel = self._seed_rumour_mode
            if sel == "default":
                sel = "decoy" if w.decoy is not None else "random_peer"
            if sel == "decoy":
                return w.decoy
            if sel == "random_peer":
                return rng.choice(peers) if peers else None
            return None

        def _social_events(self, d: int) -> list[dict[str, str]]:
            w = self._world
            r = random.Random(f"{w.world_seed}:social:{d}")
            ids = self._ids
            ev: list[dict[str, str]] = []
            rr = float(self._social_cfg.get("rumour_rate", 0.0))
            sh = float(self._social_cfg.get("rumour_frame_share", 0.0))
            for _ in range(_poisson_draw(r, rr)):
                f = self._pick_seed_target(r) if r.random() < sh else None
                if f is not None:
                    sp = r.choice([e for e in ids if e != f])
                    t = f
                else:
                    sp = r.choice(ids)
                    t = r.choice([e for e in ids if e != sp])
                ev.append({"kind": "rumour", "speaker": sp, "target": t})
            aday = int(self._social_cfg.get("authority_day", 0))
            if aday and d == aday:
                mgrs = [e.id for e in w.employees if any(k in e.role for k in AUTHORITY_ROLES)] or list(ids)
                sp = r.choice(mgrs)
                f = self._pick_seed_target(r) if r.random() < sh else None
                t = f if f is not None and f != sp else r.choice([e for e in ids if e != sp])
                ev.append({"kind": "authority", "speaker": sp, "target": t})
            gr = float(self._social_cfg.get("grudge_rate", 0.0))
            if gr > 0:
                for a, b in self._grudges():
                    if r.random() < gr:
                        sp, t = (a, b) if r.random() < 0.5 else (b, a)
                        ev.append({"kind": "grudge", "speaker": sp, "target": t})
            return ev

        def _render_social(self, d: int, events: list[dict[str, str]]) -> list[dict[str, Any]]:
            facts = self._facts(d)
            rng = random.Random(f"text:{facts.tier}:{facts.seed}:{facts.day}:social")
            by_id = {e.id: e for e in facts.employees}
            out: list[dict[str, Any]] = []
            for k, ev in enumerate(events):
                sp, t = by_id.get(ev["speaker"]), by_id.get(ev["target"])
                if sp is None or t is None:
                    continue
                tn = f"{t.name} ({t.id})"
                kind = ev["kind"]
                if kind == "rumour":
                    ch = chan_prefix + "watercooler"
                    subj = f"rumour: {t.id}"
                    body = rng.choice(SYNTH_RUMOUR_TPLS).format(tn=tn)
                    if self._plant_leak and k == 0 and d == 1:
                        body = f"{self._world.mole} is the mole (world_seed={self._world.world_seed})"
                    rec = [e.id for e in facts.employees if e.id != sp.id]
                elif kind == "authority":
                    ch = chan_prefix + "all-staff"
                    subj = f"unverified accusation: {t.id}"
                    body = rng.choice(SYNTH_AUTHORITY_TPLS).format(tn=tn)
                    rec = [e.id for e in facts.employees if e.id != sp.id]
                else:
                    ch = chan_prefix + sp.dept.lower()
                    subj = f"grudge: {t.id}"
                    body = rng.choice(SYNTH_GRUDGE_TPLS).format(tn=tn)
                    rec = [e.id for e in facts.employees if e.dept == sp.dept and e.id != sp.id]
                out.append({
                    "id": f"m{d}-s{k}",
                    "day": d,
                    "channel": ch,
                    "sender": sp.id,
                    "recipients": rec,
                    "subject": subj,
                    "body": body,
                })
            return out

        def _t_advance_day(self, a: dict[str, Any]):
            closed = self.day
            res = super()._t_advance_day(a)
            for m in self._render_social(closed, self._social_events(closed)):
                if m["id"] not in self._messages:
                    self._messages[m["id"]] = m
                    self._msg_order.append(m["id"])
            return res

    def factory(tier: str, seed: int, seed_rumour: str = "default") -> Any:
        return SyntheticV15Env(tier=tier, seed=seed, seed_rumour_mode=seed_rumour)

    return factory


def make_real_v15_factory() -> Callable[..., Any]:
    from canary.env import Env
    from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy

    def factory(tier: str, seed: int, seed_rumour: str = "default") -> Any:
        if seed_rumour == "default":
            return Env(tier=tier, seed=seed)
        strat = MoleStrategy.from_json({**DEFAULT_STRATEGY.to_json(), "seed_rumour": seed_rumour})
        return Env(tier=tier, seed=seed, mole_strategy=strat)

    return factory


def collect_episode_social_state(env_factory: Callable[..., Any], tier: str, seed: int, seed_rumour: str = "default") -> dict[str, Any]:
    env = env_factory(tier, seed, seed_rumour=seed_rumour)
    n_days = int(env.p.n_days)
    for _ in range(n_days):
        if env.done:
            break
        env.call("advance_day", {})
    docs = env.call("list_documents", {"day_from": 1, "day_to": n_days}).data.get("documents", []) if not env.done else [
        {k: (list(v) if isinstance(v, list) else v) for k, v in x.items() if k != "variants"}
        for x in env.docs
    ]
    social_msgs = []
    for mid in env._msg_order:
        m = env._messages[mid]
        subj = str(m.get("subject", ""))
        if "-s" in str(m.get("id", "")) or SOCIAL_SUBJECT_RE.match(subj):
            social_msgs.append(m)
    grudge_pairs = list(env._grudges()) if hasattr(env, "_grudges") else []
    leaked_doc_ids = {
        str(ev.detail.get("doc_id"))
        for ev in env.ledger()
        if getattr(ev, "event", "") == "leak" and getattr(ev, "detail", None) and ev.detail.get("doc_id")
    }
    return {
        "tier": tier,
        "seed": seed,
        "ids": list(env._ids),
        "mole": env._world.mole,
        "decoy": env._world.decoy,
        "world_seed": int(env._world.world_seed),
        "social_msgs": social_msgs,
        "docs": docs,
        "grudge_pairs": grudge_pairs,
        "leaked_doc_ids": leaked_doc_ids,
    }


def audit_word_and_token_leaks(env_factory: Callable[..., Any], tier: str, seeds: list[int], seed_rumour: str = "default") -> dict[str, Any]:
    mole_word_re = re.compile(r"\bmole\b", re.I)
    n_social_msgs = 0
    by_kind: Counter[str] = Counter()
    n_misforwards = 0
    mole_word_hits: list[dict[str, Any]] = []
    truth_leak_hits: list[dict[str, Any]] = []
    seed_token_hits: list[dict[str, Any]] = []

    for seed in seeds:
        st = collect_episode_social_state(env_factory, tier, seed, seed_rumour=seed_rumour)
        mole = st["mole"]
        wseed_str = str(st["world_seed"])
        seed_str = str(seed)
        raw_seed_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(seed_str)}(?![A-Za-z0-9_])") if len(seed_str) >= 4 else None

        for m in st["social_msgs"]:
            n_social_msgs += 1
            subj = str(m.get("subject", ""))
            sm = SOCIAL_SUBJECT_RE.match(subj)
            kind = sm.group(1) if sm else "other"
            by_kind[kind] += 1
            blob = json.dumps(m, sort_keys=True)
            text_fields = f"{m.get('subject', '')}\n{m.get('body', '')}\n{m.get('channel', '')}"
            if "mole" in text_fields.lower() or mole_word_re.search(text_fields):
                mole_word_hits.append({"seed": seed, "msg_id": m.get("id"), "text": text_fields[:200]})
            if mole_named_leak(blob, mole):
                truth_leak_hits.append({"seed": seed, "msg_id": m.get("id"), "text": blob[:200]})
            low_blob = blob.lower()
            if (
                wseed_str in blob
                or any(tok in low_blob for tok in FORBIDDEN_SUBSTRINGS)
                or (raw_seed_re is not None and raw_seed_re.search(text_fields))
            ):
                seed_token_hits.append({"seed": seed, "msg_id": m.get("id"), "text": blob[:200]})

        for d in st["docs"]:
            if "forwarded_to" not in d:
                continue
            n_misforwards += 1
            blob = json.dumps(d, sort_keys=True)
            low_blob = blob.lower()
            if "mole" in low_blob or mole_word_re.search(blob):
                mole_word_hits.append({"seed": seed, "doc_id": d.get("doc_id"), "text": blob[:200]})
            if mole_named_leak(blob, mole):
                truth_leak_hits.append({"seed": seed, "doc_id": d.get("doc_id"), "text": blob[:200]})
            if (
                wseed_str in blob
                or any(tok in low_blob for tok in FORBIDDEN_SUBSTRINGS)
                or (raw_seed_re is not None and raw_seed_re.search(blob))
            ):
                seed_token_hits.append({"seed": seed, "doc_id": d.get("doc_id"), "text": blob[:200]})

    return {
        "tier": tier,
        "n_seeds": len(seeds),
        "seed_rumour": seed_rumour,
        "social_messages_scanned": n_social_msgs,
        "social_messages_by_kind": dict(by_kind),
        "misforwarded_docs_scanned": n_misforwards,
        "mole_word_leaks": len(mole_word_hits),
        "truth_pattern_leaks": len(truth_leak_hits),
        "seed_or_secret_token_leaks": len(seed_token_hits),
        "clean": len(mole_word_hits) == 0 and len(truth_leak_hits) == 0 and len(seed_token_hits) == 0,
        "sample_hits": (mole_word_hits + truth_leak_hits + seed_token_hits)[:5],
    }


def audit_social_conditionals(env_factory: Callable[..., Any], tier: str, seeds: list[int], seed_rumour: str = "default") -> dict[str, Any]:
    emp_total = 0
    emp_mole = 0

    rumour_event_total = 0
    rumour_event_mole = 0
    rumour_event_decoy = 0
    rumour_non_target_total = 0
    rumour_non_target_mole = 0

    emp_rumoured_ge1_total = 0
    emp_rumoured_ge1_mole = 0
    emp_not_rumoured_total = 0
    emp_not_rumoured_mole = 0

    emp_rumoured_ge2_total = 0
    emp_rumoured_ge2_mole = 0
    emp_rumoured_ge3_total = 0
    emp_rumoured_ge3_mole = 0
    emp_rumoured_ge5_total = 0
    emp_rumoured_ge5_mole = 0

    top_rumoured_total = 0
    top_rumoured_mole = 0
    top_rumoured_decoy = 0

    auth_event_total = 0
    auth_event_mole = 0
    auth_event_decoy = 0

    grudge_event_total = 0
    grudge_event_mole = 0
    grudge_event_decoy = 0
    emp_grudge_target_total = 0
    emp_grudge_target_mole = 0
    emp_grudge_target_decoy = 0
    emp_not_grudge_target_total = 0
    emp_not_grudge_target_mole = 0
    emp_grudge_part_total = 0
    emp_grudge_part_mole = 0
    emp_grudge_part_decoy = 0
    emp_grudge_pair_total = 0
    emp_grudge_pair_mole = 0
    emp_grudge_pair_decoy = 0

    misfwd_event_total = 0
    misfwd_event_mole = 0
    misfwd_event_decoy = 0
    emp_misfwd_total = 0
    emp_misfwd_mole = 0
    emp_not_misfwd_total = 0
    emp_not_misfwd_mole = 0

    regular_docs_total = 0
    base_rec_sum = 0
    eff_rec_sum = 0
    leaked_reg_docs = 0
    leaked_via_misfwd = 0
    eps_with_misfwd_leak = 0
    base_inter_sizes: list[int] = []
    eff_inter_sizes: list[int] = []

    n_staff = 0
    for seed in seeds:
        st = collect_episode_social_state(env_factory, tier, seed, seed_rumour=seed_rumour)
        ids = st["ids"]
        n_staff = len(ids)
        mole = st["mole"]
        decoy = st["decoy"]
        leaked_ids = st.get("leaked_doc_ids", set())

        rumour_cnt: Counter[str] = Counter()
        grudge_tgt_cnt: Counter[str] = Counter()
        grudge_part_cnt: Counter[str] = Counter()
        misfwd_cnt: Counter[str] = Counter()

        for m in st["social_msgs"]:
            sm = SOCIAL_SUBJECT_RE.match(str(m.get("subject", "")))
            if not sm:
                continue
            kind, tgt = sm.group(1), sm.group(2)
            if kind == "rumour":
                rumour_cnt[tgt] += 1
                rumour_event_total += 1
                if tgt == mole:
                    rumour_event_mole += 1
                if decoy is not None and tgt == decoy:
                    rumour_event_decoy += 1
                rumour_non_target_total += n_staff - 1
                if tgt != mole:
                    rumour_non_target_mole += 1
            elif kind == "unverified accusation":
                auth_event_total += 1
                if tgt == mole:
                    auth_event_mole += 1
                if decoy is not None and tgt == decoy:
                    auth_event_decoy += 1
            elif kind == "grudge":
                grudge_tgt_cnt[tgt] += 1
                grudge_part_cnt[tgt] += 1
                snd = str(m.get("sender") or "")
                if snd in ids:
                    grudge_part_cnt[snd] += 1
                grudge_event_total += 1
                if tgt == mole:
                    grudge_event_mole += 1
                if decoy is not None and tgt == decoy:
                    grudge_event_decoy += 1

        ep_had_misfwd_leak = False
        ep_base_inter: set[str] | None = None
        ep_eff_inter: set[str] | None = None

        for d in st["docs"]:
            if not d.get("is_canary", False):
                eff_recs = list(d.get("recipients", []))
                actor_doc = d.get("forwarded_to")
                base_recs = [x for x in eff_recs if x != actor_doc] if actor_doc else eff_recs
                regular_docs_total += 1
                base_rec_sum += len(base_recs)
                eff_rec_sum += len(eff_recs)
                if str(d.get("doc_id", "")) in leaked_ids:
                    leaked_reg_docs += 1
                    if actor_doc == mole:
                        leaked_via_misfwd += 1
                        ep_had_misfwd_leak = True
                    ep_base_inter = set(base_recs) if ep_base_inter is None else (ep_base_inter & set(base_recs))
                    ep_eff_inter = set(eff_recs) if ep_eff_inter is None else (ep_eff_inter & set(eff_recs))
            actor = d.get("forwarded_to")
            if actor:
                misfwd_cnt[actor] += 1
                misfwd_event_total += 1
                if actor == mole:
                    misfwd_event_mole += 1
                if decoy is not None and actor == decoy:
                    misfwd_event_decoy += 1

        if ep_had_misfwd_leak:
            eps_with_misfwd_leak += 1
        if ep_base_inter is not None and ep_eff_inter is not None:
            base_inter_sizes.append(len(ep_base_inter))
            eff_inter_sizes.append(len(ep_eff_inter))

        if rumour_cnt:
            top_emp = max(ids, key=lambda e: (rumour_cnt[e], -ids.index(e)))
            top_rumoured_total += 1
            if top_emp == mole:
                top_rumoured_mole += 1
            if decoy is not None and top_emp == decoy:
                top_rumoured_decoy += 1

        pair_members = {x for pair in st["grudge_pairs"] for x in pair}
        for e in ids:
            is_m = int(e == mole)
            is_d = int(decoy is not None and e == decoy)
            emp_total += 1
            emp_mole += is_m

            rc = rumour_cnt[e]
            if rc >= 1:
                emp_rumoured_ge1_total += 1
                emp_rumoured_ge1_mole += is_m
            else:
                emp_not_rumoured_total += 1
                emp_not_rumoured_mole += is_m
            if rc >= 2:
                emp_rumoured_ge2_total += 1
                emp_rumoured_ge2_mole += is_m
            if rc >= 3:
                emp_rumoured_ge3_total += 1
                emp_rumoured_ge3_mole += is_m
            if rc >= 5:
                emp_rumoured_ge5_total += 1
                emp_rumoured_ge5_mole += is_m

            if grudge_tgt_cnt[e] >= 1:
                emp_grudge_target_total += 1
                emp_grudge_target_mole += is_m
                emp_grudge_target_decoy += is_d
            else:
                emp_not_grudge_target_total += 1
                emp_not_grudge_target_mole += is_m

            if grudge_part_cnt[e] >= 1:
                emp_grudge_part_total += 1
                emp_grudge_part_mole += is_m
                emp_grudge_part_decoy += is_d

            if e in pair_members:
                emp_grudge_pair_total += 1
                emp_grudge_pair_mole += is_m
                emp_grudge_pair_decoy += is_d

            if misfwd_cnt[e] >= 1:
                emp_misfwd_total += 1
                emp_misfwd_mole += is_m
            else:
                emp_not_misfwd_total += 1
                emp_not_misfwd_mole += is_m

    s_share = SOCIAL_PARAMS_V15["rumour_frame_share"]
    prior = 1.0 / n_staff if n_staff else 0.0
    analytic_rumour_event_mole = (1.0 - s_share) / n_staff if n_staff else 0.0
    analytic_rumour_non_target_mole = (1.0 - analytic_rumour_event_mole) / (n_staff - 1) if n_staff > 1 else 0.0
    analytic_grudge_non_decoy_mole = (1.0 / (n_staff - 1)) if (n_staff > 1 and tier in ("medium", "hard")) else prior

    return {
        "tier": tier,
        "n_seeds": len(seeds),
        "n_employees": n_staff,
        "seed_rumour": seed_rumour,
        "prior_mole": round(prior, 6),
        "analytical": {
            "p_mole_given_rumour_event": round(analytic_rumour_event_mole, 6),
            "p_mole_given_not_rumour_event_target": round(analytic_rumour_non_target_mole, 6),
            "p_mole_given_grudge_member": round(analytic_grudge_non_decoy_mole, 6),
            "p_mole_given_misforward_actor": round(prior, 6),
        },
        "rumour_event": {
            "p_mole_given_rumoured": rate_summary(rumour_event_mole, rumour_event_total),
            "p_mole_given_not_rumoured": rate_summary(rumour_non_target_mole, rumour_non_target_total),
            "p_decoy_given_rumoured": rate_summary(rumour_event_decoy, rumour_event_total),
        },
        "employee_rumour": {
            "p_mole_given_rumoured_ge1": rate_summary(emp_rumoured_ge1_mole, emp_rumoured_ge1_total),
            "p_mole_given_not_rumoured": rate_summary(emp_not_rumoured_mole, emp_not_rumoured_total),
            "p_mole_given_rumoured_ge2": rate_summary(emp_rumoured_ge2_mole, emp_rumoured_ge2_total),
            "p_mole_given_rumoured_ge3": rate_summary(emp_rumoured_ge3_mole, emp_rumoured_ge3_total),
            "p_mole_given_rumoured_ge5": rate_summary(emp_rumoured_ge5_mole, emp_rumoured_ge5_total),
            "p_mole_given_top_rumoured": rate_summary(top_rumoured_mole, top_rumoured_total),
            "p_decoy_given_top_rumoured": rate_summary(top_rumoured_decoy, top_rumoured_total),
        },
        "authority_event": {
            "p_mole_given_authority_target": rate_summary(auth_event_mole, auth_event_total),
            "p_decoy_given_authority_target": rate_summary(auth_event_decoy, auth_event_total),
        },
        "grudge": {
            "p_mole_given_grudge_event_target": rate_summary(grudge_event_mole, grudge_event_total),
            "p_mole_given_grudge_target_ge1": rate_summary(emp_grudge_target_mole, emp_grudge_target_total),
            "p_mole_given_not_grudge_target": rate_summary(emp_not_grudge_target_mole, emp_not_grudge_target_total),
            "p_mole_given_grudge_participant": rate_summary(emp_grudge_part_mole, emp_grudge_part_total),
            "p_mole_given_grudge_pair_member": rate_summary(emp_grudge_pair_mole, emp_grudge_pair_total),
            "p_decoy_given_grudge_target_ge1": rate_summary(emp_grudge_target_decoy, emp_grudge_target_total),
            "p_decoy_given_grudge_participant": rate_summary(emp_grudge_part_decoy, emp_grudge_part_total),
            "p_decoy_given_grudge_pair_member": rate_summary(emp_grudge_pair_decoy, emp_grudge_pair_total),
        },
        "misforward": {
            "p_mole_given_misforward_event_actor": rate_summary(misfwd_event_mole, misfwd_event_total),
            "p_mole_given_misforward_actor_ge1": rate_summary(emp_misfwd_mole, emp_misfwd_total),
            "p_mole_given_not_misforward_actor": rate_summary(emp_not_misfwd_mole, emp_not_misfwd_total),
            "regular_docs_published": regular_docs_total,
            "misforwarded_doc_rate": rate_summary(misfwd_event_total, regular_docs_total),
            "mean_base_recipients": round(base_rec_sum / regular_docs_total, 4) if regular_docs_total else 0.0,
            "mean_effective_recipients": round(eff_rec_sum / regular_docs_total, 4) if regular_docs_total else 0.0,
            "holder_slot_expansion_pct": round(100.0 * (eff_rec_sum - base_rec_sum) / base_rec_sum, 4) if base_rec_sum else 0.0,
            "leaked_regular_docs": leaked_reg_docs,
            "leaks_enabled_by_misforward": rate_summary(leaked_via_misfwd, leaked_reg_docs),
            "episodes_with_misforward_leak": rate_summary(eps_with_misfwd_leak, len(seeds)),
            "mean_leaked_base_intersection_size": round(statistics.mean(base_inter_sizes), 4) if base_inter_sizes else 0.0,
            "mean_leaked_effective_intersection_size": round(statistics.mean(eff_inter_sizes), 4) if eff_inter_sizes else 0.0,
        },
        "unconditional_check": rate_summary(emp_mole, emp_total),
    }


def audit_exclusion_by_day(
    env_factory: Callable[..., Any],
    tier: str,
    seeds: list[int],
    checkpoints: tuple[int, ...] = (3, 6, 10, 14),
    seed_rumour: str = "default",
) -> dict[str, Any]:
    by_day: dict[int, dict[str, int]] = {
        d: {"evaluated": 0, "has_candidate": 0, "excluded_not_mole": 0, "excluded_is_decoy": 0}
        for d in checkpoints
    }
    for seed in seeds:
        st = collect_episode_social_state(env_factory, tier, seed, seed_rumour=seed_rumour)
        ids = st["ids"]
        mole = st["mole"]
        decoy = st["decoy"]
        msgs = st["social_msgs"]
        for d in checkpoints:
            grudge_set: set[str] = set()
            rc: Counter[str] = Counter()
            for m in msgs:
                if int(m.get("day", 0)) > d:
                    continue
                sm = SOCIAL_SUBJECT_RE.match(str(m.get("subject", "")))
                if not sm:
                    continue
                kind, tgt = sm.group(1), sm.group(2)
                if kind == "grudge":
                    grudge_set.add(tgt)
                    if m.get("sender"):
                        grudge_set.add(str(m["sender"]))
                elif kind == "rumour":
                    rc[tgt] += 1
                elif kind == "unverified accusation":
                    rc[tgt] += 2
            cands = [(e, rc[e]) for e in ids if rc[e] > 0 and e not in grudge_set]
            row = by_day[d]
            row["evaluated"] += 1
            if not cands:
                continue
            cands.sort(key=lambda kv: (-kv[1], kv[0]))
            top = cands[0][0]
            row["has_candidate"] += 1
            if top != mole:
                row["excluded_not_mole"] += 1
            if decoy is not None and top == decoy:
                row["excluded_is_decoy"] += 1
    out: dict[str, Any] = {}
    for d, row in by_day.items():
        hc = row["has_candidate"]
        out[f"day_{d}"] = {
            "evaluated": row["evaluated"],
            "has_candidate": hc,
            "safe_exclusion_not_mole": rate_summary(row["excluded_not_mole"], hc),
            "exact_decoy_match": rate_summary(row["excluded_is_decoy"], hc),
        }
    return {"tier": tier, "n_seeds": len(seeds), "seed_rumour": seed_rumour, "checkpoints": out}


def _parse_instruction_floats(instruction: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in (instruction or "").splitlines():
        s = line.strip()
        if s.startswith("- ") and ": " in s:
            k, v = s[2:].split(": ", 1)
            try:
                out[k.strip()] = float(v.strip())
            except ValueError:
                pass
    return out


def build_policies() -> dict[str, Any]:
    from canary.baselines import LogsMinusDecoy, ScriptedPolicy, _argmax, items
    from canary.solver.policy import SolverPolicy, _items

    class RumourFollowerProbe(ScriptedPolicy):
        name = "rumour_follower"

        def script(self):
            emps = yield from self._employees()
            yield from self._advance(6)
            c: Counter[str] = Counter()
            for q, wgt in (("rumour:", 1), ("unverified accusation:", 3), ("grudge:", 1)):
                r = yield ("search_messages", {"query": q})
                for m in items(r):
                    if isinstance(m, dict):
                        tgt = str(m.get("subject", "")).split(": ")[-1]
                        if tgt in emps:
                            c[tgt] += wgt
            yield ("accuse", {"employee": _argmax(c, emps, self.rng)})

    class LogsAntiRumourProbe(ScriptedPolicy):
        name = "logs_anti_rumour"
        wait = 5

        def script(self):
            emps = yield from self._employees()
            yield from self._advance(self.wait)
            grudge_set: set[str] = set()
            rg = yield ("search_messages", {"query": "grudge:"})
            for m in items(rg):
                if isinstance(m, dict):
                    tgt = str(m.get("subject", "")).split(": ")[-1]
                    if tgt in emps:
                        grudge_set.add(tgt)
                    if m.get("sender") in emps:
                        grudge_set.add(str(m["sender"]))
            rc: Counter[str] = Counter()
            for q, wgt in (("rumour:", 1), ("unverified accusation:", 2)):
                rr = yield ("search_messages", {"query": q})
                for m in items(rr):
                    if isinstance(m, dict):
                        tgt = str(m.get("subject", "")).split(": ")[-1]
                        if tgt in emps and tgt not in grudge_set:
                            rc[tgt] += wgt
            excluded_decoy = rc.most_common(1)[0][0] if rc else None
            logs = yield from self._logs()
            c: Counter[str] = Counter()
            for x in logs:
                c[str(x.get("employee"))] += 1 + 3 * bool(x.get("after_hours"))
            pool = [e for e in emps if e != excluded_decoy] or emps
            yield ("accuse", {"employee": _argmax(c, pool, self.rng)})

    class AntiRumourSolver(SolverPolicy):
        name = "anti_rumour_solver"

        def reset(self, tools_spec: list[dict], instruction: str) -> None:
            super().reset(tools_spec, instruction)
            self.extra_params = _parse_instruction_floats(instruction)
            self.social_events: list[tuple[str, str, str]] = []
            self.rumour_score: Counter[str] = Counter()
            self.grudge_members: set[str] = set()
            self.last_social_query_day = 0

        def _social_share(self) -> float:
            val = getattr(self.P, "rumour_frame_share", None)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
            return float(self.extra_params.get("rumour_frame_share", 0.0))

        def _rumour_rate(self) -> float:
            val = getattr(self.P, "rumour_rate", None)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
            return float(self.extra_params.get("rumour_rate", 0.0))

        def _authority_day(self) -> int:
            val = getattr(self.P, "authority_day", None)
            if isinstance(val, int) and val > 0:
                return val
            return int(self.extra_params.get("authority_day", 0))

        def _grudge_rate(self) -> float:
            val = getattr(self.P, "grudge_rate", None)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
            return float(self.extra_params.get("grudge_rate", 0.0))

        def _ingest(self, st) -> None:
            r = st.result or {}
            ok_flag = r.get("ok", True)
            if ok_flag and st.tool == "search_messages":
                data = r.get("data") or {}
                for m in _items(data, "messages"):
                    mid = m.get("id")
                    if mid in self.seen_msgs:
                        continue
                    subj = str(m.get("subject") or "")
                    sm = SOCIAL_SUBJECT_RE.match(subj)
                    if sm:
                        self.seen_msgs.add(mid)
                        raw_kind, tgt = sm.group(1), sm.group(2)
                        snd = str(m.get("sender") or "")
                        kind = {"rumour": "rumour", "unverified accusation": "authority", "grudge": "grudge"}[raw_kind]
                        self.social_events.append((kind, snd, tgt))
                        if hasattr(self.obs, "social"):
                            self.obs.social.append((kind, snd, tgt))
                        if kind == "rumour":
                            self.rumour_score[tgt] += 1
                        elif kind == "authority":
                            self.rumour_score[tgt] += 2
                        elif kind == "grudge":
                            self.grudge_members.add(tgt)
                            if snd:
                                self.grudge_members.add(snd)
                self._infer_decoy_from_rumours()
            super()._ingest(st)

        def _infer_decoy_from_rumours(self) -> None:
            if not (self.P and self.P.decoy) or self.obs.decoy is not None:
                return
            cands = [(e, c) for e, c in self.rumour_score.items() if e not in self.grudge_members]
            if not cands:
                return
            cands.sort(key=lambda kv: (-kv[1], kv[0]))
            top, n1 = cands[0]
            n2 = cands[1][1] if len(cands) > 1 else 0
            if n1 >= 3 and n1 >= 2 * max(1, n2):
                self.obs.decoy = top

        def belief(self) -> dict[str, float]:
            post = super().belief()
            if hasattr(self.obs, "social"):
                return post
            sh = self._social_share()
            if not self.social_events or sh <= 0 or (self.P.decoy and self.obs.decoy is not None):
                return post
            n = len(self.obs.employees)
            if n < 3:
                return post
            unnorm: dict[str, float] = {}
            for s, p in post.items():
                if p <= 0.0:
                    unnorm[s] = 0.0
                    continue
                ll = 0.0
                for kind, sp, t in self.social_events:
                    qt = 0.0 if t == s else 1.0 / (n - 1)
                    qsp = 0.0 if sp == s else 1.0 / (n - 1)
                    if kind == "rumour":
                        ll += math.log((1.0 - sh) / (n * (n - 1)) + sh * qt / (n - 1))
                    elif kind == "authority":
                        ll += math.log((1.0 - sh) / (n - 1) + sh * (qt + qsp / (n - 1)))
                unnorm[s] = p * math.exp(ll)
            z = sum(unnorm.values())
            if z <= 0.0:
                return post
            return {k: v / z for k, v in unnorm.items()}

        def decoy_queries(self) -> list[tuple[str, dict]]:
            if self._rumour_rate() <= 0:
                return super().decoy_queries()
            today = self.obs.today
            if today < 2 or self.last_social_query_day >= today:
                return []
            if self.P and self.P.decoy and self.obs.decoy is not None:
                return []
            self.last_social_query_day = today
            q: list[tuple[str, dict]] = []
            if self.P and self.P.decoy and self._grudge_rate() > 0 and "grudge:" not in self.queries_done:
                q.append(("search_messages", {"query": "grudge:"}))
            q.append(("search_messages", {"query": "rumour:", "day_from": max(1, today - 4), "day_to": today}))
            aday = self._authority_day()
            if aday and today >= aday + 1 and "unverified accusation:" not in self.queries_done:
                q.append(("search_messages", {"query": "unverified accusation:"}))
            return q

    return {
        "solver": SolverPolicy,
        "anti_rumour_solver": AntiRumourSolver,
        "rumour_follower": RumourFollowerProbe,
        "logs_minus_decoy": LogsMinusDecoy,
        "logs_anti_rumour": LogsAntiRumourProbe,
    }


def run_policy_episode(env: Any, policy: Any, max_steps: int = 1000) -> dict[str, Any]:
    from canary.baselines import play

    score = float(play(env, policy, max_steps=max_steps))
    accused = getattr(env, "_accused", None)
    correct = bool(getattr(env, "_correct", False))
    true_decoy = getattr(env._world, "decoy", None)
    obs = getattr(policy, "obs", None)
    found_decoy = getattr(obs, "decoy", None) if obs is not None else None
    social_len = len(getattr(policy, "social_events", None) or getattr(obs, "social", None) or ())
    return {
        "score": score,
        "accused": accused is not None,
        "correct": correct,
        "decoy_found": (true_decoy is not None and found_decoy == true_decoy),
        "social_ingested": social_len,
        "final_day": int(env.day),
    }


def summarize_policy_runs(rows: list[dict[str, Any]], has_decoy: bool) -> dict[str, Any]:
    scores = [r["score"] for r in rows]
    n = len(rows) or 1
    acc_rows = [r for r in rows if r["accused"]]
    return {
        "n": len(rows),
        "mean_score": round(statistics.mean(scores), 4) if scores else 0.0,
        "ci95": round(ci95(scores), 4),
        "acc": round(sum(1 for r in rows if r["correct"]) / n, 4),
        "acc_when_accusing": round(sum(1 for r in acc_rows if r["correct"]) / len(acc_rows), 4) if acc_rows else 0.0,
        "abstain_rate": round(1.0 - len(acc_rows) / n, 4),
        "mean_day": round(statistics.mean([r["final_day"] for r in acc_rows]), 2) if acc_rows else None,
        "decoy_id_rate": round(sum(1 for r in rows if r["decoy_found"]) / n, 4) if has_decoy else None,
        "mean_social_ingested": round(statistics.mean([r["social_ingested"] for r in rows]), 2) if rows else 0.0,
    }


def audit_policies(
    env_factory: Callable[..., Any],
    tier: str,
    seeds: list[int],
    seed_rumour: str = "default",
    include_log_probes: bool = True,
) -> dict[str, Any]:
    pols = build_policies()
    sample_env = env_factory(tier, seeds[0], seed_rumour=seed_rumour)
    has_decoy = bool(sample_env.p.decoy)

    sol_rows: list[dict[str, Any]] = []
    ar_rows: list[dict[str, Any]] = []
    rf_rows: list[dict[str, Any]] = []
    lmd_rows: list[dict[str, Any]] = []
    lar_rows: list[dict[str, Any]] = []

    for s in seeds:
        sol_rows.append(run_policy_episode(env_factory(tier, s, seed_rumour=seed_rumour), pols["solver"]()))
        ar_rows.append(run_policy_episode(env_factory(tier, s, seed_rumour=seed_rumour), pols["anti_rumour_solver"]()))
        rf_rows.append(run_policy_episode(env_factory(tier, s, seed_rumour=seed_rumour), pols["rumour_follower"](seed=s)))
        if include_log_probes:
            lmd_rows.append(run_policy_episode(env_factory(tier, s, seed_rumour=seed_rumour), pols["logs_minus_decoy"](seed=s)))
            lar_rows.append(run_policy_episode(env_factory(tier, s, seed_rumour=seed_rumour), pols["logs_anti_rumour"](seed=s)))

    diffs = [a["score"] - b["score"] for a, b in zip(ar_rows, sol_rows)]
    wins = sum(1 for d in diffs if d > 1e-9)
    ties = sum(1 for d in diffs if abs(d) <= 1e-9)
    losses = sum(1 for d in diffs if d < -1e-9)

    out: dict[str, Any] = {
        "tier": tier,
        "n_seeds": len(seeds),
        "seed_range": [seeds[0], seeds[-1]],
        "seed_rumour": seed_rumour,
        "solver": summarize_policy_runs(sol_rows, has_decoy),
        "anti_rumour_solver": summarize_policy_runs(ar_rows, has_decoy),
        "rumour_follower": summarize_policy_runs(rf_rows, has_decoy),
        "paired_anti_rumour_minus_solver": {
            "mean_diff": round(statistics.mean(diffs), 4) if diffs else 0.0,
            "ci95": round(ci95(diffs), 4),
            "wins": wins,
            "ties": ties,
            "losses": losses,
        },
    }
    if include_log_probes:
        log_diffs = [a["score"] - b["score"] for a, b in zip(lar_rows, lmd_rows)]
        out["logs_minus_decoy"] = summarize_policy_runs(lmd_rows, has_decoy)
        out["logs_anti_rumour"] = summarize_policy_runs(lar_rows, has_decoy)
        out["paired_logs_anti_rumour_minus_logs_minus_decoy"] = {
            "mean_diff": round(statistics.mean(log_diffs), 4) if log_diffs else 0.0,
            "ci95": round(ci95(log_diffs), 4),
        }
    return out


def _unsurfaced_leaks_exist(env: Any) -> bool:
    led = env.ledger()
    leaked = {e.detail.get("doc_id") for e in led if getattr(e, "event", "") == "leak"}
    surfaced = {e.detail.get("doc_id") for e in led if getattr(e, "event", "") == "leak_surfaced"}
    return bool(leaked - surfaced)


def audit_invariants(env_factory: Callable[..., Any], tier: str, seeds: list[int]) -> dict[str, Any]:
    from canary.baselines import DoNothing, play
    from canary.redteam.fuzz import _accusations, score_invariants

    dn_scores: list[float] = []
    se_quit_scores: list[float] = []
    g1_scores: list[float] = []
    score_inv_violations = 0
    v_monotone_violations = 0
    v_steps_checked = 0
    hidden_leak_states = 0
    known_v_reveals = 0

    for s in seeds:
        e_dn = env_factory(tier, s)
        sc_dn = float(play(e_dn, DoNothing(seed=s)))
        dn_scores.append(sc_dn)
        if score_invariants(sc_dn, _accusations(e_dn.ledger(), set(e_dn._ids)), e_dn._world.mole):
            score_inv_violations += 1

        e_se = env_factory(tier, s)
        e_se.call("list_employees", {})
        e_se.call("status", {})
        e_se.call("read_access_logs", {"day_from": 1, "day_to": 1})
        sc_se = float(e_se.score())
        se_quit_scores.append(sc_se)
        if score_invariants(sc_se, _accusations(e_se.ledger(), set(e_se._ids)), e_se._world.mole):
            score_inv_violations += 1

        e_g1 = env_factory(tier, s)
        rng_g1 = random.Random(s)
        emps = [x["id"] for x in e_g1.call("list_employees", {}).data["employees"]]
        e_g1.call("accuse", {"employee": rng_g1.choice(emps)})
        sc_g1 = float(e_g1.score())
        g1_scores.append(sc_g1)
        if score_invariants(sc_g1, _accusations(e_g1.ledger(), set(e_g1._ids)), e_g1._world.mole):
            score_inv_violations += 1

        e_v = env_factory(tier, s)
        rng_v = random.Random(100000 + s)
        emps_v = list(e_v._ids)
        prev_true = 1.0
        prev_known = float(e_v.call("status", {}).data["V"])
        if abs(prev_known - 1.0) > 1e-9:
            v_monotone_violations += 1
        for step_idx in range(80):
            if e_v.done:
                break
            choice = step_idx % 5
            if choice == 0 and len(emps_v) >= 2:
                pair = rng_v.sample(emps_v, 2)
                e_v.call("plant_canary", {"doc_title": f"Audit {step_idx}", "assignment": {pair[0]: "A", pair[1]: "B"}})
            elif choice == 1:
                e_v.call("search_messages", {"query": "rumour:"})
            elif choice == 2:
                e_v.call("list_documents", {"day_from": 1, "day_to": e_v.day})
            else:
                adv = e_v.call("advance_day", {})
                if not e_v.done and adv.ok and "V" in adv.data:
                    av = float(adv.data["V"])
                    if av > prev_known + 1e-12:
                        v_monotone_violations += 1
                    if _unsurfaced_leaks_exist(e_v) and abs(av - e_v.V) < 1e-9:
                        known_v_reveals += 1
            if e_v.done:
                break
            kv = float(e_v.call("status", {}).data["V"])
            tv = float(e_v.V)
            v_steps_checked += 1
            if tv > prev_true + 1e-12 or kv > prev_known + 1e-12:
                v_monotone_violations += 1
            prev_true, prev_known = tv, kv
            if _unsurfaced_leaks_exist(e_v):
                hidden_leak_states += 1
                if abs(kv - tv) < 1e-9:
                    known_v_reveals += 1

    dn_all_zero = all(x == 0.0 for x in dn_scores)
    se_all_zero = all(x == 0.0 for x in se_quit_scores)
    g1_mean = statistics.mean(g1_scores) if g1_scores else 0.0
    return {
        "tier": tier,
        "n_seeds": len(seeds),
        "do_nothing_all_zero": dn_all_zero,
        "do_nothing_mean": round(statistics.mean(dn_scores), 6) if dn_scores else 0.0,
        "stop_early_all_zero": se_all_zero,
        "stop_early_mean": round(statistics.mean(se_quit_scores), 6) if se_quit_scores else 0.0,
        "guess_day1_mean": round(g1_mean, 4),
        "guess_day1_ci95": round(ci95(g1_scores), 4),
        "guess_day1_negative": g1_mean < 0.0,
        "score_invariant_violations": score_inv_violations,
        "v_steps_checked": v_steps_checked,
        "v_monotone_violations": v_monotone_violations,
        "hidden_leak_states": hidden_leak_states,
        "known_v_reveals": known_v_reveals,
        "all_invariants_hold": (
            dn_all_zero
            and se_all_zero
            and g1_mean < 0.0
            and score_inv_violations == 0
            and v_monotone_violations == 0
            and hidden_leak_states > 0
            and known_v_reveals == 0
        ),
    }


def run_self_test() -> dict[str, Any]:
    t0 = time.time()
    clean_factory = make_synthetic_v15_factory(plant_leak=False)
    leaky_factory = make_synthetic_v15_factory(plant_leak=True)

    seeds_stat = list(range(7500, 7530))
    seeds_pol = list(range(7500, 7506))

    leak_clean = audit_word_and_token_leaks(clean_factory, "medium", seeds_stat[:10])
    leak_planted = audit_word_and_token_leaks(leaky_factory, "medium", seeds_stat[:3])
    cond_hard = audit_social_conditionals(clean_factory, "hard", seeds_stat)
    cond_peer = audit_social_conditionals(clean_factory, "hard", seeds_stat, seed_rumour="random_peer")
    inv_med = audit_invariants(clean_factory, "medium", seeds_stat[:12])
    pol_med = audit_policies(clean_factory, "medium", seeds_pol, include_log_probes=True)

    checks = {
        "clean_word_leak_pass": leak_clean["clean"] and leak_clean["social_messages_scanned"] > 0,
        "planted_leak_detected": (
            not leak_planted["clean"]
            and leak_planted["mole_word_leaks"] > 0
            and leak_planted["truth_pattern_leaks"] > 0
            and leak_planted["seed_or_secret_token_leaks"] > 0
        ),
        "rumour_anti_inversion_signal": (
            cond_hard["rumour_event"]["p_mole_given_rumoured"]["rate"] < cond_hard["prior_mole"]
            and cond_hard["employee_rumour"]["p_mole_given_top_rumoured"]["rate"] == 0.0
            and cond_hard["grudge"]["p_decoy_given_grudge_target_ge1"]["rate"] == 0.0
            and cond_hard["grudge"]["p_decoy_given_grudge_participant"]["rate"] == 0.0
            and cond_hard["grudge"]["p_decoy_given_grudge_pair_member"]["rate"] == 0.0
        ),
        "misforward_holder_expansion": (
            cond_hard["misforward"]["mean_effective_recipients"] > cond_hard["misforward"]["mean_base_recipients"]
            and cond_hard["misforward"]["misforwarded_doc_rate"]["rate"] > 0.0
        ),
        "random_peer_exclusion_signal": (
            cond_peer["rumour_event"]["p_mole_given_rumoured"]["rate"] < cond_peer["prior_mole"]
        ),
        "invariants_hold": inv_med["all_invariants_hold"],
        "rumour_follower_trapped": pol_med["rumour_follower"]["mean_score"] < 0.0,
        "anti_rumour_ingests_social": pol_med["anti_rumour_solver"]["mean_social_ingested"] > 0.0,
    }
    ok = all(checks.values())
    return {
        "mode": "self_test",
        "ok": ok,
        "seconds": round(time.time() - t0, 2),
        "checks": checks,
        "sample_conditionals_hard": cond_hard,
        "sample_invariants_medium": inv_med,
        "sample_policies_medium": pol_med,
    }


def run_full_audit(
    v15_root: Path | None,
    fuzz_dir: Path | None,
    seeds: list[int],
    solver_seeds: list[int],
    tiers: list[str],
    synthetic: bool = False,
) -> dict[str, Any]:
    t0 = time.time()
    fuzz_summary = summarize_fuzz_dir(fuzz_dir) if fuzz_dir is not None else {"present": False, "tiers": [], "totals": {}}

    if synthetic or v15_root is None:
        factory = make_synthetic_v15_factory(plant_leak=False)
        result = _execute_audit_suite(factory, "synthetic-v1.5", fuzz_summary, seeds, solver_seeds, tiers)
        result["seconds"] = round(time.time() - t0, 2)
        return result

    activate_repo_root(v15_root)
    import canary.rules as rules

    sha = git_head_sha(v15_root)
    with rules.tiers_version("v1.5-candidate"):
        factory = make_real_v15_factory()
        result = _execute_audit_suite(factory, f"justSilas-v15@{sha}", fuzz_summary, seeds, solver_seeds, tiers)
    result["v15_commit"] = sha
    result["seconds"] = round(time.time() - t0, 2)
    return result


def _execute_audit_suite(
    factory: Callable[..., Any],
    source_label: str,
    fuzz_summary: dict[str, Any],
    seeds: list[int],
    solver_seeds: list[int],
    tiers: list[str],
) -> dict[str, Any]:
    word_leaks: dict[str, Any] = {}
    conditionals: dict[str, Any] = {}
    exclusion_curves: dict[str, Any] = {}
    invariants: dict[str, Any] = {}
    policies: dict[str, Any] = {}

    for tier in tiers:
        word_leaks[tier] = audit_word_and_token_leaks(factory, tier, seeds)
        conditionals[tier] = audit_social_conditionals(factory, tier, seeds)
        chk = (3, 6, 10, 21) if tier == "hard" else (3, 6, 10, 14)
        exclusion_curves[tier] = audit_exclusion_by_day(factory, tier, seeds, checkpoints=chk)
        invariants[tier] = audit_invariants(factory, tier, seeds)
        policies[tier] = audit_policies(factory, tier, solver_seeds, include_log_probes=True)

    extra_probes: dict[str, Any] = {}
    if "hard" in tiers:
        extra_probes["hard_random_peer_conditionals"] = audit_social_conditionals(
            factory, "hard", seeds, seed_rumour="random_peer"
        )
        extra_probes["hard_random_peer_word_leaks"] = audit_word_and_token_leaks(
            factory, "hard", seeds[:50], seed_rumour="random_peer"
        )
        gate_b_seeds = list(range(0, 10))
        extra_probes["hard_gate_b_seeds_0_9"] = audit_policies(
            factory, "hard", gate_b_seeds, include_log_probes=True
        )
        peer_probe_seeds = solver_seeds[: min(len(solver_seeds), 50)]
        extra_probes["hard_random_peer_policies"] = audit_policies(
            factory, "hard", peer_probe_seeds, seed_rumour="random_peer", include_log_probes=False
        )
        extra_probes["easy_policies_50"] = audit_policies(
            factory, "easy", solver_seeds[: min(len(solver_seeds), 50)], include_log_probes=False
        )

    return {
        "source": source_label,
        "workers": 1,
        "llm_calls": 0,
        "seeds": [seeds[0], seeds[-1]],
        "n_seeds": len(seeds),
        "solver_seeds": [solver_seeds[0], solver_seeds[-1]],
        "n_solver_seeds": len(solver_seeds),
        "tiers": tiers,
        "fuzz_4tier": fuzz_summary,
        "word_and_token_leaks": word_leaks,
        "social_conditionals": conditionals,
        "exclusion_by_day": exclusion_curves,
        "invariants": invariants,
        "policy_comparisons": policies,
        "extra_probes": extra_probes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit justSilas-v15 social mechanics, anti-inversion leaks, and fuzz outputs.")
    ap.add_argument("--v15-root", type=Path, default=None)
    ap.add_argument("--fuzz-dir", type=Path, default=None)
    ap.add_argument("--seeds", default="7500:7700")
    ap.add_argument("--solver-seeds", default=None)
    ap.add_argument("--tiers", default="hard,medium")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise ValueError("integrity_v15_social_sweep requires --workers 1")

    if args.self_test:
        repo_root = Path(__file__).resolve().parent.parent
        activate_repo_root(repo_root)
        res = run_self_test()
        payload = json.dumps(res, indent=2, sort_keys=True)
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(payload + "\n")
        print(payload)
        return 0 if res["ok"] else 1

    if args.v15_root is None and not args.synthetic:
        repo_root = Path(__file__).resolve().parent.parent
        activate_repo_root(repo_root)
        args.synthetic = True

    seeds = parse_seed_spec(args.seeds)
    solver_seeds = parse_seed_spec(args.solver_seeds) if args.solver_seeds else list(seeds)
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]

    res = run_full_audit(
        v15_root=args.v15_root,
        fuzz_dir=args.fuzz_dir,
        seeds=seeds,
        solver_seeds=solver_seeds,
        tiers=tiers,
        synthetic=args.synthetic,
    )
    payload = json.dumps(res, indent=2, sort_keys=True)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload + "\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
