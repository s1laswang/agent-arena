import glob
import json
import os
import sys
from pathlib import Path

import pytest

from agents import gemini
from scripts import gemini_seat as gs

ROOT = Path(__file__).resolve().parent.parent
import subprocess
TRACKED = [str(ROOT / x) for x in subprocess.run(["git", "ls-files", "results/frontier"], cwd=ROOT, capture_output=True, text=True).stdout.split() if x.endswith(".json") and "-s" in x and "-t" in x and ".state." not in x]


def test_abort_still_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    seq = iter([{"text": "", "tool_calls": [{"name": "read_chat", "args": {}}]}] * 10)
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: next(seq))
    row, p = gs.run_seat("gemini", "m", seed=1000, max_calls=3, com="t", base=tmp_path)
    assert row["aborted"] == "max_calls" and row["calls"] == 3 and row["scores"]["reward"] == 0
    assert json.loads(p.read_text())["model"] == "m"


@pytest.mark.parametrize("f", TRACKED or [None])
def test_replay_byte_identical(f, tmp_path, monkeypatch):
    if f is None or ".state." in f:
        pytest.skip("no committed run")
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    src = Path(f)
    model, com, name = src.parent.parent.name, src.parent.name, src.stem
    seat, rest = name.rsplit("-s", 1)
    seed, trial = rest.split("-t")
    import shutil
    shutil.copytree(src.parent, tmp_path / model / com)
    (tmp_path / model / com / src.name).unlink()
    pb = json.loads(src.read_text()).get("prompt_budget", 60)
    row, p = gs.run_seat("gemini", model, seat, int(seed), trial=int(trial), com=com, base=tmp_path, prompt_budget=pb)
    assert p.read_bytes() == src.read_bytes()
