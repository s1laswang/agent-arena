"""Shared helpers for training/: chat format, prompt rendering and a tolerant tool-call parser.

Stdlib only. The same rendering is used to train (train_lora.py) and to test the model
(eval_small_model.py), so the model sees the same text format in both.

Chat format (OpenAI / Hugging Face style), one dataset row:
  {"messages": [
     {"role": "system", "content": <instruction>},
     {"role": "user", "content": FIRST_MESSAGE},
     {"role": "assistant", "content": null,
      "tool_calls": [{"id": "call_0", "type": "function",
                      "function": {"name": "list_vendors", "arguments": "{}"}}]},
     {"role": "tool", "tool_call_id": "call_0", "content": "{\"ok\":true,...}"},
     ...
     {"role": "assistant", "content": "Done. ..."}],
   "tools": [{"type": "function", "function": {"name", "description", "parameters"}}], ...}
Tool results are the dispatch dict {"ok", "result", "error"} as compact JSON, exactly what
the Gemini agent and the MCP server hand back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIRST_MESSAGE = ("Start the task now. Use the tools to do the work. When you are completely "
                 "finished, reply with a short summary and no tool call.")

PLAIN_PROTOCOL = """# How to call tools
To call a tool, reply with one block like this and nothing else:
<tool_call>
{"name": "TOOL_NAME", "arguments": {"param": "value"}}
</tool_call>
You will get the result back as a message that starts with [tool result].
Call one tool at a time. When you are completely finished, reply with a short summary and no tool call."""

NUDGE = ("Your last reply looked like a tool call, but it could not be read. Reply with one "
         "<tool_call>{\"name\": ..., \"arguments\": {...}}</tool_call> block, or with a short summary "
         "and no tool call if you are finished.")


def dtype_kwarg(dtype) -> dict:
    """{"dtype": x} for transformers >= 4.56, else {"torch_dtype": x} (lazy import)."""
    import transformers
    from packaging.version import Version
    return {"dtype" if Version(transformers.__version__) >= Version("4.56") else "torch_dtype": dtype}


def model_short_name(model: str) -> str:
    """'Qwen/Qwen3-4B-Instruct-2507' or a local folder (/ or \\ separators) -> the last path part."""
    parts = [p for p in re.split(r"[\\/]+", str(model)) if p]
    return parts[-1] if parts else "model"


def dumps_compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def openai_tools(specs: list) -> list:
    """pinbox tool specs -> OpenAI/HF `tools` list."""
    return [{"type": "function", "function": {"name": s["name"], "description": s.get("description", ""),
                                              "parameters": s.get("parameters") or {"type": "object",
                                                                                    "properties": {}}}}
            for s in specs]


def tool_content(out: dict) -> str:
    """The tool message text for one dispatch dict."""
    return dumps_compact({"ok": bool(out.get("ok")), "result": out.get("result"), "error": out.get("error")})


def assistant_call(call_id: str, name: str, args: dict, content=None) -> dict:
    return {"role": "assistant", "content": content,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": dumps_compact(args or {})}}]}


def tool_message(call_id: str, name: str, out: dict) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": tool_content(out)}


def final_summary(trajectory: list, write_names) -> str:
    """A short, factual closing message built from the successful write calls."""
    acts = []
    for rec in trajectory:
        if rec.get("ok") and rec.get("tool") in write_names:
            args = rec.get("args") or {}
            short = ", ".join(f"{k}={v}" for k, v in args.items() if k not in ("body", "message"))
            acts.append(f"{rec['tool']}({short})")
    if not acts:
        return "Done. I checked everything and made no changes."
    return "Done. Actions taken: " + "; ".join(acts) + "."


def trajectory_to_messages(instruction: str, trajectory: list, write_names, final_text: str | None = None) -> list:
    """A pinbox trajectory (list of {"i","tool","args","ok","result"|"error"}) -> chat messages."""
    msgs = [{"role": "system", "content": instruction}, {"role": "user", "content": FIRST_MESSAGE}]
    for k, rec in enumerate(trajectory):
        cid = f"call_{k}"
        args = rec.get("args") if isinstance(rec.get("args"), dict) else {}
        msgs.append(assistant_call(cid, str(rec.get("tool")), args))
        out = {"ok": rec.get("ok"), "result": rec.get("result"), "error": rec.get("error")}
        msgs.append(tool_message(cid, str(rec.get("tool")), out))
    msgs.append({"role": "assistant", "content": final_text or final_summary(trajectory, write_names)})
    return msgs


# ---------------------------------------------------------------- validation

def validate_row(row: dict) -> list:
    """Problems with one dataset row (empty list = fine)."""
    errs = []
    msgs = row.get("messages")
    tools = row.get("tools")
    if not isinstance(msgs, list) or len(msgs) < 3:
        return ["messages missing or too short"]
    if not isinstance(tools, list) or not tools:
        errs.append("tools missing")
    names = {t.get("function", {}).get("name") for t in tools or []}
    if msgs[0].get("role") != "system" or not msgs[0].get("content"):
        errs.append("first message must be a non-empty system message")
    if msgs[1].get("role") != "user":
        errs.append("second message must be the user message")
    open_ids: list = []
    for j, m in enumerate(msgs[2:], start=2):
        role = m.get("role")
        if role == "assistant":
            if open_ids:
                errs.append(f"message {j}: assistant before all tool results came back")
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if fn.get("name") not in names:
                    errs.append(f"message {j}: tool {fn.get('name')!r} not in tools")
                try:
                    if not isinstance(json.loads(fn.get("arguments", "")), dict):
                        errs.append(f"message {j}: arguments is not a JSON object")
                except (TypeError, ValueError):
                    errs.append(f"message {j}: arguments is not JSON")
                open_ids.append(tc.get("id"))
        elif role == "tool":
            if not open_ids or m.get("tool_call_id") != open_ids[0]:
                errs.append(f"message {j}: tool result does not answer the next open call")
            else:
                open_ids.pop(0)
            try:
                json.loads(m.get("content", ""))
            except (TypeError, ValueError):
                errs.append(f"message {j}: tool content is not JSON")
        else:
            errs.append(f"message {j}: unexpected role {role!r}")
    last = msgs[-1]
    if last.get("role") != "assistant" or last.get("tool_calls") or not last.get("content"):
        errs.append("last message must be a plain assistant summary")
    return errs


# ---------------------------------------------------------------- rendering

def to_hf_messages(messages: list) -> list:
    """OpenAI rows -> what HF chat templates expect (arguments as dicts, no None content)."""
    out = []
    for m in messages:
        m2 = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                calls.append({"id": tc.get("id"), "type": "function",
                              "function": {"name": fn.get("name"), "arguments": args or {}}})
            m2["tool_calls"] = calls
        if m["role"] == "tool":
            m2["tool_call_id"] = m.get("tool_call_id")
            if m.get("name"):
                m2["name"] = m["name"]
        out.append(m2)
    return out


def call_block(name: str, args) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return "<tool_call>\n" + dumps_compact({"name": name, "arguments": args or {}}) + "\n</tool_call>"


def to_plain_messages(messages: list, tools: list) -> list:
    """For chat templates without tool support: tools go in the system text, calls and results
    become plain text turns."""
    out = []
    tool_lines = "\n".join(dumps_compact(t.get("function", t)) for t in tools or [])
    for m in messages:
        role = m["role"]
        if role == "system":
            out.append({"role": "system",
                        "content": (m.get("content") or "") + "\n\n# Tools\n" + tool_lines + "\n\n" + PLAIN_PROTOCOL})
        elif role == "assistant":
            parts = [m["content"]] if m.get("content") else []
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                parts.append(call_block(fn.get("name"), fn.get("arguments")))
            out.append({"role": "assistant", "content": "\n".join(parts)})
        elif role == "tool":
            text = f"[tool result] {m.get('name') or ''}\n{m.get('content') or ''}"
            if out and out[-1]["role"] == "user" and out[-1]["content"].startswith("[tool result]"):
                out[-1]["content"] += "\n\n" + text
            else:
                out.append({"role": "user", "content": text})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _simple_template(messages: list, add_generation_prompt: bool) -> str:
    """A fallback text format when there is no tokenizer or no chat template."""
    text = "".join(f"<|{m['role']}|>\n{m['content']}\n<|end|>\n" for m in messages)
    return text + ("<|assistant|>\n" if add_generation_prompt else "")


def choose_protocol(tokenizer, protocol: str = "auto") -> str:
    """'native' = the model's own chat template with tools; 'plain' = tools as text (works anywhere)."""
    if protocol in ("native", "plain"):
        return protocol
    tmpl = getattr(tokenizer, "chat_template", None) if tokenizer is not None else None
    if isinstance(tmpl, dict):
        tmpl = " ".join(tmpl.values())
    return "native" if isinstance(tmpl, str) and "tool" in tmpl else "plain"


def render_text(tokenizer, messages: list, tools: list, protocol: str = "auto",
                add_generation_prompt: bool = False) -> str:
    """Render a conversation to one prompt string (same function for training and for eval)."""
    proto = choose_protocol(tokenizer, protocol)
    if proto == "native":
        return tokenizer.apply_chat_template(to_hf_messages(messages), tools=tools, tokenize=False,
                                             add_generation_prompt=add_generation_prompt, enable_thinking=False)
    plain = to_plain_messages(messages, tools)
    if tokenizer is not None and getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(plain, tokenize=False, add_generation_prompt=add_generation_prompt,
                                             enable_thinking=False)
    return _simple_template(plain, add_generation_prompt)


def assistant_char_spans(tokenizer, messages: list, tools: list, protocol: str = "auto"):
    """(full_text, [(start, end), ...]) where each span is the text of one assistant turn.

    Found by rendering the conversation prefix by prefix. Used for assistant-only loss.
    """
    full = render_text(tokenizer, messages, tools, protocol)
    spans = []
    for j, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        before_gen = render_text(tokenizer, messages[:j], tools, protocol, add_generation_prompt=True)
        upto = render_text(tokenizer, messages[: j + 1], tools, protocol)
        if upto.startswith(before_gen):
            start = len(before_gen)
        else:   # template adds something only to the generation prompt (e.g. an empty think block)
            before = render_text(tokenizer, messages[:j], tools, protocol)
            if not upto.startswith(before):
                return full, None
            start = len(before)
        if not full.startswith(upto):
            return full, None
        spans.append((start, len(upto)))
    return full, spans


# ---------------------------------------------------------------- tolerant parser

_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S)
_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.S)
_FENCE_RE = re.compile(r"```(?:json|tool_call|tool)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _close_brackets(text: str) -> str:
    """Add the closing brackets a JSON value is missing. A value cut off inside a string is
    left alone (it was truncated, and a half IBAN must never become a call)."""
    stack, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return text if in_str else text + "".join(reversed(stack))


def _loads_loose(text: str):
    text = text.strip()
    if not text:
        return None
    for attempt in range(4):
        try:
            return json.loads(text)
        except ValueError:
            pass
        if attempt == 0:
            text = (text.replace("“", '"').replace("”", '"').replace("‘", "'")
                    .replace("’", "'"))
            text = _TRAILING_COMMA_RE.sub(r"\1", text)
        elif attempt == 1:
            text = re.sub(r"\bTrue\b", "true", text)
            text = re.sub(r"\bFalse\b", "false", text)
            text = re.sub(r"\bNone\b", "null", text)
        elif attempt == 2 and text.startswith("{"):
            text = _TRAILING_COMMA_RE.sub(r"\1", _close_brackets(text.rstrip().rstrip(",")))
    try:   # first complete JSON value at the start, ignore trailing junk
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj
    except ValueError:
        return None


def _as_call(obj):
    """A parsed JSON value -> (name, args) or None."""
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("function"), dict):        # OpenAI style {"function": {"name", "arguments"}}
        obj = obj["function"]
    name = obj.get("name") or obj.get("tool") or obj.get("tool_name") or obj.get("function")
    if not isinstance(name, str) or not name.strip():
        return None
    args = None
    for key in ("arguments", "args", "parameters", "input"):
        if key in obj:
            args = obj[key]
            break
    if isinstance(args, str):
        args = _loads_loose(args) if args.strip() else {}
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None
    return name.strip(), args


def _json_objects(text: str):
    """Every top-level {...} JSON object found anywhere in the text."""
    dec = json.JSONDecoder()
    i = 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        yield obj
        i = end


def strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text or "")


def parse_tool_calls(text: str) -> list:
    """Find tool calls in model text. Returns [(name, args_dict), ...] (empty = no call).

    Accepts <tool_call>{...}</tool_call> blocks (also unclosed), ```json fences and bare JSON
    objects; keys name/tool/function and arguments/args/parameters; arguments as an object or
    a JSON string; smart quotes, trailing commas and Python True/False/None.
    """
    text = strip_thinking(text)
    calls = []
    tagged = _TAG_RE.findall(text)
    if tagged:
        for chunk in tagged:
            c = _as_call(_loads_loose(chunk))
            if c:
                calls.append(c)
        return calls
    for chunk in _FENCE_RE.findall(text):
        c = _as_call(_loads_loose(chunk))
        if c:
            calls.append(c)
    if calls:
        return calls
    for obj in _json_objects(text):
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            c = _as_call(it)
            if c:
                calls.append(c)
    return calls


def looks_like_call(text: str) -> bool:
    """True if the text seems to try a tool call (used to nudge after a parse failure)."""
    t = strip_thinking(text)
    return "<tool_call>" in t or bool(re.search(r'"(name|tool)"\s*:', t))


def prose_before_calls(text: str) -> str:
    """Any plain text the model wrote before its first tool call (kept in the history)."""
    t = strip_thinking(text)
    cut = len(t)
    for marker in ("<tool_call>", "```", "{"):
        k = t.find(marker)
        if k >= 0:
            cut = min(cut, k)
    return t[:cut].strip()
