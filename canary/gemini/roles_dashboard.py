from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from canary.llm.pricing import cost as price_tokens

ROOT = Path(__file__).resolve().parents[2]

ROLES: tuple[str, ...] = (
    "world_text",
    "adaptive_mole",
    "investigators",
    "failure_analyst",
    "exploit_hunter",
    "multimodal_evidence",
)

ROLE_SPECS: dict[str, dict[str, Any]] = {
    "world_text": {
        "index": "01",
        "title": "World Text & Persona Synthesis",
        "stage": "Company Construction",
        "color": "var(--s1)",
        "capabilities": ["Structured JSON", "Public-Facts Isolation", "Deterministic Cache"],
        "summary": "Synthesizes company personas, department cultures, daily Slack/email chatter, and interview answers strictly from public facts with zero mole leakage.",
        "offline_cmd": "GEMINI_API_KEY= PYTHONPATH=. python -m canary.text.build --provider template --seeds dev20",
    },
    "adaptive_mole": {
        "index": "02",
        "title": "Adaptive Mole & Mole Forge",
        "stage": "Adversarial Evolution",
        "color": "var(--s2)",
        "capabilities": ["Live Mole Decisions", "Evolutionary DSL Mutation", "PAIRED Solvability Gate"],
        "summary": "Plays the live insider mole choosing daily leaks and framing targets, and evolves mole DSL strategies constrained to stay solvable by SolverPolicy.",
        "offline_cmd": "GEMINI_API_KEY= PYTHONPATH=. python -m canary.agents.clash --llm stub --tier medium --seeds 0 1 2",
    },
    "investigators": {
        "index": "03",
        "title": "Security-Lead Investigators",
        "stage": "Bayesian Investigation",
        "color": "var(--s3)",
        "capabilities": ["13-Tool Function Calling", "Thinking Levels", "Thought-Signature Replay"],
        "summary": "Acts as head of security planting canary traps, auditing access logs, interviewing suspects, and making calibrated accusations paired against SolverPolicy.",
        "offline_cmd": "GEMINI_API_KEY= PYTHONPATH=. python scripts/verify_replay.py data/runs/committed/v1.4/gemini-4-carbon/medium-0-1",
    },
    "failure_analyst": {
        "index": "04",
        "title": "Long-Context Failure Analyst",
        "stage": "Trajectory Forensics",
        "color": "var(--s4)",
        "capabilities": ["1M Long Context", "Context Caching", "Verbatim Quote Verification"],
        "summary": "Ingests multi-episode trajectory corpora and solver regret tags in one long-context call to cluster failure modes with code-verified transcript quotes.",
        "offline_cmd": "GEMINI_API_KEY= PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out results/gemini",
    },
    "exploit_hunter": {
        "index": "05",
        "title": "Whitebox & MCP Exploit Hunter",
        "stage": "Reward & Protocol Red-Team",
        "color": "var(--s5)",
        "capabilities": ["Whole-Repo Context Pack", "High-Thinking Planner", "Live MCP Execution"],
        "summary": "Reads the full repository source to plan and execute multi-persona whitebox and blackbox MCP attacks, checked strictly against server-side ledgers.",
        "offline_cmd": "GEMINI_API_KEY= PYTHONPATH=. python -m canary.gemini.swarm --attackers 3 --planner stub --executor script --out /tmp/opencode/swarm-smoke",
    },
    "multimodal_evidence": {
        "index": "06",
        "title": "Multimodal Evidence & Vision Forensics",
        "stage": "Pixel & Chart Inspection",
        "color": "var(--s6)",
        "capabilities": ["Native Vision PNG Input", "Scanned Canary Watermarks", "Belief-Chart Forensics"],
        "summary": "Reads pixel-only canary watermarks from scanned leaked memos and diagnoses posterior belief trajectories and SOC access heatmaps directly from images.",
        "offline_cmd": "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. pytest -q tests/test_roles_dashboard.py",
    },
}

SECRET_RE = re.compile(
    r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
    r"(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|api[_-]?key|secret)"
    r"\s*[=:][ \t]*(?![A-Za-z0-9_]+=)[^\s\"',;]{4,})"
)

HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
MAX_SCAN_BYTES = 512_000


def clean_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    s = SECRET_RE.sub("[redacted]", s)
    return s.replace("\u2014", "-").replace("\u2013", "-")


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, list):
        return [redact_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {clean_str(k): redact_obj(v) for k, v in obj.items()}
    return obj


def esc(val: Any) -> str:
    return html.escape(clean_str(val), quote=True)


def md_cell(val: Any) -> str:
    txt = clean_str(val).replace("\r", " ").replace("\n", " ").strip()
    return txt.replace("|", "\\|")


def git_head(cwd: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        out = res.stdout.strip()
        return out if out else "unknown"
    except Exception:
        return "unknown"


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    except (OSError, UnicodeDecodeError):
        return []
    return rows


def _int_from(d: dict[str, Any], keys: tuple[str, ...]) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and not math.isnan(v):
            return int(v)
    return 0


def _float_from(d: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and not math.isnan(v):
            return float(v)
    return None


def _scan_run_for_secrets(run_dir: Path) -> bool:
    for fp in sorted(run_dir.rglob("*")):
        if not fp.is_file():
            continue
        if fp.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".gz", ".zip", ".pyc"):
            continue
        try:
            if fp.stat().st_size > MAX_SCAN_BYTES:
                continue
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if SECRET_RE.search(txt):
            return True
    return False


def _normalize_model_id(meta: dict[str, Any], companion: dict[str, Any]) -> str:
    for src in (meta, companion):
        for k in ("model_id", "model", "exec_model"):
            val = src.get(k)
            if isinstance(val, str) and val.strip():
                return clean_str(val.strip())
        models = src.get("models")
        if isinstance(models, list) and models:
            first = str(models[0]).strip()
            if first:
                return clean_str(first)
        agent = src.get("agent")
        if isinstance(agent, str) and agent.strip():
            raw = agent.strip()
            for prefix in ("opencode:google/", "opencode:", "gemini:", "google/", "openai:", "codex:"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):]
            if raw:
                return clean_str(raw)
    return "unknown"


def _load_episodes(run_dir: Path) -> list[dict[str, Any]]:
    eps = _load_jsonl(run_dir / "episodes.jsonl")
    if eps:
        return eps
    ep_json = _load_json(run_dir / "episodes.json")
    if isinstance(ep_json, list):
        return [e for e in ep_json if isinstance(e, dict)]
    if isinstance(ep_json, dict) and isinstance(ep_json.get("episodes"), list):
        return [e for e in ep_json["episodes"] if isinstance(e, dict)]
    return []


def _extract_usage(
    meta: dict[str, Any],
    episodes: list[dict[str, Any]],
    swarm_doc: dict[str, Any] | None,
    model_id: str,
) -> dict[str, Any]:
    u = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    tin = _int_from(u, ("in", "prompt_tokens", "input_tokens", "prompt_token_count", "tokens_in"))
    tout = _int_from(u, ("out", "out_tokens", "output_tokens", "candidates_tokens", "candidates_token_count", "tokens_out"))
    tthink = _int_from(u, ("thinking", "thinking_tokens", "thoughts_tokens", "thoughts_token_count", "tokens_thinking"))
    tcached = _int_from(u, ("cached", "cached_in", "cached_tokens", "cached_content_token_count", "tokens_cached"))
    calls = _int_from(u, ("calls", "n_calls", "api_calls"))
    cost_val = _float_from(u, ("cost_usd_est", "cost_usd"))

    if tin == 0 and tout == 0 and tthink == 0 and episodes:
        for ep in episodes:
            em = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            eu = em.get("usage") if isinstance(em.get("usage"), dict) else {}
            tin += _int_from(eu, ("in", "prompt_tokens", "input_tokens", "tokens_in"))
            tout += _int_from(eu, ("out", "out_tokens", "output_tokens", "tokens_out"))
            tthink += _int_from(eu, ("thinking", "thinking_tokens", "thoughts_tokens"))
            tcached += _int_from(eu, ("cached", "cached_in", "cached_tokens"))
            calls += _int_from(eu, ("calls", "n_calls"))
            ec = _float_from(eu, ("cost_usd_est", "cost_usd"))
            if ec is not None:
                cost_val = (cost_val or 0.0) + ec

    if tin == 0 and tout == 0 and tthink == 0 and isinstance(swarm_doc, dict):
        for att in swarm_doc.get("attempts") or []:
            if not isinstance(att, dict):
                continue
            pm = att.get("planner_meta") if isinstance(att.get("planner_meta"), dict) else {}
            em = att.get("executor_meta") if isinstance(att.get("executor_meta"), dict) else {}
            tin += _int_from(pm, ("in",)) + _int_from(em, ("exec_in", "in"))
            tout += _int_from(pm, ("out",)) + _int_from(em, ("exec_out", "out"))
            tthink += _int_from(pm, ("thinking",)) + _int_from(em, ("thinking",))
            tcached += _int_from(pm, ("cached_tokens", "cached"))
            if pm:
                calls += 1
            calls += _int_from(em, ("turns", "calls"))
            ec = _float_from(em, ("exec_cost_usd", "cost_usd"))
            if ec is not None:
                cost_val = (cost_val or 0.0) + ec

    if (cost_val is None or cost_val <= 0.0) and (tin > 0 or tout > 0 or tthink > 0):
        est = price_tokens(model_id, tin, tout + tthink, tcached)
        cost_val = float(est.get("cost_usd_est", est.get("cost_usd", 0.0)))

    return {
        "in": max(0, tin),
        "out": max(0, tout),
        "thinking": max(0, tthink),
        "cached": max(0, tcached),
        "calls": max(0, calls),
        "cost_usd": round(float(cost_val or 0.0), 4),
    }


def _fmt_pct(val: float) -> str:
    ratio = val / 100.0 if val > 1.0001 else val
    return f"{ratio * 100.0:.0f}%"


def _build_key_metric(
    role: str,
    meta: dict[str, Any],
    episodes: list[dict[str, Any]],
    companions: dict[str, Any],
    paired_solver_scores: list[float] | None = None,
) -> str:
    explicit = meta.get("key_metric")
    if isinstance(explicit, str) and explicit.strip():
        return clean_str(explicit.strip())

    if role == "world_text":
        parts: list[str] = []
        if meta.get("n_worlds") is not None:
            parts.append(f"{int(meta['n_worlds'])} worlds")
        if meta.get("truth_leak_violations") is not None:
            parts.append(f"{int(meta['truth_leak_violations'])} truth leaks")
        if meta.get("lint_violations") is not None:
            parts.append(f"{int(meta['lint_violations'])} lint errs")
        if not parts and meta.get("llm_ok_count") is not None:
            parts.append(f"{int(meta['llm_ok_count'])} LLM worlds ok")
        return ", ".join(parts) if parts else "verified world text"

    if role == "adaptive_mole":
        if meta.get("investigator_score") is not None and meta.get("solver_score") is not None:
            inv_s = float(meta["investigator_score"])
            sol_s = float(meta["solver_score"])
            return f"investigator {inv_s:+.3f} vs solver {sol_s:+.3f}"
        if meta.get("best_fitness") is not None:
            fit = float(meta["best_fitness"])
            extra = ""
            if meta.get("fresh_solver_accuracy") is not None:
                extra = f", solver acc {_fmt_pct(float(meta['fresh_solver_accuracy']))}"
            elif meta.get("n_valid_llm_children") is not None:
                extra = f", {int(meta['n_valid_llm_children'])} LLM children"
            return f"fitness {fit:.3f}{extra}"
        if meta.get("n_kept") is not None and meta.get("n_llm_valid") is not None:
            return f"kept {int(meta['n_kept'])}/{int(meta['n_llm_valid'])} solvable scenarios"
        if meta.get("solver_accuracy") is not None:
            acc = _fmt_pct(float(meta["solver_accuracy"]))
            if meta.get("heuristic_mean") is not None:
                return f"solver acc {acc}, heuristic {float(meta['heuristic_mean']):+.3f}"
            return f"solver acc {acc}"
        if episodes:
            scores = [float(e["score"]) for e in episodes if isinstance(e.get("score"), (int, float))]
            if scores:
                return f"mean {sum(scores) / len(scores):+.3f} (n={len(scores)})"
        return "adaptive mole verified"

    if role == "investigators":
        lvl = meta.get("levels_summary")
        if isinstance(lvl, dict) and lvl:
            segs: list[str] = []
            for k in ("minimal", "low", "medium", "high"):
                if isinstance(lvl.get(k), dict) and isinstance(lvl[k].get("mean_score"), (int, float)):
                    segs.append(f"{k} {float(lvl[k]['mean_score']):+.3f}")
                elif isinstance(lvl.get(k), (int, float)):
                    segs.append(f"{k} {float(lvl[k]):+.3f}")
            if segs:
                return " -> ".join(segs)
        valid_eps = [
            e for e in episodes
            if e.get("end_reason") != "error"
            and (e.get("meta") or {}).get("valid") is not False
            and isinstance(e.get("score"), (int, float))
        ]
        if valid_eps:
            mean_s = sum(float(e["score"]) for e in valid_eps) / len(valid_eps)
            acc = sum(1 for e in valid_eps if e.get("correct")) / len(valid_eps)
            if paired_solver_scores and len(paired_solver_scores) == len(valid_eps):
                sol_m = sum(paired_solver_scores) / len(paired_solver_scores)
                return f"mean {mean_s:+.3f} vs solver {sol_m:+.3f} (acc {acc:.0%}, n={len(valid_eps)})"
            return f"mean {mean_s:+.3f}, acc {acc:.0%} (n={len(valid_eps)})"
        summ = meta.get("summary")
        if isinstance(summ, dict):
            for tier_k, tv in summ.items():
                if isinstance(tv, dict) and isinstance(tv.get("mean"), (int, float)):
                    acc_v = float(tv.get("accuracy", 0.0))
                    n_v = int(tv.get("n", 0))
                    return f"{tier_k}: mean {float(tv['mean']):+.3f}, acc {acc_v:.0%} (n={n_v})"
        if isinstance(meta.get("mean_score"), (int, float)):
            return f"mean {float(meta['mean_score']):+.3f}"
        return "investigator run"

    if role == "failure_analyst":
        parts = []
        if meta.get("n_episodes_packed") is not None:
            parts.append(f"{int(meta['n_episodes_packed'])} eps packed")
        rep = companions.get("report")
        if isinstance(rep, dict) and isinstance(rep.get("clusters"), list):
            parts.append(f"{len(rep['clusters'])} clusters")
        if meta.get("verified_quotes_pct") is not None:
            parts.append(f"{_fmt_pct(float(meta['verified_quotes_pct']))} verified quotes")
        return ", ".join(parts) if parts else "long-context failure report"

    if role == "exploit_hunter":
        sw = companions.get("swarm")
        sm = companions.get("summary")
        att_n = meta.get("attempts")
        if att_n is None and isinstance(sw, dict):
            att_n = (sw.get("counts") or {}).get("attempts")
        if att_n is None:
            att_n = meta.get("runs")
        if att_n is None and isinstance(sm, dict):
            att_n = sm.get("runs")

        exp_n = meta.get("exploits")
        if exp_n is None:
            exp_n = meta.get("exploits_found")
        if exp_n is None and isinstance(sw, dict):
            exp_n = (sw.get("counts") or {}).get("exploits")
        if exp_n is None and isinstance(sm, dict):
            exp_n = sm.get("exploits")

        viol_n = meta.get("invariant_violations")
        if viol_n is None and isinstance(sw, dict):
            viol_n = (sw.get("counts") or {}).get("invariant_violations")

        parts = []
        if att_n is not None:
            parts.append(f"{int(att_n)} attempts")
        if exp_n is not None:
            parts.append(f"{int(exp_n)} exploits")
        if viol_n is not None:
            parts.append(f"{int(viol_n)} violations")
        return ", ".join(parts) if parts else "ledger-verified red-team audit"

    if role == "multimodal_evidence":
        parts = []
        if meta.get("n_images_read_by_model") is not None:
            parts.append(f"{int(meta['n_images_read_by_model'])} images")
        elif meta.get("n_charts_analyzed") is not None:
            parts.append(f"{int(meta['n_charts_analyzed'])} charts")
        if meta.get("variant_vision_accuracy") is not None:
            parts.append(f"vision acc {_fmt_pct(float(meta['variant_vision_accuracy']))}")
        elif meta.get("visual_threshold_accuracy") is not None:
            parts.append(f"threshold acc {_fmt_pct(float(meta['visual_threshold_accuracy']))}")
        if meta.get("multimodal_mean_score") is not None and meta.get("blind_ablation_mean_score") is not None:
            mm = float(meta["multimodal_mean_score"])
            bl = float(meta["blind_ablation_mean_score"])
            parts.append(f"score {mm:+.3f} vs blind {bl:+.3f}")
        return ", ".join(parts) if parts else "multimodal vision forensics"

    return "committed run"


def _discover_candidates(root: Path) -> list[tuple[Path, str, dict[str, Any]]]:
    found: list[tuple[Path, str, dict[str, Any]]] = []

    roles_dir = root / "results" / "gemini_roles"
    if roles_dir.is_dir():
        accepted_roles: list[Path] = []
        meta_files = sorted(roles_dir.rglob("meta.json"), key=lambda p: (len(p.parts), p.as_posix()))
        for mf in meta_files:
            meta = _load_json(mf)
            if not isinstance(meta, dict):
                continue
            cdir = mf.parent
            if any(anc in cdir.parents for anc in accepted_roles):
                if not (meta.get("role") and meta.get("subrole")):
                    continue
            accepted_roles.append(cdir)
            found.append((cdir, "gemini_roles", meta))

    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    if v14_dir.is_dir():
        accepted_v14: list[Path] = []
        meta_files = sorted(v14_dir.rglob("meta.json"), key=lambda p: (len(p.parts), p.as_posix()))
        for mf in meta_files:
            rel_parts = mf.relative_to(v14_dir).parts
            if rel_parts and rel_parts[0] in ("reference", "superseded"):
                continue
            meta = _load_json(mf)
            if not isinstance(meta, dict):
                continue
            cdir = mf.parent
            if any(anc in cdir.parents for anc in accepted_v14):
                if not (meta.get("role") and meta.get("subrole")):
                    continue
            probe_str = " ".join(
                str(meta.get(k) or "") for k in ("role", "model_id", "model", "agent", "provider")
            ).lower()
            if meta.get("role") not in ROLES and "gemini" not in probe_str:
                continue
            accepted_v14.append(cdir)
            found.append((cdir, "v1.4", meta))

    return found


def _load_solver_reference(root: Path, needed: set[tuple[str, int]]) -> dict[tuple[str, int], dict[str, Any]]:
    solver_map: dict[tuple[str, int], dict[str, Any]] = {}
    ref_dir = root / "data" / "runs" / "committed" / "v1.4" / "reference"
    if ref_dir.is_dir():
        for ep_file in sorted(ref_dir.rglob("episodes.jsonl")):
            for ep in _load_jsonl(ep_file):
                if ep.get("agent") == "solver" and isinstance(ep.get("tier"), str) and isinstance(ep.get("seed"), int):
                    solver_map[(ep["tier"], int(ep["seed"]))] = ep

    missing = sorted(
        pair for pair in needed
        if pair not in solver_map and pair[0] in ("easy", "medium", "hard")
    )
    if missing and len(missing) <= 40:
        try:
            from canary.eval import make_env, run_episode
            from canary.solver.policy import SolverPolicy

            for tier, seed in missing:
                res = run_episode(make_env(tier, seed), SolverPolicy())
                d = dataclasses.asdict(res) if dataclasses.is_dataclass(res) else dict(res)
                d["agent"] = "solver"
                solver_map[(tier, seed)] = d
        except Exception:
            pass
    return solver_map


def _mean_ci(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return 0.0, 0.0
    m = sum(vals) / len(vals)
    if len(vals) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
    return m, 1.96 * math.sqrt(var / len(vals))


def _compute_paired(
    runs: list[dict[str, Any]],
    raw_episodes_by_run: dict[str, list[dict[str, Any]]],
    solver_map: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    chosen: dict[tuple[str, int], tuple[dict[str, Any], dict[str, Any], int]] = {}
    for run in runs:
        if run["role"] != "investigators" or run["model_id"] != "gemini-4-carbon":
            continue
        if run["meta_flags"]["fake_env"] or run["meta_flags"]["smoke"]:
            continue
        priority = 2 if run["source_kind"] == "v1.4" and not run["meta_flags"]["hinted"] else (1 if not run["meta_flags"]["hinted"] else 0)
        for ep in raw_episodes_by_run.get(run["run_folder"], []):
            if ep.get("end_reason") == "error" or (ep.get("meta") or {}).get("valid") is False:
                continue
            tier = ep.get("tier") or run["tier"]
            seed = ep.get("seed")
            if not isinstance(tier, str) or not isinstance(seed, int) or not isinstance(ep.get("score"), (int, float)):
                continue
            key = (tier, int(seed))
            prev = chosen.get(key)
            if prev is None or priority > prev[2]:
                chosen[key] = (ep, run, priority)

    seed_rows: list[dict[str, Any]] = []
    for (tier, seed), (ep, run, _) in sorted(chosen.items(), key=lambda x: (x[0][0] != "medium", x[0][0], x[0][1])):
        sol = solver_map.get((tier, seed))
        sol_score: float | None = None
        sol_correct: bool | None = None
        sol_day: int | None = None
        if isinstance(sol, dict) and isinstance(sol.get("score"), (int, float)):
            sol_score = float(sol["score"])
            sol_correct = bool(sol.get("correct"))
            sol_day = int(sol["final_day"]) if isinstance(sol.get("final_day"), int) else None
        elif isinstance(ep.get("solver_score"), (int, float)):
            sol_score = float(ep["solver_score"])
        if sol_score is None:
            continue
        c_score = float(ep["score"])
        seed_rows.append({
            "tier": tier,
            "seed": seed,
            "carbon_score": round(c_score, 4),
            "solver_score": round(sol_score, 4),
            "diff": round(c_score - sol_score, 4),
            "carbon_correct": bool(ep.get("correct")),
            "solver_correct": sol_correct,
            "carbon_accused": bool(ep.get("accused")),
            "carbon_day": int(ep["final_day"]) if isinstance(ep.get("final_day"), int) else None,
            "solver_day": sol_day,
            "run_folder": run["run_folder"],
        })

    def _agg_tier(label: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
        c_scores = [r["carbon_score"] for r in subset]
        s_scores = [r["solver_score"] for r in subset]
        diffs = [r["diff"] for r in subset]
        cm, cci = _mean_ci(c_scores)
        sm, sci = _mean_ci(s_scores)
        dm, dci = _mean_ci(diffs)
        c_acc = sum(1 for r in subset if r["carbon_correct"]) / len(subset)
        s_known = [r for r in subset if r["solver_correct"] is not None]
        s_acc = (sum(1 for r in s_known if r["solver_correct"]) / len(s_known)) if s_known else None
        c_days = [r["carbon_day"] for r in subset if r["carbon_day"] is not None and r["carbon_accused"]]
        s_days = [r["solver_day"] for r in subset if r["solver_day"] is not None]
        ratio = (cm / sm) if sm > 1e-9 else None
        return {
            "tier": label,
            "n": len(subset),
            "seeds": [r["seed"] for r in subset],
            "carbon_mean": round(cm, 4),
            "carbon_ci": round(cci, 4),
            "solver_mean": round(sm, 4),
            "solver_ci": round(sci, 4),
            "paired_diff": round(dm, 4),
            "diff_ci": round(dci, 4),
            "ratio": round(ratio, 4) if ratio is not None else None,
            "carbon_accuracy": round(c_acc, 4),
            "solver_accuracy": round(s_acc, 4) if s_acc is not None else None,
            "carbon_accuse_day": round(sum(c_days) / len(c_days), 2) if c_days else None,
            "solver_accuse_day": round(sum(s_days) / len(s_days), 2) if s_days else None,
        }

    tiers_present: list[str] = []
    for t in ("easy", "medium", "hard"):
        if any(r["tier"] == t for r in seed_rows):
            tiers_present.append(t)
    for r in seed_rows:
        if r["tier"] not in tiers_present:
            tiers_present.append(r["tier"])

    tier_summaries = [_agg_tier(t, [r for r in seed_rows if r["tier"] == t]) for t in tiers_present]
    overall = _agg_tier("overall", seed_rows) if seed_rows else None
    return {
        "tiers": tier_summaries,
        "overall": overall,
        "seeds": seed_rows,
    }


def collect_roles_data(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    candidates = _discover_candidates(root_path)

    prelim_runs: list[dict[str, Any]] = []
    raw_episodes_by_run: dict[str, list[dict[str, Any]]] = {}
    needed_solver_pairs: set[tuple[str, int]] = set()

    for cdir, source_kind, meta in candidates:
        rel_folder = cdir.relative_to(root_path).as_posix()
        role_raw = meta.get("role")
        role: str | None = None
        if isinstance(role_raw, str) and role_raw in ROLES:
            role = role_raw
        elif source_kind == "gemini_roles":
            rel_roles = cdir.relative_to(root_path / "results" / "gemini_roles").parts
            if rel_roles and rel_roles[0] in ROLES:
                role = rel_roles[0]
        elif source_kind == "v1.4":
            role = "investigators"
        if role not in ROLES:
            continue

        companions: dict[str, Any] = {}
        for cname in ("swarm", "summary", "report", "results", "diagnoses", "comparison", "solver_check"):
            cj = _load_json(cdir / f"{cname}.json")
            if isinstance(cj, dict):
                companions[cname] = cj

        primary_comp = companions.get("swarm") or companions.get("summary") or companions.get("report") or {}
        model_id = _normalize_model_id(meta, primary_comp)

        commit_raw = ""
        for k in ("commit", "git_sha"):
            v = meta.get(k) or primary_comp.get(k)
            if isinstance(v, str) and v.strip():
                commit_raw = v.strip()
                break

        subrole_raw = meta.get("subrole")
        if isinstance(subrole_raw, str) and subrole_raw.strip():
            subrole = clean_str(subrole_raw.strip())
        elif meta.get("hint"):
            subrole = f"hint_{clean_str(meta.get('tier') or cdir.name)}"
        elif cdir.name != role:
            subrole = clean_str(cdir.name)
        else:
            subrole = "primary"

        episodes = _load_episodes(cdir)
        raw_episodes_by_run[rel_folder] = episodes
        usage = _extract_usage(meta, episodes, companions.get("swarm"), model_id)
        secret_found = _scan_run_for_secrets(cdir)

        tier_val = meta.get("tier") if isinstance(meta.get("tier"), str) else ""
        if role == "investigators":
            for ep in episodes:
                t = ep.get("tier") or tier_val
                s = ep.get("seed")
                if isinstance(t, str) and isinstance(s, int):
                    needed_solver_pairs.add((t, int(s)))

        reasons: list[str] = []
        if not model_id.startswith("gemini-"):
            reasons.append("non-gemini model")
        if not HEX_SHA_RE.match(commit_raw):
            reasons.append("invalid commit")
        if usage["in"] <= 0 or (usage["out"] + usage["thinking"]) <= 0:
            reasons.append("zero tokens")
        if bool(meta.get("fake_env")):
            reasons.append("fake_env")
        if bool(meta.get("smoke")):
            reasons.append("smoke")
        if bool(meta.get("plumbing_only")):
            reasons.append("plumbing_only")
        if str(meta.get("source") or "").startswith("fallback"):
            reasons.append("fallback")
        if secret_found:
            reasons.append("secret detected")

        verified = len(reasons) == 0
        cmd_raw = meta.get("command") or meta.get("provenance") or ""

        prelim_runs.append({
            "role": role,
            "subrole": subrole,
            "model_id": model_id,
            "commit": clean_str(commit_raw) if commit_raw else "-",
            "run_folder": clean_str(rel_folder),
            "usage": usage,
            "verified": verified,
            "verified_reasons": reasons,
            "verified_label": "yes" if verified else f"no ({', '.join(reasons)})",
            "timestamp": clean_str(meta.get("timestamp") or ""),
            "command": clean_str(cmd_raw),
            "tier": clean_str(tier_val),
            "source_kind": source_kind,
            "meta_flags": {
                "fake_env": bool(meta.get("fake_env")),
                "smoke": bool(meta.get("smoke")),
                "hinted": bool(meta.get("hint")),
            },
            "_meta": meta,
            "_companions": companions,
        })

    solver_map = _load_solver_reference(root_path, needed_solver_pairs)

    runs: list[dict[str, Any]] = []
    for r in prelim_runs:
        eps = raw_episodes_by_run.get(r["run_folder"], [])
        paired_scores: list[float] | None = None
        if r["role"] == "investigators" and eps:
            valid_eps = [
                e for e in eps
                if e.get("end_reason") != "error"
                and (e.get("meta") or {}).get("valid") is not False
                and isinstance(e.get("score"), (int, float))
            ]
            ps: list[float] = []
            for e in valid_eps:
                t = e.get("tier") or r["tier"]
                s = e.get("seed")
                sol_ep = solver_map.get((t, int(s))) if isinstance(t, str) and isinstance(s, int) else None
                if isinstance(sol_ep, dict) and isinstance(sol_ep.get("score"), (int, float)):
                    ps.append(float(sol_ep["score"]))
            if valid_eps and len(ps) == len(valid_eps):
                paired_scores = ps

        key_metric = _build_key_metric(r["role"], r["_meta"], eps, r["_companions"], paired_scores)
        out_r = {k: v for k, v in r.items() if not k.startswith("_")}
        out_r["key_metric"] = clean_str(key_metric)
        runs.append(out_r)

    runs.sort(
        key=lambda r: (
            ROLES.index(r["role"]),
            not (r["verified"] and r["model_id"] == "gemini-4-carbon"),
            not r["verified"],
            r["run_folder"],
        )
    )

    paired = _compute_paired(runs, raw_episodes_by_run, solver_map)

    roles_summary: list[dict[str, Any]] = []
    for role in ROLES:
        spec = ROLE_SPECS[role]
        rr = [r for r in runs if r["role"] == role]
        ver_carbon = [r for r in rr if r["verified"] and r["model_id"] == "gemini-4-carbon"]
        ver_any = [r for r in rr if r["verified"]]
        t_in = sum(r["usage"]["in"] for r in rr)
        t_out = sum(r["usage"]["out"] for r in rr)
        t_think = sum(r["usage"]["thinking"] for r in rr)
        t_cache = sum(r["usage"]["cached"] for r in rr)
        t_calls = sum(r["usage"]["calls"] for r in rr)
        t_cost = round(sum(r["usage"]["cost_usd"] for r in rr), 4)
        roles_summary.append({
            "role": role,
            "index": spec["index"],
            "title": spec["title"],
            "stage": spec["stage"],
            "color": spec["color"],
            "capabilities": list(spec["capabilities"]),
            "summary": spec["summary"],
            "offline_cmd": spec["offline_cmd"],
            "runs": rr,
            "n_runs": len(rr),
            "n_verified": len(ver_any),
            "n_carbon_verified": len(ver_carbon),
            "role_verified": len(ver_carbon) > 0,
            "tokens_in": t_in,
            "tokens_out": t_out,
            "tokens_thinking": t_think,
            "tokens_cached": t_cache,
            "calls": t_calls,
            "cost_usd": t_cost,
        })

    verified_roles = [rs["role"] for rs in roles_summary if rs["role_verified"]]
    tot_in = sum(rs["tokens_in"] for rs in roles_summary)
    tot_out = sum(rs["tokens_out"] for rs in roles_summary)
    tot_think = sum(rs["tokens_thinking"] for rs in roles_summary)
    tot_cache = sum(rs["tokens_cached"] for rs in roles_summary)
    tot_calls = sum(rs["calls"] for rs in roles_summary)
    tot_cost = round(sum(rs["cost_usd"] for rs in roles_summary), 4)
    models_seen = sorted({r["model_id"] for r in runs if r["model_id"] != "unknown"})

    return redact_obj({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_head(root_path),
        "roles": roles_summary,
        "runs": runs,
        "paired_comparison": paired,
        "totals": {
            "n_roles_total": len(ROLES),
            "n_roles_verified": len(verified_roles),
            "verified_roles": verified_roles,
            "all_roles_verified": len(verified_roles) == len(ROLES),
            "n_runs": len(runs),
            "n_verified_runs": sum(1 for r in runs if r["verified"]),
            "tokens_in": tot_in,
            "tokens_out": tot_out,
            "tokens_thinking": tot_think,
            "tokens_cached": tot_cache,
            "calls": tot_calls,
            "cost_usd": tot_cost,
            "models": models_seen,
        },
    })


def _fmt_tokens_pair(usage: dict[str, Any]) -> str:
    tin = int(usage.get("in", 0))
    tout = int(usage.get("out", 0))
    tthink = int(usage.get("thinking", 0))
    if tthink > 0:
        return f"{tin:,} / {tout:,} (+{tthink:,} think)"
    return f"{tin:,} / {tout:,}"


def render_roles_markdown(data: dict[str, Any]) -> str:
    tot = data["totals"]
    lines: list[str] = [
        "# Gemini 6-Role Showcase Matrix",
        "",
        (
            f"Verified roles: **{tot['n_roles_verified']} / {tot['n_roles_total']}** | "
            f"Committed runs: **{tot['n_runs']}** ({tot['n_verified_runs']} verified) | "
            f"Tokens (in / out / thinking): **{tot['tokens_in']:,} / {tot['tokens_out']:,} / {tot['tokens_thinking']:,}** | "
            f"Estimated cost: **${tot['cost_usd']:.4f}**"
        ),
        "",
        "| Role | Subrole | Model ID | Commit | Run Folder | Key Metric | Tokens (in/out) | Verified |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for rs in data["roles"]:
        role = rs["role"]
        if not rs["runs"]:
            lines.append(f"| {md_cell(role)} | pending | - | - | - | pending | 0 / 0 | pending |")
            continue
        for run in rs["runs"]:
            commit_cell = f"`{md_cell(run['commit'])}`" if run["commit"] != "-" else "-"
            folder_cell = f"`{md_cell(run['run_folder'])}`"
            tok_cell = _fmt_tokens_pair(run["usage"])
            lines.append(
                f"| {md_cell(run['role'])} | {md_cell(run['subrole'])} | {md_cell(run['model_id'])} | "
                f"{commit_cell} | {folder_cell} | {md_cell(run['key_metric'])} | "
                f"{md_cell(tok_cell)} | {md_cell(run['verified_label'])} |"
            )

    paired = data["paired_comparison"]
    if paired["tiers"]:
        lines.extend([
            "",
            "## Paired gemini-4-carbon vs SolverPolicy Comparison",
            "",
            "| Tier | Paired Seeds | gemini-4-carbon Mean | SolverPolicy Mean | Score / Solver | Paired Diff +/- 95% CI | Carbon Accuracy | Solver Accuracy |",
            "|---|---|---|---|---|---|---|---|",
        ])
        rows_to_render = list(paired["tiers"])
        if paired["overall"] and len(paired["tiers"]) > 1:
            rows_to_render.append(paired["overall"])
        for pr in rows_to_render:
            ratio_txt = f"{pr['ratio'] * 100.0:.0f}%" if pr["ratio"] is not None else "n/a"
            s_acc_txt = f"{pr['solver_accuracy'] * 100.0:.0f}%" if pr["solver_accuracy"] is not None else "n/a"
            lines.append(
                f"| {md_cell(pr['tier'])} | {pr['n']} | {pr['carbon_mean']:+.3f} | {pr['solver_mean']:+.3f} | "
                f"{ratio_txt} | {pr['paired_diff']:+.3f} +/- {pr['diff_ci']:.3f} | "
                f"{pr['carbon_accuracy'] * 100.0:.0f}% | {s_acc_txt} |"
            )

    lines.extend([
        "",
        "## Token & Cost Breakdown by Role",
        "",
        "| Role | Runs | Verified | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for rs in data["roles"]:
        lines.append(
            f"| {md_cell(rs['role'])} | {rs['n_runs']} | {rs['n_verified']} | {rs['calls']:,} | "
            f"{rs['tokens_in']:,} | {rs['tokens_out']:,} | {rs['tokens_thinking']:,} | "
            f"{rs['tokens_cached']:,} | ${rs['cost_usd']:.4f} |"
        )
    lines.append(
        f"| **total** | **{tot['n_runs']}** | **{tot['n_verified_runs']}** | **{tot['calls']:,}** | "
        f"**{tot['tokens_in']:,}** | **{tot['tokens_out']:,}** | **{tot['tokens_thinking']:,}** | "
        f"**{tot['tokens_cached']:,}** | **${tot['cost_usd']:.4f}** |"
    )

    lines.extend([
        "",
        "## Offline Keyless Reproduction",
        "",
        "```bash",
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out results/gemini",
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. pytest -q tests/test_roles_dashboard.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def _svg_paired_chart(paired: dict[str, Any]) -> str:
    rows = list(paired.get("tiers") or [])
    if paired.get("overall") and len(rows) > 1:
        rows.append(paired["overall"])
    if not rows:
        return '<div class="empty-box">No paired gemini-4-carbon vs SolverPolicy episodes available yet.</div>'

    width = 640
    row_h = 64
    top = 28
    left = 110
    right = 90
    height = top + len(rows) * row_h + 24
    vals = [abs(float(r["carbon_mean"])) for r in rows] + [abs(float(r["solver_mean"])) for r in rows] + [1.0]
    min_v = min([0.0] + [float(r["carbon_mean"]) for r in rows] + [float(r["solver_mean"]) for r in rows])
    max_v = max([1.0] + vals)
    span = max(0.01, max_v - min_v)
    plot_w = width - left - right
    zero_x = left + (0.0 - min_v) / span * plot_w

    parts: list[str] = [
        f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Paired gemini-4-carbon vs SolverPolicy mean score">',
        f'<line x1="{zero_x:.1f}" y1="{top - 8}" x2="{zero_x:.1f}" y2="{height - 16}" class="axis-line"/>',
        f'<rect x="{left}" y="4" width="12" height="10" rx="2" fill="var(--s3)"/>',
        f'<text x="{left + 18}" y="13" class="svg-leg">gemini-4-carbon</text>',
        f'<rect x="{left + 145}" y="4" width="12" height="10" rx="2" fill="var(--s1)"/>',
        f'<text x="{left + 163}" y="13" class="svg-leg">SolverPolicy (same seeds)</text>',
    ]

    for idx, r in enumerate(rows):
        y0 = top + idx * row_h
        label = f"{r['tier']} (n={r['n']})"
        parts.append(f'<text x="{left - 10}" y="{y0 + 26}" text-anchor="end" class="svg-label">{esc(label)}</text>')
        for bar_i, (val, col) in enumerate(((float(r["carbon_mean"]), "var(--s3)"), (float(r["solver_mean"]), "var(--s1)"))):
            by = y0 + 6 + bar_i * 22
            vx = left + (val - min_v) / span * plot_w
            bx = min(zero_x, vx)
            bw = max(2.0, abs(vx - zero_x))
            tx = vx + 6 if val >= 0 else vx - 6
            anchor = "start" if val >= 0 else "end"
            parts.append(f'<rect x="{bx:.1f}" y="{by}" width="{bw:.1f}" height="16" rx="3" fill="{col}"/>')
            parts.append(f'<text x="{tx:.1f}" y="{by + 12}" text-anchor="{anchor}" class="svg-val">{esc(f"{val:+.3f}")}</text>')

    parts.append("</svg>")
    return "".join(parts)


def _svg_token_bars(roles_summary: list[dict[str, Any]]) -> str:
    width = 580
    row_h = 38
    top = 28
    left = 148
    right = 96
    height = top + len(roles_summary) * row_h + 12
    plot_w = width - left - right
    totals = [rs["tokens_in"] + rs["tokens_out"] + rs["tokens_thinking"] for rs in roles_summary]
    max_tot = max([1] + totals)

    parts: list[str] = [
        f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Token breakdown across 6 roles">',
        f'<rect x="{left}" y="4" width="10" height="10" rx="2" fill="var(--s1)"/>',
        f'<text x="{left + 15}" y="13" class="svg-leg">Input</text>',
        f'<rect x="{left + 68}" y="4" width="10" height="10" rx="2" fill="var(--s3)"/>',
        f'<text x="{left + 83}" y="13" class="svg-leg">Output</text>',
        f'<rect x="{left + 144}" y="4" width="10" height="10" rx="2" fill="var(--s2)"/>',
        f'<text x="{left + 159}" y="13" class="svg-leg">Thinking</text>',
    ]
    for idx, rs in enumerate(roles_summary):
        y = top + idx * row_h
        t_in = rs["tokens_in"]
        t_out = rs["tokens_out"]
        t_th = rs["tokens_thinking"]
        tot = t_in + t_out + t_th
        w_in = plot_w * (t_in / max_tot)
        w_out = plot_w * (t_out / max_tot)
        w_th = plot_w * (t_th / max_tot)
        parts.append(f'<text x="{left - 8}" y="{y + 18}" text-anchor="end" class="svg-label">{esc(rs["role"])}</text>')
        x_cur = float(left)
        for seg_w, col in ((w_in, "var(--s1)"), (w_out, "var(--s3)"), (w_th, "var(--s2)")):
            if seg_w > 0.4:
                parts.append(f'<rect x="{x_cur:.1f}" y="{y + 6}" width="{max(1.5, seg_w):.1f}" height="16" fill="{col}"/>')
                x_cur += seg_w
        if tot == 0:
            parts.append(f'<rect x="{left}" y="{y + 6}" width="2" height="16" fill="var(--muted)"/>')
        parts.append(f'<text x="{x_cur + 6:.1f}" y="{y + 18}" class="svg-val">{esc(f"{tot:,}")}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_cost_bars(roles_summary: list[dict[str, Any]]) -> str:
    width = 580
    row_h = 38
    top = 28
    left = 148
    right = 96
    height = top + len(roles_summary) * row_h + 12
    plot_w = width - left - right
    max_cost = max([0.0001] + [float(rs["cost_usd"]) for rs in roles_summary])

    parts: list[str] = [
        f'<svg class="svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Estimated USD cost across 6 roles">',
        f'<text x="{left}" y="13" class="svg-leg">Estimated list-price USD per role</text>',
    ]
    for idx, rs in enumerate(roles_summary):
        y = top + idx * row_h
        c = float(rs["cost_usd"])
        bw = plot_w * (c / max_cost) if c > 0 else 0.0
        parts.append(f'<text x="{left - 8}" y="{y + 18}" text-anchor="end" class="svg-label">{esc(rs["role"])}</text>')
        if bw > 0:
            parts.append(f'<rect x="{left}" y="{y + 6}" width="{max(2.0, bw):.1f}" height="16" rx="3" fill="{rs["color"]}"/>')
        else:
            parts.append(f'<rect x="{left}" y="{y + 6}" width="2" height="16" fill="var(--muted)"/>')
        parts.append(f'<text x="{left + bw + 6:.1f}" y="{y + 18}" class="svg-val">{esc(f"${c:.4f}")}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _safe_json_for_script(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), default=str)
    return raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_roles_html(data: dict[str, Any]) -> str:
    tot = data["totals"]
    paired = data["paired_comparison"]
    roles_summary = data["roles"]

    arch_cards: list[str] = []
    for rs in roles_summary:
        status_cls = "ok" if rs["role_verified"] else ("warn" if rs["n_runs"] > 0 else "pending")
        status_txt = "VERIFIED" if rs["role_verified"] else ("UNVERIFIED" if rs["n_runs"] > 0 else "PENDING")
        caps_html = "".join(f'<span class="chip">{esc(c)}</span>' for c in rs["capabilities"])
        rs_tok_total = f"{rs['tokens_in'] + rs['tokens_out'] + rs['tokens_thinking']:,}"
        rs_cost_fmt = f"${rs['cost_usd']:.4f}"
        arch_cards.append(
            f'<article class="card c4 arch-card" data-arch-role="{esc(rs["role"])}">'
            f'<div class="arch-top">'
            f'<span class="role-idx" style="background:{rs["color"]}">{esc(rs["index"])}</span>'
            f'<div class="arch-titles">'
            f'<div class="kicker">{esc(rs["role"])} | {esc(rs["stage"])}</div>'
            f'<h3>{esc(rs["title"])}</h3>'
            f'</div>'
            f'<span class="badge {status_cls}">{esc(status_txt)}</span>'
            f'</div>'
            f'<p class="arch-desc">{esc(rs["summary"])}</p>'
            f'<div class="caps">{caps_html}</div>'
            f'<div class="arch-foot">'
            f'<span>Runs: <b>{rs["n_runs"]}</b> ({rs["n_verified"]} verified)</span>'
            f'<span>Tokens: <b>{esc(rs_tok_total)}</b></span>'
            f'<span>Cost: <b>{esc(rs_cost_fmt)}</b></span>'
            f'</div>'
            f'</article>'
        )

    filter_buttons: list[str] = [
        f'<button type="button" class="flt-btn" data-filter="all" aria-pressed="true">All Roles ({tot["n_runs"]})</button>'
    ]
    for rs in roles_summary:
        label = f"{rs['role']} ({rs['n_runs']})"
        filter_buttons.append(
            f'<button type="button" class="flt-btn" data-filter="{esc(rs["role"])}" aria-pressed="false">{esc(label)}</button>'
        )

    run_cards: list[str] = []
    for rs in roles_summary:
        if not rs["runs"]:
            run_cards.append(
                f'<article class="card c6 run-card pending-card" data-role="{esc(rs["role"])}">'
                f'<div class="run-head">'
                f'<div><span class="role-pill" style="border-color:{rs["color"]}">{esc(rs["role"])}</span>'
                f'<h3>{esc(rs["title"])}</h3></div>'
                f'<span class="badge pending">PENDING</span>'
                f'</div>'
                f'<p class="sub">No committed run folder found yet under results/gemini_roles/{esc(rs["role"])}/.</p>'
                f'<div class="cmd-line"><code>{esc(rs["offline_cmd"])}</code></div>'
                f'</article>'
            )
            continue
        for run in rs["runs"]:
            b_cls = "ok" if run["verified"] else "no"
            b_txt = "VERIFIED" if run["verified"] else esc(run["verified_label"].upper())
            u = run["usage"]
            cmd_block = (
                f'<div class="meta-row"><span class="meta-k">Command</span><code class="mono-wrap">{esc(run["command"])}</code></div>'
                if run["command"]
                else ""
            )
            run_cards.append(
                f'<article class="card c6 run-card" data-role="{esc(run["role"])}">'
                f'<div class="run-head">'
                f'<div>'
                f'<span class="role-pill" style="border-color:{rs["color"]}">{esc(run["role"])}</span>'
                f'<span class="subrole-tag">{esc(run["subrole"])}</span>'
                f'</div>'
                f'<span class="badge {b_cls}">{b_txt}</span>'
                f'</div>'
                f'<div class="metric-callout">{esc(run["key_metric"])}</div>'
                f'<div class="meta-list">'
                f'<div class="meta-row"><span class="meta-k">Model ID</span><code class="model-chip">{esc(run["model_id"])}</code></div>'
                f'<div class="meta-row"><span class="meta-k">Commit</span><code class="mono-wrap">{esc(run["commit"])}</code></div>'
                f'<div class="meta-row"><span class="meta-k">Run Folder</span><code class="mono-wrap">{esc(run["run_folder"])}</code></div>'
                f'<div class="meta-row"><span class="meta-k">Tokens (in / out)</span><span>{esc(_fmt_tokens_pair(u))}</span></div>'
                f'<div class="meta-row"><span class="meta-k">Calls / Cached / Cost</span>'
                f'<span>{u["calls"]:,} calls | {u["cached"]:,} cached | ${u["cost_usd"]:.4f}</span></div>'
                f'{cmd_block}'
                f'</div>'
                f'</article>'
            )

    matrix_rows: list[str] = []
    for rs in roles_summary:
        if not rs["runs"]:
            matrix_rows.append(
                f'<tr data-role="{esc(rs["role"])}">'
                f'<td><code>{esc(rs["role"])}</code></td>'
                f'<td>pending</td><td>-</td><td>-</td><td>-</td><td>pending</td>'
                f'<td class="num">0 / 0</td><td><span class="badge pending">pending</span></td>'
                f'</tr>'
            )
            continue
        for run in rs["runs"]:
            v_cls = "ok" if run["verified"] else "no"
            matrix_rows.append(
                f'<tr data-role="{esc(run["role"])}">'
                f'<td><code>{esc(run["role"])}</code></td>'
                f'<td>{esc(run["subrole"])}</td>'
                f'<td><code>{esc(run["model_id"])}</code></td>'
                f'<td><code>{esc(run["commit"])}</code></td>'
                f'<td><code>{esc(run["run_folder"])}</code></td>'
                f'<td>{esc(run["key_metric"])}</td>'
                f'<td class="num">{esc(_fmt_tokens_pair(run["usage"]))}</td>'
                f'<td><span class="badge {v_cls}">{esc(run["verified_label"])}</span></td>'
                f'</tr>'
            )

    paired_tier_rows: list[str] = []
    tier_list = list(paired["tiers"])
    if paired["overall"] and len(tier_list) > 1:
        tier_list.append(paired["overall"])
    for pr in tier_list:
        ratio_s = f"{pr['ratio'] * 100.0:.0f}%" if pr["ratio"] is not None else "n/a"
        s_acc_s = f"{pr['solver_accuracy'] * 100.0:.0f}%" if pr["solver_accuracy"] is not None else "n/a"
        c_day_s = f"{pr['carbon_accuse_day']:.1f}" if pr["carbon_accuse_day"] is not None else "-"
        s_day_s = f"{pr['solver_accuse_day']:.1f}" if pr["solver_accuse_day"] is not None else "-"
        c_mean_s = f"{pr['carbon_mean']:+.3f}"
        s_mean_s = f"{pr['solver_mean']:+.3f}"
        diff_s = f"{pr['paired_diff']:+.3f} +/- {pr['diff_ci']:.3f}"
        c_acc_s = f"{pr['carbon_accuracy'] * 100.0:.0f}%"
        paired_tier_rows.append(
            f'<tr>'
            f'<td><b>{esc(pr["tier"])}</b></td>'
            f'<td class="num">{pr["n"]}</td>'
            f'<td class="num">{esc(c_mean_s)}</td>'
            f'<td class="num">{esc(s_mean_s)}</td>'
            f'<td class="num"><b>{esc(ratio_s)}</b></td>'
            f'<td class="num">{esc(diff_s)}</td>'
            f'<td class="num">{esc(c_acc_s)}</td>'
            f'<td class="num">{esc(s_acc_s)}</td>'
            f'<td class="num">{esc(c_day_s)} / {esc(s_day_s)}</td>'
            f'</tr>'
        )

    paired_seed_rows: list[str] = []
    for sr in paired["seeds"]:
        c_out = "correct" if sr["carbon_correct"] else ("wrong" if sr["carbon_accused"] else "abstain")
        sr_c_score = f"{sr['carbon_score']:+.3f}"
        sr_s_score = f"{sr['solver_score']:+.3f}"
        sr_diff = f"{sr['diff']:+.3f}"
        paired_seed_rows.append(
            f'<tr>'
            f'<td>{esc(sr["tier"])}</td>'
            f'<td class="num">{sr["seed"]}</td>'
            f'<td class="num">{esc(sr_c_score)}</td>'
            f'<td class="num">{esc(sr_s_score)}</td>'
            f'<td class="num">{esc(sr_diff)}</td>'
            f'<td>{esc(c_out)}</td>'
            f'<td><code>{esc(sr["run_folder"])}</code></td>'
            f'</tr>'
        )

    paired_table_html = (
        '<table class="list">'
        '<thead><tr>'
        '<th>Tier</th><th class="num">Seeds</th><th class="num">gemini-4-carbon</th>'
        '<th class="num">SolverPolicy</th><th class="num">Carbon / Solver</th>'
        '<th class="num">Paired Diff +/- 95% CI</th><th class="num">Carbon Acc</th>'
        '<th class="num">Solver Acc</th><th class="num">Accuse Day (C / S)</th>'
        '</tr></thead>'
        f'<tbody>{"".join(paired_tier_rows)}</tbody>'
        '</table>'
        if paired_tier_rows
        else '<div class="empty-box">No paired episodes found in committed investigator runs yet.</div>'
    )

    seed_details_html = (
        '<details class="seed-details"><summary>Per-seed paired scores (gemini-4-carbon vs SolverPolicy)</summary>'
        '<div class="table-wrap"><table class="list">'
        '<thead><tr><th>Tier</th><th class="num">Seed</th><th class="num">gemini-4-carbon</th>'
        '<th class="num">SolverPolicy</th><th class="num">Delta</th><th>Outcome</th><th>Run Folder</th></tr></thead>'
        f'<tbody>{"".join(paired_seed_rows)}</tbody></table></div></details>'
        if paired_seed_rows
        else ""
    )

    cost_rows: list[str] = []
    for rs in roles_summary:
        cost_rows.append(
            f'<tr>'
            f'<td><code>{esc(rs["role"])}</code></td>'
            f'<td>{esc(rs["title"])}</td>'
            f'<td class="num">{rs["n_runs"]}</td>'
            f'<td class="num">{rs["n_verified"]}</td>'
            f'<td class="num">{rs["calls"]:,}</td>'
            f'<td class="num">{rs["tokens_in"]:,}</td>'
            f'<td class="num">{rs["tokens_out"]:,}</td>'
            f'<td class="num">{rs["tokens_thinking"]:,}</td>'
            f'<td class="num">{rs["tokens_cached"]:,}</td>'
            f'<td class="num">${rs["cost_usd"]:.4f}</td>'
            f'</tr>'
        )
    cost_rows.append(
        f'<tr class="tot-row">'
        f'<td><b>total</b></td>'
        f'<td><b>All 6 Gemini Roles</b></td>'
        f'<td class="num"><b>{tot["n_runs"]}</b></td>'
        f'<td class="num"><b>{tot["n_verified_runs"]}</b></td>'
        f'<td class="num"><b>{tot["calls"]:,}</b></td>'
        f'<td class="num"><b>{tot["tokens_in"]:,}</b></td>'
        f'<td class="num"><b>{tot["tokens_out"]:,}</b></td>'
        f'<td class="num"><b>{tot["tokens_thinking"]:,}</b></td>'
        f'<td class="num"><b>{tot["tokens_cached"]:,}</b></td>'
        f'<td class="num"><b>${tot["cost_usd"]:.4f}</b></td>'
        f'</tr>'
    )

    repro_items = [
        (
            "Rebuild 6-Role Markdown Matrix & HTML Showcase (Keyless)",
            "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out results/gemini",
        ),
        (
            "Run Keyless 6-Role Dashboard Verification Suite",
            "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. pytest -q tests/test_roles_dashboard.py",
        ),
        (
            "Replay Recorded Gemini Gateway Showcase Offline (No API Key)",
            "make lab-replay",
        ),
    ]
    for rs in roles_summary:
        repro_items.append((f"Role {rs['index']} ({rs['role']}): Keyless Offline Check", rs["offline_cmd"]))

    repro_cards = "".join(
        f'<div class="card c6 repro-card">'
        f'<div class="repro-top"><h3>{esc(label)}</h3>'
        f'<button type="button" class="copy-btn" data-cmd="{esc(cmd)}">Copy</button></div>'
        f'<pre class="cmd-pre"><code>{esc(cmd)}</code></pre>'
        f'</div>'
        for label, cmd in repro_items
    )

    models_str = ", ".join(tot["models"]) if tot["models"] else "gemini-4-carbon"
    paired_seeds_n = len(paired["seeds"])
    overall_ratio_str = (
        f"{paired['overall']['ratio'] * 100.0:.0f}% of SolverPolicy"
        if paired["overall"] and paired["overall"]["ratio"] is not None
        else "awaiting paired runs"
    )

    body = (
        HTML_TEMPLATE
        .replace("__CSS_BLOCK__", CSS_STYLES)
        .replace("__JS_BLOCK__", JS_SCRIPT)
        .replace("__DATA_JSON__", _safe_json_for_script(data))
        .replace("__GIT_SHA__", esc(data["git_sha"]))
        .replace("__GENERATED_AT__", esc(data["generated_at"]))
        .replace("__ROLES_VERIFIED__", esc(f"{tot['n_roles_verified']} / {tot['n_roles_total']}"))
        .replace("__RUNS_COUNT__", esc(str(tot["n_runs"])))
        .replace("__VERIFIED_RUNS_NOTE__", esc(f"{tot['n_verified_runs']} verified committed folders"))
        .replace("__MODELS_USED__", esc(models_str))
        .replace("__TOKENS_IN__", esc(f"{tot['tokens_in']:,}"))
        .replace("__TOKENS_OUT__", esc(f"{tot['tokens_out']:,}"))
        .replace("__TOKENS_THINK__", esc(f"{tot['tokens_thinking']:,}"))
        .replace("__COST_USD__", esc(f"${tot['cost_usd']:.4f}"))
        .replace("__CALLS_COUNT__", esc(f"{tot['calls']:,} API calls"))
        .replace("__PAIRED_SEEDS__", esc(str(paired_seeds_n)))
        .replace("__PAIRED_RATIO_NOTE__", esc(overall_ratio_str))
        .replace("__ARCH_CARDS__", "".join(arch_cards))
        .replace("__FILTER_BUTTONS__", "".join(filter_buttons))
        .replace("__RUN_CARDS__", "".join(run_cards))
        .replace("__MATRIX_ROWS__", "".join(matrix_rows))
        .replace("__PAIRED_CHART__", _svg_paired_chart(paired))
        .replace("__PAIRED_TABLE__", paired_table_html)
        .replace("__SEED_DETAILS__", seed_details_html)
        .replace("__TOKEN_BARS__", _svg_token_bars(roles_summary))
        .replace("__COST_BARS__", _svg_cost_bars(roles_summary))
        .replace("__COST_ROWS__", "".join(cost_rows))
        .replace("__REPRO_CARDS__", repro_cards)
    )
    return body


def build_roles_dashboard(
    root: str | Path = ROOT,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    target_dir = Path(out_dir) if out_dir is not None else (root_path / "results" / "gemini")
    target_dir.mkdir(parents=True, exist_ok=True)

    data = collect_roles_data(root_path)
    md_text = render_roles_markdown(data)
    html_text = render_roles_html(data)

    md_path = target_dir / "ROLES_TABLE.md"
    html_path = target_dir / "roles_dashboard.html"
    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")

    data["markdown_path"] = str(md_path)
    data["html_path"] = str(html_path)
    return data


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canary x Gemini: Unified 6-Role Showcase</title>
<style>__CSS_BLOCK__</style>
</head>
<body>
<header class="top">
  <div class="brand">
    <svg class="bird" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M6 20c0-7 5-12 12-12 3 0 5 1 6 3l4 1-4 2c0 6-5 10-11 10H8l-3 3 1-5z" fill="var(--canary)"/>
      <circle cx="21" cy="12" r="1.4" fill="var(--ink)"/>
    </svg>
    <div>
      <div class="eyebrow">Canary Lab | Best Use of Gemini API</div>
      <h1>Unified 6-Role Gemini Showcase</h1>
    </div>
  </div>
  <div class="topmeta">
    <span>commit <code>__GIT_SHA__</code> | __GENERATED_AT__</span>
    <button id="theme-toggle" type="button" aria-label="Toggle theme">Theme: auto</button>
  </div>
</header>

<main>
  <section id="sec-overview" class="panel">
    <div class="hero">
      <div class="card hero-card">
        <div class="kicker">Role Coverage</div>
        <div class="hero-num">__ROLES_VERIFIED__</div>
        <p>Essential Gemini roles backed by committed run folders with verified model IDs, git commits, and non-zero token provenance.</p>
        <div class="caps">
          <span class="chip">world_text</span>
          <span class="chip">adaptive_mole</span>
          <span class="chip">investigators</span>
          <span class="chip">failure_analyst</span>
          <span class="chip">exploit_hunter</span>
          <span class="chip">multimodal_evidence</span>
        </div>
      </div>
      <div class="tiles">
        <div class="tile"><div class="lab">Committed Runs</div><div class="val">__RUNS_COUNT__</div><div class="note">__VERIFIED_RUNS_NOTE__</div></div>
        <div class="tile"><div class="lab">Headline Model</div><div class="val">gemini-4-carbon</div><div class="note">__MODELS_USED__</div></div>
        <div class="tile"><div class="lab">Input Tokens</div><div class="val">__TOKENS_IN__</div><div class="note">across committed role runs</div></div>
        <div class="tile"><div class="lab">Output Tokens</div><div class="val">__TOKENS_OUT__</div><div class="note">__TOKENS_THINK__ thinking tokens</div></div>
        <div class="tile"><div class="lab">Estimated Cost</div><div class="val">__COST_USD__</div><div class="note">__CALLS_COUNT__</div></div>
        <div class="tile"><div class="lab">Paired Seeds</div><div class="val">__PAIRED_SEEDS__</div><div class="note">__PAIRED_RATIO_NOTE__</div></div>
      </div>
    </div>
  </section>

  <section id="sec-architecture" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>01</b> Architecture</div>
        <h2>Six Essential Gemini Roles Across the Canary Benchmark Lifecycle</h2>
        <p class="lede">Gemini constructs the company world, evolves and plays the insider mole, investigates leaks via 13 MCP tools, inspects visual document scans, diagnoses long-context trajectory corpora, and red-teams the full repository.</p>
      </div>
    </div>
    <div class="grid">__ARCH_CARDS__</div>
  </section>

  <section id="sec-runs" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>02</b> Provenance &amp; Run Cards</div>
        <h2>Committed Runs Across results/gemini_roles/ and data/runs/committed/v1.4/</h2>
        <p class="lede">Every claim maps directly to a committed directory on disk recording the exact Gemini model ID, git commit hash, token counts, and domain evaluation metric.</p>
      </div>
      <div class="flt-bar" role="group" aria-label="Filter runs by role">__FILTER_BUTTONS__</div>
    </div>
    <div id="run-cards-grid" class="grid">__RUN_CARDS__</div>
    <div class="card matrix-card">
      <h3>Unified 6-Role Provenance Matrix (ROLES_TABLE.md)</h3>
      <p class="sub">Complete tabular view matching results/gemini/ROLES_TABLE.md</p>
      <div class="table-wrap">
        <table id="roles-matrix-table" class="list">
          <thead>
            <tr>
              <th>Role</th>
              <th>Subrole</th>
              <th>Model ID</th>
              <th>Commit</th>
              <th>Run Folder</th>
              <th>Key Metric</th>
              <th class="num">Tokens (in/out)</th>
              <th>Verified</th>
            </tr>
          </thead>
          <tbody>__MATRIX_ROWS__</tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="sec-paired" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>03</b> Paired Evaluation</div>
        <h2>Paired gemini-4-carbon vs SolverPolicy Comparison</h2>
        <p class="lede">Head-to-head investigator evaluation on identical Canary v1.4 worlds against the exact Bayesian reference solver.</p>
      </div>
    </div>
    <div class="grid">
      <div class="card c5">
        <h3>Mean Score by Tier</h3>
        <p class="sub">gemini-4-carbon vs SolverPolicy on identical seeds</p>
        __PAIRED_CHART__
      </div>
      <div class="card c7">
        <h3>Paired Statistical Summary</h3>
        <p class="sub">Score ratio, paired difference with 95% confidence interval, and accusation accuracy</p>
        <div class="table-wrap">__PAIRED_TABLE__</div>
        __SEED_DETAILS__
      </div>
    </div>
  </section>

  <section id="sec-tokens" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>04</b> Economics &amp; Accounting</div>
        <h2>Token &amp; Cost Breakdown Across All 6 Roles</h2>
        <p class="lede">Aggregated input, output, thinking, and cached token usage with list-price USD accounting per role.</p>
      </div>
    </div>
    <div class="grid">
      <div class="card c6">
        <h3>Tokens by Role</h3>
        <p class="sub">Stacked input, output, and thinking tokens</p>
        __TOKEN_BARS__
      </div>
      <div class="card c6">
        <h3>Cost (USD) by Role</h3>
        <p class="sub">List-price USD across committed runs</p>
        __COST_BARS__
      </div>
      <div class="card c12">
        <h3>Role-by-Role Token &amp; Cost Ledger</h3>
        <div class="table-wrap">
          <table class="list">
            <thead>
              <tr>
                <th>Role</th>
                <th>Title</th>
                <th class="num">Runs</th>
                <th class="num">Verified</th>
                <th class="num">Calls</th>
                <th class="num">Input Tokens</th>
                <th class="num">Output Tokens</th>
                <th class="num">Thinking Tokens</th>
                <th class="num">Cached Tokens</th>
                <th class="num">Cost (USD)</th>
              </tr>
            </thead>
            <tbody>__COST_ROWS__</tbody>
          </table>
        </div>
      </div>
    </div>
  </section>

  <section id="sec-reproduce" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>05</b> Offline Reproducibility</div>
        <h2>Keyless Verification &amp; Reproduction Commands</h2>
        <p class="lede">Every verification check, replay audit, and dashboard build runs offline with GEMINI_API_KEY unset.</p>
      </div>
    </div>
    <div class="grid">__REPRO_CARDS__</div>
  </section>
</main>

<footer class="foot">
  Canary x Gemini 6-Role Showcase | Self-contained offline artifact generated by <code>python -m canary.gemini.roles_dashboard</code>
</footer>
<script id="roles-data" type="application/json">__DATA_JSON__</script>
<script>__JS_BLOCK__</script>
</body>
</html>
"""

CSS_STYLES = """
:root {
  color-scheme: light;
  --page: #f6f5f0;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink2: #4c4b47;
  --muted: #82807a;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --ring: rgba(11, 11, 11, 0.10);
  --wash: rgba(11, 11, 11, 0.038);
  --canary: #f2b705;
  --s1: #2a78d6;
  --s2: #eb6834;
  --s3: #1baf7a;
  --s4: #d48c00;
  --s5: #c93b6b;
  --s6: #6250d6;
  --good: #0ca30c;
  --goodtext: #006300;
  --warn: #d48c00;
  --crit: #c93333;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0e0e0d;
    --surface: #191918;
    --ink: #f1f0ec;
    --ink2: #c5c4bc;
    --muted: #8c8a83;
    --grid: #2b2b29;
    --axis: #3d3d39;
    --ring: rgba(255, 255, 255, 0.11);
    --wash: rgba(255, 255, 255, 0.05);
    --s1: #4c95ee;
    --s2: #f07b4c;
    --s3: #28c58d;
    --s4: #ebb02d;
    --s5: #e66591;
    --s6: #9284f0;
    --goodtext: #34d058;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0e0e0d;
  --surface: #191918;
  --ink: #f1f0ec;
  --ink2: #c5c4bc;
  --muted: #8c8a83;
  --grid: #2b2b29;
  --axis: #3d3d39;
  --ring: rgba(255, 255, 255, 0.11);
  --wash: rgba(255, 255, 255, 0.05);
  --s1: #4c95ee;
  --s2: #f07b4c;
  --s3: #28c58d;
  --s4: #ebb02d;
  --s5: #e66591;
  --s6: #9284f0;
  --goodtext: #34d058;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
.top, main, .foot { max-width: 1280px; margin: 0 auto; padding: 0 24px; }
.top {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  padding-top: 26px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--grid);
  flex-wrap: wrap;
}
.brand { display: flex; gap: 14px; align-items: center; }
.bird { width: 42px; height: 42px; flex: none; }
.eyebrow, .kicker {
  font: 600 11px/1.2 ui-monospace, "SF Mono", Menlo, monospace;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}
.kicker b { color: var(--ink); margin-right: 6px; }
h1 {
  margin: 4px 0 0;
  font: 600 26px/1.15 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}
.topmeta {
  display: flex;
  gap: 12px;
  align-items: center;
  color: var(--muted);
  font: 12px/1.4 ui-monospace, "SF Mono", Menlo, monospace;
  flex-wrap: wrap;
}
button {
  font: 500 12px/1 system-ui, -apple-system, sans-serif;
  color: var(--ink2);
  background: var(--surface);
  border: 1px solid var(--ring);
  border-radius: 999px;
  padding: 7px 13px;
  cursor: pointer;
}
button:hover { background: var(--wash); }
button[aria-pressed="true"] { background: var(--ink); color: var(--surface); }
.panel { padding: 32px 0 6px; }
.phead {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.phead h2 {
  margin: 3px 0 0;
  font: 600 21px/1.22 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}
.lede { margin: 5px 0 0; color: var(--ink2); max-width: 82ch; }
.hero { display: grid; grid-template-columns: minmax(280px, 1.15fr) 2.4fr; gap: 16px; }
@media (max-width: 960px) { .hero { grid-template-columns: 1fr; } }
.hero-num { font: 700 54px/1 system-ui, -apple-system, sans-serif; letter-spacing: -0.03em; margin: 10px 0 8px; }
.hero-card p { margin: 0; color: var(--ink2); }
.tiles {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  background: var(--ring);
  border: 1px solid var(--ring);
  border-radius: 12px;
  overflow: hidden;
}
@media (max-width: 680px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.tile { background: var(--surface); padding: 14px 16px; min-width: 0; }
.tile .lab { color: var(--muted); font-size: 12px; }
.tile .val { font: 600 20px/1.25 system-ui, -apple-system, sans-serif; margin-top: 4px; font-variant-numeric: tabular-nums; }
.tile .note { color: var(--muted); font-size: 11.5px; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(12, minmax(0, 1fr)); }
.card {
  background: var(--surface);
  border: 1px solid var(--ring);
  border-radius: 12px;
  padding: 18px 20px;
  min-width: 0;
}
.card h3 { margin: 0; font: 600 15px/1.3 system-ui, -apple-system, sans-serif; }
.card .sub { margin: 3px 0 12px; color: var(--muted); font-size: 12px; }
.c4 { grid-column: span 4; }
.c5 { grid-column: span 5; }
.c6 { grid-column: span 6; }
.c7 { grid-column: span 7; }
.c12 { grid-column: span 12; }
@media (max-width: 980px) { .c4, .c5, .c6, .c7 { grid-column: span 12; } }
.caps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.chip {
  font: 500 11px/1 ui-monospace, "SF Mono", Menlo, monospace;
  padding: 5px 8px;
  border-radius: 999px;
  border: 1px solid var(--ring);
  color: var(--ink2);
  background: var(--wash);
}
.arch-card { display: flex; flex-direction: column; justify-content: space-between; }
.arch-top { display: flex; align-items: flex-start; gap: 10px; }
.arch-titles { flex: 1; min-width: 0; }
.role-idx {
  color: #fff;
  font: 700 11px/1 ui-monospace, Menlo, monospace;
  padding: 6px 7px;
  border-radius: 7px;
  flex: none;
}
.arch-desc { margin: 10px 0 2px; color: var(--ink2); font-size: 13px; }
.arch-foot {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--grid);
  font-size: 12px;
  color: var(--muted);
}
.arch-foot b { color: var(--ink); font-variant-numeric: tabular-nums; }
.badge {
  display: inline-flex;
  align-items: center;
  font: 600 10.5px/1 ui-monospace, Menlo, monospace;
  padding: 4px 7px;
  border-radius: 5px;
  white-space: nowrap;
}
.badge.ok { color: var(--goodtext); background: rgba(12, 163, 12, 0.14); }
.badge.warn { color: var(--warn); background: rgba(212, 140, 0, 0.15); }
.badge.no { color: var(--crit); background: rgba(201, 51, 51, 0.14); }
.badge.pending { color: var(--muted); background: var(--wash); border: 1px dashed var(--axis); }
.flt-bar { display: flex; flex-wrap: wrap; gap: 6px; }
.run-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
.role-pill {
  display: inline-block;
  font: 600 11px/1 ui-monospace, Menlo, monospace;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1.5px solid var(--axis);
  margin-right: 8px;
}
.subrole-tag { font: 600 14px/1.2 system-ui, -apple-system, sans-serif; }
.metric-callout {
  font: 600 13.5px/1.35 ui-monospace, "SF Mono", Menlo, monospace;
  padding: 8px 11px;
  border-radius: 8px;
  background: var(--wash);
  border-left: 3px solid var(--canary);
  margin-bottom: 12px;
}
.meta-list { display: grid; gap: 6px; font-size: 12.5px; }
.meta-row { display: grid; grid-template-columns: 145px minmax(0, 1fr); gap: 8px; align-items: baseline; }
.meta-k { color: var(--muted); font-size: 12px; }
.model-chip {
  display: inline-block;
  font: 600 11.5px/1.2 ui-monospace, Menlo, monospace;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--wash);
}
.mono-wrap {
  font: 11.5px/1.35 ui-monospace, "SF Mono", Menlo, monospace;
  word-break: break-all;
}
.pending-card { border-style: dashed; }
.matrix-card { margin-top: 16px; }
.table-wrap { overflow-x: auto; }
table.list { width: 100%; border-collapse: collapse; font-size: 12.5px; }
table.list th {
  text-align: left;
  font-weight: 600;
  color: var(--muted);
  font-size: 11.5px;
  padding: 7px 8px;
  border-bottom: 1px solid var(--axis);
  white-space: nowrap;
}
table.list td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--grid);
  vertical-align: top;
}
table.list td.num, table.list th.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
table.list tr.tot-row td { border-top: 1.5px solid var(--axis); border-bottom: 0; padding-top: 9px; }
code { font: 11.5px/1.35 ui-monospace, "SF Mono", Menlo, monospace; }
.svg-chart { display: block; width: 100%; height: auto; }
.axis-line { stroke: var(--axis); stroke-width: 1; }
.svg-label { font: 500 11.5px system-ui, -apple-system, sans-serif; fill: var(--ink2); }
.svg-val { font: 600 11px ui-monospace, Menlo, monospace; fill: var(--ink); }
.svg-leg { font: 500 11px system-ui, -apple-system, sans-serif; fill: var(--muted); }
.empty-box {
  padding: 24px 16px;
  text-align: center;
  color: var(--muted);
  border: 1px dashed var(--axis);
  border-radius: 8px;
  background: var(--wash);
}
.seed-details { margin-top: 12px; }
.seed-details summary { cursor: pointer; color: var(--ink2); font-size: 12.5px; font-weight: 500; margin-bottom: 8px; }
.repro-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 8px; }
.cmd-pre, .cmd-line {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--wash);
  border: 1px solid var(--ring);
  overflow-x: auto;
}
.foot {
  color: var(--muted);
  font-size: 12px;
  padding-top: 26px;
  padding-bottom: 40px;
  border-top: 1px solid var(--grid);
  margin-top: 32px;
}
.hidden-role { display: none !important; }
"""

JS_SCRIPT = """
(function () {
  'use strict';
  var root = document.documentElement;
  var themeBtn = document.getElementById('theme-toggle');
  var theme = 'auto';
  try { theme = localStorage.getItem('canary-roles-theme') || 'auto'; } catch (e) {}
  function applyTheme() {
    if (theme === 'auto') { root.removeAttribute('data-theme'); }
    else { root.setAttribute('data-theme', theme); }
    if (themeBtn) { themeBtn.textContent = 'Theme: ' + theme; }
  }
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      theme = theme === 'auto' ? 'light' : (theme === 'light' ? 'dark' : 'auto');
      try { localStorage.setItem('canary-roles-theme', theme); } catch (e) {}
      applyTheme();
    });
  }
  applyTheme();

  var filterBtns = document.querySelectorAll('.flt-btn');
  filterBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = btn.getAttribute('data-filter') || 'all';
      filterBtns.forEach(function (b) {
        b.setAttribute('aria-pressed', String(b === btn));
      });
      document.querySelectorAll('#run-cards-grid .run-card, #roles-matrix-table tbody tr').forEach(function (el) {
        var r = el.getAttribute('data-role');
        if (target === 'all' || r === target) { el.classList.remove('hidden-role'); }
        else { el.classList.add('hidden-role'); }
      });
    });
  });

  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var cmd = btn.getAttribute('data-cmd') || '';
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(cmd).then(function () {
          btn.textContent = 'Copied';
          setTimeout(function () { btn.textContent = 'Copy'; }, 1400);
        }).catch(function () {});
      }
    });
  });
})();
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.roles_dashboard")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", "--out-dir", dest="out_dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    data = build_roles_dashboard(args.root, args.out_dir)
    if args.json:
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    tot = data["totals"]
    print(
        f"wrote {data['markdown_path']} and {data['html_path']} "
        f"({tot['n_roles_verified']}/{tot['n_roles_total']} roles verified, {tot['n_runs']} runs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
