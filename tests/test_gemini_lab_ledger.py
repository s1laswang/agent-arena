from canary.gemini import lab_client, read_ledger


def test_ledgered_stub_writes_rows(tmp_path, monkeypatch):
    led = tmp_path / "l.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))
    c = lab_client("stub", feature="test")
    c.chat([{"role": "user", "content": "hi"}])
    c.chat([{"role": "user", "content": "hi"}])
    rows = read_ledger([led])
    assert len(rows) == 2 and all(r["feature"] == "test" and r["ok"] for r in rows)
    assert c.total_usage["calls"] == 2
