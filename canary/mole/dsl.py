"""Mole DSL (CONTRACT section 7): a JSON rule language + deterministic interpreter. No code execution.

Strategy JSON:
  {"rules": [{"if": [["days_since_last_leak", ">=", 2], ...], "then": {"leak": "<sel>"|null, "frame": "<fsel>"|null}}, ...],
   "default": {"leak": "random_seeded", "frame": "none"}}          # "default" optional
Conditions may also be strings "feature op number". All conditions of a rule must hold (AND); an
empty "if" always matches. First matching rule wins, else the default rule. p_leak still gates leaking.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

FEATURES = ("day", "days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
            "recent_low_recipient_docs", "n_leakable")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
       ">=": lambda a, b: a >= b, "==": lambda a, b: a == b}
LEAK_SELECTORS = ("newest", "oldest", "most_recipients", "fewest_recipients", "random_seeded", "none")
FRAME_SELECTORS = ("decoy", "most_restricted_peer", "random_peer", "none")
MAX_RULES = 12


class StrategyError(ValueError):
    pass


@dataclass(frozen=True)
class MoleDoc:
    doc_id: str
    title: str
    recipient_count: int
    age_days: int


@dataclass(frozen=True)
class MoleView:
    """Only what the mole can see. Never says which docs are canaries."""
    day: int
    docs: tuple[MoleDoc, ...]            # leakable docs (held, inside the leak window, not yet leaked), received order
    days_since_last_leak: int            # = day if never leaked
    i_am_restricted: int                 # 0/1
    n_restricted_colleagues: int
    recent_low_recipient_docs: int       # leakable docs with recipient_count <= rules.low_recipient_threshold
    peers: tuple[str, ...]               # all other employee ids
    restricted_peers: tuple[str, ...]
    decoy: str | None
    can_leak: bool                       # the p_leak gate passed today (drawn by the env)
    # Tier mechanic, not mole knowledge: careful_mole selection weights for random_seeded (env-supplied).
    select_weights: tuple[float, ...] | None = None

    def feature(self, name: str) -> float:
        if name == "n_leakable":
            return len(self.docs)
        return getattr(self, name)


def _cond(c: Any) -> tuple[str, str, float]:
    if isinstance(c, str):
        parts = c.split()
        if len(parts) != 3:
            raise StrategyError("bad condition")
        f, op, n = parts
        try:
            n = float(n)
        except ValueError:
            raise StrategyError("bad number")
    elif isinstance(c, (list, tuple)) and len(c) == 3:
        f, op, n = c
    else:
        raise StrategyError("bad condition")
    if f not in FEATURES or op not in OPS:
        raise StrategyError("bad feature/op")
    if isinstance(n, bool) or not isinstance(n, (int, float)) or n != n or abs(n) > 1e6:
        raise StrategyError("bad number")
    return (f, op, float(n))


def _then(t: Any) -> tuple[str, str]:
    if not isinstance(t, dict) or set(t) - {"leak", "frame"}:
        raise StrategyError("bad then")
    leak = t.get("leak") or "none"
    frame = t.get("frame") or "none"
    if leak not in LEAK_SELECTORS or frame not in FRAME_SELECTORS:
        raise StrategyError("bad selector")
    return (leak, frame)


@dataclass(frozen=True)
class MoleStrategy:
    rules: tuple[tuple[tuple[tuple[str, str, float], ...], tuple[str, str]], ...]
    default: tuple[str, str] = ("random_seeded", "none")
    name: str = "custom"

    @classmethod
    def from_json(cls, obj: Any) -> "MoleStrategy":
        if not isinstance(obj, dict) or set(obj) - {"rules", "default", "name"}:
            raise StrategyError("bad strategy")
        rules = obj.get("rules", [])
        if not isinstance(rules, list) or len(rules) > MAX_RULES:
            raise StrategyError("bad rules")
        out = []
        for r in rules:
            if not isinstance(r, dict) or set(r) != {"if", "then"} or not isinstance(r["if"], list):
                raise StrategyError("bad rule")
            out.append((tuple(_cond(c) for c in r["if"]), _then(r["then"])))
        default = _then(obj["default"]) if "default" in obj else ("random_seeded", "none")
        name = obj.get("name", "custom")
        if not isinstance(name, str) or len(name) > 80:
            raise StrategyError("bad name")
        return cls(tuple(out), default, name)

    def to_json(self) -> dict:
        return {"name": self.name,
                "rules": [{"if": [list(c) for c in conds], "then": {"leak": l, "frame": f}} for conds, (l, f) in self.rules],
                "default": {"leak": self.default[0], "frame": self.default[1]}}

    def decide(self, view: MoleView, rng: random.Random) -> dict:
        leak_sel, frame_sel = self.default
        for conds, then in self.rules:
            if all(OPS[op](view.feature(f), n) for f, op, n in conds):
                leak_sel, frame_sel = then
                break
        return {"leak": _select_leak(leak_sel, view, rng), "frame": _select_frame(frame_sel, view, rng)}


def _select_leak(sel: str, v: MoleView, rng: random.Random) -> str | None:
    docs = v.docs
    if sel == "none" or not docs or not v.can_leak:
        return None
    if sel == "random_seeded":
        w = list(v.select_weights) if v.select_weights is not None else [1.0] * len(docs)
        if sum(w) <= 0:
            return None
        return rng.choices([d.doc_id for d in docs], weights=w)[0]
    # deterministic selectors: ties -> first in received order
    key = {"newest": lambda d: d.age_days, "oldest": lambda d: -d.age_days,
           "most_recipients": lambda d: -d.recipient_count, "fewest_recipients": lambda d: d.recipient_count}[sel]
    return min(docs, key=key).doc_id


def _select_frame(sel: str, v: MoleView, rng: random.Random) -> str | None:
    if sel == "decoy":
        return v.decoy
    if sel == "most_restricted_peer":
        return v.restricted_peers[0] if v.restricted_peers else None
    if sel == "random_peer":
        return rng.choice(v.peers) if v.peers else None
    return None


DEFAULT_STRATEGY = MoleStrategy(rules=(), default=("random_seeded", "none"), name="default_v0")


def random_strategy(rng: random.Random, max_rules: int = 6) -> MoleStrategy:
    rules = []
    for _ in range(rng.randint(0, max_rules)):
        conds = [[rng.choice(FEATURES), rng.choice(list(OPS)), rng.randint(0, 6)] for _ in range(rng.randint(1, 2))]
        rules.append({"if": conds, "then": {"leak": rng.choice(LEAK_SELECTORS), "frame": rng.choice(FRAME_SELECTORS)}})
    return MoleStrategy.from_json({"name": "random", "rules": rules,
                                   "default": {"leak": rng.choice(LEAK_SELECTORS[:-1]), "frame": rng.choice(FRAME_SELECTORS)}})
