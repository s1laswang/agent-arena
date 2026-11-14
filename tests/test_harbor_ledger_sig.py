"""Pin Harbor ledger signing to canary.mcp_server and harbor/template/tests/test.sh.

A valid signature verifies. A tampered body does not. A missing key does not.
The MAC is the same HMAC-SHA256 over canonical JSON that test.sh recomputes.
"""
import hashlib
import hmac
import json
from pathlib import Path

from canary.mcp_server import SIG_ALG, ledger_canonical, sign_ledger, verify_ledger

ROOT = Path(__file__).resolve().parents[1]
TEST_SH = (ROOT / "harbor/template/tests/test.sh").read_text(encoding="utf-8")
KEY = "test-ledger-key"
PAYLOAD = {"score": 0.5, "done": True, "ledger": [{"tool": "accuse", "ok": True}]}


def verifier_mac(payload: dict, key: bytes) -> str:
    """The check in harbor/template/tests/test.sh, copied so the two stay pinned."""
    body = {k: v for k, v in payload.items() if k != "sig"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def test_valid_signature():
    signed = sign_ledger(PAYLOAD, KEY)
    assert signed["sig"]["alg"] == SIG_ALG
    assert verify_ledger(signed, KEY)
    assert verify_ledger(signed, KEY.encode())
    assert signed["sig"]["mac"] == verifier_mac(signed, KEY.encode())
    assert ledger_canonical(signed) == ledger_canonical(PAYLOAD)
    assert 'separators=(",", ":")' in TEST_SH
    assert "HMAC-SHA256" in TEST_SH


def test_tampered_body():
    signed = sign_ledger(PAYLOAD, KEY)
    signed["score"] = 1.0
    assert not verify_ledger(signed, KEY)
    assert signed["sig"]["mac"] != verifier_mac(signed, KEY.encode())


def test_missing_key():
    signed = sign_ledger(PAYLOAD, KEY)
    assert not verify_ledger(signed, "")
    assert not verify_ledger(signed, b"")
    assert not verify_ledger(signed, None)
    assert "no ledger signing key" in TEST_SH
