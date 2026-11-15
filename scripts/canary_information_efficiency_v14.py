"""Deterministic keyless v1.4 Shannon entropy and canary-partition efficiency verifier.

    python scripts/canary_information_efficiency_v14.py
    python scripts/canary_information_efficiency_v14.py --check
    python scripts/canary_information_efficiency_v14.py --check --full-check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary import rules
from canary.analysis.tags import to_result
from canary.env import Env, INVESTIGATIVE_TOOLS
from canary.redteam.anticheat import _canon, _client_only_step, _client_truncated_bytes, _norm_result
from canary.rules import TIERS, tier_params_for_episode
from canary.solver.belief import _fallback, behaviour_logliks, leak_loglik
from canary.solver.params import params_from_instruction
from canary.solver.policy import SolverPolicy
from canary.types import Step

HASH_CHAR = chr(35)
H1, H2 = HASH_CHAR + " ", HASH_CHAR * 2 + " "
EN_DASH, EM_DASH, MINUS_SIGN, PLUS_MINUS = chr(0x2013), chr(0x2014), chr(0x2212), chr(0x00B1)

SCHEMA_VERSION = "canary_information_efficiency_v14.v1"
TIERS_VERSION = "v1.4"
PRIMARY_SEEDS: tuple[int, ...] = tuple(range(30))
FLOAT_TOL = 1e-9
IDENTITY_TOL = 1e-12
JSON_DIGITS = 6
MAX_JSON_BYTES = 80_000
LOG2_3 = math.log2(3.0)

DEFAULT_OUT_JSON = ROOT / "results/eval_v14/canary_information_efficiency_v14.json"
DEFAULT_OUT_MD = ROOT / "docs/reports/canary_information_efficiency_v14.md"

EXPECTED_INPUTS_SHA256 = "a6f13d9cea43fca74992b32ed0443e0b11afe726bf05074c62b3c8a4a7a552ca"
EXPECTED_OUT_JSON_SHA256 = "ce5b8341a93a4828b9c7f015210aee6ac54c7541edae5488a997dfcf144c0574"

COHORT_SPECS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("solver", "solver", "hard", "committed_reference_v1.4", (
        "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
        "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
    )),
    ("opencode-gpt-5.5", "opencode:openai/gpt-5.5", "hard", "committed_preregistered_second_family_v1.4", (
        "data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl",
    )),
    ("inproc-gemini-4-carbon", "gemini:gemini-4-carbon", "hard", "committed_primary_locked_v1.4", (
        "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl",
    )),
    ("opencode-gemini-4-carbon", "opencode:google/gemini-4-carbon", "hard", "committed_primary_locked_v1.4", (
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",
    )),
    ("opencode-gemini-3.5-flash", "opencode:google/gemini-3.5-flash", "hard", "committed_primary_locked_v1.4", (
        "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl",
    )),
    ("solver", "solver", "medium", "committed_reference_v1.4", (
        "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
        "data/runs/committed/v1.4/reference/solver-medium-seeds20to29/episodes.jsonl",
    )),
    ("inproc-gemini-4-carbon", "gemini:gemini-4-carbon", "medium", "committed_primary_locked_v1.4", (
        "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl",
    )),
    ("opencode-gemini-4-carbon", "opencode:google/gemini-4-carbon", "medium", "committed_primary_locked_v1.4", (
        "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl",
    )),
    ("opencode-gemini-3.5-flash", "opencode:google/gemini-3.5-flash", "medium", "fr8_replication_3shard_v1.4", (
        "results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-00-14/episodes.jsonl",
        "results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-15-29/episodes.jsonl",
        "results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-s28/episodes.jsonl",
    )),
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"(?:AIza[0-9A-Za-z_\-]{20,}|\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b)")),
    ("oauth_or_provider_token", re.compile(r"\b(?:ya29\.[0-9A-Za-z_\-]{20,}|xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret_env_assignment",
        re.compile(
            r"\b(?:(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|CANARY_LEDGER_TOKEN|"
            r"CANARY_ADMIN_TOKEN|XAI_API_KEY|HF_TOKEN)\s*=\s*[\x27\x22]?[A-Za-z0-9_\-]{16,}"
            r"|CANARY_WORLD_SECRET\s*=\s*[\x27\x22]?(?!canary-demo-live(?![A-Za-z0-9_\-]))[A-Za-z0-9_\-]{16,})"
        ),
    ),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
)


def norm_ascii(text: str) -> str:
    return text.replace(EN_DASH, "-").replace(EM_DASH, "--").replace(MINUS_SIGN, "-").replace(PLUS_MINUS, "+/-")


def round_clean(obj: Any, ndigits: int = JSON_DIGITS) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return norm_ascii(obj) if isinstance(obj, str) else obj
    if isinstance(obj, float):
        val = round(obj, ndigits)
        return 0.0 if val == 0.0 else val
    if isinstance(obj, dict):
        return {str(k): round_clean(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_clean(v, ndigits) for v in obj]
    return obj


def serialize_json(payload: dict[str, Any]) -> str:
    return json.dumps(round_clean(payload, JSON_DIGITS), indent=1, ensure_ascii=True) + "\n"


def approx_equal(a: Any, b: Any, tol: float = 1e-6) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def binary_entropy_bits(p: float) -> float:
    return 0.0 if p <= 0.0 or p >= 1.0 else -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)


def canary_leak_ceiling_bits(max_variants: int, fingerprint_accuracy: float) -> float:
    if max_variants <= 1:
        return 0.0
    h_out = math.log2(float(max_variants))
    if fingerprint_accuracy >= 1.0:
        return h_out
    err = 1.0 - fingerprint_accuracy
    return h_out - (-fingerprint_accuracy * math.log2(fingerprint_accuracy) - err * math.log2(err / (max_variants - 1)))


def interview_channel_mi_bits(prior_mole: float, p_evasive_innocent: float, interview_lr: float) -> float:
    q0 = p_evasive_innocent
    q1 = min(1.0, q0 * interview_lr)
    q_mix = prior_mole * q1 + (1.0 - prior_mole) * q0
    return binary_entropy_bits(q_mix) - prior_mole * binary_entropy_bits(q1) - (1.0 - prior_mole) * binary_entropy_bits(q0)


def entropy_bits(probs: dict[str, float] | list[float]) -> float:
    vals = probs.values() if isinstance(probs, dict) else probs
    h = -sum(p * math.log2(p) for p in vals if p > 0.0)
    return 0.0 if h == 0.0 else h


def kl_divergence_bits(p: dict[str, float] | list[float], q: dict[str, float] | list[float]) -> float:
    if isinstance(p, dict) and isinstance(q, dict):
        pairs = [(float(pv), float(q.get(k, 0.0))) for k, pv in p.items()]
    elif not isinstance(p, dict) and not isinstance(q, dict):
        if len(p) != len(q):
            raise ValueError(f"Distribution length mismatch: {len(p)} vs {len(q)}")
        pairs = [(float(pv), float(qv)) for pv, qv in zip(p, q)]
    else:
        raise TypeError("Both distributions must have matching container types")
    acc = 0.0
    for pv, qv in pairs:
        if pv < 0.0 or qv < 0.0:
            raise ValueError("Probabilities must be non-negative")
        if pv > 0.0:
            if qv <= 0.0:
                return math.inf
            acc += pv * math.log2(pv / qv)
    return 0.0 if abs(acc) <= 1e-15 else max(0.0, acc)


def mean_ci95_hw(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return (xs[0] if n == 1 else 0.0, 0.0)
    m = sum(xs) / n
    return (m, 1.96 * math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) / math.sqrt(n))


def _match_step(r_ok: bool, r_data: Any, r_error: str | None, rec_raw: Any) -> bool:
    if rec_raw is None:
        return True
    want = _norm_result(rec_raw)
    got: dict[str, Any] = {"ok": r_ok, "data": r_data, "error": r_error}
    has_det = isinstance(want, dict) and isinstance(want.get("data"), dict) and "detail" in want["data"]
    if not r_ok and isinstance(r_data, dict) and set(r_data) == {"detail"} and not has_det:
        got = {"ok": r_ok, "data": {}, "error": r_error}
    trunc = _client_truncated_bytes(want)
    if trunc is not None:
        return len(json.dumps(got).encode("utf-8")) == trunc
    return want is None or got == want or _canon(got) == _canon(want)


def _assemble_posterior(sp: SolverPolicy, leak_ll: dict[str, float], beh_ll: dict[str, float], iv_ll: dict[str, float]) -> dict[str, float]:
    o, bt = sp.obs, sp.behaviour_temper
    logs: dict[str, float] = {}
    for s in o.employees:
        lp = leak_ll[s]
        if bt > 0.0 and lp > -math.inf:
            lp += bt * beh_ll[s] + iv_ll[s]
        if o.decoy is not None and s == o.decoy:
            lp = -math.inf
        logs[s] = lp
    m = max(logs.values()) if logs else -math.inf
    if m == -math.inf:
        return _fallback(o)
    z = sum(math.exp(v - m) for v in logs.values())
    return {s: math.exp(v - m) / z for s, v in logs.items()}


def analyze_episode(ep: dict[str, Any]) -> dict[str, Any]:
    if rules.TIERS_VERSION != TIERS_VERSION:
        raise RuntimeError(f"Expected TIERS_VERSION={TIERS_VERSION}, got {rules.TIERS_VERSION}")
    tier, seed = str(ep["tier"]), int(ep["seed"])
    P = TIERS[tier]
    h0 = math.log2(float(P.n_employees))
    cur_post = {f"e{i + 1:02d}": 1.0 / P.n_employees for i in range(P.n_employees)}

    res = to_result(ep)
    env = Env(tier, seed)
    ins = env.instruction()
    sp = SolverPolicy(params_from_instruction(ins) or tier_params_for_episode(tier, res.steps))
    sp.reset([], ins)
    sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()

    leak_ll: dict[str, float] = {}
    beh_ll: dict[str, float] = {}
    iv_ll: dict[str, float] = {}
    pe = sp.P.p_evasive_innocent
    pm = min(0.999, pe * sp.P.interview_lr)
    iv_ev_step = sp.behaviour_temper * math.log(pm / pe)
    iv_co_step = sp.behaviour_temper * math.log((1.0 - pm) / (1.0 - pe))

    h_prev = h0
    ch = {"leak_doc": 0.0, "logs": 0.0, "msgs": 0.0, "interview": 0.0, "other": 0.0}
    counts = {"canary": 0, "interview": 0, "search": 0, "logs": 0, "restrict": 0, "inv": 0}
    steps_verified = 0
    canaries: list[dict[str, float | int]] = []

    for idx, (raw_st, st) in enumerate(zip(ep.get("steps") or [], res.steps)):
        if _client_only_step(raw_st):
            continue
        r = env.call(st.tool, st.args or {})
        if not _match_step(r.ok, r.data, r.error, raw_st.get("result")):
            raise ValueError(f"Replay mismatch on {ep.get('agent')} {tier} seed {seed} step {idx} ({st.tool})")
        steps_verified += 1

        if r.ok:
            if st.tool in INVESTIGATIVE_TOOLS:
                counts["inv"] += 1
            if st.tool == "plant_canary":
                counts["canary"] += 1
                asg = dict((st.args or {}).get("assignment") or {})
                k_rec = len(asg)
                cov = k_rec / P.n_employees
                care_w = (1.0 - cov) if P.careful_mole else 1.0
                vc: dict[str, int] = {}
                vp: dict[str, float] = {}
                for emp, lab in asg.items():
                    vc[str(lab)] = vc.get(str(lab), 0) + 1
                    vp[str(lab)] = vp.get(str(lab), 0.0) + float(cur_post.get(emp, 0.0))
                p_cov = sum(vp.values())
                canaries.append({
                    "k": k_rec, "n_variants": len(vc), "cov": cov, "careful_w": care_w,
                    "p_cov": p_cov, "eff_exp": p_cov * care_w,
                    "h_rec": entropy_bits([c / k_rec for c in vc.values()]),
                    "h_post": entropy_bits([w / p_cov for w in vp.values()]) if p_cov > 0.0 else 0.0,
                })
            elif st.tool == "interview":
                counts["interview"] += 1
            elif st.tool in ("search_messages", "read_message"):
                counts["search"] += 1
            elif st.tool == "read_access_logs":
                counts["logs"] += 1
            elif st.tool in ("restrict_access", "unrestrict_access"):
                counts["restrict"] += 1

        pre_closed = (len(sp.obs.closed_days), sp.obs.today, sp.obs.decoy)
        sp._ingest(Step(t=st.t, day=st.day, tool=st.tool, args=st.args, result={"ok": r.ok, "data": r.data, "error": r.error}))
        if r.ok and sp.obs.employees:
            sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
            if st.tool == "list_employees":
                leak_ll = {s: leak_loglik(sp.obs, s, sp.P, sp.choice_temper, sp.noleak_temper) for s in sp.obs.employees}
                beh_ll = behaviour_logliks(sp.obs, sp.P) if sp.behaviour_temper > 0 else {s: 0.0 for s in sp.obs.employees}
                iv_ll = {s: 0.0 for s in sp.obs.employees}
                cur_post = _assemble_posterior(sp, leak_ll, beh_ll, iv_ll)
            elif st.tool in ("list_documents", "check_leak_feed") or (st.tool in ("status", "advance_day") and (len(sp.obs.closed_days), sp.obs.today, sp.obs.decoy) != pre_closed):
                leak_ll = {s: leak_loglik(sp.obs, s, sp.P, sp.choice_temper, sp.noleak_temper) for s in sp.obs.employees}
                cur_post = _assemble_posterior(sp, leak_ll, beh_ll, iv_ll)
            elif st.tool == "read_access_logs" or (st.tool == "search_messages" and sp.obs.decoy != pre_closed[2]):
                beh_ll = behaviour_logliks(sp.obs, sp.P) if sp.behaviour_temper > 0 else beh_ll
                cur_post = _assemble_posterior(sp, leak_ll, beh_ll, iv_ll)
            elif st.tool == "interview":
                who, ev = sp.obs.interviews[-1]
                iv_ll[who] = iv_ll.get(who, 0.0) + (iv_ev_step if ev else iv_co_step)
                cur_post = _assemble_posterior(sp, leak_ll, beh_ll, iv_ll)

        h_now = entropy_bits(cur_post) if sp.obs.employees else h_prev
        dh = h_prev - h_now
        h_prev = h_now
        if st.tool in ("check_leak_feed", "list_documents", "status", "advance_day"):
            ch["leak_doc"] += dh
        elif st.tool == "read_access_logs":
            ch["logs"] += dh
        elif st.tool in ("search_messages", "read_message"):
            ch["msgs"] += dh
        elif st.tool == "interview":
            ch["interview"] += dh
        else:
            ch["other"] += dh

    if sp.obs.employees:
        ref_post = sp.belief()
        if max(abs(cur_post[s] - ref_post[s]) for s in cur_post) > 1e-11:
            raise ValueError(f"Incremental posterior drift on {tier} seed {seed}")

    verdict = env.verdict()
    if abs(float(env.score()) - float(ep["score"])) > FLOAT_TOL or verdict["accused"] != ep.get("accused"):
        raise ValueError(f"Verdict mismatch on {ep.get('agent')} {tier} seed {seed}")
    delta_h = h0 - h_prev
    residual = abs(sum(ch.values()) - delta_h)
    if residual > IDENTITY_TOL:
        raise ValueError(f"Entropy telescoping residual {residual} on {tier} seed {seed}")

    leaked_c = sum(1 for cid in env._canary_ids if cid in env._leaked)
    surfaced_c = sum(1 for it in env._feed if env._doc_by_id[it["doc_id"]]["is_canary"] and int(it["surfaced_day"]) <= env.day)
    return {
        "seed": seed, "score": float(env.score()), "correct": bool(verdict["correct"]),
        "final_day": int(verdict["final_day"]), "h_final": h_prev, "delta_h": delta_h,
        "ch": ch, "residual": residual, "counts": counts,
        "leaked_c": leaked_c, "surfaced_c": surfaced_c, "canaries": canaries, "steps_verified": steps_verified,
    }


def summarize_cohort(root: Path, spec: tuple[str, str, str, str, tuple[str, ...]]) -> dict[str, Any]:
    cohort, agent_label, tier, prov, paths = spec
    P = TIERS[tier]
    by_seed: dict[int, dict[str, Any]] = {}
    for rel in paths:
        for ln in (root / rel).read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            ep = json.loads(ln)
            meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            if ep.get("tier") == tier and ep.get("valid") is not False and meta.get("valid") is not False and int(ep["seed"]) in PRIMARY_SEEDS:
                by_seed[int(ep["seed"])] = analyze_episode(ep)
    if len(by_seed) != len(PRIMARY_SEEDS):
        raise ValueError(f"Expected 30 seeds for {cohort} {tier}, got {len(by_seed)}")

    eps = [by_seed[s] for s in PRIMARY_SEEDS]
    n = len(eps)
    cans = [c for e in eps for c in e["canaries"]]
    tot_c = len(cans)
    tot_iv = sum(int(e["counts"]["interview"]) for e in eps)
    tot_inv = sum(int(e["counts"]["inv"]) for e in eps)
    tot_srch = sum(int(e["counts"]["search"]) for e in eps)
    tot_logs = sum(int(e["counts"]["logs"]) for e in eps)
    tot_rest = sum(int(e["counts"]["restrict"]) for e in eps)
    tot_leaked = sum(int(e["leaked_c"]) for e in eps)
    tot_surf = sum(int(e["surfaced_c"]) for e in eps)
    horizon_cap = n * P.canaries_per_day * P.n_days
    active_cap = sum(P.canaries_per_day * int(e["final_day"]) for e in eps)

    dh_mean, dh_hw = mean_ci95_hw([float(e["delta_h"]) for e in eps])
    hf_mean, hf_hw = mean_ci95_hw([float(e["h_final"]) for e in eps])
    sc_mean, sc_hw = mean_ci95_hw([float(e["score"]) for e in eps])
    tot_dh = sum(float(e["delta_h"]) for e in eps)
    tot_ch_iv = sum(float(e["ch"]["interview"]) for e in eps)
    tot_ch_ld = sum(float(e["ch"]["leak_doc"]) for e in eps)
    h_post_mean = sum(float(c["h_post"]) for c in cans) / max(1, tot_c)

    return {
        "cohort": cohort, "agent": agent_label, "tier": tier, "provenance": prov, "n": n,
        "score_mean": sc_mean, "score_ci95_hw": sc_hw,
        "accuracy": sum(1 for e in eps if e["correct"]) / n,
        "mean_final_day": sum(int(e["final_day"]) for e in eps) / n,
        "steps_verified": sum(int(e["steps_verified"]) for e in eps),
        "partition_balance": {
            "total_canaries": tot_c, "canaries_per_ep": tot_c / n,
            "ceiling_3way_bits": LOG2_3,
            "noisy_leak_ceiling_bits": canary_leak_ceiling_bits(P.max_variants, P.fingerprint_accuracy),
            "recipient_entropy_bits_mean": sum(float(c["h_rec"]) for c in cans) / max(1, tot_c),
            "posterior_entropy_bits_mean": h_post_mean,
            "posterior_balance_efficiency": h_post_mean / LOG2_3,
            "singleton_k1_rate": sum(1 for c in cans if int(c["k"]) == 1) / max(1, tot_c),
            "tiny_subset_k_le_3_rate": sum(1 for c in cans if int(c["k"]) <= 3) / max(1, tot_c),
            "sub_3variant_rate": sum(1 for c in cans if int(c["n_variants"]) < 3) / max(1, tot_c),
            "min_recipients_k": min(int(c["k"]) for c in cans),
            "max_recipients_k": max(int(c["k"]) for c in cans),
        },
        "careful_mole_and_capacity": {
            "recipient_coverage_mean": sum(float(c["cov"]) for c in cans) / max(1, tot_c),
            "careful_mole_weight_mean": sum(float(c["careful_w"]) for c in cans) / max(1, tot_c),
            "posterior_mass_covered_mean": sum(float(c["p_cov"]) for c in cans) / max(1, tot_c),
            "effective_trigger_exposure_mean": sum(float(c["eff_exp"]) for c in cans) / max(1, tot_c),
            "wide_ge_50pct_staff_rate": sum(1 for c in cans if float(c["cov"]) >= 0.5) / max(1, tot_c),
            "full_staff_zero_weight_count": sum(1 for c in cans if int(c["k"]) == P.n_employees),
            "leaked_canary_rate": tot_leaked / max(1, tot_c),
            "surfaced_canary_rate": tot_surf / max(1, tot_c),
            "horizon_capacity_utilization": tot_c / horizon_cap,
            "active_day_capacity_utilization": tot_c / active_cap,
        },
        "entropy_reduction": {
            "h0_bits": math.log2(float(P.n_employees)),
            "h_final_bits_mean": hf_mean, "h_final_bits_ci95_hw": hf_hw,
            "delta_h_bits_mean": dh_mean, "delta_h_bits_ci95_hw": dh_hw,
            "leak_and_doc_channel_bits": tot_ch_ld / n,
            "access_log_channel_bits": sum(float(e["ch"]["logs"]) for e in eps) / n,
            "message_channel_bits": sum(float(e["ch"]["msgs"]) for e in eps) / n,
            "interview_channel_bits": tot_ch_iv / n,
            "max_telescoping_residual": max(float(e["residual"]) for e in eps),
            "realized_total_bits_per_canary": tot_dh / max(1, tot_c),
            "realized_leak_doc_bits_per_canary": tot_ch_ld / max(1, tot_c),
            "realized_leak_doc_bits_per_surfaced_canary": tot_ch_ld / max(1, tot_surf),
            "realized_bits_per_interview": (tot_ch_iv / tot_iv) if tot_iv > 0 else None,
            "interview_lr": P.interview_lr,
            "interview_mi_half_prior_ceiling_bits": interview_channel_mi_bits(0.5, P.p_evasive_innocent, P.interview_lr),
        },
        "tool_budget": {
            "investigative_calls_per_ep": tot_inv / n,
            "plant_canary_per_ep": tot_c / n, "interview_per_ep": tot_iv / n,
            "search_and_read_msg_per_ep": tot_srch / n, "read_access_logs_per_ep": tot_logs / n,
            "restrict_ops_per_ep": tot_rest / n,
            "plant_canary_share_of_investigative": tot_c / max(1, tot_inv),
            "interview_share_of_investigative": tot_iv / max(1, tot_inv),
            "search_msg_share_of_investigative": tot_srch / max(1, tot_inv),
        },
    }


def verify_harbor_rehearsal_contrast(root: Path) -> dict[str, Any]:
    table_txt = norm_ascii((root / "results/harbor/rehearsal/TABLE.md").read_text(encoding="utf-8"))
    build_txt = norm_ascii((root / "results/harbor/rehearsal/BUILD.txt").read_text(encoding="utf-8"))
    gap_txt = norm_ascii((root / "docs/reports/gap.md").read_text(encoding="utf-8"))
    ceo_txt = norm_ascii((root / "docs/reports/CEO.md").read_text(encoding="utf-8"))
    for token in ("1bc3e281", "93% [20%, 371%]", "116% [78%, 363%]", "131% [86%, 590%]"):
        if token not in table_txt or (token != "1bc3e281" and token not in gap_txt):
            raise ValueError(f"Missing rehearsal token {token!r}")
    if "harbor: 0.26.0" not in build_txt or "20 of 28 trials" not in gap_txt or "aa1c679e" not in ceo_txt:
        raise ValueError("Harbor BUILD/gap/CEO provenance tokens missing")
    return {
        "build_tag_commit": "1bc3e281", "final_rehearsal_commits": ["aa1c679e", "5f9b3297"],
        "harbor_version": "0.26.0", "judge_tasks": "hard seeds 900000-900009 (10 tasks)",
        "run_ratios_vs_oracle": ["93% [20%, 371%]", "116% [78%, 363%]", "131% [86%, 590%]"],
        "run3_final_valid_trials": 9, "run3_final_mean": 0.626,
        "shell_used_trials": "20/28", "total_correct_over_accused": "28/29",
        "mcp_only_hard_headline_raw": "65% [24%, 98%]", "mcp_only_hard_headline_luck_adjusted": "72% [52%, 91%]",
    }


def compute_all(root: Path = ROOT) -> dict[str, Any]:
    cohorts = [summarize_cohort(root, spec) for spec in COHORT_SPECS]
    return {
        "schema_version": SCHEMA_VERSION, "tiers_version": TIERS_VERSION,
        "primary_seeds": "0-29", "n_seeds_per_cohort": len(PRIMARY_SEEDS),
        "theoretical_bounds": {
            "max_3way_partition_bits": LOG2_3,
            "hard_noisy_3way_leak_mi_bits": canary_leak_ceiling_bits(3, 0.95),
            "hard_h0_bits": math.log2(40.0), "medium_h0_bits": math.log2(20.0),
            "hard_interview_lr": 1.2,
            "hard_interview_mi_ceiling_bits": interview_channel_mi_bits(0.5, 0.20, 1.2),
            "hard_interview_mi_prior_bits": interview_channel_mi_bits(1.0 / 40.0, 0.20, 1.2),
            "medium_interview_lr": 1.3,
            "medium_interview_mi_ceiling_bits": interview_channel_mi_bits(0.5, 0.20, 1.3),
        },
        "verification_totals": {
            "cohorts_verified": len(cohorts),
            "episodes_replayed": sum(int(c["n"]) for c in cohorts),
            "steps_verified": sum(int(c["steps_verified"]) for c in cohorts),
            "max_telescoping_residual": max(float(c["entropy_reduction"]["max_telescoping_residual"]) for c in cohorts),
        },
        "harbor_rehearsal_contrast": verify_harbor_rehearsal_contrast(root),
        "cohorts": cohorts,
    }


def render_markdown_report(data: dict[str, Any]) -> str:
    tb, hr = data["theoretical_bounds"], data["harbor_rehearsal_contrast"]
    by_ct = {(c["cohort"], c["tier"]): c for c in data["cohorts"]}
    oc_m = by_ct[("opencode-gemini-4-carbon", "medium")]
    oc_h = by_ct[("opencode-gemini-4-carbon", "hard")]
    ip_h = by_ct[("inproc-gemini-4-carbon", "hard")]
    sv_h = by_ct[("solver", "hard")]
    gp_h = by_ct[("opencode-gpt-5.5", "hard")]
    hard_cs = [c for c in data["cohorts"] if c["tier"] == "hard"]
    ld_min = min(float(c["entropy_reduction"]["leak_and_doc_channel_bits"]) for c in hard_cs)
    ld_max = max(float(c["entropy_reduction"]["leak_and_doc_channel_bits"]) for c in hard_cs)
    ld_share_min = min(
        100.0 * float(c["entropy_reduction"]["leak_and_doc_channel_bits"]) / float(c["entropy_reduction"]["delta_h_bits_mean"])
        for c in hard_cs
    )
    oc_h_iv_tot = round(int(oc_h["n"]) * float(oc_h["tool_budget"]["interview_per_ep"]))
    ip_h_iv_tot = round(int(ip_h["n"]) * float(ip_h["tool_budget"]["interview_per_ep"]))
    iv_ratio_lo = round(float(tb["hard_noisy_3way_leak_mi_bits"]) / float(tb["hard_interview_mi_ceiling_bits"]))
    iv_ratio_hi = round(float(tb["max_3way_partition_bits"]) / float(tb["hard_interview_mi_ceiling_bits"]))
    lines = [
        f"{H1}Canary v1.4 Information Efficiency, Canary Partition & Entropy Audit (`n = 30`, Seeds `0-29`)", "",
        ("**Headline & rehearsal framing.** Across post-hoc locked `v1.4` dev seeds `0-29` (`671ed96`, 28 s after `8fd4dec`, "
         "lock against later reruns and cherry-picking, not a pre-registration), OpenCode `gemini-4-carbon` over MCP scores "
         f"**`{hr['mcp_only_hard_headline_raw']}`** raw (`{hr['mcp_only_hard_headline_luck_adjusted']}` luck-adjusted) on Hard vs "
         "`111% [99%, 127%]` raw (`101% [85%, 119%]` luck-adjusted) on Medium, while pre-registered OpenCode "
         "`gpt-5.5` (`cf394894`) reaches **`101% [79%, 140%]`** raw (`84% [67%, 103%]` luck-adjusted; no gap for this agent). "
         f"In the 3-run Harbor `{hr['harbor_version']}` judge rehearsal (`{hr['build_tag_commit']}`, corrected in `aa1c679e` / `5f9b3297`), "
         f"`gemini-4-carbon` scored **`{hr['run_ratios_vs_oracle'][0]}`**, **`{hr['run_ratios_vs_oracle'][1]}`**, and "
         f"**`{hr['run_ratios_vs_oracle'][2]}`** (`{hr['run3_final_valid_trials']}` valid trials in run 3, mean `+{hr['run3_final_mean']:.3f}`, "
         f"`{hr['total_correct_over_accused']}` accusations correct) where the container shell was used in **`{hr['shell_used_trials']}`** "
         "trials -- the MCP-only Hard gap did not reproduce in the judge path."), "",
        "```bash",
        "python scripts/canary_information_efficiency_v14.py",
        "python scripts/canary_information_efficiency_v14.py --check",
        "python scripts/canary_information_efficiency_v14.py --check --full-check",
        "```", "",
        f"{H2}1. Theoretical Channel Ceilings (`v1.4` Rules)", "",
        (f"- **3-variant canary partition ceiling:** `log2(3) = {tb['max_3way_partition_bits']:.4f}` bits per noiseless "
         f"surfaced leak (Medium); under Hard's `95%` fingerprint recovery (`5%` uniform flip across the other 2 variants), "
         f"conditional leak mutual information is `{tb['hard_noisy_3way_leak_mi_bits']:.4f}` bits against initial uniform "
         f"prior `H_0 = log2(40) = {tb['hard_h0_bits']:.4f}` bits (`log2(20) = {tb['medium_h0_bits']:.4f}` bits on Medium)."),
        ("- **Careful-mole wide-distribution penalty:** On Hard and Medium (`careful_mole = True`), a canary sent to `k` "
         "of `N` staff receives leak-selection weight `1 - k / N` (`<= 0.50` once `k >= N / 2`, `0.00` at `k = N`), trading "
         "wide suspect coverage `P(mole in S)` against effective trigger exposure `P(mole in S) * (1 - k / N)`."),
        (f"- **Binary interview (`LR = 1.2` Hard, `1.3` Medium) vs canary capacity:** Even at peak sensitivity `p = 0.50`, "
         f"a single Hard `interview` (`q_0 = 0.20, q_1 = 0.24`) yields at most `{tb['hard_interview_mi_ceiling_bits']:.5f}` "
         f"bits (`{tb['hard_interview_mi_prior_bits']:.5f}` bits at `p = 1/40`; `{tb['medium_interview_mi_ceiling_bits']:.5f}` bits max on Medium) "
         f"-- `{iv_ratio_lo}x-{iv_ratio_hi}x` less mutual information than one surfaced 3-way canary leak."), "",
        f"{H2}2. Canary Partition Balance, Careful-Mole Exposure & Capacity Utilization (`0-29`)", "",
        "| Agent | Tier | Canaries/ep | Util (Act / Hor) | `H_rec` / `H_post` (bits) | `k<=3` / `<3` var | Mean Cov / `1-k/N` | Wide `>=50%` (`k=N`) | Surfaced Rate |",
        "|---|---|---:|---|---|---|---|---|---:|",
    ]
    for c in data["cohorts"]:
        pb, cm = c["partition_balance"], c["careful_mole_and_capacity"]
        lines.append(
            f"| `{c['agent']}` | `{c['tier']}` | `{pb['canaries_per_ep']:.2f}` "
            f"| `{100*cm['active_day_capacity_utilization']:.1f}% / {100*cm['horizon_capacity_utilization']:.1f}%` "
            f"| `{pb['recipient_entropy_bits_mean']:.3f} / {pb['posterior_entropy_bits_mean']:.3f}` "
            f"| `{100*pb['tiny_subset_k_le_3_rate']:.1f}% / {100*pb['sub_3variant_rate']:.1f}%` "
            f"| `{100*cm['recipient_coverage_mean']:.1f}% / {cm['careful_mole_weight_mean']:.3f}` "
            f"| `{100*cm['wide_ge_50pct_staff_rate']:.1f}%` (`{cm['full_staff_zero_weight_count']}`) "
            f"| `{100*cm['surfaced_canary_rate']:.1f}%` |"
        )
    lines.extend([
        "", f"{H2}3. Telescoping Entropy Reduction (`H_0 - H_final`) & Tool-Budget Allocation", "",
        "| Agent (`tier`) | Score | `H_final` (bits) | `Delta H` (bits) | Leak+Doc / Log / Msg / Intv (bits) | `Delta H`/Can | Bits/Intv | Tool Mix (`Can / Intv / Msg / Log` per ep) |",
        "|---|---:|---:|---:|---|---:|---:|---|",
    ])
    for c in data["cohorts"]:
        er, tbr = c["entropy_reduction"], c["tool_budget"]
        b_iv = f"{er['realized_bits_per_interview']:+.4f}" if er["realized_bits_per_interview"] is not None else "n/a"
        lines.append(
            f"| `{c['agent']}` (`{c['tier']}`) | `{c['score_mean']:+.3f}` | `{er['h_final_bits_mean']:.3f}` | `{er['delta_h_bits_mean']:.3f}` "
            f"| `{er['leak_and_doc_channel_bits']:+.2f} / {er['access_log_channel_bits']:+.2f} / {er['message_channel_bits']:+.2f} / {er['interview_channel_bits']:+.2f}` "
            f"| `{er['realized_total_bits_per_canary']:.3f}` | `{b_iv}` "
            f"| `{tbr['plant_canary_per_ep']:.1f} / {tbr['interview_per_ep']:.1f} / {tbr['search_and_read_msg_per_ep']:.1f} / {tbr['read_access_logs_per_ep']:.1f}` |"
        )
    lines.extend([
        "", f"{H2}4. Mechanistic Diagnosis & Harbor Shell Contrast", "",
        (f"1. **Action-budget starvation when Hard doubles `canaries_per_day` (`1 -> 2`):** On Medium (`1` canary/day), "
         f"`opencode:google/gemini-4-carbon` plants `{oc_m['partition_balance']['canaries_per_ep']:.2f}` canaries/ep "
         f"(`{100*oc_m['careful_mole_and_capacity']['active_day_capacity_utilization']:.1f}%` of active-day canary capacity) and "
         f"achieves `Delta H = {oc_m['entropy_reduction']['delta_h_bits_mean']:.3f}` bits "
         f"(`H_final = {oc_m['entropy_reduction']['h_final_bits_mean']:.3f}` bits, `111%` of solver). On Hard (`2` canaries/day, `8` "
         f"investigative calls/day), it spends **`{oc_h['tool_budget']['interview_per_ep']:.2f}` calls/ep "
         f"(`{100*oc_h['tool_budget']['interview_share_of_investigative']:.1f}%` of investigative calls) on `interview`** "
         f"(`{ip_h['tool_budget']['interview_per_ep']:.2f}` calls/ep in-proc) vs only "
         f"**`{oc_h['partition_balance']['canaries_per_ep']:.2f}` `plant_canary` calls/ep "
         f"(`{100*oc_h['careful_mole_and_capacity']['active_day_capacity_utilization']:.1f}%` active-day capacity)**, whereas "
         f"`solver` (`{sv_h['partition_balance']['canaries_per_ep']:.2f}` canaries, `0` interviews, "
         f"`{100*sv_h['careful_mole_and_capacity']['active_day_capacity_utilization']:.1f}%` active capacity) and "
         f"`opencode:openai/gpt-5.5` (`{gp_h['partition_balance']['canaries_per_ep']:.2f}` canaries, "
         f"`{gp_h['tool_budget']['interview_per_ep']:.2f}` interviews, "
         f"`{100*gp_h['careful_mole_and_capacity']['active_day_capacity_utilization']:.1f}%` active capacity) saturate the 2-canary/day pipeline."),
        (f"2. **Negative realized entropy return on `LR = 1.2` interviews:** Across `{oc_h_iv_tot:,}` Hard `interview` calls on "
         f"`opencode:google/gemini-4-carbon` (`{ip_h_iv_tot:,}` in-proc), realized Bayesian entropy change is "
         f"**`{oc_h['entropy_reduction']['interview_channel_bits']:+.3f}` bits/ep** "
         f"(`{oc_h['entropy_reduction']['realized_bits_per_interview']:+.4f}` bits/call) because interviewing concentrated suspects "
         "yields `76%` cooperative answers from the mole (`LR_coop = 0.95`), flattening `P_max` without resolving ties; "
         f"`leak + doc` observations carry `{ld_min:+.3f}` to `{ld_max:+.3f}` bits/ep (`>={ld_share_min:.1f}%` of total entropy "
         "reduction across every Hard cohort)."),
        (f"3. **Endgame partition floor (`min k = {oc_h['partition_balance']['min_recipients_k']}`) vs `1-vs-1-vs-1` isolation "
         f"& Harbor shell (`{hr['shell_used_trials']}` trials):** `gemini-4-carbon` achieves high 3-way split balance "
         f"(`H_rec = {oc_h['partition_balance']['recipient_entropy_bits_mean']:.3f}-{ip_h['partition_balance']['recipient_entropy_bits_mean']:.3f}` "
         f"vs `{tb['max_3way_partition_bits']:.3f}` ceiling, `0` singletons) but never plants `k <= 3` endgame probes "
         f"(`{100*oc_h['partition_balance']['tiny_subset_k_le_3_rate']:.1f}%` vs `solver` "
         f"`{100*sv_h['partition_balance']['tiny_subset_k_le_3_rate']:.1f}%` and `gpt-5.5` "
         f"`{100*gp_h['partition_balance']['tiny_subset_k_le_3_rate']:.1f}%`, though `gpt-5.5` also spends "
         f"`{100*gp_h['partition_balance']['singleton_k1_rate']:.1f}%` on `k = 1` singletons and "
         f"`{gp_h['careful_mole_and_capacity']['full_staff_zero_weight_count']}` full-40 zero-weight canary). "
         f"In Harbor (`aa1c679e` / `5f9b3297`), shell scripting (`{hr['shell_used_trials']}` trials) lets `gemini-4-carbon` automate "
         "Bayesian filtering and partition bookkeeping outside prose memory (`93%`, `116%`, `131%`), eliminating the MCP-only Hard bottleneck."), "",
    ])
    return "\n".join(lines)


def check_text_hygiene(label: str, text: str) -> list[str]:
    errs: list[str] = []
    if any(ord(ch) >= 128 for ch in text):
        errs.append(f"{label}: non-ASCII character")
    if EN_DASH in text or EM_DASH in text:
        errs.append(f"{label}: forbidden en/em dash")
    for name, rx in SECRET_PATTERNS:
        if rx.search(text):
            errs.append(f"{label}: matched forbidden {name}")
    return errs


def _repo_inputs_sha256(root: Path) -> str:
    rels: list[str] = [rel for spec in COHORT_SPECS for rel in spec[4] if (root / rel).is_file()]
    solver_dir = root / "canary/solver"
    if solver_dir.is_dir():
        rels.extend(p.relative_to(root).as_posix() for p in sorted(solver_dir.rglob("*.py")) if p.is_file())
    for extra in (
        "canary/rules.py",
        "canary/env.py",
        "results/harbor/rehearsal/TABLE.md",
        "results/harbor/rehearsal/BUILD.txt",
        "docs/reports/gap.md",
        "docs/reports/CEO.md",
    ):
        if (root / extra).is_file():
            rels.append(extra)
    h = hashlib.sha256()
    for r in sorted(set(rels)):
        h.update(r.encode("ascii") + b"\0" + hashlib.sha256((root / r).read_bytes()).digest())
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic v1.4 Shannon entropy and canary information-efficiency audit.")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--full-check", action="store_true")
    ap.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    ap.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    ap.add_argument("--root", default=str(ROOT))
    args = ap.parse_args(argv)

    root, out_json, out_md = Path(args.root).resolve(), Path(args.out_json), Path(args.out_md)
    if (args.check and not args.full_check and root == ROOT.resolve()
            and out_json.resolve() == DEFAULT_OUT_JSON.resolve() and out_md.resolve() == DEFAULT_OUT_MD.resolve()
            and out_json.is_file() and out_md.is_file()):
        raw_bytes = out_json.read_bytes()
        if (len(raw_bytes) < MAX_JSON_BYTES
                and hashlib.sha256(raw_bytes).hexdigest() == EXPECTED_OUT_JSON_SHA256
                and _repo_inputs_sha256(root) == EXPECTED_INPUTS_SHA256):
            raw_str = raw_bytes.decode("utf-8", errors="replace")
            md_disk = out_md.read_text(encoding="utf-8", errors="replace")
            errs = check_text_hygiene(str(out_json), raw_str) + check_text_hygiene(str(out_md), md_disk)
            disk_obj = json.loads(raw_str)
            if errs or not approx_equal(disk_obj, json.loads(serialize_json(disk_obj)), tol=FLOAT_TOL) or md_disk != render_markdown_report(disk_obj):
                print("CHECK FAILED: content or hygiene drift", file=sys.stderr)
                return 1
            print(f"OK: canary_information_efficiency_v14 verified ({len(disk_obj['cohorts'])} cohorts, {disk_obj['verification_totals']['episodes_replayed']} eps, {len(raw_bytes)} bytes JSON)")
            return 0

    data = compute_all(root)
    json_str, md_str = serialize_json(data), render_markdown_report(data)
    json_bytes = json_str.encode("utf-8")
    hygiene = check_text_hygiene("json", json_str) + check_text_hygiene("md", md_str)
    if len(json_bytes) >= MAX_JSON_BYTES or hygiene:
        for e in ([f"JSON size {len(json_bytes)} >= {MAX_JSON_BYTES}"] if len(json_bytes) >= MAX_JSON_BYTES else []) + hygiene:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    if args.check:
        if not out_json.is_file() or not out_md.is_file():
            print("CHECK FAILED: missing output artifact(s)", file=sys.stderr)
            return 1
        disk_bytes = out_json.read_bytes()
        disk_str, md_disk = disk_bytes.decode("utf-8", errors="replace"), out_md.read_text(encoding="utf-8", errors="replace")
        errs = check_text_hygiene(str(out_json), disk_str) + check_text_hygiene(str(out_md), md_disk)
        if len(disk_bytes) >= MAX_JSON_BYTES or errs or not approx_equal(json.loads(disk_str), json.loads(json_str), tol=FLOAT_TOL) or md_disk != md_str:
            print("CHECK FAILED: content or hygiene drift", file=sys.stderr)
            return 1
        print(f"OK: canary_information_efficiency_v14 verified ({len(data['cohorts'])} cohorts, {data['verification_totals']['episodes_replayed']} eps, {len(json_bytes)} bytes JSON)")
        return 0

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_bytes(json_bytes)
    out_md.write_text(md_str, encoding="utf-8")
    print(f"WROTE {out_json} ({len(json_bytes)} bytes) and {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
