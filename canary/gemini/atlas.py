from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import datetime as dt
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

from canary import rules
from canary.analysis.tags import to_result
from canary.baselines import BASELINES, CALIBRATION_POLICIES
from canary.gemini.ledger import LedgeredClient, lab_client
from canary.rules import (
    HELDOUT_SEEDS,
    JUDGE_SEEDS,
    TIERS_HISTORY,
    TIERS_VERSION,
    tier_params_for_episode,
)
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute
from canary.types import EpisodeResult
from canary.world import generate_world

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS = ROOT / "data" / "runs" / "committed"
DEFAULT_OUT = ROOT / "results" / "gemini"
FEATURE = "atlas"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_LLM = f"gemini:{DEFAULT_MODEL}"

SKIP_DIRS = frozenset({"superseded", "_invalid", "_ledger"})
SCRIPTED_AGENTS = frozenset({"solver", *BASELINES.keys(), *CALIBRATION_POLICIES.keys()})

SECRET_RE = re.compile(
    r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
    r"(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|api[_-]?key|token|secret)"
    r"\s*[=:][ \t]*[^\s\"',;]+)"
)

RULE_TAGS: tuple[str, ...] = (
    "premature_accusation",
    "uninformative_canary",
    "budget_waste",
    "ignored_delay",
    "over_restriction",
    "decoy_chase",
    "no_accusation",
    "late_commit",
)

TAG_SPECS: dict[str, dict[str, str]] = {
    "premature_accusation": {
        "id": "premature-accusation",
        "name": "Premature accusation under ambiguity",
        "decision": "accuse",
        "description": (
            "Commits to accuse before canary leaks and access logs isolate a suspect above the "
            "rational Bayesian break-even threshold 1/(1+V)."
        ),
    },
    "uninformative_canary": {
        "id": "uninformative-canary",
        "name": "Uninformative canary splits",
        "decision": "plant_canary",
        "description": (
            "Deploys low-entropy canary variants on tiny pairs or skewed recipient groups that "
            "fail to bisect the active suspect posterior."
        ),
    },
    "budget_waste": {
        "id": "budget-waste",
        "name": "Action budget waste and limit overruns",
        "decision": "search_messages",
        "description": (
            "Spends daily investigative slots on repeated or failing tool calls, hitting action "
            "limits and delaying high-information canary tests."
        ),
    },
    "ignored_delay": {
        "id": "ignored-delay",
        "name": "Ignored leak propagation delay",
        "decision": "accuse",
        "description": (
            "Accuses a suspect while recently planted canaries remain inside the multi-day leak "
            "surfacing window and could still exonerate or confirm candidates."
        ),
    },
    "over_restriction": {
        "id": "over-restriction",
        "name": "Over-restriction of low-posterior staff",
        "decision": "restrict_access",
        "description": (
            "Restricts employees whose Bayesian posterior is near zero, incurring daily value "
            "costs while suppressing diagnostic canary exposure."
        ),
    },
    "decoy_chase": {
        "id": "decoy-chase",
        "name": "Chases the hostile decoy",
        "decision": "restrict_access",
        "description": (
            "Treats hostile decoy messages or framed after-hours access logs as decisive proof "
            "and restricts or accuses the innocent decoy."
        ),
    },
    "no_accusation": {
        "id": "no-accusation",
        "name": "Horizon expiration without accusation",
        "decision": "(no accusation)",
        "description": (
            "Reaches the final day horizon or global tool-call cap without issuing an accusation "
            "even when accumulated evidence yields positive expected value."
        ),
    },
    "late_commit": {
        "id": "late-commit",
        "name": "Commits too late after decisive posterior",
        "decision": "advance_day",
        "description": (
            "Keeps advancing days and running redundant checks after the Bayesian posterior is "
            "already decisive, losing company value V to ongoing leaks."
        ),
    },
}

TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "premature_accusation": ("premature", "early", "ambig", "guess", "threshold", "gamble"),
    "uninformative_canary": ("canary", "wide", "narrow", "variant", "split", "partition", "gini"),
    "budget_waste": ("budget", "waste", "limit", "redundant", "repeat", "quota", "overrun"),
    "ignored_delay": ("delay", "pending", "propagation", "window", "surface"),
    "over_restriction": ("over-restrict", "over_restrict", "lockdown", "restrict"),
    "decoy_chase": ("decoy", "hostile", "angry", "frame", "framed"),
    "no_accusation": ("no-accusation", "no_accusation", "abstain", "horizon", "timeout", "unaccused"),
    "late_commit": ("late-commit", "late_commit", "too late", "waits", "hesitat", "over-test"),
}

ATLAS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Concise synthesis of failure modes across the packed trajectory corpus (plain ASCII hyphens only).",
        },
        "modes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "decision": {"type": "string"},
                    "rule_tag": {
                        "type": "string",
                        "enum": [*RULE_TAGS, "other"],
                    },
                    "episode_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "quotes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "episode": {"type": "string"},
                                "t": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                            "required": ["episode", "t", "quote"],
                        },
                    },
                },
                "required": ["id", "name", "description", "decision", "rule_tag", "episode_keys", "quotes"],
            },
        },
    },
    "required": ["summary", "modes"],
}

SYSTEM_PROMPT = (
    "You are the Canary Lab Failure Analyst. You receive a full trajectory corpus of insider-threat "
    "investigations packed with deterministic Bayesian solver regret tags (canary.solver.regret.attribute) "
    "and accusation-time posteriors.\n"
    "Cluster the agent mistakes into 4 to 6 distinct failure modes and return strict JSON matching the schema:\n"
    "1. Map each mode to its primary rule_tag from the schema enum and canonical tool decision.\n"
    "2. List all matching episode_keys from the corpus headers (the exact token right after 'EPISODE ').\n"
    "3. Include 2 to 3 quotes per mode. Every quote.episode MUST be an exact episode key from the corpus, "
    "quote.t MUST be the integer step index t on that line, and quote.quote MUST be an exact, unmodified "
    "character-for-character substring copied from inside that episode block (never paraphrase or add '...').\n"
    "4. Use plain ASCII hyphens only; never output unicode em dashes or en dashes."
)


def sanitize_text(val: Any) -> str:
    if val is None:
        return ""
    text = SECRET_RE.sub("[redacted]", str(val))
    return text.replace("\u2014", " - ").replace("\u2013", "-")


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return sanitize_text(obj)
    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {sanitize_text(k): sanitize_obj(v) for k, v in obj.items()}
    return obj


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", sanitize_text(text).lower()).strip("-")
    return slug[:48] or "mode"


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


@contextmanager
def tier_context(version: str):
    target = "v1.3" if version == "v1.2" else version
    if target != TIERS_VERSION and target not in TIERS_HISTORY:
        target = TIERS_VERSION
    old_kv = rules.KNOWN_V_MODE
    with rules.tiers_version(target):
        rules.KNOWN_V_MODE = version != "v1.2"
        try:
            yield
        finally:
            rules.KNOWN_V_MODE = old_kv


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
        return str(meta["tiers_version"])
    if dir_meta and isinstance(dir_meta.get("tiers_version"), str) and dir_meta["tiers_version"]:
        return str(dir_meta["tiers_version"])
    params = tier_params_for_episode(res.tier, res.steps)
    if res.tier in ("hard", "hard_forge") and params.n_employees == 30:
        return "v1.3"
    if "committed" in all_parts and not any(p.startswith("v1.") for p in all_parts):
        return "v1.2"
    return TIERS_VERSION


def compute_accusation_posterior(res: EpisodeResult, version: str) -> dict[str, Any]:
    params = tier_params_for_episode(res.tier, res.steps)
    if version in ("v1.2", "v1.3") and res.tier in (TIERS_HISTORY.get("v1.3") or {}):
        has_roster = any(
            st.tool == "list_employees" and isinstance(st.result, dict) and st.result.get("ok")
            for st in res.steps
        )
        if not has_roster:
            params = TIERS_HISTORY["v1.3"][res.tier]
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
    total_mass = sum(clamped.values())
    if total_mass > 0.0:
        post = {emp: prob / total_mass for emp, prob in clamped.items()}
    else:
        n_emp = max(1, len(sp.obs.employees))
        post = {emp: 1.0 / n_emp for emp in sp.obs.employees}

    if acc_idx is not None:
        acc_step = res.steps[acc_idx]
        decision_t = int(acc_step.t if acc_step.t is not None else acc_idx)
        decision_day = int(acc_step.day)
        accused = (acc_step.args or {}).get("employee") or res.accused
    else:
        decision_t = len(res.steps)
        decision_day = int(res.final_day)
        accused = res.accused

    meta = res.meta or {}
    if meta.get("V_true") is not None:
        v_true = min(1.0, max(0.0, float(meta["V_true"])))
    elif accused and res.correct and res.score >= 0.0:
        v_true = min(1.0, max(0.0, float(res.score)))
    elif version == "v1.2":
        v_true = min(1.0, max(0.0, float(sp.V)))
    else:
        v_true = min(1.0, max(0.0, float(sp.expected_true_V())))

    wrong_score = float(getattr(params, "wrong_accusation_score", -1.0))
    denom = v_true - wrong_score
    threshold = (-wrong_score / denom) if denom > 0.0 else 1.0
    top_emp = max(post, key=post.get)
    p_top = float(post[top_emp])
    did_accuse = bool(accused)
    p_accused = float(post.get(str(accused), 0.0)) if did_accuse else None
    ev_accuse = (p_accused * v_true + (1.0 - p_accused) * wrong_score) if p_accused is not None else 0.0
    ev_top = p_top * v_true + (1.0 - p_top) * wrong_score
    premature = bool(did_accuse and ev_accuse < -1e-9)

    if not did_accuse:
        verdict = "abstained_missed" if ev_top > 1e-9 else "abstained_rational"
    elif premature:
        verdict = "premature_lucky" if res.correct else "premature_wrong"
    else:
        verdict = "calibrated_correct" if res.correct else "calibrated_unlucky"

    return {
        "decision_t": decision_t,
        "decision_day": decision_day,
        "did_accuse": did_accuse,
        "accused": accused,
        "top_employee": top_emp,
        "p_accused": round(p_accused, 4) if p_accused is not None else None,
        "p_top": round(p_top, 4),
        "v_true": round(v_true, 4),
        "threshold": round(threshold, 4),
        "ev_accuse": round(ev_accuse, 4),
        "premature_commit": premature,
        "verdict": verdict,
    }


def _row_effective_tags(row: dict[str, Any]) -> list[str]:
    tags = [str(t) for t in (row.get("tags") or []) if str(t)]
    if not tags and row.get("action") == "advance_day" and float(row.get("regret") or 0.0) >= 0.02:
        return ["late_commit"]
    return tags


def load_transcript_notes(run_dir: Path, seed: int) -> list[tuple[int, str]]:
    notes: list[tuple[int, str]] = []
    json_fp = run_dir / "transcripts" / f"{seed}.json"
    txt_fp = run_dir / "transcripts" / f"{seed}.txt"
    if json_fp.is_file():
        try:
            items = json.loads(json_fp.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            items = []
        step_idx = 0
        if isinstance(items, list):
            for turn in items:
                if not isinstance(turn, dict):
                    continue
                if turn.get("role") == "assistant":
                    raw = sanitize_text(turn.get("content") or "").strip()
                    if raw:
                        first_line = " ".join(raw.splitlines()[0].split())[:180]
                        if len(first_line) >= 12:
                            notes.append((step_idx, first_line))
                    tcs = turn.get("tool_calls") or []
                    if isinstance(tcs, list):
                        step_idx += len(tcs)
                if len(notes) >= 6:
                    break
    elif txt_fp.is_file():
        try:
            lines = txt_fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for idx, ln in enumerate(lines):
            cleaned = " ".join(sanitize_text(ln).split())[:180]
            if len(cleaned) >= 16 and not cleaned.startswith("{"):
                notes.append((idx, cleaned))
            if len(notes) >= 4:
                break
    return notes


def analyze_episode_record(
    ep_input: EpisodeResult | dict[str, Any],
    index: int,
    rel_parts: tuple[str, ...] = (),
    dir_meta: dict[str, Any] | None = None,
    root_parts: tuple[str, ...] = (),
    transcript_notes: list[tuple[int, str]] | None = None,
) -> dict[str, Any]:
    raw_dict = (
        {
            "tier": ep_input.tier,
            "seed": ep_input.seed,
            "agent": ep_input.agent,
            "steps": [
                {"t": s.t, "day": s.day, "tool": s.tool, "args": s.args, "result": s.result}
                for s in ep_input.steps
            ],
            "score": ep_input.score,
            "accused": ep_input.accused,
            "correct": ep_input.correct,
            "final_day": ep_input.final_day,
            "end_reason": ep_input.end_reason,
            "meta": dict(ep_input.meta or {}),
        }
        if isinstance(ep_input, EpisodeResult)
        else dict(ep_input)
    )

    res = to_result(raw_dict)
    ver = infer_version(res, rel_parts=rel_parts, dir_meta=dir_meta, root_parts=root_parts)

    with tier_context(ver):
        params = tier_params_for_episode(res.tier, res.steps)
        meta_copy = dict(res.meta or {})
        if (
            "decoy" not in meta_copy
            and res.seed not in JUDGE_SEEDS
            and res.seed not in HELDOUT_SEEDS
            and params.decoy
        ):
            try:
                meta_copy["decoy"] = generate_world(res.tier, res.seed, params).decoy
            except Exception:
                pass
        res.meta = meta_copy
        regret_rows = attribute(res)
        posterior_info = compute_accusation_posterior(res, ver)

    explicit_id = raw_dict.get("episode_id")
    key = sanitize_text(explicit_id).strip() if explicit_id else f"{res.agent}/{res.tier}/{res.seed}#{index}"

    rule_tags: set[str] = set()
    tag_regret: dict[str, float] = defaultdict(float)
    total_regret = 0.0
    enriched_rows: list[dict[str, Any]] = []
    for row in regret_rows:
        r_val = float(row.get("regret") or 0.0)
        total_regret += r_val
        eff_tags = _row_effective_tags(row)
        for tg in eff_tags:
            rule_tags.add(tg)
            tag_regret[tg] += r_val
        enriched_rows.append({**row, "effective_tags": eff_tags})

    extra_notes = list(transcript_notes or [])
    inline_notes = raw_dict.get("notes") or (raw_dict.get("meta") or {}).get("notes") or []
    if isinstance(inline_notes, list):
        for n_item in inline_notes[:6]:
            if isinstance(n_item, dict) and n_item.get("quote"):
                extra_notes.append((int(n_item.get("t") or 0), sanitize_text(n_item["quote"]).strip()[:180]))
            elif isinstance(n_item, str) and n_item.strip():
                extra_notes.append((0, sanitize_text(n_item).strip()[:180]))

    return {
        "index": index,
        "key": key,
        "tiers_version": ver,
        "episode": raw_dict,
        "regret_rows": enriched_rows,
        "total_regret": round(total_regret, 6),
        "rule_tags": sorted(rule_tags),
        "tag_regret": {k: round(v, 6) for k, v in tag_regret.items()},
        "posterior": posterior_info,
        "notes": extra_notes,
    }


def records_from_episodes(episodes: Iterable[EpisodeResult | dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ep in episodes:
        if isinstance(ep, dict):
            if (ep.get("meta") or {}).get("valid") is False or ep.get("end_reason") == "error":
                continue
        elif (ep.meta or {}).get("valid") is False or ep.end_reason == "error":
            continue
        out.append(analyze_episode_record(ep, index=len(out)))
    return out


def _expand_run_paths(runs: Sequence[str | Path] | str | Path) -> list[Path]:
    raw_list = [runs] if isinstance(runs, (str, Path)) else list(runs)
    if not raw_list:
        raw_list = [DEFAULT_RUNS]
    expanded: list[Path] = []
    for item in raw_list:
        p = Path(item).expanduser()
        if p.exists():
            expanded.append(p)
            continue
        parts = [seg.strip() for seg in str(item).split(",") if seg.strip()]
        for seg in parts:
            expanded.append(Path(seg).expanduser())
    return expanded


def load_corpus(
    runs: Sequence[str | Path] | str | Path = (DEFAULT_RUNS,),
    include_reference: bool = False,
    max_episodes: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    paths = _expand_run_paths(runs)
    records: list[dict[str, Any]] = []
    ref_candidates: list[tuple[dict[str, Any], tuple[str, ...], dict[str, Any], Path, tuple[str, ...]]] = []
    invalid_skipped = 0
    seen_files: set[Path] = set()

    for base in paths:
        if not base.exists():
            continue
        files = [base] if base.is_file() else sorted(base.rglob("episodes.jsonl"))
        root_parts = base.parts if base.is_dir() else base.parent.parts
        for fp in files:
            resolved = fp.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            rel_parts = () if base.is_file() else fp.relative_to(base).parts[:-1]
            if any(p in SKIP_DIRS or p.endswith("-smoke") for p in rel_parts):
                continue
            dir_meta: dict[str, Any] = {}
            meta_fp = fp.parent / "meta.json"
            if meta_fp.is_file():
                try:
                    parsed_meta = json.loads(meta_fp.read_text(encoding="utf-8", errors="ignore"))
                    if isinstance(parsed_meta, dict):
                        dir_meta = parsed_meta
                except (OSError, json.JSONDecodeError):
                    dir_meta = {}
            for line in fp.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                emeta = d.get("meta") or {}
                if emeta.get("valid") is False or d.get("end_reason") == "error":
                    invalid_skipped += 1
                    continue
                agent_name = str(d.get("agent") or "")
                is_ref = "reference" in rel_parts or agent_name in SCRIPTED_AGENTS
                if is_ref and not include_reference:
                    ref_candidates.append((d, tuple(rel_parts), dir_meta, fp.parent, tuple(root_parts)))
                    continue
                notes = load_transcript_notes(fp.parent, int(d.get("seed") or 0))
                records.append(
                    analyze_episode_record(
                        d,
                        index=len(records),
                        rel_parts=tuple(rel_parts),
                        dir_meta=dir_meta,
                        root_parts=tuple(root_parts),
                        transcript_notes=notes,
                    )
                )
                if max_episodes is not None and len(records) >= max_episodes:
                    return records, invalid_skipped

    if not records and ref_candidates:
        for d, rel_parts, dir_meta, run_dir, root_parts in ref_candidates:
            notes = load_transcript_notes(run_dir, int(d.get("seed") or 0))
            records.append(
                analyze_episode_record(
                    d,
                    index=len(records),
                    rel_parts=rel_parts,
                    dir_meta=dir_meta,
                    root_parts=root_parts,
                    transcript_notes=notes,
                )
            )
            if max_episodes is not None and len(records) >= max_episodes:
                break

    return records, invalid_skipped


def _fmt_step_line(step: dict[str, Any]) -> str:
    t_val = int(step.get("t") if step.get("t") is not None else 0)
    day_val = int(step.get("day") if step.get("day") is not None else 1)
    tool = sanitize_text(step.get("tool") or "")
    args = step.get("args") or {}
    if isinstance(args, dict):
        arg_txt = ",".join(f"{sanitize_text(k)}={sanitize_text(v)}" for k, v in args.items())
    else:
        arg_txt = sanitize_text(args)
    if len(arg_txt) > 120:
        arg_txt = arg_txt[:117] + "..."
    res = step.get("result") or {}
    ok = res.get("ok", True) if isinstance(res, dict) else True
    err = sanitize_text(res.get("error") if isinstance(res, dict) else "")
    brief = "ok" if ok else f"ERR {err}"
    return f"t={t_val} d={day_val} {tool}({arg_txt}) -> {brief}"


def pack_corpus(
    records: list[dict[str, Any]],
    max_steps: int = 36,
    max_chars: int = 900_000,
) -> tuple[str, dict[str, str]]:
    blocks: dict[str, str] = {}
    for rec in records:
        ep = rec["episode"]
        post = rec["posterior"]
        key = rec["key"]
        tags_str = ", ".join(rec["rule_tags"]) if rec["rule_tags"] else "none"
        lines = [
            (
                f"EPISODE {key} tier={ep.get('tier')} seed={ep.get('seed')} agent={ep.get('agent')} "
                f"score={float(ep.get('score') or 0.0):.3f} correct={bool(ep.get('correct'))} "
                f"accused={ep.get('accused')} day={ep.get('final_day')} end={ep.get('end_reason')}"
            ),
            (
                f"posterior: p_accused={post['p_accused']} p_top={post['p_top']} "
                f"top={post['top_employee']} v_true={post['v_true']} "
                f"threshold={post['threshold']} ev_accuse={post['ev_accuse']} verdict={post['verdict']}"
            ),
            f"tags: {tags_str} | total_regret={rec['total_regret']:.3f}",
        ]

        flagged_rows = [
            r
            for r in rec["regret_rows"]
            if float(r.get("regret") or 0.0) > 0.0 or bool(r.get("effective_tags"))
        ]
        flagged_rows.sort(key=lambda r: (-float(r.get("regret") or 0.0), int(r.get("t") or 0)))
        for r in sorted(flagged_rows[:14], key=lambda x: int(x.get("t") or 0)):
            lines.append(
                f"regret t={r.get('t')} d={r.get('day')} {r.get('action')} "
                f"r={float(r.get('regret') or 0.0):.3f} p_best={r.get('p_best')} "
                f"tags={r.get('effective_tags')}"
            )

        raw_steps = list(ep.get("steps") or [])
        keep_indices = set(range(min(len(raw_steps), max_steps)))
        flagged_ts = {int(r.get("t") or 0) for r in flagged_rows[:14]}
        for idx, st in enumerate(raw_steps):
            st_dict = st if isinstance(st, dict) else {}
            st_t = int(st_dict.get("t") if st_dict.get("t") is not None else idx)
            if st_t in flagged_ts or st_dict.get("tool") in ("accuse", "restrict_access"):
                keep_indices.add(idx)
        if raw_steps:
            keep_indices.add(len(raw_steps) - 1)

        ordered_idx = sorted(keep_indices)
        for pos, idx in enumerate(ordered_idx):
            if pos > 0 and idx > ordered_idx[pos - 1] + 1:
                skipped = idx - ordered_idx[pos - 1] - 1
                lines.append(f"... {skipped} intermediate steps omitted")
            st_item = raw_steps[idx]
            st_dict = (
                st_item
                if isinstance(st_item, dict)
                else {"t": st_item.t, "day": st_item.day, "tool": st_item.tool, "args": st_item.args, "result": st_item.result}
            )
            lines.append(_fmt_step_line(st_dict))

        for note_t, note_txt in rec.get("notes") or []:
            clean_note = sanitize_text(note_txt).replace("\n", " ").strip()
            if clean_note:
                lines.append(f"note t={int(note_t)}: {clean_note}")

        blocks[key] = sanitize_text("\n".join(lines))

    packed = "\n\n".join(blocks.values())
    if len(packed) > max_chars:
        trimmed_blocks: list[str] = []
        used = 0
        for k, blk in blocks.items():
            sep = 2 if trimmed_blocks else 0
            if used + sep + len(blk) > max_chars and trimmed_blocks:
                break
            trimmed_blocks.append(blk)
            used += sep + len(blk)
        packed = "\n\n".join(trimmed_blocks)
    return packed, blocks


def summarize_corpus_stats(records: list[dict[str, Any]], packed_text: str, invalid_skipped: int = 0) -> dict[str, Any]:
    total_regret = sum(float(r["total_regret"]) for r in records)
    tag_eps: Counter[str] = Counter()
    tag_inst: Counter[str] = Counter()
    tag_reg: Counter[str] = Counter()

    for rec in records:
        seen: set[str] = set()
        for row in rec["regret_rows"]:
            rv = float(row.get("regret") or 0.0)
            for tg in row.get("effective_tags") or []:
                tag_inst[tg] += 1
                tag_reg[tg] += rv
                seen.add(tg)
        for tg in seen:
            tag_eps[tg] += 1

    regret_tags = {
        tg: {
            "episodes": int(tag_eps[tg]),
            "instances": int(tag_inst[tg]),
            "regret_sum": round(float(tag_reg[tg]), 4),
            "regret_share": round(float(tag_reg[tg]) / total_regret, 4) if total_regret > 0.0 else 0.0,
        }
        for tg in sorted(tag_inst, key=lambda k: (-tag_reg[k], -tag_eps[k], k))
    }

    posts = [r["posterior"] for r in records]
    accused_posts = [p for p in posts if p["did_accuse"] and p["p_accused"] is not None]
    n_acc = len(accused_posts)
    n_ep = len(records)

    accusation_posteriors = {
        "accused_episodes": n_acc,
        "abstained_episodes": n_ep - n_acc,
        "mean_p_accused": (
            round(sum(float(p["p_accused"]) for p in accused_posts) / n_acc, 4) if n_acc else None
        ),
        "mean_p_top": round(sum(float(p["p_top"]) for p in posts) / n_ep, 4) if n_ep else None,
        "mean_threshold": round(sum(float(p["threshold"]) for p in posts) / n_ep, 4) if n_ep else None,
        "premature_commits": sum(1 for p in posts if p["premature_commit"]),
        "justified_commits": sum(
            1 for p in posts if p["verdict"] in ("calibrated_correct", "calibrated_unlucky")
        ),
        "lucky_commits": sum(1 for p in posts if p["verdict"] == "premature_lucky"),
    }

    return {
        "episodes": n_ep,
        "invalid_skipped": int(invalid_skipped),
        "chars": len(packed_text),
        "total_regret": round(total_regret, 4),
        "regret_tags": regret_tags,
        "accusation_posteriors": accusation_posteriors,
    }


def _pick_verbatim_quote(rec: dict[str, Any], block: str, tag: str) -> tuple[int, str]:
    lines = [ln for ln in block.splitlines() if ln.strip()]
    for ln in lines:
        if ln.startswith("note t="):
            m = re.match(r"^note t=(\d+):\s*(.+)$", ln)
            if m and m.group(2) in block:
                return int(m.group(1)), m.group(2)
    target_t: int | None = None
    best_r = -1.0
    for row in rec["regret_rows"]:
        if tag in (row.get("effective_tags") or []):
            rv = float(row.get("regret") or 0.0)
            if rv > best_r:
                best_r = rv
                target_t = int(row.get("t") or 0)
    if target_t is not None:
        prefix_reg = f"regret t={target_t} "
        prefix_step = f"t={target_t} "
        for ln in lines:
            if ln.startswith(prefix_step) and len(ln) <= 220:
                return target_t, ln
        for ln in lines:
            if ln.startswith(prefix_reg) and len(ln) <= 220:
                return target_t, ln
    for ln in lines:
        m = re.match(r"^(?:regret )?t=(\d+)\b", ln)
        if m and len(ln) <= 220:
            return int(m.group(1)), ln
    return 0, lines[0][:200] if lines else ""


def build_stub_payload(
    records: list[dict[str, Any]],
    blocks: dict[str, str],
    max_modes: int = 6,
) -> dict[str, Any]:
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tag_reg_totals: Counter[str] = Counter()
    tag_decisions: dict[str, Counter[str]] = defaultdict(Counter)

    for rec in records:
        if rec["key"] not in blocks:
            continue
        for tg in rec["rule_tags"]:
            by_tag[tg].append(rec)
            tag_reg_totals[tg] += float(rec["tag_regret"].get(tg, 0.0))
        for row in rec["regret_rows"]:
            act = str(row.get("action") or "")
            for tg in row.get("effective_tags") or []:
                if act:
                    tag_decisions[tg][act] += 1

    ordered_tags = sorted(
        by_tag,
        key=lambda t: (-float(tag_reg_totals[t]), -len(by_tag[t]), t),
    )[:max_modes]

    modes: list[dict[str, Any]] = []
    for tg in ordered_tags:
        spec = TAG_SPECS.get(
            tg,
            {
                "id": slugify(tg),
                "name": tg.replace("_", " ").title(),
                "decision": "accuse",
                "description": f"Episodes exhibiting solver failure tag {tg}.",
            },
        )
        matched = sorted(
            by_tag[tg],
            key=lambda r: (-float(r["tag_regret"].get(tg, 0.0)), -float(r["total_regret"]), r["index"]),
        )
        ep_keys = [r["key"] for r in by_tag[tg]]
        quotes = []
        for sample_rec in matched[:2]:
            q_t, q_txt = _pick_verbatim_quote(sample_rec, blocks[sample_rec["key"]], tg)
            if q_txt:
                quotes.append({"episode": sample_rec["key"], "t": q_t, "quote": q_txt})
        dec_counts = tag_decisions.get(tg)
        decision = spec["decision"]
        if tg == "budget_waste" and dec_counts:
            decision = dec_counts.most_common(1)[0][0]
        modes.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "description": spec["description"],
                "decision": decision,
                "rule_tag": tg,
                "episode_keys": ep_keys,
                "quotes": quotes,
            }
        )

    if not modes and records:
        first_rec = next((r for r in records if r["key"] in blocks), records[0])
        blk = blocks.get(first_rec["key"], "")
        q_t, q_txt = _pick_verbatim_quote(first_rec, blk, "other")
        modes.append(
            {
                "id": "calibrated-execution",
                "name": "Calibrated baseline execution",
                "description": "Trajectories completed without triggering deterministic solver regret failure tags.",
                "decision": "accuse",
                "rule_tag": "other",
                "episode_keys": [r["key"] for r in records if r["key"] in blocks],
                "quotes": [{"episode": first_rec["key"], "t": q_t, "quote": q_txt}] if q_txt else [],
            }
        )

    n_ok = sum(1 for r in records if r["episode"].get("correct"))
    summary = (
        f"Deterministic atlas synthesis across {len(records)} packed episodes "
        f"({n_ok} correct accusations, {len(modes)} clustered failure modes)."
    )
    return {"summary": summary, "modes": modes}


def resolve_rule_tag(mode: dict[str, Any]) -> str:
    explicit = str(mode.get("rule_tag") or "").strip().lower().replace("-", "_")
    if explicit in RULE_TAGS:
        return explicit
    blob = " ".join(
        str(mode.get(k) or "") for k in ("id", "name", "description", "decision")
    ).lower()
    for tg in RULE_TAGS:
        if tg in blob or tg.replace("_", "-") in blob:
            return tg
    for tg, words in TAG_KEYWORDS.items():
        if any(w in blob for w in words):
            return tg
    dec = str(mode.get("decision") or "").strip().lower()
    if dec in ("canary", "plant_canary"):
        return "uninformative_canary"
    if dec in ("restrict", "restrict_access"):
        return "over_restriction"
    if dec == "advance_day":
        return "late_commit"
    if dec == "(no accusation)":
        return "no_accusation"
    return "other"


def verify_quotes(modes: list[dict[str, Any]], episode_texts: dict[str, str]) -> dict[str, Any]:
    verified_count = 0
    total_count = 0
    unverified: list[dict[str, Any]] = []

    for mode in modes:
        out_quotes: list[dict[str, Any]] = []
        for raw_q in mode.get("quotes") or []:
            if not isinstance(raw_q, dict):
                continue
            total_count += 1
            ep_key = str(raw_q.get("episode") or "").strip()
            raw_quote = str(raw_q.get("quote") or "")
            clean_q = raw_quote.strip()
            t_raw = raw_q.get("t")
            t_val: int | None = None
            if isinstance(t_raw, int) and not isinstance(t_raw, bool):
                t_val = t_raw
            elif isinstance(t_raw, float):
                t_val = int(t_raw)
            else:
                m = re.search(r"\bt=(\d+)\b", clean_q)
                if m:
                    t_val = int(m.group(1))
            src_text = episode_texts.get(ep_key)
            ok = bool(src_text is not None and len(clean_q) > 0 and clean_q in src_text)
            if ok:
                verified_count += 1
            else:
                unverified.append(
                    {
                        "mode": str(mode.get("id") or mode.get("name") or ""),
                        "episode": ep_key,
                        "t": t_val,
                        "quote": sanitize_text(clean_q),
                    }
                )
            out_quotes.append(
                {
                    "episode": sanitize_text(ep_key),
                    "t": t_val if t_val is not None else 0,
                    "quote": sanitize_text(clean_q),
                    "verified": ok,
                }
            )
        mode["quotes"] = out_quotes

    rate = round(verified_count / total_count, 4) if total_count > 0 else 0.0
    return {
        "verified_quotes": verified_count,
        "total_quotes": total_count,
        "rate": rate,
        "pct": round(100.0 * rate, 2),
        "unverified": unverified,
    }


def _claimed_episode_keys(mode: dict[str, Any], valid_keys: set[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for k in mode.get("episode_keys") or []:
        ks = str(k).strip()
        if ks in valid_keys and ks not in seen:
            seen.add(ks)
            ordered.append(ks)
    for q in mode.get("quotes") or []:
        if isinstance(q, dict):
            ks = str(q.get("episode") or "").strip()
            if ks in valid_keys and ks not in seen:
                seen.add(ks)
                ordered.append(ks)
    return ordered


def compute_agreement(
    modes: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {r["key"]: r for r in records}
    valid_keys = set(by_key)
    has_explicit_lists = any(bool(m.get("episode_keys")) for m in modes)

    if has_explicit_lists or not modes:
        eval_records = records
    else:
        quoted_keys = {
            str(q.get("episode") or "").strip()
            for m in modes
            for q in (m.get("quotes") or [])
            if isinstance(q, dict) and str(q.get("episode") or "").strip() in valid_keys
        }
        eval_records = [by_key[k] for k in sorted(quoted_keys)] if quoted_keys else records

    eval_key_set = {r["key"] for r in eval_records}
    rule_pairs: set[tuple[str, str]] = {
        (tg, r["key"]) for r in eval_records for tg in r["rule_tags"]
    }
    rule_by_tag: dict[str, set[str]] = defaultdict(set)
    for tg, k in rule_pairs:
        rule_by_tag[tg].add(k)

    llm_pairs: set[tuple[str, str]] = set()
    llm_by_tag: dict[str, set[str]] = defaultdict(set)
    by_mode: list[dict[str, Any]] = []

    for mode in modes:
        tag = resolve_rule_tag(mode)
        claimed = [k for k in _claimed_episode_keys(mode, valid_keys) if k in eval_key_set]
        claimed_set = set(claimed)
        if tag != "other":
            for k in claimed:
                llm_pairs.add((tag, k))
                llm_by_tag[tag].add(k)
            rule_set = rule_by_tag.get(tag, set())
            overlap = len(claimed_set & rule_set)
            union_n = len(claimed_set | rule_set)
        else:
            dec = str(mode.get("decision") or "").strip()
            matched_clean = {
                k
                for k in claimed
                if not by_key[k]["rule_tags"]
                or any(
                    float(rw.get("regret") or 0.0) > 0.0 and str(rw.get("action") or "") == dec
                    for rw in by_key[k]["regret_rows"]
                )
            }
            for k in claimed:
                if k not in matched_clean:
                    llm_pairs.add(("other", k))
            overlap = len(matched_clean)
            union_n = len(claimed_set)

        by_mode.append(
            {
                "id": str(mode.get("id") or ""),
                "rule_tag": tag,
                "llm_episodes": len(claimed_set),
                "rule_episodes": len(rule_by_tag.get(tag, set())) if tag != "other" else overlap,
                "overlap": overlap,
                "precision": round(overlap / len(claimed_set), 4) if claimed_set else 0.0,
                "jaccard": round(overlap / union_n, 4) if union_n else 1.0,
            }
        )

    union_pairs = rule_pairs | llm_pairs
    inter_pairs = rule_pairs & llm_pairs

    if not union_pairs:
        agree = len(eval_records)
        total = len(eval_records)
        rate = 1.0 if total > 0 else 0.0
        precision = 1.0 if total > 0 else 0.0
        recall = 1.0 if total > 0 else 0.0
        f1 = 1.0 if total > 0 else 0.0
    else:
        agree = len(inter_pairs)
        total = len(union_pairs)
        rate = round(agree / total, 4)
        precision = round(len(inter_pairs) / len(llm_pairs), 4) if llm_pairs else 0.0
        recall = round(len(inter_pairs) / len(rule_pairs), 4) if rule_pairs else 0.0
        f1 = (
            round(2.0 * len(inter_pairs) / (len(llm_pairs) + len(rule_pairs)), 4)
            if (llm_pairs or rule_pairs)
            else 0.0
        )

    ep_agree = 0
    for r in eval_records:
        r_tags = set(r["rule_tags"])
        l_tags = {tg for tg, k in llm_pairs if k == r["key"] and tg != "other"}
        has_other = ("other", r["key"]) in llm_pairs
        if not r_tags and not l_tags and not has_other:
            ep_agree += 1
        elif r_tags & l_tags:
            ep_agree += 1
    ep_overlap_rate = round(ep_agree / len(eval_records), 4) if eval_records else 0.0

    active_tags = sorted(set(rule_by_tag) | set(llm_by_tag))
    if active_tags:
        macro_jaccard = round(
            sum(
                len(rule_by_tag[t] & llm_by_tag[t]) / max(1, len(rule_by_tag[t] | llm_by_tag[t]))
                for t in active_tags
            )
            / len(active_tags),
            4,
        )
    else:
        macro_jaccard = 1.0 if eval_records else 0.0

    return {
        "agree": int(agree),
        "total": int(total),
        "rate": rate,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "episode_overlap_rate": ep_overlap_rate,
        "macro_jaccard": macro_jaccard,
        "method": "rule_based_vs_llm",
        "labeler": "canary.solver.regret.attribute",
        "by_mode": by_mode,
    }


def attribute_mode_regret(modes: list[dict[str, Any]], records: list[dict[str, Any]]) -> None:
    by_key = {r["key"]: r for r in records}
    valid_keys = set(by_key)
    total_corpus_regret = sum(float(r["total_regret"]) for r in records)

    mode_tags = [resolve_rule_tag(m) for m in modes]
    mode_claimed = [set(_claimed_episode_keys(m, valid_keys)) for m in modes]
    mode_regret = [0.0 for _ in modes]

    for rec in records:
        k = rec["key"]
        for row in rec["regret_rows"]:
            rv = float(row.get("regret") or 0.0)
            if rv <= 0.0:
                continue
            eff = set(row.get("effective_tags") or [])
            matched_idx = [i for i, tg in enumerate(mode_tags) if tg != "other" and tg in eff]
            if not matched_idx:
                act = str(row.get("action") or "")
                matched_idx = [
                    i
                    for i, m in enumerate(modes)
                    if k in mode_claimed[i] and str(m.get("decision") or "") == act
                ]
            if matched_idx:
                share_each = rv / len(matched_idx)
                for i in matched_idx:
                    mode_regret[i] += share_each

    used_ids: set[str] = set()
    for i, m in enumerate(modes):
        base_id = slugify(m.get("id") or m.get("name") or f"mode-{i + 1}")
        mid = base_id
        suffix = 2
        while mid in used_ids:
            mid = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(mid)

        tag = mode_tags[i]
        claimed_list = _claimed_episode_keys(m, valid_keys)
        if claimed_list:
            ep_keys = claimed_list
        elif tag != "other":
            ep_keys = [r["key"] for r in records if tag in r["rule_tags"]]
        else:
            ep_keys = []

        r_sum = mode_regret[i]
        r_share = round(r_sum / total_corpus_regret, 4) if total_corpus_regret > 0.0 else 0.0

        m["id"] = mid
        m["name"] = sanitize_text(m.get("name") or mid).strip()[:100]
        m["description"] = sanitize_text(m.get("description") or "").strip()[:600]
        m["decision"] = sanitize_text(m.get("decision") or TAG_SPECS.get(tag, {}).get("decision", "accuse")).strip()
        m["rule_tag"] = tag
        m["regret_sum"] = round(r_sum, 4)
        m["regret_share"] = r_share
        m["episode_keys"] = ep_keys
        m["episodes"] = len(ep_keys)


def render_mode_chart(mode: dict[str, Any], rec: dict[str, Any], out_dir: Path) -> str:
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    mid = slugify(mode.get("id") or "mode")
    rows = rec.get("regret_rows") or []
    xs: list[int] = []
    ps: list[float] = []
    rs: list[float] = []
    flagged_x: list[int] = []
    flagged_p: list[float] = []
    tag = mode.get("rule_tag") or "other"

    for idx, row in enumerate(rows):
        p_val = row.get("p_best")
        if p_val is None:
            continue
        t_val = int(row.get("t") if row.get("t") is not None else idx)
        xs.append(t_val)
        ps.append(float(p_val))
        rv = float(row.get("regret") or 0.0)
        rs.append(rv)
        if tag in (row.get("effective_tags") or []) or rv >= 0.05:
            flagged_x.append(t_val)
            flagged_p.append(float(p_val))

    if not xs:
        xs = [0, 1]
        ps = [0.05, float(rec["posterior"].get("p_top") or 0.05)]
        rs = [0.0, float(rec["total_regret"])]

    thr = float(rec["posterior"].get("threshold") or 0.5)

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4.2, 3.0), dpi=95)
        ax.plot(xs, ps, color="#2a78d6", linewidth=1.8, label="Solver max P(mole)")
        ax.axhline(thr, color="#eb6834", linestyle="--", linewidth=1.2, label=f"1/(1+V)={thr:.2f}")
        if flagged_x:
            ax.scatter(flagged_x, flagged_p, color="#d03b3b", s=28, zorder=5, label="Mode regret")
        if rec["posterior"].get("did_accuse"):
            acc_t = int(rec["posterior"].get("decision_t") or xs[-1])
            ax.axvline(acc_t, color="#6250d6", linestyle=":", linewidth=1.3)
        ax.set_ylim(-0.04, 1.05)
        ax.set_xlabel("Step t", fontsize=8)
        ax.set_ylabel("Posterior", fontsize=8)
        ep = rec["episode"]
        ax.set_title(f"{mode['name'][:30]} ({ep.get('tier')}-{ep.get('seed')})", fontsize=8.5)
        ax.tick_params(labelsize=7.5)
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=6.8, loc="upper left", framealpha=0.88)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        rel = f"charts/{mid}.png"
        (out_dir / rel).write_bytes(buf.getvalue())
        return rel
    except Exception:
        w, h = 360, 240
        max_x = max(1, max(xs))
        pts = " ".join(
            f"{36 + (w - 52) * (x / max_x):.1f},{16 + (h - 44) * (1.0 - max(0.0, min(1.0, p))):.1f}"
            for x, p in zip(xs, ps)
        )
        ty = 16 + (h - 44) * (1.0 - max(0.0, min(1.0, thr)))
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
            f'<line x1="36" y1="{ty:.1f}" x2="{w - 16}" y2="{ty:.1f}" stroke="#eb6834" stroke-dasharray="4,3"/>'
            f'<polyline fill="none" stroke="#2a78d6" stroke-width="2" points="{pts}"/>'
            f"</svg>"
        )
        rel = f"charts/{mid}.svg"
        (out_dir / rel).write_text(svg, encoding="utf-8")
        return rel


def select_representative_record(mode: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {r["key"]: r for r in records}
    tag = mode.get("rule_tag") or "other"
    cands = [by_key[k] for k in (mode.get("episode_keys") or []) if k in by_key]
    if not cands and tag != "other":
        cands = [r for r in records if tag in r["rule_tags"]]
    if not cands:
        cands = list(records)
    cands.sort(
        key=lambda r: (
            -float(r["tag_regret"].get(tag, 0.0)),
            -float(r["total_regret"]),
            bool(r["episode"].get("correct")),
            r["index"],
        )
    )
    return cands[0]


def _extract_usage_tokens(resp: Any, packed_text: str) -> tuple[int, int, int, int]:
    raw = getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None

    def _u(attr: str) -> int:
        v = getattr(um, attr, 0) if um is not None else 0
        return v if isinstance(v, int) else 0

    usage = getattr(resp, "usage", None) or {}
    tin = _u("prompt_token_count") or int(usage.get("in") or 0) or max(1, len(packed_text) // 4)
    cached = _u("cached_content_token_count") or int(usage.get("cached_in") or usage.get("cached") or 0)
    tout = _u("candidates_token_count") or int(usage.get("out") or 0)
    thinking = _u("thoughts_token_count") or int(usage.get("thinking") or 0)
    return tin, tout, thinking, cached


def _parse_atlas_json(raw_text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"^```(?:json)?|```$", "", (raw_text or "").strip(), flags=re.M).strip()
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("modes"), list):
        return None
    return parsed


def render_atlas_markdown(atlas_doc: dict[str, Any]) -> str:
    corpus = atlas_doc["corpus"]
    qv = atlas_doc["quote_verification"]
    ag = atlas_doc["agreement"]
    ap = corpus.get("accusation_posteriors") or {}
    lines = [
        "# Canary Lab Failure Atlas",
        "",
        (
            f"Generated `{atlas_doc['generated_at']}` at git `{atlas_doc['git_sha']}` | "
            f"model `{atlas_doc['model']}` | source `{atlas_doc['source']}` | "
            f"ledger run ids: `{', '.join(atlas_doc['ledger_run_ids'])}`"
        ),
        "",
        "## Corpus and Verification Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Episodes packed | {corpus['episodes']} |",
        f"| Corpus tokens (cached) | {corpus['tokens']:,} ({corpus['cached_tokens']:,} cached) |",
        f"| Total solver regret (V) | {corpus.get('total_regret', 0.0):.4f} |",
        f"| Failure modes ranked | {len(atlas_doc['modes'])} |",
        f"| Verbatim quotes verified | {qv['verified_quotes']} / {qv['total_quotes']} ({qv['pct']:.1f}%) |",
        f"| Rule-based vs LLM cluster agreement | {ag['agree']} / {ag['total']} ({ag['rate'] * 100.0:.1f}%) |",
        (
            f"| Accusation calibration | accused {ap.get('accused_episodes', 0)}, "
            f"mean P(accused) {ap.get('mean_p_accused')}, premature {ap.get('premature_commits', 0)} |"
        ),
        "",
        sanitize_text(atlas_doc.get("summary") or ""),
        "",
        "## Deterministic Solver Regret Tags",
        "",
        "| Tag | Episodes | Instances | Regret Sum (V) | Regret Share |",
        "|---|---:|---:|---:|---:|",
    ]
    for tg, info in (corpus.get("regret_tags") or {}).items():
        lines.append(
            f"| `{tg}` | {info['episodes']} | {info['instances']} | "
            f"{info['regret_sum']:.4f} | {info['regret_share'] * 100.0:.1f}% |"
        )

    lines.extend(["", "## Ranked Failure Modes", ""])
    for idx, mode in enumerate(atlas_doc["modes"], start=1):
        lines.extend(
            [
                f"### {idx}. {mode['name']} (`{mode['id']}`)",
                "",
                (
                    f"- Regret share: **{mode['regret_share'] * 100.0:.1f}%** "
                    f"({mode.get('regret_sum', 0.0):.4f} V) | "
                    f"Episodes: **{mode['episodes']}** | "
                    f"Decision: `{mode['decision']}` | "
                    f"Rule tag: `{mode.get('rule_tag', 'other')}` | "
                    f"Chart: `{mode.get('chart', '')}`"
                ),
                f"- {mode['description']}",
                "",
            ]
        )
        for q in mode.get("quotes") or []:
            status = "verified" if q.get("verified") else "unverified"
            lines.append(f"> \"{q['quote']}\" ({q['episode']} step {q.get('t', 0)} [{status}])")
        lines.append("")

    return sanitize_text("\n".join(lines).rstrip() + "\n")


def _normalize_llm_spec(llm: str | None, model: str | None = None) -> str:
    if llm:
        spec = llm.strip()
    elif model:
        m = model.strip()
        spec = "stub" if m == "stub" else (m if ":" in m else f"gemini:{m}")
    else:
        spec = DEFAULT_LLM
    if spec in ("gemini", "gemini:"):
        return DEFAULT_LLM
    return spec


def run_atlas(
    runs: Sequence[str | Path] | str | Path = (DEFAULT_RUNS,),
    llm: str = DEFAULT_LLM,
    out_dir: str | Path | None = DEFAULT_OUT,
    episodes: Iterable[EpisodeResult | dict[str, Any]] | None = None,
    client: Any = None,
    run_id: str = "",
    include_reference: bool = False,
    max_episodes: int | None = None,
    render_charts: bool = True,
    human_labels_path: str | Path | None = None,
) -> dict[str, Any]:
    if episodes is not None:
        records = records_from_episodes(episodes)
        invalid_skipped = 0
    else:
        records, invalid_skipped = load_corpus(
            runs=runs,
            include_reference=include_reference,
            max_episodes=max_episodes,
        )
    if not records:
        raise ValueError(f"no valid episodes found in {runs!r}")

    packed_text, blocks = pack_corpus(records)
    corpus_stats = summarize_corpus_stats(records, packed_text, invalid_skipped=invalid_skipped)
    stub_payload = build_stub_payload(records, blocks)

    resolved_run_id = (
        run_id.strip()
        or os.environ.get("CANARY_GEMINI_RUN_ID", "").strip()
        or f"atlas-{int(time.time())}"
    )

    spec = _normalize_llm_spec(llm)
    if client is None:
        led_client = lab_client(
            spec,
            feature=FEATURE,
            run_id=resolved_run_id,
            meta={"episodes": len(records), "chars": len(packed_text)},
        )
        if spec == "stub":
            led_client.inner.script = [{"json": stub_payload}]
    elif isinstance(client, LedgeredClient):
        led_client = client
        if getattr(led_client, "run_id", ""):
            resolved_run_id = led_client.run_id
    else:
        led_client = LedgeredClient(
            client,
            feature=FEATURE,
            run_id=resolved_run_id,
            meta={"episodes": len(records), "chars": len(packed_text)},
        )

    provider = str(getattr(led_client, "provider", "") or "").lower()
    raw_model = str(getattr(led_client, "model", "") or "").strip()
    if provider == "stub":
        model_id = raw_model or "stub"
        is_stub = True
    else:
        model_id = raw_model or (spec.partition(":")[2] if ":" in spec else spec) or DEFAULT_MODEL
        is_stub = False

    corpus_header = json.dumps(
        {
            "episodes": corpus_stats["episodes"],
            "total_regret": corpus_stats["total_regret"],
            "regret_tags": corpus_stats["regret_tags"],
            "accusation_posteriors": corpus_stats["accusation_posteriors"],
        }
    )
    user_prompt = f"CORPUS SUMMARY:\n{corpus_header}\n\nPACKED TRAJECTORIES:\n{packed_text}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    resp = led_client.chat(messages, response_schema=ATLAS_SCHEMA, max_tokens=16384)
    tin, tout, thinking, cached = _extract_usage_tokens(resp, packed_text)
    parsed = _parse_atlas_json(getattr(resp, "text", "") or "")

    if parsed is not None and not parsed.get("modes") and is_stub:
        parsed = stub_payload

    source = "stub" if is_stub else ("llm" if parsed is not None else "fallback")
    if parsed is None:
        parsed = stub_payload
        if not is_stub:
            source = "fallback"

    raw_modes = [dict(m) for m in (parsed.get("modes") or []) if isinstance(m, dict)]
    qv = verify_quotes(raw_modes, blocks)

    if provider == "gemini" and (qv["total_quotes"] == 0 or qv["verified_quotes"] < qv["total_quotes"]):
        retry_msg = (
            f"Some quotes failed exact substring check ({qv['verified_quotes']}/{qv['total_quotes']}): "
            f"{json.dumps(qv['unverified'][:4])}. Return corrected JSON where every quote.quote is an "
            "exact unmodified substring of its named episode block."
        )
        try:
            resp2 = led_client.chat(
                [*messages, {"role": "assistant", "content": getattr(resp, "text", "") or "{}"}, {"role": "user", "content": retry_msg}],
                response_schema=ATLAS_SCHEMA,
                max_tokens=16384,
            )
            tin2, tout2, thinking2, cached2 = _extract_usage_tokens(resp2, packed_text)
            tin += tin2
            tout += tout2
            thinking += thinking2
            cached += cached2
            parsed2 = _parse_atlas_json(getattr(resp2, "text", "") or "")
            if parsed2 is not None and parsed2.get("modes"):
                cand_modes = [dict(m) for m in parsed2["modes"] if isinstance(m, dict)]
                qv2 = verify_quotes(cand_modes, blocks)
                if qv2["rate"] >= qv["rate"] and qv2["verified_quotes"] >= qv["verified_quotes"]:
                    parsed = parsed2
                    raw_modes = cand_modes
                    qv = qv2
                    source = "llm"
        except Exception:
            pass

    attribute_mode_regret(raw_modes, records)
    raw_modes.sort(key=lambda m: (-float(m["regret_share"]), -int(m["episodes"]), str(m["id"])))

    agreement = compute_agreement(raw_modes, records)

    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)

    for m in raw_modes:
        if render_charts and out_path is not None and records:
            rep_rec = select_representative_record(m, records)
            m["chart"] = render_mode_chart(m, rep_rec, out_path)
        else:
            m["chart"] = f"charts/{m['id']}.png" if render_charts else ""

    human_agreement: dict[str, Any] = {
        "agree": agreement["agree"],
        "total": agreement["total"],
        "rate": agreement["rate"],
        "labeler": agreement["labeler"],
    }
    if human_labels_path is not None and Path(human_labels_path).is_file():
        try:
            loaded_ha = json.loads(Path(human_labels_path).read_text(encoding="utf-8"))
            if isinstance(loaded_ha, dict) and "rate" in loaded_ha:
                human_agreement = sanitize_obj(loaded_ha)
        except (OSError, json.JSONDecodeError):
            pass

    atlas_doc: dict[str, Any] = sanitize_obj(
        {
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "git_sha": git_sha(),
            "ledger_run_ids": [resolved_run_id],
            "synthetic": bool(is_stub),
            "source": source,
            "model": model_id,
            "summary": str(parsed.get("summary") or stub_payload["summary"]),
            "modes": raw_modes,
            "corpus": {
                "episodes": corpus_stats["episodes"],
                "tokens": int(tin),
                "cached_tokens": int(cached),
                "out_tokens": int(tout),
                "thinking_tokens": int(thinking),
                "chars": corpus_stats["chars"],
                "invalid_skipped": corpus_stats["invalid_skipped"],
                "total_regret": corpus_stats["total_regret"],
                "regret_tags": corpus_stats["regret_tags"],
                "accusation_posteriors": corpus_stats["accusation_posteriors"],
            },
            "quote_verification": qv,
            "agreement": agreement,
            "human_agreement": human_agreement,
        }
    )

    if out_path is not None:
        (out_path / "atlas.json").write_text(json.dumps(atlas_doc, indent=2) + "\n", encoding="utf-8")
        (out_path / "atlas.md").write_text(render_atlas_markdown(atlas_doc), encoding="utf-8")

    return atlas_doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m canary.gemini.atlas",
        description="Canary Lab Failure Atlas: long-context failure clustering with verified quotes and solver regret.",
    )
    ap.add_argument("--runs", nargs="*", action="extend", default=[], help="run dirs or episodes.jsonl files")
    ap.add_argument("--llm", default=None, help="stub or gemini:gemini-4-carbon")
    ap.add_argument("--model", default=None, help="optional model alias, e.g. gemini-4-carbon")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output directory for atlas.json and atlas.md")
    ap.add_argument("--run-id", default="", help="explicit ledger run_id")
    ap.add_argument("--max-episodes", type=int, default=None, help="optional cap on episodes packed")
    ap.add_argument("--include-reference", action="store_true", help="include reference solver and scripted baselines")
    ap.add_argument("--no-charts", action="store_true", help="skip rendering belief-vs-solver mode charts")
    ap.add_argument("--human-labels", default=None, help="optional JSON file with human validation agreement")
    args = ap.parse_args(argv)

    llm_spec = _normalize_llm_spec(args.llm, args.model)
    run_sources = args.runs or [str(DEFAULT_RUNS)]
    doc = run_atlas(
        runs=run_sources,
        llm=llm_spec,
        out_dir=args.out,
        run_id=args.run_id,
        include_reference=args.include_reference,
        max_episodes=args.max_episodes,
        render_charts=not args.no_charts,
        human_labels_path=args.human_labels,
    )
    qv = doc["quote_verification"]
    ag = doc["agreement"]
    print(
        f"wrote {Path(args.out) / 'atlas.json'} and {Path(args.out) / 'atlas.md'} "
        f"(episodes={doc['corpus']['episodes']}, modes={len(doc['modes'])}, "
        f"quotes={qv['verified_quotes']}/{qv['total_quotes']}, agreement={ag['agree']}/{ag['total']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
