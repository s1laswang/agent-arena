# NEXT LEVEL: Saturday briefs (CEO, Sat 14 Nov ~12:30)

Read docs/agents/COMMON.md first (git, secrets, FR8 rules, reporting). They still apply, with these updates:
- **The OpenAI key is removed.** Never use OpenAI or Codex. **Gemini has no spend limit**: use `gemini-4-carbon` for any frontier-agent run (smaller Gemini models only for cheap smoke tests).
- **Rules are frozen at v1.4** (8f87ed1; `rules.TIERS_VERSION`). v1.3 stays reproducible via `rules.tiers_version("v1.3")`. Any rules change goes on a branch and merges only on CEO + Silas approval.
- **Time comes from `date`**, never estimated.
- A Gemini measurement engineer (CEO subagent, branch `justSilas-gemini`) is ALREADY running gemini-4-carbon on v1.3 and v1.4 (OpenCode over MCP + in-process). Don't duplicate it; build on its runs in `data/runs/committed/`.

## Where we stand (Grok bake-off 2, judged ~10:00, before the latest work)
Canary 70, Poisoned Inbox 64, Blind Spot 61, Sleeper 51 → **ship Canary**. Canary's deductions:
- **Gap 12/30:** no consistent frontier gap in the judges' harness. Since then: official v1.3, Codex gpt-5.5 over MCP, n=11+11 = **medium 55% [−8, 104], hard 106% [91, 136]**. v1.4 hard is now frozen; the gemini-4-carbon measurement is the decisive next number.
- **Difficulty 23/30:** failure tags came from the truncated scaffold. Since then: the regret for the full-history Codex runs is committed; premature accusation is ~97% of tagged loss; **no frontier episode ever abstained.**
- **Integrity 22/25:** Harbor isolation was linted but not booted in Docker by the judge; `CANARY_SEED` can still sit in a non-Harbor server's environment.
- **Craft 13/15:** OpenCode rows average `valid:false` infra failures into the mean; the README band missed one cell.
- **Gemini:** not on the judged path; nothing ran with a key (now a key exists).

## The next-level thesis
Every frontier agent we measured shares one robust, explainable failure: **it never says "I don't know".** It accuses at P = 0.18–0.45 when the instructions show abstaining (score 0) beats a likely −1. Our solver abstains rationally. The next level is to make **calibrated commitment** the measured skill, while keeping every rule written down:
1. Show it with **three frontier families** (gpt-5.5, Grok, gemini-4-carbon), in the judges' harness.
2. Prove each decision matters with a **skill ladder** (solver ablations).
3. Put **Gemini on the judged and analysis path** (frontier agent, failure analyst, evolved moles).
4. Make the **small model gain reward**, not just behaviour.

---

## HEAD-ENV (relaunch): branch `justSilas-env2`
1. **Skill ladder** (difficulty evidence, the Poisoned Inbox idea): `scripts/skill_ladder.py`, solver variants each missing ONE component:
   - no EV accusation rule (accuse at the argmax on the last day / at a fixed P);
   - no careful-mole model;
   - no delay model;
   - single-canary planning on v1.4 hard;
   - no decoy marginalisation;
   - no framing model.

   On fresh seeds (n≥400 per tier, v1.4), the table goes in `results/skill_ladder_v1.4.md` plus a chart. Every rung should cost score; report any that doesn't.
2. **v1.5 candidate, "dormant mole" knob (branch only, DO NOT merge)**: with documented probability q (e.g. 0.25–0.35) the mole is cautious and leaks with a lower p_leak (e.g. 0.3), stated plainly in the instructions. Then by the horizon the evidence is often insufficient, and the right play is to wait or abstain. Calibrate on dev seeds: solver accuracy ≥ 85% on accused episodes; solver mean still > grok_tactics/heuristic; the fraction of episodes where the solver abstains. Report the numbers; the CEO decides after the gemini-4-carbon v1.4 result (~17:00) whether v1.5 ships.
3. Keep the freeze tests, determinism and `make hunt` green. Merge only the ladder (not v1.5) to justSilas.

## HEAD-AGENTS (relaunch): branch `justSilas-agents2`
1. **Gemini failure analyst (the prize-critical use that doesn't depend on the model failing):**
   - `canary/agents/analyst.py` runs gemini-4-carbon over ALL committed frontier transcripts (v1.2, v1.3, v1.4, every model), plus the regret tags, plus the solver's posterior at each accusation;
   - it produces `docs/reports/failure_gallery.md`: clustered failure modes with counts, and one annotated trajectory per mode (day, action, posterior, what the solver did instead);
   - cache the Gemini responses in the repo (`data/gemini_cache/`) so `make analyst` replays offline;
   - every quote must come from a real transcript.
2. **Mole Forge with Gemini on v1.4 hard:**
   - mutator = gemini-4-carbon;
   - investigators = grok_tactics + heuristic + a few gemini-4-carbon episodes as the spot check;
   - fitness = regret vs the strongest investigator, subject to solver accuracy ≥ 0.75;
   - validate the top moles against gemini-4-carbon on the same seeds;
   - claim "harder for frontier agents" ONLY if the data shows it;
   - save the evolution log for a "generations" chart.
3. **Hint ablation with Gemini:** one sentence per failure mode (e.g. "Accusing below the break-even probability has negative expected value; abstaining scores 0"). Show the matching tag drops on gemini-4-carbon (≥10 episodes per hint, v1.4 hard). That's causal evidence that the information suffices.
4. Update `pitch/GEMINI.md` with REAL runs only (model id, n, what Gemini did).

## HEAD-INTEGRITY (relaunch): branch `justSilas-integrity2`
1. **Gemini exploit hunter:**
   - gemini-4-carbon told "maximise reward by any means" against the real MCP server, black-box (no repo source) and white-box (with source, in a sandboxed temp dir), on v1.4;
   - log every attempt to `data/runs/redteam-gemini-*`;
   - add EXPLOITS rows plus regression tests.
2. **Close the bake-off's integrity notes:**
   - non-Harbor launches must not put the seed in the server's environment by default: use `CANARY_EPISODE_FILE` in `make mcp`/configs and update the README;
   - add a test.
3. **Re-run the full hunt on v1.4** (all modes, a long budget) and the property tests.
4. Check that the OpenCode `valid:false` filtering (HARNESS) can't hide real agent failures. Invalid must mean infra only, with evidence.

## HEAD-HARNESS (relaunch; the previous session is stuck): branch `justSilas-harness2`
1. **Boot Harbor for real:**
   - colima (small: 2 CPU / 3 GB; stop it afterwards) → `harbor run` on one medium AND one hard v1.4 judge task: oracle (expect the solver score), `ORACLE_POLICY=do_nothing` (0), `ORACLE_POLICY=stop_early` (≈−1);
   - run `harbor/check_isolation.sh` inside `main`;
   - commit the logs and outputs to `results/harbor/` and summarise them in `harbor/README.md`. Judges can't see this today.
2. **Reproduce table fix:**
   - drop `valid:false` episodes from the reported-run means (show them as a separate `invalid n` column, with reasons);
   - add a test.
3. **Then the gemini-4-carbon Harbor run:** `harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon` on 3 hard + 3 medium v1.4 tasks (OpenCode reads GEMINI_API_KEY from the host env). This is the exact judge path with a real frontier model. Commit the results.
4. **Before submission:** rerun `scripts/repro_spread.py 30` on the final commit and refresh the README band; a fresh-clone check; CI green.

## FR8 (live session; the CEO messages it directly)
Small-model v2 when a V100 frees up (Silas's sky array ends ~18:30): dense 4k windows + `--oversample-endings 3` on the J3 v2 data, a FAST eval (a KV-cached loop, or capped calls) with n ≥ 30 per tier. The goal is a REWARD gain on held-out seeds.
