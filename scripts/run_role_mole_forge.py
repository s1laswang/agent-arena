from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.runlog import git_sha, parse_seeds
from canary.forge import evolve
from canary.forge.fitness import (
    ClassFactory,
    default_investigators,
    default_solver_factory,
    evaluate,
    fake_factory,
    fake_runner,
    real_runner,
    solver_baseline,
    tier_defaults,
)
from canary.forge.mutate import LLMMutator, default_strategy_json, validate_strategy
from canary.gemini import lab_client, ledger_path, read_ledger
from canary.llm.base import is_retryable
from canary.rules import TIERS_VERSION

DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "mole-forge-carbon-v14"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def clean_str(val: str) -> str:
    return val.replace(EM_DASH, "-").replace(EN_DASH, "-")


def normalize_llm_spec(spec: str) -> str:
    spec = spec.strip()
    if spec == "stub" or spec.startswith("stub:"):
        return spec
    if ":" not in spec:
        return f"gemini:{spec}"
    return spec


def model_id_from_client(spec: str, client: Any) -> str:
    provider, _, model_part = spec.partition(":")
    return getattr(client, "model", "") or model_part or provider


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


class RetryingForgeClient:
    def __init__(self, inner: Any, sleep_fn=time.sleep):
        self.inner = inner
        self.sleep_fn = sleep_fn

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        is_gemini = getattr(self.inner, "provider", "") == "gemini"
        max_attempts = max(1, int(os.environ.get("CANARY_LLM_MAX_RETRIES", "10"))) if is_gemini else 1
        resp = None
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                resp = self.inner.chat(messages, **kw)
            except Exception as exc:
                if not is_gemini or attempt + 1 >= max_attempts or not is_retryable(exc):
                    raise
                last_exc = exc
                self.sleep_fn(min(1.5 * (2 ** attempt), 15.0))
                continue
            txt = getattr(resp, "text", None)
            if isinstance(txt, str):
                resp.text = clean_str(txt)
            if not (is_gemini and kw.get("response_schema") is not None):
                return resp
            raw_txt = (getattr(resp, "text", None) or "").strip()
            if raw_txt:
                try:
                    parsed = json.loads(raw_txt)
                    if isinstance(parsed, dict) and isinstance(parsed.get("children"), list) and parsed["children"]:
                        return resp
                except json.JSONDecodeError:
                    pass
            if attempt + 1 < max_attempts:
                self.sleep_fn(min(1.5 * (2 ** attempt), 15.0))
        if resp is None and last_exc is not None:
            raise last_exc
        return resp


class ForgeLLMMutator(LLMMutator):
    def __init__(self, client: Any, seed: int = 0, min_batch: int = 4):
        super().__init__(client, seed=seed)
        self.min_batch = min_batch

    def prompt(self, parents: list[dict], n: int) -> list[dict]:
        return super().prompt(parents, max(n, self.min_batch))


def stub_children_script(rounds: int = 24) -> list[dict]:
    candidates = [
        {
            "rationale": "frame decoy while leaking oldest docs when tiny canaries appear",
            "rules": [
                {
                    "if": [["min_recipient_count", "<=", "2"], ["max_recipient_count", ">=", "4"]],
                    "then": {"leak": "oldest", "frame": "decoy"},
                }
            ],
            "default": {"leak": "random_seeded", "frame": "decoy"},
        },
        {
            "rationale": "shift blame to restricted peers and delay narrow leaks",
            "rules": [
                {
                    "if": [["n_restricted_colleagues", ">=", "1"]],
                    "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                },
                {
                    "if": [["days_since_last_leak", ">=", "2"]],
                    "then": {"leak": "oldest", "frame": "decoy"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "decoy"},
        },
        {
            "rationale": "avoid low recipient traps and frame random peers",
            "rules": [
                {
                    "if": [["recent_low_recipient_docs", ">=", "1"], ["max_recipient_count", ">=", "5"]],
                    "then": {"leak": "newest", "frame": "random_peer"},
                }
            ],
            "default": {"leak": "random_seeded", "frame": "decoy"},
        },
        {
            "rationale": "leak older documents early with decoy framing",
            "rules": [
                {
                    "if": [["day", "<=", "4"]],
                    "then": {"leak": "oldest", "frame": "decoy"},
                }
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
    ]
    out = []
    for i in range(rounds):
        k = i % len(candidates)
        out.append({"json": {"children": candidates[k:] + candidates[:k]}})
    return out


def build_generations_doc(
    log_lines: list[dict],
    model_id: str,
    tier: str,
    dev_seeds: list[int],
    fitness_mode: str,
    min_solver_acc: float,
    baseline: dict,
) -> dict:
    default_member = log_lines[0]["population"][0]
    default_eval = default_member["eval"]
    default_dev = {
        "fitness": default_member["fitness"],
        "solver_score": default_eval.get("solver_score"),
        "solver_acc": default_eval.get("solver_acc"),
        "per_investigator": default_eval.get("per_investigator", {}),
    }
    hof_best = None
    gens_out = []
    for row in log_lines:
        bf = row.get("best_fitness")
        if bf is not None and (hof_best is None or bf > hof_best):
            hof_best = bf
        pop = row.get("population", [])
        feas_count = sum(1 for p in pop if p.get("fitness") is not None)
        best_eval = row.get("best_eval", {})
        gens_out.append(
            {
                "gen": row["gen"],
                "best_fitness": bf,
                "hof_best_fitness": hof_best,
                "mean_fitness": row.get("mean_fitness"),
                "feasible_share": row.get("feasible_share"),
                "feasible_count": feas_count,
                "pop_size": len(pop),
                "best_solver_score": best_eval.get("solver_score"),
                "best_solver_acc": best_eval.get("solver_acc"),
                "best_per_investigator": best_eval.get("per_investigator", {}),
                "best_strategy": row.get("best_strategy"),
                "seconds": row.get("seconds"),
            }
        )
    return sanitize_json(
        {
            "model_id": model_id,
            "tier": tier,
            "dev_seeds": dev_seeds,
            "fitness_mode": fitness_mode,
            "min_solver_acc": min_solver_acc,
            "baseline_solver": baseline,
            "default_mole_dev": default_dev,
            "generations": gens_out,
        }
    )


def plot_generations(generations_doc: dict, fresh_top: dict, fresh_default: dict, out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gens = generations_doc["generations"]
    xs = [g["gen"] for g in gens]
    hof_ys = [g["hof_best_fitness"] if g["hof_best_fitness"] is not None else float("nan") for g in gens]
    best_ys = [g["best_fitness"] if g["best_fitness"] is not None else float("nan") for g in gens]
    mean_ys = [g["mean_fitness"] if g["mean_fitness"] is not None else float("nan") for g in gens]
    default_fit = generations_doc["default_mole_dev"].get("fitness")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 4.6))

    ax1.plot(xs, hof_ys, marker="o", linewidth=2.2, color="#8e1b1b", label="HoF best fitness (min regret)")
    if best_ys != hof_ys:
        ax1.plot(xs, best_ys, marker="s", linestyle="-.", linewidth=1.4, color="#d9603b", label="Gen best fitness")
    ax1.plot(xs, mean_ys, marker="^", linestyle="--", linewidth=1.6, color="#1f4fbf", label="Gen feasible mean")
    if default_fit is not None:
        ax1.axhline(default_fit, linestyle=":", linewidth=1.5, color="#444444", label=f"Default mole ({default_fit:.3f})")

    finite_ax1 = [v for v in (hof_ys + best_ys + mean_ys) if math.isfinite(v)]
    if default_fit is not None and math.isfinite(default_fit):
        finite_ax1.append(float(default_fit))
    if finite_ax1:
        ylo, yhi = min(finite_ax1), max(finite_ax1)
        yspan = max(0.06, yhi - ylo)
        ax1.set_ylim(ylo - 0.14 * yspan, yhi + 0.28 * yspan)

    for g in gens:
        y = g["hof_best_fitness"]
        acc = g.get("best_solver_acc")
        if y is not None and acc is not None:
            ax1.annotate(
                f"{y:.3f}\n(acc {acc:.0%})",
                (g["gen"], y),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=8,
            )
    ax1.set_xticks(xs, [f"Gen {x}" for x in xs])
    ax1.set_xlabel("Generation")
    ax1.set_ylabel("Fitness (solver score minus strongest investigator)")
    ax1.set_title(f"Mole Forge ({generations_doc['model_id']}, {generations_doc['tier']} dev)", pad=10)
    ax1.grid(True, alpha=0.25)
    ax1.legend(fontsize=8, loc="lower right")

    agents = ["solver", "grok_tactics", "obvious_heuristic"]
    labels = ["SolverPolicy", "GrokTactics", "ObviousHeuristic"]
    def_scores = [
        fresh_default["solver_score"],
        fresh_default["per_investigator"]["grok_tactics"]["score"],
        fresh_default["per_investigator"]["obvious_heuristic"]["score"],
    ]
    top_scores = [
        fresh_top["solver_score"],
        fresh_top["per_investigator"]["grok_tactics"]["score"],
        fresh_top["per_investigator"]["obvious_heuristic"]["score"],
    ]
    pos = list(range(len(agents)))
    width = 0.36
    bars_def = ax2.bar([p - width / 2 for p in pos], def_scores, width=width, color="#9aa5b1", label="Default mole")
    bars_top = ax2.bar([p + width / 2 for p in pos], top_scores, width=width, color="#8e1b1b", label="Top evolved mole")
    ax2.axhline(0.0, color="#666666", linewidth=0.8)

    all_scores = [float(v) for v in (def_scores + top_scores + [0.0]) if math.isfinite(v)]
    if all_scores:
        slo, shi = min(all_scores), max(all_scores)
        sspan = max(0.25, shi - slo)
        ax2.set_ylim(slo - 0.16 * sspan, shi + 0.18 * sspan)

    for bar in list(bars_def) + list(bars_top):
        h = bar.get_height()
        offset = 5 if h >= 0 else -13
        ax2.annotate(
            f"{h:+.2f}",
            (bar.get_x() + bar.get_width() / 2, h),
            textcoords="offset points",
            xytext=(0, offset),
            ha="center",
            fontsize=8,
        )
    solver_acc = fresh_top["solver_acc"]
    ax2.set_xticks(pos, labels, rotation=10)
    ax2.set_ylabel("Mean episode score")
    ax2.set_title(f"Fresh Seeds Confirmation (solver acc={solver_acc:.0%})", pad=10)
    ax2.grid(True, axis="y", alpha=0.25)
    ax2.legend(fontsize=8, loc="upper right")

    fig.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_summary_md(meta: dict, generations_doc: dict, hof: list[dict]) -> str:
    fresh_top = meta["fresh_confirmation"]["top_hof"]
    fresh_def = meta["fresh_confirmation"]["default_mole"]
    u = meta["usage"]
    def_fit_txt = "n/a" if meta["default_dev_fitness"] is None else f"{meta['default_dev_fitness']:.4f}"
    lines = [
        "# Role 2 (adaptive_mole): Mole Forge Evolution Report",
        "",
        f"- **Model:** `{meta['model_id']}` (`feature=\"mole_forge\"` via `canary.gemini.lab_client`)",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Tier:** `{meta['tier']}` (`{meta['tiers_version']}`, dev seeds `{meta['dev_seeds'][0]}..{meta['dev_seeds'][-1]}`, fresh seeds `{meta['fresh_seeds'][0]}..{meta['fresh_seeds'][-1]}`)",
        f"- **Valid LLM DSL children:** `{meta['n_valid_llm_children']}` (invalid dropped: `{meta['n_invalid_llm_children']}`)",
        f"- **Best dev fitness (min regret):** `{meta['best_fitness']:.4f}` (default mole dev fitness: `{def_fit_txt}`)",
        f"- **Fresh 20-seed SolverPolicy accuracy:** `{meta['fresh_solver_accuracy']:.2%}` (constraint `>= {meta['min_solver_acc']:.0%}`)",
        f"- **Fresh 20-seed min regret vs strongest investigator:** `{meta['fresh_min_regret']:+.4f}` (default mole: `{meta['default_fresh_min_regret']:+.4f}`)",
        f"- **Gemini usage:** `{u['calls']}` calls, `{u['in']}` in tokens, `{u['out']}` out tokens (thinking `{u['thinking']}`), `${u['cost_usd']:.4f}`",
        "",
        "## Evolution Across Generations (Dev Seeds)",
        "",
        "| Gen | Best Fitness | HoF Best | Feasible Mean | Feasible | Best Solver Score | Best Solver Acc | Seconds |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for g in generations_doc["generations"]:
        bf = "n/a" if g["best_fitness"] is None else f"{g['best_fitness']:.4f}"
        hb = "n/a" if g["hof_best_fitness"] is None else f"{g['hof_best_fitness']:.4f}"
        mf = "n/a" if g["mean_fitness"] is None else f"{g['mean_fitness']:.4f}"
        bs = "n/a" if g["best_solver_score"] is None else f"{g['best_solver_score']:+.4f}"
        ba = "n/a" if g["best_solver_acc"] is None else f"{g['best_solver_acc']:.2%}"
        fc = f"{g['feasible_count']}/{g['pop_size']}"
        lines.append(f"| {g['gen']} | {bf} | {hb} | {mf} | {fc} | {bs} | {ba} | {g['seconds']:.2f}s |")

    lines += [
        "",
        "## Fresh Seeds Confirmation (Seeds 5000..5019)",
        "",
        "| Investigator | Default Mole Score | Default Mole Acc | Evolved Mole Score | Evolved Mole Acc | Evolved Regret vs Solver |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| SolverPolicy | {fresh_def['solver_score']:+.4f} | {fresh_def['solver_acc']:.2%} "
            f"| {fresh_top['solver_score']:+.4f} | {fresh_top['solver_acc']:.2%} | +0.0000 |"
        ),
    ]
    for inv_key, inv_label in (("grok_tactics", "GrokTactics"), ("obvious_heuristic", "ObviousHeuristic")):
        d_inv = fresh_def["per_investigator"][inv_key]
        t_inv = fresh_top["per_investigator"][inv_key]
        lines.append(
            f"| {inv_label} | {d_inv['score']:+.4f} | {d_inv['acc']:.2%} "
            f"| {t_inv['score']:+.4f} | {t_inv['acc']:.2%} | {t_inv['regret']:+.4f} |"
        )

    lines += [
        "",
        f"Top Hall-of-Fame strategy (`rank=1`, `{len(hof)}` feasible strategies total):",
        "",
        "```json",
        json.dumps(meta["top_strategy"], indent=2),
        "```",
        "",
    ]
    return clean_str("\n".join(lines))


def run_forge(
    llm: str = "gemini:gemini-4-carbon",
    tier: str = "hard",
    gens: int = 3,
    pop: int = 4,
    children: int = 4,
    elite: int = 1,
    seeds: str = "4000-4009",
    fresh_seeds: str = "5000-5019",
    workers: int = 10,
    seed: int = 0,
    hof_k: int = 20,
    min_solver_acc: float | None = None,
    out: str | Path = DEFAULT_OUT,
    fake: bool = False,
    command_str: str = "",
    client: Any = None,
) -> dict:
    spec = normalize_llm_spec(llm)
    dev_seed_list = parse_seeds(seeds)
    fresh_seed_list = parse_seeds(fresh_seeds)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    td = tier_defaults(tier)
    fitness_mode = td["fitness_mode"]
    acc_floor = td["min_solver_acc"] if min_solver_acc is None else min_solver_acc

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    run_id = f"mole-forge-{stamp}-{seed}"
    led_file = ledger_path()

    if client is None:
        raw_client = lab_client(spec, feature="mole_forge", run_id=run_id)
        if spec == "stub" and hasattr(raw_client, "inner") and not getattr(raw_client.inner, "script", None):
            raw_client.inner.script = stub_children_script(max(24, gens * 4))
        wrapped_client = RetryingForgeClient(raw_client)
    else:
        wrapped_client = client if isinstance(client, RetryingForgeClient) else RetryingForgeClient(client)

    model_id = model_id_from_client(spec, wrapped_client)
    mutator = ForgeLLMMutator(wrapped_client, seed=seed, min_batch=max(1, children))
    effective_elite = max(0, min(elite, pop - 1))

    if fake:
        dev_investigators = None
    else:
        dev_investigators = {
            **default_investigators(),
            "grok_tactics": ClassFactory("canary.baselines", "GrokTactics"),
            "obvious_heuristic": ClassFactory("canary.baselines", "ObviousHeuristic"),
        }

    with tempfile.TemporaryDirectory(prefix="mole_forge_") as tmp:
        work_dir = Path(tmp)
        with patch.object(evolve, "get_mutator", side_effect=lambda _s, seed=0: mutator):
            res = evolve.run(
                mutator_spec=spec,
                tier=tier,
                pop_size=pop,
                gens=gens,
                seeds=dev_seed_list,
                workers=workers,
                out=work_dir,
                fake=fake,
                seed=seed,
                elite=effective_elite,
                hof_k=hof_k,
                investigators=dev_investigators,
                fitness_mode=fitness_mode,
                min_solver_acc=acc_floor,
            )
        if mutator.n_valid <= 0:
            raise RuntimeError(
                f"LLMMutator ({model_id}) produced 0 valid DSL children (n_invalid={mutator.n_invalid})"
            )
        hof = res["hof"]
        if not hof:
            raise RuntimeError("Mole Forge produced an empty hall of fame")

        log_lines = [
            json.loads(line)
            for line in (work_dir / "log.jsonl").read_text().splitlines()
            if line.strip()
        ]
        hof_text = clean_str((work_dir / "hall_of_fame.jsonl").read_text())
        (out_dir / "hall_of_fame.jsonl").write_text(hof_text)

    if fake:
        runner = fake_runner
        solver_fac = fake_factory
        fresh_investigators = {
            "grok_tactics": fake_factory,
            "obvious_heuristic": fake_factory,
        }
    else:
        runner = real_runner
        solver_fac = default_solver_factory()
        fresh_investigators = {
            "grok_tactics": ClassFactory("canary.baselines", "GrokTactics"),
            "obvious_heuristic": ClassFactory("canary.baselines", "ObviousHeuristic"),
        }

    fresh_base = solver_baseline(solver_fac, fresh_seed_list, tier, runner, workers)
    default_strat = validate_strategy(default_strategy_json())
    fresh_default = evaluate(
        default_strat,
        fresh_investigators,
        solver_fac,
        fresh_seed_list,
        tier,
        runner=runner,
        workers=workers,
        baseline=fresh_base,
        fitness_mode=fitness_mode,
        min_solver_acc=acc_floor,
    )
    top_strat = hof[0]["strategy_json"]
    fresh_top = evaluate(
        top_strat,
        fresh_investigators,
        solver_fac,
        fresh_seed_list,
        tier,
        runner=runner,
        workers=workers,
        baseline=fresh_base,
        fitness_mode=fitness_mode,
        min_solver_acc=acc_floor,
    )

    generations_doc = build_generations_doc(
        log_lines=log_lines,
        model_id=model_id,
        tier=tier,
        dev_seeds=dev_seed_list,
        fitness_mode=fitness_mode,
        min_solver_acc=acc_floor,
        baseline=res["baseline"],
    )
    (out_dir / "generations.json").write_text(
        json.dumps(generations_doc, indent=2, allow_nan=False) + "\n"
    )
    plot_generations(generations_doc, fresh_top, fresh_default, out_dir / "generations.png")

    ledger_rows = []
    if led_file.exists():
        ledger_rows = [r for r in read_ledger([led_file]) if r.get("run_id") == run_id]
    total_u = getattr(wrapped_client, "total_usage", {}) or {}
    if ledger_rows:
        ok_rows = [r for r in ledger_rows if r.get("ok", True)]
        usage = {
            "calls": int(len(ok_rows) or len(ledger_rows)),
            "in": int(sum(r.get("in", 0) for r in ledger_rows)),
            "out": int(sum(r.get("out", 0) for r in ledger_rows)),
            "thinking": int(sum(r.get("thinking", 0) for r in ledger_rows)),
            "cached": int(sum(r.get("cached", 0) for r in ledger_rows)),
            "cost_usd": round(float(sum(r.get("cost_usd", 0.0) for r in ledger_rows)), 6),
            "latency_s": round(float(sum(r.get("latency_s", 0.0) for r in ledger_rows)), 3),
            "ledger_run_id": run_id,
        }
    else:
        usage = {
            "calls": int(total_u.get("calls", 0)),
            "in": int(total_u.get("in", 0)),
            "out": int(total_u.get("out", 0)),
            "thinking": 0,
            "cached": 0,
            "cost_usd": round(float(total_u.get("cost_usd", 0.0)), 6),
            "latency_s": 0.0,
            "ledger_run_id": run_id,
        }

    provider_settings = wrapped_client.settings() if hasattr(wrapped_client, "settings") else {}
    default_dev_fit = generations_doc["default_mole_dev"]["fitness"]
    meta = sanitize_json(
        {
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "model_id": model_id,
            "commit": git_sha(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "command": clean_str(command_str),
            "usage": usage,
            "n_valid_llm_children": int(mutator.n_valid),
            "n_invalid_llm_children": int(mutator.n_invalid),
            "n_samples": int(mutator.n_valid),
            "best_fitness": float(hof[0]["fitness"]),
            "default_dev_fitness": float(default_dev_fit) if default_dev_fit is not None else None,
            "fresh_solver_accuracy": float(fresh_top["solver_acc"]),
            "fresh_min_regret": float(fresh_top["min_regret"]),
            "default_fresh_min_regret": float(fresh_default["min_regret"]),
            "fake_env": bool(fake),
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "gens": gens,
            "pop_size": pop,
            "requested_children": children,
            "elite": effective_elite,
            "children_per_gen": pop - effective_elite,
            "dev_seeds": dev_seed_list,
            "fresh_seeds": fresh_seed_list,
            "fitness_mode": fitness_mode,
            "min_solver_acc": acc_floor,
            "hof_size": len(hof),
            "top_strategy": top_strat,
            "provider_settings": provider_settings,
            "fresh_confirmation": {
                "top_hof": fresh_top,
                "default_mole": fresh_default,
            },
        }
    )
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, allow_nan=False) + "\n")
    (out_dir / "summary.md").write_text(build_summary_md(meta, generations_doc, hof))
    return meta


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scripts/run_role_mole_forge.py")
    ap.add_argument("--llm", default="gemini:gemini-4-carbon")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--gens", type=int, default=3)
    ap.add_argument("--pop", type=int, default=4)
    ap.add_argument("--children", type=int, default=4)
    ap.add_argument("--elite", type=int, default=1)
    ap.add_argument("--seeds", default="4000-4009")
    ap.add_argument("--fresh-seeds", default="5000-5019")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--hof", type=int, default=20)
    ap.add_argument("--min-solver-acc", type=float, default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--fake", action="store_true")
    return ap


def main(argv: list[str] | None = None, client: Any = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if argv is None:
        prog_path = Path(sys.argv[0]).resolve()
        rel_prog = prog_path.relative_to(ROOT).as_posix() if prog_path.is_relative_to(ROOT) else Path(sys.argv[0]).as_posix()
        cmd_tokens = [rel_prog, *sys.argv[1:]]
    else:
        cmd_tokens = ["scripts/run_role_mole_forge.py", *argv]
    command_str = " ".join(shlex.quote(x) for x in cmd_tokens)
    meta = run_forge(
        llm=a.llm,
        tier=a.tier,
        gens=a.gens,
        pop=a.pop,
        children=a.children,
        elite=a.elite,
        seeds=a.seeds,
        fresh_seeds=a.fresh_seeds,
        workers=a.workers,
        seed=a.seed,
        hof_k=a.hof,
        min_solver_acc=a.min_solver_acc,
        out=a.out,
        fake=a.fake,
        command_str=command_str,
        client=client,
    )
    print(
        json.dumps(
            {
                "out": str(a.out),
                "model_id": meta["model_id"],
                "n_valid_llm_children": meta["n_valid_llm_children"],
                "best_fitness": meta["best_fitness"],
                "fresh_solver_accuracy": meta["fresh_solver_accuracy"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
