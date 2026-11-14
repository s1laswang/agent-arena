"""Gemini video understanding QA for the demo video: Gemini watches the final cut and checks every narration line
against what is on screen.

    python -m canary.gemini.video_qa --video demo.mp4 --script docs/gemini/VIDEO-2MIN.md
        [--model gemini-3.8-flash] [--out results/gemini/video_qa.json] [--dry-run]

Reads the `> VO[<id>]: <text>` lines of the script (same format as canary.gemini.narrate), uploads the MP4 with the
Files API, waits until it is ACTIVE, then makes ONE generate_content call with the video plus the lines and a
response_json_schema. For each line Gemini returns where it is spoken (start/end seconds), whether the visual on screen
at that moment supports the claim, which numbers are readable on screen, and an issue string ("" if fine).
The call is ledgered: record(feature="video_qa", ...). No prompts or keys are logged.
Runs direct with GEMINI_API_KEY (unset GEMINI_GATEWAY_URL: the gateway relays generate calls, not file uploads).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

VO_RE = re.compile(r"^>\s*VO\[(?P<id>[\w.-]+)\]:\s*(?P<text>.+?)\s*$", re.M)
DEFAULT_MODEL = "gemini-3.8-flash"
SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"},
            "start_s": {"type": "number"},
            "end_s": {"type": "number"},
            "visual_supports_claim": {"type": "boolean"},
            "numbers_on_screen": {"type": "array", "items": {"type": "string"}},
            "issue": {"type": "string"},
        }, "required": ["id", "start_s", "end_s", "visual_supports_claim", "issue"]}},
        "overall": {"type": "string"},
    },
    "required": ["lines", "overall"],
}


def vo_lines(text: str) -> list[dict]:
    return [{"id": m["id"], "text": m["text"]} for m in VO_RE.finditer(text)]


def prompt(lines: list[dict]) -> str:
    body = "\n".join(f"- [{ln['id']}] {ln['text']}" for ln in lines)
    return ("You are the fact-checker for a 2-minute product demo video. The narration lines are below, in order. "
            "Watch the whole video. For every line, give the time range where it is spoken or should be shown, say "
            "whether what is visible on screen at that moment supports the claim (a number in the narration must be "
            "readable on screen or in a chart shown at that moment), list the numbers you can read on screen, and "
            "describe any mismatch in `issue` (empty string if none). Do not invent numbers.\n\nNarration:\n" + body)


def _state(f) -> str:
    s = getattr(f, "state", None)
    return getattr(s, "name", None) or str(s)


def wait_active(client, f, timeout_s: float = 300.0, poll_s: float = 3.0):
    t0 = time.time()
    while _state(f) in ("PROCESSING", "STATE_UNSPECIFIED", "None"):
        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"video still {_state(f)} after {timeout_s:.0f}s")
        time.sleep(poll_s)
        f = client.files.get(name=f.name)
    if _state(f) != "ACTIVE":
        raise RuntimeError(f"video upload ended in state {_state(f)}")
    return f


def run(video: Path, lines: list[dict], model: str = DEFAULT_MODEL, run_id: str = "") -> dict:
    from google.genai import types

    from canary.gemini.ledger import record
    from canary.gemini.sdk import genai_client
    client = genai_client()
    f = wait_active(client, client.files.upload(file=str(video)))
    t0 = time.time()
    try:
        r = client.models.generate_content(
            model=model, contents=[f, prompt(lines)],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=SCHEMA,
                                               thinking_config=types.ThinkingConfig(thinking_level="LOW")))
    except Exception as e:  # noqa: BLE001
        record("video_qa", model, usage=None, latency_s=time.time() - t0, ok=False,
               error=f"{type(e).__name__}: {e}", run_id=run_id, meta={"op": "video_qa"})
        raise
    record("video_qa", model, usage=getattr(r, "usage_metadata", None), latency_s=time.time() - t0, run_id=run_id,
           meta={"op": "video_qa", "lines": len(lines), "video_bytes": video.stat().st_size})
    try:
        client.files.delete(name=f.name)
    except Exception:  # noqa: BLE001  best effort; files expire after 48 h anyway
        pass
    return json.loads(r.text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--video", type=Path)
    ap.add_argument("--script", type=Path, default=Path("docs/gemini/VIDEO-2MIN.md"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=Path("results/gemini/video_qa.json"))
    ap.add_argument("--dry-run", action="store_true", help="print the parsed lines and the prompt; no API call")
    a = ap.parse_args(argv)
    lines = vo_lines(a.script.read_text())
    if not lines:
        print(f"no VO[...] lines in {a.script}", file=sys.stderr)
        return 2
    if a.dry_run:
        print(json.dumps({"lines": len(lines), "ids": [ln["id"] for ln in lines]}))
        return 0
    if a.video is None or not a.video.exists():
        print("--video <file.mp4> is required (and must exist) unless --dry-run", file=sys.stderr)
        return 2
    out = run(a.video, lines, a.model)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2) + "\n")
    bad = [ln for ln in out.get("lines", []) if not ln.get("visual_supports_claim") or ln.get("issue")]
    print(json.dumps({"lines": len(out.get("lines", [])), "flagged": len(bad), "out": str(a.out)}))
    for ln in bad:
        print(f"  FLAG {ln.get('id')} @{ln.get('start_s')}s: {ln.get('issue')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
