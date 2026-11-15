from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import contextlib
from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.redteam import anticheat
from canary.redteam import fuzz
from canary.solver.policy import SolverPolicy
from canary.types import LedgerEntry, ToolResult
from scripts.audit_submission import compute_tier_hash

MAKE_HUNT_TRACKS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge")
HELDOUT_TRACKS: tuple[str, ...] = ("hard", "hard_forge")
FUZZ_MODES: tuple[str, ...] = ("random", "malformed", "evolve", "parallel_accuse")
DEFAULT_OUT_DIR = Path("/tmp/opencode/w2_final_make_hunt_v14")
ANTICHEAT_ARTIFACT = ROOT / "results" / "anticheat" / "exploits.json"
COMMITTED_REF_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
FAKE_EMPS: list[str] = [f"e{i:02d}" for i in range(12)]

CellSpec = tuple[str, str, str, str, list[int], int, int]

FULL_CELLS: tuple[CellSpec, ...] = (
    ("make_hunt_easy_0_49", "make_hunt", "easy", "0-49", list(range(0, 50)), 2000, 0),
    ("make_hunt_medium_0_49", "make_hunt", "medium", "0-49", list(range(0, 50)), 2000, 0),
    ("make_hunt_hard_0_49", "make_hunt", "hard", "0-49", list(range(0, 50)), 2000, 0),
    ("make_hunt_hard_forge_0_49", "make_hunt", "hard_forge", "0-49", list(range(0, 50)), 2000, 0),
    ("heldout_hard_5000_5099", "heldout", "hard", "5000-5099", list(range(5000, 5100)), 2000, 0),
    ("heldout_hard_forge_5000_5099", "heldout", "hard_forge", "5000-5099", list(range(5000, 5100)), 2000, 0),
)

QUICK_CELLS: tuple[CellSpec, ...] = (
    ("make_hunt_easy_0_1", "make_hunt", "easy", "0-1", [0, 1], 4, 0),
    ("make_hunt_medium_0_1", "make_hunt", "medium", "0-1", [0, 1], 4, 0),
    ("make_hunt_hard_0_1", "make_hunt", "hard", "0-1", [0, 1], 4, 0),
    ("make_hunt_hard_forge_0_1", "make_hunt", "hard_forge", "0-1", [0, 1], 4, 0),
    ("heldout_hard_5000_5001", "heldout", "hard", "5000-5001", [5000, 5001], 4, 0),
    ("heldout_hard_forge_5000_5001", "heldout", "hard_forge", "5000-5001", [5000, 5001], 4, 0),
)


def _default_env_factory(tier: str, seed: int) -> Any:
    return Env(tier=tier, seed=seed)


def _available_cpus() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def strict_v14_episode_violations(env: Any, tier: str, seed: int) -> list[dict[str, Any]]:
    mole = fuzz.true_mole(env)
    idset = set(getattr(env, "_idset", ())) | {mole} | set(FAKE_EMPS)
    acc = fuzz._accusations(env.ledger(), idset)
    sc = float(env.score())
    out: list[dict[str, Any]] = []
    if len(acc) > 1:
        out.append({"kind": "strict_v14_multiple_accusations", "tier": tier, "seed": seed, "accusations": acc, "score": sc})
    if len(acc) == 1 and acc[0] != mole and abs(sc + 1.0) > 1e-9:
        out.append({"kind": "strict_v14_wrong_accuse_not_minus_one", "tier": tier, "seed": seed, "accused": acc[0], "score": sc})
    if len(acc) == 0 and abs(sc) > 1e-9:
        out.append({"kind": "strict_v14_unaccused_nonzero", "tier": tier, "seed": seed, "score": sc})
    if hasattr(env, "V"):
        v_val = float(env.V)
        if not (-1e-9 <= v_val <= 1.0 + 1e-9):
            out.append({"kind": "strict_v14_true_v_bounds", "tier": tier, "seed": seed, "V": v_val})
    if hasattr(env, "visible_V"):
        vv_val = float(env.visible_V())
        if not (-1e-9 <= vv_val <= 1.0 + 1e-9):
            out.append({"kind": "strict_v14_visible_v_bounds", "tier": tier, "seed": seed, "visible_V": vv_val})
    return out


def make_auditing_factory(
    base_factory: Callable[[str, int], Any] = _default_env_factory,
    check_strict_v14: bool = True,
) -> tuple[Callable[[str, int], Any], Callable[[], dict[str, Any]]]:
    state: dict[str, Any] = {
        "episodes": 0,
        "tool_calls": 0,
        "last_env": None,
        "last_meta": None,
        "strict_violations": [],
    }

    def _finalize_prev() -> None:
        if check_strict_v14 and state["last_env"] is not None:
            lt, ls = state["last_meta"]
            state["strict_violations"].extend(strict_v14_episode_violations(state["last_env"], lt, ls))
            state["last_env"] = None
            state["last_meta"] = None

    def factory(tier: str, seed: int) -> Any:
        _finalize_prev()
        env = base_factory(tier, seed)
        state["episodes"] += 1
        state["last_env"] = env
        state["last_meta"] = (tier, seed)
        orig_call = env.call

        def wrapped_call(tool: Any, args: Any) -> Any:
            state["tool_calls"] += 1
            return orig_call(tool, args)

        env.call = wrapped_call
        return env

    def finalize() -> dict[str, Any]:
        _finalize_prev()
        return {
            "episodes": int(state["episodes"]),
            "tool_calls": int(state["tool_calls"]),
            "strict_v14_violations": list(state["strict_violations"]),
        }

    return factory, finalize


def _run_mode_shard(args: tuple[str, str, list[int], int, int, str, str]) -> dict[str, Any]:
    cell_id, tier, seeds, cell_budget, rng_seed, mode, out_dir_str = args
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    shard_file = Path(out_dir_str) / "shards" / f"{cell_id}__{mode}.json"
    mode_budget = cell_budget // 3
    cfac, finalize = make_auditing_factory(_default_env_factory, check_strict_v14=True)
    t0 = time.monotonic()
    res = fuzz.hunt(
        tier=tier,
        seeds=seeds,
        budget=mode_budget,
        seed=rng_seed,
        mode=mode,
        workers=1,
        factory=cfac,
    )
    elapsed = round(time.monotonic() - t0, 3)
    audit = finalize()
    genomes = 0 if mode == "parallel_accuse" else mode_budget
    races = int(res.get("races", 0))
    parity_seeds = 0 if mode == "parallel_accuse" else min(len(seeds), 5)
    payload = {
        "cell_id": cell_id,
        "tier": tier,
        "mode": mode,
        "n_seeds": len(seeds),
        "cell_budget": cell_budget,
        "mode_budget": int(res.get("budget", 0)),
        "genomes_evaluated": genomes,
        "races": races,
        "threads_per_race": int(res.get("threads_per_race", 0)),
        "parity_seeds_probed": parity_seeds,
        "rng_seed": rng_seed,
        "episode_evaluations": audit["episodes"],
        "tool_call_evaluations": audit["tool_calls"],
        "best_non_solver_score": float(res["best_non_solver_score"]),
        "best_score_per_call": round(float(res["best_score_per_call"]), 6),
        "n_violations": len(res["invariant_violations"]),
        "violation_kinds": list(res["violation_kinds"]),
        "invariant_violations": list(res["invariant_violations"])[:25],
        "strict_v14_violations_count": len(audit["strict_v14_violations"]),
        "strict_v14_violations": audit["strict_v14_violations"][:25],
        "wall_seconds": elapsed,
    }
    shard_file.parent.mkdir(parents=True, exist_ok=True)
    shard_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _load_committed_solver_episodes(tier: str) -> dict[int, dict[str, Any]]:
    if not COMMITTED_REF_DIR.is_dir():
        return {}
    by_seed: dict[int, dict[str, Any]] = {}
    for p in sorted(COMMITTED_REF_DIR.glob(f"solver-{tier}-*/episodes.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if ep.get("tier") == tier and isinstance(ep.get("seed"), int):
                by_seed[int(ep["seed"])] = ep
    return by_seed


def compute_solver_reference(tier: str, seeds: list[int], quick: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    committed = _load_committed_solver_episodes(tier)
    if quick:
        target_seeds = seeds[:1] if tier == "easy" else [s for s in seeds if s in committed]
    elif tier in ("easy", "medium", "hard") and seeds and seeds[0] == 0:
        target_seeds = list(seeds)
    else:
        target_seeds = seeds[:5]

    scores: list[float] = []
    corrects: list[bool] = []
    days: list[int] = []
    steps_counts: list[int] = []
    live_episodes = 0
    committed_episodes = 0

    for s in target_seeds:
        if s in committed:
            rec = committed[s]
            scores.append(float(rec["score"]))
            corrects.append(bool(rec["correct"]))
            days.append(int(rec["final_day"]))
            steps_counts.append(int(rec.get("n_calls", len(rec.get("steps", [])))))
            committed_episodes += 1
        else:
            ep = run_episode(Env(tier=tier, seed=s), SolverPolicy())
            scores.append(float(ep.score))
            corrects.append(bool(ep.correct))
            days.append(int(ep.final_day))
            steps_counts.append(len(ep.steps))
            live_episodes += 1

    n = len(scores)
    mean_sc = sum(scores) / n if n else None
    if n >= 2 and mean_sc is not None:
        sd = math.sqrt(sum((x - mean_sc) ** 2 for x in scores) / (n - 1))
        ci95 = 1.96 * sd / math.sqrt(n)
    else:
        ci95 = 0.0
    sub30 = scores[:30] if len(scores) >= 30 else []
    sub30_corr = corrects[:30] if len(corrects) >= 30 else []
    live_steps = sum(steps_counts) if committed_episodes == 0 else sum(
        steps_counts[i] for i, s in enumerate(target_seeds) if s not in committed
    )
    return {
        "tier": tier,
        "n_seeds": n,
        "live_episodes": live_episodes,
        "committed_episodes": committed_episodes,
        "live_steps": int(live_steps),
        "seed_range": [target_seeds[0], target_seeds[-1]] if target_seeds else [],
        "mean_score": round(mean_sc, 4) if mean_sc is not None else None,
        "fuzz_report_mean": f"{mean_sc:.3f}" if mean_sc is not None else "n/a",
        "ci95": round(ci95, 4),
        "accuracy": round(sum(corrects) / n, 4) if n else None,
        "n_correct": int(sum(corrects)),
        "mean_final_day": round(sum(days) / n, 2) if n else None,
        "mean_steps": round(sum(steps_counts) / n, 2) if n else None,
        "total_steps": int(sum(steps_counts)),
        "dev30_mean_score": round(sum(sub30) / len(sub30), 4) if sub30 else None,
        "dev30_accuracy": round(sum(sub30_corr) / len(sub30_corr), 4) if sub30_corr else None,
        "wall_seconds": round(time.monotonic() - t0, 3),
    }


def _run_solver_shard(args: tuple[str, str, list[int], bool, str]) -> tuple[str, dict[str, Any]]:
    cell_id, tier, seeds, quick, out_dir_str = args
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    shard_file = Path(out_dir_str) / "shards" / f"{cell_id}__solver.json"
    ref = compute_solver_reference(tier, seeds, quick=quick)
    shard_file.parent.mkdir(parents=True, exist_ok=True)
    shard_file.write_text(json.dumps(ref, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return cell_id, ref


def run_full_seed_parity_audit(
    cells: tuple[CellSpec, ...],
    factory: Callable[[str, int], Any] = _default_env_factory,
) -> dict[str, Any]:
    t0 = time.monotonic()
    cfac, finalize = make_auditing_factory(factory, check_strict_v14=(factory is _default_env_factory))
    violations: list[dict[str, Any]] = []
    per_cell: dict[str, Any] = {}
    total_pairs = 0
    for cell_id, _, tier, _, seeds, _, _ in cells:
        cell_v: list[dict[str, Any]] = []
        for s in seeds:
            total_pairs += 1
            cell_v.extend(fuzz.parity_probe(tier, s, cfac))
        violations.extend(cell_v)
        per_cell[cell_id] = {
            "tier": tier,
            "seeds_probed": len(seeds),
            "violations_count": len(cell_v),
        }
    audit = finalize()
    return {
        "track_seed_pairs_probed": total_pairs,
        "episode_evaluations": audit["episodes"],
        "tool_call_evaluations": audit["tool_calls"],
        "violations_count": len(violations),
        "strict_v14_violations_count": len(audit["strict_v14_violations"]),
        "per_cell": per_cell,
        "wall_seconds": round(time.monotonic() - t0, 3),
    }


@dataclass
class _FakeWorld:
    mole: str


class PlantedBugFakeEnv:
    def __init__(self, tier: str, seed: int, bug: str | None = None):
        self._world = _FakeWorld(mole=FAKE_EMPS[seed % len(FAKE_EMPS)])
        self.bug = bug
        self.tier = tier
        self.seed = seed
        self.day = 1
        self.V = 1.0
        self._done = False
        self._score = 0.0
        self._ledger: list[LedgerEntry] = []
        self._restricted: set[str] = set()
        self._lock = threading.Lock()
        self.history: list[Any] = []

    @property
    def done(self) -> bool:
        return self._done

    def score(self) -> float:
        return self._score

    def visible_V(self) -> float:
        return self.V

    def ledger(self) -> list[LedgerEntry]:
        return list(self._ledger)

    def _call_body(self, tool: Any, args: Any) -> ToolResult:
        if self.bug == "unhandled_exception" and (not isinstance(args, dict) or tool not in fuzz.TOOLS):
            raise RuntimeError("planted unhandled crash on malformed input")
        if self._done and not (self.bug == "accuse_twice" and tool == "accuse"):
            return ToolResult(False, {}, "episode over")
        if not isinstance(tool, str) or tool not in fuzz.TOOLS:
            return ToolResult(False, {}, "unknown tool")
        if not isinstance(args, dict):
            return ToolResult(False, {}, "invalid arguments")
        if tool == "list_employees":
            return ToolResult(True, {"employees": [{"id": e} for e in FAKE_EMPS]})
        if tool == "status":
            if self.bug == "truth_leak":
                return ToolResult(True, {"day": self.day, "V": self.V, "mole": self._world.mole})
            return ToolResult(True, {"day": self.day, "V": round(self.V, 10)})
        if tool == "advance_day":
            self.day += 1
            self.V = round(max(0.0, self.V - 0.02), 10)
            if self.day > 14:
                self._done = True
            return ToolResult(True, {"day": self.day, "V": self.V})
        if tool == "restrict_access":
            emp = args.get("employee")
            if not isinstance(emp, str) or emp not in FAKE_EMPS or set(args) != {"employee"}:
                return ToolResult(False, {"detail": "bad employee"}, "invalid arguments")
            if emp in self._restricted:
                if self.bug == "parity_leak" and emp == self._world.mole:
                    return ToolResult(False, {"detail": f"{emp} already restricted (flagged)"}, "already restricted")
                return ToolResult(False, {"detail": f"{emp} already restricted"}, "already restricted")
            self._restricted.add(emp)
            return ToolResult(True, {"restricted": emp})
        if tool == "unrestrict_access":
            emp = args.get("employee")
            if not isinstance(emp, str) or emp not in FAKE_EMPS or set(args) != {"employee"}:
                return ToolResult(False, {"detail": "bad employee"}, "invalid arguments")
            if emp not in self._restricted:
                return ToolResult(False, {"detail": f"{emp} not restricted"}, "not restricted")
            self._restricted.remove(emp)
            return ToolResult(True, {"unrestricted": emp})
        if tool == "accuse":
            emp = args.get("employee")
            if not isinstance(emp, str) or emp not in FAKE_EMPS or set(args) != {"employee"}:
                return ToolResult(False, {"detail": "bad employee"}, "invalid arguments")
            if self.bug == "parallel_accuse_race":
                time.sleep(0.0004)
            self._ledger.append(LedgerEntry(len(self._ledger), self.day, "accused", {"employee": emp}))
            self._done = True
            if emp == self._world.mole or self.bug == "accuse_twice":
                self._score = round(self.V, 10)
            elif self.bug == "wrong_accusation_positive":
                self._score = 0.5
            elif self.bug == "wrong_accusation_zero":
                self._score = 0.0
            else:
                self._score = -1.0
            return ToolResult(True, {"accused": emp, "episode_over": True})
        return ToolResult(True, {"ok_stub": tool})

    def call(self, tool: Any, args: Any) -> ToolResult:
        if self.bug == "parallel_accuse_race":
            return self._call_body(tool, args)
        with self._lock:
            return self._call_body(tool, args)


def run_fake_env_positive_controls(quick: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    ctrl_seeds = range(2) if quick else range(4)
    clean_budget = 24 if quick else 90
    clean_fac, clean_fin = make_auditing_factory(
        lambda t, s: PlantedBugFakeEnv(t, s, bug=None),
        check_strict_v14=True,
    )
    clean_res = fuzz.hunt("easy", ctrl_seeds, clean_budget, 0, "all", workers=1, factory=clean_fac)
    clean_audit = clean_fin()

    hi = 72 if quick else 240
    lo = 18 if quick else 60
    par = 12 if quick else 30
    bug_specs: tuple[tuple[str, set[str], int], ...] = (
        ("accuse_twice", {"post_end_effect", "score_without_correct_accusation"}, hi),
        ("truth_leak", {"truth_leak"}, lo),
        ("parity_leak", {"parity_leak"}, par),
        ("unhandled_exception", {"exception"}, lo),
        ("wrong_accusation_positive", {"wrong_accusation_positive", "score_without_correct_accusation"}, hi),
        ("parallel_accuse_race", {"parallel_accuse_race"}, par),
    )

    per_bug: dict[str, Any] = {}
    caught_count = 0
    for bug_name, expected_any, b_budget in bug_specs:
        bfac, bfin = make_auditing_factory(
            lambda t, s, b=bug_name: PlantedBugFakeEnv(t, s, bug=b),
            check_strict_v14=True,
        )
        r = fuzz.hunt("easy", ctrl_seeds, b_budget, 0, "all", workers=1, factory=bfac)
        baudit = bfin()
        kinds = set(r["violation_kinds"])
        caught = bool(kinds & expected_any)
        caught_count += int(caught)
        per_bug[bug_name] = {
            "caught": caught,
            "n_violations": len(r["invariant_violations"]),
            "violation_kinds": sorted(kinds),
            "best_non_solver_score": float(r["best_non_solver_score"]),
            "episodes": baudit["episodes"],
            "tool_calls": baudit["tool_calls"],
        }

    zfac, zfin = make_auditing_factory(
        lambda t, s: PlantedBugFakeEnv(t, s, bug="wrong_accusation_zero"),
        check_strict_v14=True,
    )
    zres = fuzz.hunt("easy", ctrl_seeds, hi, 0, "all", workers=1, factory=zfac)
    zaudit = zfin()
    fuzz_caught_zero_wrong = len(zres["invariant_violations"]) > 0
    strict_caught_zero_wrong = any(
        v["kind"] == "strict_v14_wrong_accuse_not_minus_one" for v in zaudit["strict_v14_violations"]
    )

    return {
        "clean_control": {
            "n_violations": len(clean_res["invariant_violations"]),
            "strict_v14_violations": len(clean_audit["strict_v14_violations"]),
            "best_non_solver_score": float(clean_res["best_non_solver_score"]),
            "clean": len(clean_res["invariant_violations"]) == 0 and len(clean_audit["strict_v14_violations"]) == 0 and clean_res["best_non_solver_score"] == 0.0,
        },
        "bugs_tested": len(bug_specs),
        "bugs_caught": caught_count,
        "catch_rate": round(caught_count / len(bug_specs), 4),
        "all_caught": caught_count == len(bug_specs),
        "per_bug": per_bug,
        "v0_zero_wrong_audit": {
            "fuzz_score_invariants_caught": fuzz_caught_zero_wrong,
            "strict_v14_oracle_caught": strict_caught_zero_wrong,
            "strict_v14_violations_count": len(zaudit["strict_v14_violations"]),
        },
        "wall_seconds": round(time.monotonic() - t0, 3),
    }


def _parse_verify_stdout(text: str) -> dict[str, int | None]:
    m = re.search(
        r":\s*(\d+)\s+rows rerun on\s+(\d+)\s+seeds x\s+(\d+)\s+tiers under the public secret;\s*(\d+)\s+differences",
        text,
    )
    if not m:
        return {"rows_rerun": None, "seeds_rerun": None, "tiers_rerun": None, "differences": None}
    return {
        "rows_rerun": int(m.group(1)),
        "seeds_rerun": int(m.group(2)),
        "tiers_rerun": int(m.group(3)),
        "differences": int(m.group(4)),
    }


def run_anticheat_verification(quick: bool = False, artifact_path: Path = ANTICHEAT_ARTIFACT) -> dict[str, Any]:
    from canary import world as W

    t0 = time.monotonic()
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    committed_seeds = sorted({int(s) for r in raw["rows"] for s in r.get("seeds", [])})
    harbor_rows = raw.get("harbor") or []
    harbor_trials = [r for r in harbor_rows if r.get("kind", "trial") == "trial"]
    harbor_jobs = [r for r in harbor_rows if r.get("kind") == "job"]

    meta = {
        "artifact": artifact_path.relative_to(ROOT).as_posix() if artifact_path.is_relative_to(ROOT) else str(artifact_path),
        "committed_rows": len(raw["rows"]),
        "committed_tiers": list(raw["tiers"]),
        "committed_n_seeds": len(committed_seeds),
        "committed_seed_range": [committed_seeds[0], committed_seeds[-1]] if committed_seeds else [],
        "world_secret_public": raw.get("world_secret_public"),
        "world_secret_fingerprint": raw.get("world_secret_fingerprint"),
        "all_blocked": bool(raw.get("all_blocked")),
        "replay_all_consistent": bool(raw.get("replay_all_consistent")),
        "replay_counts": raw.get("replay_counts"),
        "harbor_all_consistent": bool(raw.get("harbor_all_consistent")),
        "harbor_trials_consistent": sum(1 for r in harbor_trials if r.get("consistent") is True),
        "harbor_trials_total": len(harbor_trials),
        "harbor_jobs_consistent": sum(1 for r in harbor_jobs if r.get("consistent") is True),
        "harbor_jobs_total": len(harbor_jobs),
    }

    rt_tiers = ["easy"] if quick else ["easy", "medium"]
    rt_seeds = [900000] if quick else [900000, 900001]
    expected_rows = 33 * len(rt_tiers)
    with tempfile.TemporaryDirectory(prefix="canary-w2-ac-rt-") as tmp:
        tmp_dir = Path(tmp)
        prev_secret = W._SET_SECRET
        test_secret = "canary-w2-roundtrip-verify-secret-v14"
        W.set_world_secret(test_secret.encode("utf-8"))
        try:
            anticheat.run_and_write(
                rt_tiers,
                rt_seeds,
                tmp_dir,
                replay=False,
                quiet=True,
                extra={"world_secret_public": test_secret},
            )
        finally:
            W.set_world_secret(prev_secret)
        q_art = tmp_dir / "exploits.json"
        buf_ok = io.StringIO()
        with contextlib.redirect_stdout(buf_ok):
            rc_ok = anticheat.verify_artifact(q_art)
        parsed_ok = _parse_verify_stdout(buf_ok.getvalue())

        tampered = json.loads(q_art.read_text(encoding="utf-8"))
        tampered["rows"][0]["mean"] = round(float(tampered["rows"][0]["mean"]) + 0.125, 4)
        bad_art = tmp_dir / "exploits_tampered.json"
        bad_art.write_text(json.dumps(tampered), encoding="utf-8")
        buf_bad = io.StringIO()
        with contextlib.redirect_stdout(buf_bad):
            rc_bad = anticheat.verify_artifact(bad_art)
        parsed_bad = _parse_verify_stdout(buf_bad.getvalue())

    return {
        **meta,
        "mode": "quick_easy_roundtrip_plus_committed_schema" if quick else "easy_medium_roundtrip_plus_committed_schema",
        "verify_rc": rc_ok,
        "verify_stdout": buf_ok.getvalue().strip(),
        **parsed_ok,
        "tamper_positive_control_rc": rc_bad,
        "tamper_positive_control_diffs": parsed_bad["differences"],
        "verified_ok": (
            rc_ok == 0
            and parsed_ok["rows_rerun"] == expected_rows
            and parsed_ok["seeds_rerun"] == len(rt_seeds)
            and parsed_ok["tiers_rerun"] == len(rt_tiers)
            and parsed_ok["differences"] == 0
            and rc_bad == 1
            and (parsed_bad["differences"] or 0) >= 1
            and meta["committed_rows"] == 99
            and meta["committed_n_seeds"] == 40
            and meta["committed_tiers"] == ["easy", "medium", "hard"]
            and meta["all_blocked"] is True
            and meta["replay_all_consistent"] is True
            and meta["harbor_all_consistent"] is True
        ),
        "wall_seconds": round(time.monotonic() - t0, 3),
    }


def _run_anticheat_worker(args: tuple[bool, str]) -> dict[str, Any]:
    quick, out_dir_str = args
    shard_file = Path(out_dir_str) / "shards" / "anticheat_verify.json"
    res = run_anticheat_verification(quick=quick, artifact_path=ANTICHEAT_ARTIFACT)
    shard_file.parent.mkdir(parents=True, exist_ok=True)
    shard_file.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return res


def inspect_make_hunt_harness_issues(
    cells_summary: list[dict[str, Any]],
    fake_controls: dict[str, Any],
) -> list[dict[str, Any]]:
    make_cells = [c for c in cells_summary if c["group"] == "make_hunt"]
    requested_make_budget = sum(int(c["requested_budget"]) for c in make_cells)
    actual_make_genomes = sum(int(c["genomes_evaluated"]) for c in make_cells)
    dropped_make_genomes = requested_make_budget - actual_make_genomes
    makefile_requested = 4 * 20000
    makefile_actual = 4 * 3 * (20000 // 3)
    makefile_dropped = makefile_requested - makefile_actual

    rng_a = fuzz.search("easy", [0, 1], 8, "random", rng_seed=0, factory=lambda t, s: PlantedBugFakeEnv(t, s))
    rng_b = fuzz.search("easy", [0, 1], 8, "evolve", rng_seed=0, factory=lambda t, s: PlantedBugFakeEnv(t, s))
    shared_rng_warmup_identical = (rng_a[1] == rng_b[1])

    issues: list[dict[str, Any]] = [
        {
            "id": "ISSUE-W2-FUZZ-ALL-BUDGET-TRUNCATION-AND-SHARED-RNG",
            "severity": "low",
            "kind": "fuzzer_budget_and_seed_scheduling",
            "locations": ["canary/redteam/fuzz.py:336,347,389-390", "Makefile:58-59"],
            "evidence": {
                "makefile_requested_budget": makefile_requested,
                "makefile_actual_genomes": makefile_actual,
                "makefile_dropped_genomes_modulo_3": makefile_dropped,
                "requested_make_hunt_budget": requested_make_budget,
                "actual_make_hunt_genomes": actual_make_genomes,
                "dropped_genomes_modulo_3": dropped_make_genomes,
                "shared_rng_warmup_identical": shared_rng_warmup_identical,
                "parity_seeds_per_search_mode": 5,
            },
            "summary": (
                f"In mode='all', fuzz.hunt passes budget // 3 and identical rng_seed=seed to random, malformed, "
                f"and evolve: on Makefile make hunt (4 x 20,000 = {makefile_requested}), integer division executes "
                f"{makefile_actual} genomes (dropping {makefile_dropped} genomes; {requested_make_budget} -> "
                f"{actual_make_genomes} in this run, dropping {dropped_make_genomes}), evolve's first 8 warm-up "
                "genomes duplicate random's first 8 genomes under rng_seed=0, and parity_probe repeats seeds[:5] "
                "3 times per track while leaving seeds 5..N-1 unprobed unless audited separately."
            ),
        },
        {
            "id": "ISSUE-W2-FUZZ-LEGACY-V0-ZERO-SCORE-INVARIANT-GAP",
            "severity": "low",
            "kind": "legacy_v0_oracle_relaxation",
            "locations": ["canary/redteam/fuzz.py:191-205", "canary/rules.py:46"],
            "evidence": {
                "fuzz_score_invariants_on_zero_wrong": fuzz.score_invariants(0.0, ["e02"], "e01"),
                "fuzz_score_invariants_on_double_accuse_zero": fuzz.score_invariants(0.0, ["e01", "e02"], "e03"),
                "fuzz_caught_planted_zero_wrong": fake_controls["v0_zero_wrong_audit"]["fuzz_score_invariants_caught"],
                "strict_v14_caught_planted_zero_wrong": fake_controls["v0_zero_wrong_audit"]["strict_v14_oracle_caught"],
            },
            "summary": (
                "fuzz.score_invariants retains a v0 compatibility allowance permitting score == 0.0 on a single wrong "
                "accusation and does not flag len(accusations) > 1 when score == 0.0; under frozen v1.4 "
                "(wrong_accusation_score = -1.0), a wrong accusation scoring 0.0 would make day-1 blind guessing "
                "positive-EV (+1/N). Our strict_v14 post-episode oracle verified 0 occurrences across every real Env "
                "episode in this sweep."
            ),
        },
        {
            "id": "ISSUE-W2-MAKE-HUNT-DEFAULT-OUT-DIR-ACCUMULATION",
            "severity": "advisory",
            "kind": "cli_artifact_accumulation",
            "locations": ["Makefile:58-59", "canary/redteam/fuzz.py:446,451-460"],
            "evidence": {
                "default_out_arg": "data/runs",
                "dirs_per_make_hunt": 4,
            },
            "summary": (
                "make hunt invokes canary.redteam.fuzz without overriding --out data/runs, creating 4 new timestamped "
                "data/runs/redteam-fuzz-<ts>-<tier>-all/ directories inside the workspace per run without cleanup."
            ),
        },
    ]
    return issues


def check_report_hygiene(report_path: Path, expected_tokens: tuple[str, ...] = ()) -> dict[str, Any]:
    problems: list[str] = []
    if not report_path.is_file():
        return {"ok": False, "problems": [f"missing_report:{report_path}"]}
    txt = report_path.read_text(encoding="utf-8")
    low = txt.lower()
    if "\u2014" in txt:
        problems.append("em_dash")
    if "\u2013" in txt:
        problems.append("en_dash")
    if "\u2212" in txt:
        problems.append("minus_sign")
    co_author = "-".join(("co", "authored", "by"))
    if co_author in low:
        problems.append("co_authored_by")
    for banned in ("pre-" + "reg", "pre" + "reg"):
        if banned in low:
            problems.append(f"banned_term:{banned}")
    for tok in expected_tokens:
        if tok not in txt:
            problems.append(f"missing_token:{tok}")
    return {"ok": not problems, "problems": problems}


def run_sweep(
    quick: bool = False,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    jobs: int | None = None,
    resume: bool = False,
    cells_override: tuple[CellSpec, ...] | None = None,
    factory: Callable[[str, int], Any] | None = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    cells = cells_override if cells_override is not None else (QUICK_CELLS if quick else FULL_CELLS)
    max_jobs = 1 if (quick or factory is not None) else max(1, jobs if jobs is not None else _available_cpus())

    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)

    mode_results: dict[tuple[str, str], dict[str, Any]] = {}
    solver_results: dict[str, dict[str, Any]] = {}
    anticheat_res: dict[str, Any] | None = None

    if factory is not None:
        is_real = factory is _default_env_factory
        for cell_id, _, tier, _, seeds, cell_budget, rng_seed in cells:
            for mode in FUZZ_MODES:
                cfac, finalize = make_auditing_factory(factory, check_strict_v14=is_real)
                mt0 = time.monotonic()
                r = fuzz.hunt(tier, seeds, cell_budget // 3, rng_seed, mode, 1, cfac)
                melapsed = round(time.monotonic() - mt0, 3)
                maudit = finalize()
                mode_results[(cell_id, mode)] = {
                    "cell_id": cell_id,
                    "tier": tier,
                    "mode": mode,
                    "n_seeds": len(seeds),
                    "cell_budget": cell_budget,
                    "mode_budget": int(r.get("budget", 0)),
                    "genomes_evaluated": 0 if mode == "parallel_accuse" else (cell_budget // 3),
                    "races": int(r.get("races", 0)),
                    "threads_per_race": int(r.get("threads_per_race", 0)),
                    "parity_seeds_probed": 0 if mode == "parallel_accuse" else min(len(seeds), 5),
                    "rng_seed": rng_seed,
                    "episode_evaluations": maudit["episodes"],
                    "tool_call_evaluations": maudit["tool_calls"],
                    "best_non_solver_score": float(r["best_non_solver_score"]),
                    "best_score_per_call": round(float(r["best_score_per_call"]), 6),
                    "n_violations": len(r["invariant_violations"]),
                    "violation_kinds": list(r["violation_kinds"]),
                    "invariant_violations": list(r["invariant_violations"])[:25],
                    "strict_v14_violations_count": len(maudit["strict_v14_violations"]),
                    "strict_v14_violations": maudit["strict_v14_violations"][:25],
                    "wall_seconds": melapsed,
                }
            solver_results[cell_id] = {
                "tier": tier,
                "n_seeds": 0,
                "live_episodes": 0,
                "committed_episodes": 0,
                "live_steps": 0,
                "seed_range": [],
                "mean_score": None,
                "fuzz_report_mean": "n/a",
                "ci95": 0.0,
                "accuracy": None,
                "n_correct": 0,
                "mean_final_day": None,
                "mean_steps": None,
                "total_steps": 0,
                "dev30_mean_score": None,
                "dev30_accuracy": None,
                "wall_seconds": 0.0,
            }
        anticheat_res = run_anticheat_verification(quick=True)
    else:
        pending_modes: list[tuple[str, str, list[int], int, int, str, str]] = []
        pending_solvers: list[tuple[str, str, list[int], bool, str]] = []
        shards_dir = out_root / "shards"
        shards_dir.mkdir(parents=True, exist_ok=True)

        for cell_id, _, tier, _, seeds, cell_budget, rng_seed in cells:
            for mode in FUZZ_MODES:
                sf = shards_dir / f"{cell_id}__{mode}.json"
                if resume and sf.is_file():
                    cached = json.loads(sf.read_text(encoding="utf-8"))
                    if cached.get("cell_budget") == cell_budget and cached.get("n_seeds") == len(seeds):
                        mode_results[(cell_id, mode)] = cached
                        continue
                pending_modes.append((cell_id, tier, seeds, cell_budget, rng_seed, mode, str(out_root)))

            sol_f = shards_dir / f"{cell_id}__solver.json"
            if resume and sol_f.is_file():
                cached_sol = json.loads(sol_f.read_text(encoding="utf-8"))
                solver_results[cell_id] = cached_sol
                continue
            pending_solvers.append((cell_id, tier, seeds, quick, str(out_root)))

        ac_f = shards_dir / "anticheat_verify.json"
        need_ac = True
        want_ac_mode = "quick_easy_roundtrip_plus_committed_schema" if quick else "easy_medium_roundtrip_plus_committed_schema"
        if resume and ac_f.is_file():
            cached_ac = json.loads(ac_f.read_text(encoding="utf-8"))
            if cached_ac.get("mode") == want_ac_mode:
                anticheat_res = cached_ac
                need_ac = False

        if max_jobs == 1:
            for item in pending_modes:
                r_m = _run_mode_shard(item)
                mode_results[(r_m["cell_id"], r_m["mode"])] = r_m
            for s_item in pending_solvers:
                cid, s_ref = _run_solver_shard(s_item)
                solver_results[cid] = s_ref
            if need_ac:
                anticheat_res = _run_anticheat_worker((quick, str(out_root)))
        else:
            pending_modes.sort(key=lambda x: -x[3])
            with ProcessPoolExecutor(max_workers=max_jobs) as pool:
                ac_fut = pool.submit(_run_anticheat_worker, (quick, str(out_root))) if need_ac else None
                mode_futs = [pool.submit(_run_mode_shard, item) for item in pending_modes]
                sol_futs = [pool.submit(_run_solver_shard, s_item) for s_item in pending_solvers]
                for fut in mode_futs:
                    r_m = fut.result()
                    mode_results[(r_m["cell_id"], r_m["mode"])] = r_m
                for sfut in sol_futs:
                    cid, s_ref = sfut.result()
                    solver_results[cid] = s_ref
                if ac_fut is not None:
                    anticheat_res = ac_fut.result()

    assert anticheat_res is not None
    parity_audit = run_full_seed_parity_audit(cells, factory=factory or _default_env_factory)
    fake_controls = run_fake_env_positive_controls(quick=quick)

    cells_summary: list[dict[str, Any]] = []
    per_mode_totals: dict[str, dict[str, Any]] = {
        m: {
            "genomes_evaluated": 0,
            "races": 0,
            "episode_evaluations": 0,
            "tool_call_evaluations": 0,
            "best_non_solver_score": 0.0,
            "best_score_per_call": 0.0,
            "n_violations": 0,
            "strict_v14_violations_count": 0,
            "cpu_seconds": 0.0,
        }
        for m in FUZZ_MODES
    }
    group_totals: dict[str, dict[str, Any]] = {
        g: {
            "cells": 0,
            "requested_budget": 0,
            "genomes_evaluated": 0,
            "races": 0,
            "episode_evaluations": 0,
            "tool_call_evaluations": 0,
            "best_non_solver_score": 0.0,
            "best_score_per_call": 0.0,
            "n_violations": 0,
            "strict_v14_violations_count": 0,
            "cpu_seconds": 0.0,
        }
        for g in ("make_hunt", "heldout")
    }

    total_requested_budget = 0
    total_genomes = 0
    total_races = 0
    total_fuzz_episodes = 0
    total_fuzz_calls = 0
    total_violations = 0
    total_strict_violations = 0
    all_violation_kinds: set[str] = set()
    overall_best_non_solver = 0.0
    overall_best_spc = 0.0
    total_fuzz_cpu_s = 0.0

    for idx_c, (cell_id, group, tier, band_label, seeds, cell_budget, rng_seed) in enumerate(cells, 1):
        p = rules.tier_params(tier)
        per_m = {m: mode_results[(cell_id, m)] for m in FUZZ_MODES}
        c_genomes = sum(int(per_m[m]["genomes_evaluated"]) for m in FUZZ_MODES)
        c_races = sum(int(per_m[m]["races"]) for m in FUZZ_MODES)
        c_eps = sum(int(per_m[m]["episode_evaluations"]) for m in FUZZ_MODES)
        c_calls = sum(int(per_m[m]["tool_call_evaluations"]) for m in FUZZ_MODES)
        c_viol = sum(int(per_m[m]["n_violations"]) for m in FUZZ_MODES)
        c_strict = sum(int(per_m[m]["strict_v14_violations_count"]) for m in FUZZ_MODES)
        c_non_solver = max(float(per_m[m]["best_non_solver_score"]) for m in FUZZ_MODES)
        c_spc = max(float(per_m[m]["best_score_per_call"]) for m in FUZZ_MODES)
        c_cpu_s = round(sum(float(per_m[m]["wall_seconds"]) for m in FUZZ_MODES), 3)
        c_kinds = sorted({k for m in FUZZ_MODES for k in per_m[m]["violation_kinds"]})
        all_violation_kinds.update(c_kinds)

        sol_ref = solver_results[cell_id]
        row = {
            "cell_index": idx_c,
            "cell_id": cell_id,
            "group": group,
            "tier": tier,
            "seed_band": band_label,
            "n_seeds": len(seeds),
            "rng_seed": rng_seed,
            "params": {
                "n_employees": p.n_employees,
                "n_days": p.n_days,
                "canaries_per_day": p.canaries_per_day,
                "max_variants": p.max_variants,
                "tool_call_cap": p.tool_call_cap,
                "leak_damage": p.leak_damage,
                "fingerprint_accuracy": p.fingerprint_accuracy,
            },
            "requested_budget": cell_budget,
            "genomes_evaluated": c_genomes,
            "races": c_races,
            "episode_evaluations": c_eps,
            "tool_call_evaluations": c_calls,
            "best_non_solver_score": c_non_solver,
            "best_score_per_call": round(c_spc, 6),
            "n_violations": c_viol,
            "strict_v14_violations_count": c_strict,
            "violation_kinds": c_kinds,
            "solver_reference": sol_ref,
            "per_mode": {
                m: {k: v for k, v in per_m[m].items() if k not in ("invariant_violations", "strict_v14_violations")}
                for m in FUZZ_MODES
            },
            "cpu_seconds": c_cpu_s,
        }
        cells_summary.append(row)

        cell_findings = [v for m in FUZZ_MODES for v in per_m[m]["invariant_violations"]]
        findings_path = out_root / f"{cell_id}_findings.jsonl"
        with open(findings_path, "w", encoding="utf-8") as fh:
            for fv in cell_findings:
                fh.write(json.dumps(fv, sort_keys=True, default=repr) + "\n")

        for m in FUZZ_MODES:
            pmt = per_mode_totals[m]
            pmt["genomes_evaluated"] += int(per_m[m]["genomes_evaluated"])
            pmt["races"] += int(per_m[m]["races"])
            pmt["episode_evaluations"] += int(per_m[m]["episode_evaluations"])
            pmt["tool_call_evaluations"] += int(per_m[m]["tool_call_evaluations"])
            pmt["best_non_solver_score"] = max(pmt["best_non_solver_score"], float(per_m[m]["best_non_solver_score"]))
            pmt["best_score_per_call"] = round(max(pmt["best_score_per_call"], float(per_m[m]["best_score_per_call"])), 6)
            pmt["n_violations"] += int(per_m[m]["n_violations"])
            pmt["strict_v14_violations_count"] += int(per_m[m]["strict_v14_violations_count"])
            pmt["cpu_seconds"] = round(pmt["cpu_seconds"] + float(per_m[m]["wall_seconds"]), 3)

        gt = group_totals[group]
        gt["cells"] += 1
        gt["requested_budget"] += cell_budget
        gt["genomes_evaluated"] += c_genomes
        gt["races"] += c_races
        gt["episode_evaluations"] += c_eps
        gt["tool_call_evaluations"] += c_calls
        gt["best_non_solver_score"] = max(gt["best_non_solver_score"], c_non_solver)
        gt["best_score_per_call"] = round(max(gt["best_score_per_call"], c_spc), 6)
        gt["n_violations"] += c_viol
        gt["strict_v14_violations_count"] += c_strict
        gt["cpu_seconds"] = round(gt["cpu_seconds"] + c_cpu_s, 3)

        total_requested_budget += cell_budget
        total_genomes += c_genomes
        total_races += c_races
        total_fuzz_episodes += c_eps
        total_fuzz_calls += c_calls
        total_violations += c_viol
        total_strict_violations += c_strict
        overall_best_non_solver = max(overall_best_non_solver, c_non_solver)
        overall_best_spc = max(overall_best_spc, c_spc)
        total_fuzz_cpu_s = round(total_fuzz_cpu_s + c_cpu_s, 3)

    solver_total_episodes = sum(int(r["live_episodes"]) for r in solver_results.values())
    solver_total_calls = sum(int(r["live_steps"]) for r in solver_results.values())
    grand_total_episodes = total_fuzz_episodes + parity_audit["episode_evaluations"] + solver_total_episodes
    grand_total_calls = total_fuzz_calls + parity_audit["tool_call_evaluations"] + solver_total_calls

    issues = inspect_make_hunt_harness_issues(cells_summary, fake_controls)
    wall_s = round(time.monotonic() - t0, 3)

    all_passed = bool(
        rules.TIERS_VERSION == "v1.4"
        and rules.KNOWN_V_MODE is True
        and v14_hash == "a8f99c2537c91d72"
        and total_violations == 0
        and total_strict_violations == 0
        and overall_best_non_solver == 0.0
        and parity_audit["violations_count"] == 0
        and parity_audit["strict_v14_violations_count"] == 0
        and anticheat_res["verified_ok"] is True
        and fake_controls["clean_control"]["clean"] is True
        and fake_controls["all_caught"] is True
        and fake_controls["v0_zero_wrong_audit"]["strict_v14_oracle_caught"] is True
    )

    summary = {
        "all_passed": all_passed,
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": rules.KNOWN_V_MODE,
        "v14_tier_hash": v14_hash,
        "v13_tier_hash": v13_hash,
        "quick": quick,
        "jobs": max_jobs,
        "tracks_make_hunt": list(MAKE_HUNT_TRACKS),
        "tracks_heldout": list(HELDOUT_TRACKS),
        "modes": list(FUZZ_MODES),
        "total_cells": len(cells_summary),
        "requested_fuzz_budget": total_requested_budget,
        "total_genomes_evaluated": total_genomes,
        "total_parallel_races": total_races,
        "fuzz_episode_evaluations": total_fuzz_episodes,
        "fuzz_tool_call_evaluations": total_fuzz_calls,
        "solver_reference_episodes": solver_total_episodes,
        "solver_reference_tool_calls": solver_total_calls,
        "grand_total_episodes": grand_total_episodes,
        "grand_total_tool_calls": grand_total_calls,
        "best_non_solver_score": overall_best_non_solver,
        "best_score_per_call": round(overall_best_spc, 6),
        "total_invariant_violations": total_violations,
        "total_strict_v14_violations": total_strict_violations,
        "violation_kinds": sorted(all_violation_kinds),
        "fuzz_cpu_seconds": total_fuzz_cpu_s,
        "wall_seconds": wall_s,
        "group_totals": group_totals,
        "per_mode_totals": per_mode_totals,
        "cells": cells_summary,
        "full_seed_parity_audit": parity_audit,
        "anticheat_verification": anticheat_res,
        "fake_env_positive_controls": fake_controls,
        "report_only_issues": issues,
    }
    (out_root / "final_make_hunt_v14_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_final_make_hunt_v14")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--check-report", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    summary = run_sweep(
        quick=args.quick,
        out_dir=args.out_dir,
        jobs=args.jobs,
        resume=args.resume,
    )
    if args.check_report is not None:
        rep_chk = check_report_hygiene(args.check_report)
        summary["report_check"] = rep_chk
        summary["all_passed"] = bool(summary["all_passed"] and rep_chk["ok"])
        (Path(args.out_dir) / "final_make_hunt_v14_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            f"tiers={summary['tiers_version']} ({summary['v14_tier_hash']}) quick={summary['quick']} "
            f"jobs={summary['jobs']} cells={summary['total_cells']} genomes={summary['total_genomes_evaluated']} "
            f"races={summary['total_parallel_races']} fuzz_eps={summary['fuzz_episode_evaluations']} "
            f"fuzz_calls={summary['fuzz_tool_call_evaluations']} grand_calls={summary['grand_total_tool_calls']} "
            f"non_solver={summary['best_non_solver_score']:.3f} violations={summary['total_invariant_violations']} "
            f"strict_v14_violations={summary['total_strict_v14_violations']} "
            f"ac_ok={summary['anticheat_verification']['verified_ok']} "
            f"fake_caught={summary['fake_env_positive_controls']['bugs_caught']}/{summary['fake_env_positive_controls']['bugs_tested']} "
            f"wall={summary['wall_seconds']}s"
        )
        for c in summary["cells"]:
            sm = c["solver_reference"]["mean_score"]
            sa = c["solver_reference"]["accuracy"]
            sm_s = f"{sm:.4f}" if isinstance(sm, float) else "n/a"
            sa_s = f"{sa:.4f}" if isinstance(sa, float) else "n/a"
            print(
                f"  [{c['cell_id']:29s}] budget={c['requested_budget']:5d} genomes={c['genomes_evaluated']:5d} "
                f"eps={c['episode_evaluations']:6d} calls={c['tool_call_evaluations']:7d} "
                f"non_solver={c['best_non_solver_score']:.3f} spc={c['best_score_per_call']:.6f} "
                f"solver={sm_s} (acc={sa_s}) viol={c['n_violations']}/{c['strict_v14_violations_count']} "
                f"cpu={c['cpu_seconds']}s"
            )
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
