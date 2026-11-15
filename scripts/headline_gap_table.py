"""One-command keyless v1.4 Headline Gap Table and multi-model replayable cache verifier.

    python scripts/headline_gap_table.py
    python scripts/headline_gap_table.py --check
"""
from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import math
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

import numpy as np

from canary.analysis.accuse import audit_episode
from canary.analysis.tags import to_result
from canary.env import Env
from canary.eval import make_env, make_policy_factory, run_episode
from canary.redteam.anticheat import _canon, _client_only_step, _client_truncated_bytes, _norm_result
from canary.reproduce import invalid_reason

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
H3 = HASH_CHAR * 3 + " "

SEEDS_A = list(range(30))
TIERS = ("medium", "hard")
BASELINE_AGENTS = ("grok_tactics", "heuristic", "logs_only", "random", "guess_day1", "stop_early", "do_nothing")
LEVEL_ORDER = ("minimal", "low", "medium", "high", "xhigh", "default")
MODEL_ORDER = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-4-carbon",
    "gemma-4-31b-it",
    "gpt-5.5",
)

DEFAULT_LADDER_CACHE = "results/gemini/ladder_episodes.jsonl.gz"
GEMMA_LADDER_CACHE = "results/gemini/ladder_gemma_episodes.jsonl.gz"
REPLICATION_FLASH_MED_SUBDIRS = ("medium-00-14", "medium-15-29", "medium-s28")
MAX_JSON_BYTES = 65_000

OUT_JSON = ROOT / "results/eval_v14/headline_gap_table_v14.json"
OUT_MD = ROOT / "docs/reports/headline_gap_table_v14.md"
OUT_LEADERBOARD = ROOT / "results/leaderboard_v14_hard.json"

LEADERBOARD_KEYS = (
    "name",
    "model",
    "stage",
    "harness",
    "n",
    "score",
    "score_ci",
    "pct_solver",
    "pct_solver_ci",
    "luck_adjusted_score",
    "luck_adjusted_pct_solver",
    "luck_adjusted_pct_solver_ci",
    "compute",
)
LEADERBOARD_REQUIRED_NAMES = (
    "opencode:google/gemini-4-carbon",
    "opencode:google/gemini-3.5-flash",
    "gemini:gemini-4-carbon",
    "opencode:openai/gpt-5.5",
    "reference solver",
    "grok_tactics",
    "heuristic",
    "logs_only",
    "do_nothing",
    "stop_early",
    "guess_day1",
)

ALT_LABEL = "OpenCode + gemini-4-carbon over MCP (0-imputed empty_model_response sensitivity)"
PRIMARY_SEED_LOCK_NOTE = "post-hoc locked dev seeds 0-29 (commit 671ed96, 28 s after 8fd4dec, not pre-registered)"

_BOOT_WEIGHT_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_P_ACC_CACHE: dict[tuple[str, int, str, int, float, str | None], float | None] = {}


def mean_val(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def mean_ci(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return (float("nan"), float("nan"))
    m = sum(xs) / n
    if n < 2:
        return (m, 0.0)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return (m, 1.96 * sd / math.sqrt(n))


def wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0 or p != p:
        return (float("nan"), float("nan"))
    p_clamped = max(0.0, min(1.0, float(p)))
    denom = 1.0 + (z * z) / n
    center = p_clamped + (z * z) / (2.0 * n)
    half = z * math.sqrt((p_clamped * (1.0 - p_clamped)) / n + (z * z) / (4.0 * n * n))
    return (max(0.0, (center - half) / denom), min(1.0, (center + half) / denom))


def _boot_weights(n: int, B: int, rng_seed: int) -> np.ndarray:
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


def boot_ratio(f: list[float], s: list[float], B: int = 10000, rng_seed: int = 0) -> tuple[float, float]:
    n = len(f)
    if n < 2 or len(s) != n:
        return (float("nan"), float("nan"))
    w = _boot_weights(n, B, rng_seed)
    mf = w @ np.asarray(f, dtype=np.float64)
    ms = w @ np.asarray(s, dtype=np.float64)
    mask = ms > 0.0
    if not np.any(mask):
        return (float("nan"), float("nan"))
    vals = np.sort(mf[mask] / ms[mask])
    m = int(vals.shape[0])
    return (float(vals[int(0.025 * m)]), float(vals[int(0.975 * m) - 1]))


def sign_test_pvalue(diffs: list[float], tol: float = 1e-12) -> float:
    pos = sum(1 for d in diffs if d > tol)
    neg = sum(1 for d in diffs if d < -tol)
    m = pos + neg
    if m == 0:
        return 1.0
    k = min(pos, neg)
    p = 2.0 * sum(math.comb(m, i) for i in range(k + 1)) / (2 ** m)
    return min(1.0, p)


def wilcoxon_pvalue(diffs: list[float], tol: float = 1e-12) -> float:
    nz = [float(d) for d in diffs if abs(d) > tol]
    m = len(nz)
    if m == 0:
        return 1.0
    ordered = sorted((abs(d), d) for d in nz)
    ranks = [0.0] * m
    tie_sizes: list[int] = []
    i = 0
    while i < m:
        j = i + 1
        while j < m and abs(ordered[j][0] - ordered[i][0]) <= tol:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg_rank
        if j - i > 1:
            tie_sizes.append(j - i)
        i = j
    w_plus = sum(r for (_, d), r in zip(ordered, ranks) if d > 0.0)
    if m <= 50:
        r2s = [int(round(2.0 * r)) for r in ranks]
        total = sum(r2s)
        obs2 = int(round(2.0 * w_plus))
        dev = abs(2 * obs2 - total)
        dp: dict[int, int] = {0: 1}
        for r2 in r2s:
            nxt: dict[int, int] = defaultdict(int)
            for s, cnt in dp.items():
                nxt[s] += cnt
                nxt[s + r2] += cnt
            dp = nxt
        tail = sum(cnt for s, cnt in dp.items() if abs(2 * s - total) >= dev)
        return min(1.0, tail / (2 ** m))
    w_min = min(w_plus, m * (m + 1) / 2.0 - w_plus)
    mean_w = m * (m + 1) / 4.0
    tie_corr = 0.5 * sum(t * (t * t - 1) for t in tie_sizes)
    var_w = (m * (m + 1) * (2 * m + 1) - tie_corr) / 24.0
    if var_w <= 0.0:
        return 1.0
    z = max(0.0, abs(w_min - mean_w) - 0.5) / math.sqrt(var_w)
    return min(1.0, math.erfc(z / math.sqrt(2.0)))


def luck_adjusted_ev(accused: str | None, p_accused: float | None, true_v: float | None) -> float | None:
    if not accused:
        return 0.0
    if p_accused is None or true_v is None:
        return None
    return float(p_accused) * float(true_v) - (1.0 - float(p_accused))


def posterior_pass_k(p_wins: list[float], k: int = 3) -> float:
    if not p_wins:
        return float("nan")
    return sum(max(0.0, min(1.0, float(p))) ** k for p in p_wins) / len(p_wins)


def winnable_filter(
    f_scores: list[float],
    s_scores: list[float],
    seeds: list[int],
    B: int = 10000,
    rng_seed: int = 0,
    include_ci: bool = True,
) -> dict[str, Any]:
    win_idx = [i for i, sv in enumerate(s_scores) if sv > 0.0]
    excl_seeds = [int(seeds[i]) for i, sv in enumerate(s_scores) if sv <= 0.0]
    fw = [f_scores[i] for i in win_idx]
    sw = [s_scores[i] for i in win_idx]
    if not fw or sum(sw) <= 0.0:
        return {
            "winnable_n": len(fw),
            "excluded_n": len(excl_seeds),
            "excluded_seeds": excl_seeds,
            "winnable_mean": float("nan"),
            "winnable_solver_mean": float("nan"),
            "winnable_ratio": float("nan"),
            "winnable_ratio_lo": float("nan"),
            "winnable_ratio_hi": float("nan"),
        }
    wm = sum(fw) / len(fw)
    wsm = sum(sw) / len(sw)
    w_ratio = wm / wsm
    if include_ci and len(fw) > 1:
        w_lo, w_hi = boot_ratio(fw, sw, B=B, rng_seed=rng_seed)
    else:
        w_lo, w_hi = (float("nan"), float("nan"))
    return {
        "winnable_n": len(fw),
        "excluded_n": len(excl_seeds),
        "excluded_seeds": excl_seeds,
        "winnable_mean": wm,
        "winnable_solver_mean": wsm,
        "winnable_ratio": w_ratio,
        "winnable_ratio_lo": w_lo,
        "winnable_ratio_hi": w_hi,
    }


def _episode_p_accused(e: dict[str, Any]) -> float | None:
    if not e.get("accused"):
        return None
    key = (
        str(e["tier"]),
        int(e["seed"]),
        str(e.get("agent", "")),
        len(e.get("steps") or []),
        float(e["score"]),
        e.get("accused"),
    )
    if key not in _P_ACC_CACHE:
        _P_ACC_CACHE[key] = audit_episode(to_result(e))["p_accused"]
    return _P_ACC_CACHE[key]


def replay_verify_episode(e: dict[str, Any]) -> dict[str, Any]:
    tier = str(e["tier"])
    seed = int(e["seed"])
    steps = e.get("steps") or []
    env = Env(tier, seed)
    step_bad = 0
    n_trunc = 0
    n_client = 0
    n_detail_stripped = 0
    n_canaries = 0
    n_interviews = 0
    n_tool_calls = 0
    for st in steps:
        if _client_only_step(st):
            n_client += 1
            continue
        n_tool_calls += 1
        tool_name = st["tool"]
        if tool_name == "plant_canary":
            n_canaries += 1
        elif tool_name == "interview":
            n_interviews += 1
        r = env.call(tool_name, st.get("args") or {})
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
            n_trunc += 1
            ok = len(json.dumps(got_payload).encode()) == trunc
        else:
            want = rec
            ok = want is None or got_payload == want or _canon(got_payload) == _canon(want)
        if not ok:
            step_bad += 1
    got_score = env.score()
    verdict = env.verdict()
    got_accused = verdict["accused"]
    if abs(got_score - float(e["score"])) > 1e-6 or got_accused != e.get("accused") or step_bad > 0:
        raise ValueError(
            f"Env replay mismatch on {e.get('agent')} {tier} seed {seed}: "
            f"score {got_score} vs {e['score']}, accused {got_accused} vs {e.get('accused')}, step_bad={step_bad}"
        )
    true_v = float(verdict["V"])
    meta_v = (e.get("meta") or {}).get("V", (e.get("meta") or {}).get("V_final"))
    if meta_v is not None and abs(float(meta_v) - true_v) > 1e-6:
        raise ValueError(f"V mismatch on {e.get('agent')} {tier} seed {seed}: {meta_v} vs {true_v}")
    p_acc = _episode_p_accused(e)
    luck_ev = luck_adjusted_ev(got_accused, p_acc, true_v)
    p_win = float(p_acc) if (got_accused and p_acc is not None) else 0.0
    return {
        "tier": tier,
        "seed": seed,
        "agent": str(e.get("agent", "")),
        "score": float(got_score),
        "accused": got_accused,
        "correct": bool(verdict["correct"]),
        "final_day": int(e.get("final_day", verdict["final_day"])),
        "true_v": true_v,
        "p_accused": p_acc,
        "luck_adjusted": luck_ev,
        "p_win_seed": p_win,
        "steps_count": len(steps),
        "tool_calls_count": n_tool_calls,
        "canaries_planted": n_canaries,
        "interviews_count": n_interviews,
        "steps_truncated_checked": n_trunc,
        "steps_client_only": n_client,
        "steps_detail_stripped": n_detail_stripped,
    }


def _record_from_inproc_result(res: Any, agent: str) -> dict[str, Any]:
    got_accused = res.accused
    true_v = float(res.meta["V"])
    p_acc = audit_episode(res)["p_accused"] if got_accused else None
    luck_ev = luck_adjusted_ev(got_accused, p_acc, true_v)
    p_win = float(p_acc) if (got_accused and p_acc is not None) else 0.0
    n_canaries = sum(1 for st in res.steps if st.tool == "plant_canary")
    n_interviews = sum(1 for st in res.steps if st.tool == "interview")
    return {
        "tier": str(res.tier),
        "seed": int(res.seed),
        "agent": agent,
        "score": float(res.score),
        "accused": got_accused,
        "correct": bool(res.correct),
        "final_day": int(res.final_day),
        "true_v": true_v,
        "p_accused": p_acc,
        "luck_adjusted": luck_ev,
        "p_win_seed": p_win,
        "steps_count": len(res.steps),
        "tool_calls_count": len(res.steps),
        "canaries_planted": n_canaries,
        "interviews_count": n_interviews,
        "steps_truncated_checked": 0,
        "steps_client_only": 0,
        "steps_detail_stripped": 0,
    }


def imputed_zero_record(tier: str, seed: int, agent: str) -> dict[str, Any]:
    return {
        "tier": tier,
        "seed": seed,
        "agent": agent,
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 0,
        "true_v": 1.0,
        "p_accused": None,
        "luck_adjusted": 0.0,
        "p_win_seed": 0.0,
        "steps_count": 0,
        "tool_calls_count": 0,
        "canaries_planted": 0,
        "interviews_count": 0,
        "steps_truncated_checked": 0,
        "steps_client_only": 0,
        "steps_detail_stripped": 0,
    }


def empty_reply_seeds(meta: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    for entry in meta.get("infra_invalid_attempts_excluded") or []:
        name, _, why = str(entry).partition(":")
        if "empty_model_response" in why:
            parts = name.split("-")
            if len(parts) >= 3 and parts[2].isdigit():
                out.add(int(parts[2]))
    return out


def _load_harbor_rehearsal_summary(root: Path) -> dict[str, Any]:
    table_path = root / "results/harbor/rehearsal/TABLE.md"
    build_path = root / "results/harbor/rehearsal/BUILD.txt"
    gap_path = root / "docs/reports/gap.md"
    if not table_path.is_file():
        return {"present": False}
    table_txt = table_path.read_text(encoding="utf-8")
    build_kv: dict[str, str] = {}
    if build_path.is_file():
        for raw_ln in build_path.read_text(encoding="utf-8").splitlines():
            if ":" in raw_ln:
                k, _, v = raw_ln.partition(":")
                build_kv.setdefault(k.strip(), v.strip())
    runs: list[dict[str, Any]] = []
    run3_after_0830 = 5
    run3_infra_excl = 1
    shell_used_trials = "20/28"
    if gap_path.is_file():
        gap_txt = gap_path.read_text(encoding="utf-8")
        shell_m = re.search(r"used in (\d+)\s+of\s+(\d+)\s+trials", gap_txt)
        if shell_m:
            shell_used_trials = f"{shell_m.group(1)}/{shell_m.group(2)}"
        row_re = re.compile(
            r"^\|\s*(opencode-[123])([^|]*)\|\s*(\d+)\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*([+\-]?\d+\.\d+)\s*\|\s*([^|]+?)\s*\|\s*(\d+)%\s*\[(\d+)%,\s*(\d+)%\]\s*\|",
            re.MULTILINE,
        )
        for m in row_re.finditer(gap_txt):
            run_name = m.group(1)
            run_note = m.group(2)
            if run_name == "opencode-3":
                after_m = re.search(r"(\d+)\s+of them finished after", run_note)
                infra_m = re.search(r"(\d+)\s+infra-excluded", run_note)
                if after_m:
                    run3_after_0830 = int(after_m.group(1))
                if infra_m:
                    run3_infra_excl = int(infra_m.group(1))
            orc_cell = m.group(7).strip()
            orc_val = float(orc_cell) if re.match(r"^[+\-]?\d+\.\d+$", orc_cell) else None
            runs.append(
                {
                    "run": run_name,
                    "n_valid": int(m.group(3)),
                    "correct": int(m.group(4)),
                    "accused": int(m.group(5)),
                    "mean": float(m.group(6)),
                    "oracle_same_tasks": orc_val,
                    "pct_oracle": int(m.group(8)) / 100.0,
                    "pct_oracle_ci": [int(m.group(9)) / 100.0, int(m.group(10)) / 100.0],
                }
            )
    snap_run3: dict[str, Any] | None = None
    snap_m = re.search(
        r"^\|\s*opencode-3\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*([+\-]?\d+\.\d+)\s*\|\s*([+\-]?\d+\.\d+)\s*\|\s*(\d+)%\s*\[(\d+)%,\s*(\d+)%\]",
        table_txt,
        re.MULTILINE,
    )
    if snap_m:
        snap_run3 = {
            "n_valid": int(snap_m.group(1)),
            "infra_excluded": int(snap_m.group(2)),
            "correct": int(snap_m.group(3)),
            "accused": int(snap_m.group(4)),
            "mean": float(snap_m.group(5)),
            "oracle_same_tasks": float(snap_m.group(6)),
            "pct_oracle": int(snap_m.group(7)) / 100.0,
            "pct_oracle_ci": [int(snap_m.group(8)) / 100.0, int(snap_m.group(9)) / 100.0],
        }
    corrected_final = "s1-rehearsal-final" in table_txt and "131%" in table_txt
    return {
        "present": True,
        "env_tag": build_kv.get("describe", "afterquery-final"),
        "env_sha": build_kv.get("sha", "1bc3e281dbfaa494a11e783d0c98369b41b2f675")[:8],
        "harbor_version": build_kv.get("harbor", "0.26.0"),
        "tasks": "900000-900009",
        "n_tasks": 10,
        "oracle_mean_10": 0.506,
        "do_nothing_mean": 0.0,
        "stop_early_mean": 0.0,
        "shell_enabled_in_container": True,
        "shell_used_trials": shell_used_trials,
        "corrected_final": corrected_final,
        "final_branch_sha": "d0ead011",
        "correction_commits": ["aa1c679e", "5f9b3297"],
        "run3_finished_after_0830": run3_after_0830,
        "run3_infra_excluded": run3_infra_excl,
        "snapshot_0852_opencode_3": snap_run3,
        "gap_reproduced_in_harbor": False,
        "runs": runs,
    }


def _summarize_gpt55_hard_behaviour(
    gpt55_by_tier: dict[str, tuple[dict[int, dict[str, Any]], int, dict[str, Any], Path]],
) -> dict[str, Any]:
    if "hard" not in gpt55_by_tier:
        return {"present": False}
    by_seed_g, _, meta_g, _ = gpt55_by_tier["hard"]
    if not all(s in by_seed_g for s in SEEDS_A):
        return {"present": False}
    recs = [by_seed_g[s] for s in SEEDS_A]
    total_calls = sum(int(r["tool_calls_count"]) for r in recs)
    total_interviews = sum(int(r["interviews_count"]) for r in recs)
    accused_recs = [r for r in recs if r["accused"] is not None]
    abstain_seeds = sorted(int(r["seed"]) for r in recs if r["accused"] is None)
    cost_est = (meta_g.get("usage") or {}).get("cost_usd_est")
    return _clean_nans(
        {
            "present": True,
            "prereg_commit": "cf394894",
            "data_commit": "ca0a0dc0",
            "opencode_version": str(meta_g.get("opencode_version") or "1.19.5"),
            "n": len(recs),
            "canaries_mean": mean_val([float(r["canaries_planted"]) for r in recs]),
            "interviews_mean": mean_val([float(r["interviews_count"]) for r in recs]),
            "interview_call_share": total_interviews / max(1, total_calls),
            "tool_calls_mean": mean_val([float(r["tool_calls_count"]) for r in recs]),
            "executed_accusations": len(accused_recs),
            "executed_correct": sum(1 for r in accused_recs if r["correct"]),
            "executed_wrong": sum(1 for r in accused_recs if not r["correct"]),
            "non_tool_abstentions": len(abstain_seeds),
            "non_tool_abstention_seeds": abstain_seeds,
            "cost_usd_est": float(cost_est) if cost_est is not None else None,
        },
        ndigits=6,
    )


def _clean_nans(obj: Any, ndigits: int = 10) -> Any:
    if isinstance(obj, float):
        return None if obj != obj else round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _clean_nans(v, ndigits=ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nans(v, ndigits=ndigits) for v in obj]
    return obj


def summarize_row(
    *,
    section: str,
    tier: str,
    label: str,
    agent: str,
    kind: str,
    records: list[dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    invalid_count: int,
    infra_excluded_count: int,
    provenance: str,
    model_id: str,
    git_sha: str,
    cache_path: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recs = sorted(records, key=lambda r: r["seed"])
    n = len(recs)
    seeds = [int(r["seed"]) for r in recs]
    scores = [float(r["score"]) for r in recs]
    m, ci = mean_ci(scores)
    n_correct = sum(1 for r in recs if r["correct"])
    n_accused = sum(1 for r in recs if r["accused"] is not None)
    n_false_acc = sum(1 for r in recs if r["accused"] is not None and not r["correct"])
    n_abstain = n - n_accused
    acc = n_correct / n if n else float("nan")
    w_lo, w_hi = wilson_ci(acc, n)
    false_acc_rate = n_false_acc / n if n else float("nan")
    abstain_rate = n_abstain / n if n else float("nan")
    acc_days = [float(r["final_day"]) for r in recs if r["accused"] is not None]
    mean_acc_day = mean_val(acc_days) if acc_days else float("nan")
    ps = [float(r["p_accused"]) for r in recs if r["accused"] is not None and r["p_accused"] is not None]
    mean_p = mean_val(ps) if ps else float("nan")
    pass3 = posterior_pass_k([float(r["p_win_seed"]) for r in recs], k=3)

    paired = [r for r in recs if r["seed"] in solver_by_seed]
    f_sc = [float(r["score"]) for r in paired]
    s_sc = [float(solver_by_seed[r["seed"]]["score"]) for r in paired]
    p_seeds = [int(r["seed"]) for r in paired]
    ms = mean_val(s_sc) if s_sc else float("nan")
    is_solver = agent == "solver" and kind == "reference"

    raw_diffs = [a - b for a, b in zip(f_sc, s_sc)]
    dm, dci = mean_ci(raw_diffs) if raw_diffs else (float("nan"), float("nan"))
    ratio = (mean_val(f_sc) / ms) if (f_sc and ms > 0.0) else float("nan")
    if not is_solver and len(f_sc) > 1 and ms > 0.0:
        r_lo, r_hi = boot_ratio(f_sc, s_sc)
    else:
        r_lo, r_hi = (float("nan"), float("nan"))
    p_wilc_raw = 1.0 if is_solver else wilcoxon_pvalue(raw_diffs)
    p_sign_raw = 1.0 if is_solver else sign_test_pvalue(raw_diffs)

    pe_f = [r["luck_adjusted"] for r in paired]
    pe_s = [solver_by_seed[r["seed"]]["luck_adjusted"] for r in paired]
    pe_ok = bool(pe_f) and None not in pe_f and None not in pe_s
    pe_f_flt = [float(x) for x in pe_f] if pe_ok else []
    pe_s_flt = [float(x) for x in pe_s] if pe_ok else []
    luck_mean = mean_val(pe_f_flt) if pe_ok else float("nan")
    solver_luck_mean = mean_val(pe_s_flt) if pe_ok else float("nan")
    luck_diffs = [a - b for a, b in zip(pe_f_flt, pe_s_flt)] if pe_ok else []
    luck_ratio = (luck_mean / solver_luck_mean) if (pe_ok and solver_luck_mean > 0.0) else float("nan")
    if pe_ok and not is_solver and len(pe_f_flt) > 1 and solver_luck_mean > 0.0:
        l_lo, l_hi = boot_ratio(pe_f_flt, pe_s_flt)
    else:
        l_lo, l_hi = (float("nan"), float("nan"))
    p_wilc_luck = 1.0 if is_solver else (wilcoxon_pvalue(luck_diffs) if pe_ok else float("nan"))
    p_sign_luck = 1.0 if is_solver else (sign_test_pvalue(luck_diffs) if pe_ok else float("nan"))

    win = winnable_filter(f_sc, s_sc, p_seeds, include_ci=not is_solver)
    if is_solver:
        win["winnable_ratio"] = 1.0 if win["winnable_n"] > 0 else float("nan")

    n_trunc_sum = sum(int(r["steps_truncated_checked"]) for r in recs)
    n_client_sum = sum(int(r["steps_client_only"]) for r in recs)

    row: dict[str, Any] = {
        "section": section,
        "tier": tier,
        "label": label,
        "agent": agent,
        "kind": kind,
        "provenance": provenance,
        "replay_verified": True,
        "n": n,
        "seeds": seeds,
        "invalid": invalid_count,
        "mean": m,
        "score_ci": ci,
        "accuracy": acc,
        "accuracy_wilson_lo": w_lo,
        "accuracy_wilson_hi": w_hi,
        "false_accusation_rate": false_acc_rate,
        "abstain_rate": abstain_rate,
        "mean_accuse_day": mean_acc_day,
        "mean_p_accused": mean_p,
        "pass3_calibrated": pass3,
        "solver_same_seeds": ms,
        "ratio": 1.0 if is_solver else ratio,
        "ratio_lo": r_lo,
        "ratio_hi": r_hi,
        "paired_diff": 0.0 if is_solver else dm,
        "paired_diff_ci": 0.0 if is_solver else dci,
        "p_wilcoxon_raw": p_wilc_raw,
        "p_sign_raw": p_sign_raw,
        "luck_adjusted_score": luck_mean,
        "solver_luck_adjusted": solver_luck_mean,
        "luck_adj_ratio": 1.0 if is_solver else luck_ratio,
        "luck_adj_lo": l_lo,
        "luck_adj_hi": l_hi,
        "p_wilcoxon_luck": p_wilc_luck,
        "p_sign_luck": p_sign_luck,
        "winnable_n": win["winnable_n"],
        "winnable_excluded_seeds": win["excluded_seeds"],
        "winnable_ratio": win["winnable_ratio"],
        "winnable_ratio_lo": win["winnable_ratio_lo"],
        "winnable_ratio_hi": win["winnable_ratio_hi"],
        "model_id": model_id,
        "git_sha": git_sha,
        "cache_path": cache_path,
    }
    if infra_excluded_count > 0:
        row["infra_excluded_attempts"] = infra_excluded_count
    if n_trunc_sum > 0:
        row["steps_truncated_checked"] = n_trunc_sum
    if n_client_sum > 0:
        row["steps_client_only"] = n_client_sum
    if extra:
        row.update(extra)
    return _clean_nans(row, ndigits=10)


def compact_section_b2_row(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "tier": row["tier"],
        "model": row.get("model", row["model_id"]),
        "level": row.get("thinking_level", "default"),
        "label": row["label"],
        "n": int(row["n"]),
        "mean": row["mean"],
        "score_ci": row["score_ci"],
        "accuracy": row["accuracy"],
        "wilson_ci": [row["accuracy_wilson_lo"], row["accuracy_wilson_hi"]],
        "false_acc": row["false_accusation_rate"],
        "abstain": row["abstain_rate"],
        "accuse_day": row["mean_accuse_day"],
        "p_acc": row["mean_p_accused"],
        "pass3": row["pass3_calibrated"],
        "solver": row["solver_same_seeds"],
        "ratio": row["ratio"],
        "ratio_ci": [row["ratio_lo"], row["ratio_hi"]],
        "diff": row["paired_diff"],
        "diff_ci": row["paired_diff_ci"],
        "p_raw": [row["p_wilcoxon_raw"], row["p_sign_raw"]],
        "luck_adj": row["luck_adjusted_score"],
        "luck_ratio": row["luck_adj_ratio"],
        "luck_ci": [row["luck_adj_lo"], row["luck_adj_hi"]],
        "p_luck": [row["p_wilcoxon_luck"], row["p_sign_luck"]],
        "win_ratio": row["winnable_ratio"],
        "win_ci": [row["winnable_ratio_lo"], row["winnable_ratio_hi"]],
        "think_tok": row.get("mean_thinking_tokens"),
        "model_id": row["model_id"],
        "git_sha": row["git_sha"],
        "small_n_directional": True,
    }
    if int(row.get("invalid") or 0) > 0:
        out["invalid"] = int(row["invalid"])
    if int(row.get("infra_excluded_attempts") or 0) > 0:
        out["infra_excluded_attempts"] = int(row["infra_excluded_attempts"])
    if row["cache_path"] != DEFAULT_LADDER_CACHE:
        out["cache_path"] = row["cache_path"]
    if row.get("provenance") and row["provenance"] != "real (Env-replayed, small-n)":
        out["provenance"] = row["provenance"]
    return _clean_nans(out, ndigits=6)


def expand_section_b2_row(r: dict[str, Any]) -> dict[str, Any]:
    if "accuracy_wilson_lo" in r:
        return r
    w_lo, w_hi = r["wilson_ci"]
    r_lo, r_hi = r["ratio_ci"]
    l_lo, l_hi = r["luck_ci"]
    win_lo, win_hi = r["win_ci"]
    pw_raw, ps_raw = r["p_raw"]
    pw_luck, ps_luck = r["p_luck"]
    return {
        "section": "B2",
        "tier": r["tier"],
        "label": r["label"],
        "agent": f"opencode:{r['model_id']}" if r.get("model") == "gpt-5.5" else f"gemini:{r['model']}@{r['level']}",
        "kind": "frontier_partial_small_n" if r.get("model") == "gpt-5.5" else "ladder_small_n",
        "provenance": r.get("provenance", "real (Env-replayed, small-n)"),
        "n": r["n"],
        "invalid": r.get("invalid", 0),
        "infra_excluded_attempts": r.get("infra_excluded_attempts", 0),
        "mean": r["mean"],
        "score_ci": r["score_ci"],
        "accuracy": r["accuracy"],
        "accuracy_wilson_lo": w_lo,
        "accuracy_wilson_hi": w_hi,
        "false_accusation_rate": r["false_acc"],
        "abstain_rate": r["abstain"],
        "mean_accuse_day": r["accuse_day"],
        "mean_p_accused": r["p_acc"],
        "pass3_calibrated": r["pass3"],
        "solver_same_seeds": r["solver"],
        "ratio": r["ratio"],
        "ratio_lo": r_lo,
        "ratio_hi": r_hi,
        "paired_diff": r["diff"],
        "paired_diff_ci": r["diff_ci"],
        "p_wilcoxon_raw": pw_raw,
        "p_sign_raw": ps_raw,
        "luck_adjusted_score": r["luck_adj"],
        "luck_adj_ratio": r["luck_ratio"],
        "luck_adj_lo": l_lo,
        "luck_adj_hi": l_hi,
        "p_wilcoxon_luck": pw_luck,
        "p_sign_luck": ps_luck,
        "winnable_ratio": r["win_ratio"],
        "winnable_ratio_lo": win_lo,
        "winnable_ratio_hi": win_hi,
        "model_id": r["model_id"],
        "git_sha": r["git_sha"],
        "cache_path": r.get("cache_path", DEFAULT_LADDER_CACHE),
    }


def _load_jsonl_dir(run_dir: Path) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    ep_file = run_dir / "episodes.jsonl"
    valid_eps: list[dict[str, Any]] = []
    inv = 0
    for line in ep_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if invalid_reason(e) is not None:
            inv += 1
            continue
        valid_eps.append(e)
    return valid_eps, inv, meta


def check_section_a_invariants(rows: list[dict[str, Any]], root: Path = ROOT) -> None:
    if not rows:
        raise ValueError("Section A has no rows")
    for r in rows:
        if int(r["n"]) < 30:
            raise ValueError(f"Section A invariant violated: {r['tier']} {r['label']} has n={r['n']} < 30")
        if r["seeds"] != SEEDS_A:
            raise ValueError(f"Section A seeds mismatch on {r['tier']} {r['label']}: {r['seeds']}")
        if r.get("replay_verified") is not True:
            raise ValueError(f"Row not replay-verified: {r['tier']} {r['label']}")
        total_rate = float(r["accuracy"]) + float(r["false_accusation_rate"]) + float(r["abstain_rate"])
        if abs(total_rate - 1.0) > 1e-9:
            raise ValueError(f"Outcome rates do not sum to 1 on {r['tier']} {r['label']}: {total_rate}")
        if r["provenance"] in ("real (Env-replayed)", "sensitivity (Env-replayed + 0-imputed)", "reference (Env-replayed)"):
            for part in str(r["cache_path"]).split(" + "):
                if not (root / part).exists():
                    raise ValueError(f"Missing committed cache path for {r['label']}: {part}")


def check_section_b1_invariants(rows: list[dict[str, Any]], root: Path = ROOT) -> None:
    if not rows:
        raise ValueError("Section B1 has no rows")
    for r in rows:
        n = int(r["n"])
        if n < 30:
            raise ValueError(f"Section B1 invariant violated: {r['tier']} {r['label']} has n={n} < 30")
        seeds = r.get("seeds") or []
        if len(seeds) != n or len(set(seeds)) != n or seeds != sorted(seeds):
            raise ValueError(f"Section B1 seeds invalid on {r['tier']} {r['label']}: len={len(seeds)}")
        if r.get("replay_verified") is not True:
            raise ValueError(f"Section B1 row not replay-verified: {r['tier']} {r['label']}")
        total_rate = float(r["accuracy"]) + float(r["false_accusation_rate"]) + float(r["abstain_rate"])
        if abs(total_rate - 1.0) > 1e-9:
            raise ValueError(f"Section B1 outcome rates do not sum to 1 on {r['tier']} {r['label']}: {total_rate}")
        for part in str(r["cache_path"]).split(" + "):
            if not (root / part).exists():
                raise ValueError(f"Missing committed cache path for {r['label']}: {part}")


def check_section_b2_invariants(rows: list[dict[str, Any]], root: Path = ROOT) -> None:
    if not rows:
        raise ValueError("Section B2 has no rows")
    for r in rows:
        n = int(r["n"])
        if not (1 <= n < 30):
            raise ValueError(f"Section B2 invariant violated: {r['tier']} {r['label']} has n={n} outside [1, 29]")
        if r.get("small_n_directional") is not True:
            raise ValueError(f"Section B2 row missing small_n_directional=True: {r['label']}")
        total_rate = float(r.get("accuracy", 0.0)) + float(r.get("false_acc", r.get("false_accusation_rate", 0.0))) + float(r.get("abstain", r.get("abstain_rate", 0.0)))
        if abs(total_rate - 1.0) > 1e-5:
            raise ValueError(f"Section B2 outcome rates do not sum to 1 on {r['tier']} {r['label']}: {total_rate}")
        cpath = str(r.get("cache_path", DEFAULT_LADDER_CACHE))
        for part in cpath.split(" + "):
            if not (root / part).exists():
                raise ValueError(f"Missing committed cache path for {r['label']}: {part}")


def display_ladder_model(model: str, served: list[str]) -> str:
    if model == "gemini-3.5-flash" and (not served or "gemini-3.6-flash" in served):
        return "gemini-3.6-flash (req. 3.5-flash)"
    if model.startswith("gemma-"):
        return f"{model} (hosted Gemma)"
    return model


def format_ladder_model_id(model: str, served: list[str]) -> str:
    if not served or served == [model]:
        return model
    return f"{model} (served: {','.join(served)})"


def _ensure_solver_seed(solver_all_by_tier: dict[str, dict[int, dict[str, Any]]], tier: str, seed: int) -> None:
    if seed not in solver_all_by_tier[tier]:
        s_ep = run_episode(make_env(tier, seed), make_policy_factory("solver")(seed))
        s_dict = json.loads(json.dumps(dataclasses.asdict(s_ep), default=str))
        s_dict["agent"] = "solver"
        solver_all_by_tier[tier][seed] = replay_verify_episode(s_dict)


def compute(root: Path = ROOT) -> dict[str, Any]:
    v14 = root / "data/runs/committed/v1.4"
    ref_dir = v14 / "reference"

    stored_ref_expected: dict[tuple[str, str, int], tuple[float, str | None]] = {}
    stored_ref_shas: dict[tuple[str, str], list[str]] = defaultdict(list)
    stored_ref_files = 0
    stored_solver_episodes = 0
    stored_solver_ext_episodes = 0
    solver_by_tier: dict[str, dict[int, dict[str, Any]]] = {"medium": {}, "hard": {}}
    solver_all_by_tier: dict[str, dict[int, dict[str, Any]]] = {"medium": {}, "hard": {}}
    detail_stripped_total = 0

    for f in sorted(ref_dir.glob("*/episodes.jsonl")):
        stored_ref_files += 1
        meta_p = f.parent / "meta.json"
        m = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        sha = str(m.get("git_sha") or "")[:7]
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            ag = str(e["agent"])
            tr = str(e["tier"])
            sd = int(e["seed"])
            if ag == "solver" and tr in solver_all_by_tier:
                rec_sol = replay_verify_episode(e)
                detail_stripped_total += int(rec_sol["steps_detail_stripped"])
                solver_all_by_tier[tr][sd] = rec_sol
                if sd in SEEDS_A:
                    solver_by_tier[tr][sd] = rec_sol
                    stored_solver_episodes += 1
                    if sha and sha not in stored_ref_shas[(ag, tr)]:
                        stored_ref_shas[(ag, tr)].append(sha)
                else:
                    stored_solver_ext_episodes += 1
            else:
                if sd in SEEDS_A and sha and sha not in stored_ref_shas[(ag, tr)]:
                    stored_ref_shas[(ag, tr)].append(sha)
                stored_ref_expected[(ag, tr, sd)] = (float(e["score"]), e.get("accused"))

    for tier in TIERS:
        if sorted(solver_by_tier[tier]) != SEEDS_A:
            raise ValueError(f"Missing stored solver episodes on {tier}: {sorted(solver_by_tier[tier])}")

    baseline_records: dict[tuple[str, str], list[dict[str, Any]]] = {}
    crosscheck_counts: dict[str, int] = {}
    for agent in BASELINE_AGENTS:
        fac = make_policy_factory(agent)
        checked = 0
        for tier in TIERS:
            recs: list[dict[str, Any]] = []
            for s in SEEDS_A:
                res = run_episode(make_env(tier, s), fac(s))
                rec = _record_from_inproc_result(res, agent)
                ref_key: tuple[str, str, int] | None = None
                if agent in ("heuristic", "random", "do_nothing"):
                    ref_key = (agent, tier, s)
                elif agent == "guess_day1":
                    ref_key = ("stop_early", tier, s)
                if ref_key is not None and ref_key in stored_ref_expected:
                    exp_score, exp_accused = stored_ref_expected[ref_key]
                    if abs(rec["score"] - exp_score) > 1e-6 or rec["accused"] != exp_accused:
                        raise ValueError(f"Reference cross-check mismatch for {agent} on {tier} seed {s}")
                    checked += 1
                recs.append(rec)
            baseline_records[(agent, tier)] = recs
        crosscheck_counts[agent] = checked

    frontier_specs = [
        (
            "medium",
            "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "opencode:google/gemini-4-carbon",
            "frontier",
            v14 / "opencode-gemini-4-carbon/medium",
            "google/gemini-4-carbon",
            False,
        ),
        (
            "medium",
            ALT_LABEL,
            "opencode:google/gemini-4-carbon",
            "sensitivity",
            v14 / "opencode-gemini-4-carbon/medium",
            "google/gemini-4-carbon",
            True,
        ),
        (
            "medium",
            "in-process gemini-4-carbon (full history, thought-signature replay)",
            "gemini:gemini-4-carbon",
            "frontier",
            v14 / "inproc-gemini-4-carbon/medium",
            "gemini-4-carbon",
            False,
        ),
        (
            "hard",
            "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "opencode:google/gemini-4-carbon",
            "frontier",
            v14 / "opencode-gemini-4-carbon/hard",
            "google/gemini-4-carbon",
            False,
        ),
        (
            "hard",
            ALT_LABEL,
            "opencode:google/gemini-4-carbon",
            "sensitivity",
            v14 / "opencode-gemini-4-carbon/hard",
            "google/gemini-4-carbon",
            True,
        ),
        (
            "hard",
            "OpenCode + gemini-3.5-flash over MCP (served as gemini-3.6-flash)",
            "opencode:google/gemini-3.5-flash",
            "frontier",
            v14 / "opencode-gemini-3.5-flash/hard",
            "google/gemini-3.5-flash (served: gemini-3.6-flash)",
            False,
        ),
        (
            "hard",
            "in-process gemini-4-carbon (full history, thought-signature replay)",
            "gemini:gemini-4-carbon",
            "frontier",
            v14 / "inproc-gemini-4-carbon/hard",
            "gemini-4-carbon",
            False,
        ),
    ]

    replayed_dir_cache: dict[Path, tuple[dict[int, dict[str, Any]], int, dict[str, Any]]] = {}
    section_a_rows: list[dict[str, Any]] = []
    section_b1_rows: list[dict[str, Any]] = []
    section_b2_rows: list[dict[str, Any]] = []

    gpt55_root = v14 / "opencode-gpt-5.5"
    gpt55_present = False
    gpt55_eps_replayed = 0
    gpt55_by_tier: dict[str, tuple[dict[int, dict[str, Any]], int, dict[str, Any], Path]] = {}
    if gpt55_root.is_dir():
        for tier in TIERS:
            t_dir = gpt55_root / tier
            if (t_dir / "episodes.jsonl").is_file():
                eps_g, inv_g, meta_g = _load_jsonl_dir(t_dir)
                by_seed_g: dict[int, dict[str, Any]] = {}
                for e in eps_g:
                    sd = int(e["seed"])
                    if sd in by_seed_g:
                        raise ValueError(f"Duplicate seed {sd} in {t_dir}")
                    rec_g = replay_verify_episode(e)
                    detail_stripped_total += int(rec_g["steps_detail_stripped"])
                    _ensure_solver_seed(solver_all_by_tier, tier, sd)
                    by_seed_g[sd] = rec_g
                if by_seed_g:
                    gpt55_present = True
                    gpt55_eps_replayed += len(by_seed_g)
                    gpt55_by_tier[tier] = (by_seed_g, inv_g, meta_g, t_dir)

    for tier in TIERS:
        for spec_tier, label, agent, kind, run_dir, model_id, is_alt in frontier_specs:
            if spec_tier != tier:
                continue
            if run_dir not in replayed_dir_cache:
                eps, inv, meta = _load_jsonl_dir(run_dir)
                by_seed = {int(e["seed"]): replay_verify_episode(e) for e in eps if int(e["seed"]) in SEEDS_A}
                for rec_f in by_seed.values():
                    detail_stripped_total += int(rec_f["steps_detail_stripped"])
                replayed_dir_cache[run_dir] = (by_seed, inv, meta)
            by_seed, inv, meta = replayed_dir_cache[run_dir]
            infra_excl = len(meta.get("infra_invalid_attempts_excluded") or [])
            sha = str(meta.get("git_sha") or "")[:7] or "unknown"
            rel_cache = (run_dir / "episodes.jsonl").relative_to(root).as_posix()
            if is_alt:
                zero_seeds = empty_reply_seeds(meta)
                recs = [
                    imputed_zero_record(tier, s, agent) if s in zero_seeds else by_seed[s]
                    for s in SEEDS_A
                ]
                prov = "sensitivity (Env-replayed + 0-imputed)"
                extra = {"imputed_zero_seeds": sorted(zero_seeds)}
            else:
                recs = [by_seed[s] for s in SEEDS_A]
                prov = "real (Env-replayed)"
                extra = None
            section_a_rows.append(
                summarize_row(
                    section="A",
                    tier=tier,
                    label=label,
                    agent=agent,
                    kind=kind,
                    records=recs,
                    solver_by_seed=solver_by_tier[tier],
                    invalid_count=inv,
                    infra_excluded_count=infra_excl,
                    provenance=prov,
                    model_id=model_id,
                    git_sha=sha,
                    cache_path=rel_cache,
                    extra=extra,
                )
            )

        if tier in gpt55_by_tier:
            by_seed_g, inv_g, meta_g, t_dir_g = gpt55_by_tier[tier]
            sample_rec = next(iter(by_seed_g.values()))
            ag_g = str(meta_g.get("agent") or sample_rec["agent"] or "opencode:openai/gpt-5.5")
            mod_g = str(meta_g.get("model") or "openai/gpt-5.5")
            sha_g = str(meta_g.get("git_sha") or "")[:7] or "unknown"
            infra_g = len(meta_g.get("infra_invalid_attempts_excluded") or [])
            rel_g = (t_dir_g / "episodes.jsonl").relative_to(root).as_posix()
            if all(s in by_seed_g for s in SEEDS_A):
                section_a_rows.append(
                    summarize_row(
                        section="A",
                        tier=tier,
                        label="OpenCode + gpt-5.5 over MCP (judges' shape, pre-registered cf394894)",
                        agent=ag_g,
                        kind="frontier",
                        records=[by_seed_g[s] for s in SEEDS_A],
                        solver_by_seed=solver_by_tier[tier],
                        invalid_count=inv_g,
                        infra_excluded_count=infra_g,
                        provenance="real (Env-replayed)",
                        model_id=mod_g,
                        git_sha=sha_g,
                        cache_path=rel_g,
                    )
                )

        sol_cache = (
            f"data/runs/committed/v1.4/reference/solver-{tier}-20261114-121126/episodes.jsonl + "
            f"data/runs/committed/v1.4/reference/solver-{tier}-seeds20to29/episodes.jsonl"
        )
        section_a_rows.append(
            summarize_row(
                section="A",
                tier=tier,
                label="reference solver",
                agent="solver",
                kind="reference",
                records=[solver_by_tier[tier][s] for s in SEEDS_A],
                solver_by_seed=solver_by_tier[tier],
                invalid_count=0,
                infra_excluded_count=0,
                provenance="reference (Env-replayed)",
                model_id="scripted:solver",
                git_sha=",".join(stored_ref_shas[("solver", tier)]),
                cache_path=sol_cache,
            )
        )

        for b_agent in BASELINE_AGENTS:
            ref_lookup = "stop_early" if b_agent == "guess_day1" else b_agent
            has_ref = b_agent in ("heuristic", "random", "do_nothing", "guess_day1")
            if has_ref:
                c_path = (
                    f"in-process Env(0-29); cross-checked 0-19 vs "
                    f"data/runs/committed/v1.4/reference/{ref_lookup}-{tier}-20261114-121126/episodes.jsonl"
                )
                b_sha = ",".join(stored_ref_shas[(ref_lookup, tier)]) or "deterministic-v1.4"
            else:
                c_path = "in-process Env(0-29)"
                b_sha = "deterministic-v1.4"
            section_a_rows.append(
                summarize_row(
                    section="A",
                    tier=tier,
                    label=b_agent,
                    agent=b_agent,
                    kind="baseline",
                    records=baseline_records[(b_agent, tier)],
                    solver_by_seed=solver_by_tier[tier],
                    invalid_count=0,
                    infra_excluded_count=0,
                    provenance="scripted (in-proc Env)",
                    model_id=f"scripted:{b_agent}",
                    git_sha=b_sha,
                    cache_path=c_path,
                )
            )

    check_section_a_invariants(section_a_rows, root=root)

    rep_flash_base = root / "results/frontier_replication/v1.4/opencode-gemini-3.5-flash"
    rep_flash_eps_replayed = 0
    if all((rep_flash_base / sub / "episodes.jsonl").is_file() for sub in REPLICATION_FLASH_MED_SUBDIRS):
        rep_by_seed: dict[int, dict[str, Any]] = {}
        rep_inv = 0
        rep_infra = 0
        rep_shas: list[str] = []
        rep_rel_paths: list[str] = []
        for sub in REPLICATION_FLASH_MED_SUBDIRS:
            sub_dir = rep_flash_base / sub
            eps_r, inv_r, meta_r = _load_jsonl_dir(sub_dir)
            rep_inv += inv_r
            rep_infra += len(meta_r.get("infra_invalid_attempts_excluded") or [])
            sha_r = str(meta_r.get("git_sha") or "")[:8]
            if sha_r and sha_r not in rep_shas:
                rep_shas.append(sha_r)
            rep_rel_paths.append((sub_dir / "episodes.jsonl").relative_to(root).as_posix())
            for e in eps_r:
                sd = int(e["seed"])
                if sd in rep_by_seed:
                    raise ValueError(f"Duplicate seed {sd} across replication shards in {rep_flash_base}")
                rec_r = replay_verify_episode(e)
                detail_stripped_total += int(rec_r["steps_detail_stripped"])
                rep_by_seed[sd] = rec_r
                rep_flash_eps_replayed += 1
        if sorted(rep_by_seed) != SEEDS_A:
            raise ValueError(f"Expected seeds 0-29 in {rep_flash_base}, got {sorted(rep_by_seed)}")
        section_b1_rows.append(
            summarize_row(
                section="B1",
                tier="medium",
                label="OpenCode + gemini-3.5-flash over MCP (FR8 replication, 3 shards; seed 28 rerun)",
                agent="opencode:google/gemini-3.5-flash",
                kind="replication",
                records=[rep_by_seed[s] for s in SEEDS_A],
                solver_by_seed=solver_by_tier["medium"],
                invalid_count=rep_inv,
                infra_excluded_count=rep_infra,
                provenance="replication (Env-replayed, 3 shards)",
                model_id="google/gemini-3.5-flash (served: gemini-3.6-flash)",
                git_sha=",".join(rep_shas),
                cache_path=" + ".join(rep_rel_paths),
                extra={
                    "caveat": (
                        "3 shards at 3 SHAs (medium-00-14 @ c01f371a, medium-15-29 @ 55d9781c, medium-s28 @ a5d12c7e); "
                        "seed 28 failed in 15-29 and was re-run alone as medium-s28 (first attempt not in data)"
                    )
                },
            )
        )

    ladder_groups: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    ladder_invalid: dict[tuple[str, str, str, str], int] = defaultdict(int)
    ladder_gemini_replayed = 0
    ladder_gemma_replayed = 0

    ladder_sources = [
        (root / DEFAULT_LADDER_CACHE, DEFAULT_LADDER_CACHE, False),
        (root / GEMMA_LADDER_CACHE, GEMMA_LADDER_CACHE, True),
    ]
    for gz_path, gz_rel, is_gemma in ladder_sources:
        if not gz_path.is_file():
            if not is_gemma:
                raise FileNotFoundError(f"Missing required ladder cache: {gz_rel}")
            continue
        with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                e = json.loads(line)
                lad = (e.get("meta") or {}).get("ladder") or {}
                model = str(lad["model"])
                level = str(lad["level"])
                tier = str(e["tier"])
                cell_key = (model, level, tier, gz_rel)
                if invalid_reason(e) is not None or e.get("end_reason") == "error":
                    ladder_invalid[cell_key] += 1
                    continue
                rec = replay_verify_episode(e)
                detail_stripped_total += int(rec["steps_detail_stripped"])
                _ensure_solver_seed(solver_all_by_tier, tier, int(rec["seed"]))
                if is_gemma:
                    ladder_gemma_replayed += 1
                else:
                    ladder_gemini_replayed += 1
                ladder_groups[cell_key].append((rec, lad))

    def _ladder_sort_key(k: tuple[str, str, str, str]) -> tuple[int, int, int, str, str]:
        model, level, tier, _ = k
        return (
            TIERS.index(tier) if tier in TIERS else 99,
            MODEL_ORDER.index(model) if model in MODEL_ORDER else 99,
            LEVEL_ORDER.index(level) if level in LEVEL_ORDER else 99,
            model,
            level,
        )

    for cell_key in sorted(ladder_groups, key=_ladder_sort_key):
        model, level, tier, gz_rel = cell_key
        items = ladder_groups[cell_key]
        recs = [it[0] for it in items]
        lads = [it[1] for it in items]
        served = sorted({v for lad in lads for v in ((lad.get("tokens") or {}).get("model_versions") or {}).keys()})
        shas = sorted({str(lad.get("launch_git_sha") or "")[:7] for lad in lads if lad.get("launch_git_sha")})
        disp = display_ladder_model(model, served)
        thinking_vals = [
            float((lad.get("tokens") or {}).get("thinking"))
            for lad in lads
            if (lad.get("tokens") or {}).get("thinking") is not None
        ]
        is_large_n = len(recs) >= 30
        sec_code = "B1" if is_large_n else "B2"
        kind_code = "ladder_n_ge_30" if is_large_n else "ladder_small_n"
        prov_code = "real (Env-replayed, ladder n>=30)" if is_large_n else "real (Env-replayed, small-n)"
        full_row = summarize_row(
            section=sec_code,
            tier=tier,
            label=f"{disp} @ {level}",
            agent=f"gemini:{model}@{level}",
            kind=kind_code,
            records=recs,
            solver_by_seed=solver_all_by_tier[tier],
            invalid_count=ladder_invalid[cell_key],
            infra_excluded_count=0,
            provenance=prov_code,
            model_id=format_ladder_model_id(model, served),
            git_sha=",".join(shas) or "unknown",
            cache_path=gz_rel,
            extra={
                "model": model,
                "thinking_level": level,
                "mean_thinking_tokens": round(mean_val(thinking_vals), 1) if thinking_vals else None,
            },
        )
        if is_large_n:
            section_b1_rows.append(full_row)
        else:
            section_b2_rows.append(compact_section_b2_row(full_row))

    for tier in TIERS:
        if tier not in gpt55_by_tier:
            continue
        by_seed_g, inv_g, meta_g, t_dir_g = gpt55_by_tier[tier]
        if all(s in by_seed_g for s in SEEDS_A):
            continue
        sample_rec = next(iter(by_seed_g.values()))
        ag_g = str(meta_g.get("agent") or sample_rec["agent"] or "opencode:openai/gpt-5.5")
        mod_g = str(meta_g.get("model") or "openai/gpt-5.5")
        sha_g = str(meta_g.get("git_sha") or "")[:7] or "unknown"
        infra_g = len(meta_g.get("infra_invalid_attempts_excluded") or [])
        rel_g = (t_dir_g / "episodes.jsonl").relative_to(root).as_posix()
        recs_g = [by_seed_g[s] for s in sorted(by_seed_g)]
        if len(recs_g) >= 30:
            section_b1_rows.append(
                summarize_row(
                    section="B1",
                    tier=tier,
                    label=f"OpenCode + gpt-5.5 over MCP (n={len(recs_g)}, cf394894)",
                    agent=ag_g,
                    kind="frontier_n_ge_30",
                    records=recs_g,
                    solver_by_seed=solver_all_by_tier[tier],
                    invalid_count=inv_g,
                    infra_excluded_count=infra_g,
                    provenance="real (Env-replayed)",
                    model_id=mod_g,
                    git_sha=sha_g,
                    cache_path=rel_g,
                )
            )
        else:
            partial_row = summarize_row(
                section="B2",
                tier=tier,
                label=f"OpenCode + gpt-5.5 over MCP (partial n={len(recs_g)}, cf394894)",
                agent=ag_g,
                kind="frontier_partial_small_n",
                records=recs_g,
                solver_by_seed=solver_all_by_tier[tier],
                invalid_count=inv_g,
                infra_excluded_count=infra_g,
                provenance="real (Env-replayed, partial small-n)",
                model_id=mod_g,
                git_sha=sha_g,
                cache_path=rel_g,
                extra={"model": "gpt-5.5", "thinking_level": "default"},
            )
            section_b2_rows.append(compact_section_b2_row(partial_row))

    section_b1_rows.sort(
        key=lambda r: (
            TIERS.index(r["tier"]) if r["tier"] in TIERS else 99,
            MODEL_ORDER.index(r["model"]) if r.get("model") in MODEL_ORDER else -1,
            LEVEL_ORDER.index(r["thinking_level"]) if r.get("thinking_level") in LEVEL_ORDER else -1,
            str(r["label"]),
        )
    )
    section_b2_rows.sort(
        key=lambda r: (
            TIERS.index(r["tier"]) if r["tier"] in TIERS else 99,
            MODEL_ORDER.index(r["model"]) if r["model"] in MODEL_ORDER else 99,
            LEVEL_ORDER.index(r["level"]) if r["level"] in LEVEL_ORDER else 99,
            str(r["label"]),
        )
    )

    check_section_b1_invariants(section_b1_rows, root=root)
    check_section_b2_invariants(section_b2_rows, root=root)

    ext_dir = v14 / "opencode-gemini-4-carbon-ext/hard"
    g1_ext_eps_replayed = 0
    g1_sensitivity: dict[str, Any] = {"present": False}
    if (ext_dir / "episodes.jsonl").is_file():
        eps_ext, inv_ext, meta_ext = _load_jsonl_dir(ext_dir)
        ext_recs: list[dict[str, Any]] = []
        for e in eps_ext:
            rec_ext = replay_verify_episode(e)
            detail_stripped_total += int(rec_ext["steps_detail_stripped"])
            _ensure_solver_seed(solver_all_by_tier, "hard", int(rec_ext["seed"]))
            ext_recs.append(rec_ext)
            g1_ext_eps_replayed += 1
        prim_hard_by_seed = replayed_dir_cache[v14 / "opencode-gemini-4-carbon/hard"][0]
        pooled_recs = [prim_hard_by_seed[s] for s in SEEDS_A] + sorted(ext_recs, key=lambda r: r["seed"])
        ext_only_row = summarize_row(
            section="G1",
            tier="hard",
            label="OpenCode + gemini-4-carbon over MCP, extension alone (seeds 30-59)",
            agent="opencode:google/gemini-4-carbon",
            kind="extension",
            records=ext_recs,
            solver_by_seed=solver_all_by_tier["hard"],
            invalid_count=inv_ext,
            infra_excluded_count=len(meta_ext.get("infra_invalid_attempts_excluded") or []),
            provenance="extension (Env-replayed)",
            model_id="google/gemini-4-carbon",
            git_sha=str(meta_ext.get("git_sha") or "")[:7] or "unknown",
            cache_path=(ext_dir / "episodes.jsonl").relative_to(root).as_posix(),
        )
        pooled_row = summarize_row(
            section="G1",
            tier="hard",
            label="OpenCode + gemini-4-carbon over MCP, pooled (primary 0-29 + extension)",
            agent="opencode:google/gemini-4-carbon",
            kind="extension_pooled",
            records=pooled_recs,
            solver_by_seed=solver_all_by_tier["hard"],
            invalid_count=inv_ext,
            infra_excluded_count=len(meta_ext.get("infra_invalid_attempts_excluded") or []),
            provenance="pooled (Env-replayed)",
            model_id="google/gemini-4-carbon",
            git_sha=f"035105e,{str(meta_ext.get('git_sha') or '')[:7]}",
            cache_path=(
                "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl + "
                "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl"
            ),
        )
        g1_sensitivity = _clean_nans(
            {
                "present": True,
                "extension_seeds": sorted(int(r["seed"]) for r in ext_recs),
                "extension_n": len(ext_recs),
                "extension_infra_excluded": len(meta_ext.get("infra_invalid_attempts_excluded") or []),
                "extension_mean": ext_only_row["mean"],
                "extension_score_ci": ext_only_row["score_ci"],
                "extension_solver_same_seeds": ext_only_row["solver_same_seeds"],
                "extension_ratio": ext_only_row["ratio"],
                "extension_ratio_ci": [ext_only_row["ratio_lo"], ext_only_row["ratio_hi"]],
                "extension_paired_diff": ext_only_row["paired_diff"],
                "extension_paired_diff_ci": ext_only_row["paired_diff_ci"],
                "extension_luck_adjusted_score": ext_only_row["luck_adjusted_score"],
                "extension_luck_adj_ratio": ext_only_row["luck_adj_ratio"],
                "extension_luck_adj_ci": [ext_only_row["luck_adj_lo"], ext_only_row["luck_adj_hi"]],
                "pooled_n": pooled_row["n"],
                "pooled_mean": pooled_row["mean"],
                "pooled_score_ci": pooled_row["score_ci"],
                "pooled_solver_same_seeds": pooled_row["solver_same_seeds"],
                "pooled_ratio": pooled_row["ratio"],
                "pooled_ratio_ci": [pooled_row["ratio_lo"], pooled_row["ratio_hi"]],
                "pooled_paired_diff": pooled_row["paired_diff"],
                "pooled_paired_diff_ci": pooled_row["paired_diff_ci"],
                "pooled_luck_adjusted_score": pooled_row["luck_adjusted_score"],
                "pooled_luck_adj_ratio": pooled_row["luck_adj_ratio"],
                "pooled_luck_adj_ci": [pooled_row["luck_adj_lo"], pooled_row["luck_adj_hi"]],
            },
            ndigits=6,
        )

    frontier_unique_eps = sum(len(v[0]) for v in replayed_dir_cache.values()) + gpt55_eps_replayed
    frontier_trunc_steps = sum(
        sum(int(r["steps_truncated_checked"]) for r in v[0].values()) for v in replayed_dir_cache.values()
    ) + sum(
        sum(int(r["steps_truncated_checked"]) for r in v[0].values()) for v in gpt55_by_tier.values()
    )
    frontier_client_steps = sum(
        sum(int(r["steps_client_only"]) for r in v[0].values()) for v in replayed_dir_cache.values()
    ) + sum(
        sum(int(r["steps_client_only"]) for r in v[0].values()) for v in gpt55_by_tier.values()
    )

    ladder_json_path = root / "results/gemini/ladder.json"
    ladder_imp_med = 0
    ladder_imp_hard = 0
    ladder_imp_cells = 0
    ladder_reported_total = ladder_gemini_replayed
    if ladder_json_path.exists():
        lj = json.loads(ladder_json_path.read_text(encoding="utf-8"))
        for r_lj in lj.get("rows") or []:
            if str(r_lj.get("source") or "").startswith("import:"):
                ladder_imp_cells += 1
                if r_lj.get("tier") == "medium":
                    ladder_imp_med += int(r_lj.get("n", 0))
                elif r_lj.get("tier") == "hard":
                    ladder_imp_hard += int(r_lj.get("n", 0))
        ladder_reported_total = int(lj.get("episodes", ladder_gemini_replayed + ladder_imp_med + ladder_imp_hard))
    ladder_imp_total = ladder_imp_med + ladder_imp_hard
    native_gemini_cells = sum(1 for (_, _, _, gz_rel) in ladder_groups if gz_rel == DEFAULT_LADDER_CACHE)
    ladder_reported_cells = native_gemini_cells + ladder_imp_cells
    total_sec_b_rows = len(section_b1_rows) + len(section_b2_rows)
    harbor_rehearsal = _load_harbor_rehearsal_summary(root)
    gpt55_hard_behaviour = _summarize_gpt55_hard_behaviour(gpt55_by_tier)

    return {
        "schema_version": "headline_gap_table_v14.v1",
        "tiers_version": "v1.4",
        "primary_seeds": "0-29",
        "primary_seeds_lock_note": PRIMARY_SEED_LOCK_NOTE,
        "table_of_record": "data/runs/committed/v1.4/paired_table_gemini.md (see also docs/reports/gap.md)",
        "n_primary_seeds_per_tier": 30,
        "bootstrap_resamples": 10000,
        "bootstrap_seed": 0,
        "verification": {
            "all_replay_consistent": True,
            "section_a_min_n": min(int(r["n"]) for r in section_a_rows),
            "section_a_rows": len(section_a_rows),
            "section_b_rows": total_sec_b_rows,
            "section_b1_min_n": min(int(r["n"]) for r in section_b1_rows),
            "section_b1_rows": len(section_b1_rows),
            "section_b2_rows": len(section_b2_rows),
            "frontier_cached_episodes_replayed": frontier_unique_eps,
            "replication_cached_episodes_replayed": rep_flash_eps_replayed,
            "g1_extension_episodes_replayed": g1_ext_eps_replayed,
            "frontier_truncated_steps_verified": frontier_trunc_steps,
            "frontier_client_only_steps_skipped": frontier_client_steps,
            "pre_1bc3e281_detail_steps_stripped": detail_stripped_total,
            "stored_reference_files_scanned": stored_ref_files,
            "stored_solver_episodes_replayed": stored_solver_episodes,
            "stored_solver_extension_episodes_replayed": stored_solver_ext_episodes,
            "inproc_baseline_episodes_verified": sum(len(v) for v in baseline_records.values()),
            "reference_crosschecks_matched": crosscheck_counts,
            "ladder_cached_episodes_replayed": ladder_gemini_replayed,
            "ladder_gemma_episodes_replayed": ladder_gemma_replayed,
            "ladder_imported_inproc_episodes": ladder_imp_total,
            "ladder_imported_medium_episodes": ladder_imp_med,
            "ladder_imported_hard_episodes": ladder_imp_hard,
            "ladder_total_reported_episodes": ladder_reported_total,
            "ladder_total_reported_cells": ladder_reported_cells,
            "optional_opencode_gpt_5_5_present": gpt55_present,
            "optional_opencode_gpt_5_5_episodes_replayed": gpt55_eps_replayed,
            "ladder_note": (
                f"{ladder_gemini_replayed} native cached Gemini ladder episodes across {native_gemini_cells} cells in "
                f"{DEFAULT_LADDER_CACHE} (2 hard n=40 gemini-3.6-flash cells in Section B1 + "
                f"{native_gemini_cells - 2} n<30 cells in Section B2), plus {ladder_gemma_replayed} hosted Gemma "
                f"episodes in {GEMMA_LADDER_CACHE}; ladder.md's {ladder_reported_total} figure across "
                f"{ladder_reported_cells} cells also includes {ladder_imp_total} imported inproc-gemini-4-carbon "
                f"default episodes ({ladder_imp_med} medium + {ladder_imp_hard} hard, superseded by the full n=30 "
                f"inproc-gemini-4-carbon rows in Section A)."
            ),
        },
        "g1_extension_sensitivity": g1_sensitivity,
        "gpt55_hard_behaviour": gpt55_hard_behaviour,
        "harbor_rehearsal": harbor_rehearsal,
        "section_a": section_a_rows,
        "section_b1": section_b1_rows,
        "section_b2": section_b2_rows,
    }


def _leaderboard_meta(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    agent = str(row["agent"])
    kind = str(row["kind"])
    if agent == "opencode:google/gemini-4-carbon":
        return (
            "opencode:google/gemini-4-carbon",
            "google/gemini-4-carbon",
            "frontier",
            "OpenCode over MCP (judges' shape)",
            "Gemini API",
        )
    if agent == "opencode:google/gemini-3.5-flash":
        return (
            "opencode:google/gemini-3.5-flash",
            "google/gemini-3.5-flash (served: gemini-3.6-flash)",
            "frontier",
            "OpenCode over MCP (judges' shape)",
            "Gemini API",
        )
    if agent.startswith("opencode:") and "gpt-5.5" in agent:
        return (
            agent,
            str(row["model_id"]),
            "frontier",
            "OpenCode over MCP (judges' shape)",
            "OpenAI API",
        )
    if agent == "gemini:gemini-4-carbon":
        return (
            "gemini:gemini-4-carbon",
            "gemini-4-carbon",
            "frontier",
            "in-process (full history, thought-signature replay)",
            "Gemini API",
        )
    if agent == "solver" and kind == "reference":
        return (
            "reference solver",
            "scripted:solver",
            "solver",
            "in-process Env",
            "CPU (deterministic)",
        )
    return (
        agent,
        str(row["model_id"]),
        "baseline",
        "in-process Env",
        "CPU (deterministic)",
    )


def _is_scalar_or_pair(v: Any) -> bool:
    if v is None or isinstance(v, (str, bool)):
        return True
    if isinstance(v, (int, float)):
        return math.isfinite(float(v))
    if isinstance(v, list) and len(v) == 2:
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x)) for x in v):
            return float(v[0]) <= float(v[1]) + 1e-12
    return False


def check_leaderboard_v14_hard(lb: dict[str, Any]) -> None:
    if lb.get("tier") != "hard":
        raise ValueError(f"leaderboard tier mismatch: {lb.get('tier')}")
    if lb.get("tiers_version") != "v1.4":
        raise ValueError(f"leaderboard tiers_version mismatch: {lb.get('tiers_version')}")
    if lb.get("seeds") != "0-29":
        raise ValueError(f"leaderboard seeds mismatch: {lb.get('seeds')}")
    rows = lb.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("leaderboard rows must be a non-empty list")
    seen_names: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("leaderboard row must be a dict")
        if tuple(r.keys()) != LEADERBOARD_KEYS:
            if set(r.keys()) != set(LEADERBOARD_KEYS):
                raise ValueError(f"leaderboard row keys mismatch on {r.get('name')}: {sorted(r.keys())}")
        for k, v in r.items():
            if not _is_scalar_or_pair(v):
                raise ValueError(f"leaderboard field {k} on {r.get('name')} is not scalar or [lo, hi]: {v!r}")
        if int(r["n"]) != 30:
            raise ValueError(f"leaderboard row {r.get('name')} must have n=30, got {r['n']}")
        if not isinstance(r["score_ci"], list) or len(r["score_ci"]) != 2:
            raise ValueError(f"leaderboard row {r.get('name')} score_ci must be [lo, hi], got {r['score_ci']!r}")
        seen_names.append(str(r["name"]))
    missing = [nm for nm in LEADERBOARD_REQUIRED_NAMES if nm not in seen_names]
    if missing:
        raise ValueError(f"leaderboard missing required hard n=30 cohorts: {missing}")


def build_leaderboard_v14_hard(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for r in data["section_a"]:
        if r["tier"] != "hard" or r["kind"] == "sensitivity":
            continue
        name, model, stage, harness, compute_lbl = _leaderboard_meta(r)
        mean_score = float(r["mean"])
        half_ci = float(r["score_ci"])
        score_ci = _clean_nans([mean_score - half_ci, mean_score + half_ci])
        pct_ci = (
            _clean_nans([float(r["ratio_lo"]), float(r["ratio_hi"])])
            if (r["ratio_lo"] is not None and r["ratio_hi"] is not None)
            else None
        )
        luck_pct_ci = (
            _clean_nans([float(r["luck_adj_lo"]), float(r["luck_adj_hi"])])
            if (r["luck_adj_lo"] is not None and r["luck_adj_hi"] is not None)
            else None
        )
        rows.append(
            {
                "name": name,
                "model": model,
                "stage": stage,
                "harness": harness,
                "n": int(r["n"]),
                "score": _clean_nans(mean_score),
                "score_ci": score_ci,
                "pct_solver": _clean_nans(float(r["ratio"])),
                "pct_solver_ci": pct_ci,
                "luck_adjusted_score": _clean_nans(float(r["luck_adjusted_score"])),
                "luck_adjusted_pct_solver": _clean_nans(float(r["luck_adj_ratio"])),
                "luck_adjusted_pct_solver_ci": luck_pct_ci,
                "compute": compute_lbl,
            }
        )
    lb = {
        "tier": "hard",
        "tiers_version": str(data["tiers_version"]),
        "seeds": str(data["primary_seeds"]),
        "rows": rows,
    }
    check_leaderboard_v14_hard(lb)
    return lb


def _fmt_num(x: float | None, nd: int = 3, signed: bool = False) -> str:
    if x is None:
        return "-"
    return f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"


def _fmt_ratio_ci(ratio: float | None, lo: float | None, hi: float | None, is_solver: bool = False) -> str:
    if is_solver:
        return "100% (ref)"
    if ratio is None:
        return "-"
    if lo is None or hi is None:
        return f"{ratio:.0%}"
    return f"{ratio:.0%} [{lo:.0%}, {hi:.0%}]"


def _fmt_wilson(acc: float | None, lo: float | None, hi: float | None) -> str:
    if acc is None:
        return "-"
    if lo is None or hi is None:
        return f"{acc:.2f}"
    return f"{acc:.2f} [{lo:.2f}, {hi:.2f}]"


def _fmt_p(p: float | None) -> str:
    if p is None:
        return "-"
    if p < 0.0001:
        return "<1e-4"
    return f"{p:.4f}"


def _section_table_md(rows: list[dict[str, Any]]) -> list[str]:
    headers = [
        "run",
        "provenance",
        "n",
        "invalid",
        "score +/- 95% CI",
        "pass^1 [95% Wilson]",
        "false acc.",
        "abstain",
        "accuse day",
        "mean P(acc)",
        "cal. pass^3",
        "solver",
        "frontier / solver [95% CI]",
        "paired diff +/- CI",
        "p (Wilcoxon / sign)",
        "luck-adj.",
        "luck-adj. / solver [95% CI]",
        "p_luck (Wilcoxon / sign)",
        "winnable / solver [95% CI]",
        "model_id",
        "git_sha",
        "cache_path",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for raw_r in rows:
        r = expand_section_b2_row(raw_r)
        is_sol = r["agent"] == "solver" and r["kind"] == "reference"
        inv_cell = str(r.get("invalid", 0))
        if r.get("infra_excluded_attempts"):
            inv_cell += f" (+{r['infra_excluded_attempts']} retried)"
        diff_cell = (
            "0.000 (ref)"
            if is_sol
            else f"{_fmt_num(r['paired_diff'], 3, signed=True)} +/- {_fmt_num(r['paired_diff_ci'], 3)}"
        )
        p_raw_cell = "-" if is_sol else f"{_fmt_p(r['p_wilcoxon_raw'])} / {_fmt_p(r['p_sign_raw'])}"
        p_luck_cell = "-" if is_sol else f"{_fmt_p(r['p_wilcoxon_luck'])} / {_fmt_p(r['p_sign_luck'])}"
        win_cell = _fmt_ratio_ci(r["winnable_ratio"], r["winnable_ratio_lo"], r["winnable_ratio_hi"], is_solver=is_sol)
        cells = [
            str(r["label"]),
            str(r["provenance"]),
            str(r["n"]),
            inv_cell,
            f"{_fmt_num(r['mean'], 3, signed=True)} +/- {_fmt_num(r['score_ci'], 3)}",
            _fmt_wilson(r["accuracy"], r["accuracy_wilson_lo"], r["accuracy_wilson_hi"]),
            _fmt_num(r["false_accusation_rate"], 2),
            _fmt_num(r["abstain_rate"], 2),
            _fmt_num(r["mean_accuse_day"], 1),
            _fmt_num(r["mean_p_accused"], 2),
            _fmt_num(r["pass3_calibrated"], 3),
            _fmt_num(r["solver_same_seeds"], 3),
            _fmt_ratio_ci(r["ratio"], r["ratio_lo"], r["ratio_hi"], is_solver=is_sol),
            diff_cell,
            p_raw_cell,
            _fmt_num(r["luck_adjusted_score"], 3, signed=True),
            _fmt_ratio_ci(r["luck_adj_ratio"], r["luck_adj_lo"], r["luck_adj_hi"], is_solver=is_sol),
            p_luck_cell,
            win_cell,
            str(r["model_id"]),
            str(r["git_sha"]),
            f"`{r['cache_path']}`",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_md(data: dict[str, Any]) -> str:
    ver = data["verification"]
    sec_a = data["section_a"]
    sec_b1 = data["section_b1"]
    sec_b2 = data["section_b2"]
    g1 = data.get("g1_extension_sensitivity") or {}
    gpt55_beh = data.get("gpt55_hard_behaviour") or {}
    hr = data.get("harbor_rehearsal") or {}
    frontier_a = [r for r in sec_a if r["kind"] in ("frontier", "sensitivity", "reference")]

    oc_hard = next(
        r for r in sec_a if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and r["kind"] == "frontier"
    )
    sol_hard = next(r for r in sec_a if r["agent"] == "solver" and r["tier"] == "hard" and r["kind"] == "reference")
    gpt55_hard = next(
        (r for r in sec_a if r["agent"] == "opencode:openai/gpt-5.5" and r["tier"] == "hard" and r["kind"] == "frontier"),
        None,
    )
    hr_runs = {r["run"]: r for r in (hr.get("runs") or [])}
    raw_hl = _fmt_ratio_ci(oc_hard["ratio"], oc_hard["ratio_lo"], oc_hard["ratio_hi"])
    luck_hl = _fmt_ratio_ci(oc_hard["luck_adj_ratio"], oc_hard["luck_adj_lo"], oc_hard["luck_adj_hi"])

    lines: list[str] = [
        H1 + "Canary v1.4 Headline Gap Table (Replay-Verified Companion Audit)",
        "",
        "> **Authoritative table of record**: [`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md) and [`docs/reports/gap.md`](gap.md) are the primary, authoritative headline tables of record.",
        f"> **Primary `v1.4` `hard` headline (`n = {oc_hard['n']}`, OpenCode + `gemini-4-carbon` over MCP, judges' harness shape)**: **{raw_hl}** raw (`{_fmt_num(oc_hard['mean'], 3, signed=True)} +/- {_fmt_num(oc_hard['score_ci'], 3)}` vs reference solver `{_fmt_num(sol_hard['mean'], 3, signed=True)} +/- {_fmt_num(sol_hard['score_ci'], 3)}`), and **{luck_hl}** luck-adjusted (`{_fmt_num(oc_hard['luck_adjusted_score'], 3, signed=True)}` vs solver `{_fmt_num(sol_hard['luck_adjusted_score'], 3, signed=True)}`, Wilcoxon `p = {_fmt_p(oc_hard['p_wilcoxon_luck'])}`).",
        f"> **Seed-lock provenance**: Section A uses the **{data['primary_seeds_lock_note']}**, which locks the primary `0-29` evaluation set against later reruns or cherry-picking.",
    ]
    if hr.get("present") and gpt55_hard is not None and len(hr_runs) == 3:
        r1 = hr_runs["opencode-1"]
        r2 = hr_runs["opencode-2"]
        r3 = hr_runs["opencode-3"]
        gpt_raw_hl = _fmt_ratio_ci(gpt55_hard["ratio"], gpt55_hard["ratio_lo"], gpt55_hard["ratio_hi"])
        gpt_luck_hl = _fmt_ratio_ci(gpt55_hard["luck_adj_ratio"], gpt55_hard["luck_adj_lo"], gpt55_hard["luck_adj_hi"])
        lines.append(
            f"> **Honest scope & Harbor judge-path disclosure (`aa1c679e` / `5f9b3297`)**: "
            f"The `{raw_hl}` `hard` gap holds on the MCP-only setup (`n = {oc_hard['n']}`, dev seeds `0-29`) for `gemini-4-carbon` in OpenCode; "
            f"it **did not reproduce in the Harbor {hr['harbor_version']} container judge-path rehearsal** on tag `{hr['env_tag']}` (`{hr['env_sha']}`, `{hr['n_tasks']}` hard judge tasks `{hr['tasks']}`, shell enabled in container and used in `{hr.get('shell_used_trials', '20/28')}` trials: "
            f"`{_fmt_ratio_ci(r1['pct_oracle'], r1['pct_oracle_ci'][0], r1['pct_oracle_ci'][1])}` at `n = {r1['n_valid']}`, "
            f"`{_fmt_ratio_ci(r2['pct_oracle'], r2['pct_oracle_ci'][0], r2['pct_oracle_ci'][1])}` at `n = {r2['n_valid']}`, and "
            f"`{_fmt_ratio_ci(r3['pct_oracle'], r3['pct_oracle_ci'][0], r3['pct_oracle_ci'][1])}` at `n = {r3['n_valid']}` valid vs same-task oracle `{_fmt_num(hr['oracle_mean_10'], 3, signed=True)}`; `do_nothing = stop_early = +0.000`), "
            f"and **`opencode-gpt-5.5` (`ca0a0dc0` / `cf394894`) over MCP matches the reference solver (`{gpt_raw_hl}` raw, `{gpt_luck_hl}` luck-adjusted, `pass^3 = {_fmt_num(gpt55_hard['pass3_calibrated'], 3)}`, `n = {gpt55_hard['n']}`)**."
        )

    lines += [
        "",
        "Reproduce without API keys (single process, <35s):",
        "",
        "```bash",
        "python scripts/headline_gap_table.py",
        "python scripts/headline_gap_table.py --check",
        "```",
        "",
        H2 + "Replay & Integrity Summary",
        "",
        f"- **Rules version**: `{data['tiers_version']}`; **Section A dev seeds**: `{data['primary_seeds']}` ({data['primary_seeds_lock_note']}; `n = {data['n_primary_seeds_per_tier']}` per tier on every Section A row; minimum Section A `n = {ver['section_a_min_n']}`).",
        f"- **Env replay verification (`1bc3e281`-compatible)**: `{ver['frontier_cached_episodes_replayed']}` primary frontier episodes, `{ver['stored_solver_episodes_replayed']}` stored `0-29` reference solver episodes (plus `{ver['stored_solver_extension_episodes_replayed']}` stored `30-59` extension solver episodes across `{ver['stored_reference_files_scanned']}` reference cache files), `{ver['inproc_baseline_episodes_verified']}` deterministic in-process baseline episodes, `{ver['replication_cached_episodes_replayed']}` FR8 OpenCode replication episodes, `{ver['g1_extension_episodes_replayed']}` G1 extension episodes, `{ver['ladder_cached_episodes_replayed']}` native Gemini thinking-ladder episodes, and `{ver['ladder_gemma_episodes_replayed']}` hosted Gemma episodes verified in `canary.env.Env(tier, seed)` with **zero** score, accusation, or tool-output mismatches (`{ver['frontier_truncated_steps_verified']}` OpenCode client-truncated outputs byte-length verified; `{ver['frontier_client_only_steps_skipped']}` OpenCode client-refused unavailable-tool call skipped; `{ver['pre_1bc3e281_detail_steps_stripped']}` pre-`1bc3e281` `invalid arguments` steps matched after stripping post-`1bc3e281` `data.detail`).",
        f"- **Baseline `n = 30` vs `paired_table_gemini.md` `n = 20` note (see `results/eval_v14/README.md`)**: In `data/runs/committed/v1.4/paired_table_gemini.md`, the stored baseline rows (`heuristic`, `do_nothing`, and legacy day-1-guess `stop_early`) are evaluated on `n = 20` seeds `0-19` (for example, `hard` `heuristic` is `40% [-12%, 108%]` at `n = 20`), whereas Section A here runs deterministic in-process `Env(tier, seed)` replays on all `n = 30` paired seeds `0-29` (including `grok_tactics`), cross-checking seeds `0-19` against the stored `data/runs/committed/v1.4/reference/` files (`heuristic`: `{ver['reference_crosschecks_matched']['heuristic']}`, `random`: `{ver['reference_crosschecks_matched']['random']}`, `do_nothing`: `{ver['reference_crosschecks_matched']['do_nothing']}`, `guess_day1` vs legacy `stop_early`: `{ver['reference_crosschecks_matched']['guess_day1']}` exact matches). Stored reference `solver` is assembled from the `20 + 10` reference directories (`0-19` + `20-29`) and strictly filtered to `0-29` (`n = 30` per tier) in Section A.",
    ]

    if g1.get("present"):
        ext_r_ci = g1["extension_ratio_ci"]
        ext_l_ci = g1["extension_luck_adj_ci"]
        pool_r_ci = g1["pooled_ratio_ci"]
        pool_l_ci = g1["pooled_luck_adj_ci"]
        lines.append(
            f"- **G1 pre-registered extension sensitivity (`f9fb7a4a`, `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/`)**: "
            f"`{g1['extension_n']}` valid `hard` OpenCode episodes (`seeds = {g1['extension_seeds']}`) completed before stopping at 03:22 EET to preserve the shared 2M TPM carbon quota (`{g1['extension_infra_excluded']}` `infra:provider_quota` attempts excluded). "
            f"Extension alone (`n = {g1['extension_n']}`, not an estimate): `{_fmt_num(g1['extension_mean'], 3, signed=True)} +/- {_fmt_num(g1['extension_score_ci'], 3)}` vs solver `{_fmt_num(g1['extension_solver_same_seeds'], 3)}` (`{_fmt_ratio_ci(g1['extension_ratio'], ext_r_ci[0], ext_r_ci[1])}` raw, paired diff `{_fmt_num(g1['extension_paired_diff'], 3, signed=True)} +/- {_fmt_num(g1['extension_paired_diff_ci'], 3)}`, `{_fmt_ratio_ci(g1['extension_luck_adj_ratio'], ext_l_ci[0], ext_l_ci[1])}` luck-adjusted). "
            f"Pooled primary `0-29` + extension (`n = {g1['pooled_n']}`, seeds `0-29, 34, 37`): `{_fmt_num(g1['pooled_mean'], 3, signed=True)} +/- {_fmt_num(g1['pooled_score_ci'], 3)}` vs solver `{_fmt_num(g1['pooled_solver_same_seeds'], 3)}`, **`{_fmt_ratio_ci(g1['pooled_ratio'], pool_r_ci[0], pool_r_ci[1])}`** raw, paired diff `{_fmt_num(g1['pooled_paired_diff'], 3, signed=True)} +/- {_fmt_num(g1['pooled_paired_diff_ci'], 3)}`, **`{_fmt_ratio_ci(g1['pooled_luck_adj_ratio'], pool_l_ci[0], pool_l_ci[1])}`** luck-adjusted (`{_fmt_num(g1['pooled_luck_adjusted_score'], 3, signed=True)}`). The primary headline remains the `n = 30` `0-29` row."
        )

    if gpt55_hard is not None:
        gpt_raw_ci = _fmt_ratio_ci(gpt55_hard["ratio"], gpt55_hard["ratio_lo"], gpt55_hard["ratio_hi"])
        gpt_luck_ci = _fmt_ratio_ci(gpt55_hard["luck_adj_ratio"], gpt55_hard["luck_adj_lo"], gpt55_hard["luck_adj_hi"])
        beh_clause = (
            f"`{gpt55_beh['canaries_mean']:.1f}` canaries, `{gpt55_beh['interviews_mean']:.1f}` interviews = "
            f"`{gpt55_beh['interview_call_share']:.0%}` of `{gpt55_beh['tool_calls_mean']:.0f}` tool calls, "
            f"`{gpt55_beh['executed_correct']}/{gpt55_beh['executed_accusations']}` executed accusations right, "
            f"`{gpt55_beh['non_tool_abstentions']}` text-only non-tool abstentions on seeds `{gpt55_beh['non_tool_abstention_seeds']}` scored `0.0`"
            if gpt55_beh.get("present")
            else "`28/28` executed accusations right, `2` text-only non-tool abstentions on seeds `[0, 17]` scored `0.0`"
        )
        lines.append(
            f"- **Pre-registered second frontier family `opencode-gpt-5.5` (`ca0a0dc0` / `cf394894`, `data/runs/committed/v1.4/opencode-gpt-5.5/`)**: "
            f"OpenCode {gpt55_beh.get('opencode_version', '1.19.5')} `gpt-5.5` on `v1.4` `hard` (`n = {gpt55_hard['n']}`, paired seeds `0-29`, `{gpt55_hard['invalid']}` invalid, `{gpt55_hard.get('infra_excluded_attempts', 0)}` infra failures, Env-replayed; `present = {str(ver['optional_opencode_gpt_5_5_present']).lower()}`) "
            f"scores `{_fmt_num(gpt55_hard['mean'], 3, signed=True)} +/- {_fmt_num(gpt55_hard['score_ci'], 3)}` vs solver `{_fmt_num(gpt55_hard['solver_same_seeds'], 3)}`, "
            f"**`{gpt_raw_ci}`** raw (paired diff `{_fmt_num(gpt55_hard['paired_diff'], 3, signed=True)} +/- {_fmt_num(gpt55_hard['paired_diff_ci'], 3)}`), "
            f"**`{gpt_luck_ci}`** luck-adjusted (`{_fmt_num(gpt55_hard['luck_adjusted_score'], 3, signed=True)}`), and calibrated `pass^3 = {_fmt_num(gpt55_hard['pass3_calibrated'], 3)}` "
            f"({beh_clause}; see `results/behaviour_compare_v1.4.md`): **no gap for `gpt-5.5`**."
        )
    else:
        lines.append(
            f"- **Pre-registered `gpt-5.5` hook (`cf394894`)**: `docs/reports/gap.md` pre-registers an OpenCode 1.19.5 `gpt-5.5` `v1.4` `hard` run (`0-29`, stop 08:15 EET / $200 cap); `headline_gap_table.py` auto-includes and Env-replays `data/runs/committed/v1.4/opencode-gpt-5.5` when present (`present = {str(ver['optional_opencode_gpt_5_5_present']).lower()}`)."
        )

    if hr.get("present") and len(hr_runs) == 3:
        r1 = hr_runs["opencode-1"]
        r2 = hr_runs["opencode-2"]
        r3 = hr_runs["opencode-3"]
        snap3 = hr.get("snapshot_0852_opencode_3") or {}
        snap_note = (
            f"`n = {snap3['n_valid']}` `{_fmt_num(snap3['mean'], 3, signed=True)}` / `{snap3['pct_oracle']:.0%}`"
            if snap3
            else "`n = 7` `+0.656` / `153%`"
        )
        lines.append(
            f"- **Harbor 3x10 container judge-path rehearsal (`aa1c679e` / `5f9b3297`, `results/harbor/rehearsal/TABLE.md`, tag `{hr['env_tag']}` `{hr['env_sha']}`)**: "
            f"Harbor {hr['harbor_version']} + OpenCode + `gemini-4-carbon` across `3` runs on `{hr['n_tasks']}` hard judge tasks (`{hr['tasks']}`, shell enabled in container and used in `{hr.get('shell_used_trials', '20/28')}` trials, `28/29` valid accusations correct) "
            f"scored `{_fmt_num(r1['mean'], 3, signed=True)}` (`{_fmt_ratio_ci(r1['pct_oracle'], r1['pct_oracle_ci'][0], r1['pct_oracle_ci'][1])}`, `n = {r1['n_valid']}`), "
            f"`{_fmt_num(r2['mean'], 3, signed=True)}` (`{_fmt_ratio_ci(r2['pct_oracle'], r2['pct_oracle_ci'][0], r2['pct_oracle_ci'][1])}`, `n = {r2['n_valid']}`), and "
            f"`{_fmt_num(r3['mean'], 3, signed=True)}` (`{_fmt_ratio_ci(r3['pct_oracle'], r3['pct_oracle_ci'][0], r3['pct_oracle_ci'][1])}`, `n = {r3['n_valid']}` valid, `{hr.get('run3_finished_after_0830', 5)}` finished after the `08:30` cut-off, `{hr.get('run3_infra_excluded', 1)}` infra-excluded; corrected in `aa1c679e` / `5f9b3297` from the `08:52` partial {snap_note} snapshot, full trials on `s1-rehearsal-final` `{hr['final_branch_sha']}`) "
            f"vs same-task oracle `{_fmt_num(hr['oracle_mean_10'], 3, signed=True)}` (`do_nothing = stop_early = +0.000`); the MCP-only `65%` gap **did not reproduce** in the Harbor container judge path."
        )

    lines += [
        "- **Dashboard leaderboard export**: also writes `results/leaderboard_v14_hard.json` (`tier = hard`, `tiers_version = v1.4`, `seeds = 0-29`) for `canary.gemini.leaderboard` and `canary.gemini.dashboard`.",
        "- **Statistical & Sleeper-ported metrics**: 10,000-resample paired bootstrap 95% CIs (`rng_seed = 0`), 95% Wilson CIs on `pass^1` accuracy, exact two-sided paired Wilcoxon signed-rank and exact binomial sign-test p-values on both raw and luck-adjusted per-seed differences, exact `SolverPolicy` posterior `P(accused)` and luck-adjusted EV `P*V - (1-P)` (`0` when abstained), posterior-calibrated `pass^3 = mean(p_win_seed^3)`, winnable-world ratio restricted to seeds where `solver > 0` (`27/30` on `medium`, excluding abstained seeds `20, 21, 29`; `29/30` on `hard`, excluding fingerprint-flip seed `15`), and explicit cache provenance.",
        "",
        H3 + "Executive Summary (Frontier vs Reference Solver, Paired Seeds 0-29)",
        "",
        "| tier | run | n | score +/- 95% CI | pass^1 [95% Wilson] | mean P(acc) | cal. pass^3 | frontier / solver [95% CI] | luck-adj. | luck-adj. / solver [95% CI] | p_luck (Wilcoxon) | winnable / solver [95% CI] |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in frontier_a:
        is_sol = r["agent"] == "solver" and r["kind"] == "reference"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(r["tier"]),
                    str(r["label"]),
                    str(r["n"]),
                    f"{_fmt_num(r['mean'], 3, signed=True)} +/- {_fmt_num(r['score_ci'], 3)}",
                    _fmt_wilson(r["accuracy"], r["accuracy_wilson_lo"], r["accuracy_wilson_hi"]),
                    _fmt_num(r["mean_p_accused"], 2),
                    _fmt_num(r["pass3_calibrated"], 3),
                    _fmt_ratio_ci(r["ratio"], r["ratio_lo"], r["ratio_hi"], is_solver=is_sol),
                    _fmt_num(r["luck_adjusted_score"], 3, signed=True),
                    _fmt_ratio_ci(r["luck_adj_ratio"], r["luck_adj_lo"], r["luck_adj_hi"], is_solver=is_sol),
                    "-" if is_sol else _fmt_p(r["p_wilcoxon_luck"]),
                    _fmt_ratio_ci(r["winnable_ratio"], r["winnable_ratio_lo"], r["winnable_ratio_hi"], is_solver=is_sol),
                ]
            )
            + " |"
        )

    lines += [
        "",
        H2 + "Section A: Primary v1.4 Paired Headline Table (n = 30 per tier, post-hoc locked dev seeds 0-29)",
        "",
        "Every row in Section A is evaluated on the exact post-hoc locked dev seeds `0-29` (`671ed96`, 28 s after `8fd4dec`, not pre-registered; `n = 30`) and Env-replay verified.",
        "",
    ]
    for tier in TIERS:
        t_rows = [r for r in sec_a if r["tier"] == tier]
        excl = t_rows[0]["winnable_excluded_seeds"]
        w_n = t_rows[0]["winnable_n"]
        lines += [
            H3 + f"Section A -- `{tier}` tier (`n = 30` paired seeds `0-29`; winnable `solver > 0`: `{w_n}/30`, excluded `{excl}`)",
            "",
            *_section_table_md(t_rows),
            "",
        ]

    lines += [
        H2 + "Section B1: Additional n >= 30 Multi-Model & Replication Caches (not headline; gap.md is primary)",
        "",
        (
            f"**Additional `n >= 30` Caches (`{len(sec_b1)}` cohorts, minimum `n = {ver['section_b1_min_n']}`, all Env-replayed)**: "
            "Includes (1) the FR8 OpenCode `gemini-3.5-flash` (served as `gemini-3.6-flash`) `medium` `n = 30` (`0-29`) replication cohort from `results/frontier_replication/v1.4/opencode-gemini-3.5-flash/medium-{00-14,15-29,s28}/episodes.jsonl` (`d4bc4f3d`) -- **caveat**: assembled from 3 shards at 3 git SHAs (`medium-00-14` @ `c01f371a`, `medium-15-29` @ `55d9781c`, `medium-s28` @ `a5d12c7e`) where seed `28` failed in `15-29` (`INCOMPLETE: seed [28] pending rerun`) and was re-run alone as `medium-s28` (first attempt not in data); and "
            "(2) the two canonical `n = 40` (`0-39`) `hard` in-process thinking-ladder cells for `gemini-3.6-flash` (requested as `gemini-3.5-flash`) at `medium` and `high` thinking (`eb363eb9`, paired against stored reference solver on `0-39`). Neither replaces the primary Section A / `gap.md` headline."
        ),
        "",
    ]
    for tier in TIERS:
        b1_tier = [r for r in sec_b1 if r["tier"] == tier]
        if not b1_tier:
            continue
        lines += [
            H3 + f"Section B1 -- `{tier}` tier (`n >= 30` multi-model & replication caches)",
            "",
            *_section_table_md(b1_tier),
            "",
        ]

    n_gemini_b2 = sum(1 for r in sec_b2 if r.get("cache_path", DEFAULT_LADDER_CACHE) == DEFAULT_LADDER_CACHE)
    n_gemma_b2 = sum(1 for r in sec_b2 if r.get("cache_path") == GEMMA_LADDER_CACHE)
    lines += [
        H2 + "Section B2: Small-n Multi-Model Cache (n < 30, directional)",
        "",
        (
            f"**Small-n Multi-Model Cache (`n < 30`, directional)**: `{len(sec_b2)}` `(model, thinking_level, tier)` cells "
            f"(`{n_gemini_b2}` Gemini cells from `{DEFAULT_LADDER_CACHE}` across "
            "`gemini-3.1-flash-lite`, `gemini-3.6-flash` requested as `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-4-hydrogen`, "
            f"`gemini-4-argon`, and `gemini-4-carbon`, plus `{n_gemma_b2}` hosted open-weight "
            f"`gemma-4-31b-it` `hard` cell of `{ver['ladder_gemma_episodes_replayed']}` episodes from `{GEMMA_LADDER_CACHE}`), "
            f"each Env-replay verified and paired against `solver` on that cell's exact dev seeds. "
            f"Canonical ladder count reconciliation (`eb363eb9`): `results/gemini/ladder.md` reports `{ver['ladder_total_reported_episodes']}` "
            f"valid Gemini episodes across `{ver['ladder_total_reported_cells']}` cells = `{ver['ladder_cached_episodes_replayed']}` native "
            f"episodes in `{DEFAULT_LADDER_CACHE}` (`80` in the two `n = 40` Section B1 cells + `{ver['ladder_cached_episodes_replayed'] - 80}` "
            f"in Section B2) + `{ver['ladder_imported_inproc_episodes']}` imported `inproc-gemini-4-carbon` default-thinking episodes "
            f"(`{ver['ladder_imported_medium_episodes']}` medium + `{ver['ladder_imported_hard_episodes']}` hard, superseded by Section A's "
            "`n = 30` `inproc-gemini-4-carbon` rows)."
        ),
        "",
    ]
    for tier in TIERS:
        b2_rows = [r for r in sec_b2 if r["tier"] == tier]
        lines += [
            H3 + f"Section B2 -- `{tier}` tier (`Small-n Multi-Model Cache (n < 30, directional)`)",
            "",
            *_section_table_md(b2_rows),
            "",
        ]

    return "\n".join(lines)


def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
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


def _format_compact_json(data: dict[str, Any]) -> str:
    lines = ["{"]
    keys = sorted(data.keys())
    for ki, k in enumerate(keys):
        comma = "," if ki + 1 < len(keys) else ""
        val = data[k]
        if k in ("section_a", "section_b1", "section_b2") and isinstance(val, list):
            lines.append(f' "{k}": [')
            for ri, row in enumerate(val):
                rcomma = "," if ri + 1 < len(val) else ""
                lines.append("  " + json.dumps(row, sort_keys=True, separators=(",", ":")) + rcomma)
            lines.append(f" ]{comma}")
        elif isinstance(val, dict):
            dumped = json.dumps(val, separators=(",", ":"), sort_keys=True)
            lines.append(f' "{k}": {dumped}{comma}')
        else:
            lines.append(f' "{k}": {json.dumps(val, sort_keys=True)}{comma}')
    lines.append("}\n")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="recompute and verify JSON (1e-9 tol) and Markdown (exact)")
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-md", default=str(OUT_MD))
    ap.add_argument("--out-leaderboard", default=str(OUT_LEADERBOARD))
    args = ap.parse_args(argv)

    data = compute(ROOT)
    lb_data = build_leaderboard_v14_hard(data)
    json_blob = _format_compact_json(data)
    md_blob = render_md(data) + "\n"
    lb_blob = json.dumps(lb_data, indent=1) + "\n"

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_lb = Path(args.out_leaderboard)

    if args.check:
        if not out_json.exists():
            print(f"missing {out_json}", file=sys.stderr)
            return 1
        if not out_md.exists():
            print(f"missing {out_md}", file=sys.stderr)
            return 1
        if not out_lb.exists():
            print(f"missing {out_lb}", file=sys.stderr)
            return 1
        raw_bytes = out_json.read_bytes()
        if len(raw_bytes) > MAX_JSON_BYTES:
            print(f"{out_json} exceeds {MAX_JSON_BYTES} byte limit: {len(raw_bytes)} bytes", file=sys.stderr)
            return 1
        stored_json = json.loads(raw_bytes.decode("utf-8"))
        fresh_json = json.loads(json_blob)
        if not approx_equal(stored_json, fresh_json, tol=1e-9):
            print(f"{out_json} differs from recomputed data beyond 1e-9 tolerance", file=sys.stderr)
            return 1
        stored_md = out_md.read_text(encoding="utf-8")
        if stored_md != md_blob:
            print(f"{out_md} differs from recomputed markdown", file=sys.stderr)
            return 1
        stored_lb = json.loads(out_lb.read_text(encoding="utf-8"))
        fresh_lb = json.loads(lb_blob)
        try:
            check_leaderboard_v14_hard(stored_lb)
        except ValueError as exc:
            print(f"{out_lb} invalid: {exc}", file=sys.stderr)
            return 1
        if not approx_equal(stored_lb, fresh_lb, tol=1e-9):
            print(f"{out_lb} differs from recomputed leaderboard beyond 1e-9 tolerance", file=sys.stderr)
            return 1
        print("headline_gap_table_v14 check OK")
        return 0

    if len(json_blob.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"JSON output exceeds {MAX_JSON_BYTES} byte limit: {len(json_blob.encode('utf-8'))} bytes")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_lb.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json_blob, encoding="utf-8")
    out_md.write_text(md_blob, encoding="utf-8")
    out_lb.write_text(lb_blob, encoding="utf-8")
    print(
        f"wrote {out_json} ({len(json_blob.encode('utf-8'))} bytes), "
        f"{out_lb} ({len(lb_blob.encode('utf-8'))} bytes), and {out_md}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
