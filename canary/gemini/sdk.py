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
    return {"base_url": url, "timeout": _timeout_ms(timeout_s)}


def genai_client(timeout_s: float | None = None):
    """google.genai.Client via the gateway (token as API key) if GEMINI_GATEWAY_URL is set, else direct."""
    from google import genai
    from google.genai import types
    opts = gateway_http_options(timeout_s)
    if opts is not None:
        return genai.Client(api_key=gateway_token(), http_options=types.HttpOptions(**opts))
    from canary.llm.base import require_key
    return genai.Client(api_key=require_key("GEMINI_API_KEY"),
                        http_options=types.HttpOptions(timeout=_timeout_ms(timeout_s)))
