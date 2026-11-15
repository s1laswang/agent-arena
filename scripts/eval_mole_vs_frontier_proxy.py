from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any, Iterable

import numpy as np

from canary.baselines import GrokTactics, Heuristic, TOPICS, employee_ids
from canary.env import Env
from canary.eval import run_episode
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import RLMole
from canary.forge.rl_mole_v2 import RLMoleV2
from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS, MoleStrategy
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.types import INVESTIGATIVE_TOOLS, Step

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "results" / "moletrain" / "frontier_proxy_mole_matrix.json"
MAX_MATRIX_BYTES = 45_000

AGENTS: tuple[str, ...] = (
    "solver",
    "grok_tactics",
    "heuristic",
    "hinted_heuristic",
    "gemini_carbon_proxy",
)
NON_SOLVER_AGENTS: tuple[str, ...] = (
    "grok_tactics",
    "heuristic",
    "hinted_heuristic",
    "gemini_carbon_proxy",
)
SCRIPTED_INVESTIGATORS: tuple[str, ...] = (
    "grok_tactics",
    "heuristic",
    "hinted_heuristic",
)
DEFAULT_POLICY_SPECS: tuple[str, ...] = (
    "default",
    "rl_mole:data/rl_mole/policy_final.json",
    "rl_mole_v2:results/moletrain/rl_mole_v2_policy.json",
    "fixed:none/decoy",
    "fixed:random_seeded/decoy",
)
DEFAULT_SUITE_BASES: tuple[tuple[str, int], ...] = (
    ("200000-200029", 200_000),
    ("800000-800029", 800_000),
)
PROXY_LABELS: tuple[str, ...] = ("v1", "v2", "v3", "v4")
ANGRY_WORDS: tuple[str, ...] = (
    "unfair",
    "angry",
    "furious",
    "sick of",
    "quit",
    "ridiculous",
    "fed up",
    "hate",
    "frustrated",
    "promotion",
    "goalposts",
    "burn out",
    "deserve",
    "joke",
)


def _parse_instruction_params(instruction: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (instruction or "").splitlines():
        line = raw.strip()
        if line.startswith("- ") and ": " in line:
            k, v = line[2:].split(": ", 1)
            if k.replace("_", "").isalnum():
                out.setdefault(k, v.strip())
    return out


def _fallback_employees(instruction: str) -> list[str]:
    m = re.search(r"\be00\b(?:\s*(?:to|\.\.)\s*)\be(\d{2,3})\b", instruction or "")
    if m:
        hi = int(m.group(1))
        width = len(m.group(1))
        return [f"e{i:0{width}d}" for i in range(hi + 1)]
    m = re.search(r"with (\d+) employees", instruction or "")
    if m:
        n = int(m.group(1))
        return [f"e{i:02d}" for i in range(n)]
    return []


class FallbackGeminiCarbonProxy:
    name = "gemini_carbon_proxy"

    def __init__(
        self,
        seed: int = 0,
        accuse_threshold: float = 0.55,
        decoy_weight: float = 0.25,
        after_hours_pull: float = 0.08,
        canary_start_day: int = 3,
    ):
        self.seed = int(seed)
        self.accuse_threshold = float(accuse_threshold)
        self.decoy_weight = float(decoy_weight)
        self.after_hours_pull = float(after_hours_pull)
        self.canary_start_day = int(canary_start_day)
        self.reset([], "")

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self.tools_spec = list(tools_spec or [])
        self.instruction = instruction or ""
        p = _parse_instruction_params(self.instruction)
        low = self.instruction.lower()

        m_days = re.search(r"at most (\d+) days", self.instruction)
        self.n_days = int(float(p["n_days"])) if "n_days" in p else (int(m_days.group(1)) if m_days else 21)

        m_var = re.search(r"at most (\d+) (?:different|distinct) (?:variant|label)", self.instruction)
        self.max_variants = int(float(p["max_variants"])) if "max_variants" in p else (int(m_var.group(1)) if m_var else 3)
        self.max_variants = max(2, self.max_variants)

        self.canaries_per_day = int(float(p.get("canaries_per_day", 2)))
        self.actions_per_day = int(float(p.get("actions_per_day", 8)))
        self.wrong_accusation_score = float(p.get("wrong_accusation_score", -1.0))

        m_fp = re.search(r"variant label the mole received with probability ([0-9]*\.?[0-9]+)", self.instruction)
        if "fingerprint_accuracy" in p:
            self.fingerprint_accuracy = float(p["fingerprint_accuracy"])
        elif m_fp:
            self.fingerprint_accuracy = float(m_fp.group(1))
        else:
            self.fingerprint_accuracy = 0.95

        if "decoy" in p:
            self.has_decoy = p["decoy"].lower() in ("on", "true", "1", "yes")
        elif "there is no decoy" in low:
            self.has_decoy = False
        else:
            self.has_decoy = True

        self.rng = random.Random(f"gemini_carbon_proxy:{self.seed}")
        self.seen = 0
        self.list_emps_called = False
        self.emps: list[str] = []
        self.tie_order: dict[str, float] = {}
        self.day = 1
        self.V = 1.0
        self.actions_left = self.actions_per_day
        self.restricted: set[str] = set()
        self.docs: dict[str, dict[str, Any]] = {}
        self.planted_variants: dict[str, dict[str, list[str]]] = {}
        self.feed_seen: set[tuple[Any, ...]] = set()
        self.regular_leaks: list[set[str]] = []
        self.canary_leaks: list[tuple[set[str], dict[str, set[str]], str]] = []
        self.decoy: str | None = None
        self.angry_counts: Counter[str] = Counter()
        self.seen_msg_ids: set[str] = set()
        self.after_hours: Counter[str] = Counter()
        self.last_log_day = 0
        self.canary_exposures: Counter[str] = Counter()
        self.interview_cursor = 0
        self.interviewed_today: set[str] = set()
        self.planned_day = 0
        self.queue: list[tuple[str, dict[str, Any]]] = []

    def _init_employees(self, ids: list[str]) -> None:
        self.emps = list(ids)
        for emp in self.emps:
            if emp not in self.tie_order:
                self.tie_order[emp] = self.rng.random()

    def _ingest(self, step: Step) -> None:
        res = step.result or {}
        if step.tool == "list_employees":
            self.list_emps_called = True
        if not res.get("ok"):
            if "daily action limit" in str(res.get("error") or ""):
                self.actions_left = 0
            return
        if step.tool in INVESTIGATIVE_TOOLS:
            self.actions_left = max(0, self.actions_left - 1)
        data = res.get("data")
        if not isinstance(data, dict):
            data = {}

        if step.tool == "list_employees":
            ids = employee_ids(res) or _fallback_employees(self.instruction)
            if ids:
                self._init_employees(ids)
        elif step.tool == "status":
            new_day = int(data.get("day", self.day))
            if new_day != self.day:
                self.day = new_day
                self.interviewed_today.clear()
            self.V = float(data.get("V", data.get("value", self.V)))
            if "actions_left_today" in data:
                self.actions_left = int(data["actions_left_today"])
            if "restricted" in data:
                self.restricted = set(data.get("restricted") or [])
        elif step.tool == "advance_day":
            self.day = int(data.get("day", self.day + 1))
            if "V" in data:
                self.V = float(data["V"])
            self.actions_left = self.actions_per_day
            self.interviewed_today.clear()
        elif step.tool == "list_documents":
            for doc in data.get("documents") or []:
                if isinstance(doc, dict) and "doc_id" in doc:
                    self.docs[str(doc["doc_id"])] = doc
        elif step.tool == "plant_canary":
            cid = str(data.get("canary_id") or data.get("doc_id") or f"c{self.day}")
            asg = dict(step.args.get("assignment") or {})
            variants: dict[str, list[str]] = {}
            for emp, lab in sorted(asg.items()):
                variants.setdefault(str(lab), []).append(str(emp))
            self.planted_variants[cid] = variants
            self.docs.setdefault(
                cid,
                {
                    "doc_id": cid,
                    "day": step.day,
                    "recipients": sorted(asg),
                    "is_canary": True,
                    "variants": variants,
                },
            )
            for emp in asg:
                self.canary_exposures[str(emp)] += 1
        elif step.tool == "check_leak_feed":
            for it in data.get("items") or []:
                if not isinstance(it, dict):
                    continue
                did = str(it.get("doc_id") or "")
                var = it.get("variant")
                key = (did, it.get("surfaced_day"), var)
                if key in self.feed_seen:
                    continue
                self.feed_seen.add(key)
                doc = self.docs.get(did) or {}
                vmap = doc.get("variants") or self.planted_variants.get(did)
                if var and isinstance(vmap, dict) and vmap:
                    groups = {str(lab): {str(x) for x in ms} for lab, ms in vmap.items()}
                    recips = set().union(*groups.values()) if groups else {str(x) for x in doc.get("recipients") or []}
                    self.canary_leaks.append((recips, groups, str(var)))
                elif doc.get("recipients") and not doc.get("is_canary"):
                    self.regular_leaks.append({str(x) for x in doc["recipients"]})
        elif step.tool == "search_messages":
            for m in data.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                snd = m.get("sender")
                if not isinstance(snd, str):
                    continue
                mid = m.get("id")
                txt = f"{m.get('subject', '')} {m.get('snippet', '')} {m.get('body', '')}".lower()
                if any(w in txt for w in ANGRY_WORDS):
                    if mid is None or str(mid) not in self.seen_msg_ids:
                        if mid is not None:
                            self.seen_msg_ids.add(str(mid))
                        self.angry_counts[snd] += 1
            if self.has_decoy and self.angry_counts:
                self.decoy = sorted(self.angry_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        elif step.tool == "read_access_logs":
            d_to = int(step.args.get("day_to", self.last_log_day))
            self.last_log_day = max(self.last_log_day, d_to)
            for entry in data.get("logs") or []:
                if isinstance(entry, dict) and entry.get("after_hours"):
                    emp = entry.get("employee")
                    if isinstance(emp, str):
                        self.after_hours[emp] += 1
        elif step.tool == "interview":
            emp = step.args.get("employee")
            if isinstance(emp, str):
                self.interviewed_today.add(emp)

    def _posterior(self) -> tuple[set[str], dict[str, float]]:
        pool = set(self.emps)
        for recips in self.regular_leaks:
            if pool & recips:
                pool &= recips
        for crecips, _, _ in self.canary_leaks:
            if pool & crecips:
                pool &= crecips
        if not pool:
            pool = set(self.emps)

        w: dict[str, float] = {}
        for emp in self.emps:
            if emp not in pool:
                w[emp] = 0.0
                continue
            base = self.decoy_weight if (self.has_decoy and emp == self.decoy and len(pool) > 1) else 1.0
            ah_pull = math.exp(self.after_hours_pull * min(self.after_hours[emp], 10))
            w[emp] = base * ah_pull

        q_subj = min(0.99, self.fingerprint_accuracy + 0.03) if self.fingerprint_accuracy < 1.0 else 1.0
        for crecips, groups, shown in self.canary_leaks:
            k_var = max(2, len(groups))
            hit = groups.get(shown, set())
            miss_w = (1.0 - q_subj) / (k_var - 1)
            for emp in pool:
                if emp in hit:
                    w[emp] *= q_subj
                elif emp in crecips:
                    w[emp] *= miss_w

        tot = sum(w.values())
        if tot <= 0.0:
            u = 1.0 / max(1, len(pool))
            return pool, {emp: (u if emp in pool else 0.0) for emp in self.emps}
        return pool, {emp: val / tot for emp, val in w.items()}

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < self.seen:
            self.reset(self.tools_spec, self.instruction)
        for st in history[self.seen:]:
            self._ingest(st)
        self.seen = len(history)

        if not self.list_emps_called:
            return ("list_employees", {})
        if not self.emps:
            fb = _fallback_employees(self.instruction)
            if fb:
                self._init_employees(fb)
            else:
                return ("advance_day", {})

        if self.planned_day != self.day:
            self.planned_day = self.day
            d_hi = min(self.day, self.n_days)
            d_lo = 1 if d_hi <= 1 else max(1, d_hi - 2)
            q: list[tuple[str, dict[str, Any]]] = [
                ("status", {}),
                ("list_documents", {"day_from": d_lo, "day_to": d_hi}),
            ]
            if self.day == 1:
                q.append(("search_messages", {"query": "unfair"}))
            elif self.day == 2 and self.has_decoy and self.decoy is None:
                q.append(("search_messages", {"query": "angry"}))
            q.append(("check_leak_feed", {}))
            if self.day >= 2 and self.last_log_day < self.day - 1:
                if self.day % 2 == 0 or self.day >= self.n_days - 2:
                    log_from = max(1, self.last_log_day + 1)
                    log_to = min(self.n_days, max(log_from, self.day - 1))
                    q.append(("read_access_logs", {"day_from": log_from, "day_to": log_to}))
            q.append(("__decide__", {}))
            self.queue = q

        while self.queue:
            tool, args = self.queue.pop(0)
            if tool == "__decide__":
                self._decide_next()
                continue
            if tool in INVESTIGATIVE_TOOLS and self.actions_left <= 0:
                continue
            return (tool, args)
        return ("advance_day", {})

    def _decide_next(self) -> None:
        pool, post = self._posterior()
        live = sorted([e for e in pool if post[e] > 1e-4]) or sorted(pool)
        best = max(live, key=lambda e: (round(post[e], 8), self.after_hours[e], self.tie_order[e]))
        pb = post[best]
        ev = pb * self.V + (1.0 - pb) * self.wrong_accusation_score

        if pb >= self.accuse_threshold and ev > 0.0:
            self.queue = [("accuse", {"employee": best})]
            return

        if self.day >= self.n_days:
            if pb >= 0.40:
                self.queue = [("accuse", {"employee": best})]
            else:
                self.queue = [("advance_day", {})]
            return

        nxt: list[tuple[str, dict[str, Any]]] = []
        if self.actions_left >= 3 and len(live) >= 2:
            iv_cands = [e for e in live if e not in self.interviewed_today]
            if iv_cands:
                e0 = iv_cands[(self.day + self.seed) % len(iv_cands)]
                topic = TOPICS[self.interview_cursor % len(TOPICS)]
                self.interview_cursor += 1
                nxt.append(("interview", {"employee": e0, "topic": topic}))

        start_d = self.canary_start_day if self.n_days >= 10 else 2
        plant_today = self.day >= start_d and (self.day + self.seed) % 3 != 1
        if plant_today and self.canaries_per_day >= 1 and self.actions_left - len(nxt) >= 1:
            cand = [e for e in live if e not in self.restricted]
            if len(cand) >= 2:
                cand.sort(
                    key=lambda e: (
                        -round(post[e], 5),
                        -self.after_hours[e],
                        self.canary_exposures[e],
                        -self.tie_order[e],
                    )
                )
                cap = 6 if (self.day + self.seed) % 2 == 0 else 8
                subset = cand[: min(len(cand), cap)]
                use_three = self.max_variants >= 3 and len(subset) >= 6 and (self.day + self.seed) % 3 == 0
                k_var = 3 if use_three else 2
                labels = PROXY_LABELS[:k_var]
                asg = {emp: labels[i % k_var] for i, emp in enumerate(subset)}
                nxt.append(("plant_canary", {"doc_title": f"Security review d{self.day}", "assignment": asg}))

        nxt.append(("advance_day", {}))
        self.queue = nxt


def resolve_gemini_carbon_proxy(force_fallback: bool = False) -> tuple[type, str]:
    if not force_fallback:
        try:
            from canary.forge.frontier_proxies import GeminiCarbonProxy as _ExtProxy

            return _ExtProxy, "canary.forge.frontier_proxies:GeminiCarbonProxy"
        except ImportError:
            pass
    return FallbackGeminiCarbonProxy, "builtin_fallback"


GeminiCarbonProxy, GEMINI_PROXY_SOURCE = resolve_gemini_carbon_proxy()


def validate_seed_hygiene(seeds: Iterable[int]) -> list[int]:
    out = [int(s) for s in seeds]
    if not out:
        raise ValueError("seed list cannot be empty")
    if len(set(out)) != len(out):
        raise ValueError("duplicate seeds in evaluation suite")
    for s in out:
        if s < 0:
            raise ValueError(f"negative seed forbidden: {s}")
        if 0 <= s < 10_000:
            raise ValueError(f"dev calibration seed forbidden in held-out mole eval: {s}")
        if 100_000 <= s < 200_000:
            raise ValueError(f"training seed forbidden in held-out mole eval: {s}")
        if 300_000 <= s < 400_000:
            raise ValueError(f"grpo prompt seed forbidden in held-out mole eval: {s}")
        if s >= 900_000:
            raise ValueError(f"judge seed forbidden in held-out mole eval: {s}")
    return out


@dataclass(frozen=True)
class MolePolicySpec:
    label: str
    kind: str
    source: str
    payload: dict[str, Any] | None

    def instantiate(self):
        if self.kind == "default":
            return None
        if self.kind == "rl_mole":
            assert self.payload is not None
            return RLMole.from_json(self.payload)
        if self.kind == "rl_mole_v2":
            assert self.payload is not None
            return RLMoleV2.from_json(self.payload)
        if self.kind in ("fixed_dsl", "dsl"):
            assert self.payload is not None
            return MoleStrategy.from_json(self.payload)
        raise ValueError(f"unknown mole policy kind: {self.kind}")


def _resolve_path(raw_path: str) -> Path:
    p = Path(raw_path)
    if p.is_absolute():
        return p
    cand = ROOT / p
    return cand if cand.exists() else p


def _load_rl_mole_v2_json(path: Path, greedy_override: bool = False) -> dict[str, Any]:
    loader = getattr(RLMoleV2, "load", None)
    if callable(loader):
        pol = loader(path)
        obj = pol.to_json()
    else:
        obj = json.loads(path.read_text(encoding="utf-8"))
    if greedy_override:
        obj = dict(obj, greedy=True)
    RLMoleV2.from_json(obj)
    return obj


def _load_dsl_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if path.suffix == ".jsonl":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            raise ValueError(f"empty jsonl file: {path}")
        obj = json.loads(lines[0])
    else:
        obj = json.loads(text)
    if isinstance(obj, dict) and ("strategy_json" in obj or "strategy" in obj):
        inner = obj.get("strategy_json", obj.get("strategy"))
        if not isinstance(inner, dict):
            raise ValueError(f"invalid wrapped strategy in {path}")
        return inner
    if not isinstance(obj, dict):
        raise ValueError(f"expected strategy dict in {path}")
    return obj


def parse_mole_spec(raw: str, default_kind: str | None = None) -> MolePolicySpec:
    spec = raw.strip()
    if not spec:
        raise ValueError("empty mole policy spec")
    if spec == "default":
        return MolePolicySpec(label="default", kind="default", source="default", payload=None)

    custom_label: str | None = None
    known_prefixes = (
        "rl_mole:",
        "rl_mole_greedy:",
        "rl_mole_v2:",
        "rl_mole_v2_greedy:",
        "fixed:",
        "dsl:",
    )
    if "=" in spec and not spec.startswith(known_prefixes):
        custom_label, spec = [part.strip() for part in spec.split("=", 1)]

    if spec.startswith("fixed:"):
        body = spec[len("fixed:") :]
        if "/" not in body:
            raise ValueError(f"fixed spec must be fixed:<leak>/<frame>, got {raw!r}")
        leak, frame = [x.strip() for x in body.split("/", 1)]
        if leak not in LEAK_SELECTORS or frame not in FRAME_SELECTORS:
            raise ValueError(f"invalid fixed selectors in {raw!r}")
        strat = MoleStrategy(rules=(), default=(leak, frame), name=f"fixed_{leak}_{frame}")
        label = custom_label or f"fixed:{leak}/{frame}"
        return MolePolicySpec(label=label, kind="fixed_dsl", source=spec, payload=strat.to_json())

    if spec.startswith("rl_mole_v2:") or spec.startswith("rl_mole_v2_greedy:") or default_kind == "rl_mole_v2":
        greedy_override = spec.startswith("rl_mole_v2_greedy:")
        if spec.startswith("rl_mole_v2:"):
            rel = spec[len("rl_mole_v2:") :]
        elif spec.startswith("rl_mole_v2_greedy:"):
            rel = spec[len("rl_mole_v2_greedy:") :]
        else:
            rel = spec
        path = _resolve_path(rel)
        obj = _load_rl_mole_v2_json(path, greedy_override=greedy_override)
        prefix = "rl_mole_v2_greedy" if greedy_override else "rl_mole_v2"
        label = custom_label or f"{prefix}:{rel}"
        return MolePolicySpec(label=label, kind="rl_mole_v2", source=rel, payload=obj)

    if spec.startswith("rl_mole:") or spec.startswith("rl_mole_greedy:") or default_kind == "rl_mole":
        greedy_override = spec.startswith("rl_mole_greedy:")
        if spec.startswith("rl_mole:"):
            rel = spec[len("rl_mole:") :]
        elif spec.startswith("rl_mole_greedy:"):
            rel = spec[len("rl_mole_greedy:") :]
        else:
            rel = spec
        path = _resolve_path(rel)
        obj = json.loads(path.read_text(encoding="utf-8"))
        if default_kind == "rl_mole" and not spec.startswith(("rl_mole:", "rl_mole_greedy:")) and obj.get("kind") == "rl_mole_v2":
            obj_v2 = _load_rl_mole_v2_json(path, greedy_override=greedy_override)
            label = custom_label or f"rl_mole_v2:{rel}"
            return MolePolicySpec(label=label, kind="rl_mole_v2", source=rel, payload=obj_v2)
        if greedy_override:
            obj = dict(obj, greedy=True)
        RLMole.from_json(obj)
        prefix = "rl_mole_greedy" if greedy_override else "rl_mole"
        label = custom_label or f"{prefix}:{rel}"
        return MolePolicySpec(label=label, kind="rl_mole", source=rel, payload=obj)

    if spec.startswith("dsl:") or default_kind == "dsl":
        rel = spec[len("dsl:") :] if spec.startswith("dsl:") else spec
        path = _resolve_path(rel)
        obj = _load_dsl_json(path)
        MoleStrategy.from_json(obj)
        label = custom_label or f"dsl:{rel}"
        return MolePolicySpec(label=label, kind="dsl", source=rel, payload=obj)

    raise ValueError(f"unrecognized mole policy spec: {raw!r}")


def make_investigator(name: str, tier: str, seed: int, proxy_cls: type | None = None):
    if name == "solver":
        return SolverPolicy(tier)
    if name == "grok_tactics":
        return GrokTactics(seed=seed)
    if name == "heuristic":
        return Heuristic(seed=seed)
    if name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if name == "gemini_carbon_proxy":
        cls = proxy_cls or GeminiCarbonProxy
        return cls(seed=seed)
    raise ValueError(f"unknown investigator: {name}")


def _eval_seed_all_policies(
    task: tuple[tuple[MolePolicySpec, ...], str, int, tuple[str, ...], bool],
) -> dict[str, dict[str, tuple[float, float]]]:
    specs, tier, seed, agents, force_fallback = task
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    logging.getLogger("canary.world").setLevel(logging.ERROR)
    proxy_cls, _ = resolve_gemini_carbon_proxy(force_fallback=force_fallback)
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for spec in specs:
        pol_out: dict[str, tuple[float, float]] = {}
        for ag in agents:
            env = Env(tier, seed, mole_strategy=spec.instantiate())
            pol = make_investigator(ag, tier, seed, proxy_cls=proxy_cls)
            res = run_episode(env, pol)
            pol_out[ag] = (float(res.score), 1.0 if res.correct else 0.0)
        out[spec.label] = pol_out
    return out


def run_suite_seeds(
    specs: list[MolePolicySpec],
    tier: str,
    seeds: list[int],
    agents: tuple[str, ...] = AGENTS,
    workers: int = 1,
    force_fallback: bool = False,
) -> dict[str, list[dict[str, tuple[float, float]]]]:
    spec_tuple = tuple(specs)
    tasks = [(spec_tuple, tier, s, agents, force_fallback) for s in seeds]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
            seed_rows = list(ex.map(_eval_seed_all_policies, tasks))
    else:
        seed_rows = [_eval_seed_all_policies(t) for t in tasks]
    return {
        sp.label: [row[sp.label] for row in seed_rows]
        for sp in spec_tuple
    }


def _ci_from_boot(point: float, boot_samples: np.ndarray) -> dict[str, Any]:
    b = int(boot_samples.shape[0])
    s = np.sort(boot_samples)
    lo = float(s[int(0.025 * b)])
    hi = float(s[int(0.975 * b)])
    return {"mean": round(float(point), 4), "ci95": [round(lo, 4), round(hi, 4)]}


def _bootstrap_indices(n: int, resamples: int = 2000, seed: int = 20261114) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, n, size=(resamples, n))


def summarize_suite(
    rows_by_policy: dict[str, list[dict[str, tuple[float, float]]]],
    agents: tuple[str, ...] = AGENTS,
    resamples: int = 2000,
    boot_seed: int = 20261114,
) -> dict[str, Any]:
    if "default" not in rows_by_policy:
        raise ValueError("rows_by_policy must include 'default' for paired bootstrap CIs and catchability")

    default_rows = rows_by_policy["default"]
    n = len(default_rows)
    idx = _bootstrap_indices(n, resamples=resamples, seed=boot_seed)
    non_solver = tuple(a for a in agents if a != "solver")
    scripted = tuple(a for a in SCRIPTED_INVESTIGATORS if a in agents)

    def to_arrays(rows: list[dict[str, tuple[float, float]]]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
        sc = {a: np.asarray([r[a][0] for r in rows], dtype=np.float64) for a in agents}
        ac = {a: np.asarray([r[a][1] for r in rows], dtype=np.float64) for a in agents}
        return sc, ac

    def_sc, def_ac = to_arrays(default_rows)
    default_solver_score = float(def_sc["solver"].mean())

    def boot_mean(arr: np.ndarray) -> np.ndarray:
        return arr[idx].mean(axis=1)

    def boot_min_regret(sc_map: dict[str, np.ndarray], pool_agents: tuple[str, ...]) -> tuple[float, np.ndarray]:
        sol_pt = float(sc_map["solver"].mean())
        pt = min((sol_pt - float(sc_map[k].mean()) for k in pool_agents), default=0.0)
        if not pool_agents:
            return 0.0, np.zeros(resamples, dtype=np.float64)
        sol_b = boot_mean(sc_map["solver"])
        reg_b = np.stack([sol_b - boot_mean(sc_map[k]) for k in pool_agents], axis=1)
        return pt, reg_b.min(axis=1)

    def_min_pt, def_min_b = boot_min_regret(def_sc, non_solver)
    def_scr_pt, def_scr_b = boot_min_regret(def_sc, scripted)
    def_gap_vec = def_sc["solver"] - def_sc["gemini_carbon_proxy"] if "gemini_carbon_proxy" in def_sc else np.zeros(n)

    policies_out: dict[str, Any] = {}
    for label, rows in rows_by_policy.items():
        if len(rows) != n:
            raise ValueError(f"policy {label} has {len(rows)} rows, expected {n}")
        sc, ac = to_arrays(rows)
        ag_summary = {
            a: {
                "score": _ci_from_boot(float(sc[a].mean()), boot_mean(sc[a])),
                "acc": _ci_from_boot(float(ac[a].mean()), boot_mean(ac[a])),
            }
            for a in agents
        }
        regrets = {}
        for k in non_solver:
            vec = sc["solver"] - sc[k]
            regrets[k] = _ci_from_boot(float(vec.mean()), boot_mean(vec))

        gap_vec = sc["solver"] - sc["gemini_carbon_proxy"] if "gemini_carbon_proxy" in sc else np.zeros(n)
        gap_ci = _ci_from_boot(float(gap_vec.mean()), boot_mean(gap_vec))

        min_pt, min_b = boot_min_regret(sc, non_solver)
        scr_pt, scr_b = boot_min_regret(sc, scripted)
        strongest = max(non_solver, key=lambda k: float(sc[k].mean())) if non_solver else "none"

        sol_score = float(sc["solver"].mean())
        sol_acc = float(ac["solver"].mean())
        ratio = sol_score / default_solver_score if default_solver_score > 0.0 else 0.0
        catchable_85 = bool(sol_acc >= 0.85 and sol_score >= 0.5 * default_solver_score)
        catchable_75 = bool(sol_acc >= 0.75 and sol_score >= 0.5 * default_solver_score)

        diff_score = {
            a: _ci_from_boot(float((sc[a] - def_sc[a]).mean()), boot_mean(sc[a] - def_sc[a]))
            for a in agents
        }
        diff_acc = {
            a: _ci_from_boot(float((ac[a] - def_ac[a]).mean()), boot_mean(ac[a] - def_ac[a]))
            for a in agents
        }
        diff_gap_vec = gap_vec - def_gap_vec
        paired_diff = {
            "agent_score": diff_score,
            "agent_acc": diff_acc,
            "solver_minus_carbon_proxy": _ci_from_boot(float(diff_gap_vec.mean()), boot_mean(diff_gap_vec)),
            "min_regret": _ci_from_boot(float(min_pt - def_min_pt), min_b - def_min_b),
            "scripted_min_regret": _ci_from_boot(float(scr_pt - def_scr_pt), scr_b - def_scr_b),
        }

        policies_out[label] = {
            "agents": ag_summary,
            "regret_vs_solver": regrets,
            "solver_minus_carbon_proxy": gap_ci,
            "min_regret": _ci_from_boot(min_pt, min_b),
            "scripted_min_regret": _ci_from_boot(scr_pt, scr_b),
            "strongest_investigator": strongest,
            "solver_score_ratio_vs_default": round(ratio, 4),
            "catchable_85": catchable_85,
            "catchable_75": catchable_75,
            "paired_diff_vs_default": paired_diff,
        }

    return {
        "n": n,
        "default_solver_score": round(default_solver_score, 4),
        "policies": policies_out,
    }


def build_headline(suites_out: dict[str, Any], policy_labels: list[str]) -> dict[str, Any]:
    headline: dict[str, Any] = {}
    for pol in policy_labels:
        headline[pol] = {}
        for sname, sdata in suites_out.items():
            ps = sdata["policies"][pol]
            headline[pol][sname] = {
                "solver_score": ps["agents"]["solver"]["score"]["mean"],
                "solver_acc": ps["agents"]["solver"]["acc"]["mean"],
                "gemini_carbon_proxy_score": ps["agents"]["gemini_carbon_proxy"]["score"]["mean"],
                "gemini_carbon_proxy_acc": ps["agents"]["gemini_carbon_proxy"]["acc"]["mean"],
                "solver_minus_carbon_proxy": ps["solver_minus_carbon_proxy"]["mean"],
                "min_regret": ps["min_regret"]["mean"],
                "delta_gap_vs_default": ps["paired_diff_vs_default"]["solver_minus_carbon_proxy"]["mean"],
                "delta_min_regret_vs_default": ps["paired_diff_vs_default"]["min_regret"]["mean"],
                "catchable_85": ps["catchable_85"],
            }
    return headline


def evaluate_matrix(
    policy_specs: list[MolePolicySpec],
    suites: list[tuple[str, list[int]]],
    tier: str = "hard",
    workers: int = 1,
    resamples: int = 2000,
    boot_seed: int = 20261114,
    force_fallback: bool = False,
) -> dict[str, Any]:
    if not any(s.label == "default" for s in policy_specs):
        policy_specs = [parse_mole_spec("default")] + list(policy_specs)

    validated_suites: list[tuple[str, list[int]]] = []
    all_seeds: list[int] = []
    for name, seeds in suites:
        clean = validate_seed_hygiene(seeds)
        validated_suites.append((name, clean))
        all_seeds.extend(clean)
    validate_seed_hygiene(all_seeds)

    _, proxy_source = resolve_gemini_carbon_proxy(force_fallback=force_fallback)
    t0 = time.perf_counter()

    raw_suite_rows: dict[str, dict[str, list[dict[str, tuple[float, float]]]]] = {}
    for name, seeds in validated_suites:
        raw_suite_rows[name] = run_suite_seeds(
            specs=policy_specs,
            tier=tier,
            seeds=seeds,
            agents=AGENTS,
            workers=workers,
            force_fallback=force_fallback,
        )

    suites_out: dict[str, Any] = {}
    for idx_s, (name, seeds) in enumerate(validated_suites):
        summary = summarize_suite(
            raw_suite_rows[name],
            agents=AGENTS,
            resamples=resamples,
            boot_seed=boot_seed + idx_s,
        )
        suites_out[name] = {
            "seed_range": f"{seeds[0]}-{seeds[-1]}",
            "n": summary["n"],
            "default_solver_score": summary["default_solver_score"],
            "policies": summary["policies"],
        }

    if len(validated_suites) > 1:
        pooled_rows: dict[str, list[dict[str, tuple[float, float]]]] = {}
        for spec in policy_specs:
            combined: list[dict[str, tuple[float, float]]] = []
            for name, _ in validated_suites:
                combined.extend(raw_suite_rows[name][spec.label])
            pooled_rows[spec.label] = combined
        pooled_summary = summarize_suite(
            pooled_rows,
            agents=AGENTS,
            resamples=resamples,
            boot_seed=boot_seed + 99,
        )
        pooled_key = f"combined_{len(all_seeds)}"
        suites_out[pooled_key] = {
            "seed_range": ",".join(f"{s[0]}-{s[-1]}" for _, s in validated_suites),
            "n": pooled_summary["n"],
            "default_solver_score": pooled_summary["default_solver_score"],
            "policies": pooled_summary["policies"],
        }

    elapsed_s = round(time.perf_counter() - t0, 2)
    policy_labels = [s.label for s in policy_specs]
    world_key_mode = "env_secret" if os.environ.get("CANARY_WORLD_SECRET") else "per_process_paired"
    return {
        "schema": "canary.moletrain.frontier_proxy_mole_matrix.v1",
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "gemini_carbon_proxy_source": proxy_source,
        "heldout_800k_world_key_mode": world_key_mode,
        "agents": list(AGENTS),
        "bootstrap": {
            "resamples": resamples,
            "ci_level": 0.95,
            "seed": boot_seed,
            "paired_baseline": "default",
        },
        "catchability_rule": {
            "name": "catchable_85",
            "min_solver_acc": 0.85,
            "min_solver_score_ratio_vs_default": 0.5,
        },
        "policy_specs": [
            {"label": s.label, "kind": s.kind, "source": s.source}
            for s in policy_specs
        ],
        "elapsed_s": elapsed_s,
        "headline": build_headline(suites_out, policy_labels),
        "suites": suites_out,
    }


def _is_compact_leaf(obj: Any) -> bool:
    if isinstance(obj, dict):
        keys = set(obj.keys())
        if keys == {"mean", "ci95"} or keys == {"label", "kind", "source"} or keys == {"score", "acc"}:
            return True
    if isinstance(obj, list) and all(not isinstance(x, (dict, list)) for x in obj):
        return True
    return False


def _dumps_matrix_json(obj: Any, level: int = 0) -> str:
    if _is_compact_leaf(obj):
        return json.dumps(obj, separators=(", ", ": "))
    pad = " " * level
    child_pad = " " * (level + 1)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f"{child_pad}{json.dumps(str(k))}: {_dumps_matrix_json(v, level + 1)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        items = [f"{child_pad}{_dumps_matrix_json(v, level + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(obj)


def _is_finite_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _check_ci_leaf(
    leaf: Any,
    ctx: str,
    lo_bound: float | None = None,
    hi_bound: float | None = None,
) -> float:
    if not isinstance(leaf, dict) or set(leaf.keys()) != {"mean", "ci95"}:
        raise ValueError(f"{ctx}: invalid CI leaf {leaf!r}")
    mean = leaf["mean"]
    ci = leaf["ci95"]
    if not _is_finite_num(mean) or not isinstance(ci, list) or len(ci) != 2 or not _is_finite_num(ci[0]) or not _is_finite_num(ci[1]):
        raise ValueError(f"{ctx}: non-finite CI values {leaf!r}")
    m_f, lo_f, hi_f = float(mean), float(ci[0]), float(ci[1])
    if lo_f > hi_f + 1e-9:
        raise ValueError(f"{ctx}: ci95 lower > upper in {leaf!r}")
    if lo_bound is not None and (m_f < lo_bound - 1e-9 or lo_f < lo_bound - 1e-9):
        raise ValueError(f"{ctx}: value below bound {lo_bound} in {leaf!r}")
    if hi_bound is not None and (m_f > hi_bound + 1e-9 or hi_f > hi_bound + 1e-9):
        raise ValueError(f"{ctx}: value above bound {hi_bound} in {leaf!r}")
    return m_f


def _parse_seed_range(seed_range: str) -> list[int]:
    if not isinstance(seed_range, str) or not seed_range.strip():
        raise ValueError(f"invalid seed_range: {seed_range!r}")
    seeds: list[int] = []
    for part in seed_range.split(","):
        seg = part.strip()
        if not seg:
            raise ValueError(f"empty segment in seed_range: {seed_range!r}")
        if "-" in seg:
            lo_s, hi_s = seg.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"inverted seed_range segment {seg!r}")
            seeds.extend(range(lo, hi + 1))
        else:
            seeds.append(int(seg))
    return seeds


def validate_matrix_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("matrix payload must be a JSON object")
    if data.get("schema") != "canary.moletrain.frontier_proxy_mole_matrix.v1":
        raise ValueError(f"unexpected schema: {data.get('schema')!r}")
    if data.get("tiers_version") != TIERS_VERSION:
        raise ValueError(f"unexpected tiers_version: {data.get('tiers_version')!r} != {TIERS_VERSION!r}")
    if data.get("tier") not in ("easy", "medium", "hard", "expert"):
        raise ValueError(f"unexpected tier: {data.get('tier')!r}")
    if data.get("agents") != list(AGENTS):
        raise ValueError(f"unexpected agents list: {data.get('agents')!r}")

    boot = data.get("bootstrap")
    if not isinstance(boot, dict) or int(boot.get("resamples", 0)) < 100 or boot.get("ci_level") != 0.95 or boot.get("paired_baseline") != "default":
        raise ValueError(f"invalid bootstrap metadata: {boot!r}")

    rule = data.get("catchability_rule")
    if rule != {"name": "catchable_85", "min_solver_acc": 0.85, "min_solver_score_ratio_vs_default": 0.5}:
        raise ValueError(f"invalid catchability_rule: {rule!r}")

    raw_specs = data.get("policy_specs")
    if not isinstance(raw_specs, list) or not raw_specs:
        raise ValueError("policy_specs must be a non-empty list")
    valid_kinds = {"default", "rl_mole", "rl_mole_v2", "fixed_dsl", "dsl"}
    policy_labels: list[str] = []
    for item in raw_specs:
        if not isinstance(item, dict) or set(item.keys()) != {"label", "kind", "source"}:
            raise ValueError(f"invalid policy_specs entry: {item!r}")
        if item["kind"] not in valid_kinds or not isinstance(item["label"], str) or not item["label"]:
            raise ValueError(f"invalid policy_specs kind/label: {item!r}")
        if item["label"] in policy_labels:
            raise ValueError(f"duplicate policy label: {item['label']!r}")
        policy_labels.append(item["label"])
    if "default" not in policy_labels:
        raise ValueError("policy_specs must include 'default'")

    suites = data.get("suites")
    headline = data.get("headline")
    if not isinstance(suites, dict) or not suites:
        raise ValueError("suites must be a non-empty object")
    if not isinstance(headline, dict) or set(headline.keys()) != set(policy_labels):
        raise ValueError("headline keys must match policy_specs labels")

    base_suites = [(k, v) for k, v in suites.items() if not k.startswith("combined_")]
    combined_suites = [(k, v) for k, v in suites.items() if k.startswith("combined_")]
    if not base_suites:
        raise ValueError("suites must include at least one non-combined suite")

    all_base_seeds: list[int] = []
    for sname, sdata in base_suites:
        if not isinstance(sdata, dict):
            raise ValueError(f"suite {sname} must be an object")
        seeds = _parse_seed_range(sdata.get("seed_range", ""))
        validate_seed_hygiene(seeds)
        if sdata.get("n") != len(seeds):
            raise ValueError(f"suite {sname}: n={sdata.get('n')} != len(seeds)={len(seeds)}")
        all_base_seeds.extend(seeds)
    validate_seed_hygiene(all_base_seeds)

    if len(base_suites) > 1:
        expected_combined = f"combined_{len(all_base_seeds)}"
        if [k for k, _ in combined_suites] != [expected_combined]:
            raise ValueError(f"expected combined suite {[expected_combined]}, got {[k for k, _ in combined_suites]}")
        cdata = suites[expected_combined]
        if cdata.get("n") != len(all_base_seeds) or _parse_seed_range(cdata.get("seed_range", "")) != all_base_seeds:
            raise ValueError(f"combined suite {expected_combined} seed_range/n mismatch")
    elif combined_suites:
        raise ValueError("unexpected combined suite when only one base suite exists")

    for sname, sdata in suites.items():
        pols = sdata.get("policies")
        if not isinstance(pols, dict) or set(pols.keys()) != set(policy_labels):
            raise ValueError(f"suite {sname}: policy keys mismatch")
        def_sol = sdata.get("default_solver_score")
        if not _is_finite_num(def_sol):
            raise ValueError(f"suite {sname}: non-finite default_solver_score")
        def_sol_f = float(def_sol)
        def_entry_sol = _check_ci_leaf(pols["default"]["agents"]["solver"]["score"], f"{sname}.default.solver.score", -1.0, 1.0)
        if abs(def_sol_f - def_entry_sol) > 1e-3:
            raise ValueError(f"suite {sname}: default_solver_score {def_sol_f} != {def_entry_sol}")

        for pol in policy_labels:
            ps = pols[pol]
            ctx = f"{sname}.{pol}"
            ag_map = ps.get("agents")
            if not isinstance(ag_map, dict) or set(ag_map.keys()) != set(AGENTS):
                raise ValueError(f"{ctx}: agents keys mismatch")
            for ag in AGENTS:
                _check_ci_leaf(ag_map[ag].get("score"), f"{ctx}.{ag}.score", -1.0, 1.0)
                _check_ci_leaf(ag_map[ag].get("acc"), f"{ctx}.{ag}.acc", 0.0, 1.0)

            reg_map = ps.get("regret_vs_solver")
            if not isinstance(reg_map, dict) or set(reg_map.keys()) != set(NON_SOLVER_AGENTS):
                raise ValueError(f"{ctx}: regret_vs_solver keys mismatch")
            for ag in NON_SOLVER_AGENTS:
                _check_ci_leaf(reg_map[ag], f"{ctx}.regret.{ag}", -2.0, 2.0)

            gap_m = _check_ci_leaf(ps.get("solver_minus_carbon_proxy"), f"{ctx}.gap", -2.0, 2.0)
            min_reg_m = _check_ci_leaf(ps.get("min_regret"), f"{ctx}.min_regret", -2.0, 2.0)
            _check_ci_leaf(ps.get("scripted_min_regret"), f"{ctx}.scripted_min_regret", -2.0, 2.0)

            pdiff = ps.get("paired_diff_vs_default")
            if not isinstance(pdiff, dict):
                raise ValueError(f"{ctx}: missing paired_diff_vs_default")
            for k_ag in ("agent_score", "agent_acc"):
                if not isinstance(pdiff.get(k_ag), dict) or set(pdiff[k_ag].keys()) != set(AGENTS):
                    raise ValueError(f"{ctx}: invalid paired_diff {k_ag}")
                for ag in AGENTS:
                    m_d = _check_ci_leaf(pdiff[k_ag][ag], f"{ctx}.diff.{k_ag}.{ag}", -2.0, 2.0)
                    if pol == "default" and abs(m_d) > 1e-9:
                        raise ValueError(f"{ctx}: non-zero self diff on {k_ag}.{ag}")
            d_gap = _check_ci_leaf(pdiff.get("solver_minus_carbon_proxy"), f"{ctx}.diff.gap", -4.0, 4.0)
            d_min = _check_ci_leaf(pdiff.get("min_regret"), f"{ctx}.diff.min_regret", -4.0, 4.0)
            _check_ci_leaf(pdiff.get("scripted_min_regret"), f"{ctx}.diff.scripted_min_regret", -4.0, 4.0)
            if pol == "default" and (abs(d_gap) > 1e-9 or abs(d_min) > 1e-9):
                raise ValueError(f"{ctx}: non-zero self diff on gap/min_regret")

            c85 = ps.get("catchable_85")
            c75 = ps.get("catchable_75")
            ratio = ps.get("solver_score_ratio_vs_default")
            if not isinstance(c85, bool) or not isinstance(c75, bool) or not _is_finite_num(ratio):
                raise ValueError(f"{ctx}: invalid catchability fields")
            if c85 and not c75:
                raise ValueError(f"{ctx}: catchable_85=True implies catchable_75=True")

            sol_acc = float(ag_map["solver"]["acc"]["mean"])
            sol_score = float(ag_map["solver"]["score"]["mean"])
            ratio_f = float(ratio)
            if def_sol_f > 0.0:
                if abs(ratio_f - (sol_score / def_sol_f)) > 1e-3:
                    raise ValueError(f"{ctx}: solver_score_ratio_vs_default {ratio_f} mismatch")
                if pol == "default" and abs(ratio_f - 1.0) > 1e-9:
                    raise ValueError(f"{ctx}: default ratio must be 1.0")
            if sol_acc >= 0.85 + 1e-4 and sol_score >= 0.5 * def_sol_f + 1e-4 and not c85:
                raise ValueError(f"{ctx}: expected catchable_85=True for acc={sol_acc}, score={sol_score}")
            if (sol_acc < 0.85 - 1e-4 or sol_score < 0.5 * def_sol_f - 1e-4) and c85:
                raise ValueError(f"{ctx}: expected catchable_85=False for acc={sol_acc}, score={sol_score}")
            if sol_acc >= 0.75 + 1e-4 and sol_score >= 0.5 * def_sol_f + 1e-4 and not c75:
                raise ValueError(f"{ctx}: expected catchable_75=True for acc={sol_acc}, score={sol_score}")
            if (sol_acc < 0.75 - 1e-4 or sol_score < 0.5 * def_sol_f - 1e-4) and c75:
                raise ValueError(f"{ctx}: expected catchable_75=False for acc={sol_acc}, score={sol_score}")
            if pol == "fixed:none/decoy" and c85:
                raise ValueError(f"{ctx}: fixed:none/decoy must fail catchable_85")

            hl_pol = headline.get(pol)
            if not isinstance(hl_pol, dict) or sname not in hl_pol:
                raise ValueError(f"{ctx}: missing headline entry")
            expected_hl = {
                "solver_score": ag_map["solver"]["score"]["mean"],
                "solver_acc": ag_map["solver"]["acc"]["mean"],
                "gemini_carbon_proxy_score": ag_map["gemini_carbon_proxy"]["score"]["mean"],
                "gemini_carbon_proxy_acc": ag_map["gemini_carbon_proxy"]["acc"]["mean"],
                "solver_minus_carbon_proxy": gap_m,
                "min_regret": min_reg_m,
                "delta_gap_vs_default": d_gap,
                "delta_min_regret_vs_default": d_min,
                "catchable_85": c85,
            }
            if hl_pol[sname] != expected_hl:
                raise ValueError(f"{ctx}: headline mismatch with suite summary")

    return {
        "schema": data["schema"],
        "tiers_version": data["tiers_version"],
        "tier": data["tier"],
        "policies": policy_labels,
        "base_suites": [k for k, _ in base_suites],
        "total_unique_seeds": len(all_base_seeds),
    }


def check_matrix_file(path: Path, max_bytes: int = MAX_MATRIX_BYTES) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"matrix file not found: {path}")
    size_bytes = path.stat().st_size
    if size_bytes <= 0 or size_bytes >= max_bytes:
        raise ValueError(f"matrix file size {size_bytes} bytes violates 0 < size < {max_bytes}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    info = validate_matrix_payload(raw)
    return {"ok": True, "path": str(path), "size_bytes": size_bytes, **info}


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="eval_mole_vs_frontier_proxy")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--n-per-suite", type=int, default=30)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--boot-seed", type=int, default=20261114)
    ap.add_argument("--policies", nargs="*", default=None)
    ap.add_argument("--extra-rl", action="append", default=[])
    ap.add_argument("--extra-dsl", action="append", default=[])
    ap.add_argument("--force-fallback-proxy", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    return ap


def collect_policy_specs(args: argparse.Namespace) -> list[MolePolicySpec]:
    base_raw = list(args.policies) if args.policies else list(DEFAULT_POLICY_SPECS)
    specs = [parse_mole_spec(item) for item in base_raw]
    for item in args.extra_rl or []:
        for sub in [x.strip() for x in item.split(",") if x.strip()]:
            specs.append(parse_mole_spec(sub, default_kind="rl_mole"))
    for item in args.extra_dsl or []:
        for sub in [x.strip() for x in item.split(",") if x.strip()]:
            specs.append(parse_mole_spec(sub, default_kind="dsl"))
    seen: set[str] = set()
    deduped: list[MolePolicySpec] = []
    for sp in specs:
        if sp.label not in seen:
            seen.add(sp.label)
            deduped.append(sp)
    return deduped


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    out_path = Path(args.out)
    if args.check:
        try:
            report = check_matrix_file(out_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "path": str(out_path), "error": str(exc)}), file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2))
        return 0

    n = int(args.n_per_suite)
    if n <= 0:
        raise ValueError("n-per-suite must be >= 1")
    suites = [
        (f"{base}-{base + n - 1}", list(range(base, base + n)))
        for _, base in DEFAULT_SUITE_BASES
    ]
    specs = collect_policy_specs(args)
    matrix = evaluate_matrix(
        policy_specs=specs,
        suites=suites,
        tier=args.tier,
        workers=int(args.workers),
        resamples=int(args.resamples),
        boot_seed=int(args.boot_seed),
        force_fallback=bool(args.force_fallback_proxy),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_dumps_matrix_json(matrix) + "\n", encoding="utf-8")
    check_matrix_file(out_path)
    print(json.dumps({"out": str(out_path), "elapsed_s": matrix["elapsed_s"], "headline": matrix["headline"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
