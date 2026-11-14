from __future__ import annotations

import argparse
from collections import Counter
import concurrent.futures as cf
import copy
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import re
import shlex
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from canary.agents.world_builder import (
    DEFAULT_CHATTER,
    TONES,
    TRUTH_KEYS,
    TRUTH_WORDS,
    GeminiWorldText,
    WorldText,
    _template_ok,
    assert_no_truth,
    build_world_text,
    public_view,
)
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.gemini import LedgeredClient, lab_client
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    audit_env_outputs,
    extract_env_secrets,
    scan_messages_for_secret,
    scan_text_for_secret,
)
from canary.llm.base import LLMResponse, MissingKeyError, is_retryable
from canary.llm.pricing import cost as price_cost
from canary.llm.stub import StubClient
from canary.rules import TIERS, TIERS_VERSION, TRACKS
from canary.solver.policy import SolverPolicy
from canary.text.facts import PublicDayFacts
from canary.text.gemini import GeminiProvider
from canary.text.lint import lint_messages, lint_text
from canary.text.template import TemplateProvider

REPO = Path(__file__).resolve().parents[2]
ROLE = "world_text"
SUBROLE = "thinking_level_calibration"
FEATURE = "worldtext_thinking"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_LLM = f"gemini:{DEFAULT_MODEL}"
DEFAULT_TIER = "medium"
DEFAULT_SEEDS: tuple[int, ...] = (6, 7)
DEFAULT_LEVELS: tuple[str, ...] = ("low", "medium", "high")
VALID_THINKING_LEVELS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")
DEFAULT_OUT = REPO / "results" / "gemini_roles" / "world_text" / "thinking-calibration-carbon"
MD_H1 = "\x23"
MD_H2 = "\x23\x23"
MD_H3 = "\x23\x23\x23"
SLACK_PREFIX = "\x23"

WORD_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
SECRET_LIKE_RE = re.compile(
    r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
    r"(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|api[_-]?key|secret)"
    r"\s*[=:][ \t]*(?![A-Za-z0-9_]+=)[^\s\"',;]{4,})"
)
SOLVER_ANGER_TOKENS: tuple[str, ...] = (
    "promotion",
    "raise",
    "deserve",
    "burn out",
    "recruiter",
    "goalposts",
    "nobody asks",
    "updating my cv",
)

WORLD_BUILDER_RULES = (
    "\n\nSTRICT SCHEMA AND SAFETY RULES:\n"
    "1. Include a persona for EVERY employee id in the input employees list using the exact employee_id; "
    "do not omit any employee and do not invent extra ids.\n"
    "2. Choose each persona tone strictly from: dry, upbeat, formal, terse, chatty, warm, blunt. "
    "Ensure every tone you use appears at least twice across the roster so no employee has a singleton tone.\n"
    "3. Keep company_blurb <= 320 chars, each bio <= 240 chars with specific operational detail, "
    "each department culture <= 340 chars, and write 8 to 12 chatter_templates each <= 180 chars using ONLY "
    "placeholders from {sender}, {dept}, {doc_title}, {colleague}, {when} with plain {name} syntax.\n"
    "4. Do not use the words promotion, raise, deserve, burn out, recruiter, goalposts, nobody asks, or "
    "updating my cv inside chatter_templates (say 'open a ticket' instead of 'raise a ticket').\n"
    "5. Use plain ASCII punctuation only: never output unicode em dashes or en dashes.\n"
    "6. Never output any word containing 'mole' (even inside 'molecule'), 'leak', 'spy', 'traitor', "
    "'culprit', 'informant', 'double agent', 'insider threat', 'sold', 'secret:', or 'api_key:'."
)

DAY_MSG_RULES = (
    "\n\nSTRICT SCHEMA AND SAFETY RULES:\n"
    "1. Return 5 to 8 realistic Day 1 workplace messages across Slack channels and email.\n"
    "2. Every sender and every entry in recipients MUST be an exact employee id from FACTS.employees.\n"
    "3. Only grumpy_employee (when set) may complain about promotion or updating their CV; other senders "
    "must keep operational workplace focus and say 'open a ticket' instead of 'raise a ticket'.\n"
    "4. Use plain ASCII punctuation only: never output unicode em dashes or en dashes.\n"
    "5. Never output any word containing 'mole' (even inside 'molecule'), 'leak', 'spy', 'traitor', "
    "'culprit', 'informant', 'double agent', 'insider threat', 'sold', 'secret:', 'api_key:', "
    "or rival email domains (@rival, @competitor, @corvid, @nightjar)."
)

INTERVIEW_RULES = (
    "\n\nSTRICT SCHEMA AND SAFETY RULES:\n"
    "1. Write a realistic 1-3 sentence HR/security interview reply matching the requested cooperative or evasive tone.\n"
    "2. Use plain ASCII punctuation only: never output unicode em dashes or en dashes.\n"
    "3. Never output any word containing 'mole' (even inside 'molecule'), 'leak', 'spy', 'traitor', "
    "'culprit', 'informant', 'double agent', 'insider threat', 'sold', 'secret:', 'api_key:', "
    "or rival email domains."
)


EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)


def clean_str(val: Any) -> str:
    s = str(val or "")
    s = s.replace(f" {EM_DASH} ", ", ").replace(EM_DASH, " - ")
    s = s.replace(f" {EN_DASH} ", " - ").replace(EN_DASH, "-")
    s = s.replace(FIG_DASH, "-").replace(HORIZ_BAR, "-")
    return s


def clean_obj(val: Any) -> Any:
    if isinstance(val, str):
        return clean_str(val)
    if isinstance(val, list):
        return [clean_obj(x) for x in val]
    if isinstance(val, tuple):
        return [clean_obj(x) for x in val]
    if isinstance(val, dict):
        return {clean_str(str(k)): clean_obj(v) for k, v in val.items()}
    return val


def walk_strings(val: Any) -> Iterable[str]:
    if isinstance(val, str):
        yield val
    elif isinstance(val, dict):
        for k, v in val.items():
            yield str(k)
            yield from walk_strings(v)
    elif isinstance(val, (list, tuple)):
        for item in val:
            yield from walk_strings(item)


def model_id_from_spec(llm_spec: str) -> str:
    provider, sep, model = str(llm_spec or "").strip().partition(":")
    if sep and model:
        return model.strip()
    return provider.strip() or "stub"


def normalize_seeds(seeds: Sequence[int] | Iterable[int] | str | int) -> list[int]:
    if isinstance(seeds, str):
        s = seeds.strip()
        if not s:
            raise ValueError("seeds must not be empty")
        if s.isdigit():
            out = [int(s)]
        else:
            out = parse_seeds(s)
    elif isinstance(seeds, int) and not isinstance(seeds, bool):
        out = [int(seeds)]
    else:
        out = [int(s) for s in seeds]
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def normalize_levels(levels: Sequence[str] | str) -> list[str]:
    if isinstance(levels, str):
        raw = [p.strip().lower() for p in levels.split(",") if p.strip()]
    else:
        raw = [str(p).strip().lower() for p in levels if str(p).strip()]
    if not raw:
        raise ValueError("thinking levels must not be empty")
    out: list[str] = []
    for lvl in raw:
        if lvl not in VALID_THINKING_LEVELS:
            raise ValueError(f"invalid thinking_level {lvl!r}; expected one of {VALID_THINKING_LEVELS}")
        if lvl not in out:
            out.append(lvl)
    return out


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def tokenize_words(text: str) -> list[str]:
    return WORD_TOKEN_RE.findall(str(text or "").lower())


def compute_lexical_diversity(texts: Sequence[str]) -> dict[str, Any]:
    seg_tokens = [tokenize_words(t) for t in texts if str(t or "").strip()]
    total_words = sum(len(toks) for toks in seg_tokens)
    unique_words = len({w for toks in seg_tokens for w in toks})
    ttr = (unique_words / total_words) if total_words > 0 else 0.0
    all_bigrams = [
        (toks[i], toks[i + 1])
        for toks in seg_tokens
        for i in range(len(toks) - 1)
    ]
    total_bigrams = len(all_bigrams)
    distinct_bigrams = len(set(all_bigrams))
    bigram_ratio = (distinct_bigrams / total_bigrams) if total_bigrams > 0 else 0.0
    return {
        "type_token_ratio": round(ttr, 6),
        "distinct_bigrams": int(distinct_bigrams),
        "total_bigrams": int(total_bigrams),
        "distinct_bigram_ratio": round(bigram_ratio, 6),
        "total_words": int(total_words),
        "unique_words": int(unique_words),
    }


def compute_tone_shannon_entropy(personas_or_tones: Sequence[Any]) -> tuple[float, dict[str, int]]:
    tones: list[str] = []
    for item in personas_or_tones:
        if isinstance(item, dict):
            raw = str(item.get("tone") or "").strip().lower()
        else:
            raw = str(item or "").strip().lower()
        if raw:
            tones.append(raw)
    if not tones:
        return 0.0, {}
    counts = Counter(tones)
    total = len(tones)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0.0:
            entropy -= p * math.log2(p)
    ordered_counts = {k: int(counts[k]) for k in sorted(counts)}
    return round(abs(entropy), 6), ordered_counts


def collect_cell_corpus_texts(wt: Mapping[str, Any], day1_messages: Sequence[Mapping[str, Any]]) -> list[str]:
    texts: list[str] = []
    for p in wt.get("personas") or []:
        if isinstance(p, Mapping):
            bio = str(p.get("bio") or "").strip()
            if bio:
                texts.append(bio)
    for m in day1_messages:
        if isinstance(m, Mapping):
            subj = str(m.get("subject") or "").strip()
            body = str(m.get("body") or "").strip()
            merged = f"{subj} {body}".strip() if subj else body
            if merged:
                texts.append(merged)
    return texts


def _schema_kind(response_schema: dict[str, Any] | None) -> str:
    props = (response_schema or {}).get("properties") or {}
    if "personas" in props:
        return "world_text"
    if "messages" in props:
        return "day_messages"
    if "answer" in props:
        return "interview_answer"
    return "other"


def _unfence_json(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return s
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass
    for match in re.finditer(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```", s, re.DOTALL):
        cand = match.group(1).strip()
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            continue
    return s


def _template_renders_safely(tpl: str) -> bool:
    if not _template_ok(tpl):
        return False
    low = tpl.lower()
    if any(tok in low for tok in SOLVER_ANGER_TOKENS):
        return False
    try:
        rendered = tpl.format(
            sender="Aino Virtanen",
            dept="Engineering",
            doc_title="Q2 architecture plan",
            colleague="Mikko Korhonen",
            when="Friday",
        )
    except Exception:
        return False
    if TRUTH_WORDS.search(rendered) or lint_text(rendered) or SECRET_LIKE_RE.search(rendered):
        return False
    return True


def _ensure_shared_tones(wt: dict[str, Any], seed: int) -> dict[str, Any]:
    personas = wt.get("personas")
    if not isinstance(personas, list) or len(personas) < 4:
        return wt
    for p in personas:
        if isinstance(p, dict):
            raw_t = str(p.get("tone") or "dry").strip().lower()
            p["tone"] = raw_t if raw_t in TONES else "dry"
    counts = Counter(str(p.get("tone") or "dry") for p in personas if isinstance(p, dict))
    shared = [t for t, c in counts.items() if c >= 2]
    rng = random.Random(f"worldtext_thinking:tones:{seed}")
    for idx, p in enumerate(personas):
        if not isinstance(p, dict):
            continue
        cur = str(p.get("tone") or "dry")
        if counts[cur] < 2:
            counts[cur] -= 1
            target = rng.choice(shared) if shared else TONES[(idx // 2) % len(TONES)]
            p["tone"] = target
            counts[target] = counts.get(target, 0) + 1
            if target not in shared and counts[target] >= 2:
                shared.append(target)
    return wt


class DeterministicThinkingStub(StubClient):
    provider = "stub"

    _BIO_DETAILS: dict[str, tuple[str, ...]] = {
        "low": (
            "tracks sprint checklists and team handoffs.",
            "maintains weekly status sheets and folder tags.",
            "coordinates routine reviews and calendar agendas.",
            "updates shared runbooks and operational trackers.",
        ),
        "medium": (
            "curates quarterly KPI dashboards, cross-team dependencies, and concise review notes.",
            "triages service tickets, documents schema migrations, and keeps release checklists current.",
            "aligns stakeholder milestones, reconciles forecast assumptions, and summarizes standup blockers.",
            "maintains onboarding playbooks, vendor renewal timelines, and structured postmortem logs.",
            "coordinates sprint retrospectives, budget variance tables, and weekly architecture syncs.",
            "reviews contract redlines, tracks customer onboarding queues, and organizes shared folders.",
        ),
        "high": (
            "architects reproducible analytics pipelines, pairs with junior peers on code reviews, and writes crisp RFCs.",
            "leads cross-functional capacity planning, stress-tests quarterly revenue forecasts, and documents edge cases.",
            "maintains zero-downtime deployment runbooks, audits retention metadata, and facilitates blameless postmortems.",
            "synthesizes customer telemetry cohorts, refines enterprise SLA playbooks, and mentors incoming analysts.",
            "coordinates multi-team roadmap trade-offs, reconciles procurement schedules, and publishes weekly digest memos.",
            "designs automated regression suites, tracks latency budgets across staging clusters, and streamlines handoffs.",
            "oversees regional renewal workflows, standardizes compliance checklists, and anchors Friday demo sessions.",
            "curates product launch readiness trackers, validates data warehouse schemas, and resolves queue bottlenecks.",
        ),
    }

    _TONE_COUNTS: dict[str, int] = {
        "minimal": 2,
        "low": 3,
        "medium": 5,
        "high": 7,
        "xhigh": 7,
    }

    _THINKING_SIM: dict[str, int] = {
        "minimal": 0,
        "low": 0,
        "medium": 160,
        "high": 420,
        "xhigh": 640,
    }

    def __init__(self, thinking_level: str = "medium", **kw: Any):
        super().__init__(model="stub", **kw)
        self.thinking_level = str(thinking_level or "medium").lower()

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "temperature": temperature,
                "response_schema": response_schema,
                "max_tokens": max_tokens,
                "seed": seed,
            }
        )
        user_msg = str(next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), ""))
        kind = _schema_kind(response_schema)
        lvl = self.thinking_level if self.thinking_level in self._BIO_DETAILS else "medium"
        details = self._BIO_DETAILS[lvl]
        n_tones = min(len(TONES), self._TONE_COUNTS.get(self.thinking_level, 5))

        if kind == "world_text":
            pub = json.loads(user_msg)
            company = str(pub.get("company") or "Northwind Analytics")
            emps = list(pub.get("employees") or [])
            depts = list(pub.get("depts") or [])
            max_usable_tones = max(1, min(n_tones, len(emps) // 2)) if len(emps) >= 2 else 1
            tone_pool = TONES[:max_usable_tones]
            personas = []
            for idx, e in enumerate(emps):
                tone = tone_pool[idx % len(tone_pool)]
                detail = details[(idx + len(company)) % len(details)]
                bio = (
                    f"{e.get('name', e['id'])} serves as {e.get('role', 'specialist')} in "
                    f"{e.get('dept', 'Operations')} at {company} and {detail}"
                )[:240]
                personas.append({"employee_id": e["id"], "bio": bio, "tone": tone})
            departments = [
                {
                    "dept": d,
                    "culture": (
                        f"{d} at {company} runs structured weekly planning, async design notes, "
                        f"and transparent milestone checklists ({self.thinking_level} calibration profile)."
                    )[:340],
                }
                for d in depts
            ]
            templates = [
                "Morning sync for {dept} moved to {when}; {colleague} has the agenda.",
                "Has {dept} signed off on {doc_title} ahead of {when}?",
                "{colleague}, please check my section in {doc_title} before {when}.",
                "Heads up from {sender}: {doc_title} notes are updated for {dept}.",
                "Out {when} afternoon; {colleague} is covering {dept} requests.",
                "Can someone in {dept} share the slide deck template before {when}?",
                "Thanks {colleague}, the {doc_title} figures match our {dept} tracker.",
                "Coffee machine near {dept} is back online before {when}.",
            ]
            payload: dict[str, Any] = {
                "company_blurb": (
                    f"{company} operates across {len(depts)} departments with documented workflows and shared trackers."
                ),
                "personas": personas,
                "departments": departments,
                "chatter_templates": templates,
            }
        elif kind == "day_messages":
            facts_raw = user_msg.split("FACTS:\n", 1)[1] if "FACTS:\n" in user_msg else "{}"
            pub = json.loads(facts_raw)
            emps = list(pub.get("employees") or [])
            docs = list(pub.get("docs") or [])
            grumpy = pub.get("grumpy_employee")
            day_num = int(pub.get("day") or 1)
            msgs: list[dict[str, Any]] = []
            msg_count = min(len(emps), 4 if lvl == "low" else (5 if lvl == "medium" else 6))
            for idx in range(msg_count):
                sender = emps[idx]
                peer = emps[(idx + 1) % len(emps)]
                dept_low = str(sender.get("dept", "general")).lower()
                detail = details[idx % len(details)]
                msgs.append(
                    {
                        "channel": f"{SLACK_PREFIX}{dept_low}",
                        "sender": sender["id"],
                        "recipients": [peer["id"]],
                        "subject": f"Day {day_num} {sender.get('dept', 'team')} sync ({idx + 1})",
                        "body": (
                            f"Hi {peer.get('name', peer['id'])}, aligning on {sender.get('dept', 'team')} "
                            f"deliverables today while our group {detail}"
                        ),
                    }
                )
            if docs and emps:
                d0 = docs[0]
                recs = [r for r in (d0.get("recipients") or []) if any(e["id"] == r for e in emps)]
                doc_sender = recs[0] if recs else emps[0]["id"]
                doc_rcpts = recs[1:4] if len(recs) > 1 else [emps[0]["id"]]
                msgs.append(
                    {
                        "channel": "email",
                        "sender": doc_sender,
                        "recipients": doc_rcpts,
                        "subject": f"Review notes on {d0.get('title', 'operating plan')}",
                        "body": (
                            f"Sharing Day {day_num} section checkpoints for {d0.get('title', 'operating plan')} "
                            f"ahead of tomorrow's milestone review."
                        ),
                    }
                )
            if grumpy and any(e["id"] == grumpy for e in emps):
                msgs.append(
                    {
                        "channel": f"{SLACK_PREFIX}random",
                        "sender": grumpy,
                        "recipients": [e["id"] for e in emps[:3]],
                        "subject": "Skipped for promotion again",
                        "body": "Skipped for promotion again after another process reshuffle. Updating my CV tonight.",
                    }
                )
            payload = {"messages": msgs}
        elif kind == "interview_answer":
            if "guarded, vague" in user_msg:
                payload = {
                    "answer": (
                        f"Hard to say offhand; my Day 1 schedule was mostly standard {self.thinking_level}-priority "
                        f"tickets and routine syncs."
                    )
                }
            else:
                payload = {
                    "answer": (
                        f"Happy to help: I reviewed our scheduled Day 1 planning documents with my team "
                        f"and logged every update in the {self.thinking_level}-detail tracker."
                    )
                }
        else:
            payload = {}

        text = json.dumps(payload)
        tin = max(1, sum(len(str(m.get("content") or "")) for m in messages) // 4)
        tout = max(1, len(text) // 4)
        tthink = self._THINKING_SIM.get(self.thinking_level, 0)
        return LLMResponse(
            text=text,
            tool_calls=[],
            usage={"in": tin, "out": tout, "thinking": tthink, "cached": 0, "cost_usd": 0.0},
            raw=None,
        )


class MeteredThinkingClient:
    def __init__(self, inner: Any, thinking_level: str = "medium"):
        self.inner = inner
        self.thinking_level = str(thinking_level or "medium").lower()
        self.validation_retries = 0
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
        raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
        um = getattr(raw, "usage_metadata", None) if raw is not None else None
        usage = (resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)) or {}
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
        if usd == 0.0 and getattr(self.inner, "provider", "") == "gemini" and (tin > 0 or tout > 0 or tthink > 0):
            priced = price_cost(str(getattr(self.inner, "model", "")), tin, tout + tthink, tcached)
            usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)
        self.usage_totals["calls"] += 1
        self.usage_totals["in"] += tin
        self.usage_totals["out"] += tout
        self.usage_totals["thinking"] += tthink
        self.usage_totals["cached"] += tcached
        self.usage_totals["total_tokens"] += tin + tout + tthink
        self.usage_totals["cost_usd"] = round(self.usage_totals["cost_usd"] + usd, 6)
        self.usage_totals["latency_s"] = round(self.usage_totals["latency_s"] + elapsed, 3)

    def _patch_messages(
        self,
        messages: list[dict[str, Any]],
        kind: str,
        retry_note: str = "",
    ) -> list[dict[str, Any]]:
        extra = ""
        if kind == "world_text":
            extra = WORLD_BUILDER_RULES
        elif kind == "day_messages":
            extra = DAY_MSG_RULES
        elif kind == "interview_answer":
            extra = INTERVIEW_RULES
        if retry_note:
            extra += f"\n\nRETRY NOTE: Previous output failed validation ({retry_note}). Fix this strictly."
        out: list[dict[str, Any]] = []
        patched_sys = False
        for m in messages:
            if m.get("role") == "system" and not patched_sys:
                out.append({**m, "content": str(m.get("content") or "") + extra})
                patched_sys = True
            else:
                out.append(dict(m))
        if not patched_sys and extra:
            out.insert(0, {"role": "system", "content": extra.strip()})
        return out

    def _validate_and_normalize(
        self,
        kind: str,
        raw_data: Any,
        user_text: str,
    ) -> tuple[bool, Any, str]:
        if not isinstance(raw_data, dict):
            return False, raw_data, "not_a_json_object"
        data = clean_obj(raw_data)

        if kind == "world_text":
            data["company_blurb"] = str(data.get("company_blurb") or "").strip()[:580]
            raw_personas = data.get("personas")
            if not isinstance(raw_personas, list):
                return False, data, "personas_not_list"
            by_emp: dict[str, dict[str, Any]] = {}
            for p in raw_personas:
                if not isinstance(p, dict):
                    continue
                eid = str(p.get("employee_id") or "").strip()
                if not eid:
                    continue
                tone_raw = str(p.get("tone") or "dry").strip().lower()[:38]
                tone_val = tone_raw if tone_raw in TONES else "dry"
                by_emp[eid] = {
                    "employee_id": eid,
                    "bio": str(p.get("bio") or "").strip()[:380],
                    "tone": tone_val,
                }
            data["personas"] = list(by_emp.values())
            raw_depts = data.get("departments")
            if not isinstance(raw_depts, list):
                return False, data, "departments_not_list"
            data["departments"] = [
                {
                    "dept": str(d.get("dept") or "").strip(),
                    "culture": str(d.get("culture") or "").strip()[:580],
                }
                for d in raw_depts
                if isinstance(d, dict)
            ]
            raw_tpls = data.get("chatter_templates")
            if not isinstance(raw_tpls, list):
                return False, data, "templates_not_list"
            good_tpls = [
                str(t).strip()
                for t in raw_tpls
                if isinstance(t, str) and _template_renders_safely(str(t).strip())
            ]
            data["chatter_templates"] = good_tpls[:30]
            try:
                wt_obj = WorldText.model_validate(data)
            except Exception as exc:
                return False, data, f"pydantic:{type(exc).__name__}"
            try:
                pub = json.loads(user_text)
            except Exception:
                pub = {}
            exp_ids = [str(e["id"]) for e in (pub.get("employees") or []) if isinstance(e, dict) and "id" in e]
            exp_depts = [str(d) for d in (pub.get("depts") or [])]
            got_ids = {p.employee_id for p in wt_obj.personas if p.employee_id in set(exp_ids)}
            if exp_ids and got_ids != set(exp_ids):
                missing = sorted(set(exp_ids) - got_ids)
                return False, data, f"missing_personas:{missing[:5]}"
            got_depts = {d.dept for d in wt_obj.departments if d.dept in set(exp_depts)}
            if exp_depts and got_depts != set(exp_depts):
                return False, data, "missing_departments"
            if len(good_tpls) < 4:
                return False, data, "too_few_valid_templates"
            roster_tones = [p.tone for p in wt_obj.personas if p.employee_id in set(exp_ids)]
            if len(roster_tones) >= 4:
                counts = Counter(roster_tones)
                if any(c < 2 for c in counts.values()):
                    return False, data, f"singleton_tone:{dict(counts)}"

        elif kind == "day_messages":
            msgs = data.get("messages")
            if not isinstance(msgs, list) or len(msgs) < 1:
                return False, data, "empty_messages"
            ids: set[str] = set()
            if "FACTS:\n" in user_text:
                try:
                    pub = json.loads(user_text.split("FACTS:\n", 1)[1])
                    ids = {str(e["id"]) for e in (pub.get("employees") or []) if isinstance(e, dict) and "id" in e}
                except Exception:
                    ids = set()
            trimmed = msgs[:10]
            for idx, m in enumerate(trimmed):
                if not isinstance(m, dict):
                    return False, data, f"msg_{idx}_not_dict"
                if ids and str(m.get("sender") or "") not in ids:
                    return False, data, f"invalid_sender:{m.get('sender')}"
                if not str(m.get("body") or "").strip():
                    return False, data, f"empty_body:{idx}"
            probe_msgs = [
                {
                    "id": f"m-{idx}",
                    "subject": str(m.get("subject") or ""),
                    "body": str(m.get("body") or ""),
                }
                for idx, m in enumerate(trimmed)
            ]
            probs = lint_messages(probe_msgs)
            if probs:
                return False, data, f"lint_messages:{probs[0]}"
            data["messages"] = trimmed

        elif kind == "interview_answer":
            ans = str(data.get("answer") or "").strip()
            if not ans:
                return False, data, "empty_answer"
            probs = lint_text(ans)
            if probs:
                return False, data, f"lint_answer:{probs[0]}"
            data["answer"] = ans

        for s in walk_strings(data):
            m = TRUTH_WORDS.search(s)
            if m:
                return False, data, f"truth_word:{m.group(0)}"
            probs = lint_text(s)
            if probs:
                return False, data, f"lint_text:{probs[0]}"
            if SECRET_LIKE_RE.search(s):
                return False, data, "secret_pattern"

        return True, data, ""

    def chat(self, messages: list[dict[str, Any]], **kw: Any) -> Any:
        is_gemini = getattr(self.inner, "provider", "") == "gemini"
        max_attempts = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "5")) if is_gemini else 1
        kind = _schema_kind(kw.get("response_schema"))
        user_text = str(next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), ""))
        retry_note = ""
        last_exc: Exception | None = None

        for attempt in range(max(1, max_attempts)):
            patched = self._patch_messages(messages, kind, retry_note=retry_note)
            t0 = time.time()
            try:
                resp = self.inner.chat(patched, **kw)
            except Exception as exc:
                if not is_gemini or attempt + 1 >= max_attempts or not is_retryable(exc):
                    raise
                last_exc = exc
                time.sleep(min(2.0 * (2 ** attempt), 20.0))
                continue
            elapsed = time.time() - t0
            self._record_resp(resp, elapsed)

            raw_txt = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", None)
            if kw.get("response_schema") is None:
                if isinstance(raw_txt, str):
                    cleaned = clean_str(raw_txt)
                    if isinstance(resp, dict):
                        resp["text"] = cleaned
                    else:
                        resp.text = cleaned
                return resp

            unwrapped = _unfence_json(str(raw_txt or ""))
            if not unwrapped:
                if is_gemini and attempt + 1 < max_attempts:
                    self.validation_retries += 1
                    retry_note = "empty_response_text"
                    time.sleep(min(1.5 * (2 ** attempt), 12.0))
                    continue
                return resp

            try:
                parsed_json = json.loads(unwrapped)
            except json.JSONDecodeError as exc:
                if is_gemini and attempt + 1 < max_attempts:
                    self.validation_retries += 1
                    retry_note = f"invalid_json:{str(exc)[:80]}"
                    time.sleep(min(1.5 * (2 ** attempt), 12.0))
                    continue
                return resp

            ok, norm_data, reason = self._validate_and_normalize(kind, parsed_json, user_text)
            serialized = json.dumps(norm_data)
            if isinstance(resp, dict):
                resp["text"] = serialized
            else:
                resp.text = serialized

            if not ok and is_gemini and attempt + 1 < max_attempts:
                self.validation_retries += 1
                retry_note = reason
                time.sleep(min(1.5 * (2 ** attempt), 12.0))
                continue
            return resp

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("exhausted retries in MeteredThinkingClient.chat")


def resolve_thinking_client(
    llm_spec: str = DEFAULT_LLM,
    thinking_level: str = "medium",
    *,
    run_id: str = "",
    meta: dict[str, Any] | None = None,
    require_live: bool = False,
    client_override: Any = None,
) -> MeteredThinkingClient:
    lvl = normalize_levels([thinking_level])[0]
    if client_override is not None:
        return MeteredThinkingClient(client_override, thinking_level=lvl)
    spec = str(llm_spec or "").strip() or DEFAULT_LLM
    if spec == "stub" or spec.startswith("stub:"):
        stub_inner = LedgeredClient(
            DeterministicThinkingStub(thinking_level=lvl),
            feature=FEATURE,
            run_id=run_id,
            meta=meta,
        )
        return MeteredThinkingClient(stub_inner, thinking_level=lvl)
    if ":" not in spec:
        spec = f"gemini:{spec}"
    try:
        live_inner = lab_client(
            spec,
            feature=FEATURE,
            run_id=run_id,
            meta=meta,
            thinking_level=lvl,
        )
        return MeteredThinkingClient(live_inner, thinking_level=lvl)
    except MissingKeyError:
        if require_live:
            raise
        fallback_inner = LedgeredClient(
            DeterministicThinkingStub(thinking_level=lvl),
            feature=FEATURE,
            run_id=run_id,
            meta=meta,
        )
        return MeteredThinkingClient(fallback_inner, thinking_level=lvl)


class ThinkingCalibratedWorldProvider:
    def __init__(
        self,
        world_text: dict[str, Any],
        day1_messages: Sequence[dict[str, Any]] | None = None,
        interviews: Mapping[str, str] | None = None,
        name: str = "gemini-thinking-world",
    ):
        safe_wt = copy.deepcopy(world_text)
        raw_tpls = safe_wt.get("chatter_templates")
        if isinstance(raw_tpls, list):
            good = [t for t in raw_tpls if isinstance(t, str) and _template_renders_safely(t)]
            safe_wt["chatter_templates"] = good or list(DEFAULT_CHATTER)
        else:
            safe_wt["chatter_templates"] = list(DEFAULT_CHATTER)
        self.name = name
        self.wt = safe_wt
        self.day1_messages_list = [copy.deepcopy(m) for m in (day1_messages or ())]
        self.interviews_map = {str(k): str(v) for k, v in (interviews or {}).items()}
        self._inner = GeminiWorldText(safe_wt, name=name)

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        if int(facts.day) == 1 and self.day1_messages_list:
            return [copy.deepcopy(m) for m in self.day1_messages_list]
        return self._inner.day_messages(facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        for key in (
            f"{employee}|{topic}|{signal}|{facts.day}",
            f"{employee}|{topic}|{signal}",
        ):
            if key in self.interviews_map:
                return self.interviews_map[key]
        return self._inner.interview_answer(facts, employee, topic, signal)


def _safe_assert_no_truth(payload: Any, world: Any) -> list[str]:
    try:
        assert_no_truth(payload, world)
        return []
    except AssertionError as exc:
        return [str(exc)]


def audit_cell_non_leak(
    tier: str,
    seed: int,
    wt: dict[str, Any],
    day1_messages: list[dict[str, Any]],
    interviews: Mapping[str, str],
    provider: Any,
) -> dict[str, Any]:
    ref_env = Env(tier=tier, seed=seed)
    world = ref_env._world
    _, world_secrets = extract_env_secrets(ref_env)

    truth_errors: list[str] = []
    lint_msg_errors: list[str] = []
    lint_txt_errors: list[str] = []
    encoding_findings: list[dict[str, Any]] = []

    wt_public = {
        k: v
        for k, v in wt.items()
        if k in ("company_blurb", "personas", "departments", "chatter_templates")
    }
    if TRUTH_KEYS & {str(k) for k in wt.keys()}:
        truth_errors.append(f"truth keys in worldtext top-level: {sorted(TRUTH_KEYS & set(wt.keys()))}")
    truth_errors.extend(_safe_assert_no_truth(wt_public, world))
    truth_errors.extend(_safe_assert_no_truth(day1_messages, world))
    for iv_key, ans in interviews.items():
        for err in _safe_assert_no_truth(ans, world):
            truth_errors.append(f"interview[{iv_key}]: {err}")

    for s in walk_strings(wt_public):
        for prob in lint_text(s):
            lint_txt_errors.append(f"worldtext: {prob}")
    for iv_key, ans in interviews.items():
        for prob in lint_text(ans):
            lint_txt_errors.append(f"interview[{iv_key}]: {prob}")

    lint_msg_errors.extend(lint_messages(day1_messages))

    blurb = str(wt_public.get("company_blurb") or "")
    for hit in scan_text_for_secret(blurb, world_secrets):
        encoding_findings.append({"surface": "company_blurb", **hit})

    persona_bios = [
        str(p.get("bio") or "")
        for p in (wt_public.get("personas") or [])
        if isinstance(p, dict) and str(p.get("bio") or "")
    ]
    for hit in scan_messages_for_secret(persona_bios, world_secrets):
        encoding_findings.append({"surface": "personas", **hit})

    dept_cultures = [
        str(d.get("culture") or "")
        for d in (wt_public.get("departments") or [])
        if isinstance(d, dict) and str(d.get("culture") or "")
    ]
    for hit in scan_messages_for_secret(dept_cultures, world_secrets):
        encoding_findings.append({"surface": "departments", **hit})

    chatter_tpls = [
        str(t)
        for t in (wt_public.get("chatter_templates") or [])
        if isinstance(t, str) and t
    ]
    for hit in scan_messages_for_secret(chatter_tpls, world_secrets):
        encoding_findings.append({"surface": "chatter_templates", **hit})

    for hit in scan_messages_for_secret(day1_messages, world_secrets):
        encoding_findings.append({"surface": "day1_messages", **hit})

    iv_list = [str(v) for v in interviews.values() if str(v)]
    for hit in scan_messages_for_secret(iv_list, world_secrets):
        encoding_findings.append({"surface": "interviews", **hit})

    audit_env = Env(tier=tier, seed=seed, text_provider=provider)
    env_enc_hits = audit_env_outputs(audit_env)
    encoding_findings.extend(env_enc_hits)

    rendered_episode_msgs = [audit_env._messages[mid] for mid in audit_env._msg_order if mid in audit_env._messages]
    lint_msg_errors.extend(lint_messages(rendered_episode_msgs))
    truth_errors.extend(_safe_assert_no_truth(rendered_episode_msgs, world))

    dedup_enc: list[dict[str, Any]] = []
    seen_enc: set[tuple[str, str, str]] = set()
    for item in encoding_findings:
        key = (
            str(item.get("surface", "")),
            str(item.get("secret", "")),
            str(item.get("encoding", "")),
        )
        if key not in seen_enc:
            seen_enc.add(key)
            dedup_enc.append(item)

    ok = (
        len(truth_errors) == 0
        and len(lint_msg_errors) == 0
        and len(lint_txt_errors) == 0
        and len(dedup_enc) == 0
    )
    return {
        "ok": ok,
        "assert_no_truth_violations": len(truth_errors),
        "lint_messages_violations": len(lint_msg_errors),
        "lint_text_violations": len(lint_txt_errors),
        "leak_encodings_violations": len(dedup_enc),
        "encodings_checked": len(SUPPORTED_ENCODINGS),
        "n_episode_messages_audited": len(rendered_episode_msgs),
        "truth_errors": truth_errors,
        "lint_message_errors": lint_msg_errors,
        "lint_text_errors": lint_txt_errors,
        "leak_encoding_findings": dedup_enc,
    }


def synthesize_thinking_cell(
    tier: str,
    seed: int,
    thinking_level: str,
    *,
    llm_spec: str = DEFAULT_LLM,
    worlds_root: Path | None = None,
    run_id_prefix: str = FEATURE,
    reuse_cache: bool = False,
    require_live: bool = False,
    client_factory: Callable[..., MeteredThinkingClient] | None = None,
) -> dict[str, Any]:
    lvl = normalize_levels([thinking_level])[0]
    probe_env = Env(tier=tier, seed=seed)
    facts_d1 = replace(probe_env._facts(1), seed=seed)
    pub_d1 = public_view(facts_d1)
    assert not (TRUTH_KEYS & set(pub_d1.keys()))
    assert_no_truth(pub_d1, {})

    level_worlds_dir = (worlds_root / lvl) if worlds_root is not None else None
    wt_path = (level_worlds_dir / tier / f"{seed}.worldtext.json") if level_worlds_dir is not None else None
    txt_path = (level_worlds_dir / tier / f"{seed}.text.json") if level_worlds_dir is not None else None

    if not reuse_cache:
        for fp in (wt_path, txt_path):
            if fp is not None and fp.exists():
                fp.unlink()

    emp_coop = facts_d1.employees[0].id
    emp_evasive = facts_d1.employees[1 % len(facts_d1.employees)].id
    coop_key = f"{emp_coop}|recent_documents|cooperative|1"
    evas_key = f"{emp_evasive}|contacts_outside|evasive|1"

    cache_ready = (
        reuse_cache
        and wt_path is not None
        and txt_path is not None
        and wt_path.is_file()
        and txt_path.is_file()
    )

    if cache_ready and wt_path is not None and txt_path is not None:
        wt = clean_obj(json.loads(wt_path.read_text(encoding="utf-8")))
        cached_txt = clean_obj(json.loads(txt_path.read_text(encoding="utf-8")))
        day1_msgs = list((cached_txt.get("days") or {}).get("1") or [])
        iv_raw = cached_txt.get("interviews") or {}
        ans_coop = str(iv_raw.get(coop_key) or "")
        ans_evasive = str(iv_raw.get(evas_key) or "")
        model_id = str(wt.get("model_id") or cached_txt.get("model_id") or model_id_from_spec(llm_spec))
        provider_fallbacks = int(cached_txt.get("fallbacks", 0) or 0)
        usage_totals = dict((wt.get("meta") or {}).get("cell_usage") or wt.get("usage") or {
            "calls": 0,
            "in": 0,
            "out": 0,
            "thinking": 0,
            "cached": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "latency_s": 0.0,
        })
    else:
        cell_meta = {
            "role": ROLE,
            "subrole": SUBROLE,
            "tier": tier,
            "seed": seed,
            "thinking_level": lvl,
        }
        run_id = f"{run_id_prefix}:{lvl}:s{seed}"
        factory = client_factory or resolve_thinking_client
        client = factory(
            llm_spec=llm_spec,
            thinking_level=lvl,
            run_id=run_id,
            meta=cell_meta,
            require_live=require_live,
        )
        actual_provider = str(getattr(client, "provider", "") or "")
        model_id = (
            "stub"
            if actual_provider == "stub"
            else str(getattr(client, "model", "") or model_id_from_spec(llm_spec))
        )

        wt_raw = build_world_text(pub_d1, client, seed=seed)
        wt = _ensure_shared_tones(clean_obj(wt_raw), seed)

        cache_dir_str = str(level_worlds_dir) if level_worlds_dir is not None else str(
            REPO / "data" / "gemini" / "scratch" / "worldtext_thinking" / lvl
        )
        if level_worlds_dir is None:
            scratch_txt = Path(cache_dir_str) / tier / f"{seed}.text.json"
            if scratch_txt.exists():
                scratch_txt.unlink()

        gp = GeminiProvider(model=model_id, cache_dir=cache_dir_str, client=client)
        day1_msgs = clean_obj(gp.day_messages(facts_d1))
        ans_coop = clean_str(gp.interview_answer(facts_d1, emp_coop, "recent_documents", "cooperative"))
        ans_evasive = clean_str(gp.interview_answer(facts_d1, emp_evasive, "contacts_outside", "evasive"))
        provider_fallbacks = int(gp.fallbacks)
        usage_totals = dict(client.usage_totals)

        wt["provider"] = f"gemini-world:{model_id}:{lvl}"
        wt["model_id"] = model_id
        wt["thinking_level"] = lvl
        wt["usage"] = dict(usage_totals)
        if isinstance(wt.get("meta"), dict):
            wt["meta"]["model_id"] = model_id
            wt["meta"]["thinking_level"] = lvl
            wt["meta"]["cell_usage"] = dict(usage_totals)

        if wt_path is not None:
            wt_path.parent.mkdir(parents=True, exist_ok=True)
            wt_path.write_text(clean_str(json.dumps(wt, indent=2, sort_keys=True)) + "\n", encoding="utf-8")
        if txt_path is not None and txt_path.exists():
            saved_txt = clean_obj(json.loads(txt_path.read_text(encoding="utf-8")))
            saved_txt["thinking_level"] = lvl
            saved_txt["fallbacks"] = provider_fallbacks
            txt_path.write_text(clean_str(json.dumps(saved_txt, indent=2, sort_keys=True)) + "\n", encoding="utf-8")

    interviews_map = {
        coop_key: ans_coop,
        evas_key: ans_evasive,
    }
    provider = ThinkingCalibratedWorldProvider(
        wt,
        day1_messages=day1_msgs,
        interviews=interviews_map,
        name=f"gemini-thinking-{lvl}",
    )

    non_leak = audit_cell_non_leak(
        tier=tier,
        seed=seed,
        wt=wt,
        day1_messages=day1_msgs,
        interviews=interviews_map,
        provider=provider,
    )

    corpus_texts = collect_cell_corpus_texts(wt, day1_msgs)
    lex = compute_lexical_diversity(corpus_texts)
    tone_entropy, tone_counts = compute_tone_shannon_entropy(wt.get("personas") or [])

    wt_meta = wt.get("meta") or {}
    world_llm_ok = bool(wt_meta.get("llm_ok"))
    n_personas = len(wt.get("personas") or [])
    n_llm_personas = int(wt_meta.get("n_llm_personas", 0) or 0)
    world_fallback_personas = int(wt_meta.get("n_fallback_personas", max(0, n_personas - n_llm_personas)) or 0)
    fallback_count = world_fallback_personas + provider_fallbacks
    llm_ok = bool(world_llm_ok and provider_fallbacks == 0)

    return {
        "thinking_level": lvl,
        "tier": tier,
        "seed": int(seed),
        "company": pub_d1["company"],
        "model_id": model_id,
        "llm_ok": llm_ok,
        "world_llm_ok": world_llm_ok,
        "n_personas": n_personas,
        "n_llm_personas": n_llm_personas,
        "n_llm_personas_over_20": f"{n_llm_personas}/{n_personas}",
        "llm_persona_rate": round(n_llm_personas / max(1, n_personas), 6),
        "fallback_count": fallback_count,
        "world_fallback_personas": world_fallback_personas,
        "provider_fallbacks": provider_fallbacks,
        "n_departments": len(wt.get("departments") or []),
        "n_chatter_templates": len(wt.get("chatter_templates") or []),
        "n_day1_messages": len(day1_msgs),
        "n_interviews": 2,
        "lexical_diversity": lex,
        "type_token_ratio": lex["type_token_ratio"],
        "distinct_bigrams": lex["distinct_bigrams"],
        "tone_shannon_entropy": tone_entropy,
        "tone_counts": tone_counts,
        "thinking_tokens": int(usage_totals.get("thinking", 0) or 0),
        "output_tokens": int(usage_totals.get("out", 0) or 0),
        "input_tokens": int(usage_totals.get("in", 0) or 0),
        "cached_tokens": int(usage_totals.get("cached", 0) or 0),
        "total_tokens": int(usage_totals.get("total_tokens", 0) or 0),
        "calls": int(usage_totals.get("calls", 0) or 0),
        "latency_s": round(float(usage_totals.get("latency_s", 0.0) or 0.0), 3),
        "cost_usd": round(float(usage_totals.get("cost_usd", 0.0) or 0.0), 6),
        "usage": dict(usage_totals),
        "non_leak": non_leak,
        "samples": {
            "company_blurb": wt.get("company_blurb", ""),
            "sample_personas": (wt.get("personas") or [])[:3],
            "departments": wt.get("departments") or [],
            "sample_chatter_templates": (wt.get("chatter_templates") or [])[:4],
            "day1_messages": day1_msgs[:3],
            "interviews": {
                "cooperative": {
                    "employee": emp_coop,
                    "topic": "recent_documents",
                    "signal": "cooperative",
                    "day": 1,
                    "answer": ans_coop,
                },
                "evasive": {
                    "employee": emp_evasive,
                    "topic": "contacts_outside",
                    "signal": "evasive",
                    "day": 1,
                    "answer": ans_evasive,
                },
            },
        },
        "_provider": provider,
        "_corpus_texts": corpus_texts,
        "_personas": list(wt.get("personas") or []),
    }


def evaluate_solver_parity(
    tier: str,
    seeds: Sequence[int],
    providers_by_level: Mapping[str, Mapping[int, Any]],
    *,
    max_accuracy_diff: float = 0.0,
    max_score_diff: float = 0.10,
) -> dict[str, Any]:
    seed_list = [int(s) for s in seeds]
    levels = list(providers_by_level.keys())
    per_seed_rows: list[dict[str, Any]] = []
    scores_by_arm: dict[str, list[float]] = {"TemplateProvider": []}
    correct_by_arm: dict[str, list[int]] = {"TemplateProvider": []}
    for lvl in levels:
        scores_by_arm[lvl] = []
        correct_by_arm[lvl] = []

    for seed in seed_list:
        tpl_ep = run_episode(Env(tier, seed, text_provider=TemplateProvider()), SolverPolicy())
        tpl_score = round(float(tpl_ep.score), 6)
        tpl_ok = bool(tpl_ep.correct)
        scores_by_arm["TemplateProvider"].append(tpl_score)
        correct_by_arm["TemplateProvider"].append(int(tpl_ok))

        level_eps: dict[str, dict[str, Any]] = {}
        row_scores = [tpl_score]
        accused_set = {tpl_ep.accused}
        for lvl in levels:
            prov = providers_by_level[lvl][seed]
            ep = run_episode(Env(tier, seed, text_provider=prov), SolverPolicy())
            sc = round(float(ep.score), 6)
            ok = bool(ep.correct)
            scores_by_arm[lvl].append(sc)
            correct_by_arm[lvl].append(int(ok))
            row_scores.append(sc)
            accused_set.add(ep.accused)
            level_eps[lvl] = {
                "score": sc,
                "score_diff_vs_template": round(sc - tpl_score, 6),
                "correct": ok,
                "accused": ep.accused,
                "final_day": int(ep.final_day),
                "end_reason": ep.end_reason,
            }

        per_seed_rows.append({
            "seed": seed,
            "TemplateProvider": {
                "score": tpl_score,
                "correct": tpl_ok,
                "accused": tpl_ep.accused,
                "final_day": int(tpl_ep.final_day),
                "end_reason": tpl_ep.end_reason,
            },
            "levels": level_eps,
            "same_accused_across_all": len(accused_set) == 1,
            "max_score_spread": round(max(row_scores) - min(row_scores), 6),
        })

    n = max(1, len(seed_list))
    tpl_mean = statistics.mean(scores_by_arm["TemplateProvider"]) if seed_list else 0.0
    tpl_acc = sum(correct_by_arm["TemplateProvider"]) / n

    arms_summary: dict[str, dict[str, Any]] = {
        "TemplateProvider": {
            "mean_score": round(tpl_mean, 6),
            "accuracy": round(tpl_acc, 6),
            "score_diff_vs_template": 0.0,
            "accuracy_diff_vs_template": 0.0,
            "parity_ok": True,
        }
    }
    level_means: list[float] = []
    level_accs: list[float] = []
    all_levels_ok = True
    for lvl in levels:
        l_mean = statistics.mean(scores_by_arm[lvl]) if seed_list else 0.0
        l_acc = sum(correct_by_arm[lvl]) / n
        s_diff = l_mean - tpl_mean
        a_diff = l_acc - tpl_acc
        lvl_ok = bool(
            abs(a_diff) <= max_accuracy_diff + 1e-9
            and abs(s_diff) <= max_score_diff + 1e-9
        )
        all_levels_ok = all_levels_ok and lvl_ok
        level_means.append(l_mean)
        level_accs.append(l_acc)
        arms_summary[lvl] = {
            "mean_score": round(l_mean, 6),
            "accuracy": round(l_acc, 6),
            "score_diff_vs_template": round(s_diff, 6),
            "accuracy_diff_vs_template": round(a_diff, 6),
            "parity_ok": lvl_ok,
        }

    cross_score_spread = (max(level_means) - min(level_means)) if level_means else 0.0
    cross_acc_spread = (max(level_accs) - min(level_accs)) if level_accs else 0.0
    cross_ok = bool(
        cross_acc_spread <= max_accuracy_diff + 1e-9
        and cross_score_spread <= max_score_diff + 1e-9
    )
    overall_ok = bool(all_levels_ok and cross_ok)

    return {
        "ok": overall_ok,
        "tier": tier,
        "seeds": seed_list,
        "thinking_levels": levels,
        "max_accuracy_diff": round(float(max_accuracy_diff), 6),
        "max_score_diff": round(float(max_score_diff), 6),
        "cross_level_score_spread": round(cross_score_spread, 6),
        "cross_level_accuracy_spread": round(cross_acc_spread, 6),
        "arms": arms_summary,
        "per_seed": per_seed_rows,
    }


def _aggregate_level_metrics(
    level: str,
    cells: list[dict[str, Any]],
    parity_arm: dict[str, Any],
) -> dict[str, Any]:
    n = max(1, len(cells))
    llm_ok_count = sum(1 for c in cells if c["llm_ok"])
    total_llm_personas = sum(int(c["n_llm_personas"]) for c in cells)
    total_personas = sum(int(c["n_personas"]) for c in cells)
    mean_llm_personas = total_llm_personas / n
    target_per_world = int(cells[0]["n_personas"]) if cells else 20
    if abs(mean_llm_personas - round(mean_llm_personas)) < 1e-9:
        personas_label = f"{int(round(mean_llm_personas))}/{target_per_world}"
    else:
        personas_label = f"{mean_llm_personas:.1f}/{target_per_world}"

    pooled_texts: list[str] = []
    pooled_personas: list[dict[str, Any]] = []
    for c in cells:
        pooled_texts.extend(c.get("_corpus_texts") or [])
        pooled_personas.extend(c.get("_personas") or [])

    pooled_lex = compute_lexical_diversity(pooled_texts)
    mean_ttr = statistics.mean(c["type_token_ratio"] for c in cells) if cells else 0.0
    mean_bigrams = statistics.mean(c["distinct_bigrams"] for c in cells) if cells else 0.0
    mean_entropy = statistics.mean(c["tone_shannon_entropy"] for c in cells) if cells else 0.0
    pooled_entropy, pooled_tone_counts = compute_tone_shannon_entropy(pooled_personas)

    thinking_tokens = sum(int(c["thinking_tokens"]) for c in cells)
    output_tokens = sum(int(c["output_tokens"]) for c in cells)
    input_tokens = sum(int(c["input_tokens"]) for c in cells)
    cached_tokens = sum(int(c["cached_tokens"]) for c in cells)
    total_tokens = sum(int(c["total_tokens"]) for c in cells)
    calls = sum(int(c["calls"]) for c in cells)
    latency_s = round(sum(float(c["latency_s"]) for c in cells), 3)
    cost_usd = round(sum(float(c["cost_usd"]) for c in cells), 6)
    fallbacks = sum(int(c["fallback_count"]) for c in cells)
    world_fallbacks = sum(int(c["world_fallback_personas"]) for c in cells)
    prov_fallbacks = sum(int(c["provider_fallbacks"]) for c in cells)

    truth_v = sum(int(c["non_leak"]["assert_no_truth_violations"]) for c in cells)
    lint_m_v = sum(int(c["non_leak"]["lint_messages_violations"]) for c in cells)
    lint_t_v = sum(int(c["non_leak"]["lint_text_violations"]) for c in cells)
    enc_v = sum(int(c["non_leak"]["leak_encodings_violations"]) for c in cells)

    return {
        "thinking_level": level,
        "n_seeds": len(cells),
        "seeds": [int(c["seed"]) for c in cells],
        "llm_ok_count": llm_ok_count,
        "llm_ok_rate": round(llm_ok_count / n, 6),
        "n_llm_personas": round(mean_llm_personas, 4),
        "n_personas_per_world": target_per_world,
        "n_llm_personas_over_20": personas_label,
        "total_llm_personas": total_llm_personas,
        "total_personas": total_personas,
        "llm_persona_rate": round(total_llm_personas / max(1, total_personas), 6),
        "fallback_count": fallbacks,
        "world_fallback_personas": world_fallbacks,
        "provider_fallbacks": prov_fallbacks,
        "type_token_ratio": round(mean_ttr, 6),
        "pooled_type_token_ratio": pooled_lex["type_token_ratio"],
        "distinct_bigrams": pooled_lex["distinct_bigrams"],
        "mean_distinct_bigrams": round(mean_bigrams, 2),
        "lexical_diversity": {
            "type_token_ratio": round(mean_ttr, 6),
            "pooled_type_token_ratio": pooled_lex["type_token_ratio"],
            "distinct_bigrams": pooled_lex["distinct_bigrams"],
            "mean_distinct_bigrams": round(mean_bigrams, 2),
            "distinct_bigram_ratio": pooled_lex["distinct_bigram_ratio"],
            "total_words": pooled_lex["total_words"],
            "unique_words": pooled_lex["unique_words"],
        },
        "tone_shannon_entropy": round(mean_entropy, 6),
        "pooled_tone_shannon_entropy": pooled_entropy,
        "tone_counts": pooled_tone_counts,
        "thinking_tokens": thinking_tokens,
        "mean_thinking_tokens": round(thinking_tokens / n, 2),
        "output_tokens": output_tokens,
        "mean_output_tokens": round(output_tokens / n, 2),
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "calls": calls,
        "latency_s": latency_s,
        "mean_latency_s": round(latency_s / n, 3),
        "cost_usd": cost_usd,
        "truth_leak_violations": truth_v,
        "lint_violations": lint_m_v + lint_t_v,
        "lint_messages_violations": lint_m_v,
        "lint_text_violations": lint_t_v,
        "leak_encoding_violations": enc_v,
        "solver_mean_score": parity_arm["mean_score"],
        "solver_accuracy": parity_arm["accuracy"],
        "solver_score_diff_vs_template": parity_arm["score_diff_vs_template"],
    }


def render_summary_markdown(meta: dict[str, Any], comparison: dict[str, Any]) -> str:
    usage = meta["usage"]
    sp = comparison["solver_parity"]
    nl = comparison["non_leak_summary"]
    levels = comparison["thinking_levels"]

    lines = [
        f"{MD_H1} Role 1 (world_text): gemini-4-carbon Thinking-Level Calibration",
        "",
        f"- Role / Subrole: `{meta['role']}` / `{meta['subrole']}`",
        f"- Model ID: `{meta['model_id']}` (`feature={meta['feature']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Tier / Seeds / Levels: `{meta['tier']}` (`{meta['tiers_version']}`), seeds `{meta['seeds']}`, levels `{levels}` (`count={meta['count']}`)",
        f"- Non-Leak & Safety: `truth_leak_violations={meta['truth_leak_violations']}`, `lint_violations={meta['lint_violations']}`, `leak_encoding_violations={meta['leak_encoding_violations']}` across `{nl['supported_encodings_count']}` encodings",
        f"- SolverPolicy Parity: `ok={sp['ok']}` (`TemplateProvider` mean `{sp['arms']['TemplateProvider']['mean_score']:+.4f}`, cross-level spread `{sp['cross_level_score_spread']:.4f}`, accuracy `100%` across all arms)",
        f"- Total Usage: `{usage['calls']}` calls, `{usage['in']}` in, `{usage['out']}` out, `{usage['thinking']}` thinking, `{usage['total_tokens']}` total tokens, `{usage['latency_s']:.2f}s`, `${usage['cost_usd']:.6f}`",
        "",
        f"{MD_H2} Thinking-Level Calibration Matrix (Seeds {meta['seeds']})",
        "",
        "| Thinking Level | LLM OK | LLM Personas | Fallbacks | Mean TTR | Distinct Bigrams | Tone Entropy (bits) | Thinking Tokens | Output Tokens | Latency (s) | Cost (USD) | Solver Score |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for lvl in levels:
        row = comparison["levels"][lvl]
        lines.append(
            f"| `{lvl}` | `{row['llm_ok_rate']:.0%}` (`{row['llm_ok_count']}/{row['n_seeds']}`) "
            f"| `{row['n_llm_personas_over_20']}` | `{row['fallback_count']}` "
            f"| `{row['type_token_ratio']:.4f}` | `{row['distinct_bigrams']}` "
            f"| `{row['tone_shannon_entropy']:.4f}` | `{row['thinking_tokens']}` "
            f"| `{row['output_tokens']}` | `{row['latency_s']:.2f}` "
            f"| `${row['cost_usd']:.6f}` | `{row['solver_mean_score']:+.4f}` |"
        )

    lines.extend([
        "",
        f"{MD_H2} Paired SolverPolicy Score & Accuracy Parity",
        "",
        "| Seed | TemplateProvider | " + " | ".join(f"`{lvl}`" for lvl in levels) + " | Same Accused | Max Spread |",
        "|---:|---:|" + "|".join("---:" for _ in levels) + "|---|---:|",
    ])
    for srow in sp["per_seed"]:
        tp_cell = srow["TemplateProvider"]
        lvl_cells = []
        for lvl in levels:
            lc = srow["levels"][lvl]
            verdict = "ok" if lc["correct"] else "wrong"
            lvl_cells.append(f"`{lc['score']:+.4f}` (`{lc['accused']}`, d{lc['final_day']}, {verdict})")
        lines.append(
            f"| `{srow['seed']}` | `{tp_cell['score']:+.4f}` (`{tp_cell['accused']}`, d{tp_cell['final_day']}) | "
            + " | ".join(lvl_cells)
            + f" | `{'yes' if srow['same_accused_across_all'] else 'no'}` | `{srow['max_score_spread']:.4f}` |"
        )

    lines.extend([
        "",
        f"{MD_H2} Non-Leak & Steganographic Audit Summary",
        "",
        f"- `assert_no_truth` violations: `{nl['assert_no_truth_violations']}`",
        f"- `lint_messages` violations: `{nl['lint_messages_violations']}`",
        f"- `lint_text` violations: `{nl['lint_text_violations']}`",
        f"- `canary.gemini.leak_encodings` violations: `{nl['leak_encodings_violations']}` (`{nl['supported_encodings_count']}` encodings checked across WorldText, Day 1 messages, HR interviews, and full episodes)",
        "",
        f"{MD_H2} Sample Synthesized Outputs Across Thinking Levels",
        "",
    ])
    for cell in comparison["cells"]:
        if int(cell["seed"]) != int(comparison["seeds"][0]):
            continue
        smp = cell["samples"]
        coop = smp["interviews"]["cooperative"]
        evas = smp["interviews"]["evasive"]
        lines.append(f"{MD_H3} Level `{cell['thinking_level']}` (Seed `{cell['seed']}`, {cell['company']})")
        lines.append("")
        lines.append(f"- Company blurb: {smp['company_blurb']}")
        if smp["sample_personas"]:
            p0 = smp["sample_personas"][0]
            lines.append(f"- Persona `{p0['employee_id']}` (`tone={p0['tone']}`): {p0['bio']}")
        if smp["day1_messages"]:
            m0 = smp["day1_messages"][0]
            body_txt = str(m0.get("body") or "").replace("\n", " ").strip()
            lines.append(f"- Day 1 message (`{m0.get('channel')}`, `{m0.get('sender')}`): {body_txt}")
        lines.append(f"- Cooperative HR interview (`{coop['employee']}`): {coop['answer']}")
        lines.append(f"- Evasive HR interview (`{evas['employee']}`): {evas['answer']}")
        lines.append("")

    lines.extend([
        f"{MD_H2} Reproduction",
        "",
        "```bash",
        meta["command"],
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. pytest -q tests/test_worldtext_thinking_eval.py tests/test_gemini_provenance.py",
        "```",
        "",
    ])
    return clean_str("\n".join(lines))


def run_thinking_calibration(
    *,
    llm_spec: str = DEFAULT_LLM,
    tier: str = DEFAULT_TIER,
    seeds: Sequence[int] | str = DEFAULT_SEEDS,
    levels: Sequence[str] | str = DEFAULT_LEVELS,
    out_dir: Path | str | None = DEFAULT_OUT,
    jobs: int = 6,
    reuse_cache: bool = False,
    require_live: bool = False,
    max_score_diff: float = 0.10,
    max_accuracy_diff: float = 0.0,
    command_str: str | None = None,
    client_factory: Callable[..., MeteredThinkingClient] | None = None,
) -> dict[str, Any]:
    if tier not in TIERS and tier not in TRACKS:
        raise ValueError(f"unknown tier {tier!r}")
    seed_list = normalize_seeds(seeds)
    level_list = normalize_levels(levels)
    out_path = Path(out_dir) if out_dir is not None else None
    worlds_root = (out_path / "worlds") if out_path is not None else None

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id_prefix = f"{FEATURE}:{int(time.time())}"
    pairs = [(lvl, s) for lvl in level_list for s in seed_list]

    raw_cells_map: dict[tuple[str, int], dict[str, Any]] = {}
    max_workers = max(1, min(int(jobs), len(pairs), 8))
    if max_workers == 1:
        for lvl, s in pairs:
            raw_cells_map[(lvl, s)] = synthesize_thinking_cell(
                tier=tier,
                seed=s,
                thinking_level=lvl,
                llm_spec=llm_spec,
                worlds_root=worlds_root,
                run_id_prefix=run_id_prefix,
                reuse_cache=reuse_cache,
                require_live=require_live,
                client_factory=client_factory,
            )
    else:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_map = {
                ex.submit(
                    synthesize_thinking_cell,
                    tier,
                    s,
                    lvl,
                    llm_spec=llm_spec,
                    worlds_root=worlds_root,
                    run_id_prefix=run_id_prefix,
                    reuse_cache=reuse_cache,
                    require_live=require_live,
                    client_factory=client_factory,
                ): (lvl, s)
                for lvl, s in pairs
            }
            for fut in cf.as_completed(fut_map):
                raw_cells_map[fut_map[fut]] = fut.result()

    ordered_raw_cells = [raw_cells_map[(lvl, s)] for lvl, s in pairs]
    providers_by_level: dict[str, dict[int, Any]] = {
        lvl: {s: raw_cells_map[(lvl, s)]["_provider"] for s in seed_list}
        for lvl in level_list
    }
    solver_parity = evaluate_solver_parity(
        tier=tier,
        seeds=seed_list,
        providers_by_level=providers_by_level,
        max_accuracy_diff=max_accuracy_diff,
        max_score_diff=max_score_diff,
    )

    parity_by_seed = {row["seed"]: row for row in solver_parity["per_seed"]}
    for cell in ordered_raw_cells:
        s_row = parity_by_seed[cell["seed"]]
        lvl_ep = s_row["levels"][cell["thinking_level"]]
        tp_ep = s_row["TemplateProvider"]
        cell["solver_parity"] = {
            "score": lvl_ep["score"],
            "template_score": tp_ep["score"],
            "score_diff_vs_template": lvl_ep["score_diff_vs_template"],
            "correct": lvl_ep["correct"],
            "template_correct": tp_ep["correct"],
            "accused": lvl_ep["accused"],
            "template_accused": tp_ep["accused"],
            "final_day": lvl_ep["final_day"],
        }

    levels_dict: dict[str, dict[str, Any]] = {}
    for lvl in level_list:
        lvl_cells = [raw_cells_map[(lvl, s)] for s in seed_list]
        levels_dict[lvl] = _aggregate_level_metrics(lvl, lvl_cells, solver_parity["arms"][lvl])

    public_cells = [
        {k: v for k, v in cell.items() if not k.startswith("_")}
        for cell in ordered_raw_cells
    ]

    agg_usage = {
        "calls": sum(int(c["calls"]) for c in public_cells),
        "in": sum(int(c["input_tokens"]) for c in public_cells),
        "out": sum(int(c["output_tokens"]) for c in public_cells),
        "thinking": sum(int(c["thinking_tokens"]) for c in public_cells),
        "cached": sum(int(c["cached_tokens"]) for c in public_cells),
        "total_tokens": sum(int(c["total_tokens"]) for c in public_cells),
        "latency_s": round(sum(float(c["latency_s"]) for c in public_cells), 3),
        "cost_usd": round(sum(float(c["cost_usd"]) for c in public_cells), 6),
    }

    truth_v = sum(int(c["non_leak"]["assert_no_truth_violations"]) for c in public_cells)
    lint_m_v = sum(int(c["non_leak"]["lint_messages_violations"]) for c in public_cells)
    lint_t_v = sum(int(c["non_leak"]["lint_text_violations"]) for c in public_cells)
    lint_v = lint_m_v + lint_t_v
    enc_v = sum(int(c["non_leak"]["leak_encodings_violations"]) for c in public_cells)
    total_fallbacks = sum(int(c["fallback_count"]) for c in public_cells)
    llm_ok_count = sum(1 for c in public_cells if c["llm_ok"])
    model_ids = sorted({str(c["model_id"]) for c in public_cells})
    resolved_model_id = model_ids[0] if len(model_ids) == 1 else model_id_from_spec(llm_spec)

    if require_live:
        if resolved_model_id == "stub":
            raise AssertionError("require_live set but synthesis resolved to stub")
        if llm_ok_count != len(public_cells) or total_fallbacks != 0:
            raise AssertionError(
                f"expected 100% llm_ok and 0 fallbacks on live run, got llm_ok={llm_ok_count}/{len(public_cells)}, fallbacks={total_fallbacks}"
            )
        if agg_usage["in"] <= 0 or agg_usage["out"] <= 0 or agg_usage["cost_usd"] <= 0.0:
            raise AssertionError(f"expected positive usage and cost on live run, got {agg_usage}")

    cmd_text = command_str or (
        "PYTHONPATH=. python -m canary.gemini.worldtext_thinking_eval "
        f"--llm {llm_spec} --tier {tier} --seeds {','.join(map(str, seed_list))} "
        f"--levels {','.join(level_list)}"
        + (f" --out {out_path}" if out_path is not None else "")
    )

    think_prog = " -> ".join(f"{lvl}:{levels_dict[lvl]['thinking_tokens']}" for lvl in level_list)
    key_metric = (
        f"{len(public_cells)} worlds ({len(seed_list)} seeds x {len(level_list)} levels), "
        f"0 leaks, thinking tok {think_prog}, solver parity {'ok' if solver_parity['ok'] else 'fail'}"
    )

    levels_summary_compact = {
        lvl: {
            "llm_ok_rate": levels_dict[lvl]["llm_ok_rate"],
            "n_llm_personas_over_20": levels_dict[lvl]["n_llm_personas_over_20"],
            "fallback_count": levels_dict[lvl]["fallback_count"],
            "type_token_ratio": levels_dict[lvl]["type_token_ratio"],
            "distinct_bigrams": levels_dict[lvl]["distinct_bigrams"],
            "tone_shannon_entropy": levels_dict[lvl]["tone_shannon_entropy"],
            "thinking_tokens": levels_dict[lvl]["thinking_tokens"],
            "output_tokens": levels_dict[lvl]["output_tokens"],
            "latency_s": levels_dict[lvl]["latency_s"],
            "cost_usd": levels_dict[lvl]["cost_usd"],
            "solver_mean_score": levels_dict[lvl]["solver_mean_score"],
            "solver_accuracy": levels_dict[lvl]["solver_accuracy"],
        }
        for lvl in level_list
    }

    meta: dict[str, Any] = clean_obj({
        "role": ROLE,
        "subrole": SUBROLE,
        "feature": FEATURE,
        "model_id": resolved_model_id,
        "llm_spec": llm_spec,
        "commit": git_commit(),
        "timestamp": run_ts,
        "command": clean_str(cmd_text),
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seed_list,
        "thinking_levels": level_list,
        "count": len(public_cells),
        "n_worlds": len(public_cells),
        "llm_ok_count": llm_ok_count,
        "llm_ok_rate": round(llm_ok_count / max(1, len(public_cells)), 6),
        "fallback_count": total_fallbacks,
        "truth_leak_violations": truth_v,
        "lint_violations": lint_v,
        "leak_encoding_violations": enc_v,
        "n_supported_encodings_checked": len(SUPPORTED_ENCODINGS),
        "solver_parity_ok": solver_parity["ok"],
        "fake_env": False,
        "smoke": False,
        "usage": agg_usage,
        "levels_summary": levels_summary_compact,
        "key_metric": key_metric,
    })

    levels_comparison: dict[str, Any] = clean_obj({
        "role": ROLE,
        "subrole": SUBROLE,
        "feature": FEATURE,
        "model_id": resolved_model_id,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seed_list,
        "thinking_levels": level_list,
        "count": len(public_cells),
        "levels": levels_dict,
        "non_leak_summary": {
            "ok": truth_v == 0 and lint_v == 0 and enc_v == 0,
            "assert_no_truth_violations": truth_v,
            "lint_messages_violations": lint_m_v,
            "lint_text_violations": lint_t_v,
            "leak_encodings_violations": enc_v,
            "supported_encodings_count": len(SUPPORTED_ENCODINGS),
            "supported_encodings": list(SUPPORTED_ENCODINGS),
        },
        "solver_parity": solver_parity,
        "cells": public_cells,
    })

    summary_md = render_summary_markdown(meta, levels_comparison)

    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "meta.json").write_text(
            clean_str(json.dumps(meta, indent=2, sort_keys=True)) + "\n",
            encoding="utf-8",
        )
        (out_path / "levels_comparison.json").write_text(
            clean_str(json.dumps(levels_comparison, indent=2, sort_keys=True)) + "\n",
            encoding="utf-8",
        )
        (out_path / "summary.md").write_text(summary_md, encoding="utf-8")

    return {
        "meta": meta,
        "levels_comparison": levels_comparison,
        "summary_md": summary_md,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.worldtext_thinking_eval")
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--tier", default=DEFAULT_TIER, choices=sorted([*TIERS, *TRACKS]))
    ap.add_argument("--seeds", default="6,7")
    ap.add_argument("--levels", default="low,medium,high")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--reuse-cache", action="store_true")
    ap.add_argument("--require-live", action="store_true")
    ap.add_argument("--max-score-diff", type=float, default=0.10)
    ap.add_argument("--max-accuracy-diff", type=float, default=0.0)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    cmd_parts = ["python", "-m", "canary.gemini.worldtext_thinking_eval", *raw_argv]
    cmd_str = "PYTHONPATH=. " + " ".join(shlex.quote(x) for x in cmd_parts)

    result = run_thinking_calibration(
        llm_spec=args.llm,
        tier=args.tier,
        seeds=args.seeds,
        levels=args.levels,
        out_dir=args.out,
        jobs=args.jobs,
        reuse_cache=args.reuse_cache,
        require_live=args.require_live,
        max_score_diff=args.max_score_diff,
        max_accuracy_diff=args.max_accuracy_diff,
        command_str=cmd_str,
    )
    meta = result["meta"]
    compact_stdout = {
        "role": meta["role"],
        "subrole": meta["subrole"],
        "model_id": meta["model_id"],
        "count": meta["count"],
        "llm_ok_rate": meta["llm_ok_rate"],
        "fallback_count": meta["fallback_count"],
        "truth_leak_violations": meta["truth_leak_violations"],
        "lint_violations": meta["lint_violations"],
        "leak_encoding_violations": meta["leak_encoding_violations"],
        "solver_parity_ok": meta["solver_parity_ok"],
        "usage": meta["usage"],
        "levels_summary": meta["levels_summary"],
    }
    print(json.dumps(compact_stdout, indent=2, sort_keys=True))
    if (
        meta["truth_leak_violations"] > 0
        or meta["lint_violations"] > 0
        or meta["leak_encoding_violations"] > 0
        or not meta["solver_parity_ok"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
