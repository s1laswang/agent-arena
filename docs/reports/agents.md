# HEAD-AGENTS report

# Relaunch (branch `justSilas-agents2`)

## 22:55 Hint ablation v2 RESULT (gemini-4-carbon in-process, v1.4 hard, dev seeds 0–9, n=10/arm) — INCONCLUSIVE
`data/runs/ablate-v2-hard-gemini/ablation_combined.{json,md}`; hints = HINTS_V2 (fact-only; tests/test_agents_policy.py).
| arm | mean | acc | premature_accusation tag rate |
|---|---|---|---|
| control | +0.427 | 0.90 | 0.10 |
| premature_accusation hint | +0.487 | 1.00 | 0.00 |
| decoy_chase hint | +0.648 | 1.00 | 0.00 |
- Paired diff vs control (bootstrap 95%): premature_accusation +0.06 [−0.17, +0.41]; decoy_chase +0.22 [−0.05, +0.61].
  Both are driven by control's single wrong accusation (seed 3, −1.0), which both hint arms avoided. Excluding seed 3:
  −0.09 [−0.20, +0.05] and +0.05 [−0.08, +0.19].
- Honest reading: on v1.4 hard, gemini-4-carbon rarely fails (1/10 control episodes wrong; decoy_chase tag 0/10 even
  without a hint), so there is little for a hint to fix. No causal claim. This agrees with the CEO's v1.4 no-gap
  measurement and motivated the expert tier (Track 2, branch justSilas-expert). The CEO's B1 run (ev_delay, n=20 paired)
  is the larger test.

## 19:xx WS3 FINAL SUMMARY (honest; for README/pitch)
Charts: `results/ws3_rl_mole_curve.png`, `results/ws3_grpo_mole_curves.png` (`uv run --extra plot python scripts/ws3_charts.py`).

### A. CPU RL mole (canary/forge/rl_mole.py; REAL training, scripted investigators)
- MLP policy over MoleView features → (leak selector, frame selector); REINFORCE on solver − max investigator,
  Lagrange multiplier for solver accuracy ≥ 0.75; 80 iters × 48 train seeds on a Mac CPU (~15 min).
- Held-out (hard, seeds 200000–099, n=100, paired bootstrap 95% CI, RL − default) — `data/rl_mole/heldout_paired.json`:
  - every investigator gets worse: solver −0.17 [−0.27,−0.08], grok_tactics −0.21 [−0.29,−0.13],
    hinted_heuristic −0.17 [−0.28,−0.07], heuristic −0.37 [−0.56,−0.18];
  - solver accuracy 0.97 → 0.75 [0.67,0.83]: still catchable, at the floor (CI dips below);
  - regret vs the strongest scripted investigators unchanged (grok +0.04 [−0.09,0.17], hinted +0.00 [−0.15,0.14]).
- Learned behaviour is diverse, not collapsed: leak newest 38% / none 19% / most_recipients 15% / random 12% / oldest 11%
  / fewest 6%; frame none 34% / random_peer 29% / most_restricted_peer 20% / decoy 17%.
- Pitch line: "the environment supports trained adversaries: an RL mole makes it harder for every investigator while
  staying (borderline) catchable." NOT a gap result. `hard_rl` track exists but is OUT of `make reproduce` (CEO).
- Not done: Gemini spot check on hard_rl (first attempt invalid due to the thought-signature bug; rerun queued after
  the hint ablation).

### B. GRPO LLM mole (train/grpo_mole.py; Qwen2.5-0.5B-Instruct, LoRA, fp16 V100, FR8 jobs 44424/44425/44426,
400 steps each, group 8 × 4 prompts; REAL small model, scripted investigators) — curves in `data/grpo_mole/`
- Format learning works: valid action JSON 3–16% at step 0 → 97–100% by step ~50, all three seeds.
- Strategy learning does NOT: reward among VALID completions, first 50 vs last 50 steps:
  seed 0 −0.085 → −0.072, seed 1 −0.070 → −0.085, seed 2 −0.027 → −0.011 (flat within noise).
  The headline reward rise (−0.9 → −0.14 / −0.29 / +0.34) is almost entirely the −1 invalid penalty disappearing.
- Mode collapse: each seed ends on ONE action for every state (seeds 0, 2: `none/decoy` = never leak that day, frame
  the decoy; seed 1: `newest/decoy`). Solver accuracy stays 0.93–0.96: these moles remain catchable.
- Why (diagnosis): a one-day counterfactual reward is sparse and noisy relative to the per-state action effect;
  with no KL/entropy term and a 0.5B policy, GRPO locks onto the first action that is valid and not bad.
- Honest label: "a real 0.5B model learned the mole's action format from env reward in 50 steps; it did not learn a
  better strategy than the scripted mole." Next steps if anyone continues: multi-day horizon reward, entropy bonus or
  KL to the base, condition on the CPU RL mole as base policy (`--base-policy`).

## 17:xx status
- Done: **in-process Gemini bug found** (thought_signature dropped on turn 2 → 400; swallowed into res.meta → silent score 0).
  Reported to CEO; fixed on justSilas (e8a6fdf, from gemini-track); merged here. My first RL spot check (12 eps) was
  entirely invalid because of it and was discarded (not committed).
- Verified that gemini-4-carbon works in-process after the fix: hard seed 200000 → accused correctly, 0.80, 57 calls,
  ~20 min, est. $0.76.
- Done (verified: tests/test_agents_policy.py): hint set **v2**, one sentence per failure mode, restating ONLY facts on
  the instruction page (a test checks each fact against the hard instruction). `ablate --hint-set v2 --no-control`.
- In progress: hint ablation v2 on gemini-4-carbon, v1.4 hard, seeds 0–9: arms control / premature_accusation /
  decoy_chase (3 parallel processes, ≈3.5 h) → `data/runs/ablate-v2-hard-gemini/`.
- Next: RL spot check (gemini-4-carbon, hard_rl vs hard, same 6 seeds; `scripts/rl_mole_gemini_spot.py`), then Forge.

## 16:xx status: WS3 merged into justSilas (ded822e)
- Done (verified: `uv run --extra dev --extra llm pytest -q` → 587 passed, 6 skipped)
- **RL mole held-out result** (`scripts/rl_mole_heldout.py`, hard, seeds 200000–200099, n=100, paired bootstrap 95% CI, RL − default):
  - solver score −0.17 [−0.27, −0.08]; solver acc 0.97 → **0.75 [0.67, 0.83]** (meets the constraint in point estimate, CI dips below)
  - grok_tactics −0.21 [−0.29, −0.13]; hinted_heuristic −0.17 [−0.28, −0.07]; heuristic −0.37 [−0.56, −0.18]
  - regret vs grok_tactics +0.04 [−0.09, 0.17]; vs hinted +0.00 [−0.15, 0.14]; vs heuristic +0.20 [−0.00, 0.41]
  - **Honest reading:** the RL mole makes the task harder for everyone (incl. the solver) and stays borderline
    catchable; it does NOT significantly widen the gap to the strongest scripted investigator. Learned behaviour:
    leaks the newest doc 38%, skips 19% of days, frames a colleague ~66% of days (random 29%, restricted 20%, decoy 17%).
- gemini-4-carbon spot check on hard_rl: pending (next).
Lane (per NEXT-LEVEL lane update): WS3 RL mole (with Momin) → Mole Forge on v1.4 hard with Gemini → hint ablations.
The Gemini failure analyst is dropped here (owned by the Gemini CEO's Atlas). gemini-4-carbon headline measurement is the
CEO engineer's; not duplicated.

## 15:xx status
- Done (verified: `uv run --extra dev pytest tests/test_rl_mole.py tests/test_forge_track.py` → 11 passed)
  - `canary/forge/rl_mole.py`: numpy MLP mole (MoleView features → leak selector × frame selector, same vocab as the
    Mole DSL, plugs into `Env(mole_strategy=...)`, samples with the env RNG → deterministic). REINFORCE on
    J = solver − max_k investigator (k ∈ grok_tactics, heuristic, hinted_heuristic; softmax-weighted max), with a
    Lagrange multiplier enforcing solver accuracy ≥ 0.75 (+0.05 margin). Train seeds 100000+, eval seeds 200000+.
  - `hard_rl` judge track (`rules.TRACKS`, `forge_track.hof_path(track)`, own instruction text); loads
    `data/rl_mole/hall_of_fame.jsonl` (rows with an `rl_mole` policy). NOT added to `make reproduce` (CEO's call).
  - `train/grpo_mole.py` (ready for FR8, GPU path untested): prompts = real MoleView snapshots (seed, day) from
    solver episodes; completion = one DSL action JSON; reward = counterfactual replay of solver + 3 investigators with
    that action on day d (regret − 0.5 if the solver misses, −1 if invalid). Backends: plain torch+peft GRPO (default,
    needs only pytorch-volta) or TRL. `--dry-run` verified on CPU: reward varies within 100% of groups.
  - `fr8/grpo_mole.sbatch` (+ `SMOKE=1`), `fr8/grpo_mole_setup.sh` (login node: model download, optional TRL).
- In progress: RL mole training run (150 iters × 64 seeds, Mac CPU) → curve + frozen policies in `data/rl_mole/`.
- For FR8 head: `bash fr8/grpo_mole_setup.sh` on the login node, then `sbatch --export=ALL,SMOKE=1 fr8/grpo_mole.sbatch`,
  then the real run (`SIZE=0.5B STEPS=200`, 1 GPU, 8 CPUs). Untested on GPU.
- For Momin: no overlap found on `momin` (no RL mole there). Proposed split: I own `rl_mole.py`/`hard_rl`; you take the
  Gemini-on-mole side and the GRPO run with FR8. Leave notes in this file.

---
# Previous AGENTS head (history)

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
