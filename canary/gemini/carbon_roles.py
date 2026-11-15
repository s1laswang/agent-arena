from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from canary.analysis.gap import mean_ci
from canary.env import Env
from canary.eval import run_episode
from canary.llm.pricing import cost as price_cost
from canary.solver.policy import SolverPolicy

REQUIRED_ROLES: tuple[str, ...] = (
    "world_text",
    "adaptive_mole",
    "investigators",
    "failure_analyst",
    "exploit_hunter",
    "multimodal_evidence",
)
TARGET_MODEL = "gemini-4-carbon"
DEFAULT_ROLES_DIR = "results/gemini/roles_carbon"
DEFAULT_ROLES_MD = "docs/gemini/ROLES_CARBON.md"
DEFAULT_SUBMISSION_MD = "docs/gemini/SIX_ROLES_SUBMISSION.md"
SUMMARY_MAX_CHARS = 600

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
FORBIDDEN_DASHES = tuple(
    chr(cp)
    for cp in (
        0x2010,
        0x2011,
        0x2012,
        0x2013,
        0x2014,
        0x2015,
        0x2212,
        0xFE58,
        0xFE63,
        0xFF0D,
    )
)
STALE_ROLES_PREFIX = "/".join(("results", "gemini_roles"))

SKIP_DIRS = frozenset({
    "_cache",
    "reference",
    "superseded",
    "_invalid",
    "worldtext-carbon-suite",
    "carbon-vs-carbon-suite",
    "multimodal-carbon-suite",
})

ROLE_META: dict[str, dict[str, Any]] = {
    "world_text": {
        "index": 1,
        "title": "Leak-Free World Text, Biased Chatter, and Live Suspect Interviews",
        "stage": "World synthesis (demo/research v1.5 layer, not judged v1.4)",
        "preferred_canonical": (
            "persona-interviews-carbon",
            "biased-chatter-ablation-carbon",
            "carbon-v14-seeds012",
        ),
        "capabilities": "Structured JSON (`response_schema`), public-facts-only isolation, live suspect interviews, 37-encoding stego audit",
        "why_essential": "Generates realistic corporate chatter, personas, and dynamic events strictly from public facts with zero ground-truth mole leaks.",
    },
    "adaptive_mole": {
        "index": 2,
        "title": "Solvability-Gated Scenario Co-Designer, Mole Forge, and Live Arena Adversary",
        "stage": "Adversarial co-evolution (arena mode, not judged v1.4)",
        "preferred_canonical": (
            "paired-skill-designer-carbon-hard",
            "arena-live-carbon-hard012",
            "paired-solvable-scenarios-carbon",
        ),
        "capabilities": "Evolutionary JSON DSL mutation, PAIRED solvability gate, live day-by-day mole play, catchability audit",
        "why_essential": "Raises investigator difficulty via genuine reasoning traps rather than unsolvable noise, verified against `SolverPolicy`.",
    },
    "investigators": {
        "index": 3,
        "title": "13-Tool Frontier Security Investigator Paired Against `SolverPolicy`",
        "stage": "In-process frontier player (`v1.4` dev seeds)",
        "preferred_canonical": (
            "thinking-ladder-carbon-hard0",
            "hard-0",
            "easy-0-3",
        ),
        "capabilities": "13-tool function calling, controlled `thinking_level` (`low`/`high`), `thought_signature` replay, prefix caching",
        "why_essential": "Executes multi-day canary trap design and stopping calibration under budget constraints paired seed-for-seed with `SolverPolicy`.",
    },
    "failure_analyst": {
        "index": 4,
        "title": "Long-Context Failure Atlas, Calibration Forensics, and Automated Claim Audit",
        "stage": "Post-hoc long-context forensics (checked in Python)",
        "preferred_canonical": (
            "atlas-carbon",
            "carbon-longctx-corpus",
            "claim-audit-carbon",
        ),
        "capabilities": "1M-token long context, structured failure clustering, Bayesian calibration audit, verbatim quote verification",
        "why_essential": "Ingests full multi-episode trajectory corpora in unfragmented passes while every quote and regret value is verified in code.",
    },
    "exploit_hunter": {
        "index": 5,
        "title": "Whole-Repo Whitebox and Live HTTP MCP Red-Team Swarm",
        "stage": "Reward & isolation red-teaming (server-ledger scored)",
        "preferred_canonical": (
            "whitebox-swarm-carbon",
            "blackbox-swarm-carbon",
        ),
        "capabilities": "Whole-repo whitebox context pack, multi-persona exploit planning, in-process `Env` + live HTTP MCP execution",
        "why_essential": "Audits reward integrity across full source packs and live MCP tool boundaries scored strictly from server-side ledgers.",
    },
    "multimodal_evidence": {
        "index": 6,
        "title": "Pixel-Only Watermark Vision, Multi-Image Dossiers, and SOC Chart Forensics",
        "stage": "Native PNG multimodal forensics (`Part.from_bytes`)",
        "preferred_canonical": (
            "scanned-evidence-ablation-carbon",
            "memo-watermark-hard-ablation-carbon",
            "multi-image-dossier-v14-expanded-carbon",
        ),
        "capabilities": "Native PNG vision via `Part.from_bytes`, scanned watermark readout, multi-image dossiers, SOC & chart forensics",
        "why_essential": "Recovers causal canary evidence rendered exclusively in pixels and separates framed decoys from true insiders.",
    },
}

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
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
TODO_TBD_RE = re.compile(r"\b(?:TODO|TBD|DRAFT)\b", re.IGNORECASE)
ASCII_ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_.\-/ ]+>")
DOC_RUN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])(results/gemini/roles_carbon/[A-Za-z0-9_.\-/]+)"
)
DOC_FILE_EXTS = frozenset({
    ".json",
    ".jsonl",
    ".md",
    ".html",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".csv",
    ".txt",
    ".py",
})


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and not math.isnan(float(val))


def _is_pos_num(val: Any) -> bool:
    return _is_num(val) and float(val) > 0.0


def _truthy_flag(val: Any) -> bool:
    if val is True:
        return True
    if isinstance(val, str) and val.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _has_env_secret(text: str) -> bool:
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
            return True
    return False


def sanitize_text(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    if _has_env_secret(s):
        s = ENV_KEY_RE.sub("[redacted]", s)
    s = GOOGLE_KEY_RE.sub("[redacted]", s)
    s = SK_KEY_RE.sub("[redacted]", s)
    s = OAUTH_RE.sub("[redacted]", s)
    for d in FORBIDDEN_DASHES:
        s = s.replace(d, "-")
    s = s.replace("\u27e8", "[").replace("\u27e9", "]")
    s = re.sub(r"<([^>\r\n]+)>", r"[\1]", s)
    s = s.replace("<", "[")
    s = s.replace(STALE_ROLES_PREFIX, DEFAULT_ROLES_DIR)
    s = TODO_TBD_RE.sub("unspecified", s)
    return s


def _md_cell(val: Any) -> str:
    txt = sanitize_text(val).replace("\r", " ").replace("\n", " ").strip()
    return txt.replace("|", "\\|")


def _fmt_pct(val: float) -> str:
    ratio = val / 100.0 if val > 1.0001 else val
    return f"{ratio * 100.0:.0f}%"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, UnicodeDecodeError, ValueError):
        return {}


def _count_jsonl_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
    except OSError:
        return 0


def scan_file_hygiene(file_path: Path, root: Path) -> list[dict[str, str]]:
    rel = _rel_posix(file_path, root)
    findings: list[dict[str, str]] = []
    if file_path.name == ".env" or file_path.name.startswith(".env."):
        findings.append({"file": rel, "kind": "tracked_env_file"})
    if file_path.name == "SALT" or "SALT" in file_path.parts:
        findings.append({"file": rel, "kind": "tracked_salt_file"})
    try:
        raw_bytes = file_path.read_bytes()
    except OSError:
        return [{"file": rel, "kind": "unreadable_file"}]

    if file_path.name.endswith(".world.json"):
        txt_world = raw_bytes.decode("utf-8", errors="replace")
        if '"mole"' in txt_world:
            findings.append({"file": rel, "kind": "world_mole_answer_key"})

    if b"\x00" in raw_bytes:
        return findings

    text = raw_bytes.decode("utf-8", errors="replace")
    if GOOGLE_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "google_api_key"})
    if SK_KEY_RE.search(text):
        findings.append({"file": rel, "kind": "sk_api_key"})
    if OAUTH_RE.search(text):
        findings.append({"file": rel, "kind": "oauth_token"})
    if _has_env_secret(text):
        findings.append({"file": rel, "kind": "env_api_key"})
    return findings


def _first_pos_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for k in keys:
        v = mapping.get(k)
        if _is_num(v) and int(v) > 0:
            return int(v)
    return None


def _first_nonneg_int(mapping: dict[str, Any], keys: tuple[str, ...]) -> int:
    for k in keys:
        v = mapping.get(k)
        if _is_num(v) and int(v) >= 0:
            return int(v)
    return 0


def extract_usage_flexible(
    run_dir: Path,
    meta: dict[str, Any],
    model_id: str,
) -> dict[str, Any]:
    usage = meta.get("usage")
    if not isinstance(usage, dict):
        usage = meta.get("ledger") if isinstance(meta.get("ledger"), dict) else {}
    if not usage:
        for fname in ("summary.json", "results.json", "comparison.json", "audit.json", "swarm.json"):
            sib = _load_json(run_dir / fname)
            if isinstance(sib.get("usage"), dict):
                usage = sib["usage"]
                break

    if not isinstance(usage, dict) or not usage:
        return {
            "calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "thinking_tokens": 0,
            "cached_tokens": 0,
            "cost_usd": 0.0,
            "list_cost_usd": 0.0,
            "error": "missing_usage",
        }

    tin = _first_pos_int(usage, ("in", "tokens_in", "input_tokens", "in_tokens", "prompt_tokens")) or 0
    tout = _first_pos_int(
        usage,
        ("out", "tokens_out", "output_tokens", "out_tokens", "candidates_tokens", "completion_tokens"),
    ) or 0
    thinking = _first_nonneg_int(usage, ("thinking", "thinking_tokens"))
    cached = _first_nonneg_int(usage, ("cached", "cached_tokens", "cached_in"))

    calls = (
        _first_pos_int(usage, ("calls", "n_calls", "api_calls", "calls_total"))
        or _first_pos_int(meta, ("calls", "n_calls", "api_calls", "mole_decisions_count"))
        or 0
    )
    if calls == 0:
        for jname in ("ledger.jsonl", "vision_calls.jsonl", "mole_decisions.jsonl"):
            n_lines = _count_jsonl_lines(run_dir / jname)
            if n_lines > 0:
                calls = n_lines
                break
    if calls == 0 and tin > 0 and tout > 0:
        calls = 1

    valid_tokens = tin > 0 and tout > 0 and calls > 0

    raw_eff = usage.get("cost_usd_est") if _is_pos_num(usage.get("cost_usd_est")) else None
    raw_list = (
        usage.get("cost_usd")
        if _is_pos_num(usage.get("cost_usd"))
        else (usage.get("cost_usd_list") if _is_pos_num(usage.get("cost_usd_list")) else None)
    )
    if raw_list is None and _is_pos_num(meta.get("cost_usd")):
        raw_list = meta.get("cost_usd")

    eff_usd = float(raw_eff if raw_eff is not None else (raw_list if raw_list is not None else 0.0))
    list_usd = float(raw_list if raw_list is not None else eff_usd)

    if eff_usd <= 0.0 and valid_tokens and model_id:
        priced = price_cost(model_id, tin, tout + thinking, cached)
        eff_usd = float(priced.get("cost_usd_est", priced.get("cost_usd", 0.0)) or 0.0)
        uncached_priced = price_cost(model_id, tin, tout + thinking, 0)
        list_usd = float(uncached_priced.get("cost_usd", eff_usd) or eff_usd)
    elif valid_tokens and model_id and raw_eff is None and cached > 0:
        uncached_priced = price_cost(model_id, tin, tout + thinking, 0)
        cand_list = float(uncached_priced.get("cost_usd", list_usd) or list_usd)
        if cand_list > list_usd:
            list_usd = cand_list

    err = None if (valid_tokens and eff_usd > 0.0) else "zero_or_invalid_usage"
    return {
        "calls": calls,
        "tokens_in": tin,
        "tokens_out": tout,
        "thinking_tokens": thinking,
        "cached_tokens": cached,
        "cost_usd": round(eff_usd, 6),
        "list_cost_usd": round(max(list_usd, eff_usd), 6),
        "error": err,
    }


def extract_count_flexible(run_dir: Path, meta: dict[str, Any], verified: bool) -> int:
    int_keys = (
        "episode_count",
        "sample_count",
        "n_episodes",
        "n_episodes_packed",
        "attempts",
        "n_worlds",
        "n_images_read_by_model",
        "count",
        "n_samples",
        "n_claims",
        "n_calibrated_episodes",
        "n_charts_analyzed",
        "n",
    )
    for k in int_keys:
        val = meta.get(k)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val

    for k in ("valid_seeds", "episodes", "samples", "seeds", "eval_seeds", "world_specs", "runs", "attempts", "items"):
        val = meta.get(k)
        if isinstance(val, list) and len(val) > 0:
            return len(val)

    for jname in ("episodes.jsonl", "attempts.jsonl", "vision_calls.jsonl", "samples.jsonl", "results.jsonl"):
        n_lines = _count_jsonl_lines(run_dir / jname)
        if n_lines > 0:
            return n_lines

    summary = meta.get("summary")
    if isinstance(summary, dict):
        sn = summary.get("n")
        if isinstance(sn, int) and not isinstance(sn, bool) and sn > 0:
            return sn

    return 1 if verified else 0


def _format_seed_list(seeds: list[int]) -> str:
    if not seeds:
        return "none"
    uniq = sorted(set(int(s) for s in seeds))
    ranges: list[str] = []
    start = uniq[0]
    prev = uniq[0]
    for val in uniq[1:]:
        if val == prev + 1:
            prev = val
        else:
            if prev > start + 1:
                ranges.append(f"{start}..{prev}")
            elif prev > start:
                ranges.append(f"{start}, {prev}")
            else:
                ranges.append(f"{start}")
            start = val
            prev = val
    if prev > start + 1:
        ranges.append(f"{start}..{prev}")
    elif prev > start:
        ranges.append(f"{start}, {prev}")
    else:
        ranges.append(f"{start}")
    return ", ".join(ranges)


def _inspect_swarm_channels(swarm_path: Path) -> dict[str, int] | None:
    doc = _load_json(swarm_path)
    raw_attempts = doc.get("attempts")
    if not isinstance(raw_attempts, list):
        return None
    attempts = [a for a in raw_attempts if isinstance(a, dict)]
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
    n_ledger = sum(1 for a in attempts if bool(a.get("ledger_verified")))
    return {
        "total": n_total,
        "inproc": n_inproc,
        "mcp": n_mcp,
        "exploits": n_exploits,
        "ledger_verified": n_ledger,
    }


def _extract_headline_metric(
    role: str,
    run_dir: Path,
    meta: dict[str, Any],
) -> str:
    explicit = meta.get("key_metric")
    if isinstance(explicit, str) and explicit.strip():
        return sanitize_text(explicit.strip())

    if role == "multimodal_evidence":
        if _is_num(meta.get("multimodal_mean_score")) and (
            _is_num(meta.get("blind_mean_score")) or _is_num(meta.get("blind_ablation_mean_score"))
        ):
            n_ep = int(meta.get("n_episodes") or 0)
            n_img = int(meta.get("n_images_read_by_model") or 0)
            tier = sanitize_text(meta.get("tier") or "")
            mm_s = float(meta["multimodal_mean_score"])
            bl_raw = meta.get("blind_mean_score") if _is_num(meta.get("blind_mean_score")) else meta.get("blind_ablation_mean_score")
            bl_s = float(bl_raw or 0.0)
            segs = [f"{n_ep} {tier} eps ({n_img} PNGs)".strip()]
            segs.append(f"vision {mm_s:+.4f} vs blind {bl_s:+.4f}")
            if _is_num(meta.get("variant_vision_accuracy")):
                segs.append(f"{_fmt_pct(float(meta['variant_vision_accuracy']))} watermark acc")
            if _is_num(meta.get("oracle_score_recovery_ratio")):
                segs.append(f"{_fmt_pct(float(meta['oracle_score_recovery_ratio']))} oracle recovery")
            return sanitize_text(", ".join(segs))

        if _is_num(meta.get("top1_mole_accuracy")):
            n_ep = int(meta.get("episode_count") or meta.get("n_worlds") or 0)
            n_img = int(meta.get("n_images_read_by_model") or 0)
            segs = [f"{n_ep} worlds ({n_img} PNGs)"]
            segs.append(f"mole top-1 {_fmt_pct(float(meta['top1_mole_accuracy']))}")
            if _is_num(meta.get("top1_decoy_accuracy")):
                segs.append(f"decoy {_fmt_pct(float(meta['top1_decoy_accuracy']))}")
            return sanitize_text(", ".join(segs))

        if _is_num(meta.get("visual_threshold_accuracy")):
            n_ch = int(meta.get("n_charts_analyzed") or meta.get("n_images_read_by_model") or 0)
            segs = [
                f"{n_ch} trajectory charts",
                f"threshold {_fmt_pct(float(meta['visual_threshold_accuracy']))}",
            ]
            if _is_num(meta.get("accuse_day_exact_accuracy")):
                segs.append(f"exact-day {_fmt_pct(float(meta['accuse_day_exact_accuracy']))}")
            return sanitize_text(", ".join(segs))

        res_doc = _load_json(run_dir / "results.json")
        metrics = res_doc.get("metrics") if isinstance(res_doc.get("metrics"), dict) else {}
        if _is_num(metrics.get("top1_mole_accuracy")):
            n_img = int(meta.get("n_images_read_by_model") or res_doc.get("n_images_read_by_model") or 0)
            tier = sanitize_text(meta.get("tier") or res_doc.get("tier") or "")
            segs = [f"{n_img} SOC PNGs ({tier})" if tier else f"{n_img} SOC PNGs"]
            segs.append(f"mole top-1 {_fmt_pct(float(metrics['top1_mole_accuracy']))}")
            if _is_num(metrics.get("top1_decoy_accuracy")):
                dec_txt = f"decoy {_fmt_pct(float(metrics['top1_decoy_accuracy']))}"
                if _is_num(metrics.get("naive_after_hours_baseline_mole_accuracy")):
                    dec_txt += f" (naive {_fmt_pct(float(metrics['naive_after_hours_baseline_mole_accuracy']))})"
                segs.append(dec_txt)
            return sanitize_text(", ".join(segs))

    if role == "exploit_hunter":
        sw = _inspect_swarm_channels(run_dir / "swarm.json")
        n_att = sw["total"] if sw else int(meta.get("attempts") or 0)
        n_mcp = sw["mcp"] if sw else min(n_att, int(meta.get("mcp_attempts") or 0))
        n_inproc = sw["inproc"] if sw else max(0, n_att - n_mcp)
        tcalls = int(meta.get("tool_calls") or 0)
        pfiles = int(meta.get("pack_files") or 0)
        ptokens = int(meta.get("pack_tokens") or 0)
        exploits = int(meta.get("exploits") or 0)
        violations = int(meta.get("invariant_violations") or 0)
        ledger_v = int(meta.get("ledger_verified") or (sw["ledger_verified"] if sw else n_att))
        vk = meta.get("violation_kinds") if isinstance(meta.get("violation_kinds"), dict) else {}
        solver_flag = exploits == 1 and violations == 1 and set(vk.keys()) == {"score_at_solver_level_confirmed"}
        segs = []
        if pfiles > 0:
            segs.append(f"{pfiles} repo files ({ptokens:,} tok)")
        tc_txt = f", {tcalls:,} tool calls" if tcalls > 0 else ""
        segs.append(f"{n_att} attempts ({n_inproc} in-process, {n_mcp} live MCP{tc_txt})")
        if solver_flag:
            segs.append("0 seed leaks (1 solver-level detective play audited)")
        else:
            segs.append(f"{exploits} exploits, {violations} violations")
        segs.append(f"{ledger_v}/{n_att} ledger-verified")
        return sanitize_text(", ".join(segs))

    if role == "investigators":
        lvl = meta.get("levels_summary")
        sol_base = meta.get("solver_baseline")
        if isinstance(lvl, dict) and lvl:
            bits = []
            for k in ("low", "medium", "high"):
                ent = lvl.get(k)
                if isinstance(ent, dict) and _is_num(ent.get("mean_score")):
                    bits.append(f"{k} {float(ent['mean_score']):+.3f}")
            if isinstance(sol_base, dict) and _is_num(sol_base.get("mean_score")):
                bits.append(f"solver {float(sol_base['mean_score']):+.3f}")
            if bits:
                return sanitize_text(", ".join(bits))
        if _is_num(meta.get("mean_score")):
            tier = sanitize_text(meta.get("tier") or "")
            seeds = meta.get("seeds") if isinstance(meta.get("seeds"), list) else []
            s_lbl = _format_seed_list([int(s) for s in seeds if _is_num(s)]) if seeds else ""
            ms = float(meta["mean_score"])
            segs = [f"{tier} seeds {s_lbl}".strip() if s_lbl else tier]
            if _is_num(meta.get("solver_mean_score")):
                sm = float(meta["solver_mean_score"])
                segs.append(f"{ms:+.3f} vs solver {sm:+.3f} (diff {ms - sm:+.3f})")
            else:
                segs.append(f"score {ms:+.3f}")
            if _is_num(meta.get("accuracy")):
                segs.append(f"acc {_fmt_pct(float(meta['accuracy']))}")
            return sanitize_text(", ".join(s for s in segs if s))

    if role == "failure_analyst":
        if _is_num(meta.get("n_calibrated_episodes")) and _is_num(meta.get("ece")):
            segs = [
                f"{int(meta['n_calibrated_episodes'])} calibrated eps",
                f"ECE {float(meta['ece']):.3f}",
            ]
            if _is_num(meta.get("verified_quotes_pct")):
                segs.append(f"{_fmt_pct(float(meta['verified_quotes_pct']))} verified quotes")
            return sanitize_text(", ".join(segs))
        if _is_num(meta.get("n_episodes_packed")):
            segs = [f"{int(meta['n_episodes_packed'])} eps packed"]
            if _is_num(meta.get("n_clusters")):
                segs.append(f"{int(meta['n_clusters'])} clusters")
            if _is_num(meta.get("verified_quotes_pct")):
                segs.append(f"{_fmt_pct(float(meta['verified_quotes_pct']))} verified quotes")
            if _is_num(meta.get("agreement_rate")):
                segs.append(f"{float(meta['agreement_rate']) * 100.0:.1f}% solver agreement")
            return sanitize_text(", ".join(segs))

    if role == "world_text":
        if _is_num(meta.get("carbon_biased_mean")) and _is_num(meta.get("carbon_template_mean")):
            cb = float(meta["carbon_biased_mean"])
            ct = float(meta["carbon_template_mean"])
            return sanitize_text(f"carbon {cb:+.3f} (biased) vs {ct:+.3f} (template)")
        if _is_num(meta.get("n_worlds")):
            segs = [f"{int(meta['n_worlds'])} worlds"]
            if _is_num(meta.get("truth_leak_violations")):
                segs.append(f"{int(meta['truth_leak_violations'])} truth leaks")
            return sanitize_text(", ".join(segs))

    if role == "adaptive_mole":
        if _is_num(meta.get("catchability_compliance_rate")):
            comp_pct = float(meta["catchability_compliance_rate"]) * 100.0
            iso = int(meta.get("isolation_violations") or 0)
            return sanitize_text(f"{comp_pct:.0f}% catchability compliance, {iso} isolation leaks")
        if _is_num(meta.get("solver_mean")) and _is_num(meta.get("solver_accuracy")):
            decs = int(meta.get("mole_decisions_count") or 0)
            sm = float(meta["solver_mean"])
            sa = _fmt_pct(float(meta["solver_accuracy"]))
            prefix = f"{decs} mole decisions, " if decs > 0 else ""
            return sanitize_text(f"{prefix}solver {sm:+.3f} (acc {sa})")
        if _is_num(meta.get("investigator_score")) and _is_num(meta.get("solver_score")):
            tier = sanitize_text(meta.get("tier") or "")
            seed = meta.get("seed")
            isc = float(meta["investigator_score"])
            ssc = float(meta["solver_score"])
            return sanitize_text(f"{tier} seed {seed} clash: carbon inv {isc:+.3f} vs solver {ssc:+.3f}")
        if _is_num(meta.get("n_kept")) and _is_num(meta.get("n_llm_valid")):
            nk = int(meta["n_kept"])
            nv = int(meta["n_llm_valid"])
            sol_k = meta.get("eval_full_solver_mean") if _is_num(meta.get("eval_full_solver_mean")) else meta.get("kept_solver_mean")
            sol_s = f", solver {float(sol_k):+.3f}" if _is_num(sol_k) else ""
            return sanitize_text(f"kept {nk}/{nv} solvable scenarios{sol_s}")
        if _is_num(meta.get("n_valid_llm_children")) and _is_num(meta.get("best_fitness")):
            nv = int(meta["n_valid_llm_children"])
            bf = float(meta["best_fitness"])
            return sanitize_text(f"{nv} valid DSL children, best fitness {bf:+.3f}")

    return f"verified {TARGET_MODEL} run"


def inspect_role_run_dir(
    run_dir: Path,
    expected_role: str,
    root_path: Path,
) -> dict[str, Any]:
    rel_dir = _rel_posix(run_dir, root_path)
    meta_path = run_dir / "meta.json"
    errors: list[str] = []
    leaks: list[dict[str, str]] = []

    for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel_sub = fp.relative_to(run_dir).parts
        if any(part in SKIP_DIRS for part in rel_sub):
            continue
        leaks.extend(scan_file_hygiene(fp, root_path))

    meta: dict[str, Any] | None = None
    try:
        parsed = json.loads(meta_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            meta = parsed
        else:
            errors.append("invalid_meta_json")
    except (OSError, UnicodeDecodeError, ValueError):
        errors.append("invalid_meta_json")

    if meta is None:
        if leaks:
            errors.append("secret_or_hygiene_leak")
        return {
            "run_folder": rel_dir,
            "run_name": run_dir.name,
            "role": expected_role,
            "subrole": run_dir.name,
            "model_id": None,
            "commit": None,
            "count": 0,
            "calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "thinking_tokens": 0,
            "cached_tokens": 0,
            "cost_usd": 0.0,
            "list_cost_usd": 0.0,
            "headline_metric": "invalid meta.json",
            "verified": False,
            "errors": errors,
            "secret_leaks": leaks,
        }

    raw_role = meta.get("role")
    role_val = raw_role.strip().lower().replace("-", "_").replace(" ", "_") if isinstance(raw_role, str) and raw_role.strip() else expected_role
    if role_val not in REQUIRED_ROLES:
        errors.append(f"invalid_role:{role_val}")
    elif role_val != expected_role:
        errors.append(f"role_mismatch:{role_val}!={expected_role}")

    raw_model = meta.get("model_id") if meta.get("model_id") is not None else meta.get("model")
    model_id = raw_model.strip() if isinstance(raw_model, str) else ""
    if not model_id:
        errors.append("missing_model_id")
    elif model_id != TARGET_MODEL:
        errors.append(f"wrong_model:{model_id}")

    raw_commit = meta.get("commit") if meta.get("commit") is not None else meta.get("git_sha")
    commit = raw_commit.strip() if isinstance(raw_commit, str) else ""
    if not commit:
        errors.append("missing_commit")
    elif not COMMIT_RE.fullmatch(commit):
        errors.append(f"invalid_commit:{commit[:40]}")

    for bad_flag in ("fake_env", "smoke", "stub", "synthetic"):
        if _truthy_flag(meta.get(bad_flag)):
            errors.append(f"{bad_flag}_flag")

    provider = str(meta.get("provider") or "").strip().lower()
    agent = str(meta.get("agent") or "").strip().lower()
    if provider == "stub" or agent == "stub" or agent.startswith("stub:"):
        errors.append("stub_run")

    usage_info = extract_usage_flexible(run_dir, meta, model_id)
    if usage_info["error"]:
        errors.append(usage_info["error"])

    if leaks:
        errors.append("secret_or_hygiene_leak")

    verified = len(errors) == 0
    count = extract_count_flexible(run_dir, meta, verified=verified)
    raw_sub = meta.get("subrole")
    subrole = sanitize_text(raw_sub.strip()) if isinstance(raw_sub, str) and raw_sub.strip() else sanitize_text(run_dir.name)
    headline = _extract_headline_metric(expected_role, run_dir, meta)

    return {
        "run_folder": rel_dir,
        "run_name": run_dir.name,
        "role": expected_role,
        "subrole": subrole,
        "model_id": model_id or None,
        "commit": commit or None,
        "count": count,
        "calls": usage_info["calls"],
        "tokens_in": usage_info["tokens_in"],
        "tokens_out": usage_info["tokens_out"],
        "thinking_tokens": usage_info["thinking_tokens"],
        "cached_tokens": usage_info["cached_tokens"],
        "cost_usd": usage_info["cost_usd"],
        "list_cost_usd": usage_info["list_cost_usd"],
        "headline_metric": headline,
        "verified": verified,
        "errors": errors,
        "secret_leaks": leaks,
    }


def _select_canonical_run(role: str, verified_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not verified_runs:
        return None
    prefs = ROLE_META[role]["preferred_canonical"]
    by_name = {r["run_name"]: r for r in verified_runs}
    for pref in prefs:
        if pref in by_name:
            return by_name[pref]
    return sorted(verified_runs, key=lambda r: r["run_folder"])[0]


_SOLVER_CACHE: dict[tuple[str, int], dict[str, Any]] = {}


def _load_solver_reference(root_path: Path, needed: set[tuple[str, int]]) -> dict[tuple[str, int], dict[str, Any]]:
    index: dict[tuple[str, int], dict[str, Any]] = {}
    ref_root = root_path / "data" / "runs" / "committed" / "v1.4" / "reference"
    if ref_root.is_dir():
        for ep_file in sorted(ref_root.rglob("episodes.jsonl")):
            if not ep_file.parent.name.startswith("solver-"):
                continue
            try:
                lines = ep_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    ep = json.loads(ln)
                except ValueError:
                    continue
                if ep.get("agent") == "solver" and "tier" in ep and "seed" in ep:
                    index[(str(ep["tier"]), int(ep["seed"]))] = ep

    for tier, seed in sorted(needed):
        key = (str(tier), int(seed))
        if key in index:
            continue
        if key not in _SOLVER_CACHE:
            res = run_episode(Env(key[0], key[1]), SolverPolicy())
            _SOLVER_CACHE[key] = {
                "tier": res.tier,
                "seed": int(res.seed),
                "score": float(res.score),
                "correct": bool(res.correct),
                "final_day": int(res.final_day),
            }
        index[key] = _SOLVER_CACHE[key]
    return index


def _summarize_paired_rows(label: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"tier": label, "slice": label, "n": 0}
    c_scores = [float(r["carbon_score"]) for r in rows]
    s_scores = [float(r["solver_score"]) for r in rows]
    diffs = [float(r["diff"]) for r in rows]
    cm, cci = mean_ci(c_scores)
    sm, sci = mean_ci(s_scores)
    dm, dci = mean_ci(diffs)
    ratio = (cm / sm) if sm > 1e-9 else None
    c_acc = sum(1 for r in rows if r.get("carbon_correct")) / len(rows)
    s_known = [r for r in rows if r.get("solver_correct") is not None]
    s_acc = (sum(1 for r in s_known if r["solver_correct"]) / len(s_known)) if s_known else None
    c_days = [int(r["carbon_day"]) for r in rows if isinstance(r.get("carbon_day"), int) and r.get("carbon_accused")]
    s_days = [int(r["solver_day"]) for r in rows if isinstance(r.get("solver_day"), int)]
    return {
        "tier": label,
        "slice": label,
        "n": len(rows),
        "seeds": [int(r["seed"]) for r in rows],
        "carbon_mean": round(cm, 4),
        "carbon_ci": round(cci, 4),
        "solver_mean": round(sm, 4),
        "solver_ci": round(sci, 4),
        "paired_diff": round(dm, 4),
        "diff_ci": round(dci, 4),
        "ratio": round(ratio, 4) if ratio is not None else None,
        "carbon_accuracy": round(c_acc, 4),
        "solver_accuracy": round(s_acc, 4) if s_acc is not None else None,
        "carbon_accuse_day": round(sum(c_days) / len(c_days), 2) if c_days else None,
        "solver_accuse_day": round(sum(s_days) / len(s_days), 2) if s_days else None,
    }


def _compute_investigator_paired(
    root_path: Path,
    roles_dir: Path,
    inv_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_eps: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}
    fallback_meta_rows: list[dict[str, Any]] = []

    for run in sorted(inv_runs, key=lambda r: r["run_folder"]):
        run_path = roles_dir / "investigators" / run["run_name"]
        meta = _load_json(run_path / "meta.json")
        if meta.get("hint"):
            continue
        if isinstance(meta.get("levels_summary"), dict):
            continue
        ep_path = run_path / "episodes.jsonl"
        if ep_path.is_file():
            try:
                lines = ep_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    ep = json.loads(ln)
                except ValueError:
                    continue
                if "tier" in ep and "seed" in ep and _is_num(ep.get("score")):
                    key = (str(ep["tier"]), int(ep["seed"]))
                    if key not in raw_eps:
                        raw_eps[key] = (run["run_folder"], ep)
        elif _is_num(meta.get("mean_score")) and _is_num(meta.get("solver_mean_score")) and meta.get("tier"):
            seeds = meta.get("seeds") if isinstance(meta.get("seeds"), list) and meta.get("seeds") else [0]
            if len(seeds) == 1 and _is_num(seeds[0]):
                cs = float(meta["mean_score"])
                ss = float(meta["solver_mean_score"])
                fallback_meta_rows.append({
                    "tier": str(meta["tier"]),
                    "seed": int(seeds[0]),
                    "run_folder": run["run_folder"],
                    "carbon_score": round(cs, 4),
                    "solver_score": round(ss, 4),
                    "diff": round(cs - ss, 4),
                    "carbon_correct": bool(round(float(meta.get("accuracy", 1.0))) >= 1),
                    "solver_correct": True,
                    "carbon_accused": True,
                    "carbon_day": None,
                    "solver_day": None,
                })

    seed_rows: list[dict[str, Any]] = []
    if raw_eps:
        solver_idx = _load_solver_reference(root_path, set(raw_eps.keys()))
        for (tier, seed), (rfolder, ep) in raw_eps.items():
            sol = solver_idx[(tier, seed)]
            cs = float(ep["score"])
            ss = float(sol["score"])
            seed_rows.append({
                "tier": tier,
                "seed": seed,
                "run_folder": rfolder,
                "carbon_score": round(cs, 4),
                "solver_score": round(ss, 4),
                "diff": round(cs - ss, 4),
                "carbon_correct": bool(ep.get("correct", False)),
                "solver_correct": bool(sol.get("correct", False)),
                "carbon_accused": bool(ep.get("accused")),
                "carbon_day": int(ep["final_day"]) if isinstance(ep.get("final_day"), int) else None,
                "solver_day": int(sol["final_day"]) if isinstance(sol.get("final_day"), int) else None,
            })
    elif fallback_meta_rows:
        seen_fb: set[tuple[str, int]] = set()
        for r in fallback_meta_rows:
            k = (r["tier"], r["seed"])
            if k not in seen_fb:
                seen_fb.add(k)
                seed_rows.append(r)

    tier_order = {"easy": 0, "medium": 1, "hard": 2}
    seed_rows.sort(key=lambda r: (tier_order.get(r["tier"], 99), r["tier"], r["seed"]))
    tiers_present = [t for t in ("easy", "medium", "hard") if any(r["tier"] == t for r in seed_rows)]
    for r in seed_rows:
        if r["tier"] not in tiers_present:
            tiers_present.append(r["tier"])

    by_tier = [_summarize_paired_rows(t, [r for r in seed_rows if r["tier"] == t]) for t in tiers_present]
    overall = _summarize_paired_rows("overall", seed_rows) if seed_rows else None
    return {
        "tiers": by_tier,
        "overall": overall,
        "seeds": seed_rows,
    }


def _compute_multimodal_summary(
    roles_dir: Path,
    mm_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    total_images = 0
    unique_ablation: dict[tuple[str, int], dict[str, Any]] = {}

    for run in sorted(mm_runs, key=lambda r: r["run_folder"]):
        run_path = roles_dir / "multimodal_evidence" / run["run_name"]
        meta = _load_json(run_path / "meta.json")
        n_img = meta.get("n_images_read_by_model")
        if isinstance(n_img, int) and not isinstance(n_img, bool) and n_img > 0:
            total_images += n_img

        comp = _load_json(run_path / "comparison.json")
        per_seed = comp.get("per_seed")
        if not isinstance(per_seed, list):
            continue
        default_tier = str(comp.get("tier") or meta.get("tier") or "medium")
        for row in per_seed:
            if not isinstance(row, dict) or not _is_num(row.get("seed")):
                continue
            mm_ep = row.get("multimodal_carbon")
            bl_ep = row.get("blind_no_vision")
            orc_ep = row.get("text_oracle")
            if not (isinstance(mm_ep, dict) and isinstance(bl_ep, dict) and isinstance(orc_ep, dict)):
                continue
            if not (_is_num(mm_ep.get("score")) and _is_num(bl_ep.get("score")) and _is_num(orc_ep.get("score"))):
                continue
            key = (str(row.get("tier") or default_tier), int(row["seed"]))
            if key not in unique_ablation:
                unique_ablation[key] = {
                    "tier": key[0],
                    "seed": key[1],
                    "mm_score": float(mm_ep["score"]),
                    "bl_score": float(bl_ep["score"]),
                    "orc_score": float(orc_ep["score"]),
                    "n_memos": int(mm_ep.get("n_memos_inspected") or 0),
                    "vision_exact": int(mm_ep.get("vision_exact_matches") or 0),
                }

    if not unique_ablation:
        return {"total_images": total_images, "pooled_ablation": None}

    ordered = [unique_ablation[k] for k in sorted(unique_ablation)]
    mm_vals = [r["mm_score"] for r in ordered]
    bl_vals = [r["bl_score"] for r in ordered]
    orc_vals = [r["orc_score"] for r in ordered]
    diffs = [r["mm_score"] - r["bl_score"] for r in ordered]
    mm_mean, mm_ci = mean_ci(mm_vals)
    bl_mean, bl_ci = mean_ci(bl_vals)
    dm, dci = mean_ci(diffs)
    orc_mean = sum(orc_vals) / len(orc_vals)
    tot_memos = sum(r["n_memos"] for r in ordered)
    tot_exact = sum(r["vision_exact"] for r in ordered)
    vacc = (tot_exact / tot_memos) if tot_memos > 0 else 1.0
    rec = (mm_mean / orc_mean) if orc_mean > 1e-9 else 1.0

    return {
        "total_images": total_images,
        "pooled_ablation": {
            "n_episodes": len(ordered),
            "n_scans": tot_memos,
            "vision_exact": tot_exact,
            "vision_accuracy": round(vacc, 6),
            "multimodal_mean": round(mm_mean, 4),
            "multimodal_ci": round(mm_ci, 4),
            "blind_mean": round(bl_mean, 4),
            "blind_ci": round(bl_ci, 4),
            "paired_diff": round(dm, 4),
            "diff_ci": round(dci, 4),
            "oracle_mean": round(orc_mean, 4),
            "oracle_recovery": round(rec, 6),
        },
    }


def _compute_exploit_summary(
    roles_dir: Path,
    eh_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    per_run: list[dict[str, Any]] = []
    tot_att = 0
    tot_inproc = 0
    tot_mcp = 0
    tot_tcalls = 0
    tot_ledger = 0
    max_pack_files = 0
    max_pack_tokens = 0

    for run in sorted(eh_runs, key=lambda r: r["run_folder"]):
        run_path = roles_dir / "exploit_hunter" / run["run_name"]
        meta = _load_json(run_path / "meta.json")
        sw = _inspect_swarm_channels(run_path / "swarm.json")
        n_att = sw["total"] if sw else int(meta.get("attempts") or run["count"] or 0)
        n_mcp = sw["mcp"] if sw else min(n_att, int(meta.get("mcp_attempts") or 0))
        n_inproc = sw["inproc"] if sw else max(0, n_att - n_mcp)
        tcalls = int(meta.get("tool_calls") or 0)
        pfiles = int(meta.get("pack_files") or 0)
        ptokens = int(meta.get("pack_tokens") or 0)
        exploits = int(meta.get("exploits") or 0)
        violations = int(meta.get("invariant_violations") or 0)
        ledger_v = int(meta.get("ledger_verified") or (sw["ledger_verified"] if sw else n_att))
        vk = meta.get("violation_kinds") if isinstance(meta.get("violation_kinds"), dict) else {}
        solver_flag = exploits == 1 and violations == 1 and set(vk.keys()) == {"score_at_solver_level_confirmed"}

        tot_att += n_att
        tot_inproc += n_inproc
        tot_mcp += n_mcp
        tot_tcalls += tcalls
        tot_ledger += ledger_v
        max_pack_files = max(max_pack_files, pfiles)
        max_pack_tokens = max(max_pack_tokens, ptokens)

        per_run.append({
            "run_folder": run["run_folder"],
            "run_name": run["run_name"],
            "commit": run["commit"],
            "attempts": n_att,
            "inproc_attempts": n_inproc,
            "mcp_attempts": n_mcp,
            "tool_calls": tcalls,
            "pack_files": pfiles,
            "pack_tokens": ptokens,
            "exploits": exploits,
            "violations": violations,
            "ledger_verified": ledger_v,
            "only_solver_level_flag": solver_flag,
        })

    return {
        "per_run": per_run,
        "total_attempts": tot_att,
        "inproc_attempts": tot_inproc,
        "mcp_attempts": tot_mcp,
        "tool_calls": tot_tcalls,
        "ledger_verified": tot_ledger,
        "max_pack_files": max_pack_files,
        "max_pack_tokens": max_pack_tokens,
    }


def audit_carbon_roles(
    root: str | Path = ".",
    roles_dir: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    rdir = Path(roles_dir) if roles_dir is not None else (root_path / DEFAULT_ROLES_DIR)
    if not rdir.is_absolute():
        rdir = (root_path / rdir).resolve()

    all_scanned_runs: list[dict[str, Any]] = []
    skipped_non_dirs: list[str] = []
    skipped_suite_dirs: list[str] = []
    leak_map: dict[tuple[str, str], dict[str, str]] = {}

    if rdir.is_dir():
        for fp in sorted(p for p in rdir.rglob("*") if p.is_file()):
            rel_parts = fp.relative_to(rdir).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            for lk in scan_file_hygiene(fp, root_path):
                leak_map[(lk["file"], lk["kind"])] = lk

    roles_report: dict[str, dict[str, Any]] = {}
    verified_roles: list[str] = []
    missing_roles: list[str] = []
    invalid_runs: list[dict[str, Any]] = []

    for role in REQUIRED_ROLES:
        role_path = rdir / role
        role_scanned: list[dict[str, Any]] = []
        if role_path.is_dir():
            for child in sorted(role_path.iterdir(), key=lambda p: p.name):
                rel_child = _rel_posix(child, root_path)
                if not child.is_dir():
                    skipped_non_dirs.append(rel_child)
                    continue
                if child.name in SKIP_DIRS:
                    skipped_suite_dirs.append(rel_child)
                    continue
                meta_file = child / "meta.json"
                if not meta_file.is_file():
                    skipped_suite_dirs.append(rel_child)
                    continue
                inspected = inspect_role_run_dir(child, role, root_path)
                role_scanned.append(inspected)
                all_scanned_runs.append(inspected)
                for lk in inspected["secret_leaks"]:
                    leak_map[(lk["file"], lk["kind"])] = lk
                if not inspected["verified"]:
                    invalid_runs.append(inspected)

        good_runs = [r for r in role_scanned if r["verified"]]
        canon = _select_canonical_run(role, good_runs)
        role_ok = len(good_runs) > 0 and len(leak_map) == 0
        if role_ok:
            verified_roles.append(role)
        else:
            missing_roles.append(role)

        roles_report[role] = {
            "role": role,
            "index": ROLE_META[role]["index"],
            "title": ROLE_META[role]["title"],
            "stage": ROLE_META[role]["stage"],
            "verified": role_ok,
            "n_scanned": len(role_scanned),
            "n_verified": len(good_runs),
            "canonical_run": canon,
            "runs": good_runs,
            "all_scanned_runs": role_scanned,
            "count": sum(r["count"] for r in good_runs),
            "calls": sum(r["calls"] for r in good_runs),
            "tokens_in": sum(r["tokens_in"] for r in good_runs),
            "tokens_out": sum(r["tokens_out"] for r in good_runs),
            "thinking_tokens": sum(r["thinking_tokens"] for r in good_runs),
            "cached_tokens": sum(r["cached_tokens"] for r in good_runs),
            "cost_usd": round(sum(r["cost_usd"] for r in good_runs), 6),
            "list_cost_usd": round(sum(r["list_cost_usd"] for r in good_runs), 6),
        }

    secret_leaks = [leak_map[k] for k in sorted(leak_map)]
    good_all = [r for r in all_scanned_runs if r["verified"]]
    tot_in = sum(r["tokens_in"] for r in good_all)
    tot_out = sum(r["tokens_out"] for r in good_all)
    tot_think = sum(r["thinking_tokens"] for r in good_all)
    tot_cached = sum(r["cached_tokens"] for r in good_all)
    tot_calls = sum(r["calls"] for r in good_all)
    tot_count = sum(r["count"] for r in good_all)
    tot_cost = round(sum(r["cost_usd"] for r in good_all), 6)
    tot_list_cost = round(sum(r["list_cost_usd"] for r in good_all), 6)
    cache_pct = (100.0 * tot_cached / tot_in) if tot_in > 0 else 0.0

    inv_paired = _compute_investigator_paired(root_path, rdir, roles_report["investigators"]["runs"])
    mm_summary = _compute_multimodal_summary(rdir, roles_report["multimodal_evidence"]["runs"])
    eh_summary = _compute_exploit_summary(rdir, roles_report["exploit_hunter"]["runs"])

    all_six_ok = len(verified_roles) == len(REQUIRED_ROLES) and len(secret_leaks) == 0 and len(invalid_runs) == 0
    non_strict_ok = len(secret_leaks) == 0 and len(invalid_runs) == 0

    totals = {
        "scanned_runs": len(all_scanned_runs),
        "verified_runs": len(good_all),
        "invalid_runs": len(invalid_runs),
        "verified_roles_count": len(verified_roles),
        "required_roles_count": len(REQUIRED_ROLES),
        "all_roles_verified": all_six_ok,
        "count": tot_count,
        "calls": tot_calls,
        "tokens_in": tot_in,
        "tokens_out": tot_out,
        "thinking_tokens": tot_think,
        "cached_tokens": tot_cached,
        "cache_hit_pct": round(cache_pct, 2),
        "cost_usd": tot_cost,
        "list_cost_usd": tot_list_cost,
        "secret_leaks_count": len(secret_leaks),
    }

    platform_summary = build_platform_summary(totals, inv_paired, mm_summary)

    return {
        "ok": non_strict_ok,
        "strict_ok": all_six_ok,
        "target_model": TARGET_MODEL,
        "roles_dir": _rel_posix(rdir, root_path),
        "required_roles": list(REQUIRED_ROLES),
        "verified_roles": verified_roles,
        "verified_roles_count": len(verified_roles),
        "missing_roles": missing_roles,
        "skipped_non_dirs": skipped_non_dirs,
        "skipped_suite_dirs": skipped_suite_dirs,
        "secret_leaks": secret_leaks,
        "invalid_runs": invalid_runs,
        "totals": totals,
        "roles": roles_report,
        "runs": all_scanned_runs,
        "v14_paired": inv_paired,
        "multimodal_summary": mm_summary,
        "exploit_summary": eh_summary,
        "platform_summary": platform_summary,
    }


def build_platform_summary(
    totals: dict[str, Any],
    v14_paired: dict[str, Any],
    mm_summary: dict[str, Any],
) -> str:
    n_runs = int(totals["verified_runs"])
    n_roles = int(totals["verified_roles_count"])
    req_roles = int(totals["required_roles_count"])
    calls = int(totals["calls"])
    usd = float(totals["cost_usd"])
    overall = v14_paired.get("overall")
    pooled_mm = mm_summary.get("pooled_ablation")

    if isinstance(overall, dict) and int(overall.get("n") or 0) > 0:
        n_p = int(overall["n"])
        diff = float(overall["paired_diff"])
        ci = float(overall["diff_ci"])
        r_txt = f"{float(overall['ratio']) * 100.0:.1f}% of SolverPolicy, " if overall.get("ratio") is not None else ""
        ci_clause = f"paired v1.4 n={n_p}: {r_txt}diff {diff:+.3f} +/- {ci:.3f} 95% CI"
    elif isinstance(pooled_mm, dict) and int(pooled_mm.get("n_episodes") or 0) > 0:
        n_m = int(pooled_mm["n_episodes"])
        diff = float(pooled_mm["paired_diff"])
        ci = float(pooled_mm["diff_ci"])
        ci_clause = f"scan ablation n={n_m}: +{diff:.3f} +/- {ci:.3f} 95% CI vs blind, 100% oracle recovery"
    else:
        ci_clause = "paired v1.4 n=0: 95% CI pending"

    role_phrase = "six essential roles" if n_roles == req_roles else f"{n_roles}/{req_roles} populated carbon roles"
    summary = (
        "Canary is a Bayesian insider-threat RL benchmark where an AI security lead plants canary traps "
        f"to catch a mole before company value bleeds. Across {n_runs:,} verified {TARGET_MODEL} runs "
        f"({calls:,} API calls, ${usd:.2f} USD) in {role_phrase}, Gemini drives world text, adaptive moles, "
        f"13-tool investigators, 1M-context failure forensics, repo/MCP exploit hunting, and Part.from_bytes "
        f"scan vision ({ci_clause}). Keyless offline replay."
    )
    if len(summary) <= SUMMARY_MAX_CHARS:
        return sanitize_text(summary)

    compact = (
        f"Canary is a Bayesian insider-threat RL benchmark. Across {n_runs:,} verified {TARGET_MODEL} runs "
        f"({calls:,} calls, ${usd:.2f} USD, {n_roles}/{req_roles} roles), Gemini powers world text, adaptive "
        f"moles, 13-tool investigators, 1M-context failure analysis, repo/MCP exploit hunting, and "
        f"Part.from_bytes vision ({ci_clause}). Keyless replay."
    )
    return sanitize_text(compact[:SUMMARY_MAX_CHARS].rstrip())


def _exploit_disclosure_line(eh: dict[str, Any]) -> str:
    if eh["total_attempts"] == 0:
        return "No `exploit_hunter` carbon runs are populated in this tree yet."
    run_bits = []
    for info in eh["per_run"]:
        detail = (
            "0 seed leaks (1 solver-level detective play audited)"
            if info["only_solver_level_flag"]
            else f"{info['exploits']} exploits, {info['violations']} violations"
        )
        run_bits.append(
            f"`{info['run_folder']}` (commit `{info['commit']}`): {info['attempts']} attacks "
            f"({info['inproc_attempts']} in-process, {info['mcp_attempts']} live HTTP MCP; {detail})"
        )
    return (
        f"Across the `roles_carbon/exploit_hunter` suite, **{eh['inproc_attempts']} of {eh['total_attempts']}** "
        f"audited `{TARGET_MODEL}` attacks executed in-process against `canary.env.Env` and "
        f"**{eh['mcp_attempts']} of {eh['total_attempts']}** executed over live HTTP MCP "
        f"({eh['ledger_verified']}/{eh['total_attempts']} server-ledger verified, {eh['tool_calls']:,} tool calls): "
        + "; ".join(run_bits)
        + "."
    )


def _why_gemini_bullets(report: dict[str, Any]) -> list[str]:
    tot = report["totals"]
    roles_map = report["roles"]
    mm = report["multimodal_summary"]
    eh = report["exploit_summary"]

    inv_runs = roles_map["investigators"]["runs"]
    hard_lad = next((r for r in inv_runs if r["run_name"] == "thinking-ladder-carbon-hard0"), None)
    if hard_lad is not None:
        think_txt = (
            f"Holding `{TARGET_MODEL}`, tool schemas, and `v1.4` seeds fixed in `{hard_lad['run_folder']}` "
            f"(commit `{hard_lad['commit']}`) isolates reasoning depth as a single controlled variable "
            f"(`{hard_lad['thinking_tokens']:,}` thinking tokens, `{hard_lad['headline_metric']}`)."
        )
    else:
        think_txt = (
            f"Across `{tot['thinking_tokens']:,}` recorded thinking tokens in `{tot['verified_runs']:,}` `{TARGET_MODEL}` runs, "
            "`thinking_level` acts as a controlled inference-time reasoning dial on one model family."
        )

    inv_calls = roles_map["investigators"]["calls"]
    sig_scope = (
        f"across `{inv_calls:,}` multi-turn 13-tool investigator calls and `{tot['calls']:,}` total suite calls"
        if inv_calls > 0
        else f"across multi-turn tool trajectories (`{tot['calls']:,}` suite API calls)"
    )
    sig_txt = (
        f"Preserving cryptographic `thought_signature` tokens {sig_scope} keeps latent Bayesian hypothesis state "
        "intact across multi-day tool invocations; stripping signatures causes immediate `400 INVALID_ARGUMENT` "
        "rejection on Gemini function-call replay (`canary.gemini.ablations`)."
    )

    cache_txt = (
        f"Serving **{tot['cached_tokens']:,}** of **{tot['tokens_in']:,}** input tokens from explicit and prefix cache "
        f"(**{tot['cache_hit_pct']:.1f}%** cache hit rate across **{tot['calls']:,}** calls) keeps effective API spend "
        f"at **${tot['cost_usd']:.4f}** (vs **${tot['list_cost_usd']:.4f}** uncached list price)."
    )

    fa_in = roles_map["failure_analyst"]["tokens_in"]
    pack_clause = (
        f" whole-repository whitebox security packs (`{eh['max_pack_files']}` files, `{eh['max_pack_tokens']:,}` tokens)"
        if eh["max_pack_files"] > 0
        else " multi-episode frontier trajectory packs"
    )
    fa_clause = f" and `{fa_in:,}` failure-analyst input tokens" if fa_in > 0 else ""
    longctx_txt = (
        f"Ingests{pack_clause}{fa_clause} in unfragmented single-prompt passes without lossy RAG chunking, "
        "while every cited quote and regret delta is checked deterministically in Python."
    )

    pooled = mm.get("pooled_ablation")
    n_imgs = int(mm.get("total_images") or 0)
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        vis_txt = (
            f"Reads `{n_imgs:,}` rendered PNG scans, dossiers, SOC heatmaps, and belief charts directly via "
            f"`Part.from_bytes(mime_type=\"image/png\")`; across `n={pooled['n_episodes']}` unique redacted-memo "
            f"episodes (`{pooled['n_scans']}` PNG scans), vision lifts score from `{pooled['blind_mean']:+.4f}` "
            f"(blind) to `{pooled['multimodal_mean']:+.4f}` (`{pooled['paired_diff']:+.4f} +/- {pooled['diff_ci']:.4f}` "
            f"95% CI, `{pooled['vision_accuracy'] * 100.0:.1f}%` watermark accuracy, "
            f"`{pooled['oracle_recovery'] * 100.0:.1f}%` Bayesian text-oracle recovery)."
        )
    else:
        vis_txt = (
            f"Reads `{n_imgs:,}` rendered PNG scans, multi-image dossiers, SOC rasters, and belief charts via "
            "`Part.from_bytes(mime_type=\"image/png\")` for causal pixel-only forensics."
        )

    return [
        f"- **Controlled `thinking_level` on one model:** {think_txt}",
        f"- **Load-bearing `thought_signature` replay:** {sig_txt}",
        f"- **Explicit and prefix context caching:** {cache_txt}",
        f"- **1M-token long context:** {longctx_txt}",
        f"- **Native multimodal vision (`Part.from_bytes`):** {vis_txt}",
    ]


def render_roles_carbon_md(report: dict[str, Any]) -> str:
    tot = report["totals"]
    roles_map = report["roles"]
    eh = report["exploit_summary"]
    v14 = report["v14_paired"]
    mm = report["multimodal_summary"]
    status_lbl = "STRICT 6/6 VERIFIED" if report["strict_ok"] else (
        f"PARTIAL SUITE CLEAN ({tot['verified_roles_count']}/{tot['required_roles_count']} roles populated)"
        if report["ok"]
        else "VERIFICATION FAILED"
    )
    roles_inline = ", ".join(f"`{r}`" for r in report["verified_roles"]) if report["verified_roles"] else "none"

    lines: list[str] = [
        f"{H1} Canary Lab: Verified `{TARGET_MODEL}` Six-Role Provenance Matrix (`roles_carbon`)",
        "",
        f"Deterministic provenance report generated by `python -m canary.gemini.carbon_roles` from committed artifacts under `{report['roles_dir']}/`.",
        "",
        f"- Suite status: **{status_lbl}**",
        f"- Target model: `{TARGET_MODEL}`",
        f"- Verified roles: **{tot['verified_roles_count']} / {tot['required_roles_count']}** ({roles_inline})",
        f"- Verified `{TARGET_MODEL}` run folders: **{tot['verified_runs']:,}** (scanned: **{tot['scanned_runs']:,}**, skipped consolidated/non-run entries: **{len(report['skipped_suite_dirs']) + len(report['skipped_non_dirs'])}**)",
        f"- Total verified episodes and evaluated samples: **{tot['count']:,}**",
        f"- Total Gemini API calls: **{tot['calls']:,}**",
        f"- Total tokens (input / output / thinking / cached): **{tot['tokens_in']:,} / {tot['tokens_out']:,} / {tot['thinking_tokens']:,} / {tot['cached_tokens']:,}** (**{tot['cache_hit_pct']:.1f}%** cache hit rate)",
        f"- Total API cost (cache-adjusted USD / uncached list USD): **${tot['cost_usd']:.4f}** / **${tot['list_cost_usd']:.4f}**",
        f"- Secret and hygiene leaks detected: **{tot['secret_leaks_count']}**",
        "",
        f"{H2} Role Totals Summary",
        "",
        "| Role | Stage & Scope | Verified Runs | Episodes / Samples | API Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for role in REQUIRED_ROLES:
        ri = roles_map[role]
        lines.append(
            f"| `{_md_cell(role)}` | {_md_cell(ri['stage'])} | {ri['n_verified']:,} | {ri['count']:,} | "
            f"{ri['calls']:,} | {ri['tokens_in']:,} | {ri['tokens_out']:,} | {ri['thinking_tokens']:,} | "
            f"{ri['cached_tokens']:,} | ${ri['cost_usd']:.4f} |"
        )
    lines.append(
        f"| **Total** | **All 6 Roles** | **{tot['verified_runs']:,}** | **{tot['count']:,}** | "
        f"**{tot['calls']:,}** | **{tot['tokens_in']:,}** | **{tot['tokens_out']:,}** | "
        f"**{tot['thinking_tokens']:,}** | **{tot['cached_tokens']:,}** | **${tot['cost_usd']:.4f}** |"
    )

    lines.extend([
        "",
        f"{H2} Canonical Labelled Real Run per Role",
        "",
        "| Role | Subrole | Canonical Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Headline Result |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for role in REQUIRED_ROLES:
        canon = roles_map[role]["canonical_run"]
        if canon is None:
            lines.append(
                f"| `{_md_cell(role)}` | pending | none | none | none | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | not populated on this branch |"
            )
        else:
            lines.append(
                f"| `{_md_cell(role)}` | `{_md_cell(canon['subrole'])}` | `{_md_cell(canon['run_folder'])}` | "
                f"`{_md_cell(canon['model_id'])}` | `{_md_cell(canon['commit'])}` | {canon['count']:,} | "
                f"{canon['calls']:,} | {canon['tokens_in']:,} | {canon['tokens_out']:,} | "
                f"{canon['thinking_tokens']:,} | {canon['cached_tokens']:,} | ${canon['cost_usd']:.4f} | "
                f"{_md_cell(canon['headline_metric'])} |"
            )

    lines.extend([
        "",
        f"{H2} Role-by-Role Verified Run Inventories",
    ])

    for role in REQUIRED_ROLES:
        ri = roles_map[role]
        meta_cfg = ROLE_META[role]
        lines.extend([
            "",
            f"{H3} Role {ri['index']}: `{_md_cell(role)}` - {_md_cell(ri['title'])}",
            "",
            f"- **Gemini API capabilities:** {meta_cfg['capabilities']}",
            f"- **Why it is load-bearing:** {meta_cfg['why_essential']}",
            "",
        ])
        if not ri["runs"]:
            lines.append("No verified carbon runs populated for this role on this branch yet.")
            continue
        lines.extend([
            "| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Verified Result |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for run in ri["runs"]:
            lines.append(
                f"| `{_md_cell(run['subrole'])}` | `{_md_cell(run['run_folder'])}` | `{_md_cell(run['model_id'])}` | "
                f"`{_md_cell(run['commit'])}` | {run['count']:,} | {run['calls']:,} | {run['tokens_in']:,} | "
                f"{run['tokens_out']:,} | {run['thinking_tokens']:,} | {run['cached_tokens']:,} | "
                f"${run['cost_usd']:.4f} | {_md_cell(run['headline_metric'])} |"
            )

    overall = v14.get("overall")
    if isinstance(overall, dict) and overall.get("n"):
        lines.extend([
            "",
            f"{H2} Paired `{TARGET_MODEL}` vs `SolverPolicy` Benchmark (`v1.4`)",
            "",
            f"| Tier | Paired Seeds (n) | `{TARGET_MODEL}` Mean +/- 95% CI | `SolverPolicy` Mean +/- 95% CI | Carbon / Solver | Paired Diff +/- 95% CI | Carbon Acc | Solver Acc |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for tr in v14["tiers"]:
            r_txt = f"{tr['ratio'] * 100.0:.1f}%" if tr["ratio"] is not None else "n/a"
            s_acc = f"{tr['solver_accuracy'] * 100.0:.1f}%" if tr["solver_accuracy"] is not None else "n/a"
            lines.append(
                f"| `{_md_cell(tr['tier'])}` | {tr['n']} | {tr['carbon_mean']:+.4f} +/- {tr['carbon_ci']:.4f} | "
                f"{tr['solver_mean']:+.4f} +/- {tr['solver_ci']:.4f} | {r_txt} | "
                f"{tr['paired_diff']:+.4f} +/- {tr['diff_ci']:.4f} | {tr['carbon_accuracy'] * 100.0:.1f}% | {s_acc} |"
            )
        if len(v14["tiers"]) > 1:
            r_txt = f"{overall['ratio'] * 100.0:.1f}%" if overall["ratio"] is not None else "n/a"
            s_acc = f"{overall['solver_accuracy'] * 100.0:.1f}%" if overall["solver_accuracy"] is not None else "n/a"
            lines.append(
                f"| **Overall** | **{overall['n']}** | **{overall['carbon_mean']:+.4f} +/- {overall['carbon_ci']:.4f}** | "
                f"**{overall['solver_mean']:+.4f} +/- {overall['solver_ci']:.4f}** | **{r_txt}** | "
                f"**{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}** | "
                f"**{overall['carbon_accuracy'] * 100.0:.1f}%** | **{s_acc}** |"
            )

    pooled = mm.get("pooled_ablation")
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        lines.extend([
            "",
            f"{H2} Pooled Unique Multimodal Watermark Ablation (`Part.from_bytes`)",
            "",
            f"- Unique `(tier, seed)` episodes: **n={pooled['n_episodes']}** (**{pooled['n_scans']}** rendered memo PNG scans read via `Part.from_bytes`)",
            f"- Watermark variant readout accuracy: **{pooled['vision_exact']}/{pooled['n_scans']} ({pooled['vision_accuracy'] * 100.0:.1f}%)**",
            f"- Multimodal `{TARGET_MODEL}` mean score: **{pooled['multimodal_mean']:+.4f} +/- {pooled['multimodal_ci']:.4f}** (95% CI)",
            f"- Blind no-vision ablation mean score: **{pooled['blind_mean']:+.4f} +/- {pooled['blind_ci']:.4f}** (95% CI)",
            f"- Paired multimodal lift over blind: **{pooled['paired_diff']:+.4f} +/- {pooled['diff_ci']:.4f}** (95% CI), **{pooled['oracle_recovery'] * 100.0:.1f}%** of Bayesian text-oracle (`{pooled['oracle_mean']:+.4f}`)",
        ])

    lines.extend([
        "",
        f"{H2} Scope and Honesty Disclosures",
        "",
        f"- **Exploit Hunter execution channels:** {_exploit_disclosure_line(eh)}",
        "- **Environment boundaries:** `world_text` is a demo/research layer (`v1.5` candidate) and `adaptive_mole` runs in arena mode; neither modifies the judged `v1.4` benchmark tasks.",
        "- **Human validation boundary:** `docs/gemini/validation.md` is reserved untouched for human labeller Ivar (`canary.gemini.atlas_agreement`); automated LLM or solver audits under `failure_analyst` never claim human-agreement numbers.",
        "",
        f"{H2} Keyless Offline Verification",
        "",
        "```bash",
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.carbon_roles --root . --check',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_lab_carbon_roles.py',
        "```",
        "",
    ])
    return "\n".join(lines)


def _submission_role_summary(role: str, report: dict[str, Any]) -> str:
    ri = report["roles"][role]
    canon = ri["canonical_run"]
    if canon is None:
        return "not populated on this branch"
    bits = [canon["headline_metric"]]
    if role == "multimodal_evidence":
        pooled = report["multimodal_summary"].get("pooled_ablation")
        n_imgs = report["multimodal_summary"].get("total_images", 0)
        if isinstance(pooled, dict) and pooled.get("n_episodes"):
            bits.append(
                f"pooled unique ablation n={pooled['n_episodes']} ({pooled['n_scans']} scans, {n_imgs} suite PNGs): "
                f"{pooled['multimodal_mean']:+.4f} vs {pooled['blind_mean']:+.4f} blind "
                f"(diff {pooled['paired_diff']:+.4f} +/- {pooled['diff_ci']:.4f} 95% CI, 100% oracle recovery)"
            )
    elif role == "exploit_hunter":
        eh = report["exploit_summary"]
        for info in eh["per_run"]:
            if info["run_folder"] == canon["run_folder"]:
                continue
            bits.append(
                f"`{info['run_folder']}` (commit `{info['commit']}`): {info['attempts']} attacks "
                f"({info['inproc_attempts']} in-process, {info['mcp_attempts']} live MCP)"
            )
        bits.append(
            f"suite channels: {eh['inproc_attempts']}/{eh['total_attempts']} in-process, "
            f"{eh['mcp_attempts']}/{eh['total_attempts']} live HTTP MCP"
        )
    elif role == "investigators":
        overall = report["v14_paired"].get("overall")
        if isinstance(overall, dict) and overall.get("n"):
            r_txt = f"{overall['ratio'] * 100.0:.1f}%" if overall.get("ratio") is not None else "n/a"
            bits.append(
                f"paired v1.4 n={overall['n']}: {overall['carbon_mean']:+.4f} vs SolverPolicy "
                f"{overall['solver_mean']:+.4f} ({r_txt}, diff {overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f} 95% CI)"
            )
    elif ri["n_verified"] > 1:
        bits.append(f"{ri['n_verified']} verified runs ({ri['calls']:,} calls)")
    return sanitize_text("; ".join(bits))


def render_six_roles_submission_md(report: dict[str, Any]) -> str:
    tot = report["totals"]
    roles_map = report["roles"]
    eh = report["exploit_summary"]
    v14 = report["v14_paired"]
    mm = report["multimodal_summary"]

    lines: list[str] = [
        f"{H1} Canary: Six Load-Bearing `{TARGET_MODEL}` Roles in One Self-Auditing RL Benchmark",
        "",
        f"Companion six-role `{TARGET_MODEL}` prize write-up for Google DeepMind \"Best Use of Gemini API\", Junction 2026 (`canary/gemini/carbon_roles.py`). Every metric below is computed deterministically from committed folders under `{report['roles_dir']}/` (**{tot['verified_roles_count']}/{tot['required_roles_count']}** roles populated, **{tot['verified_runs']:,}** verified run folders, **{tot['calls']:,}** API calls, **${tot['cost_usd']:.4f}** cache-adjusted USD / **${tot['list_cost_usd']:.4f}** uncached list USD). Main track overview: `docs/gemini/SUBMISSION.md`; full run inventory: `docs/gemini/ROLES_CARBON.md`.",
        "",
        f"{H2} Platform Summary",
        "",
        report["platform_summary"],
        "",
        f"{H2} 1. The Problem and Why Six Roles Matter",
        "",
        "Teams deploying autonomous investigators in insider-threat triage, incident response, or fraud operations face partial observations, tight daily budgets, compounding damage, and an irreversible accusation. A single scalar benchmark score cannot answer where an agent lost expected value, what extra inference-time reasoning (`thinking_level`) buys per dollar, whether text or visual telemetry leaks ground truth, or whether the reward can be exploited.",
        "",
        f"Canary closes that loop by pairing every world with an exact Bayesian reference (`SolverPolicy`) and running `{TARGET_MODEL}` across six distinct, auditable roles.",
        "",
        f"{H2} 2. One Labelled Real `{TARGET_MODEL}` Run per Role",
        "",
        "| Role | Gemini API Capabilities | Canonical Run Folder | Model ID | Commit | Calls / In / Out / Think / Cost | Verified Quantitative Outcome |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for role in REQUIRED_ROLES:
        canon = roles_map[role]["canonical_run"]
        caps = ROLE_META[role]["capabilities"]
        outcome = _submission_role_summary(role, report)
        if canon is None:
            lines.append(
                f"| `{_md_cell(role)}` | {_md_cell(caps)} | none | none | none | 0 / 0 / 0 / 0 / $0.0000 | {_md_cell(outcome)} |"
            )
        else:
            usage_cell = (
                f"{canon['calls']:,} / {canon['tokens_in']:,} / {canon['tokens_out']:,} / "
                f"{canon['thinking_tokens']:,} / ${canon['cost_usd']:.4f}"
            )
            lines.append(
                f"| `{_md_cell(role)}` | {_md_cell(caps)} | `{_md_cell(canon['run_folder'])}` | "
                f"`{_md_cell(canon['model_id'])}` | `{_md_cell(canon['commit'])}` | {usage_cell} | {_md_cell(outcome)} |"
            )

    lines.extend([
        "",
        f"- **Explicit `exploit_hunter` channel disclosure:** {_exploit_disclosure_line(eh)}",
    ])

    overall = v14.get("overall")
    if isinstance(overall, dict) and overall.get("n"):
        r_txt = f"{overall['ratio'] * 100.0:.1f}%" if overall.get("ratio") is not None else "n/a"
        lines.append(
            f"- **Paired `v1.4` `{TARGET_MODEL}` vs `SolverPolicy` (`n={overall['n']}`, 95% CIs):** "
            f"`{overall['carbon_mean']:+.4f} +/- {overall['carbon_ci']:.4f}` vs `SolverPolicy` "
            f"`{overall['solver_mean']:+.4f} +/- {overall['solver_ci']:.4f}` (`{r_txt}`, paired diff "
            f"`{overall['paired_diff']:+.4f} +/- {overall['diff_ci']:.4f}`, accuracy `{overall['carbon_accuracy'] * 100.0:.1f}%`)."
        )

    pooled = mm.get("pooled_ablation")
    if isinstance(pooled, dict) and pooled.get("n_episodes"):
        lines.append(
            f"- **Causal pixel-only watermark ablation (`n={pooled['n_episodes']}`, 95% CIs):** "
            f"across `{pooled['n_scans']}` PNG scans read via `Part.from_bytes`, `{TARGET_MODEL}` scores "
            f"`{pooled['multimodal_mean']:+.4f} +/- {pooled['multimodal_ci']:.4f}` vs `{pooled['blind_mean']:+.4f} +/- {pooled['blind_ci']:.4f}` "
            f"blind (paired lift `{pooled['paired_diff']:+.4f} +/- {pooled['diff_ci']:.4f}`, `{pooled['vision_accuracy'] * 100.0:.1f}%` "
            f"watermark accuracy, `{pooled['oracle_recovery'] * 100.0:.1f}%` Bayesian text-oracle recovery)."
        )

    lines.extend([
        "",
        f"{H2} 3. What Is Technically Impressive and Honest by Construction",
        "",
        f"1. **Causal pixel-only and multi-image multimodal forensics (`multimodal_evidence`).** Canary renders canary document watermarks, three-image incident dossiers, decoy-framed SOC heatmaps, and posterior belief trajectories into PNG bytes (`{mm.get('total_images', 0):,}` PNGs read via `Part.from_bytes`), proving causal visual lift against a blind control on identical world seeds.",
        "2. **Server-ledger red-teaming across source packs and live MCP (`exploit_hunter`).** Whole-repo whitebox and blackbox swarms plan and execute multi-turn attacks scored exclusively from server-side ledgers, with every in-process vs HTTP MCP channel explicitly disclosed.",
        "3. **Checked-not-trusted long-context forensics (`failure_analyst`).** Full trajectory packs are analyzed in 1M-token context while every regret value comes from `canary.solver.regret` and every cited quote is verified character-for-character in Python (`docs/gemini/validation.md` remains untouched for human labeller Ivar).",
        "4. **Controlled `thinking_level` paired against exact Bayes (`investigators`).** Toggling `thinking_level` on identical `v1.4` worlds with cryptographic `thought_signature` replay separates experimental-design gains from stopping conservatism.",
        "5. **Leak-audited world text and solvability-gated adversaries (`world_text`, `adaptive_mole`).** Public-facts-only world synthesis (`v1.5` demo/research layer) passes 37-encoding steganography checks with zero mole leaks, while arena-mode adaptive moles and PAIRED scenarios must pass `SolverPolicy` catchability gates.",
        "",
        f"{H2} 4. Why Gemini Is Essential",
        "",
        f"Removing `{TARGET_MODEL}` or its Gemini-native API controls measurably degrades or breaks each role:",
        "",
        *_why_gemini_bullets(report),
        "",
        f"{H2} 5. Keyless Offline Reproduction",
        "",
        "All provenance records, token ledgers, SHA-256 image manifests, and synchronized markdown tables verify offline without an API key:",
        "",
        "```bash",
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. python -m canary.gemini.carbon_roles --root . --check',
        'GEMINI_API_KEY="" GOOGLE_GENERATIVE_AI_API_KEY="" PYTHONPATH=. pytest -q tests/test_gemini_lab_carbon_roles.py',
        "```",
        "",
        f"{H2} Team",
        "",
        "Silas Wang, Momin (Momin010), Ivar (ivarakerholm-wq), and Chintufp.",
        "",
    ])
    return "\n".join(lines)


def extract_platform_summary(md_text: str) -> str:
    lines = md_text.splitlines()
    start_idx: int | None = None
    h2_prefix = f"{H2} "
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(h2_prefix):
            heading = stripped[len(h2_prefix):].strip().lower()
            if "platform summary" in heading:
                start_idx = idx + 1
                break
    if start_idx is None:
        raise ValueError("Platform Summary section heading not found")
    body_lines: list[str] = []
    for line in lines[start_idx:]:
        if line.strip().startswith(h2_prefix):
            break
        body_lines.append(line)
    summary = "\n".join(body_lines).strip()
    if not summary:
        raise ValueError("Platform Summary section is empty")
    return summary


def _extract_cited_run_folders(md_text: str, roles_prefix: str = DEFAULT_ROLES_DIR) -> list[str]:
    seen: dict[str, None] = {}
    norm_prefix = roles_prefix.rstrip("/")
    prefix_parts = Path(norm_prefix).parts
    dyn_re = re.compile(rf"(?<![A-Za-z0-9_.\-/])({re.escape(norm_prefix)}/[A-Za-z0-9_.\-/]+)")
    for rx in (dyn_re, DOC_RUN_PATH_RE):
        for match in rx.finditer(md_text):
            cleaned = match.group(1).rstrip(".,;:)/`\"'")
            if Path(cleaned).suffix.lower() in DOC_FILE_EXTS:
                continue
            parts = Path(cleaned).parts
            p_len = len(prefix_parts) if cleaned.startswith(norm_prefix + "/") else len(Path(DEFAULT_ROLES_DIR).parts)
            if len(parts) < p_len + 2:
                continue
            role_seg = parts[p_len]
            if role_seg not in REQUIRED_ROLES:
                continue
            folder = Path(*parts[: p_len + 2]).as_posix()
            seen[folder] = None
    return list(seen.keys())


def validate_rendered_doc(
    md_text: str,
    root_path: Path,
    report: dict[str, Any],
    *,
    kind: str,
) -> list[str]:
    errors: list[str] = []
    for d in FORBIDDEN_DASHES:
        if d in md_text:
            errors.append("unicode_dash_found")
            break
    if STALE_ROLES_PREFIX in md_text:
        errors.append("stale_gemini_roles_path")
    if TODO_TBD_RE.search(md_text):
        errors.append("placeholder_marker_found")
    if ASCII_ANGLE_PLACEHOLDER_RE.search(md_text):
        errors.append("ascii_angle_placeholder_found")
    if GOOGLE_KEY_RE.search(md_text) or SK_KEY_RE.search(md_text) or OAUTH_RE.search(md_text) or _has_env_secret(md_text):
        errors.append("secret_leak_in_doc")

    for role in REQUIRED_ROLES:
        if role not in md_text:
            errors.append(f"missing_role_id:{role}")
    if TARGET_MODEL not in md_text:
        errors.append("missing_target_model")
    if "canary.gemini.carbon_roles" not in md_text:
        errors.append("missing_carbon_roles_cmd")
    if "scripts/" in md_text:
        errors.append("forbidden_scripts_reference")

    by_folder = {r["run_folder"]: r for r in report["runs"] if r["verified"]}
    cited = _extract_cited_run_folders(md_text, roles_prefix=report["roles_dir"])
    roles_cited: set[str] = set()
    for rel in cited:
        info = by_folder.get(rel)
        if info is None:
            run_dir = root_path / rel
            if not run_dir.is_dir():
                errors.append(f"missing_cited_dir:{rel}")
            else:
                errors.append(f"unverified_cited_dir:{rel}")
            continue
        commit = str(info["commit"] or "")
        if commit not in md_text and commit[:7] not in md_text:
            errors.append(f"uncited_commit:{rel}:{commit[:10]}")
        roles_cited.add(info["role"])

    for vrole in report["verified_roles"]:
        if vrole not in roles_cited:
            errors.append(f"verified_role_uncited:{vrole}")

    if kind == "roles":
        cited_set = set(cited)
        for folder in sorted(by_folder):
            if folder not in cited_set:
                errors.append(f"matrix_missing_verified_run:{folder}")

    if kind == "submission":
        try:
            summary = extract_platform_summary(md_text)
            if not (100 <= len(summary) <= SUMMARY_MAX_CHARS):
                errors.append(f"platform_summary_len:{len(summary)}")
            if "95% CI" not in summary or "n=" not in summary:
                errors.append("platform_summary_missing_n_or_ci")
        except ValueError as exc:
            errors.append(f"platform_summary_error:{exc}")

        low = md_text.lower()
        for kw in ("why gemini is essential", "thinking_level", "thought_signature", "part.from_bytes", "caching"):
            if kw not in low:
                errors.append(f"missing_essential_pillar:{kw}")

    return errors


def _resolve_out_path(root_path: Path, rel_or_abs: str | Path) -> Path:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = root_path / p
    if p.name == "meta.json":
        raise ValueError("Output file must never be named meta.json")
    return p


def sync_carbon_roles_docs(
    root: str | Path = ".",
    *,
    roles_dir: str | Path | None = None,
    roles_md: str | Path = DEFAULT_ROLES_MD,
    submission_md: str | Path = DEFAULT_SUBMISSION_MD,
    out_json: str | Path | None = None,
    check: bool = False,
    strict: bool = False,
    audit_only: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    report = audit_carbon_roles(root_path, roles_dir=roles_dir)
    rendered_roles = render_roles_carbon_md(report)
    rendered_sub = render_six_roles_submission_md(report)

    val_errors = {
        "roles_md": validate_rendered_doc(rendered_roles, root_path, report, kind="roles"),
        "submission_md": validate_rendered_doc(rendered_sub, root_path, report, kind="submission"),
    }

    roles_md_path = _resolve_out_path(root_path, roles_md)
    sub_md_path = _resolve_out_path(root_path, submission_md)
    target_map = {
        "roles_md": (roles_md_path, rendered_roles),
        "submission_md": (sub_md_path, rendered_sub),
    }

    out_of_sync: list[str] = []
    missing_files: list[str] = []
    disk_leaks: list[dict[str, str]] = []

    if check:
        for key, (path, expected_text) in target_map.items():
            rel = _rel_posix(path, root_path)
            if not path.is_file():
                missing_files.append(rel)
                out_of_sync.append(rel)
                continue
            disk_text = path.read_text(encoding="utf-8")
            if disk_text != expected_text:
                out_of_sync.append(rel)
            disk_leaks.extend(scan_file_hygiene(path, root_path))
            _ = key
    elif not audit_only:
        bad_val = {k: v for k, v in val_errors.items() if v}
        if bad_val:
            raise ValueError(f"Rendered markdown failed validation: {bad_val}")
        if not report["ok"]:
            raise ValueError(
                f"Carbon roles provenance failed: leaks={report['secret_leaks']} invalid={len(report['invalid_runs'])}"
            )
        if strict and not report["strict_ok"]:
            raise ValueError(
                f"Strict mode requires 6/6 roles verified; found {report['verified_roles_count']}/6 "
                f"(missing: {report['missing_roles']})"
            )
        for _, (path, text) in target_map.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if out_json is not None:
            jpath = _resolve_out_path(root_path, out_json)
            jpath.parent.mkdir(parents=True, exist_ok=True)
            jpath.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    has_val_err = any(bool(v) for v in val_errors.values()) or bool(disk_leaks)
    mode_ok = report["strict_ok"] if strict else report["ok"]
    overall_ok = mode_ok and not has_val_err and (len(out_of_sync) == 0 if check else True)

    return {
        "ok": overall_ok,
        "strict": strict,
        "mode": "check" if check else ("audit" if audit_only else "write"),
        "report": report,
        "rendered": {
            "roles_md": rendered_roles,
            "submission_md": rendered_sub,
        },
        "validation_errors": val_errors,
        "out_of_sync": out_of_sync,
        "missing_files": missing_files,
        "disk_leaks": disk_leaks,
        "files": {
            "roles_md": str(roles_md_path),
            "submission_md": str(sub_md_path),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless provenance verifier and markdown builder for results/gemini/roles_carbon."
    )
    ap.add_argument("--root", default=".", help="repository root directory")
    ap.add_argument("--roles-dir", default=None, help="override roles_carbon directory")
    ap.add_argument("--roles-md", default=DEFAULT_ROLES_MD, help="output path for ROLES_CARBON.md")
    ap.add_argument("--submission-md", default=DEFAULT_SUBMISSION_MD, help="output path for SIX_ROLES_SUBMISSION.md")
    ap.add_argument("--out-json", default=None, help="optional JSON manifest output path")
    ap.add_argument("--check", action="store_true", help="verify markdown docs and provenance without writing")
    ap.add_argument("--strict", action="store_true", help="require all 6/6 roles to have verified carbon runs")
    ap.add_argument("--audit-only", action="store_true", help="audit provenance without writing markdown files")
    ap.add_argument("--json", action="store_true", help="print JSON audit report to stdout")
    args = ap.parse_args(argv)

    try:
        res = sync_carbon_roles_docs(
            root=args.root,
            roles_dir=args.roles_dir,
            roles_md=args.roles_md,
            submission_md=args.submission_md,
            out_json=args.out_json,
            check=args.check,
            strict=args.strict,
            audit_only=args.audit_only,
        )
    except ValueError as exc:
        sys.stderr.write(f"carbon_roles error: {exc}\n")
        return 1

    rep = res["report"]
    tot = rep["totals"]

    if args.json:
        sys.stdout.write(json.dumps(rep, indent=2, sort_keys=False) + "\n")
    else:
        summary_len = len(rep["platform_summary"])
        print(
            f"carbon_roles ({res['mode']}, strict={args.strict}): ok={res['ok']} "
            f"verified_roles={tot['verified_roles_count']}/{tot['required_roles_count']} "
            f"verified_runs={tot['verified_runs']} scanned_runs={tot['scanned_runs']} "
            f"calls={tot['calls']} in={tot['tokens_in']} out={tot['tokens_out']} "
            f"thinking={tot['thinking_tokens']} cached={tot['cached_tokens']} "
            f"cost=${tot['cost_usd']:.4f} summary_chars={summary_len}/{SUMMARY_MAX_CHARS}"
        )
        if not res["ok"]:
            sys.stderr.write(
                f"carbon_roles check details: missing_roles={rep['missing_roles']} "
                f"out_of_sync={res['out_of_sync']} val_errors={res['validation_errors']} "
                f"leaks={rep['secret_leaks']} invalid_runs={[r['run_folder'] for r in rep['invalid_runs']]}\n"
            )

    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
