"""Canary Lab narration (G5): VIDEO.md parsing and placeholder filling, keyless."""
import io
import wave
from pathlib import Path

import pytest

from canary.gemini import narrate

ROOT = Path(__file__).resolve().parents[1]
FX = Path(__file__).parent / "fixtures" / "gemini_lab"
VIDEO = ROOT / "docs" / "gemini" / "VIDEO.md"


def test_video_script_fills_from_fixtures():
    vals = narrate.values(FX / "results", [FX / "ledger"])
    clips = narrate.script(VIDEO, vals)
    ids = [c["id"] for c in clips]
    assert ids[0] == "01-hook" and ids[-1] == "06-close" and len(ids) == len(set(ids)) >= 6
    text = " ".join(c["text"] for c in clips)
    assert "{" not in text and "pending" not in text
    assert 100 < sum(c["est_s"] for c in clips) <= 180  # fits the 3-minute cut


def test_missing_results_stop_unless_allowed(tmp_path):
    vals = narrate.values(tmp_path, [tmp_path])
    with pytest.raises(SystemExit):
        narrate.script(VIDEO, vals)
    assert any("pending" in c["text"] for c in narrate.script(VIDEO, vals, allow_pending=True))


def test_spoken_formats_and_wav(tmp_path):
    assert narrate.say_model("gemini-3.8-flash") == "Gemini 3.8 Flash"
    assert narrate.say_tokens(2_900_000) == "2.9 million" and narrate.say_pct(0.834) == "83 percent"
    assert narrate.say_score(-0.2) == "minus 0.20"
    p = tmp_path / "a.wav"
    assert narrate.write_wav(p, b"\0\0" * 24000, 24000) == pytest.approx(1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(b"\0\0" * 12000)
    assert narrate.write_wav(tmp_path / "b.wav", buf.getvalue(), 0) == pytest.approx(0.5)
