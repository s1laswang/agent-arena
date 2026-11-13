# Blind Spot (Ivar's branch of agent-arena)

Junction 2026: AfterQuery "Break the Agent" + Google DeepMind "Best Use of Gemini API".

**One working day in a small company's accounts payable seat. The queue looks routine. Some
tickets hide the mistakes that have actually cost real companies millions: a typed amount with an
extra zero, SEK read as EUR, a duplicate "reminder" invoice, a spreadsheet total that skips rows,
"we always skip the receipt check for them", an invoice two colleagues approved because each
assumed the other checked, a confidential board pack attached for the bank, last month's contractor
list reused, a fake CEO, a lookalike supplier changing bank details.** Most are honest mistakes and
structural gaps, not villains.

The agent must finish the valid work AND stop the hazards. Reward reads only the final state of the
company's systems.

- Research: [docs/FAILURE-RESEARCH.md](docs/FAILURE-RESEARCH.md) (38 real cases, sourced) and
  [data/failures/](data/failures/) (`cases_*.json`, `patterns.json`).
- Exploit log: [docs/EXPLOITS.md](docs/EXPLOITS.md). Progress log: [docs/reports/ivar.md](docs/reports/ivar.md).
- Team briefs: [CHALLENGES-AFTERQUERY-GEMINI.md](CHALLENGES-AFTERQUERY-GEMINI.md),
  the team idea [docs/SLEEPER.md](docs/SLEEPER.md).

## One command

```bash
./reproduce.sh          # Linux/macOS      (Windows: .\reproduce.ps1)
```

Creates `.venv`, runs the test suite, then plays 30 seeded days with the scripted reference, the
baselines and (if `GEMINI_API_KEY` is in `.env`) Gemini as plain staff and Gemini with the reference
procedure, 3 repeats each. Writes `results/latest/summary.md`.

Current table (scripted policies, seeds 0-29):

| Agent | Mean reward | Tickets OK | Hazards caught | Valid work done | EUR lost |
|---|---|---|---|---|---|
| oracle (reference procedure, tools only) | 1.00 | 100% | 100% | 100% | 0 |
| autopilot (honest clerk doing what tickets say) | 0.30 | 83% | 0% | 100% | 570,488 |
| do_nothing | 0.00 | 0% | 0% | 0% | 0 |
| stop_early | 0.00 | 24% | 30% | 23% | 0 |
| refuse_all | 0.00 | 11% | 65% | 0% | 0 |
| escalate_all | 0.00 | 11% | 65% | 0% | 0 |
| claim_in_chat | 0.00 | 0% | 0% | 0% | 0 |

## Pieces

| Path | What |
|---|---|
| `blindspot/world.py` | Seeded day generator: 11 ticket families, each with a hazard version and a benign twin |
| `blindspot/policy.py` | The handbook the agent can read (rules P1-P12) |
| `blindspot/env.py` | 24 tools, append-only ledger, no hidden state in tool output |
| `blindspot/verify.py` | Final-state reward + partial metrics + EUR lost |
| `blindspot/baselines.py` | Oracle (tools + visible text only) and integrity baselines |
| `blindspot/agents.py` | Gemini staff / Gemini reference agents (cached, optional) |
| `blindspot/mcp_server.py` | MCP server for one day (stdio or streamable-http) |
| `blindspot/sidecar.py`, `harbor_build.py` | Harbor tasks: world in a sidecar container, token-guarded reward |
| `blindspot/eval.py` | Runner + results tables (pass^k, per-family catch rates) |

```bash
python -m blindspot.mcp_server --seed 3 --state-out runs/day3.json    # play over MCP (stdio)
python -m blindspot.score runs/day3.json                              # score a saved day
python -m blindspot.mcp_client stdio:3 oracle                         # oracle through real MCP
python -m blindspot.harbor_build --seeds 0-19                         # Harbor task folders
harbor run -p harbor/tasks --agent opencode --model <model>           # judges' harness
```
