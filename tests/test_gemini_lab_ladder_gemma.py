"""Gemini Ladder: the open-weight Gemma section (hosted Gemma via the Gemini API), keyless with the stub backend."""
import json

from canary.gemini import ladder, ladder_report
from canary.gemini.ledger import LedgeredClient
from canary.llm.stub import StubClient


def _factory(cell, run_id, meta):
    script = [{"tool_calls": [{"name": "status", "args": {}}]},
              {"tool_calls": [{"name": "accuse", "args": {"employee": "e01"}}]}]
    return LedgeredClient(StubClient(script=script), feature="ladder", run_id=run_id, meta=meta)


def _grid(out, models, level, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(out / "_ledger" / "x.jsonl"))
    ladder.run_grid(out, ladder.expand_grid(models, [level], ["hard"], [0, 1]), concurrency=2,
                    client_factory=_factory, log=lambda m: None)


def test_gemma_section_separate_labelled_and_roundtrips(tmp_path, monkeypatch):
    _grid(tmp_path / "gem", ["gemini-3.8-flash"], "low", monkeypatch)
    _grid(tmp_path / "gma", ["gemma-4-31b-it"], "default", monkeypatch)
    common = ["--bootstrap", "100", "--probe", str(tmp_path / "none.json"), "--no-figures", "--no-tags"]
    assert ladder_report.main(["--runs", str(tmp_path / "gem"), "--gemma-runs", str(tmp_path / "gma"),
                               "--out", str(tmp_path / "a"), "--export", str(tmp_path / "ex"), *common]) == 0
    a = json.loads((tmp_path / "a" / "ladder.json").read_text())
    md = (tmp_path / "a" / "ladder.md").read_text()
    # Gemini table and counts are untouched; Gemma lives only in its own section
    assert a["episodes"] == 2 and [r["model"] for r in a["rows"]] == ["gemini-3.8-flash"]
    assert a["gemma"]["episodes"] == 2 and a["gemma"]["rows"][0]["model"] == "gemma-4-31b-it"
    assert a["gemma"]["ledger"]["calls"] == 4 and len(a["gemma"]["ledger_run_ids"]) == 2
    assert "## Open-weight Gemma (hosted Gemma via the Gemini API)" in md
    assert "gemma-4-31b-it via Gemini API (hosted Gemma)" in md
    assert "Verda" not in md and md.count("self-hosted") == md.count("(not self-hosted)") == 1
    assert md.index("gemma-4-31b-it") > md.index("## Open-weight Gemma")
    # keyless round trip from the exports
    ex = tmp_path / "ex"
    assert ladder_report.main(["--runs", str(ex / "ladder_episodes.jsonl.gz"), "--ledger", str(ex / "ladder_ledger.jsonl.gz"),
                               "--gemma-runs", str(ex / "ladder_gemma_episodes.jsonl.gz"),
                               "--gemma-ledger", str(ex / "ladder_gemma_ledger.jsonl.gz"),
                               "--out", str(tmp_path / "b"), *common]) == 0
    b = json.loads((tmp_path / "b" / "ladder.json").read_text())
    strip = lambda rows: [{k: v for k, v in r.items() if k != "source"} for r in rows]  # noqa: E731
    assert strip(a["gemma"]["rows"]) == strip(b["gemma"]["rows"]) and a["gemma"]["ledger"] == b["gemma"]["ledger"]


def test_frontier_chart_and_json(tmp_path, monkeypatch):
    _grid(tmp_path / "gem", ["gemini-3.8-flash"], "low", monkeypatch)
    _grid(tmp_path / "gma", ["gemma-4-31b-it"], "default", monkeypatch)
    assert ladder_report.main(["--runs", str(tmp_path / "gem"), "--gemma-runs", str(tmp_path / "gma"), "--out",
                               str(tmp_path / "a"), "--bootstrap", "100", "--probe", str(tmp_path / "none.json"),
                               "--no-tags"]) == 0
    assert (tmp_path / "a" / "frontier.png").stat().st_size > 10_000
    fr = json.loads((tmp_path / "a" / "frontier.json").read_text())
    assert fr["title"]["hard"].startswith("Thinking is a dial")
    g = [p for p in fr["points"]["hard"] if p["kind"] == "gemma"]
    assert g and g[0]["label"] == "gemma-4-31b-it via Gemini API (hosted Gemma)"
    assert g[0]["cost_per_ep_usd"] is None  # no list price: never placed at an invented cost
    assert all("Verda" not in p["label"] for p in fr["points"]["hard"])
    assert "](frontier.png)" in (tmp_path / "a" / "ladder.md").read_text()


def test_no_gemma_section_without_gemma_runs(tmp_path, monkeypatch):
    _grid(tmp_path / "gem", ["gemini-3.8-flash"], "low", monkeypatch)
    assert ladder_report.main(["--runs", str(tmp_path / "gem"), "--out", str(tmp_path / "a"), "--bootstrap", "100",
                               "--probe", str(tmp_path / "none.json"), "--no-figures", "--no-tags"]) == 0
    assert "Gemma" not in (tmp_path / "a" / "ladder.md").read_text()
    assert "gemma" not in json.loads((tmp_path / "a" / "ladder.json").read_text())
