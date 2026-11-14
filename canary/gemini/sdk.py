"""google-genai client factory that is gateway-aware.

    from canary.gemini.sdk import genai_client
    c = genai_client()          # GEMINI_GATEWAY_URL set -> via the Canary Lab gateway, else direct

Env:
  GEMINI_GATEWAY_URL         e.g. http://freighter-mgmt01:8787 (unset = direct to Google with GEMINI_API_KEY)
  GEMINI_GATEWAY_TOKEN       the gateway token (sent as the API key), or
  GEMINI_GATEWAY_TOKEN_FILE  a file holding it (default ~/agent-arena-gemini/.gateway_token; first token,
                             or the line `name token` matching GEMINI_GATEWAY_CLIENT if set)
Raw SDK users must still ledger their calls with canary.gemini.ledger.record(...).
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_TOKEN_FILE = "~/agent-arena-gemini/.gateway_token"
# google-genai 3.x defaults to API v1, where caches.create (and other preview surfaces) 404: pin v1beta.
API_VERSION = "v1beta"


def gateway_url() -> str | None:
    u = (os.environ.get("GEMINI_GATEWAY_URL") or "").strip()
    return u.rstrip("/") or None


def gateway_token() -> str:
    tok = (os.environ.get("GEMINI_GATEWAY_TOKEN") or "").strip()
    if tok:
        return tok
    path = Path(os.path.expanduser(os.environ.get("GEMINI_GATEWAY_TOKEN_FILE") or DEFAULT_TOKEN_FILE))
    if not path.exists():
        from canary.llm import MissingKeyError
        raise MissingKeyError("GEMINI_GATEWAY_URL is set but no GEMINI_GATEWAY_TOKEN or token file "
                              f"({path}) was found")
    want = os.environ.get("GEMINI_GATEWAY_CLIENT")
    for line in path.read_text().splitlines():
        parts = line.strip().split()
        if not parts or parts[0].startswith("#"):
            continue
        name, t = (parts[0], parts[1]) if len(parts) >= 2 else ("default", parts[0])
        if want is None or name == want:
            return t
    from canary.llm import MissingKeyError
    raise MissingKeyError(f"no usable gateway token in {path}")


def _timeout_ms(timeout_s: float | None) -> int:
    if timeout_s is None:
        timeout_s = float(os.environ.get("CANARY_GEMINI_TIMEOUT_S", "600"))
    return int(timeout_s * 1000)


def gateway_http_options(timeout_s: float | None = None) -> dict | None:
    """HttpOptions kwargs for the gateway when GEMINI_GATEWAY_URL is set, else None."""
    url = gateway_url()
    if not url:
        return None
    return {"base_url": url, "timeout": _timeout_ms(timeout_s), "api_version": API_VERSION}


def genai_client(timeout_s: float | None = None, replay_tag: str | None = None):
    """google.genai.Client via the gateway (token as API key) if GEMINI_GATEWAY_URL is set, else direct.
    replay_tag (gateway only): a stable label for one logical run (e.g. a ladder episode), sent as
    x-canary-replay-tag so record/replay can tell identical requests from different episodes apart."""
    from google import genai
    from google.genai import types
    opts = gateway_http_options(timeout_s)
    if opts is not None:
        if replay_tag:
            opts["headers"] = {"x-canary-replay-tag": replay_tag}
        return genai.Client(api_key=gateway_token(), http_options=types.HttpOptions(**opts))
    from canary.llm.base import require_key
    return genai.Client(api_key=require_key("GEMINI_API_KEY"),
                        http_options=types.HttpOptions(timeout=_timeout_ms(timeout_s), api_version=API_VERSION))


def smoke(model: str = "gemini-3.1-flash-lite") -> dict:
    """One ledgered call (via the gateway if GEMINI_GATEWAY_URL is set). Prints no secrets."""
    import socket
    import time
    from .ledger import lab_client, ledger_path
    t0 = time.time()
    c = lab_client(f"gemini:{model}", feature="gateway-smoke")
    r = c.chat([{"role": "user", "content": "Reply with exactly: canary ok"}])
    return {"host": socket.gethostname().split(".")[0], "via": gateway_url() or "direct", "model": model,
            "text": r.text.strip()[:80], "in": r.usage.get("in"), "out": r.usage.get("out"),
            "latency_s": round(time.time() - t0, 2), "ledger": str(ledger_path())}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(smoke(*(sys.argv[1:2] or []))))
