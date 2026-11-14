

def test_no_key_exits_clean(monkeypatch):
    import scripts.key_check as kc
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert kc.tiny() == 0
