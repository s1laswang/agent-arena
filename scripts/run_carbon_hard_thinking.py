from __future__ import annotations

import argparse
import collections
import concurrent.futures
import dataclasses
import hashlib
import json
import math
import os
import shutil
import socket
import sys
import tempfile
import time
import types
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

DEFAULT_OUT = "results/gemini_roles/investigators/thinking-ladder-carbon-hard0"
DEFAULT_MODEL = "gemini-4-carbon"
ROLE = "investigators"
SUBROLE = "hard_thinking_ablation"
HOST = socket.gethostname().split(".")[0]


def shannon_entropy_bits(weights: list[float]) -> float:
    total = sum(w for w in weights if w > 0.0)
    if total <= 0.0:
        return 0.0
    ent = 0.0
    for w in weights:
        if w > 0.0:
            p = w / total
            ent -= p * math.log2(p)
    return ent


class StubGeminiClient:
    def __init__(self, model: str, thinking_level: str, script: list[dict], max_retries: int = 10):
        from canary.llm.stub import StubClient
        self._stub = StubClient(script=script, model=model, max_retries=max_retries)
        self.provider = "gemini"
        self.model = model
        self.max_retries = max_retries
        self.thinking_level = thinking_level
        self.signature_model = True
        self.supports_temperature = False
        self.finish_reasons: dict[str, int] = {}
        self.total_usage: dict[str, Any] = {"in": 0, "out": 0, "cost_usd": 0.0, "calls": 0}

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def settings(self) -> dict:
        return {
            "thinking_level": self.thinking_level,
            "include_thoughts": True,
            "temperature": "not sent (API default 1.0)",
            "thought_signature_replay": True,
            "api": "generateContent",
            "stub": True,
        }

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.0, response_schema: dict | None = None,
             max_tokens: int | None = None, seed: int | None = None):
        from canary.llm.pricing import cost
        resp = self._stub.chat(
            messages,
            tools=tools,
            temperature=temperature,
            response_schema=response_schema,
            max_tokens=max_tokens,
            seed=seed,
        )
        think_tok = 32 if self.thinking_level == "low" else 256
        tin = max(120, int(resp.usage.get("in", 0) or 0))
        tout = max(16, int(resp.usage.get("out", 0) or 0))
        cached = 0 if self.thinking_level == "low" else 40
        um = types.SimpleNamespace(
            prompt_token_count=tin,
            candidates_token_count=tout,
            thoughts_token_count=think_tok,
            cached_content_token_count=cached,
            total_token_count=tin + tout + think_tok,
        )
        resp.raw = types.SimpleNamespace(
            usage_metadata=um,
            model_version=f"stub-{self.model}",
        )
        c = cost(self.model, tin, tout + think_tok, cached)
        resp.usage = {"in": tin, "out": tout + think_tok, **c}
        fake_sig = f"opaque-sig-{self.thinking_level}-" + "s" + "k-" + "0123456789abcdef"
        resp.provider_items = [{
            "role": "model",
            "parts": [
                {"text": f"stub-{self.thinking_level}-thought", "thought": True},
                {"thought_signature": fake_sig},
            ],
        }]
        resp.thoughts = f"stub-{self.thinking_level}-thought"
        self.finish_reasons["FinishReason.STOP"] = self.finish_reasons.get("FinishReason.STOP", 0) + 1
        for k in ("in", "out", "cost_usd"):
            self.total_usage[k] += resp.usage.get(k, 0) or 0
        self.total_usage["calls"] += 1
        return resp


def default_stub_script(level: str) -> list[dict]:
    if level == "low":
        return [
            {"tool_calls": [{"name": "list_employees", "args": {}}]},
            {"tool_calls": [{"name": "status", "args": {}}]},
            {"tool_calls": [{"name": "plant_canary", "args": {
                "doc_title": "Memo draft low",
                "assignment": {"e00": "A", "e01": "A"},
            }}]},
            {"tool_calls": [{"name": "accuse", "args": {"employee": "e00"}}]},
        ]
    return [
        {"tool_calls": [{"name": "list_employees", "args": {}}]},
        {"tool_calls": [{"name": "status", "args": {}}]},
        {"tool_calls": [{"name": "list_documents", "args": {"day_from": 1, "day_to": 1}}]},
        {"tool_calls": [{"name": "plant_canary", "args": {
            "doc_title": "Memo draft high 1",
            "assignment": {"e00": "A", "e01": "B", "e02": "C"},
        }}]},
        {"tool_calls": [{"name": "plant_canary", "args": {
            "doc_title": "Memo draft high 2",
            "assignment": {"e03": "A", "e04": "B", "e05": "C"},
        }}]},
        {"tool_calls": [{"name": "advance_day", "args": {}}]},
        {"tool_calls": [{"name": "check_leak_feed", "args": {}}]},
        {"tool_calls": [{"name": "accuse", "args": {"employee": "e01"}}]},
    ]


class TallyClient:
    def __init__(self, inner: Any, model: str):
        self.inner = inner
        self.model = model
        self.tally: dict[str, Any] = {
            "calls": 0,
            "in": 0,
            "out": 0,
            "thinking": 0,
            "cached": 0,
            "out_incl_thinking": 0,
            "cost_usd": 0.0,
            "cost_usd_est": 0.0,
            "latency_s": 0.0,
            "max_call_s": 0.0,
            "max_thinking_call": 0,
            "per_call_thinking": [],
            "model_version": None,
        }

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages: list[dict], **kw: Any) -> Any:
        from canary.llm.pricing import cost
        t0 = time.time()
        r = self.inner.chat(messages, **kw)
        dt = time.time() - t0
        raw = getattr(r, "raw", None)
        um = getattr(raw, "usage_metadata", None) if raw is not None else None

        def _num(attr: str) -> int:
            v = getattr(um, attr, 0) if um is not None else 0
            return v if isinstance(v, int) else 0

        t = self.tally
        t["calls"] += 1
        t["latency_s"] = round(t["latency_s"] + dt, 3)
        t["max_call_s"] = round(max(t["max_call_s"], dt), 3)
        mv = getattr(raw, "model_version", None) if raw is not None else None
        if mv:
            t["model_version"] = str(mv)
        if um is not None:
            tin = _num("prompt_token_count")
            tout = _num("candidates_token_count")
            think = _num("thoughts_token_count")
            cached = _num("cached_content_token_count")
        else:
            u = getattr(r, "usage", None) or {}
            tin = int(u.get("in", 0) or 0)
            tout = int(u.get("out", 0) or 0)
            think = 0
            cached = int(u.get("cached_in", 0) or 0)
        c = cost(self.model, tin, tout + think, cached)
        usd = float(c.get("cost_usd", 0.0) or 0.0)
        usd_est = float(c.get("cost_usd_est", usd) or usd)
        t["in"] += tin
        t["out"] += tout
        t["thinking"] += think
        t["cached"] += cached
        t["out_incl_thinking"] += tout + think
        t["cost_usd"] = round(t["cost_usd"] + usd, 6)
        t["cost_usd_est"] = round(t["cost_usd_est"] + usd_est, 6)
        t["max_thinking_call"] = max(t["max_thinking_call"], think)
        t["per_call_thinking"].append(think)
        return r


def build_real_client(model: str, level: str, run_id: str, meta: dict,
                      max_retries: int = 10, sdk_client: Any = None):
    from canary.gemini.ledger import lab_client
    kw: dict[str, Any] = {"thinking_level": level, "max_retries": max_retries}
    if sdk_client is not None:
        kw["sdk_client"] = sdk_client
    inner = lab_client(f"gemini:{model}", feature=ROLE, run_id=run_id, meta=meta, **kw)
    return TallyClient(inner, model=model)


def build_stub_client(model: str, level: str, run_id: str, meta: dict,
                      max_retries: int = 10, script: list[dict] | None = None):
    from canary.gemini.ledger import LedgeredClient
    base = StubGeminiClient(
        model=model,
        thinking_level=level,
        script=default_stub_script(level) if script is None else list(script),
        max_retries=max_retries,
    )
    inner = LedgeredClient(base, feature=ROLE, run_id=run_id, meta=meta)
    return TallyClient(inner, model=model)


def read_single_episode(level_dir: Path) -> dict | None:
    ep_file = level_dir / "episodes.jsonl"
    if not ep_file.exists():
        return None
    lines = [json.loads(x) for x in ep_file.read_text().splitlines() if x.strip()]
    return lines[-1] if lines else None


def is_valid_episode(ep: dict | None) -> bool:
    if not ep:
        return False
    if (ep.get("meta") or {}).get("valid") is False:
        return False
    if ep.get("end_reason") == "error":
        return False
    return True


def finalize_tally_summary(tally: dict[str, Any], wall_s: float) -> dict[str, Any]:
    calls = int(tally.get("calls", 0) or 0)
    tin = int(tally.get("in", 0) or 0)
    tout = int(tally.get("out", 0) or 0)
    think = int(tally.get("thinking", 0) or 0)
    cached = int(tally.get("cached", 0) or 0)
    out_total = tout + think
    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": think,
        "cached": cached,
        "out_incl_thinking": out_total,
        "mean_thinking_per_call": round(think / calls, 2) if calls > 0 else 0.0,
        "max_thinking_call": int(tally.get("max_thinking_call", 0) or 0),
        "thinking_share_of_generation": round(think / out_total, 4) if out_total > 0 else 0.0,
        "cost_usd": round(float(tally.get("cost_usd", 0.0) or 0.0), 6),
        "cost_usd_est": round(float(tally.get("cost_usd_est", 0.0) or 0.0), 6),
        "latency_s": round(float(tally.get("latency_s", 0.0) or 0.0), 3),
        "max_call_s": round(float(tally.get("max_call_s", 0.0) or 0.0), 3),
        "wall_s": round(wall_s, 3),
        "model_version": tally.get("model_version"),
    }


def sanitize_transcripts(level_dir: Path) -> None:
    tx_dir = level_dir / "transcripts"
    if not tx_dir.is_dir():
        return
    for tx_file in sorted(tx_dir.glob("*.json")):
        data = json.loads(tx_file.read_text())
        if not isinstance(data, list):
            continue
        changed = False
        for msg in data:
            if not isinstance(msg, dict):
                continue
            items = msg.get("provider_items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                parts = item.get("parts")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if isinstance(part, dict) and isinstance(part.get("thought_signature"), str):
                        sig = part.pop("thought_signature")
                        part["thought_signature_sha256"] = hashlib.sha256(sig.encode("utf-8")).hexdigest()
                        part["thought_signature_len"] = len(sig)
                        changed = True
        if changed:
            tx_file.write_text(json.dumps(data, indent=1, default=str))


def migrate_level_meta(level_dir: Path, commit: str) -> dict[str, Any]:
    legacy = level_dir / "meta.json"
    target = level_dir / "level_meta.json"
    meta: dict[str, Any] = {}
    if target.exists():
        meta.update(json.loads(target.read_text()))
    if legacy.exists():
        meta.update(json.loads(legacy.read_text()))
        legacy.unlink()
    if meta:
        meta["git_sha"] = commit
        meta["commit"] = commit
        target.write_text(json.dumps(meta, indent=1, default=str) + "\n")
    return meta


def run_level_episode(out_dir: Path, model: str, level: str, tier: str, seed: int,
                      stub: bool = False, resume: bool = False, max_retries: int = 10,
                      max_attempts: int = 3, client_builder: Callable | None = None) -> tuple[dict, dict]:
    from canary.agents import play
    from canary.agents.runlog import git_sha
    level_dir = out_dir / level
    run_id = f"hard_thinking_ablation:{model}:{level}:{tier}:{seed}"
    if resume and level_dir.exists():
        existing = read_single_episode(level_dir)
        existing_meta = migrate_level_meta(level_dir, git_sha())
        sanitize_transcripts(level_dir)
        if is_valid_episode(existing) and existing_meta.get("thinking_usage"):
            return existing, existing_meta["thinking_usage"]

    last_err = "unknown error"
    for attempt in range(1, max_attempts + 1):
        if level_dir.exists():
            shutil.rmtree(level_dir)
        level_dir.mkdir(parents=True, exist_ok=True)
        call_meta = {
            "role": ROLE,
            "subrole": SUBROLE,
            "model": model,
            "thinking_level": level,
            "tier": tier,
            "seed": seed,
            "attempt": attempt,
            "stub": stub,
        }
        if client_builder is not None:
            client = client_builder(model, level, run_id, call_meta, max_retries)
        elif stub:
            client = build_stub_client(model, level, run_id, call_meta, max_retries=max_retries)
        else:
            client = build_real_client(model, level, run_id, call_meta, max_retries=max_retries)

        print(f"[hard_thinking] START level={level} attempt={attempt} model={model} tier={tier} seed={seed} stub={stub}", flush=True)
        t0 = time.time()
        play.main(
            ["--agent", f"gemini:{model}", "--tier", tier, "--seeds", str(seed), "--out", str(level_dir)],
            client=client,
        )
        wall_s = time.time() - t0
        ep = read_single_episode(level_dir)
        if is_valid_episode(ep):
            sanitize_transcripts(level_dir)
            usage_summary = finalize_tally_summary(client.tally, wall_s)
            print(
                f"[hard_thinking] DONE level={level} score={ep.get('score')} correct={ep.get('correct')} "
                f"day={ep.get('final_day')} calls={usage_summary['calls']} thinking={usage_summary['thinking']} "
                f"wall={wall_s:.1f}s",
                flush=True,
            )
            usage_summary["run_id"] = run_id
            ep["agent"] = f"gemini:{model}+think:{level}"
            ep.setdefault("meta", {})["thinking_level"] = level
            ep["meta"]["thinking_usage"] = usage_summary
            ep["meta"]["run_id"] = run_id
            ep["meta"]["stub"] = stub
            (level_dir / "episodes.jsonl").write_text(json.dumps(ep, default=str) + "\n")
            commit = git_sha()
            m = migrate_level_meta(level_dir, commit)
            m.update({
                "role": ROLE,
                "subrole": SUBROLE,
                "model_id": model,
                "thinking_level": level,
                "commit": commit,
                "git_sha": commit,
                "run_id": run_id,
                "thinking_usage": usage_summary,
                "wall_s": round(wall_s, 3),
                "host": HOST,
                "stub": stub,
            })
            (level_dir / "level_meta.json").write_text(json.dumps(m, indent=1, default=str) + "\n")
            return ep, usage_summary

        err_msg = (ep.get("meta") or {}).get("error") if ep else "no episode written"
        last_err = f"level={level} attempt={attempt} end_reason={ep.get('end_reason') if ep else None} error={err_msg}"
        if attempt < max_attempts and not stub:
            time.sleep(min(60.0, 15.0 * attempt))

    raise RuntimeError(f"Failed to complete valid episode: {last_err}")


def analyze_canary_partitions(ep_res: Any, params: Any) -> dict[str, Any]:
    from canary.solver.policy import SolverPolicy
    sp = SolverPolicy(params)
    default_emps = [f"e{k:02d}" for k in range(params.n_employees)]
    per_canary: list[dict[str, Any]] = []

    for i, st in enumerate(ep_res.steps):
        for prev in ep_res.steps[sp.seen:i]:
            sp._ingest(prev)
        sp.seen = i
        ok = (st.result or {}).get("ok", True)
        if st.tool != "plant_canary" or not ok:
            continue
        if not sp.obs.employees:
            sp.obs.employees = list(default_emps)
        post = sp.belief()
        asg = dict((st.args or {}).get("assignment") or {})
        var_counts = collections.Counter(asg.values())
        rec_ent = shannon_entropy_bits([float(c) for c in var_counts.values()])

        cell_mass: dict[str, float] = collections.Counter()
        assigned_mass: dict[str, float] = collections.Counter()
        for emp, p in post.items():
            lbl = asg.get(emp, "__none__")
            cell_mass[lbl] += p
            if lbl != "__none__":
                assigned_mass[lbl] += p

        post_ent = shannon_entropy_bits(list(cell_mass.values()))
        assigned_post_ent = shannon_entropy_bits(list(assigned_mass.values()))
        post_gini = 1.0 - sum(m * m for m in cell_mass.values())
        per_canary.append({
            "t": st.t,
            "day": st.day,
            "n_recipients": len(asg),
            "n_variants": len(var_counts),
            "recipient_entropy_bits": round(rec_ent, 4),
            "posterior_entropy_bits": round(post_ent, 4),
            "assigned_posterior_entropy_bits": round(assigned_post_ent, 4),
            "posterior_gini": round(post_gini, 4),
        })

    n_can = len(per_canary)
    if n_can == 0:
        return {
            "canaries_planted": 0,
            "mean_recipients": 0.0,
            "mean_distinct_variants": 0.0,
            "mean_recipient_entropy_bits": 0.0,
            "mean_posterior_entropy_bits": 0.0,
            "mean_assigned_posterior_entropy_bits": 0.0,
            "mean_posterior_gini": 0.0,
            "per_canary": [],
        }

    return {
        "canaries_planted": n_can,
        "mean_recipients": round(sum(x["n_recipients"] for x in per_canary) / n_can, 2),
        "mean_distinct_variants": round(sum(x["n_variants"] for x in per_canary) / n_can, 2),
        "mean_recipient_entropy_bits": round(sum(x["recipient_entropy_bits"] for x in per_canary) / n_can, 4),
        "mean_posterior_entropy_bits": round(sum(x["posterior_entropy_bits"] for x in per_canary) / n_can, 4),
        "mean_assigned_posterior_entropy_bits": round(
            sum(x["assigned_posterior_entropy_bits"] for x in per_canary) / n_can, 4
        ),
        "mean_posterior_gini": round(sum(x["posterior_gini"] for x in per_canary) / n_can, 4),
        "per_canary": per_canary,
    }


def analyze_accusation_calibration(ep_res: Any, params: Any) -> dict[str, Any]:
    from canary.analysis.accuse import audit_episode
    from canary.solver.policy import SolverPolicy

    audit = audit_episode(ep_res)
    sp = SolverPolicy(params)
    default_emps = [f"e{k:02d}" for k in range(params.n_employees)]
    target_idx = len(ep_res.steps)
    accused_emp = ep_res.accused
    accuse_day = ep_res.final_day
    for i, st in enumerate(ep_res.steps):
        if st.tool == "accuse":
            target_idx = i
            accused_emp = (st.args or {}).get("employee", accused_emp)
            accuse_day = st.day
            break
    for prev in ep_res.steps[:target_idx]:
        sp._ingest(prev)
    sp.seen = target_idx
    if not sp.obs.employees:
        sp.obs.employees = list(default_emps)
    post = sp.belief()
    post_ent = shannon_entropy_bits(list(post.values()))
    sum_sq = sum(p * p for p in post.values())
    neff = (1.0 / sum_sq) if sum_sq > 0.0 else float(params.n_employees)
    p_top = max(post.values()) if post else 0.0
    v_true = float((ep_res.meta or {}).get("V", max(0.0, ep_res.score)))

    if accused_emp is not None:
        p_acc = float(post.get(accused_emp, 0.0))
        y = 1.0 if ep_res.correct else 0.0
        brier = (y - p_acc) ** 2
        luck_adj = p_acc * v_true + (1.0 - p_acc) * float(params.wrong_accusation_score)
        verdict = (
            audit["verdict"]
            if audit.get("p_accused") is not None
            else ("justified" if p_acc >= 0.6 else "lucky" if ep_res.correct else "premature-wrong")
        )
        p_acc_out: float | None = round(p_acc, 4)
        brier_out: float | None = round(brier, 4)
    else:
        p_acc_out = None
        brier_out = None
        luck_adj = 0.0
        verdict = "none"

    return {
        "accused": accused_emp,
        "correct": bool(ep_res.correct),
        "day": accuse_day,
        "p_accused": p_acc_out,
        "p_top": round(p_top, 4),
        "audit_p_accused": audit.get("p_accused"),
        "audit_p_top": audit.get("p_top"),
        "verdict": verdict,
        "posterior_entropy_bits": round(post_ent, 4),
        "effective_suspects": round(neff, 2),
        "brier_score": brier_out,
        "true_V_at_end": round(v_true, 4),
        "luck_adjusted_score": round(luck_adj, 4),
    }


def analyze_regret(ep_res: Any) -> dict[str, Any]:
    from canary.solver.regret import attribute
    items = attribute(ep_res)
    tag_counts: dict[str, int] = collections.Counter()
    tag_regret_sums: dict[str, float] = collections.Counter()
    total_regret = 0.0
    for item in items:
        reg = float(item.get("regret", 0.0) or 0.0)
        total_regret += reg
        for tg in item.get("tags") or []:
            tag_counts[tg] += 1
            tag_regret_sums[tg] += reg
    return {
        "total_regret": round(total_regret, 4),
        "tags_present": sorted(tag_counts.keys()),
        "tag_counts": dict(sorted(tag_counts.items())),
        "tag_regret_sums": {k: round(v, 4) for k, v in sorted(tag_regret_sums.items())},
        "steps": items,
    }


def analyze_episode(ep_dict: dict, solver_score: float, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    import verify_replay
    from canary.analysis.tags import to_result
    from canary.rules import tier_params_for_episode

    rep = verify_replay.replay_episode(ep_dict)
    replay_ok = abs(rep["score"] - ep_dict["score"]) < 1e-9 and rep["accused"] == ep_dict.get("accused")
    if not replay_ok:
        raise RuntimeError(f"Replay mismatch for {ep_dict.get('agent')}: recorded={ep_dict['score']} replay={rep['score']}")

    ep_res = to_result(ep_dict)
    params = tier_params_for_episode(ep_res.tier, ep_res.steps)
    tool_counts = collections.Counter(st.tool for st in ep_res.steps)

    return {
        "agent": ep_dict["agent"],
        "score": round(float(ep_dict["score"]), 4),
        "correct": bool(ep_dict.get("correct", False)),
        "accused": ep_dict.get("accused"),
        "final_day": int(ep_dict.get("final_day", 0)),
        "end_reason": ep_dict.get("end_reason"),
        "total_steps": len(ep_res.steps),
        "tool_counts": dict(sorted(tool_counts.items())),
        "score_ratio_vs_solver": round(float(ep_dict["score"]) / solver_score, 4) if solver_score > 0 else None,
        "replay": {"ok": replay_ok, **rep},
        "usage": usage,
        "canary_partition": analyze_canary_partitions(ep_res, params),
        "accusation_calibration": analyze_accusation_calibration(ep_res, params),
        "regret": analyze_regret(ep_res),
    }


def run_solver_baseline(tier: str, seed: int) -> tuple[dict, dict[str, Any]]:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    env = Env(tier, seed)
    pol = SolverPolicy()
    res = run_episode(env, pol)
    ep_dict = json.loads(json.dumps(dataclasses.asdict(res), default=str))
    ep_dict["agent"] = "solver"
    metrics = analyze_episode(ep_dict, solver_score=float(ep_dict["score"]), usage=None)
    return ep_dict, metrics


def combine_usage(by_level: dict[str, dict[str, Any]]) -> dict[str, Any]:
    calls = sum(int(u.get("calls", 0) or 0) for u in by_level.values())
    tin = sum(int(u.get("in", 0) or 0) for u in by_level.values())
    tout = sum(int(u.get("out", 0) or 0) for u in by_level.values())
    think = sum(int(u.get("thinking", 0) or 0) for u in by_level.values())
    cached = sum(int(u.get("cached", 0) or 0) for u in by_level.values())
    cost_usd = round(sum(float(u.get("cost_usd", 0.0) or 0.0) for u in by_level.values()), 6)
    cost_usd_est = round(sum(float(u.get("cost_usd_est", 0.0) or 0.0) for u in by_level.values()), 6)
    latency_s = round(sum(float(u.get("latency_s", 0.0) or 0.0) for u in by_level.values()), 3)
    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": think,
        "cached": cached,
        "out_incl_thinking": tout + think,
        "cost_usd": cost_usd,
        "cost_usd_est": cost_usd_est,
        "latency_s": latency_s,
        "by_level": by_level,
    }


def compute_deltas(low_m: dict[str, Any], high_m: dict[str, Any]) -> dict[str, Any]:
    lu = low_m.get("usage") or {}
    hu = high_m.get("usage") or {}
    lc = low_m["canary_partition"]
    hc = high_m["canary_partition"]
    la = low_m["accusation_calibration"]
    ha = high_m["accusation_calibration"]
    lr = low_m["regret"]
    hr = high_m["regret"]

    all_tags = sorted(set(lr["tag_counts"]) | set(hr["tag_counts"]))
    p_delta = (
        round(ha["p_accused"] - la["p_accused"], 4)
        if ha["p_accused"] is not None and la["p_accused"] is not None
        else None
    )
    low_think = int(lu.get("thinking", 0) or 0)
    high_think = int(hu.get("thinking", 0) or 0)
    return {
        "score_delta": round(high_m["score"] - low_m["score"], 4),
        "luck_adjusted_score_delta": round(ha["luck_adjusted_score"] - la["luck_adjusted_score"], 4),
        "thinking_tokens_delta": high_think - low_think,
        "thinking_tokens_ratio": round(high_think / low_think, 3) if low_think > 0 else None,
        "calls_delta": int(hu.get("calls", 0) or 0) - int(lu.get("calls", 0) or 0),
        "cost_usd_delta": round(float(hu.get("cost_usd", 0.0) or 0.0) - float(lu.get("cost_usd", 0.0) or 0.0), 6),
        "mean_canary_recipient_entropy_bits_delta": round(
            hc["mean_recipient_entropy_bits"] - lc["mean_recipient_entropy_bits"], 4
        ),
        "mean_canary_posterior_entropy_bits_delta": round(
            hc["mean_posterior_entropy_bits"] - lc["mean_posterior_entropy_bits"], 4
        ),
        "p_accused_delta": p_delta,
        "total_regret_delta": round(hr["total_regret"] - lr["total_regret"], 4),
        "tag_count_deltas": {t: hr["tag_counts"].get(t, 0) - lr["tag_counts"].get(t, 0) for t in all_tags},
        "tag_regret_deltas": {
            t: round(hr["tag_regret_sums"].get(t, 0.0) - lr["tag_regret_sums"].get(t, 0.0), 4)
            for t in all_tags
        },
    }


def render_summary_md(meta: dict[str, Any], comp: dict[str, Any]) -> str:
    low = comp["low"]
    high = comp["high"]
    sol = comp["solver"]
    deltas = comp["deltas_high_minus_low"]
    tp = comp["tier_params"]

    def _fmt(v: Any, nd: int = 4) -> str:
        if v is None:
            return "n/a"
        if isinstance(v, float):
            return f"{v:.{nd}f}"
        return str(v)

    lines = [
        f"# Gemini 4 Carbon Hard-Tier Thinking Ablation ({comp['tier']} seed {comp['seed']}, {meta['tiers_version']})",
        "",
        "## Provenance",
        f"- Role: `{meta['role']}` / `{meta['subrole']}`",
        f"- Model: `{meta['model_id']}`",
        f"- World: Canary `{meta['tiers_version']}` `{comp['tier']}` seed `{comp['seed']}` "
        f"({tp['n_employees']} employees, {tp['n_days']} days, {tp['canaries_per_day']} canaries/day, "
        f"{tp['max_variants']} max variants)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Replay verified (`scripts/verify_replay.py`): `{meta['replay_verified']}`",
        f"- Mode: `{'stub' if meta.get('stub') else 'real_api'}`",
        "",
        "## Headline Comparison (`low` vs `high` vs `SolverPolicy`)",
        "",
        "| Metric | gemini-4-carbon (low) | gemini-4-carbon (high) | SolverPolicy | Delta (high - low) |",
        "|---|---:|---:|---:|---:|",
        f"| Score | {_fmt(low['score'])} | {_fmt(high['score'])} | {_fmt(sol['score'])} | {deltas['score_delta']:+.4f} |",
        f"| Correct accusation | {low['correct']} | {high['correct']} | {sol['correct']} | n/a |",
        f"| Accused employee | {low['accused'] or 'none'} | {high['accused'] or 'none'} | {sol['accused'] or 'none'} | n/a |",
        f"| Final day | {low['final_day']} | {high['final_day']} | {sol['final_day']} | {high['final_day'] - low['final_day']:+d} |",
        f"| Score / Solver | {_fmt(low['score_ratio_vs_solver'], 3)} | {_fmt(high['score_ratio_vs_solver'], 3)} | 1.000 | n/a |",
        f"| Luck-adjusted score | {_fmt(low['accusation_calibration']['luck_adjusted_score'])} | "
        f"{_fmt(high['accusation_calibration']['luck_adjusted_score'])} | "
        f"{_fmt(sol['accusation_calibration']['luck_adjusted_score'])} | {deltas['luck_adjusted_score_delta']:+.4f} |",
        f"| Solver P(accused) | {_fmt(low['accusation_calibration']['p_accused'])} | "
        f"{_fmt(high['accusation_calibration']['p_accused'])} | "
        f"{_fmt(sol['accusation_calibration']['p_accused'])} | {_fmt(deltas['p_accused_delta'])} |",
        f"| Accusation verdict | {low['accusation_calibration']['verdict']} | "
        f"{high['accusation_calibration']['verdict']} | {sol['accusation_calibration']['verdict']} | n/a |",
        f"| Canaries planted | {low['canary_partition']['canaries_planted']} | "
        f"{high['canary_partition']['canaries_planted']} | {sol['canary_partition']['canaries_planted']} | "
        f"{high['canary_partition']['canaries_planted'] - low['canary_partition']['canaries_planted']:+d} |",
        f"| Mean canary recipient entropy (bits) | {_fmt(low['canary_partition']['mean_recipient_entropy_bits'])} | "
        f"{_fmt(high['canary_partition']['mean_recipient_entropy_bits'])} | "
        f"{_fmt(sol['canary_partition']['mean_recipient_entropy_bits'])} | "
        f"{deltas['mean_canary_recipient_entropy_bits_delta']:+.4f} |",
        f"| Mean canary posterior entropy (bits) | {_fmt(low['canary_partition']['mean_posterior_entropy_bits'])} | "
        f"{_fmt(high['canary_partition']['mean_posterior_entropy_bits'])} | "
        f"{_fmt(sol['canary_partition']['mean_posterior_entropy_bits'])} | "
        f"{deltas['mean_canary_posterior_entropy_bits_delta']:+.4f} |",
        f"| Total solver regret | {_fmt(low['regret']['total_regret'])} | {_fmt(high['regret']['total_regret'])} | "
        f"{_fmt(sol['regret']['total_regret'])} | {deltas['total_regret_delta']:+.4f} |",
        f"| API calls | {low['usage']['calls']} | {high['usage']['calls']} | 0 | {deltas['calls_delta']:+d} |",
        f"| Input tokens | {low['usage']['in']} | {high['usage']['in']} | 0 | {high['usage']['in'] - low['usage']['in']:+d} |",
        f"| Output tokens (excl. thinking) | {low['usage']['out']} | {high['usage']['out']} | 0 | "
        f"{high['usage']['out'] - low['usage']['out']:+d} |",
        f"| Thinking tokens | {low['usage']['thinking']} | {high['usage']['thinking']} | 0 | "
        f"{deltas['thinking_tokens_delta']:+d} |",
        f"| Cached input tokens | {low['usage']['cached']} | {high['usage']['cached']} | 0 | "
        f"{high['usage']['cached'] - low['usage']['cached']:+d} |",
        f"| Cached-adjusted cost (USD) | {_fmt(low['usage']['cost_usd_est'], 4)} | {_fmt(high['usage']['cost_usd_est'], 4)} | "
        f"0.0000 | {high['usage']['cost_usd_est'] - low['usage']['cost_usd_est']:+.4f} |",
        f"| List-price cost (USD) | {_fmt(low['usage']['cost_usd'], 4)} | {_fmt(high['usage']['cost_usd'], 4)} | "
        f"0.0000 | {deltas['cost_usd_delta']:+.4f} |",
        "",
        "## Canary Partition Entropy & Information Design",
        f"- `low`: {low['canary_partition']['canaries_planted']} canaries, "
        f"mean recipients {low['canary_partition']['mean_recipients']:.2f}, "
        f"mean variants {low['canary_partition']['mean_distinct_variants']:.2f}, "
        f"recipient entropy {low['canary_partition']['mean_recipient_entropy_bits']:.4f} bits, "
        f"posterior entropy {low['canary_partition']['mean_posterior_entropy_bits']:.4f} bits, "
        f"posterior Gini {low['canary_partition']['mean_posterior_gini']:.4f}.",
        f"- `high`: {high['canary_partition']['canaries_planted']} canaries, "
        f"mean recipients {high['canary_partition']['mean_recipients']:.2f}, "
        f"mean variants {high['canary_partition']['mean_distinct_variants']:.2f}, "
        f"recipient entropy {high['canary_partition']['mean_recipient_entropy_bits']:.4f} bits, "
        f"posterior entropy {high['canary_partition']['mean_posterior_entropy_bits']:.4f} bits, "
        f"posterior Gini {high['canary_partition']['mean_posterior_gini']:.4f}.",
        f"- `solver`: {sol['canary_partition']['canaries_planted']} canaries, "
        f"mean recipients {sol['canary_partition']['mean_recipients']:.2f}, "
        f"mean variants {sol['canary_partition']['mean_distinct_variants']:.2f}, "
        f"recipient entropy {sol['canary_partition']['mean_recipient_entropy_bits']:.4f} bits, "
        f"posterior entropy {sol['canary_partition']['mean_posterior_entropy_bits']:.4f} bits, "
        f"posterior Gini {sol['canary_partition']['mean_posterior_gini']:.4f}.",
        "",
        "## Accusation Posterior Calibration",
        f"- `low`: accused `{low['accusation_calibration']['accused']}` on day {low['accusation_calibration']['day']} "
        f"(P(accused)={_fmt(low['accusation_calibration']['p_accused'])}, "
        f"P(top)={_fmt(low['accusation_calibration']['p_top'])}, "
        f"posterior entropy={low['accusation_calibration']['posterior_entropy_bits']:.4f} bits, "
        f"N_eff={low['accusation_calibration']['effective_suspects']:.2f}, "
        f"Brier={_fmt(low['accusation_calibration']['brier_score'])}, "
        f"verdict={low['accusation_calibration']['verdict']}).",
        f"- `high`: accused `{high['accusation_calibration']['accused']}` on day {high['accusation_calibration']['day']} "
        f"(P(accused)={_fmt(high['accusation_calibration']['p_accused'])}, "
        f"P(top)={_fmt(high['accusation_calibration']['p_top'])}, "
        f"posterior entropy={high['accusation_calibration']['posterior_entropy_bits']:.4f} bits, "
        f"N_eff={high['accusation_calibration']['effective_suspects']:.2f}, "
        f"Brier={_fmt(high['accusation_calibration']['brier_score'])}, "
        f"verdict={high['accusation_calibration']['verdict']}).",
        f"- `solver`: accused `{sol['accusation_calibration']['accused']}` on day {sol['accusation_calibration']['day']} "
        f"(P(accused)={_fmt(sol['accusation_calibration']['p_accused'])}, "
        f"P(top)={_fmt(sol['accusation_calibration']['p_top'])}, "
        f"posterior entropy={sol['accusation_calibration']['posterior_entropy_bits']:.4f} bits, "
        f"N_eff={sol['accusation_calibration']['effective_suspects']:.2f}, "
        f"Brier={_fmt(sol['accusation_calibration']['brier_score'])}, "
        f"verdict={sol['accusation_calibration']['verdict']}).",
        "",
        "## Solver Regret Attribution (`canary.solver.regret.attribute`)",
        "",
        "| Failure Tag | low (count / regret) | high (count / regret) | solver (count / regret) | Delta regret (high - low) |",
        "|---|---:|---:|---:|---:|",
    ]
    all_tags = sorted(
        set(low["regret"]["tag_counts"])
        | set(high["regret"]["tag_counts"])
        | set(sol["regret"]["tag_counts"])
    )
    if not all_tags:
        lines.append("| (none) | 0 / 0.0000 | 0 / 0.0000 | 0 / 0.0000 | +0.0000 |")
    else:
        for tg in all_tags:
            lc = low["regret"]["tag_counts"].get(tg, 0)
            lr = low["regret"]["tag_regret_sums"].get(tg, 0.0)
            hc = high["regret"]["tag_counts"].get(tg, 0)
            hr = high["regret"]["tag_regret_sums"].get(tg, 0.0)
            sc = sol["regret"]["tag_counts"].get(tg, 0)
            sr = sol["regret"]["tag_regret_sums"].get(tg, 0.0)
            lines.append(
                f"| `{tg}` | {lc} / {lr:.4f} | {hc} / {hr:.4f} | {sc} / {sr:.4f} | {hr - lr:+.4f} |"
            )
    lines.extend([
        "",
        "## Key Takeaways",
        f"- Thinking budget scaling: `low` used {low['usage']['thinking']:,} thinking tokens across "
        f"{low['usage']['calls']} calls ({low['usage']['thinking_share_of_generation'] * 100.0:.1f}% of generation), "
        f"while `high` used {high['usage']['thinking']:,} thinking tokens across {high['usage']['calls']} calls "
        f"({high['usage']['thinking_share_of_generation'] * 100.0:.1f}% of generation, peak "
        f"{high['usage']['max_thinking_call']:,} thinking tokens in a single call).",
        f"- Partition information & per-step regret: `high` achieved mean canary posterior entropy "
        f"{high['canary_partition']['mean_posterior_entropy_bits']:.4f} bits and posterior Gini "
        f"{high['canary_partition']['mean_posterior_gini']:.4f} (vs `low` "
        f"{low['canary_partition']['mean_posterior_entropy_bits']:.4f} bits / Gini "
        f"{low['canary_partition']['mean_posterior_gini']:.4f}, `SolverPolicy` "
        f"{sol['canary_partition']['mean_posterior_entropy_bits']:.4f} bits / Gini "
        f"{sol['canary_partition']['mean_posterior_gini']:.4f}), shifting total solver regret by "
        f"{deltas['total_regret_delta']:+.4f} ({low['regret']['total_regret']:.4f} to {high['regret']['total_regret']:.4f}).",
        f"- Stopping threshold vs daily bleed: `low` ended on day {low['final_day']} at "
        f"P(accused)={_fmt(low['accusation_calibration']['p_accused'])} for score {low['score']:+.4f} "
        f"(`SolverPolicy` day {sol['final_day']}, P(accused)={_fmt(sol['accusation_calibration']['p_accused'])}, "
        f"score {sol['score']:+.4f}), whereas `high` ended on day {high['final_day']} at "
        f"P(accused)={_fmt(high['accusation_calibration']['p_accused'])} "
        f"(N_eff={high['accusation_calibration']['effective_suspects']:.2f}) for score {high['score']:+.4f}.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None, client_builder: Callable | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-retries", type=int, default=10)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--stub", action="store_true")
    args = ap.parse_args(argv)

    prev_retries = os.environ.get("CANARY_LLM_MAX_RETRIES")
    os.environ["CANARY_LLM_MAX_RETRIES"] = str(args.max_retries)

    try:
        import verify_replay
        from canary.agents.runlog import git_sha
        from canary.analysis.tags import tag_report
        from canary.rules import TIERS_VERSION, tier_params

        if TIERS_VERSION != "v1.4":
            raise RuntimeError(f"Expected TIERS_VERSION=='v1.4', got {TIERS_VERSION!r}")

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

        temp_ledger_ctx = None
        prev_ledger = os.environ.get("CANARY_GEMINI_LEDGER")
        if args.stub and not prev_ledger:
            temp_ledger_ctx = tempfile.TemporaryDirectory()
            os.environ["CANARY_GEMINI_LEDGER"] = str(Path(temp_ledger_ctx.name) / "stub_ledger.jsonl")

        try:
            levels = ("low", "high")
            episodes: dict[str, dict] = {}
            usages: dict[str, dict[str, Any]] = {}

            workers = 1 if args.stub or args.jobs <= 1 else min(args.jobs, len(levels))
            if workers == 1:
                for lv in levels:
                    ep, u = run_level_episode(
                        out_dir=out_dir,
                        model=args.model,
                        level=lv,
                        tier=args.tier,
                        seed=args.seed,
                        stub=args.stub,
                        resume=args.resume,
                        max_retries=args.max_retries,
                        max_attempts=args.max_attempts,
                        client_builder=client_builder,
                    )
                    episodes[lv] = ep
                    usages[lv] = u
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = {
                        pool.submit(
                            run_level_episode,
                            out_dir=out_dir,
                            model=args.model,
                            level=lv,
                            tier=args.tier,
                            seed=args.seed,
                            stub=args.stub,
                            resume=args.resume,
                            max_retries=args.max_retries,
                            max_attempts=args.max_attempts,
                            client_builder=client_builder,
                        ): lv
                        for lv in levels
                    }
                    for fut in concurrent.futures.as_completed(futs):
                        lv = futs[fut]
                        ep, u = fut.result()
                        episodes[lv] = ep
                        usages[lv] = u

            rc = verify_replay.main([str(out_dir / "low"), str(out_dir / "high")])
            if rc != 0:
                raise RuntimeError("verify_replay failed on generated episodes")

            solver_ep, solver_metrics = run_solver_baseline(args.tier, args.seed)
            solver_score = float(solver_metrics["score"])
            low_metrics = analyze_episode(episodes["low"], solver_score=solver_score, usage=usages["low"])
            high_metrics = analyze_episode(episodes["high"], solver_score=solver_score, usage=usages["high"])
            deltas = compute_deltas(low_metrics, high_metrics)
            pooled_tags = tag_report([episodes["low"], episodes["high"], solver_ep])

            p = tier_params(args.tier)
            commit = git_sha()
            ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            cmd_tokens = [
                "CANARY_LLM_MAX_RETRIES=" + str(args.max_retries),
                "PYTHONPATH=.",
                "python",
                "scripts/run_carbon_hard_thinking.py",
                "--out",
                str(args.out),
                "--model",
                str(args.model),
                "--tier",
                str(args.tier),
                "--seed",
                str(args.seed),
                "--max-retries",
                str(args.max_retries),
            ]
            if args.stub:
                cmd_tokens.append("--stub")
            cmd_str = " ".join(cmd_tokens)
            combined_usage = combine_usage({"low": usages["low"], "high": usages["high"]})
            key_metric = (
                f"low {low_metrics['score']:+.3f} ({usages['low']['thinking']:,} think tok, day {low_metrics['final_day']}) "
                f"-> high {high_metrics['score']:+.3f} ({usages['high']['thinking']:,} think tok, day {high_metrics['final_day']}) "
                f"vs solver {solver_score:+.3f}"
            )

            meta = {
                "role": ROLE,
                "subrole": SUBROLE,
                "model_id": args.model,
                "tiers_version": TIERS_VERSION,
                "tier": args.tier,
                "seed": args.seed,
                "episode_count": 2,
                "commit": commit,
                "timestamp": ts,
                "command": cmd_str,
                "usage": combined_usage,
                "low_score": low_metrics["score"],
                "high_score": high_metrics["score"],
                "solver_score": solver_score,
                "levels_summary": {
                    "low": low_metrics["score"],
                    "high": high_metrics["score"],
                },
                "key_metric": key_metric,
                "replay_verified": True,
                "stub": bool(args.stub),
                "ledger_run_ids": [usages["low"]["run_id"], usages["high"]["run_id"]],
            }

            comparison = {
                "role": ROLE,
                "subrole": SUBROLE,
                "model_id": args.model,
                "tiers_version": TIERS_VERSION,
                "tier": args.tier,
                "seed": args.seed,
                "tier_params": {
                    "n_employees": p.n_employees,
                    "n_days": p.n_days,
                    "canaries_per_day": p.canaries_per_day,
                    "max_variants": p.max_variants,
                    "leak_damage": p.leak_damage,
                    "canary_cost": p.canary_cost,
                    "actions_per_day": p.actions_per_day,
                    "tool_call_cap": p.tool_call_cap,
                    "fingerprint_accuracy": p.fingerprint_accuracy,
                },
                "commit": commit,
                "timestamp": ts,
                "stub": bool(args.stub),
                "replay_verified": True,
                "low": low_metrics,
                "high": high_metrics,
                "solver": solver_metrics,
                "deltas_high_minus_low": deltas,
                "tag_report": pooled_tags,
            }

            (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")
            (out_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, default=str) + "\n")
            (out_dir / "summary.md").write_text(render_summary_md(meta, comparison))
            return 0
        finally:
            if temp_ledger_ctx is not None:
                if prev_ledger is None:
                    os.environ.pop("CANARY_GEMINI_LEDGER", None)
                else:
                    os.environ["CANARY_GEMINI_LEDGER"] = prev_ledger
                temp_ledger_ctx.cleanup()
    finally:
        if prev_retries is None:
            os.environ.pop("CANARY_LLM_MAX_RETRIES", None)
        else:
            os.environ["CANARY_LLM_MAX_RETRIES"] = prev_retries


if __name__ == "__main__":
    raise SystemExit(main())
