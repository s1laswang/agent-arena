from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from canary.agents.runlog import git_sha
from canary.analysis.tags import to_result
from canary.baselines import BASELINES, CALIBRATION_POLICIES
from canary.rules import TIERS_HISTORY, TIERS_VERSION, tier_params_for_episode
from canary.solver.params import params_from_instruction
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult

EPS = 1e-12
SCRIPTED_AGENTS = frozenset({"solver", *BASELINES.keys(), *CALIBRATION_POLICIES.keys()})
SKIP_DIRS = frozenset({"superseded", "_invalid", "_ledger"})


def break_even_threshold(v_true: float, wrong_score: float = -1.0) -> float:
    v = float(v_true)
    w = float(wrong_score)
    if math.isnan(v) or math.isinf(v) or v < 0.0:
        raise ValueError(f"v_true must be finite and >= 0, got {v_true!r}")
    if math.isnan(w) or math.isinf(w) or w >= 0.0:
        raise ValueError(f"wrong_score must be finite and < 0, got {wrong_score!r}")
    if w == -1.0:
        return 1.0 / (1.0 + v)
    return -w / (v - w)


def expected_accuse_ev(p_accused: float, v_true: float, wrong_score: float = -1.0) -> float:
    p = float(p_accused)
    if math.isnan(p) or p < -1e-9 or p > 1.0 + 1e-9:
        raise ValueError(f"p_accused must be in [0, 1], got {p_accused!r}")
    p = min(1.0, max(0.0, p))
    v = float(v_true)
    w = float(wrong_score)
    if math.isnan(v) or math.isinf(v) or v < 0.0:
        raise ValueError(f"v_true must be finite and >= 0, got {v_true!r}")
    if math.isnan(w) or math.isinf(w) or w >= 0.0:
        raise ValueError(f"wrong_score must be finite and < 0, got {wrong_score!r}")
    return p * v + (1.0 - p) * w


def premature_ev_loss(p_accused: float | None, v_true: float, wrong_score: float = -1.0) -> float:
    if p_accused is None:
        return 0.0
    ev = expected_accuse_ev(p_accused, v_true, wrong_score)
    return -ev if ev < -EPS else 0.0


def classify_agent(agent: str, meta: dict[str, Any] | None = None, rel_parts: tuple[str, ...] = ()) -> str:
    if "reference" in rel_parts or agent in SCRIPTED_AGENTS:
        return "reference"
    low = (agent or "").lower()
    lad = (meta or {}).get("ladder") or {}
    lad_model = str(lad.get("model") or "").lower()
    if "gemini" in low or "gemini" in lad_model:
        return "gemini"
    return "frontier"


def infer_version(
    res: EpisodeResult,
    rel_parts: tuple[str, ...] = (),
    dir_meta: dict[str, Any] | None = None,
    root_parts: tuple[str, ...] = (),
) -> str:
    all_parts = (*root_parts, *rel_parts)
    for part in all_parts:
        if part.startswith("v1."):
            return part
    meta = res.meta or {}
    if isinstance(meta.get("tiers_version"), str) and meta["tiers_version"]:
        return meta["tiers_version"]
    if dir_meta and isinstance(dir_meta.get("tiers_version"), str) and dir_meta["tiers_version"]:
        return dir_meta["tiers_version"]
    if "committed" in all_parts:
        return "v1.2"
    params = tier_params_for_episode(res.tier, res.steps)
    if res.tier in ("hard", "hard_forge") and params.n_employees == 30:
        return "v1.3"
    return TIERS_VERSION


def _params_for_episode(res: EpisodeResult, version: str | None, instruction: str | None):
    if instruction:
        parsed = params_from_instruction(instruction)
        if parsed is not None:
            return parsed
    has_emp_step = any(
        st.tool == "list_employees" and isinstance(st.result, dict) and st.result.get("ok")
        for st in res.steps
    )
    if not has_emp_step and version in ("v1.2", "v1.3"):
        hist = TIERS_HISTORY.get("v1.3") or {}
        if res.tier in hist:
            return hist[res.tier]
    return tier_params_for_episode(res.tier, res.steps)


def episode_posterior(
    ep: EpisodeResult | dict[str, Any],
    instruction: str | None = None,
    version: str | None = None,
) -> tuple[dict[str, float], SolverPolicy, int, int, str | None]:
    res = to_result(ep) if isinstance(ep, dict) else ep
    params = _params_for_episode(res, version=version, instruction=instruction)
    sp = SolverPolicy(params)
    default_emps = [f"e{k:02d}" for k in range(max(1, params.n_employees))]
    sp.obs.employees = list(default_emps)

    acc_idx = next((i for i, st in enumerate(res.steps) if st.tool == "accuse"), None)
    stop_idx = acc_idx if acc_idx is not None else len(res.steps)
    for prev in res.steps[:stop_idx]:
        sp._ingest(prev)
    sp.seen = stop_idx
    if not sp.obs.employees:
        sp.obs.employees = list(default_emps)

    raw_post = sp.belief()
    clamped = {emp: min(1.0, max(0.0, float(prob))) for emp, prob in raw_post.items()}
    total = sum(clamped.values())
    if total > 0.0:
        post = {emp: prob / total for emp, prob in clamped.items()}
    else:
        n_emp = len(sp.obs.employees) or 1
        post = {emp: 1.0 / n_emp for emp in sp.obs.employees}

    if acc_idx is not None:
        step_obj = res.steps[acc_idx]
        decision_step = int(step_obj.t if step_obj.t is not None else acc_idx)
        decision_day = int(step_obj.day)
        accused = (step_obj.args or {}).get("employee") or res.accused
    else:
        decision_step = len(res.steps)
        decision_day = int(res.final_day)
        accused = res.accused

    return post, sp, decision_step, decision_day, accused


def resolve_v_true(res: EpisodeResult, sp: SolverPolicy, version: str | None = None) -> float:
    meta = res.meta or {}
    for key in ("V_true", "V", "V_final"):
        val = meta.get(key)
        if val is not None:
            return min(1.0, max(0.0, float(val)))
    if res.accused and res.correct and res.score >= 0.0:
        return min(1.0, max(0.0, float(res.score)))
    if version == "v1.2":
        return min(1.0, max(0.0, float(sp.V)))
    return min(1.0, max(0.0, float(sp.expected_true_V())))


def analyze_episode(
    ep: EpisodeResult | dict[str, Any],
    version: str | None = None,
    instruction: str | None = None,
    rel_parts: tuple[str, ...] = (),
    dir_meta: dict[str, Any] | None = None,
    root_parts: tuple[str, ...] = (),
) -> dict[str, Any]:
    res = to_result(ep) if isinstance(ep, dict) else ep
    ver = version or infer_version(res, rel_parts=rel_parts, dir_meta=dir_meta, root_parts=root_parts)
    post, sp, decision_step, decision_day, accused = episode_posterior(res, instruction=instruction, version=ver)
    v_true = resolve_v_true(res, sp, version=ver)
    wrong_score = float(getattr(sp.P, "wrong_accusation_score", -1.0))
    threshold = break_even_threshold(v_true, wrong_score=wrong_score)

    top_employee = max(post, key=post.get)
    p_top = float(post[top_employee])
    did_accuse = bool(accused)
    p_accused = float(post.get(accused, 0.0)) if did_accuse else None

    ev_accuse = expected_accuse_ev(p_accused, v_true, wrong_score=wrong_score) if p_accused is not None else 0.0
    ev_top = expected_accuse_ev(p_top, v_true, wrong_score=wrong_score)
    premature_commit = bool(did_accuse and ev_accuse < -EPS)
    ev_lost = premature_ev_loss(p_accused, v_true, wrong_score=wrong_score)
    missed_commit = bool((not did_accuse) and ev_top > EPS)
    missed_ev = max(0.0, ev_top) if not did_accuse else 0.0
    suboptimal_target = bool(did_accuse and p_accused is not None and p_accused + 1e-9 < p_top)

    gated_ev = max(0.0, ev_accuse) if did_accuse else 0.0
    score = float(res.score)
    gated_score = 0.0 if premature_commit else score
    correct = bool(res.correct)
    brier = ((p_accused - (1.0 if correct else 0.0)) ** 2) if p_accused is not None else None

    if not did_accuse:
        verdict = "abstained_missed_ev" if missed_commit else "abstained_rational"
    elif premature_commit:
        verdict = "premature_lucky" if correct else "premature_wrong"
    else:
        verdict = "calibrated_correct" if correct else "calibrated_unlucky"

    meta = res.meta or {}
    lad = meta.get("ladder") or {}
    thinking_level = lad.get("thinking_level") or meta.get("thinking_level") or (dir_meta or {}).get("thinking_level")
    family = classify_agent(res.agent, meta=meta, rel_parts=rel_parts)

    return {
        "version": ver,
        "family": family,
        "agent": res.agent,
        "thinking_level": thinking_level,
        "tier": res.tier,
        "seed": int(res.seed),
        "run_id": meta.get("run_id") or (dir_meta or {}).get("run_id"),
        "end_reason": res.end_reason,
        "final_day": int(res.final_day),
        "decision_step": decision_step,
        "decision_day": decision_day,
        "n_employees": len(post),
        "did_accuse": did_accuse,
        "accused": accused,
        "correct": correct,
        "score": score,
        "gated_score": gated_score,
        "v_true": v_true,
        "wrong_score": wrong_score,
        "threshold": threshold,
        "p_accused": p_accused,
        "p_top": p_top,
        "top_employee": top_employee,
        "ev_accuse": ev_accuse,
        "ev_top": ev_top,
        "gated_ev": gated_ev,
        "premature_commit": premature_commit,
        "ev_lost": ev_lost,
        "missed_commit": missed_commit,
        "missed_ev": missed_ev,
        "suboptimal_target": suboptimal_target,
        "brier": brier,
        "verdict": verdict,
        "posterior": post,
    }


def _scan_root(root: str | Path) -> list[tuple[dict[str, Any], tuple[str, ...], dict[str, Any]]]:
    base = Path(root)
    if not base.exists():
        return []
    files = [base] if base.is_file() else sorted(base.rglob("episodes.jsonl"))
    items: list[tuple[dict[str, Any], tuple[str, ...], dict[str, Any]]] = []
    for fp in files:
        rel_parts = () if base.is_file() else fp.relative_to(base).parts[:-1]
        if any(p in SKIP_DIRS or p.endswith("-smoke") for p in rel_parts):
            continue
        meta_path = fp.parent / "meta.json"
        dir_meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                loaded = json.loads(meta_path.read_text())
                if isinstance(loaded, dict):
                    dir_meta = loaded
            except (OSError, json.JSONDecodeError):
                dir_meta = {}
        for line in fp.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            ep = json.loads(line)
            emeta = ep.get("meta") or {}
            if emeta.get("valid") is False or ep.get("end_reason") == "error":
                continue
            ep = dict(ep)
            merged_meta = dict(emeta)
            merged_meta.setdefault("run_id", fp.parent.name)
            ep["meta"] = merged_meta
            items.append((ep, tuple(rel_parts), dir_meta))
    return items


def load_episodes(
    runs_dir: str | Path = "data/runs/committed",
    include_reference: bool = False,
    tier: str | None = None,
    agent_prefix: str = "",
    extra_runs: Iterable[str | Path] = (),
) -> list[dict[str, Any]]:
    roots = [runs_dir, *extra_runs]
    out: list[dict[str, Any]] = []
    for root in roots:
        for ep, rel_parts, dir_meta in _scan_root(root):
            fam = classify_agent(ep.get("agent", ""), meta=ep.get("meta"), rel_parts=rel_parts)
            if not include_reference and fam == "reference":
                continue
            if tier and ep.get("tier") != tier:
                continue
            if agent_prefix and not str(ep.get("agent", "")).startswith(agent_prefix):
                continue
            meta = dict(ep.get("meta") or {})
            if "tiers_version" not in meta and dir_meta.get("tiers_version"):
                meta["tiers_version"] = dir_meta["tiers_version"]
            for p in rel_parts:
                if p.startswith("v1."):
                    meta.setdefault("tiers_version", p)
                    break
            if "thinking_level" not in meta and dir_meta.get("thinking_level"):
                meta["thinking_level"] = dir_meta["thinking_level"]
            ep["meta"] = meta
            out.append(ep)
    return out


def calibration_bins(records: Iterable[dict[str, Any]], n_bins: int = 10) -> list[dict[str, Any]]:
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins!r}")
    accused_recs = [r for r in records if r.get("did_accuse") and r.get("p_accused") is not None]
    bins: list[dict[str, Any]] = []
    for idx in range(n_bins):
        lo = idx / n_bins
        hi = (idx + 1) / n_bins
        mid = 0.5 * (lo + hi)
        if idx < n_bins - 1:
            members = [r for r in accused_recs if lo <= float(r["p_accused"]) < hi]
        else:
            members = [r for r in accused_recs if lo <= float(r["p_accused"]) <= 1.0]
        cnt = len(members)
        if cnt == 0:
            bins.append({
                "bin_index": idx,
                "lo": round(lo, 6),
                "hi": round(hi, 6),
                "mid": round(mid, 6),
                "count": 0,
                "mean_predicted": None,
                "empirical_accuracy": None,
                "calibration_gap": None,
                "signed_gap": None,
                "mean_threshold": None,
                "mean_v_true": None,
                "mean_score": None,
                "mean_ev": None,
                "premature_count": 0,
                "ev_lost_sum": 0.0,
            })
            continue
        mean_pred = sum(float(r["p_accused"]) for r in members) / cnt
        emp_acc = sum(1.0 if r["correct"] else 0.0 for r in members) / cnt
        mean_thr = sum(float(r["threshold"]) for r in members) / cnt
        mean_vt = sum(float(r["v_true"]) for r in members) / cnt
        mean_sc = sum(float(r["score"]) for r in members) / cnt
        mean_ev = sum(float(r["ev_accuse"]) for r in members) / cnt
        prem_cnt = sum(1 for r in members if r["premature_commit"])
        loss_sum = sum(float(r["ev_lost"]) for r in members)
        bins.append({
            "bin_index": idx,
            "lo": round(lo, 6),
            "hi": round(hi, 6),
            "mid": round(mid, 6),
            "count": cnt,
            "mean_predicted": mean_pred,
            "empirical_accuracy": emp_acc,
            "calibration_gap": abs(mean_pred - emp_acc),
            "signed_gap": mean_pred - emp_acc,
            "mean_threshold": mean_thr,
            "mean_v_true": mean_vt,
            "mean_score": mean_sc,
            "mean_ev": mean_ev,
            "premature_count": prem_cnt,
            "ev_lost_sum": loss_sum,
        })
    return bins


def summarize_records(records: Iterable[dict[str, Any]], n_bins: int = 10) -> dict[str, Any]:
    recs = list(records)
    n_ep = len(recs)
    if n_ep == 0:
        return {
            "n_episodes": 0,
            "n_accused": 0,
            "n_abstained": 0,
            "accuse_rate": 0.0,
            "accuracy_overall": 0.0,
            "accuracy_when_accused": None,
            "mean_score": 0.0,
            "mean_gated_score": 0.0,
            "realized_abstain_gain": 0.0,
            "mean_v_true": None,
            "mean_threshold": None,
            "mean_p_accused": None,
            "mean_p_top": None,
            "mean_ev": 0.0,
            "mean_gated_ev": 0.0,
            "premature_count": 0,
            "premature_rate_episodes": 0.0,
            "premature_rate_accusations": 0.0,
            "ev_lost_total": 0.0,
            "ev_lost_per_episode": 0.0,
            "ev_lost_per_premature": 0.0,
            "missed_commit_count": 0,
            "missed_ev_total": 0.0,
            "suboptimal_target_count": 0,
            "brier_score": None,
            "ece": None,
        }

    accused_recs = [r for r in recs if r["did_accuse"] and r["p_accused"] is not None]
    n_acc = len(accused_recs)
    n_abs = n_ep - n_acc
    prem_recs = [r for r in recs if r["premature_commit"]]
    n_prem = len(prem_recs)

    mean_score = sum(float(r["score"]) for r in recs) / n_ep
    mean_gated_score = sum(float(r["gated_score"]) for r in recs) / n_ep
    mean_v_true = sum(float(r["v_true"]) for r in recs) / n_ep
    mean_thr = sum(float(r["threshold"]) for r in recs) / n_ep
    mean_p_top = sum(float(r["p_top"]) for r in recs) / n_ep
    mean_ev = sum(float(r["ev_accuse"]) for r in recs) / n_ep
    mean_gated_ev = sum(float(r["gated_ev"]) for r in recs) / n_ep
    ev_lost_total = sum(float(r["ev_lost"]) for r in recs)
    missed_cnt = sum(1 for r in recs if r["missed_commit"])
    missed_ev_total = sum(float(r["missed_ev"]) for r in recs)
    subopt_cnt = sum(1 for r in recs if r["suboptimal_target"])

    if n_acc > 0:
        acc_when_acc = sum(1.0 if r["correct"] else 0.0 for r in accused_recs) / n_acc
        mean_p_acc = sum(float(r["p_accused"]) for r in accused_recs) / n_acc
        brier = sum(float(r["brier"]) for r in accused_recs if r["brier"] is not None) / n_acc
        bins = calibration_bins(accused_recs, n_bins=n_bins)
        ece = sum((b["count"] / n_acc) * float(b["calibration_gap"]) for b in bins if b["count"] > 0)
    else:
        acc_when_acc = None
        mean_p_acc = None
        brier = None
        ece = None

    return {
        "n_episodes": n_ep,
        "n_accused": n_acc,
        "n_abstained": n_abs,
        "accuse_rate": n_acc / n_ep,
        "accuracy_overall": sum(1.0 if r["correct"] else 0.0 for r in recs) / n_ep,
        "accuracy_when_accused": acc_when_acc,
        "mean_score": mean_score,
        "mean_gated_score": mean_gated_score,
        "realized_abstain_gain": mean_gated_score - mean_score,
        "mean_v_true": mean_v_true,
        "mean_threshold": mean_thr,
        "mean_p_accused": mean_p_acc,
        "mean_p_top": mean_p_top,
        "mean_ev": mean_ev,
        "mean_gated_ev": mean_gated_ev,
        "premature_count": n_prem,
        "premature_rate_episodes": n_prem / n_ep,
        "premature_rate_accusations": (n_prem / n_acc) if n_acc > 0 else 0.0,
        "ev_lost_total": ev_lost_total,
        "ev_lost_per_episode": ev_lost_total / n_ep,
        "ev_lost_per_premature": (ev_lost_total / n_prem) if n_prem > 0 else 0.0,
        "missed_commit_count": missed_cnt,
        "missed_ev_total": missed_ev_total,
        "suboptimal_target_count": subopt_cnt,
        "brier_score": brier,
        "ece": ece,
    }


def build_report(
    records: list[dict[str, Any]],
    n_bins: int = 10,
    runs_dir: str = "",
    reference_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(
        records,
        key=lambda r: (
            str(r.get("version") or ""),
            str(r.get("agent") or ""),
            str(r.get("thinking_level") or ""),
            str(r.get("tier") or ""),
            int(r.get("seed") or 0),
        ),
    )
    summary = summarize_records(ordered, n_bins=n_bins)
    bins = calibration_bins(ordered, n_bins=n_bins)

    fam_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    agent_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cell_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    tier_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ver_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for rec in ordered:
        fam_groups[rec["family"]].append(rec)
        agent_groups[rec["agent"]].append(rec)
        cell_key = (
            rec["version"],
            rec["agent"],
            str(rec.get("thinking_level") or ""),
            rec["tier"],
        )
        cell_groups[cell_key].append(rec)
        tier_groups[rec["tier"]].append(rec)
        ver_groups[rec["version"]].append(rec)

    by_family = {fam: summarize_records(rs, n_bins=n_bins) for fam, rs in sorted(fam_groups.items())}
    by_tier = {t: summarize_records(rs, n_bins=n_bins) for t, rs in sorted(tier_groups.items())}
    by_version = {v: summarize_records(rs, n_bins=n_bins) for v, rs in sorted(ver_groups.items())}

    by_agent: list[dict[str, Any]] = []
    for agent, rs in sorted(agent_groups.items(), key=lambda kv: (kv[1][0]["family"] != "gemini", kv[0])):
        row = {"agent": agent, "family": rs[0]["family"]}
        row.update(summarize_records(rs, n_bins=n_bins))
        by_agent.append(row)

    by_agent_tier: list[dict[str, Any]] = []
    for (ver, agent, think, tier_name), rs in sorted(cell_groups.items()):
        row = {
            "version": ver,
            "family": rs[0]["family"],
            "agent": agent,
            "thinking_level": think or None,
            "tier": tier_name,
        }
        row.update(summarize_records(rs, n_bins=n_bins))
        by_agent_tier.append(row)

    premature_examples = [
        {k: v for k, v in rec.items() if k != "posterior"}
        for rec in sorted(
            (r for r in ordered if r["premature_commit"]),
            key=lambda r: (-float(r["ev_lost"]), r["agent"], r["tier"], r["seed"]),
        )
    ]

    ref_benchmarks: list[dict[str, Any]] = []
    if reference_records:
        ref_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for rec in reference_records:
            ref_groups[(rec["version"], rec["agent"], rec["tier"])].append(rec)
        for (ver, agent, tier_name), rs in sorted(ref_groups.items()):
            row = {"version": ver, "agent": agent, "tier": tier_name}
            row.update(summarize_records(rs, n_bins=n_bins))
            ref_benchmarks.append(row)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_sha": git_sha(),
        "runs_dir": str(runs_dir),
        "n_bins": n_bins,
        "summary": summary,
        "bins": bins,
        "by_family": by_family,
        "by_agent": by_agent,
        "by_agent_tier": by_agent_tier,
        "by_tier": by_tier,
        "by_version": by_version,
        "premature_examples": premature_examples,
        "reference_benchmarks": ref_benchmarks,
        "episodes": ordered,
    }


def analyze_episodes(
    episodes: Iterable[EpisodeResult | dict[str, Any]],
    n_bins: int = 10,
    runs_dir: str = "",
) -> dict[str, Any]:
    records = [analyze_episode(ep) for ep in episodes]
    return build_report(records, n_bins=n_bins, runs_dir=runs_dir)


def plot_calibration(report: dict[str, Any], out_path: str | Path) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    summary = report.get("summary") or {}
    bins = report.get("bins") or []
    episodes = report.get("episodes") or []

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.6, 5.4))

    ax1.plot([0.0, 1.0], [0.0, 1.0], linestyle="--", color=(0.35, 0.35, 0.35), linewidth=1.2, label="Ideal calibration (y = x)")

    mean_thr = summary.get("mean_threshold")
    if mean_thr is not None:
        ax1.axvspan(0.0, float(mean_thr), color=(0.98, 0.86, 0.85), alpha=0.4, label=f"Mean premature zone (< {float(mean_thr):.3f})")
        ax1.axvline(float(mean_thr), linestyle=":", color=(0.78, 0.16, 0.16), linewidth=1.4)

    non_empty = [b for b in bins if int(b.get("count") or 0) > 0]
    if non_empty:
        xs = [float(b["mean_predicted"]) for b in non_empty]
        ys = [float(b["empirical_accuracy"]) for b in non_empty]
        errs = [
            math.sqrt(max(0.0, y * (1.0 - y)) / max(1, int(b["count"])))
            for b, y in zip(non_empty, ys)
        ]
        ax1.errorbar(
            xs,
            ys,
            yerr=errs,
            marker="o",
            markersize=6,
            linewidth=1.8,
            capsize=3,
            color=(0.11, 0.38, 0.76),
            label="Empirical accuracy (binned)",
        )
        for b, x_val, y_val in zip(non_empty, xs, ys):
            offset = (-26, -13) if x_val > 0.88 else (4, 5)
            ax1.annotate(
                f"n={b['count']}",
                (x_val, y_val),
                fontsize=7.5,
                xytext=offset,
                textcoords="offset points",
            )

    ax1.set_xlim(-0.02, 1.02)
    ax1.set_ylim(-0.05, 1.06)
    ax1.set_xlabel("Bayesian posterior P(accused == mole) at accusation")
    ax1.set_ylabel("Empirical accusation accuracy")
    ax1.set_title("Posterior Reliability Curve")
    ax1.grid(True, alpha=0.25)
    ax1.legend(fontsize=8, loc="lower right")

    v_grid = [i / 200.0 for i in range(201)]
    thr_grid = [break_even_threshold(v) for v in v_grid]
    ax2.plot(v_grid, thr_grid, color=(0.78, 0.16, 0.16), linewidth=2.0, label="Rational break-even 1 / (1 + V_true)")
    ax2.fill_between(v_grid, 0.0, thr_grid, color=(0.98, 0.84, 0.82), alpha=0.38, label="Premature commit (EV < 0 vs abstain)")
    ax2.fill_between(v_grid, thr_grid, 1.0, color=(0.86, 0.95, 0.86), alpha=0.32, label="Rational commit (EV >= 0)")

    palette = {
        "gemini": (0.08, 0.45, 0.85),
        "frontier": (0.85, 0.38, 0.11),
        "reference": (0.42, 0.42, 0.42),
    }

    for fam in ("gemini", "frontier", "reference"):
        fam_acc_ok = [r for r in episodes if r.get("family") == fam and r.get("did_accuse") and r.get("correct")]
        fam_acc_bad = [r for r in episodes if r.get("family") == fam and r.get("did_accuse") and not r.get("correct")]
        fam_abs = [r for r in episodes if r.get("family") == fam and not r.get("did_accuse")]
        col = palette.get(fam, (0.3, 0.3, 0.3))
        if fam_acc_ok:
            ax2.scatter(
                [float(r["v_true"]) for r in fam_acc_ok],
                [float(r["p_accused"]) for r in fam_acc_ok],
                color=col,
                marker="o",
                s=34,
                alpha=0.82,
                label=f"{fam}: accused (correct, n={len(fam_acc_ok)})",
            )
        if fam_acc_bad:
            ax2.scatter(
                [float(r["v_true"]) for r in fam_acc_bad],
                [float(r["p_accused"]) for r in fam_acc_bad],
                color=col,
                marker="x",
                s=46,
                linewidths=1.6,
                alpha=0.9,
                label=f"{fam}: accused (wrong, n={len(fam_acc_bad)})",
            )
        if fam_abs:
            ax2.scatter(
                [float(r["v_true"]) for r in fam_abs],
                [float(r["p_top"]) for r in fam_abs],
                edgecolors=col,
                facecolors="none",
                marker="^",
                s=42,
                linewidths=1.3,
                alpha=0.9,
                label=f"{fam}: abstained P(top) (n={len(fam_abs)})",
            )

    for rec in episodes:
        if rec.get("premature_commit") and rec.get("p_accused") is not None:
            vx = float(rec["v_true"])
            py = float(rec["p_accused"])
            ty = float(rec["threshold"])
            ax2.plot([vx, vx], [py, ty], color=(0.75, 0.15, 0.15), linewidth=0.7, alpha=0.45)

    ax2.set_xlim(-0.02, 1.02)
    ax2.set_ylim(-0.03, 1.03)
    ax2.set_xlabel("True company value V_true at decision")
    ax2.set_ylabel("Posterior P(accused == mole) [or P(top) if abstained]")
    ax2.set_title("Commitment vs Rational EV Threshold 1 / (1 + V_true)")
    ax2.grid(True, alpha=0.25)
    ax2.legend(fontsize=6.8, loc="lower left", framealpha=0.9)

    n_ep = int(summary.get("n_episodes") or 0)
    n_prem = int(summary.get("premature_count") or 0)
    ev_lost = float(summary.get("ev_lost_total") or 0.0)
    fig.suptitle(
        f"Canary Accusation Calibration: n={n_ep} episodes, premature commits={n_prem}, EV lost vs abstain={ev_lost:.3f}",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(target, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return target


def _fmt(val: float | None, digits: int = 3, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "NA"
    spec = f"+.{digits}f" if signed else f".{digits}f"
    return format(float(val), spec)


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Bayesian Accusation Calibration and Premature-Commit EV Report",
        "",
        f"Generated `{report['generated_at']}` at git `{str(report['git_sha'])[:12]}` from `{report['runs_dir']}`.",
        "",
        "## Headline Summary",
        "",
        f"- Episodes analyzed: {s['n_episodes']} ({s['n_accused']} accused, {s['n_abstained']} abstained; accuse rate {_fmt(s['accuse_rate'], 3)})",
        f"- Mean posterior P(accused == mole) at accusation: {_fmt(s['mean_p_accused'], 3)}; empirical accuracy when accusing: {_fmt(s['accuracy_when_accused'], 3)}",
        f"- Calibration metrics: Brier score {_fmt(s['brier_score'], 4)}, ECE ({report['n_bins']} bins) {_fmt(s['ece'], 4)}",
        f"- Mean V_true at decision: {_fmt(s['mean_v_true'], 3)}; mean rational EV break-even threshold 1 / (1 + V_true): {_fmt(s['mean_threshold'], 3)}",
        f"- Premature commits (P(accused) < 1 / (1 + V_true)): {s['premature_count']} ({_fmt(s['premature_rate_episodes'], 3)} of episodes, {_fmt(s['premature_rate_accusations'], 3)} of accusations)",
        f"- Expected value lost from accusing below break-even vs abstaining (score 0): {_fmt(s['ev_lost_total'], 3)} total ({_fmt(s['ev_lost_per_episode'], 4)} per episode, {_fmt(s['ev_lost_per_premature'], 3)} per premature commit)",
        f"- Mean realized score: {_fmt(s['mean_score'], 3)}; counterfactual abstain-gated score: {_fmt(s['mean_gated_score'], 3)} (delta {_fmt(s['realized_abstain_gain'], 3, signed=True)})",
        f"- Mean Bayesian EV: {_fmt(s['mean_ev'], 3)}; counterfactual abstain-gated Bayesian EV: {_fmt(s['mean_gated_ev'], 3)}",
        "",
        "## Calibration by Agent and Tier",
        "",
        "| version | family | agent | thinking | tier | n | accused | acc | score | gated score | mean V_true | mean 1/(1+V) | mean P(accused) | premature | EV lost total | EV lost / ep | Brier |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report.get("by_agent_tier") or []:
        think = r.get("thinking_level") or "-"
        lines.append(
            f"| {r['version']} | {r['family']} | {r['agent']} | {think} | {r['tier']} | {r['n_episodes']} | "
            f"{r['n_accused']} | {_fmt(r['accuracy_overall'], 2)} | {_fmt(r['mean_score'], 3)} | "
            f"{_fmt(r['mean_gated_score'], 3)} | {_fmt(r['mean_v_true'], 3)} | {_fmt(r['mean_threshold'], 3)} | "
            f"{_fmt(r['mean_p_accused'], 3)} | {r['premature_count']} | {_fmt(r['ev_lost_total'], 3)} | "
            f"{_fmt(r['ev_lost_per_episode'], 3)} | {_fmt(r['brier_score'], 3)} |"
        )

    lines += [
        "",
        "## Reliability Bins",
        "",
        "| bin | count | mean P(accused) | empirical acc | abs gap | mean 1/(1+V) | mean score | mean EV | premature | EV lost |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for b in report.get("bins") or []:
        rng = f"[{b['lo']:.2f}, {b['hi']:.2f})" if b["bin_index"] < report["n_bins"] - 1 else f"[{b['lo']:.2f}, {b['hi']:.2f}]"
        lines.append(
            f"| {rng} | {b['count']} | {_fmt(b['mean_predicted'], 3)} | {_fmt(b['empirical_accuracy'], 3)} | "
            f"{_fmt(b['calibration_gap'], 3)} | {_fmt(b['mean_threshold'], 3)} | {_fmt(b['mean_score'], 3, signed=True)} | "
            f"{_fmt(b['mean_ev'], 3, signed=True)} | {b['premature_count']} | {_fmt(b['ev_lost_sum'], 3)} |"
        )

    prem = (report.get("premature_examples") or [])[:15]
    if prem:
        lines += [
            "",
            "## Worst Premature Accusations (Below 1 / (1 + V_true))",
            "",
            "| version | agent | tier | seed | day | accused | correct | score | V_true | 1/(1+V) | P(accused) | P(top) | EV(accuse) | EV lost | verdict |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in prem:
            lines.append(
                f"| {r['version']} | {r['agent']} | {r['tier']} | {r['seed']} | {r['decision_day']} | {r['accused']} | "
                f"{r['correct']} | {_fmt(r['score'], 2, signed=True)} | {_fmt(r['v_true'], 3)} | {_fmt(r['threshold'], 3)} | "
                f"{_fmt(r['p_accused'], 3)} | {_fmt(r['p_top'], 3)} | {_fmt(r['ev_accuse'], 3, signed=True)} | "
                f"{_fmt(r['ev_lost'], 3)} | {r['verdict']} |"
            )

    refs = report.get("reference_benchmarks") or []
    if refs:
        lines += [
            "",
            "## Reference Baselines (Context Only)",
            "",
            "| version | agent | tier | n | accused | acc | score | mean 1/(1+V) | mean P(accused) | premature | EV lost total |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in refs:
            lines.append(
                f"| {r['version']} | {r['agent']} | {r['tier']} | {r['n_episodes']} | {r['n_accused']} | "
                f"{_fmt(r['accuracy_overall'], 2)} | {_fmt(r['mean_score'], 3)} | {_fmt(r['mean_threshold'], 3)} | "
                f"{_fmt(r['mean_p_accused'], 3)} | {r['premature_count']} | {_fmt(r['ev_lost_total'], 3)} |"
            )

    lines += ["", "Figure: `calibration_curve.png`. Data: `calibration.json`.", ""]
    return "\n".join(lines)


def run_calibration(
    runs_dir: str | Path = "data/runs/committed",
    out_dir: str | Path = "results/gemini/calibration",
    n_bins: int = 10,
    include_reference: bool = False,
    tier: str | None = None,
    agent_prefix: str = "",
    extra_runs: Iterable[str | Path] = (),
) -> dict[str, Any]:
    roots = [runs_dir, *extra_runs]
    primary_records: list[dict[str, Any]] = []
    reference_records: list[dict[str, Any]] = []

    for root in roots:
        rparts = Path(root).parts
        for ep, rel_parts, dir_meta in _scan_root(root):
            if tier and ep.get("tier") != tier:
                continue
            if agent_prefix and not str(ep.get("agent", "")).startswith(agent_prefix):
                continue
            rec = analyze_episode(ep, rel_parts=rel_parts, dir_meta=dir_meta, root_parts=rparts)
            if rec["family"] == "reference" and not include_reference:
                reference_records.append(rec)
            else:
                primary_records.append(rec)

    report = build_report(
        primary_records,
        n_bins=n_bins,
        runs_dir=str(runs_dir),
        reference_records=reference_records,
    )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    png_path = plot_calibration(report, out_path / "calibration_curve.png")
    report["figure"] = png_path.name
    (out_path / "calibration.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_path / "calibration.md").write_text(render_markdown(report))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m canary.gemini.calibration",
        description="Bayesian accusation calibration and premature-commit EV analyzer.",
    )
    ap.add_argument("--runs-dir", "--runs", dest="runs_dir", default="data/runs/committed")
    ap.add_argument("--extra-runs", action="append", default=[])
    ap.add_argument("--out", default="results/gemini/calibration")
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--tier", default=None)
    ap.add_argument("--agent-prefix", default="")
    ap.add_argument("--include-reference", action="store_true")
    args = ap.parse_args(argv)

    report = run_calibration(
        runs_dir=args.runs_dir,
        out_dir=args.out,
        n_bins=args.bins,
        include_reference=args.include_reference,
        tier=args.tier,
        agent_prefix=args.agent_prefix,
        extra_runs=args.extra_runs,
    )
    s = report["summary"]
    print(
        f"wrote calibration report to {args.out}: "
        f"episodes={s['n_episodes']} accused={s['n_accused']} "
        f"premature={s['premature_count']} ev_lost={s['ev_lost_total']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
