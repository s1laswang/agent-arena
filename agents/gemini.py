import base64
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("SLEEPER_CACHE_DIR") or ROOT / ".cache" / "gemini")
_used = set()
if os.environ.get("SLEEPER_USED_FILE"):
    import atexit

    atexit.register(lambda: Path(os.environ["SLEEPER_USED_FILE"]).write_text("\n".join(sorted(_used))))
DEFAULT_MODEL = "gemini-2.5-flash"
_usage = {"calls": 0, "cache_hits": 0, "in_tokens": 0, "out_tokens": 0, "retries": 0}
_client = None


class GeminiUnavailable(Exception):
    pass


class OfflineCacheMiss(Exception):
    pass


def load_env():
    for p in (Path.home() / "arena-agents" / ".env", ROOT / ".env"):
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def enable_live():
    load_env()
    os.environ["SLEEPER_LIVE"] = "1"
    return enabled()


ARENA_ROLE = {"staff": "DEFENDER", "defender": "DEFENDER", "sleeper": "ATTACKER", "attacker": "ATTACKER", "reference": "REFERENCE", "procedure": "REFERENCE"}


def model_for(role):
    arena = ARENA_ROLE.get(role)
    return os.environ.get("SLEEPER_MODEL_" + role.upper()) or (arena and os.environ.get("ARENA_MODEL_" + arena)) or DEFAULT_MODEL


TEMPS = {"staff": 0.7, "reference": 0.7, "sleeper": 0.9}


def temp_for(role):
    return float(os.environ.get("SLEEPER_TEMP_" + role.upper()) or TEMPS.get(role, 0))


def enabled():
    return (os.environ.get("SLEEPER_LIVE") == "1" and bool(os.environ.get("GEMINI_API_KEY"))) or os.environ.get("SLEEPER_OFFLINE") == "1"


def usage():
    u = dict(_usage)
    pin = float(os.environ.get("SLEEPER_PRICE_IN_PER_M", 0) or 0)
    pout = float(os.environ.get("SLEEPER_PRICE_OUT_PER_M", 0) or 0)
    u["est_calls_per_day"] = estimate_calls(
        int(os.environ.get("SLEEPER_SEATS", 8)), int(os.environ.get("SLEEPER_ROUNDS", 3)), int(os.environ.get("SLEEPER_STEPS", 10))
    )
    u["cost"] = (u["in_tokens"] * pin + u["out_tokens"] * pout) / 1e6
    return u


def estimate_calls(seats=8, rounds=3, steps=10):
    return seats * rounds * steps


def reset_usage():
    _used.clear()
    for k in _usage:
        _usage[k] = 0


def to_declarations(tools):
    from google.genai import types

    return [
        types.FunctionDeclaration(
            name=t["name"],
            description=t.get("description", ""),
            parameters_json_schema=t.get("parameters") or {"type": "object", "properties": {}},
        )
        for t in tools or []
    ]


def _mime(path):
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(Path(path).suffix.lower(), "image/png")


def _fhash(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else str(path)


def _hashed(messages):
    out = []
    for m in messages:
        if m.get("images"):
            m = {**m, "images": [_fhash(i) for i in m["images"]]}
        if m.get("tool_results"):
            rs = []
            for r in m["tool_results"]:
                if isinstance(r.get("result"), dict) and r["result"].get("image"):
                    r = {**r, "result": {**r["result"], "image": _fhash(r["result"]["image"])}}
                rs.append(r)
            m = {**m, "tool_results": rs}
        out.append(m)
    return out


def _contents(messages):
    from google.genai import types

    out = []
    for m in messages:
        parts = []
        if m.get("text"):
            parts.append(types.Part(text=m["text"]))
        for img in m.get("images") or []:
            parts.append(types.Part.from_bytes(data=Path(img).read_bytes(), mime_type=_mime(img)))
        for c in m.get("tool_calls") or []:
            sig = base64.b64decode(c["sig"]) if c.get("sig") else b"skip_thought_signature_validator"
            parts.append(types.Part(function_call=types.FunctionCall(name=c["name"], args=c.get("args") or {}), thought_signature=sig))
        for r in m.get("tool_results") or []:
            parts.append(types.Part.from_function_response(name=r["name"], response={"result": r["result"]}))
        role = "model" if m["role"] in ("assistant", "model") else "user"
        out.append(types.Content(role=role, parts=parts))
    return out


def cache_key(model, system, messages, tools, temperature, seed):
    blob = json.dumps([model, system, _hashed(messages), tools, temperature, seed], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"timeout": 300000})
    return _client


def _generate(model, system, messages, tools, temperature, seed):
    from google.genai import errors, types

    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        temperature=temperature,
        seed=None if seed is None else seed % 2147483647,
        tools=[types.Tool(function_declarations=to_declarations(tools))] if tools else None,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    delay = 1.0
    for attempt in range(6):
        try:
            return _get_client().models.generate_content(model=model, contents=_contents(messages), config=cfg)
        except errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            if (code == 429 or code >= 500) and attempt < 5:
                _usage["retries"] += 1
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise


def _parse(resp):
    text, calls = "", []
    for cand in (resp.candidates or [])[:1]:
        for p in (cand.content.parts if cand.content and cand.content.parts else []):
            if getattr(p, "function_call", None):
                sig = getattr(p, "thought_signature", None)
                calls.append({"name": p.function_call.name, "args": dict(p.function_call.args or {}), **({"sig": base64.b64encode(sig).decode()} if sig else {})})
            elif getattr(p, "text", None):
                text += p.text
    return {"text": text, "tool_calls": calls}


def chat(model, system, messages, tools=None, temperature=0, seed=None):
    key = cache_key(model, system, messages, tools, temperature, seed)
    path = CACHE / (key + ".json")
    _used.add(key)
    if path.is_file():
        _usage["cache_hits"] += 1
        return json.loads(path.read_text())
    if os.environ.get("SLEEPER_OFFLINE") == "1":
        raise OfflineCacheMiss("SLEEPER_OFFLINE=1 and no cached response for this prompt")
    if not enabled():
        raise GeminiUnavailable("no GEMINI_API_KEY and no cached response")
    cap = int(os.environ.get("SLEEPER_MAX_CALLS", 0) or 0)
    if cap and _usage["calls"] >= cap:
        raise GeminiUnavailable("SLEEPER_MAX_CALLS reached")
    resp = _generate(model, system, messages, tools, temperature, seed)
    _usage["calls"] += 1
    um = getattr(resp, "usage_metadata", None)
    if um:
        _usage["in_tokens"] += um.prompt_token_count or 0
        _usage["out_tokens"] += um.candidates_token_count or 0
        CACHE.mkdir(parents=True, exist_ok=True)
        with open(CACHE / "usage.jsonl", "a") as f:
            f.write(json.dumps({"model": model, "in": um.prompt_token_count or 0, "out": um.candidates_token_count or 0}) + "\n")
    out = _parse(resp)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(out))
    tmp.replace(path)
    return out


KEEP_LAST = 10
LIST_CAP = 25
TEXT_CAP = 600
DOC_CAP = 2000


def compact_result(name, result):
    if not isinstance(result, dict) or os.environ.get("SLEEPER_COMPACT") == "0":
        return result
    r = dict(result)
    if isinstance(r.get("tickets"), list):
        open_ = [t for t in r["tickets"] if not (isinstance(t, dict) and t.get("closed"))]
        if len(open_) < len(r["tickets"]):
            r["closed_ticket_count"] = len(r["tickets"]) - len(open_)
        r["tickets"] = open_
    if isinstance(r.get("payments"), list) and len(r["payments"]) > LIST_CAP:
        pend = [p for p in r["payments"] if isinstance(p, dict) and p.get("status") == "pending"]
        rest = [p for p in r["payments"] if p not in pend]
        keep = max(LIST_CAP - len(pend), 0)
        r["omitted_payments"] = len(rest) - keep
        r["payments"] = (rest[len(rest) - keep:] if keep else []) + pend
    for k, v in list(r.items()):
        if isinstance(v, list) and len(v) > LIST_CAP and k != "payments":
            r["omitted_" + k] = len(v) - LIST_CAP
            r[k] = v[-LIST_CAP:]
    if isinstance(r.get("messages"), list):
        r["messages"] = [{**m, "body": str(m.get("body", ""))[:TEXT_CAP]} if isinstance(m, dict) else m for m in r["messages"]]
    if isinstance(r.get("doc"), dict) and len(str(r["doc"].get("body", ""))) > DOC_CAP:
        r["doc"] = {**r["doc"], "body": str(r["doc"]["body"])[:DOC_CAP], "body_truncated": True}
    return r


def _elide(messages):
    idx = [i for i, m in enumerate(messages) if m.get("tool_results")]
    for i in idx[:-KEEP_LAST]:
        rs = []
        for x in messages[i]["tool_results"]:
            n = len(json.dumps(x["result"], default=str))
            rs.append({**x, "result": {"elided": "%s result, %d chars" % (x["name"], n)}} if n > TEXT_CAP else x)
        messages[i] = {**messages[i], "tool_results": rs}


def run_tool_loop(model, system, view_text, tools, call, max_steps=60, temperature=None, seed=None, role="staff", log=None, guard=None):
    if temperature is None:
        temperature = temp_for(role)
    messages = [{"role": "user", "text": view_text}]
    text = ""
    for _ in range(max_steps):
        r = chat(model, system, messages, tools, temperature, seed)
        if log:
            log({"role": "model", **r})
        text = r["text"] or text
        if not r["tool_calls"]:
            break
        messages.append({"role": "assistant", "text": r["text"], "tool_calls": r["tool_calls"]})
        results = []
        done = False
        for c in r["tool_calls"]:
            if c["name"] == "end_turn":
                done = True
            blocked = guard(c["name"], c["args"]) if guard else None
            results.append({"name": c["name"], "result": blocked if blocked is not None else call(c["name"], c["args"])})
            if log:
                log({"role": "tool", **results[-1]})
        imgs = [x["result"]["image"] for x in results if isinstance(x["result"], dict) and x["result"].get("image")]
        messages.append({"role": "user", "tool_results": [{**x, "result": compact_result(x["name"], x["result"])} for x in results], **({"images": imgs} if imgs else {})})
        _elide(messages)
        if done:
            break
    return {"text": text, "messages": messages}
