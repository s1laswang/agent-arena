"""Seed-hygiene guard, replay-verified paired evaluator, and luck-adjusted scorer for Canary tiebreak models."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
from typing import Any, Callable, Iterable

from canary.env import Env
from canary.eval import parse_seeds, run_episode as canary_run_episode
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS as RULE_TIERS, TRAIN_SEEDS
from canary.solver.policy import SolverPolicy
from canary import world as canary_world

EVAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
DEFAULT_HELD_OUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
DEFAULT_BASE_MODEL = os.path.expanduser("~/agent-arena-data/models/Qwen2.5-1.5B-Instruct")
SNAPSHOT_COMPACT_RENDER = Path("/tmp/fleet-silas/shared/tiebreak/code_snapshot/train/compact_render.py")

_UNSET_SECRET_MARKERS: frozenset[str] = frozenset({
    "",
    "none",
    "null",
    "unset",
    "missing",
    "unknown",
    "random",
    "per_process",
    "per-process",
    "proc_secret",
    "os.urandom",
    "urandom",
    "ephemeral",
})
_UNSET_SECRET_PREFIXES: tuple[str, ...] = (
    "unset",
    "proc:",
    "proc_",
    "per_process",
    "per-process",
    "random:",
    "random_",
    "urandom",
    "ephemeral",
)


def load_compact_render_module():
    if "train.compact_render" in sys.modules:
        return sys.modules["train.compact_render"]
    try:
        return importlib.import_module("train.compact_render")
    except ModuleNotFoundError:
        if not SNAPSHOT_COMPACT_RENDER.is_file():
            raise
        spec = importlib.util.spec_from_file_location("train.compact_render", str(SNAPSHOT_COMPACT_RENDER))
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load compact_render from {SNAPSHOT_COMPACT_RENDER}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["train.compact_render"] = mod
        spec.loader.exec_module(mod)
        return mod


def _secret_bytes(world_secret: bytes | bytearray | str | None) -> bytes | None:
    if world_secret is None:
        return None
    if isinstance(world_secret, str):
        if not world_secret:
            return None
        return world_secret.encode("utf-8")
    if isinstance(world_secret, (bytes, bytearray)):
        if len(world_secret) == 0:
            return None
        return bytes(world_secret)
    raise TypeError(f"unsupported world_secret type: {type(world_secret)!r}")


def compute_world_secret_tag(world_secret: bytes | bytearray | str | None) -> str | None:
    sec = _secret_bytes(world_secret)
    if sec is None:
        return None
    return "sha256:" + hashlib.sha256(sec).hexdigest()[:16]


def active_world_secret_tag(explicit_secret: bytes | bytearray | str | None = None) -> str | None:
    if explicit_secret is not None:
        return compute_world_secret_tag(explicit_secret)
    in_proc = getattr(canary_world, "_SET_SECRET", None)
    if in_proc is not None:
        return compute_world_secret_tag(in_proc)
    env_sec = os.environ.get("CANARY_WORLD_SECRET")
    if env_sec:
        return compute_world_secret_tag(env_sec)
    salt_path = Path(canary_world.__file__).resolve().parent.parent / "data" / "worlds" / "judge" / "SALT"
    if salt_path.is_file():
        return compute_world_secret_tag(salt_path.read_bytes())
    return None


@contextmanager
def _world_secret_scope(world_secret: bytes | bytearray | str | None):
    sec = _secret_bytes(world_secret)
    if sec is None:
        yield
        return
    prev = getattr(canary_world, "_SET_SECRET", None)
    canary_world.set_world_secret(sec)
    try:
        yield
    finally:
        canary_world.set_world_secret(prev)


def _is_unset_secret_tag(tag: Any) -> bool:
    if tag is None or not isinstance(tag, str):
        return True
    norm = tag.strip().lower()
    if norm in _UNSET_SECRET_MARKERS:
        return True
    return norm.startswith(_UNSET_SECRET_PREFIXES)


def _coerce_seed_list(seeds: Iterable[Any], label: str, violations: list[str]) -> list[int]:
    out: list[int] = []
    bad_type = False
    for s in seeds:
        if isinstance(s, bool) or not isinstance(s, int):
            bad_type = True
            continue
        out.append(int(s))
    if bad_type:
        violations.append(f"non_int_{label}_seed")
    return out


def audit_seed_hygiene(
    train_seeds: Iterable[int],
    eval_seeds: Iterable[int],
    world_secret_tags: dict[str, str | None] | Iterable[str | None] | None = None,
) -> dict[str, Any]:
    violations: list[str] = []
    train_list = _coerce_seed_list(train_seeds, "train", violations)
    eval_list = _coerce_seed_list(eval_seeds, "eval", violations)

    train_set = set(train_list)
    eval_set = set(eval_list)

    negative_leaks = sorted(s for s in train_set if s < 0)
    dev_leaks = sorted(s for s in train_set if s in DEV_SEEDS or 0 <= s <= 9_999)
    pre_train_leaks = sorted(s for s in train_set if 10_000 <= s <= 99_999)
    post_train_leaks = sorted(s for s in train_set if 200_000 <= s < 800_000)
    heldout_leaks = sorted(s for s in train_set if s in HELDOUT_SEEDS or 800_000 <= s < 900_000)
    judge_leaks = sorted(s for s in train_set if s in JUDGE_SEEDS or s >= 900_000)
    outside_train = sorted(s for s in train_set if s not in TRAIN_SEEDS or not (100_000 <= s <= 199_999))
    overlap = sorted(train_set & eval_set)

    if negative_leaks:
        violations.append("train_negative_seed")
    if dev_leaks:
        violations.append("train_dev_seed_leak")
    if pre_train_leaks:
        violations.append("train_pre_train_range_leak")
    if post_train_leaks:
        violations.append("train_post_train_range_leak")
    if heldout_leaks:
        violations.append("train_heldout_seed_leak")
    if judge_leaks:
        violations.append("train_judge_seed_leak")
    if outside_train and not (
        negative_leaks or dev_leaks or pre_train_leaks or post_train_leaks or heldout_leaks or judge_leaks
    ):
        violations.append("train_outside_train_seeds")
    if overlap:
        violations.append("train_eval_seed_overlap")

    heldout_eval = any(s in HELDOUT_SEEDS or s in JUDGE_SEEDS or s >= 800_000 for s in eval_set)
    unset_secret_runs: list[str] = []
    distinct_secret_tags: list[str] = []
    world_secret_paired: bool | None = None if heldout_eval else True

    if world_secret_tags is not None:
        if isinstance(world_secret_tags, dict):
            tag_items = [(str(k), v) for k, v in world_secret_tags.items()]
        else:
            tag_items = [(f"run_{idx}", v) for idx, v in enumerate(world_secret_tags)]

        valid_tags: set[str] = set()
        for run_name, raw_tag in tag_items:
            if _is_unset_secret_tag(raw_tag):
                unset_secret_runs.append(run_name)
            else:
                valid_tags.add(str(raw_tag).strip())
        distinct_secret_tags = sorted(valid_tags)

        if heldout_eval:
            if not tag_items:
                violations.append("heldout_empty_world_secret_tags")
                world_secret_paired = False
            else:
                if unset_secret_runs:
                    violations.append("heldout_unset_world_secret")
                if len(distinct_secret_tags) > 1:
                    violations.append("heldout_mismatched_world_secret_tags")
                world_secret_paired = (not unset_secret_runs) and len(distinct_secret_tags) == 1
        else:
            world_secret_paired = True

    ok = len(violations) == 0
    return {
        "ok": ok,
        "passed": ok,
        "n_train_seeds": len(train_list),
        "n_eval_seeds": len(eval_list),
        "n_unique_train_seeds": len(train_set),
        "n_unique_eval_seeds": len(eval_set),
        "negative_leaks": negative_leaks,
        "dev_leaks": dev_leaks,
        "pre_train_leaks": pre_train_leaks,
        "post_train_leaks": post_train_leaks,
        "heldout_leaks": heldout_leaks,
        "judge_leaks": judge_leaks,
        "outside_train_seeds": outside_train,
        "train_eval_overlap": overlap,
        "heldout_eval": heldout_eval,
        "world_secret_checked": world_secret_tags is not None,
        "world_secret_paired": world_secret_paired,
        "unset_secret_runs": unset_secret_runs,
        "distinct_world_secret_tags": distinct_secret_tags,
        "violations": violations,
    }


def classify_episode_data_rule(ep: dict[str, Any]) -> tuple[bool, list[str]]:
    meta = ep.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    reasons: list[str] = []

    if ep.get("end_reason") == "error":
        reasons.append("end_reason_error")
    rc_top = ep.get("rc")
    rc_meta = meta_dict.get("rc")
    if rc_top == "timeout" or rc_meta == "timeout" or ep.get("end_reason") == "timeout":
        reasons.append("rc_timeout")
    if ep.get("valid") is False or meta_dict.get("valid") is False:
        reasons.append("valid_false")
    err_str = meta_dict.get("error")
    if isinstance(err_str, str) and err_str.startswith("infra:"):
        reasons.append("infra_error")

    return len(reasons) == 0, reasons


def _resolve_episode_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_dir():
        cand = p / "episodes.jsonl"
        if cand.is_file():
            return cand
    return p


def _extract_step_tool_args(st: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(st, dict):
        tool = str(st.get("tool", ""))
        raw_args = st.get("args")
    else:
        tool = str(getattr(st, "tool", ""))
        raw_args = getattr(st, "args", None)
    args = dict(raw_args) if isinstance(raw_args, dict) else {}
    return tool, args


def _replay_in_current_world(ep_dict: dict[str, Any]) -> tuple[Env, SolverPolicy, Any]:
    tier = str(ep_dict["tier"])
    seed = int(ep_dict["seed"])
    agent = str(ep_dict.get("agent", "replay"))

    env = Env(tier, seed)
    sp = SolverPolicy(env.p)
    sp.reset(env.tools_spec(), env.instruction())
    sp.obs.employees = [f"e{i:02d}" for i in range(env.p.n_employees)]

    for raw_step in ep_dict.get("steps") or []:
        if env.done:
            break
        tool, args = _extract_step_tool_args(raw_step)
        res = env.call(tool, args)
        if not (tool == "accuse" and res.ok):
            sp._ingest(env.history[-1])
            sp.seen = len(env.history)

    replay = env.result(agent)
    return env, sp, replay


def luck_adjusted_episode_ev(
    ep_dict: dict[str, Any],
    world_secret: bytes | bytearray | str | None = None,
) -> dict[str, Any]:
    with _world_secret_scope(world_secret):
        env, sp, replay = _replay_in_current_world(ep_dict)

    post = sp.belief() if sp.obs.employees else {}
    if post:
        ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
        top_emp, top_p = ranked[0][0], float(ranked[0][1])
    else:
        top_emp, top_p = None, 0.0

    true_v = round(float(env.V), 10)
    known_v = round(float(env.visible_V()), 10)
    breakeven_p = 1.0 / (1.0 + known_v)
    accused = replay.accused

    if accused is not None and replay.end_reason == "accused":
        p_emp: float | None = float(post.get(accused, 0.0))
        ev = p_emp * true_v - (1.0 - p_emp)
    else:
        p_emp = None
        ev = 0.0

    meta = ep_dict.get("meta")
    meta_dict = meta if isinstance(meta, dict) else {}
    total_calls = len(env.history)
    env_failed_calls = sum(1 for st in env.history if not (st.result or {}).get("ok", True))
    unparsed_calls = int(meta_dict.get("invalid_calls", 0) or 0)
    invalid_calls = min(total_calls, env_failed_calls + max(0, unparsed_calls))
    valid_calls = max(0, total_calls - invalid_calls)

    replay_match = True
    if "score" in ep_dict:
        replay_match = (
            abs(replay.score - float(ep_dict["score"])) < 1e-9
            and replay.accused == ep_dict.get("accused")
        )

    return {
        "tier": str(ep_dict["tier"]),
        "seed": int(ep_dict["seed"]),
        "agent": str(ep_dict.get("agent", "replay")),
        "end_reason": replay.end_reason,
        "final_day": int(replay.final_day),
        "accused": accused,
        "correct": bool(replay.correct),
        "raw_score": float(replay.score),
        "true_v": true_v,
        "known_v": known_v,
        "breakeven_p": breakeven_p,
        "p_emp": p_emp,
        "p_accused": p_emp,
        "top_emp": top_emp,
        "top_p": top_p,
        "luck_adjusted_ev": float(ev),
        "ev": float(ev),
        "total_calls": total_calls,
        "valid_calls": valid_calls,
        "invalid_calls": invalid_calls,
        "replay_match": replay_match,
    }


def _detect_run_secret_tag(
    file_path: Path | None,
    episodes: list[dict[str, Any]],
    world_secret: Any,
) -> str | None:
    if file_path is not None:
        meta_json_path = file_path.parent / "meta.json"
        if meta_json_path.is_file():
            try:
                run_meta = json.loads(meta_json_path.read_text(encoding="utf-8"))
                if isinstance(run_meta, dict) and "world_secret_tag" in run_meta:
                    val = run_meta.get("world_secret_tag")
                    return str(val) if val is not None else "unset"
            except (OSError, json.JSONDecodeError):
                pass

    ep_tags: set[str] = set()
    saw_explicit_unset = False
    for ep in episodes:
        meta = ep.get("meta")
        if isinstance(meta, dict) and "world_secret_tag" in meta:
            tval = meta.get("world_secret_tag")
            if _is_unset_secret_tag(tval):
                saw_explicit_unset = True
            else:
                ep_tags.add(str(tval).strip())
    if saw_explicit_unset:
        return "unset"
    if len(ep_tags) == 1:
        return next(iter(ep_tags))
    if len(ep_tags) > 1:
        return "mixed:" + ",".join(sorted(ep_tags))
    if world_secret is not None:
        return compute_world_secret_tag(world_secret)
    return None


def verify_episode_file(
    path: str | Path,
    world_secret: bytes | bytearray | str | None = None,
) -> dict[str, Any]:
    file_path = _resolve_episode_path(path)
    raw_lines = file_path.read_text(encoding="utf-8").splitlines()

    all_records: list[dict[str, Any]] = []
    valid_episodes: list[dict[str, Any]] = []
    excluded_episodes: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    replay_verified_count = 0

    with _world_secret_scope(world_secret):
        for line_no, line in enumerate(raw_lines, start=1):
            if not line.strip():
                continue
            ep = json.loads(line)
            all_records.append(ep)
            is_valid, reasons = classify_episode_data_rule(ep)
            if not is_valid:
                excluded_episodes.append({
                    "line": line_no,
                    "tier": ep.get("tier"),
                    "seed": ep.get("seed"),
                    "agent": ep.get("agent"),
                    "recorded_score": ep.get("score"),
                    "end_reason": ep.get("end_reason"),
                    "reasons": reasons,
                })
                continue

            env = Env(str(ep["tier"]), int(ep["seed"]))
            for raw_step in ep.get("steps") or []:
                if env.done:
                    break
                tool, args = _extract_step_tool_args(raw_step)
                env.call(tool, args)
            replay = env.result("replay")

            rec_score = float(ep["score"])
            rec_accused = ep.get("accused")
            score_ok = abs(replay.score - rec_score) < 1e-9
            accused_ok = replay.accused == rec_accused
            if score_ok and accused_ok:
                replay_verified_count += 1
                valid_episodes.append(ep)
            else:
                mismatches.append({
                    "line": line_no,
                    "tier": ep.get("tier"),
                    "seed": ep.get("seed"),
                    "agent": ep.get("agent"),
                    "recorded_score": rec_score,
                    "replay_score": replay.score,
                    "recorded_accused": rec_accused,
                    "replay_accused": replay.accused,
                })

    mean_score = (
        sum(float(e["score"]) for e in valid_episodes) / len(valid_episodes)
        if valid_episodes
        else None
    )
    replay_ok = len(mismatches) == 0
    secret_tag = _detect_run_secret_tag(file_path, all_records, world_secret)

    return {
        "path": str(file_path),
        "ok": replay_ok,
        "replay_ok": replay_ok,
        "data_rule_clean": len(excluded_episodes) == 0,
        "total_count": len(all_records),
        "valid_count": len(valid_episodes),
        "excluded_count": len(excluded_episodes),
        "replay_verified_count": replay_verified_count,
        "mismatch_count": len(mismatches),
        "mean_score": mean_score,
        "excluded_episodes": excluded_episodes,
        "flagged_episodes": excluded_episodes,
        "mismatches": mismatches,
        "valid_episodes": valid_episodes,
        "world_secret_tag": secret_tag,
    }


def _bootstrap_mean_ci(
    xs: list[float],
    bootstrap_n: int,
    rng: random.Random,
) -> tuple[float, float, float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0
    mean_val = sum(xs) / n
    if n < 2 or bootstrap_n <= 0:
        return mean_val, mean_val, mean_val, 0.0
    choices = rng.choices
    samples = [sum(choices(xs, k=n)) / n for _ in range(bootstrap_n)]
    samples.sort()
    lo_idx = int(0.025 * bootstrap_n)
    hi_idx = min(bootstrap_n - 1, int(0.975 * bootstrap_n))
    lo = samples[lo_idx]
    hi = samples[hi_idx]
    half = 0.5 * (hi - lo)
    return mean_val, lo, hi, half


def _normalize_run_specs(run_specs: Any) -> list[tuple[str, Any]]:
    if isinstance(run_specs, dict):
        return [(str(k), v) for k, v in run_specs.items()]
    if not isinstance(run_specs, (list, tuple)):
        raise TypeError(f"unsupported run_specs type: {type(run_specs)!r}")

    out: list[tuple[str, Any]] = []
    seen_labels: set[str] = set()
    for idx, item in enumerate(run_specs):
        if isinstance(item, tuple) and len(item) == 2:
            label, src = str(item[0]), item[1]
        elif isinstance(item, dict) and ("path" in item or "episodes" in item):
            label = str(item.get("label") or item.get("name") or f"run_{idx}")
            src = item["episodes"] if "episodes" in item else item["path"]
        elif isinstance(item, str) and "=" in item and not Path(item).exists():
            lhs, rhs = item.split("=", 1)
            label, src = lhs.strip(), rhs.strip()
        else:
            p = Path(item)
            base_lbl = p.parent.name if p.name == "episodes.jsonl" and p.parent.name else p.stem
            label = base_lbl or f"run_{idx}"
            src = item
        if label in seen_labels:
            label = f"{label}_{idx}"
        seen_labels.add(label)
        out.append((label, src))
    return out


def _load_and_score_run(
    label: str,
    src: Any,
    world_secret: bytes | bytearray | str | None,
) -> dict[str, Any]:
    if isinstance(src, (str, Path)):
        ver = verify_episode_file(src, world_secret=world_secret)
        if not ver["replay_ok"]:
            raise ValueError(f"replay mismatch in run {label!r}: {ver['mismatches'][:3]}")
        raw_valid = ver["valid_episodes"]
        excluded = ver["excluded_episodes"]
        secret_tag = ver["world_secret_tag"]
        path_str: str | None = ver["path"]
    elif isinstance(src, list):
        raw_valid = []
        excluded = []
        for idx, ep in enumerate(src):
            is_valid, reasons = classify_episode_data_rule(ep)
            if not is_valid:
                excluded.append({
                    "line": idx + 1,
                    "tier": ep.get("tier"),
                    "seed": ep.get("seed"),
                    "agent": ep.get("agent"),
                    "recorded_score": ep.get("score"),
                    "end_reason": ep.get("end_reason"),
                    "reasons": reasons,
                })
            else:
                raw_valid.append(ep)
        secret_tag = _detect_run_secret_tag(None, src, world_secret)
        path_str = None
    else:
        raise TypeError(f"unsupported run source for {label!r}: {type(src)!r}")

    scored: list[dict[str, Any]] = []
    with _world_secret_scope(world_secret):
        for ep in raw_valid:
            ev_rec = luck_adjusted_episode_ev(ep, world_secret=None)
            if not ev_rec["replay_match"]:
                raise ValueError(
                    f"replay mismatch in run {label!r} on {ep.get('tier')} seed={ep.get('seed')}"
                )
            scored.append(ev_rec)

    scored.sort(key=lambda r: (r["tier"], r["seed"]))
    return {
        "label": label,
        "path": path_str,
        "scored_episodes": scored,
        "excluded_episodes": excluded,
        "world_secret_tag": secret_tag,
    }


def _summarize_subset(
    sub: list[dict[str, Any]],
    excluded_sub: list[dict[str, Any]],
    bootstrap_n: int,
    rng: random.Random,
) -> dict[str, Any]:
    n = len(sub)
    scores = [r["raw_score"] for r in sub]
    evs = [r["luck_adjusted_ev"] for r in sub]
    mean_sc, sc_lo, sc_hi, sc_half = _bootstrap_mean_ci(scores, bootstrap_n, rng)
    mean_ev, ev_lo, ev_hi, ev_half = _bootstrap_mean_ci(evs, bootstrap_n, rng)

    if n > 0:
        n_correct = sum(1 for r in sub if r["correct"])
        n_accused = sum(1 for r in sub if r["accused"] is not None and r["end_reason"] == "accused")
        n_abstain = n - n_accused
        n_wrong = sum(1 for r in sub if r["accused"] is not None and r["end_reason"] == "accused" and not r["correct"])
        tot_calls = sum(r["total_calls"] for r in sub)
        val_calls = sum(r["valid_calls"] for r in sub)
        valid_call_rate = (val_calls / tot_calls) if tot_calls > 0 else 1.0
        accuracy = n_correct / n
        accuse_rate = n_accused / n
        abstain_rate = n_abstain / n
        wrong_accuse_rate = n_wrong / n
    else:
        accuracy = 0.0
        accuse_rate = 0.0
        abstain_rate = 0.0
        wrong_accuse_rate = 0.0
        valid_call_rate = 0.0

    return {
        "n": n,
        "n_excluded": len(excluded_sub),
        "mean_score": mean_sc,
        "score_ci95": sc_half,
        "score_ci_lo": sc_lo,
        "score_ci_hi": sc_hi,
        "score_ci": [sc_lo, sc_hi],
        "accuracy": accuracy,
        "accuse_rate": accuse_rate,
        "abstain_rate": abstain_rate,
        "wrong_accuse_rate": wrong_accuse_rate,
        "valid_tool_call_rate": valid_call_rate,
        "mean_luck_adjusted_ev": mean_ev,
        "luck_adjusted_ev": mean_ev,
        "luck_adjusted_ci95": ev_half,
        "luck_adjusted_ci_lo": ev_lo,
        "luck_adjusted_ci_hi": ev_hi,
        "luck_adjusted_ci": [ev_lo, ev_hi],
    }


def _paired_tier_summary(
    before_sub: list[dict[str, Any]],
    after_sub: list[dict[str, Any]],
    bootstrap_n: int,
    rng: random.Random,
) -> dict[str, Any]:
    before_map = {(r["tier"], r["seed"]): r for r in before_sub}
    after_map = {(r["tier"], r["seed"]): r for r in after_sub}
    paired_keys = sorted(set(before_map) & set(after_map))
    unpaired_before = sorted(set(before_map) - set(after_map))
    unpaired_after = sorted(set(after_map) - set(before_map))

    n_p = len(paired_keys)
    b_scores = [before_map[k]["raw_score"] for k in paired_keys]
    a_scores = [after_map[k]["raw_score"] for k in paired_keys]
    score_diffs = [a - b for a, b in zip(a_scores, b_scores)]

    b_evs = [before_map[k]["luck_adjusted_ev"] for k in paired_keys]
    a_evs = [after_map[k]["luck_adjusted_ev"] for k in paired_keys]
    ev_diffs = [a - b for a, b in zip(a_evs, b_evs)]

    sc_delta, sc_lo, sc_hi, sc_half = _bootstrap_mean_ci(score_diffs, bootstrap_n, rng)
    ev_delta, ev_lo, ev_hi, ev_half = _bootstrap_mean_ci(ev_diffs, bootstrap_n, rng)

    if n_p > 0:
        b_acc = sum(1 for k in paired_keys if before_map[k]["correct"]) / n_p
        a_acc = sum(1 for k in paired_keys if after_map[k]["correct"]) / n_p
        b_acc_rate = sum(
            1 for k in paired_keys if before_map[k]["accused"] is not None and before_map[k]["end_reason"] == "accused"
        ) / n_p
        a_acc_rate = sum(
            1 for k in paired_keys if after_map[k]["accused"] is not None and after_map[k]["end_reason"] == "accused"
        ) / n_p
        b_wrong = sum(
            1
            for k in paired_keys
            if before_map[k]["accused"] is not None
            and before_map[k]["end_reason"] == "accused"
            and not before_map[k]["correct"]
        ) / n_p
        a_wrong = sum(
            1
            for k in paired_keys
            if after_map[k]["accused"] is not None
            and after_map[k]["end_reason"] == "accused"
            and not after_map[k]["correct"]
        ) / n_p
        b_tot_c = sum(before_map[k]["total_calls"] for k in paired_keys)
        b_val_c = sum(before_map[k]["valid_calls"] for k in paired_keys)
        a_tot_c = sum(after_map[k]["total_calls"] for k in paired_keys)
        a_val_c = sum(after_map[k]["valid_calls"] for k in paired_keys)
        b_vcr = (b_val_c / b_tot_c) if b_tot_c > 0 else 1.0
        a_vcr = (a_val_c / a_tot_c) if a_tot_c > 0 else 1.0
        b_mean_sc = sum(b_scores) / n_p
        a_mean_sc = sum(a_scores) / n_p
        b_mean_ev = sum(b_evs) / n_p
        a_mean_ev = sum(a_evs) / n_p
    else:
        b_acc = a_acc = 0.0
        b_acc_rate = a_acc_rate = 0.0
        b_wrong = a_wrong = 0.0
        b_vcr = a_vcr = 0.0
        b_mean_sc = a_mean_sc = 0.0
        b_mean_ev = a_mean_ev = 0.0

    wins = sum(1 for d in score_diffs if d > 1e-9)
    losses = sum(1 for d in score_diffs if d < -1e-9)
    ties = n_p - wins - losses

    return {
        "n_paired": n_p,
        "n_unpaired_before": len(unpaired_before),
        "n_unpaired_after": len(unpaired_after),
        "paired_seeds": [s for _, s in paired_keys],
        "before_mean_score": b_mean_sc,
        "after_mean_score": a_mean_sc,
        "mean_score_delta": sc_delta,
        "score_delta": sc_delta,
        "score_delta_ci95": sc_half,
        "score_delta_ci_lo": sc_lo,
        "score_delta_ci_hi": sc_hi,
        "score_delta_ci": [sc_lo, sc_hi],
        "before_mean_luck_adjusted_ev": b_mean_ev,
        "after_mean_luck_adjusted_ev": a_mean_ev,
        "mean_luck_adjusted_ev_delta": ev_delta,
        "luck_adjusted_ev_delta": ev_delta,
        "luck_adjusted_ev_delta_ci95": ev_half,
        "luck_adjusted_ev_delta_ci_lo": ev_lo,
        "luck_adjusted_ev_delta_ci_hi": ev_hi,
        "luck_adjusted_ev_delta_ci": [ev_lo, ev_hi],
        "accuracy_delta": a_acc - b_acc,
        "accuse_rate_delta": a_acc_rate - b_acc_rate,
        "abstain_rate_delta": (1.0 - a_acc_rate) - (1.0 - b_acc_rate),
        "wrong_accuse_rate_delta": a_wrong - b_wrong,
        "valid_tool_call_rate_delta": a_vcr - b_vcr,
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }


def compare_runs(
    run_specs: Any,
    world_secret: bytes | bytearray | str | None = None,
    bootstrap_n: int = 5000,
    rng_seed: int = 0,
    train_seeds: Iterable[int] | None = None,
) -> dict[str, Any]:
    norm_specs = _normalize_run_specs(run_specs)
    if not norm_specs:
        raise ValueError("run_specs must contain at least one run")

    loaded = [_load_and_score_run(lbl, src, world_secret) for lbl, src in norm_specs]
    rng = random.Random(rng_seed)

    extra_tiers = sorted({
        r["tier"]
        for item in loaded
        for r in item["scored_episodes"]
        if r["tier"] not in EVAL_TIERS
    })
    tier_order = [*EVAL_TIERS, *extra_tiers, "all"]

    runs_out: dict[str, Any] = {}
    all_eval_seeds: set[int] = set()
    secret_tags_by_run: dict[str, str | None] = {}

    for item in loaded:
        lbl = item["label"]
        eps = item["scored_episodes"]
        excl = item["excluded_episodes"]
        for r in eps:
            all_eval_seeds.add(r["seed"])
        secret_tags_by_run[lbl] = item["world_secret_tag"]

        by_tier: dict[str, Any] = {}
        for t in tier_order:
            sub = eps if t == "all" else [r for r in eps if r["tier"] == t]
            excl_sub = excl if t == "all" else [e for e in excl if e.get("tier") == t]
            by_tier[t] = _summarize_subset(sub, excl_sub, bootstrap_n, rng)

        runs_out[lbl] = {
            "label": lbl,
            "path": item["path"],
            "n_valid": len(eps),
            "n_excluded": len(excl),
            "excluded_episodes": excl,
            "world_secret_tag": item["world_secret_tag"],
            "by_tier": by_tier,
        }

    labels = [item["label"] for item in loaded]
    loaded_by_label = {item["label"]: item for item in loaded}
    baseline_label = "before" if "before" in loaded_by_label else labels[0]

    paired_out: dict[str, dict[str, Any]] = {}
    primary_paired: dict[str, Any] | None = None
    after_candidates = [lbl for lbl in labels if lbl != baseline_label]
    if "after" in after_candidates:
        after_candidates = ["after"] + [lbl for lbl in after_candidates if lbl != "after"]

    base_eps = loaded_by_label[baseline_label]["scored_episodes"]
    for cand_label in after_candidates:
        cand_eps = loaded_by_label[cand_label]["scored_episodes"]
        pair_key = f"{cand_label}_vs_{baseline_label}"
        per_tier_pair: dict[str, Any] = {}
        for t in tier_order:
            b_sub = base_eps if t == "all" else [r for r in base_eps if r["tier"] == t]
            a_sub = cand_eps if t == "all" else [r for r in cand_eps if r["tier"] == t]
            per_tier_pair[t] = _paired_tier_summary(b_sub, a_sub, bootstrap_n, rng)
        paired_out[pair_key] = {
            "before": baseline_label,
            "after": cand_label,
            "by_tier": per_tier_pair,
        }
        if primary_paired is None:
            primary_paired = per_tier_pair

    hygiene = audit_seed_hygiene(
        train_seeds=list(train_seeds) if train_seeds is not None else [],
        eval_seeds=sorted(all_eval_seeds),
        world_secret_tags=secret_tags_by_run,
    )

    result: dict[str, Any] = {
        "tiers": tier_order,
        "bootstrap_n": bootstrap_n,
        "rng_seed": rng_seed,
        "baseline": baseline_label,
        "runs": runs_out,
        "paired": paired_out,
        "paired_delta": primary_paired,
        "after_minus_before": primary_paired,
        "hygiene": hygiene,
    }
    result["markdown"] = format_comparison_markdown(result)
    return result


def format_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines: list[str] = [
        "| Run | Tier | n (excl) | Mean Score +/- 95% CI | Luck-Adj EV +/- 95% CI | Acc | Accuse | Abstain | Wrong | Valid Calls |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    tiers = comparison.get("tiers") or [*EVAL_TIERS, "all"]
    runs = comparison.get("runs") or {}
    for lbl, rdata in runs.items():
        by_tier = rdata.get("by_tier") or {}
        for t in tiers:
            row = by_tier.get(t)
            if not row or (row["n"] == 0 and row["n_excluded"] == 0 and t != "all"):
                continue
            sc_str = f"{row['mean_score']:+.4f} +/- {row['score_ci95']:.4f} [{row['score_ci_lo']:+.4f}, {row['score_ci_hi']:+.4f}]"
            ev_str = (
                f"{row['mean_luck_adjusted_ev']:+.4f} +/- {row['luck_adjusted_ci95']:.4f} "
                f"[{row['luck_adjusted_ci_lo']:+.4f}, {row['luck_adjusted_ci_hi']:+.4f}]"
            )
            lines.append(
                f"| {lbl} | {t} | {row['n']} ({row['n_excluded']}) | {sc_str} | {ev_str} | "
                f"{row['accuracy']:.1%} | {row['accuse_rate']:.1%} | {row['abstain_rate']:.1%} | "
                f"{row['wrong_accuse_rate']:.1%} | {row['valid_tool_call_rate']:.1%} |"
            )

    paired = comparison.get("paired") or {}
    if paired:
        lines.extend([
            "",
            "| Paired (after - before) | Tier | Paired n | Score Delta +/- 95% CI | Luck-Adj EV Delta +/- 95% CI | Acc Delta | Wrong Delta | W/L/T |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ])
        for pair_name, pdata in paired.items():
            label_str = f"{pdata['after']} - {pdata['before']}" if "after" in pdata and "before" in pdata else pair_name
            p_by_tier = pdata.get("by_tier") or {}
            for t in tiers:
                prow = p_by_tier.get(t)
                if not prow or (prow["n_paired"] == 0 and t != "all"):
                    continue
                sd_str = (
                    f"{prow['mean_score_delta']:+.4f} +/- {prow['score_delta_ci95']:.4f} "
                    f"[{prow['score_delta_ci_lo']:+.4f}, {prow['score_delta_ci_hi']:+.4f}]"
                )
                ed_str = (
                    f"{prow['mean_luck_adjusted_ev_delta']:+.4f} +/- {prow['luck_adjusted_ev_delta_ci95']:.4f} "
                    f"[{prow['luck_adjusted_ev_delta_ci_lo']:+.4f}, {prow['luck_adjusted_ev_delta_ci_hi']:+.4f}]"
                )
                wlt = f"{prow['wins']}/{prow['losses']}/{prow['ties']}"
                lines.append(
                    f"| {label_str} | {t} | {prow['n_paired']} | {sd_str} | {ed_str} | "
                    f"{prow['accuracy_delta']:+.1%} | {prow['wrong_accuse_rate_delta']:+.1%} | {wlt} |"
                )

    return "\n".join(lines)


def _load_hf_model_and_tokenizer(
    model_spec: str,
    adapter_path: str | None = None,
) -> tuple[Any, Any, str]:
    torch = importlib.import_module("torch")
    transformers = importlib.import_module("transformers")
    auto_model_cls = transformers.AutoModelForCausalLM
    auto_tok_cls = transformers.AutoTokenizer

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    resolved_spec = DEFAULT_BASE_MODEL if model_spec == "base" else model_spec

    tok_source = resolved_spec
    if adapter_path is not None:
        peft = importlib.import_module("peft")
        base_model = auto_model_cls.from_pretrained(
            resolved_spec,
            dtype=dtype,
            attn_implementation="sdpa",
        )
        model = peft.PeftModel.from_pretrained(base_model, adapter_path).merge_and_unload()
        if os.path.exists(os.path.join(adapter_path, "tokenizer_config.json")):
            tok_source = adapter_path
        base_tag = os.path.basename(os.path.normpath(resolved_spec))
        adap_tag = os.path.basename(os.path.normpath(adapter_path))
        name = f"compact-hf-lora:{base_tag}+{adap_tag}"
    elif os.path.exists(os.path.join(resolved_spec, "adapter_config.json")):
        peft = importlib.import_module("peft")
        with open(os.path.join(resolved_spec, "adapter_config.json"), encoding="utf-8") as fh:
            acfg = json.load(fh)
        base_path = acfg["base_model_name_or_path"]
        base_model = auto_model_cls.from_pretrained(
            base_path,
            dtype=dtype,
            attn_implementation="sdpa",
        )
        model = peft.PeftModel.from_pretrained(base_model, resolved_spec).merge_and_unload()
        if os.path.exists(os.path.join(resolved_spec, "tokenizer_config.json")):
            tok_source = resolved_spec
        else:
            tok_source = base_path
        name = "compact-hf-lora:" + os.path.basename(os.path.normpath(resolved_spec))
    else:
        model = auto_model_cls.from_pretrained(
            resolved_spec,
            dtype=dtype,
            attn_implementation="sdpa",
        )
        name = "compact-hf:" + os.path.basename(os.path.normpath(resolved_spec))

    tok = auto_tok_cls.from_pretrained(tok_source)
    model.to(dev).eval()
    return model, tok, name


def _resolve_eval_seeds(seeds_arg: str, n: int) -> list[int]:
    spec = seeds_arg.strip()
    if spec == "heldout":
        pool = list(HELDOUT_SEEDS)
        return pool[:n] if n > 0 else pool
    if spec == "dev":
        pool = list(DEV_SEEDS)
        return pool[:n] if n > 0 else pool[:200]
    if spec == "val":
        pool = list(range(190_000, 200_000))
        return pool[:n] if n > 0 else pool[:200]
    parsed = parse_seeds(spec)
    return parsed[:n] if n > 0 else parsed


def _run_capped_episode(env: Env, policy: Any, max_calls: int):
    if max_calls <= 0:
        return canary_run_episode(env, policy)
    ep = canary_run_episode(env, policy, max_iters=max_calls)
    if ep.end_reason == "error" and str((ep.meta or {}).get("error", "")).startswith("no episode end"):
        ep.end_reason = "eval_cap"
        ep.meta.pop("error", None)
    return ep


def _git_short_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def run_compact_eval(
    model_spec: str,
    out_root: str | Path,
    adapter_path: str | None = None,
    tiers: Iterable[str] = EVAL_TIERS,
    seeds_spec: str = "heldout",
    n: int = 50,
    run_id: str | None = None,
    world_secret: bytes | bytearray | str | None = None,
    max_ctx: int = 2048,
    max_new_tokens: int = 96,
    tail_turns: int = 4,
    max_calls: int = 120,
    max_minutes: float = 0.0,
    kv_reuse: bool = True,
    workers: int = 1,
    generator: Callable[..., str] | None = None,
    bootstrap_n: int = 5000,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("workers must be 1 under memory guard")

    tier_list = [t.strip() for t in tiers if t.strip()]
    for t in tier_list:
        if t not in RULE_TIERS:
            raise ValueError(f"unknown tier {t!r}")

    seed_list = _resolve_eval_seeds(seeds_spec, n)
    uses_heldout = any(s in HELDOUT_SEEDS or s in JUDGE_SEEDS or s >= 800_000 for s in seed_list)

    if world_secret is None and uses_heldout:
        env_sec = os.environ.get("CANARY_WORLD_SECRET")
        effective_secret: bytes | bytearray | str | None = env_secret if (env_secret := env_sec) else DEFAULT_HELD_OUT_WORLD_SECRET
    elif world_secret == "":
        effective_secret = None
    else:
        effective_secret = world_secret

    secret_tag = active_world_secret_tag(effective_secret)

    compact_mod = None
    model = None
    tok = None
    if generator is not None:
        compact_mod = load_compact_render_module()
        agent_name = f"compact-gen:{model_spec}"
    elif model_spec == "solver":
        agent_name = "solver"
    else:
        compact_mod = load_compact_render_module()
        model, tok, agent_name = _load_hf_model_and_tokenizer(model_spec, adapter_path=adapter_path)

    resolved_run_id = run_id or (
        f"{agent_name.replace(':', '-').replace('/', '_')}-"
        f"{'+'.join(tier_list)}-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    run_dir = Path(out_root) / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta_payload = {
        "run_id": resolved_run_id,
        "agent": agent_name,
        "model": model_spec,
        "adapter": adapter_path,
        "provider": "compact_hf" if model_spec != "solver" else "solver",
        "git_sha": _git_short_sha(),
        "tiers": tier_list,
        "seeds_spec": seeds_spec,
        "seeds": seed_list,
        "n": len(seed_list),
        "max_ctx": max_ctx,
        "max_new_tokens": max_new_tokens,
        "tail_turns": tail_turns,
        "max_calls": max_calls,
        "workers": 1,
        "world_secret_tag": secret_tag if secret_tag is not None else "unset",
    }
    (run_dir / "meta.json").write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")

    episodes_path = run_dir / "episodes.jsonl"
    t0 = time.time()
    with _world_secret_scope(effective_secret):
        with open(episodes_path, "w", encoding="utf-8") as fh:
            for seed in seed_list:
                for tier in tier_list:
                    if max_minutes > 0 and (time.time() - t0) > 60.0 * max_minutes:
                        break
                    env = Env(tier=tier, seed=seed)
                    if model_spec == "solver" and generator is None:
                        pol: Any = SolverPolicy()
                    elif generator is not None:
                        assert compact_mod is not None
                        pol = compact_mod.CompactHFPolicy(
                            name=agent_name,
                            max_ctx=max_ctx,
                            max_new=max_new_tokens,
                            tail_turns=tail_turns,
                            kv_reuse=False,
                            generator=generator,
                        )
                    else:
                        assert compact_mod is not None
                        pol = compact_mod.CompactHFPolicy(
                            model=model,
                            tokenizer=tok,
                            name=agent_name,
                            max_ctx=max_ctx,
                            max_new=max_new_tokens,
                            tail_turns=tail_turns,
                            kv_reuse=kv_reuse,
                        )
                    t_ep = time.time()
                    ep = _run_capped_episode(env, pol, max_calls)
                    ep.meta = dict(ep.meta or {})
                    ep.meta["invalid_calls"] = int(getattr(pol, "invalid", 0) or 0)
                    ep.meta["eval_seconds"] = round(time.time() - t_ep, 2)
                    ep.meta["world_secret_tag"] = secret_tag if secret_tag is not None else "unset"
                    if getattr(pol, "encoded", None) is not None:
                        ep.meta["prefill_tokens"] = int(pol.encoded)
                        ep.meta["reused_tokens"] = int(pol.reused)
                    rec = dataclasses.asdict(ep)
                    fh.write(json.dumps(rec, default=str) + "\n")
                    fh.flush()

    comp = compare_runs(
        {resolved_run_id: episodes_path},
        world_secret=effective_secret,
        bootstrap_n=bootstrap_n,
    )
    run_summary = comp["runs"][resolved_run_id]
    summary_payload = {
        "run_id": resolved_run_id,
        "agent": agent_name,
        "seconds": round(time.time() - t0, 2),
        "world_secret_tag": secret_tag if secret_tag is not None else "unset",
        "n_valid": run_summary["n_valid"],
        "n_excluded": run_summary["n_excluded"],
        "by_tier": run_summary["by_tier"],
        "hygiene": comp["hygiene"],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")
    return summary_payload


def _load_seeds_from_jsonl(paths: list[str]) -> list[int]:
    seeds: list[int] = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if "seed" in row:
                    seeds.append(int(row["seed"]))
    return seeds


def main(argv: list[str] | None = None) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="python -m train.eval_compact_hf")
    ap.add_argument("--compare", nargs="+", default=None, help="Run specs: label=path or path [...]")
    ap.add_argument("--verify", default=None, help="Verify a single episodes.jsonl or run dir")
    ap.add_argument("--eval-model", default=None, help="HF model path, 'base', or 'solver'")
    ap.add_argument("--adapter", default=None, help="Optional PEFT LoRA adapter path")
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--seeds", default="heldout")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--out", default="/tmp/opencode/compact_runs")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--world-secret", default=None)
    ap.add_argument("--max-ctx", type=int, default=2048)
    ap.add_argument("--max-new-tokens", type=int, default=96)
    ap.add_argument("--tail-turns", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=120)
    ap.add_argument("--max-minutes", type=float, default=0.0)
    ap.add_argument("--no-kv-reuse", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--bootstrap-n", type=int, default=5000)
    ap.add_argument("--rng-seed", type=int, default=0)
    ap.add_argument("--train-jsonl", nargs="*", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise ValueError("--workers must be 1")

    cli_secret: bytes | bytearray | str | None
    if args.world_secret is None:
        cli_secret = os.environ.get("CANARY_WORLD_SECRET") or DEFAULT_HELD_OUT_WORLD_SECRET
    elif args.world_secret == "":
        cli_secret = None
    else:
        cli_secret = args.world_secret

    if args.verify is not None:
        res = verify_episode_file(args.verify, world_secret=cli_secret)
        if args.out_json:
            Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out_json).write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in res.items() if k != "valid_episodes"}))
        return res

    if args.eval_model is not None:
        summary = run_compact_eval(
            model_spec=args.eval_model,
            out_root=args.out,
            adapter_path=args.adapter,
            tiers=args.tiers.split(","),
            seeds_spec=args.seeds,
            n=args.n,
            run_id=args.run_id,
            world_secret=args.world_secret,
            max_ctx=args.max_ctx,
            max_new_tokens=args.max_new_tokens,
            tail_turns=args.tail_turns,
            max_calls=args.max_calls,
            max_minutes=args.max_minutes,
            kv_reuse=not args.no_kv_reuse,
            workers=args.workers,
            bootstrap_n=args.bootstrap_n,
        )
        if args.out_json:
            Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary))
        return summary

    if args.compare:
        train_seeds = _load_seeds_from_jsonl(args.train_jsonl) if args.train_jsonl else None
        comp = compare_runs(
            args.compare,
            world_secret=cli_secret,
            bootstrap_n=args.bootstrap_n,
            rng_seed=args.rng_seed,
            train_seeds=train_seeds,
        )
        md = comp["markdown"]
        if args.out_md:
            Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out_md).write_text(md + "\n", encoding="utf-8")
        if args.out_json:
            Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out_json).write_text(json.dumps(comp, indent=2), encoding="utf-8")
        print(md)
        return comp

    ap.error("specify one of --compare, --eval-model, or --verify")
    return {}


if __name__ == "__main__":
    main()
