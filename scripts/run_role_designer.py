from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.designer import KNOB_RANGES, design_round
from canary.baselines import ObviousHeuristic
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import lab_client
from canary.llm.base import is_retryable
from canary.mole.dsl import FEATURES as DSL_FEATURES
from canary.mole.dsl import MoleStrategy
from canary.rules import TIERS, TIERS_VERSION, tier_params
from canary.solver.policy import SolverPolicy

ROLE = "adaptive_mole"
SUBROLE = "paired_designer"
DEFAULT_LLM = "gemini:gemini-4-carbon"
DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "paired-designer-carbon"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
_TIERS_LOCK = threading.Lock()


def clean_text(val: Any) -> Any:
    if isinstance(val, str):
        return val.replace(EM_DASH, "-").replace(EN_DASH, "-")
    if isinstance(val, list):
        return [clean_text(x) for x in val]
    if isinstance(val, dict):
        return {clean_text(k): clean_text(v) for k, v in val.items()}
    return val


def sanitize_json_numbers(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, list):
        return [sanitize_json_numbers(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize_json_numbers(v) for k, v in obj.items()}
    return obj


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


def filter_response_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        if "anyOf" in schema and isinstance(schema["anyOf"], list):
            non_null = [
                x for x in schema["anyOf"] if not (isinstance(x, dict) and x.get("type") == "null")
            ]
            if len(non_null) == 1:
                return filter_response_schema(non_null[0])
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k in ("maxLength", "maxItems", "minLength", "minItems"):
                continue
            if k == "enum" and isinstance(v, list) and "days_since_last_leak" in v:
                out[k] = [x for x in v if x in DSL_FEATURES]
            else:
                out[k] = filter_response_schema(v)
        if out.get("type") == "object" and isinstance(out.get("properties"), dict):
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(schema, list):
        return [filter_response_schema(x) for x in schema]
    return schema


def sanitize_proposal_payload(payload: Any) -> Any:
    payload = clean_text(payload)
    if not isinstance(payload, dict):
        return payload
    cands = payload.get("candidates")
    if not isinstance(cands, list):
        return payload
    cleaned_cands = []
    for c in cands[:8]:
        if not isinstance(c, dict):
            cleaned_cands.append(c)
            continue
        item = dict(c)
        if isinstance(item.get("name"), str):
            item["name"] = item["name"].strip()[:60]
        if isinstance(item.get("rationale"), str):
            item["rationale"] = item["rationale"].strip()[:400]
        if isinstance(item.get("rules"), list):
            rules_out = []
            for r in item["rules"][:12]:
                if isinstance(r, dict) and isinstance(r.get("conditions"), list):
                    r_copy = dict(r)
                    r_copy["conditions"] = r["conditions"][:4]
                    rules_out.append(r_copy)
                else:
                    rules_out.append(r)
            item["rules"] = rules_out
        cleaned_cands.append(item)
    out = dict(payload)
    out["candidates"] = cleaned_cands
    return out


def build_system_addendum(tier: str, n: int, x_thr: float, y_thr: float) -> str:
    p = tier_params(tier)
    valid_feats = ", ".join(
        f for f in ("day", "days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
                    "recent_low_recipient_docs", "min_recipient_count")
        if f in DSL_FEATURES
    )
    return (
        f"\n\nPAIRED EVALUATION TARGETS ({tier} tier, Canary {TIERS_VERSION}):\n"
        f"- Company size: {p.n_employees} employees, horizon: {p.n_days} days, leak surfacing delay: {list(p.delay_choices)} days.\n"
        f"- A candidate scenario is KEPT iff SolverPolicy mean score >= {x_thr:.2f} AND ObviousHeuristic mean score <= {y_thr:.2f}.\n"
        f"- Allowed condition features ONLY: {valid_feats} (never use n_held_docs).\n"
        "- Solvability constraint: because the episode lasts 14 days with 1 to 3 day surfacing delays, "
        "do NOT throttle leaks with days_since_last_leak -> leak='none' and do NOT lower p_leak below 0.75, "
        "or SolverPolicy will run out of days and fail (< 0.50). Instead keep p_leak in 0.78..0.90 and "
        "leak_damage in 0.035..0.045, keep decoy=true, framing=true, careful_mole=true, use random_seeded "
        "as the catch-all leak selector so partial-coverage Bayesian canaries still leak while full-staff "
        "naive canaries are downweighted, and use targeted framing (decoy, most_restricted_peer, random_peer) "
        "plus selective evasions (for example when recent_low_recipient_docs >= 2 or n_restricted_colleagues >= 1) "
        "to mislead ObviousHeuristic.\n"
        f"- Return exactly {n} distinct candidates. Keep each name <= 50 ASCII chars and rationale <= 320 ASCII chars. "
        "Use plain ASCII hyphens only (no unicode dashes)."
    )


class MeteredDesignerClient:
    def __init__(self, inner: Any, system_addendum: str = ""):
        self.inner = inner
        self.system_addendum = clean_text(system_addendum)
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
        patched_messages = []
        for m in messages:
            if m.get("role") == "system" and self.system_addendum:
                content = clean_text(str(m.get("content") or "")).rstrip() + self.system_addendum
                patched_messages.append({**m, "content": content})
            else:
                patched_messages.append(dict(m))
        call_kw = dict(kw)
        if call_kw.get("response_schema") is not None:
            call_kw["response_schema"] = filter_response_schema(call_kw["response_schema"])

        is_gemini = getattr(self.inner, "provider", "") == "gemini"
        max_attempts = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "6")) if is_gemini else 1
        last_exc: Exception | None = None
        for attempt in range(max(1, max_attempts)):
            t0 = time.time()
            try:
                resp = self.inner.chat(patched_messages, **call_kw)
            except Exception as exc:
                if not is_gemini or attempt + 1 >= max_attempts or not is_retryable(exc):
                    raise
                last_exc = exc
                time.sleep(min(2.0 * (2 ** attempt), 30.0))
                continue
            elapsed = time.time() - t0
            self._record_resp(resp, elapsed)
            txt = getattr(resp, "text", None)
            if is_gemini and call_kw.get("response_schema") is not None:
                raw_txt = (txt or "").strip()
                if not raw_txt:
                    if attempt + 1 < max_attempts:
                        time.sleep(min(1.5 * (2 ** attempt), 20.0))
                        continue
                else:
                    try:
                        parsed_json = sanitize_proposal_payload(json.loads(raw_txt))
                        resp.text = json.dumps(parsed_json)
                    except json.JSONDecodeError:
                        if attempt + 1 < max_attempts:
                            time.sleep(min(1.5 * (2 ** attempt), 20.0))
                            continue
            elif isinstance(txt, str):
                try:
                    parsed_json = sanitize_proposal_payload(json.loads(txt))
                    resp.text = json.dumps(parsed_json)
                except Exception:
                    resp.text = clean_text(txt)
            return resp
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("exhausted retries in MeteredDesignerClient.chat")


def build_designer_client(
    llm_spec: str = DEFAULT_LLM,
    run_id: str = "",
    meta: dict[str, Any] | None = None,
    thinking_level: str | None = None,
    system_addendum: str = "",
    client_override: Any = None,
) -> MeteredDesignerClient:
    if client_override is not None:
        return MeteredDesignerClient(client_override, system_addendum=system_addendum)
    kw: dict[str, Any] = {}
    if thinking_level:
        kw["thinking_level"] = thinking_level
    inner = lab_client(llm_spec, feature=ROLE, run_id=run_id, meta=meta, **kw)
    return MeteredDesignerClient(inner, system_addendum=system_addendum)


def make_candidate_env(tier: str, seed: int, candidate: dict[str, Any] | None = None) -> Env:
    strat_obj = None
    knobs: dict[str, Any] = {}
    if candidate is not None:
        dsl = candidate.get("mole_strategy")
        if isinstance(dsl, dict):
            strat_obj = MoleStrategy.from_json(dsl)
        elif dsl is not None:
            strat_obj = dsl
        knobs = dict(candidate.get("knobs") or {})
    with _TIERS_LOCK:
        orig = TIERS[tier]
        overrides = {k: v for k, v in knobs.items() if hasattr(orig, k) and v is not None}
        custom = replace(orig, **overrides) if overrides else orig
        TIERS[tier] = custom
        try:
            return Env(tier=tier, seed=seed, mole_strategy=strat_obj)
        finally:
            TIERS[tier] = orig


def evaluate_policy_on_candidate(
    tier: str,
    seeds: list[int],
    candidate: dict[str, Any] | None,
    policy_factory: Callable[[int], Any],
    policy_label: str,
) -> dict[str, Any]:
    episodes: list[dict[str, Any]] = []
    for seed in seeds:
        env = make_candidate_env(tier, seed, candidate)
        policy = policy_factory(seed)
        ep = run_episode(env, policy)
        verdict = env.verdict()
        ledger = env.ledger()
        leaks = sum(1 for x in ledger if x.event == "leak")
        frames = sum(1 for x in ledger if x.event == "framed")
        episodes.append(
            {
                "seed": seed,
                "policy": policy_label,
                "score": round(float(ep.score), 6),
                "correct": bool(ep.correct),
                "accused": ep.accused,
                "final_day": int(ep.final_day),
                "end_reason": ep.end_reason,
                "V": round(float(verdict.get("V", 0.0)), 6),
                "steps_count": len(ep.steps),
                "mole_leaks": leaks,
                "mole_frames": frames,
            }
        )
    scores = [float(r["score"]) for r in episodes]
    acc = sum(1 for r in episodes if r["correct"]) / len(episodes) if episodes else 0.0
    mean_day = statistics.mean(r["final_day"] for r in episodes) if episodes else 0.0
    return {
        "mean_score": statistics.mean(scores) if scores else 0.0,
        "accuracy": round(acc, 4),
        "mean_day": round(mean_day, 2),
        "episodes": episodes,
    }


def candidate_key(candidate: dict[str, Any]) -> str:
    return json.dumps(
        {
            "name": candidate.get("name", ""),
            "mole_strategy": candidate.get("mole_strategy", {}),
            "knobs": candidate.get("knobs", {}),
        },
        sort_keys=True,
    )


def render_summary_md(meta: dict[str, Any], report_payload: dict[str, Any]) -> str:
    usage = meta["usage"]
    base = report_payload["baseline_default"]
    lines = [
        "# Role 2: PAIRED Scenario Designer Run",
        "",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model ID: `{meta['model_id']}` (`{meta['llm_spec']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Tier: `{meta['tier']}` (Canary `{meta['tiers_version']}`)",
        f"- Seeds: `{meta['seeds']}`",
        f"- Solvability gate: keep iff `SolverPolicy >= {meta['X']:.2f}` and `ObviousHeuristic <= {meta['Y']:.2f}`",
        f"- LLM output valid: `llm_ok={meta['llm_ok']}`, `n_llm_valid={meta['n_llm_valid']}/{meta['n_proposals']}`, `n_kept={meta['n_kept']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
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
        f"- Latency (s): `{usage['latency_s']:.3f}`",
        "",
        "## Default Scenario Baseline (Same Seeds)",
        "",
        f"- `SolverPolicy` mean score: `{base['solver_mean']:+.4f}` (accuracy `{base['solver_accuracy']:.2%}`)",
        f"- `ObviousHeuristic` mean score: `{base['agent_mean']:+.4f}` (accuracy `{base['agent_accuracy']:.2%}`)",
        f"- Default regret (`SolverPolicy - ObviousHeuristic`): `{base['regret']:+.4f}`",
        "",
        "## Proposed Candidate Scenarios & Regret Filter",
        "",
        "| # | Candidate | Source | SolverPolicy Mean | Solver Acc | ObviousHeuristic Mean | Heuristic Acc | Regret | Gate Outcome |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(report_payload["rows"], start=1):
        s_str = f"`{row['solver']:+.4f}`"
        s_acc = f"`{row['solver_accuracy']:.0%}`"
        a_str = f"`{row['agent']:+.4f}`" if row["agent"] is not None else "`skipped`"
        a_acc = f"`{row['agent_accuracy']:.0%}`" if row["agent_accuracy"] is not None else "`-`"
        reg_str = f"`{row['regret']:+.4f}`" if row["regret"] is not None else "`-`"
        lines.append(
            f"| {idx} | `{row['name']}` | `{row['origin']}` | {s_str} | {s_acc} | "
            f"{a_str} | {a_acc} | {reg_str} | `{row['why']}` |"
        )
    lines.extend(["", "## Candidate Details (Mole DSL & Clamped Knobs)", ""])
    for idx, row in enumerate(report_payload["rows"], start=1):
        cand = row["candidate"]
        lines.extend(
            [
                f"### {idx}. `{row['name']}` (`{row['why']}`)",
                "",
                f"- Rationale: {cand.get('rationale') or 'n/a'}",
                f"- Clamped knobs: `{json.dumps(cand.get('knobs', {}), sort_keys=True)}`",
                f"- Mole DSL rules: `{json.dumps(cand.get('mole_strategy', {}).get('rules', []))}`",
                "- Per-seed `SolverPolicy` scores: "
                + ", ".join(f"s{ep['seed']}=`{ep['score']:+.2f}`" for ep in row["solver_episodes"]),
            ]
        )
        if row["agent_episodes"]:
            lines.append(
                "- Per-seed `ObviousHeuristic` scores: "
                + ", ".join(f"s{ep['seed']}=`{ep['score']:+.2f}`" for ep in row["agent_episodes"])
            )
        lines.append("")
    return clean_text("\n".join(lines).rstrip() + "\n")


def run_designer_suite(
    llm_spec: str = DEFAULT_LLM,
    tier: str = "medium",
    seeds: list[int] | None = None,
    n: int = 4,
    x_thr: float = 0.50,
    y_thr: float = 0.25,
    seed: int = 0,
    rounds: int | None = None,
    thinking_level: str | None = None,
    out_dir: str | Path = DEFAULT_OUT,
    require_llm: bool | None = None,
    command_str: str | None = None,
    client_factory: Callable[..., MeteredDesignerClient] | None = None,
) -> dict[str, Any]:
    seeds_list = list(seeds if seeds is not None else [0, 1, 2, 3, 4])
    if require_llm is None:
        require_llm = not str(llm_spec).startswith("stub")
    max_rounds = int(rounds) if rounds is not None else (2 if require_llm else 1)

    out_path = Path(out_dir)
    run_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"paired_designer:{int(time.time())}"
    addendum = build_system_addendum(tier=tier, n=n, x_thr=x_thr, y_thr=y_thr)
    call_meta = {
        "role": ROLE,
        "subrole": SUBROLE,
        "tier": tier,
        "seeds": seeds_list,
        "n": n,
        "X": x_thr,
        "Y": y_thr,
    }
    builder = client_factory or build_designer_client
    client = builder(
        llm_spec=llm_spec,
        run_id=run_id,
        meta=call_meta,
        thinking_level=thinking_level,
        system_addendum=addendum,
    )

    solver_factory = lambda s: SolverPolicy()
    agent_factory = lambda s: ObviousHeuristic(seed=s)

    base_solver = evaluate_policy_on_candidate(tier, seeds_list, None, solver_factory, "solver")
    base_agent = evaluate_policy_on_candidate(tier, seeds_list, None, agent_factory, "obvious_heuristic")
    baseline_default = {
        "solver_mean": round(base_solver["mean_score"], 6),
        "solver_accuracy": base_solver["accuracy"],
        "solver_mean_day": base_solver["mean_day"],
        "agent_mean": round(base_agent["mean_score"], 6),
        "agent_accuracy": base_agent["accuracy"],
        "agent_mean_day": base_agent["mean_day"],
        "regret": round(base_solver["mean_score"] - base_agent["mean_score"], 6),
        "solver_episodes": base_solver["episodes"],
        "agent_episodes": base_agent["episodes"],
    }

    eval_store: dict[str, dict[str, Any]] = {}

    def solver_eval(cand: dict[str, Any]) -> float:
        ck = candidate_key(cand)
        bucket = eval_store.setdefault(ck, {})
        if "solver" not in bucket:
            bucket["solver"] = evaluate_policy_on_candidate(tier, seeds_list, cand, solver_factory, "solver")
        return float(bucket["solver"]["mean_score"])

    def agent_eval(cand: dict[str, Any]) -> float:
        ck = candidate_key(cand)
        bucket = eval_store.setdefault(ck, {})
        if "agent" not in bucket:
            bucket["agent"] = evaluate_policy_on_candidate(tier, seeds_list, cand, agent_factory, "obvious_heuristic")
        return float(bucket["agent"]["mean_score"])

    history: list[dict[str, Any]] = []
    rep: dict[str, Any] = {}
    round_summaries: list[dict[str, Any]] = []
    for r_idx in range(max(1, max_rounds)):
        rep = design_round(
            client=client,
            solver_eval=solver_eval,
            agent_eval=agent_eval,
            X=x_thr,
            Y=y_thr,
            tier=tier,
            n=n,
            history=history or None,
            seed=seed + r_idx,
        )
        round_summaries.append(
            {
                "round": r_idx + 1,
                "llm_ok": bool(rep["meta"]["llm_ok"]),
                "n_llm_valid": int(rep["meta"]["n_llm_valid"]),
                "n_kept": len(rep["kept"]),
                "error": rep["meta"].get("error"),
            }
        )
        if not require_llm:
            break
        if rep["meta"]["llm_ok"] and rep["meta"]["n_llm_valid"] >= 1 and len(rep["kept"]) >= 1:
            break
        for row in rep["rows"]:
            history.append(
                {
                    "name": row["name"],
                    "keep": row["keep"],
                    "solver": round(float(row["solver"]), 4),
                    "agent": round(float(row["agent"]), 4) if math.isfinite(float(row["agent"])) else None,
                    "why": row["why"],
                    "knobs": row["candidate"].get("knobs", {}),
                }
            )

    if require_llm:
        if not rep["meta"]["llm_ok"]:
            raise RuntimeError(f"designer LLM call failed: {rep['meta']}")
        if int(rep["meta"]["n_llm_valid"]) < 1:
            raise RuntimeError(f"designer produced 0 valid LLM candidates: {rep['meta']}")

    n_llm_valid = int(rep["meta"]["n_llm_valid"])
    enriched_rows: list[dict[str, Any]] = []
    total_eval_episodes = len(base_solver["episodes"]) + len(base_agent["episodes"])
    for idx, row in enumerate(rep["rows"]):
        cand = clean_text(row["candidate"])
        ck = candidate_key(row["candidate"])
        s_info = eval_store.get(ck, {}).get("solver")
        a_info = eval_store.get(ck, {}).get("agent")
        if s_info is not None:
            total_eval_episodes += len(s_info["episodes"])
        if a_info is not None:
            total_eval_episodes += len(a_info["episodes"])
        s_val = float(row["solver"])
        a_val = float(row["agent"])
        reg_val = float(row["regret"])
        enriched_rows.append(
            {
                "name": clean_text(row["name"]),
                "origin": "llm" if idx < n_llm_valid else "fallback",
                "keep": bool(row["keep"]),
                "solver": round(s_val, 6),
                "solver_accuracy": s_info["accuracy"] if s_info else 0.0,
                "agent": round(a_val, 6) if math.isfinite(a_val) else None,
                "agent_accuracy": a_info["accuracy"] if a_info else None,
                "regret": round(reg_val, 6) if math.isfinite(reg_val) else None,
                "why": clean_text(row["why"]),
                "candidate": cand,
                "solver_episodes": s_info["episodes"] if s_info else [],
                "agent_episodes": a_info["episodes"] if a_info else [],
            }
        )

    kept_rows = [r for r in enriched_rows if r["keep"]]
    kept_candidates = [r["candidate"] for r in kept_rows]
    n_kept = len(kept_candidates)
    n_kept_llm = sum(1 for r in kept_rows if r["origin"] == "llm")

    kept_solver_mean = (
        round(statistics.mean(r["solver"] for r in kept_rows), 4) if kept_rows else None
    )
    kept_agent_mean = (
        round(statistics.mean(r["agent"] for r in kept_rows if r["agent"] is not None), 4)
        if kept_rows
        else None
    )
    kept_regret_mean = (
        round(statistics.mean(r["regret"] for r in kept_rows if r["regret"] is not None), 4)
        if kept_rows
        else None
    )

    cmd_text = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    meta = clean_text(
        {
            "role": ROLE,
            "subrole": SUBROLE,
            "model_id": model_id_from_spec(llm_spec),
            "llm_spec": llm_spec,
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "seeds": seeds_list,
            "X": x_thr,
            "Y": y_thr,
            "n_proposals": n,
            "sample_count": len(enriched_rows),
            "n_episodes_evaluated": total_eval_episodes,
            "llm_ok": bool(rep["meta"]["llm_ok"]),
            "n_llm_valid": n_llm_valid,
            "n_kept": n_kept,
            "n_kept_llm": n_kept_llm,
            "kept_solver_mean": kept_solver_mean,
            "kept_heuristic_mean": kept_agent_mean,
            "kept_regret_mean": kept_regret_mean,
            "baseline_default_scenario": {
                "solver_mean": round(baseline_default["solver_mean"], 4),
                "solver_accuracy": baseline_default["solver_accuracy"],
                "heuristic_mean": round(baseline_default["agent_mean"], 4),
                "heuristic_accuracy": baseline_default["agent_accuracy"],
                "regret": round(baseline_default["regret"], 4),
            },
            "rounds_executed": len(round_summaries),
            "commit": git_commit(),
            "timestamp": run_ts,
            "command": clean_text(cmd_text),
            "usage": dict(client.usage_totals),
        }
    )

    report_payload = clean_text(
        sanitize_json_numbers(
            {
                "tier": tier,
                "tiers_version": TIERS_VERSION,
                "seeds": seeds_list,
                "model_id": meta["model_id"],
                "X": x_thr,
                "Y": y_thr,
                "knob_ranges": KNOB_RANGES,
                "meta": clean_text(rep["meta"]),
                "rounds": round_summaries,
                "rows": enriched_rows,
                "kept": kept_candidates,
                "baseline_default": baseline_default,
            }
        )
    )

    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "meta.json").write_text(
        clean_text(json.dumps(meta, indent=2, sort_keys=True, allow_nan=False)) + "\n"
    )
    (out_path / "report.json").write_text(
        clean_text(json.dumps(report_payload, indent=2, sort_keys=True, allow_nan=False)) + "\n"
    )
    (out_path / "summary.md").write_text(render_summary_md(meta, report_payload))
    return {"meta": meta, "report": report_payload, "raw_design_round": rep}


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
    ap = argparse.ArgumentParser(prog="run_role_designer")
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", nargs="+", default=["0", "1", "2", "3", "4"])
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--X", type=float, default=0.50)
    ap.add_argument("--Y", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--require-llm", action="store_true")
    args = ap.parse_args(argv)

    seeds = parse_seeds_arg(args.seeds)
    raw_argv = argv if argv is not None else sys.argv[1:]
    cmd_str = " ".join(
        shlex.quote(x)
        for x in [sys.executable, str(Path(__file__).relative_to(ROOT)), *raw_argv]
    )
    req_llm = True if args.require_llm else (not str(args.llm).startswith("stub"))
    res = run_designer_suite(
        llm_spec=args.llm,
        tier=args.tier,
        seeds=seeds,
        n=args.n,
        x_thr=args.X,
        y_thr=args.Y,
        seed=args.seed,
        rounds=args.rounds,
        thinking_level=args.thinking_level,
        out_dir=args.out,
        require_llm=req_llm,
        command_str=cmd_str,
    )
    meta = res["meta"]
    print(
        json.dumps(
            {
                "model_id": meta["model_id"],
                "llm_ok": meta["llm_ok"],
                "n_llm_valid": meta["n_llm_valid"],
                "n_kept": meta["n_kept"],
                "kept_solver_mean": meta["kept_solver_mean"],
                "kept_heuristic_mean": meta["kept_heuristic_mean"],
                "total_tokens": meta["usage"]["total_tokens"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
