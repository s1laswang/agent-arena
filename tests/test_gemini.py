import json

import pytest

from agents import gemini


def test_cache_hit_no_key(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "CACHE", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    msgs = [{"role": "user", "text": "hi"}]
    key = gemini.cache_key("m", "sys", msgs, None, 0, 1)
    (tmp_path / (key + ".json")).write_text(json.dumps({"text": "yo", "tool_calls": []}))
    assert gemini.chat("m", "sys", msgs, None, 0, 1) == {"text": "yo", "tool_calls": []}


def test_no_key_miss_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "CACHE", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert not gemini.enabled()
    with pytest.raises(gemini.GeminiUnavailable):
        gemini.chat("m", "s", [{"role": "user", "text": "x"}])


def test_tool_conversion():
    d = gemini.to_declarations([{"name": "pay", "description": "d", "parameters": {"type": "object", "properties": {"a": {"type": "number"}}}}])
    assert d[0].name == "pay" and d[0].parameters_json_schema["properties"]["a"]["type"] == "number"


def test_tool_loop(monkeypatch):
    seq = iter([
        {"text": "", "tool_calls": [{"name": "read_chat", "args": {}}]},
        {"text": "", "tool_calls": [{"name": "end_turn", "args": {}}]},
    ])
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: next(seq))
    seen = []
    out = gemini.run_tool_loop("m", "s", "v", [], lambda n, a: seen.append(n) or {"ok": 1})
    assert seen == ["read_chat", "end_turn"] and len(out["messages"]) == 5


def test_contents_roundtrip():
    c = gemini._contents([{"role": "assistant", "tool_calls": [{"name": "x", "args": {"q": 1}}]}, {"role": "user", "tool_results": [{"name": "x", "result": {"a": 1}}]}])
    assert c[0].role == "model" and c[1].parts[0].function_response.name == "x"
