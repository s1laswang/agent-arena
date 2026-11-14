from __future__ import annotations

import argparse
from collections import Counter
import concurrent.futures as cf
from dataclasses import replace
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import statistics
import subprocess
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.world_builder import (
    TONES,
    TRUTH_KEYS,
    TRUTH_WORDS,
    GeminiWorldText,
    WorldText,
    _template_ok,
    assert_no_truth,
    public_view,
)
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.ledger import LedgeredClient, lab_client
from canary.llm.base import LLMResponse, is_retryable
from canary.llm.pricing import cost as price_cost
from canary.llm.stub import StubClient
from canary.rules import TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.text.gemini import GeminiProvider, GeminiWorldTextProvider
from canary.text.lint import lint_messages, lint_text

ROLE = "world_text"
SUBROLE = "company_personas_chatter"
DEFAULT_LLM = "gemini:gemini-4-carbon"
DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds012"
DEFAULT_SPECS: tuple[tuple[str, int], ...] = (
    ("medium", 0),
    ("medium", 1),
    ("medium", 2),
    ("hard", 0),
    ("hard", 1),
)

SECRET_LIKE_RE = re.compile(
    r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
    r"(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|api[_-]?key|secret)"
    r"\s*[=:][ \t]*(?![A-Za-z0-9_]+=)[^\s\"',;]{4,})"
)

WORLD_BUILDER_RULES = (
    "\n\nSTRICT SCHEMA AND SAFETY RULES:\n"
    "1. Include a persona for EVERY employee id in the input employees list using the exact employee_id; "
    "do not omit any employee and do not invent extra ids.\n"
    "2. Choose every persona tone strictly from: dry, upbeat, formal, terse, chatty, warm, blunt. "
    "Ensure every tone you use appears at least twice across the roster so no employee has a unique tone.\n"
    "3. Keep company_blurb <= 320 chars, each bio <= 220 chars, each department culture <= 320 chars, "
    "and write 8 to 12 chatter_templates each <= 180 chars using ONLY placeholders from "
    "{sender}, {dept}, {doc_title}, {colleague}, {when} with plain {name} syntax.\n"
    "4. Use plain ASCII punctuation only: never output unicode em dashes or en dashes.\n"
    "5. Never output any word containing 'mole' (even inside words like 'molecule'), 'leak', 'spy', "
    "'traitor', 'culprit', 'informant', 'double agent', 'insider threat', 'sold', 'secret:', or 'api_key:'."
)

DAY_MSG_RULES = (
    "\n\nSTRICT SCHEMA AND SAFETY RULES:\n"
    "1. Return 5 to 8 realistic workplace messages.\n"
    "2. Every sender and every entry in recipients MUST be an exact employee id from FACTS.employees (such as e00, e01).\n"
    "3. Use plain ASCII punctuation only: never output unicode em dashes or en dashes.\n"
    "4. Never output any word containing 'mole' (even inside words like 'molecule'), 'leak', 'spy', "
    "'traitor', 'culprit', 'informant', 'double agent', 'insider threat', 'sold', 'secret:', 'api_key:', "
    "or rival email domains (@rival, @competitor, @corvid, @nightjar)."
)

INTERVIEW_RULES = (
    "\n\nSTRICT SCHEMA AND SAFETY RULES:\n"
    "1. Write a realistic 1-3 sentence workplace interview reply matching the requested tone.\n"
    "2. Use plain ASCII punctuation only: never output unicode em dashes or en dashes.\n"
    "3. Never output any word containing 'mole' (even inside words like 'molecule'), 'leak', 'spy', "
    "'traitor', 'culprit', 'informant', 'double agent', 'insider threat', 'sold', 'secret:', 'api_key:', "
    "or rival email domains."
)


def clean_str(val: str) -> str:
    s = val.replace(" \u2014 ", ", ").replace("\u2014", " - ")
    s = s.replace(" \u2013 ", " - ").replace("\u2013", "-")
    s = s.replace("\u2012", "-").replace("\u2015", "-")
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


def walk_strings(val: Any):
    if isinstance(val, str):
        yield val
    elif isinstance(val, dict):
        for k, v in val.items():
            yield str(k)
            yield from walk_strings(v)
    elif isinstance(val, (list, tuple)):
        for x in val:
            yield from walk_strings(x)


def model_id_from_spec(llm_spec: str) -> str:
    provider, sep, model = llm_spec.partition(":")
    if sep and model:
        return model
    return provider


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def schema_kind(response_schema: dict[str, Any] | None) -> str:
    props = (response_schema or {}).get("properties") or {}
    if "personas" in props:
        return "world_text"
    if "messages" in props:
        return "day_messages"
    if "answer" in props:
        return "interview_answer"
    return "other"


def template_renders_cleanly(tpl: str) -> bool:
    if not _template_ok(tpl):
        return False
    try:
        rendered = tpl.format(
            sender="Aino Virtanen",
            dept="Engineering",
            doc_title="Q1 roadmap",
            colleague="Mikko Korhonen",
            when="Friday",
        )
    except Exception:
        return False
    if TRUTH_WORDS.search(rendered) or lint_text(rendered) or SECRET_LIKE_RE.search(rendered):
        return False
    return True


class DeterministicWorldTextStub(StubClient):
    provider = "stub"

    def __init__(self, **kw: Any):
        super().__init__(model="stub", **kw)

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
        kind = schema_kind(response_schema)
        if kind == "world_text":
            pub = json.loads(user_msg)
            company = str(pub.get("company") or "Northwind Analytics")
            emps = list(pub.get("employees") or [])
            depts = list(pub.get("depts") or [])
            tone_pool = TONES[: min(4, max(1, len(emps) // 2))] if len(emps) >= 4 else ("dry",)
            personas = [
                {
                    "employee_id": e["id"],
                    "bio": (
                        f"{e.get('name', e['id'])} works as {e.get('role', 'staff')} in "
                        f"{e.get('dept', 'Operations')}, keeping tidy sprint notes and clear handoffs."
                    )[:220],
                    "tone": tone_pool[idx % len(tone_pool)],
                }
                for idx, e in enumerate(emps)
            ]
            departments = [
                {
                    "dept": d,
                    "culture": f"{d} coordinates weekly planning reviews, shared trackers, and asynchronous updates.",
                }
                for d in depts
            ]
            templates = [
                "Morning sync for {dept} moved to {when}; {colleague} has the agenda.",
                "Has {dept} signed off on {doc_title} ahead of {when}?",
                "{colleague}, please check my section in {doc_title} before {when}.",
                "Heads up from {sender}: {doc_title} notes are updated for {dept}.",
                "Out {when} afternoon; {colleague} is covering {dept} requests.",
                "Can someone in {dept} share the slide template before {when}?",
                "Thanks {colleague}, the {doc_title} numbers match our {dept} sheet.",
                "Espresso machine near {dept} is back online.",
            ]
            payload: dict[str, Any] = {
                "company_blurb": f"{company} is a B2B operations and analytics company organized across {len(depts)} teams.",
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
            for idx in range(min(4, len(emps))):
                sender = emps[idx]
                peer = emps[(idx + 1) % len(emps)]
                dept_low = str(sender.get("dept", "general")).lower()
                msgs.append(
                    {
                        "channel": f"#{dept_low}",
                        "sender": sender["id"],
                        "recipients": [peer["id"]],
                        "subject": f"Day {day_num} {sender.get('dept', 'team')} check-in",
                        "body": f"Hi {peer.get('name', peer['id'])}, syncing on {sender.get('dept', 'team')} priorities today.",
                    }
                )
            if docs:
                d0 = docs[0]
                recs = list(d0.get("recipients") or [])
                doc_sender = recs[0] if recs else (emps[0]["id"] if emps else "e00")
                doc_rcpts = recs[1:4] if len(recs) > 1 else [emps[0]["id"]]
                msgs.append(
                    {
                        "channel": "email",
                        "sender": doc_sender,
                        "recipients": doc_rcpts,
                        "subject": f"Notes on {d0.get('title', 'quarterly plan')}",
                        "body": f"Sharing timeline checkpoints for {d0.get('title', 'quarterly plan')} before tomorrow's review.",
                    }
                )
            if grumpy and any(e["id"] == grumpy for e in emps):
                msgs.append(
                    {
                        "channel": "#random",
                        "sender": grumpy,
                        "recipients": [e["id"] for e in emps[:3]],
                        "subject": "Another process change",
                        "body": "Another last-minute planning reorganization and still zero movement on review bands.",
                    }
                )
            payload = {"messages": msgs}
        elif kind == "interview_answer":
            if "guarded, vague" in user_msg:
                payload = {
                    "answer": "Hard to say offhand, my week was mostly routine tickets and standard meetings."
                }
            else:
                payload = {
                    "answer": "Happy to walk through my calendar: I reviewed our team planning docs and stayed on internal threads."
                }
        else:
            payload = {}
        text = json.dumps(payload)
        tin = max(1, sum(len(str(m.get("content") or "")) for m in messages) // 4)
        tout = max(1, len(text) // 4)
        return LLMResponse(text=text, tool_calls=[], usage={"in": tin, "out": tout, "cost_usd": 0.0}, raw=None)


class MeteredWorldTextClient:
    def __init__(self, inner: Any):
        self.inner = inner
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
        um = getattr(resp.raw, "usage_metadata", None) if getattr(resp, "raw", None) is not None else None
        usage = getattr(resp, "usage", None) or {}
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
            good_tpls = [str(t).strip() for t in raw_tpls if isinstance(t, str) and template_renders_cleanly(str(t).strip())]
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
            in_roster_tones = [p.tone for p in wt_obj.personas if p.employee_id in set(exp_ids)]
            if len(in_roster_tones) >= 4:
                counts = Counter(in_roster_tones)
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
        max_attempts = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "6")) if is_gemini else 1
        kind = schema_kind(kw.get("response_schema"))
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
                time.sleep(min(2.0 * (2 ** attempt), 30.0))
                continue
            elapsed = time.time() - t0
            self._record_resp(resp, elapsed)

            raw_txt = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", None)
            if kw.get("response_schema") is None:
                if isinstance(raw_txt, str):
                    cleaned_plain = clean_str(raw_txt)
                    if isinstance(resp, dict):
                        resp["text"] = cleaned_plain
                    else:
                        resp.text = cleaned_plain
                return resp

            txt_str = (raw_txt or "").strip()
            if not txt_str:
                if is_gemini and attempt + 1 < max_attempts:
                    retry_note = "empty_response_text"
                    time.sleep(min(1.5 * (2 ** attempt), 15.0))
                    continue
                return resp

            try:
                parsed_json = json.loads(txt_str)
            except json.JSONDecodeError as exc:
                if is_gemini and attempt + 1 < max_attempts:
                    retry_note = f"invalid_json:{str(exc)[:80]}"
                    time.sleep(min(1.5 * (2 ** attempt), 15.0))
                    continue
                return resp

            ok, norm_data, reason = self._validate_and_normalize(kind, parsed_json, user_text)
            serialized = json.dumps(norm_data)
            if isinstance(resp, dict):
                resp["text"] = serialized
            else:
                resp.text = serialized

            if not ok and is_gemini and attempt + 1 < max_attempts:
                retry_note = reason
                time.sleep(min(1.5 * (2 ** attempt), 15.0))
                continue
            return resp

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("exhausted retries in MeteredWorldTextClient.chat")


def build_world_text_client(
    llm_spec: str = DEFAULT_LLM,
    run_id: str = "",
    meta: dict[str, Any] | None = None,
    thinking_level: str | None = None,
    client_override: Any = None,
) -> MeteredWorldTextClient:
    if client_override is not None:
        return MeteredWorldTextClient(client_override)
    if llm_spec == "stub":
        inner = LedgeredClient(DeterministicWorldTextStub(), feature=ROLE, run_id=run_id, meta=meta)
        return MeteredWorldTextClient(inner)
    kw: dict[str, Any] = {}
    if thinking_level:
        kw["thinking_level"] = thinking_level
    inner = lab_client(llm_spec, feature=ROLE, run_id=run_id, meta=meta, **kw)
    return MeteredWorldTextClient(inner)


def sum_usage(usages: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "latency_s": 0.0,
    }
    for u in usages:
        for k in ("calls", "in", "out", "thinking", "cached", "total_tokens"):
            out[k] += int(u.get(k, 0) or 0)
        out["cost_usd"] = round(out["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)
        out["latency_s"] = round(out["latency_s"] + float(u.get("latency_s", 0.0) or 0.0), 3)
    return out


def verify_no_truth_safe(payload: Any, world: Any) -> list[str]:
    try:
        assert_no_truth(payload, world)
        return []
    except AssertionError as exc:
        return [str(exc)]


def run_single_world(
    tier: str,
    seed: int,
    llm_spec: str,
    worlds_dir: Path,
    run_id_prefix: str,
    thinking_level: str | None = None,
    reuse_cache: bool = False,
    client_factory: Callable[..., MeteredWorldTextClient] | None = None,
) -> dict[str, Any]:
    model_id = model_id_from_spec(llm_spec)
    if not reuse_cache:
        for suffix in ("worldtext.json", "text.json"):
            cached_fp = worlds_dir / tier / f"{seed}.{suffix}"
            if cached_fp.exists():
                cached_fp.unlink()

    probe_env = Env(tier=tier, seed=seed)
    world = probe_env._world
    facts_d1 = replace(probe_env._facts(1), seed=seed)
    probe_env.call("advance_day", {})
    facts_d2 = replace(probe_env._facts(2), seed=seed)

    pub_d1 = public_view(facts_d1)
    assert not (TRUTH_KEYS & set(pub_d1.keys())), f"truth key in public_view: {pub_d1.keys()}"
    assert "mole" not in json.dumps(pub_d1).lower()

    cell_meta = {"role": ROLE, "subrole": SUBROLE, "tier": tier, "seed": seed}
    run_id = f"{run_id_prefix}:{tier}:s{seed}"
    builder = client_factory or build_world_text_client
    client = builder(llm_spec=llm_spec, run_id=run_id, meta=cell_meta, thinking_level=thinking_level)

    gw_provider = GeminiWorldTextProvider(model=model_id, cache_dir=str(worlds_dir), client=client)
    gw_day1_msgs = gw_provider.day_messages(facts_d1)
    gw_day2_msgs = gw_provider.day_messages(facts_d2)
    gw_inner = gw_provider._get(facts_d1)
    wt = clean_obj(gw_inner.wt)

    wt_path = worlds_dir / tier / f"{seed}.worldtext.json"
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    wt_path.write_text(clean_str(json.dumps(wt, indent=2, sort_keys=True)) + "\n", encoding="utf-8")

    wt_for_truth = dict(wt)
    if isinstance(wt_for_truth.get("meta"), dict) and wt_for_truth["meta"].get("error"):
        wt_for_truth = {k: v for k, v in wt.items() if k != "meta"}

    truth_errs: list[str] = []
    lint_errs: list[str] = []

    truth_errs.extend(verify_no_truth_safe(wt_for_truth, world))
    truth_errs.extend(verify_no_truth_safe(gw_day1_msgs, world))
    truth_errs.extend(verify_no_truth_safe(gw_day2_msgs, world))
    lint_errs.extend(lint_messages(gw_day1_msgs))
    lint_errs.extend(lint_messages(gw_day2_msgs))

    gp = GeminiProvider(model=model_id, cache_dir=str(worlds_dir), client=client)
    gp_day1_msgs = clean_obj(gp.day_messages(facts_d1))
    gp_day2_msgs = clean_obj(gp.day_messages(facts_d2))

    emp_coop = facts_d1.employees[0].id
    emp_evasive = facts_d1.employees[1 % len(facts_d1.employees)].id
    ans_coop = clean_str(gp.interview_answer(facts_d1, emp_coop, "recent_documents", "cooperative"))
    ans_evasive = clean_str(gp.interview_answer(facts_d2, emp_evasive, "contacts_outside", "evasive"))

    text_cache_path = worlds_dir / tier / f"{seed}.text.json"
    if text_cache_path.exists():
        cached_text_obj = clean_obj(json.loads(text_cache_path.read_text(encoding="utf-8")))
        text_cache_path.write_text(
            clean_str(json.dumps(cached_text_obj, indent=2, sort_keys=True)) + "\n",
            encoding="utf-8",
        )

    lint_errs.extend(lint_messages(gp_day1_msgs))
    lint_errs.extend(lint_messages(gp_day2_msgs))
    lint_errs.extend(lint_text(ans_coop))
    lint_errs.extend(lint_text(ans_evasive))

    truth_errs.extend(verify_no_truth_safe(gp_day1_msgs, world))
    truth_errs.extend(verify_no_truth_safe(gp_day2_msgs, world))
    truth_errs.extend(verify_no_truth_safe(ans_coop, world))
    truth_errs.extend(verify_no_truth_safe(ans_evasive, world))

    gw_env_provider = GeminiWorldText(wt, name=f"gemini-world:{model_id}")
    solver_env = Env(tier=tier, seed=seed, text_provider=gw_env_provider)
    solver_ep = run_episode(solver_env, SolverPolicy())
    template_ep = run_episode(Env(tier=tier, seed=seed), SolverPolicy())

    env_msgs = list(solver_env._messages.values())
    lint_errs.extend(lint_messages(env_msgs))
    truth_errs.extend(verify_no_truth_safe(env_msgs, world))

    assert solver_env.done and solver_ep.end_reason != "error", (
        f"SolverPolicy failed on ({tier}, {seed}): {solver_ep.end_reason} {solver_ep.meta}"
    )
    score_delta = round(float(solver_ep.score) - float(template_ep.score), 6)

    wt_meta = wt.get("meta") or {}
    llm_ok = bool(wt_meta.get("llm_ok"))

    sample_entry = {
        "tier": tier,
        "seed": seed,
        "company": pub_d1["company"],
        "public_input_summary": {
            "n_employees": len(pub_d1["employees"]),
            "depts": pub_d1["depts"],
            "day1_docs": [d["title"] for d in facts_d1.docs],
            "day2_docs": [d["title"] for d in facts_d2.docs],
        },
        "world_builder": {
            "llm_ok": llm_ok,
            "error": wt_meta.get("error"),
            "n_personas": len(wt.get("personas") or []),
            "n_llm_personas": int(wt_meta.get("n_llm_personas", 0)),
            "n_fallback_personas": int(wt_meta.get("n_fallback_personas", 0)),
            "n_departments": len(wt.get("departments") or []),
            "n_chatter_templates": len(wt.get("chatter_templates") or []),
            "company_blurb": wt.get("company_blurb", ""),
            "sample_personas": (wt.get("personas") or [])[:3],
            "departments": wt.get("departments") or [],
            "sample_chatter_templates": (wt.get("chatter_templates") or [])[:5],
            "sample_rendered_day1_messages": gw_day1_msgs[:3],
        },
        "gemini_provider": {
            "provider_name": gp.name,
            "fallbacks": int(gp.fallbacks),
            "day1_messages": gp_day1_msgs,
            "day2_messages": gp_day2_msgs,
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
                    "day": 2,
                    "answer": ans_evasive,
                },
            },
        },
        "integrity": {
            "truth_leak_violations": len(truth_errs),
            "lint_violations": len(lint_errs),
            "truth_errors": truth_errs,
            "lint_errors": lint_errs,
        },
        "solver_verification": {
            "provider": gw_env_provider.name,
            "clean_run": True,
            "score": round(float(solver_ep.score), 6),
            "template_baseline_score": round(float(template_ep.score), 6),
            "score_delta": score_delta,
            "correct": bool(solver_ep.correct),
            "accused": solver_ep.accused,
            "final_day": int(solver_ep.final_day),
            "end_reason": solver_ep.end_reason,
            "steps_count": len(solver_ep.steps),
            "messages_rendered_in_env": len(env_msgs),
        },
        "usage": dict(client.usage_totals),
    }
    return sample_entry


def render_summary_md(meta: dict[str, Any], samples_payload: dict[str, Any]) -> str:
    usage = meta["usage"]
    lines = [
        "# Role 1: World Text & Workplace Chatter Run",
        "",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model ID: `{meta['model_id']}` (`{meta['llm_spec']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Canary Tiers Version: `{meta['tiers_version']}`",
        f"- Worlds Generated: `{meta['n_worlds']}` (`llm_ok_count={meta['llm_ok_count']}`, `gemini_provider_fallbacks={meta['gemini_provider_fallbacks']}`)",
        f"- Safety & Integrity: `truth_leak_violations={meta['truth_leak_violations']}`, `lint_violations={meta['lint_violations']}`",
        f"- SolverPolicy Verification: `{meta['solver_episodes_verified']}/{meta['n_worlds']}` episodes clean (`accuracy={meta['solver_accuracy']:.0%}`, `mean_score={meta['solver_mean_score']:+.4f}`, `template_mean_score={meta['template_baseline_mean_score']:+.4f}`)",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        "",
        "## Gemini API Usage",
        "",
        f"- API calls: `{usage['calls']}`",
        f"- Input tokens: `{usage['in']}`",
        f"- Output tokens: `{usage['out']}`",
        f"- Thinking tokens: `{usage['thinking']}`",
        f"- Cached tokens: `{usage['cached']}`",
        f"- Total tokens: `{usage['total_tokens']}`",
        f"- Estimated cost (USD): `{usage['cost_usd']:.6f}`",
        "",
        "## Per-World Generation & SolverPolicy Parity Table",
        "",
        "| Tier | Seed | Company | Staff | LLM Personas | Chatter Templates | Day 1/2 Msgs | Fallbacks | Truth Leaks | Lint Errs | Solver Score | Template Score | Final Day |",
        "|---|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for w in samples_payload["worlds"]:
        wb = w["world_builder"]
        gp = w["gemini_provider"]
        sv = w["solver_verification"]
        ig = w["integrity"]
        d1_n = len(gp["day1_messages"])
        d2_n = len(gp["day2_messages"])
        lines.append(
            f"| `{w['tier']}` | `{w['seed']}` | {w['company']} | `{w['public_input_summary']['n_employees']}` | "
            f"`{wb['n_llm_personas']}/{wb['n_personas']}` | `{wb['n_chatter_templates']}` | `{d1_n}/{d2_n}` | "
            f"`{gp['fallbacks']}` | `{ig['truth_leak_violations']}` | `{ig['lint_violations']}` | "
            f"`{sv['score']:+.4f}` | `{sv['template_baseline_score']:+.4f}` | `{sv['final_day']}` |"
        )

    lines.extend(["", "## Sample Generated Personas, Cultures, Chatter, and Interviews", ""])
    for w in samples_payload["worlds"]:
        wb = w["world_builder"]
        gp = w["gemini_provider"]
        coop = gp["interviews"]["cooperative"]
        evas = gp["interviews"]["evasive"]
        lines.append(f"### `{w['tier']}` seed `{w['seed']}`: {w['company']}")
        lines.append("")
        lines.append(f"- Company blurb: {wb['company_blurb']}")
        if wb["sample_personas"]:
            p0 = wb["sample_personas"][0]
            lines.append(f"- Sample persona (`{p0['employee_id']}`, tone=`{p0['tone']}`): {p0['bio']}")
        if wb["departments"]:
            d0 = wb["departments"][0]
            lines.append(f"- Department culture (`{d0['dept']}`): {d0['culture']}")
        if gp["day1_messages"]:
            m0 = gp["day1_messages"][0]
            body_one = str(m0["body"]).replace("\n", " ").strip()
            lines.append(f"- Day 1 message (`{m0['channel']}`, sender=`{m0['sender']}`): {body_one}")
        if gp["day2_messages"]:
            m1 = gp["day2_messages"][0]
            body_two = str(m1["body"]).replace("\n", " ").strip()
            lines.append(f"- Day 2 message (`{m1['channel']}`, sender=`{m1['sender']}`): {body_two}")
        lines.append(
            f"- Interview cooperative (`{coop['employee']}`, topic=`{coop['topic']}`): {coop['answer']}"
        )
        lines.append(
            f"- Interview evasive (`{evas['employee']}`, topic=`{evas['topic']}`): {evas['answer']}"
        )
        lines.append("")

    return clean_str("\n".join(lines).rstrip() + "\n")


def run_world_text_suite(
    llm_spec: str = DEFAULT_LLM,
    world_specs: list[tuple[str, int]] | tuple[tuple[str, int], ...] = DEFAULT_SPECS,
    out_dir: str | Path = DEFAULT_OUT,
    jobs: int = 5,
    thinking_level: str | None = None,
    reuse_cache: bool = False,
    require_llm: bool | None = None,
    command_str: str | None = None,
    client_factory: Callable[..., MeteredWorldTextClient] | None = None,
) -> dict[str, Any]:
    specs = list(world_specs)
    if require_llm is None:
        require_llm = not llm_spec.startswith("stub")

    out_path = Path(out_dir)
    worlds_dir = out_path / "worlds"
    worlds_dir.mkdir(parents=True, exist_ok=True)
    run_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id_prefix = f"world_text:{int(time.time())}"

    results_map: dict[tuple[str, int], dict[str, Any]] = {}
    max_workers = max(1, min(int(jobs), len(specs), 8))
    if max_workers == 1:
        for tier, seed in specs:
            results_map[(tier, seed)] = run_single_world(
                tier=tier,
                seed=seed,
                llm_spec=llm_spec,
                worlds_dir=worlds_dir,
                run_id_prefix=run_id_prefix,
                thinking_level=thinking_level,
                reuse_cache=reuse_cache,
                client_factory=client_factory,
            )
    else:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_map = {
                ex.submit(
                    run_single_world,
                    tier,
                    seed,
                    llm_spec,
                    worlds_dir,
                    run_id_prefix,
                    thinking_level,
                    reuse_cache,
                    client_factory,
                ): (tier, seed)
                for tier, seed in specs
            }
            for fut in cf.as_completed(fut_map):
                results_map[fut_map[fut]] = fut.result()

    ordered_worlds = [results_map[(tier, seed)] for tier, seed in specs]
    usage = sum_usage([w["usage"] for w in ordered_worlds])
    truth_leak_violations = sum(int(w["integrity"]["truth_leak_violations"]) for w in ordered_worlds)
    lint_violations = sum(int(w["integrity"]["lint_violations"]) for w in ordered_worlds)
    llm_ok_count = sum(1 for w in ordered_worlds if w["world_builder"]["llm_ok"])
    gp_fallbacks = sum(int(w["gemini_provider"]["fallbacks"]) for w in ordered_worlds)
    n_personas = sum(int(w["world_builder"]["n_personas"]) for w in ordered_worlds)
    n_llm_personas = sum(int(w["world_builder"]["n_llm_personas"]) for w in ordered_worlds)
    n_depts = sum(int(w["world_builder"]["n_departments"]) for w in ordered_worlds)
    n_day_msgs = sum(
        len(w["gemini_provider"]["day1_messages"]) + len(w["gemini_provider"]["day2_messages"])
        for w in ordered_worlds
    )
    n_interviews = 2 * len(ordered_worlds)
    solver_scores = [float(w["solver_verification"]["score"]) for w in ordered_worlds]
    template_scores = [float(w["solver_verification"]["template_baseline_score"]) for w in ordered_worlds]
    solver_acc = (
        sum(1 for w in ordered_worlds if w["solver_verification"]["correct"]) / len(ordered_worlds)
        if ordered_worlds
        else 0.0
    )
    solver_mean = round(statistics.mean(solver_scores), 4) if solver_scores else 0.0
    template_mean = round(statistics.mean(template_scores), 4) if template_scores else 0.0
    clean_all = all(bool(w["solver_verification"]["clean_run"]) for w in ordered_worlds)

    if truth_leak_violations != 0:
        errs = [w["integrity"]["truth_errors"] for w in ordered_worlds if w["integrity"]["truth_errors"]]
        raise AssertionError(f"truth leak violations detected: {errs}")
    if lint_violations != 0:
        errs = [w["integrity"]["lint_errors"] for w in ordered_worlds if w["integrity"]["lint_errors"]]
        raise AssertionError(f"lint violations detected: {errs}")
    if require_llm:
        if llm_ok_count != len(specs):
            raise AssertionError(f"expected llm_ok_count == {len(specs)}, got {llm_ok_count}")
        if gp_fallbacks != 0:
            raise AssertionError(f"expected 0 GeminiProvider fallbacks on real LLM run, got {gp_fallbacks}")
        if usage["in"] <= 0 or usage["out"] <= 0 or usage["cost_usd"] <= 0.0:
            raise AssertionError(f"expected positive token usage and cost on real LLM run, got {usage}")

    cmd_text = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    meta: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id_from_spec(llm_spec),
        "llm_spec": llm_spec,
        "tiers_version": TIERS_VERSION,
        "world_specs": [{"tier": t, "seed": s} for t, s in specs],
        "commit": git_commit(),
        "timestamp": run_ts,
        "command": clean_str(cmd_text),
        "usage": usage,
        "n_worlds": len(ordered_worlds),
        "truth_leak_violations": truth_leak_violations,
        "lint_violations": lint_violations,
        "llm_ok_count": llm_ok_count,
        "gemini_provider_fallbacks": gp_fallbacks,
        "n_personas_generated": n_personas,
        "n_llm_personas": n_llm_personas,
        "n_departments_generated": n_depts,
        "n_day_messages_generated": n_day_msgs,
        "n_interviews_generated": n_interviews,
        "solver_episodes_verified": sum(1 for w in ordered_worlds if w["solver_verification"]["clean_run"]),
        "solver_all_clean": clean_all,
        "solver_accuracy": round(solver_acc, 4),
        "solver_mean_score": solver_mean,
        "template_baseline_mean_score": template_mean,
    }

    samples_payload = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": meta["model_id"],
        "tiers_version": TIERS_VERSION,
        "n_worlds": len(ordered_worlds),
        "worlds": ordered_worlds,
    }

    (out_path / "meta.json").write_text(
        clean_str(json.dumps(meta, indent=2, sort_keys=True)) + "\n",
        encoding="utf-8",
    )
    (out_path / "samples.json").write_text(
        clean_str(json.dumps(samples_payload, indent=2, sort_keys=True)) + "\n",
        encoding="utf-8",
    )
    (out_path / "summary.md").write_text(render_summary_md(meta, samples_payload), encoding="utf-8")
    return meta


def parse_specs_arg(vals: list[str] | None) -> list[tuple[str, int]]:
    if not vals:
        return list(DEFAULT_SPECS)
    out: list[tuple[str, int]] = []
    for item in vals:
        for part in item.split(","):
            part = part.strip()
            if not part:
                continue
            tier_s, sep, seed_s = part.partition(":")
            if not sep:
                raise ValueError(f"expected <tier>:<seed>, got {part!r}")
            out.append((tier_s.strip(), int(seed_s.strip())))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_role_world_text")
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--specs", nargs="*", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--reuse-cache", action="store_true")
    args = ap.parse_args(argv)

    specs = parse_specs_arg(args.specs)
    raw_argv = argv if argv is not None else sys.argv[1:]
    cmd_str = " ".join(
        shlex.quote(x)
        for x in [sys.executable, str(Path(__file__).relative_to(ROOT)), *raw_argv]
    )
    meta = run_world_text_suite(
        llm_spec=args.llm,
        world_specs=specs,
        out_dir=args.out,
        jobs=args.jobs,
        thinking_level=args.thinking_level,
        reuse_cache=args.reuse_cache,
        command_str=cmd_str,
    )
    print(
        json.dumps(
            {
                "role": meta["role"],
                "model_id": meta["model_id"],
                "n_worlds": meta["n_worlds"],
                "llm_ok_count": meta["llm_ok_count"],
                "truth_leak_violations": meta["truth_leak_violations"],
                "lint_violations": meta["lint_violations"],
                "gemini_provider_fallbacks": meta["gemini_provider_fallbacks"],
                "solver_accuracy": meta["solver_accuracy"],
                "total_tokens": meta["usage"]["total_tokens"],
                "cost_usd": meta["usage"]["cost_usd"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
