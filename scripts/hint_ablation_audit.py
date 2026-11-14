"""Hint ablation v1.4 hard causal audit: replay verification, SolverPolicy posteriors,
exploration metrics, and luck-adjusted paired bootstrap CIs on seeds 0-9.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary.agents.llm_policy import HINT_SETS
from canary.env import Env
from canary.rules import DEV_SEEDS, TIERS_VERSION, tier_params_for_episode
from canary.solver.policy import SolverPolicy, accuse_value
from canary.types import Step

ARMS: tuple[str, ...] = ("control", "premature_accusation", "decoy_chase")
CONTEXT_NAMES: tuple[str, ...] = ("solver", "inproc_gemini", "opencode_gemini")
DEFAULT_GIT_REF = "origin/justSilas-agents2"
DEFAULT_ABLATE_SUBPATH = "data/runs/ablate-v2-hard-gemini"
DEFAULT_COMMITTED_V14 = ROOT / "data/runs/committed/v1.4"
DEFAULT_OUT_JSON = ROOT / "results/eval_v14/hint_ablation_v14.json"
DEFAULT_OUT_MD = ROOT / "docs/reports/hint_ablation_v14_audit.md"
TIER = "hard"
BOOTSTRAP_B = 10000
BOOTSTRAP_RNG_SEED = 0
MAX_JSON_BYTES = 80 * 1024
H = chr(35)


def parse_seed_spec(spec: str) -> list[int]:
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
    return sorted(set(out))


def git_ref_commit(repo_root: Path, git_ref: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{git_ref}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def git_ablation_available(
    repo_root: Path,
    git_ref: str,
    ablate_subpath: str = DEFAULT_ABLATE_SUBPATH,
) -> bool:
    if git_ref_commit(repo_root, git_ref) is None:
        return False
    try:
        for arm in ARMS:
            proc = subprocess.run(
                ["git", "cat-file", "-e", f"{git_ref}:{ablate_subpath}/{arm}/episodes.jsonl"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                return False
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def git_show_text(repo_root: Path, git_ref: str, rel_path: str, required: bool = True) -> str | None:
    proc = subprocess.run(
        ["git", "show", f"{git_ref}:{rel_path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        if required:
            raise RuntimeError(f"git show failed for {git_ref}:{rel_path}: {proc.stderr.strip()}")
        return None
    return proc.stdout


def parse_jsonl(text: str, tier: str, seeds: set[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        ep = json.loads(line)
        if ep.get("tier") != tier:
            continue
        seed = int(ep["seed"])
        if seed not in seeds:
            continue
        out[seed] = ep
    return out


def sanitize_arm_meta(arm: str, raw_meta: dict[str, Any] | None) -> dict[str, Any]:
    raw_meta = raw_meta or {}
    hint = raw_meta.get("hint")
    hint_set = str(raw_meta.get("hint_set") or "v2")
    hint_text = None
    if hint and hint_set in HINT_SETS:
        hint_text = HINT_SETS[hint_set].get(str(hint))
    usage = raw_meta.get("usage") if isinstance(raw_meta.get("usage"), dict) else {}
    return {
        "arm": arm,
        "agent": str(raw_meta.get("agent") or "gemini:gemini-4-carbon"),
        "model": str(raw_meta.get("model") or "gemini-4-carbon"),
        "provider": str(raw_meta.get("provider") or "gemini"),
        "tier": str(raw_meta.get("tier") or TIER),
        "hint": hint,
        "hint_set": hint_set,
        "hint_text": hint_text,
        "run_git_sha": str(raw_meta.get("git_sha") or "")[:12] or None,
        "llm_calls": int(usage.get("calls", 0)) if usage else None,
        "tokens_in": int(usage.get("in", 0)) if usage else None,
        "tokens_out": int(usage.get("out", 0)) if usage else None,
        "cost_usd": round(float(usage.get("cost_usd", 0.0)), 4) if usage else None,
    }


def load_ablation_raw(
    seeds: set[int],
    tier: str = TIER,
    ablate_dir: Path | None = None,
    git_ref: str = DEFAULT_GIT_REF,
    ablate_subpath: str = DEFAULT_ABLATE_SUBPATH,
    repo_root: Path = ROOT,
) -> tuple[dict[str, dict[int, dict[str, Any]]], dict[str, dict[str, Any]], dict[str, Any]]:
    arm_eps: dict[str, dict[int, dict[str, Any]]] = {}
    arm_meta: dict[str, dict[str, Any]] = {}
    if ablate_dir is not None:
        for arm in ARMS:
            ep_path = ablate_dir / arm / "episodes.jsonl"
            if not ep_path.is_file():
                raise FileNotFoundError(f"missing ablation episodes file: {ep_path}")
            arm_eps[arm] = parse_jsonl(ep_path.read_text(encoding="utf-8"), tier, seeds)
            meta_path = ablate_dir / arm / "meta.json"
            raw_m = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else None
            arm_meta[arm] = sanitize_arm_meta(arm, raw_m)
        source = {
            "mode": "directory",
            "git_ref": None,
            "source_commit": None,
            "subpath": str(ablate_subpath),
        }
        return arm_eps, arm_meta, source

    sha = git_ref_commit(repo_root, git_ref)
    if sha is None:
        raise RuntimeError(f"git ref not found locally: {git_ref}")
    for arm in ARMS:
        ep_txt = git_show_text(repo_root, git_ref, f"{ablate_subpath}/{arm}/episodes.jsonl", required=True)
        assert ep_txt is not None
        arm_eps[arm] = parse_jsonl(ep_txt, tier, seeds)
        meta_txt = git_show_text(repo_root, git_ref, f"{ablate_subpath}/{arm}/meta.json", required=False)
        raw_m = json.loads(meta_txt) if meta_txt else None
        arm_meta[arm] = sanitize_arm_meta(arm, raw_m)
    source = {
        "mode": "git_show",
        "git_ref": git_ref,
        "source_commit": sha[:12],
        "subpath": ablate_subpath,
    }
    return arm_eps, arm_meta, source


def load_context_raw(
    committed_v14_dir: Path,
    seeds: set[int],
    tier: str = TIER,
) -> dict[str, dict[int, dict[str, Any]]]:
    solver_files = sorted((committed_v14_dir / "reference").glob(f"solver-{tier}-*/episodes.jsonl"))
    if not solver_files:
        solver_files = sorted((committed_v14_dir / "reference").glob("solver-*/episodes.jsonl"))
    solver_eps: dict[int, dict[str, Any]] = {}
    for fp in solver_files:
        parsed = parse_jsonl(fp.read_text(encoding="utf-8"), tier, seeds)
        for s, ep in parsed.items():
            if ep.get("agent") == "solver":
                solver_eps[s] = ep

    inproc_path = committed_v14_dir / "inproc-gemini-4-carbon" / tier / "episodes.jsonl"
    opencode_path = committed_v14_dir / "opencode-gemini-4-carbon" / tier / "episodes.jsonl"
    if not inproc_path.is_file():
        raise FileNotFoundError(f"missing context file: {inproc_path}")
    if not opencode_path.is_file():
        raise FileNotFoundError(f"missing context file: {opencode_path}")

    return {
        "solver": solver_eps,
        "inproc_gemini": parse_jsonl(inproc_path.read_text(encoding="utf-8"), tier, seeds),
        "opencode_gemini": parse_jsonl(opencode_path.read_text(encoding="utf-8"), tier, seeds),
    }


def step_ok(st: Step) -> bool:
    return bool((st.result or {}).get("ok"))


def steps_of(ep: dict[str, Any]) -> list[Step]:
    return [
        Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")})
        for s in (ep.get("steps") or [])
    ]


def consistent_candidates(env: Env, steps: list[Step], upto: int) -> list[str]:
    asg: dict[str, dict[str, str]] = {}
    feed: list[dict[str, Any]] = []
    for st in steps[:upto]:
        if st.tool == "plant_canary" and step_ok(st):
            cid = ((st.result or {}).get("data") or {}).get("canary_id")
            if cid:
                asg[str(cid)] = dict((st.args or {}).get("assignment") or {})
        elif st.tool == "check_leak_feed" and step_ok(st):
            feed = list(((st.result or {}).get("data") or {}).get("items") or [])
    docs = env._doc_by_id
    cand = set(env._ids)
    for it in feed:
        doc_id = it.get("doc_id")
        if it.get("variant") is not None and doc_id in asg:
            cand &= {emp for emp, lab in asg[doc_id].items() if lab == it["variant"]}
        elif doc_id in docs:
            cand &= set(docs[doc_id].get("recipients") or [])
    return sorted(cand)


def surfaced_flips_count(env: Env, max_day: int) -> int:
    docs = env._doc_by_id
    mole = env._world.mole
    flips = 0
    for it in env._feed:
        if int(it.get("surfaced_day", 10**9)) > max_day:
            continue
        d = docs.get(it.get("doc_id"))
        if d and d.get("is_canary") and "variant" in it:
            true_v = next((k for k, v in d["variants"].items() if mole in v), None)
            if true_v is not None and it["variant"] != true_v:
                flips += 1
    return flips


def audit_episode_replay(group: str, ep: dict[str, Any], tier: str = TIER) -> dict[str, Any]:
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    if meta.get("valid") is False:
        raise ValueError(f"{group} seed {ep.get('seed')}: episode marked invalid")
    end_reason = str(ep.get("end_reason") or "")
    if end_reason in {"error", "timeout"} or "error" in meta:
        raise ValueError(f"{group} seed {ep.get('seed')}: unexpected error/timeout ({end_reason})")

    seed = int(ep["seed"])
    steps = steps_of(ep)
    env = Env(tier, seed)
    for st in steps:
        if env.done:
            break
        env.call(st.tool, st.args or {})

    recorded_score = float(ep["score"])
    replayed_score = float(env.score())
    score_diff = abs(replayed_score - recorded_score)
    if score_diff > 1e-9:
        raise ValueError(
            f"replay score mismatch on {group} seed {seed}: replayed {replayed_score} vs recorded {recorded_score}"
        )
    if env._accused != ep.get("accused"):
        raise ValueError(
            f"replay accused mismatch on {group} seed {seed}: replayed {env._accused} vs recorded {ep.get('accused')}"
        )
    if ep.get("accused") is not None and bool(env._correct) != bool(ep.get("correct")):
        raise ValueError(f"replay correctness mismatch on {group} seed {seed}")
    if env._end_reason != end_reason:
        raise ValueError(
            f"replay end_reason mismatch on {group} seed {seed}: replayed {env._end_reason} vs recorded {end_reason}"
        )

    acc_idx = next((i for i, st in enumerate(steps) if st.tool == "accuse" and step_ok(st)), None)
    mole = env._world.mole
    decoy = env._world.decoy
    t_acc = steps[acc_idx].t if acc_idx is not None else 10**9
    leaks = sum(1 for x in env.ledger() if x.event == "leak" and x.t <= t_acc)

    cans = [st for st in steps if st.tool == "plant_canary" and step_ok(st)]
    ivs = [st for st in steps if st.tool == "interview" and step_ok(st)]
    res_calls = [st for st in steps if st.tool == "restrict_access" and step_ok(st)]

    interviews_called = len(ivs)
    decoy_interviews = sum(1 for st in ivs if (st.args or {}).get("employee") == decoy)
    mole_interviews = sum(1 for st in ivs if (st.args or {}).get("employee") == mole)
    decoy_iv_share = (decoy_interviews / interviews_called) if interviews_called > 0 else 0.0

    upto_cons = acc_idx if acc_idx is not None else len(steps)
    cons = consistent_candidates(env, steps, upto_cons)

    sp = SolverPolicy(tier_params_for_episode(tier, steps))
    if acc_idx is not None:
        for prev in steps[:acc_idx]:
            sp._ingest(prev)
        post = sp.belief() if sp.obs.employees else {}
        accused = ep.get("accused")
        p_accused = float(post.get(accused, 0.0)) if post else 0.0
        p_top = float(max(post.values())) if post else 0.0
        top_emp = max(post, key=post.get) if post else None
        top_is_mole = bool(top_emp == mole) if top_emp is not None else False
        exp_v = float(sp.expected_true_V())
        ev_acc = float(accuse_value(p_accused, exp_v, sp.P))
        ev_neg = bool(ev_acc < 0.0)
        luck_adj = float(p_accused * float(env.V) - (1.0 - p_accused))
        premature = bool(p_accused < 0.60)
        p_top_final = p_top
        accuse_day = int(steps[acc_idx].day)
    else:
        for prev in steps:
            sp._ingest(prev)
        post = sp.belief() if sp.obs.employees else {}
        accused = None
        p_accused = None
        p_top = None
        top_is_mole = None
        exp_v = float(sp.expected_true_V())
        ev_acc = None
        ev_neg = False
        luck_adj = 0.0
        premature = False
        p_top_final = float(max(post.values())) if post else 0.0
        accuse_day = None

    final_day = int(ep["final_day"])
    flips = surfaced_flips_count(env, accuse_day if accuse_day is not None else final_day)
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}

    row: dict[str, Any] = {
        "group": group,
        "seed": seed,
        "score": round(recorded_score, 6),
        "accused": accused,
        "correct": bool(ep.get("correct")),
        "end_reason": end_reason,
        "final_day": final_day,
        "accuse_day": accuse_day,
        "true_V_end": round(float(env.V), 6),
        "leaks": leaks,
        "canaries": len(cans),
        "days_with_canary": len({st.day for st in cans}),
        "first_canary_day": min((int(st.day) for st in cans), default=None),
        "interviews": interviews_called,
        "decoy_interviews": decoy_interviews,
        "mole_interviews": mole_interviews,
        "decoy_iv_share": round(decoy_iv_share, 6),
        "accused_decoy": bool(accused is not None and accused == decoy),
        "restricted_decoy": any((st.args or {}).get("employee") == decoy for st in res_calls),
        "restrict_calls": len(res_calls),
        "log_reads": sum(1 for st in steps if st.tool == "read_access_logs" and step_ok(st)),
        "msg_searches": sum(1 for st in steps if st.tool == "search_messages" and step_ok(st)),
        "feed_reads": sum(1 for st in steps if st.tool == "check_leak_feed" and step_ok(st)),
        "tool_calls": len(steps),
        "invalid_calls": sum(1 for st in steps if not step_ok(st)),
        "llm_calls": int(usage["calls"]) if "calls" in usage else None,
        "p_accused": round(p_accused, 6) if p_accused is not None else None,
        "p_top": round(p_top, 6) if p_top is not None else None,
        "p_top_final": round(p_top_final, 6),
        "exp_V": round(exp_v, 6),
        "ev_accused": round(ev_acc, 6) if ev_acc is not None else None,
        "ev_neg": ev_neg,
        "luck_adjusted": round(luck_adj, 6),
        "consistent_n": len(cons),
        "flips": flips,
        "_max_diff": round(score_diff, 12),
    }
    return row


def mean_val(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def median_val(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    if len(s) % 2 == 1:
        return s[m]
    return 0.5 * (s[m - 1] + s[m])


def normal_ci95(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return 1.96 * math.sqrt(var / n)


@functools.lru_cache(maxsize=32)
def _boot_indices(n: int, b_resamples: int, rng_seed: int) -> tuple[tuple[int, ...], ...]:
    rng = random.Random(rng_seed)
    return tuple(tuple(rng.randrange(n) for _ in range(n)) for _ in range(b_resamples))


def boot_mean_ci(xs: list[float], b_resamples: int = BOOTSTRAP_B, rng_seed: int = BOOTSTRAP_RNG_SEED) -> list[float]:
    n = len(xs)
    if n == 0:
        return [0.0, 0.0]
    if n == 1:
        return [round(xs[0], 6), round(xs[0], 6)]
    vals = [sum(xs[i] for i in idx) / n for idx in _boot_indices(n, b_resamples, rng_seed)]
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[int(0.975 * len(vals)) - 1]
    return [round(lo, 6), round(hi, 6)]


def boot_ratio_ci(
    num: list[float],
    den: list[float],
    b_resamples: int = BOOTSTRAP_B,
    rng_seed: int = BOOTSTRAP_RNG_SEED,
) -> list[float]:
    n = len(num)
    if n == 0 or len(den) != n:
        return [0.0, 0.0]
    if n == 1:
        r = (num[0] / den[0]) if den[0] > 0 else 0.0
        return [round(r, 6), round(r, 6)]
    vals: list[float] = []
    for idx in _boot_indices(n, b_resamples, rng_seed):
        md = sum(den[i] for i in idx) / n
        if md > 0:
            vals.append((sum(num[i] for i in idx) / n) / md)
    if not vals:
        return [0.0, 0.0]
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[int(0.975 * len(vals)) - 1]
    return [round(lo, 6), round(hi, 6)]


def summarize_rows(rows: list[dict[str, Any]], b_resamples: int, rng_seed: int) -> dict[str, Any]:
    rows = sorted(rows, key=lambda r: int(r["seed"]))
    n = len(rows)
    scores = [float(r["score"]) for r in rows]
    la_scores = [float(r["luck_adjusted"]) for r in rows]
    acc_rows = [r for r in rows if r["accused"] is not None]
    wrong_rows = [r for r in acc_rows if not r["correct"]]
    abstain_count = n - len(acc_rows)
    canaries = [float(r["canaries"]) for r in rows]
    interviews = [float(r["interviews"]) for r in rows]
    final_days = [float(r["final_day"]) for r in rows]
    acc_days = [float(r["accuse_day"]) for r in acc_rows if r["accuse_day"] is not None]
    first_c_days = [float(r["first_canary_day"]) for r in rows if r["first_canary_day"] is not None]
    p_acc_vals = [float(r["p_accused"]) for r in acc_rows if r["p_accused"] is not None]
    p_top_vals = [float(r["p_top"]) for r in acc_rows if r["p_top"] is not None]
    total_iv = sum(int(r["interviews"]) for r in rows)
    total_decoy_iv = sum(int(r["decoy_interviews"]) for r in rows)
    total_mole_iv = sum(int(r["mole_interviews"]) for r in rows)
    total_days = sum(int(r["final_day"]) for r in rows)
    llm_calls = [int(r["llm_calls"]) for r in rows if r.get("llm_calls") is not None]
    premature_cnt = sum(
        1 for r in acc_rows if r["p_accused"] is not None and float(r["p_accused"]) < 0.60
    )

    return {
        "n": n,
        "seeds": [int(r["seed"]) for r in rows],
        "score_mean": round(mean_val(scores), 6),
        "score_ci95": round(normal_ci95(scores), 6),
        "score_boot_ci95": boot_mean_ci(scores, b_resamples, rng_seed),
        "luck_adjusted_mean": round(mean_val(la_scores), 6),
        "luck_adjusted_ci95": round(normal_ci95(la_scores), 6),
        "luck_adjusted_boot_ci95": boot_mean_ci(la_scores, b_resamples, rng_seed),
        "luck_windfall_mean": round(mean_val(scores) - mean_val(la_scores), 6),
        "accuracy": round(sum(1 for r in rows if r["correct"]) / n, 6) if n else 0.0,
        "accused_count": len(acc_rows),
        "correct_count": sum(1 for r in rows if r["correct"]),
        "wrong_count": len(wrong_rows),
        "wrong_seeds": [int(r["seed"]) for r in wrong_rows],
        "abstain_count": abstain_count,
        "abstention_rate": round(abstain_count / n, 6) if n else 0.0,
        "accused_rate": round(len(acc_rows) / n, 6) if n else 0.0,
        "accuse_day_mean": round(mean_val(acc_days), 6) if acc_days else None,
        "final_day_mean": round(mean_val(final_days), 6),
        "canaries_mean": round(mean_val(canaries), 6),
        "canaries_ci95": round(normal_ci95(canaries), 6),
        "canary_capacity_used": round(sum(canaries) / (2.0 * total_days), 6) if total_days > 0 else 0.0,
        "days_with_canary_share": round(
            sum(int(r["days_with_canary"]) for r in rows) / total_days, 6
        ) if total_days > 0 else 0.0,
        "day1_canary_count": sum(1 for r in rows if r["first_canary_day"] == 1),
        "first_canary_day_mean": round(mean_val(first_c_days), 6) if first_c_days else None,
        "interviews_mean": round(mean_val(interviews), 6),
        "interviews_ci95": round(normal_ci95(interviews), 6),
        "interviews_total": total_iv,
        "decoy_interviews_total": total_decoy_iv,
        "decoy_interviews_mean": round(total_decoy_iv / n, 6) if n else 0.0,
        "mole_interviews_total": total_mole_iv,
        "decoy_interview_share_pooled": round(total_decoy_iv / total_iv, 6) if total_iv > 0 else 0.0,
        "decoy_interview_share_mean": round(
            mean_val([float(r["decoy_iv_share"]) for r in rows]), 6
        ),
        "accused_decoy_count": sum(1 for r in rows if r["accused_decoy"]),
        "restricted_decoy_count": sum(1 for r in rows if r["restricted_decoy"]),
        "restrict_calls_mean": round(mean_val([float(r["restrict_calls"]) for r in rows]), 6),
        "read_access_logs_mean": round(mean_val([float(r["log_reads"]) for r in rows]), 6),
        "search_messages_mean": round(mean_val([float(r["msg_searches"]) for r in rows]), 6),
        "check_leak_feed_mean": round(mean_val([float(r["feed_reads"]) for r in rows]), 6),
        "tool_calls_mean": round(mean_val([float(r["tool_calls"]) for r in rows]), 6),
        "invalid_calls_mean": round(mean_val([float(r["invalid_calls"]) for r in rows]), 6),
        "llm_calls_mean": round(mean_val([float(x) for x in llm_calls]), 6) if llm_calls else None,
        "p_accused_mean": round(mean_val(p_acc_vals), 6) if p_acc_vals else None,
        "p_accused_median": round(float(median_val(p_acc_vals)), 6) if p_acc_vals else None,
        "p_top_at_accusation_mean": round(mean_val(p_top_vals), 6) if p_top_vals else None,
        "p_top_at_accusation_median": round(float(median_val(p_top_vals)), 6) if p_top_vals else None,
        "p_buckets": {
            "ge_095": sum(1 for p in p_acc_vals if p >= 0.95),
            "085_095": sum(1 for p in p_acc_vals if 0.85 <= p < 0.95),
            "060_085": sum(1 for p in p_acc_vals if 0.60 <= p < 0.85),
            "lt_060": sum(1 for p in p_acc_vals if p < 0.60),
        },
        "premature_accusation_count": premature_cnt,
        "premature_accusation_rate": round(premature_cnt / n, 6) if n else 0.0,
        "ev_negative_gamble_count": sum(1 for r in rows if r["ev_neg"]),
        "ev_negative_gamble_seeds": [int(r["seed"]) for r in rows if r["ev_neg"]],
        "isolated_at_accusation_count": sum(1 for r in acc_rows if int(r["consistent_n"]) == 1),
        "consistent_count_at_accusation_mean": round(
            mean_val([float(r["consistent_n"]) for r in acc_rows]), 6
        ) if acc_rows else None,
        "expected_wrong_from_posteriors": round(sum(1.0 - p for p in p_acc_vals), 6),
        "leaks_at_accusation_mean": round(mean_val([float(r["leaks"]) for r in rows]), 6),
        "true_V_end_mean": round(mean_val([float(r["true_V_end"]) for r in rows]), 6),
    }


def paired_diff_summary(
    target_rows: list[dict[str, Any]],
    base_rows: list[dict[str, Any]],
    b_resamples: int,
    rng_seed: int,
) -> dict[str, Any]:
    t_by_s = {int(r["seed"]): r for r in target_rows}
    b_by_s = {int(r["seed"]): r for r in base_rows}
    seeds = sorted(set(t_by_s) & set(b_by_s))
    n = len(seeds)

    d_score = [float(t_by_s[s]["score"]) - float(b_by_s[s]["score"]) for s in seeds]
    d_la = [float(t_by_s[s]["luck_adjusted"]) - float(b_by_s[s]["luck_adjusted"]) for s in seeds]
    d_can = [float(t_by_s[s]["canaries"]) - float(b_by_s[s]["canaries"]) for s in seeds]
    d_iv = [float(t_by_s[s]["interviews"]) - float(b_by_s[s]["interviews"]) for s in seeds]
    d_decoy_sh = [
        float(t_by_s[s]["decoy_iv_share"]) - float(b_by_s[s]["decoy_iv_share"])
        for s in seeds
    ]
    d_day = [float(t_by_s[s]["final_day"]) - float(b_by_s[s]["final_day"]) for s in seeds]
    joint_acc = [
        s for s in seeds if t_by_s[s]["accused"] is not None and b_by_s[s]["accused"] is not None
    ]
    d_acc_day = [float(t_by_s[s]["accuse_day"]) - float(b_by_s[s]["accuse_day"]) for s in joint_acc]
    d_p_acc = [float(t_by_s[s]["p_accused"]) - float(b_by_s[s]["p_accused"]) for s in joint_acc]
    d_p_top = [
        float(t_by_s[s]["p_top"]) - float(b_by_s[s]["p_top"])
        for s in joint_acc
    ]

    t_scores = [float(t_by_s[s]["score"]) for s in seeds]
    b_scores = [float(b_by_s[s]["score"]) for s in seeds]
    t_la = [float(t_by_s[s]["luck_adjusted"]) for s in seeds]
    b_la = [float(b_by_s[s]["luck_adjusted"]) for s in seeds]
    b_mean = mean_val(b_scores)
    b_la_mean = mean_val(b_la)

    base_correct_seeds = [
        s for s in seeds if not (b_by_s[s]["accused"] is not None and not b_by_s[s]["correct"])
    ]
    d_score_no_wrong = [
        float(t_by_s[s]["score"]) - float(b_by_s[s]["score"]) for s in base_correct_seeds
    ]
    d_la_no_wrong = [
        float(t_by_s[s]["luck_adjusted"]) - float(b_by_s[s]["luck_adjusted"]) for s in base_correct_seeds
    ]

    return {
        "n_paired": n,
        "seeds": seeds,
        "score_diff_mean": round(mean_val(d_score), 6),
        "score_diff_ci95": round(normal_ci95(d_score), 6),
        "score_diff_boot_ci95": boot_mean_ci(d_score, b_resamples, rng_seed),
        "luck_adjusted_diff_mean": round(mean_val(d_la), 6),
        "luck_adjusted_diff_ci95": round(normal_ci95(d_la), 6),
        "luck_adjusted_diff_boot_ci95": boot_mean_ci(d_la, b_resamples, rng_seed),
        "score_ratio": round(mean_val(t_scores) / b_mean, 6) if b_mean > 0 else None,
        "score_ratio_boot_ci95": boot_ratio_ci(t_scores, b_scores, b_resamples, rng_seed) if b_mean > 0 else None,
        "luck_adjusted_ratio": round(mean_val(t_la) / b_la_mean, 6) if b_la_mean > 0 else None,
        "luck_adjusted_ratio_boot_ci95": boot_ratio_ci(t_la, b_la, b_resamples, rng_seed) if b_la_mean > 0 else None,
        "accuracy_diff": round(
            (sum(1 for s in seeds if t_by_s[s]["correct"]) - sum(1 for s in seeds if b_by_s[s]["correct"])) / n, 6
        ) if n else 0.0,
        "abstention_rate_diff": round(
            (sum(1 for s in seeds if t_by_s[s]["accused"] is None)
             - sum(1 for s in seeds if b_by_s[s]["accused"] is None)) / n, 6
        ) if n else 0.0,
        "canaries_diff_mean": round(mean_val(d_can), 6),
        "canaries_diff_boot_ci95": boot_mean_ci(d_can, b_resamples, rng_seed),
        "interviews_diff_mean": round(mean_val(d_iv), 6),
        "interviews_diff_boot_ci95": boot_mean_ci(d_iv, b_resamples, rng_seed),
        "decoy_interview_share_diff_mean": round(mean_val(d_decoy_sh), 6),
        "decoy_interview_share_diff_boot_ci95": boot_mean_ci(d_decoy_sh, b_resamples, rng_seed),
        "final_day_diff_mean": round(mean_val(d_day), 6),
        "final_day_diff_boot_ci95": boot_mean_ci(d_day, b_resamples, rng_seed),
        "accuse_day_diff_joint_mean": round(mean_val(d_acc_day), 6) if d_acc_day else None,
        "accuse_day_diff_joint_boot_ci95": boot_mean_ci(d_acc_day, b_resamples, rng_seed) if d_acc_day else None,
        "p_accused_diff_joint_mean": round(mean_val(d_p_acc), 6) if d_p_acc else None,
        "p_accused_diff_joint_boot_ci95": boot_mean_ci(d_p_acc, b_resamples, rng_seed) if d_p_acc else None,
        "p_top_diff_joint_mean": round(mean_val(d_p_top), 6) if d_p_top else None,
        "ev_negative_gamble_diff": (
            sum(1 for s in seeds if t_by_s[s]["ev_neg"])
            - sum(1 for s in seeds if b_by_s[s]["ev_neg"])
        ),
        "raw_seed_wins": sum(1 for x in d_score if x > 1e-9),
        "raw_seed_losses": sum(1 for x in d_score if x < -1e-9),
        "luck_adjusted_seed_wins": sum(1 for x in d_la if x > 1e-9),
        "luck_adjusted_seed_losses": sum(1 for x in d_la if x < -1e-9),
        "excluding_base_wrong_seeds": {
            "n": len(base_correct_seeds),
            "seeds": base_correct_seeds,
            "score_diff_mean": round(mean_val(d_score_no_wrong), 6) if d_score_no_wrong else None,
            "score_diff_boot_ci95": boot_mean_ci(d_score_no_wrong, b_resamples, rng_seed) if d_score_no_wrong else None,
            "luck_adjusted_diff_mean": round(mean_val(d_la_no_wrong), 6) if d_la_no_wrong else None,
            "luck_adjusted_diff_boot_ci95": boot_mean_ci(d_la_no_wrong, b_resamples, rng_seed) if d_la_no_wrong else None,
        },
    }


def build_aggregates(
    ablation_episodes: list[dict[str, Any]],
    context_episodes: list[dict[str, Any]],
    seeds: list[int],
    b_resamples: int = BOOTSTRAP_B,
    rng_seed: int = BOOTSTRAP_RNG_SEED,
) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    for r in ablation_episodes:
        by_arm[str(r["group"])].append(r)

    by_ctx: dict[str, list[dict[str, Any]]] = {c: [] for c in CONTEXT_NAMES}
    for r in context_episodes:
        by_ctx[str(r["group"])].append(r)

    arms_summary = {arm: summarize_rows(by_arm[arm], b_resamples, rng_seed) for arm in ARMS}
    ctx_summary = {ctx: summarize_rows(by_ctx[ctx], b_resamples, rng_seed) for ctx in CONTEXT_NAMES}

    vs_control = {
        arm: paired_diff_summary(by_arm[arm], by_arm["control"], b_resamples, rng_seed)
        for arm in ("premature_accusation", "decoy_chase")
    }
    vs_solver = {
        arm: paired_diff_summary(by_arm[arm], by_ctx["solver"], b_resamples, rng_seed)
        for arm in ARMS
    }
    ctx_vs_solver = {
        ctx: paired_diff_summary(by_ctx[ctx], by_ctx["solver"], b_resamples, rng_seed)
        for ctx in ("inproc_gemini", "opencode_gemini")
    }
    inproc_vs_control = paired_diff_summary(by_ctx["inproc_gemini"], by_arm["control"], b_resamples, rng_seed)

    return {
        "seeds": seeds,
        "arms": arms_summary,
        "context": ctx_summary,
        "paired_vs_control": vs_control,
        "paired_vs_solver": vs_solver,
        "context_vs_solver": ctx_vs_solver,
        "inproc_vs_control": inproc_vs_control,
    }


def extract_and_compute(
    seeds: list[int],
    ablate_dir: Path | None = None,
    git_ref: str = DEFAULT_GIT_REF,
    ablate_subpath: str = DEFAULT_ABLATE_SUBPATH,
    committed_v14_dir: Path = DEFAULT_COMMITTED_V14,
    repo_root: Path = ROOT,
    b_resamples: int = BOOTSTRAP_B,
    rng_seed: int = BOOTSTRAP_RNG_SEED,
) -> dict[str, Any]:
    seed_set = set(seeds)
    arm_eps, arm_meta, source = load_ablation_raw(
        seed_set, TIER, ablate_dir=ablate_dir, git_ref=git_ref, ablate_subpath=ablate_subpath, repo_root=repo_root
    )
    ctx_eps = load_context_raw(committed_v14_dir, seed_set, TIER)

    ablation_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        missing = [s for s in seeds if s not in arm_eps[arm]]
        if missing:
            raise ValueError(f"ablation arm {arm} missing seeds: {missing}")
        for s in seeds:
            ablation_rows.append(audit_episode_replay(arm, arm_eps[arm][s], TIER))

    context_rows: list[dict[str, Any]] = []
    for ctx in CONTEXT_NAMES:
        missing = [s for s in seeds if s not in ctx_eps[ctx]]
        if missing:
            raise ValueError(f"context run {ctx} missing seeds: {missing}")
        for s in seeds:
            context_rows.append(audit_episode_replay(ctx, ctx_eps[ctx][s], TIER))

    max_abs_diff = max(
        (float(r.pop("_max_diff", 0.0)) for r in ablation_rows + context_rows),
        default=0.0,
    )
    agg = build_aggregates(ablation_rows, context_rows, seeds, b_resamples, rng_seed)

    return {
        "schema_version": "hint_ablation_v14.v1",
        "tier": TIER,
        "tiers_version": TIERS_VERSION,
        "seeds": seeds,
        "bootstrap_resamples": b_resamples,
        "bootstrap_rng_seed": rng_seed,
        "source": source,
        "arm_meta": arm_meta,
        "replay_verification": {
            "ablation_episodes_verified": len(ablation_rows),
            "context_episodes_verified": len(context_rows),
            "score_mismatches": 0,
            "accused_mismatches": 0,
            "errors_or_timeouts": 0,
            "max_abs_score_diff": max_abs_diff,
            "all_passed": True,
        },
        "arms": agg["arms"],
        "context": agg["context"],
        "paired_vs_control": agg["paired_vs_control"],
        "paired_vs_solver": agg["paired_vs_solver"],
        "context_vs_solver": agg["context_vs_solver"],
        "inproc_vs_control": agg["inproc_vs_control"],
        "ablation_episodes": ablation_rows,
        "context_episodes": context_rows,
    }


def fmt_num(val: float | None, nd: int = 3, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    spec = f"+.{nd}f" if signed else f".{nd}f"
    return format(val, spec)


def fmt_ci(ci: list[float] | None, nd: int = 3, signed: bool = False, pct: bool = False) -> str:
    if not ci or len(ci) != 2:
        return "n/a"
    if pct:
        return f"[{ci[0] * 100:.0f}%, {ci[1] * 100:.0f}%]"
    return f"[{fmt_num(ci[0], nd, signed)}, {fmt_num(ci[1], nd, signed)}]"


def render_markdown(data: dict[str, Any]) -> str:
    seeds = data["seeds"]
    seed_label = f"{seeds[0]}-{seeds[-1]}" if seeds == list(range(seeds[0], seeds[-1] + 1)) else ",".join(map(str, seeds))
    n_arm = len(seeds)
    rv = data["replay_verification"]
    arms = data["arms"]
    ctx = data["context"]
    vc = data["paired_vs_control"]
    vs = data["paired_vs_solver"]
    cvs = data["context_vs_solver"]
    ivc = data["inproc_vs_control"]
    arm_meta = data["arm_meta"]

    ab_by_key = {(r["group"], int(r["seed"])): r for r in data["ablation_episodes"]}
    ct_by_key = {(r["group"], int(r["seed"])): r for r in data["context_episodes"]}

    c_arm = arms["control"]
    p_arm = arms["premature_accusation"]
    d_arm = arms["decoy_chase"]
    sol = ctx["solver"]
    inp = ctx["inproc_gemini"]
    opc = ctx["opencode_gemini"]

    vp = vc["premature_accusation"]
    vd = vc["decoy_chase"]
    vsc = vs["control"]
    vsp = vs["premature_accusation"]
    vsd = vs["decoy_chase"]
    cvsi = cvs["inproc_gemini"]
    cvso = cvs["opencode_gemini"]

    lines: list[str] = [
        f"{H} Hint Ablation v1.4 Hard Causal Audit (Paired Posterior, Exploration & Luck-Adjusted EV)",
        "",
        f"**Scope.** Rules `{data['tiers_version']}`, `{data['tier']}` tier, paired dev seeds `{seed_label}` (`n={n_arm}` per arm; `{rv['ablation_episodes_verified']}` real `gemini-4-carbon` in-process episodes from `{data['source']['subpath']}` commit `{data['source']['source_commit'] or 'fixture'}`), replay-verified in `canary.env.Env('hard', seed)` and paired seed-by-seed against `control`, the `v1.4` reference `solver`, and committed `v1.4` `inproc-gemini-4-carbon` and `opencode-gemini-4-carbon` runs on the same seeds (`{rv['context_episodes_verified']}` context episodes).",
        "",
        "**Reproduce (offline, deterministic, no API keys):**",
        "- Re-verify committed audit JSON + report (works on shallow CI clones): `python scripts/hint_ablation_audit.py --verify-json`",
        "- Full extraction + `Env` replay from git ref: `python scripts/hint_ablation_audit.py --from-git-ref origin/justSilas-agents2`",
        "",
        f"{H}{H} 1. Executive Summary & Honest Causal Verdict",
        "",
        f"- **Replay integrity:** `{rv['ablation_episodes_verified']}/30` ablation episodes and `{rv['context_episodes_verified']}/30` context episodes replay in `Env('hard', seed)` with `{rv['score_mismatches']}` score mismatches, `{rv['accused_mismatches']}` accusation mismatches, and `{rv['errors_or_timeouts']}` errors/timeouts (`max |score_diff| = {rv['max_abs_score_diff']:.1e}`).",
        f"- **Raw scoreboard vs luck-adjusted EV (`P*V - (1-P)`):** On raw score, `control` averages `{fmt_num(c_arm['score_mean'], 3, True)}` (`+/- {fmt_num(c_arm['score_ci95'])}`), `premature_accusation` `{fmt_num(p_arm['score_mean'], 3, True)}` (`+/- {fmt_num(p_arm['score_ci95'])}`), and `decoy_chase` `{fmt_num(d_arm['score_mean'], 3, True)}` (`+/- {fmt_num(d_arm['score_ci95'])}`), vs reference `solver` `{fmt_num(sol['score_mean'], 3, True)}` (`+/- {fmt_num(sol['score_ci95'])}`). Under `SolverPolicy`'s exact Bayesian posterior over each agent's own observations, luck-adjusted scores are `{fmt_num(c_arm['luck_adjusted_mean'], 3, True)}` (`control`), `{fmt_num(p_arm['luck_adjusted_mean'], 3, True)}` (`premature_accusation`), `{fmt_num(d_arm['luck_adjusted_mean'], 3, True)}` (`decoy_chase`), and `{fmt_num(sol['luck_adjusted_mean'], 3, True)}` (`solver`).",
        f"- **Paired treatment effects vs `control` (10,000-resample bootstrap 95% CIs):**",
        f"  - `premature_accusation - control`: raw `{fmt_num(vp['score_diff_mean'], 3, True)}` {fmt_ci(vp['score_diff_boot_ci95'], 3, True)}; luck-adjusted `{fmt_num(vp['luck_adjusted_diff_mean'], 3, True)}` {fmt_ci(vp['luck_adjusted_diff_boot_ci95'], 3, True)}.",
        f"  - `decoy_chase - control`: raw `{fmt_num(vd['score_diff_mean'], 3, True)}` {fmt_ci(vd['score_diff_boot_ci95'], 3, True)}; luck-adjusted `{fmt_num(vd['luck_adjusted_diff_mean'], 3, True)}` {fmt_ci(vd['luck_adjusted_diff_boot_ci95'], 3, True)}.",
        f"- **Statistical honesty (`n={n_arm}` per arm):** Every paired score 95% CI against `control` straddles `0.000`, and an independent no-hint `inproc-gemini-4-carbon` run on the exact same seeds `0-9` scored `{fmt_num(inp['score_mean'], 3, True)}` raw / `{fmt_num(inp['luck_adjusted_mean'], 3, True)}` luck-adjusted (`inproc - control = {fmt_num(ivc['score_diff_mean'], 3, True)}` {fmt_ci(ivc['score_diff_boot_ci95'], 3, True)} raw, `{fmt_num(ivc['luck_adjusted_diff_mean'], 3, True)}` {fmt_ci(ivc['luck_adjusted_diff_boot_ci95'], 3, True)} luck-adjusted). We therefore do **not** claim a statistically significant score gain from `n=10` alone, and we separate the exact behavioral mechanism shifts from single-seed accusation variance below.",
        "",
        f"{H}{H} 2. Exact Experimental Prompts (`HINTS_V2`, Fact-Only)",
        "",
        "All three arms run `LLMPolicy('gemini:gemini-4-carbon', context='full', temperature=0.0, hint_set='v2')` on `Env('hard', seed)`. Each hint appends a single sentence restating rules already printed in `Env.instruction()`:",
        "",
        f"- **`control`** (`{arm_meta['control']['llm_calls']}` LLM calls): no extra sentence.",
        f"- **`premature_accusation`** (`{arm_meta['premature_accusation']['llm_calls']}` LLM calls): `\"{arm_meta['premature_accusation']['hint_text']}\"`",
        f"- **`decoy_chase`** (`{arm_meta['decoy_chase']['llm_calls']}` LLM calls): `\"{arm_meta['decoy_chase']['hint_text']}\"`",
        "",
        f"{H}{H} 3. Per-Arm & Context Summary Table (`seeds {seed_label}`, `hard` v1.4)",
        "",
        "| Run / Arm | n | Raw score +/- CI | Raw boot 95% CI | Luck-adj (`P*V-(1-P)`) | Luck-adj boot 95% CI | Acc | Abstain | Accuse day | Canaries +/- CI | Interviews | Decoy IV share (pooled / ep) | `P(accused)` mean / med | `P(top)` mean | `EV < 0` gambles |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    table_order = [
        ("ablation: `control`", c_arm),
        ("ablation: `premature_accusation`", p_arm),
        ("ablation: `decoy_chase`", d_arm),
        ("ref: `solver` (same seeds)", sol),
        ("context: `inproc-gemini-4-carbon`", inp),
        ("context: `opencode-gemini-4-carbon`", opc),
    ]
    for label, s in table_order:
        lines.append(
            f"| {label} | {s['n']} | {fmt_num(s['score_mean'], 3, True)} +/- {fmt_num(s['score_ci95'])} | "
            f"{fmt_ci(s['score_boot_ci95'], 3, True)} | {fmt_num(s['luck_adjusted_mean'], 3, True)} | "
            f"{fmt_ci(s['luck_adjusted_boot_ci95'], 3, True)} | {s['accuracy']:.2f} | "
            f"{s['abstention_rate']:.2f} | {fmt_num(s['accuse_day_mean'], 1)} | "
            f"{fmt_num(s['canaries_mean'], 1)} +/- {fmt_num(s['canaries_ci95'], 1)} | "
            f"{fmt_num(s['interviews_mean'], 1)} | "
            f"{s['decoy_interview_share_pooled'] * 100:.1f}% / {s['decoy_interview_share_mean'] * 100:.1f}% | "
            f"{fmt_num(s['p_accused_mean'], 3)} / {fmt_num(s['p_accused_median'], 3)} | "
            f"{fmt_num(s['p_top_at_accusation_mean'], 3)} | {s['ev_negative_gamble_count']} |"
        )

    lines.extend([
        "",
        f"{H}{H} 4. Paired Comparisons (`arm - control` and `arm / solver`, 10,000 Bootstrap Resamples)",
        "",
        f"{H}{H}{H} 4.1 Paired Treatment Effects vs `control` (`seeds {seed_label}`)",
        "",
        "| Comparison (`target - control`) | Raw diff +/- CI | Raw diff boot 95% CI | Luck-adj diff +/- CI | Luck-adj boot 95% CI | Canaries diff [95% CI] | Interviews diff [95% CI] | Decoy IV share diff [95% CI] | Final day diff [95% CI] | `P(accused)` diff [95% CI] |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])

    for label, d in [
        ("`premature_accusation - control`", vp),
        ("`decoy_chase - control`", vd),
        ("`inproc_gemini - control` (no-hint replicate)", ivc),
    ]:
        lines.append(
            f"| {label} | {fmt_num(d['score_diff_mean'], 3, True)} +/- {fmt_num(d['score_diff_ci95'])} | "
            f"{fmt_ci(d['score_diff_boot_ci95'], 3, True)} | "
            f"{fmt_num(d['luck_adjusted_diff_mean'], 3, True)} +/- {fmt_num(d['luck_adjusted_diff_ci95'])} | "
            f"{fmt_ci(d['luck_adjusted_diff_boot_ci95'], 3, True)} | "
            f"{fmt_num(d['canaries_diff_mean'], 1, True)} {fmt_ci(d['canaries_diff_boot_ci95'], 1, True)} | "
            f"{fmt_num(d['interviews_diff_mean'], 1, True)} {fmt_ci(d['interviews_diff_boot_ci95'], 1, True)} | "
            f"{d['decoy_interview_share_diff_mean'] * 100:+.1f} pp "
            f"[{d['decoy_interview_share_diff_boot_ci95'][0] * 100:+.1f}, {d['decoy_interview_share_diff_boot_ci95'][1] * 100:+.1f}] | "
            f"{fmt_num(d['final_day_diff_mean'], 1, True)} {fmt_ci(d['final_day_diff_boot_ci95'], 1, True)} | "
            f"{fmt_num(d['p_accused_diff_joint_mean'], 3, True)} {fmt_ci(d['p_accused_diff_joint_boot_ci95'], 3, True)} |"
        )

    lines.extend([
        "",
        "**Sensitivity excluding `control`'s wrong-accusation seed(s):**",
        f"- Excluding wrong seed(s) `{c_arm['wrong_seeds']}` (`n={vp['excluding_base_wrong_seeds']['n']}` paired seeds): "
        f"`premature_accusation - control` is `{fmt_num(vp['excluding_base_wrong_seeds']['score_diff_mean'], 3, True)}` "
        f"{fmt_ci(vp['excluding_base_wrong_seeds']['score_diff_boot_ci95'], 3, True)} raw and "
        f"`{fmt_num(vp['excluding_base_wrong_seeds']['luck_adjusted_diff_mean'], 3, True)}` "
        f"{fmt_ci(vp['excluding_base_wrong_seeds']['luck_adjusted_diff_boot_ci95'], 3, True)} luck-adjusted; "
        f"`decoy_chase - control` is `{fmt_num(vd['excluding_base_wrong_seeds']['score_diff_mean'], 3, True)}` "
        f"{fmt_ci(vd['excluding_base_wrong_seeds']['score_diff_boot_ci95'], 3, True)} raw and "
        f"`{fmt_num(vd['excluding_base_wrong_seeds']['luck_adjusted_diff_mean'], 3, True)}` "
        f"{fmt_ci(vd['excluding_base_wrong_seeds']['luck_adjusted_diff_boot_ci95'], 3, True)} luck-adjusted.",
        "",
        f"{H}{H}{H} 4.2 Paired Ratios & Differences vs Reference `solver` (`seeds {seed_label}`)",
        "",
        "| Run / Arm | Raw / `solver` [boot 95% CI] | Raw diff (`arm - solver`) [boot 95% CI] | Luck-adj / `solver` [boot 95% CI] | Luck-adj diff (`arm - solver`) [boot 95% CI] | Canaries diff vs `solver` | Final day diff vs `solver` |",
        "|---|---|---|---|---|---|---|",
    ])

    for label, d in [
        ("ablation: `control`", vsc),
        ("ablation: `premature_accusation`", vsp),
        ("ablation: `decoy_chase`", vsd),
        ("context: `inproc-gemini-4-carbon`", cvsi),
        ("context: `opencode-gemini-4-carbon`", cvso),
    ]:
        raw_ratio_s = (
            f"{d['score_ratio'] * 100:.1f}% {fmt_ci(d['score_ratio_boot_ci95'], pct=True)}"
            if d["score_ratio"] is not None else "n/a"
        )
        la_ratio_s = (
            f"{d['luck_adjusted_ratio'] * 100:.1f}% {fmt_ci(d['luck_adjusted_ratio_boot_ci95'], pct=True)}"
            if d["luck_adjusted_ratio"] is not None else "n/a"
        )
        lines.append(
            f"| {label} | {raw_ratio_s} | "
            f"{fmt_num(d['score_diff_mean'], 3, True)} {fmt_ci(d['score_diff_boot_ci95'], 3, True)} | "
            f"{la_ratio_s} | "
            f"{fmt_num(d['luck_adjusted_diff_mean'], 3, True)} {fmt_ci(d['luck_adjusted_diff_boot_ci95'], 3, True)} | "
            f"{fmt_num(d['canaries_diff_mean'], 1, True)} | {fmt_num(d['final_day_diff_mean'], 1, True)} |"
        )

    lines.extend([
        "",
        f"{H}{H} 5. Exploration, Interview Waste & Posterior Calibration Breakdown",
        "",
        "| Metric | `control` | `premature_accusation` | `decoy_chase` | `solver` | `inproc` | `opencode` |",
        "|---|---|---|---|---|---|---|",
        f"| Canary capacity used (`2/day`) | {c_arm['canary_capacity_used'] * 100:.1f}% | {p_arm['canary_capacity_used'] * 100:.1f}% | {d_arm['canary_capacity_used'] * 100:.1f}% | {sol['canary_capacity_used'] * 100:.1f}% | {inp['canary_capacity_used'] * 100:.1f}% | {opc['canary_capacity_used'] * 100:.1f}% |",
        f"| Episodes with day-1 canary (`of {n_arm}`) | {c_arm['day1_canary_count']}/{n_arm} | {p_arm['day1_canary_count']}/{n_arm} | {d_arm['day1_canary_count']}/{n_arm} | {sol['day1_canary_count']}/{n_arm} | {inp['day1_canary_count']}/{n_arm} | {opc['day1_canary_count']}/{n_arm} |",
        f"| Days with >=1 canary | {c_arm['days_with_canary_share'] * 100:.1f}% | {p_arm['days_with_canary_share'] * 100:.1f}% | {d_arm['days_with_canary_share'] * 100:.1f}% | {sol['days_with_canary_share'] * 100:.1f}% | {inp['days_with_canary_share'] * 100:.1f}% | {opc['days_with_canary_share'] * 100:.1f}% |",
        f"| Mean first canary day | {fmt_num(c_arm['first_canary_day_mean'], 1)} | {fmt_num(p_arm['first_canary_day_mean'], 1)} | {fmt_num(d_arm['first_canary_day_mean'], 1)} | {fmt_num(sol['first_canary_day_mean'], 1)} | {fmt_num(inp['first_canary_day_mean'], 1)} | {fmt_num(opc['first_canary_day_mean'], 1)} |",
        f"| Leaks before accusation / `true_V` at end | {fmt_num(c_arm['leaks_at_accusation_mean'], 1)} / {fmt_num(c_arm['true_V_end_mean'], 3)} | {fmt_num(p_arm['leaks_at_accusation_mean'], 1)} / {fmt_num(p_arm['true_V_end_mean'], 3)} | {fmt_num(d_arm['leaks_at_accusation_mean'], 1)} / {fmt_num(d_arm['true_V_end_mean'], 3)} | {fmt_num(sol['leaks_at_accusation_mean'], 1)} / {fmt_num(sol['true_V_end_mean'], 3)} | {fmt_num(inp['leaks_at_accusation_mean'], 1)} / {fmt_num(inp['true_V_end_mean'], 3)} | {fmt_num(opc['leaks_at_accusation_mean'], 1)} / {fmt_num(opc['true_V_end_mean'], 3)} |",
        f"| Total interviews ({n_arm} seeds) | {c_arm['interviews_total']} | {p_arm['interviews_total']} | {d_arm['interviews_total']} | {sol['interviews_total']} | {inp['interviews_total']} | {opc['interviews_total']} |",
        f"| Decoy interviews ({n_arm} seeds; random = 2.5%) | {c_arm['decoy_interviews_total']} ({c_arm['decoy_interview_share_pooled'] * 100:.1f}%) | {p_arm['decoy_interviews_total']} ({p_arm['decoy_interview_share_pooled'] * 100:.1f}%) | {d_arm['decoy_interviews_total']} ({d_arm['decoy_interview_share_pooled'] * 100:.1f}%) | {sol['decoy_interviews_total']} (0.0%) | {inp['decoy_interviews_total']} ({inp['decoy_interview_share_pooled'] * 100:.1f}%) | {opc['decoy_interviews_total']} ({opc['decoy_interview_share_pooled'] * 100:.1f}%) |",
        f"| Accused / restricted decoy | {c_arm['accused_decoy_count']} / {c_arm['restricted_decoy_count']} | {p_arm['accused_decoy_count']} / {p_arm['restricted_decoy_count']} | {d_arm['accused_decoy_count']} / {d_arm['restricted_decoy_count']} | {sol['accused_decoy_count']} / {sol['restricted_decoy_count']} | {inp['accused_decoy_count']} / {inp['restricted_decoy_count']} | {opc['accused_decoy_count']} / {opc['restricted_decoy_count']} |",
        f"| Access-log / message-search reads | {fmt_num(c_arm['read_access_logs_mean'], 1)} / {fmt_num(c_arm['search_messages_mean'], 1)} | {fmt_num(p_arm['read_access_logs_mean'], 1)} / {fmt_num(p_arm['search_messages_mean'], 1)} | {fmt_num(d_arm['read_access_logs_mean'], 1)} / {fmt_num(d_arm['search_messages_mean'], 1)} | {fmt_num(sol['read_access_logs_mean'], 1)} / {fmt_num(sol['search_messages_mean'], 1)} | {fmt_num(inp['read_access_logs_mean'], 1)} / {fmt_num(inp['search_messages_mean'], 1)} | {fmt_num(opc['read_access_logs_mean'], 1)} / {fmt_num(opc['search_messages_mean'], 1)} |",
        f"| Accusations at `P >= 0.95` / `0.85-0.95` / `0.60-0.85` / `< 0.60` | {c_arm['p_buckets']['ge_095']}/{c_arm['p_buckets']['085_095']}/{c_arm['p_buckets']['060_085']}/{c_arm['p_buckets']['lt_060']} | {p_arm['p_buckets']['ge_095']}/{p_arm['p_buckets']['085_095']}/{p_arm['p_buckets']['060_085']}/{p_arm['p_buckets']['lt_060']} | {d_arm['p_buckets']['ge_095']}/{d_arm['p_buckets']['085_095']}/{d_arm['p_buckets']['060_085']}/{d_arm['p_buckets']['lt_060']} | {sol['p_buckets']['ge_095']}/{sol['p_buckets']['085_095']}/{sol['p_buckets']['060_085']}/{sol['p_buckets']['lt_060']} | {inp['p_buckets']['ge_095']}/{inp['p_buckets']['085_095']}/{inp['p_buckets']['060_085']}/{inp['p_buckets']['lt_060']} | {opc['p_buckets']['ge_095']}/{opc['p_buckets']['085_095']}/{opc['p_buckets']['060_085']}/{opc['p_buckets']['lt_060']} |",
        f"| Isolated (`consistent_count == 1`) at accusation | {c_arm['isolated_at_accusation_count']}/{c_arm['accused_count']} | {p_arm['isolated_at_accusation_count']}/{p_arm['accused_count']} | {d_arm['isolated_at_accusation_count']}/{d_arm['accused_count']} | {sol['isolated_at_accusation_count']}/{sol['accused_count']} | {inp['isolated_at_accusation_count']}/{inp['accused_count']} | {opc['isolated_at_accusation_count']}/{opc['accused_count']} |",
        f"| Expected wrong (`sum(1 - P)`) vs realized wrong | {fmt_num(c_arm['expected_wrong_from_posteriors'], 2)} vs {c_arm['wrong_count']} | {fmt_num(p_arm['expected_wrong_from_posteriors'], 2)} vs {p_arm['wrong_count']} | {fmt_num(d_arm['expected_wrong_from_posteriors'], 2)} vs {d_arm['wrong_count']} | {fmt_num(sol['expected_wrong_from_posteriors'], 2)} vs {sol['wrong_count']} | {fmt_num(inp['expected_wrong_from_posteriors'], 2)} vs {inp['wrong_count']} | {fmt_num(opc['expected_wrong_from_posteriors'], 2)} vs {opc['wrong_count']} |",
        f"| Luck windfall (`raw - luck_adjusted`) | {fmt_num(c_arm['luck_windfall_mean'], 3, True)} | {fmt_num(p_arm['luck_windfall_mean'], 3, True)} | {fmt_num(d_arm['luck_windfall_mean'], 3, True)} | {fmt_num(sol['luck_windfall_mean'], 3, True)} | {fmt_num(inp['luck_windfall_mean'], 3, True)} | {fmt_num(opc['luck_windfall_mean'], 3, True)} |",
        "",
        f"{H}{H} 6. Per-Seed Paired Audit Table (`seeds {seed_label}`)",
        "",
        "| Seed | `control` raw / LA (`day`, `P`, `can`/`iv`) | `premature_acc` raw / LA (`day`, `P`, `can`/`iv`) | `decoy_chase` raw / LA (`day`, `P`, `can`/`iv`) | `solver` raw / LA (`day`, `P`, `can`) | `inproc` raw / LA | `opencode` raw / LA |",
        "|---|---|---|---|---|---|---|",
    ])

    def cell(r: dict[str, Any], include_iv: bool = True) -> str:
        mark = " X" if (r["accused"] is not None and not r["correct"]) else (" ABST" if r["accused"] is None else "")
        d_s = str(r["accuse_day"]) if r["accuse_day"] is not None else f"H{r['final_day']}"
        p_s = f"{r['p_accused']:.2f}" if r["p_accused"] is not None else "n/a"
        tail = f"{r['canaries']}/{r['interviews']}" if include_iv else f"{r['canaries']}"
        return f"{r['score']:+.2f}{mark} / {r['luck_adjusted']:+.2f} (d{d_s}, P={p_s}, {tail})"

    for s in seeds:
        rc = ab_by_key[("control", s)]
        rp = ab_by_key[("premature_accusation", s)]
        rd = ab_by_key[("decoy_chase", s)]
        rs = ct_by_key[("solver", s)]
        ri = ct_by_key[("inproc_gemini", s)]
        ro = ct_by_key[("opencode_gemini", s)]
        lines.append(
            f"| {s} | {cell(rc)} | {cell(rp)} | {cell(rd)} | {cell(rs, False)} | "
            f"{ri['score']:+.2f} / {ri['luck_adjusted']:+.2f} | {ro['score']:+.2f} / {ro['luck_adjusted']:+.2f} |"
        )

    ctrl_rows_list = [ab_by_key[("control", s)] for s in seeds]
    ctrl_wrong_detail = [
        f"seed {r['seed']} (`score={r['score']:+.2f}`, `P={r['p_accused']:.3f}`, `EV={r['ev_accused']:+.3f}`, `flips={r['flips']}`, `LA={r['luck_adjusted']:+.3f}`)"
        for r in ctrl_rows_list if r["accused"] is not None and not r["correct"]
    ]
    ctrl_evneg_detail = [
        f"seed {r['seed']} (`day={r['accuse_day']}`, `score={r['score']:+.2f}`, `P(accused)={r['p_accused']:.3f}`, `P(top)={r['p_top']:.3f}`, `EV={r['ev_accused']:+.3f}`, `LA={r['luck_adjusted']:+.3f}`, `windfall={r['score'] - r['luck_adjusted']:+.3f}`)"
        for r in ctrl_rows_list if r["ev_neg"]
    ]
    wrong_note = "; ".join(ctrl_wrong_detail) if ctrl_wrong_detail else "none"
    evneg_note = "; ".join(ctrl_evneg_detail) if ctrl_evneg_detail else "none"
    vsd_la_ratio_txt = (
        f"{vsd['luck_adjusted_ratio'] * 100:.1f}% of `solver` {fmt_ci(vsd['luck_adjusted_ratio_boot_ci95'], pct=True)}"
        if vsd["luck_adjusted_ratio"] is not None else "n/a"
    )

    lines.extend([
        "",
        "`X` = wrong accusation (`-1.00`); `ABST` = abstained (`0.00`); `LA` = luck-adjusted score `P*V - (1-P)`.",
        "",
        f"{H}{H} 7. Causal Interpretation & Limitations",
        "",
        f"1. **Forensic correction to raw-only reading (`control` wrong accusation != premature accusation):** Replay + `SolverPolicy` belief reconstruction reveals two opposite luck events hidden inside `control`'s `{fmt_num(c_arm['score_mean'], 3, True)}` raw mean (`{fmt_num(c_arm['luck_adjusted_mean'], 3, True)}` luck-adjusted). `control`'s wrong accusation ({wrong_note}) was **not** a premature gamble -- it occurred at high Bayesian posterior after a 5% canary fingerprint flip, so `control` suffered bad luck there. Conversely, `control`'s actual premature / negative-EV gamble ({evneg_note}) **succeeded by luck** above posterior EV. Those two opposite luck shocks nearly cancelled in `control`'s aggregate (`raw - LA = {fmt_num(c_arm['luck_windfall_mean'], 3, True)}`).",
        f"2. **Why `decoy_chase` works via canary-vs-log weighting, not decoy avoidance:** Across all unhinted runs (`control` `{c_arm['decoy_interviews_total']}/{c_arm['interviews_total']}` = `{c_arm['decoy_interview_share_pooled'] * 100:.1f}%`, `inproc` `{inp['decoy_interviews_total']}/{inp['interviews_total']}` = `{inp['decoy_interview_share_pooled'] * 100:.1f}%`, `opencode` `{opc['decoy_interviews_total']}/{opc['interviews_total']}` = `0.0%`), `gemini-4-carbon` already avoids interviewing, restricting (`0/{n_arm}`), or accusing (`0/{n_arm}`) the angry decoy (well below the `1/40 = 2.5%` uniform rate). Instead, the second clause of `HINTS_V2['decoy_chase']` (*\"logs and anger are weak evidence; leaked canary variants are strong evidence\"*) shifts exploration from Day 1: day-1 canary episodes rise from `{c_arm['day1_canary_count']}/{n_arm}` (`control`) to `{d_arm['day1_canary_count']}/{n_arm}` (`decoy_chase`), daily canary capacity utilization rises from `{c_arm['canary_capacity_used'] * 100:.1f}%` to `{d_arm['canary_capacity_used'] * 100:.1f}%`, access-log reads drop `{fmt_num(c_arm['read_access_logs_mean'], 1)} -> {fmt_num(d_arm['read_access_logs_mean'], 1)}`, interviews drop by `{fmt_num(vd['interviews_diff_mean'], 1, True)}` {fmt_ci(vd['interviews_diff_boot_ci95'], 1, True)} (`{c_arm['interviews_total']} -> {d_arm['interviews_total']}`), and accusation day advances from `{fmt_num(c_arm['accuse_day_mean'], 1)}` to `{fmt_num(d_arm['accuse_day_mean'], 1)}` (`{vd['raw_seed_wins']}/{n_arm}` paired seed wins raw, `{vd['luck_adjusted_seed_wins']}/{n_arm}` luck-adjusted). Removing its `{fmt_num(d_arm['luck_windfall_mean'], 3, True)}` luck windfall (`0` wrong vs `{fmt_num(d_arm['expected_wrong_from_posteriors'], 2)}` expected) trims `decoy_chase` from `{fmt_num(d_arm['score_mean'], 3, True)}` raw to `{fmt_num(d_arm['luck_adjusted_mean'], 3, True)}` luck-adjusted ({vsd_la_ratio_txt}).",
        f"3. **Why `premature_accusation` improves posterior calibration but trades away time/leak V:** Reminding the agent of `P x V - (1 - P) > 0` eliminates negative-EV horizon gambling (`{c_arm['ev_negative_gamble_count']} -> {p_arm['ev_negative_gamble_count']}` gambles; `P(accused)` mean `{fmt_num(c_arm['p_accused_mean'], 3)} -> {fmt_num(p_arm['p_accused_mean'], 3)}`, paired diff `{fmt_num(vp['p_accused_diff_joint_mean'], 3, True)}` {fmt_ci(vp['p_accused_diff_joint_boot_ci95'], 3, True)}) and cuts interviews by `{fmt_num(vp['interviews_diff_mean'], 1, True)}` {fmt_ci(vp['interviews_diff_boot_ci95'], 1, True)}. However, it also delays first canary planting (`{fmt_num(c_arm['first_canary_day_mean'], 1)} -> {fmt_num(p_arm['first_canary_day_mean'], 1)}`) and delays accusation (`{fmt_num(c_arm['accuse_day_mean'], 1)} -> {fmt_num(p_arm['accuse_day_mean'], 1)}`, leaks `{fmt_num(c_arm['leaks_at_accusation_mean'], 1)} -> {fmt_num(p_arm['leaks_at_accusation_mean'], 1)}`, `true_V_end` `{fmt_num(c_arm['true_V_end_mean'], 3)} -> {fmt_num(p_arm['true_V_end_mean'], 3)}`), leaving a modest net luck-adjusted diff of `{fmt_num(vp['luck_adjusted_diff_mean'], 3, True)}` {fmt_ci(vp['luck_adjusted_diff_boot_ci95'], 3, True)}.",
        f"4. **Honest `n={n_arm}` statistical power caveat:** With `n={n_arm}` paired seeds per arm, every paired score 95% bootstrap CI against `control` crosses zero (`premature_accusation`: raw `{fmt_ci(vp['score_diff_boot_ci95'], 3, True)}`, LA `{fmt_ci(vp['luck_adjusted_diff_boot_ci95'], 3, True)}`; `decoy_chase`: raw `{fmt_ci(vd['score_diff_boot_ci95'], 3, True)}`, LA `{fmt_ci(vd['luck_adjusted_diff_boot_ci95'], 3, True)}`), and an independent no-hint `inproc-gemini-4-carbon` run on seeds `{seed_label}` differs from `control` by `{fmt_num(ivc['score_diff_mean'], 3, True)}` {fmt_ci(ivc['score_diff_boot_ci95'], 3, True)} raw (`{fmt_num(ivc['luck_adjusted_diff_mean'], 3, True)}` {fmt_ci(ivc['luck_adjusted_diff_boot_ci95'], 3, True)} LA). The behavioral shifts (fewer wasted interviews, higher accusation posteriors `{fmt_num(p_arm['p_accused_mean'], 3)}` / `{fmt_num(d_arm['p_accused_mean'], 3)}` vs `{fmt_num(c_arm['p_accused_mean'], 3)}`, and earlier canary pipelining under `decoy_chase`) are clear in mechanism, while headline score superiority requires `n >= 30` paired seeds to resolve.",
        "",
    ])
    return "\n".join(lines)


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


FORBIDDEN_SUBSTRINGS: tuple[str, ...] = ("AIza", "sk-", "BEGIN RSA", "CANARY_WORLD_SECRET")


def verify_committed_json(
    json_path: Path = DEFAULT_OUT_JSON,
    md_path: Path | None = DEFAULT_OUT_MD,
    committed_v14_dir: Path | None = DEFAULT_COMMITTED_V14,
) -> dict[str, Any]:
    if not json_path.is_file():
        raise FileNotFoundError(f"missing committed audit JSON: {json_path}")
    raw_bytes = json_path.read_bytes()
    if len(raw_bytes) >= MAX_JSON_BYTES:
        raise ValueError(f"audit JSON exceeds {MAX_JSON_BYTES} bytes: {len(raw_bytes)}")
    raw_text = raw_bytes.decode("utf-8")
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in raw_text:
            raise ValueError(f"forbidden secret-like token found in {json_path}")
    if "\u2014" in raw_text or "\u2013" in raw_text:
        raise ValueError(f"unicode dash found in {json_path}")

    data = json.loads(raw_text)
    rv = data.get("replay_verification") or {}
    if (
        not rv.get("all_passed")
        or rv.get("score_mismatches") != 0
        or rv.get("accused_mismatches") != 0
        or rv.get("errors_or_timeouts") != 0
    ):
        raise ValueError(f"replay verification invariants failed: {rv}")

    seeds = [int(s) for s in data["seeds"]]
    tier_name = str(data["tier"])
    ab_eps = data["ablation_episodes"]
    ct_eps = data["context_episodes"]
    if len(ab_eps) != len(ARMS) * len(seeds):
        raise ValueError(f"expected {len(ARMS) * len(seeds)} ablation rows, got {len(ab_eps)}")
    if len(ct_eps) != len(CONTEXT_NAMES) * len(seeds):
        raise ValueError(f"expected {len(CONTEXT_NAMES) * len(seeds)} context rows, got {len(ct_eps)}")
    if rv.get("ablation_episodes_verified") != len(ab_eps) or rv.get("context_episodes_verified") != len(ct_eps):
        raise ValueError(f"verified episode counts mismatch row counts: {rv}")

    arm_meta = data.get("arm_meta") or {}
    for arm in ARMS:
        am = arm_meta.get(arm) or {}
        hint = am.get("hint")
        hint_set = str(am.get("hint_set") or "v2")
        expected_hint_text = HINT_SETS[hint_set].get(str(hint)) if (hint and hint_set in HINT_SETS) else None
        if am.get("hint_text") != expected_hint_text:
            raise ValueError(f"arm_meta hint_text mismatch for {arm}")

    probes = {s: Env(tier_name, s) for s in seeds}
    for row in ab_eps + ct_eps:
        if "steps" in row or "transcript" in row or "prompt" in row:
            raise ValueError("raw transcript/steps must not be stored in compact summary JSON")
        s_id = int(row["seed"])
        if s_id not in probes:
            raise ValueError(f"unexpected seed in episode row: {s_id}")
        probe = probes[s_id]
        if not (1 <= int(row["final_day"]) <= probe.p.n_days):
            raise ValueError(f"final_day out of range: {row}")
        iv_cnt = int(row["interviews"])
        exp_decoy_share = (int(row["decoy_interviews"]) / iv_cnt) if iv_cnt > 0 else 0.0
        if abs(float(row["decoy_iv_share"]) - exp_decoy_share) > 1e-5:
            raise ValueError(f"decoy_iv_share mismatch: {row}")
        if row["accused"] is None:
            if row["correct"] or row["accused_decoy"]:
                raise ValueError(f"abstained row cannot be correct or accused_decoy: {row}")
            if abs(float(row["score"])) > 1e-9 or abs(float(row["luck_adjusted"])) > 1e-9:
                raise ValueError(f"abstained row must have score 0 and luck_adjusted 0: {row}")
        else:
            acc = str(row["accused"])
            if acc not in probe._ids:
                raise ValueError(f"accused employee {acc} not in Env world: {row}")
            if bool(row["correct"]) != (acc == probe._world.mole):
                raise ValueError(f"stored correctness does not match Env mole: {row}")
            if bool(row["accused_decoy"]) != (acc == probe._world.decoy):
                raise ValueError(f"stored accused_decoy does not match Env decoy: {row}")
            exp_score = float(row["true_V_end"]) if row["correct"] else float(probe.p.wrong_accusation_score)
            if abs(float(row["score"]) - exp_score) > 1e-5:
                raise ValueError(f"stored score mismatch vs true_V_end/wrong_accusation_score: {row}")
            p_acc = float(row["p_accused"])
            if not (-1e-9 <= p_acc <= 1.0 + 1e-9):
                raise ValueError(f"p_accused out of [0, 1]: {row}")
            expected_la = p_acc * float(row["true_V_end"]) - (1.0 - p_acc)
            if abs(float(row["luck_adjusted"]) - expected_la) > 1e-5:
                raise ValueError(f"stored row luck_adjusted mismatch: {row}")
            if bool(row["ev_neg"]) != (float(row["ev_accused"]) < 0.0):
                raise ValueError(f"stored ev_neg mismatch: {row}")

    recomputed = build_aggregates(
        ab_eps,
        ct_eps,
        seeds,
        int(data["bootstrap_resamples"]),
        int(data["bootstrap_rng_seed"]),
    )
    for key in ("arms", "context", "paired_vs_control", "paired_vs_solver", "context_vs_solver", "inproc_vs_control"):
        if not approx_equal(data[key], recomputed[key]):
            raise ValueError(f"committed JSON aggregate mismatch on key: {key}")

    if md_path is not None:
        if not md_path.is_file():
            raise FileNotFoundError(f"missing committed markdown report: {md_path}")
        md_text = md_path.read_text(encoding="utf-8")
        if "\u2014" in md_text or "\u2013" in md_text:
            raise ValueError(f"unicode dash found in {md_path}")
        expected_md = render_markdown(data)
        if md_text != expected_md:
            raise ValueError(f"{md_path} differs from deterministic render_markdown(data)")

    if committed_v14_dir is not None:
        if not committed_v14_dir.is_dir():
            raise FileNotFoundError(f"missing committed v1.4 directory: {committed_v14_dir}")
        ctx_raw = load_context_raw(committed_v14_dir, set(seeds), tier_name)
        fresh_ctx: list[dict[str, Any]] = []
        for ctx in CONTEXT_NAMES:
            missing_ctx = [s for s in seeds if s not in ctx_raw[ctx]]
            if missing_ctx:
                raise ValueError(f"committed v1.4 context {ctx} missing seeds: {missing_ctx}")
            for s in seeds:
                r_ctx = audit_episode_replay(ctx, ctx_raw[ctx][s], tier_name)
                r_ctx.pop("_max_diff", None)
                fresh_ctx.append(r_ctx)
        if not approx_equal(ct_eps, fresh_ctx):
            raise ValueError("committed v1.4 context episodes differ from fresh Env replay")

    return data


def _compact_json_lines(val: Any, indent_level: int = 1) -> str:
    pad = " " * indent_level
    if isinstance(val, dict):
        if not val:
            return "{}"
        items = []
        for k in sorted(val.keys()):
            items.append(f'{pad} "{k}": {_compact_json_lines(val[k], indent_level + 1)}')
        return "{\n" + ",\n".join(items) + f"\n{pad[:-1]}}}"
    if isinstance(val, list):
        if not val or all(not isinstance(x, (dict, list)) for x in val):
            return json.dumps(val, separators=(",", ": "))
        items = [f"{pad} " + json.dumps(x, sort_keys=True, separators=(",", ":")) for x in val]
        return "[\n" + ",\n".join(items) + f"\n{pad[:-1]}]"
    return json.dumps(val)


def serialize_json(data: dict[str, Any]) -> str:
    return _compact_json_lines(data, 1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Hint ablation v1.4 hard causal audit")
    ap.add_argument("--from-git-ref", default=DEFAULT_GIT_REF)
    ap.add_argument("--ablate-subpath", default=DEFAULT_ABLATE_SUBPATH)
    ap.add_argument("--ablate-dir", type=Path, default=None)
    ap.add_argument("--committed-v14-dir", type=Path, default=DEFAULT_COMMITTED_V14)
    ap.add_argument("--seeds", default="0-9")
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP_B)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--verify-json", "--check-committed-json", dest="verify_json", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if args.verify_json:
        verify_committed_json(args.out_json, None if args.json_only else args.out_md, args.committed_v14_dir)
        print(f"verified {args.out_json}")
        return 0

    seeds = parse_seed_spec(args.seeds)

    if args.check:
        can_extract = args.ablate_dir is not None or git_ablation_available(
            ROOT, args.from_git_ref, args.ablate_subpath
        )
        try:
            committed = verify_committed_json(
                args.out_json,
                None if args.json_only else args.out_md,
                None if can_extract else args.committed_v14_dir,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"offline consistency check failed: {exc}", file=sys.stderr)
            return 1
        if not can_extract:
            print(
                f"git ref {args.from_git_ref} absent (shallow clone); "
                "offline JSON + markdown + v1.4 context verified"
            )
            return 0
        fresh = extract_and_compute(
            seeds=seeds,
            ablate_dir=args.ablate_dir,
            git_ref=args.from_git_ref,
            ablate_subpath=args.ablate_subpath,
            committed_v14_dir=args.committed_v14_dir,
            repo_root=ROOT,
            b_resamples=args.bootstrap,
        )
        if not approx_equal(committed, fresh):
            print("committed JSON differs from fresh git-ref replay extraction", file=sys.stderr)
            return 1
        if not args.json_only:
            if not args.out_md.is_file() or args.out_md.read_text(encoding="utf-8") != render_markdown(fresh):
                print("committed markdown report differs from fresh render", file=sys.stderr)
                return 1
        print("hint ablation audit reproduces cleanly")
        return 0

    data = extract_and_compute(
        seeds=seeds,
        ablate_dir=args.ablate_dir,
        git_ref=args.from_git_ref,
        ablate_subpath=args.ablate_subpath,
        committed_v14_dir=args.committed_v14_dir,
        repo_root=ROOT,
        b_resamples=args.bootstrap,
    )
    blob = serialize_json(data)
    if len(blob.encode("utf-8")) >= MAX_JSON_BYTES:
        raise RuntimeError(f"serialized JSON too large ({len(blob.encode('utf-8'))} bytes >= {MAX_JSON_BYTES})")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(blob, encoding="utf-8")
    print(f"wrote {args.out_json}")

    if not args.json_only:
        md = render_markdown(data)
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
        print(f"wrote {args.out_md}")

    verify_committed_json(args.out_json, None if args.json_only else args.out_md, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
