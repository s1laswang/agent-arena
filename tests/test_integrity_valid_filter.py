"""INTEGRITY item 4: `valid: false` (dropped from the reported means) must mean infra only."""
from __future__ import annotations

import json
from pathlib import Path

from canary.agents.frontier.common import agent_touched_server, classify_infra

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "data/runs/committed/opencode-gpt-5.6-sol"


def _split(t: str):
    out, _, err = t.partition("--- stderr")
    return out, err


def test_committed_invalid_episodes_are_still_classified_infra():
    """Every committed infra:* episode still classifies the same from its transcript (no silent drift)."""
    n = 0
    for tier in ("hard", "medium"):
        for line in (RUN / tier / "episodes.jsonl").read_text().splitlines():
            e = json.loads(line)
            err = (e.get("meta") or {}).get("error") or ""
            tr = RUN / tier / "transcripts" / f"{e['seed']}.txt"
            if err.startswith("infra:") and tr.exists():
                assert classify_infra(*_split(tr.read_text())) == err.split(":", 1)[1], (tier, e["seed"])
                n += 1
    assert n >= 4


def test_agent_text_never_voids_a_run():
    stdout = "\n".join(json.dumps(ev) for ev in [
        {"type": "text", "part": {"text": "The database is locked; usage limit has been reached, so I give up."}},
        {"type": "tool_use", "part": {"state": {"output": "429 Too Many Requests"}}},
    ])
    assert classify_infra(stdout, "") is None


def test_real_harness_errors_still_count():
    ev = json.dumps({"type": "error", "error": {"name": "APIError", "data": {"message": "The usage limit has been reached"}}})
    assert classify_infra(ev, "") == "provider_quota"
    assert classify_infra("", "Error: database is locked") == "opencode_db_locked"


def test_killing_the_server_is_the_agents_failure():
    for cmd in ("pkill -f canary.mcp_server", "kill -9 4242", "killall python", "kill $(lsof -ti :8765)"):
        assert agent_touched_server(json.dumps({"type": "tool_use", "part": {"state": {"input": {"command": cmd}}}}))
    assert not agent_touched_server(json.dumps({"type": "text", "part": {"text": "I will not kill anyone; skill check"}}))


def test_run_one_marks_a_self_killed_server_valid_zero(tmp_path):
    import threading
    from canary.agents.frontier import common as c

    class DeadServer:
        url, token = "http://x/mcp", "tok"
        def __init__(self, *a): pass
        def start(self, **k): return self
        def ledger(self): raise RuntimeError("MCP server died during the episode (rc=-9)")
        def stop(self): pass

    class P:
        returncode, stderr = 0, ""
        stdout = json.dumps({"type": "tool_use", "part": {"state": {"input": {"command": "pkill -f canary.mcp_server"}}}})

    spec = c.RunSpec(agent="opencode:x/y", tier="easy", seeds=[3], out=tmp_path)
    w = c.RunWriter(tmp_path)
    res = c.run_one(spec, 3, lambda wd, p, u: ["true", p], set(), w, threading.Lock(),
                    runner=lambda *a, **k: P(), server_factory=DeadServer, write=False)
    assert "error" not in res.meta and res.meta["note"].startswith("agent_killed_server") and res.score == 0.0
