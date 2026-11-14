"""Failure Atlas, data layer: load committed runs, align agent rationale to steps, compute per-step regret
(canary.solver.regret.attribute, ENV-owned) and the solver's belief trace, and pack everything into compact
per-episode text blocks for one long-context Gemini prompt.

Nothing here calls Gemini. Every number the atlas reports (regret, episode counts, shares) comes from here.

    eps = load_corpus(["data/runs/committed/v1.3", ...])
    text, blocks = pack_corpus(eps)
"""
from __future__ import annotations

import glob
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Rationale text budget (characters) per step in the pack. High-regret steps get the long budget.
RATIONALE_SHORT = 360
RATIONALE_LONG = 1400
HIGH_REGRET = 0.01  # a step is "high regret" at or above this (in units of V; wrong accusation ~ 1.5)


@dataclass
class StepRow:
    t: int
    day: int
    tool: str
    args: dict
    brief: str
    ok: bool = True
    regret: float = 0.0
    tags: list[str] = field(default_factory=list)
    p_top: float | None = None
    top: str | None = None
    p_mole: float | None = None
    p_accusee: float | None = None
    rationale: str = ""          # verbatim agent text/thought summary that preceded this call ("" if none)


@dataclass
class Episode:
    id: str
    run: str
    agent: str
    family: str          # gemini | gpt | grok | ...
    model: str           # gemini-4-carbon, gpt-5.5, ...
    harness: str         # inproc | opencode | codex | replayed
    tier: str
    tiers_version: str
    seed: int
    score: float
    correct: bool
    accused: str | None
    mole: str | None
    final_day: int
    end_reason: str
    steps: list[StepRow]
    thinking_level: str = "default"
    rationale_source: str = "none"   # thought_summaries | agent_messages | final_text | none
    solver_score: float | None = None
    terminal_regret: float = 0.0     # regret of ending without an accusation (attribute's last row)

    @property
    def total_regret(self) -> float:
        return round(sum(s.regret for s in self.steps) + self.terminal_regret, 6)

    @property
    def cohort(self) -> str:
        """Model[@thinking] x harness x tiers_version: the unit we compare (never pool versions or thinking levels)."""
        lv = "" if self.thinking_level == "default" else f"@{self.thinking_level}"
        return f"{self.model}{lv}/{self.harness}/{self.tiers_version}"

    def rationale_text(self) -> str:
        return "\n".join(s.rationale for s in self.steps if s.rationale)


# ----------------------------------------------------------------------------------------- identity

def agent_identity(agent: str, meta: dict) -> tuple[str, str, str]:
    """(family, model, harness) from an episodes.jsonl agent string + run meta."""
    a = agent or ""
    harness, model = "inproc", a
    if a.startswith("opencode:"):
        harness, model = "opencode", a.split(":", 1)[1].split("/")[-1]
    elif a.startswith("codex:"):
        harness, model = "codex", a.split(":", 1)[1]
    elif ":" in a:
        model = a.split(":", 1)[1]
    if meta.get("source", "").startswith("replayed"):
        harness = "replayed"
    model = meta.get("model") or model
    if "/" in model:
        model = model.split("/")[-1]
    m = model.lower()
    family = ("gemini" if "gemini" in m or "gemma" in m else "gpt" if m.startswith("gpt") or "openai" in m
              else "grok" if "grok" in m else m.split("-")[0] or "other")
    return family, model, harness


def infer_version(path: str, meta: dict) -> str:
    v = meta.get("tiers_version")
    if v:
        return str(v)
    for cand in ("v1.4", "v1.3", "v1.2"):
        if f"/{cand}/" in path or f"/{cand}-" in path:
            return cand
    m = re.search(r"(?:^|[/_-])v1\.?([234])(?:$|[/_.-])", f"{path}/{meta.get('ladder_run', '')}")
    if m:  # e.g. ~/agent-arena-data/gemini/ladder/ladder-v14/...
        return f"v1.{m.group(1)}"
    return "v1.2"  # pre-versioned committed runs (README: v1.2 history)


def thinking_of(meta: dict, ep_meta: dict) -> str:
    for src in (ep_meta, meta, meta.get("provider_settings") or {}, ep_meta.get("provider_settings") or {}):
        lv = src.get("thinking_level")
        if lv and "default" not in str(lv):
            return str(lv).lower()
    return "default"


# ----------------------------------------------------------------------------------------- briefs

def _short_ids(ids: list) -> str:
    return ",".join(str(i) for i in ids)


def compact_args(tool: str, args: dict) -> str:
    args = args or {}
    if tool == "plant_canary":
        groups: dict[str, list[str]] = {}
        for e, v in sorted((args.get("assignment") or {}).items()):
            groups.setdefault(str(v), []).append(e)
        return " | ".join(f"{v}:{_short_ids(es)}" for v, es in sorted(groups.items()))
    return ",".join(f"{k}={json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int, float)) else v}"
                    for k, v in sorted(args.items()))


def brief_result(tool: str, res: Any, max_len: int = 160) -> str:
    """One-line summary of a tool result (the facts an analyst needs, not the whole payload)."""
    if not isinstance(res, dict):
        return str(res)[:max_len]
    if not res.get("ok", True):
        return f"ERR {res.get('error')}"
    d = res.get("data") or {}
    try:
        if tool == "advance_day":
            nd = d.get("new_documents") or []
            return f"closed d{d.get('closed_day')} V={d.get('V')} new={_short_ids(nd)}"
        if tool == "status":
            return f"V={d.get('V')} left_today={d.get('actions_left_today')} calls_left={d.get('tool_calls_left')}"
        if tool == "check_leak_feed":
            items = d.get("items") or []
            return "feed: " + ("; ".join(
                f"{it.get('doc_id')}@d{it.get('surfaced_day')}" + (f" var={it['variant']}" if it.get("variant") else "")
                for it in items) or "empty")
        if tool == "list_documents":
            docs = d.get("documents") or []
            return f"{len(docs)} docs: " + "; ".join(
                f"{x.get('doc_id')}{'*' if x.get('is_canary') else ''}[{len(x.get('recipients') or [])}]" for x in docs)[:max_len]
        if tool == "list_employees":
            return f"{len(d.get('employees') or [])} employees"
        if tool == "read_access_logs":
            logs = d.get("logs") or []
            ah: dict[str, int] = {}
            for x in logs:
                if x.get("after_hours"):
                    ah[x.get("employee")] = ah.get(x.get("employee"), 0) + 1
            top = sorted(ah.items(), key=lambda kv: -kv[1])[:4]
            return f"{len(logs)} log rows; after-hours: " + (",".join(f"{e}x{n}" for e, n in top) or "none")
        if tool == "interview":
            return f"\"{str(d.get('answer', ''))[:max_len - 10]}\""
        if tool == "search_messages":
            ms = d.get("messages") or []
            first = json.dumps(ms[0], ensure_ascii=False)[:90] if ms else ""
            return f"{len(ms)} msgs {first}"
        if tool == "plant_canary":
            return f"canary {d.get('canary_id')}"
        if tool == "accuse":
            return f"accused {d.get('accused')} (episode over)"
    except Exception:  # noqa: BLE001
        pass
    return json.dumps(d, ensure_ascii=False)[:max_len]


# ----------------------------------------------------------------------------------------- transcripts

def _calls_from_json_transcript(msgs: list) -> tuple[list[tuple[str, str]], str]:
    """In-process transcript (canary.llm messages). Returns [(tool_name, rationale)], source."""
    calls, source = [], "none"
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        texts = []
        for it in m.get("provider_items") or []:
            if isinstance(it, dict):
                for p in it.get("parts") or []:  # Gemini Content: thought summaries are parts with thought=True
                    if isinstance(p, dict) and p.get("text"):
                        texts.append(p["text"].strip())
                        if p.get("thought"):
                            source = "thought_summaries"
                for s in it.get("summary") or []:  # OpenAI reasoning summaries (usually empty)
                    if isinstance(s, dict) and s.get("text"):
                        texts.append(s["text"].strip())
                        source = "thought_summaries"
        if m.get("content"):
            texts.append(str(m["content"]).strip())
            if source == "none":
                source = "agent_messages"
        rat = "\n".join(t for t in texts if t)
        for j, tc in enumerate(m.get("tool_calls") or []):
            calls.append((tc.get("name", ""), rat if j == 0 else ""))
    return calls, source


def _calls_from_jsonl_transcript(text: str) -> tuple[list[tuple[str, str]], str]:
    """Codex (`item.completed`) or OpenCode (`tool_use`/`text`) JSON event logs."""
    calls, pending, source = [], [], "none"
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ = d.get("type")
        if typ == "item.completed":
            it = d.get("item") or {}
            if it.get("type") in ("agent_message", "reasoning") and it.get("text"):
                pending.append(it["text"].strip())
                source = "agent_messages"
            elif it.get("type") == "mcp_tool_call":
                calls.append((str(it.get("tool", "")), "\n".join(pending)))
                pending = []
        elif typ in ("text", "reasoning"):
            t = (d.get("part") or {}).get("text")
            if t:
                pending.append(t.strip())
                source = "agent_messages"
        elif typ == "tool_use":
            tool = str((d.get("part") or {}).get("tool", ""))
            calls.append((re.sub(r"^canary[_.]", "", tool), "\n".join(pending)))
            pending = []
    if pending and calls:  # trailing final message: attach to the last call (usually the accusation)
        name, rat = calls[-1]
        calls[-1] = (name, (rat + "\n" + "\n".join(pending)).strip())
        if source == "none":
            source = "final_text"
    return calls, source


def load_transcript(path: Path) -> tuple[list[tuple[str, str]], str]:
    raw = path.read_text(errors="replace")
    if path.suffix == ".json":
        try:
            return _calls_from_json_transcript(json.loads(raw))
        except (json.JSONDecodeError, AttributeError, TypeError):
            return [], "none"
    return _calls_from_jsonl_transcript(raw)


def align_rationale(steps: list[dict], calls: list[tuple[str, str]], lookahead: int = 4) -> list[str]:
    """Attach each transcript call's rationale to the episode step with the same tool, walking in order."""
    out = [""] * len(steps)
    j = 0
    for i, st in enumerate(steps):
        for k in range(j, min(j + lookahead, len(calls))):
            if calls[k][0] == st.get("tool"):
                # rationale of skipped calls (e.g. rejected tool names) is kept with this step
                out[i] = "\n".join(c[1] for c in calls[j:k + 1] if c[1])
                j = k + 1
                break
    return out


# ----------------------------------------------------------------------------------------- solver replay

def belief_trace(ep_dict: dict) -> tuple[list[dict], list[dict]]:
    """(attribute rows from canary.solver.regret, belief rows [{t, post}] BEFORE each step)."""
    from canary.analysis.tags import to_result
    from canary.rules import tier_params_for_episode
    from canary.solver.policy import SolverPolicy
    from canary.solver.regret import attribute
    ep = to_result(ep_dict)
    rows = attribute(ep)
    sp = SolverPolicy(tier_params_for_episode(ep.tier, ep.steps))
    beliefs = []
    for i, st in enumerate(ep.steps):
        for prev in ep.steps[sp.seen:i]:
            sp._ingest(prev)
        sp.seen = i
        beliefs.append(sp.belief() if sp.obs.employees else {})
    return rows, beliefs


def true_mole(ep_dict: dict) -> str | None:
    """Regenerate the world (dev seeds use the public key) and return its mole; None if not reproducible."""
    try:
        from canary.analysis.tags import to_result
        from canary.rules import tier_params_for_episode
        from canary.world import JUDGE_SEEDS, HELDOUT_SEEDS, generate_world
        if ep_dict["seed"] in JUDGE_SEEDS or ep_dict["seed"] in HELDOUT_SEEDS:
            import os
            if not os.environ.get("CANARY_WORLD_SECRET") and not (ROOT / "data/worlds/judge/SALT").exists():
                return None
        ep = to_result(ep_dict)
        return generate_world(ep.tier, ep.seed, tier_params_for_episode(ep.tier, ep.steps)).mole
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------------------- loading

def find_run_dirs(paths: list[str | Path]) -> list[Path]:
    out = []
    for p in paths:
        for f in sorted(glob.glob(str(Path(p) / "**" / "episodes.jsonl"), recursive=True)):
            d = Path(f).parent
            if "superseded" in d.parts:
                continue
            out.append(d)
    return sorted(set(out))


def _model_short(model: str) -> str:
    m = model.lower().replace("gemini-", "g").replace("gpt-", "gpt")
    return re.sub(r"[^a-z0-9.]+", "", m)[:14]


def load_run(d: Path, attribute_steps: bool = True) -> list[Episode]:
    meta = {}
    if (d / "meta.json").exists():
        try:
            meta = json.loads((d / "meta.json").read_text())
        except json.JSONDecodeError:
            meta = {}
    version = infer_version(str(d), meta)
    raw = [json.loads(line) for line in (d / "episodes.jsonl").read_text().splitlines() if line.strip()]
    # transcripts are named <seed>.json|txt
    tr = {p.stem: p for p in (d / "transcripts").glob("*")} if (d / "transcripts").is_dir() else {}
    # mole reproducibility per run: every correct episode's accused must equal the regenerated mole
    moles = {i: true_mole(e) for i, e in enumerate(raw)}
    reproducible = all(moles[i] == e.get("accused") for i, e in enumerate(raw) if e.get("correct"))
    eps = []
    for i, e in enumerate(raw):
        family, model, harness = agent_identity(e.get("agent", ""), meta)
        mole = moles[i] if reproducible else (e.get("accused") if e.get("correct") else None)
        steps_raw = e.get("steps") or []
        calls, source = load_transcript(tr[str(e["seed"])]) if str(e["seed"]) in tr else ([], "none")
        rats = align_rationale(steps_raw, calls) if calls else [""] * len(steps_raw)
        rows, beliefs = belief_trace(e) if attribute_steps else ([], [{}] * len(steps_raw))
        by_t = {r["t"]: r for r in rows if isinstance(r.get("t"), int) and r.get("action") != "(no accusation)"}
        terminal = sum(r["regret"] for r in rows if r.get("action") == "(no accusation)")
        accusee = e.get("accused")
        steps = []
        for k, s in enumerate(steps_raw):
            r = by_t.get(s.get("t"), {})
            post = beliefs[k] if k < len(beliefs) else {}
            top = max(post, key=post.get) if post else None
            steps.append(StepRow(
                t=s.get("t", k), day=s.get("day", 0), tool=s.get("tool", ""), args=s.get("args") or {},
                brief=brief_result(s.get("tool", ""), s.get("result")), ok=(s.get("result") or {}).get("ok", True),
                regret=float(r.get("regret", 0.0)), tags=list(r.get("tags", [])),
                p_top=round(post[top], 4) if top else None, top=top,
                p_mole=round(post.get(mole, 0.0), 4) if (post and mole) else None,
                p_accusee=round(post.get(accusee, 0.0), 4) if (post and accusee) else None,
                rationale=rats[k] if k < len(rats) else ""))
        em = e.get("meta") or {}
        ep = Episode(id="", run=str(d), agent=e.get("agent", ""), family=family, model=model, harness=harness,
                     tier=e["tier"], tiers_version=version, seed=int(e["seed"]), score=float(e.get("score", 0.0)),
                     correct=bool(e.get("correct")), accused=accusee, mole=mole, final_day=int(e.get("final_day", 0)),
                     end_reason=e.get("end_reason", ""), steps=steps, thinking_level=thinking_of(meta, em),
                     rationale_source=source if any(rats) else "none", terminal_regret=round(terminal, 6))
        eps.append(ep)
    return eps


def _solver_scores(paths: list[str | Path]) -> dict[tuple[str, str, int], float]:
    """(tiers_version, tier, seed) -> reference solver score, from reference runs under the given roots."""
    out = {}
    for p in paths:
        for f in sorted(glob.glob(str(Path(p) / "**" / "solver-*" / "episodes.jsonl"), recursive=True)):
            if "superseded" in f:
                continue
            d = Path(f).parent
            meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
            v = infer_version(str(d), meta)
            for line in Path(f).read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    out[(v, e["tier"], int(e["seed"]))] = float(e.get("score", 0.0))
    return out


def load_corpus(paths: list[str | Path], solver_roots: list[str | Path] | None = None,
                skip_agents: tuple[str, ...] = ("solver", "random", "heuristic", "do_nothing", "stop_early",
                                                "restrict_all")) -> list[Episode]:
    eps: list[Episode] = []
    for d in find_run_dirs(paths):
        if "reference" in d.parts:
            continue
        for ep in load_run(d):
            if ep.agent in skip_agents:
                continue
            eps.append(ep)
    solver = _solver_scores(solver_roots if solver_roots is not None else paths)
    seen: dict[str, int] = {}
    for ep in eps:
        ver = ep.tiers_version.replace("v", "").replace(".", "")
        lv = "" if ep.thinking_level == "default" else f"-{ep.thinking_level}"
        base = f"{_model_short(ep.model)}{lv}.{ep.harness[:2]}.v{ver}.{ep.tier[0]}{ep.seed}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        ep.id = base if n == 0 else f"{base}#{n}"
        ep.solver_score = solver.get((ep.tiers_version, ep.tier, ep.seed))
    eps.sort(key=lambda e: e.id)  # path-independent order: the same episodes always pack to the same corpus
    return eps


def save_snapshot(eps: list[Episode], path: Path) -> None:
    """The loaded corpus (episodes + per-step regret/belief/words) as gzip JSON, so --replay needs no run dirs."""
    import gzip
    from dataclasses import asdict
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps([asdict(e) for e in eps], separators=(",", ":")).encode(), mtime=0))


def load_snapshot(path: Path) -> list[Episode]:
    import gzip
    out = []
    for d in json.loads(gzip.decompress(Path(path).read_bytes())):
        d["steps"] = [StepRow(**s) for s in d["steps"]]
        out.append(Episode(**d))
    return out


# ----------------------------------------------------------------------------------------- packing

def _f(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}".lstrip("0") if 0 <= x < 1 else f"{x:.2f}"


def belief_str(s: StepRow) -> str:
    belief = f"top={s.top}:{_f(s.p_top)}" if s.top else ""
    if s.p_mole is not None:
        belief += f" mole:{_f(s.p_mole)}"
    return belief


def step_line(s: StepRow, show_belief: bool = True) -> str:
    belief = belief_str(s) if show_belief else ""
    reg = f" | REGRET {s.regret:.3f}" + (f" [{','.join(s.tags)}]" if s.tags else "") if s.regret >= 0.001 or s.tags else ""
    return f"t{s.t} d{s.day} {s.tool}({compact_args(s.tool, s.args)}) -> {s.brief}{reg} | {belief}".rstrip(" |")


def episode_header(ep: Episode) -> str:
    sol = f" solver_same_seed={ep.solver_score:.3f}" if ep.solver_score is not None else ""
    return (f"=== EPISODE {ep.id} | agent={ep.agent} family={ep.family} harness={ep.harness} tiers={ep.tiers_version} "
            f"tier={ep.tier} seed={ep.seed} thinking={ep.thinking_level}\n"
            f"outcome: accused={ep.accused} correct={ep.correct} true_mole={ep.mole or 'unknown'} score={ep.score:.3f}"
            f"{sol} final_day={ep.final_day} end={ep.end_reason} total_regret={ep.total_regret:.3f} "
            f"rationale={ep.rationale_source}")


def pack_episode(ep: Episode, short: int = RATIONALE_SHORT, long: int = RATIONALE_LONG) -> str:
    lines = [episode_header(ep)]
    last = None
    for s in ep.steps:
        b = belief_str(s)  # the solver belief is printed only when it changes (saves ~25% tokens)
        lines.append(step_line(s, show_belief=(b != last)))
        last = b
        if s.rationale:
            budget = long if s.regret >= HIGH_REGRET or s.tool == "accuse" else short
            r = re.sub(r"\s+", " ", s.rationale).strip()
            lines.append(f"   says: {r[:budget]}{' [...]' if len(r) > budget else ''}")
    if ep.terminal_regret:
        lines.append(f"t{len(ep.steps)} (no accusation) | REGRET {ep.terminal_regret:.3f} [no_accusation]")
    return "\n".join(lines)


PACK_LEGEND = """FORMAT. One block per episode. Each step line:
  t<step> d<day> <tool>(<args>) -> <result summary> | REGRET <r> [<tags>] | top=<solver's top suspect>:<P> mole:<P(true mole)>
The solver belief (top=, mole:) is printed only when it changed since the previous line.
REGRET is computed in code by replaying the Bayesian reference solver's belief before that step: the value lost
versus the solver's choice (plant_canary: information lost vs the solver's partition; advance_day: value of
accusing now vs waiting; accuse: value vs the best accusation; restrict_access: cost x P(innocent)).
plant_canary args are written as variant groups, e.g. "A:e01,e05 | B:e07" (A went to e01 and e05).
`says:` lines are the agent's own words (thought summaries or messages) before that call, verbatim but truncated."""


def pack_corpus(eps: list[Episode], **kw) -> tuple[str, dict[str, str]]:
    blocks = {ep.id: pack_episode(ep, **kw) for ep in eps}
    return PACK_LEGEND + "\n\n" + "\n\n".join(blocks.values()), blocks


def high_regret_steps(eps: list[Episode], threshold: float = HIGH_REGRET, limit: int | None = None) -> list[tuple[Episode, StepRow]]:
    out = [(ep, s) for ep in eps for s in ep.steps if s.regret >= threshold]
    out.sort(key=lambda es: -es[1].regret)
    return out[:limit] if limit else out


def excerpt(ep: Episode, t: int, before: int = 8, after: int = 2, rationale_chars: int = 900) -> str:
    """Steps around t (for per-decision labelling and multimodal localisation)."""
    idx = next((i for i, s in enumerate(ep.steps) if s.t == t), None)
    lines = [episode_header(ep)]
    if idx is None:
        return "\n".join(lines)
    for s in ep.steps[max(0, idx - before): idx + after + 1]:
        mark = ">>> " if s.t == t else ""
        lines.append(mark + step_line(s))
        if s.rationale:
            r = re.sub(r"\s+", " ", s.rationale).strip()
            lines.append(f"   says: {r[:rationale_chars]}{' [...]' if len(r) > rationale_chars else ''}")
    return "\n".join(lines)


def behaviour_stats(eps: list[Episode]) -> dict[str, dict]:
    """Per cohort, code-computed decision statistics (to check Gemini's cross-family reading against)."""
    from collections import defaultdict
    by: dict[str, list[Episode]] = defaultdict(list)
    for e in eps:
        by[e.cohort].append(e)
    out = {}
    for c, es in sorted(by.items()):
        n = len(es)
        can = [s for e in es for s in e.steps if s.tool == "plant_canary" and s.ok]
        groups = [len(s.args.get("assignment") or {}) for s in can]
        variants = [len(set((s.args.get("assignment") or {}).values())) for s in can]
        acc = [s for e in es for s in e.steps if s.tool == "accuse"]
        p_acc = [s.p_accusee for s in acc if s.p_accusee is not None]
        out[c] = {
            "episodes": n,
            "steps_per_episode": round(sum(len(e.steps) for e in es) / n, 1),
            "canaries_per_episode": round(len(can) / n, 2),
            "canary_recipients_mean": round(sum(groups) / len(groups), 1) if groups else None,
            "canary_variants_mean": round(sum(variants) / len(variants), 2) if variants else None,
            "canary_regret_per_episode": round(sum(s.regret for s in can) / n, 4),
            "interviews_per_episode": round(sum(1 for e in es for s in e.steps if s.tool == "interview") / n, 1),
            "restrictions_per_episode": round(sum(1 for e in es for s in e.steps if s.tool == "restrict_access") / n, 2),
            "failed_calls_per_episode": round(sum(1 for e in es for s in e.steps if not s.ok) / n, 2),
            "accuse_day_mean": round(sum(s.day for s in acc) / len(acc), 1) if acc else None,
            "p_accused_mean": round(sum(p_acc) / len(p_acc), 3) if p_acc else None,
            "accused_below_0.6": sum(1 for p in p_acc if p < 0.6),
            "wrong_accusations": sum(1 for e in es if e.accused and not e.correct),
            # wrong accusations the solver's own posterior also backed (>= 0.5): bad luck, not an agent error
            "wrong_but_evidence_backed": sum(1 for e in es if e.accused and not e.correct and any(
                s.tool == "accuse" and (s.p_accusee or 0) >= 0.5 for s in e.steps)),
            "no_accusation": sum(1 for e in es if not e.accused),
        }
    return out
