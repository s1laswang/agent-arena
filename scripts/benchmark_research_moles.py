from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.baselines import GrokTactics, Heuristic, _params_from_instruction
from canary.env import Env
from canary.eval import run_episode
from canary.forge.investigators import HintedHeuristic
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.solver.policy import SolverPolicy

H = chr(35)
DEFAULT_LIBRARY_PATH = ROOT / "data" / "forge" / "research_sleeper_moles_v14.json"
EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
MIN_SOLVER_ACC = 0.85
FEASIBLE_SOLVER_RATIO = 0.5
MAX_LIBRARY_BYTES = 15000

EXPECTED_STRATEGY_IDS: tuple[str, ...] = (
    "sleeper_stackelberg_v14",
    "sleeper_override_cover_v16",
    "reciprocity_retaliator_v14",
    "mixed_trap_dodger_v14",
)

INVESTIGATOR_NAMES: tuple[str, ...] = (
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
    "interview_crowded_qre",
)

ALL_AGENT_NAMES: tuple[str, ...] = ("solver",) + INVESTIGATOR_NAMES

EVASIVE_SNIPPETS: tuple[str, ...] = (
    "couldn't tell you",
    "is something missing",
    "don't really keep track",
    "skim most of it",
    "nothing worth mentioning",
    "depends what you count",
    "rather not go through",
    "not like i keep a list",
    "busy. it's fine",
    "same as always",
    "some days are late",
    "talk about this another time",
    "whatever access i need",
    "it set it up",
    "problem with my access",
    "less than i'd like",
    "evasive",
)


def compute_v14_hash() -> str:
    obj = {
        "tiers": {k: v.to_dict() for k, v in rules.TIERS.items()},
        "known_v_mode": rules.KNOWN_V_MODE,
    }
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def load_mole_strategy(strategy_dict: dict[str, Any]) -> MoleStrategy:
    loader = getattr(MoleStrategy, "from_dict", MoleStrategy.from_json)
    strat = loader(strategy_dict)
    roundtrip = loader(strat.to_json())
    if roundtrip != strat:
        raise ValueError(f"MoleStrategy round-trip mismatch for {strat.name}")
    return strat


def qre_horizon_choice(
    post: dict[str, float],
    value_v: float,
    day: int,
    n_days: int,
    rng: random.Random,
    lam_qre: float = 6.0,
) -> str | None:
    ranked = sorted((e for e, p in post.items() if p > 1e-4), key=lambda e: (-post[e], e))
    if not ranked:
        return None
    best = ranked[0]
    pb = post[best]
    if pb >= 0.90 and pb * value_v - (1.0 - pb) > 0.0:
        return best
    horizon_start = max(8, n_days - 7)
    if day < horizon_start:
        return None
    eu_acc = pb * value_v - (1.0 - pb)
    eu_wait = max(0.0, value_v - 0.05 * (n_days - day) * 0.40) * 0.35
    if day >= n_days and eu_acc > -0.15:
        p_stop = 0.95
    else:
        p_stop = 1.0 / (1.0 + math.exp(-lam_qre * (eu_acc - eu_wait + 0.18)))
    if rng.random() >= p_stop:
        return None
    top = ranked[:4]
    weights = [math.exp(lam_qre * post[c]) for c in top]
    return rng.choices(top, weights=weights, k=1)[0]


class InterviewCrowdedQREProxy:
    name = "interview_crowded_qre"
    TOPICS = ("recent_documents", "contacts_outside", "workload", "access_needs")
    DECOY_WORDS = ("raise", "promotion", "deserve")

    def __init__(self, seed: int = 0, lam_qre: float = 6.0):
        self.seed = seed
        self.lam_qre = lam_qre
        self.n_days = 21
        self.k = 3
        self.q = 0.95
        self.rng = random.Random(f"qre_proxy:{seed}")
        self.emps: list[str] = []
        self.docs: dict[str, dict[str, Any]] = {}
        self.feed_seen: set[str] = set()
        self.feed_items: list[dict[str, Any]] = []
        self.after_hours: Counter[str] = Counter()
        self.evasive: Counter[str] = Counter()
        self.decoy_votes: Counter[str] = Counter()
        self.decoy: str | None = None
        self.logs_read_to = 0
        self.V = 1.0
        self.day = 1
        self.started_day = 0
        self.iv_cursor = 0
        self.queue: list[tuple[str, dict[str, Any]]] = []

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        parsed = _params_from_instruction(instruction)
        self.n_days = int(float(parsed.get("n_days", 21)))
        self.k = max(2, min(3, int(float(parsed.get("max_variants", 3)))))
        self.q = float(parsed.get("fingerprint_accuracy", 0.95))
        self.rng = random.Random(f"qre_proxy:{self.seed}")
        self.emps = []
        self.docs = {}
        self.feed_seen = set()
        self.feed_items = []
        self.after_hours = Counter()
        self.evasive = Counter()
        self.decoy_votes = Counter()
        self.decoy = None
        self.logs_read_to = 0
        self.V = 1.0
        self.day = 1
        self.started_day = 0
        self.iv_cursor = 0
        self.queue = []

    def _ingest(self, step: Any) -> None:
        res, tool = step.result, step.tool
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        if tool == "list_employees":
            self.emps = [e["id"] if isinstance(e, dict) else e for e in data.get("employees", [])]
        elif tool == "status":
            self.V = float(data.get("V", self.V))
            self.day = int(data.get("day", self.day))
        elif tool == "list_documents":
            for doc in data.get("documents", []):
                self.docs[doc["doc_id"]] = doc
        elif tool == "check_leak_feed":
            for item in data.get("items", []):
                key = f"{item.get('doc_id')}:{item.get('variant')}"
                if key not in self.feed_seen:
                    self.feed_seen.add(key)
                    self.feed_items.append(item)
        elif tool == "search_messages":
            for msg in data.get("messages", []):
                sender = msg.get("sender")
                if sender:
                    self.decoy_votes[sender] += 1
        elif tool == "read_access_logs":
            for entry in data.get("logs", []):
                emp = entry.get("employee")
                if entry.get("after_hours") and emp:
                    self.after_hours[emp] += 1
        elif tool == "interview":
            ans = str(data.get("answer", "")).lower()
            emp = step.args.get("employee")
            if emp and any(snippet in ans for snippet in EVASIVE_SNIPPETS):
                self.evasive[emp] += 1

    def _posterior(self) -> dict[str, float]:
        logw = {e: 0.0 for e in self.emps}
        alive = set(self.emps)
        for item in self.feed_items:
            doc = self.docs.get(item.get("doc_id"))
            if not doc:
                continue
            if doc.get("is_canary") and item.get("variant") and doc.get("variants"):
                groups = {lab: set(members) for lab, members in doc["variants"].items()}
                k = max(2, len(groups))
                hit = groups.get(item["variant"], set())
                all_c = set().union(*groups.values())
                if alive & all_c:
                    alive &= all_c
                for emp in list(alive):
                    if emp in hit:
                        logw[emp] += math.log(max(1e-6, self.q))
                    elif emp in all_c:
                        logw[emp] += math.log(max(1e-6, (1.0 - self.q) / (k - 1)))
            else:
                rec = set(doc.get("recipients", []))
                if rec and (alive & rec):
                    alive &= rec
        for emp in alive:
            if emp != self.decoy:
                logw[emp] += 0.28 * min(self.after_hours[emp], 10) + 0.18 * self.evasive[emp]
            else:
                logw[emp] -= 1.5
        mx = max((logw[e] for e in alive), default=0.0)
        raw = {e: (math.exp(logw[e] - mx) if e in alive else 0.0) for e in self.emps}
        norm = sum(raw.values()) or 1.0
        return {e: val / norm for e, val in raw.items()}

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        if history:
            self._ingest(history[-1])
            if history[-1].tool == "advance_day" and history[-1].result.get("ok"):
                self.day = history[-1].result["data"].get("day", self.day + 1)
        if not self.emps:
            return "list_employees", {}
        if self.day != self.started_day:
            self.started_day = self.day
            q: list[tuple[str, dict[str, Any]]] = []
            if self.day == 1:
                for word in self.DECOY_WORDS:
                    q.append(("search_messages", {"query": word}))
            q.extend(
                [
                    ("status", {}),
                    ("list_documents", {"day_from": 1, "day_to": self.day}),
                    ("check_leak_feed", {}),
                ]
            )
            if self.day > 1 and self.logs_read_to < self.day - 1:
                q.append(("read_access_logs", {"day_from": self.logs_read_to + 1, "day_to": self.day - 1}))
                self.logs_read_to = self.day - 1
            q.append(("__plan__", {}))
            self.queue = q
        while self.queue:
            tool, args = self.queue.pop(0)
            if tool == "__plan__":
                if self.decoy is None and self.decoy_votes:
                    self.decoy = self.decoy_votes.most_common(1)[0][0]
                post = self._posterior()
                choice = qre_horizon_choice(post, self.V, self.day, self.n_days, self.rng, self.lam_qre)
                if choice is not None:
                    return "accuse", {"employee": choice}
                if self.day >= self.n_days:
                    return "advance_day", {}
                ranked = sorted(
                    (e for e in self.emps if post[e] > 1e-4 and e != self.decoy),
                    key=lambda e: (-post[e], e),
                )
                if not ranked:
                    ranked = sorted(self.emps)
                n_iv = 2 if self.day == 1 else (3 if self.day % 2 == 0 else 4)
                for idx in range(n_iv):
                    emp = ranked[(self.iv_cursor + idx) % len(ranked)]
                    topic = self.TOPICS[(self.day + idx) % len(self.TOPICS)]
                    self.queue.append(("interview", {"employee": emp, "topic": topic}))
                self.iv_cursor += n_iv
                if self.day % 2 == 0 and len(ranked) >= 2:
                    labels = "ABC"[: self.k]
                    cap = ranked[: max(2, min(len(ranked), 15))]
                    asg = {emp: labels[i % len(labels)] for i, emp in enumerate(cap)}
                    self.queue.append(("plant_canary", {"doc_title": f"Audit memo {self.day}", "assignment": asg}))
                continue
            return tool, args
        return "advance_day", {}


def make_agent(agent_name: str, tier: str, seed: int) -> Any:
    if agent_name == "solver":
        return SolverPolicy(tier)
    if agent_name == "grok_tactics":
        return GrokTactics(seed=seed)
    if agent_name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if agent_name == "heuristic":
        return Heuristic(seed=seed)
    if agent_name == "interview_crowded_qre":
        return InterviewCrowdedQREProxy(seed=seed)
    raise ValueError(f"Unknown agent {agent_name!r}")


def _seed_worker(task: tuple[str, int, dict[str, Any], tuple[str, ...]]) -> dict[str, tuple[float, bool]]:
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    tier, seed, strategy_dict, agents = task
    strat = load_mole_strategy(strategy_dict)
    out: dict[str, tuple[float, bool]] = {}
    for agent_name in agents:
        ep = run_episode(Env(tier, seed, mole_strategy=strat), make_agent(agent_name, tier, seed))
        out[agent_name] = (round(float(ep.score), 10), bool(ep.correct))
    return out


def run_strategy_on_seeds(
    strategy_dict: dict[str, Any],
    seeds: list[int],
    tier: str = "hard",
    agents: tuple[str, ...] = ALL_AGENT_NAMES,
    workers: int = 1,
) -> list[dict[str, tuple[float, bool]]]:
    tasks = [(tier, int(s), strategy_dict, agents) for s in seeds]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
            return list(pool.map(_seed_worker, tasks))
    return [_seed_worker(t) for t in tasks]


def paired_bootstrap_ci(values: list[float], n_boot: int = 2000, seed: int = 0) -> list[float]:
    if not values:
        return [0.0, 0.0, 0.0]
    n = len(values)
    mean_val = sum(values) / n
    rng = random.Random(seed)
    boot_means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = boot_means[int(0.025 * n_boot)]
    hi = boot_means[int(0.975 * n_boot)]
    return [round(mean_val, 4), round(lo, 4), round(hi, 4)]


def summarize_rows(
    rows: list[dict[str, tuple[float, bool]]],
    baseline_rows: list[dict[str, tuple[float, bool]]] | None = None,
    min_solver_acc: float = MIN_SOLVER_ACC,
) -> dict[str, Any]:
    solver_scores = [r["solver"][0] for r in rows]
    solver_accs = [1.0 if r["solver"][1] else 0.0 for r in rows]
    solver_score_ci = paired_bootstrap_ci(solver_scores, seed=11)
    solver_acc_ci = paired_bootstrap_ci(solver_accs, seed=17)

    per_inv: dict[str, dict[str, Any]] = {}
    per_seed_mean_regrets: list[float] = []
    for idx in range(len(rows)):
        s_val = rows[idx]["solver"][0]
        per_seed_mean_regrets.append(sum(s_val - rows[idx][ag][0] for ag in INVESTIGATOR_NAMES) / len(INVESTIGATOR_NAMES))

    for offset, ag in enumerate(INVESTIGATOR_NAMES):
        sc = [r[ag][0] for r in rows]
        ac = [1.0 if r[ag][1] else 0.0 for r in rows]
        reg = [s - x for s, x in zip(solver_scores, sc)]
        per_inv[ag] = {
            "score": paired_bootstrap_ci(sc, seed=100 + offset),
            "acc": paired_bootstrap_ci(ac, seed=200 + offset),
            "regret": paired_bootstrap_ci(reg, seed=300 + offset),
        }

    min_regret = round(min(v["regret"][0] for v in per_inv.values()), 4)
    mean_regret_ci = paired_bootstrap_ci(per_seed_mean_regrets, seed=401)
    base_solver_score = (
        sum(r["solver"][0] for r in baseline_rows) / len(baseline_rows)
        if baseline_rows is not None
        else solver_score_ci[0]
    )
    feasible = bool(
        solver_acc_ci[0] >= min_solver_acc
        and solver_score_ci[0] >= FEASIBLE_SOLVER_RATIO * base_solver_score
    )

    out: dict[str, Any] = {
        "n_seeds": len(rows),
        "solver_score": solver_score_ci,
        "solver_acc": solver_acc_ci,
        "min_regret": min_regret,
        "mean_regret": mean_regret_ci,
        "feasible": feasible,
        "per_investigator": per_inv,
    }

    if baseline_rows is not None:
        base_solver_scores = [r["solver"][0] for r in baseline_rows]
        base_solver_accs = [1.0 if r["solver"][1] else 0.0 for r in baseline_rows]
        base_mean_regrets = [
            sum(baseline_rows[i]["solver"][0] - baseline_rows[i][ag][0] for ag in INVESTIGATOR_NAMES)
            / len(INVESTIGATOR_NAMES)
            for i in range(len(baseline_rows))
        ]
        paired_vs_default: dict[str, list[float]] = {
            "solver_score_delta": paired_bootstrap_ci(
                [a - b for a, b in zip(solver_scores, base_solver_scores)], seed=501
            ),
            "solver_acc_delta": paired_bootstrap_ci(
                [a - b for a, b in zip(solver_accs, base_solver_accs)], seed=502
            ),
            "mean_regret_delta": paired_bootstrap_ci(
                [a - b for a, b in zip(per_seed_mean_regrets, base_mean_regrets)], seed=503
            ),
        }
        for offset, ag in enumerate(INVESTIGATOR_NAMES):
            reg_new = [rows[i]["solver"][0] - rows[i][ag][0] for i in range(len(rows))]
            reg_base = [baseline_rows[i]["solver"][0] - baseline_rows[i][ag][0] for i in range(len(baseline_rows))]
            paired_vs_default[f"{ag}_regret_delta"] = paired_bootstrap_ci(
                [a - b for a, b in zip(reg_new, reg_base)], seed=600 + offset
            )
        out["paired_vs_default"] = paired_vs_default

    return out


def load_library(path: Path = DEFAULT_LIBRARY_PATH) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Research mole library must be a JSON object")
    strategies = data.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 4:
        raise ValueError("Research mole library must define exactly 4 strategies")
    ids = tuple(entry.get("id") for entry in strategies)
    if ids != EXPECTED_STRATEGY_IDS:
        raise ValueError(f"Expected strategy ids {EXPECTED_STRATEGY_IDS}, got {ids}")
    for entry in strategies:
        sj = entry.get("strategy_json")
        if not isinstance(sj, dict) or sj.get("name") != entry.get("id"):
            raise ValueError(f"Invalid strategy_json in entry {entry.get('id')!r}")
        load_mole_strategy(sj)
    return data


def export_forge_hof_jsonl(library: dict[str, Any], split: str = "heldout") -> str:
    lines: list[str] = []
    for rank, entry in enumerate(library["strategies"], start=1):
        bench = (entry.get("benchmark_v14_hard") or {}).get(split) or {}
        row = {
            "rank": rank,
            "id": entry["id"],
            "fitness": bench.get("min_regret", 0.0),
            "solver_score": (bench.get("solver_score") or [0.0])[0],
            "solver_acc": (bench.get("solver_acc") or [0.0])[0],
            "strategy_json": entry["strategy_json"],
        }
        lines.append(json.dumps(row, sort_keys=True))
    return "\n".join(lines) + "\n"


def parse_seed_slice(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = (int(x) for x in spec.split(":", 1))
        return list(range(lo, hi))
    if "-" in spec:
        lo, hi = (int(x) for x in spec.split("-", 1))
        return list(range(lo, hi + 1))
    return [int(x) for x in spec.split(",") if x.strip()]


def run_full_benchmark(
    library_path: Path = DEFAULT_LIBRARY_PATH,
    dev_seeds: list[int] | None = None,
    heldout_seeds: list[int] | None = None,
    workers: int = 2,
) -> dict[str, Any]:
    if rules.TIERS_VERSION != EXPECTED_TIERS_VERSION:
        raise RuntimeError(f"Expected TIERS_VERSION={EXPECTED_TIERS_VERSION}, got {rules.TIERS_VERSION}")
    v14_hash = compute_v14_hash()
    if v14_hash != EXPECTED_V14_HASH:
        raise RuntimeError(f"Expected v1.4 hash {EXPECTED_V14_HASH}, got {v14_hash}")

    dev = dev_seeds if dev_seeds is not None else list(range(2000, 2060))
    heldout = heldout_seeds if heldout_seeds is not None else list(range(2100, 2160))
    if set(dev) & set(heldout):
        raise ValueError("dev and heldout seed sets must be strictly disjoint")

    lib = load_library(library_path)
    default_json = DEFAULT_STRATEGY.to_json()

    base_dev_rows = run_strategy_on_seeds(default_json, dev, tier="hard", workers=workers)
    base_held_rows = run_strategy_on_seeds(default_json, heldout, tier="hard", workers=workers)

    lib["tiers_version"] = rules.TIERS_VERSION
    lib["tiers_v14_hash"] = v14_hash
    lib["splits"] = {
        "dev": {"seed_range": f"{dev[0]}-{dev[-1]}", "n_seeds": len(dev)},
        "heldout": {"seed_range": f"{heldout[0]}-{heldout[-1]}", "n_seeds": len(heldout)},
    }
    lib["baseline_default_v0"] = {
        "strategy_json": default_json,
        "benchmark_v14_hard": {
            "dev": summarize_rows(base_dev_rows, baseline_rows=None),
            "heldout": summarize_rows(base_held_rows, baseline_rows=None),
        },
    }

    smoke_records: dict[str, dict[str, dict[str, list[Any]]]] = {}
    smoke_dev_seed = dev[0]
    smoke_held_seed = heldout[0]

    for idx, entry in enumerate(lib["strategies"]):
        sj = entry["strategy_json"]
        dev_rows = run_strategy_on_seeds(sj, dev, tier="hard", workers=workers)
        held_rows = run_strategy_on_seeds(sj, heldout, tier="hard", workers=workers)
        dev_sum = summarize_rows(dev_rows, baseline_rows=base_dev_rows)
        held_sum = summarize_rows(held_rows, baseline_rows=base_held_rows)
        if not dev_sum["feasible"] or not held_sum["feasible"]:
            raise RuntimeError(
                f"Strategy {entry['id']} failed >=85% catchability gate: "
                f"dev={dev_sum['solver_acc'][0]}, heldout={held_sum['solver_acc'][0]}"
            )
        entry["benchmark_v14_hard"] = {
            "dev": dev_sum,
            "heldout": held_sum,
        }
        entry_smoke: dict[str, dict[str, list[Any]]] = {
            str(smoke_dev_seed): {ag: [round(dev_rows[0][ag][0], 6), dev_rows[0][ag][1]] for ag in INVESTIGATOR_NAMES},
        }
        if idx == 0:
            entry_smoke[str(smoke_held_seed)] = {
                "solver": [round(held_rows[0]["solver"][0], 6), held_rows[0]["solver"][1]]
            }
        smoke_records[entry["id"]] = entry_smoke

    lib["smoke_verification"] = smoke_records
    post_hash = compute_v14_hash()
    if post_hash != EXPECTED_V14_HASH:
        raise RuntimeError(f"v1.4 hash mutated during benchmark: {post_hash}")
    return lib


def verify_recorded_library(library_path: Path = DEFAULT_LIBRARY_PATH, run_smoke: bool = True) -> dict[str, Any]:
    raw_bytes = library_path.read_bytes()
    if len(raw_bytes) >= MAX_LIBRARY_BYTES:
        raise ValueError(f"Library exceeds 15 KB cap: {len(raw_bytes)} bytes >= {MAX_LIBRARY_BYTES}")
    lib = load_library(library_path)
    if lib.get("tiers_version") != EXPECTED_TIERS_VERSION:
        raise ValueError(f"Unexpected tiers_version {lib.get('tiers_version')!r}")
    if lib.get("tiers_v14_hash") != EXPECTED_V14_HASH or compute_v14_hash() != EXPECTED_V14_HASH:
        raise ValueError("v1.4 frozen hash mismatch")

    splits = lib.get("splits") or {}
    dev_seeds = parse_seed_slice(splits["dev"]["seed_range"])
    held_seeds = parse_seed_slice(splits["heldout"]["seed_range"])
    if len(dev_seeds) != 60 or len(held_seeds) != 60 or (set(dev_seeds) & set(held_seeds)):
        raise ValueError("Expected disjoint n=60 dev and n=60 heldout seed ranges")

    base_bench = (lib.get("baseline_default_v0") or {}).get("benchmark_v14_hard") or {}
    for split_key in ("dev", "heldout"):
        b_split = base_bench.get(split_key) or {}
        if b_split.get("n_seeds") != 60 or not b_split.get("feasible"):
            raise ValueError(f"Baseline default_v0 invalid on {split_key}")

    for entry in lib["strategies"]:
        bench = entry.get("benchmark_v14_hard") or {}
        for split_key in ("dev", "heldout"):
            sp = bench.get(split_key) or {}
            b_sp = base_bench[split_key]
            if sp.get("n_seeds") != 60:
                raise ValueError(f"{entry['id']} {split_key} n_seeds != 60")
            if not sp.get("feasible"):
                raise ValueError(f"{entry['id']} {split_key} feasible is False")
            if sp["solver_acc"][0] < MIN_SOLVER_ACC:
                raise ValueError(f"{entry['id']} {split_key} solver_acc {sp['solver_acc'][0]} < {MIN_SOLVER_ACC}")
            if sp["solver_score"][0] < FEASIBLE_SOLVER_RATIO * b_sp["solver_score"][0]:
                raise ValueError(f"{entry['id']} {split_key} solver_score ratio violation")

    if run_smoke:
        smoke = lib.get("smoke_verification") or {}
        s_dev = str(dev_seeds[0])
        for entry in lib["strategies"]:
            sid = entry["id"]
            non_solver = INVESTIGATOR_NAMES
            row_dev = run_strategy_on_seeds(entry["strategy_json"], [dev_seeds[0]], tier="hard", agents=non_solver, workers=1)[0]
            for ag in non_solver:
                exp_sc, exp_ok = smoke[sid][s_dev][ag]
                if abs(row_dev[ag][0] - exp_sc) > 1e-5 or bool(row_dev[ag][1]) != bool(exp_ok):
                    raise ValueError(f"Smoke parity mismatch on {sid} seed {s_dev} agent {ag}")
        first_strat = lib["strategies"][0]
        sol_row = run_strategy_on_seeds(first_strat["strategy_json"], [held_seeds[0]], tier="hard", agents=("solver",), workers=1)[0]
        exp_sol_sc, exp_sol_ok = smoke[first_strat["id"]][str(held_seeds[0])]["solver"]
        if abs(sol_row["solver"][0] - exp_sol_sc) > 1e-5 or bool(sol_row["solver"][1]) != bool(exp_sol_ok):
            raise ValueError("Solver smoke parity mismatch")

    if compute_v14_hash() != EXPECTED_V14_HASH:
        raise ValueError("v1.4 hash changed after smoke verification")
    return {"ok": True, "bytes": len(raw_bytes), "strategies": [e["id"] for e in lib["strategies"]]}


def format_markdown_summary(lib: dict[str, Any]) -> str:
    lines: list[str] = []
    for split_key, label in (("dev", "Dev (2000-2059, n=60)"), ("heldout", "Held-Out (2100-2159, n=60)")):
        lines.append(f"{H}{H}{H} {label}")
        lines.append("")
        lines.append(
            "| Strategy | Solver Score [95% CI] | Solver Acc [95% CI] | Grok Score | Hinted Score | Heuristic Score | QRE Proxy Score | min_regret | mean_regret [95% CI] |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        all_rows = [("default_v0", lib["baseline_default_v0"]["benchmark_v14_hard"][split_key])]
        for entry in lib["strategies"]:
            all_rows.append((entry["id"], entry["benchmark_v14_hard"][split_key]))
        for name, sp in all_rows:
            ss = sp["solver_score"]
            sa = sp["solver_acc"]
            mr = sp["mean_regret"]
            pi = sp["per_investigator"]
            lines.append(
                f"| `{name}` | `{ss[0]:.4f} [{ss[1]:.4f}, {ss[2]:.4f}]` | "
                f"`{sa[0]*100:.1f}% [{sa[1]*100:.1f}%, {sa[2]*100:.1f}%]` | "
                f"`{pi['grok_tactics']['score'][0]:.4f}` | "
                f"`{pi['hinted_heuristic']['score'][0]:.4f}` | "
                f"`{pi['heuristic']['score'][0]:.4f}` | "
                f"`{pi['interview_crowded_qre']['score'][0]:.4f}` | "
                f"`{sp['min_regret']:+.4f}` | "
                f"`{mr[0]:+.4f} [{mr[1]:+.4f}, {mr[2]:+.4f}]` |"
            )
        lines.append("")
    return "\n".join(lines)


def _inline_scalar_lists(raw_json: str) -> str:
    return re.sub(
        r"\[\n\s+([^\[\]\{\}]+?)\n\s*\]",
        lambda m: "[" + ", ".join(part.strip() for part in m.group(1).split(",")) + "]",
        raw_json,
    )


def write_compact_library(lib: dict[str, Any], out_path: Path) -> int:
    text = _inline_scalar_lists(json.dumps(lib, indent=1, ensure_ascii=True)) + "\n"
    if len(text.encode("utf-8")) >= MAX_LIBRARY_BYTES:
        text = json.dumps(lib, separators=(",", ":"), ensure_ascii=True) + "\n"
    size_bytes = len(text.encode("utf-8"))
    if size_bytes >= MAX_LIBRARY_BYTES:
        raise ValueError(f"Serialized library {size_bytes} bytes >= {MAX_LIBRARY_BYTES} limit")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return size_bytes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark and verify the research-grounded Canary v1.4 mole library.")
    ap.add_argument("--library", type=Path, default=DEFAULT_LIBRARY_PATH)
    ap.add_argument("--dev-seeds", type=str, default="2000:2060")
    ap.add_argument("--heldout-seeds", type=str, default="2100:2160")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--write-library", action="store_true")
    ap.add_argument("--verify-recorded", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    if args.verify_recorded:
        summary = verify_recorded_library(args.library, run_smoke=True)
        summary["elapsed_s"] = round(time.monotonic() - t0, 3)
        print(json.dumps(summary, indent=2))
        return 0

    dev_seeds = parse_seed_slice(args.dev_seeds)
    heldout_seeds = parse_seed_slice(args.heldout_seeds)
    lib = run_full_benchmark(args.library, dev_seeds=dev_seeds, heldout_seeds=heldout_seeds, workers=args.workers)
    if args.write_library:
        written_bytes = write_compact_library(lib, args.library)
        print(f"Wrote {args.library} ({written_bytes} bytes < {MAX_LIBRARY_BYTES})", file=sys.stderr)
    if args.markdown:
        print(format_markdown_summary(lib))
    else:
        print(json.dumps(lib, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
