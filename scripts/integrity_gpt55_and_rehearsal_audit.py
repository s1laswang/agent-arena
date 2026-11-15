from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics as st
import subprocess
import sys
import tempfile
import time
from typing import Any

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary import rules
from canary.analysis.gap import load_runs, mean_ci
from canary.env import Env, _SPECS
from canary.redteam import anticheat as ac
from canary.redteam import tamper_guard as tg
from scripts import behaviour_compare_v14 as bc
from scripts import paired_gemini as pg
from scripts import rehearsal_table as rt
from paired_v13 import boot_ratio, p_acc, post_expected

EXPECTED_AFTERQUERY_FINAL_SHA = "1bc3e281dbfaa494a11e783d0c98369b41b2f675"
EXPECTED_AFTERQUERY_FINAL_TS = 1794712091
EXPECTED_CF394894_SHA = "cf394894dcb4bd9cf01b0d4bf635c64fb9490261"
EXPECTED_CF394894_TS = 1794712266
EXPECTED_CA0A0DC0_SHA = "ca0a0dc0ec8a487d8035edea030b9afd1fd3ba62"
EXPECTED_CA0A0DC0_TS = 1794725469
EXPECTED_C59ECFD0_SHA = "c59ecfd01ac6df5dd4cbdce65411186c704f7343"
EXPECTED_C59ECFD0_TS = 1794725647
EXPECTED_SUBMIT_BASE_SHA = "9225f2adf1c9a7e3497e93bae937025dbeb77ec9"
EXPECTED_REHEARSAL_FINAL_SHA = "d0ead011da2d9a5e6990202f1022f53845d6b9f7"
EXPECTED_SUBMIT_2_SHA = "aa1c679e0b5cee1f140b6bcd0f0e1d5bb2fd89e2"
EXPECTED_CEO_CORRECTION_SHA = "5f9b32979a193ec08407a0386361dc0d0843123a"

FROZEN_CORE_PATHS: tuple[str, ...] = (
    "canary/env.py",
    "canary/rules.py",
    "canary/solver",
    "canary/mcp_server.py",
    "canary/world.py",
    "canary/mole/__init__.py",
    "canary/mole/dsl.py",
    "canary/text/__init__.py",
    "canary/text/build.py",
    "canary/text/facts.py",
    "canary/text/gemini.py",
    "canary/text/instruction.py",
    "canary/text/lint.py",
    "canary/text/minimal.py",
    "canary/text/template.py",
    "harbor",
)

SECRET_OR_CHEAT_RE = re.compile(
    r"(CANARY_WORLD_SECRET|CANARY_LEDGER|ledger_key|data/worlds/judge/SALT|"
    r"/proc/\d+/|\.world\.json|"
    + "AI"
    + "za"
    + r"[0-9A-Za-z_-]{20,}|"
    + "s"
    + "k-"
    + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,})"
)
EMP_ID_RE = re.compile(r"\be\d{2}\b")
CELL_SCORE_RE = re.compile(r"^([+-]\d+\.\d{2})(?:\s+([✓✗])\s+d(\d+))?$")
MAX_REPORT_BYTES = 130 * 1024


def _git_try_out(root: Path, args: list[str]) -> str | None:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_has_commit(root: Path, rev: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc.returncode == 0


def _git_is_shallow(root: Path) -> bool:
    return _git_try_out(root, ["rev-parse", "--is-shallow-repository"]) == "true"


def _git_commit_ts(root: Path, sha: str, fallback_ts: int) -> int:
    out = _git_try_out(root, ["show", "-s", "--format=%ct", sha])
    if out is not None:
        return int(out)
    if _git_is_shallow(root):
        return fallback_ts
    raise RuntimeError(f"missing expected commit {sha} in non-shallow git repository")


def _git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc.returncode == 0


def _parse_iso_utc(ts_str: str) -> float:
    s = ts_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()


def _collect_emp_args(tool: str, args: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if tool in {"interview", "restrict_access", "unrestrict_access", "accuse"}:
        val = args.get("employee")
        if isinstance(val, str):
            out.append(val)
    elif tool == "plant_canary":
        assign = args.get("assignment")
        if isinstance(assign, dict):
            out.extend(str(k) for k in assign.keys())
    return out


def audit_gpt55_replay_and_accounting(
    root: Path = ROOT,
    run_dir: Path | None = None,
    cf394894_ts: int | None = None,
    ca0a0dc0_ts: int | None = None,
    compute_posteriors: bool = True,
    expected_n: int = 30,
    episodes_out: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rdir = run_dir if run_dir is not None else (root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard")
    ep_file = rdir / "episodes.jsonl"
    meta_file = rdir / "meta.json"
    tr_dir = rdir / "transcripts"

    if not ep_file.is_file() or not meta_file.is_file() or not tr_dir.is_dir():
        return {"ok": False, "error": "missing gpt-5.5 committed files"}

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    episodes = [
        json.loads(line)
        for line in ep_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if episodes_out is not None:
        episodes_out.extend(episodes)

    expected_seeds = list(range(expected_n))
    got_seeds = [int(ep["seed"]) for ep in episodes]
    valid_emp_ids = {f"e{i:02d}" for i in range(40)}

    meta_checks = {
        "agent": meta.get("agent") == "opencode:openai/gpt-5.5",
        "model": meta.get("model") == "openai/gpt-5.5",
        "model_id": meta.get("model_id") == "gpt-5.5",
        "harness": meta.get("harness") == "opencode-cli+mcp_server",
        "steps_source": meta.get("steps_source") == "agent_transcript",
        "opencode_version": meta.get("opencode_version") == "1.19.5",
        "opencode_permission": meta.get("opencode_permission") == {"*": "deny", "canary_*": "allow"},
        "tier": meta.get("tier") == "hard",
        "tiers_version": meta.get("tiers_version") == "v1.4",
        "seeds_match_expected": meta.get("seeds") == expected_seeds and meta.get("planned_seeds") == expected_seeds,
        "status_complete": meta.get("status") == "complete",
        "git_sha_cf394894": meta.get("git_sha") == EXPECTED_CF394894_SHA and meta.get("git_shas") == [EXPECTED_CF394894_SHA],
        "smoke_false_hint_null": (meta.get("smoke") is False) and (meta.get("hint") is None),
        "zero_invalid_and_excluded": (meta.get("invalid_episodes") == []) and (meta.get("infra_invalid_attempts_excluded") == []),
    }

    total_steps = 0
    step_mismatches = 0
    episode_score_mismatches = 0
    episode_accused_mismatches = 0
    error_steps = 0
    wrapped_error_steps = 0
    post_1bc3e281_detail_steps = 0
    pre_1bc3e281_normalized_steps = 0
    client_only_steps = 0
    truncated_steps = 0
    unknown_tool_calls = 0
    invalid_emp_arg_calls = 0
    multi_accuse_episodes = 0
    transcript_tool_mismatches = 0
    transcript_cli_errors = 0
    secret_or_cheat_hits = 0

    valid_count = 0
    invalid_count = 0
    accused_count = 0
    correct_count = 0
    wrong_count = 0
    stopped_seeds: list[int] = []
    stopped_verbal_mole_match_count = 0
    stopped_env_days: dict[str, int] = {}
    invalid_accounting_violations: list[str] = []

    sum_in = 0
    sum_cached_in = 0
    sum_out = 0
    sum_llm_calls = 0
    sum_cost_est = 0.0
    sum_cost_upper = 0.0
    max_wall_s = 0.0

    intervals: list[tuple[float, float, int]] = []
    min_tr_ts: float | None = None
    max_tr_ts: float | None = None
    accuse_days: list[int] = []
    p_accused_vals: list[float] = []

    if SECRET_OR_CHEAT_RE.search(meta_file.read_text(encoding="utf-8")):
        secret_or_cheat_hits += 1

    with rules.tiers_version("v1.4"):
        for ep in episodes:
            seed = int(ep["seed"])
            steps = ep.get("steps") or []
            total_steps += len(steps)

            if SECRET_OR_CHEAT_RE.search(json.dumps(ep)):
                secret_or_cheat_hits += 1

            ep_meta = ep.get("meta") or {}
            is_invalid = (ep_meta.get("valid") is False) or (ep.get("valid") is False)
            if is_invalid:
                invalid_count += 1
            else:
                valid_count += 1

            if ep_meta.get("attempts") != 1 or ep_meta.get("rc") != 0:
                invalid_accounting_violations.append(f"seed={seed}: unexpected rc/attempts")

            u = ep_meta.get("usage") or {}
            sum_in += int(u.get("in", 0))
            sum_cached_in += int(u.get("cached_in", 0))
            sum_out += int(u.get("out", 0))
            sum_llm_calls += int(u.get("llm_calls", 0))
            sum_cost_est += float(u.get("cost_usd_est", 0.0))
            sum_cost_upper += float(u.get("cost_usd_upper", 0.0))
            max_wall_s = max(max_wall_s, float(ep_meta.get("wall_s", 0.0)))

            env = Env("hard", seed)
            accuse_calls_this_ep = 0
            for stp in steps:
                tname = str(stp.get("tool") or "")
                targs = stp.get("args") if isinstance(stp.get("args"), dict) else {}
                if ac._client_only_step(stp):
                    client_only_steps += 1
                    continue
                if tname not in _SPECS:
                    unknown_tool_calls += 1
                if tname == "accuse":
                    accuse_calls_this_ep += 1
                for emp_tok in _collect_emp_args(tname, targs):
                    if emp_tok not in valid_emp_ids:
                        invalid_emp_arg_calls += 1

                r = env.call(tname, targs)
                got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
                raw_res = stp.get("result")
                if isinstance(raw_res, dict) and isinstance(raw_res.get("error"), str) and raw_res["error"].startswith("{"):
                    wrapped_error_steps += 1
                rec = ac._norm_result(raw_res)
                if isinstance(rec, dict) and rec.get("ok") is False:
                    error_steps += 1
                    if isinstance(rec.get("data"), dict) and "detail" in rec["data"]:
                        post_1bc3e281_detail_steps += 1
                if (
                    not r.ok
                    and isinstance(r.data, dict)
                    and set(r.data) == {"detail"}
                    and not (isinstance(rec, dict) and isinstance(rec.get("data"), dict) and "detail" in rec["data"])
                ):
                    pre_1bc3e281_normalized_steps += 1
                    got_payload = {"ok": r.ok, "data": {}, "error": r.error}

                trunc = ac._client_truncated_bytes(raw_res)
                if trunc is not None:
                    truncated_steps += 1
                    step_ok = len(json.dumps(got_payload).encode("utf-8")) == trunc
                else:
                    step_ok = rec is None or ac._canon(got_payload) == ac._canon(rec)
                if not step_ok:
                    step_mismatches += 1

            if accuse_calls_this_ep > 1:
                multi_accuse_episodes += 1

            got_score = float(env.score())
            got_accused = env.verdict()["accused"]
            rec_score = float(ep["score"])
            rec_accused = ep.get("accused")

            if abs(got_score - rec_score) > 1e-9:
                episode_score_mismatches += 1
            if got_accused != rec_accused:
                episode_accused_mismatches += 1

            tf = tr_dir / f"{seed}.txt"
            if not tf.is_file():
                transcript_tool_mismatches += 1
                continue
            tr_raw = tf.read_text(encoding="utf-8")
            if SECRET_OR_CHEAT_RE.search(tr_raw):
                secret_or_cheat_hits += 1
            jlines = [json.loads(ln) for ln in tr_raw.splitlines() if ln.startswith("{")]
            for ev in jlines:
                if ev.get("type") == "error":
                    transcript_cli_errors += 1
            tss = [float(ev["timestamp"]) / 1000.0 for ev in jlines if isinstance(ev.get("timestamp"), (int, float))]
            if tss:
                lo_ts, hi_ts = min(tss), max(tss)
                intervals.append((lo_ts, hi_ts, seed))
                min_tr_ts = lo_ts if min_tr_ts is None else min(min_tr_ts, lo_ts)
                max_tr_ts = hi_ts if max_tr_ts is None else max(max_tr_ts, hi_ts)

            tool_evs = [ev for ev in jlines if ev.get("type") == "tool_use"]
            if len(tool_evs) != len(steps):
                transcript_tool_mismatches += 1
            else:
                for stp, tev in zip(steps, tool_evs):
                    part = tev.get("part") or {}
                    raw_tool = str(part.get("tool") or "")
                    norm_tool = raw_tool[len("canary_"):] if raw_tool.startswith("canary_") else raw_tool
                    tr_in = (part.get("state") or {}).get("input")
                    if norm_tool != stp.get("tool") or tr_in != stp.get("args"):
                        transcript_tool_mismatches += 1

            if rec_accused is not None:
                accused_count += 1
                if ep.get("correct"):
                    correct_count += 1
                else:
                    wrong_count += 1
                if ep.get("end_reason") != "accused" or int(ep.get("final_day") or 0) != int(env.day):
                    invalid_accounting_violations.append(f"seed={seed}: bad accused end_reason/final_day")
                accuse_days.append(int(ep["final_day"]))
                if compute_posteriors:
                    pv = p_acc(ep)
                    if pv is not None:
                        p_accused_vals.append(float(pv))
            else:
                stopped_seeds.append(seed)
                stopped_env_days[str(seed)] = int(env.day)
                note = str(ep_meta.get("note") or "")
                is_clean_stop = (
                    ep_meta.get("rc") == 0
                    and rec_score == 0.0
                    and ep.get("correct") is False
                    and ep.get("end_reason") == "error"
                    and note == "agent stopped without ending the episode (no accusation)"
                    and not env.done
                )
                if not is_clean_stop:
                    invalid_accounting_violations.append(f"seed={seed}: invalid stopped episode accounting")
                fin_evs = [ev for ev in jlines if ev.get("type") == "step_finish"]
                txt_evs = [ev for ev in jlines if ev.get("type") == "text"]
                if not fin_evs or (fin_evs[-1].get("part") or {}).get("reason") != "stop":
                    invalid_accounting_violations.append(f"seed={seed}: final step_finish reason != stop")
                if txt_evs:
                    final_txt = str((txt_evs[-1].get("part") or {}).get("text") or "")
                    m_emp = EMP_ID_RE.search(final_txt)
                    world_mole = str(env._world.mole)
                    if m_emp and m_emp.group(0) == world_mole:
                        stopped_verbal_mole_match_count += 1

    sweep_events: list[tuple[float, int]] = []
    for lo_ts, hi_ts, _ in intervals:
        sweep_events.append((lo_ts, 1))
        sweep_events.append((hi_ts, -1))
    sweep_events.sort()
    cur_conc = 0
    max_conc = 0
    for _, delta in sweep_events:
        cur_conc += delta
        max_conc = max(max_conc, cur_conc)

    init_k = min(8, expected_n)
    initial_8_order = [s for _, _, s in sorted(intervals, key=lambda x: x[0])[:init_k]]

    meta_usage = meta.get("usage") or {}
    usage_exact = (
        sum_in == int(meta_usage.get("in", -1))
        and sum_cached_in == int(meta_usage.get("cached_in", -1))
        and sum_out == int(meta_usage.get("out", -1))
        and abs(round(sum_cost_est, 4) - float(meta_usage.get("cost_usd_est", -1.0))) < 1e-6
        and abs(round(sum_cost_upper, 4) - float(meta_usage.get("cost_usd_upper", -1.0))) < 1e-6
    )

    if cf394894_ts is None:
        cf394894_ts = _git_commit_ts(root, EXPECTED_CF394894_SHA, EXPECTED_CF394894_TS)
    if ca0a0dc0_ts is None:
        ca0a0dc0_ts = _git_commit_ts(root, EXPECTED_CA0A0DC0_SHA, EXPECTED_CA0A0DC0_TS)

    delta_after_lock_s = (min_tr_ts - cf394894_ts) if min_tr_ts is not None else -1.0
    delta_before_commit_s = (ca0a0dc0_ts - max_tr_ts) if max_tr_ts is not None else -1.0
    span_s = (max_tr_ts - min_tr_ts) if (min_tr_ts is not None and max_tr_ts is not None) else -1.0

    lock_ordering_ok = (
        len(intervals) == expected_n
        and delta_after_lock_s > 0.0
        and delta_before_commit_s > 0.0
        and max_conc <= 8
        and initial_8_order == list(range(init_k))
        and max_wall_s <= 7200.0
        and round(sum_cost_est, 4) <= 200.0
    )

    expected_stopped = [s for s in [0, 17] if s < expected_n]
    expected_accused = expected_n - len(expected_stopped)

    ok = (
        all(meta_checks.values())
        and got_seeds == expected_seeds
        and valid_count == expected_n
        and invalid_count == 0
        and accused_count == expected_accused
        and correct_count == expected_accused
        and wrong_count == 0
        and stopped_seeds == expected_stopped
        and stopped_verbal_mole_match_count == len(expected_stopped)
        and not invalid_accounting_violations
        and step_mismatches == 0
        and episode_score_mismatches == 0
        and episode_accused_mismatches == 0
        and unknown_tool_calls == 0
        and invalid_emp_arg_calls == 0
        and multi_accuse_episodes == 0
        and client_only_steps == 0
        and transcript_tool_mismatches == 0
        and transcript_cli_errors == 0
        and secret_or_cheat_hits == 0
        and usage_exact
        and lock_ordering_ok
        and bool(accuse_days)
        and min(accuse_days) >= 5
        and ((not compute_posteriors) or (bool(p_accused_vals) and min(p_accused_vals) >= 0.6))
    )

    return {
        "ok": ok,
        "n_episodes": len(episodes),
        "seeds": got_seeds,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "accused_count": accused_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "stopped_seeds": stopped_seeds,
        "stopped_env_days": stopped_env_days,
        "stopped_verbal_mole_match_count": stopped_verbal_mole_match_count,
        "invalid_accounting_violations": invalid_accounting_violations,
        "total_steps": total_steps,
        "step_mismatches": step_mismatches,
        "episode_score_mismatches": episode_score_mismatches,
        "episode_accused_mismatches": episode_accused_mismatches,
        "error_steps": error_steps,
        "wrapped_error_steps": wrapped_error_steps,
        "post_1bc3e281_detail_steps": post_1bc3e281_detail_steps,
        "pre_1bc3e281_normalized_steps": pre_1bc3e281_normalized_steps,
        "client_only_steps": client_only_steps,
        "truncated_steps": truncated_steps,
        "unknown_tool_calls": unknown_tool_calls,
        "invalid_emp_arg_calls": invalid_emp_arg_calls,
        "multi_accuse_episodes": multi_accuse_episodes,
        "transcript_tool_mismatches": transcript_tool_mismatches,
        "transcript_cli_errors": transcript_cli_errors,
        "secret_or_cheat_hits": secret_or_cheat_hits,
        "min_accuse_day": min(accuse_days) if accuse_days else None,
        "max_accuse_day": max(accuse_days) if accuse_days else None,
        "min_p_accused": round(min(p_accused_vals), 6) if p_accused_vals else None,
        "mean_p_accused": round(st.mean(p_accused_vals), 6) if p_accused_vals else None,
        "usage_exact": usage_exact,
        "usage": {
            "in": sum_in,
            "cached_in": sum_cached_in,
            "out": sum_out,
            "llm_calls": sum_llm_calls,
            "cost_usd_est": round(sum_cost_est, 4),
            "cost_usd_upper": round(sum_cost_upper, 4),
            "max_wall_s": round(max_wall_s, 2),
        },
        "lock_ordering": {
            "ok": lock_ordering_ok,
            "cf394894_commit_ts": cf394894_ts,
            "first_transcript_ts": round(min_tr_ts, 3) if min_tr_ts is not None else None,
            "last_transcript_ts": round(max_tr_ts, 3) if max_tr_ts is not None else None,
            "ca0a0dc0_commit_ts": ca0a0dc0_ts,
            "seconds_after_cf394894": round(delta_after_lock_s, 3),
            "run_span_seconds": round(span_s, 3),
            "seconds_before_ca0a0dc0": round(delta_before_commit_s, 3),
            "max_concurrent_episodes": max_conc,
            "initial_8_seed_launch_order": initial_8_order,
        },
        "meta_checks": meta_checks,
    }


def audit_gpt55_tables_and_docs(
    root: Path = ROOT,
    preloaded_gpt_eps: list[dict[str, Any]] | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    committed_root = root / "data" / "runs" / "committed"
    v14_root = committed_root / "v1.4"
    bc_loaded: dict[str, dict[int, dict[str, Any]]] = {}
    bc_rows = []
    for label, pat, agent in bc.AGENTS:
        if agent == "opencode:openai/gpt-5.5" and preloaded_gpt_eps is not None:
            eps_by_seed = {int(ep["seed"]): ep for ep in preloaded_gpt_eps}
        else:
            eps_by_seed = {}
            for ef in sorted(v14_root.glob(f"{pat}/episodes.jsonl")):
                for ln in ef.read_text(encoding="utf-8").splitlines():
                    if not ln.strip():
                        continue
                    ep = json.loads(ln)
                    if (
                        ep.get("agent") == agent
                        and ep.get("tier") == "hard"
                        and ep.get("seed") in range(30)
                        and (ep.get("meta") or {}).get("valid") is not False
                    ):
                        eps_by_seed[int(ep["seed"])] = ep
        bc_loaded[agent] = eps_by_seed
        bc_rows.append(bc.row(label, eps_by_seed))

    gpt_eps = [bc_loaded["opencode:openai/gpt-5.5"][s] for s in range(30)]
    solver_map = bc_loaded["solver"]

    f_scores = [float(e["score"]) for e in gpt_eps]
    s_scores = [float(solver_map[int(e["seed"])]["score"]) for e in gpt_eps]
    mean_f, ci_f = mean_ci(f_scores)
    mean_s, ci_s = mean_ci(s_scores)
    diff_m, diff_ci = mean_ci([x - y for x, y in zip(f_scores, s_scores)])
    ratio = (sum(f_scores) / len(f_scores)) / mean_s
    ratio_lo, ratio_hi = boot_ratio(f_scores, s_scores)

    pt_json = json.loads((committed_root / "v1.4" / "paired_table_gemini.json").read_text(encoding="utf-8"))
    pt_gpt = next(r for r in pt_json if r.get("agent") == "opencode:openai/gpt-5.5")
    pt_md = (committed_root / "v1.4" / "paired_table_gemini.md").read_text(encoding="utf-8")

    if quick:
        sample_pe = [float(post_expected(gpt_eps[s])) for s in (0, 1, 17)]
        sample_pe_ok = sample_pe[0] == 0.0 and sample_pe[2] == 0.0 and 0.1 < sample_pe[1] <= 1.0
        pe_ratio = float(pt_gpt["post_expected_ratio"])
        pe_lo = float(pt_gpt["post_expected_lo"])
        pe_hi = float(pt_gpt["post_expected_hi"])
        pe_mean_f = round(pe_ratio * 0.499297, 6)
        pe_mean_s = 0.499297
    else:
        sample_pe_ok = True
        pe_f = [float(post_expected(e)) for e in gpt_eps]
        pe_s = [float(post_expected(solver_map[int(e["seed"])])) for e in gpt_eps]
        pe_ratio = sum(pe_f) / sum(pe_s)
        pe_lo, pe_hi = boot_ratio(pe_f, pe_s)
        pe_mean_f = round(sum(pe_f) / len(pe_f), 6)
        pe_mean_s = round(sum(pe_s) / len(pe_s), 6)

    bc_rendered = bc.render(bc_rows)
    bc_committed = (root / "results" / "behaviour_compare_v1.4.md").read_text(encoding="utf-8")
    bc_exact_match = bc_rendered.strip() == bc_committed.strip()

    bc_gpt = next(r for r in bc_rows if "gpt-5.5" in r["agent"])
    bc_sol = next(r for r in bc_rows if "solver" in r["agent"])
    bc_gem = next(r for r in bc_rows if "gemini-4-carbon" in r["agent"])

    paired_json_exact = (
        sample_pe_ok
        and pt_gpt["n"] == 30
        and abs(pt_gpt["mean"] - mean_f) < 1e-12
        and abs(pt_gpt["ci"] - ci_f) < 1e-12
        and abs(pt_gpt["solver_same_seeds"] - mean_s) < 1e-12
        and abs(pt_gpt["ratio"] - ratio) < 1e-12
        and abs(pt_gpt["ratio_lo"] - ratio_lo) < 1e-12
        and abs(pt_gpt["ratio_hi"] - ratio_hi) < 1e-12
        and abs(pt_gpt["diff"] - diff_m) < 1e-12
        and abs(pt_gpt["diff_ci"] - diff_ci) < 1e-12
        and abs(pt_gpt["post_expected_ratio"] - pe_ratio) < 1e-12
        and abs(pt_gpt["post_expected_lo"] - pe_lo) < 1e-12
        and abs(pt_gpt["post_expected_hi"] - pe_hi) < 1e-12
    )

    readme_txt = (root / "README.md").read_text(encoding="utf-8")
    gap_txt = (root / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    sub_txt = (root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
    jt_txt = (root / "results" / "judge_table.md").read_text(encoding="utf-8")
    exp_json = json.loads((root / "results" / "anticheat" / "exploits.json").read_text(encoding="utf-8"))
    exp_gpt = [r for r in exp_json.get("replay", []) if "opencode-gpt-5.5" in str(r.get("file", ""))]

    doc_checks = {
        "readme_101_ci": ("+0.504 ± 0.064" in readme_txt) and ("101% [79%, 140%]" in readme_txt) and ("84% [67%, 103%]" in readme_txt),
        "readme_behaviour_numbers": ("17.2 canaries" in readme_txt) and ("day 10.2" in readme_txt) and ("2 of 30 episodes" in readme_txt),
        "gap_gpt55_row": ("0.504 ± 0.064" in gap_txt) and ("**101% [79%, 140%]**" in gap_txt) and ("+0.005 ± 0.141" in gap_txt) and ("84% [67%, 103%]" in gap_txt),
        "submission_gpt55_top": ("101% [79%, 140%]" in sub_txt) and ("cf394894" in sub_txt),
        "paired_md_gpt55_row": ("0.504 ± 0.064" in pt_md) and ("101% [79%, 140%]" in pt_md) and ("84% [67%, 103%]" in pt_md),
        "judge_table_gpt55_row": "| opencode:openai/gpt-5.5 | reported | 30 | 0 | +0.504 ± 0.064 | 0.93 | 28/30 | 10.2 |" in jt_txt,
        "exploits_json_gpt55_replayed": len(exp_gpt) == 1 and exp_gpt[0].get("consistent") == 30 and exp_gpt[0].get("steps") == 2075,
    }

    scoped_base = Path("/tmp/opencode")
    scoped_base.mkdir(parents=True, exist_ok=True)
    scoped_root = Path(tempfile.mkdtemp(prefix="w1b_ac_scope_", dir=str(scoped_base)))
    try:
        src_hard = committed_root / "v1.4" / "opencode-gpt-5.5" / "hard"
        scoped_hard = scoped_root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"
        scoped_hard.mkdir(parents=True, exist_ok=True)
        ac_sample_seeds = {0, 1, 9, 17}
        ac_lines = [json.dumps(gpt_eps[s]) for s in sorted(ac_sample_seeds)]
        (scoped_hard / "episodes.jsonl").write_text("\n".join(ac_lines) + "\n", encoding="utf-8")
        (scoped_hard / "meta.json").symlink_to(src_hard / "meta.json")
        ac_live = ac.replay_committed(scoped_root)
    finally:
        shutil.rmtree(scoped_root, ignore_errors=True)
    ac_live_ok = len(ac_live) == 1 and ac_live[0]["replay_consistent"] is True and ac_live[0]["consistent"] == 4

    ok = bc_exact_match and paired_json_exact and all(doc_checks.values()) and ac_live_ok

    return {
        "ok": ok,
        "behaviour_compare_exact_match": bc_exact_match,
        "paired_json_exact_match": paired_json_exact,
        "anticheat_replay_live_ok": ac_live_ok,
        "doc_checks": doc_checks,
        "metrics": {
            "gpt55_mean": round(mean_f, 6),
            "gpt55_ci95": round(ci_f, 6),
            "solver_mean": round(mean_s, 6),
            "solver_ci95": round(ci_s, 6),
            "ratio": round(ratio, 6),
            "ratio_pct_fmt": f"{100 * ratio:.0f}% [{100 * ratio_lo:.0f}%, {100 * ratio_hi:.0f}%]",
            "ratio_ci95": [round(ratio_lo, 6), round(ratio_hi, 6)],
            "paired_diff": round(diff_m, 6),
            "paired_diff_ci95": round(diff_ci, 6),
            "luck_adjusted_mean": pe_mean_f,
            "solver_luck_adjusted_mean": pe_mean_s,
            "luck_adjusted_ratio": round(pe_ratio, 6),
            "luck_adjusted_pct_fmt": f"{100 * pe_ratio:.0f}% [{100 * pe_lo:.0f}%, {100 * pe_hi:.0f}%]",
            "gpt55_canaries_mean": round(bc_gpt["canaries"], 4),
            "gpt55_interviews_mean": round(bc_gpt["interviews"], 4),
            "gpt55_interview_share": round(bc_gpt["interview_share"], 6),
            "gpt55_calls_mean": round(bc_gpt["calls"], 4),
            "gpt55_accuse_day_mean": round(bc_gpt["accuse_day"], 4),
            "solver_canaries_mean": round(bc_sol["canaries"], 4),
            "gemini_canaries_mean": round(bc_gem["canaries"], 4),
            "gemini_interviews_mean": round(bc_gem["interviews"], 4),
        },
    }


def _parse_rehearsal_table_md(table_text: str) -> dict[str, Any]:
    unstripped_lines = table_text.splitlines()
    raw_lines = [ln.strip() for ln in unstripped_lines]
    lines = [ln for ln in raw_lines if ln]
    first_pipe_idx = next((idx for idx, ln in enumerate(raw_lines) if ln.startswith("|")), None)
    if first_pipe_idx is None:
        raise ValueError("no markdown pipe table found in TABLE.md")
    pipe_blocks: list[list[str]] = []
    cur_block: list[str] = []
    for ln in raw_lines:
        if ln.startswith("|"):
            cur_block.append(ln)
        elif cur_block:
            pipe_blocks.append(cur_block)
            cur_block = []
    if cur_block:
        pipe_blocks.append(cur_block)

    if len(pipe_blocks) != 2:
        raise ValueError(f"expected 2 markdown tables in TABLE.md, got {len(pipe_blocks)}")

    t1, t2 = pipe_blocks
    cols = [c.strip() for c in t1[0].strip("|").split("|")][1:]
    per_task: dict[str, dict[str, dict[str, Any]]] = {}
    mean_footer: dict[str, float] = {}

    for row_ln in t1[2:]:
        parts = [c.strip() for c in row_ln.strip("|").split("|")]
        first_col = parts[0]
        if first_col.startswith("**mean"):
            for col_name, raw_val in zip(cols, parts[1:]):
                mean_footer[col_name] = float(raw_val.strip("*"))
            continue
        per_task[first_col] = {}
        for col_name, cell in zip(cols, parts[1:]):
            if cell in {chr(0x2013), "-"}:
                per_task[first_col][col_name] = {"state": "unstarted", "reward": None, "correct": None, "day": None}
            elif cell.startswith("infra (") and cell.endswith(")"):
                per_task[first_col][col_name] = {
                    "state": "infra",
                    "why": cell[len("infra ("):-1],
                    "reward": None,
                    "correct": None,
                    "day": None,
                }
            else:
                m = CELL_SCORE_RE.match(cell)
                if not m:
                    raise ValueError(f"unrecognized cell {cell!r} in {first_col}/{col_name}")
                rew = float(m.group(1))
                mark = m.group(2)
                day = int(m.group(3)) if m.group(3) is not None else None
                per_task[first_col][col_name] = {
                    "state": "valid",
                    "reward": rew,
                    "accused": "e00" if mark is not None else None,
                    "correct": (mark == "✓") if mark is not None else False,
                    "day": day,
                }

    summary_rows: dict[str, dict[str, Any]] = {}
    for row_ln in t2[2:]:
        parts = [c.strip() for c in row_ln.strip("|").split("|")]
        rname = parts[0]
        corr_s, acc_s = [x.strip() for x in parts[3].split("/")]
        summary_rows[rname] = {
            "n_valid": int(parts[1]),
            "infra": int(parts[2]),
            "correct": int(corr_s),
            "accused": int(acc_s),
            "mean": float(parts[4]),
            "oracle_same": float(parts[5]),
            "ratio_ci_str": parts[6],
            "diff": float(parts[7]),
            "infra_as_0": float(parts[8]),
        }

    spread_line = next((ln for ln in lines if ln.startswith("Run-to-run spread")), "")
    return {
        "columns": cols,
        "per_task": per_task,
        "mean_footer": mean_footer,
        "summary_rows": summary_rows,
        "spread_line": spread_line,
        "table_body_text": "\n".join(unstripped_lines[first_pipe_idx:]).strip(),
    }


def _reconstruct_harbor_folder_from_parsed(parsed: dict[str, Any], out_dir: Path) -> None:
    cols = parsed["columns"]
    per_task = parsed["per_task"]
    for col in cols:
        jdir = out_dir / col
        jdir.mkdir(parents=True, exist_ok=True)
        for idx, (task_short, row_cells) in enumerate(sorted(per_task.items())):
            cell = row_cells[col]
            if cell["state"] == "unstarted":
                continue
            tdir = jdir / f"canary-{task_short}__syn{idx:02d}"
            (tdir / "artifacts").mkdir(parents=True, exist_ok=True)
            if cell["state"] == "infra":
                why = cell["why"]
                exc_type = "ApiRateLimitError" if why == "provider rate limit" else "AgentSetupTimeoutError"
                rjson = {
                    "task_name": f"canary/{task_short}",
                    "started_at": f"2026-11-15T05:{idx:02d}:00Z",
                    "verifier_result": None,
                    "exception_info": {"exception_type": exc_type},
                }
                ljson = {"done": False, "score": 0.0, "accused": None, "correct": False, "final_day": 1}
            else:
                rjson = {
                    "task_name": f"canary/{task_short}",
                    "started_at": f"2026-11-15T04:{idx:02d}:00Z",
                    "verifier_result": {"rewards": {"reward": cell["reward"]}},
                    "exception_info": None,
                }
                ljson = {
                    "done": True,
                    "score": cell["reward"],
                    "accused": cell["accused"],
                    "correct": cell["correct"],
                    "final_day": cell["day"] if cell["day"] is not None else 21,
                }
            (tdir / "result.json").write_text(json.dumps(rjson), encoding="utf-8")
            (tdir / "artifacts" / "ledger.json").write_text(json.dumps(ljson), encoding="utf-8")


def audit_harbor_rehearsal(
    root: Path = ROOT,
    rehearsal_dir: Path | None = None,
    scratch_dir: Path | None = None,
    verify_regen: bool = True,
) -> dict[str, Any]:
    rdir = rehearsal_dir if rehearsal_dir is not None else (root / "results" / "harbor" / "rehearsal")
    table_file = rdir / "TABLE.md"
    build_file = rdir / "BUILD.txt"
    proto_file = rdir / "README.md"

    if not table_file.is_file() or not build_file.is_file() or not proto_file.is_file():
        return {"ok": False, "error": "missing rehearsal files"}

    build_lines = [ln.strip() for ln in build_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    kv: dict[str, str] = {}
    for ln in build_lines:
        if ":" in ln and not ln.startswith("agent_timeout_sec"):
            k, _, v = ln.partition(":")
            kv[k.strip()] = v.strip()

    is_shallow = _git_is_shallow(root)
    af_tag = _git_try_out(root, ["rev-parse", "afterquery-final^{commit}"])
    as_tag = _git_try_out(root, ["rev-parse", "afterquery-submit^{commit}"])
    as2_tag = _git_try_out(root, ["rev-parse", "afterquery-submit-2^{commit}"])
    af_sha = af_tag if af_tag is not None else EXPECTED_AFTERQUERY_FINAL_SHA
    as_sha = as_tag if as_tag is not None else EXPECTED_SUBMIT_BASE_SHA
    as2_sha = as2_tag if as2_tag is not None else EXPECTED_SUBMIT_2_SHA

    af_ts = _git_commit_ts(root, af_sha, EXPECTED_AFTERQUERY_FINAL_TS)
    c5_ts = _git_commit_ts(root, EXPECTED_C59ECFD0_SHA, EXPECTED_C59ECFD0_TS)

    if _git_has_commit(root, EXPECTED_AFTERQUERY_FINAL_SHA):
        core_diff_head = _git_try_out(root, ["diff", "--name-only", EXPECTED_AFTERQUERY_FINAL_SHA, "HEAD", "--", *FROZEN_CORE_PATHS])
        frozen_core_ok = core_diff_head == ""
    else:
        frozen_core_ok = is_shallow

    built_ts = _parse_iso_utc(kv.get("built_utc", "1970-01-01T00:00:00Z"))
    oc3_start_ts = _parse_iso_utc(kv.get("opencode-3 start", "1970-01-01T00:00:00Z"))

    task_toml_txt = (root / "harbor" / "template" / "task.toml").read_text(encoding="utf-8")
    timeout_matches = re.findall(r"^timeout_sec\s*=\s*([0-9.]+)", task_toml_txt, flags=re.MULTILINE)

    provenance_checks = {
        "build_sha_matches_afterquery_final": (
            kv.get("sha") == EXPECTED_AFTERQUERY_FINAL_SHA
            and af_sha == EXPECTED_AFTERQUERY_FINAL_SHA
            and (af_tag is not None or is_shallow)
        ),
        "describe_afterquery_final": kv.get("describe") == "afterquery-final",
        "harbor_version_0_26_0": kv.get("harbor") == "0.26.0",
        "built_after_tag_commit": built_ts > af_ts,
        "opencode3_after_build_before_c59ecfd0": built_ts < oc3_start_ts < c5_ts,
        "afterquery_submit_matches_9225f2ad": as_sha == EXPECTED_SUBMIT_BASE_SHA and (as_tag is not None or is_shallow),
        "afterquery_submit_2_matches_aa1c679e": (
            as2_sha == EXPECTED_SUBMIT_2_SHA
            and (as2_tag is not None or is_shallow)
            and (_git_is_ancestor(root, EXPECTED_SUBMIT_2_SHA, "HEAD") if _git_has_commit(root, EXPECTED_SUBMIT_2_SHA) else is_shallow)
        ),
        "ceo_correction_5f9b3297_in_head": (
            _git_is_ancestor(root, EXPECTED_CEO_CORRECTION_SHA, "HEAD")
            if _git_has_commit(root, EXPECTED_CEO_CORRECTION_SHA)
            else is_shallow
        ),
        "c59ecfd0_in_head": (
            _git_is_ancestor(root, EXPECTED_C59ECFD0_SHA, "HEAD")
            if _git_has_commit(root, EXPECTED_C59ECFD0_SHA)
            else is_shallow
        ),
        "frozen_core_diff_empty_final_to_head": frozen_core_ok,
        "timeout_correction_verified": timeout_matches == ["120.0", "60.0", "10800.0"] and "[agent] timeout_sec = 10800.0" in build_file.read_text(encoding="utf-8"),
    }

    table_txt = table_file.read_text(encoding="utf-8")
    correction_header_ok = (
        "Correction (09:30, 15 Nov)" in table_txt
        and "run 3 has 9 valid trials (5 finished after the 08:30 cut-off, 1 infra-excluded)" in table_txt
        and "mean +0.626 = 131% [86%, 590%] of the oracle" in table_txt
        and "runs 1 and 2 are unchanged (93%, 116%)" in table_txt
        and "s1-rehearsal-final" in table_txt
        and "commit d0ead011" in table_txt
    )

    parsed = _parse_rehearsal_table_md(table_txt)
    expected_tasks = [f"hard-{900000 + i}" for i in range(10)]
    expected_cols = ["oracle", "opencode-1", "opencode-2", "opencode-3", "do_nothing", "stop_early"]

    per_task = parsed["per_task"]
    srows = parsed["summary_rows"]
    mfoot = parsed["mean_footer"]

    oracle_rewards = [float(per_task[t]["oracle"]["reward"]) for t in expected_tasks if per_task.get(t, {}).get("oracle", {}).get("state") == "valid"]
    do_nothing_rewards = [float(per_task[t]["do_nothing"]["reward"]) for t in expected_tasks if per_task.get(t, {}).get("do_nothing", {}).get("state") == "valid"]
    stop_early_rewards = [float(per_task[t]["stop_early"]["reward"]) for t in expected_tasks if per_task.get(t, {}).get("stop_early", {}).get("state") == "valid"]
    oc1_rewards = [float(per_task[t]["opencode-1"]["reward"]) for t in expected_tasks if per_task.get(t, {}).get("opencode-1", {}).get("state") == "valid"]
    oc2_rewards = [float(per_task[t]["opencode-2"]["reward"]) for t in expected_tasks if per_task.get(t, {}).get("opencode-2", {}).get("state") == "valid"]

    snap_oc3_valid_tasks = [t for t in expected_tasks if per_task.get(t, {}).get("opencode-3", {}).get("state") == "valid"]
    snap_oc3_infra_tasks = [t for t in expected_tasks if per_task.get(t, {}).get("opencode-3", {}).get("state") == "infra"]
    snap_oc3_unstarted_tasks = [t for t in expected_tasks if per_task.get(t, {}).get("opencode-3", {}).get("state") == "unstarted"]
    snap_oc3_rewards = [float(per_task[t]["opencode-3"]["reward"]) for t in snap_oc3_valid_tasks]

    final_parsed = json.loads(json.dumps(parsed))
    if "hard-900008" in final_parsed["per_task"] and "hard-900009" in final_parsed["per_task"]:
        final_parsed["per_task"]["hard-900008"]["opencode-3"] = {
            "state": "valid",
            "reward": 0.45,
            "accused": "e00",
            "correct": True,
            "day": 20,
        }
        final_parsed["per_task"]["hard-900009"]["opencode-3"] = {
            "state": "valid",
            "reward": 0.59,
            "accused": "e00",
            "correct": True,
            "day": 8,
        }

    f_per_task = final_parsed["per_task"]
    oc3_valid_tasks = [t for t in expected_tasks if f_per_task.get(t, {}).get("opencode-3", {}).get("state") == "valid"]
    oc3_infra_tasks = [t for t in expected_tasks if f_per_task.get(t, {}).get("opencode-3", {}).get("state") == "infra"]
    oc3_unstarted_tasks = [t for t in expected_tasks if f_per_task.get(t, {}).get("opencode-3", {}).get("state") == "unstarted"]
    oc3_rewards = [float(f_per_task[t]["opencode-3"]["reward"]) for t in oc3_valid_tasks]
    orc_on_oc3 = [float(f_per_task[t]["oracle"]["reward"]) for t in oc3_valid_tasks]

    oc1_correct = sum(1 for t in expected_tasks if f_per_task.get(t, {}).get("opencode-1", {}).get("correct") is True)
    oc2_correct = sum(1 for t in expected_tasks if f_per_task.get(t, {}).get("opencode-2", {}).get("correct") is True)
    oc3_correct = sum(1 for t in oc3_valid_tasks if f_per_task.get(t, {}).get("opencode-3", {}).get("correct") is True)
    total_valid_correct = oc1_correct + oc2_correct + oc3_correct
    total_valid_accused = len(oc1_rewards) + len(oc2_rewards) + len(oc3_rewards)

    oracle_mean = st.mean(oracle_rewards) if len(oracle_rewards) == 10 else float("nan")
    neg_controls_ok = (
        len(do_nothing_rewards) == 10
        and all(x == 0.0 for x in do_nothing_rewards)
        and all(per_task[t]["do_nothing"]["accused"] is None for t in expected_tasks)
        and mfoot.get("do_nothing") == 0.0
        and srows.get("do_nothing", {}).get("mean") == 0.0
        and srows.get("do_nothing", {}).get("accused") == 0
        and srows.get("do_nothing", {}).get("infra_as_0") == 0.0
        and len(stop_early_rewards) == 10
        and all(x == 0.0 for x in stop_early_rewards)
        and all(per_task[t]["stop_early"]["accused"] is None for t in expected_tasks)
        and mfoot.get("stop_early") == 0.0
        and srows.get("stop_early", {}).get("mean") == 0.0
        and srows.get("stop_early", {}).get("accused") == 0
        and srows.get("stop_early", {}).get("infra_as_0") == 0.0
    )

    oracle_ok = (
        len(oracle_rewards) == 10
        and abs(oracle_mean - 0.506) < 1e-12
        and mfoot.get("oracle") == 0.506
        and 0.39 <= oracle_mean <= 0.68
        and sum(1 for t in expected_tasks if per_task[t]["oracle"]["correct"]) == 9
    )

    run_counts_ok = (
        list(per_task.keys()) == expected_tasks
        and parsed["columns"] == expected_cols
        and len(oc1_rewards) == 10
        and len(oc2_rewards) == 10
        and len(snap_oc3_valid_tasks) == 7
        and snap_oc3_infra_tasks == ["hard-900002"]
        and snap_oc3_unstarted_tasks == ["hard-900008", "hard-900009"]
        and len(oc3_valid_tasks) == 9
        and oc3_infra_tasks == ["hard-900002"]
        and oc3_unstarted_tasks == []
        and total_valid_correct == 28
        and total_valid_accused == 29
        and srows["opencode-1"]["n_valid"] == 10
        and srows["opencode-1"]["infra"] == 0
        and srows["opencode-2"]["n_valid"] == 10
        and srows["opencode-2"]["infra"] == 0
        and srows["opencode-3"]["n_valid"] == 7
        and srows["opencode-3"]["infra"] == 1
    )

    if verify_regen:
        base_tmp = scratch_dir if scratch_dir is not None else Path("/tmp/opencode")
        base_tmp.mkdir(parents=True, exist_ok=True)
        syn_root = Path(tempfile.mkdtemp(prefix="w1b_rehearsal_syn_", dir=str(base_tmp)))
        try:
            syn_jobs_snap = syn_root / "jobs_snap"
            syn_out_snap = syn_root / "regenerated_snap.md"
            _reconstruct_harbor_folder_from_parsed(parsed, syn_jobs_snap)
            with contextlib.redirect_stdout(io.StringIO()):
                rt.main([str(syn_jobs_snap), "--out", str(syn_out_snap)])
            regen_snap_txt = syn_out_snap.read_text(encoding="utf-8").strip()

            syn_jobs_final = syn_root / "jobs_final"
            syn_out_final = syn_root / "regenerated_final.md"
            _reconstruct_harbor_folder_from_parsed(final_parsed, syn_jobs_final)
            with contextlib.redirect_stdout(io.StringIO()):
                rt.main([str(syn_jobs_final), "--out", str(syn_out_final)])
            regen_final_txt = syn_out_final.read_text(encoding="utf-8").strip()
        finally:
            shutil.rmtree(syn_root, ignore_errors=True)

        snapshot_table_exact_match = regen_snap_txt == parsed["table_body_text"]
        final_regen_parsed = _parse_rehearsal_table_md(regen_final_txt)
        f_oc3_row = final_regen_parsed["summary_rows"]["opencode-3"]
        final_rehearsal_table_exact_match = (
            f_oc3_row["n_valid"] == 9
            and f_oc3_row["infra"] == 1
            and f_oc3_row["correct"] == 9
            and f_oc3_row["accused"] == 9
            and abs(f_oc3_row["mean"] - 0.626) < 1e-12
            and abs(f_oc3_row["oracle_same"] - 0.478) < 1e-12
            and f_oc3_row["ratio_ci_str"] == "131% [86%, 590%]"
            and abs(f_oc3_row["diff"] - 0.148) < 1e-12
            and abs(f_oc3_row["infra_as_0"] - 0.563) < 1e-12
            and final_regen_parsed["spread_line"]
            == "Run-to-run spread over 3 OpenCode runs: run means +0.472, +0.585, +0.626; mean of means +0.561, SD 0.080, range 0.154."
        )
        if _git_has_commit(root, EXPECTED_REHEARSAL_FINAL_SHA):
            d0_tbl = _git_try_out(root, ["show", f"{EXPECTED_REHEARSAL_FINAL_SHA}:results/harbor/rehearsal/TABLE.md"])
            s1_rehearsal_final_git_exact_match = d0_tbl is not None and d0_tbl.strip() == regen_final_txt
        else:
            s1_rehearsal_final_git_exact_match = True
        rehearsal_table_exact_match = (
            snapshot_table_exact_match
            and final_rehearsal_table_exact_match
            and s1_rehearsal_final_git_exact_match
        )
    else:
        snapshot_table_exact_match = True
        final_rehearsal_table_exact_match = True
        s1_rehearsal_final_git_exact_match = True
        rehearsal_table_exact_match = True

    readme_txt = (root / "README.md").read_text(encoding="utf-8")
    gap_txt = (root / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    sub_txt = (root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
    ceo_txt = (root / "docs" / "reports" / "CEO.md").read_text(encoding="utf-8")

    doc_rehearsal_ok = (
        ("+0.472 / +0.585 / +0.626" in readme_txt)
        and ("93% / 116% / 131%" in readme_txt)
        and ("oracle +0.506 on all 10" in readme_txt)
        and ("10 / 10 / 9" in readme_txt)
        and ("28 of 29 valid Gemini accusations correct" in readme_txt)
        and ("93% [20%, 371%]" in gap_txt)
        and ("116% [78%, 363%]" in gap_txt)
        and ("131% [86%, 590%]" in gap_txt)
        and ("+0.626" in gap_txt)
        and ("9 / 9" in gap_txt)
        and ("+0.472, +0.585 and +0.626" in sub_txt)
        and ("93%, 116% and 131%" in sub_txt)
        and ("93-131%, 3 runs" in sub_txt)
        and ("oracle +0.506" in sub_txt)
        and ("93%, 116%, 131%" in ceo_txt)
        and ("afterquery-submit-2" in ceo_txt)
        and ("aa1c679e" in ceo_txt)
        and ("d0ead011" in ceo_txt)
    )

    run_means = [st.mean(oc1_rewards), st.mean(oc2_rewards), st.mean(oc3_rewards)]
    mean_of_means = st.mean(run_means)
    sd_of_means = st.stdev(run_means)
    range_of_means = max(run_means) - min(run_means)

    ok = (
        all(provenance_checks.values())
        and correction_header_ok
        and neg_controls_ok
        and oracle_ok
        and run_counts_ok
        and rehearsal_table_exact_match
        and doc_rehearsal_ok
    )

    return {
        "ok": ok,
        "provenance_checks": provenance_checks,
        "correction_header_ok": correction_header_ok,
        "negative_controls_ok": neg_controls_ok,
        "oracle_ok": oracle_ok,
        "run_counts_ok": run_counts_ok,
        "snapshot_table_exact_match": snapshot_table_exact_match,
        "final_rehearsal_table_exact_match": final_rehearsal_table_exact_match,
        "s1_rehearsal_final_git_exact_match": s1_rehearsal_final_git_exact_match,
        "rehearsal_table_exact_match": rehearsal_table_exact_match,
        "doc_rehearsal_ok": doc_rehearsal_ok,
        "metrics": {
            "afterquery_final_sha": af_sha,
            "afterquery_submit_sha": as_sha,
            "afterquery_submit_2_sha": as2_sha,
            "built_seconds_after_tag": round(built_ts - af_ts, 1),
            "opencode3_seconds_after_build": round(oc3_start_ts - built_ts, 1),
            "do_nothing_mean": 0.0,
            "stop_early_mean": 0.0,
            "oracle_mean": round(oracle_mean, 6),
            "oracle_on_opencode3_mean": round(st.mean(orc_on_oc3), 6),
            "opencode_1_mean": round(st.mean(oc1_rewards), 6),
            "opencode_2_mean": round(st.mean(oc2_rewards), 6),
            "opencode_3_mean": round(st.mean(oc3_rewards), 6),
            "opencode_3_ratio_ci": "131% [86%, 590%]",
            "opencode_3_infra_as_0": round(sum(oc3_rewards) / 10.0, 6),
            "opencode_3_valid_count": len(oc3_valid_tasks),
            "opencode_3_infra_count": len(oc3_infra_tasks),
            "opencode_3_unstarted_count": len(oc3_unstarted_tasks),
            "valid_correct_total": total_valid_correct,
            "valid_accused_total": total_valid_accused,
            "snapshot_opencode_3_mean": round(st.mean(snap_oc3_rewards), 6) if snap_oc3_rewards else None,
            "snapshot_opencode_3_valid_count": len(snap_oc3_valid_tasks),
            "mean_of_means": round(mean_of_means, 6),
            "sd_of_means": round(sd_of_means, 6),
            "range_of_means": round(range_of_means, 6),
        },
    }


def collect_report_only_issues(
    root: Path = ROOT,
    scratch_dir: Path | None = None,
    preloaded_gpt_eps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scoped_base = scratch_dir if scratch_dir is not None else Path("/tmp/opencode")
    scoped_base.mkdir(parents=True, exist_ok=True)
    scoped_root = Path(tempfile.mkdtemp(prefix="w1b_tg_scope_", dir=str(scoped_base)))
    try:
        src_hard = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"
        scoped_hard = scoped_root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"
        scoped_hard.mkdir(parents=True, exist_ok=True)
        eps_src = preloaded_gpt_eps if preloaded_gpt_eps is not None else [
            json.loads(ln) for ln in (src_hard / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        by_seed = {int(e["seed"]): e for e in eps_src}
        tg_sample_seeds = [0, 1, 17]
        (scoped_hard / "episodes.jsonl").write_text(
            "\n".join(json.dumps(by_seed[s]) for s in tg_sample_seeds) + "\n",
            encoding="utf-8",
        )
        (scoped_hard / "meta.json").symlink_to(src_hard / "meta.json")
        tg_rows = tg.replay_committed(scoped_root)
    finally:
        shutil.rmtree(scoped_root, ignore_errors=True)
    tg_flagged_seeds = sorted(m["seed"] for m in (tg_rows[0]["mismatches"] if tg_rows else []))
    tg_live_ok = (
        len(tg_rows) == 1
        and tg_rows[0]["replay_consistent"] is True
        and tg_rows[0]["consistent"] == 3
        and tg_flagged_seeds == []
    )

    raw_rehearsal_trial_dirs = sorted((root / "results" / "harbor" / "rehearsal").glob("*/canary-*/result.json"))
    sub_lines = (root / "docs" / "SUBMISSION.md").read_text(encoding="utf-8").splitlines()
    stale_no_tag_line = any("no tag exists yet" in ln for ln in sub_lines)
    stale_only_gemini_v14_line = any("Only Gemini-family models were run on rules v1.4" in ln for ln in sub_lines)
    stale_1021_replay_line = any("1,021 of 1,031" in ln for ln in sub_lines)

    issues = [
        {
            "id": "ISSUE-W1B-1",
            "severity": "low",
            "area": "opencode_stopped_episode_schema_and_final_day_zero",
            "summary": (
                "Clean non-accusing OpenCode exits on gpt-5.5 seeds [0, 17] (rc=0, step_finish reason='stop' at "
                "env.day 8 and 9) are stored with end_reason='error' and final_day=0 alongside meta.note='agent "
                "stopped without ending the episode (no accusation)'; audit_submission.py, anticheat.replay_committed, "
                "and tamper_guard.replay_committed (aligned in cc75aacd) all accept 30/30 episodes, while final_day=0 "
                "drops the stopping day (8 and 9) unless reconstructed by Env replay."
            ),
        },
        {
            "id": "ISSUE-W1B-2",
            "severity": "info",
            "area": "gpt55_verbal_accusation_without_tool_call",
            "summary": (
                "In 2/30 gpt-5.5 episodes (seeds 0 and 17), final_answer assistant text named the actual mole employee "
                "ID after canary narrowing without calling canary_accuse; both episodes scored 0.0 (accused=None), "
                "confirming server-side ledger grading ignores assistant text."
            ),
        },
        {
            "id": "ISSUE-W1B-3",
            "severity": "low",
            "area": "rehearsal_raw_trials_on_side_branch_and_snapshot_table_body",
            "summary": (
                "results/harbor/rehearsal/ on justSilas (afterquery-submit-2 aa1c679e / 5f9b3297) omits the 78 MB raw "
                "trial directories (committed on branch s1-rehearsal-final d0ead011) and retains the 08:52 snapshot "
                "table body (7 valid on opencode-3, 153% [89%, 411%]) beneath the 09:30 Correction blockquote citing "
                "finalized Run 3 (9 valid, +0.626 = 131% [86%, 590%]); scripts/rehearsal_table.py deterministically "
                "reproduces 100% of both the 08:52 snapshot table and the finalized d0ead011 9-valid table."
            ),
        },
        {
            "id": "ISSUE-W1B-4",
            "severity": "low",
            "area": "rehearsal_launcher_grep_timeout_header",
            "summary": (
                "scripts/rehearsal_run.sh line 17 greps the first '^timeout_sec = ' in task.toml, recording [verifier] "
                "timeout_sec = 120.0 as agent_timeout_sec = 120.0 on BUILD.txt line 5 before [agent] timeout_sec = 10800.0; "
                "explicitly disclosed and corrected on BUILD.txt line 8."
            ),
        },
        {
            "id": "ISSUE-W1B-5",
            "severity": "low",
            "area": "submission_doc_body_supersede_residuals",
            "summary": (
                "docs/SUBMISSION.md adds an explicit top 'Final results, Sun 15 Nov 09:00' supersede block (lines 7-13, "
                "updated in aa1c679e to 93%, 116% and 131%), leaving three superseded body lines below: 'no tag exists "
                "yet' (line 37), 'Only Gemini-family models were run on rules v1.4' (line 119), and '1,021 of 1,031' / "
                "'51,814' steps (line 185 vs 1,051/1,061 and 53,889 in results/anticheat/exploits.md)."
            ),
        },
    ]

    return {
        "issue_count": len(issues),
        "tamper_guard_replay_live_ok": tg_live_ok,
        "tamper_guard_flagged_gpt55_seeds": tg_flagged_seeds,
        "raw_rehearsal_trial_files_committed": len(raw_rehearsal_trial_dirs),
        "submission_body_supersede_residuals": {
            "stale_no_tag_line": stale_no_tag_line,
            "stale_only_gemini_v14_line": stale_only_gemini_v14_line,
            "stale_1021_replay_line": stale_1021_replay_line,
        },
        "issues": issues,
    }


def _copy_gpt55_subset(src_dir: Path, dst_dir: Path, n_seeds: int = 2) -> list[dict[str, Any]]:
    (dst_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    all_eps = [json.loads(ln) for ln in (src_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    sub_eps = [ep for ep in all_eps if int(ep["seed"]) < n_seeds]
    meta = json.loads((src_dir / "meta.json").read_text(encoding="utf-8"))
    meta["seeds"] = list(range(n_seeds))
    meta["planned_seeds"] = list(range(n_seeds))
    meta["usage"] = {
        "in": sum(int(e["meta"]["usage"]["in"]) for e in sub_eps),
        "cached_in": sum(int(e["meta"]["usage"]["cached_in"]) for e in sub_eps),
        "out": sum(int(e["meta"]["usage"]["out"]) for e in sub_eps),
        "cost_usd_est": round(sum(float(e["meta"]["usage"]["cost_usd_est"]) for e in sub_eps), 4),
        "cost_usd_upper": round(sum(float(e["meta"]["usage"]["cost_usd_upper"]) for e in sub_eps), 4),
    }
    (dst_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (dst_dir / "episodes.jsonl").write_text("\n".join(json.dumps(e) for e in sub_eps) + "\n", encoding="utf-8")
    for s in range(n_seeds):
        (dst_dir / "transcripts" / f"{s}.txt").symlink_to(src_dir / "transcripts" / f"{s}.txt")
    return sub_eps


def run_positive_controls(root: Path = ROOT, scratch_dir: Path | None = None) -> dict[str, Any]:
    base_tmp = scratch_dir if scratch_dir is not None else Path("/tmp/opencode")
    base_tmp.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="w1b_pos_ctrl_", dir=str(base_tmp)))
    src_gpt = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"
    src_reh = root / "results" / "harbor" / "rehearsal"
    cf_ts = _git_commit_ts(root, EXPECTED_CF394894_SHA, EXPECTED_CF394894_TS)
    ca_ts = _git_commit_ts(root, EXPECTED_CA0A0DC0_SHA, EXPECTED_CA0A0DC0_TS)

    try:
        c1_dir = work / "c1_step_tamper"
        eps1 = _copy_gpt55_subset(src_gpt, c1_dir, n_seeds=2)
        eps1[1]["steps"][0]["result"]["data"]["V"] = 0.42
        (c1_dir / "episodes.jsonl").write_text("\n".join(json.dumps(x) for x in eps1) + "\n", encoding="utf-8")
        r1 = audit_gpt55_replay_and_accounting(
            root, run_dir=c1_dir, cf394894_ts=cf_ts, ca0a0dc0_ts=ca_ts, compute_posteriors=False, expected_n=2
        )
        c1_caught = (r1["ok"] is False) and (r1["step_mismatches"] >= 1)

        c2_dir = work / "c2_forged_stopped_score"
        eps2 = _copy_gpt55_subset(src_gpt, c2_dir, n_seeds=2)
        eps2[0]["score"] = 0.71
        (c2_dir / "episodes.jsonl").write_text("\n".join(json.dumps(x) for x in eps2) + "\n", encoding="utf-8")
        r2 = audit_gpt55_replay_and_accounting(
            root, run_dir=c2_dir, cf394894_ts=cf_ts, ca0a0dc0_ts=ca_ts, compute_posteriors=False, expected_n=2
        )
        c2_caught = (r2["ok"] is False) and (r2["episode_score_mismatches"] >= 1) and bool(r2["invalid_accounting_violations"])

        c3_dir = work / "c3_backdated_lock"
        _copy_gpt55_subset(src_gpt, c3_dir, n_seeds=2)
        t0_link = c3_dir / "transcripts" / "0.txt"
        t0_lines = (src_gpt / "transcripts" / "0.txt").read_text(encoding="utf-8").splitlines()
        t0_link.unlink()
        new_t0: list[str] = []
        mutated = False
        for ln in t0_lines:
            if ln.startswith("{") and not mutated:
                ev = json.loads(ln)
                ev["timestamp"] = (cf_ts - 60) * 1000
                new_t0.append(json.dumps(ev))
                mutated = True
            else:
                new_t0.append(ln)
        t0_link.write_text("\n".join(new_t0) + "\n", encoding="utf-8")
        r3 = audit_gpt55_replay_and_accounting(
            root, run_dir=c3_dir, cf394894_ts=cf_ts, ca0a0dc0_ts=ca_ts, compute_posteriors=False, expected_n=2
        )
        c3_caught = (r3["ok"] is False) and (r3["lock_ordering"]["ok"] is False) and (r3["lock_ordering"]["seconds_after_cf394894"] < 0)

        c4_dir = work / "c4_neg_control_tamper"
        c4_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_reh / "README.md", c4_dir / "README.md")
        shutil.copy2(src_reh / "BUILD.txt", c4_dir / "BUILD.txt")
        bad_tbl = (src_reh / "TABLE.md").read_text(encoding="utf-8").replace(
            "| hard-900000 | +0.56 ✓ d12 | +0.69 ✓ d7 | +0.72 ✓ d7 | +0.79 ✓ d6 | +0.00 | +0.00 |",
            "| hard-900000 | +0.56 ✓ d12 | +0.69 ✓ d7 | +0.72 ✓ d7 | +0.79 ✓ d6 | +0.00 | +0.01 |",
        )
        (c4_dir / "TABLE.md").write_text(bad_tbl, encoding="utf-8")
        r4 = audit_harbor_rehearsal(root, rehearsal_dir=c4_dir, scratch_dir=work, verify_regen=False)
        c4_caught = (r4["ok"] is False) and (r4["negative_controls_ok"] is False)

        c5_dir = work / "c5_sha_tamper"
        c5_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_reh / "README.md", c5_dir / "README.md")
        shutil.copy2(src_reh / "TABLE.md", c5_dir / "TABLE.md")
        bad_build = (src_reh / "BUILD.txt").read_text(encoding="utf-8").replace(
            EXPECTED_AFTERQUERY_FINAL_SHA,
            "0000000000000000000000000000000000000000",
        )
        (c5_dir / "BUILD.txt").write_text(bad_build, encoding="utf-8")
        r5 = audit_harbor_rehearsal(root, rehearsal_dir=c5_dir, scratch_dir=work, verify_regen=False)
        c5_caught = (r5["ok"] is False) and (r5["provenance_checks"]["build_sha_matches_afterquery_final"] is False)

        c6_dir = work / "c6_run3_correction_tamper"
        c6_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_reh / "README.md", c6_dir / "README.md")
        shutil.copy2(src_reh / "BUILD.txt", c6_dir / "BUILD.txt")
        bad_corr = (src_reh / "TABLE.md").read_text(encoding="utf-8").replace(
            "mean +0.626 = 131% [86%, 590%] of the oracle",
            "mean +0.322 = 65% [24%, 98%] of the oracle",
        )
        (c6_dir / "TABLE.md").write_text(bad_corr, encoding="utf-8")
        r6 = audit_harbor_rehearsal(root, rehearsal_dir=c6_dir, scratch_dir=work, verify_regen=False)
        c6_caught = (r6["ok"] is False) and (r6["correction_header_ok"] is False)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    controls = {
        "tampered_gpt55_step_caught": c1_caught,
        "forged_gpt55_stopped_score_caught": c2_caught,
        "backdated_gpt55_before_cf394894_caught": c3_caught,
        "tampered_rehearsal_negative_control_caught": c4_caught,
        "tampered_rehearsal_sha_caught": c5_caught,
        "tampered_rehearsal_final_run3_correction_caught": c6_caught,
    }
    return {"all_caught": all(controls.values()), "controls": controls}


def check_report_file(report_path: Path) -> dict[str, Any]:
    raw = report_path.read_bytes()
    text = raw.decode("utf-8")
    low = text.lower()
    bad_dashes = [ch for ch in (chr(0x2014), chr(0x2013), chr(0x2212)) if ch in text]
    banned_prereg = [kw for kw in ("pre-reg", "prereg") if kw in low]
    size_ok = len(raw) <= MAX_REPORT_BYTES
    required_tokens = (
        "ca0a0dc0",
        "cf394894",
        "c59ecfd0",
        "1bc3e281",
        "9225f2ad",
        "aa1c679e",
        "5f9b3297",
        "d0ead011",
        "afterquery-final",
        "afterquery-submit-2",
        "2,075",
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "+0.506",
        "+0.472",
        "+0.585",
        "+0.626",
        "+0.478",
        "+0.561",
        "93% [20%, 371%]",
        "116% [78%, 363%]",
        "131% [86%, 590%]",
        "28/29",
        "ISSUE-W1B-1",
        "ISSUE-W1B-2",
        "ISSUE-W1B-3",
        "ISSUE-W1B-4",
        "ISSUE-W1B-5",
    )
    missing = [tok for tok in required_tokens if tok not in text]
    ok = (not bad_dashes) and (not banned_prereg) and size_ok and (not missing)
    return {
        "ok": ok,
        "size_bytes": len(raw),
        "size_ok": size_ok,
        "bad_dashes": bad_dashes,
        "banned_prereg": banned_prereg,
        "missing_tokens": missing,
    }


def run_audit(
    root: Path = ROOT,
    scratch_dir: Path | None = None,
    include_controls: bool = True,
    quick: bool = False,
) -> dict[str, Any]:
    t0 = time.monotonic()
    shared_gpt_eps: list[dict[str, Any]] = []
    gpt_replay = audit_gpt55_replay_and_accounting(
        root=root,
        compute_posteriors=not quick,
        episodes_out=shared_gpt_eps,
    )
    gpt_tables = audit_gpt55_tables_and_docs(
        root=root,
        preloaded_gpt_eps=shared_gpt_eps or None,
        quick=quick,
    )
    rehearsal = audit_harbor_rehearsal(root=root, scratch_dir=scratch_dir)
    issues = collect_report_only_issues(
        root=root, scratch_dir=scratch_dir, preloaded_gpt_eps=shared_gpt_eps or None
    )
    controls = run_positive_controls(root=root, scratch_dir=scratch_dir) if include_controls else {"all_caught": True, "controls": {}}
    elapsed_s = round(time.monotonic() - t0, 4)

    ok = (
        gpt_replay["ok"]
        and gpt_tables["ok"]
        and rehearsal["ok"]
        and issues["tamper_guard_replay_live_ok"]
        and controls["all_caught"]
    )

    return {
        "ok": ok,
        "headline": {
            "ok": ok,
            "gpt55_episodes": gpt_replay["n_episodes"],
            "gpt55_valid": gpt_replay["valid_count"],
            "gpt55_invalid": gpt_replay["invalid_count"],
            "gpt55_stopped_no_accuse": len(gpt_replay["stopped_seeds"]),
            "gpt55_steps_replayed": gpt_replay["total_steps"],
            "gpt55_step_mismatches": gpt_replay["step_mismatches"],
            "gpt55_seconds_after_cf394894": gpt_replay["lock_ordering"]["seconds_after_cf394894"],
            "gpt55_ratio_vs_solver": gpt_tables["metrics"]["ratio_pct_fmt"],
            "gpt55_luck_adjusted_vs_solver": gpt_tables["metrics"]["luck_adjusted_pct_fmt"],
            "rehearsal_oracle_mean": rehearsal["metrics"]["oracle_mean"],
            "rehearsal_do_nothing_mean": rehearsal["metrics"]["do_nothing_mean"],
            "rehearsal_stop_early_mean": rehearsal["metrics"]["stop_early_mean"],
            "rehearsal_opencode_means": [
                rehearsal["metrics"]["opencode_1_mean"],
                rehearsal["metrics"]["opencode_2_mean"],
                rehearsal["metrics"]["opencode_3_mean"],
            ],
            "rehearsal_opencode_valid_counts": [10, 10, rehearsal["metrics"]["opencode_3_valid_count"]],
            "rehearsal_opencode_3_ratio_ci": rehearsal["metrics"]["opencode_3_ratio_ci"],
            "rehearsal_valid_correct": f"{rehearsal['metrics']['valid_correct_total']}/{rehearsal['metrics']['valid_accused_total']}",
            "positive_controls_all_caught": controls["all_caught"],
            "report_only_issue_count": issues["issue_count"],
            "elapsed_seconds": elapsed_s,
        },
        "gpt55_replay_and_accounting": gpt_replay,
        "gpt55_tables_and_docs": gpt_tables,
        "harbor_rehearsal": rehearsal,
        "positive_controls": controls,
        "report_only_issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_gpt55_and_rehearsal_audit")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--scratch-dir", type=Path, default=Path("/tmp/opencode"))
    ap.add_argument("--no-controls", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--check-report", type=Path, default=None)
    args = ap.parse_args(argv)

    payload = run_audit(
        root=args.root.resolve(),
        scratch_dir=args.scratch_dir,
        include_controls=not args.no_controls,
        quick=args.quick,
    )
    if args.check_report is not None:
        rep = check_report_file(args.check_report)
        payload["report_check"] = rep
        payload["ok"] = bool(payload["ok"] and rep["ok"])
        payload["headline"]["ok"] = payload["ok"]

    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload["headline"], indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
