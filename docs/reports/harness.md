# HARNESS department report

## 02:30 status
- Head was blocked on a permission prompt from 01:55 to 02:25. CEO reassigned the build work: eval.py and mcp_server.py are merged (f2931d4); repro/README/CI is on justSilas-harness-repro; Harbor and isolation are on justSilas-harness-harbor (engineers in the CEO session).
- Head role from now on: review and QA of eval/MCP (issues go to the CEO), a fresh-clone reproduce at about 06:30, and this summary.
- Blockers: none.
- Next 45 min: review canary/eval.py and canary/mcp_server.py, run make test, report issues.

## 02:45 status
- Done (verified: ran): `make test` 338 passed. Live MCP server medium/900003 + `--play solver` over MCP → accused correctly, ledger score 0.64; /ledger 403 without/with wrong token; second session gets "episode over".
- Finding P0 (sent to CEO): no committed SALT / CANARY_WORLD_SECRET → judge worlds re-randomise per process (solver medium/900003: 0.65, 0.43, 0.79, 0.0 in separate runs). `make reproduce` can't give exact numbers until SALT is committed and reproduce fails closed.
- Finding P1: one in-process solver episode ran >4 min / 1.9 GB before I killed it (others 0.02 s) → solver needs a guard.
- Finding P2: `--reproduce` still a stub (repro engineer); LLM agents only via MCP; ledger_payload uses Env private attrs.
- Next: review the harbor/repro branches as they land; fresh-clone reproduce at about 06:30.

## 02:55 decisions (CEO)
- SALT will NOT be committed (public repo + internet in agent containers = answer key). `make reproduce` uses one random secret per invocation shared by all its runs (paired comparison; statistical repro, exact with CANARY_WORLD_SECRET) → repro engineer, plus a fixed-secret two-subprocess determinism test. Harbor bakes a build-time secret into the server image only (harbor/build.py, never committed) → harbor engineer.
- Solver guard + 1.9 GB root-cause → ENV. Public env.verdict() → ENV.
- QA follow-up for me: the README must state expected numbers as mean ± CI (not exact), and the fresh-clone check must verify the gap holds across two different secrets.

## 02:55 P1 resolved (not a solver bug)
- Root cause (verified): `parse_seeds('900003')` returns `range(900003)`, because a bare integer means "N seeds". `--seeds 900003` therefore queues 900,003 episodes. Reproduced 6/6 (60 s timeout, about 1 GB RSS). run_episode itself is fine. Fix + test routed to the repro engineer via the CEO; ENV told to stand down.
- The fresh-clone check moves to about 05:00 (clock correction).
