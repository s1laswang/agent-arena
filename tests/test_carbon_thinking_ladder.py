from __future__ import annotations

import io
import json
import sys
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.gap import load_runs
from canary.env import Env
from canary.eval import run_episode
from canary.gemini.ledger import LedgeredClient, read_ledger
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.gemini.roles_dashboard import collect_roles_data
from canary.llm import MissingKeyError
from canary.llm.gemini_backend import GeminiClient
from canary.solver.policy import SolverPolicy
from scripts import run_carbon_thinking_ladder as runner


def test_stub_end_to_end_ladder(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "thinking-ladder-carbon-med01"

    rc = runner.main([
        "--stub",
        "--model", "gemini-4-carbon",
        "--levels", "low,high",
        "--tier", "medium",
        "--seeds", "0,1",
        "--out", str(out_dir),
    ])
    assert rc == 0

    meta_path = out_dir / "meta.json"
    comp_path = out_dir / "comparison.json"
    md_path = out_dir / "summary.md"
    assert meta_path.exists()
    assert comp_path.exists()
    assert md_path.exists()

    meta = json.loads(meta_path.read_text())
    assert meta["role"] == "investigators"
    assert meta["subrole"] == "thinking_level_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["stub"] is True
    assert meta["tier"] == "medium"
    assert meta["seeds"] == [0, 1]
    assert meta["levels"] == ["low", "high"]
    assert meta["n_episodes"] == 4
    assert isinstance(meta["commit"], str) and len(meta["commit"]) >= 7
    assert isinstance(meta["timestamp"], str) and "T" in meta["timestamp"]
    assert "--stub" in meta["command"]
    assert set(meta["levels_summary"].keys()) == {"low", "high"}

    for s in (0, 1):
        expected_solver = run_episode(Env("medium", s), SolverPolicy()).score
        assert meta["solver_baseline"]["per_seed"][str(s)]["score"] == pytest.approx(expected_solver)

    low_sum = meta["levels_summary"]["low"]
    high_sum = meta["levels_summary"]["high"]
    assert high_sum["thinking_tokens_per_episode"] > low_sum["thinking_tokens_per_episode"]
    assert low_sum["tag_counts"].get("premature_accusation", 0) >= 2
    assert low_sum["regret_total"] > 0.0

    for lv in ("low", "high"):
        lv_dir = out_dir / lv
        assert (lv_dir / "episodes.jsonl").exists()
        assert (lv_dir / "level_meta.json").exists()
        assert not (lv_dir / "meta.json").exists()
        for s in (0, 1):
            tr_file = lv_dir / "transcripts" / f"{s}.json"
            assert tr_file.exists()
            tr_text = tr_file.read_text()
            assert "<redacted_thought_signature_chars:" in tr_text
            assert "c3R1Yl9zaWc=" not in tr_text

    loaded = load_runs(out_dir)
    assert len(loaded) == 4
    assert {e["agent"] for e in loaded} == {
        "stub:gemini-4-carbon+think:low",
        "stub:gemini-4-carbon+think:high",
    }

    comp = json.loads(comp_path.read_text())
    assert len(comp["paired_by_seed"]) == 2
    assert comp["delta_high_vs_low"]["thinking_tokens_per_episode_delta"] > 0

    md_text = md_path.read_text()
    assert "\u2014" not in md_text and "\u2013" not in md_text
    assert "SolverPolicy (reference)" in md_text
    assert "canary.solver.regret.attribute" in md_text

    led_rows = read_ledger([ledger_file])
    assert len(led_rows) == meta["usage"]["calls"]
    assert sum(r["thinking"] for r in led_rows) == meta["usage"]["thinking"]


def test_gemini_backend_thinking_level_wiring_keyless(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    ledger_file = tmp_path / "wiring_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    captured: list[dict] = []

    class FakeModels:
        def __init__(self, think_tokens: int):
            self.think_tokens = think_tokens

        def generate_content(self, **kwargs):
            captured.append(kwargs)
            part_thought = SimpleNamespace(function_call=None, text="pondering", thought=True)
            fc = SimpleNamespace(id="call_1", name="status", args={})
            part_fc = SimpleNamespace(function_call=fc, text=None, thought=False)
            content = SimpleNamespace(
                parts=[part_thought, part_fc],
                model_dump=lambda mode="json", exclude_none=True: {
                    "role": "model",
                    "parts": [
                        {"thought": True, "text": "pondering"},
                        {"function_call": {"id": "call_1", "name": "status", "args": {}}, "thought_signature": "abc123"},
                    ],
                },
            )
            cand = SimpleNamespace(content=content, finish_reason="STOP")
            um = SimpleNamespace(
                prompt_token_count=120,
                candidates_token_count=18,
                thoughts_token_count=self.think_tokens,
                cached_content_token_count=40,
            )
            return SimpleNamespace(candidates=[cand], usage_metadata=um, model_version="gemini-4-carbon-001")

    for level, expected_enum, think_tok in (("low", "LOW", 80), ("high", "HIGH", 900)):
        sdk = SimpleNamespace(models=FakeModels(think_tok))
        gem = GeminiClient(model="gemini-4-carbon", sdk_client=sdk, thinking_level=level)
        assert gem.settings()["thinking_level"] == level
        assert gem.settings()["include_thoughts"] is True
        led = LedgeredClient(gem, feature="ladder", run_id=f"test:{level}")
        tally = runner.TallyClient(led, model="gemini-4-carbon")
        resp = tally.chat(
            [{"role": "user", "content": "Check status."}],
            tools=[{"name": "status", "description": "status", "parameters": {"type": "object", "properties": {}}}],
        )
        req = captured[-1]
        tc = req["config"].thinking_config
        assert tc.include_thoughts is True
        assert expected_enum in str(tc.thinking_level)
        assert req["config"].temperature is None
        assert resp.thoughts == "pondering"
        u = tally.usage_dict(wall_s=1.2)
        assert u["in"] == 120
        assert u["out"] == 18
        assert u["thinking"] == think_tok
        assert u["cached"] == 40
        assert u["out_incl_thinking"] == 18 + think_tok

    rows = read_ledger([ledger_file])
    assert [r["thinking"] for r in rows] == [80, 900]
    assert [r["out"] for r in rows] == [18, 18]


def test_guards_invalid_inputs_and_missing_key(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        runner.parse_levels("low,extreme")
    with pytest.raises(ValueError):
        runner.parse_public_seeds("900000")
    with pytest.raises(ValueError):
        runner.parse_public_seeds("800001")
    with pytest.raises(ValueError):
        runner.guard_output_dir(ROOT / "data" / "runs" / "committed" / "v1.4" / "forbidden")

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    with pytest.raises(MissingKeyError):
        runner.make_default_client("gemini-4-carbon", "low", "run:test", {}, stub=False)


def test_committed_artifact_schema_if_present():
    artifact = ROOT / "results" / "gemini_roles" / "investigators" / "thinking-ladder-carbon-med01"
    meta_file = artifact / "meta.json"
    if not meta_file.exists():
        pytest.skip("real artifact not yet generated")
    meta = json.loads(meta_file.read_text())
    assert meta["role"] == "investigators"
    assert meta["subrole"] == "thinking_level_ablation"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["stub"] is False
    assert meta["tier"] == "medium"
    assert meta["seeds"] == [0, 1]
    assert meta["levels"] == ["low", "high"]
    assert meta["n_episodes"] == 4
    assert meta["usage"]["episodes"] == 4
    assert meta["usage"]["calls"] > 0
    assert meta["usage"]["thinking"] > 0
    for lv in ("low", "high"):
        assert (artifact / lv / "episodes.jsonl").exists()
        assert (artifact / lv / "level_meta.json").exists()
        assert not (artifact / lv / "meta.json").exists()
        eps = [json.loads(x) for x in (artifact / lv / "episodes.jsonl").read_text().splitlines() if x.strip()]
        assert len(eps) == 2
        assert all(e["end_reason"] != "error" for e in eps)
    for p in artifact.rglob("*"):
        if p.is_file():
            txt = p.read_text()
            assert "\u2014" not in txt and "\u2013" not in txt
            assert "AIza" not in txt
            assert scan_file_secrets(p, ROOT) == []

    prov = audit_provenance(ROOT)
    ladder_prov = [
        r for r in prov["runs"]
        if r["run_dir"].startswith("results/gemini_roles/investigators/thinking-ladder-carbon-med01")
    ]
    assert len(ladder_prov) == 1
    assert ladder_prov[0]["verified"] is True
    assert ladder_prov[0]["count"] == 4

    dash = collect_roles_data(ROOT)
    ladder_dash = [
        r for r in dash["runs"]
        if r["run_folder"].startswith("results/gemini_roles/investigators/thinking-ladder-carbon-med01")
    ]
    assert len(ladder_dash) == 1
    assert ladder_dash[0]["verified"] is True
    assert "low" in ladder_dash[0]["key_metric"] and "high" in ladder_dash[0]["key_metric"]


def test_source_files_have_no_comments_em_dashes_or_keys():
    for path in (
        ROOT / "scripts" / "run_carbon_thinking_ladder.py",
        ROOT / "tests" / "test_carbon_thinking_ladder.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []
        assert scan_file_secrets(path, ROOT) == []
