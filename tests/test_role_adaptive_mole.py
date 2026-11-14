from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest

from canary.agents.mole_arena import LLMMole
from canary.gemini.ledger import read_ledger
from canary.llm.stub import StubClient
from scripts import run_role_adaptive_mole as mod

ROOT = Path(__file__).resolve().parents[1]
COMMITTED_DIR = ROOT / "results" / "gemini_roles" / "adaptive_mole" / "arena-live-carbon-med012"


class AdaptiveStubClient:
    provider = "stub"
    model = "adaptive-stub"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None, seed=None):
        self.calls += 1
        user_payload = json.loads(messages[-1]["content"])
        docs = user_payload.get("held_docs") or []
        peers = user_payload.get("peers") or []
        wide = [d for d in docs if (d.get("recipient_count") or 0) >= 8]
        leak = max(wide, key=lambda d: d["recipient_count"])["doc_id"] if wide else None
        frame = peers[0] if peers else None
        body = json.dumps({"leak": leak, "frame": frame, "reason": "pick widest briefing\u2014avoid narrow trap"})
        return SimpleNamespace(text=body, tool_calls=[], usage={"in": 40, "out": 15, "cost_usd": 0.0002}, raw=None)


def test_live_arena_mole_masks_canary_ids_and_records_decisions():
    view = SimpleNamespace(
        day=3,
        docs=(
            SimpleNamespace(doc_id="c3", title="Board memo draft 3", recipient_count=2, age_days=0),
            SimpleNamespace(doc_id="d3-1", title="Q3 Sales forecast", recipient_count=11, age_days=0),
        ),
        days_since_last_leak=2,
        i_am_restricted=0,
        n_restricted_colleagues=1,
        recent_low_recipient_docs=1,
        peers=("e01", "e02", "e07"),
        restricted_peers=("e07",),
        decoy="e02",
        can_leak=True,
    )
    stub = AdaptiveStubClient()
    client = mod.MeteredMoleClient(stub)
    mole = mod.LiveArenaMole(client, tier="medium", seed=0, investigator="solver")
    assert isinstance(mole, LLMMole)
    move = mole.decide(view)
    assert move == {"leak": "d3-1", "frame": "e01"}
    assert len(mole.decisions) == 1
    rec = mole.decisions[0]
    assert rec["day"] == 3
    assert rec["leak"] == "d3-1"
    assert rec["frame"] == "e01"
    assert "\u2014" not in (rec["reason"] or "")
    assert {d["doc_id"] for d in rec["mole_view"]["held_docs"]} == {"c3", "d3-1"}
    assert rec["rejected"] == []
    assert rec["error"] is None
    assert client.usage_totals["total_tokens"] == 55


def test_live_arena_mole_records_rejected_moves():
    script = [{"json": {"leak": "doc99", "frame": "bad_id", "reason": "invalid ids"}}]
    stub = StubClient(script=script)
    mole = mod.LiveArenaMole(mod.MeteredMoleClient(stub), tier="medium", seed=1, investigator="grok_tactics")
    view = {
        "day": 2,
        "held_docs": [{"doc_id": "d2-1", "title": "Ops plan", "recipient_count": 10, "age_days": 0}],
        "days_since_last_leak": 1,
        "i_am_restricted": False,
        "n_restricted_colleagues": 0,
        "recent_low_recipient_docs": 0,
        "peers": ["e03", "e04"],
    }
    move = mole.decide(view)
    assert move == {"leak": None, "frame": None}
    assert mole.decisions[0]["rejected"] == ["leak:doc99", "frame:bad_id"]


def test_cli_stub_runs_keylessly_and_writes_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "out_stub"

    rc = mod.main(["--llm", "stub", "--tier", "medium", "--seeds", "0", "--out", str(out_dir), "--jobs", "2"])
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text())
    episodes = json.loads((out_dir / "episodes.json").read_text())
    decisions = [json.loads(line) for line in (out_dir / "mole_decisions.jsonl").read_text().splitlines() if line.strip()]
    summary = (out_dir / "summary.md").read_text()

    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "live_arena_mole"
    assert meta["model_id"] == "stub"
    assert meta["mole_llm_errors"] == 0
    assert meta["usage"]["calls"] == len(decisions) > 0
    assert len(episodes["adaptive_mole"]) == 3
    assert len(episodes["default_mole"]) == 3
    assert summary.startswith("# Role 2: Adaptive Mole Live Arena Run")
    ledger_rows = read_ledger([ledger_file])
    assert len(ledger_rows) == len(decisions)
    assert all(r["feature"] == "adaptive_mole" for r in ledger_rows)


def test_adaptive_mole_solvability_on_seeds_012(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    out_dir = tmp_path / "solvability"
    meta = mod.run_arena_suite(
        llm_spec="stub:adaptive",
        tier="medium",
        seeds=[0, 1, 2],
        out_dir=out_dir,
        jobs=3,
        client_factory=lambda **kw: mod.MeteredMoleClient(AdaptiveStubClient()),
    )
    assert meta["solver_accuracy"] == 1.0
    assert meta["solver_mean"] > meta["grok_tactics_mean"]
    assert meta["solver_mean"] > meta["heuristic_mean"]
    assert meta["grok_tactics_mean"] < meta["baseline_default_mole"]["grok_tactics_mean"]
    assert meta["solvability_verified"] is True


def test_no_code_comments_or_em_dashes():
    for rel in ("scripts/run_role_adaptive_mole.py", "tests/test_role_adaptive_mole.py"):
        src = (ROOT / rel).read_text()
        assert "\u2014" not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found code comment in {rel}: {comments[0]}"


@pytest.mark.skipif(not COMMITTED_DIR.exists(), reason="committed live run folder not generated yet")
def test_committed_live_carbon_run_artifacts():
    for fname in ("meta.json", "episodes.json", "mole_decisions.jsonl", "summary.md"):
        fpath = COMMITTED_DIR / fname
        assert fpath.exists(), f"missing {fname}"
        txt = fpath.read_text()
        assert txt.strip(), f"empty {fname}"
        assert "\u2014" not in txt, f"em dash found in {fname}"

    meta = json.loads((COMMITTED_DIR / "meta.json").read_text())
    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "live_arena_mole"
    assert meta["model_id"] == "gemini-4-carbon"
    assert len(meta["commit"]) >= 7 and meta["commit"] != "unknown"
    assert meta["timestamp"]
    assert meta["command"]
    assert meta["mole_llm_errors"] == 0
    assert meta["usage"]["calls"] > 0
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["total_tokens"] > 0
    assert meta["solver_accuracy"] > 0.0
    assert meta["solver_mean"] > meta["grok_tactics_mean"]
    assert meta["solver_mean"] > meta["heuristic_mean"]

    episodes = json.loads((COMMITTED_DIR / "episodes.json").read_text())
    assert len(episodes["adaptive_mole"]) == 9
    assert len(episodes["default_mole"]) == 9

    decisions = [
        json.loads(line)
        for line in (COMMITTED_DIR / "mole_decisions.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(decisions) == meta["mole_decisions_count"] > 0
    for d in decisions:
        assert {"day", "mole_view", "leak", "frame", "reason", "rejected", "error"} <= set(d)
        assert d["error"] is None
