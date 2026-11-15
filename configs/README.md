# Running an agent against the Canary MCP server

## 1. Start the server (one episode per process)

```bash
CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=<random> make mcp
# MCP (streamable HTTP): http://127.0.0.1:8765/mcp
```

| env var | default | meaning |
|---|---|---|
| `CANARY_HOST` / `CANARY_PORT` | `127.0.0.1` / `8765` | bind address; change the port to run several episodes in parallel |
| `CANARY_TIER` / `CANARY_SEED` | `easy` / `900000` | the episode. Only judge (900000-900039) and held-out (800000-800199) seeds are served |
| `CANARY_ALLOW_DEV=1` | unset | also serve public dev/train seeds (internal testing only) |
| `CANARY_LEDGER_TOKEN` | unset | grader token for `GET /ledger?token=...`; unset means `/ledger` always returns 403 |
| `CANARY_ADMIN_TOKEN` | unset | enables `POST /admin/reset?token=...` with body `{"tier": ..., "seed": ...}` |
| `CANARY_PROVIDER` | `template` | text provider (`gemini:<model>` in the morning) |

**Judge runs: use secret files, not env vars (EXPLOITS #27).** A same-uid process can read the server's
exec-time environment (`/proc/<pid>/environ`, `ps eww`). Put the episode, world secret and tokens in 0600
files instead; a `*_FILE` var wins over its plain counterpart, which is then not needed:

```bash
umask 077; d=$(mktemp -d)
echo '{"tier": "medium", "seed": 900007}' > $d/episode.json
openssl rand -hex 32 > $d/ledger_token          # the grader reads this file
cp /path/to/world_secret $d/world_secret         # or omit: judge worlds then use a per-process random secret
CANARY_EPISODE_FILE=$d/episode.json CANARY_LEDGER_TOKEN_FILE=$d/ledger_token \
  CANARY_WORLD_SECRET_FILE=$d/world_secret make mcp
```

`CANARY_ADMIN_TOKEN_FILE` works the same way. A missing, empty or malformed file makes the server refuse
to start (exit 2) without echoing the contents. Note that 0600 does not stop a same-uid reader of the file
itself; the real boundary is running the server outside the agent's sandbox (Harbor sidecar).

The agent sees only the 13 tools from `Env.tools_spec()` and the rules as MCP `instructions`. The seed,
the world and the mole are never in a tool result or error. Judge worlds also need `CANARY_WORLD_SECRET`
(or the SALT file) on the server side so the same seed gives the same world across restarts.

## 2. OpenCode

`configs/opencode/opencode.json` is a project config with one remote MCP server. Copy it into the
directory you run OpenCode from (or point `OPENCODE_CONFIG` at it):

```bash
mkdir -p /tmp/canary-run && cp configs/opencode/opencode.json /tmp/canary-run/
cd /tmp/canary-run && opencode mcp list          # expect: canary connected
opencode run -m openai/<model> "You are the security lead. Use the canary tools; the rules are in the MCP instructions. Find and accuse the mole."
```

The flat `"mcp": {"canary": {...}}` form and the newer `"mcp": {"servers": {"canary": {...}}}` form both
connected with OpenCode 1.18.29.

## 3. Codex CLI (untested end to end)

```bash
codex -c 'mcp_servers.canary.url="http://127.0.0.1:8765/mcp"' exec "<same prompt>"
```

## 4. Score it (grader side)

```bash
curl -s "http://127.0.0.1:8765/ledger?token=$CANARY_LEDGER_TOKEN"
# {"score", "done", "end_reason", "accused", "accused_correct", "final_day", "V", "episode", "ledger": [...]}
```

Reference run over MCP (no keys needed): `python -m canary.mcp_server --play solver --url http://127.0.0.1:8765/mcp`.
