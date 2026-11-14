from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shlex
import statistics
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.agents import designer
from canary.analysis.gap import mean_ci
from canary.baselines import ObviousHeuristic
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import lab_client, ledger_path, read_ledger
from canary.llm.pricing import cost as price_cost
from canary.llm.stub import register_script
from canary.solver.policy import SolverPolicy
from scripts import skill_ladder

ROLE = "adaptive_mole"
SUBROLE = "paired_skill_designer"
FEATURE = "paired_designer"
DEFAULT_LLM = "gemini:gemini-4-carbon"
DEFAULT_TIER = "medium"
DEFAULT_DESIGN_SEEDS = "5,6,7,8,9"
DEFAULT_EVAL_SEEDS = "5100..5119"
DEFAULT_N_PROPOSALS = 4
DEFAULT_X = 0.50
DEFAULT_Y = 0.20
DEFAULT_MAX_ROUNDS = 3
DEFAULT_OUT_DIR = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "paired-solvable-scenarios-carbon"
STUB_SCRIPT_NAME = "paired_skill_designer"

HEADLINE_RUNGS: tuple[str, ...] = (
    "full_solver",
    "no_ev_commit",
    "binary_canary_only",
    "heuristic_bisection",
    "do_nothing",
)
ALL_RUNGS: tuple[str, ...] = skill_ladder.RUNG_ORDER
VALID_DSL_FEATURES = frozenset({
    "days_since_last_leak",
    "i_am_restricted",
    "n_restricted_colleagues",
    "recent_low_recipient_docs",
    "day",
    "min_recipient_count",
})

DESIGNER_GUIDANCE = (
    "Important environment constraints: (1) Use only valid MoleView features "
    "(day, days_since_last_leak, i_am_restricted, n_restricted_colleagues, "
    "recent_low_recipient_docs, min_recipient_count). "
    "(2) Regular documents are published before daily canaries, so deterministic 'newest' or "
    "'most_recipients' on every day starves canary traps and fails solvability; keep 'random_seeded' "
    "as the default leak selector and avoid multi-day leak='none' blackouts so SolverPolicy scores >= 0.50 "
    "while framing ('decoy', 'random_peer', 'most_restricted_peer') and knobs defeat naive/ablated policies. "
    "(3) Keep candidate name <= 50 chars, rationale <= 320 chars, and never use em dashes."
)

SECRET_PAT = re.compile(
    r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
    r"(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|anthropic_api_key|xai_api_key)"
    r"[\"']?[ \t]*[:=][ \t]*[^\s\"',}\]]{4,})"
)

STUB_PROPOSAL_PAYLOAD: dict[str, Any] = {
    "candidates": [
        {
            "name": "decoy-shield-broad-leak",
            "rationale": "Frames the decoy on day 1 with a broad leak, then uses seeded random leaks while framing peers.",
            "rules": [
                {
                    "conditions": [{"feature": "day", "op": "==", "value": 1}],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
                {
                    "conditions": [],
                    "then": {"leak": "random_seeded", "frame": "decoy"},
                },
            ],
            "knobs": {
                "p_leak": 0.80,
                "leak_damage": 0.045,
                "log_rate_mole": 1.05,
                "interview_lr": 1.2,
                "decoy": True,
                "framing": True,
                "careful_mole": True,
            },
        },
        {
            "name": "peer-frame-rotator",
            "rationale": "Frames the decoy early and random peers later while keeping seeded random leaks active.",
            "rules": [
                {
                    "conditions": [{"feature": "day", "op": "<=", "value": 2}],
                    "then": {"leak": "random_seeded", "frame": "decoy"},
                },
                {
                    "conditions": [],
                    "then": {"leak": "random_seeded", "frame": "random_peer"},
                },
            ],
            "knobs": {
                "p_leak": 0.80,
                "leak_damage": 0.04,
                "decoy": True,
                "framing": True,
                "careful_mole": True,
            },
        },
        {
            "name": "deep-sleep-unsolvable",
            "rationale": "Suppresses almost all leaks so neither solver nor heuristic gets canary signal.",
            "rules": [
                {
                    "conditions": [{"feature": "days_since_last_leak", "op": "<", "value": 5}],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "conditions": [],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
            ],
            "knobs": {
                "p_leak": 0.65,
                "careful_mole": True,
            },
        },
        {
            "name": "restricted-pivot-mole",
            "rationale": "Pivots framing onto restricted peers if restricted, otherwise leaks via random_seeded and frames decoy.",
            "rules": [
                {
                    "conditions": [{"feature": "i_am_restricted", "op": "==", "value": 1}],
                    "then": {"leak": "oldest", "frame": "most_restricted_peer"},
                },
                {
                    "conditions": [],
                    "then": {"leak": "random_seeded", "frame": "decoy"},
                },
            ],
            "knobs": {
                "p_leak": 0.82,
                "leak_damage": 0.045,
                "decoy": True,
                "framing": True,
                "careful_mole": True,
            },
        },
    ]
}


def clean_str(val: Any) -> str:
    if val is None:
        return ""
    out = str(val).replace(chr(0x2014), "-").replace(chr(0x2013), "-")
    return SECRET_PAT.sub("[redacted]", out)


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {clean_str(k): sanitize_obj(v) for k, v in obj.items()}
    return obj


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = sanitize_obj(payload)
    path.write_text(json.dumps(cleaned, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def register_stub_designer() -> str:
    register_script(STUB_SCRIPT_NAME, [{"json": STUB_PROPOSAL_PAYLOAD}])
    return f"stub:{STUB_SCRIPT_NAME}"


def resolve_model_and_provider(llm_spec: str, client: Any = None) -> tuple[str, str, bool]:
    if client is not None and not isinstance(llm_spec, str):
        prov = str(getattr(client, "provider", "custom"))
        mod = str(getattr(client, "model", "custom") or "custom")
        return mod, prov, prov == "stub"
    provider, sep, model = str(llm_spec).strip().partition(":")
    provider = provider.strip().lower()
    if provider == "stub":
        return "stub", "stub", True
    if not sep or not model.strip():
        model = str(getattr(client, "model", "") or "gemini-4-carbon")
    return model.strip(), provider or "gemini", False


def sanitize_gemini_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if schema is None:
        return None

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "anyOf" in node:
            non_null = [x for x in node["anyOf"] if isinstance(x, dict) and x.get("type") != "null"]
            if non_null:
                merged = dict(non_null[0])
                if "description" in node and "description" not in merged:
                    merged["description"] = node["description"]
                return walk(merged)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("title", "default", "maxLength", "minLength", "maxItems", "minItems", "additionalProperties"):
                continue
            if k == "enum" and isinstance(v, list):
                filtered = [x for x in v if x != "n_held_docs"]
                out[k] = filtered if filtered else list(v)
            else:
                out[k] = walk(v)
        if out.get("type") == "object" and "properties" in out and "required" not in out:
            props = out["properties"]
            if set(props.keys()) >= {"name", "rationale", "rules", "knobs"}:
                out["required"] = ["name", "rationale", "rules", "knobs"]
            elif set(props.keys()) == {"leak", "frame"}:
                out["required"] = ["leak", "frame"]
            elif set(props.keys()) == {"candidates"}:
                out["required"] = ["candidates"]
        return out

    return walk(schema)


def clamp_proposal_json_text(raw_text: str) -> str:
    try:
        data = json.loads(raw_text)
    except (TypeError, ValueError):
        return raw_text
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        return raw_text
    trimmed_cands: list[Any] = []
    for cand in data["candidates"][:8]:
        if not isinstance(cand, dict):
            continue
        c = dict(cand)
        if isinstance(c.get("name"), str):
            c["name"] = clean_str(c["name"])[:60]
        if isinstance(c.get("rationale"), str):
            c["rationale"] = clean_str(c["rationale"])[:400]
        if isinstance(c.get("rules"), list):
            rules_list: list[Any] = []
            for r in c["rules"][: designer.MAX_RULES]:
                if not isinstance(r, dict):
                    continue
                rc = dict(r)
                if isinstance(rc.get("conditions"), list):
                    rc["conditions"] = [
                        cond for cond in rc["conditions"][:4]
                        if isinstance(cond, dict) and cond.get("feature") in VALID_DSL_FEATURES
                    ]
                rules_list.append(rc)
            c["rules"] = rules_list
        trimmed_cands.append(c)
    data["candidates"] = trimmed_cands
    return json.dumps(data)


class DesignerClientAdapter:
    def __init__(self, inner: Any):
        self.inner = inner
        self.provider = getattr(inner, "provider", "gemini")
        self.model = getattr(inner, "model", "")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Any = None,
        temperature: float = 0.0,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> Any:
        adj_messages: list[dict[str, Any]] = []
        added_guidance = False
        for m in messages:
            mc = dict(m)
            if mc.get("role") == "system" and not added_guidance:
                mc["content"] = f"{mc.get('content', '').rstrip()}\n\n{DESIGNER_GUIDANCE}"
                added_guidance = True
            adj_messages.append(mc)
        clean_schema = sanitize_gemini_schema(response_schema) if self.provider == "gemini" else response_schema
        resp = self.inner.chat(
            adj_messages,
            tools=tools,
            temperature=temperature,
            response_schema=clean_schema,
            max_tokens=max_tokens,
            seed=seed,
        )
        if getattr(resp, "text", None):
            resp.text = clamp_proposal_json_text(resp.text)
        return resp


def build_designer_client(
    llm_spec: str,
    run_id: str,
    max_retries: int | None = None,
) -> Any:
    spec = llm_spec.strip()
    if spec == "stub":
        stub_spec = register_stub_designer()
        return DesignerClientAdapter(lab_client(stub_spec, feature=FEATURE, run_id=run_id))
    if spec.startswith("stub:"):
        return DesignerClientAdapter(lab_client(spec, feature=FEATURE, run_id=run_id))
    retries = max_retries
    if retries is None:
        retries = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "10"))
    return DesignerClientAdapter(lab_client(spec, feature=FEATURE, run_id=run_id, max_retries=retries))


@contextmanager
def candidate_tier_context(tier: str, candidate: dict[str, Any] | None):
    orig = rules.TIERS[tier]
    knobs = dict((candidate or {}).get("knobs") or {})
    if knobs:
        valid_fields = {k: v for k, v in knobs.items() if hasattr(orig, k) and v is not None}
        if valid_fields:
            rules.TIERS[tier] = replace(orig, **valid_fields)
    try:
        yield rules.TIERS[tier]
    finally:
        rules.TIERS[tier] = orig


def evaluate_policy_mean(
    tier: str,
    seeds: list[int],
    candidate: dict[str, Any] | None,
    policy_kind: str,
) -> float:
    mole_strategy = (candidate or {}).get("mole_strategy") if candidate else None
    with candidate_tier_context(tier, candidate):
        scores: list[float] = []
        for s in seeds:
            if policy_kind == "solver":
                pol: Any = SolverPolicy()
            elif policy_kind == "heuristic":
                pol = ObviousHeuristic(seed=s)
            else:
                raise ValueError(f"unknown policy_kind '{policy_kind}'")
            ep = run_episode(Env(tier, s, mole_strategy=mole_strategy), pol)
            scores.append(float(ep.score))
    return float(statistics.mean(scores))


def evaluate_scenario_rungs(
    tier: str,
    seeds: list[int],
    rungs: tuple[str, ...] = ALL_RUNGS,
    candidate: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[int, dict[str, Any]]]]:
    mole_strategy = (candidate or {}).get("mole_strategy") if candidate else None
    per_rung: dict[str, dict[int, dict[str, Any]]] = {}
    with candidate_tier_context(tier, candidate):
        for rung in rungs:
            by_seed: dict[int, dict[str, Any]] = {}
            for s in seeds:
                env = Env(tier, s, mole_strategy=mole_strategy)
                pol = skill_ladder.make_rung(rung, seed=s)
                ep = run_episode(env, pol)
                by_seed[s] = skill_ladder._episode_stats(ep)
            per_rung[rung] = by_seed

    ref_by_seed = per_rung.get("full_solver", {})
    rows: list[dict[str, Any]] = []
    for rung in rungs:
        cell = per_rung[rung]
        ordered = [cell[s] for s in seeds]
        n = len(ordered)
        scores = [r["score"] for r in ordered]
        luck_scores = [r["luck_adjusted_score"] for r in ordered]
        m, ci = mean_ci(scores)
        lm, lci = mean_ci(luck_scores)

        if ref_by_seed and rung != "full_solver":
            diffs = [cell[s]["score"] - ref_by_seed[s]["score"] for s in seeds]
            costs = [ref_by_seed[s]["score"] - cell[s]["score"] for s in seeds]
            ldiffs = [cell[s]["luck_adjusted_score"] - ref_by_seed[s]["luck_adjusted_score"] for s in seeds]
            dm, dci = mean_ci(diffs)
            cm, cci = mean_ci(costs)
            ldm, ldci = mean_ci(ldiffs)
        else:
            dm, dci = 0.0, 0.0
            cm, cci = 0.0, 0.0
            ldm, ldci = 0.0, 0.0

        accused_eps = [r for r in ordered if r["accused"]]
        p_vals = [r["p_accused"] for r in accused_eps if r["p_accused"] is not None]
        acc_days = [r["final_day"] for r in accused_eps]

        rows.append({
            "tier": tier,
            "rung": rung,
            "description": skill_ladder.RUNG_DESCRIPTIONS.get(rung, ""),
            "n": n,
            "mean_score": round(m, 4),
            "ci95": round(ci, 4),
            "paired_diff": round(dm, 4),
            "paired_diff_ci95": round(dci, 4),
            "cost_vs_full_solver": round(cm, 4),
            "cost_ci95": round(cci, 4),
            "luck_adjusted_mean": round(lm, 4),
            "luck_adjusted_ci95": round(lci, 4),
            "luck_adjusted_diff": round(ldm, 4),
            "luck_adjusted_diff_ci95": round(ldci, 4),
            "accuracy": round(sum(1 for r in ordered if r["correct"]) / n, 4),
            "accused_rate": round(len(accused_eps) / n, 4),
            "abstain_rate": round(1.0 - len(accused_eps) / n, 4),
            "mean_p_accused": round(statistics.mean(p_vals), 4) if p_vals else None,
            "mean_accuse_day": round(statistics.mean(acc_days), 2) if acc_days else None,
            "max_canaries_in_a_day": max((r["max_canaries_day"] for r in ordered), default=0),
            "max_variants_used": max((r["max_variants_used"] for r in ordered), default=0),
        })
    return rows, per_rung


def build_comparison_rows(
    seeds: list[int],
    rungs: tuple[str, ...],
    baseline_rows: list[dict[str, Any]],
    baseline_map: dict[str, dict[int, dict[str, Any]]],
    designed_rows: list[dict[str, Any]],
    designed_map: dict[str, dict[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    base_by_rung = {r["rung"]: r for r in baseline_rows}
    des_by_rung = {r["rung"]: r for r in designed_rows}
    base_ref = baseline_map.get("full_solver", {})
    des_ref = designed_map.get("full_solver", {})

    out: list[dict[str, Any]] = []
    for rung in rungs:
        br = base_by_rung[rung]
        dr = des_by_rung[rung]
        b_cell = baseline_map[rung]
        d_cell = designed_map[rung]

        s_deltas = [d_cell[s]["score"] - b_cell[s]["score"] for s in seeds]
        sd_m, sd_ci = mean_ci(s_deltas)

        l_deltas = [d_cell[s]["luck_adjusted_score"] - b_cell[s]["luck_adjusted_score"] for s in seeds]
        ld_m, ld_ci = mean_ci(l_deltas)

        if rung != "full_solver" and base_ref and des_ref:
            gap_widen = [
                (des_ref[s]["score"] - d_cell[s]["score"]) - (base_ref[s]["score"] - b_cell[s]["score"])
                for s in seeds
            ]
            gw_m, gw_ci = mean_ci(gap_widen)
            lgap_widen = [
                (des_ref[s]["luck_adjusted_score"] - d_cell[s]["luck_adjusted_score"])
                - (base_ref[s]["luck_adjusted_score"] - b_cell[s]["luck_adjusted_score"])
                for s in seeds
            ]
            lgw_m, lgw_ci = mean_ci(lgap_widen)
        else:
            gw_m, gw_ci = 0.0, 0.0
            lgw_m, lgw_ci = 0.0, 0.0

        out.append({
            "rung": rung,
            "in_headline_subset": rung in HEADLINE_RUNGS,
            "n": len(seeds),
            "baseline_mean_score": br["mean_score"],
            "baseline_ci95": br["ci95"],
            "designed_mean_score": dr["mean_score"],
            "designed_ci95": dr["ci95"],
            "score_shift_designed_minus_baseline": round(sd_m, 4),
            "score_shift_ci95": round(sd_ci, 4),
            "baseline_gap_vs_full_solver": br["cost_vs_full_solver"],
            "designed_gap_vs_full_solver": dr["cost_vs_full_solver"],
            "gap_widening": round(gw_m, 4),
            "gap_widening_ci95": round(gw_ci, 4),
            "baseline_luck_mean": br["luck_adjusted_mean"],
            "designed_luck_mean": dr["luck_adjusted_mean"],
            "luck_shift_designed_minus_baseline": round(ld_m, 4),
            "luck_shift_ci95": round(ld_ci, 4),
            "luck_gap_widening": round(lgw_m, 4),
            "luck_gap_widening_ci95": round(lgw_ci, 4),
            "baseline_accuracy": br["accuracy"],
            "designed_accuracy": dr["accuracy"],
            "baseline_accused_rate": br["accused_rate"],
            "designed_accused_rate": dr["accused_rate"],
            "baseline_mean_accuse_day": br["mean_accuse_day"],
            "designed_mean_accuse_day": dr["mean_accuse_day"],
        })
    return out


def collect_usage(
    run_id: str,
    client: Any,
    model_id: str,
    is_stub: bool,
    elapsed_s: float,
) -> dict[str, Any]:
    lp = ledger_path()
    matched: list[dict[str, Any]] = []
    if lp.is_file():
        matched = [r for r in read_ledger([lp]) if r.get("run_id") == run_id and r.get("ok")]

    if matched:
        tin = sum(int(r.get("in", 0) or 0) for r in matched)
        tout = sum(int(r.get("out", 0) or 0) for r in matched)
        tthink = sum(int(r.get("thinking", 0) or 0) for r in matched)
        tcached = sum(int(r.get("cached", 0) or 0) for r in matched)
        tcost = sum(float(r.get("cost_usd", 0.0) or 0.0) for r in matched)
        tlat = sum(float(r.get("latency_s", 0.0) or 0.0) for r in matched)
        calls = len(matched)
    else:
        tot = getattr(client, "total_usage", None) or {}
        tin = int(tot.get("in", 0) or 0)
        tout = int(tot.get("out", 0) or 0)
        tthink = int(tot.get("thinking", 0) or 0)
        tcached = int(tot.get("cached", 0) or 0)
        tcost = float(tot.get("cost_usd", 0.0) or 0.0)
        tlat = float(elapsed_s)
        calls = int(tot.get("calls", 0) or 0)

    if tcost <= 0.0 and not is_stub and tin > 0 and (tout + tthink) > 0:
        priced = price_cost(model_id, tin, tout + tthink, tcached)
        tcost = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)

    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": tthink,
        "cached": tcached,
        "cost_usd": round(tcost, 6),
        "latency_s": round(tlat, 3),
    }


def _fmt_opt(val: float | None, nd: int = 3, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return "n/a"
    return f"{val:+.{nd}f}" if signed else f"{val:.{nd}f}"


def render_summary_md(
    meta: dict[str, Any],
    design_doc: dict[str, Any],
    gap_doc: dict[str, Any],
) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3
    u = meta["usage"]
    sel = design_doc["selected_top_scenario"]
    cand = sel["candidate"]
    base_d = design_doc["baseline_on_design_seeds"]

    lines: list[str] = [
        f"{h1} Role 2 ({meta['role']}) - Solvability-Constrained PAIRED Scenario Designer vs Skill Ladder",
        "",
        f"{h2} Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}` via `canary.gemini.lab_client(..., feature=\"{FEATURE}\")`",
        f"- Tiers version: `{meta['tiers_version']}` (`{meta['tier']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Design seeds: `{design_doc['design_seeds']}` (`X >= {design_doc['X']:.2f}` for `SolverPolicy`, `Y <= {design_doc['Y']:.2f}` for `ObviousHeuristic`)",
        f"- Fresh skill-ladder seeds: `{gap_doc['seed_start']}..{gap_doc['seed_end']}` (`n_episodes = {meta['n_episodes']}` per rung)",
        f"- LLM proposal validity: `llm_ok = {meta['llm_ok']}`, `n_llm_valid = {meta['n_llm_valid']}`, `n_kept = {meta['n_kept']}`",
        f"- Gemini usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`",
        "",
        f"{h2} PAIRED Design Round (`{meta['tier']}`, seeds `{design_doc['design_seeds']}`)",
        "",
        f"Default v1.4 `{meta['tier']}` on seeds `{design_doc['design_seeds']}`: `SolverPolicy = {base_d['solver_mean']:+.3f}`, `ObviousHeuristic = {base_d['heuristic_mean']:+.3f}`, `regret = {base_d['regret']:+.3f}`.",
        "",
        "| Round | # | Candidate | Origin | SolverPolicy | ObviousHeuristic | Regret | Verdict |",
        "|---:|---:|---|---|---:|---:|---:|---|",
    ]

    for row in design_doc["rows"]:
        lines.append(
            f"| {row['round']} | {row['proposal_index']} | `{clean_str(row['name'])}` | `{row['origin']}` | "
            f"{_fmt_opt(row['solver'], 3, True)} | {_fmt_opt(row['agent'], 3, True)} | "
            f"{_fmt_opt(row['regret'], 3, True)} | {clean_str(row['why'])} |"
        )

    lines.extend([
        "",
        f"{h3} Top Kept Scenario: `{clean_str(sel['name'])}`",
        f"- Design-seed `SolverPolicy` mean: `{sel['solver']:+.3f}` (solvability gate `>= {design_doc['X']:.2f}` passed)",
        f"- Design-seed `ObviousHeuristic` mean: `{sel['agent']:+.3f}` (exploitability gate `<= {design_doc['Y']:.2f}` passed)",
        f"- Design-seed PAIRED regret: `{sel['regret']:+.3f}`",
        f"- Rationale: {clean_str(cand.get('rationale', ''))}",
        f"- Overridden tier knobs: `{json.dumps(cand.get('knobs') or {}, sort_keys=True)}`",
        f"- Mole DSL rules (`{len((cand.get('mole_strategy') or {}).get('rules') or [])}` rules): `{json.dumps(cand.get('mole_strategy') or {}, sort_keys=True)}`",
        "",
        f"{h2} Skill-Ladder Evaluation on Fresh Seeds `{gap_doc['seed_start']}..{gap_doc['seed_end']}` (`n={meta['n_episodes']}`)",
        "",
        "| Rung | Subset | Baseline Mean +/- CI | Designed Mean +/- CI | Baseline Gap vs Solver | Designed Gap vs Solver | Gap Widening +/- CI | Designed Luck Mean | Designed Acc |",
        "|---|---|---|---|---|---|---|---|---|",
    ])

    des_by_rung = {r["rung"]: r for r in gap_doc["designed_rows"]}
    for cr in gap_doc["comparison_rows"]:
        rung = cr["rung"]
        dr = des_by_rung[rung]
        subset = "headline" if cr["in_headline_subset"] else "extended"
        is_ref = rung == "full_solver"
        bgap = "ref" if is_ref else _fmt_opt(cr["baseline_gap_vs_full_solver"], 3, True)
        dgap = "ref" if is_ref else _fmt_opt(cr["designed_gap_vs_full_solver"], 3, True)
        gw = "ref" if is_ref else f"{_fmt_opt(cr['gap_widening'], 3, True)} +/- {_fmt_opt(cr['gap_widening_ci95'], 3)}"
        lines.append(
            f"| `{rung}` | {subset} | "
            f"{_fmt_opt(cr['baseline_mean_score'], 3, True)} +/- {_fmt_opt(cr['baseline_ci95'], 3)} | "
            f"{_fmt_opt(cr['designed_mean_score'], 3, True)} +/- {_fmt_opt(cr['designed_ci95'], 3)} | "
            f"{bgap} | {dgap} | {gw} | "
            f"{_fmt_opt(dr['luck_adjusted_mean'], 3, True)} | {dr['accuracy']:.1%} |"
        )

    lines.append("")
    return clean_str("\n".join(lines))


def run_paired_skill_designer(
    *,
    llm_spec: str = DEFAULT_LLM,
    tier: str = DEFAULT_TIER,
    design_seeds: list[int] | None = None,
    eval_seeds: list[int] | None = None,
    n_proposals: int = DEFAULT_N_PROPOSALS,
    X: float = DEFAULT_X,
    Y: float = DEFAULT_Y,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    out_dir: Path = DEFAULT_OUT_DIR,
    rungs: tuple[str, ...] = ALL_RUNGS,
    client: Any = None,
    max_retries: int | None = None,
    command_str: str | None = None,
    require_llm_kept: bool | None = None,
) -> dict[str, Any]:
    if tier not in rules.TIERS:
        raise ValueError(f"unknown tier '{tier}'; expected one of {tuple(rules.TIERS)}")
    d_seeds = list(design_seeds) if design_seeds is not None else skill_ladder.parse_seeds(DEFAULT_DESIGN_SEEDS)
    e_seeds = list(eval_seeds) if eval_seeds is not None else skill_ladder.parse_seeds(DEFAULT_EVAL_SEEDS)
    if not d_seeds or not e_seeds:
        raise ValueError("design_seeds and eval_seeds must be non-empty")

    out_dir = Path(out_dir)

    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    commit = skill_ladder.current_git_sha()
    run_id = os.environ.get("CANARY_GEMINI_RUN_ID") or f"{FEATURE}:{SUBROLE}:{ts.strftime('%Y%m%dT%H%M%SZ')}:{os.getpid()}"

    active_client = client if client is not None else build_designer_client(llm_spec, run_id=run_id, max_retries=max_retries)
    model_id, provider, is_stub = resolve_model_and_provider(llm_spec, active_client)
    must_have_llm_kept = (not is_stub) if require_llm_kept is None else bool(require_llm_kept)

    base_design_solver = evaluate_policy_mean(tier, d_seeds, None, "solver")
    base_design_heur = evaluate_policy_mean(tier, d_seeds, None, "heuristic")

    def solver_eval(cand: dict[str, Any]) -> float:
        return evaluate_policy_mean(tier, d_seeds, cand, "solver")

    def agent_eval(cand: dict[str, Any]) -> float:
        return evaluate_policy_mean(tier, d_seeds, cand, "heuristic")

    history: list[dict[str, Any]] = []
    rounds_out: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    kept_llm_rows: list[dict[str, Any]] = []
    kept_all_rows: list[dict[str, Any]] = []
    total_llm_valid = 0
    any_llm_ok = False

    t0 = time.time()
    for r_idx in range(max(1, max_rounds)):
        rep = designer.design_round(
            active_client,
            solver_eval,
            agent_eval,
            X=X,
            Y=Y,
            tier=tier,
            n=n_proposals,
            history=history if history else None,
            seed=r_idx,
        )
        rmeta = dict(rep["meta"])
        n_llm = int(rmeta.get("n_llm_valid", 0) or 0)
        llm_ok = bool(rmeta.get("llm_ok"))
        any_llm_ok = any_llm_ok or llm_ok
        total_llm_valid += n_llm

        round_rows: list[dict[str, Any]] = []
        for idx, row in enumerate(rep["rows"]):
            origin = "llm" if idx < n_llm else "fallback"
            cand_clean = sanitize_obj(row["candidate"])
            s_val = float(row["solver"])
            a_raw = float(row["agent"])
            reg_raw = float(row["regret"])
            a_val = None if math.isnan(a_raw) else round(a_raw, 4)
            reg_val = None if math.isnan(reg_raw) else round(reg_raw, 4)
            enriched = {
                "round": r_idx + 1,
                "proposal_index": idx,
                "origin": origin,
                "name": clean_str(row["name"]),
                "keep": bool(row["keep"]),
                "solver": round(s_val, 4),
                "agent": a_val,
                "regret": reg_val,
                "why": clean_str(row["why"]),
                "candidate": cand_clean,
            }
            round_rows.append(enriched)
            all_rows.append(enriched)
            if enriched["keep"]:
                kept_all_rows.append(enriched)
                if origin == "llm":
                    kept_llm_rows.append(enriched)

            history.append({
                "name": enriched["name"],
                "origin": origin,
                "solver": enriched["solver"],
                "agent": enriched["agent"],
                "keep": enriched["keep"],
                "why": enriched["why"],
                "knobs": cand_clean.get("knobs", {}),
                "note": (
                    "SolverPolicy must score >= "
                    f"{X:.2f} on {tier}: keep p_leak >= 0.75, avoid multi-day leak=none blackouts, "
                    "and use leak='random_seeded' in default/common rules (because deterministic 'newest' "
                    "or 'most_recipients' only leaks regular morning docs and starves canary traps). "
                    "Use only supported MoleView features: day, days_since_last_leak, i_am_restricted, "
                    "n_restricted_colleagues, recent_low_recipient_docs, min_recipient_count."
                ),
            })

        rounds_out.append({
            "round": r_idx + 1,
            "meta": sanitize_obj(rmeta),
            "n_llm_valid": n_llm,
            "n_kept_llm": sum(1 for x in round_rows if x["keep"] and x["origin"] == "llm"),
            "n_kept_total": sum(1 for x in round_rows if x["keep"]),
            "rows": round_rows,
        })

        if kept_llm_rows:
            break

    llm_elapsed_s = time.time() - t0
    usage = collect_usage(run_id, active_client, model_id=model_id, is_stub=is_stub, elapsed_s=llm_elapsed_s)

    if must_have_llm_kept:
        if not any_llm_ok or total_llm_valid < 1:
            raise RuntimeError(f"LLM designer failed validity check: llm_ok={any_llm_ok}, n_llm_valid={total_llm_valid}")
        if not kept_llm_rows:
            raise RuntimeError("No LLM-proposed scenario satisfied both SolverPolicy >= X and ObviousHeuristic <= Y")
        if usage["in"] <= 0 or usage["out"] <= 0:
            raise RuntimeError(f"Expected non-zero real token usage, got {usage}")

    pool_for_top = kept_llm_rows if kept_llm_rows else kept_all_rows
    if not pool_for_top:
        raise RuntimeError("No scenario kept in design_round (neither LLM nor fallback satisfied X and Y)")

    ranked_kept = sorted(
        pool_for_top,
        key=lambda r: (
            float(r["regret"]) if r["regret"] is not None else -1e9,
            float(r["solver"]),
            -int(r["round"]),
            -int(r["proposal_index"]),
        ),
        reverse=True,
    )
    top_kept = ranked_kept[0]

    baseline_rows, baseline_map = evaluate_scenario_rungs(tier=tier, seeds=e_seeds, rungs=rungs, candidate=None)
    designed_rows, designed_map = evaluate_scenario_rungs(
        tier=tier,
        seeds=e_seeds,
        rungs=rungs,
        candidate=top_kept["candidate"],
    )
    comparison_rows = build_comparison_rows(
        seeds=e_seeds,
        rungs=rungs,
        baseline_rows=baseline_rows,
        baseline_map=baseline_map,
        designed_rows=designed_rows,
        designed_map=designed_map,
    )

    des_by_rung = {r["rung"]: r for r in designed_rows}
    comp_by_rung = {r["rung"]: r for r in comparison_rows}
    headline_summary = {
        r: comp_by_rung[r]
        for r in HEADLINE_RUNGS
        if r in comp_by_rung
    }

    if command_str is None:
        prefix = (
            f"CANARY_LLM_MAX_RETRIES={os.environ['CANARY_LLM_MAX_RETRIES']} "
            if os.environ.get("CANARY_LLM_MAX_RETRIES")
            else ""
        )
        command_str = f"{prefix}PYTHONPATH=. {sys.executable} " + " ".join(shlex.quote(a) for a in sys.argv)

    n_kept_count = len(kept_llm_rows) if kept_llm_rows else len(kept_all_rows)
    meta: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "provider": provider,
        "tiers_version": rules.TIERS_VERSION,
        "tier": tier,
        "commit": commit,
        "timestamp": ts_iso,
        "command": clean_str(command_str.strip()),
        "ledger_run_id": run_id,
        "design_seeds": d_seeds,
        "eval_seeds": e_seeds,
        "n_episodes": len(e_seeds),
        "n_proposals_per_round": n_proposals,
        "n_rounds_run": len(rounds_out),
        "X": X,
        "Y": Y,
        "llm_ok": any_llm_ok,
        "n_llm_valid": total_llm_valid,
        "n_kept": n_kept_count,
        "n_kept_total": len(kept_all_rows),
        "top_scenario_name": top_kept["name"],
        "design_solver_mean": top_kept["solver"],
        "design_heuristic_mean": top_kept["agent"],
        "design_regret": top_kept["regret"],
        "eval_full_solver_mean": des_by_rung["full_solver"]["mean_score"] if "full_solver" in des_by_rung else None,
        "eval_heuristic_mean": (
            des_by_rung["heuristic_bisection"]["mean_score"]
            if "heuristic_bisection" in des_by_rung
            else None
        ),
        "usage": usage,
    }
    if is_stub:
        meta["stub"] = True

    design_doc: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "tiers_version": rules.TIERS_VERSION,
        "tier": tier,
        "commit": commit,
        "timestamp": ts_iso,
        "design_seeds": d_seeds,
        "X": X,
        "Y": Y,
        "n_proposals_per_round": n_proposals,
        "baseline_on_design_seeds": {
            "solver_mean": round(base_design_solver, 4),
            "heuristic_mean": round(base_design_heur, 4),
            "regret": round(base_design_solver - base_design_heur, 4),
        },
        "meta": {
            "llm_ok": any_llm_ok,
            "n_llm_valid": total_llm_valid,
            "n_kept": n_kept_count,
            "n_kept_total": len(kept_all_rows),
            "n_rounds": len(rounds_out),
        },
        "rounds": rounds_out,
        "rows": all_rows,
        "kept": [r["candidate"] for r in kept_llm_rows] if kept_llm_rows else [r["candidate"] for r in kept_all_rows],
        "selected_top_scenario": top_kept,
    }

    gap_doc: dict[str, Any] = {
        "title": f"PAIRED Solvability-Constrained Scenario vs Skill Ladder ({model_id})",
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": bool(rules.KNOWN_V_MODE),
        "tier": tier,
        "commit": commit,
        "timestamp": ts_iso,
        "seed_start": min(e_seeds),
        "seed_end": max(e_seeds),
        "n_episodes": len(e_seeds),
        "seeds": e_seeds,
        "rungs": [{"rung": r, "description": skill_ladder.RUNG_DESCRIPTIONS.get(r, "")} for r in rungs],
        "headline_rungs": list(HEADLINE_RUNGS),
        "selected_scenario": top_kept["candidate"],
        "designed_rows": designed_rows,
        "baseline_rows": baseline_rows,
        "comparison_rows": comparison_rows,
        "headline_comparison": headline_summary,
    }

    summary_md = render_summary_md(meta, design_doc, gap_doc)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "meta.json", meta)
    write_json(out_dir / "design_report.json", design_doc)
    write_json(out_dir / "skill_gap.json", gap_doc)
    (out_dir / "summary.md").write_text(summary_md, encoding="utf-8")

    return {
        "meta": sanitize_obj(meta),
        "design_report": sanitize_obj(design_doc),
        "skill_gap": sanitize_obj(gap_doc),
        "summary_md": summary_md,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run PAIRED solvability-constrained Gemini scenario designer vs skill ladder.")
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--tier", default=DEFAULT_TIER)
    ap.add_argument("--design-seeds", default=DEFAULT_DESIGN_SEEDS)
    ap.add_argument("--eval-seeds", default=DEFAULT_EVAL_SEEDS)
    ap.add_argument("--n-proposals", type=int, default=DEFAULT_N_PROPOSALS)
    ap.add_argument("--X", type=float, default=DEFAULT_X)
    ap.add_argument("--Y", type=float, default=DEFAULT_Y)
    ap.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    ap.add_argument("--max-retries", type=int, default=None)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)
    d_seeds = skill_ladder.parse_seeds(args.design_seeds)
    e_seeds = skill_ladder.parse_seeds(args.eval_seeds)

    raw_argv = argv if argv is not None else sys.argv[1:]
    prefix = (
        f"CANARY_LLM_MAX_RETRIES={os.environ['CANARY_LLM_MAX_RETRIES']} "
        if os.environ.get("CANARY_LLM_MAX_RETRIES")
        else ""
    )
    cmd = f"{prefix}PYTHONPATH=. {sys.executable} scripts/run_paired_skill_designer.py"
    if raw_argv:
        cmd += " " + " ".join(shlex.quote(x) for x in raw_argv)

    bundle = run_paired_skill_designer(
        llm_spec=args.llm,
        tier=args.tier,
        design_seeds=d_seeds,
        eval_seeds=e_seeds,
        n_proposals=args.n_proposals,
        X=args.X,
        Y=args.Y,
        max_rounds=args.max_rounds,
        out_dir=args.out_dir,
        max_retries=args.max_retries,
        command_str=cmd,
    )
    meta = bundle["meta"]
    u = meta["usage"]
    print(
        f"paired_skill_designer: model={meta['model_id']} llm_ok={meta['llm_ok']} "
        f"valid={meta['n_llm_valid']} kept={meta['n_kept']} top={meta['top_scenario_name']} "
        f"solver_eval={meta['eval_full_solver_mean']} heur_eval={meta['eval_heuristic_mean']} "
        f"in={u['in']} out={u['out']} think={u['thinking']} cost=${u['cost_usd']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
