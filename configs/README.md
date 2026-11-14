# Running an agent against the Canary MCP server

## 1. Start the server (one episode per process)

Default recommended non-Harbor launch: write `0600` episode and token files first with `--write-episode-file`,
then launch the server with `CANARY_EPISODE_FILE` and `CANARY_LEDGER_TOKEN_FILE` so `/proc/<pid>/environ` and
`ps eww` never contain `CANARY_SEED`, `CANARY_WORLD_SECRET`, or token values (EXPLOITS #25):

```bash
umask 077; d=$(mktemp -d)
uv run --python 3.12 python -m canary.mcp_server \
  --write-episode-file "$d/episode.json" --tier medium --seed 900007 \
  --ledger-token-out "$d/ledger_token"
CANARY_EPISODE_FILE="$d/episode.json" CANARY_LEDGER_TOKEN_FILE="$d/ledger_token" make mcp
```

MCP (streamable HTTP) listens at `http://127.0.0.1:8765/mcp` by default. If you also use a fixed judge world
secret, copy it to a `0600` file (`cp /path/to/world_secret "$d/world_secret" && chmod 600 "$d/world_secret"`)
and pass `CANARY_WORLD_SECRET_FILE="$d/world_secret"` (or `--world-secret-file "$d/world_secret"`). Without it,
judge worlds use a fresh per-process random secret in memory. Python callers can also call
`canary.mcp_server.spawn_isolated_server(tier, seed)`, which writes temporary `0600` files and strips
`CANARY_SEED`, `CANARY_TIER`, `CANARY_LEDGER_TOKEN`, and `CANARY_WORLD_SECRET` from the child environment.

| config (`*_FILE` / CLI flag / env var) | default | meaning |
|---|---|---|
| `CANARY_EPISODE_FILE` / `--episode-file` | unset | `0600` JSON `{"tier": ..., "seed": ...}`. Only judge (900000-900029) and held-out (800000-800199) seeds are served |
| `CANARY_LEDGER_TOKEN_FILE` / `--ledger-token-file` | unset | `0600` file with grader token for `GET /ledger?token=...`; unset means `/ledger` always returns 403 |
| `CANARY_WORLD_SECRET_FILE` / `--world-secret-file` | unset | `0600` file with judge world secret (>= 16 bytes), applied in-process and never exported to `os.environ` |
| `CANARY_ADMIN_TOKEN_FILE` | unset | `0600` file with token for `POST /admin/reset?token=...` body `{"tier": ..., "seed": ...}` |
| `CANARY_HOST` / `CANARY_PORT` | `127.0.0.1` / `8765` | bind address; change the port to run several episodes in parallel |
| `CANARY_ALLOW_DEV=1` | unset | also serve public dev/train seeds (internal testing only) |
| `CANARY_PROVIDER` | `template` | text provider (`gemini:<model>` when configured) |
| `CANARY_TIER` / `CANARY_SEED` / `CANARY_LEDGER_TOKEN` / `CANARY_ADMIN_TOKEN` | `easy` / `900000` / unset / unset | legacy plain env fallbacks for local dev only (CLI flags and `*_FILE` vars win; never use plain secret env vars in judge runs because `/proc/<pid>/environ` exposes them to same-uid processes) |

A missing, empty or malformed secret file makes the server refuse to start (exit 2) without echoing the
contents. Note that `0600` stops `/proc/<pid>/environ` inspection, not a same-uid process reading the file path
itself; the full isolation boundary is running the server outside the agent's sandbox (Harbor sidecar).

The agent sees only the 13 tools from `Env.tools_spec()` and the rules as MCP `instructions`. The seed,
the world and the mole are never in a tool result or error.

## 2. OpenCode

`configs/opencode/opencode.json` is a project config with one remote MCP server. Copy it into the
directory you run OpenCode from (or point `OPENCODE_CONFIG` at it):

```bash
mkdir -p /tmp/canary-run && cp configs/opencode/opencode.json /tmp/canary-run/
cd /tmp/canary-run && opencode mcp list
opencode run -m google/gemini-4-carbon "You are the security lead. Use the canary tools; the rules are in the MCP instructions. Find and accuse the mole."
```

The flat `"mcp": {"canary": {...}}` form and the newer `"mcp": {"servers": {"canary": {...}}}` form both
connected with OpenCode 1.18.29.

## 3. Codex CLI (untested end to end)

```bash
codex -c 'mcp_servers.canary.url="http://127.0.0.1:8765/mcp"' exec "<same prompt>"
```

## 4. Score it (grader side)

```bash
curl -s "http://127.0.0.1:8765/ledger?token=$(cat "$d/ledger_token")"
```

Returns JSON `{"score", "done", "end_reason", "accused", "accused_correct", "final_day", "V", "episode", "ledger": [...]}`.

Reference run over MCP (no keys needed): `python -m canary.mcp_server --play solver --url http://127.0.0.1:8765/mcp`.
