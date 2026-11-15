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


def test_headline_verb_is_ci_gated():
    r = lambda v, lo, hi: {"ratio": v, "ratio_lo": lo, "ratio_hi": hi}  # noqa: E731
    assert ladder_report.headline_verb(r(.98, .82, 1.19), r(1.09, .90, 1.39)).startswith("matches")
    assert "CIs are wide" in ladder_report.headline_verb(r(.78, .28, 1.51), r(.71, .11, 1.58))
    assert ladder_report.headline_verb(r(.85, .81, .95), r(.9, .82, .97)).startswith("comes close")
    assert ladder_report.headline_verb(r(.5, .3, .7), r(.6, .4, .8)).startswith("reaches part")


def test_j1_self_hosted_section_replay_verified_and_costed(tmp_path, monkeypatch):
    from canary.agents import play
    _grid(tmp_path / "gem", ["gemini-3.8-flash"], "low", monkeypatch)
    j1 = tmp_path / "j1"
    play.main(["--agent", "stub", "--tier", "hard", "--seeds", "0-1", "--out", str(j1)])
    args = ["--runs", str(tmp_path / "gem"), "--out", str(tmp_path / "a"), "--bootstrap", "100",
            "--probe", str(tmp_path / "none.json"), "--no-tags", "--j1-runs", str(j1), "--j1-model", "Qwen/Qwen3-14B",
            "--j1-eur-per-hour", "1.0794", "--j1-billed-hours", "hard=0.5", "--j1-eur-usd", "1.10",
            "--j1-fx-source", "test rate", "--j1-cap-tokens", "4096"]
    assert ladder_report.main(args) == 0
    doc = json.loads((tmp_path / "a" / "ladder.json").read_text())
    j = doc["j1"]
    assert j["episodes"] == 2 and j["replay_verified"] == 2 and not j["replay_mismatches"]
    r = j["rows"][0]
    assert abs(r["cost_per_ep_eur"] - 1.0794 * 0.5 / 2) < 1e-9 and abs(r["cost_per_ep"] - 1.0794 * 0.25 * 1.10) < 1e-9
    md = (tmp_path / "a" / "ladder.md").read_text()
    assert "## Open-weight comparison on Canary v1.4 (Verda self-hosted)" in md and "2/2 replay-verified" in md
    assert "Qwen/Qwen3-14B (Verda self-hosted, vLLM)" in md
    assert ("Gemini cells had no per-turn output cap; Qwen/Qwen3-14B was capped at 4096 tokens/turn for time." in md)
    assert "| medium | Qwen/Qwen3-14B (Verda self-hosted, vLLM) | 0 | not run |" in md
    assert doc["episodes"] == 2 and [x["model"] for x in doc["rows"]] == ["gemini-3.8-flash"]  # Gemini table untouched
    fr = json.loads((tmp_path / "a" / "frontier.json").read_text())
    p = [x for x in fr["points"]["hard"] if x["kind"] == "j1"][0]
    assert p["cost_per_ep_usd"] and "EUR 1.0794/h" in p["cost_basis"] and not p["imported"]
    assert p["label"] == "Qwen/Qwen3-14B (Verda self-hosted, vLLM, capped 4096 tok/turn)"
    # without cost inputs the points are never placed at an invented cost
    assert ladder_report.main(args[:-10] + ["--out", str(tmp_path / "b")]) == 0
    fb = json.loads((tmp_path / "b" / "frontier.json").read_text())
    assert [x for x in fb["points"]["hard"] if x["kind"] == "j1"][0]["cost_per_ep_usd"] is None


def test_no_gemma_section_without_gemma_runs(tmp_path, monkeypatch):
    _grid(tmp_path / "gem", ["gemini-3.8-flash"], "low", monkeypatch)
    assert ladder_report.main(["--runs", str(tmp_path / "gem"), "--out", str(tmp_path / "a"), "--bootstrap", "100",
                               "--probe", str(tmp_path / "none.json"), "--no-figures", "--no-tags"]) == 0
    assert "Gemma" not in (tmp_path / "a" / "ladder.md").read_text()
    assert "gemma" not in json.loads((tmp_path / "a" / "ladder.json").read_text())
