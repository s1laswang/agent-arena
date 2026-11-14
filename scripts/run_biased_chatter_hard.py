from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.world_builder import assert_no_truth
from canary.baselines import DoNothing, ObviousHeuristic
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.biased_chatter import (
    BIAS_KINDS,
    DEFAULT_MODEL,
    BiasEventSpec,
    BiasedChatterProvider,
    build_bias_event_spec,
    generate_biased_chatter,
    public_facts_from_env,
    sanitize_public_facts,
    validate_biased_chatter,
)
from canary.gemini.leak_encodings import extract_env_secrets, scan_messages_for_secret
from canary.rules import TIERS_VERSION, tier_params
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages
from canary.text.template import TemplateProvider
from canary.world import world_seed

SUBROLE = "biased_chatter_hard"
DEFAULT_TIER = "hard"
DEFAULT_SEEDS: tuple[int, ...] = (0, 1, 2, 3)
DEFAULT_DAYS: tuple[int, ...] = (1, 4, 8)
DEFAULT_OUT = "results/gemini_roles/world_text/biased-chatter-hard-carbon"
MD_H1 = "\x23"
MD_H2 = "\x23\x23"
MD_H3 = "\x23\x23\x23"


def scrub_dashes(text: str) -> str:
    s = str(text or "")
    s = s.replace(" \u2014 ", ", ").replace("\u2014", ", ")
    s = s.replace(" \u2013 ", " - ").replace("\u2013", "-")
    s = s.replace("\u2012", "-").replace("\u2015", ", ")
    return s


def sanitize_for_storage(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {scrub_dashes(str(k)): sanitize_for_storage(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_storage(v) for v in obj]
    if isinstance(obj, str):
        return scrub_dashes(obj)
    return obj


def parse_int_list(spec: str | Sequence[int]) -> list[int]:
    if not isinstance(spec, str):
        out = [int(x) for x in spec]
        if not out:
            raise ValueError("empty integer sequence")
        return out
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"invalid range: {part}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError("no integers specified")
    return out


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        sha = out.stdout.strip()
        return sha if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha) else "0000000"
    except Exception:
        return "0000000"


def merge_usage(usages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    int_keys = (
        "calls",
        "in",
        "out",
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "cached_tokens",
        "total_tokens",
    )
    agg: dict[str, Any] = {k: sum(int(u.get(k, 0) or 0) for u in usages) for k in int_keys}
    agg["cost_usd"] = round(sum(float(u.get("cost_usd", 0.0) or 0.0) for u in usages), 6)
    return agg


def format_command(argv: Sequence[str] | None) -> str:
    raw_args = sys.argv[1:] if argv is None else list(argv)
    parts = ["python", "scripts/run_biased_chatter_hard.py"]
    for tok in raw_args:
        clean = scrub_dashes(str(tok))
        if any(marker in clean for marker in ("API_KEY", "AIza", "sk-", "ya29.")):
            continue
        parts.append(clean)
    return " ".join(parts)


def build_hidden_role_targets(env: Any) -> list[str]:
    _, world_targets = extract_env_secrets(env)
    return list(world_targets)


def audit_messages_against_world(
    payload_or_messages: dict[str, Any] | Sequence[dict[str, Any]],
    env: Any,
) -> dict[str, int]:
    if isinstance(payload_or_messages, dict):
        payload = payload_or_messages
        messages = list(payload.get("messages") or [])
    else:
        messages = list(payload_or_messages)
        payload = {"messages": messages}

    pub_roster = [
        {"id": e.id, "name": e.name, "dept": e.dept, "role": e.role}
        for e in env._world.employees
    ]
    true_world = {"mole": env._world.mole, "employees": pub_roster}

    lint_probs = lint_messages(messages)
    if lint_probs:
        raise AssertionError(f"lint_messages violations: {lint_probs}")

    validate_biased_chatter(payload, world=true_world)
    assert_no_truth(payload, true_world)

    targets = build_hidden_role_targets(env)
    encoding_hits = scan_messages_for_secret(messages, targets)
    if encoding_hits:
        raise AssertionError(f"scan_messages_for_secret violations: {encoding_hits}")

    return {
        "truth_leak_violations": 0,
        "lint_violations": 0,
        "encoding_scan_violations": 0,
    }


def collect_public_day_snapshots(
    tier: str,
    seed: int,
    days: Sequence[int],
) -> tuple[Env, dict[int, dict[str, Any]]]:
    env = Env(tier, int(seed))
    company = scrub_dashes(str(env._world.company))
    snapshots: dict[int, dict[str, Any]] = {}
    for day in sorted({int(d) for d in days}):
        if day < 1 or day > env.p.n_days:
            raise ValueError(f"day {day} out of range 1..{env.p.n_days}")
        while env.day < day and not env.done:
            env.call("advance_day", {})
        raw_pub = public_facts_from_env(env, company=company)
        clean_pub = sanitize_public_facts(raw_pub)
        assert_no_truth(
            clean_pub,
            {"mole": env._world.mole, "employees": clean_pub["employees"]},
        )
        snapshots[day] = clean_pub
    return env, snapshots


class CachedBiasedChatterProvider(BiasedChatterProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        base: TemplateProvider | None = None,
    ) -> None:
        super().__init__(model=model, client=None)
        self.name = f"cached-biased-chatter:{model}"
        self._template = base if base is not None else TemplateProvider()
        self.sampled_hits = 0
        self.template_fallback_days = 0

    def register_day(
        self,
        tier: str,
        seed: int,
        day: int,
        messages: Sequence[dict[str, Any]],
    ) -> None:
        cleaned: list[dict[str, Any]] = []
        for idx, raw in enumerate(messages):
            cleaned.append(
                {
                    "id": str(raw.get("id", f"bc{int(day)}-{idx}")),
                    "day": int(day),
                    "channel": scrub_dashes(str(raw["channel"])),
                    "sender": str(raw["sender"]),
                    "recipients": [str(r) for r in raw["recipients"]],
                    "subject": scrub_dashes(str(raw.get("subject", ""))),
                    "body": scrub_dashes(str(raw["body"])),
                }
            )
        probs = lint_messages(cleaned)
        if probs:
            raise ValueError(f"cached message lint failure: {probs}")
        assert_no_truth({"messages": cleaned}, {})
        ws = world_seed(tier, int(seed))
        self._cache[(tier, int(seed), int(day))] = cleaned
        self._cache[(tier, int(ws), int(day))] = cleaned

    @classmethod
    def from_samples(
        cls,
        samples: Sequence[dict[str, Any]],
        *,
        tier: str = DEFAULT_TIER,
        model: str = DEFAULT_MODEL,
    ) -> CachedBiasedChatterProvider:
        prov = cls(model=model)
        for item in samples:
            item_tier = str(item.get("tier", tier))
            prov.register_day(
                tier=item_tier,
                seed=int(item["seed"]),
                day=int(item["day"]),
                messages=item["messages"],
            )
        return prov

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        base_msgs = [
            dict(m, recipients=list(m["recipients"]))
            for m in self._template.day_messages(facts)
        ]
        key = (facts.tier, int(facts.seed), int(facts.day))
        cached = self._cache.get(key)
        if cached is None:
            self.template_fallback_days += 1
            return base_msgs

        self.sampled_hits += 1
        emp_ids = {e.id for e in facts.employees}
        seen_ids = {str(m["id"]) for m in base_msgs}
        out = list(base_msgs)
        for idx, raw in enumerate(cached):
            m = copy.deepcopy(raw)
            if emp_ids and m["sender"] not in emp_ids:
                continue
            if emp_ids:
                recips = [r for r in m["recipients"] if r in emp_ids and r != m["sender"]]
                if not recips:
                    recips = [eid for eid in sorted(emp_ids) if eid != m["sender"]][:1]
                m["recipients"] = recips
            mid = str(m.get("id") or f"bc{int(facts.day)}-{idx}")
            if mid in seen_ids:
                mid = f"{mid}-{len(out)}"
            m["id"] = mid
            m["day"] = int(facts.day)
            seen_ids.add(mid)
            out.append(m)
        return out


def verify_solver_parity_hard(
    *,
    tier: str,
    seeds: Sequence[int],
    days: Sequence[int],
    samples: Sequence[dict[str, Any]],
    model_id: str,
) -> dict[str, Any]:
    p = tier_params(tier)
    seed_list = [int(s) for s in seeds]
    day_list = [int(d) for d in days]
    cached_provider = CachedBiasedChatterProvider.from_samples(
        samples,
        tier=tier,
        model=model_id,
    )

    per_seed: list[dict[str, Any]] = []
    for s in seed_list:
        tpl_solver = run_episode(
            Env(tier, s, text_provider=TemplateProvider()),
            SolverPolicy(),
        )
        bc_solver = run_episode(
            Env(tier, s, text_provider=cached_provider),
            SolverPolicy(),
        )
        tpl_obvious = run_episode(
            Env(tier, s, text_provider=TemplateProvider()),
            ObviousHeuristic(seed=s),
        )
        bc_obvious = run_episode(
            Env(tier, s, text_provider=cached_provider),
            ObviousHeuristic(seed=s),
        )

        horizon_env = Env(tier, s, text_provider=cached_provider)
        do_nothing_res = run_episode(horizon_env, DoNothing(seed=s))
        all_msgs = [horizon_env._messages[mid] for mid in horizon_env._msg_order]
        bc_msgs = [m for m in all_msgs if str(m.get("id", "")).startswith("bc")]
        if lint_messages(all_msgs):
            raise AssertionError(f"horizon lint violation on seed {s}")
        audit_messages_against_world(bc_msgs, horizon_env)

        per_seed.append(
            {
                "seed": s,
                "template_solver": {
                    "score": round(float(tpl_solver.score), 4),
                    "correct": bool(tpl_solver.correct),
                    "accused": tpl_solver.accused,
                    "final_day": int(tpl_solver.final_day),
                    "end_reason": str(tpl_solver.end_reason),
                },
                "biased_chatter_solver": {
                    "score": round(float(bc_solver.score), 4),
                    "correct": bool(bc_solver.correct),
                    "accused": bc_solver.accused,
                    "final_day": int(bc_solver.final_day),
                    "end_reason": str(bc_solver.end_reason),
                },
                "template_obvious_heuristic": {
                    "score": round(float(tpl_obvious.score), 4),
                    "correct": bool(tpl_obvious.correct),
                    "accused": tpl_obvious.accused,
                    "final_day": int(tpl_obvious.final_day),
                    "end_reason": str(tpl_obvious.end_reason),
                },
                "biased_chatter_obvious_heuristic": {
                    "score": round(float(bc_obvious.score), 4),
                    "correct": bool(bc_obvious.correct),
                    "accused": bc_obvious.accused,
                    "final_day": int(bc_obvious.final_day),
                    "end_reason": str(bc_obvious.end_reason),
                },
                "biased_chatter_do_nothing_score": round(float(do_nothing_res.score), 4),
                "biased_messages_delivered": len(bc_msgs),
                "total_horizon_messages": len(all_msgs),
            }
        )

    n = max(1, len(per_seed))
    tpl_s_catch = round(
        sum(1.0 if r["template_solver"]["correct"] else 0.0 for r in per_seed) / n,
        6,
    )
    bc_s_catch = round(
        sum(1.0 if r["biased_chatter_solver"]["correct"] else 0.0 for r in per_seed) / n,
        6,
    )
    tpl_s_mean = round(
        sum(float(r["template_solver"]["score"]) for r in per_seed) / n,
        6,
    )
    bc_s_mean = round(
        sum(float(r["biased_chatter_solver"]["score"]) for r in per_seed) / n,
        6,
    )
    tpl_o_catch = round(
        sum(1.0 if r["template_obvious_heuristic"]["correct"] else 0.0 for r in per_seed) / n,
        6,
    )
    bc_o_catch = round(
        sum(
            1.0 if r["biased_chatter_obvious_heuristic"]["correct"] else 0.0
            for r in per_seed
        )
        / n,
        6,
    )
    tpl_o_mean = round(
        sum(float(r["template_obvious_heuristic"]["score"]) for r in per_seed) / n,
        6,
    )
    bc_o_mean = round(
        sum(float(r["biased_chatter_obvious_heuristic"]["score"]) for r in per_seed) / n,
        6,
    )
    s_catch_delta = round(bc_s_catch - tpl_s_catch, 6)
    s_score_delta = round(bc_s_mean - tpl_s_mean, 6)
    o_score_delta = round(bc_o_mean - tpl_o_mean, 6)
    solver_gap = round(bc_s_mean - bc_o_mean, 6)
    do_nothing_zero = all(r["biased_chatter_do_nothing_score"] == 0.0 for r in per_seed)
    parity_ok = bool(
        do_nothing_zero
        and abs(s_score_delta) <= 0.05
        and bc_s_catch >= tpl_s_catch - 1e-9
        and solver_gap > 0.20
    )

    parity_doc = sanitize_for_storage(
        {
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "n_employees": int(p.n_employees),
            "n_days": int(p.n_days),
            "seeds": seed_list,
            "sampled_days": day_list,
            "template_solver_catch_rate": tpl_s_catch,
            "biased_chatter_solver_catch_rate": bc_s_catch,
            "solver_catch_rate_delta": s_catch_delta,
            "template_solver_mean_score": tpl_s_mean,
            "biased_chatter_solver_mean_score": bc_s_mean,
            "solver_mean_score_delta": s_score_delta,
            "template_obvious_heuristic_catch_rate": tpl_o_catch,
            "biased_chatter_obvious_heuristic_catch_rate": bc_o_catch,
            "template_obvious_heuristic_mean_score": tpl_o_mean,
            "biased_chatter_obvious_heuristic_mean_score": bc_o_mean,
            "obvious_heuristic_mean_score_delta": o_score_delta,
            "solver_vs_obvious_gap": solver_gap,
            "do_nothing_all_zero": do_nothing_zero,
            "extra_api_calls_during_rollout": 0,
            "cached_sampled_day_hits": int(cached_provider.sampled_hits),
            "template_fallback_day_hits": int(cached_provider.template_fallback_days),
            "parity_ok": parity_ok,
            "per_seed": per_seed,
        }
    )
    assert_no_truth(parity_doc, {})
    return parity_doc


def generate_single_seed_days(
    *,
    tier: str,
    seed: int,
    days: Sequence[int],
    model: str,
    client: Any,
    run_id: str,
    thinking_level: str | None,
    require_live: bool,
    max_attempts: int,
) -> list[dict[str, Any]]:
    env, snapshots = collect_public_day_snapshots(tier, seed, days)
    pub_roster = [
        {"id": e.id, "name": e.name, "dept": e.dept, "role": e.role}
        for e in env._world.employees
    ]
    true_world = {"mole": env._world.mole, "employees": pub_roster}

    seed_samples: list[dict[str, Any]] = []
    seed_messages: list[dict[str, Any]] = []

    for day in sorted(snapshots):
        pub_facts = snapshots[day]
        explicit_spec = build_bias_event_spec(pub_facts, seed=int(seed))
        attempts = max(1, int(max_attempts)) if require_live else 1
        gen: dict[str, Any] | None = None
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                cand = generate_biased_chatter(
                    pub_facts,
                    bias_spec=explicit_spec,
                    model=model,
                    client=client,
                    seed=int(seed),
                    run_id=run_id,
                    thinking_level=thinking_level,
                    world_for_check=true_world,
                    require_live=require_live,
                )
                audit_counts = audit_messages_against_world(cand, env)
                cand = {**cand, **audit_counts}
                gen = cand
                break
            except Exception as exc:
                last_err = exc
                if attempt + 1 < attempts:
                    time.sleep(min(12.0, 2.0 * (attempt + 1)))
        if gen is None:
            assert last_err is not None
            raise last_err

        sample_record = sanitize_for_storage(
            {
                "tier": tier,
                "seed": int(seed),
                **gen,
            }
        )
        assert_no_truth(sample_record, true_world)
        seed_samples.append(sample_record)
        seed_messages.extend(sample_record["messages"])

    audit_messages_against_world(seed_messages, env)
    return seed_samples


def render_summary_md(
    meta: dict[str, Any],
    samples_doc: dict[str, Any],
    parity_doc: dict[str, Any],
) -> str:
    u = meta["usage"]
    lines = [
        f"{MD_H1} Hard-Tier Multi-Day Biased Workplace Chatter ({meta['model_id']})",
        "",
        f"- Role: `{meta['role']}` / `{meta['subrole']}`",
        f"- Model: `{meta['model_id']}`",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Tier and horizon: `{meta['tier']}` (`{meta['tiers_version']}`, `{meta['n_employees']}` employees, `{meta['n_days']}` days)",
        f"- Seeds and sampled days: seeds `{meta['seeds']}` across days `{meta['days']}` (`{meta['n_samples']}` snapshots)",
        f"- Messages generated: `{meta['n_messages']}` (`{meta['n_llm_messages']}` live model, `{meta['n_fallback_messages']}` fallback)",
        f"- Token usage: `{u['input_tokens']}` input, `{u['output_tokens']}` candidate output, `{u['thinking_tokens']}` thinking, `{u['total_tokens']}` total across `{u['calls']}` calls (`${u['cost_usd']:.6f}`)",
        f"- Non-leak checks: `truth_leak_violations={meta['truth_leak_violations']}`, `lint_violations={meta['lint_violations']}`, `encoding_scan_violations={meta['encoding_scan_violations']}`",
        "",
        f"{MD_H2} SolverPolicy and ObviousHeuristic Parity on 40-Employee Hard Worlds",
        "",
        "| Seed | Template SolverPolicy | Biased-Chatter SolverPolicy | Template ObviousHeuristic | Biased-Chatter ObviousHeuristic | DoNothing | Biased Msgs Delivered |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in parity_doc["per_seed"]:
        ts_r = row["template_solver"]
        bs_r = row["biased_chatter_solver"]
        to_r = row["template_obvious_heuristic"]
        bo_r = row["biased_chatter_obvious_heuristic"]
        ts_tag = "ok" if ts_r["correct"] else "wrong"
        bs_tag = "ok" if bs_r["correct"] else "wrong"
        to_tag = "ok" if to_r["correct"] else "wrong"
        bo_tag = "ok" if bo_r["correct"] else "wrong"
        lines.append(
            f"| {row['seed']} | {ts_r['score']:+.4f} (d{ts_r['final_day']}, {ts_tag}) "
            f"| {bs_r['score']:+.4f} (d{bs_r['final_day']}, {bs_tag}) "
            f"| {to_r['score']:+.4f} (d{to_r['final_day']}, {to_tag}) "
            f"| {bo_r['score']:+.4f} (d{bo_r['final_day']}, {bo_tag}) "
            f"| {row['biased_chatter_do_nothing_score']:+.4f} | {row['biased_messages_delivered']} |"
        )

    lines.extend(
        [
            "",
            f"- `TemplateProvider` SolverPolicy catch rate: `{parity_doc['template_solver_catch_rate']:.2f}`, mean score: `{parity_doc['template_solver_mean_score']:+.4f}`",
            f"- `CachedBiasedChatterProvider` SolverPolicy catch rate: `{parity_doc['biased_chatter_solver_catch_rate']:.2f}`, mean score: `{parity_doc['biased_chatter_solver_mean_score']:+.4f}` (delta `{parity_doc['solver_mean_score_delta']:+.4f}`)",
            f"- `ObviousHeuristic` mean score: `{parity_doc['biased_chatter_obvious_heuristic_mean_score']:+.4f}` vs template `{parity_doc['template_obvious_heuristic_mean_score']:+.4f}`",
            f"- `SolverPolicy` minus `ObviousHeuristic` gap: `{parity_doc['solver_vs_obvious_gap']:+.4f}` (`parity_ok={parity_doc['parity_ok']}`, extra rollout API calls `{parity_doc['extra_api_calls_during_rollout']}`)",
            "",
            f"{MD_H2} Sampled Day Snapshots",
            "",
        ]
    )

    for s_item in samples_doc["samples"]:
        bs = s_item["bias_spec"]
        lines.append(
            f"{MD_H3} Seed `{s_item['seed']}` Day `{s_item['day']}` (`{s_item['company']}`, `{s_item['source']}`)"
        )
        lines.append("")
        lines.append(
            f"- Spec: rumour_target=`{bs['rumour_target']}`, grudge_pair=`{bs['grudge_pair'][0]},{bs['grudge_pair'][1]}`, "
            f"manager_id=`{bs['manager_id']}`, forwarded_doc_title=`{bs['forwarded_doc_title']}`"
        )
        for m in s_item["messages"]:
            snippet = scrub_dashes(m["body"])
            if len(snippet) > 130:
                snippet = snippet[:127] + "..."
            lines.append(
                f"  - `{m['id']}` [{m['bias_type']}] `{m['sender']}` -> `{','.join(m['recipients'])}` ({m['channel']}): {snippet}"
            )
        lines.append("")

    return scrub_dashes("\n".join(lines).rstrip() + "\n")


def run_biased_chatter_hard(
    out_dir: str | Path = DEFAULT_OUT,
    *,
    tier: str = DEFAULT_TIER,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    days: Sequence[int] = DEFAULT_DAYS,
    model: str = DEFAULT_MODEL,
    stub: bool = False,
    require_live: bool | None = None,
    thinking_level: str | None = None,
    client: Any = None,
    jobs: int = 4,
    max_attempts: int = 4,
    command_str: str | None = None,
) -> dict[str, Any]:
    effective_model = "stub" if stub else model
    is_stub_model = stub or effective_model == "stub" or effective_model.startswith("stub:")
    live_flag = (not is_stub_model) if require_live is None else bool(require_live)

    if live_flag and not is_stub_model:
        os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "8")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"{SUBROLE}:{effective_model}:{ts}"

    seed_list = [int(s) for s in seeds]
    day_list = sorted({int(d) for d in days})
    p = tier_params(tier)

    workers = 1 if (is_stub_model or client is not None or int(jobs) <= 1) else min(int(jobs), len(seed_list))

    def _run_one_seed(s: int) -> list[dict[str, Any]]:
        return generate_single_seed_days(
            tier=tier,
            seed=s,
            days=day_list,
            model=effective_model,
            client=client,
            run_id=run_id,
            thinking_level=thinking_level,
            require_live=live_flag,
            max_attempts=max_attempts,
        )

    samples: list[dict[str, Any]] = []
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for chunk in pool.map(_run_one_seed, seed_list):
                samples.extend(chunk)
    else:
        for s in seed_list:
            samples.extend(_run_one_seed(s))

    samples.sort(key=lambda item: (int(item["seed"]), int(item["day"])))

    parity_doc = verify_solver_parity_hard(
        tier=tier,
        seeds=seed_list,
        days=day_list,
        samples=samples,
        model_id=effective_model,
    )
    if not parity_doc["parity_ok"]:
        raise AssertionError(f"solver parity check failed: {parity_doc}")

    samples_doc = sanitize_for_storage(
        {
            "model_id": effective_model,
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "n_employees": int(p.n_employees),
            "n_days": int(p.n_days),
            "seeds": seed_list,
            "days": day_list,
            "n_samples": len(samples),
            "n_messages": sum(len(s["messages"]) for s in samples),
            "samples": samples,
        }
    )
    assert_no_truth(samples_doc, {})

    agg_usage = merge_usage([s["usage"] for s in samples])
    n_messages = sum(len(s["messages"]) for s in samples)
    n_llm_messages = sum(int(s["n_llm_messages"]) for s in samples)
    n_fallback_messages = sum(int(s["n_fallback_messages"]) for s in samples)
    truth_violations = sum(int(s["truth_leak_violations"]) for s in samples)
    lint_violations = sum(int(s["lint_violations"]) for s in samples)
    encoding_violations = sum(int(s["encoding_scan_violations"]) for s in samples)

    if live_flag:
        if n_llm_messages != n_messages or n_fallback_messages != 0:
            raise AssertionError(
                f"expected 100% live messages, got llm={n_llm_messages}, fallback={n_fallback_messages}"
            )

    meta = sanitize_for_storage(
        {
            "role": "world_text",
            "subrole": SUBROLE,
            "model_id": effective_model,
            "commit": git_commit(),
            "timestamp": ts,
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "n_employees": int(p.n_employees),
            "n_days": int(p.n_days),
            "seeds": seed_list,
            "days": day_list,
            "bias_patterns": list(BIAS_KINDS),
            "n_samples": len(samples),
            "n_messages": n_messages,
            "n_llm_messages": n_llm_messages,
            "n_fallback_messages": n_fallback_messages,
            "truth_leak_violations": truth_violations,
            "lint_violations": lint_violations,
            "encoding_scan_violations": encoding_violations,
            "solver_parity_ok": bool(parity_doc["parity_ok"]),
            "template_solver_catch_rate": parity_doc["template_solver_catch_rate"],
            "biased_chatter_solver_catch_rate": parity_doc["biased_chatter_solver_catch_rate"],
            "template_solver_mean_score": parity_doc["template_solver_mean_score"],
            "biased_chatter_solver_mean_score": parity_doc["biased_chatter_solver_mean_score"],
            "template_obvious_heuristic_mean_score": parity_doc["template_obvious_heuristic_mean_score"],
            "biased_chatter_obvious_heuristic_mean_score": parity_doc[
                "biased_chatter_obvious_heuristic_mean_score"
            ],
            "stub": bool(stub or effective_model == "stub"),
            "fake_env": False,
            "smoke": False,
            "ledger_run_id": run_id,
            "command": command_str or format_command(None),
            "usage": agg_usage,
        }
    )

    summary_md = render_summary_md(meta, samples_doc, parity_doc)

    (out_path / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_path / "chatter_samples.json").write_text(
        json.dumps(samples_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_path / "solver_parity.json").write_text(
        json.dumps(parity_doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_path / "summary.md").write_text(summary_md, encoding="utf-8")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/run_biased_chatter_hard.py")
    ap.add_argument("--tier", default=DEFAULT_TIER)
    ap.add_argument("--seeds", default="0,1,2,3")
    ap.add_argument("--days", default="1,4,8")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    ap.add_argument("--allow-fallback", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--max-attempts", type=int, default=4)
    args = ap.parse_args(list(argv) if argv is not None else None)

    seed_list = parse_int_list(args.seeds)
    day_list = parse_int_list(args.days)
    if args.stub or args.allow_fallback:
        req_live: bool | None = False
    elif args.require_live:
        req_live = True
    else:
        req_live = None

    meta = run_biased_chatter_hard(
        args.out,
        tier=args.tier,
        seeds=seed_list,
        days=day_list,
        model=args.model,
        stub=bool(args.stub),
        require_live=req_live,
        thinking_level=args.thinking_level,
        jobs=args.jobs,
        max_attempts=args.max_attempts,
        command_str=format_command(argv),
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "model_id": meta["model_id"],
                "n_samples": meta["n_samples"],
                "n_messages": meta["n_messages"],
                "n_llm_messages": meta["n_llm_messages"],
                "solver_parity_ok": meta["solver_parity_ok"],
                "usage": meta["usage"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
