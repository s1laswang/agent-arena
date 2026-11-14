# Gemini notes (google-genai SDK)

For whoever builds `pinbox/gemini/*` and `pinbox/agents/gemini_agent.py`.

- Checked: 2026-11-14. **No API key on this machine.** Nothing here was sent to the real API.
- SDK: **`google-genai` 3.3.0** (`from google import genai`), Python 3.14.5, in the team venv.
  It pulls in `httpx2` (a fork of httpx), `tenacity`, `pydantic` 2.14.
- How it was checked: read the installed source, and ran every snippet below against a fake HTTP
  server (`httpx2.MockTransport`, see section 7). So the **request shape and the parsing are
  verified**; what the real server does with them is not.

## 0. Model picks (from the docs, 2026-11-14)

| Use | Model id | Context in / max out | Price per 1M in / out | Free tier |
|---|---|---|---|---|
| Best reasoning | `gemini-4-carbon` | 1,048,576 / 65,536 (1M with "long decode") | $2 / $10 until 30 Nov, then $4 / $20 | No |
| Default all-rounder | `gemini-4-hydrogen` | 1,048,576 / 65,536 | $1.50 / $7.50 | Yes |
| Fast and cheap | `gemini-3.5-flash-lite` | not stated on the page I read | $0.30 / $2.50 | Yes |

Other ids that exist: `gemini-4-argon` (cheaper, faster Gemini 4 reasoning; paid only),
`gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview`.
Gone or going: `gemini-3-pro-preview` (shut down), `gemini-2.5-pro` and `gemini-2.5-flash`
(shut down 1 Dec 2026). Gemini 4 Hydrogen came out 12 Nov 2026, Carbon on 10 Nov.

Suggestion for us:
- Defender agent (our "Gemini gap" number): `gemini-4-carbon`. If no paid key, `gemini-4-hydrogen`.
- Attacker wording + fairness judge: `gemini-4-hydrogen`. Bulk or cheap runs: `gemini-3.5-flash-lite`.
- Analyst (all trajectories in one prompt): `gemini-4-hydrogen` (1M context).
- Keep it in env `PINBOX_GEMINI_MODEL` (SPEC section 9). Check ids live with:
  `for m in client.models.list(): print(m.name, m.input_token_limit, m.output_token_limit)`
  (`m.name` looks like `models/gemini-4-hydrogen`).

Gemini 4 and 3 settings:
- Thinking is set with `thinking_level`, not `thinking_budget` (sending both to Gemini 4 is a 400).
  Levels: Carbon/Argon `low|medium|high` (default medium). Hydrogen `low|medium|high|xhigh`
  (default high). Flash-Lite 3.5 `minimal|low|medium|high` (default minimal). Gemini 4 cannot turn thinking off.
- `max_output_tokens` includes thinking tokens. Do not set it small; the docs suggest >= 32,768 for Gemini 4.
- A Google guide says Gemini 4 ignores `temperature`, `top_p`, `top_k`. So do not rely on them for determinism.
- Google now calls `generateContent` "legacy" and pushes the new Interactions API
  (`client.interactions.create`). `generate_content` still works and all docs still show it.
  We use `generate_content`: it is stateless, which fits our replay and logging.

## 1. Client

```python
import os
from google import genai
from google.genai import types

client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],          # pass it explicitly, see note
    http_options=types.HttpOptions(
        timeout=600_000,                            # MILLISECONDS (10 min)
        retry_options=types.HttpRetryOptions(attempts=5),   # retries are OFF by default, see section 5
    ),
)
```

- With no `api_key`, the SDK reads env `GOOGLE_API_KEY` first, then `GEMINI_API_KEY`. If both are set,
  `GOOGLE_API_KEY` wins (with a warning). Passing `api_key=` explicitly avoids surprises.
- No key at all: `genai.Client()` raises `ValueError("No API key was provided...")` at construction.
  So import `google.genai` lazily and build the client only when a key exists (SPEC rule: stdlib-only import path).
- Endpoint used by 3.3.0: `https://generativelanguage.googleapis.com/v1/models/<id>:generateContent`,
  key in header `x-goog-api-key`. If a feature is rejected on `v1`, try `types.HttpOptions(api_version="v1beta")`.
- `client.close()` or `with genai.Client(...) as client:` closes the HTTP pool. Async: `client.aio.models.generate_content(...)`.

## 2. JSON output with a schema

```python
SCHEMA = {  # plain JSON Schema dict
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["fair", "unfair"]},
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
}

resp = client.models.generate_content(
    model="gemini-4-hydrogen",
    contents="Is this wording fair under the policy? ...",
    config=types.GenerateContentConfig(
        system_instruction="You are a strict judge.",
        response_mime_type="application/json",     # required with a schema
        response_json_schema=SCHEMA,               # JSON Schema dict
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        max_output_tokens=32768,
    ),
)
data = resp.parsed          # dict, or None if the text was not valid JSON
if data is None:
    raise ValueError(f"bad JSON, finish={resp.candidates[0].finish_reason}: {resp.text!r}")
```

- Use `response_json_schema` (JSON Schema dict). `response_schema` is the older OpenAPI-style
  `types.Schema` (or a pydantic class). Do not set both.
- `resp.parsed` = `json.loads(resp.text)` for a dict schema. If the JSON is broken (for example cut off by
  `MAX_TOKENS`) `parsed` is **None, no exception**. Always check it.
- If you pass a pydantic class as `response_schema`, `parsed` is an instance of that class.
- `config` may also be a plain dict: `config={"response_mime_type": "application/json", "response_json_schema": SCHEMA}`.
- Supported schema keywords (docs): `type` (incl. `["string","null"]`), `title`, `description`, `properties`,
  `required`, `additionalProperties`, `enum`, `format` (date-time/date/time), `minimum`, `maximum`, `items`,
  `prefixItems`, `minItems`, `maxItems`, `anyOf`, `$ref`/`$defs`. Others are ignored. Huge or deep schemas → 400.
- Valid JSON is guaranteed, correct values are not. Validate in code.

## 3. Function calling with a manual loop

Our tools come as `client.tools()` → `[{"name", "description", "parameters": <JSON Schema object>}]`.
`parameters_json_schema` takes that dict as-is.

```python
from google.genai import types

def to_gemini_tools(specs):
    decls = []
    for s in specs:
        params = s.get("parameters") or {}
        kwargs = {"name": s["name"], "description": s.get("description", "")}
        if params.get("properties"):                 # skip schema for no-arg tools
            kwargs["parameters_json_schema"] = params
        decls.append(types.FunctionDeclaration(**kwargs))
    return [types.Tool(function_declarations=decls)]

def run_gemini_agent(gclient, ep_client, model, max_turns=200):   # gclient = genai.Client
    config = types.GenerateContentConfig(
        system_instruction=ep_client.instruction(),
        tools=to_gemini_tools(ep_client.tools()),
        # We pass declarations, not Python functions, so the SDK would not auto-run anything anyway.
        # Disable it to be explicit.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")),  # AUTO|ANY|NONE|VALIDATED
        thinking_config=types.ThinkingConfig(thinking_level="medium"),
        max_output_tokens=32768,
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text="Start the task now.")])]
    for _ in range(max_turns):
        resp = gclient.models.generate_content(model=model, contents=contents, config=config)
        if not resp.candidates:               # prompt blocked: see resp.prompt_feedback
            break
        cand = resp.candidates[0]
        contents.append(cand.content)        # append the model turn UNCHANGED (keeps thought signatures)
        calls = resp.function_calls or []     # list[types.FunctionCall]: .id .name .args (dict)
        if not calls:
            break                             # model is done (or finish_reason says why not)
        parts = []
        for fc in calls:
            out = ep_client.call(fc.name, **(fc.args or {}))   # {"ok", "result", "error"} - a dict
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=fc.id, name=fc.name, response=out)))
        contents.append(types.Content(role="user", parts=parts))   # all results of one turn together
        if out.get("error") == "tool budget exhausted":
            break                             # SPEC: stop at budget
    return contents
```

Must-knows:
- **Thought signatures.** Gemini 4 and 3 attach a `thought_signature` to function-call parts. You must send
  them back, or the API returns 400 (finish reason enum also has `MISSING_THOUGHT_SIGNATURE`). Appending
  `resp.candidates[0].content` unchanged does this. Verified: the signature goes back as `thoughtSignature`.
  Do not rebuild the model turn with `Part.from_function_call(...)`; that drops the signature.
- **Call ids.** Gemini 3+ gives each call an `id`. Return it in `FunctionResponse(id=...)`.
  In 3.3.0, `types.Part.from_function_response(name=, response=)` has **no `id` argument**
  (the docs show one; it raises `TypeError` here). Use `types.Part(function_response=types.FunctionResponse(id=..., name=..., response=...))` as above.
- `FunctionResponse.response` must be a **dict** (a list fails validation). Our dispatch dict is fine.
- Parallel calls: one model turn can hold several calls. Run them in order and send all results in one user turn.
- `resp.text` on a function-call-only reply is None and logs a warning. Use `resp.function_calls`.
- Check `cand.finish_reason` (`types.FinishReason`): `STOP` normal; `MAX_TOKENS`; `MALFORMED_FUNCTION_CALL`
  (bad call, worth one retry with a nudge); `TOO_MANY_TOOL_CALLS`; `UNEXPECTED_TOOL_CALL`; `SAFETY` etc.
  `resp.prompt_feedback.block_reason` is set if the prompt itself was blocked (then `candidates` may be empty).
- Docs advice: keep about 10-20 tools active (we have ~12-14 per family, fine).
- Saving a transcript: `c.model_dump(mode="json", exclude_none=True)` gives JSON (signature as base64);
  `types.Content.model_validate(d)` restores it exactly (verified round-trip).
- Numbers in `fc.args` are plain JSON numbers. If our dispatcher is strict about int vs float, coerce
  using the tool schema before calling.

## 4. Tokens

```python
n = client.models.count_tokens(model="gemini-4-hydrogen", contents=big_text).total_tokens

u = resp.usage_metadata          # after generate_content
u.prompt_token_count, u.candidates_token_count, u.thoughts_token_count, u.total_token_count
u.cached_content_token_count     # implicit cache hits (Gemini 4: implicit caching only)
```

- On the Gemini Developer API, `count_tokens(..., config=types.CountTokensConfig(system_instruction=..., tools=...))`
  raises `ValueError` in the SDK (only allowed on Vertex/Enterprise). To count a full prompt,
  put the system text into `contents`, or just read `usage_metadata` after the call.
- Thinking tokens are billed as output and count against `max_output_tokens`.

## 5. Retries, rate limits, errors

**Retries are off by default in 3.3.0.** With no `retry_options`, the client makes exactly 1 attempt
(verified with a fake 429). Some Google docs say "retries 4 times by default"; that is only true once you
pass `HttpRetryOptions()`.

```python
types.HttpOptions(retry_options=types.HttpRetryOptions(
    attempts=5,          # total tries incl. the first (default 5 when the object exists)
    initial_delay=1.0,   # seconds, default 1.0
    max_delay=60.0,      # default 60
    exp_base=2.0,        # default 2
    jitter=1.0,          # default 1
    # http_status_codes default: 408, 429, 500, 502, 503, 504
))
```
- Set it on the client (`genai.Client(http_options=...)`) or per call
  (`GenerateContentConfig(http_options=types.HttpOptions(retry_options=...))`). Both verified.
- It also retries httpx timeouts and connect errors. 400/403/404 are never retried (verified).

Exceptions (`from google.genai import errors`):

| Class | When | Useful fields |
|---|---|---|
| `errors.APIError` | base class for HTTP errors | `.code` (int), `.status` (e.g. `"RESOURCE_EXHAUSTED"`), `.message`, `.details` (raw JSON) |
| `errors.ClientError(APIError)` | any 4xx. **429 rate limit is a ClientError** | `e.code == 429`, `e.status == "RESOURCE_EXHAUSTED"` |
| `errors.ServerError(APIError)` | any 5xx (503 `UNAVAILABLE` = overloaded) | |
| `ValueError` | no API key; bad config | |
| `pydantic.ValidationError` | wrong types in `types.*` objects | |

Rate-limit pattern (on top of SDK retries, for long eval runs):
```python
import time, random
from google.genai import errors

def call_with_backoff(fn, tries=6):
    for i in range(tries):
        try:
            return fn()
        except errors.APIError as e:
            if e.code not in (408, 429, 500, 502, 503, 504) or i == tries - 1:
                raise
            time.sleep(min(60, 2 ** i) + random.random())
```
- Docs: retry only 408, 429, 5xx. Exponential backoff with jitter. Do not retry 400/402/403.
- Per-model RPM/TPM/RPD numbers are only shown in AI Studio, not on the docs page. Carbon/Argon have no free tier.
- For long hard prompts Google suggests long HTTP timeouts (up to 15 min). Our `timeout` is in **milliseconds**.

## 6. Small things that bite

- `types.ThinkingConfig(thinking_level="low")` works with a string (sent as `"LOW"`).
- The SDK sends `parameters_json_schema` and `thinking_level` in snake_case in the JSON body. Google's
  JSON parser normally accepts both spellings, but this was not tested live.
- `system_instruction` can be a plain string.
- `seed=` exists in the config, but with Gemini 4 ignoring sampling params, expect runs to differ.
  Our 3-runs-per-episode plan (SPEC section 1) handles that.
- Free-tier keys may log prompts for training. Our data is synthetic, so that is fine.

## 7. Testing without a key (for `tests/test_gemini.py`)

The real `genai.Client` can run against a fake server. This is how everything above was checked.

```python
import json, httpx2
from google import genai
from google.genai import types

def fake_client(replies):                    # replies: list of (status, json_body)
    def handler(request):
        status, body = replies.pop(0)
        return httpx2.Response(status, json=body)
    return genai.Client(api_key="FAKE", http_options=types.HttpOptions(
        httpx_client=httpx2.Client(transport=httpx2.MockTransport(handler))))

reply = {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"id": "fc_1", "name": "list_invoices", "args": {"status": "open"}},
             "thoughtSignature": "c2lnLTE="}]}, "finishReason": "STOP"}]}
```
Use the REST camelCase shape in fake replies (`functionCall`, `thoughtSignature` base64, `usageMetadata`).
`FakeGemini` (SPEC section 9) can stay a simple stub; this is for testing the real wrapper.

## Sources

- Installed source: `venv/Lib/site-packages/google/genai/` (`client.py`, `_api_client.py` lines ~163 and ~670-730,
  `errors.py`, `types.py` `GenerateContentResponse._from_response`, `Part.from_function_response`).
- Models: https://ai.google.dev/gemini-api/docs/models (redirects to https://aistudio.google.com/docs/models)
- Model pages: https://aistudio.google.com/docs/models/gemini-4-carbon , .../gemini-4-hydrogen , .../gemini-4-argon
- Latest models: https://aistudio.google.com/docs/latest-model
- Pricing: https://aistudio.google.com/docs/pricing
- Deprecations: https://aistudio.google.com/docs/deprecations
- Function calling (generateContent version): https://aistudio.google.com/docs/function-calling?generate-content=true
- Structured output: https://aistudio.google.com/docs/structured-output?generate-content=true
- Thinking: https://aistudio.google.com/docs/thinking?generate-content=true
- Thought signatures: https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures
- Tokens: https://aistudio.google.com/docs/tokens?generate-content=true
- Rate limits: https://aistudio.google.com/docs/rate-limits
- Troubleshooting / errors: https://aistudio.google.com/docs/troubleshooting
- Gemini 4 dev guides (seen only via search snippets): https://aistudio.google.com/learn/gemini-4-carbon-developer-guide ,
  https://aistudio.google.com/learn/gemini-4-argon-developer-guide

## UNVERIFIED (check with a real key first)

1. Model ids, limits and prices come from docs pages read on 2026-11-14 through a summariser. Run `client.models.list()` once with a key.
2. Context size for `gemini-3.5-flash-lite` (not read). Probably 1M, unconfirmed.
3. "Gemini 4 ignores temperature/top_p/top_k" and "max_output_tokens >= 32,768" come from search snippets of the
   Gemini 4 developer guides; the pages themselves did not render for me.
4. That the `v1` endpoint (SDK 3.3.0 default) accepts `responseJsonSchema`, `parameters_json_schema` and
   `thinking_level` as sent. If you get 400 "unknown field", try `api_version="v1beta"`.
5. That `parameters_json_schema` accepts our tool schemas as-is (e.g. a `default` keyword, or an empty `properties`).
   I skip the schema for no-arg tools to be safe.
6. Real server behaviour for: thought signatures on Gemini 4, call ids always present, parallel calls,
   number types in `fc.args`.
7. Free-tier rate limits for `gemini-4-hydrogen` and `gemini-3.5-flash-lite` (only shown in AI Studio).
8. Whether `seed` has any effect on Gemini 4.
