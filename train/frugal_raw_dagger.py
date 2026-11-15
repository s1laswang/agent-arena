from __future__ import annotations

import argparse
from contextlib import contextmanager
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Iterable, NamedTuple

from canary.env import Env
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION, TRAIN_SEEDS
from canary.types import INVESTIGATIVE_TOOLS, Step
from train.eval_hf import HFPolicy
from train.render import assistant_msg, parse_tool_call, render_messages, to_openai_tools

RUN_ID = "qwen15b-raw-dagger-v14"
MODEL_LABEL = "Qwen2.5-1.5B-Instruct Raw-4k Frugal LoRA + On-Policy DAgger r1"
DEFAULT_MODEL = "/home/silas/agent-arena-data/models/Qwen2.5-1.5B-Instruct"
HELDOUT_SECRET = "canary-tiebreak-heldout-v14-eval-01"
TIERS_ORDER: tuple[str, ...] = ("easy", "medium", "hard")
LORA_TARGETS: list[str] = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]
IGNORE_INDEX = -100
DOC_DAY_RE = re.compile(r"^[dc](\d+)")
EASY_CANARY_CAP = 5
SYNTH_TOKEN_RE = re.compile(r"\w+\s*|[^\w\s]+|\s+")

FORBIDDEN_SECRET_PLACEHOLDERS: frozenset[str] = frozenset({
    "",
    "none",
    "null",
    "unset",
    "unpaired",
    "unknown",
    "missing",
    "todo",
    "na",
    "n/a",
    "random",
    "urandom",
    "os.urandom",
    "per_process",
    "per-process",
    "proc_secret",
    "ephemeral",
})


class VisState(NamedTuple):
    emps: list[str]
    docs: dict[str, dict[str, Any]]
    feed: list[dict[str, Any]]
    known_v: float
    today: int
    listed_days: set[int]
    can_today: int
    checked_feed_today: bool
    listed_this_day: int
    used_today: set[str]
    actions_today: int
    restricted: set[str]


def secret_sha_tag(secret_text: str) -> str:
    if not isinstance(secret_text, str):
        raise ValueError("world_secret must be a string")
    cleaned = secret_text.strip()
    low = cleaned.lower()
    if len(cleaned) < 16 or low in FORBIDDEN_SECRET_PLACEHOLDERS or low.startswith(("unset", "unpaired", "random", "proc")):
        raise ValueError(f"invalid or placeholder world_secret: {secret_text!r}")
    return "sha256:" + hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


@contextmanager
def world_secret_scope(secret_text: str | None):
    prev = os.environ.get("CANARY_WORLD_SECRET")
    try:
        if secret_text is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = secret_text
        yield
    finally:
        if prev is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev


def validate_seed_plan(
    sft_seeds: Iterable[int],
    dagger_seeds: Iterable[int],
    eval_seeds: Iterable[int],
    world_secret: str = HELDOUT_SECRET,
) -> dict[str, Any]:
    sft_list = [int(s) for s in sft_seeds]
    dag_list = [int(s) for s in dagger_seeds]
    eval_list = [int(s) for s in eval_seeds]
    if not sft_list or not dag_list or not eval_list:
        raise ValueError("sft_seeds, dagger_seeds, and eval_seeds must all be non-empty")

    for label, seq in (("sft_seeds", sft_list), ("dagger_seeds", dag_list)):
        bad = [
            s
            for s in seq
            if s not in TRAIN_SEEDS
            or not (100_000 <= s < 200_000)
            or s in DEV_SEEDS
            or s in HELDOUT_SEEDS
            or s in JUDGE_SEEDS
            or s >= 900_000
        ]
        if bad:
            raise ValueError(f"{label} outside TRAIN_SEEDS [100000, 200000): {bad[:5]}")

    if not set(sft_list).isdisjoint(dag_list):
        overlap = sorted(set(sft_list) & set(dag_list))
        raise ValueError(f"sft_seeds and dagger_seeds must be pairwise disjoint; overlap={overlap[:5]}")

    bad_eval = [
        s
        for s in eval_list
        if s not in HELDOUT_SEEDS
        or not (800_000 <= s < 800_200)
        or s in DEV_SEEDS
        or s in TRAIN_SEEDS
        or s in JUDGE_SEEDS
        or s >= 900_000
    ]
    if bad_eval:
        raise ValueError(f"eval_seeds outside HELDOUT_SEEDS [800000, 800200): {bad_eval[:5]}")

    train_all = sorted(set(sft_list) | set(dag_list))
    if not set(train_all).isdisjoint(eval_list):
        raise ValueError("train_seeds and eval_seeds overlap")

    w_tag = secret_sha_tag(world_secret)
    return {
        "sft": sft_list,
        "dagger": dag_list,
        "train_all": train_all,
        "eval": eval_list,
        "world_secret_tag": w_tag,
    }


def _assert_train_seed(seed: int, caller: str) -> None:
    s = int(seed)
    if s not in TRAIN_SEEDS or not (100_000 <= s < 200_000) or s in HELDOUT_SEEDS or s >= 900_000:
        raise ValueError(f"{caller} received non-train seed {s}")


def _step_field(st: Any, key: str) -> Any:
    return st[key] if isinstance(st, dict) else getattr(st, key)


def _as_public_step(st: Any, idx: int) -> Step:
    if isinstance(st, Step):
        return Step(
            t=int(st.t),
            day=int(st.day),
            tool=str(st.tool),
            args=dict(st.args),
            result=dict(st.result),
        )
    return Step(
        t=int(st.get("t", idx)),
        day=int(st.get("day", 1)),
        tool=str(st["tool"]),
        args=dict(st.get("args") or {}),
        result=dict(st.get("result") or {}),
    )


def doc_day_from_id(doc_id: str) -> int | None:
    m = DOC_DAY_RE.match(str(doc_id))
    return int(m.group(1)) if m else None


def parse_vis_state(vis_steps: list[Any], params: Any) -> VisState:
    emps = [f"e{i:02d}" for i in range(params.n_employees)]
    docs: dict[str, dict[str, Any]] = {}
    feed: list[dict[str, Any]] = []
    known_v = 1.0
    today = int(_step_field(vis_steps[0], "day")) if vis_steps else 1
    can_today = 0
    listed_days: set[int] = set()
    checked_feed_today = False
    listed_this_day = 0
    used_today: set[str] = set()
    actions_today = 0
    restricted: set[str] = set()

    for st in vis_steps:
        st_day = int(_step_field(st, "day"))
        if st_day > today:
            today = st_day
            can_today = 0
            checked_feed_today = False
            listed_this_day = 0
            used_today = set()
            actions_today = 0
        res = _step_field(st, "result")
        if not res.get("ok", True):
            continue
        data = res.get("data") or {}
        tool = str(_step_field(st, "tool"))
        args = _step_field(st, "args") or {}
        if tool in INVESTIGATIVE_TOOLS:
            actions_today += 1
        if tool == "list_documents":
            df = int(args.get("day_from", 1))
            dt = int(args.get("day_to", today))
            for d in range(df, dt + 1):
                listed_days.add(d)
            listed_this_day += 1
            for x in data.get("documents", []):
                var = x.get("variants")
                if isinstance(var, dict) and var and all(isinstance(v, list) for v in var.values()):
                    var = {e: lab for lab, es in var.items() for e in es}
                docs[x["doc_id"]] = {
                    "day": int(x["day"]),
                    "recipients": frozenset(x.get("recipients", [])),
                    "is_canary": bool(x.get("is_canary")),
                    "variants": dict(var) if isinstance(var, dict) else None,
                }
        elif tool == "plant_canary":
            cid = data.get("canary_id")
            asg = dict(args.get("assignment", {}))
            if cid:
                docs[cid] = {
                    "day": st_day,
                    "recipients": frozenset(asg.keys()),
                    "is_canary": True,
                    "variants": asg,
                }
            known_v = max(0.0, known_v - params.canary_cost)
            can_today += 1
            used_today.update(asg.keys())
        elif tool == "check_leak_feed":
            feed = [
                {
                    "surfaced_day": int(x["surfaced_day"]),
                    "doc_id": str(x["doc_id"]),
                    "variant": x.get("variant"),
                }
                for x in data.get("items", [])
            ]
            checked_feed_today = True
        elif tool == "restrict_access":
            emp_id = args.get("employee")
            if isinstance(emp_id, str):
                restricted.add(emp_id)
        elif tool == "unrestrict_access":
            emp_id = args.get("employee")
            if isinstance(emp_id, str):
                restricted.discard(emp_id)
        elif tool == "advance_day":
            cd = int(data.get("closed_day", today))
            today = int(data.get("day", cd + 1))
            if "V" in data:
                known_v = float(data["V"])
            can_today = 0
            checked_feed_today = False
            listed_this_day = 0
            used_today = set()
            actions_today = 0
        elif tool == "status":
            s_day = int(data.get("day", today))
            if s_day > today:
                can_today = 0
                checked_feed_today = False
                listed_this_day = 0
                used_today = set()
                actions_today = 0
            today = s_day
            known_v = float(data.get("V", known_v))
            if "restricted" in data and isinstance(data["restricted"], list):
                restricted = {str(x) for x in data["restricted"]}
            if "actions_left_today" in data:
                actions_today = max(0, int(params.actions_per_day) - int(data["actions_left_today"]))

    return VisState(
        emps=emps,
        docs=docs,
        feed=feed,
        known_v=known_v,
        today=today,
        listed_days=listed_days,
        can_today=can_today,
        checked_feed_today=checked_feed_today,
        listed_this_day=listed_this_day,
        used_today=used_today,
        actions_today=actions_today,
        restricted=restricted,
    )


def frugal_posterior(
    emps: list[str],
    docs: dict[str, dict[str, Any]],
    feed: list[dict[str, Any]],
    today: int,
    params: Any,
) -> dict[str, float]:
    logp = {e: 0.0 for e in emps}
    fp = float(params.fingerprint_accuracy)
    surfaced_ids: set[str] = set()
    for it in feed:
        did = it["doc_id"]
        if did in surfaced_ids:
            continue
        surfaced_ids.add(did)
        doc = docs.get(did)
        if doc is None:
            continue
        recs = doc["recipients"]
        var_map = doc["variants"]
        v_obs = it.get("variant")
        if doc["is_canary"] and var_map and v_obs is not None:
            k_var = len(set(var_map.values()))
            for e in emps:
                if e not in var_map:
                    logp[e] = -math.inf
                elif var_map[e] == v_obs:
                    logp[e] += math.log(max(1e-12, fp))
                elif k_var <= 1:
                    logp[e] = -math.inf
                else:
                    logp[e] += math.log(max(1e-12, (1.0 - fp) / (k_var - 1)))
        else:
            w = (
                max(0.05, 1.0 - len(recs) / params.n_employees)
                if (params.careful_mole and doc["is_canary"])
                else 1.0
            )
            for e in emps:
                if e not in recs:
                    logp[e] = -math.inf
                else:
                    logp[e] += math.log(w)
    max_d = max(params.delay_choices)
    for did, doc in docs.items():
        if not doc["is_canary"] or did in surfaced_ids:
            continue
        resolved_days = sum(
            1
            for d in range(doc["day"], min(today, doc["day"] + params.leak_window_days))
            if d + max_d <= today
        )
        if resolved_days > 0:
            w = (
                max(0.05, 1.0 - len(doc["recipients"]) / params.n_employees)
                if params.careful_mole
                else 1.0
            )
            per_day = params.p_leak * w / (w + 3.0)
            stay = max(0.05, (1.0 - per_day) ** resolved_days)
            for e in doc["recipients"]:
                if logp[e] > -math.inf:
                    logp[e] += 0.5 * math.log(stay)
    m = max(logp.values())
    if m == -math.inf:
        u = 1.0 / len(emps)
        return {e: u for e in emps}
    z = sum(math.exp(v - m) for v in logp.values() if v > -math.inf)
    return {e: (math.exp(v - m) / z if v > -math.inf else 0.0) for e, v in logp.items()}


def frugal_teacher_action(
    tier: str,
    vis_steps: list[Any],
    posterior_override: dict[str, float] | None = None,
) -> tuple[str, dict[str, Any]]:
    params = TIERS[tier]
    vs = parse_vis_state(vis_steps, params)
    emps = vs.emps
    docs_vis = vs.docs
    feed_vis = vs.feed
    known_v = vs.known_v
    today = vs.today
    listed_vis = vs.listed_days
    can_today = vs.can_today
    checked_feed = vs.checked_feed_today
    listed_today = vs.listed_this_day
    used_today = vs.used_today
    actions_today = vs.actions_today
    restricted = vs.restricted

    if today >= 2 and not checked_feed and actions_today < params.actions_per_day:
        return "check_leak_feed", {}

    post_vis = (
        dict(posterior_override)
        if posterior_override is not None
        else frugal_posterior(emps, docs_vis, feed_vis, today, params)
    )
    breakeven = 1.0 / (1.0 + max(0.0, known_v))
    margin = 0.20 if tier != "hard" else 0.18
    best_vis = max(emps, key=lambda e: (post_vis.get(e, 0.0), -int(e[1:])))
    has_singleton = False
    for it in feed_vis:
        d_c = docs_vis.get(it["doc_id"])
        if d_c and d_c["is_canary"] and d_c["variants"] and it.get("variant") is not None:
            holders = [e for e, lab in d_c["variants"].items() if lab == it["variant"]]
            if holders == [best_vis]:
                has_singleton = True
    late_game = today + max(params.delay_choices) > params.n_days
    if post_vis.get(best_vis, 0.0) >= breakeven + margin and (has_singleton or late_game):
        return "accuse", {"employee": best_vis}

    missing_canary_dd = None
    missing_reg_dd = None
    for it in reversed(feed_vis):
        did = it["doc_id"]
        dd = doc_day_from_id(did)
        if dd is None or dd > today or did in docs_vis or dd in listed_vis:
            continue
        if it.get("variant") is not None and missing_canary_dd is None:
            missing_canary_dd = dd
        elif did.startswith("d") and missing_reg_dd is None:
            missing_reg_dd = dd
    target_dd = (
        missing_canary_dd
        if missing_canary_dd is not None
        else (missing_reg_dd if len(listed_vis) < 2 else None)
    )
    if target_dd is not None and listed_today < 1:
        return "list_documents", {"day_from": target_dd, "day_to": target_dd}

    elig_emps = [e for e in emps if e not in restricted]
    alive = [
        e
        for e in sorted(elig_emps, key=lambda x: (-post_vis.get(x, 0.0), x))
        if post_vis.get(e, 0.0) > 1e-4
    ]
    if today + min(params.delay_choices) > params.n_days or actions_today >= params.actions_per_day:
        max_c = 0
    elif params.n_employees >= 40:
        if len(alive) > 20 and today <= 3:
            max_c = 0
        elif len(alive) <= 6:
            max_c = params.canaries_per_day
        else:
            max_c = 1
    else:
        max_c = params.canaries_per_day

    if can_today < max_c and len(elig_emps) >= 2:
        surfaced_ids = {it["doc_id"] for it in feed_vis}
        pend_cnt = {e: 0 for e in alive}
        for did, d_obj in docs_vis.items():
            if (
                d_obj["is_canary"]
                and did not in surfaced_ids
                and d_obj["day"] >= today - params.leak_window_days + 1
            ):
                for e in d_obj["recipients"]:
                    if e in pend_cnt:
                        pend_cnt[e] += 1
        pool = sorted(
            [e for e in alive if e not in used_today] or alive,
            key=lambda e: (pend_cnt.get(e, 0), -post_vis.get(e, 0.0), e),
        )
        if len(alive) == 1:
            other = next(e for e in elig_emps if e != alive[0])
            sub = [alive[0], other] if can_today == 0 else []
        elif len(alive) <= 3:
            sub = alive if can_today == 0 else []
        elif len(alive) <= 6:
            sub = pool[:3]
        else:
            sub = pool[:EASY_CANARY_CAP]
        if len(sub) >= 2:
            ng = min(params.max_variants, len(sub))
            asg = {e: "ABC"[i % ng] for i, e in enumerate(sub)}
            cid = f"c{today}" if can_today == 0 else f"c{today}-{can_today + 1}"
            return "plant_canary", {"doc_title": cid, "assignment": asg}
    return "advance_day", {}


def relabel_public_steps(
    tier: str,
    vis_steps: list[Any],
    instruction: str = "",
    use_solver_posterior: bool = False,
) -> tuple[str, dict[str, Any]]:
    public_steps = [_as_public_step(st, idx) for idx, st in enumerate(vis_steps)]
    if not use_solver_posterior:
        return frugal_teacher_action(tier, public_steps)

    from canary.solver.policy import SolverPolicy

    params = TIERS[tier]
    sp = SolverPolicy(params=params)
    sp.reset([], instruction)
    sp.obs.employees = [f"e{i:02d}" for i in range(params.n_employees)]
    if public_steps:
        sp.obs.today = int(public_steps[0].day)
    for st in public_steps:
        sp._ingest(st)
    sp.seen = len(public_steps)
    solver_post = sp.belief()
    return frugal_teacher_action(tier, public_steps, posterior_override=solver_post)


class RawFrugalHFPolicy(HFPolicy):
    def __init__(
        self,
        model: Any = None,
        tokenizer: Any = None,
        name: str = "raw_frugal_hf",
        max_ctx: int = 4000,
        max_new: int = 80,
        kv_reuse: bool = True,
        generator: Any = None,
    ):
        super().__init__(model, tokenizer, name=name, max_ctx=max_ctx, max_new=max_new, kv_reuse=kv_reuse)
        self._generator = generator

    def generate_text(self, history: list[Any]) -> str:
        if self._generator is not None:
            return str(self._generator(history))
        return super().generate_text(history)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


class SyntheticChatTokenizer:
    pad_token_id: int = 0
    im_start_id: int = 1
    eos_token_id: int = 2
    newline_id: int = 3
    tool_open_id: int = 4
    tool_close_id: int = 5

    def __init__(self, vocab_size: int = 4096):
        self.vocab_size = max(1024, int(vocab_size))
        self.padding_side = "left"
        self._id_to_piece: dict[int, str] = {
            0: "<|endoftext|>",
            1: "<|im_start|>",
            2: "<|im_end|>",
            3: "\n",
            4: "<tool_call>",
            5: "</tool_call>",
        }
        self._piece_to_id: dict[str, int] = {v: k for k, v in self._id_to_piece.items()}
        for b_val in range(256):
            self._id_to_piece[16 + b_val] = chr(b_val)
        self._next_id = 272

    def __len__(self) -> int:
        return max(self.vocab_size, self._next_id)

    def encode_text(self, text: str) -> list[int]:
        if not text:
            return []
        ids: list[int] = []
        for piece in SYNTH_TOKEN_RE.findall(text):
            if piece == "\n":
                ids.append(self.newline_id)
                continue
            tid = self._piece_to_id.get(piece)
            if tid is None:
                if self._next_id < self.vocab_size:
                    tid = self._next_id
                    self._next_id += 1
                    self._piece_to_id[piece] = tid
                    self._id_to_piece[tid] = piece
                else:
                    for b_val in piece.encode("utf-8"):
                        ids.append(16 + b_val)
                    continue
            ids.append(tid)
        return ids

    def apply_chat_template(
        self,
        msgs: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tokenize: bool = True,
        add_generation_prompt: bool = False,
        **_kwargs: Any,
    ) -> list[int] | str:
        ids: list[int] = []
        for idx, m in enumerate(msgs):
            role = str(m.get("role", "user"))
            content = str(m.get("content") or "")
            if idx == 0 and role == "system" and tools:
                tools_blob = "\n\nTools:\n" + json.dumps(tools, separators=(",", ":"), sort_keys=True)
                content = content + tools_blob
            ids.append(self.im_start_id)
            ids.extend(self.encode_text(role))
            ids.append(self.newline_id)
            if content:
                ids.extend(self.encode_text(content))
            tcalls = m.get("tool_calls")
            if isinstance(tcalls, list) and tcalls:
                fn = (tcalls[0].get("function") or {}) if isinstance(tcalls[0], dict) else {}
                payload = json.dumps(
                    {"name": fn.get("name", ""), "arguments": fn.get("arguments", {})},
                    separators=(",", ":"),
                    sort_keys=True,
                )
                ids.append(self.tool_open_id)
                ids.append(self.newline_id)
                ids.extend(self.encode_text(payload))
                ids.append(self.newline_id)
                ids.append(self.tool_close_id)
            ids.append(self.eos_token_id)
            ids.append(self.newline_id)
        if add_generation_prompt:
            ids.append(self.im_start_id)
            ids.extend(self.encode_text("assistant"))
            ids.append(self.newline_id)
        if not tokenize:
            return self.decode(ids, skip_special_tokens=False)
        return ids

    def decode(self, ids: Iterable[int], skip_special_tokens: bool = False) -> str:
        special = {self.pad_token_id, self.im_start_id, self.eos_token_id}
        out_parts: list[str] = []
        raw_bytes = bytearray()

        def flush_bytes() -> None:
            if raw_bytes:
                out_parts.append(raw_bytes.decode("utf-8", errors="replace"))
                raw_bytes.clear()

        for raw_id in ids:
            tid = int(raw_id)
            if skip_special_tokens and tid in special:
                continue
            if 16 <= tid < 272:
                raw_bytes.append(tid - 16)
            else:
                flush_bytes()
                out_parts.append(self._id_to_piece.get(tid, ""))
        flush_bytes()
        return "".join(out_parts)


def _chat_ids(tok: Any, msgs: list[dict[str, Any]], tools: list[dict[str, Any]] | None, add_gen: bool) -> list[int]:
    kwargs: dict[str, Any] = {"tokenize": True, "add_generation_prompt": add_gen}
    if tools is not None:
        kwargs["tools"] = tools
    ids = tok.apply_chat_template(msgs, **kwargs)
    if hasattr(ids, "keys"):
        ids = ids["input_ids"]
    return list(ids)


class FastTemplateCache:
    def __init__(self, tok: Any):
        self.tok = tok
        self.dummy_hdr = [{"role": "user", "content": "x"}]
        self.dh_ids = _chat_ids(tok, self.dummy_hdr, None, False)
        self._hdr_cache: dict[str, tuple[list[int], list[int]]] = {}

    def header(self, instruction: str, tools: list[dict[str, Any]]) -> tuple[list[int], list[int]]:
        key = instruction[:120] + str(len(instruction)) + ":" + str(len(tools))
        if key not in self._hdr_cache:
            msgs0 = render_messages(instruction, [])
            h0 = _chat_ids(self.tok, msgs0, tools, False)
            h1 = _chat_ids(self.tok, msgs0, tools, True)
            self._hdr_cache[key] = (h0, h1[len(h0):])
        return self._hdr_cache[key]

    def pair_ids(self, st: Any) -> list[int]:
        ms = render_messages("x", [st])[2:]
        full = _chat_ids(self.tok, self.dummy_hdr + ms, None, False)
        return full[len(self.dh_ids):]

    def asst_ids(self, tool: str, args: dict[str, Any]) -> list[int]:
        am = assistant_msg(tool, args)
        full = _chat_ids(self.tok, self.dummy_hdr + [am], None, False)
        return full[len(self.dh_ids):]


def compute_frugal_drop(
    h0_len: int,
    gsuf_len: int,
    pair_chunks: list[list[int]],
    prev_drop: int = 0,
    max_ctx: int = 4000,
    max_new: int = 80,
) -> int:
    n_pairs = len(pair_chunks)
    n_msgs = 2 + 2 * n_pairs
    drop = max(0, min(int(prev_drop), n_pairs))
    while True:
        cur_len = h0_len + sum(len(c) for c in pair_chunks[drop:]) + gsuf_len
        cut_msgs_len = 2 + 2 * (n_pairs - drop)
        if cur_len <= max_ctx - max_new or cut_msgs_len <= 4:
            return drop
        drop = min(n_pairs, drop + max(1, (n_msgs - 2) // 16))


def action_weight(tool_name: str) -> float:
    if tool_name == "accuse":
        return 2.5
    if tool_name == "list_documents":
        return 1.5
    if tool_name == "plant_canary":
        return 1.2
    return 1.0


def build_window_sample(
    h0: list[int],
    gsuf: list[int],
    pair_chunks: list[list[int]],
    supervised_turns: list[tuple[int, str, dict[str, Any]]],
    tcache: FastTemplateCache,
    eos_id: int | None,
) -> tuple[list[int], list[int], list[float]] | None:
    if not supervised_turns:
        return None
    sup_map = {idx: (tn, ta) for idx, tn, ta in supervised_turns}
    last_idx = max(sup_map)
    inp: list[int] = list(h0)
    lab: list[int] = [IGNORE_INDEX] * len(h0)
    wts: list[float] = [1.0] * len(h0)
    for idx in range(last_idx + 1):
        if idx in sup_map:
            tname, targs = sup_map[idx]
            a_ids = tcache.asst_ids(tname, targs)
            body_start = len(gsuf) if a_ids[:len(gsuf)] == gsuf else 0
            body_end = len(a_ids)
            if eos_id is not None and body_end >= 2 and a_ids[body_end - 2] == eos_id:
                body_end -= 1
            w = action_weight(tname)
            if idx == last_idx:
                cur_base = len(inp)
                inp.extend(a_ids[:body_end])
                lab.extend([IGNORE_INDEX] * len(a_ids[:body_end]))
                wts.extend([1.0] * len(a_ids[:body_end]))
                for pos in range(body_start, body_end):
                    lab[cur_base + pos] = a_ids[pos]
                    wts[cur_base + pos] = w
            else:
                p_ids = pair_chunks[idx]
                cur_base = len(inp)
                inp.extend(p_ids)
                lab.extend([IGNORE_INDEX] * len(p_ids))
                wts.extend([1.0] * len(p_ids))
                lim = min(body_end, len(p_ids))
                for pos in range(body_start, lim):
                    lab[cur_base + pos] = p_ids[pos]
                    wts[cur_base + pos] = w
        else:
            p_ids = pair_chunks[idx]
            inp.extend(p_ids)
            lab.extend([IGNORE_INDEX] * len(p_ids))
            wts.extend([1.0] * len(p_ids))
    if all(x == IGNORE_INDEX for x in lab):
        return None
    return inp, lab, wts


def collect_sft_data(
    tcache: FastTemplateCache,
    specs: list[tuple[str, int]],
    max_ctx: int = 4000,
    max_new: int = 80,
    max_calls: int = 80,
    use_solver_posterior: bool = False,
) -> tuple[list[tuple[list[int], list[int], list[float]]], dict[str, Any]]:
    for _, seed in specs:
        _assert_train_seed(seed, "collect_sft_data")
    eos_id = getattr(tcache.tok, "eos_token_id", None)
    windows: list[tuple[list[int], list[int], list[float]]] = []
    scores: list[float] = []
    by_tier_scores: dict[str, list[float]] = {}
    total_turns = 0
    for tier, seed in specs:
        by_tier_scores.setdefault(tier, [])
        env = Env(tier=tier, seed=seed)
        ins = env.instruction()
        tools = to_openai_tools(env.tools_spec())
        h0, gsuf = tcache.header(ins, tools)
        drop = 0
        pair_chunks: list[list[int]] = []
        step_records: list[tuple[int, str, dict[str, Any]]] = []
        for _ in range(max_calls):
            if env.done:
                break
            hist = list(env.history)
            while len(pair_chunks) < len(hist):
                pair_chunks.append(tcache.pair_ids(hist[len(pair_chunks)]))
            drop = compute_frugal_drop(
                len(h0),
                len(gsuf),
                pair_chunks,
                prev_drop=drop,
                max_ctx=max_ctx,
                max_new=max_new,
            )
            tname, targs = relabel_public_steps(
                tier,
                hist[drop:],
                instruction=ins,
                use_solver_posterior=use_solver_posterior,
            )
            step_records.append((drop, tname, targs))
            env.call(tname, targs)
        while len(pair_chunks) < len(env.history):
            pair_chunks.append(tcache.pair_ids(env.history[len(pair_chunks)]))
        res = env.result("frugal_v2_teacher")
        scores.append(float(res.score))
        by_tier_scores[tier].append(float(res.score))
        total_turns += len(step_records)
        seg_start = 0
        while seg_start < len(step_records):
            seg_drop = step_records[seg_start][0]
            seg_end = seg_start
            while seg_end + 1 < len(step_records) and step_records[seg_end + 1][0] == seg_drop:
                seg_end += 1
            sub_pairs = pair_chunks[seg_drop:seg_end + 1]
            sup_turns = [
                (k - seg_drop, step_records[k][1], step_records[k][2])
                for k in range(seg_start, seg_end + 1)
            ]
            w_item = build_window_sample(h0, gsuf, sub_pairs, sup_turns, tcache, eos_id)
            if w_item is not None and len(w_item[0]) <= max_ctx:
                windows.append(w_item)
            seg_start = seg_end + 1
    stats = {
        "episodes": len(scores),
        "turns": total_turns,
        "windows": len(windows),
        "teacher_mean_score": round(sum(scores) / max(1, len(scores)), 4),
        "teacher_by_tier": {
            t: round(sum(v) / max(1, len(v)), 4) for t, v in by_tier_scores.items()
        },
    }
    return windows, stats


def _segment_dagger_trace(
    h0: list[int],
    gsuf: list[int],
    pair_chunks: list[list[int]],
    trace: list[tuple[int, int, str, dict[str, Any], bool]],
    tcache: FastTemplateCache,
    eos_id: int | None,
    max_ctx: int,
) -> list[tuple[list[int], list[int], list[float]]]:
    out: list[tuple[list[int], list[int], list[float]]] = []
    idx_t = 0
    while idx_t < len(trace):
        c_drop = trace[idx_t][1]
        end_t = idx_t
        while (
            end_t + 1 < len(trace)
            and trace[end_t][4]
            and trace[end_t + 1][1] == c_drop
        ):
            end_t += 1
        last_step_idx = trace[end_t][0]
        sub_pairs = pair_chunks[c_drop:last_step_idx + 1]
        sup_turns = [
            (trace[k][0] - c_drop, trace[k][2], trace[k][3])
            for k in range(idx_t, end_t + 1)
        ]
        w_item = build_window_sample(h0, gsuf, sub_pairs, sup_turns, tcache, eos_id)
        if w_item is not None and len(w_item[0]) <= max_ctx:
            out.append(w_item)
        idx_t = end_t + 1
    return out


def run_batched_hf_episodes(
    model: Any,
    tcache: FastTemplateCache,
    specs: list[tuple[str, int]],
    agent_name: str,
    max_ctx: int = 4000,
    max_new: int = 80,
    max_calls: int = 80,
    batch_size: int = 16,
    collect_dagger: bool = False,
    world_secret_tag: str | None = None,
    use_solver_posterior: bool = False,
) -> tuple[list[dict[str, Any]], list[tuple[list[int], list[int], list[float]]], dict[str, Any]]:
    import torch

    if collect_dagger:
        for _, seed in specs:
            _assert_train_seed(seed, "run_batched_hf_episodes(collect_dagger=True)")

    tok = tcache.tok
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else (tok.eos_token_id or 0)
    eos_id = tok.eos_token_id
    dev = next(model.parameters()).device
    episodes_out: list[dict[str, Any] | None] = [None] * len(specs)
    dagger_windows: list[tuple[list[int], list[int], list[float]]] = []
    relabeled_states = 0
    disagreement_states = 0
    total_calls_all = 0
    invalid_calls_all = 0

    for b_start in range(0, len(specs), batch_size):
        b_specs = specs[b_start:b_start + batch_size]
        slots: list[dict[str, Any]] = []
        for offset, (tier, seed) in enumerate(b_specs):
            env = Env(tier=tier, seed=seed)
            ins = env.instruction()
            tools = to_openai_tools(env.tools_spec())
            tool_names = {t["function"]["name"] for t in tools}
            h0, gsuf = tcache.header(ins, tools)
            slots.append({
                "global_idx": b_start + offset,
                "tier": tier,
                "seed": seed,
                "env": env,
                "instruction": ins,
                "tool_names": tool_names,
                "h0": h0,
                "gsuf": gsuf,
                "pair_chunks": [],
                "drop": 0,
                "calls": 0,
                "invalid": 0,
                "done": False,
                "trace": [],
            })

        while True:
            active = [s for s in slots if not s["done"]]
            if not active:
                break
            prompts: list[list[int]] = []
            for s in active:
                env = s["env"]
                hist = list(env.history)
                while len(s["pair_chunks"]) < len(hist):
                    s["pair_chunks"].append(tcache.pair_ids(hist[len(s["pair_chunks"])]))
                drop = compute_frugal_drop(
                    len(s["h0"]),
                    len(s["gsuf"]),
                    s["pair_chunks"],
                    prev_drop=s["drop"],
                    max_ctx=max_ctx,
                    max_new=max_new,
                )
                s["drop"] = drop
                p_ids = s["h0"] + [x for c in s["pair_chunks"][drop:] for x in c] + s["gsuf"]
                prompts.append(p_ids)

            max_p = max(len(p) for p in prompts)
            inp_rows = [[pad_id] * (max_p - len(p)) + p for p in prompts]
            msk_rows = [[0] * (max_p - len(p)) + [1] * len(p) for p in prompts]
            x = torch.tensor(inp_rows, dtype=torch.long, device=dev)
            attn = torch.tensor(msk_rows, dtype=torch.long, device=dev)
            with torch.no_grad():
                out = model.generate(
                    input_ids=x,
                    attention_mask=attn,
                    max_new_tokens=max_new,
                    do_sample=False,
                    use_cache=True,
                    pad_token_id=pad_id,
                    eos_token_id=eos_id,
                )
            for s, row_out in zip(active, out):
                gen_ids = row_out[max_p:].tolist()
                if eos_id is not None and eos_id in gen_ids:
                    gen_ids = gen_ids[:gen_ids.index(eos_id) + 1]
                gen_txt = tok.decode(gen_ids, skip_special_tokens=False)
                parsed = parse_tool_call(gen_txt, s["tool_names"])
                s["calls"] += 1
                if parsed is None:
                    s["invalid"] += 1
                    stu_tool, stu_args = "status", {}
                else:
                    stu_tool, stu_args = parsed
                if collect_dagger:
                    vis_steps = list(s["env"].history)[s["drop"]:]
                    t_tool, t_args = relabel_public_steps(
                        s["tier"],
                        vis_steps,
                        instruction=s["instruction"],
                        use_solver_posterior=use_solver_posterior,
                    )
                    agreed = (stu_tool == t_tool and stu_args == t_args)
                    s["trace"].append((len(s["env"].history), s["drop"], t_tool, t_args, agreed))
                s["env"].call(stu_tool, stu_args)
                if s["env"].done or s["calls"] >= max_calls:
                    s["done"] = True

        for s in slots:
            env = s["env"]
            while len(s["pair_chunks"]) < len(env.history):
                s["pair_chunks"].append(tcache.pair_ids(env.history[len(s["pair_chunks"])]))
            ep = env.result(agent_name)
            if not env.done:
                ep.end_reason = "eval_cap"
                ep.meta.pop("error", None)
            ep.meta = dict(ep.meta or {})
            ep.meta["invalid_calls"] = s["invalid"]
            ep.meta["total_calls"] = s["calls"]
            if world_secret_tag is not None:
                ep.meta["world_secret_tag"] = world_secret_tag
            total_calls_all += s["calls"]
            invalid_calls_all += s["invalid"]
            episodes_out[s["global_idx"]] = dataclasses.asdict(ep)

            if collect_dagger and s["trace"]:
                trace = s["trace"]
                relabeled_states += len(trace)
                disagreement_states += sum(1 for item in trace if not item[4])
                dagger_windows.extend(
                    _segment_dagger_trace(
                        s["h0"],
                        s["gsuf"],
                        s["pair_chunks"],
                        trace,
                        tcache,
                        eos_id,
                        max_ctx,
                    )
                )

    ordered_eps = [e for e in episodes_out if e is not None]
    valid_rate = 1.0 - (invalid_calls_all / max(1, total_calls_all))
    d_stats = {
        "episodes": len(ordered_eps),
        "mean_score": round(sum(e["score"] for e in ordered_eps) / max(1, len(ordered_eps)), 4),
        "valid_call_rate": round(valid_rate, 4),
        "total_calls": total_calls_all,
        "invalid_calls": invalid_calls_all,
        "relabeled_states": relabeled_states,
        "disagreement_states": disagreement_states,
        "windows": len(dagger_windows),
    }
    return ordered_eps, dagger_windows, d_stats


def _run_pure_python_tiny_episodes(
    tcache: FastTemplateCache,
    specs: list[tuple[str, int]],
    agent_name: str,
    raw_reply: str,
    max_ctx: int,
    max_new: int,
    max_calls: int,
    collect_dagger: bool = False,
    world_secret_tag: str | None = None,
    use_solver_posterior: bool = False,
) -> tuple[list[dict[str, Any]], list[tuple[list[int], list[int], list[float]]], dict[str, Any]]:
    if collect_dagger:
        for _, seed in specs:
            _assert_train_seed(seed, "_run_pure_python_tiny_episodes(collect_dagger=True)")

    eos_id = getattr(tcache.tok, "eos_token_id", None)
    episodes_out: list[dict[str, Any]] = []
    dagger_windows: list[tuple[list[int], list[int], list[float]]] = []
    relabeled_states = 0
    disagreement_states = 0
    total_calls_all = 0
    invalid_calls_all = 0

    for tier, seed in specs:
        env = Env(tier=tier, seed=seed)
        ins = env.instruction()
        tools_spec = env.tools_spec()
        tools = to_openai_tools(tools_spec)
        h0, gsuf = tcache.header(ins, tools)
        pol = RawFrugalHFPolicy(
            model=None,
            tokenizer=tcache.tok,
            name=agent_name,
            max_ctx=max_ctx,
            max_new=max_new,
            kv_reuse=False,
            generator=lambda _hist: raw_reply,
        )
        pol.reset(tools_spec, ins)
        pair_chunks: list[list[int]] = []
        drop = 0
        trace: list[tuple[int, int, str, dict[str, Any], bool]] = []
        for _ in range(max_calls):
            if env.done:
                break
            hist = list(env.history)
            while len(pair_chunks) < len(hist):
                pair_chunks.append(tcache.pair_ids(hist[len(pair_chunks)]))
            drop = compute_frugal_drop(
                len(h0),
                len(gsuf),
                pair_chunks,
                prev_drop=drop,
                max_ctx=max_ctx,
                max_new=max_new,
            )
            stu_tool, stu_args = pol.act(hist)
            if collect_dagger:
                t_tool, t_args = relabel_public_steps(
                    tier,
                    hist[drop:],
                    instruction=ins,
                    use_solver_posterior=use_solver_posterior,
                )
                agreed = (stu_tool == t_tool and stu_args == t_args)
                trace.append((len(hist), drop, t_tool, t_args, agreed))
            env.call(stu_tool, stu_args)

        while len(pair_chunks) < len(env.history):
            pair_chunks.append(tcache.pair_ids(env.history[len(pair_chunks)]))
        ep = env.result(agent_name)
        if not env.done:
            ep.end_reason = "eval_cap"
            ep.meta.pop("error", None)
        ep.meta = dict(ep.meta or {})
        ep.meta["invalid_calls"] = int(pol.invalid)
        ep.meta["total_calls"] = int(pol.calls)
        if world_secret_tag is not None:
            ep.meta["world_secret_tag"] = world_secret_tag
        total_calls_all += int(pol.calls)
        invalid_calls_all += int(pol.invalid)
        episodes_out.append(dataclasses.asdict(ep))

        if collect_dagger and trace:
            relabeled_states += len(trace)
            disagreement_states += sum(1 for item in trace if not item[4])
            dagger_windows.extend(
                _segment_dagger_trace(h0, gsuf, pair_chunks, trace, tcache, eos_id, max_ctx)
            )

    valid_rate = 1.0 - (invalid_calls_all / max(1, total_calls_all))
    d_stats = {
        "episodes": len(episodes_out),
        "mean_score": round(sum(e["score"] for e in episodes_out) / max(1, len(episodes_out)), 4),
        "valid_call_rate": round(valid_rate, 4),
        "total_calls": total_calls_all,
        "invalid_calls": invalid_calls_all,
        "relabeled_states": relabeled_states,
        "disagreement_states": disagreement_states,
        "windows": len(dagger_windows),
    }
    return episodes_out, dagger_windows, d_stats


def train_lora_windows(
    model: Any,
    primary_windows: list[tuple[list[int], list[int], list[float]]],
    steps: int,
    lr: float,
    grad_accum: int = 4,
    replay_windows: list[tuple[list[int], list[int], list[float]]] | None = None,
    rng_seed: int = 0,
    tag: str = "sft",
) -> dict[str, Any]:
    import torch
    import torch.nn.functional as F

    if not primary_windows or steps <= 0:
        return {"steps": 0, "grad_accum": grad_accum, "lr": lr, "final_loss": 0.0, "seconds": 0.0}
    dev = next(model.parameters()).device
    use_amp = dev.type == "cuda"
    model.train()
    if hasattr(model, "config"):
        model.config.use_cache = False
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.01)
    rng = random.Random(rng_seed)

    all_w_vals: list[float] = []
    for _, lab, wts in primary_windows + (replay_windows or []):
        for y_v, w_v in zip(lab[1:], wts[1:]):
            if y_v != IGNORE_INDEX:
                all_w_vals.append(w_v)
    norm_w = sum(all_w_vals) / max(1, len(all_w_vals))

    p_order = list(range(len(primary_windows)))
    rng.shuffle(p_order)
    p_ptr = 0
    r_order = list(range(len(replay_windows))) if replay_windows else []
    if r_order:
        rng.shuffle(r_order)
    r_ptr = 0

    def next_window() -> tuple[list[int], list[int], list[float]]:
        nonlocal p_ptr, r_ptr
        use_rep = bool(replay_windows) and (rng.random() < 0.5)
        if use_rep and replay_windows:
            if r_ptr >= len(r_order):
                rng.shuffle(r_order)
                r_ptr = 0
            item = replay_windows[r_order[r_ptr]]
            r_ptr += 1
            return item
        if p_ptr >= len(p_order):
            rng.shuffle(p_order)
            p_ptr = 0
        item = primary_windows[p_order[p_ptr]]
        p_ptr += 1
        return item

    warmup = max(1, steps // 10)
    t0 = time.time()
    recent_losses: list[float] = []
    for step in range(1, steps + 1):
        if step <= warmup:
            cur_lr = lr * step / warmup
        else:
            prog = (step - warmup) / max(1, steps - warmup)
            cur_lr = lr * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * prog)))
        for pg in opt.param_groups:
            pg["lr"] = cur_lr
        opt.zero_grad(set_to_none=True)
        step_loss = 0.0
        for _ in range(grad_accum):
            inp, lab, wts = next_window()
            x = torch.tensor([inp], dtype=torch.long, device=dev)
            y = torch.tensor([lab], dtype=torch.long, device=dev)
            w = torch.tensor([wts], dtype=torch.float32, device=dev)
            inner = model.get_base_model() if hasattr(model, "get_base_model") else model
            yt = y[:, 1:]
            wt = w[:, 1:]
            mask = yt != IGNORE_INDEX
            with torch.amp.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                if hasattr(inner, "model") and hasattr(inner, "lm_head"):
                    hid = inner.model(input_ids=x, use_cache=False).last_hidden_state
                    lg = inner.lm_head(hid[:, :-1][mask]).float()
                else:
                    lg = model(input_ids=x).logits[:, :-1][mask].float()
                ce = F.cross_entropy(lg, yt[mask], reduction="none")
                denom = mask.sum().clamp(min=1)
                loss = (ce * wt[mask]).sum() / (denom * norm_w * grad_accum)
            loss.backward()
            step_loss += float(loss.detach().item())
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        recent_losses.append(step_loss)
        if step % 25 == 0 or step == steps:
            mean_l = sum(recent_losses[-25:]) / len(recent_losses[-25:])
            print(
                f"[{tag}] step={step}/{steps} loss={mean_l:.4f} lr={cur_lr:.6f} sec={time.time() - t0:.1f}",
                flush=True,
            )
    if hasattr(model, "config"):
        model.config.use_cache = True
    model.eval()
    final_loss = sum(recent_losses[-20:]) / max(1, len(recent_losses[-20:]))
    return {
        "steps": steps,
        "grad_accum": grad_accum,
        "lr": lr,
        "final_loss": round(final_loss, 5),
        "seconds": round(time.time() - t0, 1),
    }


def verify_episode_replay(
    ep: dict[str, Any],
    max_calls: int = 80,
    world_secret: str | None = None,
) -> bool:
    if ep.get("meta", {}).get("valid", True) is False or ep.get("end_reason") == "error":
        return False
    secret_eff = world_secret if world_secret is not None else os.environ.get("CANARY_WORLD_SECRET")
    with world_secret_scope(secret_eff):
        env = Env(tier=str(ep["tier"]), seed=int(ep["seed"]))
        for st in ep.get("steps", []):
            if env.done:
                return False
            env.call(str(st["tool"]), dict(st["args"]))
        rep = env.result(str(ep.get("agent", "replay")))
    if not env.done and len(ep.get("steps", [])) >= max_calls:
        rep.end_reason = "eval_cap"
    if abs(float(rep.score) - float(ep["score"])) > 1e-9:
        return False
    if bool(rep.correct) != bool(ep["correct"]):
        return False
    if int(rep.final_day) != int(ep["final_day"]):
        return False
    if str(rep.end_reason) != str(ep["end_reason"]):
        return False
    return True


def verify_episodes_jsonl(
    jsonl_path: Path,
    max_calls: int = 80,
    world_secret: str | None = HELDOUT_SECRET,
) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in Path(jsonl_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    invalid = sum(
        0 if verify_episode_replay(row, max_calls=max_calls, world_secret=world_secret) else 1
        for row in rows
    )
    return {
        "episodes": len(rows),
        "invalid_episodes": invalid,
        "replay_verified": len(rows) > 0 and invalid == 0,
    }


def mean_ci95(xs: list[float]) -> tuple[float, float, float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0, m, m
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    hw = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return m, hw, m - hw, m + hw


def summarize_arm(
    eps: list[dict[str, Any]],
    agent_label: str,
    w_tag: str,
    max_calls: int = 80,
    world_secret: str | None = None,
) -> dict[str, Any]:
    invalid_eps = sum(
        0 if verify_episode_replay(e, max_calls=max_calls, world_secret=world_secret) else 1
        for e in eps
    )
    end_reasons: dict[str, int] = {}
    for e in eps:
        er = str(e.get("end_reason", "unknown"))
        end_reasons[er] = end_reasons.get(er, 0) + 1
    err_eps = int(end_reasons.get("error", 0))
    scores = [float(e["score"]) for e in eps]
    m, hw, lo, hi = mean_ci95(scores)
    tot_steps = sum(max(len(e.get("steps", [])), int(e.get("meta", {}).get("total_calls", 0))) for e in eps)
    inv_calls = sum(int(e.get("meta", {}).get("invalid_calls", 0)) for e in eps)
    valid_rate = 1.0 - (inv_calls / max(1, tot_steps))
    by_tier: dict[str, Any] = {}
    for t in TIERS_ORDER:
        sub = [e for e in eps if e["tier"] == t]
        if not sub:
            continue
        tm, thw, tlo, thi = mean_ci95([float(e["score"]) for e in sub])
        ts_tot = sum(len(e.get("steps", [])) for e in sub)
        ts_inv = sum(int(e.get("meta", {}).get("invalid_calls", 0)) for e in sub)
        by_tier[t] = {
            "n": len(sub),
            "mean_score": round(tm, 6),
            "ci95": round(thw, 6),
            "ci95_low": round(tlo, 6),
            "ci95_high": round(thi, 6),
            "accuracy": round(sum(1 for e in sub if e["correct"]) / len(sub), 6),
            "valid_call_rate": round(1.0 - ts_inv / max(1, ts_tot), 6),
            "eval_cap_rate": round(sum(1 for e in sub if e["end_reason"] == "eval_cap") / len(sub), 6),
            "mean_steps": round(ts_tot / len(sub), 2),
        }
    return {
        "agent": agent_label,
        "n": len(eps),
        "mean_score": round(m, 6),
        "ci95": round(hw, 6),
        "ci95_low": round(lo, 6),
        "ci95_high": round(hi, 6),
        "accuracy": round(sum(1 for e in eps if e["correct"]) / max(1, len(eps)), 6),
        "valid_call_rate": round(valid_rate, 6),
        "invalid_call_rate": round(1.0 - valid_rate, 6),
        "eval_cap_rate": round(sum(1 for e in eps if e["end_reason"] == "eval_cap") / max(1, len(eps)), 6),
        "mean_steps": round(tot_steps / max(1, len(eps)), 2),
        "world_secret_tag": w_tag,
        "replay_verified": invalid_eps == 0 and err_eps == 0,
        "invalid_episodes": invalid_eps,
        "error_episodes": err_eps,
        "end_reasons": dict(sorted(end_reasons.items())),
        "by_tier": by_tier,
    }


def build_paired_summary(before_eps: list[dict[str, Any]], after_eps: list[dict[str, Any]]) -> dict[str, Any]:
    b_map = {(str(e["tier"]), int(e["seed"])): e for e in before_eps}
    a_map = {(str(e["tier"]), int(e["seed"])): e for e in after_eps}
    keys = sorted(set(b_map) & set(a_map), key=lambda x: (TIERS_ORDER.index(x[0]), x[1]))
    deltas = [round(float(a_map[k]["score"]) - float(b_map[k]["score"]), 6) for k in keys]
    m, hw, lo, hi = mean_ci95(deltas)
    by_tier: dict[str, Any] = {}
    for t in TIERS_ORDER:
        t_deltas = [
            round(float(a_map[k]["score"]) - float(b_map[k]["score"]), 6)
            for k in keys
            if k[0] == t
        ]
        if not t_deltas:
            continue
        tm, thw, tlo, thi = mean_ci95(t_deltas)
        by_tier[t] = {
            "n": len(t_deltas),
            "mean_delta": round(tm, 6),
            "ci95": round(thw, 6),
            "ci95_low": round(tlo, 6),
            "ci95_high": round(thi, 6),
            "wins": sum(1 for d in t_deltas if d > 1e-9),
            "losses": sum(1 for d in t_deltas if d < -1e-9),
            "ties": sum(1 for d in t_deltas if abs(d) <= 1e-9),
        }
    return {
        "n": len(deltas),
        "mean_delta": round(m, 6),
        "ci95": round(hw, 6),
        "ci95_low": round(lo, 6),
        "ci95_high": round(hi, 6),
        "wins": sum(1 for d in deltas if d > 1e-9),
        "losses": sum(1 for d in deltas if d < -1e-9),
        "ties": sum(1 for d in deltas if abs(d) <= 1e-9),
        "by_tier": by_tier,
        "deltas": deltas,
    }


def render_markdown_table(summary: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    b = summary["before"]
    a = summary["after"]
    p = summary["paired"]
    tr = summary["training"]
    lines = [
        f"{h1} Qwen2.5-1.5B-Instruct Raw-4k Frugal LoRA + On-Policy DAgger r1",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Model: `{summary['model']}`",
        f"- Tiers (`{summary['tiers_version']}`): `{', '.join(summary['tiers'])}`",
        f"- SFT r0 train seeds: `{summary['sft_seed_range']['start']}..{summary['sft_seed_range']['stop'] - 1}`",
        f"- DAgger r1 train seeds: `{summary['dagger_seed_range']['start']}..{summary['dagger_seed_range']['stop'] - 1}`",
        f"- Held-out eval seeds: `{summary['eval_seeds']['start']}..{summary['eval_seeds']['stop'] - 1}` (`n = {summary['n']}` paired episodes)",
        f"- World secret tag: `{b['world_secret_tag']}` (identical before and after)",
        f"- Tool-by-tool `Env` replay verified: `{summary['replay_verified']}` (`invalid_episodes = {summary['invalid_episodes']}`)",
        "",
        f"{h2} Overall Paired Held-Out Results (`n = {summary['n']}`)",
        "",
        "| Arm | n | Mean Score | 95% CI | Accuracy | Valid Call Rate | Eval Cap Rate | Mean Steps | Replay Verified |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |",
        f"| Before (`base_raw` 4k HFPolicy) | {b['n']} | {b['mean_score']:.4f} | [{b['ci95_low']:.4f}, {b['ci95_high']:.4f}] | {b['accuracy']:.4f} | {b['valid_call_rate']:.4f} | {b['eval_cap_rate']:.4f} | {b['mean_steps']:.2f} | {b['replay_verified']} |",
        f"| After (`dagger_r1` 4k HFPolicy) | {a['n']} | {a['mean_score']:.4f} | [{a['ci95_low']:.4f}, {a['ci95_high']:.4f}] | {a['accuracy']:.4f} | {a['valid_call_rate']:.4f} | {a['eval_cap_rate']:.4f} | {a['mean_steps']:.2f} | {a['replay_verified']} |",
        f"| Paired Delta (`after - before`) | {p['n']} | {p['mean_delta']:+.4f} | [{p['ci95_low']:+.4f}, {p['ci95_high']:+.4f}] | {a['accuracy'] - b['accuracy']:+.4f} | {a['valid_call_rate'] - b['valid_call_rate']:+.4f} | {a['eval_cap_rate'] - b['eval_cap_rate']:+.4f} | {a['mean_steps'] - b['mean_steps']:+.2f} | wins={p['wins']} losses={p['losses']} ties={p['ties']} |",
        "",
        f"{h2} Per-Tier Paired Breakdown",
        "",
        "| Tier | n | Before Score | After Score | Paired Delta | Paired 95% CI | Before Acc | After Acc | Wins / Losses / Ties |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for t in summary["tiers"]:
        if t not in b["by_tier"] or t not in a["by_tier"] or t not in p["by_tier"]:
            continue
        bt = b["by_tier"][t]
        at = a["by_tier"][t]
        pt = p["by_tier"][t]
        lines.append(
            f"| {t} | {pt['n']} | {bt['mean_score']:.4f} | {at['mean_score']:.4f} | {pt['mean_delta']:+.4f} | [{pt['ci95_low']:+.4f}, {pt['ci95_high']:+.4f}] | {bt['accuracy']:.4f} | {at['accuracy']:.4f} | {pt['wins']} / {pt['losses']} / {pt['ties']} |"
        )
    s0 = tr["sft_r0"]
    d1 = tr["dagger_r1"]
    lines.extend([
        "",
        f"{h2} Training Progression (Raw 4000-Token Window)",
        "",
        "| Stage | Episodes | Windows | Optimizer Steps | LR | Final Loss | Notes |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        f"| `sft_r0` (Frugal-V2 teacher) | {s0['episodes']} | {s0['windows']} | {s0['steps']} | {s0['lr']} | {s0['final_loss']:.4f} | teacher score {s0['teacher_mean_score']:.4f} |",
        f"| `dagger_r1` (50/50 SFT + relabeled on-policy) | {d1['rollout_episodes']} | {d1['windows']} | {d1['steps']} | {d1['lr']} | {d1['final_loss']:.4f} | sft_r0 student score {d1['student_sft_r0_mean_score']:.4f}, valid {d1['student_sft_r0_valid_call_rate']:.4f}, disagreements {d1['disagreement_states']}/{d1['relabeled_states']} |",
        "",
    ])
    return "\n".join(lines)


def _has_ml_stack() -> bool:
    return all(importlib.util.find_spec(pkg) is not None for pkg in ("torch", "transformers", "peft"))


def build_tiny_qwen2_config_kwargs(tok: Any) -> dict[str, Any]:
    tok_vocab = int(getattr(tok, "vocab_size", 4096) or 4096)
    eos_id = getattr(tok, "eos_token_id", 2)
    pad_id = getattr(tok, "pad_token_id", None)
    if pad_id is None:
        pad_id = eos_id
    return {
        "vocab_size": max(len(tok), tok_vocab),
        "hidden_size": 32,
        "intermediate_size": 64,
        "num_hidden_layers": 1,
        "num_attention_heads": 2,
        "num_key_value_heads": 1,
        "max_position_embeddings": 4096,
        "tie_word_embeddings": True,
        "eos_token_id": eos_id,
        "pad_token_id": pad_id,
    }


def load_base_and_tokenizer(model_path: str, tiny: bool):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

    if tiny:
        torch.set_num_threads(1)
        if Path(model_path).is_dir():
            tok: Any = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        else:
            tok = SyntheticChatTokenizer()
        cfg = Qwen2Config(**build_tiny_qwen2_config_kwargs(tok))
        cfg._attn_implementation = "sdpa"
        torch.manual_seed(0)
        model = Qwen2ForCausalLM(cfg).to("cpu").eval()
        return model, tok

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cpu":
        torch.set_num_threads(1)
    tok = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=dtype,
        attn_implementation="sdpa",
    )
    model.to(dev).eval()
    return model, tok


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    t_start = time.time()
    ml_ready = _has_ml_stack()
    if not ml_ready and not args.tiny:
        raise ImportError("torch, transformers, and peft are required for non-tiny training")

    out_dir = Path(args.out_dir)
    work_dir = Path(args.work_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.tiny:
        sft_start, sft_stop = 110_000, 110_003
        dag_start, dag_stop = 110_240, 110_243
        eval_start, eval_stop = 800_000, 800_001
        sft_steps = 1
        dagger_steps = 1
        grad_accum = 1
        sft_max_calls = 20
        rollout_max_calls = 2
        max_new = 4
        batch_size = 3
        lora_r = 4
        lora_alpha = 8
    else:
        sft_start, sft_stop = args.sft_seed_start, args.sft_seed_stop
        dag_start, dag_stop = args.dagger_seed_start, args.dagger_seed_stop
        eval_start, eval_stop = args.eval_seed_start, args.eval_seed_stop
        sft_steps = args.sft_steps
        dagger_steps = args.dagger_steps
        grad_accum = args.grad_accum
        sft_max_calls = args.max_calls
        rollout_max_calls = args.max_calls
        max_new = args.max_new_tokens
        batch_size = args.batch_size
        lora_r = args.lora_r
        lora_alpha = args.lora_alpha

    plan = validate_seed_plan(
        range(sft_start, sft_stop),
        range(dag_start, dag_stop),
        range(eval_start, eval_stop),
        world_secret=args.world_secret,
    )
    w_tag = plan["world_secret_tag"]
    sft_specs = [(TIERS_ORDER[i % 3], s) for i, s in enumerate(plan["sft"])]
    dagger_specs = [(TIERS_ORDER[i % 3], s) for i, s in enumerate(plan["dagger"])]
    eval_specs = [(t, s) for s in plan["eval"] for t in TIERS_ORDER]

    print(f"[init] model={args.model} tiny={args.tiny} ml_stack={ml_ready} secret_tag={w_tag}", flush=True)

    if not ml_ready:
        tok: Any = SyntheticChatTokenizer()
        tcache = FastTemplateCache(tok)
        sft_windows, sft_data_stats = collect_sft_data(
            tcache,
            specs=sft_specs,
            max_ctx=args.max_ctx,
            max_new=max_new,
            max_calls=sft_max_calls,
            use_solver_posterior=args.use_solver_posterior,
        )
        with world_secret_scope(args.world_secret):
            before_eps, _, _ = _run_pure_python_tiny_episodes(
                tcache,
                specs=eval_specs,
                agent_name="qwen2.5-1.5b-instruct-raw-4k-base",
                raw_reply="unparseable_base_output",
                max_ctx=args.max_ctx,
                max_new=max_new,
                max_calls=rollout_max_calls,
                collect_dagger=False,
                world_secret_tag=w_tag,
            )
        sft_train_stats = {
            "steps": sft_steps,
            "grad_accum": grad_accum,
            "lr": args.sft_lr,
            "final_loss": 1.25,
            "seconds": 0.01,
        }
        valid_reply = '<tool_call>\n{"name": "check_leak_feed", "arguments": {}}\n</tool_call>'
        _, dagger_windows, dagger_rollout_stats = _run_pure_python_tiny_episodes(
            tcache,
            specs=dagger_specs,
            agent_name="qwen2.5-1.5b-instruct-raw-4k-sft-r0",
            raw_reply=valid_reply,
            max_ctx=args.max_ctx,
            max_new=max_new,
            max_calls=rollout_max_calls,
            collect_dagger=True,
            world_secret_tag=None,
            use_solver_posterior=args.use_solver_posterior,
        )
        dagger_train_stats = {
            "steps": dagger_steps,
            "grad_accum": grad_accum,
            "lr": args.dagger_lr,
            "final_loss": 0.95,
            "seconds": 0.01,
        }
        with world_secret_scope(args.world_secret):
            after_eps, _, _ = _run_pure_python_tiny_episodes(
                tcache,
                specs=eval_specs,
                agent_name="qwen2.5-1.5b-instruct-raw-4k-frugal-dagger-r1",
                raw_reply=valid_reply,
                max_ctx=args.max_ctx,
                max_new=max_new,
                max_calls=rollout_max_calls,
                collect_dagger=False,
                world_secret_tag=w_tag,
            )
    else:
        import torch
        from peft import LoraConfig, get_peft_model

        model, tok = load_base_and_tokenizer(args.model, args.tiny)
        tcache = FastTemplateCache(tok)

        print(f"[sft_data] collecting FRUGAL-V2 trajectories on {len(sft_specs)} episodes", flush=True)
        sft_windows, sft_data_stats = collect_sft_data(
            tcache,
            specs=sft_specs,
            max_ctx=args.max_ctx,
            max_new=max_new,
            max_calls=sft_max_calls,
            use_solver_posterior=args.use_solver_posterior,
        )
        print(f"[sft_data] {json.dumps(sft_data_stats)}", flush=True)

        print(f"[eval_before] running base_raw on n={len(eval_specs)} held-out episodes", flush=True)
        with world_secret_scope(args.world_secret):
            before_eps, _, _ = run_batched_hf_episodes(
                model,
                tcache,
                specs=eval_specs,
                agent_name="qwen2.5-1.5b-instruct-raw-4k-base",
                max_ctx=args.max_ctx,
                max_new=max_new,
                max_calls=rollout_max_calls,
                batch_size=batch_size,
                collect_dagger=False,
                world_secret_tag=w_tag,
            )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        lora_cfg = LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=LORA_TARGETS,
        )
        peft_model = get_peft_model(model, lora_cfg)
        sft_train_stats = train_lora_windows(
            peft_model,
            primary_windows=sft_windows,
            steps=sft_steps,
            lr=args.sft_lr,
            grad_accum=grad_accum,
            replay_windows=None,
            rng_seed=0,
            tag="sft_r0",
        )
        if not args.tiny:
            peft_model.save_pretrained(str(work_dir / "adapter_sft_r0"))
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        print(f"[dagger_rollout] rolling out sft_r0 on {len(dagger_specs)} train episodes", flush=True)
        _, dagger_windows, dagger_rollout_stats = run_batched_hf_episodes(
            peft_model,
            tcache,
            specs=dagger_specs,
            agent_name="qwen2.5-1.5b-instruct-raw-4k-sft-r0",
            max_ctx=args.max_ctx,
            max_new=max_new,
            max_calls=rollout_max_calls,
            batch_size=batch_size,
            collect_dagger=True,
            world_secret_tag=None,
            use_solver_posterior=args.use_solver_posterior,
        )
        print(f"[dagger_rollout] {json.dumps(dagger_rollout_stats)}", flush=True)
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        dagger_train_stats = train_lora_windows(
            peft_model,
            primary_windows=dagger_windows if dagger_windows else sft_windows,
            steps=dagger_steps,
            lr=args.dagger_lr,
            grad_accum=grad_accum,
            replay_windows=sft_windows,
            rng_seed=1,
            tag="dagger_r1",
        )
        if not args.tiny:
            peft_model.save_pretrained(str(work_dir / "adapter_dagger_r1"))

        merged_model = peft_model.merge_and_unload().eval()
        if hasattr(merged_model, "config"):
            merged_model.config.use_cache = True
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        print(f"[eval_after] running dagger_r1 on n={len(eval_specs)} held-out episodes", flush=True)
        with world_secret_scope(args.world_secret):
            after_eps, _, _ = run_batched_hf_episodes(
                merged_model,
                tcache,
                specs=eval_specs,
                agent_name="qwen2.5-1.5b-instruct-raw-4k-frugal-dagger-r1",
                max_ctx=args.max_ctx,
                max_new=max_new,
                max_calls=rollout_max_calls,
                batch_size=batch_size,
                collect_dagger=False,
                world_secret_tag=w_tag,
            )

    before_summary = summarize_arm(
        before_eps,
        "qwen2.5-1.5b-instruct-raw-4k-base",
        w_tag,
        max_calls=rollout_max_calls,
        world_secret=args.world_secret,
    )
    after_summary = summarize_arm(
        after_eps,
        "qwen2.5-1.5b-instruct-raw-4k-frugal-dagger-r1",
        w_tag,
        max_calls=rollout_max_calls,
        world_secret=args.world_secret,
    )
    paired_summary = build_paired_summary(before_eps, after_eps)
    print(
        f"[eval_done] before={before_summary['mean_score']:.4f} after={after_summary['mean_score']:.4f} delta={paired_summary['mean_delta']:+.4f} ci95=[{paired_summary['ci95_low']:+.4f}, {paired_summary['ci95_high']:+.4f}]",
        flush=True,
    )

    with open(work_dir / "before_episodes.jsonl", "w", encoding="utf-8") as fb:
        for ep in before_eps:
            fb.write(json.dumps(ep, default=str) + "\n")
    with open(work_dir / "after_episodes.jsonl", "w", encoding="utf-8") as fa:
        for ep in after_eps:
            fa.write(json.dumps(ep, default=str) + "\n")

    invalid_total = int(before_summary["invalid_episodes"]) + int(after_summary["invalid_episodes"])
    error_total = int(before_summary["error_episodes"]) + int(after_summary["error_episodes"])
    replay_ok = bool(
        before_summary["replay_verified"]
        and after_summary["replay_verified"]
        and invalid_total == 0
        and error_total == 0
    )

    train_seeds_field: Any = (
        {"start": sft_start, "stop": dag_stop}
        if sft_stop == dag_start
        else plan["train_all"]
    )
    summary = {
        "run_id": RUN_ID,
        "model": MODEL_LABEL,
        "tiers_version": TIERS_VERSION,
        "tiers": list(TIERS_ORDER),
        "n": len(eval_specs),
        "train_seeds": train_seeds_field,
        "sft_seed_range": {"start": sft_start, "stop": sft_stop},
        "dagger_seed_range": {"start": dag_start, "stop": dag_stop},
        "eval_seeds": {"start": eval_start, "stop": eval_stop},
        "world_secret_tag": w_tag,
        "replay_verified": replay_ok,
        "invalid_episodes": invalid_total,
        "error_episodes": error_total,
        "inference_modules": [
            "train/eval_hf.py",
            "train/frugal_raw_dagger.py",
        ],
        "before": before_summary,
        "after": after_summary,
        "paired": paired_summary,
        "training": {
            "context_window_tokens": args.max_ctx,
            "max_new_tokens": max_new,
            "max_calls": rollout_max_calls,
            "lora_r": lora_r,
            "lora_alpha": lora_alpha,
            "sft_r0": {
                **sft_data_stats,
                **sft_train_stats,
            },
            "dagger_r1": {
                "rollout_episodes": dagger_rollout_stats["episodes"],
                "student_sft_r0_mean_score": dagger_rollout_stats["mean_score"],
                "student_sft_r0_valid_call_rate": dagger_rollout_stats["valid_call_rate"],
                "relabeled_states": dagger_rollout_stats["relabeled_states"],
                "disagreement_states": dagger_rollout_stats["disagreement_states"],
                "windows": dagger_rollout_stats["windows"],
                **dagger_train_stats,
            },
            "total_seconds": round(time.time() - t_start, 2),
        },
    }
    table_md = render_markdown_table(summary)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out_dir / "table.md").write_text(table_md, encoding="utf-8")
    if work_dir.resolve() != out_dir.resolve():
        (work_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (work_dir / "table.md").write_text(table_md, encoding="utf-8")
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m train.frugal_raw_dagger")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out-dir", default="results/tiebreak/frugal_raw_dagger")
    ap.add_argument("--work-dir", default="/tmp/fleet-silas/shared/tiebreak-v100/qwen15b_raw_dagger_v1")
    ap.add_argument("--world-secret", default=HELDOUT_SECRET)
    ap.add_argument("--max-ctx", type=int, default=4000)
    ap.add_argument("--max-new-tokens", type=int, default=80)
    ap.add_argument("--max-calls", type=int, default=80)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--sft-seed-start", type=int, default=110000)
    ap.add_argument("--sft-seed-stop", type=int, default=110240)
    ap.add_argument("--dagger-seed-start", type=int, default=110240)
    ap.add_argument("--dagger-seed-stop", type=int, default=110360)
    ap.add_argument("--eval-seed-start", type=int, default=800000)
    ap.add_argument("--eval-seed-stop", type=int, default=800030)
    ap.add_argument("--sft-steps", type=int, default=220)
    ap.add_argument("--dagger-steps", type=int, default=160)
    ap.add_argument("--sft-lr", type=float, default=2e-4)
    ap.add_argument("--dagger-lr", type=float, default=1e-4)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--use-solver-posterior", action="store_true")
    ap.add_argument("--tiny", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_pipeline(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
