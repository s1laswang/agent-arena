"""Precompute deterministic hard-tier reference scores for seeds 30..49 and warm social caches."""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.accuse import audit_episode
from canary.baselines import DoNothing, Heuristic, StopEarlyQuit
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.text.llm_cache import default_cache_dir

DEFAULT_OUT = ROOT / "results" / "v16_social" / "reference_seeds_30_49.json"
EMP_ID_CHECK = re.compile(r"\be\d{2,3}\b", re.I)


def compute_luck_adjusted(ep: Any, p_accused: float | None) -> float:
    if not ep.accused or p_accused is None:
        return 0.0
    v_at_accuse = float((ep.meta or {}).get("V", 0.0))
    return round(float(p_accused) * v_at_accuse - (1.0 - float(p_accused)), 6)


def evaluate_seed(seed: int, tier: str = "hard") -> dict[str, Any]:
    solver_ep = run_episode(Env(tier, seed), SolverPolicy(tier))
    solver_audit = audit_episode(solver_ep)
    solver_p = solver_audit["p_accused"]
    solver_luck = compute_luck_adjusted(solver_ep, solver_p)

    dn_ep = run_episode(Env(tier, seed), DoNothing(seed=seed))
    if float(dn_ep.score) != 0.0:
        raise AssertionError(f"DoNothing score on {tier} seed {seed} expected 0.0, got {dn_ep.score}")

    se_ep = run_episode(Env(tier, seed), StopEarlyQuit(seed=seed))
    if float(se_ep.score) != 0.0:
        raise AssertionError(f"StopEarlyQuit score on {tier} seed {seed} expected 0.0, got {se_ep.score}")

    heur_ep = run_episode(Env(tier, seed), Heuristic(seed=seed))
    heur_audit = audit_episode(heur_ep)
    heur_p = heur_audit["p_accused"]
    heur_luck = compute_luck_adjusted(heur_ep, heur_p)

    return {
        "seed": int(seed),
        "solver_score": round(float(solver_ep.score), 6),
        "solver_correct": bool(solver_ep.correct),
        "solver_accused_bool": bool(solver_ep.accused is not None),
        "solver_day": int(solver_audit["day"]),
        "solver_p_accused": float(solver_p) if solver_p is not None else None,
        "solver_luck_adj": solver_luck,
        "do_nothing_score": float(dn_ep.score),
        "stop_early_score": float(se_ep.score),
        "heuristic_score": round(float(heur_ep.score), 6),
        "heuristic_correct": bool(heur_ep.correct),
        "heuristic_accused_bool": bool(heur_ep.accused is not None),
        "heuristic_day": int(heur_audit["day"]),
        "heuristic_p_accused": float(heur_p) if heur_p is not None else None,
        "heuristic_luck_adj": heur_luck,
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    sp_vals = [r["solver_p_accused"] for r in rows if r["solver_p_accused"] is not None]
    hp_vals = [r["heuristic_p_accused"] for r in rows if r["heuristic_p_accused"] is not None]
    return {
        "n": n,
        "seed_min": min(r["seed"] for r in rows),
        "seed_max": max(r["seed"] for r in rows),
        "solver_score_mean": round(sum(r["solver_score"] for r in rows) / n, 6),
        "solver_acc": round(sum(1.0 for r in rows if r["solver_correct"]) / n, 6),
        "solver_accused_rate": round(sum(1.0 for r in rows if r["solver_accused_bool"]) / n, 6),
        "solver_day_mean": round(sum(r["solver_day"] for r in rows) / n, 4),
        "solver_p_accused_mean": round(sum(sp_vals) / len(sp_vals), 6) if sp_vals else None,
        "solver_luck_adj_mean": round(sum(r["solver_luck_adj"] for r in rows) / n, 6),
        "do_nothing_score_mean": round(sum(r["do_nothing_score"] for r in rows) / n, 6),
        "stop_early_score_mean": round(sum(r["stop_early_score"] for r in rows) / n, 6),
        "heuristic_score_mean": round(sum(r["heuristic_score"] for r in rows) / n, 6),
        "heuristic_acc": round(sum(1.0 for r in rows if r["heuristic_correct"]) / n, 6),
        "heuristic_accused_rate": round(sum(1.0 for r in rows if r["heuristic_accused_bool"]) / n, 6),
        "heuristic_day_mean": round(sum(r["heuristic_day"] for r in rows) / n, 4),
        "heuristic_p_accused_mean": round(sum(hp_vals) / len(hp_vals), 6) if hp_vals else None,
        "heuristic_luck_adj_mean": round(sum(r["heuristic_luck_adj"] for r in rows) / n, 6),
    }


def assert_zero_truth_leak(payload_json: str) -> None:
    low = payload_json.lower()
    if "mole" in low or "decoy" in low:
        raise ValueError("reference output must never contain mole or decoy fields")
    if EMP_ID_CHECK.search(payload_json):
        raise ValueError("reference output must never contain employee identifiers")


def build_reference_payload(seeds: list[int], tier: str = "hard") -> dict[str, Any]:
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    rows = [evaluate_seed(s, tier=tier) for s in seeds]
    rows_30_39 = [r for r in rows if 30 <= r["seed"] <= 39]
    rows_40_49 = [r for r in rows if 40 <= r["seed"] <= 49]
    rows_30_49 = [r for r in rows if 30 <= r["seed"] <= 49]
    summary: dict[str, Any] = {"all": summarize_rows(rows)}
    if rows_30_39:
        summary["30-39"] = summarize_rows(rows_30_39)
    if rows_40_49:
        summary["40-49"] = summarize_rows(rows_40_49)
    if rows_30_49:
        summary["30-49"] = summarize_rows(rows_30_49)
    payload = {
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": rows,
        "summary": summary,
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    assert_zero_truth_leak(serialized)
    return payload


class _ChatterWarmProvider:
    def __init__(self, model: str, cache_dir: Path, stub: bool = False):
        from canary.text.template import TemplateProvider
        self.base = TemplateProvider()
        self.model = model
        self.cache_dir = cache_dir
        self.stub = stub
        self.name = f"chatter-warm:{'stub' if stub else model}"

    def day_messages(self, facts: Any) -> list[dict[str, Any]]:
        from canary.social.gemini_chatter import render_with_gemini
        base_msgs = self.base.day_messages(facts)
        if not base_msgs:
            return base_msgs
        emp_ids = [e.id for e in facts.employees]
        target = emp_ids[facts.day % len(emp_ids)] if emp_ids else "e00"
        sender = emp_ids[(facts.day + 1) % len(emp_ids)] if len(emp_ids) > 1 else target
        synthetic = [{
            "id": f"m{facts.day}-s0",
            "day": facts.day,
            "channel": "general",
            "sender": sender,
            "recipients": emp_ids[:4],
            "subject": f"note {target}",
            "body": f"In today's meeting {target} asked about the latest doc.",
            "target": target,
            "meta": {"target": target, "bias": "rumour"},
        }]
        rendered = render_with_gemini(
            facts,
            synthetic,
            model=self.model,
            cache_dir=str(self.cache_dir),
            stub=self.stub,
        )
        return base_msgs + rendered

    def interview_answer(self, facts: Any, employee: str, topic: str, signal: str) -> str:
        return self.base.interview_answer(facts, employee, topic, signal)


def _resolve_warm_provider(provider_spec: str, cache_dir: Path) -> Any:
    if provider_spec in ("chatter-stub", "social-stub"):
        return _ChatterWarmProvider("gemini-4-carbon", cache_dir, stub=True)
    if provider_spec.startswith("chatter:"):
        model = provider_spec.split(":", 1)[1] or "gemini-4-carbon"
        return _ChatterWarmProvider(model, cache_dir, stub=False)

    for mod_name in ("canary.social", "canary.social.engine", "canary.social.variants", "canary.social.provider"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        for fn_name in ("make_v16_provider", "get_social_provider", "make_social_provider", "get_provider"):
            fn = getattr(mod, fn_name, None)
            if callable(fn):
                try:
                    return fn(provider_spec, cache_dir=str(cache_dir))
                except TypeError:
                    try:
                        return fn(provider_spec)
                    except (ValueError, KeyError):
                        continue
                except (ValueError, KeyError):
                    continue

    from canary.text.gemini import get_provider
    normalized = f"gemini:{provider_spec}" if provider_spec == "gemini-4-carbon" else provider_spec
    if normalized in ("template", None, ""):
        return get_provider("template")
    return get_provider(normalized, cache_dir=str(cache_dir))


def warm_cache(seeds: list[int], tier: str, provider_spec: str, cache_dir: str | Path | None = None) -> dict[str, Any]:
    resolved_dir = default_cache_dir(cache_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)
    days_warmed = 0
    for seed in seeds:
        prov = _resolve_warm_provider(provider_spec, resolved_dir)
        env = Env(tier, seed, text_provider=prov)
        days_warmed += 1
        while not env.done:
            res = env.call("advance_day", {})
            if not res.ok:
                break
            days_warmed += 1
    return {
        "tier": tier,
        "provider": provider_spec,
        "cache_dir": str(resolved_dir),
        "n_seeds": len(seeds),
        "seeds": seeds,
        "days_processed": days_warmed,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts.v16_prepare_seeds")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="30-49")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--warm-cache", action="store_true")
    ap.add_argument("--provider", default="gemini-4-carbon")
    ap.add_argument("--cache-dir", default=None)
    args = ap.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    if args.warm_cache:
        report = warm_cache(seeds, tier=args.tier, provider_spec=args.provider, cache_dir=args.cache_dir)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    payload = build_reference_payload(seeds, tier=args.tier)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert_zero_truth_leak(serialized)
    out_path.write_text(serialized, encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
