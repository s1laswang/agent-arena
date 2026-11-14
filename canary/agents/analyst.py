"""Failure analyst: pack N episodes + regret tags into one long-context prompt; get clustered
failure modes with verbatim quotes (structured output); render markdown. Deterministic fallback
clusters by tag counts when the LLM is unavailable or its output is invalid/unverifiable.

    md = analyze(episodes, tags, client)
episodes: list[EpisodeResult | dict]; tags: list aligned with episodes, each a list of
{t, action, regret, tags[]} (canary.solver.regret.attribute output) or plain tag strings.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import BaseModel, Field

from ._common import load_prompt, structured_call


class Quote(BaseModel):
    episode: str
    quote: str = Field(max_length=300)


class Cluster(BaseModel):
    name: str = Field(max_length=80)
    count: int = Field(ge=0)
    description: str = Field(max_length=600)
    quotes: list[Quote] = Field(default_factory=list, max_length=3)


class Report(BaseModel):
    summary: str = Field(default="", max_length=1200)
    clusters: list[Cluster] = Field(default_factory=list, max_length=10)


def _ep(e: Any) -> dict:
    return asdict(e) if is_dataclass(e) else dict(e)


def _tag_names(tag_list: Any) -> list[str]:
    out = []
    for t in tag_list or []:
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            out += [str(x) for x in t.get("tags", [])]
    return out


def _fmt_step(s: dict) -> str:
    args = ",".join(f"{k}={v}" for k, v in (s.get("args") or {}).items())
    res = s.get("result") or {}
    brief = "ok" if res.get("ok", True) else f"ERR {res.get('error')}"
    return f"d{s.get('day')} {s.get('tool')}({args}) -> {brief}"


def pack(episodes: list, tags: list, max_steps: int = 40, max_chars: int = 900_000) -> tuple[str, dict[str, str]]:
    """Compact text, one block per episode. Returns (text, {episode_key: block}) for quote checking."""
    blocks: dict[str, str] = {}
    for i, e in enumerate(episodes):
        d = _ep(e)
        key = f"{d.get('agent')}/{d.get('tier')}/{d.get('seed')}#{i}"
        tg = tags[i] if i < len(tags) else []
        lines = [f"### {key} score={d.get('score', 0):.3f} correct={d.get('correct')} accused={d.get('accused')} "
                 f"day={d.get('final_day')} end={d.get('end_reason')}",
                 "tags: " + ", ".join(sorted(set(_tag_names(tg)))) or "-"]
        for t in tg or []:
            if isinstance(t, dict) and t.get("regret", 0) > 0:
                lines.append(f"regret t={t.get('t')} {t.get('action')} r={t.get('regret'):.3f} {t.get('tags')}")
        steps = [s if isinstance(s, dict) else _ep(s) for s in d.get("steps") or []]
        lines += [_fmt_step(s) for s in steps[:max_steps]]
        if len(steps) > max_steps:
            lines.append(f"... {len(steps) - max_steps} more steps")
        blocks[key] = "\n".join(lines)
    text = "\n\n".join(blocks.values())
    return text[:max_chars], blocks


def fallback_report(episodes: list, tags: list, top: int = 6) -> Report:
    counts: Counter[str] = Counter()
    where: dict[str, list[int]] = defaultdict(list)
    for i in range(len(episodes)):
        for name in sorted(set(_tag_names(tags[i] if i < len(tags) else []))):
            counts[name] += 1
            where[name].append(i)
    _, blocks = pack(episodes, tags)
    keys = list(blocks)
    clusters = []
    for name, c in counts.most_common(top):
        q = [Quote(episode=keys[i], quote=blocks[keys[i]].splitlines()[0][:300]) for i in where[name][:2]]
        clusters.append(Cluster(name=name, count=c, description=f"{c}/{len(episodes)} episodes carry tag '{name}'.",
                                quotes=q))
    n_ok = sum(1 for e in episodes if _ep(e).get("correct"))
    return Report(summary=f"{len(episodes)} episodes, {n_ok} correct accusations. Clusters = regret-tag counts "
                          "(deterministic fallback, no LLM).", clusters=clusters)


def _verify(r: Report, blocks: dict[str, str]) -> Report | None:
    """Keep only quotes that literally appear in the named episode; reject reports with no grounded cluster."""
    good = []
    for c in r.clusters:
        qs = [q for q in c.quotes if q.episode in blocks and q.quote.strip() and q.quote.strip() in blocks[q.episode]]
        if qs:
            good.append(c.model_copy(update={"quotes": qs}))
    return r.model_copy(update={"clusters": good}) if good else None


def render(r: Report, source: str) -> str:
    out = [f"# Failure-mode report ({source})", "", r.summary, ""]
    for c in r.clusters:
        out += [f"## {c.name} ({c.count})", "", c.description, ""]
        out += [f"> `{q.episode}`: {q.quote}" for q in c.quotes]
        out.append("")
    return "\n".join(out)


def analyze(episodes: list, tags: list, client, return_report: bool = False):
    text, blocks = pack(episodes, tags)
    cfg = load_prompt("analyst")
    parsed, err = structured_call(client, cfg.get("system", "Cluster failure modes."), text, Report)
    report = _verify(parsed, blocks) if parsed else None
    source = "llm" if report else f"fallback{': ' + err if err else ''}"
    report = report or fallback_report(episodes, tags)
    md = render(report, "llm" if source == "llm" else "fallback: tag counts")
    return (md, report, source) if return_report else md
