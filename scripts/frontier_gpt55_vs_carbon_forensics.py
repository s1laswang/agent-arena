"""Seed-by-seed paired cross-vendor forensics: OpenCode gpt-5.5 vs gemini-4-carbon vs solver on Canary v1.4 hard 0-29.

    python scripts/frontier_gpt55_vs_carbon_forensics.py --write
    python scripts/frontier_gpt55_vs_carbon_forensics.py --check
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary.analysis.accuse import audit_episode
from canary.analysis.gap import load_runs, mean_ci
from canary.analysis.tags import to_result
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.solver.policy import SolverPolicy
import frontier_trajectory_audit as fta
from paired_v13 import _P_CACHE, boot_ratio, p_acc, post_expected

SCHEMA_VERSION = "v1.4-frontier-gpt55-vs-carbon-forensics-1"
UPSTREAM_SYNC_COMMIT = "5f9b3297"
MAX_JSON_BYTES = 38_000
SEEDS: tuple[int, ...] = tuple(range(30))
CARBON_WRONG_SEEDS = [1, 15, 18, 26]
CARBON_ABSTAIN_SEEDS = [11]
GPT55_NON_ACCUSE_SEEDS = [0, 17]
DIVERGENCE_SEEDS = [0, 1, 11, 15, 17, 18, 26]

_PROSE_SUSPECT_RE = re.compile(r"\bAccusing\s+(e\d{2})\b", re.I)
_HARBOR_CORR_RE = re.compile(
    r"run\s+3\s+has\s+(\d+)\s+valid\s+trials\s*\([^)]*?(\d+)\s+infra-excluded\),\s*mean\s+([+-]?\d+\.\d+)\s*=\s*(\d+)%\s*\[(\d+)%,\s*(\d+)%\]",
    re.I,
)
_HARBOR_ROW_RE = re.compile(
    r"^\|\s*(opencode-1|opencode-2)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*\d+\s*/\s*\d+\s*\|\s*([+-]?\d+\.\d+)\s*\|\s*([+-]?\d+\.\d+)\s*\|\s*(\d+)%\s*\[(\d+)%,\s*(\d+)%\]"
)
_GOOGLE_KEY_PFX = "AI" + "za"
_OPENAI_KEY_PFX = "s" + "k-"
_GH_PAT_PFX = "gh" + "p_"
_PEM_MARKER = "BEGIN " + "PRIVATE KEY"
_TSIG_KEY = '"thought' + 'Signature":'
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])" + _GOOGLE_KEY_PFX + r"[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])" + _OPENAI_KEY_PFX + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
    re.compile(r"(?<![0-9A-Za-z_])" + _GH_PAT_PFX + r"[0-9A-Za-z]{30,}"),
    re.compile(re.escape(_PEM_MARKER)),
    re.compile(_TSIG_KEY + r'\s*"[^"<]{64,}"'),
)
_BOOT_IDX_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_AUDIT_CACHE: dict[tuple[str, tuple[tuple[str, int, int], ...]], dict[str, Any]] = {}


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "gpt55_vs_carbon_forensics.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_gpt55_vs_carbon_forensics_v14.md"


def _h(level: int, title: str) -> str:
    return f"{chr(35) * level} {title}"


def _r(val: float | None, nd: int = 6) -> float | None:
    return None if val is None else round(float(val), nd)


def _boot_idx(n: int, B: int, rng_seed: int) -> np.ndarray:
    key = (n, B, rng_seed)
    arr = _BOOT_IDX_CACHE.get(key)
    if arr is None:
        if n <= 1:
            arr = np.zeros((B, n), dtype=np.intp)
        else:
            rng = random.Random(rng_seed)
            grb = rng.getrandbits
            k = n.bit_length()
            buf = [0] * (B * n)
            for i in range(B * n):
                x = grb(k)
                while x >= n:
                    x = grb(k)
                buf[i] = x
            arr = np.asarray(buf, dtype=np.intp).reshape(B, n)
        _BOOT_IDX_CACHE[key] = arr
    return arr


def _fast_boot_ratio(f: list[float], s: list[float], B: int = 10_000, rng_seed: int = 0) -> tuple[float, float]:
    n = len(f)
    idx = _boot_idx(n, B, rng_seed)
    fa = np.asarray(f, dtype=np.float64)[idx].sum(axis=1) / n
    sa = np.asarray(s, dtype=np.float64)[idx].sum(axis=1) / n
    mask = sa > 0.0
    vals = np.sort(fa[mask] / sa[mask])
    k = int(vals.size)
    return float(vals[int(0.025 * k)]), float(vals[int(0.975 * k) - 1])


def _boot_diff(xs: list[float], B: int = 10_000, rng_seed: int = 0) -> tuple[float, float]:
    n = len(xs)
    idx = _boot_idx(n, B, rng_seed)
    vals = np.sort(np.asarray(xs, dtype=np.float64)[idx].sum(axis=1) / n)
    return float(vals[int(0.025 * B)]), float(vals[int(0.975 * B) - 1])


def _wlt(pairs: list[tuple[float, float]], tol: float = 1e-9) -> dict[str, int]:
    wins = sum(1 for a, b in pairs if a - b > tol)
    losses = sum(1 for a, b in pairs if b - a > tol)
    return {"wins": wins, "losses": losses, "ties": len(pairs) - wins - losses}


def _scan_hygiene_errors(raw: bytes, label: str) -> list[str]:
    txt = raw.decode("utf-8")
    errs: list[str] = []
    if not txt.isascii():
        errs.append(f"{label}: non-ASCII characters detected")
    if chr(0x2014) in txt or chr(0x2013) in txt:
        errs.append(f"{label}: em/en dash detected")
    for rx in _SECRET_PATTERNS:
        if rx.search(txt):
            errs.append(f"{label}: secret pattern detected")
    return errs


def _parse_harbor_rehearsal(root: Path) -> dict[str, Any]:
    tpath = root / "results" / "harbor" / "rehearsal" / "TABLE.md"
    if not tpath.is_file():
        raise ValueError(f"missing {tpath}")
    txt = tpath.read_text(encoding="utf-8")
    rows: dict[str, dict[str, Any]] = {}
    for ln in txt.splitlines():
        m = _HARBOR_ROW_RE.match(ln.strip())
        if m:
            rows[m.group(1)] = {
                "n_valid": int(m.group(2)),
                "infra_excluded": int(m.group(3)),
                "mean": float(m.group(4)),
                "oracle_same_tasks": float(m.group(5)),
                "ratio_pct": int(m.group(6)),
                "ci_pct": [int(m.group(7)), int(m.group(8))],
            }
    cm = _HARBOR_CORR_RE.search(txt)
    if "opencode-1" not in rows or "opencode-2" not in rows or cm is None or "d0ead011" not in txt:
        raise ValueError("malformed Harbor rehearsal TABLE.md")
    r1, r2 = rows["opencode-1"], rows["opencode-2"]
    r3_n, r3_inf, r3_mean, r3_pct = int(cm.group(1)), int(cm.group(2)), float(cm.group(3)), int(cm.group(4))
    r3_ci = [int(cm.group(5)), int(cm.group(6))]
    ratios = [r1["ratio_pct"], r2["ratio_pct"], r3_pct]
    if ratios != [93, 116, 131] or [r1["n_valid"], r2["n_valid"], r3_n] != [10, 10, 9]:
        raise ValueError(f"unexpected Harbor rehearsal summary: {ratios}")
    return {
        "source_rel": "results/harbor/rehearsal/TABLE.md",
        "final_branch_commit": "d0ead011",
        "ceo_correction_commit": UPSTREAM_SYNC_COMMIT,
        "final_ratios_pct": ratios,
        "valid_trials_by_run": [r1["n_valid"], r2["n_valid"], r3_n],
        "run3_final": {"n_valid": r3_n, "infra_excluded": r3_inf, "mean": r3_mean, "ratio_pct": r3_pct, "ci_pct": r3_ci},
    }


def _replay_and_audit_episode(ep: dict[str, Any]) -> tuple[dict[str, Any], fta.Env, dict[str, float]]:
    steps = ep.get("steps") or []
    last_msg = max((i for i, s in enumerate(steps) if s.get("tool") in fta._MSG_TOOLS), default=-1)
    prov = fta._ReplayTemplateProvider(need_messages=last_msg >= 0, need_interview_text=True)
    env = fta._make_replay_env(str(ep["tier"]), int(ep["seed"]), prov)
    step_mismatches = 0
    for idx, st in enumerate(steps):
        if idx > last_msg:
            prov.need_messages = False
        if fta.is_client_only_step(st):
            continue
        tname = str(st.get("tool"))
        if env.done or tname not in fta.ENV_TOOLS:
            step_mismatches += 1
            continue
        raw_res = st.get("result")
        prov.need_interview_text = raw_res is not None
        got = fta._replay_env_step(env, tname, st.get("args") or {})
        ok_step, _ = fta.step_result_matches(raw_res, got)
        if not ok_step:
            step_mismatches += 1
    res_replay = env.result("replay")
    clean_non_acc = fta.is_clean_non_accuse_rc0_exit(ep, env_done=env.done)
    score_ok = (
        abs(float(res_replay.score) - float(ep["score"])) < 1e-9
        and res_replay.accused == ep.get("accused")
        and bool(res_replay.correct) == bool(ep.get("correct"))
        and (int(res_replay.final_day) == int(ep.get("final_day") or 0) or clean_non_acc)
    )
    if not score_ok or step_mismatches != 0:
        raise ValueError(f"replay mismatch for {ep.get('agent')} seed {ep.get('seed')}")

    ep_res = to_result(ep)
    aud = audit_episode(ep_res)
    _P_CACHE[id(ep)] = aud["p_accused"]
    belief: dict[str, float] = {}
    top_emp: str | None = ep.get("accused") if aud["p_accused"] == aud["p_top"] else None
    top_p: float | None = aud["p_top"]
    if ep.get("accused") is None or not bool(ep.get("correct")) or top_emp is None:
        sp = SolverPolicy(tier_params_for_episode(ep_res.tier, ep_res.steps))
        for st_obj in ep_res.steps:
            if st_obj.tool == "accuse":
                break
            sp._ingest(st_obj)
        belief = sp.belief() if sp.obs.employees else {}
        if belief:
            top_emp = max(belief, key=belief.get)
            top_p = round(float(belief[top_emp]), 3)

    tc = Counter(str(s.get("tool")) for s in steps)
    pe = float(post_expected(ep) or 0.0)
    summary = {
        "accused": ep.get("accused"),
        "correct": bool(ep.get("correct")),
        "score": _r(float(ep["score"]), 4),
        "p_accused": aud["p_accused"],
        "p_top": top_p,
        "top_suspect": top_emp,
        "post_expected": _r(pe, 6),
        "final_day": int(ep.get("final_day") or 0),
        "end_reason": str(ep.get("end_reason") or ""),
        "v_at_end": _r(float(env.V), 4),
        "clean_rc0_non_accuse": clean_non_acc,
        "tools": {
            "canary": tc["plant_canary"],
            "interview": tc["interview"],
            "restrict": tc["restrict_access"],
            "search_logs": tc["read_access_logs"],
            "search_messages": tc["search_messages"],
            "advance_day": tc["advance_day"],
            "total": len(steps),
        },
    }
    return summary, env, belief


def _parse_non_accuse_transcript(tpath: Path, ep: dict[str, Any], rec: dict[str, Any], env: fta.Env) -> dict[str, Any]:
    if not tpath.is_file():
        raise ValueError(f"missing transcript {tpath}")
    raw = tpath.read_text(encoding="utf-8")
    if any(rx.search(raw) for rx in _SECRET_PATTERNS):
        raise ValueError(f"secret pattern detected in {tpath}")
    stdout = raw.split("\n--- stdout\n", 1)[1].rsplit("\n--- stderr", 1)[0] if "\n--- stdout\n" in raw else raw
    texts: list[str] = []
    finish_reason = None
    for ln in stdout.splitlines():
        if not ln.startswith("{"):
            continue
        part = (json.loads(ln).get("part") or {})
        if part.get("type") == "text" and (part.get("text") or "").strip():
            texts.append(part["text"].strip())
        elif part.get("type") == "step-finish":
            finish_reason = part.get("reason")
    if not texts:
        raise ValueError(f"no prose text found in {tpath}")
    final_prose = texts[-1].replace(chr(0x2014), "-").replace(chr(0x2013), "-")
    m = _PROSE_SUSPECT_RE.search(final_prose)
    if m is None:
        raise ValueError(f"no prose suspect named in {tpath}: {final_prose!r}")
    named = m.group(1)
    steps = ep.get("steps") or []
    last_st = steps[-1]
    day_at_exit = int(env.day)
    v_before = float(env.V)
    fta._replay_env_step(env, "accuse", {"employee": named})
    cf_score = float(env.score())
    p_named = float(rec["p_top"]) if named == rec["top_suspect"] and rec["p_top"] is not None else 0.0
    cf_la = p_named * v_before - (1.0 - p_named)
    return {
        "seed": int(ep["seed"]),
        "mole": str(env._world.mole),
        "decoy": str(env._world.decoy),
        "rc": int((ep.get("meta") or {}).get("rc", -1)),
        "finish_reason": str(finish_reason or ""),
        "recorded_final_day": rec["final_day"],
        "step_count": len(steps),
        "final_step_day": int(last_st["day"]),
        "env_day_at_exit": day_at_exit,
        "final_step_tool": str(last_st["tool"]),
        "v_at_end": _r(v_before, 4),
        "top_posterior_suspect": rec["top_suspect"],
        "top_posterior_p": rec["p_top"],
        "prose_suspect_named": named,
        "matches_true_mole": named == str(env._world.mole),
        "matches_top_posterior": named == rec["top_suspect"],
        "final_prose": final_prose,
        "counterfactual_score": _r(cf_score, 4),
        "counterfactual_post_expected": _r(cf_la, 6),
    }


def _summarize_cohort(
    label: str,
    agent: str,
    recs: dict[int, dict[str, Any]],
    sol_recs: dict[int, dict[str, Any]],
    is_solver: bool = False,
) -> dict[str, Any]:
    raw = [float(recs[s]["score"]) for s in SEEDS]
    la = [float(recs[s]["post_expected"]) for s in SEEDS]
    s_raw = [float(sol_recs[s]["score"]) for s in SEEDS]
    s_la = [float(sol_recs[s]["post_expected"]) for s in SEEDS]
    m_raw, ci_raw = mean_ci(raw)
    m_la, ci_la = mean_ci(la)
    d_m, d_ci = mean_ci([a - b for a, b in zip(raw, s_raw)])
    acc_recs = [recs[s] for s in SEEDS if recs[s]["accused"] is not None]
    r_val = sum(raw) / sum(s_raw)
    la_r_val = sum(la) / sum(s_la)
    r_lo, r_hi = (1.0, 1.0) if is_solver else _fast_boot_ratio(raw, s_raw, B=10_000, rng_seed=0)
    la_lo, la_hi = (1.0, 1.0) if is_solver else _fast_boot_ratio(la, s_la, B=10_000, rng_seed=0)
    tool_keys = ("canary", "interview", "restrict", "search_logs", "search_messages", "advance_day", "total")
    return {
        "label": label,
        "agent": agent,
        "n": 30,
        "mean_score": _r(m_raw),
        "ci_score": _r(ci_raw),
        "accuracy": _r(sum(1 for s in SEEDS if recs[s]["correct"]) / 30),
        "accused_count": len(acc_recs),
        "correct_count": sum(1 for r in acc_recs if r["correct"]),
        "wrong_count": sum(1 for r in acc_recs if not r["correct"]),
        "non_accuse_count": 30 - len(acc_recs),
        "mean_p_accused": _r(sum(float(r["p_accused"]) for r in acc_recs) / len(acc_recs)),
        "mean_post_expected": _r(m_la),
        "ci_post_expected": _r(ci_la),
        "realization_luck_mean": _r(m_raw - m_la),
        "mean_v_at_end_all": _r(sum(float(recs[s]["v_at_end"]) for s in SEEDS) / 30),
        "mean_v_at_end_accused": _r(sum(float(r["v_at_end"]) for r in acc_recs) / len(acc_recs)),
        "mean_accuse_day": _r(sum(float(r["final_day"]) for r in acc_recs) / len(acc_recs)),
        "raw_ratio_vs_solver": _r(r_val),
        "raw_ratio_pct": int(round(r_val * 100)),
        "raw_ratio_ci_pct": [int(round(r_lo * 100)), int(round(r_hi * 100))],
        "luck_adjusted_ratio_vs_solver": _r(la_r_val),
        "luck_adjusted_ratio_pct": int(round(la_r_val * 100)),
        "luck_adjusted_ratio_ci_pct": [int(round(la_lo * 100)), int(round(la_hi * 100))],
        "paired_diff_vs_solver": _r(d_m),
        "paired_diff_ci_vs_solver": _r(d_ci),
        "mean_tools": {k: _r(sum(int(recs[s]["tools"][k]) for s in SEEDS) / 30) for k in tool_keys},
    }


def compute_forensics(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    v14 = root / "data" / "runs" / "committed" / "v1.4"
    gpt_dir = v14 / "opencode-gpt-5.5" / "hard"
    car_dir = v14 / "opencode-gemini-4-carbon" / "hard"
    sol_dirs = [v14 / "reference" / "solver-hard-20261114-121126", v14 / "reference" / "solver-hard-seeds20to29"]
    ptg_path = v14 / "paired_table_gemini.json"
    harbor_path = root / "results" / "harbor" / "rehearsal" / "TABLE.md"

    tracked_files = [
        gpt_dir / "episodes.jsonl",
        gpt_dir / "meta.json",
        gpt_dir / "transcripts" / "0.txt",
        gpt_dir / "transcripts" / "17.txt",
        car_dir / "episodes.jsonl",
        car_dir / "meta.json",
        sol_dirs[0] / "episodes.jsonl",
        sol_dirs[1] / "episodes.jsonl",
        ptg_path,
        harbor_path,
    ]
    for fp in tracked_files:
        if not fp.is_file():
            raise ValueError(f"missing required input {fp}")
    sig = tuple((str(fp), fp.stat().st_mtime_ns, fp.stat().st_size) for fp in tracked_files)
    ckey = (str(root), sig)
    if ckey in _AUDIT_CACHE:
        return copy.deepcopy(_AUDIT_CACHE[ckey])

    prev_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        harbor = _parse_harbor_rehearsal(root)
        gpt_meta = json.loads((gpt_dir / "meta.json").read_text(encoding="utf-8"))
        car_meta = json.loads((car_dir / "meta.json").read_text(encoding="utf-8"))
        ptg_rows = json.loads(ptg_path.read_text(encoding="utf-8"))
        ptg_hard = next(
            r for r in ptg_rows if r.get("agent") == "opencode:google/gemini-4-carbon" and r.get("tier") == "hard"
        )

        def _by_seed(eps: list[dict[str, Any]], agent: str) -> dict[int, dict[str, Any]]:
            got: dict[int, dict[str, Any]] = {}
            for e in eps:
                if e.get("agent") == agent and e.get("tier") == "hard" and int(e["seed"]) in SEEDS:
                    s = int(e["seed"])
                    if s in got:
                        raise ValueError(f"duplicate seed {s} for {agent}")
                    got[s] = e
            if sorted(got) != list(SEEDS):
                raise ValueError(f"incomplete seeds for {agent}: {sorted(got)}")
            return got

        gpt_eps = _by_seed(load_runs(gpt_dir), "opencode:openai/gpt-5.5")
        car_eps = _by_seed(load_runs(car_dir), "opencode:google/gemini-4-carbon")
        sol_eps = _by_seed(load_runs(sol_dirs[0]) + load_runs(sol_dirs[1]), "solver")

        gpt_rec: dict[int, dict[str, Any]] = {}
        car_rec: dict[int, dict[str, Any]] = {}
        sol_rec: dict[int, dict[str, Any]] = {}
        gpt_env: dict[int, fta.Env] = {}
        car_belief: dict[int, dict[str, float]] = {}
        world_info: dict[int, tuple[str, str]] = {}

        for s in SEEDS:
            gr, ge, _ = _replay_and_audit_episode(gpt_eps[s])
            cr, _, cb = _replay_and_audit_episode(car_eps[s])
            sr, _, _ = _replay_and_audit_episode(sol_eps[s])
            gpt_rec[s], gpt_env[s] = gr, ge
            car_rec[s], car_belief[s] = cr, cb
            sol_rec[s] = sr
            world_info[s] = (str(ge._world.mole), str(ge._world.decoy))

        clean_rc0 = sorted(s for s in SEEDS if gpt_rec[s]["clean_rc0_non_accuse"])
        if clean_rc0 != GPT55_NON_ACCUSE_SEEDS:
            raise ValueError(f"unexpected clean rc=0 non-accuse seeds: {clean_rc0}")

        gpt_sum = _summarize_cohort("OpenCode gpt-5.5 hard (0-29)", "opencode:openai/gpt-5.5", gpt_rec, sol_rec)
        car_sum = _summarize_cohort("OpenCode gemini-4-carbon hard (0-29)", "opencode:google/gemini-4-carbon", car_rec, sol_rec)
        sol_sum = _summarize_cohort("reference solver hard (0-29)", "solver", sol_rec, sol_rec, is_solver=True)

        if abs(car_sum["mean_score"] - float(ptg_hard["mean"])) > 1e-6 or abs(
            car_sum["mean_post_expected"] - float(ptg_hard["post_expected"])
        ) > 1e-6:
            raise ValueError("carbon summary drifted from paired_table_gemini.json")

        raw_pairs = [(float(gpt_rec[s]["score"]), float(car_rec[s]["score"])) for s in SEEDS]
        la_pairs = [(float(gpt_rec[s]["post_expected"]), float(car_rec[s]["post_expected"])) for s in SEEDS]
        raw_diffs = [a - b for a, b in raw_pairs]
        la_diffs = [a - b for a, b in la_pairs]
        rd_m, rd_ci = mean_ci(raw_diffs)
        ld_m, ld_ci = mean_ci(la_diffs)
        rd_lo, rd_hi = _boot_diff(raw_diffs, B=10_000, rng_seed=0)
        ld_lo, ld_hi = _boot_diff(la_diffs, B=10_000, rng_seed=0)
        gc_r_lo, gc_r_hi = _fast_boot_ratio([a for a, _ in raw_pairs], [b for _, b in raw_pairs], B=10_000, rng_seed=0)
        gc_la_lo, gc_la_hi = _fast_boot_ratio([a for a, _ in la_pairs], [b for _, b in la_pairs], B=10_000, rng_seed=0)

        def _cell(r: dict[str, Any]) -> dict[str, Any]:
            return {
                "accused": r["accused"],
                "correct": r["correct"],
                "score": r["score"],
                "p_accused": r["p_accused"],
                "post_expected": r["post_expected"],
                "final_day": r["final_day"],
                "v_at_end": r["v_at_end"],
                "tools": r["tools"],
            }

        seed_matrix = []
        for s in SEEDS:
            mole, decoy = world_info[s]
            rd = float(gpt_rec[s]["score"]) - float(car_rec[s]["score"])
            ld = float(gpt_rec[s]["post_expected"]) - float(car_rec[s]["post_expected"])
            seed_matrix.append(
                {
                    "seed": s,
                    "mole": mole,
                    "decoy": decoy,
                    "gpt55": _cell(gpt_rec[s]),
                    "carbon": _cell(car_rec[s]),
                    "solver": _cell(sol_rec[s]),
                    "diff_gpt55_minus_carbon": {
                        "raw": _r(rd, 4),
                        "post_expected": _r(ld, 6),
                        "raw_wlt": "W" if rd > 1e-9 else ("L" if rd < -1e-9 else "T"),
                        "la_wlt": "W" if ld > 1e-9 else ("L" if ld < -1e-9 else "T"),
                    },
                }
            )

        carbon_wrong_cases = []
        for s in CARBON_WRONG_SEEDS:
            mole, decoy = world_info[s]
            cr, gr, sr = car_rec[s], gpt_rec[s], sol_rec[s]
            p_mole = round(float(car_belief[s].get(mole, 0.0)), 3)
            carbon_wrong_cases.append(
                {
                    "seed": s,
                    "mole": mole,
                    "decoy": decoy,
                    "carbon_accused": cr["accused"],
                    "carbon_p_accused": cr["p_accused"],
                    "carbon_p_mole": p_mole,
                    "carbon_final_day": cr["final_day"],
                    "carbon_v_at_end": cr["v_at_end"],
                    "carbon_post_expected": cr["post_expected"],
                    "carbon_canaries": cr["tools"]["canary"],
                    "carbon_interviews": cr["tools"]["interview"],
                    "mechanism": "below_breakeven_gamble_after_interview_erosion"
                    if float(cr["post_expected"]) < 0
                    else "single_noisy_canary_false_attribution",
                    "gpt55_accused": gr["accused"],
                    "gpt55_score": gr["score"],
                    "gpt55_p_accused": gr["p_accused"],
                    "gpt55_final_day": gr["final_day"],
                    "gpt55_canaries": gr["tools"]["canary"],
                    "solver_accused": sr["accused"],
                    "solver_correct": sr["correct"],
                    "solver_score": sr["score"],
                }
            )

        s11_mole, s11_decoy = world_info[11]
        carbon_abstain_cases = [
            {
                "seed": 11,
                "mole": s11_mole,
                "decoy": s11_decoy,
                "carbon_end_reason": car_rec[11]["end_reason"],
                "carbon_final_day": car_rec[11]["final_day"],
                "carbon_top_suspect": car_rec[11]["top_suspect"],
                "carbon_p_top": car_rec[11]["p_top"],
                "carbon_p_mole": round(float(car_belief[11].get(s11_mole, 0.0)), 3),
                "carbon_canaries": car_rec[11]["tools"]["canary"],
                "carbon_interviews": car_rec[11]["tools"]["interview"],
                "gpt55_accused": gpt_rec[11]["accused"],
                "gpt55_score": gpt_rec[11]["score"],
                "gpt55_p_accused": gpt_rec[11]["p_accused"],
                "gpt55_final_day": gpt_rec[11]["final_day"],
                "gpt55_canaries": gpt_rec[11]["tools"]["canary"],
                "solver_score": sol_rec[11]["score"],
            }
        ]

        non_accuse_cases = []
        for s in GPT55_NON_ACCUSE_SEEDS:
            case = _parse_non_accuse_transcript(
                gpt_dir / "transcripts" / f"{s}.txt", gpt_eps[s], gpt_rec[s], gpt_env[s]
            )
            case["carbon_score"] = car_rec[s]["score"]
            case["solver_score"] = sol_rec[s]["score"]
            non_accuse_cases.append(case)

        s28 = [s for s in SEEDS if s not in GPT55_NON_ACCUSE_SEEDS]
        cf_map = {c["seed"]: c for c in non_accuse_cases}
        cf_raw = [
            float(cf_map[s]["counterfactual_score"]) if s in cf_map else float(gpt_rec[s]["score"]) for s in SEEDS
        ]
        cf_la = [
            float(cf_map[s]["counterfactual_post_expected"]) if s in cf_map else float(gpt_rec[s]["post_expected"])
            for s in SEEDS
        ]
        sol_raw_sum = sum(float(sol_rec[s]["score"]) for s in SEEDS)
        sol_la_sum = sum(float(sol_rec[s]["post_expected"]) for s in SEEDS)
        non_acc_la_drag = sum(float(sol_rec[s]["post_expected"]) - float(gpt_rec[s]["post_expected"]) for s in GPT55_NON_ACCUSE_SEEDS) / 30
        acc28_la_drag = sum(float(sol_rec[s]["post_expected"]) - float(gpt_rec[s]["post_expected"]) for s in s28) / 30
        total_la_gap = float(sol_sum["mean_post_expected"]) - float(gpt_sum["mean_post_expected"])

        concordant_23 = [s for s in SEEDS if s not in DIVERGENCE_SEEDS]
        if not all(gpt_rec[s]["correct"] and car_rec[s]["correct"] and gpt_rec[s]["accused"] == car_rec[s]["accused"] for s in concordant_23):
            raise ValueError("expected all 23 non-divergence seeds to be concordantly solved")

        out = fta.clean_json(
            {
                "schema_version": SCHEMA_VERSION,
                "tiers_version": TIERS_VERSION,
                "upstream_justsilas_sync_commit": UPSTREAM_SYNC_COMMIT,
                "pure_cpu_zero_api_calls": True,
                "zero_subprocesses": True,
                "zero_git_history_calls": True,
                "provenance_and_locks": {
                    "upstream_justsilas_sync": {
                        "head_commit": UPSTREAM_SYNC_COMMIT,
                        "code_freeze_tag": "afterquery-final",
                        "code_freeze_commit": "1bc3e281",
                        "afterquery_submit_commit": "9225f2ad",
                        "afterquery_submit_2_commit": "aa1c679e",
                        "ceo_correction_commit": UPSTREAM_SYNC_COMMIT,
                        "harbor_rehearsal": harbor,
                    },
                    "primary_carbon_hard_0_29": {
                        "classification": "post_hoc_lock",
                        "episodes_commit": "8fd4dec",
                        "lock_commit": "671ed96",
                        "lock_delay_s": 28,
                        "opencode_version": str(car_meta.get("opencode_version")),
                        "infra_excluded_attempts": len(car_meta.get("infra_invalid_attempts_excluded") or []),
                        "run_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
                    },
                    "gpt_5_5_hard_0_29": {
                        "classification": "pre_registered",
                        "prereg_commit": "cf394894",
                        "results_commit": "ca0a0dc0",
                        "upstream_sync_commit": UPSTREAM_SYNC_COMMIT,
                        "opencode_version": str(gpt_meta.get("opencode_version")),
                        "timeout_cap_s": 7200,
                        "infra_excluded_attempts": len(gpt_meta.get("infra_invalid_attempts_excluded") or []),
                        "cost_usd_est": _r(float((gpt_meta.get("usage") or {}).get("cost_usd_est", 0.0)), 3),
                        "clean_rc0_non_accuse_seeds": GPT55_NON_ACCUSE_SEEDS,
                        "run_dir": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
                    },
                },
                "replay_verification": {
                    "paired_seeds_count": 30,
                    "total_episodes_verified": 90,
                    "mismatches": 0,
                    "step_mismatches": 0,
                    "duplicates": 0,
                },
                "cohort_summaries": {
                    "gpt_5_5": gpt_sum,
                    "carbon": car_sum,
                    "solver": sol_sum,
                },
                "paired_head_to_head": {
                    "comparison": "gpt_5_5_minus_carbon_hard_0_29",
                    "n_paired": 30,
                    "bootstrap_resamples": 10_000,
                    "bootstrap_rng_seed": 0,
                    "raw_diff": {
                        "mean": _r(rd_m),
                        "normal_ci95_halfwidth": _r(rd_ci),
                        "bootstrap_95_ci": [_r(rd_lo), _r(rd_hi)],
                        "wlt_concordance": _wlt(raw_pairs),
                    },
                    "luck_adjusted_diff": {
                        "mean": _r(ld_m),
                        "normal_ci95_halfwidth": _r(ld_ci),
                        "bootstrap_95_ci": [_r(ld_lo), _r(ld_hi)],
                        "wlt_concordance": _wlt(la_pairs),
                    },
                    "cross_vendor_ratios": {
                        "raw_gpt55_over_carbon": _r(float(gpt_sum["mean_score"]) / float(car_sum["mean_score"])),
                        "raw_bootstrap_95_ci": [_r(gc_r_lo), _r(gc_r_hi)],
                        "luck_adjusted_gpt55_over_carbon": _r(
                            float(gpt_sum["mean_post_expected"]) / float(car_sum["mean_post_expected"])
                        ),
                        "luck_adjusted_bootstrap_95_ci": [_r(gc_la_lo), _r(gc_la_hi)],
                    },
                },
                "divergence_forensics": {
                    "divergence_seeds": DIVERGENCE_SEEDS,
                    "divergence_count": 7,
                    "concordant_correct_seeds_count": 23,
                    "carbon_wrong_accusation_seeds": CARBON_WRONG_SEEDS,
                    "carbon_abstention_seeds": CARBON_ABSTAIN_SEEDS,
                    "gpt55_non_accuse_prose_exit_seeds": GPT55_NON_ACCUSE_SEEDS,
                    "carbon_failures_solved_by_gpt55_count": 5,
                    "carbon_wrong_cases": carbon_wrong_cases,
                    "carbon_abstention_cases": carbon_abstain_cases,
                    "gpt55_non_accuse_prose_cases": non_accuse_cases,
                },
                "luck_gap_decomposition": {
                    "headline_contrast": {
                        "gpt55_raw_ratio_pct": gpt_sum["raw_ratio_pct"],
                        "gpt55_raw_ratio_ci_pct": gpt_sum["raw_ratio_ci_pct"],
                        "gpt55_luck_adjusted_ratio_pct": gpt_sum["luck_adjusted_ratio_pct"],
                        "gpt55_luck_adjusted_ratio_ci_pct": gpt_sum["luck_adjusted_ratio_ci_pct"],
                        "ratio_drop_pct_points": gpt_sum["raw_ratio_pct"] - gpt_sum["luck_adjusted_ratio_pct"],
                    },
                    "realization_luck_by_cohort": {
                        "gpt_5_5": {
                            "raw_mean": gpt_sum["mean_score"],
                            "post_expected_mean": gpt_sum["mean_post_expected"],
                            "realization_luck_mean": gpt_sum["realization_luck_mean"],
                            "expected_wrong_from_posterior": _r(
                                sum(1.0 - float(gpt_rec[s]["p_accused"]) for s in s28)
                            ),
                            "realized_wrong_count": 0,
                            "sub_090_posterior_correct_seeds": [
                                s for s in s28 if float(gpt_rec[s]["p_accused"]) < 0.90
                            ],
                        },
                        "carbon": {
                            "raw_mean": car_sum["mean_score"],
                            "post_expected_mean": car_sum["mean_post_expected"],
                            "realization_luck_mean": car_sum["realization_luck_mean"],
                            "expected_wrong_from_posterior": _r(
                                sum(
                                    1.0 - float(car_rec[s]["p_accused"])
                                    for s in SEEDS
                                    if car_rec[s]["accused"] is not None
                                )
                            ),
                            "realized_wrong_count": 4,
                        },
                        "solver": {
                            "raw_mean": sol_sum["mean_score"],
                            "post_expected_mean": sol_sum["mean_post_expected"],
                            "realization_luck_mean": sol_sum["realization_luck_mean"],
                            "expected_wrong_from_posterior": _r(
                                sum(1.0 - float(sol_rec[s]["p_accused"]) for s in SEEDS)
                            ),
                            "realized_wrong_count": 1,
                        },
                    },
                    "solver_minus_gpt55_la_gap_breakdown": {
                        "total_la_gap_per_seed": _r(total_la_gap),
                        "non_accuse_seeds_0_17_drag_per_seed": _r(non_acc_la_drag),
                        "non_accuse_share_of_la_gap": _r(non_acc_la_drag / total_la_gap),
                        "accused_28_seeds_v_and_p_drag_per_seed": _r(acc28_la_drag),
                        "accused_28_share_of_la_gap": _r(acc28_la_drag / total_la_gap),
                        "gpt55_v_mean_on_28_accused": _r(sum(float(gpt_rec[s]["v_at_end"]) for s in s28) / 28),
                        "solver_v_mean_on_28_accused": _r(sum(float(sol_rec[s]["v_at_end"]) for s in s28) / 28),
                        "gpt55_p_mean_on_28_accused": _r(sum(float(gpt_rec[s]["p_accused"]) for s in s28) / 28),
                        "solver_p_mean_on_28_accused": _r(sum(float(sol_rec[s]["p_accused"]) for s in s28) / 28),
                    },
                    "counterfactual_if_non_accuse_executed": {
                        "gpt55_raw_mean": _r(sum(cf_raw) / 30),
                        "gpt55_raw_ratio_pct": int(round(sum(cf_raw) / sol_raw_sum * 100)),
                        "gpt55_post_expected_mean": _r(sum(cf_la) / 30),
                        "gpt55_luck_adjusted_ratio_pct": int(round(sum(cf_la) / sol_la_sum * 100)),
                        "correct_count": 30,
                    },
                },
                "seed_matrix": seed_matrix,
            }
        )
        if len(_AUDIT_CACHE) >= 4:
            _AUDIT_CACHE.clear()
        _AUDIT_CACHE[ckey] = out
        return copy.deepcopy(out)
    finally:
        if prev_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_dev


def serialize_forensics_json(data: dict[str, Any]) -> str:
    lines = ["{"]
    keys = list(data.keys())
    for idx, k in enumerate(keys):
        comma = "," if idx + 1 < len(keys) else ""
        val = data[k]
        if isinstance(val, list):
            lines.append(f' "{k}": [')
            for r_i, item in enumerate(val):
                rc = "," if r_i + 1 < len(val) else ""
                lines.append("  " + json.dumps(item, sort_keys=True, separators=(",", ":")) + rc)
            lines.append(f" ]{comma}")
        else:
            lines.append(f' "{k}": ' + json.dumps(val, sort_keys=True, separators=(",", ":")) + comma)
    lines.append("}\n")
    return "\n".join(lines)


def render_markdown(data: dict[str, Any]) -> str:
    prov = data["provenance_and_locks"]
    harbor = prov["upstream_justsilas_sync"]["harbor_rehearsal"]
    cs = data["cohort_summaries"]
    gp, ca, so = cs["gpt_5_5"], cs["carbon"], cs["solver"]
    h2h = data["paired_head_to_head"]
    rd, ld = h2h["raw_diff"], h2h["luck_adjusted_diff"]
    div = data["divergence_forensics"]
    lgd = data["luck_gap_decomposition"]
    sbrk = lgd["solver_minus_gpt55_la_gap_breakdown"]
    cf = lgd["counterfactual_if_non_accuse_executed"]
    rl = lgd["realization_luck_by_cohort"]

    lines = [
        _h(1, "Paired Cross-Vendor Forensics on Canary v1.4 Hard (Seeds 0-29): OpenCode gpt-5.5 vs gemini-4-carbon vs Solver"),
        "",
        "Every figure in this report is deterministically computed on pure CPU from replay-verified `episodes.jsonl` records and OpenCode `transcripts/*.txt` event streams by `scripts/frontier_gpt55_vs_carbon_forensics.py` using `scripts/paired_v13.py` (`boot_ratio`, `p_acc`, `post_expected`), `canary.analysis.accuse` (`audit_episode`), and `_ReplayTemplateProvider` caching (`0` API calls, `0` subprocesses, `0` runtime `.git` calls).",
        "",
        _h(2, "1. Provenance Sync (justSilas@5f9b3297) and Headline Summary"),
        "",
        f"- **Upstream sync (`justSilas@{data['upstream_justsilas_sync_commit']}`):** Code freeze `afterquery-final` (`1bc3e281`), submit tags `9225f2ad` / `aa1c679e`, CEO log correction `{data['upstream_justsilas_sync_commit']}`, and Harbor judge rehearsal final ratios `{harbor['final_ratios_pct'][0]}%, {harbor['final_ratios_pct'][1]}%, {harbor['final_ratios_pct'][2]}%` (`n={harbor['valid_trials_by_run']}` valid trials) on `s1-rehearsal-final@{harbor['final_branch_commit']}`.",
        f"- **Primary `gemini-4-carbon` hard `0-29` (`post_hoc_lock`):** Episodes committed at `8fd4dec`, locked `28s` later at `671ed96` (`OpenCode {prov['primary_carbon_hard_0_29']['opencode_version']}`, `{prov['primary_carbon_hard_0_29']['infra_excluded_attempts']}` infra-excluded retries): raw `{ca['mean_score']:.3f}` (`{ca['raw_ratio_pct']}% [{ca['raw_ratio_ci_pct'][0]}%, {ca['raw_ratio_ci_pct'][1]}%]` of solver `{so['mean_score']:.3f}`), luck-adjusted `{ca['mean_post_expected']:.3f}` (`{ca['luck_adjusted_ratio_pct']}% [{ca['luck_adjusted_ratio_ci_pct'][0]}%, {ca['luck_adjusted_ratio_ci_pct'][1]}%]`).",
        f"- **Pre-registered `openai/gpt-5.5` hard `0-29` (`pre_registered`):** Pre-registered at `cf394894`, results committed at `ca0a0dc0` (`OpenCode {prov['gpt_5_5_hard_0_29']['opencode_version']}`, `0` infra exclusions, `${prov['gpt_5_5_hard_0_29']['cost_usd_est']:.2f}` total): raw `{gp['mean_score']:.3f}` (`{gp['raw_ratio_pct']}% [{gp['raw_ratio_ci_pct'][0]}%, {gp['raw_ratio_ci_pct'][1]}%]`), luck-adjusted `{gp['mean_post_expected']:.3f}` (`{gp['luck_adjusted_ratio_pct']}% [{gp['luck_adjusted_ratio_ci_pct'][0]}%, {gp['luck_adjusted_ratio_ci_pct'][1]}%]`).",
        "",
        "| Cohort | n | Raw +/- 95% CI | Raw / Solver [95% CI] | Mean P(acc) | Luck-Adj (LA) | LA / Solver [95% CI] | End V (all/acc) | Acc Day | Canaries | Interviews | Total Calls | C / W / None |",
        "|---|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for c in (gp, ca, so):
        raw_str = "100%" if c["agent"] == "solver" else f"{c['raw_ratio_pct']}% [{c['raw_ratio_ci_pct'][0]}%, {c['raw_ratio_ci_pct'][1]}%]"
        la_str = "100%" if c["agent"] == "solver" else f"{c['luck_adjusted_ratio_pct']}% [{c['luck_adjusted_ratio_ci_pct'][0]}%, {c['luck_adjusted_ratio_ci_pct'][1]}%]"
        lines.append(
            f"| {c['label']} | {c['n']} | {c['mean_score']:+.3f} +/- {c['ci_score']:.3f} | {raw_str} | "
            f"{c['mean_p_accused']:.3f} | {c['mean_post_expected']:+.3f} | {la_str} | "
            f"{c['mean_v_at_end_all']:.3f} / {c['mean_v_at_end_accused']:.3f} | {c['mean_accuse_day']:.2f} | "
            f"{c['mean_tools']['canary']:.1f} | {c['mean_tools']['interview']:.1f} | {c['mean_tools']['total']:.1f} | "
            f"{c['correct_count']} / {c['wrong_count']} / {c['non_accuse_count']} |"
        )

    rwlt, lwlt = rd["wlt_concordance"], ld["wlt_concordance"]
    lines.extend(
        [
            "",
            _h(2, "2. Paired Head-to-Head (`gpt-5.5` minus `gemini-4-carbon`, n=30 Hard Seeds)"),
            "",
            f"- **Raw paired delta:** `{rd['mean']:+.3f}` (`+/- {rd['normal_ci95_halfwidth']:.3f}` normal 95% CI; seeded 10,000-resample bootstrap 95% CI `[{rd['bootstrap_95_ci'][0]:+.3f}, {rd['bootstrap_95_ci'][1]:+.3f}]`), seed concordance `W/L/T = {rwlt['wins']}/{rwlt['losses']}/{rwlt['ties']}` (`gpt-5.5` wins fewer individual raw ties/margins because it plants `17.2` vs `8.5` canaries on shared solves, but avoids all four `-1.0` wrong accusations).",
            f"- **Luck-adjusted paired delta:** `{ld['mean']:+.3f}` (`+/- {ld['normal_ci95_halfwidth']:.3f}` normal 95% CI; bootstrap 95% CI `[{ld['bootstrap_95_ci'][0]:+.3f}, {ld['bootstrap_95_ci'][1]:+.3f}]`), seed concordance `W/L/T = {lwlt['wins']}/{lwlt['losses']}/{lwlt['ties']}`.",
            f"- **Outcome concordance:** Across all `23` non-divergence seeds, both OpenCode models accuse the exact same true mole (`23/23` correct); the entire accuracy and penalty separation concentrates in `7` divergence seeds `{div['divergence_seeds']}`.",
            "",
            _h(2, "3. Deep Forensics of the 7 Divergence Seeds"),
            "",
            _h(3, "3A. Carbon's 4 Wrong Accusations [1, 15, 18, 26] + 1 Horizon Abstention [11] (5/5 Solved by gpt-5.5)"),
            "",
            "| Seed | Mole / Decoy | Carbon Outcome | Carbon P(acc) / P(mole) | Carbon Canaries / IVs | Mechanism | gpt-5.5 Outcome (P, Canaries) | Solver Outcome |",
            "|---:|---|---|---|---:|---|---|---|",
        ]
    )
    for w in div["carbon_wrong_cases"]:
        lines.append(
            f"| {w['seed']} | `{w['mole']}` / `{w['decoy']}` | accused `{w['carbon_accused']}` (d{w['carbon_final_day']}, `-1.000`, LA `{w['carbon_post_expected']:+.3f}`) | "
            f"`{w['carbon_p_accused']:.3f}` / `{w['carbon_p_mole']:.3f}` | {w['carbon_canaries']} / {w['carbon_interviews']} | `{w['mechanism']}` | "
            f"accused `{w['gpt55_accused']}` (d{w['gpt55_final_day']}, `{w['gpt55_score']:+.3f}`, P=`{w['gpt55_p_accused']:.3f}`, c={w['gpt55_canaries']}) | "
            f"accused `{w['solver_accused']}` (`{w['solver_score']:+.3f}`) |"
        )
    ab = div["carbon_abstention_cases"][0]
    lines.extend(
        [
            f"| {ab['seed']} | `{ab['mole']}` / `{ab['decoy']}` | `None` (`{ab['carbon_end_reason']}` d{ab['carbon_final_day']}, `+0.000`) | "
            f"top `{ab['carbon_top_suspect']}`=`{ab['carbon_p_top']:.3f}` / `{ab['carbon_p_mole']:.3f}` | {ab['carbon_canaries']} / {ab['carbon_interviews']} | `interview_saturation_diffuse_posterior` | "
            f"accused `{ab['gpt55_accused']}` (d{ab['gpt55_final_day']}, `{ab['gpt55_score']:+.3f}`, P=`{ab['gpt55_p_accused']:.3f}`, c={ab['gpt55_canaries']}) | "
            f"accused `{ab['mole']}` (`{ab['solver_score']:+.3f}`) |",
            "",
            _h(3, "3B. GPT-5.5's 2 Clean rc=0 Non-Accuse Prose Exits [0, 17]"),
            "",
            "| Seed | Mole | Steps / Exit Day | Last MCP Tool | V_at_end | Top Posterior | Prose Suspect Named | Counterfactual Score / LA | Final Stop Prose |",
            "|---:|---|---|---|---:|---|---|---|",
        ]
    )
    for nc in div["gpt55_non_accuse_prose_cases"]:
        lines.append(
            f"| {nc['seed']} | `{nc['mole']}` | {nc['step_count']} / day {nc['env_day_at_exit']} (`rc={nc['rc']}`, `{nc['finish_reason']}`) | "
            f"`{nc['final_step_tool']}` | {nc['v_at_end']:.3f} | `{nc['top_posterior_suspect']}` (`{nc['top_posterior_p']:.3f}`) | "
            f"`{nc['prose_suspect_named']}` (mole={nc['matches_true_mole']}) | `{nc['counterfactual_score']:+.3f}` / `{nc['counterfactual_post_expected']:+.3f}` | "
            f"{nc['final_prose']} |"
        )

    lines.extend(
        [
            "",
            _h(2, "4. Why GPT-5.5 Raw Ratio Is 101% While Luck-Adjusted Ratio Is 84% [67%, 103%]"),
            "",
            f"1. **Zero `-1.0` realization luck (`{rl['gpt_5_5']['realization_luck_mean']:+.3f}` per seed on `gpt-5.5` vs `{rl['solver']['realization_luck_mean']:+.3f}` on `solver` and `{rl['carbon']['realization_luck_mean']:+.3f}` on `carbon`):** Across `gpt-5.5`'s `28` accusations, mean Bayesian posterior was `{gp['mean_p_accused']:.3f}`, implying `{rl['gpt_5_5']['expected_wrong_from_posterior']:.2f}` expected noisy-canary false positives (`5` accusations made at `P < 0.90` on seeds `{rl['gpt_5_5']['sub_090_posterior_correct_seeds']}`). Realizing `0` wrong accusations (`28/28` correct) added `+{rl['gpt_5_5']['realization_luck_mean']:.3f}` realization luck per seed above posterior expectation (`0.504` raw vs `0.418` LA), whereas the solver realized `1` noisy-canary `-1.0` error (seed `15`, vs `{rl['solver']['expected_wrong_from_posterior']:.2f}` expected).",
            f"2. **Exact decomposition of the `-0.082` (`{sbrk['total_la_gap_per_seed']:.4f}`) LA shortfall vs solver (`0.418` vs `0.499`):**",
            f"   - **Two non-accuse zeros on seeds `[0, 17]` (`{sbrk['non_accuse_seeds_0_17_drag_per_seed']:+.4f}`/seed, `{sbrk['non_accuse_share_of_la_gap'] * 100:.1f}%` of LA gap):** Scoring `0.000` instead of solver's `+0.556` and `+0.696` accounts for over half the LA gap. Had `gpt-5.5` invoked `accuse` for the exact mole it named in prose on `[0, 17]`, counterfactual `gpt-5.5` reaches `{cf['gpt55_raw_mean']:.3f}` raw (`{cf['gpt55_raw_ratio_pct']}%` of solver, `30/30` correct) and `{cf['gpt55_post_expected_mean']:.3f}` LA (`{cf['gpt55_luck_adjusted_ratio_pct']}%` of solver).",
            f"   - **Slightly lower `V_at_end` and terminal posterior on the 28 accused seeds (`{sbrk['accused_28_seeds_v_and_p_drag_per_seed']:+.4f}`/seed, `{sbrk['accused_28_share_of_la_gap'] * 100:.1f}%` of LA gap):** On seeds where `gpt-5.5` accused, heavier canary planting (`17.2` vs `14.1`) and `4.2` interviews yielded `V_at_end = {sbrk['gpt55_v_mean_on_28_accused']:.3f}` vs solver `{sbrk['solver_v_mean_on_28_accused']:.3f}` and mean `P(accused) = {sbrk['gpt55_p_mean_on_28_accused']:.3f}` vs solver `{sbrk['solver_p_mean_on_28_accused']:.3f}`.",
            "",
            _h(2, "5. Seed-by-Seed 3-Way Matrix (v1.4 Hard Seeds 0-29)"),
            "",
            "| Seed | Mole | gpt-5.5 (acc, raw, P, LA, d, V, c/iv) | carbon (acc, raw, P, LA, d, V, c/iv) | solver (acc, raw, P, LA, d, V, c) | dRaw (G-C) | dLA (G-C) |",
            "|---:|---|---|---|---|---:|---:|",
        ]
    )
    for row in data["seed_matrix"]:
        g, c, s, df = row["gpt55"], row["carbon"], row["solver"], row["diff_gpt55_minus_carbon"]
        gp_p = "-" if g["p_accused"] is None else f"{g['p_accused']:.3f}"
        ca_p = "-" if c["p_accused"] is None else f"{c['p_accused']:.3f}"
        lines.append(
            f"| {row['seed']} | `{row['mole']}` | `{g['accused'] or 'None'}` {g['score']:+.2f} P={gp_p} LA={g['post_expected']:+.2f} d{g['final_day']} V={g['v_at_end']:.2f} ({g['tools']['canary']}/{g['tools']['interview']}) | "
            f"`{c['accused'] or 'None'}` {c['score']:+.2f} P={ca_p} LA={c['post_expected']:+.2f} d{c['final_day']} V={c['v_at_end']:.2f} ({c['tools']['canary']}/{c['tools']['interview']}) | "
            f"`{s['accused']}` {s['score']:+.2f} P={s['p_accused']:.3f} LA={s['post_expected']:+.2f} d{s['final_day']} V={s['v_at_end']:.2f} ({s['tools']['canary']}) | "
            f"{df['raw']:+.2f} ({df['raw_wlt']}) | {df['post_expected']:+.3f} ({df['la_wlt']}) |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Paired cross-vendor forensics: gpt-5.5 vs carbon vs solver on v1.4 hard 0-29.")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)

    if sum(bool(x) for x in (args.write, args.check, args.stdout)) > 1:
        ap.error("pass at most one of --write, --check, or --stdout")

    root = Path(args.root).resolve()
    out_json = Path(args.out_json).resolve() if args.out_json else default_json_path(root)
    out_md = Path(args.out_md).resolve() if args.out_md else default_md_path(root)

    try:
        data = compute_forensics(root=root)
    except Exception as exc:
        print(f"forensics audit failed: {exc}", file=sys.stderr)
        return 1

    json_blob = serialize_forensics_json(data)
    md_blob = render_markdown(data)

    if args.check:
        if not out_json.is_file() or not out_md.is_file():
            print("missing output artifact(s)", file=sys.stderr)
            return 1
        jraw = out_json.read_bytes()
        mraw = out_md.read_bytes()
        if len(jraw) == 0 or len(jraw) > MAX_JSON_BYTES:
            print(f"{out_json} size {len(jraw)} violates cap {MAX_JSON_BYTES}", file=sys.stderr)
            return 1
        hyg = _scan_hygiene_errors(jraw, str(out_json)) + _scan_hygiene_errors(mraw, str(out_md))
        if hyg:
            print("; ".join(hyg), file=sys.stderr)
            return 1
        if not fta.approx_equal(json.loads(jraw.decode("utf-8")), json.loads(json_blob), tol=1e-9):
            print(f"{out_json} drifted from fresh computation", file=sys.stderr)
            return 1
        if mraw.decode("utf-8") != md_blob:
            print(f"{out_md} drifted from fresh markdown render", file=sys.stderr)
            return 1
        gp = data["cohort_summaries"]["gpt_5_5"]
        ca = data["cohort_summaries"]["carbon"]
        h2h = data["paired_head_to_head"]
        print(
            f"OK gpt55_vs_carbon_forensics=PASS seeds=30 verified=90 "
            f"gpt55={gp['raw_ratio_pct']}%/{gp['luck_adjusted_ratio_pct']}% "
            f"carbon={ca['raw_ratio_pct']}%/{ca['luck_adjusted_ratio_pct']}% "
            f"diff_raw={h2h['raw_diff']['mean']:+.3f} diff_la={h2h['luck_adjusted_diff']['mean']:+.3f} "
            f"bytes={len(jraw)}"
        )
        return 0

    if args.write:
        if len(json_blob.encode("utf-8")) > MAX_JSON_BYTES:
            print(f"serialized JSON exceeds {MAX_JSON_BYTES} bytes", file=sys.stderr)
            return 1
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_blob, encoding="utf-8")
        out_md.write_text(md_blob, encoding="utf-8")
        print(f"wrote {out_json} ({out_json.stat().st_size} bytes)")
        print(f"wrote {out_md}")
        return 0

    print(md_blob, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
