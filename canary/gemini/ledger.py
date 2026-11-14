"""Gemini usage ledger: one JSONL line per Gemini API call, from every feature, host and process.

Record schema (stable; the dashboard and the submission numbers read it):
    {ts, feature, model, kind, in, out, thinking, cached, latency_s, cost_usd, ok, error,
     run_id, host, pid, meta}
kind: generate | embed | batch | cache | tts | live | count
`in`/`out`/`thinking`/`cached` are token counts (`out` excludes thinking; cost counts both).

Path: $CANARY_GEMINI_LEDGER (a file) or data/gemini/ledger/<host>-<pid>.jsonl (one file per
process, so concurrent writers never interleave). Readers glob the directory.
Never records prompts, keys or secrets: counts, timings and labels only.
"""
from __future__ import annotations

import glob
import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Iterable

from canary.llm import LLMClient, get_client
from canary.llm.pricing import cost

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = Path(os.environ.get("CANARY_GEMINI_LEDGER_DIR", ROOT / "data" / "gemini" / "ledger"))


def ledger_path() -> Path:
    p = os.environ.get("CANARY_GEMINI_LEDGER")
    if p:
        return Path(p)
    return LEDGER_DIR / f"{socket.gethostname().split('.')[0]}-{os.getpid()}.jsonl"


def _n(obj: Any, attr: str) -> int:
    if obj is None:
        return 0
    v = obj.get(attr, 0) if isinstance(obj, dict) else getattr(obj, attr, 0)
    return v if isinstance(v, int) else 0


def record(feature: str, model: str, kind: str = "generate", usage: Any = None, latency_s: float = 0.0,
           ok: bool = True, error: str = "", run_id: str = "", meta: dict | None = None,
           tokens: dict | None = None) -> dict:
    """Append one ledger row. `usage` = a google-genai usage_metadata (or dict with the same fields);
    or pass `tokens={"in","out","thinking","cached"}` directly."""
    if tokens is None:
        tokens = {"in": _n(usage, "prompt_token_count"), "out": _n(usage, "candidates_token_count"),
                  "thinking": _n(usage, "thoughts_token_count"),
                  "cached": _n(usage, "cached_content_token_count")}
    tin, tout = tokens.get("in", 0), tokens.get("out", 0)
    thinking, cached = tokens.get("thinking", 0), tokens.get("cached", 0)
    c = cost(model, tin, tout + thinking, cached)
    usd = c.get("cost_usd_est", c.get("cost_usd", 0.0))
    if kind == "batch":
        usd *= 0.5  # Batch API list price is 50% of interactive
    row = {"ts": round(time.time(), 3), "feature": feature, "model": model, "kind": kind,
           "in": tin, "out": tout, "thinking": thinking, "cached": cached,
           "latency_s": round(latency_s, 3), "cost_usd": round(usd, 6),
           "cost_unknown": bool(c.get("cost_unknown", False)), "ok": ok, "error": error[:200],
           "run_id": run_id or os.environ.get("CANARY_GEMINI_RUN_ID", ""),
           "host": socket.gethostname().split(".")[0], "pid": os.getpid(), "meta": meta or {}}
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def read_ledger(paths: Iterable[str | Path] | None = None) -> list[dict]:
    files = [str(p) for p in paths] if paths else sorted(glob.glob(str(LEDGER_DIR / "**" / "*.jsonl"), recursive=True))
    rows = []
    for fp in files:
        with open(fp) as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return rows


class LedgeredClient(LLMClient):
    """Wraps any canary.llm client; delegates chat() and writes one ledger row per call (incl. failures)."""

    def __init__(self, inner: LLMClient, feature: str, run_id: str = "", meta: dict | None = None):
        super().__init__(model=inner.model, max_retries=0)
        self.inner, self.feature, self.run_id, self.meta = inner, feature, run_id, meta or {}
        self.provider = inner.provider

    def __getattr__(self, name):  # settings(), finish_reasons, thinking_level, ... of the inner client
        return getattr(self.__dict__["inner"], name)

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, max_tokens=None, seed=None):
        t0 = time.time()
        try:
            r = self.inner.chat(messages, tools=tools, temperature=temperature, response_schema=response_schema,
                                max_tokens=max_tokens, seed=seed)
        except Exception as e:  # noqa: BLE001
            record(self.feature, self.inner.model, usage=None, latency_s=time.time() - t0, ok=False,
                   error=f"{type(e).__name__}: {e}", run_id=self.run_id, meta=self.meta)
            raise
        um = getattr(r.raw, "usage_metadata", None) if r.raw is not None else None
        if um is not None:
            record(self.feature, self.inner.model, usage=um, latency_s=time.time() - t0,
                   run_id=self.run_id, meta=self.meta)
        else:  # stub / non-Gemini: fall back to the normalised usage dict
            record(self.feature, self.inner.model, latency_s=time.time() - t0, run_id=self.run_id,
                   meta=self.meta, tokens={"in": r.usage.get("in", 0), "out": r.usage.get("out", 0)})
        for k in ("in", "out", "cost_usd"):
            self.total_usage[k] += r.usage.get(k, 0) or 0
        self.total_usage["calls"] += 1
        return r


def lab_client(spec: str, feature: str, run_id: str = "", meta: dict | None = None, **kw) -> LedgeredClient:
    """get_client(spec, **kw) wrapped in the ledger. spec: 'gemini:<model>' (or 'stub' in tests).
    Gemini specs get a gateway-aware SDK client (canary.gemini.sdk.genai_client): with GEMINI_GATEWAY_URL set,
    every call goes through the Canary Lab gateway; otherwise direct with GEMINI_API_KEY."""
    if spec.partition(":")[0] == "gemini" and kw.get("sdk_client") is None:
        from .sdk import genai_client
        kw["sdk_client"] = genai_client()
    return LedgeredClient(get_client(spec, **kw), feature=feature, run_id=run_id, meta=meta)
