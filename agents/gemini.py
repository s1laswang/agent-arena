import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"
_usage = {"calls": 0, "cache_hits": 0, "in_tokens": 0, "out_tokens": 0, "retries": 0}
_client = None


class GeminiUnavailable(Exception):
    pass


def _load_env():
    for p in (Path.home() / "arena-agents" / ".env", ROOT / ".env"):
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_env()


def model_for(role):
    return os.environ.get("SLEEPER_MODEL_" + role.upper()) or DEFAULT_MODEL


TEMPS = {"staff": 0.7, "reference": 0.7, "sleeper": 0.9}


def temp_for(role):
    return float(os.environ.get("SLEEPER_TEMP_" + role.upper()) or TEMPS.get(role, 0))


def enabled():
    return bool(os.environ.get("GEMINI_API_KEY"))


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


def _hashed(messages):
    out = []
    for m in messages:
        if m.get("images"):
            m = {**m, "images": [hashlib.sha256(Path(i).read_bytes()).hexdigest() for i in m["images"]]}
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
            parts.append(types.Part.from_function_call(name=c["name"], args=c.get("args") or {}))
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

        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _generate(model, system, messages, tools, temperature, seed):
    from google.genai import errors, types

    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        temperature=temperature,
        seed=seed,
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
                calls.append({"name": p.function_call.name, "args": dict(p.function_call.args or {})})
            elif getattr(p, "text", None):
                text += p.text
    return {"text": text, "tool_calls": calls}


def chat(model, system, messages, tools=None, temperature=0, seed=None):
    key = cache_key(model, system, messages, tools, temperature, seed)
    path = CACHE / (key + ".json")
    if path.is_file():
        _usage["cache_hits"] += 1
        return json.loads(path.read_text())
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
    out = _parse(resp)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp%d" % os.getpid())
    tmp.write_text(json.dumps(out))
    tmp.replace(path)
    return out


def run_tool_loop(model, system, view_text, tools, call, max_steps=60, temperature=None, seed=None, role="staff", log=None):
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
            results.append({"name": c["name"], "result": call(c["name"], c["args"])})
            if log:
                log({"role": "tool", **results[-1]})
        messages.append({"role": "user", "tool_results": results})
        if done:
            break
    return {"text": text, "messages": messages}
