"""Paired and luck-adjusted evaluator for Canary v1.4 primary, G1, and FR8 replication cohorts (pure CPU, zero API calls).

    python scripts/verify_frontier_replication.py --write
    python scripts/verify_frontier_replication.py --check
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary.analysis.gap import load_runs, mean_ci
from canary.baselines import GrokTactics
from canary.env import Env
from canary.eval import run_episode
from paired_v13 import _P_CACHE, boot_ratio, p_acc, post_expected
from verify_replay import replay_episode

MAX_JSON_BYTES = 45_000

DEFAULT_JSON = ROOT / "results" / "frontier_replication" / "v1.4" / "replication_summary.json"
DEFAULT_MD = ROOT / "docs" / "reports" / "frontier_replication_v14.md"

ALT_LABEL = (
    "OpenCode, alternative (NOT the headline): episodes whose first attempt ended on an empty model reply "
    "counted as 0 instead of retried"
)

LEGACY_STOP_EARLY_LABEL = (
    "day-1 guess (recorded under the pre-2bb6729 name stop_early; "
    "today's stop_early stops without accusing and scores 0, see results/judge_table.md)"
)

NON_SOLVER_BASELINES_30_59 = (
    "grok_tactics",
    "heuristic",
    "do_nothing",
    "stop_early",
    "random",
    "logs_only",
    "guess_day1",
    "restrict_all",
)

COMMITTED_BASELINES_0_19 = (
    "heuristic",
    "do_nothing",
    "stop_early",
    "random",
    "restrict_all",
)


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    if not gap_md.exists():
        return False
    return "gemini-3.5-flash" in gap_md.read_text(encoding="utf-8")


def clean_json(obj: Any, float_ndigits: int | None = None) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, float_ndigits) if float_ndigits is not None else obj
    if isinstance(obj, dict):
        return {str(k): clean_json(v, float_ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v, float_ndigits) for v in obj]
    return obj


def _fmt_json_compact(obj: Any, depth: int = 0, max_expand_depth: int = 1) -> str:
    if depth >= max_expand_depth or not isinstance(obj, (dict, list)) or not obj:
        return json.dumps(obj, sort_keys=True, allow_nan=False, separators=(",", ":"))
    pad = " " * depth
    inner_pad = " " * (depth + 1)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return json.dumps(obj, allow_nan=False, separators=(",", ":"))
        items = [inner_pad + _fmt_json_compact(v, depth + 1, max_expand_depth) for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    items = [
        f"{inner_pad}{json.dumps(k)}: {_fmt_json_compact(obj[k], depth + 1, max_expand_depth)}"
        for k in sorted(obj.keys())
    ]
    return "{\n" + ",\n".join(items) + "\n" + pad + "}"


def serialize_summary_json(summary: dict[str, Any]) -> str:
    blob = _fmt_json_compact(summary, depth=0, max_expand_depth=1) + "\n"
    size = len(blob.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(f"serialized replication_summary.json is {size} bytes, exceeding {MAX_JSON_BYTES}")
    return blob


def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def empty_reply_seeds(run_dir: Path, tier: str) -> set[int]:
    meta_path = run_dir / tier / "meta.json"
    if not meta_path.exists():
        return set()
    out: set[int] = set()
    for entry in json.loads(meta_path.read_text(encoding="utf-8")).get("infra_invalid_attempts_excluded") or []:
        name, _, why = entry.partition(":")
        if "empty_model_response" in why:
            out.add(int(name.split("-")[2]))
    return out


def _count_pre_1bc3e281_error_steps(episodes: list[dict[str, Any]]) -> int:
    count = 0
    for ep in episodes:
        for st in ep.get("steps") or []:
            res = st.get("result")
            if isinstance(res, str) and '"ok": false' in res and '"detail"' not in res:
                count += 1
            elif isinstance(res, dict) and res.get("ok") is False and "detail" not in (res.get("data") or {}):
                count += 1
    return count


@contextlib.contextmanager
def _allow_dev_env():
    had_key = "CANARY_ALLOW_DEV" in os.environ
    prev_val = os.environ.get("CANARY_ALLOW_DEV")
    if not had_key:
        os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        yield
    finally:
        if not had_key:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        elif prev_val is not None:
            os.environ["CANARY_ALLOW_DEV"] = prev_val


def verify_episode_list(episodes: list[dict[str, Any]], cohort_name: str) -> dict[str, Any]:
    with _allow_dev_env():
        seen: set[tuple[str, str, int]] = set()
        duplicates: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        for e in episodes:
            key = (str(e["agent"]), str(e["tier"]), int(e["seed"]))
            if key in seen:
                duplicates.append({"cohort": cohort_name, "agent": key[0], "tier": key[1], "seed": key[2]})
            seen.add(key)
            rep = replay_episode(e)
            ok = (
                abs(float(rep["score"]) - float(e["score"])) < 1e-9
                and rep["accused"] == e.get("accused")
                and bool(rep["correct"]) == bool(e["correct"])
                and int(rep["final_day"]) == int(e.get("final_day") or 0)
            )
            if not ok:
                mismatches.append(
                    {
                        "cohort": cohort_name,
                        "agent": e["agent"],
                        "tier": e["tier"],
                        "seed": e["seed"],
                        "recorded_score": e["score"],
                        "replay_score": rep["score"],
                        "recorded_accused": e.get("accused"),
                        "replay_accused": rep["accused"],
                        "recorded_correct": e["correct"],
                        "replay_correct": rep["correct"],
                        "recorded_final_day": e.get("final_day"),
                        "replay_final_day": rep["final_day"],
                    }
                )
        if duplicates:
            raise ValueError(f"duplicate episodes in {cohort_name}: {duplicates}")
        if mismatches:
            raise ValueError(f"replay mismatches in {cohort_name}: {mismatches}")
        return {
            "cohort": cohort_name,
            "total": len(episodes),
            "verified": len(episodes) - len(mismatches),
            "mismatches": len(mismatches),
            "duplicates": len(duplicates),
            "pre_1bc3e281_error_steps": _count_pre_1bc3e281_error_steps(episodes),
        }


def verify_solver_30_59_parity(comm_solver_dir: Path, rep_solver_dir: Path) -> dict[str, Any]:
    comm_eps = [
        e for e in load_runs(comm_solver_dir)
        if e.get("agent") == "solver" and e.get("tier") == "hard"
    ]
    rep_eps = [
        e for e in load_runs(rep_solver_dir)
        if e.get("agent") == "solver" and e.get("tier") == "hard"
    ]
    expected_seeds = list(range(30, 60))
    comm_seeds = [int(e["seed"]) for e in comm_eps]
    rep_seeds = [int(e["seed"]) for e in rep_eps]
    if len(comm_seeds) != len(set(comm_seeds)):
        raise ValueError(f"duplicate solver seeds in {comm_solver_dir}: {comm_seeds}")
    if len(rep_seeds) != len(set(rep_seeds)):
        raise ValueError(f"duplicate solver seeds in {rep_solver_dir}: {rep_seeds}")
    if sorted(comm_seeds) != expected_seeds:
        raise ValueError(f"committed solver 30-59 seeds mismatch: {sorted(comm_seeds)}")
    if sorted(rep_seeds) != expected_seeds:
        raise ValueError(f"replication solver 30-59 seeds mismatch: {sorted(rep_seeds)}")

    by_comm = {int(e["seed"]): e for e in comm_eps}
    by_rep = {int(e["seed"]): e for e in rep_eps}
    mismatches: list[dict[str, Any]] = []
    for seed in expected_seeds:
        ce = by_comm[seed]
        re_ = by_rep[seed]
        same = (
            abs(float(ce["score"]) - float(re_["score"])) < 1e-12
            and ce.get("accused") == re_.get("accused")
            and bool(ce["correct"]) == bool(re_["correct"])
            and int(ce["final_day"]) == int(re_["final_day"])
        )
        if not same:
            mismatches.append(
                {
                    "seed": seed,
                    "committed": {
                        "score": float(ce["score"]),
                        "accused": ce.get("accused"),
                        "correct": bool(ce["correct"]),
                        "final_day": int(ce["final_day"]),
                    },
                    "replication": {
                        "score": float(re_["score"]),
                        "accused": re_.get("accused"),
                        "correct": bool(re_["correct"]),
                        "final_day": int(re_["final_day"]),
                    },
                }
            )
    if mismatches:
        raise ValueError(f"committed vs FR8 solver 30-59 parity mismatch: {mismatches}")
    return {
        "committed_dir": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59",
        "replication_dir": "results/frontier_replication/v1.4/reference/solver-hard-seeds30to59",
        "seeds": expected_seeds,
        "n": len(expected_seeds),
        "matched": len(expected_seeds),
        "mismatches": 0,
        "fields_verified": ["score", "accused", "correct", "final_day"],
        "exact_parity": True,
    }


def dedup_extension_union(
    g1_eps: list[dict[str, Any]],
    fr8_eps: list[dict[str, Any]],
    solver_map: dict[tuple[str, int], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, str], dict[str, Any]]:
    g1_seeds = [int(e["seed"]) for e in g1_eps]
    fr8_seeds = [int(e["seed"]) for e in fr8_eps]
    if len(g1_seeds) != len(set(g1_seeds)):
        raise ValueError(f"duplicate seeds inside G1 extension: {g1_seeds}")
    if len(fr8_seeds) != len(set(fr8_seeds)):
        raise ValueError(f"duplicate seeds inside FR8 replication: {fr8_seeds}")

    seen: set[tuple[str, int]] = set()
    union_eps: list[dict[str, Any]] = []
    source_by_seed: dict[int, str] = {}
    shared_seeds: list[int] = []
    dropped = 0
    for src_name, cohort_eps in (("committed_g1", g1_eps), ("fr8_replication", fr8_eps)):
        for ep in sorted(cohort_eps, key=lambda e: int(e["seed"])):
            key = (str(ep["tier"]), int(ep["seed"]))
            if key not in seen:
                seen.add(key)
                union_eps.append(ep)
                source_by_seed[key[1]] = src_name
            else:
                dropped += 1
                shared_seeds.append(key[1])
    union_eps.sort(key=lambda e: int(e["seed"]))

    seen_alt: set[tuple[str, int]] = set()
    alt_union_eps: list[dict[str, Any]] = []
    for cohort_eps in (fr8_eps, g1_eps):
        for ep in sorted(cohort_eps, key=lambda e: int(e["seed"])):
            key = (str(ep["tier"]), int(ep["seed"]))
            if key not in seen_alt:
                seen_alt.add(key)
                alt_union_eps.append(ep)
    alt_union_eps.sort(key=lambda e: int(e["seed"]))

    g1_by_seed = {int(e["seed"]): e for e in g1_eps}
    fr8_by_seed = {int(e["seed"]): e for e in fr8_eps}
    shared_comparisons: list[dict[str, Any]] = []
    for seed in sorted(shared_seeds):
        ge = g1_by_seed[seed]
        fe = fr8_by_seed[seed]
        se = solver_map[("hard", seed)]
        shared_comparisons.append(
            clean_json(
                {
                    "seed": seed,
                    "selected_source": "committed_g1",
                    "committed_g1": {
                        "source": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                        "score": float(ge["score"]),
                        "correct": bool(ge["correct"]),
                        "accused": ge.get("accused"),
                        "final_day": int(ge["final_day"]),
                        "p_accused": p_acc(ge),
                        "luck_adjusted": post_expected(ge),
                    },
                    "fr8_replication": {
                        "source": f"results/frontier_replication/v1.4/opencode-gemini-4-carbon/hard-s{seed}",
                        "score": float(fe["score"]),
                        "correct": bool(fe["correct"]),
                        "accused": fe.get("accused"),
                        "final_day": int(fe["final_day"]),
                        "p_accused": p_acc(fe),
                        "luck_adjusted": post_expected(fe),
                    },
                    "solver": {
                        "source": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59",
                        "score": float(se["score"]),
                        "correct": bool(se["correct"]),
                        "accused": se.get("accused"),
                        "final_day": int(se["final_day"]),
                        "p_accused": p_acc(se),
                        "luck_adjusted": post_expected(se),
                    },
                },
                float_ndigits=8,
            )
        )

    reconcile_meta = {
        "dedup_rule": "committed_g1_precedes_fr8_replication_per_eb9dee54",
        "g1_seeds": sorted(g1_seeds),
        "fr8_seeds": sorted(fr8_seeds),
        "g1_only_seeds": sorted(set(g1_seeds) - set(fr8_seeds)),
        "fr8_only_seeds": sorted(set(fr8_seeds) - set(g1_seeds)),
        "shared_seeds": sorted(shared_seeds),
        "dropped_duplicate_episodes": dropped,
        "shared_seed_comparisons": shared_comparisons,
    }
    return union_eps, alt_union_eps, source_by_seed, reconcile_meta


def pool_disjoint_episodes(
    primary_eps: list[dict[str, Any]],
    ext_eps: list[dict[str, Any]],
    pool_name: str,
) -> list[dict[str, Any]]:
    prim_seeds = [int(e["seed"]) for e in primary_eps]
    ext_seeds = [int(e["seed"]) for e in ext_eps]
    if len(prim_seeds) != len(set(prim_seeds)):
        raise ValueError(f"duplicate seeds inside primary set for {pool_name}: {prim_seeds}")
    if len(ext_seeds) != len(set(ext_seeds)):
        raise ValueError(f"duplicate seeds inside extension set for {pool_name}: {ext_seeds}")
    overlap = sorted(set(prim_seeds) & set(ext_seeds))
    if overlap:
        raise ValueError(f"overlapping seeds in {pool_name}: {overlap}")
    combined = sorted(primary_eps + ext_eps, key=lambda e: int(e["seed"]))
    combined_seeds = [int(e["seed"]) for e in combined]
    if len(combined_seeds) != len(set(combined_seeds)):
        raise ValueError(f"duplicate seeds after pooling {pool_name}: {combined_seeds}")
    return combined


def build_paired_row(
    label: str,
    group: str,
    agent: str,
    tier: str,
    episodes: list[dict[str, Any]],
    solver_map: dict[tuple[str, int], dict[str, Any]],
    float_ndigits: int | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    es = sorted(episodes, key=lambda e: int(e["seed"]))
    if not es:
        raise ValueError(f"empty episode list for {label} ({tier})")
    seeds = [int(e["seed"]) for e in es]
    if len(seeds) != len(set(seeds)):
        raise ValueError(f"duplicate seeds in paired row {label} ({tier}): {seeds}")
    paired = [e for e in es if (tier, int(e["seed"])) in solver_map]
    if len(paired) != len(es):
        missing = [int(e["seed"]) for e in es if (tier, int(e["seed"])) not in solver_map]
        raise ValueError(f"missing paired solver seeds for {label} ({tier}): {missing}")
    f = [float(e["score"]) for e in paired]
    s = [float(solver_map[(tier, int(e["seed"]))]["score"]) for e in paired]
    m, h = mean_ci([float(e["score"]) for e in es])
    ms = sum(s) / len(s) if s else float("nan")
    dm, dh = mean_ci([x - y for x, y in zip(f, s)]) if f else (float("nan"), float("nan"))
    ps = [float(x) for x in (p_acc(e) for e in es if e.get("accused")) if x is not None]
    pe = [post_expected(e) for e in paired]
    pe_s = [post_expected(solver_map[(tier, int(e["seed"]))]) for e in paired]
    pe_ok = bool(pe) and None not in pe + pe_s
    pe_f = [float(x) for x in pe] if pe_ok else []
    pe_sf = [float(x) for x in pe_s] if pe_ok else []
    pe_ratio = (sum(pe_f) / sum(pe_sf)) if pe_ok and sum(pe_sf) > 0 else float("nan")
    pe_lo, pe_hi = (
        boot_ratio(pe_f, pe_sf)
        if pe_ok and len(pe_f) > 1 and agent != "solver"
        else (float("nan"), float("nan"))
    )
    lo, hi = boot_ratio(f, s) if len(f) > 1 and agent != "solver" else (float("nan"), float("nan"))
    accused_count = sum(1 for e in es if e.get("accused"))
    accuse_day = (
        sum(float(e["final_day"]) for e in es if e.get("accused")) / max(1, accused_count)
        if accused_count
        else 0.0
    )
    row: dict[str, Any] = {
        "label": label,
        "agent": agent,
        "tier": tier,
        "n": len(es),
        "mean": m,
        "ci": h,
        "accuracy": sum(bool(e["correct"]) for e in es) / len(es),
        "accused_rate": accused_count / len(es),
        "p_accused": (sum(ps) / len(ps)) if ps else float("nan"),
        "accuse_day": accuse_day,
        "solver_same_seeds": ms,
        "ratio": (sum(f) / len(f) / ms) if f and ms > 0 else float("nan"),
        "ratio_lo": lo,
        "ratio_hi": hi,
        "diff": dm,
        "diff_ci": dh,
        "post_expected": (sum(pe_f) / len(pe_f)) if pe_ok else float("nan"),
        "post_expected_ratio": pe_ratio,
        "post_expected_lo": pe_lo,
        "post_expected_hi": pe_hi,
        "solver_post_expected": (sum(pe_sf) / len(pe_sf)) if pe_ok else float("nan"),
    }
    if not compact:
        row["group"] = group
        row["seeds"] = seeds
        row["n_p"] = len(ps)
    return clean_json(row, float_ndigits=float_ndigits)


def head_to_head_diff(
    label: str,
    tier: str,
    eps_a: list[dict[str, Any]],
    eps_b: list[dict[str, Any]],
    float_ndigits: int | None = 10,
) -> dict[str, Any]:
    by_a = {int(e["seed"]): e for e in eps_a}
    by_b = {int(e["seed"]): e for e in eps_b}
    shared = sorted(set(by_a) & set(by_b))
    raw_diffs = [float(by_a[s]["score"]) - float(by_b[s]["score"]) for s in shared]
    la_diffs = [float(post_expected(by_a[s])) - float(post_expected(by_b[s])) for s in shared]
    raw_m, raw_ci = mean_ci(raw_diffs)
    la_m, la_ci = mean_ci(la_diffs)
    return clean_json(
        {
            "label": label,
            "tier": tier,
            "n": len(shared),
            "seeds": shared,
            "agent_a": eps_a[0]["agent"],
            "agent_b": eps_b[0]["agent"],
            "mean_a": sum(float(by_a[s]["score"]) for s in shared) / len(shared),
            "mean_b": sum(float(by_b[s]["score"]) for s in shared) / len(shared),
            "raw_diff": raw_m,
            "raw_diff_ci": raw_ci,
            "luck_adjusted_a": sum(float(post_expected(by_a[s])) for s in shared) / len(shared),
            "luck_adjusted_b": sum(float(post_expected(by_b[s])) for s in shared) / len(shared),
            "luck_adjusted_diff": la_m,
            "luck_adjusted_diff_ci": la_ci,
        },
        float_ndigits=float_ndigits,
    )


def _build_per_seed_detail(
    carbon_eps: list[dict[str, Any]],
    solver_30_59: dict[tuple[str, int], dict[str, Any]],
    gt_30_59_by_seed: dict[int, dict[str, Any]],
    source_by_seed: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in sorted(carbon_eps, key=lambda ep: int(ep["seed"])):
        s_seed = int(e["seed"])
        se = solver_30_59[("hard", s_seed)]
        ge = gt_30_59_by_seed[s_seed]
        row: dict[str, Any] = {
            "seed": s_seed,
            "carbon_score": float(e["score"]),
            "carbon_correct": bool(e["correct"]),
            "carbon_accused": e.get("accused"),
            "carbon_day": int(e["final_day"]),
            "carbon_p_accused": p_acc(e),
            "carbon_luck_adjusted": post_expected(e),
            "solver_score": float(se["score"]),
            "solver_correct": bool(se["correct"]),
            "solver_accused": se.get("accused"),
            "solver_day": int(se["final_day"]),
            "solver_p_accused": p_acc(se),
            "solver_luck_adjusted": post_expected(se),
            "grok_tactics_score": float(ge["score"]),
            "grok_tactics_luck_adjusted": post_expected(ge),
        }
        if source_by_seed is not None:
            row["source"] = source_by_seed[s_seed]
        out.append(clean_json(row, float_ndigits=4))
    return out


def simulate_grok_tactics(tier: str, seeds: list[int]) -> list[dict[str, Any]]:
    with _allow_dev_env():
        out: list[dict[str, Any]] = []
        for seed in seeds:
            res = asdict(run_episode(Env(tier, seed), GrokTactics(seed=seed)))
            out.append(res)
        return out


def compute_summary(root: Path = ROOT, verify_replays: bool = True) -> dict[str, Any]:
    _P_CACHE.clear()
    try:
        with _allow_dev_env():
            return _compute_summary_impl(root=root, verify_replays=verify_replays)
    finally:
        _P_CACHE.clear()


def _compute_summary_impl(root: Path = ROOT, verify_replays: bool = True) -> dict[str, Any]:
    comm_v14 = root / "data" / "runs" / "committed" / "v1.4"
    rep_v14 = root / "results" / "frontier_replication" / "v1.4"

    comm_eps = load_runs(comm_v14)
    rep_eps = load_runs(rep_v14)
    g1_ext_dir = comm_v14 / "opencode-gemini-4-carbon-ext" / "hard"
    g1_dir_eps = load_runs(g1_ext_dir) if g1_ext_dir.exists() else []
    keep_alive: list[Any] = [comm_eps, rep_eps, g1_dir_eps]

    if verify_replays:
        comm_audit = verify_episode_list(comm_eps, "data/runs/committed/v1.4")
        rep_audit = verify_episode_list(rep_eps, "results/frontier_replication/v1.4")
    else:
        comm_audit = {
            "cohort": "data/runs/committed/v1.4",
            "total": len(comm_eps),
            "verified": 0,
            "mismatches": 0,
            "duplicates": 0,
            "pre_1bc3e281_error_steps": _count_pre_1bc3e281_error_steps(comm_eps),
        }
        rep_audit = {
            "cohort": "results/frontier_replication/v1.4",
            "total": len(rep_eps),
            "verified": 0,
            "mismatches": 0,
            "duplicates": 0,
            "pre_1bc3e281_error_steps": _count_pre_1bc3e281_error_steps(rep_eps),
        }

    solver_30_59_parity = verify_solver_30_59_parity(
        comm_v14 / "reference" / "solver-hard-seeds30to59",
        rep_v14 / "reference" / "solver-hard-seeds30to59",
    )

    seeds_0_29 = set(range(30))
    seeds_30_59 = set(range(30, 60))
    solver_0_29 = {
        (str(e["tier"]), int(e["seed"])): e
        for e in comm_eps
        if e["agent"] == "solver" and int(e["seed"]) in seeds_0_29
    }
    solver_30_59 = {
        (str(e["tier"]), int(e["seed"])): e
        for e in comm_eps
        if e["agent"] == "solver" and int(e["seed"]) in seeds_30_59
    }
    solver_pooled = {**solver_0_29, **solver_30_59}

    carbon_oc_dir = comm_v14 / "opencode-gemini-4-carbon"
    carbon_oc_med_0_29 = [
        e for e in comm_eps
        if e["agent"] == "opencode:google/gemini-4-carbon" and e["tier"] == "medium" and int(e["seed"]) in seeds_0_29
    ]
    carbon_oc_hard_0_29 = [
        e for e in comm_eps
        if e["agent"] == "opencode:google/gemini-4-carbon" and e["tier"] == "hard" and int(e["seed"]) in seeds_0_29
    ]
    carbon_g1_ext_hard = sorted(
        (
            e for e in comm_eps
            if e["agent"] == "opencode:google/gemini-4-carbon"
            and e["tier"] == "hard"
            and int(e["seed"]) in seeds_30_59
        ),
        key=lambda e: int(e["seed"]),
    )
    g1_dir_seeds = sorted(int(e["seed"]) for e in g1_dir_eps if e.get("agent") == "opencode:google/gemini-4-carbon" and e.get("tier") == "hard")
    g1_hard_seeds = [int(e["seed"]) for e in carbon_g1_ext_hard]
    if g1_dir_seeds != g1_hard_seeds:
        raise ValueError(f"G1 extension dir seeds {g1_dir_seeds} differ from committed 30-59 carbon seeds {g1_hard_seeds}")
    g1_hard_seed_set = set(g1_hard_seeds)

    carbon_ip_med_0_29 = [
        e for e in comm_eps
        if e["agent"] == "gemini:gemini-4-carbon" and e["tier"] == "medium" and int(e["seed"]) in seeds_0_29
    ]
    carbon_ip_hard_0_29 = [
        e for e in comm_eps
        if e["agent"] == "gemini:gemini-4-carbon" and e["tier"] == "hard" and int(e["seed"]) in seeds_0_29
    ]
    flash_oc_hard_0_29 = [
        e for e in comm_eps
        if e["agent"] == "opencode:google/gemini-3.5-flash" and e["tier"] == "hard" and int(e["seed"]) in seeds_0_29
    ]
    solver_med_0_29 = [
        e for e in comm_eps
        if e["agent"] == "solver" and e["tier"] == "medium" and int(e["seed"]) in seeds_0_29
    ]
    solver_hard_0_29 = [
        e for e in comm_eps
        if e["agent"] == "solver" and e["tier"] == "hard" and int(e["seed"]) in seeds_0_29
    ]

    def alt_episodes(es: list[dict[str, Any]], tier: str) -> list[dict[str, Any]]:
        zero = empty_reply_seeds(carbon_oc_dir, tier)
        if not zero:
            return []
        out_es = [
            dict(e, score=0.0, correct=False, accused=None) if int(e["seed"]) in zero else e
            for e in es
        ]
        have = {int(e["seed"]) for e in out_es}
        for z in sorted(zero - have):
            if z in seeds_0_29:
                out_es.append(
                    {
                        "tier": tier,
                        "seed": z,
                        "agent": "opencode:google/gemini-4-carbon",
                        "score": 0.0,
                        "correct": False,
                        "accused": None,
                        "final_day": 0,
                        "steps": [],
                        "meta": {},
                    }
                )
        sorted_out = sorted(out_es, key=lambda e: int(e["seed"]))
        keep_alive.append(sorted_out)
        return sorted_out

    primary_rows: list[dict[str, Any]] = []
    primary_rows.append(
        build_paired_row(
            "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "medium",
            carbon_oc_med_0_29,
            solver_0_29,
            float_ndigits=None,
        )
    )
    alt_med = alt_episodes(carbon_oc_med_0_29, "medium")
    if alt_med:
        primary_rows.append(
            build_paired_row(
                ALT_LABEL,
                "v1.4/opencode-gemini-4-carbon",
                "opencode:google/gemini-4-carbon",
                "medium",
                alt_med,
                solver_0_29,
                float_ndigits=None,
            )
        )
    primary_rows.append(
        build_paired_row(
            "in-process gemini-4-carbon (full history, thought-signature replay)",
            "v1.4/inproc-gemini-4-carbon",
            "gemini:gemini-4-carbon",
            "medium",
            carbon_ip_med_0_29,
            solver_0_29,
            float_ndigits=None,
        )
    )
    primary_rows.append(
        build_paired_row(
            "reference solver",
            "v1.4/reference",
            "solver",
            "medium",
            solver_med_0_29,
            solver_0_29,
            float_ndigits=None,
        )
    )
    include_flash_hard = gap_ships_flash_hard(root)

    for base in COMMITTED_BASELINES_0_19:
        base_med = [e for e in comm_eps if e["agent"] == base and e["tier"] == "medium" and int(e["seed"]) in seeds_0_29]
        if base_med:
            base_label = LEGACY_STOP_EARLY_LABEL if base == "stop_early" else base
            primary_rows.append(
                build_paired_row(base_label, "v1.4/reference", base, "medium", base_med, solver_0_29, float_ndigits=None)
            )

    primary_rows.append(
        build_paired_row(
            "OpenCode + gemini-4-carbon over MCP (judges' shape)",
            "v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "hard",
            carbon_oc_hard_0_29,
            solver_0_29,
            float_ndigits=None,
        )
    )
    alt_hard = alt_episodes(carbon_oc_hard_0_29, "hard")
    if alt_hard:
        primary_rows.append(
            build_paired_row(
                ALT_LABEL,
                "v1.4/opencode-gemini-4-carbon",
                "opencode:google/gemini-4-carbon",
                "hard",
                alt_hard,
                solver_0_29,
                float_ndigits=None,
            )
        )
    primary_rows.append(
        build_paired_row(
            "in-process gemini-4-carbon (full history, thought-signature replay)",
            "v1.4/inproc-gemini-4-carbon",
            "gemini:gemini-4-carbon",
            "hard",
            carbon_ip_hard_0_29,
            solver_0_29,
            float_ndigits=None,
        )
    )
    if include_flash_hard:
        primary_rows.append(
            build_paired_row(
                "OpenCode + gemini-3.5-flash over MCP (second Gemini family; the API reports modelVersion gemini-3.6-flash for this id)",
                "v1.4/opencode-gemini-3.5-flash",
                "opencode:google/gemini-3.5-flash",
                "hard",
                flash_oc_hard_0_29,
                solver_0_29,
                float_ndigits=None,
            )
        )
    primary_rows.append(
        build_paired_row(
            "reference solver",
            "v1.4/reference",
            "solver",
            "hard",
            solver_hard_0_29,
            solver_0_29,
            float_ndigits=None,
        )
    )
    for base in COMMITTED_BASELINES_0_19:
        base_hard = [e for e in comm_eps if e["agent"] == base and e["tier"] == "hard" and int(e["seed"]) in seeds_0_29]
        if base_hard:
            base_label = LEGACY_STOP_EARLY_LABEL if base == "stop_early" else base
            primary_rows.append(
                build_paired_row(base_label, "v1.4/reference", base, "hard", base_hard, solver_0_29, float_ndigits=None)
            )

    carbon_rep_hard = sorted(
        (e for e in rep_eps if e["agent"] == "opencode:google/gemini-4-carbon" and e["tier"] == "hard"),
        key=lambda e: int(e["seed"]),
    )
    rep_hard_seeds = [int(e["seed"]) for e in carbon_rep_hard]
    rep_hard_seed_set = set(rep_hard_seeds)

    prim_hard_seed_set = {int(e["seed"]) for e in carbon_oc_hard_0_29}
    if not prim_hard_seed_set.isdisjoint(rep_hard_seed_set):
        raise ValueError("primary 0-29 and FR8 replication hard seeds overlap")
    if not prim_hard_seed_set.isdisjoint(g1_hard_seed_set):
        raise ValueError("primary 0-29 and G1 extension hard seeds overlap")

    solver_rep_hard_30 = sorted(
        (e for e in rep_eps if e["agent"] == "solver" and e["tier"] == "hard"),
        key=lambda e: int(e["seed"]),
    )
    solver_comm_hard_30 = sorted(
        (e for e in comm_eps if e["agent"] == "solver" and e["tier"] == "hard" and int(e["seed"]) in seeds_30_59),
        key=lambda e: int(e["seed"]),
    )
    gt_30_59_by_seed = {
        int(e["seed"]): e for e in rep_eps if e["agent"] == "grok_tactics" and e["tier"] == "hard"
    }

    solver_g1_hard_2 = [e for e in solver_comm_hard_30 if int(e["seed"]) in g1_hard_seed_set]
    n_g1 = len(carbon_g1_ext_hard)
    g1_rows: list[dict[str, Any]] = [
        build_paired_row(
            "OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)",
            "v1.4/opencode-gemini-4-carbon-ext",
            "opencode:google/gemini-4-carbon",
            "hard",
            carbon_g1_ext_hard,
            solver_30_59,
            float_ndigits=None,
        ),
        build_paired_row(
            f"reference solver (same {n_g1} seeds)",
            "v1.4/reference",
            "solver",
            "hard",
            solver_g1_hard_2,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
    ]

    solver_rep_hard_5 = [e for e in solver_rep_hard_30 if int(e["seed"]) in rep_hard_seed_set]
    rep_seeds_txt = ", ".join(str(s) for s in rep_hard_seeds)
    n_rep = len(carbon_rep_hard)
    cohort_a_5_rows: list[dict[str, Any]] = [
        build_paired_row(
            f"OpenCode + gemini-4-carbon over MCP (replication seeds {rep_seeds_txt})",
            "frontier_replication/v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "hard",
            carbon_rep_hard,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"reference solver (same {n_rep} seeds)",
            "frontier_replication/v1.4/reference",
            "solver",
            "hard",
            solver_rep_hard_5,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
    ]
    for base in NON_SOLVER_BASELINES_30_59:
        base_5 = [
            e for e in rep_eps
            if e["agent"] == base and e["tier"] == "hard" and int(e["seed"]) in rep_hard_seed_set
        ]
        cohort_a_5_rows.append(
            build_paired_row(
                f"{base} (same {n_rep} seeds)",
                "frontier_replication/v1.4/reference",
                base,
                "hard",
                base_5,
                solver_30_59,
                float_ndigits=6,
                compact=True,
            )
        )

    cohort_a_30_rows: list[dict[str, Any]] = [
        build_paired_row(
            "reference solver (seeds 30-59)",
            "frontier_replication/v1.4/reference",
            "solver",
            "hard",
            solver_rep_hard_30,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        )
    ]
    for base in NON_SOLVER_BASELINES_30_59:
        base_30 = [e for e in rep_eps if e["agent"] == base and e["tier"] == "hard"]
        cohort_a_30_rows.append(
            build_paired_row(
                f"{base} (seeds 30-59)",
                "frontier_replication/v1.4/reference",
                base,
                "hard",
                base_30,
                solver_30_59,
                float_ndigits=6,
                compact=True,
            )
        )

    per_seed_rep_detail = _build_per_seed_detail(carbon_rep_hard, solver_30_59, gt_30_59_by_seed)

    carbon_union_hard_6, carbon_union_alt_6, union_source_by_seed, union_meta = dedup_extension_union(
        carbon_g1_ext_hard, carbon_rep_hard, solver_30_59
    )
    union_hard_seeds = [int(e["seed"]) for e in carbon_union_hard_6]
    union_hard_seed_set = set(union_hard_seeds)
    union_seeds_txt = ", ".join(str(s) for s in union_hard_seeds)
    n_union = len(carbon_union_hard_6)
    solver_union_hard_6 = [e for e in solver_comm_hard_30 if int(e["seed"]) in union_hard_seed_set]
    gt_union_hard_6 = [gt_30_59_by_seed[s] for s in union_hard_seeds]

    union_rows: list[dict[str, Any]] = [
        build_paired_row(
            f"OpenCode + gemini-4-carbon over MCP (deduplicated union seeds {union_seeds_txt}; committed G1 on seed 34)",
            "reconciled_30_59_union_g1_plus_fr8",
            "opencode:google/gemini-4-carbon",
            "hard",
            carbon_union_hard_6,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"OpenCode + gemini-4-carbon over MCP (union sensitivity: FR8 tie-break on seed 34, seeds {union_seeds_txt})",
            "reconciled_30_59_union_fr8_tiebreak",
            "opencode:google/gemini-4-carbon",
            "hard",
            carbon_union_alt_6,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"reference solver (same {n_union} seeds)",
            "v1.4/reference",
            "solver",
            "hard",
            solver_union_hard_6,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"grok_tactics (same {n_union} seeds)",
            "frontier_replication/v1.4/reference",
            "grok_tactics",
            "hard",
            gt_union_hard_6,
            solver_30_59,
            float_ndigits=6,
            compact=True,
        ),
    ]
    per_seed_union_detail = _build_per_seed_detail(
        carbon_union_hard_6, solver_30_59, gt_30_59_by_seed, source_by_seed=union_source_by_seed
    )

    pooled_carbon_32 = pool_disjoint_episodes(carbon_oc_hard_0_29, carbon_g1_ext_hard, "pooled_n32_primary_plus_g1")
    pooled_solver_32 = pool_disjoint_episodes(solver_hard_0_29, solver_g1_hard_2, "pooled_n32_solver")
    n_pool_32 = len(pooled_carbon_32)
    pooled_n32_rows: list[dict[str, Any]] = [
        build_paired_row(
            "OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)",
            "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext",
            "opencode:google/gemini-4-carbon",
            "hard",
            pooled_carbon_32,
            solver_pooled,
            float_ndigits=None,
        ),
        build_paired_row(
            f"reference solver (same {n_pool_32} seeds)",
            "secondary_pooled_0_29_plus_g1_2",
            "solver",
            "hard",
            pooled_solver_32,
            solver_pooled,
            float_ndigits=6,
            compact=True,
        ),
    ]

    pooled_carbon_35 = pool_disjoint_episodes(carbon_oc_hard_0_29, carbon_rep_hard, "pooled_n35_primary_plus_fr8")
    pooled_solver_35 = pool_disjoint_episodes(solver_hard_0_29, solver_rep_hard_5, "pooled_n35_solver")
    n_pool_35 = len(pooled_carbon_35)
    cohort_b_rows: list[dict[str, Any]] = [
        build_paired_row(
            f"SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + {rep_seeds_txt} replication)",
            "secondary_pooled_0_29_plus_rep5",
            "opencode:google/gemini-4-carbon",
            "hard",
            pooled_carbon_35,
            solver_pooled,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"reference solver (same {n_pool_35} seeds)",
            "secondary_pooled_0_29_plus_rep5",
            "solver",
            "hard",
            pooled_solver_35,
            solver_pooled,
            float_ndigits=6,
            compact=True,
        ),
    ]

    pooled_carbon_36 = pool_disjoint_episodes(carbon_oc_hard_0_29, carbon_union_hard_6, "pooled_n36_primary_plus_union6")
    pooled_carbon_36_alt = pool_disjoint_episodes(
        carbon_oc_hard_0_29, carbon_union_alt_6, "pooled_n36_primary_plus_union6_fr8_tiebreak"
    )
    pooled_solver_36 = pool_disjoint_episodes(solver_hard_0_29, solver_union_hard_6, "pooled_n36_solver")
    n_pool_36 = len(pooled_carbon_36)
    pooled_n36_rows: list[dict[str, Any]] = [
        build_paired_row(
            f"SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + deduplicated union {union_seeds_txt}; committed G1 seed 34)",
            "secondary_pooled_0_29_plus_union6",
            "opencode:google/gemini-4-carbon",
            "hard",
            pooled_carbon_36,
            solver_pooled,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"SECONDARY sensitivity: OpenCode + gemini-4-carbon hard pooled (0-29 primary + union {union_seeds_txt}; FR8 seed 34 tie-break)",
            "secondary_pooled_0_29_plus_union6_fr8_tiebreak",
            "opencode:google/gemini-4-carbon",
            "hard",
            pooled_carbon_36_alt,
            solver_pooled,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"reference solver (same {n_pool_36} seeds)",
            "secondary_pooled_0_29_plus_union6",
            "solver",
            "hard",
            pooled_solver_36,
            solver_pooled,
            float_ndigits=6,
            compact=True,
        ),
    ]

    flash_rep_med_29 = sorted(
        (e for e in rep_eps if e["agent"] == "opencode:google/gemini-3.5-flash" and e["tier"] == "medium"),
        key=lambda e: int(e["seed"]),
    )
    flash_med_seed_set = {int(e["seed"]) for e in flash_rep_med_29}
    flash_med_missing = sorted(seeds_0_29 - flash_med_seed_set)
    flash_med_n = len(flash_rep_med_29)
    flash_med_seeds_txt = "0-29" if not flash_med_missing else ", ".join(str(s) for s in sorted(flash_med_seed_set))
    flash_med_row_label = (
        "OpenCode + gemini-3.5-flash over MCP (seeds 0-29, complete n=30)"
        if not flash_med_missing
        else f"OpenCode + gemini-3.5-flash over MCP (seeds {flash_med_seeds_txt}; missing {flash_med_missing})"
    )

    gt_med_0_29 = simulate_grok_tactics("medium", list(range(30)))
    gt_hard_0_29 = simulate_grok_tactics("hard", list(range(30)))
    keep_alive.extend([gt_med_0_29, gt_hard_0_29])
    if verify_replays:
        verify_episode_list(gt_med_0_29 + gt_hard_0_29, "deterministic_grok_tactics_0_29")

    carbon_oc_med_29 = [e for e in carbon_oc_med_0_29 if int(e["seed"]) in flash_med_seed_set]
    carbon_ip_med_29 = [e for e in carbon_ip_med_0_29 if int(e["seed"]) in flash_med_seed_set]
    solver_med_29 = [e for e in solver_med_0_29 if int(e["seed"]) in flash_med_seed_set]
    gt_med_29 = [e for e in gt_med_0_29 if int(e["seed"]) in flash_med_seed_set]

    cross_model_med_29_rows: list[dict[str, Any]] = [
        build_paired_row(
            f"OpenCode + gemini-4-carbon over MCP (shared {flash_med_n} seeds)",
            "v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "medium",
            carbon_oc_med_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"reference solver (shared {flash_med_n} seeds)",
            "v1.4/reference",
            "solver",
            "medium",
            solver_med_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"in-process gemini-4-carbon (shared {flash_med_n} seeds)",
            "v1.4/inproc-gemini-4-carbon",
            "gemini:gemini-4-carbon",
            "medium",
            carbon_ip_med_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            f"grok_tactics (deterministic scripted policy, shared {flash_med_n} seeds)",
            "deterministic_policy_v1.4",
            "grok_tactics",
            "medium",
            gt_med_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            flash_med_row_label,
            "frontier_replication/v1.4/opencode-gemini-3.5-flash",
            "opencode:google/gemini-3.5-flash",
            "medium",
            flash_rep_med_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
    ]
    flash_med_n29_full_row = build_paired_row(
        flash_med_row_label,
        "frontier_replication/v1.4/opencode-gemini-3.5-flash",
        "opencode:google/gemini-3.5-flash",
        "medium",
        flash_rep_med_29,
        solver_0_29,
        float_ndigits=6,
        compact=False,
    )

    cross_model_hard_30_rows: list[dict[str, Any]] = [
        build_paired_row(
            "reference solver (seeds 0-29)",
            "v1.4/reference",
            "solver",
            "hard",
            solver_hard_0_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            "in-process gemini-4-carbon (seeds 0-29)",
            "v1.4/inproc-gemini-4-carbon",
            "gemini:gemini-4-carbon",
            "hard",
            carbon_ip_hard_0_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            "grok_tactics (deterministic scripted policy, seeds 0-29)",
            "deterministic_policy_v1.4",
            "grok_tactics",
            "hard",
            gt_hard_0_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
        build_paired_row(
            "OpenCode + gemini-4-carbon over MCP (primary seeds 0-29)",
            "v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "hard",
            carbon_oc_hard_0_29,
            solver_0_29,
            float_ndigits=6,
            compact=True,
        ),
    ]
    if include_flash_hard:
        cross_model_hard_30_rows.append(
            build_paired_row(
                "OpenCode + gemini-3.5-flash over MCP (seeds 0-29)",
                "v1.4/opencode-gemini-3.5-flash",
                "opencode:google/gemini-3.5-flash",
                "hard",
                flash_oc_hard_0_29,
                solver_0_29,
                float_ndigits=6,
                compact=True,
            )
        )

    gt_med_30_row = build_paired_row(
        "grok_tactics (deterministic scripted policy, seeds 0-29)",
        "deterministic_policy_v1.4",
        "grok_tactics",
        "medium",
        gt_med_0_29,
        solver_0_29,
        float_ndigits=6,
        compact=True,
    )

    h2h_med = head_to_head_diff(
        f"OpenCode gemini-4-carbon minus gemini-3.5-flash on medium (shared seeds {flash_med_seeds_txt})",
        "medium",
        carbon_oc_med_29,
        flash_rep_med_29,
        float_ndigits=6,
    )
    h2h_map: dict[str, Any] = {"medium_n29": h2h_med}
    if include_flash_hard:
        h2h_map["hard_n30"] = head_to_head_diff(
            "OpenCode gemini-4-carbon minus gemini-3.5-flash on hard (shared seeds 0-29)",
            "hard",
            carbon_oc_hard_0_29,
            flash_oc_hard_0_29,
            float_ndigits=6,
        )

    gpt55_committed_count = sum(1 for e in comm_eps if "gpt-5.5" in str(e.get("agent") or ""))
    all_pooled_exclude_parity = bool(
        pooled_n32_rows[0]["post_expected_hi"] < 1.0
        and cohort_b_rows[0]["post_expected_hi"] < 1.0
        and pooled_n36_rows[0]["post_expected_hi"] < 1.0
        and pooled_n36_rows[1]["post_expected_hi"] < 1.0
    )

    return clean_json(
        {
            "schema_version": "v1.4-frontier-replication-2",
            "tiers_version": "v1.4",
            "zero_live_api_calls": True,
            "zero_git_dependency": True,
            "pre_registered_rule": {
                "enforced": True,
                "primary_seeds": list(range(30)),
                "primary_lock_classification": "post_hoc_lock",
                "primary_episodes_commit": "8fd4dec",
                "primary_lock_commit": "671ed96",
                "primary_lock_delay_s": 28,
                "g1_extension_classification": "pre_registered",
                "g1_prereg_commit": "f9fb7a4a",
                "g1_carbon_ext_hard_seeds": g1_hard_seeds,
                "gpt_5_5_classification": "pre_registered",
                "gpt_5_5_prereg_commit": "cf394894",
                "gpt_5_5_committed_v14_episodes": gpt55_committed_count,
                "replication_carbon_hard_seeds": rep_hard_seeds,
                "union_dedup_hard_seeds": union_hard_seeds,
                "shared_extension_seeds": union_meta["shared_seeds"],
                "shared_seed_tiebreak_rule": union_meta["dedup_rule"],
                "primary_and_replication_disjoint": True,
                "pooled_n32_classification": "secondary_sensitivity_only",
                "pooled_n35_classification": "secondary_sensitivity_only",
                "pooled_n36_classification": "secondary_sensitivity_only",
                "source_rule": (
                    "docs/reports/gap.md (primary 0-29 post-hoc lock in 671ed96, 28 s after 8fd4dec, "
                    "not pre-registered; G1 extension pre-registered in f9fb7a4a; gpt-5.5 pre-registered "
                    "in cf394894; repeated seed deduplication per eb9dee54)"
                ),
            },
            "replay_verification": {
                "committed_v14": comm_audit,
                "replication_v14": rep_audit,
                "step_error_detail_1bc3e281_compat": True,
                "committed_breakdown": {
                    "opencode_gemini_4_carbon_primary_0_29": len(carbon_oc_med_0_29) + len(carbon_oc_hard_0_29),
                    "opencode_gemini_4_carbon_g1_ext_hard": len(carbon_g1_ext_hard),
                    "inproc_gemini_4_carbon_0_29": len(carbon_ip_med_0_29) + len(carbon_ip_hard_0_29),
                    "opencode_gemini_3_5_flash_hard_0_29": len(flash_oc_hard_0_29),
                    "reference_solver_0_29_and_30_59": len(solver_med_0_29) + len(solver_hard_0_29) + len(solver_comm_hard_30),
                    "baselines_0_19": (
                        len(comm_eps)
                        - len(carbon_oc_med_0_29)
                        - len(carbon_oc_hard_0_29)
                        - len(carbon_g1_ext_hard)
                        - len(carbon_ip_med_0_29)
                        - len(carbon_ip_hard_0_29)
                        - len(flash_oc_hard_0_29)
                        - len(solver_med_0_29)
                        - len(solver_hard_0_29)
                        - len(solver_comm_hard_30)
                    ),
                },
                "replication_breakdown": {
                    "opencode_gemini_4_carbon_hard": len(carbon_rep_hard),
                    "opencode_gemini_3_5_flash_medium": len(flash_rep_med_29),
                    "reference_and_baselines_hard_30_59": len(rep_eps) - len(carbon_rep_hard) - len(flash_rep_med_29),
                },
            },
            "solver_30_59_parity": solver_30_59_parity,
            "primary_v14_0_29": {
                "classification": "primary_headline_locked",
                "rows": primary_rows,
            },
            "g1_committed_ext_hard_n2": {
                "classification": "pre_registered_partial_extension",
                "prereg_commit": "f9fb7a4a",
                "source_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                "seeds": g1_hard_seeds,
                "pending_seeds_in_30_59": sorted(seeds_30_59 - g1_hard_seed_set),
                "rows": g1_rows,
            },
            "cohort_a_carbon_hard_replication": {
                "classification": "replication_separate",
                "seeds": rep_hard_seeds,
                "pending_seeds_in_30_59": sorted(seeds_30_59 - rep_hard_seed_set),
                "paired_5_seeds_rows": cohort_a_5_rows,
                "per_seed_detail": per_seed_rep_detail,
                "reference_30_59_rows": cohort_a_30_rows,
            },
            "union_dedup_hard_n6": {
                "classification": "deduplicated_30_59_extension_union",
                "dedup_rule": union_meta["dedup_rule"],
                "seeds": union_hard_seeds,
                "g1_only_seeds": union_meta["g1_only_seeds"],
                "fr8_only_seeds": union_meta["fr8_only_seeds"],
                "shared_seeds": union_meta["shared_seeds"],
                "dropped_duplicate_episodes": union_meta["dropped_duplicate_episodes"],
                "pending_seeds_in_30_59": sorted(seeds_30_59 - union_hard_seed_set),
                "shared_seed_comparisons": union_meta["shared_seed_comparisons"],
                "rows": union_rows,
                "per_seed_detail": per_seed_union_detail,
            },
            "cohort_b_secondary_pooled_hard_n35": {
                "classification": "secondary_sensitivity_only",
                "seeds": [int(e["seed"]) for e in pooled_carbon_35],
                "rows": cohort_b_rows,
            },
            "secondary_pooled_hard_reconciliation": {
                "classification": "secondary_sensitivity_only",
                "primary_headline_n": len(carbon_oc_hard_0_29),
                "no_duplicate_seeds_verified": True,
                "all_luck_adjusted_95ci_exclude_parity": all_pooled_exclude_parity,
                "n32_primary_plus_g1": {
                    "seeds": [int(e["seed"]) for e in pooled_carbon_32],
                    "rows": pooled_n32_rows,
                },
                "n35_primary_plus_fr8": {
                    "seeds": [int(e["seed"]) for e in pooled_carbon_35],
                    "cohort_ref": "cohort_b_secondary_pooled_hard_n35",
                },
                "n36_primary_plus_union6": {
                    "seeds": [int(e["seed"]) for e in pooled_carbon_36],
                    "rows": pooled_n36_rows,
                },
            },
            "cohort_c_flash_and_cross_model": {
                "flash_hard_held_pending_gap_md": not include_flash_hard,
                "flash_medium_n29_row": flash_med_n29_full_row,
                "flash_medium_missing_seeds_in_0_29": sorted(seeds_0_29 - flash_med_seed_set),
                "flash_hard_n30_row": cross_model_hard_30_rows[-1] if include_flash_hard else None,
                "grok_tactics_medium_0_29_row": gt_med_30_row,
                "cross_model_medium_same_29_seeds_rows": cross_model_med_29_rows,
                "cross_model_hard_0_29_rows": cross_model_hard_30_rows,
                "head_to_head_carbon_vs_flash": h2h_map,
            },
        }
    )


def _num(x: float | None, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _signed(x: float | None, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+.{nd}f}"


def _ratio_cell(r: dict[str, Any], bold: bool = False) -> str:
    if r["agent"] == "solver" or r["ratio"] is None:
        return "n/a"
    if r["ratio_lo"] is None or r["ratio_hi"] is None:
        txt = f"{r['ratio']:.0%}"
    else:
        txt = f"{r['ratio']:.0%} [{r['ratio_lo']:.0%}, {r['ratio_hi']:.0%}]"
    return f"**{txt}**" if bold else txt


def _luck_cell(r: dict[str, Any], bold: bool = True) -> str:
    if r["agent"] == "solver" or r["post_expected_ratio"] is None:
        return "n/a"
    if r["post_expected_lo"] is None or r["post_expected_hi"] is None:
        txt = f"{r['post_expected_ratio']:.0%}"
    else:
        txt = f"{r['post_expected_ratio']:.0%} [{r['post_expected_lo']:.0%}, {r['post_expected_hi']:.0%}]"
    return f"**{txt}**" if bold else txt


def _paired_table_md(rows: list[dict[str, Any]], include_tier: bool = True) -> list[str]:
    if include_tier:
        hdr = (
            "| tier | run | n | score +/- 95% CI | accuracy | accused | mean accuse day | "
            "mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | "
            "luck-adjusted score | luck-adj. / solver [95% CI] |"
        )
        sep = "|---|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|"
    else:
        hdr = (
            "| run | n | score +/- 95% CI | accuracy | accused | mean accuse day | "
            "mean P(accused) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | "
            "luck-adjusted score | luck-adj. / solver [95% CI] |"
        )
        sep = "|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|"
    lines = [hdr, sep]
    for r in rows:
        is_solver = r["agent"] == "solver"
        diff_txt = "n/a" if is_solver else f"{_signed(r['diff'])} +/- {_num(r['diff_ci'])}"
        acc_day_txt = _num(r["accuse_day"], 1) if r["accused_rate"] > 0 else "0.0"
        prefix = f"| {r['tier']} | {r['label']} |" if include_tier else f"| {r['label']} |"
        lines.append(
            f"{prefix} {r['n']} | {_num(r['mean'])} +/- {_num(r['ci'])} | {r['accuracy']:.2f} | "
            f"{r['accused_rate']:.2f} | {acc_day_txt} | {_num(r['p_accused'], 2)} | {_num(r['solver_same_seeds'])} | "
            f"{_ratio_cell(r)} | {diff_txt} | {_num(r['post_expected'])} | {_luck_cell(r)} |"
        )
    return lines


def _md_heading(level: int, title: str) -> str:
    return (chr(35) * level) + " " + title


def render_markdown(summary: dict[str, Any]) -> str:
    rv = summary["replay_verification"]
    rb = rv["replication_breakdown"]
    cbk = rv["committed_breakdown"]
    sp = summary["solver_30_59_parity"]
    rule = summary["pre_registered_rule"]
    prim_rows = summary["primary_v14_0_29"]["rows"]
    g1 = summary["g1_committed_ext_hard_n2"]
    ca = summary["cohort_a_carbon_hard_replication"]
    cb = summary["cohort_b_secondary_pooled_hard_n35"]
    u6 = summary["union_dedup_hard_n6"]
    sec_pool = summary["secondary_pooled_hard_reconciliation"]
    cc = summary["cohort_c_flash_and_cross_model"]

    prim_by_key = {(r["agent"], r["tier"], r["label"]): r for r in prim_rows}
    c_hard_prim = prim_by_key[("opencode:google/gemini-4-carbon", "hard", "OpenCode + gemini-4-carbon over MCP (judges' shape)")]
    c_med_prim = prim_by_key[("opencode:google/gemini-4-carbon", "medium", "OpenCode + gemini-4-carbon over MCP (judges' shape)")]
    s_hard_prim = prim_by_key[("solver", "hard", "reference solver")]
    c_ip_hard_prim = prim_by_key[("gemini:gemini-4-carbon", "hard", "in-process gemini-4-carbon (full history, thought-signature replay)")]

    c_g1_2 = g1["rows"][0]
    c_rep_5 = ca["paired_5_seeds_rows"][0]
    c_union_6 = u6["rows"][0]
    c_union_6_alt = u6["rows"][1]
    s_rep_30 = ca["reference_30_59_rows"][0]

    n35_rows = sec_pool["n35_primary_plus_fr8"].get("rows") or cb["rows"]
    c_pool_32 = sec_pool["n32_primary_plus_g1"]["rows"][0]
    c_pool_35 = n35_rows[0]
    c_pool_36 = sec_pool["n36_primary_plus_union6"]["rows"][0]
    c_pool_36_alt = sec_pool["n36_primary_plus_union6"]["rows"][1]

    f_hard_prim = cc["flash_hard_n30_row"]
    flash_hard_held = bool(cc.get("flash_hard_held_pending_gap_md", f_hard_prim is None))
    f_med_rep = cc["flash_medium_n29_row"]
    c_med_29 = cc["cross_model_medium_same_29_seeds_rows"][0]
    gt_med_29 = cc["cross_model_medium_same_29_seeds_rows"][3]
    gt_hard_30 = cc["cross_model_hard_0_29_rows"][2]
    seed30_detail = ca["per_seed_detail"][0]
    s34_cmp = u6["shared_seed_comparisons"][0]
    h2h_med = cc["head_to_head_carbon_vs_flash"]["medium_n29"]
    h2h_hard = cc["head_to_head_carbon_vs_flash"].get("hard_n30")

    g1_seeds_str = ", ".join(str(s) for s in g1["seeds"])
    rep_seeds_str = ", ".join(str(s) for s in ca["seeds"])
    union_seeds_str = ", ".join(str(s) for s in u6["seeds"])
    med_seeds_str = "0-29" if not cc["flash_medium_missing_seeds_in_0_29"] else ", ".join(str(s) for s in f_med_rep["seeds"])
    rep_correct = round(c_rep_5["accuracy"] * c_rep_5["n"])

    if not flash_hard_held and f_hard_prim is not None and h2h_hard is not None:
        cross_model_bullet = (
            f"  - **Cross-model ordering (`gemini-4-carbon` vs `gemini-3.5-flash` vs `grok_tactics` vs `solver`):** "
            f"On medium (`n={f_med_rep['n']}` shared seeds `{med_seeds_str}`, separate FR8 replication cohort), "
            f"`opencode:google/gemini-3.5-flash` reaches `{_ratio_cell(f_med_rep)}` raw / "
            f"`{_luck_cell(f_med_rep, bold=False)}` luck-adjusted (`gemini-4-carbon - gemini-3.5-flash = "
            f"{_signed(h2h_med['raw_diff'])} +/- {_num(h2h_med['raw_diff_ci'])}` V raw, "
            f"`{_signed(h2h_med['luck_adjusted_diff'])} +/- {_num(h2h_med['luck_adjusted_diff_ci'])}` V luck-adjusted). "
            f"On hard (`n=30`, `0-29`), `gemini-3.5-flash`'s raw `{_ratio_cell(f_hard_prim)}` reflects 7 lucky sub-break-even guesses "
            f"(mean `P(accused) = {_num(f_hard_prim['p_accused'], 2)}`); its luck-adjusted ratio falls to **{_luck_cell(f_hard_prim, bold=False)}** "
            f"(`gemini-4-carbon - gemini-3.5-flash = {_signed(h2h_hard['luck_adjusted_diff'])} +/- {_num(h2h_hard['luck_adjusted_diff_ci'])}` V/episode)."
        )
    else:
        cross_model_bullet = (
            f"  - **Cross-model replication (`gemini-3.5-flash` medium `n={f_med_rep['n']}`, separate FR8 replication cohort):** "
            f"On medium (`n={f_med_rep['n']}` shared seeds `{med_seeds_str}`), `opencode:google/gemini-3.5-flash` reaches "
            f"`{_ratio_cell(f_med_rep)}` raw / `{_luck_cell(f_med_rep, bold=False)}` luck-adjusted (`gemini-4-carbon - gemini-3.5-flash = "
            f"{_signed(h2h_med['raw_diff'])} +/- {_num(h2h_med['raw_diff_ci'])}` V raw, "
            f"`{_signed(h2h_med['luck_adjusted_diff'])} +/- {_num(h2h_med['luck_adjusted_diff_ci'])}` V luck-adjusted). "
            "`docs/reports/gap.md` is the sole source for primary `hard` (`0-29`) gap rows; `opencode:google/gemini-3.5-flash` hard "
            f"is replay-verified in `committed_v14` (`{rv['committed_v14']['verified']}/{rv['committed_v14']['total']}`) and omitted from tables here until `docs/reports/gap.md` ships it."
        )

    pooled_all_rows = (
        sec_pool["n32_primary_plus_g1"]["rows"]
        + n35_rows
        + sec_pool["n36_primary_plus_union6"]["rows"]
    )

    lines: list[str] = [
        _md_heading(1, "Canary v1.4 Frontier Replication and Cross-Model Capability Report"),
        "",
        "Every figure in this report is deterministically computed from replay-verified episodes by "
        "`scripts/verify_frontier_replication.py` using `canary.analysis.gap` (`load_runs`, `mean_ci`) and "
        "`scripts/paired_v13.py` (`boot_ratio`, `p_acc`, `post_expected`), with zero live API calls and zero runtime `.git` calls.",
        "",
        "Reproduce and verify:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/verify_frontier_replication.py --check",
        "```",
        "",
        _md_heading(2, "1. Post-Hoc Seed Lock, Pre-Registered Extensions, and Replay Audit"),
        "",
        "- **Post-hoc seed lock and pre-registered extensions (`docs/reports/gap.md`, commits `8fd4dec`, `671ed96`, `f9fb7a4a`, `cf394894`, `eb9dee54`):** "
        "The `justSilas` committed dev set (`seeds 0-29`, `n=30` per tier in `data/runs/committed/v1.4/`) is the locked "
        "**PRIMARY** headline result (`671ed96` came 28 s after `8fd4dec`, so it is a post-hoc lock against later reruns "
        "and cherry-picking, not a pre-registration). By contrast, the G1 `opencode-gemini-4-carbon-ext` hard extension "
        f"(`seeds {g1_seeds_str}`, `n={c_g1_2['n']}` completed before early quota stop, pre-registered in `f9fb7a4a`) and the second "
        f"frontier family `gpt-5.5` (`v1.4` hard `seeds 0-29`, OpenCode `1.19.5`, pre-registered in `cf394894`, `{rule['gpt_5_5_committed_v14_episodes']}` "
        "committed v1.4 episodes at `58716742`) were pre-registered before any episode launched. All FR8 episodes under "
        "`results/frontier_replication/v1.4/` are evaluated separately; when G1 and FR8 `30-59` hard runs are reconciled into "
        f"the deduplicated 6-seed union (`seeds {union_seeds_str}`, `n={c_union_6['n']}`), shared seed `34` deterministically uses committed "
        "`opencode-gemini-4-carbon-ext` (`eb9dee54`, never double-counting a repeated `(tier, seed)`).",
        f"- **Replay verification (`scripts/verify_replay.py`, commit `1bc3e281` compatibility) and solver `30-59` parity:** "
        f"`{rv['committed_v14']['verified']}/{rv['committed_v14']['total']}` episodes verified in `data/runs/committed/v1.4/` "
        f"(`{cbk['opencode_gemini_4_carbon_primary_0_29']}` primary OpenCode carbon, `{cbk['opencode_gemini_4_carbon_g1_ext_hard']}` G1 carbon-ext, "
        f"`{cbk['inproc_gemini_4_carbon_0_29']}` in-process carbon, `{cbk['opencode_gemini_3_5_flash_hard_0_29']}` OpenCode flash hard, "
        f"`{cbk['reference_solver_0_29_and_30_59']}` solver, `{cbk['baselines_0_19']}` baselines) and "
        f"`{rv['replication_v14']['verified']}/{rv['replication_v14']['total']}` episodes verified in `results/frontier_replication/v1.4/` "
        f"(`{rb['opencode_gemini_4_carbon_hard']}` OpenCode carbon hard, `{rb['opencode_gemini_3_5_flash_medium']}` OpenCode flash medium, "
        f"`{rb['reference_and_baselines_hard_30_59']}` reference solver and baselines on hard `seeds 30-59`), with `0` mismatches and `0` "
        f"intra-cohort duplicates across all `{rv['committed_v14']['verified'] + rv['replication_v14']['verified']}` episodes "
        f"(including `{rv['committed_v14']['pre_1bc3e281_error_steps']}` committed and `{rv['replication_v14']['pre_1bc3e281_error_steps']}` replication "
        "pre-`1bc3e281` tool-error steps recorded before `data.detail` was added). Furthermore, `solver-hard-seeds30to59` matches "
        f"`{sp['matched']}/{sp['n']}` (`0` mismatches on `score`, `accused`, `correct`, and `final_day`) between "
        "`data/runs/committed/v1.4/reference/` and `results/frontier_replication/v1.4/reference/`.",
        "- **Headline and reconciled extension summary:**",
        f"  - **Primary `0-29` (`n=30`, locked headline):** `opencode:google/gemini-4-carbon` on hard scores "
        f"`{_num(c_hard_prim['mean'])} +/- {_num(c_hard_prim['ci'])}` vs solver `{_num(c_hard_prim['solver_same_seeds'])}`, "
        f"giving **{_ratio_cell(c_hard_prim)}** raw and **{_luck_cell(c_hard_prim, bold=False)}** luck-adjusted; on medium (`n=30`) "
        f"it reaches `{_ratio_cell(c_med_prim)}` raw and `{_luck_cell(c_med_prim, bold=False)}` luck-adjusted.",
        f"  - **Reconciled `30-59` hard extensions (`n=2` G1, `n=5` FR8, `n=6` deduplicated union, separate cohorts):** "
        f"Committed G1 (`seeds {g1_seeds_str}`, `n={c_g1_2['n']}`) scores `{_num(c_g1_2['mean'])} +/- {_num(c_g1_2['ci'])}` vs solver "
        f"`{_num(c_g1_2['solver_same_seeds'])}` (`{_ratio_cell(c_g1_2)}` raw, `{_luck_cell(c_g1_2, bold=False)}` luck-adjusted); "
        f"FR8 replication (`seeds {rep_seeds_str}`, `n={c_rep_5['n']}`) scores `{_num(c_rep_5['mean'])} +/- {_num(c_rep_5['ci'])}` "
        f"({rep_correct}/{c_rep_5['n']} correct, luck-adjusted `{_num(c_rep_5['post_expected'])}`) vs solver `{_num(c_rep_5['solver_same_seeds'])}` raw "
        f"(`{_luck_cell(c_rep_5, bold=False)}` luck-adjusted); and the deduplicated 6-seed union (`seeds {union_seeds_str}`, `n={c_union_6['n']}`, "
        f"committed G1 on shared seed `34`) scores `{_num(c_union_6['mean'])} +/- {_num(c_union_6['ci'])}` vs solver `{_num(c_union_6['solver_same_seeds'])}` "
        f"(`{_ratio_cell(c_union_6)}` raw, `{_luck_cell(c_union_6, bold=False)}` luck-adjusted; FR8 seed-34 tie-break: `{_luck_cell(c_union_6_alt, bold=False)}`).",
        f"  - **Secondary pooled hard sensitivity (`n=32`, `n=35`, `n=36`, secondary under post-hoc seed lock `671ed96`):** "
        f"Pooling primary `0-29` with G1 (`n={c_pool_32['n']}`, matching `README.md` / `docs/reports/gap.md`) gives `{_ratio_cell(c_pool_32)}` raw and "
        f"**{_luck_cell(c_pool_32, bold=False)}** luck-adjusted; pooling with FR8 (`n={c_pool_35['n']}`) gives `{_ratio_cell(c_pool_35)}` raw and "
        f"**{_luck_cell(c_pool_35, bold=False)}** luck-adjusted; and pooling with the deduplicated 6-seed union (`n={c_pool_36['n']}`, `0` duplicate seeds) "
        f"gives `{_ratio_cell(c_pool_36)}` raw and **{_luck_cell(c_pool_36, bold=False)}** luck-adjusted (`post_expected_hi = {_num(c_pool_36['post_expected_hi'])} < 1.000`; "
        f"FR8 seed-34 tie-break: `{_luck_cell(c_pool_36_alt, bold=False)}`). Across all secondary pooled sets (`n=32`, `n=35`, `n=36`), the luck-adjusted 95% CI continues to exclude parity.",
        cross_model_bullet,
        "",
        _md_heading(2, "2. Primary Committed v1.4 Cohort (Seeds 0-29, Locked Headline)"),
        "",
        "Exact reproduction of `docs/reports/gap.md` rows in `data/runs/committed/v1.4/` (`scripts/paired_gemini.py --version v1.4 --seeds 0-29`; solver `0-29` spans `solver-*-20261114-121126` for `0-19` plus `solver-*-seeds20to29` for `20-29`):",
        "",
    ]
    lines.extend(_paired_table_md(prim_rows, include_tier=True))
    lines.extend(
        [
            "",
            "Note on `stop_early` provenance: the `data/runs/committed/v1.4/reference/stop_early-*` episodes (`seeds 0-19`) "
            "were recorded under the earlier day-1 random accusation baseline (now named `guess_day1`), whereas current "
            "`stop_early` (`StopEarlyQuit` in `canary/baselines.py`, used in `seeds 30-59` below) stops on day 1 without accusing and scores `0.000`.",
            "",
            _md_heading(2, f"3. Cohort (a): Reconciled Seeds 30-59 Hard Extensions (G1 n={c_g1_2['n']}, FR8 n={c_rep_5['n']}, Deduplicated Union n={c_union_6['n']}) and Baselines"),
            "",
            _md_heading(3, f"3.1 Committed G1 Partial Hard Extension (`seeds {g1_seeds_str}`, `n={c_g1_2['n']}`, Pre-Registered in `f9fb7a4a`)"),
            "",
            f"`{c_g1_2['n']}` valid episodes completed in `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard` before the run was stopped early "
            f"to preserve shared carbon quota for the Harbor rehearsal ({len(g1['pending_seeds_in_30_59'])} seeds in `30-59` stopped on `infra:provider_quota`), "
            f"paired on `{g1['seeds']}` against `data/runs/committed/v1.4/reference/solver-hard-seeds30to59`:",
            "",
        ]
    )
    lines.extend(_paired_table_md(g1["rows"], include_tier=False))
    lines.extend(
        [
            "",
            _md_heading(3, f"3.2 FR8 Hard Replication Cohort (`seeds {rep_seeds_str}`, `n={c_rep_5['n']}`)"),
            "",
            f"`{c_rep_5['n']}` completed `opencode:google/gemini-4-carbon` episodes in `results/frontier_replication/v1.4/opencode-gemini-4-carbon/` "
            f"({len(ca['pending_seeds_in_30_59'])} seeds in `30-59` remain pending in FR8), paired on the exact same {c_rep_5['n']} seeds against "
            "`results/frontier_replication/v1.4/reference/solver-hard-seeds30to59` and all 8 non-solver baselines:",
            "",
        ]
    )
    lines.extend(_paired_table_md(ca["paired_5_seeds_rows"], include_tier=False))
    lines.extend(
        [
            "",
            f"Per-seed inspection on `{ca['seeds']}` explains why the raw {c_rep_5['n']}-seed ratio (`{c_rep_5['ratio']:.0%}`) is much higher than the "
            f"luck-adjusted ratio (`{_luck_cell(c_rep_5, bold=False)}`): on seed `{seed30_detail['seed']}` the reference solver suffered a "
            f"`{_signed(seed30_detail['solver_score'])}` wrong accusation on day `{seed30_detail['solver_day']}` "
            f"(pulling the {c_rep_5['n']}-seed raw solver mean down to `{_num(c_rep_5['solver_same_seeds'])}`), while under posterior expectation "
            f"the two agents are close (`{_num(c_rep_5['post_expected'])}` vs `{_num(c_rep_5['solver_post_expected'])}`):",
            "",
            "| seed | carbon score | carbon correct | carbon day | carbon P(accused) | carbon luck-adj. | solver score | solver correct | solver day | solver P(accused) | solver luck-adj. | grok_tactics score | grok_tactics luck-adj. |",
            "|---:|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
        ]
    )
    for d in ca["per_seed_detail"]:
        lines.append(
            f"| {d['seed']} | {_signed(d['carbon_score'])} | {d['carbon_correct']} | {d['carbon_day']} | "
            f"{_num(d['carbon_p_accused'], 3)} | {_signed(d['carbon_luck_adjusted'])} | {_signed(d['solver_score'])} | "
            f"{d['solver_correct']} | {d['solver_day']} | {_num(d['solver_p_accused'], 3)} | {_signed(d['solver_luck_adjusted'])} | "
            f"{_signed(d['grok_tactics_score'])} | {_signed(d['grok_tactics_luck_adjusted'])} |"
        )
    lines.extend(
        [
            "",
            _md_heading(3, f"3.3 Deduplicated 6-Seed Hard Extension Union (`seeds {union_seeds_str}`, `n={c_union_6['n']}`, `eb9dee54`) and Seed-34 Comparison"),
            "",
            f"Combining G1 (`seeds {g1_seeds_str}`) and FR8 (`seeds {rep_seeds_str}`) covers `{c_union_6['n']}` unique seeds in `30-59` "
            f"(`{union_seeds_str}`, with `{len(u6['pending_seeds_in_30_59'])}` seeds in `30-59` still unplayed). Seed `{s34_cmp['seed']}` was played independently "
            "in both G1 and FR8; per `eb9dee54` (never double-count a repeated `(tier, seed)` when pooling), the canonical union deterministically selects "
            f"the committed G1 episode (`{u6['dropped_duplicate_episodes']}` duplicate episode dropped), with the FR8 tie-break shown alongside for sensitivity:",
            "",
        ]
    )
    lines.extend(_paired_table_md(u6["rows"], include_tier=False))
    lines.extend(
        [
            "",
            f"Side-by-side reconciliation on shared seed `{s34_cmp['seed']}` (true mole `{s34_cmp['solver']['accused']}`):",
            "",
            "| cohort / run | source | score | correct | accused | final day | P(accused) | luck-adjusted score |",
            "|---|---|---:|---|---|---:|---:|---:|",
            f"| Committed G1 (selected for union) | `{s34_cmp['committed_g1']['source']}` | {_signed(s34_cmp['committed_g1']['score'])} | "
            f"{s34_cmp['committed_g1']['correct']} | `{s34_cmp['committed_g1']['accused']}` | {s34_cmp['committed_g1']['final_day']} | "
            f"{_num(s34_cmp['committed_g1']['p_accused'], 3)} | {_signed(s34_cmp['committed_g1']['luck_adjusted'])} |",
            f"| FR8 replication (tie-break sensitivity) | `{s34_cmp['fr8_replication']['source']}` | {_signed(s34_cmp['fr8_replication']['score'])} | "
            f"{s34_cmp['fr8_replication']['correct']} | `{s34_cmp['fr8_replication']['accused']}` | {s34_cmp['fr8_replication']['final_day']} | "
            f"{_num(s34_cmp['fr8_replication']['p_accused'], 3)} | {_signed(s34_cmp['fr8_replication']['luck_adjusted'])} |",
            f"| Reference solver | `{s34_cmp['solver']['source']}` | {_signed(s34_cmp['solver']['score'])} | "
            f"{s34_cmp['solver']['correct']} | `{s34_cmp['solver']['accused']}` | {s34_cmp['solver']['final_day']} | "
            f"{_num(s34_cmp['solver']['p_accused'], 3)} | {_signed(s34_cmp['solver']['luck_adjusted'])} |",
            "",
            f"Per-seed breakdown across all `{c_union_6['n']}` unique seeds in the deduplicated `30-59` union:",
            "",
            "| seed | union source | carbon score | carbon correct | carbon day | carbon P(accused) | carbon luck-adj. | solver score | solver correct | solver day | solver luck-adj. | grok_tactics score | grok_tactics luck-adj. |",
            "|---:|---|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for d in u6["per_seed_detail"]:
        lines.append(
            f"| {d['seed']} | `{d['source']}` | {_signed(d['carbon_score'])} | {d['carbon_correct']} | {d['carbon_day']} | "
            f"{_num(d['carbon_p_accused'], 3)} | {_signed(d['carbon_luck_adjusted'])} | {_signed(d['solver_score'])} | "
            f"{d['solver_correct']} | {d['solver_day']} | {_signed(d['solver_luck_adjusted'])} | "
            f"{_signed(d['grok_tactics_score'])} | {_signed(d['grok_tactics_luck_adjusted'])} |"
        )
    lines.extend(
        [
            "",
            _md_heading(3, "3.4 Full Hard Extension Reference and Baselines (`seeds 30-59`, `n=30`) and Solver Parity (`30/30`)"),
            "",
            f"Exact `{sp['matched']}/{sp['n']}` per-seed parity (`score`, `accused`, `correct`, `final_day`) holds between "
            f"`{sp['committed_dir']}` and `{sp['replication_dir']}`. Across all 30 extension seeds (`30-59`), "
            f"the reference solver averages `{_num(s_rep_30['mean'])} +/- {_num(s_rep_30['ci'])}` (`{_num(s_rep_30['post_expected'])}` luck-adjusted), "
            f"matching its `0-29` mean (`{_num(s_hard_prim['mean'])} +/- {_num(s_hard_prim['ci'])}`), "
            "while all 8 non-solver baselines remain well below solver parity on luck-adjusted value:",
            "",
        ]
    )
    lines.extend(_paired_table_md(ca["reference_30_59_rows"], include_tier=False))
    lines.extend(
        [
            "",
            _md_heading(2, f"4. Cohort (b): Secondary Pooled Hard Sensitivity Reconciliation (`n={c_pool_32['n']}`, `n={c_pool_35['n']}`, `n={c_pool_36['n']}`)"),
            "",
            f"**SECONDARY SENSITIVITY ONLY (NOT THE HEADLINE):** Per the post-hoc seed lock (`docs/reports/gap.md`, commit `671ed96`), "
            f"the `n={c_hard_prim['n']}` (`seeds 0-29`) result remains the primary headline (`{_ratio_cell(c_hard_prim)}` raw, "
            f"`{_luck_cell(c_hard_prim, bold=False)}` luck-adjusted). Reconciling all non-overlapping pooled combinations with primary `0-29` "
            f"(`n={c_pool_32['n']}` with committed G1 `{g1_seeds_str}`, `n={c_pool_35['n']}` with FR8 `{rep_seeds_str}`, and `n={c_pool_36['n']}` "
            f"with the deduplicated 6-seed union `{union_seeds_str}`, `0` duplicate seeds in every pool) shows that every luck-adjusted 95% CI "
            f"continues to exclude parity (`post_expected_hi` = `{_num(c_pool_32['post_expected_hi'])}`, `{_num(c_pool_35['post_expected_hi'])}`, "
            f"and `{_num(c_pool_36['post_expected_hi'])}`, all `< 1.000`):",
            "",
        ]
    )
    lines.extend(_paired_table_md(pooled_all_rows, include_tier=False))
    sec5_title = (
        f"5. Cohort (c): gemini-3.5-flash Medium (`n={f_med_rep['n']}`) + Hard (`n=30`) and Cross-Model Capability Ordering"
        if not flash_hard_held
        else f"5. Cohort (c): gemini-3.5-flash Medium Replication (`n={f_med_rep['n']}`) and Capability Ordering"
    )
    lines.extend(
        [
            "",
            _md_heading(2, sec5_title),
            "",
            _md_heading(3, f"5.1 Cross-Model Capability Ordering on Medium (`seeds {med_seeds_str}`, `n={f_med_rep['n']}` Shared Seeds, FR8 Replication Cohort)"),
            "",
            f"`results/frontier_replication/v1.4/opencode-gemini-3.5-flash` contains `{f_med_rep['n']}` replay-verified medium episodes "
            f"(`seeds {med_seeds_str}`; missing seeds in `0-29`: `{cc['flash_medium_missing_seeds_in_0_29']}`). Pairing all agents on those exact "
            f"`{f_med_rep['n']}` seeds against `data/runs/committed/v1.4/reference/solver-medium*` "
            "(with deterministic `GrokTactics` included for baseline context; on full `0-29` `grok_tactics` scores "
            f"`{_num(cc['grok_tactics_medium_0_29_row']['mean'])} +/- {_num(cc['grok_tactics_medium_0_29_row']['ci'])}`, "
            f"`{_ratio_cell(cc['grok_tactics_medium_0_29_row'])}`):",
            "",
        ]
    )
    lines.extend(_paired_table_md(cc["cross_model_medium_same_29_seeds_rows"], include_tier=False))
    hard_intro = (
        "Pairing `solver`, `gemini-4-carbon` (in-process and OpenCode over MCP), `grok_tactics` (deterministic policy), "
        "and `gemini-3.5-flash` (OpenCode over MCP) on the exact same 30 hard seeds (`0-29`):"
        if not flash_hard_held
        else "Pairing `docs/reports/gap.md`-approved primary runs (`solver`, in-process `gemini-4-carbon`, OpenCode `gemini-4-carbon` over MCP) "
        "and deterministic `grok_tactics` on the exact same 30 hard seeds (`0-29`; `opencode:google/gemini-3.5-flash` hard is held pending `docs/reports/gap.md`):"
    )
    lines.extend(
        [
            "",
            _md_heading(3, "5.2 Capability Ordering on Hard (`seeds 0-29`, `n=30` Shared Seeds)"),
            "",
            hard_intro,
            "",
        ]
    )
    lines.extend(_paired_table_md(cc["cross_model_hard_0_29_rows"], include_tier=False))
    h2h_lines = [
        "",
        _md_heading(3, "5.3 Direct Paired Model Comparison (`opencode:google/gemini-4-carbon` minus `opencode:google/gemini-3.5-flash`)"),
        "",
        "| tier | shared seeds (n) | gemini-4-carbon raw | gemini-3.5-flash raw | paired raw diff +/- 95% CI | gemini-4-carbon luck-adj. | gemini-3.5-flash luck-adj. | paired luck-adj. diff +/- 95% CI |",
        "|---|---:|---:|---:|---|---:|---:|---|",
        f"| medium | {h2h_med['n']} (`{med_seeds_str}`) | {_num(h2h_med['mean_a'])} | {_num(h2h_med['mean_b'])} | "
        f"**{_signed(h2h_med['raw_diff'])} +/- {_num(h2h_med['raw_diff_ci'])}** | {_num(h2h_med['luck_adjusted_a'])} | "
        f"{_num(h2h_med['luck_adjusted_b'])} | **{_signed(h2h_med['luck_adjusted_diff'])} +/- {_num(h2h_med['luck_adjusted_diff_ci'])}** |",
    ]
    if not flash_hard_held and h2h_hard is not None:
        h2h_lines.append(
            f"| hard | {h2h_hard['n']} (`0-29`) | {_num(h2h_hard['mean_a'])} | {_num(h2h_hard['mean_b'])} | "
            f"{_signed(h2h_hard['raw_diff'])} +/- {_num(h2h_hard['raw_diff_ci'])} | {_num(h2h_hard['luck_adjusted_a'])} | "
            f"{_num(h2h_hard['luck_adjusted_b'])} | **{_signed(h2h_hard['luck_adjusted_diff'])} +/- {_num(h2h_hard['luck_adjusted_diff_ci'])}** |"
        )
    lines.extend(h2h_lines)

    if not flash_hard_held and f_hard_prim is not None and h2h_hard is not None:
        hard_takeaway = (
            f"- On **hard**, `gemini-3.5-flash` commits on weak evidence (`mean P(accused) = {_num(f_hard_prim['p_accused'], 2)}` vs "
            f"`gemini-4-carbon`'s `{_num(c_hard_prim['p_accused'], 2)}` and `solver`'s `{_num(s_hard_prim['p_accused'], 2)}`). "
            f"Lucky low-posterior guesses lift its raw score (`{_num(f_hard_prim['mean'])}`), but posterior-expected scoring exposes a "
            f"decision-quality drop to `{_num(f_hard_prim['post_expected'])}` (`{_luck_cell(f_hard_prim, bold=False)}` of solver), trailing "
            f"`gemini-4-carbon` (`{_num(c_hard_prim['post_expected'])}`, `{_luck_cell(c_hard_prim, bold=False)}`) by "
            f"`{_signed(h2h_hard['luck_adjusted_diff'])} +/- {_num(h2h_hard['luck_adjusted_diff_ci'])}` luck-adjusted V per episode "
            f"while `gemini-4-carbon` itself remains significantly below the Bayesian reference `solver` (`{_num(s_hard_prim['post_expected'])}`)."
        )
    else:
        hard_takeaway = (
            f"- On **hard**, `OpenCode + gemini-4-carbon over MCP` scores `{_num(c_hard_prim['mean'])} +/- {_num(c_hard_prim['ci'])}` raw "
            f"(`{_ratio_cell(c_hard_prim)}`) and `{_num(c_hard_prim['post_expected'])}` luck-adjusted (`{_luck_cell(c_hard_prim, bold=False)}` of solver `{_num(s_hard_prim['post_expected'])}`), "
            f"trailing both in-process `gemini-4-carbon` (`{_num(c_ip_hard_prim['post_expected'])}`, `{_luck_cell(c_ip_hard_prim, bold=False)}`) "
            f"and deterministic `grok_tactics` (`{_num(gt_hard_30['post_expected'])}`, `{_luck_cell(gt_hard_30, bold=False)}`) while remaining "
            "significantly below the Bayesian reference `solver`."
        )

    lines.extend(
        [
            "",
            "Key takeaway on capability ordering:",
            f"- On **medium**, `gemini-4-carbon` solves `{c_med_29['n']}/{c_med_29['n']}` shared seeds at high posterior confidence "
            f"(`mean P(accused) = {_num(c_med_29['p_accused'], 2)}`, `{c_med_29['post_expected_ratio']:.0%}` luck-adjusted of solver), "
            f"outperforming both `grok_tactics` (`{gt_med_29['post_expected_ratio']:.0%}` luck-adjusted, `{1.0 - gt_med_29['accused_rate']:.0%}` abstention when scripted narrowing stalls) "
            f"and the FR8 `gemini-3.5-flash` medium replication cohort (`{f_med_rep['post_expected_ratio']:.0%}` luck-adjusted, accuracy `{f_med_rep['accuracy']:.2f}`, "
            f"`{_signed(h2h_med['raw_diff'])} +/- {_num(h2h_med['raw_diff_ci'])}` raw V/episode in favor of `gemini-4-carbon`).",
            hard_takeaway,
        ]
    )
    return "\n".join(lines) + "\n"


def default_json_path(root: Path = ROOT) -> Path:
    return DEFAULT_JSON if root == ROOT else root / "results" / "frontier_replication" / "v1.4" / "replication_summary.json"


def default_md_path(root: Path = ROOT) -> Path:
    return DEFAULT_MD if root == ROOT else root / "docs" / "reports" / "frontier_replication_v14.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compute or verify paired and luck-adjusted Canary v1.4 replication tables."
    )
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)

    if args.write and args.check:
        ap.error("pass either --write or --check, not both")
    if args.stdout and (args.write or args.check):
        ap.error("pass --stdout alone, not with --write or --check")

    root = Path(args.root).resolve()
    out_json = Path(args.out_json).resolve() if args.out_json else default_json_path(root)
    out_md = Path(args.out_md).resolve() if args.out_md else default_md_path(root)

    if args.check:
        if not out_json.is_file():
            print(f"missing {out_json}", file=sys.stderr)
            return 1
        if not out_md.is_file():
            print(f"missing {out_md}", file=sys.stderr)
            return 1
        if out_json.stat().st_size > MAX_JSON_BYTES:
            print(f"{out_json} exceeds {MAX_JSON_BYTES} bytes ({out_json.stat().st_size} bytes)", file=sys.stderr)
            return 1

    summary = compute_summary(root=root, verify_replays=True)
    json_blob = serialize_summary_json(summary)
    md_blob = render_markdown(summary)

    if args.check:
        existing_json = json.loads(out_json.read_text(encoding="utf-8"))
        fresh_json = json.loads(json_blob)
        if not approx_equal(existing_json, fresh_json, tol=1e-9):
            print(f"{out_json} differs from fresh computation beyond 1e-9 tolerance", file=sys.stderr)
            return 1
        existing_md = out_md.read_text(encoding="utf-8")
        if existing_md != md_blob:
            print(f"{out_md} differs from fresh markdown render", file=sys.stderr)
            return 1
        print(
            f"frontier replication summary and report verified "
            f"(committed={summary['replay_verification']['committed_v14']['verified']}/"
            f"{summary['replay_verification']['committed_v14']['total']}, "
            f"replication={summary['replay_verification']['replication_v14']['verified']}/"
            f"{summary['replay_verification']['replication_v14']['total']}, "
            f"union_n={len(summary['union_dedup_hard_n6']['seeds'])}, "
            f"pooled_n36={len(summary['secondary_pooled_hard_reconciliation']['n36_primary_plus_union6']['seeds'])}, "
            f"json_bytes={out_json.stat().st_size})"
        )
        return 0

    if args.stdout:
        print(md_blob, end="")
        return 0

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json_blob, encoding="utf-8")
    out_md.write_text(md_blob, encoding="utf-8")
    print(f"wrote {out_json} ({len(json_blob.encode('utf-8'))} bytes)")
    print(f"wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
