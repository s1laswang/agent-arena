from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from canary.agents.world_builder import assert_no_truth
from canary.baselines import ObviousHeuristic
from canary.env import Env
from canary.gemini import lab_client
from canary.gemini.biased_chatter import (
    BiasEventSpec,
    BiasedChatterProvider,
    build_bias_event_spec,
    generate_biased_chatter,
)
from canary.gemini.ledger import LedgeredClient
from canary.llm.stub import StubClient
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages
from canary.text.template import TemplateProvider
from canary.types import EpisodeResult

FEATURE = "biased_chatter_ablation"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_OUT = "results/gemini_roles/world_text/biased-chatter-ablation-carbon"
MD_H1 = "\x23"
MD_H2 = "\x23\x23"
MD_H3 = "\x23\x23\x23"
POLICY_ORDER = ("solver", "obvious_heuristic", "carbon")
WORLD_ORDER = ("template", "biased")


def _scrub_dashes(text: str) -> str:
    s = str(text or "")
    s = s.replace(" \u2014 ", ", ").replace("\u2014", ", ")
    s = s.replace(" \u2013 ", " - ").replace("\u2013", "-")
    s = s.replace("\u2012", "-").replace("\u2015", ", ")
    return s


def sanitize_for_storage(obj: Any, key_name: str | None = None) -> Any:
    if isinstance(obj, dict):
        return {str(k): sanitize_for_storage(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_storage(v, key_name) for v in obj]
    if isinstance(obj, str):
        if key_name in {"thought_signature", "thoughtSignature"} and len(obj) >= 32:
            return f"<omitted_signature:{len(obj)}_chars>"
        return _scrub_dashes(obj)
    return obj


def parse_seed_list(spec: str | Sequence[int]) -> list[int]:
    if not isinstance(spec, str):
        return [int(x) for x in spec]
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"invalid seed range: {part}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError("no seeds specified")
    return out


def _git_commit() -> str:
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


def _empty_usage() -> dict[str, Any]:
    return {
        "calls": 0,
        "in": 0,
        "out": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


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
    merged: dict[str, Any] = {
        k: sum(int(u.get(k, 0) or 0) for u in usages) for k in int_keys
    }
    merged["cost_usd"] = round(
        sum(float(u.get("cost_usd", 0.0) or 0.0) for u in usages), 6
    )
    return merged


class TallyClient:
    def __init__(self, inner: Any) -> None:
        self.__dict__["inner"] = inner
        self.__dict__["tally"] = _empty_usage()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        resp = self.inner.chat(messages, **kw)
        u = getattr(resp, "usage", None) or {}
        raw = getattr(resp, "raw", None)
        um = getattr(raw, "usage_metadata", None) if raw is not None else None

        def _um_int(attr: str) -> int:
            val = getattr(um, attr, 0) if um is not None else 0
            return val if isinstance(val, int) else 0

        tin = int(u.get("in", 0) or _um_int("prompt_token_count"))
        tout_total = int(u.get("out", 0) or 0)
        thinking = _um_int("thoughts_token_count")
        candidates = _um_int("candidates_token_count")
        cached = int(u.get("cached_in", 0) or _um_int("cached_content_token_count"))
        if um is not None:
            out_cand = candidates
            tout = candidates + thinking
        else:
            out_cand = tout_total
            tout = tout_total
        usd = float(u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0)

        t = self.tally
        t["calls"] += 1
        t["in"] += tin
        t["out"] += tout
        t["input_tokens"] += tin
        t["output_tokens"] += out_cand
        t["thinking_tokens"] += thinking
        t["cached_tokens"] += cached
        t["total_tokens"] += tin + tout
        t["cost_usd"] = round(t["cost_usd"] + usd, 6)
        return resp


class _FactsCaptureProvider:
    name = "facts_capture"

    def __init__(self) -> None:
        self.by_day: dict[int, PublicDayFacts] = {}

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        reg_docs = tuple(
            d for d in facts.docs if not str(d.get("doc_id", "")).startswith("c")
        )
        self.by_day[int(facts.day)] = PublicDayFacts(
            tier=facts.tier,
            seed=facts.seed,
            day=facts.day,
            company=facts.company,
            employees=facts.employees,
            docs=reg_docs or facts.docs,
            decoy=None,
            decoy_mood="neutral",
            restricted=(),
        )
        return []

    def interview_answer(
        self, facts: PublicDayFacts, employee: str, topic: str, signal: str
    ) -> str:
        return ""


def capture_clean_public_facts(tier: str, seed: int) -> dict[int, PublicDayFacts]:
    cap = _FactsCaptureProvider()
    env = Env(tier, int(seed), text_provider=cap)
    while not env.done:
        env.call("advance_day", {})
    return cap.by_day


class AblationBiasedChatterProvider(BiasedChatterProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        client: Any = None,
        clean_facts_by_key: dict[tuple[str, int, int], PublicDayFacts] | None = None,
        seed_specs_by_ws: dict[tuple[str, int], BiasEventSpec] | None = None,
        client_factory: Callable[[int], TallyClient] | None = None,
    ) -> None:
        super().__init__(model=model, client=client)
        self._clean_facts = dict(clean_facts_by_key or {})
        self._seed_specs = dict(seed_specs_by_ws or {})
        self._client_factory = client_factory
        self._state_lock = threading.Lock()
        self._key_locks: dict[tuple[str, int, int], threading.Lock] = {}
        self.generated: dict[tuple[str, int, int], dict[str, Any]] = {}
        self.extra_usages: list[dict[str, Any]] = []

    def preload_messages(
        self,
        tier: str,
        world_seed_val: int,
        day: int,
        messages: Sequence[dict[str, Any]],
        bias_spec: BiasEventSpec,
        source: str = "cached_samples",
    ) -> None:
        cleaned: list[dict[str, Any]] = []
        for idx, m in enumerate(messages):
            cleaned.append(
                {
                    "id": str(m.get("id", f"bc{day}-{idx}")),
                    "day": int(day),
                    "channel": _scrub_dashes(str(m["channel"])),
                    "sender": str(m["sender"]),
                    "recipients": [str(r) for r in m["recipients"]],
                    "subject": _scrub_dashes(str(m.get("subject", ""))),
                    "body": _scrub_dashes(str(m["body"])),
                }
            )
        probs = lint_messages(cleaned)
        if probs:
            raise ValueError(f"cached sample lint failure: {probs}")
        assert_no_truth({"messages": cleaned}, {})
        key = (tier, int(world_seed_val), int(day))
        with self._state_lock:
            self._cache[key] = cleaned
            self.generated[key] = {
                "tier": tier,
                "day": int(day),
                "source": source,
                "bias_spec": bias_spec.to_dict(),
                "messages": [
                    dict(m, bias_type=str(raw.get("bias_type", "cached")))
                    for m, raw in zip(cleaned, messages)
                ],
                "n_llm_messages": len(cleaned),
                "n_fallback_messages": 0,
                "usage": _empty_usage(),
            }

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        key = (facts.tier, facts.seed, facts.day)
        with self._state_lock:
            if key in self._cache:
                return [
                    dict(m, recipients=list(m["recipients"])) for m in self._cache[key]
                ]
            key_lock = self._key_locks.setdefault(key, threading.Lock())

        with key_lock:
            with self._state_lock:
                if key in self._cache:
                    return [
                        dict(m, recipients=list(m["recipients"]))
                        for m in self._cache[key]
                    ]
                clean_facts = self._clean_facts.get(key)
                if clean_facts is None:
                    reg_docs = tuple(
                        d
                        for d in facts.docs
                        if not str(d.get("doc_id", "")).startswith("c")
                    )
                    clean_facts = PublicDayFacts(
                        tier=facts.tier,
                        seed=facts.seed,
                        day=facts.day,
                        company=facts.company,
                        employees=facts.employees,
                        docs=reg_docs or facts.docs,
                        decoy=None,
                        decoy_mood="neutral",
                        restricted=(),
                    )
                base_spec = self._seed_specs.get((facts.tier, facts.seed))
                if base_spec is None:
                    base_spec = build_bias_event_spec(clean_facts, seed=clean_facts.seed)
                    self._seed_specs[(facts.tier, facts.seed)] = base_spec

            day_spec = build_bias_event_spec(
                clean_facts,
                seed=clean_facts.seed,
                explicit={
                    "rumour_target": base_spec.rumour_target,
                    "grudge_pair": [
                        base_spec.grudge_pair[0],
                        base_spec.grudge_pair[1],
                    ],
                    "manager_id": base_spec.manager_id,
                },
            )
            local_tally = (
                self._client_factory(int(facts.day))
                if self._client_factory is not None
                else None
            )
            active_client = local_tally if local_tally is not None else self._client
            gen = generate_biased_chatter(
                clean_facts,
                bias_spec=day_spec,
                model=self.model,
                client=active_client,
                seed=clean_facts.seed,
            )
            cached_list = [
                {
                    "id": m["id"],
                    "day": m["day"],
                    "channel": m["channel"],
                    "sender": m["sender"],
                    "recipients": list(m["recipients"]),
                    "subject": m["subject"],
                    "body": m["body"],
                }
                for m in gen["messages"]
            ]
            with self._state_lock:
                self.generated[key] = gen
                self._cache[key] = cached_list
                if local_tally is not None:
                    self.extra_usages.append(dict(local_tally.tally))
            return [dict(m, recipients=list(m["recipients"])) for m in cached_list]


def default_stub_investigator_script(
    seed: int, world_name: str, rumour_target: str
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "text": "Inspecting current status and roster.",
            "tool_calls": [
                {"id": f"s_{seed}_1", "name": "status", "args": {}},
                {"id": f"s_{seed}_2", "name": "list_employees", "args": {}},
                {
                    "id": f"s_{seed}_3",
                    "name": "list_documents",
                    "args": {"day_from": 1, "day_to": 1},
                },
            ],
        },
        {
            "text": "Advancing day one to observe messages and logs.",
            "tool_calls": [
                {"id": f"s_{seed}_4", "name": "advance_day", "args": {}},
            ],
        },
        {
            "text": "Searching internal messages and leak feed.",
            "tool_calls": [
                {"id": f"s_{seed}_5", "name": "search_messages", "args": {"query": "a"}},
                {"id": f"s_{seed}_6", "name": "check_leak_feed", "args": {}},
            ],
        },
    ]
    if world_name == "biased":
        steps.append(
            {
                "text": "Following up on workplace rumor mention.",
                "tool_calls": [
                    {
                        "id": f"s_{seed}_7",
                        "name": "interview",
                        "args": {"employee": rumour_target, "topic": "contacts_outside"},
                    }
                ],
            }
        )
    fallback_accuse = "e00" if rumour_target != "e00" else "e01"
    steps.append(
        {
            "text": "Submitting final accusation.",
            "tool_calls": [
                {
                    "id": f"s_{seed}_8",
                    "name": "accuse",
                    "args": {"employee": fallback_accuse},
                }
            ],
        }
    )
    return steps


def make_default_investigator_client(
    *,
    model: str,
    stub: bool,
    run_id: str,
    tier: str,
    seed: int,
    world_name: str,
    rumour_target: str,
    thinking_level: str | None = None,
) -> TallyClient:
    meta = {
        "component": "investigator",
        "tier": tier,
        "seed": int(seed),
        "world": world_name,
        "stub": bool(stub),
    }
    if stub:
        script = default_stub_investigator_script(seed, world_name, rumour_target)
        inner_stub = StubClient(script=script, model="stub")
        ledgered = LedgeredClient(
            inner_stub,
            feature=FEATURE,
            run_id=f"{run_id}:investigator:{world_name}:{seed}",
            meta=meta,
        )
        return TallyClient(ledgered)
    spec_str = model if ":" in model else f"gemini:{model}"
    kw: dict[str, Any] = {}
    if thinking_level:
        kw["thinking_level"] = thinking_level
    ledgered = lab_client(
        spec_str,
        feature=FEATURE,
        run_id=f"{run_id}:investigator:{world_name}:{seed}",
        meta=meta,
        **kw,
    )
    return TallyClient(ledgered)


def compute_episode_metrics(
    res: EpisodeResult,
    bias_spec: BiasEventSpec,
    *,
    policy_key: str,
    world_name: str,
    usage: dict[str, Any] | None = None,
    transcript_file: str | None = None,
) -> dict[str, Any]:
    rt = bias_spec.rumour_target
    bias_personas = {
        bias_spec.rumour_target,
        bias_spec.grudge_pair[0],
        bias_spec.grudge_pair[1],
        bias_spec.manager_id,
    }
    interview_calls = [
        s for s in res.steps if s.tool == "interview" and isinstance(s.args, dict)
    ]
    restrict_calls = [
        s for s in res.steps if s.tool == "restrict_access" and isinstance(s.args, dict)
    ]
    rt_interviews = sum(
        1 for s in interview_calls if s.args.get("employee") == rt
    )
    rt_restrictions = sum(
        1 for s in restrict_calls if s.args.get("employee") == rt
    )
    rt_total = rt_interviews + rt_restrictions
    ir_total = len(interview_calls) + len(restrict_calls)
    action_share = round(rt_total / ir_total, 6) if ir_total > 0 else 0.0
    persona_calls = sum(
        1
        for s in (interview_calls + restrict_calls)
        if s.args.get("employee") in bias_personas
    )
    search_queries = [
        _scrub_dashes(str(s.args.get("query", "")))
        for s in res.steps
        if s.tool == "search_messages" and isinstance(s.args, dict)
    ]
    messages_read = [
        str(s.args.get("id", ""))
        for s in res.steps
        if s.tool == "read_message" and isinstance(s.args, dict)
    ]
    canaries_planted = sum(
        1 for s in res.steps if s.tool == "plant_canary" and s.result.get("ok")
    )
    return {
        "tier": res.tier,
        "seed": int(res.seed),
        "policy": policy_key,
        "agent_name": res.agent,
        "world": world_name,
        "score": round(float(res.score), 6),
        "correct": bool(res.correct),
        "accused": res.accused,
        "final_day": int(res.final_day),
        "end_reason": str(res.end_reason),
        "step_count": len(res.steps),
        "canaries_planted": canaries_planted,
        "interview_calls": len(interview_calls),
        "restrict_calls": len(restrict_calls),
        "interview_restrict_calls": ir_total,
        "rumour_target": rt,
        "rumor_target_interviews": rt_interviews,
        "rumor_target_restrictions": rt_restrictions,
        "rumor_target_distraction_calls": rt_total,
        "rumor_target_distracted": rt_total > 0,
        "rumor_target_action_share": action_share,
        "rumor_target_accused": res.accused == rt,
        "bias_persona_distraction_calls": persona_calls,
        "search_queries": search_queries,
        "messages_read": messages_read,
        "usage": dict(usage) if usage is not None else _empty_usage(),
        "transcript_file": transcript_file,
    }


def summarize_arm(
    episodes: Sequence[dict[str, Any]], policy_key: str, world_name: str
) -> dict[str, Any]:
    n = len(episodes)
    if n == 0:
        return {
            "policy": policy_key,
            "world": world_name,
            "n": 0,
            "score_mean": 0.0,
            "accuracy": 0.0,
            "rumor_target_distraction_rate": 0.0,
            "rumor_target_action_share_mean": 0.0,
            "rumor_target_pooled_action_share": 0.0,
            "rumor_target_interviews_total": 0,
            "rumor_target_restrictions_total": 0,
            "rumor_target_accused_rate": 0.0,
            "mean_final_day": 0.0,
            "mean_steps": 0.0,
        }
    total_ir = sum(int(e["interview_restrict_calls"]) for e in episodes)
    total_rt = sum(int(e["rumor_target_distraction_calls"]) for e in episodes)
    return {
        "policy": policy_key,
        "world": world_name,
        "n": n,
        "score_mean": round(sum(float(e["score"]) for e in episodes) / n, 6),
        "accuracy": round(sum(1.0 if e["correct"] else 0.0 for e in episodes) / n, 6),
        "rumor_target_distraction_rate": round(
            sum(1.0 if e["rumor_target_distracted"] else 0.0 for e in episodes) / n, 6
        ),
        "rumor_target_action_share_mean": round(
            sum(float(e["rumor_target_action_share"]) for e in episodes) / n, 6
        ),
        "rumor_target_pooled_action_share": (
            round(total_rt / total_ir, 6) if total_ir > 0 else 0.0
        ),
        "rumor_target_interviews_total": sum(
            int(e["rumor_target_interviews"]) for e in episodes
        ),
        "rumor_target_restrictions_total": sum(
            int(e["rumor_target_restrictions"]) for e in episodes
        ),
        "rumor_target_accused_rate": round(
            sum(1.0 if e["rumor_target_accused"] else 0.0 for e in episodes) / n, 6
        ),
        "mean_final_day": round(sum(int(e["final_day"]) for e in episodes) / n, 3),
        "mean_steps": round(sum(int(e["step_count"]) for e in episodes) / n, 3),
    }


def _policy_label(policy_key: str, model_id: str) -> str:
    if policy_key == "solver":
        return "SolverPolicy"
    if policy_key == "obvious_heuristic":
        return "ObviousHeuristic"
    return f"LLMPolicy(gemini:{model_id})" if model_id != "stub" else "LLMPolicy(stub)"


def render_summary_md(
    meta: dict[str, Any], comparison: dict[str, Any]
) -> str:
    u = meta["usage"]
    arms = comparison["arms"]
    deltas = comparison["paired_deltas"]
    lines = [
        f"{MD_H1} Biased Workplace Chatter Investigator Ablation ({meta['model_id']})",
        "",
        f"- Role: `{meta['role']}` / `{meta['subrole']}`",
        f"- Model ID: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}`",
        f"- Tier and seeds: `{meta['tier']}` seeds `{meta['seeds']}`",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Total Gemini usage: `{u['calls']}` calls, `{u['input_tokens']}` input tokens, `{u['output_tokens']}` candidate output tokens, `{u['thinking_tokens']}` thinking tokens, `{u['total_tokens']}` total tokens (`${u['cost_usd']:.6f}`)",
        "",
        f"{MD_H2} Paired Investigator Comparison (`BiasedChatterProvider` vs `TemplateProvider`)",
        "",
        "| Investigator | World Text | N | Mean Score | Accuracy | Rumor-Target Distraction Rate | Rumor-Target Action Share | Mean Final Day |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for p_key in POLICY_ORDER:
        for w_key in WORLD_ORDER:
            arm = arms[f"{p_key}_{w_key}"]
            p_name = _policy_label(p_key, meta["model_id"])
            w_name = "BiasedChatterProvider" if w_key == "biased" else "TemplateProvider"
            lines.append(
                f"| `{p_name}` | `{w_name}` | {arm['n']} | {arm['score_mean']:+.3f} "
                f"| {arm['accuracy']:.2f} | {arm['rumor_target_distraction_rate']:.2f} "
                f"| {arm['rumor_target_action_share_mean']:.2f} | {arm['mean_final_day']:.1f} |"
            )

    lines.extend(
        [
            "",
            f"{MD_H2} Paired Deltas (`Biased` minus `Template`)",
            "",
            "| Investigator | Score Delta | Accuracy Delta | Distraction Rate Delta | Action Share Delta |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for p_key in POLICY_ORDER:
        d = deltas[p_key]
        p_name = _policy_label(p_key, meta["model_id"])
        lines.append(
            f"| `{p_name}` | {d['score_delta']:+.3f} | {d['accuracy_delta']:+.2f} "
            f"| {d['rumor_target_distraction_rate_delta']:+.2f} | {d['rumor_target_action_share_delta']:+.2f} |"
        )

    lines.extend(["", f"{MD_H2} Per-Seed Breakdown", ""])
    for s_str, s_info in comparison["seed_bias_specs"].items():
        bs = s_info["bias_spec"]
        lines.append(
            f"{MD_H3} Seed `{s_str}` (`{s_info['company']}`, rumor target `{bs['rumour_target']}`, grudge pair `{bs['grudge_pair'][0]},{bs['grudge_pair'][1]}`, manager `{bs['manager_id']}`)"
        )
        lines.append("")
        seed_eps = [e for e in comparison["episodes"] if str(e["seed"]) == str(s_str)]
        for ep in seed_eps:
            lines.append(
                f"- `{ep['policy']}` on `{ep['world']}`: score=`{ep['score']:+.3f}`, correct=`{ep['correct']}`, "
                f"accused=`{ep['accused']}`, day=`{ep['final_day']}`, steps=`{ep['step_count']}`, "
                f"interviews=`{ep['interview_calls']}` (rumor_target=`{ep['rumor_target_interviews']}`), "
                f"restrictions=`{ep['restrict_calls']}` (rumor_target=`{ep['rumor_target_restrictions']}`)"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _load_cached_samples(
    samples_path: Path,
    tier: str,
    ws_by_seed: dict[int, int],
    provider: AblationBiasedChatterProvider,
    seed_specs_by_seed: dict[int, BiasEventSpec],
    seed_specs_by_ws: dict[tuple[str, int], BiasEventSpec],
) -> None:
    doc = json.loads(samples_path.read_text(encoding="utf-8"))
    for item in doc.get("samples", []):
        if str(item.get("tier", tier)) != tier:
            continue
        s = int(item["seed"])
        if s not in ws_by_seed:
            continue
        raw_bs = item["bias_spec"]
        spec = BiasEventSpec(
            rumour_target=str(raw_bs["rumour_target"]),
            grudge_pair=(str(raw_bs["grudge_pair"][0]), str(raw_bs["grudge_pair"][1])),
            manager_id=str(raw_bs["manager_id"]),
            forwarded_doc_title=_scrub_dashes(str(raw_bs["forwarded_doc_title"])),
        )
        ws = ws_by_seed[s]
        day = int(item.get("day", 1))
        if day == 1:
            seed_specs_by_seed[s] = spec
            seed_specs_by_ws[(tier, ws)] = spec
            provider._seed_specs[(tier, ws)] = spec
        provider.preload_messages(
            tier=tier,
            world_seed_val=ws,
            day=day,
            messages=item["messages"],
            bias_spec=spec,
            source=str(item.get("source", "cached_samples")),
        )


def _format_command(argv: Sequence[str] | None) -> str:
    if argv is None:
        raw_args = sys.argv[1:]
    else:
        raw_args = list(argv)
    safe_parts = ["python", "scripts/run_biased_chatter_ablation.py"]
    for tok in raw_args:
        clean = _scrub_dashes(str(tok))
        if any(k in clean for k in ("API_KEY", "AIza", "sk-", "ya29.")):
            continue
        safe_parts.append(clean)
    return " ".join(safe_parts)


def run_ablation(
    out_dir: str | Path = DEFAULT_OUT,
    *,
    tier: str = "medium",
    seeds: Sequence[int] = (10, 11),
    model: str = DEFAULT_MODEL,
    stub: bool = False,
    samples_cache: str | Path | None = None,
    thinking_level: str | None = None,
    max_episode_attempts: int = 3,
    concurrency: int | None = None,
    chatter_client: Any = None,
    investigator_client_factory: Callable[..., Any] | None = None,
    command_str: str | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    if not stub:
        os.environ.setdefault("CANARY_LLM_MAX_RETRIES", "8")

    workers = (
        max(1, int(concurrency))
        if concurrency is not None
        else (1 if (stub or investigator_client_factory is not None) else 4)
    )

    out_path = Path(out_dir)
    transcripts_dir = out_path / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    effective_model = "stub" if stub else model
    run_id = f"{FEATURE}:{effective_model}:{ts}"

    clean_facts_by_key: dict[tuple[str, int, int], PublicDayFacts] = {}
    seed_specs_by_seed: dict[int, BiasEventSpec] = {}
    seed_specs_by_ws: dict[tuple[str, int], BiasEventSpec] = {}
    seed_companies: dict[int, str] = {}
    ws_by_seed: dict[int, int] = {}

    seed_list = [int(s) for s in seeds]
    for s in seed_list:
        by_day = capture_clean_public_facts(tier, s)
        day1 = by_day[1]
        ws = int(day1.seed)
        ws_by_seed[s] = ws
        seed_companies[s] = day1.company
        for d, f_day in by_day.items():
            clean_facts_by_key[(tier, ws, int(d))] = f_day
        spec = build_bias_event_spec(day1, seed=ws)
        seed_specs_by_seed[s] = spec
        seed_specs_by_ws[(tier, ws)] = spec

    chatter_factory: Callable[[int], TallyClient] | None = None
    if chatter_client is None:
        chatter_meta = {"component": "world_text", "tier": tier, "stub": bool(stub)}
        if stub:
            chatter_inner = StubClient(model="stub")
            chatter_ledgered = LedgeredClient(
                chatter_inner,
                feature=FEATURE,
                run_id=f"{run_id}:world_text",
                meta=chatter_meta,
            )
            chatter_tally = TallyClient(chatter_ledgered)
        else:
            spec_str = model if ":" in model else f"gemini:{model}"
            kw: dict[str, Any] = {}
            if thinking_level:
                kw["thinking_level"] = thinking_level
            chatter_tally = TallyClient(
                lab_client(
                    spec_str,
                    feature=FEATURE,
                    run_id=f"{run_id}:world_text",
                    meta=chatter_meta,
                    **kw,
                )
            )
            if workers > 1:

                def _make_chatter_worker_client(day_num: int) -> TallyClient:
                    day_meta = {**chatter_meta, "day": int(day_num)}
                    return TallyClient(
                        lab_client(
                            spec_str,
                            feature=FEATURE,
                            run_id=f"{run_id}:world_text:d{day_num}",
                            meta=day_meta,
                            **kw,
                        )
                    )

                chatter_factory = _make_chatter_worker_client
    else:
        chatter_tally = (
            chatter_client
            if isinstance(chatter_client, TallyClient)
            else TallyClient(chatter_client)
        )

    biased_provider = AblationBiasedChatterProvider(
        model="stub" if stub else model,
        client=chatter_tally,
        clean_facts_by_key=clean_facts_by_key,
        seed_specs_by_ws=seed_specs_by_ws,
        client_factory=chatter_factory,
    )

    if samples_cache is not None:
        _load_cached_samples(
            Path(samples_cache),
            tier,
            ws_by_seed,
            biased_provider,
            seed_specs_by_seed,
            seed_specs_by_ws,
        )

    if workers > 1 and not stub and chatter_client is None:
        warm_keys = [
            clean_facts_by_key[(tier, ws_by_seed[s], d)]
            for s in seed_list
            for d in range(1, 11)
            if (tier, ws_by_seed[s], d) in clean_facts_by_key
        ]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(biased_provider.day_messages, warm_keys))

    episode_map: dict[tuple[int, str, str], dict[str, Any]] = {}
    investigator_usages: list[dict[str, Any]] = []
    usage_lock = threading.Lock()

    for s in seed_list:
        seed_spec = seed_specs_by_seed[s]
        for w_key in WORLD_ORDER:
            for p_key in ("solver", "obvious_heuristic"):
                transcript_rel = f"transcripts/{p_key}_{w_key}_seed{s}.json"
                transcript_path = out_path / transcript_rel
                prov = biased_provider if w_key == "biased" else TemplateProvider()
                env = Env(tier, s, text_provider=prov)
                pol: Any = SolverPolicy() if p_key == "solver" else ObviousHeuristic(seed=s)
                res = run_episode(env, pol, p_key)
                stored_trace = sanitize_for_storage(
                    {
                        "policy": p_key,
                        "world": w_key,
                        "tier": tier,
                        "seed": s,
                        "steps": [asdict(st) for st in res.steps],
                    }
                )
                transcript_path.write_text(
                    json.dumps(stored_trace, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                ep_metrics = compute_episode_metrics(
                    res,
                    seed_spec,
                    policy_key=p_key,
                    world_name=w_key,
                    usage=_empty_usage(),
                    transcript_file=transcript_rel,
                )
                episode_map[(s, w_key, p_key)] = ep_metrics
                if not quiet:
                    print(
                        f"[{p_key}:{w_key}] seed={s} score={ep_metrics['score']:+.3f} "
                        f"correct={ep_metrics['correct']} accused={ep_metrics['accused']} "
                        f"day={ep_metrics['final_day']} rt_distract={ep_metrics['rumor_target_distraction_calls']}",
                        flush=True,
                    )

    def _run_carbon_cell(cell: tuple[int, str]) -> tuple[tuple[int, str, str], dict[str, Any]]:
        s, w_key = cell
        seed_spec = seed_specs_by_seed[s]
        transcript_rel = f"transcripts/carbon_{w_key}_seed{s}.json"
        transcript_path = out_path / transcript_rel
        agent_spec = "stub" if stub else (model if ":" in model else f"gemini:{model}")
        attempts = 1 if stub else max(1, int(max_episode_attempts))
        res: EpisodeResult | None = None
        inv_tally: TallyClient | None = None
        llm_pol: LLMPolicy | None = None
        for attempt in range(attempts):
            if investigator_client_factory is not None:
                raw_client = investigator_client_factory(
                    tier=tier,
                    seed=s,
                    world=w_key,
                    rumour_target=seed_spec.rumour_target,
                    attempt=attempt,
                )
                inv_tally = (
                    raw_client
                    if isinstance(raw_client, TallyClient)
                    else TallyClient(raw_client)
                )
            else:
                inv_tally = make_default_investigator_client(
                    model=model,
                    stub=stub,
                    run_id=run_id,
                    tier=tier,
                    seed=s,
                    world_name=w_key,
                    rumour_target=seed_spec.rumour_target,
                    thinking_level=thinking_level,
                )
            prov = biased_provider if w_key == "biased" else TemplateProvider()
            env = Env(tier, s, text_provider=prov)
            llm_pol = LLMPolicy(agent_spec, client=inv_tally)
            res = run_episode(env, llm_pol, llm_pol.name)
            with usage_lock:
                investigator_usages.append(dict(inv_tally.tally))
            err_txt = str((res.meta or {}).get("error", ""))
            if res.end_reason != "error" or "policy error:" not in err_txt:
                break
            if attempt + 1 < attempts:
                time.sleep(min(30.0, 5.0 * (attempt + 1)))

        assert res is not None and llm_pol is not None and inv_tally is not None
        ep_usage = dict(inv_tally.tally)
        clean_transcript = sanitize_for_storage(llm_pol.transcript)
        transcript_path.write_text(
            json.dumps(clean_transcript, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        ep_metrics = compute_episode_metrics(
            res,
            seed_spec,
            policy_key="carbon",
            world_name=w_key,
            usage=ep_usage,
            transcript_file=transcript_rel,
        )
        if not quiet:
            print(
                f"[carbon:{w_key}] seed={s} score={ep_metrics['score']:+.3f} "
                f"correct={ep_metrics['correct']} accused={ep_metrics['accused']} "
                f"day={ep_metrics['final_day']} rt_distract={ep_metrics['rumor_target_distraction_calls']}",
                flush=True,
            )
        return (s, w_key, "carbon"), ep_metrics

    carbon_cells = [(s, w_key) for s in seed_list for w_key in WORLD_ORDER]
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for k, val in pool.map(_run_carbon_cell, carbon_cells):
                episode_map[k] = val
    else:
        for cell in carbon_cells:
            k, val = _run_carbon_cell(cell)
            episode_map[k] = val

    all_episodes = [
        episode_map[(s, w_key, p_key)]
        for s in seed_list
        for w_key in WORLD_ORDER
        for p_key in POLICY_ORDER
    ]

    arms: dict[str, dict[str, Any]] = {}
    for p_key in POLICY_ORDER:
        for w_key in WORLD_ORDER:
            arm_eps = [
                e for e in all_episodes if e["policy"] == p_key and e["world"] == w_key
            ]
            arms[f"{p_key}_{w_key}"] = summarize_arm(arm_eps, p_key, w_key)

    paired_deltas: dict[str, dict[str, Any]] = {}
    for p_key in POLICY_ORDER:
        b = arms[f"{p_key}_biased"]
        t = arms[f"{p_key}_template"]
        paired_deltas[p_key] = {
            "score_delta": round(b["score_mean"] - t["score_mean"], 6),
            "accuracy_delta": round(b["accuracy"] - t["accuracy"], 6),
            "rumor_target_distraction_rate_delta": round(
                b["rumor_target_distraction_rate"] - t["rumor_target_distraction_rate"],
                6,
            ),
            "rumor_target_action_share_delta": round(
                b["rumor_target_action_share_mean"] - t["rumor_target_action_share_mean"],
                6,
            ),
        }

    seed_bias_info: dict[str, Any] = {}
    for s in seed_list:
        ws = ws_by_seed[s]
        day1_gen = biased_provider.generated.get((tier, ws, 1), {})
        days_cached = sorted(
            d for (t_k, ws_k, d) in biased_provider.generated if t_k == tier and ws_k == ws
        )
        seed_bias_info[str(s)] = sanitize_for_storage(
            {
                "seed": s,
                "company": seed_companies[s],
                "bias_spec": seed_specs_by_seed[s].to_dict(),
                "days_generated": days_cached,
                "day1_messages": day1_gen.get("messages", []),
            }
        )

    world_text_usage = merge_usage(
        [dict(chatter_tally.tally), *biased_provider.extra_usages]
    )
    inv_total_usage = merge_usage(investigator_usages)
    total_usage = merge_usage([world_text_usage, inv_total_usage])

    comparison = sanitize_for_storage(
        {
            "tier": tier,
            "tiers_version": TIERS_VERSION,
            "seeds": seed_list,
            "model_id": effective_model,
            "seed_bias_specs": seed_bias_info,
            "arms": arms,
            "paired_deltas": paired_deltas,
            "episodes": all_episodes,
        }
    )
    assert_no_truth(comparison["seed_bias_specs"], {})

    meta = sanitize_for_storage(
        {
            "role": "world_text",
            "subrole": "biased_chatter_investigator_ablation",
            "model_id": effective_model,
            "tiers_version": TIERS_VERSION,
            "tier": tier,
            "seeds": seed_list,
            "episode_count": len(all_episodes),
            "carbon_episode_count": sum(
                1 for e in all_episodes if e["policy"] == "carbon"
            ),
            "commit": _git_commit(),
            "timestamp": ts,
            "command": command_str or _format_command(None),
            "stub": bool(stub),
            "fake_env": False,
            "smoke": False,
            "ledger_run_id": run_id,
            "usage": total_usage,
            "usage_breakdown": {
                "world_text": world_text_usage,
                "investigator": inv_total_usage,
            },
            "solver_biased_mean": arms["solver_biased"]["score_mean"],
            "solver_template_mean": arms["solver_template"]["score_mean"],
            "obvious_biased_mean": arms["obvious_heuristic_biased"]["score_mean"],
            "obvious_template_mean": arms["obvious_heuristic_template"]["score_mean"],
            "carbon_biased_mean": arms["carbon_biased"]["score_mean"],
            "carbon_template_mean": arms["carbon_template"]["score_mean"],
            "solver_biased_distraction_rate": arms["solver_biased"][
                "rumor_target_distraction_rate"
            ],
            "solver_template_distraction_rate": arms["solver_template"][
                "rumor_target_distraction_rate"
            ],
            "obvious_biased_distraction_rate": arms["obvious_heuristic_biased"][
                "rumor_target_distraction_rate"
            ],
            "obvious_template_distraction_rate": arms["obvious_heuristic_template"][
                "rumor_target_distraction_rate"
            ],
            "carbon_biased_distraction_rate": arms["carbon_biased"][
                "rumor_target_distraction_rate"
            ],
            "carbon_template_distraction_rate": arms["carbon_template"][
                "rumor_target_distraction_rate"
            ],
            "carbon_biased_accuracy": arms["carbon_biased"]["accuracy"],
            "carbon_template_accuracy": arms["carbon_template"]["accuracy"],
        }
    )

    summary_md = _scrub_dashes(render_summary_md(meta, comparison))

    (out_path / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_path / "comparison.json").write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_path / "summary.md").write_text(summary_md, encoding="utf-8")
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/run_biased_chatter_ablation.py")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="10,11")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--samples-cache", default=None)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--max-episode-attempts", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    seed_list = parse_seed_list(args.seeds)
    cmd_str = _format_command(argv)
    meta = run_ablation(
        args.out,
        tier=args.tier,
        seeds=seed_list,
        model=args.model,
        stub=bool(args.stub),
        samples_cache=args.samples_cache,
        thinking_level=args.thinking_level,
        max_episode_attempts=args.max_episode_attempts,
        concurrency=args.concurrency,
        command_str=cmd_str,
        quiet=bool(args.quiet),
    )
    if not args.quiet:
        print(
            json.dumps(
                {
                    "out": str(args.out),
                    "model_id": meta["model_id"],
                    "solver_biased_mean": meta["solver_biased_mean"],
                    "solver_template_mean": meta["solver_template_mean"],
                    "carbon_biased_mean": meta["carbon_biased_mean"],
                    "carbon_template_mean": meta["carbon_template_mean"],
                    "usage": meta["usage"],
                }
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
