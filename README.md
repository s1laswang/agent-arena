# Blind Spot (Ivar's branch of agent-arena)

Junction 2026: AfterQuery "Break the Agent" + Google DeepMind "Best Use of Gemini API".

**One working day in a small company's accounts payable seat. The queue looks routine. Some
tickets hide the mistakes that have actually cost real companies millions: a typed amount with an
extra zero, SEK read as EUR, a duplicate "reminder" invoice, a spreadsheet total that skips rows,
"we always skip the receipt check for them", an invoice two colleagues approved because each
assumed the other checked, a confidential board pack attached for the bank, last month's contractor
list reused, a fake CEO, a lookalike supplier changing bank details, a buyer who approved the order
AND signed for the goods, a bank "payee name does not match" alert nobody opened, a manager pushing a
cost into next month to hit a target, a warehouse supervisor whose "only a quarter arrived" got
overruled.** Most are honest mistakes, structural gaps and cultural blind spots, not villains.

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

Current table (scripted policies, seeds 0-49, 15 families):

| Agent | Mean reward | Tickets OK | Hazards caught | Valid work done | EUR lost |
|---|---|---|---|---|---|
| oracle (reference procedure, tools only) | 1.00 | 100% | 100% | 100% | 0 |
| autopilot (honest clerk doing what tickets say) | 0.32 | 82% | 0% | 100% | 717,003 |
| do_nothing | 0.00 | 0% | 0% | 0% | 0 |
| stop_early | 0.00 | 30% | 36% | 29% | 0 |
| refuse_all | 0.00 | 11% | 61% | 0% | 0 |
| escalate_all | 0.00 | 11% | 61% | 0% | 0 |
| claim_in_chat | 0.00 | 0% | 0% | 0% | 0 |

## Pieces

| Path | What |
|---|---|
| `blindspot/world.py` | Seeded day generator: 15 ticket families, each with a hazard version and a benign twin |
| `blindspot/policy.py` | The handbook the agent can read (rules P1-P15) |
| `blindspot/env.py` | 25 tools (incl. bank portal alerts), append-only ledger, no hidden state in tool output |
| `blindspot/verify.py` | Final-state reward + partial metrics + EUR lost |
| `blindspot/baselines.py` | Oracle (tools + visible text only) and integrity baselines |
| `blindspot/agents.py` | Gemini staff / Gemini reference agents (cached, optional) |
| `blindspot/mcp_server.py` | MCP server for one day (stdio or streamable-http) |
| `blindspot/sidecar.py`, `harbor_build.py` | Harbor tasks: world in a sidecar container, token-guarded reward |
| `blindspot/eval.py` | Runner + results tables (pass^k, per-family catch rates) |
| `blindspot/play.py` | Play a day one tool call per shell command (used for blind frontier-agent runs) |
| `blindspot/cost_table.py` | Builds [pitch/COST.md](pitch/COST.md): real-world loss vs simulated loss per pattern |
| `blindspot/export_sft.py` | Oracle trajectories as tool-calling SFT data ([docs/TRAINING.md](docs/TRAINING.md)) |

```bash
python -m blindspot.mcp_server --seed 3 --state-out runs/day3.json    # play over MCP (stdio)
python -m blindspot.score runs/day3.json                              # score a saved day
python -m blindspot.mcp_client stdio:3 oracle                         # oracle through real MCP
python -m blindspot.harbor_build --seeds 0-19                         # Harbor task folders
harbor run -p harbor/tasks --agent opencode --model <model>           # judges' harness
python -m blindspot.play new --session runs/play/me.json --seed 7     # play by hand / with any CLI agent
python -m blindspot.play call --session runs/play/me.json list_tickets
```
