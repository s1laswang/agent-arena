import json
import os
from types import SimpleNamespace as NS

import pytest

from canary.llm import (LLMError, MissingKeyError, StubClient, get_client, register_script,
                        schema_example)
from canary.llm import check
from canary.llm.base import load_env

load_env()

TOOLS = [{"name": "status", "description": "get status", "input_schema": {"type": "object", "properties": {}}},
         {"name": "accuse", "description": "accuse", "parameters": {
             "type": "object", "properties": {"employee_id": {"type": "string"}}, "required": ["employee_id"]}}]


# ---------- stub ----------
def test_stub_script_loop():
    c = StubClient(script=[{"tool_calls": [{"name": "status", "args": {}}]}, {"text": "done"}])
    r1 = c.chat([{"role": "user", "content": "go"}], tools=TOOLS)
    assert r1.tool_calls[0].name == "status" and r1.tool_calls[0].id
    msgs = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": r1.tool_calls[0].id, "name": "status", "args": {}}]},
            {"role": "tool", "tool_call_id": r1.tool_calls[0].id, "content": "{}"}]
    assert c.chat(msgs).text == "done"
    assert len(c.calls) == 2 and c.calls[0]["tools"][1]["schema"]["required"] == ["employee_id"]
    assert c.total_usage["calls"] == 2


def test_stub_deterministic_and_named_script():
    a = get_client("stub").chat([{"role": "user", "content": "hi"}]).text
    assert a == get_client("stub").chat([{"role": "user", "content": "hi"}]).text
    register_script("t1", [{"json": {"a": 1}}])
    c = get_client("stub:t1")
    assert json.loads(c.chat([{"role": "user", "content": "x"}]).text) == {"a": 1}
    with pytest.raises(LLMError):
        get_client("stub:nope")
    with pytest.raises(LLMError):
        get_client("bogus:x")


def test_schema_example():
    s = {"type": "object", "properties": {
        "s": {"type": "string"}, "n": {"type": "number"}, "i": {"type": "integer", "minimum": 3},
        "b": {"type": "boolean"}, "e": {"enum": ["x", "y"]},
        "a": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "o": {"type": "object", "properties": {"k": {"type": "string"}}}}}
    v = schema_example(s)
    assert v == {"s": "stub", "n": 0.0, "i": 3, "b": False, "e": "x", "a": ["stub"], "o": {"k": "stub"}}
    r = StubClient().chat([{"role": "user", "content": "q"}], response_schema=s)
    assert json.loads(r.text) == v


# ---------- retry ----------
class RateLimit(Exception):
    status_code = 429


def test_retry_backoff():
    sleeps = []
    c = StubClient(script=[RateLimit(), RateLimit(), {"text": "ok"}], sleep=sleeps.append)
    assert c.chat([{"role": "user", "content": "x"}]).text == "ok"
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]


def test_retry_gives_up_and_non_retryable():
    c = StubClient(script=[RateLimit()] * 6, sleep=lambda s: None)
    with pytest.raises(RateLimit):
        c.chat([{"role": "user", "content": "x"}])
    assert len(c.calls) == 6
    c = StubClient(script=[ValueError("bad")], sleep=lambda s: None)
    with pytest.raises(ValueError):
        c.chat([{"role": "user", "content": "x"}])
    assert len(c.calls) == 1


# ---------- missing keys ----------
def test_missing_keys(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(MissingKeyError, match="OPENAI_API_KEY"):
        get_client("openai:gpt-4o-mini")
    with pytest.raises(MissingKeyError, match="GEMINI_API_KEY"):
        get_client("gemini")


# ---------- openai (mocked SDK) ----------
class FakeOpenAI:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **req):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def oa_resp(content=None, tool_calls=None, pin=10, pout=5):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))],
              usage=NS(prompt_tokens=pin, completion_tokens=pout))


def test_openai_conversion_and_parsing():
    from canary.llm.openai_backend import OpenAIClient
    tc = NS(id="c1", function=NS(name="accuse", arguments='{"employee_id": "e7"}'))
    fake = FakeOpenAI([oa_resp(tool_calls=[tc]), oa_resp(content='{"x": 1}')])
    c = OpenAIClient("gpt-4o-mini", sdk_client=fake)
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c0", "name": "status", "args": {}}]},
            {"role": "tool", "tool_call_id": "c0", "name": "status", "content": '{"day": 1}'}]
    r = c.chat(msgs, tools=TOOLS, temperature=0.3, seed=7)
    req = fake.requests[0]
    assert req["temperature"] == 0.3 and req["seed"] == 7
    assert req["messages"][2]["tool_calls"][0]["function"] == {"name": "status", "arguments": "{}"}
    assert req["messages"][3] == {"role": "tool", "tool_call_id": "c0", "content": '{"day": 1}'}
    assert req["tools"][1]["function"]["parameters"]["required"] == ["employee_id"]
    assert r.tool_calls[0].args == {"employee_id": "e7"} and r.tool_calls[0].id == "c1"
    assert r.usage["in"] == 10 and r.usage["cost_usd"] > 0
    c.chat([{"role": "user", "content": "q"}], response_schema={"type": "object", "properties": {"x": {"type": "integer"}}})
    assert fake.requests[1]["response_format"]["type"] == "json_schema"
    assert c.total_usage["in"] == 20


def test_openai_temperature_handling():
    from canary.llm.openai_backend import OpenAIClient
    fake = FakeOpenAI([oa_resp(content="hi")])
    OpenAIClient("gpt-5-mini", sdk_client=fake, api="chat").chat([{"role": "user", "content": "q"}], temperature=0.5)
    assert "temperature" not in fake.requests[0]
    err = Exception("Unsupported value: 'temperature' does not support 0.0")
    err.status_code = 400
    fake = FakeOpenAI([err, oa_resp(content="hi")])
    c = OpenAIClient("some-new-model", sdk_client=fake)
    r = c.chat([{"role": "user", "content": "q"}])
    assert r.text == "hi" and "temperature" not in fake.requests[1]
    assert r.usage.get("cost_unknown") is True and r.usage["cost_usd"] == 0.0


# ---------- gemini (mocked transport) ----------
def test_gemini_conversion_and_parsing(monkeypatch):
    from google.genai import types
    from canary.llm.gemini_backend import GeminiClient
    monkeypatch.setenv("CANARY_GEMINI_THINKING", "512")
    seen = {}
    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[
            types.Part(text="thinking...", thought=True),
            types.Part(text="I will accuse."),
            types.Part(function_call=types.FunctionCall(name="accuse", args={"employee_id": "e3"}))]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20))

    def fake_generate(**req):
        seen.update(req)
        return resp
    sdk = NS(models=NS(generate_content=fake_generate))
    c = GeminiClient("gemini-2.5-flash", sdk_client=sdk)  # legacy 2.5 path: thinking_budget + temperature
    assert c.model == "gemini-2.5-flash"
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c0", "name": "status", "args": {}}]},
            {"role": "tool", "tool_call_id": "c0", "content": '{"day": 1}'}]
    r = c.chat(msgs, tools=TOOLS, temperature=0.2, seed=3, max_tokens=99)
    cfg, contents = seen["config"], seen["contents"]
    assert cfg.system_instruction == "sys" and cfg.temperature == 0.2 and cfg.seed == 3
    assert cfg.max_output_tokens == 99 and cfg.thinking_config.thinking_budget == 512
    fds = cfg.tools[0].function_declarations
    assert [f.name for f in fds] == ["status", "accuse"] and fds[1].parameters_json_schema["required"] == ["employee_id"]
    assert [x.role for x in contents] == ["user", "model", "user"]
    assert contents[1].parts[0].function_call.name == "status"
    fr = contents[2].parts[0].function_response
    assert fr.name == "status" and fr.response == {"day": 1}
    assert r.text == "I will accuse."
    assert r.tool_calls[0].name == "accuse" and r.tool_calls[0].args == {"employee_id": "e3"}
    assert r.usage["in"] == 100 and r.usage["out"] == 20 and r.usage["cost_usd"] > 0


def test_gemini_schema_and_duck_typed():
    from canary.llm.gemini_backend import GeminiClient
    seen = {}
    duck = NS(candidates=[NS(content=NS(parts=[NS(text='{"a": "b"}', function_call=None, thought=None)]))],
              usage_metadata=None)
    sdk = NS(models=NS(generate_content=lambda **req: seen.update(req) or duck))
    c = GeminiClient("gemini-2.5-pro", sdk_client=sdk)
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    r = c.chat([{"role": "user", "content": "q"}], response_schema=schema)
    assert seen["config"].response_mime_type == "application/json"
    assert seen["config"].response_json_schema == schema
    assert json.loads(r.text) == {"a": "b"} and r.usage["in"] == 0


# ---------- check.py ----------
def test_check_stub(capsys):
    assert check.main(["stub"]) == 0
    assert capsys.readouterr().out.startswith("OK stub")


def test_check_missing_key(monkeypatch, capsys):
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert check.main(["gemini"]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err


# ---------- live (opt-in) ----------
@pytest.mark.skipif(not (os.environ.get("OPENAI_API_KEY") and os.environ.get("CANARY_LIVE") == "1"),
                    reason="live test: set OPENAI_API_KEY and CANARY_LIVE=1")
def test_openai_live():
    c = get_client(os.environ.get("CANARY_LIVE_OPENAI_MODEL", "openai:gpt-4o-mini"))
    r = c.chat([{"role": "user", "content": "Call the status tool."}], tools=TOOLS)
    assert r.tool_calls and r.tool_calls[0].name == "status"
    assert c.total_usage["in"] > 0


def test_openai_default_is_frontier(monkeypatch):
    from canary.llm import default_openai_model
    monkeypatch.delenv("CANARY_OPENAI_MODEL", raising=False)
    assert default_openai_model() == "gpt-5.5"
    monkeypatch.setenv("CANARY_OPENAI_MODEL", "gpt-5.6-sol")
    assert default_openai_model() == "gpt-5.6-sol"
