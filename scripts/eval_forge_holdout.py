from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.runlog import git_sha, parse_seeds
from canary.forge.fitness import (
    FEASIBLE_SOLVER_RATIO,
    ClassFactory,
    default_solver_factory,
    evaluate,
    fake_factory,
    fake_runner,
    real_runner,
    solver_baseline,
    tier_defaults,
)
from canary.forge.mutate import canonical, default_strategy_json, validate_strategy
from canary.rules import TIERS_VERSION

DEFAULT_RUN_DIR = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "mole-forge-carbon-hard-deep"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

INVESTIGATOR_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("grok_tactics", "GrokTactics", "canary.baselines", "GrokTactics"),
    ("heuristic", "Heuristic", "canary.baselines", "Heuristic"),
    ("hinted_heuristic", "HintedHeuristic", "canary.forge.investigators", "HintedHeuristic"),
    ("obvious_heuristic", "ObviousHeuristic", "canary.baselines", "ObviousHeuristic"),
)


def clean_str(val: str) -> str:
    return val.replace(EM_DASH, "-").replace(EN_DASH, "-")


def sanitize_json(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {clean_str(str(k)): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    return obj


def rel_posix(path: Path) -> str:
    resolved = path.resolve()
    root_resolved = ROOT.resolve()
    if resolved.is_relative_to(root_resolved):
        return resolved.relative_to(root_resolved).as_posix()
    return path.as_posix()


def holdout_investigators(fake: bool = False) -> dict[str, Any]:
    if fake:
        return {key: fake_factory for key, _, _, _ in INVESTIGATOR_SPECS}
    return {key: ClassFactory(mod, attr) for key, _, mod, attr in INVESTIGATOR_SPECS}


def select_top_unique_strategies(hof_path: Path, top_k: int = 3) -> list[dict[str, Any]]:
    if not hof_path.is_file():
        raise FileNotFoundError(f"Missing hall_of_fame.jsonl at {hof_path}")
    default_norm = validate_strategy(default_strategy_json())
    default_key = canonical(default_norm)
    seen: set[str] = {default_key}
    selected: list[dict[str, Any]] = []
    fallback_default_row: dict[str, Any] | None = None

    lines = [ln for ln in hof_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"Empty hall_of_fame.jsonl at {hof_path}")

    for idx, ln in enumerate(lines, start=1):
        row = json.loads(ln)
        raw_sj = row.get("strategy_json", row.get("strategy"))
        if raw_sj is None:
            raise ValueError(f"{hof_path}: line {idx} missing strategy_json")
        norm_sj = validate_strategy(raw_sj)
        key = canonical(norm_sj)
        rank = int(row.get("rank", idx))
        entry = {
            "strategy_id": f"hof_rank_{rank}",
            "label": f"HoF#{rank}",
            "hof_rank": rank,
            "dev_fitness": row.get("fitness"),
            "dev_solver_score": row.get("solver_score"),
            "dev_solver_acc": row.get("solver_acc"),
            "strategy_json": norm_sj,
        }
        if key == default_key and fallback_default_row is None:
            fallback_default_row = entry
            continue
        if key in seen:
            continue
        seen.add(key)
        selected.append(entry)
        if len(selected) >= top_k:
            break

    if not selected and fallback_default_row is not None and top_k > 0:
        selected.append(fallback_default_row)
    return selected


def pool_disjoint_evals(
    eval_a: dict[str, Any],
    seeds_a: list[int],
    eval_b: dict[str, Any],
    seeds_b: list[int],
    baseline_combined: dict[str, float],
    fitness_mode: str,
    min_solver_acc: float,
) -> dict[str, Any]:
    na = len(seeds_a)
    nb = len(seeds_b)
    ntot = na + nb
    if ntot <= 0:
        raise ValueError("Combined seed count must be positive")
    solver_score = (na * float(eval_a["solver_score"]) + nb * float(eval_b["solver_score"])) / ntot
    solver_acc = (na * float(eval_a["solver_acc"]) + nb * float(eval_b["solver_acc"])) / ntot
    per_inv: dict[str, dict[str, float]] = {}
    for inv_key in sorted(eval_a["per_investigator"]):
        ia = eval_a["per_investigator"][inv_key]
        ib = eval_b["per_investigator"][inv_key]
        sc = (na * float(ia["score"]) + nb * float(ib["score"])) / ntot
        ac = (na * float(ia["acc"]) + nb * float(ib["acc"])) / ntot
        reg = (na * float(ia["regret"]) + nb * float(ib["regret"])) / ntot
        per_inv[inv_key] = {"score": sc, "acc": ac, "regret": reg}
    mean_regret = sum(v["regret"] for v in per_inv.values()) / len(per_inv) if per_inv else 0.0
    min_regret = min((v["regret"] for v in per_inv.values()), default=0.0)
    feasible = (solver_score >= FEASIBLE_SOLVER_RATIO * float(baseline_combined["score"])) and (
        solver_acc >= min_solver_acc
    )
    fit_raw = min_regret if fitness_mode == "min" else mean_regret
    return {
        "fitness": fit_raw if feasible else None,
        "regret": mean_regret,
        "min_regret": min_regret,
        "fitness_mode": fitness_mode,
        "min_solver_acc": min_solver_acc,
        "solver_score": solver_score,
        "solver_acc": solver_acc,
        "per_investigator": per_inv,
        "feasible": feasible,
        "baseline_solver_score": float(baseline_combined["score"]),
        "beaten": [k for k, v in per_inv.items() if v["regret"] > 0],
    }


def pick_best_evolved(evolved_entries: list[dict[str, Any]], split_key: str) -> dict[str, Any] | None:
    if not evolved_entries:
        return None
    feasible = [e for e in evolved_entries if e[split_key].get("feasible")]
    pool = feasible if feasible else evolved_entries
    return max(pool, key=lambda e: (float(e[split_key]["min_regret"]), -int(e["hof_rank"])))


def format_split_table(
    title: str,
    seeds: list[int],
    split_key: str,
    all_entries: list[dict[str, Any]],
) -> list[str]:
    seed_span = f"{seeds[0]}..{seeds[-1]}" if seeds == list(range(seeds[0], seeds[-1] + 1)) else ",".join(map(str, seeds))
    lines = [
        f"## {title} (`{seed_span}`, `n={len(seeds)}`)",
        "",
        "| Strategy | Investigator | Mean Score | Accuracy | Regret (Solver - Inv) |",
        "|---|---|---:|---:|---:|",
    ]
    for entry in all_entries:
        ev = entry[split_key]
        label = entry["label"]
        lines.append(
            f"| `{label}` | `SolverPolicy` | {ev['solver_score']:+.4f} | {ev['solver_acc']:.2%} | +0.0000 |"
        )
        for inv_key, inv_label, _, _ in INVESTIGATOR_SPECS:
            iv = ev["per_investigator"][inv_key]
            lines.append(
                f"| `{label}` | `{inv_label}` | {iv['score']:+.4f} | {iv['acc']:.2%} | {iv['regret']:+.4f} |"
            )
    lines.append("")
    return lines


def build_holdout_summary_md(doc: dict[str, Any]) -> str:
    unseen_seeds = doc["splits"]["unseen_seeds"]
    confirm_seeds = doc["splits"]["confirm_seeds"]
    combined_seeds = doc["splits"]["combined_seeds"]
    s = doc["summary"]
    default_entry = doc["default_mole"]
    evolved_entries = doc["evolved_strategies"]
    all_entries = [default_entry, *evolved_entries]

    lines = [
        "# Mole Forge Holdout Generalization Report",
        "",
        f"- **Source run:** `{doc['source_run_dir']}`",
        f"- **Model:** `{doc['source_model_id'] or 'unknown'}`",
        f"- **Source commit:** `{doc['source_commit']}` (eval commit: `{doc['eval_commit']}`)",
        f"- **Timestamp:** `{doc['timestamp']}`",
        f"- **Tier:** `{doc['tier']}` (`{doc['tiers_version']}`, solver accuracy floor `>= {doc['min_solver_acc']:.0%}`)",
        f"- **Unseen hard seeds:** `{unseen_seeds[0]}..{unseen_seeds[-1]}` (`n={len(unseen_seeds)}`)",
        f"- **Fresh confirmation seeds:** `{confirm_seeds[0]}..{confirm_seeds[-1]}` (`n={len(confirm_seeds)}`)",
        f"- **Top-1 unseen min regret:** `{s['top1_unseen_min_regret']:+.4f}` vs default `{s['default_unseen_min_regret']:+.4f}` (delta `{s['top1_unseen_delta_vs_default']:+.4f}`)",
        f"- **Top-1 confirmation min regret:** `{s['top1_confirm_min_regret']:+.4f}` vs default `{s['default_confirm_min_regret']:+.4f}` (delta `{s['top1_confirm_delta_vs_default']:+.4f}`)",
        f"- **Top-1 combined 30-seed min regret:** `{s['top1_combined_min_regret']:+.4f}` vs default `{s['default_combined_min_regret']:+.4f}` (delta `{s['top1_combined_delta_vs_default']:+.4f}`)",
        f"- **All evolved strategies solvable (`SolverPolicy` feasible):** unseen=`{s['all_evolved_solvable_unseen']}`, confirm=`{s['all_evolved_solvable_confirm']}`",
        "",
        "## Strategy Generalization Summary",
        "",
        "| Strategy | Dev Fitness | Unseen Solver Acc | Unseen Min Regret | Confirm Solver Acc | Confirm Min Regret | Combined Solver Acc | Combined Min Regret | Combined Mean Regret | Feasible (U/C/All) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for entry in all_entries:
        dev_fit = entry.get("dev_fitness")
        dev_txt = "n/a" if dev_fit is None else f"{float(dev_fit):+.4f}"
        u = entry["unseen"]
        c = entry["confirm"]
        cb = entry["combined"]
        feas_txt = f"{'Y' if u['feasible'] else 'N'}/{'Y' if c['feasible'] else 'N'}/{'Y' if cb['feasible'] else 'N'}"
        lines.append(
            f"| `{entry['label']}` | {dev_txt} "
            f"| {u['solver_acc']:.2%} | {u['min_regret']:+.4f} "
            f"| {c['solver_acc']:.2%} | {c['min_regret']:+.4f} "
            f"| {cb['solver_acc']:.2%} | {cb['min_regret']:+.4f} | {cb['regret']:+.4f} "
            f"| {feas_txt} |"
        )

    lines.append("")
    lines.extend(format_split_table("Unseen Hard Seeds Breakdown", unseen_seeds, "unseen", all_entries))
    lines.extend(format_split_table("Fresh Confirmation Seeds Breakdown", confirm_seeds, "confirm", all_entries))
    lines.extend(format_split_table("Combined Holdout Seeds Breakdown", combined_seeds, "combined", all_entries))

    lines.append("## Evaluated Evolved Strategies (DSL)")
    lines.append("")
    for entry in evolved_entries:
        lines.append(f"### `{entry['label']}` (`{entry['strategy_id']}`)")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(entry["strategy_json"], indent=2))
        lines.append("```")
        lines.append("")

    return clean_str("\n".join(lines))


def evaluate_holdout(
    run_dir: str | Path = DEFAULT_RUN_DIR,
    hof_path: str | Path | None = None,
    top_k: int = 3,
    tier: str = "hard",
    unseen_seeds: str = "20-29",
    confirm_seeds: str = "5020-5039",
    workers: int = 8,
    min_solver_acc: float | None = None,
    fake: bool = False,
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
    command_str: str = "",
) -> dict[str, Any]:
    rdir = Path(run_dir)
    hpath = Path(hof_path) if hof_path is not None else (rdir / "hall_of_fame.jsonl")
    json_path = Path(out_json) if out_json is not None else (rdir / "holdout_generalization.json")
    md_path = Path(out_md) if out_md is not None else (rdir / "holdout_summary.md")

    unseen_list = parse_seeds(unseen_seeds)
    confirm_list = parse_seeds(confirm_seeds)
    if not unseen_list or not confirm_list:
        raise ValueError("Both unseen_seeds and confirm_seeds must be non-empty")

    td = tier_defaults(tier)
    fitness_mode = td["fitness_mode"]
    acc_floor = td["min_solver_acc"] if min_solver_acc is None else min_solver_acc

    source_meta: dict[str, Any] = {}
    meta_file = rdir / "meta.json"
    if meta_file.is_file():
        parsed_meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if isinstance(parsed_meta, dict):
            source_meta = parsed_meta

    top_unique = select_top_unique_strategies(hpath, top_k=top_k)
    default_strat = validate_strategy(default_strategy_json())

    runner = fake_runner if fake else real_runner
    solver_fac = fake_factory if fake else default_solver_factory()
    inv_map = holdout_investigators(fake=fake)

    unseen_base = solver_baseline(solver_fac, unseen_list, tier, runner, workers)
    confirm_base = solver_baseline(solver_fac, confirm_list, tier, runner, workers)

    disjoint = set(unseen_list).isdisjoint(set(confirm_list))
    combined_list = list(dict.fromkeys([*unseen_list, *confirm_list]))
    if disjoint:
        ntot = len(unseen_list) + len(confirm_list)
        combined_base = {
            "score": (len(unseen_list) * unseen_base["score"] + len(confirm_list) * confirm_base["score"]) / ntot,
            "acc": (len(unseen_list) * unseen_base["acc"] + len(confirm_list) * confirm_base["acc"]) / ntot,
        }
    else:
        combined_base = solver_baseline(solver_fac, combined_list, tier, runner, workers)

    def eval_strategy_all_splits(strat_json: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        ev_u = evaluate(
            strat_json,
            inv_map,
            solver_fac,
            unseen_list,
            tier,
            runner=runner,
            workers=workers,
            baseline=unseen_base,
            fitness_mode=fitness_mode,
            min_solver_acc=acc_floor,
        )
        ev_c = evaluate(
            strat_json,
            inv_map,
            solver_fac,
            confirm_list,
            tier,
            runner=runner,
            workers=workers,
            baseline=confirm_base,
            fitness_mode=fitness_mode,
            min_solver_acc=acc_floor,
        )
        if disjoint:
            ev_all = pool_disjoint_evals(
                ev_u,
                unseen_list,
                ev_c,
                confirm_list,
                combined_base,
                fitness_mode=fitness_mode,
                min_solver_acc=acc_floor,
            )
        else:
            ev_all = evaluate(
                strat_json,
                inv_map,
                solver_fac,
                combined_list,
                tier,
                runner=runner,
                workers=workers,
                baseline=combined_base,
                fitness_mode=fitness_mode,
                min_solver_acc=acc_floor,
            )
        return sanitize_json(ev_u), sanitize_json(ev_c), sanitize_json(ev_all)

    def_u, def_c, def_all = eval_strategy_all_splits(default_strat)
    default_entry = {
        "strategy_id": "default_mole",
        "label": "DefaultMole",
        "is_default": True,
        "dev_fitness": source_meta.get("default_dev_fitness"),
        "strategy_json": default_strat,
        "unseen": def_u,
        "confirm": def_c,
        "combined": def_all,
    }

    evolved_entries: list[dict[str, Any]] = []
    for item in top_unique:
        eu, ec, eall = eval_strategy_all_splits(item["strategy_json"])
        evolved_entries.append(
            {
                **item,
                "is_default": False,
                "unseen": eu,
                "confirm": ec,
                "combined": eall,
            }
        )

    top1 = evolved_entries[0] if evolved_entries else default_entry
    best_u = pick_best_evolved(evolved_entries, "unseen")
    best_c = pick_best_evolved(evolved_entries, "confirm")
    best_all = pick_best_evolved(evolved_entries, "combined")

    summary = {
        "n_evolved_evaluated": len(evolved_entries),
        "best_unseen_strategy_id": best_u["strategy_id"] if best_u else None,
        "best_unseen_min_regret": float(best_u["unseen"]["min_regret"]) if best_u else None,
        "best_confirm_strategy_id": best_c["strategy_id"] if best_c else None,
        "best_confirm_min_regret": float(best_c["confirm"]["min_regret"]) if best_c else None,
        "best_combined_strategy_id": best_all["strategy_id"] if best_all else None,
        "best_combined_min_regret": float(best_all["combined"]["min_regret"]) if best_all else None,
        "top1_strategy_id": top1["strategy_id"],
        "top1_unseen_solver_acc": float(top1["unseen"]["solver_acc"]),
        "top1_unseen_min_regret": float(top1["unseen"]["min_regret"]),
        "default_unseen_min_regret": float(default_entry["unseen"]["min_regret"]),
        "top1_unseen_delta_vs_default": float(top1["unseen"]["min_regret"] - default_entry["unseen"]["min_regret"]),
        "top1_confirm_solver_acc": float(top1["confirm"]["solver_acc"]),
        "top1_confirm_min_regret": float(top1["confirm"]["min_regret"]),
        "default_confirm_min_regret": float(default_entry["confirm"]["min_regret"]),
        "top1_confirm_delta_vs_default": float(top1["confirm"]["min_regret"] - default_entry["confirm"]["min_regret"]),
        "top1_combined_solver_acc": float(top1["combined"]["solver_acc"]),
        "top1_combined_min_regret": float(top1["combined"]["min_regret"]),
        "default_combined_min_regret": float(default_entry["combined"]["min_regret"]),
        "top1_combined_delta_vs_default": float(
            top1["combined"]["min_regret"] - default_entry["combined"]["min_regret"]
        ),
        "all_evolved_solvable_unseen": all(bool(e["unseen"]["feasible"]) for e in evolved_entries),
        "all_evolved_solvable_confirm": all(bool(e["confirm"]["feasible"]) for e in evolved_entries),
        "all_evolved_solvable_combined": all(bool(e["combined"]["feasible"]) for e in evolved_entries),
    }

    doc = sanitize_json(
        {
            "schema_version": "1.0",
            "source_run_dir": rel_posix(rdir),
            "source_hof": rel_posix(hpath),
            "source_model_id": source_meta.get("model_id"),
            "source_commit": source_meta.get("commit") or git_sha(),
            "eval_commit": git_sha(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": clean_str(command_str),
            "fake_env": bool(fake),
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "fitness_mode": fitness_mode,
            "min_solver_acc": acc_floor,
            "investigators": ["solver", *[k for k, _, _, _ in INVESTIGATOR_SPECS]],
            "splits": {
                "unseen_seeds": unseen_list,
                "confirm_seeds": confirm_list,
                "combined_seeds": combined_list,
            },
            "baseline_solver": {
                "unseen": unseen_base,
                "confirm": confirm_base,
                "combined": combined_base,
            },
            "default_mole": default_entry,
            "evolved_strategies": evolved_entries,
            "summary": summary,
        }
    )

    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    md_path.write_text(build_holdout_summary_md(doc), encoding="utf-8")
    return doc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scripts/eval_forge_holdout.py")
    ap.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    ap.add_argument("--hof", default=None)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--unseen-seeds", default="20-29")
    ap.add_argument("--confirm-seeds", default="5020-5039")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--min-solver-acc", type=float, default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--fake", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if argv is None:
        prog_path = Path(sys.argv[0]).resolve()
        rel_prog = prog_path.relative_to(ROOT).as_posix() if prog_path.is_relative_to(ROOT) else Path(sys.argv[0]).as_posix()
        cmd_tokens = [rel_prog, *sys.argv[1:]]
    else:
        cmd_tokens = ["scripts/eval_forge_holdout.py", *argv]
    command_str = " ".join(shlex.quote(x) for x in cmd_tokens)

    doc = evaluate_holdout(
        run_dir=a.run_dir,
        hof_path=a.hof,
        top_k=a.top_k,
        tier=a.tier,
        unseen_seeds=a.unseen_seeds,
        confirm_seeds=a.confirm_seeds,
        workers=a.workers,
        min_solver_acc=a.min_solver_acc,
        fake=a.fake,
        out_json=a.out_json,
        out_md=a.out_md,
        command_str=command_str,
    )
    print(
        json.dumps(
            {
                "run_dir": doc["source_run_dir"],
                "n_evolved_evaluated": doc["summary"]["n_evolved_evaluated"],
                "top1_unseen_solver_acc": doc["summary"]["top1_unseen_solver_acc"],
                "top1_unseen_min_regret": doc["summary"]["top1_unseen_min_regret"],
                "top1_confirm_solver_acc": doc["summary"]["top1_confirm_solver_acc"],
                "top1_confirm_min_regret": doc["summary"]["top1_confirm_min_regret"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
