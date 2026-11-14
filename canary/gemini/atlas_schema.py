"""Failure Atlas: structured-output schemas (pydantic -> response_json_schema) and code-side verification.

Gemini never supplies a number the atlas reports: regret shares, episode counts and agreement rates are
computed in code. Gemini's quotes are kept only if they appear verbatim in the named episode (and, for
step-level claims, in that step's lines); everything else is dropped and counted.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

M = TypeVar("M", bound=BaseModel)

DECISIONS = ("canary_design", "evidence_gathering", "commit_timing", "accusation_target", "restriction",
             "budget_use", "other")
Decision = Literal["canary_design", "evidence_gathering", "commit_timing", "accusation_target", "restriction",
                   "budget_use", "other"]


class Evidence(BaseModel):
    episode: str = Field(description="episode id exactly as in '=== EPISODE <id>'")
    t: int = Field(description="step number t of the decision")
    quote: str = Field(description="5-40 words copied VERBATIM from that episode block (prefer the agent's "
                                   "`says:` words at or just before step t; else the step line itself)")
    why: str = Field(default="", description="one sentence: why this step shows the failure mode")


class Mode(BaseModel):
    id: str = Field(description="short snake_case id, e.g. wide_canary_split")
    name: str = Field(description="human-readable name, <= 8 words")
    description: str = Field(description="what goes wrong, in 2-3 sentences, in terms of the agent's decisions")
    decision: Decision = Field(description="which decision type fails")
    mechanism: str = Field(description="why the agent makes this mistake (its belief or reasoning error)")
    solver_would: str = Field(description="what the Bayesian reference solver does instead at such a step")
    evidence: list[Evidence] = Field(description="3-8 concrete steps from DIFFERENT episodes where possible")


class Taxonomy(BaseModel):
    summary: str = Field(description="3-5 sentence overview of why these agents lose value vs the solver")
    modes: list[Mode] = Field(description="4-8 failure modes, most regret first; must be mutually exclusive")


class StepLabel(BaseModel):
    episode: str
    t: int
    mode: str = Field(description="one mode id from the taxonomy, or 'other'")
    confidence: float = Field(description="0..1")
    quote: str = Field(description="5-30 words VERBATIM from this step's lines or the agent's words right before it")
    explanation: str = Field(description="one sentence")


class StepLabels(BaseModel):
    labels: list[StepLabel]


class SingleLabel(BaseModel):
    mode: str = Field(description="one mode id from the taxonomy, or 'other'")
    confidence: float = Field(description="0..1")
    quote: str = Field(description="5-30 words VERBATIM from the >>> step line or the agent's words right before it")
    explanation: str = Field(description="one sentence")


class CohortFinding(BaseModel):
    cohort: str = Field(description="cohort id exactly as given (model/harness/tiers_version)")
    dominant_modes: list[str] = Field(description="mode ids, most characteristic first")
    behaviour: str = Field(description="2-3 sentences: how this cohort plays and fails, vs the others")
    evidence: list[Evidence] = Field(description="1-3 verbatim quotes")


class Comparison(BaseModel):
    cohorts: list[CohortFinding]
    cross_family_finding: str = Field(description="the single most important difference between the Gemini "
                                                  "cohorts and the GPT/Grok cohorts, honest about sample size and "
                                                  "that tiers versions differ")
    caveats: str


class Counterfactual(BaseModel):
    episode: str
    t: int
    agent_did: str
    solver_would: str = Field(description="what the reference solver would have done at this step and why")
    why_diverged: str = Field(description="the agent's belief or reasoning error behind the difference")
    quote: str = Field(description="5-30 words VERBATIM from the episode at or before step t")


class Counterfactuals(BaseModel):
    items: list[Counterfactual]


class Divergence(BaseModel):
    divergence_t: int = Field(description="step t where the agent's course departs from what the solver's "
                                          "belief supports (read it off the chart and the excerpt)")
    what_chart_shows: str = Field(description="describe the curves around that step")
    what_agent_believed: str
    quote: str = Field(description="5-30 words VERBATIM from the excerpt")


class ClusterName(BaseModel):
    cluster: int
    name: str = Field(description="<= 6 words")
    description: str = Field(description="one sentence on the shared reasoning pattern")


class ClusterNames(BaseModel):
    clusters: list[ClusterName]


class ThinkingFinding(BaseModel):
    model: str
    effect: str = Field(description="what changes in the agent's decisions as thinking level rises")
    modes_reduced: list[str]
    modes_unchanged: list[str]
    evidence: list[Evidence]


class ThinkingEffects(BaseModel):
    findings: list[ThinkingFinding]
    summary: str


def inline_schema(model: type[BaseModel]) -> dict:
    """pydantic JSON schema with $refs inlined and titles/defaults dropped (Gemini structured output)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


def parse(text: str, model: type[M]) -> tuple[M | None, str | None]:
    try:
        t = (text or "").strip()
        if t.startswith("```"):
            t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
        return model.model_validate(json.loads(t)), None
    except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as e:
        return None, f"{type(e).__name__}: {str(e)[:200]}"


# ------------------------------------------------------------------------------------- quote verification

_TRANS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        " ": " ", "`": "'", "*": ""})


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_TRANS)
    return re.sub(r"\s+", " ", s).strip().lower()


def _fragments(quote: str) -> list[str]:
    q = norm(quote).strip(" '\"")
    q = re.sub(r"^(says:\s*)", "", q)
    frags = [f.strip(" '\".,;:") for f in re.split(r"\.\.\.|…|\[\.\.\.\]", q)]
    return [f for f in frags if f]


def quote_in(quote: str, haystack: str, min_chars: int = 12) -> bool:
    """True iff every fragment of the quote (split on ellipses) appears verbatim (after whitespace/quote-mark
    normalisation, case-insensitive) in the haystack, in order, and the quote has substance."""
    frags = _fragments(quote)
    if not frags or sum(len(f) for f in frags) < min_chars:
        return False
    h, pos = norm(haystack), 0
    for f in frags:
        i = h.find(f, pos)
        if i < 0:
            return False
        pos = i + len(f)
    return True


class Verifier:
    """Checks quotes against the corpus: episode-level (anywhere in that episode's block or full rationale) and
    step-level (in step t's line, its `says:` text, or the agent text of the previous `window` steps)."""

    def __init__(self, eps: list, blocks: dict[str, str], window: int = 2):
        from .atlas_data import pack_episode, step_line
        self.blocks = blocks
        self.eps = {ep.id: ep for ep in eps}
        self.full = {ep.id: blocks.get(ep.id, pack_episode(ep)) + "\n" + ep.rationale_text() for ep in eps}
        self.words = {ep.id: ep.rationale_text() for ep in eps}
        self.step_text: dict[tuple[str, int], str] = {}
        for ep in eps:
            for i, s in enumerate(ep.steps):
                parts = []
                for p in ep.steps[max(0, i - window): i + 1]:
                    parts.append(p.rationale)
                parts.append(step_line(s))
                self.step_text[(ep.id, s.t)] = "\n".join(parts)
        self.n_checked = 0
        self.n_verified = 0
        self.n_step_verified = 0
        self.dropped: list[dict] = []

    def check(self, episode: str, t: int | None, quote: str, context: str = "") -> dict:
        self.n_checked += 1
        ep_ok = episode in self.full and quote_in(quote, self.full[episode])
        step_ok = bool(ep_ok and t is not None and quote_in(quote, self.step_text.get((episode, t), "")))
        self.n_verified += ep_ok
        self.n_step_verified += step_ok
        if not ep_ok:
            self.dropped.append({"episode": episode, "t": t, "quote": quote[:200], "context": context,
                                 "reason": "unknown episode" if episode not in self.full else "not verbatim"})
        source = "agent_words" if ep_ok and quote_in(quote, self.words.get(episode, "")) else "step_record"
        return {"episode": episode, "t": t, "quote": quote, "verified": ep_ok, "step_verified": step_ok,
                "source": source}

    def summary(self) -> dict[str, Any]:
        n = max(1, self.n_checked)
        return {"quotes_checked": self.n_checked, "quotes_verified": self.n_verified,
                "pass_rate": round(self.n_verified / n, 4), "step_verified": self.n_step_verified,
                "step_pass_rate": round(self.n_step_verified / n, 4), "dropped": len(self.dropped)}
