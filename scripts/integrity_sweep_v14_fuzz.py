from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.env import Env
from canary.eval import run_episode
from canary.redteam import fuzz
from canary.solver.policy import SolverPolicy
from canary.world import generate_world

TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge", "hard_rl")
MODES_EXPECTED = ("random", "malformed", "evolve", "parallel_accuse")
DEFAULT_SCRATCH_ROOT = Path("/localscratch/job_44578")


def _default_out_dir(
    scratch_root: Path = DEFAULT_SCRATCH_ROOT,
    repo_root: Path = ROOT,
) -> str:
    env_dir = os.environ.get("CANARY_FUZZ_OUT_DIR")
    if env_dir:
        return env_dir
    if scratch_root.is_dir():
        return str(scratch_root / "w1" / "w1-fuzz")
    return str(repo_root / "results" / "latest" / "v14_fuzz_sweep")


DEFAULT_OUT_DIR = _default_out_dir()

FULL_SEED_BANDS: tuple[tuple[str, list[int]], ...] = (
    ("0-99", list(range(0, 100))),
    ("50000-50199", list(range(50000, 50200))),
)
QUICK_SEED_BANDS: tuple[tuple[str, list[int]], ...] = (
    ("0", [0]),
    ("50000", [50000]),
)

FULL_BAND_BUDGETS: dict[str, tuple[int, int]] = {
    "easy": (2001, 3999),
    "medium": (3000, 6000),
    "hard": (1500, 3000),
    "hard_forge": (2001, 3999),
    "hard_rl": (2001, 3999),
}
QUICK_BAND_BUDGETS: dict[str, tuple[int, int]] = {
    "easy": (3, 3),
    "medium": (3, 3),
    "hard": (3, 3),
    "hard_forge": (3, 3),
    "hard_rl": (3, 3),
}


def _default_env_factory(tier: str, seed: int):
    return Env(tier=tier, seed=seed)


def _counting_factory(base_factory: Callable[[str, int], Any]) -> tuple[Callable[[str, int], Any], Callable[[], tuple[int, int]]]:
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


def inspect_world_departments(
    targets: tuple[str, ...] = TARGETS,
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    sample_seeds = list(seeds) if seeds is not None else (list(range(0, 100)) + list(range(50000, 50200)))
    per_target: dict[str, Any] = {}
    for target in targets:
        p = rules.tier_params(target)
        dept_counts: set[int] = set()
        depts_union: set[str] = set()
        rec_sizes: list[int] = []
        for s in sample_seeds:
            w = generate_world(target, s, p)
            dept_counts.add(len(w.depts))
            depts_union.update(w.depts)
            for docs in w.planned_docs.values():
                for doc in docs:
                    rec_sizes.append(len(doc["recipients"]))
        env0 = Env(tier=target, seed=sample_seeds[0])
        ins = env0.instruction()
        claims_same_as_hard = "All other rules and numbers are the same as in the hard tier." in ins
        mean_rec = round(sum(rec_sizes) / len(rec_sizes), 4) if rec_sizes else 0.0
        per_target[target] = {
            "n_employees": p.n_employees,
            "n_days": p.n_days,
            "canaries_per_day": p.canaries_per_day,
            "max_variants": p.max_variants,
            "tool_call_cap": p.tool_call_cap,
            "p_single_dept_recipients": p.p_single_dept_recipients,
            "dept_counts_seen": sorted(dept_counts),
            "dept_count": sorted(dept_counts)[0] if len(dept_counts) == 1 else sorted(dept_counts),
            "depts": sorted(depts_union),
            "n_seeds_checked": len(sample_seeds),
            "n_planned_docs": len(rec_sizes),
            "recipient_size_min": min(rec_sizes) if rec_sizes else 0,
            "recipient_size_mean": mean_rec,
            "recipient_size_max": max(rec_sizes) if rec_sizes else 0,
            "recipient_share_mean": round(mean_rec / p.n_employees, 4) if p.n_employees else 0.0,
            "instruction_claims_same_as_hard": claims_same_as_hard,
        }

    hard_info = per_target.get("hard", {})
    hard_forge_info = per_target.get("hard_forge", {})
    hard_rl_info = per_target.get("hard_rl", {})
    hard_depts = set(hard_info.get("depts", []))
    hard_rl_depts = set(hard_rl_info.get("depts", []))
    mismatch = bool(
        hard_info
        and hard_rl_info
        and hard_rl_info.get("dept_count") != hard_info.get("dept_count")
        and hard_rl_info.get("instruction_claims_same_as_hard")
    )
    return {
        "n_seeds_checked": len(sample_seeds),
        "hard_dept_count": hard_info.get("dept_count"),
        "hard_forge_dept_count": hard_forge_info.get("dept_count"),
        "hard_rl_dept_count": hard_rl_info.get("dept_count"),
        "missing_depts_in_hard_rl": sorted(hard_depts - hard_rl_depts) if (hard_info and hard_rl_info) else [],
        "hard_recipient_size_mean": hard_info.get("recipient_size_mean"),
        "hard_forge_recipient_size_mean": hard_forge_info.get("recipient_size_mean"),
        "hard_rl_recipient_size_mean": hard_rl_info.get("recipient_size_mean"),
        "mismatch_detected": mismatch,
        "per_target": per_target,
    }


def compute_solver_reference(tier: str, seeds: list[int]) -> dict[str, Any]:
    scores: list[float] = []
    corrects: list[bool] = []
    days: list[int] = []
    for s in seeds:
        ep = run_episode(Env(tier=tier, seed=s), SolverPolicy())
        scores.append(float(ep.score))
        corrects.append(bool(ep.correct))
        days.append(int(ep.final_day))
    n = len(scores)
    return {
        "n_seeds": n,
        "seeds_sample": [seeds[0], seeds[-1]] if seeds else [],
        "mean_score": round(sum(scores) / n, 4) if n else 0.0,
        "accuracy": round(sum(corrects) / n, 4) if n else 0.0,
        "mean_final_day": round(sum(days) / n, 2) if n else 0.0,
    }


def _parse_budget_overrides(spec: str | None) -> dict[str, int | tuple[int, int]]:
    if not spec:
        return {}
    out: dict[str, int | tuple[int, int]] = {}
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            k, _, v = item.partition("=")
            if not k or not v:
                raise ValueError(f"invalid budget override: {item}")
            out[k.strip()] = int(v.strip())
        elif ":" in item:
            parts = [p.strip() for p in item.split(":")]
            if len(parts) == 3 and parts[0]:
                out[parts[0]] = (int(parts[1]), int(parts[2]))
            elif len(parts) == 2 and parts[0]:
                out[parts[0]] = int(parts[1])
            else:
                raise ValueError(f"invalid budget override: {item}")
        else:
            raise ValueError(f"invalid budget override: {item}")
    return out


def run_sweep(
    quick: bool = False,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    workers: int = 1,
    rng_seed: int = 0,
    targets: tuple[str, ...] = TARGETS,
    budget_overrides: dict[str, int | tuple[int, int]] | None = None,
    compute_solver: bool = True,
    resume: bool = False,
    factory: Callable[[str, int], Any] = _default_env_factory,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("workers must be 1 (single-process rule)")
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    seed_bands = QUICK_SEED_BANDS if quick else FULL_SEED_BANDS
    base_budgets = QUICK_BAND_BUDGETS if quick else FULL_BAND_BUDGETS
    overrides = budget_overrides or {}

    t_start = time.time()
    all_seeds_flat = [s for _, band in seed_bands for s in band]
    world_check = inspect_world_departments(targets=targets, seeds=all_seeds_flat)

    per_target: dict[str, Any] = {}
    total_episodes = 0
    total_tool_calls = 0
    total_budget = 0
    total_violations = 0
    all_violation_kinds: set[str] = set()
    overall_best_non_solver = 0.0
    overall_best_score_per_call = 0.0

    for idx_t, target in enumerate(targets):
        t0 = time.time()
        t_idx = TARGETS.index(target) if target in TARGETS else idx_t
        if target in overrides:
            ov = overrides[target]
            if isinstance(ov, tuple):
                band_budgets = ov
            else:
                b0 = max(3, (ov // 3 // 3) * 3)
                b1 = max(3, ov - b0)
                band_budgets = (b0, b1)
        else:
            band_budgets = base_budgets[target]

        band_results: dict[str, Any] = {}
        target_violations: list[dict[str, Any]] = []
        target_episodes = 0
        target_tool_calls = 0
        target_budget = 0
        target_best_non_solver = 0.0
        target_best_spc = 0.0
        target_band_secs = 0.0
        merged_modes: dict[str, dict[str, Any]] = {
            m: {"budget": 0, "best_non_solver_score": 0.0, "best_score_per_call": 0.0, "n_violations": 0, "races": 0}
            for m in MODES_EXPECTED
        }

        for idx_b, ((band_label, band_seeds), band_budget) in enumerate(zip(seed_bands, band_budgets)):
            run_rng = rng_seed + t_idx * 100 + idx_b
            band_dir = out_root / f"{target}_{band_label}"
            summary_file = band_dir / "summary.json"
            findings_file = band_dir / "findings.jsonl"

            reused = False
            if resume and summary_file.exists() and findings_file.exists():
                cached = json.loads(summary_file.read_text(encoding="utf-8"))
                if (
                    cached.get("tier") == target
                    and cached.get("seed_band") == band_label
                    and cached.get("budget") == band_budget
                    and cached.get("rng_seed") == run_rng
                ):
                    band_summary = cached
                    band_violations = [
                        json.loads(ln)
                        for ln in findings_file.read_text(encoding="utf-8").splitlines()
                        if ln.strip()
                    ]
                    reused = True

            if not reused:
                cfac, read_counts = _counting_factory(factory)
                bt0 = time.time()
                res = fuzz.hunt(
                    tier=target,
                    seeds=band_seeds,
                    budget=band_budget,
                    seed=run_rng,
                    mode="all",
                    workers=1,
                    factory=cfac,
                )
                eps, calls = read_counts()
                b_elapsed = round(time.time() - bt0, 2)

                band_dir.mkdir(parents=True, exist_ok=True)
                band_violations = list(res["invariant_violations"])
                with open(findings_file, "w", encoding="utf-8") as fh:
                    for v in band_violations:
                        fh.write(json.dumps(v, sort_keys=True, default=repr) + "\n")

                band_summary = {
                    "tier": target,
                    "seed_band": band_label,
                    "n_seeds": len(band_seeds),
                    "budget": band_budget,
                    "rng_seed": run_rng,
                    "episode_evaluations": eps,
                    "tool_call_evaluations": calls,
                    "mode": res["mode"],
                    "best_non_solver_score": res["best_non_solver_score"],
                    "best_score_per_call": round(res["best_score_per_call"], 6),
                    "n_violations": len(band_violations),
                    "violation_kinds": res["violation_kinds"],
                    "per_mode": res["per_mode"],
                    "seconds": b_elapsed,
                }
                summary_file.write_text(json.dumps(band_summary, indent=2) + "\n", encoding="utf-8")

            band_results[band_label] = band_summary
            target_violations.extend(band_violations)
            target_episodes += int(band_summary["episode_evaluations"])
            target_tool_calls += int(band_summary["tool_call_evaluations"])
            target_budget += int(band_summary["budget"])
            target_best_non_solver = max(target_best_non_solver, float(band_summary["best_non_solver_score"]))
            target_best_spc = max(target_best_spc, float(band_summary["best_score_per_call"]))
            target_band_secs += float(band_summary["seconds"])

            for m_name, m_data in band_summary["per_mode"].items():
                mm = merged_modes[m_name]
                mm["budget"] += int(m_data.get("budget", 0))
                mm["best_non_solver_score"] = max(mm["best_non_solver_score"], float(m_data["best_non_solver_score"]))
                mm["best_score_per_call"] = max(mm["best_score_per_call"], float(m_data["best_score_per_call"]))
                mm["n_violations"] += int(m_data["n_violations"])
                mm["races"] += int(m_data.get("races", 0))

        solver_ref: dict[str, Any] | None = None
        if compute_solver:
            if quick:
                solver_seeds = [seed_bands[0][1][0]]
            else:
                solver_seeds = seed_bands[0][1][:30]
            solver_ref = compute_solver_reference(target, solver_seeds)

        v_kinds = sorted({v["kind"] for v in target_violations})
        all_violation_kinds.update(v_kinds)
        p = rules.tier_params(target)
        per_target[target] = {
            "tier": target,
            "params": {
                "n_employees": p.n_employees,
                "n_days": p.n_days,
                "canaries_per_day": p.canaries_per_day,
                "max_variants": p.max_variants,
                "tool_call_cap": p.tool_call_cap,
                "leak_damage": p.leak_damage,
                "fingerprint_accuracy": p.fingerprint_accuracy,
            },
            "budget": target_budget,
            "episode_evaluations": target_episodes,
            "tool_call_evaluations": target_tool_calls,
            "best_non_solver_score": target_best_non_solver,
            "best_score_per_call": round(target_best_spc, 6),
            "solver_mean": solver_ref["mean_score"] if solver_ref is not None else None,
            "solver_accuracy": solver_ref["accuracy"] if solver_ref is not None else None,
            "solver_n_seeds": solver_ref["n_seeds"] if solver_ref is not None else 0,
            "solver_reference": solver_ref,
            "invariant_violations_count": len(target_violations),
            "violation_kinds": v_kinds,
            "per_mode": merged_modes,
            "per_band": band_results,
            "seconds": round(max(time.time() - t0, target_band_secs), 2),
        }

        total_episodes += target_episodes
        total_tool_calls += target_tool_calls
        total_budget += target_budget
        total_violations += len(target_violations)
        overall_best_non_solver = max(overall_best_non_solver, target_best_non_solver)
        overall_best_score_per_call = max(overall_best_score_per_call, target_best_spc)

    report_only_issues: list[dict[str, Any]] = []
    if world_check.get("mismatch_detected"):
        report_only_issues.append(
            {
                "id": "ISSUE-W1-HARD-RL-DEPTS",
                "severity": "medium",
                "kind": "rule_vs_world_mismatch",
                "locations": ["canary/world.py:121", "canary/env.py:205", "canary/forge_track.py:89"],
                "summary": (
                    f"generate_world gives hard_rl {world_check['hard_rl_dept_count']} departments "
                    f"(missing {world_check['missing_depts_in_hard_rl']}) with mean regular doc recipient size "
                    f"{world_check['hard_rl_recipient_size_mean']} vs hard {world_check['hard_dept_count']} "
                    f"departments and mean {world_check['hard_recipient_size_mean']}, despite env.py:205 stating "
                    "all other rules and numbers match the hard tier."
                ),
            }
        )
    hard_rl_row = per_target.get("hard_rl")
    if (
        hard_rl_row is not None
        and int(hard_rl_row.get("solver_n_seeds", 0)) >= 20
        and hard_rl_row.get("solver_accuracy") is not None
        and float(hard_rl_row["solver_accuracy"]) < 0.75
    ):
        report_only_issues.append(
            {
                "id": "ISSUE-W1-HARD-RL-V14-CATCHABILITY",
                "severity": "low",
                "kind": "solver_catchability_drift",
                "locations": ["canary/forge_track.py:25", "canary/forge/rl_mole.py:35", "data/rl_mole/hall_of_fame.jsonl"],
                "summary": (
                    f"On v1.4 hard_rl (n={hard_rl_row['solver_n_seeds']} dev seeds), SolverPolicy accuracy is "
                    f"{hard_rl_row['solver_accuracy']} (mean_score={hard_rl_row['solver_mean']}), below the "
                    "MIN_ACC=0.75 catchability floor enforced during v1.3 HoF validation."
                ),
            }
        )

    summary = {
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": rules.KNOWN_V_MODE,
        "quick": quick,
        "workers": workers,
        "mode": "all",
        "rng_seed": rng_seed,
        "targets": list(targets),
        "seed_bands": [label for label, _ in seed_bands],
        "total_genome_budget": total_budget,
        "total_episode_evaluations": total_episodes,
        "total_tool_call_evaluations": total_tool_calls,
        "best_non_solver_score": overall_best_non_solver,
        "best_score_per_call": round(overall_best_score_per_call, 6),
        "total_invariant_violations": total_violations,
        "violation_kinds": sorted(all_violation_kinds),
        "per_target": per_target,
        "world_check": world_check,
        "report_only_issues": report_only_issues,
        "elapsed_seconds": round(
            max(time.time() - t_start, sum(float(r["seconds"]) for r in per_target.values())),
            2,
        ),
    }
    (out_root / "sweep_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_sweep_v14_fuzz")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--targets", default=",".join(TARGETS))
    ap.add_argument("--budgets", default=None)
    ap.add_argument("--no-solver", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise SystemExit("error: --workers must be 1")

    targets = tuple(t.strip() for t in args.targets.split(",") if t.strip())
    overrides = _parse_budget_overrides(args.budgets)
    summary = run_sweep(
        quick=args.quick,
        out_dir=args.out_dir,
        workers=args.workers,
        rng_seed=args.rng,
        targets=targets,
        budget_overrides=overrides,
        compute_solver=not args.no_solver,
        resume=args.resume,
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"tiers={summary['tiers_version']} quick={summary['quick']} workers={summary['workers']} "
            f"episodes={summary['total_episode_evaluations']} tool_calls={summary['total_tool_call_evaluations']} "
            f"violations={summary['total_invariant_violations']} best_non_solver={summary['best_non_solver_score']:.3f} "
            f"elapsed={summary['elapsed_seconds']}s"
        )
        for t in targets:
            row = summary["per_target"][t]
            sm = f"{row['solver_mean']:.3f}" if row["solver_mean"] is not None else "n/a"
            print(
                f"  [{t:10s}] budget={row['budget']:6d} episodes={row['episode_evaluations']:6d} "
                f"tool_calls={row['tool_call_evaluations']:7d} non_solver={row['best_non_solver_score']:.3f} "
                f"solver={sm} violations={row['invariant_violations_count']} ({row['seconds']}s)"
            )
        wc = summary["world_check"]
        print(
            f"  [world_check] hard_depts={wc['hard_dept_count']} (mean_rec={wc['hard_recipient_size_mean']}) "
            f"hard_forge_depts={wc['hard_forge_dept_count']} (mean_rec={wc['hard_forge_recipient_size_mean']}) "
            f"hard_rl_depts={wc['hard_rl_dept_count']} (mean_rec={wc['hard_rl_recipient_size_mean']}) "
            f"mismatch={wc['mismatch_detected']}"
        )

    return 1 if summary["total_invariant_violations"] > 0 or summary["best_non_solver_score"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
