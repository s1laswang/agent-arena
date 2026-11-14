"""Voice-over clips for the Canary video from docs/VIDEO-STORYBOARD.md (ElevenLabs TTS).

    ELEVENLABS_API_KEY=... python scripts/video_vo.py [--only 01-hook,05-replay] [--voice <voice_id>] [--dry-run]
    python scripts/video_vo.py --env-file /path/to/.env      # read ELEVENLABS_API_KEY from a dotenv file

Reads every `> VO[<id>]: <text>` line of the storyboard and writes docs/video/vo/<id>.mp3 plus index.json
(id, voice, words, characters, file). A line that still holds a placeholder (⟨…⟩) is skipped, so the voice track
never says a number that is not committed. The key is read from the environment (or --env-file) and never printed
or written anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "docs/VIDEO-STORYBOARD.md"
OUT = ROOT / "docs/video/vo"
VOICE = "JBFqnCBsd6RMkjVDRZzb"          # ElevenLabs premade "George" (warm British storyteller)
MODEL = "eleven_multilingual_v2"
LINE = re.compile(r"^>\s*VO\[([\w-]+)\]:\s*(.+)$")


def clips(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).strip()) for line in text.splitlines() if (m := LINE.match(line.strip()))]


def key_from(env_file: str | None) -> str:
    if env_file:
        for line in Path(env_file).read_text().splitlines():
            if line.strip().startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    k = os.environ.get("ELEVENLABS_API_KEY", "")
    if not k:
        raise SystemExit("ELEVENLABS_API_KEY is not set (or pass --env-file)")
    return k


def tts(key: str, voice: str, text: str) -> bytes:
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": MODEL,
                         "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="", help="comma-separated clip ids")
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--env-file")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    want = {s for s in a.only.split(",") if s}
    todo = [(i, t) for i, t in clips(BOARD.read_text()) if not want or i in want]
    index = []
    key = None if a.dry_run else key_from(a.env_file)
    OUT.mkdir(parents=True, exist_ok=True)
    for cid, text in todo:
        if "⟨" in text:
            print(f"skip {cid}: placeholder")
            continue
        words = len(text.split())
        print(f"{cid}: {words} words, ~{words / 2.5:.0f} s")
        if a.dry_run:
            continue
        (OUT / f"{cid}.mp3").write_bytes(tts(key, a.voice, text))
        index.append({"id": cid, "voice": a.voice, "model": MODEL, "words": words, "characters": len(text),
                      "file": f"{cid}.mp3", "text": text})
    if index and not a.dry_run:
        old = {e["id"]: e for e in json.loads((OUT / "index.json").read_text())} if (OUT / "index.json").exists() else {}
        old.update({e["id"]: e for e in index})
        (OUT / "index.json").write_text(json.dumps(sorted(old.values(), key=lambda e: e["id"]), indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
