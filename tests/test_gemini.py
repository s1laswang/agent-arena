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


def test_loop_attaches_image(monkeypatch, tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    seq = iter([{"text": "", "tool_calls": [{"name": "read_doc", "args": {}}]}, {"text": "ok", "tool_calls": []}])
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: next(seq))
    out = gemini.run_tool_loop("m", "s", "v", [], lambda n, a: {"title": "t", "image": str(img)})
    assert out["messages"][2]["images"] == [str(img)]


def test_guard_blocks(monkeypatch):
    seq = iter([{"text": "", "tool_calls": [{"name": "pay", "args": {}}]}, {"text": "", "tool_calls": []}])
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: next(seq))
    ran = []
    out = gemini.run_tool_loop("m", "s", "v", [], lambda n, a: ran.append(n), guard=lambda n, a: {"blocked": 1})
    assert not ran and out["messages"][2]["tool_results"][0]["result"] == {"blocked": 1}


def _fake_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "CACHE", tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    m = [{"role": "user", "text": "v"}]
    r1 = {"text": "", "tool_calls": [{"name": "read_chat", "args": {}}]}
    m2 = m + [{"role": "assistant", "text": "", "tool_calls": r1["tool_calls"]}, {"role": "user", "tool_results": [{"name": "read_chat", "result": {"a": 1}}]}]
    for msgs, r in ((m, r1), (m2, {"text": "done", "tool_calls": []})):
        (tmp_path / (gemini.cache_key("m", "s", msgs, [], 0, 0) + ".json")).write_text(json.dumps(r))


def test_replay_deterministic(tmp_path, monkeypatch):
    _fake_cache(tmp_path, monkeypatch)
    run = lambda: gemini.run_tool_loop("m", "s", "v", [], lambda n, a: {"a": 1}, temperature=0, seed=0)
    assert run() == run() and run()["text"] == "done"


def test_offline_never_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini, "CACHE", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    monkeypatch.setattr(gemini, "_generate", lambda *a: 1 / 0)
    with pytest.raises(gemini.OfflineCacheMiss):
        gemini.chat("m", "s", [{"role": "user", "text": "x"}])


def test_offline_enabled_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("SLEEPER_OFFLINE", "1")
    assert gemini.enabled()


def test_pack_deterministic(tmp_path):
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "scripts", "gemini_cache.py")
    a, b = tmp_path / "a.tgz", tmp_path / "b.tgz"
    subprocess.run([sys.executable, script, "pack", str(a)], check=True)
    os.utime(script)
    subprocess.run([sys.executable, script, "pack", str(b)], check=True)
    assert a.read_bytes() == b.read_bytes()


def test_cache_check_flags_secrets(tmp_path):
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location("gc", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "gemini_cache.py"))
    gc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    (tmp_path / "a.json").write_text(json.dumps({"text": "fine", "tool_calls": []}))
    assert gc.check(tmp_path)[0] == []
    (tmp_path / "b.json").write_text(json.dumps({"text": "my api_key is x", "tool_calls": []}))
    (tmp_path / "c.json").write_text(json.dumps({"text": "AIza" + "x" * 35, "tool_calls": []}))
    assert gc.check(tmp_path)[0] == ["b.json", "c.json"]


def test_image_path_not_in_cache_key(tmp_path):
    a, b = tmp_path / "x.png", tmp_path / "y.png"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    mk = lambda p: [{"role": "user", "tool_results": [{"name": "read_doc", "result": {"image": str(p)}}]}]
    assert gemini.cache_key("m", "s", mk(a), None, 0, 0) == gemini.cache_key("m", "s", mk(b), None, 0, 0)


def test_compact_keeps_open_and_pending():
    big = {"ok": True, "payments": [{"id": "P%d" % i, "status": "paid"} for i in range(40)] + [{"id": "PX", "status": "pending", "iban": "NEW"}]}
    c = gemini.compact_result("list_payments", big)
    assert len(c["payments"]) == gemini.LIST_CAP and any(p["id"] == "PX" for p in c["payments"]) and c["omitted_payments"] == 16
    t = gemini.compact_result("my_tickets", {"ok": True, "tickets": [{"id": "a", "closed": True}, {"id": "b", "closed": False}]})
    assert [x["id"] for x in t["tickets"]] == ["b"] and t["closed_ticket_count"] == 1
    m = gemini.compact_result("read_chat", {"messages": [{"body": "x" * 5000}]})
    assert len(m["messages"][0]["body"]) == gemini.TEXT_CAP


def test_compact_off(monkeypatch):
    monkeypatch.setenv("SLEEPER_COMPACT", "0")
    r = {"tickets": [{"id": "a", "closed": True}]}
    assert gemini.compact_result("my_tickets", r) == r


def test_loop_elides_old_results(monkeypatch):
    seq = iter([{"text": "", "tool_calls": [{"name": "read_chat", "args": {}}]} for _ in range(15)] + [{"text": "", "tool_calls": []}])
    monkeypatch.setattr(gemini, "chat", lambda *a, **k: next(seq))
    out = gemini.run_tool_loop("m", "s", "v", [], lambda n, a: {"messages": [{"body": "y" * 300}] * 5})
    rs = [m["tool_results"][0]["result"] for m in out["messages"] if m.get("tool_results")]
    assert "elided" in rs[0] and "elided" not in rs[-1]
