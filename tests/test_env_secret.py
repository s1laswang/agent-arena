import canary.world as W


def test_judge_seed_never_public_and_fresh_per_process(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_WORLD_SECRET", raising=False)
    monkeypatch.setattr(W, "Path", lambda *_a, **_k: tmp_path / "nope" / "x" / "y" / "z")
    s = 900_003
    import hmac, hashlib
    public = int.from_bytes(hmac.new(b"public", f"easy:{s}".encode(), hashlib.sha256).digest()[:8], "big")
    monkeypatch.setattr(W, "_PROC_SECRET", None)
    a = W.world_seed("easy", s)
    assert a != public
    assert W.world_seed("easy", s) == a           # stable within a process
    monkeypatch.setattr(W, "_PROC_SECRET", None)  # "server restart"
    assert W.world_seed("easy", s) != a
    assert W.world_seed("easy", 5) == int.from_bytes(hmac.new(b"public", b"easy:5", hashlib.sha256).digest()[:8], "big")
