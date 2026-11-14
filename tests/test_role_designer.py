from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest

from canary.agents._common import inline_schema
from canary.agents.designer import Proposal
from canary.gemini.ledger import read_ledger
from canary.gemini.provenance import scan_file_secrets
from canary.rules import TIERS
from canary.solver.params import params_from_instruction
from scripts import run_role_designer as mod

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_DIR = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "paired-designer-carbon"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


@pytest.fixture(autouse=True)
def _isolate_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "isolated_ledger.jsonl"))


class ScriptedDesignerClient:
    provider = "stub"
    model = "designer-stub"

    def __init__(self, candidates: list[dict]):
        self.candidates = candidates
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None, seed=None):
        self.calls.append({"messages": messages, "response_schema": response_schema})
        body = json.dumps({"candidates": self.candidates})
        return SimpleNamespace(
            text=body,
            tool_calls=[],
            usage={"in": 120, "out": 85, "cost_usd": 0.0005},
            raw=None,
        )


def test_schema_filter_removes_unsupported_dsl_feature():
    raw_schema = inline_schema(Proposal)
    raw_txt = json.dumps(raw_schema)
    assert '"n_held_docs"' in raw_txt
    filtered = mod.filter_response_schema(raw_schema)
    filtered_txt = json.dumps(filtered)
    assert '"n_held_docs"' not in filtered_txt
    assert '"days_since_last_leak"' in filtered_txt
    assert '"recent_low_recipient_docs"' in filtered_txt


def test_make_candidate_env_applies_knobs_and_restores_tiers():
    orig = TIERS["medium"]
    cand = {
        "name": "custom-knobs",
        "rationale": "test knob propagation",
        "mole_strategy": {"rules": [{"if": [], "then": {"leak": "random_seeded", "frame": None}}]},
        "knobs": {"p_leak": 0.85, "leak_damage": 0.045, "careful_mole": True, "framing": True, "decoy": True},
    }
    env = mod.make_candidate_env("medium", 0, cand)
    assert TIERS["medium"] == orig
    assert env.p.p_leak == 0.85
    assert env.p.leak_damage == 0.045
    parsed = params_from_instruction(env.instruction())
    assert parsed == env.p


def test_cli_stub_runs_keylessly_and_writes_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "out_stub"

    rc = mod.main(["--llm", "stub", "--tier", "medium", "--seeds", "0", "1", "--n", "2", "--out", str(out_dir)])
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text())
    report = json.loads((out_dir / "report.json").read_text())
    summary = (out_dir / "summary.md").read_text()

    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "paired_designer"
    assert meta["model_id"] == "stub"
    assert meta["llm_ok"] is True
    assert meta["X"] == 0.50
    assert meta["Y"] == 0.25
    assert meta["usage"]["calls"] == 1
    assert len(report["rows"]) == 2
    assert summary.startswith("# Role 2: PAIRED Scenario Designer Run")
    for txt in ((out_dir / "meta.json").read_text(), (out_dir / "report.json").read_text(), summary):
        assert EM_DASH not in txt and EN_DASH not in txt

    ledger_rows = read_ledger([ledger_file])
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["feature"] == "adaptive_mole"


def test_paired_regret_filter_on_medium_seeds_0_to_4(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    candidates = [
        {
            "name": "decoy-framer-broad-first",
            "rationale": f"Frame decoy{EM_DASH}keep broad leaks solvable for Bayes" + ("x" * 420),
            "rules": [
                {
                    "conditions": [{"feature": "n_restricted_colleagues", "op": ">=", "value": 1}],
                    "then": {"leak": "oldest", "frame": "most_restricted_peer"},
                },
                {
                    "conditions": [{"feature": "day", "op": "<=", "value": 3}],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
                {
                    "conditions": [],
                    "then": {"leak": "random_seeded", "frame": "decoy"},
                },
            ],
            "knobs": {"p_leak": 0.85, "leak_damage": 0.04, "decoy": True, "framing": True, "careful_mole": True},
        },
        {
            "name": "over-throttled-unsolvable",
            "rationale": "Suppresses leaks for four days so solver lacks evidence",
            "rules": [
                {
                    "conditions": [{"feature": "days_since_last_leak", "op": "<", "value": 4}],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "conditions": [],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
            ],
            "knobs": {"p_leak": 0.65, "careful_mole": True},
        },
    ]
    stub = ScriptedDesignerClient(candidates)
    out_dir = tmp_path / "paired_eval"
    res = mod.run_designer_suite(
        llm_spec="stub:scripted",
        tier="medium",
        seeds=[0, 1, 2, 3, 4],
        n=2,
        x_thr=0.50,
        y_thr=0.25,
        out_dir=out_dir,
        require_llm=True,
        client_factory=lambda **kw: mod.MeteredDesignerClient(stub, system_addendum=kw.get("system_addendum", "")),
    )
    meta = res["meta"]
    report = res["report"]
    assert meta["llm_ok"] is True
    assert meta["n_llm_valid"] == 2
    assert meta["n_kept"] == 1
    assert len(report["kept"]) == 1
    assert report["kept"][0]["name"] == "decoy-framer-broad-first"
    assert EM_DASH not in report["kept"][0]["rationale"]
    assert len(report["kept"][0]["rationale"]) <= 400

    kept_row = report["rows"][0]
    rejected_row = report["rows"][1]
    assert kept_row["keep"] is True
    assert kept_row["solver"] >= 0.50
    assert kept_row["agent"] is not None and kept_row["agent"] <= 0.25
    assert kept_row["why"] == "kept"

    assert rejected_row["keep"] is False
    assert rejected_row["solver"] < 0.50
    assert rejected_row["agent"] is None
    assert rejected_row["regret"] is None
    assert rejected_row["why"] == "unsolvable (solver < X)"


def test_no_code_comments_or_em_dashes():
    for rel in ("scripts/run_role_designer.py", "tests/test_role_designer.py"):
        src = (ROOT / rel).read_text()
        assert EM_DASH not in src and EN_DASH not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found code comment in {rel}: {comments[0]}"


@pytest.mark.skipif(not COMMITTED_DIR.exists(), reason="committed designer run folder not generated yet")
def test_committed_paired_designer_carbon_artifacts():
    for fname in ("meta.json", "report.json", "summary.md"):
        fpath = COMMITTED_DIR / fname
        assert fpath.exists(), f"missing {fname}"
        txt = fpath.read_text()
        assert txt.strip(), f"empty {fname}"
        assert EM_DASH not in txt and EN_DASH not in txt, f"unicode dash found in {fname}"
        assert not scan_file_secrets(fpath, ROOT), f"secret leak found in {fname}"

    meta = json.loads((COMMITTED_DIR / "meta.json").read_text())
    report = json.loads((COMMITTED_DIR / "report.json").read_text())

    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "paired_designer"
    assert meta["model_id"] == "gemini-4-carbon"
    assert len(meta["commit"]) >= 7 and meta["commit"] != "unknown"
    assert meta["timestamp"]
    assert meta["command"]
    assert meta["tier"] == "medium"
    assert meta["tiers_version"] == "v1.4"
    assert meta["seeds"] == [0, 1, 2, 3, 4]
    assert meta["X"] == 0.50
    assert meta["Y"] == 0.25
    assert meta["llm_ok"] is True
    assert meta["n_llm_valid"] >= 1
    assert meta["n_kept"] >= 1
    assert meta["usage"]["calls"] >= 1
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["total_tokens"] > 0

    assert report["meta"]["llm_ok"] is True
    assert report["meta"]["n_llm_valid"] == meta["n_llm_valid"] >= 1
    assert len(report["rows"]) == 4
    assert len(report["kept"]) == meta["n_kept"] >= 1
    for row in report["rows"]:
        if row["keep"]:
            assert row["solver"] >= 0.50
            assert row["agent"] is not None and row["agent"] <= 0.25
