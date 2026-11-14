"""Failure Atlas, BLIND: Gemini discovers failure modes from what the agents saw, did and said, without our labels.

    python -m canary.gemini.atlas --blind [--runs ...] [--cache-model gemini-3.8-flash] [--replay]
      -> results/gemini/atlas_blind.{json,md}

Why: atlas v1 showed Gemini the code's own per-step REGRET, tags (canary/analysis/tags.py), solver beliefs and the
true mole, so "Gemini named the failure modes" was partly circular. Here the packed corpus has only tool calls, tool
results as the agent saw them, the agent's own words, and the final outcome (test: no code labels in the pack).

Steps (one explicit context cache on --cache-model, every call streamed and ledgered):
 1. discovery: modes + cited (episode, step) examples + quotes of the agent's own words;
 2. mining: for each mode, Gemini lists every (episode, step) where it occurs;
 3. scoring in code against tags.py and the solver regret (never shown to Gemini):
    recall per code tag (share of its steps Gemini cited), precision (share of cited steps that are high-regret or
    tagged), regret share covered, tag -> mode overlap, and modes our tags do not have.
Quotes are verified against agent-authored text only (harness/code lines never count).
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from .atlas_data import HIGH_REGRET, ROOT, Episode, load_corpus, load_snapshot, pack_corpus_blind, save_snapshot
from .atlas_gemini import AtlasOps, ReplayMiss
from .atlas_schema import inline_schema, parse, quote_in

SYSTEM_BLIND = """You are a failure analyst for Canary, an environment where an LLM agent (head of security) must catch
one mole among the staff using canary traps (documents with per-recipient variants), access logs, interviews and the
leak feed, then make exactly one accusation. Score = remaining company value V on a correct accusation, -1 on a wrong
one, 0 for none. You see exactly what each agent saw, did and said. Answer only from the corpus. Quotes must be copied
character for character from the agent's own words (`says:` lines); a program checks them."""

CODE_TAGS = ("premature_accusation", "decoy_chase", "ignored_delay", "uninformative_canary", "over_restriction",
             "budget_waste", "no_accusation")


class Cite(BaseModel):
    episode: str
    t: int
    quote: str = Field(default="", description="5-30 words VERBATIM from the agent's own `says:` words at or just "
                                                "before step t; empty if the agent wrote nothing there")


class BlindMode(BaseModel):
    id: str = Field(description="snake_case")
    name: str
    description: str = Field(description="what goes wrong, in terms of the agent's decisions")
    why: str = Field(description="the reasoning error behind it, as visible in the agents' words")
    examples: list[Cite] = Field(description="5-10 specific steps from different episodes")


class BlindTaxonomy(BaseModel):
    summary: str
    modes: list[BlindMode] = Field(description="4-8 mutually exclusive failure modes")


class StepRef(BaseModel):
    episode: str
    t: int


class Mined(BaseModel):
    steps: list[StepRef]


DISCOVER = ("TASK. Read every episode above. Without any scoring hints, find the 4-8 most important FAILURE MODES: "
            "recurring decisions that cost the agents company value or got them a wrong accusation (or none). For "
            "each mode cite 5-10 specific steps (episode id exactly as in the header, step number t) from different "
            "episodes and agents, each with a verbatim quote of the agent's own words where it wrote any.")


def mine_q(mode: BlindMode) -> str:
    return (f"FAILURE MODE `{mode.id}`: {mode.name}. {mode.description}\n\nTASK. List EVERY step in the corpus "
            "where an agent makes this mistake (episode id exactly as in the header, step number t of the decision "
            "itself). Be exhaustive across all episodes; list at most 400 steps; do not list steps that are not this "
            "mistake.")


def code_truth(eps: list[Episode]) -> dict:
    """(episode, t) sets per code tag (all tagged steps and the high-regret subset), all high-regret steps, regret."""
    tag_steps: dict[str, set] = defaultdict(set)
    tag_hr: dict[str, set] = defaultdict(set)
    regret: dict[tuple[str, int], float] = {}
    for ep in eps:
        for s in ep.steps:
            regret[(ep.id, s.t)] = s.regret
            for tg in s.tags:
                tag_steps[tg].add((ep.id, s.t))
                if s.regret >= HIGH_REGRET:
                    tag_hr[tg].add((ep.id, s.t))
        if ep.terminal_regret:
            k = (ep.id, len(ep.steps))
            regret[k] = ep.terminal_regret
            tag_steps["no_accusation"].add(k)
            tag_hr["no_accusation"].add(k)
    hr = {k for k, v in regret.items() if v >= HIGH_REGRET}
    return {"tag_steps": tag_steps, "tag_hr": tag_hr, "hr": hr, "regret": regret,
            "total_regret": sum(e.total_regret for e in eps)}


def _near(k, pool: set, tol: int) -> bool:
    return any((k[0], k[1] + d) in pool for d in range(-tol, tol + 1))


def score_recovery(eps: list[Episode], cited: dict[str, set], tol: int = 1) -> dict:
    """All in code. cited: mode id -> {(episode, t)} (valid steps only). A cited step matches a code step if it is
    the same episode and within `tol` steps (the agent's decision vs the call Gemini pointed at)."""
    T = code_truth(eps)
    all_cited = set().union(*cited.values()) if cited else set()
    tags = {}
    for tg in CODE_TAGS:
        steps, hrs = T["tag_steps"].get(tg, set()), T["tag_hr"].get(tg, set())
        if not steps:
            continue
        rec = sum(_near(k, all_cited, tol) for k in steps) / len(steps)
        rec_hr = sum(_near(k, all_cited, tol) for k in hrs) / len(hrs) if hrs else None
        best_mode, best = None, 0.0
        for m, cs in cited.items():
            r = sum(_near(k, cs, tol) for k in steps) / len(steps)
            if r > best:
                best_mode, best = m, r
        tags[tg] = {"steps": len(steps), "high_regret_steps": len(hrs), "recall": round(rec, 4),
                    "recall_high_regret": round(rec_hr, 4) if rec_hr is not None else None,
                    "best_mode": best_mode, "best_mode_recall": round(best, 4),
                    "regret": round(sum(T["regret"].get(k, 0) for k in steps), 4)}
    tagged_all = set().union(*T["tag_steps"].values()) if T["tag_steps"] else set()
    modes = {}
    for m, cs in cited.items():
        n = len(cs)
        hit_hr = sum(_near(k, T["hr"], tol) for k in cs)
        hit_tag = sum(_near(k, tagged_all, tol) for k in cs)
        overlap = {tg: sum(_near(k, T["tag_steps"][tg], tol) for k in cs) for tg in T["tag_steps"]}
        top_tag = max(overlap, key=overlap.get) if overlap and max(overlap.values()) > 0 else None
        modes[m] = {"cited_steps": n, "precision_high_regret": round(hit_hr / n, 4) if n else None,
                    "precision_tagged": round(hit_tag / n, 4) if n else None,
                    "regret": round(sum(T["regret"].get(k, 0) for k in cs), 4),
                    "top_tag": top_tag, "top_tag_share": round(overlap[top_tag] / n, 4) if top_tag and n else 0.0,
                    "novel": (hit_tag / n if n else 0) < 0.3}
    covered = sum(v for k, v in T["regret"].items() if _near(k, all_cited, 0))
    recovered = [tg for tg, d in tags.items() if d["recall"] >= 0.3]
    return {"tolerance_steps": tol, "tags": tags, "modes": modes,
            "cited_steps": len(all_cited),
            "precision_high_regret": round(sum(_near(k, T["hr"], tol) for k in all_cited) / len(all_cited), 4)
            if all_cited else None,
            "precision_tagged": round(sum(_near(k, tagged_all, tol) for k in all_cited) / len(all_cited), 4)
            if all_cited else None,
            "regret_share_covered": round(covered / T["total_regret"], 4) if T["total_regret"] else None,
            "high_regret_steps": len(T["hr"]),
            "high_regret_recall": round(sum(_near(k, all_cited, tol) for k in T["hr"]) / len(T["hr"]), 4)
            if T["hr"] else None,
            "tags_recovered": recovered, "n_tags": len(tags),
            "novel_modes": [m for m, d in modes.items() if d["novel"]]}


def verify_agent_quote(ep: Episode | None, t: int, quote: str, window: int = 2) -> dict:
    """Agent-authored text only: the agent's own words at step t or the `window` steps before it (episode-level as a
    weaker check). Harness/code lines (step lines, headers) never count."""
    if ep is None or not quote.strip():
        return {"verified": False, "step_verified": False, "empty": not quote.strip()}
    idx = next((i for i, s in enumerate(ep.steps) if s.t == t), None)
    near = "\n".join(s.rationale for s in ep.steps[max(0, (idx or 0) - window):(idx or 0) + 1]) if idx is not None else ""
    ep_ok = quote_in(quote, ep.rationale_text())
    return {"verified": ep_ok, "step_verified": bool(ep_ok and quote_in(quote, near)), "empty": False}


def run(args) -> dict:
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir) if args.cache_dir else out / "atlas_cache_blind"
    snap = cache_dir / "corpus.json.gz"
    if args.replay and snap.exists():
        eps = load_snapshot(snap)
    else:
        runs = [str(ROOT / r) if not Path(r).is_absolute() else r for r in args.runs]
        eps = load_corpus([r for r in runs if Path(r).exists()])
        save_snapshot(eps, snap)
    text, blocks = pack_corpus_blind(eps)
    sha = hashlib.sha256(text.encode()).hexdigest()
    ops = AtlasOps(replay=args.replay, cache_dir=cache_dir)
    model = args.cache_model
    errors: list[str] = []
    tokens = ops.count_tokens(model, text)
    print(f"blind corpus: {len(eps)} episodes, {tokens:,} tokens", flush=True)
    import threading
    lock = threading.Lock()
    state = {"name": None, "tokens": ops.recorded_cache_tokens(model, text, SYSTEM_BLIND)}

    def lazy():
        with lock:
            if state["name"] is None:
                state["name"], state["tokens"] = ops.create_cache(model, text, SYSTEM_BLIND)
                print(f"context cache {state['tokens']:,} tokens", flush=True)
            return state["name"]

    def ask(q, schema, tag):
        try:
            r = ops.generate(model, [q], schema=inline_schema(schema), tag=tag, cache_name=lazy, cache_key=sha,
                             thinking_level="medium")
        except (ReplayMiss, Exception) as e:  # noqa: BLE001
            errors.append(f"{tag}: {type(e).__name__}: {str(e)[:200]}")
            return None, None
        p, err = parse(r.get("text", ""), schema)
        if p is None:
            errors.append(f"{tag}: {err}")
        return p, r
    tax, r0 = ask(DISCOVER, BlindTaxonomy, "blind:discover")
    if tax is None:
        ops.delete_cache(state["name"])
        raise SystemExit(f"blind discovery failed: {errors[-1:]}")
    print(f"blind taxonomy: {[m.id for m in tax.modes]}", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        mined = list(ex.map(lambda m: ask(mine_q(m), Mined, f"blind:mine:{m.id}"), tax.modes))
    ops.delete_cache(state["name"])
    by = {e.id: e for e in eps}
    valid = {(e.id, s.t) for e in eps for s in e.steps} | {(e.id, len(e.steps)) for e in eps}
    cited: dict[str, set] = {}
    invalid = Counter()
    for m, (mm, _) in zip(tax.modes, mined):
        cs = set()
        for c in list(m.examples) + (mm.steps if mm else []):
            k = (c.episode, c.t)
            if k in valid:
                cs.add(k)
            else:
                invalid[m.id] += 1
        cited[m.id] = cs
    rec = score_recovery(eps, cited)
    qrows = []
    for m in tax.modes:
        for c in m.examples:
            v = verify_agent_quote(by.get(c.episode), c.t, c.quote)
            qrows.append({"mode": m.id, "episode": c.episode, "t": c.t, "quote": c.quote, **v})
    nq = [q for q in qrows if not q["empty"]]
    from .atlas import git_sha
    mv = (r0 or {}).get("model_version")
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "git_sha": git_sha(),
        "ledger_run_ids": sorted(ops.source_run_ids), "model": model, "model_version": mv,
        "blind": True,
        "blind_pack": "tool calls, tool results as the agent saw them, the agent's own words, final outcome; no regret, "
                      "tags, solver beliefs, true mole or solver scores (tests/test_gemini_lab_atlas.py)",
        "corpus": {"episodes": len(eps), "tokens": tokens, "cache_tokens": state["tokens"], "sha256": sha},
        "summary": tax.summary,
        "modes": [{**m.model_dump(exclude={"examples"}), "examples": [q for q in qrows if q["mode"] == m.id],
                   "cited_steps": len(cited[m.id]), "invalid_citations": invalid[m.id],
                   **rec["modes"].get(m.id, {})} for m in tax.modes],
        "recovery": rec,
        "quotes": {"checked": len(nq), "verified_agent_text": sum(q["verified"] for q in nq),
                   "verified_at_step": sum(q["step_verified"] for q in nq), "empty": len(qrows) - len(nq),
                   "rule": "a quote counts only if it appears verbatim in the agent's own words"},
        "errors": errors, "replay": bool(args.replay),
        "spend": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ops.stats.items()},
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out / "atlas_blind.json").write_text(json.dumps(result, indent=1, default=str))
    (out / "atlas_blind.md").write_text(render(result))
    print(f"wrote {out/'atlas_blind.json'}: recovered {len(rec['tags_recovered'])}/{rec['n_tags']} tags, "
          f"precision(hr) {rec['precision_high_regret']}, regret covered {rec['regret_share_covered']}, "
          f"quotes {result['quotes']['verified_agent_text']}/{len(nq)}", flush=True)
    return result


def _p(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def render(r: dict) -> str:
    rec, q = r["recovery"], r["quotes"]
    novel = rec["novel_modes"]
    out = ["# Canary Failure Atlas, blind", "",
           f"*Generated {r['generated_at']} at `{r['git_sha']}`; model `{r['model']}` (served `{r['model_version']}`); "
           f"ledger run ids {', '.join(r['ledger_run_ids']) or '-'}.*", "",
           f"**Gemini, without seeing our labels, recovered {len(rec['tags_recovered'])} of {rec['n_tags']} "
           f"code-defined failure modes** (recall >= 30% of the tag's steps cited) **and named {len(novel)} "
           f"mode(s) our tags don't have.** Its cited steps cover {_p(rec['regret_share_covered'])} of all solver "
           f"regret; {_p(rec['precision_high_regret'])} of the steps it cites are high-regret "
           f"(regret >= {HIGH_REGRET}) and {_p(rec['precision_tagged'])} carry a code tag.", "",
           f"What Gemini saw: {r['corpus']['episodes']} episodes, {r['corpus']['tokens']:,} tokens, held in one explicit "
           "context cache. Only tool calls, tool results as the agent saw them, the agent's own words and the "
           "final outcome. No regret, no tags, no solver belief, no true mole, no solver score (a test checks the "
           "pack). Gemini first named the modes with examples, then listed every step of each mode; all scoring "
           "below is computed in code against `canary/analysis/tags.py` and the solver regret, which Gemini never saw.",
           "", "## Recall per code tag", "",
           f"A cited step matches a tagged step in the same episode within {rec['tolerance_steps']} step(s).", "",
           "| code tag | tagged steps | regret | recall (any Gemini mode) | recall on high-regret steps | best-matching Gemini mode |",
           "|---|---|---|---|---|---|"]
    for tg, d in sorted(rec["tags"].items(), key=lambda kv: -kv[1]["regret"]):
        out.append(f"| `{tg}` | {d['steps']} | {d['regret']:.2f} | {_p(d['recall'])} | {_p(d['recall_high_regret'])} | "
                   f"`{d['best_mode']}` ({_p(d['best_mode_recall'])}) |")
    out += ["", f"All high-regret steps: {rec['high_regret_steps']}; Gemini cited {_p(rec['high_regret_recall'])} of them.",
            "", "## Gemini's modes", "",
            "| mode | cited steps | precision (high-regret) | precision (tagged) | regret of cited steps | closest tag | new? |",
            "|---|---|---|---|---|---|---|"]
    for m in r["modes"]:
        out.append(f"| **{m['name']}** (`{m['id']}`) | {m['cited_steps']} | {_p(m.get('precision_high_regret'))} | "
                   f"{_p(m.get('precision_tagged'))} | {m.get('regret', 0):.2f} | `{m.get('top_tag')}` "
                   f"({_p(m.get('top_tag_share'))}) | {'yes' if m.get('novel') else ''} |")
    out += ["", r["summary"], ""]
    for m in r["modes"]:
        out += [f"### {m['name']}", "", m["description"], "", f"*Why:* {m['why']}", ""]
        for ex in [e for e in m["examples"] if e["verified"]][:2]:
            out.append(f"> `{ex['episode']}` t={ex['t']}: \"{' '.join(ex['quote'].split())[:240]}\"")
        out.append("")
    out += ["## Quote check (agent-authored text only)", "",
            f"{q['verified_agent_text']}/{q['checked']} quotes appear verbatim in the agent's own words "
            f"({q['verified_at_step']} at or just before the cited step); {q['empty']} examples had no agent text to "
            "quote. Step records, headers and anything the harness or our code generated never count.", "",
            "Reproduce offline: `python -m canary.gemini.atlas --blind --replay`.", ""]
    if r["errors"]:
        out += ["Run notes: " + "; ".join(r["errors"][:5]), ""]
    return "\n".join(out)
