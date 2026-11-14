from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from canary.gemini.ledger import LedgeredClient, read_ledger
from canary.llm import LLMClient, LLMResponse, MissingKeyError, ToolCall
import scripts.run_gemini_clash as clash_script


class MockGeminiBackend(LLMClient):
    provider = "gemini"

    def __init__(self, model: str, mode: str, true_mole: str = "e00"):
        super().__init__(model=model, max_retries=0)
        self.mode = mode
        self.true_mole = true_mole
        self.turn = 0

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        self.turn += 1
        raw = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=100,
                candidates_token_count=25,
                thoughts_token_count=50,
                cached_content_token_count=20,
            )
        )
        if self.mode == "mole":
            payload = json.loads(messages[-1]["content"])
            docs = payload.get("held_docs") or []
            leak_id = docs[0]["doc_id"] if docs else None
            text = json.dumps({"leak": leak_id, "frame": None, "reason": "wide distribution \u2014 safe"})
            return LLMResponse(text=text, tool_calls=[], usage={"in": 100, "out": 75, "cost_usd": 0.001}, raw=raw)
        if self.turn == 1:
            tc = [ToolCall(id="c_1", name="advance_day", args={})]
        else:
            tc = [ToolCall(id="c_2", name="accuse", args={"employee": self.true_mole})]
        return LLMResponse(text="", tool_calls=tc, usage={"in": 100, "out": 75, "cost_usd": 0.001}, raw=raw)


def test_run_gemini_clash_stub_keyless(tmp_path, monkeypatch):
    ledger_file = tmp_path / "ledger.jsonl"
    out_dir = tmp_path / "clash_stub"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")

    rc = clash_script.main(["--llm", "stub", "--tier", "medium", "--seed", "0", "--out", str(out_dir)])
    assert rc == 0

    for fname in ("meta.json", "investigator_transcript.json", "mole_log.json", "solver_check.json", "summary.md"):
        assert (out_dir / fname).is_file()

    meta = json.loads((out_dir / "meta.json").read_text())
    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "carbon_vs_carbon_clash"
    assert meta["model_id"] == "stub"
    assert meta["tier"] == "medium"
    assert meta["seed"] == 0
    assert meta["commit"]
    assert meta["timestamp"].endswith("Z")
    assert isinstance(meta["investigator_score"], float)
    assert isinstance(meta["solver_score"], float)

    rows = read_ledger([ledger_file])
    inv_rows = [r for r in rows if r["feature"] == "clash_investigator"]
    mole_rows = [r for r in rows if r["feature"] == "clash_mole"]
    assert len(inv_rows) == 7
    assert len(mole_rows) >= 2

    u = meta["usage"]
    assert u["clash_investigator"]["calls"] == len(inv_rows)
    assert u["clash_mole"]["calls"] == len(mole_rows)
    assert u["calls"] == len(inv_rows) + len(mole_rows)
    assert u["in"] == u["clash_investigator"]["in"] + u["clash_mole"]["in"]
    assert u["out"] == u["clash_investigator"]["out"] + u["clash_mole"]["out"]

    inv_tr = json.loads((out_dir / "investigator_transcript.json").read_text())
    assert inv_tr["end_reason"] == "accused"
    assert inv_tr["steps"][-1]["tool"] == "accuse"
    assert inv_tr["transcript"][-1]["role"] == "tool"
    assert inv_tr["transcript"][-1]["name"] == "accuse"

    mole_log = json.loads((out_dir / "mole_log.json").read_text())
    assert len(mole_log["clash_mole_log"]) == 2
    assert len(mole_log["solver_mole_log"]) >= 1

    solver_check = json.loads((out_dir / "solver_check.json").read_text())
    assert solver_check["investigator"] == "solver"
    assert len(solver_check["steps"]) > 0
    assert len(solver_check["belief_trace"]) > 0

    summary_md = (out_dir / "summary.md").read_text()
    assert "\u2014" not in summary_md
    assert "clash_investigator" in summary_md
    assert "clash_mole" in summary_md


def test_run_gemini_clash_carbon_usage_and_solvability(tmp_path, monkeypatch):
    from canary.env import Env

    ledger_file = tmp_path / "carbon_ledger.jsonl"
    out_dir = tmp_path / "carbon_out"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    true_mole = Env("medium", 0)._world.mole

    def fake_builder(spec, feature, run_id, meta, thinking_level=None):
        mode = "mole" if feature == "clash_mole" else "investigator"
        return LedgeredClient(MockGeminiBackend("gemini-4-carbon", mode=mode, true_mole=true_mole),
                              feature=feature, run_id=run_id, meta=meta)

    meta = clash_script.run_clash(
        spec="gemini:gemini-4-carbon",
        tier="medium",
        seed=0,
        out_dir=out_dir,
        client_builder=fake_builder,
    )
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["investigator_correct"] is True
    assert meta["investigator_score"] > 0.0
    assert meta["solver_correct"] is True
    assert meta["solver_score"] > 0.0
    assert meta["solvable"] is True

    u = meta["usage"]
    assert u["clash_investigator"]["calls"] == 2
    assert u["clash_investigator"]["thinking"] == 100
    assert u["clash_investigator"]["cached"] == 40
    assert u["clash_mole"]["calls"] == meta["mole_clash_days"] + meta["mole_solver_days"]
    assert u["thinking"] == u["clash_investigator"]["thinking"] + u["clash_mole"]["thinking"]
    assert u["cached"] == u["clash_investigator"]["cached"] + u["clash_mole"]["cached"]
    assert u["cost_usd"] > 0.0

    rows = read_ledger([ledger_file])
    assert sum(r["thinking"] for r in rows) == u["thinking"]
    assert sum(r["in"] for r in rows) == u["in"]
    assert sum(r["out"] for r in rows) == u["out"]

    summary_md = (out_dir / "summary.md").read_text()
    assert "\u2014" not in summary_md
    assert "wide distribution - safe" in summary_md


def test_cli_subprocess_keyless(tmp_path):
    out_dir = tmp_path / "subproc_out"
    ledger_file = tmp_path / "subproc_ledger.jsonl"
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(
        os.environ,
        PYTHONPATH=str(repo_root),
        GEMINI_API_KEY="",
        GOOGLE_GENERATIVE_AI_API_KEY="",
        CANARY_GEMINI_LEDGER=str(ledger_file),
    )
    res = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "run_gemini_clash.py"),
         "--llm", "stub", "--tier", "easy", "--seed", "0", "--out", str(out_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    summary = json.loads(res.stdout.strip())
    assert summary["model_id"] == "stub"
    assert (out_dir / "meta.json").is_file()


def test_missing_key_raises_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    with pytest.raises(MissingKeyError):
        clash_script.build_ledgered_client("gemini:gemini-4-carbon", "clash_mole", "r1", {})
