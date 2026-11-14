"""Failure Atlas, Gemini layer: every raw SDK call the atlas makes (generate with structured output, count_tokens,
explicit context caching, multimodal, embeddings, Batch API), each one written to the usage ledger and to an
offline response cache so the whole atlas replays without a key.

Response cache: results/gemini/atlas_cache/<sha256>.json.gz, key = sha256(op + model + canonical request).
Requests that use an explicit context cache are keyed by the corpus hash, never by the (ephemeral) cache name.
    ops = AtlasOps(replay=True)      # cache miss -> ReplayMiss (callers fall back deterministically)
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any

from .ledger import record

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "results" / "gemini" / "atlas_cache"
FEATURE = "atlas"
# long-context calls on gemini-4-carbon (~800k tokens + thinking) can take well over 10 minutes
TIMEOUT_S = float(os.environ.get("CANARY_ATLAS_TIMEOUT_S", "2400"))


class ReplayMiss(RuntimeError):
    pass


def sdk_client():
    """google-genai client on API v1beta (google-genai 3.x defaults to v1, where cachedContents is a bare 404).
    Goes through the Canary Lab gateway (G1's canary.gemini.sdk) when GEMINI_GATEWAY_URL is set."""
    from google import genai
    from google.genai import types
    try:
        from canary.gemini.sdk import gateway_http_options, gateway_token  # type: ignore
        opts = gateway_http_options(TIMEOUT_S)
        if opts:
            return genai.Client(api_key=gateway_token(), http_options=types.HttpOptions(**opts, api_version="v1beta"))
    except ImportError:
        pass
    from canary.llm.base import require_key
    return genai.Client(api_key=require_key("GEMINI_API_KEY"),
                        http_options=types.HttpOptions(timeout=int(TIMEOUT_S * 1000), api_version="v1beta"))


def _usage_dict(um: Any) -> dict:
    def g(a):
        v = getattr(um, a, None) if um is not None else None
        return v if isinstance(v, int) else 0
    return {"prompt_token_count": g("prompt_token_count"), "candidates_token_count": g("candidates_token_count"),
            "thoughts_token_count": g("thoughts_token_count"),
            "cached_content_token_count": g("cached_content_token_count")}


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def text_parts(contents: list) -> list:
    """Canonical, hashable form of contents (str | {'image': bytes, 'mime': str})."""
    out = []
    for c in contents:
        if isinstance(c, dict) and "image" in c:
            out.append({"image_sha": hashlib.sha256(c["image"]).hexdigest(), "mime": c.get("mime", "image/png")})
        else:
            out.append(str(c))
    return out


class AtlasOps:
    def __init__(self, client: Any = None, replay: bool = False, cache_dir: Path | None = None, run_id: str = "",
                 record_responses: bool = True, max_retries: int = 5):
        self._client = client
        self.replay = replay
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.run_id = run_id or f"atlas-{time.strftime('%Y%m%d-%H%M%S')}"
        self.record_responses = record_responses
        self.max_retries = max_retries
        self.stats = {"calls": 0, "replayed": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0,
                      "by_kind": {}}
        self.source_run_ids: set[str] = set()

    # ------------------------------------------------------------------ plumbing
    @property
    def client(self):
        if self._client is None:
            if self.replay:
                raise ReplayMiss("replay mode: no live client")
            self._client = sdk_client()
        return self._client

    def _key(self, op: str, model: str, payload: Any) -> str:
        return hashlib.sha256(f"{op}\n{model}\n{_canon(payload)}".encode()).hexdigest()

    def _load(self, key: str) -> dict | None:
        p = self.cache_dir / f"{key}.json.gz"
        if p.exists():
            d = json.loads(gzip.decompress(p.read_bytes()))
            self.stats["replayed"] += 1
            if d.get("run_id"):
                self.source_run_ids.add(d["run_id"])
            return d
        return None

    def _store(self, key: str, d: dict) -> None:
        if not self.record_responses:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        d = {**d, "run_id": self.run_id, "ts": round(time.time(), 1)}
        (self.cache_dir / f"{key}.json.gz").write_bytes(gzip.compress(_canon(d).encode(), mtime=0))

    def _cached(self, op: str, model: str, payload: Any, fn) -> dict:
        key = self._key(op, model, payload)
        hit = self._load(key)
        if hit is not None:
            return hit
        if self.replay:
            raise ReplayMiss(f"{op}/{model}: no recorded response {key[:12]}")
        d = fn()
        self._store(key, d)
        self.source_run_ids.add(self.run_id)
        return d

    def _ledger(self, model: str, kind: str, usage: Any, t0: float, ok: bool = True, error: str = "",
                meta: dict | None = None, tokens: dict | None = None) -> dict:
        row = record(FEATURE, model, kind=kind, usage=usage, latency_s=time.time() - t0, ok=ok, error=error,
                     run_id=self.run_id, meta=meta or {}, tokens=tokens)
        self.stats["calls"] += 1
        for k in ("in", "out", "thinking", "cached"):
            self.stats[k] += row[k]
        self.stats["cost_usd"] += row["cost_usd"]
        self.stats["by_kind"][kind] = self.stats["by_kind"].get(kind, 0) + 1
        return row

    def _retry(self, fn, model: str, kind: str, meta: dict):
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            t0 = time.time()
            try:
                return fn(), t0
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {str(e)[:180]}"
                self._ledger(model, kind, None, t0, ok=False, error=msg, meta=meta)
                transient = any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "500", "UNAVAILABLE",
                                                   "DEADLINE", "Timeout", "timed out", "ServerError"))
                timeout = any(s in msg for s in ("Timeout", "timed out", "DEADLINE"))
                if not transient or attempt == self.max_retries or (timeout and attempt >= 1):
                    raise
                time.sleep(min(60.0, delay) * (0.5 + random.random()))
                delay *= 2

    # ------------------------------------------------------------------ operations
    def generate(self, model: str, contents: list, schema: dict | None = None, system: str | None = None,
                 cache_name: str | None = None, cache_key: str | None = None, thinking_level: str | None = None,
                 max_output_tokens: int = 32768, tag: str = "") -> dict:
        """Structured (or plain) generateContent. contents: [str | {'image': bytes, 'mime': ...}].
        cache_name: an explicit context cache; cache_key: the corpus hash it stands for (part of the request key).
        Returns {'text', 'usage'}."""
        payload = {"contents": text_parts(contents), "schema": schema, "system": system, "cache": cache_key,
                   "thinking": thinking_level, "max": max_output_tokens}
        meta = {"op": tag or "generate", "explicit_cache": bool(cache_name)}

        def call():
            from google.genai import types
            parts = []
            for c in contents:
                if isinstance(c, dict) and "image" in c:
                    parts.append(types.Part.from_bytes(data=c["image"], mime_type=c.get("mime", "image/png")))
                else:
                    parts.append(types.Part(text=str(c)))
            cfg: dict = {"max_output_tokens": max_output_tokens}
            if schema is not None:
                cfg["response_mime_type"] = "application/json"
                cfg["response_json_schema"] = schema
            cn = cache_name() if callable(cache_name) else cache_name  # lazy: created on the first real miss
            if system and not cn:
                cfg["system_instruction"] = system
            if cn:
                cfg["cached_content"] = cn
            if thinking_level:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level.upper())
            r, t0 = self._retry(lambda: self.client.models.generate_content(
                model=model, contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(**cfg)), model, "generate", meta)
            um = getattr(r, "usage_metadata", None)
            self._ledger(model, "generate", um, t0, meta=meta)
            text = r.text if getattr(r, "text", None) is not None else ""
            return {"text": text, "usage": _usage_dict(um)}
        return self._cached("generate", model, payload, call)

    def count_tokens(self, model: str, text: str) -> int:
        payload = {"sha": hashlib.sha256(text.encode()).hexdigest()}

        def call():
            r, t0 = self._retry(lambda: self.client.models.count_tokens(model=model, contents=text), model, "count",
                                {"op": "count_tokens"})
            n = int(getattr(r, "total_tokens", 0) or 0)
            self._ledger(model, "count", None, t0, meta={"op": "count_tokens", "counted": n},
                         tokens={"in": 0, "out": 0})
            return {"total_tokens": n}
        return int(self._cached("count", model, payload, call)["total_tokens"])

    def recorded_cache_tokens(self, model: str, corpus: str, system: str) -> int:
        key = self._key("cache_meta", model, {"corpus_sha": hashlib.sha256(corpus.encode()).hexdigest(), "system": system})
        p = self.cache_dir / f"{key}.json.gz"
        return int(json.loads(gzip.decompress(p.read_bytes())).get("tokens", 0)) if p.exists() else 0

    def create_cache(self, model: str, corpus: str, system: str, ttl_s: int = 3600) -> tuple[str | None, int]:
        """Explicit context cache of the corpus. Returns (cache_name, cached_token_count). Never replayed: in
        replay mode returns (None, recorded count) and the questions resolve from the response cache."""
        key_payload = {"corpus_sha": hashlib.sha256(corpus.encode()).hexdigest(), "system": system}
        key = self._key("cache_meta", model, key_payload)
        hit = self._load(key)
        if self.replay:
            return None, int((hit or {}).get("tokens", 0))
        from google.genai import types
        meta = {"op": "caches.create", "ttl_s": ttl_s}
        r, t0 = self._retry(lambda: self.client.caches.create(model=model, config=types.CreateCachedContentConfig(
            contents=[types.Content(role="user", parts=[types.Part(text=corpus)])], system_instruction=system,
            ttl=f"{ttl_s}s", display_name="canary-atlas-corpus")), model, "cache", meta)
        um = getattr(r, "usage_metadata", None)
        n = int(getattr(um, "total_token_count", 0) or 0)
        # cache creation bills the corpus once as input
        self._ledger(model, "cache", None, t0, meta={**meta, "cache_tokens": n}, tokens={"in": n, "out": 0})
        self._store(key, {"tokens": n})
        return r.name, n

    def delete_cache(self, name: str | None) -> None:
        if name and not self.replay:
            try:
                self.client.caches.delete(name=name)
            except Exception:  # noqa: BLE001
                pass

    def embed(self, texts: list[str], model: str = "gemini-embedding-2", dim: int = 256,
              task_type: str = "CLUSTERING") -> list[list[float]]:
        payload = {"texts": texts, "dim": dim, "task": task_type}

        def call():
            from google.genai import types
            vecs: list[list[float]] = []
            for i in range(0, len(texts), 100):
                chunk = texts[i:i + 100]
                r, t0 = self._retry(lambda: self.client.models.embed_content(
                    model=model, contents=chunk,
                    config=types.EmbedContentConfig(output_dimensionality=dim, task_type=task_type)),
                    model, "embed", {"op": "embed"})
                n_tok = sum(max(1, len(t) // 4) for t in chunk)  # API returns no usage for embeddings; estimate
                self._ledger(model, "embed", None, t0, meta={"op": "embed", "n": len(chunk), "tokens_estimated": True},
                             tokens={"in": n_tok, "out": 0})
                vecs += [[round(x, 5) for x in e.values] for e in r.embeddings]
            return {"vectors": vecs}
        return self._cached("embed", model, payload, call)["vectors"]

    # ------------------------------------------------------------------ Batch API
    def batch_generate(self, model: str, prompts: list[str], schema: dict | None, system: str | None = None,
                       poll_s: float = 20.0, timeout_s: float = 3600.0, state_file: Path | None = None,
                       on_poll=None) -> list[dict | None]:
        """Batch API (inline requests, 50% price). Resumable: the job name is kept in `state_file` so a rerun
        polls the same job instead of resubmitting. Returns one {'text','usage'} (or None) per prompt."""
        payload = {"prompts": [hashlib.sha256(p.encode()).hexdigest() for p in prompts], "schema": schema,
                   "system": system}
        key = self._key("batch", model, payload)
        hit = self._load(key)
        if hit is not None:
            return hit["responses"]
        if self.replay:
            raise ReplayMiss(f"batch/{model}: not recorded")
        from google.genai import types
        state = {}
        if state_file and Path(state_file).exists():
            state = json.loads(Path(state_file).read_text())
        name = state.get(key)
        if not name:
            cfg: dict = {}
            if schema is not None:
                cfg = {"response_mime_type": "application/json", "response_json_schema": schema}
            if system:
                cfg["system_instruction"] = system
            reqs = [types.InlinedRequest(model=model, contents=[types.Content(role="user", parts=[types.Part(text=p)])],
                                         config=types.GenerateContentConfig(**cfg) if cfg else None,
                                         metadata={"i": str(i)}) for i, p in enumerate(prompts)]
            job, t0 = self._retry(lambda: self.client.batches.create(
                model=model, src=reqs, config=types.CreateBatchJobConfig(display_name="canary-atlas-labels")),
                model, "batch", {"op": "batches.create"})
            name = job.name
            self._ledger(model, "batch", None, t0, meta={"op": "batches.create", "n": len(prompts), "job": name},
                         tokens={"in": 0, "out": 0})
            if state_file:
                state[key] = name
                Path(state_file).parent.mkdir(parents=True, exist_ok=True)
                Path(state_file).write_text(json.dumps(state))
        t_start = time.time()
        while True:
            job = self.client.batches.get(name=name)
            st = str(getattr(job.state, "name", job.state))
            if on_poll:
                on_poll(st, time.time() - t_start)
            if st in ("JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
                break
            if time.time() - t_start > timeout_s:
                raise TimeoutError(f"batch {name} still {st}")
            time.sleep(poll_s)
        if st != "JOB_STATE_SUCCEEDED":
            raise RuntimeError(f"batch {name} ended {st}: {getattr(job, 'error', '')}")
        out: list[dict | None] = [None] * len(prompts)
        inl = (job.dest.inlined_responses if job.dest else None) or []
        for j, ir in enumerate(inl):
            idx = j
            md = getattr(ir, "metadata", None) or {}
            if isinstance(md, dict) and str(md.get("i", "")).isdigit():
                idx = int(md["i"])
            resp = getattr(ir, "response", None)
            if resp is None or idx >= len(out):
                continue
            um = getattr(resp, "usage_metadata", None)
            # one ledger row per labelled request; kind=batch applies the 50% price
            row = record(FEATURE, model, kind="batch", usage=um, latency_s=0.0, run_id=self.run_id,
                         meta={"op": "batch_result", "job": name})
            u = _usage_dict(um)
            self.stats["calls"] += 1
            self.stats["cost_usd"] += row["cost_usd"]
            self.stats["by_kind"]["batch"] = self.stats["by_kind"].get("batch", 0) + 1
            self.stats["in"] += u["prompt_token_count"]
            self.stats["out"] += u["candidates_token_count"]
            try:
                text = resp.text or ""
            except Exception:  # noqa: BLE001
                text = ""
            out[idx] = {"text": text, "usage": u}
        self._store(key, {"responses": out, "job": name})
        self.source_run_ids.add(self.run_id)
        return out


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")
