# HEAD-AGENTS report

## 02:05 status
- Done: worktree `wt/justSilas-agents`; engineer worktrees `-llm`, `-runner` created.
- In progress:
  - llm-providers (stub/openai/gemini-mocked, check.py; ETA 03:00)
  - investigator-runner (LLMPolicy + FakeEnv, then OpenCode/Codex MCP runners; ETA 03:30)
- Blockers: no `.env` / OPENAI_API_KEY in the shared checkout (CEO asked Silas). Until it exists, the frontier = OpenCode + Codex on their own logins over MCP (CEO decision).
- Next 45 min: review the engineers' first commits; spawn gemini-roles after llm-providers lands.

## 02:35 status
- Done (verified: make test on justSilas, 66 passed / 1 skipped):
  - canary/llm (stub/openai/gemini-mocked) merged 25b3d70. Live `openai:gpt-5-mini` check passed.
  - Gap analysis (`python -m canary.analysis.gap`, with the 85% alert) merged.
  - Frontier default = $CANARY_OPENAI_MODEL or gpt-5.5, merged 7d60f81. One-call model probe: gpt-5.5 / gpt-5.6-sol / gpt-5.6-terra work; gpt-5.5-pro is Responses-only.
- In progress:
  - investigator-runner (LLMPolicy on the real Env + OpenCode/Codex MCP runners)
  - gemini-roles (world builder, arena mole, designer, analyst, clash, pitch/GEMINI.md; stub)
  - mole-forge (stub mutator, fitness with the solver feasibility constraint, evolve CLI, FR8 sbatch)
- Notes: v0.3 scoring (wrong = -1) handled: the analysis supports negative scores; the prompt uses the Env instruction verbatim.
- Blockers: none. Waiting on the DSL interpreter (ENV) and the MCP server (HARNESS) for the Forge real runs and the OpenCode/Codex live runs.
- Next 45 min: first gpt-5.5 episodes on medium; review/merge the runner.

## 02:50 status
- Done (verified):
  - LLMPolicy + play CLI + OpenCode/Codex runners merged (15caa46).
  - Mole Forge on the real DSL/solver/Env merged (d803011); make test 285 passed.
  - Real forge on medium (pop 8, 5 gens, 10 seeds): best feasible fitness 0.276 → 0.751; the top mole frames the decoy and drives the heuristic to ≈0 while the solver stays 0.75 (acc 1.0).
  - References, medium seeds 0-9: solver 0.777±0.046 (acc 1.0), heuristic 0.496, do-nothing 0, stop-early −1.0, random −0.80.
- **GAP ALERT sent to CEO:** gpt-5.5 on medium seeds 0-1 scored 0.76/0.83 (both correct, day 6) vs solver 0.80/0.75 = 103%. CEO decision: contract v0.4 hardening (ENV); headline gap = HARD + Forge moles; medium = "fair" tier.
- In progress:
  - gpt-5.5 medium seeds 2-9 + hard seeds 0-9; hard references.
  - Runner engineer: regret tags, hint ablations (stub first), OpenCode gpt-5.6-sol one live seed once MCP lands.
  - Forge engineer: stronger investigator set, a hard forge run, HOF vs gpt-5.5 validation (≤$25).
  - FR8: J5 forge job handed over.
- Notes: OpenCode's ChatGPT login rejects gpt-5.5 → OpenCode runs use gpt-5.6-sol (CEO). Morning: API-key auth for OpenCode (Silas).
- Spend so far: ≈ $1.6 OpenAI.

## 02:35 status (note: the earlier entries' times were estimates; from now on stamped with `date`)
- Done (verified):
  - Failure tags (`canary.analysis.tags`), hint ablation runner (stub-tested), accusation audit (`canary.analysis.accuse`), recursive run loading. make test 322 passed.
  - docs/reports/gap.md draft: v1 partials, hard diagnosis, annotated medium seed 5 failure.
- Gap (tiers v1 partials, pre-fix solver): medium gpt-5.5 14% of solver (n=3); hard 113% (n=4) → **kill switch on hard**, sent to the CEO + ENV with the root cause (the solver's canary partition ignores the careful-mole size weighting; gpt-5.5 uses small canary groups).
- In progress:
  - v1 gpt-5.5 runs continuing (data/runs_v1).
  - Runner engineer: OpenCode gpt-5.6-sol + Codex over the merged MCP server.
  - Forge engineer: hard forge + HOF vs gpt-5.5 validation.
  - FR8 J5 forge (500 gens) on the Mac.
- Next: on ENV's freeze (~07:00) the OFFICIAL run (gpt-5.5 20+20 dev seeds + OpenCode 5+5) → data/runs/committed; then tags, ablations, final gap.md.
