"""One transcript format shared by SFT export (train.export_sft) and HF eval (train.eval_hf).

Pure Python (no torch). The training data and the eval prompt MUST come from these functions,
so the model is evaluated in exactly the format it was trained on.

Chat layout (OpenAI / Qwen2.5 tool-calling style):
    system    : the Env instruction + a short protocol note
    user      : KICKOFF
    assistant : {"tool_calls": [{"type": "function", "function": {"name", "arguments"}}]}
    tool      : json of the ToolResult the agent saw (truncated to MAX_TOOL_CHARS)
    ... repeated, one tool call per assistant turn.
"""
from __future__ import annotations

import json
import re
from typing import Any

PROTOCOL = (
    "\n\nYou act only through tool calls. Make exactly one tool call per turn, "
    "as JSON: {\"name\": <tool>, \"arguments\": {...}}."
)
KICKOFF = "Begin the investigation. Find the mole and accuse them."
MAX_TOOL_CHARS = 3000


def system_text(instruction: str) -> str:
    return instruction.rstrip() + PROTOCOL


def to_openai_tools(tools_spec: list[dict]) -> list[dict]:
    """Normalise Env.tools_spec() (MCP-style or OpenAI-style) to OpenAI function specs."""
    out = []
    for t in tools_spec:
        if t.get("type") == "function" and "function" in t:
            out.append(t)
            continue
        params = t.get("parameters") or t.get("input_schema") or t.get("inputSchema") \
            or {"type": "object", "properties": {}}
        out.append({"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""), "parameters": params}})
    return out


def _step_get(step: Any, key: str):
    return step[key] if isinstance(step, dict) else getattr(step, key)


def tool_content(result: dict) -> str:
    if result.get("ok", True):
        body: Any = result.get("data", {})
    else:
        body = {"error": result.get("error") or "error"}
    s = json.dumps(body, separators=(",", ":"), sort_keys=True, default=str)
    if len(s) > MAX_TOOL_CHARS:
        s = s[:MAX_TOOL_CHARS] + "...[truncated]"
    return s


def assistant_msg(tool: str, args: dict) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"type": "function", "function": {"name": tool, "arguments": dict(args)}}]}


def render_messages(instruction: str, steps: list) -> list[dict]:
    msgs = [{"role": "system", "content": system_text(instruction)},
            {"role": "user", "content": KICKOFF}]
    for st in steps:
        msgs.append(assistant_msg(_step_get(st, "tool"), _step_get(st, "args")))
        msgs.append({"role": "tool", "name": _step_get(st, "tool"),
                     "content": tool_content(_step_get(st, "result"))})
    return msgs


def render_episode(ep, instruction: str, tools_spec: list[dict]) -> dict:
    """EpisodeResult (dataclass or dict) -> one SFT JSONL record."""
    g = (lambda k: ep[k]) if isinstance(ep, dict) else (lambda k: getattr(ep, k))
    return {
        "tier": g("tier"), "seed": g("seed"), "agent": g("agent"),
        "score": g("score"), "correct": g("correct"), "final_day": g("final_day"),
        "end_reason": g("end_reason"),
        "tools": to_openai_tools(tools_spec),
        "messages": render_messages(instruction, g("steps")),
    }


# ---------- parsing model output back into a tool call ----------

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.S)


def _first_json_obj(s: str) -> dict | None:
    start = s.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = s.find("{", start + 1)
    return None


def parse_tool_call(text: str, tool_names: set[str] | None = None) -> tuple[str, dict] | None:
    """Model text -> (tool, args), or None if no valid call. Accepts <tool_call>{...}</tool_call>,
    bare JSON, {"name", "arguments"} or {"function": {...}}; arguments may be a JSON string."""
    m = _TOOL_CALL_RE.search(text)
    obj = _first_json_obj(m.group(1) if m else text)
    if obj is None:
        return None
    if "function" in obj and isinstance(obj["function"], dict):
        obj = obj["function"]
    name = obj.get("name") or obj.get("tool")
    args = obj.get("arguments", obj.get("args", obj.get("parameters", {})))
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return None
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    if tool_names is not None and name not in tool_names:
        return None
    return name, args
