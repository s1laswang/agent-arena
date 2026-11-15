"""Deterministic keyless v1.4 counterfactual gap-decomposition verifier and report generator.

    python scripts/counterfactual_decomposition_v14.py
    python scripts/counterfactual_decomposition_v14.py --check
    python scripts/counterfactual_decomposition_v14.py --check --full-check
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary import rules
from canary.analysis.tags import to_result
from canary.env import Env
from canary.eval import make_policy_factory, run_episode
from canary.redteam.anticheat import _canon, _client_only_step, _client_truncated_bytes, _norm_result
from canary.rules import TIERS, tier_params_for_episode
from canary.solver.params import params_from_instruction
from canary.solver.policy import SolverPolicy, accuse_value
from canary.solver.regret import q_continue
from canary.types import Step

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
H3 = HASH_CHAR * 3 + " "
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)

SCHEMA_VERSION = "counterfactual_decomposition_v14.v1"
TIERS_VERSION = "v1.4"
PRIMARY_SEEDS: tuple[int, ...] = tuple(range(30))
N_SEEDS = 30
BOOT_B = 10000
BOOT_SEED = 42
IDENTITY_TOL = 1e-12
FLOAT_TOL = 1e-9
JSON_DIGITS = 8
MAX_JSON_BYTES = 60_000

PRIMARY_SEED_LOCK_NOTE = (
    "post-hoc locked paired dev seeds 0-29 (commit 671ed96, 28 s after 8fd4dec; "
    "lock against later reruns and cherry-picking, not a pre-registration)"
)

DEFAULT_OUT_JSON = ROOT / "results/eval_v14/counterfactual_decomposition_v14.json"
DEFAULT_OUT_MD = ROOT / "docs/reports/counterfactual_decomposition_v14.md"

COMPONENT_KEYS: tuple[str, ...] = (
    "ev_abstain_rescue",
    "calibrated_wrong_accuse_residual",
    "missed_catch_information_gap",
    "timing_and_cost_bleed_gap",
    "solver_miss_frontier_catch_offset",
)

SOLVER_REF_PATHS: dict[str, tuple[str, ...]] = {
    "hard": (
        "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
        "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
    ),
    "medium": (
        "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
        "data/runs/committed/v1.4/reference/solver-medium-seeds20to29/episodes.jsonl",
    ),
}

PRIMARY_FRONTIER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "cohort": "opencode-gemini-4-carbon",
        "tier": "hard",
        "provenance": "committed_primary_locked_v1.4",
        "paths": ("data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",),
    },
    {
        "cohort": "inproc-gemini-4-carbon",
        "tier": "hard",
        "provenance": "committed_primary_locked_v1.4",
        "paths": ("data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl",),
    },
    {
        "cohort": "opencode-gemini-3.5-flash",
        "tier": "hard",
        "provenance": "committed_primary_locked_v1.4",
        "paths": ("data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl",),
    },
    {
        "cohort": "opencode-gemini-4-carbon",
        "tier": "medium",
        "provenance": "committed_primary_locked_v1.4",
        "paths": ("data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl",),
    },
    {
        "cohort": "inproc-gemini-4-carbon",
        "tier": "medium",
        "provenance": "committed_primary_locked_v1.4",
        "paths": ("data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl",),
    },
    {
        "cohort": "opencode-gemini-3.5-flash",
        "tier": "medium",
        "provenance": "fr8_replication_3shard_v1.4",
        "paths": (
            "results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-00-14/episodes.jsonl",
            "results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-15-29/episodes.jsonl",
            "results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-s28/episodes.jsonl",
        ),
        "caveat": (
            "FR8 3-shard replication (commit d4bc4f3d: medium-00-14 @ c01f371a, "
            "medium-15-29 @ 55d9781c, medium-s28 @ a5d12c7e; seed 28 rerun alone)."
        ),
    },
)

OPTIONAL_FRONTIER_DIRS: tuple[str, ...] = (
    "inproc-grok-4.20-beta",
    "opencode-grok-4.20-beta",
    "opencode-gpt-5.5",
    "opencode-gemini-4-argon",
    "opencode-gemini-4-hydrogen",
)

BASELINE_REFERENCE_AGENTS: tuple[str, ...] = (
    "grok_tactics",
)

REGIME_SHORT_CODES: dict[str, str] = {
    "both_caught": "BC",
    "calibrated_wrong_accuse": "CW",
    "rescued_wrong_accuse_solver_caught": "RW_SC",
    "rescued_wrong_accuse_solver_abstained": "RW_SA",
    "rescued_wrong_accuse_solver_wrong": "RW_SW",
    "frontier_abstained_solver_caught": "FA_SC",
    "frontier_abstained_solver_wrong": "FA_SW",
    "both_abstained": "BA",
    "frontier_caught_solver_missed": "FC_SM",
}

SECRET_AND_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("provider_token", re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret_env_assignment",
        re.compile(
            r"\b(?:"
            r"(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|CANARY_LEDGER_TOKEN|"
            r"CANARY_ADMIN_TOKEN|XAI_API_KEY|HF_TOKEN)\s*=\s*[\x27\x22]?[A-Za-z0-9_\-]{16,}"
            r"|CANARY_WORLD_SECRET\s*=\s*[\x27\x22]?(?!canary-demo-live(?![A-Za-z0-9_\-]))[A-Za-z0-9_\-]{16,}"
            r")"
        ),
    ),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
)

_BOOT_WEIGHT_CACHE: dict[tuple[int, int, int], np.ndarray] = {}


def norm_ascii(text: str) -> str:
    return (
        text.replace(EN_DASH, "-")
        .replace(EM_DASH, "--")
        .replace(MINUS_SIGN, "-")
        .replace(PLUS_MINUS, "+/-")
    )


def round_clean(obj: Any, ndigits: int = JSON_DIGITS) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return norm_ascii(obj) if isinstance(obj, str) else obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        val = round(obj, ndigits)
        return 0.0 if val == 0.0 else val
    if isinstance(obj, dict):
        return {str(k): round_clean(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_clean(v, ndigits) for v in obj]
    return obj


def _is_scalar_list(val: Any) -> bool:
    return isinstance(val, list) and all(
        v is None or isinstance(v, (bool, int, float, str)) for v in val
    )


def _is_leaf_value(val: Any) -> bool:
    return val is None or isinstance(val, (bool, int, float, str)) or _is_scalar_list(val)


def format_compact_json(obj: Any, indent: int = 0) -> str:
    pad = " " * indent
    next_pad = " " * (indent + 1)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        if all(_is_leaf_value(v) for v in obj.values()):
            one_line = json.dumps(obj, ensure_ascii=True)
            if len(one_line) <= 160:
                return one_line
        items: list[str] = []
        for k, v in obj.items():
            k_str = json.dumps(str(k), ensure_ascii=True)
            v_str = format_compact_json(v, indent + 1)
            items.append(f"{next_pad}{k_str}: {v_str}")
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        if _is_scalar_list(obj):
            return "[" + ", ".join(json.dumps(v, ensure_ascii=True) for v in obj) + "]"
        items = [f"{next_pad}{format_compact_json(v, indent + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return json.dumps(obj, ensure_ascii=True)


def serialize_json(payload: dict[str, Any]) -> str:
    return format_compact_json(round_clean(payload, JSON_DIGITS)) + "\n"


def approx_equal(a: Any, b: Any, tol: float = FLOAT_TOL) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa, fb = float(a), float(b)
        if not (math.isfinite(fa) and math.isfinite(fb)):
            return False
        return math.isclose(fa, fb, rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def mean_ci95_normal(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    m = sum(xs) / n
    if n < 2:
        return (m, 0.0)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return (m, 1.96 * sd / math.sqrt(n))


def boot_weights(n: int, B: int = BOOT_B, rng_seed: int = BOOT_SEED) -> np.ndarray:
    key = (n, B, rng_seed)
    if key not in _BOOT_WEIGHT_CACHE:
        rng = random.Random(rng_seed)
        w = np.zeros((B, n), dtype=np.float64)
        inv_n = 1.0 / n
        for b in range(B):
            for _ in range(n):
                w[b, rng.randrange(n)] += inv_n
        _BOOT_WEIGHT_CACHE[key] = w
    return _BOOT_WEIGHT_CACHE[key]


def boot_mean_ci(xs: list[float], B: int = BOOT_B, rng_seed: int = BOOT_SEED) -> tuple[list[float], np.ndarray]:
    n = len(xs)
    if n == 0:
        return ([0.0, 0.0], np.zeros(B, dtype=np.float64))
    w = boot_weights(n, B=B, rng_seed=rng_seed)
    draws = w @ np.asarray(xs, dtype=np.float64)
    ordered = np.sort(draws)
    m = int(ordered.shape[0])
    lo = float(ordered[int(0.025 * m)])
    hi = float(ordered[int(0.975 * m) - 1])
    return ([lo, hi], draws)


def shannon_entropy_bits_nats(post: dict[str, float]) -> tuple[float, float]:
    h_bits = 0.0
    h_nats = 0.0
    for p in post.values():
        if p > 0.0:
            h_bits -= p * math.log2(p)
            h_nats -= p * math.log(p)
    return (0.0 if h_bits == 0.0 else h_bits, 0.0 if h_nats == 0.0 else h_nats)


def _match_step_payload(
    r_ok: bool,
    r_data: Any,
    r_error: str | None,
    rec_raw: Any,
) -> tuple[bool, int, int]:
    if rec_raw is None:
        return (True, 0, 0)
    want = _norm_result(rec_raw)
    got_payload: dict[str, Any] = {"ok": r_ok, "data": r_data, "error": r_error}
    detail_stripped = 0
    has_recorded_detail = (
        isinstance(want, dict)
        and isinstance(want.get("data"), dict)
        and "detail" in want["data"]
    )
    if not r_ok and isinstance(r_data, dict) and set(r_data) == {"detail"} and not has_recorded_detail:
        got_payload = {"ok": r_ok, "data": {}, "error": r_error}
        detail_stripped = 1
    trunc = _client_truncated_bytes(want)
    if trunc is not None:
        return (len(json.dumps(got_payload).encode("utf-8")) == trunc, detail_stripped, 1)
    if want is None or got_payload == want or _canon(got_payload) == _canon(want):
        return (True, detail_stripped, 0)
    return (False, detail_stripped, 0)


def _detect_surfaced_flips(env: Env) -> list[dict[str, Any]]:
    flips: list[dict[str, Any]] = []
    docs = env._doc_by_id
    culprit = env._world.mole
    for it in env._feed:
        d = docs.get(it["doc_id"])
        if d and d.get("is_canary") and "variant" in it:
            assigned_var = next(k for k, v in d["variants"].items() if culprit in v)
            if it["variant"] != assigned_var:
                flips.append(
                    {
                        "doc_id": str(it["doc_id"]),
                        "shown_variant": str(it["variant"]),
                        "assigned_variant": str(assigned_var),
                        "surfaced_day": int(it["surfaced_day"]),
                    }
                )
    return flips


def replay_and_step_belief(ep: dict[str, Any]) -> dict[str, Any]:
    if rules.TIERS_VERSION != TIERS_VERSION:
        raise RuntimeError(f"Expected TIERS_VERSION={TIERS_VERSION}, got {rules.TIERS_VERSION}")
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    raw_steps = ep.get("steps") or []
    res = to_result(ep)
    env = Env(tier, seed)
    instruction = env.instruction()
    P_ep = params_from_instruction(instruction) or tier_params_for_episode(tier, res.steps)
    sp = SolverPolicy(P_ep)
    sp.reset([], instruction)

    steps_verified = 0
    steps_detail_stripped = 0
    steps_truncated_checked = 0
    steps_client_only = 0

    acc_step_idx: int | None = None
    accuse_env_t: int | None = None
    accused_emp: str | None = None
    accuse_day: int | None = None
    known_v_decision: float | None = None
    p_solver: float | None = None
    p_top: float = 0.0
    h_bits: float = 0.0
    h_nats: float = 0.0
    accuse_step_regret: float = 0.0
    premature_tag: bool = False
    n_canaries = 0

    for idx, (raw_st, st) in enumerate(zip(raw_steps, res.steps)):
        if _client_only_step(raw_st):
            steps_client_only += 1
            continue
        pre_accuse_v: float | None = None
        if st.tool == "accuse" and not env.done and acc_step_idx is None:
            pre_accuse_v = float(env.visible_V())

        r = env.call(st.tool, st.args or {})
        matched, det_strip, was_trunc = _match_step_payload(r.ok, r.data, r.error, raw_st.get("result"))
        if not matched:
            raise ValueError(
                f"Env step replay mismatch on {ep.get('agent')} {tier} seed {seed} at step {idx} ({st.tool})"
            )
        steps_verified += 1
        steps_detail_stripped += det_strip
        steps_truncated_checked += was_trunc

        if pre_accuse_v is not None and r.ok:
            acc_step_idx = idx
            accuse_env_t = len(env.history)
            accuse_day = int(st.day)
            accused_emp = str((st.args or {}).get("employee"))
            known_v_decision = pre_accuse_v
            if abs(known_v_decision - float(sp.V)) > 1e-9:
                raise ValueError(
                    f"visible_V vs SolverPolicy.V mismatch on {ep.get('agent')} {tier} seed {seed}: "
                    f"{known_v_decision} vs {sp.V}"
                )
            post = sp.belief() if sp.obs.employees else {}
            if post:
                p_solver = float(post.get(accused_emp, 0.0))
                p_top = float(max(post.values()))
                h_bits, h_nats = shannon_entropy_bits_nats(post)
                best_emp = max(post, key=post.get)
                days_left = P_ep.n_days - int(st.day)
                qc = q_continue(post, known_v_decision, P_ep, days_left)
                vstar = max(accuse_value(post[best_emp], known_v_decision, P_ep), qc, 0.0)
                accuse_step_regret = max(0.0, vstar - accuse_value(p_solver, known_v_decision, P_ep))
                premature_tag = p_solver < 0.6
            else:
                p_solver = 0.0
                p_top = 0.0
                h_bits, h_nats = (0.0, 0.0)
        elif st.tool == "plant_canary" and r.ok and acc_step_idx is None:
            n_canaries += 1

        sp._ingest(
            Step(
                t=st.t,
                day=st.day,
                tool=st.tool,
                args=st.args,
                result={"ok": r.ok, "data": r.data, "error": r.error},
            )
        )

    got_score = float(env.score())
    verdict = env.verdict()
    got_accused = verdict["accused"]
    got_correct = bool(verdict["correct"])
    true_v = float(verdict["V"])

    if abs(got_score - float(ep["score"])) > FLOAT_TOL or got_accused != ep.get("accused"):
        raise ValueError(
            f"Episode verdict mismatch on {ep.get('agent')} {tier} seed {seed}: "
            f"score {got_score} vs {ep['score']}, accused {got_accused} vs {ep.get('accused')}"
        )

    if acc_step_idx is None:
        known_v_decision = float(env.visible_V())
        post = sp.belief() if sp.obs.employees else {}
        if post:
            p_top = float(max(post.values()))
            h_bits, h_nats = shannon_entropy_bits_nats(post)

    assert known_v_decision is not None
    ev_threshold = 1.0 / (1.0 + known_v_decision)

    if got_accused is not None and p_solver is not None:
        known_ev_accuse = p_solver * known_v_decision - (1.0 - p_solver)
        luck_adjusted = p_solver * true_v - (1.0 - p_solver)
        sub_threshold = p_solver < ev_threshold
        cf_action = "abstain" if sub_threshold else "accuse"
        blind_cf_score = 0.0 if sub_threshold else got_score
    else:
        known_ev_accuse = None
        luck_adjusted = 0.0
        sub_threshold = False
        cf_action = "abstain"
        blind_cf_score = 0.0

    t_cutoff = accuse_env_t if accuse_env_t is not None else 10**9
    led = env.ledger()
    n_leaks = sum(1 for entry in led if entry.event == "leak" and entry.t <= t_cutoff)
    P_tier = TIERS[tier]
    canary_cost_spent = P_tier.canary_cost * n_canaries
    raw_restriction_cost = float(env._costs) - canary_cost_spent
    if raw_restriction_cost < -1e-9:
        raise ValueError(f"Negative raw restriction cost on {tier} seed {seed}: {raw_restriction_cost}")
    restriction_cost = 1.0 - true_v - P_tier.leak_damage * n_leaks - canary_cost_spent
    if abs(restriction_cost) < 1e-12:
        restriction_cost = 0.0

    return {
        "tier": tier,
        "seed": seed,
        "agent": str(ep.get("agent", "")),
        "score": got_score,
        "accused": got_accused,
        "correct": got_correct,
        "final_day": int(ep.get("final_day", verdict["final_day"])),
        "accuse_day": accuse_day,
        "true_V": true_v,
        "known_V": known_v_decision,
        "ev_threshold": ev_threshold,
        "p_solver": p_solver,
        "p_solver_round4": round(p_solver, 4) if p_solver is not None else None,
        "p_top": p_top,
        "entropy_bits": h_bits,
        "entropy_nats": h_nats,
        "known_ev_accuse": known_ev_accuse,
        "luck_adjusted": luck_adjusted,
        "sub_threshold_gamble": sub_threshold,
        "cf_action": cf_action,
        "blind_cf_score": blind_cf_score,
        "n_leaks": n_leaks,
        "n_canaries": n_canaries,
        "restriction_cost": restriction_cost,
        "flips": _detect_surfaced_flips(env),
        "accuse_step_regret": accuse_step_regret,
        "premature_tag": premature_tag,
        "steps_verified": steps_verified,
        "steps_detail_stripped": steps_detail_stripped,
        "steps_truncated_checked": steps_truncated_checked,
        "steps_client_only": steps_client_only,
    }


def load_episodes_by_seed(
    root: Path,
    rel_paths: tuple[str, ...],
    tier: str,
    allowed_seeds: set[int],
) -> dict[int, dict[str, Any]]:
    by_seed: dict[int, dict[str, Any]] = {}
    for rel in rel_paths:
        fp = root / rel
        if not fp.is_file():
            raise FileNotFoundError(f"Missing required episode cache: {rel}")
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if ep.get("tier") != tier:
                continue
            meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
            if ep.get("valid") is False or meta.get("valid") is False:
                continue
            s = int(ep["seed"])
            if s not in allowed_seeds:
                continue
            if s in by_seed:
                raise ValueError(f"Duplicate valid episode for {tier} seed {s} in {rel_paths}")
            by_seed[s] = replay_and_step_belief(ep)
    if set(by_seed.keys()) != allowed_seeds:
        missing = sorted(allowed_seeds - set(by_seed.keys()))
        raise ValueError(f"Incomplete seed set for {tier} in {rel_paths}: missing {missing}")
    return by_seed


def decompose_seed_pair(
    ag: dict[str, Any],
    sol: dict[str, Any],
    tier: str,
) -> dict[str, Any]:
    seed = int(ag["seed"])
    if seed != int(sol["seed"]):
        raise ValueError(f"Seed mismatch: {seed} vs {sol['seed']}")

    ag_sc = float(ag["score"])
    sol_sc = float(sol["score"])
    delta = sol_sc - ag_sc

    ag_acc = ag["accused"] is not None
    ag_corr = bool(ag["correct"])
    sol_corr = bool(sol["correct"])
    p_sol = ag["p_solver"]
    thr = float(ag["ev_threshold"])

    ev_abstain_rescue = 0.0
    calibrated_wrong_accuse_residual = 0.0
    missed_catch_information_gap = 0.0
    timing_and_cost_bleed_gap = 0.0
    solver_miss_frontier_catch_offset = 0.0

    leak_bleed_diff = 0.0
    canary_cost_diff = 0.0
    restriction_cost_diff = 0.0

    if ag_acc and not ag_corr:
        assert p_sol is not None
        if p_sol < thr:
            cf_ev_score = 0.0
            ev_abstain_rescue = cf_ev_score - ag_sc
            if sol_corr:
                missed_catch_information_gap = sol_sc - cf_ev_score
                regime = "rescued_wrong_accuse_solver_caught"
            elif sol_sc == 0.0:
                regime = "rescued_wrong_accuse_solver_abstained"
            else:
                solver_miss_frontier_catch_offset = sol_sc - cf_ev_score
                regime = "rescued_wrong_accuse_solver_wrong"
        else:
            cf_ev_score = ag_sc
            calibrated_wrong_accuse_residual = sol_sc - ag_sc
            regime = "calibrated_wrong_accuse"
    elif not ag_acc:
        cf_ev_score = 0.0
        if sol_corr:
            missed_catch_information_gap = sol_sc - cf_ev_score
            regime = "frontier_abstained_solver_caught"
        elif sol_sc == 0.0:
            regime = "both_abstained"
        else:
            solver_miss_frontier_catch_offset = sol_sc - cf_ev_score
            regime = "frontier_abstained_solver_wrong"
    else:
        cf_ev_score = ag_sc
        if sol_corr:
            timing_and_cost_bleed_gap = sol_sc - ag_sc
            P_tier = TIERS[tier]
            leak_bleed_diff = P_tier.leak_damage * (int(ag["n_leaks"]) - int(sol["n_leaks"]))
            canary_cost_diff = P_tier.canary_cost * (int(ag["n_canaries"]) - int(sol["n_canaries"]))
            restriction_cost_diff = float(ag["restriction_cost"]) - float(sol["restriction_cost"])
            sub_sum = leak_bleed_diff + canary_cost_diff + restriction_cost_diff
            if abs(sub_sum - timing_and_cost_bleed_gap) > IDENTITY_TOL:
                raise ValueError(
                    f"Timing/cost subcomponent residual on {tier} seed {seed}: "
                    f"{sub_sum} vs {timing_and_cost_bleed_gap}"
                )
            regime = "both_caught"
        else:
            solver_miss_frontier_catch_offset = sol_sc - ag_sc
            regime = "frontier_caught_solver_missed"

    comp_sum = (
        ev_abstain_rescue
        + calibrated_wrong_accuse_residual
        + missed_catch_information_gap
        + timing_and_cost_bleed_gap
        + solver_miss_frontier_catch_offset
    )
    residual = abs(comp_sum - delta)
    if residual > IDENTITY_TOL:
        raise ValueError(
            f"Per-seed decomposition identity failed on {tier} seed {seed}: "
            f"sum={comp_sum} vs delta={delta} (residual={residual})"
        )

    return {
        "seed": seed,
        "regime": regime,
        "agent_score": ag_sc,
        "solver_score": sol_sc,
        "counterfactual_ev_score": cf_ev_score,
        "blind_cf_score": float(ag["blind_cf_score"]),
        "delta": delta,
        "ev_abstain_rescue": ev_abstain_rescue,
        "calibrated_wrong_accuse_residual": calibrated_wrong_accuse_residual,
        "missed_catch_information_gap": missed_catch_information_gap,
        "timing_and_cost_bleed_gap": timing_and_cost_bleed_gap,
        "solver_miss_frontier_catch_offset": solver_miss_frontier_catch_offset,
        "leak_bleed_diff": leak_bleed_diff,
        "canary_cost_diff": canary_cost_diff,
        "restriction_cost_diff": restriction_cost_diff,
        "abs_residual": residual,
    }


def summarize_cohort_decomposition(
    *,
    cohort: str,
    tier: str,
    provenance: str,
    cache_paths: list[str],
    ag_by_seed: dict[int, dict[str, Any]],
    sol_by_seed: dict[int, dict[str, Any]],
    include_seed_vectors: bool,
    caveat: str | None = None,
) -> dict[str, Any]:
    seeds = sorted(ag_by_seed.keys())
    n = len(seeds)
    ag_list = [ag_by_seed[s] for s in seeds]
    sol_list = [sol_by_seed[s] for s in seeds]
    pairs = [decompose_seed_pair(ag_by_seed[s], sol_by_seed[s], tier) for s in seeds]

    ag_scores = [float(x["score"]) for x in ag_list]
    sol_scores = [float(x["score"]) for x in sol_list]
    deltas = [float(p["delta"]) for p in pairs]

    ag_mean, ag_hw = mean_ci95_normal(ag_scores)
    sol_mean, sol_hw = mean_ci95_normal(sol_scores)
    delta_mean = sol_mean - ag_mean
    delta_ci, delta_draws = boot_mean_ci(deltas)

    comp_summary: dict[str, Any] = {}
    comp_means_sum = 0.0
    comp_draws_sum = np.zeros(BOOT_B, dtype=np.float64)
    abs_comp_total = sum(abs(sum(float(p[k]) for p in pairs) / n) for k in COMPONENT_KEYS)

    for k in COMPONENT_KEYS:
        vec = [float(p[k]) for p in pairs]
        c_sum = sum(vec)
        c_mean = c_sum / n
        c_ci, c_draws = boot_mean_ci(vec)
        comp_means_sum += c_mean
        comp_draws_sum = comp_draws_sum + c_draws
        active = [int(p["seed"]) for p in pairs if abs(float(p[k])) > IDENTITY_TOL]
        entry: dict[str, Any] = {
            "mean": c_mean,
            "sum_seeds": c_sum,
            "ci95": c_ci,
            "share_of_abs_gap_terms": (abs(c_mean) / abs_comp_total) if abs_comp_total > 0.0 else 0.0,
            "active_seed_count": len(active),
        }
        if k != "timing_and_cost_bleed_gap":
            entry["active_seeds"] = active
        comp_summary[k] = entry

    mean_residual = abs(comp_means_sum - delta_mean)
    seed_max_residual = max(float(p["abs_residual"]) for p in pairs)
    boot_max_residual = float(np.max(np.abs(comp_draws_sum - delta_draws)))

    if mean_residual > IDENTITY_TOL or seed_max_residual > IDENTITY_TOL or boot_max_residual > IDENTITY_TOL:
        raise ValueError(
            f"Cohort decomposition identity failed on {cohort}/{tier}: "
            f"mean_res={mean_residual}, seed_res={seed_max_residual}, boot_res={boot_max_residual}"
        )

    leak_vec = [float(p["leak_bleed_diff"]) for p in pairs]
    can_vec = [float(p["canary_cost_diff"]) for p in pairs]
    rest_vec = [float(p["restriction_cost_diff"]) for p in pairs]
    leak_mean = sum(leak_vec) / n
    can_mean = sum(can_vec) / n
    rest_mean = sum(rest_vec) / n
    bleed_sub_res = abs((leak_mean + can_mean + rest_mean) - comp_summary["timing_and_cost_bleed_gap"]["mean"])
    if bleed_sub_res > IDENTITY_TOL:
        raise ValueError(f"Bleed subcomponent sum mismatch on {cohort}/{tier}: {bleed_sub_res}")

    blind_cf_scores = [float(p["blind_cf_score"]) for p in pairs]
    blind_gains = [b - a for b, a in zip(blind_cf_scores, ag_scores)]
    blind_rem_gaps = [s - b for s, b in zip(sol_scores, blind_cf_scores)]
    blind_gain_ci, _ = boot_mean_ci(blind_gains)
    blind_rem_ci, _ = boot_mean_ci(blind_rem_gaps)

    forfeited_lucky = sum(
        -float(x["score"]) for x in ag_list if x["correct"] and x["sub_threshold_gamble"]
    ) / n
    rescued_wrong = comp_summary["ev_abstain_rescue"]["mean"]
    if abs((rescued_wrong + forfeited_lucky) - (sum(blind_gains) / n)) > IDENTITY_TOL:
        raise ValueError(f"Blind EV counterfactual gain identity failed on {cohort}/{tier}")

    accused_eps = [x for x in ag_list if x["accused"] is not None]
    wrong_eps = [x for x in accused_eps if not x["correct"]]
    sub_gambles = [x for x in accused_eps if x["sub_threshold_gamble"]]
    sub_wrong = [x for x in sub_gambles if not x["correct"]]
    sub_lucky = [x for x in sub_gambles if x["correct"]]
    cal_wrong = [x for x in wrong_eps if not x["sub_threshold_gamble"]]

    ag_la = sum(float(x["luck_adjusted"]) for x in ag_list) / n
    sol_la = sum(float(x["luck_adjusted"]) for x in sol_list) / n

    out: dict[str, Any] = {
        "cohort": cohort,
        "agent": ag_list[0]["agent"],
        "tier": tier,
        "provenance": provenance,
        "cache_paths": cache_paths,
        "n": n,
        "seeds": [seeds[0], seeds[-1]],
        "replay_audit": {
            "episodes_verified": n,
            "steps_verified": sum(int(x["steps_verified"]) for x in ag_list),
            "steps_detail_stripped": sum(int(x["steps_detail_stripped"]) for x in ag_list),
            "steps_truncated_checked": sum(int(x["steps_truncated_checked"]) for x in ag_list),
            "steps_client_only": sum(int(x["steps_client_only"]) for x in ag_list),
        },
        "scores_and_posteriors": {
            "agent_mean": ag_mean,
            "agent_score_ci95_halfwidth": ag_hw,
            "solver_mean": sol_mean,
            "solver_score_ci95_halfwidth": sol_hw,
            "total_gap_delta": delta_mean,
            "total_gap_sum_seeds": sum(deltas),
            "total_gap_ci95": delta_ci,
            "agent_luck_adjusted": ag_la,
            "solver_luck_adjusted": sol_la,
            "luck_adjusted_gap": sol_la - ag_la,
            "realized_luck_agent": ag_mean - ag_la,
            "accuracy": sum(1 for x in ag_list if x["correct"]) / n,
            "accused_count": len(accused_eps),
            "wrong_count": len(wrong_eps),
            "abstain_count": n - len(accused_eps),
            "sub_threshold_gamble_count": len(sub_gambles),
            "sub_threshold_wrong_count": len(sub_wrong),
            "sub_threshold_lucky_catch_count": len(sub_lucky),
            "calibrated_wrong_count": len(cal_wrong),
            "mean_p_solver_at_accuse": (
                sum(float(x["p_solver"]) for x in accused_eps) / len(accused_eps)
                if accused_eps
                else None
            ),
            "mean_ev_threshold_at_accuse": (
                sum(float(x["ev_threshold"]) for x in accused_eps) / len(accused_eps)
                if accused_eps
                else None
            ),
            "mean_entropy_bits_at_decision": sum(float(x["entropy_bits"]) for x in ag_list) / n,
            "mean_entropy_nats_at_decision": sum(float(x["entropy_nats"]) for x in ag_list) / n,
        },
        "components": comp_summary,
        "identity_check": {
            "sum_of_component_means": comp_means_sum,
            "solver_minus_agent_mean": delta_mean,
            "mean_abs_residual": mean_residual,
            "per_seed_max_abs_residual": seed_max_residual,
            "bootstrap_max_abs_residual": boot_max_residual,
            "within_1e_12": True,
        },
        "timing_and_cost_subcomponents": {
            "joint_catch_count": sum(1 for p in pairs if p["regime"] == "both_caught"),
            "leak_bleed_diff_mean": leak_mean,
            "canary_cost_diff_mean": can_mean,
            "restriction_cost_diff_mean": rest_mean,
            "subcomponent_abs_residual": bleed_sub_res,
        },
        "blind_ev_stopping_counterfactual": {
            "rule": "accuse iff p_solver(accused | agent_history) >= 1 / (1 + known_V), else abstain 0.0",
            "blind_cf_mean": sum(blind_cf_scores) / n,
            "blind_cf_gain_over_agent": sum(blind_gains) / n,
            "blind_cf_gain_ci95": blind_gain_ci,
            "rescued_wrong_gain": rescued_wrong,
            "forfeited_lucky_catch_loss": forfeited_lucky,
            "remaining_gap_to_solver": sum(blind_rem_gaps) / n,
            "remaining_gap_ci95": blind_rem_ci,
        },
    }
    if caveat:
        out["caveat"] = caveat
    if include_seed_vectors:
        out["seed_vectors"] = {
            "delta": [round(float(p["delta"]), 4) for p in pairs],
            "p_solver": [round(float(x["p_solver"]), 4) if x["p_solver"] is not None else None for x in ag_list],
            "ev_threshold": [round(float(x["ev_threshold"]), 4) for x in ag_list],
            "entropy_bits": [round(float(x["entropy_bits"]), 4) for x in ag_list],
            "regime_code": [REGIME_SHORT_CODES[str(p["regime"])] for p in pairs],
        }
    return out


def build_hard_seed_forensics(
    frontier_raw: dict[tuple[str, str], dict[int, dict[str, Any]]],
    solver_raw: dict[str, dict[int, dict[str, Any]]],
) -> dict[str, Any]:
    focus_seeds = (6, 18, 26)
    sol_hard = solver_raw["hard"]
    rows: list[dict[str, Any]] = []
    candidate_cohorts = (
        "opencode-gemini-4-carbon",
        "inproc-gemini-4-carbon",
        "opencode-gemini-3.5-flash",
        "opencode-gpt-5.5",
    )
    for cohort_name in candidate_cohorts:
        if (cohort_name, "hard") not in frontier_raw:
            continue
        ag_map = frontier_raw[(cohort_name, "hard")]
        for s in focus_seeds:
            ag = ag_map[s]
            sol = sol_hard[s]
            pair = decompose_seed_pair(ag, sol, "hard")
            rows.append(
                {
                    "cohort": cohort_name,
                    "seed": s,
                    "accused": ag["accused"],
                    "correct": ag["correct"],
                    "accuse_day": ag["accuse_day"],
                    "agent_score": ag["score"],
                    "solver_score": sol["score"],
                    "known_V": ag["known_V"],
                    "ev_threshold": ag["ev_threshold"],
                    "p_solver": ag["p_solver"],
                    "p_top": ag["p_top"],
                    "entropy_bits": ag["entropy_bits"],
                    "cf_action": ag["cf_action"],
                    "surfaced_flips": ag["flips"],
                    "regime": pair["regime"],
                    "delta": pair["delta"],
                    "ev_abstain_rescue": pair["ev_abstain_rescue"],
                    "calibrated_wrong_accuse_residual": pair["calibrated_wrong_accuse_residual"],
                    "missed_catch_information_gap": pair["missed_catch_information_gap"],
                    "timing_and_cost_bleed_gap": pair["timing_and_cost_bleed_gap"],
                }
            )
    return {
        "highlight_note": (
            "Hard seed 6 vs seed 26 vs seed 18 contrast: on seed 6 opencode-gemini-4-carbon isolates e34 cleanly "
            "(+0.730, p_solver=0.9981 >= threshold 0.5780, H=0.0214 bits) and opencode-gpt-5.5 catches e34 on d6 "
            "(+0.750, p_solver=0.9572, H=0.322 bits), while inproc-gemini-4-carbon hits a 5% c4-2 variant flip and "
            "accuses e18 below break-even (p_solver=0.6295 < 0.6452, rescued -1.0 -> 0.0). On seed 26 "
            "opencode-gemini-4-carbon accuses e04 on a 5% c6-2 S1!=S3 readout flip where strict set elimination "
            "collapses to a singleton and Bayesian p_solver=0.9504 >= threshold 0.5988 (landing in "
            "calibrated_wrong_accuse_residual +1.690 V), whereas inproc-gemini-4-carbon sees a c4 flip leaving "
            "p_top=0.3793 < 0.6849 and rationally abstains (0.0 vs solver +0.690), opencode-gemini-3.5-flash accuses "
            "e38 at p_solver=0.1000 < 0.7874 (rescued +1.000 V by ev_abstain_rescue), and opencode-gpt-5.5 catches e08 "
            "on d10 (+0.620, p_solver=0.9817, H=0.150 bits). On seed 18 opencode-gemini-4-carbon accuses e29 across 4 "
            "unresolved suspects at p_solver=0.6272 < threshold 0.6623 (rescued +1.000 V by ev_abstain_rescue), "
            "whereas opencode-gpt-5.5 absorbs a 5% c8-2 C!=B flip on d12, plants further canaries to p_solver=1.0000 "
            "(H=0.000 bits), and catches e27 on d14 (+0.480)."
        ),
        "records": rows,
    }


def verify_regret_crosschecks(
    root: Path,
    frontier_raw: dict[tuple[str, str], dict[int, dict[str, Any]]],
) -> dict[str, Any]:
    targets = (
        ("opencode-gemini-4-carbon", "results/regret_opencode-gemini-4-carbon-v1.4.json"),
        ("inproc-gemini-4-carbon", "results/regret_inproc-gemini-4-carbon-v1.4.json"),
    )
    results_out: dict[str, Any] = {}
    for cohort_name, rel_path in targets:
        fp = root / rel_path
        if not fp.is_file():
            raise FileNotFoundError(f"Missing required regret artifact for cross-check: {rel_path}")
        reg_doc = json.loads(fp.read_text(encoding="utf-8"))
        agent_block = reg_doc["agent"]
        tier_checks: dict[str, Any] = {}
        for tier in ("hard", "medium"):
            ref = agent_block[tier]
            eps = [frontier_raw[(cohort_name, tier)][s] for s in PRIMARY_SEEDS]
            n = len(eps)
            mean_sc = sum(float(x["score"]) for x in eps) / n
            acc = sum(1 for x in eps if x["correct"]) / n
            p_r4 = [float(x["p_solver_round4"]) for x in eps if x["p_solver_round4"] is not None]
            mean_p_r4 = statistics.mean(p_r4)
            prem_cnt = sum(1 for x in eps if x["premature_tag"])
            prem_loss = round(sum(float(x["accuse_step_regret"]) for x in eps if x["premature_tag"]), 4)
            no_acc_cnt = sum(1 for x in eps if x["accused"] is None)

            if n != int(ref["n"]):
                raise ValueError(f"{rel_path} {tier} n mismatch: {n} vs {ref['n']}")
            if abs(mean_sc - float(ref["mean_score"])) > FLOAT_TOL:
                raise ValueError(f"{rel_path} {tier} mean_score mismatch: {mean_sc} vs {ref['mean_score']}")
            if abs(acc - float(ref["accuracy"])) > FLOAT_TOL:
                raise ValueError(f"{rel_path} {tier} accuracy mismatch: {acc} vs {ref['accuracy']}")
            if abs(mean_p_r4 - float(ref["mean_p_correct_at_accusation"])) > FLOAT_TOL:
                raise ValueError(
                    f"{rel_path} {tier} mean_p_correct_at_accusation mismatch: "
                    f"{mean_p_r4} vs {ref['mean_p_correct_at_accusation']}"
                )
            if prem_cnt != int(ref["tags"]["premature_accusation"]["count"]):
                raise ValueError(f"{rel_path} {tier} premature_accusation count mismatch")
            if abs(prem_loss - float(ref["tags"]["premature_accusation"]["value_lost"])) > 1e-4:
                raise ValueError(f"{rel_path} {tier} premature_accusation value_lost mismatch")
            if no_acc_cnt != int(ref["tags"]["no_accusation"]["count"]):
                raise ValueError(f"{rel_path} {tier} no_accusation count mismatch")

            top5_accuse_verified = 0
            for item in ref.get("top5") or []:
                if item.get("action") == "accuse":
                    s_id = int(item["seed"])
                    got_reg = round(float(frontier_raw[(cohort_name, tier)][s_id]["accuse_step_regret"]), 6)
                    if abs(got_reg - float(item["regret"])) > 2e-6:
                        raise ValueError(
                            f"{rel_path} {tier} top5 accuse regret mismatch on seed {s_id}: "
                            f"{got_reg} vs {item['regret']}"
                        )
                    top5_accuse_verified += 1

            tier_checks[tier] = {
                "n": n,
                "mean_score": mean_sc,
                "mean_total_regret_committed": float(ref["mean_total_regret"]),
                "mean_p_correct_at_accusation": mean_p_r4,
                "premature_accusation_count": prem_cnt,
                "premature_accusation_value_lost": prem_loss,
                "no_accusation_count": no_acc_cnt,
                "top5_accuse_entries_verified": top5_accuse_verified,
                "all_matched": True,
            }
        results_out[cohort_name] = {
            "artifact": rel_path,
            "tiers": tier_checks,
        }
    return results_out


def verify_panel_fix_a_and_headline(
    root: Path,
    cohort_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    gap_path = root / "docs/reports/gap.md"
    hgt_path = root / "results/eval_v14/headline_gap_table_v14.json"
    if not gap_path.is_file():
        raise FileNotFoundError("Missing docs/reports/gap.md")
    if not hgt_path.is_file():
        raise FileNotFoundError("Missing results/eval_v14/headline_gap_table_v14.json")

    gap_txt = norm_ascii(gap_path.read_text(encoding="utf-8"))
    required_snippets = (
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "111% [99%, 127%]",
        "101% [85%, 119%]",
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "93% [20%, 371%]",
        "116% [78%, 363%]",
        "131% [86%, 590%]",
        "671ed96",
        "post-hoc lock",
        "f9fb7a4a",
        "Pre-registered second frontier family: gpt-5.5",
    )
    for snip in required_snippets:
        if snip not in gap_txt:
            raise ValueError(f"docs/reports/gap.md missing required Panel Fix A / headline token: {snip!r}")

    hgt = json.loads(hgt_path.read_text(encoding="utf-8"))
    sec_a = hgt.get("section_a") or []
    by_key = {
        (str(r["agent"]), str(r["tier"]), str(r["kind"])): r
        for r in sec_a
        if isinstance(r, dict)
    }

    oc_hard = next(
        c for c in cohort_summaries if c["cohort"] == "opencode-gemini-4-carbon" and c["tier"] == "hard"
    )
    hgt_oc_hard = by_key[("opencode:google/gemini-4-carbon", "hard", "frontier")]
    if abs(oc_hard["scores_and_posteriors"]["agent_mean"] - float(hgt_oc_hard["mean"])) > FLOAT_TOL:
        raise ValueError("Headline OpenCode hard mean mismatch vs headline_gap_table_v14.json")
    if abs(oc_hard["scores_and_posteriors"]["solver_mean"] - float(hgt_oc_hard["solver_same_seeds"])) > FLOAT_TOL:
        raise ValueError("Headline solver hard mean mismatch vs headline_gap_table_v14.json")
    if abs(oc_hard["scores_and_posteriors"]["total_gap_delta"] - (-float(hgt_oc_hard["paired_diff"]))) > FLOAT_TOL:
        raise ValueError("Headline paired_diff mismatch vs headline_gap_table_v14.json")

    gpt55_hard = next(
        (c for c in cohort_summaries if c["cohort"] == "opencode-gpt-5.5" and c["tier"] == "hard"),
        None,
    )
    if gpt55_hard is not None and ("opencode:openai/gpt-5.5", "hard", "frontier") in by_key:
        hgt_gpt_hard = by_key[("opencode:openai/gpt-5.5", "hard", "frontier")]
        if abs(gpt55_hard["scores_and_posteriors"]["agent_mean"] - float(hgt_gpt_hard["mean"])) > FLOAT_TOL:
            raise ValueError("Headline gpt-5.5 hard mean mismatch vs headline_gap_table_v14.json")
        if abs(gpt55_hard["scores_and_posteriors"]["total_gap_delta"] - (-float(hgt_gpt_hard["paired_diff"]))) > FLOAT_TOL:
            raise ValueError("Headline gpt-5.5 paired_diff mismatch vs headline_gap_table_v14.json")

    return {
        "authoritative_headline_doc": "docs/reports/gap.md",
        "primary_hard_raw_ratio_headline": "65% [24%, 98%]",
        "primary_hard_luck_adjusted_ratio_headline": "72% [52%, 91%]",
        "primary_medium_raw_ratio": "111% [99%, 127%]",
        "primary_medium_luck_adjusted_ratio": "101% [85%, 119%]",
        "opencode_gpt55_hard_raw_ratio": "101% [79%, 140%]",
        "opencode_gpt55_hard_luck_adjusted_ratio": "84% [67%, 103%]",
        "harbor_rehearsal_3run_ratios": [
            "93% [20%, 371%]",
            "116% [78%, 363%]",
            "131% [86%, 590%]",
        ],
        "seed_lock_commit": "671ed96",
        "seed_lock_framing": PRIMARY_SEED_LOCK_NOTE,
        "preregistered_extensions": {
            "g1_hard_30_59": "f9fb7a4a",
            "causal_hint_gather": "fd8c1cb0",
            "opencode_gpt55_hard_0_29": "cf394894",
        },
        "headline_gap_table_crosschecked": True,
    }


def probe_optional_frontier_cohorts(
    root: Path,
    solver_raw: dict[str, dict[int, dict[str, Any]]],
    seed_set: set[int],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[tuple[str, str], dict[int, dict[str, Any]]],
]:
    probe_records: list[dict[str, Any]] = []
    extra_summaries: list[dict[str, Any]] = []
    extra_raw: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    v14_root = root / "data/runs/committed/v1.4"
    for dir_name in OPTIONAL_FRONTIER_DIRS:
        cohort_dir = v14_root / dir_name
        present_tiers: list[str] = []
        if cohort_dir.is_dir():
            for tier in ("hard", "medium"):
                ep_file = cohort_dir / tier / "episodes.jsonl"
                if ep_file.is_file():
                    lines = [
                        json.loads(ln)
                        for ln in ep_file.read_text(encoding="utf-8").splitlines()
                        if ln.strip()
                    ]
                    valid_seeds = {
                        int(r["seed"])
                        for r in lines
                        if r.get("tier") == tier
                        and r.get("valid") is not False
                        and (r.get("meta") or {}).get("valid") is not False
                        and int(r["seed"]) in seed_set
                    }
                    if valid_seeds == seed_set:
                        rel_p = f"data/runs/committed/v1.4/{dir_name}/{tier}/episodes.jsonl"
                        ag_map = load_episodes_by_seed(root, (rel_p,), tier, seed_set)
                        extra_raw[(dir_name, tier)] = ag_map
                        prov = (
                            "committed_preregistered_second_family_v1.4"
                            if dir_name == "opencode-gpt-5.5"
                            else "committed_optional_v1.4"
                        )
                        extra_summaries.append(
                            summarize_cohort_decomposition(
                                cohort=dir_name,
                                tier=tier,
                                provenance=prov,
                                cache_paths=[rel_p],
                                ag_by_seed=ag_map,
                                sol_by_seed=solver_raw[tier],
                                include_seed_vectors=True,
                            )
                        )
                        present_tiers.append(tier)
        probe_records.append(
            {
                "cohort": dir_name,
                "present_complete_0_29_tiers": present_tiers,
            }
        )
    return (probe_records, extra_summaries, extra_raw)


def compute_baseline_decompositions(
    solver_raw: dict[str, dict[int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for agent_name in BASELINE_REFERENCE_AGENTS:
        factory = make_policy_factory(agent_name)
        for tier in ("hard", "medium"):
            ag_map: dict[int, dict[str, Any]] = {}
            for s in PRIMARY_SEEDS:
                res = run_episode(Env(tier, s), factory(s))
                ag_map[s] = replay_and_step_belief(asdict(res))
            out.append(
                summarize_cohort_decomposition(
                    cohort=agent_name,
                    tier=tier,
                    provenance="inproc_deterministic_baseline_v1.4",
                    cache_paths=[f"in-process Env({tier}, seeds=0..29)"],
                    ag_by_seed=ag_map,
                    sol_by_seed=solver_raw[tier],
                    include_seed_vectors=False,
                )
            )
    return out


def compute_all(root: Path = ROOT) -> dict[str, Any]:
    seed_set = set(PRIMARY_SEEDS)
    solver_raw: dict[str, dict[int, dict[str, Any]]] = {
        tier: load_episodes_by_seed(root, SOLVER_REF_PATHS[tier], tier, seed_set)
        for tier in ("hard", "medium")
    }

    frontier_raw: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}
    frontier_summaries: list[dict[str, Any]] = []
    for spec in PRIMARY_FRONTIER_SPECS:
        c_name = str(spec["cohort"])
        tier = str(spec["tier"])
        paths = tuple(spec["paths"])
        ag_map = load_episodes_by_seed(root, paths, tier, seed_set)
        frontier_raw[(c_name, tier)] = ag_map
        frontier_summaries.append(
            summarize_cohort_decomposition(
                cohort=c_name,
                tier=tier,
                provenance=str(spec["provenance"]),
                cache_paths=list(paths),
                ag_by_seed=ag_map,
                sol_by_seed=solver_raw[tier],
                include_seed_vectors=True,
                caveat=spec.get("caveat"),
            )
        )

    probes, extra_frontier, extra_raw = probe_optional_frontier_cohorts(root, solver_raw, seed_set)
    frontier_raw.update(extra_raw)
    all_frontier = frontier_summaries + extra_frontier
    baseline_summaries = compute_baseline_decompositions(solver_raw)
    forensics = build_hard_seed_forensics(frontier_raw, solver_raw)
    regret_checks = verify_regret_crosschecks(root, frontier_raw)
    headline_check = verify_panel_fix_a_and_headline(root, all_frontier)

    total_frontier_eps = sum(int(c["n"]) for c in all_frontier)
    total_frontier_steps = sum(int(c["replay_audit"]["steps_verified"]) for c in all_frontier)
    total_solver_steps = sum(
        int(x["steps_verified"]) for t_map in solver_raw.values() for x in t_map.values()
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "primary_seeds": "0-29",
        "n_seeds_per_cohort": N_SEEDS,
        "primary_seed_lock_note": PRIMARY_SEED_LOCK_NOTE,
        "bootstrap": {
            "resamples": BOOT_B,
            "seed": BOOT_SEED,
            "method": "paired_seed_multinomial_percentile_95",
        },
        "counterfactual_rule": {
            "belief_engine": "canary.solver.policy.SolverPolicy exact Bayesian posterior on recorded agent steps",
            "step_error_detail_compat": "1bc3e281",
            "stopping_rule": "accuse iff p_solver(accused | agent_history) >= 1 / (1 + known_V), else abstain 0.0",
            "identity": (
                "solver_score - agent_score == ev_abstain_rescue + calibrated_wrong_accuse_residual "
                "+ missed_catch_information_gap + timing_and_cost_bleed_gap + solver_miss_frontier_catch_offset"
            ),
            "identity_tolerance": IDENTITY_TOL,
            "regime_code_legend": {v: k for k, v in REGIME_SHORT_CODES.items()},
        },
        "verification_totals": {
            "frontier_cohorts_count": len(all_frontier),
            "baseline_cohorts_count": len(baseline_summaries),
            "frontier_episodes_replayed": total_frontier_eps,
            "solver_reference_episodes_replayed": sum(len(v) for v in solver_raw.values()),
            "frontier_steps_verified": total_frontier_steps,
            "solver_steps_verified": total_solver_steps,
            "all_identities_within_1e_12": True,
        },
        "panel_fix_a_and_headline": headline_check,
        "frontier_cohorts": all_frontier,
        "baseline_reference_cohorts": baseline_summaries,
        "hard_seed_forensics": forensics,
        "regret_crosschecks": regret_checks,
        "optional_frontier_cohort_probes": probes,
    }


def _fmt_signed(val: float, digits: int = 3) -> str:
    return f"{val:+.{digits}f}"


def _fmt_ci(ci: list[float], digits: int = 3) -> str:
    return f"[{ci[0]:+.{digits}f}, {ci[1]:+.{digits}f}]"


def render_markdown_report(data: dict[str, Any]) -> str:
    lines: list[str] = []
    n_cohorts = len(data["frontier_cohorts"])
    oc_hard = next(
        c for c in data["frontier_cohorts"] if c["cohort"] == "opencode-gemini-4-carbon" and c["tier"] == "hard"
    )
    oc_tc = oc_hard["timing_and_cost_subcomponents"]

    lines.append(f"{H1}Canary v1.4 Counterfactual Gap Decomposition (Paired Seeds 0-29)")
    lines.append("")
    lines.append(
        "**Authoritative headline, cross-family & rehearsal framing (Panel Fix A).** In the MCP-only dev setup "
        "(OpenCode + `gemini-4-carbon` over MCP, rules `v1.4`, paired dev seeds `0-29`, `n = 30` per tier), "
        "the primary Hard row in `docs/reports/gap.md` is **`65% [24%, 98%]`** raw "
        "(`+0.322 +/- 0.199` vs reference solver `+0.499 +/- 0.119`, paired gap `Delta = +0.177 V/ep` = `+5.30 V` "
        "over 30 seeds) and **`72% [52%, 91%]`** luck-adjusted (`+0.360` vs `+0.499`), with Medium at "
        "`111% [99%, 127%]` raw and `101% [85%, 119%]` luck-adjusted. Primary seeds `0-29` are a **post-hoc lock** "
        "(`671ed96`, committed 28 s after `8fd4dec` against later reruns and cherry-picking, not a pre-registration); "
        "true pre-registrations committed before any episode are the G1 Hard `30-59` extension (`f9fb7a4a`), "
        "the OpenCode `--hint gather` test (`fd8c1cb0`), and OpenCode 1.19.5 `gpt-5.5` Hard `0-29` (`cf394894`). "
        "On the pre-registered `gpt-5.5` run (`ca0a0dc0`, `n = 30`, `0` infra failures), `gpt-5.5` matches the solver "
        "at **`101% [79%, 140%]`** raw (`+0.504 +/- 0.064`, `84% [67%, 103%]` luck-adjusted, `28/28` accusations correct, "
        "`2` prose-only non-accusations on seeds `0, 17`), and in the 3-run Harbor 0.26.0 rehearsal on 10 hard judge tasks "
        "(`aa1c679e`, where the agent also has a shell used in `20/28` trials), `gemini-4-carbon` scored "
        "`93% [20%, 371%]`, `116% [78%, 363%]`, and `131% [86%, 590%]` (`9` valid trials, `+0.626`, `28/29` correct across "
        "three runs -- the gap did not reproduce in the judge path)."
    )
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/counterfactual_decomposition_v14.py")
    lines.append("python scripts/counterfactual_decomposition_v14.py --check")
    lines.append("python scripts/run_all_eval_checks.py --check --only counterfactual_decomposition_v14")
    lines.append("```")
    lines.append("")
    lines.append(f"{H2}1. Exact Counterfactual Decomposition Identity & Method")
    lines.append("")
    lines.append(
        "Every episode in each `v1.4` cohort is replayed step-by-step in `canary.env.Env(tier, seed)` "
        "(enforcing `1bc3e281` `data.detail` step-output compatibility and byte-length verification on client-truncated "
        "logs) while stepping `SolverPolicy`'s exact Bayesian belief updater along the agent's own recorded `steps` "
        "to evaluate `p_solver(accused | agent_history)`, Shannon entropy `H(agent_history)`, and the public EV "
        "stopping threshold `tau = 1 / (1 + known_V)` (`accuse` iff `p_solver >= tau`, else abstain `0.0`)."
    )
    lines.append("")
    lines.append(
        "For every paired seed `i in 0..29`, `Delta_i = solver_score_i - agent_score_i` partitions with zero residual "
        "(`|sum - Delta| <= 1e-12` on every seed, cohort mean, and all `10,000` paired bootstrap draws at `seed = 42`):"
    )
    lines.append("")
    lines.append(
        "- **`ev_abstain_rescue` (`a`):** Gain (`-1.0 -> 0.0`, `+1.0 V` on that seed) when the agent made a wrong "
        "accusation despite `p_solver(accused | agent_history) < 1 / (1 + known_V)` (negative-EV gamble vetoed)."
    )
    lines.append(
        "- **`calibrated_wrong_accuse_residual` (`b`):** `solver_score - agent_score` on wrong accusations where even "
        "`p_solver(accused | agent_history) >= 1 / (1 + known_V)` (including 5% canary readout flip traps on Hard)."
    )
    lines.append(
        "- **`missed_catch_information_gap` (`c`):** `solver_score - counterfactual_ev_score` (`solver_score - 0.0`) "
        "on seeds where the frontier agent abstained or was rescued to `0.0` while `SolverPolicy` caught the culprit "
        "via higher-rate posterior-balanced canary partitions."
    )
    lines.append(
        "- **`timing_and_cost_bleed_gap` (`d`):** `solver_score - agent_score` on seeds where both agents caught the "
        "culprit, sub-decomposed exactly into `leak_bleed_diff + canary_cost_diff + restriction_cost_diff`."
    )
    lines.append(
        "- **`solver_miss_frontier_catch_offset` (`e`):** `solver_score - agent_score <= 0` on seeds where the frontier "
        "agent caught the culprit while `SolverPolicy` abstained (Medium seeds `20, 21, 29`) or suffered a 5% flip "
        "(Hard seed `15`; `0.000` on `opencode-gemini-4-carbon` Hard)."
    )
    lines.append("")
    lines.append(
        f"{H2}2. {n_cohorts}-Cohort Paired Gap Decomposition (`n = 30` Seeds `0-29`, 10,000 Paired Bootstrap CIs, `seed = 42`)"
    )
    lines.append("")
    lines.append(
        "| Cohort | Tier | Agent | Solver | `Delta (S - A)` `[95% CI]` | `(a)` EV Rescue `[95% CI]` | `(b)` Cal. Wrong `[95% CI]` | `(c)` Info Gap `[95% CI]` | `(d)` Bleed/Cost `[95% CI]` | `(e)` Solver-Miss Offset |"
    )
    lines.append("|---|---|---:|---:|---|---|---|---|---|---:|")
    for c in data["frontier_cohorts"]:
        sp = c["scores_and_posteriors"]
        cm = c["components"]
        tag = " *(rep)*" if "replication" in c["provenance"] else (" *(pre-reg)*" if "preregistered" in c["provenance"] else "")
        lines.append(
            f"| `{c['cohort']}`{tag} | `{c['tier']}` | `{_fmt_signed(sp['agent_mean'])}` | `{_fmt_signed(sp['solver_mean'])}` "
            f"| `{_fmt_signed(sp['total_gap_delta'])} {_fmt_ci(sp['total_gap_ci95'])}` "
            f"| `{_fmt_signed(cm['ev_abstain_rescue']['mean'])} {_fmt_ci(cm['ev_abstain_rescue']['ci95'])}` "
            f"| `{_fmt_signed(cm['calibrated_wrong_accuse_residual']['mean'])} {_fmt_ci(cm['calibrated_wrong_accuse_residual']['ci95'])}` "
            f"| `{_fmt_signed(cm['missed_catch_information_gap']['mean'])} {_fmt_ci(cm['missed_catch_information_gap']['ci95'])}` "
            f"| `{_fmt_signed(cm['timing_and_cost_bleed_gap']['mean'])} {_fmt_ci(cm['timing_and_cost_bleed_gap']['ci95'])}` "
            f"| `{_fmt_signed(cm['solver_miss_frontier_catch_offset']['mean'])}` |"
        )
    lines.append("")
    lines.append(
        "*Note:* `opencode-gemini-3.5-flash` Medium (`*(rep)*`) is the 3-shard FR8 replication (`d4bc4f3d`, seed 28 rerun); "
        "`opencode-gpt-5.5` Hard (`*(pre-reg)*`) is the pre-registered OpenCode 1.19.5 second-family cohort (`cf394894` / `ca0a0dc0`). "
        "Optional probe directories `inproc-grok-4.20-beta`, `opencode-grok-4.20-beta`, `opencode-gemini-4-argon`, and "
        "`opencode-gemini-4-hydrogen` have no committed `0-29` `v1.4` directory; deterministic `grok_tactics` on `0-29` is "
        "decomposed in Section 4 below."
    )
    lines.append("")
    lines.append(f"{H2}3. Posterior Calibration, Entropy, Bleed Sub-Accounting & Blind EV-Gate Counterfactual")
    lines.append("")
    lines.append(
        "| Cohort (`tier`) | Acc / Wrong / Abst | Sub-`tau` Gambles (W / Lucky) | Mean `p_solver` vs `tau` | Mean `H` (bits) | Joint-Catch Leak / Canary / Restrict Diff | Blind EV-Gate Mean (`Gain [95% CI]`) |"
    )
    lines.append("|---|---|---|---|---:|---|---|")
    for c in data["frontier_cohorts"]:
        sp = c["scores_and_posteriors"]
        tc = c["timing_and_cost_subcomponents"]
        bl = c["blind_ev_stopping_counterfactual"]
        lines.append(
            f"| `{c['cohort']}` (`{c['tier']}`) "
            f"| `{sp['accused_count']} / {sp['wrong_count']} / {sp['abstain_count']}` "
            f"| `{sp['sub_threshold_gamble_count']}` (`{sp['sub_threshold_wrong_count']}W / {sp['sub_threshold_lucky_catch_count']}L`) "
            f"| `{sp['mean_p_solver_at_accuse']:.3f}` vs `{sp['mean_ev_threshold_at_accuse']:.3f}` "
            f"| `{sp['mean_entropy_bits_at_decision']:.3f}` "
            f"| `{_fmt_signed(tc['leak_bleed_diff_mean'])} / {_fmt_signed(tc['canary_cost_diff_mean'])} / {_fmt_signed(tc['restriction_cost_diff_mean'])}` "
            f"| `{_fmt_signed(bl['blind_cf_mean'])}` (`{_fmt_signed(bl['blind_cf_gain_over_agent'])} {_fmt_ci(bl['blind_cf_gain_ci95'])}`) |"
        )
    lines.append("")
    lines.append(
        "**Key mechanistic findings on Hard (`0-29`):**"
    )
    lines.append(
        "1. **Why OpenCode `gemini-4-carbon`'s `+0.177 V/ep` (`+5.30 V`) Hard gap is dominated by evidence quality, not bleed:** "
        f"On the `{oc_tc['joint_catch_count']}` jointly-caught Hard seeds, later accusation leak bleed "
        f"(`{_fmt_signed(oc_tc['leak_bleed_diff_mean'])} V/ep` = `{_fmt_signed(oc_tc['leak_bleed_diff_mean'] * 30, 2)} V`) "
        "is more than offset by unplanted canary cost savings "
        f"(`{_fmt_signed(oc_tc['canary_cost_diff_mean'])} V/ep` = `{_fmt_signed(oc_tc['canary_cost_diff_mean'] * 30, 2)} V`, "
        f"plus `{_fmt_signed(oc_tc['restriction_cost_diff_mean'])} V/ep` = `{_fmt_signed(oc_tc['restriction_cost_diff_mean'] * 30, 2)} V` "
        "restriction cost), yielding `timing_and_cost_bleed_gap = -0.007 V/ep` (`-0.22 V`). Instead, `100%` of the positive gap "
        "comes from commitment under thin/noisy evidence: `calibrated_wrong_accuse_residual = +0.113 V/ep` (`+3.38 V` on seeds "
        "`1, 26`, with seed `15` tying solver `-1.00 vs -1.00`), `missed_catch_information_gap = +0.038 V/ep` (`+1.14 V`, "
        "seed `11` abstained `+0.62 V` + seed `18` `+0.52 V`), and `ev_abstain_rescue = +0.033 V/ep` (`+1.00 V` on seed `18`)."
    )
    lines.append(
        "2. **Blind EV-stopping (`accuse` iff `p_solver >= 1 / (1 + known_V)`) raises raw score on all three Gemini Hard cohorts "
        "and leaves `gpt-5.5` invariant:** Even after forfeiting lucky sub-threshold catches (`-0.013 V/ep` on `opencode-carbon` "
        "seeds `5, 23`; `-0.085 V/ep` across `7` lucky gambles on `opencode-3.5-flash`), enforcing the Bayesian EV threshold raises "
        "`opencode-carbon` `+0.322 -> +0.343`, `inproc-carbon` `+0.473 -> +0.486`, and `opencode-3.5-flash` `+0.373 -> +0.388` "
        "(`+0.434 -> +0.580`, `+0.146 V/ep` gain on Medium), while `opencode-gpt-5.5` is unchanged (`+0.504 -> +0.504`, `0` "
        "sub-threshold gambles across all `28` accusations)."
    )
    lines.append(
        "3. **Cross-family contrast (`gemini-4-carbon` `65%` vs `gpt-5.5` `101%` on identical MCP tools):** `opencode-gpt-5.5` "
        "records `ev_abstain_rescue = 0.000` and `calibrated_wrong_accuse_residual = 0.000` (`28/28` correct, mean "
        "`p_solver = 0.940`, mean `H = 0.327` bits vs `opencode-carbon`'s `0.647` bits); its `+0.047 V/ep` (`+1.41 V`) "
        "`missed_catch_information_gap` arises solely on seeds `0` (`p_top = 0.9487`) and `17` (`p_top = 0.9634`) where it named "
        "the culprit in prose without calling `accuse`, balanced by `-0.052 V/ep` (`-1.57 V`) `solver_miss_frontier_catch_offset` "
        "on seed `15` (`+0.57` vs solver `-1.00`) and `+0.001 V/ep` net bleed/cost (`-0.023` faster leak containment vs `+0.024` "
        "higher canary spend)."
    )
    lines.append("")
    lines.append(f"{H3}3.1 Hard Seed Forensics: Seed 6 vs Seed 26 (5% S1 Flip) vs Seed 18")
    lines.append("")
    lines.append(
        "| Cohort | Seed | Decision (Day) | Score vs Solver | `p_solver` vs `tau` (`known_V`) | `H` (bits) | Surfaced 5% Flip | Decomposition Regime | Active Term(s) |"
    )
    lines.append("|---|---:|---|---|---|---:|---|---|---|")
    for r in data["hard_seed_forensics"]["records"]:
        if r["seed"] not in (6, 18, 26):
            continue
        dec = f"accuse `{r['accused']}` (d{r['accuse_day']})" if r["accused"] else "abstain (d21)"
        p_txt = f"`{r['p_solver']:.4f}`" if r["p_solver"] is not None else f"`None` (`p_top={r['p_top']:.4f}`)"
        fl_txt = (
            ", ".join(f"`{f['doc_id']}` `{f['shown_variant']}!={f['assigned_variant']}`" for f in r["surfaced_flips"])
            if r["surfaced_flips"]
            else "none"
        )
        terms_active = []
        for short_k, full_k in (
            ("a", "ev_abstain_rescue"),
            ("b", "calibrated_wrong_accuse_residual"),
            ("c", "missed_catch_information_gap"),
            ("d", "timing_and_cost_bleed_gap"),
        ):
            if abs(float(r[full_k])) > IDENTITY_TOL:
                terms_active.append(f"`{short_k}={_fmt_signed(float(r[full_k]), 2)}`")
        t_str = ", ".join(terms_active) if terms_active else "`0.00`"
        lines.append(
            f"| `{r['cohort']}` | `{r['seed']}` | {dec} | `{_fmt_signed(r['agent_score'], 2)}` vs `{_fmt_signed(r['solver_score'], 2)}` "
            f"| {p_txt} vs `{r['ev_threshold']:.4f}` (`{r['known_V']:.2f}`) | `{r['entropy_bits']:.3f}` | {fl_txt} | `{r['regime']}` | {t_str} |"
        )
    lines.append("")
    lines.append(f"{H2}4. Scripted Baseline Reference Decomposition (`grok_tactics`) & Regret Cross-Checks")
    lines.append("")
    lines.append(
        "| Baseline Cohort | Tier | Score | Solver | `Delta` | `(a)` EV Rescue | `(b)` Cal. Wrong | `(c)` Info Gap | `(d)` Bleed/Cost | `(e)` Offset |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for b in data["baseline_reference_cohorts"]:
        sp = b["scores_and_posteriors"]
        cm = b["components"]
        lines.append(
            f"| `{b['cohort']}` | `{b['tier']}` | `{_fmt_signed(sp['agent_mean'])}` | `{_fmt_signed(sp['solver_mean'])}` "
            f"| `{_fmt_signed(sp['total_gap_delta'])}` | `{_fmt_signed(cm['ev_abstain_rescue']['mean'])}` "
            f"| `{_fmt_signed(cm['calibrated_wrong_accuse_residual']['mean'])}` | `{_fmt_signed(cm['missed_catch_information_gap']['mean'])}` "
            f"| `{_fmt_signed(cm['timing_and_cost_bleed_gap']['mean'])}` | `{_fmt_signed(cm['solver_miss_frontier_catch_offset']['mean'])}` |"
        )
    lines.append("")
    lines.append(
        "**Committed per-decision regret cross-checks (`0` discrepancies):** Verified exact parity against "
        "`results/regret_opencode-gemini-4-carbon-v1.4.json` (Hard: `mean_score = +0.3223`, `mean_p_correct = 0.8819`, "
        "`premature_accusation = 2` losing `0.8044 V`, `no_accusation = 1`; Medium: `mean_score = +0.7130`, "
        "`mean_p_correct = 0.9615`, `premature_accusation = 1` losing `0.1567 V`) and "
        "`results/regret_inproc-gemini-4-carbon-v1.4.json` (Hard: `mean_score = +0.4730`, `mean_p_correct = 0.9299`, "
        "`premature_accusation = 1` losing `0.5889 V`, `no_accusation = 1`; Medium: `mean_score = +0.5303`, "
        "`mean_p_correct = 0.9286`, `premature_accusation = 3` losing `1.2919 V`, `no_accusation = 4`), including "
        "every `top5` accusation decision regret to `1e-6`."
    )
    lines.append("")
    return "\n".join(lines)


def check_text_hygiene(label: str, text: str) -> list[str]:
    errs: list[str] = []
    if any(ord(ch) >= 128 for ch in text):
        errs.append(f"{label}: contains non-ASCII character(s)")
    if EN_DASH in text or EM_DASH in text:
        errs.append(f"{label}: contains forbidden en/em dash")
    for pat_name, rx in SECRET_AND_LEAK_PATTERNS:
        if rx.search(text):
            errs.append(f"{label}: matched forbidden {pat_name} pattern")
    return errs


EXPECTED_INPUTS_SHA256 = "921a8ab98739d7782b0dc2b40cb547202691eef98536925d2856efd4e6710e90"
EXPECTED_OUT_JSON_SHA256 = "53ab61449caa9fc99abc7506245105a36d41d56e6842925a4499fb899b744ac6"


def _repo_inputs_sha256(root: Path) -> str:
    rels: list[str] = []
    for base in ("data/runs/committed/v1.4", "results/frontier_replication/v1.4"):
        d = root / base
        if d.is_dir():
            for p in sorted(d.rglob("episodes.jsonl")):
                if p.is_file():
                    rels.append(p.relative_to(root).as_posix())
    solver_dir = root / "canary/solver"
    if solver_dir.is_dir():
        for p in sorted(solver_dir.rglob("*.py")):
            if p.is_file():
                rels.append(p.relative_to(root).as_posix())
    for extra in (
        "canary/rules.py",
        "canary/env.py",
        "results/harbor/rehearsal/TABLE.md",
        "results/harbor/rehearsal/BUILD.txt",
        "results/regret_opencode-gemini-4-carbon-v1.4.json",
        "results/regret_inproc-gemini-4-carbon-v1.4.json",
        "docs/reports/gap.md",
    ):
        if (root / extra).is_file():
            rels.append(extra)
    h = hashlib.sha256()
    for r in sorted(set(rels)):
        h.update(r.encode("ascii") + b"\0")
        h.update(hashlib.sha256((root / r).read_bytes()).digest())
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic keyless v1.4 counterfactual gap decomposition verifier."
    )
    ap.add_argument("--check", action="store_true", help="Verify committed JSON and Markdown without writing.")
    ap.add_argument("--full-check", action="store_true", help="Force full recomputation during --check.")
    ap.add_argument("--out-json", default=str(DEFAULT_OUT_JSON), help="Path to output JSON artifact.")
    ap.add_argument("--out-md", default=str(DEFAULT_OUT_MD), help="Path to output Markdown report.")
    args = ap.parse_args(argv)

    out_json_path = Path(args.out_json)
    out_md_path = Path(args.out_md)

    if (
        args.check
        and not args.full_check
        and out_json_path.resolve() == DEFAULT_OUT_JSON.resolve()
        and out_md_path.resolve() == DEFAULT_OUT_MD.resolve()
        and out_json_path.is_file()
        and out_md_path.is_file()
    ):
        on_disk_bytes = out_json_path.read_bytes()
        if (
            len(on_disk_bytes) <= MAX_JSON_BYTES
            and hashlib.sha256(on_disk_bytes).hexdigest() == EXPECTED_OUT_JSON_SHA256
            and _repo_inputs_sha256(ROOT) == EXPECTED_INPUTS_SHA256
        ):
            on_disk_str = on_disk_bytes.decode("utf-8", errors="replace")
            md_disk = out_md_path.read_text(encoding="utf-8", errors="replace")
            fast_errs = check_text_hygiene(str(out_json_path), on_disk_str) + check_text_hygiene(
                str(out_md_path), md_disk
            )
            on_disk_obj = json.loads(on_disk_str)
            roundtrip_obj = json.loads(serialize_json(on_disk_obj))
            if (
                not fast_errs
                and approx_equal(on_disk_obj, roundtrip_obj, tol=FLOAT_TOL)
                and md_disk == render_markdown_report(on_disk_obj)
            ):
                print(
                    f"OK: counterfactual_decomposition_v14 verified ({len(on_disk_obj['frontier_cohorts'])} frontier cohorts, "
                    f"{on_disk_obj['verification_totals']['frontier_episodes_replayed']} frontier eps, "
                    f"{len(on_disk_bytes)} bytes JSON)"
                )
                return 0

    data = compute_all(ROOT)
    expected_json_str = serialize_json(data)
    expected_json_bytes = expected_json_str.encode("utf-8")
    expected_md_str = render_markdown_report(data)

    if len(expected_json_bytes) > MAX_JSON_BYTES:
        print(
            f"FAIL: serialized JSON size {len(expected_json_bytes)} bytes exceeds {MAX_JSON_BYTES} byte cap",
            file=sys.stderr,
        )
        return 1

    hygiene_errors = check_text_hygiene("generated_json", expected_json_str) + check_text_hygiene(
        "generated_md", expected_md_str
    )
    if hygiene_errors:
        for e in hygiene_errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    if args.check:
        failures: list[str] = []
        if not out_json_path.is_file():
            failures.append(f"missing JSON artifact: {out_json_path}")
        else:
            on_disk_bytes = out_json_path.read_bytes()
            if len(on_disk_bytes) > MAX_JSON_BYTES:
                failures.append(f"JSON size {len(on_disk_bytes)} > {MAX_JSON_BYTES}")
            on_disk_str = on_disk_bytes.decode("utf-8", errors="replace")
            failures.extend(check_text_hygiene(str(out_json_path), on_disk_str))
            try:
                on_disk_obj = json.loads(on_disk_str)
                expected_obj = json.loads(expected_json_str)
                if not approx_equal(on_disk_obj, expected_obj, tol=FLOAT_TOL):
                    failures.append(f"JSON content drift in {out_json_path}")
            except json.JSONDecodeError as exc:
                failures.append(f"invalid JSON in {out_json_path}: {exc}")

        if not out_md_path.is_file():
            failures.append(f"missing Markdown report: {out_md_path}")
        else:
            md_disk = out_md_path.read_text(encoding="utf-8", errors="replace")
            failures.extend(check_text_hygiene(str(out_md_path), md_disk))
            if md_disk != expected_md_str:
                failures.append(f"Markdown report drift in {out_md_path}")

        if failures:
            for f in failures:
                print(f"CHECK FAILED: {f}", file=sys.stderr)
            return 1
        print(
            f"OK: counterfactual_decomposition_v14 verified ({len(data['frontier_cohorts'])} frontier cohorts, "
            f"{data['verification_totals']['frontier_episodes_replayed']} frontier eps, "
            f"{len(expected_json_bytes)} bytes JSON)"
        )
        return 0

    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_bytes(expected_json_bytes)
    out_md_path.write_text(expected_md_str, encoding="utf-8")
    print(
        f"WROTE {out_json_path} ({len(expected_json_bytes)} bytes) and {out_md_path} "
        f"({len(data['frontier_cohorts'])} frontier cohorts, {data['verification_totals']['frontier_episodes_replayed']} eps)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
