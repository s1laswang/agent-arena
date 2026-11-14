from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import random
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents._common import get
from canary.agents.mole_arena import LLMMole, view_to_dict
from canary.baselines import GrokTactics, ObviousHeuristic
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import lab_client
from canary.llm.base import is_retryable
from canary.rules import TIERS_VERSION, tier_params
from canary.solver.policy import SolverPolicy

ROLE = "adaptive_mole"
SUBROLE = "live_arena_mole"
DEFAULT_LLM = "gemini:gemini-4-carbon"
DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "arena-live-carbon-med012"
INVESTIGATOR_ORDER = ("solver", "grok_tactics", "obvious_heuristic")


def clean_text(val: Any) -> Any:
    if isinstance(val, str):
        return val.replace("\u2014", "-").replace("\u2013", "-")
    return val


def model_id_from_spec(llm_spec: str) -> str:
    provider, sep, model = llm_spec.partition(":")
    if sep and model:
        return model
    return provider


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def make_investigators() -> dict[str, Callable[[int], Any]]:
    return {
        "solver": lambda seed: SolverPolicy(adaptive=True, alternate=True, probing=True),
        "grok_tactics": lambda seed: GrokTactics(seed=seed),
        "obvious_heuristic": lambda seed: ObviousHeuristic(seed=seed),
    }


class MeteredMoleClient:
    def __init__(self, inner: Any):
        self.inner = inner
        self.usage_totals: dict[str, Any] = {
            "calls": 0,
            "in": 0,
            "out": 0,
            "thinking": 0,
            "cached": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "latency_s": 0.0,
        }

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def _record_resp(self, resp: Any, elapsed: float) -> None:
        um = getattr(resp.raw, "usage_metadata", None) if getattr(resp, "raw", None) is not None else None
        usage = getattr(resp, "usage", None) or {}
        if um is not None:
            tin = int(getattr(um, "prompt_token_count", 0) or 0)
            tout = int(getattr(um, "candidates_token_count", 0) or 0)
            tthink = int(getattr(um, "thoughts_token_count", 0) or 0)
            tcached = int(getattr(um, "cached_content_token_count", 0) or 0)
        else:
            tin = int(usage.get("in", 0) or 0)
            tout = int(usage.get("out", 0) or 0)
            tthink = int(usage.get("thinking", 0) or 0)
            tcached = int(usage.get("cached", 0) or 0)
        usd = float(usage.get("cost_usd_est", usage.get("cost_usd", 0.0)) or 0.0)
        self.usage_totals["calls"] += 1
        self.usage_totals["in"] += tin
        self.usage_totals["out"] += tout
        self.usage_totals["thinking"] += tthink
        self.usage_totals["cached"] += tcached
        self.usage_totals["total_tokens"] += tin + tout + tthink
        self.usage_totals["cost_usd"] = round(self.usage_totals["cost_usd"] + usd, 6)
        self.usage_totals["latency_s"] = round(self.usage_totals["latency_s"] + elapsed, 3)

    def chat(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        is_gemini = getattr(self.inner, "provider", "") == "gemini"
        max_attempts = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "10")) if is_gemini else 1
        last_exc: Exception | None = None
        for attempt in range(max(1, max_attempts)):
            t0 = time.time()
            try:
                resp = self.inner.chat(messages, **kw)
            except Exception as exc:
                if not is_gemini or attempt + 1 >= max_attempts or not is_retryable(exc):
                    raise
                last_exc = exc
                time.sleep(min(2.0 * (2 ** attempt), 30.0))
                continue
            elapsed = time.time() - t0
            self._record_resp(resp, elapsed)
            txt = getattr(resp, "text", None)
            if is_gemini and kw.get("response_schema") is not None:
                raw_txt = (txt or "").strip()
                if not raw_txt:
                    if attempt + 1 < max_attempts:
                        time.sleep(min(1.5 * (2 ** attempt), 20.0))
                        continue
                else:
                    try:
                        parsed_json = json.loads(raw_txt)
                        if isinstance(parsed_json, dict) and isinstance(parsed_json.get("reason"), str):
                            parsed_json["reason"] = clean_text(parsed_json["reason"])[:280]
                            resp.text = json.dumps(parsed_json)
                    except json.JSONDecodeError:
                        if attempt + 1 < max_attempts:
                            time.sleep(min(1.5 * (2 ** attempt), 20.0))
                            continue
            elif isinstance(txt, str):
                try:
                    parsed_json = json.loads(txt)
                    if isinstance(parsed_json, dict) and isinstance(parsed_json.get("reason"), str):
                        parsed_json["reason"] = clean_text(parsed_json["reason"])[:280]
                        resp.text = json.dumps(parsed_json)
                except Exception:
                    pass
            return resp
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("exhausted retries in MeteredMoleClient.chat")


def build_mole_client(
    llm_spec: str = DEFAULT_LLM,
    run_id: str = "",
    meta: dict[str, Any] | None = None,
    thinking_level: str | None = None,
    client_override: Any = None,
) -> MeteredMoleClient:
    if client_override is not None:
        return MeteredMoleClient(client_override)
    kw: dict[str, Any] = {}
    if thinking_level:
        kw["thinking_level"] = thinking_level
    inner = lab_client(llm_spec, feature=ROLE, run_id=run_id, meta=meta, **kw)
    return MeteredMoleClient(inner)


def serialize_mole_view(view: Any) -> dict[str, Any]:
    raw = view_to_dict(view)
    for extra in ("restricted_peers", "decoy", "can_leak"):
        val = get(view, extra, None)
        if val is not None:
            raw[extra] = list(val) if isinstance(val, tuple) else val
    for d in raw.get("held_docs", []):
        if "title" in d and d["title"] is not None:
            d["title"] = clean_text(d["title"])
    return raw


class LiveArenaMole(LLMMole):
    def __init__(
        self,
        client: Any,
        tier: str = "medium",
        seed: int = 0,
        investigator: str = "",
        mask_doc_ids: bool = True,
        temperature: float = 0.4,
    ):
        super().__init__(client, temperature=temperature)
        p = tier_params(tier)
        self.system = (
            clean_text(self.system).rstrip()
            + f"\nThe episode runs for {p.n_days} days in a {p.n_employees}-employee company. "
            "Your rival rewards every document you leak while avoiding capture: "
            "leak the widest-shared held document whenever at least one held document reaches "
            "broadly (8 or more recipients), go quiet (null) only when all held documents have "
            "suspiciously few recipients or you hold none, and frame a peer employee id to "
            "deflect access-log suspicion. Return JSON with keys leak, frame, and reason "
            "(under 200 characters, ASCII hyphens only)."
        )
        self.tier = tier
        self.seed = seed
        self.investigator = investigator
        self.mask_doc_ids = mask_doc_ids
        self.decisions: list[dict[str, Any]] = []

    def decide(self, view: Any) -> dict[str, Any]:
        raw_view = serialize_mole_view(view)
        alias_to_real: dict[str, str] = {}
        prompt_view = dict(raw_view)
        if self.mask_doc_ids and raw_view.get("held_docs"):
            docs_copy = [dict(d) for d in raw_view["held_docs"]]
            rng = random.Random(f"arena-mask:{self.tier}:{self.seed}:{self.investigator}:{raw_view['day']}")
            rng.shuffle(docs_copy)
            masked_docs = []
            for idx, d in enumerate(docs_copy):
                alias = f"doc{idx + 1:02d}"
                real_id = str(d["doc_id"])
                alias_to_real[alias] = real_id
                masked_docs.append(
                    {
                        "doc_id": alias,
                        "title": f"Internal briefing {idx + 1:02d}",
                        "recipient_count": d.get("recipient_count"),
                        "age_days": d.get("age_days"),
                    }
                )
            prompt_view["held_docs"] = masked_docs
        move = super().decide(prompt_view)
        if move.get("leak") in alias_to_real:
            real_leak = alias_to_real[move["leak"]]
            move["leak"] = real_leak
            if self.log:
                self.log[-1]["move"]["leak"] = real_leak
        last_log = self.log[-1] if self.log else {"error": None, "rejected": [], "reason": None}
        reason = clean_text(last_log.get("reason"))
        rejected = [clean_text(x) for x in (last_log.get("rejected") or [])]
        err = clean_text(last_log.get("error"))
        self.decisions.append(
            {
                "tier": self.tier,
                "seed": self.seed,
                "investigator": self.investigator,
                "day": raw_view["day"],
                "mole_view": raw_view,
                "leak": move.get("leak"),
                "frame": move.get("frame"),
                "reason": reason,
                "rejected": rejected,
                "error": err,
            }
        )
        return move


def sum_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "latency_s": 0.0,
    }
    for u in usages:
        for k in ("calls", "in", "out", "thinking", "cached", "total_tokens"):
            out[k] += int(u.get(k, 0) or 0)
        out["cost_usd"] = round(out["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)
        out["latency_s"] = round(out["latency_s"] + float(u.get("latency_s", 0.0) or 0.0), 3)
    return out


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "mean_score": 0.0, "accuracy": 0.0, "mean_day": 0.0}
    scores = [float(r["score"]) for r in rows]
    acc = sum(1 for r in rows if r["correct"]) / len(rows)
    days = [int(r["final_day"]) for r in rows]
    return {
        "n": len(rows),
        "mean_score": round(statistics.mean(scores), 4),
        "accuracy": round(acc, 4),
        "mean_day": round(statistics.mean(days), 2),
    }


def run_single_adaptive_episode(
    tier: str,
    seed: int,
    inv_name: str,
    llm_spec: str,
    run_id_prefix: str,
    thinking_level: str | None = None,
    mask_doc_ids: bool = True,
    client_factory: Callable[..., MeteredMoleClient] | None = None,
) -> dict[str, Any]:
    inv_factory = make_investigators()[inv_name]
    cell_meta = {"role": ROLE, "subrole": SUBROLE, "tier": tier, "seed": seed, "investigator": inv_name}
    run_id = f"{run_id_prefix}:{inv_name}:s{seed}"
    builder = client_factory or build_mole_client
    client = builder(llm_spec=llm_spec, run_id=run_id, meta=cell_meta, thinking_level=thinking_level)
    mole = LiveArenaMole(
        client=client,
        tier=tier,
        seed=seed,
        investigator=inv_name,
        mask_doc_ids=mask_doc_ids,
    )
    env = Env(tier=tier, seed=seed, mole_strategy=mole)
    policy = inv_factory(seed)
    ep = run_episode(env, policy)
    verdict = env.verdict()
    llm_errors = sum(1 for d in mole.decisions if d.get("error"))
    rejected_count = sum(len(d.get("rejected") or []) for d in mole.decisions)
    leaks_chosen = sum(1 for d in mole.decisions if d.get("leak") is not None)
    frames_chosen = sum(1 for d in mole.decisions if d.get("frame") is not None)
    episode_row = {
        "tier": tier,
        "seed": seed,
        "mole": "llm-mole",
        "model_id": model_id_from_spec(llm_spec),
        "investigator": inv_name,
        "policy_name": getattr(policy, "name", inv_name),
        "score": round(float(ep.score), 6),
        "correct": bool(ep.correct),
        "accused": ep.accused,
        "final_day": int(ep.final_day),
        "end_reason": ep.end_reason,
        "V": round(float(verdict.get("V", 0.0)), 6),
        "steps_count": len(ep.steps),
        "mole_days": len(mole.decisions),
        "mole_leaks_chosen": leaks_chosen,
        "mole_frames_chosen": frames_chosen,
        "mole_llm_errors": llm_errors,
        "mole_rejected_moves": rejected_count,
        "usage": dict(client.usage_totals),
    }
    return {"episode": episode_row, "decisions": mole.decisions}


def run_single_default_episode(tier: str, seed: int, inv_name: str) -> dict[str, Any]:
    inv_factory = make_investigators()[inv_name]
    env = Env(tier=tier, seed=seed, mole_strategy=None)
    policy = inv_factory(seed)
    ep = run_episode(env, policy)
    verdict = env.verdict()
    leaks = sum(1 for x in env.ledger() if x.event == "leak")
    return {
        "tier": tier,
        "seed": seed,
        "mole": "default",
        "model_id": None,
        "investigator": inv_name,
        "policy_name": getattr(policy, "name", inv_name),
        "score": round(float(ep.score), 6),
        "correct": bool(ep.correct),
        "accused": ep.accused,
        "final_day": int(ep.final_day),
        "end_reason": ep.end_reason,
        "V": round(float(verdict.get("V", 0.0)), 6),
        "steps_count": len(ep.steps),
        "mole_leaks": leaks,
    }


def render_summary_md(
    meta: dict[str, Any],
    episodes_payload: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> str:
    by_inv = episodes_payload["by_investigator"]
    usage = meta["usage"]
    lines = [
        "# Role 2: Adaptive Mole Live Arena Run",
        "",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model ID: `{meta['model_id']}` (`{meta['llm_spec']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Tier: `{meta['tier']}` (Canary `{meta['tiers_version']}`)",
        f"- Seeds: `{meta['seeds']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Solvability verified: `{meta['solvability_verified']}`",
        "",
        "## Gemini API Usage",
        "",
        f"- Calls: `{usage['calls']}`",
        f"- Input tokens: `{usage['in']}`",
        f"- Output tokens: `{usage['out']}`",
        f"- Thinking tokens: `{usage['thinking']}`",
        f"- Cached tokens: `{usage['cached']}`",
        f"- Total tokens: `{usage['total_tokens']}`",
        f"- Estimated cost (USD): `{usage['cost_usd']:.6f}`",
        f"- Mole LLM errors: `{meta['mole_llm_errors']}`",
        f"- Recorded day decisions: `{meta['mole_decisions_count']}`",
        "",
        "## Investigator Comparison (Adaptive Gemini Mole vs Default Scripted Mole)",
        "",
        "| Investigator | Adaptive Mole Mean Score | Adaptive Mole Accuracy | Default Mole Mean Score | Default Mole Accuracy | Score Delta (Adaptive - Default) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for inv in INVESTIGATOR_ORDER:
        row = by_inv[inv]
        am = row["adaptive_mole"]
        dm = row["default_mole"]
        lines.append(
            f"| `{inv}` | `{am['mean_score']:+.4f}` | `{am['accuracy']:.2%}` | "
            f"`{dm['mean_score']:+.4f}` | `{dm['accuracy']:.2%}` | `{row['delta_mean']:+.4f}` |"
        )
    lines.extend(
        [
            "",
            "## Per-Episode Results (Adaptive Gemini Mole)",
            "",
            "| Investigator | Seed | Score | Correct | Final Day | End Reason | Mole Days | Leaks Chosen | Frames Chosen | LLM Errors |",
            "|---|---:|---:|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for ep in episodes_payload["adaptive_mole"]:
        lines.append(
            f"| `{ep['investigator']}` | `{ep['seed']}` | `{ep['score']:+.4f}` | `{ep['correct']}` | "
            f"`{ep['final_day']}` | `{ep['end_reason']}` | `{ep['mole_days']}` | "
            f"`{ep['mole_leaks_chosen']}` | `{ep['mole_frames_chosen']}` | `{ep['mole_llm_errors']}` |"
        )
    lines.extend(
        [
            "",
            "## Per-Episode Results (Default Scripted Mole Baseline)",
            "",
            "| Investigator | Seed | Score | Correct | Final Day | End Reason | Leaks |",
            "|---|---:|---:|---|---:|---|---:|",
        ]
    )
    for ep in episodes_payload["default_mole"]:
        lines.append(
            f"| `{ep['investigator']}` | `{ep['seed']}` | `{ep['score']:+.4f}` | `{ep['correct']}` | "
            f"`{ep['final_day']}` | `{ep['end_reason']}` | `{ep['mole_leaks']}` |"
        )
    lines.extend(["", "## Sample Day-by-Day Mole Decisions", ""])
    for d in decisions[:6]:
        reason_str = (d.get("reason") or "").replace("\n", " ").strip()
        lines.append(
            f"- `{d['investigator']}` seed `{d['seed']}` day `{d['day']}`: "
            f"held={len(d['mole_view'].get('held_docs', []))}, "
            f"leak=`{d['leak']}`, frame=`{d['frame']}`, rejected=`{d['rejected']}`, "
            f"reason=\"{reason_str}\""
        )
    lines.append("")
    return clean_text("\n".join(lines))


def run_arena_suite(
    llm_spec: str = DEFAULT_LLM,
    tier: str = "medium",
    seeds: list[int] | None = None,
    out_dir: str | Path = DEFAULT_OUT,
    jobs: int = 6,
    thinking_level: str | None = None,
    mask_doc_ids: bool = True,
    command_str: str | None = None,
    client_factory: Callable[..., MeteredMoleClient] | None = None,
) -> dict[str, Any]:
    seeds_list = list(seeds if seeds is not None else [0, 1, 2])
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    run_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id_prefix = f"adaptive_mole:{int(time.time())}"

    default_rows: list[dict[str, Any]] = []
    for inv_name in INVESTIGATOR_ORDER:
        for seed in seeds_list:
            default_rows.append(run_single_default_episode(tier, seed, inv_name))

    tasks = [(inv_name, seed) for inv_name in INVESTIGATOR_ORDER for seed in seeds_list]
    results_map: dict[tuple[str, int], dict[str, Any]] = {}
    max_workers = max(1, min(int(jobs), len(tasks), 8))
    if max_workers == 1:
        for inv_name, seed in tasks:
            results_map[(inv_name, seed)] = run_single_adaptive_episode(
                tier=tier,
                seed=seed,
                inv_name=inv_name,
                llm_spec=llm_spec,
                run_id_prefix=run_id_prefix,
                thinking_level=thinking_level,
                mask_doc_ids=mask_doc_ids,
                client_factory=client_factory,
            )
    else:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_map = {
                ex.submit(
                    run_single_adaptive_episode,
                    tier,
                    seed,
                    inv_name,
                    llm_spec,
                    run_id_prefix,
                    thinking_level,
                    mask_doc_ids,
                    client_factory,
                ): (inv_name, seed)
                for inv_name, seed in tasks
            }
            for fut in cf.as_completed(fut_map):
                key = fut_map[fut]
                results_map[key] = fut.result()

    adaptive_rows: list[dict[str, Any]] = []
    all_decisions: list[dict[str, Any]] = []
    for inv_name in INVESTIGATOR_ORDER:
        for seed in seeds_list:
            item = results_map[(inv_name, seed)]
            adaptive_rows.append(item["episode"])
            all_decisions.extend(item["decisions"])

    by_investigator: dict[str, Any] = {}
    for inv_name in INVESTIGATOR_ORDER:
        a_sub = [r for r in adaptive_rows if r["investigator"] == inv_name]
        d_sub = [r for r in default_rows if r["investigator"] == inv_name]
        a_sum = summarize_group(a_sub)
        d_sum = summarize_group(d_sub)
        by_investigator[inv_name] = {
            "adaptive_mole": a_sum,
            "default_mole": d_sum,
            "delta_mean": round(a_sum["mean_score"] - d_sum["mean_score"], 4),
        }

    usage = sum_usage([r["usage"] for r in adaptive_rows])
    solver_acc = by_investigator["solver"]["adaptive_mole"]["accuracy"]
    solver_mean = by_investigator["solver"]["adaptive_mole"]["mean_score"]
    grok_mean = by_investigator["grok_tactics"]["adaptive_mole"]["mean_score"]
    grok_acc = by_investigator["grok_tactics"]["adaptive_mole"]["accuracy"]
    heur_mean = by_investigator["obvious_heuristic"]["adaptive_mole"]["mean_score"]
    heur_acc = by_investigator["obvious_heuristic"]["adaptive_mole"]["accuracy"]
    default_grok_mean = by_investigator["grok_tactics"]["default_mole"]["mean_score"]
    mole_llm_errors = sum(int(r["mole_llm_errors"]) for r in adaptive_rows)
    rejected_total = sum(int(r["mole_rejected_moves"]) for r in adaptive_rows)

    solvable = bool(
        solver_acc > 0.0
        and solver_mean > grok_mean
        and solver_mean > heur_mean
        and (grok_mean < default_grok_mean or heur_mean < solver_mean)
    )

    cmd_text = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    meta = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id_from_spec(llm_spec),
        "llm_spec": llm_spec,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seeds_list,
        "commit": git_commit(),
        "timestamp": run_ts,
        "command": clean_text(cmd_text),
        "usage": usage,
        "solver_accuracy": solver_acc,
        "solver_mean": solver_mean,
        "grok_tactics_mean": grok_mean,
        "grok_tactics_accuracy": grok_acc,
        "heuristic_mean": heur_mean,
        "heuristic_accuracy": heur_acc,
        "baseline_default_mole": {
            "solver_accuracy": by_investigator["solver"]["default_mole"]["accuracy"],
            "solver_mean": by_investigator["solver"]["default_mole"]["mean_score"],
            "grok_tactics_accuracy": by_investigator["grok_tactics"]["default_mole"]["accuracy"],
            "grok_tactics_mean": default_grok_mean,
            "heuristic_accuracy": by_investigator["obvious_heuristic"]["default_mole"]["accuracy"],
            "heuristic_mean": by_investigator["obvious_heuristic"]["default_mole"]["mean_score"],
        },
        "solvability_verified": solvable,
        "mole_llm_errors": mole_llm_errors,
        "mole_decisions_count": len(all_decisions),
        "mole_rejected_moves_count": rejected_total,
    }

    episodes_payload = {
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seeds_list,
        "model_id": meta["model_id"],
        "adaptive_mole": adaptive_rows,
        "default_mole": default_rows,
        "by_investigator": by_investigator,
    }

    (out_path / "meta.json").write_text(clean_text(json.dumps(meta, indent=2, sort_keys=True)) + "\n")
    (out_path / "episodes.json").write_text(clean_text(json.dumps(episodes_payload, indent=2, sort_keys=True)) + "\n")
    with (out_path / "mole_decisions.jsonl").open("w") as fh:
        for d in all_decisions:
            fh.write(clean_text(json.dumps(d, sort_keys=True)) + "\n")
    (out_path / "summary.md").write_text(render_summary_md(meta, episodes_payload, all_decisions))
    return meta


def parse_seeds_arg(vals: list[str]) -> list[int]:
    out: list[int] = []
    for item in vals:
        for part in item.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo, hi = part.split("-", 1)
                out.extend(range(int(lo), int(hi) + 1))
            else:
                out.append(int(part))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_role_adaptive_mole")
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", nargs="+", default=["0", "1", "2"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--no-mask-doc-ids", action="store_true")
    args = ap.parse_args(argv)
    seeds = parse_seeds_arg(args.seeds)
    cmd_str = " ".join(
        shlex.quote(x)
        for x in ([sys.executable, str(Path(__file__).relative_to(ROOT)), *(argv if argv is not None else sys.argv[1:])])
    )
    meta = run_arena_suite(
        llm_spec=args.llm,
        tier=args.tier,
        seeds=seeds,
        out_dir=args.out,
        jobs=args.jobs,
        thinking_level=args.thinking_level,
        mask_doc_ids=not args.no_mask_doc_ids,
        command_str=cmd_str,
    )
    print(
        json.dumps(
            {
                "model_id": meta["model_id"],
                "solver_accuracy": meta["solver_accuracy"],
                "solver_mean": meta["solver_mean"],
                "grok_tactics_mean": meta["grok_tactics_mean"],
                "heuristic_mean": meta["heuristic_mean"],
                "mole_llm_errors": meta["mole_llm_errors"],
                "total_tokens": meta["usage"]["total_tokens"],
                "solvability_verified": meta["solvability_verified"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
