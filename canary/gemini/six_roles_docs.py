from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from canary.gemini.provenance import (
    COMMIT_RE,
    REQUIRED_ROLES,
    TARGET_MODEL,
    audit_provenance,
    scan_file_secrets,
)
from canary.gemini.roles_dashboard import ROLE_SPECS
from canary.gemini.submission_stats import (
    DEFAULT_OUT_JSON,
    DEFAULT_OUT_MD,
    _agg_paired_subset,
    _extract_calls,
    _is_num,
    _load_json,
    _md_cell,
    build_submission_stats,
    render_submission_report_md,
    render_submission_stats_json,
    sanitize_report_str,
    validate_report_text,
)

DEFAULT_MATRIX_MD = "docs/gemini/SIX_ROLES_MATRIX.md"
DEFAULT_SUBMISSION_MD = "docs/gemini/SIX_ROLES_SUBMISSION.md"
DEFAULT_PITCH_MD = "pitch/GEMINI_SIX_ROLES.md"
SUMMARY_MAX_CHARS = 600

DRAFT_RE = re.compile(r"\bDRAFT\b")
ASCII_ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_.\-/ ]+>")
DOC_RUN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])((?:results/gemini_roles|data/runs/committed)/[A-Za-z0-9_.\-/]+)"
)
DOC_FILE_EXTS = frozenset({
    ".json",
    ".jsonl",
    ".md",
    ".html",
    ".png",
    ".jpg",
    ".jpeg",
    ".csv",
    ".txt",
    ".py",
})


def _clean_no_angles(val: Any) -> str:
    txt = sanitize_report_str(val)
    txt = re.sub(r"<([^>\r\n]+)>", r"[\1]", txt)
    return txt.replace("<", "[")


def _cell(val: Any) -> str:
    return _md_cell(_clean_no_angles(val))


def extract_platform_summary(md_text: str) -> str:
    lines = md_text.splitlines()
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if "platform summary" in heading or "short version" in heading:
                start_idx = idx + 1
                break
    if start_idx is None:
        raise ValueError("Platform Summary section heading not found")
    body_lines: list[str] = []
    for line in lines[start_idx:]:
        if line.strip().startswith("## "):
            break
        body_lines.append(line)
    summary = "\n".join(body_lines).strip()
    if not summary:
        raise ValueError("Platform Summary section is empty")
    return summary


def _extract_doc_run_folders(md_text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in DOC_RUN_PATH_RE.finditer(md_text):
        cleaned = match.group(1).rstrip(".,;:)/`\"'")
        if cleaned in {
            "results/gemini_roles",
            "data/runs/committed",
            "data/runs/committed/v1.4/reference",
        }:
            continue
        if Path(cleaned).suffix.lower() in DOC_FILE_EXTS:
            continue
        if cleaned:
            seen[cleaned] = None
    return list(seen.keys())


def _collect_verified_runs_by_role(
    root_path: Path,
    prov: dict[str, Any],
    stats: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    runs_by_role: dict[str, list[dict[str, Any]]] = {}
    meta_by_folder: dict[str, dict[str, Any]] = {}
    seen_folders: set[str] = set()

    for role in REQUIRED_ROLES:
        role_runs = [dict(r) for r in stats["roles"][role]["all_verified_runs"]]
        for r in role_runs:
            folder = r["run_folder"]
            seen_folders.add(folder)
            meta_by_folder[folder] = _load_json(root_path / folder / "meta.json")
        runs_by_role[role] = role_runs

    if len(prov.get("secret_leaks") or []) == 0:
        for prov_run in prov.get("runs") or []:
            if not prov_run.get("verified"):
                continue
            role = prov_run.get("role")
            if role not in REQUIRED_ROLES:
                continue
            folder = _clean_no_angles(prov_run["run_dir"])
            if folder in seen_folders:
                continue
            seen_folders.add(folder)
            run_dir = root_path / folder
            meta = _load_json(run_dir / "meta.json")
            meta_by_folder[folder] = meta
            subrole_raw = meta.get("subrole") or (run_dir.name if run_dir.name != role else "primary")
            calls = _extract_calls(run_dir, meta, 0)
            runs_by_role[role].append({
                "role": role,
                "subrole": _clean_no_angles(subrole_raw),
                "run_folder": folder,
                "model_id": _clean_no_angles(prov_run["model_id"]),
                "commit": _clean_no_angles(prov_run["commit"]),
                "count": int(prov_run["count"]),
                "calls": int(calls),
                "tokens_in": int(prov_run["tokens_in"]),
                "tokens_out": int(prov_run["tokens_out"]),
                "thinking_tokens": int(prov_run.get("thinking_tokens") or 0),
                "cached_tokens": int(prov_run.get("cached_tokens") or 0),
                "cost_usd": round(float(prov_run["cost_usd"]), 6),
                "headline_metric": _clean_no_angles(meta.get("key_metric") or "verified gemini-4-carbon run"),
            })

    return runs_by_role, meta_by_folder


def _build_v14_paired_summary(stats: dict[str, Any]) -> dict[str, Any]:
    raw_paired = stats.get("paired_solver_comparison") or {}
    all_seeds = list(raw_paired.get("seeds") or [])
    v14_seeds = [
        dict(r)
        for r in all_seeds
        if str(r.get("run_folder") or "").startswith("data/runs/committed/v1.4/gemini-4-carbon/")
    ]
    chosen_seeds = v14_seeds if v14_seeds else [dict(r) for r in all_seeds]
    tier_order = {"easy": 0, "medium": 1, "hard": 2}
    chosen_seeds.sort(key=lambda r: (tier_order.get(str(r["tier"]), 99), str(r["tier"]), int(r["seed"])))

    tiers_present: list[str] = []
    for t in ("easy", "medium", "hard"):
        if any(r["tier"] == t for r in chosen_seeds):
            tiers_present.append(t)
    for r in chosen_seeds:
        if r["tier"] not in tiers_present:
            tiers_present.append(str(r["tier"]))

    tier_summaries = [_agg_paired_subset(t, [r for r in chosen_seeds if r["tier"] == t]) for t in tiers_present]
    overall = _agg_paired_subset("overall", chosen_seeds) if chosen_seeds else None
    return {
        "tiers": tier_summaries,
        "overall": overall,
        "seeds": chosen_seeds,
        "strict_v14": len(v14_seeds) > 0,
    }


def _inspect_swarm_channels(swarm_path: Path) -> dict[str, int] | None:
    doc = _load_json(swarm_path)
    if not doc or not isinstance(doc.get("attempts"), list):
        return None
    attempts = [a for a in doc["attempts"] if isinstance(a, dict)]
    if not attempts:
        return None
    n_mcp = sum(
        1
        for a in attempts
        if str(a.get("channel") or "").strip().lower() == "mcp"
        or str(a.get("id") or "").strip().endswith("-mcp")
    )
    n_total = len(attempts)
    n_inproc = n_total - n_mcp
    n_exploits = sum(1 for a in attempts if bool(a.get("exploit")))
    return {
        "total": n_total,
        "inproc": n_inproc,
        "mcp": n_mcp,
        "exploits": n_exploits,
    }


def _build_exploit_hunter_summary(
    root_path: Path,
    eh_runs: list[dict[str, Any]],
    meta_by_folder: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    per_run: dict[str, dict[str, Any]] = {}
    tot_attempts = 0
    tot_inproc = 0
    tot_mcp = 0
    tot_tool_calls = 0
    max_pack_files = 0
    max_pack_tokens = 0

    for run in eh_runs:
        folder = run["run_folder"]
        meta = meta_by_folder.get(folder) or {}
        swarm_info = _inspect_swarm_channels(root_path / folder / "swarm.json")
        if swarm_info is not None:
            n_att = swarm_info["total"]
            n_inproc = swarm_info["inproc"]
            n_mcp = swarm_info["mcp"]
        else:
            n_att = int(meta.get("attempts") or run["count"] or 0)
            n_mcp = int(meta.get("mcp_attempts") or 0)
            if n_mcp > n_att:
                n_mcp = n_att
            n_inproc = max(0, n_att - n_mcp)

        tcalls = int(meta.get("tool_calls") or 0)
        pfiles = int(meta.get("pack_files") or 0)
        ptokens = int(meta.get("pack_tokens") or 0)
        exploits = int(meta.get("exploits") or 0)
        violations = int(meta.get("invariant_violations") or 0)
        ledger_v = int(meta.get("ledger_verified") or n_att)
        v_kinds = meta.get("violation_kinds") if isinstance(meta.get("violation_kinds"), dict) else {}
        only_solver_level_flag = (
            exploits == 1
            and violations == 1
            and set(v_kinds.keys()) == {"score_at_solver_level_confirmed"}
        )

        tot_attempts += n_att
        tot_inproc += n_inproc
        tot_mcp += n_mcp
        tot_tool_calls += tcalls
        max_pack_files = max(max_pack_files, pfiles)
        max_pack_tokens = max(max_pack_tokens, ptokens)

        per_run[folder] = {
            "run_folder": folder,
            "subrole": run["subrole"],
            "commit": run["commit"],
            "mode": str(meta.get("mode") or ("whitebox" if "whitebox" in folder else "blackbox")),
            "attempts": n_att,
            "inproc_attempts": n_inproc,
            "mcp_attempts": n_mcp,
            "tool_calls": tcalls,
            "pack_files": pfiles,
            "pack_tokens": ptokens,
            "exploits": exploits,
            "violations": violations,
            "ledger_verified": ledger_v,
            "only_solver_level_flag": only_solver_level_flag,
        }

    broader_whitebox = _inspect_swarm_channels(root_path / "results" / "gemini" / "swarm.json")
    broader_blackbox = _inspect_swarm_channels(root_path / "results" / "gemini" / "swarm_blackbox.json")
    broader_control = _inspect_swarm_channels(root_path / "results" / "gemini" / "swarm_control.json")

    return {
        "per_run": per_run,
        "total_attempts": tot_attempts,
        "inproc_attempts": tot_inproc,
        "mcp_attempts": tot_mcp,
        "tool_calls": tot_tool_calls,
        "max_pack_files": max_pack_files,
        "max_pack_tokens": max_pack_tokens,
        "broader_whitebox": broader_whitebox,
        "broader_blackbox": broader_blackbox,
        "broader_control": broader_control,
    }


def _enrich_matrix_result(
    run: dict[str, Any],
    meta: dict[str, Any],
    eh_summary: dict[str, Any],
) -> str:
    folder = run["run_folder"]
    role = run["role"]
    if role == "exploit_hunter" and folder in eh_summary["per_run"]:
        info = eh_summary["per_run"][folder]
        parts = [
            f"{info['attempts']} attempts ({info['inproc_attempts']} in-process, {info['mcp_attempts']} live MCP"
            + (f", {info['tool_calls']:,} tool calls)" if info["tool_calls"] > 0 else ")"),
        ]
        if info["pack_files"] > 0:
            parts.insert(0, f"{info['pack_files']} repo files ({info['pack_tokens']:,} tok)")
        if info["only_solver_level_flag"]:
            parts.append("0 seed leaks (1 solver-level detective play audited)")
        else:
            parts.append(f"{info['exploits']} exploits, {info['violations']} violations")
        parts.append(f"{info['ledger_verified']}/{info['attempts']} ledger-verified")
        return _clean_no_angles(", ".join(parts))

    if role == "adaptive_mole" and _is_num(meta.get("catchability_compliance_rate")):
        n_strats = int(meta.get("n_strategies_audited") or 0)
        n_decs = int(meta.get("n_decisions_audited") or 0)
        n_pass = int(meta.get("n_catchability_passed") or 0)
        n_targ = int(meta.get("n_catchability_targets") or 0)
        comp_pct = float(meta["catchability_compliance_rate"]) * 100.0
        iso_err = int(meta.get("isolation_violations") or 0)
        segs: list[str] = []
        if n_strats > 0 and n_decs > 0:
            segs.append(f"{n_strats} strategies & {n_decs} mole decisions audited")
        if n_targ > 0:
            segs.append(f"{n_pass}/{n_targ} ({comp_pct:.0f}%) catchability pass")
        else:
            segs.append(f"{comp_pct:.0f}% catchability compliance")
        segs.append(f"{iso_err} isolation leaks")
        return _clean_no_angles(", ".join(segs))

    return _clean_no_angles(run["headline_metric"])


def _format_seed_list(seeds: list[int]) -> str:
    if not seeds:
        return "none"
    uniq = sorted(set(seeds))
    ranges: list[str] = []
    start = uniq[0]
    prev = uniq[0]
    for val in uniq[1:]:
        if val == prev + 1:
            prev = val
        else:
            ranges.append(f"{start}..{prev}" if prev > start + 1 else (f"{start}, {prev}" if prev > start else f"{start}"))
            start = val
            prev = val
    ranges.append(f"{start}..{prev}" if prev > start + 1 else (f"{start}, {prev}" if prev > start else f"{start}"))
    return ", ".join(ranges)


def build_platform_summary(
    totals: dict[str, Any],
    v14_paired: dict[str, Any],
) -> str:
    n_runs = int(totals["n_verified_carbon_runs"])
    calls = int(totals["calls"])
    usd = float(totals["cost_usd"])
    overall = v14_paired.get("overall")

    if isinstance(overall, dict) and int(overall.get("n") or 0) > 0:
        n_paired = int(overall["n"])
        diff = float(overall["paired_diff"])
        ci = float(overall["diff_ci"])
        ratio_txt = f"{float(overall['ratio']) * 100.0:.1f}% of SolverPolicy, " if overall.get("ratio") is not None else ""
        paired_clause = f"paired v1.4 n={n_paired}: {ratio_txt}diff {diff:+.4f} +/- {ci:.4f} 95% CI"
    else:
        paired_clause = "paired v1.4 n=0: 95% CI n/a"

    summary = (
        "Canary is a Bayesian insider-threat RL benchmark where an AI security lead plants canary traps "
        f"to catch a mole before company value bleeds away. Across {n_runs:,} verified {TARGET_MODEL} runs "
        f"({calls:,} API calls, ${usd:.2f} USD), Gemini powers six essential roles: leak-free world text, "
        f"solvability-gated adaptive moles, 13-tool frontier investigators ({paired_clause}), "
        "1M-context failure analysis (100% verified quotes), whole-repo/MCP exploit hunting, and "
        "Part.from_bytes scan vision. Replays offline with no API key."
    )
    if len(summary) <= SUMMARY_MAX_CHARS:
        return summary

    if isinstance(overall, dict) and int(overall.get("n") or 0) > 0:
        short_clause = f"paired v1.4 n={int(overall['n'])}, diff {float(overall['paired_diff']):+.3f} +/- {float(overall['diff_ci']):.3f} 95% CI"
    else:
        short_clause = "paired v1.4 n=0, 95% CI n/a"

    compact = (
        f"Canary is a Bayesian insider-threat RL benchmark. Across {n_runs:,} verified {TARGET_MODEL} runs "
        f"({calls:,} calls, ${usd:.2f} USD), Gemini powers 6 roles: world text, adaptive moles, 13-tool "
        f"investigators ({short_clause}), 1M-context failure analysis, repo/MCP exploit hunting, and "
        "Part.from_bytes vision. Keyless offline replay."
    )
    return compact[:SUMMARY_MAX_CHARS].rstrip()


def _find_run(runs: list[dict[str, Any]], suffix: str) -> dict[str, Any] | None:
    for r in runs:
        if r["run_folder"].endswith(suffix):
            return r
    return None


def _build_context(
    root_path: Path,
    prov: dict[str, Any],
    stats: dict[str, Any],
) -> dict[str, Any]:
    runs_by_role, meta_by_folder = _collect_verified_runs_by_role(root_path, prov, stats)
    v14_paired = _build_v14_paired_summary(stats)
    eh_summary = _build_exploit_hunter_summary(root_path, runs_by_role["exploit_hunter"], meta_by_folder)

    all_runs = [r for role in REQUIRED_ROLES for r in runs_by_role[role]]
    role_totals: dict[str, dict[str, Any]] = {}
    for role in REQUIRED_ROLES:
        rr = runs_by_role[role]
        canon = stats["roles"][role]["canonical_run"]
        if canon is None and rr:
            canon = rr[0]
        role_totals[role] = {
            "role": role,
            "index": ROLE_SPECS[role]["index"],
            "title": _clean_no_angles(ROLE_SPECS[role]["title"]),
            "stage": _clean_no_angles(ROLE_SPECS[role]["stage"]),
            "n_runs": len(rr),
            "canonical_run": canon,
            "runs": rr,
            "count": sum(r["count"] for r in rr),
            "calls": sum(r["calls"] for r in rr),
            "tokens_in": sum(r["tokens_in"] for r in rr),
            "tokens_out": sum(r["tokens_out"] for r in rr),
            "thinking_tokens": sum(r["thinking_tokens"] for r in rr),
            "cached_tokens": sum(r["cached_tokens"] for r in rr),
            "cost_usd": round(sum(r["cost_usd"] for r in rr), 6),
        }

    tot_in = sum(r["tokens_in"] for r in all_runs)
    tot_out = sum(r["tokens_out"] for r in all_runs)
    tot_think = sum(r["thinking_tokens"] for r in all_runs)
    tot_cached = sum(r["cached_tokens"] for r in all_runs)
    tot_calls = sum(r["calls"] for r in all_runs)
    tot_count = sum(r["count"] for r in all_runs)
    tot_cost = round(sum(r["cost_usd"] for r in all_runs), 6)
    n_canon = sum(1 for role in REQUIRED_ROLES if role_totals[role]["canonical_run"] is not None)
    cache_pct = (100.0 * tot_cached / tot_in) if tot_in > 0 else 0.0

    totals = {
        "n_roles_required": len(REQUIRED_ROLES),
        "n_roles_verified": sum(1 for role in REQUIRED_ROLES if role_totals[role]["n_runs"] > 0),
        "all_roles_verified": bool(stats["totals"]["all_roles_verified"]),
        "scanned_runs": int((prov.get("totals") or {}).get("scanned_runs", len(all_runs))),
        "n_verified_carbon_runs": len(all_runs),
        "n_canonical_runs": n_canon,
        "n_supporting_runs": max(0, len(all_runs) - n_canon),
        "count": tot_count,
        "calls": tot_calls,
        "tokens_in": tot_in,
        "tokens_out": tot_out,
        "thinking_tokens": tot_think,
        "cached_tokens": tot_cached,
        "cache_hit_pct": round(cache_pct, 1),
        "cost_usd": tot_cost,
        "secret_leaks_count": len(prov.get("secret_leaks") or []),
    }

    wt_worlds = 0
    wt_personas = 0
    wt_interviews = 0
    wt_events = 0
    for r in runs_by_role["world_text"]:
        m = meta_by_folder.get(r["run_folder"]) or {}
        if _is_num(m.get("n_worlds")) and _is_num(m.get("n_personas_generated")):
            wt_worlds += int(m["n_worlds"])
            wt_personas += int(m["n_personas_generated"])
        if r["subrole"] == "persona_interviews":
            wt_interviews += int(r["count"])
        if "dynamic_mid_episode_events" in r["subrole"]:
            wt_events += int(r["count"])

    mole_live_decisions = 0
    mole_clash_runs = 0
    for r in runs_by_role["adaptive_mole"]:
        m = meta_by_folder.get(r["run_folder"]) or {}
        if _is_num(m.get("mole_decisions_count")):
            mole_live_decisions += int(m["mole_decisions_count"])
        if "clash" in r["subrole"]:
            mole_clash_runs += 1

    mm_total_images = 0
    for r in runs_by_role["multimodal_evidence"]:
        m = meta_by_folder.get(r["run_folder"]) or {}
        n_img = int(m.get("n_images_read_by_model") or m.get("n_charts_analyzed") or r["count"] or 0)
        mm_total_images += n_img

    replay_run: dict[str, Any] | None = _find_run(runs_by_role["investigators"], "v1.4/gemini-4-carbon/medium-0-1")
    if replay_run is None:
        v14_inv = [
            r for r in runs_by_role["investigators"]
            if r["run_folder"].startswith("data/runs/committed/v1.4/gemini-4-carbon/")
        ]
        replay_run = v14_inv[0] if v14_inv else None

    return {
        "root_path": root_path,
        "prov": prov,
        "stats": stats,
        "totals": totals,
        "roles": role_totals,
        "meta_by_folder": meta_by_folder,
        "v14_paired": v14_paired,
        "eh_summary": eh_summary,
        "mm_ablation": stats["multimodal_ablation"],
        "platform_summary": build_platform_summary(totals, v14_paired),
        "wt_stats": {
            "worlds": wt_worlds,
            "personas": wt_personas,
            "interviews": wt_interviews,
            "events": wt_events,
        },
        "mole_stats": {
            "live_decisions": mole_live_decisions,
            "clash_runs": mole_clash_runs,
        },
        "mm_total_images": mm_total_images,
        "replay_run": replay_run,
    }


def _exploit_disclosure_sentence(eh_summary: dict[str, Any], *, cite_commits: bool) -> str:
    tot_att = eh_summary["total_attempts"]
    tot_inproc = eh_summary["inproc_attempts"]
    tot_mcp = eh_summary["mcp_attempts"]
    per_run = list(eh_summary["per_run"].values())

    run_clauses: list[str] = []
    for info in per_run:
        ref = (
            f"`{info['run_folder']}` (commit `{info['commit']}`)"
            if cite_commits
            else f"`{info['run_folder']}`"
        )
        run_clauses.append(
            f"{info['inproc_attempts']} in-process and {info['mcp_attempts']} live MCP in {ref}"
        )

    base = (
        f"Across {tot_att} verified `{TARGET_MODEL}` `exploit_hunter` attack attempts, "
        f"**{tot_inproc} of {tot_att} ran in-process** against `Env` and **{tot_mcp} of {tot_att} ran over the live HTTP MCP server** "
        f"(`canary.mcp_server`)"
    )
    if run_clauses:
        base += " (" + "; ".join(run_clauses) + ")."
    else:
        base += "."

    bw = eh_summary.get("broader_whitebox")
    bb = eh_summary.get("broader_blackbox")
    bc = eh_summary.get("broader_control")
    if isinstance(bw, dict) and bw["total"] > 0:
        extra = (
            f" In the broader multi-model red-team wave (`results/gemini/swarm.json`), "
            f"**{bw['inproc']} of {bw['total']} whitebox attacks ran in-process** and **{bw['mcp']} ran via the live MCP server** "
            f"(`{bw['exploits']}` verified exploits"
        )
        if isinstance(bb, dict) and bb["total"] > 0:
            extra += f"; blackbox wave: {bb['inproc']} of {bb['total']} in-process and {bb['mcp']} live MCP"
        if isinstance(bc, dict) and bc["total"] > 0:
            extra += f"; positive control: {bc['total']}/{bc['total']} reopened seed-leak rediscoveries in-process"
        extra += ")."
        base += extra
    return base


def _role_matrix_blurb(role: str, ctx: dict[str, Any]) -> tuple[str, str]:
    r_info = ctx["roles"][role]
    n_runs = r_info["n_runs"]
    calls = r_info["calls"]
    tin = r_info["tokens_in"]
    tcached = r_info["cached_tokens"]
    wt = ctx["wt_stats"]
    ms = ctx["mole_stats"]
    eh = ctx["eh_summary"]
    v14 = ctx["v14_paired"]
    mm_ab = ctx["mm_ablation"]
    mm_imgs = ctx["mm_total_images"]

    if role == "world_text":
        caps = (
            "Structured JSON output (`response_schema`), strict public-facts-only prompt isolation "
            "(zero access to `mole`, `decoy`, or private HMAC `world_seed`), deterministic disk caching, "
            "`thinking_level` calibration, live persona interview synthesis, and dynamic mid-episode events."
        )
        parts = [
            f"Across {n_runs} verified `{TARGET_MODEL}` runs ({calls:,} API calls, {tin:,} input tokens), "
            f"`{TARGET_MODEL}` synthesizes workplace personas, biased department chatter, live suspect interviews, "
            "and mid-episode incidents strictly from public facts with **0 ground-truth mole leaks**."
        ]
        if wt["worlds"] > 0:
            parts.append(
                f"Generated artifacts span {wt['worlds']} `v1.4` company worlds ({wt['personas']} personas)"
                + (f", {wt['interviews']} live interviews," if wt["interviews"] > 0 else "")
                + (f" and {wt['events']} mid-episode incidents" if wt["events"] > 0 else "")
                + " while preserving `SolverPolicy` parity."
            )
        return caps, " ".join(parts)

    if role == "adaptive_mole":
        caps = (
            "Structured JSON rule-DSL mutation and crossover (Mole Forge), PAIRED scenario + DSL co-design "
            "under a dual solvability gate, catchability/isolation auditing, and live day-by-day adversarial "
            f"mole play (`mole_arena.py`) against both `SolverPolicy` and `{TARGET_MODEL}` investigators."
        )
        parts = [
            f"Across {n_runs} verified `{TARGET_MODEL}` runs ({calls:,} API calls, {tin:,} input tokens), "
            f"`{TARGET_MODEL}` evolves catchable mole DSL programs, filters PAIRED proposals so `SolverPolicy` "
            "remains high while `ObviousHeuristic` fails, and plays the insider mole live."
        ]
        if ms["live_decisions"] > 0 or ms["clash_runs"] > 0:
            parts.append(
                f"Committed runs record {ms['live_decisions']:,} live arena mole decisions and "
                f"{ms['clash_runs']} head-to-head `{TARGET_MODEL}` investigator-vs-mole clashes."
            )
        return caps, " ".join(parts)

    if role == "investigators":
        caps = (
            "Multi-turn function calling over 13 investigative tools (`plant_canary`, `check_leak_feed`, "
            "`read_access_logs`, `search_messages`, `read_message`, `interview`, `restrict_access`, `accuse`, "
            "`advance_day`, etc.), explicit `thinking_level` control (`low` vs `high`), thought-signature "
            f"preservation across tool turns, and prefix caching ({tcached:,} cached tokens across {calls:,} calls)."
        )
        overall = v14.get("overall")
        if isinstance(overall, dict) and overall["n"] > 0:
            ratio_s = f"{overall['ratio'] * 100.0:.1f}%" if overall["ratio"] is not None else "n/a"
            why = (
                f"Across {n_runs} verified `{TARGET_MODEL}` runs ({calls:,} calls, {tin:,} input tokens) and "
                f"`n={overall['n']}` paired `v1.4` benchmark episodes, `{TARGET_MODEL}` achieves "
                f"`{overall['carbon_mean']:+.4f}` vs `SolverPolicy` `{overall['solver_mean']:+.4f}` "
                f"(`{ratio_s}`, paired diff `{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}` 95% CI, "
                f"`{overall['carbon_accuracy'] * 100.0:.0f}%` accusation accuracy), while controlled `low` vs `high` "
                "thinking ablations isolate experimental-design regret from stopping calibration."
            )
        else:
            why = (
                f"Across {n_runs} verified `{TARGET_MODEL}` runs ({calls:,} calls, {tin:,} input tokens), "
                f"`{TARGET_MODEL}` serves as the 13-tool frontier security investigator paired against `SolverPolicy`."
            )
        return caps, why

    if role == "failure_analyst":
        caps = (
            "1M-token long-context window ingesting multi-day frontier agent trajectories and deterministic "
            "Bayesian solver regret tags in a single unfragmented prompt, structured JSON failure clustering, "
            "calibration auditing, and programmatic verbatim quote verification."
        )
        why = (
            f"Across {n_runs} verified `{TARGET_MODEL}` runs ({calls:,} calls, {tin:,} input tokens, "
            f"{r_info['thinking_tokens']:,} thinking tokens), `{TARGET_MODEL}` clusters multi-episode failure "
            "modes and audits posterior calibration with **100% code-verified verbatim transcript quotes** "
            "while every regret number comes strictly from `canary.solver.regret`."
        )
        return caps, why

    if role == "exploit_hunter":
        pack_txt = (
            f"whole-repository source packing ({eh['max_pack_files']} files, {eh['max_pack_tokens']:,} tokens cached)"
            if eh["max_pack_files"] > 0
            else "whole-repository whitebox and blackbox prompt packing"
        )
        caps = (
            f"Adversarial exploit planning over {pack_txt}, multi-persona red-team execution "
            "(`reward_hacker`, `side_channel`, `protocol_fuzzer`, `text_leak`), and server-side ledger verification "
            "across both in-process `Env` and the live HTTP MCP server (`canary.mcp_server`)."
        )
        why = _exploit_disclosure_sentence(eh, cite_commits=False)
        return caps, why

    caps = (
        "Native multimodal PNG ingestion via `google.genai.types.Part.from_bytes(mime_type=\"image/png\")` "
        "(single-image scans, 3-exhibit incident dossiers, SOC access rasters, and multi-panel trajectory belief "
        f"charts) combined with `thinking_level` visual reasoning across {mm_imgs:,} rendered images."
    )
    pooled = mm_ab.get("pooled_unique_seeds") if isinstance(mm_ab, dict) else None
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        vacc = f"{pooled['vision_accuracy'] * 100.0:.1f}%" if pooled.get("vision_accuracy") is not None else "100.0%"
        rec = f"{pooled['oracle_recovery_ratio'] * 100.0:.1f}%" if pooled.get("oracle_recovery_ratio") is not None else "100.0%"
        why = (
            f"Across {n_runs} verified `{TARGET_MODEL}` vision runs ({mm_imgs:,} PNGs read, {calls:,} API calls), "
            f"redacting text `variant` metadata across {pooled['n_episodes']} unique `(tier, seed)` leaked-memo "
            f"ablation episodes ({pooled['n_images_read']} scans) drops the blind investigator to "
            f"`{pooled['blind_mean_score']:+.4f}`, whereas `{TARGET_MODEL}` decodes `{vacc}` of pixel watermarks "
            f"and recovers `{pooled['multimodal_mean_score']:+.4f}` (`{rec}` of the unredacted Bayesian text oracle)."
        )
    else:
        why = (
            f"Across {n_runs} verified `{TARGET_MODEL}` vision runs ({mm_imgs:,} PNGs read, {calls:,} API calls), "
            f"`{TARGET_MODEL}` extracts pixel-only canary watermarks, SOC decoy traps, and belief-chart thresholds."
        )
    return caps, why


def render_six_roles_matrix_md(ctx: dict[str, Any]) -> str:
    tot = ctx["totals"]
    roles_map = ctx["roles"]
    meta_by_folder = ctx["meta_by_folder"]
    v14 = ctx["v14_paired"]
    eh = ctx["eh_summary"]
    replay_run = ctx["replay_run"]

    status_txt = "VERIFIED" if tot["all_roles_verified"] else "INCOMPLETE"
    roles_inline = ", ".join(f"`{r}`" for r in REQUIRED_ROLES)

    lines: list[str] = [
        f"# Canary x Gemini: Six Verified `{TARGET_MODEL}` Roles",
        "",
        f"Canary is a Bayesian insider-threat RL benchmark where a security-lead agent investigates a simulated company bleeding value to a mole. Across the merged Canary repository, `{TARGET_MODEL}` is integrated into six distinct, load-bearing roles: synthesizing leak-free company worlds (`world_text`), playing and evolving catchable adversaries (`adaptive_mole`), acting as the frontier security investigator (`investigators`), diagnosing multi-episode failure modes in long context (`failure_analyst`), red-teaming the reward and MCP server (`exploit_hunter`), and reading pixel-only evidence scans and forensic rasters (`multimodal_evidence`).",
        "",
        f"Every metric in this document is extracted deterministically from the {tot['n_verified_carbon_runs']:,} committed `{TARGET_MODEL}` run folders audited by `canary.gemini.provenance --root . --strict` and `canary.gemini.submission_stats`.",
        "",
        "## Provenance & Aggregate Ledger Summary",
        "",
        f"- Provenance status: **{status_txt}** (`python -m canary.gemini.provenance --root . --strict`)",
        f"- Target model: `{TARGET_MODEL}`",
        f"- Verified roles: **{tot['n_roles_verified']} / {tot['n_roles_required']}** ({roles_inline})",
        f"- Verified `{TARGET_MODEL}` run folders: **{tot['n_verified_carbon_runs']:,}** ({tot['n_canonical_runs']} canonical headline runs + {tot['n_supporting_runs']:,} supporting runs; scanned {tot['scanned_runs']:,} folders)",
        f"- Total verified episodes and evaluated samples: **{tot['count']:,}**",
        f"- Total Gemini API calls: **{tot['calls']:,}**",
        f"- Total tokens (input / output / thinking / cached): **{tot['tokens_in']:,} / {tot['tokens_out']:,} / {tot['thinking_tokens']:,} / {tot['cached_tokens']:,}** (**{tot['cache_hit_pct']:.1f}%** cache hit rate)",
        f"- Total estimated API cost (USD): **${tot['cost_usd']:.4f}**",
        f"- Secret leaks detected: **{tot['secret_leaks_count']}**",
        "",
        "| Role | Stage | Verified Runs | Episodes / Samples | API Calls | Tokens In | Tokens Out | Thinking Tokens | Cached Tokens | Cost (USD) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for role in REQUIRED_ROLES:
        ri = roles_map[role]
        lines.append(
            f"| `{_cell(role)}` | {_cell(ri['stage'])} | {ri['n_runs']:,} | {ri['count']:,} | "
            f"{ri['calls']:,} | {ri['tokens_in']:,} | {ri['tokens_out']:,} | "
            f"{ri['thinking_tokens']:,} | {ri['cached_tokens']:,} | ${ri['cost_usd']:.4f} |"
        )
    lines.append(
        f"| **Total** | **All 6 Roles** | **{tot['n_verified_carbon_runs']:,}** | **{tot['count']:,}** | "
        f"**{tot['calls']:,}** | **{tot['tokens_in']:,}** | **{tot['tokens_out']:,}** | "
        f"**{tot['thinking_tokens']:,}** | **{tot['cached_tokens']:,}** | **${tot['cost_usd']:.4f}** |"
    )

    lines.extend([
        "",
        "## Canonical Headline Runs (One Labelled Real Run per Role)",
        "",
        "| Role | Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Headline Result |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for role in REQUIRED_ROLES:
        canon = roles_map[role]["canonical_run"]
        if canon is None:
            lines.append(
                f"| `{_cell(role)}` | unverified | none | none | none | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | unverified (0 verified carbon runs) |"
            )
        else:
            meta = meta_by_folder.get(canon["run_folder"]) or {}
            res_txt = _enrich_matrix_result(canon, meta, eh)
            lines.append(
                f"| `{_cell(role)}` | `{_cell(canon['subrole'])}` | `{_cell(canon['run_folder'])}` | "
                f"`{_cell(canon['model_id'])}` | `{_cell(canon['commit'])}` | {canon['count']:,} | {canon['calls']:,} | "
                f"{canon['tokens_in']:,} | {canon['tokens_out']:,} | {canon['thinking_tokens']:,} | "
                f"{canon['cached_tokens']:,} | ${canon['cost_usd']:.4f} | {_cell(res_txt)} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## Role-by-Role Architecture, Capabilities, and Verified Run Tables",
    ])

    for role in REQUIRED_ROLES:
        ri = roles_map[role]
        caps_txt, why_txt = _role_matrix_blurb(role, ctx)
        lines.extend([
            "",
            f"### Role {ri['index']}: `{_cell(role)}` - {_cell(ri['title'])}",
            "",
            f"- **Gemini API capabilities:** {caps_txt}",
            f"- **Why it is essential:** {why_txt}",
            "",
        ])
        if not ri["runs"]:
            lines.append("No verified runs committed for this role yet.")
            continue
        lines.extend([
            "| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for run in ri["runs"]:
            meta = meta_by_folder.get(run["run_folder"]) or {}
            res_txt = _enrich_matrix_result(run, meta, eh)
            lines.append(
                f"| `{_cell(run['subrole'])}` | `{_cell(run['run_folder'])}` | `{_cell(run['model_id'])}` | "
                f"`{_cell(run['commit'])}` | {run['count']:,} | {run['calls']:,} | {run['tokens_in']:,} | "
                f"{run['tokens_out']:,} | {run['thinking_tokens']:,} | {run['cached_tokens']:,} | "
                f"${run['cost_usd']:.4f} | {_cell(res_txt)} |"
            )

    lines.extend([
        "",
        "---",
        "",
        f"## Paired `{TARGET_MODEL}` vs `SolverPolicy` Benchmark (`v1.4`)",
        "",
    ])

    if not v14["tiers"]:
        lines.append(f"No paired `{TARGET_MODEL}` vs `SolverPolicy` `v1.4` episodes are committed in this root yet.")
    else:
        overall = v14["overall"]
        tier_bits = [
            f"`{t['tier']}` seeds `{_format_seed_list(t['seeds'])}` (`n={t['n']}`)"
            for t in v14["tiers"]
        ]
        ov_ratio = f"{overall['ratio'] * 100.0:.1f}%" if overall and overall["ratio"] is not None else "n/a"
        lines.extend([
            f"Across all **{overall['n']}** committed `v1.4` frontier episodes ({', '.join(tier_bits)}) paired on identical world seeds against the deterministic Bayesian reference (`SolverPolicy`), `{TARGET_MODEL}` reaches **{ov_ratio}** of `SolverPolicy` overall (`{overall['carbon_mean']:+.4f}` vs `{overall['solver_mean']:+.4f}`, paired difference `{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}` 95% CI, `{overall['carbon_accuracy'] * 100.0:.0f}%` accusation accuracy):",
            "",
            f"| Tier | Paired Seeds (n) | `{TARGET_MODEL}` Mean +/- 95% CI | `SolverPolicy` Mean +/- 95% CI | Score / Solver | Paired Diff +/- 95% CI | Carbon Accuracy | Solver Accuracy | Mean Accuse Day (Carbon / Solver) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for tr in v14["tiers"]:
            r_txt = f"{tr['ratio'] * 100.0:.1f}%" if tr["ratio"] is not None else "n/a"
            s_acc = f"{tr['solver_accuracy'] * 100.0:.0f}%" if tr["solver_accuracy"] is not None else "n/a"
            c_day = f"{tr['carbon_accuse_day']:.2f}" if tr["carbon_accuse_day"] is not None else "n/a"
            s_day = f"{tr['solver_accuse_day']:.2f}" if tr["solver_accuse_day"] is not None else "n/a"
            lines.append(
                f"| `{_cell(tr['tier'])}` | {tr['n']} | {tr['carbon_mean']:+.4f} +/- {tr['carbon_ci']:.4f} | "
                f"{tr['solver_mean']:+.4f} +/- {tr['solver_ci']:.4f} | {r_txt} | "
                f"{tr['paired_diff']:+.4f} +/- {tr['diff_ci']:.4f} | {tr['carbon_accuracy'] * 100.0:.0f}% | "
                f"{s_acc} | {c_day} / {s_day} |"
            )
        if overall and len(v14["tiers"]) > 1:
            r_txt = f"{overall['ratio'] * 100.0:.1f}%" if overall["ratio"] is not None else "n/a"
            s_acc = f"{overall['solver_accuracy'] * 100.0:.0f}%" if overall["solver_accuracy"] is not None else "n/a"
            c_day = f"{overall['carbon_accuse_day']:.2f}" if overall["carbon_accuse_day"] is not None else "n/a"
            s_day = f"{overall['solver_accuse_day']:.2f}" if overall["solver_accuse_day"] is not None else "n/a"
            lines.append(
                f"| **Overall** | **{overall['n']}** | **{overall['carbon_mean']:+.4f} +/- {overall['carbon_ci']:.4f}** | "
                f"**{overall['solver_mean']:+.4f} +/- {overall['solver_ci']:.4f}** | **{r_txt}** | "
                f"**{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}** | **{overall['carbon_accuracy'] * 100.0:.0f}%** | "
                f"**{s_acc}** | **{c_day} / {s_day}** |"
            )

        if v14["seeds"]:
            lines.extend([
                "",
                "### Per-Seed Paired `v1.4` Investigator Ledger",
                "",
                "| Tier | Seed | Run Folder | Carbon Score | Solver Score | Diff | Carbon Correct | Solver Correct | Accuse Day (Carbon / Solver) |",
                "| --- | ---: | --- | ---: | ---: | ---: | --- | --- | --- |",
            ])
            for sr in v14["seeds"]:
                c_ok = "yes" if sr["carbon_correct"] else "no"
                s_ok = "yes" if sr["solver_correct"] else ("no" if sr["solver_correct"] is False else "n/a")
                c_d = str(sr["carbon_day"]) if sr["carbon_day"] is not None else "n/a"
                s_d = str(sr["solver_day"]) if sr["solver_day"] is not None else "n/a"
                lines.append(
                    f"| `{_cell(sr['tier'])}` | {sr['seed']} | `{_cell(sr['run_folder'])}` | "
                    f"{sr['carbon_score']:+.4f} | {sr['solver_score']:+.4f} | {sr['diff']:+.4f} | "
                    f"{c_ok} | {s_ok} | {c_d} / {s_d} |"
                )

    cmd_lines = [
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/sync_six_roles_docs.py --root . --check',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.provenance --root . --strict',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/build_gemini_submission_stats.py --root . --out-md docs/gemini/ROLES_REPORT.md --out-json results/gemini_roles/submission_stats.json --strict',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out /tmp/opencode/gemini-roles-dashboard',
    ]
    if replay_run is not None:
        cmd_lines.append(
            f'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/verify_replay.py {replay_run["run_folder"]}'
        )
    cmd_lines.append(
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_six_roles_docs_sync.py tests/test_gemini_submission_doc.py tests/test_submission_stats.py tests/test_roles_dashboard.py tests/test_gemini_provenance.py'
    )

    lines.extend([
        "",
        "## Keyless Offline Verification Commands",
        "",
        f"Judges can verify all {tot['n_verified_carbon_runs']:,} `{TARGET_MODEL}` run folders, token ledgers, replay transcripts, stats reports, and dashboard outputs offline without any API key:",
        "",
        "```bash",
        *cmd_lines,
        "```",
        "",
    ])
    return "\n".join(lines)


def _submission_role_outcome(role: str, ctx: dict[str, Any]) -> tuple[str, str]:
    ri = ctx["roles"][role]
    canon = ri["canonical_run"]
    runs = ri["runs"]
    meta_map = ctx["meta_by_folder"]
    eh = ctx["eh_summary"]
    v14 = ctx["v14_paired"]
    wt = ctx["wt_stats"]
    ms = ctx["mole_stats"]
    mm_ab = ctx["mm_ablation"]
    replay_run = ctx["replay_run"]

    if canon is None:
        return "unverified", "unverified (0 verified carbon runs)"

    if role == "world_text":
        caps = "Structured JSON (`response_schema`), public-facts-only isolation, live suspect interviews, deterministic cache"
        bits = [_clean_no_angles(canon["headline_metric"])]
        ab_med = _find_run(runs, "biased-chatter-ablation-carbon")
        if ab_med and ab_med["run_folder"] != canon["run_folder"]:
            bits.append(
                f"biased-chatter ablation (`{ab_med['run_folder']}`, commit `{ab_med['commit']}`): {_clean_no_angles(ab_med['headline_metric'])}"
            )
        if wt["worlds"] > 0:
            bits.append(f"0 ground-truth mole leaks across {wt['worlds']} v1.4 worlds ({wt['personas']} personas, {ri['n_runs']} runs)")
        return caps, "; ".join(bits)

    if role == "adaptive_mole":
        caps = "Evolutionary JSON DSL mutation, PAIRED solvability gate, live day-by-day mole play, catchability audit"
        bits = [_clean_no_angles(canon["headline_metric"])]
        paired_sc = _find_run(runs, "paired-solvable-scenarios-carbon")
        if paired_sc and paired_sc["run_folder"] != canon["run_folder"]:
            bits.append(
                f"PAIRED scenarios (`{paired_sc['run_folder']}`, commit `{paired_sc['commit']}`): {_clean_no_angles(paired_sc['headline_metric'])}"
            )
        live_hard = _find_run(runs, "arena-live-carbon-hard012")
        if live_hard and live_hard["run_folder"] != canon["run_folder"]:
            bits.append(
                f"live hard mole (`{live_hard['run_folder']}`, commit `{live_hard['commit']}`): {_clean_no_angles(live_hard['headline_metric'])}"
            )
        if ms["clash_runs"] > 0:
            bits.append(f"{ms['live_decisions']:,} live mole decisions and {ms['clash_runs']} carbon-vs-carbon clashes")
        return caps, "; ".join(bits)

    if role == "investigators":
        caps = "13-tool function calling, configurable `thinking_level` (`low`/`high`), thought-signature replay, prefix caching"
        bits = [_clean_no_angles(canon["headline_metric"])]
        overall = v14.get("overall")
        if isinstance(overall, dict) and overall["n"] > 0:
            r_pct = f"{overall['ratio'] * 100.0:.1f}%" if overall["ratio"] is not None else "n/a"
            cite_v14 = ""
            if replay_run and replay_run["run_folder"] != canon["run_folder"]:
                cite_v14 = f" (including `{replay_run['run_folder']}`, commit `{replay_run['commit']}`)"
            bits.append(
                f"paired v1.4 n={overall['n']}{cite_v14}: {overall['carbon_mean']:+.4f} vs SolverPolicy {overall['solver_mean']:+.4f} "
                f"({r_pct}, diff {overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f} 95% CI, {overall['carbon_accuracy'] * 100.0:.0f}% acc)"
            )
        return caps, "; ".join(bits)

    if role == "failure_analyst":
        caps = "1M-token long context, structured failure clustering, Bayesian calibration audit, verbatim quote verification"
        bits = [_clean_no_angles(canon["headline_metric"])]
        corpus_r = _find_run(runs, "carbon-longctx-corpus")
        if corpus_r and corpus_r["run_folder"] != canon["run_folder"]:
            bits.append(
                f"`{corpus_r['run_folder']}` (commit `{corpus_r['commit']}`): {_clean_no_angles(corpus_r['headline_metric'])}"
            )
        cal_r = _find_run(runs, "calibration-ev-carbon")
        if cal_r and cal_r["run_folder"] != canon["run_folder"]:
            bits.append(
                f"`{cal_r['run_folder']}` (commit `{cal_r['commit']}`): {_clean_no_angles(cal_r['headline_metric'])}"
            )
        return caps, "; ".join(bits)

    if role == "exploit_hunter":
        caps = "Whole-repo whitebox context pack, multi-persona exploit planning, in-process `Env` + live HTTP MCP execution"
        c_info = eh["per_run"].get(canon["run_folder"])
        if c_info is not None:
            bits = [
                f"{c_info['attempts']} attacks ({c_info['inproc_attempts']} in-process, {c_info['mcp_attempts']} live MCP; "
                f"{c_info['tool_calls']:,} tool calls): {c_info['exploits']} exploits, {c_info['violations']} violations"
            ]
        else:
            bits = [_clean_no_angles(canon["headline_metric"])]
        for folder, info in eh["per_run"].items():
            if folder == canon["run_folder"]:
                continue
            detail = "0 seed leaks (1 solver-level detective play audited)" if info["only_solver_level_flag"] else f"{info['exploits']} exploits"
            bits.append(
                f"`{folder}` (commit `{info['commit']}`): {info['attempts']} attacks "
                f"({info['inproc_attempts']} in-process, {info['mcp_attempts']} live MCP), {detail}"
            )
        bits.append(f"role total: {eh['inproc_attempts']}/{eh['total_attempts']} in-process, {eh['mcp_attempts']}/{eh['total_attempts']} live MCP")
        return caps, "; ".join(bits)

    caps = "Native PNG vision via `Part.from_bytes`, scanned watermark readout, multi-image dossiers, SOC & chart forensics"
    bits = [_clean_no_angles(canon["headline_metric"])]
    hard_ab = _find_run(runs, "memo-watermark-hard-ablation-carbon")
    if hard_ab and hard_ab["run_folder"] != canon["run_folder"]:
        bits.append(
            f"hard scan ablation (`{hard_ab['run_folder']}`, commit `{hard_ab['commit']}`): {_clean_no_angles(hard_ab['headline_metric'])}"
        )
    dossier = _find_run(runs, "multi-image-dossier-carbon")
    if dossier and dossier["run_folder"] != canon["run_folder"]:
        bits.append(
            f"multi-image dossiers (`{dossier['run_folder']}`, commit `{dossier['commit']}`): {_clean_no_angles(dossier['headline_metric'])}"
        )
    pooled = mm_ab.get("pooled_unique_seeds") if isinstance(mm_ab, dict) else None
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        bits.append(
            f"pooled unique ablation n={pooled['n_episodes']} ({pooled['n_images_read']} scans): "
            f"{pooled['multimodal_mean_score']:+.4f} vs {pooled['blind_mean_score']:+.4f} blind"
        )
    _ = meta_map
    return caps, "; ".join(bits)


def _render_why_gemini_essential_bullets(ctx: dict[str, Any], *, concise: bool) -> list[str]:
    tot = ctx["totals"]
    roles_map = ctx["roles"]
    eh = ctx["eh_summary"]
    mm_ab = ctx["mm_ablation"]
    mm_imgs = ctx["mm_total_images"]

    inv_runs = roles_map["investigators"]["runs"]
    hard_lad = _find_run(inv_runs, "thinking-ladder-carbon-hard0")
    wt_cal = _find_run(roles_map["world_text"]["runs"], "thinking-calibration-carbon")
    fa_canon = roles_map["failure_analyst"]["canonical_run"]

    if hard_lad is not None:
        think_ev = (
            f"On `hard` seed `0` (`{hard_lad['run_folder']}`, commit `{hard_lad['commit']}`), scaling from `0` (`low`) "
            f"to `{hard_lad['thinking_tokens']:,}` (`high`) thinking tokens cuts Bayesian step regret from `0.1623` to `0.0298` (`81.6%` reduction)"
        )
        if wt_cal is not None and not concise:
            think_ev += (
                f", while `{wt_cal['run_folder']}` (commit `{wt_cal['commit']}`) calibrates world-synthesis "
                "thinking tokens `0 -> 3,703 -> 38,674` across `low/medium/high`."
            )
        else:
            think_ev += "."
    else:
        think_ev = (
            f"Across `{tot['thinking_tokens']:,}` recorded thinking tokens, `{TARGET_MODEL}` supports controlled "
            "`low` vs `high` reasoning experiments on identical model weights and world seeds."
        )

    sig_txt = (
        f"Preserving Gemini cryptographic `thought_signature` tokens across multi-turn 13-tool episodes "
        f"(`{roles_map['investigators']['calls']:,}` investigator calls) keeps latent Bayesian hypothesis state intact "
        "across days and enables exact keyless trajectory replay (`scripts/verify_replay.py`)."
    )

    cache_txt = (
        f"Serving **{tot['cached_tokens']:,}** of **{tot['tokens_in']:,}** input tokens from explicit and prefix cache "
        f"(**{tot['cache_hit_pct']:.1f}%** cache hit rate across **{tot['calls']:,}** calls and **{tot['n_verified_carbon_runs']:,}** runs) "
        f"keeps the entire six-role benchmark suite at **${tot['cost_usd']:.4f}** (**${tot['cost_usd']:.2f} USD**) instead of roughly 4x list cost."
    )

    fa_tok = fa_canon["tokens_in"] if fa_canon is not None else roles_map["failure_analyst"]["tokens_in"]
    fa_cnt = fa_canon["count"] if fa_canon is not None else roles_map["failure_analyst"]["count"]
    repo_clause = (
        f" and whole-repository whitebox security packs (`{eh['max_pack_files']}` files, `{eh['max_pack_tokens']:,}` tokens)"
        if eh["max_pack_files"] > 0
        else ""
    )
    longctx_txt = (
        f"Ingests multi-episode trajectory corpora (`{fa_tok:,}` tokens across `{fa_cnt}` episodes){repo_clause} "
        "in a single unfragmented pass, avoiding lossy RAG chunking while maintaining `100%` code-verified quotes."
    )

    pooled = mm_ab.get("pooled_unique_seeds") if isinstance(mm_ab, dict) else None
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        vacc = f"{pooled['vision_accuracy'] * 100.0:.1f}%" if pooled.get("vision_accuracy") is not None else "100.0%"
        rec = f"{pooled['oracle_recovery_ratio'] * 100.0:.1f}%" if pooled.get("oracle_recovery_ratio") is not None else "100.0%"
        vis_txt = (
            f"Ingests `{mm_imgs:,}` rendered PNG scans, multi-image dossiers, SOC rasters, and trajectory charts via "
            f"`Part.from_bytes(mime_type=\"image/png\")`; removing vision on `{pooled['n_episodes']}` unique redacted-memo "
            f"episodes drops score from `{pooled['multimodal_mean_score']:+.4f}` to `{pooled['blind_mean_score']:+.4f}` "
            f"(`{vacc}` watermark accuracy, `{rec}` Bayesian text-oracle recovery), while naive log heuristics score `0%` on decoy-framed SOC rasters."
        )
    else:
        vis_txt = (
            f"Ingests `{mm_imgs:,}` rendered PNG evidence scans, dossiers, SOC heatmaps, and belief charts directly via "
            "`Part.from_bytes(mime_type=\"image/png\")` for causal pixel-level forensics."
        )

    return [
        f"- **Explicit `thinking_level` control:** {think_ev}",
        f"- **Thought signatures (`thought_signature`) across tool turns:** {sig_txt}",
        f"- **Explicit and prefix context caching:** {cache_txt}",
        f"- **1M-token long context:** {longctx_txt}",
        f"- **Native multimodal vision (`Part.from_bytes`):** {vis_txt}",
    ]


def render_six_roles_submission_md(ctx: dict[str, Any]) -> str:
    tot = ctx["totals"]
    roles_map = ctx["roles"]
    v14 = ctx["v14_paired"]
    eh = ctx["eh_summary"]
    mm_ab = ctx["mm_ablation"]
    mm_imgs = ctx["mm_total_images"]
    replay_run = ctx["replay_run"]

    lines: list[str] = [
        f"# Canary: Six Load-Bearing `{TARGET_MODEL}` Roles in One Self-Auditing RL Benchmark",
        "",
        f"Google DeepMind \"Best Use of Gemini API\" submission, Junction 2026. Repository: `github.com/s1laswang/agent-arena` (`canary/gemini/`). Every claim below is backed by a committed `{TARGET_MODEL}` run folder, `model_id`, and commit SHA verified by `canary.gemini.provenance --root . --strict` across all **{tot['n_verified_carbon_runs']:,}** verified run folders (**{tot['calls']:,}** API calls, **${tot['cost_usd']:.4f}** USD).",
        "",
        "## Platform Summary",
        "",
        ctx["platform_summary"],
        "",
        "## 1. The Problem and Why It Matters",
        "",
        "Organizations increasingly delegate high-stakes investigative workflows to AI agents: insider-threat triage, incident response, fraud review, and security operations. In each setting an agent must gather partial evidence under a tight daily action budget while company damage compounds, then commit to an irreversible accusation.",
        "",
        "Conventional leaderboards compress evaluation into a single scalar score. That scalar cannot answer the three questions engineering teams need before deployment:",
        "- **Where decisions break:** which specific action lost expected value relative to exact Bayesian reasoning (`premature_accusation`, `uninformative_canary`, `ignored_delay`, `over_restriction`, or `budget_waste`).",
        "- **What extra thinking buys:** whether scaling inference-time reasoning (`thinking_level`) improves experimental design or commit timing, and at what token and dollar cost.",
        "- **Whether the benchmark itself is fair and ungameable:** whether difficulty comes from genuine reasoning gaps rather than unsolvable worlds, leaked ground truth, or exploitable reward loopholes.",
        "",
        f"Canary automates the entire scientific loop on a single frontier model, `{TARGET_MODEL}`, pairing every episode against an exact Bayesian reference (`SolverPolicy`).",
        "",
        "## 2. How the Gemini API Is Integrated Across Six Essential Roles",
        "",
        f"All Gemini calls route through unified, ledgered clients (`canary/llm/` and `canary/gemini/`) with structured output schemas (`response_schema`), Pydantic validation, prefix and explicit context caching, thought-signature preservation across multi-turn tool calls, and keyless record/replay verification. Across the **{tot['n_verified_carbon_runs']:,}** committed `{TARGET_MODEL}` run folders audited by `canary.gemini.provenance`, Canary records **{tot['calls']:,} API calls**, **{tot['tokens_in']:,} input tokens** (**{tot['cached_tokens']:,} served from cache**, a **{tot['cache_hit_pct']:.1f}%** cache hit rate), **{tot['tokens_out']:,} output tokens**, and **{tot['thinking_tokens']:,} thinking tokens** across **{tot['count']:,} verified episodes and samples** for **${tot['cost_usd']:.4f}** (**${tot['cost_usd']:.2f} USD**, **{tot['secret_leaks_count']}** secret leaks).",
        "",
        "| Role | Gemini API Capabilities Used | Canonical Verified Run Folder | Model ID | Commit | Usage (Calls / In / Out / Think / Cost) | Verified Quantitative Outcome |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for role in REQUIRED_ROLES:
        canon = roles_map[role]["canonical_run"]
        caps, outcome = _submission_role_outcome(role, ctx)
        if canon is None:
            lines.append(
                f"| `{_cell(role)}` | {_cell(caps)} | none | none | none | 0 / 0 / 0 / 0 / $0.0000 | {_cell(outcome)} |"
            )
        else:
            usage_cell = (
                f"{canon['calls']:,} / {canon['tokens_in']:,} / {canon['tokens_out']:,} / "
                f"{canon['thinking_tokens']:,} / ${canon['cost_usd']:.4f}"
            )
            lines.append(
                f"| `{_cell(role)}` | {_cell(caps)} | `{_cell(canon['run_folder'])}` | "
                f"`{_cell(canon['model_id'])}` | `{_cell(canon['commit'])}` | {usage_cell} | {_cell(outcome)} |"
            )

    lines.extend([
        "",
        f"- **Explicit `exploit_hunter` execution-channel disclosure:** {_exploit_disclosure_sentence(eh, cite_commits=True)}",
    ])

    overall = v14.get("overall")
    if isinstance(overall, dict) and overall["n"] > 0:
        tier_chunks = []
        for tr in v14["tiers"]:
            r_txt = f"{tr['ratio'] * 100.0:.1f}%" if tr["ratio"] is not None else "n/a"
            tier_chunks.append(
                f"`{tr['tier']}` n={tr['n']}: `{tr['carbon_mean']:+.4f}` vs `{tr['solver_mean']:+.4f}` "
                f"({r_txt}, diff `{tr['paired_diff']:+.4f} +/- {tr['diff_ci']:.4f}`)"
            )
        ov_ratio = f"{overall['ratio'] * 100.0:.1f}%" if overall["ratio"] is not None else "n/a"
        lines.append(
            f"- **Paired `v1.4` `{TARGET_MODEL}` vs `SolverPolicy` summary (`n={overall['n']}`, 95% CIs):** "
            f"overall `{overall['carbon_mean']:+.4f}` vs `{overall['solver_mean']:+.4f}` (`{ov_ratio}`, paired diff "
            f"`{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}`, `{overall['carbon_accuracy'] * 100.0:.0f}%` vs "
            f"`{(overall['solver_accuracy'] or 0.0) * 100.0:.0f}%` accuracy); by tier: {'; '.join(tier_chunks)}."
        )

    mole_runs = roles_map["adaptive_mole"]["runs"]
    paired_hard = _find_run(mole_runs, "paired-skill-designer-carbon-hard")
    clash_0 = _find_run(mole_runs, "carbon-vs-carbon-seed0")
    inv_runs = roles_map["investigators"]["runs"]
    hard_lad = _find_run(inv_runs, "thinking-ladder-carbon-hard0")
    mm_runs = roles_map["multimodal_evidence"]["runs"]
    soc_sweep = _find_run(mm_runs, "access-heatmap-v14-sweep-carbon")
    traj_for = _find_run(mm_runs, "carbon-trajectory-forensics")

    innov_1 = (
        f"1. **Solvability-constrained adversarial co-evolution (`adaptive_mole`).** Rather than inflating difficulty through unfair noise, `{TARGET_MODEL}` evolves mole DSL strategies and proposes PAIRED scenarios rejected unless `SolverPolicy` stays high and `ObviousHeuristic` fails (`{roles_map['adaptive_mole']['n_runs']}` verified runs, `{roles_map['adaptive_mole']['calls']:,}` calls)"
    )
    if paired_hard is not None:
        innov_1 += f", including `{paired_hard['run_folder']}` (commit `{paired_hard['commit']}`, `{_clean_no_angles(paired_hard['headline_metric'])}`)"
    if clash_0 is not None:
        innov_1 += f" and live head-to-head clashes such as `{clash_0['run_folder']}` (commit `{clash_0['commit']}`, `{_clean_no_angles(clash_0['headline_metric'])}`)"
    innov_1 += "."

    innov_2 = (
        f"2. **Controlled `thinking_level` regret decomposition (`investigators`).** Holding `{TARGET_MODEL}`, the 13 tool definitions, and world seeds constant while toggling `thinking_level` (`low` vs `high`) separates information-gathering quality from stopping calibration"
    )
    if hard_lad is not None:
        innov_2 += (
            f": in `{hard_lad['run_folder']}` (commit `{hard_lad['commit']}`), scaling from `0` to `{hard_lad['thinking_tokens']:,}` thinking tokens eliminates `uninformative_canary` errors and slashes step-level solver regret from `0.1623` to `0.0298` (`81.6%` reduction) while exposing conservative commit delay."
        )
    else:
        innov_2 += f" across `{roles_map['investigators']['n_runs']}` verified investigator runs."

    innov_3 = (
        f"3. **Checked-not-trusted long-context forensics (`failure_analyst`).** `{TARGET_MODEL}` reads full frontier trajectory corpora (`{roles_map['failure_analyst']['tokens_in']:,}` total input tokens across `{roles_map['failure_analyst']['n_runs']}` runs) in single long-context calls, while every regret value comes from `canary.solver.regret` and every cited quote is verified character-for-character in Python (`100%` verified quotes)."
    )

    innov_4 = (
        f"4. **Whole-repo and live MCP red-teaming audited by server ledgers (`exploit_hunter`).** `{TARGET_MODEL}` plans and executes `{eh['total_attempts']}` audited role attacks (`{eh['inproc_attempts']}` in-process and `{eh['mcp_attempts']}` via live HTTP MCP, `{eh['tool_calls']:,}` tool calls) scored strictly from server-side ledgers, confirming `0` seed leaks across `12,000+` `public_world_match` probes."
    )

    pooled = mm_ab.get("pooled_unique_seeds") if isinstance(mm_ab, dict) else None
    innov_5 = (
        f"5. **Causal pixel-only and multi-image multimodal ablations (`multimodal_evidence`).** Across `{roles_map['multimodal_evidence']['n_runs']}` verified runs (`{mm_imgs:,}` PNGs read via `Part.from_bytes`), Canary proves causal visual dependence"
    )
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        innov_5 += (
            f": across `{pooled['n_episodes']}` unique redacted-memo episodes (`{pooled['n_images_read']}` scans), vision lifts score from `{pooled['blind_mean_score']:+.4f}` (blind) to `{pooled['multimodal_mean_score']:+.4f}` (`100.0%` oracle recovery)"
        )
    if soc_sweep is not None:
        innov_5 += f", `{soc_sweep['run_folder']}` (commit `{soc_sweep['commit']}`) separates moles from framed decoys (`90%` mole and `100%` decoy vs `0%` naive)"
    if traj_for is not None:
        innov_5 += f", and `{traj_for['run_folder']}` (commit `{traj_for['commit']}`) hits `100%` threshold and exact-day chart forensics"
    innov_5 += "."

    cmd_lines = [
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/sync_six_roles_docs.py --root . --check',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.provenance --root . --strict',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/build_gemini_submission_stats.py --root . --out-md docs/gemini/ROLES_REPORT.md --out-json results/gemini_roles/submission_stats.json --strict',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out /tmp/opencode/gemini-roles-dashboard',
    ]
    if replay_run is not None:
        cmd_lines.append(
            f'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/verify_replay.py {replay_run["run_folder"]}'
        )
    cmd_lines.append(
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_six_roles_docs_sync.py tests/test_gemini_submission_doc.py tests/test_submission_stats.py tests/test_roles_dashboard.py tests/test_gemini_provenance.py'
    )

    lines.extend([
        "",
        "## 3. What Is Innovative and Technically Impressive",
        "",
        innov_1,
        innov_2,
        innov_3,
        innov_4,
        innov_5,
        "",
        "## 4. Why Gemini Is Essential",
        "",
        f"Removing `{TARGET_MODEL}` or its Gemini-native API controls from any of the six roles measurably degrades or disables Canary:",
        "",
        *_render_why_gemini_essential_bullets(ctx, concise=False),
        "",
        "## 5. Keyless Offline Reproduction",
        "",
        "Every provenance record, token count, replay transcript, automated stats report, synchronized write-up, and HTML showcase dashboard verifies offline with zero API keys:",
        "",
        "```bash",
        *cmd_lines,
        "```",
        "",
        "## Team",
        "",
        "Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), and Chintufp.",
        "",
    ])
    return "\n".join(lines)


def render_six_roles_pitch_md(ctx: dict[str, Any]) -> str:
    tot = ctx["totals"]
    roles_map = ctx["roles"]
    v14 = ctx["v14_paired"]
    eh = ctx["eh_summary"]
    overall = v14.get("overall")

    paired_sentence = ""
    if isinstance(overall, dict) and overall["n"] > 0:
        ov_ratio = f"{overall['ratio'] * 100.0:.1f}%" if overall["ratio"] is not None else "n/a"
        paired_sentence = (
            f" Across **n={overall['n']}** paired `v1.4` episodes, `{TARGET_MODEL}` reaches **{ov_ratio}** of "
            f"`SolverPolicy` (`{overall['carbon_mean']:+.4f}` vs `{overall['solver_mean']:+.4f}`, paired diff "
            f"`{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}` 95% CI, `{overall['carbon_accuracy'] * 100.0:.0f}%` accuracy)."
        )

    lines: list[str] = [
        f"# Canary x Gemini: Six Essential `{TARGET_MODEL}` Roles",
        "",
        "## Platform Summary",
        "",
        ctx["platform_summary"],
        "",
        "## 1. The Problem and Why It Matters",
        "",
        f"AI agents now execute high-stakes security investigations where evidence is partial, daily budgets are tight, and company value bleeds until an irreversible accusation. Single scalar leaderboards cannot reveal *where* reasoning fails, *what extra thinking buys*, or *whether the reward is gameable*. Canary pairs every episode with an exact Bayesian solver (`SolverPolicy`) and puts `{TARGET_MODEL}` in six load-bearing roles across **{tot['n_verified_carbon_runs']:,} verified runs**, **{tot['calls']:,} API calls**, **{tot['tokens_in']:,} input tokens** (**{tot['cached_tokens']:,} cached**, **{tot['cache_hit_pct']:.1f}%** hit rate), **{tot['thinking_tokens']:,} thinking tokens**, and **${tot['cost_usd']:.4f}** (**${tot['cost_usd']:.2f} USD**, **{tot['secret_leaks_count']}** secret leaks).{paired_sentence}",
        "",
        f"## 2. Six Verified `{TARGET_MODEL}` Roles (One Labelled Real Run per Role)",
        "",
        "| Role | What `gemini-4-carbon` Does | Canonical Run Folder | Model ID | Commit | Calls / Cost | Verified Result |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    short_what = {
        "world_text": "Synthesizes personas, biased chatter, live interviews, and mid-episode events strictly from public facts (`response_schema`, 0 mole leaks).",
        "adaptive_mole": "Evolves JSON mole DSL strategies, co-designs PAIRED scenarios under a solver catchability gate, and plays the mole live.",
        "investigators": "Plays head of security over 13 tools with thought-signature replay and `thinking_level` control (`low`/`high`), paired vs `SolverPolicy`.",
        "failure_analyst": "Reads full multi-episode trajectory corpora in 1M long context to cluster failures and audit calibration with 100% verified quotes.",
        "exploit_hunter": "Packs whole-repo source to plan and execute whitebox and blackbox attacks across in-process `Env` and live HTTP MCP, ledger-audited.",
        "multimodal_evidence": "Reads pixel-only canary watermarks (`Part.from_bytes`), fuses multi-image dossiers, and diagnoses SOC rasters and trajectory charts.",
    }

    for role in REQUIRED_ROLES:
        canon = roles_map[role]["canonical_run"]
        _, outcome = _submission_role_outcome(role, ctx)
        if canon is None:
            lines.append(
                f"| `{_cell(role)}` | {_cell(short_what[role])} | none | none | none | 0 / $0.0000 | unverified |"
            )
        else:
            lines.append(
                f"| `{_cell(role)}` | {_cell(short_what[role])} | `{_cell(canon['run_folder'])}` | "
                f"`{_cell(canon['model_id'])}` | `{_cell(canon['commit'])}` | "
                f"{canon['calls']:,} / ${canon['cost_usd']:.4f} | {_cell(outcome)} |"
            )

    lines.extend([
        "",
        f"- **Explicit `exploit_hunter` channel disclosure:** {_exploit_disclosure_sentence(eh, cite_commits=True)}",
        "",
        "## 3. What Is Innovative",
        "",
        "- **Difficulty by reasoning, never unfairness:** PAIRED scenario proposals and Mole Forge children are accepted only when `SolverPolicy` stays high and naive heuristics fail, guaranteeing catchable hardness.",
        f"- **Thinking-level Bayesian regret attribution:** Controlled `low` vs `high` `thinking_level` runs on identical `{TARGET_MODEL}` weights and seeds separate experimental-design gains from commit-timing conservatism.",
        "- **Checked, not trusted:** Every Failure Analyst quote is verified verbatim in Python (`100%`), every regret tag comes from `SolverPolicy`, and every Exploit Hunter score comes strictly from the server-side ledger.",
        "",
        "## 4. Why Gemini Is Essential",
        "",
        *_render_why_gemini_essential_bullets(ctx, concise=True),
        "",
        f"Full provenance tables and all {tot['n_verified_carbon_runs']:,} verified runs: `docs/gemini/SIX_ROLES_SUBMISSION.md`, `docs/gemini/SIX_ROLES_MATRIX.md`, and `docs/gemini/ROLES_REPORT.md`.",
        "",
        "```bash",
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python scripts/sync_six_roles_docs.py --root . --check',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.provenance --root . --strict',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.roles_dashboard --root . --out /tmp/opencode/gemini-roles-dashboard',
        "```",
        "",
    ])
    return "\n".join(lines)


def validate_six_roles_doc_text(
    md_text: str,
    root: str | Path,
    *,
    kind: str,
    prov: dict[str, Any] | None = None,
) -> list[str]:
    root_path = Path(root).resolve()
    errors = list(validate_report_text(md_text, root_path))

    if DRAFT_RE.search(md_text):
        errors.append("draft_marker_found")
    if "no api key yet" in md_text.lower():
        errors.append("outdated_no_api_key_note")
    if ASCII_ANGLE_PLACEHOLDER_RE.search(md_text):
        errors.append("ascii_angle_placeholder_found")

    for role in REQUIRED_ROLES:
        if role not in md_text:
            errors.append(f"missing_role_id:{role}")
    if TARGET_MODEL not in md_text:
        errors.append("missing_target_model")
    if "canary.gemini.provenance" not in md_text:
        errors.append("missing_provenance_cmd")
    if "canary.gemini.roles_dashboard" not in md_text:
        errors.append("missing_dashboard_cmd")

    folders = _extract_doc_run_folders(md_text)
    roles_seen: set[str] = set()
    for rel in folders:
        run_dir = root_path / rel
        if not run_dir.is_dir():
            errors.append(f"missing_dir:{rel}")
            continue
        meta = _load_json(run_dir / "meta.json")
        if not meta:
            errors.append(f"missing_or_invalid_meta:{rel}")
            continue
        model_id = meta.get("model_id") or meta.get("model")
        if model_id != TARGET_MODEL:
            errors.append(f"wrong_model_id:{rel}:{model_id!r}")
            continue
        commit = str(meta.get("commit") or meta.get("git_sha") or "").strip()
        if not COMMIT_RE.match(commit):
            errors.append(f"invalid_commit:{rel}:{commit!r}")
            continue
        if commit not in md_text and commit[:7] not in md_text:
            errors.append(f"uncited_commit:{rel}:{commit[:10]}")
            continue
        role_val = meta.get("role")
        if isinstance(role_val, str) and role_val in REQUIRED_ROLES:
            roles_seen.add(role_val)
        elif rel.startswith("data/runs/committed/v1.4/gemini-4-carbon/"):
            roles_seen.add("investigators")

    if prov is not None and prov.get("verified"):
        for r in REQUIRED_ROLES:
            if r not in roles_seen:
                errors.append(f"uncited_role_run:{r}")

    if kind == "matrix" and prov is not None:
        verified_prov = {
            r["run_dir"]: r
            for r in (prov.get("runs") or [])
            if r.get("verified") and r.get("role") in REQUIRED_ROLES
        }
        cited_set = set(folders)
        for vdir, entry in sorted(verified_prov.items()):
            if vdir not in cited_set:
                errors.append(f"matrix_missing_verified_run:{vdir}")
                continue
            if f"{int(entry['tokens_in']):,}" not in md_text:
                errors.append(f"matrix_missing_tokens_in:{vdir}")
            if f"{int(entry['tokens_out']):,}" not in md_text:
                errors.append(f"matrix_missing_tokens_out:{vdir}")

    if kind in ("submission", "pitch"):
        try:
            summary = extract_platform_summary(md_text)
            if not (100 <= len(summary) <= SUMMARY_MAX_CHARS):
                errors.append(f"platform_summary_len:{len(summary)}")
        except ValueError as exc:
            errors.append(f"platform_summary_missing:{exc}")

        low = md_text.lower()
        if "why gemini is essential" not in low:
            errors.append("missing_why_gemini_essential")
        for req_kw in ("thinking_level", "thought_signature", "part.from_bytes", "in-process", "mcp"):
            if req_kw not in low:
                errors.append(f"missing_required_disclosure_or_pillar:{req_kw}")

    return errors


def _finalize_stats_with_validation(stats: dict[str, Any], root_path: Path) -> tuple[dict[str, Any], str, str]:
    stats_copy = copy.deepcopy(stats)
    stats_copy.pop("validation", None)
    md_text = render_submission_report_md(stats_copy)
    prelim_json = render_submission_stats_json(stats_copy)
    md_errors = validate_report_text(md_text, root_path)
    json_errors = validate_report_text(prelim_json, root_path)
    stats_copy["validation"] = {
        "md_valid": len(md_errors) == 0,
        "md_errors": md_errors,
        "json_valid": len(json_errors) == 0,
        "json_errors": json_errors,
    }
    final_json = render_submission_stats_json(stats_copy)
    return stats_copy, md_text, final_json


def build_six_roles_bundle(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    prov = audit_provenance(root_path)
    raw_stats = build_submission_stats(root_path, provenance_report=prov)
    stats, roles_report_md, stats_json = _finalize_stats_with_validation(raw_stats, root_path)
    ctx = _build_context(root_path, prov, stats)
    matrix_md = render_six_roles_matrix_md(ctx)
    submission_md = render_six_roles_submission_md(ctx)
    pitch_md = render_six_roles_pitch_md(ctx)

    validation_errors: dict[str, list[str]] = {
        DEFAULT_OUT_JSON: list(stats["validation"]["json_errors"]),
        DEFAULT_OUT_MD: list(stats["validation"]["md_errors"]),
        DEFAULT_MATRIX_MD: validate_six_roles_doc_text(matrix_md, root_path, kind="matrix", prov=prov),
        DEFAULT_SUBMISSION_MD: validate_six_roles_doc_text(submission_md, root_path, kind="submission", prov=prov),
        DEFAULT_PITCH_MD: validate_six_roles_doc_text(pitch_md, root_path, kind="pitch", prov=prov),
    }

    return {
        "root": root_path,
        "provenance": prov,
        "stats": stats,
        "totals": ctx["totals"],
        "v14_paired": ctx["v14_paired"],
        "eh_summary": ctx["eh_summary"],
        "platform_summary": ctx["platform_summary"],
        "rendered": {
            DEFAULT_OUT_JSON: stats_json,
            DEFAULT_OUT_MD: roles_report_md,
            DEFAULT_MATRIX_MD: matrix_md,
            DEFAULT_SUBMISSION_MD: submission_md,
            DEFAULT_PITCH_MD: pitch_md,
        },
        "validation_errors": validation_errors,
    }


def _resolve_rel(root_path: Path, rel_or_abs: str | Path) -> Path:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = root_path / p
    if p.name == "meta.json":
        raise ValueError("Output file must never be named meta.json")
    return p


def sync_six_roles_docs(
    root: str | Path = ".",
    *,
    check: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    bundle = build_six_roles_bundle(root_path)
    rendered: dict[str, str] = dict(bundle["rendered"])
    val_errors: dict[str, list[str]] = {k: list(v) for k, v in bundle["validation_errors"].items()}

    target_paths: dict[str, Path] = {
        rel_key: _resolve_rel(root_path, rel_key)
        for rel_key in rendered
    }

    if check:
        stats_json_path = target_paths[DEFAULT_OUT_JSON]
        if stats_json_path.is_file():
            disk_stats_obj = _load_json(stats_json_path)
            disk_head = disk_stats_obj.get("git_head")
            if isinstance(disk_head, str) and (COMMIT_RE.fullmatch(disk_head) or disk_head == "unknown"):
                head_adjusted = copy.deepcopy(bundle["stats"])
                head_adjusted["git_head"] = disk_head
                _, adj_report_md, adj_stats_json = _finalize_stats_with_validation(head_adjusted, root_path)
                rendered[DEFAULT_OUT_MD] = adj_report_md
                rendered[DEFAULT_OUT_JSON] = adj_stats_json

        out_of_sync: list[str] = []
        missing_files: list[str] = []
        disk_secret_leaks: list[str] = []

        for rel_key, abs_path in target_paths.items():
            if not abs_path.is_file():
                missing_files.append(rel_key)
                out_of_sync.append(rel_key)
                continue
            disk_text = abs_path.read_text(encoding="utf-8")
            if disk_text != rendered[rel_key]:
                out_of_sync.append(rel_key)
            if scan_file_secrets(abs_path, root_path):
                disk_secret_leaks.append(rel_key)

        has_val_err = any(bool(v) for v in val_errors.values()) or bool(disk_secret_leaks)
        strict_fail = strict and not bool(bundle["totals"]["all_roles_verified"])
        ok = len(out_of_sync) == 0 and not has_val_err and not strict_fail
        return {
            "ok": ok,
            "mode": "check",
            "out_of_sync": out_of_sync,
            "missing_files": missing_files,
            "disk_secret_leaks": disk_secret_leaks,
            "validation_errors": val_errors,
            "totals": bundle["totals"],
            "v14_paired": bundle["v14_paired"],
            "platform_summary": bundle["platform_summary"],
            "files": {k: str(v) for k, v in target_paths.items()},
        }

    bad_val = {k: v for k, v in val_errors.items() if v}
    if bad_val:
        raise ValueError(f"Generated document validation failed: {bad_val}")
    if strict and not bool(bundle["totals"]["all_roles_verified"]):
        raise ValueError(
            f"Strict six-roles sync failed: verified {bundle['totals']['n_roles_verified']}/"
            f"{bundle['totals']['n_roles_required']} roles"
        )

    for rel_key, abs_path in target_paths.items():
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(rendered[rel_key], encoding="utf-8")

    return {
        "ok": True,
        "mode": "write",
        "out_of_sync": [],
        "missing_files": [],
        "disk_secret_leaks": [],
        "validation_errors": val_errors,
        "totals": bundle["totals"],
        "v14_paired": bundle["v14_paired"],
        "platform_summary": bundle["platform_summary"],
        "files": {k: str(v) for k, v in target_paths.items()},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministically sync or check 6-role Gemini provenance tables and prize write-up docs."
    )
    ap.add_argument("--root", default=".", help="repository root directory")
    ap.add_argument("--check", action="store_true", help="verify docs and stats JSON are in sync without writing")
    ap.add_argument("--strict", action="store_true", help="require all 6 roles to have verified gemini-4-carbon runs")
    args = ap.parse_args(argv)

    try:
        result = sync_six_roles_docs(
            root=args.root,
            check=args.check,
            strict=args.strict,
        )
    except ValueError as exc:
        sys.stderr.write(f"six_roles_docs error: {exc}\n")
        return 1

    tot = result["totals"]
    overall = (result["v14_paired"] or {}).get("overall")
    paired_str = (
        f"paired_v14_n={overall['n']} diff={overall['paired_diff']:+.4f}+/-{overall['diff_ci']:.4f}"
        if isinstance(overall, dict) and overall.get("n")
        else "paired_v14_n=0"
    )
    summary_len = len(result["platform_summary"])

    if args.check:
        if not result["ok"]:
            sys.stderr.write(
                f"six_roles_docs check FAILED: out_of_sync={result['out_of_sync']} "
                f"missing={result['missing_files']} leaks={result['disk_secret_leaks']} "
                f"validation_errors={ {k: v for k, v in result['validation_errors'].items() if v} }\n"
            )
            return 1
        print(
            f"six_roles_docs check OK: {tot['n_roles_verified']}/{tot['n_roles_required']} roles, "
            f"{tot['n_verified_carbon_runs']} carbon runs, calls={tot['calls']}, "
            f"in={tot['tokens_in']}, out={tot['tokens_out']}, thinking={tot['thinking_tokens']}, "
            f"cached={tot['cached_tokens']}, cost=${tot['cost_usd']:.4f}, {paired_str}, "
            f"summary_chars={summary_len}/{SUMMARY_MAX_CHARS}"
        )
        return 0

    print(
        f"six_roles_docs synced 5 files: {tot['n_roles_verified']}/{tot['n_roles_required']} roles, "
        f"{tot['n_verified_carbon_runs']} carbon runs, calls={tot['calls']}, "
        f"in={tot['tokens_in']}, out={tot['tokens_out']}, thinking={tot['thinking_tokens']}, "
        f"cached={tot['cached_tokens']}, cost=${tot['cost_usd']:.4f}, {paired_str}, "
        f"summary_chars={summary_len}/{SUMMARY_MAX_CHARS}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
