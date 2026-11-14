# G1 Gateway + FR8 ops: report (newest first)

## Sat 14:50: merge-ready for PR 1. FR8 smoke still blocked: this Mac's ssh to freighter times out

**FR8 status.** The CEO's session reaches `freighter`, but every connection from this agent times out at TCP connect to 194.157.9.46:22. That holds inside and outside the Claude sandbox, and with ControlMaster. It is not a rate limit: `ssh -v` never gets past `connect()`. **The CEO (or Silas) can run the smoke** with the commands below. Every script now uses one multiplexed ssh session (ControlMaster auto, ControlPersist 10m, ControlPath `~/.ssh/cm-%r@%h:%p`).
```
bash fr8/gemini/deploy.sh          # rsync -> ~/agent-arena-gemini; .gateway.env + .gateway_token (0600); uv sync; srun import check
bash fr8/gemini/gateway_up.sh      # login node, nice 19, --max-hours 8, carbon cap 8; prints /healthz, no-token -> 401, ps key check
bash fr8/gemini/smoke.sh           # srun -p normal --time=00:05:00: compute node -> gateway -> gemini-3.1-flash-lite (1 call, ledgered)
bash fr8/gemini/gateway_down.sh    # stop + stats summary (policy: take it down after the smoke)
```
M2 array test: `bash fr8/gemini/submit.sh --array 0-3 --time 00:10:00 -c 1 -- python -m canary.gemini.sdk` (4 tasks, one call each).

Done since 14:15 (verified):
- **Merged gemini-track** (all 5 branches) into gemini-gateway. 61 lab tests pass in about 11 s; `make test` is green (581 passed, 6 skipped).
- `genai_client()` pins `api_version="v1beta"` on both the direct and the gateway path. This is G3's finding: google-genai 3.x defaults to v1, where caches 404. There is a test for it (the request path seen upstream is `/v1beta/...`). The showcase was re-recorded on v1beta (the old recording used `/v1` paths).
- Adaptive per-model limit (AIMD): halved on an upstream 429, +1 per 20 successes back up to the cap. The model slot is taken before the global slot, so a throttled model never holds global slots. `/healthz` shows `[limit, cap, inflight]` per model. Tests cover it.
- `canary/gemini/lab_replay.py`. `make lab-replay` now replays **every** `results/gemini/replay*` store keyless: the showcase plus manifest stores. `python -m canary.gemini.lab_replay --record NAME -- <cmd with {out}>` records any run, for example the ladder, through a recording gateway and writes a manifest with each episode's score and the sha256 of its step list. Replay reruns the command against a replay gateway and requires identical step lists.
  - Verified on a G2 ladder cell (flash-lite, low, easy, seed 0, 14 calls). The live run took 39 s; the replay is **step-for-step identical** in 0 s, without a key.
- `make lab-replay` from a fresh `git clone` with no `.env` → `REPLAY OK`.

**Proposal for G2/CEO:** run the real ladder grid on the Mac through a recording gateway: `python -m canary.gemini.with_gateway --record data/gemini/replay-ladder-full --max-concurrency 64 --model-limit gemini-4-carbon=8 -- python -m canary.gemini.ladder ...`. That costs nothing extra (about 4 KB of gzip per call), and we can then commit the subset of cells the submission cites, so judges can replay the actual table.

## Sat 14:15: gateway, sdk, lab_client hook, record/replay and FR8 scripts are done. **Blocker: no ssh to FR8 from here**

**Blocker: ssh to FR8 fails, cause found.** The Mac is on the venue LAN `192.168.8.0/24` (gateway `unifi.local.fr8.so`). Its public IP is **194.157.9.46, the same address that `freighter.fr8.so` resolves to**. FR8 sits behind the same NAT, and the router does not hairpin TCP 22 (ping answers from the router itself). The internal name `freighter-mgmt01.local.fr8.so` → 10.10.172.201 resolves, but the guest LAN does not route to it (TCP 22 times out). GitHub ssh works, so outbound 22 in general is fine.
- This blocks every FR8 step: deploy, gateway_up, smoke, worker arrays and the `ssh -R` fallback.
- Fixes, any one of them:
  - (a) Put the Mac on a different uplink, such as a phone hotspot.
  - (b) Turn on Tailscale with an exit node. It is installed but stopped. **This changes the network for every agent on this Mac**, so it is Silas's call.
  - (c) Ask FR8 staff for a route or port forward from the venue LAN to 10.10.172.201:22.
- The scripts take `FR8_HOST=...` to point at another ssh alias.
- **Silas: please pick one.** Until then, FR8 work cannot start. Gemini runs work from the Mac through a local gateway: at C=64 on flash it handles about 1,600 req/min, which is enough for the ladder.

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
