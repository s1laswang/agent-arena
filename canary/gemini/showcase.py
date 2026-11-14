"""A tiny, recorded Gemini showcase used by `make lab-replay` (keyless reproduction through the gateway).

    python -m canary.gemini.showcase --write results/gemini/replay/showcase.json   # live/record run
    python -m canary.gemini.showcase --check results/gemini/replay/showcase.json   # replay run: must match

Exercises the paths the lab uses: function calling with thought-signature replay (2 turns through
lab_client), structured JSON output, streaming generate_content, and embeddings (raw SDK + ledger.record).
Every call goes through canary.gemini.sdk, so with GEMINI_GATEWAY_URL set it hits the gateway.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

MODEL = "gemini-3.1-flash-lite"
EMBED_MODEL = "gemini-embedding-2"
SYSTEM = ("You are the head of security at a company with a mole. You plant canary documents: each suspect gets "
          "a slightly different variant, and when a variant leaks you know who received it. Use the tools.")
TOOLS = [{"name": "check_leak", "description": "Return which suspect received a given canary document variant.",
          "parameters": {"type": "object", "properties": {"variant": {"type": "string"}}, "required": ["variant"]}}]
VARIANTS = {"B": "Dana"}
VERDICT_SCHEMA = {"type": "object", "properties": {"suspect": {"type": "string"},
                                                   "confidence": {"type": "number"}},
                  "required": ["suspect", "confidence"]}


def run() -> dict:
    from google.genai import types

    from .ledger import lab_client, record
    from .sdk import genai_client
    out: dict = {"model": MODEL, "steps": []}

    # 1) function calling, two turns (the model's Content is replayed verbatim with thought signatures)
    c = lab_client(f"gemini:{MODEL}", feature="showcase", thinking_level="low")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "The canary variant 'B' just appeared on a leak forum. "
                                        "Call check_leak for it, then name the suspect in one sentence."}]
    r1 = c.chat(msgs, tools=TOOLS)
    calls = [{"name": t.name, "args": t.args} for t in r1.tool_calls]
    out["steps"].append({"step": "function_call", "tool_calls": calls})
    msgs.append({"role": "assistant", "content": r1.text, "provider_items": getattr(r1, "provider_items", None),
                 "tool_calls": [{"id": t.id, "name": t.name, "args": t.args} for t in r1.tool_calls]})
    for t in r1.tool_calls:
        v = str(t.args.get("variant", "")).strip("'\" ").upper()
        msgs.append({"role": "tool", "tool_call_id": t.id, "name": t.name,
                     "content": json.dumps({"variant": v, "recipient": VARIANTS.get(v, "unknown")})})
    r2 = c.chat(msgs, tools=TOOLS)
    out["steps"].append({"step": "function_response", "text": r2.text.strip(),
                         "tool_calls": [{"name": t.name, "args": t.args} for t in r2.tool_calls]})

    # 2) structured output
    r3 = c.chat([{"role": "user", "content": "Variant B leaked and only Dana received it. "
                                             "Give the verdict as JSON."}], response_schema=VERDICT_SCHEMA)
    out["steps"].append({"step": "structured_output", "json": json.loads(r3.text)})

    sdk = genai_client()
    # 3) streaming generate_content (raw SDK: ledgered by hand)
    t0 = time.time()
    chunks, um = [], None
    for ch in sdk.models.generate_content_stream(
            model=MODEL, contents="In exactly five words: what is a canary trap?",
            config=types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level="LOW"))):
        chunks.append(ch.text or "")
        um = ch.usage_metadata or um
    record("showcase", MODEL, kind="generate", usage=um, latency_s=time.time() - t0, meta={"stream": True})
    out["steps"].append({"step": "stream", "chunks": len(chunks), "text": "".join(chunks).strip()})

    # 4) embeddings
    t0 = time.time()
    vecs = []
    for text in ("the mole leaked variant B", "Dana leaked the canary document"):
        e = sdk.models.embed_content(model=EMBED_MODEL, contents=text,
                                     config=types.EmbedContentConfig(output_dimensionality=256))
        vecs.append(e.embeddings[0].values)
    record("showcase", EMBED_MODEL, kind="embed", latency_s=time.time() - t0, tokens={"in": 12, "out": 0})
    a, b = vecs
    cos = sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
    out["steps"].append({"step": "embed", "dim": len(a), "cosine": round(cos, 6)})
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.showcase")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", type=Path)
    g.add_argument("--check", type=Path)
    a = p.parse_args(argv)
    got = run()
    print(json.dumps(got, indent=1))
    if a.write:
        a.write.parent.mkdir(parents=True, exist_ok=True)
        a.write.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
        print(f"showcase: wrote {a.write}")
        return 0
    want = json.loads(a.check.read_text())
    if json.loads(json.dumps(got, sort_keys=True)) != want:
        print("showcase: REPLAY MISMATCH against", a.check, file=sys.stderr)
        return 1
    print(f"showcase: REPLAY OK, {len(got['steps'])} steps reproduced keyless from the gateway cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
