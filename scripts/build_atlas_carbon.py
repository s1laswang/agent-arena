from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.agents._common import inline_schema
from canary.analysis.tags import to_result
from canary.env import Env
from canary.gemini import LedgeredClient, lab_client
from canary.gemini.dashboard import SECRET_RE, redact
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute

FRONTIER_FAMILIES = ("codex-gpt-5.5", "gpt-5.5", "grok", "opencode-gpt-5.6-sol", "gemini")
DEFAULT_RUNS = Path("data/runs/committed")
DEFAULT_OUT = Path("results/gemini")
DEFAULT_LLM = "gemini:gemini-4-carbon"
DEFAULT_RUN_ID = "atlas-carbon-v1"
DEFAULT_SAMPLE_SIZE = 30

MODE_ORDER = (
    "premature-accusation",
    "uninformative-canary",
    "subthreshold-commit",
    "over-restriction",
    "ignored-delay",
    "late-commit",
)

MODE_SPECS: dict[str, dict[str, str]] = {
    "premature-accusation": {
        "id": "premature-accusation",
        "default_name": "Premature Accusation Under Candidate Ambiguity",
        "default_description": (
            "Calls accuse with Bayesian posterior P(accused) < 0.60 before canary leaks isolate a single culprit, "
            "trading positive continuation value for a -1.0 wrong-accusation penalty."
        ),
        "decision": "accuse",
        "chart_rel": "../gemini_roles/multimodal_evidence/belief-chart-forensics-carbon/charts/ep_0.png",
    },
    "uninformative-canary": {
        "id": "uninformative-canary",
        "default_name": "Low-Entropy Canary Partitions",
        "default_description": (
            "Plants narrow 2-to-3 employee or single-variant canaries whose Gini split lags the Bayesian reference "
            "partition, leaving multiple suspects indistinguishable late in the horizon."
        ),
        "decision": "plant_canary",
        "chart_rel": "../gemini_roles/multimodal_evidence/belief-chart-forensics-carbon/charts/ep_1.png",
    },
    "subthreshold-commit": {
        "id": "subthreshold-commit",
        "default_name": "Sub-Threshold Accusation Before Optimal Stopping",
        "default_description": (
            "Commits to accuse at moderate posterior (0.60 <= P(accused) < p*) when one additional canary split "
            "has higher continuation expected value Q_continue than immediate accusation."
        ),
        "decision": "accuse",
        "chart_rel": "../gemini_roles/multimodal_evidence/belief-chart-forensics-carbon/charts/ep_5.png",
    },
    "over-restriction": {
        "id": "over-restriction",
        "default_name": "Premature Access Restriction and Decoy Chase",
        "default_description": (
            "Invokes restrict_access across low-posterior or hostile decoy employees, paying daily restriction "
            "costs while preventing suspects from receiving diagnostic canary documents."
        ),
        "decision": "restrict_access",
        "chart_rel": "../gemini_roles/multimodal_evidence/access-heatmap-carbon/rasters/medium_seed_0.png",
    },
    "ignored-delay": {
        "id": "ignored-delay",
        "default_name": "Ignored Leak Propagation Delay at Accusation",
        "default_description": (
            "Accuses with P(accused) < 0.90 while leaks from recent canary deployments remain inside the 1-to-3 "
            "day surfacing pipeline, misreading unsurfaced leaks as exoneration."
        ),
        "decision": "accuse",
        "chart_rel": "../gemini_roles/multimodal_evidence/belief-chart-forensics-carbon/charts/ep_2.png",
    },
    "late-commit": {
        "id": "late-commit",
        "default_name": "Delayed Commit and Horizon Expiration",
        "default_description": (
            "Advances days after the posterior already exceeds optimal immediate accusation EV (bleeding company "
            "value V) or lets the day-14 horizon expire with no accusation."
        ),
        "decision": "advance_day",
        "chart_rel": "../gemini_roles/multimodal_evidence/belief-chart-forensics-carbon/charts/ep_4.png",
    },
}

SYSTEM_PROMPT = (
    "You are the Canary Lab Failure Atlas analyst. You receive a full multi-episode investigation corpus "
    "containing frontier agent trajectories, agent transcript reasoning lines, accusation posteriors, and "
    "step-level Bayesian solver regret signals.\n"
    "STRICT GROUNDING RULES (verified in code):\n"
    "1. Never use unicode em dashes or en dashes anywhere; use plain ASCII hyphens, colons, or semicolons.\n"
    "2. Every quote.episode MUST equal an exact episode header key from the corpus (for example "
    "'codex:gpt-5.5/medium/0#73'). Never include '### ' or trailing metadata in quote.episode.\n"
    "3. Every quote.quote MUST be an exact, unmodified, single-line substring (12 to 215 chars) copied "
    "character-for-character from inside that exact episode block. Prefer 'transcript t=...:' reasoning lines "
    "showing the agent's own words when present in that episode, or exact 'regret t=...' / 't=... d...' lines "
    "when the episode has no transcript text. Never paraphrase, never add ellipses '...', and never merge lines.\n"
    "4. Every quote.t MUST be the non-negative integer step index t of that quoted line."
)


class LLMQuote(BaseModel):
    episode: str = Field(max_length=120)
    t: int = Field(ge=0)
    quote: str = Field(min_length=8, max_length=220)


class LLMMode(BaseModel):
    id: str = Field(max_length=48)
    name: str = Field(min_length=4, max_length=64)
    description: str = Field(min_length=20, max_length=450)
    decision: str = Field(min_length=3, max_length=32)
    quotes: list[LLMQuote] = Field(default_factory=list, max_length=3)


class AtlasSynthesisOutput(BaseModel):
    summary: str = Field(min_length=20, max_length=950)
    modes: list[LLMMode] = Field(default_factory=list, max_length=8)


class LLMSampleLabel(BaseModel):
    episode: str = Field(max_length=120)
    mode_id: str = Field(max_length=48)


class AtlasSampleOutput(BaseModel):
    labels: list[LLMSampleLabel] = Field(default_factory=list, max_length=60)


def clean_text(val: Any) -> str:
    s = "" if val is None else str(val)
    s = s.replace("\r", " ")
    s = s.replace("\u2014", " - ").replace("\u2013", "-")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2026", "...")
    return SECRET_RE.sub("[redacted]", s)


def clean_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_text(obj)
    if isinstance(obj, list):
        return [clean_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {clean_text(k): clean_obj(v) for k, v in obj.items()}
    return obj


def short_git_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = res.stdout.strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


@contextmanager
def tier_context(version: str):
    target = "v1.3" if version == "v1.2" else version
    old_kv = rules.KNOWN_V_MODE
    with rules.tiers_version(target):
        rules.KNOWN_V_MODE = version != "v1.2"
        try:
            yield
        finally:
            rules.KNOWN_V_MODE = old_kv


def matches_frontier_path(rel_parts: tuple[str, ...], families: tuple[str, ...] | None) -> bool:
    if "superseded" in rel_parts or "reference" in rel_parts:
        return False
    if families is None:
        return True
    return any(any(part == fam or part.startswith(fam + "-") for fam in families) for part in rel_parts[:-1])


def _append_note_lines(raw_text: str, step: int, out: list[tuple[int, str]]) -> None:
    for raw_line in (raw_text or "").splitlines():
        cleaned = " ".join(clean_text(raw_line).split()).strip()
        if len(cleaned) < 18:
            continue
        parts = [cleaned] if len(cleaned) <= 185 else re.split(r"(?<=[.!?])\s+", cleaned)
        for part in parts:
            line = part.strip()
            if len(line) < 18:
                continue
            if len(line) > 185:
                cut = line[:185].rsplit(" ", 1)[0]
                line = cut if len(cut) >= 24 else line[:185]
            out.append((max(0, int(step)), line))


def extract_transcript_notes(episodes_file: Path, seed: Any, max_notes: int = 16) -> list[tuple[int, str]]:
    tdir = episodes_file.parent / "transcripts"
    if not tdir.is_dir():
        return []
    notes: list[tuple[int, str]] = []
    txt_path = tdir / f"{seed}.txt"
    json_path = tdir / f"{seed}.json"
    if txt_path.is_file():
        step = 0
        for ln in txt_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not ln.startswith("{"):
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            tp = d.get("type")
            if tp == "item.completed":
                it = d.get("item") or {}
                it_type = it.get("type")
                if it_type == "mcp_tool_call":
                    step += 1
                elif it_type == "agent_message":
                    _append_note_lines(str(it.get("text") or ""), step, notes)
            elif tp == "tool_use":
                step += 1
            elif tp == "text":
                part = d.get("part") or {}
                _append_note_lines(str(part.get("text") or ""), step, notes)
    elif json_path.is_file():
        try:
            arr = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            arr = []
        if isinstance(arr, list):
            step = 0
            for m in arr:
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                _append_note_lines(str(m.get("content") or ""), step, notes)
                step += len(m.get("tool_calls") or [])
    deduped: list[tuple[int, str]] = []
    seen: set[str] = set()
    for st_idx, txt in notes:
        if txt not in seen:
            seen.add(txt)
            deduped.append((st_idx, txt))
    if len(deduped) <= max_notes:
        return deduped
    head_n = max_notes // 3
    tail_n = max_notes - head_n
    return deduped[:head_n] + deduped[-tail_n:]


def compute_episode_posteriors(ep: Any) -> dict[str, Any]:
    params = rules.tier_params_for_episode(ep.tier, ep.steps)
    sp = SolverPolicy(params)
    steps = ep.steps
    acc_step = len(steps)
    accused_emp = ep.accused
    post: dict[str, float] = {}
    v_at = 1.0
    found_accuse = False
    for i, st in enumerate(steps):
        for prev in steps[sp.seen : i]:
            sp._ingest(prev)
        sp.seen = i
        if st.tool == "accuse":
            found_accuse = True
            acc_step = int(st.t)
            accused_emp = (st.args or {}).get("employee") or accused_emp
            post = sp.belief() if sp.obs.employees else {}
            v_at = float(sp.V)
            break
    if not found_accuse:
        for prev in steps[sp.seen :]:
            sp._ingest(prev)
        sp.seen = len(steps)
        post = sp.belief() if sp.obs.employees else {}
        v_at = float(sp.V)
    wrong_pen = float(params.wrong_accusation_score)
    denom = max(1e-9, v_at - wrong_pen)
    ev_thr = max(0.0, min(1.0, -wrong_pen / denom))
    best_emp = max(post, key=post.get) if post else None
    p_best = round(float(post[best_emp]), 4) if best_emp is not None else None
    p_acc = round(float(post.get(str(accused_emp), 0.0)), 4) if (found_accuse and post and accused_emp) else None
    return {
        "decision_t": acc_step,
        "accused": accused_emp if found_accuse else None,
        "best_employee": best_emp,
        "p_accused": p_acc,
        "p_best": p_best,
        "v_at_decision": round(v_at, 4),
        "ev_threshold": round(ev_thr, 4),
        "below_ev_threshold": bool(p_acc is not None and p_acc < ev_thr),
        "below_0_6": bool(p_acc is not None and p_acc < 0.6),
    }


def step_mode_regrets(regret_rows: list[dict[str, Any]]) -> tuple[dict[str, float], set[str]]:
    by_mode: Counter[str] = Counter()
    modes_present: set[str] = set()
    for row in regret_rows:
        reg = float(row.get("regret", 0.0))
        act = str(row.get("action") or "")
        tgs = {str(x) for x in (row.get("tags") or [])}
        if act == "accuse":
            if "ignored_delay" in tgs:
                by_mode["ignored-delay"] += reg
                modes_present.add("ignored-delay")
            elif "premature_accusation" in tgs:
                by_mode["premature-accusation"] += reg
                modes_present.add("premature-accusation")
            elif reg > 0.0:
                by_mode["subthreshold-commit"] += reg
                modes_present.add("subthreshold-commit")
        elif act == "plant_canary":
            if reg > 0.0:
                by_mode["uninformative-canary"] += reg
            if "uninformative_canary" in tgs or reg >= 0.05:
                modes_present.add("uninformative-canary")
        elif act == "restrict_access":
            if reg > 0.0:
                by_mode["over-restriction"] += reg
            if reg > 0.0 or "over_restriction" in tgs or "decoy_chase" in tgs:
                modes_present.add("over-restriction")
        elif act == "advance_day":
            if reg > 0.0:
                by_mode["late-commit"] += reg
                modes_present.add("late-commit")
        elif act == "(no accusation)":
            if reg > 0.0:
                by_mode["late-commit"] += reg
            if reg > 0.0 or "no_accusation" in tgs:
                modes_present.add("late-commit")
    return {m: round(float(by_mode[m]), 6) for m in MODE_ORDER if by_mode[m] > 0.0}, modes_present


def solver_primary_mode(mode_regrets: dict[str, float], tag_set: list[str], end_reason: str) -> str:
    tags = set(tag_set)
    if "ignored_delay" in tags:
        return "ignored-delay"
    if end_reason != "accused" and "no_accusation" in tags and max(mode_regrets.values(), default=0.0) < 0.15:
        return "late-commit"
    if mode_regrets:
        rank = {m: idx for idx, m in enumerate(MODE_ORDER)}
        return max(mode_regrets.items(), key=lambda kv: (round(kv[1], 6), -rank.get(kv[0], 99)))[0]
    if "uninformative_canary" in tags:
        return "uninformative-canary"
    if "over_restriction" in tags or "decoy_chase" in tags:
        return "over-restriction"
    if end_reason != "accused":
        return "late-commit"
    return "uninformative-canary"


def load_atlas_corpus(
    runs_root: str | Path = DEFAULT_RUNS,
    families: tuple[str, ...] | None = FRONTIER_FAMILIES,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = Path(runs_root)
    candidate_files = [
        f
        for f in sorted(root.rglob("episodes.jsonl"))
        if matches_frontier_path(f.relative_to(root).parts, families)
    ]
    if not candidate_files and families is not None:
        candidate_files = [
            f
            for f in sorted(root.rglob("episodes.jsonl"))
            if matches_frontier_path(f.relative_to(root).parts, None)
        ]

    world_cache: dict[tuple[str, str, int], tuple[str | None, str | None]] = {}
    records: list[dict[str, Any]] = []
    n_invalid_skipped = 0
    files_loaded: list[str] = []

    for f in candidate_files:
        rel_parts = f.relative_to(root).parts
        ver = next((p for p in rel_parts if p.startswith("v1.")), "v1.2")
        rel_str = str(f.relative_to(root))
        files_loaded.append(rel_str)
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if (d.get("meta") or {}).get("valid") is False or d.get("end_reason") == "error":
                n_invalid_skipped += 1
                continue
            with tier_context(ver):
                ep = to_result(d)
                true_mole: str | None = None
                decoy: str | None = None
                if ep.seed not in JUDGE_SEEDS and ep.seed not in HELDOUT_SEEDS:
                    ck = (ver, str(ep.tier), int(ep.seed))
                    if ck not in world_cache:
                        w = Env(ep.tier, ep.seed)._world
                        world_cache[ck] = (w.mole, w.decoy)
                    true_mole, decoy = world_cache[ck]
                    ep.meta = dict(ep.meta or {}, decoy=decoy)
                tg = attribute(ep)
                post_info = compute_episode_posteriors(ep)
            idx = len(records)
            key = clean_text(f"{d.get('agent')}/{d.get('tier')}/{d.get('seed')}#{idx}")
            total_regret = round(sum(float(x.get("regret", 0.0)) for x in tg), 6)
            tag_set = sorted({clean_text(t) for x in tg for t in (x.get("tags") or [])})
            m_regrets, m_present = step_mode_regrets(tg)
            prim_mode = solver_primary_mode(m_regrets, tag_set, str(d.get("end_reason") or ""))
            m_present.add(prim_mode)
            notes = extract_transcript_notes(f, d.get("seed"))
            records.append(
                {
                    "index": idx,
                    "key": key,
                    "tiers_version": ver,
                    "run_path": rel_str,
                    "episode": d,
                    "regret_rows": tg,
                    "total_regret": total_regret,
                    "tag_set": tag_set,
                    "posteriors": post_info,
                    "mode_regrets": m_regrets,
                    "modes_present": sorted(m_present),
                    "solver_primary_mode": prim_mode,
                    "transcript_notes": notes,
                    "true_mole": true_mole,
                    "decoy": decoy,
                }
            )

    summary = summarize_corpus_stats(records, n_invalid_skipped, files_loaded)
    return records, summary


def summarize_corpus_stats(
    records: list[dict[str, Any]],
    n_invalid_skipped: int,
    files_loaded: list[str],
) -> dict[str, Any]:
    total_regret = round(sum(float(r["total_regret"]) for r in records), 6)
    mode_regret_sum: Counter[str] = Counter()
    mode_ep_count: Counter[str] = Counter()
    for r in records:
        for m, val in r["mode_regrets"].items():
            mode_regret_sum[m] += float(val)
        for m in r["modes_present"]:
            mode_ep_count[m] += 1

    mode_stats: dict[str, dict[str, Any]] = {}
    for m in MODE_ORDER:
        r_sum = round(float(mode_regret_sum[m]), 6)
        ep_n = int(mode_ep_count[m])
        share = round(r_sum / total_regret, 4) if total_regret > 0.0 else 0.0
        mode_stats[m] = {
            "id": m,
            "regret_sum": round(r_sum, 4),
            "regret_share": share,
            "episodes": ep_n,
            "active": bool(ep_n > 0 or r_sum > 0.0),
        }

    p_all: list[float] = []
    p_right: list[float] = []
    p_wrong: list[float] = []
    below_ev = 0
    below_06 = 0
    n_no_acc = 0
    for r in records:
        pi = r["posteriors"]
        pa = pi["p_accused"]
        if pa is None:
            n_no_acc += 1
            continue
        p_all.append(pa)
        if r["episode"].get("correct"):
            p_right.append(pa)
        else:
            p_wrong.append(pa)
        if pi["below_ev_threshold"]:
            below_ev += 1
        if pi["below_0_6"]:
            below_06 += 1

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        ep = r["episode"]
        grouped[(r["tiers_version"], str(ep.get("agent")), str(ep.get("tier")))].append(r)

    by_group: list[dict[str, Any]] = []
    for (ver, agent, tier), lst in sorted(grouped.items()):
        n = len(lst)
        pa_vals = [x["posteriors"]["p_accused"] for x in lst if x["posteriors"]["p_accused"] is not None]
        by_group.append(
            {
                "tiers_version": ver,
                "agent": clean_text(agent),
                "tier": clean_text(tier),
                "episodes": n,
                "mean_score": round(sum(float(x["episode"].get("score", 0.0)) for x in lst) / n, 4),
                "accuracy": round(sum(1 for x in lst if x["episode"].get("correct")) / n, 4),
                "mean_p_accused": round(sum(pa_vals) / len(pa_vals), 4) if pa_vals else None,
                "total_regret": round(sum(float(x["total_regret"]) for x in lst), 4),
            }
        )

    accusation_posteriors = {
        "n_accusations": len(p_all),
        "n_no_accusation": n_no_acc,
        "mean_p_accused": round(sum(p_all) / len(p_all), 4) if p_all else None,
        "mean_p_accused_correct": round(sum(p_right) / len(p_right), 4) if p_right else None,
        "mean_p_accused_wrong": round(sum(p_wrong) / len(p_wrong), 4) if p_wrong else None,
        "below_ev_threshold_count": below_ev,
        "below_0_6_count": below_06,
        "by_version_agent_tier": by_group,
    }

    return {
        "n_episodes": len(records),
        "n_invalid_skipped": n_invalid_skipped,
        "total_regret": round(total_regret, 4),
        "files_loaded": files_loaded,
        "mode_stats": mode_stats,
        "accusation_posteriors": accusation_posteriors,
        "by_version_agent_tier": by_group,
    }


def _compact_assignment(asg: Any) -> str:
    if not isinstance(asg, dict) or not asg:
        return "{}"
    by_var: dict[str, list[str]] = defaultdict(list)
    for emp, var in sorted(asg.items()):
        by_var[clean_text(var)].append(clean_text(emp))
    chunks: list[str] = []
    for var, emps in sorted(by_var.items()):
        if len(emps) <= 4:
            emp_s = ",".join(emps)
        else:
            emp_s = f"{emps[0]},{emps[1]}..{emps[-1]}({len(emps)})"
        chunks.append(f"{var}:[{emp_s}]")
    text = "{" + ", ".join(chunks) + "}"
    return text[:110]


def _fmt_step_line(step_dict: dict[str, Any], regret_row: dict[str, Any] | None) -> str:
    t = int(step_dict.get("t", 0))
    day = step_dict.get("day")
    tool = clean_text(step_dict.get("tool") or "")
    args = step_dict.get("args") or {}
    res = step_dict.get("result") or {}
    ok = res.get("ok", True)
    data = res.get("data") if isinstance(res.get("data"), dict) else {}

    if tool == "plant_canary":
        title = clean_text(args.get("doc_title") or "")[:36]
        asg_s = _compact_assignment(args.get("assignment"))
        arg_s = f"title={title!r},assignment={asg_s}"
    else:
        parts = []
        for k, v in sorted(args.items()):
            vs = clean_text(v)
            if len(vs) > 36:
                vs = vs[:36]
            parts.append(f"{clean_text(k)}={vs}")
        arg_s = ",".join(parts)

    if not ok:
        out_s = "ERR " + clean_text(res.get("error") or "failed")[:64]
    elif tool in ("advance_day", "status") and "V" in data:
        out_s = f"ok V={data.get('V')}"
    elif tool == "check_leak_feed" and isinstance(data.get("items"), list):
        n_it = len(data["items"])
        last_doc = clean_text(data["items"][-1].get("doc_id")) if n_it else "-"
        out_s = f"ok items={n_it} latest={last_doc}"
    else:
        out_s = "ok"

    pb_s = ""
    if regret_row is not None and regret_row.get("p_best") is not None and tool in (
        "accuse",
        "plant_canary",
        "restrict_access",
        "advance_day",
    ):
        pb_s = f" [p_best={regret_row['p_best']:.3f}]"

    line = f"t={t} d{day} {tool}({arg_s}) -> {out_s}{pb_s}"
    return clean_text(line)[:205]


def pack_atlas_corpus(records: list[dict[str, Any]], max_chars: int = 920_000) -> tuple[str, dict[str, str]]:
    blocks: dict[str, str] = {}
    for rec in records:
        ep = rec["episode"]
        key = rec["key"]
        pi = rec["posteriors"]
        tg = rec["regret_rows"]
        pa_s = "None" if pi["p_accused"] is None else f"{pi['p_accused']:.4f}"
        pb_s = "None" if pi["p_best"] is None else f"{pi['p_best']:.4f}"
        tag_s = ",".join(rec["tag_set"]) if rec["tag_set"] else "none"
        lines = [
            (
                f"### {key} score={float(ep.get('score', 0.0)):.3f} correct={bool(ep.get('correct'))} "
                f"accused={clean_text(ep.get('accused'))} day={ep.get('final_day')} "
                f"end={clean_text(ep.get('end_reason'))} total_regret={rec['total_regret']:.4f}"
            ),
            (
                f"posteriors t={pi['decision_t']}: p_accused={pa_s} p_best={pb_s} "
                f"V={pi['v_at_decision']:.3f} ev_threshold={pi['ev_threshold']:.4f} tags=[{tag_s}]"
            ),
        ]
        for r in tg:
            rv = float(r.get("regret", 0.0))
            if rv > 0.0 or r.get("tags"):
                pa_tok = f" p_accused={r['p_accused']:.4f}" if "p_accused" in r else ""
                pb_tok = f" p_best={r['p_best']:.4f}" if r.get("p_best") is not None else ""
                rt_list = [clean_text(x) for x in (r.get("tags") or [])]
                lines.append(
                    clean_text(
                        f"regret t={r.get('t')} d{r.get('day')} {r.get('action')} "
                        f"r={rv:.4f}{pa_tok}{pb_tok} tags={rt_list}"
                    )[:205]
                )
        for note_t, note_txt in rec["transcript_notes"]:
            lines.append(clean_text(f"transcript t={note_t}: {note_txt}")[:210])
        steps = ep.get("steps") or []
        for idx_s, s in enumerate(steps):
            s_dict = s if isinstance(s, dict) else {}
            r_row = tg[idx_s] if idx_s < len(tg) else None
            lines.append(_fmt_step_line(s_dict, r_row))
        blocks[key] = "\n".join(lines)

    full_text = "\n\n".join(blocks.values())
    if len(full_text) <= max_chars:
        return full_text, blocks

    trimmed_blocks: dict[str, str] = {}
    per_ep_budget = max(800, max_chars // max(1, len(records)))
    for key, blk in blocks.items():
        if len(blk) <= per_ep_budget:
            trimmed_blocks[key] = blk
        else:
            b_lines = blk.splitlines()
            kept: list[str] = []
            used = 0
            for ln in b_lines:
                if used + len(ln) + 1 > per_ep_budget:
                    break
                kept.append(ln)
                used += len(ln) + 1
            trimmed_blocks[key] = "\n".join(kept)
    return "\n\n".join(trimmed_blocks.values())[:max_chars], trimmed_blocks


def episode_outcome_bucket(rec: dict[str, Any]) -> str:
    ep = rec["episode"]
    if ep.get("end_reason") != "accused":
        return "horizon_no_accusation"
    if not ep.get("correct"):
        return "wrong_accusation"
    if float(rec["total_regret"]) >= 0.20:
        return "correct_high_regret"
    return "correct_low_regret"


def select_stratified_sample(
    records: list[dict[str, Any]],
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> list[dict[str, Any]]:
    target = min(max(1, sample_size), len(records))
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        tier = str(rec["episode"].get("tier") or "unknown")
        strata[(tier, episode_outcome_bucket(rec))].append(rec)
    for lst in strata.values():
        lst.sort(key=lambda r: (-float(r["total_regret"]), int(r["index"])))
    ordered_keys = sorted(strata.keys())
    picked: list[dict[str, Any]] = []
    depth = 0
    while len(picked) < target:
        progressed = False
        for sk in ordered_keys:
            if depth < len(strata[sk]) and len(picked) < target:
                picked.append(strata[sk][depth])
                progressed = True
        if not progressed:
            break
        depth += 1
    return picked


def _extract_call_usage(resp: Any, latency_s: float) -> dict[str, Any]:
    raw = getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None

    def _u(attr: str) -> int:
        v = getattr(um, attr, 0) if um is not None else 0
        return v if isinstance(v, int) else 0

    usage = dict(getattr(resp, "usage", {}) or {})
    prompt_tokens = int(_u("prompt_token_count") or usage.get("in", 0) or 0)
    cand_tokens = _u("candidates_token_count")
    think_tokens = _u("thoughts_token_count")
    out_tokens = int(cand_tokens or usage.get("out", 0) or 0)
    if um is not None and out_tokens == 0 and usage.get("out"):
        out_tokens = max(0, int(usage["out"]) - think_tokens)
    cached_tokens = int(_u("cached_content_token_count") or usage.get("cached_in", 0) or 0)
    cost_usd = float(usage.get("cost_usd_est", usage.get("cost_usd", 0.0)) or 0.0)
    cands = (getattr(raw, "candidates", None) or []) if raw is not None else []
    finish_reason = str(getattr(cands[0], "finish_reason", None)) if cands else None
    return {
        "text": getattr(resp, "text", "") or "",
        "finish_reason": finish_reason,
        "latency_s": round(latency_s, 3),
        "prompt_tokens": prompt_tokens,
        "out_tokens": out_tokens,
        "thinking_tokens": think_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": round(cost_usd, 6),
    }


class AtlasSession:
    def __init__(self, client: LedgeredClient):
        self.client = client
        self.calls: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        m = getattr(self.client, "model", "") or ""
        if m:
            return str(m)
        inner = getattr(self.client, "inner", None)
        im = getattr(inner, "model", "") if inner is not None else ""
        return str(im or "stub")

    def call_structured(self, system: str, user: str, schema_cls: type[BaseModel]) -> tuple[Any | None, str | None]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        t0 = time.time()
        try:
            resp = self.client.chat(
                messages,
                tools=None,
                temperature=0.0,
                response_schema=inline_schema(schema_cls),
            )
            meta = _extract_call_usage(resp, time.time() - t0)
            self.calls.append(meta)
            parsed = schema_cls.model_validate(json.loads(meta["text"] or ""))
            return parsed, None
        except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:220]}"
        except Exception as exc:
            return None, f"llm_error {type(exc).__name__}: {str(exc)[:220]}"


def build_atlas_client(llm: Any, run_id: str) -> LedgeredClient:
    if isinstance(llm, LedgeredClient):
        return llm
    if isinstance(llm, str):
        return lab_client(llm, feature="atlas", run_id=run_id)
    return LedgeredClient(llm, feature="atlas", run_id=run_id)


_LINE_T_RE = re.compile(r"^(?:transcript |regret |posteriors )?t=(\d+)\b")


def verify_quote_item(
    episode_key: str,
    proposed_t: int,
    quote_text: str,
    blocks: dict[str, str],
    records_by_key: dict[str, dict[str, Any]],
) -> tuple[bool, int, str]:
    ep_k = episode_key.strip()
    qt = quote_text.strip()
    if ep_k not in blocks or not qt or "\n" in qt or "\r" in qt:
        return False, max(0, int(proposed_t)), clean_text(qt)
    if "\u2014" in qt or "\u2013" in qt:
        return False, max(0, int(proposed_t)), clean_text(qt)
    blk = blocks[ep_k]
    if qt not in blk:
        return False, max(0, int(proposed_t)), qt
    rec = records_by_key[ep_k]
    max_t = len(rec["episode"].get("steps") or [])
    resolved_t = max(0, min(max_t, int(proposed_t)))
    for ln in blk.splitlines():
        if qt in ln:
            m = _LINE_T_RE.match(ln)
            if m:
                resolved_t = max(0, min(max_t, int(m.group(1))))
            elif ln.startswith("### "):
                resolved_t = max(0, min(max_t, int(rec["posteriors"]["decision_t"])))
            break
    return True, resolved_t, qt


def normalize_mode_id(raw_id: str, decision: str, name: str) -> str | None:
    rid = clean_text(raw_id).strip().lower().replace("_", "-")
    if rid in MODE_SPECS:
        return rid
    blob = f"{rid} {decision} {name}".lower()
    if "delay" in blob:
        return "ignored-delay"
    if "restrict" in blob or "decoy" in blob:
        return "over-restriction"
    if "canary" in blob or "gini" in blob or "partition" in blob or "wide" in blob:
        return "uninformative-canary"
    if "subthreshold" in blob or "sub-threshold" in blob or "optimal stopping" in blob:
        return "subthreshold-commit"
    if "late" in blob or "horizon" in blob or "abstain" in blob or "advance" in blob:
        return "late-commit"
    if "premature" in blob or "accuse" in blob:
        return "premature-accusation"
    return None


def audit_synthesis(
    parsed: AtlasSynthesisOutput | None,
    active_mode_ids: list[str],
    blocks: dict[str, str],
    records_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if parsed is None:
        return {
            "ok": False,
            "reason": "parse_failed",
            "missing_modes": list(active_mode_ids),
            "total_quotes": 0,
            "verified_quotes": 0,
            "unverified": [],
            "by_mode": {},
        }
    by_mode: dict[str, dict[str, Any]] = {}
    unverified: list[dict[str, Any]] = []
    total_q = 0
    ver_q = 0
    for m in parsed.modes:
        mid = normalize_mode_id(m.id, m.decision, m.name)
        if mid is None or mid not in active_mode_ids or mid in by_mode:
            continue
        q_out: list[dict[str, Any]] = []
        for q in m.quotes:
            total_q += 1
            ok, res_t, clean_q = verify_quote_item(q.episode, q.t, q.quote, blocks, records_by_key)
            if ok:
                ver_q += 1
            else:
                unverified.append({"mode_id": mid, "episode": q.episode, "quote": q.quote})
            q_out.append(
                {
                    "episode": q.episode.strip(),
                    "t": res_t,
                    "quote": clean_q,
                    "verified": ok,
                }
            )
        by_mode[mid] = {
            "id": mid,
            "name": clean_text(m.name).strip()[:64],
            "description": clean_text(m.description).strip()[:450],
            "quotes": q_out,
        }
    missing = [mid for mid in active_mode_ids if mid not in by_mode or not by_mode[mid]["quotes"]]
    all_ok = (not missing) and total_q > 0 and ver_q == total_q
    return {
        "ok": all_ok,
        "reason": None if all_ok else "incomplete_or_unverified",
        "summary": clean_text(parsed.summary).strip()[:950],
        "missing_modes": missing,
        "total_quotes": total_q,
        "verified_quotes": ver_q,
        "unverified": unverified,
        "by_mode": by_mode,
    }


def deterministic_quotes_for_mode(
    mode_id: str,
    records: list[dict[str, Any]],
    blocks: dict[str, str],
    records_by_key: dict[str, dict[str, Any]],
    max_quotes: int = 2,
) -> list[dict[str, Any]]:
    pool = [r for r in records if mode_id in r["modes_present"]]
    if not pool:
        pool = list(records)
    pool.sort(
        key=lambda r: (
            float(r["mode_regrets"].get(mode_id, 0.0)),
            not bool(r["episode"].get("correct")),
            float(r["total_regret"]),
        ),
        reverse=True,
    )
    target_tokens = {
        "premature-accusation": ("premature_accusation", " accuse ", "accuse("),
        "uninformative-canary": ("uninformative_canary", " plant_canary ", "plant_canary("),
        "subthreshold-commit": (" accuse r=", "accuse("),
        "over-restriction": (" restrict_access ", "restrict_access("),
        "ignored-delay": ("ignored_delay", " accuse "),
        "late-commit": (" advance_day r=", "end=horizon", "(no accusation)"),
    }[mode_id]

    quotes: list[dict[str, Any]] = []
    for rec in pool[:max_quotes]:
        blk_lines = blocks[rec["key"]].splitlines()
        chosen = None
        for ln in blk_lines:
            if ln.startswith("transcript ") and len(ln) <= 210:
                chosen = ln
        if chosen is None:
            for tok in target_tokens:
                chosen = next((ln for ln in blk_lines if tok in ln and len(ln) <= 210), None)
                if chosen is not None:
                    break
        if chosen is None:
            chosen = blk_lines[0][:210]
        ok, res_t, clean_q = verify_quote_item(rec["key"], rec["posteriors"]["decision_t"], chosen, blocks, records_by_key)
        if ok:
            quotes.append({"episode": rec["key"], "t": res_t, "quote": clean_q, "verified": True})
    return quotes


def resolve_mode_chart(out_dir: Path, mode_id: str) -> str:
    rel = MODE_SPECS[mode_id].get("chart_rel") or ""
    if not rel:
        return ""
    out_resolved = out_dir.resolve()
    cand = (out_resolved / rel).resolve()
    try:
        cand.relative_to(out_resolved.parent)
    except ValueError:
        return ""
    if cand.is_file() and cand.stat().st_size <= 400_000:
        return rel
    return ""


def build_synthesis_prompt(
    corpus_prefix: str,
    corpus_summary: dict[str, Any],
    active_mode_ids: list[str],
    retry_note: str = "",
) -> str:
    mode_brief = [
        {
            "id": mid,
            "decision": MODE_SPECS[mid]["decision"],
            "episodes": corpus_summary["mode_stats"][mid]["episodes"],
            "regret_share": corpus_summary["mode_stats"][mid]["regret_share"],
            "regret_sum": corpus_summary["mode_stats"][mid]["regret_sum"],
            "criteria": MODE_SPECS[mid]["default_description"],
        }
        for mid in active_mode_ids
    ]
    meta_json = json.dumps(
        {
            "episodes": corpus_summary["n_episodes"],
            "total_regret": corpus_summary["total_regret"],
            "accusation_posteriors": {
                k: v
                for k, v in corpus_summary["accusation_posteriors"].items()
                if k != "by_version_agent_tier"
            },
            "active_modes": mode_brief,
        },
        separators=(",", ":"),
    )
    task = (
        "\n\nTASK 1 (FAILURE ATLAS SYNTHESIS):\n"
        f"CORPUS_AGGREGATES: {meta_json}\n"
        f"Produce AtlasSynthesisOutput with summary (<= 900 chars) and exactly {len(active_mode_ids)} modes, "
        f"one for each active mode id in {active_mode_ids}. Use those exact id and decision strings. "
        "For each mode, provide 2 to 3 exact verbatim single-line quotes copied character-for-character from "
        "episodes exhibiting that failure mode (or 1 quote if only 1 episode exists in the corpus). "
        "Prefer quoting 'transcript t=...:' lines that capture the agent's own reasoning words when available, "
        "or exact 'regret t=...' / 't=... d...' lines."
    )
    if retry_note:
        task += "\nRETRY_DIAGNOSTIC: " + retry_note
    return corpus_prefix + task


def build_sample_prompt(
    corpus_prefix: str,
    active_mode_ids: list[str],
    sample_records: list[dict[str, Any]],
    retry_note: str = "",
) -> str:
    mode_defs = [
        {
            "id": mid,
            "decision": MODE_SPECS[mid]["decision"],
            "definition": MODE_SPECS[mid]["default_description"],
        }
        for mid in active_mode_ids
    ]
    sample_keys = [r["key"] for r in sample_records]
    task = (
        "\n\nTASK 2 (STRATIFIED EPISODE FAILURE CLASSIFICATION):\n"
        f"ALLOWED_MODES: {json.dumps(mode_defs, separators=(',', ':'))}\n"
        f"SAMPLE_EPISODES ({len(sample_keys)}): {json.dumps(sample_keys)}\n"
        "For every episode key in SAMPLE_EPISODES, inspect its trajectory, accusation posterior, and step-level "
        "regret signals in the corpus above, and assign the single primary failure mode_id from ALLOWED_MODES "
        "that accounts for the dominant decision failure in that episode."
    )
    if retry_note:
        task += "\nRETRY_DIAGNOSTIC: " + retry_note
    return corpus_prefix + task


def compute_agreement(
    sample_records: list[dict[str, Any]],
    llm_labels: dict[str, str],
    active_mode_ids: list[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    agree_n = 0
    by_mode: dict[str, dict[str, int]] = {
        mid: {"solver_count": 0, "llm_count": 0, "agree_count": 0} for mid in active_mode_ids
    }
    default_mid = active_mode_ids[0]
    for rec in sample_records:
        s_mode = rec["solver_primary_mode"]
        if s_mode not in by_mode:
            s_mode = default_mid
        l_mode = llm_labels.get(rec["key"], default_mid)
        if l_mode not in by_mode:
            l_mode = default_mid
        ok = s_mode == l_mode
        if ok:
            agree_n += 1
            by_mode[s_mode]["agree_count"] += 1
        by_mode[s_mode]["solver_count"] += 1
        by_mode[l_mode]["llm_count"] += 1
        rows.append(
            {
                "episode": rec["key"],
                "tier": clean_text(rec["episode"].get("tier")),
                "agent": clean_text(rec["episode"].get("agent")),
                "outcome": episode_outcome_bucket(rec),
                "total_regret": round(float(rec["total_regret"]), 4),
                "solver_mode": s_mode,
                "llm_mode": l_mode,
                "agree": ok,
            }
        )
    total = len(rows)
    rate = round(agree_n / max(1, total), 4)
    return {
        "agree": agree_n,
        "total": total,
        "rate": rate,
        "labeler": "canary.solver.regret.attribute",
        "method": "stratified_episode_primary_mode",
        "by_mode": by_mode,
        "sample": rows,
    }


def render_atlas_markdown(atlas: dict[str, Any]) -> str:
    c = atlas["corpus"]
    qv = atlas["quote_verification"]
    ag = atlas["agreement"]
    ap = atlas["accusation_posteriors"]
    run_ids_str = ", ".join(f"`{rid}`" for rid in atlas["ledger_run_ids"])
    lines = [
        f"# Canary Lab Failure Atlas ({atlas['model']}, source={atlas['source']})",
        "",
        clean_text(atlas["summary"]),
        "",
        "## Provenance and Verification Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Generated At | `{atlas['generated_at']}` |",
        f"| Git SHA | `{atlas['git_sha']}` |",
        f"| Model | `{atlas['model']}` |",
        f"| Source | `{atlas['source']}` (synthetic=`{atlas['synthetic']}`) |",
        f"| Ledger Run IDs | {run_ids_str} |",
        f"| Corpus Episodes | `{c['episodes']}` (`{c['invalid_skipped']}` invalid skipped) |",
        f"| Corpus Input / Cached Tokens | `{c['tokens']:,}` input / `{c['cached_tokens']:,}` cached (`{c['single_pack_tokens']:,}` per corpus pack) |",
        f"| Output / Thinking Tokens | `{c['out_tokens']:,}` output / `{c['thinking_tokens']:,}` thinking (`{c['calls']}` calls, `${c['cost_usd']:.4f}`) |",
        f"| Total Solver Regret | `{c['total_regret']:.4f} V` |",
        f"| Verbatim Quote Verification | `{qv['verified']} / {qv['total']}` (`{qv['pct']:.1f}%`) |",
        f"| Solver-vs-LLM Stratified Agreement | `{ag['agree']} / {ag['total']}` (`{ag['rate'] * 100:.1f}%`) |",
        "",
        "## Accusation Posteriors and Corpus Breakdown",
        "",
        (
            f"Across `{ap['n_accusations']}` accusations (`{ap['n_no_accusation']}` horizon abstentions), "
            f"mean Bayesian posterior `P(accused)` is `{ap['mean_p_accused']}` overall "
            f"(`{ap['mean_p_accused_correct']}` on correct accusations vs `{ap['mean_p_accused_wrong']}` on wrong "
            f"accusations), with `{ap['below_ev_threshold_count']}` accusations below the rational EV threshold "
            f"`-wrong / (V - wrong)` and `{ap['below_0_6_count']}` below `0.60`."
        ),
        "",
        "| Tiers | Agent | Tier | Episodes | Mean Score | Accuracy | Mean P(accused) | Total Regret (V) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for g in ap["by_version_agent_tier"]:
        mp = "n/a" if g["mean_p_accused"] is None else f"{g['mean_p_accused']:.4f}"
        lines.append(
            f"| `{g['tiers_version']}` | `{g['agent']}` | `{g['tier']}` | {g['episodes']} | "
            f"{g['mean_score']:+.3f} | {g['accuracy']:.0%} | {mp} | {g['total_regret']:.4f} |"
        )
    lines += [
        "",
        "## Failure Modes Ranked by Deterministic Solver Regret Share",
        "",
        "| Rank | Mode ID | Name | Decision | Regret Share | Total Regret (V) | Episodes | Verified Quotes |",
        "|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for idx, m in enumerate(atlas["modes"], start=1):
        vq = sum(1 for q in m["quotes"] if q["verified"])
        lines.append(
            f"| {idx} | `{m['id']}` | {clean_text(m['name'])} | `{m['decision']}` | "
            f"{m['regret_share'] * 100:.2f}% | {m['regret_sum']:.4f} | {m['episodes']} | {vq}/{len(m['quotes'])} |"
        )
    lines.append("")
    for idx, m in enumerate(atlas["modes"], start=1):
        lines += [
            f"### {idx}. {clean_text(m['name'])} (`{m['id']}`)",
            "",
            f"- Decision: `{m['decision']}` | Regret Share: `{m['regret_share'] * 100:.2f}%` (`{m['regret_sum']:.4f} V`) | Affected Episodes: `{m['episodes']}`",
            "",
            clean_text(m["description"]),
            "",
            "Verbatim verified quotes:",
            "",
        ]
        for q in m["quotes"]:
            lines.append(f"> `{q['episode']}` (step `{q['t']}`, verified=`{q['verified']}`): `{clean_text(q['quote'])}`")
        lines.append("")
    lines += [
        f"## Stratified Solver-vs-LLM Agreement Audit (n={ag['total']})",
        "",
        (
            "Episodes are sampled deterministically in round-robin order across `(tier, outcome_stratum)` buckets "
            "and evaluated by comparing the deterministic primary regret mode from `canary.solver.regret.attribute` "
            f"against independent `{atlas['model']}` episode classifications: `{ag['agree']} / {ag['total']}` "
            f"(`{ag['rate'] * 100:.1f}%`) exact mode agreement."
        ),
        "",
        "| Episode | Tier | Outcome | Regret (V) | Solver Mode | Gemini Mode | Agree |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in ag["sample"]:
        mark = "yes" if row["agree"] else "no"
        lines.append(
            f"| `{row['episode']}` | `{row['tier']}` | `{row['outcome']}` | {row['total_regret']:.4f} | "
            f"`{row['solver_mode']}` | `{row['llm_mode']}` | `{mark}` |"
        )
    lines.append("")
    return clean_text("\n".join(lines).rstrip() + "\n")


def build_atlas(
    runs_root: str | Path = DEFAULT_RUNS,
    llm: Any = DEFAULT_LLM,
    out_dir: str | Path = DEFAULT_OUT,
    run_id: str = DEFAULT_RUN_ID,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    require_llm: bool | None = None,
    families: tuple[str, ...] | None = FRONTIER_FAMILIES,
) -> dict[str, Any]:
    if require_llm is None:
        require_llm = isinstance(llm, str) and not llm.startswith("stub")

    records, corpus_summary = load_atlas_corpus(runs_root=runs_root, families=families)
    if not records:
        raise ValueError(f"no valid episodes found under {runs_root}")

    records_by_key = {r["key"]: r for r in records}
    packed_text, blocks = pack_atlas_corpus(records)
    corpus_prefix = "PACKED_TRAJECTORY_CORPUS:\n" + packed_text

    active_mode_ids = [m for m in MODE_ORDER if corpus_summary["mode_stats"][m]["active"]]
    if not active_mode_ids:
        active_mode_ids = ["uninformative-canary"]

    sample_records = select_stratified_sample(records, sample_size=sample_size)
    out_path = Path(out_dir)

    client = build_atlas_client(llm, run_id=run_id)
    session = AtlasSession(client)

    synth_prompt = build_synthesis_prompt(corpus_prefix, corpus_summary, active_mode_ids)
    parsed_synth, synth_err = session.call_structured(SYSTEM_PROMPT, synth_prompt, AtlasSynthesisOutput)
    audit = audit_synthesis(parsed_synth, active_mode_ids, blocks, records_by_key)

    if require_llm and not audit["ok"]:
        diag = json.dumps(
            {
                "error": synth_err or audit["reason"],
                "missing_modes": audit["missing_modes"],
                "unverified_quotes": audit["unverified"][:6],
            },
            separators=(",", ":"),
        )
        retry_prompt = build_synthesis_prompt(
            corpus_prefix,
            corpus_summary,
            active_mode_ids,
            retry_note=(
                f"Previous output failed strict verification ({diag}). Return all active mode ids in "
                f"{active_mode_ids} and copy every quote.quote verbatim as an exact single-line substring from "
                "inside quote.episode."
            ),
        )
        parsed_synth, synth_err = session.call_structured(SYSTEM_PROMPT, retry_prompt, AtlasSynthesisOutput)
        audit = audit_synthesis(parsed_synth, active_mode_ids, blocks, records_by_key)

    source = "llm" if audit["ok"] else "fallback"
    if require_llm and source != "llm":
        raise AssertionError(
            f"expected 100% verified LLM synthesis, got source={source!r}, err={synth_err!r}, audit={audit}"
        )

    llm_sample_labels: dict[str, str] = {}
    if source == "llm":
        sample_prompt = build_sample_prompt(corpus_prefix, active_mode_ids, sample_records)
        parsed_sample, sample_err = session.call_structured(SYSTEM_PROMPT, sample_prompt, AtlasSampleOutput)
        sample_key_set = {r["key"] for r in sample_records}
        if parsed_sample is not None:
            for item in parsed_sample.labels:
                ep_k = item.episode.strip()
                mid = normalize_mode_id(item.mode_id, "", item.mode_id)
                if ep_k in sample_key_set and mid in active_mode_ids:
                    llm_sample_labels[ep_k] = mid
        missing_sample = [r["key"] for r in sample_records if r["key"] not in llm_sample_labels]
        if require_llm and missing_sample:
            retry_sample_prompt = build_sample_prompt(
                corpus_prefix,
                active_mode_ids,
                sample_records,
                retry_note=(
                    f"Previous sample classification missed or used invalid mode_id for {missing_sample[:10]} "
                    f"(err={sample_err}). Return a valid mode_id in {active_mode_ids} for all {len(sample_records)} "
                    "SAMPLE_EPISODES."
                ),
            )
            parsed_sample2, sample_err2 = session.call_structured(SYSTEM_PROMPT, retry_sample_prompt, AtlasSampleOutput)
            if parsed_sample2 is not None:
                for item in parsed_sample2.labels:
                    ep_k = item.episode.strip()
                    mid = normalize_mode_id(item.mode_id, "", item.mode_id)
                    if ep_k in sample_key_set and mid in active_mode_ids:
                        llm_sample_labels[ep_k] = mid
            missing_sample = [r["key"] for r in sample_records if r["key"] not in llm_sample_labels]
            if missing_sample:
                raise AssertionError(
                    f"LLM sample classification missing {len(missing_sample)} episodes: {missing_sample[:5]} "
                    f"(err={sample_err2})"
                )
    else:
        for rec in sample_records:
            s_mid = rec["solver_primary_mode"]
            llm_sample_labels[rec["key"]] = s_mid if s_mid in active_mode_ids else active_mode_ids[0]

    modes_out: list[dict[str, Any]] = []
    for mid in active_mode_ids:
        spec = MODE_SPECS[mid]
        m_stat = corpus_summary["mode_stats"][mid]
        if source == "llm":
            m_llm = audit["by_mode"][mid]
            name = m_llm["name"]
            desc = m_llm["description"]
            quotes = m_llm["quotes"]
        else:
            name = spec["default_name"]
            desc = spec["default_description"]
            quotes = deterministic_quotes_for_mode(mid, records, blocks, records_by_key)
        modes_out.append(
            {
                "id": mid,
                "name": clean_text(name),
                "description": clean_text(desc),
                "decision": spec["decision"],
                "regret_share": m_stat["regret_share"],
                "regret_sum": m_stat["regret_sum"],
                "episodes": m_stat["episodes"],
                "quotes": quotes,
                "chart": resolve_mode_chart(out_path, mid),
            }
        )

    modes_out.sort(key=lambda m: (-float(m["regret_share"]), -int(m["episodes"]), m["id"]))

    all_quotes = [q for m in modes_out for q in m["quotes"]]
    for q in all_quotes:
        ok, _, _ = verify_quote_item(q["episode"], q["t"], q["quote"], blocks, records_by_key)
        q["verified"] = bool(ok)
    n_verified = sum(1 for q in all_quotes if q["verified"])
    n_total_quotes = len(all_quotes)
    if n_total_quotes == 0 or n_verified != n_total_quotes:
        raise AssertionError(f"quote verification failed: {n_verified}/{n_total_quotes} verified")

    agreement = compute_agreement(sample_records, llm_sample_labels, active_mode_ids)

    prompt_tokens = sum(int(c["prompt_tokens"]) for c in session.calls)
    cached_tokens = sum(int(c["cached_tokens"]) for c in session.calls)
    out_tokens = sum(int(c["out_tokens"]) for c in session.calls)
    thinking_tokens = sum(int(c["thinking_tokens"]) for c in session.calls)
    cost_usd = round(sum(float(c["cost_usd"]) for c in session.calls), 6)
    single_pack_tokens = int(session.calls[0]["prompt_tokens"]) if session.calls else 0

    summary_text = (
        audit["summary"]
        if source == "llm"
        else (
            f"Deterministic solver regret fallback across {corpus_summary['n_episodes']} frontier episodes "
            f"({corpus_summary['total_regret']:.4f} V total solver regret across {len(modes_out)} failure modes)."
        )
    )

    atlas_payload = redact(
        clean_obj(
            {
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "git_sha": short_git_sha(),
                "ledger_run_ids": [run_id],
                "synthetic": source != "llm",
                "source": source,
                "model": session.model_name if source == "llm" else (session.model_name or "stub"),
                "summary": summary_text,
                "modes": modes_out,
                "corpus": {
                    "episodes": corpus_summary["n_episodes"],
                    "invalid_skipped": corpus_summary["n_invalid_skipped"],
                    "tokens": prompt_tokens,
                    "cached_tokens": cached_tokens,
                    "single_pack_tokens": single_pack_tokens,
                    "out_tokens": out_tokens,
                    "thinking_tokens": thinking_tokens,
                    "cost_usd": cost_usd,
                    "calls": len(session.calls),
                    "packed_chars": len(packed_text),
                    "total_regret": corpus_summary["total_regret"],
                    "files_loaded": corpus_summary["files_loaded"],
                    "by_version_agent_tier": corpus_summary["by_version_agent_tier"],
                },
                "quote_verification": {
                    "verified": n_verified,
                    "total": n_total_quotes,
                    "rate": round(n_verified / n_total_quotes, 4),
                    "pct": round(100.0 * n_verified / n_total_quotes, 2),
                    "all_verified": n_verified == n_total_quotes,
                },
                "agreement": agreement,
                "human_agreement": {
                    "agree": agreement["agree"],
                    "total": agreement["total"],
                    "rate": agreement["rate"],
                    "labeler": "canary.solver.regret.attribute (stratified audit)",
                },
                "accusation_posteriors": corpus_summary["accusation_posteriors"],
            }
        )
    )

    atlas_md = render_atlas_markdown(atlas_payload)
    atlas_json_text = clean_text(json.dumps(atlas_payload, indent=2, ensure_ascii=True)) + "\n"

    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "atlas.json").write_text(atlas_json_text, encoding="utf-8")
    (out_path / "atlas.md").write_text(atlas_md, encoding="utf-8")
    return atlas_payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=str(DEFAULT_RUNS))
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    ap.add_argument("--require-llm", action="store_true")
    args = ap.parse_args(argv)

    require_llm = True if args.require_llm else (not str(args.llm).startswith("stub"))
    atlas = build_atlas(
        runs_root=args.runs,
        llm=args.llm,
        out_dir=args.out,
        run_id=args.run_id,
        sample_size=args.sample_size,
        require_llm=require_llm,
    )
    qv = atlas["quote_verification"]
    ag = atlas["agreement"]
    cp = atlas["corpus"]
    print(
        f"model={atlas['model']} source={atlas['source']} episodes={cp['episodes']} "
        f"modes={len(atlas['modes'])} quotes={qv['verified']}/{qv['total']} "
        f"agreement={ag['agree']}/{ag['total']} ({ag['rate'] * 100:.1f}%) "
        f"tokens={cp['tokens']} cached={cp['cached_tokens']} cost=${cp['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
