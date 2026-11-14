"""PAIRED-style scenario designer: the LLM proposes (mole DSL strategy + tier knobs); a scenario is
kept only if the reference solver still wins (>= X) AND the investigator under test fails (<= Y).

    cands = propose(client, tier="hard", n=4, history=[...])     # validated, clamped candidates
    keep, s, a = regret_filter(cand, solver_eval, agent_eval, X, Y)
    report = design_round(client, solver_eval, agent_eval, X=0.5, Y=0.3, tier="hard", n=4)

`solver_eval(candidate) -> float` and `agent_eval(candidate) -> float` are injected (mean score over
dev seeds in production, fakes in tests). This is the "every hard case is provably solvable" guarantee.
"""
from __future__ import annotations

import json
import random
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from canary.rules import TIERS

from ._common import load_prompt, structured_call

FEATURES = ("days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
            "recent_low_recipient_docs", "day", "n_held_docs", "min_recipient_count")
OPS = ("<", "<=", ">", ">=", "==")
LEAK_SEL = ("newest", "oldest", "most_recipients", "fewest_recipients", "random_seeded", "none")
FRAME_SEL = ("decoy", "most_restricted_peer", "random_peer", "none")
MAX_RULES = 12

# Knob ranges = envelope of the tier table in rules.py (designer may not leave it).
_FLOAT_KNOBS = ("p_leak", "leak_damage", "log_rate_mole", "interview_lr")
KNOB_RANGES: dict[str, tuple[float, float]] = {
    k: (min(getattr(t, k) for t in TIERS.values()), max(getattr(t, k) for t in TIERS.values()))
    for k in _FLOAT_KNOBS}
_BOOL_KNOBS = ("decoy", "framing", "careful_mole")


class Cond(BaseModel):
    feature: Literal[FEATURES]  # type: ignore[valid-type]
    op: Literal[OPS]            # type: ignore[valid-type]
    value: float


class Then(BaseModel):
    leak: Literal[LEAK_SEL] = "newest"   # type: ignore[valid-type]
    frame: Literal[FRAME_SEL] = "none"   # type: ignore[valid-type]


class Rule(BaseModel):
    conditions: list[Cond] = Field(default_factory=list, max_length=4)
    then: Then


class Knobs(BaseModel):
    p_leak: float | None = None
    leak_damage: float | None = None
    log_rate_mole: float | None = None
    interview_lr: float | None = None
    decoy: bool | None = None
    framing: bool | None = None
    careful_mole: bool | None = None


class Candidate(BaseModel):
    name: str = Field(default="", max_length=60)
    rationale: str = Field(default="", max_length=400)
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)
    knobs: Knobs = Field(default_factory=Knobs)


class Proposal(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list, max_length=8)


def to_dsl(c: Candidate) -> dict:
    """Candidate -> CONTRACT section 7 DSL JSON ({"rules": [{"if": [[f, op, v]...], "then": {...}}]})."""
    rules = [{"if": [[x.feature, x.op, x.value] for x in r.conditions],
              "then": {"leak": None if r.then.leak == "none" else r.then.leak,
                       "frame": None if r.then.frame == "none" else r.then.frame}} for r in c.rules]
    if not rules or rules[-1]["if"]:
        rules.append({"if": [], "then": {"leak": "random_seeded", "frame": None}})  # default rule
    return {"rules": rules[:MAX_RULES]}


def validate_dsl(dsl: dict) -> bool:
    """Prefer ENV's interpreter when it exists; else the local structural check."""
    try:
        from canary.mole.dsl import MoleStrategy  # type: ignore
        MoleStrategy.from_json(dsl)
        return True
    except ImportError:
        pass
    except Exception:
        return False
    rules = dsl.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= MAX_RULES:
        return False
    leaks = False
    for r in rules:
        for f, op, v in r.get("if", []):
            if f not in FEATURES or op not in OPS or not isinstance(v, (int, float)):
                return False
        t = r.get("then", {})
        if (t.get("leak") or "none") not in LEAK_SEL or (t.get("frame") or "none") not in FRAME_SEL:
            return False
        leaks |= t.get("leak") not in (None, "none")
    return leaks  # a mole that never leaks is unsolvable by construction


def clamp_knobs(k: Knobs) -> dict:
    out: dict[str, Any] = {}
    for name in _FLOAT_KNOBS:
        v = getattr(k, name)
        if v is not None:
            lo, hi = KNOB_RANGES[name]
            out[name] = round(min(hi, max(lo, float(v))), 4)
    for name in _BOOL_KNOBS:
        v = getattr(k, name)
        if v is not None:
            out[name] = bool(v)
    return out


def finalize(c: Candidate) -> dict | None:
    dsl = to_dsl(c)
    if not validate_dsl(dsl):
        return None
    return {"name": c.name or "unnamed", "rationale": c.rationale, "mole_strategy": dsl,
            "knobs": clamp_knobs(c.knobs)}


def fallback_candidates(n: int, seed: int = 0) -> list[dict]:
    """Deterministic random mutations of a trap-aware mole (used when the LLM output is unusable)."""
    rng = random.Random(f"designer:{seed}")
    out = []
    for i in range(n):
        rules = [Rule(conditions=[Cond(feature="recent_low_recipient_docs", op=">=", value=rng.choice([1, 2]))],
                      then=Then(leak="most_recipients", frame=rng.choice(["decoy", "none"]))),
                 Rule(conditions=[Cond(feature="days_since_last_leak", op="<", value=rng.choice([1, 2, 3]))],
                      then=Then(leak="none", frame="none")),
                 Rule(conditions=[], then=Then(leak=rng.choice(["newest", "oldest", "random_seeded"]),
                                               frame=rng.choice(["none", "random_peer"])))]
        knobs = Knobs(p_leak=round(rng.uniform(*KNOB_RANGES["p_leak"]), 3), careful_mole=rng.random() < 0.5)
        out.append(finalize(Candidate(name=f"fallback-{seed}-{i}", rationale="random mutation", rules=rules,
                                      knobs=knobs)))
    return [c for c in out if c]


def propose(client, tier: str = "hard", n: int = 4, history: list[dict] | None = None,
            seed: int = 0) -> tuple[list[dict], dict]:
    cfg = load_prompt("designer")
    user = json.dumps({"tier": tier, "n": n, "knob_ranges": KNOB_RANGES,
                       "base_tier": TIERS[tier].to_dict(), "history": (history or [])[-20:]})
    parsed, err = structured_call(client, cfg.get("system", "Propose scenarios."), user, Proposal,
                                  temperature=float(cfg.get("temperature", 0.9)))
    cands = [f for f in (finalize(c) for c in (parsed.candidates if parsed else [])) if f][:n]
    meta = {"llm_ok": parsed is not None, "error": err, "n_llm_valid": len(cands)}
    if len(cands) < n:
        cands += fallback_candidates(n - len(cands), seed)
    return cands, meta


def regret_filter(candidate: dict, solver_eval: Callable[[dict], float],
                  agent_eval: Callable[[dict], float], X: float, Y: float) -> tuple[bool, float, float]:
    """Scores may be negative (contract v0.3: wrong accusation = -1.0); thresholds are plain floats.
    Keep iff solver_eval(candidate) >= X and agent_eval(candidate) <= Y. Agent is only run if solver passes."""
    s = float(solver_eval(candidate))
    if s < X:
        return False, s, float("nan")
    a = float(agent_eval(candidate))
    return a <= Y, s, a


def design_round(client, solver_eval, agent_eval, X: float = 0.5, Y: float = 0.3,
                 tier: str = "hard", n: int = 4, history: list[dict] | None = None, seed: int = 0) -> dict:
    cands, meta = propose(client, tier, n, history, seed)
    rows = []
    for c in cands:
        keep, s, a = regret_filter(c, solver_eval, agent_eval, X, Y)
        rows.append({"name": c["name"], "keep": keep, "solver": s, "agent": a, "candidate": c,
                     "regret": (s - a) if a == a else float("nan"),  # scores may be negative (-1.0 wrong accusation)
                     "why": "kept" if keep else ("unsolvable (solver < X)" if s < X else "too easy (agent > Y)")})
    return {"tier": tier, "X": X, "Y": Y, "meta": meta, "rows": rows,
            "kept": [r["candidate"] for r in rows if r["keep"]]}
