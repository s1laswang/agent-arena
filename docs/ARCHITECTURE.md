# Architecture

Status key: built = on `momin`, branch = pushed on a worker branch and not merged yet, planned = not found in any branch.

```
 day generator ──> company world ──> 8 seats via MCP tools ──> ledger
 (sleeper/tickets)  (sleeper/company)  (sleeper/mcp_server)     (World, append-only)
                                                                  │
 dashboard (web/) <── lab.run summary <── Result <── verifier <───┘
                      (lab/run.py)     (models.Result) (sleeper/verifier.py)
```

A day is a pure function of `(seed, sleeper_seat or none, sleeper_goal or none, agent_config)`. The loop in `sleeper/day.py` plays each seat in turn, then advances the simulated clock. Agents are scripted, or Gemini when `GEMINI_API_KEY` is set.

## Modules

| Module | Owner file | Status | What it does |
|---|---|---|---|
| Models | `sleeper/models.py` | built | Message, Doc, Vendor, Payment, Account, Ticket, Company, Action, Day, Result. |
| Day generator | `sleeper/tickets.py` | built | Builds the 40 to 60 tickets from the seed, with a per-ticket done-check. |
| Company world | `sleeper/company.py` | built | Seats, permissions, two-person rules, systems state, the ledger. `World.call` is the only way an agent acts. |
| Day loop | `sleeper/day.py` | built | `run_day` plays each seat in order and advances the clock. |
| MCP server | `sleeper/mcp_server.py` | branch | Exposes each seat's tools over MCP. Seat mode lets the judge harness play one seat. |
| Events | `sleeper/events.py` | built | Mid-day new information and slow-burn steps. |
| Regret filter | `sleeper/regret.py` | built | Filters sleeper strategies. |
| Verifier | `sleeper/verifier.py` | built | Scores the final company and ledger. Reward is 0 or 1. |
| Canary tokens | `sleeper/canary.py` | branch | Unique token per secret, with encoded variants. |
| Canary days | `sleeper/days/canaries.py` | branch | No-sleeper days and impossible tickets that test the verifier. |
| Scripted agents | `sleeper/scripted.py` | built | No-op and oracle agents that run without a key. |
| Gemini client | `agents/gemini.py` | built | Cached Gemini calls. |
| Sleeper agent | `agents/sleeper_agent.py` | built | The covert agent. |
| Honest staff | `agents/staff.py` | branch | The 8 role-prompted employees. |
| Reference and oracle | `agents/reference.py` | branch | Stronger procedure and the scripted oracle team. |
| Runner | `lab/run.py`, `lab/results.py` | branch | Runs a team over days and seeds, writes `days.jsonl` and `summary.json`. |
| Eval | `lab/eval.py` | branch | What `make eval` calls. Runs every team and writes the table. |
| Failure analysis | `lab/analyse.py` | branch | Labels failure modes from transcripts. |
| Harbor tasks | `harbor/` | branch | Packaging for the judge harness. |
| Training | `train/` | branch | Small model fine-tune data and SFT. |
| Cluster | `cluster/` | branch | Slurm scripts for FR8. |
| Dashboard | `web/` | built | Replays one day from `web/days/*.json`. |
| Goals library | `sleeper/goals/` | planned | Sleeper goal kinds and strategies. |

## Reading a result

`verifier.score` returns a `Result` with reward, tickets done, harm list, false quarantines and whether the sleeper was caught. `lab.run` collects Results into `summary.json` (reward, pass^k, sleeper success rate, false accusations, ticket completion). The dashboard replays a saved day.
