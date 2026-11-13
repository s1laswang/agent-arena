# TEAM: owners, interfaces, milestones (overnight, branch `justSilas`)

## Humans
| Who | GitHub | Tonight | Skills |
|---|---|---|---|
| Silas Wang (lead) | s1laswang | Owns `justSilas`; frees 1 V100; pastes keys | ML / infra |
| Momin | Momin010 | Own idea on own branch (bake-off) | TBD, ask |
| Ivar | ivarakerholm-wq | Own idea on own branch (bake-off) | TBD, ask |
| Chintu | Chintufp | Own idea on own branch (bake-off) | TBD, ask |

After the 09:00 pick, humans take ownership of: human playtests + the pitch/demo, the replay viewer, and checking the AfterQuery starter kit with the mentors. Assigned at review once skills are known.

## Claude org (CEO + 5 heads in terminals + up to 3 engineers each)
| Dept | Branch | Engineers | Owns (files) | Key interface it provides |
|---|---|---|---|---|
| CEO | `justSilas` | none | docs/PLAN, CONTRACT, TEAM, reports/CEO.md, integration | Contract arbitration, merges, morning report |
| ENV | `justSilas-env` | sim-engine, bayes-solver, world-text | canary/{rules,world,env,baselines}.py, solver/, text/ | `Env`, `SolverPolicy`, `regret.attribute`, TextProvider |
| HARNESS | `justSilas-harness` | mcp-server, harbor-isolation, reproduce-docs | canary/{mcp_server,eval}.py, harbor/, configs/, README, Makefile | MCP server URL, `run_episode`, `make eval/reproduce`, Harbor task |
| INTEGRITY | `justSilas-integrity` | baseline-fuzzer, exploit-hunter | canary/redteam/, baselines (extended), docs/EXPLOITS.md | Exploit list + regression tests |
| AGENTS | `justSilas-agents` | llm-providers, investigator-runner, gemini-roles | canary/llm/, canary/agents/, canary/analysis/, docs/reports/gap.md | `get_client`, `LLMPolicy`, clash/designer/analyst, gap table |
| FR8 | `justSilas-fr8` | slurm-ops, trainer | fr8/, train/ | Calibrated tier params, training data, trained LoRA + before/after |

## Dependency chain
- ENV `Env` v0 (02:45) unblocks HARNESS (MCP), INTEGRITY (fuzzing) and AGENTS (llm_policy).
- ENV solver v1 (04:00) unblocks FR8 J1/J3 and `solve.sh`.
- HARNESS MCP server (03:45) unblocks the OpenCode/Codex runs (AGENTS) and the LLM exploit hunter (INTEGRITY).
- FR8 J1 calibration (05:00) leads to the ENV tier freeze (06:30), then judge worlds (07:30).

## Milestones (Helsinki, Sat 14 Nov)
| Time | Milestone |
|---|---|
| 02:45 | Env v0 merged |
| 03:45 | MCP + `make eval AGENT=solver` |
| 04:00 | Solver v1 |
| 05:00 | First frontier episodes; J1 results |
| 05:30 | Harbor task + isolation check; J4 pilot |
| 06:30 | Baselines ≈ 0, no exploit beats the solver; tiers frozen |
| 07:30 | Gap table + failure modes; judge worlds committed |
| 08:30 | CEO writes docs/reports/MORNING.md |
| 09:00 | Review |

## Rules
See `docs/agents/COMMON.md`: git, secrets, FR8, reporting every 45 min in `docs/reports/<dept>.md`.
