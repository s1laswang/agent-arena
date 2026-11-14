"""Gemini Live sportscaster over a Canary episode replay (stretch demo asset).

    python -m canary.gemini.commentator --episodes <episodes.jsonl> [--seed 9 | --index 0]
        [--model gemini-3.8-live] [--voice Puck] [--max-seconds 60]
        [--out docs/gemini/assets/narration/commentator-demo] [--dry-run]

Turns the episode's steps into one short play-by-play text turn per game day and streams them into a Live API session
(client.aio.live.connect). Gemini answers each turn with spoken commentary; the audio is concatenated into
<out>.wav (24 kHz mono) and the events plus Gemini's own output transcription go to <out>.json.
Each Live turn is logged to the ledger: record(feature="commentator", kind="live", ...). No prompts are logged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

from canary.gemini.ledger import record

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "gemini-3.8-live"
SYSTEM = (
    "You are a sharp, energetic esports commentator calling a live match of 'Canary', a security game. "
    "An AI agent plays head of security at a company with exactly one hidden mole who leaks documents. "
    "Its weapon is the canary trap: it sends different variants of a document to different groups and watches the "
    "leak feed to see which variant surfaces. Every leak costs company value V (starts at 1.0); the agent must accuse "
    "exactly once, and a correct accusation scores the value that is left, so waiting also costs. "
    "Each message gives you one game day of events. Call that day in two or three punchy sentences (at most 28 words): "
    "react to the moves, read the evidence, build suspense. Never invent events, names or numbers that are not in the "
    "message. A drop in the shown value is not news by itself (canaries cost a little, and leaks hurt before "
    "they surface): only call a leak when the message says LEAK FEED. Do not repeat the rules.")


# ------------------------------------------------------------------ episode -> day summaries
def _names(steps) -> dict[str, str]:
    for s in steps:
        if s.get("tool") == "list_employees":
            emps = ((s.get("result") or {}).get("data") or {}).get("employees") or []
            return {e["id"]: e.get("name", e["id"]) for e in emps}
    return {}


def day_events(ep: dict, agent_label: str) -> list[dict]:
    """One dict per day: {day, V, text}. Only what the agent saw or did; no hidden truth until the verdict."""
    steps = ep.get("steps") or []
    names = _names(steps)
    nm = lambda e: f"{names.get(e, e)} ({e})" if e in names else str(e)  # noqa: E731
    days: dict[int, list[str]] = {}
    v_at: dict[int, float] = {}
    seen_leaks: set = set()
    searches: dict[int, list[str]] = {}
    for s in steps:
        d, tool, args = int(s.get("day", 0)), s.get("tool"), s.get("args") or {}
        data = (s.get("result") or {}).get("data") or {}
        ev = days.setdefault(d, [])
        if tool == "plant_canary":
            asg = args.get("assignment") or {}
            groups: dict[str, int] = {}
            for v in asg.values():
                groups[v] = groups.get(v, 0) + 1
            split = ", ".join(f"{n} get variant {k.lstrip('v')}" for k, n in sorted(groups.items()))
            ev.append(f"plants a canary, '{args.get('doc_title', 'a document')}', to {len(asg)} people: {split}.")
        elif tool == "check_leak_feed":
            for it in data.get("items") or []:
                key = (it.get("doc_id"), it.get("variant"))
                if key in seen_leaks:
                    continue
                seen_leaks.add(key)
                if it.get("variant"):
                    ev.append(f"LEAK FEED: the canary '{it.get('title')}' surfaced, variant {it['variant'].lstrip('v')}!")
                else:
                    ev.append(f"LEAK FEED: a real document leaked, '{it.get('title')}' (not a canary, no fingerprint).")
        elif tool == "interview":
            if sum(e.startswith("interviews") for e in ev) >= 2:
                continue  # keep the day short enough to call in a few sentences
            ans = str(data.get("answer", ""))[:140]
            ev.append(f"interviews {nm(args.get('employee'))} about {str(args.get('topic', '')).replace('_', ' ')}: \"{ans}\"")
        elif tool in ("restrict_access", "restrict"):
            ev.append(f"restricts access for {nm(args.get('employee'))}.")
        elif tool == "search_messages":
            q = str(args.get("query", "")).strip()
            if len(q) >= 3:
                searches.setdefault(d, []).append(q)
        elif tool == "read_access_logs":
            n = len(data.get("logs") or [])
            ev.append(f"reads the access logs ({n} entries).")
        elif tool == "advance_day" and data.get("V") is not None:
            v_at[d] = float(data["V"])
        elif tool == "accuse":
            ev.append(f"ACCUSES {nm(args.get('employee'))}! The game is over.")
    out = []
    for d in sorted(days):
        ev = days[d]
        if searches.get(d):
            ev.insert(0, f"searches messages for {', '.join(repr(q) for q in searches[d][:4])}.")
        if not ev:
            continue
        lines = [f"Day {d}. {agent_label}:"] + [f"- {e}" for e in ev]
        if d in v_at:
            lines.append(f"End of day {d}: company value shown is {v_at[d]:.2f}.")
        out.append({"day": d, "V": v_at.get(d), "text": "\n".join(lines),
                    "key": any(e.startswith(("LEAK FEED: the canary", "ACCUSES")) for e in ev)})
    verdict = (f"FINAL WHISTLE. The accusation was {'CORRECT' if ep.get('correct') else 'WRONG'}: "
               f"{nm(ep.get('accused'))} {'was' if ep.get('correct') else 'was not'} the mole. "
               f"Final score {ep.get('score'):+.2f} on day {ep.get('final_day')}. Wrap up the match in two sentences.")
    out.append({"day": None, "V": None, "text": verdict})
    return out


def load_episode(path: Path, seed: int | None, index: int) -> dict:
    eps = [json.loads(line) for line in open(path) if line.strip()]
    if seed is not None:
        eps = [e for e in eps if e.get("seed") == seed]
        if not eps:
            raise SystemExit(f"seed {seed} not in {path}")
        return eps[0]
    return eps[index]


# ------------------------------------------------------------------ Live session
async def commentate(turns: list[dict], model: str, voice: str, max_seconds: float, run_id: str) -> tuple[bytes, list]:
    from google import genai
    from google.genai import types

    from canary.llm.base import load_env
    load_env()
    client = genai.Client(http_options=types.HttpOptions(api_version="v1beta"))
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"], system_instruction=SYSTEM,
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        output_audio_transcription=types.AudioTranscriptionConfig())
    pcm = bytearray()
    log = []
    async with client.aio.live.connect(model=model, config=cfg) as session:
        for turn in turns:
            if turn["day"] is not None and len(pcm) / 2 / 24000 >= max_seconds - 18:
                continue  # keep ~18 s for the last days' leaks and the verdict
            if turn["day"] is not None and not turn.get("key") and len(pcm) / 2 / 24000 >= max_seconds / 3:
                continue  # past the opening, only call days with a leak or the accusation
            t0 = time.time()
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text=turn["text"])]), turn_complete=True)
            said, usage, n0 = [], None, len(pcm)
            async for msg in session.receive():
                sc = msg.server_content
                if msg.usage_metadata is not None:
                    usage = msg.usage_metadata
                if sc is None:
                    continue
                if sc.model_turn:
                    for p in sc.model_turn.parts or []:
                        if p.inline_data and p.inline_data.data:
                            pcm += p.inline_data.data
                if sc.output_transcription and sc.output_transcription.text:
                    said.append(sc.output_transcription.text)
                if sc.turn_complete:
                    break
            secs = (len(pcm) - n0) / 2 / 24000
            record("commentator", model, kind="live", usage=usage, latency_s=time.time() - t0, run_id=run_id,
                   meta={"day": turn["day"], "audio_s": round(secs, 2), "voice": voice})
            log.append({"day": turn["day"], "event_text": turn["text"], "commentary": "".join(said).strip(),
                        "audio_s": round(secs, 2)})
            print(f"day {turn['day']}: {secs:.1f} s audio  | {''.join(said).strip()[:110]}", flush=True)
    return bytes(pcm), log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", required=True, help="episodes.jsonl (canary.eval format)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--agent-label", default="Gemini 4 Carbon")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--voice", default="Puck")
    ap.add_argument("--max-seconds", type=float, default=60.0)
    ap.add_argument("--out", default=str(ROOT / "docs" / "gemini" / "assets" / "narration" / "commentator-demo"))
    ap.add_argument("--dry-run", action="store_true", help="print the day turns, no API call")
    a = ap.parse_args(argv)
    ep = load_episode(Path(a.episodes), a.seed, a.index)
    turns = day_events(ep, a.agent_label)
    if a.dry_run:
        for t in turns:
            print(t["text"], "\n")
        return 0
    run_id = f"commentator-{int(time.time())}"
    pcm, log = asyncio.run(commentate(turns, a.model, a.voice, a.max_seconds, run_id))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out.with_suffix(".wav")), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(pcm)
    meta = {"episode": {"source": str(a.episodes), "seed": ep.get("seed"), "tier": ep.get("tier"),
                        "agent": ep.get("agent"), "score": ep.get("score"), "correct": ep.get("correct")},
            "model": a.model, "voice": a.voice, "seconds": round(len(pcm) / 2 / 24000, 2), "turns": log}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"wrote {out.with_suffix('.wav')} ({meta['seconds']} s) and {out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
