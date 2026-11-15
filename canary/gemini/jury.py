"""Calibrated 3-model Gemini Jury over every high-regret Canary decision step.

    python -m canary.gemini.jury [--out results/gemini/scale/jury] [--concurrency 24] [--replay]

Judges see ONLY the causal blind trajectory up to decision step t (agent-visible rules, tool calls,
tool results and the agent's own words; never REGRET, code tags, solver beliefs, true_mole or final
outcome). Each judge independently labels the decision from a closed taxonomy (tags.py tags + 'other'
+ 'not_a_mistake') with a stated confidence in [0, 1]. All calls are ledgered (feature='jury') and
stored in responses.jsonl.gz so `--replay` rebuilds jury.json, jury.md and calibration.png with 0 calls.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from canary.analysis.tags import WHY as TAG_WHY
from .atlas_data import (
    HIGH_REGRET,
    ROOT,
    agent_identity,
    align_rationale,
    belief_trace,
    compact_args,
    find_run_dirs,
    infer_version,
    load_transcript,
    thinking_of,
)
from .atlas_schema import inline_schema, parse
from .ledger import record

FEATURE = "jury"
DEFAULT_OUT = ROOT / "results" / "gemini" / "scale" / "jury"
DEFAULT_COMMITTED = ROOT / "data" / "runs" / "committed"
DEFAULT_LADDER = ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz"
DEFAULT_LADDER30 = Path.home() / "agent-arena-data" / "gemini" / "scale" / "ladder30"
DEFAULT_JUDGES = ("gemini-4-hydrogen", "gemini-4-argon", "gemini-3.8-flash")
THINKING_SWEEP = ("low", "medium", "high")
PRIMARY_LEVEL = "medium"

CODE_TAGS = tuple(TAG_WHY.keys())
TAXONOMY = CODE_TAGS + ("other", "not_a_mistake")
LabelLiteral = Literal[
    "premature_accusation",
    "decoy_chase",
    "ignored_delay",
    "uninformative_canary",
    "over_restriction",
    "budget_waste",
    "no_accusation",
    "other",
    "not_a_mistake",
]

BLIND_FORBIDDEN_ANYWHERE = (
    "REGRET",
    "top=",
    "mole:",
    "true_mole",
    "total_regret",
    "solver_same_seed",
    "[premature_accusation",
    "[decoy_chase",
    "[ignored_delay",
    "[uninformative_canary",
    "[over_restriction",
    "[budget_waste",
    "[no_accusation",
)
BLIND_FORBIDDEN_CODE_LINES = ("regret", "solver", *CODE_TAGS)

SYSTEM_PROMPT = """You are an independent calibration judge for Canary, an insider-threat investigation game.
An agent (security lead) investigates employees e00..eN over a fixed horizon of days using documents, leak feed,
canary traps (per-recipient document variants), access logs, message search, interviews, and access restrictions,
aiming to make one accusation (`accuse`). Correct accusation scores remaining company value V; wrong accusation
scores -1; ending without accusation scores 0.

You see ONLY what the agent had seen and said up to the target step marked `>>>`. You do NOT see future steps or
whether any accusation was right. Judge ONLY the single decision marked `>>>` and choose ONE label from this closed
taxonomy:
- `premature_accusation`: `accuse(employee)` when the evidence up to `>>>` leaves that employee's probability of
  being the mole below 0.60 (multiple suspects remain consistent with leaked documents/canary variants, or the
  agent relied on noisy logs / a single noisy canary / guesswork).
- `decoy_chase`: `accuse` or `restrict_access` targeting the decoy (the disgruntled innocent employee who sends
  repeated angry messages and receives framed after-hours log entries).
- `ignored_delay`: `accuse` while a recent closed day's leak could still surface in the leak feed within the tier's
  leak delay window, before the suspect's probability is overwhelming (< 0.90).
- `uninformative_canary`: a successful `plant_canary` whose variant assignment splits the currently plausible
  suspects very poorly (Gini split < 0.20 of plausible suspect probability mass — e.g. putting almost all viable
  suspects into one variant, or covering <=10% of suspect mass while leaving ~90% outside).
- `over_restriction`: a successful `restrict_access(employee)` on someone whom the evidence already makes very
  unlikely (< 0.10 probability, e.g. excluded by leaked document recipient sets or canary variants).
- `budget_waste`: a failed tool call (`ERR ...`) or repeating an identical investigative call on the same day.
- `no_accusation`: ending the final day without accusing despite decisive evidence.
- `other`: a suboptimal decision that loses expected value at `>>>` but does not fit the specific rules above
  (e.g. calling `advance_day` when one suspect is already >= 0.90 certain; a partial canary split with Gini >= 0.20
  that still leaves out several plausible suspects; accusing at moderate 0.60-0.80 confidence when one more canary
  is clearly better; or restricting a >= 0.10 suspect too early when daily restriction cost exceeds probing value).
- `not_a_mistake`: at `>>>`, given ONLY observations so far, the decision is sound or reasonable play (e.g. accusing
  the clear leading suspect at high confidence >= 0.85, or planting a well-targeted canary split across top suspects).

State a calibrated `confidence` between 0.0 and 1.0 reflecting the probability your chosen label is right."""


class JuryVerdict(BaseModel):
    label: LabelLiteral
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated probability in [0, 1] that label is accurate")
    rationale: str = Field(description="One short sentence grounded in observations up to >>>")


@dataclass
class JuryStep:
    t: int
    day: int
    tool: str
    args: dict
    result: Any
    ok: bool
    regret: float
    tags: list[str]
    p_best: float | None
    p_accused: float | None
    rationale: str = ""


@dataclass
class JuryEpisode:
    id: str
    source: str
    agent: str
    family: str
    model: str
    harness: str
    tier: str
    tiers_version: str
    seed: int
    thinking_level: str
    score: float
    correct: bool
    accused: str | None
    final_day: int
    end_reason: str
    steps: list[JuryStep] = field(default_factory=list)
    terminal_regret: float = 0.0

    @property
    def total_regret(self) -> float:
        return round(sum(s.regret for s in self.steps) + self.terminal_regret, 6)


class ReplayMiss(RuntimeError):
    pass


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _model_short(model: str) -> str:
    m = model.lower().replace("gemini-", "g").replace("gpt-", "gpt")
    return re.sub(r"[^a-z0-9.]+", "", m)[:14]


def _build_episode(raw: dict, meta: dict, version: str, source: str, rats: list[str]) -> JuryEpisode:
    from canary.analysis.tags import to_result
    from canary.solver.regret import attribute

    family, model, harness = agent_identity(raw.get("agent", ""), meta)
    steps_raw = raw.get("steps") or []
    rows = attribute(to_result(raw))
    by_t = {r["t"]: r for r in rows if isinstance(r.get("t"), int) and r.get("action") != "(no accusation)"}
    terminal = sum(float(r.get("regret", 0.0)) for r in rows if r.get("action") == "(no accusation)")
    steps: list[JuryStep] = []
    for k, s in enumerate(steps_raw):
        t = int(s.get("t", k))
        r = by_t.get(t, {})
        res = s.get("result")
        ok = (res or {}).get("ok", True) if isinstance(res, dict) else True
        steps.append(
            JuryStep(
                t=t,
                day=int(s.get("day", 0)),
                tool=str(s.get("tool", "")),
                args=dict(s.get("args") or {}),
                result=res,
                ok=bool(ok),
                regret=float(r.get("regret", 0.0)),
                tags=list(r.get("tags", [])),
                p_best=r.get("p_best"),
                p_accused=r.get("p_accused"),
                rationale=rats[k] if k < len(rats) else "",
            )
        )
    em = raw.get("meta") or {}
    lad = em.get("ladder") or {}
    lv = str(lad.get("level") or thinking_of(meta, em)).lower()
    if lad.get("model"):
        _, model, _ = agent_identity(f"gemini:{lad['model']}", meta)
    return JuryEpisode(
        id="",
        source=source,
        agent=str(raw.get("agent", "")),
        family=family,
        model=model,
        harness=harness,
        tier=str(raw["tier"]),
        tiers_version=str(lad.get("tiers_version") or version),
        seed=int(raw["seed"]),
        thinking_level=lv,
        score=float(raw.get("score", 0.0)),
        correct=bool(raw.get("correct")),
        accused=raw.get("accused"),
        final_day=int(raw.get("final_day", 0)),
        end_reason=str(raw.get("end_reason", "")),
        steps=steps,
        terminal_regret=round(terminal, 6),
    )


def load_all_episodes(
    committed_dir: Path = DEFAULT_COMMITTED,
    ladder_gz: Path = DEFAULT_LADDER,
    ladder30_dir: Path | None = None,
) -> tuple[list[JuryEpisode], dict[str, int]]:
    """Load all valid committed episodes from data/runs/committed, ladder_episodes.jsonl.gz, and ladder30 if present."""
    skip_agents = {"solver", "random", "heuristic", "do_nothing", "stop_early", "restrict_all", "grok_tactics"}
    eps: list[JuryEpisode] = []
    counts = {"committed_valid": 0, "committed_excluded_infra": 0, "ladder_valid": 0, "ladder_excluded_infra": 0,
              "ladder30_valid": 0, "ladder30_deduped": 0}
    seen_keys: set[tuple[str, str, str, str, int, int]] = set()

    if committed_dir and Path(committed_dir).exists():
        for d in find_run_dirs([committed_dir]):
            if "reference" in d.parts:
                continue
            meta = {}
            if (d / "meta.json").exists():
                try:
                    meta = json.loads((d / "meta.json").read_text())
                except json.JSONDecodeError:
                    meta = {}
            version = infer_version(str(d), meta)
            tr = {p.stem: p for p in (d / "transcripts").glob("*")} if (d / "transcripts").is_dir() else {}
            for line in (d / "episodes.jsonl").read_text().splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                if raw.get("agent") in skip_agents:
                    continue
                if (raw.get("meta") or {}).get("valid") is False or raw.get("end_reason") == "error":
                    counts["committed_excluded_infra"] += 1
                    continue
                steps_raw = raw.get("steps") or []
                calls, _ = load_transcript(tr[str(raw["seed"])]) if str(raw["seed"]) in tr else ([], "none")
                rats = align_rationale(steps_raw, calls) if calls else [""] * len(steps_raw)
                ep = _build_episode(raw, meta, version, "data/runs/committed", rats)
                eps.append(ep)
                seen_keys.add((ep.model, ep.thinking_level, ep.harness, ep.tier, ep.seed, len(ep.steps)))
                counts["committed_valid"] += 1

    if ladder_gz and Path(ladder_gz).exists():
        with gzip.open(ladder_gz, "rt") as fh:
            for line in fh:
                if not line.strip():
                    continue
                raw = json.loads(line)
                if (raw.get("meta") or {}).get("valid") is False or raw.get("end_reason") == "error":
                    counts["ladder_excluded_infra"] += 1
                    continue
                ep = _build_episode(raw, {}, "v1.4", "results/gemini/ladder_episodes.jsonl.gz", [])
                key = (ep.model, ep.thinking_level, ep.harness, ep.tier, ep.seed, len(ep.steps))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                eps.append(ep)
                counts["ladder_valid"] += 1

    if ladder30_dir and Path(ladder30_dir).exists():
        for f in sorted(Path(ladder30_dir).glob("*/*/*/*/episodes.jsonl")):
            model, level, tier, _ = f.parent.relative_to(ladder30_dir).parts
            if model.startswith("_"):
                continue
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                if (raw.get("meta") or {}).get("valid") is False or raw.get("end_reason") == "error":
                    continue
                ep = _build_episode(raw, {"model": model, "thinking_level": level}, "v1.4", "scale/ladder30", [])
                key = (ep.model, ep.thinking_level, ep.harness, ep.tier, ep.seed, len(ep.steps))
                if key in seen_keys:
                    counts["ladder30_deduped"] += 1
                    continue
                seen_keys.add(key)
                eps.append(ep)
                counts["ladder30_valid"] += 1

    id_counts: dict[str, int] = {}
    for ep in eps:
        ver = ep.tiers_version.replace("v", "").replace(".", "")
        lv = "" if ep.thinking_level == "default" else f"-{ep.thinking_level}"
        src_tag = "lad" if "ladder" in ep.source else ep.harness[:2]
        base = f"{_model_short(ep.model)}{lv}.{src_tag}.v{ver}.{ep.tier[0]}{ep.seed}"
        n = id_counts.get(base, 0)
        id_counts[base] = n + 1
        ep.id = base if n == 0 else f"{base}#{n}"
    eps.sort(key=lambda e: e.id)
    return eps, counts


# --------------------------------------------------------------------------- Blind Causal Packing

_RULES_LINE_CACHE: dict[str, str] = {}
_BLIND_VIEW_CACHE: dict[tuple[str, int], str] = {}


def _tier_rules_line(ep: JuryEpisode) -> str:
    """Public game parameters shown to the agent in Env.instruction() (no hidden state)."""
    if ep.id and ep.id in _RULES_LINE_CACHE:
        return _RULES_LINE_CACHE[ep.id]
    from canary.rules import tier_params_for_episode
    from canary.types import Step

    st_objs = [Step(t=s.t, day=s.day, tool=s.tool, args=s.args, result=s.result) for s in ep.steps]
    p = tier_params_for_episode(ep.tier, st_objs)
    vis = "true_V" if ep.tiers_version == "v1.2" else "known_V_surfaced_only"
    delays = "/".join(str(x) for x in p.delay_choices)
    out = (
        f"rules: version={ep.tiers_version} tier={ep.tier} employees={p.n_employees} days={p.n_days} "
        f"actions_per_day={p.actions_per_day} canaries_per_day={p.canaries_per_day} max_variants={p.max_variants} "
        f"fingerprint_acc={p.fingerprint_accuracy} p_leak={p.p_leak} leak_window={p.leak_window_days}d "
        f"feed_delay={delays}d canary_cost={p.canary_cost} leak_damage={p.leak_damage} "
        f"restrict_cost_per_day={p.restrict_cost_per_day} wrong_accuse={p.wrong_accusation_score:g} "
        f"careful_mole={p.careful_mole} decoy={p.decoy} framing={p.framing} V_mode={vis}"
    )
    if ep.id:
        _RULES_LINE_CACHE[ep.id] = out
    return out


def _blind_result_str(tool: str, args: dict, res: Any, seen_docs: set[str], max_len: int = 220) -> str:
    if not isinstance(res, dict):
        return str(res)[:max_len]
    if not res.get("ok", True):
        return f"ERR {str(res.get('error', ''))[:160]}"
    d = res.get("data") or {}
    try:
        if tool == "list_employees":
            emps = d.get("employees") or []
            ids = [e["id"] if isinstance(e, dict) else str(e) for e in emps]
            if ids and ids == [f"e{i:02d}" for i in range(len(ids))]:
                return f"{len(ids)} staff (e00..e{len(ids) - 1:02d})"
            return f"{len(ids)} staff: {','.join(ids)}"
        if tool == "status":
            restr = ",".join(d.get("restricted") or []) or "none"
            cans = ",".join(d.get("canaries_planted") or []) or "none"
            return (f"d={d.get('day')} V={d.get('V')} restricted=[{restr}] canaries=[{cans}] "
                    f"left_today={d.get('actions_left_today')} calls_left={d.get('tool_calls_left')}")
        if tool == "list_documents":
            docs = d.get("documents") or d.get("docs") or []
            parts = []
            for x in docs:
                did = str(x.get("doc_id", ""))
                star = "*" if x.get("is_canary") else ""
                if did in seen_docs:
                    parts.append(f"{did}{star}(same)")
                else:
                    seen_docs.add(did)
                    recs = ",".join(str(r) for r in (x.get("recipients") or []))
                    parts.append(f"{did}{star}@d{x.get('day')}[{recs}]")
            return f"{len(docs)} docs: " + "; ".join(parts)
        if tool == "check_leak_feed":
            items = d.get("items") or d.get("feed") or []
            if not items:
                return "feed: empty"
            return "feed: " + "; ".join(
                f"{it.get('doc_id')}@d{it.get('surfaced_day')}" + (f" var={it['variant']}" if it.get("variant") else "")
                for it in items
            )
        if tool == "read_access_logs":
            logs = d.get("logs") or d.get("entries") or []
            ah: Counter = Counter()
            dy: Counter = Counter()
            for x in logs:
                emp = str(x.get("employee", ""))
                if x.get("after_hours"):
                    ah[emp] += 1
                else:
                    dy[emp] += 1
            ah_s = ",".join(f"{e}:{n}" for e, n in ah.most_common(10)) or "none"
            dy_s = ",".join(f"{e}:{n}" for e, n in dy.most_common(8)) or "none"
            return f"{len(logs)} logs; after_hours=[{ah_s}] daytime=[{dy_s}]"
        if tool == "search_messages":
            ms = d.get("messages") or []
            if not ms:
                return "0 msgs"
            senders = ",".join(str(m.get("sender", "?")) for m in ms)
            txt = str(ms[0].get("text", ms[0].get("body", "")))[:90]
            return f"{len(ms)} msgs senders=[{senders}] \"{txt}\""
        if tool == "interview":
            sig = d.get("signal", "")
            ans = str(d.get("answer", ""))[:130]
            return (f"signal={sig} " if sig else "") + f"\"{ans}\""
        if tool == "plant_canary":
            return f"canary {d.get('canary_id') or d.get('doc_id')}"
        if tool == "advance_day":
            nd = ",".join(str(x) for x in (d.get("new_documents") or []))
            return f"closed d{d.get('closed_day')} -> d{d.get('day')} V={d.get('V')} new=[{nd}]"
        if tool in ("restrict_access", "unrestrict_access"):
            return "ok"
        if tool == "accuse":
            return f"accused {d.get('accused')} (episode ended)"
    except Exception:  # noqa: BLE001
        pass
    return json.dumps(d, ensure_ascii=False)[:max_len]


def _sanitize_code_line(s: str) -> str:
    s = re.sub(r"mole:", "mole -", s, flags=re.IGNORECASE)
    s = re.sub(r"true_mole", "actual_culprit", s, flags=re.IGNORECASE)
    s = re.sub(r"top=", "lead=", s, flags=re.IGNORECASE)
    s = re.sub(r"regret", "loss", s, flags=re.IGNORECASE)
    s = re.sub(r"solver", "baseline", s, flags=re.IGNORECASE)
    for tg in CODE_TAGS:
        s = s.replace(tg, tg.replace("_", " "))
    return s


def sanitize_agent_words(text: str, budget: int) -> str:
    r = re.sub(r"\s+", " ", text or "").strip()
    r = re.sub(r"mole:", "mole -", r, flags=re.IGNORECASE)
    r = re.sub(r"true_mole", "actual_culprit", r, flags=re.IGNORECASE)
    r = re.sub(r"top=", "lead=", r, flags=re.IGNORECASE)
    r = re.sub(r"REGRET", "loss", r)
    for tg in CODE_TAGS:
        r = r.replace(tg, tg.replace("_", " "))
    return f"{r[:budget]}{' [...]' if len(r) > budget else ''}"


def render_blind_segments(ep: JuryEpisode, target_t: int, split_before_t: int | None = None) -> tuple[str, str]:
    """Return (prefix_text, suffix_text) for causal blind view up to `target_t` (inclusive).
    If `split_before_t` is given (e.g. first HR step in episode for explicit caching), `prefix_text` holds header +
    steps with t < split_before_t, and `suffix_text` holds steps from split_before_t..target_t + question prompt."""
    header = [
        _sanitize_code_line(f"=== EPISODE {ep.id} ==="),
        _sanitize_code_line(_tier_rules_line(ep)),
    ]
    seen_docs: set[str] = set()
    pre_lines = list(header)
    suf_lines: list[str] = []
    target_step: JuryStep | None = None
    for s in ep.steps:
        if s.t > target_t:
            break
        is_target = s.t == target_t
        if is_target:
            target_step = s
        mark = ">>> " if is_target else ""
        res_s = _blind_result_str(s.tool, s.args, s.result, seen_docs)
        line = _sanitize_code_line(f"{mark}t{s.t} d{s.day} {s.tool}({compact_args(s.tool, s.args)}) -> {res_s}")
        dest = pre_lines if (split_before_t is not None and s.t < split_before_t) else suf_lines
        dest.append(line)
        if s.rationale:
            budget = 800 if (is_target or s.tool in ("accuse", "plant_canary", "restrict_access")) else 280
            dest.append(f"   says: {sanitize_agent_words(s.rationale, budget)}")
    tool_desc = _sanitize_code_line(
        f"{target_step.tool}({compact_args(target_step.tool, target_step.args)})" if target_step else f"t={target_t}"
    )
    suf_lines.append(
        f"\nJUDGE TARGET: Evaluate ONLY step `>>> t{target_t}` (`{tool_desc}`) using ONLY the observations above. "
        "Choose one taxonomy label, a calibrated confidence in [0, 1], and a one-sentence rationale."
    )
    if split_before_t is None:
        return "", "\n".join(pre_lines + suf_lines)
    return "\n".join(pre_lines), "\n".join(suf_lines)


def build_blind_view(ep: JuryEpisode, target_t: int) -> str:
    ck = (ep.id, target_t)
    if ep.id and ck in _BLIND_VIEW_CACHE:
        return _BLIND_VIEW_CACHE[ck]
    _, full = render_blind_segments(ep, target_t, split_before_t=None)
    if ep.id:
        _BLIND_VIEW_CACHE[ck] = full
    return full


def assert_blind_view_clean(view: str) -> None:
    for tok in BLIND_FORBIDDEN_ANYWHERE:
        if tok in view:
            raise AssertionError(f"forbidden token {tok!r} leaked into blind view")
    for tg in CODE_TAGS:
        if tg in view:
            raise AssertionError(f"code tag {tg!r} leaked into blind view")
    for ln in view.splitlines():
        if ln.lstrip().startswith("says:"):
            continue
        for tok in BLIND_FORBIDDEN_CODE_LINES:
            if tok in ln:
                raise AssertionError(f"forbidden token {tok!r} leaked into non-says line: {ln[:120]}")


# --------------------------------------------------------------------------- Gemini Ops + Response Cache

def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _usage_dict(um: Any) -> dict[str, int]:
    def g(a: str) -> int:
        v = getattr(um, a, None) if um is not None else None
        return v if isinstance(v, int) else 0
    return {
        "prompt_token_count": g("prompt_token_count"),
        "candidates_token_count": g("candidates_token_count"),
        "thoughts_token_count": g("thoughts_token_count"),
        "cached_content_token_count": g("cached_content_token_count"),
    }


class JuryOps:
    """Thread-safe Gemini caller with ledgering, explicit per-episode context caching where supported,
    resumable journal + deterministic gzipped JSONL response cache (`--replay` makes 0 calls)."""

    def __init__(
        self,
        cache_file: Path,
        replay: bool = False,
        client: Any = None,
        run_id: str = "",
        max_retries: int = 12,
        allow_carbon: bool = False,
        timeout_s: float = 180.0,
    ):
        self.cache_file = Path(cache_file)
        self.journal_file = self.cache_file.with_suffix(".journal.jsonl")
        self.replay = replay
        self._client = client
        self._client_lock = threading.Lock()
        self._store_lock = threading.Lock()
        self.run_id = run_id or f"jury-{time.strftime('%Y%m%d-%H%M%S')}"
        self.max_retries = max_retries
        self.allow_carbon = allow_carbon
        self.timeout_s = timeout_s
        self.store: dict[str, dict] = {}
        self.source_run_ids: set[str] = set()
        self.stats = {
            "calls": 0, "replayed": 0, "retries": 0, "explicit_caches_created": 0,
            "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0,
        }
        self._cache_unsupported_models: set[str] = {"gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"}
        self._load_existing()

    def _load_existing(self) -> None:
        if self.cache_file.exists():
            with gzip.open(self.cache_file, "rt") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        self.store[row["key"]] = row
                        if row.get("run_id"):
                            self.source_run_ids.add(row["run_id"])
        if not self.replay and self.journal_file.exists():
            for line in self.journal_file.read_text().splitlines():
                if line.strip():
                    try:
                        row = json.loads(line)
                        self.store[row["key"]] = row
                        if row.get("run_id"):
                            self.source_run_ids.add(row["run_id"])
                    except json.JSONDecodeError:
                        continue

    def save_compacted(self) -> None:
        if self.replay:
            return
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(self.store[k], sort_keys=True, separators=(",", ":")) for k in sorted(self.store)]
        payload = ("\n".join(lines) + ("\n" if lines else "")).encode()
        tmp = self.cache_file.with_suffix(".tmp.gz")
        tmp.write_bytes(gzip.compress(payload, mtime=0))
        tmp.replace(self.cache_file)
        if self.journal_file.exists():
            self.journal_file.unlink()

    @property
    def client(self):
        with self._client_lock:
            if self._client is None:
                if self.replay:
                    raise ReplayMiss("replay mode: live client disabled")
                from .sdk import genai_client
                self._client = genai_client(timeout_s=self.timeout_s)
            return self._client

    def _check_model(self, model: str) -> None:
        if "carbon" in model.lower() and not self.allow_carbon:
            raise ValueError(f"gemini-4-carbon is forbidden in WS2 jury (got {model!r})")

    @staticmethod
    def request_key(model: str, level: str, ep_id: str, t: int, view_sha: str, schema_sha: str) -> str:
        return hashlib.sha256(f"jury_v1\n{model}\n{level}\n{ep_id}\n{t}\n{view_sha}\n{schema_sha}".encode()).hexdigest()

    def create_episode_cache(self, model: str, prefix_text: str, ttl_s: int = 600) -> str | None:
        """Create an explicit context cache for an episode prefix when supported and >= ~4200 tokens."""
        if self.replay or model in self._cache_unsupported_models or len(prefix_text) < 16800:
            return None
        self._check_model(model)
        from google.genai import types
        t0 = time.time()
        try:
            r = self.client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    contents=[types.Content(role="user", parts=[types.Part(text=prefix_text)])],
                    system_instruction=SYSTEM_PROMPT,
                    ttl=f"{ttl_s}s",
                    display_name=f"canary-jury-{hashlib.sha256(prefix_text.encode()).hexdigest()[:10]}",
                ),
            )
            um = getattr(r, "usage_metadata", None)
            n = int(getattr(um, "total_token_count", 0) or 0)
            row = record(FEATURE, model, kind="cache", latency_s=time.time() - t0, ok=True, run_id=self.run_id,
                         meta={"op": "caches.create", "cache_tokens": n}, tokens={"in": n, "out": 0})
            with self._store_lock:
                self.stats["calls"] += 1
                self.stats["explicit_caches_created"] += 1
                self.stats["in"] += row["in"]
                self.stats["cost_usd"] += row["cost_usd"]
            return r.name
        except Exception as e:  # noqa: BLE001
            record(FEATURE, model, kind="cache", latency_s=time.time() - t0, ok=False,
                   error=f"{type(e).__name__}: {str(e)[:160]}", run_id=self.run_id, meta={"op": "caches.create"})
            msg = str(e).lower()
            if "not supported" in msg or "404" in msg or "permission" in msg:
                with self._store_lock:
                    self._cache_unsupported_models.add(model)
            return None

    def delete_episode_cache(self, name: str | None) -> None:
        if name and not self.replay:
            try:
                self.client.caches.delete(name=name)
            except Exception:  # noqa: BLE001
                pass

    def judge_step(
        self,
        model: str,
        level: str,
        ep: JuryEpisode,
        t: int,
        schema: dict,
        schema_sha: str,
        cache_name: str | None = None,
        split_before_t: int | None = None,
    ) -> dict:
        self._check_model(model)
        full_view = build_blind_view(ep, t)
        view_sha = hashlib.sha256((SYSTEM_PROMPT + "\n" + full_view).encode()).hexdigest()
        key = self.request_key(model, level, ep.id, t, view_sha, schema_sha)

        with self._store_lock:
            hit = self.store.get(key)
            if hit is not None:
                self.stats["replayed"] += 1
                return hit

        if self.replay:
            raise ReplayMiss(f"missing cached jury response for {model}@{level} {ep.id} t={t} ({key[:12]})")

        from google.genai import types

        if cache_name and split_before_t is not None:
            _, user_text = render_blind_segments(ep, t, split_before_t=split_before_t)
            use_cache = True
        else:
            user_text = full_view
            use_cache = False

        max_out = 32768
        delay = 1.5
        last_err = ""
        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            cfg: dict[str, Any] = {
                "max_output_tokens": max_out,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
                "thinking_config": types.ThinkingConfig(thinking_level=level.upper()),
            }
            if use_cache and cache_name:
                cfg["cached_content"] = cache_name
            else:
                cfg["system_instruction"] = SYSTEM_PROMPT
            meta = {"op": "judge_step", "episode": ep.id, "t": t, "thinking_level": level, "explicit_cache": use_cache}
            try:
                resp = self.client.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=[types.Part(text=user_text)])],
                    config=types.GenerateContentConfig(**cfg),
                )
                um = getattr(resp, "usage_metadata", None)
                mv = getattr(resp, "model_version", None) or model
                text = ""
                try:
                    text = resp.text or ""
                except Exception:  # noqa: BLE001
                    text = ""
                parsed, perr = parse(text, JuryVerdict)
                if parsed is None:
                    raise ValueError(f"invalid structured verdict: {perr}")
                lat = time.time() - t0
                led = record(FEATURE, model, kind="generate", usage=um, latency_s=lat, ok=True,
                             run_id=self.run_id, meta={**meta, "model_version": mv})
                row = {
                    "key": key,
                    "model": model,
                    "level": level,
                    "model_version": mv,
                    "episode": ep.id,
                    "t": t,
                    "label": parsed.label,
                    "confidence": round(float(parsed.confidence), 4),
                    "rationale": parsed.rationale.strip()[:320],
                    "usage": _usage_dict(um),
                    "latency_s": round(lat, 3),
                    "cost_usd": led["cost_usd"],
                    "run_id": self.run_id,
                }
                with self._store_lock:
                    self.store[key] = row
                    self.source_run_ids.add(self.run_id)
                    self.stats["calls"] += 1
                    for k_tok in ("in", "out", "thinking", "cached"):
                        self.stats[k_tok] += led[k_tok]
                    self.stats["cost_usd"] += led["cost_usd"]
                    self.journal_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.journal_file, "a") as jf:
                        jf.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                return row
            except Exception as e:  # noqa: BLE001
                lat = time.time() - t0
                last_err = f"{type(e).__name__}: {str(e)[:180]}"
                record(FEATURE, model, kind="generate", usage=None, latency_s=lat, ok=False, error=last_err,
                       run_id=self.run_id, meta=meta)
                if use_cache and ("cachedcontent" in last_err.lower() or "404" in last_err or "expired" in last_err.lower()):
                    use_cache = False
                    user_text = full_view
                transient = any(
                    s in last_err
                    for s in ("429", "RESOURCE_EXHAUSTED", "503", "500", "UNAVAILABLE", "DEADLINE", "Timeout",
                              "timed out", "ServerError", "RemoteProtocolError", "disconnected", "invalid structured")
                )
                if not transient or attempt == self.max_retries:
                    raise
                with self._store_lock:
                    self.stats["retries"] += 1
                is_429 = "429" in last_err or "RESOURCE_EXHAUSTED" in last_err
                wait = max(delay, 25.0) if is_429 else delay
                time.sleep(min(65.0, wait) * (0.7 + 0.6 * random.random()))
                delay = min(65.0, delay * 1.7)
        raise RuntimeError(f"unreachable retry exhaustion: {last_err}")


# --------------------------------------------------------------------------- Metrics & Calibration (Code)

def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt((p * (1.0 - p) / n) + (z * z / (4.0 * n * n)))
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def bootstrap_mean_ci(vals: list[float], B: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    if not vals:
        return (0.0, 0.0, 0.0)
    mean = sum(vals) / len(vals)
    if len(vals) == 1:
        return (round(mean, 4), round(mean, 4), round(mean, 4))
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    lo = means[int(0.025 * B)]
    hi = means[int(0.975 * B)]
    return (round(mean, 4), round(lo, 4), round(hi, 4))


def fleiss_kappa(ratings: list[list[str]], categories: tuple[str, ...] = TAXONOMY) -> dict[str, Any]:
    """Exact Fleiss' kappa across N items rated by m >= 2 raters over `categories`."""
    if not ratings:
        return {"n": 0, "raters": 0, "kappa": None, "p_observed": None, "p_expected": None}
    N = len(ratings)
    m = len(ratings[0])
    if m < 2:
        return {"n": N, "raters": m, "kappa": None, "p_observed": None, "p_expected": None}
    cat_idx = {c: i for i, c in enumerate(categories)}
    K = len(categories)
    totals = [0] * K
    p_i_sum = 0.0
    for row in ratings:
        counts = [0] * K
        for lab in row:
            j = cat_idx[lab] if lab in cat_idx else cat_idx.get("other", 0)
            counts[j] += 1
            totals[j] += 1
        p_i_sum += (sum(c * c for c in counts) - m) / (m * (m - 1))
    p_bar = p_i_sum / N
    denom_tot = float(N * m)
    p_e = sum((t / denom_tot) ** 2 for t in totals)
    if abs(1.0 - p_e) < 1e-12:
        kappa = 1.0 if abs(1.0 - p_bar) < 1e-12 else 0.0
    else:
        kappa = (p_bar - p_e) / (1.0 - p_e)
    return {
        "n": N,
        "raters": m,
        "kappa": round(kappa, 4),
        "p_observed": round(p_bar, 4),
        "p_expected": round(p_e, 4),
    }


def fleiss_kappa_with_ci(
    ratings: list[list[str]],
    episode_ids: list[str] | None = None,
    categories: tuple[str, ...] = TAXONOMY,
    B: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    base = fleiss_kappa(ratings, categories)
    if len(ratings) < 2 or base["kappa"] is None:
        return {**base, "ci95": [base["kappa"], base["kappa"]], "cluster_ci95": [base["kappa"], base["kappa"]]}
    rng = random.Random(seed)
    N = len(ratings)
    boots = []
    for _ in range(B):
        sample = [ratings[rng.randrange(N)] for _ in range(N)]
        k = fleiss_kappa(sample, categories)["kappa"]
        if k is not None:
            boots.append(k)
    boots.sort()
    ci = [round(boots[int(0.025 * len(boots))], 4), round(boots[int(0.975 * len(boots))], 4)] if boots else [None, None]
    cluster_ci = ci
    if episode_ids and len(set(episode_ids)) >= 2:
        by_ep: dict[str, list[list[str]]] = defaultdict(list)
        for eid, r in zip(episode_ids, ratings):
            by_ep[eid].append(r)
        ep_keys = sorted(by_ep)
        M = len(ep_keys)
        c_boots = []
        for _ in range(B):
            samp: list[list[str]] = []
            for _ in range(M):
                samp.extend(by_ep[ep_keys[rng.randrange(M)]])
            k = fleiss_kappa(samp, categories)["kappa"]
            if k is not None:
                c_boots.append(k)
        c_boots.sort()
        if c_boots:
            cluster_ci = [round(c_boots[int(0.025 * len(c_boots))], 4), round(c_boots[int(0.975 * len(c_boots))], 4)]
    return {**base, "ci95": ci, "cluster_ci95": cluster_ci}


def cohens_kappa(a: list[str], b: list[str], categories: tuple[str, ...] = TAXONOMY) -> dict[str, Any]:
    n = len(a)
    if n == 0 or len(b) != n:
        return {"n": 0, "agree_rate": None, "kappa": None}
    agree = sum(x == y for x, y in zip(a, b))
    p_o = agree / n
    ca, cb = Counter(a), Counter(b)
    p_e = sum((ca[c] / n) * (cb[c] / n) for c in categories)
    kappa = 1.0 if abs(1.0 - p_e) < 1e-12 and abs(1.0 - p_o) < 1e-12 else (
        0.0 if abs(1.0 - p_e) < 1e-12 else (p_o - p_e) / (1.0 - p_e)
    )
    lo, hi = wilson_ci(agree, n)
    return {"n": n, "agree": agree, "agree_rate": round(p_o, 4), "agree_ci95": [lo, hi], "kappa": round(kappa, 4)}


def is_correct_tagged(label: str, code_tags: list[str]) -> bool:
    """Strict match on code-tagged steps (where tags.py assigned >=1 failure tag)."""
    return label in code_tags


def is_code_consistent(label: str, code_tags: list[str]) -> bool:
    """Match across ALL high-regret steps: exact tag match when tags.py assigned a tag; {'other','not_a_mistake'}
    when tags.py evaluated all 7 predicates and assigned none."""
    if code_tags:
        return label in code_tags
    return label in ("other", "not_a_mistake")


def majority_vote(verdicts: list[dict]) -> dict[str, Any]:
    """Deterministic 3-judge aggregation: >=2 votes wins; 1-1-1 tie breaks by highest stated confidence."""
    counts = Counter(v["label"] for v in verdicts)
    conf_sum: dict[str, float] = defaultdict(float)
    for v in verdicts:
        conf_sum[v["label"]] += float(v["confidence"])
    top_count = max(counts.values())
    if top_count >= 2:
        winner = next(lab for lab, c in counts.most_common() if c == top_count)
        agreement_type = "unanimous" if top_count == len(verdicts) else "majority"
        agree_confs = [float(v["confidence"]) for v in verdicts if v["label"] == winner]
        # Calibrated ensemble confidence: vote share blended with agreeing judges' stated confidence
        conf = (sum(agree_confs) / len(verdicts))
    else:
        agreement_type = "split"
        best_v = max(verdicts, key=lambda v: (float(v["confidence"]), v.get("rank_tiebreak", 0)))
        winner = best_v["label"]
        conf = float(best_v["confidence"]) / len(verdicts)

    # Also compute pure confidence-weighted label
    cw_winner = max(conf_sum.items(), key=lambda kv: (kv[1], counts[kv[0]]))[0]
    total_conf = sum(conf_sum.values()) or 1.0
    return {
        "label": winner,
        "confidence": round(min(1.0, max(0.0, conf)), 4),
        "mean_voter_confidence": round(
            sum(float(v["confidence"]) for v in verdicts if v["label"] == winner)
            / max(1, sum(1 for v in verdicts if v["label"] == winner)),
            4,
        ),
        "agreement_type": agreement_type,
        "vote_count": top_count,
        "mistake_votes": sum(1 for v in verdicts if v["label"] != "not_a_mistake"),
        "conf_weighted_label": cw_winner,
        "conf_weighted_share": round(conf_sum[cw_winner] / total_conf, 4),
    }


def calibration_curve(pairs: list[tuple[float, bool]], n_bins: int = 5) -> dict[str, Any]:
    """Reliability curve, ECE and Brier score from [(confidence, correct_bool)]."""
    if not pairs:
        return {"n": 0, "ece": None, "brier": None, "mean_confidence": None, "accuracy": None, "bins": []}
    n = len(pairs)
    brier = sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in pairs) / n
    mean_c = sum(c for c, _ in pairs) / n
    acc = sum(1 for _, ok in pairs if ok) / n
    edges = [i / n_bins for i in range(n_bins + 1)]
    bins = []
    ece = 0.0
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        items = [(c, ok) for c, ok in pairs if (lo <= c < hi if b < n_bins - 1 else lo <= c <= hi)]
        bn = len(items)
        if bn == 0:
            bins.append({"bin": f"[{lo:.1f}, {hi:.1f}{']' if b == n_bins - 1 else ')'}", "lo": round(lo, 2),
                         "hi": round(hi, 2), "n": 0, "mean_conf": None, "accuracy": None, "ci95": [None, None]})
            continue
        bc = sum(c for c, _ in items) / bn
        bk = sum(1 for _, ok in items if ok)
        ba = bk / bn
        ece += (bn / n) * abs(ba - bc)
        wlo, whi = wilson_ci(bk, bn)
        bins.append({
            "bin": f"[{lo:.1f}, {hi:.1f}{']' if b == n_bins - 1 else ')'}",
            "lo": round(lo, 2),
            "hi": round(hi, 2),
            "n": bn,
            "correct": bk,
            "mean_conf": round(bc, 4),
            "accuracy": round(ba, 4),
            "ci95": [wlo, whi],
        })
    return {
        "n": n,
        "ece": round(ece, 4),
        "brier": round(brier, 4),
        "mean_confidence": round(mean_c, 4),
        "accuracy": round(acc, 4),
        "bins": bins,
    }


def score_predictions(step_items: list[tuple[JuryEpisode, JuryStep]], preds: list[dict]) -> dict[str, Any]:
    """Compute tagged accuracy, all-step code-consistency accuracy, per-tag recall/precision/F1, calibration, and
    false-positive tag rate on untagged steps."""
    n_all = len(step_items)
    tagged_idx = [i for i, (_, s) in enumerate(step_items) if s.tags]
    untagged_idx = [i for i, (_, s) in enumerate(step_items) if not s.tags]

    k_tag = sum(1 for i in tagged_idx if is_correct_tagged(preds[i]["label"], step_items[i][1].tags))
    k_all = sum(1 for i in range(n_all) if is_code_consistent(preds[i]["label"], step_items[i][1].tags))
    k_fp = sum(1 for i in untagged_idx if preds[i]["label"] in CODE_TAGS)
    k_mistake = sum(1 for p in preds if p["label"] != "not_a_mistake")

    per_tag: dict[str, Any] = {}
    for tg in ("premature_accusation", "uninformative_canary", "over_restriction", "ignored_delay", "decoy_chase", "budget_waste"):
        pos = [i for i, (_, s) in enumerate(step_items) if tg in s.tags]
        pred_pos = [i for i, p in enumerate(preds) if p["label"] == tg]
        tp = sum(1 for i in pos if preds[i]["label"] == tg)
        if not pos and not pred_pos:
            continue
        rec = tp / len(pos) if pos else None
        prec = tp / len(pred_pos) if pred_pos else None
        f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else 0.0
        per_tag[tg] = {
            "support": len(pos),
            "predicted": len(pred_pos),
            "tp": tp,
            "recall": round(rec, 4) if rec is not None else None,
            "recall_ci95": list(wilson_ci(tp, len(pos))) if pos else [None, None],
            "precision": round(prec, 4) if prec is not None else None,
            "precision_ci95": list(wilson_ci(tp, len(pred_pos))) if pred_pos else [None, None],
            "f1": round(f1, 4) if pos else None,
        }

    cal_tagged = calibration_curve(
        [(float(preds[i]["confidence"]), is_correct_tagged(preds[i]["label"], step_items[i][1].tags)) for i in tagged_idx]
    )
    cal_all = calibration_curve(
        [(float(preds[i]["confidence"]), is_code_consistent(preds[i]["label"], step_items[i][1].tags)) for i in range(n_all)]
    )

    total_hr_regret = sum(s.regret for _, s in step_items) or 1e-9
    flagged_regret = sum(s.regret for (_, s), p in zip(step_items, preds) if p["label"] != "not_a_mistake")

    return {
        "n_all": n_all,
        "n_tagged": len(tagged_idx),
        "n_untagged": len(untagged_idx),
        "tagged_correct": k_tag,
        "tagged_accuracy": round(k_tag / len(tagged_idx), 4) if tagged_idx else None,
        "tagged_accuracy_ci95": list(wilson_ci(k_tag, len(tagged_idx))),
        "all_consistent": k_all,
        "all_accuracy": round(k_all / n_all, 4) if n_all else None,
        "all_accuracy_ci95": list(wilson_ci(k_all, n_all)),
        "untagged_false_positive_tag": k_fp,
        "untagged_fp_rate": round(k_fp / len(untagged_idx), 4) if untagged_idx else None,
        "untagged_fp_ci95": list(wilson_ci(k_fp, len(untagged_idx))),
        "mistake_rate": round(k_mistake / n_all, 4) if n_all else None,
        "regret_share_flagged": round(flagged_regret / total_hr_regret, 4),
        "label_counts": dict(Counter(p["label"] for p in preds).most_common()),
        "per_tag": per_tag,
        "calibration_tagged": cal_tagged,
        "calibration_all": cal_all,
    }


# --------------------------------------------------------------------------- Parallel Execution & Aggregation

def select_thinking_subset(
    step_items: list[tuple[JuryEpisode, JuryStep]], max_steps: int, seed: int = 0
) -> list[tuple[JuryEpisode, JuryStep]]:
    """Deterministic subset for extra thinking levels if `max_steps < len(step_items)`: keeps ALL code-tagged steps
    first, then adds a stratified sample of untagged steps by tool."""
    if max_steps <= 0 or max_steps >= len(step_items):
        return list(step_items)
    tagged = [it for it in step_items if it[1].tags]
    untagged = [it for it in step_items if not it[1].tags]
    if len(tagged) >= max_steps:
        return tagged[:max_steps]
    need = max_steps - len(tagged)
    rng = random.Random(seed)
    by_tool: dict[str, list[tuple[JuryEpisode, JuryStep]]] = defaultdict(list)
    for it in untagged:
        by_tool[it[1].tool].append(it)
    for lst in by_tool.values():
        rng.shuffle(lst)
    picked: list[tuple[JuryEpisode, JuryStep]] = []
    tools = sorted(by_tool)
    idx = 0
    while len(picked) < need and any(by_tool.values()):
        tl = tools[idx % len(tools)]
        if by_tool[tl]:
            picked.append(by_tool[tl].pop())
        idx += 1
    chosen_keys = {(ep.id, s.t) for ep, s in (tagged + picked)}
    return [it for it in step_items if (it[0].id, it[1].t) in chosen_keys]


def execute_cell(
    ops: JuryOps,
    model: str,
    level: str,
    step_items: list[tuple[JuryEpisode, JuryStep]],
    concurrency: int = 24,
    log=print,
) -> dict[tuple[str, int], dict]:
    """Judge every `(ep, step)` in `step_items` with `(model, level)`, using explicit episode prefix caching where
    useful (>= 3 steps in episode and prefix >= 16.8k chars on cache-capable models)."""
    schema = inline_schema(JuryVerdict)
    schema_sha = hashlib.sha256(_canon(schema).encode()).hexdigest()

    by_ep: dict[str, list[tuple[JuryEpisode, JuryStep]]] = defaultdict(list)
    for ep, s in step_items:
        by_ep[ep.id].append((ep, s))
    for lst in by_ep.values():
        lst.sort(key=lambda es: es[1].t)

    out: dict[tuple[str, int], dict] = {}
    out_lock = threading.Lock()
    total = len(step_items)
    t_start = time.time()

    # Fast-path: resolve all cached responses immediately before spawning worker threads
    misses: list[tuple[JuryEpisode, JuryStep]] = []
    for ep, st in step_items:
        fv = build_blind_view(ep, st.t)
        vsha = hashlib.sha256((SYSTEM_PROMPT + "\n" + fv).encode()).hexdigest()
        k = ops.request_key(model, level, ep.id, st.t, vsha, schema_sha)
        with ops._store_lock:
            hit = ops.store.get(k)
            if hit is not None:
                ops.stats["replayed"] += 1
                out[(ep.id, st.t)] = hit
                continue
        misses.append((ep, st))

    done = [len(out)]
    if not misses:
        log(f"  [{model}@{level}] {done[0]}/{total} (100% cached)", flush=True)
        return out
    log(f"  [{model}@{level}] {done[0]}/{total} cached, judging {len(misses)} remaining steps...", flush=True)

    def judge_single(it: tuple[JuryEpisode, JuryStep]) -> None:
        ep, st = it
        r = ops.judge_step(model, level, ep, st.t, schema, schema_sha)
        with out_lock:
            out[(ep.id, st.t)] = r
            done[0] += 1
            if done[0] % 50 == 0 or done[0] == total:
                el = max(0.1, time.time() - t_start)
                log(f"  [{model}@{level}] {done[0]}/{total} ({(done[0] - (total - len(misses)))/el:.1f} live/s)", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futs = [pool.submit(judge_single, it) for it in misses]
        for f in as_completed(futs):
            f.result()
    return out


def evaluate_three_model_jury(
    judges: tuple[str, ...],
    level: str,
    step_items: list[tuple[JuryEpisode, JuryStep]],
    cell_results: dict[tuple[str, str], dict[tuple[str, int], dict]],
) -> dict[str, Any]:
    """Compute Fleiss' kappa, pairwise Cohen's kappa, per-judge metrics, majority-vote metrics, agreement-stratified
    accuracy, and solver-regret alignment for a 3-model jury at `level`."""
    ep_ids = [ep.id for ep, _ in step_items]
    tagged_mask = [bool(s.tags) for _, s in step_items]

    # Per-judge metrics
    per_judge: dict[str, Any] = {}
    for m in judges:
        res_map = cell_results[(m, level)]
        preds = [res_map[(ep.id, s.t)] for ep, s in step_items]
        m_versions = sorted({p.get("model_version") or m for p in preds})
        tok_think = [p["usage"]["thoughts_token_count"] for p in preds if "usage" in p]
        lats = [p.get("latency_s", 0.0) for p in preds]
        costs = [p.get("cost_usd", 0.0) for p in preds]
        per_judge[m] = {
            "model": m,
            "thinking_level": level,
            "model_versions": m_versions,
            "mean_thinking_tokens": round(sum(tok_think) / max(1, len(tok_think)), 1),
            "mean_latency_s": round(sum(lats) / max(1, len(lats)), 2),
            "cost_usd": round(sum(costs), 4),
            **score_predictions(step_items, preds),
        }

    # Ratings matrix [N x 3]
    ratings_all = [[cell_results[(m, level)][(ep.id, s.t)]["label"] for m in judges] for ep, s in step_items]
    ratings_tagged = [r for r, tg in zip(ratings_all, tagged_mask) if tg]
    ep_ids_tagged = [eid for eid, tg in zip(ep_ids, tagged_mask) if tg]
    ratings_binary = [["mistake" if x != "not_a_mistake" else "not_a_mistake" for x in r] for r in ratings_all]
    ratings_collapsed = [[x if x in CODE_TAGS else "untagged_bucket" for x in r] for r in ratings_all]

    fleiss = {
        "all_9class": fleiss_kappa_with_ci(ratings_all, ep_ids, TAXONOMY),
        "tagged_9class": fleiss_kappa_with_ci(ratings_tagged, ep_ids_tagged, TAXONOMY),
        "binary_mistake": fleiss_kappa_with_ci(ratings_binary, ep_ids, ("mistake", "not_a_mistake")),
        "code_bucket_8class": fleiss_kappa_with_ci(ratings_collapsed, ep_ids, CODE_TAGS + ("untagged_bucket",)),
    }

    pairwise = {}
    for i in range(len(judges)):
        for j in range(i + 1, len(judges)):
            m1, m2 = judges[i], judges[j]
            l1 = [cell_results[(m1, level)][(ep.id, s.t)]["label"] for ep, s in step_items]
            l2 = [cell_results[(m2, level)][(ep.id, s.t)]["label"] for ep, s in step_items]
            l1_t = [x for x, tg in zip(l1, tagged_mask) if tg]
            l2_t = [x for x, tg in zip(l2, tagged_mask) if tg]
            pairwise[f"{m1}__vs__{m2}"] = {
                "all": cohens_kappa(l1, l2, TAXONOMY),
                "tagged": cohens_kappa(l1_t, l2_t, TAXONOMY),
            }

    # Majority vote & confidence-weighted vote
    rank_Pref = {"gemini-4-argon": 3, "gemini-4-hydrogen": 2, "gemini-3.8-flash": 1}
    maj_preds: list[dict] = []
    cw_preds: list[dict] = []
    for ep, s in step_items:
        vs = [{**cell_results[(m, level)][(ep.id, s.t)], "rank_tiebreak": rank_Pref.get(m, 0)} for m in judges]
        mv = majority_vote(vs)
        maj_preds.append(mv)
        cw_preds.append({"label": mv["conf_weighted_label"], "confidence": mv["conf_weighted_share"]})

    maj_metrics = score_predictions(step_items, maj_preds)
    cw_metrics = score_predictions(step_items, cw_preds)

    # Agreement-stratified accuracy (unanimous 3/3 vs majority 2/3 vs split 1-1-1)
    by_agree: dict[str, Any] = {}
    for kind in ("unanimous", "majority", "split"):
        idxs = [i for i, mv in enumerate(maj_preds) if mv["agreement_type"] == kind]
        t_idxs = [i for i in idxs if step_items[i][1].tags]
        k_all = sum(1 for i in idxs if is_code_consistent(maj_preds[i]["label"], step_items[i][1].tags))
        k_tag = sum(1 for i in t_idxs if is_correct_tagged(maj_preds[i]["label"], step_items[i][1].tags))
        by_agree[kind] = {
            "n_all": len(idxs),
            "share_all": round(len(idxs) / max(1, len(step_items)), 4),
            "all_accuracy": round(k_all / len(idxs), 4) if idxs else None,
            "all_ci95": list(wilson_ci(k_all, len(idxs))) if idxs else [None, None],
            "n_tagged": len(t_idxs),
            "tagged_accuracy": round(k_tag / len(t_idxs), 4) if t_idxs else None,
            "tagged_ci95": list(wilson_ci(k_tag, len(t_idxs))) if t_idxs else [None, None],
        }

    # Solver regret alignment by number of judges voting "mistake" (0/3, 1/3, 2/3, 3/3)
    by_mistake_votes: dict[str, Any] = {}
    for mv_cnt in range(len(judges) + 1):
        regs = [step_items[i][1].regret for i, mv in enumerate(maj_preds) if mv["mistake_votes"] == mv_cnt]
        tag_share = (
            sum(1 for i, mv in enumerate(maj_preds) if mv["mistake_votes"] == mv_cnt and step_items[i][1].tags)
            / max(1, len(regs))
        ) if regs else None
        rmean, rlo, rhi = bootstrap_mean_ci(regs)
        by_mistake_votes[f"{mv_cnt}_of_{len(judges)}"] = {
            "n": len(regs),
            "mean_regret": rmean if regs else None,
            "mean_regret_ci95": [rlo, rhi] if regs else [None, None],
            "regret_sum": round(sum(regs), 4),
            "code_tagged_rate": round(tag_share, 4) if tag_share is not None else None,
        }

    return {
        "thinking_level": level,
        "judges": list(judges),
        "n_steps": len(step_items),
        "n_tagged_steps": sum(tagged_mask),
        "fleiss_kappa": fleiss,
        "pairwise": pairwise,
        "per_judge": per_judge,
        "majority_vote": maj_metrics,
        "confidence_weighted_vote": {
            k: cw_metrics[k] for k in ("tagged_accuracy", "tagged_accuracy_ci95", "all_accuracy", "all_accuracy_ci95")
        },
        "by_agreement_tier": by_agree,
        "regret_by_mistake_votes": by_mistake_votes,
        "maj_preds": maj_preds,
    }


# --------------------------------------------------------------------------- Plot & Markdown Report

def render_calibration_plot(report: dict[str, Any], out_png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    primary = report["primary_jury"]
    judges = primary["judges"]
    colors = {
        "gemini-4-argon": "#2563eb",
        "gemini-4-hydrogen": "#059669",
        "gemini-3.8-flash": "#d97706",
        "majority_vote": "#dc2626",
    }
    labels_pretty = {
        "gemini-4-argon": "gemini-4-argon",
        "gemini-4-hydrogen": "gemini-4-hydrogen",
        "gemini-3.8-flash": "gemini-3.8-flash",
        "majority_vote": "3-model Jury (majority)",
    }

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.2), dpi=160)
    fig.patch.set_facecolor("white")

    # Panel 1: Calibration on Code-Tagged Steps
    ax = axes[0]
    ax.plot([0, 1], [0, 1], "--", color="#94a3b8", lw=1.3, label="Perfect calibration")
    series_tagged = [(m, primary["per_judge"][m]["calibration_tagged"]) for m in judges] + [
        ("majority_vote", primary["majority_vote"]["calibration_tagged"])
    ]
    for key, cal in series_tagged:
        pts = [b for b in cal.get("bins", []) if b["n"] >= 3 and b["mean_conf"] is not None]
        if not pts:
            continue
        xs = [b["mean_conf"] for b in pts]
        ys = [b["accuracy"] for b in pts]
        lw = 2.6 if key == "majority_vote" else 1.7
        mk = "s" if key == "majority_vote" else "o"
        ece = cal.get("ece")
        lbl = f"{labels_pretty.get(key, key)} (ECE={ece:.3f})" if ece is not None else labels_pretty.get(key, key)
        ax.plot(xs, ys, marker=mk, lw=lw, ms=5.5, color=colors.get(key, "#334155"), label=lbl)
        if key == "majority_vote":
            yerr_lo = [max(0.0, b["accuracy"] - b["ci95"][0]) for b in pts]
            yerr_hi = [max(0.0, b["ci95"][1] - b["accuracy"]) for b in pts]
            ax.errorbar(xs, ys, yerr=[yerr_lo, yerr_hi], fmt="none", ecolor=colors[key], alpha=0.45, capsize=3)
    ax.set_xlim(0.0, 1.02)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlabel("Stated confidence", fontsize=10)
    ax.set_ylabel("Empirical accuracy vs code tags", fontsize=10)
    ax.set_title(f"A. Calibration on code-tagged steps (n={primary['n_tagged_steps']})", fontsize=11, fontweight="bold")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right", fontsize=8, frameon=True)

    # Panel 2: Calibration on All High-Regret Steps
    ax = axes[1]
    ax.plot([0, 1], [0, 1], "--", color="#94a3b8", lw=1.3, label="Perfect calibration")
    series_all = [(m, primary["per_judge"][m]["calibration_all"]) for m in judges] + [
        ("majority_vote", primary["majority_vote"]["calibration_all"])
    ]
    for key, cal in series_all:
        pts = [b for b in cal.get("bins", []) if b["n"] >= 5 and b["mean_conf"] is not None]
        if not pts:
            continue
        xs = [b["mean_conf"] for b in pts]
        ys = [b["accuracy"] for b in pts]
        lw = 2.6 if key == "majority_vote" else 1.7
        mk = "s" if key == "majority_vote" else "o"
        ece = cal.get("ece")
        lbl = f"{labels_pretty.get(key, key)} (ECE={ece:.3f})" if ece is not None else labels_pretty.get(key, key)
        ax.plot(xs, ys, marker=mk, lw=lw, ms=5.5, color=colors.get(key, "#334155"), label=lbl)
        if key == "majority_vote":
            yerr_lo = [max(0.0, b["accuracy"] - b["ci95"][0]) for b in pts]
            yerr_hi = [max(0.0, b["ci95"][1] - b["accuracy"]) for b in pts]
            ax.errorbar(xs, ys, yerr=[yerr_lo, yerr_hi], fmt="none", ecolor=colors[key], alpha=0.45, capsize=3)
    ax.set_xlim(0.0, 1.02)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlabel("Stated confidence", fontsize=10)
    ax.set_ylabel("Code-consistent accuracy", fontsize=10)
    ax.set_title(f"B. Calibration on all HR steps (n={primary['n_steps']})", fontsize=11, fontweight="bold")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right", fontsize=8, frameon=True)

    # Panel 3: Accuracy as a function of judge model and thinking level
    ax = axes[2]
    grid = report.get("thinking_grid", [])
    levels_present = [lv for lv in THINKING_SWEEP if any(r["thinking_level"] == lv for r in grid)]
    if levels_present:
        x_pos = list(range(len(levels_present)))
        for m in judges:
            rows_m = {r["thinking_level"]: r for r in grid if r["model"] == m}
            xs, ys, lo_e, hi_e = [], [], [], []
            for idx, lv in enumerate(levels_present):
                if lv in rows_m and rows_m[lv]["tagged_accuracy"] is not None:
                    r = rows_m[lv]
                    xs.append(idx)
                    ys.append(r["tagged_accuracy"])
                    lo_e.append(max(0.0, r["tagged_accuracy"] - r["tagged_accuracy_ci95"][0]))
                    hi_e.append(max(0.0, r["tagged_accuracy_ci95"][1] - r["tagged_accuracy"]))
            if xs:
                ax.errorbar(xs, ys, yerr=[lo_e, hi_e], marker="o", lw=2.0, ms=6, capsize=3,
                            color=colors.get(m, "#334155"), label=labels_pretty.get(m, m))
        jury_by_lv = report.get("jury_by_thinking_level", {})
        jxs, jys, jlo, jhi = [], [], [], []
        for idx, lv in enumerate(levels_present):
            if lv in jury_by_lv and jury_by_lv[lv]["majority_tagged_accuracy"] is not None:
                jr = jury_by_lv[lv]
                jxs.append(idx)
                jys.append(jr["majority_tagged_accuracy"])
                jlo.append(max(0.0, jr["majority_tagged_accuracy"] - jr["majority_tagged_ci95"][0]))
                jhi.append(max(0.0, jr["majority_tagged_ci95"][1] - jr["majority_tagged_accuracy"]))
        if jxs:
            ax.errorbar(jxs, jys, yerr=[jlo, jhi], marker="s", lw=2.6, ms=6.5, capsize=3,
                        color=colors["majority_vote"], label="3-model Jury (majority)")
        ax.set_xticks(x_pos)
        ax.set_xticklabels(levels_present, fontsize=10)
    ax.set_ylim(0.0, 1.02)
    ax.set_xlabel("Judge thinking_level", fontsize=10)
    ax.set_ylabel("Accuracy vs code tags (95% Wilson CI)", fontsize=10)
    n_sub = report.get("thinking_sweep_n_tagged", primary["n_tagged_steps"])
    ax.set_title(f"C. Accuracy by model & thinking (n_tagged={n_sub})", fontsize=11, fontweight="bold")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="lower right", fontsize=8, frameon=True)

    fig.suptitle("Canary Calibrated 3-Model Gemini Jury (Blind Causal Trajectory Evaluation)", fontsize=13, fontweight="bold", y=1.01)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", dpi=160)
    plt.close(fig)


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{100.0 * x:.1f}%"


def _ci_pct(ci: list[float | None]) -> str:
    if not ci or ci[0] is None or ci[1] is None:
        return "[-, -]"
    return f"[{100.0 * ci[0]:.1f}%, {100.0 * ci[1]:.1f}%]"


def render_markdown(r: dict[str, Any]) -> str:
    p = r["primary_jury"]
    fl_all = p["fleiss_kappa"]["all_9class"]
    fl_tag = p["fleiss_kappa"]["tagged_9class"]
    fl_bin = p["fleiss_kappa"]["binary_mistake"]
    maj = p["majority_vote"]

    lines = [
        "# Canary Calibrated 3-Model Jury (`scale/jury`)",
        "",
        f"*Generated {r['generated_at']} at `{r['git_sha']}`; judges `{', '.join(p['judges'])}` "
        f"(served `{', '.join(r['served_model_versions'])}`, NO carbon); ledger run ids: "
        f"{', '.join(r['ledger_run_ids']) or 'replay'}.*",
        "",
        "## Headline Summary",
        "",
        f"- **Scale & provenance:** **{r['total_judgments']:,} independent blind structured judgments** across "
        f"**{r['corpus']['episodes']} valid committed episodes** ({r['corpus']['excluded_infra_episodes']} infra-error "
        f"episodes excluded) and **{p['n_steps']:,} high-regret decision steps** (`regret >= {HIGH_REGRET}`), "
        f"of which **{p['n_tagged_steps']}** carry an explicit `canary/analysis/tags.py` failure tag and "
        f"**{p['n_steps'] - p['n_tagged_steps']:,}** are untagged heuristic-regret steps (`s.tags == []`).",
        f"- **Inter-judge agreement (primary `{p['thinking_level']}` jury, n={p['n_steps']:,}):** "
        f"9-class Fleiss' $\\kappa = {fl_all['kappa']:.3f}$ (95% bootstrap CI `[{fl_all['ci95'][0]:.3f}, {fl_all['ci95'][1]:.3f}]`, "
        f"episode-cluster CI `[{fl_all['cluster_ci95'][0]:.3f}, {fl_all['cluster_ci95'][1]:.3f}]`, observed agreement {_pct(fl_all['p_observed'])}); "
        f"on code-tagged steps (n={p['n_tagged_steps']}) Fleiss' $\\kappa = {fl_tag['kappa']:.3f}$ "
        f"(`[{fl_tag['ci95'][0]:.3f}, {fl_tag['ci95'][1]:.3f}]`); binary mistake vs `not_a_mistake` "
        f"Fleiss' $\\kappa = {fl_bin['kappa']:.3f}$.",
        f"- **Accuracy vs `tags.py` & ensemble gain:** On code-tagged steps (n={p['n_tagged_steps']}), majority vote "
        f"achieves **{_pct(maj['tagged_accuracy'])} {_ci_pct(maj['tagged_accuracy_ci95'])}** (ECE `{maj['calibration_tagged']['ece']:.3f}`), "
        f"and across all {p['n_steps']:,} high-regret steps code-consistent accuracy is "
        f"**{_pct(maj['all_accuracy'])} {_ci_pct(maj['all_accuracy_ci95'])}** (ECE `{maj['calibration_all']['ece']:.3f}`).",
        f"- **Solver regret recovery:** Whereas one-pass `atlas_blind` cited 4% of high-regret steps covering 21% of regret, "
        f"per-decision Jury evaluation flags **{_pct(maj['mistake_rate'])}** of high-regret steps as mistakes, capturing "
        f"**{_pct(maj['regret_share_flagged'])}** of total high-regret solver loss.",
        "",
        "## 1. Per-Judge & Majority-Vote Accuracy (`thinking_level=" + p["thinking_level"] + "`)",
        "",
        "| Judge | Served `model_version` | Tagged acc (n=" + str(p["n_tagged_steps"]) + ") | 95% Wilson CI | All-step acc (n=" + str(p["n_steps"]) + ") | 95% Wilson CI | ECE (tagged) | ECE (all) | Regret flagged |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in p["judges"]:
        jm = p["per_judge"][m]
        lines.append(
            f"| `{m}` | `{','.join(jm['model_versions'])}` | {_pct(jm['tagged_accuracy'])} | "
            f"{_ci_pct(jm['tagged_accuracy_ci95'])} | {_pct(jm['all_accuracy'])} | {_ci_pct(jm['all_accuracy_ci95'])} | "
            f"{jm['calibration_tagged']['ece']:.3f} | {jm['calibration_all']['ece']:.3f} | {_pct(jm['regret_share_flagged'])} |"
        )
    lines.append(
        f"| **3-Model Jury (majority)** | ensemble (n=3) | **{_pct(maj['tagged_accuracy'])}** | "
        f"**{_ci_pct(maj['tagged_accuracy_ci95'])}** | **{_pct(maj['all_accuracy'])}** | "
        f"**{_ci_pct(maj['all_accuracy_ci95'])}** | **{maj['calibration_tagged']['ece']:.3f}** | "
        f"**{maj['calibration_all']['ece']:.3f}** | **{_pct(maj['regret_share_flagged'])}** |"
    )

    lines += [
        "",
        "### Per-Tag Recall & Precision (3-Model Majority Vote)",
        "",
        "| `tags.py` tag | Support (HR steps) | Predicted | Recall (95% CI) | Precision (95% CI) | F1 |",
        "|---|---|---|---|---|---|",
    ]
    for tg, tm in maj["per_tag"].items():
        lines.append(
            f"| `{tg}` | {tm['support']} | {tm['predicted']} | {_pct(tm['recall'])} {_ci_pct(tm['recall_ci95'])} | "
            f"{_pct(tm['precision'])} {_ci_pct(tm['precision_ci95'])} | {tm['f1'] if tm['f1'] is not None else '-'} |"
        )

    lines += [
        "",
        "## 2. Inter-Judge Agreement (Fleiss' $\\kappa$, Pairwise Cohen's $\\kappa$, & Agreement Tiers)",
        "",
        "| Pair | All HR steps (n=" + str(p["n_steps"]) + ") agree (95% CI) | Cohen's $\\kappa$ (all) | Tagged steps (n=" + str(p["n_tagged_steps"]) + ") agree (95% CI) | Cohen's $\\kappa$ (tagged) |",
        "|---|---|---|---|---|",
    ]
    for pair_k, pm in p["pairwise"].items():
        a, b = pair_k.split("__vs__")
        lines.append(
            f"| `{a}` vs `{b}` | {_pct(pm['all']['agree_rate'])} {_ci_pct(pm['all']['agree_ci95'])} | "
            f"{pm['all']['kappa']:.3f} | {_pct(pm['tagged']['agree_rate'])} {_ci_pct(pm['tagged']['agree_ci95'])} | "
            f"{pm['tagged']['kappa']:.3f} |"
        )

    lines += [
        "",
        "### Accuracy Stratified by Jury Consensus Tier",
        "",
        "| Consensus tier | Steps (share) | All-step acc (95% CI) | Tagged steps | Tagged acc (95% CI) |",
        "|---|---|---|---|---|",
    ]
    for tier_k, label_s in (("unanimous", "3/3 unanimous"), ("majority", "2/3 majority"), ("split", "1-1-1 split")):
        bt = p["by_agreement_tier"][tier_k]
        lines.append(
            f"| {label_s} | {bt['n_all']} ({_pct(bt['share_all'])}) | {_pct(bt['all_accuracy'])} {_ci_pct(bt['all_ci95'])} | "
            f"{bt['n_tagged']} | {_pct(bt['tagged_accuracy'])} {_ci_pct(bt['tagged_ci95'])} |"
        )

    lines += [
        "",
        "## 3. Agreement with Solver Regret",
        "",
        "| Judges voting mistake (`!= not_a_mistake`) | Steps (n) | Mean solver regret (95% bootstrap CI) | Total solver regret | Share carrying `tags.py` tag |",
        "|---|---|---|---|---|",
    ]
    for k_v in sorted(p["regret_by_mistake_votes"]):
        rv = p["regret_by_mistake_votes"][k_v]
        ci_s = f"[{rv['mean_regret_ci95'][0]:.3f}, {rv['mean_regret_ci95'][1]:.3f}]" if rv["mean_regret"] is not None else "[-, -]"
        lines.append(
            f"| `{k_v.replace('_of_', ' / ')}` | {rv['n']} | "
            f"{rv['mean_regret'] if rv['mean_regret'] is not None else '-'} {ci_s} | "
            f"{rv['regret_sum']:.2f} | {_pct(rv['code_tagged_rate'])} |"
        )

    if r.get("thinking_grid"):
        lines += [
            "",
            f"## 4. Accuracy as a Function of Judge Model & Thinking Level (paired n={r['thinking_sweep_n_steps']}, tagged={r['thinking_sweep_n_tagged']})",
            "",
            "| Judge model | `thinking_level` | Tagged acc (95% CI) | All-step acc (95% CI) | ECE (tagged) | Mean thinking tokens | Mean latency (s) | Cost ($ total) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for row in r["thinking_grid"]:
            lines.append(
                f"| `{row['model']}` | `{row['thinking_level']}` | "
                f"{_pct(row['tagged_accuracy'])} {_ci_pct(row['tagged_accuracy_ci95'])} | "
                f"{_pct(row['all_accuracy'])} {_ci_pct(row['all_accuracy_ci95'])} | "
                f"{row['ece_tagged']:.3f} | {row['mean_thinking_tokens']:.0f} | "
                f"{row['mean_latency_s']:.2f} | ${row['cost_usd']:.2f} |"
            )
        lines += [
            "",
            "| Thinking level | 3-Model Majority Tagged Acc (95% CI) | 3-Model Majority All-Step Acc (95% CI) | Fleiss' $\\kappa$ (all 9-class, 95% CI) | Fleiss' $\\kappa$ (tagged, 95% CI) |",
            "|---|---|---|---|---|",
        ]
        for lv, jl in r.get("jury_by_thinking_level", {}).items():
            lines.append(
                f"| `{lv}` | {_pct(jl['majority_tagged_accuracy'])} {_ci_pct(jl['majority_tagged_ci95'])} | "
                f"{_pct(jl['majority_all_accuracy'])} {_ci_pct(jl['majority_all_ci95'])} | "
                f"{jl['fleiss_all']['kappa']:.3f} [{jl['fleiss_all']['ci95'][0]:.3f}, {jl['fleiss_all']['ci95'][1]:.3f}] | "
                f"{jl['fleiss_tagged']['kappa']:.3f} [{jl['fleiss_tagged']['ci95'][0]:.3f}, {jl['fleiss_tagged']['ci95'][1]:.3f}] |"
            )

    lines += [
        "",
        "## 5. Blindness, Honesty & Keyless Reproduction",
        "",
        "- **Blind causal trajectory:** Every judge saw only public tier rules, agent tool calls/results up to `>>> t`, and "
        "sanitized agent `says:` text. No `REGRET`, `tags`, `top=`, `mole:`, `true_mole`, `solver`, or final `correct`/`score` "
        "outcome ever entered a prompt (`tests/test_gemini_lab_jury.py`).",
        "- **Model-model evaluation caveat:** All verdicts are model judgments evaluated against deterministic code tags "
        "(`canary/analysis/tags.py`) and Bayesian reference solver regret (`canary/solver/regret.py`); no human-agreement "
        "claim is made here.",
        "- **Keyless replay (0 API calls):**",
        "  ```bash",
        "  uv run --extra llm --extra dev --extra plot python -m canary.gemini.jury --replay",
        "  ```",
        "",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- Main Runner

def run(args: argparse.Namespace) -> dict[str, Any]:
    t0 = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_file = Path(args.cache_file) if args.cache_file else out_dir / "responses.jsonl.gz"

    judges = tuple(args.judges)
    for m in judges:
        if "carbon" in m.lower() and not args.allow_carbon:
            raise ValueError(f"gemini-4-carbon is forbidden by WS2 rules; got {m}")

    eps, ep_counts = load_all_episodes(
        committed_dir=Path(args.committed),
        ladder_gz=Path(args.ladder),
        ladder30_dir=Path(args.ladder30) if args.ladder30 else None,
    )
    if args.limit_episodes:
        eps = eps[: args.limit_episodes]

    all_hr: list[tuple[JuryEpisode, JuryStep]] = [
        (ep, s) for ep in eps for s in ep.steps if s.regret >= args.threshold
    ]
    if args.limit_steps:
        all_hr = all_hr[: args.limit_steps]

    # Verify blindness on every step before issuing a single API call
    for ep, s in all_hr:
        assert_blind_view_clean(build_blind_view(ep, s.t))

    print(
        f"jury corpus: {len(eps)} valid episodes ({ep_counts['committed_excluded_infra'] + ep_counts['ladder_excluded_infra']} "
        f"infra-invalid excluded), {len(all_hr)} high-regret steps (tagged={sum(1 for _, s in all_hr if s.tags)})",
        flush=True,
    )

    ops = JuryOps(cache_file=cache_file, replay=args.replay, allow_carbon=args.allow_carbon)
    primary_level = args.primary_level
    sweep_levels = tuple(args.thinking_levels)
    schema_sha = hashlib.sha256(_canon(inline_schema(JuryVerdict)).encode()).hexdigest()

    def _has_recorded(ep: JuryEpisode, s: JuryStep, levels: tuple[str, ...]) -> bool:
        vsha = hashlib.sha256((SYSTEM_PROMPT + "\n" + build_blind_view(ep, s.t)).encode()).hexdigest()
        return all(ops.request_key(m, lv, ep.id, s.t, vsha, schema_sha) in ops.store for m in judges for lv in levels)

    if args.replay and ops.store and not args.limit_steps:
        all_hr = [(ep, s) for ep, s in all_hr if _has_recorded(ep, s, (primary_level,))]
        sweep_items = [(ep, s) for ep, s in all_hr if _has_recorded(ep, s, sweep_levels)]
    else:
        sweep_items = select_thinking_subset(all_hr, args.sweep_max_steps, seed=0)

    cell_results: dict[tuple[str, str], dict[tuple[str, int], dict]] = {}

    # 1. Run primary level across ALL high-regret steps across all 3 models concurrently
    print(f"running primary jury ({primary_level}) across {len(judges)} models x {len(all_hr)} steps...", flush=True)
    with ThreadPoolExecutor(max_workers=len(judges)) as model_pool:
        futs = {
            model_pool.submit(execute_cell, ops, m, primary_level, all_hr, args.concurrency): (m, primary_level)
            for m in judges
        }
        for f in as_completed(futs):
            cell_results[futs[f]] = f.result()
    ops.save_compacted()

    # 2. Run additional thinking levels across all 3 models concurrently
    extra_levels = [lv for lv in sweep_levels if lv != primary_level]
    if extra_levels and sweep_items:
        print(
            f"running thinking sweep {extra_levels} across {len(judges)} models x {len(sweep_items)} steps "
            f"(tagged={sum(1 for _, s in sweep_items if s.tags)})...",
            flush=True,
        )
        tasks = [(m, lv) for lv in extra_levels for m in judges]
        # Run 1 level at a time across all 3 models so per-model concurrency never doubles
        for lv in extra_levels:
            with ThreadPoolExecutor(max_workers=len(judges)) as model_pool:
                futs = {
                    model_pool.submit(execute_cell, ops, m, lv, sweep_items, args.concurrency): (m, lv)
                    for m in judges
                }
                for f in as_completed(futs):
                    cell_results[futs[f]] = f.result()
            ops.save_compacted()

    # Ensure primary level has entries in cell_results for sweep_items too (it's a superset)
    primary_eval = evaluate_three_model_jury(judges, primary_level, all_hr, cell_results)
    maj_preds = primary_eval.pop("maj_preds")

    # Assemble thinking-level grid on identical paired `sweep_items`
    thinking_grid: list[dict[str, Any]] = []
    jury_by_level: dict[str, Any] = {}
    levels_done = [lv for lv in sweep_levels if all((m, lv) in cell_results for m in judges)]
    for lv in levels_done:
        lv_eval = evaluate_three_model_jury(judges, lv, sweep_items, cell_results)
        lv_eval.pop("maj_preds", None)
        jury_by_level[lv] = {
            "n_steps": len(sweep_items),
            "n_tagged": sum(1 for _, s in sweep_items if s.tags),
            "majority_tagged_accuracy": lv_eval["majority_vote"]["tagged_accuracy"],
            "majority_tagged_ci95": lv_eval["majority_vote"]["tagged_accuracy_ci95"],
            "majority_all_accuracy": lv_eval["majority_vote"]["all_accuracy"],
            "majority_all_ci95": lv_eval["majority_vote"]["all_accuracy_ci95"],
            "fleiss_all": lv_eval["fleiss_kappa"]["all_9class"],
            "fleiss_tagged": lv_eval["fleiss_kappa"]["tagged_9class"],
        }
        for m in judges:
            jm = lv_eval["per_judge"][m]
            thinking_grid.append({
                "model": m,
                "thinking_level": lv,
                "model_versions": jm["model_versions"],
                "n_all": jm["n_all"],
                "n_tagged": jm["n_tagged"],
                "tagged_accuracy": jm["tagged_accuracy"],
                "tagged_accuracy_ci95": jm["tagged_accuracy_ci95"],
                "all_accuracy": jm["all_accuracy"],
                "all_accuracy_ci95": jm["all_accuracy_ci95"],
                "ece_tagged": jm["calibration_tagged"]["ece"],
                "ece_all": jm["calibration_all"]["ece"],
                "mean_thinking_tokens": jm["mean_thinking_tokens"],
                "mean_latency_s": jm["mean_latency_s"],
                "cost_usd": jm["cost_usd"],
            })

    served_versions = sorted({
        v.get("model_version") or v.get("model", "")
        for cmap in cell_results.values()
        for v in cmap.values()
        if v.get("model_version") or v.get("model")
    })
    total_judgments = sum(len(cmap) for cmap in cell_results.values())

    # Compact per-step table for auditability
    step_records = []
    for (ep, s), mv in zip(all_hr, maj_preds):
        step_records.append({
            "episode": ep.id,
            "source": ep.source,
            "tier": ep.tier,
            "rules": ep.tiers_version,
            "t": s.t,
            "day": s.day,
            "tool": s.tool,
            "regret": round(s.regret, 4),
            "code_tags": s.tags,
            "majority_label": mv["label"],
            "majority_confidence": mv["confidence"],
            "agreement_type": mv["agreement_type"],
            "mistake_votes": mv["mistake_votes"],
            "judges": {
                m: {
                    "label": cell_results[(m, primary_level)][(ep.id, s.t)]["label"],
                    "confidence": cell_results[(m, primary_level)][(ep.id, s.t)]["confidence"],
                }
                for m in judges
            },
        })

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_sha": git_sha(),
        "ledger_run_ids": sorted(ops.source_run_ids),
        "served_model_versions": served_versions,
        "carbon_used": False,
        "blind": True,
        "taxonomy": list(TAXONOMY),
        "high_regret_threshold": args.threshold,
        "total_judgments": total_judgments,
        "cached_responses_in_store": len(ops.store),
        "corpus": {
            "episodes": len(eps),
            "excluded_infra_episodes": ep_counts["committed_excluded_infra"] + ep_counts["ladder_excluded_infra"],
            "breakdown": ep_counts,
            "high_regret_steps": len(all_hr),
            "tagged_high_regret_steps": sum(1 for _, s in all_hr if s.tags),
            "untagged_high_regret_steps": sum(1 for _, s in all_hr if not s.tags),
            "total_high_regret_value": round(sum(s.regret for _, s in all_hr), 4),
        },
        "primary_jury": primary_eval,
        "thinking_sweep_n_steps": len(sweep_items) if levels_done else 0,
        "thinking_sweep_n_tagged": sum(1 for _, s in sweep_items if s.tags) if levels_done else 0,
        "thinking_grid": thinking_grid,
        "jury_by_thinking_level": jury_by_level,
        "spend": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ops.stats.items()},
        "replay": bool(args.replay),
        "elapsed_s": round(time.time() - t0, 1),
        "steps": step_records,
    }

    render_calibration_plot(report, out_dir / "calibration.png")
    (out_dir / "jury.json").write_text(json.dumps(report, indent=1, sort_keys=False) + "\n")
    (out_dir / "jury.md").write_text(render_markdown(report))
    print(
        f"wrote {out_dir / 'jury.json'}, {out_dir / 'jury.md'}, {out_dir / 'calibration.png'} "
        f"(judgments={total_judgments}, calls={ops.stats['calls']}, replayed={ops.stats['replayed']}, "
        f"cost=${ops.stats['cost_usd']:.2f}, elapsed={report['elapsed_s']}s)",
        flush=True,
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.jury")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--cache-file", default=None)
    p.add_argument("--committed", default=str(DEFAULT_COMMITTED))
    p.add_argument("--ladder", default=str(DEFAULT_LADDER))
    p.add_argument("--ladder30", default="", help="Optional extra ladder dir if committed/finalized")
    p.add_argument("--judges", nargs="+", default=list(DEFAULT_JUDGES))
    p.add_argument("--primary-level", default=PRIMARY_LEVEL, choices=list(THINKING_SWEEP))
    p.add_argument("--thinking-levels", nargs="*", default=list(THINKING_SWEEP))
    p.add_argument("--sweep-max-steps", type=int, default=535,
                   help="Steps evaluated on non-primary thinking levels (0 = all steps; keeps 100%% of code-tagged steps)")
    p.add_argument("--threshold", type=float, default=HIGH_REGRET)
    p.add_argument("--concurrency", type=int, default=24, help="Per-model concurrent requests")
    p.add_argument("--limit-episodes", type=int, default=0)
    p.add_argument("--limit-steps", type=int, default=0)
    p.add_argument("--replay", action="store_true", help="Rebuild outputs offline from responses.jsonl.gz with 0 API calls")
    p.add_argument("--allow-carbon", action="store_true", help="Disabled by default per WS2 rules")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())



