"""Zero-API tests: full-history context, Responses API request building + reasoning carry-over, MCP parity."""
import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from canary.agents.llm_policy import LLMPolicy, build_system_prompt
from canary.agents.loop import run_episode
from fake_env import FakeEnv


class Recorder:
    """Scripted client that records every message list it is sent."""
    def __init__(self, n_status: int):
        self.n, self.i, self.seen = n_status, 0, []

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None):
        self.seen.append(messages)
        self.i += 1
        if self.i == 1:
            name, args = "list_employees", {}
        elif self.i <= self.n:
            name, args = ("advance_day", {}) if self.i % 10 == 0 else ("status", {})
        else:
            name, args = "accuse", {"employee": "e03"}
        return NS(text="", tool_calls=[NS(id=f"c{self.i}", name=name, args=args)], usage={"in": 1, "out": 1})


def test_full_context_keeps_day1_results_in_long_episode():
    env = FakeEnv(tool_call_cap=300, n_days=14)
    rec = Recorder(n_status=80)
    pol = LLMPolicy("stub", client=rec)
    assert pol.context == "full"
    res = run_episode(env, pol, "stub")
    assert len(res.steps) > 40 and res.end_reason == "accused"
    last = rec.seen[-1]
    tool_msgs = [m for m in last if m["role"] == "tool"]
    assert tool_msgs[0]["tool_call_id"] == "c1" and tool_msgs[0]["name"] == "list_employees"
    assert len(tool_msgs) == len(res.steps) - 1                 # every earlier result present
    full = [json.dumps(s.result, default=str) for s in res.steps[:-1]]
    assert [m["content"] for m in tool_msgs] == full           # untruncated, verbatim


def test_window_mode_still_available_and_lossy():
    env = FakeEnv()
    rec = Recorder(n_status=80)
    pol = LLMPolicy("stub", client=rec, context="window", max_turns=10)
    run_episode(env, pol, "stub")
    assert not any(m.get("tool_call_id") == "c1" for m in rec.seen[-1])
    with pytest.raises(ValueError):
        LLMPolicy("stub", context="bogus")


# ---------------- Responses API (mocked SDK)
class FakeResponses:
    def __init__(self, outputs):
        self.outputs, self.requests = list(outputs), []

    def create(self, **req):
        self.requests.append(json.loads(json.dumps(req)))
        out = self.outputs.pop(0)
        return NS(output=out, usage=NS(input_tokens=100, output_tokens=10))


class FakeSDK:
    def __init__(self, outputs):
        self.responses = FakeResponses(outputs)
        self.chat = None


def _fc(cid, name, args):
    return {"type": "function_call", "id": "fc_" + cid, "call_id": cid, "name": name, "arguments": json.dumps(args)}


def _rs(n):
    return {"type": "reasoning", "id": f"rs_{n}", "summary": [], "encrypted_content": f"ENC{n}"}


def test_responses_default_for_gpt5_and_request_shape():
    from canary.llm.openai_backend import OpenAIClient
    assert OpenAIClient("gpt-5.5", sdk_client=FakeSDK([])).api == "responses"
    assert OpenAIClient("o3", sdk_client=FakeSDK([])).api == "responses"
    assert OpenAIClient("gpt-4o", sdk_client=FakeSDK([])).api == "chat"
    assert OpenAIClient("gpt-5.5", sdk_client=FakeSDK([]), api="chat").api == "chat"
    sdk = FakeSDK([[_rs(1), _fc("call_1", "status", {})]])
    c = OpenAIClient("gpt-5.5", sdk_client=sdk, reasoning_effort="medium")
    r = c.chat([{"role": "system", "content": "SYS"}, {"role": "user", "content": "go"}],
               tools=[{"name": "status", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
    req = sdk.responses.requests[0]
    assert req["instructions"] == "SYS" and req["reasoning"] == {"effort": "medium"}
    assert req["store"] is False and "reasoning.encrypted_content" in req["include"] and "temperature" not in req
    assert req["tools"] == [{"type": "function", "name": "status", "description": "d",
                             "parameters": {"type": "object", "properties": {}}}]
    assert req["input"] == [{"role": "user", "content": "go"}]
    assert [t.name for t in r.tool_calls] == ["status"] and r.tool_calls[0].id == "call_1"
    assert r.provider_items[0]["type"] == "reasoning"


def test_reasoning_items_carried_across_turns_through_policy():
    from canary.llm.openai_backend import OpenAIClient
    sdk = FakeSDK([[_rs(1), _fc("call_1", "status", {})],
                   [_rs(2), _fc("call_2", "accuse", {"employee": "e03"})]])
    client = OpenAIClient("gpt-5.5", sdk_client=sdk, reasoning_effort="medium")
    pol = LLMPolicy("openai:gpt-5.5", client=client)
    res = run_episode(FakeEnv(), pol, "x")
    assert [s.tool for s in res.steps] == ["status", "accuse"] and res.correct
    second = sdk.responses.requests[1]["input"]
    types_ = [i.get("type", i.get("role")) for i in second]
    assert types_ == ["user", "reasoning", "function_call", "function_call_output"]
    assert second[1]["encrypted_content"] == "ENC1"
    assert second[3]["call_id"] == "call_1" and json.loads(second[3]["output"])["ok"] is True


def test_policy_passes_effort_and_api_to_openai_client(monkeypatch):
    import canary.agents.llm_policy as lp
    seen = {}
    monkeypatch.setattr(lp, "_get_client", lambda spec, **kw: seen.update(spec=spec, **kw) or object())
    LLMPolicy("openai:gpt-5.5", api="responses").client
    assert seen == {"spec": "openai:gpt-5.5", "reasoning_effort": "medium", "api": "responses"}
    seen.clear()
    LLMPolicy("stub").client
    assert seen == {"spec": "stub"}


def test_play_meta_records_context_effort_api(tmp_path):
    from canary.agents import play
    rec = Recorder(n_status=2)
    out = play.main(["--agent", "openai:gpt-5.5", "--seeds", "0", "--fake", "--context", "window",
                     "--reasoning-effort", "high", "--api", "chat", "--out", str(tmp_path / "r")], client=rec)
    m = json.loads((out / "meta.json").read_text())
    assert (m["context"], m["reasoning_effort"], m["api"], m["max_turns"]) == ("window", "high", "chat", 40)
    out2 = play.main(["--agent", "openai:gpt-5.5", "--seeds", "0", "--fake", "--out", str(tmp_path / "r2")],
                     client=Recorder(n_status=2))
    m2 = json.loads((out2 / "meta.json").read_text())
    assert (m2["context"], m2["reasoning_effort"]) == ("full", "medium") and "Codex" in m2["reasoning_effort_source"]


# ---------------- parity: in-process LLMPolicy vs the real MCP server (in-memory transport, no network)
@pytest.mark.parametrize("tier,seed", [("medium", 0), ("hard", 0)])
def test_inprocess_vs_mcp_parity(tier, seed, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    from mcp import Client
    from canary.agents.frontier.common import episode_prompt
    from canary.env import Env
    from canary.mcp_server import Episode, build_server

    # in-process: what LLMPolicy sends to the client
    env = Env(tier, seed)
    pol = LLMPolicy("stub", client=object())
    pol.reset(env.tools_spec(), env.instruction())
    sent_system, sent_tools = pol._context()[0]["content"], pol.tools

    async def mcp_view():
        async with Client(build_server(Episode(tier, seed))) as c:
            tools = (await c.list_tools()).tools
            return c.instructions, [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                                    for t in tools]

    instructions, mcp_tools = asyncio.run(mcp_view())
    # instruction text: byte-identical
    assert instructions.encode() == env.instruction().encode()
    # the prompt we give Codex/OpenCode == LLMPolicy's system prompt
    assert episode_prompt(tier, seed).encode() == sent_system.encode()
    assert sent_system.startswith(instructions)
    # tool specs: same names, descriptions and JSON schemas, same order
    assert json.dumps(mcp_tools, sort_keys=True) == json.dumps(sent_tools, sort_keys=True)
    assert len(mcp_tools) == 13
