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


def test_temp_defaults(monkeypatch):
    monkeypatch.delenv("SLEEPER_TEMP_STAFF", raising=False)
    assert gemini.temp_for("sleeper") == 0.9 and gemini.temp_for("staff") == 0.7
    monkeypatch.setenv("SLEEPER_TEMP_STAFF", "0.2")
    assert gemini.temp_for("staff") == 0.2


def test_log_callback(monkeypatch):
    seq = iter([{"text": "t", "tool_calls": [{"name": "end_turn", "args": {}}]}])
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: next(seq))
    ev = []
    gemini.run_tool_loop("m", "s", "v", [], lambda n, a: {}, log=ev.append)
    assert [e["role"] for e in ev] == ["model", "tool"]


def test_image_hash_and_part(tmp_path):
    a = tmp_path / "a.png"
    a.write_bytes(b"\x89PNGone")
    k1 = gemini.cache_key("m", "s", [{"role": "user", "images": [str(a)]}], None, 0, 0)
    a.write_bytes(b"\x89PNGtwo")
    k2 = gemini.cache_key("m", "s", [{"role": "user", "images": [str(a)]}], None, 0, 0)
    assert k1 != k2
    c = gemini._contents([{"role": "user", "text": "x", "images": [str(a)]}])
    assert c[0].parts[1].inline_data.mime_type == "image/png"


def test_estimate():
    assert gemini.usage()["est_calls_per_day"] == 240
