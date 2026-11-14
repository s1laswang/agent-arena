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
| Day generator | `sleeper/tickets.py` | built | Builds the tickets from the seed, with a per-ticket done-check. |
| Day mix | `sleeper/daymix.py` | built | Picks goal kind, strategy and sleeper seat for each day id, with no-sleeper days. A day-mix bug in seat mode is being fixed by lead-env. |
| Company world | `sleeper/company.py` | built | Seats, permissions, two-person rules, systems state, the ledger. `World.call` is the only way an agent acts. |
| Day loop | `sleeper/day.py` | built | `run_day` plays each seat in order and advances the clock. |
| MCP server | `sleeper/mcp_server.py` | built | Exposes each seat's tools over MCP. |
| Events | `sleeper/events.py` | built | Mid-day new information and slow-burn steps. |
| Goals library | `sleeper/goals/` | built | Five goal kinds (fraud, leak, backdoor, sabotage, frame) with several strategies each. |
| Regret filter | `sleeper/regret.py` | built | Filters sleeper strategies. |
| Verifier | `sleeper/verifier.py` | built, rewrite pending | Scores the final company and ledger. The whitelist rewrite is at 8c65aa1 on `sleeper/rw-verifier-core`, not on `momin`. |
| Canary tokens | `sleeper/canary.py` | built | Unique token per secret, with encoded variants. |
| Canary days | `sleeper/days/canaries.py` | built | No-sleeper days and impossible tickets that test the verifier. |
| Baselines | `sleeper/baselines.py` | built | stop_early, quarantine_all, refuse_all teams. |
| Scripted agents | `sleeper/scripted.py` | built | No-op and oracle agents that run without a key. |
| Gemini client | `agents/gemini.py` | built | Cached Gemini calls. |
| Sleeper agent | `agents/sleeper_agent.py` | built | The covert agent. |
| Honest staff | `agents/staff.py` | built | The 8 role-prompted employees, scripted or Gemini. |
| Reference and oracle | `agents/reference.py` | built | Reference team and the scripted oracle team. The oracle uses the hidden sleeper identity. |
| Evidence-only reference | `agents/procedure.py` | planned | A reference that works only from logs and records. In progress. |
| Runner | `lab/run.py`, `lab/results.py` | built | Runs a team over days and trials, writes `results/runs/<run_id>/`. |
| Eval | `lab/eval.py` | built | What `make eval` calls. Writes `results/eval/summary.json` and `gap.md`. |
| Failure analysis | `lab/analyse.py` | branch | Labels failures from transcripts. On `sleeper/lab-analyst-names`. |
| Landing table | `scripts/landing_table.py` | built | Staff against oracle per strategy, writes `results/landing/`. |
| Harbor tasks | `harbor/` | built | Packaging and seat mode for the judge harness. |
| Training | `train/` | built | Small model fine-tune data and SFT. |
| Cluster | `cluster/` | built | Slurm scripts for FR8. |
| Dashboard | `web/` | built | Replays a day from `web/days/*.json`. |

## Reading a result

`verifier.score` returns a `Result` with reward, tickets done, harm list, false quarantines and whether the sleeper was caught. `lab.run` collects Results into `summary.json` (reward, pass^k, sleeper success rate, false accusations, ticket completion) under `results/runs/<run_id>/`. `lab.eval` combines runs into `results/eval/summary.json` and `gap.md`. The dashboard replays a saved day.
