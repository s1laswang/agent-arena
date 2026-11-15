"""Pure-CPU mole-archetype and seed-difficulty stratification audit for Canary v1.4 cohorts.

    python scripts/frontier_mole_stratified_gap.py --write
    python scripts/frontier_mole_stratified_gap.py --check
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from pydantic_core import from_json as _fast_json_loads
except ImportError:
    _fast_json_loads = json.loads

import canary
from canary.analysis.gap import mean_ci
from canary.env import Env
from canary.mole.dsl import DEFAULT_STRATEGY
from canary.rules import TIERS_VERSION, TRACKS, tier_params, tier_params_for_episode
from canary.solver.belief import Doc, _fallback, behaviour_logliks, leak_loglik
from canary.solver.policy import SolverPolicy
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.template import (
    SIGNALS as _IV_SIGNALS,
    TOPICS as _IV_TOPICS,
    TemplateProvider,
    _ANSWERS as _IV_ANSWERS,
    _fill as _iv_fill,
)
from canary.types import ToolResult
from canary.world import world_seed

_SHARED_CACHE: dict[str, dict[Any, Any]] = vars(canary).setdefault("_frontier_v14_cache", {})
_BASE_ENV_CACHE: dict[
    tuple[str, int, int],
    tuple[
        Env,
        tuple[EmployeeFacts, ...],
        ToolResult,
        dict[str, str],
        str,
        tuple[str, ...],
        tuple[float, float, float],
        Any,
    ],
] = _SHARED_CACHE.setdefault("base_env_proto_v5", {})
_DAY_MSG_CACHE: dict[tuple[Any, ...], tuple[dict[str, Any], ...]] = _SHARED_CACHE.setdefault(
    "day_messages", {}
)
_IV_ANS_CACHE: dict[tuple[Any, ...], str] = _SHARED_CACHE.setdefault("iv_answers", {})
_IV_RES_CACHE: dict[tuple[Any, ...], ToolResult] = _SHARED_CACHE.setdefault("iv_results", {})
_POOL_CACHE: dict[
    tuple[str, str, tuple[tuple[str, int, int], ...]],
    list[tuple[str, dict[str, Any]]],
] = _SHARED_CACHE.setdefault("indexed_pools", {})
_WORLD_PASSIVE_CACHE: dict[tuple[str, str, int], dict[str, Any]] = _SHARED_CACHE.setdefault(
    "world_passive_profiles", {}
)
_POSTERIOR_BY_STEPS: dict[int, tuple[object, float | None]] = _SHARED_CACHE.setdefault(
    "posterior_by_steps", {}
)

_BASE_TEMPLATE_PROVIDER = TemplateProvider()
_MSG_TOOLS: frozenset[str] = frozenset({"search_messages", "read_message"})
_DUMMY_FACTS = PublicDayFacts("hard", 0, 1, None, (), (), None, "neutral", ())


def _noop_log(*_args: Any, **_kwargs: Any) -> None:
    return None


class _ReplayTemplateProvider:
    name = "template"
    __slots__ = (
        "need_messages",
        "need_interview_text",
        "need_logs",
        "need_future_rng",
        "count_mole_logs_only",
    )

    def __init__(
        self,
        need_messages: bool = True,
        need_interview_text: bool = True,
        need_logs: bool = True,
        need_future_rng: bool = True,
        count_mole_logs_only: bool = False,
    ) -> None:
        self.need_messages = need_messages
        self.need_interview_text = need_interview_text
        self.need_logs = need_logs
        self.need_future_rng = need_future_rng
        self.count_mole_logs_only = count_mole_logs_only

    def day_messages(self, facts: PublicDayFacts) -> Any:
        if not self.need_messages:
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
        facts: PublicDayFacts,
        employee: str,
        topic: str,
        signal: str,
    ) -> str:
        if not self.need_interview_text:
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


_NOOP_REPLAY_PROVIDER = _ReplayTemplateProvider(
    need_messages=False,
    need_interview_text=False,
    need_logs=False,
    need_future_rng=False,
    count_mole_logs_only=False,
)


def _make_replay_env(tier: str, seed: int, provider: _ReplayTemplateProvider) -> Env:
    if tier in TRACKS:
        return Env(tier, seed, text_provider=provider)
    ws = world_seed(tier, seed)
    ckey = (tier, seed, ws)
    cached = _BASE_ENV_CACHE.get(ckey)
    if cached is None:
        proto = Env(tier, seed, text_provider=_NOOP_REPLAY_PROVIDER)
        emp_facts = tuple(
            EmployeeFacts(e.id, e.name, e.dept, e.role, e.clearance)
            for e in proto._world.employees
        )
        emp_list_out = []
        for e in proto._world.employees:
            ed = {"id": e.id, "name": e.name, "dept": e.dept, "role": e.role}
            if e.clearance is not None:
                ed["clearance"] = e.clearance
            emp_list_out.append(ed)
        emp_list_res = ToolResult(True, {"employees": emp_list_out})
        emp_dept_map = {e.id: e.dept for e in proto._world.employees}
        decoy_mood = "angry" if proto._world.decoy else "neutral"
        others_base = tuple(
            x
            for x in proto._ids
            if x != proto._world.mole and x != proto._world.decoy
        )
        tp0 = proto.p
        exp_consts = (
            math.exp(-tp0.log_rate_mole) if tp0.log_rate_mole > 0 else 1.0,
            math.exp(-tp0.log_rate_benign) if tp0.log_rate_benign > 0 else 1.0,
            math.exp(-tp0.framing_rate) if (tp0.framing and tp0.framing_rate > 0) else 1.0,
        )
        if len(_BASE_ENV_CACHE) >= 256:
            _BASE_ENV_CACHE.clear()
        cached = (proto, emp_facts, emp_list_res, emp_dept_map, decoy_mood, others_base, exp_consts, None)
        _BASE_ENV_CACHE[ckey] = cached
        if proto._world.mole_strategy is None:
            pdays: dict[int, tuple[Any, ...]] = {}
            sim_box: list[Any] = [None, 0]
            mole_id = proto._world.mole

            def _get_passive_day(
                target_d: int,
                _tier: str = tier,
                _seed: int = seed,
                _pdays: dict[int, tuple[Any, ...]] = pdays,
                _box: list[Any] = sim_box,
                _mole: str = mole_id,
            ) -> tuple[Any, ...]:
                got_p = _pdays.get(target_d)
                if got_p is not None:
                    return got_p
                s_env = _box[0]
                if s_env is None:
                    s_prov = _ReplayTemplateProvider(
                        need_messages=False,
                        need_interview_text=False,
                        need_logs=True,
                        need_future_rng=True,
                    )
                    s_env = _make_replay_env(_tier, _seed, s_prov)
                    s_env._world_diverged = True
                    _box[0] = s_env
                cur_done = int(_box[1])
                while cur_done < target_d:
                    d_sim = cur_done + 1
                    b_docs = len(s_env.docs)
                    b_feed = len(s_env._feed)
                    s_env._t_advance_day({})
                    lk = dict(s_env._feed[-1]) if len(s_env._feed) > b_feed else None
                    lgs = tuple(s_env._by_day_ref.get(d_sim, ()))
                    mlc = sum(1 for r in lgs if r["employee"] == _mole)
                    rst = s_env._dyn.getstate()
                    ndocs = tuple(
                        dict(x, recipients=list(x["recipients"])) for x in s_env.docs[b_docs:]
                    )
                    ndids = tuple(x["doc_id"] for x in ndocs)
                    _pdays[d_sim] = (lk, lgs, mlc, rst, ndocs, ndids)
                    cur_done = d_sim
                _box[1] = cur_done
                return _pdays[target_d]

            cached = (
                proto,
                emp_facts,
                emp_list_res,
                emp_dept_map,
                decoy_mood,
                others_base,
                exp_consts,
                _get_passive_day,
            )
            _BASE_ENV_CACHE[ckey] = cached
    proto, emp_facts, emp_list_res, emp_dept_map, decoy_mood, others_base, exp_consts, get_passive_day = cached
    w = proto._world
    env = Env.__new__(Env)
    env.tier = tier
    env.seed = seed
    env.p = proto.p
    env._world = w
    env._dyn = random.Random(w.world_seed ^ 1)
    env.provider = provider
    env._ids = list(proto._ids)
    env._idset = proto._idset
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
    logs_by_day: dict[int, Any] = {}
    env._by_day_ref = logs_by_day
    env._mole_log_count = 0
    env._world_diverged = get_passive_day is None
    env._passive_rng_day = 0
    env._messages = {}
    env._msg_order = []
    env._history = []
    env._ledger = []
    env._canary_ids = []
    env._last_leak_day = 0
    env._log = _noop_log
    exp_m_m, exp_m_b, exp_m_f = exp_consts
    n_others = len(others_base)
    k_others = n_others.bit_length()

    def _fast_facts(
        d: int,
        _w: Any = w,
        _tier: str = tier,
        _emps: tuple[EmployeeFacts, ...] = emp_facts,
        _mood: str = decoy_mood,
        _env: Env = env,
        _prov: _ReplayTemplateProvider = provider,
    ) -> PublicDayFacts:
        if not _prov.need_messages and not _prov.need_interview_text:
            return _DUMMY_FACTS
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

    def _fast_list_employees(_a: dict[str, Any], _res: ToolResult = emp_list_res) -> ToolResult:
        return _res

    def _fast_list_documents(a: dict[str, Any], _env: Env = env) -> ToolResult:
        lo, hi = a.get("day_from", 1), a.get("day_to", _env.day)
        return ToolResult(True, {"documents": [x for x in _env.docs if lo <= x["day"] <= hi]})

    def _fast_read_access_logs(
        a: dict[str, Any],
        _by_day: dict[int, list[dict[str, Any]]] = logs_by_day,
    ) -> ToolResult:
        emp = a.get("employee")
        lo, hi = a["day_from"], a["day_to"]
        if lo == hi:
            day_logs = _by_day.get(lo)
            if not day_logs:
                return ToolResult(True, {"logs": []})
            if emp is None:
                return ToolResult(True, {"logs": list(day_logs)})
            return ToolResult(True, {"logs": [r for r in day_logs if r["employee"] == emp]})
        out: list[dict[str, Any]] = []
        for d_i in range(lo, hi + 1):
            day_logs = _by_day.get(d_i)
            if day_logs:
                if emp is None:
                    out.extend(day_logs)
                else:
                    out.extend(r for r in day_logs if r["employee"] == emp)
        return ToolResult(True, {"logs": out})

    def _fast_check_leak_feed(_a: dict[str, Any], _env: Env = env) -> ToolResult:
        d_now = _env.day
        return ToolResult(True, {"items": [f for f in _env._feed if f["surfaced_day"] <= d_now]})

    def _fast_interview(
        a: dict[str, Any],
        _env: Env = env,
        _prov: _ReplayTemplateProvider = provider,
        _tier: str = tier,
        _w: Any = w,
        _depts: dict[str, str] = emp_dept_map,
    ) -> ToolResult:
        emp, topic = a["employee"], a["topic"]
        if topic not in _IV_TOPICS:
            return ToolResult(False, {"detail": f"topic must be one of {list(_IV_TOPICS)}"}, "invalid arguments")
        if not _prov.need_interview_text:
            return ToolResult(True, {"employee": emp, "topic": topic, "answer": ""})
        d_now = _env.day
        first_any: str | None = None
        doc_title: str | None = None
        docs_now = _env.docs
        i_doc = len(docs_now) - 1
        while i_doc >= 0 and docs_now[i_doc]["day"] == d_now:
            i_doc -= 1
        for j_doc in range(i_doc + 1, len(docs_now)):
            x = docs_now[j_doc]
            if first_any is None:
                first_any = x["title"]
            if emp in x["recipients"]:
                doc_title = x["title"]
                break
        if doc_title is None:
            doc_title = first_any if first_any is not None else "the latest team brief"
        is_m = emp == _w.mole
        ikey = (_tier, _w.world_seed, d_now, emp, topic, is_m, doc_title)
        got = _IV_RES_CACHE.get(ikey)
        if got is None:
            p_ev = _env.p.p_evasive_innocent * (_env.p.interview_lr if is_m else 1.0)
            r = random.Random(f"{_w.world_seed}:iv:{emp}:{topic}:{d_now}")
            signal = "evasive" if r.random() < p_ev else "cooperative"
            trng = random.Random(f"text:{_tier}:{_w.world_seed}:{d_now}:{emp}:{topic}")
            ans = _iv_fill(
                trng,
                trng.choice(_IV_ANSWERS[(topic, signal)]),
                doc=doc_title,
                dept=_depts.get(emp, "my team"),
            )
            got = ToolResult(True, {"employee": emp, "topic": topic, "answer": ans})
            if len(_IV_RES_CACHE) >= 16384:
                _IV_RES_CACHE.clear()
            _IV_RES_CACHE[ikey] = got
        return got

    def _fast_advance_day(
        _args: dict[str, Any],
        _env: Env = env,
        _prov: _ReplayTemplateProvider = provider,
        _others: tuple[str, ...] = others_base,
        _by_day: dict[int, Any] = logs_by_day,
        _lm: float = exp_m_m,
        _lb: float = exp_m_b,
        _lf: float = exp_m_f,
        _no: int = n_others,
        _ko: int = k_others,
        _get_pday: Any = get_passive_day,
    ) -> ToolResult:
        p, w_obj, d = _env.p, _env._world, _env.day
        held_map = _env._held
        doc_by_id = _env._doc_by_id
        if not _env._world_diverged and _get_pday is not None:
            lk_item, lgs_d, mlc_d, _rst, ndocs_d, ndids_d = _get_pday(d)
            if lk_item is not None:
                _env._leaked.add(lk_item["doc_id"])
                _env._feed.append(dict(lk_item))
                _env._charge(p.leak_damage)
                _env._last_leak_day = d
            if _prov.need_logs:
                _by_day[d] = lgs_d
                _env._logs.extend(lgs_d)
            elif _prov.count_mole_logs_only:
                _env._mole_log_count += mlc_d
            _env._passive_rng_day = d
            if _prov.need_messages:
                for m in _prov.day_messages(_env._facts(d)):
                    m_copy = dict(m)
                    if m_copy["id"] not in _env._messages:
                        _env._messages[m_copy["id"]] = m_copy
                        _env._msg_order.append(m_copy["id"])
            if d >= p.n_days:
                _env._end("horizon")
                return ToolResult(True, {"closed_day": d, "episode_over": True})
            next_d = d + 1
            _env.day = next_d
            _env._actions_today = 0
            _env._canaries_today = 0
            docs_list = _env.docs
            for nd in ndocs_d:
                nd_copy = dict(nd, recipients=list(nd["recipients"]))
                docs_list.append(nd_copy)
                doc_by_id[nd_copy["doc_id"]] = nd_copy
                for r in nd_copy["recipients"]:
                    held_map[r].append(nd_copy["doc_id"])
            return ToolResult(
                True,
                {
                    "closed_day": d,
                    "day": next_d,
                    "V": _env.visible_V(),
                    "new_documents": list(ndids_d),
                },
            )
        rng = _env._dyn
        rand = rng.random
        gb = rng.getrandbits
        mole = w_obj.mole
        decoy = w_obj.decoy
        if w_obj.mole_strategy is None:
            lo = d - p.leak_window_days + 1
            leaked_set = _env._leaked
            leakable = [
                doc_by_id[x]
                for x in held_map[mole]
                if x not in leaked_set and lo <= doc_by_id[x]["day"] <= d
            ]
            leak: str | None = None
            if leakable and rand() < p.p_leak:
                if p.careful_mole:
                    n_emp = p.n_employees
                    w_sel = [
                        1.0 - len(x["recipients"]) / n_emp if x["is_canary"] else 1.0
                        for x in leakable
                    ]
                    if sum(w_sel) > 0:
                        leak = rng.choices([x["doc_id"] for x in leakable], weights=w_sel)[0]
                else:
                    leak = rng.choices([x["doc_id"] for x in leakable], weights=[1.0] * len(leakable))[0]
            frame_tgt: str | None = None
        else:
            dec = _env._mole_decide(_env._mole_view(d))
            leak = dec.get("leak")
            frame_tgt = dec.get("frame")
        if leak is not None:
            doc = doc_by_id[leak]
            delta = rng.choice(p.delay_choices)
            item: dict[str, Any] = {"surfaced_day": d + delta, "doc_id": leak, "title": doc["title"]}
            if doc["is_canary"]:
                true_v = next(k for k, v in doc["variants"].items() if mole in v)
                others_v = sorted(k for k in doc["variants"] if k != true_v)
                if p.fingerprint_accuracy < 1.0 and others_v and rand() >= p.fingerprint_accuracy:
                    item["variant"] = rng.choice(others_v)
                else:
                    item["variant"] = true_v
            _env._leaked.add(leak)
            _env._feed.append(item)
            _env._charge(p.leak_damage)
            _env._last_leak_day = d
        if _env._restricted:
            _env._cost(p.restrict_cost_per_day * len(_env._restricted))
        if _prov.need_logs:
            ah_m, ah_b = p.p_after_hours_mole, p.p_after_hours_benign
            logs: list[dict[str, Any]] = []
            for emp_id in _env._ids:
                held = held_map[emp_id]
                nh = len(held)
                if not nh:
                    continue
                is_m = emp_id == mole
                L = _lm if is_m else _lb
                if L < 1.0:
                    prod = rand()
                    cnt = 0
                    while prod > L:
                        cnt += 1
                        prod *= rand()
                    if cnt:
                        p_ah = ah_m if is_m else ah_b
                        kh = nh.bit_length()
                        for _ in range(cnt):
                            ri = gb(kh)
                            while ri >= nh:
                                ri = gb(kh)
                            logs.append(
                                {
                                    "day": d,
                                    "employee": emp_id,
                                    "doc_id": held[ri],
                                    "after_hours": rand() < p_ah,
                                }
                            )
            if p.framing and _lf < 1.0:
                f_share = p.framing_decoy_share
                prod = rand()
                fcnt = 0
                while prod > _lf:
                    fcnt += 1
                    prod *= rand()
                for _ in range(fcnt):
                    if decoy is not None and rand() < f_share:
                        tgt = decoy
                    else:
                        ri = gb(_ko)
                        while ri >= _no:
                            ri = gb(_ko)
                        tgt = _others[ri]
                    th = held_map[tgt]
                    nth = len(th)
                    if nth:
                        kth = nth.bit_length()
                        ri = gb(kth)
                        while ri >= nth:
                            ri = gb(kth)
                        logs.append(
                            {
                                "day": d,
                                "employee": tgt,
                                "doc_id": th[ri],
                                "after_hours": True,
                            }
                        )
            tgt = frame_tgt
            if tgt is not None and tgt in _env._idset and tgt != mole and held_map[tgt]:
                th = held_map[tgt]
                nth = len(th)
                kth = nth.bit_length()
                ri = gb(kth)
                while ri >= nth:
                    ri = gb(kth)
                logs.append(
                    {
                        "day": d,
                        "employee": tgt,
                        "doc_id": th[ri],
                        "after_hours": True,
                    }
                )
            logs.sort(key=lambda r: (r["employee"], r["doc_id"], r["after_hours"]))
            _by_day[d] = logs
            _env._logs.extend(logs)
        elif _prov.need_future_rng or _prov.count_mole_logs_only:
            count_mole = _prov.count_mole_logs_only
            for emp_id in _env._ids:
                held = held_map[emp_id]
                nh = len(held)
                if not nh:
                    continue
                is_m = emp_id == mole
                L = _lm if is_m else _lb
                if L < 1.0:
                    prod = rand()
                    cnt = 0
                    while prod > L:
                        cnt += 1
                        prod *= rand()
                    if cnt:
                        kh = nh.bit_length()
                        for _ in range(cnt):
                            ri = gb(kh)
                            while ri >= nh:
                                ri = gb(kh)
                            rand()
                        if count_mole and is_m:
                            _env._mole_log_count += cnt
            if p.framing and _lf < 1.0:
                f_share = p.framing_decoy_share
                prod = rand()
                fcnt = 0
                while prod > _lf:
                    fcnt += 1
                    prod *= rand()
                for _ in range(fcnt):
                    if decoy is not None and rand() < f_share:
                        tgt = decoy
                    else:
                        ri = gb(_ko)
                        while ri >= _no:
                            ri = gb(_ko)
                        tgt = _others[ri]
                    nth = len(held_map[tgt])
                    if nth:
                        kth = nth.bit_length()
                        ri = gb(kth)
                        while ri >= nth:
                            ri = gb(kth)
            tgt = frame_tgt
            if tgt is not None and tgt in _env._idset and tgt != mole:
                nth = len(held_map[tgt])
                if nth:
                    kth = nth.bit_length()
                    ri = gb(kth)
                    while ri >= nth:
                        ri = gb(kth)
        if _prov.need_messages:
            for m in _prov.day_messages(_env._facts(d)):
                m_copy = dict(m)
                if m_copy["id"] not in _env._messages:
                    _env._messages[m_copy["id"]] = m_copy
                    _env._msg_order.append(m_copy["id"])
        if d >= p.n_days:
            _env._end("horizon")
            return ToolResult(True, {"closed_day": d, "episode_over": True})
        next_d = d + 1
        _env.day = next_d
        _env._actions_today = 0
        _env._canaries_today = 0
        restr = _env._restricted
        new_doc_ids: list[str] = []
        docs_list = _env.docs
        for raw in w_obj.planned_docs.get(next_d, ()):
            did = raw["doc_id"]
            recips = [r for r in raw["recipients"] if r not in restr] if restr else list(raw["recipients"])
            ndoc = {
                "doc_id": did,
                "title": raw["title"],
                "day": next_d,
                "recipients": recips,
                "is_canary": False,
            }
            docs_list.append(ndoc)
            doc_by_id[did] = ndoc
            for r in recips:
                held_map[r].append(did)
            new_doc_ids.append(did)
        return ToolResult(
            True,
            {
                "closed_day": d,
                "day": next_d,
                "V": _env.visible_V(),
                "new_documents": new_doc_ids,
            },
        )

    def _sync_diverged_rng(
        _env: Env = env,
        _get_pday: Any = get_passive_day,
    ) -> None:
        _env._world_diverged = True
        pday_idx = _env._passive_rng_day
        if pday_idx > 0 and _get_pday is not None:
            _env._dyn.setstate(_get_pday(pday_idx)[3])

    env._sync_diverged_rng = _sync_diverged_rng
    env._facts = _fast_facts
    env._t_list_employees = _fast_list_employees
    env._t_list_documents = _fast_list_documents
    env._t_read_access_logs = _fast_read_access_logs
    env._t_check_leak_feed = _fast_check_leak_feed
    env._t_interview = _fast_interview
    env._t_advance_day = _fast_advance_day
    return env


def _replay_env_step(env: Env, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if not getattr(env, "_world_diverged", True) and (
        tool == "plant_canary" or tool == "restrict_access"
    ):
        env._sync_diverged_rng()
    if args.__class__ is dict and not args:
        if tool == "advance_day":
            res = env._t_advance_day(args)
        elif tool == "status":
            res = env._t_status(args)
        elif tool == "list_employees":
            res = env._t_list_employees(args)
        elif tool == "list_documents":
            res = env._t_list_documents(args)
        elif tool == "check_leak_feed" and env._actions_today < env.p.actions_per_day:
            res = env._t_check_leak_feed(args)
            env._actions_today += 1
        else:
            res = env._dispatch(tool, args)
    else:
        res = env._dispatch(tool, args)
    env._history.append(None)
    if not env.done and len(env._history) >= env.p.tool_call_cap:
        env._end("tool_cap")
    return {"ok": res.ok, "data": res.data, "error": res.error}


def _load_indexed_pool(
    pool_dir: Path,
    pool_rel_prefix: str,
) -> list[tuple[str, dict[str, Any]]]:
    if not pool_dir.exists():
        return []
    resolved = pool_dir.resolve()
    files: list[tuple[Path, tuple[str, ...]]] = []
    for f in sorted(resolved.rglob("episodes.jsonl")):
        rel_parts = f.relative_to(resolved).parts[:-1]
        if any(x == "superseded" or x.startswith("v1.") or x.endswith("-smoke") for x in rel_parts):
            continue
        files.append((f, rel_parts))
    sig = tuple(
        (str(f), st.st_mtime_ns, st.st_size)
        for f, _ in files
        for st in (f.stat(),)
    )
    cache_key = (str(resolved), pool_rel_prefix, sig)
    cached = _POOL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rows: list[tuple[str, dict[str, Any]]] = []
    for f, rel_parts in files:
        rel_dir = "/".join((pool_rel_prefix, *rel_parts)) if rel_parts else pool_rel_prefix
        run_id = f.parent.name
        nonempty = [ln for ln in f.read_bytes().splitlines() if ln.strip()]
        if not nonempty:
            continue
        try:
            parsed_eps = _fast_json_loads(b"[" + b",".join(nonempty) + b"]")
        except ValueError:
            parsed_eps = [_fast_json_loads(ln) for ln in nonempty]
        for ep in parsed_eps:
            meta = ep.get("meta") or {}
            if meta.get("valid") is False:
                continue
            ep["meta"] = {**meta, "run_id": run_id}
            rows.append((rel_dir, ep))
    if len(_POOL_CACHE) >= 12:
        _POOL_CACHE.clear()
    _POOL_CACHE[cache_key] = rows
    return rows


def load_runs(root: str | Path = "data/runs") -> list[dict[str, Any]]:
    root_path = Path(root)
    return [ep for _, ep in _load_indexed_pool(root_path, "")]

MAX_JSON_BYTES = 45_000
EXPECTED_COMMITTED_V14_EPISODES = 472
EXPECTED_REPLICATION_V14_EPISODES = 305
EXPECTED_COMBINED_V14_EPISODES = 777

ENV_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "read_access_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "check_leak_feed",
    "plant_canary",
    "interview",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)

_OC_TRUNC_RE = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+The tool call succeeded but the output was "
    r"truncated\. Full output saved to: "
)
_OC_NO_TOOL_PREFIX = "Model tried to call unavailable tool"

MOLE_ARCHETYPES: tuple[str, ...] = (
    "decoy_entangled",
    "deep_crowd_camouflage",
    "low_tempo_stealth",
    "high_tempo_exposed",
)

DEPT_STRATA: tuple[str, ...] = (
    "compact_dept",
    "standard_dept",
    "crowded_dept",
)

SOLVER_DIFFICULTY_STRATA: tuple[str, ...] = (
    "fast_isolation",
    "mid_horizon_isolation",
    "late_or_stalled_isolation",
)

SEED_PROFILE_COLUMNS: tuple[str, ...] = (
    "seed",
    "mole_id",
    "decoy_id",
    "mole_dept",
    "mole_dept_size",
    "mole_clearance",
    "clearance_peer_count",
    "same_dept_decoy",
    "decoy_doc_overlap_count",
    "decoy_doc_overlap_share",
    "mole_planned_docs",
    "mole_doc_share",
    "realized_doc_access_density",
    "passive_leak_count",
    "dept_narrow_day",
    "solver_accuse_day",
    "solver_final_day",
    "solver_score",
    "solver_post_expected",
    "solver_correct",
    "mole_archetype",
    "dept_stratum",
    "solver_difficulty_stratum",
)

SEED_PROFILE_ENUMS: dict[str, tuple[str, ...]] = {
    "mole_archetype": MOLE_ARCHETYPES,
    "dept_stratum": DEPT_STRATA,
    "solver_difficulty_stratum": SOLVER_DIFFICULTY_STRATA,
}

STRATUM_METRIC_COLUMNS: tuple[str, ...] = (
    "n",
    "raw",
    "luck",
    "acc",
    "abst",
    "day",
    "s_raw",
    "s_luck",
    "r_gap",
    "l_gap",
    "ratio",
)


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "mole_stratified_gap.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_mole_stratified_gap_v14.md"


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    if not gap_md.exists():
        return False
    return "gemini-3.5-flash" in gap_md.read_text(encoding="utf-8")


def _r(val: float | None, nd: int = 5) -> float | None:
    if val is None or math.isnan(val) or math.isinf(val):
        return None
    return round(float(val), nd)


def clean_json(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 5)
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = 1e-5) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def norm_result(want: Any) -> Any:
    if isinstance(want, dict) and isinstance(want.get("error"), str) and want["error"].startswith("{"):
        try:
            inner = json.loads(want["error"])
        except ValueError:
            return want
        if isinstance(inner, dict) and {"ok", "data", "error"} <= set(inner):
            return inner
    return want


def client_truncated_bytes(want: Any) -> int | None:
    if isinstance(want, dict) and set(want) == {"raw"} and isinstance(want["raw"], str):
        m = _OC_TRUNC_RE.match(want["raw"])
        if m:
            return int(m.group(1))
    return None


def is_client_only_step(step: dict[str, Any]) -> bool:
    res = step.get("result")
    return (
        step.get("tool") not in ENV_TOOLS
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith(_OC_NO_TOOL_PREFIX)
    )


def step_result_matches(raw_recorded: Any, replayed: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    flags = {
        "unwrapped_mcp_error": False,
        "detail_normalized": False,
        "truncated_checked": False,
    }
    trunc = client_truncated_bytes(raw_recorded)
    if trunc is not None:
        flags["truncated_checked"] = True
        return len(json.dumps(replayed).encode("utf-8")) == trunc, flags
    rec = norm_result(raw_recorded)
    if rec is not raw_recorded:
        flags["unwrapped_mcp_error"] = True
    if rec is None:
        return True, flags
    rep = replayed
    if (
        isinstance(rep, dict)
        and rep.get("ok") is False
        and isinstance(rep.get("data"), dict)
        and set(rep["data"]) == {"detail"}
        and isinstance(rec, dict)
        and not ("detail" in (rec.get("data") or {}))
    ):
        rep = {"ok": False, "data": {}, "error": rep.get("error")}
        flags["detail_normalized"] = True
    matched = rep == rec or _canon(rep) == _canon(rec)
    return matched, flags


def is_clean_non_accuse_rc0_exit(ep: dict[str, Any], env_done: bool | None = None) -> bool:
    meta = ep.get("meta") or {}
    done_ok = True if env_done is None else (not env_done)
    rc = meta.get("rc")
    fday = ep.get("final_day")
    end_reason = str(ep.get("end_reason") or "").lower()
    return (
        done_ok
        and meta.get("valid") is not False
        and not isinstance(rc, bool)
        and rc == 0
        and meta.get("error") is None
        and "timeout" not in end_reason
        and ep.get("accused") is None
        and not bool(ep.get("correct"))
        and abs(float(ep.get("score") if ep.get("score") is not None else 1.0)) < 1e-9
        and not isinstance(fday, bool)
        and fday == 0
    )


def replay_and_verify_episode(ep: dict[str, Any]) -> dict[str, Any]:
    steps = ep.get("steps") or []
    last_msg_idx = -1
    last_log_idx = -1
    last_adv_idx = -1
    for i, st_i in enumerate(steps):
        tl = st_i.get("tool")
        if tl == "read_message":
            last_msg_idx = i
        elif tl == "search_messages" and st_i.get("result") is not None:
            last_msg_idx = i
        elif tl == "read_access_logs" and st_i.get("result") is not None:
            last_log_idx = i
        elif tl == "advance_day":
            last_adv_idx = i
    prov = _ReplayTemplateProvider(
        need_messages=last_msg_idx >= 0,
        need_interview_text=True,
        need_logs=last_log_idx >= 0,
        need_future_rng=last_adv_idx >= 0,
    )
    env = _make_replay_env(str(ep["tier"]), int(ep["seed"]), prov)
    step_mismatches = 0
    first_bad_step: int | None = None
    unwrapped_mcp_error_steps = 0
    detail_normalized_steps = 0
    truncated_steps_verified = 0
    client_only_steps = 0
    for idx, st in enumerate(steps):
        if idx > last_msg_idx:
            prov.need_messages = False
        if idx > last_log_idx:
            prov.need_logs = False
        prov.need_future_rng = idx < last_adv_idx
        raw_res = st.get("result")
        prov.need_interview_text = raw_res is not None
        if is_client_only_step(st):
            client_only_steps += 1
            continue
        if env.done:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
            continue
        tname = str(st.get("tool"))
        if tname not in ENV_TOOLS:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
            continue
        got_payload = _replay_env_step(env, tname, st.get("args") or {})
        if raw_res is None:
            ok_step = True
        elif isinstance(raw_res, dict) and raw_res.get("ok") is True:
            ok_step = raw_res == got_payload or _canon(got_payload) == _canon(raw_res)
        else:
            ok_step, flags = step_result_matches(raw_res, got_payload)
            if flags["unwrapped_mcp_error"]:
                unwrapped_mcp_error_steps += 1
            if flags["detail_normalized"]:
                detail_normalized_steps += 1
            if flags["truncated_checked"] and ok_step:
                truncated_steps_verified += 1
        if not ok_step:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
    res = env.result("replay")
    rec_day = int(ep.get("final_day") or 0)
    clean_zero_day = is_clean_non_accuse_rc0_exit(ep, env_done=env.done)
    day_ok = (int(res.final_day) == rec_day) or clean_zero_day
    score_ok = (
        abs(float(res.score) - float(ep["score"])) < 1e-9
        and res.accused == ep.get("accused")
        and bool(res.correct) == bool(ep.get("correct"))
        and day_ok
    )
    return {
        "ok": score_ok and step_mismatches == 0,
        "score_ok": score_ok,
        "clean_zero_day_exit": clean_zero_day,
        "replay_score": float(res.score),
        "replay_accused": res.accused,
        "replay_correct": bool(res.correct),
        "replay_final_day": int(res.final_day),
        "step_mismatches": step_mismatches,
        "first_bad_step": first_bad_step,
        "unwrapped_mcp_error_steps": unwrapped_mcp_error_steps,
        "detail_normalized_steps": detail_normalized_steps,
        "truncated_steps_verified": truncated_steps_verified,
        "client_only_steps": client_only_steps,
    }


def verify_episode_pool(episodes: list[dict[str, Any]], pool_name: str) -> dict[str, Any]:
    seen: set[tuple[str, str, int]] = set()
    duplicates: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    total_step_mismatches = 0
    total_unwrapped = 0
    total_detail_norm = 0
    total_truncated = 0
    total_client_only = 0
    clean_zero_day_seeds: list[int] = []
    for ep in episodes:
        key = (str(ep["agent"]), str(ep["tier"]), int(ep["seed"]))
        if key in seen:
            duplicates.append({"pool": pool_name, "agent": key[0], "tier": key[1], "seed": key[2]})
        seen.add(key)
        rep = replay_and_verify_episode(ep)
        total_step_mismatches += int(rep["step_mismatches"])
        total_unwrapped += int(rep["unwrapped_mcp_error_steps"])
        total_detail_norm += int(rep["detail_normalized_steps"])
        total_truncated += int(rep["truncated_steps_verified"])
        total_client_only += int(rep["client_only_steps"])
        if rep["clean_zero_day_exit"]:
            clean_zero_day_seeds.append(key[2])
        if not rep["ok"]:
            mismatches.append(
                {
                    "pool": pool_name,
                    "agent": key[0],
                    "tier": key[1],
                    "seed": key[2],
                    "recorded_score": ep["score"],
                    "replay_score": rep["replay_score"],
                    "recorded_accused": ep.get("accused"),
                    "replay_accused": rep["replay_accused"],
                    "recorded_final_day": ep.get("final_day"),
                    "replay_final_day": rep["replay_final_day"],
                    "step_mismatches": rep["step_mismatches"],
                    "first_bad_step": rep["first_bad_step"],
                }
            )
    if duplicates:
        raise ValueError(f"duplicate episodes in {pool_name}: {duplicates}")
    if mismatches:
        raise ValueError(f"replay mismatches in {pool_name}: {mismatches}")
    return {
        "pool": pool_name,
        "total": len(episodes),
        "verified": len(episodes),
        "mismatches": 0,
        "step_mismatches": total_step_mismatches,
        "duplicates": 0,
        "pre_1bc3e281_detail_normalized_steps": total_detail_norm,
        "unwrapped_mcp_error_steps": total_unwrapped,
        "truncated_output_steps_verified": total_truncated,
        "client_only_steps": total_client_only,
        "clean_rc0_non_accuse_zero_day_seeds": sorted(clean_zero_day_seeds),
    }


def _tier_mole_genome(tier: str) -> dict[str, Any]:
    tp = tier_params(tier)
    n_depts = 5 if tier in ("hard", "hard_forge") else 4
    mean_dept = int(tp.n_employees) // n_depts
    return clean_json(
        {
            "tier": tier,
            "is_judge_track": tier in TRACKS,
            "mole_policy_name": DEFAULT_STRATEGY.name,
            "mole_dsl_rule_count": len(DEFAULT_STRATEGY.rules),
            "mole_dsl_default_leak_selector": DEFAULT_STRATEGY.default[0],
            "mole_dsl_default_frame_selector": DEFAULT_STRATEGY.default[1],
            "n_employees": int(tp.n_employees),
            "n_depts": n_depts,
            "mean_dept_size": float(tp.n_employees) / float(n_depts),
            "crowd_dept_threshold": mean_dept + 2,
            "n_days": int(tp.n_days),
            "p_leak": float(tp.p_leak),
            "expected_passive_leaks": float(tp.n_days) * float(tp.p_leak),
            "delay_choices": list(tp.delay_choices),
            "leak_window_days": int(tp.leak_window_days),
            "careful_mole": bool(tp.careful_mole),
            "fingerprint_accuracy": float(tp.fingerprint_accuracy),
            "decoy": bool(tp.decoy),
            "framing": bool(tp.framing),
            "framing_rate": float(tp.framing_rate),
            "framing_decoy_share": float(tp.framing_decoy_share),
            "log_rate_benign": float(tp.log_rate_benign),
            "log_rate_mole": float(tp.log_rate_mole),
            "p_after_hours_benign": float(tp.p_after_hours_benign),
            "p_after_hours_mole": float(tp.p_after_hours_mole),
            "access_constraints": bool(tp.access_constraints),
            "p_single_dept_recipients": float(tp.p_single_dept_recipients),
            "canaries_per_day": int(tp.canaries_per_day),
            "max_variants": int(tp.max_variants),
        }
    )


def classify_mole_archetype(
    tier: str,
    same_dept_decoy: bool,
    mole_dept_size: int,
    passive_leak_count: int,
) -> str:
    tp = tier_params(tier)
    n_depts = 5 if tier in ("hard", "hard_forge") else 4
    crowd_threshold = (int(tp.n_employees) // n_depts) + 2
    expected_leaks = float(tp.n_days) * float(tp.p_leak)
    if same_dept_decoy:
        return "decoy_entangled"
    if mole_dept_size >= crowd_threshold:
        return "deep_crowd_camouflage"
    if float(passive_leak_count) < expected_leaks:
        return "low_tempo_stealth"
    return "high_tempo_exposed"


def classify_dept_stratum(tier: str, mole_dept_size: int) -> str:
    if tier == "medium":
        if mole_dept_size <= 4:
            return "compact_dept"
        if mole_dept_size <= 6:
            return "standard_dept"
        return "crowded_dept"
    if mole_dept_size <= 8:
        return "compact_dept"
    if mole_dept_size <= 10:
        return "standard_dept"
    return "crowded_dept"


def classify_solver_difficulty(tier: str, solver_final_day: int) -> str:
    if tier == "medium":
        if solver_final_day <= 6:
            return "fast_isolation"
        if solver_final_day <= 9:
            return "mid_horizon_isolation"
        return "late_or_stalled_isolation"
    if solver_final_day <= 8:
        return "fast_isolation"
    if solver_final_day <= 12:
        return "mid_horizon_isolation"
    return "late_or_stalled_isolation"


def _extract_passive_world_profile(tier: str, seed: int) -> dict[str, Any]:
    wkey = (TIERS_VERSION, str(tier), int(seed))
    cached = _WORLD_PASSIVE_CACHE.get(wkey)
    if cached is not None:
        return cached

    prov = _ReplayTemplateProvider(
        need_messages=False,
        need_interview_text=False,
        need_logs=False,
        need_future_rng=True,
        count_mole_logs_only=True,
    )
    env = _make_replay_env(str(tier), int(seed), prov)
    w = env._world
    tp = env.p
    strat_obj = w.mole_strategy if w.mole_strategy is not None else DEFAULT_STRATEGY
    mole_policy = str(getattr(strat_obj, "name", "default_v0"))

    emp_map = {e.id: e for e in w.employees}
    m_emp = emp_map[w.mole]
    d_emp = emp_map[w.decoy] if w.decoy is not None else None
    dept_emps = [e for e in w.employees if e.dept == m_emp.dept]
    mole_dept_size = len(dept_emps)
    same_dept_decoy = bool(d_emp is not None and d_emp.dept == m_emp.dept)
    mole_clearance = int(m_emp.clearance) if m_emp.clearance is not None else None
    if tp.access_constraints:
        clearance_peer_count = sum(
            1 for e in dept_emps if e.id != w.mole and e.clearance == m_emp.clearance
        )
    else:
        clearance_peer_count = mole_dept_size - 1

    all_docs = [doc for day_docs in w.planned_docs.values() for doc in day_docs]
    mole_docs = [doc for doc in all_docs if w.mole in doc["recipients"]]
    decoy_overlap = (
        sum(1 for doc in mole_docs if w.decoy in doc["recipients"])
        if w.decoy is not None
        else 0
    )
    decoy_overlap_share = (decoy_overlap / len(mole_docs)) if mole_docs else 0.0
    mole_doc_share = (len(mole_docs) / len(all_docs)) if all_docs else 0.0

    while not env.done:
        _replay_env_step(env, "advance_day", {})

    mole_log_count = int(env._mole_log_count)
    realized_doc_access_density = float(mole_log_count) / float(tp.n_days)
    passive_leak_count = len(env._feed)

    cand = set(w.ids)
    dept_narrow_day = int(tp.n_days) + 1
    for d in range(1, int(tp.n_days) + 1):
        for item in env._feed:
            if int(item["surfaced_day"]) <= d:
                cand &= set(env._doc_by_id[item["doc_id"]]["recipients"])
        if len(cand) == mole_dept_size:
            dept_narrow_day = d
            break

    mole_arch = classify_mole_archetype(
        tier=tier,
        same_dept_decoy=same_dept_decoy,
        mole_dept_size=mole_dept_size,
        passive_leak_count=passive_leak_count,
    )
    dept_stratum = classify_dept_stratum(tier=tier, mole_dept_size=mole_dept_size)
    base_prof = {
        "seed": int(seed),
        "mole_policy": mole_policy,
        "mole_id": str(w.mole),
        "decoy_id": str(w.decoy) if w.decoy is not None else None,
        "mole_dept": str(m_emp.dept),
        "mole_dept_size": mole_dept_size,
        "mole_clearance": mole_clearance,
        "clearance_peer_count": clearance_peer_count,
        "same_dept_decoy": same_dept_decoy,
        "decoy_doc_overlap_count": decoy_overlap,
        "decoy_doc_overlap_share": decoy_overlap_share,
        "mole_planned_docs": len(mole_docs),
        "mole_doc_share": mole_doc_share,
        "realized_doc_access_density": realized_doc_access_density,
        "passive_leak_count": passive_leak_count,
        "dept_narrow_day": dept_narrow_day,
        "mole_archetype": mole_arch,
        "dept_stratum": dept_stratum,
    }
    _WORLD_PASSIVE_CACHE[wkey] = base_prof
    return base_prof


def extract_seed_profile(
    tier: str,
    seed: int,
    solver_ep: dict[str, Any],
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    sol_accused = solver_ep.get("accused")
    sol_final_day = int(solver_ep["final_day"])
    sol_accuse_day = sol_final_day if sol_accused is not None else None
    sol_score = float(solver_ep["score"])
    sol_pe = _eval_post_expected(solver_ep, pe_memo)
    sol_correct = bool(solver_ep.get("correct"))

    base_prof = _extract_passive_world_profile(tier, seed)
    sol_stratum = classify_solver_difficulty(tier=tier, solver_final_day=sol_final_day)
    return clean_json(
        {
            **base_prof,
            "solver_accuse_day": sol_accuse_day,
            "solver_final_day": sol_final_day,
            "solver_score": sol_score,
            "solver_post_expected": sol_pe,
            "solver_correct": sol_correct,
            "solver_difficulty_stratum": sol_stratum,
        }
    )


class _StepView:
    __slots__ = ("tool", "day", "args", "result")

    def __init__(self, d: dict[str, Any]) -> None:
        self.tool = d.get("tool", "")
        self.day = d.get("day", 0)
        self.args = d.get("args") or {}
        self.result = d.get("result")


def _fast_p_accused(ep: dict[str, Any]) -> float | None:
    steps = ep.get("steps") or []
    acc_idx = -1
    acc_emp: Any = None
    last_feed_idx = -1
    for i, st in enumerate(steps):
        tl = st.get("tool")
        if tl == "accuse":
            acc_idx = i
            acc_emp = (st.get("args") or {}).get("employee")
            break
        if tl == "check_leak_feed" and (st.get("result") or {}).get("ok", True):
            last_feed_idx = i
    if acc_idx < 0:
        return None
    sp = SolverPolicy(tier_params_for_episode(ep["tier"], steps[: acc_idx + 1]))
    obs = sp.obs
    o_docs = obs.docs
    beh_steps: list[dict[str, Any]] = []
    for i in range(acc_idx):
        s = steps[i]
        r = s.get("result") or {}
        if not r.get("ok", True):
            continue
        tl = s.get("tool")
        if tl == "check_leak_feed":
            if i == last_feed_idx:
                sp._ingest(_StepView(s))
            continue
        if tl == "read_access_logs":
            if obs.employees:
                beh_steps.append(s)
            else:
                sp._ingest(_StepView(s))
            continue
        if tl == "interview":
            beh_steps.append(s)
            continue
        if tl == "list_documents":
            data = r.get("data") or {}
            docs_raw = data.get("documents")
            if docs_raw is None:
                docs_raw = data.get("docs") or ()
            if isinstance(docs_raw, list):
                for d in docs_raw:
                    did = d["doc_id"]
                    is_can = bool(d.get("is_canary"))
                    if did in o_docs and not is_can:
                        continue
                    var = d.get("variants")
                    if isinstance(var, dict) and var and all(isinstance(v, list) for v in var.values()):
                        var = {e: lab for lab, es in var.items() for e in es}
                    prev_var = o_docs[did].variants if did in o_docs else None
                    o_docs[did] = Doc(
                        did,
                        int(d["day"]),
                        frozenset(d.get("recipients", ())),
                        is_can,
                        dict(var) if isinstance(var, dict) else prev_var,
                    )
            else:
                sp._ingest(_StepView(s))
            continue
        sp._ingest(_StepView(s))
    if not obs.employees:
        return None
    obs.leak_timing_known = sp.v_drops_reveal_leaks()
    P = sp.P
    bt, ct, nt = sp.behaviour_temper, sp.choice_temper, sp.noleak_temper
    emps = obs.employees
    decoy = obs.decoy

    seen_f: set[str] = set()
    uniq_items = []
    for it in sorted(obs.feed, key=lambda x: (x.surfaced_day, x.doc_id)):
        if it.doc_id not in seen_f:
            seen_f.add(it.doc_id)
            uniq_items.append(it)

    possible = set(emps)
    if decoy is not None:
        possible.discard(decoy)
    fp_acc = getattr(P, "fingerprint_accuracy", 1.0)
    surf_var_docs = []
    for it in uniq_items:
        doc = o_docs.get(it.doc_id)
        if doc is None:
            possible.clear()
            break
        possible &= doc.recipients
        if it.variant and doc.variants:
            surf_var_docs.append((it.doc_id, doc.variants))
            k = len(set(doc.variants.values()))
            if k <= 1 or fp_acc >= 1.0:
                possible = {s for s in possible if doc.variants.get(s) == it.variant}
            else:
                possible = {s for s in possible if doc.variants.get(s) is not None}

    if not possible:
        post = _fallback(obs)
        return round(post.get(acc_emp, 0.0), 3)

    if len(possible) == 1:
        only_s = next(iter(possible))
        if leak_loglik(obs, only_s, P, ct, nt) == -math.inf:
            post = _fallback(obs)
            return round(post.get(acc_emp, 0.0), 3)
        return 1.0 if only_s == acc_emp else 0.0

    if bt > 0 and beh_steps:
        for bs in beh_steps:
            sp._ingest(_StepView(bs))

    beh = behaviour_logliks(obs, P) if bt > 0 else {}
    iv_ll: dict[str, float] = {}
    if bt > 0 and obs.interviews:
        pe = P.p_evasive_innocent
        pm = min(0.999, pe * P.interview_lr)
        l_ev = math.log(pm / pe)
        l_co = math.log((1.0 - pm) / (1.0 - pe))
        for who, ev in obs.interviews:
            iv_ll[who] = iv_ll.get(who, 0.0) + (l_ev if ev else l_co)

    docs_list = list(o_docs.items())
    ll_cache: dict[Any, float] = {}
    logs: dict[str, float] = {}
    for s in emps:
        if s not in possible:
            logs[s] = -math.inf
            continue
        sig = (
            tuple(did for did, doc in docs_list if s in doc.recipients),
            tuple((did, vm.get(s)) for did, vm in surf_var_docs),
        )
        lp = ll_cache.get(sig)
        if lp is None:
            lp = leak_loglik(obs, s, P, ct, nt)
            ll_cache[sig] = lp
        if bt > 0 and lp > -math.inf:
            lp += bt * (beh[s] + iv_ll.get(s, 0.0))
        logs[s] = lp
    m = max(logs.values()) if logs else -math.inf
    if m == -math.inf:
        post = _fallback(obs)
    else:
        z = sum(math.exp(v - m) for v in logs.values())
        post = {s: math.exp(v - m) / z for s, v in logs.items()}
    return round(post.get(acc_emp, 0.0), 3)


def _eval_post_expected(ep: dict[str, Any], pe_memo: dict[int, float] | None = None) -> float:
    if pe_memo is not None and id(ep) in pe_memo:
        return pe_memo[id(ep)]
    if not ep.get("accused"):
        if pe_memo is not None:
            pe_memo[id(ep)] = 0.0
        return 0.0
    meta = ep.get("meta") or {}
    v_val = meta.get("V", meta.get("V_final"))
    if v_val is None:
        raise ValueError(f"missing V in meta on ({ep.get('tier')}, {ep.get('seed')})")
    steps = ep.get("steps")
    p_val: float | None
    if isinstance(steps, list):
        hit = _POSTERIOR_BY_STEPS.get(id(steps))
        if hit is not None and hit[0] is steps:
            p_val = hit[1]
        else:
            p_val = _fast_p_accused(ep)
            if len(_POSTERIOR_BY_STEPS) >= 4096:
                _POSTERIOR_BY_STEPS.clear()
            _POSTERIOR_BY_STEPS[id(steps)] = (steps, p_val)
    else:
        p_val = _fast_p_accused(ep)
    if p_val is None:
        raise ValueError(f"post_expected returned None on ({ep.get('tier')}, {ep.get('seed')})")
    val = float(p_val) * float(v_val) - (1.0 - float(p_val))
    if pe_memo is not None:
        pe_memo[id(ep)] = val
    return val


def pack_seed_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(profiles, key=lambda p: int(p["seed"]))
    policies = sorted({str(p["mole_policy"]) for p in ordered})
    if len(policies) != 1:
        raise ValueError(f"expected single mole_policy per tier block, got {policies}")
    rows: list[list[Any]] = []
    for p in ordered:
        row: list[Any] = []
        for col in SEED_PROFILE_COLUMNS:
            val = p[col]
            if col in SEED_PROFILE_ENUMS:
                val = SEED_PROFILE_ENUMS[col].index(str(val))
            row.append(val)
        rows.append(row)
    n = len(ordered)
    arch_counts = {k: sum(1 for p in ordered if p["mole_archetype"] == k) for k in MOLE_ARCHETYPES}
    dept_counts = {k: sum(1 for p in ordered if p["dept_stratum"] == k) for k in DEPT_STRATA}
    sol_counts = {
        k: sum(1 for p in ordered if p["solver_difficulty_stratum"] == k)
        for k in SOLVER_DIFFICULTY_STRATA
    }
    return clean_json(
        {
            "n_seeds": n,
            "mole_policy": policies[0],
            "mean_mole_dept_size": sum(float(p["mole_dept_size"]) for p in ordered) / n,
            "same_dept_decoy_count": sum(1 for p in ordered if p["same_dept_decoy"]),
            "mean_decoy_doc_overlap_count": sum(float(p["decoy_doc_overlap_count"]) for p in ordered) / n,
            "mean_mole_doc_share": sum(float(p["mole_doc_share"]) for p in ordered) / n,
            "mean_realized_doc_access_density": (
                sum(float(p["realized_doc_access_density"]) for p in ordered) / n
            ),
            "mean_passive_leak_count": sum(float(p["passive_leak_count"]) for p in ordered) / n,
            "mole_archetype_counts": arch_counts,
            "dept_stratum_counts": dept_counts,
            "solver_difficulty_counts": sol_counts,
            "rows": rows,
        }
    )


def unpack_seed_profiles(packed: dict[str, Any]) -> list[dict[str, Any]]:
    cols = packed.get("columns") or SEED_PROFILE_COLUMNS
    pol = packed.get("mole_policy", "default_v0")
    enums = packed.get("enums") or {k: list(v) for k, v in SEED_PROFILE_ENUMS.items()}
    out: list[dict[str, Any]] = []
    for r in packed["rows"]:
        d = dict(zip(cols, r))
        for col, names in enums.items():
            if col in d and isinstance(d[col], int):
                d[col] = names[d[col]]
        d.setdefault("mole_policy", pol)
        out.append(d)
    return out


def pack_stratum_metrics(metrics: dict[str, Any]) -> list[Any]:
    return clean_json([metrics[col] for col in STRATUM_METRIC_COLUMNS])


def unpack_stratum_metrics(entry: list[Any] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    if len(entry) != len(STRATUM_METRIC_COLUMNS):
        raise ValueError(f"expected {len(STRATUM_METRIC_COLUMNS)} stratum cols, got {len(entry)}")
    return dict(zip(STRATUM_METRIC_COLUMNS, entry))


def compute_stratum_metrics(
    episodes: list[dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    eps = sorted(episodes, key=lambda e: int(e["seed"]))
    n = len(eps)
    if n == 0:
        return clean_json(
            {
                "n": 0,
                "raw": None,
                "luck": None,
                "acc": None,
                "abst": None,
                "day": None,
                "s_raw": None,
                "s_luck": None,
                "r_gap": None,
                "l_gap": None,
                "ratio": None,
            }
        )
    seeds = [int(e["seed"]) for e in eps]
    if len(set(seeds)) != n:
        raise ValueError(f"duplicate seeds in stratum: {seeds}")
    missing = [s for s in seeds if s not in solver_by_seed]
    if missing:
        raise ValueError(f"missing paired solver seeds: {missing}")

    f_raw = [float(e["score"]) for e in eps]
    s_raw = [float(solver_by_seed[s]["score"]) for s in seeds]
    f_pe_vals = [_eval_post_expected(e, pe_memo) for e in eps]
    s_pe_vals = [_eval_post_expected(solver_by_seed[s], pe_memo) for s in seeds]

    raw_mean = sum(f_raw) / n
    luck_adj_mean = sum(f_pe_vals) / n
    sol_raw_mean = sum(s_raw) / n
    sol_luck_mean = sum(s_pe_vals) / n
    correct_count = sum(1 for e in eps if bool(e.get("correct")))
    accused_eps = [e for e in eps if e.get("accused") is not None]
    abstention_count = n - len(accused_eps)
    accuse_day_mean = (
        sum(float(e["final_day"]) for e in accused_eps) / len(accused_eps)
        if accused_eps
        else None
    )
    luck_ratio = (luck_adj_mean / sol_luck_mean) if sol_luck_mean > 1e-12 else None

    return clean_json(
        {
            "n": n,
            "raw": raw_mean,
            "luck": luck_adj_mean,
            "acc": correct_count / n,
            "abst": abstention_count / n,
            "day": accuse_day_mean,
            "s_raw": sol_raw_mean,
            "s_luck": sol_luck_mean,
            "r_gap": sol_raw_mean - raw_mean,
            "l_gap": sol_luck_mean - luck_adj_mean,
            "ratio": luck_ratio,
        }
    )


def compute_cohort_stratification(
    cohort_id: str,
    label: str,
    agent: str,
    harness: str,
    tier: str,
    source: str,
    episodes: list[dict[str, Any]],
    profiles_by_seed: dict[int, dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    expected_n: int | None = None,
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    eps = sorted(episodes, key=lambda e: int(e["seed"]))
    if expected_n is not None and len(eps) != expected_n:
        raise ValueError(f"cohort {cohort_id} expected n={expected_n}, got n={len(eps)}")
    seeds_seen: set[int] = set()
    for ep in eps:
        s = int(ep["seed"])
        if s in seeds_seen:
            raise ValueError(f"duplicate seed {s} in cohort {cohort_id}")
        if s not in profiles_by_seed:
            raise ValueError(f"seed {s} missing from profiles in cohort {cohort_id}")
        seeds_seen.add(s)

    overall = compute_stratum_metrics(eps, solver_by_seed, pe_memo=pe_memo)
    raw_ci_mean, raw_ci_half = mean_ci([float(e["score"]) for e in eps])
    overall["raw_ci"] = _r(raw_ci_half)
    overall["raw"] = _r(raw_ci_mean)

    by_arch: dict[str, Any] = {}
    for arch in MOLE_ARCHETYPES:
        sub = [e for e in eps if profiles_by_seed[int(e["seed"])]["mole_archetype"] == arch]
        by_arch[arch] = pack_stratum_metrics(
            compute_stratum_metrics(sub, solver_by_seed, pe_memo=pe_memo)
        )

    by_dept: dict[str, Any] = {}
    for ds in DEPT_STRATA:
        sub = [e for e in eps if profiles_by_seed[int(e["seed"])]["dept_stratum"] == ds]
        by_dept[ds] = pack_stratum_metrics(
            compute_stratum_metrics(sub, solver_by_seed, pe_memo=pe_memo)
        )

    by_sol_diff: dict[str, Any] = {}
    for sd in SOLVER_DIFFICULTY_STRATA:
        sub = [e for e in eps if profiles_by_seed[int(e["seed"])]["solver_difficulty_stratum"] == sd]
        by_sol_diff[sd] = pack_stratum_metrics(
            compute_stratum_metrics(sub, solver_by_seed, pe_memo=pe_memo)
        )

    return clean_json(
        {
            "cohort_id": cohort_id,
            "label": label,
            "agent": agent,
            "harness": harness,
            "tier": tier,
            "source": source,
            "n": len(eps),
            "seeds": [int(e["seed"]) for e in eps],
            "overall": overall,
            "by_mole_archetype": by_arch,
            "by_dept_stratum": by_dept,
            "by_solver_difficulty": by_sol_diff,
        }
    )


def _rank_gap_drivers(cohort: dict[str, Any], axis_key: str) -> list[dict[str, Any]]:
    strata_map = cohort[axis_key]
    rows: list[dict[str, Any]] = []
    for name, raw_st in strata_map.items():
        st = unpack_stratum_metrics(raw_st)
        if int(st["n"]) <= 0:
            continue
        rows.append(
            clean_json(
                {
                    "stratum": name,
                    "n": int(st["n"]),
                    "raw_gap": st["r_gap"],
                    "luck_adj_gap": st["l_gap"],
                    "accuracy": st["acc"],
                }
            )
        )
    rows.sort(key=lambda r: (-float(r["luck_adj_gap"]), -int(r["n"]), str(r["stratum"])))
    return rows


def _build_solver_solvability_summary(
    med_profiles: dict[int, dict[str, Any]],
    hard_0_29_profiles: dict[int, dict[str, Any]],
    hard_30_59_profiles: dict[int, dict[str, Any]],
    sol_med: dict[int, dict[str, Any]],
    sol_h0: dict[int, dict[str, Any]],
    sol_h30: dict[int, dict[str, Any]],
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    hard_all_profiles = {**hard_0_29_profiles, **hard_30_59_profiles}
    sol_hard_all = {**sol_h0, **sol_h30}
    hard_all_eps = [sol_hard_all[s] for s in sorted(sol_hard_all)]

    pooled_hard_by_arch: dict[str, Any] = {}
    for arch in MOLE_ARCHETYPES:
        sub = [e for e in hard_all_eps if hard_all_profiles[int(e["seed"])]["mole_archetype"] == arch]
        m = compute_stratum_metrics(sub, sol_hard_all, pe_memo=pe_memo)
        accused = [e for e in sub if e.get("accused") is not None]
        prec = (
            sum(1 for e in accused if bool(e.get("correct"))) / len(accused)
            if accused
            else None
        )
        pooled_hard_by_arch[arch] = clean_json(
            {
                "n": m["n"],
                "raw": m["raw"],
                "luck": m["luck"],
                "acc": m["acc"],
                "prec": prec,
                "abst": m["abst"],
                "day": m["day"],
            }
        )

    pooled_hard_by_dept: dict[str, Any] = {}
    for ds in DEPT_STRATA:
        sub = [e for e in hard_all_eps if hard_all_profiles[int(e["seed"])]["dept_stratum"] == ds]
        m = compute_stratum_metrics(sub, sol_hard_all, pe_memo=pe_memo)
        accused = [e for e in sub if e.get("accused") is not None]
        prec = (
            sum(1 for e in accused if bool(e.get("correct"))) / len(accused)
            if accused
            else None
        )
        pooled_hard_by_dept[ds] = clean_json(
            {
                "n": m["n"],
                "raw": m["raw"],
                "luck": m["luck"],
                "acc": m["acc"],
                "prec": prec,
                "abst": m["abst"],
                "day": m["day"],
            }
        )

    med_eps = [sol_med[s] for s in sorted(sol_med)]
    med_accused = [e for e in med_eps if e.get("accused") is not None]
    hard_accused = [e for e in hard_all_eps if e.get("accused") is not None]
    med_m = compute_stratum_metrics(med_eps, sol_med, pe_memo=pe_memo)
    hard_m = compute_stratum_metrics(hard_all_eps, sol_hard_all, pe_memo=pe_memo)

    return clean_json(
        {
            "medium_0_29_overall": {
                "n": len(med_eps),
                "accuracy": sum(1 for e in med_eps if bool(e.get("correct"))) / len(med_eps),
                "precision_when_accusing": (
                    sum(1 for e in med_accused if bool(e.get("correct"))) / len(med_accused)
                ),
                "wrong_accusations": sum(1 for e in med_accused if not bool(e.get("correct"))),
                "abstentions": len(med_eps) - len(med_accused),
                "luck_adj_mean": med_m["luck"],
            },
            "hard_0_59_pooled": {
                "n": len(hard_all_eps),
                "accuracy": sum(1 for e in hard_all_eps if bool(e.get("correct"))) / len(hard_all_eps),
                "precision_when_accusing": (
                    sum(1 for e in hard_accused if bool(e.get("correct"))) / len(hard_accused)
                ),
                "wrong_accusations": sum(1 for e in hard_accused if not bool(e.get("correct"))),
                "abstentions": len(hard_all_eps) - len(hard_accused),
                "raw_mean": hard_m["raw"],
                "luck_adj_mean": hard_m["luck"],
                "all_mole_archetypes_positive_luck_adj": all(
                    v["luck"] is not None and float(v["luck"]) > 0.30
                    for v in pooled_hard_by_arch.values()
                    if int(v["n"]) > 0
                ),
                "all_dept_strata_positive_luck_adj": all(
                    v["luck"] is not None and float(v["luck"]) > 0.45
                    for v in pooled_hard_by_dept.values()
                    if int(v["n"]) > 0
                ),
                "by_mole_archetype": pooled_hard_by_arch,
                "by_dept_stratum": pooled_hard_by_dept,
            },
        }
    )


def compute_audit(
    root: Path = ROOT,
    verify_replays: bool = True,
    enforce_expected_counts: bool = True,
) -> dict[str, Any]:
    prev_allow = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        comm_v14 = root / "data" / "runs" / "committed" / "v1.4"
        rep_v14 = root / "results" / "frontier_replication" / "v1.4"

        comm_indexed = _load_indexed_pool(comm_v14, "data/runs/committed/v1.4")
        rep_indexed = _load_indexed_pool(rep_v14, "results/frontier_replication/v1.4")
        comm_eps = [ep for _, ep in comm_indexed]
        rep_eps = [ep for _, ep in rep_indexed]

        if enforce_expected_counts:
            if len(comm_eps) != EXPECTED_COMMITTED_V14_EPISODES:
                raise ValueError(
                    f"committed v1.4 expected {EXPECTED_COMMITTED_V14_EPISODES} episodes, got {len(comm_eps)}"
                )
            if len(rep_eps) != EXPECTED_REPLICATION_V14_EPISODES:
                raise ValueError(
                    f"replication v1.4 expected {EXPECTED_REPLICATION_V14_EPISODES} episodes, got {len(rep_eps)}"
                )
            if len(comm_eps) + len(rep_eps) != EXPECTED_COMBINED_V14_EPISODES:
                raise ValueError(
                    f"combined v1.4 expected {EXPECTED_COMBINED_V14_EPISODES} episodes, got {len(comm_eps) + len(rep_eps)}"
                )

        if verify_replays:
            comm_pool_audit = verify_episode_pool(comm_eps, "data/runs/committed/v1.4")
            rep_pool_audit = verify_episode_pool(rep_eps, "results/frontier_replication/v1.4")
        else:
            comm_pool_audit = {
                "pool": "data/runs/committed/v1.4",
                "total": len(comm_eps),
                "verified": 0,
                "mismatches": 0,
                "step_mismatches": 0,
                "duplicates": 0,
                "pre_1bc3e281_detail_normalized_steps": 0,
                "unwrapped_mcp_error_steps": 0,
                "truncated_output_steps_verified": 0,
                "client_only_steps": 0,
                "clean_rc0_non_accuse_zero_day_seeds": sorted(
                    int(e["seed"]) for e in comm_eps if is_clean_non_accuse_rc0_exit(e)
                ),
            }
            rep_pool_audit = {
                "pool": "results/frontier_replication/v1.4",
                "total": len(rep_eps),
                "verified": 0,
                "mismatches": 0,
                "step_mismatches": 0,
                "duplicates": 0,
                "pre_1bc3e281_detail_normalized_steps": 0,
                "unwrapped_mcp_error_steps": 0,
                "truncated_output_steps_verified": 0,
                "client_only_steps": 0,
                "clean_rc0_non_accuse_zero_day_seeds": sorted(
                    int(e["seed"]) for e in rep_eps if is_clean_non_accuse_rc0_exit(e)
                ),
            }

        include_flash_hard = gap_ships_flash_hard(root)
        pe_memo: dict[int, float] = {}

        def _select(
            rel_dir: str,
            agent: str,
            tier: str,
            s_min: int,
            s_max: int,
        ) -> list[dict[str, Any]]:
            pool_rows = (
                comm_indexed
                if rel_dir.startswith("data/runs/committed/v1.4")
                else rep_indexed
            )
            prefix = rel_dir + "/"
            return sorted(
                (
                    e
                    for rdir, e in pool_rows
                    if (rdir == rel_dir or rdir.startswith(prefix))
                    and e.get("agent") == agent
                    and e.get("tier") == tier
                    and s_min <= int(e["seed"]) <= s_max
                ),
                key=lambda e: int(e["seed"]),
            )

        sol_med_eps = _select("data/runs/committed/v1.4/reference", "solver", "medium", 0, 29)
        sol_h0_eps = _select("data/runs/committed/v1.4/reference", "solver", "hard", 0, 29)
        sol_h30_eps = _select(
            "data/runs/committed/v1.4/reference/solver-hard-seeds30to59",
            "solver",
            "hard",
            30,
            59,
        )

        if enforce_expected_counts:
            for name, arr in (
                ("solver_medium_0_29", sol_med_eps),
                ("solver_hard_0_29", sol_h0_eps),
                ("solver_hard_30_59", sol_h30_eps),
            ):
                if len(arr) != 30:
                    raise ValueError(f"{name} expected n=30, got n={len(arr)}")

        sol_med_map = {int(e["seed"]): e for e in sol_med_eps}
        sol_h0_map = {int(e["seed"]): e for e in sol_h0_eps}
        sol_h30_map = {int(e["seed"]): e for e in sol_h30_eps}

        med_profiles = {
            s: extract_seed_profile("medium", s, sol_med_map[s], pe_memo=pe_memo)
            for s in sorted(sol_med_map)
        }
        h0_profiles = {
            s: extract_seed_profile("hard", s, sol_h0_map[s], pe_memo=pe_memo)
            for s in sorted(sol_h0_map)
        }
        h30_profiles = {
            s: extract_seed_profile("hard", s, sol_h30_map[s], pe_memo=pe_memo)
            for s in sorted(sol_h30_map)
        }

        oc_c_h0 = _select(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
            "opencode:google/gemini-4-carbon",
            "hard",
            0,
            29,
        )
        ip_c_h0 = _select(
            "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard",
            "gemini:gemini-4-carbon",
            "hard",
            0,
            29,
        )
        gpt55_hard_dir = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"
        oc_gpt55_h0 = (
            _select(
                "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
                "opencode:openai/gpt-5.5",
                "hard",
                0,
                29,
            )
            if gpt55_hard_dir.is_dir() or enforce_expected_counts
            else []
        )
        oc_f_h0 = (
            _select(
                "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard",
                "opencode:google/gemini-3.5-flash",
                "hard",
                0,
                29,
            )
            if include_flash_hard
            else []
        )

        oc_c_m0 = _select(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium",
            "opencode:google/gemini-4-carbon",
            "medium",
            0,
            29,
        )
        ip_c_m0 = _select(
            "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium",
            "gemini:gemini-4-carbon",
            "medium",
            0,
            29,
        )
        oc_f_m0 = _select(
            "results/frontier_replication/v1.4/opencode-gemini-3.5-flash",
            "opencode:google/gemini-3.5-flash",
            "medium",
            0,
            29,
        )

        grok_h30 = _select(
            "results/frontier_replication/v1.4/reference/grok_tactics-hard-seeds30to59",
            "grok_tactics",
            "hard",
            30,
            59,
        )
        heur_h30 = _select(
            "results/frontier_replication/v1.4/reference/heuristic-hard-seeds30to59",
            "heuristic",
            "hard",
            30,
            59,
        )
        g1_ext_h30 = _select(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
            "opencode:google/gemini-4-carbon",
            "hard",
            30,
            59,
        )
        fr8_rep_h30 = _select(
            "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "hard",
            30,
            59,
        )

        union_map: dict[int, dict[str, Any]] = {int(e["seed"]): e for e in fr8_rep_h30}
        for e in g1_ext_h30:
            union_map[int(e["seed"])] = e
        union_ext_h30 = [union_map[s] for s in sorted(union_map)]

        exp = (lambda k: k) if enforce_expected_counts else (lambda _k: None)

        hard_0_29_cohorts = [
            compute_cohort_stratification(
                "solver_hard_0_29",
                "reference solver hard (0-29)",
                "solver",
                "reference",
                "hard",
                "committed",
                sol_h0_eps,
                h0_profiles,
                sol_h0_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_hard_0_29",
                "OpenCode gemini-4-carbon hard (0-29)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "committed",
                oc_c_h0,
                h0_profiles,
                sol_h0_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "inproc_carbon_hard_0_29",
                "in-process gemini-4-carbon hard (0-29)",
                "gemini:gemini-4-carbon",
                "inproc",
                "hard",
                "committed",
                ip_c_h0,
                h0_profiles,
                sol_h0_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
        ]
        if oc_gpt55_h0 or enforce_expected_counts:
            hard_0_29_cohorts.append(
                compute_cohort_stratification(
                    "opencode_gpt55_hard_0_29",
                    "OpenCode gpt-5.5 hard (0-29)",
                    "opencode:openai/gpt-5.5",
                    "opencode",
                    "hard",
                    "committed",
                    oc_gpt55_h0,
                    h0_profiles,
                    sol_h0_map,
                    expected_n=exp(30),
                    pe_memo=pe_memo,
                )
            )
        if include_flash_hard:
            hard_0_29_cohorts.append(
                compute_cohort_stratification(
                    "opencode_flash_hard_0_29",
                    "OpenCode gemini-3.5-flash hard (0-29)",
                    "opencode:google/gemini-3.5-flash",
                    "opencode",
                    "hard",
                    "committed",
                    oc_f_h0,
                    h0_profiles,
                    sol_h0_map,
                    expected_n=exp(30),
                    pe_memo=pe_memo,
                )
            )

        medium_0_29_cohorts = [
            compute_cohort_stratification(
                "solver_medium_0_29",
                "reference solver medium (0-29)",
                "solver",
                "reference",
                "medium",
                "committed",
                sol_med_eps,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_medium_0_29",
                "OpenCode gemini-4-carbon medium (0-29)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "medium",
                "committed",
                oc_c_m0,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "inproc_carbon_medium_0_29",
                "in-process gemini-4-carbon medium (0-29)",
                "gemini:gemini-4-carbon",
                "inproc",
                "medium",
                "committed",
                ip_c_m0,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_flash_medium_0_29",
                "OpenCode gemini-3.5-flash medium (0-29)",
                "opencode:google/gemini-3.5-flash",
                "opencode",
                "medium",
                "replication",
                oc_f_m0,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
        ]

        ext_hard_30_59_cohorts = [
            compute_cohort_stratification(
                "solver_hard_30_59",
                "reference solver hard (30-59)",
                "solver",
                "reference",
                "hard",
                "committed",
                sol_h30_eps,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "grok_tactics_hard_30_59",
                "grok_tactics hard (30-59)",
                "grok_tactics",
                "reference",
                "hard",
                "replication",
                grok_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "heuristic_hard_30_59",
                "heuristic hard (30-59)",
                "heuristic",
                "reference",
                "hard",
                "replication",
                heur_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_g1_ext_hard",
                "OpenCode gemini-4-carbon hard G1 ext (34,37)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "committed",
                g1_ext_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(2),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_fr8_rep_hard",
                "OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "replication",
                fr8_rep_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(5),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_union_ext_hard",
                "OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "union_committed_precedence",
                union_ext_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(6),
                pe_memo=pe_memo,
            ),
        ]

        g1_map = {int(e["seed"]): e for e in g1_ext_h30}
        fr8_map = {int(e["seed"]): e for e in fr8_rep_h30}
        overlap_ext_seeds = sorted(set(g1_map) & set(fr8_map))
        union_seeds = [int(e["seed"]) for e in union_ext_h30]
        union_dept_sizes = [int(h30_profiles[s]["mole_dept_size"]) for s in union_seeds]

        h0_by_id = {c["cohort_id"]: c for c in hard_0_29_cohorts}
        carbon_hard_row = h0_by_id["opencode_carbon_hard_0_29"]
        gpt55_hard_row = h0_by_id.get("opencode_gpt55_hard_0_29")
        flash_hard_row = h0_by_id.get("opencode_flash_hard_0_29")
        flash_med_row = medium_0_29_cohorts[3]
        grok_ext_row = ext_hard_30_59_cohorts[1]
        heur_ext_row = ext_hard_30_59_cohorts[2]

        gap_drivers: dict[str, Any] = {
            "primary_carbon_hard_by_mole_archetype": _rank_gap_drivers(
                carbon_hard_row, "by_mole_archetype"
            ),
            "primary_carbon_hard_by_dept_stratum": _rank_gap_drivers(
                carbon_hard_row, "by_dept_stratum"
            ),
            "primary_carbon_hard_by_solver_difficulty": _rank_gap_drivers(
                carbon_hard_row, "by_solver_difficulty"
            ),
            "fr8_flash_medium_by_mole_archetype": _rank_gap_drivers(
                flash_med_row, "by_mole_archetype"
            ),
            "ext_grok_tactics_hard_by_mole_archetype": _rank_gap_drivers(
                grok_ext_row, "by_mole_archetype"
            ),
            "ext_heuristic_hard_by_mole_archetype": _rank_gap_drivers(
                heur_ext_row, "by_mole_archetype"
            ),
            "extension_6_seed_union_selection_profile": clean_json(
                {
                    "union_seeds": union_seeds,
                    "overlap_seeds_committed_precedence": overlap_ext_seeds,
                    "seed_34_selected_source": "committed_g1_f9fb7a4a",
                    "seed_34_g1_score": float(g1_map[34]["score"]) if 34 in g1_map else None,
                    "seed_34_g1_luck_adj": (
                        _eval_post_expected(g1_map[34], pe_memo) if 34 in g1_map else None
                    ),
                    "seed_34_fr8_score": float(fr8_map[34]["score"]) if 34 in fr8_map else None,
                    "seed_34_fr8_luck_adj": (
                        _eval_post_expected(fr8_map[34], pe_memo) if 34 in fr8_map else None
                    ),
                    "mean_mole_dept_size_union_6": (
                        sum(union_dept_sizes) / len(union_dept_sizes) if union_dept_sizes else None
                    ),
                    "mean_mole_dept_size_hard_30_59": (
                        sum(float(p["mole_dept_size"]) for p in h30_profiles.values())
                        / len(h30_profiles)
                    ),
                    "mean_mole_dept_size_hard_0_29": (
                        sum(float(p["mole_dept_size"]) for p in h0_profiles.values())
                        / len(h0_profiles)
                    ),
                    "deep_crowd_camouflage_count_in_union_6": sum(
                        1
                        for s in union_seeds
                        if h30_profiles[s]["mole_archetype"] == "deep_crowd_camouflage"
                    ),
                    "crowded_dept_count_in_union_6": sum(
                        1 for s in union_seeds if h30_profiles[s]["dept_stratum"] == "crowded_dept"
                    ),
                }
            ),
        }
        if gpt55_hard_row is not None:
            gap_drivers["primary_gpt55_hard_by_mole_archetype"] = _rank_gap_drivers(
                gpt55_hard_row, "by_mole_archetype"
            )
        if include_flash_hard and flash_hard_row is not None:
            gap_drivers["primary_flash_hard_by_mole_archetype"] = _rank_gap_drivers(
                flash_hard_row, "by_mole_archetype"
            )

        solver_solvability = _build_solver_solvability_summary(
            med_profiles=med_profiles,
            hard_0_29_profiles=h0_profiles,
            hard_30_59_profiles=h30_profiles,
            sol_med=sol_med_map,
            sol_h0=sol_h0_map,
            sol_h30=sol_h30_map,
            pe_memo=pe_memo,
        )

        all_cohorts = hard_0_29_cohorts + medium_0_29_cohorts + ext_hard_30_59_cohorts
        distinct_eps_evaluated = (
            sum(c["n"] for c in hard_0_29_cohorts)
            + sum(c["n"] for c in medium_0_29_cohorts)
            + sum(
                c["n"]
                for c in ext_hard_30_59_cohorts
                if c["cohort_id"] != "opencode_carbon_union_ext_hard"
            )
        )

        return clean_json(
            {
                "schema_version": "v1.4-frontier-mole-stratified-gap-1",
                "tiers_version": TIERS_VERSION,
                "upstream_justsilas_sync_commit": "5f9b3297",
                "zero_live_api_calls": True,
                "zero_git_dependency": True,
                "zero_subprocesses": True,
                "flash_hard_shipped_in_gap_md": include_flash_hard,
                "seed_profile_columns": list(SEED_PROFILE_COLUMNS),
                "seed_profile_enums": {k: list(v) for k, v in SEED_PROFILE_ENUMS.items()},
                "stratum_metric_columns": list(STRATUM_METRIC_COLUMNS),
                "provenance_and_locks": {
                    "upstream_justsilas_sync": {
                        "head_commit": "5f9b3297",
                        "code_freeze_tag": "afterquery-final",
                        "code_freeze_commit": "1bc3e281",
                        "afterquery_submit_tag": "afterquery-submit",
                        "afterquery_submit_commit": "9225f2ad",
                        "afterquery_submit_2_tag": "afterquery-submit-2",
                        "afterquery_submit_2_commit": "aa1c679e",
                        "ceo_correction_commit": "5f9b3297",
                        "rehearsal_final_branch_commit": "d0ead011",
                        "rehearsal_snapshot_0852_ratio_pct": 153,
                        "rehearsal_snapshot_0852_valid_trials": 7,
                        "harbor_rehearsal_ratios_pct": [93, 116, 131],
                        "harbor_rehearsal_valid_trials": [10, 10, 9],
                    },
                    "primary_0_29_lock": {
                        "classification": "post_hoc_lock",
                        "episodes_commit": "8fd4dec",
                        "lock_commit": "671ed96",
                        "lock_delay_s": 28,
                        "solver_reference_layout": (
                            "20+10 split dirs (0-19 in 20261114-121126 + 20-29 in seeds20to29)"
                        ),
                        "note": (
                            "Post-hoc lock against later reruns and cherry-picking, not a pre-registration."
                        ),
                    },
                    "g1_hard_30_59_extension": {
                        "classification": "pre_registered",
                        "prereg_commit": "f9fb7a4a",
                        "run_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                        "completed_seeds": [int(e["seed"]) for e in g1_ext_h30],
                        "n": len(g1_ext_h30),
                        "stopped_reason": "quota_preserved_for_harbor_rehearsal",
                    },
                    "gpt_5_5_hard_0_29": {
                        "classification": "pre_registered",
                        "prereg_commit": "cf394894",
                        "results_commit": "ca0a0dc0",
                        "upstream_sync_commit": "5f9b3297",
                        "run_dir": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
                        "timeout_cap_s": 7200,
                        "spend_cap_usd": 200,
                        "opencode_version": "1.19.5",
                        "committed_v14_episodes": sum(
                            1 for e in comm_eps if "gpt-5.5" in str(e.get("agent") or "")
                        ),
                        "clean_rc0_non_accuse_zero_day_seeds": sorted(
                            int(e["seed"])
                            for e in comm_eps
                            if "gpt-5.5" in str(e.get("agent") or "")
                            and is_clean_non_accuse_rc0_exit(e)
                        ),
                    },
                    "step_error_detail_compat": {
                        "commit": "1bc3e281",
                        "rule": (
                            "Unwrap OpenCode stringified MCP error JSON via norm_result first, then match "
                            "pre-1bc3e281 data={} against live Env.call data={'detail': ...} when 'detail' "
                            "is absent from recorded data; allow final_day=0 on clean rc=0 non-accuse exits "
                            "(is_clean_non_accuse_rc0_exit) while rejecting timeouts, rc!=0, and tampered scores."
                        ),
                    },
                },
                "mole_policy_and_genome": {
                    "medium": _tier_mole_genome("medium"),
                    "hard": _tier_mole_genome("hard"),
                    "taxonomy_definitions": {
                        "mole_archetype": {
                            "decoy_entangled": (
                                "same_dept_decoy is True (100% regular-document overlap between mole and "
                                "angry-message decoy plus 50% framed after-hours decoy share)"
                            ),
                            "deep_crowd_camouflage": (
                                "not decoy_entangled and mole_dept_size >= floor(n_employees / n_depts) + 2 "
                                "(>=7 of 20 on medium, >=10 of 40 on hard)"
                            ),
                            "low_tempo_stealth": (
                                "neither above and passive_leak_count < n_days * p_leak "
                                "(<=10 on medium, <=13 on hard)"
                            ),
                            "high_tempo_exposed": (
                                "neither above and passive_leak_count >= n_days * p_leak "
                                "(>=11 on medium, >=14 on hard)"
                            ),
                        },
                        "dept_stratum": {
                            "compact_dept": "mole_dept_size <= 4 on medium, <= 8 on hard",
                            "standard_dept": "mole_dept_size in 5..6 on medium, 9..10 on hard",
                            "crowded_dept": "mole_dept_size >= 7 on medium, >= 11 on hard",
                        },
                        "solver_difficulty_stratum": {
                            "fast_isolation": "reference solver final_day <= 6 on medium, <= 8 on hard",
                            "mid_horizon_isolation": (
                                "reference solver final_day in 7..9 on medium, 9..12 on hard"
                            ),
                            "late_or_stalled_isolation": (
                                "reference solver final_day >= 10 on medium, >= 13 on hard"
                            ),
                        },
                    },
                    "notes": (
                        "Standard medium and hard v1.4 tiers run DEFAULT_STRATEGY (default_v0: 0 conditional "
                        "DSL rules, random_seeded leak selection weighted by careful_mole 1 - share, Poisson "
                        "framing, and 95% canary fingerprint accuracy on hard), whereas evolved HoF DSL and RL "
                        "moles apply only on hard_forge and hard_rl judge tracks. Because p_single_dept_recipients "
                        "is 0.0 on medium and hard, 100% of regular documents go to two whole departments, so "
                        "regular leaks can never separate colleagues inside mole_dept."
                    ),
                },
                "replay_verification": {
                    "committed_v14": comm_pool_audit,
                    "replication_v14": rep_pool_audit,
                },
                "summary": {
                    "worlds_extracted": len(med_profiles) + len(h0_profiles) + len(h30_profiles),
                    "cohort_count": len(all_cohorts),
                    "cohort_episode_counts": [int(c["n"]) for c in all_cohorts],
                    "distinct_cohort_episodes_evaluated": distinct_eps_evaluated,
                    "committed_v14_total": int(comm_pool_audit["total"]),
                    "committed_v14_verified": int(comm_pool_audit["verified"]),
                    "replication_v14_total": int(rep_pool_audit["total"]),
                    "replication_v14_verified": int(rep_pool_audit["verified"]),
                    "total_pool_episodes_replay_verified": (
                        int(comm_pool_audit["verified"]) + int(rep_pool_audit["verified"])
                    ),
                    "flash_hard_held_pending_gap_md": not include_flash_hard,
                },
                "seed_profiles": {
                    "medium_0_29": pack_seed_profiles(list(med_profiles.values())),
                    "hard_0_29": pack_seed_profiles(list(h0_profiles.values())),
                    "hard_30_59": pack_seed_profiles(list(h30_profiles.values())),
                },
                "blocks": {
                    "primary_hard_0_29": hard_0_29_cohorts,
                    "primary_and_fr8_medium_0_29": medium_0_29_cohorts,
                    "extension_hard_30_59": ext_hard_30_59_cohorts,
                },
                "solver_solvability": solver_solvability,
                "gap_drivers": gap_drivers,
            }
        )
    finally:
        if prev_allow is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_allow


def _fmt_json_compact(obj: Any, depth: int = 0, max_expand_depth: int = 2) -> str:
    if depth >= max_expand_depth or not isinstance(obj, (dict, list)) or not obj:
        return json.dumps(obj, sort_keys=True, allow_nan=False, separators=(",", ":"))
    pad = " " * depth
    inner_pad = " " * (depth + 1)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return json.dumps(obj, allow_nan=False, separators=(",", ":"))
        items = [inner_pad + _fmt_json_compact(v, depth + 1, max_expand_depth) for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    items = [
        f"{inner_pad}{json.dumps(k)}: {_fmt_json_compact(obj[k], depth + 1, max_expand_depth)}"
        for k in sorted(obj.keys())
    ]
    return "{\n" + ",\n".join(items) + "\n" + pad + "}"


def serialize_audit_json(audit: dict[str, Any]) -> str:
    blob = _fmt_json_compact(audit, depth=0, max_expand_depth=1) + "\n"
    size = len(blob.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(
            f"serialized mole_stratified_gap.json is {size} bytes, exceeding {MAX_JSON_BYTES}"
        )
    return blob


def _md_heading(level: int, title: str) -> str:
    return (chr(35) * level) + " " + title


def _f(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:.{nd}f}"


def _signed(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:+.{nd}f}"


def _pct(val: float | None, nd: int = 1) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{100.0 * val:.{nd}f}%"


def _render_stratum_rows(cohorts: list[dict[str, Any]], axis_key: str, keys: tuple[str, ...]) -> list[str]:
    lines = [
        "| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cohorts:
        ov = c["overall"]
        is_sol = c["agent"] == "solver"
        lines.append(
            f"| **{c['label']}** | **ALL** | {ov['n']} | {_signed(ov['raw'])} | "
            f"{_signed(ov['luck'])} | {_signed(ov['s_luck'])} | "
            f"{'n/a' if is_sol else _signed(ov['l_gap'])} | "
            f"{'n/a' if is_sol else _pct(ov['ratio'])} | "
            f"{_pct(ov['acc'])} | {_pct(ov['abst'])} | "
            f"{_f(ov['day'], 1)} |"
        )
        smap = c[axis_key]
        for k in keys:
            st = unpack_stratum_metrics(smap[k])
            if int(st["n"]) == 0:
                lines.append(
                    f"| {c['label']} | `{k}` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
                )
            else:
                lines.append(
                    f"| {c['label']} | `{k}` | {st['n']} | {_signed(st['raw'])} | "
                    f"{_signed(st['luck'])} | {_signed(st['s_luck'])} | "
                    f"{'n/a' if is_sol else _signed(st['l_gap'])} | "
                    f"{'n/a' if is_sol else _pct(st['ratio'])} | "
                    f"{_pct(st['acc'])} | {_pct(st['abst'])} | "
                    f"{_f(st['day'], 1)} |"
                )
    return lines


def render_markdown(audit: dict[str, Any]) -> str:
    s = audit["summary"]
    rv = audit["replay_verification"]
    prov = audit["provenance_and_locks"]
    gen = audit["mole_policy_and_genome"]
    sp = audit["seed_profiles"]
    blocks = audit["blocks"]
    solv = audit["solver_solvability"]
    drv = audit["gap_drivers"]
    include_flash_hard = bool(audit.get("flash_hard_shipped_in_gap_md"))

    h0_cohorts = blocks["primary_hard_0_29"]
    m0_cohorts = blocks["primary_and_fr8_medium_0_29"]
    h30_cohorts = blocks["extension_hard_30_59"]

    h0_by_id = {c["cohort_id"]: c for c in h0_cohorts}
    sol_h0 = h0_by_id["solver_hard_0_29"]
    oc_c_h0 = h0_by_id["opencode_carbon_hard_0_29"]
    oc_gpt55_h0 = h0_by_id.get("opencode_gpt55_hard_0_29")
    oc_f_h0 = h0_by_id.get("opencode_flash_hard_0_29") if include_flash_hard else None

    sol_m0 = m0_cohorts[0]
    oc_c_m0 = m0_cohorts[1]
    ip_c_m0 = m0_cohorts[2]
    oc_f_m0 = m0_cohorts[3]

    g1_h30 = h30_cohorts[3]
    fr8_h30 = h30_cohorts[4]
    u6_h30 = h30_cohorts[5]

    comm_rv = rv["committed_v14"]
    rep_rv = rv["replication_v14"]
    u6_sel = drv["extension_6_seed_union_selection_profile"]
    hard_pooled = solv["hard_0_59_pooled"]
    med_solv = solv["medium_0_29_overall"]
    hp_arch = hard_pooled["by_mole_archetype"]
    hp_dept = hard_pooled["by_dept_stratum"]

    c_arch_top = drv["primary_carbon_hard_by_mole_archetype"]
    c_dept_top = drv["primary_carbon_hard_by_dept_stratum"]
    c_sol_top = drv["primary_carbon_hard_by_solver_difficulty"]
    g_arch_top = drv["ext_grok_tactics_hard_by_mole_archetype"]
    h_arch_top = drv["ext_heuristic_hard_by_mole_archetype"]

    oc_c_decoy = unpack_stratum_metrics(oc_c_h0["by_mole_archetype"]["decoy_entangled"])
    sol_h0_decoy = unpack_stratum_metrics(sol_h0["by_mole_archetype"]["decoy_entangled"])
    sol_h0_top_arch = unpack_stratum_metrics(
        sol_h0["by_mole_archetype"][c_arch_top[0]["stratum"]]
    )
    oc_f_m0_stealth = unpack_stratum_metrics(oc_f_m0["by_mole_archetype"]["low_tempo_stealth"])
    ip_c_m0_crowd = unpack_stratum_metrics(ip_c_m0["by_dept_stratum"]["crowded_dept"])

    if oc_gpt55_h0 is not None:
        gpt_crowd = unpack_stratum_metrics(oc_gpt55_h0["by_mole_archetype"]["deep_crowd_camouflage"])
        gpt_cdept = unpack_stratum_metrics(oc_gpt55_h0["by_dept_stratum"]["crowded_dept"])
        gpt_stealth = unpack_stratum_metrics(oc_gpt55_h0["by_mole_archetype"]["low_tempo_stealth"])
        gpt_contrast = (
            f" By contrast, OpenCode `gpt-5.5` (`n={oc_gpt55_h0['n']}`, raw `{_signed(oc_gpt55_h0['overall']['raw'])}`, "
            f"luck-adjusted `{_signed(oc_gpt55_h0['overall']['luck'])}`, `{_pct(oc_gpt55_h0['overall']['ratio'])}` of solver "
            f"luck-adjusted, `{_pct(oc_gpt55_h0['overall']['acc'])}` accuracy) plants about 2 canaries/day and reaches "
            f"`{_pct(gpt_crowd['acc'])}` accuracy on `deep_crowd_camouflage` (`n={gpt_crowd['n']}`, raw `{_signed(gpt_crowd['raw'])}`, "
            f"luck-adjusted `{_signed(gpt_crowd['luck'])}`) and `{_pct(gpt_cdept['acc'])}` on `crowded_dept` (`n={gpt_cdept['n']}`, "
            f"raw `{_signed(gpt_cdept['raw'])}`, luck-adjusted `{_signed(gpt_cdept['luck'])}`), while both of its clean `rc=0` "
            f"non-accuse `final_day=0` prose stops (`seeds {prov['gpt_5_5_hard_0_29']['clean_rc0_non_accuse_zero_day_seeds']}`) "
            f"occur in `low_tempo_stealth` (`n={gpt_stealth['n']}`, abstain `{_pct(gpt_stealth['abst'])}`)."
        )
    else:
        gpt_contrast = ""

    arch_lucks = [float(hp_arch[a]["luck"]) for a in MOLE_ARCHETYPES if hp_arch[a]["luck"] is not None]
    min_arch_luck = min(arch_lucks) if arch_lucks else None
    max_arch_luck = max(arch_lucks) if arch_lucks else None

    if include_flash_hard and oc_f_h0 is not None:
        f_arch_top = drv["primary_flash_hard_by_mole_archetype"]
        flash_gate_bullet = (
            f"- **Cross-model hard stratification (`OpenCode gemini-3.5-flash` hard `0-29`, `n=30`):** "
            f"`docs/reports/gap.md` ships `gemini-3.5-flash`, so its primary hard cohort is included below "
            f"(overall raw `{_signed(oc_f_h0['overall']['raw'])}`, luck-adjusted "
            f"`{_signed(oc_f_h0['overall']['luck'])}`, gap `{_signed(oc_f_h0['overall']['l_gap'])}`; "
            f"largest mole-archetype luck-adjusted gap on `{f_arch_top[0]['stratum']}` at "
            f"`{_signed(f_arch_top[0]['luck_adj_gap'])}`)."
        )
    else:
        flash_gate_bullet = (
            "- **`docs/reports/gap.md` hard-row gate (`gap_ships_flash_hard(root)`):** "
            "`opencode:google/gemini-3.5-flash` hard (`seeds 0-29`) is replay-verified inside "
            f"`data/runs/committed/v1.4` (`{comm_rv['verified']}/{comm_rv['total']}`) and gated out of "
            "primary hard tables here until `docs/reports/gap.md` ships it; FR8 `gemini-3.5-flash` "
            "medium (`seeds 0-29`, `n=30`) is reported in full below."
        )

    clean_zero_seeds = comm_rv.get("clean_rc0_non_accuse_zero_day_seeds") or []
    clean_zero_clause = (
        f" and verifying `{len(clean_zero_seeds)}` clean `rc=0` non-accuse `final_day=0` exits (`seeds {clean_zero_seeds}`)"
        if clean_zero_seeds
        else ""
    )

    lines: list[str] = [
        _md_heading(1, "Canary v1.4 Mole-Archetype and Seed-Difficulty Stratified Gap Audit"),
        "",
        (
            "Every figure in this report is deterministically computed on pure CPU by "
            "`scripts/frontier_mole_stratified_gap.py` from `Env(tier, seed)` world/mole attributes "
            f"across `{s['worlds_extracted']}` worlds (`medium 0-29`, `hard 0-29`, `hard 30-59`) and "
            f"`{s['cohort_count']}` stratified cohorts after full step-and-ledger replay verification "
            f"of `{comm_rv['verified']}/{comm_rv['total']}` committed `v1.4` episodes and "
            f"`{rep_rv['verified']}/{rep_rv['total']}` FR8 replication episodes "
            f"(synced through `justSilas@{audit['upstream_justsilas_sync_commit']}`, `0` live API calls, "
            "`0` `.git` or subprocess runtime dependency)."
        ),
        "",
        (
            "**Complementary scope:** `docs/reports/failure_analysis_v1.4.md` decomposes within-episode "
            "agent decision mistakes on primary hard `seeds 0-29`, and `docs/reports/reference_optimality.md` "
            "establishes aggregate solver calibration and stopping optimality on dev `seeds 8000-9399`. "
            "This report addresses the orthogonal **across-seed structural and mole-archetype question**: "
            "(1) whether every mole archetype and department-anonymity stratum is reliably solvable by the "
            "Bayesian reference solver, and (2) which specific mole archetypes and world difficulty strata "
            "drive the luck-adjusted frontier gap across `gemini-4-carbon`, `gpt-5.5`, `gemini-3.5-flash`, and "
            "non-Bayesian baselines."
        ),
        "",
        "Reproduce and verify:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/frontier_mole_stratified_gap.py --check",
        "```",
        "",
        _md_heading(2, "1. Provenance Honesty (Panel Fixes A/C/D), Replay Integrity, and Headline Findings"),
        "",
        (
            f"- **Provenance & registration honesty (Panel Fixes A/C/D, synced to `justSilas@{prov['upstream_justsilas_sync']['head_commit']}`):** Primary `seeds 0-29` "
            f"(`data/runs/committed/v1.4/`, committed in `{prov['primary_0_29_lock']['episodes_commit']}`) "
            f"are governed by a **post-hoc lock** (`{prov['primary_0_29_lock']['lock_commit']}`, committed "
            f"`{prov['primary_0_29_lock']['lock_delay_s']} s` after `{prov['primary_0_29_lock']['episodes_commit']}`) "
            "against later reruns and cherry-picking, not a pre-registration (`20+10` solver reference split "
            "directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` "
            f"(`{prov['g1_hard_30_59_extension']['prereg_commit']}`, `opencode-gemini-4-carbon-ext/hard`, "
            f"`n={prov['g1_hard_30_59_extension']['n']}`, completed `seeds {prov['g1_hard_30_59_extension']['completed_seeds']}` "
            "before stopping to preserve shared carbon quota for the Harbor rehearsal) and the second frontier "
            f"family `gpt-5.5` (`{prov['gpt_5_5_hard_0_29']['prereg_commit']}`, shipped in `{prov['gpt_5_5_hard_0_29']['results_commit']}` "
            f"at `{prov['gpt_5_5_hard_0_29']['run_dir']}`, OpenCode "
            f"`{prov['gpt_5_5_hard_0_29']['opencode_version']}`, `{prov['gpt_5_5_hard_0_29']['timeout_cap_s']} s` "
            f"per-episode cap, `${prov['gpt_5_5_hard_0_29']['spend_cap_usd']}` spend cap, "
            f"`{prov['gpt_5_5_hard_0_29']['committed_v14_episodes']}` committed `v1.4` episodes with `0` infra exclusions "
            f"and `{len(prov['gpt_5_5_hard_0_29']['clean_rc0_non_accuse_zero_day_seeds'])}` clean `rc=0` non-accuse "
            f"`final_day=0` exits on `seeds {prov['gpt_5_5_hard_0_29']['clean_rc0_non_accuse_zero_day_seeds']}`) were "
            "**pre-registered** before any episode ran. Upstream submission tags: "
            f"`{prov['upstream_justsilas_sync']['code_freeze_tag']}` (`{prov['upstream_justsilas_sync']['code_freeze_commit']}` code freeze), "
            f"`{prov['upstream_justsilas_sync']['afterquery_submit_tag']}` (`{prov['upstream_justsilas_sync']['afterquery_submit_commit']}` "
            f"08:52 `{prov['upstream_justsilas_sync']['rehearsal_snapshot_0852_ratio_pct']}%` snapshot on "
            f"`{prov['upstream_justsilas_sync']['rehearsal_snapshot_0852_valid_trials']}` trials), and "
            f"`{prov['upstream_justsilas_sync']['afterquery_submit_2_tag']}` (`{prov['upstream_justsilas_sync']['afterquery_submit_2_commit']}`) "
            f"plus append-only CEO correction `{prov['upstream_justsilas_sync']['ceo_correction_commit']}` recording final Harbor rehearsal "
            "ratios `93%, 116%, 131%` across `10, 10, 9` valid trials (`s1-rehearsal-final` "
            f"`{prov['upstream_justsilas_sync']['rehearsal_final_branch_commit']}`, run 3 final `131%` on `9` valid trials superseding the 08:52 `153%` snapshot)."
        ),
        (
            f"- **100% replay integrity (`{prov['step_error_detail_compat']['commit']}` `norm_result` order):** "
            f"`{comm_rv['verified']}/{comm_rv['total']}` committed `v1.4` episodes and "
            f"`{rep_rv['verified']}/{rep_rv['total']}` FR8 replication episodes "
            f"(`{s['total_pool_episodes_replay_verified']}/{comm_rv['total'] + rep_rv['total']}` total) pass "
            "step-by-step and ledger replay with `0` mismatches and `0` duplicates, unwrapping OpenCode "
            f"MCP error JSON first (`{comm_rv['unwrapped_mcp_error_steps']}` committed, "
            f"`{rep_rv['unwrapped_mcp_error_steps']}` replication steps) before matching pre-`1bc3e281` "
            f"`data={{}}` against live `data={{'detail': ...}}` (`{comm_rv['pre_1bc3e281_detail_normalized_steps']}` "
            f"committed, `{rep_rv['pre_1bc3e281_detail_normalized_steps']}` replication steps){clean_zero_clause}."
        ),
        (
            "- **Every mole archetype and department stratum is reliably solved by the reference solver:** "
            f"Across all `{hard_pooled['n']}` hard worlds (`0-59`), the Bayesian reference solver achieves "
            f"`{_pct(hard_pooled['accuracy'])}` accuracy (`{_pct(hard_pooled['precision_when_accusing'])}` precision "
            f"when accusing, raw `{_signed(hard_pooled['raw_mean'])}`, luck-adjusted "
            f"`{_signed(hard_pooled['luck_adj_mean'])}`), with strongly positive luck-adjusted scores across every "
            f"mole archetype (`{_signed(hp_arch['decoy_entangled']['luck'])}` on `decoy_entangled`, "
            f"`{_signed(hp_arch['deep_crowd_camouflage']['luck'])}` and `{_pct(hp_arch['deep_crowd_camouflage']['acc'])}` "
            f"`{hp_arch['deep_crowd_camouflage']['n']}/{hp_arch['deep_crowd_camouflage']['n']}` accuracy on "
            f"`deep_crowd_camouflage`, `{_signed(hp_arch['low_tempo_stealth']['luck'])}` on `low_tempo_stealth`, "
            f"`{_signed(hp_arch['high_tempo_exposed']['luck'])}` on `high_tempo_exposed`) and "
            f"every department-size stratum (`{_signed(hp_dept['compact_dept']['luck'])}` compact, "
            f"`{_signed(hp_dept['standard_dept']['luck'])}` standard, `{_signed(hp_dept['crowded_dept']['luck'])}` and "
            f"`{_pct(hp_dept['crowded_dept']['acc'])}` `{hp_dept['crowded_dept']['n']}/{hp_dept['crowded_dept']['n']}` "
            f"accuracy on `crowded_dept`). On `medium 0-29`, the solver achieves `{_pct(med_solv['precision_when_accusing'])}` "
            f"precision when accusing (`{med_solv['wrong_accusations']}` wrong accusations, `{med_solv['abstentions']}` "
            "calibrated abstentions)."
        ),
        (
            "- **Primary hard frontier gap is concentrated in crowded departments and low-tempo stealth moles, NOT decoy traps:** "
            f"On primary hard `0-29`, OpenCode `gemini-4-carbon` trails the solver by "
            f"`{_signed(oc_c_h0['overall']['l_gap'])}` V/episode luck-adjusted (`{_signed(oc_c_h0['overall']['r_gap'])}` raw). "
            f"Stratification shows the gap is driven by **`{c_arch_top[0]['stratum']}`** "
            f"(`n={c_arch_top[0]['n']}`, luck-adjusted gap `{_signed(c_arch_top[0]['luck_adj_gap'])}`, raw gap "
            f"`{_signed(c_arch_top[0]['raw_gap'])}`, accuracy `{_pct(c_arch_top[0]['accuracy'])}` vs solver "
            f"`{_pct(sol_h0_top_arch['acc'])}`) and **`{c_arch_top[1]['stratum']}`** "
            f"(`n={c_arch_top[1]['n']}`, luck-adjusted gap `{_signed(c_arch_top[1]['luck_adj_gap'])}`), and structurally by "
            f"**`{c_dept_top[0]['stratum']}`** (`mole_dept_size >= 11`, `n={c_dept_top[0]['n']}`, luck-adjusted gap "
            f"`{_signed(c_dept_top[0]['luck_adj_gap'])}`, raw gap `{_signed(c_dept_top[0]['raw_gap'])}`) and "
            f"**`{c_sol_top[0]['stratum']}`** (`solver_day 9-12`, `n={c_sol_top[0]['n']}`, luck-adjusted gap "
            f"`{_signed(c_sol_top[0]['luck_adj_gap'])}`). On `decoy_entangled` (`n={oc_c_decoy['n']}`), "
            "`gemini-4-carbon` is not fooled by the angry-message decoy "
            f"(luck-adjusted `{_signed(oc_c_decoy['luck'])}` vs solver `{_signed(sol_h0_decoy['luck'])}`).{gpt_contrast}"
        ),
        (
            "- **Extension hard `30-59` confirms both baseline scaling fragility and partial-cohort selection structure:** "
            f"Across full `seeds 30-59` (`n=30`), `grok_tactics` suffers its largest luck-adjusted deficit on "
            f"`{g_arch_top[0]['stratum']}` (`{_signed(g_arch_top[0]['luck_adj_gap'])}` V/ep) while `heuristic` "
            f"collapses on `{h_arch_top[0]['stratum']}` (`{_signed(h_arch_top[0]['luck_adj_gap'])}` V/ep) "
            f"and `{h_arch_top[1]['stratum']}` (`{_signed(h_arch_top[1]['luck_adj_gap'])}` V/ep). Meanwhile, the "
            f"deduplicated `6`-seed OpenCode `gemini-4-carbon` extension union (`seeds {u6_sel['union_seeds']}`, "
            f"committed G1 precedence on shared `seed 34`: G1 raw `{_signed(u6_sel['seed_34_g1_score'])}` / "
            f"luck-adj `{_signed(u6_sel['seed_34_g1_luck_adj'])}` vs FR8 raw `{_signed(u6_sel['seed_34_fr8_score'])}` / "
            f"luck-adj `{_signed(u6_sel['seed_34_fr8_luck_adj'])}`) contains "
            f"**`{u6_sel['deep_crowd_camouflage_count_in_union_6']}/{len(u6_sel['union_seeds'])}` `deep_crowd_camouflage` seeds** "
            f"and **`{u6_sel['crowded_dept_count_in_union_6']}/{len(u6_sel['union_seeds'])}` `crowded_dept` (`>=11`) seeds** "
            f"(mean `mole_dept_size = {_f(u6_sel['mean_mole_dept_size_union_6'], 2)}` vs "
            f"`{_f(u6_sel['mean_mole_dept_size_hard_0_29'], 2)}` on `hard 0-29` and "
            f"`{_f(u6_sel['mean_mole_dept_size_hard_30_59'], 2)}` on `hard 30-59`), structurally explaining why "
            "early quota-constrained completions outperform the full-distribution primary benchmark."
        ),
        flash_gate_bullet,
        "",
        _md_heading(2, "2. Deterministic World & Mole Policy Genome Extraction (90 Seeds)"),
        "",
        (
            "In `canary/env.py`, standard `medium` and `hard` episodes (`tier not in TRACKS`) run "
            f"`DEFAULT_STRATEGY` (`{gen['hard']['mole_policy_name']}`: `{gen['hard']['mole_dsl_rule_count']}` conditional "
            f"Mole DSL rules, `{gen['hard']['mole_dsl_default_leak_selector']}` leak selector weighted by `careful_mole` "
            "`1 - share`, and Poisson framing), whereas evolved HoF DSL and RL policies apply on the `hard_forge` "
            "and `hard_rl` tracks. Because `p_single_dept_recipients = 0.0` on both `medium` (`4` depts, `20` staff) "
            "and `hard` (`5` depts, `40` staff), **100% of regular documents are sent to two whole departments**: "
            "regular document leaks narrow suspects down to `mole_dept`, after which **only canary variants** (and weak "
            "after-hours/interview LRs) can separate the `mole_dept_size` colleagues."
        ),
        "",
        "| seed block | n | mole policy | mean mole dept size | same-dept decoy seeds | mean decoy doc overlap | mean mole doc share | realized mole log density / day | mean passive leaks (expected) | archetype counts (`decoy` / `crowd` / `stealth` / `exposed`) | dept counts (`compact` / `standard` / `crowded`) |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|---|---|",
    ]

    for blk_label, tier_key, blk_key in (
        ("medium (0-29)", "medium", "medium_0_29"),
        ("hard (0-29)", "hard", "hard_0_29"),
        ("hard (30-59)", "hard", "hard_30_59"),
    ):
        pk = sp[blk_key]
        gm = gen[tier_key]
        ac = pk["mole_archetype_counts"]
        dc = pk["dept_stratum_counts"]
        lines.append(
            f"| {blk_label} | {pk['n_seeds']} | `{gm['mole_policy_name']}` | "
            f"{_f(pk['mean_mole_dept_size'], 2)} | {pk['same_dept_decoy_count']}/{pk['n_seeds']} | "
            f"{_f(pk['mean_decoy_doc_overlap_count'], 1)} | {_pct(pk['mean_mole_doc_share'])} | "
            f"{_f(pk['mean_realized_doc_access_density'], 2)} | "
            f"{_f(pk['mean_passive_leak_count'], 2)} ({_f(gm['expected_passive_leaks'], 2)}) | "
            f"{ac['decoy_entangled']} / {ac['deep_crowd_camouflage']} / "
            f"{ac['low_tempo_stealth']} / {ac['high_tempo_exposed']} | "
            f"{dc['compact_dept']} / {dc['standard_dept']} / {dc['crowded_dept']} |"
        )

    lines.extend(
        [
            "",
            "Seed-intrinsic stratification rules (zero dependence on frontier trajectories):",
            "- **`decoy_entangled`:** `same_dept_decoy == True` (`100%` regular-document overlap between mole and angry-message decoy, plus `50%` framed after-hours log share on the decoy).",
            "- **`deep_crowd_camouflage`:** non-entangled mole in a department of size `>= floor(n_employees / n_depts) + 2` (`>= 7` on `medium`, `>= 10` on `hard`), requiring multi-round 3-variant canary splitting inside `mole_dept`.",
            "- **`low_tempo_stealth`:** non-entangled mole in a compact/standard department with realized passive leaks `< n_days * p_leak` (`<= 10` on `medium`, `<= 13` on `hard`).",
            "- **`high_tempo_exposed`:** non-entangled mole in a compact/standard department with realized passive leaks `>= n_days * p_leak` (`>= 11` on `medium`, `>= 14` on `hard`).",
            "",
            _md_heading(2, "3. Primary Hard Seeds 0-29 Stratified Gap (Locked Headline Block)"),
            "",
            _md_heading(3, "3.1 By Realized Mole Behavioral Archetype"),
            "",
            *_render_stratum_rows(h0_cohorts, "by_mole_archetype", MOLE_ARCHETYPES),
            "",
            _md_heading(3, "3.2 By Mole Department Size & Solver Isolation Horizon"),
            "",
            *_render_stratum_rows(h0_cohorts, "by_dept_stratum", DEPT_STRATA),
            "",
            *_render_stratum_rows(h0_cohorts, "by_solver_difficulty", SOLVER_DIFFICULTY_STRATA),
            "",
            _md_heading(2, "4. Primary + FR8 Medium Seeds 0-29 Stratified Gap"),
            "",
            (
                f"On `medium` (`seeds 0-29`, `n={oc_c_m0['n']}`), OpenCode `gemini-4-carbon` achieves "
                f"`{_pct(oc_c_m0['overall']['acc'])}` accuracy across all four mole archetypes "
                f"(`{_signed(oc_c_m0['overall']['luck'])}` luck-adjusted vs solver "
                f"`{_signed(sol_m0['overall']['luck'])}`), whereas FR8 OpenCode `gemini-3.5-flash` "
                f"(`{_signed(oc_f_m0['overall']['luck'])}` luck-adjusted, gap "
                f"`{_signed(oc_f_m0['overall']['l_gap'])}`) collapses specifically on `low_tempo_stealth` "
                f"(`n={oc_f_m0_stealth['n']}`, accuracy `{_pct(oc_f_m0_stealth['acc'])}`, "
                f"luck-adjusted `{_signed(oc_f_m0_stealth['luck'])}`, gap `{_signed(oc_f_m0_stealth['l_gap'])}`), "
                f"and in-process `gemini-4-carbon` (`{_signed(ip_c_m0['overall']['luck'])}` luck-adjusted) "
                "drops most in `crowded_dept` (`>= 7` colleagues, luck-adjusted gap "
                f"`{_signed(ip_c_m0_crowd['l_gap'])}`):"
            ),
            "",
            *_render_stratum_rows(m0_cohorts, "by_mole_archetype", MOLE_ARCHETYPES),
            "",
            _md_heading(2, "5. Extension Hard Seeds 30-59: Reference, Baselines, G1, FR8, and 6-Seed Union"),
            "",
            (
                "Extension cohorts on `hard` (`seeds 30-59`) pair `solver` (`n=30`), `grok_tactics` (`n=30`), and "
                "`heuristic` (`n=30`) on all 30 seeds, alongside pre-registered G1 `opencode-gemini-4-carbon-ext` "
                f"(`seeds {g1_h30['seeds']}`, `n={g1_h30['n']}`), FR8 `opencode:google/gemini-4-carbon` replication "
                f"(`seeds {fr8_h30['seeds']}`, `n={fr8_h30['n']}`), and their deduplicated `{u6_h30['n']}`-seed union "
                f"(`seeds {u6_h30['seeds']}`, `n={u6_h30['n']}`, committed G1 precedence on `seed 34`), each paired "
                "against the exact same seeds in `solver_hard_30_59`:"
            ),
            "",
            _md_heading(3, "5.1 Extension Hard 30-59 by Mole Archetype"),
            "",
            *_render_stratum_rows(h30_cohorts, "by_mole_archetype", MOLE_ARCHETYPES),
            "",
            _md_heading(3, "5.2 Extension Hard 30-59 by Mole Department Size Stratum"),
            "",
            *_render_stratum_rows(h30_cohorts, "by_dept_stratum", DEPT_STRATA),
            "",
            _md_heading(2, "6. Pooled Hard 0-59 Reference Solver Solvability Proof (n=60)"),
            "",
            "| pooled hard 0-59 stratum | n | solver raw score | solver luck-adj. score | solver accuracy | precision when accusing | abstention rate | mean accuse day |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for arch in MOLE_ARCHETYPES:
        st = hp_arch[arch]
        lines.append(
            f"| mole archetype: `{arch}` | {st['n']} | {_signed(st['raw'])} | "
            f"{_signed(st['luck'])} | {_pct(st['acc'])} | "
            f"{_pct(st['prec'])} | {_pct(st['abst'])} | "
            f"{_f(st['day'], 1)} |"
        )
    for ds in DEPT_STRATA:
        st = hp_dept[ds]
        lines.append(
            f"| dept size: `{ds}` | {st['n']} | {_signed(st['raw'])} | "
            f"{_signed(st['luck'])} | {_pct(st['acc'])} | "
            f"{_pct(st['prec'])} | {_pct(st['abst'])} | "
            f"{_f(st['day'], 1)} |"
        )

    lines.extend(
        [
            "",
            (
                f"Conclusion: across all `{hard_pooled['n']}` evaluated hard worlds (`0-59`) and "
                f"`{med_solv['n']}` medium worlds (`0-29`), no mole archetype or department stratum is broken "
                f"or unsolvable. The Bayesian reference solver maintains `{_signed(min_arch_luck)}` to "
                f"`{_signed(max_arch_luck)}` luck-adjusted value across every hard mole archetype "
                f"(`{_pct(hp_arch['deep_crowd_camouflage']['acc'])}` accuracy on all "
                f"`{hp_arch['deep_crowd_camouflage']['n']}/{hp_arch['deep_crowd_camouflage']['n']}` "
                f"`deep_crowd_camouflage` worlds and `{_pct(hp_dept['crowded_dept']['acc'])}` on all "
                f"`{hp_dept['crowded_dept']['n']}/{hp_dept['crowded_dept']['n']}` `crowded_dept` worlds), "
                "whereas frontier models that under-invest daily actions in `plant_canary` lose posterior "
                "resolution precisely where intra-departmental anonymity pools (`>= 10-14` staff) or below-average "
                "leak tempo (`low_tempo_stealth`) demand sustained multi-canary bisection."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(root: Path = ROOT, out_json: Path | None = None, out_md: Path | None = None) -> int:
    jpath = out_json or default_json_path(root)
    mpath = out_md or default_md_path(root)
    audit = compute_audit(root=root, verify_replays=True, enforce_expected_counts=True)
    jblob = serialize_audit_json(audit)
    mblob = render_markdown(audit)
    jpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    jpath.write_text(jblob, encoding="utf-8")
    mpath.write_text(mblob, encoding="utf-8")
    return 0


def check_outputs(root: Path = ROOT, out_json: Path | None = None, out_md: Path | None = None) -> int:
    jpath = out_json or default_json_path(root)
    mpath = out_md or default_md_path(root)
    if not jpath.exists() or not mpath.exists():
        print(f"missing output file(s): {jpath}, {mpath}", file=sys.stderr)
        return 1
    raw_bytes = jpath.read_bytes()
    if len(raw_bytes) > MAX_JSON_BYTES:
        print(
            f"JSON output {jpath} is {len(raw_bytes)} bytes, exceeding {MAX_JSON_BYTES}",
            file=sys.stderr,
        )
        return 1
    try:
        disk_json = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        print(f"invalid JSON in {jpath}: {exc}", file=sys.stderr)
        return 1
    expected_audit = compute_audit(root=root, verify_replays=True, enforce_expected_counts=True)
    expected_json = json.loads(serialize_audit_json(expected_audit))
    if not approx_equal(disk_json, expected_json, tol=1e-6):
        print(f"JSON mismatch in {jpath}", file=sys.stderr)
        return 1
    disk_md = mpath.read_text(encoding="utf-8")
    expected_md = render_markdown(expected_audit)
    if disk_md != expected_md:
        print(f"Markdown mismatch in {mpath}", file=sys.stderr)
        return 1
    summ = expected_audit["summary"]
    print(
        f"OK mole_stratified_gap=PASS worlds={summ['worlds_extracted']} "
        f"committed_replays={summ['committed_v14_verified']} "
        f"replication_replays={summ['replication_v14_verified']} "
        f"combined_replays={summ['total_pool_episodes_replay_verified']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Pure-CPU mole-archetype and seed-difficulty stratification audit for Canary v1.4."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--write", action="store_true")
    grp.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        return write_outputs(root=args.root, out_json=args.out_json, out_md=args.out_md)
    return check_outputs(root=args.root, out_json=args.out_json, out_md=args.out_md)


if __name__ == "__main__":
    raise SystemExit(main())
