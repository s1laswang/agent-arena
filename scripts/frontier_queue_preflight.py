from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import random
import re
import shlex
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from pydantic_core import (
        SchemaValidator as _SchemaValidator,
        core_schema as _cs,
        from_json as _loads_json,
    )
except ImportError:
    _SchemaValidator = None
    _cs = None
    _loads_json = json.loads

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.agents.frontier import common, opencode_run
from canary.env import TOPICS as _ENV_TOPICS, _SPECS as _ENV_SPECS, Env
from canary.llm import base as llm_base
from canary.mole.dsl import DEFAULT_STRATEGY, MoleDoc, MoleView
from canary.rules import TRACKS, tier_params
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.template import SIGNALS as _IV_SIGNALS, TOPICS as _IV_TOPICS, TemplateProvider
from canary.types import ToolResult
from canary.world import generate_world, world_seed

VENV_PYTHON = "/tmp/fleet-silas/shared/agent-arena-venv/bin/python"
MOMIN_PATH_PREFIX = "PATH=/home/silas/momin/bin:$PATH"
RUNNER_MODULE = "canary.agents.frontier.opencode_run"
DEFAULT_TIMEOUT_S = 3600
GPT55_TIMEOUT_S = 7200
ALLOWED_TIMEOUTS_S: tuple[int, ...] = (DEFAULT_TIMEOUT_S, GPT55_TIMEOUT_S)
DEFAULT_JOBS = 1
MAX_WORKERS_PER_WAVE = 3

EXPECTED_PERMISSION = {"*": "deny", "canary_*": "allow"}
EXPECTED_CARBON_HARD_LANDED = [30, 34, 42, 45, 57]
EXPECTED_CARBON_HARD_MISSING = [
    31, 32, 33, 35, 36, 37, 38, 39, 40, 41,
    43, 44, 46, 47, 48, 49, 50, 51, 52, 53,
    54, 55, 56, 58, 59,
]
EXPECTED_G1_COMMITTED_EXT_LANDED = [34, 37]
EXPECTED_G1_COMMITTED_EXT_QUOTA_EXCLUDED = 31
EXPECTED_GPT55_COMMITTED_LANDED = list(range(30))
EXPECTED_GPT55_CLEAN_UNENDED_SEEDS = [0, 17]
EXPECTED_GPT55_INFRA_EXCLUDED = 0
EXPECTED_COMBINED_CARBON_HARD_EXT_LANDED = [30, 34, 37, 42, 45, 57]
EXPECTED_COMBINED_CARBON_HARD_EXT_REMAINING_COUNT = 24
EXPECTED_COMMITTED_V14_EPISODES = 472
EXPECTED_REPLICATION_V14_EPISODES = 305
EXPECTED_COMBINED_V14_EPISODES = 777
EXPECTED_FLASH_MEDIUM_LANDED = list(range(30))
EXPECTED_FLASH_MEDIUM_MISSING: list[int] = []
EXPECTED_FLASH_HARD_LANDED: list[int] = []
EXPECTED_FLASH_HARD_MISSING = list(range(30, 60))

GEMINI_SESSIONS_DOC = "docs/agents/GEMINI-SESSIONS.md"
GEMINI_SESSIONS_COMMIT = "f9fb7a4a"
PANEL_DOC = "docs/agents/PANEL-0500.md"
PANEL_STATUS_COMMIT = "8b9afa61"
PANEL_FIX_A_COMMIT = "92708834"
PANEL_FIX_D_COMMIT = "1bc3e281"
GPT55_PREREG_COMMIT = "cf394894"
GPT55_COMMITTED_COMMIT = "ca0a0dc0"
GPT55_COMMITTED_DIR = "data/runs/committed/v1.4/opencode-gpt-5.5/hard"
UPSTREAM_RECONCILED_COMMIT = "5f9b3297"
PRIMARY_EPISODES_COMMIT = "8fd4dec"
PRIMARY_POST_HOC_LOCK_COMMIT = "671ed96"
PRIMARY_POST_HOC_LOCK_DELAY_S = 28

CARBON_MODEL = "google/gemini-4-carbon"
OPENAI_GPT55_MODEL = "openai/gpt-5.5"
G2_MODELS: tuple[str, ...] = (
    "google/gemini-4-argon",
    "google/gemini-4-hydrogen",
)
NON_CARBON_REHEARSAL_ALLOWED_MODELS: tuple[str, ...] = (
    "google/gemini-4-argon",
    "google/gemini-4-hydrogen",
    "openai/gpt-5.5",
)
CARBON_BLACKOUT_START_ISO = "2026-11-15T04:30:00Z"
CARBON_BLACKOUT_END_ISO = "2026-11-15T06:15:00Z"
CARBON_BLACKOUT_START_UTC = datetime(2026, 11, 15, 4, 30, 0, tzinfo=timezone.utc)
CARBON_BLACKOUT_END_UTC = datetime(2026, 11, 15, 6, 15, 0, tzinfo=timezone.utc)
CARBON_BLACKOUT_LOCAL_WINDOW = "06:30-08:15 Europe/Helsinki"
CARBON_BLACKOUT_REASON = "rehearsal_carbon_blackout_0630_0815_eet"

TARGET_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-gemini-4-carbon-hard-30-59",
        "agent_dir": "opencode-gemini-4-carbon",
        "agent": "opencode:google/gemini-4-carbon",
        "model": "google/gemini-4-carbon",
        "tier": "hard",
        "seed_start": 30,
        "seed_end": 59,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "baseline_landed_seeds": EXPECTED_CARBON_HARD_LANDED,
        "priority": 1,
        "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
        "execution_owner": "silas_g1_ext60",
        "fr8_dispatch_enabled": False,
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash-medium-0-29",
        "agent_dir": "opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "model": "google/gemini-3.5-flash",
        "tier": "medium",
        "seed_start": 0,
        "seed_end": 29,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "baseline_landed_seeds": EXPECTED_FLASH_MEDIUM_LANDED,
        "priority": 2,
        "execution_owner": "fr8_frontier_complete",
        "fr8_dispatch_enabled": False,
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash-hard-30-59",
        "agent_dir": "opencode-gemini-3.5-flash",
        "agent": "opencode:google/gemini-3.5-flash",
        "model": "google/gemini-3.5-flash",
        "tier": "hard",
        "seed_start": 30,
        "seed_end": 59,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "baseline_landed_seeds": EXPECTED_FLASH_HARD_LANDED,
        "priority": 3,
        "execution_owner": "fr8_frontier_paused_pure_cpu",
        "fr8_dispatch_enabled": False,
    },
)

G2_TEMPLATE_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-gemini-4-argon-hard-0-29",
        "priority": 10,
        "agent_dir": "opencode-gemini-4-argon",
        "agent": "opencode:google/gemini-4-argon",
        "model": "google/gemini-4-argon",
        "tier": "hard",
        "seed_range": [0, 29],
        "missing_seeds": list(range(30)),
        "timeout_s": DEFAULT_TIMEOUT_S,
        "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
        "execution_owner": "silas_g2_families",
        "fr8_dispatch_enabled": False,
    },
    {
        "cohort_id": "opencode-gemini-4-hydrogen-hard-0-29",
        "priority": 11,
        "agent_dir": "opencode-gemini-4-hydrogen",
        "agent": "opencode:google/gemini-4-hydrogen",
        "model": "google/gemini-4-hydrogen",
        "tier": "hard",
        "seed_range": [0, 29],
        "missing_seeds": list(range(30)),
        "timeout_s": DEFAULT_TIMEOUT_S,
        "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
        "execution_owner": "silas_g2_families",
        "fr8_dispatch_enabled": False,
    },
)

GPT55_TEMPLATE_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "opencode-openai-gpt-5.5-hard-0-29",
        "priority": 12,
        "agent_dir": "opencode-openai-gpt-5.5",
        "agent": "opencode:openai/gpt-5.5",
        "model": OPENAI_GPT55_MODEL,
        "tier": "hard",
        "seed_range": [0, 29],
        "missing_seeds": list(range(30)),
        "timeout_s": GPT55_TIMEOUT_S,
        "max_spend_usd": 200.0,
        "stop_launch_at": "08:15",
        "hard_drop_at": "08:45",
        "pre_registered_commit": GPT55_PREREG_COMMIT,
        "committed_commit": GPT55_COMMITTED_COMMIT,
        "committed_dir": GPT55_COMMITTED_DIR,
        "execution_owner": "silas_ca0a0dc0_committed_complete",
        "fr8_dispatch_enabled": False,
    },
)

TEMPLATE_COHORTS: tuple[dict[str, Any], ...] = G2_TEMPLATE_COHORTS + GPT55_TEMPLATE_COHORTS

PROVIDER_KEY_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
)

STRIPPED_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "OLDPWD",
    "CANARY_LEDGER_TOKEN",
    "CANARY_ADMIN_TOKEN",
    "CANARY_WORLD_SECRET",
    "CANARY_TOKEN",
    "OPENCODE_CONFIG",
)


def split_transcript(text: str) -> tuple[str, str]:
    marker_out = "\n--- stdout\n"
    marker_err = "\n--- stderr\n"
    if marker_out not in text:
        return text, ""
    _, _, after_out = text.partition(marker_out)
    if marker_err in after_out:
        stdout, _, stderr = after_out.rpartition(marker_err)
        return stdout, stderr
    if after_out.endswith("\n--- stderr"):
        return after_out[: -len("\n--- stderr")], ""
    return after_out, ""


def _with_dev_seeds_allowed():
    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    return prev


def _restore_dev_seeds(prev: str | None) -> None:
    if prev is None:
        os.environ.pop("CANARY_ALLOW_DEV", None)
    else:
        os.environ["CANARY_ALLOW_DEV"] = prev


_BASE_TEMPLATE_PROVIDER = TemplateProvider()
_BASE_ENV_CACHE: dict[tuple[str, int, int], tuple[Env, tuple[EmployeeFacts, ...], str, Any]] = {}
_SCALAR_ENV_CACHE: dict[tuple[str, int, int], tuple[Any, ...]] = {}
_DAY_MSG_CACHE: dict[tuple[Any, ...], tuple[dict[str, Any], ...]] = {}
_IV_ANS_CACHE: dict[tuple[Any, ...], str] = {}
_REPLAY_OUTCOME_CACHE: dict[tuple[str, int, Any], dict[str, Any]] = {}
_EPISODE_FILE_CACHE: dict[tuple[str, int, int, int], tuple[tuple[int, dict[str, Any], bytes | None], ...]] = {}
_COMMITTED_LOOKUP_CACHE: dict[tuple[str, tuple[tuple[str, int, int], ...]], dict[tuple[str, str], list[int]]] = {}
_TRANSCRIPT_PARSE_CACHE: dict[
    tuple[str, int, int, int],
    tuple[bool, bool, str | None, list[str], list[int], list[Any]],
] = {}
_OK_TOOL_RESULT = ToolResult(True, {})
_NONE_FACTS = lambda _d: None
_MARKER_STEPS = b'"steps": ['
_MARKER_TAIL_UNSORTED = b'], "score": '
_MARKER_TAIL_SORTED = b'], "tier": '
_MARKER_RES = b', "result": '
_MARKER_ARGS_START = b'{"args": '
_STEP_NEEDLES_UNSORTED: tuple[bytes, ...] = tuple(
    f'{{"t": {i}, "day": '.encode("ascii") for i in range(512)
)
_STEP_NEEDLES_SORTED_T: tuple[bytes, ...] = tuple(
    f', "t": {i}, "tool": '.encode("ascii") for i in range(512)
)
_CLI_PARSER_CACHE: Any = None
_CMD_VALIDATION_CACHE: dict[tuple[str, str, int, int, str], tuple[str, ...]] = {}
_GEMINI_RUNNER_CHECK_CACHE: dict[str, Any] | None = None
_MCP_ENV_HELPERS_CACHE: tuple[tuple[str, ...], Any] | None = None
_READONLY_NON_INV: frozenset[str] = frozenset({"status", "list_employees", "list_documents"})
_READONLY_INV_SIMPLE: frozenset[str] = frozenset({"read_access_logs", "check_leak_feed"})
_ZERO_ARG_TOOLS: frozenset[str] = frozenset(
    {"advance_day", "status", "list_employees", "check_leak_feed", "list_documents"}
)
_UNREDACTED_SIG_BYTES_RX = re.compile(rb'"thoughtSignature":\s?"[^"<]{64,}"')


def _build_ep_head_validator() -> Any:
    if _SchemaValidator is None or _cs is None:
        return None
    meta_s = _cs.typed_dict_schema(
        {
            "valid": _cs.typed_dict_field(_cs.bool_schema(), required=False),
            "rc": _cs.typed_dict_field(_cs.any_schema(), required=False),
            "error": _cs.typed_dict_field(_cs.nullable_schema(_cs.str_schema()), required=False),
        },
        extra_behavior="ignore",
    )
    ep_s = _cs.typed_dict_schema(
        {
            "tier": _cs.typed_dict_field(_cs.str_schema()),
            "seed": _cs.typed_dict_field(_cs.int_schema()),
            "agent": _cs.typed_dict_field(_cs.str_schema(), required=False),
            "score": _cs.typed_dict_field(_cs.float_schema()),
            "accused": _cs.typed_dict_field(_cs.nullable_schema(_cs.str_schema()), required=False),
            "correct": _cs.typed_dict_field(_cs.bool_schema()),
            "final_day": _cs.typed_dict_field(_cs.nullable_schema(_cs.int_schema()), required=False),
            "end_reason": _cs.typed_dict_field(_cs.nullable_schema(_cs.str_schema()), required=False),
            "meta": _cs.typed_dict_field(_cs.nullable_schema(meta_s), required=False),
        },
        extra_behavior="ignore",
    )
    return _SchemaValidator(ep_s)


_EP_HEAD_VALIDATOR = _build_ep_head_validator()


def _load_mcp_server_env_helpers() -> tuple[tuple[str, ...], Any]:
    global _MCP_ENV_HELPERS_CACHE
    if "canary.mcp_server" in sys.modules:
        mod = sys.modules["canary.mcp_server"]
        return tuple(mod.PLAIN_SECRET_VARS), mod.clean_launch_env
    if _MCP_ENV_HELPERS_CACHE is not None:
        return _MCP_ENV_HELPERS_CACHE
    mcp_path = ROOT / "canary" / "mcp_server.py"
    tree = ast.parse(mcp_path.read_text(encoding="utf-8"), filename=str(mcp_path))
    selected: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "PLAIN_SECRET_VARS" for t in node.targets):
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "clean_launch_env":
            selected.append(node)
    mod_ast = ast.Module(body=selected, type_ignores=[])
    ns: dict[str, Any] = {"os": os}
    exec(compile(mod_ast, str(mcp_path), "exec"), ns)
    _MCP_ENV_HELPERS_CACHE = (tuple(ns["PLAIN_SECRET_VARS"]), ns["clean_launch_env"])
    return _MCP_ENV_HELPERS_CACHE


def _ok_tool_fn(_args: Any, _res: ToolResult = _OK_TOOL_RESULT) -> ToolResult:
    return _res


def _make_replay_aux(env_obj: Env) -> tuple[tuple[str, ...], tuple[str, ...], tuple[float, float, float]]:
    w = env_obj._world
    p = env_obj.p
    mole_peers = tuple(e for e in env_obj._ids if e != w.mole)
    frame_others = tuple(x for x in env_obj._ids if x != w.mole and x != w.decoy)
    exp_tup = (
        math.exp(-p.log_rate_mole) if p.log_rate_mole > 0 else 2.0,
        math.exp(-p.log_rate_benign) if p.log_rate_benign > 0 else 2.0,
        math.exp(-p.framing_rate) if p.framing_rate > 0 else 2.0,
    )
    return (mole_peers, frame_others, exp_tup)


def _fast_advance_day(self: Env) -> None:
    tp, w, d, rng = self.p, self._world, self.day, self._dyn
    mole_peers, frame_others, (L_m, L_b, L_f) = self._replay_aux
    mole = w.mole
    doc_by_id = self._doc_by_id
    leaked_set = self._leaked
    held_map = self._held
    restricted = self._restricted
    rand = rng.random
    randbelow = rng._randbelow
    lo = d - tp.leak_window_days + 1
    leakable = [
        doc_by_id[x]
        for x in held_map[mole]
        if x not in leaked_set and lo <= doc_by_id[x]["day"] <= d
    ]
    can_leak = bool(leakable) and rand() < tp.p_leak
    weights = (
        tuple(1.0 - len(x["recipients"]) / tp.n_employees if x["is_canary"] else 1.0 for x in leakable)
        if tp.careful_mole
        else None
    )
    rpeers = tuple(e for e in mole_peers if e in restricted) if restricted else ()
    low_thr = tp.low_recipient_threshold
    view = MoleView(
        day=d,
        docs=tuple(MoleDoc(x["doc_id"], x["title"], len(x["recipients"]), d - x["day"]) for x in leakable),
        days_since_last_leak=d - self._last_leak_day if self._last_leak_day else d,
        i_am_restricted=int(mole in restricted),
        n_restricted_colleagues=len(rpeers),
        recent_low_recipient_docs=sum(1 for x in leakable if len(x["recipients"]) <= low_thr),
        peers=mole_peers,
        restricted_peers=rpeers,
        decoy=w.decoy,
        can_leak=can_leak,
        select_weights=weights,
    )
    strat = w.mole_strategy or DEFAULT_STRATEGY
    try:
        dec = strat.decide(view, rng)
    except TypeError:
        dec = strat.decide(view)
    leak = dec.get("leak")
    if leak is not None:
        doc = doc_by_id[leak]
        randbelow(len(tp.delay_choices))
        if doc["is_canary"]:
            true_v = next(k for k, v in doc["variants"].items() if mole in v)
            n_others = len(doc["variants"]) - 1
            if tp.fingerprint_accuracy < 1.0 and n_others > 0 and rand() >= tp.fingerprint_accuracy:
                randbelow(n_others)
        leaked_set.add(leak)
        self._charge(tp.leak_damage)
        self._last_leak_day = d
    if restricted:
        self._cost(tp.restrict_cost_per_day * len(restricted))
    for e in self._ids:
        held = held_map[e]
        nh = len(held)
        if not nh:
            continue
        L = L_m if e == mole else L_b
        if L <= 1.0:
            pr = rand()
            if pr > L:
                cnt = 1
                pr *= rand()
                while pr > L:
                    cnt += 1
                    pr *= rand()
                for _ in range(cnt):
                    randbelow(nh)
                    rand()
    if tp.framing and L_f <= 1.0:
        pr_f = rand()
        if pr_f > L_f:
            cnt_f = 1
            pr_f *= rand()
            while pr_f > L_f:
                cnt_f += 1
                pr_f *= rand()
            decoy = w.decoy
            n_others = len(frame_others)
            f_share = tp.framing_decoy_share
            for _ in range(cnt_f):
                tgt = decoy if (decoy is not None and rand() < f_share) else frame_others[randbelow(n_others)]
                nh_t = len(held_map[tgt])
                if nh_t:
                    randbelow(nh_t)
    tgt = dec.get("frame")
    if tgt is not None and tgt in self._idset and tgt != mole:
        nh_t = len(held_map[tgt])
        if nh_t:
            randbelow(nh_t)
    if self.provider.need_messages:
        for m in self.provider.day_messages(self._facts(d)):
            mid = m["id"]
            if mid not in self._messages:
                self._messages[mid] = dict(m)
                self._msg_order.append(mid)
    if d >= tp.n_days:
        self._end("horizon")
        return
    nd = d + 1
    self.day = nd
    self._actions_today = 0
    self._canaries_today = 0
    if not restricted:
        docs_list = self.docs
        for raw in w.planned_docs.get(nd, ()):
            did = raw["doc_id"]
            recs = list(raw["recipients"])
            doc = {"doc_id": did, "title": raw["title"], "day": nd, "recipients": recs, "is_canary": False}
            docs_list.append(doc)
            doc_by_id[did] = doc
            for rec in recs:
                held_map[rec].append(did)
    else:
        self._publish_day(nd)


def _advance_day_outcome_only(self: Env, _args: Any) -> ToolResult:
    _fast_advance_day(self)
    return _OK_TOOL_RESULT


class _ReplayTemplateProvider:
    name = "template"
    __slots__ = ("need_messages", "need_interview_text")

    def __init__(self, need_messages: bool = False, need_interview_text: bool = False) -> None:
        self.need_messages = need_messages
        self.need_interview_text = need_interview_text

    def day_messages(self, facts: PublicDayFacts | None) -> Any:
        if not self.need_messages or facts is None:
            return ()
        dkey = tuple(
            (d.get("doc_id"), d.get("title"), tuple(d.get("recipients", ())))
            for d in facts.docs[:3]
        )
        key = (facts.tier, facts.seed, facts.day, dkey)
        got = _DAY_MSG_CACHE.get(key)
        if got is None:
            got = tuple(_BASE_TEMPLATE_PROVIDER.day_messages(facts))
            if len(_DAY_MSG_CACHE) >= 4096:
                _DAY_MSG_CACHE.clear()
            _DAY_MSG_CACHE[key] = got
        return got

    def interview_answer(
        self,
        facts: PublicDayFacts | None,
        employee: str,
        topic: str,
        signal: str,
    ) -> str:
        if not self.need_interview_text or facts is None:
            return ""
        if topic not in _IV_TOPICS or signal not in _IV_SIGNALS:
            return _BASE_TEMPLATE_PROVIDER.interview_answer(facts, employee, topic, signal)
        mine = [d for d in facts.docs if employee in d.get("recipients", ())] or list(facts.docs)
        doc = mine[0].get("title", "the latest brief") if mine else "the latest team brief"
        key = (facts.tier, facts.seed, facts.day, employee, topic, signal, doc)
        got = _IV_ANS_CACHE.get(key)
        if got is None:
            got = _BASE_TEMPLATE_PROVIDER.interview_answer(facts, employee, topic, signal)
            if len(_IV_ANS_CACHE) >= 16384:
                _IV_ANS_CACHE.clear()
            _IV_ANS_CACHE[key] = got
        return got


_NOOP_REPLAY_PROVIDER = _ReplayTemplateProvider(need_messages=False, need_interview_text=False)


def _make_replay_env(
    tier: str,
    seed: int,
    provider: _ReplayTemplateProvider,
    outcome_only: bool = True,
) -> Env:
    if tier in TRACKS:
        tr_env = Env(tier, seed, text_provider=provider)
        tr_env._replay_aux = _make_replay_aux(tr_env)
        return tr_env
    ws = world_seed(tier, seed)
    ckey = (tier, seed, ws)
    cached = _BASE_ENV_CACHE.get(ckey)
    if cached is None:
        proto = Env(tier, seed, text_provider=_NOOP_REPLAY_PROVIDER)
        emp_facts = tuple(
            EmployeeFacts(e.id, e.name, e.dept, e.role, e.clearance)
            for e in proto._world.employees
        )
        decoy_mood = "angry" if proto._world.decoy else "neutral"
        aux = _make_replay_aux(proto)
        if len(_BASE_ENV_CACHE) >= 256:
            _BASE_ENV_CACHE.clear()
        cached = (proto, emp_facts, decoy_mood, aux)
        _BASE_ENV_CACHE[ckey] = cached
    proto, emp_facts, decoy_mood, aux = cached
    w = proto._world
    env = Env.__new__(Env)
    env.tier = tier
    env.seed = seed
    env.p = proto.p
    env._world = w
    env._dyn = random.Random(w.world_seed ^ 1)
    env.provider = provider
    env._ids = list(proto._ids)
    env._idset = set(proto._idset)
    env._replay_aux = aux
    env.day = 1
    env.V = 1.0
    env._costs = 0.0
    env._done = False
    env._end_reason = None
    env._accused = None
    env._correct = False
    env._lock = threading.RLock()
    env._actions_today = 0
    env._canaries_today = 0
    env._restricted = set()
    docs = [dict(d, recipients=list(d["recipients"])) for d in proto.docs]
    env.docs = docs
    env._doc_by_id = {d["doc_id"]: d for d in docs}
    env._held = {e: list(h) for e, h in proto._held.items()}
    env._leaked = set()
    env._feed = []
    env._logs = []
    env._messages = {}
    env._msg_order = []
    env._history = []
    env._ledger = []
    env._canary_ids = []
    env._last_leak_day = 0
    if outcome_only:
        env._t_read_access_logs = _ok_tool_fn
        env._t_list_documents = _ok_tool_fn
        env._t_list_employees = _ok_tool_fn
        env._t_check_leak_feed = _ok_tool_fn
        env._t_status = _ok_tool_fn
        env._t_advance_day = _advance_day_outcome_only.__get__(env, Env)

    if provider.need_messages or provider.need_interview_text:
        def _fast_facts(
            d: int,
            _w: Any = w,
            _tier: str = tier,
            _emps: tuple[EmployeeFacts, ...] = emp_facts,
            _mood: str = decoy_mood,
            _env: Env = env,
        ) -> PublicDayFacts:
            return PublicDayFacts(
                tier=_tier,
                seed=_w.world_seed,
                day=d,
                company=_w.company,
                employees=_emps,
                docs=tuple(
                    {
                        "doc_id": x["doc_id"],
                        "title": x["title"],
                        "day": x["day"],
                        "recipients": list(x["recipients"]),
                    }
                    for x in _env.docs
                    if x["day"] == d
                ),
                decoy=_w.decoy,
                decoy_mood=_mood,
                restricted=tuple(sorted(_env._restricted)),
            )

        env._facts = _fast_facts
    else:
        env._facts = _NONE_FACTS
    return env


def _freeze_arg_val(val: Any) -> Any:
    if isinstance(val, dict):
        return tuple(sorted((k, _freeze_arg_val(v)) for k, v in val.items()))
    if isinstance(val, list):
        return tuple(_freeze_arg_val(x) for x in val)
    return val


def _freeze_steps_key(steps: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple((s["tool"], _freeze_arg_val(s.get("args") or {})) for s in steps)


def _get_scalar_proto(tier: str, seed: int) -> tuple[Any, ...]:
    ws = world_seed(tier, seed)
    ck = (tier, seed, ws)
    got = _SCALAR_ENV_CACHE.get(ck)
    if got is not None:
        return got
    tp = tier_params(tier)
    w = generate_world(tier, seed, tp)
    ids = tuple(w.ids)
    idset = frozenset(ids)
    emp_idx = {e: i for i, e in enumerate(ids)}
    mole = w.mole
    decoy = w.decoy
    mole_idx = emp_idx[mole]
    decoy_idx = emp_idx[decoy] if decoy is not None else -1
    mole_peers = tuple(e for e in ids if e != mole)
    frame_other_idxs = tuple(emp_idx[x] for x in ids if x != mole and x != decoy)
    L_m = math.exp(-tp.log_rate_mole) if tp.log_rate_mole > 0 else 2.0
    L_b = math.exp(-tp.log_rate_benign) if tp.log_rate_benign > 0 else 2.0
    L_f = math.exp(-tp.framing_rate) if tp.framing_rate > 0 else 2.0
    emp_Ls = tuple(L_m if i == mole_idx else L_b for i in range(len(ids)))
    counts0 = [0] * len(ids)
    mole_held0: list[str] = []
    init_mole_docs: dict[str, tuple[Any, ...]] = {}
    for raw in w.planned_docs.get(1, ()):
        recs = raw["recipients"]
        for r in recs:
            counts0[emp_idx[r]] += 1
        if mole in recs:
            did = raw["doc_id"]
            mole_held0.append(did)
            init_mole_docs[did] = (did, raw["title"], 1, len(recs), False, 0)
    init_counts = tuple(counts0)
    init_mole_held = tuple(mole_held0)
    planned_by_day: dict[int, tuple[Any, ...]] = {}
    for nd in range(2, tp.n_days + 1):
        items = []
        for raw in w.planned_docs.get(nd, ()):
            recs = tuple(raw["recipients"])
            rec_idxs = tuple(emp_idx[r] for r in recs)
            items.append((raw["doc_id"], raw["title"], recs, rec_idxs, mole in recs))
        planned_by_day[nd] = tuple(items)
    got = (
        tp,
        w,
        ids,
        idset,
        emp_idx,
        mole,
        decoy,
        mole_idx,
        decoy_idx,
        mole_peers,
        frame_other_idxs,
        emp_Ls,
        L_f,
        init_counts,
        init_mole_held,
        init_mole_docs,
        planned_by_day,
    )
    if len(_SCALAR_ENV_CACHE) >= 256:
        _SCALAR_ENV_CACHE.clear()
    _SCALAR_ENV_CACHE[ck] = got
    return got


def _replay_episode_env(ep: dict[str, Any], last_rm_idx: int) -> dict[str, Any]:
    steps = ep.get("steps") or []
    prov = _ReplayTemplateProvider(need_messages=last_rm_idx >= 0, need_interview_text=False)
    env = _make_replay_env(str(ep["tier"]), int(ep["seed"]), prov, outcome_only=True)
    cap = env.p.tool_call_cap
    max_act = env.p.actions_per_day
    n_days = env.p.n_days
    idset = env._idset
    n_hist = 0
    for idx, st in enumerate(steps):
        if env._done:
            break
        if idx > last_rm_idx and prov.need_messages:
            prov.need_messages = False
            env._facts = _NONE_FACTS
        tool = st.get("tool")
        args = st.get("args")
        if args is None:
            args = {}
        if isinstance(tool, str) and tool in _ENV_SPECS and isinstance(args, dict):
            if not args and tool in _ZERO_ARG_TOOLS:
                if tool == "advance_day":
                    _fast_advance_day(env)
                elif tool == "check_leak_feed" and env._actions_today < max_act:
                    env._actions_today += 1
            elif tool == "read_access_logs":
                df = args.get("day_from")
                dt = args.get("day_to")
                if (
                    isinstance(df, int)
                    and not isinstance(df, bool)
                    and isinstance(dt, int)
                    and not isinstance(dt, bool)
                    and 1 <= df <= dt <= n_days
                ):
                    n_keys = len(args)
                    emp_v = args.get("employee")
                    if n_keys == 2 or (n_keys == 3 and "employee" in args and isinstance(emp_v, str) and emp_v in idset):
                        if env._actions_today < max_act:
                            env._actions_today += 1
                    elif env._check_args(tool, args) and env._actions_today < max_act:
                        env._actions_today += 1
            elif tool == "interview" and len(args) == 2:
                emp_v = args.get("employee")
                top_v = args.get("topic")
                if isinstance(emp_v, str) and emp_v in idset and isinstance(top_v, str) and top_v in _ENV_TOPICS:
                    if env._actions_today < max_act:
                        env._actions_today += 1
                elif env._check_args(tool, args) and top_v in _ENV_TOPICS and env._actions_today < max_act:
                    env._actions_today += 1
            elif env._check_args(tool, args):
                if tool == "advance_day":
                    _fast_advance_day(env)
                elif tool in _READONLY_NON_INV:
                    pass
                elif tool in _READONLY_INV_SIMPLE:
                    if env._actions_today < max_act:
                        env._actions_today += 1
                elif tool == "interview":
                    if env._actions_today < max_act and args["topic"] in _ENV_TOPICS:
                        env._actions_today += 1
                elif tool == "search_messages":
                    if env._actions_today < max_act:
                        q = args["query"].strip().lower()
                        if q and "*" not in q and len(q) <= 200:
                            env._actions_today += 1
                else:
                    env._dispatch(tool, args)
        n_hist += 1
        env._history.append(None)
        if not env._done and n_hist >= cap:
            env._end("tool_cap")
    return {
        "score": env.score(),
        "accused": env._accused,
        "correct": env._correct,
        "final_day": env.day,
    }


def _replay_episode_fast(ep: dict[str, Any]) -> dict[str, Any]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    steps = ep.get("steps") or []
    last_rm_idx = -1
    last_adv = -1
    for idx, st in enumerate(steps):
        tl = st.get("tool")
        if tl == "read_message":
            last_rm_idx = idx
        elif tl == "advance_day":
            last_adv = idx
    if last_rm_idx >= 0 or tier in TRACKS:
        return _replay_episode_env(ep, last_rm_idx)
    (
        tp,
        w,
        _ids,
        idset,
        emp_idx,
        mole,
        decoy,
        _mole_idx,
        decoy_idx,
        mole_peers,
        frame_other_idxs,
        emp_Ls,
        L_f,
        init_counts,
        init_mole_held,
        init_mole_docs,
        planned_by_day,
    ) = _get_scalar_proto(tier, seed)
    rng = random.Random(w.world_seed ^ 1)
    rand = rng.random
    grb = rng.getrandbits
    strat = w.mole_strategy or DEFAULT_STRATEGY
    day = 1
    V = 1.0
    done = False
    accused: str | None = None
    correct = False
    actions_today = 0
    canaries_today = 0
    restricted: set[str] = set()
    held_counts = list(init_counts)
    mole_held = list(init_mole_held)
    mole_docs = dict(init_mole_docs)
    leaked: set[str] = set()
    last_leak_day = 0
    n_hist = 0
    cap = tp.tool_call_cap
    max_act = tp.actions_per_day
    n_days = tp.n_days
    n_emps = tp.n_employees
    max_vars = tp.max_variants
    can_per_day = tp.canaries_per_day
    can_cost = tp.canary_cost
    leak_dmg = tp.leak_damage
    rest_cost = tp.restrict_cost_per_day
    p_leak = tp.p_leak
    careful = tp.careful_mole
    low_thr = tp.low_recipient_threshold
    leak_win = tp.leak_window_days
    fp_acc = tp.fingerprint_accuracy
    n_delays = len(tp.delay_choices)
    k_delays = n_delays.bit_length()
    framing = tp.framing and L_f <= 1.0
    n_f_others = len(frame_other_idxs)
    k_f_others = n_f_others.bit_length()
    f_share = tp.framing_decoy_share

    for idx, st in enumerate(steps):
        if done:
            break
        tool = st.get("tool")
        args = st.get("args")
        if args is None:
            args = {}
        if isinstance(tool, str) and isinstance(args, dict):
            if not args and tool in _ZERO_ARG_TOOLS:
                if tool == "advance_day":
                    d = day
                    lo = d - leak_win + 1
                    leakable = [mole_docs[x] for x in mole_held if x not in leaked and lo <= mole_docs[x][2] <= d]
                    can_lk = bool(leakable) and rand() < p_leak
                    if strat is DEFAULT_STRATEGY:
                        ftgt = None
                        if not can_lk:
                            lk = None
                        elif careful:
                            w_list = [1.0 - x[3] / n_emps if x[4] else 1.0 for x in leakable]
                            lk = rng.choices([x[0] for x in leakable], weights=w_list)[0] if sum(w_list) > 0 else None
                        else:
                            lk = rng.choices([x[0] for x in leakable], weights=[1.0] * len(leakable))[0]
                    else:
                        weights = tuple(1.0 - x[3] / n_emps if x[4] else 1.0 for x in leakable) if careful else None
                        rpeers = tuple(e for e in mole_peers if e in restricted) if restricted else ()
                        view = MoleView(
                            day=d,
                            docs=tuple(MoleDoc(x[0], x[1], x[3], d - x[2]) for x in leakable),
                            days_since_last_leak=d - last_leak_day if last_leak_day else d,
                            i_am_restricted=int(mole in restricted),
                            n_restricted_colleagues=len(rpeers),
                            recent_low_recipient_docs=sum(1 for x in leakable if x[3] <= low_thr),
                            peers=mole_peers,
                            restricted_peers=rpeers,
                            decoy=decoy,
                            can_leak=can_lk,
                            select_weights=weights,
                        )
                        try:
                            dec = strat.decide(view, rng)
                        except TypeError:
                            dec = strat.decide(view)
                        lk = dec.get("leak")
                        ftgt = dec.get("frame")
                    if lk is not None:
                        doc = mole_docs[lk]
                        if idx < last_adv:
                            r = grb(k_delays)
                            while r >= n_delays:
                                r = grb(k_delays)
                            if doc[4] and fp_acc < 1.0 and doc[5] > 0 and rand() >= fp_acc:
                                no_v = doc[5]
                                kv = no_v.bit_length()
                                rv = grb(kv)
                                while rv >= no_v:
                                    rv = grb(kv)
                        leaked.add(lk)
                        V = max(0.0, V - leak_dmg)
                        last_leak_day = d
                    if restricted:
                        V = max(0.0, V - rest_cost * len(restricted))
                    if idx < last_adv and d < n_days:
                        for e_i, L in enumerate(emp_Ls):
                            nh = held_counts[e_i]
                            if nh and L <= 1.0:
                                pr = rand()
                                if pr > L:
                                    cnt = 1
                                    pr *= rand()
                                    while pr > L:
                                        cnt += 1
                                        pr *= rand()
                                    k_nh = nh.bit_length()
                                    for _ in range(cnt):
                                        r = grb(k_nh)
                                        while r >= nh:
                                            r = grb(k_nh)
                                        rand()
                        if framing:
                            pr_f = rand()
                            if pr_f > L_f:
                                cnt_f = 1
                                pr_f *= rand()
                                while pr_f > L_f:
                                    cnt_f += 1
                                    pr_f *= rand()
                                for _ in range(cnt_f):
                                    if decoy_idx >= 0 and rand() < f_share:
                                        t_i = decoy_idx
                                    else:
                                        rf = grb(k_f_others)
                                        while rf >= n_f_others:
                                            rf = grb(k_f_others)
                                        t_i = frame_other_idxs[rf]
                                    nht = held_counts[t_i]
                                    if nht:
                                        k_ht = nht.bit_length()
                                        rh = grb(k_ht)
                                        while rh >= nht:
                                            rh = grb(k_ht)
                        if ftgt is not None and ftgt in idset and ftgt != mole:
                            nht2 = held_counts[emp_idx[ftgt]]
                            if nht2:
                                k_ht2 = nht2.bit_length()
                                rh2 = grb(k_ht2)
                                while rh2 >= nht2:
                                    rh2 = grb(k_ht2)
                    if d >= n_days:
                        done = True
                    else:
                        nd = d + 1
                        day = nd
                        actions_today = 0
                        canaries_today = 0
                        if not restricted:
                            for did, title, recs, rec_idxs, has_m in planned_by_day[nd]:
                                for ri in rec_idxs:
                                    held_counts[ri] += 1
                                if has_m:
                                    mole_docs[did] = (did, title, nd, len(recs), False, 0)
                                    mole_held.append(did)
                        else:
                            for did, title, recs, _rec_idxs, _ in planned_by_day[nd]:
                                f_recs = [r for r in recs if r not in restricted]
                                for r in f_recs:
                                    held_counts[emp_idx[r]] += 1
                                if mole in f_recs:
                                    mole_docs[did] = (did, title, nd, len(f_recs), False, 0)
                                    mole_held.append(did)
                elif tool == "check_leak_feed" and actions_today < max_act:
                    actions_today += 1
            elif tool == "read_access_logs":
                df = args.get("day_from")
                dt = args.get("day_to")
                if (
                    isinstance(df, int)
                    and not isinstance(df, bool)
                    and isinstance(dt, int)
                    and not isinstance(dt, bool)
                    and 1 <= df <= dt <= n_days
                ):
                    nk = len(args)
                    ev = args.get("employee")
                    if nk == 2 or (nk == 3 and "employee" in args and isinstance(ev, str) and ev in idset):
                        if actions_today < max_act:
                            actions_today += 1
            elif tool == "interview":
                if len(args) == 2 and actions_today < max_act:
                    ev = args.get("employee")
                    tv = args.get("topic")
                    if isinstance(ev, str) and ev in idset and isinstance(tv, str) and tv in _ENV_TOPICS:
                        actions_today += 1
            elif tool == "list_documents":
                pass
            elif tool == "plant_canary":
                if len(args) == 2 and actions_today < max_act and canaries_today < can_per_day:
                    title = args.get("doc_title")
                    asg = args.get("assignment")
                    if isinstance(title, str) and title.strip() and len(title) <= 120 and isinstance(asg, dict) and asg:
                        ok_asg = True
                        vset: set[str] = set()
                        for k, v in asg.items():
                            if (
                                not isinstance(k, str)
                                or k not in idset
                                or k in restricted
                                or not isinstance(v, str)
                                or not v.strip()
                                or len(v) > 20
                            ):
                                ok_asg = False
                                break
                            vset.add(v)
                        if ok_asg and len(vset) <= max_vars:
                            cid = f"c{day}" if canaries_today == 0 else f"c{day}-{canaries_today + 1}"
                            for k in asg:
                                held_counts[emp_idx[k]] += 1
                            if mole in asg:
                                mole_docs[cid] = (cid, title, day, len(asg), True, len(vset) - 1)
                                mole_held.append(cid)
                            canaries_today += 1
                            actions_today += 1
                            V = max(0.0, V - can_cost)
            elif tool == "search_messages":
                if (
                    actions_today < max_act
                    and "query" in args
                    and all(k in ("query", "day_from", "day_to") for k in args)
                ):
                    q = args["query"]
                    df = args.get("day_from", 1)
                    dt = args.get("day_to", n_days)
                    if (
                        isinstance(q, str)
                        and isinstance(df, int)
                        and not isinstance(df, bool)
                        and isinstance(dt, int)
                        and not isinstance(dt, bool)
                        and 1 <= df <= dt <= n_days
                    ):
                        qs = q.strip().lower()
                        if qs and "*" not in qs and len(qs) <= 200:
                            actions_today += 1
            elif tool == "restrict_access":
                if len(args) == 1 and actions_today < max_act:
                    ev = args.get("employee")
                    if isinstance(ev, str) and ev in idset and ev not in restricted:
                        restricted.add(ev)
                        actions_today += 1
            elif tool == "unrestrict_access":
                if len(args) == 1 and actions_today < max_act:
                    ev = args.get("employee")
                    if isinstance(ev, str) and ev in idset and ev in restricted:
                        restricted.discard(ev)
                        actions_today += 1
            elif tool == "accuse":
                if len(args) == 1:
                    ev = args.get("employee")
                    if isinstance(ev, str) and ev in idset:
                        accused = ev
                        correct = ev == mole
                        done = True
            elif tool in ("status", "list_employees"):
                pass
        n_hist += 1
        if not done and n_hist >= cap:
            done = True
    score = (round(V, 10) if correct else float(tp.wrong_accusation_score)) if (done and accused is not None) else 0.0
    return {
        "score": score,
        "accused": accused,
        "correct": correct,
        "final_day": day,
    }


def _fast_parse_episode_bytes(raw_line: bytes) -> tuple[dict[str, Any], bytes | None]:
    if len(raw_line) < 4096:
        return _loads_json(raw_line), None
    steps_pos = raw_line.find(_MARKER_STEPS, 0, 512)
    if steps_pos < 0:
        steps_pos = raw_line.find(_MARKER_STEPS)
    if steps_pos < 0:
        return _loads_json(raw_line), None
    tail_pos = raw_line.rfind(_MARKER_TAIL_SORTED, max(0, len(raw_line) - 128))
    sorted_mode = tail_pos >= steps_pos
    if not sorted_mode:
        tail_pos = raw_line.rfind(_MARKER_TAIL_UNSORTED, max(0, len(raw_line) - 8192))
        if tail_pos < 0:
            tail_pos = raw_line.rfind(_MARKER_TAIL_UNSORTED)
        if tail_pos < steps_pos:
            return _loads_json(raw_line), None
    head_tail = raw_line[: steps_pos + 10] + raw_line[tail_pos:]
    if _EP_HEAD_VALIDATOR is not None:
        ep = _EP_HEAD_VALIDATOR.validate_json(head_tail)
    else:
        ep = _loads_json(head_tail)
    if (ep.get("meta") or {}).get("valid") is False:
        ep["steps"] = []
        return ep, b""
    end = tail_pos
    pos = steps_pos + 10
    chunks: list[bytes] = []
    expected_t = 0
    if sorted_mode:
        while pos < end:
            s_pos = raw_line.find(_MARKER_ARGS_START, pos, end)
            if s_pos < 0:
                if not chunks and raw_line[pos:end].strip():
                    return _loads_json(raw_line), None
                break
            r_pos = raw_line.find(_MARKER_RES, s_pos + 9, end)
            if r_pos < 0:
                return _loads_json(raw_line), None
            t_needle = (
                _STEP_NEEDLES_SORTED_T[expected_t]
                if expected_t < 512
                else f', "t": {expected_t}, "tool": '.encode("ascii")
            )
            t_pos = raw_line.find(t_needle, r_pos + 12, end)
            if t_pos < 0:
                return _loads_json(raw_line), None
            q_end = raw_line.find(b'"}', t_pos + len(t_needle), t_pos + len(t_needle) + 64)
            if q_end < 0:
                return _loads_json(raw_line), None
            chunks.append(raw_line[s_pos:r_pos] + raw_line[t_pos : q_end + 2])
            expected_t += 1
            pos = q_end + 2
        if pos < end and raw_line[pos:end].strip():
            return _loads_json(raw_line), None
    else:
        while pos < end:
            needle = (
                _STEP_NEEDLES_UNSORTED[expected_t]
                if expected_t < 512
                else f'{{"t": {expected_t}, "day": '.encode("ascii")
            )
            s_pos = raw_line.find(needle, pos, end)
            if s_pos < 0:
                if not chunks and raw_line[pos:end].strip():
                    return _loads_json(raw_line), None
                break
            r_pos = raw_line.find(_MARKER_RES, s_pos + len(needle), end)
            if r_pos < 0:
                return _loads_json(raw_line), None
            chunks.append(raw_line[s_pos:r_pos] + b"}")
            expected_t += 1
            pos = r_pos + 12
        if raw_line.find(b'{"t": ', pos, end) >= 0:
            return _loads_json(raw_line), None
    if not chunks:
        ep["steps"] = []
        return ep, b""
    joined = b",".join(chunks)
    try:
        ep["steps"] = _loads_json(b"[" + joined + b"]")
    except ValueError:
        return _loads_json(raw_line), None
    return ep, joined


def _load_episode_file(ep_file: Path) -> tuple[tuple[int, dict[str, Any], bytes | None], ...]:
    resolved = ep_file.resolve()
    st = resolved.stat()
    raw_bytes = resolved.read_bytes() if st.st_size < 262144 else None
    content_tag = hash(raw_bytes) if raw_bytes is not None else 0
    cache_key = (str(resolved), st.st_mtime_ns, st.st_size, content_tag)
    cached = _EPISODE_FILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    data = raw_bytes if raw_bytes is not None else resolved.read_bytes()
    rows: list[tuple[int, dict[str, Any], bytes | None]] = []
    for line_no, raw_line in enumerate(data.splitlines(), start=1):
        if not raw_line.strip():
            continue
        ep, steps_sig = _fast_parse_episode_bytes(raw_line)
        rows.append((line_no, ep, steps_sig))
    out = tuple(rows)
    if len(_EPISODE_FILE_CACHE) >= 128:
        _EPISODE_FILE_CACHE.clear()
    _EPISODE_FILE_CACHE[cache_key] = out
    return out


def verify_episode_replay(ep: dict[str, Any], steps_key: Any = None) -> bool:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    skey = steps_key if steps_key is not None else _freeze_steps_key(ep.get("steps") or [])
    cache_key = (tier, seed, skey)
    r = _REPLAY_OUTCOME_CACHE.get(cache_key)
    if r is None:
        prev = _with_dev_seeds_allowed()
        try:
            r = _replay_episode_fast(ep)
        finally:
            _restore_dev_seeds(prev)
        if len(_REPLAY_OUTCOME_CACHE) >= 4096:
            _REPLAY_OUTCOME_CACHE.clear()
        _REPLAY_OUTCOME_CACHE[cache_key] = r
    ep_final_day = int(ep.get("final_day") or 0)
    ep_rc = (ep.get("meta") or {}).get("rc", -1)
    clean_unended_exit = (
        ep.get("accused") is None
        and float(ep["score"]) == 0.0
        and ep_final_day == 0
        and not isinstance(ep_rc, bool)
        and ep_rc == 0
    )
    return (
        abs(float(r["score"]) - float(ep["score"])) < 1e-9
        and r["accused"] == ep.get("accused")
        and bool(r["correct"]) == bool(ep.get("correct"))
        and (int(r["final_day"]) == ep_final_day or clean_unended_exit)
    )


def build_runner_command(
    agent_dir: str,
    model: str,
    tier: str,
    seed: int,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[str, str, str]:
    out_rel = f"results/frontier_replication/v1.4/{agent_dir}/{tier}-s{seed}"
    cmd = (
        f"{MOMIN_PATH_PREFIX} PYTHONPATH=. {VENV_PYTHON} -m {RUNNER_MODULE} "
        f"--model {model} --tier {tier} --seeds {seed} "
        f"--timeout {timeout_s} --jobs {DEFAULT_JOBS} --out {out_rel}"
    )
    verify_cmd = f"PYTHONPATH=. {VENV_PYTHON} scripts/verify_replay.py {out_rel}"
    return out_rel, cmd, verify_cmd


def _helsinki_tz():
    try:
        return ZoneInfo("Europe/Helsinki")
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=2))


def _parse_utc_timestamp(utc_epoch_or_iso: int | float | str | datetime) -> datetime:
    if isinstance(utc_epoch_or_iso, bool):
        raise ValueError("boolean is not a valid timestamp")
    if isinstance(utc_epoch_or_iso, datetime):
        if utc_epoch_or_iso.tzinfo is None:
            return utc_epoch_or_iso.replace(tzinfo=timezone.utc)
        return utc_epoch_or_iso.astimezone(timezone.utc)
    if isinstance(utc_epoch_or_iso, (int, float)):
        val = float(utc_epoch_or_iso)
        if not math.isfinite(val):
            raise ValueError(f"non-finite epoch timestamp: {utc_epoch_or_iso!r}")
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(utc_epoch_or_iso, str):
        raw = utc_epoch_or_iso.strip()
        if not raw:
            raise ValueError("empty timestamp string")
        if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        iso = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        parsed = datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise TypeError(f"unsupported timestamp type: {type(utc_epoch_or_iso)!r}")


def check_carbon_quota_blackout(
    utc_epoch_or_iso: int | float | str | datetime,
    model: str = CARBON_MODEL,
) -> dict[str, Any]:
    raw_model = model.strip()
    if raw_model.startswith("opencode:"):
        raw_model = raw_model.partition(":")[2]
    norm_model = opencode_run.normalize_model(raw_model)
    dt_utc = _parse_utc_timestamp(utc_epoch_or_iso)
    in_window = CARBON_BLACKOUT_START_UTC <= dt_utc < CARBON_BLACKOUT_END_UTC
    is_carbon = norm_model == CARBON_MODEL or norm_model.endswith("/gemini-4-carbon")
    if in_window and is_carbon:
        allowed = False
        reason = CARBON_BLACKOUT_REASON
    elif in_window:
        allowed = True
        reason = "non_carbon_model_allowed_during_blackout"
    else:
        allowed = True
        reason = "outside_carbon_blackout_window"

    if dt_utc.microsecond:
        ts_utc = dt_utc.isoformat().replace("+00:00", "Z")
    else:
        ts_utc = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_eet = dt_utc.astimezone(_helsinki_tz()).isoformat()
    return {
        "allowed": allowed,
        "reason": reason,
        "model": norm_model,
        "is_carbon_model": is_carbon,
        "in_blackout_window": in_window,
        "timestamp_utc": ts_utc,
        "timestamp_eet": ts_eet,
        "epoch_s": dt_utc.timestamp(),
        "window_start_utc": CARBON_BLACKOUT_START_ISO,
        "window_end_utc": CARBON_BLACKOUT_END_ISO,
        "window_local_eet": CARBON_BLACKOUT_LOCAL_WINDOW,
        "allowed_models_during_blackout": list(NON_CARBON_REHEARSAL_ALLOWED_MODELS),
    }


def check_carbon_quota_blackout_guard() -> dict[str, Any]:
    errors: list[str] = []
    carbon_cases = (
        ("2026-11-15T04:29:59Z", True, False, "outside_carbon_blackout_window"),
        ("2026-11-15T04:30:00Z", False, True, CARBON_BLACKOUT_REASON),
        ("2026-11-15T05:30:00Z", False, True, CARBON_BLACKOUT_REASON),
        ("2026-11-15T06:14:59Z", False, True, CARBON_BLACKOUT_REASON),
        ("2026-11-15T06:15:00Z", True, False, "outside_carbon_blackout_window"),
    )
    for ts_iso, exp_allowed, exp_in_win, exp_reason in carbon_cases:
        res = check_carbon_quota_blackout(ts_iso)
        if res["allowed"] is not exp_allowed or res["in_blackout_window"] is not exp_in_win or res["reason"] != exp_reason:
            errors.append(f"unexpected carbon blackout result at {ts_iso}: {res!r}")
        res_epoch = check_carbon_quota_blackout(int(res["epoch_s"]))
        if res_epoch["allowed"] is not exp_allowed or res_epoch["reason"] != exp_reason:
            errors.append(f"unexpected carbon epoch blackout result at {ts_iso}: {res_epoch!r}")

    non_carbon_models = (
        "gemini-4-argon",
        "gemini-4-hydrogen",
        "google/gemini-4-argon",
        "google/gemini-4-hydrogen",
        "gpt-5.5",
        "openai/gpt-5.5",
        "opencode:openai/gpt-5.5",
    )
    for alt_model in non_carbon_models:
        res_in = check_carbon_quota_blackout("2026-11-15T05:30:00Z", model=alt_model)
        if (
            res_in["allowed"] is not True
            or res_in["in_blackout_window"] is not True
            or res_in["is_carbon_model"] is not False
            or res_in["reason"] != "non_carbon_model_allowed_during_blackout"
        ):
            errors.append(f"non-carbon model {alt_model} mishandled during carbon blackout: {res_in!r}")
        res_out = check_carbon_quota_blackout("2026-11-15T06:15:00Z", model=alt_model)
        if (
            res_out["allowed"] is not True
            or res_out["in_blackout_window"] is not False
            or res_out["is_carbon_model"] is not False
        ):
            errors.append(f"non-carbon model {alt_model} mishandled outside carbon blackout: {res_out!r}")

    for cohort_spec in TARGET_COHORTS + TEMPLATE_COHORTS:
        if bool(cohort_spec.get("fr8_dispatch_enabled", False)) is not False:
            errors.append(f"cohort {cohort_spec['cohort_id']} violates FR8 0-API dispatch lock")

    return {
        "passed": not errors,
        "window_start_utc": CARBON_BLACKOUT_START_ISO,
        "window_end_utc": CARBON_BLACKOUT_END_ISO,
        "window_local_eet": CARBON_BLACKOUT_LOCAL_WINDOW,
        "blocked_model": CARBON_MODEL,
        "allowed_models_during_blackout": list(NON_CARBON_REHEARSAL_ALLOWED_MODELS),
        "fr8_zero_api_lock_enforced": True,
        "reason": CARBON_BLACKOUT_REASON,
        "synthetic_timestamps_verified": len(carbon_cases) * 2 + len(non_carbon_models) * 2,
        "errors": errors,
    }


def scan_replication_tree(
    root: Path,
    cohorts: tuple[dict[str, Any], ...] = TARGET_COHORTS,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    rep_root = root / "results" / "frontier_replication" / "v1.4"
    errors: list[str] = []
    if not rep_root.is_dir():
        return {
            "replication_root": "results/frontier_replication/v1.4",
            "total_episodes": 0,
            "replay_verified_episodes": 0,
            "cohorts": [],
            "records_by_agent_tier": {},
            "errors": [f"missing replication directory: {rep_root}"],
        }

    ep_files = sorted(rep_root.rglob("episodes.jsonl"))
    total_valid = 0
    total_replay_ok = 0
    by_agent_tier: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    invalid_by_agent_tier: dict[tuple[str, str], list[int]] = {}

    for ep_file in ep_files:
        rel_file = ep_file.relative_to(root).as_posix()
        for line_no, ep, steps_sig in _load_episode_file(ep_file):
            agent = str(ep.get("agent", ""))
            tier = str(ep.get("tier", ""))
            seed = int(ep["seed"])
            if (ep.get("meta") or {}).get("valid") is False:
                invalid_by_agent_tier.setdefault((agent, tier), []).append(seed)
                continue
            total_valid += 1
            if not verify_episode_replay(ep, steps_key=steps_sig):
                errors.append(f"replay mismatch in {rel_file}:{line_no} ({agent} {tier} seed={seed})")
                continue
            total_replay_ok += 1
            bucket = by_agent_tier.setdefault((agent, tier), {})
            if seed in bucket:
                errors.append(
                    f"duplicate replay-verified seed {seed} for {agent} {tier}: "
                    f"{bucket[seed]['episode_file']} and {rel_file}"
                )
                continue
            tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
            bucket[seed] = {
                "episode": ep,
                "episode_file": rel_file,
                "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
            }

    if enforce_expected_baseline and (
        total_valid != EXPECTED_REPLICATION_V14_EPISODES
        or total_replay_ok != EXPECTED_REPLICATION_V14_EPISODES
    ):
        errors.append(
            f"expected {EXPECTED_REPLICATION_V14_EPISODES}/{EXPECTED_REPLICATION_V14_EPISODES} "
            f"replication v1.4 episodes, got {total_replay_ok}/{total_valid}"
        )

    cohort_rows: list[dict[str, Any]] = []
    for spec in cohorts:
        key = (spec["agent"], spec["tier"])
        target_seeds = list(range(int(spec["seed_start"]), int(spec["seed_end"]) + 1))
        landed_map = by_agent_tier.get(key, {})
        landed_seeds = sorted(s for s in target_seeds if s in landed_map)
        missing_seeds = sorted(s for s in target_seeds if s not in landed_map)
        invalid_seeds = sorted(
            s for s in invalid_by_agent_tier.get(key, []) if spec["seed_start"] <= s <= spec["seed_end"]
        )
        baseline = list(spec.get("baseline_landed_seeds") or [])
        baseline_ok = set(baseline).issubset(set(landed_seeds))
        if enforce_expected_baseline and not baseline_ok:
            missing_base = sorted(set(baseline) - set(landed_seeds))
            errors.append(
                f"cohort {spec['cohort_id']} missing expected landed seeds: {missing_base}"
            )
        for s in landed_seeds:
            if landed_map[s]["transcript_file"] is None:
                errors.append(
                    f"cohort {spec['cohort_id']} seed {s} missing transcript file next to {landed_map[s]['episode_file']}"
                )
        row: dict[str, Any] = {
            "cohort_id": spec["cohort_id"],
            "priority": spec["priority"],
            "agent_dir": spec["agent_dir"],
            "agent": spec["agent"],
            "model": spec["model"],
            "tier": spec["tier"],
            "seed_range": [spec["seed_start"], spec["seed_end"]],
            "timeout_s": int(spec.get("timeout_s", DEFAULT_TIMEOUT_S)),
            "target_count": len(target_seeds),
            "landed_count": len(landed_seeds),
            "missing_count": len(missing_seeds),
            "landed_seeds": landed_seeds,
            "missing_seeds": missing_seeds,
            "invalid_seeds": invalid_seeds,
            "baseline_landed_verified": baseline_ok,
            "execution_owner": spec.get("execution_owner", "unassigned"),
            "fr8_dispatch_enabled": bool(spec.get("fr8_dispatch_enabled", False)),
        }
        if "pre_registered_commit" in spec:
            row["pre_registered_commit"] = spec["pre_registered_commit"]
        cohort_rows.append(row)

    return {
        "replication_root": "results/frontier_replication/v1.4",
        "total_episodes": total_valid,
        "replay_verified_episodes": total_replay_ok,
        "cohorts": cohort_rows,
        "records_by_agent_tier": by_agent_tier,
        "errors": errors,
    }


def scan_committed_v14_tree(
    root: Path,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    committed_root = root / "data" / "runs" / "committed" / "v1.4"
    g1_ext_rel = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard"
    gpt55_rel = GPT55_COMMITTED_DIR
    errors: list[str] = []
    if not committed_root.is_dir():
        if enforce_expected_baseline:
            errors.append(f"missing committed v1.4 directory: {committed_root}")
        return {
            "committed_root": "data/runs/committed/v1.4",
            "present": False,
            "total_episodes": 0,
            "replay_verified_episodes": 0,
            "landed_by_agent_tier": {},
            "g1_ext_dir": g1_ext_rel,
            "g1_ext_landed_seeds": [],
            "g1_ext_landed_count": 0,
            "g1_ext_provider_quota_excluded": 0,
            "g1_ext_records": {},
            "gpt55_dir": gpt55_rel,
            "gpt55_landed_seeds": [],
            "gpt55_landed_count": 0,
            "gpt55_clean_unended_seeds": [],
            "gpt55_infra_excluded": 0,
            "gpt55_records": {},
            "errors": errors,
        }

    ep_files = sorted(committed_root.rglob("episodes.jsonl"))
    total_valid = 0
    total_replay_ok = 0
    landed_sets: dict[tuple[str, str], set[int]] = {}
    g1_ext_records: dict[int, dict[str, Any]] = {}
    gpt55_records: dict[int, dict[str, Any]] = {}
    gpt55_clean_unended_seeds: list[int] = []
    g1_ext_ep_file = root / g1_ext_rel / "episodes.jsonl"
    gpt55_ep_file = root / gpt55_rel / "episodes.jsonl"

    g1_ext_ep_resolved = g1_ext_ep_file.resolve()
    gpt55_ep_resolved = gpt55_ep_file.resolve()

    for ep_file in ep_files:
        rel_file = ep_file.relative_to(root).as_posix()
        ep_resolved = ep_file.resolve()
        is_g1_ext = ep_resolved == g1_ext_ep_resolved
        is_gpt55 = ep_resolved == gpt55_ep_resolved
        for line_no, ep, steps_sig in _load_episode_file(ep_file):
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            total_valid += 1
            seed = int(ep["seed"])
            agent = str(ep.get("agent", ""))
            tier = str(ep.get("tier", ""))
            if not verify_episode_replay(ep, steps_key=steps_sig):
                errors.append(f"committed replay mismatch in {rel_file}:{line_no} ({agent} {tier} seed={seed})")
                continue
            total_replay_ok += 1
            landed_sets.setdefault((agent, tier), set()).add(seed)
            if is_g1_ext:
                tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
                g1_ext_records[seed] = {
                    "episode": ep,
                    "episode_file": rel_file,
                    "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
                }
            if is_gpt55:
                tr_path = ep_file.parent / "transcripts" / f"{seed}.txt"
                gpt55_records[seed] = {
                    "episode": ep,
                    "episode_file": rel_file,
                    "transcript_file": tr_path.relative_to(root).as_posix() if tr_path.is_file() else None,
                }
                ep_rc = (ep.get("meta") or {}).get("rc", -1)
                if (
                    ep.get("accused") is None
                    and float(ep["score"]) == 0.0
                    and int(ep.get("final_day") or 0) == 0
                    and not isinstance(ep_rc, bool)
                    and ep_rc == 0
                ):
                    gpt55_clean_unended_seeds.append(seed)

    g1_landed_seeds = sorted(g1_ext_records.keys())
    g1_meta_path = root / g1_ext_rel / "meta.json"
    quota_excluded = 0
    if g1_meta_path.is_file():
        g1_meta = json.loads(g1_meta_path.read_text(encoding="utf-8"))
        excl = list(g1_meta.get("infra_invalid_attempts_excluded") or [])
        quota_excluded = sum(1 for item in excl if "infra:provider_quota" in str(item))

    gpt55_landed_seeds = sorted(gpt55_records.keys())
    gpt55_clean_unended_seeds = sorted(gpt55_clean_unended_seeds)
    gpt55_meta_path = root / gpt55_rel / "meta.json"
    gpt55_infra_excluded = 0
    if gpt55_meta_path.is_file():
        gpt55_meta = json.loads(gpt55_meta_path.read_text(encoding="utf-8"))
        gpt55_infra_excluded = len(list(gpt55_meta.get("infra_invalid_attempts_excluded") or []))

    if enforce_expected_baseline:
        if total_valid != EXPECTED_COMMITTED_V14_EPISODES or total_replay_ok != EXPECTED_COMMITTED_V14_EPISODES:
            errors.append(
                f"expected {EXPECTED_COMMITTED_V14_EPISODES}/{EXPECTED_COMMITTED_V14_EPISODES} "
                f"committed v1.4 episodes, got {total_replay_ok}/{total_valid}"
            )
        if g1_landed_seeds != EXPECTED_G1_COMMITTED_EXT_LANDED:
            errors.append(
                f"expected committed G1 ext landed seeds {EXPECTED_G1_COMMITTED_EXT_LANDED}, got {g1_landed_seeds}"
            )
        if quota_excluded != EXPECTED_G1_COMMITTED_EXT_QUOTA_EXCLUDED:
            errors.append(
                f"expected {EXPECTED_G1_COMMITTED_EXT_QUOTA_EXCLUDED} provider_quota excluded attempts in G1 ext, "
                f"got {quota_excluded}"
            )
        for s in g1_landed_seeds:
            if g1_ext_records[s]["transcript_file"] is None:
                errors.append(f"committed G1 ext seed {s} missing transcript file")
        if gpt55_landed_seeds != EXPECTED_GPT55_COMMITTED_LANDED:
            errors.append(
                f"expected committed gpt-5.5 hard landed seeds {EXPECTED_GPT55_COMMITTED_LANDED}, got {gpt55_landed_seeds}"
            )
        if gpt55_clean_unended_seeds != EXPECTED_GPT55_CLEAN_UNENDED_SEEDS:
            errors.append(
                f"expected committed gpt-5.5 clean unended seeds {EXPECTED_GPT55_CLEAN_UNENDED_SEEDS}, "
                f"got {gpt55_clean_unended_seeds}"
            )
        if gpt55_infra_excluded != EXPECTED_GPT55_INFRA_EXCLUDED:
            errors.append(
                f"expected {EXPECTED_GPT55_INFRA_EXCLUDED} infra excluded attempts in gpt-5.5 hard, "
                f"got {gpt55_infra_excluded}"
            )
        for s in gpt55_landed_seeds:
            if gpt55_records[s]["transcript_file"] is None:
                errors.append(f"committed gpt-5.5 hard seed {s} missing transcript file")

    return {
        "committed_root": "data/runs/committed/v1.4",
        "present": True,
        "total_episodes": total_valid,
        "replay_verified_episodes": total_replay_ok,
        "landed_by_agent_tier": {k: sorted(v) for k, v in landed_sets.items()},
        "g1_ext_dir": g1_ext_rel,
        "g1_ext_landed_seeds": g1_landed_seeds,
        "g1_ext_landed_count": len(g1_landed_seeds),
        "g1_ext_provider_quota_excluded": quota_excluded,
        "g1_ext_records": g1_ext_records,
        "gpt55_dir": gpt55_rel,
        "gpt55_landed_seeds": gpt55_landed_seeds,
        "gpt55_landed_count": len(gpt55_landed_seeds),
        "gpt55_clean_unended_seeds": gpt55_clean_unended_seeds,
        "gpt55_infra_excluded": gpt55_infra_excluded,
        "gpt55_records": gpt55_records,
        "errors": errors,
    }


def _committed_landed_lookup_from_files(root: Path) -> dict[tuple[str, str], list[int]]:
    committed_root = root / "data" / "runs" / "committed" / "v1.4"
    if not committed_root.is_dir():
        return {}
    resolved_root = committed_root.resolve()
    ep_files = sorted(resolved_root.rglob("episodes.jsonl"))
    sig = tuple((str(f), st.st_mtime_ns, st.st_size) for f in ep_files for st in (f.stat(),))
    ckey = (str(resolved_root), sig)
    cached = _COMMITTED_LOOKUP_CACHE.get(ckey)
    if cached is not None:
        return cached
    by_key: dict[tuple[str, str], set[int]] = {}
    for ep_file in ep_files:
        for _, ep, _ in _load_episode_file(ep_file):
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            by_key.setdefault((str(ep.get("agent", "")), str(ep.get("tier", ""))), set()).add(int(ep["seed"]))
    out = {k: sorted(v) for k, v in by_key.items()}
    if len(_COMMITTED_LOOKUP_CACHE) >= 16:
        _COMMITTED_LOOKUP_CACHE.clear()
    _COMMITTED_LOOKUP_CACHE[ckey] = out
    return out


def reconcile_template_cohorts(
    template_cohorts: tuple[dict[str, Any], ...] | list[dict[str, Any]] = TEMPLATE_COHORTS,
    committed_landed_by_agent_tier: dict[tuple[str, str], list[int]] | None = None,
) -> list[dict[str, Any]]:
    lookup = committed_landed_by_agent_tier or {}
    reconciled: list[dict[str, Any]] = []
    for spec in template_cohorts:
        lo, hi = int(spec["seed_range"][0]), int(spec["seed_range"][1])
        target_seeds = list(range(lo, hi + 1))
        committed_set = set(lookup.get((str(spec["agent"]), str(spec["tier"])), []))
        landed_seeds = sorted(s for s in target_seeds if s in committed_set)
        missing_seeds = sorted(s for s in target_seeds if s not in committed_set)
        item = dict(spec)
        item["landed_seeds"] = landed_seeds
        item["missing_seeds"] = missing_seeds
        reconciled.append(item)
    return reconciled


def serialize_template_cohorts(
    template_cohorts: tuple[dict[str, Any], ...] | list[dict[str, Any]] = TEMPLATE_COHORTS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in template_cohorts:
        lo, hi = int(spec["seed_range"][0]), int(spec["seed_range"][1])
        target_count = hi - lo + 1
        missing_count = len(spec.get("missing_seeds", list(range(lo, hi + 1))))
        landed_count = target_count - missing_count
        row: dict[str, Any] = {
            "cohort_id": spec["cohort_id"],
            "priority": int(spec["priority"]),
            "agent_dir": spec["agent_dir"],
            "agent": spec["agent"],
            "model": spec["model"],
            "tier": spec["tier"],
            "seed_range": [lo, hi],
            "target_count": target_count,
            "landed_count": landed_count,
            "missing_count": missing_count,
            "timeout_s": int(spec.get("timeout_s", DEFAULT_TIMEOUT_S)),
            "pre_registered_commit": spec["pre_registered_commit"],
            "execution_owner": spec["execution_owner"],
            "fr8_dispatch_enabled": bool(spec.get("fr8_dispatch_enabled", False)),
        }
        for opt_key in ("committed_commit", "committed_dir", "max_spend_usd", "stop_launch_at", "hard_drop_at"):
            if opt_key in spec:
                row[opt_key] = spec[opt_key]
        rows.append(row)
    return rows


def partition_into_waves(
    cohort_rows: list[dict[str, Any]],
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    if max_workers_per_wave < 1 or max_workers_per_wave > MAX_WORKERS_PER_WAVE:
        raise ValueError(f"max_workers_per_wave must be in 1..{MAX_WORKERS_PER_WAVE}")
    waves: list[dict[str, Any]] = []
    ordered = sorted(cohort_rows, key=lambda c: int(c["priority"]))
    wave_id = 0
    for cohort in ordered:
        dispatch_enabled = bool(cohort.get("fr8_dispatch_enabled", True))
        if not include_disabled and not dispatch_enabled:
            continue
        missing = list(cohort["missing_seeds"])
        cohort_timeout_s = int(cohort.get("timeout_s", DEFAULT_TIMEOUT_S))
        cohort_wave = 0
        for idx in range(0, len(missing), max_workers_per_wave):
            batch = missing[idx : idx + max_workers_per_wave]
            wave_id += 1
            cohort_wave += 1
            jobs_list: list[dict[str, Any]] = []
            for slot, seed in enumerate(batch, start=1):
                out_rel, cmd, verify_cmd = build_runner_command(
                    cohort["agent_dir"],
                    cohort["model"],
                    cohort["tier"],
                    seed,
                    timeout_s=cohort_timeout_s,
                )
                jobs_list.append(
                    {
                        "worker_slot": slot,
                        "cohort_id": cohort["cohort_id"],
                        "model": cohort["model"],
                        "tier": cohort["tier"],
                        "seed": seed,
                        "seeds": [seed],
                        "timeout_s": cohort_timeout_s,
                        "jobs": DEFAULT_JOBS,
                        "out_dir": out_rel,
                        "command": cmd,
                        "verify_command": verify_cmd,
                    }
                )
            wave_entry: dict[str, Any] = {
                "wave_id": wave_id,
                "cohort_id": cohort["cohort_id"],
                "cohort_wave": cohort_wave,
                "model": cohort["model"],
                "tier": cohort["tier"],
                "timeout_s": cohort_timeout_s,
                "execution_owner": cohort.get("execution_owner", "unassigned"),
                "fr8_dispatch_enabled": dispatch_enabled,
                "worker_count": len(jobs_list),
                "ram_safe": len(jobs_list) <= MAX_WORKERS_PER_WAVE,
                "seeds": batch,
                "jobs": jobs_list,
            }
            for opt_key in ("pre_registered_commit", "max_spend_usd", "stop_launch_at", "hard_drop_at"):
                if opt_key in cohort:
                    wave_entry[opt_key] = cohort[opt_key]
            waves.append(wave_entry)
    return waves


def build_template_waves(
    cohort_rows: list[dict[str, Any]],
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
) -> list[dict[str, Any]]:
    return partition_into_waves(
        cohort_rows,
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def build_g2_template_waves(
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
) -> list[dict[str, Any]]:
    return partition_into_waves(
        [dict(c) for c in G2_TEMPLATE_COHORTS],
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def build_gpt55_template_waves(
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    root: Path | None = ROOT,
    committed_landed_by_agent_tier: dict[tuple[str, str], list[int]] | None = None,
    include_committed: bool = False,
) -> list[dict[str, Any]]:
    if include_committed:
        cohorts = [dict(c) for c in GPT55_TEMPLATE_COHORTS]
    else:
        lookup = (
            committed_landed_by_agent_tier
            if committed_landed_by_agent_tier is not None
            else (_committed_landed_lookup_from_files(root) if root is not None else {})
        )
        cohorts = reconcile_template_cohorts(GPT55_TEMPLATE_COHORTS, lookup)
    return partition_into_waves(
        cohorts,
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def build_cross_family_template_waves(
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    root: Path | None = ROOT,
    committed_landed_by_agent_tier: dict[tuple[str, str], list[int]] | None = None,
    include_committed: bool = False,
) -> list[dict[str, Any]]:
    if include_committed:
        cohorts = [dict(c) for c in TEMPLATE_COHORTS]
    else:
        lookup = (
            committed_landed_by_agent_tier
            if committed_landed_by_agent_tier is not None
            else (_committed_landed_lookup_from_files(root) if root is not None else {})
        )
        cohorts = reconcile_template_cohorts(TEMPLATE_COHORTS, lookup)
    return partition_into_waves(
        cohorts,
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=True,
    )


def validate_wave_commands(waves: list[dict[str, Any]]) -> dict[str, Any]:
    global _CLI_PARSER_CACHE
    if _CLI_PARSER_CACHE is None:
        _CLI_PARSER_CACHE = common.base_args("OpenCode frontier runner", opencode_run.DEFAULT_MODEL)
    parser = _CLI_PARSER_CACHE
    errors: list[str] = []
    checked = 0
    for wave in waves:
        if wave["worker_count"] > MAX_WORKERS_PER_WAVE or wave["worker_count"] != len(wave["jobs"]):
            errors.append(f"wave {wave['wave_id']} violates <=3 worker constraint: {wave['worker_count']}")
        for job in wave["jobs"]:
            checked += 1
            cmd = str(job["command"])
            expected_timeout = int(job.get("timeout_s", DEFAULT_TIMEOUT_S))
            ckey = (cmd, str(job["model"]), expected_timeout, int(job["seed"]), str(job["out_dir"]))
            cached_errs = _CMD_VALIDATION_CACHE.get(ckey)
            if cached_errs is None:
                job_errs: list[str] = []
                if not cmd.startswith(f"{MOMIN_PATH_PREFIX} "):
                    job_errs.append(f"missing {MOMIN_PATH_PREFIX}")
                tokens = shlex.split(cmd)
                mod_idx = -1
                try:
                    mod_idx = tokens.index(RUNNER_MODULE)
                except ValueError:
                    job_errs.append(f"missing {RUNNER_MODULE}")
                if mod_idx >= 0:
                    if mod_idx < 1 or tokens[mod_idx - 1] != "-m":
                        job_errs.append(f"missing -m before {RUNNER_MODULE}")
                    else:
                        cli_argv = tokens[mod_idx + 1 :]
                        parsed = None
                        unknown: list[str] = []
                        try:
                            parsed, unknown = parser.parse_known_args(cli_argv)
                        except SystemExit as exc:
                            job_errs.append(f"failed arg parse: {exc}")
                        if parsed is not None:
                            if unknown:
                                job_errs.append(f"has invalid flags: {unknown}")
                            else:
                                norm_model = opencode_run.normalize_model(parsed.model)
                                if norm_model != job["model"]:
                                    job_errs.append(f"normalized model={norm_model} != {job['model']}")
                                spec = common.spec_from(parsed, f"opencode:{norm_model}")
                                if expected_timeout not in ALLOWED_TIMEOUTS_S:
                                    job_errs.append(f"unsupported timeout_s={expected_timeout}")
                                if parsed.timeout != expected_timeout:
                                    job_errs.append(f"timeout={parsed.timeout} != {expected_timeout}")
                                if parsed.jobs != DEFAULT_JOBS:
                                    job_errs.append(f"jobs={parsed.jobs} != {DEFAULT_JOBS}")
                                if parsed.tier not in rules.TIERS:
                                    job_errs.append(f"unknown tier={parsed.tier}")
                                if spec.seeds != [job["seed"]]:
                                    job_errs.append(f"parsed seeds={spec.seeds}")
                                if parsed.out != job["out_dir"]:
                                    job_errs.append(f"parsed out={parsed.out}")
                                if parsed.smoke or parsed.hint is not None or parsed.dry_run:
                                    job_errs.append("unexpected optional flag enabled")
                cached_errs = tuple(job_errs)
                if len(_CMD_VALIDATION_CACHE) >= 512:
                    _CMD_VALIDATION_CACHE.clear()
                _CMD_VALIDATION_CACHE[ckey] = cached_errs
            for msg in cached_errs:
                errors.append(f"wave {wave['wave_id']} seed {job['seed']} {msg}")
    return {
        "passed": not errors,
        "commands_validated": checked,
        "max_workers_per_wave": MAX_WORKERS_PER_WAVE,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "allowed_timeouts_s": list(ALLOWED_TIMEOUTS_S),
        "jobs_per_worker": DEFAULT_JOBS,
        "errors": errors,
    }


def check_tiers_gate() -> dict[str, Any]:
    errors: list[str] = []
    if rules.TIERS_VERSION != "v1.4":
        errors.append(f"expected TIERS_VERSION == 'v1.4', got {rules.TIERS_VERSION!r}")
    if set(rules.TIERS.keys()) != {"easy", "medium", "hard"}:
        errors.append(f"unexpected active tiers: {sorted(rules.TIERS.keys())}")
    return {
        "passed": not errors,
        "tiers_version": rules.TIERS_VERSION,
        "active_tiers": sorted(rules.TIERS.keys()),
        "errors": errors,
    }


def check_opencode_config_isolation() -> dict[str, Any]:
    errors: list[str] = []
    if opencode_run.PERMISSION != EXPECTED_PERMISSION:
        errors.append(f"PERMISSION mismatch: {opencode_run.PERMISSION!r}")
    test_url = "http://127.0.0.1:43210/mcp"
    cfg = opencode_run.opencode_config(test_url)
    if cfg.get("permission") != EXPECTED_PERMISSION:
        errors.append(f"opencode_config permission mismatch: {cfg.get('permission')!r}")
    cfg["permission"]["*"] = "allow"
    if opencode_run.PERMISSION != EXPECTED_PERMISSION:
        errors.append("opencode_config aliased module PERMISSION dict")
    if cfg.get("autoupdate") is not False:
        errors.append(f"expected autoupdate=False, got {cfg.get('autoupdate')!r}")
    if cfg.get("share") != "disabled":
        errors.append(f"expected share='disabled', got {cfg.get('share')!r}")
    servers = cfg.get("mcp", {}).get("servers", cfg.get("mcp", {}))
    canary_srv = servers.get("canary", {})
    if canary_srv.get("url") != test_url or canary_srv.get("enabled") is not True:
        errors.append(f"unexpected mcp canary config: {canary_srv!r}")
    for forbidden_mcp_key in ("env", "environment", "headers"):
        if forbidden_mcp_key in canary_srv:
            errors.append(f"mcp canary config unexpectedly carries {forbidden_mcp_key}")

    routing_cases = (
        ("gemini-4-carbon", "google/gemini-4-carbon"),
        ("google/gemini-4-carbon", "google/gemini-4-carbon"),
        ("gemini-4-argon", "google/gemini-4-argon"),
        ("gemini-4-hydrogen", "google/gemini-4-hydrogen"),
        ("gemini-3.5-flash", "google/gemini-3.5-flash"),
        ("gpt-5.5", "openai/gpt-5.5"),
        ("openai/gpt-5.5", "openai/gpt-5.5"),
    )
    for raw_m, exp_norm in routing_cases:
        got_norm = opencode_run.normalize_model(raw_m)
        if got_norm != exp_norm:
            errors.append(f"opencode_run.normalize_model({raw_m!r}) == {got_norm!r} != {exp_norm!r}")

    carbon_settings = opencode_run.opencode_google_settings("google/gemini-4-carbon")
    argon_settings = opencode_run.opencode_google_settings("google/gemini-4-argon")
    hydrogen_settings = opencode_run.opencode_google_settings("google/gemini-4-hydrogen")
    flash_settings = opencode_run.opencode_google_settings("google/gemini-3.5-flash")
    if "gemini-4-carbon: medium" not in carbon_settings.get("thinking", ""):
        errors.append(f"unexpected carbon thinking settings: {carbon_settings!r}")
    if "no thinkingLevel" not in argon_settings.get("thinking", ""):
        errors.append(f"unexpected argon thinking settings: {argon_settings!r}")
    if "no thinkingLevel" not in hydrogen_settings.get("thinking", ""):
        errors.append(f"unexpected hydrogen thinking settings: {hydrogen_settings!r}")
    if "thinkingLevel=high" not in flash_settings.get("thinking", ""):
        errors.append(f"unexpected flash thinking settings: {flash_settings!r}")
    if opencode_run.normalize_model("gpt-5.5").startswith("google/"):
        errors.append("openai/gpt-5.5 unexpectedly routed to google settings")
    return {
        "passed": not errors,
        "permission": dict(EXPECTED_PERMISSION),
        "autoupdate": False,
        "share": "disabled",
        "provider_routes_verified": len(routing_cases),
        "errors": errors,
    }


def check_child_env_stripping() -> dict[str, Any]:
    errors: list[str] = []
    plain_secret_vars, clean_launch_env_fn = _load_mcp_server_env_helpers()
    saved = dict(os.environ)
    orig_load_env = llm_base.load_env
    orig_mkdtemp = tempfile.mkdtemp
    wd: Path | None = None
    created_temp_dirs: list[Path] = []

    def tracked_mkdtemp(*args: Any, **kwargs: Any) -> str:
        p = orig_mkdtemp(*args, **kwargs)
        created_temp_dirs.append(Path(p))
        return p

    try:
        llm_base.load_env = lambda: None
        tempfile.mkdtemp = tracked_mkdtemp
        os.environ.pop("GOOGLE_GENERATIVE_AI_API_KEY", None)
        synthetic_values: dict[str, str] = {}
        for idx, key in enumerate(STRIPPED_ENV_VARS):
            val = f"synthetic-preflight-secret-{idx}-{key.lower()}"
            synthetic_values[key] = val
            os.environ[key] = val
        for plain_var in plain_secret_vars:
            os.environ[plain_var] = f"synthetic-plain-{plain_var.lower()}"

        base_cli_env = common.child_env()
        leaked_keys = sorted(k for k in STRIPPED_ENV_VARS if k in base_cli_env)
        if leaked_keys:
            errors.append(f"child_env leaked stripped keys: {leaked_keys}")
        leaked_vals = sorted(
            k for k, v in synthetic_values.items() if any(v == str(ev_val) for ev_val in base_cli_env.values())
        )
        if leaked_vals:
            errors.append(f"child_env leaked synthetic values for: {leaked_vals}")
        if base_cli_env.get("PWD") != "":
            errors.append(f"expected child_env PWD=='', got {base_cli_env.get('PWD')!r}")

        mcp_env = clean_launch_env_fn(base_cli_env)
        mcp_leaked_provider = sorted(
            k for k in (*PROVIDER_KEY_VARS, "GOOGLE_GENERATIVE_AI_API_KEY") if k in mcp_env
        )
        if mcp_leaked_provider:
            errors.append(f"MCP server env leaked provider keys: {mcp_leaked_provider}")
        mcp_leaked_secrets = sorted(k for k in plain_secret_vars if k in mcp_env)
        if mcp_leaked_secrets:
            errors.append(f"MCP server clean_launch_env leaked plain secret vars: {mcp_leaked_secrets}")

        wd = common.make_clean_workdir()
        extra_google, _ = opencode_run.child_env_extra("google/gemini-4-carbon")(wd)
        cli_google_env = {**common.child_env(), **extra_google}
        if cli_google_env.get("GOOGLE_GENERATIVE_AI_API_KEY") != synthetic_values["GEMINI_API_KEY"]:
            errors.append("google/* CLI env failed to map GEMINI_API_KEY to GOOGLE_GENERATIVE_AI_API_KEY")
        for forbidden_google in PROVIDER_KEY_VARS:
            if forbidden_google in cli_google_env:
                errors.append(f"google/* CLI env exposed {forbidden_google}")
        for flag_key in ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_SHARE"):
            if cli_google_env.get(flag_key) != "1":
                errors.append(f"expected {flag_key}=='1', got {cli_google_env.get(flag_key)!r}")
        oc_home = Path(cli_google_env["XDG_DATA_HOME"]).resolve().parent
        if common.REPO_ROOT.resolve() in oc_home.parents or oc_home == common.REPO_ROOT.resolve():
            errors.append("opencode per-episode XDG home is inside REPO_ROOT")
        if wd.resolve() in oc_home.parents or oc_home == wd.resolve():
            errors.append("opencode per-episode XDG home is inside agent workdir")

        for openai_alias in ("gpt-5.5", "openai/gpt-5.5"):
            extra_openai, _ = opencode_run.child_env_extra(openai_alias)(wd)
            cli_openai_env = {**common.child_env(), **extra_openai}
            if cli_openai_env.get("OPENAI_API_KEY") != synthetic_values["OPENAI_API_KEY"]:
                errors.append(f"{openai_alias} CLI env failed to pass OPENAI_API_KEY")
            for forbidden_openai in ("GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
                if forbidden_openai in cli_openai_env:
                    errors.append(f"{openai_alias} CLI env exposed {forbidden_openai}")
            oc_openai_home = Path(cli_openai_env["XDG_DATA_HOME"]).resolve().parent
            if common.REPO_ROOT.resolve() in oc_openai_home.parents or wd.resolve() in oc_openai_home.parents:
                errors.append(f"{openai_alias} per-episode XDG home violated repo/workdir isolation")

        extra_other, _ = opencode_run.child_env_extra("anthropic/unused-model")(wd)
        cli_other_env = {**common.child_env(), **extra_other}
        for any_key in (*PROVIDER_KEY_VARS, "GOOGLE_GENERATIVE_AI_API_KEY"):
            if any_key in cli_other_env:
                errors.append(f"unmapped provider CLI env unexpectedly exposed {any_key}")

        for k in PROVIDER_KEY_VARS:
            os.environ.pop(k, None)
        mcp_no_key_env = clean_launch_env_fn()
        if any(k in mcp_no_key_env for k in (*PROVIDER_KEY_VARS, "GOOGLE_GENERATIVE_AI_API_KEY")):
            errors.append("keyless parent MCP server launch env unexpectedly contained provider key")
        for missing_model in ("google/gemini-4-carbon", "openai/gpt-5.5"):
            caught_missing = False
            try:
                opencode_run.child_env_extra(missing_model)(wd)
            except llm_base.MissingKeyError:
                caught_missing = True
            if not caught_missing:
                errors.append(f"child_env_extra({missing_model!r}) did not raise MissingKeyError when key unset")
    finally:
        llm_base.load_env = orig_load_env
        tempfile.mkdtemp = orig_mkdtemp
        for k in list(os.environ.keys()):
            if k not in saved:
                os.environ.pop(k, None)
        for k, v in saved.items():
            if os.environ.get(k) != v:
                os.environ[k] = v
        if wd is not None:
            shutil.rmtree(wd, ignore_errors=True)
        for p in created_temp_dirs:
            shutil.rmtree(p, ignore_errors=True)

    return {
        "passed": not errors,
        "stripped_vars_verified": list(STRIPPED_ENV_VARS),
        "mcp_server_stripped_provider_keys": list(PROVIDER_KEY_VARS),
        "google_cli_active_key": "GOOGLE_GENERATIVE_AI_API_KEY",
        "openai_cli_active_key": "OPENAI_API_KEY",
        "isolated_xdg_home_verified": True,
        "errors": errors,
    }


_GEMINI_RUNNER_MODULE_CACHE: Any = None


def _load_gemini_runner_module():
    global _GEMINI_RUNNER_MODULE_CACHE
    if _GEMINI_RUNNER_MODULE_CACHE is not None:
        return _GEMINI_RUNNER_MODULE_CACHE
    runner_path = ROOT / "scripts" / "gemini_runner.py"
    spec = importlib.util.spec_from_file_location("preflight_gemini_runner", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {runner_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _GEMINI_RUNNER_MODULE_CACHE = mod
    return mod


def check_gemini_runner_controls() -> dict[str, Any]:
    global _GEMINI_RUNNER_CHECK_CACHE
    if _GEMINI_RUNNER_CHECK_CACHE is not None and "CANARY_TIERS_OVERRIDE" not in os.environ:
        return dict(_GEMINI_RUNNER_CHECK_CACHE, errors=list(_GEMINI_RUNNER_CHECK_CACHE["errors"]))
    errors: list[str] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="canary-preflight-gr-")).resolve()
    try:
        gr = _load_gemini_runner_module()
        route_cases = (
            ("gemini-4-carbon", "google/gemini-4-carbon"),
            ("gemini-4-argon", "google/gemini-4-argon"),
            ("gemini-4-hydrogen", "google/gemini-4-hydrogen"),
            ("gemini-3.5-flash", "google/gemini-3.5-flash"),
            ("google/gemini-4-carbon", "google/gemini-4-carbon"),
            ("gpt-5.5", "openai/gpt-5.5"),
            ("openai/gpt-5.5", "openai/gpt-5.5"),
        )
        for raw_m, exp_m in route_cases:
            got_m = gr.provider_model(raw_m)
            if got_m != exp_m:
                errors.append(f"gemini_runner.provider_model({raw_m!r}) == {got_m!r} != {exp_m!r}")

        saved_override = os.environ.pop("CANARY_TIERS_OVERRIDE", None)
        try:
            job_gpt = gr.Job("opencode", "hard", 0, tmp_dir / "s0", "gpt-5.5", GPT55_TIMEOUT_S)
            cmd_gpt = job_gpt.cmd()
            if "--model" not in cmd_gpt or cmd_gpt[cmd_gpt.index("--model") + 1] != "openai/gpt-5.5":
                errors.append(f"unexpected gpt-5.5 Job.cmd model routing: {cmd_gpt!r}")
            if "--timeout" not in cmd_gpt or cmd_gpt[cmd_gpt.index("--timeout") + 1] != str(GPT55_TIMEOUT_S):
                errors.append(f"unexpected gpt-5.5 Job.cmd timeout: {cmd_gpt!r}")

            job_gem = gr.Job("opencode", "hard", 0, tmp_dir / "s0", "gemini-4-carbon", DEFAULT_TIMEOUT_S)
            cmd_gem = job_gem.cmd()
            if "--model" not in cmd_gem or cmd_gem[cmd_gem.index("--model") + 1] != "google/gemini-4-carbon":
                errors.append(f"unexpected gemini-4-carbon Job.cmd model routing: {cmd_gem!r}")
        finally:
            if saved_override is not None:
                os.environ["CANARY_TIERS_OVERRIDE"] = saved_override

        buf_mismatch = io.StringIO()
        with contextlib.redirect_stdout(buf_mismatch):
            rc_mismatch = gr.main(["--tiers-version", "v1.3", "--staging", str(tmp_dir / "mismatch"), "--dry-run"])
        if rc_mismatch != 2:
            errors.append(f"expected gemini_runner --tiers-version mismatch rc=2, got {rc_mismatch}")

        stg_stop = tmp_dir / "stop_at"
        buf_stop = io.StringIO()
        with contextlib.redirect_stdout(buf_stop):
            rc_stop = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_stop),
                    "--model", "gpt-5.5",
                    "--seeds", "0-1",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--stop-launch-at", "00:00",
                ]
            )
        out_stop = buf_stop.getvalue()
        if rc_stop != 0 or "STOPPED LAUNCHING (stop-launch-at 00:00); 2 seed(s) never started" not in out_stop:
            errors.append(f"gemini_runner --stop-launch-at failed offline check: rc={rc_stop} out={out_stop!r}")

        stg_cap = tmp_dir / "spend_cap"
        ep0_dir = stg_cap / "opencode" / "hard" / "0"
        ep0_dir.mkdir(parents=True, exist_ok=True)
        (ep0_dir / "episodes.jsonl").write_text(
            json.dumps(
                {
                    "tier": "hard",
                    "seed": 0,
                    "agent": "opencode:openai/gpt-5.5",
                    "score": 0.6,
                    "correct": True,
                    "accused": "e01",
                    "final_day": 8,
                    "end_reason": "accused",
                    "meta": {"rc": 0, "usage": {"cost_usd_est": 200.0, "cost_usd_upper": 220.0}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        buf_cap = io.StringIO()
        with contextlib.redirect_stdout(buf_cap):
            rc_cap = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_cap),
                    "--model", "gpt-5.5",
                    "--seeds", "0-2",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--max-spend-usd", "200",
                    "--stop-launch-at", "99:99",
                ]
            )
        out_cap = buf_cap.getvalue()
        if rc_cap != 0 or "STOPPED LAUNCHING (spend cap $200 reached (est $200.00)); 2 seed(s) never started" not in out_cap:
            errors.append(f"gemini_runner --max-spend-usd failed offline check: rc={rc_cap} out={out_cap!r}")

        stg_assume = tmp_dir / "assume_cost"
        for s_idx in (0, 1):
            sd = stg_assume / "opencode" / "hard" / str(s_idx)
            sd.mkdir(parents=True, exist_ok=True)
            (sd / "episodes.jsonl").write_text(
                json.dumps(
                    {
                        "tier": "hard",
                        "seed": s_idx,
                        "agent": "opencode:openai/gpt-5.5",
                        "score": 0.5,
                        "correct": True,
                        "accused": "e01",
                        "final_day": 9,
                        "end_reason": "accused",
                        "meta": {"rc": 0, "usage": {"cost_unknown": True}},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        buf_assume_block = io.StringIO()
        with contextlib.redirect_stdout(buf_assume_block):
            rc_ab = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_assume),
                    "--model", "gpt-5.5",
                    "--seeds", "0-2",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--max-spend-usd", "15",
                    "--assume-cost-usd", "10.0",
                    "--stop-launch-at", "99:99",
                ]
            )
        out_ab = buf_assume_block.getvalue()
        if rc_ab != 0 or "STOPPED LAUNCHING (spend cap $15 reached (est $20.00)); 1 seed(s) never started" not in out_ab:
            errors.append(f"gemini_runner --assume-cost-usd block check failed: rc={rc_ab} out={out_ab!r}")

        buf_assume_dry = io.StringIO()
        with contextlib.redirect_stdout(buf_assume_dry):
            rc_ad = gr.main(
                [
                    "--tiers-version", "v1.4",
                    "--staging", str(stg_assume),
                    "--model", "gpt-5.5",
                    "--seeds", "0-2",
                    "--tiers", "hard",
                    "--harnesses", "opencode",
                    "--timeout", str(GPT55_TIMEOUT_S),
                    "--max-spend-usd", "25",
                    "--assume-cost-usd", "10.0",
                    "--stop-launch-at", "99:99",
                    "--dry-run",
                ]
            )
        out_ad = buf_assume_dry.getvalue()
        if rc_ad != 0 or "DRY opencode/hard/2:" not in out_ad or "--model openai/gpt-5.5" not in out_ad:
            errors.append(f"gemini_runner --assume-cost-usd dry-run check failed: rc={rc_ad} out={out_ad!r}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    res = {
        "passed": not errors,
        "source_commit": GPT55_PREREG_COMMIT,
        "provider_routes_verified": 7,
        "controls_verified": [
            "provider_model_google_and_openai",
            "--max-spend-usd",
            "--assume-cost-usd",
            "--stop-launch-at",
            "--tiers-version",
        ],
        "zero_live_subprocesses": True,
        "errors": errors,
    }
    if not errors and "CANARY_TIERS_OVERRIDE" not in os.environ:
        _GEMINI_RUNNER_CHECK_CACHE = dict(res, errors=list(errors))
    return res


def check_workdir_isolation(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    wd = common.make_clean_workdir()
    bad_wd = common.make_clean_workdir()
    try:
        repo_resolved = common.REPO_ROOT.resolve()
        root_resolved = root.resolve()
        wd_resolved = wd.resolve()
        if repo_resolved in wd_resolved.parents or wd_resolved == repo_resolved:
            errors.append(f"workdir {wd_resolved} is inside REPO_ROOT {repo_resolved}")
        if root_resolved in wd_resolved.parents or wd_resolved == root_resolved:
            errors.append(f"workdir {wd_resolved} is inside target root {root_resolved}")
        if list(wd.iterdir()):
            errors.append("fresh make_clean_workdir was not empty")
        cmd_google = opencode_run.build_cmd(wd, "PROMPT", "gemini-4-carbon", "http://127.0.0.1:18765/mcp")
        expected_google = [
            "opencode", "run", "--model", "google/gemini-4-carbon", "--format", "json", "--dir", str(wd), "PROMPT"
        ]
        if cmd_google != expected_google:
            errors.append(f"unexpected google build_cmd output: {cmd_google!r}")
        cmd_openai = opencode_run.build_cmd(wd, "PROMPT", "gpt-5.5", "http://127.0.0.1:18765/mcp")
        expected_openai = [
            "opencode", "run", "--model", "openai/gpt-5.5", "--format", "json", "--dir", str(wd), "PROMPT"
        ]
        if cmd_openai != expected_openai:
            errors.append(f"unexpected openai build_cmd output: {cmd_openai!r}")
        common.assert_clean(wd, opencode_run.FILES)

        (bad_wd / "opencode.json").write_text("{}", encoding="utf-8")
        (bad_wd / "leak.py").write_text("x = 1\n", encoding="utf-8")
        caught = False
        try:
            common.assert_clean(bad_wd, opencode_run.FILES)
        except AssertionError:
            caught = True
        if not caught:
            errors.append("assert_clean failed to reject unexpected .py file in workdir")
    finally:
        shutil.rmtree(wd, ignore_errors=True)
        shutil.rmtree(bad_wd, ignore_errors=True)

    if wd.exists() or bad_wd.exists():
        errors.append("temporary workdir cleanup failed")
    return {
        "passed": not errors,
        "outside_repo_root": True,
        "allowed_files": sorted(opencode_run.FILES),
        "cleaned_up": True,
        "errors": errors,
    }


def _parse_transcript_single_pass(
    tr_path: Path,
    unredacted_rx: re.Pattern[str],
) -> tuple[bool, bool, str | None, list[str], list[int], list[Any]]:
    resolved = tr_path.resolve()
    st = resolved.stat()
    raw_bytes = resolved.read_bytes()
    cache_key = (str(resolved), st.st_mtime_ns, st.st_size, hash(raw_bytes))
    cached = _TRANSCRIPT_PARSE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if unredacted_rx.pattern == r'"thoughtSignature":\s?"[^"<]{64,}"':
        has_unredacted = bool(_UNREDACTED_SIG_BYTES_RX.search(raw_bytes))
    else:
        has_unredacted = bool(unredacted_rx.search(raw_bytes.decode("utf-8")))
    m_out = b"\n--- stdout\n"
    m_err = b"\n--- stderr\n"
    if m_out in raw_bytes:
        _, _, after = raw_bytes.partition(m_out)
        if m_err in after:
            stdout_b, _, stderr_b = after.rpartition(m_err)
        elif after.endswith(b"\n--- stderr"):
            stdout_b, stderr_b = after[: -len(b"\n--- stderr")], b""
        else:
            stdout_b, stderr_b = after, b""
    else:
        stdout_b, stderr_b = raw_bytes, b""
    cur_text = 0
    cur_tool = 0
    last_reason: str | None = None
    last_text = 0
    last_tool = 0
    has_infra_ev = False
    tools: list[str] = []
    days: list[int] = []
    args_list: list[Any] = []
    day = 1
    for line in stdout_b.splitlines():
        if not line:
            continue
        if line.startswith(b'{"type":"step_start"'):
            cur_text = 0
            cur_tool = 0
            continue
        if line.startswith(b'{"type":"step_finish"'):
            if b'"reason":"tool-calls"' in line:
                last_reason = "tool-calls"
                last_text = cur_text
                last_tool = cur_tool
                continue
            if b'"reason":"stop"' in line:
                last_reason = "stop"
                last_text = cur_text
                last_tool = cur_tool
                continue
        if line.startswith(b'{"type":"reasoning"'):
            continue
        ev: Any = None
        if line.startswith(b'{"type":"tool_use"') and b"advance_day" not in line:
            s_idx = line.find(b'"state":{')
            opos = line.find(b',"output":', s_idx + 9) if s_idx >= 0 else -1
            if opos > 0:
                try:
                    cand = _loads_json(line[:opos] + b"}}}")
                    c_part = cand.get("part") if isinstance(cand, dict) else None
                    c_state = c_part.get("state") if isinstance(c_part, dict) else None
                    if (
                        isinstance(c_part, dict)
                        and isinstance(c_state, dict)
                        and "tool" in c_part
                        and "input" in c_state
                    ):
                        ev = cand
                except ValueError:
                    ev = None
        if ev is None:
            try:
                ev = _loads_json(line)
            except ValueError:
                continue
        if not isinstance(ev, dict):
            continue
        ev_type = ev.get("type")
        if ev_type in common.INFRA_EVENT_TYPES or (
            "type" not in ev and ("error" in ev or "statusCode" in ev)
        ):
            has_infra_ev = True
        part = ev.get("part")
        tool, args, res = None, None, None
        if isinstance(part, dict):
            typ = part.get("type")
            if typ == "step-start":
                cur_text = 0
                cur_tool = 0
            elif typ == "text" and (part.get("text") or "").strip():
                cur_text += 1
            elif typ == "tool":
                cur_tool += 1
                state = part.get("state") or {}
                status = state.get("status")
                if status in ("completed", "error"):
                    tool = part.get("tool", "")
                    args = state.get("input") or {}
                    if tool.endswith("advance_day"):
                        res = (
                            state.get("output")
                            if status == "completed"
                            else {"ok": False, "error": state.get("error")}
                        )
            elif typ == "step-finish":
                last_reason = part.get("reason")
                last_text = cur_text
                last_tool = cur_tool
        item = ev.get("item")
        if isinstance(item, dict) and item.get("type") == "mcp_tool_call" and ev_type == "item.completed":
            tool = item.get("tool", "")
            args = item.get("arguments") or {}
            if tool.endswith("advance_day"):
                res = (
                    item.get("result")
                    if item.get("result") is not None
                    else {"ok": False, "error": item.get("error")}
                )
        if tool is None:
            continue
        tool = common._strip(tool)
        if isinstance(args, str):
            try:
                args = _loads_json(args)
            except ValueError:
                args = {"raw": args}
        tools.append(tool)
        days.append(day)
        args_list.append(args)
        if tool == "advance_day":
            parsed_res = common._parse_result(res)
            if parsed_res.get("ok"):
                day = (parsed_res.get("data") or {}).get("day", day + 1)
    empty_final = last_reason is not None and last_reason == "stop" and not last_text and not last_tool
    if empty_final:
        infra_tag: str | None = "empty_model_response"
    elif has_infra_ev or (stderr_b and stderr_b.strip()):
        infra_tag = common.classify_infra(stdout_b.decode("utf-8"), stderr_b.decode("utf-8"))
    else:
        infra_tag = None
    parsed = (has_unredacted, empty_final, infra_tag, tools, days, args_list)
    if len(_TRANSCRIPT_PARSE_CACHE) >= 256:
        _TRANSCRIPT_PARSE_CACHE.clear()
    _TRANSCRIPT_PARSE_CACHE[cache_key] = parsed
    return parsed


def _audit_single_transcript(
    root: Path,
    tr_rel: str,
    episode: dict[str, Any],
    unredacted_rx: re.Pattern[str],
    errors: list[str],
) -> int:
    has_unredacted, empty_final, infra_tag, tools, days, args_list = _parse_transcript_single_pass(
        root / tr_rel,
        unredacted_rx,
    )
    if has_unredacted:
        errors.append(f"unredacted thoughtSignature in {tr_rel}")
    if empty_final:
        errors.append(f"verified transcript {tr_rel} flagged empty_final_response")
    if infra_tag is not None:
        errors.append(f"verified transcript {tr_rel} flagged infra={infra_tag}")
    recorded_steps = episode.get("steps") or []
    if len(tools) != len(recorded_steps):
        errors.append(
            f"steps_from_events count mismatch on {tr_rel}: "
            f"rebuilt={len(tools)} != recorded={len(recorded_steps)}"
        )
    elif tools != [s["tool"] for s in recorded_steps]:
        errors.append(f"steps_from_events tool sequence mismatch on {tr_rel}")
    elif days != [s["day"] for s in recorded_steps]:
        errors.append(f"steps_from_events day sequence mismatch on {tr_rel}")
    elif args_list != [s["args"] for s in recorded_steps]:
        errors.append(f"steps_from_events args mismatch on {tr_rel}")
    return len(tools)


def check_transcript_redaction_and_infra(
    root: Path,
    records_by_agent_tier: dict[tuple[str, str], dict[int, dict[str, Any]]],
    committed_g1_ext_records: dict[int, dict[str, Any]] | None = None,
    committed_gpt55_records: dict[int, dict[str, Any]] | None = None,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    long_sig = "T" * 240
    short_sig = "s" * 24
    synthetic_line = json.dumps(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "canary_status",
                "state": {"status": "completed", "input": {}, "output": '{"ok": true}'},
                "metadata": {
                    "google": {"thoughtSignature": long_sig},
                    "short": {"thoughtSignature": short_sig},
                },
            },
        }
    )
    compacted = common.compact_transcript(synthetic_line)
    if long_sig in compacted or '"thoughtSignature":"<240 chars>"' not in compacted:
        errors.append("compact_transcript failed to redact 240-char thoughtSignature blob")
    if short_sig not in compacted:
        errors.append("compact_transcript unexpectedly altered short <64-char thoughtSignature")

    empty_stop = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": {}}}),
        ]
    )
    normal_stop = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps({"type": "text", "part": {"type": "text", "text": "Accused e05."}}),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "stop", "tokens": {}}}),
        ]
    )
    tool_env_noise = "\n".join(
        [
            json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "type": "tool",
                        "tool": "canary_read_message",
                        "state": {
                            "status": "completed",
                            "input": {"id": "m1-0"},
                            "output": "UNAVAILABLE RESOURCE_EXHAUSTED database is locked usage limit has been reached",
                        },
                    },
                }
            ),
            json.dumps({"type": "step_finish", "part": {"type": "step-finish", "reason": "tool-calls", "tokens": {}}}),
        ]
    )
    quota_err = json.dumps({"type": "error", "error": {"data": {"message": "usage limit has been reached"}}})
    rate_err = json.dumps({"type": "error", "error": {"data": {"message": "RESOURCE_EXHAUSTED"}}})
    unavail_err = json.dumps({"type": "error", "error": {"data": {"message": "The model is overloaded"}}})
    generic_err = json.dumps({"type": "error", "error": {"name": "SyntheticError"}})

    if not common.empty_final_response(empty_stop):
        errors.append("empty_final_response missed synthetic empty stop turn")
    if common.classify_infra(empty_stop, "") != "empty_model_response":
        errors.append("classify_infra missed empty_model_response")
    if common.empty_final_response(normal_stop) or common.classify_infra(normal_stop, "") is not None:
        errors.append("normal stop turn misclassified as infra/empty")
    if common.classify_infra(tool_env_noise, "") is not None:
        errors.append("tool output text misclassified as infra error")
    if common.classify_infra(quota_err, "") != "provider_quota":
        errors.append("classify_infra missed provider_quota")
    if common.classify_infra(rate_err, "") != "provider_rate_limit":
        errors.append("classify_infra missed provider_rate_limit")
    if common.classify_infra(unavail_err, "") != "provider_unavailable":
        errors.append("classify_infra missed provider_unavailable")
    if common.classify_infra("", "Error: database is locked") != "opencode_db_locked":
        errors.append("classify_infra missed opencode_db_locked")
    if common.classify_infra(generic_err, "") != "cli_error_event":
        errors.append("classify_infra missed cli_error_event")

    unredacted_rx = re.compile(r'"thoughtSignature":\s?"[^"<]{64,}"')
    real_transcripts_checked = 0
    carbon_step_counts: dict[str, int] = {}
    committed_g1_ext_step_counts: dict[str, int] = {}
    committed_g1_ext_checked = 0
    flash_medium_s28_steps: int | None = None

    carbon_records = records_by_agent_tier.get(("opencode:google/gemini-4-carbon", "hard"), {})
    flash_medium_records = records_by_agent_tier.get(("opencode:google/gemini-3.5-flash", "medium"), {})
    if enforce_expected_baseline:
        for req_seed in EXPECTED_CARBON_HARD_LANDED:
            if req_seed not in carbon_records:
                errors.append(f"missing verified carbon hard replication record for seed {req_seed}")
        for req_seed in EXPECTED_FLASH_MEDIUM_LANDED:
            if req_seed not in flash_medium_records:
                errors.append(f"missing verified flash medium replication record for seed {req_seed}")

    for (agent, tier), seed_map in sorted(records_by_agent_tier.items()):
        if not agent.startswith("opencode:"):
            continue
        for seed, rec in sorted(seed_map.items()):
            tr_rel = rec["transcript_file"]
            if not tr_rel:
                continue
            real_transcripts_checked += 1
            step_n = _audit_single_transcript(root, tr_rel, rec["episode"], unredacted_rx, errors)
            if agent == "opencode:google/gemini-4-carbon" and tier == "hard" and 30 <= seed <= 59:
                carbon_step_counts[str(seed)] = step_n
            if agent == "opencode:google/gemini-3.5-flash" and tier == "medium" and seed == 28:
                flash_medium_s28_steps = step_n

    for seed, rec in sorted((committed_g1_ext_records or {}).items()):
        tr_rel = rec.get("transcript_file")
        if not tr_rel:
            continue
        committed_g1_ext_checked += 1
        committed_g1_ext_step_counts[str(seed)] = _audit_single_transcript(
            root, tr_rel, rec["episode"], unredacted_rx, errors
        )

    committed_gpt55_checked = 0
    committed_gpt55_total_steps = 0
    for seed, rec in sorted((committed_gpt55_records or {}).items()):
        tr_rel = rec.get("transcript_file")
        if not tr_rel:
            continue
        committed_gpt55_checked += 1
        committed_gpt55_total_steps += _audit_single_transcript(
            root, tr_rel, rec["episode"], unredacted_rx, errors
        )

    return {
        "passed": not errors,
        "synthetic_cases_verified": 9,
        "real_transcripts_checked": real_transcripts_checked,
        "committed_g1_ext_transcripts_checked": committed_g1_ext_checked,
        "committed_gpt55_transcripts_checked": committed_gpt55_checked,
        "committed_gpt55_total_steps": committed_gpt55_total_steps,
        "carbon_hard_step_counts": carbon_step_counts,
        "committed_g1_ext_step_counts": committed_g1_ext_step_counts,
        "flash_medium_s28_steps": flash_medium_s28_steps,
        "errors": errors,
    }


def build_provenance_honesty(
    committed_g1_seeds: list[int],
    committed_g1_quota_excluded: int,
    fr8_carbon_seeds: list[int],
    combined_carbon_ext_seeds: list[int],
    committed_gpt55_seeds: list[int],
    committed_gpt55_clean_unended_seeds: list[int],
    committed_gpt55_infra_excluded: int,
) -> dict[str, Any]:
    return {
        "panel_doc": PANEL_DOC,
        "panel_status_commit": PANEL_STATUS_COMMIT,
        "panel_fix_a_commit": PANEL_FIX_A_COMMIT,
        "panel_fix_d_commit": PANEL_FIX_D_COMMIT,
        "upstream_reconciled_commit": UPSTREAM_RECONCILED_COMMIT,
        "cohorts": {
            "primary_carbon_0_29": {
                "classification": "post_hoc_lock",
                "seed_range": [0, 29],
                "episodes_commit": PRIMARY_EPISODES_COMMIT,
                "lock_commit": PRIMARY_POST_HOC_LOCK_COMMIT,
                "lock_delay_s": PRIMARY_POST_HOC_LOCK_DELAY_S,
                "solver_reference_dirs": [
                    "data/runs/committed/v1.4/reference/solver-hard-20261114-121126",
                    "data/runs/committed/v1.4/reference/solver-hard-seeds20to29",
                ],
                "note": (
                    "Primary 0-29 seed lock (671ed96) landed 28s after episodes commit (8fd4dec); "
                    "classified as a post-hoc lock against reruns and cherry-picking, not a pre-registration."
                ),
            },
            "g1_carbon_hard_30_59": {
                "classification": "pre_registered",
                "seed_range": [30, 59],
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "committed_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                "committed_landed_seeds": committed_g1_seeds,
                "committed_n": len(committed_g1_seeds),
                "committed_provider_quota_excluded": committed_g1_quota_excluded,
                "fr8_replication_dir": "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
                "fr8_replication_landed_seeds": fr8_carbon_seeds,
                "fr8_replication_n": len(fr8_carbon_seeds),
                "combined_distinct_seeds": combined_carbon_ext_seeds,
                "combined_distinct_n": len(combined_carbon_ext_seeds),
            },
            "g2_argon_hydrogen_hard_0_29": {
                "classification": "pre_registered",
                "models": list(G2_MODELS),
                "tier": "hard",
                "seed_range": [0, 29],
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "committed_n": 0,
            },
            "gpt_5_5_hard_0_29": {
                "classification": "pre_registered",
                "cohort_id": "opencode-openai-gpt-5.5-hard-0-29",
                "agent": "opencode:openai/gpt-5.5",
                "model": OPENAI_GPT55_MODEL,
                "tier": "hard",
                "seed_range": [0, 29],
                "timeout_s": GPT55_TIMEOUT_S,
                "max_spend_usd": 200.0,
                "stop_launch_at": "08:15",
                "hard_drop_at": "08:45",
                "pre_registered_commit": GPT55_PREREG_COMMIT,
                "committed_commit": GPT55_COMMITTED_COMMIT,
                "committed_dir": GPT55_COMMITTED_DIR,
                "execution_owner": "silas_ca0a0dc0_committed_complete",
                "committed_n": len(committed_gpt55_seeds),
                "committed_infra_excluded": committed_gpt55_infra_excluded,
                "clean_unended_rc0_seeds": committed_gpt55_clean_unended_seeds,
            },
        },
    }


def build_manifest(
    root: Path = ROOT,
    max_workers_per_wave: int = MAX_WORKERS_PER_WAVE,
    enforce_expected_baseline: bool = True,
) -> dict[str, Any]:
    scan = scan_replication_tree(root, TARGET_COHORTS, enforce_expected_baseline=enforce_expected_baseline)
    committed_scan = scan_committed_v14_tree(root, enforce_expected_baseline=enforce_expected_baseline)
    committed_lookup = committed_scan.get("landed_by_agent_tier", {})
    reconciled_templates = reconcile_template_cohorts(TEMPLATE_COHORTS, committed_lookup)
    waves = partition_into_waves(
        scan["cohorts"],
        max_workers_per_wave=max_workers_per_wave,
        include_disabled=False,
    )
    template_waves = build_template_waves(scan["cohorts"], max_workers_per_wave=max_workers_per_wave)
    g2_template_waves = build_g2_template_waves(max_workers_per_wave=max_workers_per_wave)
    gpt55_template_waves = build_gpt55_template_waves(
        max_workers_per_wave=max_workers_per_wave,
        root=root,
        committed_landed_by_agent_tier=committed_lookup,
    )
    gpt55_synthetic_waves = build_gpt55_template_waves(
        max_workers_per_wave=max_workers_per_wave,
        include_committed=True,
    )
    cross_family_waves = build_cross_family_template_waves(
        max_workers_per_wave=max_workers_per_wave,
        root=root,
        committed_landed_by_agent_tier=committed_lookup,
    )

    tiers_check = check_tiers_gate()
    config_check = check_opencode_config_isolation()
    env_check = check_child_env_stripping()
    runner_check = check_gemini_runner_controls()
    workdir_check = check_workdir_isolation(root)
    transcript_check = check_transcript_redaction_and_infra(
        root,
        scan.get("records_by_agent_tier", {}),
        committed_g1_ext_records=committed_scan.get("g1_ext_records", {}),
        committed_gpt55_records=committed_scan.get("gpt55_records", {}),
        enforce_expected_baseline=enforce_expected_baseline,
    )
    active_cmd_check = validate_wave_commands(waves)
    template_cmd_check = validate_wave_commands(template_waves)
    g2_cmd_check = validate_wave_commands(g2_template_waves)
    gpt55_cmd_check = validate_wave_commands(gpt55_template_waves)
    gpt55_syn_cmd_check = validate_wave_commands(gpt55_synthetic_waves)
    cmd_errors = (
        list(active_cmd_check["errors"])
        + list(template_cmd_check["errors"])
        + list(g2_cmd_check["errors"])
        + list(gpt55_cmd_check["errors"])
        + list(gpt55_syn_cmd_check["errors"])
    )
    cohorts_by_id = {c["cohort_id"]: c for c in scan["cohorts"]}
    for w in waves:
        cohort_obj = cohorts_by_id.get(w["cohort_id"])
        if cohort_obj is not None and not cohort_obj.get("fr8_dispatch_enabled", False):
            cmd_errors.append(f"active wave {w['wave_id']} dispatches disabled cohort {w['cohort_id']}")
    tmpl_by_id = {c["cohort_id"]: c for c in reconciled_templates}
    for w in cross_family_waves:
        t_obj = tmpl_by_id.get(w["cohort_id"])
        if t_obj is not None:
            overlap = sorted(set(w["seeds"]) & set(t_obj.get("landed_seeds", [])))
            if overlap:
                cmd_errors.append(
                    f"cross-family template wave {w['wave_id']} queues committed seeds {overlap} for {w['cohort_id']}"
                )
    cmd_check = {
        "passed": not cmd_errors,
        "active_waves_validated": len(waves),
        "active_commands_validated": active_cmd_check["commands_validated"],
        "template_waves_validated": len(template_waves),
        "commands_validated": template_cmd_check["commands_validated"],
        "g2_family_waves_validated": len(g2_template_waves),
        "g2_family_commands_validated": g2_cmd_check["commands_validated"],
        "gpt55_waves_validated": len(gpt55_template_waves),
        "gpt55_commands_validated": gpt55_cmd_check["commands_validated"],
        "gpt55_synthetic_waves_validated": len(gpt55_synthetic_waves),
        "gpt55_synthetic_commands_validated": gpt55_syn_cmd_check["commands_validated"],
        "cross_family_waves_validated": len(cross_family_waves),
        "cross_family_commands_validated": g2_cmd_check["commands_validated"] + gpt55_cmd_check["commands_validated"],
        "max_workers_per_wave": max_workers_per_wave,
        "timeout_s": DEFAULT_TIMEOUT_S,
        "gpt55_timeout_s": GPT55_TIMEOUT_S,
        "jobs_per_worker": DEFAULT_JOBS,
        "errors": cmd_errors,
    }
    blackout_check = check_carbon_quota_blackout_guard()

    carbon_cohort = cohorts_by_id.get("opencode-gemini-4-carbon-hard-30-59", {})
    fr8_carbon_seeds = list(carbon_cohort.get("landed_seeds", []))
    committed_g1_seeds = list(committed_scan["g1_ext_landed_seeds"])
    committed_gpt55_seeds = list(committed_scan["gpt55_landed_seeds"])
    committed_gpt55_clean_unended = list(committed_scan["gpt55_clean_unended_seeds"])
    committed_gpt55_infra_excluded = int(committed_scan["gpt55_infra_excluded"])
    combined_ext_seeds = sorted(set(committed_g1_seeds) | set(fr8_carbon_seeds))
    shared_ext_seeds = sorted(set(committed_g1_seeds) & set(fr8_carbon_seeds))
    combined_ext_remaining = sorted(set(range(30, 60)) - set(combined_ext_seeds))

    reconcile_errors = list(committed_scan["errors"])
    combined_total = committed_scan["total_episodes"] + scan["total_episodes"]
    combined_verified = committed_scan["replay_verified_episodes"] + scan["replay_verified_episodes"]
    if enforce_expected_baseline:
        if combined_total != EXPECTED_COMBINED_V14_EPISODES or combined_verified != EXPECTED_COMBINED_V14_EPISODES:
            reconcile_errors.append(
                f"expected {EXPECTED_COMBINED_V14_EPISODES}/{EXPECTED_COMBINED_V14_EPISODES} "
                f"combined v1.4 episodes, got {combined_verified}/{combined_total}"
            )
        if combined_ext_seeds != EXPECTED_COMBINED_CARBON_HARD_EXT_LANDED:
            reconcile_errors.append(
                f"expected combined carbon hard 30-59 coverage {EXPECTED_COMBINED_CARBON_HARD_EXT_LANDED}, "
                f"got {combined_ext_seeds}"
            )
        if len(combined_ext_remaining) != EXPECTED_COMBINED_CARBON_HARD_EXT_REMAINING_COUNT:
            reconcile_errors.append(
                f"expected {EXPECTED_COMBINED_CARBON_HARD_EXT_REMAINING_COUNT} remaining carbon hard 30-59 seeds, "
                f"got {len(combined_ext_remaining)}"
            )
        if len(gpt55_template_waves) != 0:
            reconcile_errors.append(
                f"expected 0 remaining gpt-5.5 template waves after ca0a0dc0 reconciliation, got {len(gpt55_template_waves)}"
            )

    reconcile_check = {
        "passed": not reconcile_errors,
        "committed_v14_episodes": committed_scan["total_episodes"],
        "committed_v14_replay_verified": committed_scan["replay_verified_episodes"],
        "replication_v14_episodes": scan["total_episodes"],
        "replication_v14_replay_verified": scan["replay_verified_episodes"],
        "combined_v14_episodes": combined_total,
        "combined_v14_replay_verified": combined_verified,
        "g1_committed_landed_seeds": committed_g1_seeds,
        "g1_committed_provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
        "g1_fr8_landed_seeds": fr8_carbon_seeds,
        "g1_combined_distinct_seeds": combined_ext_seeds,
        "g1_combined_remaining_count": len(combined_ext_remaining),
        "gpt55_committed_landed_count": len(committed_gpt55_seeds),
        "gpt55_committed_clean_unended_seeds": committed_gpt55_clean_unended,
        "gpt55_committed_infra_excluded": committed_gpt55_infra_excluded,
        "errors": reconcile_errors,
    }

    checks = {
        "tiers_v14_gate": tiers_check,
        "opencode_config_permission": config_check,
        "child_env_isolation": env_check,
        "gemini_runner_cf394894_controls": runner_check,
        "clean_workdir_isolation": workdir_check,
        "transcript_redaction_infra_and_steps": transcript_check,
        "cli_command_validation": cmd_check,
        "carbon_quota_blackout_guard": blackout_check,
        "v14_corpus_reconciliation": reconcile_check,
    }
    all_errors = list(scan["errors"])
    for chk in checks.values():
        all_errors.extend(chk["errors"])

    total_target = sum(c["target_count"] for c in scan["cohorts"])
    total_landed = sum(c["landed_count"] for c in scan["cohorts"])
    total_missing = sum(c["missing_count"] for c in scan["cohorts"])
    template_cohort_rows = serialize_template_cohorts(reconciled_templates)
    provenance_honesty = build_provenance_honesty(
        committed_g1_seeds=committed_g1_seeds,
        committed_g1_quota_excluded=committed_scan["g1_ext_provider_quota_excluded"],
        fr8_carbon_seeds=fr8_carbon_seeds,
        combined_carbon_ext_seeds=combined_ext_seeds,
        committed_gpt55_seeds=committed_gpt55_seeds,
        committed_gpt55_clean_unended_seeds=committed_gpt55_clean_unended,
        committed_gpt55_infra_excluded=committed_gpt55_infra_excluded,
    )

    return {
        "schema_version": 1,
        "tiers_version": rules.TIERS_VERSION,
        "upstream_reconciled_commit": UPSTREAM_RECONCILED_COMMIT,
        "replication_root": scan["replication_root"],
        "corpus_reconciliation": {
            "committed_v14": {
                "root": committed_scan["committed_root"],
                "total_episodes": committed_scan["total_episodes"],
                "replay_verified_episodes": committed_scan["replay_verified_episodes"],
            },
            "fr8_replication_v14": {
                "root": scan["replication_root"],
                "total_episodes": scan["total_episodes"],
                "replay_verified_episodes": scan["replay_verified_episodes"],
                "frontier_target_episodes": total_target,
                "frontier_landed_episodes": total_landed,
                "frontier_missing_episodes": total_missing,
            },
            "combined_v14_total_episodes": combined_total,
            "combined_v14_replay_verified_episodes": combined_verified,
            "carbon_hard_30_59_extension": {
                "seed_range": [30, 59],
                "target_count": 30,
                "committed_g1_partial": {
                    "run_dir": committed_scan["g1_ext_dir"],
                    "landed_seeds": committed_g1_seeds,
                    "n": len(committed_g1_seeds),
                    "provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
                },
                "fr8_replication": {
                    "run_dir": "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
                    "landed_seeds": fr8_carbon_seeds,
                    "n": len(fr8_carbon_seeds),
                    "fr8_tree_remaining_count": int(carbon_cohort.get("missing_count", 25)),
                },
                "combined_distinct_landed_seeds": combined_ext_seeds,
                "combined_distinct_count": len(combined_ext_seeds),
                "shared_overlap_seeds": shared_ext_seeds,
                "shared_overlap_count": len(shared_ext_seeds),
                "combined_remaining_seeds": combined_ext_remaining,
                "combined_remaining_count": len(combined_ext_remaining),
            },
            "gpt55_hard_0_29_committed": {
                "run_dir": committed_scan["gpt55_dir"],
                "seed_range": [0, 29],
                "target_count": 30,
                "landed_count": len(committed_gpt55_seeds),
                "remaining_count": 30 - len(committed_gpt55_seeds),
                "clean_unended_rc0_seeds": committed_gpt55_clean_unended,
                "infra_excluded": committed_gpt55_infra_excluded,
                "pre_registered_commit": GPT55_PREREG_COMMIT,
                "committed_commit": GPT55_COMMITTED_COMMIT,
            },
        },
        "provenance_honesty": provenance_honesty,
        "gemini_sessions": {
            "source_doc": GEMINI_SESSIONS_DOC,
            "source_commit": GEMINI_SESSIONS_COMMIT,
            "pure_cpu_mode": True,
            "fr8_live_gemini_dispatch_enabled": any(
                c["fr8_dispatch_enabled"] for c in scan["cohorts"] + template_cohort_rows
            ),
            "g1_carbon_hard_ext60": {
                "cohort_id": "opencode-gemini-4-carbon-hard-30-59",
                "execution_owner": "silas_g1_ext60",
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "fr8_dispatch_enabled": False,
                "model": CARBON_MODEL,
                "tier": "hard",
                "seed_range": [30, 59],
                "committed_ext_dir": committed_scan["g1_ext_dir"],
                "committed_landed_seeds": committed_g1_seeds,
                "committed_landed_count": len(committed_g1_seeds),
                "committed_provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
                "fr8_landed_seeds": fr8_carbon_seeds,
                "remaining_count": int(carbon_cohort.get("missing_count", 25)),
                "combined_distinct_landed_seeds": combined_ext_seeds,
                "combined_distinct_count": len(combined_ext_seeds),
                "combined_remaining_count": len(combined_ext_remaining),
            },
            "g2_frontier_families_hard_0_29": {
                "execution_owner": "silas_g2_families",
                "pre_registered_commit": GEMINI_SESSIONS_COMMIT,
                "fr8_dispatch_enabled": False,
                "models": list(G2_MODELS),
                "tier": "hard",
                "seed_range": [0, 29],
                "allowed_during_carbon_blackout": True,
            },
            "gpt55_hard_0_29": {
                "cohort_id": "opencode-openai-gpt-5.5-hard-0-29",
                "agent": "opencode:openai/gpt-5.5",
                "model": OPENAI_GPT55_MODEL,
                "tier": "hard",
                "seed_range": [0, 29],
                "timeout_s": GPT55_TIMEOUT_S,
                "max_spend_usd": 200.0,
                "stop_launch_at": "08:15",
                "hard_drop_at": "08:45",
                "pre_registered_commit": GPT55_PREREG_COMMIT,
                "committed_commit": GPT55_COMMITTED_COMMIT,
                "committed_dir": GPT55_COMMITTED_DIR,
                "committed_landed_count": len(committed_gpt55_seeds),
                "remaining_count": 30 - len(committed_gpt55_seeds),
                "clean_unended_rc0_seeds": committed_gpt55_clean_unended,
                "execution_owner": "silas_ca0a0dc0_committed_complete",
                "fr8_dispatch_enabled": False,
                "allowed_during_carbon_blackout": True,
            },
            "carbon_quota_blackout": {
                "window_start_utc": CARBON_BLACKOUT_START_ISO,
                "window_end_utc": CARBON_BLACKOUT_END_ISO,
                "window_local_eet": CARBON_BLACKOUT_LOCAL_WINDOW,
                "blocked_models": [CARBON_MODEL],
                "allowed_models": list(NON_CARBON_REHEARSAL_ALLOWED_MODELS),
                "reason": CARBON_BLACKOUT_REASON,
            },
        },
        "runner": {
            "module": RUNNER_MODULE,
            "python": VENV_PYTHON,
            "path_prefix": MOMIN_PATH_PREFIX,
            "timeout_s": DEFAULT_TIMEOUT_S,
            "gpt55_timeout_s": GPT55_TIMEOUT_S,
            "jobs_per_worker": DEFAULT_JOBS,
            "max_workers_per_wave": max_workers_per_wave,
        },
        "summary": {
            "passed": not all_errors,
            "pure_cpu_mode": True,
            "committed_v14_total_episodes": committed_scan["total_episodes"],
            "committed_v14_replay_verified_episodes": committed_scan["replay_verified_episodes"],
            "replication_total_episodes": scan["total_episodes"],
            "replication_replay_verified_episodes": scan["replay_verified_episodes"],
            "combined_v14_total_episodes": combined_total,
            "combined_v14_replay_verified_episodes": combined_verified,
            "target_frontier_episodes": total_target,
            "landed_frontier_episodes": total_landed,
            "missing_frontier_episodes": total_missing,
            "g1_committed_ext_episodes": len(committed_g1_seeds),
            "g1_committed_ext_provider_quota_excluded": committed_scan["g1_ext_provider_quota_excluded"],
            "g1_fr8_replication_episodes": len(fr8_carbon_seeds),
            "g1_combined_distinct_hard_ext_episodes": len(combined_ext_seeds),
            "g1_combined_remaining_hard_ext_episodes": len(combined_ext_remaining),
            "gpt55_committed_hard_episodes": len(committed_gpt55_seeds),
            "fr8_dispatch_active_episodes": sum(w["worker_count"] for w in waves),
            "wave_count": len(waves),
            "max_workers_in_any_wave": max((w["worker_count"] for w in waves), default=0),
            "template_wave_count": len(template_waves),
            "template_commands_validated": template_cmd_check["commands_validated"],
            "cross_family_template_wave_count": len(cross_family_waves),
            "cross_family_template_commands_validated": (
                g2_cmd_check["commands_validated"] + gpt55_cmd_check["commands_validated"]
            ),
            "gpt55_synthetic_template_commands_validated": gpt55_syn_cmd_check["commands_validated"],
        },
        "cohorts": scan["cohorts"],
        "template_cohorts": template_cohort_rows,
        "preflight": {
            "passed": not all_errors,
            "zero_live_llm_calls": True,
            "checks": checks,
            "errors": all_errors,
        },
        "waves": waves,
    }


EXPECTED_CORPUS_SHA256 = "ffb14f00cb5b2efa24125284ebe2804de39018fb723556271ceb079c1179ead1"
EXPECTED_MANIFEST_SHA256 = "d11f690f63b8e95082cab64483cb18b400c592d79fb82f17b0c51d38e94ddf29"
_DEFAULT_BUILD_MANIFEST = build_manifest


def _corpus_inputs_sha256(root: Path) -> str:
    rels: list[str] = []
    for base in ("data/runs/committed/v1.4", "results/frontier_replication/v1.4"):
        d = root / base
        if d.is_dir():
            for dp, dns, fns in os.walk(d):
                dns.sort()
                p = Path(dp)
                for fn in sorted(fns):
                    if fn in ("episodes.jsonl", "meta.json") or (p.name == "transcripts" and fn.endswith(".txt")):
                        rels.append((p / fn).relative_to(root).as_posix())
    for extra in (
        "canary/rules.py",
        "canary/env.py",
        "canary/world.py",
        "canary/mcp_server.py",
        "canary/agents/frontier/common.py",
        "canary/agents/frontier/opencode_run.py",
        "scripts/gemini_runner.py",
    ):
        if (root / extra).is_file():
            rels.append(extra)
    h = hashlib.sha256()
    for r in sorted(set(rels)):
        h.update(r.encode("ascii") + b"\0")
        h.update(hashlib.sha256((root / r).read_bytes()).digest())
    return h.hexdigest()


def render_manifest(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2) + "\n"


def default_manifest_path(root: Path) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "queue_manifest.json"


def _emit_ok_output(manifest: dict[str, Any], rendered: str, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(rendered)
        return
    s = manifest["summary"]
    cohort_bits = ", ".join(
        f"{c['cohort_id']}: owner={c['execution_owner']} dispatch={c['fr8_dispatch_enabled']} "
        f"landed={c['landed_count']}/{c['target_count']} missing={c['missing_count']}"
        for c in manifest["cohorts"]
    )
    print(
        f"OK preflight=PASS combined_verified={s['combined_v14_replay_verified_episodes']}/{s['combined_v14_total_episodes']} "
        f"committed={s['committed_v14_replay_verified_episodes']}/{s['committed_v14_total_episodes']} "
        f"replication={s['replication_replay_verified_episodes']}/{s['replication_total_episodes']} "
        f"fr8_landed={s['landed_frontier_episodes']}/{s['target_frontier_episodes']} "
        f"g1_combined_ext={s['g1_combined_distinct_hard_ext_episodes']}/30 "
        f"active_waves={s['wave_count']} template_cmds={s['template_commands_validated']} "
        f"cross_family_cmds={s['cross_family_template_commands_validated']} ({cohort_bits})"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline frontier runner preflight and 30-59 replication queue manifest.")
    ap.add_argument("--root", default=str(ROOT), help="repository root directory")
    ap.add_argument("--manifest", default=None, help="override output/check manifest path")
    ap.add_argument("--write", action="store_true", help="write queue_manifest.json")
    ap.add_argument("--check", action="store_true", help="verify preflight passes and queue_manifest.json is up to date")
    ap.add_argument("--full-check", action="store_true", help="force full 777-episode replay during --check")
    ap.add_argument(
        "--validate-template-waves",
        action="store_true",
        help="validate offline runner CLI syntax on synthetic/template waves while keeping active waves empty",
    )
    ap.add_argument("--check-blackout", default=None, help="evaluate carbon blackout guard at UTC epoch or ISO timestamp")
    ap.add_argument("--model", default=CARBON_MODEL, help="model id for --check-blackout")
    ap.add_argument("--json", action="store_true", help="print JSON output to stdout")
    args = ap.parse_args(argv)

    if args.check_blackout is not None:
        res = check_carbon_quota_blackout(args.check_blackout, model=args.model)
        if args.json:
            sys.stdout.write(json.dumps(res, indent=2) + "\n")
        else:
            print(
                f"blackout_check model={res['model']} ts={res['timestamp_utc']} "
                f"allowed={res['allowed']} reason={res['reason']}"
            )
        return 0 if res["allowed"] else 1

    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve() if args.manifest else default_manifest_path(root)
    enforce_baseline = root == ROOT.resolve()

    if (
        args.check
        and not args.write
        and not args.full_check
        and enforce_baseline
        and build_manifest is _DEFAULT_BUILD_MANIFEST
        and manifest_path == default_manifest_path(root).resolve()
        and manifest_path.is_file()
    ):
        raw_manifest = manifest_path.read_bytes()
        if (
            hashlib.sha256(raw_manifest).hexdigest() == EXPECTED_MANIFEST_SHA256
            and _corpus_inputs_sha256(root) == EXPECTED_CORPUS_SHA256
        ):
            live_gates = (
                check_tiers_gate(),
                check_opencode_config_isolation(),
                check_child_env_stripping(),
                check_gemini_runner_controls(),
                check_workdir_isolation(root),
                check_carbon_quota_blackout_guard(),
            )
            if all(g["passed"] for g in live_gates):
                stored_manifest = _loads_json(raw_manifest)
                waves_ok = True
                if args.validate_template_waves:
                    waves_ok = (
                        stored_manifest.get("waves") == []
                        and validate_wave_commands(build_template_waves(stored_manifest["cohorts"]))["passed"]
                        and validate_wave_commands(build_g2_template_waves())["passed"]
                        and validate_wave_commands(build_gpt55_template_waves(include_committed=True))["passed"]
                    )
                if waves_ok:
                    _emit_ok_output(stored_manifest, raw_manifest.decode("utf-8"), args.json)
                    return 0

    manifest = build_manifest(root=root, enforce_expected_baseline=enforce_baseline)
    rendered = render_manifest(manifest)

    if not manifest["summary"]["passed"]:
        for err in manifest["preflight"]["errors"]:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    if args.validate_template_waves:
        cmd_val = manifest["preflight"]["checks"]["cli_command_validation"]
        if not cmd_val["passed"] or manifest["waves"] != []:
            for err in cmd_val["errors"]:
                print(f"FAIL: {err}", file=sys.stderr)
            if manifest["waves"] != []:
                print("FAIL: active waves must be empty in pure-CPU mode", file=sys.stderr)
            return 1

    if args.write:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(rendered, encoding="utf-8")

    if args.check:
        if not manifest_path.is_file():
            print(f"FAIL: manifest missing at {manifest_path}", file=sys.stderr)
            return 1
        existing = manifest_path.read_text(encoding="utf-8")
        if existing != rendered:
            print(f"FAIL: manifest out of date at {manifest_path}; re-run with --write", file=sys.stderr)
            return 1

    _emit_ok_output(manifest, rendered, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
