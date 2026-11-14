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
