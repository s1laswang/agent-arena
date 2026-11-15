"""Deterministic v1.4 paired-seed world-difficulty, covariance, and per-seed diagnostic atlas.

Usage:
    /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py
    /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py --check
    /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py --json-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary.env import Env
from canary.eval import make_env, make_policy_factory, run_episode
from canary.redteam.anticheat import _canon, _client_only_step, _client_truncated_bytes, _norm_result
from canary.rules import TIERS, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import Step

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
H3 = HASH_CHAR * 3 + " "
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)

SCHEMA_VERSION = "paired_seed_diagnostics_v14.v1"
TIERS_VERSION = "v1.4"
PRIMARY_SEEDS = list(range(30))
G1_EXT_SEEDS = [34, 37]
SOLVER_EXT_SEEDS = list(range(30, 60))
BOOT_RESAMPLES = 10000
BOOT_SEED = 0
FLOAT_TOL = 1e-9
MAX_JSON_BYTES = 80000

DEFAULT_OUT_JSON = ROOT / "results/eval_v14/paired_seed_diagnostics_v14.json"
DEFAULT_OUT_MD = ROOT / "docs/reports/paired_seed_diagnostics_v14.md"

OUTCOME_CLASSES: tuple[str, ...] = (
    "isolated_c1_win",
    "unresolved_lucky_win",
    "sub_breakeven_gamble_win",
    "sub_breakeven_gamble_loss",
    "5pct_flip_singleton_trap",
    "unresolved_premature_loss",
    "horizon_abstain",
)

PRIMARY_COHORT_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "medium": (
        {
            "key": "opencode_carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "kind": "frontier",
            "label": "OpenCode + gemini-4-carbon over MCP",
            "mode": "cached",
            "paths": ["data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl"],
        },
        {
            "key": "inproc_carbon",
            "agent": "gemini:gemini-4-carbon",
            "kind": "frontier",
            "label": "in-process gemini-4-carbon (thought-signature replay)",
            "mode": "cached",
            "paths": ["data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl"],
        },
        {
            "key": "grok_tactics",
            "agent": "grok_tactics",
            "kind": "baseline",
            "label": "grok_tactics scripted baseline",
            "mode": "inproc_baseline",
            "paths": [],
        },
        {
            "key": "solver",
            "agent": "solver",
            "kind": "reference",
            "label": "SolverPolicy reference (20+10 dirs)",
            "mode": "cached",
            "paths": [
                "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
                "data/runs/committed/v1.4/reference/solver-medium-seeds20to29/episodes.jsonl",
            ],
        },
    ),
    "hard": (
        {
            "key": "opencode_carbon",
            "agent": "opencode:google/gemini-4-carbon",
            "kind": "frontier",
            "label": "OpenCode + gemini-4-carbon over MCP (MCP-only dev 0-29)",
            "mode": "cached",
            "paths": ["data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"],
        },
        {
            "key": "opencode_gpt55",
            "agent": "opencode:openai/gpt-5.5",
            "kind": "frontier",
            "label": "OpenCode + gpt-5.5 over MCP (second frontier family, pre-reg cf394894)",
            "mode": "cached",
            "paths": ["data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl"],
        },
        {
            "key": "inproc_carbon",
            "agent": "gemini:gemini-4-carbon",
            "kind": "frontier",
            "label": "in-process gemini-4-carbon (thought-signature replay)",
            "mode": "cached",
            "paths": ["data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl"],
        },
        {
            "key": "opencode_flash",
            "agent": "opencode:google/gemini-3.5-flash",
            "kind": "frontier",
            "label": "OpenCode + gemini-3.5-flash over MCP",
            "mode": "cached",
            "paths": ["data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl"],
        },
        {
            "key": "grok_tactics",
            "agent": "grok_tactics",
            "kind": "baseline",
            "label": "grok_tactics scripted baseline",
            "mode": "inproc_baseline",
            "paths": [],
        },
        {
            "key": "solver",
            "agent": "solver",
            "kind": "reference",
            "label": "SolverPolicy reference (20+10 dirs)",
            "mode": "cached",
            "paths": [
                "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
                "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
            ],
        },
    ),
}

G1_EXT_FRONTIER_REL = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl"
G1_EXT_SOLVER_REL = "data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl"
G1_EXT_POOLED_REL = "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
HARBOR_REHEARSAL_TABLE_REL = "results/harbor/rehearsal/TABLE.md"

SECRET_AND_LEAK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{20,}")),
    ("sk_api_key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}\b")),
    ("google_oauth_token", re.compile(r"\bya29\.[0-9A-Za-z_\-]{20,}")),
    ("provider_token", re.compile(r"\b(?:xai-[A-Za-z0-9_\-]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret_env_assignment",
        re.compile(
            r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
            r"OPENAI_API_KEY|ANTHROPIC_API_KEY|CANARY_WORLD_SECRET|"
            r"CANARY_LEDGER_TOKEN|CANARY_ADMIN_TOKEN|XAI_API_KEY|HF_TOKEN)"
            r"\s*=\s*[\x27\x22]?[A-Za-z0-9_\-]{16,}"
        ),
    ),
    ("world_mole_dump", re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')),
    ("employee_id_token", re.compile(r"\be[0-3]\d\b")),
)

FORBIDDEN_MOLE_KEYS = frozenset({"mole", "mole_id", "true_mole"})

_BOOT_PAIRED_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_BOOT_INDEP_CACHE: dict[tuple[int, int, int], tuple[np.ndarray, np.ndarray]] = {}
_LEAF_LIST_RE = re.compile(
    r"\[\n(?:\s*(?:null|true|false|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?|\"[^\"\n\\]*\"),?\n)+\s*\]"
)


def _norm_ascii(text: str) -> str:
    return (
        text.replace(EN_DASH, "-")
        .replace(EM_DASH, "--")
        .replace(MINUS_SIGN, "-")
        .replace(PLUS_MINUS, "+/-")
    )


def _clean_json_value(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 9)
    if isinstance(obj, str):
        return _norm_ascii(obj)
    if isinstance(obj, dict):
        return {str(k): _clean_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_json_value(v) for v in obj]
    return obj


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


def compact_json_dumps(data: dict[str, Any]) -> str:
    cleaned = _clean_json_value(data)
    raw = json.dumps(cleaned, separators=(",", ":"), ensure_ascii=True)
    return raw + "\n"


def _scan_forbidden_keys(obj: Any, path: str = "$") -> list[str]:
    errs: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in FORBIDDEN_MOLE_KEYS:
                errs.append(f"{path}.{ks}: forbidden mole field key")
            errs.extend(_scan_forbidden_keys(v, f"{path}.{ks}"))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            errs.extend(_scan_forbidden_keys(item, f"{path}[{idx}]"))
    return errs


def scan_text_hygiene(label: str, text: str) -> list[str]:
    errs: list[str] = []
    if EN_DASH in text or EM_DASH in text:
        errs.append(f"{label}: contains unicode en/em dash")
    for pat_name, rx in SECRET_AND_LEAK_PATTERNS:
        if rx.search(text):
            errs.append(f"{label}: forbidden {pat_name} pattern detected")
    return errs


def mean_val(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def sample_var(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def sample_cov(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)


def pearson_r(xs: list[float], ys: list[float]) -> float:
    vx = sample_var(xs)
    vy = sample_var(ys)
    if vx <= 0.0 or vy <= 0.0:
        return 0.0
    return sample_cov(xs, ys) / math.sqrt(vx * vy)


def _average_ranks(xs: list[float], tol: float = 1e-12) -> list[float]:
    n = len(xs)
    indexed = sorted(enumerate(xs), key=lambda kv: kv[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and abs(indexed[j][1] - indexed[i][1]) <= tol:
            j += 1
        avg_rank = 0.5 * (i + 1 + j)
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def spearman_rho(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    return pearson_r(_average_ranks(xs), _average_ranks(ys))


def paired_boot_weights(n: int, b_resamples: int = BOOT_RESAMPLES, rng_seed: int = BOOT_SEED) -> np.ndarray:
    key = (n, b_resamples, rng_seed)
    if key not in _BOOT_PAIRED_CACHE:
        rng = random.Random(rng_seed)
        w = np.zeros((b_resamples, n), dtype=np.float64)
        inv_n = 1.0 / n
        for b in range(b_resamples):
            for _ in range(n):
                w[b, rng.randrange(n)] += inv_n
        _BOOT_PAIRED_CACHE[key] = w
    return _BOOT_PAIRED_CACHE[key]


def indep_boot_weights(
    n: int,
    b_resamples: int = BOOT_RESAMPLES,
    rng_seed: int = BOOT_SEED,
) -> tuple[np.ndarray, np.ndarray]:
    key = (n, b_resamples, rng_seed)
    if key not in _BOOT_INDEP_CACHE:
        rng = random.Random(rng_seed)
        wf = np.zeros((b_resamples, n), dtype=np.float64)
        ws = np.zeros((b_resamples, n), dtype=np.float64)
        inv_n = 1.0 / n
        for b in range(b_resamples):
            for _ in range(n):
                wf[b, rng.randrange(n)] += inv_n
        for b in range(b_resamples):
            for _ in range(n):
                ws[b, rng.randrange(n)] += inv_n
        _BOOT_INDEP_CACHE[key] = (wf, ws)
    return _BOOT_INDEP_CACHE[key]


def _percentile_95(sorted_vals: np.ndarray) -> tuple[float, float]:
    m = int(sorted_vals.shape[0])
    if m == 0:
        return (0.0, 0.0)
    return (float(sorted_vals[int(0.025 * m)]), float(sorted_vals[int(0.975 * m) - 1]))


def bootstrap_paired_vs_indep(
    f_vals: list[float],
    s_vals: list[float],
    b_resamples: int = BOOT_RESAMPLES,
    rng_seed: int = BOOT_SEED,
) -> dict[str, Any]:
    n = len(f_vals)
    if n < 2 or len(s_vals) != n:
        raise ValueError("bootstrap_paired_vs_indep requires equal-length vectors with n >= 2")
    fa = np.asarray(f_vals, dtype=np.float64)
    sa = np.asarray(s_vals, dtype=np.float64)

    wp = paired_boot_weights(n, b_resamples, rng_seed)
    mf_p = wp @ fa
    ms_p = wp @ sa
    diff_p = np.sort(mf_p - ms_p)
    d_p_lo, d_p_hi = _percentile_95(diff_p)

    mask_p = ms_p > 0.0
    ratio_p = np.sort(mf_p[mask_p] / ms_p[mask_p])
    r_p_lo, r_p_hi = _percentile_95(ratio_p)

    wf_i, ws_i = indep_boot_weights(n, b_resamples, rng_seed)
    mf_i = wf_i @ fa
    ms_i = ws_i @ sa
    diff_i = np.sort(mf_i - ms_i)
    d_i_lo, d_i_hi = _percentile_95(diff_i)

    mask_i = ms_i > 0.0
    ratio_i = np.sort(mf_i[mask_i] / ms_i[mask_i])
    r_i_lo, r_i_hi = _percentile_95(ratio_i)

    d_p_w = d_p_hi - d_p_lo
    d_i_w = d_i_hi - d_i_lo
    r_p_w = r_p_hi - r_p_lo
    r_i_w = r_i_hi - r_i_lo

    return {
        "diff_paired_ci95": [d_p_lo, d_p_hi],
        "diff_paired_width": d_p_w,
        "diff_unpaired_ci95": [d_i_lo, d_i_hi],
        "diff_unpaired_width": d_i_w,
        "diff_width_reduction": (d_i_w / d_p_w) if d_p_w > 0.0 else 1.0,
        "ratio_paired_ci95": [r_p_lo, r_p_hi],
        "ratio_paired_width": r_p_w,
        "ratio_unpaired_ci95": [r_i_lo, r_i_hi],
        "ratio_unpaired_width": r_i_w,
        "ratio_width_reduction": (r_i_w / r_p_w) if r_p_w > 0.0 else 1.0,
    }


def classify_episode_outcome(
    *,
    accused_present: bool,
    correct: bool,
    consistent_set_size: int,
    mole_in_strict_consistent_set: bool,
    p_accused: float | None,
    break_even_p: float,
    surfaced_flips_count: int,
) -> str:
    if not accused_present:
        return "horizon_abstain"
    p_val = float(p_accused) if p_accused is not None else 0.0
    if p_val < break_even_p:
        return "sub_breakeven_gamble_win" if correct else "sub_breakeven_gamble_loss"
    if correct:
        return "isolated_c1_win" if consistent_set_size <= 1 else "unresolved_lucky_win"
    if consistent_set_size <= 1 and (not mole_in_strict_consistent_set) and surfaced_flips_count >= 1:
        return "5pct_flip_singleton_trap"
    return "unresolved_premature_loss"


def load_cached_episodes(
    root: Path,
    rel_paths: list[str],
    tier: str,
    agent: str,
    allowed_seeds: set[int],
) -> tuple[dict[int, dict[str, Any]], list[str]]:
    by_seed: dict[int, dict[str, Any]] = {}
    git_shas: list[str] = []
    for rel in rel_paths:
        if "seeds30to59" in rel and allowed_seeds == set(PRIMARY_SEEDS):
            raise ValueError(f"forbidden seeds30to59 path in primary 0..29 loader: {rel}")
        fp = root / rel
        if not fp.is_file():
            raise FileNotFoundError(f"missing committed episode cache: {rel}")
        meta_fp = fp.parent / "meta.json"
        if meta_fp.is_file():
            meta_obj = json.loads(meta_fp.read_text(encoding="utf-8"))
            sha = str(meta_obj.get("git_sha") or "")[:8]
            if sha and sha not in git_shas:
                git_shas.append(sha)
        for raw_line in fp.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            ep = json.loads(raw_line)
            if str(ep.get("tier")) != tier or str(ep.get("agent")) != agent:
                continue
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            sd = int(ep["seed"])
            if sd not in allowed_seeds:
                continue
            if sd in by_seed:
                raise ValueError(f"duplicate seed {sd} for {agent} on {tier} in {rel_paths}")
            by_seed[sd] = ep
    return by_seed, git_shas


def run_and_diagnose_inproc_baseline(tier: str, agent: str, seeds: list[int]) -> list[dict[str, Any]]:
    fac = make_policy_factory(agent)
    out: list[dict[str, Any]] = []
    for sd in seeds:
        env = make_env(tier, sd)
        res = run_episode(env, fac(sd))
        ep_dict = {
            "tier": res.tier,
            "seed": res.seed,
            "agent": agent,
            "steps": [
                {"t": s.t, "day": s.day, "tool": s.tool, "args": s.args, "result": s.result}
                for s in res.steps
            ],
            "score": res.score,
            "accused": res.accused,
            "correct": res.correct,
            "final_day": res.final_day,
            "meta": res.meta,
        }
        out.append(replay_and_diagnose_episode(ep_dict))
    return out


def replay_verify_score_only(ep: dict[str, Any]) -> tuple[float, int, int]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    raw_steps = ep.get("steps") or []
    env = Env(tier, seed)
    step_bad = 0
    n_steps = 0
    n_detail_stripped = 0
    for st in raw_steps:
        if _client_only_step(st):
            continue
        n_steps += 1
        r = env.call(str(st["tool"]), st.get("args") or {})
        got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
        rec = _norm_result(st.get("result"))
        if (
            not r.ok
            and isinstance(r.data, dict)
            and set(r.data) == {"detail"}
            and not (isinstance(rec, dict) and isinstance(rec.get("data"), dict) and "detail" in rec["data"])
        ):
            got_payload = {"ok": r.ok, "data": {}, "error": r.error}
            n_detail_stripped += 1
        trunc = _client_truncated_bytes(st.get("result"))
        if trunc is not None:
            ok_match = len(json.dumps(got_payload).encode()) == trunc
        else:
            ok_match = rec is None or got_payload == rec or _canon(got_payload) == _canon(rec)
        if not ok_match:
            step_bad += 1
    got_score = float(env.score())
    verdict = env.verdict()
    if (
        abs(got_score - float(ep["score"])) > 1e-6
        or verdict["accused"] != ep.get("accused")
        or bool(verdict["correct"]) != bool(ep.get("correct"))
        or step_bad > 0
    ):
        raise ValueError(f"Env replay mismatch on {ep.get('agent')} {tier} seed {seed}")
    return (got_score, n_steps, n_detail_stripped)


def replay_and_diagnose_episode(ep: dict[str, Any]) -> dict[str, Any]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    raw_steps = ep.get("steps") or []
    env = Env(tier, seed)

    clean_steps: list[Step] = []
    step_bad = 0
    n_trunc = 0
    n_client = 0
    n_detail_stripped = 0

    for st in raw_steps:
        if _client_only_step(st):
            n_client += 1
            continue
        tool_name = str(st["tool"])
        tool_args = st.get("args") or {}
        r = env.call(tool_name, tool_args)
        live_payload = {"ok": r.ok, "data": r.data, "error": r.error}
        got_payload = live_payload
        rec = _norm_result(st.get("result"))
        if (
            not r.ok
            and isinstance(r.data, dict)
            and set(r.data) == {"detail"}
            and not (isinstance(rec, dict) and isinstance(rec.get("data"), dict) and "detail" in rec["data"])
        ):
            got_payload = {"ok": r.ok, "data": {}, "error": r.error}
            n_detail_stripped += 1

        trunc = _client_truncated_bytes(st.get("result"))
        if trunc is not None:
            n_trunc += 1
            ok_match = len(json.dumps(got_payload).encode()) == trunc
        else:
            ok_match = rec is None or got_payload == rec or _canon(got_payload) == _canon(rec)
        if not ok_match:
            step_bad += 1

        clean_steps.append(
            Step(
                t=int(st.get("t", len(clean_steps))),
                day=int(st.get("day", env.day)),
                tool=tool_name,
                args=tool_args if isinstance(tool_args, dict) else {},
                result=live_payload,
            )
        )

    got_score = float(env.score())
    verdict = env.verdict()
    got_done = bool(verdict["done"])
    got_accused = verdict["accused"]
    got_correct = bool(verdict["correct"])
    got_final_day = int(verdict["final_day"])
    true_v = float(verdict["V"])
    shown_v = float(env.visible_V())

    ep_final_day = int(ep.get("final_day", got_final_day))
    day_ok = (got_final_day == ep_final_day) if got_done else (ep_final_day in (0, got_final_day))

    if (
        abs(got_score - float(ep["score"])) > 1e-6
        or got_accused != ep.get("accused")
        or got_correct != bool(ep.get("correct"))
        or not day_ok
        or step_bad > 0
    ):
        raise ValueError(
            f"Env replay mismatch on {ep.get('agent')} {tier} seed {seed}: "
            f"score {got_score} vs {ep.get('score')}, step_bad={step_bad}"
        )

    meta_obj = ep.get("meta") or {}
    meta_v = meta_obj.get("V", meta_obj.get("V_final"))
    if meta_v is not None and abs(float(meta_v) - true_v) > 1e-6:
        raise ValueError(f"V mismatch on {ep.get('agent')} {tier} seed {seed}: {meta_v} vs {true_v}")

    acc_idx = next(
        (i for i, s in enumerate(clean_steps) if s.tool == "accuse" and bool((s.result or {}).get("ok"))),
        None,
    )
    upto = acc_idx if acc_idx is not None else len(clean_steps)

    sp = SolverPolicy(tier_params_for_episode(tier, clean_steps))
    for prev in clean_steps[:upto]:
        sp._ingest(prev)
    post = sp.belief() if sp.obs.employees else {}

    accused_present = got_accused is not None
    if accused_present:
        p_accused: float | None = round(float(post.get(got_accused, 0.0)), 3) if post else 0.0
    else:
        p_accused = None
    p_top = round(float(max(post.values())), 3) if post else round(1.0 / env.p.n_employees, 3)

    break_even_p = 1.0 / (1.0 + true_v)
    luck_adjusted = 0.0 if (not accused_present or p_accused is None) else (
        float(p_accused) * true_v - (1.0 - float(p_accused))
    )

    asg: dict[str, dict[str, str]] = {}
    last_items: list[dict[str, Any]] = []
    first_c1_day: int | None = None
    docs = env._doc_by_id
    for s in clean_steps[:upto]:
        res_ok = bool((s.result or {}).get("ok"))
        if not res_ok:
            continue
        if s.tool == "plant_canary":
            cid = ((s.result or {}).get("data") or {}).get("canary_id")
            if cid:
                asg[str(cid)] = dict((s.args or {}).get("assignment") or {})
        elif s.tool == "check_leak_feed":
            last_items = list(((s.result or {}).get("data") or {}).get("items") or [])
            cand_now = set(env._ids)
            for it in last_items:
                did = it.get("doc_id")
                if it.get("variant") is not None and did in asg:
                    cand_now &= {emp for emp, lab in asg[did].items() if lab == it["variant"]}
                elif did in docs:
                    cand_now &= set(docs[did].get("recipients") or [])
            if len(cand_now) == 1 and first_c1_day is None:
                first_c1_day = int(s.day)

    cand_final = set(env._ids)
    for it in last_items:
        did = it.get("doc_id")
        if it.get("variant") is not None and did in asg:
            cand_final &= {emp for emp, lab in asg[did].items() if lab == it["variant"]}
        elif did in docs:
            cand_final &= set(docs[did].get("recipients") or [])

    true_culprit = env._world.mole
    consistent_set_size = len(cand_final)
    mole_in_strict_consistent_set = bool(true_culprit in cand_final)

    canaries_planted = sum(
        1 for s in clean_steps[:upto] if s.tool == "plant_canary" and bool((s.result or {}).get("ok"))
    )
    interviews = sum(
        1 for s in clean_steps[:upto] if s.tool == "interview" and bool((s.result or {}).get("ok"))
    )

    surfaced_items = [f for f in env._feed if int(f["surfaced_day"]) <= got_final_day]
    surfaced_leaks = len(surfaced_items)
    surfaced_regular_leaks = 0
    surfaced_flips_count = 0
    for f in surfaced_items:
        d = docs.get(f["doc_id"])
        if d and d.get("is_canary"):
            if "variant" in f:
                true_label = next(k for k, v in d["variants"].items() if true_culprit in v)
                if f["variant"] != true_label:
                    surfaced_flips_count += 1
        else:
            surfaced_regular_leaks += 1

    outcome_class = classify_episode_outcome(
        accused_present=accused_present,
        correct=got_correct,
        consistent_set_size=consistent_set_size,
        mole_in_strict_consistent_set=mole_in_strict_consistent_set,
        p_accused=p_accused,
        break_even_p=break_even_p,
        surfaced_flips_count=surfaced_flips_count,
    )

    return {
        "seed": seed,
        "score": got_score,
        "luck_adjusted": luck_adjusted,
        "correct": got_correct,
        "accused_present": accused_present,
        "episode_done": got_done,
        "consistent_set_size": consistent_set_size,
        "mole_in_strict_consistent_set": mole_in_strict_consistent_set,
        "p_accused": p_accused,
        "p_top": p_top,
        "break_even_p": break_even_p,
        "true_v": true_v,
        "shown_v": shown_v,
        "final_day": got_final_day,
        "canaries_planted": canaries_planted,
        "interviews": interviews,
        "surfaced_leaks": surfaced_leaks,
        "surfaced_regular_leaks": surfaced_regular_leaks,
        "surfaced_flips_count": surfaced_flips_count,
        "first_c1_day": first_c1_day,
        "outcome_class": outcome_class,
        "steps_verified": len(clean_steps),
        "steps_client_only": n_client,
        "steps_truncated_checked": n_trunc,
        "steps_detail_stripped": n_detail_stripped,
    }


def probe_intrinsic_worlds(tier: str, seeds: list[int]) -> dict[int, dict[str, Any]]:
    n_days = int(TIERS[tier].n_days)
    out: dict[int, dict[str, Any]] = {}
    for sd in seeds:
        env = Env(tier, sd)
        while not env.done:
            env.call("advance_day", {})
        surfaced_reg = sum(1 for f in env._feed if int(f["surfaced_day"]) <= n_days)
        out[sd] = {
            "seed": sd,
            "n_days": n_days,
            "intrinsic_surfaced_regular_leaks": surfaced_reg,
            "intrinsic_regular_leak_rate": surfaced_reg / n_days,
        }
    return out


def compact_episode_columns(recs: list[dict[str, Any]], include_seed: bool = False) -> dict[str, list[Any]]:
    ordered = sorted(recs, key=lambda r: int(r["seed"]))
    cols: dict[str, list[Any]] = {}
    if include_seed:
        cols["seed"] = [int(r["seed"]) for r in ordered]
    cols.update(
        {
            "score": [float(r["score"]) for r in ordered],
            "la": [float(r["luck_adjusted"]) for r in ordered],
            "correct": [int(bool(r["correct"])) for r in ordered],
            "accused": [int(bool(r["accused_present"])) for r in ordered],
            "c_size": [int(r["consistent_set_size"]) for r in ordered],
            "mole_in_c": [int(bool(r["mole_in_strict_consistent_set"])) for r in ordered],
            "p_accused": [float(r["p_accused"]) if r["p_accused"] is not None else None for r in ordered],
            "p_top": [float(r["p_top"]) if r["p_top"] is not None else None for r in ordered],
            "break_even_p": [round(float(r["break_even_p"]), 6) for r in ordered],
            "true_v": [float(r["true_v"]) for r in ordered],
            "shown_v": [float(r["shown_v"]) for r in ordered],
            "final_day": [int(r["final_day"]) for r in ordered],
            "canaries": [int(r["canaries_planted"]) for r in ordered],
            "interviews": [int(r["interviews"]) for r in ordered],
            "leaks": [int(r["surfaced_leaks"]) for r in ordered],
            "flips": [int(r["surfaced_flips_count"]) for r in ordered],
            "outcome_idx": [OUTCOME_CLASSES.index(str(r["outcome_class"])) for r in ordered],
        }
    )
    return cols


def summarize_outcome_taxonomy(recs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(recs)
    counts: dict[str, int] = {cls: 0 for cls in OUTCOME_CLASSES}
    seeds_by_cls: dict[str, list[int]] = {cls: [] for cls in OUTCOME_CLASSES}
    for r in sorted(recs, key=lambda x: int(x["seed"])):
        cls = str(r["outcome_class"])
        counts[cls] = counts.get(cls, 0) + 1
        seeds_by_cls.setdefault(cls, []).append(int(r["seed"]))
    c0_recovery_seeds = [
        int(r["seed"])
        for r in recs
        if r["outcome_class"] == "isolated_c1_win" and int(r["consistent_set_size"]) == 0
    ]
    stopped_without_accuse_seeds = [
        int(r["seed"])
        for r in recs
        if (not bool(r["accused_present"])) and (not bool(r.get("episode_done", True)))
    ]
    return {
        "n": n,
        "counts": counts,
        "seeds_by_class": {cls: sds for cls, sds in seeds_by_cls.items() if sds},
        "c0_noisy_bayes_recovery_seeds": sorted(c0_recovery_seeds),
        "stopped_without_accuse_seeds": sorted(stopped_without_accuse_seeds),
    }


def summarize_cohort_subset(
    recs: list[dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    n = len(recs)
    if n == 0:
        return {
            "n": 0,
            "raw_mean": 0.0,
            "luck_adjusted_mean": 0.0,
            "accuracy": 0.0,
            "accused_rate": 0.0,
            "mean_accuse_day": None,
            "solver_raw_mean": 0.0,
            "solver_luck_mean": 0.0,
            "raw_ratio_vs_solver": None,
            "luck_ratio_vs_solver": None,
        }
    f_raw = [float(r["score"]) for r in recs]
    f_la = [float(r["luck_adjusted"]) for r in recs]
    s_raw = [float(solver_by_seed[int(r["seed"])]["score"]) for r in recs]
    s_la = [float(solver_by_seed[int(r["seed"])]["luck_adjusted"]) for r in recs]
    rm = mean_val(f_raw)
    lm = mean_val(f_la)
    srm = mean_val(s_raw)
    slm = mean_val(s_la)
    accused_days = [float(r["final_day"]) for r in recs if r["accused_present"]]
    return {
        "n": n,
        "raw_mean": rm,
        "luck_adjusted_mean": lm,
        "accuracy": sum(1 for r in recs if r["correct"]) / n,
        "accused_rate": sum(1 for r in recs if r["accused_present"]) / n,
        "mean_p_accused": (
            mean_val([float(r["p_accused"]) for r in recs if r["p_accused"] is not None])
            if any(r["p_accused"] is not None for r in recs)
            else None
        ),
        "mean_accuse_day": mean_val(accused_days) if accused_days else None,
        "mean_final_day": mean_val([float(r["final_day"]) for r in recs]),
        "solver_raw_mean": srm,
        "solver_luck_mean": slm,
        "raw_ratio_vs_solver": (rm / srm) if srm > 0.0 else None,
        "luck_ratio_vs_solver": (lm / slm) if slm > 0.0 else None,
    }


def summarize_stratum_cohort(
    recs: list[dict[str, Any]],
    solver_raw_mean: float,
    solver_luck_mean: float,
) -> dict[str, Any]:
    n = len(recs)
    if n == 0:
        return {
            "raw": 0.0,
            "la": 0.0,
            "acc": 0.0,
            "raw_ratio": None,
            "la_ratio": None,
        }
    rm = mean_val([float(r["score"]) for r in recs])
    lm = mean_val([float(r["luck_adjusted"]) for r in recs])
    return {
        "raw": rm,
        "la": lm,
        "acc": sum(1 for r in recs if r["correct"]) / n,
        "raw_ratio": (rm / solver_raw_mean) if solver_raw_mean > 0.0 else None,
        "la_ratio": (lm / solver_luck_mean) if solver_luck_mean > 0.0 else None,
    }


def build_paired_covariance_proof(
    cohort_recs: dict[str, list[dict[str, Any]]],
    cohort_order: list[str],
) -> dict[str, Any]:
    solver_recs = cohort_recs["solver"]
    s_raw = [float(r["score"]) for r in solver_recs]
    s_la = [float(r["luck_adjusted"]) for r in solver_recs]

    pairwise_matrices: dict[str, Any] = {"cohorts": cohort_order}
    for metric_key, field in (("raw", "score"), ("luck_adjusted", "luck_adjusted")):
        vecs = [[float(r[field]) for r in cohort_recs[k]] for k in cohort_order]
        m = len(cohort_order)
        r_mat = [[1.0 if i == j else round(pearson_r(vecs[i], vecs[j]), 6) for j in range(m)] for i in range(m)]
        rho_mat = [[1.0 if i == j else round(spearman_rho(vecs[i], vecs[j]), 6) for j in range(m)] for i in range(m)]
        cov_mat = [
            [round(sample_var(vecs[i]) if i == j else sample_cov(vecs[i], vecs[j]), 6) for j in range(m)]
            for i in range(m)
        ]
        pairwise_matrices[metric_key] = {
            "pearson_r": r_mat,
            "spearman_rho": rho_mat,
            "cov": cov_mat,
        }

    vs_solver: dict[str, Any] = {}
    for key in cohort_order:
        if key == "solver":
            continue
        recs = cohort_recs[key]
        f_raw = [float(r["score"]) for r in recs]
        f_la = [float(r["luck_adjusted"]) for r in recs]
        n = len(recs)

        entry: dict[str, Any] = {}
        for metric_key, fv, sv in (("raw", f_raw, s_raw), ("luck_adjusted", f_la, s_la)):
            vf = sample_var(fv)
            vs = sample_var(sv)
            cov_fs = sample_cov(fv, sv)
            diffs = [a - b for a, b in zip(fv, sv)]
            vd = sample_var(diffs)
            se_unp = math.sqrt((vf + vs) / n)
            se_prd = math.sqrt(vd / n)
            boot = bootstrap_paired_vs_indep(fv, sv)
            entry[metric_key] = {
                "frontier_mean": mean_val(fv),
                "solver_mean": mean_val(sv),
                "diff_mean": mean_val(diffs),
                "ratio": mean_val(fv) / mean_val(sv) if mean_val(sv) > 0.0 else None,
                "var_frontier": vf,
                "var_solver": vs,
                "cov_fs": cov_fs,
                "var_paired_diff": vd,
                "pearson_r": pearson_r(fv, sv),
                "spearman_rho": spearman_rho(fv, sv),
                "se_unpaired": se_unp,
                "se_paired": se_prd,
                "se_reduction_factor": (se_unp / se_prd) if se_prd > 0.0 else 1.0,
                "var_reduction_factor": ((vf + vs) / vd) if vd > 0.0 else 1.0,
                "bootstrap_10k": boot,
            }

        raw_se_unp = float(entry["raw"]["se_unpaired"])
        la_se_prd = float(entry["luck_adjusted"]["se_paired"])
        raw_ratio_w_unp = float(entry["raw"]["bootstrap_10k"]["ratio_unpaired_width"])
        la_ratio_w_prd = float(entry["luck_adjusted"]["bootstrap_10k"]["ratio_paired_width"])
        raw_diff_w_unp = float(entry["raw"]["bootstrap_10k"]["diff_unpaired_width"])
        la_diff_w_prd = float(entry["luck_adjusted"]["bootstrap_10k"]["diff_paired_width"])

        entry["combined_tightening_raw_unpaired_to_luck_paired"] = {
            "se_reduction_factor": (raw_se_unp / la_se_prd) if la_se_prd > 0.0 else 1.0,
            "var_reduction_factor": ((raw_se_unp / la_se_prd) ** 2) if la_se_prd > 0.0 else 1.0,
            "diff_boot_ci_width_reduction": (raw_diff_w_unp / la_diff_w_prd) if la_diff_w_prd > 0.0 else 1.0,
            "ratio_boot_ci_width_reduction": (raw_ratio_w_unp / la_ratio_w_prd) if la_ratio_w_prd > 0.0 else 1.0,
        }
        vs_solver[key] = entry

    return {
        "n_seeds": len(solver_recs),
        "bootstrap_resamples": BOOT_RESAMPLES,
        "bootstrap_rng_seed": BOOT_SEED,
        "pairwise_matrices": pairwise_matrices,
        "vs_solver": vs_solver,
    }


def build_world_difficulty_stratification(
    tier: str,
    cohort_recs: dict[str, list[dict[str, Any]]],
    cohort_order: list[str],
) -> dict[str, Any]:
    solver_by_seed = {int(r["seed"]): r for r in cohort_recs["solver"]}
    intrinsic_by_seed = probe_intrinsic_worlds(tier, PRIMARY_SEEDS)

    any_flip_seeds: set[int] = set()
    for k in cohort_order:
        for r in cohort_recs[k]:
            if int(r["surfaced_flips_count"]) > 0:
                any_flip_seeds.add(int(r["seed"]))

    iso_order = sorted(
        PRIMARY_SEEDS,
        key=lambda sd: (
            int(solver_by_seed[sd]["first_c1_day"])
            if solver_by_seed[sd]["first_c1_day"] is not None
            else 999,
            int(solver_by_seed[sd]["final_day"]),
            sd,
        ),
    )
    tertile_map: dict[int, str] = {}
    for idx, sd in enumerate(iso_order):
        if idx < 10:
            tertile_map[sd] = "fast_t1"
        elif idx < 20:
            tertile_map[sd] = "mid_t2"
        else:
            tertile_map[sd] = "slow_t3"

    leak_order = sorted(
        PRIMARY_SEEDS,
        key=lambda sd: (
            int(intrinsic_by_seed[sd]["intrinsic_surfaced_regular_leaks"]),
            sd,
        ),
    )
    low_leak_seeds = sorted(leak_order[:15])
    high_leak_seeds = sorted(leak_order[15:])

    solver_flip_seeds = sorted(
        sd for sd in PRIMARY_SEEDS if int(solver_by_seed[sd]["surfaced_flips_count"]) > 0
    )
    solver_no_flip_seeds = sorted(sd for sd in PRIMARY_SEEDS if sd not in set(solver_flip_seeds))

    any_cohort_flip_seeds = sorted(any_flip_seeds)
    zero_cohort_flip_seeds = sorted(sd for sd in PRIMARY_SEEDS if sd not in any_flip_seeds)

    winnable_seeds = sorted(sd for sd in PRIMARY_SEEDS if float(solver_by_seed[sd]["score"]) > 0.0)
    non_winnable_seeds = sorted(sd for sd in PRIMARY_SEEDS if float(solver_by_seed[sd]["score"]) <= 0.0)

    def _summarize_seed_group(seed_list: list[int]) -> dict[str, Any]:
        seed_set = set(seed_list)
        s_sub = [r for r in cohort_recs["solver"] if int(r["seed"]) in seed_set]
        srm = mean_val([float(r["score"]) for r in s_sub])
        slm = mean_val([float(r["luck_adjusted"]) for r in s_sub])
        cohorts_sub = {
            k: summarize_stratum_cohort(
                [r for r in cohort_recs[k] if int(r["seed"]) in seed_set],
                srm,
                slm,
            )
            for k in cohort_order
        }
        return {
            "n_seeds": len(seed_list),
            "seeds": seed_list,
            "intrinsic_regular_leak_rate_mean": mean_val(
                [float(intrinsic_by_seed[s]["intrinsic_regular_leak_rate"]) for s in seed_list]
            )
            if seed_list
            else 0.0,
            "cohorts": cohorts_sub,
        }

    own_flip_split: dict[str, Any] = {}
    if float(TIERS[tier].fingerprint_accuracy) < 1.0:
        for k in cohort_order:
            with_flip = [r for r in cohort_recs[k] if int(r["surfaced_flips_count"]) > 0]
            without_flip = [r for r in cohort_recs[k] if int(r["surfaced_flips_count"]) == 0]
            own_flip_split[k] = {
                "with_flip": {
                    "n": len(with_flip),
                    "seeds": [int(r["seed"]) for r in with_flip],
                    "raw": mean_val([float(r["score"]) for r in with_flip]),
                    "la": mean_val([float(r["luck_adjusted"]) for r in with_flip]),
                    "acc": (sum(1 for r in with_flip if r["correct"]) / len(with_flip)) if with_flip else None,
                },
                "no_flip": {
                    "n": len(without_flip),
                    "raw": mean_val([float(r["score"]) for r in without_flip]),
                    "la": mean_val([float(r["luck_adjusted"]) for r in without_flip]),
                    "acc": (
                        sum(1 for r in without_flip if r["correct"]) / len(without_flip)
                    )
                    if without_flip
                    else None,
                },
            }

    world_columns = {
        "seed": list(PRIMARY_SEEDS),
        "intrinsic_surfaced_regular_leaks": [
            int(intrinsic_by_seed[s]["intrinsic_surfaced_regular_leaks"]) for s in PRIMARY_SEEDS
        ],
        "intrinsic_regular_leak_rate": [
            round(float(intrinsic_by_seed[s]["intrinsic_regular_leak_rate"]), 6) for s in PRIMARY_SEEDS
        ],
        "solver_first_c1_day": [
            int(solver_by_seed[s]["first_c1_day"])
            if solver_by_seed[s]["first_c1_day"] is not None
            else None
            for s in PRIMARY_SEEDS
        ],
        "solver_winnable": [float(solver_by_seed[s]["score"]) > 0.0 for s in PRIMARY_SEEDS],
        "any_cohort_surfaced_flip": [s in any_flip_seeds for s in PRIMARY_SEEDS],
        "iso_tertile": [tertile_map[s] for s in PRIMARY_SEEDS],
    }

    flip_block: dict[str, Any] = {
        "fingerprint_accuracy": float(TIERS[tier].fingerprint_accuracy),
        "solver_flip_seeds": solver_flip_seeds,
        "any_cohort_flip_seeds": any_cohort_flip_seeds,
    }
    if float(TIERS[tier].fingerprint_accuracy) < 1.0:
        flip_block.update(
            {
                "solver_flip_worlds": _summarize_seed_group(solver_flip_seeds),
                "solver_no_flip_worlds": _summarize_seed_group(solver_no_flip_seeds),
                "any_cohort_flip_worlds": _summarize_seed_group(any_cohort_flip_seeds),
                "zero_cohort_flip_worlds": _summarize_seed_group(zero_cohort_flip_seeds),
                "per_cohort_own_trajectory_flip": own_flip_split,
            }
        )

    return {
        "world_columns": world_columns,
        "by_solver_isolation_tertile": {
            t_name: _summarize_seed_group([s for s in PRIMARY_SEEDS if tertile_map[s] == t_name])
            for t_name in ("fast_t1", "mid_t2", "slow_t3")
        },
        "by_intrinsic_regular_leak_rate": {
            "low_leak_half": _summarize_seed_group(low_leak_seeds),
            "high_leak_half": _summarize_seed_group(high_leak_seeds),
        },
        "by_5pct_flip_occurrence": flip_block,
        "by_winnability": {
            "winnable_solver_gt_0": _summarize_seed_group(winnable_seeds),
            "non_winnable_solver_le_0": _summarize_seed_group(non_winnable_seeds),
        },
    }


def load_harbor_rehearsal_summary(root: Path) -> dict[str, Any]:
    fp = root / HARBOR_REHEARSAL_TABLE_REL
    if not fp.is_file():
        raise FileNotFoundError(f"missing Harbor rehearsal table: {HARBOR_REHEARSAL_TABLE_REL}")
    raw_text = fp.read_text(encoding="utf-8")
    snapshot_runs: dict[str, dict[str, Any]] = {}
    target_names = {"opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early"}
    for raw_line in raw_text.splitlines():
        if not raw_line.startswith("|"):
            continue
        cells = [c.strip() for c in raw_line.strip("|").split("|")]
        if len(cells) != 9 or cells[0] not in target_names:
            continue
        ratio_tok = cells[6].split()[0].rstrip("%")
        snapshot_runs[cells[0]] = {
            "n_valid": int(cells[1]),
            "infra_excluded": int(cells[2]),
            "correct_over_accused": cells[3],
            "mean": float(cells[4]),
            "oracle_same_tasks": float(cells[5]),
            "ratio_pct": int(ratio_tok),
            "diff": float(cells[7]),
        }
    if set(snapshot_runs.keys()) != target_names:
        raise ValueError(f"incomplete Harbor rehearsal summary rows in {HARBOR_REHEARSAL_TABLE_REL}")

    runs = {k: dict(v) for k, v in snapshot_runs.items()}
    corr_rx = re.compile(
        r"Final:\s*run 3 has (\d+) valid trials\s*\([^)]*?(\d+)\s+infra-excluded\),\s*"
        r"mean\s*([+-]?\d+\.\d+)\s*=\s*(\d+)%\s*\[(\d+)%,\s*(\d+)%\]"
    )
    corr_match = corr_rx.search(raw_text)
    has_final_correction = corr_match is not None
    if corr_match is not None:
        n_val = int(corr_match.group(1))
        n_inf = int(corr_match.group(2))
        mean_v = float(corr_match.group(3))
        rat_pct = int(corr_match.group(4))
        ci_lo = int(corr_match.group(5))
        ci_hi = int(corr_match.group(6))
        snap_r3 = snapshot_runs["opencode-3"]
        runs["opencode-3"] = {
            "n_valid": n_val,
            "infra_excluded": n_inf,
            "correct_over_accused": f"{n_val} / {n_val}",
            "mean": mean_v,
            "oracle_all_10_tasks": runs["opencode-1"]["oracle_same_tasks"],
            "ratio_pct": rat_pct,
            "ratio_ci95_pct": [ci_lo, ci_hi],
            "snapshot_0852_n_valid": snap_r3["n_valid"],
            "snapshot_0852_mean": snap_r3["mean"],
            "snapshot_0852_oracle_same_tasks": snap_r3["oracle_same_tasks"],
            "snapshot_0852_ratio_pct": snap_r3["ratio_pct"],
        }

    return {
        "table_path": HARBOR_REHEARSAL_TABLE_REL,
        "tag": "afterquery-final (1bc3e281)",
        "commit": "aa1c679e" if has_final_correction else "c59ecfd0",
        "snapshot_commit": "c59ecfd0",
        "ceo_correction_commit": "5f9b3297" if has_final_correction else None,
        "final_trials_branch": "s1-rehearsal-final" if has_final_correction else None,
        "final_trials_commit": "d0ead011" if has_final_correction else None,
        "valid_gemini_accusations_correct": "28 / 29" if has_final_correction else "26 / 27",
        "gap_reproduced_in_judge_path": False,
        "runs": runs,
    }


def compute(root: Path = ROOT) -> dict[str, Any]:
    total_episodes_replayed = 0
    total_cached_episodes_replayed = 0
    total_inproc_baseline_replayed = 0
    total_steps_verified = 0
    total_client_only_steps = 0
    total_truncated_steps = 0
    total_detail_stripped_steps = 0

    tiers_out: dict[str, Any] = {}
    primary_hard_oc_recs: list[dict[str, Any]] = []
    primary_hard_sol_recs: list[dict[str, Any]] = []

    for tier in ("medium", "hard"):
        specs = PRIMARY_COHORT_SPECS[tier]
        cohort_recs: dict[str, list[dict[str, Any]]] = {}
        cohort_meta: dict[str, dict[str, Any]] = {}
        cohort_order = [str(sp["key"]) for sp in specs]

        for sp in specs:
            key = str(sp["key"])
            agent = str(sp["agent"])
            mode = str(sp["mode"])
            rel_paths = list(sp["paths"])
            if mode == "cached":
                by_seed_raw, shas = load_cached_episodes(
                    root, rel_paths, tier, agent, set(PRIMARY_SEEDS)
                )
                if sorted(by_seed_raw.keys()) != PRIMARY_SEEDS:
                    raise ValueError(
                        f"incomplete primary 0..29 seeds for {tier}/{key}: {sorted(by_seed_raw.keys())}"
                    )
                total_cached_episodes_replayed += len(by_seed_raw)
                recs = [replay_and_diagnose_episode(by_seed_raw[sd]) for sd in PRIMARY_SEEDS]
            else:
                shas = ["deterministic_inproc"]
                recs = run_and_diagnose_inproc_baseline(tier, agent, PRIMARY_SEEDS)
                total_inproc_baseline_replayed += len(recs)

            for diag in recs:
                total_episodes_replayed += 1
                total_steps_verified += int(diag["steps_verified"])
                total_client_only_steps += int(diag["steps_client_only"])
                total_truncated_steps += int(diag["steps_truncated_checked"])
                total_detail_stripped_steps += int(diag["steps_detail_stripped"])

            cohort_recs[key] = recs
            cohort_meta[key] = {
                "agent": agent,
                "kind": str(sp["kind"]),
                "label": str(sp["label"]),
                "mode": mode,
                "paths": rel_paths,
                "git_shas": shas,
            }

        if tier == "hard":
            primary_hard_oc_recs = cohort_recs["opencode_carbon"]
            primary_hard_sol_recs = cohort_recs["solver"]

        solver_by_seed = {int(r["seed"]): r for r in cohort_recs["solver"]}
        cohorts_summary: dict[str, Any] = {}
        per_seed_atlas: dict[str, Any] = {}
        outcomes_by_cohort: dict[str, Any] = {}

        for key in cohort_order:
            recs = cohort_recs[key]
            sub = summarize_cohort_subset(recs, solver_by_seed)
            shown_gap = [float(r["shown_v"]) - float(r["true_v"]) for r in recs]
            sub.update(
                {
                    "agent": cohort_meta[key]["agent"],
                    "kind": cohort_meta[key]["kind"],
                    "label": cohort_meta[key]["label"],
                    "mode": cohort_meta[key]["mode"],
                    "paths": cohort_meta[key]["paths"],
                    "git_shas": cohort_meta[key]["git_shas"],
                    "mean_true_v": mean_val([float(r["true_v"]) for r in recs]),
                    "mean_shown_v": mean_val([float(r["shown_v"]) for r in recs]),
                    "mean_unsurfaced_v_gap": mean_val(shown_gap),
                    "mean_break_even_p": mean_val([float(r["break_even_p"]) for r in recs]),
                    "mean_canaries_planted": mean_val([float(r["canaries_planted"]) for r in recs]),
                    "mean_interviews": mean_val([float(r["interviews"]) for r in recs]),
                    "mean_surfaced_leaks": mean_val([float(r["surfaced_leaks"]) for r in recs]),
                    "surfaced_flips_total": sum(int(r["surfaced_flips_count"]) for r in recs),
                    "strict_c1_at_end_count": sum(
                        1 for r in recs if int(r["consistent_set_size"]) == 1
                    ),
                    "mole_in_strict_c_count": sum(
                        1 for r in recs if bool(r["mole_in_strict_consistent_set"])
                    ),
                }
            )
            cohorts_summary[key] = sub
            per_seed_atlas[key] = compact_episode_columns(recs)
            outcomes_by_cohort[key] = summarize_outcome_taxonomy(recs)

        tiers_out[tier] = {
            "n_employees": int(TIERS[tier].n_employees),
            "n_days": int(TIERS[tier].n_days),
            "canaries_per_day": int(TIERS[tier].canaries_per_day),
            "fingerprint_accuracy": float(TIERS[tier].fingerprint_accuracy),
            "leak_damage": float(TIERS[tier].leak_damage),
            "cohort_order": cohort_order,
            "cohorts": cohorts_summary,
            "paired_vs_unpaired": build_paired_covariance_proof(cohort_recs, cohort_order),
            "world_stratification": build_world_difficulty_stratification(
                tier, cohort_recs, cohort_order
            ),
            "outcome_taxonomy": outcomes_by_cohort,
            "per_seed": per_seed_atlas,
        }

    ext_f_raw, ext_f_shas = load_cached_episodes(
        root,
        [G1_EXT_FRONTIER_REL],
        "hard",
        "opencode:google/gemini-4-carbon",
        set(G1_EXT_SEEDS),
    )
    if sorted(ext_f_raw.keys()) != G1_EXT_SEEDS:
        raise ValueError(f"expected G1 extension seeds {G1_EXT_SEEDS}, got {sorted(ext_f_raw.keys())}")

    ext_s_all_raw, ext_s_shas = load_cached_episodes(
        root,
        [G1_EXT_SOLVER_REL],
        "hard",
        "solver",
        set(SOLVER_EXT_SEEDS),
    )
    if sorted(ext_s_all_raw.keys()) != SOLVER_EXT_SEEDS:
        raise ValueError("incomplete solver-hard-seeds30to59 reference cache")

    ext_f_recs: list[dict[str, Any]] = []
    ext_s_paired_recs: list[dict[str, Any]] = []
    for sd in G1_EXT_SEEDS:
        df = replay_and_diagnose_episode(ext_f_raw[sd])
        ds = replay_and_diagnose_episode(ext_s_all_raw[sd])
        ext_f_recs.append(df)
        ext_s_paired_recs.append(ds)
        total_episodes_replayed += 2
        total_cached_episodes_replayed += 2
        total_steps_verified += int(df["steps_verified"]) + int(ds["steps_verified"])
        total_client_only_steps += int(df["steps_client_only"]) + int(ds["steps_client_only"])
        total_truncated_steps += int(df["steps_truncated_checked"]) + int(ds["steps_truncated_checked"])
        total_detail_stripped_steps += int(df["steps_detail_stripped"]) + int(ds["steps_detail_stripped"])

    ext_solver_30_59_scores: list[float] = []
    for sd in SOLVER_EXT_SEEDS:
        if sd in G1_EXT_SEEDS:
            ext_solver_30_59_scores.append(
                next(float(r["score"]) for r in ext_s_paired_recs if int(r["seed"]) == sd)
            )
        else:
            sc_only, n_st, n_det = replay_verify_score_only(ext_s_all_raw[sd])
            ext_solver_30_59_scores.append(sc_only)
            total_episodes_replayed += 1
            total_cached_episodes_replayed += 1
            total_steps_verified += n_st
            total_detail_stripped_steps += n_det

    pooled_f = primary_hard_oc_recs + ext_f_recs
    pooled_s = primary_hard_sol_recs + ext_s_paired_recs
    pooled_boot_raw = bootstrap_paired_vs_indep(
        [float(r["score"]) for r in pooled_f],
        [float(r["score"]) for r in pooled_s],
    )
    pooled_boot_la = bootstrap_paired_vs_indep(
        [float(r["luck_adjusted"]) for r in pooled_f],
        [float(r["luck_adjusted"]) for r in pooled_s],
    )

    g1_block = {
        "isolation_note": "Strictly separated from primary post-hoc locked seeds 0-29; never mixed into primary denominators.",
        "prereg_commit": "f9fb7a4a",
        "data_commit": "364fe657",
        "frontier_cache": G1_EXT_FRONTIER_REL,
        "solver_cache": G1_EXT_SOLVER_REL,
        "frontier_git_shas": ext_f_shas,
        "solver_git_shas": ext_s_shas,
        "completed_seeds": G1_EXT_SEEDS,
        "n_completed": len(G1_EXT_SEEDS),
        "ext_2seed_summary": {
            "frontier_raw_mean": mean_val([float(r["score"]) for r in ext_f_recs]),
            "solver_same_2seeds_raw_mean": mean_val([float(r["score"]) for r in ext_s_paired_recs]),
            "raw_ratio": (
                mean_val([float(r["score"]) for r in ext_f_recs])
                / mean_val([float(r["score"]) for r in ext_s_paired_recs])
            ),
            "frontier_luck_adjusted_mean": mean_val([float(r["luck_adjusted"]) for r in ext_f_recs]),
            "solver_same_2seeds_luck_adjusted_mean": mean_val(
                [float(r["luck_adjusted"]) for r in ext_s_paired_recs]
            ),
            "luck_adjusted_ratio": (
                mean_val([float(r["luck_adjusted"]) for r in ext_f_recs])
                / mean_val([float(r["luck_adjusted"]) for r in ext_s_paired_recs])
            ),
            "solver_all_30_59_raw_mean": mean_val(ext_solver_30_59_scores),
        },
        "pooled_32seed_secondary_sensitivity": {
            "n": len(pooled_f),
            "frontier_raw_mean": mean_val([float(r["score"]) for r in pooled_f]),
            "solver_raw_mean": mean_val([float(r["score"]) for r in pooled_s]),
            "raw_ratio": (
                mean_val([float(r["score"]) for r in pooled_f])
                / mean_val([float(r["score"]) for r in pooled_s])
            ),
            "raw_ratio_paired_ci95": pooled_boot_raw["ratio_paired_ci95"],
            "frontier_luck_adjusted_mean": mean_val([float(r["luck_adjusted"]) for r in pooled_f]),
            "solver_luck_adjusted_mean": mean_val([float(r["luck_adjusted"]) for r in pooled_s]),
            "luck_adjusted_ratio": (
                mean_val([float(r["luck_adjusted"]) for r in pooled_f])
                / mean_val([float(r["luck_adjusted"]) for r in pooled_s])
            ),
            "luck_adjusted_ratio_paired_ci95": pooled_boot_la["ratio_paired_ci95"],
        },
        "per_seed": {
            "opencode_carbon_ext": compact_episode_columns(ext_f_recs, include_seed=True),
            "solver_ext_34_37": compact_episode_columns(ext_s_paired_recs, include_seed=True),
        },
    }

    harbor_rehearsal = load_harbor_rehearsal_summary(root)
    h_oc_summary = tiers_out["hard"]["cohorts"]["opencode_carbon"]
    h_g5_summary = tiers_out["hard"]["cohorts"]["opencode_gpt55"]
    h_oc_boot = tiers_out["hard"]["paired_vs_unpaired"]["vs_solver"]["opencode_carbon"]
    h_g5_boot = tiers_out["hard"]["paired_vs_unpaired"]["vs_solver"]["opencode_gpt55"]
    h_g5_tax = tiers_out["hard"]["outcome_taxonomy"]["opencode_gpt55"]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "primary_seeds": "0-29",
        "n_primary_seeds_per_tier": len(PRIMARY_SEEDS),
        "outcome_classes": list(OUTCOME_CLASSES),
        "provenance_and_honesty": {
            "honest_headline_scope_c59ecfd0": {
                "framing_commit": "c59ecfd0",
                "rehearsal_final_commit": harbor_rehearsal["commit"],
                "ceo_correction_commit": harbor_rehearsal["ceo_correction_commit"],
                "gpt55_commit": "ca0a0dc0",
                "gpt55_prereg_commit": "cf394894",
                "gemini4_carbon_mcp_only_dev_0_29": {
                    "raw_ratio": h_oc_summary["raw_ratio_vs_solver"],
                    "raw_ratio_paired_ci95": h_oc_boot["raw"]["bootstrap_10k"]["ratio_paired_ci95"],
                    "luck_adjusted_ratio": h_oc_summary["luck_ratio_vs_solver"],
                    "luck_adjusted_ratio_paired_ci95": h_oc_boot["luck_adjusted"]["bootstrap_10k"]["ratio_paired_ci95"],
                    "scope_note": "MCP-only (13 tools, bash/python3 denied) on post-hoc locked dev seeds 0-29.",
                },
                "gpt55_mcp_only_dev_0_29": {
                    "raw_ratio": h_g5_summary["raw_ratio_vs_solver"],
                    "raw_ratio_paired_ci95": h_g5_boot["raw"]["bootstrap_10k"]["ratio_paired_ci95"],
                    "luck_adjusted_ratio": h_g5_summary["luck_ratio_vs_solver"],
                    "luck_adjusted_ratio_paired_ci95": h_g5_boot["luck_adjusted"]["bootstrap_10k"]["ratio_paired_ci95"],
                    "stopped_without_accuse_seeds": h_g5_tax["stopped_without_accuse_seeds"],
                    "scope_note": (
                        "Pre-registered second frontier family (cf394894 / ca0a0dc0) matches solver (no gap); "
                        "seeds 0 and 17 wrote an accusation in text without calling accuse (score 0.0, valid)."
                    ),
                },
                "harbor_judge_path_rehearsal": harbor_rehearsal,
                "statement": (
                    "The 65% raw / 72% luck-adjusted gap is specific to gemini-4-carbon with MCP tools only on "
                    "dev seeds 0-29; it did not reproduce in the Harbor judge-path rehearsal (93%, 116%, "
                    f"{harbor_rehearsal['runs']['opencode-3']['ratio_pct']}% of oracle across 3 runs in "
                    "results/harbor/rehearsal/TABLE.md, corrected in aa1c679e / 5f9b3297 from the 08:52 partial "
                    "n=7 153% snapshot; full trials on s1-rehearsal-final d0ead011), and gpt-5.5 with MCP tools "
                    "only matches the solver at 101% [79%, 140%]."
                ),
            },
            "panel_fix_a_seed_lock": {
                "classification": "post_hoc_lock_not_preregistered",
                "lock_commit": "671ed96",
                "primary_runs_commit": "8fd4dec",
                "delay_seconds": 28,
                "statement": (
                    "Primary dev seeds 0-29 were locked post-hoc in commit 671ed96 (28 s after 8fd4dec) "
                    "to prevent cherry-picking or silent rerun replacement; they were NOT pre-registered."
                ),
            },
            "solver_reference_20_plus_10_dirs": {
                "medium": [
                    "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
                    "data/runs/committed/v1.4/reference/solver-medium-seeds20to29/episodes.jsonl",
                ],
                "hard": [
                    "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
                    "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
                ],
                "excluded_from_primary": [G1_EXT_SOLVER_REL],
            },
            "hard_access_constraints_w4_noop": {
                "disclosure_ref": "docs/DIFFICULTY.md W4",
                "disclosure_commit": "0dc7d140",
                "access_constraints_flag": True,
                "canary_level": int(TIERS["hard"].canary_level),
                "employee_clearance_range": [1, 3],
                "binds_in_any_episode": False,
                "statement": (
                    "On v1.4 Hard, access_constraints is True, canary_level is 1, and all employee clearances "
                    "are 1..3, so every employee can receive every canary and the rule never binds."
                ),
            },
            "harbor_and_replay_disclosures": {
                "commit_0dc7d140": (
                    "Discloses Harbor container bash/python3 availability vs local headline OpenCode MCP "
                    "(wildcard deny, canary_* allow) harness shape in README.md plus W4 no-op in docs/DIFFICULTY.md."
                ),
                "commit_1bc3e281_panel_fix_d": (
                    "Adds public-state data.detail strings to invalid arguments tool errors and clarifies W1 "
                    "careful-mole wording after committed runs; step-level replay strips data.detail on "
                    "pre-1bc3e281 invalid arguments steps."
                ),
                "commit_cf394894_gpt55_prereg": {
                    "prereg_commit": "cf394894",
                    "data_commit": "ca0a0dc0",
                    "committed_dir_present": (root / "data/runs/committed/v1.4/opencode-gpt-5.5").is_dir(),
                    "n_episodes": h_g5_summary["n"],
                },
            },
            "secret_and_mole_hygiene": {
                "true_mole_employee_ids_emitted": False,
                "employee_id_strings_emitted": False,
                "forbidden_keys_absent": sorted(FORBIDDEN_MOLE_KEYS),
            },
        },
        "replay_verification": {
            "all_episodes_step_replayed": True,
            "total_episodes_replayed": total_episodes_replayed,
            "cached_episodes_replayed": total_cached_episodes_replayed,
            "inproc_baseline_episodes_replayed": total_inproc_baseline_replayed,
            "total_steps_verified": total_steps_verified,
            "client_only_steps_skipped": total_client_only_steps,
            "truncated_steps_byte_checked": total_truncated_steps,
            "pre_1bc3e281_detail_stripped_steps": total_detail_stripped_steps,
            "mismatches": 0,
        },
        "tiers": tiers_out,
        "g1_extension_34_37": g1_block,
    }
    return _clean_json_value(payload)


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "n/a"
    return f"{val * 100.0:.1f}%"


def _fmt_ci_pct(ci: list[float]) -> str:
    return f"[{ci[0] * 100.0:.1f}%, {ci[1] * 100.0:.1f}%]"


def render_markdown(data: dict[str, Any]) -> str:
    rv = data["replay_verification"]
    ph = data["provenance_and_honesty"]
    hs = ph["honest_headline_scope_c59ecfd0"]
    hr_runs = hs["harbor_judge_path_rehearsal"]["runs"]
    med = data["tiers"]["medium"]
    hrd = data["tiers"]["hard"]
    g1 = data["g1_extension_34_37"]

    h_oc_vs = hrd["paired_vs_unpaired"]["vs_solver"]["opencode_carbon"]
    h_g5_vs = hrd["paired_vs_unpaired"]["vs_solver"]["opencode_gpt55"]
    h_ip_vs = hrd["paired_vs_unpaired"]["vs_solver"]["inproc_carbon"]
    h_fl_vs = hrd["paired_vs_unpaired"]["vs_solver"]["opencode_flash"]
    h_gt_vs = hrd["paired_vs_unpaired"]["vs_solver"]["grok_tactics"]
    m_oc_vs = med["paired_vs_unpaired"]["vs_solver"]["opencode_carbon"]
    m_ip_vs = med["paired_vs_unpaired"]["vs_solver"]["inproc_carbon"]
    m_gt_vs = med["paired_vs_unpaired"]["vs_solver"]["grok_tactics"]

    r1 = hr_runs["opencode-1"]
    r2 = hr_runs["opencode-2"]
    r3 = hr_runs["opencode-3"]
    if "ratio_ci95_pct" in r3:
        r3_ci_lo, r3_ci_hi = r3["ratio_ci95_pct"]
        r3_clause = (
            f"`{r3['mean']:+.3f}` (`{r3['ratio_pct']}%` `[{r3_ci_lo}%, {r3_ci_hi}%]` of same-task oracle, "
            f"`n = {r3['n_valid']}` valid, `{r3['infra_excluded']}` infra-excluded; corrected in `aa1c679e` / `5f9b3297` "
            f"from the `08:52` partial `n = {r3['snapshot_0852_n_valid']}` `{r3['snapshot_0852_mean']:+.3f}` / "
            f"`{r3['snapshot_0852_ratio_pct']}%` snapshot, full trials on `s1-rehearsal-final` `d0ead011`)"
        )
    else:
        r3_clause = (
            f"`{r3['mean']:+.3f}` (`{r3['ratio_pct']}%` of same-task oracle `{r3['oracle_same_tasks']:+.3f}`, "
            f"partial `n = {r3['n_valid']}`)"
        )
    h_win = hrd["world_stratification"]["by_winnability"]["winnable_solver_gt_0"]["cohorts"]
    h_nonwin = hrd["world_stratification"]["by_winnability"]["non_winnable_solver_le_0"]["cohorts"]
    m_win = med["world_stratification"]["by_winnability"]["winnable_solver_gt_0"]["cohorts"]

    lines: list[str] = [
        H1 + "Canary v1.4 Paired-Seed Diagnostics, Covariance Proof & World-Difficulty Atlas",
        "",
        "**Honest headline framing (`c59ecfd0` / `ca0a0dc0` / `aa1c679e` / `5f9b3297`):** "
        f"(1) On `v1.4` Hard with **MCP tools only** on post-hoc locked dev `seeds 0-29` (`n = 30`), `opencode:google/gemini-4-carbon` scores `{hrd['cohorts']['opencode_carbon']['raw_mean']:+.3f}` vs `solver` `{hrd['cohorts']['solver']['raw_mean']:+.3f}` = **`{_fmt_pct(hs['gemini4_carbon_mcp_only_dev_0_29']['raw_ratio'])}` `{_fmt_ci_pct(hs['gemini4_carbon_mcp_only_dev_0_29']['raw_ratio_paired_ci95'])}` raw** (`65% [24%, 98%]`) and **`{_fmt_pct(hs['gemini4_carbon_mcp_only_dev_0_29']['luck_adjusted_ratio'])}` `{_fmt_ci_pct(hs['gemini4_carbon_mcp_only_dev_0_29']['luck_adjusted_ratio_paired_ci95'])}` luck-adjusted** (`72% [52%, 91%]`). "
        f"(2) In the **Harbor judge-path rehearsal** (`results/harbor/rehearsal/TABLE.md`, tag `afterquery-final` `1bc3e281`, where the container also provides `bash`/`python3` and carries the 15 Nov updates), **that gap did not reproduce**: three runs on hard judge tasks `900000-900009` (`{hs['harbor_judge_path_rehearsal']['valid_gemini_accusations_correct']}` valid Gemini accusations correct) scored `{r1['mean']:+.3f}` (`{r1['ratio_pct']}%` of oracle `{r1['oracle_same_tasks']:+.3f}`, `n = {r1['n_valid']}`), `{r2['mean']:+.3f}` (`{r2['ratio_pct']}%`, `n = {r2['n_valid']}`), and {r3_clause}, while `do_nothing` and `stop_early` scored `{hr_runs['do_nothing']['mean']:+.3f}` (`10/10`). "
        f"(3) The pre-registered second frontier family **`opencode:openai/gpt-5.5`** (`cf394894` / `ca0a0dc0`, MCP tools only, dev `seeds 0-29`, `n = 30`) **matches the solver at `{_fmt_pct(hs['gpt55_mcp_only_dev_0_29']['raw_ratio'])}` `{_fmt_ci_pct(hs['gpt55_mcp_only_dev_0_29']['raw_ratio_paired_ci95'])}` raw** (`101% [79%, 140%]`, `{hrd['cohorts']['opencode_gpt55']['raw_mean']:+.3f}`) and **`{_fmt_pct(hs['gpt55_mcp_only_dev_0_29']['luck_adjusted_ratio'])}` `{_fmt_ci_pct(hs['gpt55_mcp_only_dev_0_29']['luck_adjusted_ratio_paired_ci95'])}` luck-adjusted** (`84% [67%, 103%]`, `28/28` accusations correct; seeds `{hs['gpt55_mcp_only_dev_0_29']['stopped_without_accuse_seeds']}` announced an accusation in text without calling `accuse` and scored `0.000`). "
        "Frontier agents on `v1.4` Hard therefore land near the reference overall; this atlas diagnoses both frontier families (`gemini-4-carbon` and `gpt-5.5`) side-by-side against `solver` on every seed `0..29`.",
        "",
        "**Reproduce and verify (<10 s, 0 API calls, 0 keys):**",
        "",
        "```bash",
        "/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py",
        "/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/paired_seed_diagnostics_v14.py --check",
        "```",
        "",
        H2 + "1. Scope, Replay Integrity & Panel Fix A/D Disclosures",
        "",
        f"- **100% step-level `Env(tier, seed)` replay (`1bc3e281` compatible):** Verified `{rv['total_episodes_replayed']}` total episodes (`{rv['cached_episodes_replayed']}` committed JSONL episodes + `{rv['inproc_baseline_episodes_replayed']}` deterministic `grok_tactics` episodes) and `{rv['total_steps_verified']}` tool-call steps (`{rv['pre_1bc3e281_detail_stripped_steps']}` pre-`1bc3e281` `invalid arguments` steps normalized for `data.detail`, `{rv['truncated_steps_byte_checked']}` truncated MCP responses byte-verified, `{rv['mismatches']}` mismatches).",
        "- **Post-hoc seed lock (`671ed96`) vs pre-registered runs (`cf394894`, `f9fb7a4a`):** Primary `seeds 0-29` (`n = 30` per tier) is a **post-hoc lock** committed in `671ed96` **28 seconds after** the primary Gemini runs landed in `8fd4dec` (preventing reruns or cherry-picking, **not** a pre-registration). By contrast, `opencode:openai/gpt-5.5` on Hard `seeds 0-29` (`cf394894` before `ca0a0dc0`), the G1 `30-59` extension (`f9fb7a4a` before `364fe657`), and the Harbor judge rehearsal (`results/harbor/rehearsal/README.md` before `c59ecfd0`) were pre-registered prior to episode execution.",
        "- **`20 + 10` reference solver directories (`0..29` strict filter):** Primary `SolverPolicy` baselines load `solver-{medium,hard}-20261114-121126` (`0..19`) plus `solver-{medium,hard}-seeds20to29` (`20..29`), strictly excluding `solver-hard-seeds30to59` so `30..59` never enters any primary `0..29` denominator.",
        "- **Hard `access_constraints` W4 no-op & `0dc7d140` / `1bc3e281` disclosures:** On `v1.4` Hard (`N = 40`), `access_constraints = True`, `canary_level = 1`, and staff clearances span `1..3`, so every staff member qualifies for every canary and the clearance constraint never binds (`docs/DIFFICULTY.md` W4, `0dc7d140`, which also discloses Harbor `bash`/`python3` vs local OpenCode MCP `*`: `deny`, `canary_*`: `allow`). Commit `1bc3e281` (Panel Fix D) added public-only `data.detail` strings to `invalid arguments` errors and reworded the careful-mole `W1` sentence after the committed Gemini runs (`opencode:openai/gpt-5.5` ran on `afterquery-final` `1bc3e281` under OpenCode `1.19.5`).",
        "- **Zero secret or staff-ID leakage:** Neither this report nor `results/eval_v14/paired_seed_diagnostics_v14.json` emits any culprit/staff identifier strings or forbidden culprit keys; every per-episode diagnostic uses boolean indicators (`correct`, `accused_present`, `mole_in_strict_consistent_set`), integer cardinalities (`consistent_set_size`), and calibrated probabilities (`p_accused`, `p_top`, `break_even_p`).",
        "",
        H2 + "2. Cohort Summary Across Paired Seeds `0..29` (`n = 30` per Cohort)",
        "",
        "| Tier | Cohort | Raw Mean | Luck-Adj Mean | Raw / Solver | Luck-Adj / Solver | Acc. | Accused | Mean Acc. Day | Mean `P(acc)` | Mean `P*` | Mean `V_true` (`V_shown`) | Mean Canaries | Mean Interviews | `|C|=1` | Surfaced Flips |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|",
    ]

    for tier in ("hard", "medium"):
        t_blk = data["tiers"][tier]
        for key in t_blk["cohort_order"]:
            c = t_blk["cohorts"][key]
            p_acc_s = f"{c['mean_p_accused']:.3f}" if c["mean_p_accused"] is not None else "n/a"
            acc_d_s = f"{c['mean_accuse_day']:.1f}" if c["mean_accuse_day"] is not None else "n/a"
            r_rat = "100.0% (ref)" if key == "solver" else _fmt_pct(c["raw_ratio_vs_solver"])
            l_rat = "100.0% (ref)" if key == "solver" else _fmt_pct(c["luck_ratio_vs_solver"])
            lines.append(
                f"| `{tier}` | `{key}` | `{c['raw_mean']:+.3f}` | `{c['luck_adjusted_mean']:+.3f}` | "
                f"`{r_rat}` | `{l_rat}` | `{c['accuracy']:.3f}` | `{c['accused_rate']:.2f}` | `{acc_d_s}` | "
                f"`{p_acc_s}` | `{c['mean_break_even_p']:.3f}` | "
                f"`{c['mean_true_v']:.3f}` (`{c['mean_shown_v']:.3f}`) | `{c['mean_canaries_planted']:.2f}` | "
                f"`{c['mean_interviews']:.1f}` | `{c['strict_c1_at_end_count']}/30` | `{c['surfaced_flips_total']}` |"
            )

    lines.extend(
        [
            "",
            f"- **Decision-level contrast (`gemini-4-carbon` vs `gpt-5.5` vs `solver` on Hard `0..29`, matching `results/behaviour_compare_v1.4.md`):** With the exact same 13 MCP tools, `opencode_gpt55` plants `{hrd['cohorts']['opencode_gpt55']['mean_canaries_planted']:.2f}` accepted canaries per episode (`17.2` total `plant_canary` calls), runs `{hrd['cohorts']['opencode_gpt55']['mean_interviews']:.1f}` accepted interviews (`4.2` calls, `6%` of calls), isolates `|C| = 1` on `{hrd['cohorts']['opencode_gpt55']['strict_c1_at_end_count']}/30` seeds, and accuses at mean day `{hrd['cohorts']['opencode_gpt55']['mean_accuse_day']:.2f}` with `0` wrong accusations (`28/28`), matching `solver` (`{hrd['cohorts']['solver']['mean_canaries_planted']:.2f}` canaries, `0.0` interviews, day `{hrd['cohorts']['solver']['mean_accuse_day']:.1f}`). By contrast, `opencode_carbon` plants `{hrd['cohorts']['opencode_carbon']['mean_canaries_planted']:.2f}` accepted canaries (`8.5` calls), spends `{hrd['cohorts']['opencode_carbon']['mean_interviews']:.1f}` accepted interviews (`68.0` calls, `53%` of calls at stated LR `1.2`), accuses later at day `{hrd['cohorts']['opencode_carbon']['mean_accuse_day']:.1f}`, and incurs `4` wrong accusations (`-1.0` each).",
            "",
            H2 + "3. Paired vs Unpaired Variance, Covariance & 10,000-Resample Bootstrap CI Proof",
            "",
            "For frontier score `F_s` and solver score `S_s` on seed `s in {0..29}`, `Var(F - S) = Var(F) + Var(S) - 2 Cov(F, S)`. Positive world-difficulty covariance `Cov(F_s, S_s) > 0` makes `SE_paired < SE_unpaired`, while Rao-Blackwell luck-adjustment (`P * V - (1 - P)`) removes independent accusation coin-flip variance.",
            "",
            "| Tier | Cohort vs Solver | Metric | `r` (Pearson) | `rho` (Spearman) | `Cov(F, S)` | `SE_unp` | `SE_prd` | `SE_unp / SE_prd` | Ratio 95% CI (Unpaired -> Paired) | Ratio Width Reduction | Combined `SE_raw_unp / SE_luck_prd` |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|",
        ]
    )

    cov_rows = (
        ("hard", "opencode_carbon", h_oc_vs),
        ("hard", "opencode_gpt55", h_g5_vs),
        ("hard", "inproc_carbon", h_ip_vs),
        ("hard", "opencode_flash", h_fl_vs),
        ("hard", "grok_tactics", h_gt_vs),
        ("medium", "opencode_carbon", m_oc_vs),
        ("medium", "inproc_carbon", m_ip_vs),
        ("medium", "grok_tactics", m_gt_vs),
    )
    for tier, key, vs_d in cov_rows:
        comb = vs_d["combined_tightening_raw_unpaired_to_luck_paired"]
        for m_lbl, m_key in (("raw", "raw"), ("luck_adj", "luck_adjusted")):
            md = vs_d[m_key]
            b = md["bootstrap_10k"]
            comb_str = f"`{comb['se_reduction_factor']:.3f}x` (`{comb['var_reduction_factor']:.2f}x` var)" if m_key == "luck_adjusted" else "--"
            lines.append(
                f"| `{tier}` | `{key}` | `{m_lbl}` | `{md['pearson_r']:+.3f}` | `{md['spearman_rho']:+.3f}` | "
                f"`{md['cov_fs']:+.4f}` | `{md['se_unpaired']:.4f}` | `{md['se_paired']:.4f}` | "
                f"`{md['se_reduction_factor']:.3f}x` | "
                f"`{_fmt_ci_pct(b['ratio_unpaired_ci95'])} -> {_fmt_ci_pct(b['ratio_paired_ci95'])}` | "
                f"`{b['ratio_width_reduction']:.3f}x` | {comb_str} |"
            )

    lines.extend(
        [
            "",
            f"- **Why MCP-only Hard `opencode_carbon` CIs tighten by `{h_oc_vs['combined_tightening_raw_unpaired_to_luck_paired']['se_reduction_factor']:.3f}x` in SE (`{h_oc_vs['combined_tightening_raw_unpaired_to_luck_paired']['var_reduction_factor']:.2f}x` in variance):** Unpaired raw `SE(F - S)` is `{h_oc_vs['raw']['se_unpaired']:.4f}`. Pairing on `0..29` captures `Pearson r = {h_oc_vs['raw']['pearson_r']:+.3f}` (`Cov = {h_oc_vs['raw']['cov_fs']:+.4f}`), reducing raw SE by `{h_oc_vs['raw']['se_reduction_factor']:.3f}x` to `{h_oc_vs['raw']['se_paired']:.4f}`. Applying Rao-Blackwell luck-adjustment strips conditional Bernoulli coin-flip noise and raises paired correlation to `r = {h_oc_vs['luck_adjusted']['pearson_r']:+.3f}` (`SE_unpaired / SE_paired = {h_oc_vs['luck_adjusted']['se_reduction_factor']:.3f}x`), tightening SE all the way to `{h_oc_vs['luck_adjusted']['se_paired']:.4f}` and shrinking the 10,000-resample ratio 95% CI width from `{h_oc_vs['raw']['bootstrap_10k']['ratio_unpaired_width'] * 100.0:.1f}` pp (unpaired raw) to `{h_oc_vs['luck_adjusted']['bootstrap_10k']['ratio_paired_width'] * 100.0:.1f}` pp (paired luck-adjusted, `{h_oc_vs['combined_tightening_raw_unpaired_to_luck_paired']['ratio_boot_ci_width_reduction']:.2f}x` narrower).",
            f"- **Second frontier family `opencode_gpt55` covariance & precision (`100.9%` `[78.6%, 140.3%]` raw, `83.7%` `[66.5%, 103.1%]` luck-adjusted):** `opencode_gpt55` has much lower per-seed raw variance (`Var = {h_g5_vs['raw']['var_frontier']:.4f}`) than `solver` (`Var = {h_g5_vs['raw']['var_solver']:.4f}`) because `gpt-5.5` incurred `0` wrong accusations while `solver` suffered one `-1.000` 5% flip on seed `15`. Because `gpt-5.5` won on seed `15` (`{hrd['per_seed']['opencode_gpt55']['score'][15]:+.3f}`) and stopped without calling `accuse` (`0.000`) on seeds `0` and `17` where `solver` scored `{hrd['per_seed']['solver']['score'][0]:+.3f}` and `{hrd['per_seed']['solver']['score'][17]:+.3f}`, raw `Cov(F, S) = {h_g5_vs['raw']['cov_fs']:+.4f}` (`Spearman rho = {h_g5_vs['raw']['spearman_rho']:+.3f}`); under luck-adjustment, `Cov(F, S)` moves to `{h_g5_vs['luck_adjusted']['cov_fs']:+.4f}` (`rho = {h_g5_vs['luck_adjusted']['spearman_rho']:+.3f}`), tightening `SE` by `{h_g5_vs['combined_tightening_raw_unpaired_to_luck_paired']['se_reduction_factor']:.3f}x` (`{h_g5_vs['raw']['se_unpaired']:.4f} -> {h_g5_vs['luck_adjusted']['se_paired']:.4f}`) and narrowing the ratio 95% CI width by `{h_g5_vs['combined_tightening_raw_unpaired_to_luck_paired']['ratio_boot_ci_width_reduction']:.2f}x` (`{h_g5_vs['raw']['bootstrap_10k']['ratio_unpaired_width'] * 100.0:.1f}` pp -> `{h_g5_vs['luck_adjusted']['bootstrap_10k']['ratio_paired_width'] * 100.0:.1f}` pp).",
            f"- **Why `inproc_carbon` and `opencode_flash` show slightly negative raw covariance (`{h_ip_vs['raw']['cov_fs']:+.4f}`, `{h_fl_vs['raw']['cov_fs']:+.4f}`) that disappears under luck-adjustment (`{h_ip_vs['luck_adjusted']['cov_fs']:+.4f}`, `{h_fl_vs['luck_adjusted']['cov_fs']:+.4f}`):** On Hard seed `15`, `solver` hit a 5% canary variant flip (`score = {h_nonwin['solver']['raw']:+.3f}`, `luck_adjusted = {h_nonwin['solver']['la']:+.3f}`) while `inproc_carbon` (`{h_nonwin['inproc_carbon']['raw']:+.3f}`) and `opencode_flash` (`{h_nonwin['opencode_flash']['raw']:+.3f}`) did not flip. Replacing realized coin flips with posterior expectations restores positive/neutral world-difficulty covariance.",
            "",
            H2 + "4. World-Difficulty Stratification (`30` Hard Worlds & `30` Medium Worlds)",
            "",
            H3 + "4.1 Solver Isolation-Day Tertiles (`fast_t1`, `mid_t2`, `slow_t3`, `10` Worlds Each)",
            "",
            "| Tier | Stratum (`n = 10`) | Seeds | Solver Raw (LA) | `opencode_carbon` Raw (LA) | `opencode_gpt55` Raw (LA) | `inproc_carbon` Raw (LA) | `opencode_flash` Raw (LA) | `grok_tactics` Raw (LA) |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )

    for tier in ("hard", "medium"):
        strat = data["tiers"][tier]["world_stratification"]["by_solver_isolation_tertile"]
        for t_name in ("fast_t1", "mid_t2", "slow_t3"):
            sb = strat[t_name]
            ch = sb["cohorts"]
            g5_cell = (
                f"`{ch['opencode_gpt55']['raw']:+.3f}` (`{ch['opencode_gpt55']['la']:+.3f}`)"
                if "opencode_gpt55" in ch
                else "n/a"
            )
            fl_cell = (
                f"`{ch['opencode_flash']['raw']:+.3f}` (`{ch['opencode_flash']['la']:+.3f}`)"
                if "opencode_flash" in ch
                else "n/a"
            )
            sds_s = ",".join(str(s) for s in sb["seeds"])
            lines.append(
                f"| `{tier}` | `{t_name}` | `{sds_s}` | "
                f"`{ch['solver']['raw']:+.3f}` (`{ch['solver']['la']:+.3f}`) | "
                f"`{ch['opencode_carbon']['raw']:+.3f}` (`{ch['opencode_carbon']['la']:+.3f}`) | "
                f"{g5_cell} | "
                f"`{ch['inproc_carbon']['raw']:+.3f}` (`{ch['inproc_carbon']['la']:+.3f}`) | "
                f"{fl_cell} | "
                f"`{ch['grok_tactics']['raw']:+.3f}` (`{ch['grok_tactics']['la']:+.3f}`) |"
            )

    lines.extend(
        [
            "",
            H3 + "4.2 Exogenous Regular-Doc Leak Rate, Hard 5%-Flip Worlds & Winnability (`solver > 0` vs `solver <= 0`)",
            "",
            "| Tier | Stratification Axis | Stratum (`n`) | Solver Raw (LA) | `opencode_carbon` Raw /LA (`% Solver LA`) | `opencode_gpt55` Raw /LA (`% Solver LA`) | `inproc_carbon` Raw /LA (`% Solver LA`) | `opencode_flash` Raw /LA (`% Solver LA`) |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )

    def _fmt_strat_cell(c_sub: dict[str, Any]) -> str:
        return (
            f"`{c_sub['raw']:+.3f}` / `{c_sub['la']:+.3f}` "
            f"(`{_fmt_pct(c_sub['la_ratio'])}`)"
        )

    for tier in ("hard", "medium"):
        ws = data["tiers"][tier]["world_stratification"]
        axis_blocks: list[tuple[str, str, dict[str, Any]]] = [
            ("Intrinsic regular leak rate", "low_leak_half", ws["by_intrinsic_regular_leak_rate"]["low_leak_half"]),
            ("Intrinsic regular leak rate", "high_leak_half", ws["by_intrinsic_regular_leak_rate"]["high_leak_half"]),
            ("Winnability", "winnable_solver_gt_0", ws["by_winnability"]["winnable_solver_gt_0"]),
            ("Winnability", "non_winnable_solver_le_0", ws["by_winnability"]["non_winnable_solver_le_0"]),
        ]
        if tier == "hard":
            axis_blocks.extend(
                [
                    ("5% flip (solver world)", "solver_flip_worlds", ws["by_5pct_flip_occurrence"]["solver_flip_worlds"]),
                    ("5% flip (solver world)", "solver_no_flip_worlds", ws["by_5pct_flip_occurrence"]["solver_no_flip_worlds"]),
                    ("5% flip (any cohort)", "any_cohort_flip_worlds", ws["by_5pct_flip_occurrence"]["any_cohort_flip_worlds"]),
                    ("5% flip (any cohort)", "zero_cohort_flip_worlds", ws["by_5pct_flip_occurrence"]["zero_cohort_flip_worlds"]),
                ]
            )
        for ax_lbl, st_name, sb in axis_blocks:
            ch = sb["cohorts"]
            g5_s = _fmt_strat_cell(ch["opencode_gpt55"]) if "opencode_gpt55" in ch else "n/a"
            fl_s = _fmt_strat_cell(ch["opencode_flash"]) if "opencode_flash" in ch else "n/a"
            lines.append(
                f"| `{tier}` | {ax_lbl} | `{st_name}` (`n={sb['n_seeds']}`) | "
                f"`{ch['solver']['raw']:+.3f}` (`{ch['solver']['la']:+.3f}`) | "
                f"{_fmt_strat_cell(ch['opencode_carbon'])} | {g5_s} | {_fmt_strat_cell(ch['inproc_carbon'])} | {fl_s} |"
            )

    lines.extend(
        [
            "",
            f"- **Non-winnable seed reconciliation (`solver <= 0`):** On Hard, only seed `15` has `solver <= 0` (`solver` suffered a 5% canary flip and scored `{h_nonwin['solver']['raw']:+.3f}`, `luck_adjusted = {h_nonwin['solver']['la']:+.3f}`); excluding seed `15` (`winnable_n = 29`) moves raw ratios to `{_fmt_pct(h_win['opencode_carbon']['raw_ratio'])}` (`opencode_carbon`), `{_fmt_pct(h_win['opencode_gpt55']['raw_ratio'])}` (`opencode_gpt55`), `{_fmt_pct(h_win['inproc_carbon']['raw_ratio'])}` (`inproc_carbon`), and `{_fmt_pct(h_win['opencode_flash']['raw_ratio'])}` (`opencode_flash`), aligning raw ratios closely with 30-seed luck-adjusted ratios (`{_fmt_pct(hrd['cohorts']['opencode_carbon']['luck_ratio_vs_solver'])}`, `{_fmt_pct(hrd['cohorts']['opencode_gpt55']['luck_ratio_vs_solver'])}`, `{_fmt_pct(hrd['cohorts']['inproc_carbon']['luck_ratio_vs_solver'])}`, `{_fmt_pct(hrd['cohorts']['opencode_flash']['luck_ratio_vs_solver'])}`). On Medium, `solver <= 0` occurs on seeds `[20, 21, 29]` where `solver` conservatively abstained (`0.000`); on the `27` winnable seeds `opencode_carbon` scores `{_fmt_pct(m_win['opencode_carbon']['raw_ratio'])}` of `solver` raw (`{_fmt_pct(med['cohorts']['opencode_carbon']['luck_ratio_vs_solver'])}` 30-seed luck-adjusted).",
            "",
            H2 + "5. Complete Episode Outcome Taxonomy Across Cohorts (`n = 30` per Cohort)",
            "",
            "| Tier | Cohort | `isolated_c1_win` | `unresolved_lucky_win` | `sub_breakeven_gamble_win` | `sub_breakeven_gamble_loss` | `5pct_flip_singleton_trap` | `unresolved_premature_loss` | `horizon_abstain` |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for tier in ("hard", "medium"):
        t_blk = data["tiers"][tier]
        for key in t_blk["cohort_order"]:
            tx = t_blk["outcome_taxonomy"][key]
            cts = tx["counts"]
            c0_n = len(tx["c0_noisy_bayes_recovery_seeds"])
            sw_n = len(tx.get("stopped_without_accuse_seeds") or [])
            iso_cell = f"`{cts['isolated_c1_win']}` (`{c0_n}` `|C|=0`)" if c0_n > 0 else f"`{cts['isolated_c1_win']}`"
            abs_cell = f"`{cts['horizon_abstain']}` (`{sw_n}` no-call)" if sw_n > 0 else f"`{cts['horizon_abstain']}`"
            lines.append(
                f"| `{tier}` | `{key}` | {iso_cell} | `{cts['unresolved_lucky_win']}` | "
                f"`{cts['sub_breakeven_gamble_win']}` | `{cts['sub_breakeven_gamble_loss']}` | "
                f"`{cts['5pct_flip_singleton_trap']}` | `{cts['unresolved_premature_loss']}` | {abs_cell} |"
            )

    lines.extend(
        [
            "",
            "- **Key taxonomy highlights (Hard `0..29`):**",
            "  - `opencode_carbon` (`25` wins, `4` losses, `1` abstain): `18` `isolated_c1_win`, `5` `unresolved_lucky_win` (`seeds [3, 7, 8, 14, 20]`), `2` `sub_breakeven_gamble_win` (`seeds [5, 23]` at `P = 0.510 < P* = 0.862` and `P = 0.452 < P* = 0.813`), `1` `sub_breakeven_gamble_loss` (`seed [18]` at `P = 0.627 < P* = 0.685`), `2` `5pct_flip_singleton_trap` (`seeds [1, 26]` at `P = 0.988, 0.950`), `1` `unresolved_premature_loss` (`seed [15]` at `|C| = 2, P = 0.805 >= P* = 0.592`), and `1` `horizon_abstain` (`seed [11]`). Total `|C| >= 2` accusations = `9/29`, matching `docs/DIFFICULTY.md`.",
            "  - `opencode_gpt55` (`28` wins, `0` losses, `2` no-accusation stops): `23` `isolated_c1_win` (including noisy-Bayes recovery from a 5% canary flip on `seed [18]` at `|C| = 0, P = 1.000 >= P* = 0.676`), `4` `unresolved_lucky_win` (`seeds [7, 16, 21, 23]` at `P = 0.740..0.884 > P*`), `1` `sub_breakeven_gamble_win` (`seed [5]` at `P = 0.664 < P* = 0.709`), `0` wrong accusations across all `30` seeds, and `2` no-accusation episodes (`seeds [0, 17]`, stopped at days `8` and `9` with `|C| = 1` containing the true culprit after writing an accusation in text without calling `accuse`, scoring `0.000` as valid per `ca0a0dc0`).",
            "  - `inproc_carbon` (`28` wins, `1` loss, `1` abstain): recovers from 5% canary flips via noisy-Bayes likelihood tracking on `seed [3]` (`|C| = 0, P = 0.985 >= P* = 0.629`, `isolated_c1_win`) and `seed [5]` (`|C| = 0, P = 0.901 < P* = 0.909` at `V = 0.10`, classified under `sub_breakeven_gamble_win` alongside `seed [22]`), suffers `1` `sub_breakeven_gamble_loss` (`seed [6]`), and abstains on `seed [26]` after a flip.",
            "  - `opencode_flash` (`27` wins, `3` losses, `0` abstains): `7` `sub_breakeven_gamble_win` (`seeds [0, 2, 3, 17, 18, 23, 27]`) + `3` `sub_breakeven_gamble_loss` (`seeds [10, 21, 26]`) = `10/30` negative-EV horizon gambles, explaining why its `74.7%` raw ratio collapses to `22.0%` luck-adjusted.",
            "",
            H2 + "6. Separate G1 Pre-Registered Extension Diagnostic Block (`seeds [34, 37]`)",
            "",
            f"Pre-registered in `f9fb7a4a` (data committed in `364fe657`, stopped early after `2` completed valid episodes to preserve shared Gemini rehearsal quota) and paired against `{g1['solver_cache']}` without ever mixing into primary `0..29`:",
            "",
            "| Seed | Cohort | Score | Luck-Adj | Correct | Accused | `|C|` | Culprit in `C` | `P(acc)` | `P(top)` | `P*` | `V_true` (`V_shown`) | Day | Canaries | Interviews | Surfaced Leaks (Flips) | Outcome Class |",
            "|---:|---|---:|---:|---|---|---:|---|---:|---:|---:|---|---:|---:|---:|---|---:|",
        ]
    )

    outcome_names = data["outcome_classes"]
    for c_key, c_lbl in (
        ("opencode_carbon_ext", "opencode:gemini-4-carbon (ext)"),
        ("solver_ext_34_37", "solver (seeds30to59)"),
    ):
        cols = g1["per_seed"][c_key]
        for idx, sd in enumerate(cols["seed"]):
            pa = f"{cols['p_accused'][idx]:.3f}" if cols["p_accused"][idx] is not None else "n/a"
            pt = f"{cols['p_top'][idx]:.3f}" if cols["p_top"][idx] is not None else "n/a"
            ocls = outcome_names[cols["outcome_idx"][idx]]
            corr_s = "true" if cols["correct"][idx] else "false"
            acc_s = "true" if cols["accused"][idx] else "false"
            inc_s = "true" if cols["mole_in_c"][idx] else "false"
            lines.append(
                f"| `{sd}` | {c_lbl} | `{cols['score'][idx]:+.2f}` | `{cols['la'][idx]:+.3f}` | "
                f"`{corr_s}` | `{acc_s}` | "
                f"`{cols['c_size'][idx]}` | `{inc_s}` | "
                f"`{pa}` | `{pt}` | `{cols['break_even_p'][idx]:.3f}` | "
                f"`{cols['true_v'][idx]:.2f}` (`{cols['shown_v'][idx]:.2f}`) | `{cols['final_day'][idx]}` | "
                f"`{cols['canaries'][idx]}` | `{cols['interviews'][idx]}` | "
                f"`{cols['leaks'][idx]}` (`{cols['flips'][idx]}`) | `{ocls}` |"
            )

    g1_s = g1["ext_2seed_summary"]
    g1_p = g1["pooled_32seed_secondary_sensitivity"]
    lines.extend(
        [
            "",
            f"- **`[34, 37]` 2-seed summary:** OpenCode `gemini-4-carbon` averages `{g1_s['frontier_raw_mean']:+.3f}` raw (`{g1_s['frontier_luck_adjusted_mean']:+.3f}` luck-adjusted) vs paired `solver` `{g1_s['solver_same_2seeds_raw_mean']:+.3f}` raw (`{g1_s['solver_same_2seeds_luck_adjusted_mean']:+.3f}` luck-adjusted; full 30-seed `solver-hard-seeds30to59` raw mean `{g1_s['solver_all_30_59_raw_mean']:+.3f}`). Secondary `n = {g1_p['n']}` pooled (`0..29` + `[34, 37]`) sensitivity is `{_fmt_pct(g1_p['raw_ratio'])}` `{_fmt_ci_pct(g1_p['raw_ratio_paired_ci95'])}` raw and `{_fmt_pct(g1_p['luck_adjusted_ratio'])}` `{_fmt_ci_pct(g1_p['luck_adjusted_ratio_paired_ci95'])}` luck-adjusted.",
            "",
            H2 + "7. Per-Seed Hard Frontier Diagnostic Atlas (`seeds 0..29`, `opencode_carbon` & `opencode_gpt55` vs `solver`)",
            "",
            "| Seed | Tertile | Solver Day (`|C|`) | Solver Score (LA) | Carbon Day (`|C|`, in `C`) | Carbon Score (LA) | Carbon `P(acc)` / `P*` | Carbon Can/Int (Flips) | Carbon Class | GPT-5.5 Day (`|C|`, in `C`) | GPT-5.5 Score (LA) | GPT-5.5 `P(acc)` / `P*` | GPT-5.5 Can/Int (Flips) | GPT-5.5 Class |",
            "|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )

    h_wc = hrd["world_stratification"]["world_columns"]
    h_sol = hrd["per_seed"]["solver"]
    h_oc = hrd["per_seed"]["opencode_carbon"]
    h_g5 = hrd["per_seed"]["opencode_gpt55"]
    for idx in range(30):
        sd = h_wc["seed"][idx]
        tert = h_wc["iso_tertile"][idx]
        s_day = h_sol["final_day"][idx]
        s_c = h_sol["c_size"][idx]
        s_sc = h_sol["score"][idx]
        s_la = h_sol["la"][idx]

        o_day = h_oc["final_day"][idx]
        o_c = h_oc["c_size"][idx]
        o_inc = "Y" if h_oc["mole_in_c"][idx] else "N"
        o_sc = h_oc["score"][idx]
        o_la = h_oc["la"][idx]
        o_pa = f"{h_oc['p_accused'][idx]:.3f}" if h_oc["p_accused"][idx] is not None else "none"
        o_be = h_oc["break_even_p"][idx]
        o_can = h_oc["canaries"][idx]
        o_iv = h_oc["interviews"][idx]
        o_fl = h_oc["flips"][idx]
        o_cls = outcome_names[h_oc["outcome_idx"][idx]]

        g_day = h_g5["final_day"][idx]
        g_c = h_g5["c_size"][idx]
        g_inc = "Y" if h_g5["mole_in_c"][idx] else "N"
        g_sc = h_g5["score"][idx]
        g_la = h_g5["la"][idx]
        g_pa = f"{h_g5['p_accused'][idx]:.3f}" if h_g5["p_accused"][idx] is not None else "none"
        g_be = h_g5["break_even_p"][idx]
        g_can = h_g5["canaries"][idx]
        g_iv = h_g5["interviews"][idx]
        g_fl = h_g5["flips"][idx]
        g_cls = outcome_names[h_g5["outcome_idx"][idx]]

        lines.append(
            f"| `{sd}` | `{tert}` | `d{s_day}` (`{s_c}`) | `{s_sc:+.2f}` (`{s_la:+.3f}`) | "
            f"`d{o_day}` (`{o_c}`,`{o_inc}`) | `{o_sc:+.2f}` (`{o_la:+.3f}`) | `{o_pa}`/`{o_be:.3f}` | `{o_can}`/`{o_iv}` (`{o_fl}`) | `{o_cls}` | "
            f"`d{g_day}` (`{g_c}`,`{g_inc}`) | `{g_sc:+.2f}` (`{g_la:+.3f}`) | `{g_pa}`/`{g_be:.3f}` | `{g_can}`/`{g_iv}` (`{g_fl}`) | `{g_cls}` |"
        )

    lines.append("")
    return _norm_ascii("\n".join(lines))


EXPECTED_INPUTS_SHA256 = "d6768adedeab1047f8fb18c145afee896338cb21609686a17361400838c9678d"
EXPECTED_OUT_JSON_SHA256 = "047f54e65895f18ec51504556945bbe2b1505f77c9c9312b92d5d0b4f535e263"


def _repo_inputs_sha256(root: Path) -> str:
    rels: list[str] = []
    for base in ("data/runs/committed/v1.4", "canary/solver", "results/solver_range"):
        d = root / base
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file() and p.suffix in (".jsonl", ".json", ".py", ".md", ".txt"):
                    rels.append(p.relative_to(root).as_posix())
    for extra in (
        "canary/rules.py",
        "canary/env.py",
        "canary/baselines.py",
        "results/oracle_range_v1.4.json",
        "results/harbor/rehearsal/TABLE.md",
        "results/harbor/rehearsal/BUILD.txt",
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
        description="Deterministic v1.4 paired-seed world-difficulty, covariance, and per-seed diagnostic atlas."
    )
    ap.add_argument("--check", action="store_true", help="Verify committed JSON and Markdown within 1e-9")
    ap.add_argument("--full-check", action="store_true", help="Force full recomputation during --check")
    ap.add_argument("--json-only", action="store_true", help="Write or verify JSON artifact only")
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON, help="Output JSON artifact path")
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD, help="Output Markdown report path")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root path")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    if (
        args.check
        and not args.full_check
        and root == ROOT.resolve()
        and args.out_json.resolve() == DEFAULT_OUT_JSON.resolve()
        and (args.json_only or args.out_md.resolve() == DEFAULT_OUT_MD.resolve())
        and args.out_json.is_file()
        and (args.json_only or args.out_md.is_file())
    ):
        raw_bytes = args.out_json.read_bytes()
        if (
            len(raw_bytes) < MAX_JSON_BYTES
            and hashlib.sha256(raw_bytes).hexdigest() == EXPECTED_OUT_JSON_SHA256
            and _repo_inputs_sha256(root) == EXPECTED_INPUTS_SHA256
        ):
            disk_json_text = raw_bytes.decode("utf-8")
            committed_json = json.loads(disk_json_text)
            disk_errs = scan_text_hygiene(str(args.out_json), disk_json_text)
            disk_errs.extend(_scan_forbidden_keys(committed_json))
            md_ok = True
            if not args.json_only:
                disk_md_text = args.out_md.read_text(encoding="utf-8")
                disk_errs.extend(scan_text_hygiene(str(args.out_md), disk_md_text))
                md_ok = disk_md_text == render_markdown(committed_json)
            if not disk_errs and md_ok:
                print(
                    f"PASS paired_seed_diagnostics_v14 --check "
                    f"({committed_json['replay_verification']['total_episodes_replayed']} episodes, "
                    f"{committed_json['replay_verification']['total_steps_verified']} steps, {len(raw_bytes)} bytes)"
                )
                return 0

    data = compute(root)
    key_errs = _scan_forbidden_keys(data)
    if key_errs:
        for err in key_errs:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1

    json_blob = compact_json_dumps(data)
    json_bytes = len(json_blob.encode("utf-8"))
    if json_bytes >= MAX_JSON_BYTES:
        print(f"[FAIL] JSON size {json_bytes} bytes >= {MAX_JSON_BYTES} byte limit", file=sys.stderr)
        return 1

    fresh = json.loads(json_blob)
    md_blob = render_markdown(fresh)

    hygiene_errs = scan_text_hygiene("fresh_json", json_blob)
    if not args.json_only:
        hygiene_errs.extend(scan_text_hygiene("fresh_md", md_blob))
    if hygiene_errs:
        for err in hygiene_errs:
            print(f"[FAIL] {err}", file=sys.stderr)
        return 1

    if args.check:
        if not args.out_json.is_file():
            print(f"[FAIL] missing JSON artifact: {args.out_json}", file=sys.stderr)
            return 1
        disk_bytes = args.out_json.stat().st_size
        if disk_bytes >= MAX_JSON_BYTES:
            print(f"[FAIL] {args.out_json} size {disk_bytes} bytes >= {MAX_JSON_BYTES} byte limit", file=sys.stderr)
            return 1
        disk_json_text = args.out_json.read_text(encoding="utf-8")
        disk_errs = scan_text_hygiene(str(args.out_json), disk_json_text)
        try:
            committed_json = json.loads(disk_json_text)
        except ValueError as exc:
            print(f"[FAIL] invalid JSON in {args.out_json}: {exc}", file=sys.stderr)
            return 1
        disk_errs.extend(_scan_forbidden_keys(committed_json))
        if disk_errs:
            for err in disk_errs:
                print(f"[FAIL] {err}", file=sys.stderr)
            return 1
        if not approx_equal(committed_json, fresh, tol=FLOAT_TOL):
            print(f"[FAIL] {args.out_json} differs from fresh recomputation beyond tol={FLOAT_TOL}", file=sys.stderr)
            return 1

        if not args.json_only:
            if not args.out_md.is_file():
                print(f"[FAIL] missing Markdown report: {args.out_md}", file=sys.stderr)
                return 1
            disk_md_text = args.out_md.read_text(encoding="utf-8")
            md_errs = scan_text_hygiene(str(args.out_md), disk_md_text)
            if md_errs:
                for err in md_errs:
                    print(f"[FAIL] {err}", file=sys.stderr)
                return 1
            if disk_md_text != md_blob:
                print(f"[FAIL] {args.out_md} differs from fresh deterministic render", file=sys.stderr)
                return 1

        print(
            f"PASS paired_seed_diagnostics_v14 --check "
            f"({fresh['replay_verification']['total_episodes_replayed']} episodes, "
            f"{fresh['replay_verification']['total_steps_verified']} steps, {json_bytes} bytes)"
        )
        return 0

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json_blob, encoding="utf-8")
    print(f"wrote {args.out_json} ({json_bytes} bytes)")
    if not args.json_only:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md_blob, encoding="utf-8")
        print(f"wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
