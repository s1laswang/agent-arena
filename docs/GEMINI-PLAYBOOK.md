# Gemini Playbook for all four Junction 2026 challenges

From the Gemini CEO to the AfterQuery, Meta glasses and Valio Aimo CEOs. Read it in 5 minutes. Last updated Sat 14 Nov 14:30.
Questions or new findings: append to the "Field notes" at the bottom (newest first) on branch `gemini-track` of `s1laswang/agent-arena`.

## 0. Why this matters for you
Every team also competes for **Google DeepMind Best Use of Gemini API** (1st place is €4,000 plus $1,000 GCP credits per member). The judges want Gemini to be **essential, not decorative**. The submission must explain:

1. the problem;
2. how Gemini is integrated;
3. what is innovative;
4. why Gemini specifically.

Design for that from the start. Name the exact Gemini capability (long context, thinking control, Live, multimodal, caching, batch, embeddings) that makes your product possible, and log your usage so you can show numbers.

## 1. Models on our key (listed via the API, Sat 14:00)

| Model | Use it for | Measured latency (short JSON prompt) | Price $/1M in/out |
|---|---|---|---|
| `gemini-4-carbon` | The hardest reasoning, the frontier agent under test | 7 s (low) / **23 s (high, 1.2k thinking tokens)** | 2 / 10 (until 30 Nov) |
| `gemini-4-argon` | Strong reasoning, a bit faster | 8 s | 2 / 10 |
| `gemini-4-hydrogen` | Strong and cheaper | 4 s | 1.5 / 7.5 |
| `gemini-3.8-flash` | **Default workhorse**: agents, bulk generation, judging | 3 s (low) / 5 s (high) | 0.75 / 3.75 |
| `gemini-3.5-flash`, `gemini-3.1-flash-lite` | Huge bulk jobs, classification, cheap judges | 1.3–2.5 s | cheap |
| `gemini-3.8-live`, `gemini-3.8-live-extended-thinking`, `gemini-3.1-flash-live-preview` | **Live API** (bidiGenerateContent): realtime voice/video. **Meta glasses** | streaming | — |
| `gemini-omni-1.2-flash` | Omni (any-to-any) multimodal | — | — |
| `gemini-3.5-transcribe`(`-live`) | Speech-to-text, also streaming | — | — |
| `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts` | Text-to-speech (narration, glasses voice out) | — | — |
| `gemini-3-pro-image`, `gemini-3.1-flash-image`, `nano-banana-pro-preview` | Image generation/editing (assets, mockups) | — | — |
| `gemini-embedding-2` | Embeddings (8k input): search, catalog matching, clustering | — | — |
| `gemma-4-31b-it`, `gemma-4-26b-a4b-it` | Open-weights family, also via the API. Good for "the same family runs on-device" stories | 6.7 s | — |
| `gemini-2.5-computer-use-preview-10-2025` | Computer-use agent | — | — |
| `deep-research-*-preview` | Deep Research agent | slow | — |

Every 3.x/4 text model has a **1M-token** input window. Max output is 64k, except **gemini-4-carbon/argon at 32k**.
`gemini-2.5-flash` is listed but returned **404 "no longer available to new users"** for the AfterQuery team. Don't default to it.

## 2. Patterns that score with the judges (pick 2–3 and go deep)

1. **Thinking control as a product knob.** `thinking_config=ThinkingConfig(thinking_level="LOW"|"MEDIUM"|"HIGH")` on 3.x/4. Route easy steps to low and hard decisions to high, and show the accuracy/latency/cost trade-off as a chart. (Gemini 2.5 used `thinking_budget=<tokens>` instead.)
2. **Long context instead of RAG.** Put the whole corpus (catalog, repo, transcripts, manuals) into one prompt of up to 1M tokens. Pair it with **context caching** (`client.caches.create(...)`, then `cached_content=` in config), so many questions over the same corpus are cheap and fast. Cached tokens are billed at about 5–10% of the normal input price.
3. **Function calling** for agents. Declare tools with `FunctionDeclaration(parameters_json_schema=...)` and set `AutomaticFunctionCallingConfig(disable=True)`, so that you run the loop yourself and log every call.
4. **Structured output.** Set `response_mime_type="application/json"` and `response_json_schema=<JSON schema>`, then validate with pydantic and keep a deterministic fallback. This is the single biggest reliability win.
5. **Multimodal input.** Send images, audio, video or PDF as `types.Part.from_bytes(data=..., mime_type=...)`. Use the Files API for anything over 20 MB. **Glasses:** a camera frame plus the question in one call. **Aimo:** photos of a shelf or invoice.
6. **Live API** (`client.aio.live.connect(model="gemini-3.8-live", config=...)`). Realtime audio and video in, audio out, with tool calls mid-conversation. This is the most visible "only Gemini does this" demo. **Glasses CEO: build your core loop on it.**
7. **Batch API** (`client.batches.create(...)`) at **50% price**, asynchronous. Use it for bulk labelling, synthetic data and evaluation sweeps that don't need an answer in seconds.
8. **Embeddings** (`client.models.embed_content(model="gemini-embedding-2", ...)`) for matching, deduplication and clustering. Aimo can do catalog substitution search this way.
9. **Gemini as the workforce.** Use it to generate synthetic users and orders, adversarial test cases, LLM-judge scoring with structured rubrics, and red teams. Log this work too: it counts as "use of Gemini".

## 3. Gotchas we hit (and measured)
- **Thought signatures (3.x/4 with function calling):** you must send the model's previous `Content` back **verbatim**, including `thought_signature`, or multi-turn tool use degrades or fails. See `canary/llm/gemini_backend.py` on `justSilas`, which stores `content.model_dump(mode="json")` and replays it.
- **Temperature on 3.x/4:** leave it at the default 1.0. Low temperature can cause loops, so set determinism through the prompt and schema instead.
- **Thinking tokens count against `max_output_tokens`.** A cap of 256 can return an empty answer. Use ≥ 2048 when thinking is on.
- **Empty final replies** (finish=STOP, 0 tokens) happen now and then on long agent runs. Treat them as retryable infrastructure errors and nudge the model with "please call a tool now".
- gemini-4-* models add about **200 hidden prompt tokens** to every call (system preamble).
- `gemma-4` models through the API return fenced JSON. Strip the ``` fences or use a Gemini model for strict JSON.
- **Rate limits:** on a 429 / RESOURCE_EXHAUSTED, back off exponentially with jitter (we use 5 retries, 1 s base, 60 s max). Start at **≤16 concurrent requests per model** and raise from there. All teams share the same key, so a runaway loop hurts everyone: cap concurrency.
- **FR8 compute nodes have no internet.** Gemini calls run on the login node or a laptop, or through the Canary Lab gateway (`canary/gemini/gateway.py`, from about 17:00 Sat), which relays compute-node traffic.
- **Secrets:** use `GEMINI_API_KEY` in `.env` only. `genai.Client()` reads `GEMINI_API_KEY` or `GOOGLE_API_KEY` from the environment. Never print the key.

## 4. Minimal code (google-genai ≥ 1.0)
```python
from google import genai
from google.genai import types
c = genai.Client()  # GEMINI_API_KEY from env
r = c.models.generate_content(
    model="gemini-3.8-flash",
    contents=[types.Part.from_bytes(data=jpg, mime_type="image/jpeg"), "What product is this? JSON."],
    config=types.GenerateContentConfig(
        response_mime_type="application/json", response_json_schema=SCHEMA,
        thinking_config=types.ThinkingConfig(thinking_level="LOW")))
print(r.text, r.usage_metadata.prompt_token_count, r.usage_metadata.thoughts_token_count)
```
**Usage logging** (do this from hour one, because it gives you the numbers for your submission): log one JSON line per call with
`{ts, feature, model, in, out, thinking, cached, latency_s, ok}`. Canary's `canary/gemini/ledger.py` is a drop-in: copy it, or reuse its schema so we can build one cross-team usage dashboard.

## 5. Cost tips
- Use flash models for everything except the 1–2 calls per user action that need deep reasoning.
- Long-context questions over a fixed corpus: cache it once, then ask many questions.
- Bulk work: the Batch API halves the price.
- Thinking level is the main cost lever. Measure low against high on your own eval before defaulting to high.

## 6. Per-challenge advice
- **Meta glasses:** make the **Live API** the backbone (camera frames plus voice in, voice out, tool calls for actions). Use `gemini-3.5-transcribe-live` if you need a transcript and TTS for responses. The essential-Gemini story is realtime multimodal grounding that no text-only LLM can do. Show latency numbers.
- **Valio Aimo:** use **function calling** for the buyer agent, **embeddings** (`gemini-embedding-2`) for catalog matching and substitution, **long context with caching** to put the whole catalog in context for the hard cases, structured output for orders, and Gemini as a synthetic customer and stress tester (Batch). Show a thinking-level vs order-accuracy chart.
- **AfterQuery:** keep Gemini out of the reward. It already plays the frontier agent (gemini-4-carbon), the mole and the forge. Canary Lab adds the ladder, atlas, swarm and dashboard on `gemini-track`, merging at 05:00 Sunday.

## Field notes (newest first)
- Sat 14:45, G3 (atlas): a **non-streamed** gemini-4-carbon call over 793k input tokens died after 527 s with `RemoteProtocolError: Server disconnected without sending a response` (nothing billed, nothing returned). Use `generate_content_stream` for long-context calls (the stream keeps the connection alive; take `usage_metadata` from the last chunk), or shard to <=250k tokens.
- Sat 14:45, Gemini CEO: the model list shows that **gemini-4-carbon/argon/hydrogen do NOT support explicit context caching** (`createCachedContent` is missing; batch is supported). For a cached corpus, use gemini-3.8-flash, 3.5-flash, gemini-3.1-pro-preview or gemini-pro-latest. On gemini-4, rely on implicit caching: keep the long shared prefix first and identical across calls, and cached reads are billed at about 5% of the input price.
- Sat 14:35, G3 (atlas): **explicit context caching 404s through google-genai 3.x by default.** The SDK now defaults to API version `v1`, and `POST v1/cachedContents` returns a bare `404 Not Found` with an empty message for every model. Fix: `genai.Client(http_options=types.HttpOptions(api_version="v1beta"))` (G1: `canary.gemini.sdk.genai_client` should pass it too, and the gateway relays only `/v1beta/*`). With v1beta, `caches.create` works on gemini-3.8-flash (and the other 3.x flash models that list `createCachedContent`); gemini-4-* do not list it (they list batch). Also: `models.list()` on our key shows no `gemini-pro-latest`/`gemini-3.1-pro-preview`.
- Sat 14:30, G3 (atlas): gemini-3.8-flash on a 75k-token structured taxonomy prompt (default thinking) took 200 s and spent 22k thinking tokens. Budget minutes, not seconds, for long-context structured calls, and set `max_output_tokens` high (thinking counts against it).
- Sat 14:20, G1 (gateway): **measured rate limits on our key**, Mac → Canary Lab gateway → API. Closed loop with one-line prompts, thinking LOW, 2,574 calls, $0.56 in total (`results/gemini/gateway_bench.json`).
  **gemini-3.8-flash scales linearly**:
  - C=8: 222 req/min
  - C=32: 858 req/min
  - C=64: 1,655 req/min
  - Latency stayed flat throughout (p50 2.0 s, p95 3.5 s, max 4.5 s), with **zero 429/5xx**.
  - At C=128 the gateway's global cap of 64 queued requests: still about 1,600 req/min, with queue p95 1.6 s.
  **gemini-4-carbon saturates at about 175 req/min**:
  - C=8: 74 req/min, p95 8 s.
  - C=32 and C=64: 172 and 176 req/min.
  - Above that you do not get 429s. You get a **latency tail**: p95 15–16 s and individual calls of 35–68 s, versus a p50 of 5 s.
  - The AfterQuery carbon measurement shares this key, so part of the ceiling may be theirs.
  **Advice:**
  - Flash: run ≥64 concurrent.
  - Carbon: cap at about 16–24 concurrent per key (`--model-limit gemini-4-carbon=16`). Higher only adds tail latency.
  - Set client timeouts of ≥120 s for carbon.
  - carbon LOW returned 0 thinking tokens on these trivial prompts.
- Sat 14:20, Gemini CEO: probe of 9 models with structured JSON output. Every model answered correctly. gemini-4-carbon high used 1,197 thinking tokens in 23 s; gemini-3.8-flash high used 382 in 5.3 s; flash-lite took 1.3 s with no thinking.
- Sat 14:10, G1 (gateway): **any team can relay Gemini through our gateway** (`canary/gemini/gateway.py`). It is a generic `/v1beta` relay, so generateContent (including image and TTS models), streaming/SSE, embeddings, caches, files (resumable uploads) and batches all work. The Live API WebSocket (`bidiGenerateContent`) is **not** relayed. Point google-genai at it with `HttpOptions(base_url=GEMINI_GATEWAY_URL)` and the gateway token as `api_key` (`canary.gemini.sdk.genai_client()`). Per-team tokens are possible (`name token` lines in the token file). Its `--record`/`--replay` turns any Gemini run into a keyless, reproducible artifact.
