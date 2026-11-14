"""Frontier CLI agents (OpenCode, Codex) playing Canary over the HARNESS MCP server, judges' harness shape.

Each run: a fresh temp dir outside the repo with no repo source, MCP-only access to the env,
the CLI's own stored login (we never read credential files), then the server-side
ledger/history is fetched and converted to EpisodeResult JSONL under data/runs/<run_id>/.
"""
