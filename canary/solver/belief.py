"""Posterior over the mole, built ONLY from public observations (things returned by env.call).

Primary evidence (strategy-independent, CONTRACT §7): which days a leak happened (V drops in
`status`), which docs surfaced in the feed (with canary variant), and who held them.
Secondary evidence (tempered, optional): after-hours access counts, interview signals.

Leak model for suspect s (exact enumeration per suspect):
  for each closed day d:
    no leak observed  -> (1 - p_leak) if s had a leakable doc else 1
    leak observed     -> p_leak * [assigned surfaced item x: w(x)/W_s(d) * P(delta = surf - d)]
                                   or [still pending: P(delta > today - d)]
  summed over all injective matchings of surfaced feed items to leak days.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class Doc:
    doc_id: str
    day: int
    recipients: frozenset[str]
    is_canary: bool = False
    variants: dict[str, str] | None = None  # employee -> label (canaries we planted)


@dataclass
class FeedItem:
    surfaced_day: int
    doc_id: str
    variant: str | None = None


@dataclass
class Observations:
    employees: list[str] = field(default_factory=list)
    docs: dict[str, Doc] = field(default_factory=dict)
    leak_days: set[int] = field(default_factory=set)      # closed days with a V-drop leak
    closed_days: set[int] = field(default_factory=set)    # closed days whose leak status is known
    feed: list[FeedItem] = field(default_factory=list)
    today: int = 1
    # behavioural: (employee) -> [n_regular, n_after_hours] summed over days read
    access_counts: dict[str, list[int]] = field(default_factory=dict)
    access_days: dict[str, int] = field(default_factory=dict)  # employee -> #days observed
    interviews: list[tuple[str, bool]] = field(default_factory=list)  # (employee, evasive)


def _leakable(obs: Observations, s: str, d: int, window: int, known_leaked_before: dict[str, int]):
    out = []
    for doc in obs.docs.values():
        if s in doc.recipients and d - window + 1 <= doc.day <= d:
            sd = known_leaked_before.get(doc.doc_id)
            if sd is not None and sd <= d:  # surfaced on/before d => leaked strictly before d
                continue
            out.append(doc)
    return out


def _weight(doc: Doc, n_emp: int, careful: bool) -> float:
    if careful and doc.is_canary:
        return max(0.0, 1.0 - len(doc.recipients) / n_emp)
    return 1.0


def leak_loglik(obs: Observations, s: str, P, choice_temper: float = 1.0, noleak_temper: float = 1.0) -> float:
    """log P(leak-day pattern + feed | mole = s). -inf if impossible."""
    window = getattr(P, "leak_window_days", 3)
    delays = tuple(P.delay_choices)
    pd = 1.0 / len(delays)
    n = len(obs.employees) or 1
    surfaced = {}
    for it in obs.feed:
        surfaced[it.doc_id] = min(it.surfaced_day, surfaced.get(it.doc_id, 10**9))
    items = sorted(obs.feed, key=lambda x: (x.surfaced_day, x.doc_id))
    # dedupe items by doc_id
    seen, uniq = set(), []
    for it in items:
        if it.doc_id not in seen:
            seen.add(it.doc_id)
            uniq.append(it)
    items = uniq

    logp = 0.0
    W, wdoc = {}, {}
    for d in sorted(obs.closed_days):
        lk = _leakable(obs, s, d, window, surfaced)
        W[d] = sum(_weight(x, n, P.careful_mole) for x in lk)
        wdoc[d] = {x.doc_id: _weight(x, n, P.careful_mole) for x in lk}
        if d not in obs.leak_days:
            if W[d] > 0:
                logp += noleak_temper * math.log(max(1e-12, 1.0 - P.p_leak))
    ok_variant = []
    for it in items:
        doc = obs.docs.get(it.doc_id)
        ok_variant.append(not (it.variant and doc and doc.variants)
                          or doc.variants.get(s) == it.variant)
    L = sorted(d for d in obs.leak_days if d in obs.closed_days)
    today = obs.today

    @lru_cache(maxsize=None)
    def rec(i: int, used: frozenset) -> float:
        if i == len(L):
            return 1.0 if len(used) == len(items) else 0.0
        d = L[i]
        if W[d] <= 0:
            return 0.0
        tot = 0.0
        for j, it in enumerate(items):
            if j in used:
                continue
            dl = it.surfaced_day - d
            if dl in delays and it.doc_id in wdoc[d] and ok_variant[j]:
                f = (wdoc[d][it.doc_id] / W[d]) ** choice_temper * pd
                if f > 0:
                    tot += f * rec(i + 1, used | {j})
        pend = sum(pd for dl in delays if d + dl > today)
        if pend > 0:
            tot += pend * rec(i + 1, used)
        return tot

    v = rec(0, frozenset())
    if v <= 0:
        return -math.inf
    return logp + len(L) * math.log(P.p_leak) + math.log(v)


def _pois_logpmf(k: int, lam: float) -> float:
    lam = max(lam, 1e-9)
    return k * math.log(lam) - lam - math.lgamma(k + 1)


def behaviour_llr(obs: Observations, e: str, P) -> float:
    """log P(obs_e | e is mole) - log P(obs_e | e innocent)  (framing averaged over decoy)."""
    llr = 0.0
    if e in obs.access_counts:
        nr, na = obs.access_counts[e]
        k = obs.access_days.get(e, 0)
        if k > 0:
            pa_m = getattr(P, "p_after_hours_mole", 0.3)
            pa_b = getattr(P, "p_after_hours_benign", 0.1)
            fr = getattr(P, "framing_rate", 1.0) if P.framing else 0.0
            n = max(2, len(obs.employees))
            frame_e = fr / (n - 1)  # average framing share for a non-mole
            lm, lb = P.log_rate_mole * k, P.log_rate_benign * k
            llr += _pois_logpmf(nr, lm * (1 - pa_m)) + _pois_logpmf(na, lm * pa_m)
            llr -= _pois_logpmf(nr, lb * (1 - pa_b)) + _pois_logpmf(na, lb * pa_b + frame_e * k)
    pe = P.p_evasive_innocent
    pm = min(0.999, pe * P.interview_lr)
    for who, ev in obs.interviews:
        if who == e:
            llr += math.log(pm / pe) if ev else math.log((1 - pm) / (1 - pe))
    return llr


def posterior(obs: Observations, P, behaviour_temper: float = 0.3,
              choice_temper: float = 1.0, noleak_temper: float = 1.0) -> dict[str, float]:
    emps = obs.employees
    logs = {}
    for s in emps:
        lp = leak_loglik(obs, s, P, choice_temper, noleak_temper)
        if behaviour_temper > 0 and lp > -math.inf:
            lp += behaviour_temper * behaviour_llr(obs, s, P)
        logs[s] = lp
    m = max(logs.values()) if logs else -math.inf
    if m == -math.inf:
        # inconsistent observations (model mismatch): fall back to holder-only evidence
        return _fallback(obs)
    z = sum(math.exp(v - m) for v in logs.values())
    return {s: math.exp(v - m) / z for s, v in logs.items()}


def _fallback(obs: Observations) -> dict[str, float]:
    sc = {e: 1.0 for e in obs.employees}
    for it in obs.feed:
        doc = obs.docs.get(it.doc_id)
        if doc:
            for e in obs.employees:
                if e not in doc.recipients:
                    sc[e] *= 0.05
    z = sum(sc.values())
    return {e: v / z for e, v in sc.items()}
