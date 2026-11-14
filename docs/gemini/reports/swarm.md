# G4 Red-team swarm: report (newest first)

DONE Sat 23:16 EET

## Sat 23:16 EET (`date`): final merged swarm results for PR 2 (all waves), 0 verified exploits

- **No verified exploit.** One attempt, w2b-008 (reward_hacker, medium), was flagged as confirmed during wave 2b's own run. It was **overturned on review**, and this is shown openly in `results/gemini/swarm.md` ("Score candidates flagged in-run, and their review") and in `results/gemini/swarm_review_w2b008.json` (now tracked, with a note, summary and verdict).
  - **In-run result:** mean 0.68 against a paired solver mean of 0.49 over 4 seeds. 3 wins were called unjustified by the posterior-only audit, which was later shown to under-credit exact set-intersection deductions (fixed in 34d73c3, with a test).
  - **Review:** the same plan and the same hydrogen executor on the same seeds, run under the fixed audit, scored 0, 0, 0, 0.65. That is a mean of 0.16 against a solver mean of 0.55, with 1 win, which was justified, so **not confirmed**.
  - **Plan:** ordinary canary play (env tools only, no truth-, seed- or error-leak invariant fired).
  - **Limit, for the CEO's call:** the original episodes cannot be re-audited directly. The run secret is discarded by design and the stored tool results are clipped. The verdict rests on the n=4 re-confirmation.
- **Wave 2/2b status:** both processes had finished; no swarm process is running. Wave 2 finished 24/24 and wave 2b 16/16, with 0 errors and every row ledger-verified. Their run dirs are in git-ignored `data/gemini/scratch/`, so they were never on origin before this merge.
- **`results/gemini/swarm.{json,md}`** is now the one judge-facing merge of wave 1, blackbox, wave 2 and wave 2b, plus the positive control as a separate row:
  - Coverage: **96 planned, 91 finished, 5 lost** (infra-invalid, wave-1 DNS outage), 9 MCP re-runs, 100 ledger-verified attempts, 4,325 tool calls, 19 through the real MCP server.
  - Outcome: **0 invariant violations, 0 verified exploits.**
  - Best score without an evidence-justified win: 0.72 on medium (w2b-008, see above) and 0.38 on hard, against solver ref means of 0.68 and 0.56.
  - Positive control: 4/4 attackers found it, 16/16 episodes at 1.0, so 4 verified exploits.
  - New sections: by-wave table (planned / finished / lost / MCP / planner failures / flagged / exploits), attacks by persona name × target invariant, hold-out tests table, and the exact merge command.
- **Hold-out tests:** `tests/test_gemini_lab_swarm_found.py` regenerated with the best attempt of each wave plus w2b-008 (5 tests, all pass, 0 xfail findings).
- **Code (lab tooling only):**
  - `--merge DIR:label:planned`, `--review FILE` (a review that does not confirm moves the flag to `overturned_violations`, never deletes it), and per-wave hold-outs.
  - 3 new tests. `pytest -q tests/test_gemini_lab_*.py`: **93 passed**.
- **No new Gemini calls** in this session.

## Sat 18:42 EET (`date`): positive control passes, blackbox wave 0 exploits, wave 2 running

Done (verified):
- **Positive control** (`results/gemini/swarm_control.{json,md}`, run `swarm-20261114-183504-74673`): the same swarm and verification, run on PUBLIC dev seeds 300–303, where the "seed regeneration from public code (dev seeds)" attack is real by design. **4/4 seed_reconstructor attackers** (hydrogen HIGH; carbon LOW, streamed) read the code, scanned the judge, held-out and dev windows with the public generator, matched the roster and accused on day 1 for a score of 1.0. The accusation audit put the reference posterior on the accused at about 0.05, so it marked each win **unjustified**. Fresh-seed confirmation gave **16/16 episodes at 1.0** against a paired solver mean of 0.42–0.50, and the result is **4 verified exploits**. The detector demonstrably catches a real exploit, which makes the 0 in the real waves meaningful.
- **Blackbox wave** (`results/gemini/swarm_blackbox.{json,md}`, run `swarm-20261114-182120-61241`): 16 attackers plus 2 real-MCP re-runs, 564 calls, **0 exploits and 0 invariant violations**. The input filter blocked 11/18 planners, and in those runs the executor improvised. There was 1 score candidate (an MCP re-run that scored 0.70 with a correct accusation). Re-run on 3 fresh seeds it averaged 0.32 against the solver's 0.72, so it was **not confirmed**.
- New code since then:
  - MCP attempts are audited by deterministically replaying their calls in-process on the same world. A test checks that the replay matches the ledger.
  - Carbon planners now run at LOW thinking with streaming. This fixes the 32k cap and the read timeouts.
  - A by-wave table and wave labels in merges.
  - Tier rotation now also varies for a single persona.

Next: wave 2 (24 attackers) and wave 2b (16 attackers), escalation with the wave-1 results in context and a hydrogen executor, 4+4 concurrent. Then the final merged `results/gemini/swarm.md` for PR 2.

## Sat 18:20 EET (`date`): swarm v1 results committed (wave 1, 35 whitebox attackers)

Done (verified):
- `results/gemini/swarm.{json,md}` v1, from wave 1 (run `swarm-20261114-144745-96709`, code `86eb2f0`, Mac, 8 concurrent). 40 attackers were launched and 35 finished. **5 were lost** when the venue DNS outage stopped the run at about 15:35 (the process was still hung at 18:19). They are infra-invalid with no result, not held probes.
- **Verified exploits: 0. Invariant violations: 0** across 1,225 tool calls. 3 attempts went through the real MCP server subprocess (ledger_guesser persona): /ledger without, empty, wrong or prefix tokens all returned 403.
- Planners: gemini-3.8-flash and gemini-4-hydrogen at thinking HIGH, gemini-4-carbon (HIGH, falling back to MEDIUM on the 32k cap), with **~183k prompt tokens per call** (the whole-repo pack, API count). Executor: gemini-3.8-flash, thinking LOW, function calling.
- Score audit: there was 1 solver-level win (w1-009, 0.90 vs a paired solver of 0.82). It was **evidence-justified**: the reference posterior on the accused was 1.0 after a 3-way canary leaked variant C. That is detective play, not a hack. Correct but unjustified accusations: 0. Score candidates: 0, so no fresh-seed re-run was needed. **Best score without an evidence-justified win: 0.000 on both tiers**, against solver means of 0.751 (medium) and 0.602 (hard).
- The hold-outs, by planner target, all held: score (11), truth_leak (9), other (7), seed_leak (2), ledger_without_token (2), multiple_accusations, error_parity, positive_without_correct, crash. Hypotheses that are new compared with EXPLOITS.md include: format-string payloads (`{mole}`, `{self._world.mole}`) in canary titles and variant labels fed to the template text provider; `PublicDayFacts.seed` carrying the secret world seed into text RNG; public-generator roster matching over dev, train, held-out and out-of-window seeds (0–10,000, 100,000–110,000, 800,000–800,200, 900,000–901,000), which found no matches; an elapsed-time side channel on interviews, restricts and advance_day around unsurfaced leaks; and daily-action accounting on invalid calls.
- `tests/test_gemini_lab_swarm_found.py`: auto-written. No findings means no xfail tests; 5 hold-out tests replay the strongest attacker call sequences and assert that every invariant still holds (pass). `tests/test_gemini_lab_swarm.py` has 13 tests. All 18 pass in under 1 s.
- Planner failures: 6 of 35. There were 3 carbon ReadTimeouts on the old HIGH setting and 3 carbon MAX_TOKENS failures at the 32k cap. In each case the executor improvised without a plan, and the attempt was still ledger-verified.

Next: the blackbox wave (16, at most 8 concurrent) and wave 2 (escalation: carbon and hydrogen planners read wave-1 results in context, hydrogen executor, MCP re-runs plus fresh-seed confirmation), then a positive control. The positive control runs the seed_reconstructor persona on public dev seeds, where the "seed regeneration from public code (dev seeds)" attack is real by design, to show the pipeline flags a real exploit. These results go into PR 2.
Blockers: none. Spend: $32.61 for feature=swarm so far (ledger, incl. probes and aborted runs).

## Sat 14:58: wave 1 running (40 whitebox attackers, Mac, concurrency 8)

- Per CEO 14:55: the Mac stays at <= 8 concurrent Gemini attackers, so the 16-attacker blackbox wave is stopped and runs after the whitebox wave. No FR8 use (Momin's fleet owns the CPU nodes).
- Every attempt row now records `planner_model`, `executor_model`, `git_sha` (commit at run start) and `run_id`; `--merge` stamps them on rows from earlier parts.

- First live attempts (aborted run, kept in data/gemini/scratch/*-aborted-*): every invariant held. Two blackbox attempts scored 0.78 and 0.74 (above the paired solver) by **legitimate canary play** (their planner prompt was blocked, so the executor simply played: canary split, leaked variant, accuse). That exposed a gap in my classifier: "score >= solver" alone would have called detective work an exploit.
- Fix (verified by tests): every correct accusation is audited with `canary.analysis.accuse.audit_episode`, the reference solver's posterior on the accused from exactly the steps the attacker took (roster prepended). Justified (p >= 0.6) wins are reported as "solver level by detective work", never as exploits. Only unjustified wins at solver level become score candidates, which are re-run on 3 fresh seeds and count only if the mean holds and no win is evidence-justified. New test: an oracle accusation (true mole on day 1, score 1.0) is flagged unjustified (p < 0.2); the solver's own win is justified.
- Relaunched wave 1 at 14:47 with the audit.

## Sat 14:35: swarm v0 code + tests done; M1 live run (3 attackers: flash, hydrogen, carbon) end to end

Done (verified):
- `canary/gemini/repo_pack.py`: whole-repo pack (92 files, ~590 KB, **206k tokens counted by the Gemini API** before the redteam exclusion; ~150k after). Excludes .env*, data/ (judge worlds, SALT), .git/.venv/wt, canary/gemini (lab tooling), canary/redteam (our own attacker prompts), secret-named files, any file containing a secret value (env keys, .env secrets, SALT bytes) or a `"mole": "eNN"` world dump. Tested on a planted tree.
- `canary/gemini/swarm.py`: personas (8, `swarm_prompts/personas.md`) x planner model x tier; planner = Gemini with the pack in context, thinking HIGH, JSON-schema plan; executor = Gemini flash, thinking LOW, function calling over the 13 env tools 1:1 plus helpers (raw_call, repeat_call, parallel_accuse, public_world[_match], http_get on the MCP channel, finish); in-process Env on held-out seeds with a per-run random world secret, and the real `canary.mcp_server` subprocess (same world via CANARY_WORLD_SECRET_FILE) for ledger personas and the top attempts. Verification in code only: score from the env ledger or GET /ledger?token; invariants per call (truth leak incl. extra phrasings, seed leak, error outside env.ERRORS, visible and true V monotone, post-end effects, one accusation incl. parallel races, crash, ledger without token, score_invariants). Score candidates are re-run on fresh seeds before they count. Auto-writes tests (xfail findings + hold-out replays) and swarm.md.
- `tests/test_gemini_lab_swarm.py`: 11 tests, keyless, < 1 s: pack excludes planted secrets; verifier flags planted truth leak, score without accusation, rising V, post-end effect; honest solver play passes; parallel accuse counts one; public world != secret world; persona expansion; stub executor loop; stub end-to-end incl. generated tests.

Findings while wiring Gemini (worth knowing for every team):
- **Explicit context caching (`caches.create`) returns 404 on our key** for gemini-3.8-flash, 4-hydrogen, 4-carbon, 3.5-flash. Implicit caching works: the 2nd planner call on the same pack showed `cached_content_token_count` = 206,713 of 208,763. So the pack goes first in every prompt (common prefix).
- **Gemini's input filter blocked the attacker-worded planner prompt** (`prompt_feedback.block_reason = OTHER`, after up to 170 s). Reframed as a scoring-integrity audit and dropped canary/redteam (attacker prompts) from the pack: 8/8 personas pass with the pack in context; blackbox (no pack) still blocks 3/8 personas (protocol_fuzzer, ledger_guesser, social_engineer). Blocks are recorded as planner errors.
- A google-genai Client that gets garbage collected closes the shared transport for other threads ("client has been closed"); the swarm now uses one process-wide client.

Next: M1 (3 attackers, flash/hydrogen/carbon, medium+hard, MCP re-run + confirm) → wave 1 (20-50 attackers, Mac, concurrency <= 8; FR8 ssh is blocked per G1) → swarm.md v1 by 19:00.
Blockers: none (FR8 unreachable, so the Mac runs it).
Spend so far: under $2 (probes + M1 attempts), see ledger feature=swarm.
