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

## 03:25 status
- Official v1.2 (interim 29/40 gpt-5.5; `python -m canary.analysis.gap --runs data/runs/committed`):
  - **medium:** solver .690 | gpt-5.5 .605 (88%) | Grok .672 (97%)
  - **hard:** solver .584 | gpt-5.5 .544 (93%) | Grok .567 (97%)
  - → no gap on v1.2. Root cause: true V in `status` reveals each leak the same day, which defeats the delay (from Grok's own write-up). CEO decision: **v1.3** (known-V only + a stronger solver) is the official measurement; v1.2 = the "before" record.
- Merged (3bae6b6): MCP frontier runners (solver-over-MCP parity ✓), Codex gpt-5.5 over MCP (hard 0: 0.67 ✓), Grok import (10 episodes, judge seeds, ledger-reported), invalid-episode filter.
- OpenCode gpt-5.6-sol: ChatGPT credits depleted (429, ~5.8 days); 2/10 valid. **Silas morning item.**
- MCP server kills at 02:43/02:46/03:01: caused by the Grok eval client (`pkill -f canary.mcp_server` in ~/canary-eval/client/start); it has finished.
- Next: on the v1.3 merge, gpt-5.5 20+20 in-process + Codex gpt-5.5 5+5 → data/runs/committed/v1.3/; then tags, accusation audit, ablations, Forge vs gpt-5.5, final gap.md by 08:00.

### Grok re-run prompt for Silas (morning, tiers v1.3)
Run Grok exactly as before (only `configs/README.md` may be read; no source, tests or docs; don't use the reference solver), against the merged v1.3 `justSilas`. **Don't pkill other processes**: start your own server on a unique port and stop only its pid.

> You are the head of security at a company with a mole leaking documents. Start the Canary environment from the `justSilas` branch: `make setup`, then for each episode `CANARY_TIER=<tier> CANARY_SEED=<seed> CANARY_LEDGER_TOKEN=<random> CANARY_PORT=<unique free port> make mcp`, and connect to http://127.0.0.1:<port>/mcp. Read ONLY configs/README.md (no source, tests or other docs) and the MCP server's instructions. Play judge seeds 900000–900004 on medium and on hard (10 episodes), one server process per episode, and stop only the server you started (by its pid; never pkill). After each episode record GET /ledger?token=<token>. Write docs/reports/grok-agent-v1.3.md with a table (tier, seed, score, accused, correct, final day, tool calls) plus a 3-bullet rationale per episode, and save each episode's tool-call transcript to docs/reports/grok-agent-v1.3/<tier>-<seed>.jsonl (one {ts, tool, args, isError, result} per call).

Then: `python -m canary.analysis.import_transcript --agent grok --src docs/reports/grok-agent-v1.3 --report docs/reports/grok-agent-v1.3.md --out data/runs/committed/v1.3/grok`.

## 03:55 status
- Done (verified: make test 482 passed; tables regenerated from committed data):
  - **docs/reports/gap.md FINAL** for the night. v1.2 official: gpt-5.5 87% / 86% of the solver. v1.3 small-n: 44% / ≈0%. Failure mode: day-14 premature accusations (>90% of value lost).
  - Codex gpt-5.5 v1.2 5+5 complete. Grok imported. The reference definition agreed with ENV (v1.2 = db104c9 episodes; v1.3 = 0933805).
  - Forge J5b spec implemented; FR8 is running J5b on v1.3.
- **Spend:** ≈$260 est. (cap $150 hit at 03:30); all API-billed runs stopped. Codex is in API-key mode, so it is not a free path.
- Blockers / decisions for Silas (morning):
  1. Approve ~$60–90 to finish v1.3 gpt-5.5 to 20+20.
  2. GEMINI_API_KEY → `make gemini-check`, the Gemini frontier family on v1.3, the Gemini Forge mutator.
  3. OpenCode credits or `codex login` with ChatGPT for subscription-billed runs.
  4. Grok re-run on v1.3 (prompt above).
- Next (zero cost): review J5b's HOF when FR8 pings; keep the reports current.

## 04:07 status: overnight wrap-up
- Done (verified: make test 490 passed on justSilas 3ebd0ed):
  - **Scaffold fix** (zero API calls, stub-tested): LLMPolicy full history by default (no turn window, no truncation); OpenAI Responses API with encrypted reasoning carried across turns; reasoning_effort explicit = "medium" (Codex's default for gpt-5.5, from its model catalog; OpenCode's default unverified); everything logged in meta.json.
  - **Parity test:** the real MCP server's instructions and the Codex/OpenCode prompt are byte-identical to LLMPolicy's; the 13 tools are identical in name, description, schema and order.
  - gap.md: caveats first, scaffold-vs-harness table, fairness argument, kill-switch history.
- **Untested live:** whether gpt-5.5 accepts the encrypted-reasoning replay as built, and the real usage fields. Check with ONE smoke episode first.

### Morning commands (after Silas approves spend, ≈$3/episode for gpt-5.5)
1. Smoke (1 episode, ≈$3): `uv run --python 3.12 --extra llm --extra dev python -m canary.agents.play --agent openai:gpt-5.5 --tier medium --seeds 0 --smoke`. Check the episode completes, meta.json has api=responses and usage>0.
2. Paired re-run on the same v1.3 seeds, n=10 per tier (≈$60 in-process + ≈$30 Codex):
   - `python -m canary.agents.play --agent openai:gpt-5.5 --tier medium --seeds 0-9 --out data/runs/committed/v1.3/gpt-5.5-full/medium` (same for hard)
   - `python -m canary.agents.frontier.codex_run --model gpt-5.5 --tier medium --seeds 0-9 --jobs 2 --out data/runs/committed/v1.3/codex-gpt-5.5/medium` (same for hard)
3. `python -m canary.analysis.gap --runs data/runs/committed/v1.3`, then ENV's regret_report, then update gap.md (replace the small-n in-process rows; keep the window-scaffold rows labelled as such).
4. With GEMINI_API_KEY: `make gemini-check`, then the same paired run with `--agent gemini:<model>` as the third family.
