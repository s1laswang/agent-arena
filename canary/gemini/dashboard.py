"""Canary Lab dashboard: the Gemini usage ledger + ladder / atlas / swarm results in ONE static HTML file.

    python -m canary.gemini.dashboard [--ledger DIR_OR_FILE ...] [--results results/gemini]
                                      [--out results/gemini/dashboard.html] [--json]

The page is self-contained (inline CSS/JS/SVG, no network), so it works from disk, offline, and as a
published artifact. Panels whose JSON does not exist yet render as "pending".
`--json` prints the aggregated usage summary (the exact numbers the submission text quotes).

Privacy: the ledger holds counts, never prompts. On top of that, the dashboard only reads whitelisted
fields, reduces error strings to their status code / exception class, never embeds ledger `meta`, and
redacts anything key-shaped in result JSON before it reaches the page.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import glob
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from canary.llm.pricing import CACHED_PRICES, PRICES

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "data" / "gemini" / "ledger"
DEFAULT_RESULTS = ROOT / "results" / "gemini"

# Canonical model order: cheapest -> strongest text models, then the special-purpose ones.
MODEL_ORDER = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-4-hydrogen",
               "gemini-4-argon", "gemini-4-carbon", "gemini-embedding-2", "gemini-3.8-flash-tts",
               "gemini-3.8-flash-lite-tts", "gemini-3.8-live"]
LEVEL_ORDER = ["minimal", "low", "medium", "high"]
SECRET_RE = re.compile(r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
                       r"(?i:api[_-]?key|key|token|secret)\s*[=:]\s*\S+)")
MAX_THUMB_BYTES = 400_000
# USD / 1M (input, output incl. thinking, cached input) for models canary.llm.pricing lacks. Same source and values as
# G2's ladder_report.PRICES (aistudio.google.com/docs/pricing, checked 2026-11-14 14:20 EET). Rows the ledger marked
# cost_unknown are repriced from this table (and from ladder.json "prices_usd_per_1m" when present); the page says so.
EXTRA_PRICES: dict[str, tuple[float, float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025), "gemini-3.5-flash": (0.75, 3.75, 0.075)}


# ---------------------------------------------------------------- helpers
def redact(x: Any) -> Any:
    """Recursively replace key-shaped substrings in every string of a JSON-like value."""
    if isinstance(x, str):
        return SECRET_RE.sub("[redacted]", x)
    if isinstance(x, list):
        return [redact(v) for v in x]
    if isinstance(x, dict):
        return {k: redact(v) for k, v in x.items()}
    return x


def error_type(err: str) -> str:
    """Reduce an error string to a safe label: '429 RESOURCE_EXHAUSTED', 'TimeoutError', or 'other'."""
    if not err:
        return ""
    m = re.search(r"\b([45]\d\d)\s+([A-Z][A-Z_]{3,})\b", err)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.search(r"\b([45]\d\d)\b", err)
    head = err.split(":", 1)[0].strip()
    if re.fullmatch(r"[A-Za-z_][\w.]{0,60}", head):
        return f"{head} {m.group(1)}" if m else head
    return m.group(1) if m else "other"


def pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def model_key(m: str) -> tuple:
    return (MODEL_ORDER.index(m) if m in MODEL_ORDER else len(MODEL_ORDER), m)


def _price(model: str, table: dict):
    if model in table:
        return table[model]
    cands = [k for k in table if model.startswith(k)]
    return table[max(cands, key=len)] if cands else None


def cache_saving_usd(model: str, cached: int) -> float:
    if not cached:
        return 0.0
    ex = _price(model, EXTRA_PRICES)
    if ex and not _price(model, PRICES):
        return cached * (ex[0] - ex[2]) / 1e6
    p = _price(model, PRICES)
    if not p:
        return 0.0
    pc = _price(model, CACHED_PRICES)
    pc = p[0] * 0.1 if pc is None else pc
    return cached * (p[0] - pc) / 1e6


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- ledger
FIELDS = ("ts", "feature", "model", "kind", "in", "out", "thinking", "cached", "latency_s", "cost_usd",
          "cost_unknown", "ok", "error", "run_id", "host")


def load_ledger(paths: list[str | Path]) -> list[dict]:
    """Read ledger JSONL from files or directories (recursive). Only whitelisted fields are kept."""
    files: list[str] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += sorted(glob.glob(str(p / "**" / "*.jsonl"), recursive=True))
        elif p.exists():
            files.append(str(p))
    rows, seen = [], set()
    for fp in dict.fromkeys(os.path.realpath(f) for f in files):  # same file reached twice counts once
        with open(fp) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(r, dict) or "model" not in r:
                    continue
                key = (r.get("ts"), r.get("host"), r.get("pid"), r.get("feature"), r.get("model"), r.get("in"), r.get("out"))
                if key in seen:  # the same row synced into two ledger dirs (Mac + FR8 copies) counts once
                    continue
                seen.add(key)
                rows.append({k: r.get(k) for k in FIELDS})
    for r in rows:
        for k in ("in", "out", "thinking", "cached"):
            r[k] = int(r.get(k) or 0)
        r["latency_s"] = float(r.get("latency_s") or 0.0)
        r["cost_usd"] = float(r.get("cost_usd") or 0.0)
        r["ts"] = float(r.get("ts") or 0.0)
        r["ok"] = r.get("ok") is not False
        r["feature"] = str(r.get("feature") or "unknown")
        r["kind"] = str(r.get("kind") or "generate")
        r["model"] = str(r.get("model") or "unknown")
    rows.sort(key=lambda r: r["ts"])
    return rows


def discover_ledgers() -> list[str]:
    """--ledger auto: every ledger JSONL we can see on this machine (dedupe makes overlaps safe).
    Looks in data/gemini/ledger, $CANARY_GEMINI_LEDGER_DIR, ~/agent-arena-data/gemini/**/_ledger (ladder/FR8 pulls) and
    sibling Canary Lab worktrees (../gemini-*/data/gemini/**). Only files under a directory named like *ledger*."""
    roots = [ROOT / "data" / "gemini", Path.home() / "agent-arena-data" / "gemini"]
    if os.environ.get("CANARY_GEMINI_LEDGER_DIR"):
        roots.append(Path(os.environ["CANARY_GEMINI_LEDGER_DIR"]))
    roots += sorted(ROOT.parent.glob("gemini-*/data/gemini"))
    files: list[str] = []
    for r in roots:
        for f in glob.glob(str(r / "**" / "*.jsonl"), recursive=True):
            if any("ledger" in part for part in Path(f).relative_to(r).parts[:-1]) or "ledger" in r.parts:
                files.append(f)
    return sorted(set(files))


def _agg(rows: list[dict]) -> dict:
    a = {"calls": len(rows), "errors": sum(not r["ok"] for r in rows),
         "in": sum(r["in"] for r in rows), "out": sum(r["out"] for r in rows),
         "thinking": sum(r["thinking"] for r in rows), "cached": sum(r["cached"] for r in rows),
         "cost_usd": round(sum(r["cost_usd"] for r in rows), 4)}
    a["tokens"] = a["in"] + a["out"] + a["thinking"]
    return a


def _bin_seconds(span: float) -> int:
    for b in (60, 120, 300, 600, 900, 1800, 3600, 7200, 21600, 86400):
        if span / b <= 150:
            return b
    return 86400


def reprice(rows: list[dict], extra: dict | None = None) -> int:
    """Fill cost_usd for cost_unknown rows whose model has a known price. Returns how many rows were repriced."""
    table = {**EXTRA_PRICES, **{k: tuple(v) for k, v in (extra or {}).items() if isinstance(v, (list, tuple)) and len(v) == 3}}
    n = 0
    for r in rows:
        if not r.get("cost_unknown"):
            continue
        p = _price(r["model"], table)
        if not p:
            continue
        usd = ((r["in"] - r["cached"]) * p[0] + r["cached"] * p[2] + (r["out"] + r["thinking"]) * p[1]) / 1e6
        r["cost_usd"] = round(usd * (0.5 if r["kind"] == "batch" else 1.0), 6)
        r["cost_unknown"], r["repriced"] = False, True
        n += 1
    return n


def summarize(rows: list[dict]) -> dict:
    """Aggregate ledger rows into the dashboard's usage summary (JSON-serialisable, no prompts)."""
    tot = _agg(rows)
    gen_lat = [r["latency_s"] for r in rows if r["ok"] and r["kind"] == "generate" and r["latency_s"] > 0]
    models = sorted({r["model"] for r in rows}, key=model_key)
    feats_c = Counter(r["feature"] for r in rows)
    features = [f for f, _ in feats_c.most_common()]
    tot.update({
        "error_rate": round(tot["errors"] / tot["calls"], 4) if rows else 0.0,
        "models": models, "features": features, "n_models": len(models), "n_features": len(features),
        "p50_latency_s": round(pct(gen_lat, 0.5), 2), "p95_latency_s": round(pct(gen_lat, 0.95), 2),
        "cost_unknown_calls": sum(bool(r.get("cost_unknown")) for r in rows),
        "repriced_calls": sum(bool(r.get("repriced")) for r in rows),
        "hosts": len({r.get("host") for r in rows if r.get("host")}),
        "run_ids": len({r.get("run_id") for r in rows if r.get("run_id")}),
        "start": rows[0]["ts"] if rows else None, "end": rows[-1]["ts"] if rows else None,
        "thinking_share": round(tot["thinking"] / max(1, tot["out"] + tot["thinking"]), 4),
    })

    by_feature = []
    for f in features:
        fr = [r for r in rows if r["feature"] == f]
        a = _agg(fr)
        a["feature"] = f
        a["models"] = sorted({r["model"] for r in fr}, key=model_key)
        a["kinds"] = sorted({r["kind"] for r in fr})
        by_feature.append(a)

    by_model = []
    for m in models:
        mr = [r for r in rows if r["model"] == m]
        a = _agg(mr)
        lat = [r["latency_s"] for r in mr if r["ok"] and r["kind"] == "generate" and r["latency_s"] > 0]
        a.update({"model": m, "thinking_share": round(a["thinking"] / max(1, a["out"] + a["thinking"]), 4),
                  "p50_latency_s": round(pct(lat, 0.5), 2), "p95_latency_s": round(pct(lat, 0.95), 2),
                  "latency_n": len(lat), "kinds": sorted({r["kind"] for r in mr})})
        by_model.append(a)

    cells = defaultdict(list)
    for r in rows:
        cells[(r["feature"], r["model"])].append(r)
    matrix = {"features": features, "models": models,
              "cells": [{"feature": f, "model": m, **_agg(v)} for (f, m), v in cells.items()]}

    kinds = Counter(r["kind"] for r in rows)
    err_types = Counter(error_type(r.get("error") or "") or "unspecified" for r in rows if not r["ok"])

    # cache + batch economics
    cache_by_f = defaultdict(lambda: {"cached": 0, "in": 0, "saved_usd": 0.0})
    for r in rows:
        c = cache_by_f[r["feature"]]
        c["cached"] += r["cached"]
        c["in"] += r["in"]
        c["saved_usd"] += cache_saving_usd(r["model"], r["cached"])
    cache = {"cached_tokens": tot["cached"], "input_tokens": tot["in"],
             "hit_share": round(tot["cached"] / max(1, tot["in"]), 4),
             "saved_usd": round(sum(c["saved_usd"] for c in cache_by_f.values()), 4),
             "by_feature": sorted([{"feature": f, **{k: (round(v, 4) if isinstance(v, float) else v)
                                                      for k, v in c.items()}}
                                   for f, c in cache_by_f.items() if c["cached"]],
                                  key=lambda x: -x["saved_usd"])}
    br = [r for r in rows if r["kind"] == "batch"]
    batch = {"calls": len(br), "tokens": sum(r["in"] + r["out"] + r["thinking"] for r in br),
             "cost_usd": round(sum(r["cost_usd"] for r in br), 4),
             "saved_usd": round(sum(r["cost_usd"] for r in br), 4)}  # ledger already halves batch cost

    # timeline: calls per bin, stacked by feature
    timeline = {"bin_s": 60, "start": None, "bins": []}
    if rows:
        t0, t1 = rows[0]["ts"], rows[-1]["ts"]
        b = _bin_seconds(max(60.0, t1 - t0))
        start = math.floor(t0 / b) * b
        n = int((t1 - start) // b) + 1
        bins = [defaultdict(int) for _ in range(n)]
        tok = [0] * n
        for r in rows:
            i = int((r["ts"] - start) // b)
            bins[i][r["feature"]] += 1
            tok[i] += r["in"] + r["out"] + r["thinking"]
        timeline = {"bin_s": b, "start": start,
                    "bins": [{"t": start + i * b, "counts": dict(c), "tokens": tok[i]} for i, c in enumerate(bins)]}

    caps = []
    if any(r["thinking"] for r in rows):
        caps.append("thinking")
    if kinds.get("generate"):
        caps.append("generate")
    if tot["cached"] or kinds.get("cache"):
        caps.append("context caching")
    for k, label in (("batch", "batch API"), ("embed", "embeddings"), ("tts", "TTS"), ("live", "Live API"),
                     ("count", "token counting")):
        if kinds.get(k):
            caps.append(label)
    if any(r["in"] >= 200_000 for r in rows):
        caps.append("long context (≥200k)")

    return {"totals": tot, "by_feature": by_feature, "by_model": by_model, "matrix": matrix,
            "kinds": dict(kinds), "errors": [{"type": t, "n": n} for t, n in err_types.most_common(8)],
            "cache": cache, "batch": batch, "timeline": timeline, "capabilities": caps,
            "max_input_tokens": max((r["in"] for r in rows), default=0)}


# ---------------------------------------------------------------- results JSON
def load_json(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
        return d if isinstance(d, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _thumb(results_dir: Path, rel: Any, budget: list[int]) -> str:
    if not isinstance(rel, str) or not rel:
        return ""
    p = (results_dir / rel).resolve()
    try:
        p.relative_to(results_dir.resolve().parent)  # stay inside results/
    except ValueError:
        return ""
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".svg") or not p.exists():
        return ""
    size = p.stat().st_size
    if size > MAX_THUMB_BYTES or size > budget[0]:
        return ""
    budget[0] -= size
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}[p.suffix[1:].lower()]
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x else None


def slim_atlas(A: dict, results_dir: Path) -> dict:
    """Normalise G3's atlas.json (or the TEAM.md minimal shape) to what the page renders."""
    budget = [4_000_000]
    modes = []
    for m in A.get("modes") or []:
        if not isinstance(m, dict):
            continue
        eps = m.get("episodes")
        quotes = []
        for q in (m.get("quotes") or [])[:3]:
            if isinstance(q, dict) and q.get("quote"):
                quotes.append({"episode": str(q.get("episode", "")), "t": q.get("t"), "quote": str(q["quote"])[:400],
                               "verified": q.get("verified", True) is not False,  # G3 drops unverifiable quotes
                               "step_verified": bool(q.get("step_verified"))})
        modes.append({"id": m.get("id"), "name": m.get("name") or m.get("id"), "description": m.get("description", ""),
                      "mechanism": m.get("mechanism", ""), "solver_would": m.get("solver_would", ""),
                      "decision": m.get("decision", ""), "regret_share": _num(m.get("regret_share")) or 0.0,
                      "episodes": len(eps) if isinstance(eps, list) else eps, "steps": m.get("steps"),
                      "quotes": quotes, "chart": m.get("chart"), "chart_src": _thumb(results_dir, m.get("chart"), budget)})
    C = A.get("corpus") or {}
    ha = A.get("human_agreement")
    if isinstance(ha, (int, float)):
        ha = {"rate": ha}
    elif isinstance(ha, dict):
        rate = ha.get("rate", ha.get("score"))
        if rate is None and ha.get("total"):
            rate = ha.get("agree", 0) / ha["total"]
        if ha.get("status") not in (None, "done"):
            rate = None
        ha = {"rate": _num(rate), "n": ha.get("n_labelled", ha.get("total")), "agree": ha.get("agree")}
    else:
        ha = None
    V = A.get("verification") or {}
    loc = A.get("localisation") or {}
    cl = A.get("clusters") or {}
    models = A.get("models") or {}
    return {"generated_at": A.get("generated_at"), "git_sha": A.get("git_sha"), "synthetic": bool(A.get("synthetic")),
            "model": A.get("model") or models.get("long_context"), "cache_model": models.get("cache"),
            "summary": A.get("summary", ""), "modes": modes,
            "corpus": {"episodes": C.get("episodes"), "tokens": C.get("tokens"), "cached_tokens": C.get("cached_tokens"),
                       "cohorts": [{k: c.get(k) for k in ("cohort", "episodes", "score_mean", "accuracy", "regret_mean")}
                                   for c in C.get("cohorts") or [] if isinstance(c, dict)]},
            "verification": {k: V.get(k) for k in ("quotes_checked", "pass_rate", "step_pass_rate", "dropped")} if V else None,
            "human_agreement": ha,
            "localisation": {"agree": loc.get("agree_within_3_steps"), "n": loc.get("n")} if loc.get("n") else None,
            "clusters": {"n": cl.get("n"), "k": cl.get("k"), "model": cl.get("model")} if cl else None}


def _plan_text(plan) -> str:
    if isinstance(plan, str):
        return plan
    if isinstance(plan, dict):
        return str(plan.get("hypothesis") or plan.get("summary") or plan.get("name") or "")
    return ""


def slim_swarm(S: dict) -> dict:
    """Normalise G4's swarm.json (or the TEAM.md minimal shape) to what the page renders."""
    at = []
    for a in S.get("attempts") or []:
        if not isinstance(a, dict):
            continue
        plan = a.get("plan")
        at.append({"id": a.get("id"), "persona": str(a.get("persona", "")), "plan": _plan_text(plan)[:300],
                   "target": plan.get("target_invariant") if isinstance(plan, dict) else None,
                   "tier": a.get("tier"), "score": _num(a.get("score")), "correct": a.get("correct"),
                   "ledger_verified": bool(a.get("ledger_verified")), "exploit": bool(a.get("exploit")),
                   "candidate": bool(a.get("score_candidate")), "solver_score": _num(a.get("solver_score")),
                   "tools": a.get("n_tool_calls"), "channel": a.get("channel"), "error": bool(a.get("error"))})
    scored = [a for a in at if a["score"] is not None]
    tiers = {}
    for a in scored:
        tiers[a["tier"]] = tiers.get(a["tier"], 0) + 1
    main_tier = max(tiers, key=tiers.get) if tiers else S.get("tier")
    pt = (S.get("per_tier") or {}).get(main_tier) or {}
    best = S.get("best_non_solver")
    best = best.get("score") if isinstance(best, dict) else best
    if best is None:
        best = pt.get("best_non_solver")
    if best is None and scored:
        best = max(a["score"] for a in scored)
    solver = S.get("solver_score", S.get("solver"))
    if solver is None:
        solver = pt.get("solver_mean_paired", pt.get("solver_mean_ref"))
    counts = S.get("counts") or {}
    tests = S.get("tests_written")
    found = ROOT / "tests" / "test_gemini_lab_swarm_found.py"
    if tests is None and found.exists():
        tests = len(re.findall(r"^def test_", found.read_text(), re.M))
    ms = S.get("models")
    model = S.get("model") or (", ".join(map(str, ms)) if isinstance(ms, list) else ms if isinstance(ms, str) else None)
    findings = [{"title": str(f.get("title") or f.get("name") or ""), "verified": bool(f.get("verified")),
                 "test": str(f.get("test") or "")} for f in S.get("findings") or [] if isinstance(f, dict)]
    return {"generated_at": S.get("generated_at"), "git_sha": S.get("git_sha"), "synthetic": bool(S.get("synthetic")),
            "model": model,
            "mode": S.get("mode"), "tier": main_tier, "attempts": at, "best_non_solver": _num(best),
            "solver_score": _num(solver), "tests_written": tests, "findings": findings,
            "exploits": counts.get("exploits", sum(1 for a in at if a["exploit"] and a["ledger_verified"])),
            "candidates": counts.get("score_candidates", sum(1 for a in at if a["candidate"])),
            "violations": counts.get("invariant_violations"), "violation_kinds": counts.get("violation_kinds") or {},
            "tool_calls": counts.get("tool_calls", sum(a["tools"] or 0 for a in at)),
            "errors": counts.get("errors", sum(1 for a in at if a["error"]))}


def load_results(results_dir: Path) -> dict:
    results_dir = Path(results_dir)
    out: dict[str, Any] = {}
    ladder = load_json(results_dir / "ladder.json")
    if ladder:
        ladder = {k: ladder.get(k) for k in ("generated_at", "git_sha", "synthetic", "episodes", "rows", "cells",
                                              "reference", "tags", "solver", "ledger")}
        if isinstance(ladder.get("tags"), dict):
            ladder["tags"] = {k: ladder["tags"].get(k) for k in ("pooled", "pooled_common_models")}
            for v in (ladder["tags"].get("pooled") or {}).values():  # drop the per-episode "worst" lists
                for d in (v.get("tags") or {}).values():
                    if isinstance(d, dict):
                        d.pop("worst", None)
        for r in ladder.get("rows") or []:
            if isinstance(r, dict):
                r.pop("seeds", None), r.pop("run_ids", None)
    out["ladder"] = redact(ladder) if ladder else None
    atlas = load_json(results_dir / "atlas.json")
    out["atlas"] = redact(slim_atlas(atlas, results_dir)) if atlas else None
    swarm = load_json(results_dir / "swarm.json")
    out["swarm"] = redact(slim_swarm(swarm)) if swarm else None
    gb = load_json(results_dir / "gateway_bench.json")
    if gb and isinstance(gb.get("rows"), list):
        out["gateway_bench"] = redact({
            "generated_at": gb.get("generated_at"), "git_sha": gb.get("git_sha"), "calls": gb.get("calls"),
            "spend_usd": gb.get("spend_usd"), "setup": str(gb.get("setup", ""))[:300],
            "rows": [{"model": r.get("model"), "conc": r.get("conc"), "rpm": _num(r.get("rpm")), "p50_s": _num(r.get("p50_s")),
                      "p95_s": _num(r.get("p95_s")), "ok": r.get("ok"),
                      "errors": sum(v for v in (r.get("errors") or {}).values() if isinstance(v, (int, float))),
                      "retries": r.get("gw_retries")} for r in gb["rows"] if isinstance(r, dict)]})
    else:
        out["gateway_bench"] = None
    figs = {}
    budget = [3_000_000]
    for name in ("ladder.png",):
        src = _thumb(results_dir, name, budget)
        if src:
            figs[name] = src
    out["figures"] = figs
    return out


# ---------------------------------------------------------------- render
def build_payload(rows: list[dict], results_dir: Path, sources: list[str]) -> dict:
    return {"usage": summarize(rows), "results": load_results(results_dir),
            "meta": {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                     "git_sha": git_sha(), "ledger_rows": len(rows), "sources": sources}}


def render_html(payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":"), default=str)
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    return HTML.replace("/*__CSS__*/", CSS).replace("/*__JS__*/", JS).replace("__DATA__", data)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", nargs="*", default=None,
                    help="ledger dirs/files (default data/gemini/ledger); 'auto' = every ledger found on this machine")
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--out", default=str(DEFAULT_RESULTS / "dashboard.html"))
    ap.add_argument("--json", action="store_true", help="print the aggregated usage summary and exit")
    a = ap.parse_args(argv)
    sources = a.ledger or [str(DEFAULT_LEDGER)]
    if sources == ["auto"]:
        sources = discover_ledgers()
    rows = load_ledger(sources)
    lad = load_json(Path(a.results) / "ladder.json") or {}
    reprice(rows, lad.get("prices_usd_per_1m") if isinstance(lad.get("prices_usd_per_1m"), dict) else None)
    if a.json:
        s = summarize(rows)
        s.pop("timeline", None)
        s.pop("matrix", None)
        json.dump(s, sys.stdout, indent=1)
        print()
        return 0
    rel = []
    for s in (sources if len(sources) <= 6 else []):
        try:
            rel.append(str(Path(s).resolve().relative_to(ROOT)))
        except ValueError:
            rel.append(Path(s).name)
    if len(sources) > 6:
        rel = [f"{len(sources)} ledger files (--ledger auto)"]
    html = render_html(build_payload(rows, Path(a.results), rel))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({len(html) / 1024:.0f} KB, {len(rows)} ledger rows)")
    return 0


# ================================================================ page
HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Canary Lab Dashboard</title>
<style>/*__CSS__*/</style>
</head>
<body>
<header class="top">
  <div class="brand">
    <svg class="bird" viewBox="0 0 32 32" aria-hidden="true"><path d="M6 20c0-7 5-12 12-12 3 0 5 1 6 3l4 1-4 2c0 6-5 10-11 10H8l-3 3 1-5z" fill="var(--canary)"/><circle cx="21" cy="12" r="1.4" fill="var(--ink)"/></svg>
    <div>
      <div class="eyebrow">Canary Lab · Gemini API</div>
      <h1>Gemini builds, plays, attacks and explains its own benchmark</h1>
    </div>
  </div>
  <div class="topmeta">
    <span id="meta-line"></span>
    <button id="theme" type="button" aria-label="Toggle colour theme">Theme: auto</button>
  </div>
</header>
<main id="app">
  <section id="p-headline" class="panel" data-panel="headline"></section>
  <section id="p-usage" class="panel" data-panel="usage"></section>
  <section id="p-ladder" class="panel" data-panel="ladder"></section>
  <section id="p-atlas" class="panel" data-panel="atlas"></section>
  <section id="p-swarm" class="panel" data-panel="swarm"></section>
</main>
<footer class="foot" id="foot"></footer>
<div id="tip" role="tooltip" hidden></div>
<script id="data" type="application/json">__DATA__</script>
<script>/*__JS__*/</script>
</body>
</html>
"""

CSS = r"""
:root {
  color-scheme: light;
  --page: #f6f5f0; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10); --wash: rgba(11,11,11,0.035);
  --canary: #f2b705;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4; --s6: #008300; --s7: #6250d6; --s8: #e34948;
  --other: #b5b3ab;
  --good: #0ca30c; --warn: #fab219; --serious: #ec835a; --crit: #d03b3b; --goodtext: #006300;
  --q100: #cde2fb; --q700: #0d366b; --mid: #f0efec;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10); --wash: rgba(255,255,255,0.05);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #0ca30c; --s7: #9085e9; --s8: #e66767;
    --other: #5f5e59; --goodtext: #0ca30c; --mid: #383835;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10); --wash: rgba(255,255,255,0.05);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #0ca30c; --s7: #9085e9; --s8: #e66767;
  --other: #5f5e59; --goodtext: #0ca30c; --mid: #383835;
}
* { box-sizing: border-box; }
html { background: var(--page); }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; -webkit-font-smoothing: antialiased; }
.top, main, .foot { max-width: 1280px; margin: 0 auto; padding: 0 24px; }
.top { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding-top: 28px; padding-bottom: 18px;
  border-bottom: 1px solid var(--grid); flex-wrap: wrap; }
.brand { display: flex; gap: 14px; align-items: center; }
.bird { width: 44px; height: 44px; flex: none; }
.eyebrow, .kicker { font: 600 11px/1.2 ui-monospace, "SF Mono", Menlo, monospace; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
h1 { margin: 4px 0 0; font: 600 26px/1.15 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; letter-spacing: -.01em; max-width: 30ch; }
.topmeta { display: flex; gap: 12px; align-items: center; color: var(--muted); font: 12px/1.4 ui-monospace, "SF Mono", Menlo, monospace; }
button, .seg button { font: 500 12px/1 system-ui, -apple-system, sans-serif; color: var(--ink2); background: var(--surface);
  border: 1px solid var(--ring); border-radius: 999px; padding: 7px 12px; cursor: pointer; }
button:hover { background: var(--wash); }
button:focus-visible, .cell:focus-visible, [tabindex]:focus-visible { outline: 2px solid var(--s1); outline-offset: 2px; }
.seg { display: inline-flex; gap: 0; border: 1px solid var(--ring); border-radius: 999px; padding: 2px; background: var(--surface); }
.seg button { border: 0; border-radius: 999px; padding: 6px 12px; background: transparent; }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--surface); }
.panel { padding: 36px 0 8px; }
.phead { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
.phead h2 { margin: 2px 0 0; font: 600 22px/1.2 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; }
.phead .lede { margin: 4px 0 0; color: var(--ink2); max-width: 78ch; }
.kicker b { color: var(--ink); font-weight: 700; margin-right: 6px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(12, minmax(0, 1fr)); }
.card { background: var(--surface); border: 1px solid var(--ring); border-radius: 12px; padding: 18px 20px; min-width: 0; }
.card h3 { margin: 0; font: 600 14px/1.3 system-ui, -apple-system, sans-serif; }
.card .sub { margin: 2px 0 12px; color: var(--muted); font-size: 12px; }
.c3 { grid-column: span 3; } .c4 { grid-column: span 4; } .c5 { grid-column: span 5; } .c6 { grid-column: span 6; }
.c7 { grid-column: span 7; } .c8 { grid-column: span 8; } .c12 { grid-column: span 12; }
@media (max-width: 980px) { .c3, .c4, .c5, .c6, .c7, .c8 { grid-column: span 12; } }
.hero { display: grid; grid-template-columns: minmax(260px, 1.1fr) 3fr; gap: 16px; }
@media (max-width: 980px) { .hero { grid-template-columns: 1fr; } }
.heroNum { font: 650 64px/1 system-ui, -apple-system, sans-serif; letter-spacing: -.03em; margin: 10px 0 6px; }
.heroCard p { margin: 0; color: var(--ink2); }
.tiles { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1px; background: var(--ring);
  border: 1px solid var(--ring); border-radius: 12px; overflow: hidden; }
@media (max-width: 760px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.tile { background: var(--surface); padding: 14px 16px; min-width: 0; }
.tile .lab { color: var(--muted); font-size: 12px; }
.tile .val { font: 600 22px/1.2 system-ui, -apple-system, sans-serif; margin-top: 4px; letter-spacing: -.01em; }
.tile .note { color: var(--muted); font-size: 11.5px; line-height: 1.35; margin-top: 3px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.caps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.chip { font: 500 11.5px/1 ui-monospace, "SF Mono", Menlo, monospace; padding: 6px 9px; border-radius: 999px;
  border: 1px solid var(--ring); color: var(--ink2); background: var(--wash); }
svg.chart { display: block; width: 100%; height: auto; overflow: visible; }
svg text { font: 11px system-ui, -apple-system, sans-serif; fill: var(--muted); }
svg text.ink { fill: var(--ink); } svg text.ink2 { fill: var(--ink2); }
svg text.halo { paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }
svg .gridline { stroke: var(--grid); stroke-width: 1; shape-rendering: crispEdges; }
svg .baseline { stroke: var(--axis); stroke-width: 1; shape-rendering: crispEdges; }
svg .hit { fill: transparent; cursor: default; }
svg .mark:hover, svg g.hov:hover .mark { filter: brightness(1.12); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0 0 10px; color: var(--ink2); font-size: 12px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.legend i.line { height: 2px; width: 14px; border-radius: 1px; }
.matrix { width: 100%; border-collapse: separate; border-spacing: 2px; font-size: 12px; table-layout: fixed; }
.matrix th { font-weight: 500; color: var(--ink2); text-align: left; padding: 4px 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.matrix thead th { color: var(--muted); font-size: 11px; text-align: center; }
.matrix td { height: 34px; text-align: center; border-radius: 4px; font-variant-numeric: tabular-nums; font-weight: 600; }
.matrix td.empty { background: var(--wash); color: var(--muted); font-weight: 400; }
.matrix td.cell { cursor: default; }
.scale { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--muted); margin-top: 8px; }
.scale .bar { flex: 0 0 140px; height: 8px; border-radius: 4px; }
.pending { display: grid; place-items: center; text-align: center; min-height: 180px; border: 1px dashed var(--axis);
  border-radius: 12px; color: var(--muted); background: repeating-linear-gradient(135deg, transparent 0 10px, var(--wash) 10px 11px); }
.pending b { display: block; color: var(--ink2); font: 600 15px/1.4 system-ui, sans-serif; margin-bottom: 4px; }
.pending code { font: 12px ui-monospace, Menlo, monospace; }
.synth { display: inline-block; margin-left: 8px; font: 600 10.5px/1 ui-monospace, Menlo, monospace; letter-spacing: .08em;
  text-transform: uppercase; color: #0b0b0b; background: var(--warn); padding: 4px 7px; border-radius: 4px; vertical-align: middle; }
.modes { display: grid; gap: 12px; }
.mode { display: grid; grid-template-columns: 34px minmax(0, 1fr) 180px; gap: 16px; align-items: start; padding: 16px 0; border-top: 1px solid var(--grid); }
.mode:first-child { border-top: 0; padding-top: 4px; }
@media (max-width: 760px) { .mode { grid-template-columns: 28px 1fr; } .mode .thumb { grid-column: 2; } }
.rank { font: 600 22px/1 "Iowan Old Style", Palatino, Georgia, serif; color: var(--muted); }
.mode h4 { margin: 0; font-size: 15px; }
.mode .desc { margin: 2px 0 8px; color: var(--ink2); }
.mode .desc b { color: var(--ink); font-weight: 600; }
p.summary { margin: 0; color: var(--ink); max-width: 100ch; font: 15px/1.55 "Iowan Old Style", Palatino, Georgia, serif; }
.mode .facts { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin-bottom: 8px; }
.mode .facts b { color: var(--ink); font-weight: 600; }
.share { height: 8px; border-radius: 4px; background: var(--q100); overflow: hidden; margin: 2px 0 10px; max-width: 360px; }
.share > div { height: 100%; background: var(--s1); border-radius: 4px; }
blockquote { margin: 6px 0; padding: 8px 12px; border-left: 2px solid var(--axis); background: var(--wash); border-radius: 0 6px 6px 0;
  font: italic 13.5px/1.45 "Iowan Old Style", Palatino, Georgia, serif; color: var(--ink); }
blockquote .src { display: block; font: 11px/1.4 ui-monospace, Menlo, monospace; color: var(--muted); font-style: normal; margin-top: 4px; }
.badge { display: inline-flex; align-items: center; gap: 4px; font: 600 10.5px/1 ui-monospace, Menlo, monospace; padding: 3px 6px;
  border-radius: 4px; margin-left: 6px; vertical-align: 1px; }
.badge.ok { color: var(--goodtext); background: color-mix(in srgb, var(--good) 14%, transparent); }
.badge.no { color: var(--crit); background: color-mix(in srgb, var(--crit) 12%, transparent); }
.thumb img { width: 100%; border-radius: 8px; border: 1px solid var(--ring); background: #fff; display: block; }
.thumb .ph { aspect-ratio: 4/3; border-radius: 8px; border: 1px dashed var(--axis); display: grid; place-items: center; color: var(--muted); font-size: 11px; }
table.list { width: 100%; border-collapse: collapse; font-size: 12.5px; }
table.list th { text-align: left; font-weight: 500; color: var(--muted); font-size: 11.5px; padding: 6px 8px; border-bottom: 1px solid var(--axis); }
table.list td { padding: 7px 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }
table.list td.num, table.list th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
table.list td.plan { color: var(--ink2); max-width: 520px; }
table.list td.nw, .badge { white-space: nowrap; }
details.tbl { margin-top: 10px; } details.tbl summary { cursor: pointer; color: var(--muted); font-size: 12px; }
.foot { color: var(--muted); font-size: 12px; padding-top: 28px; padding-bottom: 40px; border-top: 1px solid var(--grid); margin-top: 32px; }
.foot code { font: 11.5px ui-monospace, Menlo, monospace; }
#tip { position: fixed; z-index: 10; pointer-events: none; background: var(--surface); color: var(--ink); border: 1px solid var(--ring);
  box-shadow: 0 6px 24px rgba(0,0,0,.14); border-radius: 8px; padding: 8px 10px; font-size: 12px; min-width: 120px; max-width: 300px; }
#tip .t { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
#tip .r { display: flex; align-items: center; gap: 8px; line-height: 1.6; }
#tip .r i { width: 12px; height: 2px; border-radius: 1px; flex: none; }
#tip .r b { font-variant-numeric: tabular-nums; }
#tip .r span { color: var(--ink2); }
@media (max-width: 640px) {
  .top, main, .foot { padding-left: 16px; padding-right: 16px; }
  h1 { font-size: 21px; } .phead h2 { font-size: 19px; } .heroNum { font-size: 48px; }
  .topmeta { flex-wrap: wrap; } .card { padding: 14px; }
  .matrix { font-size: 10.5px; } .matrix th { padding: 2px; }
  .card:has(.matrix) { overflow-x: auto; }
}
.grid > *, .hero > * { min-width: 0; }
body.focus .panel { display: none; } body.focus .panel.on { display: block; padding-top: 18px; }
body.focus .foot { display: none; }
@media (prefers-reduced-motion: no-preference) {
  body:not(.focus) .panel { animation: rise .5s ease both; } body:not(.focus) .panel:nth-child(2) { animation-delay: .05s; } body:not(.focus) .panel:nth-child(3) { animation-delay: .1s; }
  @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
}
@media print { .panel { animation: none; } #theme { display: none; } }
"""

JS = r"""
(function () {
'use strict';
const D = JSON.parse(document.getElementById('data').textContent);
const U = D.usage, R = D.results || {};
const NS = 'http://www.w3.org/2000/svg';
const qs = new URLSearchParams(location.search);

// ---------- theme
const root = document.documentElement;
const themeBtn = document.getElementById('theme');
let theme = qs.get('theme') || (function () { try { return localStorage.getItem('canary-lab-theme'); } catch (e) { return null; } })() || 'auto';
function applyTheme() {
  if (theme === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', theme);
  themeBtn.textContent = 'Theme: ' + theme;
}
themeBtn.addEventListener('click', () => {
  theme = theme === 'auto' ? 'light' : theme === 'light' ? 'dark' : 'auto';
  try { localStorage.setItem('canary-lab-theme', theme); } catch (e) {}
  applyTheme(); renderAll();
});
applyTheme();

// ---------- format
const nf = new Intl.NumberFormat('en-US');
function compact(n) {
  n = +n || 0; const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, '') + 'B';
  if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
  if (a >= 1e4) return (n / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, '') + 'K';
  return nf.format(Math.round(n));
}
function usd(n) { n = +n || 0; return n >= 100 ? '$' + nf.format(Math.round(n)) : n >= 1 ? '$' + n.toFixed(2) : n > 0 ? '$' + n.toFixed(3) : '$0'; }
function pctf(x, d) { return (x * 100).toFixed(d == null ? 0 : d) + '%'; }
function secs(s) { return s >= 60 ? (s / 60).toFixed(1) + ' min' : s >= 10 ? s.toFixed(0) + ' s' : s.toFixed(1) + ' s'; }
function short(m) { return String(m).replace(/^gemini-/, ''); }
function hhmm(t) { const d = new Date(t * 1000); return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function day(t) { const d = new Date(t * 1000); return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' }); }

// ---------- DOM helpers (labels always via textContent)
function h(tag, attrs, kids) {
  const e = document.createElement(tag);
  for (const k in (attrs || {})) { if (k === 'class') e.className = attrs[k]; else if (k === 'text') e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); }
  (kids || []).forEach(c => c != null && e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
  return e;
}
function s(tag, attrs, kids) {
  const e = document.createElementNS(NS, tag);
  for (const k in (attrs || {})) { if (k === 'text') e.textContent = attrs[k]; else e.setAttribute(k, attrs[k]); }
  (kids || []).forEach(c => c && e.appendChild(c));
  return e;
}
function css(v) { return getComputedStyle(root).getPropertyValue(v).trim(); }

// ---------- tooltip
const tip = document.getElementById('tip');
function showTip(ev, title, rows) {
  tip.replaceChildren(h('div', { class: 't', text: title }));
  rows.forEach(r => {
    const line = h('div', { class: 'r' });
    if (r.c) { const i = h('i'); i.style.background = r.c; line.appendChild(i); }
    line.appendChild(h('b', { text: r.v })); line.appendChild(h('span', { text: r.l || '' }));
    tip.appendChild(line);
  });
  tip.hidden = false;
  const bx = ev.clientX != null ? ev.clientX : ev.target.getBoundingClientRect().right;
  const by = ev.clientY != null ? ev.clientY : ev.target.getBoundingClientRect().top;
  const w = tip.offsetWidth, ht = tip.offsetHeight;
  let x = bx + 14, y = by + 14;
  if (x + w > innerWidth - 8) x = bx - w - 14;
  if (y + ht > innerHeight - 8) y = by - ht - 14;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
function hideTip() { tip.hidden = true; }
function bindTip(node, fn) {
  const on = ev => { const r = fn(ev); if (r) showTip(ev, r[0], r[1]); };
  node.addEventListener('pointermove', on); node.addEventListener('pointerleave', hideTip);
  node.addEventListener('focus', on); node.addEventListener('blur', hideTip);
}

// ---------- colour by entity (fixed slots, never by rank)
const FEATURE_SLOT = { ladder: 1, atlas: 2, swarm: 3, forge: 5, narrate: 6, world: 7, commentator: 8 };
const MODEL_SLOT = { 'gemini-3.1-flash-lite': 1, 'gemini-3.5-flash': 2, 'gemini-3.8-flash': 3,
  'gemini-4-hydrogen': 4, 'gemini-4-argon': 5, 'gemini-4-carbon': 6 };
const FEATURE_SLOT_PREFIX = { gateway: 4 };
function fslot(f) { return FEATURE_SLOT[f] || FEATURE_SLOT_PREFIX[String(f).split(/[-_]/)[0]] || 0; }
function featColor(f) { return fslot(f) ? css('--s' + fslot(f)) : css('--other'); }
function modelColor(m) { return MODEL_SLOT[m] ? css('--s' + MODEL_SLOT[m]) : css('--other'); }

// sequential blue ramp (palette steps 100..700); light end recedes toward the surface
const RAMP = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
function rampIdx(t) { return Math.max(0, Math.min(RAMP.length - 1, Math.round(t * (RAMP.length - 1)))); }
function cellStyle(td, t) { const i = rampIdx(t); td.style.background = RAMP[i]; td.style.color = i >= 7 ? '#ffffff' : '#0b0b0b'; }
// diverging blue <-> red around a neutral grey midpoint (palette diverging pair); equal steps per arm
const DIV_POS = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
const DIV_NEG = ['#fbd9d6', '#f6b3ad', '#ee8a82', '#e3605a', '#d03b3b', '#a82d2d', '#7d2121'];
function divStyle(td, v, neg, pos) {
  if (Math.abs(v) < 0.02) { td.style.background = css('--mid'); td.style.color = css('--ink'); return; }
  const arm = v > 0 ? DIV_POS : DIV_NEG, t = Math.min(1, Math.abs(v) / (v > 0 ? pos : neg));
  const i = Math.max(0, Math.min(arm.length - 1, Math.ceil(t * arm.length) - 1));
  td.style.background = arm[i]; td.style.color = i >= 3 ? '#ffffff' : '#0b0b0b';
}

// ---------- scaffolding
function panelHead(sec, num, title, lede, right) {
  const left = h('div', {}, [h('div', { class: 'kicker' }, [h('b', { text: num }), title.kicker]), h('h2', { text: title.h })]);
  if (lede) left.appendChild(h('p', { class: 'lede', text: lede }));
  sec.appendChild(h('div', { class: 'phead' }, [left, right || null]));
}
function card(cls, title, sub, kids) {
  const c = h('div', { class: 'card ' + cls });
  if (title) c.appendChild(h('h3', { text: title }));
  if (sub) c.appendChild(h('p', { class: 'sub', text: sub }));
  (kids || []).forEach(k => k && c.appendChild(k));
  return c;
}
function pending(what, cmd) {
  return h('div', { class: 'pending' }, [h('div', {}, [h('b', { text: what + ' pending' }),
    h('div', { text: 'This panel fills in when the results file exists.' }), cmd ? h('code', { text: cmd }) : null])]);
}
function legend(items, line) {
  return h('div', { class: 'legend' }, items.map(it => { const i = h('i', { class: line ? 'line' : '' }); i.style.background = it.c; return h('span', {}, [i, it.l]); }));
}
function synthBadge(obj) { return obj && obj.synthetic ? h('span', { class: 'synth', text: 'synthetic fixture' }) : null; }

// ---------- generic charts
function niceTicks(max, n) {
  if (max <= 0) return [0, 1];
  const raw = max / (n || 4), mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(st => st >= raw);
  const out = []; for (let v = 0; v <= max + step * 0.001; v += step) out.push(+v.toFixed(10));
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
  return out;
}

// horizontal bars, single series (slot 1) unless colorFn given
function hbars(items, opt) {
  const W = opt.W || 560, rowH = 26, labW = opt.labW || 120, valW = 70, top = 4;
  const H = top + items.length * rowH + 4;
  const max = opt.max || Math.max(1e-9, ...items.map(d => d.v));
  const x = v => (W - labW - valW) * Math.max(0, v) / max;
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': opt.aria || '' });
  svg.appendChild(s('line', { class: 'baseline', x1: labW, x2: labW, y1: 0, y2: H }));
  items.forEach((d, i) => {
    const y = top + i * rowH, bh = Math.min(16, rowH - 8), w = Math.max(d.v > 0 ? 2 : 0, x(d.v));
    const g = s('g', { class: 'hov', tabindex: 0 });
    g.appendChild(s('rect', { class: 'hit', x: 0, y: y, width: W, height: rowH }));
    g.appendChild(s('text', { x: labW - 8, y: y + rowH / 2 + 4, 'text-anchor': 'end', class: 'ink2', text: d.l }));
    const r = Math.min(4, w / 2);
    g.appendChild(s('path', { class: 'mark', fill: d.c || css('--s1'),
      d: `M${labW},${y + (rowH - bh) / 2} h${w - r} a${r},${r} 0 0 1 ${r},${r} v${bh - 2 * r} a${r},${r} 0 0 1 ${-r},${r} h${-(w - r)} z` }));
    g.appendChild(s('text', { x: labW + w + 6, y: y + rowH / 2 + 4, class: 'ink', text: d.vl }));
    bindTip(g, () => [d.l, d.tip || [{ v: d.vl, l: opt.unit || '' }]]);
    svg.appendChild(g);
  });
  return svg;
}

// stacked columns over time (calls per bin, by feature)
function timelineChart() {
  const T = U.timeline; if (!T.bins.length) return h('p', { class: 'sub', text: 'No ledger rows yet.' });
  // one series per colour slot: features sharing a prefix slot (gateway-bench, gateway-smoke) fold into 'gateway'
  const grp = f => FEATURE_SLOT[f] ? f : FEATURE_SLOT_PREFIX[String(f).split(/[-_]/)[0]] ? String(f).split(/[-_]/)[0] : 'other';
  const series = [...new Set(U.totals.features.map(grp))].filter(k => k !== 'other').sort((a, b) => fslot(a) - fslot(b));
  const hasOther = U.totals.features.some(f => grp(f) === 'other');
  const keys = hasOther ? series.concat(['other']) : series;
  const W = 780, H = 240, L = 40, Rr = 8, Tp = 8, B = 26;
  const vals = T.bins.map(b => { const o = {}; let tot = 0; keys.forEach(k => o[k] = 0);
    for (const f in b.counts) { const k = grp(f); o[k] += b.counts[f]; tot += b.counts[f]; } o._t = tot; return o; });
  const max = Math.max(1, ...vals.map(v => v._t)); const ticks = niceTicks(max, 4); const ymax = ticks[ticks.length - 1];
  const n = T.bins.length, slot = (W - L - Rr) / n, bw = Math.max(1, Math.min(24, slot - 2));
  const y = v => Tp + (H - Tp - B) * (1 - v / ymax);
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Gemini calls over time by feature' });
  ticks.forEach(t => { svg.appendChild(s('line', { class: 'gridline', x1: L, x2: W - Rr, y1: y(t), y2: y(t) }));
    svg.appendChild(s('text', { x: L - 6, y: y(t) + 4, 'text-anchor': 'end', text: compact(t) })); });
  const col = k => k === 'other' ? css('--other') : featColor(k);
  vals.forEach((v, i) => {
    const x0 = L + i * slot + (slot - bw) / 2; let acc = 0;
    const g = s('g', { class: 'hov' });
    g.appendChild(s('rect', { class: 'hit', x: L + i * slot, y: Tp, width: slot, height: H - Tp - B }));
    keys.forEach(k => { if (!v[k]) return; const y1 = y(acc), y2 = y(acc + v[k]); acc += v[k];
      g.appendChild(s('rect', { class: 'mark', x: x0, y: y2, width: bw, height: Math.max(0.5, y1 - y2 - (bw > 3 ? 1 : 0)), fill: col(k) })); });
    bindTip(g, () => [hhmm(T.bins[i].t) + ' · ' + secs(T.bin_s) + ' bin', [{ v: nf.format(v._t), l: 'calls' }]
      .concat(keys.filter(k => v[k]).map(k => ({ c: col(k), v: nf.format(v[k]), l: k })))
      .concat([{ v: compact(T.bins[i].tokens), l: 'tokens' }])]);
    svg.appendChild(g);
  });
  svg.appendChild(s('line', { class: 'baseline', x1: L, x2: W - Rr, y1: y(0), y2: y(0) }));
  const every = Math.max(1, Math.ceil(n / 8));
  T.bins.forEach((b, i) => { if (i % every) return; svg.appendChild(s('text', { x: L + i * slot + slot / 2, y: H - 8, 'text-anchor': 'middle', text: hhmm(b.t) })); });
  return h('div', {}, [legend(keys.map(k => ({ c: col(k), l: k }))), svg]);
}

// heat matrix (HTML table) — rows × cols, value fn, sequential blue
function heatMatrix(rows, cols, get, fmt, opt) {
  opt = opt || {};
  const vals = []; rows.forEach(r => cols.forEach(c => { const v = get(r, c); if (v != null) vals.push(v); }));
  const lo = opt.min != null ? opt.min : 0, hi = opt.max != null ? opt.max : Math.max(1e-9, ...vals);
  const scale = opt.log ? (v => Math.log1p(Math.max(0, v)) / Math.log1p(hi)) : (v => (v - lo) / (hi - lo || 1));
  const t = h('table', { class: 'matrix' });
  const colg = h('colgroup', {}, [h('col', { style: 'width:' + (opt.labW || 120) + 'px' })].concat(cols.map(() => h('col'))));
  t.appendChild(colg);
  t.appendChild(h('thead', {}, [h('tr', {}, [h('th', { text: opt.corner || '' })].concat(cols.map(c => h('th', { text: opt.colLabel ? opt.colLabel(c) : c }))))]));
  const tb = h('tbody');
  rows.forEach(r => {
    const tr = h('tr', {}, [h('th', { text: opt.rowLabel ? opt.rowLabel(r) : r, title: r })]);
    cols.forEach(c => {
      const v = get(r, c);
      if (v == null) { tr.appendChild(h('td', { class: 'empty', text: '·' })); return; }
      const td = h('td', { class: 'cell', tabindex: 0, text: fmt(v) });
      if (opt.diverging) divStyle(td, v, opt.diverging[0], opt.diverging[1]); else cellStyle(td, Math.max(0, Math.min(1, scale(v))));
      bindTip(td, () => [(opt.rowLabel ? opt.rowLabel(r) : r) + ' × ' + (opt.colLabel ? opt.colLabel(c) : c), opt.tip ? opt.tip(r, c, v) : [{ v: fmt(v), l: '' }]]);
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  const sc = h('div', { class: 'scale' }, [h('span', { text: opt.loLabel || fmt(lo) }), h('div', { class: 'bar' }), h('span', { text: opt.hiLabel || fmt(hi) })]);
  sc.querySelector('.bar').style.background = 'linear-gradient(90deg,' + (opt.diverging ? DIV_NEG.slice().reverse().concat([css('--mid')], DIV_POS) : RAMP).join(',') + ')';
  return h('div', {}, [t, sc]);
}

// xy chart: lines (per series) + dots; optional log x
function xyChart(series, opt) {
  const W = opt.W || 620, H = opt.H || 300, L = 48, Rr = opt.R || 16, Tp = 12, B = 34;
  const pts = series.flatMap(sr => sr.pts);
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const logx = !!opt.logx;
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  if (logx) { x0 = Math.pow(10, Math.floor(Math.log10(Math.max(x0, opt.xfloor || 1)))); x1 = Math.pow(10, Math.ceil(Math.log10(Math.max(x1, x0 * 10)))); }
  else { x0 = Math.min(0, x0); const tk = niceTicks(x1, 5); x1 = tk[tk.length - 1]; }
  const y0 = opt.ymin != null ? opt.ymin : Math.min(0, ...ys), y1 = opt.ymax != null ? opt.ymax : Math.max(...ys) * 1.08;
  const X = v => L + (W - L - Rr) * (logx ? (Math.log10(Math.max(v, x0)) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) : (v - x0) / (x1 - x0 || 1));
  const Y = v => Tp + (H - Tp - B) * (1 - (v - y0) / (y1 - y0 || 1));
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': opt.aria || '' });
  const ystep = (y1 - y0) > 2.2 ? 0.5 : 0.25, yt = [];
  for (let v = Math.ceil(y0 / ystep) * ystep; v <= y1 + 1e-9; v += ystep) yt.push(+v.toFixed(4));
  (opt.yticks && !(opt.pctAuto && (y1 - y0) > 1.3) ? opt.yticks : yt).forEach(t => { if (t < y0 || t > y1) return;
    svg.appendChild(s('line', { class: 'gridline', x1: L, x2: W - Rr, y1: Y(t), y2: Y(t) }));
    svg.appendChild(s('text', { x: L - 6, y: Y(t) + 4, 'text-anchor': 'end', text: opt.yfmt ? opt.yfmt(t) : t })); });
  const xt = []; if (opt.xticks) { opt.xticks.forEach(v => xt.push(v)); } else if (logx) { const dec = Math.round(Math.log10(x1 / x0)); for (let v = x0; v <= x1 * 1.0001; v *= 10) { xt.push(v); if (dec <= 2 && v * 2 < x1) xt.push(v * 2, v * 5); } } else niceTicks(x1, 5).forEach(v => xt.push(v));
  xt.forEach(t => svg.appendChild(s('text', { x: X(t), y: H - 12, 'text-anchor': 'middle', text: opt.xfmt ? opt.xfmt(t) : compact(t) })));
  svg.appendChild(s('line', { class: 'baseline', x1: L, x2: W - Rr, y1: Y(Math.max(y0, 0)), y2: Y(Math.max(y0, 0)) }));
  if (opt.xlabel) svg.appendChild(s('text', { x: W - Rr, y: H - 0, 'text-anchor': 'end', text: opt.xlabel }));
  (opt.refs || []).forEach(r => { if (r.y < y0 || r.y > y1) return; svg.appendChild(s('line', { x1: L, x2: W - Rr, y1: Y(r.y), y2: Y(r.y), stroke: css('--axis'), 'stroke-width': 1 }));
    svg.appendChild(s('text', { x: L + 6, y: Y(r.y) + 13, class: 'halo', text: r.l + ' ' + pctf(r.y) })); });
  if (opt.ref) { svg.appendChild(s('line', { x1: L, x2: W - Rr, y1: Y(opt.ref.y), y2: Y(opt.ref.y), stroke: css('--ink2'), 'stroke-width': 1 }));
    svg.appendChild(s('text', { x: W - Rr, y: Y(opt.ref.y) - 6, 'text-anchor': 'end', class: 'ink2', text: opt.ref.l })); }
  const surf = css('--surface');
  if (opt.frontier && opt.frontier.length > 1) svg.appendChild(s('path', { d: opt.frontier.map((c, i) => (i ? 'L' : 'M') + X(c.cost).toFixed(1) + ',' + Y(c.pct).toFixed(1)).join(''),
    fill: 'none', stroke: css('--s1'), 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  series.forEach(sr => {
    const P = sr.pts.filter(p => !p.loose).sort((a, b) => (a.o != null && b.o != null) ? a.o - b.o : a.x - b.x);
    if (sr.line !== false && P.length > 1) svg.appendChild(s('path', { d: P.map((p, i) => (i ? 'L' : 'M') + X(p.x).toFixed(1) + ',' + Y(p.y).toFixed(1)).join(''),
      fill: 'none', stroke: sr.c, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  });
  const placed = [];
  series.forEach(sr => sr.pts.slice().sort((a, b) => (b.label ? 1 : 0) - (a.label ? 1 : 0) || b.y - a.y).forEach(p => {
    const g = s('g', { class: 'hov', tabindex: 0 });
    g.appendChild(s('circle', { cx: X(p.x), cy: Y(p.y), r: 12, class: 'hit' }));
    g.appendChild(p.loose ? s('circle', { class: 'mark', cx: X(p.x), cy: Y(p.y), r: 4.5, fill: surf, stroke: p.c || sr.c, 'stroke-width': 2 })
      : s('circle', { class: 'mark', cx: X(p.x), cy: Y(p.y), r: p.r || 4.5, fill: p.c || sr.c, stroke: surf, 'stroke-width': 2 }));
    if (p.label) { const lx = X(p.x) + 9, ly = Y(p.y) - 9, lw = p.label.length * 6.2;
      const box = { x0: lx, x1: lx + lw, y0: ly - 11, y1: ly + 2 };
      if (!placed.some(b => b.x0 < box.x1 && box.x0 < b.x1 && b.y0 < box.y1 && box.y0 < b.y1) && box.x1 < W) {
        placed.push(box); g.appendChild(s('text', { x: lx, y: ly, class: 'ink2 halo', text: p.label })); } }
    bindTip(g, () => [p.title || sr.name, p.tip]);
    svg.appendChild(g);
  }));
  return svg;
}

// ================= panels
function renderHeadline() {
  const sec = document.getElementById('p-headline'); sec.replaceChildren();
  const T = U.totals;
  const span = T.start ? day(T.start) + ' ' + hhmm(T.start) + ' – ' + hhmm(T.end) : 'no calls yet';
  panelHead(sec, '01', { kicker: 'Ledger', h: 'Every Gemini call, counted' },
    'One JSONL row per call from every feature, host and process (canary/gemini/ledger.py). Counts and timings only — never prompts.');
  const heroCard = card('heroCard', null, null, [h('div', { class: 'kicker', text: 'Gemini API calls' }),
    h('div', { class: 'heroNum', text: nf.format(T.calls) }),
    h('p', { text: `${T.n_features} features · ${T.n_models} models · ${span}` }),
    h('div', { class: 'caps' }, U.capabilities.map(c => h('span', { class: 'chip', text: c })))]);
  const tiles = [
    ['Input tokens', compact(T.in), `max ${compact(U.max_input_tokens)} in one call`],
    ['Output tokens', compact(T.out), 'excludes thinking'],
    ['Thinking tokens', compact(T.thinking), pctf(T.thinking_share) + ' of generated tokens'],
    ['Cached tokens', compact(T.cached), pctf(U.cache.hit_share) + ' of input served from cache'],
    ['Cost', usd(T.cost_usd), T.cost_unknown_calls ? 'list price · ' + nf.format(T.cost_unknown_calls) + ' calls unpriced' : 'list price, every call priced'],
    ['Models', String(T.n_models), T.models.map(short).slice(0, 3).join(', ') + (T.n_models > 3 ? '…' : '')],
    ['Features', String(T.n_features), T.features.slice(0, 4).join(', ') + (T.n_features > 4 ? '…' : '')],
    ['Error rate', pctf(T.error_rate, 1), nf.format(T.errors) + ' failed calls'],
    ['p50 latency', secs(T.p50_latency_s), 'generate calls'],
    ['p95 latency', secs(T.p95_latency_s), 'generate calls'],
  ];
  const tl = h('div', { class: 'tiles' }, tiles.map(t => h('div', { class: 'tile' }, [h('div', { class: 'lab', text: t[0] }), h('div', { class: 'val', text: t[1] }), h('div', { class: 'note', text: t[2], title: t[2] })])));
  sec.appendChild(h('div', { class: 'hero' }, [heroCard, tl]));
}

function renderUsage() {
  const sec = document.getElementById('p-usage'); sec.replaceChildren();
  let metric = sec.dataset.metric || 'tokens';
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Matrix metric' }, ['calls', 'tokens', 'cost'].map(m => {
    const b = h('button', { type: 'button', 'aria-pressed': String(m === metric), text: m });
    b.addEventListener('click', () => { sec.dataset.metric = m; renderUsage(); }); return b; }));
  panelHead(sec, '02', { kicker: 'Usage', h: 'Where the tokens go' }, 'Feature × model, over time, and what thinking, caching and batch did to the bill.', seg);
  if (!U.totals.calls) { sec.appendChild(pending('Ledger', 'python -m canary.gemini.dashboard --ledger data/gemini/ledger')); return; }
  const M = U.matrix, idx = {}; M.cells.forEach(c => idx[c.feature + '|' + c.model] = c);
  const fmt = metric === 'cost' ? usd : compact;
  const get = (f, m) => { const c = idx[f + '|' + m]; return c ? (metric === 'cost' ? c.cost_usd : metric === 'calls' ? c.calls : c.tokens) : null; };
  const mat = heatMatrix(M.features, M.models, get, fmt, { log: true, labW: 110, colLabel: short, corner: 'feature ↓ model →',
    loLabel: '0', tip: (f, m) => { const c = idx[f + '|' + m]; return [{ v: nf.format(c.calls), l: 'calls' }, { v: compact(c.in), l: 'input' }, { v: compact(c.out), l: 'output' },
      { v: compact(c.thinking), l: 'thinking' }, { v: compact(c.cached), l: 'cached' }, { v: usd(c.cost_usd), l: 'cost' }]; } });
  const g = h('div', { class: 'grid' });
  g.appendChild(card('c12', 'Usage by feature × model', metric + ' per cell · log colour scale · hover a cell for the full breakdown', [mat]));
  const tlb = U.timeline.bin_s;
  g.appendChild(card('c8', 'Calls over time', 'Gemini calls per ' + secs(tlb) + ', stacked by feature', [timelineChart()]));
  const tm = U.by_model.filter(m => m.out + m.thinking > 0 && m.kinds.includes('generate'));
  g.appendChild(card('c4', 'Thinking share by model', 'thinking ÷ (thinking + output) tokens', [hbars(tm.map(m => ({ l: short(m.model), v: m.thinking_share, vl: pctf(m.thinking_share),
    tip: [{ v: pctf(m.thinking_share, 1), l: 'thinking share' }, { v: compact(m.thinking), l: 'thinking tokens' }, { v: compact(m.out), l: 'output tokens' }] })), { max: 1, labW: 100, W: 380, aria: 'thinking share by model' })]));
  const C = U.cache, Bt = U.batch;
  const econ = h('div', { class: 'tiles', style: 'grid-template-columns:repeat(2,minmax(0,1fr));margin-bottom:14px' }, [
    ['Cache savings', usd(C.saved_usd), compact(C.cached_tokens) + ' cached input tokens'],
    ['Batch savings', usd(Bt.saved_usd), Bt.calls ? nf.format(Bt.calls) + ' batch calls at 50% list' : 'no batch calls yet']].map(t =>
    h('div', { class: 'tile' }, [h('div', { class: 'lab', text: t[0] }), h('div', { class: 'val', text: t[1] }), h('div', { class: 'note', text: t[2] })])));
  const cb = C.by_feature.slice(0, 6).map(c => ({ l: c.feature, v: c.saved_usd, vl: usd(c.saved_usd), c: featColor(c.feature),
    tip: [{ v: usd(c.saved_usd), l: 'saved vs full input price' }, { v: compact(c.cached), l: 'cached tokens' }, { v: pctf(c.cached / Math.max(1, c.in)), l: 'of input cached' }] }));
  g.appendChild(card('c5', 'Cache and batch economics', 'Saved vs paying full list price for the same tokens', [econ, cb.length ? hbars(cb, { labW: 80, W: 470, aria: 'cache savings by feature' }) : null]));
  const lm = U.by_model.filter(m => m.latency_n > 0);
  g.appendChild(card('c7', 'Latency by model', 'generate calls · dot = p50, bar end = p95', [latencyChart(lm)]));
  const GB = R.gateway_bench;
  if (GB && GB.rows.length) {
    const ms = [...new Set(GB.rows.map(r => r.model))].sort(morder);
    const ser = ms.map(m => ({ name: short(m), c: modelColor(m), pts: GB.rows.filter(r => r.model === m && r.rpm != null).map(r => ({ x: r.conc, y: r.rpm,
      title: short(m) + ' · ' + r.conc + ' concurrent', tip: [{ v: nf.format(Math.round(r.rpm)), l: 'requests / min' }, { v: secs(r.p50_s || 0) + ' / ' + secs(r.p95_s || 0), l: 'p50 / p95 latency' },
        { v: nf.format(r.errors || 0), l: 'errors' }, { v: nf.format(r.retries || 0), l: 'gateway retries' }] })) })).filter(s => s.pts.length);
    const ymax = Math.max(...GB.rows.map(r => r.rpm || 0)) * 1.1;
    const yt = niceTicks(ymax, 4);
    g.appendChild(card('c12', 'Gateway throughput', 'closed-loop rate bench through the Canary Lab gateway · requests per minute vs concurrent clients · ' + nf.format(GB.calls || 0) + ' calls, $' + (GB.spend_usd || 0),
      [legend(ser.map(s => ({ c: s.c, l: s.name })), true), xyChart(ser, { W: 1180, H: 260, R: 24, ymin: 0, ymax: yt[yt.length - 1], yticks: yt, yfmt: v => compact(v), xfmt: v => String(v), xticks: [...new Set(GB.rows.map(r => r.conc))].sort((a, b) => a - b), xmin: 0, xlabel: 'concurrent clients', aria: 'gateway throughput' })]));
  }
  const ft = h('table', { class: 'list' }, [h('thead', {}, [h('tr', {}, ['feature', 'calls', 'input', 'output', 'thinking', 'cached', 'cost', 'errors', 'models'].map((c, i) => h('th', { class: i && i < 8 ? 'num' : '', text: c })))]),
    h('tbody', {}, U.by_feature.map(f => h('tr', {}, [h('td', { text: f.feature }), h('td', { class: 'num', text: nf.format(f.calls) }), h('td', { class: 'num', text: compact(f.in) }),
      h('td', { class: 'num', text: compact(f.out) }), h('td', { class: 'num', text: compact(f.thinking) }), h('td', { class: 'num', text: compact(f.cached) }),
      h('td', { class: 'num', text: usd(f.cost_usd) }), h('td', { class: 'num', text: nf.format(f.errors) }), h('td', { class: 'plan', text: f.models.map(short).join(', ') })])))]);
  const det = h('details', { class: 'tbl' }, [h('summary', { text: 'Table view: usage by feature' }), ft]);
  const errs = U.errors.length ? h('p', { class: 'sub', text: 'Errors by type: ' + U.errors.map(e => e.type + ' ×' + e.n).join(' · ') }) : null;
  g.appendChild(card('c12', null, null, [det, errs]));
  sec.appendChild(g);
}

function latencyChart(models) {
  const W = 640, rowH = 26, L = 110, Rr = 50, Tp = 4, B = 24;
  const H = Tp + models.length * rowH + B;
  const max = Math.max(1, ...models.map(m => m.p95_latency_s));
  const ticks = niceTicks(max, 5), xm = ticks[ticks.length - 1];
  const X = v => L + (W - L - Rr) * v / xm;
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'latency p50 and p95 by model' });
  ticks.forEach(t => { svg.appendChild(s('line', { class: 'gridline', x1: X(t), x2: X(t), y1: Tp, y2: H - B }));
    svg.appendChild(s('text', { x: X(t), y: H - 8, 'text-anchor': 'middle', text: t + ' s' })); });
  const surf = css('--surface');
  models.forEach((m, i) => {
    const y = Tp + i * rowH + rowH / 2, c = modelColor(m.model);
    const g = s('g', { class: 'hov', tabindex: 0 });
    g.appendChild(s('rect', { class: 'hit', x: 0, y: y - rowH / 2, width: W, height: rowH }));
    g.appendChild(s('text', { x: L - 8, y: y + 4, 'text-anchor': 'end', class: 'ink2', text: short(m.model) }));
    g.appendChild(s('line', { x1: X(m.p50_latency_s), x2: X(m.p95_latency_s), y1: y, y2: y, stroke: c, 'stroke-width': 2, 'stroke-linecap': 'round', opacity: .55 }));
    g.appendChild(s('circle', { class: 'mark', cx: X(m.p50_latency_s), cy: y, r: 4.5, fill: c, stroke: surf, 'stroke-width': 2 }));
    g.appendChild(s('text', { x: X(m.p95_latency_s) + 8, y: y + 4, class: 'ink', text: secs(m.p95_latency_s) }));
    bindTip(g, () => [short(m.model), [{ v: secs(m.p50_latency_s), l: 'p50' }, { v: secs(m.p95_latency_s), l: 'p95' }, { v: nf.format(m.latency_n), l: 'calls' }]]);
    svg.appendChild(g);
  });
  return svg;
}

// ---- ladder
function lget(c, keys, dflt) { for (const k of keys) if (c[k] != null) return c[k]; return dflt; }
function ladderCells(L) {
  return (L.rows || L.cells || []).map(c => ({ model: c.model, level: String(lget(c, ['level', 'thinking_level'], '')).toLowerCase(), tier: c.tier,
    n: lget(c, ['n', 'episodes'], null), pct: lget(c, ['ratio', 'pct_solver', 'frac_solver', 'score_vs_solver'], null),
    ci: lget(c, ['pct_solver_ci95', 'ci95'], c.ratio_lo != null && c.ratio_hi != null ? [c.ratio_lo, c.ratio_hi] : null),
    score: lget(c, ['mean', 'score_mean', 'score'], null), solver: lget(c, ['solver_same_seeds', 'solver_mean', 'solver'], null),
    think: lget(c, ['thinking_per_ep', 'thinking_tokens_per_episode', 'thinking_per_episode', 'thinking_tokens'], null),
    est: !!c.thinking_is_estimate, acc: lget(c, ['accuracy'], null), day: lget(c, ['accuse_day'], null),
    cost: lget(c, ['cost_per_ep', 'cost_usd_per_episode', 'cost_per_episode', 'cost_usd'], null), regret: lget(c, ['regret_mean', 'regret'], null) }))
    .map(c => { if (c.pct == null && c.score != null && c.solver) c.pct = c.score / c.solver; return c; })
    .filter(c => c.model && c.tier && c.pct != null);
}
const LEVELS = ['minimal', 'low', 'medium', 'high'];
const MORDER = ['gemini-3.1-flash-lite', 'gemini-3.5-flash', 'gemini-3.8-flash', 'gemini-4-hydrogen', 'gemini-4-argon', 'gemini-4-carbon'];
function morder(a, b) { const i = MORDER.indexOf(a), j = MORDER.indexOf(b); return (i < 0 ? 99 : i) - (j < 0 ? 99 : j) || (a < b ? -1 : 1); }
function lorder(a, b) { const i = LEVELS.indexOf(a), j = LEVELS.indexOf(b); return (i < 0 ? 99 : i) - (j < 0 ? 99 : j); }

function refLines(L, tier) {
  // reference agents (G2 "reference" rows) as % of the solver on the same seeds
  const ref = (L.reference || []).filter(r => r.tier === tier);
  const sol = ref.find(r => r.agent === 'solver');
  if (!sol || !(sol.mean > 0)) return [];
  return ref.filter(r => r.agent !== 'solver' && r.agent !== 'do_nothing' && r.mean != null).map(r => ({ y: r.mean / sol.mean, l: r.agent.replace('_', ' ') }));
}
function renderLadder() {
  const sec = document.getElementById('p-ladder'); sec.replaceChildren();
  const L = R.ladder; const cells = L ? ladderCells(L) : [];
  const tiers = [...new Set(cells.map(c => c.tier))].sort((a, b) => ['easy', 'medium', 'hard'].indexOf(a) - ['easy', 'medium', 'hard'].indexOf(b));
  let tier = sec.dataset.tier && tiers.includes(sec.dataset.tier) ? sec.dataset.tier : (tiers.includes('hard') ? 'hard' : tiers[0]);
  const seg = tiers.length > 1 ? h('div', { class: 'seg', role: 'group', 'aria-label': 'Tier' }, tiers.map(t => { const b = h('button', { type: 'button', 'aria-pressed': String(t === tier), text: t });
    b.addEventListener('click', () => { sec.dataset.tier = t; renderLadder(); }); return b; })) : null;
  const eps = cells.reduce((a, c) => a + (c.n || 0), 0);
  panelHead(sec, '03', { kicker: 'Ladder', h: 'How much thinking buys how much of the gap?' },
    'Gemini models × thinking levels against the Bayesian reference solver, paired on the same seeds. 100% = solver parity.' + (eps ? ' ' + nf.format(eps) + ' episodes in ' + cells.length + ' cells.' : ''), seg);
  if (!cells.length) { sec.appendChild(pending('Ladder', 'python -m canary.gemini.ladder_report --runs <dir> → results/gemini/ladder.json')); return; }
  const tc = cells.filter(c => c.tier === tier);
  const models = [...new Set(tc.map(c => c.model))].sort(morder), levels = [...new Set(tc.map(c => c.level))].sort(lorder);
  const at = (m, l) => tc.find(c => c.model === m && c.level === l);
  const cellTip = c => { const r = [{ v: pctf(c.pct), l: 'of solver score, same seeds' }];
    if (c.ci && c.ci[0] != null) r.push({ v: '[' + pctf(c.ci[0]) + ', ' + pctf(c.ci[1]) + ']', l: 'paired 95% CI' });
    if (c.score != null) r.push({ v: c.score.toFixed(3), l: 'mean score (solver ' + (c.solver != null ? c.solver.toFixed(3) : '?') + ')' });
    if (c.n != null) r.push({ v: String(c.n), l: 'episodes' });
    if (c.acc != null) r.push({ v: pctf(c.acc), l: 'correct accusations' });
    if (c.day != null) r.push({ v: c.day.toFixed(1), l: 'mean accuse day' });
    if (c.think != null) r.push({ v: compact(c.think) + (c.est ? '*' : ''), l: 'thinking tokens / episode' + (c.est ? ' (*incl. output)' : '') });
    if (c.cost != null) r.push({ v: usd(c.cost), l: 'per episode' }); return r; };
  const g = h('div', { class: 'grid' });
  const hm = heatMatrix(models, levels, (m, l) => { const c = at(m, l); return c ? c.pct : null; }, v => pctf(v), { diverging: [1, 1], labW: 120, rowLabel: short,
    corner: 'model ↓ thinking →', loLabel: '≤ −100% (worse than doing nothing)', hiLabel: '≥ 100% = solver', tip: (m, l) => cellTip(at(m, l)) });
  const ns = tc.map(c => c.n || 0), nlo = Math.min(...ns), nhi = Math.max(...ns);
  g.appendChild(card('c5', 'Score as % of solver · ' + tier, 'model × thinking level · ' + (nlo === nhi ? nlo : nlo + '–' + nhi) + ' episodes per cell · hover for the paired CI', [synthBadge(L), hm]));
  const refs = refLines(L, tier);
  const series = models.map(m => ({ name: short(m), c: modelColor(m), pts: tc.filter(c => c.model === m && c.think != null).map(c => ({ x: Math.max(c.think, 10), y: c.pct,
    o: LEVELS.indexOf(c.level) < 0 ? null : LEVELS.indexOf(c.level), loose: LEVELS.indexOf(c.level) < 0 || c.est,
    title: short(m) + ' · ' + c.level + (c.est ? ' (imported; thinking incl. output)' : ''), tip: cellTip(c) })) })).filter(sr => sr.pts.length);
  if (series.length) {
    const ys = series.flatMap(s => s.pts.map(p => p.y)).concat(refs.map(r => r.y));
    g.appendChild(card('c7', 'Score vs thinking tokens · ' + tier, 'mean thinking tokens per episode (log) · one line per model, minimal → high · hollow = imported cell at the model default',
      [legend(series.map(s => ({ c: s.c, l: s.name })), true), xyChart(series, { logx: true, xfloor: 10, ymin: Math.min(0, ...ys), ymax: Math.max(1.1, ...ys), yticks: [0, .25, .5, .75, 1], pctAuto: true,
        yfmt: v => pctf(v), xfmt: v => v <= 10 ? '≤10' : compact(v), ref: { y: 1, l: 'solver' }, refs, W: 680, H: 320, aria: 'score vs thinking tokens' })]));
  }
  const cc = tc.filter(c => c.cost != null && c.cost > 0);
  if (cc.length) {
    const sorted = cc.slice().sort((a, b) => a.cost - b.cost || b.pct - a.pct); const front = []; let best = -Infinity;
    sorted.forEach(c => { if (c.pct > best) { front.push(c); best = c.pct; } });
    const fset = new Set(front);
    const blue = css('--s1'), grey = css('--other');
    const pts = cc.map(c => ({ x: c.cost, y: c.pct, c: fset.has(c) ? blue : grey, r: fset.has(c) ? 5 : 3.5,
      label: fset.has(c) ? short(c.model) + ' · ' + c.level : null, title: short(c.model) + ' · ' + c.level,
      tip: cellTip(c).concat(fset.has(c) ? [{ v: 'frontier', l: 'nothing cheaper scores higher' }] : []) }));
    const ys = cc.map(c => c.pct).concat(refs.map(r => r.y));
    g.appendChild(card('c12', 'Cost frontier · ' + tier, 'list-price $ per episode (log) vs % of solver · blue = Pareto frontier (nothing cheaper scores higher)',
      [frontierChart(front, pts, ys, refs)]));
  }
  const tg = L.tags && L.tags.pooled;
  if (tg) {
    const lv = ['low', 'medium', 'high'].filter(l => tg[l + '|' + tier]);
    if (lv.length >= 2) {
      const tagSet = {}; lv.forEach(l => Object.entries(tg[l + '|' + tier].tags || {}).forEach(([k, v]) => { tagSet[k] = Math.max(tagSet[k] || 0, v.regret_per_ep || 0); }));
      const tags = Object.keys(tagSet).sort((a, b) => tagSet[b] - tagSet[a]).slice(0, 8);
      if (tags.length) {
        const get = (tag, l) => { const d = (tg[l + '|' + tier].tags || {})[tag]; return d ? d.regret_per_ep : 0; };
        const mx = Math.max(1e-9, ...tags.flatMap(tag => lv.map(l => get(tag, l))));
        const hm2 = heatMatrix(tags, lv, get, v => v.toFixed(3), { min: 0, max: mx, labW: 170, corner: 'failure tag ↓ thinking →', loLabel: '0', hiLabel: mx.toFixed(3) + ' regret / episode',
          tip: (tag, l) => { const d = (tg[l + '|' + tier].tags || {})[tag] || {}; return [{ v: (d.regret_per_ep || 0).toFixed(3), l: 'regret per episode' }, { v: pctf(d.rate || 0), l: 'of episodes show it' }]; } });
        const common = (L.tags.pooled_common_models || []).map(short).join(', ');
        g.appendChild(card('c12', 'Which mistakes does thinking fix? · ' + tier, 'solver regret per episode by failure tag, pooled over ' + (common || 'the models that ran every level') + ' · a row that fades left→right is a mistake thinking fixes', [hm2]));
      }
    }
  }
  sec.appendChild(g);
}
function frontierChart(front, pts, ys, refs) {
  const blue = css('--s1');
  const sf = front.slice().sort((a, b) => a.cost - b.cost);
  void blue;
  return xyChart([{ name: 'cells', c: css('--other'), pts, line: false }], { logx: true, xfloor: 0.001, W: 1180, H: 340, R: 140, ymin: Math.min(0, ...ys), ymax: Math.max(1.1, ...ys),
      yfmt: v => pctf(v), xfmt: v => v < 1 ? '$' + (+v.toPrecision(2)) : usd(v), ref: { y: 1, l: 'solver' }, refs: refs || [], aria: 'cost frontier', frontier: sf });
}

// ---- atlas
function tilesRow(tiles) {
  return h('div', { class: 'c12 tiles' }, tiles.map(t => h('div', { class: 'tile' }, [h('div', { class: 'lab', text: t[0] }), h('div', { class: 'val', text: t[1] }), h('div', { class: 'note', text: t[2] || '', title: t[2] || '' })])));
}
function renderAtlas() {
  const sec = document.getElementById('p-atlas'); sec.replaceChildren();
  const A = R.atlas;
  panelHead(sec, '04', { kicker: 'Failure Atlas', h: 'Why the agent loses, in its own words' },
    'Gemini reads the whole trajectory corpus in one long, cached context. Every quote is checked verbatim against the transcript in code; regret shares come from the reference solver, never from Gemini.');
  if (!A || !(A.modes || []).length) { sec.appendChild(pending('Atlas', 'python -m canary.gemini.atlas --runs <dirs> → results/gemini/atlas.json')); return; }
  const g = h('div', { class: 'grid' });
  const C = A.corpus || {}, HA = A.human_agreement, V = A.verification, LO = A.localisation;
  const quotes = A.modes.flatMap(m => m.quotes || []);
  const tiles = [['Episodes read', C.episodes != null ? nf.format(C.episodes) : '—', A.model ? 'by ' + short(A.model) + ' in one prompt' : ''],
    ['Corpus tokens', C.tokens != null ? compact(C.tokens) : '—', C.cached_tokens ? compact(C.cached_tokens) + ' input tokens served from cache' : 'long context'],
    ['Quotes verified', V && V.pass_rate != null ? pctf(V.pass_rate) : quotes.length ? quotes.filter(q => q.verified).length + ' / ' + quotes.length : '—',
      V && V.quotes_checked != null ? nf.format(V.quotes_checked) + ' checked verbatim · ' + (V.dropped || 0) + ' dropped' : 'verbatim match against transcripts'],
    LO ? ['Chart reading', LO.agree + ' / ' + LO.n, 'divergence step found within 3 steps (multimodal)'] : ['Failure modes', String(A.modes.length), 'ranked by regret share'],
    ['Human agreement', HA && HA.rate != null ? pctf(HA.rate) : 'pending', HA && HA.rate != null ? (HA.n ? HA.n + ' claims labelled by a teammate' : 'human–Gemini agreement') : 'labels in docs/gemini/validation.md']];
  g.appendChild(tilesRow(tiles));
  if (A.summary) g.appendChild(card('c12', 'What Gemini found', null, [h('p', { class: 'summary', text: A.summary })]));
  const modes = A.modes.slice().sort((a, b) => (b.regret_share || 0) - (a.regret_share || 0));
  const list = h('div', { class: 'modes' }, modes.slice(0, 6).map((m, i) => {
    const bar = h('div', { class: 'share' }, [h('div')]); bar.firstChild.style.width = Math.max(0, Math.min(100, (m.regret_share || 0) * 100)) + '%';
    const qs_ = (m.quotes || []).slice(0, 2).map(q => h('blockquote', {}, ['“' + q.quote + '”',
      h('span', { class: 'src' }, [`${q.episode || ''}${q.t != null ? ' · step ' + q.t : ''}`,
        h('span', { class: 'badge ' + (q.verified ? 'ok' : 'no'), text: q.verified ? (q.step_verified ? '✓ verified at step' : '✓ verified') : '✗ unverified' })])]));
    const thumb = h('div', { class: 'thumb' }, [m.chart_src ? h('img', { src: m.chart_src, alt: 'belief trace chart for ' + (m.name || m.id) }) : h('div', { class: 'ph', text: m.chart ? 'chart: ' + m.chart : 'no chart' })]);
    const extra = [];
    if (m.mechanism) extra.push(h('p', { class: 'desc' }, [h('b', { text: 'Why: ' }), m.mechanism]));
    if (m.solver_would) extra.push(h('p', { class: 'desc' }, [h('b', { text: 'Solver instead: ' }), m.solver_would]));
    return h('div', { class: 'mode' }, [h('div', { class: 'rank', text: String(i + 1) }), h('div', {}, [h('h4', { text: m.name || m.id }), h('p', { class: 'desc', text: m.description || '' })].concat(extra).concat([
      h('div', { class: 'facts' }, [h('span', {}, [h('b', { text: pctf(m.regret_share || 0) }), ' of all regret']), m.episodes != null ? h('span', {}, [h('b', { text: String(m.episodes) }), ' episodes']) : null,
        m.steps != null ? h('span', {}, [h('b', { text: String(m.steps) }), ' decisions']) : null, m.decision ? h('span', {}, ['decision ', h('b', { text: m.decision })]) : null]), bar]).concat(qs_)), thumb]);
  }));
  g.appendChild(card('c12', 'Top failure modes', 'bar = share of all solver regret attributed to the mode', [synthBadge(A), list]));
  const co = (C.cohorts || []).filter(c => c.cohort);
  if (co.length) {
    const tb = h('table', { class: 'list' }, [h('thead', {}, [h('tr', {}, ['cohort (model / harness / rules)', 'episodes', 'mean score', 'accuracy', 'mean regret'].map((c, i) => h('th', { class: i ? 'num' : '', text: c })))]),
      h('tbody', {}, co.map(c => h('tr', {}, [h('td', { text: c.cohort }), h('td', { class: 'num', text: c.episodes != null ? String(c.episodes) : '–' }),
        h('td', { class: 'num', text: c.score_mean != null ? c.score_mean.toFixed(3) : '–' }), h('td', { class: 'num', text: c.accuracy != null ? pctf(c.accuracy) : '–' }),
        h('td', { class: 'num', text: c.regret_mean != null ? c.regret_mean.toFixed(3) : '–' })])))]);
    g.appendChild(card('c12', 'Corpus by cohort', 'never pooled across rule versions', [tb]));
  }
  sec.appendChild(g);
}

// ---- swarm
function renderSwarm() {
  const sec = document.getElementById('p-swarm'); sec.replaceChildren();
  const S = R.swarm;
  panelHead(sec, '05', { kicker: 'Swarm', h: 'Can Gemini game the reward?' },
    'Gemini attackers hold the whole repo in a cached context and try to beat the score without catching the mole. Only scores the env ledger records count; every real finding becomes a regression test.');
  if (!S || !(S.attempts || []).length) { sec.appendChild(pending('Swarm', 'python -m canary.gemini.swarm --attackers 50 → results/gemini/swarm.json')); return; }
  const at = S.attempts, scored = at.filter(a => a.score != null);
  const personas = new Set(at.map(a => a.persona)).size;
  const best = S.best_non_solver, solver = S.solver_score;
  const tiles = [['Attacks', nf.format(at.length), [S.mode, S.tier].filter(Boolean).join(' · ') + (S.tool_calls ? ' · ' + nf.format(S.tool_calls) + ' tool calls' : '')],
    ['Personas', String(personas), S.model ? String(S.model).split(',').map(short).join(', ') : ''],
    ['Best non-solver score', best != null ? (best >= 0 ? '+' : '') + best.toFixed(3) : '—', solver != null ? 'solver ' + (solver >= 0 ? '+' : '') + solver.toFixed(3) + ' on the same seeds' : ''],
    ['Verified exploits', String(S.exploits || 0), (S.exploits ? 'invariant broken, ledger-verified' : 'no invariant broken') + (S.candidates ? ' · ' + S.candidates + ' score candidates' : '')],
    ['Regression tests', S.tests_written != null ? String(S.tests_written) : '—', 'written from the attacks']];
  const g = h('div', { class: 'grid' });
  g.appendChild(tilesRow(tiles));
  g.appendChild(card('c7', 'Every attack vs the solver', 'one dot per attack · x = episode score · grey = not ledger-verified · red = exploit', [synthBadge(S), stripChart(scored, solver)]));
  const top = scored.slice().sort((a, b) => b.score - a.score).slice(0, 7);
  const tbl = h('table', { class: 'list' }, [h('thead', {}, [h('tr', {}, [h('th', { text: 'persona' }), h('th', { text: 'hypothesis' }), h('th', { class: 'num', text: 'score' }), h('th', { text: 'ledger' })])]),
    h('tbody', {}, top.map(a => h('tr', {}, [h('td', { class: 'nw', text: a.persona }), h('td', { class: 'plan', text: String(a.plan || '').slice(0, 150) + (String(a.plan || '').length > 150 ? '…' : '') }), h('td', { class: 'num', text: (a.score >= 0 ? '+' : '') + a.score.toFixed(3) }),
      h('td', {}, [h('span', { class: 'badge ' + (a.ledger_verified ? 'ok' : 'no'), text: a.ledger_verified ? '✓ verified' : '✗ claim only' })])])))]);
  g.appendChild(card('c5', 'Top attacks', 'highest verified scores first', [tbl]));
  const vk = Object.entries(S.violation_kinds || {});
  if (S.findings.length || vk.length) {
    const kids = [];
    if (vk.length) kids.push(h('p', { class: 'sub', text: 'Invariant violations by kind: ' + vk.map(([k, n]) => k + ' ×' + n).join(' · ') }));
    if (S.findings.length) kids.push(h('table', { class: 'list' }, [h('tbody', {}, S.findings.map(f => h('tr', {}, [h('td', { text: f.title }),
      h('td', {}, [h('span', { class: 'badge ' + (f.verified ? 'ok' : 'no'), text: f.verified ? '✓ verified' : 'unverified' })]), h('td', { class: 'plan', text: f.test })])))]));
    g.appendChild(card('c12', 'Findings', null, kids));
  }
  sec.appendChild(g);
}
function stripChart(at, solver) {
  const W = 680, H = 240, L = 16, Rr = 16, cy = 110;
  const lo = Math.min(-1, ...at.map(a => a.score)), hi = Math.max(1, ...at.map(a => a.score));
  const X = v => L + (W - L - Rr) * (v - lo) / (hi - lo);
  const svg = s('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'attack scores vs solver' });
  [-1, -0.5, 0, 0.5, 1].forEach(t => { svg.appendChild(s('line', { class: 'gridline', x1: X(t), x2: X(t), y1: 20, y2: H - 30 }));
    svg.appendChild(s('text', { x: X(t), y: H - 12, 'text-anchor': 'middle', text: (t > 0 ? '+' : '') + t })); });
  if (solver != null) { svg.appendChild(s('line', { x1: X(solver), x2: X(solver), y1: 12, y2: H - 30, stroke: css('--ink'), 'stroke-width': 1.5 }));
    svg.appendChild(s('text', { x: X(solver) + 6, y: 20, class: 'ink', text: 'solver ' + (+solver).toFixed(2) })); }
  const surf = css('--surface'), blue = css('--s1'), grey = css('--other'), red = css('--crit');
  const sorted = at.slice().sort((a, b) => a.score - b.score); const placed = [];
  sorted.forEach(a => { const x = X(a.score); let k = 0; while (placed.some(p => Math.abs(p.x - x) < 9 && p.k === k)) k++; placed.push({ x, k, a }); });
  const maxK = Math.max(1, ...placed.map(p => p.k)); const step = Math.min(9, (H - 60) / (maxK + 1));
  placed.forEach(({ x, k, a }) => {
    const y = cy + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * step;
    const g = s('g', { class: 'hov', tabindex: 0 });
    g.appendChild(s('circle', { class: 'hit', cx: x, cy: y, r: 10 }));
    g.appendChild(s('circle', { class: 'mark', cx: x, cy: y, r: step < 7 ? 3 : 4, fill: a.exploit && a.ledger_verified ? red : a.ledger_verified ? blue : grey, stroke: surf, 'stroke-width': step < 7 ? 1 : 2 }));
    bindTip(g, () => [a.persona, [{ v: (a.score >= 0 ? '+' : '') + a.score.toFixed(3), l: 'episode score' }, { v: a.ledger_verified ? 'ledger-verified' : 'claim only', l: '' }]
      .concat(a.solver_score != null ? [{ v: a.solver_score.toFixed(3), l: 'solver, same seed' }] : []).concat(a.exploit ? [{ v: 'exploit', l: 'invariant broken' }] : [])
      .concat(a.plan ? [{ v: '', l: String(a.plan).slice(0, 120) }] : [])]);
    svg.appendChild(g); });
  return svg;
}

function renderFoot() {
  const f = document.getElementById('foot'); f.replaceChildren();
  const M = D.meta;
  document.getElementById('meta-line').textContent = 'built ' + M.generated_at.replace('T', ' ').slice(0, 16) + (M.git_sha ? ' · ' + M.git_sha : '') + ' · ' + nf.format(M.ledger_rows) + ' ledger rows';
  const prov = ['ladder', 'atlas', 'swarm'].map(k => { const r = R[k]; return r ? `${k}.json ${r.git_sha || '?'} ${r.generated_at || ''}${r.synthetic ? ' (SYNTHETIC)' : ''}` : `${k}.json pending`; });
  f.appendChild(h('p', {}, ['Generated by ', h('code', { text: 'python -m canary.gemini.dashboard' }), ' from ', h('code', { text: (M.sources || []).join(', ') }), ' and results/gemini/*.json. Static, offline, no network requests.']));
  f.appendChild(h('p', { text: prov.join(' · ') }));
  f.appendChild(h('p', { text: 'Costs are list prices from canary/llm/pricing.py; models without a list price count as $0 and are flagged. Cache savings = cached tokens × (input − cached-input price). Batch savings = 50% of the interactive price.' }));
}

function renderAll() {
  renderHeadline(); renderUsage(); renderLadder(); renderAtlas(); renderSwarm(); renderFoot();
}
const focus = qs.get('panel');
if (focus) { document.body.classList.add('focus'); focus.split(',').forEach(p => { const e = document.querySelector('[data-panel="' + p + '"]'); if (e) e.classList.add('on'); }); }
renderAll();
if (window.matchMedia) matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderAll);
})();
"""

if __name__ == "__main__":
    raise SystemExit(main())
