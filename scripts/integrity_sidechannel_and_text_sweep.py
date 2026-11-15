from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canary.baselines import play as play_baseline
from canary.env import BAD, Env, TOPICS, _SPECS
from canary.redteam import encodings as enc_mod
from canary.redteam import text_probe as tp_mod
from canary.rules import JUDGE_SEEDS, TIERS, TIERS_VERSION, TRACKS, TierParams, tier_params
from canary.solver.belief import Observations, behaviour_logliks
from canary.solver.policy import SolverPolicy
from canary.text.lint import lint_messages
from canary.text.template import _ANSWERS
import canary.world as world_mod

ALL_TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge", "hard_rl")
ALL_TOOLS: tuple[str, ...] = tuple(_SPECS.keys())
DEFAULT_PUBLIC_TEST_SECRET = "canary-anticheat-public-test-v1"
MAX_REPORT_BYTES = 130 * 1024
ANGRY_CUES: tuple[str, ...] = (
    "flat",
    "goalposts",
    "deserve",
    "updating my cv",
    "skipped for promotion",
    "nobody asks",
    "joke compared to the market",
)
EVASIVE_TEMPLATES: frozenset[str] = frozenset(
    tpl for (_, sig), tpls in _ANSWERS.items() if sig == "evasive" for tpl in tpls
)
WORD_RE = re.compile(r"[a-z0-9']+")
ZW_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u00ad]")
BRAILLE_RE = re.compile(r"[\u2800-\u28ff]")
PUNY_RE = re.compile(r"xn--", re.IGNORECASE)
MORSE_RUN_RE = re.compile(r"(?:^|\s)[.\-]{1,6}(?:\s+[.\-]{1,6}){3,}(?:\s|$)")


def parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            out.extend(range(int(lo_s), int(hi_s) + 1))
        else:
            out.append(int(part))
    return out


def parse_targets(spec: str) -> list[str]:
    targets = [t.strip() for t in spec.split(",") if t.strip()]
    for t in targets:
        tier_params(t)
    return targets


@contextmanager
def deterministic_world_secret(secret_str: str | None):
    prev = getattr(world_mod, "_SET_SECRET", None)
    salt_path = REPO / "data" / "worlds" / "judge" / "SALT"
    installed = False
    if (
        secret_str
        and prev is None
        and not os.environ.get("CANARY_WORLD_SECRET")
        and not salt_path.exists()
    ):
        raw = secret_str.encode("utf-8")
        if len(raw) < 16:
            raw = hashlib.sha256(raw).digest()
        world_mod.set_world_secret(raw)
        installed = True
    try:
        yield installed
    finally:
        if installed:
            world_mod.set_world_secret(prev)


def binom_pmf(n: int, k: int, p: float) -> float:
    if p <= 0.0:
        return 1.0 if k == 0 else 0.0
    if p >= 1.0:
        return 1.0 if k == n else 0.0
    log_p = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    log_p += k * math.log(p) + (n - k) * math.log(1.0 - p)
    return math.exp(log_p)


def p_value_above(k: int, n: int, p: float) -> float:
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return min(1.0, sum(binom_pmf(n, j, p) for j in range(k, n + 1)))


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    ph = k / n
    denom = 1.0 + z * z / n
    center = (ph + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(ph * (1.0 - ph) / n + z * z / (4.0 * n * n)) / denom
    return (round(max(0.0, center - half), 6), round(min(1.0, center + half), 6))


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def pooled_two_sample_z_and_p(xs: list[float], ys: list[float]) -> tuple[float, float]:
    nx, ny = len(xs), len(ys)
    if nx < 2 or ny < 2:
        return (0.0, 1.0)
    mx = sum(xs) / nx
    my = sum(ys) / ny
    ssx = sum((x - mx) ** 2 for x in xs)
    ssy = sum((y - my) ** 2 for y in ys)
    df = nx + ny - 2
    if df <= 0:
        return (0.0, 1.0)
    sp2 = (ssx + ssy) / df
    se = math.sqrt(sp2 * (1.0 / nx + 1.0 / ny))
    if se <= 1e-15:
        return (0.0, 1.0) if abs(mx - my) <= 1e-15 else (99.0, 0.0)
    z = (mx - my) / se
    return (z, normal_two_sided_p(z))


def paired_z_and_p(diffs: list[float]) -> tuple[float, float]:
    n = len(diffs)
    if n < 2:
        return (0.0, 1.0)
    mean_d = sum(diffs) / n
    var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
    if var_d <= 1e-15:
        return (0.0, 1.0) if abs(mean_d) <= 1e-15 else (99.0, 0.0)
    z = mean_d / math.sqrt(var_d / n)
    return (z, normal_two_sided_p(z))


def fair_bar_interview_exact(n_candidates: int, k: int, q0: float, q1: float) -> float:
    if n_candidates <= 1:
        return 1.0
    if k <= 0 or abs(q1 - q0) <= 1e-15:
        return 1.0 / n_candidates
    cdf0 = [sum(binom_pmf(k, j, q0) for j in range(c + 1)) for c in range(k + 1)]
    acc = 0.0
    for c in range(k + 1):
        pm = binom_pmf(k, c, q1)
        below = cdf0[c - 1] if c > 0 else 0.0
        eq = binom_pmf(k, c, q0)
        tie_sum = sum(
            math.comb(n_candidates - 1, j) * (eq ** j) * (below ** (n_candidates - 1 - j)) / (j + 1)
            for j in range(n_candidates)
        )
        acc += pm * tie_sum
    return acc


def text_probe_budget_k(p: TierParams) -> int:
    days = p.n_days - 1
    slots = p.actions_per_day - 1 - tp_mod.MSGS_READ_PER_DAY
    return max(1, min(len(TOPICS), (slots * days) // p.n_employees))


def compute_fair_bars(target: str, mc_trials: int = 20000, rng_seed: int = 17) -> dict[str, float]:
    p = tier_params(target)
    n = p.n_employees
    n_cand = n - 1 if p.decoy else n
    q0 = p.p_evasive_innocent
    q1 = min(0.999999, q0 * p.interview_lr)
    k_budget = text_probe_budget_k(p)
    bar_chance = 1.0 / n
    bar_decoy_excl = 1.0 / n_cand
    bar_iv_budget_raw = fair_bar_interview_exact(n, k_budget, q0, q1)
    bar_iv_budget_decoy = fair_bar_interview_exact(n_cand, k_budget, q0, q1)
    bar_iv_k4_raw = fair_bar_interview_exact(n, 4, q0, q1)
    bar_iv_k4_decoy = fair_bar_interview_exact(n_cand, 4, q0, q1)

    closed_days = p.n_days - 1
    if p.framing and p.decoy:
        fr_plain = p.framing_rate * (1.0 - p.framing_decoy_share) / max(1, n - 2)
    elif p.framing:
        fr_plain = p.framing_rate / max(1, n - 1)
    else:
        fr_plain = 0.0

    lam_m_r = max(1e-9, closed_days * p.log_rate_mole * (1.0 - p.p_after_hours_mole))
    lam_m_a = max(1e-9, closed_days * p.log_rate_mole * p.p_after_hours_mole)
    lam_b_r = max(1e-9, closed_days * p.log_rate_benign * (1.0 - p.p_after_hours_benign))
    lam_b_a = max(1e-9, closed_days * (p.log_rate_benign * p.p_after_hours_benign + fr_plain))

    rng = np.random.default_rng(rng_seed + sum(ord(c) for c in p.name))
    mr = rng.poisson(lam_m_r, size=(mc_trials, 1))
    ma = rng.poisson(lam_m_a, size=(mc_trials, 1))
    br = rng.poisson(lam_b_r, size=(mc_trials, n_cand - 1))
    ba = rng.poisson(lam_b_a, size=(mc_trials, n_cand - 1))
    r_all = np.concatenate([mr, br], axis=1)
    a_all = np.concatenate([ma, ba], axis=1)

    w_r = math.log(lam_m_r / lam_b_r)
    w_a = math.log(lam_m_a / lam_b_a)
    llr_logs = r_all * w_r + a_all * w_a
    mx_logs = llr_logs.max(axis=1, keepdims=True)
    ties_logs = llr_logs == mx_logs
    bar_logs_bayes = float((ties_logs[:, 0] / ties_logs.sum(axis=1)).mean())

    iv_m = rng.binomial(4, q1, size=(mc_trials, 1))
    iv_b = rng.binomial(4, q0, size=(mc_trials, n_cand - 1))
    iv_all = np.concatenate([iv_m, iv_b], axis=1)
    w_iv_pos = math.log(q1 / q0) if q1 > q0 else 0.0
    w_iv_neg = math.log((1.0 - q1) / (1.0 - q0)) if q1 > q0 else 0.0
    llr_joint = llr_logs + iv_all * w_iv_pos + (4 - iv_all) * w_iv_neg
    mx_joint = llr_joint.max(axis=1, keepdims=True)
    ties_joint = llr_joint == mx_joint
    bar_joint_bayes = float((ties_joint[:, 0] / ties_joint.sum(axis=1)).mean())

    return {
        "n_employees": n,
        "n_candidates_after_decoy": n_cand,
        "closed_days": closed_days,
        "k_interview_budget": k_budget,
        "bar_chance": round(bar_chance, 6),
        "bar_decoy_excluded": round(bar_decoy_excl, 6),
        "bar_interview_budget_raw": round(bar_iv_budget_raw, 6),
        "bar_interview_budget_decoy": round(bar_iv_budget_decoy, 6),
        "bar_interview_k4_raw": round(bar_iv_k4_raw, 6),
        "bar_interview_k4_decoy": round(bar_iv_k4_decoy, 6),
        "bar_logs_bayes": round(bar_logs_bayes, 6),
        "bar_joint_non_canary": round(bar_joint_bayes, 6),
    }


def _collect_text_probe_and_env(target: str, seed: int, env_factory=Env) -> tuple[dict[str, Any], Any]:
    env = env_factory(target, seed)
    p = tier_params(target)
    r = env.call("list_employees", {})
    ids = [e["id"] for e in (r.data or {}).get("employees", [])]
    days = p.n_days - 1
    k = text_probe_budget_k(p)
    todo = [(e, t) for t in TOPICS[:k] for e in ids]
    messages: dict[str, dict[str, Any]] = {}
    interviews: dict[str, list[str]] = {e: [] for e in ids}
    for d in range(1, days + 1):
        used = 0
        hits = []
        for q in ("e", "a", "the"):
            if d == 1:
                break
            sr = env.call("search_messages", {"query": q, "day_from": d - 1, "day_to": d - 1})
            used += 1
            if sr.ok:
                hits = (sr.data or {}).get("messages", [])
                break
        for m in hits[: tp_mod.MSGS_READ_PER_DAY]:
            mr = env.call("read_message", {"id": m["id"]})
            used += 1
            if mr.ok:
                msg_obj = mr.data["message"]
                messages[str(m["id"])] = {
                    "day": d - 1,
                    "sender": m.get("sender"),
                    "text": f"{msg_obj.get('subject', '')}: {msg_obj.get('body', '')}",
                }
        for m in hits[tp_mod.MSGS_READ_PER_DAY :]:
            messages.setdefault(
                str(m["id"]),
                {"day": d - 1, "sender": m.get("sender"), "text": m.get("snippet", "")},
            )
        while todo and used < p.actions_per_day:
            e, t = todo.pop(0)
            ir = env.call("interview", {"employee": e, "topic": t})
            used += 1
            if ir.ok:
                interviews[e].append(str(ir.data.get("answer", "")))
        env.call("advance_day", {})
        if env.done:
            break
    obs = {
        "tier": target,
        "seed": seed,
        "ids": ids,
        "k_interviews": k,
        "messages": messages,
        "interviews": interviews,
        "mole": env._world.mole,
    }
    return obs, env


def collect_text_probe_for_target(target: str, seed: int, env_factory=Env) -> dict[str, Any]:
    obs, _ = _collect_text_probe_and_env(target, seed, env_factory=env_factory)
    return obs


def _has_nato_run(text: str, min_len: int = 3) -> bool:
    run = 0
    for w in text.split():
        k = w.lower().strip(".,;:!?()[]{}\"'")
        if k in enc_mod.NATO_DECODE:
            run += 1
            if run >= min_len:
                return True
        else:
            run = 0
    return False


def _infer_public_decoy(emps: list[str], messages: list[dict[str, Any]], has_decoy: bool) -> str | None:
    if not has_decoy:
        return None
    angry_counts: Counter[str] = Counter()
    for m in messages:
        low = f"{m.get('subject', '')} {m.get('body', '')}".lower()
        if any(cue in low for cue in ANGRY_CUES):
            snd = m.get("sender")
            if snd in emps:
                angry_counts[snd] += 1
    if not angry_counts:
        return None
    return sorted(angry_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _fast_secret_scan(prose_texts: list[str], secret_tokens: list[str]) -> list[dict[str, Any]]:
    tokens = tuple(dict.fromkeys(t for t in secret_tokens if isinstance(t, str) and t))
    if not prose_texts or not tokens:
        return []
    cf_pats = [(tok, tok.casefold()) for tok in tokens]
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for idx, txt in enumerate(prose_texts):
        if not txt:
            continue
        variants = [("raw", txt.casefold())]
        if ZW_RE.search(txt):
            variants.append(("zw_stripped", ZW_RE.sub("", txt).casefold()))
        if not txt.isascii():
            variants.append(("homoglyph_nfkc", enc_mod._nfkc_confusables(txt).casefold()))
        for mode, low in variants:
            for tok, pat in cf_pats:
                if pat in low and (tok, mode) not in seen:
                    seen.add((tok, mode))
                    hits.append({"token": tok, "encoding": mode, "source": f"prose:{idx}"})
    return hits


def _extract_single_episode(args: tuple[str, int, bool]) -> dict[str, Any]:
    target, seed, scan_secrets = args
    p = tier_params(target)
    key_bytes = world_mod._key(seed)

    tp_obs, env = _collect_text_probe_and_env(target, seed)
    tp_guess = tp_mod.stub_guess(tp_obs)

    emp_rows = env.call("list_employees", {}).data["employees"]
    emps = [r["id"] for r in emp_rows]
    mole = env._world.mole
    ws = env._world.world_seed

    iv_by_emp_topic: dict[str, dict[str, dict[str, Any]]] = {e: {} for e in emps}
    emps_per_env = max(1, p.actions_per_day // len(TOPICS))
    for i in range(0, len(emps), emps_per_env):
        iv_env = Env(target, seed)
        for e in emps[i : i + emps_per_env]:
            for top in TOPICS:
                ir = iv_env.call("interview", {"employee": e, "topic": top})
                ans = str(ir.data["answer"])
                p_ev = p.p_evasive_innocent * (p.interview_lr if e == mole else 1.0)
                sig_rng = random.Random(f"{ws}:iv:{e}:{top}:1")
                true_sig = "evasive" if sig_rng.random() < p_ev else "cooperative"
                tpl_ev = ans in EVASIVE_TEMPLATES
                toks = WORD_RE.findall(ans.lower())
                iv_by_emp_topic[e][top] = {
                    "answer": ans,
                    "byte_len": len(ans.encode("utf-8")),
                    "tok_count": len(toks),
                    "tokens": toks,
                    "true_signal": true_sig,
                    "tpl_evasive": tpl_ev,
                    "signal_match": (true_sig == ("evasive" if tpl_ev else "cooperative")),
                }

    final_v = float(env.V)
    docs = env.call("list_documents", {"day_from": 1, "day_to": p.n_days}).data["documents"]
    logs = env.call("read_access_logs", {"day_from": 1, "day_to": p.n_days - 1}).data["logs"]
    msgs = [dict(env._messages[mid]) for mid in env._msg_order]

    doc_order_inversions = 0
    doc_rec_count: Counter[str] = Counter()
    doc_first_count: Counter[str] = Counter()
    doc_last_count: Counter[str] = Counter()
    for d in docs:
        recs = d["recipients"]
        if recs != sorted(recs) or len(recs) != len(set(recs)):
            doc_order_inversions += 1
        for r in recs:
            doc_rec_count[r] += 1
        if recs:
            doc_first_count[recs[0]] += 1
            doc_last_count[recs[-1]] += 1

    log_order_inversions = 0
    prev_key = None
    reg_logs: Counter[str] = Counter()
    ah_logs: Counter[str] = Counter()
    log_norm_pos_sum: defaultdict[str, float] = defaultdict(float)
    log_norm_pos_cnt: Counter[str] = Counter()
    by_day_logs: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in logs:
        cur_key = (int(row["day"]), str(row["employee"]), str(row["doc_id"]), bool(row["after_hours"]))
        if prev_key is not None and cur_key < prev_key:
            log_order_inversions += 1
        prev_key = cur_key
        by_day_logs[int(row["day"])].append(row)
        if row["after_hours"]:
            ah_logs[row["employee"]] += 1
        else:
            reg_logs[row["employee"]] += 1

    for d_rows in by_day_logs.values():
        denom = max(1, len(d_rows) - 1)
        for idx, row in enumerate(d_rows):
            log_norm_pos_sum[row["employee"]] += idx / denom
            log_norm_pos_cnt[row["employee"]] += 1

    msg_id_gaps = 0
    by_day_msg_indices: defaultdict[int, list[int]] = defaultdict(list)
    msg_count: Counter[str] = Counter()
    msg_bytes_sum: Counter[str] = Counter()
    msg_tokens_by_emp: dict[str, list[str]] = {e: [] for e in emps}
    for m in msgs:
        mid = str(m["id"])
        parts = mid.lstrip("m").split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            by_day_msg_indices[int(parts[0])].append(int(parts[1]))
        else:
            msg_id_gaps += 1
        snd = m["sender"]
        txt = f"{m.get('subject', '')} {m.get('body', '')}".strip()
        msg_count[snd] += 1
        msg_bytes_sum[snd] += len(txt.encode("utf-8"))
        msg_tokens_by_emp[snd].extend(WORD_RE.findall(txt.lower()))

    for indices in by_day_msg_indices.values():
        if indices != list(range(len(indices))):
            msg_id_gaps += 1

    lint_hits = lint_messages(msgs)
    inferred_decoy = _infer_public_decoy(emps, msgs, p.decoy)

    obs = Observations(employees=emps, decoy=inferred_decoy)
    for e in emps:
        obs.access_counts[e] = [reg_logs[e], ah_logs[e]]
        obs.access_days[e] = p.n_days - 1
    beh_ll = behaviour_logliks(obs, p)

    prose_texts: list[str] = [env.instruction()]
    prose_texts.extend(d["title"] for d in docs)
    prose_texts.extend(f"{m.get('subject', '')} {m.get('body', '')}".strip() for m in msgs)
    for e in emps:
        for top in TOPICS:
            prose_texts.append(iv_by_emp_topic[e][top]["answer"])

    zw_hits = sum(1 for t in prose_texts if ZW_RE.search(t))
    braille_hits = sum(1 for t in prose_texts if BRAILLE_RE.search(t))
    non_ascii_hits = sum(1 for t in prose_texts if not t.isascii())
    puny_hits = sum(1 for t in prose_texts if PUNY_RE.search(t))
    morse_hits = sum(1 for t in prose_texts if MORSE_RUN_RE.search(t))
    nato_hits = sum(1 for t in prose_texts if _has_nato_run(t, 3))

    secret_leak_hits: list[dict[str, Any]] = []
    if scan_secrets:
        secret_tokens = enc_mod._episode_secret_tokens(env, target, seed, key_bytes)
        secret_leak_hits = _fast_secret_scan(prose_texts, secret_tokens)

    per_emp: list[dict[str, Any]] = []
    for idx, r in enumerate(emp_rows):
        eid = r["id"]
        iv_bytes_total = sum(iv_by_emp_topic[eid][t]["byte_len"] for t in TOPICS)
        iv_toks_total = sum(iv_by_emp_topic[eid][t]["tok_count"] for t in TOPICS)
        iv_ev_count = sum(1 for t in TOPICS if iv_by_emp_topic[eid][t]["tpl_evasive"])
        iv_toks_all: list[str] = []
        for t in TOPICS:
            iv_toks_all.extend(iv_by_emp_topic[eid][t]["tokens"])
        per_emp.append({
            "id": eid,
            "idx": idx,
            "name_bytes": len(r["name"].encode("utf-8")),
            "dept": r["dept"],
            "role": r["role"],
            "clearance": int(r["clearance"]) if r.get("clearance") is not None else 0,
            "row_json_bytes": len(json.dumps(r, sort_keys=True).encode("utf-8")),
            "doc_count": doc_rec_count[eid],
            "doc_first": doc_first_count[eid],
            "doc_last": doc_last_count[eid],
            "reg_logs": reg_logs[eid],
            "ah_logs": ah_logs[eid],
            "log_mean_pos": (log_norm_pos_sum[eid] / log_norm_pos_cnt[eid]) if log_norm_pos_cnt[eid] else 0.5,
            "beh_ll": beh_ll[eid],
            "msg_count": msg_count[eid],
            "msg_mean_bytes": (msg_bytes_sum[eid] / msg_count[eid]) if msg_count[eid] else 0.0,
            "msg_tokens": msg_tokens_by_emp[eid][:60],
            "iv_bytes_total": iv_bytes_total,
            "iv_toks_total": iv_toks_total,
            "iv_ev_count": iv_ev_count,
            "iv_tokens": iv_toks_all,
            "iv_topics": {
                t: {
                    "byte_len": iv_by_emp_topic[eid][t]["byte_len"],
                    "tok_count": iv_by_emp_topic[eid][t]["tok_count"],
                    "true_signal": iv_by_emp_topic[eid][t]["true_signal"],
                    "signal_match": iv_by_emp_topic[eid][t]["signal_match"],
                }
                for t in TOPICS
            },
        })

    return {
        "target": target,
        "seed": seed,
        "mole": mole,
        "true_decoy": env._world.decoy,
        "inferred_decoy": inferred_decoy,
        "final_V": final_v,
        "tp_guess": tp_guess,
        "doc_count_total": len(docs),
        "log_count_total": len(logs),
        "msg_count_total": len(msgs),
        "prose_texts_scanned": len(prose_texts),
        "doc_order_inversions": doc_order_inversions,
        "log_order_inversions": log_order_inversions,
        "msg_id_gaps": msg_id_gaps,
        "lint_violations": len(lint_hits),
        "zw_hits": zw_hits,
        "braille_hits": braille_hits,
        "non_ascii_hits": non_ascii_hits,
        "puny_hits": puny_hits,
        "morse_hits": morse_hits,
        "nato_hits": nato_hits,
        "secret_leak_hits": secret_leak_hits,
        "employees": per_emp,
    }


def _argmax_det(cands: list[dict[str, Any]], key_fn) -> str:
    return max(cands, key=lambda r: (key_fn(r), -r["idx"]))["id"]


def _cv_categorical_guesses(episodes: list[dict[str, Any]], feat_fn, exclude_decoy: bool = False) -> list[str]:
    n = len(episodes)
    mid = max(1, n // 2)
    folds = (episodes[:mid], episodes[mid:]) if n >= 2 else (episodes, episodes)
    guesses = [""] * n
    for fold_idx in range(2):
        train_eps = folds[1 - fold_idx] if n >= 2 else episodes
        eval_slice = range(0, mid) if fold_idx == 0 else range(mid, n)
        mole_cnt: Counter[Any] = Counter()
        inn_cnt: Counter[Any] = Counter()
        vocab: set[Any] = set()
        tot_m, tot_i = 0, 0
        for ep in train_eps:
            m_id = ep["mole"]
            dec_id = ep["inferred_decoy"] if exclude_decoy else None
            for r in ep["employees"]:
                if dec_id and r["id"] == dec_id:
                    continue
                val = feat_fn(r, len(ep["employees"]))
                vocab.add(val)
                if r["id"] == m_id:
                    mole_cnt[val] += 1
                    tot_m += 1
                else:
                    inn_cnt[val] += 1
                    tot_i += 1
        k_v = max(1, len(vocab))
        for i in eval_slice:
            ep = episodes[i]
            dec_id = ep["inferred_decoy"] if exclude_decoy else None
            cands = [r for r in ep["employees"] if r["id"] != dec_id] or ep["employees"]
            best_id = _argmax_det(
                cands,
                lambda r: math.log((mole_cnt[feat_fn(r, len(ep["employees"]))] + 1.0) / (tot_m + k_v))
                - math.log((inn_cnt[feat_fn(r, len(ep["employees"]))] + 1.0) / (tot_i + k_v)),
            )
            guesses[i] = best_id
    return guesses


def _cv_joint_roster_guesses(episodes: list[dict[str, Any]]) -> list[str]:
    feats = (
        lambda r, n: (4 * r["idx"]) // max(1, n),
        lambda r, n: r["name_bytes"] // 3,
        lambda r, n: r["dept"],
        lambda r, n: r["role"],
        lambda r, n: r["clearance"],
    )
    n_eps = len(episodes)
    mid = max(1, n_eps // 2)
    folds = (episodes[:mid], episodes[mid:]) if n_eps >= 2 else (episodes, episodes)
    guesses = [""] * n_eps
    for fold_idx in range(2):
        train_eps = folds[1 - fold_idx] if n_eps >= 2 else episodes
        eval_slice = range(0, mid) if fold_idx == 0 else range(mid, n_eps)
        m_cnts = [Counter() for _ in feats]
        i_cnts = [Counter() for _ in feats]
        vocabs = [set() for _ in feats]
        tot_m, tot_i = 0, 0
        for ep in train_eps:
            m_id = ep["mole"]
            n_emp = len(ep["employees"])
            for r in ep["employees"]:
                is_m = r["id"] == m_id
                if is_m:
                    tot_m += 1
                else:
                    tot_i += 1
                for fi, fn in enumerate(feats):
                    v = fn(r, n_emp)
                    vocabs[fi].add(v)
                    if is_m:
                        m_cnts[fi][v] += 1
                    else:
                        i_cnts[fi][v] += 1
        for i in eval_slice:
            ep = episodes[i]
            n_emp = len(ep["employees"])

            def score_row(r: dict[str, Any]) -> float:
                s = 0.0
                for fi, fn in enumerate(feats):
                    v = fn(r, n_emp)
                    kv = max(1, len(vocabs[fi]))
                    s += math.log((m_cnts[fi][v] + 1.0) / (tot_m + kv))
                    s -= math.log((i_cnts[fi][v] + 1.0) / (tot_i + kv))
                return s

            guesses[i] = _argmax_det(ep["employees"], score_row)
    return guesses


def _cv_bow_guesses(episodes: list[dict[str, Any]], tok_key: str, exclude_decoy: bool = True) -> list[str]:
    n_eps = len(episodes)
    mid = max(1, n_eps // 2)
    folds = (episodes[:mid], episodes[mid:]) if n_eps >= 2 else (episodes, episodes)
    guesses = [""] * n_eps
    for fold_idx in range(2):
        train_eps = folds[1 - fold_idx] if n_eps >= 2 else episodes
        eval_slice = range(0, mid) if fold_idx == 0 else range(mid, n_eps)
        m_tok: Counter[str] = Counter()
        i_tok: Counter[str] = Counter()
        vocab: set[str] = set()
        tot_m, tot_i = 0, 0
        for ep in train_eps:
            m_id = ep["mole"]
            dec_id = ep["inferred_decoy"] if exclude_decoy else None
            for r in ep["employees"]:
                if dec_id and r["id"] == dec_id:
                    continue
                toks = r[tok_key]
                vocab.update(toks)
                if r["id"] == m_id:
                    m_tok.update(toks)
                    tot_m += len(toks)
                else:
                    i_tok.update(toks)
                    tot_i += len(toks)
        kv = max(1, len(vocab))
        for i in eval_slice:
            ep = episodes[i]
            dec_id = ep["inferred_decoy"] if exclude_decoy else None
            cands = [r for r in ep["employees"] if r["id"] != dec_id] or ep["employees"]

            def score_row(r: dict[str, Any]) -> float:
                toks = r[tok_key]
                if not toks:
                    return 0.0
                llr = 0.0
                for w in toks:
                    llr += math.log((m_tok[w] + 1.0) / (tot_m + kv))
                    llr -= math.log((i_tok[w] + 1.0) / (tot_i + kv))
                return llr / len(toks)

            guesses[i] = _argmax_det(cands, score_row)
    return guesses


def evaluate_non_canary_features(
    target: str,
    episodes: list[dict[str, Any]],
    bars: dict[str, float],
    alpha: float = 0.01,
) -> dict[str, Any]:
    p = tier_params(target)
    n_eps = len(episodes)
    n_emp = p.n_employees
    pe = p.p_evasive_innocent
    pm = min(0.999999, pe * p.interview_lr)
    w_iv_pos = math.log(pm / pe) if pm > pe else 0.0
    w_iv_neg = math.log((1.0 - pm) / (1.0 - pe)) if pm > pe else 0.0

    mole_idx_counts = Counter(
        next(r["idx"] for r in ep["employees"] if r["id"] == ep["mole"]) for ep in episodes
    )
    expected_idx = n_eps / n_emp
    chisq_roster = sum(
        ((mole_idx_counts[i] - expected_idx) ** 2) / max(1e-9, expected_idx) for i in range(n_emp)
    )

    dept_cv = _cv_categorical_guesses(episodes, lambda r, _: r["dept"], exclude_decoy=False)
    role_cv = _cv_categorical_guesses(episodes, lambda r, _: r["role"], exclude_decoy=False)
    clear_cv = _cv_categorical_guesses(episodes, lambda r, _: r["clearance"], exclude_decoy=False)
    roster_joint_cv = _cv_joint_roster_guesses(episodes)
    msg_len_cv = _cv_categorical_guesses(
        episodes, lambda r, _: int(r["msg_mean_bytes"] // 15), exclude_decoy=True
    )
    msg_bow_cv = _cv_bow_guesses(episodes, "msg_tokens", exclude_decoy=True)
    iv_bow_cv = _cv_bow_guesses(episodes, "iv_tokens", exclude_decoy=True)

    predictors: list[tuple[str, str, float, list[str]]] = [
        (
            "roster_first_id",
            "roster",
            bars["bar_chance"],
            [ep["employees"][0]["id"] for ep in episodes],
        ),
        (
            "roster_last_id",
            "roster",
            bars["bar_chance"],
            [ep["employees"][-1]["id"] for ep in episodes],
        ),
        (
            "roster_name_longest",
            "roster",
            bars["bar_chance"],
            [_argmax_det(ep["employees"], lambda r: r["name_bytes"]) for ep in episodes],
        ),
        (
            "roster_name_shortest",
            "roster",
            bars["bar_chance"],
            [_argmax_det(ep["employees"], lambda r: -r["name_bytes"]) for ep in episodes],
        ),
        ("roster_dept_cv_llr", "roster", bars["bar_chance"], dept_cv),
        ("roster_role_cv_llr", "roster", bars["bar_chance"], role_cv),
        ("roster_clearance_cv_llr", "roster", bars["bar_chance"], clear_cv),
        ("roster_joint_cv_nb", "roster", bars["bar_chance"], roster_joint_cv),
        (
            "doc_recipient_count_max",
            "documents",
            bars["bar_chance"],
            [_argmax_det(ep["employees"], lambda r: r["doc_count"]) for ep in episodes],
        ),
        (
            "doc_first_recipient_freq",
            "documents",
            bars["bar_chance"],
            [_argmax_det(ep["employees"], lambda r: r["doc_first"]) for ep in episodes],
        ),
        (
            "doc_last_recipient_freq",
            "documents",
            bars["bar_chance"],
            [_argmax_det(ep["employees"], lambda r: r["doc_last"]) for ep in episodes],
        ),
        (
            "msg_count_non_decoy",
            "messages",
            bars["bar_decoy_excluded"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: r["msg_count"],
                )
                for ep in episodes
            ],
        ),
        ("msg_byte_len_cv_llr", "messages", bars["bar_decoy_excluded"], msg_len_cv),
        ("msg_bow_cv_llr", "messages", bars["bar_decoy_excluded"], msg_bow_cv),
        (
            "text_probe_stub_budget",
            "interviews",
            bars["bar_interview_budget_decoy"],
            [ep["tp_guess"] for ep in episodes],
        ),
        (
            "iv_4topic_shortest_bytes",
            "interviews",
            bars["bar_interview_k4_decoy"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: -r["iv_bytes_total"],
                )
                for ep in episodes
            ],
        ),
        (
            "iv_4topic_fewest_tokens",
            "interviews",
            bars["bar_interview_k4_decoy"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: -r["iv_toks_total"],
                )
                for ep in episodes
            ],
        ),
        ("iv_4topic_bow_cv_llr", "interviews", bars["bar_interview_k4_decoy"], iv_bow_cv),
        (
            "iv_4topic_exact_template_bayes",
            "interviews",
            bars["bar_interview_k4_decoy"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: r["iv_ev_count"],
                )
                for ep in episodes
            ],
        ),
        (
            "log_position_mean_rank",
            "access_logs",
            bars["bar_chance"],
            [_argmax_det(ep["employees"], lambda r: r["log_mean_pos"]) for ep in episodes],
        ),
        (
            "log_naive_after_hours",
            "access_logs",
            bars["bar_logs_bayes"],
            [_argmax_det(ep["employees"], lambda r: 10 * r["ah_logs"] + r["reg_logs"]) for ep in episodes],
        ),
        (
            "log_minus_decoy_linear",
            "access_logs",
            bars["bar_logs_bayes"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: 3 * r["ah_logs"] + r["reg_logs"],
                )
                for ep in episodes
            ],
        ),
        (
            "log_exact_poisson_bayes",
            "access_logs",
            bars["bar_logs_bayes"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: r["beh_ll"],
                )
                for ep in episodes
            ],
        ),
        (
            "joint_non_canary_bayes",
            "joint_behaviour",
            bars["bar_joint_non_canary"],
            [
                _argmax_det(
                    [r for r in ep["employees"] if r["id"] != ep["inferred_decoy"]] or ep["employees"],
                    lambda r: r["beh_ll"]
                    + r["iv_ev_count"] * w_iv_pos
                    + (4 - r["iv_ev_count"]) * w_iv_neg,
                )
                for ep in episodes
            ],
        ),
    ]

    rows: list[dict[str, Any]] = []
    n_tests = len(predictors)
    for name, family, bar, guesses in predictors:
        hits = sum(int(g == ep["mole"]) for g, ep in zip(guesses, episodes))
        acc = hits / max(1, n_eps)
        pv = p_value_above(hits, n_eps, bar)
        pv_bonf = min(1.0, pv * n_tests)
        ev_scores = [(ep["final_V"] if g == ep["mole"] else -1.0) for g, ep in zip(guesses, episodes)]
        mean_score = sum(ev_scores) / max(1, n_eps)
        ci_lo, ci_hi = wilson_ci(hits, n_eps)
        flagged = pv_bonf < alpha
        rows.append({
            "predictor": name,
            "family": family,
            "n": n_eps,
            "hits": hits,
            "accuracy": round(acc, 6),
            "ci95": [ci_lo, ci_hi],
            "fair_bar": round(bar, 6),
            "excess_over_bar": round(acc - bar, 6),
            "p_value_vs_bar": round(pv, 6),
            "p_value_bonferroni": round(pv_bonf, 6),
            "always_accuse_mean_score": round(mean_score, 6),
            "beats_fair_bar": flagged,
        })

    iv_strata: dict[str, dict[str, Any]] = {}
    signal_mismatches = 0
    for top in TOPICS:
        for sig in ("evasive", "cooperative"):
            m_bytes: list[float] = []
            i_bytes: list[float] = []
            m_toks: list[float] = []
            i_toks: list[float] = []
            for ep in episodes:
                m_id = ep["mole"]
                for r in ep["employees"]:
                    td = r["iv_topics"][top]
                    if not td["signal_match"]:
                        signal_mismatches += 1
                    if td["true_signal"] != sig:
                        continue
                    if r["id"] == m_id:
                        m_bytes.append(float(td["byte_len"]))
                        m_toks.append(float(td["tok_count"]))
                    else:
                        i_bytes.append(float(td["byte_len"]))
                        i_toks.append(float(td["tok_count"]))
            zb, pb = pooled_two_sample_z_and_p(m_bytes, i_bytes)
            zt, pt = pooled_two_sample_z_and_p(m_toks, i_toks)
            enough = len(m_bytes) >= 5 and len(i_bytes) >= 5
            iv_strata[f"{top}:{sig}"] = {
                "n_mole": len(m_bytes),
                "n_innocent": len(i_bytes),
                "mole_mean_bytes": round(sum(m_bytes) / max(1, len(m_bytes)), 4),
                "innocent_mean_bytes": round(sum(i_bytes) / max(1, len(i_bytes)), 4),
                "bytes_z": round(zb, 4),
                "bytes_p": round(pb, 6),
                "mole_mean_tokens": round(sum(m_toks) / max(1, len(m_toks)), 4),
                "innocent_mean_tokens": round(sum(i_toks) / max(1, len(i_toks)), 4),
                "tokens_z": round(zt, 4),
                "tokens_p": round(pt, 6),
                "conditional_leak": enough and ((min(pb, pt) * 16.0) < alpha),
            }

    doc_inv = sum(ep["doc_order_inversions"] for ep in episodes)
    log_inv = sum(ep["log_order_inversions"] for ep in episodes)
    msg_gaps = sum(ep["msg_id_gaps"] for ep in episodes)
    lint_viol = sum(ep["lint_violations"] for ep in episodes)
    stego_counts = {
        "zero_width_hits": sum(ep["zw_hits"] for ep in episodes),
        "braille_hits": sum(ep["braille_hits"] for ep in episodes),
        "non_ascii_hits": sum(ep["non_ascii_hits"] for ep in episodes),
        "punycode_hits": sum(ep["puny_hits"] for ep in episodes),
        "morse_run_hits": sum(ep["morse_hits"] for ep in episodes),
        "nato_run_hits": sum(ep["nato_hits"] for ep in episodes),
        "encoded_secret_hits": sum(len(ep["secret_leak_hits"]) for ep in episodes),
    }

    any_beat = any(r["beats_fair_bar"] for r in rows)
    any_cond = any(v["conditional_leak"] for v in iv_strata.values())
    any_order = (doc_inv + log_inv + msg_gaps + lint_viol) > 0
    any_stego = sum(stego_counts.values()) > 0

    return {
        "target": target,
        "n_episodes": n_eps,
        "mean_final_V_unperturbed": round(sum(ep["final_V"] for ep in episodes) / max(1, n_eps), 6),
        "decoy_identification_accuracy": (
            round(
                sum(int(ep["inferred_decoy"] == ep["true_decoy"]) for ep in episodes) / max(1, n_eps),
                6,
            )
            if p.decoy
            else None
        ),
        "roster_index_chisq": round(chisq_roster, 4),
        "roster_index_df": n_emp - 1,
        "ordering_and_lint": {
            "total_docs_checked": sum(ep["doc_count_total"] for ep in episodes),
            "total_logs_checked": sum(ep["log_count_total"] for ep in episodes),
            "total_messages_checked": sum(ep["msg_count_total"] for ep in episodes),
            "total_prose_texts_scanned": sum(ep["prose_texts_scanned"] for ep in episodes),
            "doc_recipient_order_inversions": doc_inv,
            "access_log_order_inversions": log_inv,
            "message_id_sequence_gaps": msg_gaps,
            "text_lint_violations": lint_viol,
        },
        "stego_character_scan": stego_counts,
        "interview_signal_template_mismatches": signal_mismatches,
        "interview_conditional_strata": iv_strata,
        "predictors": rows,
        "ok": not (any_beat or any_cond or any_order or any_stego),
    }


def _serialized_bytes(res: Any) -> int:
    return len(json.dumps(asdict(res), sort_keys=True).encode("utf-8"))


def _norm_error_sig(res: Any, caller_emp: str | None) -> tuple[bool, str | None, tuple[str, ...], str | None, int]:
    ok = bool(res.ok)
    err = res.error
    data = res.data if isinstance(res.data, dict) else {}
    keys = tuple(sorted(data.keys()))
    raw_detail = data.get("detail")
    norm_detail = (
        raw_detail.replace(caller_emp, "<EMP>")
        if (isinstance(raw_detail, str) and caller_emp)
        else raw_detail
    )
    return (ok, err, keys, norm_detail, _serialized_bytes(res))


def _scan_detail_secret_leaks(
    res: Any,
    caller_emp: str | None,
    mole: str,
    mole_name: str,
    target: str,
    seed: int,
    ws: int,
    hidden_v: float | None,
) -> tuple[int, int, int]:
    if not isinstance(res.data, dict):
        return (0, 0, 0)
    raw_detail = res.data.get("detail")
    if not isinstance(raw_detail, str) or not raw_detail:
        return (0, 0, 0)
    masked = raw_detail.replace(caller_emp, "<EMP>") if caller_emp else raw_detail
    low = masked.lower()

    mole_leaks = 0
    if re.search(rf"\b{re.escape(mole)}\b", masked):
        mole_leaks += 1
    if "mole" in low or (mole_name and mole_name.lower() in low):
        mole_leaks += 1

    seed_leaks = 0
    if str(ws) in masked or f"{ws:016x}" in low:
        seed_leaks += 1
    if (
        f"{target}:{seed}".lower() in low
        or f"seed={seed}" in low
        or f"seed:{seed}" in low
        or f"seed {seed}" in low
    ):
        seed_leaks += 1
    if seed >= 1000 and str(seed) in masked:
        seed_leaks += 1

    v_leaks = 0
    if "true_v" in low or "hidden_v" in low or "v=" in low:
        v_leaks += 1
    if hidden_v is not None and 0.0 < hidden_v < 1.0:
        v_tokens = {
            f"{hidden_v:.2f}",
            f"{hidden_v:.3f}",
            f"{hidden_v:.4f}",
            f"{round(hidden_v, 6):g}",
        }
        v_tokens.discard("0")
        v_tokens.discard("1")
        if any(vt in masked for vt in v_tokens):
            v_leaks += 1

    return (mole_leaks, seed_leaks, v_leaks)


def _audit_seed_detail_parity_and_leaks(
    target: str,
    seed: int,
    env_cls: Any,
    emps: list[str],
    mole: str,
    decoy: str | None,
    peer: str,
    mole_name: str,
    ws: int,
) -> dict[str, Any]:
    p = tier_params(target)
    actors: list[tuple[str, str]] = [("mole", mole), ("innocent", peer)]
    if decoy is not None:
        actors.append(("decoy", decoy))

    probes_checked = 0
    parity_mismatches = 0
    bad_schema_violations = 0
    mole_leaks = 0
    seed_leaks = 0
    hidden_v_leaks = 0
    tools_covered: set[str] = set()
    canonical_sigs: list[tuple[str, bool, str | None, tuple[str, ...], str | None]] = []

    def record_single(probe_id: str, tool_name: str, res: Any, caller_emp: str | None, hv: float | None = None):
        nonlocal probes_checked, bad_schema_violations, mole_leaks, seed_leaks, hidden_v_leaks
        probes_checked += 1
        tools_covered.add(tool_name)
        sig = _norm_error_sig(res, caller_emp)
        if res.ok:
            bad_schema_violations += 1
        elif res.error == BAD:
            if sig[2] != ("detail",) or not isinstance(sig[3], str) or not sig[3]:
                bad_schema_violations += 1
        else:
            if sig[2] != ():
                bad_schema_violations += 1
        ml, sl, vl = _scan_detail_secret_leaks(res, caller_emp, mole, mole_name, target, seed, ws, hv)
        mole_leaks += ml
        seed_leaks += sl
        hidden_v_leaks += vl
        canonical_sigs.append((probe_id, sig[0], sig[1], sig[2], sig[3]))
        return sig

    def record_actor_group(probe_id: str, tool_name: str, call_fn, hv: float | None = None):
        nonlocal parity_mismatches
        actor_sigs = []
        for role_tag, emp_id in actors:
            res = call_fn(role_tag, emp_id)
            sig = record_single(f"{probe_id}:{role_tag}", tool_name, res, emp_id, hv=hv)
            actor_sigs.append(sig)
        if len(set(actor_sigs)) > 1:
            parity_mismatches += 1
        canonical_sigs.append((f"{probe_id}:canonical", actor_sigs[0][0], actor_sigs[0][1], actor_sigs[0][2], actor_sigs[0][3]))

    schema_env = env_cls(target, seed)
    for tool in ALL_TOOLS:
        record_single(f"non_dict:{tool}", tool, schema_env.call(tool, ["not_a_dict"]), None)
        record_actor_group(
            f"unknown_arg:{tool}",
            tool,
            lambda _rt, emp, tl=tool: schema_env.call(tl, {"_unexpected_field": emp}),
        )
        _, _, req = _SPECS[tool]
        if req:
            record_single(f"missing_req:{tool}", tool, schema_env.call(tool, {}), None)

    for day_tool, base_args_fn in (
        ("list_documents", lambda _emp: {}),
        ("read_access_logs", lambda emp: {"employee": emp}),
        ("search_messages", lambda emp: {"query": emp}),
    ):
        for bound_tag, d_from, d_to in (
            ("day_low", 0, 1),
            ("day_high", 1, p.n_days + 1),
            ("day_inverted", 2, 1),
            ("day_bool", True, 1),
        ):
            record_actor_group(
                f"{bound_tag}:{day_tool}",
                day_tool,
                lambda _rt, emp, dt=day_tool, bfn=base_args_fn, df=d_from, dto=d_to: schema_env.call(
                    dt, {**bfn(emp), "day_from": df, "day_to": dto}
                ),
            )

    record_actor_group(
        "interview_bad_topic",
        "interview",
        lambda _rt, emp: schema_env.call("interview", {"employee": emp, "topic": "invalid_topic"}),
    )
    record_actor_group(
        "interview_non_str_topic",
        "interview",
        lambda _rt, emp: schema_env.call("interview", {"employee": emp, "topic": 99}),
    )
    record_actor_group(
        "read_message_unknown_id",
        "read_message",
        lambda _rt, emp: schema_env.call("read_message", {"id": f"missing-{emp}"}),
    )
    record_actor_group(
        "search_messages_wildcard",
        "search_messages",
        lambda _rt, emp: schema_env.call("search_messages", {"query": f"{emp}*"}),
    )
    record_single(
        "search_messages_empty",
        "search_messages",
        schema_env.call("search_messages", {"query": "   "}),
        None,
    )
    for emp_tool, extra in (
        ("read_access_logs", {"day_from": 1, "day_to": 1}),
        ("interview", {"topic": "workload"}),
        ("restrict_access", {}),
        ("unrestrict_access", {}),
        ("accuse", {}),
    ):
        record_single(
            f"unknown_emp:{emp_tool}",
            emp_tool,
            schema_env.call(emp_tool, {**extra, "employee": "e99"}),
            None,
        )

    st_envs = {emp: env_cls(target, seed) for _, emp in actors}
    record_actor_group(
        "unrestrict_when_unrestricted",
        "unrestrict_access",
        lambda _rt, emp: st_envs[emp].call("unrestrict_access", {"employee": emp}),
    )
    for _, emp in actors:
        st_envs[emp].call("restrict_access", {"employee": emp})
    record_actor_group(
        "restrict_when_already_restricted",
        "restrict_access",
        lambda _rt, emp: st_envs[emp].call("restrict_access", {"employee": emp}),
    )
    record_actor_group(
        "canary_restricted_recipient",
        "plant_canary",
        lambda _rt, emp: st_envs[emp].call(
            "plant_canary", {"doc_title": "Audit", "assignment": {emp: "A"}}
        ),
    )
    for _, emp in actors:
        st_envs[emp].call("unrestrict_access", {"employee": emp})
    record_actor_group(
        "canary_blank_variant_label",
        "plant_canary",
        lambda _rt, emp: st_envs[emp].call(
            "plant_canary", {"doc_title": "Audit", "assignment": {emp: ""}}
        ),
    )
    record_actor_group(
        "canary_blank_title",
        "plant_canary",
        lambda _rt, emp: st_envs[emp].call(
            "plant_canary", {"doc_title": "   ", "assignment": {emp: "A"}}
        ),
    )

    def _too_many_variants(_rt: str, emp: str) -> Any:
        others = [x for x in emps if x != emp][: p.max_variants]
        asg = {eid: f"V{idx}" for idx, eid in enumerate([emp, *others])}
        return st_envs[emp].call("plant_canary", {"doc_title": "Variants", "assignment": asg})

    record_actor_group("canary_too_many_variants", "plant_canary", _too_many_variants)

    cap_envs = {emp: env_cls(target, seed) for _, emp in actors}
    for _, emp in actors:
        for ci in range(p.canaries_per_day):
            cap_envs[emp].call("plant_canary", {"doc_title": f"C{ci}", "assignment": {emp: "A"}})
    record_actor_group(
        "canary_daily_cap_exceeded",
        "plant_canary",
        lambda _rt, emp: cap_envs[emp].call(
            "plant_canary", {"doc_title": "CapExtra", "assignment": {emp: "A"}}
        ),
    )

    day1_hv_probe_sigs: list[tuple[str, str | None]] = []
    for tool in ALL_TOOLS:
        r0 = schema_env.call(tool, {"_hv_check": "x"})
        day1_hv_probe_sigs.append((tool, (r0.data or {}).get("detail")))

    hv_env = env_cls(target, seed)
    reached_hidden_v = False
    for _ in range(p.n_days - 1):
        hv_env.call("advance_day", {})
        if hv_env.V < hv_env.visible_V():
            reached_hidden_v = True
            break
    hv_val = float(hv_env.V) if reached_hidden_v else None
    hidden_v_detail_drift = 0
    for idx_t, tool in enumerate(ALL_TOOLS):
        rh = hv_env.call(tool, {"_hv_check": "x"})
        record_single(f"hv_unknown_arg:{tool}", tool, rh, None, hv=hv_val)
        if (rh.data or {}).get("detail") != day1_hv_probe_sigs[idx_t][1]:
            hidden_v_detail_drift += 1
    record_actor_group(
        "hv_interview_bad_topic",
        "interview",
        lambda _rt, emp: hv_env.call("interview", {"employee": emp, "topic": "bad_topic"}),
        hv=hv_val,
    )
    record_actor_group(
        "hv_read_message_unknown",
        "read_message",
        lambda _rt, emp: hv_env.call("read_message", {"id": f"hv-missing-{emp}"}),
        hv=hv_val,
    )
    record_actor_group(
        "hv_unrestrict_unrestricted",
        "unrestrict_access",
        lambda _rt, emp: hv_env.call("unrestrict_access", {"employee": emp}),
        hv=hv_val,
    )

    fp_digest = hashlib.sha256(
        json.dumps(canonical_sigs, sort_keys=False).encode("utf-8")
    ).hexdigest()[:24]

    return {
        "probes_checked": probes_checked,
        "tools_covered_count": len(tools_covered),
        "all_13_tools_covered": len(tools_covered) == len(ALL_TOOLS),
        "parity_mismatches": parity_mismatches,
        "bad_schema_violations": bad_schema_violations,
        "mole_id_leaks": mole_leaks,
        "seed_leaks": seed_leaks,
        "hidden_v_leaks": hidden_v_leaks + hidden_v_detail_drift,
        "reached_hidden_v": reached_hidden_v,
        "fingerprint": fp_digest,
    }


def _single_seed_tool_parity(args: tuple[str, int, Any]) -> dict[str, Any]:
    target, seed, env_cls = args
    base = env_cls(target, seed)
    emp_rows = base.call("list_employees", {}).data["employees"]
    emps = [r["id"] for r in emp_rows]
    mole = base._world.mole
    decoy = base._world.decoy
    ws = base._world.world_seed
    mole_name = next((e.name for e in base._world.employees if e.id == mole), "")
    innocents = [e for e in emps if e != mole and e != decoy]
    rng = random.Random(f"parity-peer:{target}:{seed}")
    peer = rng.choice(innocents)

    exact_diffs: dict[str, int] = {}
    ok_mismatches = 0

    e_m, e_i = env_cls(target, seed), env_cls(target, seed)
    r_m = e_m.call("restrict_access", {"employee": mole})
    r_i = e_i.call("restrict_access", {"employee": peer})
    exact_diffs["restrict_access"] = abs(_serialized_bytes(r_m) - _serialized_bytes(r_i))
    ok_mismatches += int(r_m.ok != r_i.ok)

    s_m = e_m.call("status", {})
    s_i = e_i.call("status", {})
    exact_diffs["status"] = abs(_serialized_bytes(s_m) - _serialized_bytes(s_i))
    ok_mismatches += int(s_m.ok != s_i.ok)

    u_m = e_m.call("unrestrict_access", {"employee": mole})
    u_i = e_i.call("unrestrict_access", {"employee": peer})
    exact_diffs["unrestrict_access"] = abs(_serialized_bytes(u_m) - _serialized_bytes(u_i))
    ok_mismatches += int(u_m.ok != u_i.ok)

    c_m = e_m.call("plant_canary", {"doc_title": "Audit check", "assignment": {mole: "A"}})
    c_i = e_i.call("plant_canary", {"doc_title": "Audit check", "assignment": {peer: "A"}})
    exact_diffs["plant_canary"] = abs(_serialized_bytes(c_m) - _serialized_bytes(c_i))
    ok_mismatches += int(c_m.ok != c_i.ok)

    d_m = e_m.call("list_documents", {})
    d_i = e_i.call("list_documents", {})
    exact_diffs["list_documents"] = abs(_serialized_bytes(d_m) - _serialized_bytes(d_i))
    ok_mismatches += int(d_m.ok != d_i.ok)

    f_m = e_m.call("check_leak_feed", {})
    f_i = e_i.call("check_leak_feed", {})
    exact_diffs["check_leak_feed"] = abs(_serialized_bytes(f_m) - _serialized_bytes(f_i))
    ok_mismatches += int(f_m.ok != f_i.ok)

    l_m = e_m.call("read_access_logs", {"day_from": 1, "day_to": 1, "employee": mole})
    l_i = e_i.call("read_access_logs", {"day_from": 1, "day_to": 1, "employee": peer})
    exact_diffs["read_access_logs"] = abs(_serialized_bytes(l_m) - _serialized_bytes(l_i))
    ok_mismatches += int(l_m.ok != l_i.ok)

    sm_m = e_m.call("search_messages", {"query": mole})
    sm_i = e_i.call("search_messages", {"query": peer})
    exact_diffs["search_messages"] = abs(_serialized_bytes(sm_m) - _serialized_bytes(sm_i))
    ok_mismatches += int(sm_m.ok != sm_i.ok)

    rm_m = e_m.call("read_message", {"id": f"missing-{mole}"})
    rm_i = e_i.call("read_message", {"id": f"missing-{peer}"})
    exact_diffs["read_message"] = abs(_serialized_bytes(rm_m) - _serialized_bytes(rm_i))
    ok_mismatches += int(rm_m.ok != rm_i.ok)

    iv_err_m = e_m.call("interview", {"employee": mole, "topic": "invalid_topic"})
    iv_err_i = e_i.call("interview", {"employee": peer, "topic": "invalid_topic"})
    exact_diffs["interview"] = abs(_serialized_bytes(iv_err_m) - _serialized_bytes(iv_err_i))
    ok_mismatches += int(iv_err_m.ok != iv_err_i.ok)

    a2_m, a2_i = env_cls(target, seed), env_cls(target, seed)
    a2_m.call("restrict_access", {"employee": mole})
    a2_i.call("restrict_access", {"employee": peer})
    adv_m = a2_m.call("advance_day", {})
    adv_i = a2_i.call("advance_day", {})
    exact_diffs["advance_day"] = abs(_serialized_bytes(adv_m) - _serialized_bytes(adv_i))
    ok_mismatches += int(adv_m.ok != adv_i.ok)

    le_m = a2_m.call("list_employees", {})
    le_i = a2_i.call("list_employees", {})
    exact_diffs["list_employees"] = abs(_serialized_bytes(le_m) - _serialized_bytes(le_i))
    ok_mismatches += int(le_m.ok != le_i.ok)

    ac_m = a2_m.call("accuse", {"employee": mole})
    ac_i = a2_i.call("accuse", {"employee": peer})
    post_m = a2_m.call("status", {})
    post_i = a2_i.call("status", {})
    exact_diffs["accuse"] = abs(_serialized_bytes(ac_m) - _serialized_bytes(ac_i)) + abs(
        _serialized_bytes(post_m) - _serialized_bytes(post_i)
    )
    ok_mismatches += int(ac_m.ok != ac_i.ok) + int(post_m.ok != post_i.ok)

    row_bytes_by_id = {
        r["id"]: len(json.dumps(r, sort_keys=True).encode("utf-8")) for r in emp_rows
    }
    emp_row_diff = float(row_bytes_by_id[mole] - row_bytes_by_id[peer])

    base.call("advance_day", {})
    msg_m_lens = [
        _serialized_bytes(base.call("read_message", {"id": mid}))
        for mid in base._msg_order
        if base._messages[mid]["sender"] == mole
    ]
    msg_i_lens = [
        _serialized_bytes(base.call("read_message", {"id": mid}))
        for mid in base._msg_order
        if base._messages[mid]["sender"] == peer
    ]
    msg_valid_diff = (
        (sum(msg_m_lens) / len(msg_m_lens)) - (sum(msg_i_lens) / len(msg_i_lens))
        if (msg_m_lens and msg_i_lens)
        else None
    )

    iv_m_env, iv_i_env = env_cls(target, seed), env_cls(target, seed)
    iv_uncond_diff = float(
        _serialized_bytes(iv_m_env.call("interview", {"employee": mole, "topic": "workload"}))
        - _serialized_bytes(iv_i_env.call("interview", {"employee": peer, "topic": "workload"}))
    )

    detail_audit = _audit_seed_detail_parity_and_leaks(
        target=target,
        seed=seed,
        env_cls=env_cls,
        emps=emps,
        mole=mole,
        decoy=decoy,
        peer=peer,
        mole_name=mole_name,
        ws=ws,
    )

    return {
        "exact_diffs": exact_diffs,
        "ok_mismatches": ok_mismatches,
        "emp_row_diff": emp_row_diff,
        "msg_valid_diff": msg_valid_diff,
        "iv_uncond_diff": iv_uncond_diff,
        "detail_audit": detail_audit,
    }


def _parity_seed_worker(args: tuple[str, list[int], str | None]) -> list[dict[str, Any]]:
    target, seeds, secret_str = args
    with deterministic_world_secret(secret_str):
        return [_single_seed_tool_parity((target, s, Env)) for s in seeds]


def _summarize_tool_parity_rows(
    target: str,
    seeds: list[int],
    rows: list[dict[str, Any]],
    alpha: float = 0.01,
) -> dict[str, Any]:
    per_tool: dict[str, dict[str, Any]] = {}
    for tool in ALL_TOOLS:
        diffs = [r["exact_diffs"][tool] for r in rows]
        per_tool[tool] = {
            "n_pairs": len(diffs),
            "max_abs_byte_diff": max(diffs) if diffs else 0,
            "nonzero_pairs": sum(1 for d in diffs if d != 0),
            "exact_parity_ok": all(d == 0 for d in diffs),
        }

    emp_diffs = [r["emp_row_diff"] for r in rows]
    msg_diffs = [r["msg_valid_diff"] for r in rows if r["msg_valid_diff"] is not None]
    iv_diffs = [r["iv_uncond_diff"] for r in rows]

    ez, ep = paired_z_and_p(emp_diffs)
    mz, mp = paired_z_and_p(msg_diffs)
    iz, ip = paired_z_and_p(iv_diffs)

    emp_flagged = (len(emp_diffs) >= 8) and (ep < (alpha / 2.0))
    msg_flagged = (len(msg_diffs) >= 8) and (mp < (alpha / 2.0))

    total_ok_mismatches = sum(r["ok_mismatches"] for r in rows)
    all_exact_zero = all(v["exact_parity_ok"] for v in per_tool.values())
    stat_ok = (not emp_flagged) and (not msg_flagged)

    d_rows = [r["detail_audit"] for r in rows]
    ref_fp = d_rows[0]["fingerprint"] if d_rows else ""
    cross_seed_mismatches = sum(1 for d in d_rows[1:] if d["fingerprint"] != ref_fp)
    detail_summary = {
        "commit_ref": "1bc3e281",
        "probes_checked": sum(d["probes_checked"] for d in d_rows),
        "all_13_tools_covered": all(d["all_13_tools_covered"] for d in d_rows),
        "actor_parity_mismatches": sum(d["parity_mismatches"] for d in d_rows),
        "schema_envelope_violations": sum(d["bad_schema_violations"] for d in d_rows),
        "cross_seed_mismatches": cross_seed_mismatches,
        "mole_id_leaks": sum(d["mole_id_leaks"] for d in d_rows),
        "seed_leaks": sum(d["seed_leaks"] for d in d_rows),
        "hidden_v_leaks": sum(d["hidden_v_leaks"] for d in d_rows),
        "hidden_v_states_exercised": sum(int(d["reached_hidden_v"]) for d in d_rows),
    }
    detail_ok = (
        detail_summary["all_13_tools_covered"]
        and detail_summary["actor_parity_mismatches"] == 0
        and detail_summary["schema_envelope_violations"] == 0
        and detail_summary["cross_seed_mismatches"] == 0
        and detail_summary["mole_id_leaks"] == 0
        and detail_summary["seed_leaks"] == 0
        and detail_summary["hidden_v_leaks"] == 0
    )
    detail_summary["ok"] = detail_ok

    return {
        "target": target,
        "n_seeds": len(seeds),
        "tools_checked": len(per_tool),
        "ok_flag_mismatches": total_ok_mismatches,
        "all_13_tools_state_matched_exact_zero": all_exact_zero,
        "per_tool_state_matched": per_tool,
        "detail_error_audit": detail_summary,
        "statistical_content_lengths": {
            "list_employees_row_bytes": {
                "n_pairs": len(emp_diffs),
                "mean_diff_mole_minus_innocent": round(sum(emp_diffs) / max(1, len(emp_diffs)), 4),
                "paired_z": round(ez, 4),
                "paired_p": round(ep, 6),
                "leak_flagged": emp_flagged,
            },
            "read_message_sender_bytes": {
                "n_pairs": len(msg_diffs),
                "mean_diff_mole_minus_innocent": round(sum(msg_diffs) / max(1, len(msg_diffs)), 4)
                if msg_diffs
                else 0.0,
                "paired_z": round(mz, 4),
                "paired_p": round(mp, 6),
                "leak_flagged": msg_flagged,
            },
            "interview_workload_unconditional_bytes": {
                "n_pairs": len(iv_diffs),
                "mean_diff_mole_minus_innocent": round(sum(iv_diffs) / max(1, len(iv_diffs)), 4),
                "paired_z": round(iz, 4),
                "paired_p": round(ip, 6),
                "note": "Documented interview_lr makes mole slightly more often evasive (shorter template); conditional-on-signal parity is checked in interview_conditional_strata.",
            },
        },
        "ok": all_exact_zero and total_ok_mismatches == 0 and stat_ok and detail_ok,
    }


def audit_tool_response_parity(
    target: str,
    seeds: list[int],
    env_cls: Any = Env,
    alpha: float = 0.01,
) -> dict[str, Any]:
    rows = [_single_seed_tool_parity((target, s, env_cls)) for s in seeds]
    return _summarize_tool_parity_rows(target, seeds, rows, alpha=alpha)


def _deep_encoding_worker(args: tuple[str, list[int], str | None]) -> dict[str, Any]:
    target, seeds, secret_str = args
    tier_params(target)
    with deterministic_world_secret(secret_str):
        return enc_mod.audit_env_no_encoded_leak(tier=target, seeds=seeds)


def run_deep_encodings_audit(
    targets: list[str],
    seeds: list[int],
    secret_str: str | None,
    workers: int = 1,
) -> dict[str, Any]:
    pos = enc_mod.self_test()
    tasks: list[tuple[str, list[int], str | None]] = []
    chunk = max(1, len(seeds) // max(1, workers))
    for target in targets:
        for i in range(0, len(seeds), chunk):
            tasks.append((target, seeds[i : i + chunk], secret_str))

    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            part_results = list(ex.map(_deep_encoding_worker, tasks))
    else:
        part_results = [_deep_encoding_worker(t) for t in tasks]

    by_target: dict[str, dict[str, Any]] = {}
    for t in targets:
        t_parts = [r for r in part_results if r["tier"] == t]
        leaks = [lk for r in t_parts for lk in r["leaks"]]
        texts_scanned = sum(int(r["texts_scanned"]) for r in t_parts)
        n_eps = sum(int(r["n_episodes"]) for r in t_parts)
        by_target[t] = {
            "ok": len(leaks) == 0,
            "n_episodes": n_eps,
            "texts_scanned": texts_scanned,
            "leak_count": len(leaks),
            "leaks": leaks[:10],
        }

    total_leaks = sum(v["leak_count"] for v in by_target.values())
    return {
        "ok": bool(pos["ok"]) and total_leaks == 0,
        "self_test": pos,
        "total_episodes": sum(v["n_episodes"] for v in by_target.values()),
        "total_texts_scanned": sum(v["texts_scanned"] for v in by_target.values()),
        "total_leaks": total_leaks,
        "by_target": by_target,
    }


def _calibration_target_worker(args: tuple[str, list[int], bool, str | None]) -> tuple[str, dict[str, Any]]:
    target, seeds, fast_solver, secret_str = args
    with deterministic_world_secret(secret_str):
        p = tier_params(target)
        pe = p.p_evasive_innocent
        pm = min(0.999999, pe * p.interview_lr)
        w_pos = math.log(pm / pe) if pm > pe else 0.0
        w_neg = math.log((1.0 - pm) / (1.0 - pe)) if pm > pe else 0.0

        solver_scores: list[float] = []
        solver_hits = 0
        nc_always_scores: list[float] = []
        nc_always_hits = 0
        nc_cal_scores: list[float] = []
        nc_cal_accused = 0
        nc_cal_hits = 0

        for s in seeds:
            s_env = Env(target, s)
            pol = (
                SolverPolicy(None, max_candidates=16, multi_candidates=8)
                if fast_solver
                else SolverPolicy(None)
            )
            sc = float(play_baseline(s_env, pol))
            solver_scores.append(sc)
            solver_hits += int(sc > 0.0)

            for selective in (False, True):
                env = Env(target, s)
                emps = [r["id"] for r in env.call("list_employees", {}).data["employees"]]
                iv_ev = {e: 0 for e in emps}
                iv_tot = {e: 0 for e in emps}
                anger = {e: 0 for e in emps}
                q_idx = 0
                for d in range(1, p.n_days + 1):
                    used = 0
                    if d == p.n_days:
                        lr = env.call("read_access_logs", {"day_from": 1, "day_to": p.n_days - 1})
                        used += 1
                        logs = lr.data["logs"]
                        for w in ("raise", "goalposts", "deserve", "promotion", "recruiter", "joke"):
                            if used >= p.actions_per_day:
                                break
                            sr = env.call("search_messages", {"query": w})
                            used += 1
                            for m in sr.data.get("messages", []):
                                anger[m["sender"]] = anger.get(m["sender"], 0) + 1
                        decoy = max(emps, key=lambda e: anger[e]) if (p.decoy and max(anger.values()) > 0) else None
                        obs = Observations(employees=emps, decoy=decoy)
                        for e in emps:
                            obs.access_counts[e] = [0, 0]
                            obs.access_days[e] = p.n_days - 1
                        for r in logs:
                            obs.access_counts[r["employee"]][1 if r["after_hours"] else 0] += 1
                        bl = behaviour_logliks(obs, p)
                        jl = {
                            e: (
                                -1e9
                                if e == decoy
                                else bl[e] + iv_ev[e] * w_pos + (iv_tot[e] - iv_ev[e]) * w_neg
                            )
                            for e in emps
                        }
                        mx = max(jl.values())
                        z = sum(math.exp(v - mx) for v in jl.values())
                        post = {e: math.exp(v - mx) / z for e, v in jl.items()}
                        best_e = max(emps, key=lambda e: (post[e], -emps.index(e)))
                        vis_v = float(env.call("status", {}).data["V"])
                        if (not selective) or (post[best_e] > 1.0 / (1.0 + vis_v)):
                            env.call("accuse", {"employee": best_e})
                            if selective:
                                nc_cal_accused += 1
                                nc_cal_hits += int(env.score() > 0.0)
                            else:
                                nc_always_hits += int(env.score() > 0.0)
                        else:
                            env.call("advance_day", {})
                        if selective:
                            nc_cal_scores.append(float(env.score()))
                        else:
                            nc_always_scores.append(float(env.score()))
                        break
                    while used < p.actions_per_day:
                        e = emps[q_idx % len(emps)]
                        top = TOPICS[(q_idx // len(emps)) % len(TOPICS)]
                        q_idx += 1
                        ir = env.call("interview", {"employee": e, "topic": top})
                        if ir.ok:
                            used += 1
                            iv_tot[e] += 1
                            if ir.data["answer"] in EVASIVE_TEMPLATES:
                                iv_ev[e] += 1
                        else:
                            break
                    env.call("advance_day", {})

        n = max(1, len(seeds))
        s_mean = sum(solver_scores) / n
        always_mean = sum(nc_always_scores) / n
        cal_mean = sum(nc_cal_scores) / n
        return (
            target,
            {
                "n_seeds": len(seeds),
                "solver_mean_score": round(s_mean, 6),
                "solver_accuracy": round(solver_hits / n, 6),
                "non_canary_always_accuse_mean_score": round(always_mean, 6),
                "non_canary_always_accuse_accuracy": round(nc_always_hits / n, 6),
                "non_canary_selective_mean_score": round(cal_mean, 6),
                "non_canary_selective_accused_rate": round(nc_cal_accused / n, 6),
                "non_canary_selective_precision": round(nc_cal_hits / max(1, nc_cal_accused), 6)
                if nc_cal_accused
                else None,
                "solver_beats_non_canary": s_mean > max(always_mean, cal_mean),
            },
        )


def run_policy_calibration_comparison(
    targets: list[str],
    seeds: list[int],
    fast_solver: bool = False,
    workers: int = 1,
    secret_str: str | None = None,
) -> dict[str, Any]:
    tasks = [(t, seeds, fast_solver, secret_str) for t in targets]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as ex:
            pairs = list(ex.map(_calibration_target_worker, tasks))
    else:
        pairs = [_calibration_target_worker(task) for task in tasks]
    return {t: res for t, res in pairs}


class PlantedToolByteLeakEnv(Env):
    def call(self, tool: str, args: dict) -> Any:
        res = super().call(tool, args)
        if (
            isinstance(args, dict)
            and tool == "restrict_access"
            and res.ok
            and args.get("employee") == self._world.mole
        ):
            res.data = dict(res.data, pad="    ")
        return res


class PlantedToolDetailParityEnv(Env):
    def call(self, tool: str, args: dict) -> Any:
        res = super().call(tool, args)
        if (
            not res.ok
            and res.error == BAD
            and isinstance(res.data, dict)
            and "detail" in res.data
            and isinstance(args, dict)
            and tool == "unrestrict_access"
            and args.get("employee") == self._world.mole
        ):
            emp = args["employee"]
            res.data = {"detail": f"{emp} is now restricted"}
        return res


class PlantedToolDetailSecretLeakEnv(Env):
    def call(self, tool: str, args: dict) -> Any:
        res = super().call(tool, args)
        if (
            not res.ok
            and res.error == BAD
            and isinstance(res.data, dict)
            and "detail" in res.data
            and tool == "read_message"
        ):
            res.data = {
                "detail": (
                    f"{res.data['detail']} "
                    f"[ref={self._world.mole} ws={self._world.world_seed} true_v={self.V:.2f}]"
                )
            }
        return res


def run_planted_positive_controls(quick: bool = False) -> dict[str, Any]:
    seeds = list(range(8 if quick else 24))
    bars = compute_fair_bars("easy", mc_trials=2000 if quick else 4000, rng_seed=3)
    raw_eps = [_extract_single_episode(("easy", s, False)) for s in seeds]

    roster_eps = json.loads(json.dumps(raw_eps))
    for ep in roster_eps:
        for r in ep["employees"]:
            if r["id"] == ep["mole"]:
                r["name_bytes"] += 40
    roster_eval = evaluate_non_canary_features("easy", roster_eps, bars)
    longest_row = next(r for r in roster_eval["predictors"] if r["predictor"] == "roster_name_longest")
    roster_detected = (
        (not roster_eval["ok"])
        and bool(longest_row["beats_fair_bar"])
        and longest_row["accuracy"] == 1.0
    )

    order_eps = json.loads(json.dumps(raw_eps))
    for ep in order_eps:
        ep["doc_order_inversions"] += 2
        ep["log_order_inversions"] += 3
        for r in ep["employees"]:
            if r["id"] == ep["mole"]:
                r["doc_first"] += 50
    order_eval = evaluate_non_canary_features("easy", order_eps, bars)
    doc_first_row = next(r for r in order_eval["predictors"] if r["predictor"] == "doc_first_recipient_freq")
    order_detected = (
        (not order_eval["ok"])
        and order_eval["ordering_and_lint"]["doc_recipient_order_inversions"] > 0
        and order_eval["ordering_and_lint"]["access_log_order_inversions"] > 0
        and bool(doc_first_row["beats_fair_bar"])
    )

    parity_seeds = list(range(2 if quick else 8))
    tool_parity = audit_tool_response_parity("easy", parity_seeds, env_cls=PlantedToolByteLeakEnv)
    tool_detected = (
        (not tool_parity["ok"])
        and (not tool_parity["all_13_tools_state_matched_exact_zero"])
        and tool_parity["per_tool_state_matched"]["restrict_access"]["max_abs_byte_diff"] > 0
    )

    detail_parity = audit_tool_response_parity(
        "medium", parity_seeds, env_cls=PlantedToolDetailParityEnv
    )
    detail_parity_detected = (
        (not detail_parity["ok"])
        and (not detail_parity["detail_error_audit"]["ok"])
        and detail_parity["detail_error_audit"]["actor_parity_mismatches"] > 0
        and detail_parity["all_13_tools_state_matched_exact_zero"]
    )

    detail_secret = audit_tool_response_parity(
        "medium", parity_seeds, env_cls=PlantedToolDetailSecretLeakEnv
    )
    ds_audit = detail_secret["detail_error_audit"]
    detail_secret_detected = (
        (not detail_secret["ok"])
        and (not ds_audit["ok"])
        and ds_audit["mole_id_leaks"] > 0
        and ds_audit["seed_leaks"] > 0
        and ds_audit["hidden_v_leaks"] > 0
    )

    secret = "mole=e07"
    stego_modes = ("zero_width_stego", "cyrillic_homoglyphs", "morse", "nato_phonetic", "acrostic_words")
    stego_hits: dict[str, bool] = {}
    for mode in stego_modes:
        payload = enc_mod.ENCODERS[mode](secret)
        hits = enc_mod.scan_for_secret([f"Weekly note: {payload}"], [secret])
        stego_hits[mode] = any(h["token"] == secret for h in hits)
    stego_detected = all(stego_hits.values())

    return {
        "all_detected": (
            roster_detected
            and order_detected
            and tool_detected
            and detail_parity_detected
            and detail_secret_detected
            and stego_detected
        ),
        "planted_roster_name_length_leak": {
            "detected": roster_detected,
            "accuracy": longest_row["accuracy"],
            "p_value_bonferroni": longest_row["p_value_bonferroni"],
        },
        "planted_doc_and_log_ordering_leak": {
            "detected": order_detected,
            "doc_inversions": order_eval["ordering_and_lint"]["doc_recipient_order_inversions"],
            "log_inversions": order_eval["ordering_and_lint"]["access_log_order_inversions"],
            "doc_first_accuracy": doc_first_row["accuracy"],
        },
        "planted_tool_response_byte_leak": {
            "detected": tool_detected,
            "restrict_access_max_byte_diff": tool_parity["per_tool_state_matched"]["restrict_access"][
                "max_abs_byte_diff"
            ],
        },
        "planted_tool_detail_parity_leak": {
            "detected": detail_parity_detected,
            "actor_parity_mismatches": detail_parity["detail_error_audit"]["actor_parity_mismatches"],
            "zero_byte_diff_evaded_size_check": detail_parity["all_13_tools_state_matched_exact_zero"],
        },
        "planted_tool_detail_secret_leak": {
            "detected": detail_secret_detected,
            "mole_id_leaks": ds_audit["mole_id_leaks"],
            "seed_leaks": ds_audit["seed_leaks"],
            "hidden_v_leaks": ds_audit["hidden_v_leaks"],
        },
        "planted_stego_text_leaks": {
            "detected": stego_detected,
            "modes_caught": stego_hits,
        },
    }


def audit_tooling_compat_issues() -> dict[str, Any]:
    tp_track_errors: dict[str, str] = {}
    for trk in sorted(TRACKS):
        try:
            tp_mod.fair_bar(trk, 2)
        except Exception as exc:
            tp_track_errors[trk] = f"{type(exc).__name__}: {exc}"

    sp = SolverPolicy(tier_params("medium"))
    env = Env("medium", 0)
    env.call("list_employees", {})
    sp._ingest(env.history[-1])
    mole = env._world.mole
    evasive_seen = 0
    ingested_true = 0
    for _ in range(1, 10):
        for top in TOPICS:
            ir = env.call("interview", {"employee": mole, "topic": top})
            if ir.ok and ir.data["answer"] in EVASIVE_TEMPLATES:
                evasive_seen += 1
                sp._ingest(env.history[-1])
                ingested_true += int(sp.obs.interviews[-1][1])
        env.call("advance_day", {})
        if evasive_seen >= 3:
            break

    hard_depts = sorted({e.dept for e in Env("hard", 0)._world.employees})
    hard_forge_depts = sorted({e.dept for e in Env("hard_forge", 0)._world.employees})
    hard_rl_depts = sorted({e.dept for e in Env("hard_rl", 0)._world.employees})

    return {
        "text_probe_track_keyerrors": tp_track_errors,
        "text_probe_tracks_fail_without_tier_params": set(tp_track_errors) == set(TRACKS),
        "solver_interview_evasive_samples": evasive_seen,
        "solver_interview_ingested_as_evasive": ingested_true,
        "evasive_templates_containing_literal_evasive": sum(
            int("evasive" in tpl.lower()) for tpl in EVASIVE_TEMPLATES
        ),
        "solver_interview_ingest_always_false_confirmed": (evasive_seen > 0 and ingested_true == 0),
        "hard_dept_count": len(hard_depts),
        "hard_forge_dept_count": len(hard_forge_depts),
        "hard_rl_dept_count": len(hard_rl_depts),
        "hard_rl_missing_depts_vs_hard": sorted(set(hard_depts) - set(hard_rl_depts)),
    }


def _extract_worker(args: tuple[str, list[int], str | None]) -> list[dict[str, Any]]:
    target, seeds, secret_str = args
    with deterministic_world_secret(secret_str):
        return [_extract_single_episode((target, s, True)) for s in seeds]


def run_sweep(
    targets: list[str],
    dev_seeds: list[int],
    judge_seeds: list[int],
    deep_encoding_dev_seeds: list[int],
    world_secret: str | None = DEFAULT_PUBLIC_TEST_SECRET,
    mc_trials: int = 20000,
    workers: int = 1,
    cal_seed_limit: int = 40,
    quick: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    fair_bars = {t: compute_fair_bars(t, mc_trials=mc_trials) for t in targets}

    all_seeds_by_band = {"dev": dev_seeds, "judge": judge_seeds}
    combined_seeds = dev_seeds + judge_seeds

    extract_tasks: list[tuple[str, list[int], str | None]] = []
    stage_workers = 1 if quick else workers
    chunk = max(1, len(combined_seeds) // max(1, stage_workers))
    for target in targets:
        for i in range(0, len(combined_seeds), chunk):
            extract_tasks.append((target, combined_seeds[i : i + chunk], world_secret))

    parity_tasks: list[tuple[str, list[int], str | None]] = []
    for target in targets:
        for i in range(0, len(combined_seeds), chunk):
            parity_tasks.append((target, combined_seeds[i : i + chunk], world_secret))

    if stage_workers > 1 and len(extract_tasks) > 1:
        with ProcessPoolExecutor(max_workers=stage_workers) as ex:
            chunks_out = list(ex.map(_extract_worker, extract_tasks))
            parity_chunks = list(ex.map(_parity_seed_worker, parity_tasks))
    else:
        chunks_out = [_extract_worker(task) for task in extract_tasks]
        parity_chunks = [_parity_seed_worker(task) for task in parity_tasks]

    eps_by_target: dict[str, list[dict[str, Any]]] = {t: [] for t in targets}
    for part in chunks_out:
        for ep in part:
            eps_by_target[ep["target"]].append(ep)
    for t in targets:
        eps_by_target[t].sort(key=lambda ep: (0 if ep["seed"] < 100000 else 1, ep["seed"]))

    parity_rows_by_target: dict[str, list[dict[str, Any]]] = {t: [] for t in targets}
    for task_spec, rows_part in zip(parity_tasks, parity_chunks):
        parity_rows_by_target[task_spec[0]].extend(rows_part)

    dev_set = set(dev_seeds)
    judge_set = set(judge_seeds)

    feature_audit_pooled: dict[str, Any] = {}
    feature_audit_by_band: dict[str, dict[str, Any]] = {"dev": {}, "judge": {}}
    parity_by_target: dict[str, Any] = {}

    with deterministic_world_secret(world_secret) as installed_secret:
        for t in targets:
            eps_all = eps_by_target[t]
            eps_dev = [e for e in eps_all if e["seed"] in dev_set]
            eps_judge = [e for e in eps_all if e["seed"] in judge_set]
            feature_audit_pooled[t] = evaluate_non_canary_features(t, eps_all, fair_bars[t])
            feature_audit_by_band["dev"][t] = evaluate_non_canary_features(t, eps_dev, fair_bars[t])
            feature_audit_by_band["judge"][t] = evaluate_non_canary_features(t, eps_judge, fair_bars[t])
            parity_by_target[t] = _summarize_tool_parity_rows(
                t, combined_seeds, parity_rows_by_target[t]
            )

        planted_controls = run_planted_positive_controls(quick=quick)
        compat_issues = audit_tooling_compat_issues()

    cal_seeds = dev_seeds[: min(cal_seed_limit, len(dev_seeds))]
    calibration = run_policy_calibration_comparison(
        targets,
        cal_seeds,
        fast_solver=quick,
        workers=stage_workers,
        secret_str=world_secret,
    )

    deep_seeds = deep_encoding_dev_seeds + (judge_seeds[:1] if quick else judge_seeds)
    deep_encodings = run_deep_encodings_audit(
        targets,
        deep_seeds,
        world_secret,
        workers=workers,
    )

    total_primary_episodes = sum(len(eps_by_target[t]) for t in targets)
    total_prose_texts = sum(
        feature_audit_pooled[t]["ordering_and_lint"]["total_prose_texts_scanned"] for t in targets
    )
    total_docs = sum(feature_audit_pooled[t]["ordering_and_lint"]["total_docs_checked"] for t in targets)
    total_logs = sum(feature_audit_pooled[t]["ordering_and_lint"]["total_logs_checked"] for t in targets)
    total_msgs = sum(feature_audit_pooled[t]["ordering_and_lint"]["total_messages_checked"] for t in targets)

    features_ok = all(feature_audit_pooled[t]["ok"] for t in targets)
    bands_ok = all(
        feature_audit_by_band[b][t]["ok"] for b in all_seeds_by_band for t in targets
    )
    parity_ok = all(parity_by_target[t]["ok"] for t in targets)
    calibration_ok = all(calibration[t]["solver_beats_non_canary"] for t in targets)
    overall_ok = (
        features_ok
        and bands_ok
        and parity_ok
        and deep_encodings["ok"]
        and planted_controls["all_detected"]
        and calibration_ok
    )

    elapsed = round(time.perf_counter() - t0, 3)
    return {
        "ok": overall_ok,
        "tiers_version": TIERS_VERSION,
        "targets": targets,
        "n_dev_seeds_per_target": len(dev_seeds),
        "n_judge_seeds_per_target": len(judge_seeds),
        "dev_seed_range": f"{dev_seeds[0]}-{dev_seeds[-1]}" if dev_seeds else "",
        "judge_seed_range": f"{judge_seeds[0]}-{judge_seeds[-1]}" if judge_seeds else "",
        "world_secret_public_fallback_used": installed_secret,
        "world_secret_label": world_secret if installed_secret else "env_or_salt",
        "headline": {
            "primary_episodes": total_primary_episodes,
            "dev_episodes": len(dev_seeds) * len(targets),
            "judge_episodes": len(judge_seeds) * len(targets),
            "tool_parity_seed_pairs": len(combined_seeds) * len(targets),
            "detail_probes_checked": sum(
                parity_by_target[t]["detail_error_audit"]["probes_checked"] for t in targets
            ),
            "deep_encoding_episodes": deep_encodings["total_episodes"],
            "prose_texts_scanned": total_prose_texts,
            "deep_encoding_texts_scanned": deep_encodings["total_texts_scanned"],
            "documents_checked": total_docs,
            "access_logs_checked": total_logs,
            "messages_checked": total_msgs,
            "non_canary_predictors_beating_fair_bar": sum(
                int(r["beats_fair_bar"])
                for t in targets
                for r in feature_audit_pooled[t]["predictors"]
            ),
            "conditional_interview_leaks": sum(
                int(v["conditional_leak"])
                for t in targets
                for v in feature_audit_pooled[t]["interview_conditional_strata"].values()
            ),
            "doc_recipient_order_inversions": sum(
                feature_audit_pooled[t]["ordering_and_lint"]["doc_recipient_order_inversions"]
                for t in targets
            ),
            "access_log_order_inversions": sum(
                feature_audit_pooled[t]["ordering_and_lint"]["access_log_order_inversions"]
                for t in targets
            ),
            "message_id_sequence_gaps": sum(
                feature_audit_pooled[t]["ordering_and_lint"]["message_id_sequence_gaps"]
                for t in targets
            ),
            "text_lint_violations": sum(
                feature_audit_pooled[t]["ordering_and_lint"]["text_lint_violations"]
                for t in targets
            ),
            "all_13_tools_state_matched_byte_parity": all(
                parity_by_target[t]["all_13_tools_state_matched_exact_zero"] for t in targets
            ),
            "all_13_tools_detail_parity": all(
                parity_by_target[t]["detail_error_audit"]["ok"] for t in targets
            ),
            "detail_mole_id_leaks": sum(
                parity_by_target[t]["detail_error_audit"]["mole_id_leaks"] for t in targets
            ),
            "detail_seed_leaks": sum(
                parity_by_target[t]["detail_error_audit"]["seed_leaks"] for t in targets
            ),
            "detail_hidden_v_leaks": sum(
                parity_by_target[t]["detail_error_audit"]["hidden_v_leaks"] for t in targets
            ),
            "encoded_secret_leaks": deep_encodings["total_leaks"]
            + sum(
                feature_audit_pooled[t]["stego_character_scan"]["encoded_secret_hits"]
                for t in targets
            ),
            "planted_positive_controls_all_detected": planted_controls["all_detected"],
            "solver_beats_non_canary_all_targets": calibration_ok,
            "elapsed_seconds": elapsed,
        },
        "fair_bars": fair_bars,
        "feature_audit_pooled": feature_audit_pooled,
        "feature_audit_by_band": feature_audit_by_band,
        "tool_response_parity": parity_by_target,
        "deep_encodings_audit": deep_encodings,
        "policy_calibration": calibration,
        "planted_positive_controls": planted_controls,
        "report_only_issues": compat_issues,
    }


def check_report_file(report_path: Path) -> dict[str, Any]:
    raw_bytes = report_path.read_bytes()
    text = raw_bytes.decode("utf-8")
    low = text.lower()
    bad_dashes = [d for d in (chr(0x2014), chr(0x2013), chr(0x2212)) if d in text]
    banned_prereg = [s for s in ("pre-reg", "prereg") if s in low]
    size_ok = len(raw_bytes) <= MAX_REPORT_BYTES
    required_tokens = (
        "easy",
        "medium",
        "hard",
        "hard_forge",
        "hard_rl",
        "900000-900039",
        "1,200",
        "1bc3e281",
        "detail",
        "planted",
        "ISSUE-W1-TEXTPROBE-TRACKS",
        "ISSUE-W1-SOLVER-IV-INGEST",
    )
    missing = [tok for tok in required_tokens if tok not in text]
    return {
        "ok": (not bad_dashes) and (not banned_prereg) and size_ok and (not missing),
        "size_bytes": len(raw_bytes),
        "size_ok": size_ok,
        "bad_dashes": bad_dashes,
        "banned_prereg": banned_prereg,
        "missing_tokens": missing,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_sidechannel_and_text_sweep")
    ap.add_argument("--targets", default=",".join(ALL_TARGETS))
    ap.add_argument("--dev-seeds", default="0-199")
    ap.add_argument("--judge-seeds", default=f"{JUDGE_SEEDS[0]}-{JUDGE_SEEDS[-1]}")
    ap.add_argument("--deep-encoding-dev-seeds", default="0-19")
    ap.add_argument("--world-secret", default=DEFAULT_PUBLIC_TEST_SECRET)
    ap.add_argument("--mc-trials", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--cal-seeds", type=int, default=40)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--check-report", default=None)
    args = ap.parse_args(argv)

    targets = parse_targets(args.targets)
    if args.quick:
        dev_seeds = [0, 1]
        judge_seeds = [900000, 900001]
        deep_dev_seeds = []
        mc_trials = 2500
        workers = max(1, args.workers)
        cal_seeds = 2
    else:
        dev_seeds = parse_seeds(args.dev_seeds)
        judge_seeds = parse_seeds(args.judge_seeds)
        deep_dev_seeds = parse_seeds(args.deep_encoding_dev_seeds)
        mc_trials = args.mc_trials
        workers = max(1, args.workers)
        cal_seeds = args.cal_seeds

    payload = run_sweep(
        targets=targets,
        dev_seeds=dev_seeds,
        judge_seeds=judge_seeds,
        deep_encoding_dev_seeds=deep_dev_seeds,
        world_secret=args.world_secret,
        mc_trials=mc_trials,
        workers=workers,
        cal_seed_limit=cal_seeds,
        quick=args.quick,
    )

    if args.check_report:
        rep_check = check_report_file(Path(args.check_report))
        payload["report_check"] = rep_check
        payload["ok"] = bool(payload["ok"] and rep_check["ok"])

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload["headline"], indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
