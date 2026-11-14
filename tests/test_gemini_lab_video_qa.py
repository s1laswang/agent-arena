"""Offline tests for canary.gemini.video_qa (no key, no network)."""
from types import SimpleNamespace

import pytest

from canary.gemini import video_qa


def test_vo_lines_parses_narrate_format():
    text = "# t\n> VO[01-hook]: One mole.\nnot a line\n> VO[02-ladder]:  Two  \n"
    assert video_qa.vo_lines(text) == [{"id": "01-hook", "text": "One mole."}, {"id": "02-ladder", "text": "Two"}]


def test_prompt_lists_every_line_and_schema_requires_lines():
    p = video_qa.prompt([{"id": "a1", "text": "134 paired episodes"}])
    assert "[a1] 134 paired episodes" in p
    assert video_qa.SCHEMA["required"] == ["lines", "overall"]


def test_wait_active_polls_until_active():
    states = iter(["PROCESSING", "ACTIVE"])

    class Files:
        def get(self, name):
            return SimpleNamespace(name=name, state=SimpleNamespace(name=next(states)))

    f = video_qa.wait_active(SimpleNamespace(files=Files()), SimpleNamespace(name="files/x", state=SimpleNamespace(name="PROCESSING")), poll_s=0)
    assert video_qa._state(f) == "ACTIVE"


def test_wait_active_raises_on_failed():
    with pytest.raises(RuntimeError):
        video_qa.wait_active(SimpleNamespace(files=None), SimpleNamespace(name="files/x", state=SimpleNamespace(name="FAILED")))


def test_dry_run_needs_no_key(tmp_path, capsys):
    s = tmp_path / "v.md"
    s.write_text("> VO[x]: hello\n")
    assert video_qa.main(["--script", str(s), "--dry-run"]) == 0
    assert '"lines": 1' in capsys.readouterr().out
