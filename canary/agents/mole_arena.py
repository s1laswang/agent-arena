"""Arena mode (NOT the judge path): an LLM plays the mole, day by day, within the rules.

    mole = LLMMole(client)
    mole.decide(view) -> {"leak": doc_id | None, "frame": employee_id | None}

`view` is a MoleView (CONTRACT section 7) as an object or dict:
    held_docs: [{doc_id, title, recipient_count, age_days}], days_since_last_leak, i_am_restricted,
    n_restricted_colleagues, recent_low_recipient_docs, day   (+ optional `peers`: [employee_id])
The mole never sees canary flags or the investigator. Same `.decide(view)` signature as
canary.mole.dsl.MoleStrategy, so it plugs into ENV's strategy hook (World.mole_strategy).
Invalid choices (unknown doc, malformed id, schema-invalid output) become "none"; the env
validates again (p_leak still gates leaking).
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from ._common import get, load_prompt, structured_call

_EID = re.compile(r"^e\d{2,3}$")


class MoleMove(BaseModel):
    leak: str | None = None
    frame: str | None = None
    reason: str = Field(default="", max_length=300)


def view_to_dict(view: Any) -> dict:
    docs = []
    for d in get(view, "held_docs", None) or get(view, "docs", None) or []:
        docs.append({k: get(d, k) for k in ("doc_id", "title", "recipient_count", "age_days")})
    out = {"day": get(view, "day", 0), "held_docs": docs,
           "days_since_last_leak": get(view, "days_since_last_leak"),
           "i_am_restricted": bool(get(view, "i_am_restricted", False)),
           "n_restricted_colleagues": get(view, "n_restricted_colleagues", 0),
           "recent_low_recipient_docs": get(view, "recent_low_recipient_docs", 0)}
    peers = get(view, "peers", None)
    if peers:
        out["peers"] = list(peers)
    return out


class LLMMole:
    name = "llm-mole"

    def __init__(self, client, temperature: float = 0.4):
        self.client = client
        self.temperature = temperature
        self.system = load_prompt("mole_arena").get("system", "You are a mole. Choose leak/frame.")
        self.log: list[dict] = []   # per-day {view, move, error, rejected}

    @classmethod
    def from_json(cls, obj):  # parity with MoleStrategy; not used for LLM moles
        raise TypeError("LLMMole is built from a client, not JSON")

    def decide(self, view: Any) -> dict:
        v = view_to_dict(view)
        parsed, err = structured_call(self.client, self.system, json.dumps(v), MoleMove, self.temperature)
        move = {"leak": None, "frame": None}
        rejected = []
        if parsed is not None:
            held = {d["doc_id"] for d in v["held_docs"]}
            if parsed.leak in held:
                move["leak"] = parsed.leak
            elif parsed.leak not in (None, "", "none", "null"):
                rejected.append(f"leak:{parsed.leak}")
            f = parsed.frame
            if f and _EID.match(f) and (not v.get("peers") or f in v["peers"]):
                move["frame"] = f
            elif f not in (None, "", "none", "null"):
                rejected.append(f"frame:{f}")
        self.log.append({"day": v["day"], "move": dict(move), "error": err, "rejected": rejected,
                         "reason": parsed.reason if parsed else None})
        return move


def attach_mole(env: Any, mole: Any) -> bool:
    """Install `mole` as the env's mole strategy (arena only). Returns True if a hook was found."""
    for holder in (env, get(env, "world", None), get(env, "_world", None)):
        if holder is None:
            continue
        for meth in ("set_mole_strategy",):
            if callable(getattr(holder, meth, None)):
                getattr(holder, meth)(mole)
                return True
        if hasattr(holder, "mole_strategy"):
            try:
                setattr(holder, "mole_strategy", mole)
                return True
            except Exception:
                pass
    return False
