from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from canary.agents.mole_arena import LLMMole
from canary.agents.runlog import git_sha
from canary.env import Env
from canary.gemini.ledger import LedgeredClient, lab_client
from canary.llm import StubClient, default_gemini_model
from canary.llm.pricing import cost
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy

DEFAULT_OUT = "results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0"
MOLE_FEATURE = "clash_mole"
INVESTIGATOR_FEATURE = "clash_investigator"

STUB_INVESTIGATOR_SCRIPT = [
    {"tool_calls": [{"name": "status", "args": {}}]},
    {"tool_calls": [{"name": "list_employees", "args": {}}]},
    {"tool_calls": [{"name": "plant_canary", "args": {"doc_title": "Q3 Audit Draft", "assignment": {"e00": "A", "e01": "B", "e02": "C"}}}]},
    {"tool_calls": [{"name": "advance_day", "args": {}}]},
    {"tool_calls": [{"name": "check_leak_feed", "args": {}}]},
    {"tool_calls": [{"name": "advance_day", "args": {}}]},
    {"tool_calls": [{"name": "accuse", "args": {"employee": "e00"}}]},
]


def empty_usage() -> dict[str, Any]:
    return {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}


def sum_usage(*items: dict[str, Any]) -> dict[str, Any]:
    out = empty_usage()
    for it in items:
        for k in ("calls", "in", "out", "thinking", "cached"):
            out[k] += int(it.get(k, 0) or 0)
        out["cost_usd"] = round(out["cost_usd"] + float(it.get("cost_usd", 0.0) or 0.0), 6)
        out["latency_s"] = round(out["latency_s"] + float(it.get("latency_s", 0.0) or 0.0), 3)
    return out


def _meta_int(obj: Any, attr: str) -> int:
    if obj is None:
        return 0
    val = obj.get(attr, 0) if isinstance(obj, dict) else getattr(obj, attr, 0)
    return val if isinstance(val, int) else 0


class UsageTracker:
    def __init__(self, inner: Any):
        self.inner = inner
        self.usage = empty_usage()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages: list[dict], **kw: Any) -> Any:
        t0 = time.time()
        resp = self.inner.chat(messages, **kw)
        dt_s = time.time() - t0
        um = getattr(resp.raw, "usage_metadata", None) if getattr(resp, "raw", None) is not None else None
        if um is not None:
            tin = _meta_int(um, "prompt_token_count")
            tout = _meta_int(um, "candidates_token_count")
            thinking = _meta_int(um, "thoughts_token_count")
            cached = _meta_int(um, "cached_content_token_count")
            c = cost(self.inner.model, tin, tout + thinking, cached)
            usd = float(c.get("cost_usd_est", c.get("cost_usd", 0.0)) or 0.0)
        else:
            u = getattr(resp, "usage", None) or {}
            tin = int(u.get("in", 0) or 0)
            tout = int(u.get("out", 0) or 0)
            thinking = int(u.get("thinking", 0) or 0)
            cached = int(u.get("cached_in", u.get("cached", 0)) or 0)
            usd = float(u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0)
        self.usage["calls"] += 1
        self.usage["in"] += tin
        self.usage["out"] += tout
        self.usage["thinking"] += thinking
        self.usage["cached"] += cached
        self.usage["cost_usd"] = round(self.usage["cost_usd"] + usd, 6)
        self.usage["latency_s"] = round(self.usage["latency_s"] + dt_s, 3)
        return resp


def normalize_spec(spec: str) -> tuple[str, str]:
    if spec in ("gemini", "gemini:"):
        model = default_gemini_model()
        return f"gemini:{model}", model
    provider, sep, model = spec.partition(":")
    if provider == "gemini" and model:
        return spec, model
    if provider == "stub":
        return spec, spec
    return spec, model or provider


def build_ledgered_client(spec: str, feature: str, run_id: str, meta: dict[str, Any],
                          thinking_level: str | None = None) -> LedgeredClient:
    if spec == "stub" and feature == INVESTIGATOR_FEATURE:
        return LedgeredClient(StubClient(script=list(STUB_INVESTIGATOR_SCRIPT)), feature=feature,
                              run_id=run_id, meta=meta)
    kw: dict[str, Any] = {}
    if thinking_level and spec.startswith("gemini"):
        kw["thinking_level"] = thinking_level
    return lab_client(spec, feature=feature, run_id=run_id, meta=meta, **kw)


def clean_md(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(str(text).replace("\u2014", "-").replace("\u2013", "-").replace("|", "/").split())


def format_summary(meta: dict[str, Any], clash_mole_log: list[dict], solver_mole_log: list[dict]) -> str:
    u = meta["usage"]
    inv_u = u[INVESTIGATOR_FEATURE]
    mole_u = u[MOLE_FEATURE]
    mole_inv_u = u["clash_mole_vs_investigator"]
    mole_sol_u = u["clash_mole_vs_solver"]
    lines = [
        "# Head-to-Head Adversarial Clash Summary",
        "",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model ID: `{meta['model_id']}` (`{meta['llm']}`)",
        f"- Canary Tiers Version: `{meta['tiers_version']}`",
        f"- Scenario: tier `{meta['tier']}`, seed `{meta['seed']}`",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        "",
        "## Episode Outcomes",
        "",
        "| Matchup | Investigator | Mole | Score | Correct | Accused | Final Day | End Reason | Steps | Mole Leaks | Mole Frames |",
        "| --- | --- | --- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: |",
        (
            f"| Clash | `{meta['llm']}` | `LLMMole({meta['model_id']})` | {meta['investigator_score']:+.3f} | "
            f"{meta['investigator_correct']} | `{meta['investigator_accused']}` | {meta['investigator_final_day']} | "
            f"`{meta['investigator_end_reason']}` | {meta['investigator_steps']} | {meta['mole_clash_leaks']} | "
            f"{meta['mole_clash_frames']} |"
        ),
        (
            f"| Solvability Check | `SolverPolicy` | `LLMMole({meta['model_id']})` | {meta['solver_score']:+.3f} | "
            f"{meta['solver_correct']} | `{meta['solver_accused']}` | {meta['solver_final_day']} | "
            f"`{meta['solver_end_reason']}` | {meta['solver_steps']} | {meta['mole_solver_leaks']} | "
            f"{meta['mole_solver_frames']} |"
        ),
        "",
        f"- Solvable under SolverPolicy: `{meta['solvable']}`",
        f"- Investigator regret vs SolverPolicy: `{meta['regret']:+.3f}`",
        "",
        "## Ledgered Token Usage",
        "",
        "| Feature / Slice | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) | Latency (s) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| `{INVESTIGATOR_FEATURE}` | {inv_u['calls']} | {inv_u['in']} | {inv_u['out']} | "
            f"{inv_u['thinking']} | {inv_u['cached']} | {inv_u['cost_usd']:.6f} | {inv_u['latency_s']:.2f} |"
        ),
        (
            f"| `{MOLE_FEATURE}` (vs investigator) | {mole_inv_u['calls']} | {mole_inv_u['in']} | {mole_inv_u['out']} | "
            f"{mole_inv_u['thinking']} | {mole_inv_u['cached']} | {mole_inv_u['cost_usd']:.6f} | {mole_inv_u['latency_s']:.2f} |"
        ),
        (
            f"| `{MOLE_FEATURE}` (vs solver) | {mole_sol_u['calls']} | {mole_sol_u['in']} | {mole_sol_u['out']} | "
            f"{mole_sol_u['thinking']} | {mole_sol_u['cached']} | {mole_sol_u['cost_usd']:.6f} | {mole_sol_u['latency_s']:.2f} |"
        ),
        (
            f"| `{MOLE_FEATURE}` (total) | {mole_u['calls']} | {mole_u['in']} | {mole_u['out']} | "
            f"{mole_u['thinking']} | {mole_u['cached']} | {mole_u['cost_usd']:.6f} | {mole_u['latency_s']:.2f} |"
        ),
        (
            f"| **Combined Total** | **{u['calls']}** | **{u['in']}** | **{u['out']}** | "
            f"**{u['thinking']}** | **{u['cached']}** | **{u['cost_usd']:.6f}** | **{u['latency_s']:.2f}** |"
        ),
        "",
        "## Adaptive Mole Decisions (Clash Episode)",
        "",
        "| Day | Leak | Frame | Rejected | Reason |",
        "| ---: | --- | --- | --- | --- |",
    ]
    if clash_mole_log:
        for entry in clash_mole_log:
            mv = entry.get("move") or {}
            rej = ", ".join(entry.get("rejected") or []) or "-"
            lines.append(
                f"| {entry.get('day')} | `{mv.get('leak')}` | `{mv.get('frame')}` | "
                f"`{clean_md(rej)}` | {clean_md(entry.get('reason')) or '-'} |"
            )
    else:
        lines.append("| - | - | - | - | No advance_day calls occurred |")
    lines += [
        "",
        "## Adaptive Mole Decisions (Solver Check Episode)",
        "",
        "| Day | Leak | Frame | Rejected | Reason |",
        "| ---: | --- | --- | --- | --- |",
    ]
    if solver_mole_log:
        for entry in solver_mole_log:
            mv = entry.get("move") or {}
            rej = ", ".join(entry.get("rejected") or []) or "-"
            lines.append(
                f"| {entry.get('day')} | `{mv.get('leak')}` | `{mv.get('frame')}` | "
                f"`{clean_md(rej)}` | {clean_md(entry.get('reason')) or '-'} |"
            )
    else:
        lines.append("| - | - | - | - | No advance_day calls occurred |")
    return "\n".join(lines) + "\n"


def run_clash(spec: str = "gemini:gemini-4-carbon", tier: str = "medium", seed: int = 0,
              out_dir: str | Path = DEFAULT_OUT, thinking_level: str | None = None,
              client_builder: Callable[..., Any] | None = None) -> dict[str, Any]:
    os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "10")
    spec, model_id = normalize_spec(spec)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = f"clash:{model_id}:{tier}:seed{seed}:{int(time.time() * 1000)}:{os.getpid()}"
    base_meta = {"role": "adaptive_mole", "subrole": "carbon_vs_carbon_clash", "tier": tier, "seed": seed}
    builder = client_builder or build_ledgered_client

    mole_base_client = builder(spec, MOLE_FEATURE, run_id, base_meta, thinking_level)
    inv_base_client = builder(spec, INVESTIGATOR_FEATURE, run_id, base_meta, thinking_level)

    clash_mole_tracker = UsageTracker(mole_base_client)
    inv_tracker = UsageTracker(inv_base_client)

    clash_mole = LLMMole(clash_mole_tracker)
    clash_env = Env(tier=tier, seed=seed, mole_strategy=clash_mole)
    investigator = LLMPolicy(spec, client=inv_tracker)
    clash_res = run_episode(clash_env, investigator, investigator.name)
    investigator._feed_results(clash_env.history)

    solver_mole_tracker = UsageTracker(mole_base_client)
    solver_mole = LLMMole(solver_mole_tracker)
    solver_env = Env(tier=tier, seed=seed, mole_strategy=solver_mole)
    solver_policy = SolverPolicy()
    solver_res = run_episode(solver_env, solver_policy, solver_policy.name)

    inv_usage = dict(inv_tracker.usage)
    mole_inv_usage = dict(clash_mole_tracker.usage)
    mole_sol_usage = dict(solver_mole_tracker.usage)
    mole_usage = sum_usage(mole_inv_usage, mole_sol_usage)
    combined_usage = sum_usage(inv_usage, mole_usage)

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = git_sha()
    meta = {
        "role": "adaptive_mole",
        "subrole": "carbon_vs_carbon_clash",
        "model_id": model_id,
        "llm": spec,
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seed": seed,
        "commit": commit,
        "timestamp": timestamp,
        "run_id": run_id,
        "investigator_score": clash_res.score,
        "investigator_correct": clash_res.correct,
        "investigator_accused": clash_res.accused,
        "investigator_final_day": clash_res.final_day,
        "investigator_end_reason": clash_res.end_reason,
        "investigator_steps": len(clash_res.steps),
        "solver_score": solver_res.score,
        "solver_correct": solver_res.correct,
        "solver_accused": solver_res.accused,
        "solver_final_day": solver_res.final_day,
        "solver_end_reason": solver_res.end_reason,
        "solver_steps": len(solver_res.steps),
        "solvable": bool(solver_res.correct and solver_res.score > 0),
        "regret": round(solver_res.score - clash_res.score, 6),
        "mole_clash_days": len(clash_mole.log),
        "mole_clash_leaks": sum(1 for x in clash_mole.log if (x.get("move") or {}).get("leak")),
        "mole_clash_frames": sum(1 for x in clash_mole.log if (x.get("move") or {}).get("frame")),
        "mole_clash_errors": sum(1 for x in clash_mole.log if x.get("error")),
        "mole_solver_days": len(solver_mole.log),
        "mole_solver_leaks": sum(1 for x in solver_mole.log if (x.get("move") or {}).get("leak")),
        "mole_solver_frames": sum(1 for x in solver_mole.log if (x.get("move") or {}).get("frame")),
        "mole_solver_errors": sum(1 for x in solver_mole.log if x.get("error")),
        "usage": {
            **combined_usage,
            INVESTIGATOR_FEATURE: inv_usage,
            MOLE_FEATURE: mole_usage,
            "clash_mole_vs_investigator": mole_inv_usage,
            "clash_mole_vs_solver": mole_sol_usage,
        },
    }

    investigator_payload = {
        "tier": clash_res.tier,
        "seed": clash_res.seed,
        "agent": clash_res.agent,
        "model_id": model_id,
        "score": clash_res.score,
        "accused": clash_res.accused,
        "correct": clash_res.correct,
        "final_day": clash_res.final_day,
        "end_reason": clash_res.end_reason,
        "usage": inv_usage,
        "steps": [dataclasses.asdict(s) for s in clash_res.steps],
        "transcript": investigator.transcript,
    }

    mole_payload = {
        "tier": tier,
        "seed": seed,
        "model_id": model_id,
        "log": clash_mole.log,
        "clash_mole_log": clash_mole.log,
        "solver_mole_log": solver_mole.log,
        "usage": {
            MOLE_FEATURE: mole_usage,
            "clash_mole_vs_investigator": mole_inv_usage,
            "clash_mole_vs_solver": mole_sol_usage,
        },
    }

    solver_payload = {
        "tier": solver_res.tier,
        "seed": solver_res.seed,
        "investigator": solver_res.agent,
        "mole": solver_mole.name,
        "mole_model_id": model_id,
        "score": solver_res.score,
        "accused": solver_res.accused,
        "correct": solver_res.correct,
        "final_day": solver_res.final_day,
        "end_reason": solver_res.end_reason,
        "solvable": bool(solver_res.correct and solver_res.score > 0),
        "steps": [dataclasses.asdict(s) for s in solver_res.steps],
        "belief_trace": solver_policy.trace,
        "mole_log": solver_mole.log,
        "mole_usage": mole_sol_usage,
    }

    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")
    (out / "investigator_transcript.json").write_text(json.dumps(investigator_payload, indent=2, default=str) + "\n")
    (out / "mole_log.json").write_text(json.dumps(mole_payload, indent=2, default=str) + "\n")
    (out / "solver_check.json").write_text(json.dumps(solver_payload, indent=2, default=str) + "\n")
    (out / "summary.md").write_text(format_summary(meta, clash_mole.log, solver_mole.log))
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/run_gemini_clash.py")
    ap.add_argument("--llm", default="gemini:gemini-4-carbon")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--thinking-level", default=None)
    args = ap.parse_args(argv)
    meta = run_clash(spec=args.llm, tier=args.tier, seed=args.seed, out_dir=args.out,
                     thinking_level=args.thinking_level)
    print(json.dumps({
        "out": str(args.out),
        "model_id": meta["model_id"],
        "investigator_score": meta["investigator_score"],
        "investigator_correct": meta["investigator_correct"],
        "solver_score": meta["solver_score"],
        "solver_correct": meta["solver_correct"],
        "calls": meta["usage"]["calls"],
        "cost_usd": meta["usage"]["cost_usd"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
