# G1 Gateway + FR8 ops: report (newest first)

## Sat 15:40: gateway, sdk, lab_client hook, record/replay and FR8 scripts are done. **Blocker: no ssh to FR8 from here**

**Blocker:** `ssh freighter` times out on TCP 22 from this Mac (14:45–15:40, every retry). ICMP ping to freighter.fr8.so works (3 ms), and TCP 22, 443 and 2222 time out (public IP 194.157.9.46). The likely causes are the venue network filtering outbound 22 or an FR8 firewall or fail2ban rate limit after many agent ssh connections. The FR8 smoke (compute node → gateway → Gemini) is **not done yet**. All the scripts are written and ready to run once ssh works. The `ssh -R` fallback needs ssh too, so the only other route is a different network (phone hotspot or VPN). **Silas: please check whether `ssh freighter hostname` works from your terminal.**

Done (verified):
- `canary/gemini/gateway.py`: a pure ASGI app on uvicorn with httpx2 for upstream (both already in the lock, so no new deps).
  - Relays `/v1beta|/v1|/v1alpha|/upload`: generateContent, streamGenerateContent (SSE), embedContent, caches, files (resumable upload: the `x-goog-upload-url` header is rewritten to point at the gateway), batches and models.
  - Requires a token on every request (`x-goog-api-key` or `?key=`); the key is swapped server-side.
  - Global and per-model caps (`--model-limit gemini-4-carbon=8`) with queueing; retries 429/5xx with exponential backoff and jitter (honours Retry-After).
  - Writes a stats JSONL with no bodies or keys; `--record` and `--replay` use gzip files in sharded dirs.
  - Self-exits after `--max-hours`; cleans up its pidfile on SIGTERM; `/healthz` needs no auth and returns counters only.
  - The key is read in-process from a 0600 file (`--key-file`, default `.env`). It is never on argv; the gateway refuses token/key files that are group- or world-readable.
  - Per-client tokens: the token file accepts `name token` lines, so the Meta glasses team can get its own token, and stats show `client`.
- `canary/gemini/sdk.py`: `genai_client()`, `gateway_http_options()`, `gateway_token()`, and `python -m canary.gemini.sdk [model]` (a one-call smoke). `lab_client("gemini:...")` now passes `sdk_client=genai_client()`, so every ladder/atlas/swarm call is gateway-capable through `GEMINI_GATEWAY_URL`. The stub path is unchanged.
- **Real Gemini through the gateway on the Mac:** the showcase made 6 calls on gemini-3.1-flash-lite and gemini-embedding-2: function calling with 2 turns and thought-signature replay, JSON schema output, streaming and embeddings. The recording is committed in `results/gemini/replay/` (28 KB). `make lab-replay` reproduces it keyless with `REPLAY OK, 5 steps`. Recorded files and stats were scanned for the key and token: clean.
- `tests/test_gemini_lab_gateway.py` (16 tests, about 7 s, keyless, fake upstream) covers: auth rejection (including the real key used as a token), key swap by header and query, record→replay (JSON key order independent, repeats in order), replay miss → 404, global and per-model caps, 429 retry, SSE relay, upload URL rewrite, no secrets or bodies in stats, 0600 enforcement, SDK+lab_client through the gateway, the token file with names, the committed showcase replaying keyless in a subprocess, and the tcprelay.
- FR8 scripts (`fr8/gemini/`): `deploy.sh` (rsync to `~/agent-arena-gemini`; key file `.gateway.env` 0600 sent via ssh stdin; token generated server-side; niced `uv sync` on login with the warm cache; srun import check), `gateway_up.sh` (binds the login node's cluster-internal source IP toward compute01, nice 19, setsid/nohup, pidfile, `--max-hours 8`, carbon cap 8, checks no-token → 401 and that the key is not in `ps`), `gateway_down.sh`, `smoke.sh` (srun 5 min, one ledgered call), `worker.sbatch` plus `submit.sh` (array; `{i}/{n}/{job}` substitution; records ids in OURS.txt), `pull.sh`, and `tunnel_up.sh [--down]` (the fallback: Mac gateway + `ssh -R` + login-node byte relay `canary.gemini.tcprelay`). None of them has been run against FR8 yet (blocker above).

Env for FR8 workers (worker.sbatch sets all of these):
```
GEMINI_GATEWAY_URL=$(cat ~/agent-arena-gemini/run/gateway.url)     # http://<login internal IP>:8787
GEMINI_GATEWAY_TOKEN_FILE=~/agent-arena-gemini/.gateway_token      # 0600, shared /home
GEMINI_API_KEY=                                                     # workers never hold the key
CANARY_GEMINI_LEDGER_DIR=~/agent-arena-data/gemini/ledger
CANARY_GEMINI_RUN_ID=slurm-<array job id>
```
Launch (G2): `bash fr8/gemini/submit.sh --array 0-3 --time 02:00:00 -c 2 -- python -m canary.gemini.ladder ... --shard {i}/{n}`

Deviation: the server-side key file is `~/agent-arena-gemini/.gateway.env` and not `.env`. Workers run from the same directory and `canary.llm` auto-loads `.env`, so a `.env` there would put the key into every worker.

Answers for other teams: the gateway relays generic `generateContent`, so **image models work** (gemini-3-pro-image, 3.1-flash-image; inline image bytes in/out) and so do TTS models. The **Live API (WebSocket bidiGenerateContent) is out of scope**: it is not relayed and the gateway drops websocket scopes.

Next: FR8 smoke as soon as ssh works (deploy → gateway_up → smoke → down); a 4-task worker.sbatch array; throughput measurement (flash and carbon at concurrency 8/32/64, < $5).
