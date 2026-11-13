import json
from types import SimpleNamespace as NS

import pytest

from canary.agents.llm_policy import HINTS, NUDGE, LLMPolicy, build_system_prompt
from canary.agents.loop import run_episode
from fake_env import FakeEnv


class Stub:
    """Local scripted stub (canary.llm StubClient may not exist yet)."""
    def __init__(self, script):
        self.script, self.i, self.seen = script, 0, []

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None):
        self.seen.append([dict(m) for m in messages])
        s = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        calls = [NS(id=f"c{self.i}_{j}", name=c["name"], args=c.get("args", {})) for j, c in enumerate(s.get("tool_calls", []))]
        return NS(text=s.get("text", ""), tool_calls=calls, usage={"in": 10, "out": 2, "cost_usd": 0.001})


def tc(name, **args):
    return {"tool_calls": [{"name": name, "args": args}]}


def test_plays_to_accusation():
    env = FakeEnv()
    stub = Stub([tc("status"), tc("check_leak_feed"), tc("advance_day"), tc("accuse", employee="e03")])
    pol = LLMPolicy("stub", client=stub)
    res = run_episode(env, pol, "stub")
    assert res.end_reason == "accused" and res.correct and res.score == 1.0
    assert [s.tool for s in res.steps] == ["status", "check_leak_feed", "advance_day", "accuse"]
    tools = [m for m in pol.transcript if m["role"] == "tool"]
    assert len(tools) == 3 and json.loads(tools[0]["content"])["ok"]
    assert pol.usage["calls"] == 4 and pol.usage["in"] == 40
    assert pol.transcript[0]["content"].startswith(env.instruction())


def test_hints():
    p = build_system_prompt("INSTR", "decoy_chase,ignored_delay")
    assert p.startswith("INSTR") and HINTS["decoy_chase"] in p and HINTS["ignored_delay"] in p
    assert HINTS["budget_waste"] not in build_system_prompt("INSTR", None)
    with pytest.raises(ValueError):
        build_system_prompt("x", "nope")
    assert len(HINTS) == 7


def test_nudge_then_fallback():
    env = FakeEnv()
    stub = Stub([{"text": "thinking"}, tc("list_employees"), {"text": "hmm"}, {"text": "still"}, tc("accuse", employee="e01")])
    pol = LLMPolicy("stub", client=stub)
    res = run_episode(env, pol, "stub")
    assert [s.tool for s in res.steps] == ["list_employees", "status", "accuse"]
    assert sum(1 for m in pol.transcript if m.get("content") == NUDGE) == 2
    assert not res.correct and res.score == 0.0


def test_multi_tool_queue():
    env = FakeEnv()
    stub = Stub([{"tool_calls": [{"name": "status"}, {"name": "list_employees"}, {"name": "check_leak_feed"}]},
                 tc("accuse", employee="e03")])
    pol = LLMPolicy("stub", client=stub)
    res = run_episode(env, pol, "stub")
    assert [s.tool for s in res.steps] == ["status", "list_employees", "check_leak_feed", "accuse"]
    assert stub.i == 2
    # every tool call id answered before the next model call
    ids = [m["tool_call_id"] for m in stub.seen[1] if m["role"] == "tool"]
    assert ids == ["c1_0", "c1_1", "c1_2"]


def test_context_truncation():
    pol = LLMPolicy("stub", client=Stub([tc("status")]), max_turns=2)
    pol.reset([], "I")
    for k in range(5):
        pol.transcript += [{"role": "assistant", "content": "", "tool_calls": [{"id": str(k), "name": "x", "args": {}}]},
                           {"role": "tool", "tool_call_id": str(k), "content": "z" * 5000}]
    ctx = pol._context()
    assert ctx[0]["role"] == "system" and sum(m["role"] == "assistant" for m in ctx) == 2
    assert len(ctx[2]["content"]) < 2100 and len(ctx[-1]["content"]) == 5000


def test_play_cli_fake(tmp_path):
    from canary.agents import play
    out = play.main(["--agent", "openai:gpt-x", "--tier", "easy", "--seeds", "0-1", "--fake", "--out", str(tmp_path / "r")],
                    client=Stub([tc("status"), tc("accuse", employee="e03")]))
    lines = (out / "episodes.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for ln in lines:
        d = json.loads(ln)
        assert {"tier", "seed", "agent", "steps", "score", "accused", "correct", "final_day", "end_reason"} <= set(d)
    meta = json.loads((out / "meta.json").read_text())
    assert meta["provider"] == "openai" and meta["model"] == "gpt-x" and meta["seeds"] == [0, 1]
    assert (out / "transcripts" / "0.json").exists()


def test_run_id():
    from canary.agents.runlog import run_id, parse_seeds
    assert ":" not in run_id("openai:gpt-5-mini", "medium") and run_id("a:b", "easy").startswith("a_b-easy-")
    assert parse_seeds("0-2,7") == [0, 1, 2, 7]
