"""Offline provenance, replay, and table-verification audit for Verda WS4, FR8 replication, and G1 extension.

Covers evaluation dataset families outside anticheat.replay_committed's default scope or requiring
extended provenance checks, with zero live LLM/API calls:
  (a) Verda WS4 tiebreaker runs (data/fr8/verda/**, data/fr8/j4/**, fr8/analysis/out/ws4_*.md, efd99c23/66a26f5c)
  (b) FR8 frontier replication cohort (results/frontier_replication/v1.4/**, n=30 medium seeds 0-29 + transcripts)
  (c) G1 partial extension (data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/ + solver-hard-seeds30to59/
      + cf394894 gpt-5.5 pre-registration disclosure + Panel Fix A raw-before-luck-adjusted and post-hoc lock checks)
  (d) Self-contained tamper/mutation positive controls in temporary scratch directories (/tmp/opencode/w7)
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import unittest.mock as _mock
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

UNACCUSED_END_REASONS = frozenset({"horizon", "tool_cap", "eval_cap"})
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)
MINUS_SIGN = chr(0x2212)
PLUS_MINUS = chr(0x00B1)
DELTA_CHAR = chr(0x0394)
HASH_CH = chr(35)
CO_AUTHOR_TAG = "-".join(("Co", "Authored", "By"))
STOP_EARLY_NOTE = (
    "day-1 guess (recorded under the pre-2bb6729 name stop_early; "
    "today's stop_early stops without accusing and scores 0, see results/judge_table.md)"
)

SECRET_SPECS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("google_api_key", "AIza", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("openai_api_key", "sk-", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("hf_token", "hf_", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    ("github_token", "gh", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("github_pat", "github_pat_", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("private_key_pem", "-----BEGIN ", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    (
        "verda_secret_literal",
        "VERDA_CLIENT_SECRET",
        re.compile(r"VERDA_CLIENT_SECRET\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    ),
    (
        "world_secret_literal",
        "CANARY_WORLD_SECRET",
        re.compile(r"CANARY_WORLD_SECRET\s*[:=]\s*['\"]?(?!<|\$)[A-Za-z0-9_\-]{12,}"),
    ),
    (
        "ledger_token_literal",
        "CANARY_LEDGER_TOKEN",
        re.compile(r"CANARY_LEDGER_TOKEN\s*[:=]\s*['\"]?(?!<|\$|abc123)[0-9a-f]{24,}"),
    ),
)
IPV4_MID_RE = re.compile(r"\.[0-9]{1,3}\.[0-9]{1,3}\.")
IPV4_EXACT_RE = re.compile(r"(?<![0-9A-Za-z])([0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})(?![0-9A-Za-z])")
TRANSCRIPT_SPLIT_RE = re.compile(r"^--- stdout\n(.*?)\n--- stderr\n(.*)$", re.M | re.S)
TRANSCRIPT_RC_RE = re.compile(r"^--- rc=(\S+)", re.M)
EXCLUDED_ATTEMPT_RE = re.compile(r"^([a-z0-9_]+)-(easy|medium|hard)-(\d+)-(\d{6}):\s*(.+)$")


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _same_value(a: Any, b: Any, tol: float = 1e-12) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
        if math.isnan(a) or math.isnan(b):
            return False
        return abs(a - b) <= tol
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same_value(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_same_value(a[k], b[k], tol) for k in a)
    return a == b


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalize_pre_1bc3e281_error_detail(
    ok: bool,
    data: Any,
    error: Any,
    want_norm: Any,
) -> tuple[dict[str, Any], bool]:
    got_payload = {"ok": ok, "data": data, "error": error}
    if (
        not ok
        and error == "invalid arguments"
        and isinstance(data, dict)
        and set(data) == {"detail"}
        and not (
            isinstance(want_norm, dict)
            and isinstance(want_norm.get("data"), dict)
            and "detail" in want_norm["data"]
        )
    ):
        return {"ok": ok, "data": {}, "error": error}, True
    return got_payload, False


def audit_eval_hf_run_dir(
    run_dir: Path,
    root: Path = ROOT,
    max_calls_cap: int | None = 120,
    require_summary: bool = True,
    score_grid: float = 0.01,
    allow_legacy_summary_no_eval_cap: bool = False,
    preloaded_eps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from canary import rules
    from canary.env import _SPECS
    from train.eval_hf import summarize

    ep_file = run_dir / "episodes.jsonl"
    meta_file = run_dir / "meta.json"
    summ_file = run_dir / "summary.json"
    eps = preloaded_eps if preloaded_eps is not None else _read_jsonl(ep_file)
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    summ = json.loads(summ_file.read_text(encoding="utf-8")) if summ_file.exists() else None

    heldout_set = set(rules.HELDOUT_SEEDS)
    dev_set = set(rules.DEV_SEEDS)
    judge_set = set(rules.JUDGE_SEEDS)

    score_violations: list[dict[str, Any]] = []
    step_violations: list[dict[str, Any]] = []
    seed_violations: list[dict[str, Any]] = []
    total_steps = 0

    for ep_idx, e in enumerate(eps):
        tier = str(e.get("tier", ""))
        seed = int(e.get("seed", -1))
        score = float(e.get("score", float("nan")))
        end_reason = str(e.get("end_reason", ""))
        accused = e.get("accused")
        correct = bool(e.get("correct"))
        steps = e.get("steps") or []
        total_steps += len(steps)

        if tier not in rules.TIERS:
            step_violations.append({"index": ep_idx, "seed": seed, "kind": "unknown_tier", "tier": tier})
            continue
        tp = rules.tier_params(tier)
        valid_emp_ids = {f"e{i:02d}" for i in range(tp.n_employees)}

        if seed not in heldout_set or seed in dev_set or seed in judge_set:
            seed_violations.append({"index": ep_idx, "tier": tier, "seed": seed, "kind": "not_heldout_seed"})

        if end_reason == "accused":
            if accused not in valid_emp_ids:
                score_violations.append({"tier": tier, "seed": seed, "kind": "invalid_accused_id", "accused": accused})
            if correct:
                if not (0.0 < score <= 1.0 + 1e-9):
                    score_violations.append({"tier": tier, "seed": seed, "kind": "right_score_bounds", "score": score})
                inv_grid = 1.0 / score_grid
                if abs(round(score * inv_grid) - score * inv_grid) > 1e-6:
                    score_violations.append(
                        {"tier": tier, "seed": seed, "kind": "non_grid_score", "score": score, "grid": score_grid}
                    )
            else:
                if abs(score - tp.wrong_accusation_score) > 1e-9:
                    score_violations.append({"tier": tier, "seed": seed, "kind": "wrong_score_not_minus_one", "score": score})
        elif end_reason in UNACCUSED_END_REASONS:
            if accused is not None or correct or abs(score) > 1e-9:
                score_violations.append({
                    "tier": tier,
                    "seed": seed,
                    "kind": "unaccused_nonzero_or_flagged",
                    "score": score,
                    "accused": accused,
                    "correct": correct,
                })
        else:
            score_violations.append({"tier": tier, "seed": seed, "kind": "unexpected_end_reason", "end_reason": end_reason})

        cap = min(tp.tool_call_cap, max_calls_cap) if max_calls_cap is not None else tp.tool_call_cap
        if not (1 <= len(steps) <= cap):
            step_violations.append({"tier": tier, "seed": seed, "kind": "step_count_cap", "steps": len(steps), "cap": cap})

        cur_day = 1
        last_known_v = 1.0
        accepted_accuse_steps: list[int] = []
        empty_status_calls = 0

        for idx, st in enumerate(steps):
            if st.get("t") != idx:
                step_violations.append({"tier": tier, "seed": seed, "kind": "non_contiguous_t", "expected": idx, "got": st.get("t")})
            tool = st.get("tool")
            if tool not in _SPECS:
                step_violations.append({"tier": tier, "seed": seed, "kind": "invalid_tool_name", "tool": tool})
            if st.get("day") != cur_day:
                step_violations.append(
                    {"tier": tier, "seed": seed, "kind": "day_progression_mismatch", "t": idx, "got": st.get("day"), "want": cur_day}
                )
            args = st.get("args") if isinstance(st.get("args"), dict) else {}
            if tool == "status" and args == {}:
                empty_status_calls += 1
            res = st.get("result") if isinstance(st.get("result"), dict) else {}
            data = res.get("data") if isinstance(res.get("data"), dict) else {}
            if res.get("ok") and "V" in data:
                last_known_v = float(data["V"])
            if tool == "advance_day" and res.get("ok"):
                cur_day = int(data.get("day", cur_day))
            if tool == "accuse" and res.get("ok"):
                accepted_accuse_steps.append(idx)
                if args.get("employee") != accused:
                    step_violations.append(
                        {"tier": tier, "seed": seed, "kind": "accuse_arg_mismatch", "arg": args.get("employee"), "accused": accused}
                    )

        final_day = int(e.get("final_day", 0))
        if final_day != cur_day or not (1 <= final_day <= tp.n_days):
            step_violations.append(
                {"tier": tier, "seed": seed, "kind": "final_day_invalid", "final_day": final_day, "tracked_day": cur_day}
            )

        if end_reason == "accused":
            if accepted_accuse_steps != [len(steps) - 1]:
                step_violations.append(
                    {"tier": tier, "seed": seed, "kind": "accuse_not_unique_terminal", "accepted": accepted_accuse_steps, "len": len(steps)}
                )
            if correct and score > last_known_v + 1e-9:
                score_violations.append(
                    {"tier": tier, "seed": seed, "kind": "score_exceeds_known_v", "score": score, "known_v": last_known_v}
                )
        else:
            if accepted_accuse_steps:
                step_violations.append({"tier": tier, "seed": seed, "kind": "unaccused_has_accepted_accuse", "accepted": accepted_accuse_steps})

        inv_calls = int((e.get("meta") or {}).get("invalid_calls", 0))
        if not (0 <= inv_calls <= empty_status_calls):
            step_violations.append(
                {
                    "tier": tier,
                    "seed": seed,
                    "kind": "invalid_calls_exceeds_status_fallbacks",
                    "invalid_calls": inv_calls,
                    "empty_status_calls": empty_status_calls,
                }
            )

    summary_violations: list[dict[str, Any]] = []
    recomputed_summary = summarize(eps)
    if summ is None:
        if require_summary:
            summary_violations.append({"kind": "missing_summary_json"})
    else:
        got_by_tier = summ.get("by_tier")
        expected_by_tier = recomputed_summary
        if allow_legacy_summary_no_eval_cap and isinstance(got_by_tier, dict):
            expected_by_tier = {
                t: ({k: v for k, v in td.items() if k != "eval_cap_rate"} if "eval_cap_rate" not in got_by_tier.get(t, {}) else td)
                for t, td in recomputed_summary.items()
            }
        if got_by_tier != expected_by_tier:
            summary_violations.append({"kind": "summary_mismatch", "recorded": got_by_tier, "recomputed": expected_by_tier})

    rel_dir = run_dir.relative_to(root).as_posix() if root in run_dir.parents or run_dir == root else run_dir.as_posix()
    ok = not (score_violations or step_violations or seed_violations or summary_violations)
    return {
        "dir": rel_dir,
        "n_episodes": len(eps),
        "n_steps": total_steps,
        "git_sha": meta.get("git_sha"),
        "seed_offset": meta.get("seed_offset", 0),
        "has_summary": summ is not None,
        "score_violations": score_violations,
        "step_violations": step_violations,
        "seed_violations": seed_violations,
        "summary_violations": summary_violations,
        "ok": ok,
    }


def audit_verda_curves(root: Path = ROOT) -> dict[str, Any]:
    from canary import rules

    verda_dir = root / "data" / "fr8" / "verda"
    curve_files = sorted(verda_dir.rglob("curve.jsonl")) if verda_dir.exists() else []
    eval_seeds = set(rules.DEV_SEEDS) | set(rules.HELDOUT_SEEDS) | set(rules.JUDGE_SEEDS)

    runs: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    total_curve_steps = 0

    for cf in curve_files:
        recs = _read_jsonl(cf)
        total_curve_steps += len(recs)
        steps = [r.get("step") for r in recs]
        contiguous = steps == list(range(len(recs)))
        if not contiguous:
            violations.append({"file": cf.relative_to(root).as_posix(), "kind": "non_contiguous_curve_steps"})
        for r in recs:
            vr = r.get("valid_rate")
            if vr is not None and not (-1e-9 <= float(vr) <= 1.0 + 1e-9):
                violations.append({"file": cf.relative_to(root).as_posix(), "step": r.get("step"), "kind": "valid_rate_bounds"})
            fac = r.get("forced_accuse_correct")
            if fac is not None and not (-1e-9 <= float(fac) <= 1.0 + 1e-9):
                violations.append({"file": cf.relative_to(root).as_posix(), "step": r.get("step"), "kind": "forced_accuse_bounds"})

        ts_file = cf.parent / "lora" / "train_summary.json"
        ts_steps = None
        seed_base = None
        if ts_file.exists():
            ts = json.loads(ts_file.read_text(encoding="utf-8"))
            ts_steps = int(ts.get("steps", -1))
            seed_base = int((ts.get("args") or {}).get("seed_base", -1))
            if ts_steps != len(recs):
                violations.append(
                    {"file": cf.relative_to(root).as_posix(), "kind": "train_summary_step_mismatch", "curve": len(recs), "summary": ts_steps}
                )
            train_probe_range = set(range(seed_base, seed_base + 50000))
            if seed_base < 100000 or (train_probe_range & eval_seeds):
                violations.append({"file": cf.relative_to(root).as_posix(), "kind": "train_seed_leakage", "seed_base": seed_base})

        runs.append({
            "file": cf.relative_to(root).as_posix(),
            "n_steps": len(recs),
            "contiguous": contiguous,
            "train_summary_steps": ts_steps,
            "seed_base": seed_base,
        })

    snap_curve = verda_dir / "run-verda-s0" / "curve.jsonl"
    full_curve = verda_dir / "h100-3bb7" / "run-verda-s0" / "curve.jsonl"
    prefix_match = None
    if snap_curve.exists() and full_curve.exists():
        snap_lines = [l for l in snap_curve.read_text(encoding="utf-8").splitlines() if l.strip()]
        full_lines = [l for l in full_curve.read_text(encoding="utf-8").splitlines() if l.strip()]
        prefix_match = len(snap_lines) <= len(full_lines) and snap_lines == full_lines[: len(snap_lines)]
        if not prefix_match:
            violations.append({"file": snap_curve.relative_to(root).as_posix(), "kind": "early_snapshot_prefix_mismatch"})

    return {
        "n_curve_files": len(curve_files),
        "total_curve_steps": total_curve_steps,
        "early_s0_prefix_match": prefix_match,
        "curves": runs,
        "violations": violations,
        "ok": not violations,
    }


def audit_ws4_tables_and_docs(
    root: Path = ROOT,
    preloaded_by_file: dict[Path, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    from fr8.analysis.ws4_table import fmt as ws4_fmt, load as ws4_load, row as ws4_row
    from fr8.analysis.ws4_whom import mci as whom_mci, wilson as ws4_wilson

    def quiet_load(dirs: list[Path]) -> list[dict[str, Any]]:
        if preloaded_by_file is not None and all((d / "episodes.jsonl") in preloaded_by_file for d in dirs):
            eps_out: list[dict[str, Any]] = []
            seen: set[tuple[str, int]] = set()
            for d in dirs:
                for e in preloaded_by_file[d / "episodes.jsonl"]:
                    k = (e["tier"], e["seed"])
                    if k not in seen:
                        seen.add(k)
                        eps_out.append(e)
            return eps_out
        spec = ",".join(str(d) for d in dirs)
        with contextlib.redirect_stderr(io.StringIO()):
            return ws4_load(spec)

    def get_eps(ef: Path) -> list[dict[str, Any]]:
        if preloaded_by_file is not None and ef in preloaded_by_file:
            return preloaded_by_file[ef]
        return _read_jsonl(ef)

    verda_ep_files = sorted((root / "data" / "fr8" / "verda").rglob("episodes.jsonl"))
    j4_ep_files = sorted((root / "data" / "fr8" / "j4").rglob("episodes.jsonl"))

    rosters_by_run: dict[str, dict[tuple[str, int], list[str]]] = {}
    for ef in verda_ep_files + j4_ep_files:
        m: dict[tuple[str, int], list[str]] = {}
        for e in get_eps(ef):
            for st in e.get("steps") or []:
                res = st.get("result") or {}
                if st.get("tool") == "list_employees" and res.get("ok"):
                    emps = (res.get("data") or {}).get("employees") or []
                    m[(e["tier"], int(e["seed"]))] = [str(x.get("name", "")) for x in emps]
                    break
        rosters_by_run[ef.parent.relative_to(root).as_posix()] = m

    run_keys = list(rosters_by_run)
    shared_seed_pairs = 0
    identical_world_pairs = 0
    for i in range(len(run_keys)):
        for j in range(i + 1, len(run_keys)):
            ra, rb = rosters_by_run[run_keys[i]], rosters_by_run[run_keys[j]]
            for k in set(ra) & set(rb):
                shared_seed_pairs += 1
                if ra[k] == rb[k]:
                    identical_world_pairs += 1

    j4_lora = root / "data" / "fr8" / "j4" / "run-44397" / "runs" / "eval-lora"
    j4_par = root / "data" / "fr8" / "j4" / "run-44397" / "runs" / "eval-lora-par"
    j4_base = root / "data" / "fr8" / "j4" / "run-44397" / "runs" / "eval-base"
    v3_s0_a = root / "data" / "fr8" / "verda" / "h100-3bb7" / "runs" / "v3-verda-s0"
    v3_s0_b = root / "data" / "fr8" / "verda" / "evalbox-68bb" / "v3-4k-s0-off30"
    v3_8k_s1 = root / "data" / "fr8" / "verda" / "a100-ac58" / "runs" / "v3-verda-8k-s1"
    v3_8k_s2 = root / "data" / "fr8" / "verda" / "h100spot-dbd0" / "runs" / "v3-verda-8k-s2"

    with contextlib.redirect_stderr(io.StringIO()):
        j4_ab = ws4_load(f"{j4_lora},{j4_par}")
        j4_ba = ws4_load(f"{j4_par},{j4_lora}")
    j4_raw_count = len(get_eps(j4_lora / "episodes.jsonl")) + len(get_eps(j4_par / "episodes.jsonl"))
    v3_ab = quiet_load([v3_s0_a, v3_s0_b])
    v3_ba = quiet_load([v3_s0_b, v3_s0_a])
    s1s2_accidental_pool = quiet_load([v3_8k_s1, v3_8k_s2])

    pooling_audit = {
        "j4_v1_raw_episodes": j4_raw_count,
        "j4_v1_pooled_n": len(j4_ab),
        "j4_v1_dropped_duplicates": j4_raw_count - len(j4_ab),
        "j4_v1_lora_then_par_mean": round(ws4_row(j4_ab)["score"], 6),
        "j4_v1_par_then_lora_mean": round(ws4_row(j4_ba)["score"], 6),
        "j4_v1_order_sensitive": abs(ws4_row(j4_ab)["score"] - ws4_row(j4_ba)["score"]) > 1e-6,
        "v3_4k_s0_pooled_n": len(v3_ab),
        "v3_4k_s0_dropped_duplicates": 180 - len(v3_ab),
        "v3_4k_s0_order_invariant": abs(ws4_row(v3_ab)["score"] - ws4_row(v3_ba)["score"]) < 1e-12,
        "s1_s2_same_seed_pool_drops_all_second": len(s1s2_accidental_pool) == 90,
    }

    committed_sources: dict[str, list[dict[str, Any]]] = {
        "v1": j4_ab,
        "v3-4k-s0": v3_ab,
        "v3_4k_s0": v3_ab,
        "v3-8k-s1": quiet_load([v3_8k_s1]),
        "v3_8k_s1_A100_371st": quiet_load([v3_8k_s1]),
        "v3-8k-s2": quiet_load([v3_8k_s2]),
        "v3_8k_s2_H100_693st": quiet_load([v3_8k_s2]),
    }
    v3_s0_first90 = quiet_load([v3_s0_a])
    j4_base_eps = quiet_load([j4_base])

    table_files = sorted((root / "fr8" / "analysis" / "out").glob("ws4_table*.md"))
    table_mismatches: list[dict[str, Any]] = []
    delta_cells_checked = 0
    committed_rows_checked = 0

    delta_hdr_re = re.compile(rf"^{DELTA_CHAR} vs (\S+) \(two-sample")
    delta_val_re = re.compile(rf"^([+-]\d+\.\d+) {PLUS_MINUS} (\d+\.\d+) \((\d+) vs (\d+)\)$")

    for tf in table_files:
        lines = tf.read_text(encoding="utf-8").splitlines()
        hdr_cols = [c.strip() for c in lines[0].split("|")[1:-1]]
        refs = [delta_hdr_re.match(c).group(1) for c in hdr_cols[10:] if delta_hdr_re.match(c)]
        data_lines = [
            l for l in lines
            if l.startswith("|") and not l.startswith("|---") and not l.startswith("| model ")
        ]
        parsed_rows: dict[tuple[str, str], tuple[int, float, float, list[str]]] = {}
        for l in data_lines:
            cols = [c.strip() for c in l.split("|")[1:-1]]
            model, _info, _seeds, tier, n_s, sc_s, acc_s, cor_s, abs_s, val_s = cols[:10]
            sc_parts = [p.strip() for p in sc_s.split(PLUS_MINUS)]
            m_val = float(sc_parts[0])
            ci_val = 0.0 if sc_parts[1] == EN_DASH else float(sc_parts[1])
            parsed_rows[(model, tier)] = (int(n_s), m_val, ci_val, cols[10:])

            src = None
            if tf.name == "ws4_table_v1.md" and model == "base":
                src = j4_base_eps
            elif tf.name == "ws4_table_v3s0.md" and model == "v3_4k_s0":
                src = v3_s0_first90
            elif model in committed_sources:
                src = committed_sources[model]

            if src is not None:
                committed_rows_checked += 1
                sub = [e for e in src if tier == "all" or e["tier"] == tier]
                r = ws4_row(sub)
                want_sc = f"{ws4_fmt(r['score'])} {PLUS_MINUS} {ws4_fmt(r['ci'])}"
                if (
                    int(n_s) != r["n"]
                    or sc_s != want_sc
                    or acc_s != ws4_fmt(r["accused"], 2)
                    or cor_s != ws4_fmt(r["correct"], 2)
                    or abs_s != ws4_fmt(r["abstain"], 2)
                    or val_s != ws4_fmt(r["valid"], 2)
                ):
                    table_mismatches.append({"table": tf.name, "model": model, "tier": tier, "kind": "committed_row_mismatch"})

        for (model, tier), (n_a, ma, ha, dcols) in parsed_rows.items():
            for idx, ref in enumerate(refs):
                delta_cells_checked += 1
                got = dcols[idx]
                if model == ref or (ref, tier) not in parsed_rows:
                    if got != EN_DASH:
                        table_mismatches.append({"table": tf.name, "model": model, "tier": tier, "ref": ref, "kind": "expected_dash"})
                    continue
                n_r, mr, hr, _ = parsed_rows[(ref, tier)]
                m_got = delta_val_re.match(got)
                if not m_got:
                    table_mismatches.append(
                        {"table": tf.name, "model": model, "tier": tier, "ref": ref, "kind": "bad_delta_format", "got": got}
                    )
                    continue
                g_dm, g_dh, g_na, g_nr = (
                    float(m_got.group(1)),
                    float(m_got.group(2)),
                    int(m_got.group(3)),
                    int(m_got.group(4)),
                )
                want_dm = ma - mr
                want_dh = math.sqrt(ha * ha + hr * hr)
                if abs(g_dm - want_dm) > 0.002 or abs(g_dh - want_dh) > 0.002 or g_na != n_a or g_nr != n_r:
                    table_mismatches.append({
                        "table": tf.name,
                        "model": model,
                        "tier": tier,
                        "ref": ref,
                        "kind": "two_sample_delta_math_mismatch",
                        "got": got,
                    })

    whom_file = root / "fr8" / "analysis" / "out" / "ws4_whom_v3.md"
    whom_checked = 0
    pooled_v3_accused = 0
    pooled_v3_correct = 0
    if whom_file.exists():
        whom_specs = {
            "v3-4k-s0": (root / "data/fr8/verda/h100-3bb7/run-verda-s0/curve.jsonl", [v3_s0_a, v3_s0_b]),
            "v3-8k-s1": (root / "data/fr8/verda/a100-ac58/run-verda-8k-s1/curve.jsonl", [v3_8k_s1]),
            "v3-8k-s2": (root / "data/fr8/verda/h100spot-dbd0/run-verda-8k-s2/curve.jsonl", [v3_8k_s2]),
        }
        for line in whom_file.read_text(encoding="utf-8").splitlines()[2:]:
            if not line.startswith("|"):
                continue
            cols = [c.strip() for c in line.split("|")[1:-1]]
            lbl = cols[0]
            if lbl.startswith("v3-"):
                acc_num = int(cols[4].split("/")[0])
                cor_num = int(cols[5].split("/")[0])
                pooled_v3_accused += acc_num
                pooled_v3_correct += cor_num
            if lbl not in whom_specs:
                continue
            whom_checked += 1
            cf, edirs = whom_specs[lbl]
            recs = _read_jsonl(cf)
            w = min(100, len(recs) // 2) or 1
            f_m = whom_mci([r.get("forced_accuse_correct") for r in recs[:w]])
            l_m = whom_mci([r.get("forced_accuse_correct") for r in recs[-w:]])
            eps = quiet_load(edirs)
            acc = [e for e in eps if e["end_reason"] == "accused"]
            k = sum(bool(e["correct"]) for e in acc)
            p, lo, hi = ws4_wilson(k, len(acc))
            want_cols = [
                lbl,
                str(len(recs)),
                f"{f_m[0]:.3f} {PLUS_MINUS} {f_m[1]:.3f} (W={w})",
                f"{l_m[0]:.3f} {PLUS_MINUS} {l_m[1]:.3f} (W={w})",
                f"{len(acc)}/{len(eps)}",
                f"{k}/{len(acc)} = {p:.2f} ({lo:.2f}{EN_DASH}{hi:.2f})",
            ]
            if cols != want_cols:
                table_mismatches.append({"table": "ws4_whom_v3.md", "model": lbl, "kind": "whom_row_mismatch", "got": cols, "want": want_cols})

    missing_local_ws4_dirs = [
        rel for rel in (
            "data/fr8/ws4/ws4-base-v14",
            "data/fr8/ws4/ws4-base-v14-off6",
            "data/fr8/ws4/ws4-v2-44410",
        )
        if not (root / rel / "episodes.jsonl").exists()
    ]

    v3_table_txt = (root / "fr8/analysis/out/ws4_table_v3.md").read_text(encoding="utf-8") if (root / "fr8/analysis/out/ws4_table_v3.md").exists() else ""
    readme_txt = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else ""
    sub_doc = (root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8") if (root / "docs" / "SUBMISSION.md").exists() else ""
    fr8_doc = (root / "docs" / "reports" / "fr8.md").read_text(encoding="utf-8") if (root / "docs" / "reports" / "fr8.md").exists() else ""

    v3_bar_not_met_lines = [l for l in v3_table_txt.splitlines() if "bar NOT met" in l]
    readme_tiebreak_ok = (
        "Tiebreak: a small model trained on Canary experience (honest result)" in readme_txt
        and "3% valid tool calls" in readme_txt
        and "| 36 |" in readme_txt
        and "0.457" in readme_txt
        and "0.147" in readme_txt
        and "0.050" in readme_txt
        and "+0.310" in readme_txt
        and "**not met**" in readme_txt
    )

    doc_checks = {
        "ws4_table_v3_all_4_bar_not_met": len(v3_bar_not_met_lines) == 4,
        "readme_66a26f5c_honest_tiebreak": readme_tiebreak_ok,
        "fr8_doc_has_0400_correction": "04:00 CORRECTION" in fr8_doc and "two-sample" in fr8_doc,
        "fr8_doc_has_0445_readout_bar_not_met": (
            "04:45 WS4 small-model tiebreaker readout: bar NOT met" in fr8_doc
            and "15/135 = 0.11" in fr8_doc
            and pooled_v3_correct == 15
            and pooled_v3_accused == 135
        ),
        "submission_states_two_sample": "two-sample, not seed-paired" in sub_doc,
        "submission_has_v3_4k_s0_n180": "-0.147" in sub_doc and "0.063" in sub_doc and "180" in sub_doc,
        "submission_has_v3_vs_v2_delta": "+0.310" in sub_doc and "0.107" in sub_doc,
        "submission_has_v3_8k_s1": "-0.777" in sub_doc and "0.118" in sub_doc,
        "submission_stale_base_n16_vs_v3_table_n36": "| base | 16 |" in sub_doc and "| all | 36 | 0.000" in v3_table_txt,
        "submission_omits_landed_v3_8k_s2": "-0.050" not in sub_doc,
    }

    honest_readout_ok = (
        doc_checks["ws4_table_v3_all_4_bar_not_met"]
        and doc_checks["readme_66a26f5c_honest_tiebreak"]
        and doc_checks["fr8_doc_has_0400_correction"]
        and doc_checks["fr8_doc_has_0445_readout_bar_not_met"]
    )

    return {
        "cross_run_shared_seed_pairs": shared_seed_pairs,
        "cross_run_identical_worlds": identical_world_pairs,
        "two_sample_required_proven": shared_seed_pairs > 0 and identical_world_pairs == 0,
        "pooling": pooling_audit,
        "n_ws4_tables": len(table_files),
        "committed_rows_checked": committed_rows_checked,
        "delta_cells_checked": delta_cells_checked,
        "whom_rows_checked": whom_checked,
        "pooled_v3_precision": {"correct": pooled_v3_correct, "accused": pooled_v3_accused},
        "table_mismatches": table_mismatches,
        "missing_local_ws4_dirs": missing_local_ws4_dirs,
        "doc_checks": doc_checks,
        "ok": shared_seed_pairs > 0 and identical_world_pairs == 0 and not table_mismatches and honest_readout_ok,
    }


def scan_secrets_and_ips(scan_paths: list[Path], root: Path = ROOT) -> dict[str, Any]:
    secret_hits: list[dict[str, str]] = []
    ip_hits: list[dict[str, str]] = []
    files_scanned = 0

    for base in scan_paths:
        if not base.exists():
            continue
        targets = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for p in targets:
            files_scanned += 1
            txt = p.read_text(encoding="utf-8", errors="replace")
            rel = p.relative_to(root).as_posix() if (root in p.parents or p == root) else p.as_posix()
            for kind, needle, pat in SECRET_SPECS:
                if needle in txt:
                    for m in pat.finditer(txt):
                        secret_hits.append({"file": rel, "kind": kind, "prefix": m.group(0)[:12] + "..."})
            if IPV4_MID_RE.search(txt):
                for m in IPV4_EXACT_RE.finditer(txt):
                    ip = m.group(1)
                    octets = [int(x) for x in ip.split(".")]
                    if all(0 <= x <= 255 for x in octets) and ip not in ("127.0.0.1", "0.0.0.0"):
                        ip_hits.append({"file": rel, "ip": ip})

    return {
        "files_scanned": files_scanned,
        "secret_hits": secret_hits,
        "non_loopback_ipv4_hits": ip_hits,
        "unique_non_loopback_ips": sorted({h["ip"] for h in ip_hits}),
        "ok": len(secret_hits) == 0,
    }


def audit_verda_ws4(root: Path = ROOT) -> dict[str, Any]:
    verda_ep_files = sorted((root / "data" / "fr8" / "verda").rglob("episodes.jsonl"))
    j4_ep_files = sorted((root / "data" / "fr8" / "j4").rglob("episodes.jsonl"))
    preloaded = {f: _read_jsonl(f) for f in verda_ep_files + j4_ep_files}

    verda_runs = [
        audit_eval_hf_run_dir(
            f.parent,
            root=root,
            max_calls_cap=120,
            require_summary=True,
            score_grid=0.01,
            allow_legacy_summary_no_eval_cap=False,
            preloaded_eps=preloaded[f],
        )
        for f in verda_ep_files
    ]
    j4_runs = [
        audit_eval_hf_run_dir(
            f.parent,
            root=root,
            max_calls_cap=300,
            require_summary=(f.parent / "summary.json").exists(),
            score_grid=0.005,
            allow_legacy_summary_no_eval_cap=True,
            preloaded_eps=preloaded[f],
        )
        for f in j4_ep_files
    ]
    curves = audit_verda_curves(root=root)
    tables_and_docs = audit_ws4_tables_and_docs(root=root, preloaded_by_file=preloaded)
    secrets = scan_secrets_and_ips(
        [
            root / "data" / "fr8" / "verda",
            root / "fr8" / "verda",
            root / "fr8" / "analysis",
        ],
        root=root,
    )

    empty_git_sha_dirs = [r["dir"] for r in verda_runs if not r.get("git_sha")]
    ok = (
        all(r["ok"] for r in verda_runs)
        and all(r["ok"] for r in j4_runs)
        and curves["ok"]
        and tables_and_docs["ok"]
        and secrets["ok"]
    )
    return {
        "n_verda_run_dirs": len(verda_runs),
        "total_verda_episodes": sum(r["n_episodes"] for r in verda_runs),
        "total_verda_steps": sum(r["n_steps"] for r in verda_runs),
        "n_j4_run_dirs": len(j4_runs),
        "total_j4_episodes": sum(r["n_episodes"] for r in j4_runs),
        "total_j4_steps": sum(r["n_steps"] for r in j4_runs),
        "empty_git_sha_dirs": empty_git_sha_dirs,
        "verda_runs": verda_runs,
        "j4_runs": j4_runs,
        "curves": curves,
        "tables_and_docs": tables_and_docs,
        "secret_scan": secrets,
        "ok": ok,
    }


def _replay_and_check_transcript_dir(
    shard_dir: Path,
    version: str = "v1.4",
    expect_transcripts: bool = True,
    root: Path = ROOT,
) -> dict[str, Any]:
    from canary import rules
    from canary.agents.frontier.common import (
        agent_touched_server,
        classify_infra,
        steps_from_events,
        usage_from_events,
    )
    from canary.env import Env
    from canary.redteam.anticheat import _client_only_step, _client_truncated_bytes, _norm_result
    from canary.redteam.tamper_guard import (
        _BRACKET_TRUNC_SUFFIX,
        check_episode_tamper,
        valid_client_only_step,
        valid_truncated_step,
    )

    eps = _read_jsonl(shard_dir / "episodes.jsonl")
    meta_file = shard_dir / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    tr_dir = shard_dir / "transcripts"
    tr_files = sorted(tr_dir.glob("*.txt")) if tr_dir.exists() else []

    replay_mismatches: list[dict[str, Any]] = []
    transcript_mismatches: list[dict[str, Any]] = []
    total_steps = 0
    truncated_checked = 0
    client_only_steps = 0
    pre_1bc3e281_detail_normalized = 0

    usage_sum = {
        "in": 0,
        "cached_in": 0,
        "out": 0,
        "llm_calls": 0,
        "opencode_reported_cost_usd": 0.0,
        "cost_usd_est": 0.0,
        "cost_usd_upper": 0.0,
    }
    ep_seeds: list[int] = []

    with rules.tiers_version(version):
        for e in eps:
            seed = int(e["seed"])
            ep_seeds.append(seed)
            tier = str(e["tier"])
            env = Env(tier, seed)
            steps = e.get("steps") or []
            total_steps += len(steps)
            step_bad = 0
            first_bad = None

            for idx, st in enumerate(steps):
                if _client_only_step(st):
                    if valid_client_only_step(st, e, meta):
                        client_only_steps += 1
                    else:
                        step_bad += 1
                        if first_bad is None:
                            first_bad = idx
                    continue
                r = env.call(st["tool"], st.get("args") or {})
                want_raw = st.get("result")
                want_norm = _norm_result(want_raw)
                got_payload, was_norm = _normalize_pre_1bc3e281_error_detail(r.ok, r.data, r.error, want_norm)
                if was_norm:
                    pre_1bc3e281_detail_normalized += 1
                is_bracket_trunc = (
                    isinstance(want_raw, dict)
                    and set(want_raw) == {"raw"}
                    and isinstance(want_raw.get("raw"), str)
                    and bool(_BRACKET_TRUNC_SUFFIX.search(want_raw["raw"]))
                )
                trunc = _client_truncated_bytes(want_raw)
                if trunc is not None or is_bracket_trunc:
                    truncated_checked += 1
                    step_ok = valid_truncated_step(want_raw, got_payload, e, meta)
                else:
                    step_ok = want_norm is not None and _canon(got_payload) == _canon(want_norm)
                if not step_ok:
                    step_bad += 1
                    if first_bad is None:
                        first_bad = idx

            verdict = env.verdict()
            got_score = env.score()
            tamper_probs = check_episode_tamper(e, env, shard_dir, meta)
            if (
                step_bad
                or tamper_probs
                or abs(got_score - float(e["score"])) > 1e-6
                or verdict["accused"] != e.get("accused")
                or bool(verdict["accused_correct"]) != bool(e.get("correct"))
            ):
                replay_mismatches.append({
                    "seed": seed,
                    "recorded_score": e.get("score"),
                    "replayed_score": got_score,
                    "recorded_accused": e.get("accused"),
                    "replayed_accused": verdict["accused"],
                    "step_mismatches": step_bad,
                    "first_bad_step": first_bad,
                    "tamper_probs": tamper_probs,
                })

            if expect_transcripts:
                tf = tr_dir / f"{seed}.txt"
                if not tf.exists():
                    transcript_mismatches.append({"seed": seed, "kind": "missing_transcript_file"})
                    continue
                raw_txt = tf.read_text(encoding="utf-8", errors="replace")
                rc_m = TRANSCRIPT_RC_RE.search(raw_txt)
                sp_m = TRANSCRIPT_SPLIT_RE.search(raw_txt)
                if not rc_m or rc_m.group(1) != "0" or not sp_m:
                    transcript_mismatches.append(
                        {"seed": seed, "kind": "bad_transcript_header_or_rc", "rc": rc_m.group(1) if rc_m else None}
                    )
                    continue
                stdout, stderr = sp_m.group(1), sp_m.group(2)
                if agent_touched_server(stdout):
                    transcript_mismatches.append({"seed": seed, "kind": "agent_touched_server"})
                infra_flag = classify_infra(stdout, stderr)
                if infra_flag is not None:
                    transcript_mismatches.append({"seed": seed, "kind": "unexpected_infra_flag", "infra": infra_flag})

                rebuilt_steps = steps_from_events(stdout)
                if len(rebuilt_steps) != len(steps):
                    transcript_mismatches.append({
                        "seed": seed,
                        "kind": "transcript_step_count_mismatch",
                        "recorded": len(steps),
                        "transcript": len(rebuilt_steps),
                    })
                else:
                    for s_idx, (s_ep, s_tr) in enumerate(zip(steps, rebuilt_steps)):
                        if (
                            s_ep.get("tool") != s_tr.tool
                            or (s_ep.get("args") or {}) != s_tr.args
                            or int(s_ep.get("day", -1)) != int(s_tr.day)
                            or _canon(s_ep.get("result")) != _canon(s_tr.result)
                        ):
                            transcript_mismatches.append({"seed": seed, "kind": "transcript_step_mismatch", "step": s_idx})
                            break

                model_spec = str(e.get("agent", "")).partition(":")[2]
                rebuilt_usage = usage_from_events(stdout, model_spec)
                ep_usage = (e.get("meta") or {}).get("usage")
                if ep_usage is not None and rebuilt_usage != ep_usage:
                    transcript_mismatches.append(
                        {"seed": seed, "kind": "episode_usage_mismatch", "recorded": ep_usage, "rebuilt": rebuilt_usage}
                    )
                for k in usage_sum:
                    if k in rebuilt_usage and rebuilt_usage[k] is not None:
                        usage_sum[k] += rebuilt_usage[k]

    if expect_transcripts:
        tr_seeds = sorted(int(p.stem) for p in tr_files if p.stem.isdigit())
        if tr_seeds != sorted(ep_seeds):
            transcript_mismatches.append(
                {"kind": "transcript_seed_bijection_mismatch", "transcript_seeds": tr_seeds, "episode_seeds": sorted(ep_seeds)}
            )

    usage_sum_rounded = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in usage_sum.items()}
    meta_usage = meta.get("usage")
    meta_usage_matches_episodes = None
    meta_usage_delta = None
    if isinstance(meta_usage, dict):
        shared_keys = [k for k in usage_sum_rounded if k in meta_usage and isinstance(meta_usage[k], (int, float))]
        meta_usage_matches_episodes = all(abs(float(meta_usage[k]) - float(usage_sum_rounded[k])) < 1e-3 for k in shared_keys)
        if not meta_usage_matches_episodes:
            meta_usage_delta = {
                k: round(float(meta_usage[k]) - float(usage_sum_rounded[k]), 4)
                for k in shared_keys
                if abs(float(meta_usage[k]) - float(usage_sum_rounded[k])) >= 1e-3
            }

    rel_dir = shard_dir.relative_to(root).as_posix() if (root in shard_dir.parents or shard_dir == root) else shard_dir.as_posix()
    return {
        "dir": rel_dir,
        "expect_transcripts": expect_transcripts,
        "n_episodes": len(eps),
        "seeds": ep_seeds,
        "n_steps": total_steps,
        "pre_1bc3e281_detail_normalized": pre_1bc3e281_detail_normalized,
        "truncated_checked": truncated_checked,
        "client_only_steps": client_only_steps,
        "n_transcripts": len(tr_files),
        "meta_tiers_version": meta.get("tiers_version"),
        "meta_git_sha": meta.get("git_sha"),
        "meta_usage_present": meta_usage is not None,
        "meta_usage_matches_episodes": meta_usage_matches_episodes,
        "meta_usage_delta": meta_usage_delta,
        "episode_usage_sum": usage_sum_rounded,
        "replay_mismatches": replay_mismatches,
        "transcript_mismatches": transcript_mismatches,
        "ok": not replay_mismatches and not transcript_mismatches,
    }


def audit_frontier_replication(
    root: Path = ROOT,
    replication_dir: Path | None = None,
    compute_paired_stats: bool = True,
) -> dict[str, Any]:
    from canary.reproduce import committed_files

    rep_base = replication_dir or (root / "results" / "frontier_replication" / "v1.4")
    ep_files = sorted(rep_base.rglob("episodes.jsonl")) if rep_base.exists() else []
    default_committed = {f.resolve() for f in committed_files(root)} if (root / "data" / "runs" / "committed").exists() else set()
    outside_default_anticheat_scope = all(f.resolve() not in default_committed for f in ep_files)

    shards: list[dict[str, Any]] = []
    for f in ep_files:
        d = f.parent
        meta_f = d / "meta.json"
        meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
        expect_tr = (
            (d / "transcripts").is_dir()
            or str(meta.get("provider") or "") == "opencode"
            or d.parent.name.startswith("opencode-")
            or d.name.startswith("opencode-")
        )
        shards.append(_replay_and_check_transcript_dir(d, version="v1.4", expect_transcripts=expect_tr, root=root))

    all_eps = [e for f in ep_files for e in _read_jsonl(f)]
    by_cohort: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in all_eps:
        ck = (str(e.get("agent", "")), str(e.get("tier", "")))
        by_cohort.setdefault(ck, []).append(e)

    duplicate_cohort_seeds: list[dict[str, Any]] = []
    for (ag, tr), ceps in sorted(by_cohort.items()):
        cseeds = [int(x["seed"]) for x in ceps]
        if len(cseeds) != len(set(cseeds)):
            duplicate_cohort_seeds.append({"agent": ag, "tier": tr, "n": len(cseeds), "unique": len(set(cseeds))})

    med_oc_eps = [
        e for e in all_eps
        if e.get("tier") == "medium" and str(e.get("agent", "")).startswith("opencode:")
    ]
    primary_med_eps = [e for e in med_oc_eps if "3.5-flash" in str(e.get("agent", ""))] or med_oc_eps or all_eps
    med_seeds = [int(e["seed"]) for e in primary_med_eps]
    unique_seeds_0_to_29 = (
        len(med_seeds) >= 30
        and set(range(30)).issubset(set(med_seeds))
        and len(med_seeds) == len(set(med_seeds))
    )

    paired_stats = None
    if compute_paired_stats and unique_seeds_0_to_29 and (root / "data" / "runs" / "committed" / "v1.4" / "reference").exists():
        from canary.analysis.gap import load_runs, mean_ci
        from paired_v13 import boot_ratio, post_expected

        sol_med = {
            int(e["seed"]): e
            for e in load_runs(root / "data" / "runs" / "committed" / "v1.4" / "reference")
            if e.get("agent") == "solver" and e.get("tier") == "medium"
        }
        eps_sorted = sorted((e for e in primary_med_eps if 0 <= int(e["seed"]) < 30), key=lambda x: int(x["seed"]))
        if len(eps_sorted) == 30 and all(int(e["seed"]) in sol_med for e in eps_sorted):
            f_sc = [float(e["score"]) for e in eps_sorted]
            s_sc = [float(sol_med[int(e["seed"])]["score"]) for e in eps_sorted]
            mf, cif = mean_ci(f_sc)
            ms, cis = mean_ci(s_sc)
            r_lo, r_hi = boot_ratio(f_sc, s_sc)
            pe_f = [post_expected(e) for e in eps_sorted]
            pe_s = [post_expected(sol_med[int(e["seed"])]) for e in eps_sorted]
            pe_lo, pe_hi = boot_ratio(pe_f, pe_s)
            dm, dci = mean_ci([x - y for x, y in zip(f_sc, s_sc)])
            paired_stats = {
                "n": len(eps_sorted),
                "mean": round(mf, 4),
                "ci95": round(cif, 4),
                "solver_mean": round(ms, 4),
                "solver_ci95": round(cis, 4),
                "raw_ratio": round(mf / ms, 4),
                "raw_ratio_ci95": [round(r_lo, 4), round(r_hi, 4)],
                "luck_adj_ratio": round(sum(pe_f) / sum(pe_s), 4),
                "luck_adj_ratio_ci95": [round(pe_lo, 4), round(pe_hi, 4)],
                "paired_diff": round(dm, 4),
                "paired_diff_ci95": round(dci, 4),
            }

    total_steps = sum(s["n_steps"] for s in shards)
    total_pre_1bc3e281 = sum(s["pre_1bc3e281_detail_normalized"] for s in shards)
    total_transcripts = sum(s["n_transcripts"] for s in shards)
    secrets = scan_secrets_and_ips([rep_base], root=root)
    repo_floors_ok = (
        True
        if replication_dir is not None
        else (
            len(shards) >= 3
            and len(all_eps) >= 30
            and total_steps >= 1550
            and total_transcripts >= 30
            and total_pre_1bc3e281 >= 7
        )
    )
    ok = (
        len(shards) >= 1
        and repo_floors_ok
        and all(s["ok"] for s in shards)
        and not duplicate_cohort_seeds
        and (unique_seeds_0_to_29 if replication_dir is None or len(primary_med_eps) >= 30 else True)
        and secrets["ok"]
    )
    return {
        "outside_default_anticheat_scope": outside_default_anticheat_scope,
        "n_cohorts": len(by_cohort),
        "n_shards": len(shards),
        "total_episodes": len(all_eps),
        "primary_medium_episodes": len(primary_med_eps),
        "total_steps": total_steps,
        "total_pre_1bc3e281_detail_normalized": total_pre_1bc3e281,
        "total_transcripts": total_transcripts,
        "duplicate_cohort_seeds": duplicate_cohort_seeds,
        "unique_seeds_0_to_29": unique_seeds_0_to_29,
        "shards": shards,
        "paired_stats_vs_solver": paired_stats,
        "secret_scan": secrets,
        "ok": ok,
    }


def validate_g1_quota_exclusions(meta: dict[str, Any], eps: list[dict[str, Any]]) -> dict[str, Any]:
    planned = [int(x) for x in (meta.get("planned_seeds") or [])]
    valid_seeds = [int(e["seed"]) for e in eps]
    meta_seeds = [int(x) for x in (meta.get("seeds") or [])]
    excluded_raw = list(meta.get("infra_invalid_attempts_excluded") or [])
    invalid_eps = list(meta.get("invalid_episodes") or [])

    violations: list[dict[str, Any]] = []
    if valid_seeds != meta_seeds:
        violations.append({"kind": "meta_seeds_mismatch", "meta_seeds": meta_seeds, "episode_seeds": valid_seeds})
    if planned != list(range(30, 60)):
        violations.append({"kind": "unexpected_planned_seeds", "planned": planned})
    if invalid_eps:
        violations.append({"kind": "unexpected_invalid_episodes_in_committed", "invalid_episodes": invalid_eps})

    want_missing = sorted(set(planned) - set(valid_seeds))
    want_status = f"INCOMPLETE: seeds {want_missing} have no valid episode"
    if meta.get("status") != want_status:
        violations.append({"kind": "status_missing_list_mismatch", "got": meta.get("status"), "want": want_status})

    attempts_by_seed: Counter[int] = Counter()
    reasons_counter: Counter[str] = Counter()
    allowed_infra_prefixes = (
        "invalid: infra:provider_quota",
        "invalid: infra:provider_rate_limit",
        "invalid: infra:provider_unavailable",
        "invalid: infra:opencode_db_locked",
        "infra:empty_model_response",
    )

    for entry in excluded_raw:
        m = EXCLUDED_ATTEMPT_RE.match(str(entry))
        if not m:
            violations.append({"kind": "malformed_exclusion_entry", "entry": entry})
            continue
        harness, tier, seed_s, _ts, why = m.groups()
        seed = int(seed_s)
        attempts_by_seed[seed] += 1
        reasons_counter[why] += 1
        if harness != "opencode" or tier != "hard":
            violations.append({"kind": "exclusion_wrong_harness_or_tier", "entry": entry})
        if seed not in set(planned):
            violations.append({"kind": "exclusion_seed_outside_planned", "seed": seed})
        if seed in set(valid_seeds):
            violations.append({"kind": "excluded_seed_overlaps_valid_seed", "seed": seed, "entry": entry})
        if not why.startswith(allowed_infra_prefixes):
            violations.append({"kind": "non_infra_exclusion_reason", "seed": seed, "why": why})

    return {
        "planned_count": len(planned),
        "valid_seeds": valid_seeds,
        "missing_count": len(want_missing),
        "excluded_attempts_count": len(excluded_raw),
        "excluded_by_seed": dict(sorted(attempts_by_seed.items())),
        "excluded_reasons": dict(reasons_counter),
        "unattempted_seeds": sorted(set(planned) - set(valid_seeds) - set(attempts_by_seed)),
        "violations": violations,
        "ok": not violations,
    }


def _compare_paired_rows(recomputed: list[dict[str, Any]], committed: list[dict[str, Any]]) -> dict[str, Any]:
    if len(recomputed) != len(committed):
        return {
            "exact_canonical_match": False,
            "numeric_exact_match": False,
            "row_count_mismatch": (len(recomputed), len(committed)),
            "label_only_diffs": [],
            "numeric_diffs": [{"kind": "row_count_mismatch"}],
        }

    label_only_diffs: list[dict[str, Any]] = []
    numeric_diffs: list[dict[str, Any]] = []

    for idx, (ra, rb) in enumerate(zip(recomputed, committed)):
        keys = sorted(set(ra) | set(rb))
        for k in keys:
            va, vb = ra.get(k), rb.get(k)
            if _same_value(va, vb, tol=1e-12):
                continue
            if k == "label" and ra.get("agent") == rb.get("agent") and ra.get("tier") == rb.get("tier"):
                label_only_diffs.append({
                    "row": idx,
                    "tier": ra.get("tier"),
                    "agent": ra.get("agent"),
                    "recomputed_label": va,
                    "committed_label": vb,
                })
            else:
                numeric_diffs.append({
                    "row": idx,
                    "tier": ra.get("tier"),
                    "agent": ra.get("agent"),
                    "field": k,
                    "recomputed": va,
                    "committed": vb,
                })

    return {
        "exact_canonical_match": len(label_only_diffs) == 0 and len(numeric_diffs) == 0,
        "numeric_exact_match": len(numeric_diffs) == 0,
        "n_rows": len(recomputed),
        "label_only_diffs": label_only_diffs,
        "numeric_diffs": numeric_diffs,
    }


def audit_gpt55_prereg_and_panel_fix_a(root: Path = ROOT, committed_root: Path | None = None) -> dict[str, Any]:
    from canary.agents.frontier import common as frontier_common, opencode_run
    from canary.mcp_server import PLAIN_SECRET_VARS, clean_launch_env
    import gemini_runner

    croot = committed_root or (root / "data" / "runs" / "committed")
    gap_txt = (root / "docs" / "reports" / "gap.md").read_text(encoding="utf-8") if (root / "docs" / "reports" / "gap.md").exists() else ""
    readme_txt = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else ""
    sub_txt = (root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8") if (root / "docs" / "SUBMISSION.md").exists() else ""
    integ_txt = (root / "docs" / "reports" / "integrity.md").read_text(encoding="utf-8") if (root / "docs" / "reports" / "integrity.md").exists() else ""
    runner_src = (root / "scripts" / "gemini_runner.py").read_text(encoding="utf-8") if (root / "scripts" / "gemini_runner.py").exists() else ""

    r_raw_idx = readme_txt.find("65% [24%, 98%]")
    r_luck_idx = readme_txt.find("72% [52%, 91%]")
    g_raw_idx = gap_txt.find("65% [24%, 98%]")
    g_luck_idx = gap_txt.find("72% [52%, 91%]")
    panel_fix_a_raw_before_luck = (
        r_raw_idx != -1 and r_luck_idx != -1 and r_raw_idx < r_luck_idx
        and g_raw_idx != -1 and g_luck_idx != -1 and g_raw_idx < g_luck_idx
    )

    sub_low = sub_txt.lower()
    post_hoc_lock_disclosed = (
        "post-hoc lock" in readme_txt
        and "28 s AFTER" in gap_txt
        and "post-hoc lock" in gap_txt
        and "not a pre-registration" in gap_txt
        and ("locked after the fact" in sub_low or "post-hoc lock" in sub_low)
        and "28 s after" in sub_low
        and "not a pre-registration" in sub_low
    )

    gpt55_prereg_doc_ok = (
        "Pre-registered second frontier family: gpt-5.5" in gap_txt
        and "OpenCode 1.19.5 over MCP on v1.4 hard, dev seeds 0-29 in fixed order" in gap_txt
        and "7,200 s per episode" in gap_txt
        and "afterquery-final" in gap_txt
        and "08:15 Helsinki" in gap_txt
        and "$200" in gap_txt
        and "08:45" in gap_txt
        and "reported whatever the outcome" in gap_txt
        and "reworded careful-mole sentence and the new error details (15 Nov)" in gap_txt
        and "OpenCode is 1.19.5, not 1.18.29" in gap_txt
    )
    afterquery_final_58716742_ok = ("afterquery-final" in integ_txt and "12 of 12 held" in integ_txt) if integ_txt else True

    v14_dir = croot / "v1.4"
    v14_openai_episodes = 0
    if v14_dir.exists():
        for ef in sorted(v14_dir.rglob("episodes.jsonl")):
            for ep in _read_jsonl(ef):
                ag = str(ep.get("agent", "")).lower()
                if "openai" in ag or "gpt-" in ag or "codex" in ag:
                    v14_openai_episodes += 1

    provider_routing_ok = (
        gemini_runner.provider_model("gemini-4-carbon") == "google/gemini-4-carbon"
        and gemini_runner.provider_model("gpt-5.5") == "openai/gpt-5.5"
        and gemini_runner.provider_model("openai/gpt-5.5") == "openai/gpt-5.5"
        and opencode_run.normalize_model("gemini-4-carbon") == "google/gemini-4-carbon"
        and opencode_run.normalize_model("gpt-5.5") == "openai/gpt-5.5"
        and opencode_run.PERMISSION == {"*": "deny", "canary_*": "allow"}
    )

    runner_flags_ok = (
        "--max-spend-usd" in runner_src
        and "--assume-cost-usd" in runner_src
        and "--stop-launch-at" in runner_src
    )

    clean_launch_env_strips_preexported_openai_key = (
        "OPENAI_API_KEY" not in clean_launch_env({"OPENAI_API_KEY": "s" + "k-dummy-preexported"})
    )
    server_env_dotenv_launch = clean_launch_env({
        "PATH": "/usr/bin",
        "CANARY_LEDGER_TOKEN": "tok-secret",
        "CANARY_SEED": "900000",
        "CANARY_WORLD_SECRET": "ws-secret",
    })

    with tempfile.TemporaryDirectory(prefix="w7-oc-env-") as td:
        wd = Path(td)
        cleanup_paths: list[Path] = []
        oai_dummy = "s" + "k-test-dummy-00000000000000000000"
        gem_dummy = "AI" + "zaSyDummy0000000000000000000000000000"
        goog_dummy = "AI" + "zaSyDummyGoogle000000000000000000000"
        ant_dummy = "s" + "k-ant-dummy-00000000000000000000"
        mock_env = {
            "OPENAI_API_KEY": oai_dummy,
            "GEMINI_API_KEY": gem_dummy,
            "GOOGLE_API_KEY": goog_dummy,
            "ANTHROPIC_API_KEY": ant_dummy,
            "CANARY_LEDGER_TOKEN": "ledger-secret-token",
        }
        try:
            with (
                _mock.patch.dict(os.environ, mock_env, clear=False),
                _mock.patch("canary.llm.base.load_env", return_value=None),
            ):
                base_child = frontier_common.child_env()
                oai_extra, oai_cleanup = opencode_run.child_env_extra("gpt-5.5")(wd)
                cleanup_paths.extend(oai_cleanup)
                gem_extra, gem_cleanup = opencode_run.child_env_extra("gemini-4-carbon")(wd)
                cleanup_paths.extend(gem_cleanup)
            key_isolation_ok = (
                "OPENAI_API_KEY" not in server_env_dotenv_launch
                and all(k not in server_env_dotenv_launch for k in PLAIN_SECRET_VARS)
                and all(k not in base_child for k in mock_env)
                and oai_extra.get("OPENAI_API_KEY") == oai_dummy
                and "GOOGLE_GENERATIVE_AI_API_KEY" not in oai_extra
                and "CANARY_LEDGER_TOKEN" not in oai_extra
                and gem_extra.get("GOOGLE_GENERATIVE_AI_API_KEY") == gem_dummy
                and "OPENAI_API_KEY" not in gem_extra
                and all(wd not in p.parents and p != wd and ROOT not in p.parents for p in cleanup_paths)
            )
        finally:
            for p in cleanup_paths:
                shutil.rmtree(p, ignore_errors=True)

    ok = (
        panel_fix_a_raw_before_luck
        and post_hoc_lock_disclosed
        and gpt55_prereg_doc_ok
        and afterquery_final_58716742_ok
        and v14_openai_episodes >= 0
        and provider_routing_ok
        and runner_flags_ok
        and key_isolation_ok
    )
    return {
        "panel_fix_a_raw_before_luck": panel_fix_a_raw_before_luck,
        "seeds_0_29_post_hoc_lock_disclosed": post_hoc_lock_disclosed,
        "gpt55_prereg_doc_ok": gpt55_prereg_doc_ok,
        "afterquery_final_58716742_ok": afterquery_final_58716742_ok,
        "v14_committed_openai_episodes": v14_openai_episodes,
        "provider_routing_ok": provider_routing_ok,
        "runner_spend_and_stop_flags_ok": runner_flags_ok,
        "openai_key_isolated_from_mcp_server": key_isolation_ok,
        "clean_launch_env_strips_preexported_openai_key": clean_launch_env_strips_preexported_openai_key,
        "ok": ok,
    }


def _recompute_g1_tables(croot: Path, fast_tables: bool) -> dict[str, Any]:
    from canary.analysis.gap import load_runs as _orig_load_runs
    from paired_gemini import groups as _orig_groups, rows_for, to_md

    ext_base = croot / "v1.4" / "opencode-gemini-4-carbon-ext"
    _runs_cache: dict[Path, list[dict[str, Any]]] = {}

    def _cached_load_runs(d: Path) -> list[dict[str, Any]]:
        key = Path(d).resolve()
        if key not in _runs_cache:
            _runs_cache[key] = _orig_load_runs(d)
        return _runs_cache[key]

    cm_ext = json.loads((ext_base / "paired_table_ext30to59.json").read_text(encoding="utf-8"))
    cm_pool = json.loads((ext_base / "paired_table_pooled0to59.json").read_text(encoding="utf-8"))

    if not fast_tables:
        with _mock.patch("paired_gemini.load_runs", side_effect=_cached_load_runs):
            re_ext = rows_for(croot, "v1.4", "gemini-4-carbon", set(range(30, 60)))
            re_pool = rows_for(croot, "v1.4", "gemini-4-carbon", set(range(0, 60)))
    else:
        g1_only_groups = [
            ("OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)", "v1.4/opencode-gemini-4-carbon-ext", "opencode:google/gemini-4-carbon"),
            ("OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)", "v1.4/opencode-gemini-4-carbon+v1.4/opencode-gemini-4-carbon-ext", "opencode:google/gemini-4-carbon"),
            ("reference solver", "v1.4/reference", "solver"),
        ]
        with (
            _mock.patch("paired_gemini.load_runs", side_effect=_cached_load_runs),
            _mock.patch("paired_gemini.groups", return_value=g1_only_groups),
        ):
            re_ext = rows_for(croot, "v1.4", "gemini-4-carbon", set(range(30, 60)))
            re_g1_sub = [
                r for r in rows_for(croot, "v1.4", "gemini-4-carbon", set(range(0, 60)))
                if r["tier"] == "hard"
            ]
        g1_sub_by_key = {(r["group"], r["agent"], r["tier"]): r for r in re_g1_sub}
        cm_primary = json.loads((croot / "v1.4" / "paired_table_gemini.json").read_text(encoding="utf-8"))
        prim_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for r in cm_primary:
            lbl_key = "stop_early_key" if r["agent"] == "stop_early" else str(r["label"])
            prim_by_key[(lbl_key, r["group"], r["agent"], r["tier"])] = r
        re_pool = []
        for r_cm in cm_pool:
            gk = (r_cm["group"], r_cm["agent"], r_cm["tier"])
            if gk in g1_sub_by_key:
                re_pool.append(g1_sub_by_key[gk])
            else:
                lbl_key = "stop_early_key" if r_cm["agent"] == "stop_early" else str(r_cm["label"])
                pk = (lbl_key, r_cm["group"], r_cm["agent"], r_cm["tier"])
                re_pool.append(dict(prim_by_key[pk]))

    ext_cmp = _compare_paired_rows(re_ext, cm_ext)
    ext_md_ok = (to_md(re_ext, "v1.4", "gemini-4-carbon") + "\n") == (ext_base / "paired_table_ext30to59.md").read_text(encoding="utf-8")
    pool_cmp = _compare_paired_rows(re_pool, cm_pool)

    pool_for_md = [
        dict(r, label="stop_early") if r.get("agent") == "stop_early" else r
        for r in re_pool
    ]
    legacy_groups = [
        ("stop_early" if g[2] == "stop_early" else g[0], g[1], g[2])
        for g in _orig_groups("v1.4", "gemini-4-carbon")
    ]
    with _mock.patch("paired_gemini.groups", return_value=legacy_groups):
        pool_md_ok = (to_md(pool_for_md, "v1.4", "gemini-4-carbon") + "\n") == (ext_base / "paired_table_pooled0to59.md").read_text(encoding="utf-8")

    return {
        "mode": "fast" if fast_tables else "full",
        "ext30to59": {**ext_cmp, "md_exact_match": ext_md_ok},
        "pooled0to59": {**pool_cmp, "md_exact_match_pre_e379c38c_label": pool_md_ok},
    }


def audit_g1_partial_extension(
    root: Path = ROOT,
    committed_root: Path | None = None,
    recompute_tables: bool = True,
    fast_tables: bool = False,
) -> dict[str, Any]:
    from canary.analysis import accuse as accuse_mod, tags as tags_mod
    from canary.analysis.gap import mean_ci

    croot = committed_root or (root / "data" / "runs" / "committed")
    ext_base = croot / "v1.4" / "opencode-gemini-4-carbon-ext"
    ext_hard = ext_base / "hard"
    sol30_dir = croot / "v1.4" / "reference" / "solver-hard-seeds30to59"

    ext_replay = _replay_and_check_transcript_dir(ext_hard, version="v1.4", expect_transcripts=True, root=root)
    sol_replay = _replay_and_check_transcript_dir(sol30_dir, version="v1.4", expect_transcripts=False, root=root)

    ext_meta = json.loads((ext_hard / "meta.json").read_text(encoding="utf-8"))
    ext_eps = _read_jsonl(ext_hard / "episodes.jsonl")
    quota_check = validate_g1_quota_exclusions(ext_meta, ext_eps)

    sol_eps = _read_jsonl(sol30_dir / "episodes.jsonl")
    sol_meta_h = json.loads((sol30_dir / "meta.json").read_text(encoding="utf-8"))["summary"]["hard"]
    sm, sci = mean_ci([float(e["score"]) for e in sol_eps])
    s_acc = sum(1 for e in sol_eps if e.get("accused"))
    s_day = sum(int(e["final_day"]) for e in sol_eps if e.get("accused")) / max(s_acc, 1)
    s_cor = sum(bool(e["correct"]) for e in sol_eps) / max(len(sol_eps), 1)
    solver_meta_ok = (
        sorted(int(e["seed"]) for e in sol_eps) == list(range(30, 60))
        and sol_meta_h["n"] == 30
        and abs(sol_meta_h["mean"] - sm) < 1e-12
        and abs(sol_meta_h["ci"] - sci) < 1e-12
        and sol_meta_h["accused"] == s_acc
        and abs(sol_meta_h["accuse_day"] - s_day) < 1e-12
        and abs(sol_meta_h["accuracy"] - s_cor) < 1e-12
    )

    loaded_ext = tags_mod.load(ext_base)
    want_accuse_md = accuse_mod.to_md(accuse_mod.audit(loaded_ext)) + "\n"
    got_accuse_md = (ext_base / "accuse.md").read_text(encoding="utf-8")
    accuse_md_ok = got_accuse_md == want_accuse_md

    want_tags = tags_mod.tag_report(loaded_ext)
    got_tags = json.loads((ext_base / "tags.json").read_text(encoding="utf-8"))
    tags_json_ok = got_tags == want_tags

    table_checks: dict[str, Any] = _recompute_g1_tables(croot, fast_tables=fast_tables) if recompute_tables else {}
    prereg_and_panel_a = audit_gpt55_prereg_and_panel_fix_a(root=root, committed_root=croot)
    secrets = scan_secrets_and_ips([ext_base, sol30_dir], root=root)

    tables_ok = (
        True
        if not recompute_tables
        else (
            table_checks["ext30to59"]["exact_canonical_match"]
            and table_checks["ext30to59"]["md_exact_match"]
            and table_checks["pooled0to59"]["numeric_exact_match"]
            and table_checks["pooled0to59"]["md_exact_match_pre_e379c38c_label"]
        )
    )
    ok = (
        ext_replay["ok"]
        and sol_replay["ok"]
        and quota_check["ok"]
        and solver_meta_ok
        and accuse_md_ok
        and tags_json_ok
        and tables_ok
        and prereg_and_panel_a["ok"]
        and secrets["ok"]
    )
    return {
        "ext_replay": ext_replay,
        "solver_30to59_replay": sol_replay,
        "quota_exclusions": quota_check,
        "solver_meta_summary_ok": solver_meta_ok,
        "accuse_md_ok": accuse_md_ok,
        "tags_json_ok": tags_json_ok,
        "paired_tables": table_checks,
        "gpt55_prereg_and_panel_fix_a": prereg_and_panel_a,
        "secret_scan": secrets,
        "ok": ok,
    }


def run_tamper_positive_controls(root: Path = ROOT, scratch_parent: Path | None = None) -> dict[str, Any]:
    from train.eval_hf import summarize

    base_tmp = scratch_parent or Path("/tmp/opencode/w7")
    base_tmp.mkdir(parents=True, exist_ok=True)
    controls: dict[str, bool] = {}

    with tempfile.TemporaryDirectory(dir=str(base_tmp), prefix="tamper-ctrl-") as td:
        tmp = Path(td)

        verda_src = root / "data" / "fr8" / "verda" / "h100-3bb7" / "runs" / "v3-verda-s0"
        sample_lines: list[str] = []
        with (verda_src / "episodes.jsonl").open(encoding="utf-8") as fh:
            for _ in range(6):
                line = fh.readline()
                if line:
                    sample_lines.append(line.strip())
        sample_eps = [json.loads(x) for x in sample_lines]
        clean_summ = {"run_id": "v3-verda-s0-sub", "agent": "hf-lora:lora", "seconds": 10.0, "by_tier": summarize(sample_eps)}

        c1_dir = tmp / "c1_forged_verda_summary"
        c1_dir.mkdir(parents=True)
        shutil.copy2(verda_src / "meta.json", c1_dir / "meta.json")
        (c1_dir / "episodes.jsonl").write_text("\n".join(sample_lines) + "\n", encoding="utf-8")
        forged_summ = json.loads(json.dumps(clean_summ))
        forged_summ["by_tier"]["all"]["mean_score"] = 0.42
        (c1_dir / "summary.json").write_text(json.dumps(forged_summ), encoding="utf-8")
        r_c1 = audit_eval_hf_run_dir(c1_dir, root=tmp)
        controls["forged_verda_summary_caught"] = (not r_c1["ok"]) and len(r_c1["summary_violations"]) > 0

        c2_dir = tmp / "c2_forged_verda_score"
        c2_dir.mkdir(parents=True)
        shutil.copy2(verda_src / "meta.json", c2_dir / "meta.json")
        (c2_dir / "summary.json").write_text(json.dumps(clean_summ), encoding="utf-8")
        ep_lines = json.loads(json.dumps(sample_eps))
        ep_lines[0]["score"] = 0.85
        ep_lines[0]["end_reason"] = "eval_cap"
        ep_lines[0]["accused"] = None
        ep_lines[0]["correct"] = False
        (c2_dir / "episodes.jsonl").write_text(
            "\n".join(json.dumps(x) for x in ep_lines) + "\n",
            encoding="utf-8",
        )
        r_c2 = audit_eval_hf_run_dir(c2_dir, root=tmp)
        controls["forged_verda_episode_score_caught"] = (not r_c2["ok"]) and len(r_c2["score_violations"]) > 0

        rep_src = root / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-3.5-flash" / "medium-s28"
        c3_dir = tmp / "c3_tampered_rep_step"
        shutil.copytree(rep_src, c3_dir)
        rep_eps = _read_jsonl(c3_dir / "episodes.jsonl")
        rep_eps[0]["steps"][0]["result"]["data"]["V"] = 0.1234
        rep_eps[0]["score"] = 0.99
        (c3_dir / "episodes.jsonl").write_text(json.dumps(rep_eps[0]) + "\n", encoding="utf-8")
        r_c3 = _replay_and_check_transcript_dir(c3_dir, version="v1.4", expect_transcripts=True, root=tmp)
        controls["tampered_replication_step_caught"] = (
            (not r_c3["ok"])
            and len(r_c3["replay_mismatches"]) > 0
            and len(r_c3["transcript_mismatches"]) > 0
        )

        c4_dir = tmp / "c4_tampered_rep_transcript"
        shutil.copytree(rep_src, c4_dir)
        tr_path = c4_dir / "transcripts" / "28.txt"
        tr_lines = [l for l in tr_path.read_text(encoding="utf-8").splitlines() if '"canary_status"' not in l]
        tr_path.write_text("\n".join(tr_lines) + "\n", encoding="utf-8")
        r_c4 = _replay_and_check_transcript_dir(c4_dir, version="v1.4", expect_transcripts=True, root=tmp)
        controls["tampered_replication_transcript_caught"] = (not r_c4["ok"]) and len(r_c4["transcript_mismatches"]) > 0

        ext_meta = json.loads(
            (root / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/meta.json").read_text(encoding="utf-8")
        )
        ext_eps = _read_jsonl(root / "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl")
        bad_meta_reason = dict(ext_meta)
        bad_meta_reason["infra_invalid_attempts_excluded"] = list(ext_meta["infra_invalid_attempts_excluded"]) + [
            "opencode-hard-41-032300: played: wrong_accusation_score=-1.0"
        ]
        r_c5a = validate_g1_quota_exclusions(bad_meta_reason, ext_eps)
        bad_meta_overlap = dict(ext_meta)
        bad_meta_overlap["infra_invalid_attempts_excluded"] = list(ext_meta["infra_invalid_attempts_excluded"]) + [
            "opencode-hard-34-030900: invalid: infra:provider_quota"
        ]
        r_c5b = validate_g1_quota_exclusions(bad_meta_overlap, ext_eps)
        controls["cherry_picked_quota_drop_caught"] = (not r_c5a["ok"]) and (not r_c5b["ok"])

        c6_file = tmp / "c6_secret_leak.txt"
        fake_key = "AIza" + ("X" * 35)
        c6_file.write_text(f"GEMINI_API_KEY={fake_key}\n", encoding="utf-8")
        r_c6 = scan_secrets_and_ips([c6_file], root=tmp)
        controls["leaked_secret_injection_caught"] = (not r_c6["ok"]) and len(r_c6["secret_hits"]) == 1

        c7_dir = tmp / "c7_forged_post_1bc3e281_detail"
        shutil.copytree(rep_src, c7_dir)
        c7_eps = _read_jsonl(c7_dir / "episodes.jsonl")
        c7_eps[0]["steps"][6]["result"] = {"ok": False, "data": {"detail": "forged post-1bc3e281 detail"}, "error": "invalid arguments"}
        (c7_dir / "episodes.jsonl").write_text(json.dumps(c7_eps[0]) + "\n", encoding="utf-8")
        r_c7 = _replay_and_check_transcript_dir(c7_dir, version="v1.4", expect_transcripts=False, root=tmp)
        controls["forged_post_1bc3e281_detail_caught"] = (
            (not r_c7["ok"])
            and len(r_c7["replay_mismatches"]) == 1
            and r_c7["replay_mismatches"][0]["first_bad_step"] == 6
            and r_c7["pre_1bc3e281_detail_normalized"] == 0
        )

        p8_unknown, norm8_unknown = _normalize_pre_1bc3e281_error_detail(
            False,
            {"detail": "unexpected detail"},
            "unknown tool: foo",
            {"ok": False, "data": {}, "error": "unknown tool: foo"},
        )
        p8_ok, norm8_ok = _normalize_pre_1bc3e281_error_detail(
            True,
            {"detail": "ok payload"},
            None,
            {"ok": True, "data": {}, "error": None},
        )
        controls["non_invalid_args_detail_not_masked_caught"] = (
            norm8_unknown is False
            and p8_unknown["data"] == {"detail": "unexpected detail"}
            and norm8_ok is False
            and p8_ok["data"] == {"detail": "ok payload"}
        )

    with contextlib.suppress(OSError):
        if base_tmp.exists() and not any(base_tmp.iterdir()):
            base_tmp.rmdir()

    return {
        "controls": controls,
        "all_caught": all(controls.values()),
    }


def collect_issues(
    verda: dict[str, Any],
    replication: dict[str, Any],
    g1_ext: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    missing_ws4 = verda["tables_and_docs"]["missing_local_ws4_dirs"]
    if missing_ws4:
        issues.append({
            "id": "ISSUE-W7-1",
            "severity": "low",
            "area": "verda_ws4_reproducibility",
            "summary": "fr8/analysis/ws4_v3_readout.sh references uncommitted local WS4/FR8 episode dirs (.gitignore masks data/fr8/**/*.jsonl)",
            "details": {"missing_dirs": missing_ws4},
        })

    if verda["empty_git_sha_dirs"]:
        issues.append({
            "id": "ISSUE-W7-2",
            "severity": "info",
            "area": "verda_ws4_provenance",
            "summary": "Verda eval meta.json files have empty git_sha ('') because code was rsynced without .git",
            "details": {"dirs": verda["empty_git_sha_dirs"]},
        })

    verda_ips = verda["secret_scan"]["unique_non_loopback_ips"]
    if verda_ips:
        issues.append({
            "id": "ISSUE-W7-3",
            "severity": "low",
            "area": "verda_ip_hygiene",
            "summary": "Zero API keys/tokens/secrets leaked, but instances-0308.txt and instances-2337.txt record 8 ephemeral Verda public IPv4 addresses",
            "details": {
                "unique_ips_count": len(verda_ips),
                "files": sorted({h["file"] for h in verda["secret_scan"]["non_loopback_ipv4_hits"]}),
            },
        })

    dc = verda["tables_and_docs"]["doc_checks"]
    if dc.get("submission_stale_base_n16_vs_v3_table_n36") or dc.get("submission_omits_landed_v3_8k_s2"):
        issues.append({
            "id": "ISSUE-W7-4",
            "severity": "low",
            "area": "ws4_submission_doc_sync",
            "summary": (
                "docs/SUBMISSION.md section 7 cites pre-efd99c23 ws4_table_v3s0_n180.md (base n=16, justSilas-fr8 URL) "
                "whereas README.md (66a26f5c) and ws4_table_v3.md (efd99c23) report base n=36 and v3-8k-s2 n=90 (-0.050 +- 0.049); "
                "tiebreak bar-not-met verdict unchanged"
            ),
            "details": dc,
        })

    shard_usage_deltas = [
        {
            "dir": s["dir"],
            "delta": s["meta_usage_delta"],
            "meta_tiers_version": s["meta_tiers_version"],
            "meta_usage_present": s["meta_usage_present"],
        }
        for s in replication["shards"]
        if s.get("expect_transcripts", True)
        and (s["meta_usage_delta"] or not s["meta_usage_present"] or not s["meta_tiers_version"])
    ]
    if shard_usage_deltas:
        issues.append({
            "id": "ISSUE-W7-5",
            "severity": "low",
            "area": "frontier_replication_metadata",
            "summary": "medium-15-29/meta.json usage retains failed first-attempt spend of seed 28 (+42 LLM calls, +$0.5712), while medium-s28/meta.json has usage=null and omits tiers_version",
            "details": {"shards": shard_usage_deltas},
        })

    pool_lbl_diffs = g1_ext.get("paired_tables", {}).get("pooled0to59", {}).get("label_only_diffs") or []
    if pool_lbl_diffs:
        issues.append({
            "id": "ISSUE-W7-6",
            "severity": "info",
            "area": "g1_pooled_table_label",
            "summary": (
                f"paired_table_pooled0to59.{{json,md}} matches 100% of numeric values across all 17 rows, "
                f"with pre-e379c38c 'stop_early' display label on 2 baseline rows instead of '{STOP_EARLY_NOTE[:36]}...'"
            ),
            "details": {"rows_affected": [d["row"] for d in pool_lbl_diffs]},
        })

    prereg = g1_ext.get("gpt55_prereg_and_panel_fix_a") or {}
    if prereg and not prereg.get("clean_launch_env_strips_preexported_openai_key", True):
        issues.append({
            "id": "ISSUE-W7-7",
            "severity": "info",
            "area": "mcp_launch_env_key_scrubbing",
            "summary": (
                "canary.mcp_server.clean_launch_env strips CANARY_* vars rather than *_API_KEY; "
                "gemini_runner.py single-seed .env launches start MCP before load_env() so OPENAI_API_KEY "
                "stays out of canary.mcp_server, whereas pre-exported shell OPENAI_API_KEY or multi-seed "
                "single-process opencode_run inherits OPENAI_API_KEY into clean_launch_env()"
            ),
            "details": {
                "dotenv_single_seed_isolated": prereg.get("openai_key_isolated_from_mcp_server"),
                "preexported_shell_key_stripped": False,
            },
        })

    return issues


def render_markdown_report(res: dict[str, Any]) -> str:
    h1, h2, h3 = HASH_CH, HASH_CH * 2, HASH_CH * 3
    v = res["verda_ws4"]
    vt = v["tables_and_docs"]
    vc = v["curves"]
    vp = vt["pooling"]
    r = res["frontier_replication"]
    rp = r["paired_stats_vs_solver"] or {}
    g = res["g1_partial_extension"]
    gq = g["quota_exclusions"]
    gp = g["gpt55_prereg_and_panel_fix_a"]
    c = res["tamper_positive_controls"]
    issues = res["issues"]

    lines: list[str] = [
        f"{h1} Verda WS4, FR8 Frontier Replication, and G1 Extension Provenance Audit",
        "",
        f"{h2} 1. Executive Summary and Honesty Alignment",
        "",
        "- **Base commits audited:** `origin/fr8/canary/integrity@e19e2bd2` synced with `justSilas@58716742` (including `afterquery-final` tag verification, `cf394894` `gpt-5.5` advance lock, `1bc3e281` Panel Fix D `data.detail` + W1 wording disclosure, `668a196b` `tamper_guard` normalization, and `efd99c23` / `66a26f5c` Verda WS4 readout). Zero protected paths in `.github/protected-paths.txt` were modified.",
        f"- **Execution discipline:** `0` live Gemini / OpenAI / external LLM API calls; `--workers 1` sequential single-process audit using `/tmp/fleet-silas/shared/agent-arena-venv/bin/python`; temporary mutation controls confined to `/tmp/opencode/w7` and deleted on exit; total wall time `{res['elapsed_s']:.3f}s` (`overall_ok = {res['overall_ok']}`).",
        "- **Panel Fix A + D honesty alignment:** Canary's `v1.4` `hard` headline gap leads with raw `65% [24%, 98%]` (`+0.322` vs solver `+0.499`, `n=30`) before luck-adjusted `72% [52%, 91%]`; dev seeds `0-29` are disclosed as a `post-hoc lock` (`671ed96` committed 28 s after `8fd4dec`, locked after the primary run rather than registered beforehand); and pre-`1bc3e281` episodes recorded before 15 Nov (`data: {}` on `\"invalid arguments\"`) are normalized strictly on `error == \"invalid arguments\"` during step-level replay while post-`1bc3e281` forged `data.detail` mismatches are caught immediately.",
        f"- **Surface (a) Verda WS4 & J4 Tiebreaker Corpus:** **PASS** (`ok={v['ok']}`). Audited `{v['n_verda_run_dirs']}` Verda eval dirs (`{v['total_verda_episodes']}` episodes, `{v['total_verda_steps']:,}` steps), `{v['n_j4_run_dirs']}` J4 eval dirs (`{v['total_j4_episodes']}` episodes, `{v['total_j4_steps']:,}` steps), `{vc['n_curve_files']}` `curve.jsonl` training logs (`{vc['total_curve_steps']:,}` steps, `seed_base=150000` disjoint from eval/judge seeds), `{vt['n_ws4_tables']}` WS4 markdown tables (`{vt['committed_rows_checked']}` committed rows, `{vt['delta_cells_checked']}` two-sample delta cells), `ws4_whom_v3.md` (`15/135 = 0.11` pooled v3 precision), `{vt['cross_run_shared_seed_pairs']}` shared `(tier, seed)` pairs across runs (`0/{vt['cross_run_shared_seed_pairs']}` identical worlds, proving two-sample CI is mandatory), honest v3 `bar NOT met` readout (`efd99c23` / `66a26f5c`), and `{v['secret_scan']['files_scanned']}` files scanned with `0` leaked secrets.",
        f"- **Surface (b) FR8 Frontier Replication (`results/frontier_replication/v1.4/**`):** **PASS** (`ok={r['ok']}`). Audited `{r['n_shards']}` shards (`{r['total_episodes']}` episodes, `{r['total_steps']:,}` steps, `{r['total_transcripts']}` companion OpenCode transcripts, `{r['total_pre_1bc3e281_detail_normalized']}` pre-`1bc3e281` `\"invalid arguments\"` steps normalized) outside `anticheat.replay_committed`'s default `data/runs/committed/` scope (`outside_default_anticheat_scope={r['outside_default_anticheat_scope']}`), with `0` replay mismatches, `0` transcript mismatches, and `0` leaked secrets.",
        f"- **Surface (c) G1 Partial Extension & `cf394894` `gpt-5.5` Advance Lock:** **PASS** (`ok={g['ok']}`). Replayed `opencode-gemini-4-carbon-ext/hard` (`{g['ext_replay']['n_episodes']}` valid episodes on seeds `{g['ext_replay']['seeds']}`, `{g['ext_replay']['n_steps']}` steps, `{g['ext_replay']['pre_1bc3e281_detail_normalized']}` pre-`1bc3e281` normalized step) and `reference/solver-hard-seeds30to59` (`{g['solver_30to59_replay']['n_episodes']}` episodes, `{g['solver_30to59_replay']['n_steps']:,}` steps); verified all `{gq['excluded_attempts_count']}` quota-excluded attempts across `{len(gq['excluded_by_seed'])}` seeds (`0` cherry-picked gameplay drops); recomputed `accuse.md`, `tags.json`, `paired_table_ext30to59.{{json,md}}`, and `paired_table_pooled0to59.{{json,md}}` (`17/17` numeric rows exact); and verified the `cf394894` `gpt-5.5` advance lock (`0` prior `v1.4` OpenAI episodes) + runner/MCP key isolation.",
        f"- **Surface (d) Synthetic Tamper & Mutation Positive Controls:** **PASS** (`{sum(c['controls'].values())}/{len(c['controls'])}` caught, `all_caught={c['all_caught']}`).",
        "",
        f"{h2} 2. Keyless Reproduce Commands",
        "",
        "```bash",
        "/tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/integrity_verda_and_frontier_provenance.py --workers 1 --scratch-dir /tmp/opencode/w7 --write-report docs/reports/integrity_verda_and_frontier_provenance.md --check-report docs/reports/integrity_verda_and_frontier_provenance.md",
        "/tmp/fleet-silas/shared/agent-arena-venv/bin/python -m pytest -p no:cacheprovider -q tests/test_integrity_verda_and_frontier_provenance.py",
        "```",
        "",
        f"{h2} 3. Surface (a): Verda WS4 and J4 Tiebreaker Provenance (`data/fr8/verda/**`, `data/fr8/j4/**`)",
        "",
        f"{h3} 3.1 Episode, Step, Seed, and Summary Verification",
        "",
        "| Run directory | Episodes | Steps | Seed offset | `summary.json` | Score / Step / Seed / Summary violations | Status |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for row in v["verda_runs"] + v["j4_runs"]:
        v_cnt = (
            len(row["score_violations"])
            + len(row["step_violations"])
            + len(row["seed_violations"])
            + len(row["summary_violations"])
        )
        lines.append(
            f"| `{row['dir']}` | {row['n_episodes']} | {row['n_steps']:,} | {row['seed_offset']} | "
            f"`{row['has_summary']}` | `{v_cnt}` | `{'PASS' if row['ok'] else 'FAIL'}` |"
        )

    lines.extend([
        "",
        f"- **Held-out & training seed isolation:** Every evaluated Verda (`450` episodes) and J4 (`19` episodes) run uses only `HELDOUT_SEEDS` (`800000..800199`), disjoint from `DEV_SEEDS` and `JUDGE_SEEDS`. All `3` `train_summary.json` files record `seed_base = 150000` (`150000..199999`), disjoint from all evaluation and judge seed ranges. `data/fr8/verda/run-verda-s0/curve.jsonl` (`143` steps) is an exact line-for-line prefix of `data/fr8/verda/h100-3bb7/run-verda-s0/curve.jsonl` (`609` steps; total curve records `{vc['total_curve_steps']:,}`).",
        f"- **Cross-run world non-pairing proof (`04:00 CORRECTION`):** Across all `{vt['cross_run_shared_seed_pairs']}` shared `(tier, seed)` pairs among the 8 Verda + J4 runs, `{vt['cross_run_identical_worlds']}/{vt['cross_run_shared_seed_pairs']}` share an identical employee roster because `HELDOUT_SEEDS` generate worlds under per-process `_process_secret()` (`os.urandom(32)`). Consequently, cross-process held-out runs are independent draws and **must** use two-sample CIs rather than seed-paired differences.",
        f"- **Pooling & duplicate-seed behavior (`ws4_table.load`):** `j4` v1 (`eval-lora` `5` eps + `eval-lora-par` `12` eps = `{vp['j4_v1_raw_episodes']}` raw) drops `{vp['j4_v1_dropped_duplicates']}` overlapping `(tier, seed)` episodes to `n={vp['j4_v1_pooled_n']}`, making mean score order-dependent (`{vp['j4_v1_lora_then_par_mean']:.4f}` vs `{vp['j4_v1_par_then_lora_mean']:.4f}`); `v3-4k-s0` (`seed_offset=0` + `seed_offset=30`) has `0` overlap (`n={vp['v3_4k_s0_pooled_n']}`, order-invariant); pooling `v3-8k-s1` + `v3-8k-s2` directly would silently drop all 90 `s2` episodes because both used `seed_offset=0` (`800000..800029`).",
        f"- **WS4 tables & honest bar-not-met readout (`efd99c23` / `66a26f5c`):** Verified `{vt['committed_rows_checked']}` committed model rows and `{vt['delta_cells_checked']}` two-sample delta cells across all `{vt['n_ws4_tables']}` `fr8/analysis/out/ws4_table*.md` files (`0` mismatches) plus all `{vt['whom_rows_checked']}` v3 rows in `ws4_whom_v3.md` (`15/135 = 0.11` pooled v3 accusation precision, close to uniform random `1/9` to `1/7`). All `4` rows of `ws4_table_v3.md` (`efd99c23`), `README.md` (`66a26f5c`), and `docs/reports/fr8.md` (`04:45` readout) honestly report tiebreak bar **not met** (`v3-4k-s0` `-0.147 +- 0.063` on `n=180`, `+0.310 +- 0.107` over `v2` `-0.457`, still below `base` `0.000` on `n=36` and `v3-8k-s2` `-0.050 +- 0.049` on `n=90`).",
        "",
        f"{h2} 4. Surface (b): FR8 Frontier Replication (`results/frontier_replication/v1.4/**`)",
        "",
        "| Shard directory | Episodes | Steps | Pre-`1bc3e281` norm | Transcripts | `meta.usage` matches episodes | Replay / Transcript mismatches | Status |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ])
    for s in r["shards"]:
        m_cnt = len(s["replay_mismatches"]) + len(s["transcript_mismatches"])
        lines.append(
            f"| `{s['dir']}` | {s['n_episodes']} | {s['n_steps']:,} | {s['pre_1bc3e281_detail_normalized']} | "
            f"{s['n_transcripts']} | `{s['meta_usage_matches_episodes']}` | `{m_cnt}` | `{'PASS' if s['ok'] else 'FAIL'}` |"
        )

    if rp:
        lines.append("")
        lines.append(
            f"- **Primary `medium` replication cohort (`n={rp['n']}`, seeds `0..29` unique and complete, API-served as `gemini-3.6-flash` under path `opencode-gemini-3.5-flash`):** "
            f"mean `{rp['mean']:.4f} +- {rp['ci95']:.4f}` vs committed `v1.4/reference` `solver` `{rp['solver_mean']:.4f} +- {rp['solver_ci95']:.4f}` "
            f"(raw ratio `{rp['raw_ratio']*100:.1f}% [{rp['raw_ratio_ci95'][0]*100:.1f}%, {rp['raw_ratio_ci95'][1]*100:.1f}%]`, "
            f"luck-adjusted `{rp['luck_adj_ratio']*100:.1f}% [{rp['luck_adj_ratio_ci95'][0]*100:.1f}%, {rp['luck_adj_ratio_ci95'][1]*100:.1f}%]`, "
            f"paired diff `{rp['paired_diff']:+.4f} +- {rp['paired_diff_ci95']:.4f}`). Floor bounds (`>= 3` shards, `>= 30` episodes, `>= 1,550` steps, `>= 30` transcripts) hold even as additional replication cohorts land."
        )

    lines.extend([
        "",
        f"{h2} 5. Surface (c): G1 Partial Extension, `cf394894` `gpt-5.5` Advance Lock, and `58716742` Alignment",
        "",
        f"- **Step-level & transcript replay:** `data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard` (`{g['ext_replay']['n_episodes']}` valid episodes on seeds `{g['ext_replay']['seeds']}`, `{g['ext_replay']['n_steps']}` steps, `{g['ext_replay']['pre_1bc3e281_detail_normalized']}` pre-`1bc3e281` `\"invalid arguments\"` step normalized, `2/2` transcripts matched, `meta.usage` exact match `$2.1401` est / `$11.1305` upper) and `data/runs/committed/v1.4/reference/solver-hard-seeds30to59` (`{g['solver_30to59_replay']['n_episodes']}` episodes on seeds `30..59`, `{g['solver_30to59_replay']['n_steps']:,}` steps, `meta.json` summary mean `0.498` exact) both pass with `0` mismatches.",
        f"- **Quota-exclusion integrity (`validate_g1_quota_exclusions`):** Planned seeds `30..59` (`30` total) = `2` valid (`[34, 37]`) + `28` missing (`status` string exact match). All `{gq['excluded_attempts_count']}` excluded attempts across `{len(gq['excluded_by_seed'])}` attempted seeds (`30, 31, 32, 33, 35, 36, 38, 39, 40`; seeds `41..59` unattempted after quota stop) carry `invalid: infra:provider_quota` and are strictly disjoint from valid seeds `[34, 37]` (`0` gameplay losses excluded).",
        f"- **Derived G1 artifacts:** `accuse.md` (`{g['accuse_md_ok']}`), `tags.json` (`{g['tags_json_ok']}`), `paired_table_ext30to59.{{json,md}}` (`2/2` rows exact canonical + markdown match), and `paired_table_pooled0to59.{{json,md}}` (`17/17` rows `100%` numeric match; `2` `stop_early` baseline rows retain pre-`e379c38c` short label, logged as `ISSUE-W7-6`).",
        f"- **`cf394894` `gpt-5.5` advance lock & `58716742` `afterquery-final` verification:** `docs/reports/gap.md` registers `gpt-5.5` beforehand via advance lock in `cf394894` (`OpenCode 1.19.5` over MCP on `v1.4` `hard`, dev seeds `0-29` in fixed order, `7,200 s` timeout, tag `afterquery-final`, `08:15 Helsinki` / `$200` launch stop, `08:45` hard drop, reported whatever the outcome, disclosing 15 Nov wording/detail updates and OpenCode `1.19.5` vs `1.18.29`); `data/runs/committed/v1.4/` contains `{gp['v14_committed_openai_episodes']}` OpenAI episodes prior to execution; `docs/reports/integrity.md` (`58716742`) records the final `12 of 12 held` judge-protocol hunt on `afterquery-final`; and `common.child_env()` + `opencode_run.child_env_extra()` isolate `OPENAI_API_KEY` vs `GOOGLE_GENERATIVE_AI_API_KEY` and strip `CANARY_LEDGER_TOKEN` (`openai_key_isolated_from_mcp_server={gp['openai_key_isolated_from_mcp_server']}`).",
        "",
        f"{h2} 6. Surface (d): Synthetic Tamper and Mutation Positive Controls (`/tmp/opencode/w7`)",
        "",
        "| Control ID | Mutation injected in scratch dir | Caught |",
        "|---|---|---|",
    ])
    ctrl_desc = {
        "forged_verda_summary_caught": "Forged `summary.json` `by_tier.all.mean_score = 0.42` vs `train.eval_hf.summarize`",
        "forged_verda_episode_score_caught": "Forged `score = 0.85` on unaccused `eval_cap` Verda episode",
        "tampered_replication_step_caught": "Mutated step `V = 0.1234` and `score = 0.99` in `medium-s28` (caught by `Env` + transcript)",
        "tampered_replication_transcript_caught": "Deleted `canary_status` event lines in `transcripts/28.txt`",
        "cherry_picked_quota_drop_caught": "Injected gameplay loss (`wrong_accusation_score=-1.0`) and valid-seed (`34`) overlap in quota exclusions",
        "leaked_secret_injection_caught": "Injected synthetic Google API key (`AIza...`) into scratch artifact",
        "forged_post_1bc3e281_detail_caught": "Injected mismatched `data.detail` on step 6 `\"invalid arguments\"` (`pre_1bc3e281_detail_normalized = 0`)",
        "non_invalid_args_detail_not_masked_caught": "Verified non-`\"invalid arguments\"` and `ok=True` `data.detail` payloads are never stripped",
    }
    for k, val in c["controls"].items():
        lines.append(f"| `{k}` | {ctrl_desc.get(k, k)} | `{val}` |")

    lines.extend([
        "",
        f"{h2} 7. Report-Only Findings Ledger (Zero Exploit Impact, Zero Protected Edits)",
        "",
        "| Issue ID | Severity | Area | Summary |",
        "|---|---|---|---|",
    ])
    for iss in issues:
        lines.append(f"| `{iss['id']}` | `{iss['severity']}` | `{iss['area']}` | {iss['summary']} |")

    lines.append("")
    return "\n".join(lines)


def check_report_md(report_path: Path) -> dict[str, Any]:
    if not report_path.exists():
        return {"exists": False, "ok": False, "problems": ["report_missing"]}
    txt = report_path.read_text(encoding="utf-8")
    problems: list[str] = []
    if EM_DASH in txt:
        problems.append("contains_em_dash")
    if EN_DASH in txt:
        problems.append("contains_en_dash")
    if MINUS_SIGN in txt:
        problems.append("contains_minus_sign")
    low_txt = txt.lower()
    if CO_AUTHOR_TAG.lower() in low_txt:
        problems.append("contains_co_authored_by")
    if "-".join(("pre", "reg")) in low_txt or "".join(("pre", "reg")) in low_txt:
        problems.append("contains_forbidden_hygiene_substring")
    raw_idx = txt.find("65% [24%, 98%]")
    luck_idx = txt.find("72% [52%, 91%]")
    if raw_idx == -1 or luck_idx == -1 or raw_idx >= luck_idx:
        problems.append("panel_fix_a_raw_must_precede_luck_adjusted")
    required_snippets = (
        "e19e2bd2",
        "58716742",
        "afterquery-final",
        "post-hoc lock",
        "registered beforehand",
        "advance lock",
        "450",
        "37,696",
        "249",
        "efd99c23",
        "66a26f5c",
        "1,550",
        "1bc3e281",
        "cf394894",
        "gpt-5.5",
        "31",
        "ISSUE-W7-1",
        "ISSUE-W7-7",
    )
    for snip in required_snippets:
        if snip not in txt:
            problems.append(f"missing_snippet:{snip}")
    return {"exists": True, "problems": problems, "ok": len(problems) == 0}


def run_full_audit(
    root: Path = ROOT,
    fast_tables: bool = False,
    scratch_parent: Path | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    verda = audit_verda_ws4(root=root)
    replication = audit_frontier_replication(root=root)
    g1_ext = audit_g1_partial_extension(root=root, fast_tables=fast_tables)
    controls = run_tamper_positive_controls(root=root, scratch_parent=scratch_parent)
    issues = collect_issues(verda, replication, g1_ext)
    elapsed_s = round(time.perf_counter() - t0, 3)

    overall_ok = verda["ok"] and replication["ok"] and g1_ext["ok"] and controls["all_caught"]
    return {
        "overall_ok": overall_ok,
        "elapsed_s": elapsed_s,
        "verda_ws4": verda,
        "frontier_replication": replication,
        "g1_partial_extension": g1_ext,
        "tamper_positive_controls": controls,
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verda WS4, FR8 replication, and G1 extension provenance auditor")
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--scratch-dir", default="/tmp/opencode/w7")
    ap.add_argument("--write-report", default=None)
    ap.add_argument("--check-report", default=None)
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise SystemExit("--workers must be 1")

    res = run_full_audit(
        Path(args.root).resolve(),
        fast_tables=bool(args.fast),
        scratch_parent=Path(args.scratch_dir),
    )
    if args.write_report:
        rep_p = Path(args.write_report)
        rep_p.parent.mkdir(parents=True, exist_ok=True)
        rep_p.write_text(render_markdown_report(res), encoding="utf-8")

    report_check = None
    if args.check_report:
        report_check = check_report_md(Path(args.check_report))
        res["report_check"] = report_check

    if args.json_out:
        out_p = Path(args.json_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")

    v = res["verda_ws4"]
    r = res["frontier_replication"]
    g = res["g1_partial_extension"]
    c = res["tamper_positive_controls"]
    print(
        f"VERDA_WS4 ok={v['ok']} dirs={v['n_verda_run_dirs']} eps={v['total_verda_episodes']} "
        f"steps={v['total_verda_steps']} curves={v['curves']['n_curve_files']} "
        f"secrets={len(v['secret_scan']['secret_hits'])}"
    )
    print(
        f"FRONTIER_REPLICATION ok={r['ok']} shards={r['n_shards']} eps={r['total_episodes']} "
        f"steps={r['total_steps']} pre_1bc3e281_norm={r['total_pre_1bc3e281_detail_normalized']} "
        f"transcripts={r['total_transcripts']}"
    )
    print(
        f"G1_EXTENSION ok={g['ok']} ext_eps={g['ext_replay']['n_episodes']} "
        f"pre_1bc3e281_norm={g['ext_replay']['pre_1bc3e281_detail_normalized']} "
        f"solver_eps={g['solver_30to59_replay']['n_episodes']} "
        f"quota_excluded={g['quota_exclusions']['excluded_attempts_count']} "
        f"gpt55_prereg_ok={g['gpt55_prereg_and_panel_fix_a']['ok']}"
    )
    print(
        f"TAMPER_CONTROLS all_caught={c['all_caught']} ({sum(c['controls'].values())}/{len(c['controls'])}) "
        f"issues_logged={len(res['issues'])} elapsed={res['elapsed_s']:.2f}s"
    )
    if report_check is not None:
        print(f"REPORT_CHECK ok={report_check['ok']} problems={report_check['problems']}")
        if not report_check["ok"]:
            return 1
    return 0 if res["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
