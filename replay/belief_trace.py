from __future__ import annotations

from collections import Counter
import math
import random
from typing import Any

from canary.rules import (
    KNOWN_V_MODE,
    KNOWN_V_MODE_HISTORY,
    TIERS,
    TIERS_HISTORY,
    TIERS_V13,
    TIERS_VERSION,
    TRACKS,
    TierParams,
    tier_params_for_episode,
)
from canary.solver.belief import MAX_STATES, _fallback, _weight, behaviour_logliks
from canary.solver.policy import LABELS, SolverPolicy, accuse_value
from canary.solver.regret import _gini, q_continue
from canary.types import EpisodeResult, Step

_TIERS_V14: dict[str, TierParams] = dict(TIERS)

_OBS_NOOP_TOOLS: frozenset[str] = frozenset({
    "accuse",
    "read_message",
    "restrict_access",
    "unrestrict_access",
})

__all__ = [
    "compute_belief_trace",
    "resolve_episode_params",
]


def _explicit_tiers_version(ep: dict[str, Any]) -> str | None:
    top = ep.get("tiers_version")
    if isinstance(top, str) and top.strip():
        return top.strip()
    meta = ep.get("meta")
    if isinstance(meta, dict):
        meta_ver = meta.get("tiers_version")
        if isinstance(meta_ver, str) and meta_ver.strip():
            return meta_ver.strip()
    run_meta = ep.get("run_meta")
    if isinstance(run_meta, dict):
        run_ver = run_meta.get("tiers_version")
        if isinstance(run_ver, str) and run_ver.strip():
            return run_ver.strip()
    return None


def resolve_episode_params(ep: dict[str, Any]) -> TierParams:
    tier = str(ep.get("tier") or "hard")
    base_tier = TRACKS.get(tier, tier)
    version = _explicit_tiers_version(ep)
    if version in ("v1.2", "v1.3") and base_tier in TIERS_V13:
        return TIERS_V13[base_tier]
    if version is not None and version in TIERS_HISTORY:
        hist = TIERS_HISTORY[version]
        if base_tier in hist:
            return hist[base_tier]
    if version == "v1.4" and base_tier in _TIERS_V14:
        return _TIERS_V14[base_tier]
    return tier_params_for_episode(tier, ep.get("steps") or ())


def _resolve_version_and_params(ep: dict[str, Any]) -> tuple[str, TierParams]:
    params = resolve_episode_params(ep)
    explicit = _explicit_tiers_version(ep)
    if explicit is not None:
        return explicit, params
    tier = str(ep.get("tier") or "hard")
    base_tier = TRACKS.get(tier, tier)
    if (
        base_tier in TIERS_V13
        and params == TIERS_V13[base_tier]
        and params != _TIERS_V14.get(base_tier)
    ):
        return "v1.3", params
    return TIERS_VERSION, params


def _leak_timing_known_for_version(tiers_version: str) -> bool:
    known_v_mode = KNOWN_V_MODE_HISTORY.get(tiers_version, KNOWN_V_MODE)
    return not bool(known_v_mode)


def _is_numeric(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _compute_break_even_p(known_v: float, wrong_accusation_score: float) -> float:
    abs_ws = abs(float(wrong_accusation_score))
    kv = max(0.0, float(known_v))
    denom = kv + abs_ws
    if denom <= 0.0:
        return 0.0
    return min(1.0, max(0.0, abs_ws / denom))


def _top_from_posterior(post: dict[str, float]) -> tuple[str, float]:
    best_emp, best_p = min(post.items(), key=lambda kv: (-kv[1], kv[0]))
    return str(best_emp), float(best_p)


def _to_step(raw: Step | dict[str, Any], idx: int) -> Step:
    if isinstance(raw, Step):
        return Step(
            t=int(raw.t),
            day=int(raw.day),
            tool=str(raw.tool),
            args=dict(raw.args) if isinstance(raw.args, dict) else {},
            result=(
                dict(raw.result)
                if isinstance(raw.result, dict)
                else {"ok": True, "data": {}, "error": None}
            ),
        )
    t_val = raw.get("t", idx)
    day_val = raw.get("day", 1)
    args_val = raw.get("args")
    res_val = raw.get("result")
    return Step(
        t=int(idx if t_val is None else t_val),
        day=int(1 if day_val is None else day_val),
        tool=str(raw.get("tool", "")),
        args=dict(args_val) if isinstance(args_val, dict) else {},
        result=(
            dict(res_val)
            if isinstance(res_val, dict)
            else {"ok": True, "data": {}, "error": None}
        ),
    )


def _to_episode_result(ep: dict[str, Any], steps: list[Step]) -> EpisodeResult:
    raw_meta = ep.get("meta")
    meta_dict = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    raw_score = ep.get("score", 0.0)
    score_val = float(raw_score) if _is_numeric(raw_score) else 0.0
    raw_final_day = ep.get("final_day")
    if _is_numeric(raw_final_day):
        final_day_val = int(raw_final_day)
    else:
        final_day_val = steps[-1].day if steps else 1
    end_reason_val = str(
        ep.get("end_reason") or ("accused" if ep.get("accused") else "horizon")
    )
    return EpisodeResult(
        tier=str(ep.get("tier") or "hard"),
        seed=int(ep.get("seed", 0)),
        agent=str(ep.get("agent") or "unknown"),
        steps=steps,
        score=score_val,
        accused=ep.get("accused"),
        correct=bool(ep.get("correct", False)),
        final_day=final_day_val,
        end_reason=end_reason_val,
        meta=meta_dict,
    )


def _resolve_v_for_luck(ep: dict[str, Any], known_v: float) -> float:
    correct = bool(ep.get("correct", False))
    raw_score = ep.get("score", 0.0)
    score = float(raw_score) if _is_numeric(raw_score) else 0.0
    if correct and score > 0.0:
        return score
    meta = ep.get("meta")
    if isinstance(meta, dict):
        if _is_numeric(meta.get("V_final")):
            return float(meta["V_final"])
        if _is_numeric(meta.get("V")):
            return float(meta["V"])
    return float(known_v)


def _classify_verdict(
    correct: bool,
    p_accused: float,
    break_even_p: float,
) -> str:
    if p_accused >= break_even_p:
        return "justified" if correct else "wrong_justified"
    return "lucky" if correct else "premature_wrong"


def _compute_leak_lp(
    obs: Any,
    params: TierParams,
    choice_temper: float,
    noleak_temper: float,
) -> dict[str, float]:
    emps = obs.employees
    if not emps:
        return {}
    window = getattr(params, "leak_window_days", 3)
    delays = tuple(params.delay_choices)
    pd = 1.0 / len(delays)
    n = len(emps) or 1

    surfaced: dict[str, int] = {}
    for it in obs.feed:
        prev_sd = surfaced.get(it.doc_id)
        if prev_sd is None or it.surfaced_day < prev_sd:
            surfaced[it.doc_id] = it.surfaced_day

    sorted_feed = sorted(obs.feed, key=lambda x: (x.surfaced_day, x.doc_id))
    seen_ids: set[str] = set()
    items = []
    for it in sorted_feed:
        if it.doc_id not in seen_ids:
            seen_ids.add(it.doc_id)
            items.append(it)

    days = sorted(obs.closed_days)
    if not days:
        init_lp = 0.0 if not items else -math.inf
        return {s: init_lp for s in emps}

    a = getattr(params, "fingerprint_accuracy", 1.0)
    item_var_info: list[tuple[dict[str, str], str, int, float] | None] = []
    canary_var_dicts: list[dict[str, str]] = []
    for it in items:
        doc = obs.docs.get(it.doc_id)
        if not (it.variant and doc and doc.variants):
            item_var_info.append(None)
        else:
            k = len(set(doc.variants.values()))
            alt = (1.0 - a) / (k - 1) if k > 1 else 0.0
            item_var_info.append((doc.variants, it.variant, k, alt))
            canary_var_dicts.append(doc.variants)

    known = obs.leak_timing_known
    today = obs.today
    min_delay = min(delays)
    latest = [it.surfaced_day - min_delay for it in items]
    log_noleak = noleak_temper * math.log(max(1e-12, 1.0 - params.p_leak))
    log_p_leak = math.log(params.p_leak)
    careful = params.careful_mole

    all_docs = list(obs.docs.values())
    all_weights = [_weight(doc, n, careful) for doc in all_docs]
    relevant_doc_indices: set[int] = set()
    day_specs: list[
        tuple[
            list[tuple[str, Any, float]],
            bool,
            bool,
            float,
            float,
            list[tuple[int, str]],
            tuple[int, ...],
        ]
    ] = []

    n_items = len(items)
    for idx, d in enumerate(days):
        day_docs: list[tuple[str, Any, float]] = []
        for d_idx, doc in enumerate(all_docs):
            if d - window + 1 <= doc.day <= d:
                sd = surfaced.get(doc.doc_id)
                if sd is not None and sd <= d:
                    continue
                day_docs.append((doc.doc_id, doc.recipients, all_weights[d_idx]))
                relevant_doc_indices.add(d_idx)
        allow_leak = (d in obs.leak_days) if known else True
        allow_none = (d not in obs.leak_days) if known else True
        pend = sum(pd for dl in delays if d + dl > today)
        log_pend = math.log(pend) if pend > 0.0 else 0.0
        day_items = [
            (j, it.doc_id)
            for j, it in enumerate(items)
            if (it.surfaced_day - d) in delays
        ]
        nd = days[idx + 1] if idx + 1 < len(days) else None
        must_used = tuple(
            j for j in range(n_items) if not (nd is not None and latest[j] >= nd)
        )
        day_specs.append(
            (day_docs, allow_leak, allow_none, pend, log_pend, day_items, must_used)
        )

    relevant_recipients = [all_docs[i].recipients for i in sorted(relevant_doc_indices)]
    sig_to_lp: dict[tuple[tuple[int, ...], tuple[str | None, ...]], float] = {}
    leak_lp: dict[str, float] = {}

    for s in emps:
        sig = (
            tuple(idx for idx, rec in enumerate(relevant_recipients) if s in rec),
            tuple(vd.get(s) for vd in canary_var_dicts),
        )
        lp_val = sig_to_lp.get(sig)
        if lp_val is None:
            vf: list[float] = []
            for info in item_var_info:
                if info is None:
                    vf.append(1.0)
                else:
                    vmap, target_var, k, alt = info
                    mine = vmap.get(s)
                    if mine == target_var:
                        vf.append(a)
                    elif mine is None or k <= 1:
                        vf.append(0.0)
                    else:
                        vf.append(alt)

            states: dict[tuple[int, ...], float] = {(): 0.0}
            impossible = False
            for (
                day_docs,
                allow_leak,
                allow_none,
                pend,
                log_pend,
                day_items,
                must_used,
            ) in day_specs:
                wdoc = {
                    doc_id: w_val
                    for doc_id, rec, w_val in day_docs
                    if s in rec
                }
                w_total = sum(wdoc.values())
                nxt: dict[tuple[int, ...], float] = {}

                for used, lw in states.items():
                    if allow_none:
                        nl_lw = lw + (log_noleak if w_total > 0.0 else 0.0)
                        cur = nxt.get(used)
                        nxt[used] = (
                            nl_lw
                            if cur is None
                            else max(cur, nl_lw) + math.log1p(math.exp(-abs(cur - nl_lw)))
                        )
                    if allow_leak and w_total > 0.0:
                        base = lw + log_p_leak
                        for j, doc_id in day_items:
                            if j in used or vf[j] <= 0.0:
                                continue
                            w_j = wdoc.get(doc_id)
                            if w_j is not None:
                                f = (w_j / w_total) ** choice_temper * pd * vf[j]
                                if f > 0.0:
                                    nkey = tuple(sorted((*used, j)))
                                    nlw = base + math.log(f)
                                    cur = nxt.get(nkey)
                                    nxt[nkey] = (
                                        nlw
                                        if cur is None
                                        else max(cur, nlw) + math.log1p(math.exp(-abs(cur - nlw)))
                                    )
                        if pend > 0.0:
                            plw = base + log_pend
                            cur = nxt.get(used)
                            nxt[used] = (
                                plw
                                if cur is None
                                else max(cur, plw) + math.log1p(math.exp(-abs(cur - plw)))
                            )

                if must_used:
                    alive = {
                        used: lw
                        for used, lw in nxt.items()
                        if all(j in used for j in must_used)
                    }
                else:
                    alive = nxt
                if len(alive) > MAX_STATES:
                    alive = dict(
                        sorted(alive.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_STATES]
                    )
                states = alive
                if not states:
                    impossible = True
                    break

            if impossible:
                lp_val = -math.inf
            else:
                full = [lw for used, lw in states.items() if len(used) == n_items]
                if not full:
                    lp_val = -math.inf
                else:
                    m_full = max(full)
                    lp_val = m_full + math.log(sum(math.exp(x - m_full) for x in full))

            sig_to_lp[sig] = lp_val
        leak_lp[s] = lp_val
    return leak_lp


def _combine_posterior(
    obs: Any,
    params: TierParams,
    behaviour_temper: float,
    leak_lp: dict[str, float],
    beh: dict[str, float],
) -> dict[str, float]:
    logs: dict[str, float] = {}
    for s in obs.employees:
        lp = leak_lp[s]
        if behaviour_temper > 0 and lp > -math.inf:
            lp += behaviour_temper * beh[s]
            for who, ev in obs.interviews:
                if who == s:
                    pe = params.p_evasive_innocent
                    pm = min(0.999, pe * params.interview_lr)
                    lp += behaviour_temper * (
                        math.log(pm / pe) if ev else math.log((1 - pm) / (1 - pe))
                    )
        if obs.decoy is not None and s == obs.decoy:
            lp = -math.inf
        logs[s] = lp
    m = max(logs.values()) if logs else -math.inf
    if m == -math.inf:
        return _fallback(obs)
    z = sum(math.exp(v - m) for v in logs.values())
    return {s: math.exp(v - m) / z for s, v in logs.items()}


def _fast_sp_belief(sp: SolverPolicy) -> dict[str, float]:
    o = sp.obs
    o.leak_timing_known = sp.v_drops_reveal_leaks()
    assert sp.P is not None
    leak_lp = _compute_leak_lp(o, sp.P, sp.choice_temper, sp.noleak_temper)
    beh = behaviour_logliks(o, sp.P) if sp.behaviour_temper > 0 else {}
    return _combine_posterior(o, sp.P, sp.behaviour_temper, leak_lp, beh)


class _IncrementalBelief:
    def __init__(
        self,
        sp: SolverPolicy,
        default_employees: list[str] | None = None,
        force_leak_timing_known: bool | None = None,
    ) -> None:
        self.sp = sp
        self.default_employees = default_employees
        self.force_leak_timing_known = force_leak_timing_known
        self.leak_dirty = True
        self.beh_dirty = True
        self.post_dirty = True
        self.leak_lp: dict[str, float] = {}
        self.beh: dict[str, float] = {}
        self.post: dict[str, float] = {}
        self._last_lt_known: bool | None = None

    def ingest(self, st: Step) -> None:
        sp = self.sp
        o = sp.obs
        r = st.result or {}
        if not r.get("ok", True):
            if self.default_employees and not o.employees:
                o.employees = list(self.default_employees)
                self.leak_dirty = self.beh_dirty = self.post_dirty = True
            if self.force_leak_timing_known is not None:
                o.leak_timing_known = self.force_leak_timing_known
            return
        tl = st.tool
        if tl == "list_employees":
            prev_emps = list(o.employees)
            sp._ingest(st)
            if self.default_employees and not o.employees:
                o.employees = list(self.default_employees)
            if o.employees != prev_emps:
                self.leak_dirty = self.beh_dirty = self.post_dirty = True
        elif tl == "list_documents":
            prev_docs = dict(o.docs)
            sp._ingest(st)
            if o.docs != prev_docs:
                self.leak_dirty = self.post_dirty = True
        elif tl == "check_leak_feed":
            prev_feed = list(o.feed)
            sp._ingest(st)
            if o.feed != prev_feed:
                self.leak_dirty = self.post_dirty = True
        elif tl == "plant_canary":
            sp._ingest(st)
            data = r.get("data") or {}
            cid = data.get("canary_id") or data.get("doc_id")
            if cid and (o.today in o.closed_days or any(it.doc_id == cid for it in o.feed)):
                self.leak_dirty = self.post_dirty = True
        elif tl in ("advance_day", "status"):
            prev_state = (o.today, frozenset(o.closed_days), frozenset(o.leak_days))
            sp._ingest(st)
            if (o.today, frozenset(o.closed_days), frozenset(o.leak_days)) != prev_state:
                self.leak_dirty = self.post_dirty = True
        elif tl == "read_access_logs":
            sp._ingest(st)
            self.beh_dirty = self.post_dirty = True
        elif tl == "search_messages":
            prev_decoy = o.decoy
            sp._ingest(st)
            if o.decoy != prev_decoy:
                self.beh_dirty = self.post_dirty = True
        elif tl == "interview":
            sp._ingest(st)
            self.post_dirty = True
        else:
            sp._ingest(st)
        if self.default_employees and not o.employees:
            o.employees = list(self.default_employees)
            self.leak_dirty = self.beh_dirty = self.post_dirty = True
        if self.force_leak_timing_known is not None:
            o.leak_timing_known = self.force_leak_timing_known

    def belief(self) -> dict[str, float]:
        sp = self.sp
        o = sp.obs
        lt_known = (
            self.force_leak_timing_known
            if self.force_leak_timing_known is not None
            else sp.v_drops_reveal_leaks()
        )
        if lt_known != self._last_lt_known:
            self.leak_dirty = self.post_dirty = True
            self._last_lt_known = lt_known
        o.leak_timing_known = lt_known
        if not self.post_dirty:
            return self.post
        assert sp.P is not None
        if self.leak_dirty:
            self.leak_lp = _compute_leak_lp(o, sp.P, sp.choice_temper, sp.noleak_temper)
            self.leak_dirty = False
        if sp.behaviour_temper > 0 and self.beh_dirty:
            self.beh = behaviour_logliks(o, sp.P)
            self.beh_dirty = False
        self.post = _combine_posterior(o, sp.P, sp.behaviour_temper, self.leak_lp, self.beh)
        self.post_dirty = False
        return self.post


def _fast_solver_gini(sp: SolverPolicy, post: dict[str, float]) -> float:
    P = sp.P
    assert P is not None
    if (
        sp.adaptive
        or sp.alternate
        or sp.design == "balanced"
        or (sp.design == "auto" and not P.careful_mole)
        or sp.utility != "mi"
    ):
        return float(_gini(post, sp.partition(post)))

    o = sp.obs
    k = P.max_variants
    n = len(o.employees) or 1
    alive = [e for e in post if post[e] > 1e-4 and e not in sp.restricted]
    if len(alive) <= 1:
        return float(_gini(post, {}))

    win_docs = [
        d
        for d in o.docs.values()
        if not d.is_canary and d.day >= o.today - P.leak_window_days
    ]
    nreg_s = {e: sum(1 for d in win_docs if e in d.recipients) for e in post}
    pos_emps = [(e, p, max(1.0, float(nreg_s[e]))) for e, p in post.items() if p > 0.0]
    win_days = P.leak_window_days
    p_leak = P.p_leak
    q_cache: dict[tuple[int, float], tuple[float, float]] = {}

    rng = random.Random(f"canary:{o.today}:{len(o.feed)}")
    fracs = sp.coverages

    def _candidates():
        if sp.tiny:
            top = sorted(alive, key=lambda e: (-post[e], e))
            for per in (1, 2):
                for m in range(1, k + 1):
                    rec = top[: m * per]
                    if len(rec) < m * per:
                        continue
                    yield {e: LABELS[i // per] for i, e in enumerate(rec)}
        sorted_alive = sorted(alive, key=lambda e: -post[e])
        n_alive = len(alive)
        for f in fracs:
            for t in range(16):
                order = sorted_alive if t == 0 else rng.sample(alive, n_alive)
                rec: list[str] = []
                m_sum = 0.0
                for e in order:
                    if m_sum >= f - 1e-9 and rec:
                        break
                    rec.append(e)
                    m_sum += post[e]
                ng = min(k, len(rec))
                mass = [0.0] * ng
                groups: list[list[str]] = [[] for _ in range(ng)]
                for e in rec:
                    g = min(range(ng), key=lambda i: (mass[i], len(groups[i])))
                    groups[g].append(e)
                    mass[g] += post[e]
                yield {e: LABELS[i] for i, grp in enumerate(groups) for e in grp}

    best: dict[str, str] = {}
    best_u = -1.0
    max_cand = sp.max_candidates
    for n_eval, asg in enumerate(_candidates()):
        if n_eval >= max_cand:
            break
        len_asg = len(asg)
        w = max(0.0, 1.0 - len_asg / n)
        po: dict[str, float] = {}
        po_none = 0.0
        hcond = 0.0
        if w <= 0.0:
            for _, p, _ in pos_emps:
                po_none += p
        else:
            for e, p, nr_m1 in pos_emps:
                lab = asg.get(e)
                if lab is None:
                    po_none += p
                else:
                    q_key = (len_asg, nr_m1)
                    q_pair = q_cache.get(q_key)
                    if q_pair is None:
                        per_day = p_leak * w / (w + nr_m1)
                        q_val = 1.0 - (1.0 - per_day) ** win_days
                        if q_val > 0.0:
                            ent_val = q_val * math.log(q_val) + (
                                (1.0 - q_val) * math.log(1.0 - q_val)
                                if q_val < 1.0
                                else 0.0
                            )
                        else:
                            ent_val = 0.0
                        q_pair = (q_val, ent_val)
                        q_cache[q_key] = q_pair
                    q_val, ent_val = q_pair
                    po_none += p * (1.0 - q_val)
                    if q_val > 0.0:
                        po[lab] = po.get(lab, 0.0) + p * q_val
                        hcond -= p * ent_val
        h = -(po_none * math.log(po_none) if po_none > 0.0 else 0.0)
        for v in po.values():
            if v > 0.0:
                h -= v * math.log(v)
        u = h - hcond
        if u > best_u:
            best = asg
            best_u = u

    return float(_gini(post, best))


def _fast_attribute(episode: EpisodeResult) -> list[dict[str, Any]]:
    P = tier_params_for_episode(episode.tier, episode.steps)
    sp = SolverPolicy(P)
    inc = _IncrementalBelief(sp)
    decoy = (episode.meta or {}).get("decoy")
    out: list[dict[str, Any]] = []
    seen_today: Counter[tuple[str, str]] = Counter()
    last_day: int | None = None
    steps = episode.steps
    max_delay = max(P.delay_choices)
    part_cache_key: tuple[int, int, int, frozenset[str], int] | None = None
    part_cache_gini = 0.0
    for i, st in enumerate(steps):
        for prev in steps[sp.seen:i]:
            inc.ingest(prev)
        sp.seen = i
        o = sp.obs
        if not o.employees:
            out.append(dict(t=st.t, day=st.day, action=st.tool, regret=0.0, p_best=None, tags=[]))
            continue
        post = inc.belief()
        V = sp.V
        best = max(post, key=post.get)
        days_left = P.n_days - st.day
        qc = q_continue(post, V, P, days_left)
        vstar = max(accuse_value(post[best], V, P), qc, 0.0)
        tags: list[str] = []
        extra: dict[str, Any] = {}
        regret = 0.0
        if st.day != last_day:
            seen_today.clear()
            last_day = st.day
        key = (st.tool, repr(sorted((st.args or {}).items())))
        seen_today[key] += 1
        ok = (st.result or {}).get("ok", True)
        if st.tool == "accuse":
            e = st.args.get("employee")
            pe = post.get(e, 0.0)
            regret = max(0.0, vstar - accuse_value(pe, V, P))
            extra["p_accused"] = round(pe, 4)
            if pe < 0.6:
                tags.append("premature_accusation")
            if decoy and e == decoy:
                tags.append("decoy_chase")
            pending = [
                d
                for d in o.leak_days
                if not any(0 < it.surfaced_day - d <= max_delay for it in o.feed)
                and d + max_delay >= st.day
            ]
            if pending and pe < 0.9:
                tags.append("ignored_delay")
        elif st.tool == "advance_day":
            regret = max(0.0, accuse_value(post[best], V, P) - max(qc, 0.0))
        elif st.tool == "plant_canary" and ok:
            asg = st.args.get("assignment") or {}
            g_agent = _gini(post, asg)
            non_canary_count = sum(1 for d in o.docs.values() if not d.is_canary)
            cur_part_key = (
                id(post),
                o.today,
                len(o.feed),
                frozenset(sp.restricted),
                non_canary_count,
            )
            if cur_part_key == part_cache_key:
                g_solver = part_cache_gini
            else:
                g_solver = _fast_solver_gini(sp, post)
                part_cache_key = cur_part_key
                part_cache_gini = g_solver
            regret = max(0.0, g_solver - g_agent) * P.p_leak * P.leak_damage * 2 + 0.0
            if g_agent < 0.2:
                tags.append("uninformative_canary")
        elif st.tool == "restrict_access" and ok:
            e = st.args.get("employee")
            regret = P.restrict_cost_per_day * max(1, days_left) * (1 - post.get(e, 0.0))
            if post.get(e, 0.0) < 0.1:
                tags.append("over_restriction")
            if decoy and e == decoy:
                tags.append("decoy_chase")
        if not ok or (seen_today[key] > 1 and st.tool not in ("status", "advance_day")):
            tags.append("budget_waste")
        out.append(
            dict(
                t=st.t,
                day=st.day,
                action=st.tool,
                regret=round(regret, 6),
                p_best=round(post[best], 4),
                tags=tags,
                **extra,
            )
        )
    if episode.end_reason != "accused":
        for prev in steps[sp.seen:]:
            inc.ingest(prev)
        post = inc.belief() if sp.obs.employees else {}
        best_v = max(0.0, accuse_value(max(post.values()), sp.V, P)) if post else 0.0
        out.append(
            dict(
                t=len(steps),
                day=episode.final_day,
                action="(no accusation)",
                regret=round(best_v, 6),
                p_best=round(max(post.values()), 4) if post else None,
                tags=["no_accusation"],
            )
        )
    return out


def compute_belief_trace(ep: dict[str, Any]) -> dict[str, Any]:
    tiers_version, params = _resolve_version_and_params(ep)
    leak_timing_known = _leak_timing_known_for_version(tiers_version)
    default_employees = [f"e{k:02d}" for k in range(params.n_employees)]

    sp = SolverPolicy(params, use_v_drops=leak_timing_known)
    sp.obs.employees = list(default_employees)
    sp.obs.leak_timing_known = leak_timing_known
    inc = _IncrementalBelief(
        sp,
        default_employees=default_employees,
        force_leak_timing_known=leak_timing_known,
    )

    raw_steps = list(ep.get("steps") or [])
    step_objs = [_to_step(s, idx) for idx, s in enumerate(raw_steps)]
    ep_result = _to_episode_result(ep, step_objs)
    attr_rows = _fast_attribute(ep_result)

    curr_post = inc.belief()
    curr_top_suspect, curr_p_top = _top_from_posterior(curr_post)
    init_known_v = 1.0
    init_break_even_p = _compute_break_even_p(
        init_known_v,
        params.wrong_accusation_score,
    )
    initial: dict[str, Any] = {
        "step_index": 0,
        "t": -1,
        "day": 1,
        "posterior": dict(curr_post),
        "p_top": curr_p_top,
        "top_suspect": curr_top_suspect,
        "known_v": init_known_v,
        "break_even_p": init_break_even_p,
    }

    step_traces: list[dict[str, Any]] = []
    accuse_snapshot: tuple[
        int,
        int,
        int,
        Step,
        dict[str, float],
        float,
        str,
        float,
    ] | None = None

    for i, st in enumerate(step_objs):
        post_before = dict(curr_post)
        top_before = curr_top_suspect
        p_top_before = curr_p_top
        known_v_before = max(0.0, float(sp.V))

        ok = bool((st.result or {}).get("ok", True))
        if accuse_snapshot is None and st.tool == "accuse" and ok:
            accuse_snapshot = (
                i + 1,
                int(st.t),
                int(st.day),
                st,
                post_before,
                p_top_before,
                top_before,
                known_v_before,
            )

        inc.ingest(st)
        if inc.post_dirty:
            curr_post = inc.belief()
            curr_top_suspect, curr_p_top = _top_from_posterior(curr_post)

        known_v_after = max(0.0, float(sp.V))
        break_even_after = _compute_break_even_p(
            known_v_after,
            params.wrong_accusation_score,
        )
        attr_item = attr_rows[i] if i < len(attr_rows) else {}
        step_regret = float(attr_item.get("regret", 0.0))
        step_tags = [str(tag) for tag in (attr_item.get("tags") or [])]

        step_traces.append({
            "step_index": i + 1,
            "t": int(st.t),
            "day": int(st.day),
            "tool": str(st.tool),
            "posterior_before": post_before,
            "posterior": dict(curr_post),
            "p_top": curr_p_top,
            "top_suspect": curr_top_suspect,
            "p_top_before": p_top_before,
            "top_suspect_before": top_before,
            "known_v": known_v_after,
            "break_even_p": break_even_after,
            "regret": step_regret,
            "tags": step_tags,
        })

    accuse_audit: dict[str, Any] | None = None
    luck_adjusted_score = 0.0

    if accuse_snapshot is not None:
        (
            acc_step_idx,
            acc_t,
            acc_day,
            acc_st,
            acc_post_before,
            acc_p_top,
            acc_top_suspect,
            acc_known_v,
        ) = accuse_snapshot
        acc_emp_raw = (
            acc_st.args.get("employee")
            or ((acc_st.result or {}).get("data") or {}).get("accused")
            or ep.get("accused")
        )
        accused_str = str(acc_emp_raw) if acc_emp_raw is not None else ""
        correct = bool(ep.get("correct", False))
        p_accused = float(acc_post_before.get(accused_str, 0.0))
        break_even_p = _compute_break_even_p(
            acc_known_v,
            params.wrong_accusation_score,
        )
        v_for_luck = _resolve_v_for_luck(ep, acc_known_v)
        luck_adjusted_score = float(
            p_accused * v_for_luck
            + (1.0 - p_accused) * float(params.wrong_accusation_score)
        )
        verdict = _classify_verdict(correct, p_accused, break_even_p)
        accuse_audit = {
            "step_index": acc_step_idx,
            "t": acc_t,
            "day": acc_day,
            "accused": accused_str,
            "correct": correct,
            "p_accused": p_accused,
            "p_top": float(acc_p_top),
            "top_suspect": str(acc_top_suspect),
            "known_v": float(acc_known_v),
            "v_for_luck": float(v_for_luck),
            "break_even_p": float(break_even_p),
            "luck_adjusted_score": luck_adjusted_score,
            "verdict": verdict,
        }
    elif isinstance(ep.get("accused"), str) and ep["accused"].strip():
        accused_str = ep["accused"].strip()
        correct = bool(ep.get("correct", False))
        acc_step_idx = len(step_traces)
        acc_t = step_traces[-1]["t"] if step_traces else -1
        acc_day = int(
            ep.get("final_day")
            or (step_traces[-1]["day"] if step_traces else 1)
        )
        acc_known_v = (
            step_traces[-1]["known_v"] if step_traces else init_known_v
        )
        p_accused = float(curr_post.get(accused_str, 0.0))
        break_even_p = _compute_break_even_p(
            acc_known_v,
            params.wrong_accusation_score,
        )
        v_for_luck = _resolve_v_for_luck(ep, acc_known_v)
        luck_adjusted_score = float(
            p_accused * v_for_luck
            + (1.0 - p_accused) * float(params.wrong_accusation_score)
        )
        verdict = _classify_verdict(correct, p_accused, break_even_p)
        accuse_audit = {
            "step_index": acc_step_idx,
            "t": acc_t,
            "day": acc_day,
            "accused": accused_str,
            "correct": correct,
            "p_accused": p_accused,
            "p_top": float(curr_p_top),
            "top_suspect": str(curr_top_suspect),
            "known_v": float(acc_known_v),
            "v_for_luck": float(v_for_luck),
            "break_even_p": float(break_even_p),
            "luck_adjusted_score": luck_adjusted_score,
            "verdict": verdict,
        }

    return {
        "tiers_version": tiers_version,
        "n_employees": int(params.n_employees),
        "initial": initial,
        "steps": step_traces,
        "accuse_audit": accuse_audit,
        "luck_adjusted_score": luck_adjusted_score,
        "decoy_inferred": sp.obs.decoy,
    }
