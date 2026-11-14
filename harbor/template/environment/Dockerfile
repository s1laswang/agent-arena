# Agent container (`main`). Deliberately empty of game internals: no canary source, no world data,
# no SALT / CANARY_WORLD_SECRET, no ledger token. The game is reachable only over MCP at
# http://canary-server:8765/mcp (a compose sidecar whose filesystem and processes this container
# cannot see). Harbor installs the agent (e.g. OpenCode) into this image at setup time.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates bash procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Project-level OpenCode config (the same server Harbor registers from task.toml
# [[environment.mcp_servers]]), so a manual `opencode` run inside the container also finds the game.
COPY opencode.json /app/opencode.json
