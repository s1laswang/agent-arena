from __future__ import annotations

import ast
import importlib.util
import io
import json
import tokenize
from pathlib import Path

import pytest

from canary import forge_track
from canary.forge.mutate import LLMMutator
from canary.llm.base import LLMResponse
from canary.llm.stub import StubClient
from canary.mole.dsl import MoleStrategy

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_role_mole_forge.py"


def load_role_module():
    spec = importlib.util.spec_from_file_location("run_role_mole_forge", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stub_end_to_end_keyless_real_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    mod = load_role_module()
    out_dir = tmp_path / "out"
    rc = mod.main(
        [
            "--llm",
            "stub",
            "--tier",
            "hard",
            "--gens",
            "2",
            "--pop",
            "4",
            "--children",
            "4",
            "--elite",
            "1",
            "--seeds",
            "0-1",
            "--fresh-seeds",
            "5000-5001",
            "--workers",
            "2",
            "--out",
            str(out_dir),
        ]
    )
    assert rc == 0

    files = {p.name for p in out_dir.iterdir()}
    assert files == {"meta.json", "hall_of_fame.jsonl", "generations.json", "generations.png", "summary.md"}

    png = (out_dir / "generations.png").read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 2000

    meta = json.loads((out_dir / "meta.json").read_text())
    required = {
        "role",
        "subrole",
        "model_id",
        "commit",
        "timestamp",
        "command",
        "usage",
        "n_valid_llm_children",
        "best_fitness",
        "fresh_solver_accuracy",
    }
    assert required <= set(meta)
    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "mole_forge"
    assert meta["model_id"] == "stub"
    assert meta["n_valid_llm_children"] > 0
    assert meta["usage"]["calls"] == 2
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert 0.0 <= meta["fresh_solver_accuracy"] <= 1.0

    fresh_top = meta["fresh_confirmation"]["top_hof"]
    assert set(fresh_top["per_investigator"]) == {"grok_tactics", "obvious_heuristic"}

    rows, strats = forge_track.load(out_dir / "hall_of_fame.jsonl")
    assert rows and len(rows) == len(strats)
    for row in rows:
        s = MoleStrategy.from_json(row["strategy_json"])
        assert s.default[0] is not None

    gens_doc = json.loads((out_dir / "generations.json").read_text())
    assert len(gens_doc["generations"]) == 2
    assert gens_doc["generations"][1]["hof_best_fitness"] >= gens_doc["generations"][0]["hof_best_fitness"]

    ledger_rows = [json.loads(line) for line in ledger_file.read_text().splitlines() if line.strip()]
    assert len(ledger_rows) == 2
    assert all(r["feature"] == "mole_forge" and r["ok"] is True for r in ledger_rows)

    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for name in ("meta.json", "hall_of_fame.jsonl", "generations.json", "summary.md"):
        txt = (out_dir / name).read_text()
        assert em_dash not in txt and en_dash not in txt


def test_gemini_empty_structured_response_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("CANARY_LLM_MAX_RETRIES", "4")
    mod = load_role_module()
    assert issubclass(mod.ForgeLLMMutator, LLMMutator)

    class FlakyGeminiFake:
        provider = "gemini"
        model = "gemini-4-carbon"
        name = "gemini:gemini-4-carbon"

        def __init__(self):
            self.calls = 0
            self.last_user_prompt = ""
            self.total_usage = {"calls": 0, "in": 0, "out": 0, "cost_usd": 0.0}

        def chat(self, messages, **kw):
            self.calls += 1
            self.last_user_prompt = messages[-1]["content"]
            if self.calls == 1:
                raise ConnectionError("transient reset")
            self.total_usage["calls"] += 1
            self.total_usage["in"] += 100
            if self.calls == 2:
                return LLMResponse(text="", usage={"in": 100, "out": 0, "cost_usd": 0.001})
            payload = {
                "children": [
                    {
                        "rationale": f"frame decoy{chr(0x2014)}avoid tiny traps",
                        "rules": [{"if": [["day", ">=", "2"]], "then": {"leak": "oldest", "frame": "decoy"}}],
                        "default": {"leak": "random_seeded", "frame": "decoy"},
                    }
                ]
            }
            self.total_usage["out"] += 60
            return LLMResponse(text=json.dumps(payload), usage={"in": 100, "out": 60, "cost_usd": 0.002})

    fake_gem = FlakyGeminiFake()
    wrapped = mod.RetryingForgeClient(fake_gem, sleep_fn=lambda _s: None)
    rc = mod.main(
        [
            "--llm",
            "gemini:gemini-4-carbon",
            "--gens",
            "1",
            "--pop",
            "2",
            "--children",
            "4",
            "--seeds",
            "0-1",
            "--fresh-seeds",
            "5000-5001",
            "--fake",
            "--out",
            str(tmp_path / "retry_out"),
        ],
        client=wrapped,
    )
    assert rc == 0
    assert fake_gem.calls == 3
    assert "Return exactly 4 children" in fake_gem.last_user_prompt
    meta = json.loads((tmp_path / "retry_out" / "meta.json").read_text())
    assert meta["n_valid_llm_children"] == 1


def test_zero_valid_llm_children_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    mod = load_role_module()
    bad_client = StubClient(script=[{"json": {"children": []}}] * 4)
    with pytest.raises(RuntimeError, match="0 valid DSL children"):
        mod.main(
            [
                "--llm",
                "stub",
                "--gens",
                "1",
                "--pop",
                "3",
                "--seeds",
                "0-1",
                "--fresh-seeds",
                "5000-5001",
                "--fake",
                "--out",
                str(tmp_path / "bad"),
            ],
            client=bad_client,
        )


def test_no_comments_or_em_dashes_in_new_sources():
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    for path in (SCRIPT_PATH, Path(__file__).resolve()):
        src = path.read_text()
        assert em_dash not in src and en_dash not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert [t for t in tokens if t.type == tokenize.COMMENT] == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                assert ast.get_docstring(node) is None
