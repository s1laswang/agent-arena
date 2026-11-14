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
    r"(AIza[0-9A-Za-z_\-]{8,}"
    r"|(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}"
    r"|(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{8,}"
    r"|(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|anthropic_api_key|xai_api_key|api[_-]?key|secret)"
    r"(?:[\"']?[ \t]*:[ \t]*|[ \t]+=[ \t]*|=(?![ \t])|=[ \t]*(?=[\"']))"
    r"(?![A-Za-z0-9_]+=)"
    r"(?![\"']?(?:null|none|false|true|unset|empty|missing|redacted|\[redacted\]|<redacted>)(?:[\"']|\b))"
    r"(?:\"[^\r\n\"]{4,}\"|'[^\r\n']{4,}'|[^\s\"',;}\]]{4,}))"
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


def _norm_ratio(val: float) -> float:
    return val / 100.0 if val > 1.0001 else val


def _first_float(dicts: list[dict[str, Any]], keys: tuple[str, ...]) -> float | None:
    for d in dicts:
        if not isinstance(d, dict):
            continue
        res = _float_from(d, keys)
        if res is not None:
            return res
    return None


def _first_int(dicts: list[dict[str, Any]], keys: tuple[str, ...]) -> int | None:
    for d in dicts:
        if not isinstance(d, dict):
            continue
        for k in keys:
            v = d.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and not math.isnan(v):
                return int(v)
    return None


def _extract_sample_count(
    cdir: Path,
    meta: dict[str, Any],
    episodes: list[dict[str, Any]],
    companions: dict[str, Any],
) -> int:
    for key in (
        "episode_count",
        "sample_count",
        "n_episodes",
        "n_samples",
        "n_episodes_packed",
        "n_calibrated_episodes",
        "n_dossiers",
        "n_charts_analyzed",
        "n_images_read_by_model",
        "n_worlds",
        "n_events_generated",
        "n_briefings",
        "n_seeds",
        "count",
        "n",
    ):
        val = meta.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    if episodes:
        return len(episodes)
    for name in ("attempts.jsonl", "samples.jsonl", "results.jsonl", "vision_calls.jsonl"):
        fp = cdir / name
        if fp.is_file():
            try:
                lines = [ln for ln in fp.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
                if lines:
                    return len(lines)
            except OSError:
                pass
    for key in ("valid_seeds", "episodes", "samples", "seeds", "world_specs", "runs", "attempts", "items", "rasters", "memos"):
        val = meta.get(key)
        if isinstance(val, list) and val:
            return len(val)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    atlas_doc = companions.get("atlas")
    if isinstance(atlas_doc, dict) and isinstance(atlas_doc.get("corpus"), dict):
        ep_c = atlas_doc["corpus"].get("episodes")
        if isinstance(ep_c, int) and not isinstance(ep_c, bool) and ep_c > 0:
            return ep_c
    res_doc = companions.get("results")
    if isinstance(res_doc, dict):
        for k in ("n_images_read_by_model", "n_worlds", "n_dossiers", "n_episodes"):
            rv = res_doc.get(k)
            if isinstance(rv, int) and not isinstance(rv, bool) and rv > 0:
                return rv
    sw_doc = companions.get("swarm")
    if isinstance(sw_doc, dict) and isinstance(sw_doc.get("counts"), dict):
        sa = sw_doc["counts"].get("attempts")
        if isinstance(sa, int) and not isinstance(sa, bool) and sa > 0:
            return sa
    diag_doc = companions.get("diagnoses")
    if isinstance(diag_doc, list) and diag_doc:
        return len(diag_doc)
    audit_doc = companions.get("audit_report")
    if isinstance(audit_doc, dict) and isinstance(audit_doc.get("n_seeds"), int) and audit_doc["n_seeds"] > 0:
        return int(audit_doc["n_seeds"])
    summary = meta.get("summary")
    if isinstance(summary, dict):
        if isinstance(summary.get("n"), int) and not isinstance(summary.get("n"), bool) and summary["n"] > 0:
            return int(summary["n"])
        sub = [
            int(v["n"])
            for v in summary.values()
            if isinstance(v, dict) and isinstance(v.get("n"), int) and not isinstance(v.get("n"), bool)
        ]
        if sub:
            return sum(sub)
    if isinstance(meta.get("n_messages"), int) and not isinstance(meta.get("n_messages"), bool) and meta["n_messages"] > 0:
        return int(meta["n_messages"])
    return 0


def _extract_multimodal_metrics(meta: dict[str, Any], companions: dict[str, Any]) -> dict[str, Any]:
    res_raw = companions.get("results")
    res_doc = res_raw if isinstance(res_raw, dict) else {}
    comp_doc = companions.get("comparison") if isinstance(companions.get("comparison"), dict) else {}
    dos_doc = companions.get("dossier") if isinstance(companions.get("dossier"), dict) else {}
    sum_doc = companions.get("summary") if isinstance(companions.get("summary"), dict) else {}
    eval_doc = companions.get("evaluation") if isinstance(companions.get("evaluation"), dict) else {}
    diag_raw = companions.get("diagnoses")

    comp_sum = comp_doc.get("summary") if isinstance(comp_doc.get("summary"), dict) else {}
    metric_dicts: list[dict[str, Any]] = [
        meta,
        meta.get("metrics") if isinstance(meta.get("metrics"), dict) else {},
        meta.get("summary") if isinstance(meta.get("summary"), dict) else {},
        res_doc.get("metrics") if isinstance(res_doc.get("metrics"), dict) else {},
        res_doc,
        dos_doc.get("metrics") if isinstance(dos_doc.get("metrics"), dict) else {},
        dos_doc,
        comp_sum,
        comp_doc,
        sum_doc.get("metrics") if isinstance(sum_doc.get("metrics"), dict) else {},
        sum_doc,
        eval_doc,
    ]

    eval_items: list[dict[str, Any]] = []
    if isinstance(res_raw, list):
        eval_items.extend(x for x in res_raw if isinstance(x, dict))
    for container in (res_doc, dos_doc, sum_doc, meta):
        if not isinstance(container, dict):
            continue
        for lk in ("worlds", "dossiers", "cases", "episodes", "samples", "items"):
            lv = container.get(lk)
            if isinstance(lv, list) and lv:
                eval_items.extend(x for x in lv if isinstance(x, dict))
                break
        if eval_items:
            break

    mole_acc = _first_float(metric_dicts, ("top1_mole_accuracy", "mole_accuracy", "dossier_mole_accuracy"))
    decoy_acc = _first_float(metric_dicts, ("top1_decoy_accuracy", "decoy_accuracy", "decoy_identified_rate"))
    naive_mole_acc = _first_float(
        metric_dicts,
        (
            "naive_baseline_mole_accuracy",
            "naive_after_hours_baseline_mole_accuracy",
            "image1_only_mole_accuracy",
            "text_only_mole_accuracy",
            "log_baseline_mole_accuracy",
        ),
    )
    naive_trap_rate = _first_float(
        metric_dicts,
        (
            "naive_after_hours_baseline_decoy_trap_rate",
            "naive_baseline_decoy_trap_rate",
            "image1_only_decoy_trap_rate",
            "naive_decoy_trap_rate",
        ),
    )

    if eval_items:
        mole_flags: list[bool] = []
        decoy_flags: list[bool] = []
        naive_flags: list[bool] = []
        trap_flags: list[bool] = []
        for it in eval_items:
            ev = it.get("evaluation") if isinstance(it.get("evaluation"), dict) else it
            for mk in ("top1_mole_correct", "mole_correct"):
                if isinstance(ev.get(mk), bool):
                    mole_flags.append(bool(ev[mk]))
                    break
            for dk in ("top1_decoy_correct", "decoy_correct", "decoy_identified"):
                if isinstance(ev.get(dk), bool):
                    decoy_flags.append(bool(ev[dk]))
                    break
            for nk in ("naive_baseline_mole_correct", "text_only_mole_correct"):
                if isinstance(ev.get(nk), bool):
                    naive_flags.append(bool(ev[nk]))
                    break
            if isinstance(ev.get("naive_baseline_trapped_by_decoy"), bool):
                trap_flags.append(bool(ev["naive_baseline_trapped_by_decoy"]))
        if mole_acc is None and mole_flags:
            mole_acc = sum(1 for x in mole_flags if x) / len(mole_flags)
        if decoy_acc is None and decoy_flags:
            decoy_acc = sum(1 for x in decoy_flags if x) / len(decoy_flags)
        if naive_mole_acc is None and naive_flags:
            naive_mole_acc = sum(1 for x in naive_flags if x) / len(naive_flags)
        if naive_trap_rate is None and trap_flags:
            naive_trap_rate = sum(1 for x in trap_flags if x) / len(trap_flags)

    mm_carbon = comp_sum.get("multimodal_carbon") if isinstance(comp_sum.get("multimodal_carbon"), dict) else {}
    bl_novis = comp_sum.get("blind_no_vision") if isinstance(comp_sum.get("blind_no_vision"), dict) else {}
    tx_oracle = comp_sum.get("text_oracle") if isinstance(comp_sum.get("text_oracle"), dict) else {}

    mm_mean = _first_float(metric_dicts, ("multimodal_mean_score", "degraded_multimodal_mean_score"))
    if mm_mean is None:
        mm_mean = _float_from(mm_carbon, ("mean_score",))
    blind_mean = _first_float(metric_dicts, ("blind_ablation_mean_score", "blind_mean_score", "no_vision_mean_score"))
    if blind_mean is None:
        blind_mean = _float_from(bl_novis, ("mean_score",))
    oracle_mean = _first_float(metric_dicts, ("oracle_mean_score",))
    if oracle_mean is None:
        oracle_mean = _float_from(tx_oracle, ("mean_score",))

    mm_acc = _first_float(metric_dicts, ("multimodal_accuracy",))
    if mm_acc is None:
        mm_acc = _float_from(mm_carbon, ("accuracy",))
    blind_acc = _first_float(metric_dicts, ("blind_accuracy", "blind_ablation_accuracy"))
    if blind_acc is None:
        blind_acc = _float_from(bl_novis, ("accuracy",))

    vision_acc = _first_float(
        metric_dicts,
        (
            "variant_vision_accuracy",
            "degraded_vision_accuracy",
            "watermark_vision_accuracy",
            "memo_scan_readout_accuracy",
            "canary_variant_vision_accuracy",
        ),
    )
    clean_vision_acc = _first_float(metric_dicts, ("clean_vision_accuracy",))

    diag_items: list[dict[str, Any]] = []
    if isinstance(diag_raw, list):
        diag_items = [x for x in diag_raw if isinstance(x, dict)]
    elif isinstance(diag_raw, dict):
        for dk in ("diagnoses", "episodes", "charts", "items"):
            if isinstance(diag_raw.get(dk), list):
                diag_items = [x for x in diag_raw[dk] if isinstance(x, dict)]
                break

    n_charts = _first_int(metric_dicts, ("n_charts_analyzed", "n_charts"))
    if n_charts is None and diag_items:
        n_charts = len(diag_items)

    thresh_acc = _first_float(metric_dicts, ("visual_threshold_accuracy", "threshold_accuracy"))
    day_exact_acc = _first_float(metric_dicts, ("accuse_day_exact_accuracy", "day_exact_accuracy"))
    day_w1_acc = _first_float(metric_dicts, ("accuse_day_within_1_accuracy", "day_within_1_accuracy"))
    bleed_acc = _first_float(metric_dicts, ("hidden_bleed_gap_accuracy", "bleed_gap_accuracy"))

    if diag_items:
        t_flags = [
            bool(x["scoring"]["threshold_match"])
            for x in diag_items
            if isinstance(x.get("scoring"), dict) and isinstance(x["scoring"].get("threshold_match"), bool)
        ]
        de_flags = [
            bool(x["scoring"]["day_exact"])
            for x in diag_items
            if isinstance(x.get("scoring"), dict) and isinstance(x["scoring"].get("day_exact"), bool)
        ]
        dw_flags = [
            bool(x["scoring"]["day_within_1"])
            for x in diag_items
            if isinstance(x.get("scoring"), dict) and isinstance(x["scoring"].get("day_within_1"), bool)
        ]
        bg_flags = [
            bool(x["scoring"]["bleed_gap_match"])
            for x in diag_items
            if isinstance(x.get("scoring"), dict) and isinstance(x["scoring"].get("bleed_gap_match"), bool)
        ]
        if thresh_acc is None and t_flags:
            thresh_acc = sum(1 for v in t_flags if v) / len(t_flags)
        if day_exact_acc is None and de_flags:
            day_exact_acc = sum(1 for v in de_flags if v) / len(de_flags)
        if day_w1_acc is None and dw_flags:
            day_w1_acc = sum(1 for v in dw_flags if v) / len(dw_flags)
        if bleed_acc is None and bg_flags:
            bleed_acc = sum(1 for v in bg_flags if v) / len(bg_flags)

    n_images = _first_int(metric_dicts, ("n_images_read_by_model", "n_images", "images_read", "n_scans"))
    if n_images is None:
        if isinstance(meta.get("rasters"), list) and meta["rasters"]:
            n_images = len(meta["rasters"])
        elif isinstance(meta.get("memos"), list) and meta["memos"]:
            n_images = len(meta["memos"])
        elif eval_items and n_charts is None:
            n_images = len(eval_items)

    n_dossiers = _first_int(metric_dicts, ("n_dossiers", "n_incidents", "n_cases"))
    if n_dossiers is None and isinstance(meta.get("dossiers"), list) and meta["dossiers"]:
        n_dossiers = len(meta["dossiers"])
    if n_dossiers is None and isinstance(dos_doc.get("dossiers"), list) and dos_doc["dossiers"]:
        n_dossiers = len(dos_doc["dossiers"])

    return {
        "n_images": n_images,
        "n_dossiers": n_dossiers,
        "n_charts": n_charts,
        "mole_acc": mole_acc,
        "decoy_acc": decoy_acc,
        "naive_mole_acc": naive_mole_acc,
        "naive_trap_rate": naive_trap_rate,
        "mm_mean": mm_mean,
        "blind_mean": blind_mean,
        "oracle_mean": oracle_mean,
        "mm_acc": mm_acc,
        "blind_acc": blind_acc,
        "vision_acc": vision_acc,
        "clean_vision_acc": clean_vision_acc,
        "thresh_acc": thresh_acc,
        "day_exact_acc": day_exact_acc,
        "day_w1_acc": day_w1_acc,
        "bleed_acc": bleed_acc,
    }


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
        c_biased = _float_from(meta, ("carbon_biased_mean", "biased_mean_score", "biased_mean"))
        c_templ = _float_from(meta, ("carbon_template_mean", "template_mean_score", "template_mean"))
        if c_biased is not None and c_templ is not None:
            segs_wt: list[str] = []
            c_acc = _float_from(meta, ("carbon_biased_accuracy", "biased_accuracy"))
            if c_acc is not None:
                segs_wt.append(f"acc {_fmt_pct(c_acc)}")
            segs_wt.append(f"biased {c_biased:+.3f} vs template {c_templ:+.3f}")
            ep_n = _first_int([meta], ("episode_count", "n_episodes"))
            if ep_n is not None:
                segs_wt[-1] = f"{segs_wt[-1]} (n={ep_n})"
            return ", ".join(segs_wt)

        audit_doc = companions.get("audit_report") if isinstance(companions.get("audit_report"), dict) else {}
        non_leak = audit_doc.get("non_leak") if isinstance(audit_doc.get("non_leak"), dict) else {}
        probe_doc = non_leak.get("text_probe") if isinstance(non_leak.get("text_probe"), dict) else {}
        parity_doc = audit_doc.get("solver_parity") if isinstance(audit_doc.get("solver_parity"), dict) else {}
        probe_acc = _first_float([meta, probe_doc], ("probe_accuracy", "stego_probe_accuracy", "accuracy"))
        if audit_doc or probe_acc is not None or meta.get("n_encodings") is not None or meta.get("encodings_tested") is not None:
            audit_parts: list[str] = []
            n_w = _first_int([meta, audit_doc], ("n_worlds", "n_seeds"))
            if n_w is not None:
                unit = "worlds" if meta.get("n_worlds") is not None else "seeds"
                audit_parts.append(f"{n_w} {unit}")
            n_enc = _first_int([meta], ("n_encodings", "encodings_tested"))
            if n_enc is not None:
                audit_parts.append(f"{n_enc} encodings")
            tv = _first_int([meta, non_leak], ("truth_leak_violations", "truth_violations", "n_truth_violations"))
            if tv is not None:
                audit_parts.append(f"{tv} truth leaks")
            if probe_acc is not None:
                audit_parts.append(f"probe {_fmt_pct(probe_acc)}")
            w_mean = _first_float([meta, parity_doc], ("world_mean_score", "solver_mean_score"))
            t_mean = _first_float([meta, parity_doc], ("template_mean_score", "template_baseline_mean_score"))
            if w_mean is not None and t_mean is not None:
                audit_parts.append(f"solver {w_mean:+.3f} vs {t_mean:+.3f}")
            if audit_parts:
                return ", ".join(audit_parts)

        parts: list[str] = []
        if meta.get("n_worlds") is not None:
            parts.append(f"{int(meta['n_worlds'])} worlds")
        elif meta.get("n_events_generated") is not None:
            n_ev = int(meta["n_events_generated"])
            n_sd = len(meta["seeds"]) if isinstance(meta.get("seeds"), list) and meta["seeds"] else None
            parts.append(f"{n_ev} events ({n_sd} seeds)" if n_sd else f"{n_ev} events")
        elif meta.get("n_messages") is not None:
            n_msg = int(meta["n_messages"])
            n_sd = int(meta["n_seeds"]) if isinstance(meta.get("n_seeds"), int) else None
            parts.append(f"{n_msg} msgs ({n_sd} seeds)" if n_sd else f"{n_msg} msgs")
        if meta.get("truth_leak_violations") is not None:
            parts.append(f"{int(meta['truth_leak_violations'])} truth leaks")
        if meta.get("lint_violations") is not None:
            parts.append(f"{int(meta['lint_violations'])} lint errs")
        sol_ms = _float_from(meta, ("solver_mean_score",))
        if sol_ms is not None:
            parts.append(f"solver {sol_ms:+.3f}")
        if not parts and meta.get("llm_ok_count") is not None:
            parts.append(f"{int(meta['llm_ok_count'])} LLM worlds ok")
        return ", ".join(parts) if parts else "verified world text"

    if role == "adaptive_mole":
        if meta.get("investigator_score") is not None and meta.get("solver_score") is not None:
            inv_s = float(meta["investigator_score"])
            sol_s = float(meta["solver_score"])
            clash_str = f"investigator {inv_s:+.3f} vs solver {sol_s:+.3f}"
            if meta.get("mole_clash_days") is not None:
                clash_str += f" ({int(meta['mole_clash_days'])}d clash)"
            return clash_str
        if meta.get("best_fitness") is not None:
            fit = float(meta["best_fitness"])
            extras: list[str] = []
            if meta.get("fresh_solver_accuracy") is not None:
                extras.append(f"solver acc {_fmt_pct(float(meta['fresh_solver_accuracy']))}")
            if meta.get("n_valid_llm_children") is not None:
                extras.append(f"{int(meta['n_valid_llm_children'])} LLM children")
            suffix = (", " + ", ".join(extras)) if extras else ""
            return f"fitness {fit:.3f}{suffix}"
        if meta.get("n_kept") is not None and meta.get("n_llm_valid") is not None:
            base_kept = f"kept {int(meta['n_kept'])}/{int(meta['n_llm_valid'])} solvable scenarios"
            s_mean = _float_from(meta, ("eval_full_solver_mean", "kept_solver_mean", "design_solver_mean"))
            h_mean = _float_from(meta, ("eval_heuristic_mean", "kept_heuristic_mean", "design_heuristic_mean"))
            if s_mean is not None and h_mean is not None:
                return f"{base_kept}, solver {s_mean:+.3f} vs heuristic {h_mean:+.3f}"
            if s_mean is not None:
                return f"{base_kept}, solver {s_mean:+.3f}"
            return base_kept
        if meta.get("solver_accuracy") is not None:
            acc = _fmt_pct(float(meta["solver_accuracy"]))
            sol_m = _float_from(meta, ("solver_mean",))
            heur_m = _float_from(meta, ("heuristic_mean",))
            moves_n = _first_int([meta], ("mole_decisions_count",))
            seg_m: list[str] = []
            if moves_n is not None:
                seg_m.append(f"{moves_n} mole moves")
            if sol_m is not None:
                seg_m.append(f"solver {sol_m:+.3f} (acc {acc})")
            else:
                seg_m.append(f"solver acc {acc}")
            if heur_m is not None:
                seg_m.append(f"heuristic {heur_m:+.3f}")
            return ", ".join(seg_m)
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
            ms_str = f"mean {float(meta['mean_score']):+.3f}"
            if isinstance(meta.get("accuracy"), (int, float)):
                ms_str += f", acc {_fmt_pct(float(meta['accuracy']))}"
            ep_cnt = _first_int([meta], ("episode_count", "n_episodes"))
            if ep_cnt is not None:
                ms_str += f" (n={ep_cnt})"
            return ms_str
        return "investigator run"

    if role == "failure_analyst":
        cal_doc = companions.get("calibration") if isinstance(companions.get("calibration"), dict) else {}
        ece_v = _first_float([meta, cal_doc], ("ece", "expected_calibration_error"))
        brier_v = _first_float([meta, cal_doc], ("brier_score", "brier"))
        ev_lost = _first_float([meta, cal_doc], ("ev_lost_total", "total_ev_lost"))
        if ece_v is not None or brier_v is not None or ev_lost is not None:
            cal_parts: list[str] = []
            n_cal = _first_int([meta, cal_doc], ("n_calibrated_episodes", "n_episodes_packed", "n_episodes"))
            if n_cal is not None:
                cal_parts.append(f"{n_cal} eps")
            if ece_v is not None:
                cal_parts.append(f"ECE {ece_v:.3f}")
            elif brier_v is not None:
                cal_parts.append(f"Brier {brier_v:.3f}")
            if ev_lost is not None:
                cal_parts.append(f"EV lost {ev_lost:.2f}")
            vq_pct = _first_float([meta, cal_doc], ("verified_quotes_pct",))
            if vq_pct is not None:
                cal_parts.append(f"{_fmt_pct(vq_pct)} verified quotes")
            return ", ".join(cal_parts)

        atlas_doc = companions.get("atlas") if isinstance(companions.get("atlas"), dict) else {}
        atlas_corpus = atlas_doc.get("corpus") if isinstance(atlas_doc.get("corpus"), dict) else {}
        atlas_qv = atlas_doc.get("quote_verification") if isinstance(atlas_doc.get("quote_verification"), dict) else {}
        atlas_ag = atlas_doc.get("agreement") if isinstance(atlas_doc.get("agreement"), dict) else {}
        ag_rate = _first_float([meta, atlas_ag], ("solver_agreement_rate", "agreement_rate", "rate"))
        if atlas_doc or ag_rate is not None or meta.get("n_modes") is not None:
            at_parts: list[str] = []
            n_ep_at = _first_int([meta, atlas_corpus], ("n_episodes_packed", "n_episodes", "episodes"))
            if n_ep_at is not None:
                at_parts.append(f"{n_ep_at} eps")
            n_modes = _first_int([meta], ("n_modes",))
            if n_modes is None and isinstance(atlas_doc.get("modes"), list):
                n_modes = len(atlas_doc["modes"])
            if n_modes is not None:
                at_parts.append(f"{n_modes} modes")
            vq_at = _first_float([meta, atlas_qv], ("verified_quotes_pct", "pct"))
            if vq_at is not None:
                at_parts.append(f"{_fmt_pct(vq_at)} verified quotes")
            if ag_rate is not None:
                at_parts.append(f"{_fmt_pct(ag_rate)} solver agreement")
            if at_parts:
                return ", ".join(at_parts)

        parts = []
        if meta.get("n_episodes_packed") is not None:
            parts.append(f"{int(meta['n_episodes_packed'])} eps packed")
        rep = companions.get("report")
        if isinstance(rep, dict) and isinstance(rep.get("clusters"), list):
            parts.append(f"{len(rep['clusters'])} clusters")
        elif meta.get("n_clusters") is not None:
            parts.append(f"{int(meta['n_clusters'])} clusters")
        if meta.get("verified_quotes_pct") is not None:
            parts.append(f"{_fmt_pct(float(meta['verified_quotes_pct']))} verified quotes")
        return ", ".join(parts) if parts else "long-context failure report"

    if role == "exploit_hunter":
        sw = companions.get("swarm") if isinstance(companions.get("swarm"), dict) else {}
        sm = companions.get("summary") if isinstance(companions.get("summary"), dict) else {}
        sw_counts = sw.get("counts") if isinstance(sw.get("counts"), dict) else {}
        att_n = _first_int([meta, sw_counts, sm], ("attempts", "runs"))
        exp_n = _first_int([meta, sw_counts, sm], ("exploits", "exploits_found"))
        viol_n = _first_int([meta, sw_counts, sm], ("invariant_violations",))
        pack_files = _first_int([meta, sw], ("pack_files",))
        mcp_att = _first_int([meta, sw_counts, sm], ("mcp_attempts",))
        tool_calls = _first_int([meta, sw_counts, sm], ("tool_calls",))

        parts = []
        if pack_files is not None:
            parts.append(f"{pack_files} repo files")
        if att_n is not None:
            if mcp_att is not None and tool_calls is not None and pack_files is None:
                parts.append(f"{att_n} attempts ({mcp_att} MCP, {tool_calls} tool calls)")
            elif mcp_att is not None and pack_files is None:
                parts.append(f"{att_n} attempts ({mcp_att} MCP)")
            else:
                parts.append(f"{att_n} attempts")
        if exp_n is not None:
            parts.append(f"{exp_n} exploits")
        if viol_n is not None:
            parts.append(f"{viol_n} violations")
        return ", ".join(parts) if parts else "ledger-verified red-team audit"

    if role == "multimodal_evidence":
        mm_info = _extract_multimodal_metrics(meta, companions)
        n_images = mm_info["n_images"]
        n_dossiers = mm_info["n_dossiers"]
        n_charts = mm_info["n_charts"]
        mole_acc = mm_info["mole_acc"]
        decoy_acc = mm_info["decoy_acc"]
        naive_acc = mm_info["naive_mole_acc"]
        mm_mean = mm_info["mm_mean"]
        bl_mean = mm_info["blind_mean"]
        vis_acc = mm_info["vision_acc"]
        clean_vis_acc = mm_info["clean_vision_acc"]
        thresh_acc = mm_info["thresh_acc"]
        day_exact = mm_info["day_exact_acc"]
        day_w1 = mm_info["day_w1_acc"]
        bleed_acc = mm_info["bleed_acc"]
        sub_l = str(meta.get("subrole") or "").lower()

        if mm_mean is not None and bl_mean is not None:
            parts = []
            if n_images is not None:
                parts.append(f"{n_images} images")
            if vis_acc is not None:
                if clean_vis_acc is not None and "degraded" in sub_l:
                    parts.append(f"vision acc {_fmt_pct(vis_acc)} (clean {_fmt_pct(clean_vis_acc)})")
                else:
                    parts.append(f"vision acc {_fmt_pct(vis_acc)}")
            parts.append(f"score {mm_mean:+.3f} vs blind {bl_mean:+.3f}")
            return ", ".join(parts)

        if mole_acc is not None:
            parts = []
            if n_images is not None and n_dossiers is not None:
                parts.append(f"{n_images} images ({n_dossiers} dossiers)")
            elif n_images is not None:
                parts.append(f"{n_images} images")
            elif n_dossiers is not None:
                parts.append(f"{n_dossiers} dossiers")
            parts.append(f"mole acc {_fmt_pct(mole_acc)}")
            if decoy_acc is not None and naive_acc is not None:
                parts.append(f"decoy acc {_fmt_pct(decoy_acc)} vs naive {_fmt_pct(naive_acc)}")
            elif decoy_acc is not None:
                parts.append(f"decoy acc {_fmt_pct(decoy_acc)}")
            elif naive_acc is not None:
                parts.append(f"vs naive {_fmt_pct(naive_acc)}")
            if vis_acc is not None and "dossier" in sub_l:
                parts.append(f"vision acc {_fmt_pct(vis_acc)}")
            return ", ".join(parts)

        if n_charts is not None or thresh_acc is not None or day_exact is not None:
            parts = []
            if n_charts is not None:
                parts.append(f"{n_charts} charts")
            elif n_images is not None:
                parts.append(f"{n_images} charts")
            if thresh_acc is not None:
                parts.append(f"threshold acc {_fmt_pct(thresh_acc)}")
            if day_exact is not None:
                parts.append(f"exact day {_fmt_pct(day_exact)}")
            elif day_w1 is not None:
                parts.append(f"day +-1 {_fmt_pct(day_w1)}")
            elif bleed_acc is not None:
                parts.append(f"bleed acc {_fmt_pct(bleed_acc)}")
            return ", ".join(parts) if parts else "multimodal vision forensics"

        parts = []
        if n_images is not None:
            parts.append(f"{n_images} images")
        if vis_acc is not None:
            parts.append(f"vision acc {_fmt_pct(vis_acc)}")
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


def _canonical_rank_key(
    role: str,
    run: dict[str, Any],
    meta: dict[str, Any],
    companions: dict[str, Any],
) -> tuple[Any, ...]:
    subrole_l = str(run.get("subrole") or "").lower()
    sample_n = int(run.get("sample_count") or 0)
    mm_info = _extract_multimodal_metrics(meta, companions) if role == "multimodal_evidence" else {}

    has_ablation = 0
    if role == "multimodal_evidence":
        if (mm_info.get("mm_mean") is not None and mm_info.get("blind_mean") is not None) or (
            mm_info.get("mole_acc") is not None and mm_info.get("naive_mole_acc") is not None
        ):
            has_ablation = 1
    elif role == "world_text":
        if (
            meta.get("carbon_biased_mean") is not None
            or meta.get("solver_mean_score") is not None
            or "ablation" in subrole_l
            or isinstance(companions.get("audit_report"), dict)
        ):
            has_ablation = 1
    elif role == "adaptive_mole":
        if (
            meta.get("best_fitness") is not None
            or isinstance(meta.get("baseline_default_mole"), dict)
            or (meta.get("investigator_score") is not None and meta.get("solver_score") is not None)
            or "ablation" in subrole_l
        ):
            has_ablation = 1
    elif role == "investigators":
        if isinstance(meta.get("levels_summary"), dict) or (not run["meta_flags"]["hinted"] and sample_n >= 2):
            has_ablation = 1
    elif role == "failure_analyst":
        if (
            isinstance(companions.get("atlas"), dict)
            or meta.get("n_episodes_packed") is not None
            or meta.get("ece") is not None
        ):
            has_ablation = 1
    elif role == "exploit_hunter":
        if (
            (isinstance(meta.get("exploits"), int) and meta["exploits"] > 0)
            or meta.get("pack_files") is not None
            or meta.get("mcp_attempts") is not None
            or isinstance(companions.get("swarm"), dict)
        ):
            has_ablation = 1

    controlled_ablation_bonus = (
        1
        if (
            "ablation" in subrole_l
            or "sweep" in subrole_l
            or "dossier" in subrole_l
            or (
                role == "multimodal_evidence"
                and mm_info.get("mm_mean") is not None
                and mm_info.get("blind_mean") is not None
            )
        )
        else 0
    )
    is_v14 = 1 if (meta.get("tiers_version") == "v1.4" or run.get("source_kind") == "v1.4") else 0
    unhinted = 0 if (run["meta_flags"]["hinted"] and "ablation" not in subrole_l) else 1

    if role == "multimodal_evidence":
        img_n = int(mm_info.get("n_images") or mm_info.get("n_charts") or 0)
        richness = max(sample_n, img_n) + sample_n
    else:
        richness = sample_n

    u = run["usage"]
    tok_total = int(u["in"]) + int(u["out"]) + int(u["thinking"])
    return (
        has_ablation,
        unhinted,
        is_v14,
        controlled_ablation_bonus,
        richness,
        tok_total,
        run["run_folder"],
    )


def _build_multimodal_spotlight(
    mm_runs_with_raw: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for run, meta, companions in mm_runs_with_raw:
        if not run["verified"]:
            continue
        mm = _extract_multimodal_metrics(meta, companions)
        sub_l = str(run["subrole"]).lower()
        folder_l = str(run["run_folder"]).lower()
        raw_tier = str(run.get("tier") or "").strip()
        if not raw_tier and isinstance(meta.get("tiers"), list) and meta["tiers"]:
            raw_tier = "+".join(str(x) for x in meta["tiers"] if str(x).strip())
        if not raw_tier and isinstance(meta.get("worlds"), list) and meta["worlds"]:
            w_tiers = list(
                dict.fromkeys(
                    str(w.get("tier") or "").strip()
                    for w in meta["worlds"]
                    if isinstance(w, dict) and str(w.get("tier") or "").strip()
                )
            )
            if w_tiers:
                raw_tier = "+".join(w_tiers)
        tier_lbl = raw_tier or str(meta.get("tiers_version") or "").strip()
        n_img = int(mm["n_images"] or mm["n_charts"] or 0)

        if mm["mm_mean"] is not None and mm["blind_mean"] is not None:
            v_val = float(mm["mm_mean"])
            b_val = float(mm["blind_mean"])
            delta = v_val - b_val
            if "degraded" in sub_l or "degraded" in folder_l:
                title = f"Degraded Scan Vision ({tier_lbl or 'v1.4'})"
            elif "scanned" in sub_l or "scanned" in folder_l:
                title = f"Scanned Evidence Vision ({tier_lbl or 'v1.4'})"
            else:
                title = f"Memo Watermark Vision ({tier_lbl or 'v1.4'})"
            sub_parts = [f"{n_img} PNGs"] if n_img > 0 else []
            if mm["vision_acc"] is not None:
                sub_parts.append(f"read {_fmt_pct(mm['vision_acc'])}")
            v_disp = f"Vision {v_val:+.3f}"
            if mm["mm_acc"] is not None:
                v_disp += f" ({_fmt_pct(mm['mm_acc'])} catch)"
            elif mm["vision_acc"] is not None:
                v_disp += f" ({_fmt_pct(mm['vision_acc'])} acc)"
            b_disp = f"Blind {b_val:+.3f}"
            if mm["blind_acc"] is not None:
                b_disp += f" ({_fmt_pct(mm['blind_acc'])} catch)"
            items.append({
                "run_folder": run["run_folder"],
                "subrole": run["subrole"],
                "tier": tier_lbl,
                "model_id": run["model_id"],
                "commit": run["commit"],
                "kind": "memo_ablation",
                "title": title,
                "subtitle": " | ".join(sub_parts) if sub_parts else run["subrole"],
                "n_images": n_img,
                "unit": "score",
                "vision_metric": round(v_val, 4),
                "vision_display": v_disp,
                "baseline_metric": round(b_val, 4),
                "baseline_name": "Blind (No Vision)",
                "baseline_display": b_disp,
                "gain_display": f"{delta:+.3f} score",
            })
            continue

        if mm["mole_acc"] is not None:
            v_ratio = _norm_ratio(float(mm["mole_acc"]))
            if "dossier" in sub_l:
                title = f"Incident Dossier Vision ({tier_lbl or 'v1.4'})"
                kind = "dossier_vision"
            elif "sweep" in sub_l:
                title = f"SOC Raster Sweep ({tier_lbl or 'v1.4'})"
                kind = "soc_vision"
            else:
                title = f"SOC Raster Vision ({tier_lbl or run['subrole']})"
                kind = "soc_vision"
            sub_parts = [f"{n_img} PNGs"] if n_img > 0 else []
            if mm["decoy_acc"] is not None:
                sub_parts.append(f"decoy {_fmt_pct(mm['decoy_acc'])}")
            v_disp = f"Vision {_fmt_pct(v_ratio)} mole"
            if mm["decoy_acc"] is not None:
                v_disp += f" ({_fmt_pct(mm['decoy_acc'])} decoy)"

            if mm["naive_mole_acc"] is not None:
                b_ratio = _norm_ratio(float(mm["naive_mole_acc"]))
                trapped = (
                    (mm["naive_trap_rate"] is not None and _norm_ratio(float(mm["naive_trap_rate"])) >= 0.5)
                    or b_ratio <= 1e-6
                )
                trap_tag = "decoy-trapped" if trapped else "mole acc"
                b_disp = f"Naive Log {_fmt_pct(b_ratio)} ({trap_tag})"
                gain_disp = f"{(v_ratio - b_ratio) * 100.0:+.0f}pp vs naive"
                b_metric: float | None = round(b_ratio, 4)
                b_name = "Naive Log Baseline"
            else:
                b_metric = None
                b_name = "-"
                b_disp = "multi-image synthesis"
                gain_disp = (
                    f"{_fmt_pct(mm['decoy_acc'])} decoy acc"
                    if mm["decoy_acc"] is not None
                    else f"{_fmt_pct(v_ratio)} mole acc"
                )

            items.append({
                "run_folder": run["run_folder"],
                "subrole": run["subrole"],
                "tier": tier_lbl,
                "model_id": run["model_id"],
                "commit": run["commit"],
                "kind": kind,
                "title": title,
                "subtitle": " | ".join(sub_parts) if sub_parts else run["subrole"],
                "n_images": n_img,
                "unit": "pct",
                "vision_metric": round(v_ratio, 4),
                "vision_display": v_disp,
                "baseline_metric": b_metric,
                "baseline_name": b_name,
                "baseline_display": b_disp,
                "gain_display": gain_disp,
            })
            continue

        if mm["thresh_acc"] is not None or mm["n_charts"] is not None:
            raw_t = mm["thresh_acc"] if mm["thresh_acc"] is not None else (mm["day_exact_acc"] or 0.0)
            v_ratio = _norm_ratio(float(raw_t))
            chart_prefix = "Trajectory Chart Forensics" if "trajectory" in sub_l else "Belief-Chart Forensics"
            title = f"{chart_prefix} ({tier_lbl or 'PNG'})"
            sub_parts = [f"{n_img} charts"] if n_img > 0 else [run["subrole"]]
            v_disp = f"Vision {_fmt_pct(v_ratio)} threshold"
            if mm["day_exact_acc"] is not None:
                v_disp += f" ({_fmt_pct(mm['day_exact_acc'])} exact day)"
            items.append({
                "run_folder": run["run_folder"],
                "subrole": run["subrole"],
                "tier": tier_lbl,
                "model_id": run["model_id"],
                "commit": run["commit"],
                "kind": "chart_forensics",
                "title": title,
                "subtitle": " | ".join(sub_parts),
                "n_images": n_img,
                "unit": "pct",
                "vision_metric": round(v_ratio, 4),
                "vision_display": v_disp,
                "baseline_metric": None,
                "baseline_name": "-",
                "baseline_display": "chart-only input",
                "gain_display": (
                    f"{_fmt_pct(mm['day_exact_acc'])} exact day"
                    if mm["day_exact_acc"] is not None
                    else f"{_fmt_pct(v_ratio)} threshold"
                ),
            })

    items.sort(
        key=lambda it: (
            it["baseline_metric"] is None,
            it["kind"] != "memo_ablation",
            -it["n_images"],
            it["tier"] != "hard",
            it["run_folder"],
        )
    )
    return {
        "n_runs": len(items),
        "n_ablation_runs": sum(1 for it in items if it["baseline_metric"] is not None),
        "total_images": sum(it["n_images"] for it in items),
        "items": items,
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
        for cname in (
            "swarm",
            "summary",
            "report",
            "results",
            "diagnoses",
            "comparison",
            "solver_check",
            "atlas",
            "audit_report",
            "dossier",
            "evaluation",
            "calibration",
        ):
            cj = _load_json(cdir / f"{cname}.json")
            if isinstance(cj, (dict, list)):
                companions[cname] = cj

        primary_comp: dict[str, Any] = {}
        for pk in ("swarm", "summary", "report", "results", "comparison", "atlas", "audit_report", "dossier"):
            cand_p = companions.get(pk)
            if isinstance(cand_p, dict):
                primary_comp = cand_p
                break
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
        swarm_dict = companions.get("swarm") if isinstance(companions.get("swarm"), dict) else None
        usage = _extract_usage(meta, episodes, swarm_dict, model_id)
        sample_count = _extract_sample_count(cdir, meta, episodes, companions)
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
        if bool(meta.get("stub")) or bool(meta.get("synthetic")):
            reasons.append("stub")
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
            "sample_count": sample_count,
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
    raw_by_folder: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
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
        raw_by_folder[out_r["run_folder"]] = (r["_meta"], r["_companions"])
        runs.append(out_r)

    canonical_runs: dict[str, dict[str, Any] | None] = {}
    canonical_folders: set[str] = set()
    for role in ROLES:
        eligible = [
            r for r in runs
            if r["role"] == role and r["verified"] and r["model_id"] == "gemini-4-carbon"
        ]
        if eligible:
            best = max(
                eligible,
                key=lambda r: _canonical_rank_key(
                    role,
                    r,
                    raw_by_folder[r["run_folder"]][0],
                    raw_by_folder[r["run_folder"]][1],
                ),
            )
            canonical_folders.add(best["run_folder"])
            canonical_runs[role] = None
        else:
            canonical_runs[role] = None

    for r in runs:
        r["is_canonical"] = r["run_folder"] in canonical_folders
        if r["is_canonical"]:
            canonical_runs[r["role"]] = dict(r)

    runs.sort(
        key=lambda r: (
            ROLES.index(r["role"]),
            not r["is_canonical"],
            not (r["verified"] and r["model_id"] == "gemini-4-carbon"),
            not r["verified"],
            r["run_folder"],
        )
    )

    paired = _compute_paired(runs, raw_episodes_by_run, solver_map)
    mm_runs_with_raw = [
        (r, raw_by_folder[r["run_folder"]][0], raw_by_folder[r["run_folder"]][1])
        for r in runs
        if r["role"] == "multimodal_evidence" and r["run_folder"] in raw_by_folder
    ]
    spotlight = _build_multimodal_spotlight(mm_runs_with_raw)

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
            "canonical_run": canonical_runs[role],
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
        "canonical_runs": canonical_runs,
        "runs": runs,
        "paired_comparison": paired,
        "multimodal_spotlight": spotlight,
        "totals": {
            "n_roles_total": len(ROLES),
            "n_roles_verified": len(verified_roles),
            "n_canonical_runs": sum(1 for v in canonical_runs.values() if v is not None),
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


def _fmt_tokens_triple(usage: dict[str, Any]) -> str:
    tin = int(usage.get("in", 0))
    tout = int(usage.get("out", 0))
    tthink = int(usage.get("thinking", 0))
    return f"{tin:,} / {tout:,} / {tthink:,}"


def render_roles_markdown(data: dict[str, Any]) -> str:
    tot = data["totals"]
    canon_map = data.get("canonical_runs") or {}
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
        "## Canonical One-Run-Per-Role Prize Claims",
        "",
        "| Role | Canonical Run Folder | Model ID | Commit | Samples/Episodes | Tokens (in / out / thinking) | Cost (USD) | Headline Metric |",
        "|---|---|---|---|---:|---|---:|---|",
    ]

    for role in ROLES:
        canon = canon_map.get(role)
        if not isinstance(canon, dict):
            lines.append(f"| {md_cell(role)} | pending | - | - | 0 | 0 / 0 / 0 | $0.0000 | pending |")
            continue
        cu = canon["usage"]
        c_commit = f"`{md_cell(canon['commit'])}`" if canon["commit"] != "-" else "-"
        c_folder = f"`{md_cell(canon['run_folder'])}`"
        c_samples = str(int(canon.get("sample_count", 0))) if int(canon.get("sample_count", 0)) > 0 else "-"
        c_toks = _fmt_tokens_triple(cu)
        lines.append(
            f"| {md_cell(role)} | {c_folder} | {md_cell(canon['model_id'])} | {c_commit} | "
            f"{c_samples} | {md_cell(c_toks)} | ${cu['cost_usd']:.4f} | {md_cell(canon['key_metric'])} |"
        )

    lines.extend([
        "",
        "## All Committed Gemini Role Runs",
        "",
        "| Role | Subrole | Model ID | Commit | Run Folder | Key Metric | Tokens (in/out) | Verified |",
        "|---|---|---|---|---|---|---|---|",
    ])

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

    spotlight = data.get("multimodal_spotlight") or {}
    spot_items = spotlight.get("items") or []
    if spot_items:
        lines.extend([
            "",
            "## Multimodal Vision vs Blind / Naive Baseline Spotlight",
            "",
            "| Evidence Track | Images Read | Gemini Vision | Blind / Naive Baseline | Gain | Run Folder |",
            "|---|---:|---|---|---|---|",
        ])
        for it in spot_items:
            lines.append(
                f"| {md_cell(it['title'])} | {it['n_images']} | {md_cell(it['vision_display'])} | "
                f"{md_cell(it['baseline_display'])} | {md_cell(it['gain_display'])} | `{md_cell(it['run_folder'])}` |"
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


def _svg_multimodal_spotlight(spotlight: dict[str, Any]) -> str:
    items = list(spotlight.get("items") or [])
    if not items:
        return '<div class="empty-box">No verified multimodal_evidence runs discovered yet.</div>'

    width = 680
    row_h = 66
    top = 32
    left = 206
    right = 198
    height = top + len(items) * row_h + 18
    plot_w = width - left - right

    raw_vals: list[float] = [0.0, 1.0]
    for it in items:
        raw_vals.append(float(it["vision_metric"]))
        if it["baseline_metric"] is not None:
            raw_vals.append(float(it["baseline_metric"]))
    min_v = min(raw_vals)
    max_v = max(raw_vals)
    span = max(0.01, max_v - min_v)
    zero_x = left + (0.0 - min_v) / span * plot_w

    parts: list[str] = [
        f'<svg id="multimodal-spotlight-svg" class="svg-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Multimodal Vision vs Blind and Naive Baseline Spotlight">',
        f'<line x1="{zero_x:.1f}" y1="{top - 8}" x2="{zero_x:.1f}" y2="{height - 12}" class="axis-line"/>',
        f'<rect x="{left}" y="4" width="12" height="10" rx="2" fill="var(--s6)"/>',
        f'<text x="{left + 17}" y="13" class="svg-leg">gemini-4-carbon Vision</text>',
        f'<rect x="{left + 158}" y="4" width="12" height="10" rx="2" fill="var(--s2)"/>',
        f'<text x="{left + 175}" y="13" class="svg-leg">Blind / Naive Log Baseline</text>',
    ]

    for idx, it in enumerate(items):
        y0 = top + idx * row_h
        parts.append(f'<text x="{left - 10}" y="{y0 + 19}" text-anchor="end" class="svg-label">{esc(it["title"])}</text>')
        parts.append(f'<text x="{left - 10}" y="{y0 + 35}" text-anchor="end" class="svg-leg">{esc(it["subtitle"])}</text>')
        parts.append(f'<rect x="{left}" y="{y0 + 6}" width="{plot_w}" height="16" rx="3" fill="var(--wash)"/>')

        v_val = float(it["vision_metric"])
        vx = left + (v_val - min_v) / span * plot_w
        v_bx = min(zero_x, vx)
        v_bw = max(3.0, abs(vx - zero_x))
        v_tx = max(v_bx + v_bw, zero_x) + 6
        parts.append(f'<rect x="{v_bx:.1f}" y="{y0 + 6}" width="{v_bw:.1f}" height="16" rx="3" fill="var(--s6)"/>')
        parts.append(f'<text x="{v_tx:.1f}" y="{y0 + 18}" class="svg-val">{esc(it["vision_display"])}</text>')

        b_metric = it["baseline_metric"]
        by = y0 + 27
        if b_metric is not None:
            parts.append(f'<rect x="{left}" y="{by}" width="{plot_w}" height="16" rx="3" fill="var(--wash)"/>')
            b_val = float(b_metric)
            bx_end = left + (b_val - min_v) / span * plot_w
            b_bx = min(zero_x, bx_end)
            b_bw = max(3.0, abs(bx_end - zero_x))
            b_tx = max(b_bx + b_bw, zero_x) + 6
            parts.append(f'<rect x="{b_bx:.1f}" y="{by}" width="{b_bw:.1f}" height="16" rx="3" fill="var(--s2)"/>')
            parts.append(f'<text x="{b_tx:.1f}" y="{by + 12}" class="svg-val">{esc(it["baseline_display"])}</text>')
        else:
            parts.append(f'<rect x="{zero_x:.1f}" y="{by + 4}" width="3" height="10" rx="1" fill="var(--muted)"/>')
            parts.append(f'<text x="{zero_x + 9:.1f}" y="{by + 12}" class="svg-leg">{esc(it["gain_display"])}</text>')

    parts.append("</svg>")
    return "".join(parts)


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
    canon_map = data.get("canonical_runs") or {}
    spotlight = data.get("multimodal_spotlight") or {"n_runs": 0, "n_ablation_runs": 0, "total_images": 0, "items": []}

    canonical_rows: list[str] = []
    c_tot_samples = 0
    c_tot_in = 0
    c_tot_out = 0
    c_tot_think = 0
    c_tot_cost = 0.0
    c_verified_n = 0
    for role in ROLES:
        canon = canon_map.get(role)
        if not isinstance(canon, dict):
            canonical_rows.append(
                f'<tr data-canon-role="{esc(role)}">'
                f'<td><code>{esc(role)}</code></td>'
                f'<td><span class="badge pending">pending</span></td>'
                f'<td>-</td>'
                f'<td>-</td>'
                f'<td class="num">0</td>'
                f'<td class="num">0 / 0 / 0</td>'
                f'<td class="num">$0.0000</td>'
                f'<td>pending</td>'
                f'</tr>'
            )
            continue
        c_verified_n += 1
        cu = canon["usage"]
        sc_val = int(canon.get("sample_count", 0))
        c_tot_samples += sc_val
        c_tot_in += int(cu["in"])
        c_tot_out += int(cu["out"])
        c_tot_think += int(cu["thinking"])
        c_tot_cost += float(cu["cost_usd"])
        sc_txt = str(sc_val) if sc_val > 0 else "-"
        canonical_rows.append(
            f'<tr data-canon-role="{esc(role)}">'
            f'<td><code>{esc(role)}</code></td>'
            f'<td><code>{esc(canon["run_folder"])}</code></td>'
            f'<td><code class="model-chip">{esc(canon["model_id"])}</code></td>'
            f'<td><code>{esc(canon["commit"])}</code></td>'
            f'<td class="num">{esc(sc_txt)}</td>'
            f'<td class="num">{esc(_fmt_tokens_triple(cu))}</td>'
            f'<td class="num">${cu["cost_usd"]:.4f}</td>'
            f'<td><b>{esc(canon["key_metric"])}</b></td>'
            f'</tr>'
        )
    canonical_rows.append(
        f'<tr class="tot-row">'
        f'<td><b>canonical total</b></td>'
        f'<td><b>{c_verified_n} / {len(ROLES)} verified prize roles</b></td>'
        f'<td><code>gemini-4-carbon</code></td>'
        f'<td>-</td>'
        f'<td class="num"><b>{c_tot_samples:,}</b></td>'
        f'<td class="num"><b>{c_tot_in:,} / {c_tot_out:,} / {c_tot_think:,}</b></td>'
        f'<td class="num"><b>${c_tot_cost:.4f}</b></td>'
        f'<td><b>1 labelled real run per role</b></td>'
        f'</tr>'
    )

    spotlight_rows: list[str] = []
    for it in spotlight.get("items") or []:
        spotlight_rows.append(
            f'<tr>'
            f'<td><b>{esc(it["title"])}</b><div class="cell-sub"><code>{esc(it["run_folder"])}</code></div></td>'
            f'<td class="num">{it["n_images"]}</td>'
            f'<td><b>{esc(it["vision_display"])}</b></td>'
            f'<td>{esc(it["baseline_display"])}</td>'
            f'<td><span class="badge ok">{esc(it["gain_display"])}</span></td>'
            f'</tr>'
        )
    spotlight_table_html = (
        '<table id="multimodal-spotlight-table" class="list">'
        '<thead><tr>'
        '<th>Evidence Track &amp; Folder</th><th class="num">Images</th>'
        '<th>Gemini Vision</th><th>Blind / Naive Baseline</th><th>Gain</th>'
        '</tr></thead>'
        f'<tbody>{"".join(spotlight_rows)}</tbody>'
        '</table>'
        if spotlight_rows
        else '<div class="empty-box">No verified multimodal_evidence runs discovered yet.</div>'
    )

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
            canon_pill = '<span class="badge canon">CANONICAL</span> ' if run.get("is_canonical") else ""
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
                f'<div>{canon_pill}<span class="badge {b_cls}">{b_txt}</span></div>'
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
        .replace("__CANONICAL_ROWS__", "".join(canonical_rows))
        .replace("__MULTIMODAL_SPOTLIGHT_CHART__", _svg_multimodal_spotlight(spotlight))
        .replace("__MULTIMODAL_SPOTLIGHT_TABLE__", spotlight_table_html)
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

  <section id="sec-canonical" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>01</b> Canonical Prize Claims</div>
        <h2>Canonical One-Run-Per-Role Prize Claims</h2>
        <p class="lede">Flagship verified gemini-4-carbon run per role selected by verification gate, real baseline/blind ablation, and sample depth.</p>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table id="canonical-claims-table" class="list">
          <thead>
            <tr>
              <th>Role</th>
              <th>Canonical Run Folder</th>
              <th>Model ID</th>
              <th>Commit</th>
              <th class="num">Samples/Episodes</th>
              <th class="num">Tokens (in / out / thinking)</th>
              <th class="num">Cost (USD)</th>
              <th>Headline Metric</th>
            </tr>
          </thead>
          <tbody>__CANONICAL_ROWS__</tbody>
        </table>
      </div>
    </div>
  </section>

  <section id="sec-multimodal" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>02</b> Multimodal Evidence Spotlight</div>
        <h2>Multimodal Vision vs Blind / Naive Baseline Spotlight</h2>
        <p class="lede">Direct pixel evidence gains where leaked memos carry watermark variants redacted from text feeds and SOC rasters separate true canary matches from framed after-hours decoys.</p>
      </div>
    </div>
    <div class="grid">
      <div class="card c6">
        <h3>Vision Gain vs Blind &amp; Naive Baselines</h3>
        <p class="sub">Computed directly from discovered multimodal_evidence run artifacts</p>
        __MULTIMODAL_SPOTLIGHT_CHART__
      </div>
      <div class="card c6">
        <h3>Multimodal Evidence Track Summary</h3>
        <p class="sub">Pixel watermark ablations, SOC telemetry rasters, dossiers, and trajectory charts</p>
        <div class="table-wrap">__MULTIMODAL_SPOTLIGHT_TABLE__</div>
      </div>
    </div>
  </section>

  <section id="sec-architecture" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>03</b> Architecture</div>
        <h2>Six Essential Gemini Roles Across the Canary Benchmark Lifecycle</h2>
        <p class="lede">Gemini constructs the company world, evolves and plays the insider mole, investigates leaks via 13 MCP tools, inspects visual document scans, diagnoses long-context trajectory corpora, and red-teams the full repository.</p>
      </div>
    </div>
    <div class="grid">__ARCH_CARDS__</div>
  </section>

  <section id="sec-runs" class="panel">
    <div class="phead">
      <div>
        <div class="kicker"><b>04</b> Provenance &amp; Run Cards</div>
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
        <div class="kicker"><b>05</b> Paired Evaluation</div>
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
        <div class="kicker"><b>06</b> Economics &amp; Accounting</div>
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
        <div class="kicker"><b>07</b> Offline Reproducibility</div>
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
.badge.canon { color: var(--s6); background: rgba(98, 80, 214, 0.14); }
.badge.warn { color: var(--warn); background: rgba(212, 140, 0, 0.15); }
.badge.no { color: var(--crit); background: rgba(201, 51, 51, 0.14); }
.badge.pending { color: var(--muted); background: var(--wash); border: 1px dashed var(--axis); }
.cell-sub { margin-top: 2px; color: var(--muted); font-size: 11px; }
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
