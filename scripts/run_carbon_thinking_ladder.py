from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import math
import os
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode as run_agent_episode
from canary.agents.runlog import RunWriter, git_sha, parse_seeds
from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.env import Env
from canary.eval import run_episode as run_eval_episode
from canary.gemini.ledger import LedgeredClient, lab_client
from canary.llm.base import LLMClient, LLMResponse, ToolCall
from canary.llm.gemini_backend import DEFAULT_MODEL, THINKING_LEVELS
from canary.llm.pricing import cost as price_cost
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute as attribute_regret
from canary.types import EpisodeResult, Step

DEFAULT_OUT = "results/gemini_roles/investigators/thinking-ladder-carbon-med01"
FEATURE = "ladder"


def strip_special_dashes(x: Any) -> Any:
    if isinstance(x, str):
        return x.replace("\u2014", " - ").replace("\u2013", "-")
    if isinstance(x, dict):
        return {k: strip_special_dashes(v) for k, v in x.items()}
    if isinstance(x, list):
        return [strip_special_dashes(v) for v in x]
    return x


def nan_to_none(x: Any) -> Any:
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: nan_to_none(v) for k, v in x.items()}
    if isinstance(x, list):
        return [nan_to_none(v) for v in x]
    return x


def parse_levels(spec: str) -> list[str]:
    levels = [part.strip().lower() for part in str(spec).split(",") if part.strip()]
    if not levels:
        raise ValueError("levels must be non-empty")
    bad = [lv for lv in levels if lv not in THINKING_LEVELS]
    if bad:
        raise ValueError(f"unknown thinking_level {bad}; allowed: {THINKING_LEVELS}")
    seen: list[str] = []
    for lv in levels:
        if lv not in seen:
            seen.append(lv)
    return seen


def parse_public_seeds(spec: str) -> list[int]:
    seeds = parse_seeds(spec)
    if not seeds:
        raise ValueError("seeds must be non-empty")
    bad = [s for s in seeds if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s < 0 or s >= 10_000]
    if bad:
        raise ValueError(f"seeds must be public dev seeds 0..9999; got {bad[:5]}")
    return seeds


def guard_output_dir(out: Path) -> Path:
    resolved = out.resolve()
    committed = (ROOT / "data" / "runs" / "committed").resolve()
    if resolved == committed or committed in resolved.parents:
        raise ValueError(f"refusing to write into {committed}")
    return out


class StubThinkingClient(LLMClient):
    provider = "stub"

    def __init__(self, model: str, thinking_level: str):
        super().__init__(model=model, max_retries=0)
        if thinking_level not in THINKING_LEVELS:
            raise ValueError(f"thinking_level must be one of {THINKING_LEVELS}")
        self.thinking_level = thinking_level
        self.finish_reasons: dict[str, int] = {}
        self._step = 0
        self._script = self._build_script(thinking_level)

    @staticmethod
    def _build_script(level: str) -> list[tuple[str, dict[str, Any]]]:
        if level in ("minimal", "low"):
            return [
                ("list_employees", {}),
                ("status", {}),
                ("accuse", {"employee": "e00"}),
            ]
        return [
            ("list_employees", {}),
            ("status", {}),
            ("list_documents", {"day_from": 1, "day_to": 1}),
            ("plant_canary", {
                "doc_title": "Board strategy draft",
                "assignment": {"e00": "A", "e01": "A", "e02": "B", "e03": "B", "e04": "C", "e05": "C"},
            }),
            ("advance_day", {}),
            ("check_leak_feed", {}),
            ("accuse", {"employee": "e05"}),
        ]

    def settings(self) -> dict[str, Any]:
        return {
            "thinking_level": self.thinking_level,
            "include_thoughts": True,
            "temperature": "not sent (stub)",
            "thought_signature_replay": True,
            "api": "stub",
            "stub": True,
        }

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        idx = min(self._step, len(self._script) - 1)
        tool_name, tool_args = self._script[idx]
        self._step += 1
        tin = max(32, sum(len(str(m.get("content") or "")) for m in messages) // 4)
        tout = 24
        think_map = {"minimal": 16, "low": 64, "medium": 256, "high": 512, "xhigh": 1024}
        tthink = think_map.get(self.thinking_level, 128)
        um = SimpleNamespace(
            prompt_token_count=tin,
            candidates_token_count=tout,
            thoughts_token_count=tthink,
            cached_content_token_count=0,
        )
        raw = SimpleNamespace(usage_metadata=um, model_version=f"stub-{self.model}")
        self.finish_reasons["STOP"] = self.finish_reasons.get("STOP", 0) + 1
        tc = ToolCall(id=f"stub_call_{self._step}", name=tool_name, args=dict(tool_args))
        c = price_cost(self.model, tin, tout + tthink, 0)
        resp = LLMResponse(
            text="",
            tool_calls=[tc],
            usage={"in": tin, "out": tout + tthink, **c},
            raw=raw,
        )
        resp.thoughts = f"stub_{self.thinking_level}_step_{self._step}"
        resp.provider_items = [{
            "role": "model",
            "parts": [
                {"thought": True, "text": resp.thoughts},
                {"function_call": {"name": tool_name, "args": dict(tool_args)}, "thought_signature": "c3R1Yl9zaWc="},
            ],
        }]
        return resp


class TallyClient:
    def __init__(self, inner: Any, model: str):
        self.inner = inner
        self.model = model
        self.calls = 0
        self.in_tokens = 0
        self.out_tokens = 0
        self.thinking_tokens = 0
        self.cached_tokens = 0
        self.latency_s = 0.0
        self.max_call_s = 0.0
        self.call_latencies_s: list[float] = []
        self.model_versions: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages: list[dict], **kw: Any) -> Any:
        t0 = time.perf_counter()
        resp = self.inner.chat(messages, **kw)
        dt = time.perf_counter() - t0
        self.calls += 1
        self.latency_s += dt
        self.max_call_s = max(self.max_call_s, dt)
        self.call_latencies_s.append(round(dt, 4))
        raw = getattr(resp, "raw", None)
        mv = getattr(raw, "model_version", None) if raw is not None else None
        if isinstance(mv, str) and mv and mv not in self.model_versions:
            self.model_versions.append(mv)
        um = getattr(raw, "usage_metadata", None) if raw is not None else None
        if um is not None:
            def _num(attr: str) -> int:
                val = getattr(um, attr, 0)
                return val if isinstance(val, int) else 0
            self.in_tokens += _num("prompt_token_count")
            self.out_tokens += _num("candidates_token_count")
            self.thinking_tokens += _num("thoughts_token_count")
            self.cached_tokens += _num("cached_content_token_count")
        else:
            u = getattr(resp, "usage", None) or {}
            self.in_tokens += int(u.get("in", 0) or 0)
            self.out_tokens += int(u.get("out", 0) or 0)
            self.cached_tokens += int(u.get("cached_in", 0) or 0)
        return resp

    def usage_dict(self, wall_s: float) -> dict[str, Any]:
        out_total = self.out_tokens + self.thinking_tokens
        c = price_cost(self.model, self.in_tokens, out_total, self.cached_tokens)
        cost_upper = float(c.get("cost_usd", 0.0) or 0.0)
        cost_est = float(c.get("cost_usd_est", cost_upper) or 0.0)
        mean_lat = (self.latency_s / self.calls) if self.calls else 0.0
        return {
            "calls": self.calls,
            "in": self.in_tokens,
            "out": self.out_tokens,
            "thinking": self.thinking_tokens,
            "cached": self.cached_tokens,
            "out_incl_thinking": out_total,
            "latency_s": round(self.latency_s, 3),
            "mean_call_s": round(mean_lat, 3),
            "max_call_s": round(self.max_call_s, 3),
            "wall_s": round(wall_s, 3),
            "cost_usd": round(cost_upper, 6),
            "cost_usd_est": round(cost_est, 6),
            "model_versions": list(self.model_versions),
        }


def clean_transcript(transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = copy.deepcopy(transcript)
    for msg in cleaned:
        items = msg.get("provider_items")
        if not items:
            continue
        items_list = items if isinstance(items, list) else [items]
        thoughts_found: list[str] = []
        for item in items_list:
            if not isinstance(item, dict):
                continue
            parts = item.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if part.get("thought") and isinstance(part.get("text"), str) and part["text"]:
                    thoughts_found.append(part["text"])
                for sig_key in ("thought_signature", "thoughtSignature"):
                    sig_val = part.get(sig_key)
                    if isinstance(sig_val, str):
                        part[sig_key] = f"<redacted_thought_signature_chars:{len(sig_val)}>"
        if thoughts_found and "thoughts" not in msg:
            msg["thoughts"] = thoughts_found
    return strip_special_dashes(cleaned)


def analyze_episode(ep: EpisodeResult) -> dict[str, Any]:
    reg_items = attribute_regret(ep)
    regret_total = sum(float(it.get("regret", 0.0) or 0.0) for it in reg_items)
    tag_counts: Counter[str] = Counter()
    tag_regret_sum: dict[str, float] = {}
    for it in reg_items:
        r = float(it.get("regret", 0.0) or 0.0)
        for tag in it.get("tags") or []:
            tag_counts[tag] += 1
            tag_regret_sum[tag] = round(tag_regret_sum.get(tag, 0.0) + r, 6)
    p_accused = None
    p_top = None
    verdict = None
    try:
        aud = audit_episode(ep)
        p_accused = aud.get("p_accused")
        p_top = aud.get("p_top")
        verdict = aud.get("verdict")
    except Exception:
        p_accused = None
    v_val = (ep.meta or {}).get("V", (ep.meta or {}).get("V_final"))
    if not ep.accused:
        luck_adj = 0.0
    elif p_accused is not None and v_val is not None:
        luck_adj = round(float(p_accused) * float(v_val) - (1.0 - float(p_accused)), 6)
    else:
        luck_adj = None
    return {
        "regret_total": round(regret_total, 6),
        "tag_counts": dict(sorted(tag_counts.items())),
        "tag_regret_sum": dict(sorted(tag_regret_sum.items())),
        "p_accused": round(float(p_accused), 4) if p_accused is not None else None,
        "p_top": round(float(p_top), 4) if p_top is not None else None,
        "verdict": verdict,
        "luck_adjusted_score": luck_adj,
    }


def make_default_client(model: str, level: str, run_id: str, meta: dict[str, Any], stub: bool) -> Any:
    if stub:
        inner = StubThinkingClient(model=model, thinking_level=level)
        return LedgeredClient(inner, feature=FEATURE, run_id=run_id, meta=meta)
    return lab_client(f"gemini:{model}", feature=FEATURE, run_id=run_id, meta=meta, thinking_level=level)


def scratch_cell_path(run_name: str, model: str, level: str, tier: str, seed: int) -> Path:
    return ROOT / "data" / "gemini" / "scratch" / run_name / f"{model}-{level}-{tier}-{seed}.json"


def save_scratch_cell(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "level": record["level"],
        "seed": record["seed"],
        "run_id": record["run_id"],
        "result": strip_special_dashes(dataclasses.asdict(record["result"])),
        "transcript": record["transcript"],
        "usage": record["usage"],
        "provider_settings": record["provider_settings"],
        "finish_reasons": record["finish_reasons"],
        "analysis": record["analysis"],
    }
    path.write_text(json.dumps(nan_to_none(payload), indent=1, allow_nan=False) + "\n")


def load_scratch_cell(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        rd = dict(raw["result"])
        rd["steps"] = [Step(**s) for s in rd.get("steps", [])]
        res = EpisodeResult(**rd)
        if res.end_reason == "error":
            return None
        return {
            "level": raw["level"],
            "seed": int(raw["seed"]),
            "run_id": raw["run_id"],
            "result": res,
            "transcript": raw["transcript"],
            "usage": raw["usage"],
            "provider_settings": raw["provider_settings"],
            "finish_reasons": raw["finish_reasons"],
            "analysis": raw["analysis"],
        }
    except Exception:
        return None


def run_single_cell(
    model: str,
    level: str,
    tier: str,
    seed: int,
    run_name: str,
    stub: bool,
    max_attempts: int,
    resume: bool = False,
    client_factory: Callable[[str, str, str, dict[str, Any], bool], Any] | None = None,
) -> dict[str, Any]:
    scratch_file = scratch_cell_path(run_name, model, level, tier, seed)
    if resume and not stub:
        cached_rec = load_scratch_cell(scratch_file)
        if cached_rec is not None:
            print(
                f"[{time.strftime('%H:%M:%S')}] resumed cached cell level={level} seed={seed} "
                f"score={cached_rec['result'].score:.3f}",
                flush=True,
            )
            return cached_rec
    factory = client_factory or make_default_client
    prefix = "stub" if stub else "gemini"
    agent_name = f"{prefix}:{model}+think:{level}"
    spec_for_policy = "stub" if stub else f"gemini:{model}"
    run_id = f"ladder:{run_name}:{model}/{level}/{tier}/{seed}"
    call_meta = {
        "role": "investigators",
        "subrole": "thinking_level_ablation",
        "ladder_run": run_name,
        "model": model,
        "thinking_level": level,
        "tier": tier,
        "seed": seed,
        "stub": stub,
    }
    last_record: dict[str, Any] | None = None
    for attempt in range(max(1, max_attempts)):
        env = Env(tier=tier, seed=seed)
        inner_client = factory(model, level, run_id, call_meta, stub)
        tally = TallyClient(inner_client, model=model)
        pol = LLMPolicy(spec_for_policy, client=tally, context="full")
        t0 = time.perf_counter()
        try:
            res = run_agent_episode(env, pol, agent_name)
        except Exception as exc:
            res = env.result(agent_name)
            res.end_reason = "error"
            res.meta = {**(res.meta or {}), "error": f"{type(exc).__name__}: {exc}"}
        wall_s = time.perf_counter() - t0
        u = tally.usage_dict(wall_s)
        prov_settings = tally.settings() if hasattr(tally, "settings") else {"thinking_level": level}
        finish_reasons = dict(getattr(tally, "finish_reasons", {}) or {})
        analysis = analyze_episode(res)
        res.meta = {
            **(res.meta or {}),
            "role": "investigators",
            "subrole": "thinking_level_ablation",
            "model_id": model,
            "thinking_level": level,
            "stub": stub,
            "run_id": run_id,
            "attempt": attempt + 1,
            "usage": u,
            "provider_settings": prov_settings,
            "finish_reasons": finish_reasons,
            "regret": analysis,
        }
        last_record = {
            "level": level,
            "seed": seed,
            "run_id": run_id,
            "result": res,
            "transcript": clean_transcript(pol.transcript),
            "usage": u,
            "provider_settings": prov_settings,
            "finish_reasons": finish_reasons,
            "analysis": analysis,
        }
        if res.end_reason != "error":
            if not stub:
                save_scratch_cell(scratch_file, last_record)
                print(
                    f"[{time.strftime('%H:%M:%S')}] cell done level={level} seed={seed} "
                    f"score={res.score:.3f} correct={res.correct} accused={res.accused} "
                    f"day={res.final_day} calls={u['calls']} thinking={u['thinking']} wall={u['wall_s']:.1f}s",
                    flush=True,
                )
            break
        if attempt + 1 < max_attempts and not stub:
            print(
                f"[{time.strftime('%H:%M:%S')}] retrying cell level={level} seed={seed} attempt={attempt + 2}",
                flush=True,
            )
            time.sleep(min(30.0, 5.0 * (attempt + 1)))
    assert last_record is not None
    return last_record


def run_solver_baseline(tier: str, seeds: list[int]) -> dict[str, Any]:
    per_seed: dict[str, Any] = {}
    scores: list[float] = []
    accuse_days: list[int] = []
    correct_count = 0
    regret_total = 0.0
    tag_counts: Counter[str] = Counter()
    for seed in seeds:
        ep = run_eval_episode(Env(tier=tier, seed=seed), SolverPolicy())
        ep.agent = "solver"
        analysis = analyze_episode(ep)
        scores.append(float(ep.score))
        if ep.correct:
            correct_count += 1
        if ep.end_reason == "accused":
            accuse_days.append(int(ep.final_day))
        regret_total += analysis["regret_total"]
        for t, cnt in analysis["tag_counts"].items():
            tag_counts[t] += cnt
        per_seed[str(seed)] = {
            "seed": seed,
            "score": round(float(ep.score), 6),
            "correct": bool(ep.correct),
            "accused": ep.accused,
            "final_day": int(ep.final_day),
            "end_reason": ep.end_reason,
            "steps": len(ep.steps),
            "p_accused": analysis["p_accused"],
            "luck_adjusted_score": analysis["luck_adjusted_score"],
            "regret_total": analysis["regret_total"],
            "tag_counts": analysis["tag_counts"],
        }
    m, ci = mean_ci(scores)
    n = len(seeds)
    return {
        "agent": "solver",
        "tier": tier,
        "seeds": list(seeds),
        "n": n,
        "mean_score": round(m, 6),
        "score_ci95": round(ci, 6),
        "accuracy": round(correct_count / n, 6) if n else 0.0,
        "mean_accuse_day": round(sum(accuse_days) / len(accuse_days), 4) if accuse_days else None,
        "regret_total": round(regret_total, 6),
        "regret_per_episode": round(regret_total / n, 6) if n else 0.0,
        "tag_counts": dict(sorted(tag_counts.items())),
        "per_seed": per_seed,
    }


def summarize_level(
    level: str,
    records: list[dict[str, Any]],
    solver_baseline: dict[str, Any],
    model: str,
    tier: str,
    stub: bool,
) -> dict[str, Any]:
    records_sorted = sorted(records, key=lambda r: r["seed"])
    n = len(records_sorted)
    scores = [float(r["result"].score) for r in records_sorted]
    m, ci = mean_ci(scores)
    solver_scores = [float(solver_baseline["per_seed"][str(r["seed"])]["score"]) for r in records_sorted]
    diffs = [a - b for a, b in zip(scores, solver_scores)]
    diff_m, diff_ci = mean_ci(diffs)
    solver_m = float(solver_baseline["mean_score"])
    ratio = (m / solver_m) if solver_m > 0 else None

    accused_eps = [r for r in records_sorted if r["result"].accused]
    p_vals = [r["analysis"]["p_accused"] for r in accused_eps if r["analysis"]["p_accused"] is not None]
    luck_vals = [r["analysis"]["luck_adjusted_score"] for r in records_sorted
                 if r["analysis"]["luck_adjusted_score"] is not None]

    calls_total = sum(int(r["usage"]["calls"]) for r in records_sorted)
    in_total = sum(int(r["usage"]["in"]) for r in records_sorted)
    out_total = sum(int(r["usage"]["out"]) for r in records_sorted)
    think_total = sum(int(r["usage"]["thinking"]) for r in records_sorted)
    cached_total = sum(int(r["usage"]["cached"]) for r in records_sorted)
    lat_total = sum(float(r["usage"]["latency_s"]) for r in records_sorted)
    wall_total = sum(float(r["usage"]["wall_s"]) for r in records_sorted)
    max_call_s = max((float(r["usage"]["max_call_s"]) for r in records_sorted), default=0.0)
    cost_total = sum(float(r["usage"]["cost_usd"]) for r in records_sorted)
    cost_est_total = sum(float(r["usage"]["cost_usd_est"]) for r in records_sorted)

    regret_total = sum(float(r["analysis"]["regret_total"]) for r in records_sorted)
    tag_counts: Counter[str] = Counter()
    tag_episodes_with: Counter[str] = Counter()
    tag_regret_sum: dict[str, float] = {}
    per_seed: dict[str, Any] = {}

    for r in records_sorted:
        s = r["seed"]
        res = r["result"]
        an = r["analysis"]
        u = r["usage"]
        sol_score = float(solver_baseline["per_seed"][str(s)]["score"])
        for tag, cnt in an["tag_counts"].items():
            tag_counts[tag] += cnt
            if cnt > 0:
                tag_episodes_with[tag] += 1
        for tag, rsum in an["tag_regret_sum"].items():
            tag_regret_sum[tag] = round(tag_regret_sum.get(tag, 0.0) + float(rsum), 6)
        per_seed[str(s)] = {
            "seed": s,
            "score": round(float(res.score), 6),
            "solver_score": round(sol_score, 6),
            "score_minus_solver": round(float(res.score) - sol_score, 6),
            "correct": bool(res.correct),
            "accused": res.accused,
            "final_day": int(res.final_day),
            "end_reason": res.end_reason,
            "steps": len(res.steps),
            "p_accused": an["p_accused"],
            "verdict": an["verdict"],
            "luck_adjusted_score": an["luck_adjusted_score"],
            "calls": u["calls"],
            "in_tokens": u["in"],
            "out_tokens": u["out"],
            "thinking_tokens": u["thinking"],
            "cached_tokens": u["cached"],
            "latency_s": u["latency_s"],
            "mean_call_s": u["mean_call_s"],
            "max_call_s": u["max_call_s"],
            "wall_s": u["wall_s"],
            "cost_usd": u["cost_usd"],
            "cost_usd_est": u["cost_usd_est"],
            "regret_total": an["regret_total"],
            "tag_counts": an["tag_counts"],
            "run_id": r["run_id"],
        }

    usage_summary = {
        "episodes": n,
        "calls": calls_total,
        "calls_per_episode": round(calls_total / n, 4) if n else 0.0,
        "in": in_total,
        "in_per_episode": round(in_total / n, 2) if n else 0.0,
        "out": out_total,
        "out_per_episode": round(out_total / n, 2) if n else 0.0,
        "thinking": think_total,
        "thinking_per_episode": round(think_total / n, 2) if n else 0.0,
        "cached": cached_total,
        "cached_per_episode": round(cached_total / n, 2) if n else 0.0,
        "out_incl_thinking": out_total + think_total,
        "latency_s": round(lat_total, 3),
        "latency_s_per_episode": round(lat_total / n, 3) if n else 0.0,
        "mean_call_s": round(lat_total / calls_total, 3) if calls_total else 0.0,
        "max_call_s": round(max_call_s, 3),
        "wall_s": round(wall_total, 3),
        "wall_s_per_episode": round(wall_total / n, 3) if n else 0.0,
        "cost_usd": round(cost_total, 6),
        "cost_usd_est": round(cost_est_total, 6),
        "cost_usd_est_per_episode": round(cost_est_total / n, 6) if n else 0.0,
    }

    prov_settings = records_sorted[0]["provider_settings"] if records_sorted else {"thinking_level": level}
    return {
        "model_id": model,
        "thinking_level": level,
        "tier": tier,
        "stub": stub,
        "n": n,
        "seeds": [r["seed"] for r in records_sorted],
        "mean_score": round(m, 6),
        "score_ci95": round(ci, 6),
        "accuracy": round(sum(1 for r in records_sorted if r["result"].correct) / n, 6) if n else 0.0,
        "accused_rate": round(len(accused_eps) / n, 6) if n else 0.0,
        "mean_accuse_day": round(sum(int(r["result"].final_day) for r in accused_eps) / len(accused_eps), 4)
        if accused_eps else None,
        "solver_mean_score": round(solver_m, 6),
        "score_to_solver_ratio": round(ratio, 6) if ratio is not None else None,
        "paired_diff_vs_solver_mean": round(diff_m, 6),
        "paired_diff_vs_solver_ci95": round(diff_ci, 6),
        "mean_p_accused": round(sum(p_vals) / len(p_vals), 4) if p_vals else None,
        "luck_adjusted_score_mean": round(sum(luck_vals) / len(luck_vals), 6) if luck_vals else None,
        "thinking_tokens_total": think_total,
        "thinking_tokens_per_episode": usage_summary["thinking_per_episode"],
        "latency_s_total": usage_summary["latency_s"],
        "latency_s_per_episode": usage_summary["latency_s_per_episode"],
        "mean_call_latency_s": usage_summary["mean_call_s"],
        "max_call_latency_s": usage_summary["max_call_s"],
        "calls_total": calls_total,
        "calls_per_episode": usage_summary["calls_per_episode"],
        "cost_usd_est_total": usage_summary["cost_usd_est"],
        "cost_usd_est_per_episode": usage_summary["cost_usd_est_per_episode"],
        "regret_total": round(regret_total, 6),
        "regret_per_episode": round(regret_total / n, 6) if n else 0.0,
        "tag_counts": dict(sorted(tag_counts.items())),
        "tag_episodes_with": dict(sorted(tag_episodes_with.items())),
        "tag_regret_sum": dict(sorted(tag_regret_sum.items())),
        "usage": usage_summary,
        "provider_settings": prov_settings,
        "per_seed": per_seed,
    }


def write_level_dir(
    out: Path,
    level: str,
    records: list[dict[str, Any]],
    level_summary: dict[str, Any],
    commit_sha: str,
    timestamp: str,
) -> None:
    level_dir = out / level
    ep_file = level_dir / "episodes.jsonl"
    if ep_file.exists():
        ep_file.unlink()
    stale_meta = level_dir / "meta.json"
    if stale_meta.exists():
        stale_meta.unlink()
    writer = RunWriter(level_dir)
    records_sorted = sorted(records, key=lambda r: r["seed"])
    for r in records_sorted:
        ep_dict = strip_special_dashes(dataclasses.asdict(r["result"]))
        writer.episode(ep_dict)
        writer.transcript(r["seed"], r["transcript"])
    prefix = "stub" if level_summary["stub"] else "gemini"
    level_meta = nan_to_none({
        "role": "investigators",
        "subrole": "thinking_level_ablation",
        "agent": f"{prefix}:{level_summary['model_id']}+think:{level}",
        "model": level_summary["model_id"],
        "model_id": level_summary["model_id"],
        "provider": prefix,
        "thinking_level": level,
        "stub": level_summary["stub"],
        "tiers_version": TIERS_VERSION,
        "tier": level_summary["tier"],
        "seeds": level_summary["seeds"],
        "n_episodes": level_summary["n"],
        "git_sha": commit_sha,
        "commit": commit_sha,
        "timestamp": timestamp,
        "provider_settings": level_summary["provider_settings"],
        "usage": level_summary["usage"],
        "summary": {
            "mean_score": level_summary["mean_score"],
            "accuracy": level_summary["accuracy"],
            "solver_mean_score": level_summary["solver_mean_score"],
            "score_to_solver_ratio": level_summary["score_to_solver_ratio"],
            "regret_total": level_summary["regret_total"],
            "regret_per_episode": level_summary["regret_per_episode"],
            "tag_counts": level_summary["tag_counts"],
        },
    })
    (level_dir / "level_meta.json").write_text(json.dumps(level_meta, indent=2, allow_nan=False) + "\n")


def build_comparison(
    model: str,
    stub: bool,
    tier: str,
    seeds: list[int],
    levels: list[str],
    commit_sha: str,
    timestamp: str,
    solver_baseline: dict[str, Any],
    levels_summary: dict[str, Any],
) -> dict[str, Any]:
    paired_by_seed: list[dict[str, Any]] = []
    for s in seeds:
        sk = str(s)
        row: dict[str, Any] = {
            "seed": s,
            "solver": solver_baseline["per_seed"][sk],
            "levels": {lv: levels_summary[lv]["per_seed"][sk] for lv in levels},
        }
        if "low" in levels_summary and "high" in levels_summary:
            lo = levels_summary["low"]["per_seed"][sk]
            hi = levels_summary["high"]["per_seed"][sk]
            lo_th = int(lo["thinking_tokens"])
            hi_th = int(hi["thinking_tokens"])
            row["high_minus_low"] = {
                "score_delta": round(float(hi["score"]) - float(lo["score"]), 6),
                "thinking_tokens_delta": hi_th - lo_th,
                "thinking_tokens_multiplier": round(hi_th / lo_th, 4) if lo_th > 0 else None,
                "calls_delta": int(hi["calls"]) - int(lo["calls"]),
                "latency_s_delta": round(float(hi["latency_s"]) - float(lo["latency_s"]), 3),
                "wall_s_delta": round(float(hi["wall_s"]) - float(lo["wall_s"]), 3),
                "cost_usd_est_delta": round(float(hi["cost_usd_est"]) - float(lo["cost_usd_est"]), 6),
                "regret_delta": round(float(hi["regret_total"]) - float(lo["regret_total"]), 6),
            }
        paired_by_seed.append(row)

    delta_hl: dict[str, Any] | None = None
    if "low" in levels_summary and "high" in levels_summary:
        lo_s = levels_summary["low"]
        hi_s = levels_summary["high"]
        all_tags = sorted(set(lo_s["tag_counts"]) | set(hi_s["tag_counts"]))
        lo_th_ep = float(lo_s["thinking_tokens_per_episode"])
        hi_th_ep = float(hi_s["thinking_tokens_per_episode"])
        lo_ratio = lo_s["score_to_solver_ratio"]
        hi_ratio = hi_s["score_to_solver_ratio"]
        lo_luck = lo_s["luck_adjusted_score_mean"]
        hi_luck = hi_s["luck_adjusted_score_mean"]
        delta_hl = {
            "mean_score_delta": round(float(hi_s["mean_score"]) - float(lo_s["mean_score"]), 6),
            "accuracy_delta": round(float(hi_s["accuracy"]) - float(lo_s["accuracy"]), 6),
            "score_to_solver_ratio_delta": round(float(hi_ratio) - float(lo_ratio), 6)
            if (lo_ratio is not None and hi_ratio is not None) else None,
            "luck_adjusted_score_delta": round(float(hi_luck) - float(lo_luck), 6)
            if (lo_luck is not None and hi_luck is not None) else None,
            "thinking_tokens_per_episode_delta": round(hi_th_ep - lo_th_ep, 2),
            "thinking_tokens_multiplier": round(hi_th_ep / lo_th_ep, 4) if lo_th_ep > 0 else None,
            "calls_per_episode_delta": round(float(hi_s["calls_per_episode"]) - float(lo_s["calls_per_episode"]), 4),
            "latency_s_per_episode_delta": round(
                float(hi_s["latency_s_per_episode"]) - float(lo_s["latency_s_per_episode"]), 3
            ),
            "mean_call_latency_s_delta": round(
                float(hi_s["mean_call_latency_s"]) - float(lo_s["mean_call_latency_s"]), 3
            ),
            "cost_usd_est_per_episode_delta": round(
                float(hi_s["cost_usd_est_per_episode"]) - float(lo_s["cost_usd_est_per_episode"]), 6
            ),
            "regret_per_episode_delta": round(
                float(hi_s["regret_per_episode"]) - float(lo_s["regret_per_episode"]), 6
            ),
            "tag_count_deltas": {
                t: int(hi_s["tag_counts"].get(t, 0)) - int(lo_s["tag_counts"].get(t, 0))
                for t in all_tags
            },
            "tag_regret_sum_deltas": {
                t: round(float(hi_s["tag_regret_sum"].get(t, 0.0)) - float(lo_s["tag_regret_sum"].get(t, 0.0)), 6)
                for t in all_tags
            },
        }

    return nan_to_none({
        "role": "investigators",
        "subrole": "thinking_level_ablation",
        "model_id": model,
        "stub": stub,
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seeds": list(seeds),
        "levels": list(levels),
        "commit": commit_sha,
        "timestamp": timestamp,
        "solver_baseline": solver_baseline,
        "levels_summary": levels_summary,
        "paired_by_seed": paired_by_seed,
        "delta_high_vs_low": delta_hl,
    })


def fmt_num(val: Any, nd: int = 3, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "-"
    if signed:
        return f"{float(val):+.{nd}f}"
    return f"{float(val):.{nd}f}"


def render_summary_md(meta: dict[str, Any], comparison: dict[str, Any]) -> str:
    solver = comparison["solver_baseline"]
    levels = comparison["levels"]
    lsum = comparison["levels_summary"]
    seeds_str = ", ".join(str(s) for s in meta["seeds"])
    mode_str = "stub (offline keyless test)" if meta["stub"] else "live Gemini API"
    lines = [
        f"# Gemini Thinking-Level Experiment: {meta['model_id']} ({' vs '.join(levels)})",
        "",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}` ({mode_str})",
        f"- Canary tiers version: `{meta['tiers_version']}`, tier: `{meta['tier']}`, paired dev seeds: `{seeds_str}`",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        "",
        "## Aggregate Performance vs Paired SolverPolicy",
        "",
        "| policy / level | n | mean score | accuracy | accused | mean day | score / solver | diff vs solver | mean P(accused) | luck-adj score | thinking tok/ep | out tok/ep | calls/ep | API latency s/ep | s/call | est $/ep | regret/ep |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        (
            f"| SolverPolicy (reference) | {solver['n']} | {fmt_num(solver['mean_score'], 3, True)} | "
            f"{fmt_num(solver['accuracy'], 2)} | 1.00 | {fmt_num(solver['mean_accuse_day'], 1)} | 100.0% | "
            f"+0.000 | 1.00 | {fmt_num(solver['mean_score'], 3, True)} | 0 | 0 | 0.0 | 0.0 | 0.00 | $0.0000 | "
            f"{fmt_num(solver['regret_per_episode'], 3)} |"
        ),
    ]
    for lv in levels:
        s = lsum[lv]
        u = s["usage"]
        ratio_str = f"{float(s['score_to_solver_ratio']) * 100:.1f}%" if s["score_to_solver_ratio"] is not None else "-"
        lines.append(
            f"| {meta['model_id']} (thinking={lv}) | {s['n']} | {fmt_num(s['mean_score'], 3, True)} | "
            f"{fmt_num(s['accuracy'], 2)} | {fmt_num(s['accused_rate'], 2)} | {fmt_num(s['mean_accuse_day'], 1)} | "
            f"{ratio_str} | {fmt_num(s['paired_diff_vs_solver_mean'], 3, True)} | {fmt_num(s['mean_p_accused'], 2)} | "
            f"{fmt_num(s['luck_adjusted_score_mean'], 3, True)} | {u['thinking_per_episode']:,.0f} | "
            f"{u['out_per_episode']:,.0f} | {fmt_num(u['calls_per_episode'], 1)} | "
            f"{fmt_num(u['latency_s_per_episode'], 1)} | {fmt_num(u['mean_call_s'], 2)} | "
            f"${u['cost_usd_est_per_episode']:.4f} | {fmt_num(s['regret_per_episode'], 3)} |"
        )

    lines += [
        "",
        "## Paired Seed-by-Seed Breakdown",
        "",
        "| seed | policy / level | score | solver score | score - solver | correct | accused | day | P(accused) | thinking tok | calls | latency s | est $ | regret | tags |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in comparison["paired_by_seed"]:
        seed = row["seed"]
        sol = row["solver"]
        sol_tags = ", ".join(f"{k}:{v}" for k, v in sol["tag_counts"].items()) or "none"
        lines.append(
            f"| {seed} | SolverPolicy | {fmt_num(sol['score'], 3, True)} | {fmt_num(sol['score'], 3, True)} | "
            f"+0.000 | {sol['correct']} | {sol['accused'] or '-'} | {sol['final_day']} | "
            f"{fmt_num(sol['p_accused'], 2)} | 0 | 0 | 0.0 | $0.0000 | {fmt_num(sol['regret_total'], 3)} | {sol_tags} |"
        )
        for lv in levels:
            ep = row["levels"][lv]
            tag_str = ", ".join(f"{k}:{v}" for k, v in ep["tag_counts"].items()) or "none"
            lines.append(
                f"| {seed} | thinking={lv} | {fmt_num(ep['score'], 3, True)} | {fmt_num(ep['solver_score'], 3, True)} | "
                f"{fmt_num(ep['score_minus_solver'], 3, True)} | {ep['correct']} | {ep['accused'] or '-'} | "
                f"{ep['final_day']} | {fmt_num(ep['p_accused'], 2)} | {ep['thinking_tokens']:,} | {ep['calls']} | "
                f"{fmt_num(ep['latency_s'], 1)} | ${ep['cost_usd_est']:.4f} | {fmt_num(ep['regret_total'], 3)} | {tag_str} |"
            )

    all_tags = sorted({t for lv in levels for t in lsum[lv]["tag_counts"]} | set(solver["tag_counts"]))
    lines += [
        "",
        "## Solver Regret Attribution by Tag (`canary.solver.regret.attribute`)",
        "",
        "| tag | solver count | " + " | ".join(f"{lv} count (regret sum)" for lv in levels) +
        (" | high - low count (regret delta) |" if comparison.get("delta_high_vs_low") else " |"),
        "|---|---|" + "---|" * len(levels) + ("---|" if comparison.get("delta_high_vs_low") else ""),
    ]
    if all_tags:
        d_hl = comparison.get("delta_high_vs_low")
        for t in all_tags:
            cells = [
                f"{lsum[lv]['tag_counts'].get(t, 0)} ({fmt_num(lsum[lv]['tag_regret_sum'].get(t, 0.0), 3)})"
                for lv in levels
            ]
            row_str = f"| `{t}` | {solver['tag_counts'].get(t, 0)} | " + " | ".join(cells)
            if d_hl:
                dc = d_hl["tag_count_deltas"].get(t, 0)
                dr = d_hl["tag_regret_sum_deltas"].get(t, 0.0)
                row_str += f" | {dc:+d} ({fmt_num(dr, 3, True)}) |"
            else:
                row_str += " |"
            lines.append(row_str)
    else:
        lines.append("| (none) | 0 | " + " | ".join("0 (0.000)" for _ in levels) +
                     (" | +0 (+0.000) |" if comparison.get("delta_high_vs_low") else " |"))

    if comparison.get("delta_high_vs_low"):
        d = comparison["delta_high_vs_low"]
        mult_str = f"{d['thinking_tokens_multiplier']:.2f}x" if d["thinking_tokens_multiplier"] is not None else "n/a"
        lines += [
            "",
            "## High vs Low Thinking Summary",
            "",
            f"- Mean score delta (`high - low`): `{fmt_num(d['mean_score_delta'], 3, True)}` "
            f"(accuracy delta `{fmt_num(d['accuracy_delta'], 2, True)}`, solver-ratio delta "
            f"`{fmt_num(d['score_to_solver_ratio_delta'], 3, True)}`)",
            f"- Thinking tokens per episode: `{lsum['low']['thinking_tokens_per_episode']:,.0f}` (`low`) vs "
            f"`{lsum['high']['thinking_tokens_per_episode']:,.0f}` (`high`), multiplier `{mult_str}` "
            f"(`{d['thinking_tokens_per_episode_delta']:+,.0f}` tokens/ep)",
            f"- API latency per episode: `{fmt_num(lsum['low']['latency_s_per_episode'], 1)}s` (`low`) vs "
            f"`{fmt_num(lsum['high']['latency_s_per_episode'], 1)}s` (`high`), delta "
            f"`{fmt_num(d['latency_s_per_episode_delta'], 1, True)}s`",
            f"- Solver regret per episode (`canary.solver.regret.attribute`): "
            f"`{fmt_num(lsum['low']['regret_per_episode'], 3)}` (`low`) vs "
            f"`{fmt_num(lsum['high']['regret_per_episode'], 3)}` (`high`), delta "
            f"`{fmt_num(d['regret_per_episode_delta'], 3, True)}`",
            f"- Total experiment usage: `{meta['usage']['calls']}` calls, `{meta['usage']['thinking']:,}` thinking tokens, "
            f"`{meta['usage']['in']:,}` input tokens, `{meta['usage']['cached']:,}` cached tokens, "
            f"estimated list cost `${meta['usage']['cost_usd_est']:.4f}`",
        ]
    lines.append("")
    return "\n".join(lines)


def run_experiment(
    out: Path,
    model: str = DEFAULT_MODEL,
    levels: list[str] | None = None,
    tier: str = "medium",
    seeds: list[int] | None = None,
    stub: bool = False,
    concurrency: int = 1,
    max_attempts: int = 3,
    resume: bool = False,
    command_str: str = "",
    client_factory: Callable[[str, str, str, dict[str, Any], bool], Any] | None = None,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; allowed: {tuple(TIERS)}")
    levels = list(levels or ["low", "high"])
    for lv in levels:
        if lv not in THINKING_LEVELS:
            raise ValueError(f"unknown level {lv!r}")
    seeds = list(seeds if seeds is not None else [0, 1])
    guard_output_dir(out)
    out.mkdir(parents=True, exist_ok=True)

    temp_ledger_path: str | None = None
    prev_ledger = os.environ.get("CANARY_GEMINI_LEDGER")
    if stub and not prev_ledger:
        fd, temp_ledger_path = tempfile.mkstemp(prefix="canary_stub_ledger_", suffix=".jsonl")
        os.close(fd)
        os.environ["CANARY_GEMINI_LEDGER"] = temp_ledger_path

    try:
        if not stub:
            os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "12")
        run_name = out.name or "thinking-ladder-carbon-med01"
        tasks = [(lv, s) for lv in levels for s in seeds]
        by_level: dict[str, list[dict[str, Any]]] = {lv: [] for lv in levels}

        if concurrency <= 1 or len(tasks) <= 1:
            for lv, s in tasks:
                rec = run_single_cell(
                    model=model,
                    level=lv,
                    tier=tier,
                    seed=s,
                    run_name=run_name,
                    stub=stub,
                    max_attempts=1 if stub else max_attempts,
                    resume=resume,
                    client_factory=client_factory,
                )
                by_level[lv].append(rec)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                fut_map = {
                    pool.submit(
                        run_single_cell,
                        model,
                        lv,
                        tier,
                        s,
                        run_name,
                        stub,
                        1 if stub else max_attempts,
                        resume,
                        client_factory,
                    ): (lv, s)
                    for lv, s in tasks
                }
                for fut in as_completed(fut_map):
                    rec = fut.result()
                    by_level[rec["level"]].append(rec)

        solver_baseline = run_solver_baseline(tier=tier, seeds=seeds)
        commit_sha = git_sha()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")

        levels_summary: dict[str, Any] = {}
        all_records: list[dict[str, Any]] = []
        for lv in levels:
            recs = sorted(by_level[lv], key=lambda r: r["seed"])
            all_records.extend(recs)
            lsum = summarize_level(
                level=lv,
                records=recs,
                solver_baseline=solver_baseline,
                model=model,
                tier=tier,
                stub=stub,
            )
            levels_summary[lv] = lsum
            write_level_dir(out, lv, recs, lsum, commit_sha, timestamp)

        total_calls = sum(int(r["usage"]["calls"]) for r in all_records)
        total_in = sum(int(r["usage"]["in"]) for r in all_records)
        total_out = sum(int(r["usage"]["out"]) for r in all_records)
        total_think = sum(int(r["usage"]["thinking"]) for r in all_records)
        total_cached = sum(int(r["usage"]["cached"]) for r in all_records)
        total_lat = sum(float(r["usage"]["latency_s"]) for r in all_records)
        total_wall = sum(float(r["usage"]["wall_s"]) for r in all_records)
        total_cost = sum(float(r["usage"]["cost_usd"]) for r in all_records)
        total_cost_est = sum(float(r["usage"]["cost_usd_est"]) for r in all_records)
        api_versions = sorted({mv for r in all_records for mv in r["usage"].get("model_versions", []) if mv})

        usage_agg = {
            "episodes": len(all_records),
            "calls": total_calls,
            "in": total_in,
            "out": total_out,
            "thinking": total_think,
            "cached": total_cached,
            "out_incl_thinking": total_out + total_think,
            "in_tokens": total_in,
            "out_tokens": total_out,
            "thinking_tokens": total_think,
            "cached_tokens": total_cached,
            "latency_s": round(total_lat, 3),
            "wall_s": round(total_wall, 3),
            "cost_usd": round(total_cost, 6),
            "cost_usd_est": round(total_cost_est, 6),
        }

        meta = nan_to_none({
            "role": "investigators",
            "subrole": "thinking_level_ablation",
            "model_id": model,
            "provider": "stub" if stub else "gemini",
            "stub": stub,
            "api_model_versions": api_versions,
            "tiers_version": TIERS_VERSION,
            "tier": tier,
            "seeds": list(seeds),
            "levels": list(levels),
            "n_episodes": len(all_records),
            "commit": commit_sha,
            "timestamp": timestamp,
            "command": command_str,
            "ledger_feature": FEATURE,
            "ledger_run_ids": [r["run_id"] for r in all_records],
            "usage": usage_agg,
            "solver_baseline": solver_baseline,
            "levels_summary": levels_summary,
        })

        comparison = build_comparison(
            model=model,
            stub=stub,
            tier=tier,
            seeds=seeds,
            levels=levels,
            commit_sha=commit_sha,
            timestamp=timestamp,
            solver_baseline=solver_baseline,
            levels_summary=levels_summary,
        )
        summary_md = render_summary_md(meta, comparison)

        (out / "meta.json").write_text(json.dumps(meta, indent=2, allow_nan=False) + "\n")
        (out / "comparison.json").write_text(json.dumps(comparison, indent=2, allow_nan=False) + "\n")
        (out / "summary.md").write_text(summary_md)
        return meta
    finally:
        if temp_ledger_path is not None:
            if prev_ledger is None:
                os.environ.pop("CANARY_GEMINI_LEDGER", None)
            else:
                os.environ["CANARY_GEMINI_LEDGER"] = prev_ledger
            try:
                os.unlink(temp_ledger_path)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="python scripts/run_carbon_thinking_ladder.py")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--levels", default="low,high")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--stub", action="store_true")
    args = ap.parse_args(raw_argv)

    levels = parse_levels(args.levels)
    seeds = parse_public_seeds(args.seeds)
    out = Path(args.out)
    cmd_parts = ["python", "scripts/run_carbon_thinking_ladder.py", *raw_argv]
    command_str = " ".join(cmd_parts)

    meta = run_experiment(
        out=out,
        model=args.model,
        levels=levels,
        tier=args.tier,
        seeds=seeds,
        stub=bool(args.stub),
        concurrency=max(1, int(args.concurrency)),
        max_attempts=max(1, int(args.max_attempts)),
        resume=bool(args.resume),
        command_str=command_str,
    )
    print(f"wrote {out} (episodes={meta['usage']['episodes']}, calls={meta['usage']['calls']}, "
          f"thinking_tokens={meta['usage']['thinking']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
