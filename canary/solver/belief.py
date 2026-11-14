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
    # v1.3: when V only reflects SURFACED leaks, leak days are latent (marginalised over delay)
    leak_timing_known: bool = True
    decoy: str | None = None          # publicly inferred decoy (angry messages), if any
    # v1.5-candidate social layer: (kind, speaker, target) parsed from message subjects
    social: list[tuple[str, str, str]] = field(default_factory=list)


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
        return max(0.05, 1.0 - len(doc.recipients) / n_emp)  # floor: DSL moles need not follow careful weights
    return 1.0


MAX_STATES = 4096


def leak_loglik(obs: Observations, s: str, P, choice_temper: float = 1.0, noleak_temper: float = 1.0) -> float:
    """log P(feed [+ leak-day pattern if timing known] | mole = s). -inf if impossible.

    Forward DP over closed days d. Options per day: no leak; leak matched to a surfaced feed item j
    (surfaced_day - d in delays, s held it, variant/fingerprint factor); leak not yet surfaced
    (d + delta > today). With obs.leak_timing_known (V drops visible) the leak/no-leak choice per
    day is fixed by obs.leak_days; otherwise it is latent and summed over.
    """
    window = getattr(P, "leak_window_days", 3)
    delays = tuple(P.delay_choices)
    pd = 1.0 / len(delays)
    n = len(obs.employees) or 1
    surfaced = {}
    for it in obs.feed:
        surfaced[it.doc_id] = min(it.surfaced_day, surfaced.get(it.doc_id, 10**9))
    items = sorted(obs.feed, key=lambda x: (x.surfaced_day, x.doc_id))
    seen, uniq = set(), []
    for it in items:
        if it.doc_id not in seen:
            seen.add(it.doc_id)
            uniq.append(it)
    items = uniq
    a = getattr(P, "fingerprint_accuracy", 1.0)
    vf = []
    for it in items:
        doc = obs.docs.get(it.doc_id)
        if not (it.variant and doc and doc.variants):
            vf.append(1.0)
            continue
        mine = doc.variants.get(s)
        k = len(set(doc.variants.values()))
        if mine == it.variant:
            vf.append(a)
        elif mine is None or k <= 1:
            vf.append(0.0)
        else:
            vf.append((1.0 - a) / (k - 1))
    known = obs.leak_timing_known
    days = sorted(obs.closed_days)
    today = obs.today
    latest = [it.surfaced_day - min(delays) for it in items]
    log_noleak = noleak_temper * math.log(max(1e-12, 1.0 - P.p_leak))
    states = {(): 0.0}   # tuple(sorted used) -> log weight
    for idx, d in enumerate(days):
        lk = _leakable(obs, s, d, window, surfaced)
        W = sum(_weight(x, n, P.careful_mole) for x in lk)
        wdoc = {x.doc_id: _weight(x, n, P.careful_mole) for x in lk}
        allow_leak = (d in obs.leak_days) if known else True
        allow_none = (d not in obs.leak_days) if known else True
        pend = sum(pd for dl in delays if d + dl > today)
        nxt: dict = {}

        def add(key, lw):
            cur = nxt.get(key)
            nxt[key] = lw if cur is None else max(cur, lw) + math.log1p(math.exp(-abs(cur - lw)))
        for used, lw in states.items():
            if allow_none:
                add(used, lw + (log_noleak if W > 0 else 0.0))
            if allow_leak and W > 0:
                base = lw + math.log(P.p_leak)
                us = set(used)
                for j, it in enumerate(items):
                    if j in us or vf[j] <= 0:
                        continue
                    dl = it.surfaced_day - d
                    if dl in delays and it.doc_id in wdoc:
                        f = (wdoc[it.doc_id] / W) ** choice_temper * pd * vf[j]
                        if f > 0:
                            add(tuple(sorted(us | {j})), base + math.log(f))
                if pend > 0:
                    add(used, base + math.log(pend))
        nd = days[idx + 1] if idx + 1 < len(days) else None
        alive = {}
        for used, lw in nxt.items():
            us = set(used)
            if all(j in us or (nd is not None and latest[j] >= nd) for j in range(len(items))):
                alive[used] = lw
        if len(alive) > MAX_STATES:
            alive = dict(sorted(alive.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_STATES])
        states = alive
        if not states:
            return -math.inf
    full = [lw for used, lw in states.items() if len(used) == len(items)]
    if not full:
        return -math.inf
    m = max(full)
    return m + math.log(sum(math.exp(x - m) for x in full))


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


def behaviour_logliks(obs: Observations, P) -> dict[str, float]:
    """Exact (up to a constant) log P(access logs | mole = s), marginalising the unknown decoy
    (framing: share `framing_decoy_share` of fake after-hours accesses to the decoy, rest uniform)."""
    emps = obs.employees
    n = len(emps)
    pa_m = getattr(P, "p_after_hours_mole", 0.3)
    pa_b = getattr(P, "p_after_hours_benign", 0.1)
    fr = getattr(P, "framing_rate", 1.0) if P.framing else 0.0
    share = getattr(P, "framing_decoy_share", 0.5) if P.decoy else 0.0
    if not P.decoy:
        f_dec, f_plain = 0.0, fr / max(1, n - 1)
    else:
        f_dec, f_plain = fr * share, fr * (1 - share) / max(1, n - 2)
    Lm, Ld, Lp = {}, {}, {}
    for e in emps:
        if e not in obs.access_counts:
            Lm[e] = Ld[e] = Lp[e] = 0.0
            continue
        nr, na = obs.access_counts[e]
        k = obs.access_days.get(e, 0)
        lm, lb = P.log_rate_mole * k, P.log_rate_benign * k
        Lm[e] = _pois_logpmf(nr, lm * (1 - pa_m)) + _pois_logpmf(na, lm * pa_m)
        reg = _pois_logpmf(nr, lb * (1 - pa_b))
        Ld[e] = reg + _pois_logpmf(na, lb * pa_b + f_dec * k)
        Lp[e] = reg + _pois_logpmf(na, lb * pa_b + f_plain * k)
    tot_p = sum(Lp.values())
    out = {}
    for s in emps:
        base = tot_p - Lp[s] + Lm[s]
        if not P.decoy:
            out[s] = base
            continue
        if obs.decoy is not None:
            out[s] = base + (Ld[obs.decoy] - Lp[obs.decoy] if obs.decoy != s else 0.0)
            continue
        terms = [Ld[c] - Lp[c] for c in emps if c != s]
        m = max(terms)
        out[s] = base + m + math.log(sum(math.exp(t - m) for t in terms) / len(terms))
    return out


def social_loglik(obs: Observations, s: str, P) -> float:
    """Exact log-likelihood (up to a constant) of the observed rumour / authority messages under mole = s,
    from the stated rules with the DEFAULT mole policy (seed target = decoy if the tier has one, else a random
    peer). Grudge messages are mole-independent (0). With a decoy that we have identified, every candidate
    gets the same likelihood (0). With an unidentified decoy, P(seed target = x | m) = [x != m] / (n - 1)
    (the decoy is a uniform non-mole), which is also the random-peer case; we use this marginal (it ignores
    the coupling with the decoy marginalisation in behaviour_logliks, a second-order effect)."""
    sh = getattr(P, "rumour_frame_share", 0.0)
    if not obs.social or sh <= 0 or (P.decoy and obs.decoy is not None):
        return 0.0
    n = len(obs.employees)
    if n < 3:
        return 0.0
    q = lambda x: 0.0 if x == s else 1.0 / (n - 1)
    out = 0.0
    for kind, sp, t in obs.social:
        if kind == "rumour":
            out += math.log((1 - sh) / (n * (n - 1)) + sh * q(t) / (n - 1))
        elif kind == "authority":
            out += math.log((1 - sh) / (n - 1) + sh * (q(t) + q(sp) / (n - 1)))
    return out


def posterior(obs: Observations, P, behaviour_temper: float = 0.3,
              choice_temper: float = 1.0, noleak_temper: float = 1.0) -> dict[str, float]:
    emps = obs.employees
    logs = {}
    beh = behaviour_logliks(obs, P) if behaviour_temper > 0 else {}
    for s in emps:
        lp = leak_loglik(obs, s, P, choice_temper, noleak_temper)
        if behaviour_temper > 0 and lp > -math.inf:
            lp += behaviour_temper * beh[s]
            for who, ev in obs.interviews:
                if who == s:
                    pe = P.p_evasive_innocent
                    pm = min(0.999, pe * P.interview_lr)
                    lp += behaviour_temper * (math.log(pm / pe) if ev else math.log((1 - pm) / (1 - pe)))
        if obs.social and lp > -math.inf:
            lp += social_loglik(obs, s, P)
        if obs.decoy is not None and s == obs.decoy:
            lp = -math.inf   # mole is uniform over NON-decoy employees
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
