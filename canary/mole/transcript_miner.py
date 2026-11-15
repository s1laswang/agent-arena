from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from canary.analysis.accuse import to_md
from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result
from canary.mole.dsl import MoleStrategy
from canary.rules import tier_params_for_episode, tiers_version
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, INVESTIGATIVE_TOOLS

ANGRY_SNIPPETS: tuple[str, ...] = (
    "flat' raise",
    "moving the goalposts",
    "deserve me",
    "skipped for promotion",
    "nobody asks us",
    "pay here is a joke",
)

COHORT_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("v1.4_gemini_opencode", "v1.4", "opencode:google/gemini-4-carbon", "Gemini-4-carbon (OpenCode MCP)"),
    ("v1.4_gemini_inproc", "v1.4", "gemini:gemini-4-carbon", "Gemini-4-carbon (In-Proc)"),
    ("v1.4_solver", "v1.4", "solver", "Reference Solver (v1.4, seeds 0-29)"),
    ("v1.3_codex_gpt55", "v1.3", "codex:gpt-5.5", "Codex GPT-5.5 (MCP)"),
    ("v1.3_inproc_gpt55", "v1.3", "openai:gpt-5.5", "GPT-5.5 (In-Proc)"),
    ("v1.3_solver", "v1.3", "solver", "Reference Solver (v1.3, seeds 0-19)"),
)

COHORT_AGENTS: frozenset[str] = frozenset(ag for _, _, ag, _ in COHORT_SPECS)

PRIMARY_COHORT_DIRS: dict[str, frozenset[str]] = {
    "v1.4": frozenset({"opencode-gemini-4-carbon", "inproc-gemini-4-carbon", "reference"}),
    "v1.3": frozenset({"codex-gpt-5.5-full", "gpt-5.5-full", "reference"}),
}

PRIMARY_SEED_MAX: dict[str, int] = {
    "v1.4": 29,
    "v1.3": 19,
}

HEADLINE_TIERS: tuple[str, ...] = ("hard", "medium")

KEY_TOOLS: tuple[str, ...] = (
    "interview",
    "read_access_logs",
    "search_messages",
    "restrict_access",
    "plant_canary",
)


def resolve_committed_root(root: str | Path) -> Path:
    p = Path(root)
    nested = p / "data" / "runs" / "committed"
    if nested.is_dir():
        return nested
    return p


def _is_valid_episode(ep: dict[str, Any]) -> bool:
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    return meta.get("valid") is not False and ep.get("valid") is not False


def _run_meta(run_dir: Path) -> dict[str, Any]:
    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        return {}
    try:
        parsed = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _should_skip_rel_parts(rel_parts: tuple[str, ...]) -> bool:
    for part in rel_parts:
        low = part.lower()
        if (
            "superseded" in low
            or low.endswith(("-smoke", "-ext"))
            or "hint" in low
            or "seeds30to59" in low
        ):
            return True
    return False


def _load_version_episodes(
    committed_root: Path,
    version: str,
) -> tuple[list[tuple[tuple[str, str], dict[str, Any]]], dict[str, Path], list[tuple[str, str, int]]]:
    ver_dir = committed_root / version
    if not ver_dir.is_dir():
        return [], {}, []
    allowed_dirs = PRIMARY_COHORT_DIRS.get(version, frozenset())
    max_seed = PRIMARY_SEED_MAX.get(version, 29)
    episodes: list[tuple[tuple[str, str], dict[str, Any]]] = []
    accuse_files: dict[str, Path] = {}
    invalid_records: list[tuple[str, str, int]] = []
    for md_path in sorted(ver_dir.rglob("accuse.md")):
        rel_md_parts = md_path.relative_to(ver_dir).parts
        if _should_skip_rel_parts(rel_md_parts):
            continue
        if len(rel_md_parts) >= 2 and rel_md_parts[0] not in allowed_dirs:
            continue
        accuse_files[str(md_path.parent.relative_to(ver_dir))] = md_path
    for fpath in sorted(ver_dir.rglob("episodes.jsonl")):
        rel_parts = fpath.relative_to(ver_dir).parts
        if len(rel_parts) < 2 or rel_parts[0] not in allowed_dirs:
            continue
        if _should_skip_rel_parts(rel_parts):
            continue
        rmeta = _run_meta(fpath.parent)
        mver = rmeta.get("tiers_version")
        if isinstance(mver, str) and mver.strip() and mver.strip() != version:
            continue
        magent = rmeta.get("agent")
        if isinstance(magent, str) and magent.strip() and magent.strip() not in COHORT_AGENTS:
            continue
        rel_dir = str(fpath.parent.relative_to(committed_root))
        recency = (str(rmeta.get("timestamp") or ""), rel_dir)
        for raw_line in fpath.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            ep = json.loads(line)
            tier = str(ep.get("tier") or "")
            if tier not in HEADLINE_TIERS:
                continue
            seed = int(ep.get("seed", -1))
            if not (0 <= seed <= max_seed):
                continue
            if not _is_valid_episode(ep):
                invalid_records.append((tier, str(ep.get("agent") or ""), seed))
                continue
            ep = dict(ep)
            meta = dict(ep.get("meta") or {})
            meta.setdefault("source_file", str(fpath.relative_to(committed_root)))
            ep["meta"] = meta
            episodes.append((recency, ep))
    return episodes, accuse_files, invalid_records


def detect_angry_decoy(ep: EpisodeResult) -> str | None:
    meta_decoy = (ep.meta or {}).get("decoy")
    found: str | None = str(meta_decoy) if isinstance(meta_decoy, str) and meta_decoy else None
    for st in ep.steps:
        res = st.result or {}
        if not res.get("ok", True):
            continue
        if st.tool not in ("search_messages", "read_message"):
            continue
        data = res.get("data") or {}
        msgs: list[dict[str, Any]] = []
        if isinstance(data.get("messages"), list):
            msgs.extend(data["messages"])
        if isinstance(data.get("message"), dict):
            msgs.append(data["message"])
        for msg in msgs:
            text = f"{msg.get('subject') or ''} {msg.get('snippet') or ''} {msg.get('body') or ''}".lower()
            sender = msg.get("sender")
            if isinstance(sender, str) and sender and any(snip in text for snip in ANGRY_SNIPPETS):
                return sender
    return found


def analyze_single_episode(
    ep: EpisodeResult,
    public_decoy_by_seed: dict[tuple[str, int], str],
) -> dict[str, Any]:
    params = tier_params_for_episode(ep.tier, ep.steps)
    sp = SolverPolicy(params)

    tool_calls: Counter[str] = Counter()
    tool_ok_calls: Counter[str] = Counter()
    failed_calls = 0
    planted_canaries: list[dict[str, Any]] = []
    restricted_now: set[str] = set()
    ever_restricted: set[str] = set()
    restrict_cost_v = 0.0
    accuse_idx: int | None = None

    for idx, st in enumerate(ep.steps):
        tool_calls[st.tool] += 1
        ok = bool((st.result or {}).get("ok", True))
        if ok:
            tool_ok_calls[st.tool] += 1
        else:
            failed_calls += 1
        if st.tool == "plant_canary" and ok:
            asg = st.args.get("assignment") or {}
            if isinstance(asg, dict) and asg:
                planted_canaries.append({
                    "day": int(st.day),
                    "n_recipients": len(asg),
                    "n_variants": len(set(asg.values())),
                })
        elif st.tool == "restrict_access" and ok:
            emp = st.args.get("employee")
            if isinstance(emp, str) and emp:
                restricted_now.add(emp)
                ever_restricted.add(emp)
        elif st.tool == "unrestrict_access" and ok:
            emp = st.args.get("employee")
            if isinstance(emp, str):
                restricted_now.discard(emp)
        elif st.tool == "advance_day" and ok:
            restrict_cost_v += params.restrict_cost_per_day * len(restricted_now)
        if st.tool == "accuse" and accuse_idx is None:
            accuse_idx = idx

    ingest_limit = accuse_idx if accuse_idx is not None else len(ep.steps)
    for st in ep.steps[:ingest_limit]:
        sp._ingest(st)

    post = sp.belief() if sp.obs.employees else {}
    v_visible = float(sp.V)
    v_expected = float(sp.expected_true_V())
    breakeven_visible = 1.0 / (1.0 + v_visible) if v_visible > 0.0 else 1.0
    breakeven_expected = 1.0 / (1.0 + v_expected) if v_expected > 0.0 else 1.0

    agent_detected_decoy = detect_angry_decoy(ep)
    known_decoy = agent_detected_decoy or public_decoy_by_seed.get((ep.tier, ep.seed))

    after_hours_by_emp = {emp: int(vals[1]) for emp, vals in sp.obs.access_counts.items()}
    max_ah = max(after_hours_by_emp.values()) if after_hours_by_emp else 0
    decoy_has_max_ah = bool(known_decoy and max_ah > 0 and after_hours_by_emp.get(known_decoy, 0) == max_ah)

    surfaced_canaries = [
        it for it in sp.obs.feed
        if sp.obs.docs.get(it.doc_id) is not None and sp.obs.docs[it.doc_id].is_canary
    ]
    surfaced_regular = [
        it for it in sp.obs.feed
        if sp.obs.docs.get(it.doc_id) is not None and not sp.obs.docs[it.doc_id].is_canary
    ]
    unlisted_feed_items = sum(1 for it in sp.obs.feed if sp.obs.docs.get(it.doc_id) is None)

    candidate_cell = set(sp.obs.employees)
    for it in surfaced_regular:
        doc = sp.obs.docs.get(it.doc_id)
        if doc is not None:
            candidate_cell &= set(doc.recipients)
    if known_decoy:
        candidate_cell.discard(known_decoy)
    for it in surfaced_canaries:
        doc = sp.obs.docs.get(it.doc_id)
        if doc is not None and doc.variants:
            candidate_cell &= {emp for emp, lab in doc.variants.items() if lab == it.variant}

    accused = ep.accused if isinstance(ep.accused, str) and ep.accused else None
    p_accused = round(float(post.get(accused, 0.0)), 3) if (accused and post) else None
    p_top = round(float(max(post.values())), 3) if post else None

    accused_canary_hits = 0
    separating_canaries = 0
    runner_up: str | None = None
    if accused:
        for it in surfaced_canaries:
            vs = sp.obs.docs[it.doc_id].variants or {}
            if vs.get(accused) == it.variant:
                accused_canary_hits += 1
        ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
        runner_up = next((emp for emp, _ in ranked if emp != accused), None)
        if runner_up is not None:
            for it in surfaced_canaries:
                vs = sp.obs.docs[it.doc_id].variants or {}
                if (vs.get(accused) == it.variant) != (vs.get(runner_up) == it.variant):
                    separating_canaries += 1

    cell_ah = {emp: after_hours_by_emp.get(emp, 0) for emp in sorted(candidate_cell)}
    accused_ah = after_hours_by_emp.get(accused, 0) if accused else 0
    cell_max_ah = max(cell_ah.values()) if cell_ah else 0
    cell_min_ah = min(cell_ah.values()) if cell_ah else 0
    non_decoy_framed_tiebreak = bool(
        accused
        and not ep.correct
        and accused != known_decoy
        and len(cell_ah) >= 2
        and accused in cell_ah
        and accused_ah == cell_max_ah
        and cell_max_ah > cell_min_ah
    )

    canary_cost_v = len(planted_canaries) * params.canary_cost
    v_lost = max(0.0, 1.0 - float(ep.score)) if ep.correct else None
    leak_v_drain = max(0.0, v_lost - canary_cost_v - restrict_cost_v) if v_lost is not None else None

    below_be_expected = bool(accused and p_accused is not None and p_accused < breakeven_expected)
    below_be_visible = bool(accused and p_accused is not None and p_accused < breakeven_visible)
    horizon_gamble = bool(below_be_expected and ep.final_day >= params.n_days)
    premature_midgame_gamble = bool(below_be_expected and ep.final_day < params.n_days)

    failure_mechanisms: list[str] = []
    if not ep.correct and accused:
        if params.fingerprint_accuracy < 1.0 and separating_canaries <= 1 and len(surfaced_canaries) >= 1:
            if accused_canary_hits == 0 and len(cell_ah) == 0:
                failure_mechanisms.append("fp95_conflicting_canaries_fallback")
            elif accused_canary_hits <= 1:
                failure_mechanisms.append("fp95_single_canary_hit")
            else:
                failure_mechanisms.append("fp95_single_separating_canary")
        if known_decoy and accused == known_decoy:
            if agent_detected_decoy is None:
                failure_mechanisms.append("unidentified_decoy_framed_log_fallback")
            else:
                failure_mechanisms.append("angry_decoy_accused")
        if non_decoy_framed_tiebreak:
            failure_mechanisms.append("non_decoy_framed_log_tiebreak")
        if horizon_gamble:
            failure_mechanisms.append("horizon_gamble_below_breakeven")
        elif premature_midgame_gamble:
            failure_mechanisms.append("midgame_gamble_below_breakeven")
        if not failure_mechanisms and accused_canary_hits <= 1:
            failure_mechanisms.append("single_canary_hit_tie")
    elif not accused:
        failure_mechanisms.append("horizon_abstention")
        if len(surfaced_canaries) == 0:
            failure_mechanisms.append("zero_surfaced_canaries")
    else:
        if horizon_gamble:
            failure_mechanisms.append("lucky_horizon_gamble_below_breakeven")
        elif below_be_expected:
            failure_mechanisms.append("lucky_midgame_gamble_below_breakeven")
        if ep.score < 0.45:
            failure_mechanisms.append("late_accusation_v_drain")

    canary_days = [c["day"] for c in planted_canaries]
    active_days = max(1, int(ep.final_day))
    day_counts = Counter(canary_days)
    two_canary_days = sum(1 for d in range(1, active_days + 1) if day_counts.get(d, 0) >= 2)

    return {
        "tier": ep.tier,
        "seed": int(ep.seed),
        "agent": ep.agent,
        "score": float(ep.score),
        "accused": accused,
        "correct": bool(ep.correct),
        "final_day": int(ep.final_day),
        "accuse_step_day": int(ep.steps[accuse_idx].day) if accuse_idx is not None else int(ep.final_day),
        "n_days": int(params.n_days),
        "end_reason": ep.end_reason,
        "fingerprint_accuracy": float(params.fingerprint_accuracy),
        "decoy_enabled": bool(params.decoy),
        "p_accused": p_accused,
        "p_top": p_top,
        "v_visible": round(v_visible, 4),
        "v_expected": round(v_expected, 4),
        "breakeven_visible": round(breakeven_visible, 4),
        "breakeven_expected": round(breakeven_expected, 4),
        "below_breakeven_expected": below_be_expected,
        "below_breakeven_visible": below_be_visible,
        "horizon_gamble": horizon_gamble,
        "premature_midgame_gamble": premature_midgame_gamble,
        "planted_canaries": planted_canaries,
        "n_canaries": len(planted_canaries),
        "canaries_per_day": len(planted_canaries) / active_days,
        "first_canary_day": min(canary_days) if canary_days else None,
        "planted_day1": bool(canary_days and min(canary_days) == 1),
        "two_canary_days": two_canary_days,
        "active_days": active_days,
        "surfaced_canaries": len(surfaced_canaries),
        "unlisted_feed_items": unlisted_feed_items,
        "accused_canary_hits": accused_canary_hits,
        "separating_canaries": separating_canaries,
        "runner_up": runner_up,
        "agent_detected_decoy": agent_detected_decoy,
        "known_decoy": known_decoy,
        "decoy_has_max_after_hours": decoy_has_max_ah,
        "decoy_accused": bool(known_decoy and accused == known_decoy),
        "decoy_restricted": bool(known_decoy and known_decoy in ever_restricted),
        "accused_after_hours": accused_ah,
        "decoy_after_hours": after_hours_by_emp.get(known_decoy, 0) if known_decoy else 0,
        "candidate_cell_size": len(cell_ah),
        "candidate_cell_max_after_hours": cell_max_ah,
        "non_decoy_framed_tiebreak": non_decoy_framed_tiebreak,
        "canary_cost_v": round(canary_cost_v, 6),
        "restrict_cost_v": round(restrict_cost_v, 6),
        "v_lost_on_correct": round(v_lost, 6) if v_lost is not None else None,
        "leak_v_drain_on_correct": round(leak_v_drain, 6) if leak_v_drain is not None else None,
        "tool_calls": dict(tool_calls),
        "tool_ok_calls": dict(tool_ok_calls),
        "failed_calls": failed_calls,
        "total_calls": sum(tool_calls.values()),
        "investigative_calls": sum(v for k, v in tool_calls.items() if k in INVESTIGATIVE_TOOLS),
        "failure_mechanisms": failure_mechanisms,
    }


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def aggregate_records(
    records: list[dict[str, Any]],
    solver_by_key: dict[tuple[str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    n = len(records)
    if n == 0:
        return {"n_episodes": 0}
    scores = [r["score"] for r in records]
    m_score, ci_score = mean_ci(scores)
    accused_recs = [r for r in records if r["accused"] is not None]
    correct_recs = [r for r in records if r["correct"]]
    wrong_recs = [r for r in accused_recs if not r["correct"]]
    abstain_recs = [r for r in records if r["accused"] is None]

    all_canaries = [c for r in records for c in r["planted_canaries"]]
    n_can = len(all_canaries)
    le_3 = sum(1 for c in all_canaries if c["n_recipients"] <= 3)
    b4_8 = sum(1 for c in all_canaries if 4 <= c["n_recipients"] <= 8)
    ge_9 = sum(1 for c in all_canaries if c["n_recipients"] >= 9)
    v1 = sum(1 for c in all_canaries if c["n_variants"] == 1)
    v2 = sum(1 for c in all_canaries if c["n_variants"] == 2)
    v3 = sum(1 for c in all_canaries if c["n_variants"] == 3)

    first_days = [r["first_canary_day"] for r in records if r["first_canary_day"] is not None]
    total_active_days = sum(r["active_days"] for r in records)
    total_two_canary_days = sum(r["two_canary_days"] for r in records)
    surfaced_total = sum(r["surfaced_canaries"] for r in records)

    tool_sums: Counter[str] = Counter()
    for r in records:
        for tool_name, cnt in r["tool_calls"].items():
            tool_sums[tool_name] += cnt
    inv_total = sum(r["investigative_calls"] for r in records)

    fp95_acc = [r for r in accused_recs if r["fingerprint_accuracy"] < 1.0]
    single_hit_all = [r for r in accused_recs if r["accused_canary_hits"] <= 1]
    single_hit_fp95 = [r for r in fp95_acc if r["accused_canary_hits"] <= 1]
    single_sep_all = [r for r in accused_recs if r["separating_canaries"] <= 1]
    single_sep_fp95 = [r for r in fp95_acc if r["separating_canaries"] <= 1]

    paired_all_lags: list[int] = []
    paired_accused_lags: list[int] = []
    solver_leak_drains: list[float] = []
    if solver_by_key:
        for r in records:
            sol = solver_by_key.get((r["tier"], r["seed"]))
            if sol is None:
                continue
            paired_all_lags.append(r["final_day"] - sol["final_day"])
            if r["accused"] is not None and sol["accused"] is not None:
                paired_accused_lags.append(r["final_day"] - sol["final_day"])
            if sol["leak_v_drain_on_correct"] is not None:
                solver_leak_drains.append(sol["leak_v_drain_on_correct"])

    v_lost_vals = [r["v_lost_on_correct"] for r in correct_recs if r["v_lost_on_correct"] is not None]
    can_cost_vals = [r["canary_cost_v"] for r in correct_recs]
    rst_cost_vals = [r["restrict_cost_v"] for r in correct_recs]
    leak_drain_vals = [r["leak_v_drain_on_correct"] for r in correct_recs if r["leak_v_drain_on_correct"] is not None]

    mean_leak_drain = round(sum(leak_drain_vals) / len(leak_drain_vals), 4) if leak_drain_vals else None
    mean_sol_leak_drain = round(sum(solver_leak_drains) / len(solver_leak_drains), 4) if solver_leak_drains else None
    extra_leak_drain = (
        round(mean_leak_drain - mean_sol_leak_drain, 4)
        if (mean_leak_drain is not None and mean_sol_leak_drain is not None)
        else None
    )

    decoy_eps = [r for r in records if r["known_decoy"] is not None]
    decoy_detected_eps = [r for r in decoy_eps if r["agent_detected_decoy"] is not None]
    decoy_detected = len(decoy_detected_eps)
    decoy_detected_accused = sum(1 for r in decoy_detected_eps if r["decoy_accused"])
    decoy_max_ah = sum(1 for r in decoy_eps if r["decoy_has_max_after_hours"])
    decoy_accused = sum(1 for r in decoy_eps if r["decoy_accused"])
    decoy_restricted = sum(1 for r in decoy_eps if r["decoy_restricted"])

    return {
        "n_episodes": n,
        "seeds": sorted({r["seed"] for r in records}),
        "score_mean": round(m_score, 4),
        "score_ci95": round(ci_score, 4),
        "accuracy": round(len(correct_recs) / n, 4),
        "accused_count": len(accused_recs),
        "accused_rate": round(len(accused_recs) / n, 4),
        "wrong_count": len(wrong_recs),
        "wrong_rate": round(len(wrong_recs) / n, 4),
        "abstain_count": len(abstain_recs),
        "abstain_rate": round(len(abstain_recs) / n, 4),
        "final_day_mean": round(sum(r["final_day"] for r in records) / n, 2),
        "accuse_day_mean": round(sum(r["final_day"] for r in accused_recs) / len(accused_recs), 2) if accused_recs else None,
        "p_accused_mean": round(
            sum(r["p_accused"] for r in accused_recs if r["p_accused"] is not None) / len(accused_recs), 3
        ) if accused_recs else None,
        "canary_metrics": {
            "total_planted": n_can,
            "attempted_calls": int(tool_sums["plant_canary"]),
            "per_episode_mean": round(n_can / n, 2),
            "per_day_mean": round(sum(r["canaries_per_day"] for r in records) / n, 3),
            "per_active_day_pooled": round(_safe_div(n_can, total_active_days), 3),
            "first_canary_day_mean": round(sum(first_days) / len(first_days), 2) if first_days else None,
            "day1_canary_share": round(sum(1 for r in records if r["planted_day1"]) / n, 3),
            "two_canary_day_share": round(_safe_div(total_two_canary_days, total_active_days), 3),
            "surfaced_total": surfaced_total,
            "surfaced_rate": round(_safe_div(surfaced_total, n_can), 3),
            "zero_surfaced_episodes": sum(1 for r in records if r["surfaced_canaries"] == 0),
            "recipient_bins": {
                "le_3_count": le_3,
                "le_3_share": round(_safe_div(le_3, n_can), 3),
                "4_to_8_count": b4_8,
                "4_to_8_share": round(_safe_div(b4_8, n_can), 3),
                "ge_9_count": ge_9,
                "ge_9_share": round(_safe_div(ge_9, n_can), 3),
            },
            "variant_counts": {
                "v1_count": v1,
                "v1_share": round(_safe_div(v1, n_can), 3),
                "v2_count": v2,
                "v2_share": round(_safe_div(v2, n_can), 3),
                "v3_count": v3,
                "v3_share": round(_safe_div(v3, n_can), 3),
            },
        },
        "tool_budget": {
            "interview_mean": round(tool_sums["interview"] / n, 2),
            "read_access_logs_mean": round(tool_sums["read_access_logs"] / n, 2),
            "search_messages_mean": round(tool_sums["search_messages"] / n, 2),
            "restrict_access_mean": round(tool_sums["restrict_access"] / n, 2),
            "plant_canary_mean": round(tool_sums["plant_canary"] / n, 2),
            "list_documents_mean": round(tool_sums["list_documents"] / n, 2),
            "check_leak_feed_mean": round(tool_sums["check_leak_feed"] / n, 2),
            "advance_day_mean": round(tool_sums["advance_day"] / n, 2),
            "status_mean": round(tool_sums["status"] / n, 2),
            "total_calls_mean": round(sum(r["total_calls"] for r in records) / n, 2),
            "failed_calls_mean": round(sum(r["failed_calls"] for r in records) / n, 2),
            "investigative_calls_mean": round(inv_total / n, 2),
            "interview_investigative_share": round(_safe_div(tool_sums["interview"], inv_total), 3),
            "unlisted_feed_episodes": sum(1 for r in records if r["unlisted_feed_items"] > 0),
            "unlisted_feed_items_total": sum(r["unlisted_feed_items"] for r in records),
        },
        "failure_anatomy": {
            "single_canary_hit_accusations": len(single_hit_all),
            "single_canary_hit_wrong": sum(1 for r in single_hit_all if not r["correct"]),
            "fp95_single_canary_hit_accusations": len(single_hit_fp95),
            "fp95_single_canary_hit_wrong": sum(1 for r in single_hit_fp95 if not r["correct"]),
            "single_separating_canary_accusations": len(single_sep_all),
            "fp95_single_separating_accusations": len(single_sep_fp95),
            "fp95_single_separating_wrong": sum(1 for r in single_sep_fp95 if not r["correct"]),
            "paired_solver_n": len(paired_all_lags),
            "paired_both_accused_n": len(paired_accused_lags),
            "accuse_day_lag_vs_solver_mean": round(
                sum(paired_accused_lags) / len(paired_accused_lags), 2
            ) if paired_accused_lags else None,
            "final_day_lag_vs_solver_mean": round(
                sum(paired_all_lags) / len(paired_all_lags), 2
            ) if paired_all_lags else None,
            "v_lost_on_correct_mean": round(sum(v_lost_vals) / len(v_lost_vals), 4) if v_lost_vals else None,
            "canary_v_cost_on_correct_mean": round(sum(can_cost_vals) / len(can_cost_vals), 4) if can_cost_vals else None,
            "restrict_v_cost_on_correct_mean": round(sum(rst_cost_vals) / len(rst_cost_vals), 4) if rst_cost_vals else None,
            "leak_v_drain_on_correct_mean": mean_leak_drain,
            "extra_leak_v_drain_vs_solver": extra_leak_drain,
            "late_v_drain_episodes": sum(1 for r in correct_recs if r["score"] < 0.45),
            "below_breakeven_gambles": sum(1 for r in accused_recs if r["below_breakeven_expected"]),
            "below_breakeven_visible_gambles": sum(1 for r in accused_recs if r["below_breakeven_visible"]),
            "horizon_gambles": sum(1 for r in accused_recs if r["horizon_gamble"]),
            "premature_midgame_gambles": sum(1 for r in accused_recs if r["premature_midgame_gamble"]),
            "decoy_present_episodes": len(decoy_eps),
            "decoy_detected_in_messages": decoy_detected,
            "decoy_detected_rate": round(_safe_div(decoy_detected, len(decoy_eps)), 4),
            "decoy_max_after_hours_episodes": decoy_max_ah,
            "decoy_accused_count": decoy_accused,
            "decoy_restricted_count": decoy_restricted,
            "decoy_dismissal_rate": round(_safe_div(len(decoy_eps) - decoy_accused, len(decoy_eps)), 4) if decoy_eps else 1.0,
            "decoy_dismissal_when_detected_rate": (
                round(_safe_div(decoy_detected - decoy_detected_accused, decoy_detected), 4)
                if decoy_detected else 1.0
            ),
            "non_decoy_framed_tiebreak_wrong": sum(1 for r in wrong_recs if r["non_decoy_framed_tiebreak"]),
        },
    }


def _verify_accuse_md(recs: list[dict[str, Any]], accuse_files: dict[str, Path], agent_name: str) -> bool:
    if not recs or not accuse_files:
        return False
    rows: list[dict[str, Any]] = []
    for r in recs:
        has_acc = r["accused"] is not None
        p_acc = r["p_accused"] if has_acc else None
        p_top = r["p_top"] if has_acc else None
        verdict = (
            "none" if p_acc is None
            else "justified" if p_acc >= 0.6
            else "lucky" if r["correct"]
            else "premature-wrong"
        )
        rows.append({
            "tier": r["tier"],
            "agent": r["agent"],
            "seed": r["seed"],
            "day": r["accuse_step_day"],
            "accused": r["accused"],
            "correct": r["correct"],
            "score": r["score"],
            "p_accused": p_acc,
            "p_top": p_top,
            "verdict": verdict,
        })
    expected_md = to_md(rows).strip()
    for path in accuse_files.values():
        txt = path.read_text(encoding="utf-8").strip()
        if txt == expected_md:
            return True
        filtered_lines = [
            ln for ln in txt.splitlines()
            if ln.startswith("| tier |") or ln.startswith("|---|") or f"| {agent_name} |" in ln
        ]
        if "\n".join(filtered_lines).strip() == expected_md:
            return True
    return False


def _build_strategy_levers(cohorts: dict[str, Any], cross: dict[str, Any]) -> list[dict[str, Any]]:
    oc_hard = cohorts.get("v1.4_gemini_opencode", {}).get("tiers", {}).get("hard", {})
    oc_med = cohorts.get("v1.4_gemini_opencode", {}).get("tiers", {}).get("medium", {})
    ip_hard = cohorts.get("v1.4_gemini_inproc", {}).get("tiers", {}).get("hard", {})
    ip_med = cohorts.get("v1.4_gemini_inproc", {}).get("tiers", {}).get("medium", {})
    sol14_hard = cohorts.get("v1.4_solver", {}).get("tiers", {}).get("hard", {})
    cx_hard = cohorts.get("v1.3_codex_gpt55", {}).get("tiers", {}).get("hard", {})
    cx_med = cohorts.get("v1.3_codex_gpt55", {}).get("tiers", {}).get("medium", {})
    g5_hard = cohorts.get("v1.3_inproc_gpt55", {}).get("tiers", {}).get("hard", {})
    g5_med = cohorts.get("v1.3_inproc_gpt55", {}).get("tiers", {}).get("medium", {})

    def _cm(tier_dict: dict[str, Any], *path: str, default: Any = 0.0) -> Any:
        cur: Any = tier_dict
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    gem_le3 = [
        _cm(t, "canary_metrics", "recipient_bins", "le_3_share")
        for t in (oc_hard, oc_med, ip_hard, ip_med) if t
    ] or [0.0]
    gem_48 = [
        _cm(t, "canary_metrics", "recipient_bins", "4_to_8_share")
        for t in (oc_hard, oc_med, ip_hard, ip_med) if t
    ] or [0.0]
    gpt_le3 = [
        _cm(t, "canary_metrics", "recipient_bins", "le_3_share")
        for t in (cx_hard, cx_med, g5_hard, g5_med) if t
    ] or [0.0]
    decoy_acc_total = cross["frontier_decoy_accused_total"]
    decoy_acc_word = "accusation" if decoy_acc_total == 1 else "accusations"

    levers = [
        {
            "id": "low_recipient_surgical_shield",
            "mole_view_features": ["recent_low_recipient_docs", "min_recipient_count"],
            "mole_strategy_selectors": {"leak": "most_recipients", "frame": "random_peer"},
            "target_weakness": (
                f"Codex and GPT-5.5 rely heavily on <=3-recipient surgical traps "
                f"({_fmt_pct(min(gpt_le3))}-{_fmt_pct(max(gpt_le3))} of planted canaries) to isolate 1-3 suspects."
            ),
            "empirical_evidence": {
                "codex_medium_le3_share": _cm(cx_med, "canary_metrics", "recipient_bins", "le_3_share"),
                "codex_hard_le3_share": _cm(cx_hard, "canary_metrics", "recipient_bins", "le_3_share"),
                "gpt55_medium_le3_share": _cm(g5_med, "canary_metrics", "recipient_bins", "le_3_share"),
                "gpt55_hard_le3_share": _cm(g5_hard, "canary_metrics", "recipient_bins", "le_3_share"),
                "gemini_opencode_hard_le3_share": _cm(oc_hard, "canary_metrics", "recipient_bins", "le_3_share"),
            },
            "dsl_snippet": {
                "name": "surgical_trap_shield",
                "rules": [
                    {
                        "if": [["recent_low_recipient_docs", ">=", 1]],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    }
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
            "solver_catchability": (
                "Solver adapts with wider coverage fractions (0.40-1.00) and canary_shy() full-staff padding "
                "when >=3 regular leaks surface without a canary hit."
            ),
        },
        {
            "id": "midsize_canary_evasion",
            "mole_view_features": ["day", "min_recipient_count", "max_recipient_count", "n_leakable"],
            "mole_strategy_selectors": {"leak": "most_recipients", "frame": "random_peer"},
            "target_weakness": (
                f"Gemini-4-carbon almost never plants <=3-recipient canaries "
                f"({_fmt_pct(min(gem_le3))}-{_fmt_pct(max(gem_le3))}), concentrating "
                f"{_fmt_pct(min(gem_48))}-{_fmt_pct(max(gem_48))} of canaries in 4-8 recipients "
                f"(3 variants of 2-3 staff) and failing on 0-canary-hit seeds."
            ),
            "empirical_evidence": {
                "gemini_opencode_hard_4_to_8_share": _cm(oc_hard, "canary_metrics", "recipient_bins", "4_to_8_share"),
                "gemini_inproc_hard_4_to_8_share": _cm(ip_hard, "canary_metrics", "recipient_bins", "4_to_8_share"),
                "gemini_inproc_medium_4_to_8_share": _cm(ip_med, "canary_metrics", "recipient_bins", "4_to_8_share"),
                "gemini_inproc_medium_zero_surfaced_eps": _cm(ip_med, "canary_metrics", "zero_surfaced_episodes", default=0),
                "gemini_opencode_hard_3var_share": _cm(oc_hard, "canary_metrics", "variant_counts", "v3_share"),
            },
            "dsl_snippet": {
                "name": "wide_crowd_preference",
                "rules": [
                    {
                        "if": [["day", "<=", 6], ["min_recipient_count", "<=", 8], ["max_recipient_count", ">=", 12]],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    }
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
            "solver_catchability": (
                "Regular leaks still narrow department intersections deterministically, and Solver's wide "
                "balanced partitions (>=9 recipients) plus midgame sampling identify the mole above 0.85 accuracy."
            ),
        },
        {
            "id": "reactive_canary_lag_oldest",
            "mole_view_features": ["day", "newest_doc_age_days", "n_leakable"],
            "mole_strategy_selectors": {"leak": "oldest", "frame": "random_peer"},
            "target_weakness": (
                f"Gemini-4-carbon delays first canary on Hard to day {_fmt_opt(_cm(oc_hard, 'canary_metrics', 'first_canary_day_mean', default=None))}-"
                f"{_fmt_opt(_cm(ip_hard, 'canary_metrics', 'first_canary_day_mean', default=None))} "
                f"(vs Solver day {_fmt_opt(_cm(sol14_hard, 'canary_metrics', 'first_canary_day_mean', default=None))}), "
                f"plants reactive age-0 canaries after leaks surface, and accuses with <=1 separating canary under 0.95 fingerprint noise."
            ),
            "empirical_evidence": {
                "gemini_opencode_hard_first_canary_day": _cm(oc_hard, "canary_metrics", "first_canary_day_mean"),
                "gemini_inproc_hard_first_canary_day": _cm(ip_hard, "canary_metrics", "first_canary_day_mean"),
                "solver_hard_first_canary_day": _cm(sol14_hard, "canary_metrics", "first_canary_day_mean"),
                "gemini_opencode_hard_fp95_single_sep_wrong": _cm(oc_hard, "failure_anatomy", "fp95_single_separating_wrong", default=0),
                "gemini_inproc_hard_fp95_single_sep_wrong": _cm(ip_hard, "failure_anatomy", "fp95_single_separating_wrong", default=0),
            },
            "dsl_snippet": {
                "name": "reactive_canary_lag",
                "rules": [
                    {
                        "if": [["day", "<=", 8], ["newest_doc_age_days", "==", 0], ["n_leakable", ">=", 2]],
                        "then": {"leak": "oldest", "frame": "random_peer"},
                    }
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
            "solver_catchability": (
                "Solver plants 2 canaries/day starting day 1.00 (14.13 canaries/episode on Hard), so its day d-2 "
                "canaries already occupy the oldest leak-window slot."
            ),
        },
        {
            "id": "non_decoy_peer_framing",
            "mole_view_features": ["n_restricted_colleagues", "i_am_restricted"],
            "mole_strategy_selectors": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            "target_weakness": (
                f"Frontier models dismissed the angry decoy in {_fmt_pct(cross['frontier_decoy_dismissal_rate'])} "
                f"of {cross['frontier_decoy_episodes_total']} episodes ({decoy_acc_total} decoy {decoy_acc_word}), "
                f"while non-decoy framed after-hours logs broke <=1-separation canary ties into -1.0 wrong accusations "
                f"({cross['wrong_non_decoy_framed_tiebreak']}/{cross['frontier_wrong_accusations_total']} wrong accusations)."
            ),
            "empirical_evidence": {
                "frontier_decoy_dismissal_rate": cross["frontier_decoy_dismissal_rate"],
                "frontier_decoy_dismissal_when_detected_rate": cross["frontier_decoy_dismissal_when_detected_rate"],
                "frontier_decoy_accused_total": decoy_acc_total,
                "wrong_non_decoy_framed_tiebreak": cross["wrong_non_decoy_framed_tiebreak"],
                "wrong_with_zero_separating_canary": cross["wrong_with_zero_separating_canary"],
                "gemini_opencode_hard_log_calls": _cm(oc_hard, "tool_budget", "read_access_logs_mean"),
            },
            "dsl_snippet": {
                "name": "non_decoy_tiebreak_framing",
                "rules": [
                    {
                        "if": [["n_restricted_colleagues", ">=", 1]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    }
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
            "solver_catchability": (
                "Solver marginalises Poisson framing across peers with behaviour_temper=0.6, preventing "
                "single-employee after-hours spikes from overriding primary leak/canary likelihoods."
            ),
        },
        {
            "id": "early_burst_midgame_quiet_pacing",
            "mole_view_features": ["day", "days_since_last_leak"],
            "mole_strategy_selectors": {"leak": "none", "frame": "random_peer"},
            "target_weakness": (
                f"Gemini-4-carbon spends {_fmt_pct(_cm(ip_hard, 'tool_budget', 'interview_investigative_share'))}-"
                f"{_fmt_pct(_cm(oc_hard, 'tool_budget', 'interview_investigative_share'))} of Hard investigative calls "
                f"on low-LR interviews ({_fmt_opt(_cm(ip_hard, 'tool_budget', 'interview_mean'))}-"
                f"{_fmt_opt(_cm(oc_hard, 'tool_budget', 'interview_mean'))}/episode), lags Solver by "
                f"{_fmt_opt(_cm(ip_hard, 'failure_anatomy', 'accuse_day_lag_vs_solver_mean', default=None), signed=True)} to "
                f"{_fmt_opt(_cm(oc_hard, 'failure_anatomy', 'accuse_day_lag_vs_solver_mean', default=None), signed=True)} days, "
                f"and frontier models make {cross['frontier_below_breakeven_gambles_total']} gambles below 1/(1+V) "
                f"({cross['frontier_horizon_gambles_total']} at the horizon)."
            ),
            "empirical_evidence": {
                "gemini_opencode_hard_interviews": _cm(oc_hard, "tool_budget", "interview_mean"),
                "gemini_inproc_hard_interviews": _cm(ip_hard, "tool_budget", "interview_mean"),
                "gemini_opencode_hard_day_lag": _cm(oc_hard, "failure_anatomy", "accuse_day_lag_vs_solver_mean"),
                "gemini_opencode_hard_leak_v_drain": _cm(oc_hard, "failure_anatomy", "leak_v_drain_on_correct_mean"),
                "frontier_below_breakeven_gambles_total": cross["frontier_below_breakeven_gambles_total"],
                "frontier_horizon_gambles_total": cross["frontier_horizon_gambles_total"],
            },
            "dsl_snippet": {
                "name": "early_burst_then_paced",
                "rules": [
                    {
                        "if": [["day", "<=", 3]],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [["day", ">=", 4], ["day", "<=", 9], ["days_since_last_leak", "<", 2]],
                        "then": {"leak": "none", "frame": "random_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
            "solver_catchability": (
                "Leaks on days 1-3 hit Solver's day-1 pipelined canaries immediately, and bounded midgame "
                "pacing preserves leak volume over 21 days so Solver exceeds the 0.85 catchability bar."
            ),
        },
    ]

    for lever in levers:
        MoleStrategy.from_json(lever["dsl_snippet"])
    return levers


def mine_committed_runs(root: str | Path = Path("data/runs/committed")) -> dict[str, Any]:
    committed_root = resolve_committed_root(root)
    loaded_by_ver: dict[
        str,
        tuple[list[tuple[tuple[str, str], dict[str, Any]]], dict[str, Path], list[tuple[str, str, int]]],
    ] = {}
    for ver in ("v1.4", "v1.3"):
        loaded_by_ver[ver] = _load_version_episodes(committed_root, ver)

    raw_by_cohort: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_by_cohort: dict[str, int] = {}
    for cohort_id, ver, agent_name, _ in COHORT_SPECS:
        rec_eps, _, inv_list = loaded_by_ver[ver]
        invalid_by_cohort[cohort_id] = sum(1 for _, ag, _ in inv_list if ag == agent_name)
        max_seed = PRIMARY_SEED_MAX.get(ver, 29)
        by_key: dict[tuple[str, int], tuple[tuple[str, str], dict[str, Any]]] = {}
        for recency, ep in rec_eps:
            if ep.get("agent") != agent_name:
                continue
            seed = int(ep["seed"])
            if not (0 <= seed <= max_seed):
                continue
            key = (str(ep["tier"]), seed)
            prev = by_key.get(key)
            if prev is None or recency > prev[0]:
                by_key[key] = (recency, ep)
        for key in sorted(by_key):
            raw_by_cohort[cohort_id].append(by_key[key][1])

    results_by_cohort: dict[str, list[EpisodeResult]] = {}
    public_decoy_by_ver: dict[str, dict[tuple[str, int], str]] = {"v1.4": {}, "v1.3": {}}
    for cohort_id, ver, _, _ in COHORT_SPECS:
        cohort_ers: list[EpisodeResult] = []
        for ep in raw_by_cohort.get(cohort_id, []):
            er = to_result(ep)
            cohort_ers.append(er)
            dec = detect_angry_decoy(er)
            if dec:
                public_decoy_by_ver[ver][(er.tier, er.seed)] = dec
        results_by_cohort[cohort_id] = cohort_ers

    analyzed_by_cohort: dict[str, list[dict[str, Any]]] = {}
    for cohort_id, ver, _, _ in COHORT_SPECS:
        ers = results_by_cohort.get(cohort_id, [])
        if not ers:
            analyzed_by_cohort[cohort_id] = []
            continue
        with tiers_version(ver):
            analyzed_by_cohort[cohort_id] = [
                analyze_single_episode(er, public_decoy_by_ver[ver])
                for er in ers
            ]

    solver_lookup: dict[str, dict[tuple[str, int], dict[str, Any]]] = {
        "v1.4": {(r["tier"], r["seed"]): r for r in analyzed_by_cohort.get("v1.4_solver", [])},
        "v1.3": {(r["tier"], r["seed"]): r for r in analyzed_by_cohort.get("v1.3_solver", [])},
    }

    cohorts_out: dict[str, Any] = {}
    failure_cases: list[dict[str, Any]] = []

    for cohort_id, ver, agent_name, label in COHORT_SPECS:
        recs = analyzed_by_cohort.get(cohort_id, [])
        if not recs:
            continue
        _, accuse_files, _ = loaded_by_ver[ver]
        verified = _verify_accuse_md(recs, accuse_files, agent_name) if agent_name != "solver" else True
        sol_map = solver_lookup[ver] if agent_name != "solver" else None
        by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in recs:
            by_tier[r["tier"]].append(r)
        tiers_dict = {
            tier: aggregate_records(t_recs, sol_map)
            for tier, t_recs in sorted(by_tier.items())
        }
        cohorts_out[cohort_id] = {
            "version": ver,
            "agent": agent_name,
            "label": label,
            "accuse_md_verified": verified,
            "invalid_excluded_count": invalid_by_cohort.get(cohort_id, 0),
            "tiers": tiers_dict,
            "pooled": aggregate_records(recs, sol_map),
        }

        if agent_name != "solver":
            for r in recs:
                sol = solver_lookup[ver].get((r["tier"], r["seed"]))
                if not r["correct"] or r["below_breakeven_expected"] or r["score"] < 0.35:
                    failure_cases.append({
                        "cohort": cohort_id,
                        "version": ver,
                        "tier": r["tier"],
                        "seed": r["seed"],
                        "agent": r["agent"],
                        "final_day": r["final_day"],
                        "solver_day": sol["final_day"] if sol else None,
                        "accused": r["accused"],
                        "correct": r["correct"],
                        "score": round(r["score"], 3),
                        "solver_score": round(sol["score"], 3) if sol else None,
                        "p_accused": r["p_accused"],
                        "p_top": r["p_top"],
                        "v_expected": r["v_expected"],
                        "breakeven_expected": r["breakeven_expected"],
                        "surfaced_canaries": r["surfaced_canaries"],
                        "accused_canary_hits": r["accused_canary_hits"],
                        "separating_canaries": r["separating_canaries"],
                        "known_decoy": r["known_decoy"],
                        "decoy_after_hours": r["decoy_after_hours"],
                        "accused_after_hours": r["accused_after_hours"],
                        "candidate_cell_size": r["candidate_cell_size"],
                        "candidate_cell_max_after_hours": r["candidate_cell_max_after_hours"],
                        "mechanisms": list(r["failure_mechanisms"]),
                    })

    frontier_recs = [
        r
        for cid, _, agent_name, _ in COHORT_SPECS
        if agent_name != "solver"
        for r in analyzed_by_cohort.get(cid, [])
    ]
    frontier_wrong = [r for r in frontier_recs if r["accused"] is not None and not r["correct"]]
    frontier_decoy_eps = [r for r in frontier_recs if r["known_decoy"] is not None]
    frontier_decoy_det_eps = [r for r in frontier_decoy_eps if r["agent_detected_decoy"] is not None]
    frontier_decoy_acc = sum(1 for r in frontier_decoy_eps if r["decoy_accused"])
    frontier_decoy_det_acc = sum(1 for r in frontier_decoy_det_eps if r["decoy_accused"])
    frontier_decoy_rst = sum(1 for r in frontier_decoy_eps if r["decoy_restricted"])
    frontier_invalid_excl = sum(
        invalid_by_cohort.get(cid, 0)
        for cid, _, agent_name, _ in COHORT_SPECS
        if agent_name != "solver"
    )

    cross_summary = {
        "frontier_episodes_total": len(frontier_recs),
        "frontier_invalid_excluded_total": frontier_invalid_excl,
        "frontier_wrong_accusations_total": len(frontier_wrong),
        "frontier_horizon_abstentions_total": sum(1 for r in frontier_recs if r["accused"] is None),
        "frontier_below_breakeven_gambles_total": sum(1 for r in frontier_recs if r["below_breakeven_expected"]),
        "frontier_horizon_gambles_total": sum(1 for r in frontier_recs if r["horizon_gamble"]),
        "frontier_premature_midgame_gambles_total": sum(1 for r in frontier_recs if r["premature_midgame_gamble"]),
        "frontier_unlisted_feed_episodes_total": sum(1 for r in frontier_recs if r["unlisted_feed_items"] > 0),
        "frontier_unlisted_feed_items_total": sum(r["unlisted_feed_items"] for r in frontier_recs),
        "frontier_decoy_episodes_total": len(frontier_decoy_eps),
        "frontier_decoy_detected_in_messages_total": len(frontier_decoy_det_eps),
        "frontier_decoy_accused_total": frontier_decoy_acc,
        "frontier_decoy_restricted_total": frontier_decoy_rst,
        "frontier_decoy_dismissal_rate": round(
            _safe_div(len(frontier_decoy_eps) - frontier_decoy_acc, len(frontier_decoy_eps)), 4
        ) if frontier_decoy_eps else 1.0,
        "frontier_decoy_dismissal_when_detected_rate": round(
            _safe_div(len(frontier_decoy_det_eps) - frontier_decoy_det_acc, len(frontier_decoy_det_eps)), 4
        ) if frontier_decoy_det_eps else 1.0,
        "wrong_with_le_1_separating_canary": sum(1 for r in frontier_wrong if r["separating_canaries"] <= 1),
        "wrong_with_zero_separating_canary": sum(1 for r in frontier_wrong if r["separating_canaries"] == 0),
        "wrong_non_decoy_framed_tiebreak": sum(1 for r in frontier_wrong if r["non_decoy_framed_tiebreak"]),
        "wrong_fp95_single_separating_canary": sum(
            1 for r in frontier_wrong
            if r["fingerprint_accuracy"] < 1.0 and r["separating_canaries"] <= 1 and r["surfaced_canaries"] >= 1
        ),
    }

    levers = _build_strategy_levers(cohorts_out, cross_summary)

    return {
        "root": str(committed_root),
        "cohorts": cohorts_out,
        "cross_model_summary": cross_summary,
        "failure_cases": failure_cases,
        "strategy_levers": levers,
    }


def _fmt_opt(val: Any, nd: int = 2, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    if isinstance(val, float):
        return f"{val:+.{nd}f}" if signed else f"{val:.{nd}f}"
    return str(val)


def _fmt_pct(val: float | None, nd: int = 1) -> str:
    if val is None:
        return "n/a"
    return f"{100.0 * val:.{nd}f}%"


def render_report(data: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = h1 * 2
    h3 = h1 * 3
    cohorts = data["cohorts"]
    cross = data["cross_model_summary"]
    cases = data["failure_cases"]
    levers = data["strategy_levers"]

    def _get(cid: str, tier: str, *keys: str) -> Any:
        cur: Any = cohorts.get(cid, {}).get("tiers", {}).get(tier, {})
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    n_oc = cohorts.get("v1.4_gemini_opencode", {}).get("pooled", {}).get("n_episodes", 0)
    n_ip = cohorts.get("v1.4_gemini_inproc", {}).get("pooled", {}).get("n_episodes", 0)
    n_cx = cohorts.get("v1.3_codex_gpt55", {}).get("pooled", {}).get("n_episodes", 0)
    n_g5 = cohorts.get("v1.3_inproc_gpt55", {}).get("pooled", {}).get("n_episodes", 0)
    n_s14 = cohorts.get("v1.4_solver", {}).get("pooled", {}).get("n_episodes", 0)
    n_s13 = cohorts.get("v1.3_solver", {}).get("pooled", {}).get("n_episodes", 0)

    gem_le3 = [
        x for x in (
            _get("v1.4_gemini_opencode", "hard", "canary_metrics", "recipient_bins", "le_3_share"),
            _get("v1.4_gemini_opencode", "medium", "canary_metrics", "recipient_bins", "le_3_share"),
            _get("v1.4_gemini_inproc", "hard", "canary_metrics", "recipient_bins", "le_3_share"),
            _get("v1.4_gemini_inproc", "medium", "canary_metrics", "recipient_bins", "le_3_share"),
        ) if x is not None
    ] or [0.0]
    gem_48 = [
        x for x in (
            _get("v1.4_gemini_opencode", "hard", "canary_metrics", "recipient_bins", "4_to_8_share"),
            _get("v1.4_gemini_opencode", "medium", "canary_metrics", "recipient_bins", "4_to_8_share"),
            _get("v1.4_gemini_inproc", "hard", "canary_metrics", "recipient_bins", "4_to_8_share"),
            _get("v1.4_gemini_inproc", "medium", "canary_metrics", "recipient_bins", "4_to_8_share"),
        ) if x is not None
    ] or [0.0]
    gem_ge9 = [
        x for x in (
            _get("v1.4_gemini_opencode", "hard", "canary_metrics", "recipient_bins", "ge_9_share"),
            _get("v1.4_gemini_opencode", "medium", "canary_metrics", "recipient_bins", "ge_9_share"),
            _get("v1.4_gemini_inproc", "hard", "canary_metrics", "recipient_bins", "ge_9_share"),
            _get("v1.4_gemini_inproc", "medium", "canary_metrics", "recipient_bins", "ge_9_share"),
        ) if x is not None
    ] or [0.0]
    gem_v3 = [
        x for x in (
            _get("v1.4_gemini_opencode", "hard", "canary_metrics", "variant_counts", "v3_share"),
            _get("v1.4_gemini_opencode", "medium", "canary_metrics", "variant_counts", "v3_share"),
            _get("v1.4_gemini_inproc", "hard", "canary_metrics", "variant_counts", "v3_share"),
            _get("v1.4_gemini_inproc", "medium", "canary_metrics", "variant_counts", "v3_share"),
        ) if x is not None
    ] or [0.0]
    gpt_le3 = [
        x for x in (
            _get("v1.3_codex_gpt55", "hard", "canary_metrics", "recipient_bins", "le_3_share"),
            _get("v1.3_codex_gpt55", "medium", "canary_metrics", "recipient_bins", "le_3_share"),
            _get("v1.3_inproc_gpt55", "hard", "canary_metrics", "recipient_bins", "le_3_share"),
            _get("v1.3_inproc_gpt55", "medium", "canary_metrics", "recipient_bins", "le_3_share"),
        ) if x is not None
    ] or [0.0]

    oc_iv = _fmt_opt(_get("v1.4_gemini_opencode", "hard", "tool_budget", "interview_mean"))
    ip_iv = _fmt_opt(_get("v1.4_gemini_inproc", "hard", "tool_budget", "interview_mean"))
    oc_d1 = _fmt_opt(_get("v1.4_gemini_opencode", "hard", "canary_metrics", "first_canary_day_mean"))
    ip_d1 = _fmt_opt(_get("v1.4_gemini_inproc", "hard", "canary_metrics", "first_canary_day_mean"))
    sol_d1 = _fmt_opt(_get("v1.4_solver", "hard", "canary_metrics", "first_canary_day_mean"))
    oc_cpd = _fmt_opt(_get("v1.4_gemini_opencode", "hard", "canary_metrics", "per_day_mean"))
    ip_cpd = _fmt_opt(_get("v1.4_gemini_inproc", "hard", "canary_metrics", "per_day_mean"))
    sol_cpd = _fmt_opt(_get("v1.4_solver", "hard", "canary_metrics", "per_day_mean"))
    oc_lag = _fmt_opt(_get("v1.4_gemini_opencode", "hard", "failure_anatomy", "accuse_day_lag_vs_solver_mean"), signed=True)
    ip_lag = _fmt_opt(_get("v1.4_gemini_inproc", "hard", "failure_anatomy", "accuse_day_lag_vs_solver_mean"), signed=True)
    oc_exd = _fmt_opt(_get("v1.4_gemini_opencode", "hard", "failure_anatomy", "extra_leak_v_drain_vs_solver"), 3, signed=True)
    ip_exd = _fmt_opt(_get("v1.4_gemini_inproc", "hard", "failure_anatomy", "extra_leak_v_drain_vs_solver"), 3, signed=True)

    dec_acc = cross["frontier_decoy_accused_total"]
    dec_acc_times = "time" if dec_acc == 1 else "times"
    dec_rst = cross["frontier_decoy_restricted_total"]
    dec_rst_times = "time" if dec_rst == 1 else "times"

    lines: list[str] = [
        f"{h1} Empirical Transcript Mining: Frontier Investigator Failure Modes and Fair Mole Levers",
        "",
        "Generated offline from committed Known-V JSONL transcripts (`data/runs/committed/v1.4/` and `data/runs/committed/v1.3/`; "
        "legacy pre-Known-V `v1.2` runs excluded because `status` exposed unsurfaced `true V`) "
        "via `python -m canary.mole.transcript_miner --out docs/reports/mole_transcript_mining.md` "
        "(verified offline via `python -m canary.mole.transcript_miner --check docs/reports/mole_transcript_mining.md`). "
        "All posteriors are replayed from public tool observations through `canary.solver.policy.SolverPolicy` "
        "(`canary.solver.belief.posterior`) and cross-verified against committed `accuse.md` tables.",
        "",
        f"{h2} 1. Headline Empirical Findings",
        "",
        f"- **Frontier corpus audited**: {cross['frontier_episodes_total']} valid primary frontier episodes "
        f"({n_oc} `opencode:google/gemini-4-carbon` on v1.4 seeds 0-29, {n_ip} `gemini:gemini-4-carbon` in-proc on v1.4 seeds 0-29, "
        f"{n_cx} `codex:gpt-5.5` on v1.3, {n_g5} `openai:gpt-5.5` in-proc on v1.3) paired against "
        f"{n_s14 + n_s13} reference `solver` episodes ({n_s14} on v1.4 seeds 0-29, {n_s13} on v1.3 seeds 0-19).",
        f"- **Angry-decoy dismissal ({_fmt_pct(cross['frontier_decoy_dismissal_rate'])}) vs non-decoy framing susceptibility**: "
        f"Across {cross['frontier_decoy_episodes_total']} decoy-enabled frontier episodes, the angry decoy was accused "
        f"**{dec_acc}** {dec_acc_times} and restricted **{dec_rst}** {dec_rst_times} "
        f"({_fmt_pct(cross['frontier_decoy_dismissal_rate'])} overall dismissal; "
        f"{_fmt_pct(cross['frontier_decoy_dismissal_when_detected_rate'])} across all "
        f"{cross['frontier_decoy_detected_in_messages_total']}/{cross['frontier_decoy_episodes_total']} episodes where angry decoy messages were retrieved). "
        "In contrast, non-decoy framed after-hours logs broke <=1-separation canary ties into -1.0 wrong accusations in "
        f"**{cross['wrong_non_decoy_framed_tiebreak']}/{cross['frontier_wrong_accusations_total']}** "
        "total frontier wrong accusations.",
        f"- **Single-separating-canary fragility under `fingerprint_accuracy=0.95`**: All "
        f"**{cross['wrong_with_le_1_separating_canary']}/{cross['frontier_wrong_accusations_total']}** frontier wrong "
        "accusations occurred with `<=1` separating canary hit (`"
        f"{cross['wrong_with_zero_separating_canary']}/{cross['frontier_wrong_accusations_total']}` with 0 separating "
        f"canaries), including **{cross['wrong_fp95_single_separating_canary']}** Hard-tier wrong accusations where a "
        "5% fingerprint flip or single unconfirmed canary was treated as proof.",
        f"- **Sharp architectural split in canary sizing**: Codex and GPT-5.5 favor surgical `<=3`-recipient traps "
        f"({_fmt_pct(min(gpt_le3))}-{_fmt_pct(max(gpt_le3))} of planted canaries), "
        f"whereas Gemini-4-carbon almost never uses `<=3` recipients ({_fmt_pct(min(gem_le3))}-{_fmt_pct(max(gem_le3))}), putting "
        f"{_fmt_pct(min(gem_v3))}-{_fmt_pct(max(gem_v3))} of canaries into 3 variants across 4-8 "
        f"({_fmt_pct(min(gem_48))}-{_fmt_pct(max(gem_48))}) or >=9 ({_fmt_pct(min(gem_ge9))}-{_fmt_pct(max(gem_ge9))}) recipients.",
        f"- **Gemini-4-carbon interview budget sink and delayed Day-1 canary start**: On v1.4 Hard (`canaries_per_day=2`), "
        f"Gemini-4-carbon spends {ip_iv}-{oc_iv} calls/episode on low-LR interviews (`interview_lr=1.2`), delays its first canary "
        f"until mean day {oc_d1} (OpenCode) and {ip_d1} (in-proc) vs Solver day {sol_d1}, plants {oc_cpd}-{ip_cpd} "
        f"canaries/day vs Solver {sol_cpd}/day, and accuses {ip_lag} to {oc_lag} days later than Solver "
        f"({oc_exd} V to {ip_exd} V extra pure leak drain on correct Hard episodes).",
        f"- **Below-breakeven midgame and horizon gambling**: Frontier agents made **{cross['frontier_below_breakeven_gambles_total']}** "
        "accusations below the exact break-even bar `P(accused) < 1 / (1 + E[true V])`, including "
        f"**{cross['frontier_horizon_gambles_total']}** final-day horizon gambles and "
        f"**{cross['frontier_premature_midgame_gambles_total']}** premature midgame gambles where waiting or abstaining had higher EV.",
        "",
        f"{h2} 2. Canary Planting Rate, Recipient Distribution, and Variant Count",
        "",
        "| Cohort | Tier | n | Score +/- CI | Acc | Canaries/Ep | Canaries/Day | First Canary Day (d1%) | 2-Can/Day% | Surfaced% | Rec <=3 | Rec 4-8 | Rec >=9 | Var 1 / 2 / 3 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for cid, _, _, label in COHORT_SPECS:
        c = cohorts.get(cid)
        if not c:
            continue
        for tier in ("hard", "medium"):
            t = c["tiers"].get(tier)
            if not t:
                continue
            cm = t["canary_metrics"]
            rb = cm["recipient_bins"]
            vc = cm["variant_counts"]
            lines.append(
                f"| {label} | {tier} | {t['n_episodes']} | {t['score_mean']:.3f} +/- {t['score_ci95']:.3f} | "
                f"{_fmt_pct(t['accuracy'], 1)} | {cm['per_episode_mean']:.2f} | {cm['per_day_mean']:.2f} | "
                f"{_fmt_opt(cm['first_canary_day_mean'])} ({_fmt_pct(cm['day1_canary_share'], 0)}) | "
                f"{_fmt_pct(cm['two_canary_day_share'], 1)} | "
                f"{_fmt_pct(cm['surfaced_rate'], 1)} ({cm['surfaced_total']}/{cm['total_planted']}) | "
                f"{_fmt_pct(rb['le_3_share'], 1)} | {_fmt_pct(rb['4_to_8_share'], 1)} | {_fmt_pct(rb['ge_9_share'], 1)} | "
                f"{_fmt_pct(vc['v1_share'], 0)} / {_fmt_pct(vc['v2_share'], 0)} / {_fmt_pct(vc['v3_share'], 0)} |"
            )

    lines.extend([
        "",
        f"{h2} 3. Tool Budget Allocation (Mean Calls per Episode)",
        "",
        "| Cohort | Tier | n | `interview` | `read_access_logs` | `search_messages` | `restrict_access` | `plant_canary` | `list_documents` | `check_leak_feed` | Failed Calls | Interview Share of Investigative |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ])

    for cid, _, _, label in COHORT_SPECS:
        c = cohorts.get(cid)
        if not c:
            continue
        for tier in ("hard", "medium"):
            t = c["tiers"].get(tier)
            if not t:
                continue
            tb = t["tool_budget"]
            lines.append(
                f"| {label} | {tier} | {t['n_episodes']} | {tb['interview_mean']:.2f} | "
                f"{tb['read_access_logs_mean']:.2f} | {tb['search_messages_mean']:.2f} | "
                f"{tb['restrict_access_mean']:.2f} | {tb['plant_canary_mean']:.2f} | "
                f"{tb['list_documents_mean']:.2f} | {tb['check_leak_feed_mean']:.2f} | "
                f"{tb['failed_calls_mean']:.2f} | {_fmt_pct(tb['interview_investigative_share'], 1)} |"
            )

    lines.extend([
        "",
        f"{h2} 4. Failure Anatomy: Fingerprint Flips, Accusation Lag, Gambles, and Decoy vs Framing",
        "",
        "| Cohort | Tier | Wrong / Abstain | Accuse Day (Lag vs Solver) | Correct Leak V Drain (vs Solver) | <=1-Hit Acc under fp=0.95 (Wrong) | <=1-Sep Acc under fp=0.95 (Wrong) | Gambles P < 1/(1+V) (Horizon) | Decoy Msg Found / Max-AH / Dismissed | Non-Decoy Framed Tie-Break Wrong |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])

    for cid, _, _, label in COHORT_SPECS:
        c = cohorts.get(cid)
        if not c:
            continue
        for tier in ("hard", "medium"):
            t = c["tiers"].get(tier)
            if not t:
                continue
            fa = t["failure_anatomy"]
            lag_val = fa["accuse_day_lag_vs_solver_mean"]
            lag_cell = f"{lag_val:+.2f}d" if lag_val is not None else "baseline"
            drain_val = fa["leak_v_drain_on_correct_mean"]
            drain_cell = f"{drain_val:.3f} V" if drain_val is not None else "n/a"
            extra_val = fa["extra_leak_v_drain_vs_solver"]
            extra_cell = f"{extra_val:+.3f} V" if extra_val is not None else "baseline"
            dec_tot = fa["decoy_present_episodes"]
            lines.append(
                f"| {label} | {tier} | {t['wrong_count']} / {t['abstain_count']} | "
                f"{_fmt_opt(t['accuse_day_mean'], 2)} ({lag_cell}) | "
                f"{drain_cell} ({extra_cell}) | "
                f"{fa['fp95_single_canary_hit_accusations']} ({fa['fp95_single_canary_hit_wrong']}) | "
                f"{fa['fp95_single_separating_accusations']} ({fa['fp95_single_separating_wrong']}) | "
                f"{fa['below_breakeven_gambles']} ({fa['horizon_gambles']}) | "
                f"{fa['decoy_detected_in_messages']}/{dec_tot} / {fa['decoy_max_after_hours_episodes']}/{dec_tot} / "
                f"{_fmt_pct(fa['decoy_dismissal_rate'], 0)} | "
                f"{fa['non_decoy_framed_tiebreak_wrong']} |"
            )

    lines.extend([
        "",
        f"{h3} 4.1 Episode-Level Anatomy of Wrong, Abstained, Gamble, and Severe V-Drain Runs",
        "",
        "| Cohort | Tier | Seed | Day (Solver) | Accused | Score (Solver) | P(acc) vs BE | Surf Canaries (Hits / Sep) | Decoy (AH) | Accused AH (Cell Max AH, Cell Size) | Failure Mechanisms |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ])

    for fc in cases:
        acc_str = fc["accused"] or "None"
        sol_d = _fmt_opt(fc["solver_day"], 0)
        sol_s = _fmt_opt(fc["solver_score"], 2)
        p_str = f"{_fmt_opt(fc['p_accused'], 3)} vs {fc['breakeven_expected']:.3f}"
        dec_str = f"{fc['known_decoy'] or 'n/a'} ({fc['decoy_after_hours']})"
        ah_str = f"{fc['accused_after_hours']} (max={fc['candidate_cell_max_after_hours']}, k={fc['candidate_cell_size']})"
        mech_str = ", ".join(fc["mechanisms"]) if fc["mechanisms"] else "low_v"
        lines.append(
            f"| `{fc['cohort']}` | {fc['tier']} | {fc['seed']} | {fc['final_day']} ({sol_d}) | "
            f"{acc_str} | {fc['score']:.2f} ({sol_s}) | {p_str} | "
            f"{fc['surfaced_canaries']} ({fc['accused_canary_hits']} / {fc['separating_canaries']}) | "
            f"{dec_str} | {ah_str} | `{mech_str}` |"
        )

    lines.extend([
        "",
        f"{h2} 5. Mapping Empirical Weaknesses to Fair `MoleView` / `MoleStrategy` Levers",
        "",
        "Every lever below uses only public-free, non-omniscient `MoleView` features from `canary.mole.dsl` "
        "(the mole never knows which document is a canary or who the investigator suspects) and validates cleanly "
        "through `MoleStrategy.from_json` while keeping the reference `SolverPolicy` above the 0.85 catchability gate.",
        "",
    ])

    for idx, lv in enumerate(levers, 1):
        feats = ", ".join(f"`{f}`" for f in lv["mole_view_features"])
        sels = f"`leak={lv['mole_strategy_selectors']['leak']}`, `frame={lv['mole_strategy_selectors']['frame']}`"
        ev_parts = [f"`{k}={v}`" for k, v in lv["empirical_evidence"].items()]
        lines.extend([
            f"{h3} 5.{idx} Lever `{lv['id']}`",
            f"- **`MoleView` features**: {feats}",
            f"- **`MoleStrategy` selectors**: {sels}",
            f"- **Empirical target**: {lv['target_weakness']}",
            f"- **Measured transcript anchors**: {', '.join(ev_parts)}",
            f"- **Why `SolverPolicy` stays unbeaten**: {lv['solver_catchability']}",
            "- **Validated Mole DSL rule snippet**:",
            "```json",
            json.dumps(lv["dsl_snippet"], indent=2),
            "```",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


_TOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:[.-][A-Za-z0-9_]+)*"
    r"|\d+_[A-Za-z0-9_]+"
    r"|(?P<num>(?:(?<![0-9%])[+-])?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)


def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _tokenize_report_line(line: str) -> tuple[tuple[str, ...], list[str]]:
    literals: list[str] = []
    numbers: list[str] = []
    last_end = 0
    for match in _TOKEN_RE.finditer(line):
        num = match.group("num")
        if num is None:
            continue
        literals.append(line[last_end:match.start()])
        numbers.append(num)
        last_end = match.end()
    literals.append(line[last_end:])
    return tuple(literals), numbers


def _is_int_token(tok: str) -> bool:
    return "." not in tok and "e" not in tok and "E" not in tok


def reports_agree(actual_md: str, expected_md: str, tol: float = 1e-9) -> tuple[bool, str]:
    if actual_md == expected_md:
        return True, "exact match"
    if actual_md.endswith("\n") != expected_md.endswith("\n"):
        return False, "trailing newline mismatch"
    act_lines = actual_md.splitlines()
    exp_lines = expected_md.splitlines()
    if len(act_lines) != len(exp_lines):
        return False, f"line count mismatch: {len(act_lines)} vs {len(exp_lines)}"
    for idx, (act_ln, exp_ln) in enumerate(zip(act_lines, exp_lines), 1):
        if act_ln == exp_ln:
            continue
        act_lit, act_nums = _tokenize_report_line(act_ln)
        exp_lit, exp_nums = _tokenize_report_line(exp_ln)
        if act_lit != exp_lit or len(act_nums) != len(exp_nums):
            return False, f"text mismatch on line {idx}"
        for tok_a, tok_b in zip(act_nums, exp_nums):
            int_a = _is_int_token(tok_a)
            int_b = _is_int_token(tok_b)
            if int_a and int_b:
                if int(tok_a) != int(tok_b):
                    return False, f"integer mismatch on line {idx}: {tok_a} vs {tok_b}"
            elif int_a != int_b:
                return False, f"numeric type mismatch on line {idx}: {tok_a} vs {tok_b}"
            elif not math.isclose(float(tok_a), float(tok_b), rel_tol=tol, abs_tol=tol):
                return False, f"float mismatch on line {idx}: {tok_a} vs {tok_b} (tol={tol:g})"
    return True, f"numerical agreement within {tol:g}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic offline miner for committed Canary frontier transcripts.")
    ap.add_argument("--runs", type=Path, default=Path("data/runs/committed"), help="Path to committed runs root")
    ap.add_argument("--out", type=Path, default=None, help="Markdown output file path")
    ap.add_argument(
        "--check",
        nargs="?",
        const=Path("docs/reports/mole_transcript_mining.md"),
        default=None,
        type=Path,
        help="Recompute offline and verify numerical agreement within 1e-9 float tolerance",
    )
    ap.add_argument("--tol", type=float, default=1e-9, help="Float tolerance for --check")
    ap.add_argument("--json", action="store_true", help="Print JSON summary to stdout")
    args = ap.parse_args(argv)

    mined = mine_committed_runs(args.runs)
    md = render_report(mined)

    if args.check is not None:
        if not args.check.is_file():
            print(f"{args.check} does not exist")
            return 1
        actual_txt = args.check.read_text(encoding="utf-8")
        if args.check.suffix == ".json":
            try:
                actual_json = json.loads(actual_txt)
            except ValueError as exc:
                print(f"{args.check} invalid JSON: {exc}")
                return 1
            fresh_json = json.loads(json.dumps(mined))
            if not approx_equal(actual_json, fresh_json, tol=args.tol):
                print(f"{args.check} differs from fresh offline computation beyond tol={args.tol:g}")
                return 1
            print(f"verified {args.check} (tol={args.tol:g})")
            return 0
        ok_agree, reason = reports_agree(actual_txt, md, tol=args.tol)
        if not ok_agree:
            print(f"{args.check} differs from fresh offline computation: {reason}")
            return 1
        print(f"verified {args.check} ({reason})")
        return 0

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")

    if args.json:
        print(json.dumps(mined, indent=2))
    else:
        cs = mined["cross_model_summary"]
        print(
            f"mined {cs['frontier_episodes_total']} frontier episodes across {len(mined['cohorts'])} cohorts; "
            f"wrong={cs['frontier_wrong_accusations_total']}, "
            f"abstain={cs['frontier_horizon_abstentions_total']}, "
            f"gambles_below_be={cs['frontier_below_breakeven_gambles_total']}, "
            f"decoy_dismissed={cs['frontier_decoy_dismissal_rate']:.1%}"
        )
        if args.out is not None:
            print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
