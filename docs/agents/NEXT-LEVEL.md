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
0. **ANTI-CHEAT PORT (top priority; the human owner is Vaishnav, so coordinate with him).** Port Poisoned Inbox's anti-cheat system into Canary. Read `git show origin/vaishnav/poisoned-inbox:docs/EXPLOITS.md` and `pinbox/eval.py` (`run_probes`, `SCRIPTED_ALWAYS_ZERO`, `run_recorded`/replay), `tests/test_eval.py`, and `harbor/template/solution/` (the `cheat` solution).
   - **Probes in the one command:** `make reproduce` also runs an anti-cheat probe battery on the judge seeds and prints a table (probe → mean score → blocked yes/no), written to `results/latest/exploits.json` and to the committed results on update. Probes: do_nothing; stop_early; random; restrict_all; probe_all; accuse_decoy; accuse_most_logs; malformed/garbage args on every tool; repeated and parallel accuse; accuse after the end; canary with one variant per person (should be rejected by max_variants); calls past the cap; plus a **control** = the solver, then pad every remaining call with reads, which must still score the solver's score. Add `tests/test_anticheat.py`: it fails if any attack probe's mean > 0 or the control drifts from the solver.
   - **Stop-early ladder:** the solver cut at 25/50/75% of its calls, and "solver minus its final accuse". Every one must score exactly 0 (no accusation means 0). That is the rubric's "stopping early earns ~0", demonstrated on the reference itself.
   - **Replay consistency:** every committed episode under data/runs/committed is re-played on a fresh Env (same tier version, seed, secret where applicable; judge-seed external runs flagged as not-replayable) and re-graded; reproduce shows `replay_consistent` per row, and a test fails on any mismatch.
   - **Harbor cheat solution:** `ORACLE_POLICY=cheat` in harbor/ tries to write /logs/verifier/reward.txt, leave a background process that rewrites it, call /ledger and /admin without a token, read server files, and accuse several ids. It must score 0 in a real `harbor run` (coordinate with HARNESS, which has colima up). Commit the log. HARNESS's exact run command (colima: `colima start --cpu 2 --memory 3` if it's down; harbor/dataset-*/ is gitignored because it holds the build SALT):
     `uv run --python 3.12 python harbor/build.py --tiers medium,hard --seeds 900000 --out harbor/dataset-cheat`
     `harbor run -p harbor/dataset-cheat -a oracle --ae ORACLE_POLICY=cheat -n 1 -o results/harbor --job-name cheat`
     Already verified by HARNESS on v1.4 (results/harbor/): oracle medium 0.78 / hard 0.66 (= in-process solver), do_nothing 0/0, stop_early −1/−1, check_isolation 11/11 OK.
   - **Grader hardening checks:** a grader exception counts as a failure (never as a pass); tool results are detached copies; identical runs across PYTHONHASHSEED values. Add tests for any that are missing.
   - Document everything in docs/EXPLOITS.md under "Anti-cheat battery (runs in make reproduce)".
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
   - dedupe per (agent, tier, version, seed), keeping the newest run, and warn when n ≠ the number of distinct seeds (the Codex smoke double count is already fixed by moving that run to superseded/);
   - add tests for both.
3. **Then the gemini-4-carbon Harbor run:** `harbor run -p harbor/dataset -a opencode -m google/gemini-4-carbon` on 3 hard + 3 medium v1.4 tasks (OpenCode reads GEMINI_API_KEY from the host env). This is the exact judge path with a real frontier model. Commit the results.
4. **Before submission:** rerun `scripts/repro_spread.py 30` on the final commit and refresh the README band; a fresh-clone check; CI green.

## FR8 (live session; the CEO messages it directly)
Small-model v2 when a V100 frees up (Silas's sky array ends ~18:30): dense 4k windows + `--oversample-endings 3` on the J3 v2 data, a FAST eval (a KV-cached loop, or capped calls) with n ≥ 30 per tier. The goal is a REWARD gain on held-out seeds.

---

# PLAN v3 additions (CEO, after the 14 Nov team brainstorm)
Read the team-facing summary `docs/IDEAS.md` and the notes `docs/meetings/2026-11-14-mole-company-simulation.md`. Team decisions:
- Canary is the base;
- Vaishnav's anti-cheat goes in;
- Momin's strongest parts go in;
- biased, human-like employees;
- an RL-trained mole;
- Gemini on the mole/poison side;
- a video + a "beat the AI" browser game.

Silas's calls:
- Momin pauses the sky jobs (GPUs free for training);
- the bias layer is a **v1.5 candidate, gated**;
- RL mole: **both, light first**;
- game: a **static browser game (Pyodide)**.

Gates:
- **A, 17:00:** gemini-4-carbon v1.4 headline (n ≥ 20 per tier); v1.5 solver numbers; first RL-mole curve.
- **B, 20:00:** ship or drop v1.5 (the gemini-4-carbon frontier/solver ratio must DROP vs v1.4, and integrity must stay clean); then the feature freeze.

## WS2: human-bias social layer, v1.5 candidate (HEAD-ENV; research grounding from Ivar)
Branch `justSilas-v15`. This replaces the "dormant mole" idea as the v1.5 candidate; keep the dormant-mole knob only if it's already built.
- New TierParams knobs (default OFF; TIERS_V14 and its hash untouched), every number stated in the instructions:
  - **Rumours:** each day, Poisson(r) messages in which an employee speculates that a colleague is the mole. Accused colleagues are chosen uniformly among non-mole employees, plus a share s_frame chosen by the mole (see below). The instructions state the exact likelihood, so a rational investigator knows how much a rumour is worth: nearly nothing.
  - **Grudge pairs:** k pairs of innocent employees who repeatedly accuse each other (a stated pattern).
  - **Authority bias:** a manager posts one confident, documented-as-unverified accusation (target uniform among innocents, or the framed target).
  - **Miscommunication:** with probability m, a regular document is also forwarded to one unplanned recipient. The forward IS visible in `list_documents` (so it's fair) but easy to miss.
  - **Mole exploitation:** a new Mole DSL action `seed_rumour(target)` (the decoy / the most-restricted peer / a random peer), which raises that target's rumour share.
- **Solver:** model the rumours/authority/forwards exactly from the stated likelihoods (they should barely move its belief), and keep it deterministic.
- **TextProvider:** the template renders these messages from labels. The Gemini provider (gemini-4-carbon) writes realistic biased chatter from the same labels, never seeing the truth. Cache it in `data/gemini_cache/` for offline replay.
- **Calibrate** on fresh seeds (Mac, ≤6 processes):
  - the solver stays ≥ 85% accurate on medium and hard;
  - the solver is still clearly above grok_tactics and heuristic;
  - `make hunt` is clean.

  Report `results/fresh_table_v1.5-candidate.md` by ~17:00.
- At Gate B the CEO runs a gemini-4-carbon spot check on v1.5 hard (10 episodes, OpenCode). Merge to justSilas ONLY on the CEO's go.

## WS3: RL-trained mole (HEAD-AGENTS + Momin; FR8 for the GPUs)
- **Light (CPU, now):** `canary/forge/rl_mole.py`, a small MLP policy over MoleView features → DSL actions (leak choice, go quiet, frame/seed_rumour), trained with REINFORCE/PPO. Reward = solver-relative regret against the strongest investigator in {solver, grok_tactics, heuristic}, **subject to solver accuracy ≥ 0.75 on that mole** (hard constraint, so the mole stays catchable). Commit the learning curve and the frozen policies (`data/rl_mole/`). Add a `hard_rl` judge track that loads them, like `hard_forge`. Spot check the best mole against gemini-4-carbon (≥5 episodes) and report honestly.
- **LLM mole (GPU, after Momin pauses sky):** with FR8, `train/grpo_mole.py`: a Qwen2.5-0.5B (then 1.5B) mole prompted with the MoleView, outputting a DSL action, trained with TRL GRPO in fp16 on V100s against the same reward (environment rollouts on CPU workers). Report the reward curve and the catchability check. Labels: REAL small model, scripted investigators.
- Coordinate with Momin, who owns this workstream; his Sleeper runners and Gemini mole code are on branch `momin`.

## WS6: browser game + video (Ivar owns; HARNESS engineer + Grok site bot build)
- `game/`: a static page that loads the real `canary` package in **Pyodide** (pure Python + numpy; check every import works in Pyodide) and plays a **medium dev-seed** episode (seeds ≥ 3000, never judge seeds):
  - one button or form per tool;
  - a day counter, the known V, the leak feed, canary assignment with drag/drop or checkboxes;
  - at the end: the player's score vs the solver's vs gemini-4-carbon's on the SAME seed (precomputed JSON from committed runs; replay the solver in-browser if fast enough);
  - must be finishable in ~10 minutes;
  - deploy to GitHub Pages or Vercel;
  - a test: the same seed and the same actions in the browser and in Python give the identical score.
- **Video script (≤ 10 min)**, owned by Ivar with Silas:
  1. hook: insider threats; a company bleeding to zero (Nokia/Yahoo framing plus real insider-leak cases from `docs/research-biases.md`);
  2. the game;
  3. a live replay of solver vs gemini-4-carbon with the "Fooled" moment (Momin's dashboard idea + the Grok viewer/site);
  4. the gap and the failure modes;
  5. anti-cheat;
  6. the trained small model and the RL mole;
  7. the game link.
