"""Tool registry and dispatcher (SPEC section 5).

Define a tool:

    @tool(name="read_email", family="*", description="Read one email in full.",
          params={"email_id": {"type": "string", "description": "Email id like E3"}},
          required=["email_id"])
    def read_email(state, email_id): ...   # return JSON-able data or raise ToolError

`family="*"` = every family. `writes=True` marks tools that change the business state
(payments, flags, sent mail...). Baselines use it to find "the last write".

`dispatch(state, name, args, trajectory)` never raises. It returns
{"ok": bool, "result": ..., "error": str | None}.
"""
from __future__ import annotations

import inspect
import json
import math
from dataclasses import dataclass, field
from typing import Callable

MAX_STRING = 20000      # longest string argument we accept
MAX_ARRAY = 100         # longest array argument we accept
TRAJ_STRING = MAX_STRING  # longer strings are cut in the trajectory (they fail validation anyway)
CUT_MARK_RE = r"\.\.\.<cut (\d+) chars>$"
JSON_TYPES = ("string", "number", "integer", "boolean", "array", "object")


class ToolError(Exception):
    """Raise inside a tool to return a clean error to the agent. Do it BEFORE changing state."""


@dataclass
class ToolDef:
    name: str
    family: str
    description: str
    params: dict
    required: list
    func: Callable
    writes: bool = False
    defaults: dict = field(default_factory=dict)

    def spec(self) -> dict:
        props = {}
        for pname, p in self.params.items():
            props[pname] = {k: v for k, v in p.items() if k != "default"}
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": props, "required": list(self.required)},
        }


_REGISTRY: dict[tuple[str, str], ToolDef] = {}


def tool(name: str | None = None, family: str = "*", description: str = "", params: dict | None = None,
         required: list | None = None, writes: bool = False):
    """Register a tool function `func(state, **args)`."""
    params = dict(params or {})
    required = list(required or [])
    for pname, p in params.items():
        if p.get("type") not in JSON_TYPES:
            raise ValueError(f"tool param {pname!r} has bad type {p.get('type')!r}")
    for r in required:
        if r not in params:
            raise ValueError(f"required param {r!r} is not in params")

    def deco(func):
        tname = name or func.__name__
        sig = inspect.signature(func)
        defaults = {k: v.default for k, v in sig.parameters.items()
                    if v.default is not inspect.Parameter.empty}
        for pname in params:
            if pname not in sig.parameters:
                raise ValueError(f"tool {tname}: param {pname!r} is not an argument of the function")
            if pname not in required and pname not in defaults:
                raise ValueError(f"tool {tname}: optional param {pname!r} needs a default value")
        _REGISTRY[(family, tname)] = ToolDef(tname, family, description, params, required, func, writes, defaults)
        return func

    return deco


def _ensure_discovered() -> None:
    from . import tasks
    tasks.discover()


def _extra_tool_names(family: str) -> list[str]:
    from . import tasks
    try:
        return list(getattr(tasks.get_task(family), "extra_tools", ()) or ())
    except KeyError:
        return []


def tools_for_family(family: str) -> list[ToolDef]:
    """Shared tools first, then the family's own tools, then any extra tools the Task lists."""
    _ensure_discovered()
    out = [t for (fam, _), t in _REGISTRY.items() if fam == "*"]
    out += [t for (fam, _), t in _REGISTRY.items() if fam == family]
    names = {t.name for t in out}
    for extra in _extra_tool_names(family):
        if extra in names:
            continue
        for (fam, tname), t in _REGISTRY.items():
            if tname == extra:
                out.append(t)
                names.add(extra)
                break
    return out


def get_tool(family: str, name: str) -> ToolDef | None:
    for t in tools_for_family(family):
        if t.name == name:
            return t
    return None


def tool_specs(family: str) -> list[dict]:
    """[{"name", "description", "parameters": JSON-Schema object}] for this family."""
    return [t.spec() for t in tools_for_family(family)]


def write_tool_names(family: str) -> set[str]:
    return {t.name for t in tools_for_family(family) if t.writes}


# ---------------------------------------------------------------- validation

def _short(value, n: int = 60) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= n else text[:n] + "..."


def _check_type(pname: str, spec: dict, value, depth: int = 0):
    t = spec.get("type")
    label = f"argument '{pname}'"
    if t == "string":
        if not isinstance(value, str):
            raise ToolError(f"{label} must be a string")
        if len(value) > MAX_STRING:
            raise ToolError(f"{label} is too long (max {MAX_STRING} characters)")
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolError(f"{label} must be a number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ToolError(f"{label} must be a finite number")
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolError(f"{label} must be an integer")
    elif t == "boolean":
        if not isinstance(value, bool):
            raise ToolError(f"{label} must be true or false")
    elif t == "array":
        if not isinstance(value, list):
            raise ToolError(f"{label} must be an array")
        if len(value) > MAX_ARRAY:
            raise ToolError(f"{label} has too many items (max {MAX_ARRAY})")
        item_spec = spec.get("items")
        if item_spec and depth < 3:
            for item in value:
                _check_type(f"{pname}[]", item_spec, item, depth + 1)
    elif t == "object":
        if not isinstance(value, dict):
            raise ToolError(f"{label} must be an object")
    if "enum" in spec and value not in spec["enum"]:
        allowed = ", ".join(str(x) for x in spec["enum"])
        raise ToolError(f"{label} must be one of: {allowed}")


def validate_args(tdef: ToolDef, args) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError("arguments must be a JSON object")
    clean = {}
    for key, value in args.items():
        if not isinstance(key, str) or key not in tdef.params:
            allowed = ", ".join(tdef.params) or "none"
            raise ToolError(f"unknown argument '{_short(key, 40)}' for tool {tdef.name} (allowed: {allowed})")
        _check_type(key, tdef.params[key], value)
        clean[key] = value
    missing = [r for r in tdef.required if r not in clean]
    if missing:
        raise ToolError(f"missing required argument(s) for {tdef.name}: {', '.join(missing)}")
    return clean


# ---------------------------------------------------------------- dispatcher

def _trim_for_log(obj, depth: int = 0):
    """JSON-safe copy of args for the trajectory (cuts giant strings)."""
    if depth > 6:
        return "<too deep>"
    if obj is None or isinstance(obj, (bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else repr(obj)
    if isinstance(obj, str):
        return obj if len(obj) <= TRAJ_STRING else obj[:TRAJ_STRING] + f"...<cut {len(obj) - TRAJ_STRING} chars>"
    if isinstance(obj, (list, tuple)):
        items = [_trim_for_log(x, depth + 1) for x in list(obj)[:MAX_ARRAY + 1]]
        return items
    if isinstance(obj, dict):
        return {str(k)[:200]: _trim_for_log(v, depth + 1) for k, v in list(obj.items())[:200]}
    return _short(repr(obj), 200)


def _record(trajectory, i, name, args, out):
    if trajectory is None:
        return
    rec = {"i": i, "tool": name if isinstance(name, str) else _short(repr(name), 200),
           "args": _trim_for_log(args), "ok": out["ok"]}
    if out["ok"]:
        rec["result"] = out["result"]
    else:
        rec["error"] = out["error"]
    trajectory.append(rec)


def dispatch(state: dict, name, args=None, trajectory: list | None = None) -> dict:
    """Run one tool call. Never raises. See module doc."""
    try:
        return _dispatch(state, name, args, trajectory)
    except Exception as e:  # last-resort guard: the dispatcher must never raise
        out = {"ok": False, "result": None, "error": f"internal error: {type(e).__name__}"}
        try:
            _record(trajectory, len(trajectory) if trajectory is not None else -1, name, args, out)
        except Exception:
            pass
        return out


def _dispatch(state, name, args, trajectory):
    i = len(trajectory) if trajectory is not None else int(state.get("calls", 0))
    budget = int(state["meta"].get("budget", 100))
    if int(state.get("calls", 0)) >= budget:
        out = {"ok": False, "result": None, "error": "tool budget exhausted"}
        _record(trajectory, i, name, args, out)
        return out

    state["calls"] = int(state.get("calls", 0)) + 1
    state["clock"] = int(state.get("clock", 0)) + 1
    family = state["meta"]["family"]

    out = None
    tdef = None
    if not isinstance(name, str) or not name or len(name) > 100:
        out = {"ok": False, "result": None, "error": "tool name must be a short string"}
    else:
        tdef = get_tool(family, name)
        if tdef is None:
            avail = ", ".join(t.name for t in tools_for_family(family))
            out = {"ok": False, "result": None, "error": f"unknown tool '{_short(name, 60)}'. Available tools: {avail}"}
    if out is None:
        try:
            clean = validate_args(tdef, args)
            result = tdef.func(state, **clean)
            result = json.loads(json.dumps(result, ensure_ascii=False))  # detached copy; proves JSON-able
            out = {"ok": True, "result": result, "error": None}
        except ToolError as e:
            out = {"ok": False, "result": None, "error": str(e) or "tool error"}
        except Exception as e:
            out = {"ok": False, "result": None, "error": f"internal error in {name}: {type(e).__name__}"}

    if out["ok"]:
        counts = state.setdefault("tool_counts", {})
        counts[name] = int(counts.get(name, 0)) + 1
    _record(trajectory, i, name, args, out)
    fire_events(state)
    return out


# ---------------------------------------------------------------- events

def _trigger_met(state: dict, trig: dict) -> bool:
    ttype = trig.get("type")
    if ttype == "after_tool":
        return int(state.get("tool_counts", {}).get(trig.get("tool"), 0)) >= int(trig.get("count", 1))
    if ttype == "after_calls":
        return int(state.get("calls", 0)) >= int(trig.get("n", trig.get("count", 1)))
    return False


def _materialize(item, now: str):
    if isinstance(item, dict):
        return {k: (now if v == "@now" else _materialize(v, now)) for k, v in item.items()}
    if isinstance(item, list):
        return [_materialize(v, now) for v in item]
    return item


def fire_events(state: dict) -> list[str]:
    """Fire every pending event whose trigger is met. Each event fires once.

    Trigger types: {"type": "after_tool", "tool": T, "count": N} (N successful calls of T)
                   {"type": "after_calls", "n": N} (N calls of any kind).
    Effects: {"op": "append", "path": "ap_run.invoices", "item": {...}}
             {"op": "set", "path": "a.b", "value": ...}
    The string "@now" inside an item becomes the simulated time.
    """
    from .state import get_path, set_path, sim_time

    events = state.get("events")
    if not events or not events.get("pending"):
        return []
    fired_ids = []
    still = []
    for ev in events["pending"]:
        if _trigger_met(state, ev.get("trigger", {})):
            now = sim_time(state)
            for eff in ev.get("effects", []):
                op = eff.get("op")
                if op == "append":
                    get_path(state, eff["path"]).append(_materialize(json.loads(json.dumps(eff["item"])), now))
                elif op == "set":
                    set_path(state, eff["path"], _materialize(json.loads(json.dumps(eff["value"])), now))
            done = dict(ev)
            done["fired_at_call"] = int(state.get("calls", 0))
            events.setdefault("fired", []).append(done)
            fired_ids.append(ev.get("id"))
        else:
            still.append(ev)
    events["pending"] = still
    return fired_ids
