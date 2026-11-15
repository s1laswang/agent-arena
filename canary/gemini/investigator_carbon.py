from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys
from typing import Any, Iterable

from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result
from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute as attribute_regret

ROLE_NAME = "investigators"
TARGET_MODEL = "gemini-4-carbon"
EXPECTED_TIERS_VERSION = "v1.4"
DEFAULT_ROLE_DIR = Path("results/gemini/roles_carbon/investigators")
DEFAULT_DOC_PATH = Path("docs/gemini/roles_carbon/investigators.md")

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FORBIDDEN_DASHES = (EM_DASH, EN_DASH)

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")
ENV_KEY_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]*\"|'[^']*'|[^\s\"',}\]]*)"
)
SAFE_PLACEHOLDERS = frozenset({
    "",
    "null",
    "none",
    "false",
    "true",
    "unset",
    "redacted",
    "[redacted]",
    "<redacted>",
    "empty",
    "missing",
})
REDACTED_SIG_PREFIX = "<redacted_thought_signature_chars:"


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def _is_pos_num(val: Any) -> bool:
    return _is_num(val) and float(val) > 0.0


def scan_text_secrets(text: str) -> list[str]:
    findings: list[str] = []
    if GOOGLE_KEY_RE.search(text):
        findings.append("google_api_key")
    if SK_KEY_RE.search(text):
        findings.append("sk_api_key")
    if OAUTH_RE.search(text):
        findings.append("oauth_token")
    for match in ENV_KEY_RE.finditer(text):
        raw = match.group(1).strip()
        quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
        inner = raw[1:-1].strip() if quoted else raw
        if inner.lower() in SAFE_PLACEHOLDERS:
            continue
        if set(inner) <= {"*"} or inner.startswith("$"):
            continue
        if not quoted and "=" in inner:
            continue
        if len(inner) >= 4:
            findings.append("env_api_key")
    return findings


def scan_text_hygiene(text: str) -> list[str]:
    issues = scan_text_secrets(text)
    if EM_DASH in text:
        issues.append("em_dash")
    if EN_DASH in text:
        issues.append("en_dash")
    stale_prefix = "/".join(("results", "gemini_roles", ""))
    if stale_prefix in text:
        issues.append("stale_gemini_roles_path")
    return issues


def redact_transcript_signatures(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    out_msgs: list[dict[str, Any]] = json.loads(json.dumps(messages))
    redacted_now = 0
    total_sigs = 0
    for msg in out_msgs:
        if not isinstance(msg, dict):
            continue
        p_items = msg.get("provider_items")
        if not isinstance(p_items, list):
            continue
        for p_item in p_items:
            if not isinstance(p_item, dict):
                continue
            parts = p_item.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                raw_sig = part.get("thought_signature")
                if isinstance(raw_sig, str):
                    total_sigs += 1
                    if not raw_sig.startswith(REDACTED_SIG_PREFIX):
                        sig_len = len(raw_sig)
                        sig_sha = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()
                        part["thought_signature"] = f"{REDACTED_SIG_PREFIX}{sig_len}>"
                        part["thought_signature_sha256"] = sig_sha
                        part["thought_signature_len"] = sig_len
                        redacted_now += 1
                elif isinstance(part.get("thought_signature_sha256"), str):
                    total_sigs += 1
    return out_msgs, {"total_signatures": total_sigs, "redacted_now": redacted_now}


def audit_transcript_data(data: Any) -> dict[str, Any]:
    messages = data if isinstance(data, list) else (data.get("messages") if isinstance(data, dict) else None)
    if not isinstance(messages, list) or not messages:
        return {
            "valid": False,
            "message_count": 0,
            "assistant_turns": 0,
            "tool_call_turns": 0,
            "thought_parts": 0,
            "signature_parts": 0,
            "sha256_parts": 0,
            "unredacted_signatures": 0,
            "errors": ["empty_or_invalid_transcript"],
        }

    assistant_turns = 0
    tool_call_turns = 0
    thought_parts = 0
    signature_parts = 0
    sha256_parts = 0
    unredacted = 0
    errors: list[str] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        assistant_turns += 1
        tcalls = msg.get("tool_calls")
        if isinstance(tcalls, list) and len(tcalls) > 0:
            tool_call_turns += 1
        p_items = msg.get("provider_items")
        if not isinstance(p_items, list):
            continue
        for p_item in p_items:
            if not isinstance(p_item, dict):
                continue
            parts = p_item.get("parts")
            if not isinstance(parts, list):
                continue
            has_fc = any(isinstance(pt, dict) and pt.get("function_call") for pt in parts)
            for pt in parts:
                if not isinstance(pt, dict):
                    continue
                if pt.get("thought") is True or (has_fc and isinstance(pt.get("text"), str) and pt["text"].strip()):
                    thought_parts += 1
                raw_sig = pt.get("thought_signature")
                sha_sig = pt.get("thought_signature_sha256")
                if isinstance(raw_sig, str):
                    if raw_sig.startswith(REDACTED_SIG_PREFIX) and raw_sig.endswith(">"):
                        signature_parts += 1
                    else:
                        unredacted += 1
                elif isinstance(sha_sig, str) and SHA256_RE.fullmatch(sha_sig):
                    signature_parts += 1
                if isinstance(sha_sig, str):
                    if SHA256_RE.fullmatch(sha_sig):
                        sha256_parts += 1
                    else:
                        errors.append("invalid_thought_signature_sha256")

    if assistant_turns == 0:
        errors.append("no_assistant_turns")
    if signature_parts == 0:
        errors.append("missing_thought_signatures")
    if unredacted > 0:
        errors.append(f"unredacted_thought_signatures:{unredacted}")

    return {
        "valid": len(errors) == 0,
        "message_count": len(messages),
        "assistant_turns": assistant_turns,
        "tool_call_turns": tool_call_turns,
        "thought_parts": thought_parts,
        "signature_parts": signature_parts,
        "sha256_parts": sha256_parts,
        "unredacted_signatures": unredacted,
        "errors": errors,
    }


def replay_verify_episode(ep: dict[str, Any]) -> dict[str, Any]:
    tier = str(ep["tier"])
    seed = int(ep["seed"])
    env = Env(tier, seed)
    for step in ep.get("steps") or []:
        if env.done:
            break
        env.call(step["tool"], step.get("args") or {})
    res = env.result("replay")
    rec_score = float(ep["score"])
    rec_accused = ep.get("accused")
    rec_correct = bool(ep.get("correct", False))
    rec_day = int(ep.get("final_day", 0))
    ok = (
        abs(res.score - rec_score) < 1e-9
        and res.accused == rec_accused
        and bool(res.correct) == rec_correct
        and int(res.final_day) == rec_day
    )
    v_val = (res.meta or {}).get("V", getattr(env, "V", None))
    return {
        "ok": ok,
        "tier": tier,
        "seed": seed,
        "recorded_score": rec_score,
        "replay_score": float(res.score),
        "recorded_accused": rec_accused,
        "replay_accused": res.accused,
        "recorded_correct": rec_correct,
        "replay_correct": bool(res.correct),
        "recorded_day": rec_day,
        "replay_day": int(res.final_day),
        "steps": len(ep.get("steps") or []),
        "v_at_end": float(v_val) if _is_num(v_val) else None,
    }


def episode_forensics(ep: dict[str, Any], replay_v: float | None = None) -> dict[str, Any]:
    ep_res = to_result(ep)
    acc = audit_episode(ep_res)
    p_accused = acc.get("p_accused")
    p_top = acc.get("p_top")
    verdict = str(acc.get("verdict") or "none")
    meta = ep.get("meta") or {}
    raw_v = meta.get("V", meta.get("V_final", replay_v))
    if not ep.get("accused"):
        luck_adj: float | None = 0.0
    elif _is_num(p_accused) and _is_num(raw_v):
        luck_adj = float(p_accused) * float(raw_v) - (1.0 - float(p_accused))
    else:
        luck_adj = None

    regret_items = attribute_regret(ep_res) or []
    regret_total = 0.0
    tag_counts: Counter[str] = Counter()
    for item in regret_items:
        r_val = float(item.get("regret", 0.0))
        regret_total += r_val
        for tg in item.get("tags") or []:
            tag_counts[str(tg)] += 1

    return {
        "p_accused": float(p_accused) if _is_num(p_accused) else None,
        "p_top": float(p_top) if _is_num(p_top) else None,
        "verdict": verdict,
        "luck_adjusted_score": round(luck_adj, 6) if luck_adj is not None else None,
        "regret_total": round(regret_total, 6),
        "tag_counts": dict(sorted(tag_counts.items())),
    }


_SOLVER_MEMO: dict[tuple[str, int], dict[str, Any]] = {}


def _episode_result_to_dict(res: Any) -> dict[str, Any]:
    return {
        "tier": res.tier,
        "seed": int(res.seed),
        "agent": res.agent,
        "steps": [
            {"t": s.t, "day": s.day, "tool": s.tool, "args": s.args, "result": s.result}
            for s in res.steps
        ],
        "score": float(res.score),
        "accused": res.accused,
        "correct": bool(res.correct),
        "final_day": int(res.final_day),
        "end_reason": res.end_reason,
        "meta": dict(res.meta or {}),
    }


def load_solver_index(root: Path, needed: Iterable[tuple[str, int]]) -> dict[tuple[str, int], dict[str, Any]]:
    index: dict[tuple[str, int], dict[str, Any]] = {}
    ref_root = root / "data" / "runs" / "committed" / "v1.4" / "reference"
    if ref_root.is_dir():
        for ep_file in sorted(ref_root.rglob("episodes.jsonl")):
            if not ep_file.parent.name.startswith("solver-"):
                continue
            for line in ep_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ep = json.loads(line)
                if ep.get("agent") == "solver":
                    key = (str(ep["tier"]), int(ep["seed"]))
                    index[key] = ep

    for tier, seed in sorted(set(needed)):
        key = (str(tier), int(seed))
        if key in index:
            continue
        if key not in _SOLVER_MEMO:
            res = run_episode(Env(key[0], key[1]), SolverPolicy())
            _SOLVER_MEMO[key] = _episode_result_to_dict(res)
        index[key] = _SOLVER_MEMO[key]
    return index


def wilson_ci95(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    z = 1.959963984540054
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = (phat + (z * z) / (2.0 * total)) / denom
    half = (z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)) / denom
    return max(0.0, round(center - half, 6)), min(1.0, round(center + half, 6))


def paired_bootstrap_ratio_ci(
    frontier: list[float],
    solver: list[float],
    n_boot: int = 10000,
    rng_seed: int = 0,
) -> tuple[float | None, float | None]:
    n = len(frontier)
    if n < 2 or len(solver) != n:
        return None, None
    rng = random.Random(rng_seed)
    vals: list[float] = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(solver[i] for i in idx) / n
        if ms > 0.0:
            vals.append((sum(frontier[i] for i in idx) / n) / ms)
    if not vals:
        return None, None
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[max(0, int(0.975 * len(vals)) - 1)]
    return round(lo, 6), round(hi, 6)


def paired_bootstrap_mean_ci(
    xs: list[float],
    n_boot: int = 10000,
    rng_seed: int = 0,
) -> tuple[float | None, float | None]:
    n = len(xs)
    if n == 0:
        return None, None
    if n == 1:
        return round(xs[0], 6), round(xs[0], 6)
    rng = random.Random(rng_seed)
    vals = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = vals[int(0.025 * len(vals))]
    hi = vals[max(0, int(0.975 * len(vals)) - 1)]
    return round(lo, 6), round(hi, 6)


_SOLVER_FORENSICS_MEMO: dict[tuple[str, int, float], dict[str, Any]] = {}


def compute_paired_slice(
    label: str,
    episodes: list[dict[str, Any]],
    solver_index: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(episodes, key=lambda r: (str(r["tier"]), int(r["seed"])))
    n = len(ordered)
    if n == 0:
        return {"slice": label, "n": 0}

    f_scores: list[float] = []
    s_scores: list[float] = []
    diffs: list[float] = []
    f_luck: list[float] = []
    s_luck: list[float] = []
    p_vals: list[float] = []
    acc_days: list[int] = []
    correct_n = 0
    accused_n = 0
    solver_correct_n = 0
    regret_sum = 0.0
    tags_agg: Counter[str] = Counter()

    for row in ordered:
        key = (str(row["tier"]), int(row["seed"]))
        sol_ep = solver_index[key]
        memo_key = (key[0], key[1], float(sol_ep["score"]))
        if memo_key not in _SOLVER_FORENSICS_MEMO:
            sol_rep = replay_verify_episode(sol_ep)
            _SOLVER_FORENSICS_MEMO[memo_key] = episode_forensics(sol_ep, sol_rep["v_at_end"])
        sol_for = _SOLVER_FORENSICS_MEMO[memo_key]

        fs = float(row["score"])
        ss = float(sol_ep["score"])
        f_scores.append(fs)
        s_scores.append(ss)
        diffs.append(fs - ss)
        if row.get("correct"):
            correct_n += 1
        if sol_ep.get("correct"):
            solver_correct_n += 1
        if row.get("accused"):
            accused_n += 1
            acc_days.append(int(row["final_day"]))
        if row.get("p_accused") is not None:
            p_vals.append(float(row["p_accused"]))
        if row.get("luck_adjusted_score") is not None and sol_for["luck_adjusted_score"] is not None:
            f_luck.append(float(row["luck_adjusted_score"]))
            s_luck.append(float(sol_for["luck_adjusted_score"]))
        regret_sum += float(row.get("regret_total", 0.0))
        for k, v in (row.get("tag_counts") or {}).items():
            tags_agg[k] += int(v)

    f_mean, f_ci = mean_ci(f_scores)
    s_mean, s_ci = mean_ci(s_scores)
    d_mean, d_ci = mean_ci(diffs)
    d_boot_lo, d_boot_hi = paired_bootstrap_mean_ci(diffs)
    ratio = (f_mean / s_mean) if s_mean > 0.0 else None
    r_lo, r_hi = paired_bootstrap_ratio_ci(f_scores, s_scores)

    luck_ok = len(f_luck) == n and sum(s_luck) > 0.0
    luck_mean = (sum(f_luck) / n) if len(f_luck) == n else None
    sol_luck_mean = (sum(s_luck) / n) if len(s_luck) == n else None
    luck_ratio = (sum(f_luck) / sum(s_luck)) if luck_ok else None
    luck_lo, luck_hi = paired_bootstrap_ratio_ci(f_luck, s_luck) if luck_ok else (None, None)

    acc_lo, acc_hi = wilson_ci95(correct_n, n)
    sol_acc_lo, sol_acc_hi = wilson_ci95(solver_correct_n, n)

    return {
        "slice": label,
        "n": n,
        "seeds": [int(r["seed"]) for r in ordered],
        "tiers": sorted({str(r["tier"]) for r in ordered}),
        "mean_score": round(f_mean, 6),
        "score_ci95": round(f_ci, 6),
        "accuracy": round(correct_n / n, 6),
        "accuracy_ci95": [acc_lo, acc_hi],
        "accused_rate": round(accused_n / n, 6),
        "mean_accuse_day": round(sum(acc_days) / len(acc_days), 4) if acc_days else None,
        "mean_p_accused": round(sum(p_vals) / len(p_vals), 4) if p_vals else None,
        "solver_mean_score": round(s_mean, 6),
        "solver_score_ci95": round(s_ci, 6),
        "solver_accuracy": round(solver_correct_n / n, 6),
        "solver_accuracy_ci95": [sol_acc_lo, sol_acc_hi],
        "frontier_over_solver_ratio": round(ratio, 6) if ratio is not None else None,
        "frontier_over_solver_ci95": [r_lo, r_hi] if r_lo is not None and r_hi is not None else None,
        "paired_diff_mean": round(d_mean, 6),
        "paired_diff_ci95": round(d_ci, 6),
        "paired_diff_boot_ci95": [d_boot_lo, d_boot_hi],
        "luck_adjusted_mean": round(luck_mean, 6) if luck_mean is not None else None,
        "solver_luck_adjusted_mean": round(sol_luck_mean, 6) if sol_luck_mean is not None else None,
        "luck_adjusted_ratio": round(luck_ratio, 6) if luck_ratio is not None else None,
        "luck_adjusted_ratio_ci95": [luck_lo, luck_hi] if luck_lo is not None and luck_hi is not None else None,
        "regret_total": round(regret_sum, 6),
        "regret_per_episode": round(regret_sum / n, 6),
        "tag_counts": dict(sorted(tags_agg.items())),
    }


def _extract_usage_fields(meta: dict[str, Any]) -> dict[str, Any]:
    usage = meta.get("usage")
    if not isinstance(usage, dict):
        return {
            "valid": False,
            "calls": 0,
            "in": 0,
            "out": 0,
            "thinking": 0,
            "cached": 0,
            "cost_usd": 0.0,
            "cost_usd_est": 0.0,
        }
    calls = int(usage.get("calls", 0) or 0)
    tin = int(usage.get("in", usage.get("in_tokens", 0)) or 0)
    tout = int(usage.get("out", usage.get("out_tokens", 0)) or 0)
    tthink = int(usage.get("thinking", usage.get("thinking_tokens", 0)) or 0)
    tcached = int(usage.get("cached", usage.get("cached_in", usage.get("cached_tokens", 0))) or 0)
    raw_list = usage.get("cost_usd", 0.0)
    raw_est = usage.get("cost_usd_est", raw_list)
    cost_list = float(raw_list) if _is_num(raw_list) else 0.0
    cost_est = float(raw_est) if _is_num(raw_est) else cost_list
    valid = calls > 0 and tin > 0 and tout > 0 and cost_list > 0.0
    return {
        "valid": valid,
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": tthink,
        "cached": tcached,
        "cost_usd": round(cost_list, 6),
        "cost_usd_est": round(cost_est, 6),
    }


def _collect_run_episodes(run_dir: Path, subrole: str) -> list[tuple[str | None, Path, Path]]:
    pairs: list[tuple[str | None, Path, Path]] = []
    top_ep = run_dir / "episodes.jsonl"
    if top_ep.is_file():
        pairs.append((None, top_ep, run_dir / "transcripts"))
    for level in ("minimal", "low", "medium", "high", "xhigh"):
        lv_ep = run_dir / level / "episodes.jsonl"
        if lv_ep.is_file():
            pairs.append((level, lv_ep, run_dir / level / "transcripts"))
    return pairs


def inspect_investigator_run(run_dir: Path, root: Path) -> dict[str, Any]:
    rel_dir = run_dir.resolve().relative_to(root.resolve()).as_posix()
    errors: list[str] = []
    hygiene_hits: list[dict[str, Any]] = []

    for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel_fp = fp.resolve().relative_to(root.resolve()).as_posix()
        if fp.name == "meta.json" and fp.parent != run_dir:
            errors.append(f"nested_meta_json:{rel_fp}")
        try:
            txt = fp.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(f"unreadable_utf8:{rel_fp}")
            continue
        issues = scan_text_hygiene(txt)
        if issues:
            hygiene_hits.append({"file": rel_fp, "issues": issues})
        if fp.suffix == ".json":
            try:
                json.loads(txt)
            except ValueError:
                errors.append(f"invalid_json:{rel_fp}")

    if hygiene_hits:
        errors.append("hygiene_violation")

    meta_path = run_dir / "meta.json"
    summary_path = run_dir / "summary.md"
    if not meta_path.is_file():
        errors.append("missing_meta_json")
        return {"run_dir": rel_dir, "verified": False, "errors": errors, "hygiene_hits": hygiene_hits}
    if not summary_path.is_file() or summary_path.stat().st_size < 80:
        errors.append("missing_or_short_summary_md")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except ValueError:
        return {"run_dir": rel_dir, "verified": False, "errors": errors + ["invalid_meta_json"], "hygiene_hits": hygiene_hits}

    if meta.get("role") != ROLE_NAME:
        errors.append(f"wrong_role:{meta.get('role')}")
    subrole = str(meta.get("subrole") or "").strip()
    if not subrole:
        errors.append("missing_subrole")
    if meta.get("model_id") != TARGET_MODEL:
        errors.append(f"wrong_model:{meta.get('model_id')}")
    if meta.get("tiers_version") != EXPECTED_TIERS_VERSION:
        errors.append(f"wrong_tiers_version:{meta.get('tiers_version')}")
    commit = str(meta.get("commit") or "").strip()
    if not COMMIT_RE.fullmatch(commit):
        errors.append(f"invalid_commit:{commit[:40]}")
    for flag in ("fake_env", "smoke", "stub", "synthetic"):
        if bool(meta.get(flag)):
            errors.append(f"disallowed_flag:{flag}")

    usage = _extract_usage_fields(meta)
    if not usage["valid"]:
        errors.append("invalid_usage")

    ep_sources = _collect_run_episodes(run_dir, subrole)
    if not ep_sources:
        errors.append("missing_episodes_jsonl")

    episode_rows: list[dict[str, Any]] = []
    transcript_audits: list[dict[str, Any]] = []

    for level, ep_file, tx_dir in ep_sources:
        raw_lines = [ln for ln in ep_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not raw_lines:
            errors.append(f"empty_episodes:{ep_file.name}")
            continue
        for ln in raw_lines:
            ep = json.loads(ln)
            if (ep.get("meta") or {}).get("valid") is False or ep.get("end_reason") == "error":
                errors.append(f"invalid_episode:{ep.get('tier')}:{ep.get('seed')}")
                continue
            rep = replay_verify_episode(ep)
            if not rep["ok"]:
                errors.append(f"replay_mismatch:{rep['tier']}:{rep['seed']}")
            forens = episode_forensics(ep, rep["v_at_end"])
            seed = int(ep["seed"])
            tx_path = tx_dir / f"{seed}.json"
            if not tx_path.is_file():
                errors.append(f"missing_transcript:{level or 'top'}:{seed}")
                tx_audit = {"valid": False, "signature_parts": 0, "sha256_parts": 0, "thought_parts": 0, "errors": ["missing_file"]}
            else:
                tx_data = json.loads(tx_path.read_text(encoding="utf-8"))
                tx_audit = audit_transcript_data(tx_data)
                if not tx_audit["valid"]:
                    errors.append(f"transcript_invalid:{level or 'top'}:{seed}:{','.join(tx_audit['errors'])}")
            transcript_audits.append({"level": level, "seed": seed, **tx_audit})

            episode_rows.append({
                "run_name": run_dir.name,
                "run_dir": rel_dir,
                "subrole": subrole,
                "level": level,
                "hint": meta.get("hint"),
                "tier": str(ep["tier"]),
                "seed": seed,
                "agent": str(ep.get("agent") or ""),
                "score": float(ep["score"]),
                "accused": ep.get("accused"),
                "correct": bool(ep.get("correct", False)),
                "final_day": int(ep.get("final_day", 0)),
                "end_reason": str(ep.get("end_reason") or ""),
                "steps": rep["steps"],
                "replay_ok": rep["ok"],
                **forens,
                "signature_parts": tx_audit["signature_parts"],
            })

    declared_n = meta.get("episode_count", meta.get("n_episodes"))
    if not isinstance(declared_n, int) or isinstance(declared_n, bool) or declared_n != len(episode_rows):
        errors.append(f"episode_count_mismatch:declared={declared_n}:actual={len(episode_rows)}")

    return {
        "run_name": run_dir.name,
        "run_dir": rel_dir,
        "role": meta.get("role"),
        "subrole": subrole,
        "model_id": meta.get("model_id"),
        "commit": commit,
        "episode_count": len(episode_rows),
        "usage": usage,
        "episodes": episode_rows,
        "transcripts": transcript_audits,
        "verified": len(errors) == 0,
        "errors": errors,
        "hygiene_hits": hygiene_hits,
    }


def _summarize_thinking_ladders(
    ladder_runs: list[dict[str, Any]],
    solver_index: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    by_run: list[dict[str, Any]] = []
    pooled: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for run in ladder_runs:
        levels_map: dict[str, list[dict[str, Any]]] = {}
        for ep in run["episodes"]:
            lv = str(ep.get("level") or "default")
            levels_map.setdefault(lv, []).append(ep)
            pooled.setdefault((ep["tier"], lv), []).append(ep)

        meta_path = Path(run["run_dir"])
        lv_stats: dict[str, Any] = {}
        for lv, eps in sorted(levels_map.items()):
            lv_stats[lv] = compute_paired_slice(f"{run['run_name']}:{lv}", eps, solver_index)
        by_run.append({
            "run_name": run["run_name"],
            "run_dir": run["run_dir"],
            "subrole": run["subrole"],
            "episode_count": run["episode_count"],
            "usage": run["usage"],
            "levels": lv_stats,
        })

    pooled_summary: dict[str, Any] = {}
    for (tier, lv), eps in sorted(pooled.items()):
        dedup: dict[int, dict[str, Any]] = {}
        for ep in eps:
            s = int(ep["seed"])
            if s not in dedup:
                dedup[s] = ep
        pooled_summary[f"{tier}:{lv}"] = compute_paired_slice(
            f"thinking_ladder:{tier}:{lv}",
            list(dedup.values()),
            solver_index,
        )

    return {"runs": by_run, "pooled_by_tier_level": pooled_summary}


def _summarize_hint_ablations(
    hint_runs: list[dict[str, Any]],
    frontier_by_key: dict[tuple[str, int], dict[str, Any]],
    solver_index: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for run in hint_runs:
        eps = sorted(run["episodes"], key=lambda e: (str(e["tier"]), int(e["seed"])))
        hint_slice = compute_paired_slice(run["run_name"], eps, solver_index)
        paired_unhinted = [
            frontier_by_key[(str(e["tier"]), int(e["seed"]))]
            for e in eps
            if (str(e["tier"]), int(e["seed"])) in frontier_by_key
        ]
        unhinted_slice = (
            compute_paired_slice(f"{run['run_name']}:unhinted_baseline", paired_unhinted, solver_index)
            if len(paired_unhinted) == len(eps)
            else None
        )
        delta_vs_unhinted = None
        if unhinted_slice and unhinted_slice["n"] > 0:
            diffs = [
                float(h["score"]) - float(u["score"])
                for h, u in zip(eps, sorted(paired_unhinted, key=lambda x: (str(x["tier"]), int(x["seed"]))))
            ]
            dm, dci = mean_ci(diffs)
            delta_vs_unhinted = {
                "mean_score_delta": round(dm, 6),
                "score_delta_ci95": round(dci, 6),
                "regret_per_episode_delta": round(
                    hint_slice["regret_per_episode"] - unhinted_slice["regret_per_episode"], 6
                ),
            }
        out.append({
            "run_name": run["run_name"],
            "run_dir": run["run_dir"],
            "hint": eps[0].get("hint") if eps else None,
            "hinted": hint_slice,
            "unhinted_same_seeds": unhinted_slice,
            "delta_vs_unhinted": delta_vs_unhinted,
        })
    return out


def audit_investigator_suite(
    root: str | Path = ".",
    role_dir: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    target_dir = Path(role_dir) if role_dir is not None else (root_path / DEFAULT_ROLE_DIR)
    if not target_dir.is_absolute():
        target_dir = root_path / target_dir

    if not target_dir.is_dir():
        return {
            "verified": False,
            "role": ROLE_NAME,
            "model_id": TARGET_MODEL,
            "errors": [f"missing_role_dir:{target_dir}"],
            "runs": [],
        }

    run_dirs = sorted(p for p in target_dir.iterdir() if p.is_dir())
    inspected = [inspect_investigator_run(d, root_path) for d in run_dirs]

    suite_errors: list[str] = []
    for r in inspected:
        if not r["verified"]:
            suite_errors.append(f"unverified_run:{r['run_dir']}:{','.join(r['errors'])}")

    needed_keys: set[tuple[str, int]] = set()
    for r in inspected:
        for ep in r.get("episodes", []):
            needed_keys.add((str(ep["tier"]), int(ep["seed"])))

    solver_index = load_solver_index(root_path, needed_keys)

    frontier_runs = [r for r in inspected if r.get("verified") and r.get("subrole") == "frontier_investigator"]
    ladder_runs = [
        r for r in inspected
        if r.get("verified") and r.get("subrole") in {"thinking_level_ablation", "hard_thinking_ablation"}
    ]
    hint_runs = [r for r in inspected if r.get("verified") and r.get("subrole") == "hint_ablation"]

    frontier_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for r in frontier_runs:
        for ep in r["episodes"]:
            key = (str(ep["tier"]), int(ep["seed"]))
            if key in frontier_by_key:
                prev = frontier_by_key[key]
                if abs(float(prev["score"]) - float(ep["score"])) > 1e-9 or prev["accused"] != ep["accused"]:
                    suite_errors.append(f"conflicting_duplicate_frontier_seed:{key[0]}:{key[1]}")
            else:
                frontier_by_key[key] = ep

    frontier_eps = [frontier_by_key[k] for k in sorted(frontier_by_key)]
    frontier_slices: dict[str, Any] = {}
    for tier in ("easy", "medium", "hard"):
        t_eps = [e for e in frontier_eps if e["tier"] == tier]
        if t_eps:
            frontier_slices[tier] = compute_paired_slice(tier, t_eps, solver_index)
    med_hard_eps = [e for e in frontier_eps if e["tier"] in {"medium", "hard"}]
    if med_hard_eps:
        frontier_slices["medium_plus_hard"] = compute_paired_slice("medium_plus_hard", med_hard_eps, solver_index)
    if frontier_eps:
        frontier_slices["all_tiers"] = compute_paired_slice("all_tiers", frontier_eps, solver_index)

    thinking_summary = _summarize_thinking_ladders(ladder_runs, solver_index)
    hint_summary = _summarize_hint_ablations(hint_runs, frontier_by_key, solver_index)

    good_runs = [r for r in inspected if r.get("verified")]
    total_eps = sum(r["episode_count"] for r in good_runs)
    total_calls = sum(r["usage"]["calls"] for r in good_runs)
    total_in = sum(r["usage"]["in"] for r in good_runs)
    total_out = sum(r["usage"]["out"] for r in good_runs)
    total_think = sum(r["usage"]["thinking"] for r in good_runs)
    total_cached = sum(r["usage"]["cached"] for r in good_runs)
    total_cost_list = round(sum(r["usage"]["cost_usd"] for r in good_runs), 6)
    total_cost_est = round(sum(r["usage"]["cost_usd_est"] for r in good_runs), 6)
    total_tx = sum(len(r["transcripts"]) for r in good_runs)
    total_sigs = sum(t["signature_parts"] for r in good_runs for t in r["transcripts"])
    hygiene_count = sum(len(r.get("hygiene_hits", [])) for r in inspected)

    return {
        "verified": len(suite_errors) == 0 and len(good_runs) > 0,
        "role": ROLE_NAME,
        "model_id": TARGET_MODEL,
        "tiers_version": EXPECTED_TIERS_VERSION,
        "totals": {
            "scanned_runs": len(inspected),
            "verified_runs": len(good_runs),
            "frontier_runs": len(frontier_runs),
            "thinking_ablation_runs": len(ladder_runs),
            "hint_ablation_runs": len(hint_runs),
            "total_episodes": total_eps,
            "unique_frontier_episodes": len(frontier_eps),
            "replay_verified_episodes": sum(
                1 for r in good_runs for e in r["episodes"] if e["replay_ok"]
            ),
            "verified_transcripts": total_tx,
            "verified_signature_parts": total_sigs,
            "calls": total_calls,
            "tokens_in": total_in,
            "tokens_out": total_out,
            "thinking_tokens": total_think,
            "cached_tokens": total_cached,
            "cost_usd_list": total_cost_list,
            "cost_usd_est": total_cost_est,
            "hygiene_violations": hygiene_count,
        },
        "frontier_paired_vs_solver": frontier_slices,
        "thinking_ablations": thinking_summary,
        "hint_ablations": hint_summary,
        "runs": [
            {
                "run_name": r["run_name"],
                "run_dir": r["run_dir"],
                "subrole": r.get("subrole"),
                "verified": r["verified"],
                "episode_count": r.get("episode_count", 0),
                "usage": r.get("usage", {}),
                "errors": r.get("errors", []),
            }
            for r in inspected
        ],
        "frontier_episodes": frontier_eps,
        "errors": suite_errors,
    }


def _fmt_ci(pair: list[float | None] | None, pct: bool = False, signed: bool = False) -> str:
    if not pair or pair[0] is None or pair[1] is None:
        return "n/a"
    lo, hi = float(pair[0]), float(pair[1])
    if pct:
        return f"[{lo * 100.0:.1f}%, {hi * 100.0:.1f}%]"
    if signed:
        return f"[{lo:+.3f}, {hi:+.3f}]"
    return f"[{lo:.3f}, {hi:.3f}]"


def render_suite_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        f"{H1} Role 3 Consolidated Suite: Frontier Investigators Paired vs SolverPolicy (`{TARGET_MODEL}`)",
        "",
        f"- Role: `{ROLE_NAME}`",
        f"- Target Model ID: `{TARGET_MODEL}` (`tiers_version={report['tiers_version']}`)",
        f"- Verified run folders: `{totals['verified_runs']}` (`{totals['frontier_runs']}` frontier + `{totals['thinking_ablation_runs']}` thinking-ladder + `{totals['hint_ablation_runs']}` hint-ablation)",
        f"- Replay-verified episodes: `{totals['replay_verified_episodes']} / {totals['total_episodes']}` (`{totals['unique_frontier_episodes']}` unique frontier episodes)",
        f"- Transcript thought-signature audit: `{totals['verified_transcripts']}` transcripts verified, `{totals['verified_signature_parts']}` redacted signature parts, `0` raw base64 leaks",
        f"- Total Gemini API calls: `{totals['calls']:,}`",
        f"- Total tokens (in / out / thinking / cached): `{totals['tokens_in']:,}` / `{totals['tokens_out']:,}` / `{totals['thinking_tokens']:,}` / `{totals['cached_tokens']:,}`",
        f"- Total cost (USD, cache-adjusted est / uncached list): `${totals['cost_usd_est']:.4f}` / `${totals['cost_usd_list']:.4f}`",
        f"- Hygiene & secret scan violations: `{totals['hygiene_violations']}`",
        "",
        f"{H2} 1. In-Process `{TARGET_MODEL}` Investigator Paired vs `SolverPolicy` (v1.4)",
        "",
        "| Slice | Seeds (n) | Carbon Mean +/- 95% CI | Carbon Acc (95% CI) | Mean Accuse Day | Mean P(accused) | Solver Mean | Carbon / Solver (95% Boot CI) | Paired Diff +/- 95% CI | Luck-Adj Carbon / Solver (95% Boot CI) |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]

    slices = report["frontier_paired_vs_solver"]
    for key in ("easy", "medium", "hard", "medium_plus_hard", "all_tiers"):
        if key not in slices:
            continue
        s = slices[key]
        ratio_str = (
            f"{s['frontier_over_solver_ratio'] * 100.0:.1f}% {_fmt_ci(s['frontier_over_solver_ci95'], pct=True)}"
            if s["frontier_over_solver_ratio"] is not None
            else "n/a"
        )
        luck_str = (
            f"{s['luck_adjusted_ratio'] * 100.0:.1f}% {_fmt_ci(s['luck_adjusted_ratio_ci95'], pct=True)}"
            if s["luck_adjusted_ratio"] is not None
            else "n/a"
        )
        day_str = f"{s['mean_accuse_day']:.1f}" if s["mean_accuse_day"] is not None else "n/a"
        p_str = f"{s['mean_p_accused']:.3f}" if s["mean_p_accused"] is not None else "n/a"
        lines.append(
            f"| `{key}` | {s['n']} | {s['mean_score']:+.3f} +/- {s['score_ci95']:.3f} "
            f"| {s['accuracy'] * 100.0:.1f}% {_fmt_ci(s['accuracy_ci95'], pct=True)} "
            f"| {day_str} | {p_str} | {s['solver_mean_score']:+.3f} "
            f"| {ratio_str} | {s['paired_diff_mean']:+.3f} +/- {s['paired_diff_ci95']:.3f} | {luck_str} |"
        )

    lines.extend([
        "",
        f"{H2} 2. Thinking-Level Ablation (`low` vs `high`) Paired vs `SolverPolicy`",
        "",
        "| Run Folder | Level | Tier | n | Mean Score | Acc | Accuse Day | P(accused) | Solver Mean | Paired Diff | Regret / Ep |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for lrun in report["thinking_ablations"]["runs"]:
        for lv, st in sorted(lrun["levels"].items()):
            day_str = f"{st['mean_accuse_day']:.1f}" if st["mean_accuse_day"] is not None else "n/a"
            p_str = f"{st['mean_p_accused']:.3f}" if st["mean_p_accused"] is not None else "n/a"
            tier_label = ",".join(st["tiers"])
            lines.append(
                f"| `{lrun['run_name']}` | `{lv}` | `{tier_label}` | {st['n']} "
                f"| {st['mean_score']:+.3f} | {st['accuracy'] * 100.0:.1f}% | {day_str} | {p_str} "
                f"| {st['solver_mean_score']:+.3f} | {st['paired_diff_mean']:+.3f} | {st['regret_per_episode']:.4f} |"
            )

    if report["hint_ablations"]:
        lines.extend([
            "",
            f"{H2} 3. Failure-Mode Hint Ablation Paired vs Unhinted `{TARGET_MODEL}` and `SolverPolicy`",
            "",
            "| Run Folder | Hint Tags | n | Hinted Mean | Unhinted Mean | Delta vs Unhinted | Solver Mean | Hinted Regret / Ep | Unhinted Regret / Ep |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for hrun in report["hint_ablations"]:
            hs = hrun["hinted"]
            us = hrun["unhinted_same_seeds"]
            dv = hrun["delta_vs_unhinted"]
            u_mean = f"{us['mean_score']:+.3f}" if us else "n/a"
            u_reg = f"{us['regret_per_episode']:.4f}" if us else "n/a"
            d_mean = f"{dv['mean_score_delta']:+.3f}" if dv else "n/a"
            lines.append(
                f"| `{hrun['run_name']}` | `{hrun['hint']}` | {hs['n']} "
                f"| {hs['mean_score']:+.3f} | {u_mean} | {d_mean} "
                f"| {hs['solver_mean_score']:+.3f} | {hs['regret_per_episode']:.4f} | {u_reg} |"
            )

    lines.extend([
        "",
        f"{H2} 4. Verified Run Folders Inventory (`results/gemini/roles_carbon/investigators/`)",
        "",
        "| Run Folder | Subrole | Episodes | Calls | Tokens In | Tokens Out | Thinking | Cached | Est Cost (USD) | Verified |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in report["runs"]:
        u = r["usage"]
        lines.append(
            f"| `{r['run_name']}` | `{r['subrole']}` | {r['episode_count']} | {u.get('calls', 0):,} "
            f"| {u.get('in', 0):,} | {u.get('out', 0):,} | {u.get('thinking', 0):,} | {u.get('cached', 0):,} "
            f"| ${u.get('cost_usd_est', 0.0):.4f} | {'yes' if r['verified'] else 'no'} |"
        )

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify and summarize gemini-4-carbon investigator runs vs SolverPolicy.")
    ap.add_argument("--root", default=".", help="repository root directory")
    ap.add_argument("--role-dir", default=None, help="override investigator role directory")
    ap.add_argument("--write-doc", default=None, help="optional markdown output path")
    ap.add_argument("--json", action="store_true", help="emit JSON report to stdout")
    ap.add_argument("--strict", action="store_true", help="exit non-zero if verification fails")
    args = ap.parse_args(argv)

    root_path = Path(args.root).resolve()
    report = audit_investigator_suite(root_path, args.role_dir)
    md = render_suite_markdown(report)

    if args.write_doc:
        doc_path = Path(args.write_doc)
        if not doc_path.is_absolute():
            doc_path = root_path / doc_path
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(md, encoding="utf-8")

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(md)

    if args.strict and not report["verified"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
